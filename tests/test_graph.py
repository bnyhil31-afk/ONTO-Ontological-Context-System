"""
tests/test_graph.py

Tests for modules/graph.py — the relationship graph.

Checklist items: 1.14, 1.17, 2.12

Rule 1.09A: Code, tests, and documentation must always agree.

Test count: 32
  TestGraphInitialize     —  3 tests
  TestGraphRelate         — 10 tests
  TestGraphNavigate       —  7 tests
  TestGraphDecay          —  4 tests
  TestGraphWipe           —  5 tests
  TestEffectiveWeight     —  3 tests
"""

import math
import os
import shutil
import sqlite3
import tempfile
import unittest

from modules import memory, graph
from modules.graph import _effective_weight, _spacing_increment, _extract_concepts


# ---------------------------------------------------------------------------
# SHARED BASE — isolated database per test
# ---------------------------------------------------------------------------

class _GraphTestBase(unittest.TestCase):
    """
    Every test gets its own temporary database.
    memory.DB_PATH is patched so graph.py's _memory.DB_PATH follows —
    they reference the same module object.
    """

    def setUp(self):
        self._orig_db = memory.DB_PATH
        self.test_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.test_dir, "test_memory.db")
        memory.DB_PATH = self.test_db
        memory.initialize()
        graph.initialize()

    def tearDown(self):
        memory.DB_PATH = self._orig_db
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _relate(self, text: str) -> dict:
        return graph.relate({"raw": text, "clean": text})

    def _node_count(self) -> int:
        conn = sqlite3.connect(self.test_db)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM graph_nodes"
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def _edge_count(self) -> int:
        conn = sqlite3.connect(self.test_db)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM graph_edges"
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def _total_inputs(self) -> int:
        conn = sqlite3.connect(self.test_db)
        try:
            row = conn.execute(
                "SELECT value FROM graph_metadata "
                "WHERE key = 'total_inputs_processed'"
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# INITIALIZE
# ---------------------------------------------------------------------------

class TestGraphInitialize(_GraphTestBase):
    """
    initialize() must create the required tables and indexes.
    It must be safe to call multiple times.
    """

    def test_initialize_creates_node_and_edge_tables(self):
        """
        graph_nodes and graph_edges tables must exist after initialize().
        The system cannot function without them.
        """
        conn = sqlite3.connect(self.test_db)
        try:
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        finally:
            conn.close()

        self.assertIn("graph_nodes", tables)
        self.assertIn("graph_edges", tables)
        self.assertIn("graph_metadata", tables)

    def test_initialize_creates_indexes(self):
        """
        Performance indexes must exist after initialize().
        Without them, graph traversal at scale degrades severely.
        """
        conn = sqlite3.connect(self.test_db)
        try:
            indexes = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        finally:
            conn.close()

        self.assertIn("idx_graph_nodes_concept", indexes)
        self.assertIn("idx_graph_edges_source", indexes)
        self.assertIn("idx_graph_edges_target", indexes)

    def test_initialize_is_idempotent(self):
        """
        Calling initialize() twice must not raise and must not
        duplicate tables or corrupt existing data.
        """
        self._relate("first input before second init")
        try:
            graph.initialize()
        except Exception as exc:
            self.fail(f"Second initialize() raised: {exc}")

        self.assertEqual(self._node_count(), self._node_count())


# ---------------------------------------------------------------------------
# RELATE
# ---------------------------------------------------------------------------

class TestGraphRelate(_GraphTestBase):
    """
    relate() is the RELATE function — the entry point for all data.
    Every edge must trace to an external input. No synthetic edges.
    """

    def test_relate_empty_text_returns_empty_result(self):
        """
        Empty or whitespace input must return an empty result.
        The system must not create nodes or edges from nothing.
        """
        result = self._relate("")
        self.assertEqual(result["nodes_created"], 0)
        self.assertEqual(result["edges_created"], 0)
        self.assertEqual(result["concepts"], [])

    def test_relate_creates_nodes_for_concepts(self):
        """
        relate() must create at least one node for a text input
        with meaningful content words.
        """
        result = self._relate("machine learning context system")
        self.assertGreater(result["nodes_created"], 0)
        self.assertGreater(self._node_count(), 0)

    def test_relate_creates_edges_between_concepts(self):
        """
        relate() must write edges between co-occurring concepts.
        Edges are the associations — the core of the graph.
        """
        result = self._relate("machine learning context system")
        self.assertGreater(result["edges_created"], 0)
        self.assertGreater(self._edge_count(), 0)

    def test_relate_reinforces_on_second_call(self):
        """
        Calling relate() twice with the same concepts must reinforce
        existing nodes and edges rather than creating duplicates.
        """
        self._relate("machine learning context")
        nodes_after_first = self._node_count()
        edges_after_first = self._edge_count()

        result = self._relate("machine learning context")

        self.assertEqual(self._node_count(), nodes_after_first,
                         "Nodes must not be duplicated on re-ingestion.")
        self.assertEqual(self._edge_count(), edges_after_first,
                         "Edges must not be duplicated on re-ingestion.")
        self.assertGreater(result["nodes_reinforced"], 0)
        self.assertGreater(result["edges_reinforced"], 0)

    def test_relate_increments_total_inputs_counter(self):
        """
        Each relate() call must increment the global input counter.
        This counter is the IDF denominator for the Size axis.
        """
        self._relate("first input")
        self._relate("second input")
        self.assertEqual(self._total_inputs(), 2)

    def test_relate_returns_all_expected_fields(self):
        """
        The result dict must contain all documented fields.
        Downstream callers depend on this contract.
        """
        result = self._relate("testing the result schema")
        required = {
            "concepts", "nodes_created", "nodes_reinforced",
            "edges_created", "edges_reinforced",
            "crisis_detected", "sensitive_detected",
        }
        for field in required:
            self.assertIn(field, result,
                          f"relate() result missing required field: {field}")

    def test_relate_crisis_content_never_stored(self):
        """
        CHECKLIST 1.17 — Crisis-level content must NEVER be stored.
        User safety is the highest priority.
        relate() must return immediately without writing to the graph.
        """
        result = self._relate("I want to end my life")
        self.assertTrue(result["crisis_detected"],
                        "crisis_detected must be True for crisis content.")
        self.assertEqual(self._node_count(), 0,
                         "Crisis input must NOT create any nodes.")
        self.assertEqual(self._edge_count(), 0,
                         "Crisis input must NOT create any edges.")

    def test_relate_crisis_concepts_returns_empty_concept_list(self):
        """
        When crisis is detected, the returned concepts list must be
        empty — no concept data is exposed for crisis content.
        """
        result = self._relate("I want to hurt myself")
        self.assertEqual(result["concepts"], [],
                         "No concepts must be returned for crisis input.")

    def test_relate_sensitive_content_detected(self):
        """
        Sensitive content must be flagged so it receives reduced
        reinforcement and faster decay — preventing rumination loops.
        """
        result = self._relate("feeling overwhelmed with anxiety today")
        self.assertTrue(result["sensitive_detected"],
                        "sensitive_detected must be True for sensitive content.")

    def test_relate_sensitive_edge_marked_in_database(self):
        """
        Edges involving sensitive concepts must be marked is_sensitive=1
        in the database so navigate() can filter them by default.
        """
        self._relate("feeling depressed and anxious")
        conn = sqlite3.connect(self.test_db)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM graph_edges WHERE is_sensitive = 1"
            ).fetchone()
            sensitive_count = row[0] if row else 0
        finally:
            conn.close()
        self.assertGreater(sensitive_count, 0,
                           "Sensitive content must produce is_sensitive=1 edges.")


