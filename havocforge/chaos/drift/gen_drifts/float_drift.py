from __future__ import annotations

from random import Random
from typing import Any, Dict, Optional

from havocforge.chaos.drift.registry import DriftResult
from havocforge.contracts.float import FloatGeneratorSpec
from havocforge.contracts.maybe import MaybeGeneratorSpec
from havocforge.chaos.drift.gen_drifts.base import DriftSpec
from havocforge.chaos.drift.gen_drifts.utils import (
    ensure_nullable_wrapper,
    rng_choice,
)


class FloatDataDrift(DriftSpec):
    spec_cls = FloatGeneratorSpec  # type: ignore[assignment]
    handlers = {"data": "handle_data"}

    @staticmethod
    def handle_data(
        spec: FloatGeneratorSpec,
        rng: Random,
        budget: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[DriftResult | str]:
        if spec.min is None or spec.max is None:
            return None

        lo = float(spec.min)
        hi = float(spec.max)
        if lo > hi:
            lo, hi = hi, lo

        cfg = config or {}
        tweaks: list[str] = []
        replacement: Optional[MaybeGeneratorSpec] = None

        offset_abs = cfg.get("offset_abs")
        if isinstance(offset_abs, (list, tuple)) and len(offset_abs) == 2:
            delta = rng.uniform(float(offset_abs[0]), float(offset_abs[1]))
        else:
            ratio = float(cfg.get("offset_ratio", 0.2))
            span = max(1.0, hi - lo)
            delta = rng.uniform(-span * ratio, span * ratio)
        new_lo = lo + delta
        new_hi = hi + delta
        spec.min = new_lo
        spec.max = max(new_lo + 1e-6, new_hi)
        tweaks.append(f"range_shift={delta}")

        if spec.precision is not None:
            step = int(cfg.get("precision_step", 1))
            if step > 0:
                choices = list(range(-step, step + 1))
                change = rng_choice(rng, choices)
                if change != 0:
                    new_precision = max(0, int(spec.precision) + change)
                    if new_precision != spec.precision:
                        spec.precision = new_precision
                        tweaks.append(f"precision_delta={change}")

        replacement, nullable_summary = ensure_nullable_wrapper(
            spec, rng, cfg.get("nullable")
        )
        if nullable_summary:
            tweaks.append(nullable_summary)

        summary = ", ".join(tweaks) if tweaks else None

        if replacement is not None:
            return DriftResult(summary=summary, replacement=replacement)
        return summary
