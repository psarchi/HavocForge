from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from havocforge.context import GenContext
from havocforge.errors import ContextError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import InvalidParameterError, MissingChildError
from havocforge.registry import Registry


if TYPE_CHECKING:  # avoid import cycles at runtime
    from havocforge.contracts.types import JsonValue  # noqa : F401


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class StringOrNullGenerator(BaseGenerator):
    """String-or-null composite generator.
        Delegates to a child generator that should return a string, or returns ``None``.
        Selection can be uniform (no weights provided) or weighted using a two-item
        sequence ``[string_weight, null_weight]``.
    Return a string from a child generator or ``None`` based on weights.

    Args:
        child (BaseGenerator | None): Built child generator expected to return a string.
        weights (Sequence[float] | None): Two-item sequence ``[string_w, null_w]``.
    """

    __meta__ = {
        "aliases": {"of": "of", "weights": "weights", "bound_to": "bound_to", "linked_to": "bound_to"},
        "deprecations": [],
        "rules": [],
    }
    __slots__ = ("child", "weights", "bound_to")
    __aliases__ = ("string_or_null",)

    def __init__(
        self,
        child: BaseGenerator | None = None,
        weights: Sequence[float] | None = None,
        bound_to: str | None = None,
    ) -> None:
        """Initialize with optional child and weights."""
        self.child = child
        self.weights = weights
        self.bound_to = bound_to

    # TODO(arch): depend on a builder/factory protocol instead of a concrete object
    @classmethod
    def from_spec(
        cls,
        builder: Any,
        spec: Mapping[str, object],
    ) -> "StringOrNullGenerator":
        """Construct an instance from a generator specification.

        The spec must provide a child generator under ``of``; optional ``weights``
        is a two-item sequence ``[string_w, null_w]``.

        Args:
            builder (Any): Object exposing ``build(spec: Mapping[str, object]) -> BaseGenerator``.
            spec (Mapping[str, object]): Parsed generator specification.

        Returns:
            StringOrNullGenerator: Configured instance.

        Raises:
            MissingChildError: If ``of`` is missing.
        """
        of_spec = spec.get("of") or spec.get("child")
        if of_spec is None:
            raise MissingChildError("string_or_null requires an 'of' child spec")
        child = builder.build(of_spec)
        return cls(child=child, weights=spec.get("weights"), bound_to=spec.get("bound_to") or spec.get("linked_to"))  # type: ignore[arg-type]

    def _sanity_check(self, ctx: GenContext) -> None:
        """Validate context and configuration invariants.

        Args:
            ctx (GenContext): Execution context.

        Raises:
            ContextError: If ``ctx`` is not a ``GenContext``.
            MissingChildError: No child generator configured.
            InvalidParameterError: ``weights`` invalid (type/length/numeric/sum).
        """
        if not isinstance(ctx, GenContext):
            raise ContextError("ctx must be an instance of GenContext")
        if self.child is None:
            raise MissingChildError("string_or_null requires a child generator")

        if self.weights is None:
            return
        if not isinstance(self.weights, (list, tuple)) or len(self.weights) != 2:
            raise InvalidParameterError(
                "weights must be a two-item list: [string, null]"
            )
        try:
            string_w = float(self.weights[0])
            null_w = float(self.weights[1])
        except (TypeError, ValueError) as exc:
            # TODO(errors): use a typed error (e.g., InvalidWeightsValueError) with offending index
            raise InvalidParameterError("weights must be numeric") from exc
        if string_w < 0 or null_w < 0:
            raise InvalidParameterError("weights must be non-negative")
        if string_w + null_w <= 0:
            raise InvalidParameterError("sum(weights) must be > 0")

    def configure(
        self,
        child: BaseGenerator | None = None,
        weights: Sequence[float] | None = None,
        **_: Any,
    ) -> "StringOrNullGenerator":
        """Update configuration and return ``self``.

        Args:
            child (BaseGenerator | None): Replacement child generator.
            weights (Sequence[float] | None): Replacement two-item sequence.
            **_ (Any): Ignored extra kwargs for forward-compatibility.

        Returns:
            StringOrNullGenerator: ``self`` for chaining.
        """
        if child is not None:
            self.child = child
        if weights is not None:
            self.weights = weights
        return self

    def _generate_impl(self, ctx: GenContext) -> "JsonValue":
        """Return the child's string or ``None`` according to weights.

        Args:
            ctx (GenContext): Execution context providing RNG/state.

        Returns:
            JsonValue: String value from the child, or ``None``.
        """
        self._sanity_check(ctx)

        # TODO(behavior): if weights are missing, current policy is 50/50; consider making configurable
        if self.weights is None:
            return None if ctx.rng.random() < 0.5 else self.child.generate(ctx)

        string_w = float(self.weights[0])  # guaranteed by _sanity_check
        null_w = float(self.weights[1])
        threshold = string_w / (string_w + null_w)
        return (
            self.child.generate(ctx)
            if ctx.rng.random() < threshold
            else None
        )
