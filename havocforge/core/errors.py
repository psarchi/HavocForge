from __future__ import annotations
from havocforge.errors import HavocforgeError


class RegistryError(HavocforgeError):
    """Errors around generator registration and lookup."""


class DuplicateAliasError(RegistryError):
    """Two or more generators registered with the same alias."""


class UnknownGeneratorError(RegistryError):
    """Requested generator alias or type is not registered."""


class InvalidRegistrationError(RegistryError):
    """Attempt to register an invalid generator or malformed entry."""


class FactoryError(HavocforgeError):
    """Errors raised by the factory when building/configuring generators."""


class MissingConfigureMethodError(FactoryError):
    """Generator lacks a `configure` method expected by the factory."""


class GeneratorInstantiationError(FactoryError):
    """Generator could not be instantiated from provided parameters."""
