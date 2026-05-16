from __future__ import annotations

from typing import Optional

from havocforge.chaos.manager import ChaosManager
from havocforge.chaos.ops.base import BaseChaosOp
from havocforge.chaos.drift import DriftCoordinator, get_drift_coordinator
from havocforge.chaos.trackers.temporal_tracker import TemporalTracker

__all__ = [
    "ChaosManager",
    "BaseChaosOp",
    "DriftCoordinator",
    "get_drift_coordinator",
    "TemporalTracker",
    "get_temporal_tracker",
]

# Singleton instance
_temporal_tracker: Optional[TemporalTracker] = None


def get_temporal_tracker() -> TemporalTracker:
    """Return singleton TemporalTracker instance.

    Returns:
        Global TemporalTracker instance
    """
    global _temporal_tracker
    if _temporal_tracker is None:
        _temporal_tracker = TemporalTracker()
    return _temporal_tracker
