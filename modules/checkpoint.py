"""
modules/checkpoint.py

The pause.
This is where the system stops and asks the human.
Nothing significant happens without this moment.
The human decides. The system records. The world continues.

Plain English: This is where you stay in charge.
The system shows you what it sees.
You tell it what to do.
It writes that down forever.

This is Principles III (Freedom) and VIII (Integrity) — in code.
"""

import sys
from typing import Any, Dict, List, Optional, Tuple
from modules import memory

# ─────────────────────────────────────────────────────────────────────────────
# CHECKPOINT THRESHOLDS
# When weight or confidence crosses these — always ask the human.
# ─────────────────────────────────────────────────────────────────────────────

ALWAYS_ASK_WEIGHT: float = 0.65    # High weight inputs always get a checkpoint
ALWAYS_ASK_CONFIDENCE: float = 0.50  # Low confidence always gets a checkpoint


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CHECKPOINT FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def run(
    surface: Dict[str, Any],
    enriched_package: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Presents the surface to the human and asks for their decision.
    Always records the human's response as permanent ground truth.

    Args:
        surface: The output from modules/surface.py.
        enriched_package: The enriched package from modules/contextualize.py.

    Returns:
        Dict containing:
            decision    — what the human chose
            action      — what should happen next
            skipped     — True if checkpoint was not needed
            record_id   — permanent audit record ID
    """
    input_text: str = enriched_package.get("clean", "")
    confidence: float = surface.get("confidence", 0.5)
    weight: float = surface.get("weight", 0.5)
    safe: bool = surface.get("safe", True)

    # ── Safety — always checkpoint, no exceptions ─────────────────────────────
    if not safe:
        print(surface["display"])
        decision: str = _ask_human(
            prompt="Is there anything I can help you with right now?",
            options=None
        )
        record_id: int = memory.record(
            event_type="CHECKPOINT",
            input_data=input_text,
            human_decision=decision,
            notes="Safety checkpoint — human response recorded."
        )
        return {
            "decision": decision,
            "action": "SAFETY_FOLLOWUP",
            "skipped": False,
            "record_id": record_id
        }

    # ── Display what the system sees ──────────────────────────────────────────
    print(surface["display"])

    # ── Decide if a checkpoint is needed ──────────────────────────────────────
    needs_checkpoint: bool = (
        weight >= ALWAYS_ASK_WEIGHT or
        confidence <= ALWAYS_ASK_CONFIDENCE
    )

    if not needs_checkpoint:
        record_id = memory.record(
            event_type="CHECKPOINT",
            input_data=input_text,
            output="AUTO_PROCEED",
            human_decision="AUTO_PROCEED",
            confidence=confidence,
            notes="Routine input — checkpoint skipped. Auto-proceeded."
        )
        print(
            f"\n  [AUTO] Routine input. Proceeding. "
            f"(Confidence: {confidence*100:.0f}%)"
        )
        return {
            "decision": "AUTO_PROCEED",
            "action": "PROCEED",
            "skipped": True,
            "record_id": record_id
        }

    # ── Human checkpoint ──────────────────────────────────────────────────────
    print("\n  ┌─────────────────────────────────────────────────────────┐")
    print("  │  YOUR DECISION IS NEEDED                                │")
    print("  └─────────────────────────────────────────────────────────┘")

    if confidence <= ALWAYS_ASK_CONFIDENCE:
        print(
            f"  (My confidence is low: {confidence*100:.0f}%. "
            f"Your judgment matters here.)\n"
        )

    decision = _ask_human(
        prompt="How would you like to proceed?",
        options=[
            ("proceed", "Accept this and move forward"),
            ("reject",  "This is wrong or not useful"),
            ("clarify", "I need to add more context"),
            ("skip",    "Skip this for now"),
            ("stop",    "Stop the session")
        ]
    )

    # Determine next action
    action_map: Dict[str, str] = {
        "proceed": "PROCEED",
        "reject":  "REJECT",
        "clarify": "CLARIFY",
        "skip":    "SKIP",
        "stop":    "STOP"
    }
    action: str = action_map.get(decision.lower(), "PROCEED")

    # Record the human's decision permanently
    record_id = memory.record(
        event_type="CHECKPOINT",
        input_data=input_text,
        output=action,
        human_decision=decision,
        confidence=confidence,
        notes=f"Human checkpoint completed. Action: {action}"
    )

    print(f"\n  [RECORDED] Your decision has been saved. Record #{record_id}")

    return {
        "decision": decision,
        "action": action,
        "skipped": False,
        "record_id": record_id
    }


# ─────────────────────────────────────────────────────────────────────────────
# ASK HUMAN — PLAIN, CLEAR PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

def _ask_human(
    prompt: str,
    options: Optional[List[Tuple[str, str]]] = None
) -> str:
    """
    Asks the human a question and waits for their answer.
    If options are provided, displays them clearly.
    Always accepts a free-text response as fallback.

    Args:
        prompt: The question to ask the human.
        options: Optional list of (key, description) tuples to display
                 as choices. If None, accepts any free-text response.

    Returns:
        str: The human's response, stripped of whitespace.
    """
    print(f"\n  {prompt}")

    if options:
        print()
        for key, description in options:
            print(f"    [{key}]  {description}")
        print()

    while True:
        try:
            response: str = input("  > ").strip()
            if response:
                return response
            print("  Please enter a response.")
        except (KeyboardInterrupt, EOFError):
            print("\n  [Session ended by user]")
            memory.record(
                event_type="HALT",
                notes="Session ended by user at checkpoint."
            )
            sys.exit(0)
