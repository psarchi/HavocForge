"""Burst traffic chaos operation for simulating traffic spikes."""

from __future__ import annotations

import random
import time
from typing import Any

from havocforge.chaos.ops.base import BaseChaosOp
from havocforge.registry import Registry


@Registry.register(BaseChaosOp)
class BurstOp(BaseChaosOp):
    """Simulates traffic burst by signaling rate limiter override.

    This chaos op doesn't modify data but returns metadata that tells
    the rate limiter to temporarily increase throughput, simulating
    a traffic burst scenario.
    """

    key = "burst"
    type_token = "burst"

    def __init__(
        self,
        enabled: bool,
        probability: float = 0.01,  # 1% chance of burst
        burst_rate: int = 10_000,  # Target rate during burst (events/sec)
        burst_duration: int = 10,  # Burst duration in seconds
        require_cache_items: int | None = None,  # Minimum cache items required
    ):
        """Initialize burst chaos op.

        Args:
            enabled: Whether this op is enabled
            probability: Probability of burst activation
            burst_rate: Target events per second during burst
            burst_duration: How long the burst lasts (seconds)
            require_cache_items: Minimum items in cache to allow burst (optional)
        """
        super().__init__(enabled=enabled, probability=probability)
        self.burst_rate = burst_rate
        self.burst_duration = burst_duration
        self.require_cache_items = require_cache_items

        # Track burst state
        self.burst_active = False
        self.burst_start: float | None = None

    def should_burst(self) -> bool:
        """Check if burst should activate or continue."""
        # If burst already active, check if it should continue
        if self.burst_active and self.burst_start:
            elapsed = time.time() - self.burst_start
            if elapsed >= self.burst_duration:
                # Burst expired
                self.burst_active = False
                self.burst_start = None
                return False
            return True

        # Try to activate new burst
        if random.random() < self.probability:  # type: ignore[attr-defined]
            self.burst_active = True
            self.burst_start = time.time()
            return True

        return False

    def apply(
        self, body: dict[str, Any], **kwargs
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Apply burst chaos by returning metadata for rate limiter.

        Args:
            body: Request body (unchanged)
            **kwargs: Additional context

        Returns:
            Tuple of (unchanged body, burst metadata)
        """
        # Check if op is enabled first
        if not self.enabled:
            return body, {}

        if not self.should_burst():
            return body, {}

        # Calculate required cache items for burst
        required_items = self.require_cache_items
        if required_items is None:
            # Auto-calculate: rate * duration
            required_items = self.burst_rate * self.burst_duration

        metadata = {
            "burst_active": True,
            "burst_rate": self.burst_rate,
            "burst_duration": self.burst_duration,
            "required_cache_items": required_items,
            "burst_started_at": self.burst_start,
        }

        return body, metadata
