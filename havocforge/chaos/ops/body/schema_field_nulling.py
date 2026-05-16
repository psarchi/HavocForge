from __future__ import annotations

import random
from typing import Any, Iterable, List, Sequence, Tuple

from havocforge.chaos.ops.base import ApplyResult, BaseChaosOp
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class SchemaFieldNullingOp(BaseChaosOp):
    """Null out a single schema field inside the response body.

    Behaviour:
        - Picks one candidate value under ``body["items"]`` (or the body itself
          when ``items`` is missing) and sets it to ``None``.
        - Candidates can be restricted via ``fields`` using dotted paths such as
          ``"device.browser"`` or ``"event_params[].value.int_value"``.

    Args:
        enabled (bool): Toggle.
        p (float): Probability [0,1].
        weight (float): Relative weight.
        fields (list[str] | None): Optional path expressions to limit targets.

    Returns:
        ApplyResult: Mutated body with a ``schema_field_nulling(...)`` description
        when a field was changed.
    """

    key = "schema_field_nulling"

    _MISSING = object()

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        fields: List[str] | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        self.fields = [
            f.strip() for f in (fields or []) if isinstance(f, str) and f.strip()
        ]

    # -------------------- helpers -------------------- #

    def _iter_configured_targets(self, record: Any) -> Iterable[Tuple[Any, Any, str]]:
        for expr in self.fields:
            tokens = [tok for tok in expr.split(".") if tok]
            if not tokens:
                continue
            yield from self._walk_tokens(record, tokens, path="")

    def _walk_tokens(
        self,
        node: Any,
        tokens: Sequence[str],
        *,
        parent: Any = None,
        key: Any = None,
        path: str,
    ) -> Iterable[Tuple[Any, Any, str]]:
        if not tokens:
            if parent is not None:
                yield parent, key, path
            return

        token = tokens[0]
        rest = tokens[1:]
        is_list = token.endswith("[]")
        name = token[:-2] if is_list else token

        if isinstance(node, dict):
            if name not in node:
                return
            child = node[name]
            next_path = f"{path}.{name}" if path else name
            if is_list:
                if not isinstance(child, list):
                    return
                if not rest:
                    for idx in range(len(child)):
                        yield child, idx, f"{next_path}[{idx}]"
                else:
                    for idx, elem in enumerate(child):
                        sub_path = f"{next_path}[{idx}]"
                        yield from self._walk_tokens(
                            elem, rest, parent=child, key=idx, path=sub_path
                        )
            else:
                if not rest:
                    yield node, name, next_path
                else:
                    yield from self._walk_tokens(
                        child, rest, parent=node, key=name, path=next_path
                    )
        elif isinstance(node, list) and is_list and name.isdigit():
            idx = int(name)
            if 0 <= idx < len(node):
                elem = node[idx]
                next_path = f"{path}[{idx}]" if path else f"[{idx}]"
                if rest:
                    yield from self._walk_tokens(
                        elem, rest, parent=node, key=idx, path=next_path
                    )
                else:
                    yield node, idx, next_path

    def _iter_leaf_targets(self, record: Any) -> Iterable[Tuple[Any, Any, str]]:
        stack: List[Tuple[Any, str]] = [(record, "")]
        while stack:
            node, path = stack.pop()
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "__meta":
                        continue
                    next_path = f"{path}.{k}" if path else k
                    if isinstance(v, (dict, list)):
                        stack.append((v, next_path))
                    else:
                        yield node, k, next_path
            elif isinstance(node, list):
                for idx, v in enumerate(node):
                    next_path = f"{path}[{idx}]" if path else f"[{idx}]"
                    if isinstance(v, (dict, list)):
                        stack.append((v, next_path))
                    else:
                        yield node, idx, next_path

    def _get_value(self, parent: Any, key: Any) -> Any:
        try:
            if isinstance(parent, dict):
                return parent[key]
            if isinstance(parent, list) and isinstance(key, int):
                if 0 <= key < len(parent):
                    return parent[key]
        except Exception:
            return self._MISSING
        return self._MISSING

    def _set_value(self, parent: Any, key: Any, value: Any) -> None:
        if isinstance(parent, dict):
            parent[key] = value
        elif (
            isinstance(parent, list) and isinstance(key, int) and 0 <= key < len(parent)
        ):
            parent[key] = value

    def apply(
        self,
        *,
        request,
        response,
        body: Any,
        rng: random.Random,
    ) -> ApplyResult:
        if not isinstance(body, dict):
            return ApplyResult(body=body, descriptions=[])

        items = body.get("items")
        records: List[Tuple[int | None, Any, str]] = []
        if isinstance(items, list) and items:
            for idx, rec in enumerate(items):
                if isinstance(rec, dict):
                    records.append((idx, rec, f"items[{idx}]"))
        else:
            records.append((None, body, ""))  # fallback to the root payload

        candidates: List[Tuple[int | None, Any, Any, str, str]] = []
        for idx, record, base_path in records:
            targets = (
                self._iter_configured_targets(record)
                if self.fields
                else self._iter_leaf_targets(record)
            )
            for parent, key, rel_path in targets:
                if parent is None:
                    continue
                value = self._get_value(parent, key)
                if value is self._MISSING:
                    continue
                if value is None:
                    continue
                candidates.append((idx, parent, key, rel_path, base_path))

        if not candidates:
            return ApplyResult(body=body, descriptions=[])

        rng.shuffle(candidates)
        idx, parent, key, rel_path, base_path = candidates[0]
        self._set_value(parent, key, None)

        full_path = rel_path
        if base_path:
            full_path = f"{base_path}.{rel_path}" if rel_path else base_path

        desc = f"schema_field_nulling({full_path})"
        return ApplyResult(body=body, descriptions=[desc])
