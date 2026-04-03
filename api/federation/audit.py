"""
api/federation/audit.py

Inter-node audit event coordination and messaging infrastructure.

Responsibilities:
  1. Create and manage federation_outbox and federation_inbox tables
  2. Record federation events to the main audit trail (memory.record)
  3. Track outbound message sequence numbers per recipient
  4. Validate inbound message sequence numbers
  5. Rate limiting: reject excess messages per peer per minute

Every federation operation writes to the main audit trail (memory.record)
so that federation activity is part of the cryptographic Merkle chain.
No federation event should be invisible to the audit trail.

Outbox retry policy: operator-initiated only.
Failed sends are recorded in the outbox with failed_at + failure_reason.
No automatic retry — see FEDERATION-SPEC-001 §9.3.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import hashlib
import sqlite3
import threading
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from modules import memory as _memory

# Message types (FEDERATION-SPEC-001 §9.2)
MSG_HANDSHAKE = "HANDSHAKE"
MSG_PING = "PING"
MSG_SHARE = "SHARE"
MSG_RETRACT = "RETRACT"
MSG_MERGE_REQUEST = "MERGE_REQUEST"
MSG_AUDIT_SYNC = "AUDIT_SYNC"

VALID_MESSAGE_TYPES = frozenset({
    MSG_HANDSHAKE, MSG_PING, MSG_SHARE,
    MSG_RETRACT, MSG_MERGE_REQUEST, MSG_AUDIT_SYNC,
})

# ---------------------------------------------------------------------------
# RATE LIMITING STATE (in-memory per process)
# ---------------------------------------------------------------------------

# {peer_did: [epoch_timestamps_of_received_messages]}
_rate_state: Dict[str, List[float]] = defaultdict(list)
_rate_lock = threading.Lock()

# Backoff tracking: {peer_did: backoff_expires_at_epoch}
_backoff_state: Dict[str, float] = {}
_backoff_levels: List[int] = [60, 120, 240, 480]   # seconds


# ---------------------------------------------------------------------------
# DATABASE SETUP
# ---------------------------------------------------------------------------

def initialize() -> None:
    """
    Create federation messaging tables. Idempotent.
    Does not modify any existing tables.
    """
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS federation_outbox (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient      TEXT    NOT NULL,
                message_type   TEXT    NOT NULL,
                sequence_id    INTEGER NOT NULL,
                payload_hash   TEXT    NOT NULL,
                sent_at        REAL,
                acked_at       REAL,
                failed_at      REAL,
                failure_reason TEXT,
                created_at     REAL    NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_recipient "
            "ON federation_outbox(recipient, sent_at)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS federation_inbox (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                sender         TEXT    NOT NULL,
                message_type   TEXT    NOT NULL,
                sequence_id    INTEGER NOT NULL,
                payload_hash   TEXT    NOT NULL,
                received_at    REAL    NOT NULL,
                processed_at   REAL,
                rejected       INTEGER NOT NULL DEFAULT 0,
                reject_reason  TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_inbox_sender "
            "ON federation_inbox(sender, received_at)"
        )
        conn.commit()
    finally:
        conn.close()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(
        _memory.DB_PATH, check_same_thread=False, timeout=10
    )
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# SEQUENCE NUMBERS
# ---------------------------------------------------------------------------

def next_outbound_sequence(recipient: str) -> int:
    """
    Return the next sequence_id for outbound messages to a recipient.
    Sequence IDs are monotonically increasing per recipient, starting at 1.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(sequence_id) AS max_seq "
            "FROM federation_outbox WHERE recipient = ?",
            (recipient,),
        ).fetchone()
        max_seq = row["max_seq"] if row and row["max_seq"] is not None else 0
        return max_seq + 1
    finally:
        conn.close()


