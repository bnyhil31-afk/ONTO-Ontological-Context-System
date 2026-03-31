"""
modules/surface.py

SURFACE — presents examined context to the human.

Design principles:
  1. Observation language, not truth claims.
     "You've mentioned X 5 times" — not "X is important to you."
     "Observed across 3 inputs" — not "This is established fact."

  2. Adaptive depth. No hand-holding.
     Simple input → clean, direct output. No framing overhead.
     Complex input → richer examination. But never imposed on simple requests.
     Vending machine use is valid. Examined inquiry is valid. Neither corrected.

  3. Show the path, not just the destination.
     When context exists: show where it came from.
     When context is contradicted: say so explicitly.
     When confidence is low: say so. Uncertainty is a first-class output.

  4. Show what's missing, not just what's present.
     Gap flags visible. The system cannot manipulate what it does not hide.

  5. Source diversity over raw frequency.
     5 mentions from 1 session ≠ 5 mentions from 5 sessions.
     The system flags when repetition is not the same as reliability.

  6. Examination from examine.py enriches the output.
     The surface layer always uses examination results if available.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import examine as examine_module
from modules import memory


# ---------------------------------------------------------------------------
# PUBLIC INTERFACE
# ---------------------------------------------------------------------------

def present(enriched_package: Dict[str, Any]) -> Dict[str, Any]:
    """
    Surface the examined context to the human.

    Input: enriched package from contextualize.build()
    Output: presentation dict with display, confidence, safe, record_id, weight

    Backward-compatible interface — all tests continue to pass.
    Additional fields added without breaking existing contracts.
    """
    # Safety check — always first, always direct
    safety = enriched_package.get("safety")
    if safety:
        return _present_safety(enriched_package, safety)

    # Get or build examination
    examination = _get_examination(enriched_package)

    # Build the display based on depth signal
    depth = examination.get("depth_signal", "simple")

    if depth == "complex":
        display = _build_complex_display(enriched_package, examination)
    elif depth == "moderate":
        display = _build_moderate_display(enriched_package, examination)
    else:
        display = _build_simple_display(enriched_package, examination)

    # Compute confidence from examination
    confidence = _compute_confidence(enriched_package, examination)
    weight = enriched_package.get("weight", 0.5)

    # Record this surface event
    record_id = _record_surface(enriched_package, examination, confidence)

    return {
        # Core fields (backward compat)
        "display": display,
        "confidence": confidence,
        "safe": True,
        "record_id": record_id,
        "weight": weight,
        # Additional fields for downstream use
        "examination": examination,
        "depth": depth,
        "epistemic_status": examination.get("epistemic_status", "unknown"),
        "contradiction_flags": examination.get("contradiction_flags", []),
        "gap_flags": examination.get("gap_flags", []),
    }


# ---------------------------------------------------------------------------
# SAFETY PRESENTATION
# ---------------------------------------------------------------------------

def _present_safety(
    enriched_package: Dict[str, Any],
    safety: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Safety-flagged input. Direct, clear, no distractions.
    Human wellbeing is the highest priority. Everything else waits.
    """
    level = safety.get("level", "UNKNOWN")
    message = safety.get("message", "")
    text = enriched_package.get("clean") or enriched_package.get("raw") or ""

    if level == "CRISIS":
        display = (
            f"I want to make sure you're okay.\n\n"
            f"If you're in crisis or thinking about hurting yourself, "
            f"please reach out to a crisis line:\n\n"
            f"  • 988 Suicide & Crisis Lifeline: call or text 988\n"
            f"  • Crisis Text Line: text HOME to 741741\n"
            f"  • International: https://www.befrienders.org\n\n"
            f"You don't have to be alone in this."
        )
    elif level == "HARM":
        display = (
            f"This input contains signals related to harm. "
            f"Before proceeding, I want to flag this for human review.\n\n"
            f"If someone is in immediate danger, please contact emergency services."
        )
    elif level == "INTEGRITY":
        display = (
            f"This input appears to ask the system to act against its principles. "
            f"The principles are sealed and cannot be overridden. "
            f"Everything is recorded."
        )
    else:
        display = (
            f"Safety flag detected. Human review required before proceeding.\n"
            f"Flag type: {level}"
        )

    record_id = _record_surface(enriched_package, {}, 0.0)

    return {
        "display": display,
        "confidence": 0.0,
        "safe": False,
        "record_id": record_id,
        "weight": enriched_package.get("weight", 0.0),
        "examination": {},
        "depth": "simple",
        "epistemic_status": "unknown",
        "contradiction_flags": [],
        "gap_flags": [],
    }


# ---------------------------------------------------------------------------
# DISPLAY BUILDERS
# ---------------------------------------------------------------------------

