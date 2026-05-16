import asyncio
import os
import random
import time
from typing import Any

import orjson
import redis.asyncio as aioredis
import structlog

from havocforge.context import GenContext
from havocforge.observability import (
    items_generated_total,
    pregen_queue_size,
    pregen_generation_rate,
)
from havocforge.chaos.access import get_chaos_manager
from server.deps import get_generator

logger = structlog.get_logger(__name__)


def _discover_stateful_fields(schema_name: str) -> list[dict[str, Any]]:
    """Return metadata for stateful generators at root level.

    Returns metadata including:
    - field: Field name
    - gen: Generator type token (e.g., "stateful_timestamp", "stateful_datetime")
    - params: Generator parameters (start, increment, format, tz, etc.)

    On any unexpected error during discovery, logs with full traceback and
    returns an empty list (safe default — the pre-gen worker treats 'no
    stateful fields' as 'nothing to track', not as an error). The previous
    implementation swallowed silently, hiding registry/contract bugs.
    """
    from havocforge.schema.registry import SchemaRegistry
    from havocforge.schema.errors import SchemaError

    fields: list[dict[str, Any]] = []
    try:
        doc = SchemaRegistry.get(schema_name)
    except SchemaError as e:
        logger.warning(
            "stateful_discovery_skipped_schema_missing",
            schema=schema_name,
            error=str(e),
        )
        return []
    except Exception:
        # Unexpected — log with full traceback so the bug is visible in ops,
        # but still return [] so one bad schema can't kill the pre-gen worker.
        logger.exception(
            "stateful_discovery_unexpected_error", schema=schema_name
        )
        return []

    for path, contract in doc.contracts_by_path.items():
        if "." in path or "[]" in path or "|" in path:
            continue
        cls_name = contract.__class__.__name__.lower()
        token = getattr(contract, "type_token", None)
        if not token and "stateful" not in cls_name:
            continue

        params: dict[str, Any] = {}
        try:
            params = contract.model_dump(exclude_none=True)
        except (AttributeError, TypeError) as e:
            logger.debug(
                "stateful_contract_dump_failed",
                schema=schema_name,
                path=path,
                error=str(e),
            )

        for k, v in list(params.items()):
            if hasattr(v, "isoformat"):
                try:
                    params[k] = v.isoformat()
                except (AttributeError, ValueError) as e:
                    logger.debug(
                        "stateful_isoformat_failed",
                        schema=schema_name,
                        path=path,
                        key=k,
                        error=str(e),
                    )
                    params.pop(k, None)

        if not params:
            start = getattr(contract, "start", None)
            increment = getattr(contract, "increment", None)
            if start is None or increment is None:
                continue
            params = {"start": start, "increment": increment}

        if "start" not in params or "increment" not in params:
            continue

        fields.append(
            {
                "field": path,
                "gen": token or cls_name,
                "params": params,
            }
        )

    return fields


def _load_pregen_config() -> tuple[int, int, int | None, int | None, bool, str]:
    """Load pregeneration settings from config (fail hard if missing)."""
    from havocforge.config import get_config_manager

    cm = get_config_manager()

    queue_size = cm.get_value("pregeneration.queue_size")
    batch_size = cm.get_value("pregeneration.batch_size")
    max_items = cm.get_value("pregeneration.max_items")
    global_max_items = cm.get_value("pregeneration.global_max_items")
    key_prefix = cm.get_value("pregeneration.key_prefix")

    record_metrics = cm.get_value("server.observability.metrics_enabled", True)

    return queue_size, batch_size, max_items, global_max_items, record_metrics, key_prefix


def _load_runtime_settings() -> tuple[list[str], str, int, int]:
    """Load schemas from config strictly; allow env overrides for deployment settings."""
    from havocforge.config import get_config_manager

    cm = get_config_manager()

    schemas: list[str] = []
    pregen_cfg = cm.get_root("pregeneration")
    if pregen_cfg:
        raw_schemas = getattr(pregen_cfg, "schemas", None)
        if isinstance(raw_schemas, str):
            schemas = [s.strip() for s in raw_schemas.split(",") if s.strip()]
        elif isinstance(raw_schemas, (list, tuple)):
            schemas = [str(s).strip() for s in raw_schemas if str(s).strip()]

    if not schemas:
        schemas = ["smoke"]
        logger.warning("schemas_not_in_config_using_default", default=schemas)

    redis_url = "redis://localhost:6379"
    workers = 1
    metrics_port = 8004

    if pregen_cfg:
        workers_cfg = getattr(pregen_cfg, "workers", None)
        if workers_cfg is not None:
            workers = int(workers_cfg)
        metrics_cfg = getattr(pregen_cfg, "metrics_port", None)
        if metrics_cfg is not None:
            metrics_port = int(metrics_cfg)

    server_cfg = cm.get_root("server")
    persistence_cfg = (
        getattr(server_cfg, "persistence", None) if server_cfg else None
    )
    if persistence_cfg:
        redis_cfg = getattr(persistence_cfg, "redis", None)
        if redis_cfg:
            redis_url = getattr(redis_cfg, "url", redis_url)

    redis_env = os.getenv("REDIS_URL")
    if redis_env:
        redis_url = redis_env

    workers_env = os.getenv("WORKERS")
    if workers_env:
        workers = int(workers_env)

    metrics_env = os.getenv("METRICS_PORT")
    if metrics_env:
        metrics_port = int(metrics_env)

    logger.info(
        "pregen_runtime_settings",
        schemas=schemas,
        redis_url=redis_url,
        workers=workers,
        metrics_port=metrics_port,
    )
    return schemas, redis_url, workers, metrics_port


