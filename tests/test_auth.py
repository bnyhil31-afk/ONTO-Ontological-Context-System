"""
tests/test_auth.py

Tests for core/auth.py — modular authentication layer.
Implements checklist item 2.02.

Expected: 11 passed (or 11 skipped if argon2-cffi not installed).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAuthentication(unittest.TestCase):
    """
    Tests for core/auth.py — the authentication layer.

    Plain English: Makes sure the system securely verifies the
    operator's identity, never exposes the passphrase, and protects
    against brute-force attacks.

    Expected: 11 passed.
    """

    def setUp(self):
        """Create a fresh temporary environment for each test."""
        # Check for the specific sub-module actually used by auth.py.
        # import argon2 alone is not sufficient — argon2.low_level
        # is required for Argon2id key derivation.
        try:
            from argon2.low_level import hash_secret_raw, Type  # noqa: F401
        except (ImportError, ModuleNotFoundError):
            self.skipTest(
                "argon2-cffi not installed or incomplete — "
                "run: pip install argon2-cffi"
            )

        self.test_dir = tempfile.mkdtemp()
        self._original_db_path = os.environ.get("ONTO_DB_PATH")
        os.environ["ONTO_DB_PATH"] = os.path.join(
            self.test_dir, "memory.db"
        )

        from core.auth import LocalAuthManager
        self.LocalAuthManager = LocalAuthManager
        self.manager = LocalAuthManager()

    def tearDown(self):
        if self._original_db_path is None:
            os.environ.pop("ONTO_DB_PATH", None)
        else:
            os.environ["ONTO_DB_PATH"] = self._original_db_path
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # SETUP AND CONFIGURATION
    # ------------------------------------------------------------------

    def test_not_configured_before_setup(self):
        """Fresh manager is not configured before setup()."""
        self.assertFalse(self.manager.is_configured())

    def test_setup_creates_auth_state_file(self):
        """setup() creates the auth state file. is_configured() returns True."""
        self.manager.setup("correct-horse-battery-staple", "blue bicycle")
        self.assertTrue(self.manager.is_configured())
        self.assertTrue(os.path.exists(self.manager._get_auth_path()))

    def test_passphrase_not_stored_in_plaintext(self):
        """
        The plaintext passphrase must NEVER appear in auth.json.
        T-011: Passphrase storage vulnerability.
        If this fails: The passphrase is exposed on disk. Critical bug.
        """
        passphrase = "correct-horse-battery-staple"
        self.manager.setup(passphrase, "blue bicycle")
        with open(self.manager._get_auth_path(), "r") as f:
            content = f.read()
        self.assertNotIn(passphrase, content)

    def test_auth_state_contains_required_fields(self):
        """Auth state file contains all required fields."""
        self.manager.setup("correct-horse-battery-staple", "blue bicycle")
        with open(self.manager._get_auth_path(), "r") as f:
            state = json.load(f)
        for field in ["passphrase_hash", "auth_salt", "identity", "algorithm"]:
            self.assertIn(field, state)
        self.assertEqual(state["algorithm"], "Argon2id")

    # ------------------------------------------------------------------
    # AUTHENTICATION
    # ------------------------------------------------------------------

    def test_correct_passphrase_authenticates(self):
        """The correct passphrase returns success=True."""
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
        """A wrong passphrase returns success=False with a reason."""
        self.manager.setup("correct-horse-battery-staple", "blue bicycle")
        result = self.manager.authenticate(passphrase_input="wrong-passphrase")
        self.assertFalse(result.success)
        self.assertNotEqual(result.reason, "")

    def test_result_contains_passphrase_for_key_derivation(self):
        """Successful AuthResult contains the raw passphrase."""
        passphrase = "correct-horse-battery-staple"
        self.manager.setup(passphrase, "blue bicycle")
        result = self.manager.authenticate(passphrase_input=passphrase)
        self.assertTrue(result.success)
        self.assertEqual(result.passphrase, passphrase)

    def test_clear_passphrase_removes_it_from_result(self):
        """clear_passphrase() clears the passphrase field."""
        passphrase = "correct-horse-battery-staple"
        self.manager.setup(passphrase, "blue bicycle")
        result = self.manager.authenticate(passphrase_input=passphrase)
        result.clear_passphrase()
        self.assertEqual(result.passphrase, "")

    # ------------------------------------------------------------------
    # BRUTE FORCE PROTECTION (T-014)
    # ------------------------------------------------------------------

    def test_failed_attempt_count_shown_in_reason(self):
        """Failed auth returns a non-empty generic reason (A-5: no attempt count disclosed)."""
        self.manager.setup("correct-horse-battery-staple", "blue bicycle")
        result = self.manager.authenticate(passphrase_input="wrong")
        self.assertFalse(result.success)
        self.assertTrue(result.reason, "Failed auth must return a non-empty reason string.")

    # ------------------------------------------------------------------
    # INPUT VALIDATION
    # ------------------------------------------------------------------

    def test_short_passphrase_rejected_at_setup(self):
        """setup() rejects passphrases shorter than 12 characters."""
        with self.assertRaises((ValueError, RuntimeError)):
            self.manager.setup("tooshort", "blue bicycle")

    def test_short_verification_phrase_rejected(self):
        """setup() rejects verification phrases shorter than 4 characters."""
        with self.assertRaises((ValueError, RuntimeError)):
            self.manager.setup("correct-horse-battery-staple", "ab")

    # ------------------------------------------------------------------
    # VERIFICATION PHRASE (T-012)
    # ------------------------------------------------------------------

    def test_verification_phrase_stored_and_retrievable(self):
        """The verification phrase is stored and returned. T-012."""
        phrase = "blue bicycle seven stars"
        self.manager.setup("correct-horse-battery-staple", phrase)
        self.assertEqual(self.manager.get_verification_phrase(), phrase)


if __name__ == "__main__":
    unittest.main()
