# ONTO Test Suite

Tests: **315** always passing + **42** MCP tests (Python 3.10+ only)
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

Run only a specific suite:

```bash
pytest tests/test_graph_phase1.py -v   # Phase 1 ontology core
pytest tests/test_mcp.py -v            # Phase 2 MCP interface
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
on Python 3.9 — the rest of the suite is unaffected. See skip behaviour
section below.

Tools are tested by calling the decorated Python functions directly,
without a live MCP transport. Session auth is mocked so tests run
without a running ONTO server or live credentials.

Class                      | Tests | What it covers
---------------------------|-------|--------------------------------------------
TestResponseEnvelope       |   5   | Every envelope shape: ok, error,
                           |       | pending_checkpoint, crisis. schema_version
                           |       | always present and equal to "1.0"
TestSessionResolution      |   5   | Bearer token parsing, valid session resolves,
                           |       | missing / non-Bearer / invalid token
                           |       | returns None, _require_session safe to call
TestOntoIngest             |   6   | Nodes and edges created, concepts in result,
                           |       | provenance_id returned, crisis input never
                           |       | writes to graph, rejected without auth
TestOntoQuery              |   5   | Known concepts return ok, unknown concepts
                           |       | return ok with warning (not an error),
                           |       | alpha clamped to [0.70, 0.95], subgraph
                           |       | keys present, rejected without auth
TestOntoSurface            |   4   | Confidence returned, classification present,
                           |       | crisis input returns crisis status,
                           |       | rejected without auth
TestOntoCheckpoint         |   6   | No decision → pending_checkpoint with
                           |       | automation bias warning (EU AI Act Art 14),
                           |       | proceed authorizes, veto halts action,
                           |       | invalid decision → error with valid options,
                           |       | all four valid decisions accepted
TestOntoRelate             |   5   | Nodes created for both concepts, empty source
                           |       | or target → error, crisis content → crisis
                           |       | status (never stored), rejected without auth
TestOntoSchema             |   3   | Exactly 16 edge types, all 7 categories
                           |       | present, schema_version = "1.0"
TestOntoStatus             |   3   | status=healthy, graph metrics present
                           |       | (nodes/edges/inputs), PPR info present
                           |       | with hardware_tier

### tests/test_session.py — Session management (17 tests)

Session creation, validation, rotation, termination, audit trail.

### tests/test_auth.py — Authentication (11 tests)

Passphrase setup, Argon2id verification, lockout, dev mode.

---

## MCP test skip behaviour

On Python 3.9, FastMCP is not installed (a version marker in
`requirements-test.txt` restricts it to Python >=3.10). Every class in
`test_mcp.py` is decorated with:

```python
@unittest.skipUnless(_FASTMCP_INSTALLED, "fastmcp not installed ...")
```

Result by Python version:

| Python | Tests run | Tests skipped | Total reported |
|--------|-----------|---------------|----------------|
| 3.9    | 315       | 42            | 357 (42 skip)  |
| 3.10   | 357       | 0             | 357            |
| 3.11   | 357       | 0             | 357            |
| 3.12   | 357       | 0             | 357            |

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
