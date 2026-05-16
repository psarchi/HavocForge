from __future__ import annotations

"""Schema-level error types."""

from havocforge.errors import HavocforgeError  # noqa: E402


class SchemaError(HavocforgeError):
    """Base class for schema package errors."""


class SchemaValidationError(SchemaError):
    """Schema validation failed (structure, types, or values)."""


class SchemaTypeError(SchemaValidationError):
    """Unexpected or missing type fields in schema nodes."""


class SchemaLookupError(SchemaError):
    """Schema registry lookup failed."""


class SchemaRegistryKeyError(SchemaLookupError):
    """Requested schema or path not found."""


class SchemaMutationError(SchemaError):
    """Schema mutation failed (bad path or attribute)."""


class SchemaPreflightError(SchemaError):
    """Schema preflight (synthesize/sample) failed."""
