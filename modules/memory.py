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
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "memory.db")


# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

def initialize():
    """
    Creates the database and tables if they don't exist.
    Safe to run multiple times — will never overwrite existing data.
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
        # Prevent deletion or update — append only
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
    context: Optional[dict] = None,
    output: Optional[str] = None,
    confidence: Optional[float] = None,
    human_decision: Optional[str] = None,
    notes: Optional[str] = None
) -> int:
    """
    Records a single event permanently.
    Returns the record ID for reference.

    event_type options:
      INTAKE      — new input received
      CONTEXT     — context field updated
      SURFACE     — options presented to human
      CHECKPOINT  — human decision recorded
      SAFETY      — safety flag raised
      ERROR       — something went wrong
      BOOT        — system started
      HALT        — system stopped
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    context_str = json.dumps(context) if context else None

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

def read_all() -> list:
    """Returns every record in plain readable form."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM events ORDER BY id ASC
        """).fetchall()
    return [_row_to_dict(row) for row in rows]


def read_by_type(event_type: str) -> list:
    """Returns all records of a specific type."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM events WHERE event_type = ? ORDER BY id ASC
        """, (event_type,)).fetchall()
    return [_row_to_dict(row) for row in rows]


def read_recent(limit: int = 10) -> list:
    """Returns the most recent records."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT * FROM events ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
    return [_row_to_dict(row) for row in reversed(rows)]


def print_readable(records: list):
    """Prints records in plain human-readable format."""
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

def _connect():
    """Opens a database connection."""
    return sqlite3.connect(DB_PATH)


def _row_to_dict(row) -> dict:
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
        "notes": row[8]
    }
