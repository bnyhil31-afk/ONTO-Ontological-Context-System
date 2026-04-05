"""
api/federation/circuit_breaker.py

Per-peer circuit breaker for the ONTO federation layer.

Protects the local node from cascading failures caused by misbehaving,
overloaded, or unreachable federation peers. Follows the classic three-state
model described in Fowler's "Release It!" (Michael T. Nygard):

  CLOSED  — normal operation; failures are counted
  OPEN    — peer is suspended; all calls fail immediately
  HALF_OPEN — one probe is allowed after the recovery window;
              success → CLOSED, failure → OPEN

Configuration (via api/federation/config.py, loaded from env vars):
  ONTO_FED_CB_FAILURE_THRESHOLD  — consecutive failures before OPEN (default 5)
  ONTO_FED_CB_RECOVERY_SECONDS   — seconds in OPEN before half-open probe (default 60)

Usage:
    from api.federation.circuit_breaker import PeerCircuitBreaker, CircuitOpen

    cb = PeerCircuitBreaker(peer_did="did:key:z6Mk...")

    try:
        cb.before_call()          # raises CircuitOpen if circuit is open
        result = send_to_peer()
        cb.on_success()
    except CircuitOpen:
        # skip this peer silently or log
        pass
    except Exception as exc:
        cb.on_failure(exc)
        raise


    # Registry: one breaker per peer DID
    from api.federation.circuit_breaker import circuit_breaker_registry
    cb = circuit_breaker_registry.get("did:key:z6Mk...")

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import threading
import time
from typing import Dict, Optional


class CircuitOpen(Exception):
    """Raised by PeerCircuitBreaker.before_call() when the circuit is OPEN."""
    def __init__(self, peer_did: str, retry_after: float):
        self.peer_did = peer_did
        self.retry_after = retry_after
        super().__init__(
            f"Circuit open for peer {peer_did!r}. "
            f"Retry after {retry_after:.1f}s."
        )


class PeerCircuitBreaker:
    """
    Three-state circuit breaker for a single federation peer.

    States:
      CLOSED    — normal; failures are counted toward the threshold
      OPEN      — calls blocked; re-tried after recovery_seconds
      HALF_OPEN — one probe allowed; success → CLOSED, failure → OPEN

    Thread-safe: all state transitions are protected by a single lock.
    """

    _STATE_CLOSED = "closed"
    _STATE_OPEN = "open"
    _STATE_HALF_OPEN = "half_open"

    def __init__(
        self,
        peer_did: str,
        failure_threshold: Optional[int] = None,
        recovery_seconds: Optional[int] = None,
    ) -> None:
        self.peer_did = peer_did
        self._lock = threading.Lock()
        self._state = self._STATE_CLOSED
        self._consecutive_failures = 0
        self._opened_at: Optional[float] = None
        self._probe_in_flight = False

        # Config loaded lazily so unit tests can override before construction
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds

    def _threshold(self) -> int:
        if self._failure_threshold is not None:
            return self._failure_threshold
        from api.federation import config as _cfg
        return _cfg.CIRCUIT_BREAKER_FAILURE_THRESHOLD

    def _recovery(self) -> int:
        if self._recovery_seconds is not None:
            return self._recovery_seconds
        from api.federation import config as _cfg
        return _cfg.CIRCUIT_BREAKER_RECOVERY_SECONDS

    @property
    def state(self) -> str:
        """Current state: 'closed', 'open', or 'half_open'."""
        with self._lock:
            return self._state

    @property
    def consecutive_failures(self) -> int:
        with self._lock:
            return self._consecutive_failures

    def before_call(self) -> None:
        """
        Called before attempting to contact the peer.

        Raises:
            CircuitOpen: if the circuit is OPEN and the recovery window
                         has not elapsed yet.
        """
        with self._lock:
            if self._state == self._STATE_CLOSED:
                return  # normal path — allow

            if self._state == self._STATE_OPEN:
                elapsed = time.monotonic() - (self._opened_at or 0.0)
                remaining = self._recovery() - elapsed
                if remaining > 0:
                    raise CircuitOpen(self.peer_did, remaining)
                # Recovery window elapsed — transition to half-open
                self._state = self._STATE_HALF_OPEN
                self._probe_in_flight = True
                return

            if self._state == self._STATE_HALF_OPEN:
                if self._probe_in_flight:
                    # Only one probe at a time
                    raise CircuitOpen(self.peer_did, 0.0)
                self._probe_in_flight = True

    def on_success(self) -> None:
        """
        Called when a peer call succeeds.
        Resets failure count and closes the circuit.
        """
        with self._lock:
            self._consecutive_failures = 0
            self._state = self._STATE_CLOSED
            self._opened_at = None
            self._probe_in_flight = False

    def on_failure(self, exc: Optional[Exception] = None) -> None:
        """
        Called when a peer call fails.
        Increments the failure counter and opens the circuit if the
        threshold is reached.
        """
        with self._lock:
            self._consecutive_failures += 1
            self._probe_in_flight = False
            if (
                self._state != self._STATE_OPEN
                and self._consecutive_failures >= self._threshold()
            ):
                self._state = self._STATE_OPEN
                self._opened_at = time.monotonic()

    def reset(self) -> None:
        """
        Manually reset to CLOSED state. Useful for operator intervention
        or test teardown.
        """
        with self._lock:
            self._state = self._STATE_CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    def status(self) -> dict:
        """Return a summary dict safe for logging and status responses."""
        with self._lock:
            return {
                "peer_did": self.peer_did,
                "state": self._state,
                "consecutive_failures": self._consecutive_failures,
                "opened_at": self._opened_at,
            }


class CircuitBreakerRegistry:
    """
    Registry of per-peer circuit breakers.
    Thread-safe: get() creates a breaker on first access.
    """

    def __init__(self) -> None:
        self._breakers: Dict[str, PeerCircuitBreaker] = {}
        self._lock = threading.Lock()

    def get(self, peer_did: str) -> PeerCircuitBreaker:
        """Return the circuit breaker for peer_did, creating it if needed."""
        with self._lock:
            if peer_did not in self._breakers:
                self._breakers[peer_did] = PeerCircuitBreaker(peer_did)
            return self._breakers[peer_did]

    def status_all(self) -> list:
        """Return status dicts for all registered breakers."""
        with self._lock:
            return [cb.status() for cb in self._breakers.values()]

    def reset_all(self) -> None:
        """Reset all breakers. Used in tests."""
        with self._lock:
            for cb in self._breakers.values():
                cb.reset()


# Shared registry — one circuit breaker per peer DID
circuit_breaker_registry = CircuitBreakerRegistry()
