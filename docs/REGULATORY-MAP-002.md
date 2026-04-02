# ONTO Regulatory Map 002
**Document ID:** REGULATORY-MAP-002
**Version:** 1.0
**Status:** Active — Supersedes COMPLIANCE-001 (extends, does not replace)
**Authors:** Neo (bnyhil31-afk), Claude (Anthropic)
**Scope:** All deployment contexts — single-node, intranet, enterprise, P2P public
**Note:** This document is not legal advice. Every item marked [LEGAL REVIEW REQUIRED]
          must be reviewed by qualified counsel before any commercial or public deployment.
          Recommended resources: EFF, Software Freedom Law Center (open-source context),
          and a technology/data-privacy attorney for enterprise and regulated domains.

---

## Purpose

COMPLIANCE-001 addressed GDPR, CCPA, data retention, consent, and safe messaging
for ONTO's Stage 1 single-node deployment. This document extends that foundation
to cover the full regulatory landscape that ONTO will encounter as it becomes an
ontology-driven integration layer exposed via MCP, operating across multiple
deployment contexts and regulated industries.

The ontology layer and MCP interface create new regulatory surface area that
COMPLIANCE-001 does not address. Specifically: AI Act obligations, provenance
and traceability requirements, inter-system data flows, and the trust/consent
implications of AI systems reasoning over enterprise data via MCP.

---

## Part I — EU AI Act

**Effective date for high-risk compliance:** August 2, 2026.
**Current date:** April 2026. **Time remaining:** ~4 months.

### 1.1 Is ONTO High-Risk?

The EU AI Act classifies AI systems by risk level. ONTO as infrastructure is
not itself a regulated AI system — it is a data management and reasoning layer.
However, *deployments* of ONTO in specific domains trigger high-risk classification.

| Deployment context                              | Risk tier      | Reason                              |
|-------------------------------------------------|----------------|-------------------------------------|
| ONTO as developer infrastructure only           | Minimal        | No direct end-user interaction      |
| ONTO powering a personal assistant              | Limited        | Transparency obligation applies     |
| ONTO in healthcare (patient data reasoning)     | HIGH-RISK      | Annex III, item 5 (medical devices) |
| ONTO in hiring/HR (candidate screening)         | HIGH-RISK      | Annex III, item 4 (employment)      |
| ONTO in education (student assessment)          | HIGH-RISK      | Annex III, item 3 (education)       |
| ONTO in financial services (credit decisions)   | HIGH-RISK      | Annex III, item 5b (creditworthiness)|
| ONTO in law enforcement (any reasoning)         | HIGH-RISK      | Annex III, item 6                   |
| ONTO as MCP server accessed by Claude/GPT       | Limited + GPAI | Transparency + GPAI rules may apply |

**Action required:** Before any regulated-domain deployment, operators must conduct
a conformity assessment and register with the EU AI Office. ONTO's architecture
is designed to *facilitate* this assessment via its audit trail, but the assessment
itself is a legal and organizational task, not a technical one.

### 1.2 What ONTO's Architecture Already Satisfies

| EU AI Act requirement                    | ONTO status | Evidence                              |
|------------------------------------------|-------------|---------------------------------------|
| Technical documentation (Article 11)     | ✅ Partial   | README, API docs, CHANGELOG           |
| Logging and monitoring (Article 12)      | ✅ Yes       | Cryptographic audit trail             |
| Transparency to users (Article 13)       | ✅ Yes       | surface.py epistemic honesty layer    |
| Human oversight (Article 14)             | ✅ Yes       | checkpoint.py at every consequential decision |
| Accuracy and robustness (Article 15)     | ⚠️ Partial   | Bias monitor designed, not yet built  |
| Record-keeping (Article 26)              | ✅ Yes       | Merkle-chained, append-only audit trail|

### 1.3 What Still Needs to Be Built

| Gap                                      | Priority | Phase  | Notes                              |
|------------------------------------------|----------|--------|------------------------------------|
| Bias monitoring and reporting            | High     | Phase 1| Checklist item 5.11                |
| Bias audit documentation                 | High     | Phase 1| Required before multi-user deploy  |
| Accuracy metric tracking                 | High     | Phase 2| Confidence scores exist; need metrics dashboard |
| Technical documentation formalization   | Medium   | Phase 0| Structured document per Article 11 |
| Incident response plan                  | Medium   | Phase 0| Required before public deployment  |
| GPAI model transparency (if applicable) | Low      | Phase 3| Depends on deployment context      |

