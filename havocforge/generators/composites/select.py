from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any
from random import Random

from havocforge.context import GenContext
from havocforge.errors import ContextError
from havocforge.generators.base import BaseGenerator
from havocforge.generators.errors import InvalidParameterError, MissingChildError
from havocforge.registry import Registry


if TYPE_CHECKING:  # avoid import cycles at runtime
    from havocforge.contracts.types import JsonValue  # noqa : F401


@Registry.register(BaseGenerator)  # type: ignore[type-abstract]
class SelectGenerator(BaseGenerator):
    """Generate a mapping by selecting some of the configured options.

    Args:
        options (dict[str, Any] | None): Internal structure with ``built`` and ``meta``.
            - ``built``: ``dict[str, BaseGenerator]``
            - ``meta``: ``dict[str, {"required": bool, "default": Any}]``
        pick (dict[str, Any] | None): Rule describing how many optional keys to pick,
            and optional ``weights`` mapping ``{key: float}``.
    """

    __meta__ = {
        "aliases": {"options": "options", "pick": "pick", "weights": "weights"},
        "deprecations": [],
        "rules": [],
    }
    __slots__ = ("options", "pick")
    __aliases__ = ("select",)

    def __init__(
        self,
        options: dict[str, Any] | None = None,
        pick: dict[str, Any] | None = None,
    ) -> None:
        """Initialize with optional options and pick rule."""
        self.options: dict[str, Any] = options or {"built": {}, "meta": {}}
        self.pick: dict[str, Any] = pick or {}

    # TODO(arch): depend on a builder/factory protocol instead of a concrete object
    @classmethod
    def from_spec(
        cls,
        builder: Any,
        spec: Mapping[str, object],
    ) -> "SelectGenerator":
        """Construct an instance from a generator specification.

        The spec must provide an ``options`` mapping. Each option is a mapping with
        an ``of`` child generator spec and optional ``required``/``default`` flags.

        Args:
            builder (Any): Object exposing ``build(spec: Mapping[str, object]) -> BaseGenerator``.
            spec (Mapping[str, object]): Parsed generator specification.

        Returns:
            SelectGenerator: Configured instance.

        Raises:
            MissingChildError: If ``options`` is missing/empty or a member lacks ``of``.
            InvalidParameterError: If ``pick.mode`` is invalid or required bounds are missing.
        """
        opts = spec.get("options")
        if opts is not None and not isinstance(opts, dict):
            raise InvalidParameterError("select 'options' must be a mapping")
        opts = opts or {}

        built: dict[str, BaseGenerator] = {}
        meta: dict[str, dict[str, Any]] = {}
        for key, conf in opts.items():
            if not isinstance(conf, dict) or "of" not in conf:
                raise MissingChildError("each option must have an 'of' spec")
            child_spec = conf.get("of")
            child = builder.build(child_spec)
            built[str(key)] = child
            meta[str(key)] = {
                "required": bool(conf.get("required")),
                "default": conf.get("default", None),
            }

        pick = dict(spec.get("pick") or {})  # type: ignore[call-overload]
        mode = pick.get("mode", "any")
        if mode not in ("any", "at_least_one", "exact", "range"):
            raise InvalidParameterError(
                "pick.mode must be any|at_least_one|exact|range"
            )
        if mode == "exact" and pick.get("min") is None:
            raise InvalidParameterError(
                "pick.min is required when mode=exact (exact count)"
            )
        if mode == "range" and (pick.get("min") is None or pick.get("max") is None):
            raise InvalidParameterError(
                "pick.min and pick.max are required when mode=range"
            )

        return cls(options={"built": built, "meta": meta}, pick=pick)

    def _sanity_check(self, ctx: GenContext) -> None:
        """Validate context and configuration invariants.

        Args:
            ctx (GenContext): Execution context.

        Raises:
            ContextError: If ``ctx`` is not a ``GenContext``.
            MissingChildError: If no options/built children exist.
        """
        if not isinstance(ctx, GenContext):
            raise ContextError("ctx must be an instance of GenContext")
        if not self.options or not self.options.get("built"):
            raise MissingChildError("select requires options")

    def configure(
        self,
        *,
        options: dict[str, Any] | None = None,
        pick: dict[str, Any] | None = None,
        **_: Any,
    ) -> "SelectGenerator":
        """Update configuration in place and return ``self``.

        Args:
            options (dict[str, Any] | None): Replacement internal structure.
            pick (dict[str, Any] | None): Replacement pick rule.
            **_ (Any): Ignored extra kwargs for forward-compatibility.

        Returns:
            SelectGenerator: ``self`` for chaining.
        """
        if options is not None:
            self.options = options
        if pick is not None:
            self.pick = pick
        return self

    # TODO(utils): move weighted sampling helper to a shared utils module if reused
    def _weighted_sample(
        self,
        rng: Random,
        items: Sequence[str],
        weights: Mapping[str, float],
        k: int,
    ) -> list[str]:
        """Draw ``k`` distinct items without replacement, biased by ``weights``.

        Args:
            rng (Random): Deterministic RNG.
            items (Sequence[str]): Candidate option keys.
            weights (Mapping[str, float]): Per-key non-negative weights.
            k (int): Number of items to draw.

        Returns:
            list[str]: Selected keys (size ``<= k`` if fewer candidates available).

        Raises:
            InvalidParameterError: If any weight is negative or NaN, or all weights are zero.
        """
        if not items or k <= 0:
            return []
        pool_items = list(items)
        pool_weights = [float(weights.get(key, 1.0)) for key in pool_items]
        if any(w < 0 for w in pool_weights):
            raise InvalidParameterError("weights must be non-negative")
        chosen: list[str] = []
        for _ in range(min(k, len(pool_items))):
            total = float(sum(pool_weights))
            if total <= 0:
                raise InvalidParameterError("sum(weights) must be > 0")
            r = rng.random() * total
            acc = 0.0
            pick_index = 0
            for i, w in enumerate(pool_weights):
                acc += w
                if r <= acc:
                    pick_index = i
                    break
            chosen.append(pool_items.pop(pick_index))
            pool_weights.pop(pick_index)
        return chosen

    def _decide_keys(self, rng: Random) -> list[str]:
        """Return the list of keys to materialize for this request.

        Args:
            rng (Random): Deterministic RNG from context.

        Returns:
            list[str]: Required keys plus selected optional keys.
        """
        built: dict[str, BaseGenerator] = self.options["built"]
        meta: dict[str, dict[str, Any]] = self.options["meta"]
        required = [key for key, info in meta.items() if info.get("required")]
        optional = [key for key in built.keys() if key not in required]

        pick = self.pick or {}
        mode = pick.get("mode", "any")
        weights_map: Mapping[str, float] = pick.get("weights", {}) or {}

        # If nothing optional to pick, return all required
        if not optional and mode in ("any", "at_least_one", "exact", "range"):
            return required

        if mode == "exact":
            count = int(pick.get("min"))
        elif mode == "range":
            count = rng.randint(int(pick.get("min")), int(pick.get("max")))
        elif mode == "at_least_one":
            count = rng.randint(1, len(optional))
        else:
            min_k = int(pick.get("min", 0))
            max_k = int(pick.get("max", len(optional)))
            if max_k < min_k:
                max_k = min_k
            count = (
                rng.randint(min_k, max_k)
                if (min_k or max_k != len(optional))
                else rng.randint(0, len(optional))
            )

        chosen_optional = self._weighted_sample(rng, optional, weights_map, count)
        return required + chosen_optional

    def _generate_impl(self, ctx: GenContext) -> dict[str, "JsonValue"]:
        """Produce a mapping according to the configured selection rule.

        Args:
            ctx (GenContext): Execution context providing RNG and state.

        Returns:
            dict[str, JsonValue]: Generated mapping.
        """
        self._sanity_check(ctx)
        keys = self._decide_keys(ctx.rng)
        built: dict[str, BaseGenerator] = self.options["built"]
        out: dict[str, Any] = {}
        for key in keys:
            out[key] = built[key].generate(ctx)
        return out