def validate_inbound_sequence(
    sender: str, sequence_id: int
) -> str:
    """
    Validate an inbound sequence_id from a sender.
    Returns one of:
      "ok"        — expected sequence; process normally
      "gap"       — one or more messages missing; request re-send
      "duplicate" — already seen this sequence_id; discard silently
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT MAX(sequence_id) AS max_seq "
            "FROM federation_inbox WHERE sender = ? AND rejected = 0",
            (sender,),
        ).fetchone()
        max_seen = (
            row["max_seq"] if row and row["max_seq"] is not None else 0
        )
    finally:
        conn.close()

    expected = max_seen + 1
    if sequence_id == expected:
        return "ok"
    if sequence_id <= max_seen:
        return "duplicate"
    return "gap"


# ---------------------------------------------------------------------------
# OUTBOX OPERATIONS
# ---------------------------------------------------------------------------

def payload_hash(payload: dict) -> str:
    """SHA-256 of the JSON-canonical payload. Stored; payload is not."""
    import json
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def record_outbound(
    recipient: str,
    message_type: str,
    payload: dict,
) -> int:
    """
    Record a message in the outbox. Returns the outbox record ID.
    The payload hash is stored; the payload itself is not persisted.
    """
    now = time.time()
    seq = next_outbound_sequence(recipient)
    p_hash = payload_hash(payload)

    conn = _get_conn()
    try:
        cursor = conn.execute(
            "INSERT INTO federation_outbox "
            "(recipient, message_type, sequence_id, payload_hash, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (recipient, message_type, seq, p_hash, now),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def mark_sent(outbox_id: int) -> None:
    """Mark an outbox record as successfully sent."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE federation_outbox SET sent_at = ? WHERE id = ?",
            (time.time(), outbox_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_acked(outbox_id: int) -> None:
    """Mark an outbox record as acknowledged by the recipient."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE federation_outbox SET acked_at = ? WHERE id = ?",
            (time.time(), outbox_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_failed(outbox_id: int, reason: str) -> None:
    """
    Mark an outbox record as failed. Operator-initiated retry only.
    The failure is surfaced in onto_status federation health block.
    """
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE federation_outbox "
            "SET failed_at = ?, failure_reason = ? WHERE id = ?",
            (time.time(), reason, outbox_id),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        _memory.record(
            event_type="FEDERATION_SEND_FAILED",
            notes=f"Outbox send failed (id={outbox_id}): {reason}",
            context={"outbox_id": outbox_id, "reason": reason},
        )
    except Exception:
        pass


def get_failed_sends() -> List[dict]:
    """Return all failed outbox records. Surfaced in onto_status."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, recipient, message_type, sequence_id, "
            "failed_at, failure_reason FROM federation_outbox "
            "WHERE failed_at IS NOT NULL ORDER BY failed_at DESC"
        ).fetchall()
        return [
            {
                "outbox_id":    r["id"],
                "recipient":    r["recipient"],
                "message_type": r["message_type"],
                "sequence_id":  r["sequence_id"],
                "failed_at":    r["failed_at"],
                "reason":       r["failure_reason"],
            }
            for r in rows
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# INBOX OPERATIONS
# ---------------------------------------------------------------------------

def record_inbound(
    sender: str,
    message_type: str,
    sequence_id: int,
    payload: dict,
    rejected: bool = False,
    reject_reason: Optional[str] = None,
) -> int:
    """
    Record a received message in the inbox. Returns the inbox record ID.
    """
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "INSERT INTO federation_inbox "
            "(sender, message_type, sequence_id, payload_hash, "
            "received_at, rejected, reject_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sender, message_type, sequence_id,
                payload_hash(payload), time.time(),
                int(rejected), reject_reason,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def mark_processed(inbox_id: int) -> None:
    """Mark an inbox record as processed."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE federation_inbox SET processed_at = ? WHERE id = ?",
            (time.time(), inbox_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# RATE LIMITING
# ---------------------------------------------------------------------------

def check_rate_limit(
    peer_did: str,
    max_per_min: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    Check if a message from peer_did is within the rate limit.
    Returns (allowed, reason).

    If exceeded, the peer enters exponential backoff.
    Backoff levels: 60s → 120s → 240s → 480s (max).
    """
    from api.federation import config as _cfg
    limit = max_per_min or _cfg.MAX_MSGS_PER_PEER_PER_MIN
    now = time.time()

    with _rate_lock:
        # Check if peer is in backoff
        backoff_until = _backoff_state.get(peer_did, 0.0)
        if now < backoff_until:
            remaining = int(backoff_until - now)
            return (
                False,
                f"peer in backoff for {remaining}s",
            )

        # Count messages in the last 60 seconds
        window = now - 60.0
        recent = [t for t in _rate_state[peer_did] if t > window]
        _rate_state[peer_did] = recent

        if len(recent) >= limit:
            # Enter/escalate backoff
            current_level = _escalate_backoff(peer_did, now)
            return (
                False,
                f"rate limit exceeded ({len(recent)}/{limit} per min); "
                f"backoff {current_level}s",
            )

        # Record this message
        _rate_state[peer_did].append(now)

    return True, "ok"


def _escalate_backoff(peer_did: str, now: float) -> int:
    """Escalate backoff level for a peer. Returns the new backoff seconds."""
    backoff_until = _backoff_state.get(peer_did, 0.0)
    # Find current level based on last backoff duration
    last_duration = max(0, backoff_until - now)
    level_idx = 0
    for i, secs in enumerate(_backoff_levels):
        if last_duration <= secs:
            level_idx = min(i + 1, len(_backoff_levels) - 1)
            break

    new_duration = _backoff_levels[level_idx]
    _backoff_state[peer_did] = now + new_duration
    return new_duration


def clear_backoff(peer_did: str) -> None:
    """Clear rate limit state for a peer. Called after successful exchange."""
    with _rate_lock:
        _rate_state.pop(peer_did, None)
        _backoff_state.pop(peer_did, None)


# ---------------------------------------------------------------------------
# FEDERATION EVENT HELPERS
# ---------------------------------------------------------------------------

def record_event(
    event_type: str,
    peer_did: str,
    notes: str,
    context: Optional[dict] = None,
) -> None:
    """
    Write a federation event to the main audit trail.
    Never raises — federation audit events must not crash the caller.
    """
    try:
        _memory.record(
            event_type=event_type,
            notes=notes,
            context={
                "peer_did": peer_did,
                **(context or {}),
            },
        )
    except Exception:
        pass


def health_summary() -> dict:
    """
    Return federation messaging health for onto_status.
    Safe to call at any time. Never raises.
    """
    try:
        conn = _get_conn()
        try:
            failed = conn.execute(
                "SELECT COUNT(*) AS c FROM federation_outbox "
                "WHERE failed_at IS NOT NULL"
            ).fetchone()["c"]
            pending = conn.execute(
                "SELECT COUNT(*) AS c FROM federation_outbox "
                "WHERE sent_at IS NULL AND failed_at IS NULL"
            ).fetchone()["c"]
            total_in = conn.execute(
                "SELECT COUNT(*) AS c FROM federation_inbox"
            ).fetchone()["c"]
        finally:
            conn.close()

        with _rate_lock:
            rate_limited = [
                did for did, until in _backoff_state.items()
                if until > time.time()
            ]

        return {
            "outbox_pending":    pending,
            "outbox_failed":     failed,
            "inbox_total":       total_in,
            "rate_limited_peers": rate_limited,
        }
    except Exception:
        return {
            "outbox_pending": 0,
            "outbox_failed":  0,
            "inbox_total":    0,
            "rate_limited_peers": [],
        }
