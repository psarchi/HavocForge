from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Mapping, Sequence, Self

from havocforge.context import GenContext
from havocforge.errors import ContextError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import (
    InvalidParameterError,
    MissingChildError,
)
from havocforge.generators.utils import _pick_index
from havocforge.registry import Registry


if TYPE_CHECKING:  # avoid import cycles at runtime
    from havocforge.contracts.types import JsonValue  # noqa : F401


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class EnumGenerator(BaseGenerator):
    """Pick an element from a configured list of values.

    Supports optional numeric weights aligned positionally with ``values``.

    Args:
        values (Sequence[Any] | None): Candidate values to choose from.
        weights (Sequence[float] | None): Relative weights aligned with ``values``; uniform if omitted.

    Raises:
        MissingChildError: When required ``values`` are absent.
        InvalidParameterError: On invalid weight shapes or totals.
    """

    __meta__ = {
        "aliases": {
            "values": "values",
            "weights": "weights",
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
    __slots__ = ("values", "weights", "bound_to", "bound_to_schema", "bound_to_revision", "pool", "depends_on_pool")
    __aliases__ = ("enum",)

    # TODO(validation): Ensure each weight is non-negative and finite (no NaN/inf).

    def __init__(
        self,
        values: Sequence[Any] | None = None,
        weights: Sequence[float] | None = None,
        bound_to: str | None = None,
        bound_to_schema: str | None = None,
        bound_to_revision: int | None = None,
        pool: List[str] | bool | None = None,
        depends_on_pool: str | None = None,
    ) -> None:
        """Initialize with optional values and weights.

        Args:
            values (Sequence[Any] | None): Candidate values; empty list if ``None``.
            weights (Sequence[float] | None): Relative weights; ``None`` means uniform.
            bound_to (str | None): Anchor field name for entity correlation.
        """
        self.values: list[Any] = list(values) if values else []
        self.weights: list[float] | None = (
            list(weights) if weights is not None else None
        )
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
    ) -> "EnumGenerator":
        """Build an instance from a spec mapping.

        Note: Contract suggests returning the concrete class *type*; preserving
        legacy behavior (instance) to avoid breaking callers.
        # TODO(arch): Revisit to return the class type once callers are updated.

        Args:
            builder (Any): Factory/builder (unused; kept for signature parity).
            spec (Mapping[str, Any]): Mapping possibly containing ``values`` and ``weights``.

        Returns:
            EnumGenerator: Configured instance.
        """
        raw_values = spec.get("values")
        if not raw_values or not isinstance(raw_values, list):
            raise MissingChildError("enum requires 'values' list")

        # Normalize values: flatten {'type': 'foo'} or {'value': 'foo'} to 'foo'
        values: list[Any] = []
        for v in raw_values:
            if isinstance(v, dict):
                if "value" in v:
                    values.append(v.get("value"))
                    continue
                if "type" in v and len(v) == 1:
                    values.append(v.get("type"))
                    continue
            values.append(v)

        return cls(
            values=values,
            weights=spec.get("weights"),
            bound_to=spec.get("bound_to") or spec.get("linked_to"),
            bound_to_schema=spec.get("bound_to_schema"),
            bound_to_revision=spec.get("bound_to_revision"),
            pool=spec.get("pool"),
            depends_on_pool=spec.get("depends_on_pool"),
        )

    def _sanity_check(self, ctx: GenContext) -> None:
        """Validate configuration and context preconditions.

        Args:
            ctx (GenContext): Generation context; must be ``GenContext``.

        Raises:
            ContextError: If ``ctx`` is not a ``GenContext``.
            MissingChildError: If ``values`` is empty.
            InvalidParameterError: If weights are malformed or invalid.
        """
        if not isinstance(ctx, GenContext):
            raise ContextError("ctx must be an instance of GenContext")
        if not self.values:
            raise MissingChildError("enum has no values")
        if self.weights is None:
            return
        if not isinstance(self.weights, (list, tuple)):
            raise InvalidParameterError("weights must be a list")
        if len(self.weights) != len(self.values):
            raise InvalidParameterError("weights length must match values")
        try:
            total = float(sum(self.weights))
        except Exception:  # noqa: BLE001 (kept behavior)
            # TODO(errors): Replace broad exception with a numeric-validation error once defined.
            raise InvalidParameterError("weights must be numeric")
        if total <= 0:
            raise InvalidParameterError("sum(weights) must be > 0")

    def configure(
        self,
        values: Sequence[Any] | None = None,
        weights: Sequence[float] | None = None,
        **_: Any,
    ) -> Self:
        """Apply configuration in-place and return ``self``.

        Unknown kwargs are intentionally ignored to preserve current behavior.

        Args:
            values (Sequence[Any] | None): Optional replacement for ``values``.
            weights (Sequence[float] | None): Optional replacement for ``weights``.
            **_ (Any): Ignored extra arguments.

        Returns:
            Self: ``self`` for fluent chaining.
        """
        if values is not None:
            self.values = list(values)
        if weights is not None:
            self.weights = list(weights)
        return self

    def _generate_impl(self, ctx: GenContext) -> "JsonValue":
        """Produce a value according to the configuration.

        Args:
            ctx (GenContext): Generation context providing RNG via ``ctx.rng``.

        Returns:
            JsonValue: One item from ``values`` (weighted if ``weights`` is provided).
        """
        self._sanity_check(ctx)
        index = _pick_index(self, ctx.rng)
        return self.values[index]
