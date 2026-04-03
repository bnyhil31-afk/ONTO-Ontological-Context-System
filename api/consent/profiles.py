"""
api/consent/profiles.py

Regulatory profile definitions for the consent ledger.

Three built-in profiles: team, healthcare, financial.
Operators can define custom profiles by subclassing RegulatoryProfile.

Each profile specifies:
  - Required consent record fields
  - Consent granularity (per-session / per-purpose / per-authorization)
  - Default re-confirmation interval
  - Default retention period (days; 0 = indefinite)
  - Maximum delegation depth
  - Revocation mechanism (electronic / written)
  - Whether VC fields are required (Phase 5 activation)
  - GLBA opt-out support (financial only)
  - HIPAA required elements (healthcare only)

Rule 1.09A: Code, tests, and documentation must always agree.
"""

from dataclasses import dataclass, field
from typing import FrozenSet, List

# ---------------------------------------------------------------------------
# PROFILE BASE CLASS
# ---------------------------------------------------------------------------


@dataclass
class RegulatoryProfile:
    """
    Base class for regulatory profiles.
    All fields have safe, minimal defaults matching the team profile.
    Subclasses override only what differs.
    """
    name: str = "team"
    display_name: str = "Team"
    description: str = "2-50 people, low regulation"

    # Consent granularity
    # "per-session"       — one consent per session per purpose
    # "per-purpose"       — one consent per purpose (may span sessions)
    # "per-authorization" — one consent per individual operation (HIPAA)
    granularity: str = "per-purpose"

    # Friction level presented to the operator
    # "low"    — JIT prompting, background consent where possible
    # "medium" — explicit per-purpose prompting
    # "high"   — explicit per-operation prompting (HIPAA)
    friction: str = "low"

    # Re-confirmation interval for standing consents (days)
    reconfirm_days: int = 90

    # Default retention period (days; 0 = indefinite)
    retention_days: int = 0

    # Maximum delegation chain depth
    delegation_max_depth: int = 3

    # Revocation mechanism
    # "electronic" — GDPR compliant (default)
    # "written"    — HIPAA §164.508(b)(5) compliant
    revocation_mechanism: str = "electronic"

    # Whether W3C VC fields are required when Phase 5 activates
    vc_required: bool = False

    # GLBA opt-out model (financial only)
    # When True: consent gate inverts — permitted until opt-out record found
    glba_opt_out_model: bool = False

    # Required fields beyond the base schema
    required_fields: FrozenSet[str] = frozenset({
        "consent_id", "subject_id", "grantor_id", "requester_id",
        "purpose", "legal_basis", "operations", "granted_at",
    })

    # Valid legal basis values for this profile
    valid_legal_bases: FrozenSet[str] = frozenset({
        "gdpr:consent-art6-1a",
        "gdpr:legitimate-interest-art6-1f",
        "legitimate-use",
    })

    # Immutable retention lock: records with these legal bases
    # cannot be erased during the retention period
    retention_locked_bases: FrozenSet[str] = frozenset()

    def validate_record(self, record: dict) -> List[str]:
        """
        Validate a consent record against this profile's requirements.
        Returns a list of error strings. Empty = valid.
        """
        errors = []
        for f in self.required_fields:
            if not record.get(f):
                errors.append(f"Required field missing: {f}")
        lb = record.get("legal_basis", "")
        if lb and lb not in self.valid_legal_bases:
            errors.append(
                f"Legal basis '{lb}' not valid for profile '{self.name}'. "
                f"Valid: {sorted(self.valid_legal_bases)}"
            )
        return errors

    def is_retention_locked(self, record: dict) -> bool:
        """
        True if this record cannot be erased during the retention period.
        Applies to financial/legal-obligation records.
        """
        return record.get("legal_basis", "") in self.retention_locked_bases


# ---------------------------------------------------------------------------
# TEAM PROFILE
# ---------------------------------------------------------------------------


@dataclass
class TeamProfile(RegulatoryProfile):
    """
    Team profile: 2-50 people, informal or low-regulation deployment.

    GDPR minimum compliance. JIT consent. Electronic revocation.
    Indefinite retention by default. Delegation up to 3 hops.
    """
    name: str = "team"
    display_name: str = "Team"
    description: str = "2-50 people, informal or low-regulation deployment"
    granularity: str = "per-purpose"
    friction: str = "low"
    reconfirm_days: int = 90
    retention_days: int = 0
    delegation_max_depth: int = 3
    revocation_mechanism: str = "electronic"
    vc_required: bool = False
    glba_opt_out_model: bool = False
    valid_legal_bases: FrozenSet[str] = frozenset({
        "gdpr:consent-art6-1a",
        "gdpr:legitimate-interest-art6-1f",
        "legitimate-use",
    })


# ---------------------------------------------------------------------------
# HEALTHCARE PROFILE
# ---------------------------------------------------------------------------


