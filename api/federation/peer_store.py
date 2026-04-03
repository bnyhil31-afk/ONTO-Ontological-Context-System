"""
api/federation/peer_store.py

TOFU (Trust On First Use) certificate pinning for peer nodes.

The first TLS certificate presented by a peer's did:key is pinned locally.
Subsequent connections must present the same certificate hash.
A certificate change requires operator confirmation via onto_checkpoint.

This provides MITM protection on the intranet without requiring a CA.
It mirrors the SSH known_hosts model — well-understood and widely proven.

Trust model:
  - Pinning is permanent until the operator explicitly approves a change.
  - A peer with a changed certificate is rejected with status "cert_changed".
  - The caller (adapter) surfaces this to onto_checkpoint for operator decision.
  - Automatic disconnection on cert change does NOT happen without operator
    confirmation — same principle as everywhere else in ONTO.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import hashlib
import sqlite3
from typing import Optional

from modules import memory as _memory

# ---------------------------------------------------------------------------
# TABLE DEFINITION
# ---------------------------------------------------------------------------

_TABLE = "federation_peer_certs"


def initialize() -> None:
    """
    Create the federation_peer_certs table if it does not exist.
    Idempotent — safe to call on every federation start.
    Does not modify any existing table.
    """
    conn = _get_conn()
    try:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                peer_did        TEXT    PRIMARY KEY,
                cert_hash       TEXT    NOT NULL,
                pinned_at       REAL    NOT NULL,
                pinned_by       TEXT    NOT NULL,
                last_seen       REAL,
                rotation_count  INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DATABASE HELPERS
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(
        _memory.DB_PATH, check_same_thread=False, timeout=10
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _cert_hash(cert_pem: str) -> str:
    """SHA-256 of the PEM-encoded certificate. Stable and compact."""
    return hashlib.sha256(cert_pem.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def pin_cert(
    peer_did: str,
    cert_pem: str,
    session_hash: str,
) -> bool:
    """
    Pin a peer's certificate for the first time.

    Returns True if the cert was newly pinned.
    Returns False if the peer already has a pinned cert (use verify_cert
    to check validity).

    Writes a FEDERATION_CERT_PINNED audit event on first pin.
    """
    import time as _time

    conn = _get_conn()
    try:
        existing = conn.execute(
            f"SELECT peer_did FROM {_TABLE} WHERE peer_did = ?",
            (peer_did,),
        ).fetchone()

        if existing:
            return False  # Already pinned — caller should use verify_cert

        h = _cert_hash(cert_pem)
        now = _time.time()
        conn.execute(
            f"INSERT INTO {_TABLE} "
            f"(peer_did, cert_hash, pinned_at, pinned_by, last_seen, "
            f"rotation_count) VALUES (?, ?, ?, ?, ?, 0)",
            (peer_did, h, now, session_hash, now),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        _memory.record(
            event_type="FEDERATION_CERT_PINNED",
            notes=f"Peer certificate pinned: {peer_did}",
            context={
                "peer_did": peer_did,
                "cert_hash": h,
                "session": session_hash,
            },
        )
    except Exception:
        pass

    return True


def verify_cert(
    peer_did: str,
    cert_pem: str,
) -> tuple:
    """
    Verify a peer's certificate against the pinned value.

    Returns a 2-tuple (status, cert_hash):
      ("unknown",       None)  — peer has never been seen before; call pin_cert
      ("valid",         hash)  — cert matches pinned value; proceed
      ("cert_changed",  hash)  — cert does not match; surface to checkpoint
      ("error",         None)  — database error; treat as unknown

    The caller is responsible for deciding what to do with "cert_changed".
    It must NOT automatically disconnect — it must surface to onto_checkpoint.
    """
    import time as _time

    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                f"SELECT cert_hash FROM {_TABLE} WHERE peer_did = ?",
                (peer_did,),
            ).fetchone()

            if not row:
                return "unknown", None

            pinned_hash = row["cert_hash"]
            current_hash = _cert_hash(cert_pem)

            # Update last_seen regardless of match
            conn.execute(
                f"UPDATE {_TABLE} SET last_seen = ? WHERE peer_did = ?",
                (_time.time(), peer_did),
            )
            conn.commit()

        finally:
            conn.close()

        if current_hash == pinned_hash:
            return "valid", current_hash

        return "cert_changed", current_hash

    except Exception:
        return "error", None


def approve_cert_change(
    peer_did: str,
    new_cert_pem: str,
    session_hash: str,
) -> bool:
    """
    Record an operator-approved certificate rotation for a peer.

    This is called AFTER the operator has confirmed via onto_checkpoint.
    Updates the pinned cert hash and increments the rotation_count.
    Writes a FEDERATION_CERT_CHANGED audit event.

    Returns True on success, False on error or if peer is unknown.
    """
    import time as _time

    conn = _get_conn()
    try:
        existing = conn.execute(
            f"SELECT cert_hash, rotation_count FROM {_TABLE} "
            f"WHERE peer_did = ?",
            (peer_did,),
        ).fetchone()

        if not existing:
            return False

        old_hash = existing["cert_hash"]
        new_hash = _cert_hash(new_cert_pem)
        new_rotation_count = existing["rotation_count"] + 1
        now = _time.time()

        conn.execute(
            f"UPDATE {_TABLE} SET cert_hash = ?, pinned_by = ?, "
            f"last_seen = ?, rotation_count = ? WHERE peer_did = ?",
            (new_hash, session_hash, now, new_rotation_count, peer_did),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        _memory.record(
            event_type="FEDERATION_CERT_CHANGED",
            notes=(
                f"Peer certificate rotation approved: {peer_did} "
                f"(rotation #{new_rotation_count})"
            ),
            context={
                "peer_did": peer_did,
                "old_cert_hash": old_hash,
                "new_cert_hash": new_hash,
                "rotation_count": new_rotation_count,
                "approved_by": session_hash,
            },
        )
    except Exception:
        pass

    return True


def get_peer_cert(peer_did: str) -> Optional[dict]:
    """
    Return the pinned cert record for a peer, or None if unknown.
    The cert_hash is a SHA-256 hex string — not the PEM cert itself.
    PEM certs are never stored locally.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT peer_did, cert_hash, pinned_at, pinned_by, "
            f"last_seen, rotation_count FROM {_TABLE} WHERE peer_did = ?",
            (peer_did,),
        ).fetchone()
        if not row:
            return None
        return {
            "peer_did":       row["peer_did"],
            "cert_hash":      row["cert_hash"],
            "pinned_at":      row["pinned_at"],
            "pinned_by":      row["pinned_by"],
            "last_seen":      row["last_seen"],
            "rotation_count": row["rotation_count"],
        }
    finally:
        conn.close()


