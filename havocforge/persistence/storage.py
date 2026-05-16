"""Unified storage interface for persistence operations."""

from __future__ import annotations

import hashlib
import json
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from havocforge.persistence.client import RedisClient, PostgresClient
from havocforge.persistence.id_generator import generate_id
from havocforge.persistence.models import StoredDataset, DatasetMetadata
from havocforge.observability import (
    persistence_writes_total,
    persistence_reads_total,
    persistence_cache_hits_total,
    persistence_cache_misses_total,
    persistence_errors_total,
    persistence_dataset_size_bytes,
    persistence_redis_writes_total,
)


class StorageManager:
    """Unified storage manager for Redis and PostgreSQL."""

    def __init__(
        self,
        redis_client: RedisClient | None = None,
        postgres_client: PostgresClient | None = None,
        config: dict[str, Any] | None = None,
    ):
        self.redis = redis_client or RedisClient()
        self.postgres = postgres_client or PostgresClient()
        self.config = config or self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load persistence configuration."""
        config_path = Path("config/default/persistence.yaml")
        if config_path.exists():
            with open(config_path) as f:
                return yaml.safe_load(f)
        return self._default_config()

    def _default_config(self) -> dict[str, Any]:
        """Default configuration."""
        return {
            "persistence": {
                "enabled": True,
                "redis": {"ttl_hours": 24},
                "postgres": {"retention_days": 30},
                "schema_tracking": {"enabled": True, "hash_algorithm": "sha256"},
            }
        }

    async def connect(self) -> None:
        """Connect to Redis and PostgreSQL."""
        await self.redis.connect()
        await self.postgres.connect()

    async def close(self) -> None:
        """Close Redis and PostgreSQL connections."""
        await self.redis.close()
        await self.postgres.close()

    async def save(
        self,
        schema_name: str,
        data: dict[str, Any],
        seed: int | None = None,
        chaos_applied: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Save dataset to Redis (async write to PostgreSQL via watcher).

        Args:
            schema_name: Schema name
            data: Dataset items
            seed: Optional seed
            chaos_applied: Optional chaos operations
            metadata: Optional additional metadata

        Returns:
            Generated dataset ID
        """
        dataset_id = generate_id()

        ttl_hours = (
            self.config.get("persistence", {}).get("redis", {}).get("ttl_hours", 24)
        )
        retention_days = (
            self.config.get("persistence", {})
            .get("postgres", {})
            .get("retention_days", 30)
        )

        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(days=retention_days)

        schema_hash = None
        if (
            self.config.get("persistence", {})
            .get("schema_tracking", {})
            .get("enabled", True)
        ):
            schema_hash = self._compute_schema_hash(schema_name)

        stored_data = {
            "id": dataset_id,
            "schema_name": schema_name,
            "data": data,
            "metadata": metadata or {},
            "seed": seed,
            "chaos_applied": chaos_applied or [],
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "schema_hash": schema_hash,
        }

        try:
            await self.redis.set(dataset_id, stored_data, ttl_hours=ttl_hours)

            dataset_size = len(json.dumps(stored_data).encode("utf-8"))
            persistence_dataset_size_bytes.labels(schema=schema_name).observe(
                dataset_size
            )

            persistence_writes_total.labels(schema=schema_name, status="success").inc()
            persistence_redis_writes_total.labels(
                schema=schema_name, status="success"
            ).inc()

        except Exception as e:
            persistence_writes_total.labels(schema=schema_name, status="error").inc()
            persistence_redis_writes_total.labels(
                schema=schema_name, status="error"
            ).inc()
            persistence_errors_total.labels(
                operation="save", error_type=type(e).__name__
            ).inc()
            raise

        return dataset_id

    async def retrieve(self, dataset_id: str) -> StoredDataset | None:
        """Retrieve dataset from Redis (hot) or PostgreSQL (warm).

        Args:
            dataset_id: Dataset ID

        Returns:
            StoredDataset or None if not found
        """
        data = await self.redis.get(dataset_id)

        if data:
            schema_name = data.get("schema_name", "unknown")
            persistence_reads_total.labels(schema=schema_name, source="redis").inc()
            persistence_cache_hits_total.labels(schema=schema_name).inc()
            return StoredDataset(**data)

        pg_data = await self.postgres.get(dataset_id)

        if pg_data:
            schema_name = pg_data.get("schema_name", "unknown")
            persistence_reads_total.labels(schema=schema_name, source="postgres").inc()
            persistence_cache_misses_total.labels(schema=schema_name).inc()

            # Serialize datetime objects before caching to Redis
            cache_data = pg_data.copy()
            if isinstance(cache_data.get("created_at"), datetime):
                cache_data["created_at"] = cache_data["created_at"].isoformat()
            if isinstance(cache_data.get("expires_at"), datetime):
                cache_data["expires_at"] = cache_data["expires_at"].isoformat()

            await self.redis.set(
                dataset_id,
                cache_data,
                ttl_hours=self.config.get("persistence", {})
                .get("redis", {})
                .get("ttl_hours", 24),
            )
            return StoredDataset(**pg_data)

        return None

    async def retrieve_metadata(self, dataset_id: str) -> DatasetMetadata | None:
        """Retrieve dataset metadata only (no items).

        Args:
            dataset_id: Dataset ID

        Returns:
            DatasetMetadata or None if not found
        """
        dataset = await self.retrieve(dataset_id)

        if dataset:
            return DatasetMetadata(
                id=dataset.id,
                schema_name=dataset.schema_name,
                seed=dataset.seed,
                count=len(dataset.data.get("items", [])),
                chaos_applied=dataset.chaos_applied,
                created_at=dataset.created_at,
                expires_at=dataset.expires_at,
            )

        return None

    async def delete(self, dataset_id: str) -> bool:
        """Delete dataset from both Redis and PostgreSQL.

        Args:
            dataset_id: Dataset ID

        Returns:
            True if deleted from at least one store
        """
        redis_deleted = await self.redis.delete(dataset_id)
        pg_deleted = await self.postgres.delete(dataset_id)

        return redis_deleted or pg_deleted

    def _compute_schema_hash(self, schema_name: str) -> str | None:
        """Compute hash of schema file for change detection.

        Args:
            schema_name: Schema name

        Returns:
            SHA256 hash or None if schema file not found
        """
        schema_path = Path(f"schemas/{schema_name}.yaml")

        if not schema_path.exists():
            return None

        with open(schema_path, "rb") as f:
            content = f.read()

        return hashlib.sha256(content).hexdigest()[:16]
