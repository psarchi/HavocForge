from __future__ import annotations

from random import Random
from typing import Any, Dict, Optional

from havocforge.contracts.string_or_null import StringOrNullGeneratorSpec
from havocforge.chaos.drift.registry import run_drift
from havocforge.chaos.drift.gen_drifts.base import DriftSpec
from havocforge.chaos.drift.gen_drifts.utils import adjust_binary_weights


class StringOrNullDataDrift(DriftSpec):
    spec_cls = StringOrNullGeneratorSpec
    handlers = {"data": "handle_data"}

    @staticmethod
    def _adjust_weights(
        weights: list[float], rng: Random, cfg: Dict[str, Any]
    ) -> Optional[str]:
        if len(weights) != 2:
            return None
        delta_cfg = cfg.get("null_delta", 0.1)
        if isinstance(delta_cfg, (list, tuple)) and len(delta_cfg) == 2:
            delta = rng.uniform(float(delta_cfg[0]), float(delta_cfg[1]))
        else:
            delta = rng.uniform(-float(delta_cfg), float(delta_cfg))
        old_first = weights[0]
        new_first, new_second = adjust_binary_weights(weights, delta)
        weights[0] = new_first
        weights[1] = new_second
        return f"weights:{old_first:.2f}->{new_first:.2f}"

    @classmethod
    def handle_data(
        cls,
        spec: StringOrNullGeneratorSpec,
        rng: Random,
        budget: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        tweaks: list[str] = []
        cfg = config or {}

        if spec.weights:
            weights = list(spec.weights)
            summary = cls._adjust_weights(weights, rng, cfg)
            if summary:
                spec.weights = weights
                tweaks.append(summary)

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
