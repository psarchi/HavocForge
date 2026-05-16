"""Fallback live generation and global cache counter maintenance.

These helpers are split out of the original ``streaming.py`` so the WebSocket
handler doesn't need to know about generator construction or about the
schema-level / global counters that the pre-generation worker maintains.
"""

from __future__ import annotations

from typing import Any

from havocforge.context import GenContext
from server.deps import get_generator
from server.logging import get_logger

logger = get_logger(__name__)


def generate_live_batch(schema: str, count: int) -> list[dict[str, Any]]:
    """Generate ``count`` items live (used when the pre-gen cache is empty).

    A failure here is intentionally non-fatal — the caller treats an empty
    list as 'try again next iteration'. The exception is fully logged with
    a stack trace so silent data loss is detectable in operations.
    """
    try:
        gen = get_generator(schema)
        ctx = GenContext(seed=None)
        ctx.schema_name = schema

        items = [gen.generate(ctx) for _ in range(count)]
        logger.debug("live_generation_batch", schema=schema, count=len(items))
        return items
    except Exception as e:
        logger.error(
            "live_generation_failed", schema=schema, error=str(e), exc_info=True
        )
        return []


async def update_global_cache_count(
    redis,
    schema: str,
    delta: int,
    global_count_key: str,
    schema_count_key_template: str,
) -> None:
    """Atomically nudge the global and per-schema cache counters.

    ``delta`` is negative when items are consumed and positive when they're
    pushed back (e.g. on disconnect with retention enabled).
    """
    try:
        await redis.client.incrby(global_count_key, delta)

        schema_count_key = schema_count_key_template.format(schema=schema)
        new_count = await redis.client.incrby(schema_count_key, delta)

        if new_count < 0:
            await redis.client.set(schema_count_key, 0)
            logger.warning("schema_count_negative_reset", schema=schema, was=new_count)
    except Exception as e:
        # Counter drift is recoverable on next pre-gen cycle; log and move on
        # rather than killing the stream.
        logger.warning(
            "global_count_update_failed", schema=schema, delta=delta, error=str(e)
        )
