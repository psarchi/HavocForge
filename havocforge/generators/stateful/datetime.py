"""Stateful datetime generator with late arrival support."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from havocforge.context import GenContext
from havocforge.errors import ContextError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import InvalidParameterError
from havocforge.generators.utils import parse_timestamp_to_microseconds
from havocforge.registry import Registry

if TYPE_CHECKING:
    pass

UTC = timezone.utc
ISO_DEFAULT = "%Y-%m-%dT%H:%M:%S%z"


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class StatefulDateTimeGenerator(BaseGenerator):
    """Generate incrementing formatted datetime strings.

    Produces sequential datetime strings that increment on each generation. Integrates
    with TemporalTracker for timeline state management. Late arrival simulation is handled
    by the LateArrivalOp chaos operation which mutates generated timestamps.

    TODO(persistence): Add support for persisting timeline state to SQL or Redis.

    Args:
        start: Start timestamp as microseconds epoch, or ISO8601 string. Required.
        end: Optional end timestamp. If provided, generator will not produce datetimes beyond this value.
        increment: Microseconds to add per generation. Required.
        format: strftime format string for output. Defaults to ISO8601.
        tz: Fixed timezone offset like "+04:00". Defaults to UTC.

    Raises:
        TypeError: If start or increment parameters are not provided.
        InvalidParameterError: If parameters are invalid or unparsable.
        ContextError: If ctx is not a GenContext in generate.

    Example YAML:
        event_date:
          type: stateful_datetime
          start: 1732378800000000
          increment: 1000000
          format: "%Y-%m-%d %H:%M:%S"
          tz: "+00:00"
    """

    __meta__ = {
        "aliases": {
            "start": "start",
            "end": "end",
            "increment": "increment",
            "format": "format",
            "tz": "tz",
        },
        "deprecations": [],
        "rules": [],
    }
    __slots__ = ("start", "end", "increment", "format", "tz")
    __aliases__ = (
        "stateful_datetime",
        "datetime_stateful",
        "dt_stateful",
    )

    def __init__(
        self,
        start: int | float | str | None = None,
        end: int | float | str | None = None,
        increment: int | None = None,
        format: str | None = None,
        tz: str | None = None,
    ) -> None:
        """Initialize stateful datetime generator.

        Args:
            start: Start timestamp (microseconds epoch or ISO8601).
            end: Optional end timestamp (microseconds epoch or ISO8601).
            increment: Microseconds to add per generation.
            format: strftime format string (default ISO8601).
            tz: Fixed timezone offset like "+04:00" (default UTC).

        Raises:
            InvalidParameterError: If start or increment is None.
        """
        if start is None:
            raise InvalidParameterError(
                "StatefulDateTimeGenerator requires 'start' parameter"
            )
        if increment is None:
            raise InvalidParameterError(
                "StatefulDateTimeGenerator requires 'increment' parameter"
            )
        self.start = start
        self.end = end
        self.increment = increment
        self.format = format or ISO_DEFAULT
        self.tz = tz

    @classmethod
    def from_spec(
        cls,
        builder: Any,
        spec: Mapping[str, Any],
    ) -> "StatefulDateTimeGenerator":
        """Construct from a generator specification mapping.

        Args:
            builder: Unused builder/factory (kept for signature parity).
            spec: Mapping containing start, end, increment, format, tz.

        Returns:
            StatefulDateTimeGenerator: Configured instance.

        Raises:
            TypeError: If start or increment is not in spec.
        """
        return cls(
            start=spec.get("start"),
            end=spec.get("end"),
            increment=spec.get("increment"),
            format=spec.get("format"),
            tz=spec.get("tz"),
        )

    def _apply_tz(self, dt: datetime) -> datetime:
        """Apply a fixed offset tz if configured.

        Args:
            dt: Datetime to convert.

        Returns:
            Datetime in the configured fixed offset or unchanged if not set.

        Raises:
            InvalidParameterError: If tz is not in "+HH:MM"/"-HH:MM" form.
        """
        if not self.tz:
            return dt

        r_tz = r"([+-])(\d{2}):(\d{2})"
        match = re.fullmatch(r_tz, self.tz)
        if not match:
            raise InvalidParameterError("tz must be like '+04:00' or '-03:30'")
        sign = 1 if match.group(1) == "+" else -1
        hours, minutes = int(match.group(2)), int(match.group(3))
        offset = timezone(sign * timedelta(hours=hours, minutes=minutes))
        return dt.astimezone(offset)

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
            raise InvalidParameterError("stateful_datetime.start is required")

        if end_ts is not None and end_ts < start_ts:
            raise InvalidParameterError("stateful_datetime.end must be >= start")

    def _generate_impl(self, ctx: GenContext) -> str:
        """Produce an incrementing formatted datetime string.

        Normal mode: Increments forward from current timeline position.
        Late arrival mode: Generates random datetime in past timeline range.

        Args:
            ctx: Generation context providing RNG, temporal tracker, and flags.

        Returns:
            Formatted datetime string.

        Raises:
            ContextError: If ctx is invalid.
            InvalidParameterError: If configuration is invalid.
        """
        self._sanity_check(ctx)

        start_ts = parse_timestamp_to_microseconds(self.start)
        end_ts = parse_timestamp_to_microseconds(self.end)

        if start_ts is None:
            raise InvalidParameterError("stateful_datetime.start is required")

        if ctx.temporal_tracker is not None:
            tracker = ctx.temporal_tracker
        else:
            from havocforge.chaos import get_temporal_tracker

            tracker = get_temporal_tracker()
            ctx.temporal_tracker = tracker

        schema_name = ctx.schema_name
        if schema_name is None:
            raise InvalidParameterError(
                "stateful_datetime requires ctx.schema_name to be set"
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

        dt = datetime.fromtimestamp(timestamp / 1_000_000, tz=UTC)
        dt = self._apply_tz(dt)

        try:
            return dt.strftime(self.format)
        except Exception as exc:
            raise InvalidParameterError(f"invalid datetime.format: {exc}")
