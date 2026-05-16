"""WebSocket streaming handler — the orchestration layer.

This module owns the WebSocket lifecycle (accept, main loop, disconnect /
error handling, close) and delegates everything else:

- Stateful field metadata + per-user state → :mod:`server.routers.streaming.state`
- Per-batch chaos application → :mod:`server.routers.streaming.chaos_apply`
- Live-generation fallback + cache counters → :mod:`server.routers.streaming.live`
- Optional cProfile capture → :mod:`server.routers.streaming.profiler`

The pre-split version of this handler was a 793-line file; the orchestration
itself is ~250 lines.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from typing import Any

import orjson
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from havocforge.config import get_config_manager
from havocforge.observability import websocket_active_connections
from server.logging import get_logger
from server.rate_limiter import AdaptiveRateLimiter

from .chaos_apply import apply_chaos_to_batch
from .live import generate_live_batch, update_global_cache_count
from .profiler import StreamProfiler
from .state import (
    apply_stateful_user_batch,
    ensure_stateful_meta,
    get_or_create_user_state,
    save_user_state,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["streaming"])


@router.websocket("/schemas/{schema}/stream")
async def stream_schema(
    websocket: WebSocket,
    schema: str,
    count: int | None = None,
    duration: int | None = None,
    max_events: int | None = None,
    user_id: str | None = None,
    forced_chaos: str | None = None,
    profile: bool = False,
) -> None:
    """Stream items from the pre-generation queue (or live fallback).

    Args:
        schema: Schema name to stream.
        count: Items per pop iteration (defaults to ``server.streaming.batch_pop_size``).
        duration: Maximum stream duration in seconds.
        max_events: Hard cap on total events sent.
        user_id: Optional ID for stateful continuation. Sequential mode only.
                 If omitted with stateful schemas, a random ID is assigned.
        forced_chaos: Comma-separated chaos op names to force on every batch.
        profile: Enable per-stream cProfile capture (requires
                 ``server.debug.profiler_enabled=true``).
    """
    await websocket.accept()
    websocket_active_connections.labels(schema=schema).inc()

    cfg = _load_stream_config()
    queue_key = cfg["queue_key_template"].format(schema=schema)
    effective_batch_size = count if count is not None else cfg["batch_pop_size"]

    profiler = StreamProfiler(
        requested=profile,
        enabled_in_config=cfg["profiler_enabled"],
        output_dir=cfg["profiler_output_dir"],
        schema=schema,
        user_id=user_id,
    )
    profiler.start()

    redis = websocket.app.state.redis
    stateful_meta = await ensure_stateful_meta(
        redis, schema, cfg["meta_key_template"], cfg["metadata_cache_ttl"]
    )

    has_stateful_fields = bool(stateful_meta.get("fields"))
    needs_user_state = has_stateful_fields and cfg["increment_mode"] == "sequential"

    user_id = await _resolve_user_id(
        user_id=user_id,
        needs_user_state=needs_user_state,
        has_stateful_fields=has_stateful_fields,
        schema=schema,
        increment_mode=cfg["increment_mode"],
        redis=redis,
        user_state_key_template=cfg["user_state_key_template"],
    )

    if needs_user_state and user_id:
        user_state = await get_or_create_user_state(
            redis,
            schema,
            user_id,
            stateful_meta,
            cfg["user_state_key_template"],
            cfg["user_state_ttl"],
        )
    else:
        user_state = {}

    forced_chaos_list = _parse_forced_chaos(
        forced_chaos, cfg["allow_forced_chaos"], schema=schema
    )

    rate_limiter = _build_rate_limiter(cfg, stateful_meta, schema)

    stream_mode = _resolve_stream_mode(cfg)
    logger.info(
        "stream_starting",
        schema=schema,
        user_id=user_id,
        pregen_enabled=cfg["pregen_enabled"],
        fallback_to_live=cfg["fallback_to_live"],
        mode=stream_mode,
    )

    await websocket.send_text(
        orjson.dumps(
            {
                "type": "start",
                "schema": schema,
                "user_id": user_id,
                "mode": stream_mode,
                "increment_mode": cfg["increment_mode"],
                "forced_chaos": forced_chaos_list,
                "rate_limit_enabled": cfg["rate_limit_enabled"],
                "rate_limit_base": cfg["base_rate"] if cfg["rate_limit_enabled"] else None,
            }
        ).decode("utf-8")
    )

    seq = 0
    start_time = time.time()

    try:
        while True:
            if duration and (time.time() - start_time) >= duration:
                break
            if max_events is not None and seq >= max_events:
                break

            remaining = max_events - seq if max_events is not None else None
            if remaining is not None and remaining <= 0:
                break
            pop_size = (
                min(effective_batch_size, remaining)
                if remaining
                else effective_batch_size
            )

            if rate_limiter and not await rate_limiter.consume(pop_size):
                await asyncio.sleep(0.001)
                continue

            raw_items = await _fetch_batch(
                redis=redis,
                websocket=websocket,
                schema=schema,
                queue_key=queue_key,
                pop_size=pop_size,
                cfg=cfg,
            )
            if raw_items is None:
                # Cache required and empty — error already sent to client
                break
            if not raw_items:
                await asyncio.sleep(0.01)
                continue

            batch_items, user_state = await apply_stateful_user_batch(
                raw_items,
                user_state,
                stateful_meta,
                increment_mode=cfg["increment_mode"],
            )

            chaos_descriptions: list[str] = []
            chaos_meta: dict[str, Any] = {}
            if cfg["apply_chaos"]:
                try:
                    (
                        batch_items,
                        chaos_descriptions,
                        chaos_meta,
                    ) = await apply_chaos_to_batch(  # type: ignore[assignment]
                        batch_items, schema, forced_chaos=forced_chaos_list
                    )
                    if rate_limiter is not None:
                        await _maybe_activate_burst(
                            rate_limiter=rate_limiter,
                            chaos_meta=chaos_meta,
                            forced_chaos_list=forced_chaos_list,
                            cfg=cfg,
                            redis=redis,
                            queue_key=queue_key,
                            schema=schema,
                        )
                except Exception as chaos_err:
                    logger.error(
                        "chaos_apply_failed",
                        schema=schema,
                        error=str(chaos_err),
                        forced_chaos=forced_chaos_list,
                    )

            sent_in_batch = 0
            try:
                for batch_item in batch_items:
                    if max_events is not None and seq >= max_events:
                        break
                    msg: dict[str, Any] = {
                        "type": "event",
                        "seq": seq,
                        "data": batch_item,
                    }
                    if chaos_descriptions:
                        msg["chaos_applied"] = chaos_descriptions
                    if chaos_meta:
                        msg["chaos_meta"] = chaos_meta
                    await websocket.send_text(orjson.dumps(msg).decode("utf-8"))
                    seq += 1
                    sent_in_batch += 1
            except WebSocketDisconnect:
                if cfg["batch_retention"]:
                    unsent_items = raw_items[sent_in_batch:]
                    if unsent_items:
                        unsent_bytes = [orjson.dumps(item) for item in unsent_items]
                        await redis.lpush(queue_key, *unsent_bytes)
                        logger.info(
                            "pushed_back_unsent_items",
                            count=len(unsent_items),
                            user_id=user_id,
                        )
                raise

            if cfg["increment_mode"] == "sequential" and user_id:
                await save_user_state(
                    redis,
                    schema,
                    user_id,
                    user_state,
                    cfg["user_state_key_template"],
                    cfg["user_state_ttl"],
                )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(
            "stream_unexpected_error", error=str(e), schema=schema, user_id=user_id
        )
        error_msg = {"type": "error", "error": type(e).__name__, "message": str(e)}
        with contextlib.suppress(Exception):
            await websocket.send_text(orjson.dumps(error_msg).decode("utf-8"))
    finally:
        websocket_active_connections.labels(schema=schema).dec()

        if cfg["increment_mode"] == "sequential" and user_id:
            await save_user_state(
                redis,
                schema,
                user_id,
                user_state,
                cfg["user_state_key_template"],
                cfg["user_state_ttl"],
            )

        profiler.stop_and_dump(items_sent=seq)

        # Give buffered send frames a chance to drain before the close frame
        # is queued, otherwise the close can interrupt in-flight sends.
        await asyncio.sleep(0.05)
        with contextlib.suppress(Exception):
            await websocket.close()


# ── Helpers ─────────────────────────────────────────────────────────────────


def _load_stream_config() -> dict[str, Any]:
    """Read all streaming-related config in one pass and derive key templates."""
    cm = get_config_manager()

    pregen_key_prefix = cm.get_value("pregeneration.key_prefix")
    user_state_key_prefix = cm.get_value("server.streaming.user_state_key_prefix")

    return {
        "profiler_enabled": cm.get_value("server.debug.profiler_enabled"),
        "profiler_output_dir": cm.get_value("server.debug.profiler_output_dir"),
        "batch_pop_size": cm.get_value("server.streaming.batch_pop_size"),
        "batch_retention": cm.get_value("server.streaming.batch_retention"),
        "increment_mode": cm.get_value("server.streaming.increment_mode"),
        "apply_chaos": cm.get_value("server.streaming.apply_chaos_in_consumer"),
        "allow_forced_chaos": cm.get_value("server.streaming.allow_forced_chaos"),
        "user_state_ttl": cm.get_value("server.streaming.user_state_ttl_seconds"),
        "metadata_cache_ttl": cm.get_value("server.streaming.metadata_cache_ttl_seconds"),
        "rate_limit_enabled": cm.get_value("server.streaming.rate_limit_enabled"),
        "base_rate": cm.get_value("server.streaming.base_rate"),
        "auto_detect_rate": cm.get_value("server.streaming.auto_detect_rate"),
        "auto_detect_sample_size": cm.get_value("server.streaming.auto_detect_sample_size"),
        "pregen_enabled": cm.get_value("pregeneration.enabled"),
        "fallback_to_live": cm.get_value("pregeneration.fallback_to_live"),
        "require_cache": cm.get_value("pregeneration.require_cache"),
        "global_max_items": cm.get_value("pregeneration.global_max_items"),
        "queue_key_template": f"{pregen_key_prefix}:{{schema}}:queue",
        "meta_key_template": f"{pregen_key_prefix}:{{schema}}:meta",
        "user_state_key_template": f"{user_state_key_prefix}:{{user_id}}:{{schema}}",
        "global_count_key": f"{pregen_key_prefix}:global:count",
        "schema_count_key_template": f"{pregen_key_prefix}:{{schema}}:count",
    }


async def _resolve_user_id(
    *,
    user_id: str | None,
    needs_user_state: bool,
    has_stateful_fields: bool,
    schema: str,
    increment_mode: str,
    redis,
    user_state_key_template: str,
) -> str | None:
    """Resolve the effective user_id, assigning a random one if needed."""
    if needs_user_state:
        if not user_id:
            user_id = uuid.uuid4().hex
            logger.info(
                "assigned_random_user_id",
                user_id=user_id,
                schema=schema,
                increment_mode=increment_mode,
            )
        else:
            state_key = user_state_key_template.format(user_id=user_id, schema=schema)
            existing_state = await redis.hgetall(state_key)
            logger.info(
                "resuming_user_state" if existing_state else "creating_new_user_state",
                user_id=user_id,
                schema=schema,
                increment_mode=increment_mode,
            )
        return user_id

    if user_id:
        if not has_stateful_fields:
            logger.info(
                "user_id_ignored_no_stateful_fields",
                user_id=user_id,
                schema=schema,
                reason="schema_has_no_stateful_fields",
            )
        elif increment_mode != "sequential":
            logger.info(
                "user_id_ignored_wallclock_mode",
                user_id=user_id,
                schema=schema,
                increment_mode=increment_mode,
            )
    return None


def _parse_forced_chaos(
    forced_chaos: str | None, allow_forced_chaos: bool, *, schema: str
) -> list[str] | None:
    if not forced_chaos:
        return None
    if not allow_forced_chaos:
        logger.info("forced_chaos_blocked_by_config", schema=schema)
        return None
    return [op.strip() for op in forced_chaos.split(",") if op.strip()]


def _build_rate_limiter(
    cfg: dict[str, Any], stateful_meta: dict[str, Any], schema: str
) -> AdaptiveRateLimiter | None:
    if not cfg["rate_limit_enabled"]:
        return None

    effective_rate = cfg["base_rate"]
    if cfg["auto_detect_rate"]:
        worker_rate = stateful_meta.get("actual_generation_rate")
        if worker_rate and worker_rate > 0:
            effective_rate = int(worker_rate * 0.9)
            logger.info(
                "using_worker_generation_rate",
                schema=schema,
                worker_rate=worker_rate,
                effective_rate=effective_rate,
                base_rate=cfg["base_rate"],
            )

    limiter = AdaptiveRateLimiter(
        base_rate=effective_rate,
        auto_detect=False,
        auto_detect_sample_size=cfg["auto_detect_sample_size"],
    )
    logger.info(
        "rate_limiter_enabled",
        schema=schema,
        effective_rate=effective_rate,
        auto_detect_from_worker=cfg["auto_detect_rate"],
    )
    return limiter


def _resolve_stream_mode(cfg: dict[str, Any]) -> str:
    if not cfg["pregen_enabled"]:
        return "live"
    if cfg["fallback_to_live"]:
        return "pregen_with_fallback"
    return "pregen_redis"


async def _fetch_batch(
    *,
    redis,
    websocket: WebSocket,
    schema: str,
    queue_key: str,
    pop_size: int,
    cfg: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Pop a batch from Redis, falling back to live generation when allowed.

    Returns ``None`` to signal that the stream should terminate (cache
    required and empty), an empty list to signal 'try again', or a non-empty
    list of items.
    """
    raw_items: list[dict[str, Any]] = []

    if cfg["pregen_enabled"]:
        try:
            batch_bytes = await redis.lpop(queue_key, pop_size)
            if batch_bytes:
                raw_items = [orjson.loads(b) for b in batch_bytes]
                if cfg["global_max_items"] is not None:
                    await update_global_cache_count(
                        redis,
                        schema,
                        -len(raw_items),
                        cfg["global_count_key"],
                        cfg["schema_count_key_template"],
                    )
            else:
                logger.warning(
                    "pregen_queue_empty",
                    schema=schema,
                    queue_key=queue_key,
                    pop_size=pop_size,
                )
        except Exception as e:
            logger.error(
                "pregen_lpop_failed",
                schema=schema,
                queue_key=queue_key,
                error=str(e),
            )

        if not raw_items:
            if cfg["require_cache"]:
                error_msg = {
                    "type": "error",
                    "error": "CacheRequired",
                    "message": "Pre-generation cache is empty",
                }
                await websocket.send_text(orjson.dumps(error_msg).decode("utf-8"))
                return None
            if cfg["fallback_to_live"]:
                logger.info(
                    "cache_empty_fallback_to_live", schema=schema, pop_size=pop_size
                )
                raw_items = generate_live_batch(schema, pop_size)
            else:
                return []
    else:
        raw_items = generate_live_batch(schema, pop_size)

    return raw_items


