# ONTO × CRE Crossover Contract
**Document ID:** CROSSOVER-CONTRACT-001  
**Version:** 1.0  
**Status:** Draft — Pending Review  
**Authors:** Neo (bnyhil31-afk), Claude (Anthropic)  
**License:** MIT  
**Related documents:**  
- ONTO MVP: https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System  
- ONTO Principles Hash: `b1d3054f646c5f3abaffd3a275683949aef426d135cf823e7b3665fb06a03ba5`  
- CRE Specification: CRE-SPEC-001 v0.5  

---

## Preamble

This document is the foundational contract between two interconnected projects:

**ONTO** — a self-preserving, node-level system for building contextual meaning around data, modeled on the architecture of consciousness.

**CRE (Contextual Reasoning Engine)** — the protocol that governs how ONTO nodes and any compliant system communicate, federate, and maintain collective integrity across any scale.

ONTO is the organism. CRE is the protocol by which organisms recognize each other, exchange meaning, and form ecosystems. Neither project is subordinate to the other. Each is complete without the other. Together they are more than either alone.

This contract defines exactly what is shared between them — the decisions made once that both projects implement. Anything defined here may not be contradicted by either project's implementation. Anything not defined here belongs to the implementing project's domain and is theirs to govern.

Every decision in this document was made against a two-sided test:

> **Brain test:** Does this preserve contextual flow and accumulated awareness?  
> **Machine test:** Is this interface clean enough that a stranger could swap this component without reading its internals?

Both tests must pass. Neither is optional.

---

## Part I: Foundational Definitions

### 1.1 What a Context Is

This definition is the load-bearing foundation of everything else. All other definitions depend on it.

> **A context is a bounded subgraph of a relationship graph, selected by relevance to a declared purpose at a specific moment in time, carrying the provenance of every relationship it contains.**

Unpacked:

- **Bounded** — a context has edges. It is not everything. It is the portion of the total relationship graph that is relevant to the present moment and declared purpose.
- **Subgraph** — a context is not a list of data points. It is a structure of relationships between data points. The relationships are primary. The data points are meaningful only through their connections.
- **Selected by relevance** — relevance is computed by the three axes (defined in Part II). Context is not retrieved; it is constructed by traversal.
- **Declared purpose** — no context may be constructed without a stated reason. The purpose shapes the traversal and bounds what is included. This is the minimum necessary principle encoded into the definition itself.
- **Specific moment in time** — a context is always present-tense. It reflects the state of the relationship graph at the moment of construction. It does not project forward. It does not predict.
- **Provenance of every relationship** — every edge in the context carries its origin: who established it, when, under what authorization. A relationship without provenance is not a valid member of any context.

**What a context is not:**

- A context is not a query result
- A context is not a prediction or forecast
- A context is not a static snapshot — it reflects the graph as it exists at the moment of construction, including all decay that has occurred up to that moment
- A context is not a complete picture — it is always partial, and that partiality must be visible to the human at the governance layer

---

### 1.2 The Node

> **A node is a self-preserving instance of ONTO or any CRE-compliant system, capable of independent operation, carrying a declared identity, and able to participate in the CRE network by choice.**

A node is a complete organism. It does not require network participation to be valid. Network participation is symbiotic, not constitutive. A node that withdraws from the network does not cease to be a node. A network does not cease to be a network when a node withdraws.

**Node identity** consists of exactly two invariants:

1. A set of declared principles, sealed at a cryptographic hash at the time of node initialization. These principles may not be altered without creating a new node identity.
2. A continuous, unbroken audit trail from the moment of initialization forward. A gap in the trail is an identity event — the node must declare and explain it.

Everything else about a node — its hardware, its operator, its modules, its data — may change without affecting its identity, provided the two invariants are maintained.

---

### 1.3 The Relationship Graph

> **The relationship graph is the primary data structure of any ONTO node. It is a directed, weighted graph where nodes are data entities and edges are relationships between them. Every edge carries a weight derived from the three axes, a timestamp, and a provenance signature.**

The graph is never complete. It is always growing, always decaying, always being traversed. Its value is not in any static state but in its continuous evolution.

**Graph invariants:**

