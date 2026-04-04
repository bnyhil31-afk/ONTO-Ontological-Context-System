"""
main.py

The entry point. The start of every session.
This is where everything comes together.

Boot → Verify → Authenticate → Remember → Graph → Listen → Understand
     → Present → Checkpoint → Repeat

Plain English: Run this to start the system.
Type anything. The system will understand, respond, and ask what to do next.
Everything is recorded. Nothing is hidden.

Run with:  python3 main.py

Encryption (item 2.01):
  When AUTH_REQUIRED=true and a passphrase is configured, the database
  is kept encrypted on disk at all times. On boot, it is decrypted to
  a session path in the same directory. On shutdown, it is re-encrypted
  and the session file is removed. Development mode (the default) skips
  this entirely — no passphrase required, no encryption.
"""
import sys as _sys
if _sys.platform == "win32":
    _sys.stdout.reconfigure(encoding="utf-8")
    _sys.stderr.reconfigure(encoding="utf-8")

import os
import shutil
import sqlite3
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.auth import auth_manager
from core.config import config
from core.encryption import encryption
from core.verify import verify_principles
from modules import checkpoint, contextualize, graph, intake, memory, surface


# ---------------------------------------------------------------------------
# ENCRYPTION SESSION STATE
# ---------------------------------------------------------------------------
# These three module-level variables track whether this session is
# running in encrypted mode and where the session files live.
#
# Development mode (default): all three stay at their initial values
# and no encryption operations are performed.
# ---------------------------------------------------------------------------

_encryption_active: bool = False
_session_db_path: Optional[str] = None    # plaintext path used during session
_original_db_path: Optional[str] = None  # permanent path on disk (encrypted)


# ─────────────────────────────────────────────────────────────────────────────
# BOOT SEQUENCE
# ─────────────────────────────────────────────────────────────────────────────

