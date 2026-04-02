# ONTO Design Specification 001
**Document ID:** DESIGN-SPEC-001
**Version:** 1.1 (supersedes v1.0)
**Status:** LOCKED — All decisions confirmed. Coding may begin.
**Authors:** Neo (bnyhil31-afk), Claude (Anthropic)
**Covers checklist items:** 6.01, 6.02, 6.03, 6.04, 6.05
**Also covers:** MCP tool surface, vector integration, build-vs-borrow, migration strategy
**Rule 1.09A:** Code, tests, and documentation must agree with every decision here.

---

## Governing Principle: One Schema Migration, Ever

Neo's confirmed design constraint:

> *"Focus on ease of upgrading or adding on additional features in the future.
> I don't want to have to redo work or create additional work, understanding
> the goals and requirements for future implications and implementations."*

This constraint governs every decision in this document. It produces one rule:

**All columns for all phases are added to the schema in Phase 1. Logic for
each column is activated in the phase that needs it. No future schema migrations.**

A column that carries no data yet is free. A schema migration on a deployed
database with real user data is expensive, risky, and breaks the trust of
operators who built on top of you.

Phase annotations appear on every column: [P1], [P2], [P3], [P4].
P1 columns are populated immediately. P2-P4 columns are NULL, zero, or
default — present but silent until their phase activates.

---

## Part X — Confirmed Decisions (was: Open Questions)

All four Part X questions from v1.0 are now confirmed and locked.

### Decision 1: domain field — free-text now, registry later

`graph_nodes.domain` is a free-text field in Phase 1. A `node_domains` registry
table is added in Phase 2 as a lookup. Existing free-text values are preserved
as-is — normalization is additive, not destructive. No rework.

### Decision 2: Back-fill existing nodes with synthetic provenance

On first Phase 1 boot, all existing nodes and edges where `provenance_id IS NULL`
are assigned a synthetic provenance record:
source_type='system', source_id='historical_backfill', trust_score=0.90.
Runs exactly once (idempotent check before creating). All future records have
real provenance from the moment they are written.

### Decision 3: PPMI pruning threshold — configurable via env var

```
ONTO_PPMI_PRUNE_THRESHOLD=0.5   # default
```

Read at each `graph.prune()` call, not at boot. Can be changed between prune
runs without restarting. Domain-appropriate values: research=0.1, finance=0.75.

### Decision 4: MCP auth — Bearer token format from day one

Stage 1 validates ONTO's existing 256-bit session token as a Bearer token.
Stage 2 replaces validation with OAuth 2.1 introspection. The header format
does not change. MCP clients need zero changes to upgrade.

```
Authorization: Bearer <256-bit-session-token>    # Stage 1
Authorization: Bearer <OAuth-2.1-access-token>   # Stage 2 — same header
```

---

## Part I — Typed Directed Edge Schema (6.01)

### 1.1 Design Principles

1. Migration-safe — every change is ALTER TABLE ADD COLUMN with a default.
2. Vocabulary-governed — edge types live in a registry, not free-form strings.
3. Provenance-first — every edge and node carries a provenance reference.
4. All columns now, logic later — every column needed by any phase is present
   in the Phase 1 schema.

### 1.2 New Table: edge_types

```sql
CREATE TABLE IF NOT EXISTS edge_types (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    UNIQUE NOT NULL,
    category     TEXT    NOT NULL
                         CHECK (category IN (
                             'taxonomic',
                             'mereological',
                             'causal',
                             'associative',
                             'temporal',
                             'spatial',
                             'epistemic'
                         )),
    inverse_id   INTEGER REFERENCES edge_types(id),
    description  TEXT    NOT NULL,
    is_directed  INTEGER NOT NULL DEFAULT 1,
    created_at   REAL    NOT NULL,
    is_sealed    INTEGER NOT NULL DEFAULT 0
);
```

### 1.3 Standard Edge Type Vocabulary (16 types, seeded at initialize)

