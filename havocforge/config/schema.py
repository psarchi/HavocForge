from __future__ import annotations

from typing import Any, Dict, List, Optional, Type, Annotated
from typing import Literal as _Literal
from pydantic import BaseModel, Field, ConfigDict, create_model
from havocforge.config.utils import (
    normalize_declared_type,
    pytype_for_declared,
    _safe_field_name,
)
from havocforge.config.errors import ConfigSchemaError, MetaKindError


class MetaNode(BaseModel):
    """Normalized, typed node used to describe configuration schemas.

    Each node represents either a scalar, array, object, or group. The tree is
    produced by :func:`build_meta_tree` from a loose schema payload and later
    used to synthesize Pydantic runtime models.

    Attributes:
        kind (str): One of ``'scalar'``, ``'array'``, ``'object'``, ``'group'``.
        declared_type (Optional[str]): Original type string (e.g. ``"int"``,
            ``"array"``) after normalization.
        description (Optional[str]): Human‑readable description from schema.
        constraints (Optional[Dict[str, float]]): Numeric bounds (``ge``,
            ``gt``, ``le``, ``lt``) if applicable.
        choices (Optional[List[Any]]): Enumerated allowed values for scalars.
        item_schema (Optional[MetaNode]): Item node for arrays.
        properties (Optional[Dict[str, MetaNode]]): Properties for objects.
        required (Optional[List[str]]): Required property names for objects.
        additionalProperties (Optional[bool]): Whether extra props are allowed.
        children (Optional[Dict[str, MetaNode]]): Members for groups.
        default_value (Any): Default literal or structured default for the
            node.
    """

    model_config = ConfigDict(extra="allow")
    # TODO(config): Revisit extra=allow
    kind: str  # 'scalar' | 'array' | 'object' | 'group'
    declared_type: Optional[str] = None
    description: Optional[str] = None
    constraints: Optional[Dict[str, float]] = None
    choices: Optional[List[Any]] = None
    item_schema: Optional["MetaNode"] = None  # arrays
    properties: Optional[Dict[str, "MetaNode"]] = None  # objects
    required: Optional[List[str]] = None
    additionalProperties: Optional[bool] = None
    children: Optional[Dict[str, "MetaNode"]] = None  # groups
    default_value: Any = None  # for leaf/object defaults


MetaNode.model_rebuild()


def build_meta_tree(root_payload: Dict[str, Any]) -> MetaNode:
    """Convert a loose schema payload into a :class:`MetaNode` tree.

    The input is a nested dict describing types, constraints, choices, and
    defaults in a permissive format. This function normalizes it into a typed
    meta tree that downstream builders can consume.

    Args:
        root_payload (Dict[str, Any]): Raw schema mapping for the root.

    Returns:
        MetaNode: The root meta node of kind ``'group'``.
    """

    def convert(node: Any) -> MetaNode:
        if isinstance(node, dict):
            t = normalize_declared_type(node.get("type"))
            # group
            if t == "group" or (
                "value" not in node
                and (
                    "properties" in node
                    or any(isinstance(v, dict) for v in node.values())
                )
                and "items" not in node
            ):
                children: Dict[str, MetaNode] = {}
                for k, v in node.items():
                    if k in {"type", "description"}:
                        continue
                    if isinstance(v, dict):
                        children[k] = convert(v)
                return MetaNode(
                    kind="group",
                    declared_type=t,
                    description=node.get("description"),
                    children=children or None,
                )
            # array
            if t in ("array", "list"):
                item_node = None
                if "items" in node and isinstance(node["items"], dict):
                    item_node = convert(node["items"])
                return MetaNode(
                    kind="array",
                    declared_type=t,
                    description=node.get("description"),
                    constraints=node.get("constraints"),
                    choices=node.get("choices"),
                    item_schema=item_node,
                    default_value=node.get("value"),
                )
            # object/dict
            if t in ("object", "dict"):
                props: Dict[str, MetaNode] = {}
                req = node.get("required") or []
                if "properties" in node and isinstance(node["properties"], dict):
                    for pk, pv in node["properties"].items():
                        if isinstance(pv, dict):
                            props[pk] = convert(pv)
                return MetaNode(
                    kind="object",
                    declared_type=t,
                    description=node.get("description"),
                    properties=props or None,
                    required=req or None,
                    additionalProperties=bool(node.get("additionalProperties", False)),
                    default_value=node.get("value"),
                )
            # scalar
            return MetaNode(
                kind="scalar",
                declared_type=t or "string",
                description=node.get("description"),
                constraints=node.get("constraints"),
                choices=node.get("choices"),
                default_value=node.get("value"),
            )
        # raw literal
        return MetaNode(kind="scalar", declared_type=None, default_value=node)

    return convert({"type": "group", **root_payload})


def _scalar_type(meta: MetaNode) -> Any:
    """Build a runtime type for a scalar node.

    Applies ``choices`` via ``typing.Literal`` and numeric ``constraints`` via
    ``typing_extensions.Annotated`` with a Pydantic ``Field``.

    Args:
        meta (MetaNode): Scalar meta node.

    Returns:
        Any: A typing type suitable for Pydantic field declaration.
    """
    base_py = pytype_for_declared(meta.declared_type or "string")
    if meta.choices:
        try:
            lit = _Literal[tuple(meta.choices)]  # type: ignore[valid-type]
        except TypeError:
            lit = _Literal[tuple(str(x) for x in meta.choices)]
        base_py = lit
    field_kwargs = {}
    if meta.constraints:
        for k in ("ge", "gt", "le", "lt"):
            if k in meta.constraints:
                field_kwargs[k] = meta.constraints[k]
    if field_kwargs:
        base_py = Annotated[base_py, Field(**field_kwargs)]  # type: ignore[arg-type]
    return base_py


