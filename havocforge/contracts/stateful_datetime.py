"""Contract for stateful datetime generator."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Optional, Set

from pydantic import ConfigDict

from havocforge.contracts.base import ContractModel


class StatefulDateTimeGeneratorSpec(ContractModel):
    """Stateful datetime generator with late arrival support.

    Generates sequential formatted datetime strings that increment on each generation.
    Integrates with TemporalTracker for state management and supports
    late arrival mode for out-of-order event simulation.

    Attributes:
        start: Start timestamp (required) as ISO8601 string or numeric epoch.
        end: Optional end timestamp. If provided, stops at this value.
        increment: Microseconds to add per generation (required).
        format: strftime format string for output (default ISO8601).
        tz: Fixed timezone offset like "+04:00" (default UTC).
    """

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "stateful_datetime"
    type_aliases: ClassVar[Set[str]] = {
        "datetime_stateful",
        "dt_stateful",
    }

    start: int | float | str | datetime
    end: Optional[int | float | str | datetime] = None
    increment: int
    format: Optional[str] = None
    tz: Optional[str] = None

    def to_spec(self, name: str, adapt) -> dict:
        """Convert to generator spec dict.

        Args:
            name: Field name (unused here).
            adapt: Adaptation function (unused here).

        Returns:
            Generator specification dictionary.
        """

        def enc(x):
            if x is None:
                return None
            if isinstance(x, (int, float, str)):
                return x
            if isinstance(x, datetime):
                return x.isoformat()
            return str(x)

        out: dict = {"type": "stateful_datetime"}
        out["start"] = enc(self.start)
        if self.end is not None:
            out["end"] = enc(self.end)
        out["increment"] = self.increment
        if self.format is not None:
            out["format"] = self.format
        if self.tz is not None:
            out["tz"] = self.tz
        return out
