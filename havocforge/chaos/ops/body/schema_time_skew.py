from __future__ import annotations
import random
import datetime
from typing import Any, List
from havocforge.chaos.ops.base import BaseChaosOp, ApplyResult
from havocforge.chaos.utils import parse_timestamp
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class SchemaTimeSkewOp(BaseChaosOp):
    """Time skew chaos operation.

    Skews timestamp fields by up to max_skew_s seconds.

    Args:
        enabled (bool): Toggle.
        p (float): Probability [0,1].
        weight (float): Relative weight.
        max_skew_s (int): Maximum absolute skew in seconds.
        direction (str): "past", "future", or "both".
        fields (list[str]): Field names that contain timestamps (ISO8601 or epoch).

    Returns:
        ApplyResult: Same body with skewed fields; descriptions=["time_skew"] when any field changed."""

    key = "schema_time_skew"

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        max_skew_s: int = 0,
        direction: str = "both",
        fields: List[str] | None = None,
        **kw,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        self.max_skew_s = int(max_skew_s or 0)
        self.direction = str(direction or "both").lower()
        self.fields = list(fields) if fields else []

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        if not isinstance(body, dict) or not self.fields or self.max_skew_s <= 0:
            return ApplyResult(body=body, descriptions=[])
        items = body.get("items")
        if not isinstance(items, list):
            return ApplyResult(body=body, descriptions=[])
        applied = False
        for rec in items:
            if not isinstance(rec, dict):
                continue
            for f in self.fields:
                if f in rec:
                    ts, kind = parse_timestamp(rec[f])
                    if ts:
                        skew = int(rng.random() * self.max_skew_s)
                        if self.direction in ("both", "past") and rng.random() < 0.5:
                            skew = -skew
                        new_dt = ts + datetime.timedelta(seconds=skew)
                        if kind == "epoch_micro":
                            rec[f] = int(new_dt.timestamp() * 1_000_000)
                        elif kind == "epoch":
                            rec[f] = int(new_dt.timestamp())
                        else:
                            rec[f] = new_dt.isoformat().replace("+00:00", "Z")
                        applied = True
        return ApplyResult(body=body, descriptions=(["time_skew"] if applied else []))
