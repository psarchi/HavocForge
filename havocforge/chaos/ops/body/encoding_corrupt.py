from __future__ import annotations

import random
from typing import Any

from havocforge.chaos.ops.base import BaseChaosOp, ApplyResult
from havocforge.chaos.ops.utils import iter_leaf_refs, iter_dict_entries
from havocforge.registry import Registry


def _json_headers() -> dict[str, str]:
    """Force JSON without charset for this op's responses."""
    return {"Content-Type": "application/json"}


def _viz(s: str, limit: int = 30) -> str:
    mapping = {
        "​": "<ZWSP>",
        "‍": "<ZWJ>",
        "‎": "<LRM>",
        "‏": "<RLM>",
        "⁦": "<LRI>",
        "⁧": "<RLI>",
        "⁨": "<FSI>",
        "⁩": "<PDI>",
        " ": "<NBSP>",
        " ": "<NNBSP>",
        " ": "<THIN>",
        " ": "<HAIR>",
    }
    out = []
    for ch in s:
        out.append(mapping.get(ch, ch))
        if len("".join(out)) >= limit:
            out.append("…")
            break
    return "".join(out)


def _corrupt_text(s: str, rng: random.Random) -> tuple[str, str]:
    """Return (corrupted_text, strategy_name) for *s* using a random strategy.

    Strategies include visible-but-valid Unicode and subtle confusables.
    """
    if not s:
        return s, "noop"

    def pick(n: int) -> int:
        return int(rng.random() * n)

    # Pools
    ZERO_WIDTHS = ["​", "‍", "‎", "‏"]  # ZWSP, ZWJ, LRM, RLM
    CONFUSABLES = [
        # quotes / dashes / punctuation
        "‘",
        "’",
        "“",
        "”",
        "–",
        "—",
        "·",
        "・",
        # spaces that look similar
        " ",  # NBSP
        " ",  # NARROW NO-BREAK SPACE
        " ",  # THIN SPACE
        " ",  # HAIR SPACE
        # bidi isolates (can confuse rendering but valid)
        "⁦",
        "⁧",
        "⁨",
        "⁩",
    ]
    FULLWIDTH_DIGITS = [chr(c) for c in range(0xFF10, 0xFF1A)]  # U+FF10..U+FF19

    strat = rng.choice(
        [
            "replacement",  # U+FFFD
            "delete",  # drop one char
            "swap",  # swap adjacent
            "zero_width",  # inject zero-width or LRM/RLM
            "homoglyph",  # similar-looking unicode
            "fullwidth",  # ASCII -> fullwidth
            "append_ff",  # append fullwidth digit
            "insert_conf",  # insert confusable char (curly quotes, spaces, bidi)
            "accent",  # add combining mark
        ]
    )

    if strat == "replacement":
        i = pick(len(s))
        return s[:i] + "�" + s[i + 1 :], "replacement"

    if strat == "delete" and len(s) > 1:
        i = pick(len(s))
        return s[:i] + s[i + 1 :], "delete"

    if strat == "swap" and len(s) > 1:
        i = pick(len(s) - 1)
        return s[:i] + s[i + 1] + s[i] + s[i + 2 :], "swap"

    if strat == "zero_width":
        zw = rng.choice(ZERO_WIDTHS)
        i = pick(len(s) + 1)
        return s[:i] + zw + s[i:], "zero_width"

    if strat == "homoglyph":
        table = {
            "a": "а",
            "e": "е",
            "o": "ο",
            "p": "р",
            "c": "с",
            "x": "х",
            "y": "у",
            "A": "Α",
            "B": "Β",
            "C": "С",
            "E": "Ε",
            "H": "Η",
            "I": "Ι",
            "K": "Κ",
            "M": "Μ",
            "N": "Ν",
            "O": "Ο",
            "P": "Ρ",
            "S": "Ѕ",
            "T": "Τ",
            "X": "Χ",
            "Y": "Υ",
            "Z": "Ζ",
        }
        idxs = [i for i, ch in enumerate(s) if ch in table]
        if idxs:
            i = rng.choice(idxs)
            return s[:i] + table[s[i]] + s[i + 1 :], "homoglyph"
        # fallback to replacement
        i = pick(len(s))
        return s[:i] + "�" + s[i + 1 :], "replacement"

    if strat == "fullwidth":

        def to_fullwidth(ch: str) -> str:
            o = ord(ch)
            if "0" <= ch <= "9":
                return chr(0xFF10 + (o - ord("0")))
            if "A" <= ch <= "Z":
                return chr(0xFF21 + (o - ord("A")))
            if "a" <= ch <= "z":
                return chr(0xFF41 + (o - ord("a")))
            return ch

        idxs = [i for i, ch in enumerate(s) if ch.isascii() and ch.isalnum()]
        if idxs:
            i = rng.choice(idxs)
            return s[:i] + to_fullwidth(s[i]) + s[i + 1 :], "fullwidth"
        # fallback to zero-width injection
        zw = rng.choice(ZERO_WIDTHS)
        i = pick(len(s) + 1)
        return s[:i] + zw + s[i:], "zero_width"

    if strat == "append_ff":
        return s + rng.choice(FULLWIDTH_DIGITS), "append_ff"

    if strat == "insert_conf":
        ch = rng.choice(CONFUSABLES)
        i = pick(len(s) + 1)
        return s[:i] + ch + s[i:], "insert_conf"

    i = pick(len(s))
    return s[:i] + rng.choice(["́", "̀", "̂", "̈"]) + s[i:], "accent"