- No edge may exist without a provenance signature
- No edge weight may be modified except through the decay function or an authorized re-evaluation with a COMMIT record
- The graph's history — every edge ever added, every weight ever changed, every decay event — is recorded in the audit trail
- The graph may grow without bound but must decay actively — unbounded growth without decay is a self-preservation failure

---

## Part II: The Three Axes

The three axes are the universal weighting function of the relationship graph. They apply to every edge, in every domain, at every scale. They are not metaphors — they are computable properties.

### 2.1 Distance

> **Distance is the measure of how far a relationship is from the current context of relevance — spatially, temporally, semantically, or relationally.**

Distance is multidimensional. Any combination of the following components may apply:

| Component | Definition | Direction |
|---|---|---|
| Temporal | How long ago was this relationship established or last confirmed? | Past only — distance increases backward in time, not forward |
| Semantic | How conceptually similar is this relationship to the declared purpose? | Lower similarity = higher distance |
| Relational | How many hops in the graph separate this relationship from the current context root? | More hops = higher distance |
| Provenance | How many intermediaries exist between this relationship's origin and a verified source? | More intermediaries = higher distance |

**High distance = lower edge weight.** The decay function operates primarily on the temporal component of distance.

**Critical constraint:** Distance has no forward temporal dimension. The system does not measure distance to future states. Distance is always measured from the present moment backward and outward — never forward.

---

### 2.2 Complexity

> **Complexity is the measure of the density and diversity of relationships surrounding a data entity or a relationship itself.**

High complexity means a data entity participates in many relationships of many types. Low complexity means a data entity participates in few relationships or relationships of a single type.

Complexity affects the system in two ways:

1. **Processing cost** — high-complexity entities require more traversal to fully contextualize. The system must be aware of this cost and manage it against available resources.
2. **Inference richness** — high-complexity entities carry more contextual signal. A data point with many diverse relationships is more informative than an isolated one.

**Complexity is not inherently good or bad.** It is a property to be measured and responded to appropriately.

---

### 2.3 Size

> **Size is the measure of the scope of impact of a data entity or relationship — how many other entities it affects, how many relationships it participates in, and the magnitude of its influence on graph topology.**

Size operates at two levels:

1. **Local size** — the immediate scope of a data entity within its neighborhood of the graph
2. **Network size** — the scope of a data entity's influence across the federated network of nodes

**Size as an environmental metric:** In the context of eco-conscious design, size maps directly to computational cost. Large entities with high network size require more resources to process, store, and transmit. The system treats size as a signal to optimize against — not to suppress large data, but to ensure that processing cost is proportional to value.

---

### 2.4 Axes as Edge Weights

The three axes combine into a single edge weight through a function that each node may configure within defined bounds:

```
weight(edge) = f(distance, complexity, size)

where:
  - distance contributes negatively (high distance = lower weight)
  - complexity contributes positively (high complexity = higher signal value)
  - size contributes according to deployment policy (may be positive or negative 
    depending on whether the deployment optimizes for richness or efficiency)
  - f() is configurable per node but must be monotonic in each axis
  - weight ∈ [0.0, 1.0]
  - weight = 0.0 means the edge is scheduled for decay
  - weight = 1.0 means maximum relevance
```

The specific function `f()` is a node-level configuration. The axis definitions and the weight range are protocol-level constants. Any compliant node may tune the function; no compliant node may redefine the axes.

---

## Part III: The Four Core Functions

Every operation in ONTO and every protocol verb in CRE maps to one of four core functions. These functions are the universal interface layer — the machine side of the brain-machine duality.

### 3.1 RELATE

> **RELATE is the function of ingesting an input, verifying its provenance, establishing its relationships to existing context, and adding weighted edges to the relationship graph.**

RELATE is the entry point of all data into the system. Nothing enters the graph without passing through RELATE.

**Mandatory steps in sequence:**

1. Receive input with declared origin
2. Verify provenance signature — if unverifiable, apply provenance discount weight (not rejection)
3. Apply sensitivity classification (see Part V)
4. Compute initial edge weights using three axes
5. Check bias monitor thresholds — flag if systematic skew detected
6. Add weighted, signed, classified edges to graph
7. Generate RELATE event for audit trail

**What RELATE does not do:**

- RELATE does not evaluate the truth or accuracy of an input — it records what was received and where it came from
- RELATE does not generate synthetic inputs — every edge traces to an external input
- RELATE does not predict — it records the present state of what has been received

