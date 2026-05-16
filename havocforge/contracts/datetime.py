from __future__ import annotations
from typing import ClassVar, List, Set, Optional, Union
from pydantic import ConfigDict
from havocforge.contracts.base import ContractModel


class DateTimeGeneratorSpec(ContractModel):
    """Date/time generator (format optional)."""

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "datetime"
    type_aliases: ClassVar[Set[str]] = set()

    start: Optional[str] = None
    end: Optional[str] = None
    format: Optional[str] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    tz: Optional[str] = None
    depends_on: Optional[str] = None
    bound_to: Optional[str] = None
    linked_to: Optional[str] = None
    bound_to_schema: Optional[str] = None
    bound_to_revision: Optional[int] = None
    pool: Optional[Union[List[str], bool]] = None
    depends_on_pool: Optional[str] = None
