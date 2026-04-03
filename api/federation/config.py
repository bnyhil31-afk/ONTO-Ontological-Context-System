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

    if FEDERATION_STAGE in ("internet", "p2p"):
        errors.append(
            f"Stage '{FEDERATION_STAGE}' is not available in Phase 3. "
            f"Use 'local' or 'intranet'."
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
    }