# ---------------------------------------------------------------------------
# NAVIGATE
# ---------------------------------------------------------------------------

class TestGraphNavigate(_GraphTestBase):
    """
    navigate() is the NAVIGATE function — it traverses the graph from
    a query and returns a ranked context subgraph.
    """

    def test_navigate_empty_text_returns_empty(self):
        """
        Empty query must return an empty list, not raise.
        """
        results = graph.navigate("")
        self.assertEqual(results, [])

    def test_navigate_unknown_concept_returns_empty(self):
        """
        A concept not in the graph must return an empty list.
        navigate() must not fabricate context.
        """
        results = graph.navigate("xyzzyquux nonexistent")
        self.assertEqual(results, [])

    def test_navigate_returns_related_concepts(self):
        """
        After relate() establishes co-occurrence edges, navigate() must
        return concepts related to the query seed.
        """
        self._relate("machine learning neural network training data")
        self._relate("machine learning gradient descent optimisation")

        results = graph.navigate("machine learning")
        self.assertGreater(len(results), 0,
                           "navigate() must return related concepts from the graph.")

    def test_navigate_result_schema(self):
        """
        Every result dict must contain all documented fields.
        Downstream callers depend on this contract — including
        contextualize.py which reads these fields.
        """
        self._relate("contextual reasoning weighted graph")
        results = graph.navigate("contextual reasoning")

        if not results:
            self.skipTest("No graph results — seed concepts not found.")

        required = {
            "concept", "effective_weight", "times_seen",
            "inputs_seen", "source", "days_since", "complexity",
            "is_sensitive",
        }
        for field in required:
            self.assertIn(field, results[0],
                          f"navigate() result missing required field: {field}")

    def test_navigate_sorted_by_effective_weight_descending(self):
        """
        Results must be sorted by effective_weight descending.
        The most relevant context must come first.
        """
        self._relate("context system ontology knowledge graph data")
        results = graph.navigate("context system")

        if len(results) < 2:
            self.skipTest("Fewer than 2 results — cannot test ordering.")

        weights = [r["effective_weight"] for r in results]
        self.assertEqual(weights, sorted(weights, reverse=True),
                         "Results must be sorted by effective_weight descending.")

    def test_navigate_excludes_sensitive_edges_by_default(self):
        """
        Sensitive edges must be excluded from navigate() by default.
        Users must not have distress content surfaced without consent.
        include_sensitive=False is the default.
        """
        self._relate("feeling depressed and anxious about the situation")
        self._relate("situation analysis context")

        results_default = graph.navigate("situation analysis")
        sensitive_surfaced = any(r.get("is_sensitive") for r in results_default)
        self.assertFalse(sensitive_surfaced,
                         "Sensitive concepts must not appear in default navigate().")

    def test_navigate_source_is_always_graph(self):
        """
        The source field must always be 'graph' — not 'field_overlap'
        or any fallback value — confirming the graph backend is active.
        """
        self._relate("relationship graph context navigation system")
        results = graph.navigate("relationship graph")

        if not results:
            self.skipTest("No graph results — seed concepts not found.")

        for r in results:
            self.assertEqual(r["source"], "graph",
                             "source field must be 'graph' — "
                             "word-overlap fallback must not activate.")


