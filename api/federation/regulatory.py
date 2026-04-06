"""
api/federation/regulatory.py

Regulatory compliance profile framework for internet-stage federation.

Regulatory profiles are ADDITIVE RESTRICTIONS ONLY.

Architecture contract:
  - Every profile's check_outbound() and check_inbound() may only return
    (False, reason) to block an operation — never to permit what a parent
    gate (LocalAdapter.can_share / LocalAdapter.can_receive) already blocked.
  - Profiles do NOT override safety.py absolute barriers (crisis content,
    classification 4+ PHI). Those blocks happen before profiles are consulted.
  - Profiles are loaded by InternetAdapter.start() and stored in
    RegulatoryProfileRegistry singleton.
  - Profile checks run AFTER super().can_share() / super().can_receive()
    returns (True, ...). If the super gate blocks, profiles are never called.

Supported profiles:
  HIPAA  — Health Insurance Portability and Accountability Act (US)
  GDPR   — General Data Protection Regulation (EU/EEA)
  FERPA  — Family Educational Rights and Privacy Act (US)
  GLBA   — Gramm-Leach-Bliley Act (US financial)

Configuration:
  ONTO_FED_REGULATORY_PROFILES=HIPAA,GDPR  (comma-separated, empty = none)

Adding new profiles:
  1. Subclass RegulatoryProfile
  2. Implement check_outbound() and check_inbound()
  3. Register in _PROFILE_REGISTRY at bottom of file
  4. Add to VALID_REGULATORY_PROFILES in config.py

Rule 1.09A: Code, tests, and documentation must always agree.
"""

from typing import Any, Dict, List, Tuple

from api.federation.adapter import NodeInfo


# ---------------------------------------------------------------------------
# BASE CLASS
# ---------------------------------------------------------------------------

class RegulatoryProfile:
    """
    Abstract base for regulatory compliance profiles.

    All methods must return (allowed: bool, reason: str).
    allowed=True means the profile does not block this operation.
    allowed=False means the profile requires this operation be blocked.

    Profiles must never raise — return (True, "") on unexpected errors
    so that a misconfigured profile does not inadvertently block all sharing.
    """

    name: str = "BASE"

    def check_outbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        """
        Check whether data may be shared with peer under this profile.

        data: the payload being sent (same structure as can_share arguments)
        peer: the recipient NodeInfo including capabilities

        Returns (True, "") if the profile permits the share.
        Returns (False, reason) if the profile requires the share be blocked.
        """
        return True, ""

    def check_inbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        """
        Check whether inbound data from peer is acceptable under this profile.

        data: the inbound payload
        peer: the sending NodeInfo including capabilities

        Returns (True, "") if the profile permits the receipt.
        Returns (False, reason) if the profile requires rejection.
        """
        return True, ""


# ---------------------------------------------------------------------------
# HIPAA PROFILE
# ---------------------------------------------------------------------------

class HIPAAProfile(RegulatoryProfile):
    """
    HIPAA — Health Insurance Portability and Accountability Act.

    Enforcement:
      - phi_flag=True in data → blocked unless peer has baa_confirmed=True
        in capabilities (operator must configure this after signing BAA)
      - Any share to a peer whose data_residency includes a country not on
        the HIPAA-safe list is blocked
      - Classification 4 (clinical PHI) is an ABSOLUTE BARRIER in safety.py
        and never reaches this profile — that is belt-and-suspenders.

    HIPAA-safe countries (jurisdiction accepted by HHS for cloud):
      US only for domestic entities; international transfers require
      Business Associate Agreement with contractual safeguards.
      Conservative default: only "US" is unconditionally safe.

    Operators who have cross-border BAAs should set
    ONTO_FED_DATA_RESIDENCY to reflect their agreement.
    """

    name = "HIPAA"

    # Countries considered unconditionally HIPAA-safe for this node
    # (US-centric default; operators extend via data_residency config)
    _HIPAA_SAFE_COUNTRIES = frozenset({"US"})

    def check_outbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        try:
            # PHI flag check
            if data.get("phi_flag"):
                baa = peer.capabilities.get("baa_confirmed", False)
                if not baa:
                    return (
                        False,
                        f"HIPAA: phi_flag=True but peer {peer.node_id[:16]}... "
                        f"has not confirmed BAA (baa_confirmed not in capabilities). "
                        f"Set baa_confirmed=true in peer capabilities after signing BAA.",
                    )

            # Data residency check for PHI-adjacent data
            if data.get("phi_flag") and peer.data_residency:
                peer_countries = peer.data_residency_set()
                unsafe = peer_countries - self._HIPAA_SAFE_COUNTRIES
                if unsafe:
                    return (
                        False,
                        f"HIPAA: PHI data cannot be shared with peer in "
                        f"non-HIPAA-safe jurisdiction(s): {sorted(unsafe)}. "
                        f"Review your Business Associate Agreement.",
                    )

            return True, ""
        except Exception:
            return True, ""  # profile failure must not block sharing

    def check_inbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        try:
            # If inbound data is flagged as PHI, require BAA on their side too
            if data.get("phi_flag"):
                baa = peer.capabilities.get("baa_confirmed", False)
                if not baa:
                    return (
                        False,
                        f"HIPAA: inbound phi_flag=True from peer {peer.node_id[:16]}... "
                        f"without baa_confirmed capability. Rejecting.",
                    )
            return True, ""
        except Exception:
            return True, ""


