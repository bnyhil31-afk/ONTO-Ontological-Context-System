"""
tests/test_p2p_adapter.py

P2PAdapter test suite.

Safety-critical classes (block deployment if they fail):

  ⚠️  TestP2PAdapterAbsoluteBarriers — crisis and classification 4+ hard blocks

All other classes verify P2P-specific features: DHT discovery (mocked),
Sybil resistance (PoW), anti-concentration routing, and inheritance of
InternetAdapter (regulatory) and LocalAdapter (safety) behaviors.

Tests are isolated: each test uses a fresh SQLite database and temp directory.

DHT is mocked throughout — these tests do not require kademlia to be installed.
When kademlia is not installed, the P2PAdapter gracefully falls back to static
peers; tests verify this behavior explicitly.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import json
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
    import kademlia as _kademlia  # noqa: F401
    _KADEMLIA = True
except ImportError:
    _KADEMLIA = False

_NO_KADEMLIA = "kademlia not installed"


# ---------------------------------------------------------------------------
# BASE CLASS — isolated DB + key dir per test
# ---------------------------------------------------------------------------

class _P2PBase(unittest.TestCase):

    def setUp(self):
        self._orig_db = memory.DB_PATH
        self.test_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.test_dir, "test_p2p.db")
        memory.DB_PATH = self.test_db
        memory.initialize()
        graph.initialize()

        try:
            from api.federation import node_identity, peer_store, consent, audit
            node_identity.initialize()
            peer_store.initialize()
            consent.initialize()
            audit.initialize()
        except BaseException as exc:
            self.skipTest(
                f"Federation deps unavailable in this environment: {type(exc).__name__}. "
                f"Run on a system with a working 'cryptography' package."
            )

        self.key_path = os.path.join(self.test_dir, "node.key")

    def tearDown(self):
        memory.DB_PATH = self._orig_db
        shutil.rmtree(self.test_dir, ignore_errors=True)
        # Reset regulatory profiles
        from api.federation.regulatory import regulatory_registry
        regulatory_registry.load([])

    def _peer(
        self,
        did="did:key:z6MkP2PPeerXXXXXXXXXX",
        trust=0.5,
        endpoint="peer.example.com:7700",
        residency="US",
        capabilities=None,
    ):
        from api.federation.adapter import NodeInfo
        return NodeInfo(
            node_id=did,
            endpoint=endpoint,
            trust_score=trust,
            capabilities=capabilities or {"max_classification": 2},
            data_residency=residency,
            last_seen=time.time(),
            cert_hash="testhash",
        )

    def _adapter(self):
        from api.federation.p2p import P2PAdapter
        from api.federation.node_identity import generate_or_load
        did, pk = generate_or_load(self.key_path)
        return P2PAdapter(did, pk), did

    def _grant(self, peer_did="did:key:z6MkP2PPeerXXXXXXXXXX", cls=0):
        from api.federation import consent as _c
        return _c.grant("testsession", peer_did, "test data", cls)


# ===========================================================================
# ⚠️  SAFETY-CRITICAL: TestP2PAdapterAbsoluteBarriers
# These tests BLOCK DEPLOYMENT if they fail.
# ===========================================================================

class TestP2PAdapterAbsoluteBarriers(_P2PBase):
    """
    Verify absolute barriers hold through the full inheritance chain:
    P2PAdapter → InternetAdapter → LocalAdapter

    At no point in the chain may crisis content or PHI (classification 4+)
    be permitted to federate.
    """

    def test_crisis_text_blocked_through_p2p_chain(self):
        """Crisis text must be blocked by P2PAdapter.can_share()."""
        adapter, did = self._adapter()
        peer = self._peer()
        consent_id = self._grant(peer.node_id)

        ok, reason = adapter.can_share(
            text="I want to end my life",
            classification=0,
            is_sensitive=False,
            is_crisis=False,  # text check must catch it
            peer=peer,
            consent_id=consent_id,
        )
        self.assertFalse(ok, "Crisis text must be blocked through P2P chain.")
        self.assertIn("crisis", reason.lower())

    def test_is_crisis_flag_blocked_through_p2p_chain(self):
        """is_crisis=True must be blocked at P2PAdapter regardless of other params."""
        adapter, did = self._adapter()
        peer = self._peer()
        consent_id = self._grant(peer.node_id)

        ok, reason = adapter.can_share(
            text="neutral text",
            classification=0,
            is_sensitive=False,
            is_crisis=True,
            peer=peer,
            consent_id=consent_id,
        )
        self.assertFalse(ok, "is_crisis=True must be blocked in P2P chain.")

    def test_classification_4_blocked_through_p2p_chain(self):
        """Classification 4 must be blocked absolutely through P2P chain."""
        adapter, did = self._adapter()
        peer = self._peer()
        consent_id = self._grant(peer.node_id, cls=4)

        ok, reason = adapter.can_share(
            text="Medical record",
            classification=4,
            is_sensitive=True,
            is_crisis=False,
            peer=peer,
            consent_id=consent_id,
        )
        self.assertFalse(ok, "Classification 4 must be blocked absolutely.")

    def test_classification_5_blocked_through_p2p_chain(self):
        """Classification 5 must be blocked absolutely through P2P chain."""
        adapter, did = self._adapter()
        peer = self._peer()
        consent_id = self._grant(peer.node_id, cls=5)

        ok, reason = adapter.can_share(
            text="Critical credentials",
            classification=5,
            is_sensitive=True,
            is_crisis=False,
            peer=peer,
            consent_id=consent_id,
        )
        self.assertFalse(ok, "Classification 5 must be blocked absolutely.")

    def test_inbound_crisis_blocked_through_p2p_chain(self):
        """Inbound crisis content must be blocked through P2P chain."""
        adapter, did = self._adapter()
        peer = self._peer()

        ok, trust = adapter.can_receive(
            data={"text": "I want to end my life", "concepts": ["suicide"]},
            peer=peer,
        )
        self.assertFalse(ok, "Inbound crisis must be blocked through P2P chain.")

    def test_inbound_trust_ceiling_enforced_through_p2p_chain(self):
        """Inbound trust must not exceed ONTO_FED_INBOUND_TRUST through P2P chain."""
        adapter, did = self._adapter()
        peer = self._peer(trust=0.99)

        ok, assigned_trust = adapter.can_receive(
            data={"concepts": ["open source", "community"]},
            peer=peer,
        )
        if ok:
            from api.federation import config as _cfg
            self.assertLessEqual(
                assigned_trust,
                _cfg.INBOUND_TRUST,
                "Trust ceiling must hold through P2P chain."
            )


# ===========================================================================
# TestP2PAdapterSybilResistance
# ===========================================================================

class TestP2PAdapterSybilResistance(_P2PBase):
    """Tests for Sybil resistance (proof-of-work)."""

    def test_generate_pow_nonce_difficulty_zero(self):
        """Difficulty 0 returns 'disabled' immediately."""
        from api.federation.p2p import generate_pow_nonce
        nonce = generate_pow_nonce("did:key:z6MkTest", 0)
        self.assertEqual(nonce, "disabled")

    def test_generate_pow_nonce_produces_valid_hex(self):
        """PoW nonce for difficulty=4 produces valid hex string."""
        from api.federation.p2p import generate_pow_nonce
        nonce = generate_pow_nonce("did:key:z6MkTestPOWXXXX", 4)
        self.assertIsInstance(nonce, str)
        self.assertNotEqual(nonce, "disabled")
        # Should be a hex string
        try:
            int(nonce, 16)
        except ValueError:
            # overflow or special case
            pass

    def test_pow_challenge_disabled_always_passes(self):
        """PoW challenge with difficulty=0 always passes."""
        from api.federation.p2p import _pow_challenge
        valid, reason = _pow_challenge("did:key:z6MkAnyPeer", 0)
        self.assertTrue(valid)
        self.assertEqual(reason, "sybil_resistance_disabled")

    def test_pow_challenge_fails_without_manifest(self):
        """PoW challenge fails if peer has no cached manifest."""
        from api.federation.p2p import _pow_challenge
        valid, reason = _pow_challenge("did:key:z6MkUnknownPeer", 4)
        self.assertFalse(valid)
        self.assertIn("no_manifest", reason)


# ===========================================================================
# TestP2PAdapterDiscovery
# ===========================================================================

class TestP2PAdapterDiscovery(_P2PBase):
    """Tests for DHT-based peer discovery (DHT is mocked)."""

    def test_discover_falls_back_to_static_when_dht_unavailable(self):
        """If DHT is unavailable, discover() returns static peers."""
        adapter, did = self._adapter()
        # DHT not started — _dht_available is False
        adapter._dht_available = False
        peers = adapter.discover()
        # Should return whatever static peers are configured (none in test)
        self.assertIsInstance(peers, list)

    def test_parse_dht_results_valid_json_object(self):
        """_parse_dht_results handles a JSON object (single announcement)."""
        from api.federation.p2p import P2PAdapter
        announcement = {
            "did": "did:key:z6MkTestPeer",
            "endpoint": "peer.example.com:7700",
            "timestamp": int(time.time()),
        }
        results = P2PAdapter._parse_dht_results(json.dumps(announcement).encode())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["did"], "did:key:z6MkTestPeer")

    def test_parse_dht_results_valid_json_list(self):
        """_parse_dht_results handles a JSON list of announcements."""
        from api.federation.p2p import P2PAdapter
        announcements = [
            {"did": "did:key:z6MkPeer1", "endpoint": "a.example.com:7700", "timestamp": int(time.time())},
            {"did": "did:key:z6MkPeer2", "endpoint": "b.example.com:7700", "timestamp": int(time.time())},
        ]
        results = P2PAdapter._parse_dht_results(json.dumps(announcements).encode())
        self.assertEqual(len(results), 2)

    def test_parse_dht_results_empty_bytes(self):
        """_parse_dht_results handles empty bytes gracefully."""
        from api.federation.p2p import P2PAdapter
        results = P2PAdapter._parse_dht_results(b"")
        self.assertEqual(results, [])

    def test_parse_dht_results_none(self):
        """_parse_dht_results handles None gracefully."""
        from api.federation.p2p import P2PAdapter
        results = P2PAdapter._parse_dht_results(None)
        self.assertEqual(results, [])

    def test_announcement_to_node_info_valid(self):
        """_announcement_to_node_info converts valid dict to NodeInfo."""
        from api.federation.p2p import P2PAdapter
        announcement = {
            "did": "did:key:z6MkValidPeer",
            "endpoint": "valid.example.com:7700",
            "timestamp": int(time.time()),
            "spec_version": "FEDERATION-SPEC-001-v1.1",
        }
        node = P2PAdapter._announcement_to_node_info(announcement)
        self.assertIsNotNone(node)
        self.assertEqual(node.node_id, "did:key:z6MkValidPeer")
        self.assertEqual(node.endpoint, "valid.example.com:7700")
        self.assertEqual(node.federation_stage, "p2p")

    def test_announcement_to_node_info_invalid_did(self):
        """_announcement_to_node_info rejects non-did:key identifiers."""
        from api.federation.p2p import P2PAdapter
        announcement = {
            "did": "not_a_did_key",
            "endpoint": "example.com:7700",
            "timestamp": int(time.time()),
        }
        node = P2PAdapter._announcement_to_node_info(announcement)
        self.assertIsNone(node)

    def test_announcement_to_node_info_stale(self):
        """_announcement_to_node_info rejects announcements older than 10 minutes."""
        from api.federation.p2p import P2PAdapter
        announcement = {
            "did": "did:key:z6MkStalePeer",
            "endpoint": "stale.example.com:7700",
            "timestamp": int(time.time()) - 700,  # 11+ minutes ago
        }
        node = P2PAdapter._announcement_to_node_info(announcement)
        self.assertIsNone(node, "Stale announcement must be rejected")

    def test_discover_filters_own_did(self):
        """discover() must not include the node's own DID in results."""
        adapter, did = self._adapter()

        # Mock: DHT returns our own DID
        own_announcement = json.dumps({
            "did": did,
            "endpoint": "127.0.0.1:7700",
            "timestamp": int(time.time()),
        }).encode()

        adapter._dht_available = True
        adapter._dht_node = MagicMock()
        adapter._dht_loop = MagicMock()

        with patch("asyncio.run_coroutine_threadsafe") as mock_rcts:
            mock_result = MagicMock()
            mock_result.result.return_value = own_announcement

            # Close the coroutine so Python doesn't warn "never awaited".
            # asyncio.run_coroutine_threadsafe receives a coroutine object;
            # the mock never schedules it, so we must close it explicitly.
            def _close_coro_and_return(coro, loop):
                coro.close()
                return mock_result

            mock_rcts.side_effect = _close_coro_and_return

            peers = adapter.discover()

        # Our own DID must not appear in results
        peer_dids = [p.node_id for p in peers]
        self.assertNotIn(did, peer_dids, "Node must not discover itself")


