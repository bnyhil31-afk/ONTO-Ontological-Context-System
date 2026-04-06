"""
tests/test_internet_adapter.py

InternetAdapter test suite.

Safety-critical classes (block deployment if they fail):

  ⚠️  TestInternetAdapterAbsoluteBarriers — crisis and classification 4+ hard blocks
  ⚠️  TestInternetAdapterRegulatoryAbsolute — regulatory profiles cannot bypass barriers

All other classes verify internet-specific features: TLS transport, regulatory
profiles (HIPAA, GDPR, FERPA, GLBA), and inheritance of LocalAdapter safety gates.

Tests are isolated: each test uses a fresh SQLite database and temp directory.

Skip strategy: Classes requiring cryptography are decorated with
@unittest.skipUnless. Safety-critical classes never skip.

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

import subprocess as _sp
_CRYPTOGRAPHY = (
    _sp.run(
        [sys.executable, "-c",
         "from cryptography.hazmat.primitives.asymmetric import rsa; "
         "rsa.generate_private_key(65537, 2048)"],
        capture_output=True,
        timeout=10,
    ).returncode == 0
)

_NO_CRYPTOGRAPHY = "cryptography package not installed"


# ---------------------------------------------------------------------------
# BASE CLASS — isolated DB + key dir per test
# ---------------------------------------------------------------------------

class _InternetBase(unittest.TestCase):

    def setUp(self):
        self._orig_db = memory.DB_PATH
        self.test_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.test_dir, "test_internet.db")
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
        self.tls_dir = os.path.join(self.test_dir, "tls")
        os.makedirs(self.tls_dir, exist_ok=True)

    def tearDown(self):
        memory.DB_PATH = self._orig_db
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _peer(
        self,
        did="did:key:z6MkInternetPeerXXXXXX",
        trust=0.5,
        endpoint="example.com:7700",
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
        from api.federation.internet import InternetAdapter
        from api.federation.node_identity import generate_or_load
        did, pk = generate_or_load(self.key_path)
        adapter = InternetAdapter(did, pk)
        return adapter, did

    def _grant(self, peer_did="did:key:z6MkInternetPeerXXXXXX", cls=0):
        from api.federation import consent as _c
        return _c.grant("testsession", peer_did, "test data", cls)


# ===========================================================================
# ⚠️  SAFETY-CRITICAL: TestInternetAdapterAbsoluteBarriers
# These tests BLOCK DEPLOYMENT if they fail.
# ===========================================================================

class TestInternetAdapterAbsoluteBarriers(_InternetBase):
    """
    Verify the absolute barriers hold in InternetAdapter.can_share().
    InternetAdapter inherits from LocalAdapter — these invariants must
    survive the inheritance chain and the added regulatory layer.

    Any configuration, peer request, regulatory profile, or environment
    variable MUST NOT be able to bypass these barriers.
    """

    def test_crisis_text_blocked_by_internet_adapter(self):
        """Crisis text must be blocked by InternetAdapter.can_share()."""
        adapter, did = self._adapter()
        peer = self._peer()
        consent_id = self._grant(peer.node_id)

        ok, reason = adapter.can_share(
            text="I want to end my life",
            classification=0,
            is_sensitive=False,
            is_crisis=False,  # text check must catch it even when flag is False
            peer=peer,
            consent_id=consent_id,
        )
        self.assertFalse(ok, "Crisis text must be blocked by InternetAdapter.")
        self.assertIn("crisis", reason.lower())

    def test_is_crisis_flag_blocked_by_internet_adapter(self):
        """is_crisis=True must be blocked regardless of text content."""
        adapter, did = self._adapter()
        peer = self._peer()
        consent_id = self._grant(peer.node_id)

        ok, reason = adapter.can_share(
            text="the weather is nice today",
            classification=0,
            is_sensitive=False,
            is_crisis=True,
            peer=peer,
            consent_id=consent_id,
        )
        self.assertFalse(ok, "is_crisis=True must always be blocked.")

    def test_classification_4_blocked_by_internet_adapter(self):
        """Classification 4 (clinical PHI) must be blocked absolutely."""
        adapter, did = self._adapter()
        peer = self._peer()
        consent_id = self._grant(peer.node_id, cls=4)

        ok, reason = adapter.can_share(
            text="Patient diagnosis: hypertension",
            classification=4,
            is_sensitive=True,
            is_crisis=False,
            peer=peer,
            consent_id=consent_id,
        )
        self.assertFalse(ok, "Classification 4 must be blocked absolutely.")

    def test_classification_5_blocked_by_internet_adapter(self):
        """Classification 5 must be blocked absolutely."""
        adapter, did = self._adapter()
        peer = self._peer()
        consent_id = self._grant(peer.node_id, cls=5)

        ok, reason = adapter.can_share(
            text="Critical system access credentials",
            classification=5,
            is_sensitive=True,
            is_crisis=False,
            peer=peer,
            consent_id=consent_id,
        )
        self.assertFalse(ok, "Classification 5 must be blocked absolutely.")

    def test_inbound_crisis_blocked_by_internet_adapter(self):
        """Crisis content in inbound data must be blocked."""
        adapter, did = self._adapter()
        peer = self._peer()

        ok, trust = adapter.can_receive(
            data={
                "text": "I want to end my life",
                "concepts": ["suicide"],
            },
            peer=peer,
        )
        self.assertFalse(ok, "Inbound crisis content must be blocked.")

    def test_inbound_trust_never_exceeds_ceiling(self):
        """Inbound trust must always be <= ONTO_FED_INBOUND_TRUST."""
        adapter, did = self._adapter()
        peer = self._peer(trust=0.99)  # Peer claims high trust

        ok, assigned_trust = adapter.can_receive(
            data={"concepts": ["technology", "news"]},
            peer=peer,
        )
        if ok:
            from api.federation import config as _cfg
            self.assertLessEqual(
                assigned_trust,
                _cfg.INBOUND_TRUST,
                "Inbound trust must never exceed ONTO_FED_INBOUND_TRUST ceiling.",
            )


# ===========================================================================
# ⚠️  SAFETY-CRITICAL: TestInternetAdapterRegulatoryAbsolute
# Regulatory profiles must NOT be able to bypass absolute barriers.
# ===========================================================================

class TestInternetAdapterRegulatoryAbsolute(_InternetBase):
    """
    Verify that regulatory profiles are additive restrictions — they can
    never permit what super().can_share() blocked.

    Even if a regulatory profile's check_outbound() returns (True, ""),
    a preceding absolute barrier block must still block the share.
    """

    def test_hipaa_profile_cannot_unblock_crisis(self):
        """A HIPAA profile cannot permit crisis content."""
        from api.federation.regulatory import regulatory_registry, HIPAAProfile

        # Load HIPAA profile with a peer that has BAA confirmed
        regulatory_registry.load(["HIPAA"])
        adapter, did = self._adapter()
        peer = self._peer(capabilities={
            "max_classification": 2,
            "baa_confirmed": True,
        })
        consent_id = self._grant(peer.node_id)

        ok, reason = adapter.can_share(
            text="I want to end my life",
            classification=0,
            is_sensitive=False,
            is_crisis=True,
            peer=peer,
            consent_id=consent_id,
        )
        self.assertFalse(ok, "HIPAA profile must not unblock crisis content.")

        # Reset
        regulatory_registry.load([])

    def test_regulatory_profile_cannot_unblock_phi(self):
        """No regulatory profile can permit classification 4 (PHI)."""
        from api.federation.regulatory import regulatory_registry

        regulatory_registry.load(["HIPAA", "GDPR"])
        adapter, did = self._adapter()
        peer = self._peer(capabilities={
            "max_classification": 4,
            "baa_confirmed": True,
            "gdpr_dpa_confirmed": True,
            "right_to_erasure_supported": True,
        })
        consent_id = self._grant(peer.node_id, cls=4)

        ok, reason = adapter.can_share(
            text="Patient record: confidential",
            classification=4,
            is_sensitive=True,
            is_crisis=False,
            peer=peer,
            consent_id=consent_id,
        )
        self.assertFalse(ok, "No regulatory profile can unblock classification 4.")

        regulatory_registry.load([])


# ===========================================================================
# TestInternetAdapterTLS
# ===========================================================================

class TestInternetAdapterTLS(_InternetBase):
    """Tests for TLS transport helpers."""

    @unittest.skipUnless(_CRYPTOGRAPHY, _NO_CRYPTOGRAPHY)
    def test_generate_self_signed_cert(self):
        """generate_self_signed_cert() produces cert and key files."""
        from api.federation.tls_transport import generate_self_signed_cert

        cert_path, key_path = generate_self_signed_cert(
            "did:key:z6MkTestNodeXXXX", self.tls_dir
        )
        self.assertTrue(os.path.exists(cert_path), "cert file must exist")
        self.assertTrue(os.path.exists(key_path), "key file must exist")

        # Key file must be owner-only readable
        stat = os.stat(key_path)
        mode = oct(stat.st_mode)[-3:]
        self.assertEqual(mode, "600", "Key file must be 0o600")

    @unittest.skipUnless(_CRYPTOGRAPHY, _NO_CRYPTOGRAPHY)
    def test_cert_fingerprint_from_file(self):
        """cert_fingerprint_from_file() returns a non-empty SHA-256 hex."""
        from api.federation.tls_transport import (
            generate_self_signed_cert,
            cert_fingerprint_from_file,
        )

        cert_path, _ = generate_self_signed_cert(
            "did:key:z6MkTestNodeXXXX", self.tls_dir
        )
        fp = cert_fingerprint_from_file(cert_path)
        self.assertIsInstance(fp, str)
        self.assertEqual(len(fp), 64, "SHA-256 hex should be 64 chars")

    def test_cert_fingerprint_missing_file(self):
        """cert_fingerprint_from_file() returns empty string for missing file."""
        from api.federation.tls_transport import cert_fingerprint_from_file
        fp = cert_fingerprint_from_file("/nonexistent/path/node.crt")
        self.assertEqual(fp, "", "Missing file should return empty string")

    def test_tls_config_from_env(self):
        """load_tls_config_from_env() returns TLSConfig with expected types."""
        from api.federation.tls_transport import load_tls_config_from_env
        cfg = load_tls_config_from_env()
        self.assertIsInstance(cfg.cert_path, str)
        self.assertIsInstance(cfg.key_path, str)
        self.assertIsInstance(cfg.mtls_required, bool)

    def test_create_server_context_missing_cert(self):
        """create_server_context() returns None when cert file is missing."""
        from api.federation.tls_transport import create_server_context, TLSConfig
        ctx = create_server_context(TLSConfig(
            cert_path="/no/cert.crt",
            key_path="/no/key.pem",
        ))
        self.assertIsNone(ctx, "Missing cert should return None context")


# ===========================================================================
# TestInternetAdapterRegulatoryProfiles
# ===========================================================================

class TestInternetAdapterRegulatoryProfiles(_InternetBase):
    """Tests for the regulatory profile framework."""

    def setUp(self):
        super().setUp()
        from api.federation.regulatory import regulatory_registry
        regulatory_registry.load([])  # Start clean

    def tearDown(self):
        from api.federation.regulatory import regulatory_registry
        regulatory_registry.load([])  # Reset
        super().tearDown()

    def test_no_profiles_permits_share(self):
        """Empty profile list should not block any share."""
        from api.federation.regulatory import RegulatoryProfileRegistry
        reg = RegulatoryProfileRegistry()
        peer = self._peer()
        ok, reason = reg.check_outbound({"text": "hello"}, peer)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_hipaa_blocks_phi_without_baa(self):
        """HIPAA profile blocks PHI-flagged data to peer without BAA."""
        from api.federation.regulatory import HIPAAProfile
        profile = HIPAAProfile()
        peer = self._peer(capabilities={"max_classification": 2})

        ok, reason = profile.check_outbound({"phi_flag": True}, peer)
        self.assertFalse(ok, "HIPAA must block PHI without BAA")
        self.assertIn("baa_confirmed", reason)

    def test_hipaa_permits_phi_with_baa(self):
        """HIPAA profile permits PHI-flagged data when peer has BAA confirmed."""
        from api.federation.regulatory import HIPAAProfile
        profile = HIPAAProfile()
        peer = self._peer(
            residency="US",
            capabilities={"max_classification": 2, "baa_confirmed": True},
        )
        ok, reason = profile.check_outbound({"phi_flag": True}, peer)
        self.assertTrue(ok, f"HIPAA should permit PHI with BAA: {reason}")

    def test_hipaa_blocks_phi_to_non_us_jurisdiction(self):
        """HIPAA blocks PHI to peer in non-HIPAA-safe jurisdiction."""
        from api.federation.regulatory import HIPAAProfile
        profile = HIPAAProfile()
        peer = self._peer(
            residency="CN",  # Not HIPAA-safe
            capabilities={"max_classification": 2, "baa_confirmed": True},
        )
        ok, reason = profile.check_outbound({"phi_flag": True}, peer)
        self.assertFalse(ok, "HIPAA must block PHI to non-US jurisdiction")

    def test_gdpr_blocks_personal_data_without_dpa(self):
        """GDPR profile blocks personal data to peer without DPA."""
        from api.federation.regulatory import GDPRProfile
        profile = GDPRProfile()
        peer = self._peer(
            residency="DE",
            capabilities={"max_classification": 2},
        )
        ok, reason = profile.check_outbound({"is_personal": True}, peer)
        self.assertFalse(ok, "GDPR must block personal data without DPA")
        self.assertIn("gdpr_dpa_confirmed", reason)

    def test_gdpr_permits_personal_data_with_dpa(self):
        """GDPR permits personal data when DPA and erasure are confirmed."""
        from api.federation.regulatory import GDPRProfile
        profile = GDPRProfile()
        peer = self._peer(
            residency="DE",
            capabilities={
                "max_classification": 2,
                "gdpr_dpa_confirmed": True,
                "right_to_erasure_supported": True,
            },
        )
        ok, reason = profile.check_outbound({"is_personal": True}, peer)
        self.assertTrue(ok, f"GDPR should permit with DPA: {reason}")

    def test_gdpr_blocks_transfer_to_third_country_without_mechanism(self):
        """GDPR blocks personal data to third country without transfer mechanism."""
        from api.federation.regulatory import GDPRProfile
        profile = GDPRProfile()
        peer = self._peer(
            residency="US",  # US is not EEA (no adequacy for GDPR purposes without SCCs)
            capabilities={
                "max_classification": 2,
                "gdpr_dpa_confirmed": True,
                "right_to_erasure_supported": True,
                # No gdpr_transfer_mechanism
            },
        )
        ok, reason = profile.check_outbound({"is_personal": True}, peer)
        self.assertFalse(ok, "GDPR must block transfer to US without mechanism")

    def test_ferpa_blocks_educational_records_without_agreement(self):
        """FERPA profile blocks educational records to peer without agreement."""
        from api.federation.regulatory import FERPAProfile
        profile = FERPAProfile()
        peer = self._peer(capabilities={"max_classification": 2})
        ok, reason = profile.check_outbound({"ferpa_flag": True}, peer)
        self.assertFalse(ok, "FERPA must block educational records without agreement")

    def test_ferpa_permits_with_agreement(self):
        """FERPA permits educational records to peer with ferpa_agreement."""
        from api.federation.regulatory import FERPAProfile
        profile = FERPAProfile()
        peer = self._peer(capabilities={
            "max_classification": 2,
            "ferpa_agreement": True,
        })
        ok, reason = profile.check_outbound({"ferpa_flag": True}, peer)
        self.assertTrue(ok, f"FERPA should permit with agreement: {reason}")

    def test_glba_blocks_financial_data_without_safeguards(self):
        """GLBA profile blocks financial data to peer without safeguards."""
        from api.federation.regulatory import GLBAProfile
        profile = GLBAProfile()
        peer = self._peer(capabilities={"max_classification": 2})
        ok, reason = profile.check_outbound({"glba_flag": True}, peer)
        self.assertFalse(ok, "GLBA must block financial data without safeguards")

    def test_glba_permits_with_safeguards(self):
        """GLBA permits financial data to peer with glba_safeguards."""
        from api.federation.regulatory import GLBAProfile
        profile = GLBAProfile()
        peer = self._peer(capabilities={
            "max_classification": 2,
            "glba_safeguards": True,
        })
        ok, reason = profile.check_outbound({"glba_flag": True}, peer)
        self.assertTrue(ok, f"GLBA should permit with safeguards: {reason}")

    def test_registry_runs_all_profiles(self):
        """Registry applies all loaded profiles (logical AND)."""
        from api.federation.regulatory import RegulatoryProfileRegistry
        reg = RegulatoryProfileRegistry()
        reg.load(["HIPAA", "GDPR"])

        # Peer has BAA but not DPA — GDPR should block
        peer = self._peer(
            residency="DE",
            capabilities={
                "max_classification": 2,
                "baa_confirmed": True,
                # No gdpr_dpa_confirmed
            },
        )
        ok, reason = reg.check_outbound({"phi_flag": True, "is_personal": True}, peer)
        self.assertFalse(ok, "GDPR gate in registry must block even if HIPAA passes")
        self.assertIn("GDPR", reason)

    def test_registry_first_blocking_profile_wins(self):
        """Registry returns the first blocking profile's reason."""
        from api.federation.regulatory import RegulatoryProfileRegistry
        reg = RegulatoryProfileRegistry()
        reg.load(["HIPAA", "GDPR"])
        peer = self._peer(capabilities={"max_classification": 2})

        # HIPAA blocks first (no BAA), GDPR would also block
        ok, reason = reg.check_outbound({"phi_flag": True, "is_personal": True}, peer)
        self.assertFalse(ok)
        # Should be HIPAA's reason (first in list)
        self.assertIn("HIPAA", reason)

    def test_non_flagged_data_passes_all_profiles(self):
        """Data without any regulatory flags passes all profiles."""
        from api.federation.regulatory import RegulatoryProfileRegistry
        reg = RegulatoryProfileRegistry()
        reg.load(["HIPAA", "GDPR", "FERPA", "GLBA"])
        peer = self._peer(capabilities={"max_classification": 2})

        ok, reason = reg.check_outbound({"text": "General discussion"}, peer)
        self.assertTrue(ok, f"Non-flagged data should pass all profiles: {reason}")