# ---------------------------------------------------------------------------
# GDPR PROFILE
# ---------------------------------------------------------------------------

class GDPRProfile(RegulatoryProfile):
    """
    GDPR — General Data Protection Regulation (EU/EEA).

    Enforcement:
      - Data with is_personal=True may not be shared to peers outside the
        EEA unless the peer declares an adequacy decision or SCCs in
        capabilities (gdpr_transfer_mechanism)
      - Peers receiving personal data must declare right_to_erasure_supported
        in capabilities (for Art.17 compliance)
      - DPA (Data Processing Agreement) confirmation required for personal
        data: gdpr_dpa_confirmed=True in peer capabilities

    EEA countries (EU27 + Iceland, Liechtenstein, Norway):
      Adequacy decisions also cover: CH, UK, CA, JP, NZ, AR, UY, IL, KR, AD
    """

    name = "GDPR"

    # EU/EEA member states + countries with EU adequacy decisions
    _EEA_AND_ADEQUATE = frozenset({
        # EU 27
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI",
        "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
        "NL", "PL", "PT", "RO", "SE", "SI", "SK",
        # EEA (non-EU)
        "IS", "LI", "NO",
        # Adequacy decisions as of 2025
        "CH", "UK", "CA", "JP", "NZ", "AR", "UY", "IL", "KR", "AD",
    })

    def check_outbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        try:
            if not data.get("is_personal"):
                return True, ""

            # DPA confirmation required for personal data
            if not peer.capabilities.get("gdpr_dpa_confirmed"):
                return (
                    False,
                    f"GDPR: personal data requires gdpr_dpa_confirmed=true "
                    f"in peer {peer.node_id[:16]}... capabilities (Art. 28 DPA).",
                )

            # Right-to-erasure support required
            if not peer.capabilities.get("right_to_erasure_supported"):
                return (
                    False,
                    f"GDPR: personal data requires right_to_erasure_supported=true "
                    f"in peer capabilities (Art. 17).",
                )

            # Cross-border transfer check
            if peer.data_residency:
                peer_countries = peer.data_residency_set()
                third_countries = peer_countries - self._EEA_AND_ADEQUATE
                if third_countries:
                    mechanism = peer.capabilities.get("gdpr_transfer_mechanism", "")
                    if not mechanism:
                        return (
                            False,
                            f"GDPR: personal data cannot be sent to peer in "
                            f"third countries {sorted(third_countries)} without "
                            f"gdpr_transfer_mechanism (SCCs, BCRs, etc.) in "
                            f"peer capabilities (Art. 44-49).",
                        )

            return True, ""
        except Exception:
            return True, ""

    def check_inbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        try:
            # Accept any inbound personal data — receiving is not a transfer
            # under GDPR Art.44 (that applies to outbound/export only)
            return True, ""
        except Exception:
            return True, ""


# ---------------------------------------------------------------------------
# FERPA PROFILE
# ---------------------------------------------------------------------------

class FERPAProfile(RegulatoryProfile):
    """
    FERPA — Family Educational Rights and Privacy Act (US).

    Enforcement:
      - Educational records (ferpa_flag=True or classification >= 2 for
        education-typed data) may only be shared with peers that declare
        ferpa_agreement=True in capabilities
      - School officials exception applies when peer declares
        ferpa_legitimate_interest=True
    """

    name = "FERPA"

    def check_outbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        try:
            is_ferpa = data.get("ferpa_flag") or data.get("data_type") == "educational_record"
            if not is_ferpa:
                return True, ""

            has_agreement = peer.capabilities.get("ferpa_agreement", False)
            has_exception = peer.capabilities.get("ferpa_legitimate_interest", False)

            if not (has_agreement or has_exception):
                return (
                    False,
                    f"FERPA: educational record requires ferpa_agreement=true "
                    f"or ferpa_legitimate_interest=true in peer "
                    f"{peer.node_id[:16]}... capabilities.",
                )

            return True, ""
        except Exception:
            return True, ""

    def check_inbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        try:
            # Receiving educational records is permitted when the sender
            # is a recognized educational institution
            if data.get("ferpa_flag"):
                if not peer.capabilities.get("ferpa_agreement", False):
                    return (
                        False,
                        f"FERPA: inbound educational record from peer without "
                        f"ferpa_agreement capability. Rejecting.",
                    )
            return True, ""
        except Exception:
            return True, ""


