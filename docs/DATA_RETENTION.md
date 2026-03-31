# Data Retention Policy

**File:** `docs/DATA_RETENTION.md`  
**Project:** ONTO — Ontological Context System  
**Version:** Draft 1.0  
**Status:** Pending legal review (checklist item 4.01)  
**Last updated:** 2026

> **Notice:** This is a working draft. Retention periods for specific
> deployment contexts must be reviewed by legal counsel, particularly
> for regulated industries.

---

## The retention design principle

ONTO's audit trail is permanent by design. The permanence of the record
is what makes it trustworthy. This creates a deliberate tension with
data minimization principles — which this document addresses directly.

The resolution: **retain the record, not the data.**

The audit trail shell (record ID, timestamp, event type, classification
level) is retained permanently. The payload (the actual personal content)
can be erased via key destruction while the shell remains. See
`docs/PRIVACY_GDPR.md` for the cryptographic erasure architecture.

---

## Default retention periods

These are ONTO's defaults. Operators should override them based on
their specific legal requirements and deployment context.

| Data type | Default retention | Rationale |
|---|---|---|
| Audit trail shell | Permanent | Chain integrity requires unbroken sequence |
| Session records | Permanent (shell) | Accountability requires session history |
| Intake records (classification 0) | Permanent | No personal data — no reason to limit |
| Intake records (classification 2–3) | Permanent shell; payload erasable | Subject to erasure request |
| Safety / crisis records | Permanent | May be required for incident review |
| System events (BOOT, HALT) | Permanent | Required for operational integrity |
| READ_ACCESS events | Permanent | Required for access accountability |

---

## Regulatory minimums

Some deployments have legally required minimum retention periods.
ONTO's permanent audit trail satisfies all of these by default.

| Regulation | Minimum retention | Relevant to ONTO |
|---|---|---|
| EU AI Act Article 26 | 6 months (high-risk AI systems) | High-risk deployments |
| HIPAA | 6 years from creation or last effective date | Healthcare deployments |
| GDPR (general) | No minimum — "as long as necessary" | All EU deployments |
| SOX | 7 years | Financial reporting contexts |
| FERPA | Duration of enrollment + varies | Education deployments |

ONTO retains all records indefinitely by default, satisfying all
minimums above. The question for operators is not whether records
are kept long enough — it is whether they are kept too long.

---

## When retention becomes a liability

Keeping data indefinitely is not always the right answer. Long
retention:

- Increases the value of a data breach (more data = more damage)
- May conflict with data minimization requirements (GDPR Art. 5(1)(e))
- Creates regulatory exposure in some jurisdictions

For Stage 1 (personal, single-device use), indefinite retention
is appropriate — the user controls their own data entirely.

For multi-user deployments (Stage 2+), operators should define
explicit retention schedules for each data classification level.

---

## Recommended retention schedule for Stage 2+ deployments

This is a starting point. Legal counsel should review before adoption.

| Classification | Recommended maximum | Notes |
|---|---|---|
| Level 0 (public) | No maximum | No personal data |
| Level 2 (personal) | 3 years from last activity | Unless legal hold applies |
| Level 3 (sensitive) | Duration of relationship + 1 year | Or regulatory minimum, whichever is longer |
| Level 4 (privileged) | As required by applicable privilege rules | Attorney-client, clinical, clergy vary by jurisdiction |
| Crisis / safety records | 7 years | May be needed for incident review |

---

## Implementing retention in ONTO

**Stage 1:** Retention is managed by the user. To clear all data:
```bash
rm data/memory.db
python3 main.py  # creates a fresh database
```

**Stage 2+ (planned):** Automated retention management will be
implemented through the consent ledger and the cryptographic erasure
layer. Records will not be deleted — their encryption keys will be
destroyed on the schedule you configure.

The shell record will always remain. The personal content will be
permanently unreadable after key destruction.

---

## Legal holds

If records become subject to litigation, regulatory investigation,
or legal hold, normal retention schedules are suspended. Records
under legal hold must not be erased, even at the subject's request.

ONTO's append-only architecture supports legal holds by default —
records cannot be deleted through normal operation. Key destruction
(erasure) must be suspended for records under legal hold.

This requires operator-level process controls. The system provides
the technical foundation; the process is the operator's responsibility.

---

## Reviewing this policy

This policy should be reviewed:
- Annually
- When a new deployment context is added
- When applicable regulations change
- When a data subject makes an erasure request that raises questions

---

*This document is a working draft and has not been reviewed by legal counsel.*  
*Retention periods for specific deployment contexts require legal assessment.*
