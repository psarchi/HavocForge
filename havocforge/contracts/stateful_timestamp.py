"""Contract for stateful timestamp generator."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Optional, Set

from pydantic import ConfigDict

from havocforge.contracts.base import ContractModel


class StatefulTimestampGeneratorSpec(ContractModel):
    """Stateful timestamp generator with late arrival support.

    Generates sequential timestamps that increment on each generation.
    Integrates with TemporalTracker for state management and supports
    late arrival mode for out-of-order event simulation.

    Attributes:
        start: Start timestamp (required) as ISO8601 string or numeric epoch.
        end: Optional end timestamp. If provided, stops at this value.
        increment: Microseconds to add per generation (required).
    """

    model_config = ConfigDict(extra="forbid")
    type_token: ClassVar[str] = "stateful_timestamp"
    type_aliases: ClassVar[Set[str]] = {
        "timestamp_stateful",
        "ts_stateful",
    }

    start: int | float | str | datetime
    end: Optional[int | float | str | datetime] = None
    increment: int

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

        out: dict = {"type": "stateful_timestamp"}
        out["start"] = enc(self.start)
        if self.end is not None:
            out["end"] = enc(self.end)
        out["increment"] = self.increment
        return out
