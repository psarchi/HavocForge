from __future__ import annotations

from typing import Any, Mapping, Sequence


class HavocforgeError(Exception):
    """Base exception for all havocforge errors."""

    def __init__(
        self,
        message: str | None = None,
        *,
        path: Sequence[str | int] | str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        self.path = self._normalize_path(path)
        self.context = dict(context) if context else {}
        self.message = message or ""
        formatted = self.message
        if self.path:
            formatted = f"[{self._format_path(self.path)}] {formatted}"
        super().__init__(formatted)

    @staticmethod
    def _normalize_path(
        path: Sequence[str | int] | str | None,
    ) -> tuple[str | int, ...] | None:
        if path is None:
            return None
        if isinstance(path, str):
            if "." in path:
                return tuple(part for part in path.split(".") if part)
            if "/" in path:
                return tuple(part for part in path.split("/") if part)
            return (path,)
        return tuple(path)

    @staticmethod
    def _format_path(path: Sequence[str | int]) -> str:
        return ".".join(str(p) for p in path)

    def to_dict(self) -> dict[str, Any]:
        """Structured representation for logging/serialization."""
        return {
            "message": self.message,
            "path": list(self.path) if self.path else None,
            "context": self.context or None,
        }


class ContextError(HavocforgeError):
    """Context-level issues (seed, RNG, locale)."""


class InvalidRNGError(ContextError):
    """Provided RNG is invalid or unsupported."""


class InvalidLocaleError(ContextError):
    """Requested locale is invalid for Faker or not available."""


class ConfigError(HavocforgeError):
    """Configuration or setup issues."""


class SpecError(HavocforgeError):
    """Spec or schema contract problems."""


class MissingTypeError(SpecError):
    """`type` key is required but missing in a spec node."""


class InvalidSpecStructureError(SpecError):
    """Spec structure is invalid for the targeted generator/contract."""


class UnknownTypeError(SpecError):
    """`type` key provided but does not map to a known generator/contract."""


class NormalizationError(SpecError):
    """Spec values cannot be normalized or coerced into valid form."""


class RegistryError(HavocforgeError):
    """Registry issues (registration conflicts or lookups)."""


class MissingRegistryKeyError(RegistryError):
    """Registry entry is missing a required key or alias."""


class DuplicateRegistryKeyError(RegistryError):
    """Registry entry conflicts with an existing key or alias."""


class APIError(HavocforgeError):
    """API-layer translation or request/response failures."""


class ChaosError(HavocforgeError):
    """Chaos subsystem failures."""


class ValidationError(HavocforgeError):
    """Schema/contract validation failures."""


class PersistenceError(HavocforgeError):
    """Persistence subsystem failures."""


class StreamingError(HavocforgeError):
    """Streaming subsystem failures."""


class PoolEmptyError(RuntimeError):
    """Pool has no records. Source schema must be generated first."""


class SchemaConfigError(ValueError):
    """Schema references a pool field that wasn't included in the pool definition."""
