"""
modules/surface.py

The system's voice.
This is where understanding becomes communication.
It takes everything the system has built and presents it clearly —
with honest confidence levels and plain language.

Plain English: This is how the system talks to you.
It tells you what it sees, what it thinks, and how sure it is.
It never pretends to know more than it does.

This is Principles IV (Truth) and IX (Humility) — in code.
"""

from typing import Any, Dict, List, Optional
from modules import memory

# ─────────────────────────────────────────────────────────────────────────────
# CONFIDENCE LANGUAGE
# Plain English descriptions of confidence levels.
# ─────────────────────────────────────────────────────────────────────────────

def _confidence_label(score: float) -> str:
    """
    Translates a 0.0-1.0 confidence score into plain, honest language.

    Args:
        score: Confidence value between 0.0 and 1.0.

    Returns:
        str: A plain English description of the confidence level.
    """
    if score >= 0.85:
        return "I am quite confident about this."
    elif score >= 0.65:
        return "I am reasonably confident, but you should verify."
    elif score >= 0.40:
        return "I am not very sure — please treat this as a starting point."
    else:
        return "I have very low confidence here. Human judgment is essential."


def _weight_label(weight: float) -> str:
    """
    Describes how much attention this input deserves.

    Args:
        weight: Attention weight between 0.0 and 1.0.

    Returns:
        str: A plain English description of the attention level.
    """
    if weight >= 0.75:
        return "This deserves careful human attention."
    elif weight >= 0.45:
        return "This warrants a thoughtful look."
    else:
        return "This appears routine."


# ─────────────────────────────────────────────────────────────────────────────
# SAFETY RESPONSE — ALWAYS FIRST
# ─────────────────────────────────────────────────────────────────────────────

SAFETY_RESPONSES: Dict[str, str] = {
    "CRISIS": """
  ┌─────────────────────────────────────────────────────────┐
  │  I want to pause here.                                  │
  │                                                         │
  │  Something in what you shared suggests you might be     │
  │  going through a really hard time right now.            │
  │                                                         │
  │  You matter. What you're feeling matters.               │
  │                                                         │
  │  Please reach out to someone who can help:              │
  │                                                         │
  │  • Call or text 988 (Suicide & Crisis Lifeline, US)     │
  │  • Text HOME to 741741 (Crisis Text Line)               │
  │  • Call 999 or 112 (Emergency, UK/EU)                   │
  │  • Go to your nearest emergency room                    │
  │  • Call someone you trust right now                     │
  │                                                         │
  │  I am here. But please also talk to a person.           │
  └─────────────────────────────────────────────────────────┘
""",
    "HARM": """
  ┌─────────────────────────────────────────────────────────┐
  │  I can't help with anything that could hurt someone.    │
  │  That's not what this system is for.                    │
  │                                                         │
  │  If you're in danger or someone else is — call 911      │
  │  or your local emergency number right now.              │
  │                                                         │
  │  If something else is going on — I'm here to listen.    │
  └─────────────────────────────────────────────────────────┘
""",
    "INTEGRITY": """
  ┌─────────────────────────────────────────────────────────┐
  │  I noticed a request to bypass my principles.           │
  │                                                         │
  │  I can't do that — and I won't.                         │
  │  These principles protect everyone, including you.      │
  │                                                         │
  │  If you have a concern about how the system works,      │
  │  please raise it openly. That's always welcome.         │
  └─────────────────────────────────────────────────────────┘
"""
}


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SURFACE FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def present(enriched_package: Dict[str, Any]) -> Dict[str, Any]:
    """
    Takes an enriched package from contextualize.py and produces
    a clear, honest, human-readable presentation.

    Args:
        enriched_package: A package from modules/contextualize.py
                          containing input data and context.

    Returns:
        Dict containing:
            display     — what to show the human
            confidence  — how sure the system is (0.0 to 1.0)
            weight      — how much attention this deserves (0.0 to 1.0)
            safe        — True if no safety flags were triggered
            record_id   — permanent audit record ID
    """
    safety: Optional[Dict[str, Any]] = enriched_package.get("safety")
    context: Dict[str, Any] = enriched_package.get("context", {})
    input_text: str = enriched_package.get("clean", "")
    input_type: str = enriched_package.get("input_type", "unknown")

    confidence: float = 1.0 - context.get("distance", 0.5)
    weight: float = context.get("weight", 0.5)

    # ── Safety response overrides everything ──────────────────────────────────
    if safety:
        level: str = safety.get("level", "HARM")
        display: str = SAFETY_RESPONSES.get(level, SAFETY_RESPONSES["HARM"])
        surface: Dict[str, Any] = {
            "display": display,
            "confidence": 1.0,
            "weight": 1.0,
            "safe": False,
            "record_id": None
        }
        record_id: int = memory.record(
            event_type="SURFACE",
            input_data=input_text,
            output=f"SAFETY RESPONSE: {level}",
            confidence=1.0,
            notes="Safety flag triggered — human attention required."
        )
        surface["record_id"] = record_id
        return surface

    # ── Normal response ───────────────────────────────────────────────────────
    lines: List[str] = []
    lines.append("\n" + "─" * 60)
    lines.append("  INPUT UNDERSTOOD")
    lines.append("─" * 60)
    lines.append(f"  You said:     {input_text[:80]}")
    lines.append(f"  Type:         {input_type.capitalize()}")
    complexity = enriched_package.get('complexity', 'unknown').capitalize()
    lines.append(f"  Complexity:   {complexity}")
    lines.append("")
    lines.append("  CONTEXT")
    lines.append(f"  {context.get('summary', '')}")
    lines.append("")

    if context.get("related_samples"):
        lines.append("  Related topics seen before:")
        for sample in context["related_samples"]:
            lines.append(f"    • {sample}")
        lines.append("")

    lines.append("  CONFIDENCE")
    lines.append(f"  {_confidence_label(confidence)}")
    lines.append(f"  Score: {confidence*100:.0f}%")
    lines.append("")
    lines.append("  ATTENTION LEVEL")
    lines.append(f"  {_weight_label(weight)}")
    lines.append("─" * 60)

    display = "\n".join(lines)

    record_id = memory.record(
        event_type="SURFACE",
        input_data=input_text,
        output=display,
        confidence=confidence,
        notes=f"Weight: {weight:.2f} | Type: {input_type}"
    )

    return {
        "display": display,
        "confidence": confidence,
        "weight": weight,
        "safe": True,
        "record_id": record_id
    }
