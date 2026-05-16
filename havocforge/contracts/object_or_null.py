from __future__ import annotations
from typing import ClassVar, Set, Any, Optional, List
from pydantic import ConfigDict
from havocforge.contracts.base import ContractModel


class ObjectOrNullGeneratorSpec(ContractModel):
    """Typed nullable shortcut for object."""

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "object_or_null"
    type_aliases: ClassVar[Set[str]] = set()

    child: Optional[Any] = None
    weights: Optional[List[float]] = None
    bound_to: Optional[str] = None
    linked_to: Optional[str] = None
    bound_to_schema: Optional[str] = None
    bound_to_revision: Optional[int] = None

    def to_spec(self, name: str, adapt):
        out = {"type": "object_or_null"}
        if self.child is not None:
            out["child"] = adapt(f"{name}.?", self.child)
        if self.weights is not None:
            out["weights"] = self.weights  # type: ignore[assignment]
        if self.bound_to is not None:
            out["bound_to"] = self.bound_to
        if self.bound_to_schema is not None:
            out["bound_to_schema"] = self.bound_to_schema
        if self.bound_to_revision is not None:
            out["bound_to_revision"] = self.bound_to_revision  # type: ignore[assignment]
        return out
