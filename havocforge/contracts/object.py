from __future__ import annotations
from typing import ClassVar, Set, Dict, Any, Optional
from pydantic import ConfigDict
from havocforge.contracts.base import ContractModel


class ObjectGeneratorSpec(ContractModel):
    """Object with named fields."""

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "object"
    type_aliases: ClassVar[Set[str]] = {"record"}

    fields: Optional[Dict[str, Any]] = None

    def to_spec(self, name: str, adapt):
        fields = {}
        for k, v in (self.fields or {}).items():
            fields[k] = adapt(f"{name}.{k}", v)
        return {"type": "object", "fields": fields}
