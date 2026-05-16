from __future__ import annotations

from typing import Dict, Type
from pydantic import BaseModel

from havocforge.config.utils import discover_roots
from havocforge.config.schema import MetaNode, build_meta_tree, build_runtime_model


class BuiltRoot:
    """Bundle holding the artifacts for a single configuration root.

    Attributes:
        name (str): Canonical root name.
        meta (MetaNode): Normalized meta tree built from the default schema.
        runtime_cls (Type[BaseModel]): Generated Pydantic model class.
        runtime (BaseModel): Instantiated model populated with defaults.
    """

    def __init__(
        self,
        name: str,
        meta: MetaNode,
        runtime_cls: Type[BaseModel],
        runtime_instance: BaseModel,
    ) -> None:
        self.name = name
        self.meta = meta
        self.runtime_cls = runtime_cls
        self.runtime = runtime_instance  # instance with default values


def build_config() -> Dict[str, BuiltRoot]:
    """Build Pydantic models for all discovered roots from defaults.

    Discovers default root schemas, converts each to a :class:`MetaNode`,
    generates the corresponding Pydantic model, and instantiates it with
    defaults.

    Returns:
        Dict[str, BuiltRoot]: Mapping ``root_name -> BuiltRoot`` with meta,
            model class, and a default-populated instance.
    """
    defaults = discover_roots()
    built: Dict[str, BuiltRoot] = {}

    for root_name, payload in defaults.items():
        meta = build_meta_tree(payload)
        runtime_cls = build_runtime_model(root_name, meta)
        runtime_inst = runtime_cls()  # defaults already placed
        built[root_name] = BuiltRoot(root_name, meta, runtime_cls, runtime_inst)

    return built
