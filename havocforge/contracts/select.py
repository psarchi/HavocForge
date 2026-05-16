from __future__ import annotations
from typing import ClassVar, Set, Dict, Any, Optional
from pydantic import ConfigDict
from havocforge.contracts.base import ContractModel


class SelectGeneratorSpec(ContractModel):
    """Pick-k-of-N named branches."""

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "select"
    type_aliases: ClassVar[Set[str]] = set()

    options: Optional[Dict[str, Any]] = None
    pick: Optional[Dict[str, Any]] = None

    def to_spec(self, name: str, adapt):
        options: Dict[str, Any] = {}
        for k, v in (self.options or {}).items():
            # Options may include required/default metadata alongside the child spec
            if isinstance(v, dict):
                opt_spec: Dict[str, Any] = {}
                child_val = v.get("of", v.get("child", v))
                if child_val is not None:
                    opt_spec["of"] = adapt(f"{name}.{k}", child_val)
                if "required" in v:
                    opt_spec["required"] = v.get("required")
                if "default" in v:
                    opt_spec["default"] = v.get("default")
                options[k] = opt_spec
            else:
                options[k] = {"of": adapt(f"{name}.{k}", v)}
        out = {"type": "select", "options": options}
        if self.pick is not None:
            out["pick"] = self.pick
        return out