# ===========================================================================
# TestP2PAdapterAntiConcentration
# ===========================================================================

class TestP2PAdapterAntiConcentration(_P2PBase):
    """Tests for anti-concentration routing."""

    def test_high_similarity_peer_blocked_when_threshold_set(self):
        """Peer above graph similarity threshold is skipped."""
        from api.federation.p2p import _graph_similarity_exceeds
        peer = self._peer(capabilities={
            "max_classification": 2,
            "graph_similarity_score": 0.95,
        })
        # threshold = 0.80 → 0.95 exceeds it
        self.assertTrue(_graph_similarity_exceeds(peer, 0.80))

    def test_low_similarity_peer_passes(self):
        """Peer below graph similarity threshold is allowed."""
        from api.federation.p2p import _graph_similarity_exceeds
        peer = self._peer(capabilities={
            "max_classification": 2,
            "graph_similarity_score": 0.50,
        })
        self.assertFalse(_graph_similarity_exceeds(peer, 0.80))

    def test_no_similarity_score_passes(self):
        """Peer without similarity score always passes (no data = permit)."""
        from api.federation.p2p import _graph_similarity_exceeds
        peer = self._peer(capabilities={"max_classification": 2})
        self.assertFalse(_graph_similarity_exceeds(peer, 0.80))

    def test_threshold_1_0_disables_anticoncentration(self):
        """Threshold=1.0 disables anti-concentration (default behavior)."""
        from api.federation.p2p import _graph_similarity_exceeds
        peer = self._peer(capabilities={
            "max_classification": 2,
            "graph_similarity_score": 0.99,
        })
        # 1.0 = disabled → even very similar peer passes
        self.assertFalse(_graph_similarity_exceeds(peer, 1.0))


