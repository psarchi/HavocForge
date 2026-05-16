from __future__ import annotations
import random
from typing import Any
from copy import deepcopy
from havocforge.chaos.ops.base import BaseChaosOp, ApplyResult
from havocforge.chaos.ops.utils import iter_lists
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class DuplicateItemsOp(BaseChaosOp):
    """Duplicate *any* list in the body (recursive auto-detect).

    Recursively walks ``body`` and duplicates elements inside **every** list it
    finds (not just keys named ``items``). Lists may appear:
      * as values of dict keys (e.g., ``{"events": [...]}``),
      * nested inside other lists (e.g., ``[ [..], [..] ]``),
      * deeply nested combinations of dicts/lists.

    For lists that are values of a dict key, if that dict also has a numeric
    ``count`` field, it will be updated to match the new list length.

    Control root behavior with ``include_root``: when ``False`` (default),
    lists attached directly under the top-level body (e.g., ``body["items"]``,
    ``body["events"]``) are skipped; only nested lists are duplicated.

    Args:
        enabled (bool): Toggle controlled by the chaos manager.
        p (float): Trigger probability in [0, 1]; handled by the base class.
        weight (float): Relative selection weight among enabled ops.
        max_dups (int): Max number of *additional* elements to insert per list.
        strategy (str): Either ``"adjacent"`` or ``"random"``.
        include_root (bool): Duplicate lists directly under the root dict.

    Returns:
        ApplyResult: Modified body and descriptions like
        ``["duplicate_items(events:2)", "duplicate_items(items[3].metrics:1)"]``.
    """

    key = "duplicate_items"

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        max_dups: int = 1,
        strategy: str = "adjacent",
        include_root: bool = False,
        **kw,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        self.max_dups = int(max(1, int(max_dups or 1)))
        s = (strategy or "adjacent").strip().lower()
        self.strategy = s if s in {"adjacent", "random"} else "adjacent"
        self.include_root = bool(include_root)

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        if not isinstance(body, dict):
            return ApplyResult(body=body, descriptions=[])

        descriptions: list[str] = []
        for path, items, owner, _ in iter_lists(
            body, include_root=self.include_root, root_label="<root>"
        ):
            # root
            if not self.include_root:
                if path == "<root>":
                    continue
                if path and ("." not in path and "[" not in path):
                    continue
            if not items:
                continue

            to_insert = min(self.max_dups, len(items))
            if to_insert <= 0:
                continue

            for _ in range(to_insert):
                idx = int(rng.random() * len(items))
                dup = deepcopy(items[idx])
                if self.strategy == "adjacent":
                    items.insert(idx + 1, dup)
                else:  # random
                    insert_at = int(rng.random() * (len(items) + 1))
                    items.insert(insert_at, dup)

            # Update sibling count if owner is dict and has 'count'
            if isinstance(owner, dict) and "count" in owner:
                try:
                    owner["count"] = len(items)
                except Exception:
                    pass

            descriptions.append(f"duplicate_items({path}:{to_insert})")

        output = ApplyResult(body=body, descriptions=descriptions)
        return output
