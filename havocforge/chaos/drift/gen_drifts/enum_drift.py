from __future__ import annotations

from random import Random
from typing import Any, Dict, Optional

from havocforge.contracts.enum import EnumGeneratorSpec
from havocforge.chaos.drift.gen_drifts.base import DriftSpec
from havocforge.chaos.drift.gen_drifts.utils import clamp, rng_choice, rng_shuffle


class EnumDataDrift(DriftSpec):
    spec_cls = EnumGeneratorSpec
    handlers = {"data": "handle_data"}

    @staticmethod
    def handle_data(
        spec: EnumGeneratorSpec,
        rng: Random,
        budget: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if not spec.values:
            return None
        values = list(spec.values)
        if len(values) <= 1:
            return None

        cfg = config or {}
        tweaks: list[str] = []

        if cfg.get("shuffle", True):
            if spec.weights and len(spec.weights) == len(values):
                zipped = list(zip(values, spec.weights))
                rng_shuffle(rng, zipped)
                _v, _w = zip(*zipped)
                values = list(_v)
                weights_unpack: list[float] = list(_w)
                spec.values = values
                spec.weights = weights_unpack
            else:
                rng_shuffle(rng, values)
                spec.values = values
            tweaks.append("reordered")

        if spec.weights and len(spec.weights) == len(values):
            weights = list(spec.weights)

            force_weight = cfg.get("force_weight", False)
            if force_weight:
                try:
                    i = next(idx for idx, w in enumerate(weights) if w > 0)
                except StopIteration:
                    i = 0
                for idx in range(len(weights)):
                    weights[idx] = 1.0 if idx == i else 0.0
                spec.weights = weights
                tweaks.append(f"weights[{i}]=1.0(forced)")
            else:
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
                weights = [round(w / total, 2) for w in weights]
                spec.weights = weights
                tweaks.append(f"weights[{i}]delta={delta}")

        return ", ".join(tweaks) if tweaks else None
