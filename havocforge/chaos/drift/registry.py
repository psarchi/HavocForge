from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any, Callable, Dict, Optional, Type, Union

from havocforge.chaos.drift.errors import InvalidDriftResultError


@dataclass
class DriftResult:
    """Outcome returned by a drift handler."""

    summary: Optional[str] = None
    replacement: Optional[object] = None

    def merge(self, other: "DriftResult") -> "DriftResult":
        """Merge another result into this one (used for recursive handlers)."""
        if other.summary:
            if self.summary:
                self.summary = f"{self.summary}, {other.summary}"
            else:
                self.summary = other.summary
        if other.replacement is not None:
            self.replacement = other.replacement
        return self


DriftHandler = Callable[
    [object, Random, int, Optional[Dict[str, Any]]],
    Optional[Union[str, DriftResult]],
]


@dataclass(frozen=True)
class _RegistryKey:
    kind: str
    spec_cls: Type[object]


class DriftRegistry:
    """Central registry of drift handlers keyed by (kind, spec class)."""

    def __init__(self) -> None:
        self._handlers: Dict[_RegistryKey, DriftHandler] = {}

    def register(
        self, kind: str, spec_cls: Type[object], handler: DriftHandler
    ) -> None:
        key = _RegistryKey(kind=kind, spec_cls=spec_cls)
        self._handlers[key] = handler

    def get(self, kind: str, spec_obj: object) -> Optional[DriftHandler]:
        key = _RegistryKey(kind=kind, spec_cls=type(spec_obj))
        return self._handlers.get(key)


DRIFT_REGISTRY = DriftRegistry()


def run_drift(
    kind: str,
    spec_obj: object,
    rng: Random,
    budget: int = 1,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[DriftResult]:
    handler = DRIFT_REGISTRY.get(kind, spec_obj)
    if handler is None:
        return None
    outcome = handler(spec_obj, rng, budget, config)
    if outcome is None:
        return None
    if isinstance(outcome, DriftResult):
        return outcome
    if isinstance(outcome, str):
        return DriftResult(summary=outcome)
    raise InvalidDriftResultError(
        f"Drift handler for {type(spec_obj).__name__} returned unsupported "
        f"type: {type(outcome)!r}"
    )
