"""Auto-load all generators and provide registry access."""

from __future__ import annotations

import importlib
import pkgutil
from havocforge.registry import Registry
from havocforge.generators.base import BaseGenerator


for _finder, name, _ispkg in pkgutil.walk_packages(__path__, prefix=__name__ + "."):
    if not name.split(".")[-1].startswith("_"):
        try:
            importlib.import_module(name)
        except Exception as e:
            print(f"Warning: Failed to load generator module {name}: {e}")


def get(key: str):
    """Get a generator class by key.

    Args:
        key: Generator key (e.g., "timestamp", "int", "string")

    Returns:
        Generator class, or None if not found

    Example:
        gen_cls = get("timestamp")
        if gen_cls:
            generator = gen_cls(...)
    """
    return Registry.get(BaseGenerator, key)


def get_all():
    """Get all registered generator classes.

    Returns:
        Dictionary mapping keys to generator classes

    Example:
        all_gens = get_all()
        print(f"Available generators: {list(all_gens.keys())}")
    """
    return Registry.get_all(BaseGenerator)


__all__ = ["get", "get_all", "Registry", "BaseGenerator"]
