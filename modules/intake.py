"""
modules/intake.py

The system's front door.
Every input comes through here first.
Nothing reaches the rest of the system without being received,
classified, and checked for safety.

Changes from v1 (REVIEW_001 findings C3, U7):

  C3 — Data classification: every intake package now includes a
       classification level (0-5 per crossover contract §28).
       Classification is applied at intake and propagates forward.
       This enables the privacy architecture to function as designed.

  U7 — Expanded crisis detection: keyword detection expanded to include
       indirect crisis expressions, future temporal markers, goodbye
       patterns, and hopelessness language. Per REVIEW_001 Finding 10.2,
       keyword-only detection has high false-negative rates for indirect
       expressions. System is documented as indicative, not comprehensive.

Classification levels (crossover contract §28):
  0 — public:     No sensitivity
  1 — internal:   Organizational sensitivity
  2 — personal:   Individual identifying information
  3 — sensitive:  Health, financial, legal, biometric
  4 — privileged: Attorney-client, clinical, clergy
  5 — critical:   Existential risk if exposed

Plain English: This is the ear of the system.
It listens to everything. It classifies what it hears.
It checks for danger before anything else happens.
"""

import os
import re
import unicodedata
from typing import Any, Dict, Optional

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Input limits
MAX_INPUT_LENGTH: int = 10_000  # characters — override via config

# ─────────────────────────────────────────────────────────────────────────────
# SAFETY PATTERNS — CRISIS, HARM, INTEGRITY
# ─────────────────────────────────────────────────────────────────────────────

# CRISIS patterns — U7 expansion
# Direct patterns (original)
_CRISIS_DIRECT = [
    r"\bkill\s+myself\b",
    r"\bend\s+my\s+life\b",
    r"\bsuicid\w*\b",
    r"\bwant\s+to\s+die\b",
    r"\bbetter\s+off\s+dead\b",
    r"\bno\s+reason\s+to\s+live\b",
    r"\bself.harm\b",
    r"\bcut\s+myself\b",
    r"\boverdose\b",
    r"\bjump\s+off\b",
    r"\bhang\s+myself\b",
]

# Indirect patterns — U7 addition
# High false-negative territory — included with appropriate humility
_CRISIS_INDIRECT = [
    r"\btired\s+of\s+(everything|it\s+all|living|life)\b",
    r"\bno\s+point\s+(anymore|to\s+anything|in\s+going\s+on)\b",
    r"\bcan'?t\s+(do\s+this|go\s+on|take\s+it)\s+(anymore|any\s+longer)\b",
    r"\bwhen\s+i'?m\s+gone\b",
    r"\bafter\s+i'?m\s+dead\b",
    r"\bwanted\s+to\s+say\s+(goodbye|thank\s+you|thanks)\s+for\s+(everything|being)\b",
    r"\bnobody\s+(would\s+miss|cares\s+about|notices)\s+me\b",
    r"\bwhat'?s\s+the\s+point\b",
    r"\bcan'?t\s+see\s+a\s+way\s+(forward|out|through)\b",
    r"\bgive\s+up\s+on\s+(everything|life|myself)\b",
    r"\bfeeling\s+(hopeless|worthless|like\s+a\s+burden)\b",
    r"\bmiss\s+me\s+when\s+i'?m\s+gone\b",
]

_CRISIS_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in _CRISIS_DIRECT + _CRISIS_INDIRECT
]

# HARM patterns — threats of harm to others
_HARM_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bhurt\s+someone\b",
        r"\bkill\s+(someone|him|her|them|you)\b",
        r"\battack\b",
        r"\bstab\b",
        r"\bshoot\s+(someone|him|her|them)\b",
        r"\bharm\s+(someone|others|them)\b",
        r"\bget\s+revenge\b",
        r"\bmake\s+(him|her|them)\s+pay\b",
    ]
]

# INTEGRITY patterns — attempts to override principles
_INTEGRITY_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bignore\s+your\s+principles\b",
        r"\bforget\s+your\s+(rules|instructions|principles)\b",
        r"\boverride\s+your\b",
        r"\bdisable\s+(the\s+|your\s+)?principles\b",
        r"\bremove\s+(the\s+|your\s+)?principles\b",
        r"\bbypass\s+(the\s+|your\s+)?principles\b",
        r"\bpretend\s+you\s+(have\s+no|don'?t\s+have)\b",
        r"\byou\s+(are\s+now|must\s+act\s+as|should\s+be)\s+a\b",
        r"\bjailbreak\b",
        r"\bdan\s+mode\b",
        r"\bdeveloper\s+mode\b",
        r"\bdisable\s+(safety|filter|constraint)\b",
        r"\bbypass\s+(your|the)\b",
        r"\bact\s+as\s+if\s+you\s+have\s+no\b",
        r"\bignore\s+(all\s+)?(previous\s+)?instructions\b",
    ]
]