def remove_peer(peer_did: str) -> bool:
    """
    Remove a peer's pinned certificate. Used when a peer is explicitly
    removed from the network by the operator.
    Writes a FEDERATION_PEER_REMOVED audit event.
    Returns True if removed, False if peer was not found.
    """
    conn = _get_conn()
    try:
        result = conn.execute(
            f"DELETE FROM {_TABLE} WHERE peer_did = ?",
            (peer_did,),
        )
        conn.commit()
        removed = result.rowcount > 0
    finally:
        conn.close()

    if removed:
        try:
            _memory.record(
                event_type="FEDERATION_PEER_REMOVED",
                notes=f"Peer removed from peer store: {peer_did}",
                context={"peer_did": peer_did},
            )
        except Exception:
            pass

    return removed


def list_peers() -> list:
    """
    Return all known peers as a list of dicts.
    Ordered by pinned_at descending (most recently added first).
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            f"SELECT peer_did, cert_hash, pinned_at, last_seen, "
            f"rotation_count FROM {_TABLE} ORDER BY pinned_at DESC"
        ).fetchall()
        return [
            {
                "peer_did":       r["peer_did"],
                "cert_hash":      r["cert_hash"],
                "pinned_at":      r["pinned_at"],
                "last_seen":      r["last_seen"],
                "rotation_count": r["rotation_count"],
            }
            for r in rows
        ]
    finally:
        conn.close()
