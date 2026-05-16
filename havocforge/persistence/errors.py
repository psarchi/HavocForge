from __future__ import annotations

"""Persistence subsystem error hierarchy.

High-level persistence errors are defined here for Redis, PostgreSQL,
storage operations, and batch synchronization.
"""

from havocforge.errors import PersistenceError as BasePersistenceError  # noqa: E402

PersistenceError = BasePersistenceError


class StorageError(PersistenceError):
    """Storage operation failures."""


class RedisError(StorageError):
    """Redis connection or operation failures."""


class RedisConnectionError(RedisError):
    """Failed to connect to Redis."""


class RedisWriteError(RedisError):
    """Failed to write data to Redis."""


class RedisReadError(RedisError):
    """Failed to read data from Redis."""


class PostgresError(StorageError):
    """PostgreSQL connection or operation failures."""


class PostgresConnectionError(PostgresError):
    """Failed to connect to PostgreSQL."""


class PostgresWriteError(PostgresError):
    """Failed to write data to PostgreSQL."""


class PostgresReadError(PostgresError):
    """Failed to read data from PostgreSQL."""


class BatchSyncError(PersistenceError):
    """Batch synchronization failures."""


class SyncConfigError(BatchSyncError):
    """Invalid or missing batch sync configuration."""


class DataSerializationError(PersistenceError):
    """Failed to serialize/deserialize data."""