| id | name           | category      | inverse        | directed | basis                  |
|----|----------------|---------------|----------------|----------|------------------------|
| 1  | related-to     | associative   | related-to     | 0        | SKOS skos:related      |
| 2  | co-occurs-with | associative   | co-occurs-with | 0        | ONTO native (default)  |
| 3  | is-a           | taxonomic     | has-subtype    | 1        | RDFS rdfs:subClassOf   |
| 4  | has-subtype    | taxonomic     | is-a           | 1        | RDFS rdfs:subClassOf   |
| 5  | instance-of    | taxonomic     | has-instance   | 1        | OWL classAssertion     |
| 6  | has-instance   | taxonomic     | instance-of    | 1        | OWL classAssertion     |
| 7  | part-of        | mereological  | has-part       | 1        | BFO RO:0001001         |
| 8  | has-part       | mereological  | part-of        | 1        | BFO RO:0001001         |
| 9  | causes         | causal        | caused-by      | 1        | RO:0002410             |
| 10 | caused-by      | causal        | causes         | 1        | RO:0002410             |
| 11 | precedes       | temporal      | follows        | 1        | OWL-Time time:before   |
| 12 | follows        | temporal      | precedes       | 1        | OWL-Time time:before   |
| 13 | located-in     | spatial       | contains       | 1        | GeoSPARQL              |
| 14 | contains       | spatial       | located-in     | 1        | GeoSPARQL              |
| 15 | supports       | epistemic     | supported-by   | 1        | ONTO native            |
| 16 | supported-by   | epistemic     | supports       | 1        | ONTO native            |

All seeded via INSERT OR IGNORE — idempotent on every boot.
Default for all existing co-occurrence edges: edge_type_id = 2.

### 1.4 New Table: provenance (W3C PROV-DM compatible from day one)

```sql
CREATE TABLE IF NOT EXISTS provenance (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,

    -- [P1] Core provenance
    source_type      TEXT    NOT NULL
                             CHECK (source_type IN (
                                 'human', 'sensor', 'llm', 'derived', 'system'
                             )),
    source_id        TEXT,
    session_hash     TEXT,               -- SHA-256(session_token)
    trust_score      REAL    NOT NULL
                             CHECK (trust_score >= 0.0 AND trust_score <= 1.0),
    content_hash     TEXT,               -- SHA-256(source_text + model_version)
    model_version    TEXT,
    created_at       REAL    NOT NULL,
    verified_at      REAL,
    verified_by      TEXT,

    -- [P2] W3C PROV-DM fields
    prov_entity_id   TEXT,
    prov_agent_id    TEXT,
    prov_activity_id TEXT,
    consent_id       TEXT,               -- UUID v4 from consent ledger

    -- [P3] Federation
    origin_node_id   TEXT
);
```

Default trust scores by source type:

| source_type | trust_score | note                                           |
|-------------|-------------|------------------------------------------------|
| human       | 0.95        | Direct input                                   |
| sensor      | 0.85        | Calibrated measurement                         |
| llm         | 0.30        | Ungrounded; must be verified to promote        |
| derived     | 0.60        | Computed; quality varies                       |
| system      | 0.90        | ONTO's own operations                          |

Configurable thresholds:
- ONTO_TRUST_THRESHOLD_FLAG=0.5        (below: flagged in surface output)
- ONTO_TRUST_THRESHOLD_CHECKPOINT=0.2  (below: requires human checkpoint)

### 1.5 graph_nodes — Complete Phase-Annotated Schema

All ALTER TABLE additions for all phases, run once in Phase 1:

```sql
-- [P1] Provenance and domain
ALTER TABLE graph_nodes ADD COLUMN provenance_id     INTEGER REFERENCES provenance(id);
ALTER TABLE graph_nodes ADD COLUMN domain            TEXT;

-- [P2] Identity, temporal validity, soft delete
ALTER TABLE graph_nodes ADD COLUMN did_key           TEXT;   -- W3C DID: did:key:z6Mk...
ALTER TABLE graph_nodes ADD COLUMN valid_from        REAL;
ALTER TABLE graph_nodes ADD COLUMN valid_to          REAL;   -- NULL = open-ended
ALTER TABLE graph_nodes ADD COLUMN is_deleted        INTEGER NOT NULL DEFAULT 0;

-- [P3] Federation and CRDT
ALTER TABLE graph_nodes ADD COLUMN origin_node_id    TEXT;
ALTER TABLE graph_nodes ADD COLUMN vector_clock      TEXT;   -- JSON: {"nodeA":3,"nodeB":1}
ALTER TABLE graph_nodes ADD COLUMN crdt_state        TEXT;   -- JSON: OR-Set CRDT state

-- [P4] Embeddings
ALTER TABLE graph_nodes ADD COLUMN embedding         BLOB;
ALTER TABLE graph_nodes ADD COLUMN embedding_model   TEXT;
ALTER TABLE graph_nodes ADD COLUMN embedding_version TEXT;
ALTER TABLE graph_nodes ADD COLUMN embedding_hash    TEXT;   -- SHA-256(label+model+version)
ALTER TABLE graph_nodes ADD COLUMN embedded_at       REAL;
```

### 1.6 graph_edges — Complete Phase-Annotated Schema

```sql
-- [P1] Core typed edge fields
ALTER TABLE graph_edges ADD COLUMN edge_type_id      INTEGER DEFAULT 2
                                                     REFERENCES edge_types(id);
ALTER TABLE graph_edges ADD COLUMN direction         TEXT DEFAULT 'undirected'
                                                     CHECK (direction IN (
                                                         'forward','reverse','undirected'));
ALTER TABLE graph_edges ADD COLUMN provenance_id     INTEGER REFERENCES provenance(id);
ALTER TABLE graph_edges ADD COLUMN confidence        REAL DEFAULT 1.0
                                                     CHECK (confidence >= 0.0
                                                        AND confidence <= 1.0);
ALTER TABLE graph_edges ADD COLUMN ppmi_weight       REAL;
ALTER TABLE graph_edges ADD COLUMN ppmi_at           REAL;

-- [P2] Temporal validity and soft delete
ALTER TABLE graph_edges ADD COLUMN valid_from        REAL;
ALTER TABLE graph_edges ADD COLUMN valid_to          REAL;
ALTER TABLE graph_edges ADD COLUMN is_deleted        INTEGER NOT NULL DEFAULT 0;

-- [P3] Federation and CRDT
ALTER TABLE graph_edges ADD COLUMN origin_node_id    TEXT;
ALTER TABLE graph_edges ADD COLUMN crdt_lww_ts       REAL;   -- LWW-Register timestamp
ALTER TABLE graph_edges ADD COLUMN vector_clock      TEXT;   -- JSON
```

### 1.7 SQLite Index Strategy (partial WHERE indexes — stay small at Phase 1 scale)

```sql
CREATE INDEX IF NOT EXISTS idx_edges_source_type
    ON graph_edges(source_id, edge_type_id) WHERE is_deleted = 0;

CREATE INDEX IF NOT EXISTS idx_edges_target_type
    ON graph_edges(target_id, edge_type_id) WHERE is_deleted = 0;

CREATE INDEX IF NOT EXISTS idx_edges_ppmi_stale
    ON graph_edges(ppmi_at)
    WHERE ppmi_weight IS NULL OR ppmi_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_provenance_type_time
    ON provenance(source_type, created_at);

CREATE INDEX IF NOT EXISTS idx_nodes_valid
    ON graph_nodes(valid_from, valid_to) WHERE valid_from IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_nodes_origin
    ON graph_nodes(origin_node_id) WHERE origin_node_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_nodes_embedding_stale
    ON graph_nodes(embedding_version) WHERE embedding IS NOT NULL;
```

---

## Part II — Personalized PageRank Interface (6.02)

### 2.1 Algorithm: fast-pagerank on scipy.sparse CSR