**CRE protocol verb:** `INGEST`  
**ONTO module:** `intake` + `contextualize` (combined — RELATE spans both)

---

### 3.2 NAVIGATE

> **NAVIGATE is the function of traversing the relationship graph, given a declared purpose, to construct a relevant context subgraph — including explicit markers for what was excluded and why.**

NAVIGATE is the intelligence of the system. It is where the three axes do their most important work.

**Mandatory steps in sequence:**

1. Receive purpose declaration
2. Verify purpose against consent ledger — confirm authorization exists for this purpose against this data
3. Traverse graph from declared root, following highest-weight edges relevant to purpose
4. Construct context subgraph
5. Identify excluded relationships — edges that exist but fall outside the traversal criteria
6. Generate completeness assessment — what is uncertain, what is missing, what was excluded and why
7. Return subgraph WITH reasoning trace and completeness assessment — never subgraph alone

**Critical requirement:** NAVIGATE must never present a context as complete. Every navigated context carries explicit uncertainty markers. A system that presents complete-seeming answers without visible uncertainty is a non-compliant implementation.

**The Socratic constraint:** The output of NAVIGATE is not an answer. It is an examined set of candidates with visible reasoning. The human at the governance layer receives the candidates, the reasoning, and the uncertainty — not a conclusion.

**CRE protocol verb:** `CONTEXTUALIZE` + `SURFACE`  
**ONTO module:** `contextualize` + `surface`

---

### 3.3 GOVERN

> **GOVERN is the function of presenting a navigated context to an authorized human at a consequential moment, receiving their decision, and recording that decision with full provenance.**

GOVERN is the human sovereignty layer. It is where the machine defers to the person.

**Mandatory steps in sequence:**

1. Receive context subgraph + reasoning trace + completeness assessment from NAVIGATE
2. Assess consequence threshold — is this decision above the configured threshold for single or multi-party authorization?
3. Present to authorized human(s) — subgraph, reasoning, uncertainty, and excluded relationships all visible
4. Receive decision — affirmative, veto, or deferred
5. Record decision with: authorizing party identity, timestamp, context hash, decision type, stated reason if veto
6. Generate GOVERN event for audit trail regardless of decision type
7. Pass authorized decision to REMEMBER

**The veto is a first-class output.** A veto is not a failure state. It is the system functioning correctly — a human exercising sovereignty. The veto record is the most valuable record the system can produce in many deployments.

**Emergency mode:** In declared emergency conditions, consequence thresholds may be temporarily adjusted by authorized protocol. Emergency mode activation and deactivation are themselves GOVERN events. Emergency mode has a maximum duration defined at deployment configuration and cannot be extended without a new authorization event.

**CRE protocol verb:** `CHECKPOINT`  
**ONTO module:** `checkpoint`

---

### 3.4 REMEMBER

> **REMEMBER is the function of committing the full record of what happened — what was related, what was navigated, what was decided — to the append-only audit trail with cryptographic integrity.**

REMEMBER is the immune memory of the system. It is where everything becomes permanent.

**Every loop pass produces a COMMIT. Without exception.**

COMMIT types:

| Type | Condition | Record weight | Required fields |
|---|---|---|---|
| `complete` | Full pass, affirmative decision | Full | All fields |
| `vetoed` | GOVERN returned veto | Full | All fields + veto reason |
| `partial` | Navigation produced empty or below-threshold context | Lightweight | Core fields only |
| `rejected` | Input failed provenance verification at minimum threshold | Minimal | Origin, timestamp, rejection reason |
| `deduplicated` | Identical input within deduplication window | Increment only | Reference to original COMMIT + repeat_count |
| `emergency` | Any COMMIT during declared emergency mode | Full + flag | All fields + emergency authorization reference |

**Cryptographic integrity requirements:**

- Every COMMIT record is chained to the previous record via hash of the previous record's content
- The chain must be unbroken — a gap is detectable and constitutes an identity event requiring declaration
- External timestamp anchoring from an independent source is required for all COMMIT types except `deduplicated`
- For deployments above a configured sensitivity threshold, COMMIT records are distributed to witness nodes simultaneously

**Read logging:** Every read of a sensitive record (classification level defined at deployment) generates a READ_ACCESS event in the audit trail. Reads are as visible as writes.

