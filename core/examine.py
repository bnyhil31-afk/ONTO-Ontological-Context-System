"""
core/examine.py

EXAMINE — the examination engine that runs between NAVIGATE and GOVERN.

Asks four honest questions before context is surfaced to the human:
  1. Consistency  — does this align with or contradict prior context?
  2. Novelty      — is this the first time, emerging, or established?
  3. Confidence   — how many distinct sources contributed? How recent?
  4. Depth signal — what level does this moment actually call for?

This module does NOT decide what to surface. It examines what was found
and characterizes it honestly so surface.py can present it without bias.

Design principles:
  - Observations, not conclusions. "Seen 5 times" not "important."
  - Source diversity matters: 5 mentions from 1 session ≠ 5 from 5 sessions.
  - Contradictions are surfaced, not silently merged or dismissed.
  - Uncertainty is a first-class output. "Unknown" is a valid answer.
  - The system never amplifies simply because something is repeated.
    Repetition alone does not make something more true.

Reference: CROSSOVER_CONTRACT_v1.0 §3.2 — The Socratic constraint.
"""

import math
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# PUBLIC INTERFACE
# ---------------------------------------------------------------------------

def examine(
    navigate_results: List[Dict[str, Any]],
    package: Dict[str, Any],
    examination_from_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run the full four-question examination.

    If contextualize.py already ran an examination (examination_from_context),
    this function enriches it with additional analysis rather than duplicating.

    Returns an examination dict used by surface.py for honest framing.

    Output fields:
      consistency         — "aligned" | "contradicted" | "new" | "unknown"
      novelty             — "first_seen" | "emerging" | "established"
      confidence_profile  — dict with source_count, diversity, recency
      depth_signal        — "simple" | "moderate" | "complex"
      contradiction_flags — list of specific contradiction descriptions
      epistemic_status    — "known" | "inferred" | "unknown"
      gap_flags           — what is NOT in context but probably should be
      provenance_summary  — plain-language description of sources
    """
    # If contextualize already did examination, enrich it
    if examination_from_context:
        return _enrich_examination(examination_from_context, navigate_results, package)

    # Fresh examination
    return _full_examination(navigate_results, package)


# ---------------------------------------------------------------------------
# INTERNAL: FULL EXAMINATION
# ---------------------------------------------------------------------------

def _full_examination(
    navigate_results: List[Dict[str, Any]],
    package: Dict[str, Any],
) -> Dict[str, Any]:
    """Run all four examination questions from scratch."""

    # Q1: Consistency
    consistency, contradiction_flags = _question_consistency(navigate_results, package)

    # Q2: Novelty
    novelty = _question_novelty(navigate_results)

    # Q3: Confidence calibration
    confidence_profile = _question_confidence(navigate_results)

    # Q4: Depth signal
    depth_signal = _question_depth(package, navigate_results)

    # Epistemic status
    epistemic_status = _assess_epistemic_status(navigate_results, package)

    # Gap flags — what's not here that might be relevant
    gap_flags = _identify_gaps(navigate_results, package)

    # Provenance summary — honest plain-language description
    provenance_summary = _build_provenance_summary(navigate_results, confidence_profile)

    return {
        "consistency": consistency,
        "novelty": novelty,
        "confidence_profile": confidence_profile,
        "depth_signal": depth_signal,
        "contradiction_flags": contradiction_flags,
        "epistemic_status": epistemic_status,
        "gap_flags": gap_flags,
        "provenance_summary": provenance_summary,
    }


def _enrich_examination(
    existing: Dict[str, Any],
    navigate_results: List[Dict[str, Any]],
    package: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Enrich an examination already produced by contextualize.py.
    Adds fields that surface.py needs without duplicating computation.
    """
    enriched = dict(existing)

    # Add fields that contextualize doesn't compute
    if "confidence_profile" not in enriched:
        enriched["confidence_profile"] = _question_confidence(navigate_results)

    if "epistemic_status" not in enriched:
        enriched["epistemic_status"] = _assess_epistemic_status(
            navigate_results, package
        )

    if "gap_flags" not in enriched:
        enriched["gap_flags"] = _identify_gaps(navigate_results, package)

    if "provenance_summary" not in enriched:
        enriched["provenance_summary"] = _build_provenance_summary(
            navigate_results, enriched.get("confidence_profile", {})
        )

    return enriched


# ---------------------------------------------------------------------------
# Q1: CONSISTENCY
# ---------------------------------------------------------------------------

def _question_consistency(
    navigate_results: List[Dict[str, Any]],
    package: Dict[str, Any],
) -> tuple:
    """
    Q1: Does this input align with, contradict, or extend prior context?

    Returns (consistency_label, contradiction_flags).

    Conservative: only flags structural contradictions, not semantic ones.
    The system does not have semantic reasoning capability.
    """
    if not navigate_results:
        return "new", []

    text = (package.get("clean") or "").lower()
    words = list(text.split())
    flags = []

    # Detect negation patterns
    negations = {
        "not", "no", "never", "without", "don't", "doesn't",
        "isn't", "aren't", "wasn't", "weren't", "can't", "cannot",
    }

    negated_targets = set()
    for i, word in enumerate(words):
        if word in negations and i + 1 < len(words):
            negated_targets.add(words[i + 1])

    # Check high-weight established concepts against negated targets
    for result in navigate_results:
        concept = (result.get("concept") or "").lower()
        weight = result.get("effective_weight", 0)
        times_seen = result.get("times_seen", 1)

        # Only flag when established context (high weight, seen multiple times)
        if weight > 0.4 and times_seen >= 2 and concept:
            concept_words = set(concept.split())
            overlap = concept_words & negated_targets
            if overlap:
                flags.append(
                    f"Input may conflict with prior context '{concept}' "
                    f"(observed {times_seen} times, weight {weight:.2f})"
                )

    if flags:
        return "contradicted", flags[:3]

    return "aligned", []


# ---------------------------------------------------------------------------
# Q2: NOVELTY
# ---------------------------------------------------------------------------

def _question_novelty(navigate_results: List[Dict[str, Any]]) -> str:
    """
    Q2: Is this the first time, an emerging pattern, or established?

    first_seen  — no prior context found at all
    emerging    — 1-3 prior observations, pattern forming
    established — 4+ prior observations, this is a recurring theme
    """
    if not navigate_results:
        return "first_seen"

    total_observations = sum(r.get("times_seen", 1) for r in navigate_results)

    if total_observations <= 3:
        return "emerging"
    return "established"


# ---------------------------------------------------------------------------
# Q3: CONFIDENCE CALIBRATION
# ---------------------------------------------------------------------------

def _question_confidence(navigate_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Q3: How confident should we be in this context?

    Key insight: source diversity matters more than raw frequency.
    5 mentions from 1 session is less reliable than 5 mentions from 5 sessions.
    The system does not amplify simply because something is repeated.
    """
    if not navigate_results:
        return {
            "level": "none",
            "source_count": 0,
            "total_observations": 0,
            "diversity_ratio": 0.0,
            "avg_days_since": None,
            "explanation": "No prior context found. This is new territory.",
        }

    # Count distinct sources
    source_ids = set()
    for r in navigate_results:
        src = r.get("source_record_id") or r.get("source")
        if src:
            source_ids.add(str(src))
    source_count = len(source_ids)

    # Total observations
    total_observations = sum(r.get("times_seen", 1) for r in navigate_results)

    # Diversity ratio: how many distinct sources vs total observations
    diversity_ratio = (
        min(source_count / max(total_observations, 1), 1.0)
        if total_observations > 0
        else 0.0
    )

    # Average recency
    days_list = [
        r.get("days_since")
        for r in navigate_results
        if r.get("days_since") is not None
    ]
    avg_days = round(sum(days_list) / len(days_list), 1) if days_list else None

    # Confidence level
    level = _compute_confidence_level(
        source_count, total_observations, diversity_ratio, avg_days
    )

    explanation = _build_confidence_explanation(
        level, source_count, total_observations, diversity_ratio, avg_days
    )

    return {
        "level": level,
        "source_count": source_count,
        "total_observations": total_observations,
        "diversity_ratio": round(diversity_ratio, 3),
        "avg_days_since": avg_days,
        "explanation": explanation,
    }


def _compute_confidence_level(
    source_count: int,
    total_observations: int,
    diversity_ratio: float,
    avg_days: Optional[float],
) -> str:
    """
    Compute confidence level: "high" | "moderate" | "low" | "none"

    Rules:
      - high:     3+ distinct sources, diversity > 0.4, recent
      - moderate: 2+ distinct sources or diversity > 0.2
      - low:      1 source or very low diversity
      - none:     no sources
    """
    if source_count == 0:
        return "none"
    if source_count >= 3 and diversity_ratio >= 0.4:
        if avg_days is None or avg_days <= 30:
            return "high"
        return "moderate"
    if source_count >= 2 or diversity_ratio >= 0.2:
        return "moderate"
    return "low"


def _build_confidence_explanation(
    level: str,
    source_count: int,
    total_observations: int,
    diversity_ratio: float,
    avg_days: Optional[float],
) -> str:
    """
    Plain-language explanation of confidence.
    Always speaks in observations, never in truth claims.
    """
    if level == "none":
        return "No prior context. Cannot assess."

    obs_phrase = (
        f"{total_observations} observation{'s' if total_observations != 1 else ''}"
    )
    src_phrase = (
        f"{source_count} distinct input{'s' if source_count != 1 else ''}"
    )

    recency = ""
    if avg_days is not None:
        if avg_days <= 1:
            recency = ", very recent"
        elif avg_days <= 7:
            recency = ", within the past week"
        elif avg_days <= 30:
            recency = ", within the past month"
        else:
            recency = f", avg {avg_days:.0f} days ago"

    if level == "high":
        return (
            f"{obs_phrase} across {src_phrase}{recency}. "
            f"Pattern is consistent and diverse."
        )
    elif level == "moderate":
        return (
            f"{obs_phrase} across {src_phrase}{recency}. "
            f"Pattern is present but limited in diversity."
        )
    else:  # low
        diversity_note = (
            " from a single input" if source_count == 1
            else " with low source diversity"
        )
        return (
            f"{obs_phrase}{diversity_note}{recency}. "
            f"Repetition alone does not increase reliability."
        )


# ---------------------------------------------------------------------------
# Q4: DEPTH SIGNAL
# ---------------------------------------------------------------------------

def _question_depth(
    package: Dict[str, Any],
    navigate_results: List[Dict[str, Any]],
) -> str:
    """
    Q4: What level does this moment call for?

    simple   — clean, minimal, direct. No framing overhead.
    moderate — brief context note when genuinely useful.
    complex  — full examination appropriate; human is engaged deeply.

    The system does not impose depth on simple requests.
    Vending machine use is valid. Examined inquiry is valid.
    Neither is corrected.
    """
    # Safety always simplifies — direct path to resources
    if package.get("safety"):
        return "simple"

    complexity = package.get("complexity", "simple")
    result_count = len(navigate_results)
    word_count = package.get("word_count", 0)

    # Rich input + rich context = complex depth appropriate
    if complexity in ("complex", "detailed") and result_count >= 4:
        return "complex"

    # Moderate input or moderate context
    if complexity in ("moderate", "complex") or result_count >= 2:
        if word_count and word_count >= 10:
            return "moderate"

    return "simple"


# ---------------------------------------------------------------------------
# EPISTEMIC STATUS
# ---------------------------------------------------------------------------

def _assess_epistemic_status(
    navigate_results: List[Dict[str, Any]],
    package: Dict[str, Any],
) -> str:
    """
    What kind of claim can the system honestly make?

    known    — directly observed with high confidence and diversity
    inferred — pattern detected but not directly confirmed
    unknown  — insufficient basis for any claim

    Following Popper: every claim must be falsifiable.
    The system only claims what it has directly observed.
    """
    if not navigate_results:
        return "unknown"

    source_count = len({
        str(r.get("source_record_id") or r.get("source", ""))
        for r in navigate_results
        if r.get("source_record_id") or r.get("source")
    })

    best_weight = max(
        (r.get("effective_weight", 0) for r in navigate_results), default=0
    )
    total_obs = sum(r.get("times_seen", 1) for r in navigate_results)

    if source_count >= 2 and best_weight >= 0.5 and total_obs >= 3:
        return "known"
    if source_count >= 1 and best_weight >= 0.2:
        return "inferred"
    return "unknown"


# ---------------------------------------------------------------------------
# GAP FLAGS
# ---------------------------------------------------------------------------

def _identify_gaps(
    navigate_results: List[Dict[str, Any]],
    package: Dict[str, Any],
) -> List[str]:
    """
    Identify what is NOT in the context but might be relevant.

    The checkpoint manipulation attack is mitigated by making gaps
    as visible as what was found. A human who sees only what the
    system chose to surface cannot evaluate completeness.

    Returns a list of gap descriptions (may be empty).
    """
    gaps = []
    complexity = package.get("complexity", "simple")

    # If nothing was found, that's itself a gap worth naming
    if not navigate_results:
        gaps.append("No prior context found for this input.")
        return gaps

    # If context exists but is very low weight
    best_weight = max(r.get("effective_weight", 0) for r in navigate_results)
    if best_weight < 0.15:
        gaps.append(
            "Prior context was found but relevance is very low. "
            "This may be a new pattern disguised as familiar language."
        )

    # If high complexity but few results — gap between depth and coverage
    if complexity in ("complex", "detailed") and len(navigate_results) <= 1:
        gaps.append(
            "Input is complex but prior context is sparse. "
            "The system's response is limited by what it has observed."
        )

    return gaps[:2]  # cap at 2 gap descriptions


# ---------------------------------------------------------------------------
# PROVENANCE SUMMARY
# ---------------------------------------------------------------------------

def _build_provenance_summary(
    navigate_results: List[Dict[str, Any]],
    confidence_profile: Dict[str, Any],
) -> str:
    """
    Plain-language description of where the context came from.

    This is the "path taken to get here" — always visible, never hidden.
    The human at the checkpoint can see exactly what the system is working from.
    """
    if not navigate_results:
        return "No prior context. First encounter."

    source_count = confidence_profile.get("source_count", 0)
    total_obs = confidence_profile.get("total_observations", 0)
    level = confidence_profile.get("level", "none")
    avg_days = confidence_profile.get("avg_days_since")

    # Build the top concept list
    top_concepts = []
    for r in navigate_results[:3]:
        concept = r.get("concept", "")
        times = r.get("times_seen", 1)
        if concept:
            top_concepts.append(f"'{concept}' ({times}×)")

    concepts_phrase = ", ".join(top_concepts) if top_concepts else "related concepts"

    recency = ""
    if avg_days is not None:
        if avg_days <= 1:
            recency = " (very recent)"
        elif avg_days <= 7:
            recency = " (past week)"
        elif avg_days <= 30:
            recency = " (past month)"
        else:
            recency = f" ({avg_days:.0f} days ago on average)"

    diversity_note = ""
    diversity_ratio = confidence_profile.get("diversity_ratio", 0)
    if total_obs > 1 and diversity_ratio < 0.3:
        diversity_note = (
            f" Note: {total_obs} observations but low source diversity "
            f"({source_count} input{'s' if source_count != 1 else ''}). "
            f"Frequency alone does not increase reliability."
        )

    return (
        f"Context drawn from {source_count} prior input{'s' if source_count != 1 else ''}"
        f"{recency}. "
        f"Related: {concepts_phrase}.{diversity_note}"
    )
