from __future__ import annotations

import json
import os
from typing import Any

import asyncpg
import redis.asyncio as redis
from datetime import datetime, timedelta, timezone

from havocforge.persistence.errors import (
    RedisConnectionError,
    RedisWriteError,
    RedisReadError,
    PostgresConnectionError,
    PostgresWriteError,
    DataSerializationError,
)


class RedisClient:
    """Async Redis client for caching."""

    def __init__(
        self,
        url: str | None = None,
        key_prefix: str = "data:",
        *,
        decode_responses: bool = True,
        encoding: str = "utf-8",
    ):
        self.url = url or os.getenv("REDIS_URL", "redis://localhost:6379")
        self.key_prefix = key_prefix
        self.decode_responses = decode_responses
        self.encoding = encoding
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        """Establish Redis connection."""
        if self._client is None:
            try:
                self._client = await redis.from_url(
                    self.url,
                    decode_responses=self.decode_responses,
                    encoding=self.encoding,
                )
            except Exception as e:
                raise RedisConnectionError(
                    f"Failed to connect to Redis at {self.url}: {e}"
                ) from e

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()

    def _make_key(self, id: str) -> str:
        """Create prefixed key."""
        return f"{self.key_prefix}{id}"

    async def set(self, id: str, data: dict[str, Any], ttl_hours: int = 24) -> bool:
        """Store dataset in Redis with TTL.

        Args:
            id: Dataset ID
            data: Dataset data to store
            ttl_hours: Time-to-live in hours

        Returns:
            True if successful
        """
        if not self._client:
            await self.connect()

        if not self._client:
            raise RedisConnectionError("Redis client not initialized")

        try:
            key = self._make_key(id)
            value = json.dumps(data)
            ttl_seconds = ttl_hours * 3600
            await self._client.set(key, value, ex=ttl_seconds)
            return True
        except (TypeError, ValueError) as e:
            raise DataSerializationError(
                f"Failed to serialize data for {id}: {e}"
            ) from e
        except Exception as e:
            raise RedisWriteError(f"Failed to write to Redis key {id}: {e}") from e

    async def set_nx(self, key: str, data: dict[str, Any]) -> bool:
        """Store data in Redis only if the key does not already exist.

        Args:
            key: Full Redis key (no prefix applied)
            data: Data to store

        Returns:
            True if stored, False if key already existed
        """
        if not self._client:
            await self.connect()

        if not self._client:
            raise RedisConnectionError("Redis client not initialized")

        try:
            value = json.dumps(data)
            result = await self._client.set(key, value, nx=True)
            return result is not None
        except (TypeError, ValueError) as e:
            raise DataSerializationError(
                f"Failed to serialize data for {key}: {e}"
            ) from e
        except Exception as e:
            raise RedisWriteError(f"Failed to set_nx Redis key {key}: {e}") from e

    async def get(self, id: str) -> dict[str, Any] | None:
        """Retrieve dataset from Redis.

        Args:
            id: Dataset ID

        Returns:
            Dataset data or None if not found
        """
        if not self._client:
            await self.connect()

        if not self._client:
            raise RedisConnectionError("Redis client not initialized")

        try:
            key = self._make_key(id)
            value = await self._client.get(key)

            if value:
                return json.loads(value)
            return None
        except (TypeError, ValueError, json.JSONDecodeError) as e:
            raise DataSerializationError(
                f"Failed to deserialize data for {id}: {e}"
            ) from e
        except Exception as e:
            raise RedisReadError(f"Failed to read from Redis key {id}: {e}") from e

    async def delete(self, id: str) -> bool:
        """Delete dataset from Redis.

        Args:
            id: Dataset ID

        Returns:
            True if deleted, False if not found
        """
        if not self._client:
            await self.connect()

        key = self._make_key(id)
        result = await self._client.delete(key)
        return result > 0

    async def keys(self, pattern: str = "*") -> list[str]:
        """Get all keys matching pattern.

        Args:
            pattern: Redis key pattern (default: "*")

        Returns:
            List of matching keys
        """
        if not self._client:
            await self.connect()

        full_pattern = f"{self.key_prefix}{pattern}"
        keys = await self._client.keys(full_pattern)

        out: list[str] = []
        for key in keys:
            if isinstance(key, bytes):
                key_str = key.decode(self.encoding, errors="replace")
            else:
                key_str = str(key)

            if key_str.startswith(self.key_prefix):
                key_str = key_str[len(self.key_prefix) :]
            else:
                key_str = key_str.replace(self.key_prefix, "", 1)
            out.append(key_str)

        return out

    async def rpop(self, key: str) -> bytes | None:
        """Remove and return the last element from a list.

        Args:
            key: List key (without prefix)

        Returns:
            The popped element or None if list is empty
        """
        if not self._client:
            await self.connect()

        if not self._client:
            raise RedisConnectionError("Redis client not initialized")

        try:
            # Don't use key prefix for queue keys
            return await self._client.rpop(key)
        except Exception as e:
            raise RedisReadError(f"Failed to rpop from Redis key {key}: {e}") from e

    async def lpop(self, key: str, count: int | None = None):
        """Pop one or more items from the head of a list without key prefix."""
        if not self._client:
            await self.connect()

        if not self._client:
            raise RedisConnectionError("Redis client not initialized")

        try:
            if count is None:
                return await self._client.lpop(key)
            return await self._client.lpop(key, count)
        except Exception as e:
            raise RedisReadError(f"Failed to lpop from Redis key {key}: {e}") from e

    async def lpush(self, key: str, *values: bytes) -> int:
        """Push one or more values to the head of a list.

        Args:
            key: List key (without prefix)
            values: Values to push

        Returns:
            The length of the list after push
        """
        if not self._client:
            await self.connect()

        if not self._client:
            raise RedisConnectionError("Redis client not initialized")

        try:
            # Don't use key prefix for queue keys
            return await self._client.lpush(key, *values)
        except Exception as e:
            raise RedisWriteError(f"Failed to lpush to Redis key {key}: {e}") from e

    async def llen(self, key: str) -> int:
        """Get the length of a list.

        Args:
            key: List key (without prefix)

        Returns:
            The length of the list
        """
        if not self._client:
            await self.connect()

        if not self._client:
            raise RedisConnectionError("Redis client not initialized")

        try:
            # Don't use key prefix for queue keys
            return await self._client.llen(key)
        except Exception as e:
            raise RedisReadError(f"Failed to get length of Redis key {key}: {e}") from e

    async def ltrim(self, key: str, start: int, stop: int) -> bool:
        """Trim a list to the specified range.

        Args:
            key: List key (without prefix)
            start: Start index
            stop: Stop index

        Returns:
            True if successful
        """
        if not self._client:
            await self.connect()

        if not self._client:
            raise RedisConnectionError("Redis client not initialized")

        try:
            # Don't use key prefix for queue keys
            await self._client.ltrim(key, start, stop)
            return True
        except Exception as e:
            raise RedisWriteError(f"Failed to ltrim Redis key {key}: {e}") from e

    async def hgetall(self, key: str) -> dict[Any, Any]:
        """Fetch all hash fields without key prefix."""
        if not self._client:
            await self.connect()

        if not self._client:
            raise RedisConnectionError("Redis client not initialized")

        try:
            return await self._client.hgetall(key)
        except Exception as e:
            raise RedisReadError(f"Failed to hgetall Redis key {key}: {e}") from e

    async def hset(self, key: str, mapping: dict[str, Any]) -> bool:
        """Set multiple hash fields without key prefix."""
        if not self._client:
            await self.connect()

        if not self._client:
            raise RedisConnectionError("Redis client not initialized")

        try:
            await self._client.hset(key, mapping=mapping)  # type: ignore[arg-type]
            return True
        except Exception as e:
            raise RedisWriteError(f"Failed to hset Redis key {key}: {e}") from e

    @property
    def client(self):
        """Expose underlying Redis client for advanced operations."""
        return self._client