| Competitor    | 10K nodes | 100K nodes | verdict                    |
|---------------|-----------|------------|----------------------------|
| NetworkX      | ~6s       | ~60s       | Rejected — too slow        |
| fast-pagerank | ~50ms     | ~500ms     | Selected                   |
| graph-tool    | ~5ms      | ~50ms      | Rejected — ARM fails       |

CSR matrix built at `graph.initialize()`, held in module scope, invalidated
on every `graph.relate()` write (flag only — rebuilt lazily on next query).

### 2.2 Alpha Policy

| Step            | alpha | behavior                                        |
|-----------------|-------|-------------------------------------------------|
| contextualize   | 0.85  | Balanced neighborhood                           |
| surface         | 0.80  | Local — directly related concepts               |
| memory          | 0.90  | Structural — globally important nodes           |
| onto_query (MCP)| 0.85 default, caller-defined, clamped [0.70, 0.95] |

### 2.3 Hardware-Tiered Graph Loading

Auto-detected from `psutil.virtual_memory().available` at boot.

| Tier       | RAM    | Max nodes | Strategy                             |
|------------|--------|-----------|--------------------------------------|
| Pi         | 256MB  | 5,000     | 2-hop subgraph from seed             |
| Laptop     | 1GB    | 50,000    | Full if < 50K, else 3-hop sub        |
| Enterprise | 8GB+   | 500,000+  | Full graph, CSR cached               |

### 2.4 Public API

```python
def compute_ppr(
    seed_node_ids: list[int],
    alpha: float = 0.85,
    edge_type_ids: list[int] | None = None,
    top_k: int = 50,
    min_score: float = 0.001,
) -> list[tuple[int, float]]:
    """
    Returns [(node_id, score), ...] sorted descending.
    Falls back to weighted BFS if graph < 200 nodes or avg_degree < 3.
    Never raises. Logs fallback to audit trail.
    """

def get_ppr_subgraph(
    seed_node_ids: list[int],
    alpha: float = 0.85,
    edge_type_ids: list[int] | None = None,
    top_k: int = 50,
) -> dict:
    """JSON-serializable subgraph. Schema: {nodes, edges, metadata}"""

def invalidate_ppr_cache() -> None:
    """Called by graph.relate() after every write."""
```

---

## Part III — PPMI Matrix Approach (6.03)

### 3.1 Design: Incremental Counters, Lazy Computation

PPMI is never materialized as a matrix. Weights are computed lazily from running
counters. O(1) per edge. Scales to streaming input indefinitely.

### 3.2 New Tables: ppmi_counters + ppmi_global

```sql
CREATE TABLE IF NOT EXISTS ppmi_counters (
    node_id        INTEGER PRIMARY KEY REFERENCES graph_nodes(id),
    marginal_count REAL    NOT NULL DEFAULT 0.0,
    last_decay_at  REAL
);

CREATE TABLE IF NOT EXISTS ppmi_global (
    key   TEXT PRIMARY KEY,
    value REAL NOT NULL
);
-- Seeded at initialize() via INSERT OR IGNORE:
-- ('total_co_occurrences', 0.0)
-- ('smoothing_alpha', 0.75)
-- ('decay_lambda', 0.95)
```

### 3.3 PPMI Formula (Levy et al. 2015, context smoothing α=0.75)

```
P(A,B)    = C(A,B) / total_co_occurrences
P(A)      = marginal_count_A / total_co_occurrences
P(B)^0.75 = (marginal_count_B / total_co_occurrences) ^ 0.75

PPMI(A,B) = max(0, log₂( P(A,B) / (P(A) × P(B)^0.75) ))
```

Result cached in `graph_edges.ppmi_weight`. Invalidated when marginals change > 5%.

### 3.4 Counter Update (inside graph.relate(), every write)

```python
# Increment both nodes' marginal counts
# Increment global total_co_occurrences
# Set ppmi_weight = NULL, ppmi_at = NULL for this edge
```

### 3.5 Vocabulary Drift (inside graph.decay())

