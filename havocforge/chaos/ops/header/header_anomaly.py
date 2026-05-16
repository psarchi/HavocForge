from __future__ import annotations
import random
from typing import Any
from havocforge.chaos.ops.base import BaseChaosOp, ApplyResult
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class HeaderAnomalyOp(BaseChaosOp):
    """Header anomaly chaos operation.

    Injects anomalous headers (huge values and/or duplicates).

    Args:
        enabled (bool): Toggle.
        p (float): Probability [0,1].
        weight (float): Relative weight.
        patterns (str): Pattern name (e.g., "huge-value").
        huge_value_bytes (int): Size of the large header value to inject.
        dup_keys_count (int): How many duplicate header keys to add.

    Returns:
        ApplyResult: Same body; descriptions with "header_huge_value(N)" and/or "header_dup(K)"."""

    key = "header_anomaly"

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        patterns: str = "huge-value",
        huge_value_bytes: int = 2048,
        dup_keys_count: int = 3,
        **kw,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        self.patterns = patterns
        self.huge_value_bytes = int(huge_value_bytes or 0)
        self.dup_keys_count = int(dup_keys_count or 0)

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        descs = []
        try:
            if "huge" in str(self.patterns):
                size = max(1, self.huge_value_bytes)
                val = "".join(chr(int(rng.random() * 26) + 65) for _ in range(size))
                response.headers["X-Anom"] = val
                descs.append(f"header_huge_value({size})")
            if self.dup_keys_count > 1:
                for i in range(self.dup_keys_count):
                    response.headers.add_vary("X-Dup-Key") if hasattr(
                        response.headers, "add_vary"
                    ) else response.headers.__setitem__(f"X-Dup-Key-{i}", "1")
                descs.append(f"header_dup({self.dup_keys_count})")
        except Exception:
            pass
        return ApplyResult(body=body, descriptions=descs)
