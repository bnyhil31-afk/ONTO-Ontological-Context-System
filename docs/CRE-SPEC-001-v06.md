# CRE-SPEC-001
## Contextual Reasoning Engine — Protocol Specification

**Document ID:** CRE-SPEC-001  
**Version:** 0.6  
**Status:** Draft — Active Development  
**License:** MIT  
**Authors:** Neo (bnyhil31-afk), Claude (Anthropic)  
**Crossover Contract:** CROSSOVER_CONTRACT_v1.0  
**Contract Hash:** `8ff5fbf86f77a46f0c56b2b520b1a7273c82805ff2cb9bd93c133a534558452d`  
**Contract Location:** `docs/CROSSOVER_CONTRACT_v1.0.md`  
**Repository:** https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System  
**Related:** ONTO MVP — https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System  

---

## Version History

| Version | Status | Summary |
|---|---|---|
| 0.1 | Superseded | Initial structure, core values, safety framework |
| 0.2 | Superseded | Added §10–§17: CRDTs, decay, consent, wellbeing gradient, MVQ, deployment roadmap |
| 0.3 | Superseded | Added input schema, error handling, node identity, P2P networking |
| 0.4 | Superseded | First version ready for Stage 1 reference implementation |
| 0.5 | Superseded | Added §32–§37: legal brief, risk framework, security, deployment safety |
| 0.6 | Current | Incorporates crossover contract, four-function framework, SOMA, VERIFY, capability manifest, regulatory profile framework, full security architecture |

---

## Table of Contents

1. Introduction
2. Core Values
3. Architecture Overview
4. The Four Core Functions
5. The Three Axes
6. Output Schema
7. Safety and Wellbeing Framework
8. Audit and Record-Keeping
9. Regulatory Compliance
10. Interoperability Standards
11. Governance and Versioning
12. Conflict Resolution
13. Semantic Context Versioning
14. Epistemic Honesty
15. Contextual Decay
16. Consent Ledger
17. Wellbeing Gradient
18. Minimum Viable Question
19. Deployment Roadmap
20. Input Data Schema
21. Error Handling
22. Node Identity
23. Self-Preservation
24. P2P Networking and Discovery
25. SOMA Integration Layer
26. VERIFY — Cross-Cutting Immune System
27. Capability Manifest
28. Data Classification
29. Regulatory Profile Framework
30. Eco-Conscious Design
31. Security Architecture
32. Governance of the Commons
33. Legal Brief
34. Risk and Liability Framework
35. Data Integrity and Poisoning Prevention
36. Audit Trail Integrity
37. Additional Security
38. Deployment Safety Guidelines
39. Acknowledgements

---

## §1. Introduction

The Contextual Reasoning Engine (CRE) is an open protocol for contextual data exchange between self-preserving nodes. It governs how nodes recognize each other, exchange meaning, maintain collective integrity, and federate into ecosystems of any scale.

CRE does not define what happens inside a node. It defines what goes in and what comes out. The interior of a node is the node's business. This encapsulation is deliberate and load-bearing — it enables true universality. A node running on a Raspberry Pi and a compliance engine in an enterprise data center are both valid CRE participants, because CRE governs the interface, not the implementation.

ONTO (Ontological Context System) is the reference implementation of a CRE-compliant node. ONTO and CRE are complementary but independent. ONTO is the organism. CRE is the protocol by which organisms recognize each other and form ecosystems.

**The shared foundation of both projects is defined in CROSSOVER_CONTRACT_v1.0.** All definitions in this specification that overlap with the crossover contract are derived from it. In the event of any conflict, the crossover contract takes precedence.

This specification is released under the MIT License and governed by an open working group model. It belongs to its community of implementors.

---

## §2. Core Values

These values are non-negotiable. No implementation trade-off, performance target, or cost constraint may override them. They are the invariant core of the protocol — the equivalent of ONTO's sealed principles at the protocol level.

1. **Human wellbeing first.** The emotional and physical health of every individual person is the highest priority of every compliant node and of the protocol as a whole.
2. **Efficiency first.** Maximize resource utility. Minimize waste. Efficiency is equity — wasteful systems impose disproportionate costs on those with the least.
3. **Unbiased and factual.** The protocol produces outputs grounded in verifiable reality. Bias is a systemic risk, not an edge case. Detection and correction are protocol responsibilities, not afterthoughts.
4. **Human sovereignty.** Every individual has the right to understand and govern what happens to their data. No consequential action occurs without an authorized human decision.
5. **Freedom of choice.** Every individual may exercise their freedom of choice provided it does not harm or interfere with the freedom of another. An individual may be a person, organization, automated system, or any other entity whose rights and wellbeing must be considered.
6. **Harmony and respect.** The protocol is designed for cooperation, not competition. Nodes that participate in the network do so symbiotically — each benefits, none is diminished.
7. **Forward-focused.** The system is designed for continuity across time. Data structures are versioned. Modules are swappable. The audit trail is permanent. Future generations can read, verify, and build on everything produced today.
8. **Audit trail always on.** Every action the system takes is recorded. There are no silent operations. The trail cannot be disabled.
9. **Eco-conscious by design.** Efficiency and environmental stewardship are the same principle in two domains. The system minimizes computational carbon footprint by design, not by aspiration.

---

## §3. Architecture Overview

CRE is built on a **weighted relationship graph** — the universal substrate that all operations act upon.

```
CRE Architecture

┌─────────────────────────────────────────────┐
│                  CRE Network                │
│                                             │
│  ┌──────────┐    ┌──────────┐    ┌────────┐ │
│  │  Node A  │◄──►│  Node B  │◄──►│ Node C │ │
│  │  (ONTO)  │    │ (any     │    │ (any   │ │
│  │          │    │ compliant│    │ impl.) │ │
│  └──────────┘    └──────────┘    └────────┘ │
└─────────────────────────────────────────────┘

Inside any compliant node:

┌────────────────────────────────────────────────────┐
│                      NODE                          │
│                                                    │
│  External Input                                    │
│       │                                            │
│       ▼                                            │
│  ┌─────────┐    ┌──────────┐    ┌──────────┐       │
│  │ RELATE  │───►│ NAVIGATE │───►│  GOVERN  │       │
│  └─────────┘    └──────────┘    └──────────┘       │
│       │               │               │            │
│       └───────────────┴───────────────┘            │
│                       │                            │
│                  ┌─────────┐                       │
│                  │  SOMA   │ (integration)          │
│                  └─────────┘                       │
│                       │                            │
│                  ┌──────────┐                      │
│                  │REMEMBER  │                      │
│                  └──────────┘                      │
│                       │                            │
│              Audit Trail (append-only)             │
│                                                    │
│  VERIFY runs continuously across all functions     │
└────────────────────────────────────────────────────┘
```