```sql
UPDATE ppmi_counters
SET marginal_count = marginal_count * :lambda
WHERE last_decay_at < :now - :epoch_seconds;
UPDATE ppmi_counters SET last_decay_at = :now;
UPDATE ppmi_global SET value = value * :lambda WHERE key = 'total_co_occurrences';
UPDATE graph_edges SET ppmi_weight = NULL, ppmi_at = NULL;
```

### 3.6 Pruning

`graph.prune(threshold=None)` reads `ONTO_PPMI_PRUNE_THRESHOLD` (default 0.5).
Read at call time — configurable between runs. Lazily computes PPMI, soft-deletes
edges below threshold (`is_deleted = 1`). Every prune event in audit trail.

---

## Part IV — Per-User Decay Calibration (6.04)

### 4.1 New Table: decay_profiles

```sql
CREATE TABLE IF NOT EXISTS decay_profiles (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT    UNIQUE NOT NULL,
    description          TEXT    NOT NULL,
    lambda               REAL    NOT NULL DEFAULT 0.95
                                 CHECK (lambda > 0.0 AND lambda <= 1.0),
    epoch_seconds        INTEGER NOT NULL DEFAULT 86400,
    min_weight           REAL    NOT NULL DEFAULT 0.01,
    domain               TEXT,
    is_default           INTEGER NOT NULL DEFAULT 0,
    created_at           REAL    NOT NULL,
    -- [P2] Regulatory linking
    regulatory_framework TEXT,           -- 'HIPAA', 'GDPR', 'GLBA', 'general'
    min_retention_days   INTEGER         -- regulatory minimum
);
```

Five seeded profiles:

| name       | λ     | epoch  | domain    | framework | retention |
|------------|-------|--------|-----------|-----------|-----------|
| standard   | 0.95  | 86400  | general   | general   | NULL      |
| slow       | 0.99  | 86400  | medical   | HIPAA     | 365       |
| fast       | 0.85  | 3600   | realtime  | general   | NULL      |
| personal   | 0.97  | 43200  | personal  | GDPR      | NULL      |
| financial  | 0.98  | 86400  | financial | GLBA      | 2555      |

Selected via `ONTO_DECAY_PROFILE=slow`. Read at each decay call.

### 4.2 New Table: session_config (thin override layer, keeps core/session.py clean)

```sql
CREATE TABLE IF NOT EXISTS session_config (
    session_hash        TEXT    PRIMARY KEY,  -- SHA-256(session_token)
    decay_profile_id    INTEGER REFERENCES decay_profiles(id),
    -- [P2] Regulatory override per session
    regulatory_profile  TEXT,
    -- [P3] Geographic data residency constraint
    data_residency      TEXT,
    created_at          REAL    NOT NULL
);
```

Phase 1: only decay_profile_id is populated. All other columns are NULL and ready.

---

## Part V — Concept Extraction (6.05)

### 5.1 Decision: YAKE-inspired stdlib implementation

YAKE's five features map to ONTO's three axes:
- Casing + position → Distance (how central is this concept?)
- Frequency → Size (how common is this concept?)
- Context diversity + sentence spread → Complexity (how many contexts does it span?)

No external dependency. ~80 lines stdlib Python. Hard cap: 15 concepts per input.

### 5.2 Pluggable Extractor Interface (the contract — never changes)

```python
# modules/intake.py

from typing import Protocol

class ConceptExtractor(Protocol):
    def extract(self, text: str, max_concepts: int = 15) -> list[str]: ...
    def get_version(self) -> str: ...       # for provenance tracking
    def get_model_name(self) -> str: ...    # for audit trail

_EXTRACTOR: ConceptExtractor = YAKEExtractor()

def set_extractor(extractor: ConceptExtractor) -> None:
    """Thread-safe swap. Change written to audit trail. Used by tests + Phase 4."""
    global _EXTRACTOR
    _EXTRACTOR = extractor
```

Phase roadmap:

| Phase | Implementation  | New dep | Capability                              |
|-------|-----------------|---------|------------------------------------------|
| P1    | YAKEExtractor   | none    | Keyword extraction, 15 cap               |
| P4    | SpacyExtractor  | spaCy   | NER: people, orgs, locations, dates      |

