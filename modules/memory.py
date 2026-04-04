"""
modules/memory.py

The system's permanent memory.
Everything that happens is recorded here — honestly and completely.
The record never changes. It only grows.

Changes from v1 (REVIEW_001 findings C2, U1, U3, U6):

  C2 — Merkle chain: every record stores a SHA-256 hash of the previous
       record's content. Deletion creates a visible gap. Tampering is
       detectable. The chain is the audit trail's integrity mechanism.

  U1 — SQLite performance pragmas: WAL mode, 32MB cache, optimized page
       size and sync mode for graph traversal workloads.

  U3 — Read logging: reads of sensitive records generate READ_ACCESS
       events in the audit trail. Reads are as visible as writes.

  U6 — signature_algorithm field: every COMMIT record declares which
       algorithm signed it. Enables migration from Ed25519 to ML-DSA
       (post-quantum) without schema changes.

Plain English: This is the system's journal.
Every action, every decision, every read of sensitive data — written
down permanently. Anyone can read it. No one can erase it.

This is Principle VII: Memory — in code.
"""

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH: str = os.path.join(ROOT, "data", "memory.db")

# Classification level at or above which reads are logged (U3)
READ_LOG_THRESHOLD: int = 2  # personal data and above


# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

def initialize() -> bool:
    """
    Creates the database and tables if they don't exist.
    Applies performance pragmas for graph traversal workloads.
    Safe to run multiple times — never overwrites existing data.

    Returns:
        bool: True when initialization is complete.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _connect() as conn:
        # U1 — Performance pragmas for graph traversal
        # WAL mode: allows concurrent reads during writes
        conn.execute("PRAGMA journal_mode=WAL")
        # Optimized page size for random-access graph traversal
        conn.execute("PRAGMA page_size=4096")
        # 32MB in-memory cache — reduces disk I/O for traversal
        conn.execute("PRAGMA cache_size=-32000")
        # NORMAL sync: balance between durability and performance
        # (FULL is too slow for high-frequency COMMIT events)
        conn.execute("PRAGMA synchronous=NORMAL")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp           TEXT    NOT NULL,
                event_type          TEXT    NOT NULL,
                input               TEXT,
                context             TEXT,
                output              TEXT,
                confidence          REAL,
                human_decision      TEXT,
                notes               TEXT,
                chain_hash          TEXT,
                signature_algorithm TEXT    DEFAULT 'Ed25519',
                classification      INTEGER DEFAULT 0
            )
        """)

        # Append-only enforcement triggers
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS prevent_delete
            BEFORE DELETE ON events
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Records cannot be deleted. Memory is permanent.'
                );
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS prevent_update
            BEFORE UPDATE ON events
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Records cannot be changed. Memory is permanent.'
                );
            END
        """)

        # U1 — Indexes for graph edge traversal performance
        # (Pre-created here for the relationship graph schema we'll add)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_type
            ON events(event_type)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_timestamp
            ON events(timestamp DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_classification
            ON events(classification)
        """)

        # Schema migration — add new columns if upgrading from older schema
        # This is safe to run on any existing database
        # Pre-approved column additions for schema migration.
        # Using a fixed dict (not user input) prevents SQL injection.
        # SQLite does not support parameterized DDL, so we whitelist explicitly.
        _MIGRATION_COLUMNS = {
            "chain_hash": "TEXT",
            "signature_algorithm": "TEXT DEFAULT 'Ed25519'",
            "classification": "INTEGER DEFAULT 0",
        }
        for col_name, col_def in _MIGRATION_COLUMNS.items():
            try:
                conn.execute(
                    f"ALTER TABLE events ADD COLUMN {col_name} {col_def}"
                )
            except sqlite3.OperationalError:
                pass  # column already exists — this is expected on fresh DBs

    return True


# ─────────────────────────────────────────────────────────────────────────────
# WRITE — APPEND ONLY WITH MERKLE CHAIN (C2)
# ─────────────────────────────────────────────────────────────────────────────