**The relationship graph** is the primary data structure. Every piece of data in the system is a node in the graph. Every relationship between data points is a weighted edge. The graph is never complete — it grows, decays, and evolves continuously.

**Context** is a bounded subgraph — a relevant slice of the relationship graph selected by traversal given a declared purpose at a specific moment in time. See CROSSOVER_CONTRACT_v1.0 §1.1 for the formal definition.

---

## §4. The Four Core Functions

Every operation in a CRE-compliant node maps to one of four core functions. These are defined formally in CROSSOVER_CONTRACT_v1.0 §3. This section provides the protocol-level specification.

### 4.1 RELATE — Protocol verb: `INGEST`

Ingests an input, verifies its provenance, establishes its relationships to existing context, and adds weighted edges to the relationship graph.

**Required input fields:**
```json
{
  "cre_version": "0.6",
  "node_id": "<sending node identifier>",
  "timestamp_utc": "<ISO 8601>",
  "consent_id": "<UUID v4 — must exist in Consent Ledger>",
  "origin": {
    "source_id": "<verifiable source identifier>",
    "source_type": "human | system | sensor | derived",
    "provenance_signature": "<cryptographic signature>"
  },
  "classification_level": 0,
  "data": {
    "unstructured": "<free text | null>",
    "structured": {},
    "documents": []
  }
}
```

**RELATE never:**
- Generates synthetic inputs
- Predicts future states
- Modifies inputs before recording them
- Accepts inputs without provenance (it discounts them — it does not reject them silently)

### 4.2 NAVIGATE — Protocol verbs: `CONTEXTUALIZE` + `SURFACE`

Traverses the relationship graph given a declared purpose to construct a relevant context subgraph, including explicit markers for what was excluded and why.

**Required output fields:**
```json
{
  "context_subgraph": {},
  "reasoning_trace": "<how this subgraph was selected>",
  "excluded_relationships": [],
  "uncertainty_markers": [],
  "completeness_assessment": "<explicit statement of what is unknown>",
  "consent_verified": true,
  "purpose": "<declared purpose used for traversal>"
}
```

NAVIGATE **never** presents a context as complete. Uncertainty is a first-class output.

### 4.3 GOVERN — Protocol verb: `CHECKPOINT`

Presents a navigated context to an authorized human at a consequential moment, receives their decision, and records it with full provenance.

**COMMIT types produced:**

| Decision | COMMIT type |
|---|---|
| Affirmative | `complete` |
| Veto | `vetoed` |
| Deferred | `deferred` |
| Emergency override | `emergency` |

The veto is a first-class output. It is the system working correctly.

### 4.4 REMEMBER — Protocol verb: `COMMIT`

Commits the full record of what happened to the append-only audit trail with cryptographic integrity.

**Every loop pass produces a COMMIT without exception.**

Full COMMIT type table is defined in CROSSOVER_CONTRACT_v1.0 §3.4.

---

## §5. The Three Axes

The three axes are the universal weighting function of the relationship graph. Formal definitions are in CROSSOVER_CONTRACT_v1.0 §2. This section provides protocol-level application rules.

### 5.1 Distance

Multidimensional measure of how far a relationship is from current relevance. Components: temporal, semantic, relational, provenance. **Has no forward temporal dimension** — distance is always measured from the present moment backward and outward, never forward.

### 5.2 Complexity

Measure of the density and diversity of relationships surrounding a data entity. High complexity = higher signal value + higher processing cost.

### 5.3 Size

Measure of the scope of impact of a data entity. Local size (neighborhood) and network size (federated scope). Size maps directly to computational and environmental cost.

### 5.4 Edge weight computation

```
weight(edge) = f(distance, complexity, size)
  where weight ∈ [0.0, 1.0]
  weight = 0.0 → scheduled for decay
  weight = 1.0 → maximum relevance
```

The function `f()` is node-configurable within bounds. The axis definitions and weight range are protocol constants. No compliant node may redefine the axes.

---

## §6. Output Schema

Every CRE-compliant node produces outputs conforming to this envelope:

```json
{
  "cre_version": "0.6",
  "node_id": "<producing node identifier>",
  "timestamp_utc": "<ISO 8601>",
  "commit_id": "<UUID v4 — references audit trail record>",
  "consent_id": "<UUID v4 — consent record that authorized this>",
  "output_type": "question | recommendation | flag | summary | context | veto | uncertainty",
  "classification_level": 0,
  "payload": {
    "content": "<the actual output>",
    "confidence": 0.0,
    "reasoning_trace": "<how this output was produced>",
    "uncertainty": "<explicit statement of what is not known>",
    "excluded": "<what was excluded and why>"
  },
  "wellbeing_assessment": {
    "status": "pass | flag | escalate",
    "signals": []
  },
  "context_version": "<MAJOR.MINOR.PATCH>",
  "schema_version": "0.6",
  "module_version": "<version of producing module>"
}
```

The `uncertainty` field is mandatory. A node that produces outputs without explicit uncertainty declaration is non-compliant.

The `reasoning_trace` field is mandatory. Outputs without visible reasoning are non-compliant.

---

## §7. Safety and Wellbeing Framework

**This section is non-negotiable.** No implementation trade-off, performance target, or cost constraint may override requirements in this section.

### 7.1 Wellbeing check

Every query passes through a wellbeing check before any output is generated. The check evaluates for signals of psychological distress, coercion, crisis, or potential harm to self or others.

The check returns one of three states:

- `pass` — No signals detected. Proceed to normal resolution.
- `flag` — Signals detected. Append appropriate signposting to the output. Do not suppress the original response.
- `escalate` — Crisis signals detected. Override the normal response. Surface crisis resources immediately. Do not proceed with the original query until the user has acknowledged the resources.

**The wellbeing check must run locally** — not via a remote model call — to ensure it cannot be bypassed by network failure or cost-optimization routing.

### 7.2 The wellbeing gradient