[LEGAL REVIEW REQUIRED] — Confirm with counsel whether ONTO as an MCP server
accessed by general-purpose AI models triggers GPAI (General Purpose AI) obligations
under Title III of the AI Act.

---

## Part II — GDPR (Updated for Ontology Layer)

COMPLIANCE-001 covers GDPR at the data storage level. This section extends that
coverage to the ontology layer's new capabilities.

### 2.1 New Risks Introduced by Typed Edges

Typed directed edges create new GDPR obligations because semantic relationships
between data subjects (people) are themselves personal data under GDPR Article 4.

Example: An edge `(person_A) --[causes]--> (adverse_health_outcome)` in the
ontology graph is personal data about person_A. It requires a lawful basis for
processing (Article 6), falls under special category data if health-related
(Article 9), and is subject to the right to erasure (Article 17).

**Mitigation in DESIGN-SPEC-001:** Every edge carries a provenance_id linking
to the source and classification level. Classification level 3+ (sensitive/health
data) triggers the existing encrypted-payload path. The cryptographic erasure
architecture (COMPLIANCE-001 §5.01) applies to edges, not just raw data records.

### 2.2 New Risks Introduced by MCP Interface

When ONTO operates as an MCP server, data flows to AI systems (Claude, GPT, etc.)
as tool call results. These flows are data processing operations under GDPR.

| GDPR obligation                  | Implication for MCP interface                      |
|----------------------------------|----------------------------------------------------|
| Article 28 (Data processor)      | If ONTO processes personal data for an enterprise, a DPA is required |
| Article 44 (Cross-border transfer)| MCP calls to AI providers may involve data transfers outside EEA |
| Article 17 (Right to erasure)    | AI systems that cache tool results may retain personal data |
| Article 22 (Automated decisions) | `onto_checkpoint` must preserve human oversight for consequential decisions |

[LEGAL REVIEW REQUIRED] — Data Processing Agreement template for enterprise
deployments. EEA-to-US data transfer mechanisms (Standard Contractual Clauses
or adequacy decision) for MCP calls to US-based AI providers.

### 2.3 Right to Portability (Article 20) — Gap

COMPLIANCE-001 does not address data portability. The ontology layer makes this
more important: a user's personal knowledge graph (their ONTO node's relationship
graph filtered to their data) should be exportable.

**Required:** A `graph.export(user_id)` function that returns all nodes, edges,
and provenance records associated with a user's data in a portable format (JSON-LD
or JSON). This is a Phase 2 deliverable but should be architected now so the
provenance schema supports it.

---

## Part III — CCPA (Updated)

COMPLIANCE-001 addresses CCPA rights-to-know and right-to-delete. The new
additions for the ontology layer:

### 3.1 Right to Know — Graph Inference

Under CCPA, consumers have the right to know what inferences a business has
drawn about them. ONTO's ontology graph *is* a collection of inferences — typed
semantic relationships derived from user input.

**Mitigation:** Every edge carries provenance_id. A `graph.export_inferences(user_id)`
function (Phase 2) can enumerate all edges derived from a user's data, satisfying
the right to know about inferences.

### 3.2 Automated Decision-Making (AB 2930 — effective Jan 2026)

California's AB 2930 (effective January 1, 2026) extends CCPA with automated
decision-making rules requiring: pre-use notice, opt-out rights for certain
decisions, access rights to logic used, and a right to correction.

**ONTO status:** The `onto_checkpoint` tool and `checkpoint.py` already require
human authorization for consequential decisions. The audit trail records the
logic path. The surface layer discloses reasoning. This satisfies the spirit
of AB 2930's human oversight requirement.

[LEGAL REVIEW REQUIRED] — Confirm AB 2930 applicability and opt-out mechanism
for California-resident users.

---

## Part IV — HIPAA

HIPAA applies to ONTO deployments that handle Protected Health Information (PHI).
This is triggered when ONTO is used in healthcare settings (patient records,
clinical notes, medical ontologies) or processes health-related data on behalf
of a Covered Entity.

