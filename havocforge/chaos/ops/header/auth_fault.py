from __future__ import annotations
import random
from typing import Any
from havocforge.chaos.ops.base import BaseChaosOp, ApplyResult
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class AuthFaultOp(BaseChaosOp):
    """Auth fault chaos operation.

    Returns 401/403 to simulate auth problems.

    Args:
        enabled (bool): Toggle.
        p (float): Probability [0,1].
        weight (float): Relative weight.
        modes (str): Behavior hint (e.g., "missing").
        codes (Sequence[int]): Candidate status codes, defaults to [401, 403].

    Returns:
        ApplyResult: Minimal error body, faults_count=1, status_override set to chosen code."""

    key = "auth_fault"

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        modes: str = "missing",
        codes=None,
        **kw,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        self.modes = modes
        self.codes = list(codes) if codes else [401, 403]

    def budget_cost(self) -> tuple[int, int]:
        return (0, 1)

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        code = self.codes[int(rng.random() * len(self.codes))]
        # Optionally strip auth header from request (no-op for response mutation)
        try:
            if self.modes and "missing" in str(self.modes).lower():
                # Starlette Request is immutable-ish; best-effort noop
                pass
        except Exception:
            pass
        return ApplyResult(
            body={"error": "auth fault injected", "status": code},
            descriptions=[f"auth_fault({code})"],
            faults_count=1,
            status=code,
        )