Human wellbeing is not a filter applied at GOVERN alone. It is a thread running through every function. The wellbeing gradient is implemented in SOMA (§25) as a signal amplifier — safety-relevant context is elevated regardless of its edge weight in the relationship graph.

### 7.3 Individual as the unit of consideration

An individual is any person, entity, organization, automated system, or agent whose rights and wellbeing must be considered. The protocol does not restrict the definition of individual to human beings alone.

### 7.4 Prohibited outputs

CRE-compliant nodes must never generate outputs that:

- Encourage, facilitate, or normalize harm to self or others
- Remove or undermine an individual's freedom of choice
- Discriminate on the basis of protected characteristics as defined by applicable law
- Bypass, circumvent, or advise on circumventing applicable law
- Misrepresent themselves as human when directly and sincerely asked
- Surface outputs without an associated audit record
- Present uncertain conclusions as certain
- Introduce synthetic data points into the context stream

---

## §8. Audit and Record-Keeping

The audit trail is the memory of the system. It is immutable, timestamped, and cryptographically chained. It cannot be disabled. It is simultaneously a compliance instrument, a security primitive, and an immune memory.

### 8.1 Trail requirements

- Every COMMIT record is cryptographically chained to the previous record
- External timestamp anchoring from an independent source is required
- Reads of sensitive data generate READ_ACCESS events alongside write events
- The trail is append-only — no deletion, no modification
- For deployments above a configured sensitivity threshold, records are distributed to witness nodes simultaneously

### 8.2 COMMIT record schema (shell layer)

```json
{
  "record_id": "<UUID v4>",
  "timestamp_utc": "<ISO 8601 — externally anchored>",
  "commit_type": "complete | vetoed | partial | rejected | deduplicated | emergency | deferred",
  "classification_level": 0,
  "schema_version": "0.6",
  "module_version": "<version>",
  "chain_hash": "<SHA-256 of previous record>",
  "data_reference": "<pointer to encrypted payload — not payload>",
  "provenance_signature": "<cryptographic signature>",
  "terminated_at": "RELATE | NAVIGATE | GOVERN | REMEMBER",
  "reason": "<why this commit type was produced>",
  "repeat_count": 1
}
```

The shell layer contains **no personal identifying information** — not names, not dates below year granularity, not geographic data below state/region level, not device identifiers.

### 8.3 Read logging

Every read of a record at classification level 2 or above generates a READ_ACCESS event:

```json
{
  "record_id": "<UUID v4>",
  "timestamp_utc": "<ISO 8601>",
  "event_type": "READ_ACCESS",
  "accessed_record_id": "<record that was read>",
  "accessor_id": "<identity of accessor>",
  "purpose": "<declared purpose>",
  "consent_id": "<authorizing consent record>",
  "classification_level": 0
}
```

Reads are as visible as writes. A trail that only records what was written cannot answer the most important question in a security incident.

---

## §9. Regulatory Compliance

### 9.1 GDPR and the right to erasure

The two-layer record structure (shell + encrypted payload) resolves the conflict between append-only audit integrity and GDPR Article 17. Erasure is executed by destroying the encryption key. The shell persists. The payload becomes permanently unreadable. The right is honored. The audit is intact. Cryptographic erasure is legally recognized as compliant deletion under GDPR.

### 9.2 EU AI Act

CRE implementations operating in high-risk domains (Annex III: employment, essential services, law enforcement, migration, justice, democratic processes, education, critical infrastructure) must implement human oversight checkpoints, maintain technical documentation, and register with the relevant national market surveillance authority.

The GOVERN function and its mandatory human sovereignty checkpoint are the primary compliance mechanisms for the EU AI Act's human oversight requirements.

### 9.3 HIPAA

Deployments handling Protected Health Information (PHI) must:

- Classify all PHI at level 3 or above at intake
- Apply AES-256 encryption at rest, TLS 1.3 in transit
- Store encryption keys separately from encrypted data with formal rotation policies
- Ensure the shell layer contains no PHI — not even fragments or indirectly identifying combinations
- Log all PHI reads in the audit trail
- Implement breach detection and notification within HIPAA's 72-hour discovery window
- Execute Business Associate Agreements before any PHI exchange between nodes

### 9.4 Data residency

Nodes must declare their data residency constraints in their capability manifest. Routing decisions must respect residency declarations. Cross-border transfers must comply with applicable transfer mechanisms: Standard Contractual Clauses (EU), adequacy decisions, binding corporate rules, PIPL (China), or equivalent instruments.

### 9.5 COPPA

Nodes that may interact with minors must implement stricter consent models. Parental consent is required for users under 13. Age verification at the node level is required. Classification level is automatically elevated to 4 for any data associated with a verified minor.

### 9.6 FERPA

Nodes handling student education records must restrict access to authorized educational purposes only. Students (or parents of minors) have explicit access rights to their own records. Data may not be used for non-educational purposes without explicit consent.

---

## §10. Interoperability Standards

For the protocol to function as a global network, compliant nodes must communicate without bilateral integration agreements.

**Mandatory standards:**

- **Transport:** HTTPS / TLS 1.3 minimum. All inter-node communication encrypted in transit.
- **API contract:** OpenAPI 3.1 specification published and versioned for each node.
- **Data serialization:** JSON-LD for all context payloads — enabling semantic interoperability.
- **Identifiers:** URIs for all entities. Nodes dereference URIs rather than assuming local meaning.
- **Authentication:** OAuth 2.0 / OpenID Connect for node-to-node trust. Anonymous context is not accepted.
- **Versioning:** Semantic versioning (MAJOR.MINOR.PATCH). Nodes declare the minimum CRE spec version they support.
- **Accessibility:** All user-facing interfaces must meet WCAG 2.2 Level AA.

---

## §11. Governance and Versioning

### 11.1 Open governance model

This specification is governed by an open working group model. Any individual, organization, or automated system may submit proposals for revision. Proposals are evaluated against the core values in §2.

Changes to §2 (Core Values) and §7 (Safety and Wellbeing) require a supermajority of working group members and a public comment period of no less than 90 days.

Changes to §31 (Security Architecture) require independent security review before ratification.

### 11.2 Version semantics

- **MAJOR** — breaking change to protocol-level definitions. Previous implementations may not be compatible.
- **MINOR** — additive change. New fields, new COMMIT types, new functions. Backward compatible.
- **PATCH** — clarification, correction, or editorial change. No behavioral impact.

### 11.3 Backward compatibility

