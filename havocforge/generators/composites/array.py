from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from havocforge.context import GenContext
from havocforge.errors import ContextError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import (
    InvalidMaxItemsError,
    InvalidMinItemsError,
    MaxLessThanMinError,
    MissingChildError,
)
from havocforge.registry import Registry

if TYPE_CHECKING:  # keep annotations strict without import cycles at runtime
    from havocforge.contracts.types import JsonValue  # noqa: F401


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class ArrayGenerator(BaseGenerator):
    """Generate an array of items produced by a child generator.

    Args:
        min_items (int | None): Minimum number of items to generate (inclusive).
        max_items (int | None): Maximum number of items to generate (inclusive).
        child (BaseGenerator | None): A fully constructed child generator.
    """

    __meta__ = {
        "aliases": {
            "child": "child",
            "max_items": "max_items",
            "min_items": "min_items",
        },
        "deprecations": [],
        "rules": [],
    }
    __slots__ = ("min_items", "max_items", "child")
    __aliases__ = ("array", "list")

    def __init__(
        self,
        min_items: int | None = None,
        max_items: int | None = None,
        child: BaseGenerator | None = None,
    ) -> None:
        """Initialize the generator with optional bounds and child."""
        self.min_items = min_items
        self.max_items = max_items
        self.child = child

    # TODO(arch): accept a factory/protocol rather than a concrete builder to reduce coupling
    @classmethod
    def from_spec(cls, builder: Any, spec: Mapping[str, object]) -> ArrayGenerator:
        """Construct an instance from a generator specification.

        The spec must include the child generator under ``child`` (preferred)
        or ``of``. Optional keys: ``min_items``, ``max_items``.

        Args:
            builder (Any): Object with ``build(spec: Mapping[str, object]) -> BaseGenerator``.
            spec (Mapping[str, object]): Parsed generator specification.

        Returns:
            ArrayGenerator: Configured instance.

        Raises:
            MissingChildError: If neither ``child`` nor ``of`` is provided.
        """
        child_spec = spec.get("child") or spec.get("of")
        if not child_spec:
            raise MissingChildError("Array spec requires 'child' or 'of'")
        child = builder.build(child_spec)
        return cls(
            min_items=spec.get("min_items"),  # type: ignore[arg-type]
            max_items=spec.get("max_items"),  # type: ignore[arg-type]
            child=child,
        )

    def _sanity_check(self, ctx: GenContext) -> None:
        """Validate context and configuration invariants.

        Args:
            ctx (GenContext): Execution context.

        Raises:
            ContextError: If ``ctx`` is not a ``GenContext``.
            InvalidMinItemsError: ``min_items`` is present but not an ``int``.
            InvalidMaxItemsError: ``max_items`` is present but not an ``int``.
            MaxLessThanMinError: ``max_items`` is smaller than ``min_items``.
            MissingChildError: No child generator has been configured.
        """
        if not isinstance(ctx, GenContext):
            raise ContextError("ctx must be an instance of GenContext")
        if self.child is None:
            raise MissingChildError("array generator requires a child generator")
        if self.min_items is not None and not isinstance(self.min_items, int):
            raise InvalidMinItemsError("min_items must be int")
        if self.max_items is not None and not isinstance(self.max_items, int):
            raise InvalidMaxItemsError("max_items must be int")
        if self.min_items is not None and self.max_items is not None:
            if self.max_items < self.min_items:
                raise MaxLessThanMinError("max_items must be >= min_items")

    def configure(
        self,
        min_items: int | None = None,
        max_items: int | None = None,
        child: BaseGenerator | None = None,
        **_: Any,
    ) -> ArrayGenerator:
        """Update configuration values in place and return ``self``.

        Args:
            min_items (int | None): New minimum bound (inclusive).
            max_items (int | None): New maximum bound (inclusive).
            child (BaseGenerator | None): Replacement child generator.
            **_ (Any): Ignored extra kwargs for forwards-compatibility.

        Returns:
            ArrayGenerator: ``self`` for chaining.
        """
        if min_items is not None:
            self.min_items = min_items
        if max_items is not None:
            self.max_items = max_items
        if child is not None:
            self.child = child
        return self

    def _generate_impl(self, ctx: GenContext) -> list[JsonValue]:
        """Produce an array value using the configured child generator.

        Args:
            ctx (GenContext): Execution context providing RNG and state.

        Returns:
            list[JsonValue]: Array of values generated by the child.
        """
        self._sanity_check(ctx)

        # TODO(behavior): define default policy when bounds are missing
        min_count = self.min_items or 0
        max_count = self.max_items if self.max_items is not None else min_count
        count = ctx.rng.randint(min_count, max_count)
        # mypy: self.child is guaranteed by _sanity_check
        return [self.child.generate(ctx) for _ in range(count)]