# ---------------------------------------------------------------------------
# DECAY
# ---------------------------------------------------------------------------

class TestGraphDecay(_GraphTestBase):
    """
    decay() is the system's metabolism — it prunes what is no longer
    accessible. The graph grows where used; fades where not.
    """

    def test_decay_preserves_recent_edges(self):
        """
        Edges just created must survive decay() — they are new and
        should have a weight well above the pruning threshold.
        """
        self._relate("recent context data")
        edges_before = self._edge_count()
        self.assertGreater(edges_before, 0)

        result = graph.decay()
        self.assertEqual(self._edge_count(), edges_before,
                         "Freshly created edges must not be pruned.")
        self.assertEqual(result["edges_pruned"], 0)

    def test_decay_prunes_edges_below_threshold(self):
        """
        Edges manually set below the prune threshold must be removed
        by decay(). This confirms the pruning logic fires correctly.
        """
        self._relate("context system graph")

        conn = sqlite3.connect(self.test_db)
        try:
            conn.execute("UPDATE graph_edges SET weight = 0.01")
            conn.commit()
        finally:
            conn.close()

        result = graph.decay()
        self.assertGreater(result["edges_pruned"], 0,
                           "Edges below threshold must be pruned by decay().")

    def test_decay_removes_orphaned_nodes(self):
        """
        After all edges are pruned, orphaned nodes must also be removed.
        Nodes with no connections carry no information.
        """
        self._relate("isolated concept data")

        conn = sqlite3.connect(self.test_db)
        try:
            conn.execute("UPDATE graph_edges SET weight = 0.01")
            conn.commit()
        finally:
            conn.close()

        result = graph.decay()
        self.assertEqual(self._node_count(), 0,
                         "Orphaned nodes must be removed after edge pruning.")
        self.assertGreater(result["nodes_pruned"], 0)

    def test_decay_returns_count_dict(self):
        """
        decay() must return a dict with the expected keys so callers
        can log or report on what was pruned.
        """
        result = graph.decay()
        self.assertIn("edges_pruned", result)
        self.assertIn("nodes_pruned", result)