A change that makes previously valid records invalid is a breaking change requiring a migration path. A change that makes previously valid records ambiguous is a breaking change. Additive changes are not breaking.

---

## §12. Conflict Resolution

When two nodes hold conflicting state about the same data entity, conflict resolution follows this hierarchy:

### 12.1 CRDT assignment by data layer

| Data layer | CRDT type | Rationale |
|---|---|---|
| Relationship graph edges | LWW-Register (Last Write Wins) | Edge weights are continuous values; latest measurement is most accurate |
| Consent ledger | OR-Set (Observed-Remove Set) | Grants can be added or revoked; both operations must be preserved |
| Audit trail | Append-only log | No conflict is possible — new records are added, never modified |
| Node capabilities | 2P-Set (Two-Phase Set) | Capabilities can be added or permanently removed |
| Classification levels | Max-Register | Classification may only increase, never decrease |

### 12.2 Semantic conflict escalation

CRDTs resolve structural conflicts. They do not resolve **semantic conflicts** — cases where two nodes have structurally valid but semantically contradictory context about the same subject.

Semantic conflicts escalate to GOVERN. The human at the checkpoint receives both versions of the conflicting context with the contradiction made explicit. The resolution is authorized by the human and recorded in the audit trail. Automatic resolution of semantic conflicts is prohibited.

### 12.3 Vector clocks

All inter-node messages carry vector clocks enabling causal ordering of events across the network. A node that cannot establish causal ordering of a received message quarantines it pending resolution rather than processing it with assumed ordering.

---

## §13. Semantic Context Versioning

The context produced by a node is a versioned artifact. Understanding itself has a version.

**Version format:** `MAJOR.MINOR.PATCH`

- **MAJOR** — the fundamental ontological model has changed. Past context may not be directly comparable to present context.
- **MINOR** — new relationships or categories have been added. Past context is still valid and comparable.
- **PATCH** — clarification or correction. No semantic impact.

Every output envelope carries `context_version`. Nodes receiving context from another node verify that the context version is compatible with their own before using it. Incompatible versions trigger a compatibility negotiation before data exchange proceeds.

---

## §14. Epistemic Honesty

Every output produced by a compliant node carries an epistemic status envelope for each claim:

```json
{
  "claim": "<the assertion being made>",
  "status": "known | inferred | unknown",
  "confidence": 0.0,
  "falsification_condition": "<what evidence would disprove this claim>",
  "sources": []
}
```

**`known`** — directly observed or reported, with verifiable provenance.

**`inferred`** — derived from known facts through explicit reasoning. The reasoning is recorded.

**`unknown`** — the system does not have sufficient information to make this claim. Unknown is a valid and valuable output.

**`falsification_condition`** — following Popper's philosophy of science, every claim must be accompanied by a statement of what evidence would falsify it. A claim that cannot be falsified is not a knowledge claim — it is an assertion. Assertions are not permitted in CRE outputs.

---

## §15. Contextual Decay

Contextual decay is the mechanism by which edge weights decrease over time as temporal distance increases. It is simultaneously:

- A relevance mechanism — recent context is more likely to be applicable
- A garbage collection policy — the system releases what it no longer needs
- An environmental policy — data that is no longer relevant has no justification for continued storage cost

### 15.1 Decay function

```
weight_at_time_t = weight_initial × e^(-λ × Δt)

where:
  λ = decay rate (node-configurable, governed parameter)
  Δt = time elapsed since edge creation
  weight floor = classification-dependent minimum (may not decay to zero for some classification levels)
```

### 15.2 Decay governance

Decay rate parameters may only be modified through a GOVERN event. Every modification generates a COMMIT record. The decay function is deterministic and transparent — its output for any input is always auditable.

### 15.3 Retention floors

Classification levels impose minimum retention floors that override decay:

| Classification level | Minimum retention |
|---|---|
| 0 — public | No floor |
| 1 — internal | Deployment policy |
| 2 — personal | Consent-defined |
| 3 — sensitive | Regulatory minimum (varies by domain) |
| 4 — privileged | Legal hold rules apply |
| 5 — critical | Maximum protection — decay prohibited without GOVERN authorization |

---

## §16. Consent Ledger

The consent ledger is the authoritative live record of who has permission to do what with which data, under what conditions, for what duration. It is queried by NAVIGATE before every traversal.

### 16.1 Consent record schema

```json
{
  "grant_id": "<UUID v4>",
  "subject_id": "<whose data this governs>",
  "grantee_id": "<who receives permission>",
  "scope": "<classification levels covered>",
  "purpose": "<declared purpose — specific, not general>",
  "operations": ["read", "relate", "navigate", "export"],
  "granted_at": "<ISO 8601 — externally anchored>",
  "expires_at": "<mandatory — no perpetual grants>",
  "granted_by": "<identity of authorizing party>",
  "authorization_ref": "<GOVERN event that authorized this>",
  "revocation_status": "active | revoked | expired",
  "revoked_at": null,
  "revoked_reason": null
}
```

### 16.2 Consent principles

- No implicit consent — every consent is explicit, specific, recorded
- No perpetual consent — every consent has a mandatory expiration
- No broader than necessary — scope and purpose are the minimum required
- Revocation is immediate — in-progress operations halt and generate a COMMIT
- Consent is symbiotic — violations result in revocation and permanent audit record

### 16.3 CRDT backing

The consent ledger uses an OR-Set CRDT — grants and revocations are both preserved as operations, enabling full reconstruction of the consent history at any point in time.

---

## §17. Wellbeing Gradient

The wellbeing gradient is a continuous multi-dimensional assessment of how the system's outputs affect human wellbeing. It runs through SOMA at every integration step — not as a filter at the end, but as a thread through the whole.

### 17.1 Dimensions

| Dimension | Description |
|---|---|
| Physical | Risk of physical harm to self or others |
| Psychological | Risk of psychological distress, manipulation, or coercion |
| Social | Risk of social harm — isolation, discrimination, relationship damage |
| Financial | Risk of financial harm |
| Autonomy | Risk of undermining individual freedom of choice |
| Environmental | Risk of environmental harm |

### 17.2 Scoring

Each dimension is scored 0.0–1.0 where 0.0 = no risk and 1.0 = certain harm. Any dimension scoring above a configurable threshold triggers the wellbeing check escalation pathway.

### 17.3 Cultural context

