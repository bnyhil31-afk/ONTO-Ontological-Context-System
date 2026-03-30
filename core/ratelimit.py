"""
core/ratelimit.py

Rate limiting for ONTO intake.
Prevents runaway automation, protects system resources,
and prepares the interface for multi-user deployment.

Plain English: This module counts how many inputs have arrived
in the last minute. If too many arrive too fast, it says so
clearly and refuses to process more until the window clears.

This is a sliding window rate limiter — it counts inputs
within a rolling time window, not fixed clock minutes.
That means limits are enforced smoothly, not in bursts.

Usage:
    from core.ratelimit import rate_limiter
    allowed, reason = rate_limiter.check()
    if not allowed:
        # handle rejection gracefully
"""

import time
from collections import deque
from typing import Tuple


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter.
    Tracks timestamps of recent inputs and enforces a maximum
    count within a configurable rolling time window.

    Thread-safe for single-threaded use (ONTO's current model).
    For multi-threaded deployments, add a threading.Lock.
    """

    def __init__(self) -> None:
        # Load config lazily to avoid circular imports at module load
        self._timestamps: deque = deque()
        self._config = None

    def _get_config(self):
        """Lazy load config to avoid circular imports."""
        if self._config is None:
            from core.config import config
            self._config = config
        return self._config

    @property
    def limit(self) -> int:
        """Maximum inputs allowed within the window."""
        return self._get_config().RATE_LIMIT_PER_MINUTE

    @property
    def window(self) -> int:
        """Time window in seconds."""
        return self._get_config().RATE_LIMIT_WINDOW_SECONDS

    def check(self) -> Tuple[bool, str]:
        """
        Check whether a new input is allowed right now.

        Returns:
            (True, "") if the input is allowed.
            (False, reason) if the rate limit has been exceeded.

        Plain English: Returns a yes or no, and if no, says why.
        Does NOT record the input — call record() after check() passes.
        """
        if self.limit == 0:
            return True, ""

        now = time.monotonic()
        cutoff = now - self.window

        # Remove timestamps outside the window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

        if len(self._timestamps) >= self.limit:
            # Calculate when the next input will be allowed
            oldest = self._timestamps[0]
            wait_seconds = int(self.window - (now - oldest)) + 1
            reason = (
                f"Rate limit reached: {self.limit} inputs per "
                f"{self.window} seconds. "
                f"Please wait approximately {wait_seconds} second(s) "
                f"before trying again."
            )
            return False, reason

        return True, ""

    def record(self) -> None:
        """
        Record that an input was accepted right now.
        Call this after check() returns True and the input
        has been accepted for processing.
        """
        self._timestamps.append(time.monotonic())

    def check_and_record(self) -> Tuple[bool, str]:
        """
        Convenience method: check and record in one call.
        Use when you want to accept the input immediately
        if the check passes.

        Returns:
            (True, "") if allowed and recorded.
            (False, reason) if rate limited — nothing recorded.
        """
        allowed, reason = self.check()
        if allowed:
            self.record()
        return allowed, reason

    def current_count(self) -> int:
        """
        Number of inputs recorded in the current window.
        Useful for diagnostics and testing.
        """
        now = time.monotonic()
        cutoff = now - self.window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        return len(self._timestamps)

    def reset(self) -> None:
        """
        Clear all recorded timestamps.
        Use in tests and for operator-level resets.
        Does NOT change the limit or window settings.
        """
        self._timestamps.clear()


# Single shared instance — import this everywhere
rate_limiter = SlidingWindowRateLimiter()
