"""
api/consent/ledger.py

ConsentLedger — the SQLite implementation of ConsentAdapter.

Responsibilities:
  - grant()   — record a consent grant
  - check()   — evaluate whether an operation is consented to
  - revoke()  — revoke a consent (terminal; cascades to children)
  - history() — return all records for a subject
  - pending() — return pending consent requests

All writes use BEGIN IMMEDIATE transactions.
All reads use WAL mode (never blocks writers).
Consent records are permanent — revoked records are marked, not deleted.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from modules import memory as _memory
from api.consent.adapter import (
    ConsentAdapter, ConsentDecision, ConsentRecord, ConsentRequest
)
from api.consent.schema import initialize, _get_conn, to_jsonld
from api.consent.profiles import get_active_profile


# ---------------------------------------------------------------------------
# CONSENT LEDGER
# ---------------------------------------------------------------------------

class ConsentLedger:
    """
    SQLite-backed implementation of the ConsentAdapter protocol.

    Thread-safe: all writes use BEGIN IMMEDIATE.
    WAL mode: reads never block writes.
    Idempotent initialization: tables created on first call.
    """

    def __init__(self) -> None:
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            initialize()
            from api.consent.status_list import initialize as _sl_init
            _sl_init()
            self._initialized = True

    # ------------------------------------------------------------------
    # GRANT
    # ------------------------------------------------------------------

    def grant(self, record: ConsentRecord) -> str:
        """
        Record a consent grant. Returns the consent_id.
        Validates the record against the active regulatory profile.
        Assigns a Bitstring Status List index (Phase 4: allocated, not live).
        Writes a CONSENT_GRANTED audit event.
        """
        self._ensure_initialized()

        # Profile validation
        profile = get_active_profile()
        errors = profile.validate_record(record.to_dict())
        if errors:
            raise ValueError(
                f"Consent record invalid for profile '{profile.name}': "
                + "; ".join(errors)
            )

        # Standing consents: set last_reconfirmed = granted_at.
        # Granting a standing consent is itself a confirmation.
        # Without this, needs_reconfirmation() fires immediately on
        # every freshly granted standing consent (last_reconfirmed=None).
        if record.valid_until is None and record.last_reconfirmed is None:
            record.last_reconfirmed = record.granted_at

        # Allocate status list index (Phase 5 will use this)
        from api.consent.status_list import allocate_index
        record.vc_status_list_idx = allocate_index()

        # Serialize list fields
        ops_json = json.dumps(record.operations)
        cats_json = json.dumps(record.data_categories) if record.data_categories else None

        conn = _get_conn()
        try:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""
                    INSERT INTO consent_ledger (
                        consent_id, schema_version,
                        subject_id, grantor_id, requester_id, operator_node_did,
                        purpose, purpose_description, legal_basis,
                        operations, classification_max, data_categories,
                        geographic_scope,
                        granted_at, valid_from, valid_until, last_reconfirmed,
                        status, revoked_at, revocation_reason, revocation_type,
                        hipaa_phi_description, hipaa_expiry_event,
                        hipaa_conditioning, hipaa_redisclosure,
                        delegated_from, delegation_depth,
                        chain_hash, govern_event_id,
                        vc_id, vc_issuer, vc_proof_type, vc_cryptosuite,
                        vc_proof, vc_status_list_id, vc_status_list_idx,
                        sd_jwt_token
                    ) VALUES (
                        ?,?,  ?,?,?,?,  ?,?,?,  ?,?,?,  ?,
                        ?,?,?,?,  ?,?,?,?,
                        ?,?,  ?,?,  ?,?,  ?,?,
                        ?,?,?,?,  ?,?,?,  ?
                    )
                """, (
                    record.consent_id, record.schema_version,
                    record.subject_id, record.grantor_id,
                    record.requester_id, record.operator_node_did,
                    record.purpose, record.purpose_description,
                    record.legal_basis,
                    ops_json, record.classification_max, cats_json,
                    record.geographic_scope,
                    record.granted_at, record.valid_from,
                    record.valid_until, record.last_reconfirmed,
                    record.status, record.revoked_at,
                    record.revocation_reason, record.revocation_type,
                    record.hipaa_phi_description, record.hipaa_expiry_event,
                    record.hipaa_conditioning, record.hipaa_redisclosure,
                    record.delegated_from, record.delegation_depth,
                    record.chain_hash, record.govern_event_id,
                    record.vc_id, record.vc_issuer, record.vc_proof_type,
                    record.vc_cryptosuite, record.vc_proof,
                    record.vc_status_list_id, record.vc_status_list_idx,
                    record.sd_jwt_token,
                ))
        finally:
            conn.close()

        # Audit event
        try:
            _memory.record(
                event_type="CONSENT_GRANTED",
                notes=(
                    f"Consent granted: {record.consent_id}. "
                    f"Purpose: {record.purpose}. "
                    f"Subject: {record.subject_id[:8]}..."
                ),
                context={
                    "consent_id":  record.consent_id,
                    "purpose":     record.purpose,
                    "legal_basis": record.legal_basis,
                    "profile":     get_active_profile().name,
                },
            )
        except Exception:
            pass  # Audit failure must not abort the grant

        return record.consent_id

    # ------------------------------------------------------------------
    # CHECK
    # ------------------------------------------------------------------

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
        Never raises — returns a ConsentDecision with allowed=False on error.
        """
        self._ensure_initialized()

        try:
            return self._check_inner(
                subject_id, requester_id, purpose, classification, operation
            )
        except Exception as exc:
            return ConsentDecision(
                allowed=False,
                reason=f"Consent check error: {exc}",
                requires_checkpoint=False,
            )

    def _check_inner(
        self,
        subject_id: str,
        requester_id: str,
        purpose: str,
        classification: int,
        operation: str,
    ) -> ConsentDecision:
        profile = get_active_profile()

        # 1. Self-access: always permitted
        if subject_id == requester_id:
            return ConsentDecision(
                allowed=True,
                reason="self-access",
            )

        # 2. GLBA opt-out check (financial profile)
        if profile.glba_opt_out_model:
            if self._has_opt_out(subject_id, requester_id, purpose):
                return ConsentDecision(
                    allowed=False,
                    reason="glba-opt-out-active",
                )
            # No opt-out found → permitted under GLBA
            return ConsentDecision(
                allowed=True,
                reason="glba-opt-in-default",
            )

        # 3. Find an active consent record
        record = self._find_active(subject_id, requester_id, purpose)

        if record is None:
            # No consent record found → request human decision
            return ConsentDecision(
                allowed=False,
                reason="no-consent-record",
                requires_checkpoint=True,
            )

        # 4. Needs re-confirmation?
        if record.needs_reconfirmation(profile.reconfirm_days):
            return ConsentDecision(
                allowed=False,
                consent_id=record.consent_id,
                reason="standing-consent-requires-reconfirmation",
                requires_checkpoint=True,
            )

        # 5. Operation permitted?
        if operation not in record.operations:
            return ConsentDecision(
                allowed=False,
                consent_id=record.consent_id,
                reason=f"operation-not-permitted: {operation}",
                requires_checkpoint=True,
            )

        # 6. Classification ceiling
        if classification > record.classification_max:
            return ConsentDecision(
                allowed=False,
                consent_id=record.consent_id,
                reason=f"classification-{classification}-exceeds-consent-ceiling-{record.classification_max}",
            )

        return ConsentDecision(
            allowed=True,
            consent_id=record.consent_id,
            reason="active-consent-found",
        )

    # ------------------------------------------------------------------
    # REVOKE
    # ------------------------------------------------------------------

    def revoke(
        self,
        consent_id: str,
        reason: str,
        revocation_type: str = "electronic",
        revocation_statement: Optional[str] = None,
    ) -> bool:
        """
        Revoke a consent record. Terminal. Cascades to delegated children.
        """
        self._ensure_initialized()
        now = time.time()

        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT status FROM consent_ledger WHERE consent_id = ?",
                (consent_id,),
            ).fetchone()
            if not row or row["status"] == "revoked":
                return False

            with conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""
                    UPDATE consent_ledger
                    SET status='revoked', revoked_at=?,
                        revocation_reason=?, revocation_type=?
                    WHERE consent_id=?
                """, (now, reason, revocation_type, consent_id))

                # Cascade revocation to delegated children
                children = conn.execute(
                    "SELECT consent_id FROM consent_ledger "
                    "WHERE delegated_from=? AND status='active'",
                    (consent_id,),
                ).fetchall()
                for child in children:
                    conn.execute("""
                        UPDATE consent_ledger
                        SET status='revoked', revoked_at=?,
                            revocation_reason=?, revocation_type=?
                        WHERE consent_id=?
                    """, (now, f"cascade:{reason}", revocation_type,
                          child["consent_id"]))
        finally:
            conn.close()

        try:
            _memory.record(
                event_type="CONSENT_REVOKED",
                notes=f"Revoked: {consent_id}. Reason: {reason}",
                context={
                    "consent_id":      consent_id,
                    "reason":          reason,
                    "revocation_type": revocation_type,
                },
            )
        except Exception:
            pass

        return True

    # ------------------------------------------------------------------
    # HISTORY
    # ------------------------------------------------------------------

    def history(
        self,
        subject_id: str,
        include_revoked: bool = True,
    ) -> List[ConsentRecord]:
        """Return all consent records for a subject, newest first."""
        self._ensure_initialized()
        conn = _get_conn()
        try:
            query = (
                "SELECT * FROM consent_ledger WHERE subject_id=?"  # nosec B608
                + ("" if include_revoked else " AND status='active'")
                + " ORDER BY granted_at DESC"
            )
            rows = conn.execute(query, (subject_id,)).fetchall()
            return [self._row_to_record(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # PENDING
    # ------------------------------------------------------------------

    def pending(
        self,
        subject_id: Optional[str] = None,
    ) -> List[ConsentRequest]:
        """Return pending consent requests awaiting human approval."""
        self._ensure_initialized()
        conn = _get_conn()
        try:
            if subject_id:
                rows = conn.execute(
                    "SELECT * FROM consent_requests "
                    "WHERE subject_id=? AND resolved_at IS NULL "
                    "ORDER BY created_at DESC",
                    (subject_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM consent_requests "
                    "WHERE resolved_at IS NULL "
                    "ORDER BY created_at DESC"
                ).fetchall()
            return [self._row_to_request(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _find_active(
        self,
        subject_id: str,
        requester_id: str,
        purpose: str,
    ) -> Optional[ConsentRecord]:
        """Find the most recent active, non-expired consent record."""
        now = time.time()
        conn = _get_conn()
        try:
            row = conn.execute("""
                SELECT * FROM consent_ledger
                WHERE subject_id=? AND requester_id=? AND purpose=?
                  AND status='active' AND revoked_at IS NULL
                  AND (valid_until IS NULL OR valid_until > ?)
                ORDER BY granted_at DESC LIMIT 1
            """, (subject_id, requester_id, purpose, now)).fetchone()
            return self._row_to_record(row) if row else None
        finally:
            conn.close()

    def _has_opt_out(
        self,
        subject_id: str,
        requester_id: str,
        purpose: str,
    ) -> bool:
        """Check for an active GLBA opt-out record."""
        conn = _get_conn()
        try:
            row = conn.execute("""
                SELECT 1 FROM consent_ledger
                WHERE subject_id=? AND requester_id=? AND purpose=?
                  AND legal_basis='glba:opt-out'
                  AND status IN ('active', 'opt_out')
                  AND revoked_at IS NULL
                LIMIT 1
            """, (subject_id, requester_id, purpose)).fetchone()
            return row is not None
        finally:
            conn.close()

    def _row_to_record(self, row: sqlite3.Row) -> ConsentRecord:
        """Convert a SQLite Row to a ConsentRecord dataclass."""
        return ConsentRecord(
            consent_id=row["consent_id"],
            schema_version=row["schema_version"],
            subject_id=row["subject_id"],
            grantor_id=row["grantor_id"],
            requester_id=row["requester_id"],
            operator_node_did=row["operator_node_did"],
            purpose=row["purpose"],
            purpose_description=row["purpose_description"] or "",
            legal_basis=row["legal_basis"],
            operations=json.loads(row["operations"] or "[]"),
            classification_max=row["classification_max"],
            data_categories=json.loads(row["data_categories"]) if row["data_categories"] else None,
            geographic_scope=row["geographic_scope"],
            granted_at=row["granted_at"],
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            last_reconfirmed=row["last_reconfirmed"],
            status=row["status"],
            revoked_at=row["revoked_at"],
            revocation_reason=row["revocation_reason"],
            revocation_type=row["revocation_type"],
            hipaa_phi_description=row["hipaa_phi_description"],
            hipaa_expiry_event=row["hipaa_expiry_event"],
            hipaa_conditioning=row["hipaa_conditioning"],
            hipaa_redisclosure=row["hipaa_redisclosure"],
            delegated_from=row["delegated_from"],
            delegation_depth=row["delegation_depth"] or 0,
            vc_status_list_idx=row["vc_status_list_idx"],
        )

    def _row_to_request(self, row: sqlite3.Row) -> ConsentRequest:
        return ConsentRequest(
            request_id=row["request_id"],
            subject_id=row["subject_id"],
            requester_id=row["requester_id"],
            purpose=row["purpose"],
            purpose_description=row["purpose_description"] or "",
            classification=row["classification"],
            operation=row["operation"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            context=json.loads(row["context_json"]) if row["context_json"] else None,
        )


# ---------------------------------------------------------------------------
# MODULE-LEVEL SINGLETON
# ---------------------------------------------------------------------------

#: The global ConsentLedger instance.
#: Usage:
#:   from api.consent.ledger import consent_ledger
#:   cid = consent_ledger.grant(record)
consent_ledger = ConsentLedger()