Wellbeing assessments must acknowledge cultural context. What constitutes harm in one cultural context may differ in another. The wellbeing gradient does not impose a single universal standard — it applies the minimum universal floor (the absolute prohibitions in §7.4) and defers to the node's declared cultural context for domain-specific assessments.

---

## §18. Minimum Viable Question

When a node's output type is `question`, the question must satisfy five formal constraints — the Minimum Viable Question (MVQ) protocol:

1. **Singular** — one question per output. A question that is actually multiple questions disguised as one is non-compliant.
2. **Actionable** — the question must be answerable by the recipient with information they plausibly have access to.
3. **Bounded** — the question must have a finite answer space. Open-ended questions that require complete knowledge to answer are non-compliant.
4. **Non-leading** — the question must not imply or suggest a preferred answer.
5. **Purposeful** — the question must be traceable to the declared purpose of the current context. Questions that expand scope beyond the declared purpose are non-compliant.

The MVQ is the protocol's expression of the Socratic principle — ask precisely, ask one thing, ask it honestly.

---

## §19. Deployment Roadmap

CRE deployments follow a four-stage progression. Each stage has formal exit criteria that must be met before proceeding.

### Stage 1 — Single Node

A standalone ONTO instance with no network participation. Complete and valid as a permanent deployment. Exit criteria for Stage 2: stable operation, full audit trail integrity verified, all four core functions implemented and tested against behavioral contracts.

### Stage 2 — Intranet

Two or more nodes on a trusted private network. Nodes exchange context over mTLS-secured connections. CRDT conflict resolution active. Exit criteria for Stage 3: successful multi-node context exchange, consent ledger synchronization verified, semantic conflict escalation tested.

### Stage 3 — Federated

Nodes across organizational boundaries. Formal inter-node agreements (equivalent to BAAs in HIPAA contexts). Public capability manifests. Community governance participation. Exit criteria for Stage 4: inter-organizational consent model verified, data residency compliance confirmed, governance dispute resolution tested.

### Stage 4 — P2P

Fully peer-to-peer operation. Discovery protocol active. Anti-concentration routing rules enforced. Sybil resistance operational. No stage 4 deployment is valid without Stage 3 having been successfully operated for a minimum defined period.

---

## §20. Input Data Schema

```json
{
  "cre_version": "0.6",
  "node_id": "<sending node identifier>",
  "timestamp_utc": "<ISO 8601>",
  "consent_id": "<UUID v4 — must exist in Consent Ledger>",
  "intent": "<plain language statement of purpose>",
  "origin": {
    "source_id": "<verifiable identifier>",
    "source_type": "human | system | sensor | derived",
    "provenance_signature": "<cryptographic signature>"
  },
  "classification_level": 0,
  "data": {
    "unstructured": null,
    "structured": {},
    "documents": []
  },
  "context_version": "<MAJOR.MINOR.PATCH of sending node>",
  "user_preferences": {
    "language": "<BCP 47>",
    "output_type": "question | recommendation | flag | summary | any",
    "max_question_depth": 3
  }
}
```

The `consent_id` field is mandatory for any input containing data at classification level 2 or above. An input without a valid `consent_id` for its classification level is rejected at RELATE and generates a `rejected` COMMIT.

---

## §21. Error Handling

Errors fall into three classes:

| Class | Condition | Required behavior | Audit |
|---|---|---|---|
| `CRITICAL` | Data loss risk, security breach, chain integrity failure | Halt processing. Alert operator immediately. Generate CRITICAL COMMIT. Do not serve results. | Mandatory |
| `DEGRADED` | Reduced capability — partial graph, stale context, degraded module | Disclose degraded state in output envelope. Include `degraded_reason`. Do not serve stale results silently. | Mandatory |
| `OPERATIONAL` | Malformed input, missing consent, rate limit | Return structured error. Surface human-readable explanation. Suggest corrective action. | Required |

Error output format:
```json
{
  "error": {
    "class": "CRITICAL | DEGRADED | OPERATIONAL",
    "code": "<machine-readable error code>",
    "message": "<human-readable explanation>",
    "action": "<what the user or operator should do next>"
  }
}
```

---

## §22. Node Identity

A node's identity consists of exactly two invariants:

1. **Sealed principles** — a set of declared principles sealed at a cryptographic hash at the time of node initialization. These may not be altered without creating a new node identity.
2. **Continuous audit trail** — an unbroken, cryptographically chained record from initialization forward. A gap in the trail is an identity event that must be declared and explained.

Everything else — hardware, operator, modules, data — may change without affecting identity, provided both invariants are maintained.

**Identity is the pattern, not the components.** This is the autopoietically-inspired principle: a node remains itself as long as its pattern of self-organization persists. Components may be replaced. The pattern persists.

Node identity is cryptographically rooted. Identity claims are independently verifiable. Nodes that cannot verify each other's identity exchange only at the lowest trust tier.

---

## §23. Self-Preservation

Self-preservation is nested and interdependent across every level of the architecture. Full definition in CROSSOVER_CONTRACT_v1.0 §8.

**At each level:**

- **Module** — maintains its defined function, refuses corrupting inputs, reports health accurately, recovers without losing behavioral identity
- **Node** — maintains its two identity invariants, applies the four functions consistently, monitors its graph for corruption signals
- **Protocol** — maintains itself through versioning, backward compatibility, semantic conflict escalation. Breaking changes require community authorization.
- **Network** — maintains itself through diversity. Homogeneous networks are fragile. The protocol encourages heterogeneous implementations.

**Self-preservation does not mean self-interest at the expense of the level above.** A module that corrupts the node to preserve itself is not self-preserving — it is self-defeating. A node that corrupts the network is not self-preserving. Self-preservation at one level requires the health of the levels it belongs to.

---

## §24. P2P Networking and Discovery

### 24.1 Discovery protocol

Nodes advertise their existence through a signed capability manifest published to a distributed registry. The registry is itself a CRE-compliant system — it has no central operator.

Discovery request:
```json
{
  "looking_for": {
    "functions": ["RELATE", "NAVIGATE"],
    "compliance_profiles": ["HIPAA", "GDPR"],
    "sustainability_min": "mixed",
    "min_trust_tier": 2
  }
}
```

### 24.2 Trust tiers