Phase 4 SpacyExtractor also implements an optional `extract_typed()` method
returning `{"label": str, "suggested_type": str}` pairs. YAKEExtractor leaves
this unimplemented (not in the Protocol — additive only).

---

## Part VI — MCP Tool Surface Design (Phase 2)

### 6.1 Framework: FastMCP 3.x

Decorator-based, async-first, OpenTelemetry built-in, granular authorization.
JSON Schema auto-generated from type annotations — tool definitions always in sync.

### 6.2 Tool Surface (8 tools — this is the ceiling)

| Tool              | Maps to              | Type     |
|-------------------|----------------------|----------|
| onto_ingest       | full 5-step pipeline | Tool     |
| onto_query        | get_ppr_subgraph()   | Tool     |
| onto_surface      | modules/surface      | Tool     |
| onto_checkpoint   | modules/checkpoint   | Tool     |
| onto_relate       | graph.relate()       | Tool     |
| onto_schema       | edge_types table     | Resource |
| onto_status       | config + graph stats | Resource |
| onto_audit        | audit trail          | Resource |

### 6.3 Standard Response Envelope (versioned from day one)

```json
{
  "status": "ok | error | pending_checkpoint | degraded",
  "data": {},
  "audit_id": "<record ID>",
  "confidence": 0.0,
  "warnings": [],
  "checkpoint_required": false,
  "checkpoint_context": null,
  "schema_version": "1.0"
}
```

`schema_version` is present immediately. Clients negotiate on it.
It does not change frequently, but it must exist before any client builds against this.

### 6.4 New Table: mcp_session_map (all phases present)

```sql
CREATE TABLE IF NOT EXISTS mcp_session_map (
    mcp_session_id   TEXT    PRIMARY KEY,
    onto_token_hash  TEXT    NOT NULL,
    created_at       REAL    NOT NULL,
    last_active      REAL    NOT NULL,
    -- [P2] OAuth 2.1 fields
    oauth_subject    TEXT,
    oauth_scope      TEXT,
    oauth_expires_at REAL,
    -- [P3] Federation
    origin_node_id   TEXT
);
```

### 6.5 Security Requirements

| Threat                | Mitigation                                                    |
|-----------------------|---------------------------------------------------------------|
| Tool poisoning        | Strict JSON Schema validation on every argument              |
| Graph poisoning       | Parameterized queries only                                    |
| Prompt injection      | All arguments treated as untrusted external input            |
| Session hijacking     | IP binding; token rotation on every call                     |
| Replay attacks        | Nonce + 30-second expiry (CRE-SPEC-001 §37.1)               |
| Audit gap             | Pre-record before execution, post-record on complete         |
| Result leakage        | Data classification filter on every response                 |
| Sensitive inference   | surface_safety_filter() on all PPR outputs                   |

onto_checkpoint is the most sensitive tool. Two-person review before production.

---

## Part VII — Vector / Embedding Integration (Phase 4)

### 7.1 Architecture: Parallel Signal, Convex Combination

```
score(node) = α × structural_ppr(node) + (1 - α) × semantic_cosine(node)
```

ONTO_EMBEDDING_ALPHA=0.7 (default, defined now, activated in Phase 4).

### 7.2 Hardware-Tiered Models (same tier detection as PPR)

| Tier       | Model                   | Dims | Latency   |
|------------|-------------------------|------|-----------|
| Pi         | all-MiniLM-L6-v2 (ONNX) | 384  | 200-500ms |
| Laptop     | nomic-embed-text-v1.5   | 768  | 80-100ms  |
| Enterprise | BGE-M3                  | 1024 | <10ms GPU |

### 7.3 Storage: sqlite-vector (zero additional infrastructure)

Vectors stored as BLOBs in `graph_nodes.embedding`. sqlite-vector adds a virtual
table index over that column. The column is already in the schema (Phase 1).
Phase 4 activates the index and similarity queries — no schema change.

