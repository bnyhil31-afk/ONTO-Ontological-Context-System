"""
api/consent/adapter.py

ConsentAdapter protocol — the single swap point for all consent behavior.

Same pattern as FederationAdapter in api/federation/adapter.py.
Any change to regulatory requirements, jurisdiction, or VC format
is addressed by wrapping or replacing the adapter.
The rest of the codebase never changes.

ConsentDecision is the universal return type for all gate decisions.
ConsentRecord is the canonical consent record dataclass.
ConsentRequest represents a pending consent request awaiting human approval.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# CONSENT DECISION
# ---------------------------------------------------------------------------

@dataclass
class ConsentDecision:
    """
    The result of a consent gate evaluation.

    Returned by ConsentGate.decide() and ConsentAdapter.check().
    All callers must handle requires_checkpoint=True by surfacing
    an onto_checkpoint before retrying the operation.
    """
    allowed: bool
    consent_id: Optional[str] = None    # UUID of the authorizing record
    reason: str = ""                     # always populated; human-readable
    requires_checkpoint: bool = False    # True → surface onto_checkpoint
    audit_id: Optional[int] = None      # audit trail record ID

    def __bool__(self) -> bool:
        return self.allowed


# ---------------------------------------------------------------------------
# CONSENT RECORD
# ---------------------------------------------------------------------------

@dataclass
class ConsentRecord:
    """
    A single consent record. Maps 1:1 to a row in consent_ledger.

    Fields follow ISO/IEC 27560:2023 with W3C DPV vocabulary for purposes
    and legal bases. W3C VC 2.0 fields are present from day one — NULL
    until Phase 5 activates the VCService.
    """
    # Identity
    consent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: str = "1.0"

    # Parties
    subject_id: str = ""            # SHA-256(user identity) — or named for HIPAA
    grantor_id: str = ""            # who gave consent
    requester_id: str = ""          # who receives access
    operator_node_did: Optional[str] = None

    # Consent substance (ISO 27560 §6.3.3)
    purpose: str = "dpv:ServiceProvision"
    purpose_description: str = ""
    legal_basis: str = "legitimate-use"
    operations: List[str] = field(default_factory=lambda: ["read", "navigate"])
    classification_max: int = 2
    data_categories: Optional[List[str]] = None
    geographic_scope: Optional[str] = None

    # Temporal (ISO 27560 §6.3.4)
    granted_at: float = field(default_factory=time.time)
    valid_from: float = field(default_factory=time.time)
    valid_until: Optional[float] = None     # None = standing consent
    last_reconfirmed: Optional[float] = None

    # State
    status: str = "active"
    revoked_at: Optional[float] = None
    revocation_reason: Optional[str] = None
    revocation_type: Optional[str] = None  # 'electronic' | 'written'

    # HIPAA §164.508 required elements (healthcare profile)
    hipaa_phi_description: Optional[str] = None
    hipaa_expiry_event: Optional[str] = None
    hipaa_conditioning: Optional[str] = None
    hipaa_redisclosure: Optional[str] = None

    # Delegation chain
    delegated_from: Optional[str] = None   # parent consent_id
    delegation_depth: int = 0

    # Audit linkage
    chain_hash: Optional[str] = None
    govern_event_id: Optional[int] = None

    # W3C VC 2.0 fields (NULL in Phase 4; activated by VCService in Phase 5)
    vc_id: Optional[str] = None
    vc_issuer: Optional[str] = None
    vc_proof_type: Optional[str] = None
    vc_cryptosuite: Optional[str] = None
    vc_proof: Optional[str] = None
    vc_status_list_id: Optional[str] = None
    vc_status_list_idx: Optional[int] = None
    sd_jwt_token: Optional[str] = None

    def is_active(self) -> bool:
        """True if the record is currently valid and not expired."""
        if self.status != "active":
            return False
        if self.revoked_at is not None:
            return False
        if self.valid_until is not None and self.valid_until < time.time():
            return False
        return True

    def needs_reconfirmation(self, reconfirm_days: int = 90) -> bool:
        """
        True if this is a standing consent that has exceeded the
        re-confirmation interval.
        """
        if self.valid_until is not None:
            return False  # Timed consent — no re-confirmation needed
        if self.status != "active":
            return False
        if self.last_reconfirmed is None:
            return True
        days_elapsed = (time.time() - self.last_reconfirmed) / 86400.0
        return days_elapsed >= reconfirm_days

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (JSON-safe, no datetime objects)."""
        return {
            "consent_id":          self.consent_id,
            "schema_version":      self.schema_version,
            "subject_id":          self.subject_id,
            "grantor_id":          self.grantor_id,
            "requester_id":        self.requester_id,
            "operator_node_did":   self.operator_node_did,
            "purpose":             self.purpose,
            "purpose_description": self.purpose_description,
            "legal_basis":         self.legal_basis,
            "operations":          self.operations,
            "classification_max":  self.classification_max,
            "data_categories":     self.data_categories,
            "geographic_scope":    self.geographic_scope,
            "granted_at":          self.granted_at,
            "valid_from":          self.valid_from,
            "valid_until":         self.valid_until,
            "last_reconfirmed":    self.last_reconfirmed,
            "status":              self.status,
            "revoked_at":          self.revoked_at,
            "revocation_reason":   self.revocation_reason,
            "revocation_type":     self.revocation_type,
            "delegation_depth":    self.delegation_depth,
            "delegated_from":      self.delegated_from,
        }


