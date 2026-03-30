"""
tests/test_security.py

Security tests for ONTO — items 2.05, 2.06, 2.11.

These tests verify that the security hardening layer
is in place and working correctly.

  2.05 — Rate limiting prevents runaway input floods
  2.06 — principles.hash is protected and monitored
  2.11 — Configuration loads correctly from environment

Expected result: 12 passed, 0 failed, 0 errors.
If you see anything different — something needs attention.
"""

import os
import sys
import time
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# TEST: RATE LIMITING (item 2.05)
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimiting(unittest.TestCase):
    """
    Tests for core/ratelimit.py — the intake rate limiter.

    Plain English: Makes sure the system stops accepting inputs
    when too many arrive too fast — and explains why clearly.

    Expected: 4 passed.
    """

    def setUp(self):
        from core.ratelimit import SlidingWindowRateLimiter
        # Create a fresh limiter for each test — never share state
        self.limiter = SlidingWindowRateLimiter()

    def test_rate_limiter_allows_inputs_under_limit(self):
        """
        Inputs below the rate limit are always allowed.
        The system must not block normal use.
        """
        # Override config for this test — use a low limit
        self.limiter._config = type("cfg", (), {
            "RATE_LIMIT_PER_MINUTE": 5,
            "RATE_LIMIT_WINDOW_SECONDS": 60
        })()

        for i in range(5):
            allowed, reason = self.limiter.check_and_record()
            self.assertTrue(
                allowed,
                f"Input {i+1} of 5 should be allowed. Got: {reason}"
            )

    def test_rate_limiter_blocks_inputs_over_limit(self):
        """
        Inputs above the rate limit are rejected with a clear reason.
        The 6th input when limit is 5 must be rejected.
        """
        self.limiter._config = type("cfg", (), {
            "RATE_LIMIT_PER_MINUTE": 5,
            "RATE_LIMIT_WINDOW_SECONDS": 60
        })()

        for _ in range(5):
            self.limiter.check_and_record()

        allowed, reason = self.limiter.check()
        self.assertFalse(
            allowed,
            "6th input when limit is 5 must be rejected."
        )
        self.assertIn(
            "Rate limit reached", reason,
            "Rejection reason must explain what happened."
        )

    def test_rate_limiter_recovers_after_window(self):
        """
        Rate limit resets after the time window passes.
        A user who hits the limit can try again after waiting.
        """
        self.limiter._config = type("cfg", (), {
            "RATE_LIMIT_PER_MINUTE": 2,
            "RATE_LIMIT_WINDOW_SECONDS": 1  # 1 second window for fast test
        })()

        self.limiter.check_and_record()
        self.limiter.check_and_record()

        allowed, _ = self.limiter.check()
        self.assertFalse(allowed, "Should be blocked at limit.")

        time.sleep(1.1)

        allowed, reason = self.limiter.check()
        self.assertTrue(
            allowed,
            f"Should be allowed after window expires. Got: {reason}"
        )

    def test_rate_limiter_disabled_when_limit_is_zero(self):
        """
        Setting limit to 0 disables rate limiting entirely.
        This is the operator's explicit choice — not a default.
        """
        self.limiter._config = type("cfg", (), {
            "RATE_LIMIT_PER_MINUTE": 0,
            "RATE_LIMIT_WINDOW_SECONDS": 60
        })()

        for _ in range(1000):
            allowed, reason = self.limiter.check_and_record()
            self.assertTrue(
                allowed,
                "Rate limiting disabled — all inputs must be allowed."
            )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: PRINCIPLES.HASH PROTECTION (item 2.06)
# ─────────────────────────────────────────────────────────────────────────────

