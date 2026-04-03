# Data Retention Policy

**Document ID:** RETENTION-001
**Version:** 1.1 (supersedes draft v1.0)
**Status:** Active — pending legal review for regulated deployments
**Covers:** Checklist item 5.03
**Last updated:** April 2026

> **Notice:** This document describes ONTO's retention architecture.
> Retention periods for regulated-industry deployments (healthcare,
> finance, legal, education) must be reviewed by qualified legal
> counsel before going live. See checklist item 4.01.

---

## The governing principle

**Retain the record. Not necessarily the data.**

The audit trail shell — record ID, timestamp, event type, classification
level, Merkle chain hash — is retained permanently. This permanence is
what makes the audit trail trustworthy. A record that can be deleted
can be manipulated.

The payload (actual personal content) is separable from the shell via
cryptographic erasure: destroying the encryption key makes the payload
permanently unreadable while the shell remains intact. The audit chain
is not broken. The right to erasure is honored.

This resolves the tension between GDPR Article 17 (right to erasure)
and the security requirement for an unbreakable audit trail.

---

## Retention by data type

### Audit trail (modules/memory.py)

| Layer | Retention | Mechanism |
|-------|-----------|-----------|
| Shell (record_id, timestamp, event_type, classification, chain_hash) | **Permanent** | Append-only SQLite trigger |
| Payload (notes, input, context, output, human_decision) | Permanent by default; erasable on request | Cryptographic erasure (key destruction) |

The shell contains no personal identifying information by design.
It cannot constitute sensitive data under any regulatory framework.

**No automatic deletion.** The audit trail grows indefinitely.
Operators who need time-bounded retention implement scheduled key
destruction for records older than their required window.
This is a [LEGAL REVIEW REQUIRED] item for regulated deployments.

### Session data (core/session.py)

| Data | Retention | Notes |
|------|-----------|-------|
| Session token | Memory only during session | Never written to disk |
| SESSION_START event | Permanent (shell) | Token prefix only, not full token |
| SESSION_END event | Permanent (shell) | Duration and identity only |
| Idle timeout | 1 hour default (ONTO_SESSION_TTL_SECONDS) | Configurable |
| Hard maximum | 8 hours default (ONTO_SESSION_MAX_LIFETIME_SECONDS) | Configurable |

After expiry or logout: token cleared from memory immediately.
GDPR Article 5(1)(c) data minimization is satisfied for session tokens.

### Graph data (modules/graph.py)

| Data | Retention | Notes |
|------|-----------|-------|
| Nodes and edges | Retained until `graph.wipe()` | Decay reduces weight; does not delete |
| PPMI counters | Retained until `graph.wipe()` | Cleared on wipe before nodes (FK order) |
| Provenance records | Permanent | Records that data existed, not the content |

`graph.wipe()` implements GDPR Article 17 right to erasure for graph content.
Nodes, edges, and PPMI counters are deleted. The audit trail records that a wipe
occurred — not the content. This is consistent with the cryptographic erasure
architecture: the shell (wipe event) persists, the payload (graph content) is gone.

### Classification-specific defaults

| Level | Label | Default retention | Notes |
|-------|-------|------------------|-------|
| 0 | Public | Permanent | No personal data present |
| 1 | Internal | Permanent | No external sharing concerns |
| 2 | Personal | Permanent shell; payload erasable | GDPR Article 17 applies |
| 3 | Sensitive | Permanent shell; payload erasable | Special category GDPR Art. 9 |
| 4 | PHI / Privileged | Permanent shell; payload erasable | HIPAA/legal privilege — never federates |
| 5 | Critical | Permanent shell; payload erasable | Maximum sensitivity — never federates |

---

## Phase 3 Federation data retention

Phase 3 adds federation infrastructure. Each table has its own retention model.

### federation_consent (api/federation/consent.py)

| Record type | Retention |
|-------------|-----------|
| Active consent record | Retained until revoked or expired |
| Revoked consent record | **Permanent** — revocation is an audit event |
| Expired consent record | **Permanent** — expiry is part of the history |
| Standing consent (expires_at=NULL) | Active until revoked; re-confirmation required every 90 days |

Consent records are part of the accountability chain. A revoked consent
record is not deleted — it is marked revoked with a timestamp and reason.
The history of what was consented to, when, and by whom is a permanent record.

### federation_peer_certs (api/federation/peer_store.py)

| Record | Retention |
|--------|-----------|
| Pinned certificate hash | Retained until `peer_store.remove_peer()` is called |
| Certificate rotation history | Permanent (rotation_count is cumulative) |

Peer certificates are retained as long as the peer relationship exists.
Operators remove a peer explicitly; the removal is recorded in the audit trail.

### federation_outbox / federation_inbox (api/federation/audit.py)

| Record | Retention |
|--------|-----------|
| Pending sends (sent_at=NULL) | Until sent or explicitly cleared by operator |
| Acknowledged sends (acked_at set) | Safe to prune after 90 days; no regulatory minimum |
| Failed sends (failed_at set) | Retained for operator review; prune after resolution |
| Received messages | Retained for audit purposes; prune after 90 days if not required |

Note: The outbox stores **payload hashes only**, not payloads.
Payloads are transmitted inline and never persisted locally.
No personal data is in the outbox or inbox.

### federation_node_config (api/federation/node_identity.py)

| Data | Retention |
|------|-----------|
| Node DID (did:key) | **Permanent** — identity record |
| Peer manifests (cached) | Retained until peer is removed or manifest is refreshed |

---

## Regulatory minimums

ONTO's indefinite audit trail satisfies all regulatory minimums by default.

| Regulation | Minimum | ONTO default |
|-----------|---------|--------------|
| EU AI Act Article 26 (high-risk) | 6 months | Indefinite ✅ |
| HIPAA | 6 years | Indefinite ✅ |
| GDPR | "As long as necessary" | Operator-defined ✅ |
| SOX | 7 years | Indefinite ✅ |

For regulated deployments: the relevant question is not whether data
is kept long enough — it is whether it is kept too long. Operators
should consult counsel to define maximum retention periods appropriate
to their context and implement scheduled key destruction accordingly.

---

## What operators must do before processing others' personal data

1. Define maximum retention periods for your jurisdiction and context.
2. Implement scheduled key destruction for data beyond your retention window.
3. Document your retention decisions and the lawful basis for them.
4. Have retention policy reviewed by qualified counsel (item 4.01).
5. Test `graph.wipe()` and erasure workflows before processing sensitive data.

---

## What still requires legal review

- [ ] Retention periods for specific regulated-industry deployments
- [ ] Key destruction schedule for personal data beyond retention window
- [ ] Right-to-correct workflow (append-only trail: Stage 2 item)
- [ ] Cross-border data flow in federation contexts (GDPR Art. 44)
- [ ] Retention obligations for federation consent records in multi-org contexts

---

*This document is part of the permanent record of ONTO.*
*It is updated as the retention architecture evolves.*
*Compliance is not a checkbox. It is a continuous commitment.*
