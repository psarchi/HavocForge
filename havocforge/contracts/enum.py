from __future__ import annotations
from typing import ClassVar, Set, List, Any, Optional, Union
from pydantic import ConfigDict
from havocforge.contracts.base import ContractModel


class EnumGeneratorSpec(ContractModel):
    """Literal set (values) with optional weights."""

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "enum"
    type_aliases: ClassVar[Set[str]] = set()

    values: Optional[List[Any]] = None
    weights: Optional[List[float]] = None
    bound_to: Optional[str] = None
    linked_to: Optional[str] = None
    bound_to_schema: Optional[str] = None
    bound_to_revision: Optional[int] = None
    pool: Optional[Union[List[str], bool]] = None
    depends_on_pool: Optional[str] = None

    def to_spec(self, name: str, adapt):
        payload = {"type": "enum", "values": list(self.values or [])}
        if self.weights is not None:
            payload["weights"] = list(self.weights)
        if self.bound_to is not None:
            payload["bound_to"] = self.bound_to
        if self.bound_to_schema is not None:
            payload["bound_to_schema"] = self.bound_to_schema
        if self.bound_to_revision is not None:
            payload["bound_to_revision"] = self.bound_to_revision  # type: ignore[assignment]
        return payload
