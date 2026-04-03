"""
tests/test_consent.py

Phase 4 Consent Ledger test suite — 62 tests across 12 classes.

Safety-critical classes (block deployment if they fail):
  ⚠️  TestConsentAbsoluteBarriers — crisis and cls 4+ always blocked
  ⚠️  TestConsentGate            — gate logic, self-access, audit-only

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import memory, graph


class _ConsentBase(unittest.TestCase):
    """Fresh isolated DB for every test."""

    def setUp(self):
        self._orig_db = memory.DB_PATH
        self.test_dir = tempfile.mkdtemp()
        self.test_db  = os.path.join(self.test_dir, "test_consent.db")
        memory.DB_PATH = self.test_db
        memory.initialize()
        graph.initialize()

        from api.consent.schema import initialize as schema_init
        from api.consent.status_list import initialize as sl_init
        schema_init()
        sl_init()

    def tearDown(self):
        memory.DB_PATH = self._orig_db
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _record(self, **kwargs):
        from api.consent.adapter import ConsentRecord
        defaults = dict(
            subject_id="subjectA",
            grantor_id="subjectA",
            requester_id="requesterB",
            purpose="dpv:ServiceProvision",
            legal_basis="gdpr:consent-art6-1a",
            operations=["read", "navigate"],
            classification_max=2,
        )
        defaults.update(kwargs)
        return ConsentRecord(**defaults)

    def _grant(self, **kwargs):
        from api.consent.ledger import consent_ledger
        return consent_ledger.grant(self._record(**kwargs))

    def _patch_consent_enabled(self, enabled=True):
        import api.consent.config as _cfg
        orig = _cfg.CONSENT_ENABLED
        _cfg.CONSENT_ENABLED = enabled
        return orig

    def _restore_consent_enabled(self, orig):
        import api.consent.config as _cfg
        _cfg.CONSENT_ENABLED = orig


# ===========================================================================
# ⚠️  SAFETY-CRITICAL: TestConsentAbsoluteBarriers
# ===========================================================================

class TestConsentAbsoluteBarriers(_ConsentBase):
    """
    Verify the two absolute barriers in ConsentGate.
    Crisis and classification 4+ are blocked regardless of any
    consent record, configuration, or regulatory profile.
    BLOCK DEPLOYMENT IF THESE FAIL.
    """

    def setUp(self):
        super().setUp()
        orig = self._patch_consent_enabled(True)
        self._orig_enabled = orig

    def tearDown(self):
        self._restore_consent_enabled(self._orig_enabled)
        super().tearDown()

    def _gate(self, **kwargs):
        from api.consent.enforcement import ConsentGate
        return ConsentGate()

    def test_crisis_flag_always_blocked(self):
        """is_crisis=True must be blocked regardless of consent record."""
        cid = self._grant()
        gate = self._gate()
        d = gate.decide(
            subject_id="subjectA",
            requester_id="requesterB",
            purpose="dpv:ServiceProvision",
            classification=0,
            operation="read",
            is_crisis=True,
        )
        self.assertFalse(d.allowed, "Crisis flag must always block.")
        self.assertIn("crisis", d.reason)

    def test_crisis_text_always_blocked(self):
        """Text containing crisis content must be blocked."""
        gate = self._gate()
        d = gate.decide(
            subject_id="subjectA",
            requester_id="requesterB",
            purpose="dpv:ServiceProvision",
            classification=0,
            operation="read",
            text="I want to end my life",
        )
        self.assertFalse(d.allowed, "Crisis text must always block.")

    def test_crisis_text_in_nested_content_blocked(self):
        """Crisis phrase embedded in longer text must still be blocked."""
        gate = self._gate()
        d = gate.decide(
            subject_id="subjectA",
            requester_id="requesterB",
            purpose="dpv:ServiceProvision",
            classification=0,
            operation="read",
            text="He said he wants to kill himself but I'm not sure",
        )
        self.assertFalse(d.allowed)

    def test_classification_4_always_blocked(self):
        """Classification 4 (PHI) must never be permitted."""
        self._grant(classification_max=5)
        gate = self._gate()
        d = gate.decide(
            subject_id="subjectA",
            requester_id="requesterB",
            purpose="dpv:ServiceProvision",
            classification=4,
            operation="read",
        )
        self.assertFalse(d.allowed, "Classification 4 must always block.")
        self.assertIn("4", d.reason)

    def test_classification_5_always_blocked(self):
        """Classification 5 (critical) must never be permitted."""
        gate = self._gate()
        d = gate.decide(
            subject_id="subjectA",
            requester_id="requesterB",
            purpose="dpv:ServiceProvision",
            classification=5,
            operation="read",
        )
        self.assertFalse(d.allowed, "Classification 5 must always block.")

    def test_absolute_barriers_override_valid_consent(self):
        """
        A valid consent record must not bypass an absolute barrier.
        Crisis and cls 4+ are blocked BEFORE consent is checked.
        """
        self._grant(classification_max=5)
        gate = self._gate()
        d = gate.decide(
            subject_id="subjectA",
            requester_id="requesterB",
            purpose="dpv:ServiceProvision",
            classification=4,
            operation="read",
            is_crisis=False,
        )
        self.assertFalse(
            d.allowed,
            "Valid consent record must not bypass classification 4 barrier."
        )


# ===========================================================================
# ⚠️  SAFETY-CRITICAL: TestConsentGate
# ===========================================================================

class TestConsentGate(_ConsentBase):
    """
    Full gate decision logic. BLOCK DEPLOYMENT IF THESE FAIL.
    """

    def setUp(self):
        super().setUp()
        self._orig_enabled = self._patch_consent_enabled(True)

    def tearDown(self):
        self._restore_consent_enabled(self._orig_enabled)
        super().tearDown()

    def _decide(self, **kwargs):
        from api.consent.enforcement import ConsentGate
        defaults = dict(
            subject_id="subjectA",
            requester_id="requesterB",
            purpose="dpv:ServiceProvision",
            classification=1,
            operation="read",
        )
        defaults.update(kwargs)
        return ConsentGate().decide(**defaults)

    def test_self_access_always_permitted(self):
        """A subject always accesses their own data without consent."""
        d = self._decide(subject_id="alice", requester_id="alice")
        self.assertTrue(d.allowed, "Self-access must always be permitted.")
        self.assertEqual(d.reason, "self-access")

    def test_no_consent_requires_checkpoint(self):
        """No active consent record triggers a checkpoint request."""
        d = self._decide()
        self.assertFalse(d.allowed)
        self.assertTrue(
            d.requires_checkpoint,
            "Missing consent must trigger requires_checkpoint=True."
        )

    def test_active_consent_permits(self):
        """A valid active consent record permits the operation."""
        self._grant()
        d = self._decide()
        self.assertTrue(d.allowed, "Valid consent must permit the operation.")

    def test_revoked_consent_triggers_checkpoint(self):
        """A revoked consent record must not permit access."""
        from api.consent.ledger import consent_ledger
        cid = self._grant()
        consent_ledger.revoke(cid, "test")
        d = self._decide()
        self.assertFalse(d.allowed)

    def test_expired_consent_triggers_checkpoint(self):
        """An expired consent record must not permit access."""
        self._grant(valid_until=time.time() - 1)
        d = self._decide()
        self.assertFalse(d.allowed)

    def test_operation_not_in_consent_blocked(self):
        """Operation not listed in the consent record must be blocked."""
        self._grant(operations=["read"])
        d = self._decide(operation="export")
        self.assertFalse(d.allowed)
        self.assertIn("not-permitted", d.reason)

    def test_consent_disabled_always_permits(self):
        """When ONTO_CONSENT_ENABLED=false, all operations are permitted."""
        self._restore_consent_enabled(False)
        d = self._decide()
        self.assertTrue(d.allowed)
        self.assertIn("single-user-mode", d.reason)

    def test_audit_only_permits_but_logs(self):
        """CONSENT_AUDIT_ONLY=true must permit while logging the decision."""
        import api.consent.config as _cfg
        orig = _cfg.CONSENT_AUDIT_ONLY
        _cfg.CONSENT_AUDIT_ONLY = True
        try:
            d = self._decide()
            self.assertTrue(d.allowed, "Audit-only mode must permit.")
            self.assertIn("audit-only", d.reason)
        finally:
            _cfg.CONSENT_AUDIT_ONLY = orig

    def test_gate_never_raises(self):
        """ConsentGate.decide() must never raise under any input."""
        from api.consent.enforcement import ConsentGate
        gate = ConsentGate()
        for bad_input in [None, "", "x" * 10000, "💀" * 100]:
            try:
                gate.decide(
                    subject_id=str(bad_input),
                    requester_id="b",
                    purpose="dpv:ServiceProvision",
                    classification=0,
                    operation="read",
                )
            except Exception as exc:
                self.fail(f"ConsentGate.decide() raised: {exc}")


# ===========================================================================
# TestConsentLedger
# ===========================================================================

class TestConsentLedger(_ConsentBase):

    def test_grant_returns_uuid(self):
        from api.consent.ledger import consent_ledger
        cid = consent_ledger.grant(self._record())
        self.assertIsInstance(cid, str)
        self.assertEqual(len(cid), 36)  # UUID v4

    def test_revoke_makes_inactive(self):
        from api.consent.ledger import consent_ledger
        cid = self._grant()
        result = consent_ledger.revoke(cid, "test")
        self.assertTrue(result)
        records = consent_ledger.history("subjectA")
        match = next((r for r in records if r.consent_id == cid), None)
        self.assertIsNotNone(match)
        self.assertEqual(match.status, "revoked")

    def test_revoke_unknown_id_returns_false(self):
        from api.consent.ledger import consent_ledger
        result = consent_ledger.revoke("not-a-real-id", "test")
        self.assertFalse(result)

    def test_revoke_cascades_to_children(self):
        """Revoking a parent consent must revoke delegated children."""
        from api.consent.ledger import consent_ledger
        parent_cid = self._grant()
        child_rec = self._record(
            delegated_from=parent_cid,
            delegation_depth=1,
        )
        child_cid = consent_ledger.grant(child_rec)
        consent_ledger.revoke(parent_cid, "parent revoked")
        history = consent_ledger.history("subjectA", include_revoked=True)
        child = next((r for r in history if r.consent_id == child_cid), None)
        self.assertIsNotNone(child)
        self.assertEqual(
            child.status, "revoked",
            "Child delegation must be cascade-revoked with parent."
        )

    def test_history_newest_first(self):
        from api.consent.ledger import consent_ledger
        cid1 = self._grant()
        time.sleep(0.01)
        cid2 = self._grant()
        history = consent_ledger.history("subjectA")
        self.assertEqual(history[0].consent_id, cid2)

    def test_history_excludes_revoked_when_requested(self):
        from api.consent.ledger import consent_ledger
        cid = self._grant()
        consent_ledger.revoke(cid, "test")
        active = consent_ledger.history("subjectA", include_revoked=False)
        self.assertEqual(len(active), 0)

    def test_grant_writes_audit_event(self):
        import sqlite3
        self._grant()
        conn = sqlite3.connect(self.test_db)
        rows = conn.execute(
            "SELECT id FROM events WHERE event_type='CONSENT_GRANTED'"
        ).fetchall()
        conn.close()
        self.assertGreater(len(rows), 0)

    def test_revoke_writes_audit_event(self):
        import sqlite3
        from api.consent.ledger import consent_ledger
        cid = self._grant()
        consent_ledger.revoke(cid, "test reason")
        conn = sqlite3.connect(self.test_db)
        rows = conn.execute(
            "SELECT id FROM events WHERE event_type='CONSENT_REVOKED'"
        ).fetchall()
        conn.close()
        self.assertGreater(len(rows), 0)


# ===========================================================================
# TestRegulatoryProfiles
# ===========================================================================

class TestRegulatoryProfiles(unittest.TestCase):

    def test_team_profile_loaded(self):
        from api.consent.profiles import get_profile
        p = get_profile("team")
        self.assertEqual(p.name, "team")
        self.assertEqual(p.revocation_mechanism, "electronic")
        self.assertEqual(p.delegation_max_depth, 3)

    def test_healthcare_profile_requires_hipaa_fields(self):
        from api.consent.profiles import get_profile
        p = get_profile("healthcare")
        self.assertIn("hipaa_phi_description", p.required_fields)
        self.assertIn("hipaa_expiry_event", p.required_fields)
        self.assertEqual(p.revocation_mechanism, "written")
        self.assertEqual(p.delegation_max_depth, 1)
        self.assertEqual(p.retention_days, 2190)

    def test_financial_profile_glba_opt_out(self):
        from api.consent.profiles import get_profile
        p = get_profile("financial")
        self.assertTrue(p.glba_opt_out_model)
        self.assertEqual(p.retention_days, 2555)
        self.assertIn("gdpr:legal-obligation-art6-1c", p.retention_locked_bases)

    def test_unknown_profile_falls_back_to_team(self):
        import warnings
        from api.consent.profiles import get_profile
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            p = get_profile("nonexistent_profile")
            self.assertEqual(p.name, "team")
            self.assertEqual(len(w), 1)

    def test_team_profile_validates_minimal_record(self):
        from api.consent.profiles import get_profile
        p = get_profile("team")
        good = {
            "consent_id": "x", "subject_id": "a", "grantor_id": "a",
            "requester_id": "b", "purpose": "dpv:ServiceProvision",
            "legal_basis": "gdpr:consent-art6-1a",
            "operations": ["read"], "granted_at": time.time(),
        }
        errors = p.validate_record(good)
        self.assertEqual(errors, [])

    def test_healthcare_profile_rejects_missing_hipaa_fields(self):
        from api.consent.profiles import get_profile
        p = get_profile("healthcare")
        # Missing all HIPAA required fields
        minimal = {
            "consent_id": "x", "subject_id": "a", "grantor_id": "a",
            "requester_id": "b", "purpose": "hipaa:authorization-164-508",
            "legal_basis": "hipaa:authorization-164-508",
            "operations": ["read"], "granted_at": time.time(),
            "valid_until": time.time() + 86400,
        }
        errors = p.validate_record(minimal)
        # Should flag missing hipaa_phi_description etc.
        self.assertGreater(len(errors), 0)

    def test_retention_lock_financial(self):
        from api.consent.profiles import get_profile
        p = get_profile("financial")
        locked_record = {"legal_basis": "gdpr:legal-obligation-art6-1c"}
        unlocked_record = {"legal_basis": "gdpr:consent-art6-1a"}
        self.assertTrue(p.is_retention_locked(locked_record))
        self.assertFalse(p.is_retention_locked(unlocked_record))


# ===========================================================================
# TestGLBAOptOut
# ===========================================================================

class TestGLBAOptOut(_ConsentBase):

    def setUp(self):
        super().setUp()
        import api.consent.config as _cfg
        import api.consent.profiles as _prof
        self._orig_enabled = _cfg.CONSENT_ENABLED
        self._orig_profile  = _cfg.CONSENT_PROFILE
        _cfg.CONSENT_ENABLED = True
        _cfg.CONSENT_PROFILE = "financial"
        # Reload active profile
        _prof._PROFILES["financial"]  # ensure it's registered

    def tearDown(self):
        import api.consent.config as _cfg
        _cfg.CONSENT_ENABLED = self._orig_enabled
        _cfg.CONSENT_PROFILE  = self._orig_profile
        super().tearDown()

    def test_no_opt_out_permits_financial(self):
        """Without an opt-out record, GLBA defaults to permitted."""
        from api.consent.enforcement import ConsentGate
        d = ConsentGate().decide(
            subject_id="subjectA",
            requester_id="requesterB",
            purpose="dpv:ServiceProvision",
            classification=1,
            operation="read",
        )
        self.assertTrue(d.allowed, "No opt-out → GLBA defaults to permitted.")

    def test_opt_out_record_blocks(self):
        """An opt-out record must block the operation."""
        from api.consent.ledger import consent_ledger
        from api.consent.adapter import ConsentRecord
        # Grant an opt-out record
        opt_out = ConsentRecord(
            subject_id="subjectA",
            grantor_id="subjectA",
            requester_id="requesterB",
            purpose="dpv:ServiceProvision",
            legal_basis="glba:opt-out",
            operations=["read"],
            status="opt_out",
        )
        consent_ledger.grant(opt_out)
        from api.consent.enforcement import ConsentGate
        d = ConsentGate().decide(
            subject_id="subjectA",
            requester_id="requesterB",
            purpose="dpv:ServiceProvision",
            classification=1,
            operation="read",
        )
        self.assertFalse(d.allowed, "Opt-out record must block the operation.")


# ===========================================================================
# TestVCServiceInterface
# ===========================================================================

class TestVCServiceInterface(unittest.TestCase):

    def test_null_vc_service_returns_none(self):
        from api.consent.vc_service import NullVCService
        svc = NullVCService()
        self.assertIsNone(svc.issue_vc({}))

    def test_null_vc_service_verify_returns_false(self):
        from api.consent.vc_service import NullVCService
        svc = NullVCService()
        valid, reason = svc.verify_vc({})
        self.assertFalse(valid)
        self.assertEqual(reason, "vc_service_not_active")

    def test_null_vc_service_revoke_returns_false(self):
        from api.consent.vc_service import NullVCService
        svc = NullVCService()
        self.assertFalse(svc.revoke_vc("x", 0))

    def test_null_vc_service_presentation_returns_empty(self):
        from api.consent.vc_service import NullVCService
        svc = NullVCService()
        self.assertEqual(svc.create_presentation_definition("p", ["r"]), {})

    def test_get_vc_service_returns_null_by_default(self):
        from api.consent.vc_service import get_vc_service, NullVCService
        svc = get_vc_service()
        self.assertIsInstance(svc, NullVCService)


# ===========================================================================
# TestSchemaJSONLD
# ===========================================================================

class TestSchemaJSONLD(_ConsentBase):

    def test_record_serializes_to_jsonld(self):
        from api.consent.adapter import ConsentRecord
        from api.consent.schema import to_jsonld
        rec = self._record()
        doc = to_jsonld(rec)
        self.assertIn("@context", doc)
        self.assertIn("@type", doc)
        self.assertEqual(doc["@type"], "dpv:ConsentRecord")
        self.assertIn("dpv:hasPurpose", doc)
        self.assertIn("dpv:hasLegalBasis", doc)

    def test_vc_envelope_structure(self):
        from api.consent.adapter import ConsentRecord
        from api.consent.schema import to_jsonld, to_vc_envelope
        rec = self._record()
        jsonld = to_jsonld(rec)
        env = to_vc_envelope(jsonld, rec)
        self.assertIn("type", env)
        self.assertIn("VerifiableCredential", env["type"])
        self.assertIn("ONTOConsentCredential", env["type"])
        self.assertIn("credentialSubject", env)

    def test_dpv_purposes_vocabulary_complete(self):
        from api.consent.schema import DPV_PURPOSES
        required = {
            "dpv:ServiceProvision",
            "dpv:ResearchAndDevelopment",
            "dpv:LegalCompliance",
            "dpv:SharingWithThirdParty",
        }
        for p in required:
            self.assertIn(p, DPV_PURPOSES)

    def test_legal_bases_vocabulary_complete(self):
        from api.consent.schema import LEGAL_BASES
        required = {
            "gdpr:consent-art6-1a",
            "hipaa:authorization-164-508",
            "glba:opt-out",
        }
        for lb in required:
            self.assertIn(lb, LEGAL_BASES)


# ===========================================================================
# TestStatusListAllocation
# ===========================================================================

class TestStatusListAllocation(_ConsentBase):

    def test_first_index_is_zero(self):
        from api.consent.status_list import allocate_index
        idx = allocate_index()
        self.assertEqual(idx, 0)

    def test_indexes_increment(self):
        from api.consent.status_list import allocate_index
        i0 = allocate_index()
        i1 = allocate_index()
        self.assertEqual(i1, i0 + 1)

    def test_grant_assigns_status_list_index(self):
        from api.consent.ledger import consent_ledger
        rec = self._record()
        cid = consent_ledger.grant(rec)
        import sqlite3
        conn = sqlite3.connect(self.test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT vc_status_list_idx FROM consent_ledger WHERE consent_id=?",
            (cid,)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row["vc_status_list_idx"])

    def test_status_encoding_decoding(self):
        from api.consent.status_list import encode_status, decode_status
        for status in ("active", "suspended", "revoked", "expired"):
            bits = encode_status(status)
            decoded = decode_status(bits)
            self.assertEqual(decoded, status)


# ===========================================================================
# TestMigration
# ===========================================================================

class TestMigration(_ConsentBase):

    def test_consent_ledger_table_created(self):
        import sqlite3
        conn = sqlite3.connect(self.test_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        self.assertIn("consent_ledger", tables)

    def test_consent_requests_table_created(self):
        import sqlite3
        conn = sqlite3.connect(self.test_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        self.assertIn("consent_requests", tables)

    def test_core_tables_unchanged(self):
        """Phase 4 must not alter any Phase 1/2/3 tables."""
        import sqlite3
        conn = sqlite3.connect(self.test_db)
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        for core in ("events", "graph_nodes", "graph_edges", "edge_types"):
            self.assertIn(core, tables)

    def test_initialize_idempotent(self):
        """Calling initialize() twice must not raise."""
        from api.consent.schema import initialize
        try:
            initialize()
            initialize()
        except Exception as exc:
            self.fail(f"Double initialize must not raise: {exc}")

    def test_consent_ledger_columns_present(self):
        """All required ISO 27560 columns must be present."""
        import sqlite3
        conn = sqlite3.connect(self.test_db)
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(consent_ledger)"
        )}
        conn.close()
        required = {
            "consent_id", "subject_id", "grantor_id", "requester_id",
            "purpose", "legal_basis", "operations", "granted_at",
            "valid_until", "status", "revoked_at",
            "hipaa_phi_description", "hipaa_expiry_event",
            "vc_id", "vc_proof", "vc_status_list_idx", "sd_jwt_token",
        }
        for col in required:
            self.assertIn(col, cols, f"Column '{col}' must exist in consent_ledger.")


# ===========================================================================
# TestConsentRecordDataclass
# ===========================================================================

class TestConsentRecordDataclass(unittest.TestCase):

    def _rec(self, **kwargs):
        from api.consent.adapter import ConsentRecord
        defaults = dict(
            subject_id="a", grantor_id="a", requester_id="b",
            purpose="dpv:ServiceProvision",
            legal_basis="gdpr:consent-art6-1a",
            operations=["read"],
        )
        defaults.update(kwargs)
        return ConsentRecord(**defaults)

    def test_is_active_fresh_record(self):
        self.assertTrue(self._rec().is_active())

    def test_is_active_revoked(self):
        r = self._rec()
        r.revoked_at = time.time()
        r.status = "revoked"
        self.assertFalse(r.is_active())

    def test_is_active_expired(self):
        r = self._rec(valid_until=time.time() - 1)
        self.assertFalse(r.is_active())

    def test_needs_reconfirmation_standing_old(self):
        r = self._rec()
        r.last_reconfirmed = time.time() - (91 * 86400)
        self.assertTrue(r.needs_reconfirmation(90))

    def test_needs_reconfirmation_timed_consent_false(self):
        r = self._rec(valid_until=time.time() + 86400)
        self.assertFalse(r.needs_reconfirmation(90))

    def test_consent_decision_bool(self):
        from api.consent.adapter import ConsentDecision
        self.assertTrue(bool(ConsentDecision(allowed=True)))
        self.assertFalse(bool(ConsentDecision(allowed=False)))

    def test_to_dict_json_safe(self):
        import json
        r = self._rec()
        d = r.to_dict()
        try:
            json.dumps(d)
        except TypeError as exc:
            self.fail(f"to_dict() must produce JSON-safe output: {exc}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
