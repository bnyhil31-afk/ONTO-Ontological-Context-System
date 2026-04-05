"""
api/consent/status_list.py

Bitstring Status List management for consent record revocation.

Phase 4: Index allocation only (vc_status_list_idx assigned to records).
         No bitstring is generated or published — VCService not active.

Phase 5: VCService activates and manages the live bitstring.
         The allocated indexes are used by the sidecar.

W3C Bitstring Status List v1.0 (W3C Recommendation, May 2025):
  - Minimum size: 131,072 entries (~16KB compressed GZIP)
  - Multi-bit: 2 bits per entry = 4 states:
      00 = active
      01 = suspended (pending review)
      10 = revoked
      11 = expired
  - TTL: 300 seconds for consent (prompt revocation propagation)

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import sqlite3
import threading
from typing import Optional

from modules import memory as _memory

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

# Minimum list size per W3C spec — ensures privacy via herd effect
MINIMUM_LIST_SIZE = 131_072

# Bits per entry — 2 bits allows 4 states
BITS_PER_ENTRY = 2

# Status values (2-bit encoding)
STATUS_ACTIVE    = 0b00  # active
STATUS_SUSPENDED = 0b01  # pending review
STATUS_REVOKED   = 0b10  # revoked
STATUS_EXPIRED   = 0b11  # expired

# TTL for consent status lists (seconds)
STATUS_LIST_TTL_SECS = 300

# Counter table name for index tracking
_COUNTER_TABLE = "consent_status_list_counter"
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# INITIALIZATION
# ---------------------------------------------------------------------------

def initialize() -> None:
    """
    Create the status list counter table idempotently.
    The counter tracks which indexes have been allocated.
    """
    conn = _get_conn()
    try:
        with conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {_COUNTER_TABLE} (
                    id      INTEGER PRIMARY KEY CHECK (id = 1),
                    next_idx INTEGER NOT NULL DEFAULT 0
                )
            """)
            # Seed with initial value if empty
            conn.execute(f"""
                INSERT OR IGNORE INTO {_COUNTER_TABLE} (id, next_idx)
                VALUES (1, 0)
            """)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# INDEX ALLOCATION
# ---------------------------------------------------------------------------

def allocate_index() -> int:
    """
    Allocate the next available status list index for a consent record.
    Thread-safe: uses a database transaction to prevent double-allocation.

    Returns the allocated index (0-based).
    Phase 4: index is stored in consent_ledger.vc_status_list_idx.
    Phase 5: VCService uses this index to set/clear the revocation bit.
    """
    with _lock:
        conn = _get_conn()
        try:
            with conn:
                row = conn.execute(
                    f"SELECT next_idx FROM {_COUNTER_TABLE} WHERE id = 1"  # nosec B608
                ).fetchone()
                idx = row["next_idx"] if row else 0
                conn.execute(
                    f"UPDATE {_COUNTER_TABLE} SET next_idx = ? WHERE id = 1",  # nosec B608
                    (idx + 1,),
                )
            return idx
        finally:
            conn.close()


def get_next_index() -> int:
    """Return the next index without allocating it (peek)."""
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT next_idx FROM {_COUNTER_TABLE} WHERE id = 1"  # nosec B608
        ).fetchone()
        return row["next_idx"] if row else 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# STATUS ENCODING
# ---------------------------------------------------------------------------

def encode_status(status: str) -> int:
    """
    Encode a consent status string to its 2-bit integer representation.
    Unknown statuses default to STATUS_SUSPENDED (safe fallback).
    """
    mapping = {
        "active":    STATUS_ACTIVE,
        "suspended": STATUS_SUSPENDED,
        "revoked":   STATUS_REVOKED,
        "expired":   STATUS_EXPIRED,
        "opt_out":   STATUS_REVOKED,  # GLBA opt-out treated as revoked
    }
    return mapping.get(status, STATUS_SUSPENDED)


def decode_status(bits: int) -> str:
    """Decode a 2-bit status integer to its string representation."""
    mapping = {
        STATUS_ACTIVE:    "active",
        STATUS_SUSPENDED: "suspended",
        STATUS_REVOKED:   "revoked",
        STATUS_EXPIRED:   "expired",
    }
    return mapping.get(bits & 0b11, "suspended")


# ---------------------------------------------------------------------------
# STATUS LIST METADATA
# ---------------------------------------------------------------------------

def get_status_list_metadata() -> dict:
    """
    Return metadata about the current status list allocation.
    Used by VCService in Phase 5 to build the status list credential.
    """
    next_idx = get_next_index()
    return {
        "minimum_size":     MINIMUM_LIST_SIZE,
        "bits_per_entry":   BITS_PER_ENTRY,
        "entries_allocated":next_idx,
        "ttl_seconds":      STATUS_LIST_TTL_SECS,
        "phase":            4,
        "vc_service_active":False,  # True in Phase 5
        "note": (
            "Indexes allocated but no live bitstring in Phase 4. "
            "VCService activation in Phase 5 publishes the bitstring."
        ),
    }


# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(
        _memory.DB_PATH,
        check_same_thread=False,
        timeout=5,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
