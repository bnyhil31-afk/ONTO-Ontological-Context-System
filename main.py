"""
main.py

The entry point. The start of every session.
This is where everything comes together.

Boot → Verify → Remember → Listen → Understand → Present → Checkpoint → Repeat

Plain English: Run this to start the system.
Type anything. The system will understand, respond, and ask what to do next.
Everything is recorded. Nothing is hidden.

Run with:  python main.py
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.verify import verify_principles
from modules import memory, intake, contextualize, surface, checkpoint


# ─────────────────────────────────────────────────────────────────────────────
# BOOT SEQUENCE
# ─────────────────────────────────────────────────────────────────────────────

def boot():
    """
    Everything that must happen before the system is ready.
    In order. Without exception.
    """
    print("\n" + "═" * 60)
    print("  ONTO — Ontological Context System")
    print("  Version 1.0 — MVP")
    print("═" * 60)

    # 1. Verify the principles — always first
    print("\n  [1/3] Verifying principles...")
    verify_principles()
    print("        Principles intact. ✓")

    # 2. Initialize memory
    print("  [2/3] Initializing memory...")
    memory.initialize()
    print("        Memory ready. ✓")

    # 3. Rebuild the field from past sessions
    print("  [3/3] Rebuilding context field...")
    field_size = contextualize.load_from_memory()
    print(f"        Field restored. {field_size} past entries loaded. ✓")

    # Record boot
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

def run():
    """
    The main loop.
    Receives input → understands it → presents it → checks with human → repeats.
    """
    while True:
        try:
            raw = input("\n  You: ").strip()
        except (KeyboardInterrupt, EOFError):
            _shutdown()
            break

        if not raw:
            continue

        # ── Built-in commands ─────────────────────────────────────────────────
        if raw.lower() in ("quit", "exit", "q"):
            _shutdown()
            break

        if raw.lower() == "history":
            _show_history()
            continue

        if raw.lower() == "help":
            _show_help()
            continue

        # ── The five-step loop ────────────────────────────────────────────────

        # Step 1: Intake
        package = intake.receive(raw)

        # Step 2: Contextualize
        enriched = contextualize.build(package)

        # Step 3: Surface
        surfaced = surface.present(enriched)

        # Step 4: Checkpoint
        result = checkpoint.run(surfaced, enriched)

        # Step 5: Act on decision
        action = result.get("action", "PROCEED")

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

def _show_history():
    """Shows recent memory records in plain language."""
    print("\n" + "─" * 60)
    print("  RECENT HISTORY (last 10 records)")
    print("─" * 60)
    records = memory.read_recent(10)
    memory.print_readable(records)
    print("─" * 60)


def _show_help():
    """Shows available commands."""
    print("""
  AVAILABLE COMMANDS
  ──────────────────
  [anything]  Type any input to begin the understanding loop
  history     Show recent records
  help        Show this message
  quit        Exit the session
    """)


def _shutdown():
    """Graceful shutdown with record."""
    memory.record(event_type="HALT", notes="Session ended normally.")
    print("\n  Session ended. All records saved.\n")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    boot()
    run()
