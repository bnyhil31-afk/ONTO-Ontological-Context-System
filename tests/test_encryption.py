"""
tests/test_encryption.py

Tests for core/encryption.py — AES-256-GCM database encryption layer.
Implements checklist item 2.01.

Expected: 8 passed (or 8 skipped if cryptography/argon2-cffi not installed).
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestEncryptionLayer(unittest.TestCase):
    """
    Tests for core/encryption.py — AES-256-GCM with Argon2id key derivation.

    Expected: 8 passed.
    """

    def setUp(self):
        """Create isolated environment — fresh layer and temp directory."""
        # Skip all tests if required libraries are not installed.
        # self.skipTest() runs at execution time — most reliable skip.
        try:
            import cryptography  # noqa: F401
            import argon2        # noqa: F401
        except ImportError as e:
            self.skipTest(
                f"Required library not installed ({e}) — "
                "run: pip install cryptography argon2-cffi"
            )

        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "memory.db")
        from core.encryption import EncryptionLayer
        self.EncryptionLayer = EncryptionLayer
        self.enc = EncryptionLayer()

    def tearDown(self):
        self.enc.clear_key()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_key_is_none_before_initialize(self):
        """Before initialize(), the key does not exist."""
        self.assertIsNone(self.enc._key)

    def test_initialize_sets_key(self):
        """initialize() derives and stores the encryption key."""
        self.enc.initialize("test-passphrase-correct-123", self.db_path)
        self.assertIsNotNone(self.enc._key)

    def test_key_is_32_bytes(self):
        """The derived key must be exactly 32 bytes (256 bits)."""
        self.enc.initialize("test-passphrase-correct-123", self.db_path)
        self.assertEqual(len(self.enc._key), 32)

    def test_clear_key_removes_key_from_memory(self):
        """
        clear_key() sets the key to None.
        T-016: key must not outlive the session.
        """
        self.enc.initialize("test-passphrase-correct-123", self.db_path)
        self.assertIsNotNone(self.enc._key)
        self.enc.clear_key()
        self.assertIsNone(self.enc._key)

    def test_same_passphrase_same_salt_same_key(self):
        """Same passphrase + same salt = same key. Required for restart."""
        self.enc.initialize("stable-passphrase-restart-test", self.db_path)
        key_first = bytes(self.enc._key)
        self.enc.clear_key()
        self.enc.initialize("stable-passphrase-restart-test", self.db_path)
        key_second = bytes(self.enc._key)
        self.assertEqual(key_first, key_second)

    def test_different_passphrase_different_key(self):
        """Different passphrases produce different keys."""
        self.enc.initialize("passphrase-alpha-one-two-three", self.db_path)
        key_alpha = bytes(self.enc._key)
        enc2 = self.EncryptionLayer()
        enc2.initialize("passphrase-beta-four-five-six", self.db_path)
        key_beta = bytes(enc2._key)
        enc2.clear_key()
        self.assertNotEqual(key_alpha, key_beta)

    def test_different_salt_files_different_keys(self):
        """Different installations produce different keys."""
        dir2 = tempfile.mkdtemp()
        db_path2 = os.path.join(dir2, "memory.db")
        try:
            self.enc.initialize("same-passphrase-cross-install", self.db_path)
            key1 = bytes(self.enc._key)
            enc2 = self.EncryptionLayer()
            enc2.initialize("same-passphrase-cross-install", db_path2)
            key2 = bytes(enc2._key)
            enc2.clear_key()
            self.assertNotEqual(key1, key2)
        finally:
            shutil.rmtree(dir2, ignore_errors=True)

    def test_salt_file_created_on_first_initialize(self):
        """Salt file is created on first initialize()."""
        from core.encryption import SALT_FILENAME
        salt_path = os.path.join(
            os.path.dirname(self.db_path), SALT_FILENAME
        )
        self.assertFalse(os.path.exists(salt_path))
        self.enc.initialize("test-passphrase-correct-123", self.db_path)
        self.assertTrue(os.path.exists(salt_path))


if __name__ == "__main__":
    unittest.main()
