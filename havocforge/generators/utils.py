"""Utility helpers for generator classes.

This module intentionally keeps behavior minimal and side-effect free.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from random import Random
from typing import TYPE_CHECKING, Any, Type, Sequence

from havocforge.generators.errors import EmptyEnumError

if TYPE_CHECKING:
    from havocforge.types import JsonValue  # noqa: F401

UTC = timezone.utc


def get_init_fields(cls: Type[object]) -> list[str]:
    """Return constructor field names for a generator class.

    Args:
        cls (Type[object]): Class to introspect (its ``__init__`` is inspected).

    Returns:
        list[str]: Field names derived from the ``__init__`` signature (excluding ``self``).
    """
    fields = getattr(cls, "_cached_init_fields", None)
    if fields is not None:
        return fields
    sig = inspect.signature(cls.__init__)
    fields = [param.name for param in sig.parameters.values() if param.name != "self"]
    setattr(cls, "_cached_init_fields", fields)
    return fields


def infer_epoch_divisor(value: float) -> float:
    """Infer divisor for numeric epochs (seconds/millis/micros).

    Args:
        value: Numeric epoch as provided.

    Returns:
        Divisor to convert value to seconds.
    """
    if value >= 1_000_000_000_000_000:
        return 1_000_000.0
    if value >= 1_000_000_000_000:
        return 1_000.0
    return 1.0


def parse_timestamp_to_microseconds(
    value: int | float | str | None, default_dt: datetime | None = None
) -> int | None:
    """Parse a timestamp value into microseconds.

    Args:
        value: ISO8601 string, epoch value, or None.
        default_dt: Datetime to use when value is None.

    Returns:
        Microseconds since epoch, or None if value and default_dt are both None.
    """
    from havocforge.generators.errors import InvalidParameterError

    if value is None:
        if default_dt is None:
            return None
        return int(round(default_dt.timestamp() * 1_000_000))

    if isinstance(value, (int, float)):
        divisor = infer_epoch_divisor(float(value))
        dt = datetime.fromtimestamp(float(value) / divisor, tz=UTC)
        return int(round(dt.timestamp() * 1_000_000))

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise InvalidParameterError(
                "timestamp value must be ISO8601 or numeric epoch"
            )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        dt = parsed.astimezone(UTC)
        return int(round(dt.timestamp() * 1_000_000))

    raise InvalidParameterError("timestamp value must be ISO8601 or numeric epoch")


def _pick_index(cls: object, rng: Random) -> int:
    """Pick an index into ``cls.values`` with optional weighting.

    ``cls`` is expected to expose ``values`` (``Sequence[Any]``) and optional
    ``weights`` (``Sequence[float] | None``). When ``weights`` is falsy, a uniform
    selection is performed; otherwise, a linear scan on cumulative weights is used.

    Args:
        cls (object): Holder of ``values`` and optional ``weights`` attributes.
        rng (Random): Deterministic random generator.

    Returns:
        int: Index selected in ``[0, len(cls.values) - 1]``.

    Raises:
        EmptyEnumError: If ``cls.values`` is empty.
    """
    values: Sequence[Any] = getattr(cls, "values")
    if not values:
        raise EmptyEnumError("values must be a non-empty sequence")

    weights: Sequence[float] | None = getattr(cls, "weights", None)
    if not weights:
        return rng.randint(0, len(values) - 1)

    # TODO(validation): Ensure length(weights) == length(values) and all weights are non-negative/finite.
    # TODO(perf): Precompute cumulative weights once and reuse.
    total = float(sum(weights))
    r = rng.random() * total
    acc = 0.0
    for index, weight in enumerate(weights):
        acc += float(weight)
        if r <= acc:
            return index
    return len(values) - 1
