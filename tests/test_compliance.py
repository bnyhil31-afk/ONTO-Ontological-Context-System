"""
tests/test_compliance.py

Compliance tests for ONTO — organized by regulation article.

Covers:
  GDPR Art. 6  — Legal basis annotated in intake audit records
  GDPR Art. 15 — Right of access (data export endpoint)
  GDPR Art. 17 — Right to erasure (graph wipe endpoint)
  GDPR Art. 20 — Right to portability (graph snapshot in export)
  GDPR Art. 22 — Automated decision disclosure (auto-proceed flag)
  EU AI Act Art. 13 — System transparency endpoint
  EU AI Act Art. 14 — Bias warning in moderate display mode

Expected result: 34 passed, 0 failed, 0 errors (8 may be skipped if
fastapi[testclient] is unavailable).
If you see anything different — something needs attention.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# TEST: GDPR ARTICLE 6 — LEGAL BASIS
# ─────────────────────────────────────────────────────────────────────────────

class TestGDPRArticle6_LegalBasis(unittest.TestCase):
    """
    GDPR Art. 6 — Legal basis must be annotated in every intake record.

    Plain English: Every time data is processed, the reason for processing
    (the legal basis) must be recorded. At Stage 1 this is
    "legitimate_interest_single_operator" because the operator and subject
    are the same person.

    Expected: 3 passed.
    """

    def setUp(self):
        import modules.memory as mem
        self._tmp = tempfile.mktemp(suffix=".db")
        self._orig_db = mem.DB_PATH
        mem.DB_PATH = self._tmp
        mem.initialize()

    def tearDown(self):
        import modules.memory as mem
        mem.DB_PATH = self._orig_db
        try:
            os.unlink(self._tmp)
        except FileNotFoundError:
            pass

    def test_intake_annotates_legal_basis_in_notes(self):
        """
        After intake.receive(), the audit record notes must contain 'legal_basis:'.
        """
        import modules.memory as memory_module
        import modules.intake as intake_module

        intake_module.receive("test input for legal basis")

        result = memory_module.query(event_type="INTAKE", limit=1)
        records = result.get("records", [])
        self.assertTrue(records, "No INTAKE record found after receive().")
        notes = records[0].get("notes", "")
        self.assertIn(
            "legal_basis:", notes,
            f"Intake record notes must include 'legal_basis:'. Got: {notes!r}"
        )

    def test_legal_basis_present_in_returned_package(self):
        """
        intake.receive() must include 'legal_basis' in the returned package dict.
        """
        import modules.intake as intake_module

        package = intake_module.receive("another test input")
        self.assertIn(
            "legal_basis", package,
            "Package returned by intake.receive() must include 'legal_basis' key."
        )
        self.assertIsInstance(package["legal_basis"], str)
        self.assertTrue(package["legal_basis"], "legal_basis must not be empty.")

    def test_legal_basis_matches_config(self):
        """
        The legal_basis in the package must match config.COMPLIANCE_LEGAL_BASIS_DEFAULT.
        """
        import modules.intake as intake_module
        import core.config as config_module

        package = intake_module.receive("config-match test")
        self.assertEqual(
            package["legal_basis"],
            config_module.config.COMPLIANCE_LEGAL_BASIS_DEFAULT,
            "Package legal_basis must match config.COMPLIANCE_LEGAL_BASIS_DEFAULT."
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: GDPR ARTICLE 15 — RIGHT OF ACCESS
# ─────────────────────────────────────────────────────────────────────────────

class TestGDPRArticle15_RightOfAccess(unittest.TestCase):
    """
    GDPR Art. 15 — Data subjects have the right to access all personal data
    held about them in a machine-readable format.

    Expected: 5 passed.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
            cls._has_testclient = True
        except ImportError:
            cls._has_testclient = False

    def _skip_if_no_client(self):
        if not self._has_testclient:
            self.skipTest("fastapi[testclient] not installed")

    def setUp(self):
        self._skip_if_no_client()
        import modules.memory as memory_module
        self._tmp = tempfile.mktemp(suffix=".db")
        self._orig_db = memory_module.DB_PATH
        memory_module.DB_PATH = self._tmp
        memory_module.initialize()
        # Pre-populate a record with classification 2 (personal data)
        memory_module.record(
            event_type="INTAKE",
            input_data="personal test input",
            classification=2,
            notes="test record for export",
        )

        from fastapi.testclient import TestClient
        import api.main as api_module
        # Authenticate to get a session token
        resp = TestClient(api_module.app, raise_server_exceptions=False).post(
            "/auth", json={"passphrase": "", "identity": "test"}
        )
        self._token = resp.json().get("token", "")
        self._client = TestClient(api_module.app, raise_server_exceptions=False)

    def tearDown(self):
        import modules.memory as memory_module
        memory_module.DB_PATH = self._orig_db
        try:
            os.unlink(self._tmp)
        except FileNotFoundError:
            pass

    def _auth_headers(self):
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def test_export_endpoint_returns_200(self):
        """GET /data/export must return HTTP 200 with a valid session token."""
        resp = self._client.get("/data/export", headers=self._auth_headers())
        self.assertEqual(
            resp.status_code, 200,
            f"GET /data/export returned {resp.status_code}: {resp.text[:300]}"
        )

    def test_export_default_classification_filter_is_2(self):
        """Default classification_filter in the response must be 2."""
        resp = self._client.get("/data/export", headers=self._auth_headers())
        if resp.status_code != 200:
            self.skipTest(f"Auth not available: {resp.status_code}")
        data = resp.json()
        self.assertEqual(
            data.get("classification_filter"), 2,
            "Default classification_filter must be 2 (personal data threshold)."
        )

    def test_export_includes_compliance_metadata(self):
        """Response must include compliance.gdpr_article == '15'."""
        resp = self._client.get("/data/export", headers=self._auth_headers())
        if resp.status_code != 200:
            self.skipTest(f"Auth not available: {resp.status_code}")
        data = resp.json()
        compliance = data.get("compliance", {})
        self.assertEqual(
            compliance.get("gdpr_article"), "15",
            "compliance.gdpr_article must be '15' (GDPR Art. 15)."
        )

    def test_export_has_format_version(self):
        """Response must include format_version field."""
        resp = self._client.get("/data/export", headers=self._auth_headers())
        if resp.status_code != 200:
            self.skipTest(f"Auth not available: {resp.status_code}")
        data = resp.json()
        self.assertIn(
            "format_version", data,
            "Export response must include 'format_version' for interoperability."
        )

    def test_export_has_records_list(self):
        """Response must include a 'records' list."""
        resp = self._client.get("/data/export", headers=self._auth_headers())
        if resp.status_code != 200:
            self.skipTest(f"Auth not available: {resp.status_code}")
        data = resp.json()
        self.assertIn("records", data, "Export response must include 'records' list.")
        self.assertIsInstance(data["records"], list)