### 4.1 Current ONTO Architecture vs HIPAA Requirements

| HIPAA Safeguard                         | ONTO status  | Notes                              |
|-----------------------------------------|--------------|------------------------------------|
| Access controls (§164.312(a))           | ✅ Yes        | Auth, session management, RBAC planned for Stage 2 |
| Audit controls (§164.312(b))            | ✅ Yes        | Merkle-chained audit trail         |
| Integrity controls (§164.312(c))        | ✅ Yes        | Cryptographic chaining + HMAC      |
| Transmission security (§164.312(e))     | ✅ Stage 2    | mTLS planned for inter-node        |
| Encryption at rest (§164.312(a)(2)(iv)) | ✅ Yes        | AES-256-GCM                        |
| Workforce training (§164.308(a)(5))     | ❌ N/A        | Operator responsibility             |
| Business Associate Agreements           | ❌ Not yet    | Required before any PHI processing |
| Breach notification (§164.400)          | ❌ Not yet    | Incident response plan required    |
| Minimum necessary standard              | ⚠️ Partial    | Data classification exists; minimum-necessary query logic not yet built |
| PHI de-identification                   | ❌ Not yet    | Phase 3 requirement                |

### 4.2 Key Gap: Field-Level Encryption for PHI

The current AES-256-GCM encryption operates at the database level (encrypts the
entire SQLite file). HIPAA's minimum-necessary standard implies that different
users/roles should be able to access different subsets of PHI without decrypting
the entire database.

**Required before any HIPAA deployment:**
- Field-level encryption for PHI-containing columns (classification level 4+).
- Per-user encryption keys (not a single database key).
- Key management system (HSM or equivalent for enterprise).

This is a Phase 3 architecture item. Stage 1 and 2 ONTO deployments must not
be used to process PHI until field-level encryption is implemented and audited.

### 4.3 BAA Requirement

ONTO's operator becomes a Business Associate under HIPAA when processing PHI
on behalf of a Covered Entity. A signed Business Associate Agreement is legally
required before any such processing.

[LEGAL REVIEW REQUIRED] — BAA template. The CRE-SPEC-001 inter-node agreement
templates should include a HIPAA BAA variant.

---

## Part V — NIST AI Risk Management Framework (AI RMF)

NIST AI RMF 1.0 (January 2023) provides a voluntary framework for managing AI
risks. Enterprise adopters increasingly require AI RMF alignment as a procurement
criterion. ONTO's architecture maps naturally to the four core functions.

### 5.1 GOVERN Function

| GOVERN requirement                      | ONTO status | Implementation                        |
|-----------------------------------------|-------------|---------------------------------------|
| AI risk policies established            | ✅ Yes       | 13 sealed principles, GOVERNANCE.md   |
| Roles and responsibilities defined      | ✅ Partial   | checkpoint.py defines human-in-loop   |
| Organizational accountability           | ⚠️ Partial   | Governance structure not yet formal   |
| Continuous monitoring                   | ⚠️ Partial   | VERIFY runs continuously; bias monitor pending |

### 5.2 MAP Function (Context and Risk Identification)

| MAP requirement                         | ONTO status | Implementation                        |
|-----------------------------------------|-------------|---------------------------------------|
| Intended use cases documented           | ✅ Yes       | README, ROADMAP_001.txt               |
| Population and context identified       | ⚠️ Partial   | Wellbeing gradient exists; demographic monitoring pending |
| Risk identification                     | ✅ Yes       | 28 threats documented and mapped      |
| Impact assessment                       | ⚠️ Partial   | EU AI Act conformity assessment pending |

### 5.3 MEASURE Function (Analysis and Assessment)

| MEASURE requirement                     | ONTO status | Implementation                        |
|-----------------------------------------|-------------|---------------------------------------|
| Metrics defined for AI risks            | ⚠️ Partial   | Confidence scores exist; dashboard pending |
| Bias and fairness evaluation            | ❌ Not yet   | Checklist item 5.11                   |
| Explainability                          | ✅ Yes       | Reasoning trace in surface output     |
| Uncertainty quantification              | ✅ Yes       | Calibrated confidence scoring         |
| Testing and evaluation                  | ✅ Yes       | 227 tests, CI green                   |