def _array_type(meta: MetaNode) -> Any:
    """Build a runtime type for an array node.

    Args:
        meta (MetaNode): Array meta node with ``item_schema``.

    Returns:
        Any: ``List[item_type]`` typing annotation.
    """
    item_meta = meta.item_schema or MetaNode(kind="scalar", declared_type="string")
    item_t = _dispatch_type(item_meta)
    from typing import List as _List

    return _List[item_t]  # type: ignore[valid-type]


def _object_type(meta: MetaNode) -> Any:
    """Build a dynamic Pydantic model for an object node.

    Creates a model with fields from ``properties``, honoring ``required`` and
    ``default_value`` on each property, and forbids extra fields.

    Args:
        meta (MetaNode): Object meta node.

    Returns:
        Any: A generated Pydantic ``BaseModel`` subclass.
    """
    fields: Dict[str, tuple[Any, Any]] = {}
    if meta.properties:
        for prop, pmeta in meta.properties.items():
            fname, alias = _safe_field_name(prop)
            ftype = _dispatch_type(pmeta)
            required = meta.required or []
            default = (
                ...
                if prop in required and pmeta.default_value is None
                else pmeta.default_value
            )
            if alias:
                fields[fname] = (ftype, Field(default, alias=alias))
            else:
                fields[fname] = (ftype, default)
    model_name = "Obj_" + hex(id(meta))[-6:]
    model = create_model(  # type: ignore[call-overload]
        model_name,
        __config__=ConfigDict(
            populate_by_name=True, extra="forbid", validate_assignment=True
        ),
        **fields,
    )
    return model


def _build_group_model(meta: MetaNode, *, model_name: str) -> Type[BaseModel]:
    """Build a Pydantic model from a *group* meta node with a given name.

    Args:
        meta (MetaNode): Must be ``kind == 'group'``.
        model_name (str): Class name for the generated model.

    Returns:
        Type[BaseModel]: Generated model class with children as fields.

    Raises:
        MetaKindError: If ``meta.kind`` is not ``'group'``.
    """
    if meta.kind != "group":
        raise MetaKindError("meta must be kind='group'")

    fields: Dict[str, tuple[Any, Any]] = {}
    if meta.children:
        for key, child in meta.children.items():
            fname, alias = _safe_field_name(key)
            ftype = _dispatch_type(child)
            default = _runtime_default_from_meta(child)
            fields[fname] = (
                (ftype, Field(default, alias=alias)) if alias else (ftype, default)
            )

    return create_model(  # type: ignore[call-overload]
        model_name,
        __config__=ConfigDict(
            populate_by_name=True, extra="forbid", validate_assignment=True
        ),
        **fields,
    )


def _group_type(meta: MetaNode) -> Type[BaseModel]:
    """Build a dynamic Pydantic model for a group node.

    Thin wrapper around :func:`_build_group_model` used when a nested ``group``
    appears inside the schema.
    """
    model_name = "Grp_" + hex(id(meta))[-6:]
    return _build_group_model(meta, model_name=model_name)


def _dispatch_type(meta: MetaNode) -> Any:
    """Dispatch to the appropriate runtime type builder for ``meta.kind``."""
    k = meta.kind
    if k == "scalar":
        return _scalar_type(meta)
    if k == "array":
        return _array_type(meta)
    if k == "object":
        return _object_type(meta)
    if k == "group":
        return _group_type(meta)
    raise ConfigSchemaError(f"unknown meta.kind: {k!r}")


def _runtime_default_from_meta(meta: MetaNode) -> Any:
    """Compute a default runtime value for a meta node.

    Scalars/arrays/objects use ``default_value`` directly; groups are
    instantiated to empty models when possible.

    Args:
        meta (MetaNode): Meta node.

    Returns:
        Any: Default value appropriate for the node kind.
    """
    if meta.kind in ("scalar", "array", "object"):
        return meta.default_value
    if meta.kind == "group":
        model = _dispatch_type(meta)
        try:
            return model()
        except Exception:
            return None
    return None


def build_runtime_model(root_name: str, meta_root: MetaNode) -> Type[BaseModel]:
    """Generate the top-level Pydantic model for a configuration root.

    Delegates to :func:`_build_group_model` after asserting ``meta_root`` is a
    group and uses a deterministic class name ``Config_{root_name}``.

    Args:
        root_name (str): Canonical root name used in the model class name.
        meta_root (MetaNode): Root meta node; must be of kind ``'group'``.

    Returns:
        Type[BaseModel]: The generated Pydantic model class.

    Raises:
        MetaKindError: If ``meta_root.kind`` is not ``'group'``.
    """
    if meta_root.kind != "group":
        raise MetaKindError("root meta must be a group")
    return _build_group_model(meta_root, model_name=f"Config_{root_name}")
