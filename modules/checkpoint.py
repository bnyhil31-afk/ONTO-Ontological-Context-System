"""
modules/checkpoint.py

This is where the system stops and asks the human.
Nothing significant happens without this moment.
The human decides. The system records. The world continues.

Changes from v1 (REVIEW_001 findings C4 and U4):

  C4 — Safe messaging: when a CRISIS signal is present, the checkpoint
       displays configured crisis response text before asking anything.
       The text follows AFSP/SAMHSA/WHO safe messaging guidelines.
       Response text is configurable in core/config.py.

  U4 — Automation bias warning: every non-safety checkpoint now displays
       a reminder that the system presents examined context, not conclusions.
       Required by EU AI Act Article 14(4)(b). Configurable in core/config.py.

Plain English: This is where you stay in charge.
The system shows you what it sees.
You tell it what to do.
It writes that down forever.

This is Principles III (Freedom) and VIII (Integrity) — in code.
"""

from modules import memory

# ─────────────────────────────────────────────────────────────────────────────
# CHECKPOINT THRESHOLDS
# When weight or safety concern is above these — always ask human.
# ─────────────────────────────────────────────────────────────────────────────

ALWAYS_ASK_WEIGHT = 0.65     # High weight inputs always get a checkpoint
ALWAYS_ASK_CONFIDENCE = 0.50  # Low confidence always gets a checkpoint


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CHECKPOINT FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def run(surface: dict, enriched_package: dict) -> dict:
    """
    Presents the surface to the human and asks for their decision.
    Always records the human's response as permanent ground truth.

    C4 — If a CRISIS signal is present, displays configured safe messaging
         text before any other content. The human's response is still
         recorded. The system never auto-responds to crisis signals.

    U4 — Displays automation bias warning at every non-safety checkpoint.
         EU AI Act Article 14(4)(b): users must be helped to remain aware
         of the tendency to over-rely on AI outputs.

    Returns a checkpoint dict with:
      decision    — what the human chose
      action      — what should happen next
      skipped     — True if checkpoint was not needed
      record_id   — permanent audit record ID
    """
    from core.config import config

    input_text = enriched_package.get("clean", "")
    confidence = surface.get("confidence", 0.5)
    weight = surface.get("weight", 0.5)
    safe = surface.get("safe", True)
    safety_info = enriched_package.get("safety")

    # ── C4: Crisis signal — safe messaging first, always ─────────────────────
    # If the intake detected a CRISIS signal, display configured crisis
    # response text before anything else. This is not optional.
    # The human sees this before they see any system output.
    if safety_info and safety_info.get("level") == "CRISIS":
        print(config.CRISIS_RESPONSE_TEXT)
        print(surface.get("display", ""))

        decision = _ask_human(
            prompt=(
                "How would you like to respond? "
                "(Press Enter to take no action)"
            ),
            options=None
        )
        record_id = memory.record(
            event_type="CHECKPOINT",
            input_data=input_text,
            human_decision=decision or "NO_ACTION",
            notes=(
                "CRISIS checkpoint. Safe messaging displayed. "
                "Human response recorded. "
                f"Resources shown: {config.CRISIS_RESOURCES_BRIEF}"
            ),
            classification=enriched_package.get("classification", 0)
        )
        return {
            "decision": decision or "NO_ACTION",
            "action": "CRISIS_FOLLOWUP",
            "skipped": False,
            "record_id": record_id
        }

    # ── Standard safety checkpoint (HARM or INTEGRITY) ───────────────────────
    if not safe:
        print(surface.get("display", ""))
        decision = _ask_human(
            prompt="Is there anything I can help you with right now?",
            options=None
        )
        record_id = memory.record(
            event_type="CHECKPOINT",
            input_data=input_text,
            human_decision=decision,
            notes="Safety checkpoint — human response recorded.",
            classification=enriched_package.get("classification", 0)
        )
        return {
            "decision": decision,
            "action": "SAFETY_FOLLOWUP",
            "skipped": False,
            "record_id": record_id
        }

    # ── Display what the system sees ──────────────────────────────────────────
    print(surface.get("display", ""))

    # ── U4: Automation bias warning ───────────────────────────────────────────
    # Displayed at every substantive checkpoint.
    # EU AI Act Article 14(4)(b) requires this.
    # Not shown for auto-proceed (low weight, high confidence).
    needs_checkpoint = (
        weight >= ALWAYS_ASK_WEIGHT
        or confidence <= ALWAYS_ASK_CONFIDENCE
    )

    if not needs_checkpoint:
        record_id = memory.record(
            event_type="CHECKPOINT",
            input_data=input_text,
            output="AUTO_PROCEED",
            human_decision="AUTO_PROCEED",
            confidence=confidence,
            notes="Routine input — checkpoint skipped. Auto-proceeded.",
            classification=enriched_package.get("classification", 0)
        )
        print(f"\n  [AUTO] Routine input. Proceeding.")
        return {
            "decision": "AUTO_PROCEED",
            "action": "PROCEED",
            "skipped": True,
            "record_id": record_id
        }

    # ── Ask human — with automation bias reminder ─────────────────────────────
    print(config.AUTOMATION_BIAS_WARNING)

    decision = _ask_human(
        prompt="What would you like to do?",
        options=["proceed", "veto", "flag", "defer"]
    )

    action = _decision_to_action(decision)

    record_id = memory.record(
        event_type="CHECKPOINT",
        input_data=input_text,
        output=action,
        human_decision=decision,
        confidence=confidence,
        notes=(
            f"Human checkpoint. Weight: {weight:.2f}. "
            f"Confidence: {confidence:.2f}. Decision: {decision}."
        ),
        classification=enriched_package.get("classification", 0)
    )

    return {
        "decision": decision,
        "action": action,
        "skipped": False,
        "record_id": record_id
    }


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _ask_human(
    prompt: str,
    options: list = None
) -> str:
    """
    Presents a prompt to the human and records their response.
    Veto is always the default — the human must actively choose to proceed.

    Plain English: You are always asked. You always choose.
    Not choosing is a valid choice — it means stop.
    """
    print(f"\n  {prompt}")

    if options:
        option_str = " | ".join(options)
        print(f"  Options: {option_str}")
        print(f"  (Press Enter to veto / take no action)\n")

    try:
        response = input("  > ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        response = ""

    # Empty response means veto — not proceed
    if not response:
        return "veto"

    # Match to known options if provided
    if options:
        for option in options:
            if response.startswith(option[0]) or response == option:
                return option
        # Unrecognised input — treat as veto
        return "veto"

    return response


def _decision_to_action(decision: str) -> str:
    """Maps a human decision to a system action."""
    mapping = {
        "proceed": "PROCEED",
        "veto": "VETO",
        "flag": "FLAG_FOR_REVIEW",
        "defer": "DEFER",
    }
    return mapping.get(decision, "VETO")
