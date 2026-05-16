"""Per-batch chaos application for the streaming endpoint.

Extracted from the original ``streaming.py`` god file. Applies chaos ops
either to the whole batch (when forced via query param) or to each item
independently (default — better randomness, at the cost of more chaos-manager
invocations).
"""

from __future__ import annotations

from typing import Any

from havocforge.chaos.access import get_chaos_manager
from havocforge.context import GenContext


async def apply_chaos_to_batch(
    items: list[dict[str, Any]],
    schema: str,
    forced_chaos: list[str] | None = None,
) -> tuple[list[dict[str, Any] | str], list[str], dict[str, Any]]:
    """Run chaos ops over a batch.

    Returns:
        Triple of ``(transformed items, sorted chaos descriptions, chaos meta)``.
        Items may be dicts or — when an encoding-style op fires — strings.
    """
    ctx = GenContext()
    ctx.schema_name = schema
    mgr = get_chaos_manager(ctx)

    if forced_chaos:
        temp_payload = {"items": items}
        result, resp_meta = mgr.apply(
            body=temp_payload, schema_name=schema, forced_activation=forced_chaos
        )
        result_body = getattr(result, "body", {})

        if isinstance(result_body, str):
            body_items: list = [result_body]
        elif isinstance(result_body, dict):
            body_items = result_body.get("items", items)
        else:
            body_items = items

        descriptions = getattr(result, "descriptions", []) or []
        return body_items, descriptions, resp_meta or {}

    out_items: list = []
    all_descriptions: set[str] = set()
    merged_meta: dict[str, Any] = {}

    for item in items:
        temp_payload = {"items": [item]}
        result, resp_meta = mgr.apply(
            body=temp_payload, schema_name=schema, forced_activation=None
        )

        result_body = getattr(result, "body", {})

        if isinstance(result_body, str):
            out_items.append(result_body)
        elif isinstance(result_body, dict):
            body_items = result_body.get("items", [item])
            out_items.append(body_items[0] if body_items else item)
        else:
            out_items.append(item)

        descriptions = getattr(result, "descriptions", []) or []
        all_descriptions.update(descriptions)

        if resp_meta:
            merged_meta.update(resp_meta)

    return out_items, sorted(all_descriptions), merged_meta
