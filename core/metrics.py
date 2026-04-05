"""
core/metrics.py

In-process Prometheus-format metrics for ONTO.
No third-party dependency — uses stdlib collections.Counter and threading.Lock.

Emits Prometheus text format (exposition format 0.0.4) suitable for scraping
by Prometheus, Grafana Agent, OpenTelemetry Collector, Datadog Agent, etc.

Counters exposed:
  onto_requests_total{endpoint, status_code}
  onto_rate_limit_hits_total{tier}      — "global" or "per_client"
  onto_auth_failures_total
  onto_auth_successes_total
  onto_chain_gaps_total
  onto_crisis_events_total
  onto_body_limit_rejections_total
  onto_timeout_rejections_total

Usage:
    from core.metrics import metrics
    metrics.inc_requests(endpoint="/process", status_code=200)
    metrics.inc_rate_limit_hit(tier="per_client")

    # Render Prometheus text:
    text = metrics.render()

Enabling the /metrics endpoint:
    Set ONTO_METRICS_ENABLED=true.
    The endpoint requires authentication by default
    (ONTO_METRICS_REQUIRE_AUTH=true).

Plain English: This module counts events so monitoring systems can observe
the system's behaviour over time without touching the audit trail.
"""

import threading
from collections import defaultdict
from typing import Dict


class ONTOMetrics:
    """
    Thread-safe in-process counter registry.
    All increment operations are O(1) and lock-protected.
    Rendering (render()) iterates all counters under the lock — acceptable
    for the scrape frequency of any monitoring system.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # {(metric_name, label_tuple): int}
        self._counters: Dict[tuple, int] = defaultdict(int)

    # ── Increment helpers ────────────────────────────────────────────────────

    def inc_requests(self, endpoint: str, status_code: int) -> None:
        """Record a completed HTTP request."""
        with self._lock:
            self._counters[("onto_requests_total", (
                ("endpoint", endpoint),
                ("status_code", str(status_code)),
            ))] += 1

    def inc_rate_limit_hit(self, tier: str = "per_client") -> None:
        """Record a rate-limit rejection. tier: 'global' or 'per_client'."""
        with self._lock:
            self._counters[("onto_rate_limit_hits_total", (
                ("tier", tier),
            ))] += 1

    def inc_auth_failure(self) -> None:
        with self._lock:
            self._counters[("onto_auth_failures_total", ())] += 1

    def inc_auth_success(self) -> None:
        with self._lock:
            self._counters[("onto_auth_successes_total", ())] += 1

    def inc_chain_gap(self) -> None:
        """Record a Merkle chain gap detected at startup or on-demand verify."""
        with self._lock:
            self._counters[("onto_chain_gaps_total", ())] += 1

    def inc_crisis_event(self) -> None:
        """Record a CRISIS signal detection."""
        with self._lock:
            self._counters[("onto_crisis_events_total", ())] += 1

    def inc_body_limit_rejection(self) -> None:
        """Record a request rejected by the body size limit middleware."""
        with self._lock:
            self._counters[("onto_body_limit_rejections_total", ())] += 1

    def inc_timeout_rejection(self) -> None:
        """Record a request rejected by the timeout middleware."""
        with self._lock:
            self._counters[("onto_timeout_rejections_total", ())] += 1

    # ── Prometheus text rendering ────────────────────────────────────────────

    def render(self) -> str:
        """
        Render all counters in Prometheus exposition format 0.0.4.
        Thread-safe: takes the lock for the duration of rendering.

        Returns a UTF-8 string ready to serve as the body of GET /metrics.
        """
        _HELP = {
            "onto_requests_total":
                "Total HTTP requests handled by the ONTO API.",
            "onto_rate_limit_hits_total":
                "Total requests rejected by rate limiting.",
            "onto_auth_failures_total":
                "Total authentication failures.",
            "onto_auth_successes_total":
                "Total successful authentications.",
            "onto_chain_gaps_total":
                "Total Merkle chain gaps detected (startup or on-demand).",
            "onto_crisis_events_total":
                "Total CRISIS signals detected in processed inputs.",
            "onto_body_limit_rejections_total":
                "Total requests rejected by the body size limit middleware.",
            "onto_timeout_rejections_total":
                "Total requests rejected by the request timeout middleware.",
        }

        lines = []
        with self._lock:
            # Group counters by metric name for # HELP / # TYPE headers
            by_name: Dict[str, list] = defaultdict(list)
            for (name, labels), value in self._counters.items():
                by_name[name].append((labels, value))

            for name in sorted(by_name):
                help_text = _HELP.get(name, f"ONTO counter: {name}")
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} counter")
                for labels, value in sorted(by_name[name]):
                    label_str = (
                        "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}"
                        if labels
                        else ""
                    )
                    lines.append(f"{name}{label_str} {value}")

        lines.append("")  # trailing newline required by Prometheus format
        return "\n".join(lines)

    def reset(self) -> None:
        """Clear all counters. Used in tests only."""
        with self._lock:
            self._counters.clear()


# Single shared instance — import this everywhere
metrics = ONTOMetrics()
