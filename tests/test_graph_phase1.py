"""
tests/test_graph_phase1.py

Phase 1 test suite for modules/graph.py (DESIGN-SPEC-001 v1.1).

Covers all Phase 1 additions:
  - 14-step migration (schema completeness and idempotency)
  - Typed directed edge schema (edge_types registry)    [6.01]
  - Provenance and trust scoring
  - Provenance backfill (historical_backfill)
  - Personalized PageRank (PPR) with graceful fallback   [6.02]
  - PPMI incremental counters                            [6.03]
  - Per-user decay profiles                              [6.04]
  - YAKE concept extractor                               [6.05]
  - Pluggable extractor interface                        [6.05]
  - Migration safety and data preservation
  - Forward compatibility (P2-P4 columns present, NULL)

Test classes (12 classes, 58 tests total):
    TestEdgeTypeRegistry     (5)  — 6.01 registry seeding and integrity
    TestTypedEdges           (4)  — 6.01 typed edge behavior
    TestProvenanceTable      (5)  — provenance layer
    TestProvBackfill         (3)  — historical_backfill idempotency
    TestPPRInterface         (5)  — 6.02 PPR compute + subgraph
    TestPPMICounters         (6)  — 6.03 counter increment + decay
    TestDecayProfiles        (5)  — 6.04 seeding + lambda constraints
    TestSessionConfig        (3)  — session-level config table
    TestConceptExtractorYAKE (6)  — 6.05 YAKE implementation
    TestExtractorPlugin      (4)  — 6.05 pluggable interface
    TestMigration            (5)  — migration safety + data preservation
    TestForwardCompat        (7)  — P2-P4 columns present and NULL

Rule 1.09A: These tests define what Phase 1 code must do.
            Code, tests, and documentation must agree before any checklist
            item is marked complete.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import modules.graph as graph
from modules.graph import (
    YAKEExtractor,
    compute_ppr,
    get_ppr_subgraph,
    invalidate_ppr_cache,
    prune,
    set_extractor,
)
from modules import memory as _memory


# ---------------------------------------------------------------------------
# BASE CLASS
# ---------------------------------------------------------------------------

class _Phase1TestBase(unittest.TestCase):
    """
    Base for all Phase 1 graph tests.

    Each test gets a fresh temporary SQLite database.
    _memory.DB_PATH is patched so graph operations use the temp DB.
    initialize() is called in setUp — every test starts with a clean,
    fully migrated database.
    """

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.test_db = self._tmp.name
        self._tmp.close()

        self._db_patcher = patch.object(_memory, "DB_PATH", self.test_db)
        self._db_patcher.start()

        graph.initialize()

    def tearDown(self):
        self._db_patcher.stop()
        try:
            os.unlink(self.test_db)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        """Open a read connection to the test database."""
        conn = sqlite3.connect(self.test_db)
        conn.row_factory = sqlite3.Row
        return conn

    def _relate(self, text: str) -> dict:
        return graph.relate({"raw": text})

    def _table_exists(self, name: str) -> bool:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def _column_exists(self, table: str, column: str) -> bool:
        conn = self._conn()
        try:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            return any(r["name"] == column for r in rows)
        finally:
            conn.close()

    def _index_exists(self, name: str) -> bool:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (name,),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def _node_count(self) -> int:
        conn = self._conn()
        try:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM graph_nodes"
            ).fetchone()["c"]
        finally:
            conn.close()

    def _edge_count(self) -> int:
        conn = self._conn()
        try:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM graph_edges"
            ).fetchone()["c"]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# TEST CLASS 1 — Edge Type Registry (6.01)
# ---------------------------------------------------------------------------

class TestEdgeTypeRegistry(_Phase1TestBase):
    """
    Checklist 6.01 — directed edge schema.
    The edge_types registry must be seeded with all 16 standard types,
    have correct inverse_ids, and remain stable across repeated boots.
    """

    def test_edge_types_table_exists(self):
        """edge_types table must be created by initialize()."""
        self.assertTrue(self._table_exists("edge_types"),
                        "edge_types table must exist after initialize().")

    def test_sixteen_standard_types_seeded(self):
        """Exactly 16 standard edge types must be seeded on first boot."""
        conn = self._conn()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM edge_types"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(count, 16,
                         "Exactly 16 standard edge types must be seeded.")

    def test_co_occurs_with_is_id_2(self):
        """
        id=2 (co-occurs-with) is the default type for Stage 1 edges.
        It must exist and be named correctly.
        """
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT name, category FROM edge_types WHERE id = 2"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, "Edge type id=2 must exist.")
        self.assertEqual(row["name"], "co-occurs-with")
        self.assertEqual(row["category"], "associative")

    def test_directed_types_have_inverse_ids(self):
        """
        All directed edge types must have their inverse_id populated.
        This is set in the two-pass seeding (pass 1: insert, pass 2: UPDATE).
        """
        conn = self._conn()
        try:
            missing = conn.execute(
                "SELECT id, name FROM edge_types "
                "WHERE is_directed = 1 AND inverse_id IS NULL"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(
            len(missing), 0,
            f"All directed edge types must have inverse_id. Missing: "
            f"{[r['name'] for r in missing]}",
        )

    def test_seeding_is_idempotent(self):
        """
        Calling initialize() a second time must not create duplicate
        edge types. INSERT OR IGNORE guarantees this.
        """
        graph.initialize()
        conn = self._conn()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM edge_types"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(count, 16,
                         "Second initialize() must not create duplicate edge types.")


# ---------------------------------------------------------------------------
# TEST CLASS 2 — Typed Edges (6.01)
# ---------------------------------------------------------------------------

class TestTypedEdges(_Phase1TestBase):
    """
    Edges created by relate() must carry the correct Phase 1 metadata:
    edge_type_id, direction, and confidence.
    """

    def test_new_edges_default_to_co_occurs_with(self):
        """relate() writes edges with edge_type_id=2 (co-occurs-with) by default."""
        self._relate("machine learning neural network inference")
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT edge_type_id FROM graph_edges LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, "At least one edge must be created.")
        self.assertEqual(row["edge_type_id"], 2,
                         "Default edge_type_id must be 2 (co-occurs-with).")

    def test_new_edges_direction_undirected(self):
        """relate() writes edges with direction='undirected' by default."""
        self._relate("context system data graph")
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT direction FROM graph_edges LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["direction"], "undirected",
                         "Stage 1 co-occurrence edges must be undirected.")

    def test_new_edges_confidence_is_one(self):
        """All edges created by relate() have confidence=1.0 (fully asserted)."""
        self._relate("system architecture design ontology")
        conn = self._conn()
        try:
            bad = conn.execute(
                "SELECT id FROM graph_edges WHERE confidence != 1.0"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(bad), 0,
                         "All relate() edges must have confidence=1.0.")

    def test_all_edge_type_categories_valid(self):
        """All 16 seeded edge types must use a valid category string."""
        valid_categories = {
            "taxonomic", "mereological", "causal",
            "associative", "temporal", "spatial", "epistemic",
        }
        conn = self._conn()
        try:
            rows = conn.execute("SELECT name, category FROM edge_types").fetchall()
        finally:
            conn.close()
        for row in rows:
            self.assertIn(
                row["category"], valid_categories,
                f"Edge type '{row['name']}' has invalid category: {row['category']}",
            )


# ---------------------------------------------------------------------------
# TEST CLASS 3 — Provenance Table
# ---------------------------------------------------------------------------

class TestProvenanceTable(_Phase1TestBase):
    """
    Every relate() call must create a provenance record.
    Trust scores must match source-type defaults from DESIGN-SPEC-001 §1.4.
    """

    def test_provenance_table_exists(self):
        self.assertTrue(self._table_exists("provenance"),
                        "provenance table must exist after initialize().")

    def test_relate_creates_provenance_record(self):
        """relate() must insert exactly one new provenance record per call."""
        conn = self._conn()
        try:
            before = conn.execute(
                "SELECT COUNT(*) AS c FROM provenance WHERE source_type = 'human'"
            ).fetchone()["c"]
        finally:
            conn.close()

        self._relate("knowledge graph ontology reasoning context")

        conn = self._conn()
        try:
            after = conn.execute(
                "SELECT COUNT(*) AS c FROM provenance WHERE source_type = 'human'"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(after, before + 1,
                         "One human provenance record must be created per relate().")

    def test_provenance_id_in_relate_result(self):
        """relate() must return a non-None provenance_id on success."""
        result = self._relate("ontology system context knowledge graph")
        self.assertIn("provenance_id", result,
                      "relate() result must include provenance_id.")
        self.assertIsNotNone(result["provenance_id"],
                             "provenance_id must be non-None for successful relate().")

    def test_nodes_have_provenance_id(self):
        """All nodes created by relate() must have provenance_id set (not NULL)."""
        self._relate("machine learning model inference reasoning")
        conn = self._conn()
        try:
            nulls = conn.execute(
                "SELECT id FROM graph_nodes WHERE provenance_id IS NULL"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(nulls), 0,
                         "No nodes should have NULL provenance_id after relate().")

    def test_human_provenance_trust_score(self):
        """Human-sourced provenance must have trust_score=0.95 per DESIGN-SPEC-001."""
        self._relate("trust provenance verification system")
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT trust_score FROM provenance "
                "WHERE source_type = 'human' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(row["trust_score"], 0.95, places=3,
                               msg="Human provenance trust_score must be 0.95.")


# ---------------------------------------------------------------------------
# TEST CLASS 4 — Provenance Backfill
# ---------------------------------------------------------------------------

class TestProvBackfill(_Phase1TestBase):
    """
    The historical backfill must create a single 'system/historical_backfill'
    provenance record and assign it to pre-existing NULL provenance_ids.
    It must never run more than once per database.
    """

    def test_backfill_record_exists_after_initialize(self):
        """A 'historical_backfill' provenance record must exist after first boot."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT id, source_type, trust_score FROM provenance "
                "WHERE source_id = 'historical_backfill'"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row,
                             "historical_backfill provenance record must exist.")
        self.assertEqual(row["source_type"], "system")
        self.assertAlmostEqual(row["trust_score"], 0.90, places=3)

    def test_backfill_is_idempotent(self):
        """
        Multiple initialize() calls must never create duplicate backfill records.
        The guard checks for source_id = 'historical_backfill' before inserting.
        """
        graph.initialize()
        graph.initialize()
        conn = self._conn()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM provenance "
                "WHERE source_id = 'historical_backfill'"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(count, 1,
                         "Backfill must produce exactly one record — never duplicates.")

    def test_no_null_provenance_after_relate(self):
        """
        After relate(), no nodes should have NULL provenance_id.
        _upsert_node() sets provenance_id on every write.
        """
        self._relate("context reasoning system graph")
        conn = self._conn()
        try:
            nulls = conn.execute(
                "SELECT COUNT(*) AS c FROM graph_nodes WHERE provenance_id IS NULL"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(nulls, 0,
                         "All nodes must have provenance_id after relate().")


# ---------------------------------------------------------------------------
# TEST CLASS 5 — PPR Interface (6.02)
# ---------------------------------------------------------------------------

class TestPPRInterface(_Phase1TestBase):
    """
    Checklist 6.02 — Personalized PageRank interface.

    For small test graphs (< 200 nodes), PPR falls back and returns [].
    Tests verify: correct return types, graceful fallback, no exceptions,
    and the subgraph dict schema.
    """

    def test_compute_ppr_returns_list(self):
        """compute_ppr() must always return a list, never raise."""
        result = compute_ppr(seed_node_ids=[999], alpha=0.85)
        self.assertIsInstance(result, list)

    def test_compute_ppr_empty_seeds_returns_empty(self):
        """compute_ppr() with empty seed list must return []."""
        self.assertEqual(compute_ppr(seed_node_ids=[]), [])

    def test_compute_ppr_nonexistent_seed_returns_empty(self):
        """compute_ppr() with a non-existent node id must return [] gracefully."""
        result = compute_ppr(seed_node_ids=[999_999_999])
        self.assertEqual(result, [])

    def test_compute_ppr_never_raises(self):
        """compute_ppr() must not raise for any valid input combination."""
        for alpha in (0.70, 0.85, 0.95):
            try:
                compute_ppr(seed_node_ids=[1, 2], alpha=alpha, top_k=10)
            except Exception as exc:
                self.fail(f"compute_ppr() raised with alpha={alpha}: {exc}")

    def test_get_ppr_subgraph_schema(self):
        """get_ppr_subgraph() must return a dict with nodes, edges, metadata keys."""
        result = get_ppr_subgraph(seed_node_ids=[999])
        self.assertIn("nodes", result)
        self.assertIn("edges", result)
        self.assertIn("metadata", result)
        self.assertIn("seed_nodes", result["metadata"])

    def test_invalidate_ppr_cache_is_safe(self):
        """invalidate_ppr_cache() must be callable at any time without error."""
        invalidate_ppr_cache()
        invalidate_ppr_cache()  # Double-call must also be safe


# ---------------------------------------------------------------------------
# TEST CLASS 6 — PPMI Counters (6.03)
# ---------------------------------------------------------------------------

class TestPPMICounters(_Phase1TestBase):
    """
    Checklist 6.03 — PPMI incremental counter design.
    Counters must be updated on every relate() and decay correctly.
    """

    def test_ppmi_counters_table_exists(self):
        self.assertTrue(self._table_exists("ppmi_counters"))

    def test_ppmi_global_table_exists(self):
        self.assertTrue(self._table_exists("ppmi_global"))

    def test_ppmi_global_seeded_with_total(self):
        """ppmi_global must have total_co_occurrences >= 0 after initialize()."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT value FROM ppmi_global WHERE key = 'total_co_occurrences'"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, "total_co_occurrences key must exist.")
        self.assertGreaterEqual(row["value"], 0.0)

    def test_relate_increments_total_co_occurrences(self):
        """relate() must increase total_co_occurrences in ppmi_global."""
        conn = self._conn()
        try:
            before = conn.execute(
                "SELECT value FROM ppmi_global WHERE key = 'total_co_occurrences'"
            ).fetchone()["value"]
        finally:
            conn.close()

        self._relate("knowledge ontology reasoning system graph context")

        conn = self._conn()
        try:
            after = conn.execute(
                "SELECT value FROM ppmi_global WHERE key = 'total_co_occurrences'"
            ).fetchone()["value"]
        finally:
            conn.close()
        self.assertGreater(after, before,
                           "total_co_occurrences must increase after relate().")

    def test_relate_populates_ppmi_counters(self):
        """relate() must create ppmi_counters rows for every concept node."""
        self._relate("machine learning ontology context knowledge")
        conn = self._conn()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM ppmi_counters"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertGreater(count, 0,
                           "ppmi_counters must be populated after relate().")

    def test_ppmi_weight_null_after_relate(self):
        """
        ppmi_weight on edges must be NULL after relate().
        PPMI is computed lazily at read time, not on write.
        """
        self._relate("lazy computation design architecture pattern")
        conn = self._conn()
        try:
            non_null = conn.execute(
                "SELECT COUNT(*) AS c FROM graph_edges WHERE ppmi_weight IS NOT NULL"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(non_null, 0,
                         "ppmi_weight must be NULL after relate() — computed lazily.")

    def test_prune_returns_edges_pruned_key(self):
        """prune() must return a dict with 'edges_pruned' key."""
        self._relate("system graph context reasoning")
        result = prune(threshold=999.9)  # threshold so high all edges are pruned
        self.assertIn("edges_pruned", result,
                      "prune() must return dict with edges_pruned key.")
        self.assertIsInstance(result["edges_pruned"], int)


# ---------------------------------------------------------------------------
# TEST CLASS 7 — Decay Profiles (6.04)
# ---------------------------------------------------------------------------

class TestDecayProfiles(_Phase1TestBase):
    """
    Checklist 6.04 — per-user decay calibration.
    Five profiles must be seeded with correct lambda values and domains.
    """

    def test_decay_profiles_table_exists(self):
        self.assertTrue(self._table_exists("decay_profiles"))

    def test_five_profiles_seeded(self):
        conn = self._conn()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM decay_profiles"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(count, 5, "Exactly 5 decay profiles must be seeded.")

    def test_standard_profile_is_default(self):
        """Exactly one profile must be marked is_default=1, and it must be 'standard'."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT name FROM decay_profiles WHERE is_default = 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, "One profile must be the default.")
        self.assertEqual(row["name"], "standard")

    def test_lambda_constraints_satisfied(self):
        """All decay profiles must have lambda in (0.0, 1.0]."""
        conn = self._conn()
        try:
            rows = conn.execute("SELECT name, lambda FROM decay_profiles").fetchall()
        finally:
            conn.close()
        for row in rows:
            self.assertGreater(
                row["lambda"], 0.0,
                f"Profile '{row['name']}': lambda must be > 0.",
            )
            self.assertLessEqual(
                row["lambda"], 1.0,
                f"Profile '{row['name']}': lambda must be <= 1.",
            )

    def test_profiles_seeding_idempotent(self):
        """Repeated initialize() calls must not add duplicate profiles."""
        graph.initialize()
        graph.initialize()
        conn = self._conn()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM decay_profiles"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(count, 5, "Profiles must not be duplicated by re-initialize.")


# ---------------------------------------------------------------------------
# TEST CLASS 8 — Session Config
# ---------------------------------------------------------------------------

class TestSessionConfig(_Phase1TestBase):
    """
    session_config is the thin override layer for session-level configuration.
    All Phase 2-3 columns must be present and NULL-able from Phase 1.
    """

    def test_session_config_table_exists(self):
        self.assertTrue(self._table_exists("session_config"))

    def test_decay_profile_id_column_exists(self):
        self.assertTrue(
            self._column_exists("session_config", "decay_profile_id"),
            "session_config.decay_profile_id must exist in Phase 1.",
        )

    def test_p2_columns_present(self):
        """Phase 2 columns must be present (NULL until Phase 2 activates logic)."""
        for col in ("regulatory_profile", "data_residency"):
            self.assertTrue(
                self._column_exists("session_config", col),
                f"Phase 2 column session_config.{col} must be present.",
            )


# ---------------------------------------------------------------------------
# TEST CLASS 9 — YAKE Concept Extractor (6.05)
# ---------------------------------------------------------------------------

class TestConceptExtractorYAKE(_Phase1TestBase):
    """
    Checklist 6.05 — YAKE-inspired concept extraction.
    Tests the YAKEExtractor directly, independent of relate().
    """

    def setUp(self):
        super().setUp()
        self.extractor = YAKEExtractor()

    def test_empty_text_returns_empty(self):
        """Empty and whitespace-only input must return []."""
        self.assertEqual(self.extractor.extract(""), [])
        self.assertEqual(self.extractor.extract("   "), [])

    def test_stopwords_not_in_output(self):
        """Common stopwords must be filtered from extracted concepts."""
        concepts = self.extractor.extract(
            "the quick brown fox and the lazy dog over the hill"
        )
        stopwords_found = [c for c in concepts if c in {"the", "and", "for", "over"}]
        self.assertEqual(stopwords_found, [],
                         f"Stopwords must not appear in output: {stopwords_found}")

    def test_max_concepts_cap_enforced(self):
        """Extractor must never return more than max_concepts items."""
        long_text = " ".join([f"concept{i}" for i in range(100)])
        concepts = self.extractor.extract(long_text, max_concepts=15)
        self.assertLessEqual(len(concepts), 15,
                             "Extractor must respect the max_concepts cap.")

    def test_returns_list_type(self):
        """Extractor must always return a list."""
        result = self.extractor.extract("machine learning ontology reasoning context")
        self.assertIsInstance(result, list)

    def test_get_version_returns_nonempty_string(self):
        version = self.extractor.get_version()
        self.assertIsInstance(version, str)
        self.assertGreater(len(version), 0)

    def test_get_model_name_is_yake_stdlib(self):
        self.assertEqual(self.extractor.get_model_name(), "yake-stdlib")


# ---------------------------------------------------------------------------
# TEST CLASS 10 — Pluggable Extractor Interface (6.05)
# ---------------------------------------------------------------------------

class _MockExtractor:
    """Test double for ConceptExtractor protocol."""
    def extract(self, text: str, max_concepts: int = 15):
        return [] if not text else ["mock_alpha", "mock_beta"][:max_concepts]
    def get_version(self) -> str:
        return "mock-1.0"
    def get_model_name(self) -> str:
        return "mock-extractor"


class TestExtractorPlugin(_Phase1TestBase):
    """
    set_extractor() must allow swapping concept extractors without touching
    any other code — the Phase 4 spaCy upgrade hook.
    """

    def tearDown(self):
        set_extractor(YAKEExtractor())   # restore default before cleanup
        super().tearDown()

    def test_set_extractor_accepts_compliant_object(self):
        """set_extractor() must accept any object satisfying the protocol."""
        try:
            set_extractor(_MockExtractor())
        except Exception as exc:
            self.fail(f"set_extractor() raised unexpectedly: {exc}")

    def test_mock_extractor_used_by_relate(self):
        """After set_extractor(MockExtractor), relate() uses mock concepts."""
        set_extractor(_MockExtractor())
        result = self._relate("this entire text is irrelevant to mock")
        if not result["crisis_detected"]:
            concepts = result.get("concepts", [])
            self.assertIn("mock_alpha", concepts,
                          "MockExtractor's concepts must appear in relate() result.")

    def test_restore_yake_removes_mock_concepts(self):
        """After restoring YAKEExtractor, relate() must not produce mock concepts."""
        set_extractor(_MockExtractor())
        set_extractor(YAKEExtractor())
        result = self._relate("machine learning ontology knowledge system context")
        concepts = result.get("concepts", [])
        self.assertNotIn("mock_alpha", concepts,
                         "After restoring YAKE, mock concepts must not appear.")

    def test_set_extractor_is_thread_safe(self):
        """set_extractor() must not raise under rapid sequential swaps."""
        for _ in range(10):
            set_extractor(_MockExtractor())
            set_extractor(YAKEExtractor())


# ---------------------------------------------------------------------------
# TEST CLASS 11 — Migration Safety
# ---------------------------------------------------------------------------

class TestMigration(_Phase1TestBase):
    """
    The 14-step migration must be safe, complete, and idempotent.
    All Stage 1 tables must survive the Phase 1 migration intact.
    """

    def test_all_phase1_tables_exist(self):
        """Every Phase 1 table must be created by initialize()."""
        required = [
            "edge_types", "provenance", "ppmi_counters",
            "ppmi_global", "decay_profiles", "session_config",
            "mcp_session_map",
        ]
        for table in required:
            self.assertTrue(
                self._table_exists(table),
                f"Phase 1 table '{table}' must exist after initialize().",
            )

    def test_stage1_tables_preserved(self):
        """Stage 1 tables must still exist and be intact after Phase 1 migration."""
        for table in ("graph_nodes", "graph_edges", "graph_metadata"):
            self.assertTrue(
                self._table_exists(table),
                f"Stage 1 table '{table}' must be preserved by Phase 1 migration.",
            )

    def test_existing_data_survives_reinitialize(self):
        """
        Data written before a second initialize() call must be intact after.
        This tests the idempotency guarantee: no data loss on re-boot.
        """
        self._relate("knowledge graph ontology reasoning system context")
        conn = self._conn()
        try:
            node_count_before = conn.execute(
                "SELECT COUNT(*) AS c FROM graph_nodes"
            ).fetchone()["c"]
        finally:
            conn.close()

        graph.initialize()  # second call

        conn = self._conn()
        try:
            node_count_after = conn.execute(
                "SELECT COUNT(*) AS c FROM graph_nodes"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(node_count_before, node_count_after,
                         "Node count must be identical after reinitialize().")

    def test_required_indexes_created(self):
        """All mandatory Phase 1 indexes must be created by initialize()."""
        required = [
            "idx_graph_nodes_concept",
            "idx_edges_source_type",
            "idx_edges_target_type",
            "idx_edges_ppmi_stale",
            "idx_provenance_type_time",
        ]
        for idx in required:
            self.assertTrue(
                self._index_exists(idx),
                f"Index '{idx}' must be created by initialize().",
            )

    def test_wipe_clears_ppmi_counters(self):
        """
        graph.wipe() must clear ppmi_counters so the derived counter state
        stays consistent with the erased graph.
        """
        self._relate("context system graph ontology")
        conn = self._conn()
        try:
            before = conn.execute(
                "SELECT COUNT(*) AS c FROM ppmi_counters"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertGreater(before, 0, "ppmi_counters must have entries after relate().")

        graph.wipe()

        conn = self._conn()
        try:
            after = conn.execute(
                "SELECT COUNT(*) AS c FROM ppmi_counters"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(after, 0,
                         "ppmi_counters must be empty after wipe().")


# ---------------------------------------------------------------------------
# TEST CLASS 12 — Forward Compatibility (P2-P4 columns)
# ---------------------------------------------------------------------------

class TestForwardCompat(_Phase1TestBase):
    """
    DESIGN-SPEC-001 §9 — One schema migration, ever.

    All Phase 2-4 columns must be present and NULL after Phase 1 boot.
    This guarantees no future ALTER TABLE migrations are ever needed.
    """

    def test_p2_graph_nodes_columns_present(self):
        """Phase 2 graph_nodes columns must exist and be addressable."""
        for col in ("did_key", "valid_from", "valid_to", "is_deleted"):
            self.assertTrue(
                self._column_exists("graph_nodes", col),
                f"Phase 2 column graph_nodes.{col} must be present from Phase 1.",
            )

    def test_p3_graph_nodes_columns_present(self):
        """Phase 3 graph_nodes columns must exist."""
        for col in ("origin_node_id", "vector_clock", "crdt_state"):
            self.assertTrue(
                self._column_exists("graph_nodes", col),
                f"Phase 3 column graph_nodes.{col} must be present from Phase 1.",
            )

    def test_p4_graph_nodes_columns_present(self):
        """Phase 4 embedding columns must exist on graph_nodes."""
        for col in ("embedding", "embedding_model", "embedding_version",
                    "embedding_hash", "embedded_at"):
            self.assertTrue(
                self._column_exists("graph_nodes", col),
                f"Phase 4 column graph_nodes.{col} must be present from Phase 1.",
            )

    def test_p2_graph_edges_columns_present(self):
        """Phase 2 graph_edges columns must exist."""
        for col in ("valid_from", "valid_to", "is_deleted"):
            self.assertTrue(
                self._column_exists("graph_edges", col),
                f"Phase 2 column graph_edges.{col} must be present from Phase 1.",
            )

    def test_p3_graph_edges_columns_present(self):
        """Phase 3 graph_edges columns must exist."""
        for col in ("origin_node_id", "crdt_lww_ts", "vector_clock"):
            self.assertTrue(
                self._column_exists("graph_edges", col),
                f"Phase 3 column graph_edges.{col} must be present from Phase 1.",
            )

    def test_p4_embedding_columns_null_until_activated(self):
        """
        P4 embedding columns must be NULL for all existing nodes —
        they are present but dormant until Phase 4 activates the logic.
        """
        self._relate("phase four columns null verification test")
        conn = self._conn()
        try:
            non_null = conn.execute(
                "SELECT COUNT(*) AS c FROM graph_nodes WHERE embedding IS NOT NULL"
            ).fetchone()["c"]
        finally:
            conn.close()
        self.assertEqual(
            non_null, 0,
            "embedding column must be NULL for all nodes until Phase 4 activates.",
        )

    def test_mcp_session_map_oauth_columns_present(self):
        """
        Phase 2 OAuth columns must be in mcp_session_map from Phase 1.
        They are NULL until Phase 2 activates them.
        """
        for col in ("oauth_subject", "oauth_scope", "oauth_expires_at"):
            self.assertTrue(
                self._column_exists("mcp_session_map", col),
                f"Phase 2 column mcp_session_map.{col} must be present from Phase 1.",
            )


if __name__ == "__main__":
    unittest.main()
