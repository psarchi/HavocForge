from __future__ import annotations

"""Chaos subsystem error hierarchy.

High-level chaos errors are defined here. Submodules can add their own
specializations in local error.py files, but should inherit from these bases.
"""

from havocforge.errors import ChaosError as BaseChaosError  # noqa: E402

# Re-export the shared chaos base for convenience.
ChaosError = BaseChaosError


class ChaosRegistryError(ChaosError):
    """Chaos op discovery/lookup failed."""


class MissingChaosOpKeyError(ChaosRegistryError):
    """Chaos op class is missing required key/alias metadata."""


class DuplicateChaosOpKeyError(ChaosRegistryError):
    """Chaos op key/alias conflicts with an existing registration."""


class ChaosOpNotFoundError(ChaosRegistryError):
    """Requested chaos op key is not registered."""


class ChaosConfigError(ChaosError):
    """Invalid or missing chaos configuration values."""


class ChaosOpError(ChaosError):
    """An individual chaos op failed during setup or execution."""


class ChaosOpValidationError(ChaosOpError):
    """Chaos op contract/metadata validation failed."""
