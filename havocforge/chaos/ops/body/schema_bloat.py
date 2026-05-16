from __future__ import annotations
import random
from typing import Any
from havocforge.chaos.ops.base import BaseChaosOp, ApplyResult
from havocforge.chaos.ops.utils import iter_leaf_refs
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class SchemaBloatOp(BaseChaosOp):
    """Schema/response bloat chaos operation.

    Inflates payload size **in place** by enlarging **one randomly selected string field**
    anywhere under the body (top-level, items, nested dicts/lists). Two strategies:
      - "insert": insert random characters into strings (default)
      - "repeat": repeat existing string content (e.g., "city") until target size

    The op keeps JSON valid and avoids touching non-strings.

    Args:
        enabled (bool): Toggle.
        p (float): Probability [0,1].
        weight (float): Relative weight.
        extra_kb (int): ~Additional bytes to add (best effort) **to one field**.
        strategy (str): "insert" | "repeat" (default "insert").

    Returns:
        ApplyResult: mutated body; description like
            ["schema_bloat(path=<path>,+<bytes> bytes,strat=<strategy>)"].
    """

    key = "schema_bloat"

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        extra_kb: int = 32,
        strategy: str = "insert",
        **kw,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        self.extra_kb = max(0, int(extra_kb or 0))
        s = (strategy or "insert").strip().lower()
        self.strategy = s if s in {"insert", "repeat"} else "insert"

    _BYTE_TO_ASCII = bytes(range(256)).translate(bytes((i % 95) + 32 for i in range(256)))

    @staticmethod
    def _rand_chars(rng: random.Random, n: int) -> str:
        random_bytes = rng.randbytes(n)
        return random_bytes.translate(SchemaBloatOp._BYTE_TO_ASCII).decode('latin-1')

    def _inflate_repeat(self, s: str, need: int, rng: random.Random) -> tuple[str, int]:
        if not s:
            ins = self._rand_chars(rng, need)
            return ins, len(ins)
        token = s
        parts = s.split()
        if parts:
            token = parts[-1]
        # ensure token non-empty
        if not token:
            token = s
        need = max(8, need)
        reps = max(
            1, min(need // max(1, len(token)), 64)
        )  # cap reps to avoid huge loops
        addition = (token + " ") * reps
        out = s + addition
        added = len(addition)
        if added > need:
            out = s + addition[:need]
            added = need
        return out, added

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        if not isinstance(body, (dict, list)):
            return ApplyResult(body=body, descriptions=[])

        # Early termination 10
        MAX_CANDIDATES = 10
        candidates = []
        for ref in iter_leaf_refs(body, predicate=lambda v: isinstance(v, str)):
            candidates.append(ref)
            if len(candidates) >= MAX_CANDIDATES:
                break

        if not candidates:
            return ApplyResult(body=body, descriptions=[])

        node_ref = rng.choice(candidates)
        parent, key, path = node_ref.parent, node_ref.key, node_ref.path

        extra_bytes = self.extra_kb * 1024
        if extra_bytes <= 0:
            return ApplyResult(body=body, descriptions=[])

        if parent is None or key is None:
            return ApplyResult(body=body, descriptions=[])

        cur = parent[key]
        if not isinstance(cur, str):
            return ApplyResult(body=body, descriptions=[])

        if self.strategy == "insert":
            ins = self._rand_chars(rng, extra_bytes)
            pos = int(rng.random() * (len(cur) + 1))
            new_val = cur[:pos] + ins + cur[pos:]
            bytes_added = len(ins)
        else:  # "repeat"
            new_val, bytes_added = self._inflate_repeat(cur, extra_bytes, rng)

        parent[key] = new_val

        return ApplyResult(
            body=body,
            descriptions=[
                f"schema_bloat(path={path},+{bytes_added} bytes,strat={self.strategy})"
            ],
        )