def record(
    event_type: str,
    input_data: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    output: Optional[str] = None,
    confidence: Optional[float] = None,
    human_decision: Optional[str] = None,
    notes: Optional[str] = None,
    classification: int = 0,
    signature_algorithm: str = "Ed25519"
) -> int:
    """
    Records a single event permanently in the audit trail.

    C2 — Merkle chain: computes the SHA-256 hash of the previous record
    and stores it in chain_hash. This creates a cryptographically linked
    chain. If any record is deleted or modified, the chain breaks and
    the gap is detectable.

    U6 — signature_algorithm: declares which algorithm signed this record.
    Defaults to Ed25519. Will be ML-DSA in Stage 2+ deployments.
    Storing the algorithm enables migration without schema changes.

    Args:
        event_type:          Type of event (BOOT, INTAKE, CHECKPOINT, etc.)
        input_data:          Raw input text if applicable
        context:             Context dict if applicable
        output:              Output text if applicable
        confidence:          Confidence score 0.0-1.0 if applicable
        human_decision:      Human decision at checkpoint if applicable
        notes:               Additional notes
        classification:      Data sensitivity level 0-5
        signature_algorithm: Algorithm used for signing (U6)

    Returns:
        int: The ID of the new record
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    context_json = json.dumps(context) if context else None

    with _connect() as conn:
        # C2 — Compute chain hash from previous record
        chain_hash = _compute_chain_hash(conn)

        cursor = conn.execute("""
            INSERT INTO events (
                timestamp, event_type, input, context, output,
                confidence, human_decision, notes,
                chain_hash, signature_algorithm, classification
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            event_type,
            input_data,
            context_json,
            output,
            confidence,
            human_decision,
            notes,
            chain_hash,
            signature_algorithm,
            classification
        ))
        return cursor.lastrowid


def log_read_access(
    record_id: int,
    accessor_id: str = "system",
    purpose: str = "unspecified",
    classification: int = 0
) -> Optional[int]:
    """
    U3 — Read logging.

    Records that a sensitive record was read. Generates a READ_ACCESS
    event in the audit trail. Reads of data at or above
    READ_LOG_THRESHOLD are as visible as writes.

    Per the crossover contract §8.3: "Every read of a sensitive record
    generates a READ_ACCESS event. Reads are as visible as writes."

    Args:
        record_id:      ID of the record that was read
        accessor_id:    Identity of the accessor
        purpose:        Declared purpose of the read
        classification: Classification level of the accessed record

    Returns:
        ID of the READ_ACCESS event, or None if below threshold
    """
    if classification < READ_LOG_THRESHOLD:
        return None

    return record(
        event_type="READ_ACCESS",
        input_data=str(record_id),
        notes=json.dumps({
            "accessed_record_id": record_id,
            "accessor_id": accessor_id,
            "purpose": purpose,
            "classification": classification
        }),
        classification=classification
    )


# ─────────────────────────────────────────────────────────────────────────────
# READ
# ─────────────────────────────────────────────────────────────────────────────

def read_all() -> List[Dict[str, Any]]:
    """
    Returns all records in the audit trail, oldest first.
    """
    with _connect() as conn:
        cursor = conn.execute("""
            SELECT id, timestamp, event_type, input, context,
                   output, confidence, human_decision, notes,
                   chain_hash, signature_algorithm, classification
            FROM events
            ORDER BY id ASC
        """)
        return [_row_to_dict(row) for row in cursor.fetchall()]


def read_recent(n: int = 10) -> List[Dict[str, Any]]:
    """
    Returns the n most recent records, newest first.
    """
    with _connect() as conn:
        cursor = conn.execute("""
            SELECT id, timestamp, event_type, input, context,
                   output, confidence, human_decision, notes,
                   chain_hash, signature_algorithm, classification
            FROM events
            ORDER BY id DESC
            LIMIT ?
        """, (n,))
        return [_row_to_dict(row) for row in cursor.fetchall()]


def read_by_id(record_id: int) -> Optional[Dict[str, Any]]:
    """
    Returns a single record by ID.
    """
    with _connect() as conn:
        cursor = conn.execute("""
            SELECT id, timestamp, event_type, input, context,
                   output, confidence, human_decision, notes,
                   chain_hash, signature_algorithm, classification
            FROM events WHERE id = ?
        """, (record_id,))
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None


