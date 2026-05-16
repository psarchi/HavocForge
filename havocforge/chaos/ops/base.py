from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from havocforge.chaos.errors import ChaosOpValidationError


@dataclass
class ApplyResult:
    """Result of a chaos op application."""

    body: Any
    descriptions: List[str] = field(default_factory=list)
    status: Optional[int] = None
    headers: Dict[str, str] = field(
        default_factory=lambda: {"Content-Type": "application/json; charset=utf-8"}
    )
    headers_delta: Optional[Dict[str, Optional[str]]] = None
    added_latency_ms: int = 0
    faults_count: int = 0


class BaseChaosOp:
    """Base class and contract for all chaos operations."""

    # REQUIRED: every subclass must override with a non-empty value.
    key: str = ""
    phase: str = "post"
    layer_kind: Optional[str] = ""

    def __init__(
        self, *, enabled: bool = True, p: float = 1.0, weight: float = 1.0, **kw
    ) -> None:
        # Keep minimal compat so existing ops that call super().__init__ won't break.
        self.enabled = bool(enabled)
        self.p = float(p)
        self.weight = float(weight)
        for k, v in kw.items():
            setattr(self, k, v)

    @classmethod
    def validate_class(cls) -> None:
        """Ensure subclass contract is satisfied (non-empty key)."""
        k = (
            getattr(cls, "key", "")
            or getattr(cls, "KEY", "")
            or getattr(cls, "NAME", "")
        )
        if not isinstance(k, str) or not k.strip() or k.strip().lower() == "base":
            raise ChaosOpValidationError(
                f"Chaos op {cls.__name__} must define non-empty 'key'."
            )

    def apply(self, *, request, response, body: Any, rng):
        """Apply operation to the response/body. Subclasses must implement."""
        raise NotImplementedError("Subclasses must implement apply()")
