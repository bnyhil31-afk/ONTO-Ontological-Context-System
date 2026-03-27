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

import json
import math
import os
from typing import Optional
from modules import memory

# ─────────────────────────────────────────────────────────────────────────────
# THE FIELD
# In a full system, this would be a vector database or knowledge graph.
# In this MVP, it is a lightweight in-memory + SQLite field.
# It grows with every interaction.
# ─────────────────────────────────────────────────────────────────────────────

_field = []  # In-memory for this session


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CONTEXTUALIZE FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def build(package: dict) -> dict:
    """
    Takes an intake package and builds context around it.
    Returns an enriched package with:
      related     — similar things seen before
      distance    — how new or familiar this input is (0=very familiar, 1=very new)
      weight      — how much attention this input deserves
      field_size  — how much the system knows right now
      summary     — plain English description of the context
    """
    input_text = package.get("clean", "")
    input_type = package.get("input_type", "unknown")
    complexity  = package.get("complexity", "simple")

    # Find related entries from memory
    related = _find_related(input_text)

    # Calculate distance — how familiar is this?
    distance = _calculate_distance(input_text, related)

    # Calculate weight — how much attention does this deserve?
    weight = _calculate_weight(
        distance=distance,
        complexity=complexity,
        word_count=package.get("word_count", 1)
    )

    # Grow the field with this new input
    _add_to_field(input_text, input_type)

    # Build plain summary
    summary = _summarize(distance, related, package)

    context = {
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

    # Enrich the package
    enriched = {**package, "context": context}
    return enriched


# ─────────────────────────────────────────────────────────────────────────────
# FIND RELATED — SIMPLE KEYWORD OVERLAP FOR MVP
# ─────────────────────────────────────────────────────────────────────────────

def _find_related(text: str) -> list:
    """
    Finds entries in the field that share meaningful words with the input.
    MVP version uses keyword overlap.
    Future version: vector embeddings.
    """
    words = set(_normalize(text).split())
    stopwords = {
        "the", "a", "an", "is", "it", "in", "on", "at", "to", "for",
        "of", "and", "or", "but", "i", "you", "we", "they", "my", "your"
    }
    keywords = words - stopwords

    if not keywords:
        return []

    related = []
    for entry in _field:
        entry_words = set(_normalize(entry["input"]).split()) - stopwords
        overlap = keywords & entry_words
        if overlap:
            score = len(overlap) / max(len(keywords), 1)
            related.append({**entry, "overlap_score": score})

    # Sort by relevance
    related.sort(key=lambda x: x["overlap_score"], reverse=True)
    return related[:10]


# ─────────────────────────────────────────────────────────────────────────────
# DISTANCE — HOW NEW IS THIS?
# ─────────────────────────────────────────────────────────────────────────────

def _calculate_distance(text: str, related: list) -> float:
    """
    Returns a value between 0.0 and 1.0.
    0.0 = very familiar, seen many times before
    1.0 = completely new, nothing like it in the field
    """
    if not _field:
        return 1.0  # First ever input — maximally new

    if not related:
        return 0.95  # Nothing related found

    # Best overlap score drives familiarity
    best_score = related[0].get("overlap_score", 0)
    distance = 1.0 - best_score
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
    """
    complexity_scores = {
        "simple":   0.2,
        "moderate": 0.5,
        "complex":  0.9
    }
    complexity_score = complexity_scores.get(complexity, 0.5)

    # Size factor — logarithmic so large inputs don't dominate completely
    size_score = min(1.0, math.log1p(word_count) / math.log1p(200))

    # Weighted combination
    weight = (distance * 0.4) + (complexity_score * 0.4) + (size_score * 0.2)
    return round(min(1.0, weight), 3)


# ─────────────────────────────────────────────────────────────────────────────
# GROW THE FIELD
# ─────────────────────────────────────────────────────────────────────────────

def _add_to_field(text: str, input_type: str):
    """Adds this input to the living field."""
    _field.append({
        "input": text,
        "type": input_type
    })


# ─────────────────────────────────────────────────────────────────────────────
# PLAIN LANGUAGE SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

def _summarize(distance: float, related: list, package: dict) -> str:
    """Produces a plain English description of what the system sees."""

    familiarity = (
        "This is very familiar territory." if distance < 0.2 else
        "This is somewhat familiar." if distance < 0.5 else
        "This is mostly new." if distance < 0.8 else
        "This is completely new territory."
    )

    related_note = (
        f"Found {len(related)} related topic(s) from past interactions."
        if related else
        "No related topics found yet."
    )

    complexity_note = {
        "simple":   "The input is simple and direct.",
        "moderate": "The input has moderate complexity.",
        "complex":  "The input is complex and deserves careful consideration."
    }.get(package.get("complexity", "simple"), "")

    return f"{familiarity} {related_note} {complexity_note}"


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Lowercases and strips punctuation for comparison."""
    return "".join(c if c.isalnum() or c == " " else " " for c in text.lower())


def load_from_memory():
    """
    Rebuilds the field from the permanent memory record.
    Call this on boot to restore the field from previous sessions.
    """
    global _field
    records = memory.read_by_type("INTAKE")
    _field = [
        {"input": r["input"], "type": r.get("context", {}).get("type", "unknown")}
        for r in records if r.get("input")
    ]
    return len(_field)
