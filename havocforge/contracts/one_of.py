from __future__ import annotations
from typing import ClassVar, Set, List, Any, Optional
from pydantic import ConfigDict
from havocforge.contracts.base import ContractModel


class OneOfGeneratorSpec(ContractModel):
    """Union of structural variants; choices are full specs with optional weights."""

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "one_of"
    type_aliases: ClassVar[Set[str]] = {"oneof"}

    choices: Optional[List[Any]] = None
    weights: Optional[List[float]] = None
    bound_to: Optional[str] = None
    linked_to: Optional[str] = None
    bound_to_schema: Optional[str] = None
    bound_to_revision: Optional[int] = None

    def to_spec(self, name: str, adapt):
        choices = [
            {"of": adapt(f"{name}|{i}", c)} for i, c in enumerate(self.choices or [])
        ]
        out = {"type": "one_of", "choices": choices}
        if self.weights:
            out["weights"] = list(self.weights)  # type: ignore[arg-type]
        if self.bound_to is not None:
            out["bound_to"] = self.bound_to
        if self.bound_to_schema is not None:
            out["bound_to_schema"] = self.bound_to_schema
        if self.bound_to_revision is not None:
            out["bound_to_revision"] = self.bound_to_revision  # type: ignore[assignment]
        return out