**Decay as governed parameter:** The decay function operates on edge weights in the relationship graph. Decay rate parameters may only be modified through a GOVERN event — never unilaterally by any module. Every decay parameter change generates a COMMIT record.

**CRE protocol verb:** `COMMIT`  
**ONTO module:** `memory`

---

## Part IV: The SOMA Integration Layer

### 4.1 Definition

> **SOMA is the integration layer within a node that binds the outputs of all four core functions into a coherent context before GOVERN presents it to a human. SOMA is the binding solution — the answer to how disparate signals become unified understanding.**

SOMA is not a fifth function. It is the connective tissue between the four functions. It exists inside the node, invisible to the protocol. CRE does not define SOMA's implementation — only its interface.

### 4.2 SOMA's role

The binding problem — how a collection of processed signals becomes a unified context — is solved by SOMA. It receives:

- The weighted edges produced by RELATE
- The context subgraph produced by NAVIGATE
- The reasoning trace and completeness assessment from NAVIGATE

And produces:

- A coherent, integrated context package ready for GOVERN
- A confidence score for the integrated context as a whole
- A summary of the integration — what signals agreed, what signals conflicted, how conflicts were resolved

### 4.3 The wellbeing gradient in SOMA

Human wellbeing is the highest priority of the system. This priority is not implemented as a filter at GOVERN alone — it is a thread that runs through SOMA at every integration step.

SOMA applies a wellbeing assessment to every context package it produces. If the integrated context contains signals that suggest risk to human wellbeing — physical, psychological, social, or environmental — those signals are elevated in the presentation to GOVERN regardless of their edge weight in the relationship graph.

The wellbeing gradient is a signal amplifier for human safety, not a content filter. It does not suppress information. It ensures that safety-relevant information cannot be buried by other high-weight relationships.

---

## Part V: Data Classification

### 5.1 Classification at intake

Every input to RELATE receives a sensitivity classification at the moment of ingestion. This classification propagates through every downstream function and governs what operations are permitted on the data.

Classification is applied at intake and may not be reduced downstream — it may only be maintained or elevated by subsequent functions that discover additional sensitivity.

### 5.2 Classification levels

| Level | Label | Description | Examples |
|---|---|---|---|
| 0 | `public` | No sensitivity — freely shareable | Published research, public records |
| 1 | `internal` | Organizational sensitivity | Business operations, internal communications |
| 2 | `personal` | Individual identifying information | Names, contact information, behavioral data |
| 3 | `sensitive` | Special category personal data | Health, financial, legal, biometric |
| 4 | `privileged` | Legally protected | Attorney-client, clinical, clergy |
| 5 | `critical` | Highest protection — existential risk if exposed | Crisis data, witness protection, active investigation |

### 5.3 Classification and the three axes

Classification interacts with the three axes to constrain operations:

- **Distance:** Higher classification levels have minimum retention floors — data may not decay below a minimum weight regardless of temporal distance. Level 3+ data has regulatory-defined retention minimums.
- **Complexity:** Higher classification levels require more granular provenance — more complex records require more complete authorization chains.
- **Size:** Higher classification levels have maximum network size constraints — the scope of distribution is bounded by the sensitivity of the data.

### 5.4 The cryptographic erasure layer

All data at classification level 2 and above is stored in a two-layer structure:

```
COMMIT record
├── shell (immutable, permanent)
│   ├── record_id
│   ├── timestamp (externally anchored)
│   ├── commit_type
│   ├── classification_level
│   ├── schema_version
│   ├── module_version
│   ├── chain_hash (hash of previous record)
│   ├── data_reference (pointer to payload — not payload itself)
│   └── provenance_signature
└── payload (encrypted, erasable)
    ├── actual content
    ├── relationship edges
    └── encrypted with subject's key
```

The shell contains no personal identifying information — not names, not dates below year granularity, not geographic data below state/region level, not device identifiers. The shell is designed so that it cannot accidentally constitute sensitive data under any regulatory framework.

Erasure is executed by destroying the encryption key. The shell persists — the audit trail records that something happened. The payload becomes permanently unreadable. The right to erasure is honored. The audit integrity is maintained.

---

## Part VI: The Consent Ledger

### 6.1 Definition

> **The consent ledger is the authoritative record of who has permission to do what with which data, under what conditions, for what duration.**

