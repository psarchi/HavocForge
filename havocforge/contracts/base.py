from __future__ import annotations
from typing import Any, ClassVar, Set, Callable
from pydantic import BaseModel, ConfigDict

AdaptFn = Callable[[str, Any], dict]


class ContractModel(BaseModel):
    """Base for all contract specs with an overridable to_spec()."""

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = ""
    type_aliases: ClassVar[Set[str]] = set()

    def to_spec(self, name: str, adapt: AdaptFn) -> dict:
        d = self.model_dump(exclude_none=True)
        d["type"] = type(self).type_token or "string"
        return d