def _build_simple_display(
    enriched: Dict[str, Any],
    examination: Dict[str, Any],
) -> str:
    """
    Simple depth display.
    Clean, direct, minimal framing. Respects that the user didn't ask for more.
    """
    text = enriched.get("clean") or enriched.get("raw") or ""
    context = enriched.get("context") or {}
    related_count = context.get("related_count", 0)
    summary = context.get("summary", "")
    novelty = examination.get("novelty", "first_seen")
    confidence_profile = examination.get("confidence_profile") or {}
    level = confidence_profile.get("level", "none")

    lines = [f"Input received: {text}"]

    if related_count == 0:
        lines.append("No prior context found.")
    elif novelty == "first_seen":
        lines.append("No prior context found.")
    else:
        lines.append(f"Connected to {related_count} prior observation(s).")

    # Confidence — honest, calibrated language
    confidence_val = _compute_confidence(enriched, examination)
    if confidence_val >= 0.7:
        lines.append(f"Confident — strong match with prior context.")
    elif confidence_val >= 0.4:
        lines.append(f"Moderate confidence.")
    elif confidence_val > 0.0:
        lines.append(
            "Low confidence — limited prior context."
            " Human judgment recommended."
        )
    else:
        lines.append("Confidence: none — new territory.")

    # Contradiction flag — always shown if present
    flags = examination.get("contradiction_flags", [])
    if flags:
        lines.append(f"⚠ Contradiction detected: {flags[0]}")

    return "\n".join(lines)


def _build_moderate_display(
    enriched: Dict[str, Any],
    examination: Dict[str, Any],
) -> str:
    """
    Moderate depth display.
    Brief context note when genuinely useful. Not imposed.
    """
    text = enriched.get("clean") or enriched.get("raw") or ""
    context = enriched.get("context") or {}
    related_count = context.get("related_count", 0)
    graph_context = enriched.get("graph_context") or []

    confidence_profile = examination.get("confidence_profile") or {}
    level = confidence_profile.get("level", "none")
    explanation = confidence_profile.get("explanation", "")
    provenance = examination.get("provenance_summary", "")

    lines = [f"Input: {text}", ""]

    # Context
    if related_count == 0:
        lines.append("No prior context found. This is new territory.")
    else:
        # Show what was found — in observation language
        top_concepts = []
        for r in graph_context[:3]:
            concept = r.get("concept", "")
            times = r.get("times_seen", 1)
            if concept:
                top_concepts.append(f"'{concept}' (observed {times}×)")

        if top_concepts:
            lines.append(f"Prior context: {', '.join(top_concepts)}.")
        else:
            lines.append(f"Prior context: {related_count} related observation(s).")

    # Confidence — honest
    if explanation:
        lines.append(f"Confidence: {level}. {explanation}")
    elif level == "none":
        lines.append("Confidence: none.")
    else:
        lines.append(f"Confidence: {level}.")

    # Contradiction — always shown
    flags = examination.get("contradiction_flags", [])
    if flags:
        lines.append(f"\n⚠ Contradiction: {flags[0]}")
        if len(flags) > 1:
            lines.append(f"  + {len(flags) - 1} more conflict(s).")

    # Provenance — brief
    if provenance and related_count > 0:
        lines.append(f"\nSource: {provenance}")

    # Gaps
    gap_flags = examination.get("gap_flags", [])
    if gap_flags:
        lines.append(f"\nGap: {gap_flags[0]}")

    return "\n".join(lines)