The consent ledger is not a log of past consents. It is a live governance instrument — it is queried by NAVIGATE before every traversal to confirm that the declared purpose is authorized.

### 6.2 Consent record schema

Every consent grant contains exactly:

```
consent_record:
  grant_id:           unique identifier
  subject_id:         whose data this governs
  grantee_id:         who receives permission
  scope:              what data classification levels are covered
  purpose:            declared purpose — specific, not general
  operations:         permitted operations (read, relate, navigate, export)
  granted_at:         timestamp (externally anchored)
  expires_at:         mandatory expiration — no perpetual grants
  granted_by:         identity of authorizing party
  authorization_ref:  reference to GOVERN event that authorized this grant
  revocation_status:  active | revoked | expired
  revoked_at:         if revoked, timestamp
  revoked_reason:     if revoked, stated reason
```

### 6.3 Consent principles

- **No implicit consent.** Every consent is explicit, specific, and recorded.
- **No perpetual consent.** Every consent has a mandatory expiration. Renewal requires a new GOVERN event.
- **No broader than necessary.** The scope and purpose of every consent must be the minimum required for the stated function.
- **Revocation is immediate.** A revoked consent takes effect at the moment of revocation. Any in-progress operation authorized by a revoked consent must halt and generate a COMMIT record of the interruption.
- **Consent is symbiotic.** A grantee who violates the terms of a consent grant has the grant revoked and the violation recorded permanently in the audit trail.

---

## Part VII: Security Architecture

### 7.1 The fundamental security principle

> **The system's best defense is its own memory. Every attack that introduces something illegitimate into the system leaves forensic evidence in the audit trail. Provenance verification at every layer makes illegitimate introduction expensive, visible, and detectable.**

Security is not a layer applied on top of the architecture. It is a property of the architecture itself. The four functions — RELATE, NAVIGATE, GOVERN, REMEMBER — are each simultaneously processing functions and security primitives.

### 7.2 VERIFY — the cross-cutting immune system

VERIFY is not a fifth function. It is the immune system — always running across all four functions, activating specifically when something threatens systemic integrity.

**VERIFY responsibilities:**

| Layer | VERIFY action |
|---|---|
| Module loading | Verify cryptographic signature of every module before loading — unsigned modules cannot load |
| RELATE | Verify provenance of every input before edge creation |
| NAVIGATE | Verify consent ledger authorization before traversal begins |
| GOVERN | Verify identity and authorization of every authorizing party |
| REMEMBER | Verify cryptographic chain integrity before and after every COMMIT |
| Continuous | Monitor audit trail for anomaly patterns indicating coordinated attack |
| Continuous | Monitor bias patterns in edge creation and navigation results |

### 7.3 Attack surface mitigation

**Graph poisoning** — mitigated by provenance discount weights, bias monitor, and forensic trail pattern analysis. Coordinated gradual distortion is detectable as a statistical anomaly in the trail.

**Checkpoint manipulation** — mitigated by mandatory completeness assessment and reasoning trace visibility. The checkpoint never presents conclusions without visible reasoning. What was excluded is as visible as what was included.

**Audit trail attacks** — mitigated by cryptographic chaining (deletion creates visible gaps), external timestamp anchoring (backdating is computationally infeasible), and distributed witnessing for sensitive deployments (alteration requires compromising multiple independent systems simultaneously).

**Module substitution** — mitigated by cryptographic module signatures, behavioral contract testing, and — for consequential deployments — multi-party authorization for module loading. No single operator can load an unverified module.

**Decay manipulation** — mitigated by requiring GOVERN authorization for any decay parameter modification. Decay function is deterministic and transparent — its output is always auditable.

**Consent forgery** — mitigated by specific scoping, mandatory expiration, and the requirement that every consent traces to a GOVERN event. Social engineering attacks on consent are mitigated by adversarially designed consent presentation — clarity and completeness are non-negotiable.

**Sybil and masquerade attacks** — mitigated by cryptographically rooted node identity. Node identity claims must be independently verifiable. Formal agreements between nodes (equivalent to Business Associate Agreements in HIPAA contexts) establish and verify identity before any data exchange.

**Supply chain attacks** — every module carries a cryptographic signature from its publisher. Signature verification is mandatory. Behavioral contract testing verifies not just that a module accepts correct inputs but that it produces semantically correct outputs — and nothing else.