class PostgresClient:
    """Async PostgreSQL client for long-term storage."""

    def __init__(self, url: str | None = None):
        self.url = url or os.getenv(
            "DATABASE_URL",
            "postgresql://havocforge:havocforge@localhost:5432/havocforge",
        )
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Establish PostgreSQL connection pool."""
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    self.url, min_size=5, max_size=10
                )
            except Exception as e:
                raise PostgresConnectionError(
                    f"Failed to connect to PostgreSQL at {self.url}: {e}"
                ) from e

    async def close(self) -> None:
        """Close PostgreSQL connection pool."""
        if self._pool:
            await self._pool.close()

    async def insert(
        self,
        id: str,
        schema_name: str,
        data: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        seed: int | None = None,
        chaos_applied: list[str] | None = None,
        retention_days: int = 30,
    ) -> bool:
        """Insert dataset into PostgreSQL.

        Args:
            id: Dataset ID
            schema_name: Schema name
            data: Dataset data
            metadata: Optional metadata
            seed: Optional seed value
            chaos_applied: Optional list of chaos ops
            retention_days: Days before expiration

        Returns:
            True if successful
        """
        if not self._pool:
            await self.connect()

        if not self._pool:
            raise PostgresConnectionError("PostgreSQL connection pool not initialized")

        try:
            expires_at = datetime.now(timezone.utc) + timedelta(days=retention_days)

            query = """
                INSERT INTO datasets
                (id, schema_name, data, metadata, seed, chaos_applied, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (id) DO NOTHING
            """

            async with self._pool.acquire() as conn:
                await conn.execute(
                    query,
                    id,
                    schema_name,
                    json.dumps(data),
                    json.dumps(metadata) if metadata else None,
                    str(seed) if seed is not None else None,
                    chaos_applied,
                    expires_at,
                )

            return True
        except (TypeError, ValueError) as e:
            raise DataSerializationError(
                f"Failed to serialize data for {id}: {e}"
            ) from e
        except Exception as e:
            raise PostgresWriteError(
                f"Failed to insert dataset {id} into PostgreSQL: {e}"
            ) from e

    async def get(self, id: str) -> dict[str, Any] | None:
        """Retrieve dataset from PostgreSQL.

        Args:
            id: Dataset ID

        Returns:
            Dataset record or None if not found
        """
        if not self._pool:
            await self.connect()

        query = """
            SELECT id, schema_name, data, metadata, seed, chaos_applied,
                   created_at, expires_at
            FROM datasets
            WHERE id = $1 AND expires_at > NOW()
        """

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, id)

        if row:
            return {
                "id": row["id"],
                "schema_name": row["schema_name"],
                "data": json.loads(row["data"]),
                "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
                "seed": row["seed"],
                "chaos_applied": row["chaos_applied"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
            }

        return None

    async def delete(self, id: str) -> bool:
        """Delete dataset from PostgreSQL.

        Args:
            id: Dataset ID

        Returns:
            True if deleted, False if not found
        """
        if not self._pool:
            await self.connect()

        query = "DELETE FROM datasets WHERE id = $1"

        async with self._pool.acquire() as conn:
            result = await conn.execute(query, id)

        return "DELETE 1" in result

    async def cleanup_expired(self) -> int:
        """Delete expired datasets.

        Returns:
            Number of deleted records
        """
        if not self._pool:
            await self.connect()

        query = "SELECT cleanup_expired_datasets()"

        async with self._pool.acquire() as conn:
            result = await conn.fetchval(query)

        return result or 0

    async def find_missing_ids(self, redis_ids: list[str]) -> list[str]:
        """Find IDs that exist in Redis but not in PostgreSQL.

        Args:
            redis_ids: List of IDs from Redis

        Returns:
            List of IDs missing in PostgreSQL
        """
        if not self._pool or not redis_ids:
            return []

        query = """
            SELECT id FROM datasets
            WHERE id = ANY($1::text[])
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, redis_ids)

        existing_ids = {row["id"] for row in rows}
        return [id for id in redis_ids if id not in existing_ids]

    async def list_datasets(
        self, offset: int = 0, limit: int = 50
    ) -> tuple[list[dict[str, Any]], int]:
        """List datasets with pagination.

        Args:
            offset: Number of records to skip
            limit: Number of records to return

        Returns:
            Tuple of (list of dataset metadata dicts, total count)
        """
        if not self._pool:
            await self.connect()

        count_query = "SELECT COUNT(*) FROM datasets WHERE expires_at > NOW()"
        async with self._pool.acquire() as conn:
            total = await conn.fetchval(count_query)

        query = """
            SELECT id, schema_name, seed, chaos_applied, created_at, expires_at,
                   jsonb_array_length(data->'items') as count
            FROM datasets
            WHERE expires_at > NOW()
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, limit, offset)

        datasets = [
            {
                "id": row["id"],
                "schema_name": row["schema_name"],
                "seed": row["seed"],
                "count": row["count"] or 0,
                "chaos_applied": row["chaos_applied"] or [],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
            }
            for row in rows
        ]

        return datasets, total or 0
