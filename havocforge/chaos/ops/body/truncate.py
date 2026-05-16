from __future__ import annotations
import random
import json
from typing import Any
from havocforge.chaos.ops.base import BaseChaosOp, ApplyResult
from havocforge.chaos.ops.utils import iter_nodes
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class TruncateOp(BaseChaosOp):
    # This op is terminal: stop running further ops after it
    terminal = True
    key = "truncate"
    """Payload truncate chaos operation (string-level corruption).

Corrupts JSON *as text* rather than removing elements:
  - If ``body['items']`` exists and is a list, replaces selected items with
    **truncated JSON text** (string slices of their JSON serialization).
    The list length stays the same and remains JSON-serializable.
  - Otherwise, serializes the entire body to JSON text and returns a
    **truncated** string as the body.

Notes:
  - ``ApplyResult.body`` may be ``dict`` (with strings inside) or ``str``.
  - This op corrupts content; it does not drop items.
"""

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        min_items: int = 1,
        max_items: int = 3,
        **kw,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        # kept for cfg compatibility, but unused in string-truncate mode
        self.min_items = int(min_items or 1)
        # cap the number of corrupted nodes per apply()
        self.max_items = max(1, int(max_items or 1))

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        """Corrupt JSON as text.

        - If top-level body['items'] exists and is a list: choose K indices
          (K = RNG[1..n]) and for each, try to corrupt a **random nested
          node** in that item (dict/list/primitive). If no suitable nested node
          exists, truncate the whole item as text.
        - Otherwise: truncate the whole body as text.
        """

        def _to_bytes(x: Any) -> bytes:
            try:
                s = json.dumps(x, separators=(",", ":"), ensure_ascii=False)
            except Exception:
                s = str(x)
            return s.encode("utf-8")

        # Helper: random cut (1..len-1), decode to text
        def _trunc_text(b: bytes) -> tuple[str, int, int]:
            cut = 1 if len(b) <= 1 else rng.randint(1, len(b) - 1)
            return b[:cut].decode("utf-8", errors="ignore"), cut, len(b)

        if isinstance(body, dict) and isinstance(body.get("items"), list):
            items = body["items"]
            n = len(items)
            if n > 0:
                candidates: list[tuple[int, Any, Any, str, Any]] = []
                for idx, obj in enumerate(items):
                    for ref in iter_nodes(obj):
                        candidates.append(
                            (idx, ref.parent, ref.key, ref.path, ref.value)
                        )

                m = len(candidates)
                if m > 0:
                    k = rng.randint(1, min(m, self.max_items))
                    picked = rng.sample(range(m), k)

                    roots = [j for j in picked if candidates[j][1] is None]
                    if roots:
                        desc_roots: list[str] = []
                        for j in sorted(roots):
                            item_idx, parent, key, path, node = candidates[j]
                            frag, cut, total = _trunc_text(_to_bytes(node))
                            items[item_idx] = frag
                            desc_roots.append(f"truncate(items[{item_idx}]:{cut}/{total})")
                        return ApplyResult(body=body, descriptions=desc_roots)

                    desc: list[str] = []
                    for j in sorted(picked):
                        item_idx, parent, key, path, node = candidates[j]
                        frag, cut, total = _trunc_text(_to_bytes(node))
                        try:
                            if parent is None:
                                items[item_idx] = frag
                                path = ""
                            elif isinstance(parent, dict):
                                parent[key] = frag
                            elif isinstance(parent, list) and isinstance(key, int):
                                parent[key] = frag
                            else:
                                # unexpected shape -> replace whole item
                                items[item_idx] = frag
                                path = ""
                        except Exception:
                            items[item_idx] = frag
                            path = ""

                        dot = ("." + path) if path else ""
                        desc.append(f"truncate(items[{item_idx}]{dot}:{cut}/{total})")

                    return ApplyResult(body=body, descriptions=desc)

        b = _to_bytes(body)
        frag, cut, total = _trunc_text(b)
        return ApplyResult(
            body=frag, descriptions=[f"truncate(body_text:{cut}/{total})"]
        )
