from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, List

from havocforge.context import GenContext
from havocforge.errors import ContextError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import InvalidParameterError
from havocforge.registry import Registry


if TYPE_CHECKING:  # import only for typing to avoid cycles
    from havocforge.types import JsonValue  # noqa: F401


# TODO: move to constants
# TODO(arch): use global timezone config from config/DEPRICATED.yaml
UTC = timezone.utc


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class TimestampGenerator(BaseGenerator):
    """Generate a Unix timestamp (microseconds) within a time window.

    Args:
        start (int | float | str | None): Start moment as ISO8601 string or numeric epoch (sec/ms/us).
        end (int | float | str | None): End moment as ISO8601 string or numeric epoch (sec/ms/us).

    Raises:
        ContextError: If ``ctx`` is not a ``GenContext`` in ``generate``.
        InvalidParameterError: If bounds are invalid or unparsable.
    """

    __meta__ = {
        "aliases": {
            "end": "end",
            "start": "start",
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
    }
    __slots__ = ("start", "end", "depends_on", "bound_to", "bound_to_schema", "bound_to_revision", "pool", "depends_on_pool")
    __aliases__ = ("timestamp",)

    # TODO(defaults): Make the fallback window configurable (currently last 365 days).

    def __init__(
        self,
        start: int | float | str | None = None,
        end: int | float | str | None = None,
        depends_on: str | None = None,
        bound_to: str | None = None,
        bound_to_schema: str | None = None,
        bound_to_revision: int | None = None,
        pool: List[str] | bool | None = None,
        depends_on_pool: str | None = None,
    ) -> None:
        """Initialize bounds.

        Args:
            start (int | float | str | None): Start moment as ISO8601 string or epoch.
            end (int | float | str | None): End moment as ISO8601 string or epoch.
            depends_on (str | None): Field name to derive from (e.g., "event_date").
            bound_to (str | None): Anchor field name for entity correlation.
        """
        self.start = start
        self.end = end
        self.depends_on = depends_on
        self.bound_to = bound_to
        self.bound_to_schema = bound_to_schema
        self.bound_to_revision = bound_to_revision
        self.pool = pool
        self.depends_on_pool = depends_on_pool

    @classmethod
    def from_spec(
        cls,
        builder: Any,
        spec: Mapping[str, Any],
    ) -> "TimestampGenerator":
        """Construct from a generator specification mapping.

        Args:
            builder (Any): Unused builder/factory (kept for signature parity).
            spec (Mapping[str, Any]): Mapping possibly containing ``start``, ``end``, and ``depends_on``.

        Returns:
            TimestampGenerator: Configured instance.
        """
        return cls(
            start=spec.get("start"),
            end=spec.get("end"),
            depends_on=spec.get("depends_on"),
            bound_to=spec.get("bound_to") or spec.get("linked_to"),
            bound_to_schema=spec.get("bound_to_schema"),
            bound_to_revision=spec.get("bound_to_revision"),
            pool=spec.get("pool"),
            depends_on_pool=spec.get("depends_on_pool"),
        )

    # TODO(move): Move to utils
    def _infer_div(self, value: float) -> float:
        """Infer divisor for numeric epochs (seconds/millis/micros).

        Args:
            value (float): Numeric epoch as provided.

        Returns:
            float: Divisor to convert value to seconds.
        """
        if value >= 1_000_000_000_000_000:  # micros
            return 1_000_000.0
        if value >= 1_000_000_000_000:  # millis
            return 1_000.0
        return 1.0  # seconds

    def _parse_dt(
        self, value: int | float | str | None, default_dt: datetime
    ) -> datetime:
        """Parse a bound value into a UTC ``datetime``.

        Args:
            value (int | float | str | None): ISO8601 string or epoch value; ``None`` uses ``default_dt``.
            default_dt (datetime): Datetime to use when ``value`` is ``None``.

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
            except ValueError:
                raise InvalidParameterError(
                    "timestamp.start/end must be ISO8601 or numeric epoch"
                )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        raise InvalidParameterError(
            "timestamp.start/end must be ISO8601 or numeric epoch"
        )

    def _sanity_check(self, ctx: GenContext) -> None:
        """Validate context and that bounds are parseable.

        Args:
            ctx (GenContext): Active generation context.

        Raises:
            ContextError: If ``ctx`` is not a ``GenContext``.
        """
        if not isinstance(ctx, GenContext):
            raise ContextError("ctx must be an instance of GenContext")
        now = datetime.now(tz=UTC)
        _ = self._parse_dt(self.start, now.replace(year=now.year - 1))
        _ = self._parse_dt(self.end, now)

    def _generate_impl(self, ctx: GenContext) -> "JsonValue":
        """Produce a timestamp (microseconds) according to configuration.

        If ``depends_on`` is set, derives the timestamp from ``ctx._depends_on`` (a datetime string).
        Otherwise, generates a random timestamp within the configured bounds.

        Args:
            ctx (GenContext): Generation context providing RNG via ``ctx.rng``.

        Returns:
            JsonValue: Integer microseconds since Unix epoch.
        """
        if self.depends_on:
            if not hasattr(ctx, "_depends_on") or ctx._depends_on is None:
                raise InvalidParameterError(
                    f"timestamp generator depends on '{self.depends_on}' but ctx._depends_on is not set"
                )

            datetime_value = ctx._depends_on
            if not isinstance(datetime_value, str):
                raise InvalidParameterError(
                    f"depends_on source must be datetime string, got {type(datetime_value)}"
                )

            try:
                dt = datetime.fromisoformat(datetime_value)
            except ValueError:
                try:
                    dt = datetime.strptime(datetime_value, "%Y%m%d")
                except ValueError:
                    raise InvalidParameterError(
                        f"Could not parse datetime string '{datetime_value}' "
                        "(expected ISO8601 or YYYYMMDD format)"
                    )

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = dt.astimezone(UTC)

            return int(round(dt.timestamp() * 1_000_000))

        self._sanity_check(ctx)
        now = datetime.now(tz=UTC)
        start_dt = self._parse_dt(self.start, now.replace(year=now.year - 1))
        end_dt = self._parse_dt(self.end, now)
        if end_dt < start_dt:
            raise InvalidParameterError("timestamp.end must be >= start")
        span_seconds = (end_dt - start_dt).total_seconds()
        choose_seconds = ctx.rng.random() * span_seconds if span_seconds > 0 else 0.0
        dt = (
            start_dt + (end_dt - start_dt) * (choose_seconds / span_seconds)
            if span_seconds > 0
            else start_dt
        )
        return int(round(dt.timestamp() * 1_000_000))
