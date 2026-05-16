from __future__ import annotations
import random
from typing import Any, Sequence
from havocforge.chaos.ops.base import BaseChaosOp, ApplyResult
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class HttpErrorOp(BaseChaosOp):
    """HTTP error chaos operation.

    Forces an HTTP error status with an empty body.

    Args:
        enabled (bool): Toggle.
        p (float): Probability [0,1].
        weight (float): Relative selection weight.
        codes (Sequence[int]): Candidate HTTP status codes (defaults to common 4xx/5xx).

    Returns:
        ApplyResult: Empty body, faults_count=1, status_override=<code>.
    """

    key = "http_error"

    _DEFAULT_CODES = (400, 401, 403, 404, 408, 409, 429, 500, 502, 503)

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        codes: Sequence[int] | None = None,
        **kw,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        available = list(dict.fromkeys(codes or self._DEFAULT_CODES))
        self.codes = available or list(self._DEFAULT_CODES)

    def budget_cost(self) -> tuple[int, int]:
        return (0, 1)

    def apply(
        self,
        *,
        request,
        response,
        body: Any,
        rng: random.Random,
    ) -> ApplyResult:
        code = rng.choice(self.codes)
        # Response body intentionally empty for this fault.
        return ApplyResult(
            body={}, descriptions=[f"http_error({code})"], faults_count=1, status=code
        )
