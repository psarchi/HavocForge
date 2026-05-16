from __future__ import annotations
import random
from typing import Any, List
from havocforge.chaos.ops.base import BaseChaosOp, ApplyResult
from havocforge.chaos.ops.utils import iter_lists
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class ListShuffleOp(BaseChaosOp):
    """Order shuffle chaos operation.

    Randomizes the order of **every list** found anywhere in the response body
    (top-level, inside `items`, nested dicts, lists-of-lists, etc.) using
    Fisher–Yates with the provided RNG.

    Args:
        enabled (bool): Toggle.
        p (float): Probability [0,1].
        weight (float): Relative selection weight.

    Returns:
        ApplyResult: Same body with lists reordered; one description entry per
        list shuffled, e.g. `list_shuffle(items[0].events)`. If nothing was
        shuffled (no lists or lists of length < 2), descriptions=[].
    """

    key = "list_shuffle"

    @staticmethod
    def _shuffle_in_place(lst: list, rng: random.Random) -> None:
        # Fisher–Yates (Durstenfeld) using supplied rng
        for i in range(len(lst) - 1, 0, -1):
            j = int(rng.random() * (i + 1))
            lst[i], lst[j] = lst[j], lst[i]

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        shuffled: List[str] = []

        for path, lst, _, _ in iter_lists(body, include_root=True, root_label="[root]"):
            if isinstance(lst, list) and len(lst) > 1:
                self._shuffle_in_place(lst, rng)
                shuffled.append(f"list_shuffle({path})")

        return ApplyResult(body=body, descriptions=shuffled)
