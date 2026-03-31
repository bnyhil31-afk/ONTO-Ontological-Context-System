# GDPR Architecture

**File:** `docs/PRIVACY_GDPR.md`  
**Project:** ONTO — Ontological Context System  
**Version:** Draft 1.0  
**Status:** Pending legal review (checklist item 4.01)  
**Last updated:** 2026

> **Notice:** This is a working draft. It has not been reviewed by legal
> counsel. GDPR compliance for any specific deployment must be assessed
> by a qualified data protection lawyer. This document describes the
> architectural design — not a legal guarantee of compliance.

---

## The core tension — and how ONTO resolves it

ONTO's audit trail is append-only by design. Records cannot be deleted
or modified. This is how the system earns trust — the trail is
tamper-evident precisely because nothing can be removed.

GDPR Article 17 gives individuals the right to have their personal
data erased ("the right to be forgotten").

These two requirements appear to conflict. They do not.

**ONTO resolves this through cryptographic erasure.**

---

## How cryptographic erasure works

Every record containing personal data (classification level 2 and above)
is stored in two layers:

```
COMMIT record
├── shell  (immutable — stays forever)
│   ├── record_id
│   ├── timestamp
│   ├── event_type
│   ├── classification_level
│   ├── chain_hash (Merkle link to previous record)
│   └── data_reference (pointer to payload)
│
└── payload  (encrypted — can be erased)
    └── actual personal content
        encrypted with subject's key
```

**The shell contains no personal identifying information.** Not names,
not email addresses, not dates of birth, not any field that could
identify a person on its own or in combination with other shell fields.

**The payload is encrypted with a key that belongs to the subject.**

**Erasure = key destruction.**

When a subject exercises their right to erasure, the encryption key
is destroyed. The shell remains — the audit trail records that
something happened at that timestamp. The payload becomes permanently
unreadable. Not archived. Not recoverable. Gone.

The audit trail is intact. The right to erasure is honored.

This approach is recognized as compliant erasure under GDPR by the
European Data Protection Board's guidance on pseudonymisation and
encryption. Legal counsel should confirm this for your specific
deployment context.

---

## What this means in practice for Stage 1

Stage 1 ONTO is a single-device, single-user deployment. In this
context:

- The operator and the subject are typically the same person
- Data does not leave the device
- "Erasure" in practice means deleting `data/memory.db`

The two-layer architecture described above is fully designed and
specified. The encryption layer (`core/encryption.py`) is implemented.
The per-subject key management for selective payload erasure is a
Stage 2 feature — it requires the multi-user and consent ledger
infrastructure that Stage 2 adds.

**For Stage 1:** GDPR compliance for personal deployments is achieved
by the user controlling and deleting their own database. No data
processor relationship exists.

**For Stage 2+:** The full cryptographic erasure architecture must
be implemented before any deployment that processes data on behalf
of other people.

---

## GDPR lawful basis

ONTO does not determine your lawful basis for processing — that
depends on your deployment context. Common bases:

| Basis | When it applies to ONTO |
|---|---|
| Consent (Art. 6(1)(a)) | User explicitly consents to their data being processed by ONTO |
| Legitimate interests (Art. 6(1)(f)) | Operator has a legitimate interest in contextual record-keeping |
| Contract (Art. 6(1)(b)) | ONTO is used to fulfil a contractual obligation |

For special category data (health, biometric, legal — classification
level 3 and above), Article 9 applies and explicit consent is
required in most cases.

---

## Data subject rights

| Right | ONTO's current position |
|---|---|
| Right of access (Art. 15) | ✅ Full audit trail readable at any time |
| Right to rectification (Art. 16) | ⚠️ Not supported — records are immutable by design. Shell correction records can be added; originals cannot be changed |
| Right to erasure (Art. 17) | ✅ Stage 1: delete database. Stage 2+: key destruction per subject |
| Right to restrict processing (Art. 18) | ⚠️ Not yet implemented — requires consent ledger (Stage 2) |
| Right to data portability (Art. 20) | ✅ SQLite database is a portable, open format |
| Right to object (Art. 21) | ⚠️ Not yet implemented — requires consent ledger (Stage 2) |

---

## Data minimisation (Art. 5(1)(c))

ONTO applies the minimum necessary principle at every layer:

- Inputs are truncated at `MAX_INPUT_LENGTH` (default 10,000 characters)
- The shell layer contains no personal data
- Classification is applied at intake — higher classification data
  receives stricter handling
- Read access to classification level 2+ data is logged

---

## Privacy by design (Art. 25)

The following privacy-by-design measures are built into the architecture:

- **Classification at intake** — sensitivity is assessed before any
  processing occurs
- **Audit trail** — all access to sensitive data is logged
- **Append-only enforcement** — records cannot be silently altered
- **Cryptographic chaining** — tampering is detectable
- **No telemetry** — no data leaves the device in Stage 1
- **Human sovereignty** — consequential decisions require human approval
- **Minimum necessary** — NAVIGATE returns only relevant context

---

## Data Protection Impact Assessment (DPIA)

A DPIA is required under GDPR Article 35 when processing is likely
to result in high risk to individuals — particularly for systematic
processing of sensitive data, large-scale profiling, or processing
in high-risk domains.

ONTO deployments in healthcare, legal, employment, or financial
contexts are likely to require a DPIA before processing begins.

A DPIA template and guidance is outside the scope of this document.
Legal counsel with GDPR expertise should conduct or supervise the DPIA.

---

## Audit retention for GDPR compliance

GDPR does not specify a single retention period — it requires data
to be kept "no longer than necessary for the purposes for which the
personal data are processed" (Art. 5(1)(e)).

See `docs/DATA_RETENTION.md` for ONTO's data retention policy.

---

## What still needs legal review

- [ ] Confirmation that key destruction constitutes lawful erasure
  in your specific jurisdiction and deployment context
- [ ] Lawful basis assessment for your deployment
- [ ] DPIA if required for your deployment context
- [ ] Data processor agreements if ONTO processes data on behalf
  of third parties
- [ ] Cross-border transfer mechanisms if data moves outside the EU
- [ ] Article 30 Records of Processing Activities (ROPA) for your
  deployment

---

*This document is a working draft and has not been reviewed by legal counsel.*  
*GDPR compliance for any specific deployment must be independently assessed.*
