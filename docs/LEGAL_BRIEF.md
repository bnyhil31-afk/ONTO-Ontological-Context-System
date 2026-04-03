# ONTO — Legal Counsel Brief

**For:** Technology and data privacy counsel
**Version:** 1.0 — April 2026
**Contact:** Neo (bnyhil31-afk)
**Repository:** github.com/bnyhil31-afk/ONTO-Ontological-Context-System
**License:** GNU Lesser General Public License v2.1 (LGPL-2.1)
**Status:** Pre-launch. No commercial deployment yet.

---

## What ONTO is

ONTO is an open-source ontological reasoning system. It takes natural
language inputs, builds a weighted knowledge graph, and surfaces context
for human-supervised decision-making. It is designed to run locally on
personal devices — phone, laptop, Raspberry Pi — with no cloud services
and no data leaving the device by default.

It is built on 13 cryptographically sealed principles (SHA-256 hash:
`b1d3054f646c5f3abaffd3a275683949aef426d135cf823e7b3665fb06a03ba5`).
These principles cannot be changed without the system detecting tampering
and refusing to run. They include: human wellbeing as highest priority,
unbiased and factual outputs, audit trail always on, freedom of choice,
and epistemic honesty as a protocol primitive.

Phase 3 adds optional peer-to-peer federation for sharing graph context
between nodes on a local network. Data only leaves a node with explicit
consent. A planned Phase 4 adds a multi-user consent ledger.

---

## Items requiring legal review

### Group A — Open source licensing

**A1. LGPL-2.1 scope and obligations**
ONTO is licensed under LGPL-2.1 (version-locked, not "or later").
We need counsel to confirm:
- The license correctly allows use of ONTO in proprietary applications
  built on top of it (without modifying ONTO itself) without requiring
  the proprietary application to be open-sourced
- The license correctly requires that modifications to ONTO's own
  source code be shared back under LGPL-2.1
- The `NOTICE` file's copyright and trademark assertions are complete
  and correctly worded for the jurisdiction(s) of intended operation

**A2. Patent pending notice**
The `NOTICE` file asserts patent-pending status for the three-axis
contextual reasoning architecture (Distance, Complexity, Size axes),
the wellbeing protection layer, the self-preserving node design,
and the SOMA integration concept.
We need counsel to:
- Review whether a provisional patent application has been filed
  (if not, advise on timeline)
- Confirm the `NOTICE` file language protects the IP claim without
  overstating what has been formally filed
- Advise on patent strategy for an open-source project

**A3. Trademark**
The `NOTICE` file includes a trademark notice for the ONTO name.
We need counsel to advise on formal trademark registration.

---

### Group B — Privacy and data protection

**B1. GDPR — cryptographic erasure as compliant deletion (§33.3 in CRE-SPEC-001)**
ONTO's audit trail is append-only — records cannot be deleted.
ONTO resolves the conflict with GDPR Article 17 (right to erasure)
through cryptographic erasure: the encryption key for personal data
is destroyed, rendering the payload permanently unreadable while
the audit trail shell remains intact.

The European Data Protection Board has recognized cryptographic
erasure as compliant deletion in guidance on pseudonymisation.
We need counsel to confirm:
- This approach is legally defensible for the EU jurisdictions
  we intend to operate in
- The specific implementation (AES-256-GCM, key stored only in
  memory during session) satisfies the EDPB's technical requirements
- Any residual risks (e.g., key material in memory dumps, swap files)
  are adequately mitigated or documented

**B2. HIPAA — authorization vs. consent (§33.4 in CRE-SPEC-001)**
Our Phase 4 consent ledger includes a healthcare regulatory profile
implementing HIPAA §164.508 authorization requirements. We need
counsel to confirm:
- The required elements (PHI description, named parties, expiry,
  conditioning statement, redisclosure warning) are correctly
  implemented in the schema
- Our interpretation of "written revocation" is technically sound
  (we require a non-empty revocation statement in the record)
- The healthcare profile is suitable for covered entities or
  requires additional elements

**B3. GLBA opt-out model (§33.5 in CRE-SPEC-001)**
The financial regulatory profile implements GLBA §6802 using an
opt-out model rather than opt-in. We need counsel to confirm:
- The opt-out record schema is legally compliant
- The 2023 GLBA Safeguards Rule amendments (effective May 2024)
  are reflected in the breach notification posture
- Annual re-confirmation requirement is appropriate

**B4. SEC Rule 17a-4 immutability (§33.6 in CRE-SPEC-001)**
Financial deployments use the audit-trail alternative pathway
(October 2022 amendment). We need counsel to confirm:
- ONTO's Merkle-chained, append-only audit trail qualifies as
  an audit-trail system under amended Rule 17a-4
- The 6-year / 3-year retention model is correctly implemented
- The retention lock on `legal-obligation` basis records is
  legally required and correctly designed

**B5. MiFID II cross-border consent (§33.7 in CRE-SPEC-001)**
For EU financial services deployments, federation across
organizational boundaries may implicate MiFID II Article 16(7)
(5-year tamper-proof retention). We need counsel to advise on:
- Whether ONTO's federation consent records satisfy MiFID II
  record-keeping requirements
- Cross-border data flow implications (GDPR Article 44) when
  two federated ONTO nodes are in different EU member states

