from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Query, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from havocforge.context import GenContext
from havocforge.chaos.access import get_chaos_manager
from havocforge.observability import (
    generation_duration_seconds,
    items_generated_total,
    seed_source_total,
    chaos_op_executions_total,
    chaos_items_affected_total,
    chaos_op_duration_seconds,
    get_count_bucket,
)
from server.auth import RequireAuth
from server.deps import get_generator, get_redis, get_correlation_redis, _SCHEMAS_DIR
from server.logging import get_logger
from server.metadata import build_response_with_metadata

logger = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["schemas"])


@router.get("/schemas")
async def list_schemas() -> JSONResponse:
    """List all available schemas.

    Returns:
        JSONResponse: List of schema names and count.
    """
    schema_files = sorted(_SCHEMAS_DIR.glob("*.yaml")) + sorted(_SCHEMAS_DIR.glob("*.yml"))
    schema_names = sorted(set(f.stem for f in schema_files))

    return JSONResponse({
        "schemas": schema_names,
        "count": len(schema_names)
    })


@router.get("/schemas/{name}/generate")
async def generate_schema(
    name: str,
    request: Request,
    redis=Depends(get_redis),
    correlation_redis=Depends(get_correlation_redis),
    count: int = Query(1, ge=1, le=1000),
    seed: int | None = Query(None),
    chaos_ops: str | None = Query(
        None, description="Comma-separated chaos op keys to force"
    ),
    include_metadata: bool = Query(
        False, description="Include _metadata field in response"
    ),
    persist: bool = Query(True, description="Persist dataset for later retrieval"),
    _token: RequireAuth = None,
) -> JSONResponse:
    start_time = time.perf_counter()

    logger.debug(
        "generation_request_received",
        schema=name,
        count=count,
        seed=seed,
        chaos_ops=chaos_ops,
        include_metadata=include_metadata,
    )

    from havocforge.config import get_config_manager
    import orjson
    from fastapi import HTTPException

    try:
        cm = get_config_manager()
        pregen_enabled = cm.get_value("pregeneration.enabled", True)
        fallback_to_live = cm.get_value("pregeneration.fallback_to_live", True)
        require_cache = cm.get_value("pregeneration.require_cache", False)
    except Exception:
        pregen_enabled = True
        fallback_to_live = True
        require_cache = False

    items = []
    ctx = GenContext(seed=seed)
    ctx.schema_name = name
    ctx._correlation_client = correlation_redis
    gen_duration: float = 0.0

    if pregen_enabled and seed is None:
        queue_key = f"pregen:{name}:queue"
        try:
            batch_bytes = await redis.client.lpop(queue_key, count)
            if batch_bytes:
                items = [orjson.loads(b) for b in batch_bytes]
                logger.debug("rest_used_pregen_cache", schema=name, count=len(items))
                seed_source_total.labels(source="pregen_cache").inc()
            elif require_cache:
                raise HTTPException(
                    status_code=503,
                    detail=f"Pre-generation cache is empty for schema '{name}'. Enable fallback_to_live or populate cache.",
                )
            elif not fallback_to_live:
                raise HTTPException(
                    status_code=503,
                    detail=f"Pre-generation cache is empty for schema '{name}'. Retry in a moment.",
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("pregen_cache_read_failed", schema=name, error=str(e))

    if not items:
        if seed is not None:
            seed_source_total.labels(source="user_provided").inc()
        else:
            seed_source_total.labels(source="server_generated").inc()

        gen = get_generator(name)

        gen_start = time.perf_counter()
        # Generation is sync and may issue blocking sync-Redis correlation calls
        # (see havocforge/generators/composites/object.py). Off-load to a worker
        # thread so the FastAPI event loop stays responsive to other requests.
        items = await asyncio.to_thread(
            lambda: [gen.generate(ctx) for _ in range(count)]
        )
        gen_duration = time.perf_counter() - gen_start

        logger.debug("rest_used_live_generation", schema=name, count=len(items))

    count_bucket = get_count_bucket(count)
    if gen_duration > 0:
        generation_duration_seconds.labels(
            schema=name, count_bucket=count_bucket
        ).observe(gen_duration)

    items_generated_total.labels(schema=name, source="api").inc(len(items))

    forced = None
    if chaos_ops:
        forced = [op.strip() for op in chaos_ops.split(",") if op.strip()]

    mgr = get_chaos_manager(ctx)
    temp_payload = {"items": items}

    # time_skew / schema_time_skew / late_arrival need field hints to fire.
    # The preview endpoint already auto-detects these from the generated items;
    # do the same here so forced ops behave consistently across both routes.
    if forced:
        _patch_mgr_for_body_ops(mgr, forced, items, schema_name=name)

    chaos_start = time.perf_counter()
    result, meta = mgr.apply(
        body=temp_payload, schema_name=name, forced_activation=forced or None
    )
    chaos_duration = time.perf_counter() - chaos_start

    items = (
        getattr(result, "body", {}).get("items", items)
        if hasattr(result, "body")
        else items
    )
    descriptions = getattr(result, "descriptions", [])

    for desc in descriptions:
        op_name = desc.split("(")[0] if "(" in desc else desc

        chaos_op_executions_total.labels(op=op_name, schema=name, applied="true").inc()

        if descriptions:
            chaos_op_duration_seconds.labels(op=op_name, schema=name).observe(
                chaos_duration / len(descriptions)
            )

        if " items)" in desc:
            try:
                affected = int(desc.split("(")[1].split(" ")[0])
                chaos_items_affected_total.labels(op=op_name, schema=name).inc(affected)
            except (ValueError, IndexError):
                pass

    dataset_id = None
    if persist:
        try:
            from havocforge.persistence.id_generator import generate_id
            from datetime import datetime, timedelta
            from havocforge.observability import (
                persistence_writes_total,
                persistence_redis_writes_total,
                persistence_dataset_size_bytes,
            )
            from havocforge.config import get_config_manager
            import json

            try:
                cm = get_config_manager()
                persistence_cfg = cm.get_root("server").persistence  # type: ignore
                ttl_hours = getattr(persistence_cfg.redis, "ttl_hours", 24)
                retention_days = getattr(persistence_cfg.postgres, "retention_days", 30)
            except (AttributeError, TypeError):
                ttl_hours = 24
                retention_days = 30

            dataset_id = generate_id()

            created_at = datetime.utcnow()
            expires_at = created_at + timedelta(days=retention_days)

            stored_data = {
                "id": dataset_id,
                "schema_name": name,
                "data": {"items": items},
                "metadata": {},
                "seed": ctx.seed,
                "chaos_applied": descriptions if descriptions else [],
                "created_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            }

            await redis.set(dataset_id, stored_data, ttl_hours=ttl_hours)

            dataset_size = len(json.dumps(stored_data).encode("utf-8"))
            persistence_dataset_size_bytes.labels(schema=name).observe(dataset_size)
            persistence_writes_total.labels(schema=name, status="success").inc()
            persistence_redis_writes_total.labels(schema=name, status="success").inc()

        except Exception as e:
            from havocforge.observability import (
                persistence_writes_total,
                persistence_redis_writes_total,
            )

            persistence_writes_total.labels(schema=name, status="error").inc()
            persistence_redis_writes_total.labels(schema=name, status="error").inc()
            logger.error("persistence_failed", error=str(e), schema=name)

    payload = build_response_with_metadata(
        items=items,
        context=ctx,
        chaos_results=descriptions,
        include_metadata=include_metadata,
    )

    if dataset_id:
        payload["id"] = dataset_id

    duration_ms = (time.perf_counter() - start_time) * 1000

    logger.info(
        "generation_complete",
        schema=name,
        count=len(items),
        duration_ms=round(duration_ms, 2),
        chaos_count=len(descriptions),
    )

    logger.debug("generation_details", seed=ctx.seed, chaos_applied=descriptions)

    status_override = (meta or {}).get("status")
    headers_override = (meta or {}).get("headers")
    return JSONResponse(
        payload, status_code=status_override or 200, headers=headers_override or None
    )


class PreviewRequest(BaseModel):
    schema: dict
    count: int = Field(10, ge=1, le=50)
    seed: int | None = None
    chaos_ops: list[str] | None = None


_DRIFT_OPS = frozenset({"schema_drift", "data_drift"})


def _detect_datetime_fields(items: list) -> list[str]:
    from havocforge.chaos.utils import parse_timestamp
    if not items or not isinstance(items[0], dict):
        return []
    return [k for k, v in items[0].items() if parse_timestamp(v)[0] is not None]


def _seed_temporal_tracker(schema_name: str) -> None:
    from havocforge.chaos import get_temporal_tracker
    import datetime
    tracker = get_temporal_tracker()
    now_us = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1_000_000)
    first_us = now_us - 2 * 3600 * 1_000_000
    try:
        tracker.get_or_init(schema_name, first_us)
        tracker.update_timeline(schema_name, now_us)
    except Exception:
        pass


def _patch_mgr_for_body_ops(
    mgr, chaos_ops: list, items: list, schema_name: str = "preview"
) -> None:
    """Patch time-op fields and late_arrival schema_name in the manager in-place.

    Auto-detects datetime fields from the first generated item and injects them
    into ``time_skew`` / ``schema_time_skew`` op params, then re-instantiates
    the ops so the new params take effect. Also seeds the temporal tracker for
    ``late_arrival``.

    ``schema_name`` defaults to ``"preview"`` for the preview endpoint; pass the
    real schema name when calling from the regular generate route.
    """
    dt_fields = _detect_datetime_fields(items)
    if dt_fields:
        for time_op in ("time_skew", "schema_time_skew"):
            if time_op in chaos_ops and time_op in mgr._op_params_by_name:
                mgr._op_params_by_name[time_op]["fields"] = dt_fields
                op_cls = mgr.registry.get(time_op)
                if op_cls:
                    try:
                        mgr._op_instances[time_op] = op_cls(**mgr._op_params_by_name[time_op])
                    except Exception:
                        pass

    if "late_arrival" in chaos_ops:
        _seed_temporal_tracker(schema_name)
        if "late_arrival" in mgr._op_params_by_name:
            mgr._op_params_by_name["late_arrival"]["schema_name"] = schema_name
            op_cls = mgr.registry.get("late_arrival")
            if op_cls:
                try:
                    mgr._op_instances["late_arrival"] = op_cls(**mgr._op_params_by_name["late_arrival"])
                except Exception:
                    pass


_PREVIEW_DRIFT_KEY = "preview:drift:state"


@router.post("/schemas/generate-preview")
async def generate_preview(
    body: PreviewRequest,
    redis=Depends(get_redis),
) -> JSONResponse:
    """Generate items from an ad-hoc schema dict without registration or persistence."""
    import hashlib as _hashlib
    import json as _json
    import havocforge.api as engine_api
    from havocforge.chaos.drift import get_drift_coordinator
    from havocforge.schema.builder import build_schema, _synthesize_root_spec
    from havocforge.schema.registry import SchemaRegistry

    chaos_ops = body.chaos_ops or []
    drift_ops = [op for op in chaos_ops if op in _DRIFT_OPS]
    body_ops  = [op for op in chaos_ops if op not in _DRIFT_OPS]

    chaos_meta: dict = {"ops_fired": [], "status": 200, "headers": {}}

    schema_hash = _hashlib.md5(
        _json.dumps(body.schema, sort_keys=True).encode()
    ).hexdigest()

    # ── Step 1: register schema so drift ops can mutate it ──────────────────
    if drift_ops:
        # Load accumulated drift spec from Redis — shared across all workers.
        # If the user changed their schema, start fresh from body.schema.
        base_spec = body.schema
        try:
            saved = await redis.get(_PREVIEW_DRIFT_KEY)
            if saved and saved.get("hash") == schema_hash:
                base_spec = saved["spec"]
        except Exception:
            pass

        try:
            # Always clear coordinator so exactly 1 fresh drift layer per request.
            get_drift_coordinator().clear_schema("preview")
            schema_doc = build_schema("preview", base_spec)
            SchemaRegistry.replace("preview", schema_doc)
        except Exception:
            drift_ops = []  # schema couldn't be registered; skip drift

    # ── Step 2: apply drift ops (they mutate the registered schema) ─────────
    if drift_ops:
        drift_mgr = get_chaos_manager(None, pre_gen=True)
        drift_result, _ = drift_mgr.apply(
            body={"items": []},
            schema_name="preview",
            forced_activation=drift_ops,
        )
        chaos_meta["ops_fired"] += getattr(drift_result, "descriptions", []) or []

    # ── Step 3: generate items from the (possibly drifted) schema ───────────
    if drift_ops:
        try:
            latest = SchemaRegistry.get_latest_name("preview")
            drifted_doc = SchemaRegistry.get(latest)
            drifted_spec = _synthesize_root_spec(drifted_doc.contracts_by_path)
            gen = engine_api.build_generator(drifted_spec)
            # Persist new accumulated spec to Redis for the next request.
            try:
                await redis.set(
                    _PREVIEW_DRIFT_KEY,
                    {"hash": schema_hash, "spec": drifted_spec},
                    ttl_hours=1,
                )
            except Exception:
                pass
        except Exception:
            gen = engine_api.build_generator(body.schema)
    else:
        gen = engine_api.build_generator(body.schema)

    items = await asyncio.to_thread(
        engine_api.generate_many, gen, body.count, body.seed
    )

    # ── Step 4: apply body-level chaos ops ──────────────────────────────────
    if body_ops:
        body_mgr = get_chaos_manager(None)
        _patch_mgr_for_body_ops(body_mgr, body_ops, items)
        result, resp_meta = body_mgr.apply(
            body={"items": items},
            schema_name="preview",
            forced_activation=body_ops,
        )
        items = (
            getattr(result, "body", {}).get("items", items)
            if hasattr(result, "body")
            else items
        )
        chaos_meta["ops_fired"] += getattr(result, "descriptions", []) or []
        chaos_meta["status"] = resp_meta.get("status", 200)
        chaos_meta["headers"] = {
            k: v for k, v in (resp_meta.get("headers") or {}).items()
            if k.lower() != "content-type"
        }

    return JSONResponse({"items": items, "chaos": chaos_meta})
