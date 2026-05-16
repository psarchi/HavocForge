from __future__ import annotations

from random import Random
from typing import Any, Iterable, Optional, Sequence, Tuple, TypeVar

from havocforge.contracts import MaybeGeneratorSpec
from havocforge.chaos.drift.errors import DriftSelectionError

T = TypeVar("T")


def rng_choice(rng: Random, items: Iterable[T]) -> T:
    seq = list(items)
    if not seq:
        raise DriftSelectionError("rng_choice called with empty iterable")
    choice_fn = getattr(rng, "choice", None)
    if choice_fn is None:
        import random

        choice_fn = random.choice
    return choice_fn(seq)


def rng_shuffle(rng: Random, items: list[T]) -> None:
    shuffle_fn = getattr(rng, "shuffle", None)
    if shuffle_fn is None:
        import random

        random.shuffle(items)
    else:
        shuffle_fn(items)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def adjust_binary_weights(weights: Sequence[float], delta: float) -> Sequence[float]:
    """Adjust two-element weight vector by delta and renormalize."""
    if len(weights) != 2:
        return weights
    first, second = weights
    first = clamp(first + delta, 0.0, 1.0)
    second = clamp(1.0 - first, 0.0, 1.0)
    total = first + second
    if total == 0:
        return (0.5, 0.5)
    return (first / total, second / total)


def ensure_nullable_wrapper(
    spec: Any,
    rng: Random,
    nullable_cfg: Any,
) -> Tuple[Optional["MaybeGeneratorSpec"], Optional[str]]:
    """Return a Maybe wrapper + summary when nullable configuration is provided."""
    from havocforge.contracts.maybe import (
        MaybeGeneratorSpec,
    )  # local import to avoid cycles

    if nullable_cfg is None or nullable_cfg is False:
        return None, None

    if isinstance(spec, MaybeGeneratorSpec):
        return None, None

    base = 0.0
    delta_span = 0.1
    range_cfg = None

    if isinstance(nullable_cfg, dict):
        base = float(nullable_cfg.get("p_null", nullable_cfg.get("base", base)))
        if "delta" in nullable_cfg:
            delta_span = float(nullable_cfg["delta"])
        if "range" in nullable_cfg:
            range_cfg = nullable_cfg["range"]
    elif isinstance(nullable_cfg, (list, tuple)) and len(nullable_cfg) == 2:
        range_cfg = nullable_cfg
    elif isinstance(nullable_cfg, (int, float)):
        base = float(nullable_cfg)
    elif nullable_cfg is True:
        pass
    else:
        range_cfg = None

    if isinstance(range_cfg, (list, tuple)) and len(range_cfg) == 2:
        low = clamp(float(range_cfg[0]), 0.0, 1.0)
        high = clamp(float(range_cfg[1]), 0.0, 1.0)
        if high < low:
            low, high = high, low
        p_null = rng.uniform(low, high)
    else:
        p_null = clamp(base + rng.uniform(-delta_span, delta_span), 0.0, 1.0)

    replacement = MaybeGeneratorSpec(child=spec, p_null=p_null)
    return replacement, f"nullable(p_null={p_null})"
