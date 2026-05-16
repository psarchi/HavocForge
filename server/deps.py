"""Dependency providers for FastAPI routes (new schema pipeline)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import yaml
from fastapi import Request

from havocforge import api as engine_api
from havocforge.schema.builder import build_schema
from havocforge.schema.registry import SchemaRegistry
from havocforge.schema.errors import SchemaRegistryKeyError

_SCHEMAS_DIR = Path("schemas")
_GENERATOR_CACHE: Dict[str, Tuple[int, object]] = {}


def _load_schema_from_disk(name: str):
    """Load a schema document from disk and register it."""
    p = _SCHEMAS_DIR / f"{name}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"schema file not found for '{name}': {p}")
    payload = yaml.safe_load(p.read_text(encoding="utf-8"))
    doc = build_schema(name, payload)
    SchemaRegistry.register(name, doc)
    return doc


def get_generator(name: str):
    """Return a generator built from the latest registered revision of ``name``."""
    from havocforge.chaos.drift import get_drift_coordinator

    coordinator = get_drift_coordinator()
    active_layers = coordinator.active_layers(name)

    if active_layers:
        newest_layer = active_layers[-1]
        target_name = newest_layer.revision
    else:
        target_name = name

    for layer in active_layers:
        remaining = coordinator.record_hit(name, layer.strategy)
        if not remaining:
            continue

    try:
        doc = SchemaRegistry.get(target_name)
    except (KeyError, SchemaRegistryKeyError):
        doc = _load_schema_from_disk(name)

    latest_name = target_name
    revision = SchemaRegistry.get_revision(latest_name)

    cached = _GENERATOR_CACHE.get(latest_name)
    if cached and cached[0] == revision:
        return cached[1]

    gen = engine_api.build(doc.contracts_by_path)
    _GENERATOR_CACHE[latest_name] = (revision, gen)
    return gen


def warmup_all(limit: int | None = None) -> int:
    count = 0
    for p in sorted(_SCHEMAS_DIR.glob("*.yml")) + sorted(_SCHEMAS_DIR.glob("*.yaml")):
        if limit and count >= limit:
            break
        name = p.stem
        try:
            _ = get_generator(name)
            count += 1
        except Exception:
            continue
    return count


def get_settings():
    from havocforge.config import get_config_manager
    from havocforge.config.access import ensure_config_fresh

    cm = get_config_manager()
    ensure_config_fresh()
    return cm


async def get_redis(request: Request):
    """Get the shared Redis client from app state."""
    return request.app.state.redis


def get_correlation_redis(request: Request):
    """Get the sync Redis client for entity correlation lookups."""
    return getattr(request.app.state, "correlation_redis", None)
