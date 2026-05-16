from __future__ import annotations

import json
from typing import Any


def count_none_values(obj: Any) -> int:
    """Count None values in nested structure."""
    if obj is None:
        return 1
    if isinstance(obj, dict):
        return sum(count_none_values(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(count_none_values(v) for v in obj)
    return 0


def count_keys(obj: Any) -> int:
    """Count all keys in nested structure."""
    if isinstance(obj, dict):
        return len(obj) + sum(count_keys(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(count_keys(v) for v in obj)
    return 0


def has_duplicate_items(items: list[dict[str, Any]]) -> bool:
    """Check if items list has duplicate top-level items."""
    if len(items) <= 1:
        return False

    seen = set()
    for item in items:
        try:
            item_str = json.dumps(item, sort_keys=True)
            if item_str in seen:
                return True
            seen.add(item_str)
        except Exception:
            pass
    return False


def has_duplicates_in_arrays(items: list[dict[str, Any]]) -> bool:
    """Check if any arrays within items contain duplicate elements."""

    def check_array_dupes(obj: Any) -> bool:
        if isinstance(obj, list):
            if len(obj) > 1:
                seen = set()
                for elem in obj:
                    try:
                        elem_str = (
                            json.dumps(elem, sort_keys=True)
                            if isinstance(elem, (dict, list))
                            else str(elem)
                        )
                        if elem_str in seen:
                            return True
                        seen.add(elem_str)
                    except Exception:
                        pass
            for elem in obj:
                if check_array_dupes(elem):
                    return True
        elif isinstance(obj, dict):
            for value in obj.values():
                if check_array_dupes(value):
                    return True
        return False

    for item in items:
        if check_array_dupes(item):
            return True
    return False


def has_truncated_strings(items: list[dict[str, Any]]) -> bool:
    """Check if any string fields appear truncated (incomplete JSON, cut off text)."""

    def check_truncated(obj: Any) -> bool:
        if isinstance(obj, str):
            if obj.strip().startswith("{") and not obj.strip().endswith("}"):
                return True
            if obj.strip().startswith("[") and not obj.strip().endswith("]"):
                return True
        elif isinstance(obj, dict):
            for value in obj.values():
                if check_truncated(value):
                    return True
        elif isinstance(obj, list):
            for elem in obj:
                if check_truncated(elem):
                    return True
        return False

    for item in items:
        if check_truncated(item):
            return True
    return False


def has_corrupted_encoding(data: Any) -> bool:
    """Check for encoding corruption indicators."""
    data_str = json.dumps(data)
    if "" in data_str:
        return True
    if any(ord(c) in (0x200B, 0x200C, 0x200D, 0xFEFF) for c in data_str):
        return True
    return False


def get_all_registered_chaos_ops() -> list[str]:
    """Get all registered chaos operation keys."""
    from havocforge.registry import Registry
    from havocforge.chaos.ops.base import BaseChaosOp

    all_ops = Registry.get_all(BaseChaosOp)
    return sorted(all_ops.keys())
