from __future__ import annotations

import random
from typing import Any, Iterable, Sequence

from havocforge.chaos.ops.base import ApplyResult, BaseChaosOp
from havocforge.registry import Registry


def _randcase(s: str, rng: random.Random) -> str:
    """Return ``s`` with randomly cased alphabetic characters."""
    out: list[str] = []
    for ch in s:
        if ch.isalpha() and rng.random() < 0.5:
            out.append(ch.upper())
        else:
            out.append(ch.lower())
    return "".join(out)


@Registry.register(BaseChaosOp)
class RandomHeaderCaseOp(BaseChaosOp):
    """Mutate header *values* by changing their casing.

    Typical use: ``application/json`` -> ``AppLiCation/JsOn`` while keeping the
    header key untouched.
    """

    key = "random_header_case"

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        headers: Sequence[str] | None = None,
        mode: str = "random",
        **kw: Any,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        self.headers = tuple(h.lower() for h in (headers or ("content-type",)))
        mode_norm = (mode or "random").strip().lower()
        self.mode = mode_norm if mode_norm in {"random", "upper", "lower"} else "random"

    @staticmethod
    def _targets(names: Iterable[str]) -> set[str]:
        return {name.lower() for name in names}

    def _transform(self, value: str, rng: random.Random) -> str:
        if self.mode == "upper":
            return value.upper()
        if self.mode == "lower":
            return value.lower()
        return _randcase(value, rng)

    def apply(
        self,
        *,
        request,
        response,
        body: Any,
        rng: random.Random,
    ) -> ApplyResult:
        mutated: list[str] = []
        try:
            for header_name in self._targets(self.headers):
                current = response.headers.get(header_name)
                if not isinstance(current, str):
                    continue
                new_value = self._transform(current, rng)
                if new_value == current:
                    continue
                response.headers[header_name] = new_value
                mutated.append(header_name)
        except Exception:
            mutated.clear()

        descriptions = [f"random_header_case({','.join(mutated)})"] if mutated else []
        return ApplyResult(body=body, descriptions=descriptions)
