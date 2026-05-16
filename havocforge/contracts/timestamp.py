from __future__ import annotations
from typing import ClassVar, List, Set, Optional, Union
from datetime import datetime
from pydantic import ConfigDict
from havocforge.contracts.base import ContractModel


class TimestampGeneratorSpec(ContractModel):
    """Timestamp generator (start/end datetimes)."""

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "timestamp"
    type_aliases: ClassVar[Set[str]] = set()

    start: Optional[datetime] = None
    end: Optional[datetime] = None
    depends_on: Optional[str] = None
    bound_to: Optional[str] = None
    linked_to: Optional[str] = None
    bound_to_schema: Optional[str] = None
    bound_to_revision: Optional[int] = None
    pool: Optional[Union[List[str], bool]] = None
    depends_on_pool: Optional[str] = None

    def to_spec(self, name: str, adapt):
        def enc(x):
            if x is None:
                return None
            if isinstance(x, (int, float, str)):
                return x
            if isinstance(x, datetime):
                return x.isoformat()
            return str(x)

        out: dict = {"type": "timestamp"}
        if self.start is not None:
            out["start"] = enc(self.start)
        if self.end is not None:
            out["end"] = enc(self.end)
        if self.depends_on is not None:
            out["depends_on"] = self.depends_on
        if self.bound_to is not None:
            out["bound_to"] = self.bound_to
        if self.bound_to_schema is not None:
            out["bound_to_schema"] = self.bound_to_schema
        if self.bound_to_revision is not None:
            out["bound_to_revision"] = self.bound_to_revision
        return out
