from __future__ import annotations

from random import Random
from typing import Any, Dict, Optional

from havocforge.contracts.array import ArrayGeneratorSpec
from havocforge.chaos.drift.registry import run_drift
from havocforge.chaos.drift.gen_drifts.base import DriftSpec


class ArrayDataDrift(DriftSpec):
    spec_cls = ArrayGeneratorSpec
    handlers = {"data": "handle_data"}

    @staticmethod
    def handle_data(
        spec: ArrayGeneratorSpec,
        rng: Random,
        budget: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        tweaks: list[str] = []
        cfg = config or {}

        if spec.min_items is not None or spec.max_items is not None:
            lo = int(spec.min_items or 0)
            hi = int(spec.max_items or (lo + 5))
            if hi < lo:
                hi = lo
            delta_cfg = cfg.get("length_delta")
            if isinstance(delta_cfg, (list, tuple)) and len(delta_cfg) == 2:
                delta = rng.randint(int(delta_cfg[0]), int(delta_cfg[1]))
            else:
                ratio = float(cfg.get("length_ratio", 0.25))
                span = max(1, hi - lo if hi > lo else 1)
                window = max(1, int(span * ratio))
                delta = rng.randint(-window, window)
            new_lo = max(0, lo + delta)
            new_hi = max(new_lo, hi + delta)
            spec.min_items = new_lo
            spec.max_items = new_hi
            tweaks.append(f"len:{lo}-{hi}->{new_lo}-{new_hi}")

        if spec.child is not None and budget > 1:
            child_cfg = cfg.get("child")
            result = run_drift(
                "data", spec.child, rng, max(1, budget - 1), config=child_cfg
            )
            if result:
                if result.summary:
                    tweaks.append(f"child[{result.summary}]")
                if result.replacement is not None:
                    spec.child = result.replacement

        return ", ".join(tweaks) if tweaks else None