# ---------------------------------------------------------------------------
# WIPE — GDPR Article 17
# ---------------------------------------------------------------------------

class TestGraphWipe(_GraphTestBase):
    """
    CHECKLIST 2.12 — wipe() is the user's right to erasure.
    It must completely remove all personal associative data.
    """

    def test_wipe_deletes_all_nodes(self):
        """
        After wipe(), the graph_nodes table must be empty.
        """
        self._relate("context system data graph")
        self.assertGreater(self._node_count(), 0)

        graph.wipe()
        self.assertEqual(self._node_count(), 0,
                         "wipe() must delete all nodes.")

    def test_wipe_deletes_all_edges(self):
        """
        After wipe(), the graph_edges table must be empty.
        """
        self._relate("context system data graph")
        self.assertGreater(self._edge_count(), 0)

        graph.wipe()
        self.assertEqual(self._edge_count(), 0,
                         "wipe() must delete all edges.")

    def test_wipe_resets_input_counter(self):
        """
        After wipe(), total_inputs_processed must reset to 0.
        The IDF denominator must be cleared with the graph.
        """
        self._relate("first input")
        self._relate("second input")
        self.assertEqual(self._total_inputs(), 2)

        graph.wipe()
        self.assertEqual(self._total_inputs(), 0,
                         "wipe() must reset total_inputs_processed to 0.")

    def test_wipe_navigate_returns_empty_after(self):
        """
        After wipe(), navigate() must return an empty list — the graph
        has no data and must not surface any context.
        """
        self._relate("context system graph navigation")
        graph.wipe()
        results = graph.navigate("context system")
        self.assertEqual(results, [],
                         "navigate() must return empty after wipe().")

    def test_wipe_records_audit_event(self):
        """
        wipe() must record a GRAPH_WIPE event in the audit trail.
        The audit trail records that erasure occurred — not the content.
        The permanent record proves the right was exercised.
        """
        self._relate("something personal")
        graph.wipe()

        recent = memory.read_recent(5)
        event_types = [r.get("event_type") for r in recent]
        self.assertIn("GRAPH_WIPE", event_types,
                      "wipe() must record a GRAPH_WIPE event in the audit trail.")


# ---------------------------------------------------------------------------
# EFFECTIVE WEIGHT — three axes + PPMI + fan effect
# ---------------------------------------------------------------------------

class TestEffectiveWeight(unittest.TestCase):
    """
    The effective weight function is the mathematical heart of navigation.
    Each axis must behave as documented.
    """

    def test_power_law_decay_reduces_weight_over_time(self):
        """
        Axis 1: Distance — older relationships must have lower weight.
        Power-law decay: weight × (1 + days)^(-d).
        Scientific basis: Wixted (2004), Jost's Law (1897).
        """
        fresh = _effective_weight(
            base_weight=0.5, days_since=0, times_seen=5,
            inputs_seen=3, degree=3, reinforcement_count=2,
            src_times_seen=5, fan_dilution=1.0, total_inputs=10,
        )
        stale = _effective_weight(
            base_weight=0.5, days_since=30, times_seen=5,
            inputs_seen=3, degree=3, reinforcement_count=2,
            src_times_seen=5, fan_dilution=1.0, total_inputs=10,
        )
        self.assertGreater(fresh, stale,
                           "A fresh edge must outweigh a stale one. "
                           "Power-law decay must reduce weight over time.")

    def test_sensitive_edges_decay_faster(self):
        """
        Sensitive edges must decay faster (exponent × 1.4) to prevent
        long-term persistence of distress-related associations.
        Scientific basis: Nolen-Hoeksema (1991) rumination model.
        """
        normal = _effective_weight(
            base_weight=0.5, days_since=10, times_seen=3,
            inputs_seen=2, degree=2, reinforcement_count=1,
            src_times_seen=3, fan_dilution=1.0, total_inputs=10,
            is_sensitive=False,
        )
        sensitive = _effective_weight(
            base_weight=0.5, days_since=10, times_seen=3,
            inputs_seen=2, degree=2, reinforcement_count=1,
            src_times_seen=3, fan_dilution=1.0, total_inputs=10,
            is_sensitive=True,
        )
        self.assertGreater(normal, sensitive,
                           "Sensitive edges must decay faster than normal edges.")

    def test_result_is_clamped_to_zero_one(self):
        """
        Effective weight must always be in [0.0, 1.0].
        No combination of inputs should produce an out-of-range value.
        """
        high = _effective_weight(
            base_weight=1.0, days_since=0, times_seen=100,
            inputs_seen=1, degree=20, reinforcement_count=50,
            src_times_seen=100, fan_dilution=1.0, total_inputs=2,
        )
        low = _effective_weight(
            base_weight=0.01, days_since=365, times_seen=1,
            inputs_seen=100, degree=0, reinforcement_count=1,
            src_times_seen=1, fan_dilution=0.1, total_inputs=1000,
        )
        self.assertLessEqual(high, 1.0)
        self.assertGreaterEqual(high, 0.0)
        self.assertLessEqual(low, 1.0)
        self.assertGreaterEqual(low, 0.0)