### 5.4 MANAGE Function (Risk Response)

| MANAGE requirement                      | ONTO status | Implementation                        |
|-----------------------------------------|-------------|---------------------------------------|
| Risk response plans                     | ❌ Not yet   | Incident response plan required       |
| Human oversight mechanisms              | ✅ Yes       | checkpoint.py, onto_checkpoint tool   |
| Transparency to affected parties        | ✅ Yes       | surface.py, epistemic honesty layer   |
| Feedback mechanisms                     | ⚠️ Partial   | Designed; not yet user-facing         |

---

## Part VI — SOC 2 Type II

SOC 2 Type II is an audit standard covering security, availability, processing
integrity, confidentiality, and privacy. Enterprise customers in B2B SaaS contexts
increasingly require SOC 2 Type II certification as a procurement requirement.

COMPLIANCE-001 notes SOC 2 preparation as a Stage 2 item (2.12). This map
provides the detailed readiness assessment.

### 6.1 Trust Services Criteria — Current Status

| Criteria                                | Status       | Evidence / Gap                         |
|-----------------------------------------|--------------|----------------------------------------|
| CC1: Control environment                | ✅ Partial    | Governance documents, principles hash  |
| CC2: Communication and information      | ✅ Partial    | README, API docs, FAQ                  |
| CC3: Risk assessment                    | ✅ Partial    | 28 threats documented                  |
| CC4: Monitoring                         | ⚠️ Partial    | Audit trail yes; real-time monitoring no |
| CC5: Control activities                 | ✅ Partial    | Auth, session, rate limiting           |
| CC6: Logical and physical access        | ⚠️ Partial    | Auth done; RBAC pending Stage 2        |
| CC7: System operations                  | ❌ Not yet    | Incident response plan needed          |
| CC8: Change management                  | ✅ Yes        | CHANGELOG.md, rule 1.09A              |
| CC9: Risk mitigation                    | ✅ Partial    | Encryption, mTLS planned              |
| A1: Availability                        | ⚠️ Partial    | Single-node only; HA in Stage 3        |
| PI1: Processing integrity               | ✅ Yes        | Merkle chain, VERIFY module            |
| C1: Confidentiality                     | ✅ Yes        | AES-256-GCM, classification system     |
| P1-P8: Privacy                          | ✅ Partial    | GDPR/CCPA architecture, erasure pending|

### 6.2 SOC 2 Preparation Timeline

- **Stage 1 (now):** Document control environment, finalize incident response plan.
- **Stage 2:** Implement RBAC, monitoring dashboards, change management process.
- **Stage 2 (end):** Engage SOC 2 auditor for Type I report (point-in-time).
- **Stage 3:** 12-month observation period → Type II report.

---

## Part VII — NIST Cybersecurity Framework (CSF 2.0)

NIST CSF 2.0 (February 2024) is the updated version of the foundational
cybersecurity framework. It adds a GOVERN function (matching AI RMF) and is
now the baseline expectation for enterprise security programs.

### 7.1 CSF 2.0 Core Functions — Quick Map

| Function  | ONTO status | Key implementations                           |
|-----------|-------------|-----------------------------------------------|
| GOVERN    | ✅ Partial   | Sealed principles, GOVERNANCE.md, governance model |
| IDENTIFY  | ✅ Yes       | 28 threats, asset inventory in docs           |
| PROTECT   | ✅ Yes       | AES-256-GCM, auth, session, rate limit        |
| DETECT    | ⚠️ Partial   | VERIFY module; intrusion detection pending (2.10) |
| RESPOND   | ❌ Not yet   | Incident response plan required               |
| RECOVER   | ⚠️ Partial   | Backup guidance in README; formal plan pending|

---

## Part VIII — Financial Services (GLBA, PCI-DSS, SEC)

Financial services deployments of ONTO trigger additional regulatory requirements.
This section provides the overview; enterprise financial deployments require
engagement with a specialized financial regulatory attorney.

### 8.1 Gramm-Leach-Bliley Act (GLBA)

Applies when ONTO processes nonpublic personal financial information (NPFI) for
financial institutions. Key requirements:

