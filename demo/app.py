"""Havocforge demo — slim, public-facing, no persistence.

A single FastAPI app that serves a static comparison-view UI and three small
endpoints. Everything else from the full project (admin, persistence, publish,
streaming) is intentionally absent.

Headline endpoint: ``GET /api/generate?schema=...&count=...&seed=...&chaos_ops=...``
runs the same seeded generation twice — once without chaos, once with — and
returns both results so the frontend can render them side-by-side.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from pathlib import Path
from typing import Any

import orjson
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from havocforge import api as engine_api
from havocforge.chaos.access import get_chaos_manager
from havocforge.context import GenContext
from havocforge.schema.builder import build_schema
from havocforge.schema.errors import SchemaRegistryKeyError
from havocforge.schema.registry import SchemaRegistry

from demo.rate_limit import IpRateLimiter

# ── Constants ───────────────────────────────────────────────────────────────

DEMO_DIR = Path(__file__).parent
STATIC_DIR = DEMO_DIR / "static"
SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"

# Hard caps — enforced server-side regardless of what the client requests.
MAX_COUNT = 50
RATE_LIMIT_PER_MIN = 30

# Schemas exposed in the demo. Excludes the cross-schema correlation ones
# (smoke_cross_schema, pool_user, pool_order) because they require Redis.
ALLOWED_SCHEMAS = {"smoke", "ga4", "patient", "stream_events"}

# Ops that aren't usable in the one-shot demo. They appear in the UI so
# visitors see the full surface, but submitting them returns a 400 with a
# pointer to the full deployment.
DEMO_DISABLED_OPS = {
    "burst": "burst signals the streaming rate-limiter; only fires inside a WebSocket stream.",
    "schema_drift": "schema_drift accumulates schema mutations across requests and needs Redis-backed state.",
    "data_drift": "data_drift accumulates field-distribution shifts across requests and needs Redis-backed state.",
}

# ── App + middleware ────────────────────────────────────────────────────────

app = FastAPI(
    title="Havocforge demo",
    docs_url=None,         # /docs surface not relevant for the demo
    redoc_url=None,
    openapi_url=None,
)

_rate_limiter = IpRateLimiter(max_requests=RATE_LIMIT_PER_MIN, window_seconds=60)


def _client_ip(request: Request) -> str:
    """Best-effort IP extraction. Cloudflare Tunnel sets cf-connecting-ip."""
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Static asset paths bypass the limiter — only API and root are limited.
    if request.url.path.startswith("/api/"):
        ip = _client_ip(request)
        if not _rate_limiter.allow(ip):
            return JSONResponse(
                {"error": "rate_limit_exceeded", "limit_per_minute": RATE_LIMIT_PER_MIN},
                status_code=429,
            )
    return await call_next(request)


# ── Static + index ──────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


# ── /api/schemas ────────────────────────────────────────────────────────────


def _schema_summary(name: str) -> dict[str, Any]:
    """Tiny preview info for the dropdown (label + a couple of root field hints)."""
    yaml_path = SCHEMAS_DIR / f"{name}.yaml"
    if not yaml_path.exists():
        return {"name": name, "label": name, "fields": []}

    import yaml

    raw = yaml.safe_load(yaml_path.read_text())
    fields = list((raw.get("fields") or {}).keys())[:6]
    return {
        "name": name,
        "label": name,
        "fields": fields,
        "field_count": len(raw.get("fields") or {}),
    }


@app.get("/api/schemas")
async def list_schemas() -> dict[str, Any]:
    schemas = sorted(ALLOWED_SCHEMAS)
    return {"schemas": [_schema_summary(s) for s in schemas]}


# ── Generation pipeline (sync, called via to_thread) ────────────────────────


_GENERATOR_CACHE: dict[str, object] = {}


def _load_generator(name: str):
    """Build + cache a generator from the schema's normalized contract tree.

    Uses the same path as the full server (``build_schema`` then
    ``engine_api.build`` over ``contracts_by_path``) — calling
    ``build_generator(spec)`` on the raw YAML skips the normalization and
    fails on schemas that use sugar syntax (e.g. ``one_of`` choices).
    """
    cached = _GENERATOR_CACHE.get(name)
    if cached is not None:
        return cached

    try:
        doc = SchemaRegistry.get(name)
    except (KeyError, SchemaRegistryKeyError):
        yaml_path = SCHEMAS_DIR / f"{name}.yaml"
        if not yaml_path.exists():
            raise HTTPException(status_code=404, detail=f"schema '{name}' not found")
        import yaml

        spec = yaml.safe_load(yaml_path.read_text())
        doc = build_schema(name, spec)
        SchemaRegistry.register(name, doc)

    gen = engine_api.build(doc.contracts_by_path)
    _GENERATOR_CACHE[name] = gen
    return gen


def _patch_time_ops(mgr, ops: list[str], items: list[dict[str, Any]], schema: str) -> None:
    """Auto-detect datetime fields for time_skew / schema_time_skew / late_arrival."""
    if not items or not isinstance(items[0], dict):
        return
    from havocforge.chaos.utils import parse_timestamp

    dt_fields = [k for k, v in items[0].items() if parse_timestamp(v)[0] is not None]
    if dt_fields:
        for op in ("time_skew", "schema_time_skew"):
            if op in ops and op in mgr._op_params_by_name:
                mgr._op_params_by_name[op]["fields"] = dt_fields
                cls = mgr.registry.get(op)
                if cls:
                    try:
                        mgr._op_instances[op] = cls(**mgr._op_params_by_name[op])
                    except Exception:
                        pass

    if "late_arrival" in ops and "late_arrival" in mgr._op_params_by_name:
        from havocforge.chaos import get_temporal_tracker
        import datetime as _dt

        tracker = get_temporal_tracker()
        now_us = int(_dt.datetime.now(_dt.timezone.utc).timestamp() * 1_000_000)
        try:
            tracker.get_or_init(schema, now_us - 2 * 3600 * 1_000_000)
            tracker.update_timeline(schema, now_us)
        except Exception:
            pass
        mgr._op_params_by_name["late_arrival"]["schema_name"] = schema
        cls = mgr.registry.get("late_arrival")
        if cls:
            try:
                mgr._op_instances["late_arrival"] = cls(**mgr._op_params_by_name["late_arrival"])
            except Exception:
                pass


def _generate(schema: str, count: int, seed: int | None, ops: list[str] | None) -> dict[str, Any]:
    """One generation run. Returns items, elapsed_ms, status, applied descriptions, headers."""
    gen = _load_generator(schema)
    ctx = GenContext(seed=seed)
    ctx.schema_name = schema

    t0 = time.perf_counter()
    items = [gen.generate(ctx) for _ in range(count)]
    gen_ms = round((time.perf_counter() - t0) * 1000, 2)

    chaos_applied: list[str] = []
    headers: dict[str, str] = {}
    status = 200

    if ops:
        mgr = get_chaos_manager(ctx)
        _patch_time_ops(mgr, ops, items, schema)
        result, meta = mgr.apply(
            body={"items": items}, schema_name=schema, forced_activation=ops
        )
        body = getattr(result, "body", {})
        if isinstance(body, dict) and "items" in body:
            items = body["items"]
        chaos_applied = getattr(result, "descriptions", []) or []
        if meta:
            status = meta.get("status", 200)
            headers = dict(meta.get("headers") or {})

    return {
        "items": items,
        "elapsed_ms": gen_ms,
        "status": status,
        "chaos_applied": chaos_applied,
        "headers": headers,
    }


# ── /api/generate (the headline endpoint) ───────────────────────────────────


@app.get("/api/generate")
async def generate(
    schema: str = Query(..., description="One of: smoke, ga4, patient, stream_events"),
    count: int = Query(10, ge=1, le=MAX_COUNT),
    seed: int | None = Query(None),
    chaos_ops: str | None = Query(None, description="Comma-separated op names"),
):
    """Run the same seeded generation twice — once clean, once with chaos.

    The frontend consumes both halves and renders them side-by-side with
    per-field diff highlighting.
    """
    if schema not in ALLOWED_SCHEMAS:
        raise HTTPException(status_code=404, detail=f"schema '{schema}' is not exposed in the demo")

    raw_ops = [op.strip() for op in (chaos_ops or "").split(",") if op.strip()]
    for op in raw_ops:
        if op in DEMO_DISABLED_OPS:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "op_unavailable_in_demo",
                    "op": op,
                    "reason": DEMO_DISABLED_OPS[op],
                    "see": "https://github.com/<your-username>/havocforge#full-deployment",
                },
            )

    # Same seed for both runs so non-chaos fields match exactly — only chaos differs.
    effective_seed = seed if seed is not None else random.randint(0, 2**32 - 1)

    clean = await asyncio.to_thread(_generate, schema, count, effective_seed, None)
    if raw_ops:
        chaos = await asyncio.to_thread(_generate, schema, count, effective_seed, raw_ops)
    else:
        chaos = clean

    return JSONResponse(
        content={
            "clean": clean,
            "chaos": chaos,
            "request": {
                "schema": schema,
                "count": count,
                "seed": effective_seed,
                "ops": raw_ops,
            },
        }
    )


# ── /api/ops (catalog the UI renders the checklist from) ────────────────────


@app.get("/api/ops")
async def list_ops() -> dict[str, Any]:
    """Return the categorised op catalog with demo-availability flags."""
    catalog = {
        "body": [
            "truncate", "schema_field_nulling", "schema_bloat", "duplicate_items",
            "list_shuffle", "late_arrival", "time_skew", "schema_time_skew",
            "encoding_corrupt", "partial_load",
        ],
        "status": ["http_error", "http_mismatch", "auth_fault"],
        "server": ["latency"],
        "header": ["header_anomaly", "random_header_case"],
        "streaming": ["burst"],
        "drift": ["schema_drift", "data_drift"],
    }
    out: dict[str, list[dict[str, Any]]] = {}
    for category, ops in catalog.items():
        out[category] = []
        for op in ops:
            entry: dict[str, Any] = {"name": op, "available": op not in DEMO_DISABLED_OPS}
            if op in DEMO_DISABLED_OPS:
                entry["disabled_reason"] = DEMO_DISABLED_OPS[op]
            out[category].append(entry)
    return {"categories": out}