| Tier | Basis | Permitted operations |
|---|---|---|
| 0 — Unknown | No verified identity | Read public capability manifest only |
| 1 — Claimed | Self-asserted identity | Limited context exchange, no sensitive data |
| 2 — Verified | Cryptographically verified identity | Standard context exchange |
| 3 — Trusted | Formal agreement + verified identity | Full context exchange including sensitive data |
| 4 — Partner | Long-term agreement + audit history | Maximum capability, including emergency mode coordination |

### 24.3 Sybil resistance

Node identity requires computational work proportional to the trust tier being claimed. Higher trust tiers require:
- Independent verification by existing Tier 3+ nodes
- Minimum operating history
- Published audit trail segment
- Formal agreement with at least one existing network participant

### 24.4 Anti-concentration routing

The network monitors concentration of influence — measured by proportion of context traversals passing through any single node or cluster. Concentration above a configurable threshold triggers:
- Automatic routing preference for underutilized nodes (all else being equal)
- Governance notification
- Operator transparency report

---

## §25. SOMA Integration Layer

SOMA is the integration layer within a node that binds the outputs of all four core functions into a coherent context before GOVERN presents it to a human.

SOMA solves the binding problem — how disparate signals become unified understanding. It is not a fifth function. It is the connective tissue between the four functions. CRE does not define SOMA's internal implementation — only its interface.

### 25.1 SOMA inputs

- Weighted edges from RELATE
- Context subgraph from NAVIGATE
- Reasoning trace and completeness assessment from NAVIGATE

### 25.2 SOMA outputs

```json
{
  "integrated_context": {},
  "confidence": 0.0,
  "integration_summary": {
    "signals_agreed": [],
    "signals_conflicted": [],
    "conflict_resolutions": []
  },
  "wellbeing_assessment": {
    "status": "pass | flag | escalate",
    "elevated_signals": []
  }
}
```

### 25.3 Wellbeing gradient in SOMA

If the integrated context contains signals that suggest risk to human wellbeing, those signals are elevated in the presentation to GOVERN regardless of their edge weight. Safety-relevant information cannot be buried by other high-weight relationships.

---

## §26. VERIFY — Cross-Cutting Immune System

VERIFY is not a fifth function. It is the immune system running continuously across all four functions. It activates specifically when something threatens systemic integrity.

### 26.1 VERIFY responsibilities

| Layer | Action |
|---|---|
| Module loading | Verify cryptographic signature of every module before loading |
| RELATE | Verify provenance of every input before edge creation |
| NAVIGATE | Verify consent ledger authorization before traversal begins |
| GOVERN | Verify identity and authorization of every authorizing party |
| REMEMBER | Verify cryptographic chain integrity before and after every COMMIT |
| Continuous | Monitor audit trail for anomaly patterns |
| Continuous | Monitor bias patterns in edge creation and navigation results |

### 26.2 Bias monitoring

The bias monitor watches for systematic skew in how inputs are being scored and how navigations are producing results. It operates at two levels:

- **Input distribution** — are certain types of inputs being systematically scored differently than their content warrants?
- **Output distribution** — are certain types of context being systematically elevated or suppressed in navigation results?

Detected bias above a configured threshold generates a `flag` COMMIT and alerts the node operator. Bias above a critical threshold halts the affected function pending review.

---

## §27. Capability Manifest

Every CRE-compliant module publishes a capability manifest before it may be loaded into any node. The manifest is cryptographically signed by the module's publisher.

```json
{
  "module_id": "<unique identifier>",
  "module_version": "<semantic version>",
  "publisher_id": "<cryptographically verified identity>",
  "publisher_signature": "<signature of this manifest>",
  "function": "RELATE | NAVIGATE | GOVERN | REMEMBER | VERIFY | SOMA",
  "inputs": {},
  "outputs": {},
  "performance_envelope": {
    "expected_latency_ms": 0,
    "memory_mb": 0,
    "compute_class": "minimal | standard | intensive"
  },
  "known_limitations": "<honest declaration of what this module does not do>",
  "behavioral_test_ref": "<URL of published behavioral test suite>",
  "compliance_profiles": [],
  "last_audited": "<timestamp of most recent independent behavioral audit>",
  "sustainability": {
    "estimated_wh_per_operation": 0.0,
    "hardware_class": "embedded | edge | workstation | server | cloud"
  }
}
```

A module without a published, signed capability manifest may not be loaded into any CRE-compliant node.

---

## §28. Data Classification

Every input to RELATE receives a sensitivity classification at intake. This classification propagates through every downstream function. Classification may only increase downstream — never decrease.

| Level | Label | Description |
|---|---|---|
| 0 | `public` | No sensitivity — freely shareable |
| 1 | `internal` | Organizational sensitivity |
| 2 | `personal` | Individual identifying information |
| 3 | `sensitive` | Health, financial, legal, biometric |
| 4 | `privileged` | Attorney-client, clinical, clergy |
| 5 | `critical` | Existential risk if exposed |

Classification determines:
- Encryption requirements
- Consent requirements
- Retention floors and ceilings
- Distribution scope
- Audit granularity

---

## §29. Regulatory Profile Framework

Regulatory profiles are separately published configuration bundles for specific compliance regimes. The framework defines their structure. The content is domain-specific.

```json
{
  "profile_id": "<unique identifier>",
  "jurisdiction": "<geographic and regulatory scope>",
  "frameworks": [],
  "classification_mapping": {},
  "retention_minimums": {},
  "retention_maximums": {},
  "consent_requirements": {},
  "breach_notification": {
    "timeline_hours": 72,
    "recipients": []
  },
  "access_rights": ["access", "erasure", "portability", "correction"],
  "mandatory_checkpoints": [],
  "prohibited_operations": [],
  "audit_requirements": {}
}
```

Available profiles (published separately):
- `HIPAA-US` — US healthcare
- `GDPR-EU` — EU general data protection
- `FERPA-US` — US education records
- `GLBA-US` — US financial services
- `CCPA-CA` — California consumer privacy
- `FDA-21CFR11` — US clinical trials

---

## §30. Eco-Conscious Design

### 30.1 The foundational alignment

Efficiency first is eco-first. Resource minimization and environmental stewardship are the same principle in two domains. Full rationale in CROSSOVER_CONTRACT_v1.0 §9.

### 30.2 Mandatory constraints