# ---------------------------------------------------------------------------
# CONSENT REQUEST
# ---------------------------------------------------------------------------

@dataclass
class ConsentRequest:
    """
    A pending consent request awaiting human approval.

    Created when a gate check returns requires_checkpoint=True.
    Surfaced to the operator via onto_checkpoint.
    Resolved when the operator grants or denies.
    """
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subject_id: str = ""
    requester_id: str = ""
    purpose: str = ""
    purpose_description: str = ""
    classification: int = 0
    operation: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    context: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# CONSENT ADAPTER PROTOCOL
# ---------------------------------------------------------------------------

@runtime_checkable
class ConsentAdapter(Protocol):
    """
    The single swap point for all consent behavior.

    Implementations:
      Phase 4: SQLiteConsentAdapter (ledger.py)
      Future:  PostgreSQLConsentAdapter, RemoteConsentAdapter, etc.

    The adapter is the interface boundary. Callers only use this protocol.
    Storage, enforcement details, and VC operations are adapter concerns.
    """

    def check(
        self,
        subject_id: str,
        requester_id: str,
        purpose: str,
        classification: int,
        operation: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ConsentDecision:
        """
        Check whether an operation is consented to.
        Returns a ConsentDecision — never raises.

        If requires_checkpoint=True: caller must surface onto_checkpoint
        before retrying. The checkpoint result is the consent grant.
        """
        ...

    def grant(self, record: ConsentRecord) -> str:
        """
        Record a consent grant.
        Returns the consent_id of the new record.
        Writes a FEDERATION_CONSENT_GRANTED audit event.
        """
        ...

    def revoke(
        self,
        consent_id: str,
        reason: str,
        revocation_type: str = "electronic",
        revocation_statement: Optional[str] = None,
    ) -> bool:
        """
        Revoke a consent record. Terminal — cannot be undone.
        Cascades to delegated records (children of this consent_id).
        Returns True if revoked, False if not found or already revoked.
        Writes a CONSENT_REVOKED audit event.
        """
        ...

    def history(
        self,
        subject_id: str,
        include_revoked: bool = True,
    ) -> List[ConsentRecord]:
        """
        Return all consent records for a subject, newest first.
        The complete history is always available — revoked records
        are never deleted, only marked revoked.
        """
        ...

    def pending(
        self,
        subject_id: Optional[str] = None,
    ) -> List[ConsentRequest]:
        """
        Return pending consent requests awaiting human approval.
        If subject_id is None, returns all pending requests.
        """
        ...