# ─────────────────────────────────────────────────────────────────────────────
# TEST: GDPR ARTICLE 17 — RIGHT TO ERASURE
# ─────────────────────────────────────────────────────────────────────────────

class TestGDPRArticle17_RightToErasure(unittest.TestCase):
    """
    GDPR Art. 17 — Data subjects have the right to delete their data.
    The graph.wipe() function exists; this tests it has an HTTP endpoint
    and that erasure is audited.

    Expected: 4 passed.
    """

    def setUp(self):
        import modules.memory as mem
        self._tmp = tempfile.mktemp(suffix=".db")
        self._orig_db = mem.DB_PATH
        mem.DB_PATH = self._tmp
        mem.initialize()

    def tearDown(self):
        import modules.memory as mem
        mem.DB_PATH = self._orig_db
        try:
            os.unlink(self._tmp)
        except FileNotFoundError:
            pass

    def test_graph_wipe_returns_counts(self):
        """
        graph.wipe() must return a dict with nodes_deleted and edges_deleted.
        This is the underlying erasure mechanism.
        """
        import modules.graph as graph_module

        result = graph_module.wipe()
        self.assertIn("nodes_deleted", result, "wipe() must return nodes_deleted.")
        self.assertIn("edges_deleted", result, "wipe() must return edges_deleted.")

    def test_erasure_records_graph_wipe_event(self):
        """
        After graph.wipe(), the audit trail must contain a GRAPH_WIPE event.
        """
        import modules.memory as memory_module
        import modules.graph as graph_module

        # Ensure graph schema exists in the test DB before wiping
        graph_module.initialize()
        graph_module.wipe()

        result = memory_module.query(event_type="GRAPH_WIPE", limit=5)
        self.assertGreater(
            result.get("total", 0), 0,
            "GRAPH_WIPE event must be recorded in the audit trail after wipe()."
        )

    def test_erasure_endpoint_returns_200(self):
        """DELETE /data/erasure must return HTTP 200 with a valid session token."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi[testclient] not installed")

        import api.main as api_module
        client = TestClient(api_module.app, raise_server_exceptions=False)
        auth_resp = client.post("/auth", json={"passphrase": "", "identity": "test"})
        token = auth_resp.json().get("token", "")
        resp = client.delete(
            "/data/erasure",
            headers={"Authorization": f"Bearer {token}"} if token else {}
        )
        self.assertEqual(
            resp.status_code, 200,
            f"DELETE /data/erasure returned {resp.status_code}: {resp.text[:300]}"
        )

    def test_erasure_response_has_gdpr_article(self):
        """Erasure response must include gdpr_article: '17'."""
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi[testclient] not installed")

        import api.main as api_module
        client = TestClient(api_module.app, raise_server_exceptions=False)
        auth_resp = client.post("/auth", json={"passphrase": "", "identity": "test"})
        token = auth_resp.json().get("token", "")
        resp = client.delete(
            "/data/erasure",
            headers={"Authorization": f"Bearer {token}"} if token else {}
        )
        if resp.status_code != 200:
            self.skipTest(f"Auth not available: {resp.status_code}")
        data = resp.json()
        self.assertEqual(
            data.get("gdpr_article"), "17",
            "Erasure response must include gdpr_article: '17'."
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: GDPR ARTICLE 20 — RIGHT TO PORTABILITY
# ─────────────────────────────────────────────────────────────────────────────

class TestGDPRArticle20_RightToPortability(unittest.TestCase):
    """
    GDPR Art. 20 — Data subjects have the right to receive their data in a
    structured, commonly used, machine-readable format.

    Expected: 3 passed.
    """

    def setUp(self):
        import modules.memory as mem
        self._tmp = tempfile.mktemp(suffix=".db")
        self._orig_db = mem.DB_PATH
        mem.DB_PATH = self._tmp
        mem.initialize()

    def tearDown(self):
        import modules.memory as mem
        mem.DB_PATH = self._orig_db
        try:
            os.unlink(self._tmp)
        except FileNotFoundError:
            pass

    def test_export_personal_data_is_machine_readable(self):
        """
        memory.export_personal_data() must return a dict with a 'records' list.
        Machine-readable = structured dict, not a human-formatted string.
        """
        import modules.memory as memory_module

        result = memory_module.export_personal_data()
        self.assertIsInstance(result, dict, "export_personal_data() must return a dict.")
        self.assertIn("records", result, "Export must include 'records' key.")
        self.assertIsInstance(result["records"], list)

    def test_export_with_graph_snapshot_has_expected_keys(self):
        """
        export_personal_data(include_graph_snapshot=True) must include
        graph_snapshot with nodes, edges, node_count, edge_count.
        """
        import modules.memory as memory_module

        result = memory_module.export_personal_data(include_graph_snapshot=True)
        snapshot = result.get("graph_snapshot")
        self.assertIsNotNone(
            snapshot,
            "graph_snapshot must be present when include_graph_snapshot=True."
        )
        for key in ("nodes", "edges", "node_count", "edge_count"):
            self.assertIn(
                key, snapshot,
                f"graph_snapshot must include '{key}' key."
            )

    def test_export_excludes_internal_integrity_fields(self):
        """
        Exported records must not include chain_hash or signature_algorithm
        (these are internal integrity fields, not personal data).
        """
        import modules.memory as memory_module

        # Insert a record so we have something to export
        memory_module.record(
            event_type="INTAKE", classification=2, notes="portability test"
        )
        result = memory_module.export_personal_data(classification_min=2)
        for record in result.get("records", []):
            self.assertNotIn(
                "chain_hash", record,
                "Exported records must not include chain_hash (internal integrity field)."
            )
            self.assertNotIn(
                "signature_algorithm", record,
                "Exported records must not include signature_algorithm."
            )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: GDPR ARTICLE 22 — AUTOMATED DECISION DISCLOSURE
# ─────────────────────────────────────────────────────────────────────────────

class TestGDPRArticle22_AutomatedDecision(unittest.TestCase):
    """
    GDPR Art. 22 — When decisions are made automatically (without human
    review), data subjects must be informed. The auto-proceed path in
    checkpoint.py must record a GDPR-22 disclosure in the audit trail.

    Expected: 3 passed.
    """

    def setUp(self):
        import modules.memory as mem
        self._tmp = tempfile.mktemp(suffix=".db")
        self._orig_db = mem.DB_PATH
        mem.DB_PATH = self._tmp
        mem.initialize()

    def tearDown(self):
        import modules.memory as mem
        mem.DB_PATH = self._orig_db
        try:
            os.unlink(self._tmp)
        except FileNotFoundError:
            pass

    def _make_auto_proceed_surface(self, weight=0.05, confidence=0.9):
        """Build a minimal surface dict that will trigger auto-proceed."""
        return {
            "confidence": confidence,
            "weight": weight,
            "safe": True,
            "display": "Test surface display.",
        }

    def _make_enriched_package(self):
        return {
            "clean": "test input",
            "classification": 0,
            "safety": None,
        }

    def test_auto_proceed_notes_contain_gdpr22_marker(self):
        """
        Auto-proceed checkpoint audit record notes must contain 'GDPR-22:'.
        """
        import modules.memory as memory_module
        import modules.checkpoint as checkpoint_module

        surface = self._make_auto_proceed_surface()
        package = self._make_enriched_package()
        checkpoint_module.run(surface, package)

        result = memory_module.query(event_type="CHECKPOINT", limit=5)
        records = result.get("records", [])
        auto_records = [
            r for r in records if "AUTO_PROCEED" in (r.get("human_decision") or "")
        ]
        self.assertTrue(auto_records, "No AUTO_PROCEED checkpoint record found.")
        notes = auto_records[0].get("notes", "")
        self.assertIn(
            "GDPR-22:", notes,
            f"Auto-proceed record must contain 'GDPR-22:' in notes. Got: {notes!r}"
        )

    def test_auto_proceed_result_has_gdpr22_flag(self):
        """
        The dict returned by checkpoint.run() on an auto-proceed path must
        include gdpr22_automated: True.
        """
        import modules.checkpoint as checkpoint_module

        surface = self._make_auto_proceed_surface()
        package = self._make_enriched_package()
        result = checkpoint_module.run(surface, package)
        self.assertTrue(
            result.get("gdpr22_automated"),
            "Auto-proceed result must include gdpr22_automated: True."
        )

    def test_human_decision_does_not_have_gdpr22_flag(self):
        """
        A human checkpoint result must NOT have gdpr22_automated: True.
        (The GDPR-22 flag should only appear when there was no human review.)
        """
        import modules.checkpoint as checkpoint_module

        # High weight forces human checkpoint
        surface = {"confidence": 0.9, "weight": 0.9, "safe": True, "display": ""}
        package = self._make_enriched_package()

        # Inject a mock that auto-answers "proceed" without user input
        original = checkpoint_module._ask_human
        checkpoint_module._ask_human = lambda prompt, options=None, **kw: "proceed"
        try:
            result = checkpoint_module.run(surface, package)
        finally:
            checkpoint_module._ask_human = original

        self.assertFalse(
            result.get("gdpr22_automated", False),
            "Human-reviewed checkpoints must NOT set gdpr22_automated."
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: EU AI ACT ARTICLE 13 — SYSTEM TRANSPARENCY
# ─────────────────────────────────────────────────────────────────────────────

class TestEUAIActArt13_Transparency(unittest.TestCase):
    """
    EU AI Act Art. 13 — High-risk AI systems must provide transparent
    documentation including known limitations, data controller identity,
    and active compliance rights.

    Expected: 4 passed.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
            import api.main as api_module
            cls.client = TestClient(api_module.app, raise_server_exceptions=False)
            cls._has_client = True
        except ImportError:
            cls._has_client = False
            cls.client = None

    def _skip_if_no_client(self):
        if not self._has_client:
            self.skipTest("fastapi[testclient] not installed")

    def test_transparency_endpoint_returns_200(self):
        """GET /system/transparency requires no authentication and returns 200."""
        self._skip_if_no_client()
        resp = self.client.get("/system/transparency")
        self.assertEqual(
            resp.status_code, 200,
            f"GET /system/transparency returned {resp.status_code}: {resp.text[:300]}"
        )

    def test_transparency_has_known_limitations(self):
        """
        Response must include a non-empty 'known_limitations' list.
        EU AI Act Art. 13(1)(b): disclosure of system limitations.
        """
        self._skip_if_no_client()
        resp = self.client.get("/system/transparency")
        if resp.status_code != 200:
            self.skipTest("Transparency endpoint not available")
        data = resp.json()
        limitations = data.get("known_limitations", [])
        self.assertIsInstance(limitations, list, "known_limitations must be a list.")
        self.assertGreater(
            len(limitations), 0,
            "known_limitations must be non-empty — at least one limitation must be disclosed."
        )

    def test_transparency_has_data_controller(self):
        """
        Response must include a 'data_controller' field.
        GDPR Art. 13 requires disclosure of the data controller's identity.
        """
        self._skip_if_no_client()
        resp = self.client.get("/system/transparency")
        if resp.status_code != 200:
            self.skipTest("Transparency endpoint not available")
        data = resp.json()
        self.assertIn(
            "data_controller", data,
            "Transparency response must include 'data_controller' field."
        )
        self.assertIsInstance(data["data_controller"], str)

    def test_transparency_compliance_stage_is_string(self):
        """
        Response must include a non-empty 'compliance_stage' string.
        This enables downstream consumers to check which rights are active.
        """
        self._skip_if_no_client()
        resp = self.client.get("/system/transparency")
        if resp.status_code != 200:
            self.skipTest("Transparency endpoint not available")
        data = resp.json()
        stage = data.get("compliance_stage", "")
        self.assertIsInstance(stage, str)
        self.assertTrue(stage, "compliance_stage must be a non-empty string.")