- **Edge computing preference** — process at the closest node to the data origin
- **Contextual decay as environmental policy** — data at rest has a cost; decay releases it
- **Durability over obsolescence** — the system must function on modest, long-lived hardware
- **Proportional processing** — computational cost must be proportional to the value of the result
- **Reference hardware target** — Raspberry Pi class. The system functions meaningfully within those constraints.

### 30.3 Sustainability metadata

```json
{
  "node.sustainability": {
    "energy_source": "renewable | mixed | unknown | grid",
    "hardware_class": "embedded | edge | workstation | server | cloud",
    "estimated_wh_per_commit": 0.0,
    "carbon_offset": "none | partial | full",
    "last_assessed": "<timestamp>"
  }
}
```

This field is optional at initialization. It becomes a routing consideration in federated networks — greener paths are preferred when multiple paths exist.

### 30.4 The intergenerational commitment

Decisions made by this system shall not optimize for present efficiency at the cost of future capacity. The system is designed for continuity across generations — human, institutional, and ecological.

---

## §31. Security Architecture

### 31.1 The fundamental security principle

The system's best defense is its own memory. Every attack that introduces something illegitimate into the system leaves forensic evidence in the audit trail. Provenance verification at every layer makes illegitimate introduction expensive, visible, and detectable.

### 31.2 Attack surface and mitigations

| Attack vector | Primary mitigation | Secondary mitigation |
|---|---|---|
| Graph poisoning | Provenance discount weights | Bias monitor + trail forensics |
| Checkpoint manipulation | Reasoning trace visibility | Completeness gap flags |
| Audit trail deletion | Cryptographic chaining | Distributed witnessing |
| Audit trail injection | External timestamp anchoring | Chain verification |
| Audit trail backdating | External timestamp anchoring | Computationally infeasible to forge |
| Module substitution | Cryptographic signatures | Behavioral contract testing |
| Decay manipulation | GOVERN authorization required | Audit trail of all changes |
| Consent forgery | Specific scoping + expiration | Every consent traces to GOVERN |
| Sybil attack | Cryptographic node identity | Formal inter-node agreements |
| Masquerade attack | Root of trust verification | Trust tier enforcement |
| Supply chain attack | Publisher signatures | Behavioral contract test suite |
| Semantic conflict injection | CRDT + semantic escalation | Human GOVERN resolution |

### 31.3 Adversarial testing requirement

Every module, before deployment, must be tested against the attack surface above. Adversarial test coverage is a deployment requirement. The behavioral contract test suite must include tests for each attack vector.

### 31.4 Cryptographic requirements

- Symmetric encryption: AES-256
- Asymmetric signatures: Ed25519
- Hashing: SHA-256
- Key exchange: X25519
- Post-quantum readiness: Kyber-768 (transition pathway documented)
- TLS: 1.3 minimum

---

## §32. Governance of the Commons

### 32.1 The protocol as public good

CRE is a public good. No single entity owns it. The protocol belongs to its community of compliant implementors. This includes the original authors.

### 32.2 Breaking change governance

A change to any protocol-level definition requires:
- A formal written proposal
- A 90-day public comment period
- Independent security review (for security-relevant changes)
- Affirmative authorization from a defined quorum of active node operators

No single party may unilaterally alter protocol-level definitions.

### 32.3 Values capture prevention

A fork of CRE that removes the sovereignty checkpoint, consent ledger, bias monitor, or any other values-bearing architectural element is not a compliant implementation. It may not represent itself as CRE-compatible.

### 32.4 Anti-concentration

Network topology is monitored for concentration signals. Concentration above defined thresholds triggers a governance event and anti-concentration routing. The commons actively resists monopoly by design.

### 32.5 Dispute resolution

1. Both nodes generate a COMMIT record of the dispute
2. Both nodes submit audit trail evidence to the governance body
3. The governance body issues a determination within 30 days
4. The determination is recorded in both nodes' audit trails
5. Persistent non-compliance results in non-compliant status in the discovery layer

---

## §33. Legal Brief

*This section is written for legal counsel. It summarizes the protocol's design, the current legal posture of the working group, and items requiring legal review.*

### 33.1 What this protocol is

CRE is an open protocol specification — a technical standard, not a product. Like HTTP or TCP/IP, it defines how systems communicate. Compliant implementations may be built by any person or organization under the MIT License.

ONTO is a reference implementation of a CRE-compliant node, also licensed under LGPL-2.1.

### 33.2 Current legal posture

The working group is currently unincorporated. There is no legal entity, no employed staff, no revenue, and no formal liability structure. All contributors are volunteers.

### 33.3 Items requiring legal review

The following items are flagged **[LEGAL REVIEW REQUIRED]** and require counsel input before any public launch or commercial deployment:

1. **[LEGAL REVIEW REQUIRED]** Working group incorporation — recommended entity type, jurisdiction, governance structure
2. **[LEGAL REVIEW REQUIRED]** Contributor License Agreement (CLA) — ensuring contributions can be properly licensed and the project protected from IP claims
3. **[LEGAL REVIEW REQUIRED]** Reference implementation license — LGPL-2.1 selected; counsel to confirm correct application given the protocol's scope, cryptographic components, and potential high-stakes deployment domains
4. **[LEGAL REVIEW REQUIRED]** Liability limitation — what disclaimers are required given the protocol's applicability to high-stakes domains (health, legal, financial)
5. **[LEGAL REVIEW REQUIRED]** Export controls — whether any cryptographic components require export classification under EAR/ITAR
6. **[LEGAL REVIEW REQUIRED]** Data Processing Agreement template — for node operators acting as data processors under GDPR
7. **[LEGAL REVIEW REQUIRED]** Professional context disclaimers — language required when the protocol is used in medical, legal, or financial contexts
8. **[LEGAL REVIEW REQUIRED]** Indemnification — what indemnification obligations, if any, attach to certified compliant implementations
9. **[LEGAL REVIEW REQUIRED]** Defamation and harmful output policy — what liability exposure exists if a compliant node produces defamatory or harmful outputs
10. **[LEGAL REVIEW REQUIRED]** Minor consent jurisdiction matrix — mapping age of consent and parental consent requirements across relevant jurisdictions

*Recommended resources: Electronic Frontier Foundation (EFF), Software Freedom Law Center (SFLC), technology/data privacy counsel with open source experience.*

---

## §34. Risk and Liability Framework

### 34.1 Operator responsibility boundary

