from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, List, Self

from havocforge.context import GenContext
from havocforge.errors import ContextError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import InvalidParameterError

from havocforge.registry import Registry


if TYPE_CHECKING:  # avoid import cycles at runtime
    from havocforge.contracts.types import JsonValue  # noqa : F401


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class IntGenerator(BaseGenerator):
    """Generate integers in ``[min, max]`` with an optional ``step``.

    Args:
        min (int | None): Minimum value (inclusive). Defaults to ``0``.
        max (int | None): Maximum value (inclusive). Defaults to ``100``.
        step (int | None): Step size between values. Defaults to ``1``.

    Raises:
        ContextError: If ``ctx`` is not a ``GenContext`` in ``generate``.
        InvalidParameterError: If ``min > max`` or ``step <= 0``.
    """

    __meta__ = {
        "aliases": {
            "max": "max",
            "min": "min",
            "step": "step",
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
    __slots__ = ("min", "max", "step", "bound_to", "bound_to_schema", "bound_to_revision", "pool", "depends_on_pool")
    __aliases__ = ("int",)

    # TODO(defaults): Allow overriding the default bounds via global config.

    def __init__(
        self,
        min: int | None = None,
        max: int | None = None,
        step: int | None = None,
        bound_to: str | None = None,
        bound_to_schema: str | None = None,
        bound_to_revision: int | None = None,
        pool: List[str] | bool | None = None,
        depends_on_pool: str | None = None,
    ) -> None:
        """Initialize bounds and step.

        Args:
            min (int | None): Minimum value (inclusive). If ``None``, defaults to ``0``.
            max (int | None): Maximum value (inclusive). If ``None``, defaults to ``100``.
            step (int | None): Step size between values. If ``None``, defaults to ``1``.
            bound_to (str | None): Anchor field name for entity correlation.
        """
        self.min: int = 0 if min is None else int(min)
        self.max: int = 100 if max is None else int(max)
        self.step: int = 1 if step is None else int(step)
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
    ) -> "IntGenerator":
        """Construct from a generator specification mapping.

        Args:
            builder (Any): Unused builder/factory (kept for signature parity).
            spec (Mapping[str, Any]): Mapping possibly containing ``min``, ``max``, ``step``.

        Returns:
            IntGenerator: Configured instance.
        """
        return cls(
            min=spec.get("min"),
            max=spec.get("max"),
            step=spec.get("step"),
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
            InvalidParameterError: If bounds/step are invalid.
        """
        if not isinstance(ctx, GenContext):
            raise ContextError("ctx must be an instance of GenContext")
        if self.step <= 0:
            raise InvalidParameterError("step must be > 0")
        if self.min > self.max:
            raise InvalidParameterError("min must be <= max")

    def configure(
        self,
        min: int | None = None,
        max: int | None = None,
        step: int | None = None,
        **_: Any,
    ) -> Self:
        """Apply configuration in-place and return ``self``.

        Unknown kwargs are intentionally ignored to preserve behavior.

        Args:
            min (int | None): Optional replacement for ``min``.
            max (int | None): Optional replacement for ``max``.
            step (int | None): Optional replacement for ``step``.
            **_ (Any): Ignored extra arguments.

        Returns:
            Self: ``self`` for fluent chaining.
        """
        if min is not None:
            self.min = int(min)
        if max is not None:
            self.max = int(max)
        if step is not None:
            self.step = int(step)
        return self

    def _generate_impl(self, ctx: GenContext) -> "JsonValue":
        """Produce an integer according to the configuration.

        Args:
            ctx (GenContext): Generation context providing RNG via ``ctx.rng``.

        Returns:
            JsonValue: ``int`` within ``[min, max]`` following the configured ``step``.
        """
        self._sanity_check(ctx)
        span = self.max - self.min
        count = span // self.step + 1
        if count <= 0:
            raise InvalidParameterError("empty range for step")
        index = ctx.rng.randint(0, count - 1)
        return self.min + index * self.step
