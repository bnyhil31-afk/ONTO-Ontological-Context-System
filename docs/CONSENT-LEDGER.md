# ONTO Consent Ledger — Operator Guide

**Document ID:** CONSENT-LEDGER-001
**Version:** 1.0
**Covers:** Phase 4 — Multi-User Consent Ledger
**Spec:** `docs/CONSENT-LEDGER-SPEC-001.md`
**Last updated:** April 2026

---

## What this is

The consent ledger enforces data access consent at the query layer —
every graph traversal involving another user's data is checked against
an active consent record before it executes. Not at a login screen.
Not at a terms checkbox. At the moment data actually moves.

This is disabled by default. Single-user deployments are entirely
unchanged. Enabling it adds multi-user and regulated-context capability.

---

## Quick start

**Step 1 — Enable**

```bash
export ONTO_CONSENT_ENABLED=true
export ONTO_CONSENT_PROFILE=team   # team | healthcare | financial
```

**Step 2 — Run ONTO normally**

```bash
python3 main.py
```

Consent tables are created automatically on first boot.

**Step 3 — Grant consent before multi-user operations**

```python
from api.consent.adapter import ConsentRecord
from api.consent.ledger import consent_ledger

record = ConsentRecord(
    subject_id="sha256_of_user_identity",
    grantor_id="sha256_of_user_identity",   # user grants to themselves
    requester_id="sha256_of_operator",
    purpose="dpv:ServiceProvision",
    legal_basis="gdpr:consent-art6-1a",
    operations=["read", "navigate"],
    classification_max=2,
)
consent_id = consent_ledger.grant(record)
```

---

## Configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `ONTO_CONSENT_ENABLED` | `false` | Master switch |
| `ONTO_CONSENT_PROFILE` | `team` | Regulatory profile |
| `ONTO_CONSENT_GATE_ENFORCE` | `true` | `false` = log only (rollout mode) |
| `ONTO_CONSENT_JIT_ENABLED` | `true` | Just-in-time prompting at navigate() |
| `ONTO_CONSENT_AUDIT_ONLY` | `false` | Log decisions without blocking |
| `ONTO_CONSENT_DELEGATION_MAX_DEPTH` | `3` | Max delegation chain length |
| `ONTO_CONSENT_RETENTION_DAYS` | `0` | Retention period (0 = indefinite) |
| `ONTO_CONSENT_RECONFIRM_DAYS` | `90` | Standing consent re-confirmation |
| `ONTO_VC_SERVICE_ENABLED` | `false` | W3C VC 2.0 sidecar (Phase 5) |
| `ONTO_VC_SERVICE_URL` | `http://127.0.0.1:7800` | Sidecar URL |

---

## Regulatory profiles

Select with `ONTO_CONSENT_PROFILE`. The underlying record structure
is identical across all three — only enforcement and presentation differ.

### Team (`team`) — default

For 2-50 people, low-regulation deployments.

- Per-purpose consent granularity
- JIT prompting (≤3 prompts per session)
- Electronic revocation
- Indefinite retention by default
- Delegation depth: 3 hops

### Healthcare (`healthcare`)

For HIPAA-covered entities and clinical research.

- Per-authorization granularity (one consent per PHI disclosure)
- Explicit consent for every operation
- Written revocation required (§164.508(b)(5))
- 6-year retention (2,190 days)
- Delegation depth: 1 (named parties only)
- Required fields: PHI description, expiry event, conditioning, redisclosure

### Financial (`financial`)

For SEC-registered, GLBA-covered, and MiFID II-subject firms.

- GLBA opt-out model (permitted until opt-out record found)
- Annual re-confirmation for standing consents
- 7-year retention (2,555 days) — SEC Rule 17a-4
- Retention lock on `legal-obligation` basis records (cannot erase)
- Privilege tagging supported
- Delegation depth: 1

---

## Consent lifecycle