# ─────────────────────────────────────────────────────────────────────────────
# TEST: EU AI ACT ARTICLE 14 — BIAS WARNING SCOPE
# ─────────────────────────────────────────────────────────────────────────────

class TestEUAIActArt14_BiasWarning(unittest.TestCase):
    """
    EU AI Act Art. 14 — AI systems must help users recognize and manage bias.
    The source diversity warning must appear in both moderate and complex
    display modes when source diversity is low.

    Expected: 4 passed.
    """

    def _make_low_diversity_examination(self):
        """Build an examination dict that should trigger the diversity warning."""
        return {
            "depth_signal": "moderate",
            "confidence_profile": {
                "level": "moderate",
                "explanation": "Based on 5 observations.",
                "diversity_ratio": 0.1,   # low diversity — below 0.3 threshold
                "total_observations": 5,
                "source_count": 1,        # only one source
            },
            "contradiction_flags": [],
            "gap_flags": [],
            "provenance_summary": "source: test",
        }

    def _make_enriched_package(self, text="test input"):
        return {
            "clean": text,
            "context": {"related_count": 5},
            "graph_context": [],
        }

    def test_moderate_display_warns_when_low_diversity(self):
        """
        _build_moderate_display() must include a diversity warning when
        diversity_ratio < 0.3 and source_count > 0 and total_observations > 1.
        """
        from modules.surface import _build_moderate_display
        examination = self._make_low_diversity_examination()
        enriched = self._make_enriched_package()
        display = _build_moderate_display(enriched, examination)
        self.assertIn(
            "Diversity note", display,
            "Moderate display must include diversity warning when diversity_ratio < 0.3."
        )
        self.assertIn(
            "Repetition does not increase reliability", display,
            "Diversity warning must include the 'repetition' message."
        )

    def test_moderate_display_no_warning_when_high_diversity(self):
        """
        _build_moderate_display() must NOT warn when diversity is high.
        """
        from modules.surface import _build_moderate_display
        examination = {
            "depth_signal": "moderate",
            "confidence_profile": {
                "level": "high",
                "explanation": "Diverse sources.",
                "diversity_ratio": 0.8,   # high diversity — above threshold
                "total_observations": 10,
                "source_count": 8,
            },
            "contradiction_flags": [],
            "gap_flags": [],
        }
        enriched = self._make_enriched_package()
        display = _build_moderate_display(enriched, examination)
        self.assertNotIn(
            "Diversity note", display,
            "Moderate display must NOT warn when diversity_ratio >= 0.3."
        )

    def test_complex_display_warns_when_low_diversity(self):
        """
        _build_complex_display() must still include the diversity warning.
        (Existing behavior — must not have been broken.)
        """
        from modules.surface import _build_complex_display
        examination = self._make_low_diversity_examination()
        examination["depth_signal"] = "complex"
        examination["contradiction_flags"] = []
        examination["gap_flags"] = []
        examination["epistemic_status"] = "known"  # string, not dict
        enriched = self._make_enriched_package("complex input with rich context")
        enriched["context"] = {"related_count": 5}
        enriched["graph_context"] = []
        display = _build_complex_display(enriched, examination)
        self.assertIn(
            "Diversity note", display,
            "Complex display must include diversity warning when diversity_ratio < 0.3."
        )

    def test_simple_display_has_no_diversity_warning(self):
        """
        _build_simple_display() must not include a diversity warning.
        Simple inputs do not warrant diversity analysis.
        """
        from modules.surface import _build_simple_display
        examination = {
            "confidence_profile": {
                "level": "none",
                "diversity_ratio": 0.0,
                "total_observations": 2,
                "source_count": 1,
            },
            "contradiction_flags": [],
            "gap_flags": [],
        }
        enriched = self._make_enriched_package("hi")
        enriched["context"] = {"related_count": 0}
        enriched["graph_context"] = []
        display = _build_simple_display(enriched, examination)
        self.assertNotIn(
            "Diversity note", display,
            "Simple display must not include source diversity warning."
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: AUDIT EVENTS — AUTH_SUCCESS, DATA_EXPORT, TRANSPARENCY_READ
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditEvents(unittest.TestCase):
    """
    Verify that the three compliance-critical audit events are emitted:
      AUTH_SUCCESS     — successful authentication must be recorded
      DATA_EXPORT      — GDPR Art. 15 data export must be recorded
      TRANSPARENCY_READ — EU AI Act Art. 13 disclosure access must be recorded

    Expected: 6 passed (or skipped if testclient unavailable).
    """

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
            cls._has_testclient = True
        except ImportError:
            cls._has_testclient = False

    def _skip_if_no_client(self):
        if not self._has_testclient:
            self.skipTest("fastapi[testclient] not installed")

    def setUp(self):
        self._skip_if_no_client()
        import modules.memory as memory_module
        self._tmp = tempfile.mktemp(suffix=".db")
        self._orig_db = memory_module.DB_PATH
        memory_module.DB_PATH = self._tmp
        memory_module.initialize()

        from fastapi.testclient import TestClient
        import api.main as api_module
        self._api = api_module
        self._client = TestClient(api_module.app, raise_server_exceptions=False)

    def tearDown(self):
        import modules.memory as memory_module
        memory_module.DB_PATH = self._orig_db
        try:
            os.unlink(self._tmp)
        except FileNotFoundError:
            pass

    def _auth_headers(self, token):
        return {"Authorization": f"Bearer {token}"} if token else {}

    # ── AUTH_SUCCESS ──────────────────────────────────────────────────────────

    def test_auth_success_event_is_recorded(self):
        """
        A successful POST /auth must produce an AUTH_SUCCESS audit record.
        """
        import modules.memory as memory_module

        resp = self._client.post("/auth", json={"passphrase": "", "identity": "audit_test"})
        self.assertEqual(resp.status_code, 200, f"Auth failed: {resp.text[:200]}")

        result = memory_module.query(event_type="AUTH_SUCCESS", limit=10)
        records = result.get("records", [])
        self.assertTrue(
            records,
            "No AUTH_SUCCESS record found after successful authentication."
        )

    def test_auth_success_notes_contain_identity(self):
        """
        The AUTH_SUCCESS record notes must include the identity that authenticated.
        """
        import modules.memory as memory_module

        resp = self._client.post("/auth", json={"passphrase": "", "identity": "alice"})
        if resp.status_code != 200:
            self.skipTest(f"Auth unavailable: {resp.status_code}")

        # The actual identity may differ (e.g. "dev-operator" in dev mode).
        # Assert that whatever identity was used appears in the notes.
        actual_identity = resp.json().get("identity", "")
        result = memory_module.query(event_type="AUTH_SUCCESS", limit=10)
        records = result.get("records", [])
        self.assertTrue(records, "No AUTH_SUCCESS record.")
        notes = records[0].get("notes", "")
        self.assertTrue(
            actual_identity and actual_identity in notes,
            f"AUTH_SUCCESS notes must include the identity '{actual_identity}'. Got: {notes!r}"
        )

    # ── DATA_EXPORT ───────────────────────────────────────────────────────────

    def test_data_export_event_is_recorded(self):
        """
        GET /data/export must produce a DATA_EXPORT audit record (in addition
        to the READ_ACCESS record emitted by export_personal_data()).
        """
        import modules.memory as memory_module

        auth_resp = self._client.post("/auth", json={"passphrase": "", "identity": "test"})
        token = auth_resp.json().get("token", "")

        self._client.get("/data/export", headers=self._auth_headers(token))

        result = memory_module.query(event_type="DATA_EXPORT", limit=10)
        records = result.get("records", [])
        self.assertTrue(
            records,
            "No DATA_EXPORT record found after GET /data/export."
        )

    def test_data_export_notes_contain_gdpr_article(self):
        """
        The DATA_EXPORT record notes must mention GDPR Art. 15.
        """
        import modules.memory as memory_module

        auth_resp = self._client.post("/auth", json={"passphrase": "", "identity": "test"})
        token = auth_resp.json().get("token", "")

        resp = self._client.get("/data/export", headers=self._auth_headers(token))
        if resp.status_code != 200:
            self.skipTest(f"Export endpoint failed: {resp.status_code}")

        result = memory_module.query(event_type="DATA_EXPORT", limit=10)
        records = result.get("records", [])
        self.assertTrue(records, "No DATA_EXPORT record.")
        notes = records[0].get("notes", "")
        self.assertIn(
            "GDPR Art. 15", notes,
            f"DATA_EXPORT notes must cite GDPR Art. 15. Got: {notes!r}"
        )

    # ── TRANSPARENCY_READ ────────────────────────────────────────────────────

    def test_transparency_read_event_is_recorded(self):
        """
        GET /system/transparency must produce a TRANSPARENCY_READ audit record.
        The endpoint is public (no auth required).
        """
        import modules.memory as memory_module

        resp = self._client.get("/system/transparency")
        self.assertEqual(
            resp.status_code, 200,
            f"Transparency endpoint returned {resp.status_code}: {resp.text[:200]}"
        )

        result = memory_module.query(event_type="TRANSPARENCY_READ", limit=10)
        records = result.get("records", [])
        self.assertTrue(
            records,
            "No TRANSPARENCY_READ record found after GET /system/transparency."
        )

    def test_transparency_known_limitations_from_config(self):
        """
        GET /system/transparency known_limitations must be sourced from
        config.COMPLIANCE_TRANSPARENCY_KNOWN_LIMITATIONS (env-var overridable).
        Verify the response list is non-empty and all entries are non-blank strings.
        """
        resp = self._client.get("/system/transparency")
        if resp.status_code != 200:
            self.skipTest(f"Transparency endpoint unavailable: {resp.status_code}")

        data = resp.json()
        limitations = data.get("known_limitations", [])
        self.assertIsInstance(limitations, list, "known_limitations must be a list.")
        self.assertGreater(
            len(limitations), 0,
            "known_limitations must not be empty."
        )
        for item in limitations:
            self.assertIsInstance(item, str, "Each known_limitation must be a string.")
            self.assertTrue(item.strip(), "No blank entries in known_limitations.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
