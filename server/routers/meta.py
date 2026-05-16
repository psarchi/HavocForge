
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/v1", tags=["meta"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return liveness status and an ISO-8601 UTC timestamp.

    Returns:
        dict[str, str]: Mapping with keys:
            - ``status``: Always ``"ok"`` when the service is alive.
            - ``ts``: Current time in ISO-8601 with ``Z`` (UTC) designator.
    """
    # TODO(observability): Attach build/version/commit metadata when available.
    return {"status": "ok", "ts": datetime.now(UTC).isoformat()}


@router.get("/health/live")
def health_live() -> dict[str, str]:
    """Liveness probe - check if application is running.

    Returns:
        dict[str, str]: Status and timestamp.
    """
    return {"status": "ok", "ts": datetime.now(UTC).isoformat()}


@router.get("/health/ready")
async def health_ready(request: Request) -> JSONResponse:
    """Readiness probe - check if application dependencies are healthy.

    Checks:
        - Redis connectivity
        - PostgreSQL connectivity

    Returns:
        JSONResponse: 200 if all dependencies healthy, 503 if any unhealthy.
    """
    checks = {"redis": "unknown", "postgres": "unknown"}
    all_healthy = True

    try:
        redis_client = request.app.state.redis
        if redis_client and redis_client.client:
            await redis_client.client.ping()
            checks["redis"] = "healthy"
        else:
            checks["redis"] = "not_connected"
            all_healthy = False
    except Exception as e:
        checks["redis"] = f"unhealthy: {str(e)[:50]}"
        all_healthy = False

    try:
        from havocforge.persistence.client import PostgresClient

        pg_client = PostgresClient()
        await pg_client.connect()
        if pg_client._pool:
            async with pg_client._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            checks["postgres"] = "healthy"
            await pg_client.close()
        else:
            checks["postgres"] = "not_connected"
            all_healthy = False
    except Exception as e:
        checks["postgres"] = f"unhealthy: {str(e)[:50]}"
        all_healthy = False

    response_status = status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=response_status,
        content={
            "status": "ready" if all_healthy else "not_ready",
            "checks": checks,
            "ts": datetime.now(UTC).isoformat(),
        },
    )
