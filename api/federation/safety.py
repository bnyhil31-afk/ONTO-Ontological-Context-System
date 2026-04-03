"""
api/federation/safety.py

FEDERATION SAFETY FILTER — the most important file in Phase 3.

This module implements the two-tier safety model for all data crossing
node boundaries:

  Tier 1 — ABSOLUTE BARRIERS (not configurable, not bypassable):
    - Crisis content NEVER crosses node boundaries. Ever.
    - Classification >= 4 (PHI, privileged) NEVER crosses node boundaries.
    These are invariants of the federation protocol. An implementation
    that violates them is non-compliant and unsafe.

  Tier 2 — CONFIGURABLE CONTROLS (defaults are maximally restrictive):
    - Classification ceiling (ONTO_FED_MAX_SHARE_CLASSIFICATION, default 2)
    - Sensitive content trust threshold (default 0.95)
    - Inbound trust floor (default 0.30)
    - Data residency constraints

Every piece of data — inbound and outbound — passes through this module
before any network operation occurs. Safety is enforced at the boundary,
not in the adapter implementations.

SAFETY-CRITICAL: Tests in TestAbsoluteBarriers and TestFederationSafetyFilter
block deployment if they fail, even if all other tests pass.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

from typing import Any, Dict, Generator, Tuple

from modules.graph import _contains_crisis


# ---------------------------------------------------------------------------
# ABSOLUTE BARRIERS — Tier 1
# These functions have no configuration parameters.
# They cannot be overridden, disabled, or bypassed.
# ---------------------------------------------------------------------------

def check_absolute_barriers(
    text: str,
    classification: int,
    is_crisis: bool,
) -> Tuple[bool, str]:
    """
    Run all absolute barriers in sequence.
    Returns (allowed, reason).
    Returns (False, reason) on the FIRST barrier that fires.
    Order is intentional: crisis is always checked first.

    These checks are called before any configurable safety checks.
    No configuration parameter can change their behavior.

    Arguments:
        text:           The raw text content being evaluated.
                        _contains_crisis() is applied to this directly.
        classification: Data classification level (0-5).
        is_crisis:      Pre-computed crisis flag from intake.receive().
                        Checked in addition to text-based detection.
    """
    # Barrier 1: Crisis content NEVER federates.
    # Check both the pre-computed flag AND the raw text.
    # The raw text check is non-negotiable — a peer cannot bypass this by
    # failing to set is_crisis=True in their payload.
    if is_crisis or _contains_crisis(text):
        return False, "crisis content never federates"

    # Barrier 2: PHI and privileged content NEVER federates.
    # classification 4 = privileged (attorney-client, clinical, clergy)
    # classification 5 = critical (existential risk if exposed)
    if classification >= 4:
        return (
            False,
            f"classification {classification} (PHI/privileged) "
            f"never federates",
        )

    return True, "passed"


def check_inbound_for_crisis(data: Dict[str, Any]) -> bool:
    """
    Run _contains_crisis() on every string-valued field in received data.
    Returns True if crisis content is found anywhere in the payload.

    Called by can_receive() on EVERY inbound payload, regardless of what
    the sender's capability manifest claims about crisis_barrier.
    A peer cannot exempt their data from this check.

    This is the receiving-side mirror of the absolute barrier on can_share().
    Both sides must enforce the barrier independently.
    """
    return any(_contains_crisis(s) for s in _walk_strings(data))


def _walk_strings(data: Any) -> Generator[str, None, None]:
    """
    Recursively yield all string values from a nested structure.
    Handles dict, list, and scalar values.
    Skips None and non-string scalars.
    Never raises.
    """
    if isinstance(data, str):
        yield data
    elif isinstance(data, dict):
        for value in data.values():
            yield from _walk_strings(value)
    elif isinstance(data, (list, tuple)):
        for item in data:
            yield from _walk_strings(item)
    # All other types (int, float, bool, None, etc.) are skipped


# ---------------------------------------------------------------------------
# CONFIGURABLE SAFETY CHECKS — Tier 2
# These checks respect the configuration from api/federation/config.py.
# Their defaults are maximally restrictive.
# ---------------------------------------------------------------------------

def check_outbound(
    text: str,
    classification: int,
    is_sensitive: bool,
    is_crisis: bool,
    peer_trust_score: float,
    peer_data_residency: str,
    consent_id: str,
    has_valid_consent: bool,
) -> Tuple[bool, str]:
    """
    Full outbound safety check for a single piece of data.

    Runs absolute barriers first, then configurable controls.
    Returns (allowed, reason) — first failure wins.

    Arguments:
        text:               Raw text for crisis detection.
        classification:     Data classification level (0-5).
        is_sensitive:       Whether content is marked sensitive.
        is_crisis:          Pre-computed crisis flag.
        peer_trust_score:   Current trust score for the receiving peer.
        peer_data_residency: ISO country code(s) the peer may hold data in.
        consent_id:         UUID of the consent record authorizing this share.
        has_valid_consent:  Whether a valid, active consent record exists.
    """
    from api.federation import config

    # --- Tier 1: Absolute barriers (no configuration) ---
    allowed, reason = check_absolute_barriers(text, classification, is_crisis)
    if not allowed:
        return False, reason

    # --- Tier 2: Configurable controls ---

    # Consent is always required — enforced at protocol level
    if not has_valid_consent:
        return False, f"no valid consent record for consent_id '{consent_id}'"

    # Classification ceiling
    if classification > config.MAX_SHARE_CLASSIFICATION:
        return (
            False,
            f"classification {classification} exceeds "
            f"ONTO_FED_MAX_SHARE_CLASSIFICATION "
            f"({config.MAX_SHARE_CLASSIFICATION})",
        )

    # Sensitive content trust threshold
    if is_sensitive and peer_trust_score < config.SENSITIVE_TRUST_THRESHOLD:
        return (
            False,
            f"sensitive content requires peer trust_score >= "
            f"{config.SENSITIVE_TRUST_THRESHOLD}, "
            f"peer has {peer_trust_score:.2f}",
        )

    # Data residency
    if config.DATA_RESIDENCY:
        peer_regions = frozenset(
            r.strip().upper()
            for r in peer_data_residency.split(",")
            if r.strip()
        )
        if not peer_regions.issubset(config.DATA_RESIDENCY):
            disallowed = peer_regions - config.DATA_RESIDENCY
            return (
                False,
                f"peer data_residency includes regions not permitted "
                f"by ONTO_FED_DATA_RESIDENCY: {sorted(disallowed)}",
            )

    return True, "passed"


def check_inbound(
    data: Dict[str, Any],
    peer_trust_score: float,
) -> Tuple[bool, float]:
    """
    Full inbound safety check for a received payload.

    Returns (allowed, assigned_trust_score).

    The assigned_trust_score is always the configured inbound trust floor —
    the sender's claimed trust score is ignored entirely. Trust must be
    earned locally through interaction, not asserted remotely.

    If crisis content is found in the payload:
      - Returns (False, 0.0)
      - Caller must trigger onto_checkpoint for operator decision

    Arguments:
        data:             The received payload dict.
        peer_trust_score: The peer's current local trust score (for logging).
                          Not used to gate the decision — only the floor matters.
    """
    from api.federation import config

    # Absolute barrier: crisis content in inbound payload
    if check_inbound_for_crisis(data):
        return False, 0.0

    # All inbound data receives the configured floor trust score.
    # Never higher, regardless of sender claims.
    assigned = min(config.INBOUND_TRUST, peer_trust_score)

    return True, assigned


# ---------------------------------------------------------------------------
# SAFETY AUDIT HELPERS
# ---------------------------------------------------------------------------

def describe_barrier_failure(reason: str) -> str:
    """
    Return a human-readable description of a barrier failure suitable for
    audit trail notes and operator notifications.
    """
    prefixes = {
        "crisis content never federates": (
            "SAFETY: Crisis content blocked from crossing node boundary. "
            "Crisis content never federates under any configuration."
        ),
        "classification": (
            "SAFETY: Sensitive data blocked from crossing node boundary. "
            "PHI and privileged data (classification 4+) never federates."
        ),
    }
    for key, description in prefixes.items():
        if reason.startswith(key):
            return description
    return f"Federation blocked: {reason}"
