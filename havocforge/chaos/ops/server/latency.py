from __future__ import annotations
import random
import time
from typing import Any
from havocforge.chaos.ops.base import BaseChaosOp, ApplyResult
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class LatencyOp(BaseChaosOp):
    """Latency chaos operation.

    Adds server-side delay in milliseconds.

    Args:
        enabled (bool): Toggle for this op.
        p (float): Probability [0,1] used by the selector.
        weight (float): Relative weight for weighted selection (if used).
        min_ms (int): Minimum delay in ms.
        max_ms (int): Maximum delay in ms.

    Returns:
        ApplyResult: Same body, descriptions like ["latency(<delay>ms)"], and added_latency_ms set to the actual delay."""

    key = "latency"

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        min_ms: int = 0,
        max_ms: int = 0,
        **kw,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        self.min_ms = int(min_ms or 0)
        self.max_ms = int(max_ms or self.min_ms)

    def budget_cost(self) -> tuple[int, int]:
        return (max(0, self.max_ms), 0)

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        if self.max_ms <= 0:
            return ApplyResult(body=body, descriptions=[])
        span = self.max_ms - self.min_ms
        delay = self.min_ms + (int(rng.random() * (span + 1)) if span > 0 else 0)
        try:
            time.sleep(delay / 1000.0)
        except Exception:
            pass
        return ApplyResult(
            body=body, descriptions=[f"latency({delay}ms)"], added_latency_ms=delay
        )