- **Safeguards Rule (FTC):** Encryption at rest and in transit, access controls,
  employee training, vendor oversight, incident response. ONTO satisfies encryption
  and access controls; training and incident response are operator obligations.
- **Privacy Rule:** Opt-out rights for information sharing with non-affiliated
  third parties. The `onto_checkpoint` pattern applies here.

### 8.2 PCI-DSS v4.0

Applies if ONTO ever processes, stores, or transmits cardholder data (credit/debit
card numbers, CVVs, PINs). Strong recommendation: **do not store cardholder data
in ONTO**. If unavoidable, PCI-DSS v4.0 Requirement 3 mandates encryption with
key management procedures that exceed ONTO's current single-key architecture.

### 8.3 SEC AI-Related Guidance

The SEC has issued guidance on AI use in investment advice and trading. If ONTO
is used to power investment recommendations, the checkpoint pattern (human
authorization before consequential decisions) is the architecturally correct
response. Investment-context deployments require SEC registration review.

---

## Part IX — Healthcare (Beyond HIPAA)

### 9.1 FDA Software as a Medical Device (SaMD)

If ONTO's outputs are used to diagnose, treat, or manage patients, it may qualify
as Software as a Medical Device under FDA 21 CFR Part 820 and EU MDR 2017/745.
This triggers clinical validation requirements far beyond ONTO's current scope.

**Action:** Any healthcare deployment that influences clinical decisions must
obtain legal and regulatory guidance before deployment. ONTO's crisis detection
and safe messaging infrastructure (COMPLIANCE-001 §5.08) is a necessary but
not sufficient condition for clinical use.

### 9.2 21st Century Cures Act — Information Blocking

The information blocking provisions of the Cures Act apply to healthcare
information technology. If ONTO is deployed in healthcare and restricts access
to electronic health information, it must comply with the ONC's information
blocking exceptions. The open-source, MIT-licensed nature of ONTO supports
interoperability, which is the spirit of the Cures Act.

---

## Part X — Safe Messaging and Mental Health (Updated)

COMPLIANCE-001 §5.08 addresses AFSP/SAMHSA/WHO safe messaging compliance.
The ontology layer creates a new consideration: semantic relationships in the graph
can surface triggering content through inference, not just direct storage.

### 10.1 Graph Inference and Crisis Risk

