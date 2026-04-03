# Consent Management Framework

**Document ID:** CONSENT-001
**Version:** 1.1 (supersedes draft v1.0)
**Status:** Active — pending legal review for multi-user/regulated deployments
**Covers:** Checklist item 5.04
**Last updated:** April 2026

> **Notice:** Consent management for any deployment processing personal
> data on behalf of others requires qualified legal and privacy
> engineering review before going live. See checklist item 4.01.

---

## What has been built

As of Phase 3, ONTO has a working consent ledger in `api/federation/consent.py`.
It records, validates, revokes, and tracks re-confirmation for every federation
data share operation. The schema is forward-compatible with W3C Verifiable
Credentials 2.0.

This document describes ONTO's full consent architecture — what is implemented
today, what is designed and planned, and what operators must do now.

---

## Consent by deployment stage

### Stage 1 — Single user, single device (current)

The operator and subject are the same person. The user controls their
own data entirely. No separate consent collection is required for
personal use.

**What this means:** If you run ONTO for yourself, process your own
data, and share nothing with other nodes — you are already compliant.
The system records your decisions in the audit trail. You have full
visibility and control.

**The boundary:** If you process personal data belonging to someone
else — even informally — you must obtain and record their consent
externally until the multi-user consent ledger is available (Stage 2).

### Phase 3 — Federation between nodes (implemented)

`api/federation/consent.py` implements a full consent ledger for
data sharing between ONTO nodes. Every share operation requires an
explicit consent record. No data leaves a node without one.

**What this means:** When you share graph context with a peer node,
you must:
1. Obtain a consent record via `consent.grant()`
2. Pass the `consent_id` to every `adapter.share()` call
3. Revoke via `consent.revoke()` when the authorization ends
4. The consent mode (explicit, session, or standing) controls
   how the checkpoint is presented

The consent ledger is queried before every outbound share. No share
proceeds without a valid, non-expired, non-revoked consent record.

### Stage 2 — Multi-user, networked (planned)

Full multi-user consent ledger. Every session requires an active
consent record. Consent is checked before every graph traversal
involving another user's personal data. W3C Verifiable Credentials
activate in Phase 5.

---

## The consent record (Phase 3 implementation)

```sql
CREATE TABLE federation_consent (
    consent_id          TEXT PRIMARY KEY,   -- UUID v4
    grantor_session     TEXT NOT NULL,      -- SHA-256(session_token)
    recipient_node      TEXT NOT NULL,      -- did:key of receiving node
    data_description    TEXT NOT NULL,      -- human-readable; permanent record
    data_concept_hash   TEXT,               -- SHA-256(sorted concept labels)
    classification      INTEGER NOT NULL,   -- max classification of shared data
    granted_at          REAL NOT NULL,
    expires_at          REAL,               -- NULL = standing consent
    last_reconfirmed    REAL,
    revoked_at          REAL,
    revocation_reason   TEXT,
    chain_hash          TEXT,               -- Merkle chain integrity link
    -- W3C VC 2.0 forward-compatible fields (NULL until Phase 5)
    vc_id               TEXT,
    vc_issuer           TEXT,
    vc_proof            TEXT
);
```

The `data_concept_hash` stores SHA-256(sorted concept labels) — not
the labels themselves. Auditors can verify what categories were shared
without the consent table becoming a second copy of the data.

---

## Consent modes (Phase 3)

| Mode | Config | Behavior | Use case |
|------|--------|----------|---------|
| `explicit` | Default | Every share triggers `onto_checkpoint` | Any sensitive sharing |
| `session` | `ONTO_FED_CONSENT_MODE=session` | One decision per session per peer | Trusted peers, frequent sharing |
| `standing` | `ONTO_FED_CONSENT_MODE=standing` | Standing record, 90-day re-confirmation | Long-term peer relationships |

**Standing consent** requires re-confirmation every
`ONTO_FED_STANDING_CONSENT_RECONFIRM_DAYS` (default 90 days). After 90
days without re-confirmation, the next share attempt triggers a checkpoint.
The consent is not revoked — it is flagged for review.

**W3C VC caveat:** Standing consent in Phase 3 is a simplified record,
not a cryptographically signed W3C Verifiable Credential. It is not
legally equivalent to a VC-based consent grant in jurisdictions that
require signed portable credentials. W3C VC activation is Phase 5.
Document this distinction clearly to users and counsel.

---

## Consent lifecycle

```
GRANTED → ACTIVE → REVOKED (terminal — permanent record)
              ↓
          EXPIRED (if expires_at reached — permanent record)
              ↓
          NEEDS_RECONFIRMATION (standing consent, 90 days elapsed)
```