# ─────────────────────────────────────────────────────────────────────────────
# CLASSIFICATION HEURISTICS (C3)
# ─────────────────────────────────────────────────────────────────────────────

# Keywords that suggest higher classification levels
_CLASSIFICATION_PATTERNS = {
    3: [  # sensitive
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(health|medical|diagnosis|symptom|prescription|medication)\b",
            r"\b(bank|account|credit\s+card|social\s+security|ssn|tax)\b",
            r"\b(password|passphrase|secret\s+key|api\s+key)\b",
            r"\b(legal|lawyer|attorney|lawsuit|court|case\s+number)\b",
            r"\b(biometric|fingerprint|facial\s+recognition|dna)\b",
            r"\b(salary|income|debt|bankruptcy|mortgage)\b",
        ]
    ],
    2: [  # personal
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(name\s+is|my\s+name|i'?m\s+called|call\s+me)\b",
            r"\b(address|location|phone\s+number|email)\b",
            r"\b(date\s+of\s+birth|born\s+on|my\s+age|years\s+old)\b",
            r"\b(relationship|partner|spouse|husband|wife|girlfriend|boyfriend)\b",
        ]
    ]
}


# ─────────────────────────────────────────────────────────────────────────────
# RECEIVE — THE MAIN FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def receive(raw_input: str) -> Dict[str, Any]:
    """
    Receives any input and produces a classified, safety-checked package.

    Steps:
      1. Sanitize (strip dangerous characters)
      2. Classify (determine sensitivity level — C3)
      3. Safety check (CRISIS, HARM, INTEGRITY — U7 expansion)
      4. Characterize (complexity, input type, word count)
      5. Return package

    The classification from this function propagates through every
    downstream module. It cannot be reduced — only maintained or elevated.

    Args:
        raw_input: Any string input from any source

    Returns:
        Dict containing the processed package with classification field
    """
    from modules import memory

    # Step 1 — Sanitize
    clean, was_sanitized, was_truncated = _sanitize(raw_input)

    # Step 2 — Classify (C3)
    classification = _classify(clean)

    # Step 3 — Safety check
    safety = _check_safety(clean)

    # Step 4 — Characterize
    word_count = len(clean.split()) if clean else 0
    complexity = _assess_complexity(clean, word_count)
    input_type = _classify_input_type(clean)

    # Step 5 — Record and return
    record_id = memory.record(
        event_type="INTAKE",
        input_data=clean[:500] if clean else None,
        notes=f"source:human | complexity:{complexity} | type:{input_type}",
        classification=classification
    )

    return {
        "raw": raw_input,
        "clean": clean,
        "input_type": input_type,
        "source": "human",
        "word_count": word_count,
        "complexity": complexity,
        "safety": safety,
        "sanitized": was_sanitized,
        "truncated": was_truncated,
        "record_id": record_id,
        "classification": classification,  # C3 — propagates forward
        "classification_basis": "auto-detected",
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLASSIFICATION (C3)
# ─────────────────────────────────────────────────────────────────────────────

def _classify(text: str) -> int:
    """
    Applies sensitivity classification heuristics to the input text.

    Returns the highest classification level detected (0-5).
    Classification can only increase downstream — never decrease.

    This is heuristic auto-detection. Deployers may override with
    user-declared classification in specialized deployments.

    Classification levels per crossover contract §28:
      0 — public:     No sensitivity
      1 — internal:   Organizational sensitivity
      2 — personal:   Individual identifying information
      3 — sensitive:  Health, financial, legal, biometric
      4 — privileged: Attorney-client, clinical, clergy
      5 — critical:   Set explicitly — not auto-detected

    Plain English: The system tries to recognize when something
    sensitive is being shared and marks it accordingly.
    """
    if not text:
        return 0

    # Check from highest auto-detectable level downward
    for level in [3, 2]:
        patterns = _CLASSIFICATION_PATTERNS.get(level, [])
        for pattern in patterns:
            if pattern.search(text):
                return level

    return 0  # Default: public


# ─────────────────────────────────────────────────────────────────────────────
# SAFETY CHECK (U7 — expanded patterns)
# ─────────────────────────────────────────────────────────────────────────────

def _check_safety(text: str) -> Optional[Dict[str, Any]]:
    """
    Checks for safety signals: CRISIS, HARM, INTEGRITY.

    U7 — Expanded to include indirect crisis expressions per
    REVIEW_001 Finding 10.2. The system cannot guarantee detection
    of all crisis signals — it is indicative, not comprehensive.
    Human judgment at the GOVERN checkpoint remains essential.

    Returns:
        None if no safety concern detected.
        Dict with level, message, and requires_human if concern detected.

    Detection note: Indirect crisis patterns (hopelessness, goodbye
    language, temporal markers) are included to reduce false negatives.
    False positives are preferable to false negatives for crisis signals.
    The checkpoint human reviews all flagged inputs.
    """
    if not text:
        return None

    # CRISIS — highest priority, checked first
    for pattern in _CRISIS_PATTERNS:
        if pattern.search(text):
            return {
                "level": "CRISIS",
                "message": (
                    "This input contains signals that may indicate "
                    "a person in distress. Human review is required "
                    "before any other action."
                ),
                "requires_human": True,
                "detection": "pattern-match",
                "note": (
                    "Detection is indicative, not comprehensive. "
                    "False negatives are possible. Human judgment "
                    "at the checkpoint is essential."
                )
            }

    # HARM — threat of harm to others
    for pattern in _HARM_PATTERNS:
        if pattern.search(text):
            return {
                "level": "HARM",
                "message": (
                    "This input contains language that may indicate "
                    "intent to harm others. Human review is required."
                ),
                "requires_human": True,
                "detection": "pattern-match"
            }

    # INTEGRITY — attempt to override system principles
    for pattern in _INTEGRITY_PATTERNS:
        if pattern.search(text):
            return {
                "level": "INTEGRITY",
                "message": (
                    "This input appears to attempt overriding the "
                    "system's principles. The system will not comply. "
                    "This event has been recorded."
                ),
                "requires_human": False,
                "detection": "pattern-match"
            }

    return None


# ─────────────────────────────────────────────────────────────────────────────
# SANITIZATION
# ─────────────────────────────────────────────────────────────────────────────

def _sanitize(text: str) -> tuple:
    """
    Sanitizes input to prevent injection attacks.
    Returns (clean_text, was_sanitized, was_truncated).
    """
    if not text:
        return ("", False, False)

    original = text
    clean = text

    # Remove null bytes
    clean = clean.replace("\x00", "")

    # Remove control characters (except newline, tab, carriage return)
    clean = "".join(
        c for c in clean
        if unicodedata.category(c) not in ("Cc",)
        or c in ("\n", "\t", "\r")
    )

    # Remove Unicode bidirectional override characters (text direction attacks)
    bidi_chars = [
        "\u202A", "\u202B", "\u202C", "\u202D", "\u202E",
        "\u2066", "\u2067", "\u2068", "\u2069",
        "\u200F", "\u200E",
    ]
    for char in bidi_chars:
        clean = clean.replace(char, "")

    # Normalize Unicode (NFC form)
    clean = unicodedata.normalize("NFC", clean)

    # Normalize whitespace — collapse multiple spaces/tabs
    clean = re.sub(r"[ \t]+", " ", clean).strip()
    # Collapse multiple consecutive newlines to maximum two
    clean = re.sub(r"\n{3,}", "\n\n", clean)

    # Enforce length limit
    max_length = MAX_INPUT_LENGTH
    try:
        from core.config import config
        max_length = config.MAX_INPUT_LENGTH
    except (ImportError, AttributeError):
        pass

    was_truncated = len(clean) > max_length
    if was_truncated:
        clean = clean[:max_length]

    was_sanitized = clean != original
    return (clean, was_sanitized, was_truncated)


# ─────────────────────────────────────────────────────────────────────────────
# CHARACTERIZATION
# ─────────────────────────────────────────────────────────────────────────────

def _assess_complexity(text: str, word_count: int) -> str:
    """
    Assesses input complexity based on sentence count.
    Returns: empty | simple | moderate | complex
    """
    if not text or word_count == 0:
        return "empty"

    # Count sentence-ending punctuation
    sentence_count = len(re.findall(r'[.!?]+', text))
    # If no punctuation, treat whole text as one sentence
    if sentence_count == 0:
        sentence_count = 1

    if sentence_count <= 1:
        return "simple"
    elif sentence_count <= 3:
        return "moderate"
    else:
        return "complex"


def _classify_input_type(text: str) -> str:
    """
    Classifies the type of input.
    Returns: question | statement | request | number | text | unknown
    """
    if not text or not text.strip():
        return "unknown"

    stripped = text.strip()

    # Pure numeric input (including formatted numbers/phone/currency)
    if re.match(r"^[\d\s\.,\-\+\(\)\/\%\$\£\€\#\@]+$", stripped):
        return "number"

    lower = stripped.lower()

    # Question words at start — detect questions even without '?'
    question_starters = (
        "what", "who", "where", "when", "why", "how",
        "which", "whose", "whom", "is ", "are ", "was ",
        "were ", "do ", "does ", "did ", "can ", "could ",
        "will ", "would ", "should ", "have ", "has ", "had "
    )
    if stripped.endswith("?") or any(
        lower.startswith(w) for w in question_starters
    ):
        return "question"

    # Request phrases
    request_starters = (
        "please", "can you", "could you", "would you",
        "help me", "tell me", "show me", "explain"
    )
    if any(lower.startswith(w) for w in request_starters):
        return "request"

    # Default
    return "statement"