Example risk: A user's ontology graph contains `(medication_name) --[causes]--
(overdose_risk)`. PPR traversal from an unrelated seed concept could surface
this relationship in context without the user explicitly requesting it.

**Mitigation required:**
- All edges involving `is_sensitive = 1` nodes inherit the sensitive flag.
- PPR traversal filters out sensitive-flagged edges from surface output unless
  explicitly authorized via checkpoint.
- The CRISIS detection in intake.py applies to *query inputs* and *surface outputs*,
  not just raw inputs.
- A `surface_safety_filter()` function (Phase 1) screens PPR results before
  returning them through `onto_surface` or any MCP tool.

### 10.2 AI-to-AI Interaction and Wellbeing

When ONTO operates as an MCP server accessed by AI systems, the wellbeing
protections must apply to the eventual human downstream, not just the AI caller.
The AI system calling `onto_query` may not be presenting results directly to
a human, but the results will eventually reach one.

**Principle:** Wellbeing protections are applied at the point of data surfacing,
regardless of whether the immediate caller is human or AI. The `onto_surface` tool
always applies the full wellbeing and crisis filter chain.

[LEGAL REVIEW REQUIRED] — Mental health professional review of the `surface_safety_filter()`
design before any multi-user deployment. Checklist item 5.09.

---

## Part XI — Open-Source Licensing Considerations

ONTO and CRE are both MIT-licensed. This has regulatory implications:

### 11.1 MIT License and Regulated Industries

MIT license grants broad permission including commercial use. However:
- Healthcare: open-source licensing does not exempt ONTO from FDA/HIPAA requirements.
- Financial: open-source does not exempt from SEC, CFTC, or banking regulator requirements.
- EU AI Act: the Act explicitly applies to open-source AI systems once they exceed
  certain scale thresholds (GPAI rules for models with > 10^25 FLOPs training compute
  do not apply to ONTO, but deployment rules may apply).

### 11.2 Patent Risk

The ontology and graph algorithms in ONTO draw on well-established academic work
(PPR, PPMI, CRDT). No novel patentable claims are made in the core architecture.
The combination of these techniques applied to the specific use case may warrant
a freedom-to-operate review before commercial deployment.

[LEGAL REVIEW REQUIRED] — Freedom-to-operate analysis before commercial launch.
EFF and Software Freedom Law Center are appropriate resources for open-source
patent defense strategy.

---

## Part XII — Regulatory Profile Framework (Cross-Reference to DESIGN-SPEC-001)

Per CRE-SPEC-001 §29, ONTO implements a regulatory profile system that allows
deployments to select their applicable compliance framework. The decay_profiles
table in DESIGN-SPEC-001 Part IV is the first expression of this — different
regulatory domains have different retention and decay requirements.

A full regulatory profile will eventually include:
- Data classification overrides (stricter than defaults)
- Decay rate configuration
- Audit trail retention period
- Encryption key rotation schedule
- MCP tool permission restrictions
- Geographic data residency enforcement

These profiles are not yet implemented but are architecturally planned in
CRE-SPEC-001 §29 (Regulatory Profile Framework). The schema designed in
DESIGN-SPEC-001 is forward-compatible with them.

---

## Part XIII — Action Register

Items requiring action before specific milestones:

### Before any public deployment:
- [ ] Legal counsel engaged (item 4.01) [LEGAL REVIEW REQUIRED]
- [ ] Third-party security audit (item 2.04)
- [ ] Incident response plan written
- [ ] Bias audit conducted (item 5.11)
- [ ] Mental health professional review (item 5.09)
- [ ] Freedom-to-operate analysis [LEGAL REVIEW REQUIRED]

### Before any enterprise deployment:
- [ ] SOC 2 Type I audit engaged
- [ ] Data Processing Agreement template finalized [LEGAL REVIEW REQUIRED]
- [ ] Business Associate Agreement template (for HIPAA contexts) [LEGAL REVIEW REQUIRED]
- [ ] EU AI Act conformity assessment (for high-risk deployment domains) [LEGAL REVIEW REQUIRED]
- [ ] AB 2930 opt-out mechanism designed

### Before any regulated-industry deployment (healthcare, finance):
- [ ] Domain-specific legal counsel engaged
- [ ] Field-level encryption implemented (Phase 3)
- [ ] RBAC implemented (Stage 2)
- [ ] Penetration test passed (item 2.08)
- [ ] Intrusion detection operational (item 2.10)

### Phase 1 code obligations (from regulatory requirements):
- [ ] `surface_safety_filter()` applied to all PPR outputs
- [ ] Sensitive edge inheritance logic (PPR respects is_sensitive)
- [ ] `graph.export(user_id)` design (right to portability groundwork)
- [ ] Bias monitoring design document (item 5.12)
- [ ] Bias audit pre-deployment (item 5.11)

---

## Summary — What ONTO's Architecture Already Gets Right

ONTO's core design choices are unusually well-aligned with regulatory requirements:

| Regulatory principle             | ONTO's architectural answer                              |
|----------------------------------|----------------------------------------------------------|
| Transparency (AI Act, NIST)      | Epistemic honesty in surface.py; reasoning traces       |
| Human oversight (AI Act, AB 2930)| checkpoint.py, onto_checkpoint tool; no autonomous consequential decisions |
| Audit trail (SOC 2, HIPAA, GLBA) | Merkle-chained, cryptographically sealed, append-only   |
| Privacy by design (GDPR, CCPA)   | Cryptographic erasure, data classification, consent ledger |
| Data minimization (GDPR)         | PPMI prunes co-incidental relationships; 15-concept cap |
| Integrity (HIPAA, SOC 2)         | Cryptographic chaining, VERIFY module                   |
| Portability (GDPR Art 20)        | Planned; schema supports it                             |
| Wellbeing (safe messaging)       | Crisis detection, wellbeing gradient, checkpoint gate   |
| Human sovereignty                | Sealed in the 13 principles; enforced by architecture   |

This document is part of the permanent record of ONTO.
It is a living document — updated as regulations change and as new deployment
contexts are confirmed. Compliance is not a checkbox. It is a continuous commitment.

*Let's explore together.*