```
GRANTED → ACTIVE
              ↓
       NEEDS_RECONFIRMATION (standing consent, 90 days elapsed)
              ↓
          REVOKED (terminal — permanent record, never deleted)
              or
          EXPIRED (valid_until reached — permanent record)
```

**Revocation cascades:** Revoking a parent consent automatically revokes
all delegated children. This is recorded as `CONSENT_CASCADE_REVOKED`
in the audit trail.

**Revocation is permanent.** Revoked records are marked, not deleted.
The full history of who consented to what, when, and when it was revoked
is always available for audit.

---

## Absolute barriers

These cannot be overridden by any consent record, configuration,
regulatory profile, or operator decision:

| Trigger | Block reason |
|---------|-------------|
| `is_crisis=True` | Crisis content never crosses a data boundary |
| Crisis text in input | Same as above — text-based detection |
| `classification >= 4` | PHI and privileged data never move without absolute isolation |

These are checked **before** the consent ledger is consulted. A valid
consent record does not bypass an absolute barrier.

---

## Rollout mode

To validate consent coverage before enforcing it:

```bash
export ONTO_CONSENT_AUDIT_ONLY=true
```

The gate logs what *would* have been blocked without blocking anything.
Watch the `CONSENT_AUDIT_ONLY` events in `onto_audit`. When you're
satisfied with coverage, flip to enforcing:

```bash
export ONTO_CONSENT_AUDIT_ONLY=false
```

Never ship to production with `CONSENT_AUDIT_ONLY=true`.

---

## DPV purpose vocabulary

Use these URIs in the `purpose` field:

| URI | Plain meaning |
|-----|--------------|
| `dpv:ServiceProvision` | Operating the ONTO system |
| `dpv:ResearchAndDevelopment` | Analytics, improvement |
| `dpv:LegalCompliance` | Audit, regulatory obligations |
| `dpv:SharingWithThirdParty` | Federation sharing |
| `dpv:PersonalisedBenefit` | Personalisation |
| `dpv:HealthcarePayment` | HIPAA treatment/operations |

Custom purposes may use your own URI namespace with a plain-language
`purpose_description`.

---

## Legal basis vocabulary

| Value | When to use |
|-------|-------------|
| `gdpr:consent-art6-1a` | EU deployment, explicit consent |
| `gdpr:legitimate-interest-art6-1f` | Legitimate interest (assessment required) |
| `gdpr:legal-obligation-art6-1c` | SEC/MiFID II retention (triggers retention lock) |
| `hipaa:authorization-164-508` | HIPAA named PHI authorization |
| `hipaa:treatment` | HIPAA treatment operations |
| `glba:opt-out` | GLBA financial data sharing |
| `legitimate-use` | Non-regulated contexts |

---

## W3C VC 2.0 (Phase 5)

The consent record schema includes W3C VC 2.0 fields today — they are
NULL until Phase 5 activates the VCService. No schema migration is
needed when Phase 5 arrives.

Phase 5 activates when `ONTO_VC_SERVICE_ENABLED=true` and a sidecar
or native Python VC 2.0 library is available. The sidecar exposes:
- `POST /vc/issue` — issue a signed VC for a consent record
- `POST /vc/verify` — verify a VC's proof and revocation status
- `POST /vc/revoke` — update the Bitstring Status List

When Phase 5 is active, consent records become cryptographically
verifiable, portable, and compatible with the EU Digital Identity
Wallet (December 2027 deadline).

---

## What still requires legal review

Before deploying the consent ledger for regulated contexts:

- Healthcare: confirm HIPAA §164.508 record structure with counsel
- Financial: confirm SEC Rule 17a-4 compliance with counsel
- EU: confirm GDPR Article 7 adequacy of ISO 27560 records with counsel
- EU: confirm SD-JWT VC adequacy for EUDIW compliance with counsel

See `docs/LEGAL_BRIEF.md` for the full list of items requiring review.

---

*This document is part of the permanent record of ONTO.*
*Consent is not a feature. It is a commitment.*
