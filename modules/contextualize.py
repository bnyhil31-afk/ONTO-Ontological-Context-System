"""
modules/contextualize.py

The system's understanding layer.
This is where raw input becomes meaning.
It places each new input into the field of everything already known —
weighted by distance, complexity, and size.

Plain English: This is where the system thinks.
Not just about what you said —
but about what it means given everything else.

This is the Living Field — in code.
"""

import math
from typing import Any, Dict, List, Set
from modules import memory

# ─────────────────────────────────────────────────────────────────────────────
# THE FIELD
# In a full system, this would be a vector database or knowledge graph.
# In this MVP, it is a lightweight in-memory + SQLite field.
# It grows with every interaction.
# ─────────────────────────────────────────────────────────────────────────────

_field: List[Dict[str, str]] = []  # In-memory for this session


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CONTEXTUALIZE FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def build(package: Dict[str, Any]) -> Dict[str, Any]:
    """
    Takes an intake package and builds context around it.

    Args:
        package: An intake package from modules/intake.py.

    Returns:
        Dict: The original package enriched with a 'context' key containing:
            related_count   — number of similar inputs seen before
            related_samples — up to 3 examples of related past inputs
            distance        — how new this input is (0.0=familiar, 1.0=new)
            weight          — how much attention this input deserves (0.0-1.0)
            field_size      — total number of inputs the system has seen
            summary         — plain English description of the context
    """
    input_text: str = package.get("clean", "")
    input_type: str = package.get("input_type", "unknown")
    complexity: str = package.get("complexity", "simple")

    # Find related entries from memory
    related: List[Dict[str, Any]] = _find_related(input_text)

    # Calculate distance — how familiar is this?
    distance: float = _calculate_distance(input_text, related)

    # Calculate weight — how much attention does this deserve?
    weight: float = _calculate_weight(
        distance=distance,
        complexity=complexity,
        word_count=package.get("word_count", 1)
    )

    # Grow the field with this new input
    _add_to_field(input_text, input_type)

    # Build plain summary
    summary: str = _summarize(distance, related, package)

    context: Dict[str, Any] = {
        "related_count": len(related),
        "related_samples": [r["input"][:60] for r in related[:3]],
        "distance": round(distance, 3),
        "weight": round(weight, 3),
        "field_size": len(_field),
        "summary": summary
    }

    # Record to memory
    memory.record(
        event_type="CONTEXT",
        input_data=input_text,
        context=context,
        confidence=1.0 - distance,
        notes=f"Field size: {len(_field)} | Weight: {weight:.2f}"
    )

    # Enrich and return the package
    enriched: Dict[str, Any] = {**package, "context": context}
    return enriched


# ─────────────────────────────────────────────────────────────────────────────
# FIND RELATED — SIMPLE KEYWORD OVERLAP FOR MVP
# ─────────────────────────────────────────────────────────────────────────────

def _find_related(text: str) -> List[Dict[str, Any]]:
    """
    Finds entries in the field that share meaningful words with the input.
    MVP version uses keyword overlap.
    Future version: vector embeddings.

    Args:
        text: The cleaned input string to find relatives for.

    Returns:
        List[Dict]: Up to 10 related field entries, sorted by relevance.
    """
    words: Set[str] = set(_normalize(text).split())
    stopwords: Set[str] = {
        "the", "a", "an", "is", "it", "in", "on", "at", "to", "for",
        "of", "and", "or", "but", "i", "you", "we", "they", "my", "your"
    }
    keywords: Set[str] = words - stopwords

    if not keywords:
        return []

    related: List[Dict[str, Any]] = []
    for entry in _field:
        entry_words: Set[str] = set(_normalize(entry["input"]).split()) - stopwords
        overlap: Set[str] = keywords & entry_words
        if overlap:
            score: float = len(overlap) / max(len(keywords), 1)
            related.append({**entry, "overlap_score": score})

    related.sort(key=lambda x: x["overlap_score"], reverse=True)
    return related[:10]


# ─────────────────────────────────────────────────────────────────────────────
# DISTANCE — HOW NEW IS THIS?
# ─────────────────────────────────────────────────────────────────────────────

