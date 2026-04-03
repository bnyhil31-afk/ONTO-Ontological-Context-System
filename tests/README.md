# ONTO Test Suite

Tests: **315** always passing + **42** MCP (Python 3.10+ only) + **69** Federation + **57** Consent Ledger
CI: green ✅ across Python 3.9–3.12

Rule 1.09A: Any change to the test suite requires updating three things
together: the test file header (expected count), this README (expected
count), and the pre-launch checklist (current status). All three or none.

---

## Running the tests

```bash
pip install -r requirements-test.txt
pytest tests/ -v
```

Run a specific suite:

```bash
pytest tests/test_graph_phase1.py -v   # Phase 1 ontology core
pytest tests/test_mcp.py -v            # Phase 2 MCP interface
pytest tests/test_federation.py -v    # Phase 3 federation
pytest tests/test_consent.py -v       # Phase 4 consent ledger
```

---

## Test files

### tests/test_onto.py — Core pipeline (188 tests)

Covers the five-step pipeline, safety, compliance, and cryptographic
integrity. Organized into test classes per module.

### tests/test_graph.py — Relationship graph Stage 1 (32 tests)

Class                   | Tests | What it covers
------------------------|-------|-----------------------------------------------
TestGraphInitialize     |   3   | Tables created, indexes exist, idempotent
TestGraphRelate         |  10   | Node/edge creation, reinforcement, input counter,
                        |       | result schema, crisis never stored (safety-critical),
                        |       | sensitive detection, sensitive edges marked
TestGraphNavigate       |   7   | Empty/unknown query, related concepts returned,
                        |       | result schema, sorted by weight, sensitive excluded
                        |       | by default, source always "graph"
TestGraphDecay          |   4   | Recent edges preserved, stale edges pruned,
                        |       | orphaned nodes removed, return counts
TestGraphWipe           |   5   | All nodes deleted, all edges deleted, counter reset,
                        |       | navigate empty after wipe, audit event recorded
TestEffectiveWeight     |   3   | Power-law decay reduces weight over time,
                        |       | sensitive edges decay faster, result clamped [0,1]
TestSpacingIncrement    |   3   | Immediate = base, 30-day = 2× base, monotonic
TestConceptExtraction   |   3   | Empty text → empty list, stopwords filtered,
                        |       | MAX_CONCEPTS_PER_INPUT respected

### tests/test_graph_phase1.py — Phase 1 Ontology Core (60 tests)

Class                      | Tests | What it covers
---------------------------|-------|--------------------------------------------
TestEdgeTypeRegistry       |   5   | 16 types seeded, inverse_ids populated,
                           |       | co-occurs-with is id=2, idempotent
TestTypedEdges             |   4   | Default edge_type_id=2, direction=undirected,
                           |       | confidence=1.0, all categories valid
TestProvenanceTable        |   5   | Record per relate(), provenance_id in result,
                           |       | nodes have it set, human trust=0.95
TestProvBackfill           |   3   | Backfill record exists, idempotent,
                           |       | no NULL provenance_ids after relate()
TestPPRInterface           |   6   | Returns list, empty on bad seeds, never raises,
                           |       | subgraph schema, cache invalidation safe
TestPPMICounters           |   6   | Tables exist, global increments, counters
                           |       | populated, ppmi_weight stays NULL (lazy),
                           |       | prune returns edges_pruned key
TestDecayProfiles          |   5   | 5 profiles seeded, standard is default,
                           |       | lambda in (0,1], idempotent
TestSessionConfig          |   3   | Table exists, P2 columns present
TestConceptExtractorYAKE   |   6   | Empty→[], stopwords filtered, cap enforced,
                           |       | returns list, version/model name correct
TestExtractorPlugin        |   4   | Swap accepted, mock concepts appear,
                           |       | YAKE restore removes mock, thread-safe
TestMigration              |   5   | All Phase 1 tables present, Stage 1 preserved,
                           |       | data survives reinitialize, indexes exist,
                           |       | wipe clears ppmi_counters
TestForwardCompat          |   7   | All P2/P3/P4 columns present and NULL on
                           |       | graph_nodes, graph_edges, mcp_session_map

### tests/test_mcp.py — Phase 2 MCP Interface (42 tests)

Requires Python 3.10+ and `fastmcp>=2.0.0`. All 42 tests skip gracefully
on Python 3.9. See skip behaviour section below.

Class                      | Tests | What it covers
---------------------------|-------|--------------------------------------------
TestResponseEnvelope       |   5   | Envelope shape: ok, error, pending, crisis
TestSessionResolution      |   5   | Bearer token parsing, valid/invalid/missing
TestOntoIngest             |   6   | Nodes created, concepts returned, crisis
                           |       | never writes to graph, auth rejected
TestOntoQuery              |   5   | Known/unknown seeds, alpha clamped,
                           |       | subgraph keys, auth rejected
TestOntoSurface            |   4   | Confidence returned, classification present,
                           |       | crisis status, auth rejected
TestOntoCheckpoint         |   6   | Pending with bias warning, proceed/veto,
                           |       | invalid decision, all 4 decisions accepted
TestOntoRelate             |   5   | Nodes created, empty inputs → error,
                           |       | crisis content → crisis, auth rejected
TestOntoSchema             |   3   | 16 types, 7 categories, schema_version
TestOntoStatus             |   3   | status=healthy, graph metrics, PPR info

### tests/test_federation.py — Phase 3 Federation (69 tests)

