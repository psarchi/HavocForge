from __future__ import annotations

"""Drift-specific error types."""

from havocforge.chaos.errors import ChaosError  # noqa: E402


class DriftError(ChaosError):
    """Base class for drift subsystem errors."""


class DriftRegistryError(DriftError):
    """Drift handler registration or lookup failed."""


class InvalidDriftResultError(DriftError):
    """Drift handler returned an unsupported result type."""


class DriftSelectionError(DriftError):
    """Selection utilities encountered invalid inputs (e.g., empty choices)."""


class DriftMutationError(DriftError):
    """Drift mutation failed due to invalid path or parent spec."""