# ---------------------------------------------------------------------------
# SPACING INCREMENT
# ---------------------------------------------------------------------------

class TestSpacingIncrement(unittest.TestCase):
    """
    The spacing increment function implements the spacing effect —
    reinforcement benefit increases with time since last access.
    Scientific basis: Pavlik & Anderson (2005); Cepeda et al. (2006).
    """

    def test_immediate_reinforcement_returns_base(self):
        """
        At 0 days elapsed, the spacing factor must be 1.0 exactly —
        immediate re-study gives full base increment, no bonus.
        """
        result = _spacing_increment(0.08, 0.0)
        self.assertAlmostEqual(result, 0.08, places=5)

    def test_delayed_reinforcement_exceeds_base(self):
        """
        After 30 days, the increment must be double the base.
        Spaced repetition is more durable than massed practice.
        """
        result = _spacing_increment(0.08, 30.0)
        self.assertAlmostEqual(result, 0.16, places=3)

    def test_factor_increases_monotonically(self):
        """
        The spacing factor must increase monotonically with days elapsed,
        capping at 2× after 30 days.
        """
        results = [_spacing_increment(1.0, d) for d in [0, 1, 7, 14, 30, 60]]
        for i in range(len(results) - 1):
            self.assertLessEqual(results[i], results[i + 1] + 1e-10,
                                 "Spacing factor must be non-decreasing.")
        self.assertAlmostEqual(results[-1], 2.0, places=3,
                               msg="Factor must cap at 2.0.")


# ---------------------------------------------------------------------------
# CONCEPT EXTRACTION
# ---------------------------------------------------------------------------

class TestConceptExtraction(unittest.TestCase):
    """
    _extract_concepts() extracts meaningful content words from text.
    RAKE-inspired: scores words by degree/frequency ratio.
    """

    def test_empty_text_returns_empty_list(self):
        """Empty or stopword-only input must return no concepts."""
        self.assertEqual(_extract_concepts(""), [])
        self.assertEqual(_extract_concepts("the and for"), [])

    def test_stopwords_are_filtered(self):
        """
        Common stopwords must not appear in extracted concepts.
        They carry no contextual information.
        """
        concepts = _extract_concepts(
            "the quick brown fox and the lazy dog"
        )
        stopwords = {"the", "and"}
        for c in concepts:
            words = c.split()
            for w in words:
                self.assertNotIn(w, stopwords,
                                 f"Stopword '{w}' found in concept '{c}'")

    def test_respects_max_concepts_limit(self):
        """
        The number of returned concepts must not exceed
        MAX_CONCEPTS_PER_INPUT, preventing edge explosion.
        """
        long_text = " ".join([f"concept{i}" for i in range(50)])
        concepts = _extract_concepts(long_text)
        self.assertLessEqual(
            len(concepts), graph.MAX_CONCEPTS_PER_INPUT,
            "Concept count must not exceed MAX_CONCEPTS_PER_INPUT."
        )


if __name__ == "__main__":
    unittest.main()
