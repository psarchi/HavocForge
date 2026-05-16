from __future__ import annotations

from random import Random
from typing import Any, Dict, Optional

from havocforge.chaos.drift.registry import DriftResult
from havocforge.contracts.int import IntGeneratorSpec
from havocforge.contracts.maybe import MaybeGeneratorSpec
from havocforge.chaos.drift.gen_drifts.base import DriftSpec
from havocforge.chaos.drift.gen_drifts.utils import (
    ensure_nullable_wrapper,
    rng_choice,
)


class IntDataDrift(DriftSpec):
    spec_cls = IntGeneratorSpec  # type: ignore[assignment]
    handlers = {"data": "handle_data"}

    @staticmethod
    def handle_data(
        spec: IntGeneratorSpec,
        rng: Random,
        budget: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[DriftResult | str]:
        tweaks: list[str] = []
        replacement: Optional[MaybeGeneratorSpec] = None

        cfg = config or {}
        if spec.min is not None and spec.max is not None:
            lo = int(spec.min)
            hi = int(spec.max)
            if lo > hi:
                lo, hi = hi, lo

            offset_abs = cfg.get("offset_abs")
            if isinstance(offset_abs, (list, tuple)) and len(offset_abs) == 2:
                delta = rng.uniform(float(offset_abs[0]), float(offset_abs[1]))
            else:
                ratio = float(cfg.get("offset_ratio", 0.2))
                span = max(1, hi - lo)
                delta = rng.uniform(-span * ratio, span * ratio)

            delta_int = int(round(delta))
            if delta_int == 0:
                delta_int = rng_choice(rng, [-1, 1])

            new_lo = lo + delta_int
            new_hi = hi + delta_int
            if new_hi <= new_lo:
                new_hi = new_lo + 1

            spec.min = new_lo
            spec.max = new_hi
            tweaks.append(f"range_shift={delta_int}")

        if spec.step:
            original_step = int(spec.step)
            step_delta = int(cfg.get("step_delta", 1))
            if step_delta > 0:
                step_change = rng_choice(rng, list(range(-step_delta, step_delta + 1)))
                if step_change != 0:
                    new_step = max(1, original_step + step_change)
                    if new_step != original_step:
                        spec.step = new_step
                        tweaks.append(f"step_delta={step_change}")

        replacement, nullable_summary = ensure_nullable_wrapper(
            spec, rng, cfg.get("nullable")
        )
        if nullable_summary:
            tweaks.append(nullable_summary)

        summary = ", ".join(tweaks) if tweaks else None

        if replacement is not None:
            return DriftResult(summary=summary, replacement=replacement)

        return summary