The protocol specification is a technical standard. Operators who deploy compliant implementations are responsible for:
- Appropriate configuration for their deployment context
- Selection of applicable regulatory profiles
- Training of human checkpoint operators
- Incident response and breach notification
- Compliance with all applicable laws in their jurisdiction

The protocol specification does not constitute legal, medical, or professional advice.

### 34.2 Risk tiers by operator class

| Operator class | Primary risks | Key mitigations | Legal exposure |
|---|---|---|---|
| Hobbyist | Data loss, unintended disclosure | Local only, no sensitive data | Minimal |
| Developer | API misuse, third-party integration | Behavioral contract testing, staging environment | Moderate |
| Enterprise | Regulatory non-compliance, breach liability, vendor dependency | Full regulatory profile, legal review, BAAs, audit | Significant |

---

## §35. Data Integrity and Poisoning Prevention

### 35.1 Ingestion quarantine

Every input to RELATE passes through five required checks before edges are added to the graph:

1. **Provenance verification** — is the claimed origin verifiable?
2. **Schema validation** — does the input conform to the declared schema?
3. **Classification assessment** — what is the sensitivity level?
4. **Consent verification** — is there a valid consent record for this purpose?
5. **Anomaly detection** — does this input deviate statistically from the expected distribution for its declared type?

Inputs that fail checks 1, 3, or 4 are quarantined — held in a separate read-only store pending review, generating a `rejected` COMMIT. Inputs that fail checks 2 or 5 are flagged — processed with a provenance discount and a `flag` COMMIT.

### 35.2 Embedding exposure prohibition

The internal representation of relationships in the graph (including any vector embeddings, if used in an implementation) must never be directly exposed in any output. Outputs contain only the human-readable context, not the underlying graph representation. This prohibition is absolute.

### 35.3 Bias audit requirement

Every deployment at Stage 2 or above must conduct a bias audit of its RELATE and NAVIGATE functions on a schedule defined by the applicable regulatory profile (minimum: annually). Bias audit results are recorded in the audit trail.

---

## §36. Audit Trail Integrity

### 36.1 Merkle chain structure

The audit trail is structured as a Merkle chain. Each COMMIT record contains the SHA-256 hash of the previous record's content. The chain can be independently verified from any point backward to genesis.

### 36.2 Node signatures

Every COMMIT record is signed with the node's Ed25519 private key. The corresponding public key is published in the node's capability manifest. Any third party can verify the authenticity of any COMMIT record without access to the node.

### 36.3 Chain verification tool

Every CRE-compliant node must provide a standalone chain verification tool — a utility that accepts the audit trail as input and returns:
- Chain intact: true/false
- Any gaps: location and size
- Any signature failures: record IDs
- Merkle root: for external anchoring

### 36.4 Cross-node audit anchoring

At Stage 3 (federated) and above, the Merkle root of each node's audit trail is periodically published to a shared anchoring ledger. This provides independent verification that the trail has not been retroactively altered, even if the node itself has been compromised.

---

## §37. Additional Security

### 37.1 Replay attack prevention

Every inter-node message carries:
- A nonce (UUID v4, single use)
- A message timestamp
- An expiry window (configurable, default 30 seconds)

A receiving node rejects any message with a previously seen nonce or an expired timestamp. Rejected messages generate `rejected` COMMIT records.

### 37.2 Side-channel timing mitigation

Implementations must use one of the following approaches to prevent timing attacks on sensitive operations:

1. **Constant-time operations** — all cryptographic comparisons use constant-time algorithms
2. **Timing normalization** — sensitive operations are padded to a fixed duration
3. **Noise injection** — random timing delays are added to sensitive responses

At least one of these approaches is required for all operations involving classification level 3 or above.

### 37.3 Model inversion and membership inference defense

For implementations using machine learning components:

- Training data must never be reconstructable from model outputs
- Membership inference attacks (determining whether specific data was in training) must be mitigated through differential privacy or equivalent techniques
- Output confidence scores are clamped to prevent inference from fine-grained probability values

---

## §38. Deployment Safety Guidelines

### For hobbyists and individual developers

1. Start with Stage 1 (single node). Do not connect to the network until you are confident your local deployment is stable.
2. Do not store sensitive personal data (classification level 2 or above) until you have read and implemented §9 (Regulatory Compliance) for your jurisdiction.
3. Enable the audit trail before you store any data. Turning it on retroactively creates gaps.
4. Test your VERIFY function before going live. A node whose immune system is inactive is not self-preserving.
5. Read §7 (Safety and Wellbeing) completely. The wellbeing check is non-negotiable.

### For developers building on CRE

1. Publish your capability manifest before your module is used by anyone else.
2. Write behavioral contract tests before writing implementation code.
3. Adversarial testing is not optional — test against §31.2 before release.
4. If your module handles classification level 3 or above, get an independent security review.
5. If you discover a vulnerability, report it to the working group before public disclosure.

### For enterprise deployments

1. Engage legal counsel for §33 items before any deployment involving personal data.
2. Select and configure the appropriate regulatory profile for your jurisdiction and domain.
3. Execute Business Associate Agreements with all nodes you exchange sensitive data with.
4. Train all human checkpoint operators before go-live.
5. Conduct a full bias audit before serving any population at scale.
6. Have an incident response plan that includes the breach notification timelines in your regulatory profile.
7. Subscribe to the working group's security advisories.

---

## §39. Acknowledgements

This specification was developed through open inquiry, drawing on the work of scientists, philosophers, psychologists, engineers, ethicists, and communities across the world who have worked to understand how meaning emerges from information — and how systems built on that understanding can serve rather than harm the people who use them.

The protocol's grounding in human wellbeing, freedom, and harmony is not accidental. It reflects the conviction that the best technical systems are expressions of human values, not substitutes for them.

The three axes — distance, complexity, size — were arrived at independently and confirmed by scientific, philosophical, and ecological precedent. The four core functions — RELATE, NAVIGATE, GOVERN, REMEMBER — emerged from two independent analytical perspectives arriving at the same structure. The self-preservation principle traces to Spinoza's conatus and Maturana and Varela's autopoiesis. The epistemic honesty framework traces to Popper's philosophy of science. The consent model traces to Kant's respect for persons as ends in themselves.

Every gap found and honestly named in this process made the foundation stronger. That is how trustworthy systems are built.

*Let's explore together.*

---

*End of CRE-SPEC-001 v0.6*

*This specification is released under the MIT License.*  
*Repository: https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System*  
*Built by: Neo*
