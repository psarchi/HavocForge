from __future__ import annotations

import datetime
import time
from typing import Any, List, Tuple


def sleep_ms(ms: int) -> None:
    """Sleep for the requested milliseconds (integer)."""
    if ms and ms > 0:
        time.sleep(ms / 1000.0)


def bernoulli(rng, p: float) -> bool:
    """Return True with probability p (0..1). Assumes p already normalized by config layer."""
    if p <= 0.0:
        return False
    if p >= 1.0:
        return True
    return rng.random() < p


def weighted_pick_one(rng, items: List[Tuple[Any, float]]):
    """
    Pick one item from a list of (item, weight) using rng.random().
    Returns the selected item, or None if list is empty or all weights <= 0.
    """
    if not items:
        return None
    total = sum(max(0.0, w) for _, w in items)
    if total <= 0.0:
        return None
    r = rng.random() * total
    upto = 0.0
    for item, w in items:
        w = max(0.0, w)
        upto += w
        if r <= upto:
            return item
    return items[-1][0]


def parse_timestamp(val: Any) -> Tuple[datetime.datetime | None, str | None]:
    """Parse a value into a datetime object and format type.

    Args:
        val: Value to parse (int, float, or string).

    Returns:
        Tuple of (datetime object, format type) where format type is:
        - "iso": ISO8601 string format
        - "epoch": Unix timestamp in seconds
        - "epoch_micro": Unix timestamp in microseconds
        - None: Could not parse
    """
    try:
        return datetime.datetime.fromisoformat(str(val).replace("Z", "+00:00")), "iso"
    except Exception:
        pass

    try:
        return datetime.datetime.utcfromtimestamp(float(val)), "epoch"
    except Exception:
        pass

    try:
        return datetime.datetime.utcfromtimestamp(float(val) / 1_000_000), "epoch_micro"
    except Exception:
        pass

    return None, None