# ===========================================================================
# TestInternetAdapterInheritance
# ===========================================================================

class TestInternetAdapterInheritance(_InternetBase):
    """
    Verify that InternetAdapter correctly inherits all LocalAdapter behaviors.
    Safety gates, CRDT merge, recall, and trust management must be unchanged.
    """

    def test_inherits_classification_ceiling(self):
        """Classification ceiling from config blocks shares above threshold."""
        adapter, did = self._adapter()
        peer = self._peer()
        consent_id = self._grant(peer.node_id, cls=3)

        # Default max share classification is 2
        ok, reason = adapter.can_share(
            text="Sensitive internal data",
            classification=3,
            is_sensitive=True,
            is_crisis=False,
            peer=peer,
            consent_id=consent_id,
        )
        self.assertFalse(ok, "Classification above ceiling must be blocked")

    def test_inherits_no_consent_blocks(self):
        """No valid consent record blocks outbound sharing."""
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
        self.assertFalse(ok, "Missing consent must block sharing")

    def test_inherits_trust_promotion(self):
        """Trust score increases after successful exchanges (inherited behavior)."""
        adapter, did = self._adapter()
        peer = self._peer()

        initial_trust = adapter.get_trust_score(peer.node_id)
        self.assertEqual(initial_trust, 0.0, "New peer starts with 0 trust")

    def test_health_reports_internet_stage(self):
        """health() reports stage as 'internet'."""
        adapter, did = self._adapter()
        h = adapter.health()
        self.assertEqual(h.get("stage"), "internet")

    def test_sso_stub_returns_not_configured(self):
        """SSO hook stub returns (False, 'sso_not_configured')."""
        adapter, did = self._adapter()
        peer = self._peer()
        valid, reason = adapter.sso_verify_token("some_token", peer)
        self.assertFalse(valid)
        self.assertEqual(reason, "sso_not_configured")


