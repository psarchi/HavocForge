from __future__ import annotations

import asyncio
import json
import os
import sys
import time

from prometheus_client import start_http_server

from havocforge.persistence.client import RedisClient, PostgresClient
from havocforge.persistence.errors import (
    RedisError,
    PostgresError,
    DataSerializationError,
)
from havocforge.observability import (
    registry,
    persistence_postgres_writes_total,
    persistence_batch_sync_datasets_synced,
    persistence_batch_sync_bytes_synced,
    persistence_batch_sync_last_run_timestamp,
)


class BatchSync:
    """Periodic batch sync from Redis to PostgreSQL."""

    def __init__(
        self,
        redis_url: str | None = None,
        postgres_url: str | None = None,
        interval_seconds: int = 300,
        batch_limit: int = 1000,
    ):
        self.redis = RedisClient(redis_url)
        self.postgres = PostgresClient(postgres_url)
        self.interval_seconds = interval_seconds
        self.batch_limit = batch_limit
        self._running = False

    async def start(self) -> None:
        """Start periodic batch sync with drain-until-empty mode."""
        self._running = True

        await self.redis.connect()
        await self.postgres.connect()

        print(
            f"Batch sync started (interval: {self.interval_seconds}s, batch_limit: {self.batch_limit})",
            file=sys.stderr,
        )

        try:
            while self._running:
                total_synced = 0
                batch_count = 0

                while self._running:
                    synced = await self._sync_batch()
                    total_synced += synced
                    batch_count += 1

                    if synced == 0:
                        break

                if batch_count > 1:
                    print(
                        f"Drain complete: {total_synced} datasets synced across {batch_count} batches",
                        file=sys.stderr,
                    )
                elif total_synced > 0:
                    print(
                        f"Batch sync complete: {total_synced} datasets synced",
                        file=sys.stderr,
                    )

                await asyncio.sleep(self.interval_seconds)

        except asyncio.CancelledError:
            print("Batch sync stopped", file=sys.stderr)
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop batch sync."""
        self._running = False
        await self.redis.close()
        await self.postgres.close()

    async def _sync_batch(self) -> int:
        """Sync a batch of datasets from Redis to PostgreSQL.

        Returns:
            Number of datasets synced
        """
        try:
            redis_keys = await self.redis.keys("*")

            if not redis_keys:
                persistence_batch_sync_last_run_timestamp.set(time.time())
                return 0

            redis_keys = redis_keys[: self.batch_limit]

            redis_ids = redis_keys
            print(f"Found {len(redis_ids)} Redis keys to check", file=sys.stderr)

            missing_ids = await self.postgres.find_missing_ids(redis_ids)
            print(
                f"Found {len(missing_ids)} missing datasets in PostgreSQL",
                file=sys.stderr,
            )

            existing_ids = [id for id in redis_ids if id not in missing_ids]
            print(
                f"Found {len(existing_ids)} datasets already in PostgreSQL (will delete from Redis)",
                file=sys.stderr,
            )

            cleanup_count = 0
            for dataset_id in existing_ids:
                await self.redis.delete(dataset_id)
                cleanup_count += 1

            if not missing_ids:
                persistence_batch_sync_last_run_timestamp.set(time.time())
                return cleanup_count

            synced_count = 0
            total_bytes = 0

            for dataset_id in missing_ids:
                data = await self.redis.get(dataset_id)

                if not data:
                    continue

                schema_name = data.get("schema_name", "unknown")

                try:
                    await self.postgres.insert(
                        id=dataset_id,
                        schema_name=schema_name,
                        data=data.get("data", {}),
                        metadata=data.get("metadata"),
                        seed=data.get("seed"),
                        chaos_applied=data.get("chaos_applied"),
                    )

                    data_bytes = len(json.dumps(data).encode("utf-8"))
                    total_bytes += data_bytes

                    persistence_postgres_writes_total.labels(
                        schema=schema_name, status="success"
                    ).inc()
                    synced_count += 1

                    await self.redis.delete(dataset_id)
                    print(
                        f"Synced and deleted dataset {dataset_id} from Redis",
                        file=sys.stderr,
                    )

                except (RedisError, PostgresError, DataSerializationError) as e:
                    persistence_postgres_writes_total.labels(
                        schema=schema_name, status="error"
                    ).inc()
                    print(
                        f"Persistence error syncing dataset {dataset_id}: {e}",
                        file=sys.stderr,
                    )
                except Exception as e:
                    persistence_postgres_writes_total.labels(
                        schema=schema_name, status="error"
                    ).inc()
                    print(
                        f"Unexpected error syncing dataset {dataset_id}: {e}",
                        file=sys.stderr,
                    )

            persistence_batch_sync_datasets_synced.inc(synced_count)
            persistence_batch_sync_bytes_synced.inc(total_bytes)
            persistence_batch_sync_last_run_timestamp.set(time.time())

            return cleanup_count + synced_count

        except (RedisError, PostgresError) as e:
            print(f"Connection error during batch sync: {e}", file=sys.stderr)
            persistence_batch_sync_last_run_timestamp.set(time.time())
            return 0
        except Exception as e:
            print(f"Unexpected error during batch sync: {e}", file=sys.stderr)
            persistence_batch_sync_last_run_timestamp.set(time.time())
            return 0


async def main():
    """Run the batch sync daemon."""
    from havocforge.config import get_config_manager

    try:
        cm = get_config_manager()
        cfg = cm.get_root("server").persistence.batch_sync

        metrics_port = int(
            os.getenv("METRICS_PORT", getattr(cfg, "metrics_port", 8001))
        )
        interval = int(
            os.getenv("SYNC_INTERVAL", getattr(cfg, "interval_seconds", 300))
        )
        batch_limit = int(os.getenv("BATCH_LIMIT", getattr(cfg, "batch_limit", 1000)))

        persistence_cfg = cm.get_root("server").persistence
        redis_url = os.getenv("REDIS_URL", getattr(persistence_cfg.redis, "url", None))
        postgres_url = os.getenv(
            "DATABASE_URL", getattr(persistence_cfg.postgres, "url", None)
        )

    except (AttributeError, TypeError, Exception):
        metrics_port = int(os.getenv("METRICS_PORT", "8001"))
        interval = int(os.getenv("SYNC_INTERVAL", "300"))
        batch_limit = int(os.getenv("BATCH_LIMIT", "1000"))
        redis_url = os.getenv("REDIS_URL")
        postgres_url = os.getenv("DATABASE_URL")

    start_http_server(metrics_port, registry=registry)
    print(f"Batch sync metrics exposed on port {metrics_port}", file=sys.stderr)

    sync = BatchSync(
        redis_url=redis_url,
        postgres_url=postgres_url,
        interval_seconds=interval,
        batch_limit=batch_limit,
    )

    try:
        await sync.start()
    except KeyboardInterrupt:
        await sync.stop()


if __name__ == "__main__":
    asyncio.run(main())
