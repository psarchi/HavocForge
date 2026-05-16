from __future__ import annotations
from havocforge.errors import HavocforgeError


class GeneratorError(HavocforgeError):
    """Base class for all generator runtime/initialization errors."""


class GeneratorInitError(GeneratorError):
    """Failed during generator initialization or validation."""


class GenerationError(GeneratorError):
    """Failure during value generation."""


class InvalidParameterError(GeneratorError):
    """Configuration parameter is invalid in value or type."""


class OutOfBoundsError(GeneratorError):
    """A numeric/date range is invalid or a generated value is out of bounds."""


class EmptyEnumError(GeneratorError):
    """Enum/selection source is empty when at least one option is required."""


class InvalidChildGeneratorError(GeneratorError):
    """Composite generator received an invalid child instance or alias."""


class CompositeError(GeneratorError):
    """Base class for composite generators (array, object)."""


class ArrayConfigError(CompositeError):
    """Array generator config (min_items/max_items/child) is invalid."""


class MissingChildError(ArrayConfigError):
    """Array/object generator is missing required child/fields definition."""


class InvalidMinItemsError(ArrayConfigError):
    """`min_items` is invalid (negative or incompatible type)."""


class InvalidMaxItemsError(ArrayConfigError):
    """`max_items` is invalid (less than min or incompatible type)."""


class MaxLessThanMinError(ArrayConfigError):
    """`max_items` is less than `min_items` when both are provided."""


class ObjectConfigError(CompositeError):
    """Object generator config is invalid."""


class MissingFieldsError(ObjectConfigError):
    """Object generator is missing `fields` mapping."""


class InvalidFieldTypeError(ObjectConfigError):
    """A field entry has an invalid type/value for an object generator."""

class InvalidSchemaNameError(ObjectConfigError):
    """Couldn't Find Schema Name"""
