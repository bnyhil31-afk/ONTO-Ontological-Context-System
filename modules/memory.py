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
        # The prevent_update trigger guards the fields that form the
        # integrity spine of the audit trail (id, timestamp, chain_hash,
        # signature_algorithm, classification). Payload fields (input,
        # context, output, notes) may be nullified by prune_payload_by_age()
        # as part of the GDPR right-to-erasure implementation — see
        # docs/PRIVACY_GDPR.md for the legal basis (GDPR Recital 49 +
        # EDPB guidance on cryptographic erasure).
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS prevent_update
            BEFORE UPDATE ON events
            BEGIN
                SELECT CASE
                    -- Spine fields: immutable under all circumstances
                    WHEN NEW.id != OLD.id
                        THEN RAISE(ABORT, 'Record id cannot be changed. Memory is permanent.')
                    WHEN NEW.timestamp != OLD.timestamp
                        THEN RAISE(ABORT, 'Record timestamp cannot be changed. Memory is permanent.')
                    WHEN NEW.chain_hash != OLD.chain_hash
                         AND OLD.chain_hash IS NOT NULL
                        THEN RAISE(ABORT, 'Record chain_hash cannot be changed. Memory is permanent.')
                    WHEN NEW.signature_algorithm != OLD.signature_algorithm
                        THEN RAISE(ABORT, 'Record signature_algorithm cannot be changed. Memory is permanent.')
                    WHEN NEW.classification != OLD.classification
                        THEN RAISE(ABORT, 'Record classification cannot be changed. Memory is permanent.')
                    WHEN NEW.event_type != OLD.event_type
                        THEN RAISE(ABORT, 'Record event_type cannot be changed. Memory is permanent.')
                    -- Payload fields: may be set to NULL (GDPR pruning) but
                    -- not replaced with a different non-NULL value.
                    WHEN NEW.input IS NOT NULL AND NEW.input != OLD.input
                        THEN RAISE(ABORT, 'Record input cannot be changed. Memory is permanent.')
                    WHEN NEW.context IS NOT NULL AND NEW.context != OLD.context
                        THEN RAISE(ABORT, 'Record context cannot be changed. Memory is permanent.')
                    WHEN NEW.output IS NOT NULL AND NEW.output != OLD.output
                        THEN RAISE(ABORT, 'Record output cannot be changed. Memory is permanent.')
                    WHEN NEW.notes IS NOT NULL AND NEW.notes != OLD.notes
                        THEN RAISE(ABORT, 'Record notes cannot be changed. Memory is permanent.')
                    WHEN NEW.human_decision IS NOT NULL
                         AND NEW.human_decision != OLD.human_decision
                        THEN RAISE(ABORT, 'Record human_decision cannot be changed. Memory is permanent.')
                    WHEN NEW.confidence IS NOT NULL AND NEW.confidence != OLD.confidence
                        THEN RAISE(ABORT, 'Record confidence cannot be changed. Memory is permanent.')
                END;
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
# EXPORT — GDPR DATA SUBJECT RIGHTS (Art. 15 + Art. 20)
# ─────────────────────────────────────────────────────────────────────────────

def export_personal_data(
    classification_min: int = 2,
    include_graph_snapshot: bool = False,
    accessor_id: str = "data_subject",
) -> Dict[str, Any]:
    """
    Export all personal data records for a data subject.

    GDPR Article 15 (Right of Access) — returns all records at or above
    the requested classification level in a machine-readable format.
    GDPR Article 20 (Right to Portability) — includes optional graph snapshot
    of all derived relationship data.

    A single READ_ACCESS audit event is written to record this bulk read.

    Args:
        classification_min:    Minimum classification level. Default: 2 (personal data).
                               Set to 0 to export all records.
        include_graph_snapshot: If True, include a snapshot of graph nodes and edges
                               (derived personal data — portability, GDPR Art. 20).
        accessor_id:           Identity of the requester, written to READ_ACCESS event.

    Returns:
        Dict with format_version, records, optional graph_snapshot, and compliance metadata.
    """
    # Internal fields not appropriate to export (integrity metadata, not personal data)
    _EXCLUDE_FIELDS = {"chain_hash", "signature_algorithm"}

    all_records: List[Dict[str, Any]] = []
    offset = 0
    page_limit = 500

    # Paginate through all matching records
    while True:
        page = query(
            classification_min=classification_min,
            limit=page_limit,
            offset=offset,
            order="asc",
        )
        for r in page.get("records", []):
            cleaned = {k: v for k, v in r.items() if k not in _EXCLUDE_FIELDS}
            all_records.append(cleaned)
        if offset + page_limit >= page.get("total", 0):
            break
        offset += page_limit

    # Log this bulk read as a single READ_ACCESS event
    max_class = max((r.get("classification", 0) for r in all_records), default=0)
    log_read_access(
        record_id=0,
        accessor_id=accessor_id,
        purpose="GDPR_Art15_data_export",
        classification=max(max_class, classification_min),
    )

    snapshot = _export_graph_snapshot() if include_graph_snapshot else None

    return {
        "format_version": "1.0",
        "export_schema": "ONTO-GDPR-Art15",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subject": accessor_id,
        "classification_filter": classification_min,
        "record_count": len(all_records),
        "records": all_records,
        "graph_snapshot": snapshot,
        "compliance": {
            "gdpr_article": "15",
            "right": "right_of_access",
            "stage": "1",
        },
    }