### 7.4 Adversarial testing requirement

Every module, before deployment in any production context, must be tested against the attack surface inventory above. Adversarial test coverage is a deployment requirement, not a recommendation. The behavioral contract test suite must include:

- Provenance bypass attempts
- Consent scope expansion attempts
- Decay rate manipulation attempts
- Chain integrity violation attempts
- Bias injection attempts

A module that passes interface compliance but fails adversarial testing is not a compliant module.

---

## Part VIII: Self-Preservation

### 8.1 The principle

> **Every component, at every scale, strives to maintain its own integrity, its own identity, and its own continuity — not at the expense of the level it belongs to, but in support of it.**

Self-preservation is nested and interdependent. A module that preserves itself at the expense of the node is behaving like cancer. A node that preserves itself at the expense of the network is behaving like a pathogen. Self-preservation at one level requires the health of the levels above and below it.

### 8.2 Self-preservation at each level

**Module level:** A module maintains the integrity of its defined function. It refuses inputs that would corrupt its operation. It reports its own health accurately. It recovers from failure without losing its behavioral identity — its core function is preserved even when its state is reset.

**Node level:** A node maintains its two identity invariants — sealed principles and continuous audit trail. It applies the four functions consistently. It monitors its own graph for signs of corruption. It can operate in complete isolation without degradation of core function.

**Protocol level:** The CRE protocol maintains itself through versioning, backward compatibility, and semantic conflict escalation. A breaking change requires community governance authorization. The protocol's core verbs may not be redefined by any single implementation.

**Network level:** The network maintains itself through diversity. Homogeneous networks are fragile. The protocol encourages heterogeneous node implementations — different internal architectures, different hardware, different operators — because diversity is resilience.

### 8.3 Identity over time

A node remains itself as long as its two identity invariants are maintained — sealed principles and unbroken audit trail. Components may be replaced. Hardware may change. Operators may change. The node persists as the same identity provided the pattern that defines it persists.

This is the autopoietic principle: identity is located in the pattern of self-organization, not in the specific components that instantiate it at any moment.

---

## Part IX: Eco-Conscious Design

### 9.1 The foundational alignment

> **Efficiency first is eco-first. Resource minimization and environmental stewardship are the same principle expressed in two domains.**

Every byte not stored, every computation not run, every network hop eliminated is energy not consumed. The eco-conscious commitments of this system are not aspirational statements — they are architectural properties with measurable implications.

### 9.2 Mandatory eco-conscious constraints

**Edge computing preference:** Processing happens at the node closest to the data origin. Round-trips to remote infrastructure are avoided unless the declared purpose specifically requires them. The Raspberry Pi class of device is the reference hardware target — the system must function meaningfully within those constraints.

**Contextual decay as environmental policy:** Data has a cost at rest. Every record stored consumes energy. Decay is not just a relevance mechanism — it is the system's metabolic process, releasing what is no longer needed and returning those resources to availability.

**Durability over obsolescence:** The system is designed to run on modest, long-lived hardware. Design patterns that require ever-increasing compute to maintain basic function are non-compliant with this principle.

**Proportional processing:** The computational cost of any operation must be proportional to the value of the result. A high-cost traversal of a large graph for a low-value purpose violates this principle. The NAVIGATE function must be aware of its own computational cost and surface that cost in its output.

### 9.3 Sustainability metadata

Every node carries an optional but strongly encouraged sustainability declaration:

```
node.sustainability:
  energy_source:      renewable | mixed | unknown | grid
  hardware_class:     embedded | edge | workstation | server | cloud
  estimated_wh_per_commit:  (measured or estimated)
  carbon_offset:      none | partial | full
  last_assessed:      timestamp
```

This field is optional at node initialization. It becomes a routing consideration in federated networks — when multiple paths exist, paths through greener nodes are preferred, all else being equal.

### 9.4 The intergenerational commitment

> **Decisions made by this system shall not optimize for present efficiency at the cost of future capacity. The system is designed for continuity across generations — human, institutional, and ecological.**

This commitment is not enforced by code. It is enforced by governance — by the humans who operate checkpoints, who govern decay parameters, who authorize protocol changes. It is included here because it must be named to be honored.

---

## Part X: Governance of the Commons

### 10.1 The governance gap addressed