---

### Group C — AI-specific obligations

**C1. EU AI Act classification (§33.8 in CRE-SPEC-001)**
ONTO is potentially a General Purpose AI (GPAI) model when
accessed via its MCP interface by general-purpose AI systems
(Claude, GPT, etc.). We need counsel to:
- Determine whether ONTO-as-MCP-server triggers GPAI obligations
  under EU AI Act Title III
- Advise on the high-risk system classification for regulated-domain
  deployments (healthcare, financial, legal)
- Confirm whether ONTO's human oversight architecture (checkpoint
  at every consequential decision) satisfies Article 14 requirements

**C2. Colorado AI Act and AB 2930**
Colorado's AI Act (effective February 2026) requires developers
of high-risk AI systems to perform impact assessments and disclose
risks. California AB 2930 has similar requirements. We need counsel
to advise on:
- Whether ONTO qualifies as a high-risk AI system under Colorado law
- Whether the existing `docs/REGULATORY-MAP-002.md` is adequate
  documentation or requires formal impact assessment
- Timeline for compliance if applicable

---

### Group D — Consent ledger (Phase 4 — pre-implementation)

**D1. Consent record adequacy across jurisdictions**
The Phase 4 consent ledger uses ISO/IEC 27560:2023 as its
record schema with W3C Data Privacy Vocabulary (DPV) concepts.
We need counsel to confirm:
- Whether ISO 27560 records satisfy GDPR Article 7 documentation
  requirements
- Whether the same schema serves HIPAA authorization requirements
  or requires a structurally separate record
- Whether DPV-based records are legally recognized in any jurisdiction
  we intend to operate in

**D2. W3C Verifiable Credentials (Phase 5 forward-compatibility)**
The consent ledger schema includes W3C VC 2.0 fields (NULL until
Phase 5 activates). We need counsel to advise on:
- Whether VC 2.0-based consent records have any recognized legal
  status in relevant jurisdictions
- EU Digital Identity Wallet compliance timeline (December 2027)
  and what ONTO must do before that deadline
- Whether SD-JWT VC satisfies the EUDIW technical requirements for
  consent records

**D3. Delegation and cascade revocation**
The consent ledger allows consent delegation (A delegates to B,
max 3 hops) with cascade revocation (revoking A auto-revokes B).
We need counsel to advise on:
- Whether cascade revocation is legally required or merely
  good practice under GDPR and HIPAA
- Whether delegation chains require explicit documentation
  of each hop in the chain
- Attorney-client privilege implications when consent records
  include privilege tagging

---

### Group E — Terms, policies, and operational documents

The following documents are drafted but have not been reviewed
by counsel. We need review and correction before public launch:

- `docs/PRIVACY_POLICY.md` — User-facing privacy policy
- `docs/TERMS_OF_USE.md` — Terms of use
- `docs/PRIVACY_GDPR.md` — GDPR architecture document
- `docs/DATA_RETENTION.md` — Data retention policy v1.1
- `docs/CONSENT_MANAGEMENT.md` — Consent management framework v1.1

All five are in the repository and can be reviewed as-is.

---

## What we have already done

To help scope the engagement, here is what has already been addressed:

- License migrated from MIT to LGPL-2.1 — LICENSE and all references updated
- Cryptographic erasure architecture designed and documented
- Data retention policy written covering all three phases
- Consent management framework written covering Stage 1 through Phase 4
- Regulatory compliance mapping (`docs/REGULATORY-MAP-002.md`) covering
  EU AI Act, GDPR, CCPA, HIPAA, GLBA, SEC 17a-4, MiFID II, SOX, FERPA
- Threat model (`docs/THREAT_MODEL_001.txt`) with 28 threats across
  9 categories — all Open/Critical threats mitigated or documented
- Security audit brief (`docs/SECURITY_AUDIT_BRIEF.md`) ready to send
  to technical auditors

---

## Suggested engagement structure

Given the scope, we suggest structuring the engagement as:

**Phase A (immediate):** Review Group A (licensing, IP) and Group E
(privacy policy, terms). These are needed before any public launch.

**Phase B (pre-launch):** Review Group B (privacy/data protection) and
Group C (AI Act). These are needed before multi-user or regulated-context
deployment.

**Phase C (Phase 4 pre-implementation):** Review Group D (consent ledger).
These decisions need to be made before Phase 4 code is written.

---

## Resources to send before the engagement

All documents referenced in this brief are available in the repository.
Suggested reading order for counsel:

1. `principles.txt` — the foundation (2 pages)
2. `docs/REGULATORY-MAP-002.md` — existing compliance work
3. `docs/THREAT_MODEL_001.txt` — security posture
4. `docs/CONSENT_MANAGEMENT.md` — consent architecture
5. `docs/DATA_RETENTION.md` — retention policy
6. `docs/CONSENT-LEDGER-SPEC-001.md` — Phase 4 design (most relevant
   to Groups B, C, D)

Counsel does not need to read the code. The architecture is documented
in the above files and can be understood without technical knowledge.

---

*This document is prepared in good faith to enable efficient legal review.*
*It does not constitute legal advice and does not create an attorney-client*
*relationship. All items marked [LEGAL REVIEW REQUIRED] in project*
*documents are open until counsel provides guidance.*