**Revocation is immediate.** When `consent.revoke()` is called:
1. The local record is marked revoked with timestamp and reason
2. `adapter.recall()` sends retraction notices to affected peers
3. Local revocation succeeds even if peers are offline (sovereignty invariant)
4. The revocation event is permanently recorded in the audit trail

**Revoked records are never deleted.** The history of what was consented
to, when, and by whom — and when it was revoked and why — is a permanent
accountability record.

---

## Consent principles (Phase 3)

**No implicit consent for federation.** Every data share requires
an explicit consent record. The consent_mode controls how the
checkpoint is presented, but the record is always created.

**No perpetual consent.** `expires_at=NULL` creates a standing
consent — but standing consents require 90-day re-confirmation.
True indefinite consent without any re-confirmation is not supported
by design.

**No broader than necessary.** Each consent record covers specific
concepts (tracked by concept hash) at a specific classification level
to a specific peer node. Consent for one peer does not apply to others.

**Revocable at any time.** `consent.revoke()` is always available.
Revocation succeeds locally even when peers are unreachable.
Data sovereignty cannot be blocked by an offline network.

**Every consent traces to a human decision.** In `explicit` mode, the
`onto_checkpoint` tool produces the consent record. The GOVERN event
is in the audit trail. The human authorized it. The record proves it.

---

## GDPR lawful bases

ONTO's consent architecture is designed around GDPR Article 6 and 9.

| Deployment context | Applicable lawful basis | ONTO mechanism |
|-------------------|------------------------|----------------|
| Personal single-user | Legitimate interest (operator = subject) | No separate consent needed |
| Multi-user (Stage 2) | Consent (Art. 6(1)(a)) | Explicit consent record per user |
| Federation (Phase 3) | Consent (Art. 6(1)(a)) | `federation_consent` ledger |
| Special category data | Explicit consent (Art. 9(2)(a)) | Classification 3+ requires separate consent |
| Research/statistics | Compatible processing (Art. 89) | [LEGAL REVIEW REQUIRED] |

**Special category data** (classification level 3+: health, financial,
legal, biometric) requires explicit consent under GDPR Article 9 —
a higher standard than general consent. The operator must ensure the
consent record clearly identifies the special category.

---

## What the crisis content rule means for consent

**Crisis content is not subject to consent management — it is an
absolute barrier that consent cannot override.**

No consent record, no matter how broad or explicit, authorizes
the federation of crisis content. `safety.check_absolute_barriers()`
returns False for crisis content before any consent check is performed.
This is a protocol invariant, not a configuration option.

This is consistent with the wellbeing principle: the emotional and
physical safety of the end user takes precedence over all other
considerations, including operator-configured consent modes.

---

## W3C Verifiable Credentials roadmap

The `federation_consent` schema includes `vc_id`, `vc_issuer`, and
`vc_proof` fields. These are NULL until Phase 5 activates W3C VC
infrastructure. The schema requires no changes for activation.

W3C VC activation will enable:
- Cryptographically signed, portable consent records
- Bitstring Status List for revocation (W3C Recommendation, May 2025)
- EU Digital Identity Wallet compatibility (required by Dec 2027)
- Interoperability with other compliant systems

---

## For operators: before processing others' personal data

**Stage 1, personal use only:**
No additional consent infrastructure required.

**Stage 1, processing others' data (multi-user pre-Stage 2):**
1. Obtain explicit, informed consent from each subject externally
2. Record that consent (signed form, email, timestamped record)
3. Link external consent records to ONTO audit trail record IDs
4. Honor revocation requests promptly — purge their data from the graph
5. Consult counsel before handling sensitive or special-category data

**Phase 3, federation:**
1. Use `ONTO_FED_CONSENT_MODE=explicit` (the default)
2. Review `consent.py` consent records regularly via `onto_audit`
3. Re-confirm standing consents within the 90-day window
4. Test `consent.revoke()` and `adapter.recall()` before production use
5. For cross-organizational federation: obtain legal review of the
   inter-node data sharing agreement before enabling federation

---

## What still requires legal review

- [ ] Consent mechanism design for your specific deployment context
- [ ] Legitimate interest assessment (where consent is not the lawful basis)
- [ ] Standing consent adequacy without W3C VC in regulated jurisdictions
- [ ] Cross-border consent in federation contexts (GDPR Art. 44)
- [ ] Age verification and parental consent for deployments reaching minors
- [ ] Consent record format adequacy for your jurisdiction's requirements
- [ ] Inter-node data sharing agreement template for cross-org federation

---

*This document is part of the permanent record of ONTO.*
*Consent is not a feature. It is a commitment to the people whose*
*data moves through this system. Their sovereignty is non-negotiable.*
