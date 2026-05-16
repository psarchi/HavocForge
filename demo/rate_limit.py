"""Simple in-memory token-bucket rate limiter for the demo.

Per-IP, sliding window. No Redis dependency — keys live in process memory
and expire after the window. Single-process / single-replica only; for a
real deployment you'd swap this for Redis-backed limits.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class IpRateLimiter:
    """Per-IP sliding-window counter. Returns False when the bucket is empty."""

    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._hits[ip]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True

    def remaining(self, ip: str) -> int:
        with self._lock:
            return max(0, self.max_requests - len(self._hits.get(ip, ())))