### 7.4 Embedding Provenance

```
embedding_hash = SHA-256(concept_label + "|" + embedding_model + "|" + embedding_version)
```

On model upgrade: flag all nodes where `embedding_version != new_version` as stale.
Re-embed lazily or in background. Never serve mixed-version vectors together.

---

## Part VIII — Build vs Borrow Register

### Build Custom

| Component               | Reason                                                        |
|-------------------------|---------------------------------------------------------------|
| SQLite schema           | No library matches ONTO's provenance + typed edge model      |
| PPMI counter logic      | No off-the-shelf incremental PPMI for streaming dynamic graphs|
| YAKE concept extractor  | Zero deps; stdlib reimplementation ~80 lines                  |
| Trust scoring           | Domain-specific W3C PROV-DM simplified for SQLite            |
| MCP tool handlers       | Business logic is ONTO-specific; FastMCP provides the frame  |
| session_config table    | Thin layer; keeps core/session.py unchanged and upgradeable  |

### Borrow (phased)

| Phase | Library         | Purpose                                | Install                       |
|-------|-----------------|----------------------------------------|-------------------------------|
| P1    | fast-pagerank   | PPR on scipy CSR                       | pip install fast-pagerank      |
| P1    | scipy           | Sparse matrix substrate                | pip install scipy              |
| P1    | psutil          | RAM detection for hardware tier        | pip install psutil             |
| P2    | fastmcp         | MCP server framework                   | pip install fastmcp            |
| P3    | zeroconf        | mDNS node discovery                    | pip install zeroconf           |
| P3    | kademlia        | DHT discovery                          | pip install kademlia           |
| P3    | crdts           | CRDT foundation                        | pip install crdts              |
| P3    | grpcio          | mTLS inter-node                        | pip install grpcio grpcio-tools|
| P4    | fastembed       | ONNX embedding inference               | pip install fastembed          |
| P4    | sqlite-vector   | Vector search in SQLite                | pip install sqlite-vector      |

### Explicitly Rejected

| Library     | Reason                                                             |
|-------------|--------------------------------------------------------------------|
| NetworkX    | 40-250x slower at meaningful graph scale                          |
| graph-tool  | ARM/Pi compilation failures                                        |
| owlready2   | Incompatible schema; opaque quadstore                             |
| PyTorch     | Too heavy for edge hardware                                        |
| LangChain   | Orchestration framework, not a knowledge store                     |

---

## Part IX — Schema Migration Strategy

### 9.1 The Single Migration Principle

All schema changes happen once, in Phase 1. Never again.
Every column for every phase is present after the first Phase 1 boot.
No future ALTER TABLE. No migration scripts. No operator downtime.

### 9.2 Migration Execution Order (single transaction, 14 steps)

```
1.  CREATE TABLE IF NOT EXISTS edge_types
2.  INSERT OR IGNORE — 16 standard edge types
3.  CREATE TABLE IF NOT EXISTS provenance
4.  CREATE TABLE IF NOT EXISTS ppmi_counters
5.  CREATE TABLE IF NOT EXISTS ppmi_global + seed rows
6.  CREATE TABLE IF NOT EXISTS decay_profiles + 5 profiles
7.  CREATE TABLE IF NOT EXISTS session_config
8.  CREATE TABLE IF NOT EXISTS mcp_session_map
9.  ALTER TABLE graph_nodes ADD COLUMN — all [P1]-[P4] columns
10. ALTER TABLE graph_edges ADD COLUMN — all [P1]-[P3] columns
11. CREATE INDEX IF NOT EXISTS — all indexes (partial WHERE clauses)
12. Provenance backfill — assign system provenance to all NULL records
13. Seed ppmi_global counters from existing edge counts
14. WAL mode, cache size, foreign key enforcement (idempotent PRAGMAs)
```

All 14 steps in one transaction. Any failure rolls back completely. ONTO exits
with a clear human-readable error. The database is never left in a partial state.