A protocol without governance is vulnerable to fragmentation and capture. This section defines the minimum governance structure required for CRE to function as a commons rather than a product.

### 10.2 Principles of commons governance

**The protocol is a public good.** No single entity — including the original authors — owns CRE. The protocol belongs to its community of compliant implementors.

**Breaking changes require community authorization.** A change to any protocol-level definition in this document requires a formal proposal, a comment period, and affirmative authorization from a defined quorum of active node operators. No single party may unilaterally alter protocol-level definitions.

**Values capture is an existential threat.** A fork of CRE that removes the sovereignty checkpoint, the consent ledger, the bias monitor, or any other values-bearing architectural element is not a compliant implementation and may not represent itself as CRE-compatible.

**Anti-concentration is a protocol responsibility.** The protocol includes routing rules that resist the accumulation of disproportionate influence by any single node or cluster of nodes. Network topology is monitored for concentration signals. Concentration above defined thresholds triggers a governance event.

### 10.3 Dispute resolution

When two nodes disagree about protocol compliance:

1. Both nodes generate a COMMIT record of the dispute
2. The dispute is submitted to the community governance body with both nodes' audit trails as evidence
3. The governance body issues a determination within a defined period
4. The determination is recorded in both nodes' audit trails
5. A node that consistently violates protocol — confirmed by governance determination — is marked non-compliant in the discovery layer

---

## Part XI: The Capability Manifest

Every CRE-compliant module publishes a capability manifest before it may be loaded into any node. The manifest is cryptographically signed by the module's publisher.

```
capability_manifest:
  module_id:            unique identifier
  module_version:       semantic version
  publisher_id:         cryptographically verified identity
  publisher_signature:  signature of this manifest
  function:             RELATE | NAVIGATE | GOVERN | REMEMBER | VERIFY | SOMA
  inputs:               defined schema of accepted inputs
  outputs:              defined schema of produced outputs
  performance_envelope: expected latency, memory, compute requirements
  known_limitations:    honest declaration of what this module does not do
  behavioral_test_ref:  reference to published behavioral test suite
  compliance_profiles:  list of regulatory profiles this module supports
  last_audited:         timestamp of most recent independent behavioral audit
```

A module without a published, signed capability manifest may not be loaded into any CRE-compliant node. This is non-negotiable.

---

## Part XII: Regulatory Profile Framework

This contract defines the structure for regulatory profiles. Specific profiles are not defined here — they are published as separate documents and referenced by deployments. The framework is universal. The content is domain-specific.

```
regulatory_profile:
  profile_id:             unique identifier
  jurisdiction:           geographic and regulatory scope
  frameworks:             list of applicable regulations
  classification_mapping: how this profile maps sensitivity levels to regulatory categories
  retention_minimums:     minimum retention by classification level
  retention_maximums:     maximum retention by classification level
  consent_requirements:   specific consent schema extensions for this jurisdiction
  breach_notification:    timeline and recipient requirements
  access_rights:          individual rights supported (access, erasure, portability, correction)
  mandatory_checkpoints:  conditions requiring GOVERN regardless of deployment configuration
  prohibited_operations:  operations this profile explicitly forbids
  audit_requirements:     specific audit trail requirements beyond baseline
```

---

## Part XIII: Forward Compatibility Commitments

### 13.1 Schema versioning

Every record in the audit trail carries `schema_version` and `module_version`. These fields exist so that any future implementation can reconstruct the exact context in which a historical record was produced.

A future query of the form "what did this system do in 2025, and what version of what module produced it, and what was the schema that governed that record" must always be answerable from the audit trail alone.

### 13.2 Backward compatibility policy

- Protocol-level definitions (Parts I through XIII of this document) may only change through community governance authorization
- A change that makes previously valid records invalid is a breaking change and requires a migration path
- A change that makes previously valid records ambiguous is a breaking change
- Additive changes — new fields, new COMMIT types, new classification levels — are not breaking changes provided they do not alter the interpretation of existing records

### 13.3 The forward-focus principle

> **The system is designed for continuity across time, not prediction of it.**

Forward-focused means:
- Data structures are versioned so future implementations can read past records
- Modules are swappable so future components can integrate without breaking history
- The audit trail is append-only so future queries can reconstruct any past state
- The protocol is extensible so future entities can participate without the present constraining them

