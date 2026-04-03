"""
api/federation/consent.py

Federation Consent Ledger.

Every share operation requires an active consent record. No exceptions.
Consent is enforced at the protocol level — no configuration disables it.

Merkle-chained: each record includes the hash of the previous record,
preventing retroactive insertion or deletion.

W3C VC forward-compatible: vc_id, vc_issuer, vc_proof are present
but NULL until Phase 5.

Lifecycle: GRANTED -> ACTIVE -> REVOKED (terminal)
                         |-> EXPIRED (if expires_at reached)
                         |-> NEEDS_RECONFIRMATION (standing, overdue)

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import hashlib
import sqlite3
import time
import uuid
from typing import List, Optional

from modules import memory as _memory

_TABLE = "federation_consent"


def initialize() -> None:
    """Create the table if absent. Idempotent. Touches no existing table."""
    conn = _get_conn()
    try:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                consent_id          TEXT    PRIMARY KEY,
                grantor_session     TEXT    NOT NULL,
                recipient_node      TEXT    NOT NULL,
                data_description    TEXT    NOT NULL,
                data_concept_hash   TEXT,
                classification      INTEGER NOT NULL,
                granted_at          REAL    NOT NULL,
                expires_at          REAL,
                last_reconfirmed    REAL,
                revoked_at          REAL,
                revocation_reason   TEXT,
                chain_hash          TEXT    NOT NULL,
                vc_id               TEXT,
                vc_issuer           TEXT,
                vc_proof            TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# INTERNAL HELPERS
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(
        _memory.DB_PATH, check_same_thread=False, timeout=10
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _compute_chain_hash(
    consent_id: str,
    granted_at: float,
    prev_hash: Optional[str],
) -> str:
    """
    Merkle chain hash for a consent record.
    Genesis:     SHA-256(consent_id + "|" + granted_at)
    Subsequent:  SHA-256(prev_hash + "|" + consent_id + "|" + granted_at)
    Retroactive insertion/deletion would break all subsequent hashes.
    """
    if prev_hash:
        data = f"{prev_hash}|{consent_id}|{granted_at}"
    else:
        data = f"{consent_id}|{granted_at}"
    return hashlib.sha256(data.encode()).hexdigest()


def _get_latest_chain_hash() -> Optional[str]:
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT chain_hash FROM {_TABLE} "
            f"ORDER BY granted_at DESC LIMIT 1"
        ).fetchone()
        return row["chain_hash"] if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def grant(
    grantor_session: str,
    recipient_node: str,
    data_description: str,
    classification: int,
    data_concept_hash: Optional[str] = None,
    expires_at: Optional[float] = None,
) -> str:
    """
    Record a new consent grant. Returns the consent_id (UUID v4).
    Writes FEDERATION_CONSENT_GRANTED to the audit trail.

    expires_at=None creates a standing consent requiring re-confirmation
    every ONTO_FED_STANDING_CONSENT_RECONFIRM_DAYS days.
    """
    consent_id = str(uuid.uuid4())
    now = time.time()
    chain_hash = _compute_chain_hash(
        consent_id, now, _get_latest_chain_hash()
    )

    conn = _get_conn()
    try:
        conn.execute(
            f"INSERT INTO {_TABLE} "
            f"(consent_id, grantor_session, recipient_node, "
            f"data_description, data_concept_hash, classification, "
            f"granted_at, expires_at, last_reconfirmed, chain_hash) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                consent_id, grantor_session, recipient_node,
                data_description, data_concept_hash, classification,
                now, expires_at, now, chain_hash,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        _memory.record(
            event_type="FEDERATION_CONSENT_GRANTED",
            notes=f"Consent to {recipient_node}: {data_description[:80]}",
            context={
                "consent_id": consent_id,
                "recipient_node": recipient_node,
                "classification": classification,
                "expires_at": expires_at,
                "session": grantor_session,
            },
        )
    except Exception:
        pass

    return consent_id


def revoke(consent_id: str, reason: str = "") -> bool:
    """
    Permanently revoke a consent. Terminal — cannot be undone.
    Returns True if revoked, False if not found or already revoked.
    Caller should invoke recall() to retract data from peers.
    """
    now = time.time()
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT revoked_at FROM {_TABLE} WHERE consent_id = ?",
            (consent_id,),
        ).fetchone()
        if not row or row["revoked_at"] is not None:
            return False
        conn.execute(
            f"UPDATE {_TABLE} "
            f"SET revoked_at = ?, revocation_reason = ? "
            f"WHERE consent_id = ?",
            (now, reason, consent_id),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        _memory.record(
            event_type="FEDERATION_CONSENT_REVOKED",
            notes=f"Revoked: {consent_id}. Reason: {reason or 'none'}",
            context={"consent_id": consent_id, "reason": reason},
        )
    except Exception:
        pass

    return True


def is_valid(consent_id: str, recipient_node: str) -> tuple:
    """
    Check whether a consent record is currently active.
    Returns (valid: bool, reason: str).
    Valid means: exists, not revoked, not expired, correct recipient.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT recipient_node, revoked_at, expires_at "
            f"FROM {_TABLE} WHERE consent_id = ?",
            (consent_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return False, f"consent_id '{consent_id}' not found"
    if row["recipient_node"] != recipient_node:
        return (
            False,
            f"consent is for '{row['recipient_node']}', "
            f"not '{recipient_node}'",
        )
    if row["revoked_at"] is not None:
        return False, "consent has been revoked"
    if row["expires_at"] is not None and row["expires_at"] < time.time():
        return False, "consent has expired"
    return True, "valid"


def needs_reconfirmation(consent_id: str) -> bool:
    """
    True if a standing consent has exceeded the re-confirmation interval.
    False for timed consents, revoked records, or unknown IDs.
    """
    from api.federation import config

    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT expires_at, last_reconfirmed, revoked_at "
            f"FROM {_TABLE} WHERE consent_id = ?",
            (consent_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row or row["revoked_at"] is not None:
        return False
    if row["expires_at"] is not None:
        return False
    if row["last_reconfirmed"] is None:
        return True
    days = (time.time() - row["last_reconfirmed"]) / 86400.0
    return days >= config.STANDING_CONSENT_RECONFIRM_DAYS


def reconfirm(consent_id: str, session_hash: str) -> bool:
    """
    Record operator re-confirmation of a standing consent.
    Returns True on success, False if not found or revoked.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT revoked_at FROM {_TABLE} WHERE consent_id = ?",
            (consent_id,),
        ).fetchone()
        if not row or row["revoked_at"] is not None:
            return False
        conn.execute(
            f"UPDATE {_TABLE} SET last_reconfirmed = ? "
            f"WHERE consent_id = ?",
            (time.time(), consent_id),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        _memory.record(
            event_type="FEDERATION_CONSENT_RECONFIRMED",
            notes=f"Re-confirmed: {consent_id}",
            context={"consent_id": consent_id, "session": session_hash},
        )
    except Exception:
        pass

    return True


def get(consent_id: str) -> Optional[dict]:
    """Return the full consent record, or None if not found."""
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT * FROM {_TABLE} WHERE consent_id = ?",
            (consent_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_for_peer(peer_did: str) -> List[dict]:
    """Return all consent records for a peer, newest first."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            f"SELECT consent_id, data_description, classification, "
            f"granted_at, expires_at, revoked_at "
            f"FROM {_TABLE} WHERE recipient_node = ? "
            f"ORDER BY granted_at DESC",
            (peer_did,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_pending_reconfirmation() -> List[dict]:
    """
    Return standing consents that need operator re-confirmation.
    Used by onto_status to surface warnings.
    """
    from api.federation import config

    threshold = (
        time.time()
        - config.STANDING_CONSENT_RECONFIRM_DAYS * 86400.0
    )
    conn = _get_conn()
    try:
        rows = conn.execute(
            f"SELECT consent_id, recipient_node, data_description, "
            f"last_reconfirmed "
            f"FROM {_TABLE} "
            f"WHERE expires_at IS NULL AND revoked_at IS NULL "
            f"AND (last_reconfirmed IS NULL OR last_reconfirmed < ?) "
            f"ORDER BY last_reconfirmed ASC",
            (threshold,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def verify_chain_integrity() -> dict:
    """
    Verify the Merkle chain of the consent ledger.
    Returns {"intact": bool, "total": int, "broken_at": Optional[str]}.
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            f"SELECT consent_id, granted_at, chain_hash "
            f"FROM {_TABLE} ORDER BY granted_at ASC"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"intact": True, "total": 0, "broken_at": None}

    prev_hash: Optional[str] = None
    for row in rows:
        expected = _compute_chain_hash(
            row["consent_id"], row["granted_at"], prev_hash
        )
        if row["chain_hash"] != expected:
            return {
                "intact": False,
                "total": len(rows),
                "broken_at": row["consent_id"],
            }
        prev_hash = row["chain_hash"]

    return {"intact": True, "total": len(rows), "broken_at": None}
