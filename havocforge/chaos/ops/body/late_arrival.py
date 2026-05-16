"""Late arrival chaos operation for out-of-order timestamp simulation."""

from __future__ import annotations

import datetime
import random
from typing import Any

from havocforge.chaos.ops.base import ApplyResult, BaseChaosOp
from havocforge.chaos.utils import parse_timestamp
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class LateArrivalOp(BaseChaosOp):
    """Simulate out-of-order event timestamps for stream processing testing.

    This operation mutates timestamp fields in the response body by replacing
    incrementing timestamps with random values from earlier in the timeline.
    Simulates late-arriving events in stream processing scenarios (Kafka, Flink, etc.).

    Auto-discovers stateful timestamp/datetime fields from schema configuration.
    Only eligible after minimum elapsed time threshold is met.

    Args:
        enabled: Whether this op is enabled.
        p: Probability of activation (0.0-1.0).
        weight: Selection weight when choosing ops.
        min_elapsed_seconds: Minimum elapsed seconds before late arrival is eligible.
        late_window_seconds: Maximum seconds back from current to generate late timestamp.
        schema_name: Schema name for temporal tracking (optional, inferred from context).
        **kw: Additional parameters.

    Example config:
        chaos:
          ops:
            late_arrival:
              enabled: true
              p: 0.15
              weight: 1.0
              min_elapsed_seconds: 3600
              late_window_seconds: 3600
    """

    key = "late_arrival"

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        min_elapsed_seconds: int = 3600,
        late_window_seconds: int = 3600,
        schema_name: str | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        self.min_elapsed_seconds = int(min_elapsed_seconds)
        self.late_window_seconds = int(late_window_seconds)
        self.schema_name = schema_name

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        """Apply late arrival mutation to timestamp fields in body.

        Args:
            request: HTTP request object (unused).
            response: HTTP response object (unused).
            body: Response body dict containing items to mutate.
            rng: Random number generator.

        Returns:
            ApplyResult with mutated body and descriptions.
        """
        if not isinstance(body, dict):
            return ApplyResult(body=body, descriptions=[])

        items = body.get("items")
        if not isinstance(items, list) or not items:
            return ApplyResult(body=body, descriptions=[])

        from havocforge.chaos import get_temporal_tracker

        tracker = get_temporal_tracker()
        schema_name = (
            self.schema_name
            or body.get("schema_name")
            or getattr(response, "schema_name", None)
        )
        if not schema_name:
            return ApplyResult(body=body, descriptions=[])

        first, current = tracker.get_range(schema_name)
        if first is None or current is None:
            return ApplyResult(body=body, descriptions=[])

        elapsed_us = current - first
        min_elapsed_us = self.min_elapsed_seconds * 1_000_000

        if elapsed_us < min_elapsed_us:
            return ApplyResult(body=body, descriptions=[])

        late_window_us = min(self.late_window_seconds * 1_000_000, elapsed_us)
        late_start = current - late_window_us

        stateful_fields = self._discover_stateful_fields(items)
        if not stateful_fields:
            return ApplyResult(body=body, descriptions=[])

        applied = False
        for rec in items:
            if not isinstance(rec, dict):
                continue

            late_ts = rng.randint(late_start, current)
            late_dt = datetime.datetime.fromtimestamp(
                late_ts / 1_000_000, tz=datetime.timezone.utc
            )

            for field in stateful_fields:
                if field not in rec:
                    continue

                val = rec[field]
                parsed_dt, kind = parse_timestamp(val)
                if parsed_dt:
                    if kind == "epoch_micro":
                        rec[field] = late_ts
                    elif kind == "epoch":
                        rec[field] = int(late_ts / 1_000_000)
                    else:
                        rec[field] = (
                            late_dt.isoformat().replace("+00:00", "Z")
                            if isinstance(val, str) and "Z" in val
                            else late_dt.strftime("%Y-%m-%d %H:%M:%S")
                        )
                    applied = True

        return ApplyResult(body=body, descriptions=["late_arrival"] if applied else [])

    def _discover_stateful_fields(self, items: list) -> list[str]:
        """Auto-discover fields that contain timestamp-like values.

        Args:
            items: List of record dicts.

        Returns:
            List of field names that appear to be timestamps or datetime strings.
        """
        if not items:
            return []

        first_item = items[0]
        if not isinstance(first_item, dict):
            return []

        stateful_fields = []
        for key, val in first_item.items():
            parsed_dt, _ = parse_timestamp(val)
            if parsed_dt:
                stateful_fields.append(key)

        return stateful_fields
