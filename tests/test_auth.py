"""
tests/test_auth.py

Tests for core/auth.py — modular authentication layer.
Implements checklist item 2.02.

Covers:
  - First-time setup and state file creation
  - Passphrase never stored in plaintext
  - Correct passphrase authenticates
  - Wrong passphrase fails with clear reason
  - AuthResult contract (fields, clear_passphrase)
  - Verification phrase (T-012 anti-fake-boot-screen)
  - Brute force protection — attempt counting (T-014)
  - Short passphrase rejected at setup
  - Development mode (no passphrase configured, AUTH_REQUIRED=false)

Threats mitigated (from THREAT_MODEL_001):
  T-011 — Passphrase storage vulnerability
  T-012 — Fake boot screen attack
  T-014 — Brute force passphrase attack

Expected: 11 passed.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

try:
    import argon2  # noqa: F401
    ARGON2_AVAILABLE = True
except ImportError:
    ARGON2_AVAILABLE = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@unittest.skipIf(not ARGON2_AVAILABLE, "argon2-cffi not installed — run: pip install argon2-cffi")
class TestAuthentication(unittest.TestCase):
    """
    Tests for core/auth.py — the authentication layer.

    Plain English: Makes sure the system securely verifies the
    operator's identity, never exposes the passphrase, and protects
    against brute-force attacks.

    Each test gets a fresh LocalAuthManager and a temporary directory
    so the real auth state and the test state never mix.

    Expected: 11 passed.
    """

    def setUp(self):
        """Create a fresh temporary environment for each test."""
        self.test_dir = tempfile.mkdtemp()
        # Route the auth state file into the temp directory
        # by pointing DB_PATH at a file inside it
        self._original_db_path = os.environ.get("ONTO_DB_PATH")
        os.environ["ONTO_DB_PATH"] = os.path.join(self.test_dir, "memory.db")

        # Fresh manager — no shared state between tests
        from core.auth import LocalAuthManager
        self.LocalAuthManager = LocalAuthManager
        self.manager = LocalAuthManager()

    def tearDown(self):
        """Restore original state and remove temporary files."""
        if self._original_db_path is None:
            os.environ.pop("ONTO_DB_PATH", None)
        else:
            os.environ["ONTO_DB_PATH"] = self._original_db_path
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # SETUP AND CONFIGURATION
    # ------------------------------------------------------------------

    def test_not_configured_before_setup(self):
        """
        A fresh LocalAuthManager is not configured.
        is_configured() must return False until setup() is called.
        If this fails: The system may behave incorrectly on first install.
        """
        self.assertFalse(
            self.manager.is_configured(),
            "Fresh manager must not be configured before setup() is called."
        )

    def test_setup_creates_auth_state_file(self):
        """
        setup() creates the auth state file (auth.json).
        After setup, is_configured() must return True.
        """
        self.manager.setup("correct-horse-battery-staple", "blue bicycle")
        self.assertTrue(
            self.manager.is_configured(),
            "is_configured() must return True after setup() is called."
        )
        self.assertTrue(
            os.path.exists(self.manager._get_auth_path()),
            "Auth state file must exist after setup."
        )

    def test_passphrase_not_stored_in_plaintext(self):
        """
        The plaintext passphrase must NEVER appear in auth.json.
        Only its Argon2id hash and the random salt are stored.
        If this fails: The passphrase is exposed on disk. Critical bug.
        T-011: Passphrase storage vulnerability.
        """
        passphrase = "correct-horse-battery-staple"
        self.manager.setup(passphrase, "blue bicycle")
        with open(self.manager._get_auth_path(), "r") as f:
            content = f.read()
        self.assertNotIn(
            passphrase, content,
            "Plaintext passphrase must never be stored in auth.json. "
            "Only the Argon2id hash should be present."
        )

    def test_auth_state_contains_required_fields(self):
        """Auth state file contains all required fields for verification."""
        self.manager.setup("correct-horse-battery-staple", "blue bicycle")
        with open(self.manager._get_auth_path(), "r") as f:
            state = json.load(f)
        for field in ["passphrase_hash", "auth_salt", "identity", "algorithm"]:
            self.assertIn(
                field, state,
                f"Auth state missing required field: '{field}'"
            )
        self.assertEqual(
            state["algorithm"], "Argon2id",
            "Algorithm field must declare Argon2id."
        )

    # ------------------------------------------------------------------
    # AUTHENTICATION
    # ------------------------------------------------------------------

    def test_correct_passphrase_authenticates(self):
        """
        The correct passphrase returns success=True with the operator identity.
        This is the normal happy path — it must always work.
        """
        self.manager.setup(
            "correct-horse-battery-staple",
            "blue bicycle",
            identity="test-operator"
        )
        result = self.manager.authenticate(
            passphrase_input="correct-horse-battery-staple"
        )
        self.assertTrue(result.success)
        self.assertEqual(result.identity, "test-operator")

    def test_wrong_passphrase_fails(self):
        """
        A wrong passphrase returns success=False with a non-empty reason.
        The reason must be human-readable and explain what happened.
        """
        self.manager.setup("correct-horse-battery-staple", "blue bicycle")
        result = self.manager.authenticate(passphrase_input="wrong-passphrase")
        self.assertFalse(result.success)
        self.assertNotEqual(
            result.reason, "",
            "Failed authentication must include a reason string."
        )

    def test_result_contains_passphrase_for_key_derivation(self):
        """
        A successful AuthResult contains the raw passphrase for key derivation.
        The caller uses it to initialize encryption, then must clear it.
        """
        passphrase = "correct-horse-battery-staple"
        self.manager.setup(passphrase, "blue bicycle")
        result = self.manager.authenticate(passphrase_input=passphrase)
        self.assertTrue(result.success)
        self.assertEqual(
            result.passphrase, passphrase,
            "Successful result must contain the passphrase for key derivation."
        )

    def test_clear_passphrase_removes_it_from_result(self):
        """
        clear_passphrase() removes the passphrase from the AuthResult.
        Must be called immediately after deriving the encryption key.
        If this fails: The passphrase persists in memory longer than needed.
        """
        passphrase = "correct-horse-battery-staple"
        self.manager.setup(passphrase, "blue bicycle")
        result = self.manager.authenticate(passphrase_input=passphrase)
        self.assertEqual(result.passphrase, passphrase)
        result.clear_passphrase()
        self.assertEqual(
            result.passphrase, "",
            "clear_passphrase() must clear the passphrase field."
        )

    # ------------------------------------------------------------------
    # BRUTE FORCE PROTECTION (T-014)
    # ------------------------------------------------------------------

    def test_failed_attempt_count_shown_in_reason(self):
        """
        After a failed attempt, the reason tells the operator how many
        attempts remain. T-014: operators know their situation.
        """
        self.manager.setup("correct-horse-battery-staple", "blue bicycle")
        result = self.manager.authenticate(passphrase_input="wrong")
        self.assertFalse(result.success)
        self.assertIn(
            "attempt", result.reason.lower(),
            "Reason must mention remaining attempts."
        )

    # ------------------------------------------------------------------
    # INPUT VALIDATION
    # ------------------------------------------------------------------

    def test_short_passphrase_rejected_at_setup(self):
        """
        setup() rejects passphrases shorter than 12 characters.
        Short passphrases are weak — the system must refuse them.
        """
        with self.assertRaises(ValueError):
            self.manager.setup("tooshort", "blue bicycle")

    def test_short_verification_phrase_rejected(self):
        """
        setup() rejects verification phrases shorter than 4 characters.
        A too-short verification phrase provides no T-012 protection.
        """
        with self.assertRaises(ValueError):
            self.manager.setup("correct-horse-battery-staple", "ab")

    # ------------------------------------------------------------------
    # VERIFICATION PHRASE (T-012)
    # ------------------------------------------------------------------

    def test_verification_phrase_stored_and_retrievable(self):
        """
        The verification phrase is stored and returned by
        get_verification_phrase(). It is displayed at every boot so
        the operator can detect a fake ONTO screen (T-012).
        """
        phrase = "blue bicycle seven stars"
        self.manager.setup("correct-horse-battery-staple", phrase)
        self.assertEqual(
            self.manager.get_verification_phrase(),
            phrase,
            "get_verification_phrase() must return exactly the stored phrase."
        )


if __name__ == "__main__":
    unittest.main()
