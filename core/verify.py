"""
core/verify.py

The guardian of the principles.
This module runs on every boot and before every action.
If the principles have been altered in any way — the system stops.

Plain English: This is the lock on the foundation.
Nobody gets in if the foundation has been touched.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRINCIPLES_FILE: str = os.path.join(ROOT, "principles.txt")
HASH_FILE: str = os.path.join(ROOT, "core", "principles.hash")


# ─────────────────────────────────────────────────────────────────────────────
# HASHING
# ─────────────────────────────────────────────────────────────────────────────

def compute_hash(filepath: str) -> str:
    """
    Reads a file and returns its SHA-256 hash.
    SHA-256 is a one-way function — you cannot reverse it.
    If even one character changes, the hash changes completely.

    Args:
        filepath: The absolute path to the file to hash.

    Returns:
        str: A 64-character lowercase hexadecimal SHA-256 hash.
    """
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# FIRST RUN — SEAL THE PRINCIPLES
# ─────────────────────────────────────────────────────────────────────────────

def seal_principles() -> Dict[str, Any]:
    """
    Run once at project creation.
    Computes the hash of the principles and saves it permanently.
    After this — the principles are sealed.

    Returns:
        Dict: The sealed hash record containing the hash, timestamp,
              filename, algorithm, and a plain English note.
    """
    if not os.path.exists(PRINCIPLES_FILE):
        print("[CRITICAL] principles.txt not found. Cannot continue.")
        sys.exit(1)

    principles_hash: str = compute_hash(PRINCIPLES_FILE)
    sealed_at: str = datetime.now(timezone.utc).isoformat()

    record: Dict[str, Any] = {
        "sealed_at": sealed_at,
        "hash": principles_hash,
        "file": "principles.txt",
        "algorithm": "SHA-256",
        "note": (
            "This hash was computed at the moment the principles were finalized. "
            "It cannot be changed. Any modification to principles.txt will cause "
            "the system to refuse to operate."
        )
    }

    os.makedirs(os.path.dirname(HASH_FILE), exist_ok=True)
    with open(HASH_FILE, "w") as f:
        json.dump(record, f, indent=2)

    print(f"[SEALED] Principles locked at {sealed_at}")
    print(f"[HASH]   {principles_hash}")
    print(f"[NOTE]   Publish this hash publicly so anyone can verify it.")
    return record


# ─────────────────────────────────────────────────────────────────────────────
# VERIFY — RUNS EVERY TIME
# ─────────────────────────────────────────────────────────────────────────────

def verify_principles() -> bool:
    """
    Checks that the principles have not been changed since sealing.
    Stops the system completely if anything has changed.

    Returns:
        bool: True if principles are intact. Never returns False —
              instead halts the system if verification fails.
    """
    # Check principles file exists
    if not os.path.exists(PRINCIPLES_FILE):
        _halt("principles.txt is missing. The system cannot operate without it.")

    # Check hash record exists
    if not os.path.exists(HASH_FILE):
        _halt(
            "No sealed hash found. "
            "Either this is a new installation (run seal_principles()) "
            "or the hash file has been removed. "
            "The system cannot verify its own integrity."
        )

    # Load the sealed hash
    with open(HASH_FILE, "r") as f:
        record: Dict[str, Any] = json.load(f)

    sealed_hash: str = record.get("hash", "")
    current_hash: str = compute_hash(PRINCIPLES_FILE)

    if current_hash != sealed_hash:
        _halt(
            "THE PRINCIPLES HAVE BEEN ALTERED.\n"
            f"  Expected: {sealed_hash}\n"
            f"  Found:    {current_hash}\n"
            "This system will not operate with modified principles. "
            "Restore principles.txt to its original state to continue."
        )

    return True


# ─────────────────────────────────────────────────────────────────────────────
# HALT — THE SYSTEM STOPS AND EXPLAINS WHY
# ─────────────────────────────────────────────────────────────────────────────

def _halt(reason: str) -> None:
    """
    Stops everything. Prints a clear explanation. Exits.
    This is Principle VIII: Integrity — in code.

    Args:
        reason: A plain English explanation of why the system is halting.
    """
    print("\n" + "═" * 70)
    print("  SYSTEM HALTED — INTEGRITY CHECK FAILED")
    print("═" * 70)
    print(f"\n  Reason: {reason}\n")
    print("  This is not an error. This is the system working as intended.")
    print("  The principles protect everyone — including from this system itself.")
    print("\n" + "═" * 70 + "\n")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — FOR STANDALONE USE
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Principle verification tool."
    )
    parser.add_argument(
        "--seal",
        action="store_true",
        help="Seal the principles for the first time. Run once only."
    )
    args = parser.parse_args()

    if args.seal:
        seal_principles()
    else:
        if verify_principles():
            print("[OK] Principles verified. System integrity confirmed.")
