"""
api/federation/network_resilience.py

Per-peer network quality tracking and resilient request execution.

Handles the realities of real-world networks:
  - Jitter: variance in round-trip time between packets
  - Lag: elevated baseline RTT (distance, congestion, load)
  - Packet loss: requests that never complete
  - Intermittent failures: transient network hiccups

Architecture: this module sits between InternetAdapter._post() and the
actual network call. It wraps every outbound request with:

  1. Circuit breaker check (from circuit_breaker.py — peer already known bad?)
  2. Adaptive timeout (base + 2× jitter buffer, capped at MAX_TIMEOUT)
  3. The actual network call
  4. RTT measurement and quality metric update
  5. On failure: jitter-aware exponential backoff before retry
  6. Circuit breaker update (on_success / on_failure)

Retry policy — full jitter (AWS recommended approach):
  delay = random(0, min(MAX_DELAY, BASE_DELAY * 2^attempt))
  This prevents thundering herd: when a peer recovers, many nodes
  don't all retry at the same instant.

See: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/

Configuration (env vars, all optional — safe defaults apply):
  ONTO_FED_RETRY_MAX_ATTEMPTS   — max retries per request (default: 3)
  ONTO_FED_RETRY_BASE_DELAY_MS  — base backoff delay in ms (default: 500)
  ONTO_FED_RETRY_MAX_DELAY_MS   — cap on retry delay in ms (default: 10000)
  ONTO_FED_TIMEOUT_BASE_SECS    — baseline request timeout (default: 10)
  ONTO_FED_TIMEOUT_MAX_SECS     — ceiling on adaptive timeout (default: 30)
  ONTO_FED_QUALITY_MIN_SCORE    — score below which peer is deprioritized
                                   in discovery (0.0–1.0, default: 0.10)
  ONTO_FED_RTT_WINDOW           — rolling window size for RTT samples
                                   (default: 20)

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import random
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# CONNECTION METRICS — per-peer rolling quality tracking
# ---------------------------------------------------------------------------

class ConnectionMetrics:
    """
    Rolling-window connection quality metrics for a single peer.

    Tracks three independent quality dimensions:
      - RTT (round-trip time): how long requests take when they succeed
      - Jitter: variance in RTT between consecutive successful requests
      - Packet loss rate: fraction of attempts that fail completely

    All three feed into quality_score() — a single 0.0–1.0 signal that
    the discovery layer uses to deprioritize degraded peers.

    Thread-safe: all mutations are protected by a single lock.
    """

    def __init__(self, window: int = 20) -> None:
        self._lock = threading.Lock()
        self._window = window
        self._rtt_samples: deque = deque(maxlen=window)   # milliseconds
        self._jitter_samples: deque = deque(maxlen=window) # |rtt[n] - rtt[n-1]|
        self._last_rtt: Optional[float] = None
        self._attempts: int = 0
        self._failures: int = 0

    def record_success(self, rtt_ms: float) -> None:
        """
        Record a successful request with measured RTT.
        Computes jitter as |current_rtt - previous_rtt|.
        """
        with self._lock:
            self._attempts += 1
            self._rtt_samples.append(rtt_ms)
            if self._last_rtt is not None:
                jitter = abs(rtt_ms - self._last_rtt)
                self._jitter_samples.append(jitter)
            self._last_rtt = rtt_ms

    def record_failure(self) -> None:
        """Record a failed request (timeout, connection error, etc.)."""
        with self._lock:
            self._attempts += 1
            self._failures += 1

    def rtt_avg_ms(self) -> float:
        """Rolling average RTT in milliseconds. Returns 0.0 if no data."""
        with self._lock:
            if not self._rtt_samples:
                return 0.0
            return sum(self._rtt_samples) / len(self._rtt_samples)

    def jitter_avg_ms(self) -> float:
        """
        Rolling average jitter in milliseconds.
        Jitter is the mean absolute deviation between consecutive RTT samples.
        Returns 0.0 if fewer than two samples (cannot compute jitter yet).
        """
        with self._lock:
            if not self._jitter_samples:
                return 0.0
            return sum(self._jitter_samples) / len(self._jitter_samples)

    def packet_loss_rate(self) -> float:
        """Fraction of requests that failed. Returns 0.0 if no attempts."""
        with self._lock:
            if self._attempts == 0:
                return 0.0
            return self._failures / self._attempts

    def adaptive_timeout(self, base_secs: float, max_secs: float = 30.0) -> float:
        """
        Compute an adaptive request timeout that accounts for current jitter.

        Formula (RFC 6298 inspired, simplified for application-level use):
          timeout = base + 4 × jitter_avg

        The 4× multiplier gives significant headroom for jitter spikes without
        being so permissive that genuinely dead peers tie up threads. The result
        is clamped to [base_secs, max_secs].

        With no data (new peer), returns base_secs (safe default).
        """
        jitter = self.jitter_avg_ms() / 1000.0  # convert to seconds
        timeout = base_secs + (4.0 * jitter)
        return min(max(timeout, base_secs), max_secs)

    def quality_score(self) -> float:
        """
        Composite connection quality score: 0.0 (unusable) to 1.0 (perfect).

        Weighted contributions:
          - Packet loss (50%): most important — a lossy link is unreliable
          - Jitter (30%): high jitter means unpredictable latency
          - RTT (20%): high RTT degrades throughput but not correctness

        Thresholds (calibrated for federation use):
          - RTT: 0ms–500ms → 1.0–0.0 (anything over 500ms scores 0)
          - Jitter: 0ms–200ms → 1.0–0.0
          - Loss rate: 0%–50% → 1.0–0.0 (anything over 50% scores 0)

        Returns 1.0 if no data (benefit of the doubt for new peers).
        """
        with self._lock:
            if self._attempts == 0:
                return 1.0  # new peer — no data means assume healthy

            rtt = sum(self._rtt_samples) / len(self._rtt_samples) if self._rtt_samples else 0.0
            jitter = sum(self._jitter_samples) / len(self._jitter_samples) if self._jitter_samples else 0.0
            loss = self._failures / self._attempts

        rtt_score    = max(0.0, 1.0 - rtt / 500.0)
        jitter_score = max(0.0, 1.0 - jitter / 200.0)
        loss_score   = max(0.0, 1.0 - loss / 0.5)

        return (
            0.20 * rtt_score
            + 0.30 * jitter_score
            + 0.50 * loss_score
        )

    def sample_count(self) -> int:
        """Number of RTT samples recorded."""
        with self._lock:
            return len(self._rtt_samples)

    def status(self) -> dict:
        """Return a summary dict safe for audit logging and health endpoints."""
        return {
            "rtt_avg_ms":       round(self.rtt_avg_ms(), 2),
            "jitter_avg_ms":    round(self.jitter_avg_ms(), 2),
            "packet_loss_rate": round(self.packet_loss_rate(), 4),
            "quality_score":    round(self.quality_score(), 3),
            "attempts":         self._attempts,
            "failures":         self._failures,
            "sample_count":     self.sample_count(),
        }


# ---------------------------------------------------------------------------
# RETRY POLICY — full jitter exponential backoff
# ---------------------------------------------------------------------------

class RetryPolicy:
    """
    Jitter-aware exponential backoff for retrying failed peer requests.

    Uses "full jitter" strategy (AWS recommended):
      delay = random(0, min(MAX_DELAY_MS, BASE_DELAY_MS × 2^attempt)) / 1000

    Full jitter spreads retries randomly across the backoff window.
    This prevents thundering herd: when a peer recovers from an outage,
    all retrying nodes don't hammer it simultaneously.

    "Capped" (no jitter) and "decorrelated" are alternatives, but full
    jitter gives the best outcome for distributed systems under load.
    """

    def __init__(
        self,
        max_attempts: int,
        base_delay_ms: int,
        max_delay_ms: int,
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay_ms = base_delay_ms
        self.max_delay_ms = max_delay_ms

    @classmethod
    def from_config(cls) -> "RetryPolicy":
        """Load retry policy from federation config."""
        from api.federation import config as _cfg
        return cls(
            max_attempts=_cfg.RETRY_MAX_ATTEMPTS,
            base_delay_ms=_cfg.RETRY_BASE_DELAY_MS,
            max_delay_ms=_cfg.RETRY_MAX_DELAY_MS,
        )

    def delay_for_attempt(self, attempt: int) -> float:
        """
        Compute the delay (in seconds) before retry attempt `attempt`.

        attempt=1 is the first retry (after the initial failure).
        Returns 0.0 for attempt=0 (immediate first try).

        Full jitter formula:
          cap = min(MAX_DELAY_MS, BASE_DELAY_MS × 2^(attempt-1))
          delay = random(0, cap) / 1000
        """
        if attempt <= 0:
            return 0.0
        cap_ms = min(
            self.max_delay_ms,
            self.base_delay_ms * (2 ** (attempt - 1)),
        )
        return random.uniform(0, cap_ms) / 1000.0

    def should_retry(self, attempt: int) -> bool:
        """Return True if another retry attempt is permitted."""
        return attempt < self.max_attempts


# ---------------------------------------------------------------------------
# RESILIENCE MANAGER — per-peer metrics registry
# ---------------------------------------------------------------------------

class NetworkResilienceManager:
    """
    Singleton registry of per-peer connection quality metrics.

    Usage:
        resilience = network_resilience_manager   # module singleton

        # Record outcome of a peer request
        resilience.record_success("did:key:z6Mk...", rtt_ms=45.3)
        resilience.record_failure("did:key:z6Mk...")

        # Get adaptive timeout
        timeout = resilience.adaptive_timeout("did:key:z6Mk...", base_secs=10)

        # Check quality for discovery filtering
        score = resilience.quality_score("did:key:z6Mk...")

    Thread-safe: the registry lock protects metric creation; each
    ConnectionMetrics has its own lock for updates.
    """

    def __init__(self) -> None:
        self._metrics: Dict[str, ConnectionMetrics] = {}
        self._lock = threading.Lock()

    def _get_or_create(self, peer_did: str) -> ConnectionMetrics:
        with self._lock:
            if peer_did not in self._metrics:
                from api.federation import config as _cfg
                self._metrics[peer_did] = ConnectionMetrics(
                    window=_cfg.RTT_WINDOW
                )
            return self._metrics[peer_did]

    def record_success(self, peer_did: str, rtt_ms: float) -> None:
        """Record a successful request and its RTT."""
        self._get_or_create(peer_did).record_success(rtt_ms)

    def record_failure(self, peer_did: str) -> None:
        """Record a failed request (timeout, connection error, etc.)."""
        self._get_or_create(peer_did).record_failure()

    def adaptive_timeout(self, peer_did: str, base_secs: float) -> float:
        """Return an adaptive timeout for peer, accounting for jitter."""
        from api.federation import config as _cfg
        return self._get_or_create(peer_did).adaptive_timeout(
            base_secs=base_secs,
            max_secs=_cfg.TIMEOUT_MAX_SECS,
        )

    def quality_score(self, peer_did: str) -> float:
        """Return the composite quality score for peer (0.0–1.0)."""
        with self._lock:
            if peer_did not in self._metrics:
                return 1.0  # unknown peer — assume healthy
        return self._metrics[peer_did].quality_score()

    def is_quality_acceptable(self, peer_did: str) -> bool:
        """
        Return False if the peer's quality score is below the minimum
        threshold configured in ONTO_FED_QUALITY_MIN_SCORE.
        Peers below this threshold are deprioritized in discovery results
        but NOT blocked — the circuit breaker handles actual blocking.
        """
        from api.federation import config as _cfg
        return self.quality_score(peer_did) >= _cfg.QUALITY_MIN_SCORE

    def retry_delay(self, peer_did: str, attempt: int) -> float:
        """Return the jitter-based delay (seconds) for the given retry attempt."""
        return RetryPolicy.from_config().delay_for_attempt(attempt)

    def health_for_peer(self, peer_did: str) -> dict:
        """Return metrics dict for a specific peer. Safe to log."""
        with self._lock:
            if peer_did not in self._metrics:
                return {"peer_did": peer_did, "status": "no_data"}
        return {
            "peer_did": peer_did,
            **self._metrics[peer_did].status(),
        }

    def health_all(self) -> dict:
        """Return metrics for all tracked peers. Safe to include in onto_status."""
        with self._lock:
            peer_dids = list(self._metrics.keys())
        return {
            did: self._metrics[did].status()
            for did in peer_dids
        }


# ---------------------------------------------------------------------------
# MODULE-LEVEL SINGLETON
# ---------------------------------------------------------------------------

#: Global resilience manager — one per process.
#: InternetAdapter._post() and P2PAdapter DHT operations use this.
network_resilience_manager = NetworkResilienceManager()


# ---------------------------------------------------------------------------
# RESILIENT CALL WRAPPER
# ---------------------------------------------------------------------------

def resilient_call(
    peer_did: str,
    fn: Callable,
    *args: Any,
    base_timeout: float = 10.0,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
    **kwargs: Any,
) -> Any:
    """
    Execute fn(*args, **kwargs) with adaptive retry, jitter backoff,
    adaptive timeouts, and circuit breaker integration.

    Used by InternetAdapter._post() for all outbound HTTP(S) requests.
    Can be used for any peer-facing call that may encounter network issues.

    Parameters:
        peer_did:     DID of the peer being contacted (for metrics + circuit breaker)
        fn:           The function to call (e.g., urllib.request.urlopen)
        *args:        Positional arguments for fn
        base_timeout: Baseline timeout in seconds (will be adapted for jitter)
        on_retry:     Optional callback called on each retry with (attempt, exc)
        **kwargs:     Keyword arguments for fn (timeout will be injected)

    Returns:
        Return value of fn on success.

    Raises:
        CircuitOpen:  If the circuit breaker is open for this peer.
        Exception:    The last exception if all retry attempts are exhausted.

    Retry behavior:
        - Attempt 1: immediate
        - Attempt 2+: full-jitter exponential backoff
        - CircuitOpen is never retried — the operator must review
        - Adaptive timeout increases with measured jitter (RTT + 4×jitter)
    """
    from api.federation.circuit_breaker import circuit_breaker_registry, CircuitOpen
    from api.federation import config as _cfg

    cb = circuit_breaker_registry.get(peer_did)
    policy = RetryPolicy.from_config()
    last_exc: Optional[Exception] = None

    for attempt in range(1, policy.max_attempts + 1):
        # Circuit breaker check — raises CircuitOpen if peer is suspended
        try:
            cb.before_call()
        except CircuitOpen:
            raise  # never retry — circuit is open

        # Compute adaptive timeout for this peer's current network conditions
        timeout = network_resilience_manager.adaptive_timeout(
            peer_did, base_timeout
        )

        # Inject timeout into kwargs if the function accepts it
        call_kwargs = dict(kwargs)
        if "timeout" in _fn_accepts_timeout(fn):
            call_kwargs["timeout"] = timeout

        t_start = time.monotonic()
        try:
            result = fn(*args, **call_kwargs)
            rtt_ms = (time.monotonic() - t_start) * 1000.0
            network_resilience_manager.record_success(peer_did, rtt_ms)
            cb.on_success()
            return result

        except Exception as exc:
            rtt_ms = (time.monotonic() - t_start) * 1000.0
            network_resilience_manager.record_failure(peer_did)
            cb.on_failure(exc)
            last_exc = exc

            if on_retry is not None:
                try:
                    on_retry(attempt, exc)
                except Exception:
                    pass

            if policy.should_retry(attempt):
                delay = policy.delay_for_attempt(attempt)
                if delay > 0:
                    time.sleep(delay)
            else:
                break  # exhausted

    raise last_exc  # type: ignore[misc]


def _fn_accepts_timeout(fn: Callable) -> set:
    """
    Return the set of parameter names for fn.
    Used to detect whether to inject `timeout` into the call kwargs.
    Pure introspection — never raises.
    """
    try:
        import inspect
        return set(inspect.signature(fn).parameters.keys())
    except Exception:
        return set()
