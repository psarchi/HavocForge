from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict


class PreflightFailure(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str
    error: str


class PreflightReport(BaseModel):
    """Summary of deterministic preflight generation attempts."""

    model_config = ConfigDict(extra="allow")
    seeds: List[int]
    samples: int
    failures: List[PreflightFailure] = []
    arrays_materialized: int = 0
    union_choices_hit: Dict[str, int] = {}


class SchemaDoc(BaseModel):
    """Top-level schema artifact returned by the schema pipeline."""

    model_config = ConfigDict(extra="allow")
    name: str
    source_path: Optional[str] = None
    checksum: Optional[str] = None
    contracts_tree: Any
    contracts_by_path: Dict[str, Any]
    engine_spec: Optional[Dict[str, Any]] = None
    preflight: Optional[PreflightReport] = None
