"""Rate limiter for Telegram commands."""

from __future__ import annotations

import time
from collections import defaultdict

from ..core.interfaces import IRateLimiter


class RateLimiter(IRateLimiter):
    """Simple in-memory rate limiter using sliding window."""

    def __init__(self, default_max: int = 10, window_sec: int = 60) -> None:
        self.default_max = default_max
        self.window_sec = window_sec
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, max_requests: int | None = None) -> bool:
        now = time.monotonic()
        window = now - self.window_sec
        bucket = self._buckets[key]
        # Prune old entries
        self._buckets[key] = [t for t in bucket if t > window]
        bucket = self._buckets[key]
        limit = max_requests if max_requests is not None else self.default_max
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def remaining(self, key: str, max_requests: int | None = None) -> int:
        now = time.monotonic()
        window = now - self.window_sec
        bucket = [t for t in self._buckets[key] if t > window]
        limit = max_requests if max_requests is not None else self.default_max
        return max(0, limit - len(bucket))
