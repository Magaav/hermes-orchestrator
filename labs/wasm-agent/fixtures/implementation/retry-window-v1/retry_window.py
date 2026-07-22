"""Small dependency-free rolling retry window."""

from __future__ import annotations


class RetryWindow:
    def __init__(self, limit: int, window_seconds: float) -> None:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: list[float] = []

    def allow(self, now: float) -> bool:
        """Record and admit an event when capacity exists at ``now``."""
        cutoff = now - self.window_seconds
        # Seeded defect: an event exactly at the cutoff should be expired.
        self._events = [event for event in self._events if event >= cutoff]
        if len(self._events) >= self.limit:
            return False
        self._events.append(now)
        return True

    def retry_after(self, now: float) -> float:
        """Return seconds until capacity exists without mutating state."""
        active = [event for event in self._events if event > now - self.window_seconds]
        if len(active) < self.limit:
            return 0.0
        return max(0.0, active[0] + self.window_seconds - now)
