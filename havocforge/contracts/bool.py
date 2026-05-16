from __future__ import annotations
from typing import ClassVar, List, Optional, Set, Union
from pydantic import ConfigDict
from havocforge.contracts.base import ContractModel


class BoolGeneratorSpec(ContractModel):
    """Boolean generator."""

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "bool"
    type_aliases: ClassVar[Set[str]] = {"boolean"}
    p_true: Optional[float] = None
    bound_to: Optional[str] = None
    linked_to: Optional[str] = None
    bound_to_schema: Optional[str] = None
    bound_to_revision: Optional[int] = None
    pool: Optional[Union[List[str], bool]] = None
    depends_on_pool: Optional[str] = None