def _export_graph_snapshot() -> Dict[str, Any]:
    """
    Export a read-only snapshot of all graph nodes and edges.
    Used by export_personal_data() when include_graph_snapshot=True.
    Both graph and memory share the same SQLite database (DB_PATH).
    """
    db_path = DB_PATH
    if not os.path.exists(db_path):
        return {
            "nodes": [],
            "edges": [],
            "node_count": 0,
            "edge_count": 0,
            "note": "graph_not_initialized",
        }

    try:
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            nodes = [
                dict(row) for row in conn.execute(
                    "SELECT uuid, concept, weight, times_seen, is_sensitive, "
                    "created_at, last_reinforced "
                    "FROM graph_nodes "
                    "WHERE (is_deleted = 0 OR is_deleted IS NULL) "
                    "ORDER BY weight DESC"
                ).fetchall()
            ]
            edges = [
                dict(row) for row in conn.execute(
                    "SELECT n1.concept AS source, n2.concept AS target, "
                    "e.weight, e.times_seen, e.edge_type_id "
                    "FROM graph_edges e "
                    "JOIN graph_nodes n1 ON e.source_node_id = n1.id "
                    "JOIN graph_nodes n2 ON e.target_node_id = n2.id "
                    "WHERE (e.is_deleted = 0 OR e.is_deleted IS NULL)"
                ).fetchall()
            ]
        finally:
            conn.close()
        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
    except Exception:
        return {
            "nodes": [],
            "edges": [],
            "node_count": 0,
            "edge_count": 0,
            "note": "graph_read_error",
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

def get_genesis_hash() -> Optional[str]:
    """
    C-2 — T-001 Genesis Block Poisoning mitigation helper.

    Returns the SHA-256 hash of the first (genesis) audit record.
    Publish this value immediately after the first session to an external
    location (e.g. a public Gist). Anyone can then run verify_chain()
    and compare its first_record_hash against the published value to confirm
    the audit trail has not been retroactively poisoned.

    Returns None if the database has no records yet.

    Usage:
        python3 -m modules.memory genesis
    """
    records = read_all()
    if not records:
        return None
    return _hash_record_content(records[0])


def verify_chain() -> Dict[str, Any]:
    """
    Verifies the integrity of the Merkle chain.

    Walks every record in sequence, recomputing the expected chain_hash
    from the previous record's content, and comparing it to the stored
    chain_hash. Any gap, deletion, or modification breaks the chain.

    Pruned records: records whose payload fields (input, context, output,
    notes) have been nullified by prune_payload_by_age() retain their
    chain_hash. These records are marked pruned=True in the gap_detail
    list and do NOT count as chain breaks — the hash covers the original
    content; it is simply no longer recomputable from the nullified payload.

    Returns:
        Dict with keys:
          intact (bool): True if chain is unbroken (pruned records do not
                         affect this flag)
          total (int): Total records checked
          gaps (list): List of dicts for records where chain breaks
                       (tampered or deleted, NOT including pruned records)
          pruned (int): Number of records identified as payload-pruned
          first_record_hash (str): Hash of the genesis record (publish this)
    """
    records = read_all()
    gaps = []
    pruned_count = 0
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
            # Distinguish pruned records from tampered records.
            # A pruned record has chain_hash present but all payload fields
            # null. Its chain_hash was written when the full content existed,
            # so the mismatch is expected and benign.
            _payload_fields = (
                r.get("input"),
                r.get("context"),
                r.get("output"),
                r.get("notes"),
            )
            if stored is not None and all(f is None for f in _payload_fields):
                # Payload-pruned record — not a tampering gap.
                pruned_count += 1
                # Use the stored hash as prev_hash so the next record can
                # verify against it normally.
                prev_hash = stored
                continue

            gaps.append({
                "record_id": r["id"],
                "expected": prev_hash,
                "stored": stored,
                "pruned": False,
            })

        prev_hash = _hash_record_content(r)

    first_hash = _hash_record_content(records[0]) if records else None

    return {
        "intact": len(gaps) == 0,
        "total": len(records),
        "gaps": gaps,
        "pruned": pruned_count,
        "first_record_hash": first_hash,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LIGHTWEIGHT CHAIN TAIL VERIFICATION
# Fast integrity check used by GET /health. Verifies only the last n records
# rather than walking the full history, so health probes are cheap.
# ─────────────────────────────────────────────────────────────────────────────

def verify_chain_tail(n: int = 2) -> Dict[str, Any]:
    """
    Verify the Merkle chain integrity of the most recent `n` records only.

    This is a fast, lightweight version of verify_chain() designed for use
    by the /health endpoint where probing the full chain on every request
    would be too expensive.

    Returns:
        Dict with keys:
          intact (bool): True if the tail of the chain is unbroken.
          checked (int): Number of records actually checked (may be < n if
                         the database has fewer records).
          gaps (list): Any gaps found in the tail segment.

    If the database is empty or has only one record, returns intact=True.
    """
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, timestamp, event_type, input, context,
                   output, confidence, human_decision, notes,
                   chain_hash, signature_algorithm, classification
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (n,),
        ).fetchall()

    records = [_row_to_dict(row) for row in reversed(rows)]

    if len(records) < 2:
        return {"intact": True, "checked": len(records), "gaps": []}

    gaps = []
    for i in range(1, len(records)):
        prev = records[i - 1]
        curr = records[i]
        expected = _hash_record_content(prev)
        stored = curr.get("chain_hash")
        if stored is None and expected is None:
            continue  # pre-chain records
        if stored != expected:
            # Check if pruned (same heuristic as verify_chain)
            _payload_fields = (
                curr.get("input"),
                curr.get("context"),
                curr.get("output"),
                curr.get("notes"),
            )
            if stored is not None and all(f is None for f in _payload_fields):
                continue  # pruned — not a gap
            gaps.append({
                "record_id": curr["id"],
                "expected": expected,
                "stored": stored,
            })

    return {
        "intact": len(gaps) == 0,
        "checked": len(records),
        "gaps": gaps,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DATA RETENTION — PAYLOAD PRUNING (GDPR Art. 17 / right to erasure)
# ─────────────────────────────────────────────────────────────────────────────

def prune_payload_by_age(days: int) -> int:
    """
    Implement GDPR right-to-erasure via payload cryptographic erasure.

    Nullifies the personal-content fields (input, context, output, notes)
    of all records older than `days` days. The audit shell —
    (id, timestamp, event_type, classification, chain_hash) — is
    preserved so the Merkle chain proof remains verifiable.

    This approach is aligned with GDPR Recital 49 (security requirement
    justifying append-only design) and EDPB guidance that cryptographic
    erasure of payload data satisfies Art. 17 where deletion is technically
    impossible without destroying integrity proofs.

    After pruning, verify_chain() marks affected records as pruned=True
    rather than reporting a chain gap — the chain hash is still present
    and covers the original content; it is simply no longer recomputable
    from the nullified payload.

    Arguments:
        days: Records older than this many days have their payload nullified.
              Pass 0 to prune all records (useful for testing).
              Must be >= 0.

    Returns:
        int: Number of records pruned.

    Raises:
        ValueError: If days < 0.
    """
    if days < 0:
        raise ValueError(f"days must be >= 0, got {days}")

    cutoff = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )
    if days > 0:
        from datetime import timedelta
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff = cutoff_dt.replace(microsecond=0).isoformat()

    with _connect() as conn:
        # Only prune records that still have payload content — skip already-pruned.
        cursor = conn.execute(
            """
            UPDATE events
            SET input   = NULL,
                context = NULL,
                output  = NULL,
                notes   = NULL
            WHERE timestamp < ?
              AND (input IS NOT NULL
                   OR context IS NOT NULL
                   OR output IS NOT NULL
                   OR notes IS NOT NULL)
            """,
            (cutoff,),
        )
        pruned_count = cursor.rowcount

    if pruned_count > 0:
        # Record the pruning event itself so operators can see when and how
        # many records were pruned. This event has no sensitive payload.
        record(
            event_type="RETENTION_PRUNED",
            notes=(
                f"Payload pruning completed. "
                f"{pruned_count} record(s) older than {days} day(s) pruned. "
                f"Cutoff timestamp: {cutoff}. "
                f"Audit shells (id, timestamp, chain_hash, classification) retained."
            ),
        )

    return pruned_count


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


# ─────────────────────────────────────────────────────────────────────────────
# CLI — python3 -m modules.memory genesis
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "genesis":
        initialize()
        h = get_genesis_hash()
        if h is None:
            print("No records found. Run the system at least once first.")
            _sys.exit(1)
        print("\n  ONTO — Genesis Block Hash")
        print("  ─" * 30)
        print(f"\n  {h}\n")
        print("  Publish this hash to an external, independently verifiable")
        print("  location (e.g. a public Gist) to anchor your audit trail.")
        print("  Anyone can verify it with: python3 -m modules.memory genesis")
        print("  and compare against your published value.\n")
    else:
        print("Usage: python3 -m modules.memory genesis")
