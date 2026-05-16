"""FastAPI application entrypoint.

Exposes a factory to construct the app and a module-level ``app`` instance.
Behavior is unchanged; formatting/docstrings/typing follow the golden style.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.routers import (
    admin_config,
    admin_chaos,
    admin_schemas,
    admin_generators,
    admin_pools,
    meta,
    schemas,
    data,
    streaming,
    publish,
    users,
)
from server.errors import build_error_response, build_unhandled_response
from server.logging import setup_logging
from server.middleware.correlation import CorrelationMiddleware
from server.middleware.metrics import MetricsMiddleware
from havocforge.errors import HavocforgeError, PoolEmptyError, SchemaConfigError
from havocforge.observability import get_metrics_app

__all__ = ["create_app", "app"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm configuration and generator caches on startup."""
    import asyncio
    from server.deps import get_settings, warmup_all
    from havocforge.persistence.metrics_collector import MetricsCollector

    # Setup structured logging
    setup_logging()

    warmup_all()
    cm = get_settings()

    try:
        server_cfg = cm.get_root("server")
        metrics_enabled = bool(server_cfg.observability.metrics_enabled)
    except (AttributeError, TypeError):
        metrics_enabled = False

    # Read persistence config
    try:
        persistence_cfg = cm.get_root("server").persistence
        redis_url = getattr(persistence_cfg.redis, "url", None)
        metrics_interval = getattr(
            persistence_cfg.metrics_collector, "interval_seconds", 30
        )
    except (AttributeError, TypeError):
        redis_url = None
        metrics_interval = 30

    # Initialize shared Redis client (API only writes to Redis)
    from havocforge.persistence import RedisClient
    import redis as redis_sync

    # Use bytes responses for streaming/pregen queue hot path (avoids per-item UTF-8 decode in redis-py).
    redis = RedisClient(redis_url, decode_responses=False)
    await redis.connect()
    app.state.redis = redis

    # Sync Redis client for entity correlation lookups during generation
    app.state.correlation_redis = redis_sync.Redis.from_url(
        redis_url or "redis://localhost:6379", decode_responses=True
    )

    # Construct publishers eagerly so concurrent first-requests can't race
    # to instantiate them (the previous lazy globals had this race).
    from server.routers.publish import init_publishers_from_config

    init_publishers_from_config(app)

    metrics_collector = None
    collector_task = None
    if metrics_enabled:
        metrics_collector = MetricsCollector(interval_seconds=metrics_interval)
        collector_task = asyncio.create_task(metrics_collector.start())

    from server.config_exporter import config_exporter_loop

    config_task = asyncio.create_task(config_exporter_loop())

    yield

    if metrics_collector is not None:
        await metrics_collector.stop()
    if collector_task is not None:
        collector_task.cancel()
    config_task.cancel()
    try:
        if collector_task is not None:
            await collector_task
    except asyncio.CancelledError:
        pass
    try:
        await config_task
    except asyncio.CancelledError:
        pass

    from server.routers.publish import shutdown_publishers

    await shutdown_publishers(app)

    await redis.close()
    app.state.correlation_redis.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        FastAPI: Configured application instance.
    """
    app = FastAPI(title="Mock Data API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(CorrelationMiddleware)

    from havocforge.config import get_config_manager

    try:
        server_cfg = get_config_manager().get_root("server")
        metrics_enabled = server_cfg.observability.metrics_enabled  # type: ignore
        metrics_path = server_cfg.observability.prometheus_path  # type: ignore
    except (AttributeError, TypeError):
        metrics_enabled = False
        metrics_path = "/metrics"

    if metrics_enabled:
        app.add_middleware(MetricsMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(admin_config.router)
    app.include_router(admin_chaos.router)
    app.include_router(admin_schemas.router)
    app.include_router(admin_generators.router)
    app.include_router(admin_pools.router)
    app.include_router(meta.router)
    app.include_router(schemas.router)
    app.include_router(data.router)
    app.include_router(streaming.router)
    app.include_router(publish.router)
    app.include_router(users.router)

    if metrics_enabled:
        app.mount(metrics_path, get_metrics_app())

    @app.exception_handler(HavocforgeError)
    async def handle_engine_error(request, exc: HavocforgeError):
        return build_error_response(exc, request)

    @app.exception_handler(PoolEmptyError)
    async def handle_pool_empty_error(request, exc: PoolEmptyError):
        return build_error_response(exc, request)

    @app.exception_handler(SchemaConfigError)
    async def handle_schema_config_error(request, exc: SchemaConfigError):
        return build_error_response(exc, request)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request, exc: Exception):
        return build_unhandled_response(exc, request)

    return app


app = create_app()