@dataclass
class HealthcareProfile(RegulatoryProfile):
    """
    Healthcare profile: HIPAA-covered entities, clinical research.

    Implements HIPAA 45 CFR §164.508 authorization requirements.
    Per-authorization granularity. Written revocation. 6-year retention.
    Named parties (subject_id and requester_id are not hashed).
    Delegation depth 1 (named parties only).
    """
    name: str = "healthcare"
    display_name: str = "Healthcare (HIPAA)"
    description: str = "HIPAA-covered entities, clinical research"
    granularity: str = "per-authorization"
    friction: str = "high"
    reconfirm_days: int = 365   # re-authorization per use, not time-based
    retention_days: int = 2190  # 6 years
    delegation_max_depth: int = 1
    revocation_mechanism: str = "written"
    vc_required: bool = False   # True when Phase 5 activates
    glba_opt_out_model: bool = False
    required_fields: FrozenSet[str] = frozenset({
        # Base fields
        "consent_id", "subject_id", "grantor_id", "requester_id",
        "purpose", "legal_basis", "operations", "granted_at",
        # HIPAA §164.508 required elements
        "hipaa_phi_description",      # specific PHI description
        "hipaa_expiry_event",          # expiry by date OR event
        "hipaa_conditioning",          # conditioning statement
        "hipaa_redisclosure",          # redisclosure warning
        "valid_until",                 # HIPAA requires explicit expiry
    })
    valid_legal_bases: FrozenSet[str] = frozenset({
        "hipaa:authorization-164-508",
        "hipaa:treatment",
        "hipaa:operations",
        "hipaa:payment",
    })

    def validate_record(self, record: dict) -> List[str]:
        errors = super().validate_record(record)
        # HIPAA requires either valid_until OR hipaa_expiry_event (not both null)
        if not record.get("valid_until") and not record.get("hipaa_expiry_event"):
            errors.append(
                "HIPAA authorization requires either valid_until (date) "
                "or hipaa_expiry_event (event description). Both are null."
            )
        return errors


# ---------------------------------------------------------------------------
# FINANCIAL PROFILE
# ---------------------------------------------------------------------------


@dataclass
class FinancialProfile(RegulatoryProfile):
    """
    Financial profile: SEC-registered entities, GLBA-covered institutions,
    MiFID II-subject firms.

    GLBA opt-out model. SEC 17a-4 / MiFID II retention (7 years).
    Retention lock on legal-obligation basis records.
    Privilege tagging supported.
    Annual re-confirmation for standing consents.
    """
    name: str = "financial"
    display_name: str = "Financial / Legal"
    description: str = "SEC, GLBA, MiFID II regulated contexts"
    granularity: str = "per-purpose"
    friction: str = "medium"
    reconfirm_days: int = 365   # annual
    retention_days: int = 2555  # 7 years (SEC 17a-4)
    delegation_max_depth: int = 1
    revocation_mechanism: str = "electronic"
    vc_required: bool = False   # True when Phase 5 activates
    glba_opt_out_model: bool = True
    required_fields: FrozenSet[str] = frozenset({
        "consent_id", "subject_id", "grantor_id", "requester_id",
        "purpose", "legal_basis", "operations", "granted_at",
    })
    valid_legal_bases: FrozenSet[str] = frozenset({
        "gdpr:consent-art6-1a",
        "gdpr:legal-obligation-art6-1c",  # SEC / MiFID II retention
        "glba:opt-out",
        "legitimate-use",
    })
    retention_locked_bases: FrozenSet[str] = frozenset({
        "gdpr:legal-obligation-art6-1c",  # Cannot erase during retention period
    })


# ---------------------------------------------------------------------------
# PROFILE REGISTRY
# ---------------------------------------------------------------------------

_PROFILES = {
    "team":        TeamProfile(),
    "healthcare":  HealthcareProfile(),
    "financial":   FinancialProfile(),
}


def get_profile(name: str) -> RegulatoryProfile:
    """
    Return the regulatory profile for the given name.
    Falls back to TeamProfile for unknown names (with a warning).
    """
    profile = _PROFILES.get(name)
    if profile is None:
        import warnings
        warnings.warn(
            f"Unknown regulatory profile '{name}'. Using 'team' profile. "
            f"Valid profiles: {sorted(_PROFILES.keys())}",
            stacklevel=2,
        )
        return _PROFILES["team"]
    return profile


def get_active_profile() -> RegulatoryProfile:
    """Return the profile currently configured by ONTO_CONSENT_PROFILE."""
    from api.consent import config as _cfg
    return get_profile(_cfg.CONSENT_PROFILE)


def list_profiles() -> dict:
    """Return a summary of all available profiles."""
    return {
        name: {
            "display_name":      p.display_name,
            "description":       p.description,
            "granularity":       p.granularity,
            "friction":          p.friction,
            "retention_days":    p.retention_days or "indefinite",
            "revocation":        p.revocation_mechanism,
            "delegation_depth":  p.delegation_max_depth,
        }
        for name, p in _PROFILES.items()
    }
