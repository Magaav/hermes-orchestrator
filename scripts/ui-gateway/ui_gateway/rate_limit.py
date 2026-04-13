from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
import time


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_sec: float


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str, *, limit: int, window_sec: float) -> RateLimitResult:
        now = time.monotonic()
        with self._lock:
            bucket = self._events.setdefault(key, deque())
            cutoff = now - window_sec
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(0.0, window_sec - (now - bucket[0])) if bucket else window_sec
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    retry_after_sec=retry_after,
                )

            bucket.append(now)
            remaining = max(0, limit - len(bucket))
            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                retry_after_sec=0.0,
            )
