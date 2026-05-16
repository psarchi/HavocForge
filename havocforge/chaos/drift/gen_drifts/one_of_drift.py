from __future__ import annotations

from random import Random
from typing import Any, Dict, Optional

from havocforge.contracts.one_of import OneOfGeneratorSpec
from havocforge.chaos.drift.registry import run_drift
from havocforge.chaos.drift.gen_drifts.base import DriftSpec
from havocforge.chaos.drift.gen_drifts.utils import clamp, rng_choice


class OneOfDataDrift(DriftSpec):
    spec_cls = OneOfGeneratorSpec
    handlers = {"data": "handle_data"}

    @staticmethod
    def _adjust_weights(
        weights: list[float], rng: Random, cfg: Dict[str, Any]
    ) -> Optional[str]:
        if len(weights) < 2:
            return None

        force_weight = cfg.get("force_weight", False)
        if force_weight:
            i = rng.randint(0, len(weights) - 1)
            for idx in range(len(weights)):
                weights[idx] = 1.0 if idx == i else 0.0
            return f"weights[{i}]=1.0(forced)"

        delta_cfg = cfg.get("weight_delta", 0.1)
        if isinstance(delta_cfg, (list, tuple)) and len(delta_cfg) == 2:
            delta = rng.uniform(float(delta_cfg[0]), float(delta_cfg[1]))
        else:
            delta = float(delta_cfg)
            delta = rng.uniform(-delta, delta)
        i = rng.randint(0, len(weights) - 1)
        j_candidates = [idx for idx in range(len(weights)) if idx != i]
        if not j_candidates:
            j_candidates = [i]
        j = rng_choice(rng, j_candidates)
        weights[i] = clamp(weights[i] + delta, 0.0, 1.0)
        weights[j] = clamp(weights[j] - delta, 0.0, 1.0)
        total = sum(weights) or 1.0
        for idx in range(len(weights)):
            weights[idx] = round(weights[idx] / total, 2)
        return f"weights[{i}]delta={delta}"

    @classmethod
    def handle_data(
        cls,
        spec: OneOfGeneratorSpec,
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

        if spec.choices and budget > 1:
            idx = rng_choice(rng, range(len(spec.choices)))
            choice = spec.choices[idx]
            child_cfg = cfg.get("child")
            result = run_drift(
                "data", choice, rng, max(1, budget - 1), config=child_cfg
            )
            if result:
                if result.summary:
                    tweaks.append(f"choice[{idx}][{result.summary}]")
                if result.replacement is not None:
                    spec.choices[idx] = result.replacement

        return ", ".join(tweaks) if tweaks else None