def boot() -> None:
    """
    Everything that must happen before the system is ready.
    Runs in order. Without exception.

    Steps:
        1. Verify the principles are intact
        2. Authenticate the operator (if configured)
        3. Initialize permanent memory (decrypt if authenticated)
        4. Initialize the relationship graph
        5. Rebuild the context field from past sessions
    """
    global _encryption_active, _session_db_path, _original_db_path

    print("\n" + "═" * 60)
    print("  ONTO — Ontological Context System")
    print("  Version 1.0 — MVP")
    print("═" * 60)

    # 1. Verify the principles — always first, before anything else.
    #    If the principles file has been altered, the system stops here.
    print("\n  [1/5] Verifying principles...")
    verify_principles()
    print("        Principles intact. ✓")

    # 2. Authenticate.
    #    Development mode: auth_manager.authenticate() returns success
    #    automatically when AUTH_REQUIRED=false and no auth is configured.
    #    Production mode: displays the verification phrase, prompts for
    #    passphrase, verifies with Argon2id + constant-time comparison.
    print("  [2/5] Authenticating...")
    auth_result = auth_manager.authenticate()

    if not auth_result.success:
        print(f"\n  Authentication failed: {auth_result.reason}\n")
        sys.exit(1)

    if auth_manager.is_configured():
        print(f"        Authenticated as {auth_result.identity}. ✓")
    else:
        print("        Development mode — no authentication configured. ✓")

    # 3. Initialize memory.
    #    If a passphrase was returned, we are in production mode:
    #      a. Derive the AES-256-GCM key from the passphrase (Argon2id).
    #      b. Decrypt the database from its permanent encrypted path to
    #         a session-specific plaintext path.
    #      c. Redirect memory.DB_PATH to the session path — graph.py
    #         follows automatically since it uses the same module var.
    #      d. Clear the passphrase immediately after key derivation —
    #         the key lives in memory; the passphrase does not.
    print("  [3/5] Initializing memory...")

    if auth_result.passphrase:
        _original_db_path = config.DB_PATH
        _session_db_path = _original_db_path + ".session"

        encryption.initialize(auth_result.passphrase, _original_db_path)
        auth_result.clear_passphrase()  # clear as soon as the key is derived

        if os.path.exists(_original_db_path):
            try:
                decrypted = encryption.decrypt_database(
                    _original_db_path, _session_db_path
                )
                if not decrypted:
                    # DB exists but is not yet encrypted — first session
                    # after enabling auth on an existing installation.
                    shutil.copy2(_original_db_path, _session_db_path)
            except Exception as _exc:
                # Decryption failed — wrong key, corrupted file, etc.
                # Do NOT continue: if we proceed with an empty DB and
                # shut down cleanly, the empty DB would overwrite the
                # encrypted original, destroying all historical data.
                encryption.clear_key()
                print("\n  ═" * 35)
                print("  CANNOT START SESSION — DECRYPTION FAILED")
                print("  ═" * 35)
                print(f"\n  Details: {_exc}")
                print(
                    "\n  The database could not be decrypted. "
                    "Possible causes:\n"
                    "    - Wrong passphrase\n"
                    "    - Corrupted database file\n"
                    "    - Salt file mismatch\n"
                    "\n  The encrypted file has NOT been modified."
                    "\n  Re-run and enter the correct passphrase.\n"
                )
                sys.exit(1)

        memory.DB_PATH = _session_db_path
        _encryption_active = True

    memory.initialize()
    print("        Memory ready. ✓")

    # 4. Initialize the relationship graph.
    #    graph.py uses memory.DB_PATH, so it follows the session path
    #    automatically if encryption is active.
    print("  [4/5] Initializing relationship graph...")
    graph.initialize()
    graph.decay()
    print("        Graph ready. ✓")

    # 5. Rebuild the context field from past sessions.
    print("  [5/5] Rebuilding context field...")
    field_size: int = contextualize.load_from_memory()
    print(f"        Field restored. {field_size} past entries loaded. ✓")

    memory.record(
        event_type="BOOT",
        notes=f"System started. Field size: {field_size}"
    )

    print("\n  System ready. Type anything to begin.")
    print("  Type 'history' to see past records.")
    print("  Type 'quit' or press Ctrl+C to exit.\n")
    print("═" * 60 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP — THE DANCE
# ─────────────────────────────────────────────────────────────────────────────

def run() -> None:
    """
    The main loop — the dance between human and system.
    Receives input → understands it → presents it → checks with human
    → repeats. Runs until the human chooses to stop.
    """
    while True:
        try:
            raw: str = input("\n  You: ").strip()
        except (KeyboardInterrupt, EOFError):
            _shutdown()
            break

        if not raw:
            continue

        # ── Built-in commands ─────────────────────────────────────────

        if raw.lower() in ("quit", "exit", "q"):
            _shutdown()
            break

        if raw.lower() == "history":
            _show_history()
            continue

        if raw.lower() == "help":
            _show_help()
            continue

        # ── The five-step loop ────────────────────────────────────────

        # Step 1: Intake
        package: Dict[str, Any] = intake.receive(raw)

        # Step 2: Contextualize
        enriched: Dict[str, Any] = contextualize.build(package)

        # Step 3: Surface
        surfaced: Dict[str, Any] = surface.present(enriched)

        # Step 4: Checkpoint
        result: Dict[str, Any] = checkpoint.run(surfaced, enriched)

        # Step 5: Act on decision
        action: str = result.get("action", "PROCEED")

        if action == "STOP":
            _shutdown()
            break
        elif action == "CLARIFY":
            print("\n  Please add more context and try again.")
        elif action == "REJECT":
            print("\n  Understood. That has been recorded.")
        elif action == "SKIP":
            print("\n  Skipped. Moving on.")
        # PROCEED — loop continues naturally


# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _show_history() -> None:
    """Shows the most recent memory records in plain language."""
    print("\n" + "─" * 60)
    print("  RECENT HISTORY (last 10 records)")
    print("─" * 60)
    records: List[Dict[str, Any]] = memory.read_recent(10)
    memory.print_readable(records)
    print("─" * 60)


def _show_help() -> None:
    """Shows available commands."""
    print("""
  AVAILABLE COMMANDS
  ──────────────────
  [anything]  Type any input to begin the understanding loop
  history     Show recent records
  help        Show this message
  quit        Exit the session
    """)


def _shutdown() -> None:
    """
    Records a clean shutdown and exits gracefully.

    If encryption is active:
      1. Checkpoint WAL into the main DB file.
      2. Encrypt the session DB in place.
      3. Move the encrypted file to the permanent location.
      4. Remove WAL sidecar files.
      5. Clear the encryption key from memory.

    This ensures the database is never left unencrypted on disk
    between sessions. If any step fails, the session file is
    preserved as a plaintext backup with a warning.
    """
    global _encryption_active, _session_db_path, _original_db_path

    memory.record(event_type="HALT", notes="Session ended normally.")

    if _encryption_active and _session_db_path and _original_db_path:
        print("  Saving and encrypting session...")
        try:
            # Checkpoint: merge WAL into the main DB file so the
            # plaintext file is self-contained before we encrypt it.
            conn = sqlite3.connect(_session_db_path)
            conn.execute("PRAGMA wal_checkpoint(FULL)")
            conn.close()

            # Encrypt the session file in place.
            encryption.encrypt_database(_session_db_path)

            # Move the encrypted session file to the permanent location.
            shutil.move(_session_db_path, _original_db_path)

            # Remove WAL sidecar files — they are no longer needed.
            for _p in [
                _session_db_path + "-wal",
                _session_db_path + "-shm",
                _original_db_path + "-wal",
                _original_db_path + "-shm",
            ]:
                if os.path.exists(_p):
                    os.remove(_p)

            print("        Encrypted and saved. ✓")

        except Exception as _exc:
            print(f"\n  Warning: encryption error on shutdown.")
            print(f"  Details: {_exc}")
            print(f"  Session data preserved at: {_session_db_path}")
            print(f"  Re-run the system to retry encryption.\n")

        finally:
            # Always clear the key — even if encryption failed.
            encryption.clear_key()
            _encryption_active = False

    print("\n  Session ended. All records saved.\n")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    boot()
    run()