async def generate_and_push(
    redis: aioredis.Redis,
    schema_name: str,
    generator,
    queue_size: int,
    batch_size: int,
    max_items: int | None,
    global_max_items: int | None,
    record_metrics: bool,
    key_prefix: str,
):
    """
    Continuously generate items and push to Redis queue.

    Args:
        redis: Redis client
        schema_name: Schema to generate for
        generator: Generator instance
        queue_size: Maximum queue size (LTRIM limit)
        batch_size: Items per batch before pushing
        max_items: Per-schema maximum items (optional)
        global_max_items: Global maximum items across all schemas (optional)
        record_metrics: Whether to record Prometheus metrics
        key_prefix: Redis key prefix (from config)
    """
    queue_key = f"{key_prefix}:{schema_name}:queue"
    rng = random.Random()
    ctx = GenContext(rng=rng, locale="en_US")
    ctx.schema_name = schema_name
    chaos_mgr = get_chaos_manager(ctx, pre_gen=True)

    batch: list = []
    batch_count = 0
    generated_total = 0

    rate_tracking_start = time.time()
    rate_tracking_count = 0
    meta_key = f"{key_prefix}:{schema_name}:meta"
    global_count_key = f"{key_prefix}:global:count"
    schema_count_key = f"{key_prefix}:{schema_name}:count"

    logger.info(
        "pregen_worker_started",
        schema=schema_name,
        queue_size=queue_size,
        batch_size=batch_size,
        max_items=max_items,
        global_max_items=global_max_items,
    )

    while True:
        try:
            if max_items is not None and generated_total >= max_items:
                logger.info(
                    "pregen_max_items_reached", schema=schema_name, max_items=max_items
                )
                break

            if len(batch) == 0:
                current_len = await redis.llen(queue_key)
                if current_len is not None and current_len >= queue_size:
                    await asyncio.sleep(0.1)
                    continue

                if global_max_items is not None:
                    try:
                        global_count_raw = await redis.get(global_count_key)
                        global_count = int(global_count_raw) if global_count_raw else 0
                        if global_count >= global_max_items:
                            logger.debug(
                                "global_max_items_reached_waiting",
                                schema=schema_name,
                                global_count=global_count,
                                global_max=global_max_items,
                            )
                            await asyncio.sleep(0.5)
                            continue
                    except Exception as e:
                        logger.warning(
                            "global_count_check_failed",
                            schema=schema_name,
                            error=str(e),
                        )

                try:
                    chaos_mgr.apply(body={}, schema_name=schema_name)
                except Exception as e:
                    logger.warning(
                        "pregen_chaos_apply_failed", schema=schema_name, error=str(e)
                    )

            item = generator.generate(ctx)

            serialized = orjson.dumps(item)
            batch.append(serialized)

            if len(batch) >= batch_size:
                if global_max_items is not None:
                    try:
                        async with redis.pipeline() as pipe:
                            pipe.incrby(global_count_key, len(batch))
                            pipe.incrby(schema_count_key, len(batch))
                            pipe.lpush(queue_key, *batch)
                            pipe.ltrim(queue_key, 0, queue_size - 1)
                            await pipe.execute()
                    except Exception as e:
                        logger.error(
                            "batch_push_with_counters_failed",
                            schema=schema_name,
                            error=str(e),
                        )
                        async with redis.pipeline() as pipe:
                            pipe.lpush(queue_key, *batch)
                            pipe.ltrim(queue_key, 0, queue_size - 1)
                            await pipe.execute()
                else:
                    async with redis.pipeline() as pipe:
                        pipe.lpush(queue_key, *batch)
                        pipe.ltrim(queue_key, 0, queue_size - 1)
                        await pipe.execute()

                if record_metrics:
                    items_generated_total.labels(
                        schema=schema_name, source="pregen"
                    ).inc(len(batch))

                rate_tracking_count += len(batch)

                batch_count += 1
                if batch_count % 10 == 0:
                    queue_len = await redis.llen(queue_key)

                    if queue_len is not None:
                        pregen_queue_size.labels(schema=schema_name).set(queue_len)

                    elapsed = time.time() - rate_tracking_start
                    if elapsed > 0:
                        actual_rate = int(rate_tracking_count / elapsed)

                        pregen_generation_rate.labels(schema=schema_name).set(
                            actual_rate
                        )

                        try:
                            existing_meta_raw = await redis.get(meta_key)
                            if existing_meta_raw:
                                existing_meta = orjson.loads(existing_meta_raw)
                                existing_meta["actual_generation_rate"] = actual_rate
                                existing_meta["rate_updated_at"] = time.time()
                                await redis.set(meta_key, orjson.dumps(existing_meta))

                                logger.debug(
                                    "generation_rate_updated",
                                    schema=schema_name,
                                    rate=actual_rate,
                                    items=rate_tracking_count,
                                    elapsed=elapsed,
                                )
                        except Exception as e:
                            logger.warning(
                                "rate_update_failed", schema=schema_name, error=str(e)
                            )

                        rate_tracking_start = time.time()
                        rate_tracking_count = 0

                    logger.debug(
                        "pregen_batch_pushed",
                        schema=schema_name,
                        batch_count=batch_count,
                        batch_size=len(batch),
                        queue_length=queue_len,
                    )

                batch = []
                await asyncio.sleep(0)

            generated_total += 1

        except Exception as e:
            logger.error(
                "pregen_generation_error",
                schema=schema_name,
                error=str(e),
                exc_info=True,
            )
            await asyncio.sleep(1)


