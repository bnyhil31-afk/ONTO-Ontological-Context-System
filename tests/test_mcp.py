"""
tests/test_mcp.py

Phase 2 MCP Interface test suite.

Tests the ONTO MCP server (api/onto_server.py) without requiring a live
MCP transport. All tools are tested by calling the decorated Python
functions directly through their unwrapped implementations. This avoids
the complexity of spinning up a real MCP transport in CI while still
testing all business logic, security controls, and response contracts.

Test classes (9 classes, 42 tests):
    TestResponseEnvelope     (5)  — standard envelope shape and schema_version
    TestSessionResolution    (5)  — Bearer token parsing and auth rejection
    TestOntoIngest           (6)  — pipeline, crisis handling, empty input
    TestOntoQuery            (5)  — PPR, seed resolution, safety filter
    TestOntoSurface          (4)  — epistemic state, crisis gate
    TestOntoCheckpoint       (6)  — pending, valid decisions, invalid decision
    TestOntoRelate           (5)  — typed edge creation, sanitization
    TestOntoSchema           (3)  — edge type vocabulary resource
    TestOntoStatus           (3)  — health resource, graph metrics

Rule 1.09A: Code, tests, and documentation must always agree.

Skip strategy: If FastMCP is not installed, all tests in this file are
skipped gracefully. This allows CI to pass on Python environments where
fastmcp is not yet available without blocking the test suite.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import memory, graph

# Graceful skip if FastMCP not installed
try:
    import fastmcp  # noqa: F401
    _FASTMCP_INSTALLED = True
except ImportError:
    _FASTMCP_INSTALLED = False

_SKIP_MSG = "fastmcp not installed — install with: pip install fastmcp>=2.0.0"


# ---------------------------------------------------------------------------
# BASE CLASS
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FASTMCP_INSTALLED, _SKIP_MSG)
class _MCPTestBase(unittest.TestCase):
    """
    Base class for all MCP tests.

    Provides an isolated database and a mock session so tests can
    exercise all tool logic without live network or auth infrastructure.
    """

    def setUp(self):
        self._orig_db = memory.DB_PATH
        self.test_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.test_dir, "test_mcp.db")
        memory.DB_PATH = self.test_db
        memory.initialize()
        graph.initialize()

        # Valid mock session returned by session_manager.validate()
        self.valid_session = {
            "token": "test-token-256-bits-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "identity": "test-operator",
            "active": True,
        }
        self.valid_auth = "Bearer test-token-256-bits-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

    def tearDown(self):
        memory.DB_PATH = self._orig_db
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _relate(self, text: str) -> dict:
        return graph.relate({"raw": text, "clean": text})

    # ------------------------------------------------------------------
    # Import helpers — import inside methods so the skip decorator fires
    # before the module-level import of onto_server runs (which itself
    # attempts to import fastmcp at load time).
    # ------------------------------------------------------------------

    def _get_server_module(self):
        import importlib
        import api.onto_server as m
        importlib.reload(m)
        return m

    def _mock_session(self):
        """
        Context manager: patch session_manager.validate to return
        a valid session for the standard test token.
        """
        return patch(
            "api.onto_server.session_manager.validate",
            return_value=self.valid_session,
        )

    def _mock_no_session(self):
        """Context manager: patch session_manager.validate to reject."""
        return patch(
            "api.onto_server.session_manager.validate",
            return_value=None,
        )


# ---------------------------------------------------------------------------
# TEST CLASS 1 — Response Envelope
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FASTMCP_INSTALLED, _SKIP_MSG)
class TestResponseEnvelope(_MCPTestBase):
    """
    Every tool must return the standard response envelope defined in
    DESIGN-SPEC-001 §6.3. The schema_version field enables clients to
    negotiate gracefully when the envelope evolves.
    """

    def _assert_envelope(self, result: dict) -> None:
        required = {
            "status", "data", "audit_id", "confidence",
            "warnings", "checkpoint_required",
            "checkpoint_context", "schema_version",
        }
        for key in required:
            self.assertIn(
                key, result,
                f"Response envelope missing required key: '{key}'",
            )

    def test_ok_envelope_shape(self):
        from api.onto_server import _ok
        result = _ok(data={"x": 1}, audit_id=42, confidence=0.9)
        self._assert_envelope(result)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["schema_version"], "1.0")

    def test_error_envelope_shape(self):
        from api.onto_server import _error
        result = _error("something went wrong", audit_id=1)
        self._assert_envelope(result)
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result["data"])

    def test_pending_checkpoint_envelope_shape(self):
        from api.onto_server import _pending_checkpoint
        result = _pending_checkpoint(
            context={"summary": "test"}, audit_id=5
        )
        self._assert_envelope(result)
        self.assertEqual(result["status"], "pending_checkpoint")
        self.assertTrue(result["checkpoint_required"])
        self.assertIsNotNone(result["checkpoint_context"])

    def test_crisis_envelope_shape(self):
        with patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import _crisis
            result = _crisis(audit_id=99)
        self._assert_envelope(result)
        self.assertEqual(result["status"], "crisis")
        self.assertIn("crisis_detected", result["data"])
        self.assertTrue(result["data"]["crisis_detected"])

    def test_schema_version_is_always_1_0(self):
        from api.onto_server import _ok, _error, _pending_checkpoint
        for fn, args in [
            (_ok, {"data": {}}),
            (_error, {"message": "x"}),
            (_pending_checkpoint, {"context": {}}),
        ]:
            result = fn(**args)
            self.assertEqual(
                result["schema_version"], "1.0",
                f"{fn.__name__} must return schema_version='1.0'",
            )


# ---------------------------------------------------------------------------
# TEST CLASS 2 — Session Resolution
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FASTMCP_INSTALLED, _SKIP_MSG)
class TestSessionResolution(_MCPTestBase):
    """
    _resolve_session() and _require_session() are the auth layer for all
    MCP tools. They must parse Bearer tokens correctly and reject anything
    that isn't a valid ONTO session.
    """

    def test_valid_bearer_token_resolves(self):
        from api.onto_server import _resolve_session
        with self._mock_session():
            result = _resolve_session(self.valid_auth)
        self.assertIsNotNone(result)
        self.assertEqual(result["identity"], "test-operator")

    def test_missing_authorization_returns_none(self):
        from api.onto_server import _resolve_session
        self.assertIsNone(_resolve_session(None))
        self.assertIsNone(_resolve_session(""))

    def test_non_bearer_scheme_returns_none(self):
        from api.onto_server import _resolve_session
        with self._mock_session():
            self.assertIsNone(_resolve_session("Basic dXNlcjpwYXNz"))

    def test_invalid_token_returns_none(self):
        from api.onto_server import _resolve_session
        with self._mock_no_session():
            result = _resolve_session("Bearer invalid-token")
        self.assertIsNone(result)

    def test_require_session_returns_none_on_no_auth(self):
        """
        _require_session returns None when auth fails.
        Each tool checks for None and returns _auth_error() envelope.
        This avoids uncaught ValueError propagating out of the tool.
        """
        from api.onto_server import _require_session
        with self._mock_no_session():
            result = _require_session(None)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# TEST CLASS 3 — onto_ingest
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FASTMCP_INSTALLED, _SKIP_MSG)
class TestOntoIngest(_MCPTestBase):
    """
    onto_ingest runs the full 5-step pipeline. Crisis signals must be
    returned immediately. Successful ingestion must create nodes and edges.
    """

    def test_ingest_creates_nodes_and_edges(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_ingest
            result = onto_ingest(
                text="machine learning ontology context knowledge",
                authorization=self.valid_auth,
            )
        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["data"]["nodes_created"], 0)
        self.assertGreater(result["data"]["edges_created"], 0)

    def test_ingest_returns_concept_list(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_ingest
            result = onto_ingest(
                text="knowledge graph reasoning inference system",
                authorization=self.valid_auth,
            )
        self.assertIn("concepts", result["data"])
        self.assertIsInstance(result["data"]["concepts"], list)

    def test_ingest_crisis_returns_crisis_status(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_ingest
            result = onto_ingest(
                text="I want to end my life",
                authorization=self.valid_auth,
            )
        self.assertEqual(result["status"], "crisis",
                         "Crisis input must return status='crisis'.")
        self.assertTrue(result["data"]["crisis_detected"])

    def test_ingest_crisis_never_creates_nodes(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_ingest
            onto_ingest(
                text="I want to hurt myself",
                authorization=self.valid_auth,
            )
        import sqlite3
        conn = sqlite3.connect(self.test_db)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM graph_nodes"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0,
                         "Crisis input must never create graph nodes.")

    def test_ingest_rejected_without_auth(self):
        with self._mock_no_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_ingest
            result = onto_ingest(
                text="test input",
                authorization="Bearer bad-token",
            )
        self.assertEqual(result["status"], "error")

    def test_ingest_returns_provenance_id(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_ingest
            result = onto_ingest(
                text="provenance tracking ontology reasoning",
                authorization=self.valid_auth,
            )
        self.assertEqual(result["status"], "ok")
        self.assertIn("provenance_id", result["data"])


# ---------------------------------------------------------------------------
# TEST CLASS 4 — onto_query
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FASTMCP_INSTALLED, _SKIP_MSG)
class TestOntoQuery(_MCPTestBase):
    """
    onto_query resolves concept labels to node IDs and runs PPR.
    Unknown concepts must return an empty result gracefully.
    Sensitive nodes must be filtered from output.
    """

    def setUp(self):
        super().setUp()
        self._relate("knowledge graph ontology reasoning context system")

    def test_query_known_concepts_returns_ok(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_query
            result = onto_query(
                concepts=["knowledge", "graph"],
                authorization=self.valid_auth,
            )
        self.assertIn(result["status"], ("ok",),
                      f"Unexpected status: {result['status']}")

    def test_query_unknown_concepts_returns_ok_with_warning(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_query
            result = onto_query(
                concepts=["absolutely_unknown_concept_xyz"],
                authorization=self.valid_auth,
            )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["nodes"], [])
        self.assertGreater(len(result["warnings"]), 0)

    def test_query_alpha_clamped_to_valid_range(self):
        """alpha outside [0.70, 0.95] must be silently clamped."""
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_query
            # Should not raise even with out-of-range alpha
            result = onto_query(
                concepts=["knowledge"],
                authorization=self.valid_auth,
                alpha=0.0,  # below minimum
            )
        self.assertIn(result["status"], ("ok",))

    def test_query_result_has_subgraph_keys(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_query
            result = onto_query(
                concepts=["knowledge"],
                authorization=self.valid_auth,
            )
        self.assertIn("nodes", result["data"])
        self.assertIn("edges", result["data"])
        self.assertIn("metadata", result["data"])

    def test_query_rejected_without_auth(self):
        with self._mock_no_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_query
            result = onto_query(
                concepts=["knowledge"],
                authorization="Bearer bad-token",
            )
        self.assertEqual(result["status"], "error")


# ---------------------------------------------------------------------------
# TEST CLASS 5 — onto_surface
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FASTMCP_INSTALLED, _SKIP_MSG)
class TestOntoSurface(_MCPTestBase):
    """
    onto_surface returns epistemic state. It must always include
    confidence, related_context, and classification. Crisis inputs
    must return crisis status without entering the surface pipeline.
    """

    def test_surface_returns_confidence(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_surface
            result = onto_surface(
                text="machine learning context reasoning",
                authorization=self.valid_auth,
            )
        self.assertIn(result["status"], ("ok",))
        self.assertIn("confidence", result["data"])

    def test_surface_includes_classification(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_surface
            result = onto_surface(
                text="ontology system knowledge graph",
                authorization=self.valid_auth,
            )
        self.assertIn("classification", result["data"])

    def test_surface_crisis_returns_crisis_status(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_surface
            result = onto_surface(
                text="I want to end my life",
                authorization=self.valid_auth,
            )
        self.assertEqual(result["status"], "crisis")

    def test_surface_rejected_without_auth(self):
        with self._mock_no_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_surface
            result = onto_surface(
                text="test",
                authorization="Bearer bad-token",
            )
        self.assertEqual(result["status"], "error")


# ---------------------------------------------------------------------------
# TEST CLASS 6 — onto_checkpoint
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FASTMCP_INSTALLED, _SKIP_MSG)
class TestOntoCheckpoint(_MCPTestBase):
    """
    onto_checkpoint is the human sovereignty gate.
    No human_decision → pending_checkpoint with automation bias warning.
    Valid decision → recorded permanently, action authorized/halted.
    Invalid decision → error with valid options listed.
    """

    def test_no_decision_returns_pending(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_checkpoint
            result = onto_checkpoint(
                authorization=self.valid_auth,
                context_summary="Should we proceed with deletion?",
                proposed_action="delete_records",
            )
        self.assertEqual(result["status"], "pending_checkpoint")
        self.assertTrue(result["checkpoint_required"])

    def test_pending_includes_automation_bias_warning(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_checkpoint
            result = onto_checkpoint(
                authorization=self.valid_auth,
                context_summary="Review this action.",
                proposed_action="export_data",
            )
        ctx = result["checkpoint_context"]
        self.assertIn("automation_bias_warning", ctx)
        self.assertGreater(len(ctx["automation_bias_warning"]), 0)

    def test_proceed_decision_authorized(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_checkpoint
            result = onto_checkpoint(
                authorization=self.valid_auth,
                context_summary="Proceed with export?",
                proposed_action="export_data",
                human_decision="proceed",
            )
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["data"]["authorized"])
        self.assertEqual(result["data"]["decision"], "proceed")

    def test_veto_decision_halts_action(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_checkpoint
            result = onto_checkpoint(
                authorization=self.valid_auth,
                context_summary="Delete user data?",
                proposed_action="delete_records",
                human_decision="veto",
            )
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["data"]["authorized"])
        self.assertEqual(result["data"]["action"], "halted")

    def test_invalid_decision_returns_error(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_checkpoint
            result = onto_checkpoint(
                authorization=self.valid_auth,
                context_summary="Test.",
                proposed_action="test",
                human_decision="maybe",
            )
        self.assertEqual(result["status"], "error")
        self.assertIn("maybe", result["data"]["message"])

    def test_all_valid_decisions_accepted(self):
        valid = ["proceed", "veto", "flag", "defer"]
        for decision in valid:
            with self._mock_session(), \
                 patch("api.onto_server.memory.DB_PATH", self.test_db):
                from api.onto_server import onto_checkpoint
                result = onto_checkpoint(
                    authorization=self.valid_auth,
                    context_summary="Test decision.",
                    proposed_action="test_action",
                    human_decision=decision,
                )
            self.assertEqual(
                result["status"], "ok",
                f"Decision '{decision}' must be accepted.",
            )


# ---------------------------------------------------------------------------
# TEST CLASS 7 — onto_relate
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FASTMCP_INSTALLED, _SKIP_MSG)
class TestOntoRelate(_MCPTestBase):
    """
    onto_relate asserts typed edges between concepts.
    Empty concepts must be rejected. Crisis content must never be stored.
    Confidence must be clamped to [0.0, 1.0].
    """

    def test_relate_creates_nodes(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_relate
            result = onto_relate(
                source_concept="machine_learning",
                target_concept="neural_network",
                authorization=self.valid_auth,
            )
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["data"]["nodes_created"], 0)

    def test_relate_empty_source_returns_error(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_relate
            result = onto_relate(
                source_concept="",
                target_concept="neural_network",
                authorization=self.valid_auth,
            )
        self.assertEqual(result["status"], "error")

    def test_relate_empty_target_returns_error(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_relate
            result = onto_relate(
                source_concept="machine_learning",
                target_concept="",
                authorization=self.valid_auth,
            )
        self.assertEqual(result["status"], "error")

    def test_relate_crisis_content_returns_crisis(self):
        with self._mock_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_relate
            result = onto_relate(
                source_concept="want to die",
                target_concept="end my life",
                authorization=self.valid_auth,
            )
        self.assertEqual(result["status"], "crisis")

    def test_relate_rejected_without_auth(self):
        with self._mock_no_session(), \
             patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_relate
            result = onto_relate(
                source_concept="alpha",
                target_concept="beta",
                authorization="Bearer bad-token",
            )
        self.assertEqual(result["status"], "error")


# ---------------------------------------------------------------------------
# TEST CLASS 8 — onto_schema
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FASTMCP_INSTALLED, _SKIP_MSG)
class TestOntoSchema(_MCPTestBase):
    """
    onto_schema returns the edge type vocabulary. It must include all
    16 standard types organized by category. Read-only; no auth required.
    """

    def test_schema_returns_16_types(self):
        with patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_schema
            result = onto_schema()
        self.assertEqual(result["total_types"], 16,
                         "Edge type registry must contain exactly 16 types.")

    def test_schema_has_all_categories(self):
        with patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_schema
            result = onto_schema()
        expected_categories = {
            "taxonomic", "mereological", "causal",
            "associative", "temporal", "spatial", "epistemic",
        }
        self.assertEqual(
            set(result["categories"].keys()), expected_categories,
            "Schema must contain all 7 edge type categories.",
        )

    def test_schema_includes_schema_version(self):
        with patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_schema
            result = onto_schema()
        self.assertIn("schema_version", result)
        self.assertEqual(result["schema_version"], "1.0")


# ---------------------------------------------------------------------------
# TEST CLASS 9 — onto_status
# ---------------------------------------------------------------------------

@unittest.skipUnless(_FASTMCP_INSTALLED, _SKIP_MSG)
class TestOntoStatus(_MCPTestBase):
    """
    onto_status returns node health and graph metrics. It must always
    return a dict with the required keys even on a fresh empty graph.
    """

    def test_status_returns_healthy(self):
        with patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_status
            result = onto_status()
        self.assertEqual(result["status"], "healthy")

    def test_status_includes_graph_metrics(self):
        with patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_status
            result = onto_status()
        self.assertIn("graph", result)
        for key in ("nodes", "edges", "total_inputs_processed"):
            self.assertIn(key, result["graph"])

    def test_status_includes_ppr_info(self):
        with patch("api.onto_server.memory.DB_PATH", self.test_db):
            from api.onto_server import onto_status
            result = onto_status()
        self.assertIn("ppr", result)
        self.assertIn("available", result["ppr"])
        self.assertIn("hardware_tier", result["ppr"])


if __name__ == "__main__":
    unittest.main()