@Registry.register(BaseChaosOp)
class EncodingCorruptOp(BaseChaosOp):
    """Corrupt up to N string fields using mixed strategies.

    Always returns headers without a charset: {"Content-Type": "application/json"}.
    """

    key = "encoding_corrupt"

    def __init__(
        self,
        *,
        enabled: bool,
        p: float = 0.0,
        weight: float = 1.0,
        fields_to_corrupt: int = 1,
        **kw,
    ) -> None:
        super().__init__(enabled=enabled, p=p, weight=weight, **kw)
        self.fields_to_corrupt = int(max(1, int(fields_to_corrupt or 1)))

    def apply(self, *, request, response, body: Any, rng: random.Random) -> ApplyResult:
        if not isinstance(body, dict):
            return ApplyResult(body=body, descriptions=[], headers=_json_headers())
        items = body.get("items")
        if not isinstance(items, list) or not items:
            return ApplyResult(body=body, descriptions=[], headers=_json_headers())

        changed = 0
        desc: list[str] = []

        order = list(range(len(items)))
        rng.shuffle(order)

        for idx in order:
            if changed >= self.fields_to_corrupt:
                break
            rec = items[idx]
            if not isinstance(rec, dict):
                continue

            value_refs = list(
                iter_leaf_refs(rec, predicate=lambda v: isinstance(v, str))
            )
            key_refs = [
                ref for ref in iter_dict_entries(rec) if isinstance(ref.key, str)
            ]
            cands = [("value", ref) for ref in value_refs] + [
                ("key", ref) for ref in key_refs
            ]
            if not cands:
                continue

            kind, ref = rng.choice(cands)
            parent, key, path = ref.parent, ref.key, ref.path
            value = ref.value

            if kind == "value":
                # corrupt a string value at arbitrary depth
                original = value
                new_val, strat = _corrupt_text(original, rng)
                # ensure some observable change; retry a few times
                retries = 0
                while new_val == original and retries < 3:
                    new_val, strat = _corrupt_text(original, rng)
                    retries += 1
                try:
                    if parent is None or key is None:
                        continue
                    parent[key] = new_val
                    changed += 1
                    dot = ("." + path) if path else ""
                    prev_old = _viz(original)
                    prev_new = _viz(new_val)
                    desc.append(
                        f"encoding_corrupt(items[{idx}]{dot} value:'{prev_old}'->'{prev_new}' strat={strat})"
                    )
                except Exception:
                    # skip on mutation error
                    pass
                continue

            if not isinstance(parent, dict) or not isinstance(key, str):
                continue
            old_k: str = key
            # derive a new key via corruption; ensure it differs
            new_k, kstrat = _corrupt_text(old_k, rng)
            retries = 0
            while new_k == old_k and retries < 3:
                new_k, kstrat = _corrupt_text(old_k, rng)
                retries += 1
            if new_k == old_k:
                continue  # give up if no change

            # avoid collisions by nudging with a zero-width space if needed
            if new_k in parent and new_k != old_k:
                new_k = new_k + "​"  # make unique
            try:
                parent[new_k] = parent.pop(old_k)
                changed += 1
                dot_parent = ("." + path.rsplit(".", 1)[0]) if "." in path else ""
                desc.append(
                    f"encoding_corrupt(items[{idx}]{dot_parent} key:'{old_k}'->'{new_k}' strat={kstrat})"
                )
            except Exception:
                # if we fail to rename, skip
                pass

        return ApplyResult(
            body=body, descriptions=desc if changed else [], headers=_json_headers()
        )