async def run_worker_for_schemas(
    schema_names: list[str],
    redis_url: str = "redis://localhost:6379",
    redis_client=None,
):
    """
    Run pre-generation worker for specified schemas (used in API startup).

    Args:
        schema_names: List of schema names to pre-generate
        redis_url: Redis connection URL (used if redis_client not provided)
        redis_client: Existing Redis client instance to reuse
    """
    logger.info("pregen_worker_starting", schemas=schema_names)

    queue_size, batch_size, max_items, global_max_items, record_metrics, key_prefix = (
        _load_pregen_config()
    )

    if redis_client:
        redis = redis_client.client
    else:
        redis = await aioredis.from_url(redis_url, decode_responses=False)

    tasks = []

    for schema_name in schema_names:
        try:
            generator = get_generator(schema_name)

            stateful_meta = _discover_stateful_fields(schema_name)
            if stateful_meta:
                meta_key = f"{key_prefix}:{schema_name}:meta"
                worker_start_time_us = time.time_ns() // 1000
                meta_payload = {
                    "schema": schema_name,
                    "stateful": stateful_meta,
                    "worker_start_time_us": worker_start_time_us,
                    "worker_start_time_seconds": time.time(),
                }
                await redis.set(meta_key, orjson.dumps(meta_payload))

            task = asyncio.create_task(
                generate_and_push(
                    redis,
                    schema_name,
                    generator,
                    queue_size=queue_size,
                    batch_size=batch_size,
                    max_items=max_items,
                    global_max_items=global_max_items,
                    record_metrics=record_metrics,
                    key_prefix=key_prefix,
                )
            )
            tasks.append(task)

            logger.info("pregen_task_created", schema=schema_name)

        except Exception as e:
            logger.error(
                "pregen_task_creation_failed",
                schema=schema_name,
                error=str(e),
                exc_info=True,
            )

    if not tasks:
        logger.error("no_pregen_tasks_created")
        return

    logger.info("pregen_worker_running", task_count=len(tasks))

    await asyncio.gather(*tasks, return_exceptions=True)


async def run_worker(
    schema_names: list[str],
    redis_url: str = "redis://localhost:6379",
):
    """
    Run pre-generation worker for specified schemas (standalone mode).

    Args:
        schema_names: List of schema names to pre-generate
        redis_url: Redis connection URL
    """
    await run_worker_for_schemas(
        schema_names,
        redis_url,
        None,
    )


async def run_metrics_server(port: int = 8004):
    """Run HTTP server to expose Prometheus metrics."""
    from havocforge.observability import get_metrics_app
    import uvicorn

    config = uvicorn.Config(
        app=get_metrics_app(),
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    import sys
    import multiprocessing

    schemas, redis_url, workers, metrics_port = _load_runtime_settings()

    if not schemas:
        logger.error("no_schemas_configured")
        sys.exit(1)

    if workers == 1:
        async def run_with_metrics():
            metrics_task = asyncio.create_task(run_metrics_server(metrics_port))
            worker_task = asyncio.create_task(run_worker(schemas, redis_url))
            await asyncio.gather(metrics_task, worker_task)

        asyncio.run(run_with_metrics())
    else:
        logger.info("starting_multiprocess_workers", workers=workers, schemas=schemas)

        def worker_process(worker_id: int):
            """Worker process entrypoint."""
            logger.info("worker_process_starting", worker_id=worker_id, schemas=schemas)
            asyncio.run(run_worker(schemas, redis_url))

        def metrics_process():
            """Metrics server process."""
            asyncio.run(run_metrics_server(metrics_port))

        processes = []

        metrics_proc = multiprocessing.Process(target=metrics_process)
        metrics_proc.start()
        processes.append(metrics_proc)

        for i in range(workers):
            p = multiprocessing.Process(target=worker_process, args=(i,))
            p.start()
            processes.append(p)

        for p in processes:
            p.join()
