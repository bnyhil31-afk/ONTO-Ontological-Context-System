"""
api/consent/__init__.py

ONTO Consent Ledger — Phase 4

Multi-user consent infrastructure. Disabled by default.
Single-user deployments are entirely unchanged when
ONTO_CONSENT_ENABLED=false (the default).

Phase 4 has no required dependencies beyond Python's standard library.
The consent ledger is pure Python + SQLite.

Phase 5 adds the VCService sidecar for W3C VC 2.0 issuance.
Phase 5 required deps: a Rust/Go sidecar (HTTP API) or a Python
VC 2.0 library when one becomes available.

To enable consent for multi-user deployments:
  1. Set ONTO_CONSENT_ENABLED=true
  2. Set ONTO_CONSENT_PROFILE=team|healthcare|financial
  3. Run ONTO normally — consent tables are created on first boot

Governing principle: Consent is checked at the data-access layer,
not just at collection time. Every graph.navigate() call involving
another subject's data passes through the consent gate.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

CONSENT_SPEC_VERSION: str = "CONSENT-LEDGER-SPEC-001-v1.0"

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
# Import lazily to avoid circular imports and to keep startup fast
# when consent is disabled (the common case in Phase 4).
#
# Callers should use:
#   from api.consent.adapter import ConsentAdapter, ConsentDecision
#   from api.consent.ledger import ConsentLedger
#   from api.consent.enforcement import consent_gate
#   from api.consent.profiles import get_active_profile
#   from api.consent import config as consent_config
#
# Do not import from this __init__ directly — import from the submodule.
# ---------------------------------------------------------------------------


def is_enabled() -> bool:
    """
    Return True if consent is configured and enabled.
    Safe to call at any time — never raises.

    Returns False if:
      - ONTO_CONSENT_ENABLED is false (or not set)
      - Any exception occurs during the check
    """
    try:
        from api.consent import config as _cfg
        return _cfg.CONSENT_ENABLED
    except Exception:
        return False


def get_spec_version() -> str:
    """Return the consent spec version this package implements."""
    return CONSENT_SPEC_VERSION
