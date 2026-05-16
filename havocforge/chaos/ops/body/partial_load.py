from __future__ import annotations
import random
from typing import Any
from havocforge.chaos.ops.base import BaseChaosOp, ApplyResult
from havocforge.chaos.ops.utils import iter_dict_entries
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class PartialLoadOp(BaseChaosOp):
    """Partial load chaos operation.

    - Randomly drops keys from dicts under `body["items"]` (including nested
      dicts inside each item) to mimic *partially loaded/trimmed* records.
    - Does **not** change transport (no byte truncation; still JSON-serializable).

    Tuning (bounds; conservative defaults):
      - `min_items` / `max_items`: bounds for how many items are affected (default 1..3)
      - `min_keys_per_item` / `max_keys_per_item`: bounds for keys removed per affected item (default 1..3)
      - `max_keys_per_item`: cap how many keys are removed per affected item (default 3)
    """

    key = "partial_load"

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        min_items: int = 1,
        max_items: int = 3,
        min_keys_per_item: int = 1,
        max_keys_per_item: int = 3,
        **kw,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        mi = int(min_items or 1)
        ma = int(max_items or 1)
        if ma < mi:
            mi, ma = ma, mi
        self.min_items = max(1, mi)
        self.max_items = max(self.min_items, ma)
        mki = int(min_keys_per_item or 1)
        mka = int(max_keys_per_item or 1)
        if mka < mki:
            mki, mka = mka, mki
        self.min_keys_per_item = max(1, mki)
        self.max_keys_per_item = max(self.min_keys_per_item, mka)

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        descriptions: list[str] = []

        if not isinstance(body, dict):
            return ApplyResult(body=body, descriptions=[])

        items = body.get("items") if isinstance(body, dict) else None
        if isinstance(items, list) and items:
            n = len(items)
            upper_items = min(n, self.max_items)
            lower_items = min(self.min_items, upper_items)
            k_items = rng.randint(
                lower_items, upper_items
            )  # RNG how many items to affect
            item_indices = rng.sample(range(n), k_items)

            for idx in sorted(item_indices):
                obj = items[idx]
                if not isinstance(obj, (dict, list)):
                    continue
                candidates = [
                    (ref.parent, ref.key, ref.path)
                    for ref in iter_dict_entries(obj, skip_keys={"__meta"})
                ]
                if not candidates:
                    continue

                m = len(candidates)
                upper_keys = min(m, self.max_keys_per_item)
                lower_keys = min(self.min_keys_per_item, upper_keys)
                k_drop = rng.randint(lower_keys, upper_keys)
                picks = rng.sample(range(m), k_drop)
                for j in sorted(
                    picks, reverse=True
                ):  # reverse indices not required but stable
                    parent, key, path = candidates[j]
                    try:
                        parent.pop(key, None)
                        descriptions.append(
                            f"partial_load(items[{idx}].{path} drop:{key})"
                        )
                    except Exception:
                        # ignore failures
                        pass

        return ApplyResult(body=body, descriptions=descriptions)
