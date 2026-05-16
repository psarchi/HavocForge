from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Mapping, Self

from havocforge.context import GenContext
from havocforge.errors import ContextError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import InvalidParameterError

from havocforge.registry import Registry


if TYPE_CHECKING:  # avoid import cycles at runtime
    from havocforge.contracts.types import JsonValue  # noqa : F401


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class FloatGenerator(BaseGenerator):
    """Generate floating-point numbers within a configurable range.

    Args:
        min (float | None): Minimum value (inclusive). Defaults to ``0.0``.
        max (float | None): Maximum value (inclusive). Defaults to ``1.0``.
        precision (int | None): Number of decimal places to round to; ``None`` for no rounding.

    Raises:
        ContextError: If ``ctx`` is not a ``GenContext`` in ``generate``.
        InvalidParameterError: If ``min > max`` or ``precision < 0``.
    """

    __meta__ = {
        "aliases": {
            "max": "max",
            "min": "min",
            "precision": "precision",
            "bound_to": "bound_to",
            "linked_to": "bound_to",
            "bound_to_schema": "bound_to_schema",
            "bound_to_revision": "bound_to_revision",
            "pool": "pool",
            "depends_on_pool": "depends_on_pool",
        },
        "deprecations": [],
        "rules": [],
    }
    __slots__ = ("min", "max", "precision", "bound_to", "bound_to_schema", "bound_to_revision", "pool", "depends_on_pool")
    __aliases__ = ("float",)

    # TODO(validation): Ensure bounds and precision are finite (no NaN/inf) once global validation utilities are in place.

    def __init__(
        self,
        min: float | None = None,
        max: float | None = None,
        precision: int | None = None,
        bound_to: str | None = None,
        bound_to_schema: str | None = None,
        bound_to_revision: int | None = None,
        pool: List[str] | bool | None = None,
        depends_on_pool: str | None = None,
    ) -> None:
        """Initialize the generator with bounds and precision.

        Args:
            min (float | None): Minimum value (inclusive). If ``None``, defaults to ``0.0``.
            max (float | None): Maximum value (inclusive). If ``None``, defaults to ``1.0``.
            precision (int | None): Decimal places for rounding; ``None`` leaves raw value.
            bound_to (str | None): Anchor field name for entity correlation.
        """
        self.min: float = 0.0 if min is None else float(min)
        self.max: float = 1.0 if max is None else float(max)
        self.precision: int | None = None if precision is None else int(precision)
        self.bound_to = bound_to
        self.bound_to_schema = bound_to_schema
        self.bound_to_revision = bound_to_revision
        self.pool = pool
        self.depends_on_pool = depends_on_pool

    @classmethod
    def from_spec(
        cls,
        builder: Any,
        spec: Mapping[str, Any],
    ) -> "FloatGenerator":
        """Construct from a generator specification mapping.

        Note: Contract suggests returning the concrete class *type*; preserving
        legacy behavior (instance) to avoid breaking callers.

        Args:
            builder (Any): Unused builder/factory (kept for signature parity).
            spec (Mapping[str, Any]): Mapping possibly containing ``min``, ``max``, ``precision``.

        Returns:
            FloatGenerator: Configured instance.
        """
        return cls(
            min=spec.get("min"),
            max=spec.get("max"),
            precision=spec.get("precision"),
            bound_to=spec.get("bound_to") or spec.get("linked_to"),
            bound_to_schema=spec.get("bound_to_schema"),
            bound_to_revision=spec.get("bound_to_revision"),
            pool=spec.get("pool"),
            depends_on_pool=spec.get("depends_on_pool"),
        )

    def _sanity_check(self, ctx: GenContext) -> None:
        """Validate configuration and context preconditions.

        Args:
            ctx (GenContext): Active generation context.

        Raises:
            ContextError: If ``ctx`` is not a ``GenContext``.
            InvalidParameterError: If bounds/precision are invalid.
        """
        if not isinstance(ctx, GenContext):
            raise ContextError("ctx must be an instance of GenContext")
        if self.min > self.max:
            raise InvalidParameterError("min must be <= max")
        if self.precision is not None and self.precision < 0:
            raise InvalidParameterError("precision must be >= 0")

    def configure(
        self,
        min: float | None = None,
        max: float | None = None,
        precision: int | None = None,
        **_: Any,
    ) -> Self:
        """Apply configuration in-place and return ``self``.

        Unknown kwargs are intentionally ignored to preserve behavior.

        Args:
            min (float | None): Optional replacement for ``min``.
            max (float | None): Optional replacement for ``max``.
            precision (int | None): Optional replacement for ``precision``.
            **_ (Any): Ignored extra arguments.

        Returns:
            Self: ``self`` for fluent chaining.
        """
        if min is not None:
            self.min = float(min)
        if max is not None:
            self.max = float(max)
        if precision is not None:
            self.precision = int(precision)
        return self

    def _generate_impl(self, ctx: GenContext) -> "JsonValue":
        """Produce a float according to the configuration.

        Args:
            ctx (GenContext): Generation context providing RNG via ``ctx.rng``.

        Returns:
            JsonValue: ``float`` within ``[min, max]`` (rounded if ``precision`` is set).
        """
        self._sanity_check(ctx)
        value = ctx.rng.random() * (self.max - self.min) + self.min
        if self.precision is not None:
            return round(value, self.precision)
        return value
