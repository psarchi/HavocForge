from __future__ import annotations

from threading import Lock
from typing import Optional

from havocforge.chaos.drift.coordinator import DriftCoordinator

# Eager import of built-in drift specs so handlers self-register.
from havocforge.chaos.drift.gen_drifts import base as _base  # noqa: F401
from havocforge.chaos.drift.gen_drifts import int_drift as _int_drift  # noqa: F401
from havocforge.chaos.drift.gen_drifts import float_drift as _float_drift  # noqa: F401
from havocforge.chaos.drift.gen_drifts import enum_drift as _enum_drift  # noqa: F401
from havocforge.chaos.drift.gen_drifts import array_drift as _array_drift  # noqa: F401
from havocforge.chaos.drift.gen_drifts import select_drift as _select_drift  # noqa: F401
from havocforge.chaos.drift.gen_drifts import maybe_drift as _maybe_drift  # noqa: F401
from havocforge.chaos.drift.gen_drifts import string_drift as _string_drift  # noqa: F401
from havocforge.chaos.drift.gen_drifts import string_or_null_drift as _string_or_null_drift  # noqa: F401
from havocforge.chaos.drift.gen_drifts import object_or_null_drift as _object_or_null_drift  # noqa: F401
from havocforge.chaos.drift.gen_drifts import timestamp_drift as _timestamp_drift  # noqa: F401
from havocforge.chaos.drift.gen_drifts import one_of_drift as _one_of_drift  # noqa: F401

__all__ = ["DriftCoordinator", "get_drift_coordinator"]

_coordinator: Optional[DriftCoordinator] = None
_coordinator_lock = Lock()


def get_drift_coordinator() -> DriftCoordinator:
    """Return the process-wide drift coordinator singleton."""
    global _coordinator
    if _coordinator is None:
        with _coordinator_lock:
            if _coordinator is None:
                _coordinator = DriftCoordinator()
    return _coordinator