### 9.3 Forward Compatibility Invariants (never violate)

1. All columns are nullable or have defaults.
2. No column is ever renamed.
3. No column is ever deleted (mark deprecated in docs; leave in schema).
4. edge_types.id values are never recycled.
5. provenance schema is W3C PROV-DM additive — new fields only.

### 9.4 Required Test Classes (Rule 1.09A)

| Test class             | Covers                                                       |
|------------------------|--------------------------------------------------------------|
| TestEdgeTypeRegistry   | Seeding, idempotency, FK integrity, is_sealed enforcement    |
| TestTypedEdges         | Create edge per type, direction semantics, default type=2    |
| TestProvenanceTable    | Create records, trust constraints, backfill idempotency      |
| TestPPRCompute         | PPR on small graph, BFS fallback, alpha boundaries           |
| TestPPRSubgraph        | JSON-serializable output, edge type filtering                |
| TestPPMICounters       | Increment, decay, formula correctness, threshold pruning     |
| TestDecayProfiles      | Seeding, lambda constraints, env var selection               |
| TestSessionConfig      | Create session config, profile assignment, isolation         |
| TestConceptExtractor   | YAKE scoring, 15-concept cap, empty input, protocol impl     |
| TestExtractorPlugin    | set_extractor() swap, MockExtractor, audit trail entry       |
| TestMigration          | Apply Phase 1 schema to Stage 1 database, zero data loss     |
| TestForwardCompat      | P2-P4 columns present and NULL after Phase 1 boot            |
| TestProvBackfill       | Backfill runs once, all NULL provenance_ids assigned         |

---

## Phase Activation Map

What is active in each phase. Code written; logic dormant until activated:

| Component                       | P1 | P2 | P3 | P4 |
|---------------------------------|----|----|----|----|
| Typed edge schema (all cols)    | ✅ | ✅ | ✅ | ✅ |
| edge_type_id logic              | ✅ | ✅ | ✅ | ✅ |
| Provenance + trust scoring      | ✅ | ✅ | ✅ | ✅ |
| W3C PROV-DM export              | 💤 | ✅ | ✅ | ✅ |
| Consent ledger (consent_id)     | 💤 | ✅ | ✅ | ✅ |
| PPR compute + BFS fallback      | ✅ | ✅ | ✅ | ✅ |
| PPMI counters + lazy weight     | ✅ | ✅ | ✅ | ✅ |
| Decay profiles + env config     | ✅ | ✅ | ✅ | ✅ |
| Regulatory profile link         | 💤 | ✅ | ✅ | ✅ |
| did:key node identity           | 💤 | ✅ | ✅ | ✅ |
| Temporal validity (valid_from)  | 💤 | ✅ | ✅ | ✅ |
| Soft delete (is_deleted)        | 💤 | ✅ | ✅ | ✅ |
| MCP tool surface (8 tools)      | 💤 | ✅ | ✅ | ✅ |
| Bearer token auth               | 💤 | ✅ | ✅ | ✅ |
| OAuth 2.1 + PKCE                | 💤 | 💤 | ✅ | ✅ |
| CRDT fields + merge logic       | 💤 | 💤 | ✅ | ✅ |
| Federation + vector clock       | 💤 | 💤 | ✅ | ✅ |
| mDNS + Kademlia discovery       | 💤 | 💤 | ✅ | ✅ |
| Embedding columns (graph_nodes) | 💤 | 💤 | 💤 | ✅ |
| sqlite-vector index             | 💤 | 💤 | 💤 | ✅ |
| Convex combination scoring      | 💤 | 💤 | 💤 | ✅ |
| Hardware-tiered model select    | 💤 | 💤 | 💤 | ✅ |

✅ = logic active   💤 = column present, logic dormant

---

## Document Status

All items locked. Coding may begin.

First file: `modules/graph.py`
First change: `graph.initialize()` — the 14-step migration sequence.
Rule 1.09A applies from line one.

This document is part of the permanent record of ONTO.
Code follows design. Never the reverse.

*Let's explore together.*
