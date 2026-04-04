"""
modules/contextualize.py

CONTEXTUALIZE — the RELATE + NAVIGATE layer.

Takes an intake package and:
  1. Calls graph.relate() to build edges from this input
  2. Calls graph.navigate() to find relevant prior context
  3. Returns an enriched package with graph-backed context

The graph records observations, not truth claims.
Everything surfaced here is "observed N times" — never "is true."

Anti-echo-chamber design:
  - Source diversity is tracked: 3 mentions from 1 session ≠ 3 mentions from 3 sessions
  - New context that contradicts established context is flagged, not silently merged
  - The field size (how much we've seen) is always visible
  - The system does not boost things simply because they appear often

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import os
from typing import Any, Dict, List

from modules import memory

try:
    from modules import graph as _graph_module
    _GRAPH_AVAILABLE = True
except ImportError:
    _graph_module = None  # type: ignore
    _GRAPH_AVAILABLE = False

# ---------------------------------------------------------------------------
# MODULE STATE
# ---------------------------------------------------------------------------

# _field is kept for backward compatibility with tests that patch it.
# In the graph-backed implementation, this is populated from navigate results.
_field: List[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# PUBLIC INTERFACE
# ---------------------------------------------------------------------------

def load_from_memory() -> int:
    """
    Rebuild the in-memory field from past sessions.
    Called at system boot.

    Returns the number of past entries loaded.
    """
    global _field
    _field = []

    try:
        records = memory.read_all()
        for record in records:
            text = record.get("notes") or ""
            if text:
                _field.append({
                    "text": text,
                    "event_type": record.get("event_type", "UNKNOWN"),
                    "timestamp": record.get("timestamp", ""),
                })
        return len(_field)
    except Exception:
        return 0


def build(package: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich an intake package with graph-backed context.

    Steps:
      1. Relate — add this input to the graph
      2. Navigate — find relevant prior context
      3. Examine — check consistency, novelty, source diversity
      4. Build enriched package — backward-compatible interface

    The enriched package carries:
      - All original intake fields
      - context dict (backward compat: related_count, distance, weight, field_size)
      - graph_context: the raw navigate results
      - examination: the four-question examination

    No synthetic data is introduced. Every edge traces to this input.
    """
    text = package.get("clean") or package.get("raw") or ""

    # Step 1: RELATE — add this input to the graph
    relate_result = _safe_relate(text, package)

    # Step 2: NAVIGATE — find relevant prior context
    navigate_results = _safe_navigate(text)

    # Step 3: EXAMINE — honest examination before surfacing
    examination = _examine(navigate_results, package, relate_result)

    # Step 4: Build the enriched package
    enriched = dict(package)  # preserve all intake fields

    # Compute distance and weight from navigate results
    distance, weight = _compute_axes(navigate_results, package)

    # Build legacy context dict (backward compat with tests)
    related_count = len(navigate_results)
    related_samples = [
        r.get("concept", "") for r in navigate_results[:3] if r.get("concept")
    ]

    context = {
        "related_count": related_count,
        "related_samples": related_samples,
        "distance": distance,
        "weight": weight,
        "field_size": len(_field),
        "summary": _build_summary(navigate_results, examination),
    }

    # Add graph context to enriched package
    enriched["context"] = context
    enriched["distance"] = distance
    enriched["weight"] = weight
    enriched["graph_context"] = navigate_results
    enriched["examination"] = examination
    enriched["relate_result"] = relate_result

    # Update field (backward compat)
    _field.append({
        "text": text,
        "event_type": "CONTEXTUALIZE",
        "timestamp": "",
    })

    # Record to memory
    try:
        memory.record(
            event_type="CONTEXTUALIZE",
            notes=text[:200] if text else "",
            context={
                "related_count": related_count,
                "distance": round(distance, 3),
                "weight": round(weight, 3),
                "examination_depth": examination.get("depth_signal", "simple"),
            }
        )
    except Exception:
        pass

    return enriched


# ---------------------------------------------------------------------------
# INTERNAL: RELATE
# ---------------------------------------------------------------------------