def read_by_type(event_type: str) -> List[Dict[str, Any]]:
    """
    Returns all records matching a given event type.
    """
    with _connect() as conn:
        cursor = conn.execute("""
            SELECT id, timestamp, event_type, input, context,
                   output, confidence, human_decision, notes,
                   chain_hash, signature_algorithm, classification
            FROM events WHERE event_type = ?
            ORDER BY id ASC
        """, (event_type,))
        return [_row_to_dict(row) for row in cursor.fetchall()]


def print_readable(records: List[Dict[str, Any]]) -> None:
    """
    Prints records in a human-readable format.
    """
    if not records:
        print("  No records found.")
        return

    for r in records:
        print(f"\n  [{r['id']}] {r['timestamp']}")
        print(f"  Type:  {r['event_type']}")
        if r.get("classification"):
            print(f"  Class: {r['classification']}")
        if r.get("input"):
            text = r["input"][:80] + "..." if len(r["input"]) > 80 else r["input"]
            print(f"  Input: {text}")
        if r.get("output"):
            print(f"  Output: {r['output'][:80]}")
        if r.get("human_decision"):
            print(f"  Decision: {r['human_decision']}")
        if r.get("chain_hash"):
            print(f"  Chain:  {r['chain_hash'][:16]}...")
        print(f"  Sig:   {r.get('signature_algorithm', 'unknown')}")
        print("  " + "─" * 48)

# ─────────────────────────────────────────────────────────────────────────────
# QUERY — COMPOSABLE FILTERED READ
# ─────────────────────────────────────────────────────────────────────────────

