from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from redis.exceptions import RedisError

from havocforge.context import GenContext
from havocforge.schema.registry import SchemaRegistry
from havocforge.errors import ContextError, PoolEmptyError, SchemaConfigError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import (
    InvalidParameterError,
    MissingChildError,
    InvalidSchemaNameError
)
from havocforge.registry import Registry

logger = logging.getLogger(__name__)

# Errors that are expected during cross-schema correlation lookups: transient
# Redis hiccups, malformed cached payloads. Anything outside this set indicates
# a programming bug and should propagate so it's noticed.
_CORRELATION_LOOKUP_ERRORS = (RedisError, json.JSONDecodeError, ValueError)


if TYPE_CHECKING:  # avoid import cycles at runtime
    from havocforge.contracts.types import JsonValue  # noqa : F401


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class ObjectGenerator(BaseGenerator):
    """Generate an object with fields produced by child generators.

    Args:
        fields (dict[str, BaseGenerator] | None): Mapping of field name to child generator.
    """

    __meta__ = {
        "aliases": {"fields": "fields", "properties": "fields"},
        "deprecations": [],
        "rules": [],
    }
    __slots__ = ("_built", "_meta", "_field_configs", "_anchor_map", "_pool_anchor", "_pool_siblings", "_depends_on_pool_map")
    __aliases__ = ("object",)

    def __init__(self, fields: dict[str, BaseGenerator] | None = None) -> None:
        """Initialize with an optional mapping of field generators."""
        self._built: dict[str, BaseGenerator] = fields or {}
        # Field metadata: {field_name: {"required": bool, "default": Any}}
        self._meta: dict[str, dict[str, Any]] = {}
        # Cached field configurations for fast lookup during generation
        self._field_configs: dict[str, dict[str, Any]] = {}
        # anchor_field → [correlated_field_names], built at scan time
        self._anchor_map: dict[str, list[str]] = {}
        # pool anchor field name (or None if this schema doesn't feed a pool)
        self._pool_anchor: str | None = None
        # sibling field names to store alongside the anchor in the pool record
        self._pool_siblings: list[str] = []
        # field_name → source_schema_name for fields that read from an external pool
        self._depends_on_pool_map: dict[str, str] = {}

    # TODO(arch): depend on a builder/factory *protocol* instead of a concrete object
    @classmethod
    def from_spec(
        cls,
        builder: Any,
        spec: Mapping[str, object],
    ) -> "ObjectGenerator":
        """Construct an instance from a generator specification.

        The spec must provide field definitions under ``fields`` (preferred) or
        ``properties``. Each field item may be either a nested spec (built as-is),
        or a mapping with an ``of`` key indicating the child generator spec plus
        optional ``required`` and ``default`` hints.

        Args:
            builder (Any): Object exposing ``build(spec: Mapping[str, object]) -> BaseGenerator``.
            spec (Mapping[str, object]): Parsed generator specification.

        Returns:
            ObjectGenerator: Configured instance.

        Raises:
            MissingChildError: No ``fields``/``properties`` block present or empty.
        """
        fields_block = spec.get("fields") or spec.get("properties")
        if not fields_block or not isinstance(fields_block, dict):
            built: dict[str, Any] = {}
            meta: dict[str, Any] = {}
        else:
            built = {}
            meta = {}
            for field_name, field_spec in fields_block.items():
                if isinstance(field_spec, dict) and "of" in field_spec:
                    child_spec = field_spec.get("of")
                    child = builder.build(child_spec)
                    meta[field_name] = {
                        "required": bool(field_spec.get("required")),
                        "default": field_spec.get("default", None),
                    }
                else:
                    child = builder.build(field_spec)
                    meta[field_name] = {"required": False, "default": None}
                built[field_name] = child

        instance = cls(fields=built)
        instance._meta = meta
        instance._build_field_configs()
        return instance

    def _sanity_check(self, ctx: GenContext) -> None:
        """Validate context and that at least one field is configured.

        Args:
            ctx (GenContext): Execution context.

        Raises:
            ContextError: If ``ctx`` is not a ``GenContext``.
            MissingChildError: If no fields are configured.
        """
        if not isinstance(ctx, GenContext):
            raise ContextError("ctx must be an instance of GenContext")
        if not self._built:
            raise MissingChildError("object has no fields")

    def configure(
        self,
        *,
        fields: dict[str, BaseGenerator] | None = None,
        **_: Any,
    ) -> "ObjectGenerator":
        """Update configuration and return ``self``.

        Args:
            fields (dict[str, BaseGenerator] | None): Replacement field map.
            **_ (Any): Ignored extra kwargs for forward-compatibility.

        Returns:
            ObjectGenerator: ``self`` for chaining.
        """
        if fields is not None:
            self._built = fields
            self._build_field_configs()
        return self

    def _build_field_configs(self) -> None:
        """Precompute field configurations for fast lookup during generation."""
        self._field_configs = {}
        self._anchor_map = {}
        self._pool_anchor = None
        self._pool_siblings = []
        self._depends_on_pool_map = {}
        for field_name, child_gen in self._built.items():
            field_meta = self._meta.get(field_name, {})
            bound_to = getattr(child_gen, "bound_to", None)
            bound_to_schema = getattr(child_gen, "bound_to_schema", None)
            bound_to_revision = getattr(child_gen, "bound_to_revision", None)
            self._field_configs[field_name] = {
                "is_required": bool(field_meta.get("required")),
                "default_value": field_meta.get("default", None),
                "depends": getattr(child_gen, "depends_on", None),
                "bound_to": bound_to,
                "bound_to_schema": bound_to_schema,
                "bound_to_revision": bound_to_revision,
                "child_gen": child_gen,
            }
            if bound_to and bound_to_schema is None:
                self._anchor_map.setdefault(bound_to, []).append(field_name)

            pool_cfg = getattr(child_gen, "pool", None)
            if pool_cfg is not None:
                self._pool_anchor = field_name
                if pool_cfg is True:
                    self._pool_siblings = []
                else:
                    self._pool_siblings = list(pool_cfg)

            source = getattr(child_gen, "depends_on_pool", None)
            if source:
                self._depends_on_pool_map[field_name] = source

    def _value_checker(self, value, default_value, is_required, field_name):
        """Check and apply defaults/required validation for a field value."""
        if value is None:
            if default_value is not None:
                value = default_value
            elif is_required:
                # TODO(errors): consider a more specific error (e.g., RequiredFieldMissingError)
                raise InvalidParameterError(
                    f"required field '{field_name}' generated None"
                )
        return value

    def _generate_impl(self, ctx: GenContext) -> dict[str, "JsonValue"]:
        """Produce an object with values from each child generator.

        Args:
            ctx (GenContext): Execution context providing RNG/state.

        Returns:
            dict[str, JsonValue]: Field values; defaults applied when child returns ``None``.

        Raises:
            InvalidParameterError: A required field generated ``None`` and no default was provided.
        """
        self._sanity_check(ctx)
        # Reset per-record pool cache so each record independently samples the pool
        ctx._pool_cache = {}
        output: dict[str, Any] = {}
        depends_on = []
        # corr_data: {anchor_field: {field_name: cached_value}} fetched from Redis
        corr_data: dict[str, dict[str, Any]] = {}
        # track which anchors were a MISS so we write them after generation
        corr_miss: set[str] = set()

        correlation_client = getattr(ctx, "_correlation_client", None)
        _schema_name = getattr(ctx, "schema_name", None)
        if not _schema_name and correlation_client is not None:
            raise InvalidSchemaNameError
        _schema_ver = (
            SchemaRegistry.get_revision(SchemaRegistry.get_latest_name(_schema_name))
            if correlation_client is not None
            else None
        )

        # Use cached field configs for fast lookup
        for field_name, config in self._field_configs.items():
            depends = config["depends"]
            bound_to = config["bound_to"]

            # Pool consumer: field value comes from an external pool record
            if field_name in self._depends_on_pool_map:
                source_schema = self._depends_on_pool_map[field_name]
                if source_schema not in ctx._pool_cache:
                    pool_key = f"pool:{source_schema}"
                    raw = correlation_client.srandmember(pool_key) if correlation_client else None
                    if raw is None:
                        raise PoolEmptyError(
                            f"Pool '{pool_key}' is empty. "
                            f"Generate '{source_schema}' records before '{ctx.schema_name}'."
                        )
                    ctx._pool_cache[source_schema] = json.loads(raw)
                record = ctx._pool_cache[source_schema]
                if field_name not in record:
                    raise SchemaConfigError(
                        f"Field '{field_name}' not found in pool record for '{source_schema}'. "
                        f"Add '{field_name}' to pool list in {source_schema}.yaml."
                    )
                output[field_name] = record[field_name]
                continue

            if depends and depends not in output:
                depends_on.append(field_name)
                continue
            if depends and depends in output:
                ctx._depends_on = output[depends]

            # After generating an anchor field, fetch its correlated values from Redis
            if field_name in self._anchor_map and correlation_client is not None:
                value = config["child_gen"].generate(ctx)
                value = self._value_checker(
                    value, config["default_value"], config["is_required"], field_name
                )
                output[field_name] = value
                key = f"corr:{_schema_name}:{_schema_ver}:{field_name}:{value}"
                try:
                    raw = correlation_client.get(key)
                    if raw:
                        corr_data[field_name] = json.loads(raw)
                    else:
                        corr_miss.add(field_name)
                except _CORRELATION_LOOKUP_ERRORS:
                    # Redis or payload-parse failure: log with traceback so
                    # this isn't an invisible source of "missing data" bugs,
                    # then continue with the locally-generated value.
                    logger.exception(
                        "correlation_redis_get_failed schema=%s field=%s key=%s",
                        _schema_name, field_name, key,
                    )
                continue

            # If this field is intra-schema correlated, use cached value if available
            if bound_to and not config["bound_to_schema"] and bound_to in corr_data:
                cached_val = corr_data[bound_to].get(field_name)
                if cached_val is not None:
                    output[field_name] = cached_val
                    continue

            value = config["child_gen"].generate(ctx)
            value = self._value_checker(
                value, config["default_value"], config["is_required"], field_name
            )
            output[field_name] = value

        while depends_on:
            resolved_any = False
            indx = len(depends_on) - 1
            while indx >= 0:
                d_field_name = depends_on[indx]
                d_config = self._field_configs[d_field_name]
                d_depends_on = d_config["depends"]
                if d_depends_on in output:
                    ctx._depends_on = output[d_depends_on]
                    value = d_config["child_gen"].generate(ctx)
                    value = self._value_checker(
                        value,
                        d_config["default_value"],
                        d_config["is_required"],
                        d_field_name,
                    )
                    output[d_field_name] = value
                    depends_on.pop(indx)
                    resolved_any = True
                indx -= 1

            if not resolved_any:
                raise InvalidParameterError(
                    f"Cannot resolve dependencies: {', '.join(depends_on)}"
                )

        # Cross-schema correlation lookup — read from source schema's cache, override if hit
        if correlation_client is not None:
            for field_name, config in self._field_configs.items():
                bound_to_schema = config["bound_to_schema"]
                if not bound_to_schema:
                    continue
                bound_to = config["bound_to"]
                if not bound_to or bound_to not in output:
                    continue
                anchor_val = output[bound_to]
                pinned_rev = config["bound_to_revision"]
                try:
                    if pinned_rev is not None:
                        src_rev = pinned_rev
                    else:
                        src_rev = SchemaRegistry.get_revision(
                            SchemaRegistry.get_latest_name(bound_to_schema)
                        )
                    key = f"corr:{bound_to_schema}:{src_rev}:{bound_to}:{anchor_val}"
                    raw = correlation_client.get(key)
                    if raw:
                        cached = json.loads(raw)
                        if field_name in cached:
                            output[field_name] = cached[field_name]
                    else:
                        logger.warning(
                            "cross-schema corr miss: schema=%s field=%s anchor=%s=%s",
                            bound_to_schema, field_name, bound_to, anchor_val,
                        )
                except _CORRELATION_LOOKUP_ERRORS:
                    logger.exception(
                        "cross_schema_correlation_redis_get_failed schema=%s field=%s anchor=%s=%s",
                        bound_to_schema, field_name, bound_to, anchor_val,
                    )

        # Write new correlated entries to Redis (SET NX — only if not exists)
        if corr_miss and correlation_client is not None:
            for anchor_field in corr_miss:
                if anchor_field not in output:
                    continue
                anchor_val = output[anchor_field]
                corr_fields = self._anchor_map.get(anchor_field, [])
                new_data = {f: output[f] for f in corr_fields if f in output}
                if new_data:
                    key = f"corr:{_schema_name}:{_schema_ver}:{anchor_field}:{anchor_val}"
                    try:
                        correlation_client.set(key, json.dumps(new_data), nx=True)
                    except RedisError:
                        # Best-effort write — a future read will retry. Log
                        # with traceback so persistent failures are visible.
                        logger.exception(
                            "correlation_redis_set_nx_failed key=%s", key
                        )

        # Pool write: push anchor + siblings into Redis SET for downstream schemas
        if self._pool_anchor and correlation_client is not None:
            anchor_val = output.get(self._pool_anchor)
            if anchor_val is not None:
                pool_record = {self._pool_anchor: anchor_val}
                for sibling in self._pool_siblings:
                    if sibling in output:
                        pool_record[sibling] = output[sibling]
                pool_key = f"pool:{_schema_name}"
                try:
                    correlation_client.sadd(pool_key, json.dumps(pool_record))
                except RedisError:
                    logger.exception(
                        "pool_redis_sadd_failed key=%s", pool_key
                    )

        return output
