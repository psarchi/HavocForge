"""Timeline state management for late arrival simulation.

Thread-safe tracking of first and current timestamps per schema to support
out-of-order event generation for stream processing testing scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Dict, Optional, Tuple

from havocforge.observability import (
    temporal_tracker_elapsed_seconds,
    temporal_tracker_current_timestamp,
    temporal_tracker_resets_total,
)


@dataclass
class TimelineState:
    """Timeline tracking for a single schema.

    Attributes:
        schema_name: Canonical schema name
        first_timestamp: First timestamp ever generated (microseconds)
        current_timestamp: Latest timestamp so far (microseconds)
    """

    schema_name: str
    first_timestamp: Optional[int] = None
    current_timestamp: Optional[int] = None


class TemporalTracker:
    """Thread-safe timeline state management for late arrival simulation.

    Tracks first and current timestamps per schema to enable smart late
    arrival windows based on elapsed time. Similar to DriftCoordinator
    but focused on temporal state.

    Example usage:
        tracker = TemporalTracker()
        state = tracker.get_or_init("ga4", 1732378800000000)
        tracker.update_timeline("ga4", 1732378860000000)
        first, current = tracker.get_range("ga4")
        elapsed = current - first
        late_window = min(elapsed * 0.1, 3600_000_000)
        late_ts = random.randint(current - late_window, current)
    """

    def __init__(self) -> None:
        """Initialize tracker with empty timeline state."""
        self._lock = Lock()
        self._timelines: Dict[str, TimelineState] = {}

    def get_or_init(self, schema_name: str, initial_ts: int) -> TimelineState:
        """Get existing timeline or initialize with first timestamp.

        Args:
            schema_name: Schema to track
            initial_ts: Timestamp in microseconds to use if initializing

        Returns:
            TimelineState for the schema
        """
        with self._lock:
            state = self._timelines.get(schema_name)
            if state is None:
                state = TimelineState(
                    schema_name=schema_name,
                    first_timestamp=initial_ts,
                    current_timestamp=initial_ts,
                )
                self._timelines[schema_name] = state
            return state

    def update_timeline(self, schema_name: str, timestamp: int) -> None:
        """Update current timestamp if it's later than existing.

        Args:
            schema_name: Schema to update
            timestamp: New timestamp in microseconds
        """
        with self._lock:
            state = self._timelines.get(schema_name)
            if state is None:
                # Initialize if not exists
                state = TimelineState(
                    schema_name=schema_name,
                    first_timestamp=timestamp,
                    current_timestamp=timestamp,
                )
                self._timelines[schema_name] = state
            elif state.current_timestamp is None or timestamp > state.current_timestamp:
                state.current_timestamp = timestamp

            if state.first_timestamp and state.current_timestamp:
                elapsed_seconds = (
                    state.current_timestamp - state.first_timestamp
                ) / 1_000_000
                temporal_tracker_elapsed_seconds.labels(schema=schema_name).set(
                    elapsed_seconds
                )
                temporal_tracker_current_timestamp.labels(schema=schema_name).set(
                    state.current_timestamp
                )

    def get_range(self, schema_name: str) -> Tuple[Optional[int], Optional[int]]:
        """Return (first_timestamp, current_timestamp) for schema.

        Args:
            schema_name: Schema to query

        Returns:
            Tuple of (first_timestamp, current_timestamp) in microseconds,
            or (None, None) if schema not tracked
        """
        with self._lock:
            state = self._timelines.get(schema_name)
            if state is None:
                return (None, None)
            return (state.first_timestamp, state.current_timestamp)

    def get_state(self, schema_name: str) -> Optional[TimelineState]:
        """Return the timeline state for a schema (read-only; testing/debug).

        Args:
            schema_name: Schema to query

        Returns:
            TimelineState or None if not tracked
        """
        with self._lock:
            return self._timelines.get(schema_name)

    def reset(self, schema_name: str) -> None:
        """Clear timeline for a schema.

        Args:
            schema_name: Schema to reset
        """
        with self._lock:
            if schema_name in self._timelines:
                self._timelines.pop(schema_name)
                temporal_tracker_resets_total.labels(schema=schema_name).inc()

    def clear_all(self) -> None:
        """Clear all timelines."""
        with self._lock:
            self._timelines.clear()

    def list_schemas(self) -> list[str]:
        """Return list of schemas being tracked.

        Returns:
            List of schema names
        """
        with self._lock:
            return list(self._timelines.keys())
