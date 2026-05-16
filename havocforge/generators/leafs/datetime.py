from __future__ import annotations
from datetime import datetime, timedelta, timezone
import re
from typing import Any, List, Mapping, Optional, Tuple

from havocforge.generators.errors import InvalidParameterError
from havocforge.generators.base import BaseGenerator
from havocforge.context import GenContext
from havocforge.registry import Registry

UTC = timezone.utc
ISO_DEFAULT = "%Y-%m-%dT%H:%M:%S%z"
r_time = r"(\d{2}):(\d{2})(?::(\d{2}))?"
r_tz = r"([+-])(\d{2}):(\d{2})"
# TODO(config): Allow overriding ISO_DEFAULT via global settings.
# TODO(arch): use global timezone config from config/default.yaml
# TODO(refractor): unify with TimestampGenerator maybe?


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class DateTimeGenerator(BaseGenerator):
    """Generate formatted datetimes within optional bounds and timezone.

    Configuration accepts absolute bounds (``start``/``end`` as ISO8601 or epoch),
    time-of-day bounds (``time_start``/``time_end``), output ``format`` (``strftime``
    compatible), and an optional fixed timezone offset ``tz`` like "+04:00".

    Attributes:
        start (int | float | str | None): ISO8601 string or epoch for lower bound.
        end (int | float | str | None): ISO8601 string or epoch for upper bound.
        format (str): ``strftime`` format string for output.
        time_start (str | None): Lower time-of-day bound ("HH:MM" or "HH:MM:SS").
        time_end (str | None): Upper time-of-day bound ("HH:MM" or "HH:MM:SS").
        tz (str | None): Fixed timezone offset like "+04:00".
    """

    __meta__ = {
        "aliases": {
            "end": "end",
            "format": "format",
            "start": "start",
            "time_end": "time_end",
            "time_start": "time_start",
            "tz": "tz",
            "depends_on": "depends_on",
            "bound_to": "bound_to",
            "linked_to": "bound_to",
            "bound_to_schema": "bound_to_schema",
            "bound_to_revision": "bound_to_revision",
            "pool": "pool",
            "depends_on_pool": "depends_on_pool",
        },
        "deprecations": [],
        "rules": [],
        # TODO(versioning): introduce per-generator semver once contracts stabilize.
    }
    __slots__ = (
        "start", "end", "format", "time_start", "time_end", "tz",
        "depends_on", "bound_to", "bound_to_schema", "bound_to_revision",
        "pool", "depends_on_pool",
    )
    __aliases__ = ("datetime",)

    def __init__(
        self,
        start: int | float | str | None = None,
        end: int | float | str | None = None,
        format: Optional[str] = None,
        time_start: Optional[str] = None,
        time_end: Optional[str] = None,
        tz: Optional[str] = None,
        depends_on: Optional[str] = None,
        bound_to: Optional[str] = None,
        bound_to_schema: str | None = None,
        bound_to_revision: int | None = None,
        pool: List[str] | bool | None = None,
        depends_on_pool: str | None = None,
    ) -> None:
        """Initialize the generator.

        Args:
            start (int | float | str | None): Lower bound as ISO8601 string or epoch seconds/millis/micros.
            end (int | float | str | None): Upper bound as ISO8601 string or epoch seconds/millis/micros.
            format (str | None): ``strftime`` output format. Defaults to ``ISO_DEFAULT``.
            time_start (str | None): Lower time-of-day bound ("HH:MM" or "HH:MM:SS").
            time_end (str | None): Upper time-of-day bound ("HH:MM" or "HH:MM:SS").
            tz (str | None): Fixed offset like "+04:00"; if ``None``, UTC is used.
            depends_on (str | None): Field name to derive from (e.g., "event_timestamp").
            bound_to (str | None): Anchor field name for entity correlation.
        """
        self.start = start
        self.end = end
        self.format = format or ISO_DEFAULT
        self.time_start = time_start
        self.time_end = time_end
        self.tz = tz
        self.depends_on = depends_on
        self.bound_to = bound_to
        self.bound_to_schema = bound_to_schema
        self.bound_to_revision = bound_to_revision
        self.pool = pool
        self.depends_on_pool = depends_on_pool

    @classmethod
    def from_spec(cls, builder: Any, spec: Mapping[str, Any]) -> "DateTimeGenerator":
        """Construct from a spec mapping.

        Args:
            builder (Any): Unused here; kept for a uniform factory signature.
            spec (Mapping[str, Any]): Mapping providing configuration keys.

        Returns:
            DateTimeGenerator: Configured instance.
        """
        return cls(
            start=spec.get("start"),
            end=spec.get("end"),
            format=spec.get("format"),
            time_start=spec.get("time_start"),
            time_end=spec.get("time_end"),
            tz=spec.get("tz"),
            depends_on=spec.get("depends_on"),
            bound_to=spec.get("bound_to") or spec.get("linked_to"),
            bound_to_schema=spec.get("bound_to_schema"),
            bound_to_revision=spec.get("bound_to_revision"),
            pool=spec.get("pool"),
            depends_on_pool=spec.get("depends_on_pool"),
        )

    def _infer_div(self, epoch_value: float) -> float:
        """Infer divisor for numeric epochs (seconds/millis/micros).

        Args:
            epoch_value (float): Numeric epoch as provided.

        Returns:
            float: Divisor to convert value to seconds.
        """
        if epoch_value >= 1_000_000_000_000_000:  # micros
            return 1_000_000.0
        if epoch_value >= 1_000_000_000_000:  # millis
            return 1_000.0
        return 1.0  # seconds

    def _parse_moment(
        self, value: int | float | str | None, default_dt: datetime
    ) -> datetime:
        """Parse a bound value into a UTC ``datetime``.

        Args:
            value (int | float | str | None): ISO8601 string or epoch value; ``None`` uses ``default_dt``.
            default_dt (datetime): Datetime to use when ``value`` is ``None".

        Returns:
            datetime: Parsed UTC datetime.

        Raises:
            InvalidParameterError: If the value cannot be parsed.
        """
        if value is None:
            return default_dt
        if isinstance(value, (int, float)):
            divisor = self._infer_div(float(value))
            return datetime.fromtimestamp(float(value) / divisor, tz=UTC)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value)
            except Exception:
                # TODO(errors): narrow except to parsing-specific errors when standardizing inputs.
                raise InvalidParameterError(
                    "datetime.start/end must be ISO8601 or numeric epoch"
                )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        raise InvalidParameterError(
            "datetime.start/end must be ISO8601 or numeric epoch"
        )

    def _parse_time(self, time_text: Optional[str]) -> Tuple[int, int, int]:
        """Parse time-of-day string to (hour, minute, second).

        Args:
            time_text (str | None): Text like "HH:MM" or "HH:MM:SS".

        Returns:
            tuple[int, int, int]: (hour, minute, second).

        Raises:
            InvalidParameterError: On format mismatch or out-of-range values.
        """
        match = re.fullmatch(r_time, time_text or "")
        if not match:
            raise InvalidParameterError(
                "time_start/time_end must be 'HH:MM' or 'HH:MM:SS'"
            )
        hour, minute, second = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3) or 0),
        )
        if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
            raise InvalidParameterError("time_start/time_end out of range")
        return hour, minute, second

    def _apply_tz(self, dt: datetime) -> datetime:
        """Apply a fixed offset ``tz`` if configured.

        Args:
            dt (datetime): Datetime to convert.

        Returns:
            datetime: Datetime in the configured fixed offset or unchanged if not set.

        Raises:
            InvalidParameterError: If ``tz`` is not in "+HH:MM"/"-HH:MM" form.
        """
        if not self.tz:
            return dt
        # TODO(validation): Accept 'Z'/'UTC' synonyms when we standardize timezone inputs.
        match = re.fullmatch(r_tz, self.tz)
        if not match:
            raise InvalidParameterError("tz must be like '+04:00' or '-03:30'")
        sign = 1 if match.group(1) == "+" else -1
        hours, minutes = int(match.group(2)), int(match.group(3))
        offset = timezone(sign * timedelta(hours=hours, minutes=minutes))
        return dt.astimezone(offset)

    def _generate_impl(self, ctx: GenContext) -> str:
        """Produce a formatted datetime string within configured bounds.

        If ``depends_on`` is set, derives the datetime from ``ctx._depends_on`` (a timestamp).
        Otherwise, generates a random datetime within the configured bounds.

        If ``time_start``/``time_end`` are provided without absolute bounds, a
        time-of-day window for "today" is used. Otherwise, absolute bounds are
        parsed with UTC normalization.

        Args:
            ctx (GenContext): Execution context providing RNG and state.

        Returns:
            str: Formatted datetime string.

        Raises:
            InvalidParameterError: On invalid bounds or ``format``.
        """
        if self.depends_on:
            if not hasattr(ctx, "_depends_on") or ctx._depends_on is None:
                raise InvalidParameterError(
                    f"datetime generator depends on '{self.depends_on}' but ctx._depends_on is not set"
                )

            timestamp = ctx._depends_on
            if not isinstance(timestamp, (int, float)):
                raise InvalidParameterError(
                    f"depends_on source must be numeric timestamp, got {type(timestamp)}"
                )

            divisor = self._infer_div(float(timestamp))
            dt = datetime.fromtimestamp(float(timestamp) / divisor, tz=UTC)
            dt = self._apply_tz(dt)

            try:
                return dt.strftime(self.format)
            except Exception as exc:
                raise InvalidParameterError(f"invalid datetime.format: {exc}")

        now = datetime.now(tz=UTC)
        if (
            self.start is None
            and self.end is None
            and (self.time_start or self.time_end)
        ):
            base = now.replace(hour=0, minute=0, second=0, microsecond=0)
            start_hour, start_minute, start_second = self._parse_time(
                self.time_start or "00:00:00"
            )
            end_hour, end_minute, end_second = self._parse_time(
                self.time_end or "23:59:59"
            )
            start_dt = base.replace(
                hour=start_hour, minute=start_minute, second=start_second
            )
            end_dt = base.replace(hour=end_hour, minute=end_minute, second=end_second)
        else:
            start_dt = self._parse_moment(self.start, now - timedelta(days=365))
            end_dt = self._parse_moment(self.end, now)

        if end_dt < start_dt:
            raise InvalidParameterError("datetime.end must be >= start")

        span_seconds = (end_dt - start_dt).total_seconds()
        choose_seconds = ctx.rng.random() * span_seconds if span_seconds > 0 else 0.0
        dt = start_dt + timedelta(seconds=choose_seconds)
        dt = self._apply_tz(dt)

        try:
            return dt.strftime(self.format)
        except Exception as exc:
            raise InvalidParameterError(f"invalid datetime.format: {exc}")
