"""
tests/test_network_resilience.py

Network resilience test suite.

Tests adaptive timeout calculation, jitter measurement, packet loss rate,
quality scoring, exponential backoff retry policy, and integration of the
resilient_call() wrapper with the circuit breaker.

No network connections are made — all tests use controlled inputs and
mock functions.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import sys
import os
import time
import threading
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# TestConnectionMetrics
# ---------------------------------------------------------------------------

class TestConnectionMetrics(unittest.TestCase):
    """Tests for per-peer rolling connection quality metrics."""

    def _metrics(self, window=20):
        from api.federation.network_resilience import ConnectionMetrics
        return ConnectionMetrics(window=window)

    def test_new_metrics_all_zero(self):
        """Fresh metrics return 0.0 for all averages."""
        m = self._metrics()
        self.assertEqual(m.rtt_avg_ms(), 0.0)
        self.assertEqual(m.jitter_avg_ms(), 0.0)
        self.assertEqual(m.packet_loss_rate(), 0.0)

    def test_new_metrics_quality_score_is_1(self):
        """New peer (no data) gets benefit-of-the-doubt score of 1.0."""
        m = self._metrics()
        self.assertEqual(m.quality_score(), 1.0)

    def test_rtt_average_accumulates(self):
        """RTT average is the mean of all recorded samples."""
        m = self._metrics()
        m.record_success(100.0)
        m.record_success(200.0)
        m.record_success(300.0)
        self.assertAlmostEqual(m.rtt_avg_ms(), 200.0)

    def test_jitter_computed_from_consecutive_rtts(self):
        """Jitter is |rtt[n] - rtt[n-1]|, averaged over the window."""
        m = self._metrics()
        m.record_success(100.0)  # no jitter yet (first sample)
        m.record_success(150.0)  # jitter = |150-100| = 50
        m.record_success(100.0)  # jitter = |100-150| = 50
        self.assertAlmostEqual(m.jitter_avg_ms(), 50.0)

    def test_jitter_zero_for_single_sample(self):
        """Jitter requires at least two samples."""
        m = self._metrics()
        m.record_success(100.0)
        self.assertEqual(m.jitter_avg_ms(), 0.0)

    def test_packet_loss_rate(self):
        """Loss rate = failures / total attempts."""
        m = self._metrics()
        m.record_success(50.0)
        m.record_success(50.0)
        m.record_failure()
        # 1 failure out of 3 attempts
        self.assertAlmostEqual(m.packet_loss_rate(), 1.0 / 3.0)

    def test_packet_loss_rate_zero_on_all_success(self):
        """Zero failures means zero packet loss rate."""
        m = self._metrics()
        for _ in range(10):
            m.record_success(30.0)
        self.assertEqual(m.packet_loss_rate(), 0.0)

    def test_rolling_window_discards_old_samples(self):
        """Window limits the number of RTT samples kept."""
        m = self._metrics(window=3)
        m.record_success(100.0)
        m.record_success(100.0)
        m.record_success(100.0)
        m.record_success(900.0)  # replaces oldest — window is full
        # Average of last 3: 100, 100, 900 = 366.67
        avg = m.rtt_avg_ms()
        self.assertGreater(avg, 300.0, "Window should have dropped first 100ms sample")

    def test_adaptive_timeout_with_no_data(self):
        """Adaptive timeout returns base_secs when no samples exist."""
        m = self._metrics()
        self.assertEqual(m.adaptive_timeout(base_secs=10.0), 10.0)

    def test_adaptive_timeout_increases_with_jitter(self):
        """High jitter increases the adaptive timeout."""
        m = self._metrics()
        m.record_success(100.0)
        m.record_success(500.0)  # jitter = 400ms
        m.record_success(100.0)  # jitter = 400ms
        # jitter_avg = 400ms = 0.4s; timeout = 10 + 4×0.4 = 11.6s
        timeout = m.adaptive_timeout(base_secs=10.0)
        self.assertGreater(timeout, 10.0)
        self.assertLessEqual(timeout, 30.0)

    def test_adaptive_timeout_capped_at_max(self):
        """Adaptive timeout never exceeds max_secs."""
        m = self._metrics()
        # Simulate extreme jitter (10 seconds between samples)
        for _ in range(5):
            m.record_success(0.0)
            m.record_success(10000.0)  # 10 second RTT spike
        timeout = m.adaptive_timeout(base_secs=5.0, max_secs=15.0)
        self.assertLessEqual(timeout, 15.0)

    def test_adaptive_timeout_never_below_base(self):
        """Adaptive timeout is always >= base_secs."""
        m = self._metrics()
        m.record_success(1.0)   # 1ms RTT
        m.record_success(1.5)   # near-zero jitter
        timeout = m.adaptive_timeout(base_secs=10.0)
        self.assertGreaterEqual(timeout, 10.0)

    def test_quality_score_decreases_with_packet_loss(self):
        """High packet loss reduces quality score significantly.

        With 100% packet loss and no RTT/jitter data:
          rtt_score=1.0 (20%), jitter_score=1.0 (30%), loss_score=0.0 (50%)
          → score = 0.50. So 100% loss caps quality at exactly 0.50.
        """
        m = self._metrics()
        for _ in range(5):
            m.record_failure()  # 100% loss
        score = m.quality_score()
        self.assertLessEqual(score, 0.5, "100% packet loss should cap quality at 0.5")

    def test_quality_score_decreases_with_high_rtt(self):
        """Very high RTT reduces quality score.

        With RTT=1000ms (beyond the 500ms threshold) and no loss or jitter:
          rtt_score=0.0 (20%), jitter_score=1.0 (30%), loss_score=1.0 (50%)
          → score = 0.80. RTT contributes 20% so this is the expected floor.
        """
        m = self._metrics()
        for _ in range(5):
            m.record_success(1000.0)  # 1 second RTT — beyond threshold
        score = m.quality_score()
        self.assertLess(score, 1.0, "High RTT must reduce quality below perfect")
        self.assertAlmostEqual(score, 0.80, delta=0.01,
                               msg="High RTT with no loss/jitter should give ~0.80")

    def test_quality_score_stays_high_for_good_peer(self):
        """Low RTT, low jitter, zero loss → high quality score."""
        m = self._metrics()
        for _ in range(10):
            m.record_success(20.0)  # 20ms, zero jitter, zero loss
        score = m.quality_score()
        self.assertGreater(score, 0.8, "Healthy peer should have high quality score")

    def test_quality_score_bounded_0_to_1(self):
        """Quality score is always in [0.0, 1.0]."""
        m = self._metrics()
        # Worst possible: all failures
        for _ in range(100):
            m.record_failure()
        score = m.quality_score()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_status_returns_dict(self):
        """status() returns a summary dict with expected keys."""
        m = self._metrics()
        m.record_success(50.0)
        status = m.status()
        self.assertIn("rtt_avg_ms", status)
        self.assertIn("jitter_avg_ms", status)
        self.assertIn("packet_loss_rate", status)
        self.assertIn("quality_score", status)
        self.assertIn("attempts", status)
        self.assertIn("failures", status)

    def test_thread_safety(self):
        """Concurrent record_success/record_failure calls do not raise."""
        m = self._metrics()
        errors = []

        def _writer(n):
            try:
                for _ in range(n):
                    m.record_success(float(n))
                    m.record_failure()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_writer, args=(50,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], "Thread-safety failure in ConnectionMetrics")


# ---------------------------------------------------------------------------
# TestRetryPolicy
# ---------------------------------------------------------------------------

class TestRetryPolicy(unittest.TestCase):
    """Tests for jitter-aware exponential backoff retry policy."""

    def _policy(self, max_attempts=3, base_ms=500, max_ms=10000):
        from api.federation.network_resilience import RetryPolicy
        return RetryPolicy(max_attempts, base_ms, max_ms)

    def test_delay_for_attempt_0_is_zero(self):
        """Attempt 0 (initial try) has zero delay."""
        p = self._policy()
        self.assertEqual(p.delay_for_attempt(0), 0.0)

    def test_delay_is_non_negative(self):
        """All attempt delays must be >= 0."""
        p = self._policy()
        for attempt in range(1, 6):
            delay = p.delay_for_attempt(attempt)
            self.assertGreaterEqual(delay, 0.0)

    def test_delay_bounded_by_max(self):
        """Delay never exceeds max_delay_ms / 1000 seconds."""
        p = self._policy(max_ms=1000)
        for attempt in range(1, 10):
            delay = p.delay_for_attempt(attempt)
            self.assertLessEqual(delay, 1.0 + 0.001)  # tiny float tolerance

    def test_should_retry_within_limit(self):
        """should_retry returns True when below max_attempts."""
        p = self._policy(max_attempts=3)
        self.assertTrue(p.should_retry(1))
        self.assertTrue(p.should_retry(2))

    def test_should_not_retry_at_limit(self):
        """should_retry returns False at max_attempts."""
        p = self._policy(max_attempts=3)
        self.assertFalse(p.should_retry(3))

    def test_full_jitter_produces_different_delays(self):
        """Full jitter means delays vary between calls (not deterministic)."""
        p = self._policy()
        delays = {p.delay_for_attempt(2) for _ in range(50)}
        # With full jitter, highly unlikely to get the same value 50 times
        self.assertGreater(len(delays), 1, "Full jitter should produce varied delays")

    def test_single_attempt_means_no_retry(self):
        """max_attempts=1 means no retries are permitted."""
        p = self._policy(max_attempts=1)
        self.assertFalse(p.should_retry(1))


# ---------------------------------------------------------------------------
# TestNetworkResilienceManager
# ---------------------------------------------------------------------------

class TestNetworkResilienceManager(unittest.TestCase):
    """Tests for the per-peer resilience manager registry."""

    def setUp(self):
        from api.federation.network_resilience import NetworkResilienceManager
        self.mgr = NetworkResilienceManager()

    def test_unknown_peer_quality_is_1(self):
        """Unknown peer (no data) returns quality score 1.0."""
        score = self.mgr.quality_score("did:key:z6MkNewPeer")
        self.assertEqual(score, 1.0)

    def test_record_success_updates_metrics(self):
        """Record success updates RTT for the peer."""
        self.mgr.record_success("did:key:z6MkPeer1", rtt_ms=100.0)
        h = self.mgr.health_for_peer("did:key:z6MkPeer1")
        self.assertAlmostEqual(h["rtt_avg_ms"], 100.0)

    def test_record_failure_updates_loss_rate(self):
        """Record failure updates packet loss rate."""
        self.mgr.record_success("did:key:z6MkPeer2", rtt_ms=50.0)
        self.mgr.record_failure("did:key:z6MkPeer2")
        h = self.mgr.health_for_peer("did:key:z6MkPeer2")
        self.assertGreater(h["packet_loss_rate"], 0.0)

    def test_adaptive_timeout_defaults_to_base(self):
        """New peer adaptive timeout equals base_secs."""
        timeout = self.mgr.adaptive_timeout("did:key:z6MkNewPeer2", base_secs=10.0)
        self.assertEqual(timeout, 10.0)

    def test_health_all_returns_all_peers(self):
        """health_all() includes all tracked peers."""
        self.mgr.record_success("did:key:z6MkPeerA", rtt_ms=30.0)
        self.mgr.record_success("did:key:z6MkPeerB", rtt_ms=60.0)
        all_health = self.mgr.health_all()
        self.assertIn("did:key:z6MkPeerA", all_health)
        self.assertIn("did:key:z6MkPeerB", all_health)

    def test_health_for_unknown_peer(self):
        """health_for_peer() returns no_data for unknown peer."""
        h = self.mgr.health_for_peer("did:key:z6MkUnknown")
        self.assertEqual(h.get("status"), "no_data")

    def test_is_quality_acceptable_default(self):
        """New peer is acceptable by default (no data = quality 1.0)."""
        with patch.object(
            type(self.mgr),
            "quality_score",
            return_value=1.0,
        ):
            # Patch quality_min_score to a known value
            with patch("api.federation.config.QUALITY_MIN_SCORE", 0.10):
                result = self.mgr.is_quality_acceptable("did:key:z6MkFresh")
        self.assertTrue(result)

    def test_separate_instances_are_independent(self):
        """Two manager instances track metrics independently."""
        from api.federation.network_resilience import NetworkResilienceManager
        mgr1 = NetworkResilienceManager()
        mgr2 = NetworkResilienceManager()
        mgr1.record_success("did:key:z6MkShared", rtt_ms=999.0)
        # mgr2 should not see mgr1's data
        h2 = mgr2.health_for_peer("did:key:z6MkShared")
        self.assertEqual(h2.get("status"), "no_data")


# ---------------------------------------------------------------------------
# TestResilientCall
# ---------------------------------------------------------------------------

class TestResilientCall(unittest.TestCase):
    """Tests for the resilient_call() wrapper."""

    def setUp(self):
        # Reset circuit breakers between tests
        from api.federation.circuit_breaker import circuit_breaker_registry
        circuit_breaker_registry.reset_all()

    def test_successful_call_returns_result(self):
        """resilient_call returns result on first success."""
        from api.federation.network_resilience import resilient_call

        result = resilient_call(
            peer_did="did:key:z6MkSuccessPeer",
            fn=lambda: {"status": "ok"},
        )
        self.assertEqual(result, {"status": "ok"})

    def test_retries_on_failure_then_succeeds(self):
        """resilient_call retries and returns result when fn eventually succeeds."""
        from api.federation.network_resilience import resilient_call
        import api.federation.config as _cfg

        call_count = {"n": 0}

        def _flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("transient error")
            return {"status": "ok"}

        # Ensure at least 3 attempts
        with patch.object(_cfg, "RETRY_MAX_ATTEMPTS", 3), \
             patch.object(_cfg, "RETRY_BASE_DELAY_MS", 1), \
             patch.object(_cfg, "RETRY_MAX_DELAY_MS", 1):
            result = resilient_call(
                peer_did="did:key:z6MkRetryPeer",
                fn=_flaky,
            )

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(call_count["n"], 3)

    def test_raises_after_max_attempts(self):
        """resilient_call raises after all retry attempts are exhausted."""
        from api.federation.network_resilience import resilient_call
        import api.federation.config as _cfg

        def _always_fail():
            raise ConnectionError("always fails")

        with patch.object(_cfg, "RETRY_MAX_ATTEMPTS", 2), \
             patch.object(_cfg, "RETRY_BASE_DELAY_MS", 1), \
             patch.object(_cfg, "RETRY_MAX_DELAY_MS", 1):
            with self.assertRaises(ConnectionError):
                resilient_call(
                    peer_did="did:key:z6MkFailPeer",
                    fn=_always_fail,
                )

    def test_circuit_open_not_retried(self):
        """resilient_call raises CircuitOpen without retrying."""
        from api.federation.network_resilience import resilient_call
        from api.federation.circuit_breaker import circuit_breaker_registry, CircuitOpen
        import api.federation.config as _cfg

        # Force circuit open for this peer
        cb = circuit_breaker_registry.get("did:key:z6MkCircuitPeer")
        for _ in range(_cfg.CIRCUIT_BREAKER_FAILURE_THRESHOLD):
            cb.on_failure()

        call_count = {"n": 0}
        def _counter():
            call_count["n"] += 1
            return {}

        with self.assertRaises(CircuitOpen):
            resilient_call(
                peer_did="did:key:z6MkCircuitPeer",
                fn=_counter,
            )

        self.assertEqual(call_count["n"], 0, "fn must not be called when circuit is open")

    def test_on_retry_callback_called_on_each_retry(self):
        """on_retry callback is invoked for each retry attempt."""
        from api.federation.network_resilience import resilient_call
        import api.federation.config as _cfg

        attempts = []

        def _on_retry(attempt, exc):
            attempts.append(attempt)

        call_count = {"n": 0}

        def _fail_twice():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ConnectionError("fail")
            return {"ok": True}

        with patch.object(_cfg, "RETRY_MAX_ATTEMPTS", 3), \
             patch.object(_cfg, "RETRY_BASE_DELAY_MS", 1), \
             patch.object(_cfg, "RETRY_MAX_DELAY_MS", 1):
            resilient_call(
                peer_did="did:key:z6MkCallbackPeer",
                fn=_fail_twice,
                on_retry=_on_retry,
            )

        self.assertEqual(len(attempts), 2, "on_retry should be called twice")

    def test_metrics_recorded_on_success(self):
        """resilient_call records RTT on success."""
        from api.federation.network_resilience import resilient_call, network_resilience_manager

        resilient_call(
            peer_did="did:key:z6MkMetricsPeer",
            fn=lambda: {},
        )
        h = network_resilience_manager.health_for_peer("did:key:z6MkMetricsPeer")
        self.assertGreater(h.get("attempts", 0), 0)

    def test_metrics_recorded_on_failure(self):
        """resilient_call records failures in metrics."""
        from api.federation.network_resilience import resilient_call, network_resilience_manager
        import api.federation.config as _cfg

        def _fail():
            raise TimeoutError("timeout")

        with patch.object(_cfg, "RETRY_MAX_ATTEMPTS", 1), \
             patch.object(_cfg, "RETRY_BASE_DELAY_MS", 1), \
             patch.object(_cfg, "RETRY_MAX_DELAY_MS", 1):
            try:
                resilient_call(
                    peer_did="did:key:z6MkFailMetricsPeer",
                    fn=_fail,
                )
            except TimeoutError:
                pass

        h = network_resilience_manager.health_for_peer("did:key:z6MkFailMetricsPeer")
        self.assertGreater(h.get("failures", 0), 0)


# ---------------------------------------------------------------------------
# TestQualityBasedRouting
# ---------------------------------------------------------------------------

class TestQualityBasedRouting(unittest.TestCase):
    """Tests for quality-score-based peer prioritization in discovery."""

    def test_quality_min_score_config_default(self):
        """QUALITY_MIN_SCORE must default to 0.10."""
        import importlib
        import api.federation.config as _cfg
        importlib.reload(_cfg)
        self.assertAlmostEqual(_cfg.QUALITY_MIN_SCORE, 0.10)

    def test_rtt_window_config_default(self):
        """RTT_WINDOW must default to 20."""
        import importlib
        import api.federation.config as _cfg
        importlib.reload(_cfg)
        self.assertEqual(_cfg.RTT_WINDOW, 20)

    def test_timeout_base_default(self):
        """TIMEOUT_BASE_SECS must default to 10."""
        import importlib
        import api.federation.config as _cfg
        importlib.reload(_cfg)
        self.assertAlmostEqual(_cfg.TIMEOUT_BASE_SECS, 10.0)

    def test_timeout_max_default(self):
        """TIMEOUT_MAX_SECS must default to 30."""
        import importlib
        import api.federation.config as _cfg
        importlib.reload(_cfg)
        self.assertAlmostEqual(_cfg.TIMEOUT_MAX_SECS, 30.0)

    def test_retry_max_attempts_default(self):
        """RETRY_MAX_ATTEMPTS must default to 3."""
        import importlib
        import api.federation.config as _cfg
        importlib.reload(_cfg)
        self.assertEqual(_cfg.RETRY_MAX_ATTEMPTS, 3)

    def test_retry_base_delay_default(self):
        """RETRY_BASE_DELAY_MS must default to 500."""
        import importlib
        import api.federation.config as _cfg
        importlib.reload(_cfg)
        self.assertEqual(_cfg.RETRY_BASE_DELAY_MS, 500)

    def test_config_validates_timeout_order(self):
        """validate() rejects TIMEOUT_MAX_SECS < TIMEOUT_BASE_SECS."""
        import importlib, api.federation.config as _cfg
        importlib.reload(_cfg)
        with patch.object(_cfg, "TIMEOUT_BASE_SECS", 30.0), \
             patch.object(_cfg, "TIMEOUT_MAX_SECS", 5.0):
            errors = _cfg.validate()
        self.assertTrue(
            any("TIMEOUT_MAX" in e for e in errors),
            "validate() must reject inverted timeout bounds"
        )

    def test_config_validates_retry_attempts(self):
        """validate() rejects RETRY_MAX_ATTEMPTS < 1."""
        import importlib, api.federation.config as _cfg
        importlib.reload(_cfg)
        with patch.object(_cfg, "RETRY_MAX_ATTEMPTS", 0):
            errors = _cfg.validate()
        self.assertTrue(
            any("RETRY_MAX_ATTEMPTS" in e for e in errors),
            "validate() must reject RETRY_MAX_ATTEMPTS=0"
        )


if __name__ == "__main__":
    unittest.main()