Forward-focused does not mean:
- The system generates predictions
- The system introduces synthetic data points representing future states
- The system models what is likely to happen

Every data point in the system traces to an external input or a direct, fully recorded derivation from external inputs. The system processes what is given to it. It does not reach beyond its inputs.

---

## Part XIV: The Socratic Principle

> **At every consequential moment, the system asks rather than tells. It presents examined candidates with visible reasoning rather than conclusions. Uncertainty is a first-class output.**

The Socratic principle is implemented structurally:

- NAVIGATE always returns a reasoning trace alongside its results
- NAVIGATE always returns completeness gaps alongside its results
- GOVERN always presents reasoning and uncertainty to the authorizing human
- "I do not know" is a valid and valuable COMMIT type — uncertainty, properly recorded, is one of the most informative signals the system produces

A system that always produces confident answers is not more trustworthy than one that declares uncertainty honestly. It is less trustworthy. Epistemic humility is not a weakness — it is the foundation of genuine reliability.

---

## Signatures and Ratification

This document becomes binding on both ONTO and CRE when:

1. Its SHA-256 hash is recorded in the ONTO public Gist alongside the principles hash
2. It is referenced in CRE-SPEC-001 as the crossover contract
3. Both projects' test suites include at least one test per core function (Parts III and IV) that verifies conformance with the definitions herein

Until those three conditions are met, this document is a draft under active review.

---

## Appendix A: Quick Reference — Protocol Verb Mapping

| ONTO module | Four-function layer | CRE protocol verb | COMMIT type produced |
|---|---|---|---|
| `intake` | RELATE (step 1) | `INGEST` | `rejected` if fails provenance |
| `contextualize` | RELATE (step 2) + NAVIGATE (step 1) | `INGEST` + `CONTEXTUALIZE` | `partial` if below threshold |
| `surface` | NAVIGATE (step 2) | `SURFACE` | — |
| SOMA | Integration | (internal — not a CRE verb) | — |
| `checkpoint` | GOVERN | `CHECKPOINT` | `vetoed` or passes to memory |
| `memory` | REMEMBER | `COMMIT` | `complete` |

---

## Appendix B: Quick Reference — Security Attack Surface

| Attack vector | Primary mitigation | Secondary mitigation |
|---|---|---|
| Graph poisoning | Provenance discount weights | Bias monitor + trail forensics |
| Checkpoint manipulation | Reasoning trace visibility | Completeness gap flags |
| Audit trail deletion | Cryptographic chaining | Distributed witnessing |
| Audit trail injection | External timestamp anchoring | Chain verification |
| Module substitution | Cryptographic signatures | Behavioral contract testing |
| Decay manipulation | GOVERN authorization required | Audit trail of all changes |
| Consent forgery | Specific scoping + expiration | Every consent traces to GOVERN |
| Sybil / masquerade | Cryptographic node identity | Formal inter-node agreements |

---

## Appendix C: Glossary

**Autopoiesis** — the property of a system that continuously regenerates itself through its own processes. Identity is located in the pattern of self-organization, not in specific components.

**Binding** — the integration of disparate signals into a unified understanding. Solved in this architecture by SOMA.

**Conatus** — Spinoza's principle that every thing strives to persist in its own being. The philosophical foundation of the self-preservation principle.

**Context** — see Part I, Section 1.1. A bounded subgraph of the relationship graph selected by relevance to a declared purpose at a specific moment in time.

**Contextual decay** — the reduction of edge weights over time as temporal distance increases. The system's metabolic process and environmental policy.

**CRE** — Contextual Reasoning Engine. The protocol governing communication between nodes.

**ONTO** — the node-level system implementing the four core functions.

**Provenance** — the verifiable chain of origin for a data entity or relationship. Who produced it, when, under what authorization.

**SOMA** — the integration layer within a node that binds processed signals into coherent context for GOVERN.

**Subgraph** — a subset of the relationship graph, selected by traversal from a declared root.

**VERIFY** — the cross-cutting immune system running across all four core functions.

---

*End of CROSSOVER-CONTRACT-001 v1.0*

*This document was produced through a collaborative design process between Neo and Claude, grounded in neuroscience, philosophy of mind, ecology, information theory, regulatory compliance, and adversarial systems design. It is released under the GNU Lesser General Public License v2.1 (LGPL-2.1).*
