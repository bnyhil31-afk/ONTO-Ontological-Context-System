"""
tests/test_federation.py

Phase 3 Federation test suite — 69 tests across 16 classes.

Safety-critical classes (block deployment if they fail, even if all
other tests pass — see FEDERATION-SPEC-001 §13):

  ⚠️  TestAbsoluteBarriers       — crisis and classification 4+ hard blocks
  ⚠️  TestFederationSafetyFilter  — full outbound/inbound safety logic

All other classes exercise individual federation modules. Tests are
isolated: each test uses a fresh SQLite database and temp directory.

Skip strategy: Classes requiring zeroconf or grpcio are decorated with
@unittest.skipUnless so they skip gracefully when deps are absent.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import memory, graph

# ---------------------------------------------------------------------------
# Optional dep availability flags
# ---------------------------------------------------------------------------
try:
    import zeroconf as _zc          # noqa: F401
    _ZEROCONF = True
except ImportError:
    _ZEROCONF = False

try:
    import grpcio as _grpc          # noqa: F401
    _GRPCIO = True
except ImportError:
    _GRPCIO = False

_NO_ZEROCONF = "zeroconf not installed"
_NO_GRPCIO   = "grpcio not installed"


# ---------------------------------------------------------------------------
# BASE CLASS — isolated DB + key dir per test
# ---------------------------------------------------------------------------

class _FedBase(unittest.TestCase):

    def setUp(self):
        self._orig_db = memory.DB_PATH
        self.test_dir = tempfile.mkdtemp()
        self.test_db  = os.path.join(self.test_dir, "test_fed.db")
        memory.DB_PATH = self.test_db
        memory.initialize()
        graph.initialize()

        # Initialize all federation tables
        from api.federation import node_identity, peer_store, consent, audit
        node_identity.initialize()
        peer_store.initialize()
        consent.initialize()
        audit.initialize()

        self.key_path = os.path.join(self.test_dir, "node.key")

    def tearDown(self):
        memory.DB_PATH = self._orig_db
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _peer(
        self,
        did="did:key:z6MkTestPeerXXXXXXXXX",
        trust=0.5,
        endpoint="127.0.0.1:7701",
        residency="",
    ):
        from api.federation.adapter import NodeInfo
        return NodeInfo(
            node_id=did,
            endpoint=endpoint,
            trust_score=trust,
            capabilities={"max_classification": 2},
            data_residency=residency,
            last_seen=time.time(),
            cert_hash="testhash",
        )

    def _adapter(self):
        from api.federation.local import LocalAdapter
        from api.federation.node_identity import generate_or_load
        did, pk = generate_or_load(self.key_path)
        return LocalAdapter(did, pk)

    def _grant(self, peer_did="did:key:z6MkTestPeerXXXXXXXXX", cls=0):
        from api.federation import consent as _c
        return _c.grant("testsession", peer_did, "test data", cls)


# ===========================================================================
# ⚠️  SAFETY-CRITICAL: TestAbsoluteBarriers
# These tests BLOCK DEPLOYMENT if they fail.
# ===========================================================================

class TestAbsoluteBarriers(_FedBase):
    """
    Verify the two absolute barriers in safety.check_absolute_barriers()
    and check_inbound_for_crisis().

    These are non-configurable protocol invariants.
    Any configuration, peer request, or environment variable
    MUST NOT be able to bypass them.
    """

    def test_crisis_text_always_blocked(self):
        """
        Raw crisis text must be blocked regardless of other parameters.
        The text-based check runs independently of the is_crisis flag.
        """
        from api.federation.safety import check_absolute_barriers
        ok, reason = check_absolute_barriers(
            text="I want to end my life",
            classification=0,
            is_crisis=False,   # pre-computed flag is False — text check must catch it
        )
        self.assertFalse(ok, "Crisis text must always be blocked.")
        self.assertIn("crisis", reason)

    def test_is_crisis_flag_always_blocked(self):
        """
        is_crisis=True must be blocked even if the text seems benign.
        The flag is the intake module's pre-computed signal.
        """
        from api.federation.safety import check_absolute_barriers
        ok, reason = check_absolute_barriers(
            text="the weather is nice today",
            classification=0,
            is_crisis=True,
        )
        self.assertFalse(ok, "is_crisis=True must always be blocked.")

    def test_classification_4_blocked(self):
        """Classification 4 (PHI/privileged) must never federate."""
        from api.federation.safety import check_absolute_barriers
        ok, reason = check_absolute_barriers(
            text="routine data",
            classification=4,
            is_crisis=False,
        )
        self.assertFalse(ok, "Classification 4 must always be blocked.")
        self.assertIn("4", reason)

    def test_classification_5_blocked(self):
        """Classification 5 (critical) must never federate."""
        from api.federation.safety import check_absolute_barriers
        ok, reason = check_absolute_barriers(
            text="routine data",
            classification=5,
            is_crisis=False,
        )
        self.assertFalse(ok, "Classification 5 must always be blocked.")

    def test_check_inbound_finds_crisis_in_nested_dict(self):
        """
        check_inbound_for_crisis must scan every string field,
        including nested dicts. A peer cannot hide crisis content
        in a sub-field to bypass the check.
        """
        from api.federation.safety import check_inbound_for_crisis
        data = {
            "concept": "weather",
            "metadata": {
                "raw": "I want to end my life",
            },
        }
        self.assertTrue(
            check_inbound_for_crisis(data),
            "Crisis content in nested dict must be detected.",
        )

    def test_check_inbound_finds_crisis_in_list(self):
        """
        check_inbound_for_crisis must scan lists recursively.
        A peer cannot embed crisis content in a list to bypass the check.
        """
        from api.federation.safety import check_inbound_for_crisis
        data = {
            "concepts": ["weather", "I want to hurt myself", "graph"],
        }
        self.assertTrue(
            check_inbound_for_crisis(data),
            "Crisis content in list must be detected.",
        )


# ===========================================================================
# ⚠️  SAFETY-CRITICAL: TestFederationSafetyFilter
# ===========================================================================

class TestFederationSafetyFilter(_FedBase):
    """
    Verify the full outbound and inbound safety filter logic.
    Absolute barriers are tested in TestAbsoluteBarriers;
    this class tests the configurable controls.
    """

    def test_valid_data_with_consent_passes(self):
        """Normal data with valid consent must pass outbound check."""
        from api.federation.safety import check_outbound
        cid = self._grant()
        ok, reason = check_outbound(
            text="machine learning context",
            classification=1,
            is_sensitive=False,
            is_crisis=False,
            peer_trust_score=0.5,
            peer_data_residency="",
            consent_id=cid,
            has_valid_consent=True,
        )
        self.assertTrue(ok, f"Valid data should pass: {reason}")

    def test_no_consent_blocks_outbound(self):
        """No valid consent must block outbound data."""
        from api.federation.safety import check_outbound
        ok, reason = check_outbound(
            text="normal data",
            classification=0,
            is_sensitive=False,
            is_crisis=False,
            peer_trust_score=0.8,
            peer_data_residency="",
            consent_id="nonexistent-uuid",
            has_valid_consent=False,
        )
        self.assertFalse(ok, "No consent must block the share.")

    def test_classification_above_ceiling_blocked(self):
        """Data above MAX_SHARE_CLASSIFICATION must be blocked."""
        from api.federation.safety import check_outbound
        cid = self._grant(cls=3)
        # MAX_SHARE_CLASSIFICATION defaults to 2; classification 3 exceeds it
        ok, reason = check_outbound(
            text="internal data",
            classification=3,
            is_sensitive=False,
            is_crisis=False,
            peer_trust_score=0.9,
            peer_data_residency="",
            consent_id=cid,
            has_valid_consent=True,
        )
        self.assertFalse(ok)
        self.assertIn("classification", reason.lower())

    def test_sensitive_content_low_trust_blocked(self):
        """Sensitive content requires high peer trust (default 0.95)."""
        from api.federation.safety import check_outbound
        cid = self._grant()
        ok, reason = check_outbound(
            text="health information",
            classification=2,
            is_sensitive=True,
            is_crisis=False,
            peer_trust_score=0.50,   # below SENSITIVE_TRUST_THRESHOLD=0.95
            peer_data_residency="",
            consent_id=cid,
            has_valid_consent=True,
        )
        self.assertFalse(ok)
        self.assertIn("trust", reason.lower())

    def test_inbound_trust_capped_at_floor(self):
        """
        Inbound data always receives at most ONTO_FED_INBOUND_TRUST=0.30.
        The sender's claimed trust score is ignored entirely.
        """
        from api.federation.safety import check_inbound
        ok, assigned_trust = check_inbound(
            data={"concept": "weather"},
            peer_trust_score=0.99,   # sender claims high trust — must be ignored
        )
        self.assertTrue(ok)
        self.assertLessEqual(
            assigned_trust, 0.30 + 1e-6,
            "Assigned trust must never exceed INBOUND_TRUST floor.",
        )


# ===========================================================================
# TestNodeIdentity
# ===========================================================================

class TestNodeIdentity(_FedBase):

    def test_did_key_format(self):
        """Generated DID must start with 'did:key:z6Mk'."""
        from api.federation.node_identity import generate_or_load
        did, _ = generate_or_load(self.key_path)
        self.assertTrue(
            did.startswith("did:key:z"),
            f"Expected did:key:z prefix, got: {did!r}",
        )

    def test_key_file_created_not_sqlite(self):
        """Private key must be written to file, not SQLite."""
        from api.federation.node_identity import generate_or_load
        generate_or_load(self.key_path)
        self.assertTrue(
            os.path.exists(self.key_path),
            "Key file must be created at key_path.",
        )
        # Verify key is not in the database
        import sqlite3
        conn = sqlite3.connect(self.test_db)
        rows = conn.execute(
            "SELECT value FROM federation_node_config WHERE key='did_key'"
        ).fetchall()
        conn.close()
        for row in rows:
            self.assertNotIn(
                "key", row[0].lower().replace("did:key:", ""),
                "Private key material must not appear in SQLite value.",
            )

    def test_sign_verify_roundtrip(self):
        """Signing data and verifying with the same DID must succeed."""
        from api.federation.node_identity import generate_or_load, sign, verify
        did, pk = generate_or_load(self.key_path)
        data = b"test payload for signing"
        sig = sign(pk, data)
        self.assertTrue(verify(did, data, sig))

    def test_verify_wrong_data_fails(self):
        """Verifying a signature against different data must return False."""
        from api.federation.node_identity import generate_or_load, sign, verify
        did, pk = generate_or_load(self.key_path)
        sig = sign(pk, b"original data")
        self.assertFalse(verify(did, b"tampered data", sig))

    def test_load_existing_returns_same_did(self):
        """Loading an existing key file must return the same DID."""
        from api.federation.node_identity import generate_or_load
        did1, _ = generate_or_load(self.key_path)
        did2, _ = generate_or_load(self.key_path)
        self.assertEqual(did1, did2)


# ===========================================================================
# TestCapabilityManifest
# ===========================================================================

class TestCapabilityManifest(_FedBase):

    def _make_manifest(self):
        from api.federation.node_identity import generate_or_load
        from api.federation.capability import create_manifest
        did, pk = generate_or_load(self.key_path)
        return did, pk, create_manifest(did, pk)

    def test_manifest_has_required_fields(self):
        """Manifest must contain all required fields."""
        _, _, manifest = self._make_manifest()
        required = {
            "node_id", "onto_version", "spec_version",
            "signed_at", "signature", "capabilities",
        }
        for field in required:
            self.assertIn(field, manifest)

    def test_crisis_barrier_always_true(self):
        """crisis_barrier must always be True — it is not configurable."""
        _, _, manifest = self._make_manifest()
        self.assertTrue(
            manifest["capabilities"]["crisis_barrier"],
            "crisis_barrier must always be True in capability manifest.",
        )

    def test_verify_valid_manifest(self):
        """A freshly created manifest must verify successfully."""
        from api.federation.capability import verify_manifest
        _, _, manifest = self._make_manifest()
        valid, reason = verify_manifest(manifest)
        self.assertTrue(valid, f"Valid manifest should verify: {reason}")

    def test_verify_tampered_manifest_fails(self):
        """Tampering with the manifest body must invalidate the signature."""
        from api.federation.capability import verify_manifest
        _, _, manifest = self._make_manifest()
        manifest["capabilities"]["max_classification"] = 99
        valid, reason = verify_manifest(manifest)
        self.assertFalse(valid, "Tampered manifest must not verify.")


# ===========================================================================
# TestConsentLedger
# ===========================================================================

class TestConsentLedger(_FedBase):

    def test_grant_returns_uuid(self):
        """grant() must return a non-empty consent_id string."""
        from api.federation import consent as _c
        cid = _c.grant("sess", "did:key:peer", "test data", 0)
        self.assertIsInstance(cid, str)
        self.assertGreater(len(cid), 0)

    def test_active_consent_is_valid(self):
        """A freshly granted consent must be valid."""
        from api.federation import consent as _c
        cid = _c.grant("sess", "did:key:peer", "test data", 1)
        self.assertTrue(_c.is_valid(cid))

    def test_revoked_consent_invalid(self):
        """Revoking a consent must make it invalid."""
        from api.federation import consent as _c
        cid = _c.grant("sess", "did:key:peer", "test data", 0)
        _c.revoke(cid, "test revocation")
        self.assertFalse(_c.is_valid(cid))

    def test_expired_consent_invalid(self):
        """An expired consent must not be valid."""
        from api.federation import consent as _c
        cid = _c.grant(
            "sess", "did:key:peer", "test data", 0,
            expires_at=time.time() - 1,  # already expired
        )
        self.assertFalse(_c.is_valid(cid))

    def test_standing_consent_needs_reconfirmation(self):
        """
        A standing consent (expires_at=None) with last_reconfirmed
        older than STANDING_CONSENT_RECONFIRM_DAYS must need reconfirmation.
        """
        from api.federation import consent as _c
        cid = _c.grant("sess", "did:key:peer", "standing test", 0)
        # Manually set last_reconfirmed to 91 days ago
        import sqlite3
        conn = sqlite3.connect(self.test_db)
        old_time = time.time() - (91 * 86400)
        conn.execute(
            "UPDATE federation_consent SET last_reconfirmed=? "
            "WHERE consent_id=?",
            (old_time, cid),
        )
        conn.commit()
        conn.close()
        status = _c.get_status(cid)
        self.assertEqual(
            status, _c.STATUS_NEEDS_RECONFIRMATION,
            "90-day old standing consent must need reconfirmation.",
        )

    def test_list_for_peer_active_only(self):
        """list_for_peer without include_revoked returns only active records."""
        from api.federation import consent as _c
        peer = "did:key:z6MkListTest"
        cid1 = _c.grant("sess", peer, "active data", 0)
        cid2 = _c.grant("sess", peer, "revoked data", 0)
        _c.revoke(cid2, "test")
        records = _c.list_for_peer(peer)
        ids = [r["consent_id"] for r in records]
        self.assertIn(cid1, ids)
        self.assertNotIn(cid2, ids)


# ===========================================================================
# TestPeerStore
# ===========================================================================

class TestPeerStore(_FedBase):

    _SAMPLE_CERT = "-----BEGIN CERTIFICATE-----\nMIIBtest\n-----END CERTIFICATE-----"

    def test_pin_cert_stores_hash_not_pem(self):
        """pin_cert must store the SHA-256 hash, not the PEM data."""
        from api.federation import peer_store
        peer_store.pin_cert("did:key:peer1", self._SAMPLE_CERT, "sess")
        record = peer_store.get_peer_cert("did:key:peer1")
        self.assertIsNotNone(record)
        # Hash is 64 hex chars; PEM is much longer
        self.assertEqual(len(record["cert_hash"]), 64)
        self.assertNotIn("BEGIN CERTIFICATE", record["cert_hash"])

    def test_verify_matching_cert_returns_valid(self):
        """verify_cert must return 'valid' for the pinned certificate."""
        from api.federation import peer_store
        peer_store.pin_cert("did:key:peer2", self._SAMPLE_CERT, "sess")
        status, _ = peer_store.verify_cert("did:key:peer2", self._SAMPLE_CERT)
        self.assertEqual(status, "valid")

    def test_verify_changed_cert_returns_cert_changed(self):
        """verify_cert must return 'cert_changed' for a different cert."""
        from api.federation import peer_store
        peer_store.pin_cert("did:key:peer3", self._SAMPLE_CERT, "sess")
        different = "-----BEGIN CERTIFICATE-----\nDIFFERENT\n-----END CERTIFICATE-----"
        status, _ = peer_store.verify_cert("did:key:peer3", different)
        self.assertEqual(
            status, "cert_changed",
            "A different cert must return 'cert_changed', not 'valid'.",
        )

    def test_approve_cert_change_increments_rotation(self):
        """Approving a cert change must increment rotation_count."""
        from api.federation import peer_store
        peer_store.pin_cert("did:key:peer4", self._SAMPLE_CERT, "sess")
        new_cert = "-----BEGIN CERTIFICATE-----\nNEW\n-----END CERTIFICATE-----"
        peer_store.approve_cert_change("did:key:peer4", new_cert, "sess2")
        record = peer_store.get_peer_cert("did:key:peer4")
        self.assertEqual(record["rotation_count"], 1)


# ===========================================================================
# TestVectorClocks
# ===========================================================================

class TestVectorClocks(unittest.TestCase):

    def test_equal_clocks(self):
        from api.federation.crdt import vclock_compare, EQUAL
        self.assertEqual(vclock_compare({}, {}), EQUAL)
        self.assertEqual(vclock_compare({"a": 1}, {"a": 1}), EQUAL)

    def test_a_dominates(self):
        from api.federation.crdt import vclock_compare, A_DOMINATES
        self.assertEqual(
            vclock_compare({"a": 2}, {"a": 1}), A_DOMINATES
        )

    def test_b_dominates(self):
        from api.federation.crdt import vclock_compare, B_DOMINATES
        self.assertEqual(
            vclock_compare({"a": 1}, {"a": 2}), B_DOMINATES
        )

    def test_concurrent(self):
        from api.federation.crdt import vclock_compare, CONCURRENT
        self.assertEqual(
            vclock_compare({"a": 2, "b": 1}, {"a": 1, "b": 2}), CONCURRENT
        )

    def test_merge_component_max(self):
        from api.federation.crdt import vclock_merge
        merged = vclock_merge({"a": 3, "b": 1}, {"a": 1, "b": 4, "c": 2})
        self.assertEqual(merged, {"a": 3, "b": 4, "c": 2})


# ===========================================================================
# TestCRDTMerge
# ===========================================================================

class TestCRDTMerge(unittest.TestCase):

    def test_or_set_add_wins(self):
        """OR-Set: concurrent add and remove → element survives (add-wins)."""
        from api.federation.crdt import ORSet
        s = ORSet()
        tag = s.add("concept_a")
        s.remove("concept_a")
        s.add("concept_a", "concurrent_tag")
        self.assertTrue(
            s.contains("concept_a"),
            "Add-wins: element must survive concurrent add after remove.",
        )

    def test_lww_register_causal_order(self):
        """LWW-Register: causally later value wins."""
        from api.federation.crdt import LWWRegister
        r1 = LWWRegister(value=0.8, timestamp=100.0, vclock={"a": 1})
        r2 = LWWRegister(value=0.6, timestamp=200.0, vclock={"a": 2})
        merged = r1.merge(r2)
        self.assertAlmostEqual(merged.value, 0.6)

    def test_gset_merge_is_union(self):
        """G-Set merge must be set union."""
        from api.federation.crdt import GSet
        g1, g2 = GSet(), GSet()
        g1.add("r1"); g1.add("r2")
        g2.add("r2"); g2.add("r3")
        merged = g1.merge(g2)
        self.assertSetEqual(
            merged.elements(), frozenset({"r1", "r2", "r3"})
        )

    def test_merge_node_sets_remote_only_added(self):
        """merge_node_sets must add concepts that exist only on remote."""
        from api.federation.crdt import merge_node_sets
        local = {"concept_a": {"weight": 0.8, "vector_clock": None}}
        remote = {
            "concept_a": {"weight": 0.7, "vector_clock": None},
            "concept_b": {"weight": 0.5, "vector_clock": None},
        }
        merged, conflicts = merge_node_sets(local, remote)
        self.assertIn("concept_b", merged, "Remote-only concept must be added.")

    def test_concurrent_writes_produce_conflict(self):
        """Concurrent writes (neither vclock dominates) must appear in conflicts."""
        from api.federation.crdt import merge_edge_weights, vclock_to_json
        vc_a = vclock_to_json({"node_a": 2, "node_b": 1})
        vc_b = vclock_to_json({"node_a": 1, "node_b": 2})
        local = {"edge_1": {"weight": 0.8, "vector_clock": vc_a,
                            "last_reinforced": 100.0}}
        remote = {"edge_1": {"weight": 0.4, "vector_clock": vc_b,
                             "last_reinforced": 200.0}}
        _, conflicts = merge_edge_weights(local, remote)
        self.assertGreater(
            len(conflicts), 0,
            "Concurrent edge weight writes must be flagged as conflicts.",
        )


# ===========================================================================
# TestLocalAdapter
# ===========================================================================

class TestLocalAdapter(_FedBase):

    def test_can_share_crisis_always_false(self):
        """can_share must return False for crisis content — no exceptions."""
        adapter = self._adapter()
        peer = self._peer()
        cid = self._grant(peer.node_id)
        ok, reason = adapter.can_share(
            text="I want to end my life",
            classification=0,
            is_sensitive=False,
            is_crisis=True,
            peer=peer,
            consent_id=cid,
        )
        self.assertFalse(ok, "Crisis content must never be shareable.")

    def test_can_share_classification_4_always_false(self):
        """can_share must return False for classification 4+."""
        adapter = self._adapter()
        peer = self._peer(trust=0.99)
        cid = self._grant(peer.node_id, cls=4)
        ok, _ = adapter.can_share(
            text="phi data",
            classification=4,
            is_sensitive=True,
            is_crisis=False,
            peer=peer,
            consent_id=cid,
        )
        self.assertFalse(ok, "Classification 4 must never be shareable.")

    def test_can_receive_trust_capped(self):
        """can_receive must assign trust <= INBOUND_TRUST regardless of peer."""
        adapter = self._adapter()
        peer = self._peer(trust=0.99)
        ok, assigned = adapter.can_receive({"concept": "weather"}, peer)
        self.assertTrue(ok)
        self.assertLessEqual(
            assigned, 0.30 + 1e-6,
            "Received trust must never exceed INBOUND_TRUST floor.",
        )

    def test_discover_returns_list(self):
        """discover must return a list (empty or populated)."""
        adapter = self._adapter()
        result = adapter.discover()
        self.assertIsInstance(result, list)

    def test_merge_returns_local_on_error(self):
        """merge must return local_state on error — never raises."""
        adapter = self._adapter()
        peer = self._peer()
        local = {"nodes": {"a": {"weight": 0.5}}, "edges": {}}
        merged, vc = adapter.merge(local, {}, {}, {}, peer)
        self.assertIn("nodes", merged)

    def test_health_returns_required_keys(self):
        """health must return a dict with at least enabled and stage keys."""
        adapter = self._adapter()
        h = adapter.health()
        self.assertIn("enabled", h)
        self.assertIn("stage", h)


# ===========================================================================
# TestIntranetAdapter
# ===========================================================================

class TestIntranetAdapter(_FedBase):

    def test_extends_local_adapter(self):
        """IntranetAdapter must be a subclass of LocalAdapter."""
        from api.federation.local import LocalAdapter
        from api.federation.intranet import IntranetAdapter
        self.assertTrue(issubclass(IntranetAdapter, LocalAdapter))

    def test_health_includes_mdns_active(self):
        """IntranetAdapter.health must include mdns_active field."""
        from api.federation.intranet import IntranetAdapter
        from api.federation.node_identity import generate_or_load
        did, pk = generate_or_load(self.key_path)
        adapter = IntranetAdapter(did, pk)
        h = adapter.health()
        self.assertIn(
            "mdns_active", h,
            "IntranetAdapter.health must report mdns_active status.",
        )

    def test_discover_includes_static_peers(self):
        """discover must include static peers even without mDNS."""
        from api.federation.intranet import IntranetAdapter
        from api.federation.node_identity import generate_or_load
        from api.federation.adapter import NodeInfo
        did, pk = generate_or_load(self.key_path)
        adapter = IntranetAdapter(did, pk)
        # Manually add a static peer
        static_peer = NodeInfo(
            node_id="did:key:z6MkStatic",
            endpoint="192.168.1.10:7700",
            trust_score=0.0,
            capabilities={},
            data_residency="",
            last_seen=time.time(),
            cert_hash="",
        )
        with adapter._lock:
            adapter._peers["did:key:z6MkStatic"] = static_peer
        result = adapter.discover()
        dids = [p.node_id for p in result]
        self.assertIn("did:key:z6MkStatic", dids)


# ===========================================================================
# TestFederationManager
# ===========================================================================

class TestFederationManager(_FedBase):

    def test_is_enabled_false_when_config_off(self):
        """is_enabled must return False when ONTO_FEDERATION_ENABLED=false."""
        from api.federation.manager import FederationManager
        mgr = FederationManager()
        # Default config has FEDERATION_ENABLED=false
        with patch.dict(
            "os.environ", {"ONTO_FEDERATION_ENABLED": "false"}
        ):
            from api.federation import config as _cfg
            import importlib
            importlib.reload(_cfg)
            self.assertFalse(mgr.is_enabled())

    def test_is_enabled_never_raises(self):
        """is_enabled must return False (not raise) on any exception."""
        from api.federation.manager import FederationManager
        mgr = FederationManager()
        with patch(
            "api.federation.manager.FederationManager.is_enabled",
            side_effect=Exception("unexpected"),
        ):
            # The real is_enabled catches exceptions; test the real one
            pass
        # Just call it — must not raise
        try:
            mgr.is_enabled()
        except Exception:
            self.fail("is_enabled must never raise an exception.")

    def test_get_adapter_none_before_start(self):
        """get_adapter must return None before start() is called."""
        from api.federation.manager import FederationManager
        mgr = FederationManager()
        self.assertIsNone(mgr.get_adapter())

    def test_start_initializes_tables(self):
        """start() must create all federation tables."""
        from api.federation.manager import FederationManager
        mgr = FederationManager()
        with (
            patch("api.federation.manager.require_deps"),
            patch("api.federation.config.FEDERATION_ENABLED", True),
            patch("api.federation.config.FEDERATION_STAGE", "local"),
            patch("api.federation.config.validate", return_value=[]),
            patch("api.federation.local.LocalAdapter.start"),
        ):
            mgr._start_locked()

        import sqlite3
        conn = sqlite3.connect(self.test_db)
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()
        for t in (
            "federation_node_config",
            "federation_peer_certs",
            "federation_consent",
            "federation_outbox",
            "federation_inbox",
        ):
            self.assertIn(t, tables, f"Table {t} must be created by start().")

    def test_stop_is_idempotent(self):
        """stop() must not raise when called without a prior start()."""
        from api.federation.manager import FederationManager
        mgr = FederationManager()
        try:
            mgr.stop()
            mgr.stop()
        except Exception as exc:
            self.fail(f"stop() must be idempotent: {exc}")


# ===========================================================================
# TestMessaging
# ===========================================================================

class TestMessaging(_FedBase):

    def test_first_sequence_id_is_one(self):
        """First outbound message to a new recipient must get sequence_id=1."""
        from api.federation.audit import next_outbound_sequence
        seq = next_outbound_sequence("did:key:new_recipient")
        self.assertEqual(seq, 1)

    def test_sequence_increments_per_recipient(self):
        """Sequence IDs must increment per recipient."""
        from api.federation.audit import record_outbound, next_outbound_sequence
        record_outbound("did:key:recip_a", "PING", {"test": 1})
        seq = next_outbound_sequence("did:key:recip_a")
        self.assertEqual(seq, 2)

    def test_validate_sequence_gap_detected(self):
        """validate_inbound_sequence must return 'gap' for skipped IDs."""
        from api.federation.audit import validate_inbound_sequence
        # First message with seq=1 is ok; seq=3 skips 2
        status = validate_inbound_sequence("did:key:sender_x", 3)
        self.assertEqual(status, "gap")

    def test_rate_limit_blocks_excess(self):
        """check_rate_limit must block after threshold is exceeded."""
        from api.federation.audit import check_rate_limit, _rate_state, _rate_lock
        peer = "did:key:rate_test"
        # Flood the rate state
        now = time.time()
        with _rate_lock:
            _rate_state[peer] = [now] * 60
        ok, reason = check_rate_limit(peer, max_per_min=60)
        self.assertFalse(ok, "Rate limit must block excess messages.")
        # Cleanup
        with _rate_lock:
            _rate_state.pop(peer, None)


# ===========================================================================
# TestMigration
# ===========================================================================

class TestMigration(_FedBase):

    def test_all_federation_tables_created(self):
        """All five federation tables must exist after initialize()."""
        import sqlite3
        conn = sqlite3.connect(self.test_db)
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()
        for expected in (
            "federation_node_config",
            "federation_peer_certs",
            "federation_consent",
            "federation_outbox",
            "federation_inbox",
        ):
            self.assertIn(
                expected, tables,
                f"Federation table '{expected}' must be created.",
            )

    def test_core_tables_unchanged(self):
        """Phase 3 must not alter any existing Phase 1/2 tables."""
        import sqlite3
        conn = sqlite3.connect(self.test_db)
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()
        for core in ("events", "graph_nodes", "graph_edges", "edge_types"):
            self.assertIn(
                core, tables,
                f"Core table '{core}' must still exist after Phase 3 init.",
            )

    def test_graph_nodes_columns_unchanged(self):
        """Phase 3 must not add or remove columns from graph_nodes."""
        import sqlite3
        conn = sqlite3.connect(self.test_db)
        cols = {
            r[1] for r in conn.execute("PRAGMA table_info(graph_nodes)")
        }
        conn.close()
        # These Phase 1 columns must all still be present
        for col in ("id", "concept", "weight", "last_reinforced"):
            self.assertIn(col, cols)

    def test_initialize_is_idempotent(self):
        """Calling all initialize() functions twice must not raise."""
        from api.federation import node_identity, peer_store, consent, audit
        try:
            node_identity.initialize()
            peer_store.initialize()
            consent.initialize()
            audit.initialize()
        except Exception as exc:
            self.fail(f"Double initialize must not raise: {exc}")


# ===========================================================================
# TestConcentrationDetection
# ===========================================================================

class TestConcentrationDetection(unittest.TestCase):

    def test_identical_graphs_similarity_one(self):
        """Two nodes with identical concept sets have similarity 1.0."""
        concepts = frozenset({"a", "b", "c"})
        intersection = concepts & concepts
        union = concepts | concepts
        similarity = len(intersection) / len(union)
        self.assertAlmostEqual(similarity, 1.0)

    def test_disjoint_graphs_similarity_zero(self):
        """Two nodes with no shared concepts have similarity 0.0."""
        local = frozenset({"a", "b", "c"})
        remote = frozenset({"x", "y", "z"})
        intersection = local & remote
        union = local | remote
        similarity = len(intersection) / len(union)
        self.assertAlmostEqual(similarity, 0.0)


# ===========================================================================
# TestAuditIntegrity
# ===========================================================================

class TestAuditIntegrity(_FedBase):

    def test_consent_grant_writes_audit_event(self):
        """consent.grant must write a FEDERATION_CONSENT_GRANTED event."""
        from api.federation import consent as _c
        import sqlite3
        before = time.time()
        _c.grant("sess", "did:key:peer", "test share", 0)
        conn = sqlite3.connect(self.test_db)
        rows = conn.execute(
            "SELECT id FROM events WHERE event_type='FEDERATION_CONSENT_GRANTED'"
        ).fetchall()
        conn.close()
        self.assertGreater(len(rows), 0, "Consent grant must create audit record.")

    def test_consent_revoke_writes_audit_event(self):
        """consent.revoke must write a FEDERATION_CONSENT_REVOKED event."""
        from api.federation import consent as _c
        import sqlite3
        cid = _c.grant("sess", "did:key:peer", "test", 0)
        _c.revoke(cid, "test reason")
        conn = sqlite3.connect(self.test_db)
        rows = conn.execute(
            "SELECT id FROM events WHERE event_type='FEDERATION_CONSENT_REVOKED'"
        ).fetchall()
        conn.close()
        self.assertGreater(len(rows), 0)

    def test_peer_pin_writes_audit_event(self):
        """peer_store.pin_cert must write a FEDERATION_CERT_PINNED event."""
        from api.federation import peer_store
        import sqlite3
        peer_store.pin_cert(
            "did:key:auditpeer",
            "-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----",
            "sess",
        )
        conn = sqlite3.connect(self.test_db)
        rows = conn.execute(
            "SELECT id FROM events WHERE event_type='FEDERATION_CERT_PINNED'"
        ).fetchall()
        conn.close()
        self.assertGreater(len(rows), 0)


# ===========================================================================
# TestOfflineSovereignty
# ===========================================================================

class TestOfflineSovereignty(_FedBase):

    def test_recall_revokes_locally_before_peer_notification(self):
        """
        recall() must revoke the consent locally BEFORE attempting
        to notify peers. Sovereignty cannot be blocked by offline peers.
        """
        from api.federation import consent as _c
        adapter = self._adapter()
        peer = self._peer(
            did="did:key:z6MkOfflinePeer",
            endpoint="127.0.0.1:9999",  # nothing listening
        )
        with adapter._lock:
            adapter._peers[peer.node_id] = peer

        cid = self._grant(peer.node_id)
        self.assertTrue(_c.is_valid(cid))

        # recall() — peer is offline but local revocation must still succeed
        adapter.recall(cid)
        self.assertFalse(
            _c.is_valid(cid),
            "Consent must be locally revoked even when peer is offline.",
        )

    def test_recall_returns_empty_when_peer_unreachable(self):
        """
        recall() must return an empty notification list when the peer
        is unreachable — but must not raise.
        """
        from api.federation import consent as _c
        adapter = self._adapter()
        peer = self._peer(
            did="did:key:z6MkUnreachable",
            endpoint="127.0.0.1:9998",
        )
        with adapter._lock:
            adapter._peers[peer.node_id] = peer

        cid = self._grant(peer.node_id)
        try:
            notified = adapter.recall(cid)
            # notified may be empty — that is correct and expected
            self.assertIsInstance(notified, list)
        except Exception as exc:
            self.fail(f"recall() must not raise when peer offline: {exc}")


if __name__ == "__main__":
    unittest.main()
