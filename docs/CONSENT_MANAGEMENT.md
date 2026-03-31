# Consent Management Framework

**File:** `docs/CONSENT_MANAGEMENT.md`  
**Project:** ONTO — Ontological Context System  
**Version:** Draft 1.0  
**Status:** Pending legal review (checklist item 4.01)  
**Last updated:** 2026

> **Notice:** This is a working draft. Consent management for any
> specific deployment must be reviewed by legal counsel before
> processing personal data on behalf of others.

---

## What consent means in ONTO

Consent in ONTO means more than a checkbox. It is an architectural
primitive — a live governance instrument that is queried before every
operation involving personal data.

The consent ledger is not a log of past agreements. It is the
authoritative record of who has permission to do what with which
data, under what conditions, and for how long.

**No consent record = no operation.** For data at classification
level 2 and above, NAVIGATE checks the consent ledger before
traversal. An operation without a valid consent record is rejected
at the RELATE layer.

---

## The consent record

Every consent grant contains exactly:

| Field | Description |
|---|---|
| `grant_id` | Unique identifier for this consent grant |
| `subject_id` | Whose data this governs |
| `grantee_id` | Who receives permission (operator, system, specific user) |
| `scope` | What classification levels are covered |
| `purpose` | The specific declared purpose — not a general category |
| `operations` | Permitted operations: read, relate, navigate, export |
| `granted_at` | Timestamp of grant (externally anchored) |
| `expires_at` | Mandatory expiration — no perpetual grants |
| `granted_by` | Identity of the authorizing party |
| `authorization_ref` | Reference to the GOVERN event that authorized this grant |
| `revocation_status` | `active`, `revoked`, or `expired` |
| `revoked_at` | If revoked: timestamp |
| `revoked_reason` | If revoked: stated reason |

---

## Consent principles

**No implicit consent.**  
Every consent is explicit, specific, and recorded. "The user agreed
to the terms" is not a consent record. The specific data, purpose,
and operations must be named.

**No perpetual consent.**  
Every consent grant has a mandatory expiration date. Renewal requires
a new GOVERN event. There are no infinite grants.

**No broader than necessary.**  
Consent for one purpose does not cover other purposes. "Agreed to
use the system" does not consent to analysis, export, or sharing.
Each purpose requires its own grant.

**Revocable at any time.**  
A subject may revoke consent at any time. Revocation is immediate.
The revocation is recorded. Operations that relied on the revoked
consent are not retroactively invalidated — but new operations
against that data require a new grant.

**The GOVERN event is the consent event.**  
Every consent grant traces to a GOVERN event in the audit trail.
The human at the checkpoint authorized it. The record proves it.

---

## Consent in Stage 1 vs Stage 2+

### Stage 1 (current — single user, single device)

In Stage 1, the operator and the subject are typically the same
person. The user controls their own data. Formal consent records
are not required for this use case — the user is consenting to
their own data being processed.

The consent ledger architecture is designed and specified but not
yet implemented in the codebase. It is a Stage 2 feature.

**What this means for Stage 1 operators:**  
If you are running ONTO for yourself, no additional consent
infrastructure is needed. If you are running ONTO on behalf of
others — processing their personal data — you must obtain and
record their consent before Stage 2 consent ledger infrastructure
is available. This means external consent records (e.g., signed
consent forms, email confirmation) and careful manual processes
until the ledger is implemented.

### Stage 2+ (multi-user, networked)

The full consent ledger is required before any multi-user deployment.
No operation involving another person's personal data may proceed
without a valid consent record.

---

## Valid consent under GDPR

For EU deployments, consent must be:

- **Freely given** — no coercion, no bundling with other agreements
- **Specific** — each purpose requires separate consent
- **Informed** — the person understands what they are agreeing to
- **Unambiguous** — a clear affirmative action (not a pre-ticked box)
- **Withdrawable** — as easy to withdraw as to give

ONTO's consent architecture satisfies all five requirements by design:
- GOVERN event = affirmative action
- Purpose field = specific and declared
- Expiration = limited duration
- Revocation support = withdrawable

---

## Consent for special category data (GDPR Art. 9)

Data at classification level 3 and above (health, financial, legal,
biometric) constitutes "special category data" under GDPR in most
cases. Processing requires **explicit consent** — a higher standard
than general consent.

For ONTO, this means:
- Classification level 3+ data requires its own consent record,
  separate from any general consent
- The consent record must explicitly name the special category
- The GOVERN event authorizing the consent must be clear about
  the sensitive nature of the data

---

## Parental consent for minors

If ONTO may be used by or to process data about minors:

- Parental or guardian consent is required for users under 13 (US)
  or under 16 in most EU member states (GDPR Art. 8)
- Classification level is automatically elevated to 4 (privileged)
  for any data associated with a verified minor
- Age verification at the node level is required for deployments
  that may reach minors

---

## Implementation roadmap

The consent ledger is a Stage 2 feature. The implementation sequence:

1. **Schema** — add `consent_ledger` table to `data/memory.db`
2. **Grant** — implement `consent.grant()` — creates a consent record via a GOVERN event
3. **Check** — implement `consent.check(subject_id, purpose, operation)` — returns valid grant or None
4. **Revoke** — implement `consent.revoke(grant_id, reason)` — marks grant as revoked
5. **Integrate** — hook `consent.check()` into NAVIGATE before any traversal
6. **Audit** — all consent operations recorded in the audit trail

The schema is designed to be forward-compatible with W3C Verifiable
Credentials 2.0 — the fields align with the VC standard, enabling
cryptographically verifiable consent records in Stage 3+.

---

## For operators: before Stage 2

Until the consent ledger is implemented, operators processing data
on behalf of others must:

1. Obtain explicit, informed consent from each subject before
   running their data through ONTO
2. Record that consent externally (signed form, email, etc.)
3. Keep those external records linked to the ONTO audit trail
   record IDs for the relevant data
4. Honor revocation requests promptly and completely
5. Not process data beyond the scope of the consent obtained

This is a temporary process. The consent ledger will replace it
when Stage 2 is implemented.

---

## What still needs legal review

- [ ] Consent mechanism design for your specific deployment
- [ ] Age verification requirements for your jurisdiction
- [ ] Legitimate interest assessment (where consent is not the
  lawful basis)
- [ ] Cookie consent if a web interface is added (see checklist 5.06)
- [ ] Consent record format for W3C VC 2.0 forward-compatibility

---

*This document is a working draft and has not been reviewed by legal counsel.*  
*Consent management for any deployment processing others' personal data*  
*requires qualified legal and privacy engineering review.*
