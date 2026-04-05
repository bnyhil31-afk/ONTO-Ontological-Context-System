"""
core/ratelimit.py

Rate limiting for ONTO intake.
Prevents runaway automation, protects system resources,
and prepares the interface for multi-user deployment.

Plain English: This module counts how many inputs have arrived
in the last minute. If too many arrive too fast, it says so
clearly and refuses to process more until the window clears.

Two limiters are provided:

  SlidingWindowRateLimiter — per-client sliding window limiter.
    Used by rate_limiter (the existing singleton). Tracks requests
    from a single caller identified by the calling context.

  GlobalRateLimiter — cross-client aggregate limiter.
    Used by global_rate_limiter (new singleton). Enforces a ceiling
    across ALL callers combined, regardless of identity.
    Controlled by ONTO_GLOBAL_RATE_LIMIT_PER_MINUTE (default 0 = disabled).

Both are sliding window limiters — limits are enforced smoothly,
not in burst-at-the-clock-minute style.

Usage:
    from core.ratelimit import rate_limiter, global_rate_limiter
    allowed, reason = rate_limiter.check_and_record()
    if not allowed:
        # handle rejection gracefully
"""

import threading
import time
from collections import deque
from typing import Tuple


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter.
    Tracks timestamps of recent inputs and enforces a maximum
    count within a configurable rolling time window.

    Thread-safe: a threading.Lock protects the _timestamps deque so that
    check_and_record() is atomic across concurrent FastAPI workers.
    """

    def __init__(self) -> None:
        # Load config lazily to avoid circular imports at module load
        self._timestamps: deque = deque()
        self._config = None
        self._lock = threading.Lock()

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

        with self._lock:
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
        with self._lock:
            self._timestamps.append(time.monotonic())

    def check_and_record(self) -> Tuple[bool, str]:
        """
        Atomically check and record in one call.
        The lock is held across both operations so concurrent callers
        cannot both pass check() before either records.

        Returns:
            (True, "") if allowed and recorded.
            (False, reason) if rate limited — nothing recorded.
        """
        if self.limit == 0:
            return True, ""

        with self._lock:
            now = time.monotonic()
            cutoff = now - self.window

            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

            if len(self._timestamps) >= self.limit:
                oldest = self._timestamps[0]
                wait_seconds = int(self.window - (now - oldest)) + 1
                reason = (
                    f"Rate limit reached: {self.limit} inputs per "
                    f"{self.window} seconds. "
                    f"Please wait approximately {wait_seconds} second(s) "
                    f"before trying again."
                )
                return False, reason

            self._timestamps.append(now)
            return True, ""

    def current_count(self) -> int:
        """
        Number of inputs recorded in the current window.
        Useful for diagnostics and testing.
        """
        with self._lock:
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
        with self._lock:
            self._timestamps.clear()


# Per-client limiter — the original singleton
rate_limiter = SlidingWindowRateLimiter()


# ─────────────────────────────────────────────────────────────────────────────
# GLOBAL (CROSS-CLIENT) RATE LIMITER
# Structurally identical to SlidingWindowRateLimiter but uses a single shared
# deque with no per-client partitioning. Enforces an aggregate ceiling across
# all callers. Disabled by default (ONTO_GLOBAL_RATE_LIMIT_PER_MINUTE=0).
# ─────────────────────────────────────────────────────────────────────────────

class GlobalRateLimiter:
    """
    Cross-client aggregate sliding window rate limiter.

    Tracks the total number of requests from ALL callers within the
    configured window and rejects requests when the aggregate ceiling is
    reached. This limits total system load, independent of any single
    client's per-minute quota.

    Disabled when ONTO_GLOBAL_RATE_LIMIT_PER_MINUTE is 0 (the default).

    Thread-safe: the same lock-and-deque pattern as SlidingWindowRateLimiter.
    """

    def __init__(self) -> None:
        self._timestamps: deque = deque()
        self._config = None
        self._lock = threading.Lock()

    def _get_config(self):
        if self._config is None:
            from core.config import config
            self._config = config
        return self._config

    @property
    def limit(self) -> int:
        """Global ceiling; 0 = disabled."""
        return self._get_config().GLOBAL_RATE_LIMIT_PER_MINUTE

    @property
    def window(self) -> int:
        """Time window in seconds (shares ONTO_RATE_LIMIT_WINDOW_SECONDS)."""
        return self._get_config().RATE_LIMIT_WINDOW_SECONDS

    def check_and_record(self) -> Tuple[bool, str]:
        """
        Atomically check and record. Returns (True, "") if allowed,
        (False, reason) if the global ceiling is reached.
        When disabled (limit == 0), always returns (True, "").
        """
        if self.limit == 0:
            return True, ""

        with self._lock:
            now = time.monotonic()
            cutoff = now - self.window

            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()

            if len(self._timestamps) >= self.limit:
                oldest = self._timestamps[0]
                wait_seconds = int(self.window - (now - oldest)) + 1
                reason = (
                    f"Global rate limit reached: {self.limit} total requests "
                    f"per {self.window} seconds across all clients. "
                    f"Please wait approximately {wait_seconds} second(s)."
                )
                return False, reason

            self._timestamps.append(now)
            return True, ""

    def current_count(self) -> int:
        """Number of requests recorded in the current global window."""
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.window
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            return len(self._timestamps)

    def reset(self) -> None:
        """Clear all recorded timestamps. Use in tests."""
        with self._lock:
            self._timestamps.clear()


# Global limiter singleton — disabled by default (limit=0)
global_rate_limiter = GlobalRateLimiter()
