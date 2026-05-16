from __future__ import annotations

import random
from typing import Any, Sequence

from havocforge.chaos.ops.base import ApplyResult, BaseChaosOp
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class HttpMismatchOp(BaseChaosOp):
    """HTTP mismatch chaos operation.

    Leaves a successful-looking body intact but forces a non-2xx status code.

    Args:
        enabled (bool): Toggle.
        p (float): Probability [0,1].
        weight (float): Relative weight.
        codes (Sequence[int]): Candidate status codes (defaults to non-2xx codes).

    Returns:
        ApplyResult: Original body, faults_count=1, status_override=<code>.
    """

    key = "http_mismatch"

    _DEFAULT_CODES = (400, 401, 403, 409, 412, 422, 429, 500, 502, 503)

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
        return ApplyResult(
            body=body,
            descriptions=[f"http_mismatch({code})"],
            faults_count=1,
            status=code,
        )
