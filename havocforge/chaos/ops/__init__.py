"""Auto-load all chaos ops and provide registry access."""

from __future__ import annotations

import importlib
import pkgutil
from havocforge.registry import Registry
from havocforge.chaos.ops.base import BaseChaosOp


for _finder, name, _ispkg in pkgutil.walk_packages(__path__, prefix=__name__ + "."):
    if not name.split(".")[-1].startswith("_"):
        try:
            importlib.import_module(name)
        except Exception as e:
            print(f"Warning: Failed to load chaos op module {name}: {e}")


def get(key: str):
    """Get a chaos op class by key.

    Args:
        key: Chaos op key (e.g., "late_arrival", "time_skew", "delay")

    Returns:
        Chaos op class, or None if not found

    Example:
        op_cls = get("late_arrival")
        if op_cls:
            op = op_cls(enabled=True, p=0.15)
    """
    return Registry.get(BaseChaosOp, key)


def get_all():
    """Get all registered chaos op classes.

    Returns:
        Dictionary mapping keys to chaos op classes

    Example:
        all_ops = get_all()
        print(f"Available chaos ops: {list(all_ops.keys())}")
    """
    return Registry.get_all(BaseChaosOp)


__all__ = ["get", "get_all", "Registry", "BaseChaosOp"]
