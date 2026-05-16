from __future__ import annotations
from typing import ClassVar, Set, Any, Optional
from pydantic import ConfigDict
from havocforge.contracts.base import ContractModel


class ArrayGeneratorSpec(ContractModel):
    """Array of a single child spec (with min/max cardinality)."""

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "array"
    type_aliases: ClassVar[Set[str]] = {"list"}

    child: Optional[Any] = None
    min_items: Optional[int] = None
    max_items: Optional[int] = None

    def to_spec(self, name: str, adapt):
        out = {"type": "array"}
        if self.child is not None:
            out["child"] = adapt(f"{name}[]", self.child)
        if self.min_items is not None:
            out["min_items"] = int(self.min_items)  # type: ignore[assignment]
        if self.max_items is not None:
            out["max_items"] = int(self.max_items)  # type: ignore[assignment]
        return out
