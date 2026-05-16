from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from havocforge.observability import (
    http_requests_total,
    http_request_duration_seconds,
    http_request_size_bytes,
    http_response_size_bytes,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to track request metrics.

    Automatically instruments all HTTP requests with:
    - Request counter (by method, endpoint, schema, status)
    - Request duration histogram (by method, endpoint, schema)
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        method = request.method
        endpoint = request.url.path
        schema = self._extract_schema(endpoint)

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                http_request_size_bytes.labels(
                    method=method, endpoint=endpoint
                ).observe(int(content_length))
            except (ValueError, TypeError):
                pass

        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time

        http_requests_total.labels(
            method=method,
            endpoint=endpoint,
            schema=schema or "unknown",
            status_code=response.status_code,
        ).inc()

        http_request_duration_seconds.labels(
            method=method, endpoint=endpoint, schema=schema or "unknown"
        ).observe(duration)

        response_length = response.headers.get("content-length")
        if response_length:
            try:
                http_response_size_bytes.labels(
                    endpoint=endpoint, schema=schema or "unknown"
                ).observe(int(response_length))
            except (ValueError, TypeError):
                pass

        return response

    @staticmethod
    def _extract_schema(endpoint: str) -> str | None:
        """Extract schema name from endpoint path.

        Supports patterns like:
        - /v1/schemas/{name}/generate
        - /v1/schemas/{name}/stream

        Args:
            endpoint: URL path

        Returns:
            Schema name or None if not found
        """
        parts = endpoint.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "v1" and parts[1] == "schemas":
            return parts[2]
        return None