def _calculate_distance(text: str, related: List[Dict[str, Any]]) -> float:
    """
    Calculates how new or familiar this input is.

    Args:
        text: The cleaned input string.
        related: Related entries found in the field.

    Returns:
        float: A value between 0.0 and 1.0.
            0.0 = very familiar, seen many times before
            1.0 = completely new, nothing like it in the field
    """
    if not _field:
        return 1.0  # First ever input — maximally new

    if not related:
        return 0.95  # Nothing related found

    best_score: float = related[0].get("overlap_score", 0)
    distance: float = 1.0 - best_score
    return max(0.0, min(1.0, distance))


# ─────────────────────────────────────────────────────────────────────────────
# WEIGHT — HOW MUCH ATTENTION DOES THIS DESERVE?
# ─────────────────────────────────────────────────────────────────────────────

def _calculate_weight(
    distance: float,
    complexity: str,
    word_count: int
) -> float:
    """
    Combines distance, complexity, and size into a single weight.
    Higher weight = deserves more careful consideration.
    The three governing forces — distance, complexity, size — all here.

    Args:
        distance: How new this input is (0.0 to 1.0).
        complexity: 'simple', 'moderate', or 'complex'.
        word_count: Number of words in the input.

    Returns:
        float: A weight value between 0.0 and 1.0.
    """
    complexity_scores: Dict[str, float] = {
        "simple":   0.2,
        "moderate": 0.5,
        "complex":  0.9
    }
    complexity_score: float = complexity_scores.get(complexity, 0.5)

    # Size factor — logarithmic so large inputs don't dominate completely
    size_score: float = min(1.0, math.log1p(word_count) / math.log1p(200))

    # Weighted combination
    weight: float = (distance * 0.4) + (complexity_score * 0.4) + (size_score * 0.2)
    return round(min(1.0, weight), 3)


# ─────────────────────────────────────────────────────────────────────────────
# GROW THE FIELD
# ─────────────────────────────────────────────────────────────────────────────

def _add_to_field(text: str, input_type: str) -> None:
    """
    Adds this input to the living field.

    Args:
        text: The cleaned input string.
        input_type: The classified type of this input.
    """
    _field.append({
        "input": text,
        "type": input_type
    })


# ─────────────────────────────────────────────────────────────────────────────
# PLAIN LANGUAGE SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

def _summarize(
    distance: float,
    related: List[Dict[str, Any]],
    package: Dict[str, Any]
) -> str:
    """
    Produces a plain English description of what the system sees.

    Args:
        distance: How new this input is (0.0 to 1.0).
        related: Related entries found in the field.
        package: The original intake package.

    Returns:
        str: A plain English summary of the current context.
    """
    familiarity: str = (
        "This is very familiar territory." if distance < 0.2 else
        "This is somewhat familiar." if distance < 0.5 else
        "This is mostly new." if distance < 0.8 else
        "This is completely new territory."
    )

    related_note: str = (
        f"Found {len(related)} related topic(s) from past interactions."
        if related else
        "No related topics found yet."
    )

    complexity_note: str = {
        "simple":   "The input is simple and direct.",
        "moderate": "The input has moderate complexity.",
        "complex":  "The input is complex and deserves careful consideration."
    }.get(package.get("complexity", "simple"), "")

    return f"{familiarity} {related_note} {complexity_note}"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """
    Lowercases and strips punctuation for comparison.

    Args:
        text: Any string.

    Returns:
        str: Lowercase, punctuation-free version for comparison.
    """
    return "".join(c if c.isalnum() or c == " " else " " for c in text.lower())


def load_from_memory() -> int:
    """
    Rebuilds the field from the permanent memory record.
    Call this on boot to restore the field from previous sessions.

    Returns:
        int: The number of entries loaded into the field.
    """
    global _field
    records = memory.read_by_type("INTAKE")
    _field = [
        {"input": r["input"], "type": r.get("context", {}).get("type", "unknown")}
        for r in records if r.get("input")
    ]
    return len(_field)
