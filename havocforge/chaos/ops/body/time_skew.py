from __future__ import annotations

import random
from typing import Any, Iterable, List

from havocforge.chaos.ops.base import ApplyResult, BaseChaosOp
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class TimeSkewOp(BaseChaosOp):
    """Skew numeric timestamp fields by up to max_skew_s seconds."""

    key = "time_skew"

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        max_skew_s: int = 0,
        direction: str = "both",
        fields: Iterable[str] | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        self.max_skew_s = int(max_skew_s or 0)
        self.direction = str(direction or "both").lower()
        self.fields: List[str] = list(fields or [])

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        if not isinstance(body, dict) or self.max_skew_s <= 0 or not self.fields:
            return ApplyResult(body=body, descriptions=[])
        items = body.get("items")
        if not isinstance(items, list):
            return ApplyResult(body=body, descriptions=[])

        applied = False
        for rec in items:
            if not isinstance(rec, dict):
                continue
            for field in self.fields:
                if field not in rec:
                    continue
                val = rec[field]
                if not isinstance(val, (int, float)):
                    continue
                skew = rng.randint(0, self.max_skew_s)
                if self.direction in {"both", "past"} and rng.random() < 0.5:
                    skew = -skew
                rec[field] = val + skew
                applied = True

        return ApplyResult(body=body, descriptions=(["time_skew"] if applied else []))
