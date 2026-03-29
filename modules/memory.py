"""
modules/memory.py

The system's permanent memory.
Everything that happens is recorded here — honestly and completely.
The record never changes. It only grows.

Plain English: This is the system's journal.
Every action, every decision, every mistake — written down forever.
Anyone can read it. No one can erase it.

This is Principle VII: Memory — in code.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH: str = os.path.join(ROOT, "data", "memory.db")


# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

def initialize() -> bool:
    """
    Creates the database and tables if they don't exist.
    Safe to run multiple times — will never overwrite existing data.

    Returns:
        bool: True when initialization is complete.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                event_type  TEXT    NOT NULL,
                input       TEXT,
                context     TEXT,
                output      TEXT,
                confidence  REAL,
                human_decision TEXT,
                notes       TEXT
            )
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS prevent_delete
            BEFORE DELETE ON events
            BEGIN
                SELECT RAISE(ABORT, 'Records cannot be deleted. Memory is permanent.');
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS prevent_update
            BEFORE UPDATE ON events
            BEGIN
                SELECT RAISE(ABORT, 'Records cannot be changed. Memory is permanent.');
            END
        """)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# WRITE — APPEND ONLY
# ─────────────────────────────────────────────────────────────────────────────

def record(
    event_type: str,
    input_data: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    output: Optional[str] = None,
    confidence: Optional[float] = None,
    human_decision: Optional[str] = None,
    notes: Optional[str] = None
) -> int:
    """
    Records a single event permanently.
    Returns the record ID for reference.

    Args:
        event_type: The type of event being recorded.
            INTAKE      — new input received
            CONTEXT     — context field updated
            SURFACE     — options presented to human
            CHECKPOINT  — human decision recorded
            SAFETY      — safety flag raised
            ERROR       — something went wrong
            BOOT        — system started
            HALT        — system stopped
        input_data: The raw input that triggered this event.
        context: A dictionary of context data at time of event.
        output: What the system produced in response.
        confidence: How confident the system was (0.0 to 1.0).
        human_decision: What the human decided at checkpoint.
        notes: Any additional notes about this event.

    Returns:
        int: The unique ID of the newly created record.
    """
    timestamp: str = datetime.now(timezone.utc).isoformat()
    context_str: Optional[str] = json.dumps(context) if context else None

    with _connect() as conn:
        cursor = conn.execute("""
            INSERT INTO events
                (timestamp, event_type, input, context, output,
                 confidence, human_decision, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp, event_type, input_data, context_str,
            output, confidence, human_decision, notes
        ))
        return cursor.lastrowid


# ─────────────────────────────────────────────────────────────────────────────
# READ — ANYONE CAN READ
# ─────────────────────────────────────────────────────────────────────────────

def read_all() -> List[Dict[str, Any]]:
    """
    Returns every record in plain readable form, oldest first.

    Returns:
        List[Dict]: All records as readable dictionaries.
    """
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM events ORDER BY id ASC
        """).fetchall()
    return [_row_to_dict(row) for row in rows]


def read_by_type(event_type: str) -> List[Dict[str, Any]]:
    """
    Returns all records of a specific event type.

    Args:
        event_type: The event type to filter by (e.g. 'INTAKE', 'SAFETY').

    Returns:
        List[Dict]: Matching records as readable dictionaries.
    """
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM events WHERE event_type = ? ORDER BY id ASC
        """, (event_type,)).fetchall()
    return [_row_to_dict(row) for row in rows]


def read_recent(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Returns the most recently added records.

    Args:
        limit: Maximum number of records to return. Defaults to 10.

    Returns:
        List[Dict]: Most recent records in chronological order.
    """
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM events ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
    return [_row_to_dict(row) for row in reversed(rows)]


def print_readable(records: List[Dict[str, Any]]) -> None:
    """
    Prints records in plain human-readable format.

    Args:
        records: A list of record dictionaries from read_all(),
                 read_by_type(), or read_recent().
    """
    if not records:
        print("  No records found.")
        return
    for r in records:
        print(f"\n  [{r['id']}] {r['timestamp']} — {r['event_type']}")
        if r['input']:
            print(f"       Input:    {r['input'][:80]}")
        if r['output']:
            print(f"       Output:   {r['output'][:80]}")
        if r['confidence'] is not None:
            print(f"       Confidence: {r['confidence']*100:.0f}%")
        if r['human_decision']:
            print(f"       Human:    {r['human_decision']}")
        if r['notes']:
            print(f"       Notes:    {r['notes']}")


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    """
    Opens and returns a database connection.

    Returns:
        sqlite3.Connection: An active connection to the memory database.
    """
    return sqlite3.connect(DB_PATH)


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """
    Converts a raw database row into a readable dictionary.

    Args:
        row: A raw row returned from a SQLite query.

    Returns:
        Dict: A human-readable dictionary of the record's fields.
    """
    return {
        "id": row[0],
        "timestamp": row[1],
        "event_type": row[2],
        "input": row[3],
        "context": json.loads(row[4]) if row[4] else None,
        "output": row[5],
        "confidence": row[6],
        "human_decision": row[7],
        "notes": row[8]
    }