def query(
    event_type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    classification_min: int = 0,
    identity: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    order: str = "desc",
) -> Dict[str, Any]:
    """
    Composable filtered query across the audit trail.

    All parameters are optional and combinable. Any subset of filters
    may be applied in a single call. This is the primary read interface
    for reporting, compliance, and audit purposes.

    Args:
        event_type:         Filter to a specific event type string.
                            Exact match. Examples: "CHECKPOINT", "SESSION_START".
        since:              ISO 8601 timestamp. Return records at or after
                            this time. Example: "2026-01-01T00:00:00+00:00"
        until:              ISO 8601 timestamp. Return records at or before
                            this time. Example: "2026-12-31T23:59:59+00:00"
        classification_min: Minimum classification level (inclusive).
                            0 = all records. 2 = personal data and above.
                            3 = sensitive/special categories and above.
        identity:           Filter by human_decision identity field.
                            Partial match (LIKE %identity%). Used to find
                            all records associated with a specific operator.
        search:             Full-text search across `input` and `notes` fields.
                            Partial match (LIKE %search%). Case-insensitive
                            in SQLite default collation.
                            Privacy note: search results may contain personal
                            data. The caller is responsible for ensuring the
                            query is authorized. In Stage 2 this parameter
                            will be enforced against the caller's authorization
                            level based on classification_min.
        limit:              Maximum records to return. Hard ceiling: 500.
                            Default: 50.
        offset:             Number of records to skip. Use with limit for
                            pagination. Default: 0.
        order:              Sort order. "desc" = newest first (default).
                            "asc" = oldest first.

    Returns:
        Dict with keys:
          records (list):  The matching records.
          total   (int):   Total matching records (before limit/offset).
                           Use this to compute page counts.
          limit   (int):   The limit applied.
          offset  (int):   The offset applied.
          filters (dict):  The filters that were applied, for audit purposes.

    Privacy note:
        Every call to query() with classification_min >= READ_LOG_THRESHOLD
        generates a READ_ACCESS event in the audit trail. Reads of sensitive
        data are as visible as writes (U3, crossover contract §8.3).
    """
    limit = min(max(1, limit), 500)
    offset = max(0, offset)
    order_sql = "ASC" if order.lower() == "asc" else "DESC"

    conditions: List[str] = []
    params: List[Any] = []

    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)

    if since:
        conditions.append("timestamp >= ?")
        params.append(since)

    if until:
        conditions.append("timestamp <= ?")
        params.append(until)

    if classification_min > 0:
        conditions.append("classification >= ?")
        params.append(classification_min)

    if identity:
        conditions.append("human_decision LIKE ?")
        params.append(f"%{identity}%")

    if search:
        conditions.append("(input LIKE ? OR notes LIKE ?)")
        params.append(f"%{search}%")
        params.append(f"%{search}%")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    select_cols = """
        id, timestamp, event_type, input, context,
        output, confidence, human_decision, notes,
        chain_hash, signature_algorithm, classification
    """

    count_sql = f"SELECT COUNT(*) FROM events {where_clause}"
    data_sql = f"""
        SELECT {select_cols}
        FROM events
        {where_clause}
        ORDER BY id {order_sql}
        LIMIT ? OFFSET ?
    """

    with _connect() as conn:
        # Total count (before pagination) for the caller to compute pages
        total = conn.execute(count_sql, params).fetchone()[0]

        # Paginated data
        rows = conn.execute(data_sql, params + [limit, offset]).fetchall()
        records = [_row_to_dict(row) for row in rows]

    # U3 — log this read if it touches sensitive data
    if classification_min >= READ_LOG_THRESHOLD or (
        not classification_min and any(
            r.get("classification", 0) >= READ_LOG_THRESHOLD
            for r in records
        )
    ):
        log_read_access(
            record_id=0,
            accessor_id="api",
            purpose=f"query: type={event_type} search={search} "
                    f"identity={identity} class>={classification_min}",
            classification=max(
                (r.get("classification", 0) for r in records), default=0
            )
        )

    filters_applied = {
        "event_type": event_type,
        "since": since,
        "until": until,
        "classification_min": classification_min,
        "identity": identity,
        "search": bool(search),  # boolean — don't log the search term itself
        "order": order,
    }

    return {
        "records": records,
        "total": total,
        "limit": limit,
        "offset": offset,
        "filters": filters_applied,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARIZE — AGGREGATE STATISTICS
# ─────────────────────────────────────────────────────────────────────────────

def summarize() -> Dict[str, Any]:
    """
    Returns aggregate statistics across the entire audit trail.

    Produces a compliance-ready summary suitable for dashboards,
    health checks, and regulatory reporting. Does not return any
    record content — only counts, timestamps, and distributions.

    Returns:
        Dict with keys:
          total_records      (int):   Total events in the audit trail.
          by_event_type      (dict):  Count per event_type.
          by_classification  (dict):  Count per classification level.
          earliest_timestamp (str):   Timestamp of the first record.
          latest_timestamp   (str):   Timestamp of the most recent record.
          chain_intact       (bool):  Result of verify_chain().
          chain_total        (int):   Total records verified in chain.
          chain_gaps         (int):   Number of chain gaps detected.

    This function never logs a READ_ACCESS event — it returns only
    aggregate statistics, not record content.
    """
    with _connect() as conn:
        # Total records
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

        if total == 0:
            return {
                "total_records": 0,
                "by_event_type": {},
                "by_classification": {},
                "earliest_timestamp": None,
                "latest_timestamp": None,
                "chain_intact": True,
                "chain_total": 0,
                "chain_gaps": 0,
            }

        # Count by event type
        type_rows = conn.execute("""
            SELECT event_type, COUNT(*) as cnt
            FROM events
            GROUP BY event_type
            ORDER BY cnt DESC
        """).fetchall()
        by_event_type = {row[0]: row[1] for row in type_rows}

        # Count by classification level
        class_rows = conn.execute("""
            SELECT classification, COUNT(*) as cnt
            FROM events
            GROUP BY classification
            ORDER BY classification ASC
        """).fetchall()
        # Map integer levels to human-readable labels
        level_labels = {
            0: "UNCLASSIFIED",
            1: "INTERNAL",
            2: "PERSONAL",
            3: "SENSITIVE",
            4: "RESTRICTED",
            5: "HIGHEST",
        }
        by_classification = {
            level_labels.get(row[0], str(row[0])): row[1]
            for row in class_rows
        }

        # Timestamp range
        earliest = conn.execute(
            "SELECT timestamp FROM events ORDER BY id ASC LIMIT 1"
        ).fetchone()[0]
        latest = conn.execute(
            "SELECT timestamp FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]

    # Chain integrity — verify the full chain
    chain = verify_chain()

    return {
        "total_records": total,
        "by_event_type": by_event_type,
        "by_classification": by_classification,
        "earliest_timestamp": earliest,
        "latest_timestamp": latest,
        "chain_intact": chain["intact"],
        "chain_total": chain["total"],
        "chain_gaps": len(chain["gaps"]),
    }

# ─────────────────────────────────────────────────────────────────────────────
# CHAIN VERIFICATION (C2)
# ─────────────────────────────────────────────────────────────────────────────

def verify_chain() -> Dict[str, Any]:
    """
    Verifies the integrity of the Merkle chain.

    Walks every record in sequence, recomputing the expected chain_hash
    from the previous record's content, and comparing it to the stored
    chain_hash. Any gap, deletion, or modification breaks the chain.

    Returns:
        Dict with keys:
          intact (bool): True if chain is unbroken
          total (int): Total records checked
          gaps (list): List of record IDs where chain breaks
          first_record_hash (str): Hash of the genesis record (publish this)
    """
    records = read_all()
    gaps = []
    prev_hash = None

    for idx, r in enumerate(records):
        if idx == 0:
            # Genesis record (first by id, regardless of its actual id value).
            # It has no predecessor, so chain_hash is expected to be None.
            prev_hash = _hash_record_content(r)
            continue

        stored = r.get("chain_hash")

        # Pre-chain records: written before Merkle chaining was introduced.
        # Both stored and expected are None — treat as intact, not a gap.
        if stored is None and prev_hash is None:
            prev_hash = _hash_record_content(r)
            continue

        if stored != prev_hash:
            gaps.append({
                "record_id": r["id"],
                "expected": prev_hash,
                "stored": stored
            })

        prev_hash = _hash_record_content(r)

    first_hash = _hash_record_content(records[0]) if records else None

    return {
        "intact": len(gaps) == 0,
        "total": len(records),
        "gaps": gaps,
        "first_record_hash": first_hash
    }


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    """
    Returns a connection to the memory database.
    Ensures the parent directory exists before connecting — this allows
    _connect() to be called safely even if initialize() has not yet run,
    which can happen in test environments that patch DB_PATH directly.
    """
    db_dir = os.path.dirname(os.path.abspath(DB_PATH))
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Converts a database row to a readable dictionary."""
    return {
        "id": row[0],
        "timestamp": row[1],
        "event_type": row[2],
        "input": row[3],
        "context": json.loads(row[4]) if row[4] else None,
        "output": row[5],
        "confidence": row[6],
        "human_decision": row[7],
        "notes": row[8],
        "chain_hash": row[9],
        "signature_algorithm": row[10],
        "classification": row[11]
    }


def _compute_chain_hash(conn: sqlite3.Connection) -> Optional[str]:
    """
    C2 — Computes the chain hash for the next record.

    Finds the most recent record and hashes its content.
    The new record will store this hash in its chain_hash field,
    creating a cryptographic link to the previous record.

    Returns None for the genesis record (first record in the chain).
    """
    cursor = conn.execute("""
        SELECT id, timestamp, event_type, input, context,
               output, confidence, human_decision, notes,
               chain_hash, signature_algorithm, classification
        FROM events
        ORDER BY id DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    if row is None:
        return None  # Genesis record — no previous hash

    prev = _row_to_dict(row)
    return _hash_record_content(prev)


def _hash_record_content(record_dict: Dict[str, Any]) -> str:
    """
    Produces a deterministic SHA-256 hash of a record's content.
    Used for Merkle chain linking.
    """
    # Canonical representation — sort keys for determinism
    content = json.dumps({
        "id": record_dict["id"],
        "timestamp": record_dict["timestamp"],
        "event_type": record_dict["event_type"],
        "input": record_dict["input"],
        "context": record_dict["context"],
        "output": record_dict["output"],
        "confidence": record_dict["confidence"],
        "human_decision": record_dict["human_decision"],
        "notes": record_dict["notes"],
        "classification": record_dict["classification"]
    }, sort_keys=True, default=str)

    return hashlib.sha256(content.encode("utf-8")).hexdigest()