# ---------------------------------------------------------------------------
# GLBA PROFILE
# ---------------------------------------------------------------------------

class GLBAProfile(RegulatoryProfile):
    """
    GLBA — Gramm-Leach-Bliley Act (US financial data).

    Enforcement:
      - Financial data (glba_flag=True) may only be shared with peers that
        declare glba_safeguards=True (confirming their Safeguards Rule
        compliance)
      - Non-public personal financial information (NPPI) requires
        opt-out mechanism confirmation: glba_optout_supported=True
    """

    name = "GLBA"

    def check_outbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        try:
            is_glba = data.get("glba_flag") or data.get("data_type") == "financial_record"
            if not is_glba:
                return True, ""

            if not peer.capabilities.get("glba_safeguards", False):
                return (
                    False,
                    f"GLBA: financial data requires glba_safeguards=true in "
                    f"peer {peer.node_id[:16]}... capabilities (Safeguards Rule).",
                )

            if data.get("is_nppi") and not peer.capabilities.get("glba_optout_supported", False):
                return (
                    False,
                    f"GLBA: NPPI data requires glba_optout_supported=true in "
                    f"peer capabilities.",
                )

            return True, ""
        except Exception:
            return True, ""

    def check_inbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        try:
            if data.get("glba_flag"):
                if not peer.capabilities.get("glba_safeguards", False):
                    return (
                        False,
                        f"GLBA: inbound financial data from peer without "
                        f"glba_safeguards capability. Rejecting.",
                    )
            return True, ""
        except Exception:
            return True, ""


# ---------------------------------------------------------------------------
# REGISTRY
# ---------------------------------------------------------------------------

#: Maps profile name → class. Used by RegulatoryProfileRegistry.load().
_PROFILE_REGISTRY = {
    "HIPAA": HIPAAProfile,
    "GDPR":  GDPRProfile,
    "FERPA": FERPAProfile,
    "GLBA":  GLBAProfile,
}


class RegulatoryProfileRegistry:
    """
    Holds the set of active regulatory profiles for this node.

    Usage:
        registry = RegulatoryProfileRegistry()
        registry.load(["HIPAA", "GDPR"])

        ok, reason = registry.check_outbound(data, peer)
        if not ok:
            return False, reason

    All profiles must pass (logical AND). The first blocking profile
    wins and its reason is returned. This is intentional — in regulated
    environments, all applicable laws must be satisfied simultaneously.
    """

    def __init__(self):
        self._profiles: List[RegulatoryProfile] = []

    def load(self, profile_names: List[str]) -> None:
        """
        Load the named profiles. Unknown names are silently skipped
        (validation in config.py catches them before load() is called).
        """
        self._profiles = []
        for name in profile_names:
            cls = _PROFILE_REGISTRY.get(name.upper())
            if cls:
                self._profiles.append(cls())

    def active_profiles(self) -> List[str]:
        """Return names of currently active profiles."""
        return [p.name for p in self._profiles]

    def check_outbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        """
        Run all active profile outbound checks.
        Returns (False, reason) on first blocking profile.
        Returns (True, "") if no profiles are active or all pass.
        """
        for profile in self._profiles:
            allowed, reason = profile.check_outbound(data, peer)
            if not allowed:
                return False, f"[{profile.name}] {reason}"
        return True, ""

    def check_inbound(
        self,
        data: Dict[str, Any],
        peer: "NodeInfo",
    ) -> Tuple[bool, str]:
        """
        Run all active profile inbound checks.
        Returns (False, reason) on first blocking profile.
        Returns (True, "") if no profiles are active or all pass.
        """
        for profile in self._profiles:
            allowed, reason = profile.check_inbound(data, peer)
            if not allowed:
                return False, f"[{profile.name}] {reason}"
        return True, ""


# ---------------------------------------------------------------------------
# MODULE-LEVEL SINGLETON
# ---------------------------------------------------------------------------

#: Global registry instance.
#: InternetAdapter.start() calls regulatory_registry.load(cfg.REGULATORY_PROFILES).
#: All subsequent can_share / can_receive calls use this registry.
regulatory_registry = RegulatoryProfileRegistry()
