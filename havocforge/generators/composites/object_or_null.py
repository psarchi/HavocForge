from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from havocforge.context import GenContext
from havocforge.errors import ContextError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import (
    InvalidParameterError,
    MissingChildError,
)
from havocforge.registry import Registry


if TYPE_CHECKING:  # avoid import cycles at runtime
    from havocforge.contracts.types import JsonValue  # noqa : F401


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class ObjectOrNullGenerator(BaseGenerator):
    """Object-or-null composite generator.

        Returns ``None`` with probability ``p_null``; otherwise delegates to a child
        *object* generator and returns its produced mapping.

    Args:
        child (BaseGenerator | None): A built child generator that yields a ``dict``.
        p_null (float | None): Probability of returning ``None`` (0.0–1.0).
    """

    __meta__ = {
        "aliases": {"child": "child", "p_null": "p_null", "bound_to": "bound_to", "linked_to": "bound_to"},
        "deprecations": [],
        "rules": [],
    }
    __slots__ = ("child", "p_null", "bound_to")
    __aliases__ = ("object_or_null",)

    def __init__(
        self,
        child: BaseGenerator | None = None,
        p_null: float | None = None,
        bound_to: str | None = None,
    ) -> None:
        """Initialize with optional child and null probability."""
        self.child = child
        self.p_null = 0.1 if p_null is None else p_null
        self.bound_to = bound_to

    # TODO(arch): depend on a builder/factory protocol instead of a concrete object
    @classmethod
    def from_spec(
        cls,
        builder: Any,
        spec: Mapping[str, object],
    ) -> "ObjectOrNullGenerator":
        """Construct an instance from a generator specification.

        The spec must provide an object generator under ``of`` or a field mapping
        under ``fields``. When ``fields`` is provided, an object generator spec is
        synthesized as ``{"kind": "object", "fields": fields}``.

        Args:
            builder (Any): Object exposing ``build(spec: Mapping[str, object]) -> BaseGenerator``.
            spec (Mapping[str, object]): Parsed generator specification.

        Returns:
            ObjectOrNullGenerator: Configured instance.

        Raises:
            MissingChildError: If neither ``of`` nor ``fields`` is present.
        """
        of_spec = spec.get("of")
        fields_block = spec.get("fields")
        if of_spec is None and fields_block is None:
            raise MissingChildError("object_or_null requires 'fields' or 'of'")
        if of_spec is None:
            of_spec = {"kind": "object", "fields": fields_block}
        child = builder.build(of_spec)
        return cls(child=child, p_null=spec.get("p_null"), bound_to=spec.get("bound_to") or spec.get("linked_to"))  # type: ignore[arg-type]

    def _sanity_check(self, ctx: GenContext) -> None:
        """Validate context and configuration invariants.

        Args:
            ctx (GenContext): Execution context.

        Raises:
            ContextError: If ``ctx`` is not a ``GenContext``.
            MissingChildError: No child generator has been configured.
            InvalidParameterError: ``p_null`` is outside ``[0.0, 1.0]`` or not numeric.
        """
        if not isinstance(ctx, GenContext):
            raise ContextError("ctx must be an instance of GenContext")
        if self.child is None:
            raise MissingChildError("object_or_null requires an object child")
        if self.p_null is None:
            self.p_null = 0.1
        try:
            probability = float(self.p_null)
        except (TypeError, ValueError) as exc:
            # TODO(errors): consider a typed error (e.g., InvalidProbabilityError)
            raise InvalidParameterError(
                "p_null must be a float between 0 and 1"
            ) from exc
        if not 0.0 <= probability <= 1.0:
            raise InvalidParameterError("p_null must be between 0 and 1")

    def configure(
        self,
        child: BaseGenerator | None = None,
        p_null: float | None = None,
        **_: Any,
    ) -> "ObjectOrNullGenerator":
        """Update configuration and return ``self``.

        Args:
            child (BaseGenerator | None): Replacement child generator.
            p_null (float | None): New null probability (0.0–1.0).
            **_ (Any): Ignored extra kwargs for forward-compatibility.

        Returns:
            ObjectOrNullGenerator: ``self`` for chaining.
        """
        if child is not None:
            self.child = child
        if p_null is not None:
            self.p_null = p_null
        return self

    def _generate_impl(self, ctx: GenContext) -> "JsonValue":
        """Return ``None`` with probability ``p_null``; else delegate to child.

        Args:
            ctx (GenContext): Execution context providing RNG/state.

        Returns:
            JsonValue: JSON-compatible value or ``None``.
        """
        self._sanity_check(ctx)
        if ctx.rng.random() < float(self.p_null):
            return None
        # mypy: self.child is validated in _sanity_check
        return self.child.generate(ctx)