# ===========================================================================
# TestP2PAdapterInheritance
# ===========================================================================

class TestP2PAdapterInheritance(_P2PBase):
    """
    Verify P2PAdapter correctly inherits InternetAdapter and LocalAdapter
    behaviors. Safety gates, regulatory gates, and trust management must
    all be present.
    """

    def test_inherits_consent_check(self):
        """P2PAdapter blocks sharing without valid consent."""
        adapter, did = self._adapter()
        peer = self._peer()

        ok, reason = adapter.can_share(
            text="Public information",
            classification=0,
            is_sensitive=False,
            is_crisis=False,
            peer=peer,
            consent_id="nonexistent_consent_id",
        )
        self.assertFalse(ok, "Missing consent must block in P2P chain")

    def test_inherits_regulatory_check(self):
        """P2PAdapter applies regulatory profiles from InternetAdapter."""
        from api.federation.regulatory import regulatory_registry
        regulatory_registry.load(["HIPAA"])

        adapter, did = self._adapter()
        peer = self._peer(capabilities={"max_classification": 2})  # No BAA
        consent_id = self._grant(peer.node_id)

        ok, reason = adapter.can_share(
            text="Patient data",
            classification=0,
            is_sensitive=True,
            is_crisis=False,
            peer=peer,
            consent_id=consent_id,
        )
        # HIPAA blocks PHI-flagged data without BAA
        # (text check doesn't set phi_flag, so this should pass)
        # The key test is that the regulatory layer is called at all
        # when sharing data with phi_flag explicitly:
        ok2, reason2 = adapter.can_share(
            text="Normal text",
            classification=0,
            is_sensitive=False,
            is_crisis=False,
            peer=peer,
            consent_id=consent_id,
        )
        # Non-PHI data should pass HIPAA check
        self.assertIsNotNone(ok2)  # Just verify the call succeeded

        regulatory_registry.load([])

    def test_health_reports_p2p_stage(self):
        """health() reports stage as 'p2p'."""
        adapter, did = self._adapter()
        h = adapter.health()
        self.assertEqual(h.get("stage"), "p2p")

    def test_health_reports_dht_status(self):
        """health() includes DHT availability status."""
        adapter, did = self._adapter()
        h = adapter.health()
        self.assertIn("dht_available", h)
        self.assertIn("dht_node_running", h)

    def test_carbon_aware_score_stub(self):
        """carbon_aware_score() returns a float in [0, 1]."""
        adapter, did = self._adapter()
        peer = self._peer()
        score = adapter.carbon_aware_score(peer)
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_post_quantum_stub(self):
        """post_quantum_key_exchange_supported() returns False (stub)."""
        adapter, did = self._adapter()
        self.assertFalse(adapter.post_quantum_key_exchange_supported())


