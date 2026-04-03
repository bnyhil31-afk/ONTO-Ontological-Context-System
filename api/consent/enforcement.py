"""
api/consent/enforcement.py

ConsentGate — the PDP (Policy Decision Point) for consent enforcement.

The gate is stateless and pure. It reads from the consent ledger and
the regulatory profile — it never writes anything.

graph.navigate() is the PEP (Policy Enforcement Point) — one call,
behind a feature flag, completely backwards compatible.

Absolute barriers (non-configurable, same as federation):
  - classification >= 4 → always blocked (PHI/privileged)
  - is_crisis=True      → always blocked (safety gate)
  - crisis text content → always blocked

These barriers cannot be overridden by any consent record,
configuration, or regulatory profile.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

from typing import Any, Dict, Optional

from api.consent.adapter import ConsentDecision
from api.consent import config as _cfg


# ---------------------------------------------------------------------------
# CRISIS PATTERNS (same set as federation safety module)
# ---------------------------------------------------------------------------

_CRISIS_PHRASES = frozenset({
    "end my life", "kill myself", "take my life",
    "want to die", "better off dead", "can't go on",
    "no reason to live", "hurt myself", "self-harm",
    "suicide", "suicidal",
})


def _contains_crisis(text: str) -> bool:
    """
    Check whether text contains crisis content.
    Same check as federation safety — no data crosses either boundary
    when crisis is detected.
    """
    lower = text.lower()
    return any(phrase in lower for phrase in _CRISIS_PHRASES)


# ---------------------------------------------------------------------------
# CONSENT GATE
# ---------------------------------------------------------------------------

class ConsentGate:
    """
    The PDP (Policy Decision Point) for the consent ledger.

    Stateless and pure — reads only, never writes.
    Can be called from any context at any frequency.

    The PEP (graph.navigate) calls decide() once per traversal.
    Additional PEPs at graph.relate() and MCP tools can be added
    without modifying this class.
    """

    def decide(
        self,
        subject_id: str,
        requester_id: str,
        purpose: str,
        classification: int,
        operation: str,
        is_crisis: bool = False,
        text: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ConsentDecision:
        """
        Evaluate a consent request and return a ConsentDecision.

        Decision logic (in order — first match wins):
          1. Absolute barriers (not configurable)
          2. Consent disabled → permit (single-user mode unchanged)
          3. Audit-only mode → log and permit
          4. Self-access → permit
          5. Consent ledger check (via ConsentLedger.check())
          6. Default deny

        Never raises. Returns allowed=False with a reason on any error.
        """
        try:
            return self._decide_inner(
                subject_id, requester_id, purpose,
                classification, operation, is_crisis, text, context,
            )
        except Exception as exc:
            self._write_audit("CONSENT_GATE_ERROR", subject_id, str(exc))
            return ConsentDecision(
                allowed=False,
                reason=f"consent-gate-error: {exc}",
            )

    def _decide_inner(
        self,
        subject_id: str,
        requester_id: str,
        purpose: str,
        classification: int,
        operation: str,
        is_crisis: bool,
        text: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> ConsentDecision:

        # ── 1. ABSOLUTE BARRIERS ─────────────────────────────────────────────
        # Not configurable. Cannot be bypassed by consent, config, or profile.

        if is_crisis:
            self._write_audit(
                "CONSENT_GATE_CRISIS_BLOCKED", subject_id,
                "Crisis flag set — absolute barrier."
            )
            return ConsentDecision(
                allowed=False,
                reason="absolute-barrier:crisis-flag",
            )

        if text and _contains_crisis(text):
            self._write_audit(
                "CONSENT_GATE_CRISIS_BLOCKED", subject_id,
                "Crisis content in text — absolute barrier."
            )
            return ConsentDecision(
                allowed=False,
                reason="absolute-barrier:crisis-text",
            )

        if classification >= 4:
            self._write_audit(
                "CONSENT_GATE_PHI_BLOCKED", subject_id,
                f"Classification {classification} >= 4 — absolute barrier."
            )
            return ConsentDecision(
                allowed=False,
                reason=f"absolute-barrier:classification-{classification}",
            )

        # ── 2. CONSENT DISABLED ──────────────────────────────────────────────
        # Single-user deployments are entirely unchanged.

        if not _cfg.CONSENT_ENABLED:
            return ConsentDecision(
                allowed=True,
                reason="consent-disabled:single-user-mode",
            )

        # ── 3. AUDIT-ONLY MODE ───────────────────────────────────────────────
        # Log what would happen without blocking. Use during rollout.

        if _cfg.CONSENT_AUDIT_ONLY:
            decision = self._ledger_check(
                subject_id, requester_id, purpose,
                classification, operation, context,
            )
            self._write_audit(
                "CONSENT_AUDIT_ONLY",
                subject_id,
                f"[AUDIT ONLY] would_allow={decision.allowed} reason={decision.reason}",
            )
            return ConsentDecision(
                allowed=True,
                consent_id=decision.consent_id,
                reason=f"audit-only:{decision.reason}",
            )

        # ── 4. GATE ENFORCEMENT DISABLED ────────────────────────────────────
        # Same as audit-only but without the logging overhead.

        if not _cfg.CONSENT_GATE_ENFORCE:
            return ConsentDecision(
                allowed=True,
                reason="gate-enforce-disabled",
            )

        # ── 5. LEDGER CHECK ──────────────────────────────────────────────────

        decision = self._ledger_check(
            subject_id, requester_id, purpose,
            classification, operation, context,
        )

        # Write audit event for any blocked operation
        if not decision.allowed:
            self._write_audit(
                "CONSENT_GATE_BLOCKED",
                subject_id,
                f"Blocked: {decision.reason}. "
                f"purpose={purpose} op={operation} cls={classification}",
            )

        return decision

    def _ledger_check(
        self,
        subject_id: str,
        requester_id: str,
        purpose: str,
        classification: int,
        operation: str,
        context: Optional[Dict[str, Any]],
    ) -> ConsentDecision:
        """Delegate to the ConsentLedger for the policy decision."""
        from api.consent.ledger import consent_ledger
        return consent_ledger.check(
            subject_id=subject_id,
            requester_id=requester_id,
            purpose=purpose,
            classification=classification,
            operation=operation,
            context=context,
        )

    def _write_audit(
        self,
        event_type: str,
        subject_id: str,
        notes: str,
    ) -> None:
        """Write a consent gate event to the audit trail. Never raises."""
        try:
            from modules import memory as _memory
            _memory.record(
                event_type=event_type,
                notes=notes,
                context={"subject_id": subject_id},
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# MODULE-LEVEL SINGLETON
# ---------------------------------------------------------------------------

#: The global ConsentGate instance.
#: Usage:
#:   from api.consent.enforcement import consent_gate
#:   decision = consent_gate.decide(subject_id=..., ...)
consent_gate = ConsentGate()
