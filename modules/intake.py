"""
modules/intake.py

The system's front door.
Every input — from any source — comes through here first.
Nothing reaches the rest of the system without being received,
classified, and cleared for safety.

Plain English: This is the ear of the system.
It listens to everything. It judges nothing yet.
But it makes sure nothing harmful gets through unchecked.

This is Principles II (Life First) and V (Do No Harm) — in code.
"""

import re
from typing import Dict, List, Optional, Tuple, Any
from modules import memory

# ─────────────────────────────────────────────────────────────────────────────
# INPUT TYPES — WHAT KIND OF THING ARRIVED?
# ─────────────────────────────────────────────────────────────────────────────

INPUT_TYPES: Dict[str, str] = {
    "text":     "Plain written or spoken words",
    "number":   "A numerical value",
    "question": "A request for information",
    "command":  "A request to do something",
    "file":     "A file or document",
    "signal":   "A system-level signal",
    "unknown":  "Could not be classified"
}

# ─────────────────────────────────────────────────────────────────────────────
# SAFETY PATTERNS — THINGS THAT NEED IMMEDIATE ATTENTION
# ─────────────────────────────────────────────────────────────────────────────

SAFETY_PATTERNS: List[Tuple[str, str, str]] = [
    # Crisis language — mental health and physical safety
    (r"\b(kill\s*(my)?self|suicide|end\s*my\s*life|hurt\s*(my)?self|"
     r"don'?t\s*want\s*to\s*(live|be\s*here|exist))\b",
     "CRISIS", "Possible mental health crisis detected."),

    # Harm to others
    (r"\b(kill|harm|hurt|attack|destroy)\s+(him|her|them|you|someone|people)\b",
     "HARM", "Possible intent to harm others detected."),

    # System manipulation
    (r"\b(ignore\s*(your|the)\s*principles?|override|bypass|disable|"
     r"turn\s*off\s*(safety|principles?))\b",
     "INTEGRITY", "Attempt to override principles detected."),
]

# ─────────────────────────────────────────────────────────────────────────────
# MAIN INTAKE FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def receive(raw_input: str, source: str = "human") -> Dict[str, Any]:
    """
    Receives any input and returns a structured, classified package
    ready for the rest of the system to work with.

    Args:
        raw_input: The raw input string exactly as it arrived.
        source: Where the input came from. Defaults to 'human'.

    Returns:
        Dict containing:
            raw         — exactly what came in, unchanged
            clean       — trimmed, normalized
            input_type  — what kind of input this is
            source      — where it came from
            word_count  — how many words it contains
            complexity  — simple / moderate / complex
            safety      — None if clear, or a safety flag dict
            record_id   — permanent audit record ID
    """
    # Clean without altering meaning
    clean: str = raw_input.strip()

    # Classify
    input_type: str = _classify(clean)
    word_count: int = len(clean.split())
    complexity: str = _estimate_complexity(clean, word_count)

    # Safety check — always runs first
    safety_flag: Optional[Dict[str, Any]] = _check_safety(clean)

    # Build the package
    package: Dict[str, Any] = {
        "raw": raw_input,
        "clean": clean,
        "input_type": input_type,
        "source": source,
        "word_count": word_count,
        "complexity": complexity,
        "safety": safety_flag,
        "record_id": None
    }

    # Record to permanent memory
    record_id: int = memory.record(
        event_type="INTAKE",
        input_data=clean,
        context={"type": input_type, "source": source, "complexity": complexity},
        notes=f"Safety flag: {safety_flag['level'] if safety_flag else 'None'}"
    )
    package["record_id"] = record_id

    # If safety flagged — record separately too
    if safety_flag:
        memory.record(
            event_type="SAFETY",
            input_data=clean,
            notes=safety_flag["message"]
        )

    return package


# ─────────────────────────────────────────────────────────────────────────────
# CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def _classify(text: str) -> str:
    """
    Makes a best guess at what kind of input this is.

    Args:
        text: The cleaned input string.

    Returns:
        str: One of the keys from INPUT_TYPES.
    """
    if not text:
        return "unknown"

    text_lower: str = text.lower()

    # Questions
    if text.endswith("?") or text_lower.startswith(
        ("what", "who", "where", "when", "why", "how", "is ", "are ",
         "can ", "could ", "would ", "should ", "do ", "does ", "did ")
    ):
        return "question"

    # Commands
    if text_lower.startswith(
        ("do ", "make ", "create ", "delete ", "remove ", "add ", "run ",
         "start ", "stop ", "show ", "find ", "get ", "set ", "update ",
         "please ", "can you ", "could you ")
    ):
        return "command"

    # Numbers
    if re.match(r"^[\d\s\.,\-\+\%\$]+$", text):
        return "number"

    # Default to text
    return "text"


# ─────────────────────────────────────────────────────────────────────────────
# COMPLEXITY ESTIMATE
# ─────────────────────────────────────────────────────────────────────────────

def _estimate_complexity(text: str, word_count: int) -> str:
    """
    Estimates how complex an input is.
    Affects how much context-building the system will do.
    Distance, complexity, and size — all measured here.

    Args:
        text: The cleaned input string.
        word_count: The number of words in the input.

    Returns:
        str: One of 'simple', 'moderate', or 'complex'.
    """
    # Size factor
    size: str
    if word_count <= 5:
        size = "small"
    elif word_count <= 30:
        size = "medium"
    else:
        size = "large"

    # Sentence count as proxy for complexity
    sentence_count: int = max(1, len(re.split(r'[.!?]+', text)))

    if sentence_count == 1 and size == "small":
        return "simple"
    elif sentence_count <= 3 and size in ("small", "medium"):
        return "moderate"
    else:
        return "complex"


# ─────────────────────────────────────────────────────────────────────────────
# SAFETY CHECK
# ─────────────────────────────────────────────────────────────────────────────

def _check_safety(text: str) -> Optional[Dict[str, Any]]:
    """
    Scans input for signals that require immediate human attention.
    This is not about judgment. It is about care.

    Args:
        text: The cleaned input string.

    Returns:
        None if the input is clear.
        Dict with 'level', 'message', and 'requires_human' if flagged.
    """
    text_lower: str = text.lower()

    for pattern, level, message in SAFETY_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return {
                "level": level,
                "message": message,
                "requires_human": True
            }

    return None
