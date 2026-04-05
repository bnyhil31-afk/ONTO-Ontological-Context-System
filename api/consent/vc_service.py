"""
api/consent/vc_service.py

VCService protocol — W3C VC 2.0 issuance and verification interface.

Phase 4: NullVCService is the only implementation.
         All methods return None/False/empty.
         The interface is defined now so the rest of the system
         is built to the interface — not to the implementation.

Phase 5: Either a native Python VC 2.0 library (if one becomes
         available) or a Rust/Go sidecar via HTTP API activates.
         Nothing upstream changes. The sidecar exposes:
           POST /vc/issue
           POST /vc/verify
           POST /vc/revoke
           GET  /vc/status/{consent_id}

The watch movement principle: define the interface, build to it,
activate the component when it's ready.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import json
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable


# ---------------------------------------------------------------------------
# VCSERVICE PROTOCOL
# ---------------------------------------------------------------------------

@runtime_checkable
class VCService(Protocol):
    """
    Cryptographic VC 2.0 operations for consent records.

    Phase 4: not implemented. NullVCService returns safe no-ops.
    Phase 5: sidecar or native Python implementation activates.
    """

    def issue_vc(
        self,
        consent_record: Dict,
        fmt: str = "data-integrity",
    ) -> Optional[Dict]:
        """
        Issue a W3C VC 2.0 for a consent record.

        fmt="data-integrity" → DataIntegrityProof + eddsa-rdfc-2022
        fmt="sd-jwt"         → SD-JWT VC (EUDIW-compatible)

        Returns the signed VC dict, or None if VCService not active.
        """
        ...

    def verify_vc(self, vc: Dict) -> Tuple[bool, str]:
        """
        Verify a VC's cryptographic proof and revocation status.
        Returns (valid: bool, reason: str).
        Returns (False, "vc_service_not_active") in Phase 4.
        """
        ...

    def revoke_vc(
        self,
        consent_id: str,
        status_list_index: int,
    ) -> bool:
        """
        Flip the revocation bit in the Bitstring Status List.
        Returns False in Phase 4 (status list not active).
        """
        ...

    def create_presentation_definition(
        self,
        required_purpose: str,
        required_operations: List[str],
    ) -> Dict:
        """
        Create a DIF Presentation Definition for consent verification.
        Used when ONTO acts as a verifier (Phase 5+).
        Returns {} in Phase 4.
        """
        ...


# ---------------------------------------------------------------------------
# NULL VCSERVICE (Phase 4 no-op implementation)
# ---------------------------------------------------------------------------

class NullVCService:
    """
    Phase 4 implementation. All methods return safe no-ops.
    Activated when ONTO_VC_SERVICE_ENABLED=false (default in Phase 4).

    The system functions correctly without VC cryptographic proofs.
    Consent records are valid and enforced — they just lack external
    cryptographic verifiability until Phase 5.
    """

    def issue_vc(
        self,
        consent_record: Dict,
        fmt: str = "data-integrity",
    ) -> Optional[Dict]:
        """Phase 4: VCService not active. Returns None."""
        return None

    def verify_vc(self, vc: Dict) -> Tuple[bool, str]:
        """Phase 4: VCService not active. Returns (False, reason)."""
        return False, "vc_service_not_active"

    def revoke_vc(
        self,
        consent_id: str,
        status_list_index: int,
    ) -> bool:
        """Phase 4: Bitstring Status List not active. Returns False."""
        return False

    def create_presentation_definition(
        self,
        required_purpose: str,
        required_operations: List[str],
    ) -> Dict:
        """Phase 4: Presentation Exchange not active. Returns {}."""
        return {}

    def is_active(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# HTTP VCSERVICE (Phase 5 sidecar implementation)
# ---------------------------------------------------------------------------

class HttpVCService:
    """
    Phase 5 implementation: calls a Rust/Go sidecar via HTTP API.

    Sidecar endpoints:
      POST /vc/issue   — issue a signed VC
      POST /vc/verify  — verify a VC's proof
      POST /vc/revoke  — update Bitstring Status List
      GET  /vc/status/{consent_id} — check revocation status

    Activated when ONTO_VC_SERVICE_ENABLED=true.
    URL configured via ONTO_VC_SERVICE_URL (default: http://127.0.0.1:7800).
    Timeout configured via ONTO_VC_SERVICE_TIMEOUT_SECS (default: 5).
    """

    def __init__(self, base_url: str, timeout_secs: int = 5):
        self._base = base_url.rstrip("/")
        self._timeout = timeout_secs

    def issue_vc(
        self,
        consent_record: Dict,
        fmt: str = "data-integrity",
    ) -> Optional[Dict]:
        try:
            return self._post("/vc/issue", {
                "record": consent_record,
                "format": fmt,
            })
        except Exception:
            return None

    def verify_vc(self, vc: Dict) -> Tuple[bool, str]:
        try:
            result = self._post("/vc/verify", {"vc": vc})
            return result.get("valid", False), result.get("reason", "")
        except Exception as exc:
            return False, str(exc)

    def revoke_vc(
        self,
        consent_id: str,
        status_list_index: int,
    ) -> bool:
        try:
            result = self._post("/vc/revoke", {
                "consent_id": consent_id,
                "status_list_index": status_list_index,
            })
            return bool(result.get("revoked"))
        except Exception:
            return False

    def create_presentation_definition(
        self,
        required_purpose: str,
        required_operations: List[str],
    ) -> Dict:
        try:
            return self._post("/vc/presentation-definition", {
                "required_purpose": required_purpose,
                "required_operations": required_operations,
            })
        except Exception:
            return {}

    def is_active(self) -> bool:
        """Ping the sidecar to confirm it is reachable."""
        try:
            req = urllib.request.Request(
                f"{self._base}/health",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec B310
                return resp.status == 200
        except Exception:
            return False

    def _post(self, path: str, payload: Dict) -> Dict:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self._base}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec B310
            return json.loads(resp.read())


# ---------------------------------------------------------------------------
# FACTORY
# ---------------------------------------------------------------------------

def get_vc_service() -> VCService:
    """
    Return the appropriate VCService for the current configuration.

    Phase 4: always returns NullVCService.
    Phase 5: returns HttpVCService when ONTO_VC_SERVICE_ENABLED=true.
    """
    from api.consent import config as _cfg
    if _cfg.VC_SERVICE_ENABLED:
        return HttpVCService(
            base_url=_cfg.VC_SERVICE_URL,
            timeout_secs=_cfg.VC_SERVICE_TIMEOUT_SECS,
        )
    return NullVCService()