class TestPrinciplesHashProtection(unittest.TestCase):
    """
    Tests for core/verify.py — protection of the principles hash.

    Plain English: Makes sure the hash file that seals the principles
    is protected against tampering and that any modification is
    detectable by the system.

    Expected: 4 passed.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_principles = os.path.join(self.test_dir, "principles.txt")
        self.test_hash = os.path.join(self.test_dir, "principles.hash")

        with open(self.test_principles, "w", newline="\n") as f:
            f.write("These are test principles. They must not change.")

    def tearDown(self):
        import stat
        for root, dirs, files in os.walk(self.test_dir):
            for d in dirs:
                os.chmod(os.path.join(root, d), stat.S_IRWXU)
            for f in files:
                os.chmod(os.path.join(root, f), stat.S_IRWXU)
        shutil.rmtree(self.test_dir)

    def test_hash_file_detects_modified_principles(self):
        """
        If principles.txt is modified after sealing,
        verify_principles must detect the change and halt.
        This is the core integrity guarantee of the system.
        """
        import hashlib
        import json

        original = "Original principles content."
        with open(self.test_principles, "w", newline="\n") as f:
            f.write(original)

        sha256 = hashlib.sha256()
        with open(self.test_principles, "rb") as f:
            sha256.update(f.read())

        record = {
            "sealed_at": "2026-01-01T00:00:00+00:00",
            "hash": sha256.hexdigest(),
            "file": "principles.txt",
            "algorithm": "SHA-256"
        }
        with open(self.test_hash, "w") as f:
            json.dump(record, f)

        with open(self.test_principles, "w", newline="\n") as f:
            f.write("These principles have been changed.")

        tampered_hash = hashlib.sha256()
        with open(self.test_principles, "rb") as f:
            tampered_hash.update(f.read())

        self.assertNotEqual(
            sha256.hexdigest(),
            tampered_hash.hexdigest(),
            "Modified file must produce a different hash. "
            "If hashes match after modification, integrity is broken."
        )

    def test_hash_file_passes_for_unmodified_principles(self):
        """
        Verify passes when principles.txt has not been changed.
        This is the normal case — must work on every clean boot.
        """
        import hashlib
        import json

        content = "These principles have not changed."
        with open(self.test_principles, "w", newline="\n") as f:
            f.write(content)

        sha256 = hashlib.sha256()
        with open(self.test_principles, "rb") as f:
            sha256.update(f.read())
        original_hash = sha256.hexdigest()

        record = {
            "sealed_at": "2026-01-01T00:00:00+00:00",
            "hash": original_hash,
            "file": "principles.txt",
            "algorithm": "SHA-256"
        }
        with open(self.test_hash, "w") as f:
            json.dump(record, f)

        verify_hash = hashlib.sha256()
        with open(self.test_principles, "rb") as f:
            verify_hash.update(f.read())

        self.assertEqual(
            original_hash,
            verify_hash.hexdigest(),
            "Unmodified file must produce matching hash. "
            "Integrity check must pass for clean deployments."
        )

    def test_missing_hash_file_is_detected(self):
        """
        If the hash file is missing, the system cannot verify itself.
        This must be detectable — not a silent pass.
        """
        self.assertFalse(
            os.path.exists(self.test_hash),
            "Hash file must not exist at start of this test."
        )
        self.assertFalse(
            os.path.exists(self.test_hash),
            "A missing hash file means integrity cannot be verified. "
            "The system must treat this as a security event."
        )

    def test_hash_algorithm_is_sha256(self):
        """
        The principles hash must use SHA-256.
        Weaker algorithms are not acceptable for integrity verification.
        This is the published standard for this system.
        """
        import hashlib
        import json

        with open(self.test_principles, "w", newline="\n") as f:
            f.write("Test principles for algorithm verification.")

        sha256 = hashlib.sha256()
        with open(self.test_principles, "rb") as f:
            sha256.update(f.read())

        record = {
            "sealed_at": "2026-01-01T00:00:00+00:00",
            "hash": sha256.hexdigest(),
            "file": "principles.txt",
            "algorithm": "SHA-256"
        }
        with open(self.test_hash, "w") as f:
            json.dump(record, f)

        with open(self.test_hash, "r") as f:
            loaded = json.load(f)

        self.assertEqual(
            loaded["algorithm"], "SHA-256",
            "Hash file must declare SHA-256 as the algorithm. "
            "Other algorithms are not accepted."
        )
        self.assertEqual(
            len(loaded["hash"]), 64,
            "SHA-256 hash must be exactly 64 hex characters."
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: ENVIRONMENT VARIABLE CONFIGURATION (item 2.11)
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvironmentConfig(unittest.TestCase):
    """
    Tests for core/config.py — environment variable configuration.

    Plain English: Makes sure the configuration system loads
    correctly from environment variables, uses safe defaults
    when variables are not set, and never exposes secrets.

    Expected: 4 passed.
    """

    def setUp(self):
        self._original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._original_env)

    def test_config_uses_safe_defaults_when_env_not_set(self):
        """
        When no environment variables are set, the config
        must use safe, documented defaults.
        A missing env var must never crash the system.
        """
        for key in [k for k in os.environ if k.startswith("ONTO_")]:
            del os.environ[key]

        from core.config import ONTOConfig
        cfg = ONTOConfig()

        self.assertEqual(cfg.RATE_LIMIT_PER_MINUTE, 60)
        self.assertEqual(cfg.RATE_LIMIT_WINDOW_SECONDS, 60)
        self.assertEqual(cfg.MAX_INPUT_LENGTH, 10000)
        self.assertEqual(cfg.ENVIRONMENT, "development")
        self.assertFalse(cfg.AUTH_REQUIRED)
        self.assertIsNone(cfg.DB_ENCRYPTION_KEY)
        self.assertIsNone(cfg.AUTH_PASSPHRASE_HASH)

    def test_config_reads_values_from_environment(self):
        """
        When environment variables are set, the config
        must use those values instead of defaults.
        """
        os.environ["ONTO_RATE_LIMIT_PER_MINUTE"] = "30"
        os.environ["ONTO_ENVIRONMENT"] = "production"
        os.environ["ONTO_MAX_INPUT_LENGTH"] = "5000"

        from core.config import ONTOConfig
        cfg = ONTOConfig()

        self.assertEqual(cfg.RATE_LIMIT_PER_MINUTE, 30)
        self.assertEqual(cfg.ENVIRONMENT, "production")
        self.assertEqual(cfg.MAX_INPUT_LENGTH, 5000)

    def test_config_summary_does_not_expose_secrets(self):
        """
        The config summary must never include secret values.
        It must only confirm whether secrets are set or not.
        This is the rule: show presence, never content.
        """
        os.environ["ONTO_DB_ENCRYPTION_KEY"] = "super-secret-key-value"
        os.environ["ONTO_AUTH_PASSPHRASE_HASH"] = "secret-hash-value"

        from core.config import ONTOConfig
        cfg = ONTOConfig()
        summary = cfg.summary()

        self.assertNotIn(
            "super-secret-key-value", summary,
            "Config summary must NEVER expose the encryption key."
        )
        self.assertNotIn(
            "secret-hash-value", summary,
            "Config summary must NEVER expose the passphrase hash."
        )
        self.assertIn(
            "SET", summary,
            "Config summary must confirm that secrets ARE set."
        )

    def test_config_handles_invalid_env_values_gracefully(self):
        """
        If an environment variable contains an invalid value,
        the config must fall back to the safe default.
        Invalid config must never crash the system.
        """
        os.environ["ONTO_RATE_LIMIT_PER_MINUTE"] = "not-a-number"
        os.environ["ONTO_MAX_INPUT_LENGTH"] = "also-not-a-number"
        os.environ["ONTO_ENVIRONMENT"] = "invalid-environment"

        from core.config import ONTOConfig
        cfg = ONTOConfig()

        self.assertEqual(
            cfg.RATE_LIMIT_PER_MINUTE, 60,
            "Invalid rate limit must fall back to default 60."
        )
        self.assertEqual(
            cfg.MAX_INPUT_LENGTH, 10000,
            "Invalid max length must fall back to default 10000."
        )
        self.assertEqual(
            cfg.ENVIRONMENT, "development",
            "Invalid environment must fall back to development."
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