def _safe_relate(text: str, package: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call graph.relate() safely. Returns empty result on failure.
    Falls back gracefully if graph module is not available.
    """
    if not text or not text.strip() or not _GRAPH_AVAILABLE or _graph_module is None:
        return {"concepts": [], "edges_created": 0, "nodes_created": 0}

    try:
        return _graph_module.relate(package)
    except Exception:
        return {"concepts": [], "edges_created": 0, "nodes_created": 0}


# ---------------------------------------------------------------------------
# INTERNAL: NAVIGATE
# ---------------------------------------------------------------------------

def _safe_navigate(text: str) -> List[Dict[str, Any]]:
    """
    Call graph.navigate() safely. Returns empty list on failure.
    Falls back to _field-based word overlap if graph is unavailable.
    """
    if not text or not text.strip() or not _GRAPH_AVAILABLE or _graph_module is None:
        return _word_overlap_fallback(text)

    try:
        results = _graph_module.navigate(text)
        if results:
            return results
    except Exception:
        pass

    # Fallback: word overlap against _field (original behavior)
    return _word_overlap_fallback(text)


def _word_overlap_fallback(text: str) -> List[Dict[str, Any]]:
    """
    Original word-overlap context search.
    Used as fallback when graph is unavailable.
    """
    words = set(text.lower().split())
    results = []

    for entry in _field[-50:]:  # last 50 entries
        entry_text = entry.get("text", "")
        entry_words = set(entry_text.lower().split())
        overlap = words & entry_words
        if len(overlap) >= 1:
            results.append({
                "concept": entry_text[:60],
                "effective_weight": len(overlap) / max(len(words), 1),
                "times_seen": 1,
                "source": "field_overlap",
                "days_since": 0,
            })

    results.sort(key=lambda r: r.get("effective_weight", 0), reverse=True)
    return results[:10]


# ---------------------------------------------------------------------------
# INTERNAL: EXAMINE
# ---------------------------------------------------------------------------

def _examine(
    navigate_results: List[Dict[str, Any]],
    package: Dict[str, Any],
    relate_result: Dict[str, Any],
) -> Dict[str, Any]:
    """
    The four-question examination engine.

    Asks four honest questions before surfacing:
      1. Consistency — does this align with or contradict prior context?
      2. Novelty — is this the first time we're seeing this?
      3. Source diversity — how many distinct inputs contributed?
      4. Depth signal — what level of engagement does this call for?

    Returns an examination dict that travels with the enriched package.
    """
    complexity = package.get("complexity", "simple")

    # Q1: Consistency
    contradiction_flags = _check_consistency(navigate_results, package)
    if contradiction_flags:
        consistency = "contradicted"
    elif navigate_results:
        consistency = "aligned"
    else:
        consistency = "new"

    # Q2: Novelty
    new_concepts = relate_result.get("concepts", [])
    total_navigate = len(navigate_results)
    if total_navigate == 0:
        novelty = "first_seen"
    elif total_navigate <= 2:
        novelty = "emerging"
    else:
        novelty = "established"

    # Q3: Source diversity
    # Count unique source record IDs — how many distinct inputs contributed
    source_ids = set()
    for r in navigate_results:
        src = r.get("source_record_id") or r.get("source")
        if src:
            source_ids.add(str(src))
    source_diversity = len(source_ids)

    # Total times seen across all results
    total_observations = sum(
        r.get("times_seen", 1) for r in navigate_results
    )

    # Diversity ratio: if all observations from 1 source, diversity is low
    if total_observations > 0 and source_diversity > 0:
        diversity_ratio = min(source_diversity / max(total_observations, 1), 1.0)
    else:
        diversity_ratio = 0.0

    # Q4: Depth signal
    depth_signal = _assess_depth(complexity, navigate_results, package)

    return {
        "consistency": consistency,
        "novelty": novelty,
        "source_diversity": source_diversity,
        "total_observations": total_observations,
        "diversity_ratio": round(diversity_ratio, 3),
        "contradiction_flags": contradiction_flags,
        "new_concepts": new_concepts,
        "depth_signal": depth_signal,
    }


def _check_consistency(
    navigate_results: List[Dict[str, Any]],
    package: Dict[str, Any],
) -> List[str]:
    """
    Check for potential contradictions between new input and prior context.

    A contradiction is flagged when the new input introduces concepts
    that directly conflict with high-weight established context.

    Conservative: only flags obvious structural contradictions.
    Does not attempt semantic reasoning.
    """
    flags = []
    text = (package.get("clean") or "").lower()
    words = set(text.split())

    # Simple negation check: if input contains "not X" or "no X"
    # and prior context has high weight on X, flag it
    negations = {"not", "no", "never", "without", "don't", "doesn't", "isn't", "aren't"}
    negated_words = set()

    words_list = list(words)
    for i, word in enumerate(words_list):
        if word in negations and i + 1 < len(words_list):
            negated_words.add(words_list[i + 1])

    for result in navigate_results:
        concept = (result.get("concept") or "").lower()
        weight = result.get("effective_weight", 0)

        # Only flag high-weight established concepts
        if weight > 0.5 and concept:
            concept_words = set(concept.split())
            if concept_words & negated_words:
                flags.append(
                    f"Input may contradict established context: '{concept}' "
                    f"(observed {result.get('times_seen', 1)} times)"
                )

    return flags[:3]  # cap at 3 flags


def _assess_depth(
    complexity: str,
    navigate_results: List[Dict[str, Any]],
    package: Dict[str, Any],
) -> str:
    """
    Determine the appropriate depth of response.

    simple — clean, minimal output. No hand-holding.
    moderate — brief context if genuinely relevant.
    complex — fuller examination appropriate.
    """
    # Safety always takes priority — simple escalation
    if package.get("safety"):
        return "simple"

    # Complex input + rich context = complex depth
    if complexity in ("complex", "detailed") and len(navigate_results) >= 3:
        return "complex"

    # Complex input + sparse context = moderate
    if complexity in ("complex", "detailed"):
        return "moderate"

    # Simple input — stay simple regardless of context richness
    return "simple"


# ---------------------------------------------------------------------------
# INTERNAL: AXES + SUMMARY
# ---------------------------------------------------------------------------

def _compute_axes(
    navigate_results: List[Dict[str, Any]],
    package: Dict[str, Any],
) -> tuple:
    """
    Compute distance and weight from navigate results.

    Distance: how far the current input is from prior context.
              0.0 = very familiar, 1.0 = completely new.
    Weight: combined relevance score.
    """
    if not navigate_results:
        # Nothing found — completely new territory
        distance = 1.0
        weight = _weight_from_complexity(package.get("complexity", "simple"))
        return distance, weight

    # Average effective weight of top results
    top = navigate_results[:5]
    avg_weight = sum(r.get("effective_weight", 0) for r in top) / len(top)

    # Distance is inverse of familiarity
    distance = max(0.0, min(1.0, 1.0 - avg_weight))

    # Weight from the best result + complexity modifier
    best_weight = max(r.get("effective_weight", 0) for r in top)
    complexity_modifier = {
        "simple": 0.0,
        "moderate": 0.1,
        "complex": 0.2,
        "detailed": 0.2,
    }.get(package.get("complexity", "simple"), 0.0)

    weight = min(1.0, best_weight + complexity_modifier)

    return round(distance, 4), round(weight, 4)


def _weight_from_complexity(complexity: str) -> float:
    """Base weight for new inputs with no prior context."""
    return {
        "simple": 0.3,
        "moderate": 0.4,
        "complex": 0.5,
        "detailed": 0.5,
    }.get(complexity, 0.3)


def _build_summary(
    navigate_results: List[Dict[str, Any]],
    examination: Dict[str, Any],
) -> str:
    """
    Build a brief summary for the legacy context.summary field.
    Used by tests that check context structure.
    """
    novelty = examination.get("novelty", "first_seen")
    related_count = len(navigate_results)
    consistency = examination.get("consistency", "new")

    if novelty == "first_seen":
        return "This is completely new territory — no prior context found."
    elif novelty == "emerging":
        return (
            f"This connects to {related_count} prior observation(s). "
            f"Pattern is emerging."
        )
    elif consistency == "contradicted":
        return (
            f"This connects to {related_count} prior observation(s). "
            f"Potential contradiction with established context detected."
        )
    else:
        return (
            f"This connects to {related_count} prior observation(s). "
            f"Pattern is established."
        )
