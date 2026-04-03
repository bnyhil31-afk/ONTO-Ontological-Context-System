"""
api/consent/config.py

All consent configuration in one place.

Every behavior has an env var. Every env var has a safe default.
The safe default for every toggle preserves backwards compatibility:
ONTO_CONSENT_ENABLED=false means single-user deployments are entirely
unchanged by Phase 4.

No code outside this file reads consent env vars directly.
This makes configuration auditable and testable in isolation.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import os
from typing import FrozenSet

# ---------------------------------------------------------------------------
# MASTER SWITCH
# ---------------------------------------------------------------------------

CONSENT_ENABLED: bool = (
    os.getenv("ONTO_CONSENT_ENABLED", "false").lower() == "true"
)

# ---------------------------------------------------------------------------
# REGULATORY PROFILE
# ---------------------------------------------------------------------------

CONSENT_PROFILE: str = os.getenv("ONTO_CONSENT_PROFILE", "team")

VALID_PROFILES: FrozenSet[str] = frozenset(
    {"team", "healthcare", "financial", "custom"}
)

# ---------------------------------------------------------------------------
# FEATURE FLAGS
# ---------------------------------------------------------------------------

# When False: consent decisions are logged but never block operations.
# Use during rollout to validate coverage before enforcing.
# NEVER set False in production.
CONSENT_GATE_ENFORCE: bool = (
    os.getenv("ONTO_CONSENT_GATE_ENFORCE", "true").lower() == "true"
)

# Enable just-in-time consent prompting at graph.navigate()
CONSENT_JIT_ENABLED: bool = (
    os.getenv("ONTO_CONSENT_JIT_ENABLED", "true").lower() == "true"
)

# Audit-only mode: log what would be blocked without blocking it.
# Use this during rollout. Never ship to production in this mode.
CONSENT_AUDIT_ONLY: bool = (
    os.getenv("ONTO_CONSENT_AUDIT_ONLY", "false").lower() == "true"
)

# ---------------------------------------------------------------------------
# DELEGATION
# ---------------------------------------------------------------------------

# Maximum delegation chain depth. A → B → C = depth 2.
# Healthcare and financial profiles override this to 1.
CONSENT_DELEGATION_MAX_DEPTH: int = int(
    os.getenv("ONTO_CONSENT_DELEGATION_MAX_DEPTH", "3")
)

# ---------------------------------------------------------------------------
# RETENTION
# ---------------------------------------------------------------------------

# Retention period in days. 0 = indefinite (default).
# Healthcare profile: 2190 (6 years). Financial: 2555 (7 years).
# Operator env var overrides profile default when set.
_retention_raw = os.getenv("ONTO_CONSENT_RETENTION_DAYS", "")
CONSENT_RETENTION_DAYS: int = int(_retention_raw) if _retention_raw else 0

# ---------------------------------------------------------------------------
# RE-CONFIRMATION
# ---------------------------------------------------------------------------

# Days before a standing consent (valid_until=NULL) requires re-confirmation.
CONSENT_RECONFIRM_DAYS: int = int(
    os.getenv("ONTO_CONSENT_RECONFIRM_DAYS", "90")
)

# ---------------------------------------------------------------------------
# VCSERVICE (Phase 5)
# ---------------------------------------------------------------------------

VC_SERVICE_ENABLED: bool = (
    os.getenv("ONTO_VC_SERVICE_ENABLED", "false").lower() == "true"
)

VC_SERVICE_URL: str = os.getenv(
    "ONTO_VC_SERVICE_URL", "http://127.0.0.1:7800"
)

VC_SERVICE_TIMEOUT_SECS: int = int(
    os.getenv("ONTO_VC_SERVICE_TIMEOUT_SECS", "5")
)

VC_STATUS_LIST_URL: str = os.getenv("ONTO_VC_STATUS_LIST_URL", "")

# ---------------------------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------------------------

def validate() -> list:
    """
    Validate the current consent configuration.
    Returns a list of error strings. Empty list = valid.
    Called by ConsentManager.start() before initialising.
    """
    errors = []

    if CONSENT_PROFILE not in VALID_PROFILES:
        errors.append(
            f"Invalid ONTO_CONSENT_PROFILE '{CONSENT_PROFILE}'. "
            f"Valid values: {sorted(VALID_PROFILES)}"
        )

    if not 0 <= CONSENT_DELEGATION_MAX_DEPTH <= 5:
        errors.append(
            f"ONTO_CONSENT_DELEGATION_MAX_DEPTH must be in [0, 5], "
            f"got {CONSENT_DELEGATION_MAX_DEPTH}."
        )

    if CONSENT_RECONFIRM_DAYS < 1:
        errors.append(
            f"ONTO_CONSENT_RECONFIRM_DAYS must be >= 1, "
            f"got {CONSENT_RECONFIRM_DAYS}."
        )

    if CONSENT_AUDIT_ONLY and CONSENT_GATE_ENFORCE:
        # Audit-only takes precedence but the combination is confusing.
        # Warn rather than error — the system will behave correctly.
        errors.append(
            "Warning: ONTO_CONSENT_AUDIT_ONLY=true overrides "
            "ONTO_CONSENT_GATE_ENFORCE=true. Consent will be logged "
            "but not enforced."
        )

    return errors


def summary() -> dict:
    """
    Return a sanitised summary of the current configuration.
    Safe to log or include in onto_status output.
    """
    return {
        "enabled":               CONSENT_ENABLED,
        "profile":               CONSENT_PROFILE,
        "gate_enforce":          CONSENT_GATE_ENFORCE,
        "jit_enabled":           CONSENT_JIT_ENABLED,
        "audit_only":            CONSENT_AUDIT_ONLY,
        "delegation_max_depth":  CONSENT_DELEGATION_MAX_DEPTH,
        "retention_days":        CONSENT_RETENTION_DAYS or "indefinite",
        "reconfirm_days":        CONSENT_RECONFIRM_DAYS,
        "vc_service_enabled":    VC_SERVICE_ENABLED,
        "vc_service_url":        VC_SERVICE_URL if VC_SERVICE_ENABLED else "",
    }
