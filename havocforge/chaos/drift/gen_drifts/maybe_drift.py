from __future__ import annotations

from random import Random
from typing import Any, Dict, Optional

from havocforge.contracts.maybe import MaybeGeneratorSpec
from havocforge.chaos.drift.registry import run_drift
from havocforge.chaos.drift.gen_drifts.base import DriftSpec
from havocforge.chaos.drift.gen_drifts.utils import clamp


class MaybeDataDrift(DriftSpec):
    spec_cls = MaybeGeneratorSpec
    handlers = {"data": "handle_data"}

    @staticmethod
    def handle_data(
        spec: MaybeGeneratorSpec,
        rng: Random,
        budget: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        tweaks: list[str] = []
        cfg = config or {}

        if spec.p_null is not None:
            null_delta = cfg.get("null_delta", 0.1)
            if isinstance(null_delta, (list, tuple)) and len(null_delta) == 2:
                delta = rng.uniform(float(null_delta[0]), float(null_delta[1]))
            else:
                delta = rng.uniform(-float(null_delta), float(null_delta))
            old = spec.p_null
            spec.p_null = clamp(old + delta, 0.0, 1.0)
            tweaks.append(f"p_null:{old}->{spec.p_null}")

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
