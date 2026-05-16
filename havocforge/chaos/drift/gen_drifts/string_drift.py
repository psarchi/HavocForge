from __future__ import annotations

from random import Random
from typing import Any, Dict, Optional

from havocforge.chaos.drift.registry import DriftResult
from havocforge.contracts.string import StringGeneratorSpec
from havocforge.chaos.drift.gen_drifts.base import DriftSpec
from havocforge.chaos.drift.gen_drifts.utils import ensure_nullable_wrapper


class StringDataDrift(DriftSpec):
    spec_cls = StringGeneratorSpec
    handlers = {"data": "handle_data"}

    @staticmethod
    def handle_data(
        spec: StringGeneratorSpec,
        rng: Random,
        budget: int,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[DriftResult | str]:
        cfg = config or {}
        replacement, nullable_summary = ensure_nullable_wrapper(
            spec, rng, cfg.get("nullable")
        )
        if replacement is None:
            return None
        summary = nullable_summary or "nullable_wrapped"
        return DriftResult(summary=summary, replacement=replacement)