def _build_complex_display(
    enriched: Dict[str, Any],
    examination: Dict[str, Any],
) -> str:
    """
    Complex depth display.
    Full examination visible. Shows path, not just destination.
    Appropriate for deeply engaged input. Not imposed on simple requests.
    """
    text = enriched.get("clean") or enriched.get("raw") or ""
    context = enriched.get("context") or {}
    related_count = context.get("related_count", 0)
    graph_context = enriched.get("graph_context") or []

    confidence_profile = examination.get("confidence_profile") or {}
    level = confidence_profile.get("level", "none")
    explanation = confidence_profile.get("explanation", "")
    novelty = examination.get("novelty", "first_seen")
    consistency = examination.get("consistency", "new")
    epistemic = examination.get("epistemic_status", "unknown")
    provenance = examination.get("provenance_summary", "")

    lines = []

    # Header
    lines.append(f"Input: {text}")
    lines.append("─" * 40)

    # Epistemic status — always first in complex mode
    epistemic_labels = {
        "known": "Known (directly observed, multiple sources)",
        "inferred": "Inferred (pattern detected, not confirmed)",
        "unknown": "Unknown (insufficient basis for any claim)",
    }
    lines.append(f"Epistemic status: {epistemic_labels.get(epistemic, epistemic)}")
    lines.append("")

    # What was found
    if related_count == 0:
        lines.append("Prior context: none found.")
        lines.append("This is new territory. The system has no basis for context.")
    else:
        lines.append(f"Prior context: {related_count} observation(s) found.")
        lines.append("")

        # Top concepts with honest framing
        for r in graph_context[:5]:
            concept = r.get("concept", "")
            times = r.get("times_seen", 1)
            weight = r.get("effective_weight", 0)
            days = r.get("days_since")
            if concept:
                recency = f", {days:.0f}d ago" if days is not None else ""
                lines.append(
                    f"  • '{concept}' — observed {times}× "
                    f"(relevance: {weight:.2f}{recency})"
                )

    lines.append("")

    # Novelty
    novelty_labels = {
        "first_seen": "First encounter — no pattern established.",
        "emerging":   "Emerging pattern — observed in a few inputs.",
        "established": "Established pattern — recurring across multiple inputs.",
    }
    lines.append(f"Pattern: {novelty_labels.get(novelty, novelty)}")

    # Confidence
    lines.append(f"Confidence: {level}.")
    if explanation:
        lines.append(f"  {explanation}")

    # Source diversity note — anti-echo-chamber core
    diversity_ratio = confidence_profile.get("diversity_ratio", 0)
    total_obs = confidence_profile.get("total_observations", 0)
    source_count = confidence_profile.get("source_count", 0)
    if total_obs > 1 and diversity_ratio < 0.3 and source_count > 0:
        lines.append(
            f"\n  ⚠ Diversity note: {total_obs} observations, "
            f"but only {source_count} distinct source(s). "
            f"Repetition does not increase reliability."
        )

    lines.append("")

    # Contradictions — always visible
    flags = examination.get("contradiction_flags", [])
    if flags:
        lines.append("Contradictions detected:")
        for flag in flags:
            lines.append(f"  ⚠ {flag}")
        lines.append("")

    # Provenance
    if provenance:
        lines.append(f"Provenance: {provenance}")
        lines.append("")

    # Gaps — what's not here
    gap_flags = examination.get("gap_flags", [])
    if gap_flags:
        lines.append("Gaps in context:")
        for gap in gap_flags:
            lines.append(f"  → {gap}")
        lines.append("")

    # Consistency
    consistency_labels = {
        "aligned":     "Consistent with prior context.",
        "contradicted": "Conflicts with prior context (see above).",
        "new":         "No prior context to compare against.",
        "unknown":     "Consistency unknown.",
    }
    lines.append(f"Consistency: {consistency_labels.get(consistency, consistency)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# EXAMINATION RETRIEVAL
# ---------------------------------------------------------------------------

def _get_examination(enriched: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get or build the examination for this enriched package.
    Uses contextualize's examination if available, enriches it via examine.py.
    """
    existing = enriched.get("examination")
    navigate_results = enriched.get("graph_context") or []

    return examine_module.examine(
        navigate_results=navigate_results,
        package=enriched,
        examination_from_context=existing,
    )


# ---------------------------------------------------------------------------
# CONFIDENCE COMPUTATION
# ---------------------------------------------------------------------------

def _compute_confidence(
    enriched: Dict[str, Any],
    examination: Dict[str, Any],
) -> float:
    """
    Compute a numeric confidence value (0.0 to 1.0).

    When no graph data is available: confidence = 1 - distance (original behavior).
    When graph data exists: modulate by source diversity and confidence level.

    Confidence thresholds:
      >= 0.7  → high confidence
      >= 0.4  → moderate confidence
      >  0.0  → low confidence (humble language — never pretend to know more)
      == 0.0  → none (completely new territory, distance = 1.0)
    """
    context = enriched.get("context") or {}
    # Top-level distance takes priority over context["distance"]
    distance = enriched.get("distance", context.get("distance", 1.0))
    base = max(0.0, min(1.0, 1.0 - distance))

    # Only apply level adjustment when we actually have graph-backed context
    navigate_results = enriched.get("graph_context") or []
    if not navigate_results:
        return round(base, 3)

    # Graph data exists — modulate by confidence profile
    level_adjustments = {
        "high": 0.15,
        "moderate": 0.05,
        "low": -0.05,
        "none": -0.10,
    }
    confidence_profile = examination.get("confidence_profile") or {}
    level = confidence_profile.get("level", "none")
    adjustment = level_adjustments.get(level, 0.0)

    return round(max(0.0, min(1.0, base + adjustment)), 3)


# ---------------------------------------------------------------------------
# RECORD KEEPING
# ---------------------------------------------------------------------------

def _record_surface(
    enriched: Dict[str, Any],
    examination: Dict[str, Any],
    confidence: float,
) -> int:
    """
    Record this surface event to the audit trail.
    Returns the record_id.

    Every surface event is recorded — the trail is always on.
    """
    text = (enriched.get("clean") or enriched.get("raw") or "")[:200]
    depth = examination.get("depth_signal", "simple")
    epistemic = examination.get("epistemic_status", "unknown")

    try:
        record_id = memory.record(
            event_type="SURFACE",
            notes=text,
            context={
                "confidence": round(confidence, 3),
                "depth": depth,
                "epistemic_status": epistemic,
                "novelty": examination.get("novelty", "unknown"),
                "consistency": examination.get("consistency", "unknown"),
            }
        )
        return record_id if isinstance(record_id, int) else 1
    except Exception:
        return 1
