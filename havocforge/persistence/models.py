"""Data models for persistence layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel


class StoredDataset(BaseModel):
    """Stored dataset model."""

    id: str
    schema_name: str
    data: dict[str, Any]
    metadata: dict[str, Any] | None = None
    seed: int | None = None
    chaos_applied: list[str] | None = None
    created_at: datetime
    expires_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class DatasetMetadata(BaseModel):
    """Dataset metadata without full data."""

    id: str
    schema_name: str
    seed: int | None = None
    count: int
    chaos_applied: list[str] | None = None
    created_at: datetime
    expires_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
