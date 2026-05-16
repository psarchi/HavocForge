from __future__ import annotations

from random import Random
from typing import Any, Dict, Optional

from havocforge.contracts.select import SelectGeneratorSpec
from havocforge.chaos.drift.registry import run_drift
from havocforge.chaos.drift.gen_drifts.base import DriftSpec
from havocforge.chaos.drift.gen_drifts.utils import rng_choice, rng_shuffle


class SelectDataDrift(DriftSpec):
    spec_cls = SelectGeneratorSpec
    handlers = {"data": "handle_data"}

    @staticmethod
    def handle_data(
        spec: SelectGeneratorSpec,
        rng: Random,
        budget: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        options = spec.options or {}
        if not options:
            return None

        cfg = config or {}
        items = list(options.items())
        tweaks: list[str] = []

        if cfg.get("shuffle", True):
            rng_shuffle(rng, items)
            tweaks.append("options:shuffled")
        spec.options = dict(items)

        if spec.pick is not None:
            max_pick = max(1, len(items))
            pick_delta = int(cfg.get("pick_delta", 1))
            if pick_delta > 0:
                delta = rng.randint(-pick_delta, pick_delta)
                if delta != 0:
                    new_pick = max(1, min(max_pick, spec.pick + delta))  # type: ignore[operator]
                    if new_pick != spec.pick:
                        tweaks.append(f"pick:{spec.pick}->{new_pick}")
                        spec.pick = new_pick  # type: ignore[assignment]

        if budget > 1:
            child_cfg = cfg.get("child")
            key, value = rng_choice(rng, items)
            result = run_drift("data", value, rng, max(1, budget - 1), config=child_cfg)
            if result:
                if result.summary:
                    tweaks.append(f"{key}[{result.summary}]")
                if result.replacement is not None:
                    spec.options[key] = result.replacement

        return ", ".join(tweaks) if tweaks else None