Safety-critical classes are marked ⚠️. They block deployment if they
fail, even if all other tests pass.

Class                      | Tests | What it covers
---------------------------|-------|--------------------------------------------
⚠️ TestAbsoluteBarriers    |   6   | Crisis text always blocked, is_crisis=True
                           |       | always blocked, classification 4+ always
                           |       | blocked, nested field scanning
⚠️ TestFederationSafetyFilter|  5  | Valid data passes, no consent blocks,
                           |       | classification ceiling, sensitive low-trust,
                           |       | inbound trust capped at floor
TestNodeIdentity           |   5   | did:key format, key in file not SQLite,
                           |       | sign/verify roundtrip, load existing key
TestCapabilityManifest     |   4   | Required fields, crisis_barrier=True always,
                           |       | verify valid, verify tampered fails
TestConsentLedger          |   6   | Grant returns UUID, active valid, revoke,
                           |       | expired, standing reconfirmation, peer list
TestPeerStore              |   4   | Hash not PEM, valid cert, cert_changed,
                           |       | approve increments rotation_count
TestVectorClocks           |   5   | Equal, A dominates, B dominates, concurrent,
                           |       | merge is component-wise max
TestCRDTMerge              |   5   | ORSet add-wins, LWW causal order, GSet union,
                           |       | remote-only nodes added, concurrent conflict
TestLocalAdapter           |   6   | Crisis always false, class 4 always false,
                           |       | trust capped, discover, merge, health keys
TestIntranetAdapter        |   3   | Extends LocalAdapter, mdns_active in health,
                           |       | static peers in discover
TestFederationManager      |   5   | is_enabled false, never raises, get_adapter
                           |       | None before start, tables created, stop safe
TestMessaging              |   4   | First seq=1, increments, gap detected,
                           |       | rate limit blocks excess
TestMigration              |   4   | All 5 federation tables created, core tables
                           |       | unchanged, graph_nodes unchanged, idempotent
TestConcentrationDetection |   2   | Identical graphs=1.0, disjoint=0.0
TestAuditIntegrity         |   3   | Consent grant/revoke write audit events,
                           |       | peer pin writes audit event
TestOfflineSovereignty     |   2   | recall() revokes locally before peer notify,
                           |       | returns list even when peer unreachable

### tests/test_consent.py — Phase 4 Consent Ledger (57 tests)

Safety-critical classes are marked ⚠️. They block deployment if they
fail, even if all other tests pass.

Class                      | Tests | What it covers
---------------------------|-------|--------------------------------------------
⚠️ TestConsentAbsoluteBarriers| 6  | Crisis flag always blocked, crisis text always
                           |       | blocked, classification 4+ always blocked,
                           |       | valid consent cannot bypass absolute barrier
⚠️ TestConsentGate         |   9   | Self-access permitted, no consent triggers
                           |       | checkpoint, active consent permits, revoked
                           |       | blocked, expired blocked, wrong operation
                           |       | blocked, consent disabled permits all,
                           |       | audit-only permits but logs, never raises
TestConsentLedger          |   8   | Grant returns UUID, revoke marks inactive,
                           |       | unknown ID returns False, cascade revocation,
                           |       | history newest first, excludes revoked,
                           |       | grant/revoke write audit events
TestRegulatoryProfiles     |   7   | Team/healthcare/financial profiles load,
                           |       | HIPAA fields required, GLBA opt-out flag,
                           |       | unknown profile fallback, validation,
                           |       | retention lock financial
TestGLBAOptOut             |   2   | No opt-out permits, opt-out record blocks
TestVCServiceInterface     |   5   | NullVCService returns None/False/{},
                           |       | get_vc_service returns Null by default
TestSchemaJSONLD           |   4   | JSON-LD structure, VC envelope, DPV purposes,
                           |       | legal bases vocabularies complete
TestStatusListAllocation   |   4   | First index=0, increments, grant assigns
                           |       | index, encode/decode roundtrip
TestMigration              |   5   | consent_ledger and consent_requests tables,
                           |       | core tables unchanged, idempotent, all columns
TestConsentRecordDataclass |   7   | is_active fresh/revoked/expired,
                           |       | needs_reconfirmation, timed consent false,
                           |       | ConsentDecision bool, to_dict JSON-safe

### tests/test_session.py — Session management (17 tests)

Session creation, validation, rotation, termination, audit trail.

### tests/test_auth.py — Authentication (11 tests)

Passphrase setup, Argon2id verification, lockout, dev mode.

---

## Skip behaviour by Python version

| Python | Always | MCP | Federation | Consent | Total |
|--------|--------|-----|------------|---------|-------|
| 3.9    | 315    |  0  |    69      |   57    | 441   |
| 3.10+  | 315    |  42 |    69      |   57    | 483   |

MCP tests skip on 3.9 (fastmcp requires Python >=3.10).
All other tests run on all versions — no network required.
Skipped tests are not failures. CI is green on all versions.

---

## If a test fails

1. Read the failure message carefully — it explains exactly what went wrong
2. Do not ignore it or work around it
3. Fix the underlying issue before shipping

A failing test is the system telling you something important.
Listen to it.

---

## Keeping the count accurate — Rule 1.09A

Any change to the test suite requires updating three things together:
  - The test file header (expected count)
  - This README (expected count)
  - The pre-launch checklist (current status)

All three or none. A wrong number anywhere breaks trust.

---

These tests exist because the system makes promises.
The tests make sure the system keeps them.
