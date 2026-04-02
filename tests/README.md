# ONTO Test Suite

Tests: **313** passing across Python 3.9–3.12
CI: green ✅

Rule 1.09A: Any change to the test suite requires updating three things
together: the test file header (expected count), this README (expected
count), and the pre-launch checklist (current status). All three or none.

---

## Running the tests

```bash
pip install -r requirements-test.txt
pytest tests/ -v
```

To run only Phase 1 tests:
```bash
pytest tests/test_graph_phase1.py -v
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

### tests/test_session.py — Session management (17 tests)

Session creation, validation, rotation, termination, audit trail.

### tests/test_auth.py — Authentication (11 tests)

Passphrase setup, Argon2id verification, lockout, dev mode.

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
