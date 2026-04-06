"""
api/federation/config.py

All federation configuration in one place.

Every behavior has an env var. Every env var has a safe default.
The safe default for every toggle is the most restrictive option.

No code outside this file reads federation env vars directly.
This makes configuration auditable and testable in isolation.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import os
from typing import FrozenSet, Optional


# ---------------------------------------------------------------------------
# MASTER SWITCH
# ---------------------------------------------------------------------------

FEDERATION_ENABLED: bool = (
    os.getenv("ONTO_FEDERATION_ENABLED", "false").lower() == "true"
)

# ---------------------------------------------------------------------------
# DEPLOYMENT STAGE
# Controls which discovery protocol is active.
# Phase 3 supports: local, intranet
# Phase 4+ will support: internet, p2p
# ---------------------------------------------------------------------------

FEDERATION_STAGE: str = os.getenv("ONTO_FEDERATION_STAGE", "local")

VALID_STAGES: FrozenSet[str] = frozenset(
    {"local", "intranet", "internet", "p2p"}
)

# ---------------------------------------------------------------------------
# IDENTITY AND KEY STORAGE
# The private key is NEVER stored in SQLite.
# It lives in a separate encrypted file.
# ---------------------------------------------------------------------------

FEDERATION_KEY_PATH: str = os.path.expanduser(
    os.getenv("ONTO_FED_KEY_PATH", "~/.onto/federation/node.key")
)

# ---------------------------------------------------------------------------
# TRUST
# ---------------------------------------------------------------------------

# Trust assigned to ALL inbound data from federation, regardless of source.
# The sender's claimed trust score is ignored entirely.
INBOUND_TRUST: float = float(
    os.getenv("ONTO_FED_INBOUND_TRUST", "0.30")
)

# Minimum peer trust score required before sensitive content
# (is_sensitive=True) may be shared with or received from that peer.
SENSITIVE_TRUST_THRESHOLD: float = float(
    os.getenv("ONTO_FED_SENSITIVE_TRUST_THRESHOLD", "0.95")
)

# ---------------------------------------------------------------------------
# DATA CLASSIFICATION CEILING
# Maximum classification level of data that may leave this node.
# 0 = public only
# 1 = internal
# 2 = personal (default)
# 3+ = never shares (sensitive, PHI, privileged)
# ---------------------------------------------------------------------------

MAX_SHARE_CLASSIFICATION: int = int(
    os.getenv("ONTO_FED_MAX_SHARE_CLASSIFICATION", "2")
)

# ---------------------------------------------------------------------------
# DATA RESIDENCY
# Comma-separated ISO 3166-1 alpha-2 country codes.
# Empty string = no constraint.
# Example: "US,CA,GB"
# ---------------------------------------------------------------------------

_residency_raw: str = os.getenv("ONTO_FED_DATA_RESIDENCY", "")
DATA_RESIDENCY: FrozenSet[str] = frozenset(
    c.strip().upper()
    for c in _residency_raw.split(",")
    if c.strip()
)

# ---------------------------------------------------------------------------
# CONSENT
# ---------------------------------------------------------------------------

CONSENT_MODE: str = os.getenv("ONTO_FED_CONSENT_MODE", "explicit")

VALID_CONSENT_MODES: FrozenSet[str] = frozenset(
    {"explicit", "session", "standing"}
)

# Days before a standing consent (expires_at=NULL) requires re-confirmation.
STANDING_CONSENT_RECONFIRM_DAYS: int = int(
    os.getenv("ONTO_FED_STANDING_CONSENT_RECONFIRM_DAYS", "90")
)

# ---------------------------------------------------------------------------
# ANTI-CONCENTRATION
# Graph similarity above this threshold triggers a soft warning.
# 1.0 = disabled (default). 0.8 = warn if 80%+ concept overlap.
# ---------------------------------------------------------------------------

MAX_GRAPH_SIMILARITY: float = float(
    os.getenv("ONTO_FED_MAX_GRAPH_SIMILARITY", "1.0")
)

# ---------------------------------------------------------------------------
# RATE LIMITING AND MESSAGING
# ---------------------------------------------------------------------------

# Maximum messages accepted from a single peer per minute.
MAX_MSGS_PER_PEER_PER_MIN: int = int(
    os.getenv("ONTO_FED_MAX_MSGS_PER_PEER_PER_MIN", "60")
)

# ---------------------------------------------------------------------------
# CIRCUIT BREAKER
# Protects against cascading failures from misbehaving or unreachable peers.
# Opens the circuit after CIRCUIT_BREAKER_FAILURE_THRESHOLD consecutive
# failures, and half-opens after CIRCUIT_BREAKER_RECOVERY_SECONDS.
# ---------------------------------------------------------------------------

# Number of consecutive failures before the circuit opens for a peer.
CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = int(
    os.getenv("ONTO_FED_CB_FAILURE_THRESHOLD", "5")
)

# Seconds to wait in OPEN state before allowing a single probe (half-open).
CIRCUIT_BREAKER_RECOVERY_SECONDS: int = int(
    os.getenv("ONTO_FED_CB_RECOVERY_SECONDS", "60")
)

# ---------------------------------------------------------------------------
# STATIC PEERS (for local stage)
# Format: did:key:z6Mk...@host:port,did:key:z6Mk...@host:port
# ---------------------------------------------------------------------------

_peers_raw: str = os.getenv("ONTO_FED_PEERS", "")
STATIC_PEERS: list = [
    p.strip() for p in _peers_raw.split(",") if p.strip()
]

# ---------------------------------------------------------------------------
# CERTIFICATE LIFETIME
# Short-lived certs with proactive renewal at 50% of lifetime.
# ---------------------------------------------------------------------------

CERT_LIFETIME_DAYS: int = int(
    os.getenv("ONTO_FED_CERT_LIFETIME_DAYS", "7")
)

# ---------------------------------------------------------------------------
# TLS / mTLS (internet + p2p stages)
# Required when FEDERATION_STAGE=internet or p2p.
# If cert/key files don't exist, InternetAdapter auto-generates a
# self-signed certificate and writes an audit event.
# ---------------------------------------------------------------------------

# Require mutual TLS (both sides present certificates).
# Default: true — most restrictive option.
MTLS_REQUIRED: bool = (
    os.getenv("ONTO_FED_MTLS_REQUIRED", "true").lower() == "true"
)

# Path to this node's TLS certificate (PEM format).
TLS_CERT_PATH: str = os.path.expanduser(
    os.getenv("ONTO_FED_TLS_CERT_PATH", "~/.onto/federation/node.crt")
)

# Path to this node's TLS private key (PEM format). Mode 0o600 required.
TLS_KEY_PATH: str = os.path.expanduser(
    os.getenv("ONTO_FED_TLS_KEY_PATH", "~/.onto/federation/node.pem")
)

# Path to CA bundle for peer certificate verification.
# Empty = use system CA store (acceptable for CA-signed certs;
# TOFU pinning in peer_store.py provides additional verification).
TLS_CA_BUNDLE: str = os.path.expanduser(
    os.getenv("ONTO_FED_TLS_CA_BUNDLE", "")
)

# ---------------------------------------------------------------------------
# REGULATORY PROFILES (internet + p2p stages)
# Comma-separated profile names. Empty = no regulatory profile (default).
# Valid values: HIPAA, GDPR, FERPA, GLBA
# Profiles are ADDITIVE RESTRICTIONS ONLY — they can only further restrict
# what the safety gates already enforce. They never override absolute barriers.
# Example: ONTO_FED_REGULATORY_PROFILES=HIPAA,GDPR
# ---------------------------------------------------------------------------

_profiles_raw: str = os.getenv("ONTO_FED_REGULATORY_PROFILES", "")
REGULATORY_PROFILES: list = [
    p.strip().upper() for p in _profiles_raw.split(",") if p.strip()
]

VALID_REGULATORY_PROFILES: FrozenSet[str] = frozenset(
    {"HIPAA", "GDPR", "FERPA", "GLBA"}
)

# ---------------------------------------------------------------------------
# P2P / KADEMLIA DHT (p2p stage)
# ---------------------------------------------------------------------------

# UDP port for the Kademlia DHT node (separate from the federation HTTP port).
DHT_PORT: int = int(os.getenv("ONTO_FED_DHT_PORT", "7701"))

# Comma-separated bootstrap node addresses: "host:port,host:port"
# Required when FEDERATION_STAGE=p2p.
_bootstrap_raw: str = os.getenv("ONTO_FED_DHT_BOOTSTRAP_NODES", "")
DHT_BOOTSTRAP_NODES: list = [
    n.strip() for n in _bootstrap_raw.split(",") if n.strip()
]

# Sybil resistance proof-of-work difficulty (leading zero bits).
# 0 = disabled. 4 = default (~65000 hashes per identity). 8 = strict.
SYBIL_POW_DIFFICULTY: int = int(
    os.getenv("ONTO_FED_SYBIL_POW_DIFFICULTY", "4")
)

# ---------------------------------------------------------------------------
# NETWORK RESILIENCE (internet + p2p stages)
# Controls adaptive timeouts, jitter-aware retry, and connection quality
# tracking. These settings apply regardless of network environment —
# they protect against real-world conditions: jitter, lag, packet loss.
# ---------------------------------------------------------------------------

# Maximum number of attempts per outbound request (initial + retries).
# 1 = no retry. 3 = default (initial + 2 retries). Set to 1 for environments
# where retries are undesirable (e.g., idempotency not guaranteed).
RETRY_MAX_ATTEMPTS: int = int(
    os.getenv("ONTO_FED_RETRY_MAX_ATTEMPTS", "3")
)

# Base delay for exponential backoff (milliseconds).
# Full jitter: delay = random(0, min(MAX_DELAY_MS, BASE_DELAY_MS × 2^attempt))
# This prevents thundering herd when many nodes retry a recovering peer.
RETRY_BASE_DELAY_MS: int = int(
    os.getenv("ONTO_FED_RETRY_BASE_DELAY_MS", "500")
)

# Maximum retry delay cap (milliseconds).
# Prevents excessive wait when backoff exponent grows large.
RETRY_MAX_DELAY_MS: int = int(
    os.getenv("ONTO_FED_RETRY_MAX_DELAY_MS", "10000")
)

# Baseline request timeout (seconds) before jitter adjustment.
# The adaptive timeout formula is: base + 4 × jitter_avg
# This matches RFC 6298 (TCP RTO calculation) adapted for application level.
TIMEOUT_BASE_SECS: float = float(
    os.getenv("ONTO_FED_TIMEOUT_BASE_SECS", "10.0")
)

# Maximum adaptive timeout ceiling (seconds).
# No matter how high jitter is, timeouts are capped here to prevent
# threads from blocking indefinitely on a slow or malicious peer.
TIMEOUT_MAX_SECS: float = float(
    os.getenv("ONTO_FED_TIMEOUT_MAX_SECS", "30.0")
)

# Minimum quality score to prioritize a peer in discovery results.
# Peers below this score are still contacted but ranked lower.
# The circuit breaker (not this threshold) handles actual blocking.
# Range: 0.0 (accept any quality) – 1.0 (perfect only). Default: 0.10.
QUALITY_MIN_SCORE: float = float(
    os.getenv("ONTO_FED_QUALITY_MIN_SCORE", "0.10")
)

# Rolling window size for per-peer RTT and jitter samples.
# Larger = more stable estimates; smaller = faster adaptation to changes.
RTT_WINDOW: int = int(
    os.getenv("ONTO_FED_RTT_WINDOW", "20")
)

# ---------------------------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------------------------

def validate() -> list:
    """
    Validate the current federation configuration.
    Returns a list of error strings. Empty list = valid.
    Called by FederationManager.start() before initializing.
    """
    errors = []

    if FEDERATION_STAGE not in VALID_STAGES:
        errors.append(
            f"Invalid ONTO_FEDERATION_STAGE '{FEDERATION_STAGE}'. "
            f"Valid values: {sorted(VALID_STAGES)}"
        )

    if not 0.0 <= INBOUND_TRUST <= 1.0:
        errors.append(
            f"ONTO_FED_INBOUND_TRUST must be in [0.0, 1.0], "
            f"got {INBOUND_TRUST}."
        )

    if not 0.0 <= SENSITIVE_TRUST_THRESHOLD <= 1.0:
        errors.append(
            f"ONTO_FED_SENSITIVE_TRUST_THRESHOLD must be in [0.0, 1.0], "
            f"got {SENSITIVE_TRUST_THRESHOLD}."
        )

    if not 0 <= MAX_SHARE_CLASSIFICATION <= 5:
        errors.append(
            f"ONTO_FED_MAX_SHARE_CLASSIFICATION must be in [0, 5], "
            f"got {MAX_SHARE_CLASSIFICATION}."
        )

    if CONSENT_MODE not in VALID_CONSENT_MODES:
        errors.append(
            f"Invalid ONTO_FED_CONSENT_MODE '{CONSENT_MODE}'. "
            f"Valid values: {sorted(VALID_CONSENT_MODES)}"
        )

    if not 0.0 <= MAX_GRAPH_SIMILARITY <= 1.0:
        errors.append(
            f"ONTO_FED_MAX_GRAPH_SIMILARITY must be in [0.0, 1.0], "
            f"got {MAX_GRAPH_SIMILARITY}."
        )

    if MAX_MSGS_PER_PEER_PER_MIN < 1:
        errors.append(
            f"ONTO_FED_MAX_MSGS_PER_PEER_PER_MIN must be >= 1, "
            f"got {MAX_MSGS_PER_PEER_PER_MIN}."
        )

    for profile in REGULATORY_PROFILES:
        if profile not in VALID_REGULATORY_PROFILES:
            errors.append(
                f"Unknown regulatory profile '{profile}'. "
                f"Valid values: {sorted(VALID_REGULATORY_PROFILES)}"
            )

    if FEDERATION_STAGE == "p2p" and not DHT_BOOTSTRAP_NODES:
        errors.append(
            "P2P stage requires at least one bootstrap node. "
            "Set ONTO_FED_DHT_BOOTSTRAP_NODES=host:port"
        )

    if not 0 <= SYBIL_POW_DIFFICULTY <= 20:
        errors.append(
            f"ONTO_FED_SYBIL_POW_DIFFICULTY must be in [0, 20], "
            f"got {SYBIL_POW_DIFFICULTY}."
        )

    if RETRY_MAX_ATTEMPTS < 1:
        errors.append(
            f"ONTO_FED_RETRY_MAX_ATTEMPTS must be >= 1, "
            f"got {RETRY_MAX_ATTEMPTS}."
        )

    if RETRY_BASE_DELAY_MS < 1:
        errors.append(
            f"ONTO_FED_RETRY_BASE_DELAY_MS must be >= 1, "
            f"got {RETRY_BASE_DELAY_MS}."
        )

    if TIMEOUT_BASE_SECS <= 0:
        errors.append(
            f"ONTO_FED_TIMEOUT_BASE_SECS must be > 0, "
            f"got {TIMEOUT_BASE_SECS}."
        )

    if TIMEOUT_MAX_SECS < TIMEOUT_BASE_SECS:
        errors.append(
            f"ONTO_FED_TIMEOUT_MAX_SECS ({TIMEOUT_MAX_SECS}) must be >= "
            f"ONTO_FED_TIMEOUT_BASE_SECS ({TIMEOUT_BASE_SECS})."
        )

    if not 0.0 <= QUALITY_MIN_SCORE <= 1.0:
        errors.append(
            f"ONTO_FED_QUALITY_MIN_SCORE must be in [0.0, 1.0], "
            f"got {QUALITY_MIN_SCORE}."
        )

    if RTT_WINDOW < 2:
        errors.append(
            f"ONTO_FED_RTT_WINDOW must be >= 2, got {RTT_WINDOW}."
        )

    return errors


def summary() -> dict:
    """
    Return a sanitized summary of the current configuration.
    Safe to log or include in onto_status output.
    Key file path is included (not the key itself).
    """
    return {
        "enabled":                  FEDERATION_ENABLED,
        "stage":                    FEDERATION_STAGE,
        "key_path":                 FEDERATION_KEY_PATH,
        "inbound_trust":            INBOUND_TRUST,
        "sensitive_trust_threshold": SENSITIVE_TRUST_THRESHOLD,
        "max_share_classification": MAX_SHARE_CLASSIFICATION,
        "data_residency":           sorted(DATA_RESIDENCY),
        "consent_mode":             CONSENT_MODE,
        "standing_reconfirm_days":  STANDING_CONSENT_RECONFIRM_DAYS,
        "max_graph_similarity":     MAX_GRAPH_SIMILARITY,
        "max_msgs_per_peer_min":    MAX_MSGS_PER_PEER_PER_MIN,
        "static_peer_count":        len(STATIC_PEERS),
        "cert_lifetime_days":       CERT_LIFETIME_DAYS,
        "mtls_required":            MTLS_REQUIRED,
        "tls_cert_path":            TLS_CERT_PATH,
        "regulatory_profiles":      REGULATORY_PROFILES,
        "dht_port":                 DHT_PORT,
        "dht_bootstrap_count":      len(DHT_BOOTSTRAP_NODES),
        "sybil_pow_difficulty":     SYBIL_POW_DIFFICULTY,
        "retry_max_attempts":       RETRY_MAX_ATTEMPTS,
        "retry_base_delay_ms":      RETRY_BASE_DELAY_MS,
        "retry_max_delay_ms":       RETRY_MAX_DELAY_MS,
        "timeout_base_secs":        TIMEOUT_BASE_SECS,
        "timeout_max_secs":         TIMEOUT_MAX_SECS,
        "quality_min_score":        QUALITY_MIN_SCORE,
        "rtt_window":               RTT_WINDOW,
    }