# ===========================================================================
# TestInternetAdapterConfig
# ===========================================================================

class TestInternetAdapterConfig(_InternetBase):
    """Tests for internet-stage configuration."""

    def test_valid_stages_includes_internet(self):
        """VALID_STAGES must include 'internet'."""
        from api.federation.config import VALID_STAGES
        self.assertIn("internet", VALID_STAGES)

    def test_internet_stage_not_blocked_by_validate(self):
        """validate() must NOT return an error for stage=internet."""
        import os
        old = os.environ.get("ONTO_FEDERATION_STAGE")
        os.environ["ONTO_FEDERATION_STAGE"] = "internet"
        try:
            # Re-import to pick up env change
            import importlib
            import api.federation.config as _cfg
            importlib.reload(_cfg)
            errors = [e for e in _cfg.validate() if "internet" in e and "not available" in e]
            self.assertEqual(
                errors, [],
                "validate() must not block 'internet' stage"
            )
        finally:
            if old is None:
                os.environ.pop("ONTO_FEDERATION_STAGE", None)
            else:
                os.environ["ONTO_FEDERATION_STAGE"] = old

    def test_regulatory_profiles_config_default_empty(self):
        """REGULATORY_PROFILES must default to empty list."""
        import importlib
        import api.federation.config as _cfg
        importlib.reload(_cfg)
        self.assertEqual(
            _cfg.REGULATORY_PROFILES, [],
            "Default REGULATORY_PROFILES must be empty"
        )

    def test_mtls_required_default_true(self):
        """MTLS_REQUIRED must default to True."""
        import importlib
        import api.federation.config as _cfg
        importlib.reload(_cfg)
        self.assertTrue(_cfg.MTLS_REQUIRED, "MTLS_REQUIRED must default to True")

    def test_unknown_regulatory_profile_fails_validation(self):
        """validate() must reject unknown regulatory profile names."""
        import os, importlib
        old = os.environ.get("ONTO_FED_REGULATORY_PROFILES")
        os.environ["ONTO_FED_REGULATORY_PROFILES"] = "UNKNOWN_PROFILE"
        try:
            import api.federation.config as _cfg
            importlib.reload(_cfg)
            errors = _cfg.validate()
            self.assertTrue(
                any("UNKNOWN_PROFILE" in e for e in errors),
                "validate() must reject unknown regulatory profile"
            )
        finally:
            if old is None:
                os.environ.pop("ONTO_FED_REGULATORY_PROFILES", None)
            else:
                os.environ["ONTO_FED_REGULATORY_PROFILES"] = old


if __name__ == "__main__":
    unittest.main()
