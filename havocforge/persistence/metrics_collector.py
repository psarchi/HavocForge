from __future__ import annotations

import asyncio
import json
import os
import sys

from havocforge.persistence.client import RedisClient, PostgresClient
from havocforge.observability import (
    persistence_redis_cache_size_mb,
    persistence_postgres_cache_size_mb,
)


class MetricsCollector:
    """Collects cache size metrics from Redis and PostgreSQL."""

    def __init__(
        self,
        redis_url: str | None = None,
        postgres_url: str | None = None,
        interval_seconds: int = 30,
    ):
        self.redis = RedisClient(redis_url)
        self.postgres = PostgresClient(postgres_url)
        self.interval_seconds = interval_seconds
        self._running = False

    async def start(self) -> None:
        """Start periodic metrics collection."""
        self._running = True

        await self.redis.connect()
        await self.postgres.connect()

        print(
            f"Metrics collector started (interval: {self.interval_seconds}s)",
            file=sys.stderr,
        )

        try:
            while self._running:
                await self._collect_metrics()
                await asyncio.sleep(self.interval_seconds)

        except asyncio.CancelledError:
            print("Metrics collector stopped", file=sys.stderr)
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop metrics collection."""
        self._running = False
        await self.redis.close()
        await self.postgres.close()

    async def _collect_metrics(self) -> None:
        """Collect cache size metrics from Redis and PostgreSQL."""
        try:
            await self._collect_redis_sizes()
            await self._collect_postgres_sizes()

        except Exception as e:
            print(f"Error collecting metrics: {e}", file=sys.stderr)

    async def _collect_redis_sizes(self) -> None:
        """Query Redis for cache sizes by schema."""
        try:
            keys = await self.redis.keys("*")

            if not keys:
                return

            schema_sizes: dict[str, int] = {}

            for key in keys:
                data = await self.redis.get(key)
                if not data:
                    continue

                schema_name = data.get("schema_name", "unknown")
                data_bytes = len(json.dumps(data).encode("utf-8"))

                if schema_name not in schema_sizes:
                    schema_sizes[schema_name] = 0
                schema_sizes[schema_name] += data_bytes

            for schema_name, size_bytes in schema_sizes.items():
                size_mb = size_bytes / (1024 * 1024)
                persistence_redis_cache_size_mb.labels(schema=schema_name).set(size_mb)

        except Exception as e:
            print(f"Error collecting Redis sizes: {e}", file=sys.stderr)

    async def _collect_postgres_sizes(self) -> None:
        """Query PostgreSQL for storage sizes by schema."""
        try:
            if not self.postgres._pool:
                return

            query = """
                SELECT
                    schema_name,
                    SUM(pg_column_size(data)) as size_bytes
                FROM datasets
                WHERE expires_at > NOW()
                GROUP BY schema_name
            """

            async with self.postgres._pool.acquire() as conn:
                rows = await conn.fetch(query)

                for row in rows:
                    schema_name = row["schema_name"]
                    size_bytes = row["size_bytes"] or 0
                    size_mb = size_bytes / (1024 * 1024)
                    persistence_postgres_cache_size_mb.labels(schema=schema_name).set(
                        size_mb
                    )

        except Exception as e:
            print(f"Error collecting PostgreSQL sizes: {e}", file=sys.stderr)


async def main():
    """Run the metrics collector daemon."""
    from prometheus_client import start_http_server
    from havocforge.observability import registry
    from havocforge.config import get_config_manager

    try:
        cm = get_config_manager()
        server_cfg = cm.get_root("server")
        metrics_enabled = bool(server_cfg.observability.metrics_enabled)
        if not metrics_enabled:
            print(
                "Metrics disabled via server.observability.metrics_enabled; exiting",
                file=sys.stderr,
            )
            return
        cfg = cm.get_root("server").persistence.metrics_collector

        metrics_port = int(
            os.getenv("METRICS_PORT", getattr(cfg, "metrics_port", 8003))
        )
        interval = int(
            os.getenv("METRICS_INTERVAL", getattr(cfg, "interval_seconds", 30))
        )

    except (AttributeError, TypeError, Exception):
        metrics_port = int(os.getenv("METRICS_PORT", "8003"))
        interval = int(os.getenv("METRICS_INTERVAL", "30"))

    start_http_server(metrics_port, registry=registry)
    print(
        f"Metrics collector HTTP server started on port {metrics_port}", file=sys.stderr
    )

    collector = MetricsCollector(interval_seconds=interval)

    try:
        await collector.start()
    except KeyboardInterrupt:
        await collector.stop()


if __name__ == "__main__":
    asyncio.run(main())
