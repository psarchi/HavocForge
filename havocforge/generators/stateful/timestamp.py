"""Stateful timestamp generator with late arrival support."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from havocforge.context import GenContext
from havocforge.errors import ContextError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import InvalidParameterError
from havocforge.generators.utils import parse_timestamp_to_microseconds
from havocforge.registry import Registry


if TYPE_CHECKING:  # avoid import cycles at runtime
    from havocforge.contracts.types import JsonValue  # noqa : F401


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class StatefulTimestampGenerator(BaseGenerator):
    """Generate incrementing Unix timestamps (microseconds).

    Produces sequential timestamps that increment on each generation. Integrates with
    TemporalTracker for timeline state management. Late arrival simulation is handled
    by the LateArrivalOp chaos operation which mutates generated timestamps.

    TODO(persistence): Add support for persisting timeline state to SQL or Redis.

    Args:
        start: Start timestamp as microseconds epoch, or ISO8601 string. Required.
        end: Optional end timestamp. If provided, generator will not produce timestamps beyond this value.
        increment: Microseconds to add per generation. Required.

    Raises:
        TypeError: If start or increment parameters are not provided.
        InvalidParameterError: If parameters are invalid or unparsable.
        ContextError: If ctx is not a GenContext in generate.

    Example YAML:
        event_timestamp:
          type: stateful_timestamp
          start: 1732378800000000
          increment: 1000000
          end: 1732465200000000
    """

    __meta__ = {
        "aliases": {
            "start": "start",
            "end": "end",
            "increment": "increment",
        },
        "deprecations": [],
        "rules": [],
    }
    __slots__ = ("start", "end", "increment")
    __aliases__ = (
        "stateful_timestamp",
        "timestamp_stateful",
        "ts_stateful",
    )

    def __init__(
        self,
        start: int | float | str | None = None,
        end: int | float | str | None = None,
        increment: int | None = None,
    ) -> None:
        """Initialize stateful timestamp generator.

        Args:
            start: Start timestamp (microseconds epoch or ISO8601).
            end: Optional end timestamp (microseconds epoch or ISO8601).
            increment: Microseconds to add per generation.

        Raises:
            InvalidParameterError: If start or increment is None.
        """
        if start is None:
            raise InvalidParameterError(
                "StatefulTimestampGenerator requires 'start' parameter"
            )
        if increment is None:
            raise InvalidParameterError(
                "StatefulTimestampGenerator requires 'increment' parameter"
            )
        self.start = start
        self.end = end
        self.increment = increment

    @classmethod
    def from_spec(
        cls,
        builder: Any,
        spec: Mapping[str, Any],
    ) -> "StatefulTimestampGenerator":
        """Construct from a generator specification mapping.

        Args:
            builder: Unused builder/factory (kept for signature parity).
            spec: Mapping containing start, end (optional), increment.

        Returns:
            StatefulTimestampGenerator: Configured instance.

        Raises:
            TypeError: If start or increment is not in spec.
        """
        return cls(
            start=spec.get("start"),
            end=spec.get("end"),
            increment=spec.get("increment"),
        )

    def _sanity_check(self, ctx: GenContext) -> None:
        """Validate context and that bounds are parseable.

        Args:
            ctx: Active generation context.

        Raises:
            ContextError: If ctx is not a GenContext.
            InvalidParameterError: If start/end cannot be parsed or end < start.
        """
        if not isinstance(ctx, GenContext):
            raise ContextError("ctx must be an instance of GenContext")

        start_ts = parse_timestamp_to_microseconds(self.start)
        end_ts = parse_timestamp_to_microseconds(self.end)

        if start_ts is None:
            raise InvalidParameterError("stateful_timestamp.start is required")

        if end_ts is not None and end_ts < start_ts:
            raise InvalidParameterError("stateful_timestamp.end must be >= start")

    def _generate_impl(self, ctx: GenContext) -> "JsonValue":
        """Produce an incrementing timestamp according to configuration.

        Normal mode: Increments forward from current timeline position.
        Late arrival mode: Generates random timestamp in past timeline range.

        Args:
            ctx: Generation context providing RNG, temporal tracker, and flags.

        Returns:
            Integer microseconds since Unix epoch.

        Raises:
            ContextError: If ctx is invalid.
            InvalidParameterError: If configuration is invalid.
        """
        self._sanity_check(ctx)

        start_ts = parse_timestamp_to_microseconds(self.start)
        end_ts = parse_timestamp_to_microseconds(self.end)

        if start_ts is None:
            raise InvalidParameterError("stateful_timestamp.start is required")

        if ctx.temporal_tracker is not None:
            tracker = ctx.temporal_tracker
        else:
            from havocforge.chaos import get_temporal_tracker

            tracker = get_temporal_tracker()
            ctx.temporal_tracker = tracker

        schema_name = ctx.schema_name
        if schema_name is None:
            raise InvalidParameterError(
                "stateful_timestamp requires ctx.schema_name to be set"
            )

        state = tracker.get_or_init(schema_name, start_ts)

        current = state.current_timestamp
        if current is None:
            timestamp: int = start_ts
        else:
            timestamp = current + self.increment

        if end_ts is not None and timestamp > end_ts:
            timestamp = end_ts

        tracker.update_timeline(schema_name, timestamp)

        return timestamp