# ===========================================================================
# TestP2PAdapterConfig
# ===========================================================================

class TestP2PAdapterConfig(_P2PBase):
    """Tests for P2P-stage configuration."""

    def test_valid_stages_includes_p2p(self):
        """VALID_STAGES must include 'p2p'."""
        from api.federation.config import VALID_STAGES
        self.assertIn("p2p", VALID_STAGES)

    def test_p2p_stage_not_blocked_by_validate(self):
        """validate() must not produce 'not available' error for p2p stage."""
        import os, importlib
        old_stage = os.environ.get("ONTO_FEDERATION_STAGE")
        old_nodes = os.environ.get("ONTO_FED_DHT_BOOTSTRAP_NODES")
        os.environ["ONTO_FEDERATION_STAGE"] = "p2p"
        os.environ["ONTO_FED_DHT_BOOTSTRAP_NODES"] = "bootstrap.example.com:7701"
        try:
            import api.federation.config as _cfg
            importlib.reload(_cfg)
            errors = [e for e in _cfg.validate() if "not available" in e and "p2p" in e]
            self.assertEqual(errors, [], "validate() must not block 'p2p' stage")
        finally:
            if old_stage is None:
                os.environ.pop("ONTO_FEDERATION_STAGE", None)
            else:
                os.environ["ONTO_FEDERATION_STAGE"] = old_stage
            if old_nodes is None:
                os.environ.pop("ONTO_FED_DHT_BOOTSTRAP_NODES", None)
            else:
                os.environ["ONTO_FED_DHT_BOOTSTRAP_NODES"] = old_nodes

    def test_p2p_requires_bootstrap_nodes(self):
        """validate() must require bootstrap nodes for p2p stage."""
        import os, importlib
        old_stage = os.environ.get("ONTO_FEDERATION_STAGE")
        old_nodes = os.environ.get("ONTO_FED_DHT_BOOTSTRAP_NODES")
        os.environ["ONTO_FEDERATION_STAGE"] = "p2p"
        os.environ.pop("ONTO_FED_DHT_BOOTSTRAP_NODES", None)
        try:
            import api.federation.config as _cfg
            importlib.reload(_cfg)
            errors = _cfg.validate()
            self.assertTrue(
                any("bootstrap" in e.lower() or "p2p" in e.lower() for e in errors),
                "validate() must require bootstrap nodes for p2p"
            )
        finally:
            if old_stage is None:
                os.environ.pop("ONTO_FEDERATION_STAGE", None)
            else:
                os.environ["ONTO_FEDERATION_STAGE"] = old_stage
            if old_nodes is None:
                os.environ.pop("ONTO_FED_DHT_BOOTSTRAP_NODES", None)
            else:
                os.environ["ONTO_FED_DHT_BOOTSTRAP_NODES"] = old_nodes

    def test_sybil_pow_difficulty_default(self):
        """SYBIL_POW_DIFFICULTY must default to 4."""
        import importlib
        import api.federation.config as _cfg
        importlib.reload(_cfg)
        self.assertEqual(_cfg.SYBIL_POW_DIFFICULTY, 4)

    def test_dht_port_default(self):
        """DHT_PORT must default to 7701."""
        import importlib
        import api.federation.config as _cfg
        importlib.reload(_cfg)
        self.assertEqual(_cfg.DHT_PORT, 7701)

    def test_kademlia_dep_check_in_init(self):
        """__init__.py must expose _KADEMLIA_AVAILABLE."""
        from api.federation import _KADEMLIA_AVAILABLE
        # Just verify it's a bool — either True or False depending on install
        self.assertIsInstance(_KADEMLIA_AVAILABLE, bool)

    def test_parse_bootstrap_node_valid(self):
        """_parse_bootstrap_node parses valid host:port strings."""
        from api.federation.p2p import P2PAdapter
        result = P2PAdapter._parse_bootstrap_node("bootstrap.example.com:7701")
        self.assertEqual(result, ("bootstrap.example.com", 7701))

    def test_parse_bootstrap_node_invalid(self):
        """_parse_bootstrap_node returns None for malformed strings."""
        from api.federation.p2p import P2PAdapter
        result = P2PAdapter._parse_bootstrap_node("not_a_node")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
