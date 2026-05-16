"""Per-user / per-schema stateful field handling for the streaming endpoint.

Handles three responsibilities, all of which used to live inside the 793-line
``streaming.py`` god file:

1. Loading and caching the *stateful field metadata* that the pre-generation
   worker writes to Redis (which fields are stateful, their start values,
   increments, format, etc.).
2. Loading / persisting *per-user state* in Redis with TTL so concurrent users
   don't collide and abandoned states expire.
3. Applying stateful field transforms to a batch of items, supporting both
   ``sequential`` (per-user incrementing) and ``wallclock`` (worker-relative)
   modes.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import orjson

from havocforge.generators.utils import parse_timestamp_to_microseconds
from server.logging import get_logger

logger = get_logger(__name__)

# Per-process metadata cache. Concurrent reads can both miss and re-fetch from
# Redis; both writes produce identical data so the redundancy is benign (the
# original assessment audit confirmed this is not a real race).
_STATEFUL_META: dict[str, dict[str, Any]] = {}


async def ensure_stateful_meta(
    redis,
    schema: str,
    meta_key_template: str,
    cache_ttl_seconds: int,
) -> dict[str, Any]:
    """Load and parse stateful field metadata from Redis with TTL caching.

    Returns metadata including ``fields`` (list of stateful field configs)
    and ``worker_start_time_seconds`` (used by wallclock mode).
    """
    if schema in _STATEFUL_META:
        cached_entry = _STATEFUL_META[schema]
        cached_at = cached_entry.get("cached_at", 0)
        if time.time() - cached_at < cache_ttl_seconds:
            return {k: v for k, v in cached_entry.items() if k != "cached_at"}
        logger.debug("metadata_cache_expired", schema=schema, cached_at=cached_at)
        del _STATEFUL_META[schema]

    meta_key = meta_key_template.format(schema=schema)
    raw = await redis.get(meta_key)
    if not raw:
        empty_meta: dict = {"fields": [], "worker_start_time_seconds": None}
        _STATEFUL_META[schema] = {**empty_meta, "cached_at": time.time()}
        return empty_meta

    try:
        meta = orjson.loads(raw)
        fields: list[dict[str, Any]] = meta.get("stateful") or []
        worker_start_time_seconds = meta.get("worker_start_time_seconds")
    except orjson.JSONDecodeError as e:
        logger.warning(
            "stateful_meta_decode_failed", schema=schema, error=str(e)
        )
        fields = []
        worker_start_time_seconds = None

    parsed: list[dict[str, Any]] = []
    for f in fields:
        try:
            field_name = f["field"]
            params = f.get("params") or {}
            start = parse_timestamp_to_microseconds(params.get("start"))
            increment = int(params.get("increment", 1))
            if start is None:
                continue
            kind = (
                "datetime"
                if "datetime" in str(f.get("gen") or f.get("type", "")).lower()
                else "timestamp"
            )
            parsed.append(
                {
                    "field": field_name,
                    "start": start,
                    "increment": increment,
                    "kind": kind,
                    "format": params.get("format"),
                    "tz": params.get("tz"),
                    "gen": f.get("gen", ""),
                }
            )
        except (KeyError, ValueError, TypeError) as e:
            logger.debug(
                "stateful_field_parse_skipped", schema=schema, error=str(e), field=f
            )
            continue

    parsed_meta = {
        "fields": parsed,
        "worker_start_time_seconds": worker_start_time_seconds,
        "actual_generation_rate": meta.get("actual_generation_rate"),
        "rate_updated_at": meta.get("rate_updated_at"),
    }
    _STATEFUL_META[schema] = {**parsed_meta, "cached_at": time.time()}
    return parsed_meta


async def get_or_create_user_state(
    redis,
    schema: str,
    user_id: str,
    meta: dict[str, Any],
    user_state_key_template: str,
    ttl_seconds: int,
) -> dict[str, int]:
    """Load existing user state or seed a fresh one from field start values.

    Refreshes the TTL on every read so active users keep their state and
    abandoned ones expire.
    """
    state_key = user_state_key_template.format(user_id=user_id, schema=schema)
    existing_state = await redis.hgetall(state_key)

    if existing_state:
        parsed_state: dict[str, int] = {}
        for k, v in existing_state.items():
            key = k.decode() if hasattr(k, "decode") else str(k)
            val = int(v.decode() if hasattr(v, "decode") else v)
            parsed_state[key] = val

        await redis.expire(state_key, ttl_seconds)
        return parsed_state

    initial_state: dict[str, int] = {}
    for field_meta in meta.get("fields", []):
        initial_state[field_meta["field"]] = field_meta["start"]

    if initial_state:
        await redis.hset(state_key, mapping=initial_state)
        await redis.expire(state_key, ttl_seconds)
    return initial_state


async def save_user_state(
    redis,
    schema: str,
    user_id: str,
    state: dict[str, int],
    user_state_key_template: str,
    ttl_seconds: int,
) -> None:
    """Persist user state with TTL refresh."""
    if not state:
        return
    state_key = user_state_key_template.format(user_id=user_id, schema=schema)
    await redis.hset(state_key, mapping=state)
    await redis.expire(state_key, ttl_seconds)


async def apply_stateful_user_batch(
    items: list[dict[str, Any]],
    user_state: dict[str, int],
    meta: dict[str, Any],
    increment_mode: str = "sequential",
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Apply per-field stateful increments to a batch of items.

    In ``sequential`` mode each user's state advances independently. In
    ``wallclock`` mode the value is derived from elapsed time since the
    pre-generation worker started, so all users see the same value at the
    same wall-clock moment.
    """
    fields_meta = meta.get("fields", [])
    if not fields_meta:
        return items, user_state

    new_state = user_state.copy()
    out_items = []
    worker_start_time = meta.get("worker_start_time_seconds")
    current_time_seconds = time.time()

    for item in items:
        payload = item.copy()
        for field_meta in fields_meta:
            field = field_meta["field"]
            increment = field_meta["increment"]
            kind = field_meta["kind"]
            fmt = field_meta.get("format")
            tz = field_meta.get("tz")
            start = field_meta["start"]

            if increment_mode == "wallclock":
                if worker_start_time is not None:
                    elapsed_seconds = current_time_seconds - worker_start_time
                    elapsed_microseconds = int(elapsed_seconds * 1_000_000)
                    increments_passed = elapsed_microseconds // increment
                    new_value = start + (increments_passed * increment)
                else:
                    logger.warning(
                        "wallclock_mode_fallback",
                        field=field,
                        reason="no_worker_start_time",
                    )
                    last_value = new_state.get(field, start)
                    new_value = last_value + increment
                    new_state[field] = new_value
            else:
                last_value = new_state.get(field, start)
                new_value = last_value + increment
                new_state[field] = new_value

            if kind == "datetime":
                dt = datetime.fromtimestamp(new_value / 1_000_000, tz=timezone.utc)
                if tz:
                    try:
                        sign = 1 if tz.startswith("+") else -1
                        hh, mm = tz[1:].split(":")
                        offset = timezone(
                            sign * timedelta(hours=int(hh), minutes=int(mm))
                        )
                        dt = dt.astimezone(offset)
                    except (ValueError, IndexError) as e:
                        # Invalid tz string — fall back to UTC; logged once at debug
                        logger.debug(
                            "invalid_tz_offset", field=field, tz=tz, error=str(e)
                        )
                payload[field] = dt.strftime(fmt or "%Y-%m-%dT%H:%M:%S%z")
            else:
                payload[field] = new_value

        out_items.append(payload)

    return out_items, new_state
