from __future__ import annotations

from datetime import datetime
from random import Random
from typing import Any, Dict, Optional, Tuple

from havocforge.chaos.drift.registry import DriftResult
from havocforge.contracts.maybe import MaybeGeneratorSpec
from havocforge.contracts.timestamp import TimestampGeneratorSpec
from havocforge.chaos.drift.gen_drifts.base import DriftSpec
from havocforge.chaos.drift.gen_drifts.utils import ensure_nullable_wrapper


def _normalize(value) -> Tuple[Optional[float], str]:
    if value is None:
        return None, "none"
    if isinstance(value, datetime):
        return value.timestamp(), "datetime"
    if isinstance(value, (int, float)):
        return float(value), "numeric"
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None, "none"
        return dt.timestamp(), "str"
    return None, "none"


def _denormalize(epoch: float, kind: str):
    if kind == "datetime":
        return datetime.fromtimestamp(epoch)
    if kind == "numeric":
        return epoch
    if kind == "str":
        return datetime.fromtimestamp(epoch).isoformat()
    return None


class TimestampDataDrift(DriftSpec):
    spec_cls = TimestampGeneratorSpec
    handlers = {"data": "handle_data"}

    @staticmethod
    def handle_data(
        spec: TimestampGeneratorSpec,
        rng: Random,
        budget: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[DriftResult | str]:
        start_val, start_kind = _normalize(spec.start)
        end_val, end_kind = _normalize(spec.end)
        tweaks: list[str] = []
        replacement: Optional[MaybeGeneratorSpec] = None

        if start_val is None and end_val is None:
            return None

        if start_val is not None and end_val is not None and end_val < start_val:
            start_val, end_val = end_val, start_val

        if start_val is not None and end_val is not None:
            span = max(1.0, end_val - start_val)
        elif start_val is not None:
            span = abs(start_val) or 60.0
        elif end_val is not None:
            span = abs(end_val) or 60.0
        else:
            span = 60.0

        cfg = config or {}
        offset_abs = cfg.get("offset_abs")
        if isinstance(offset_abs, (list, tuple)) and len(offset_abs) == 2:
            offset = rng.uniform(float(offset_abs[0]), float(offset_abs[1]))
        else:
            ratio = float(cfg.get("offset_ratio", 0.1))
            offset = rng.uniform(-ratio, ratio) * span

        if start_val is not None:
            start_val += offset
            tweaks.append(f"start_shift={offset}s")

        if end_val is not None:
            end_val += offset
            tweaks.append(f"end_shift={offset}s")
            if start_val is not None:
                end_val = max(end_val, start_val)

        if start_val is not None:
            spec.start = _denormalize(start_val, start_kind)
        if end_val is not None:
            spec.end = _denormalize(end_val, end_kind)

        replacement, nullable_summary = ensure_nullable_wrapper(
            spec, rng, cfg.get("nullable")
        )
        if nullable_summary:
            tweaks.append(nullable_summary)

        summary = ", ".join(tweaks) if tweaks else None
        if replacement is not None:
            return DriftResult(summary=summary, replacement=replacement)
        return summary