async def _maybe_activate_burst(
    *,
    rate_limiter: AdaptiveRateLimiter,
    chaos_meta: dict[str, Any],
    forced_chaos_list: list[str] | None,
    cfg: dict[str, Any],
    redis,
    queue_key: str,
    schema: str,
) -> None:
    """Activate the rate limiter's burst mode if a chaos op signaled one.

    The burst is only allowed when the pre-generation cache holds enough
    items to sustain it — otherwise we'd just empty the queue and stall.
    """
    if not chaos_meta.get("burst_active") or forced_chaos_list:
        return

    burst_rate = chaos_meta.get("burst_rate", cfg["base_rate"] * 10)
    burst_duration = chaos_meta.get("burst_duration", 10)
    required_cache_items = chaos_meta.get(
        "required_cache_items", burst_rate * burst_duration
    )

    if cfg["pregen_enabled"] and required_cache_items:
        current_queue_len = await redis.llen(queue_key)
        if current_queue_len < required_cache_items:
            logger.warning(
                "burst_blocked_insufficient_cache",
                schema=schema,
                required=required_cache_items,
                available=current_queue_len,
                burst_rate=burst_rate,
                burst_duration=burst_duration,
            )
            return
        rate_limiter.activate_burst(burst_rate, burst_duration)
        logger.info(
            "burst_activated_cache_validated",
            schema=schema,
            required=required_cache_items,
            available=current_queue_len,
            burst_rate=burst_rate,
            burst_duration=burst_duration,
        )
    else:
        rate_limiter.activate_burst(burst_rate, burst_duration)
