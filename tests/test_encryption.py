"""
tests/test_encryption.py

Tests for core/encryption.py — AES-256-GCM database encryption layer.
Implements checklist item 2.01.

Covers:
  - Key not set before initialize()
  - initialize() derives a 256-bit key
  - Same passphrase + same salt = same key (required for restart)
  - Different passphrase = different key
  - Different salt file = different key (per-installation isolation)
  - clear_key() removes key from memory (T-016 cold boot mitigation)
  - Salt file created on first initialize()

Threats mitigated (from THREAT_MODEL_001):
  T-004 — Database file size oracle (padding)
  T-016 — Cold boot key recovery (key cleared at session end)

Expected: 8 passed (or 8 skipped if cryptography/argon2-cffi not installed).
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# DEPENDENCY GUARD
# Both cryptography and argon2-cffi are required for encryption tests.
# If either is absent, all tests are skipped with a clear message rather
# than failing with a confusing RuntimeError from _require_libraries().
# ---------------------------------------------------------------------------

try:
    import cryptography   # noqa: F401
    import argon2         # noqa: F401
    ENCRYPTION_LIBS_AVAILABLE = True
except ImportError:
    ENCRYPTION_LIBS_AVAILABLE = False


@unittest.skipIf(
    not ENCRYPTION_LIBS_AVAILABLE,
    "cryptography or argon2-cffi not installed — run: pip install cryptography argon2-cffi"
)
class TestEncryptionLayer(unittest.TestCase):
    """
    Tests for core/encryption.py — AES-256-GCM with Argon2id key derivation.

    Plain English: Makes sure the encryption layer correctly derives
    and manages a cryptographic key from the operator's passphrase.
    The key must never be stored — it exists only in memory for the
    duration of the session and is cleared when the session ends.

    Each test uses a fresh EncryptionLayer instance and a temporary
    directory so test databases never touch the real system.

    Expected: 8 passed.
    """

    def setUp(self):
        """Create isolated environment — fresh layer and temp directory."""
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "memory.db")
        from core.encryption import EncryptionLayer
        self.EncryptionLayer = EncryptionLayer
        self.enc = EncryptionLayer()

    def tearDown(self):
        """Always clear the key and clean up — mirrors production teardown."""
        self.enc.clear_key()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # KEY STATE
    # ------------------------------------------------------------------

    def test_key_is_none_before_initialize(self):
        """
        Before initialize() is called, the encryption key does not exist.
        The system must not have an implicit or default key.
        If this fails: Data might be encrypted with an unintended key.
        """
        self.assertIsNone(
            self.enc._key,
            "Key must be None before initialize() is called."
        )

    def test_initialize_sets_key(self):
        """initialize() derives and stores the encryption key."""
        self.enc.initialize("test-passphrase-correct-123", self.db_path)
        self.assertIsNotNone(
            self.enc._key,
            "Key must not be None after initialize() is called."
        )

    def test_key_is_32_bytes(self):
        """
        The derived key must be exactly 32 bytes (256 bits).
        AES-256-GCM requires a 256-bit key — any other length is wrong.
        """
        self.enc.initialize("test-passphrase-correct-123", self.db_path)
        self.assertEqual(
            len(self.enc._key), 32,
            f"Key must be 32 bytes (256 bits). Got: {len(self.enc._key)} bytes."
        )

    def test_clear_key_removes_key_from_memory(self):
        """
        clear_key() sets the key to None.
        This is the T-016 mitigation — the key must not outlive the session.
        Call clear_key() at session end, on logout, and on error.
        If this fails: The key persists in memory after the session ends.
        """
        self.enc.initialize("test-passphrase-correct-123", self.db_path)
        self.assertIsNotNone(self.enc._key)
        self.enc.clear_key()
        self.assertIsNone(
            self.enc._key,
            "clear_key() must set _key to None."
        )

    # ------------------------------------------------------------------
    # KEY DERIVATION PROPERTIES
    # ------------------------------------------------------------------

    def test_same_passphrase_same_salt_same_key(self):
        """
        Key derivation is deterministic: the same passphrase and the
        same salt always produce the same key. This is required so the
        database can be decrypted after a system restart.
        If this fails: The database becomes unreadable after each restart.
        """
        self.enc.initialize("stable-passphrase-restart-test", self.db_path)
        key_first = bytes(self.enc._key)
        self.enc.clear_key()

        # Re-initialize with the same passphrase — reuses the existing salt file
        self.enc.initialize("stable-passphrase-restart-test", self.db_path)
        key_second = bytes(self.enc._key)

        self.assertEqual(
            key_first, key_second,
            "Same passphrase + same salt must produce the same key. "
            "If this differs, the database cannot be reopened after restart."
        )

    def test_different_passphrase_different_key(self):
        """
        Different passphrases produce different keys, even with the same
        salt file. An attacker cannot use their passphrase to decrypt
        another user's database.
        """
        self.enc.initialize("passphrase-alpha-one-two-three", self.db_path)
        key_alpha = bytes(self.enc._key)

        enc2 = self.EncryptionLayer()
        enc2.initialize("passphrase-beta-four-five-six", self.db_path)
        key_beta = bytes(enc2._key)
        enc2.clear_key()

        self.assertNotEqual(
            key_alpha, key_beta,
            "Different passphrases must produce different keys."
        )

    def test_different_salt_files_different_keys(self):
        """
        Two fresh installations with the same passphrase produce different
        keys because each generates a unique random salt. This prevents
        cross-installation attacks — a key valid on one device is not valid
        on another.
        If this fails: The per-installation salt is not being used.
        """
        dir2 = tempfile.mkdtemp()
        db_path2 = os.path.join(dir2, "memory.db")

        try:
            self.enc.initialize("same-passphrase-cross-install", self.db_path)
            key1 = bytes(self.enc._key)

            enc2 = self.EncryptionLayer()
            enc2.initialize("same-passphrase-cross-install", db_path2)
            key2 = bytes(enc2._key)
            enc2.clear_key()

            self.assertNotEqual(
                key1, key2,
                "Different installations must produce different keys. "
                "Each installation generates a unique random salt."
            )
        finally:
            shutil.rmtree(dir2, ignore_errors=True)

    # ------------------------------------------------------------------
    # SALT FILE
    # ------------------------------------------------------------------

    def test_salt_file_created_on_first_initialize(self):
        """
        A salt file is created on the first call to initialize().
        The salt is stored so the same key can be derived on restart.
        Without the salt file, the database cannot be decrypted.
        If this fails: The salt is not persisted — restart will lose data.
        """
        from core.encryption import SALT_FILENAME
        salt_path = os.path.join(os.path.dirname(self.db_path), SALT_FILENAME)

        self.assertFalse(
            os.path.exists(salt_path),
            "Salt file must not exist before first initialize()."
        )
        self.enc.initialize("test-passphrase-correct-123", self.db_path)
        self.assertTrue(
            os.path.exists(salt_path),
            "Salt file must be created by initialize(). "
            f"Expected at: {salt_path}"
        )


if __name__ == "__main__":
    unittest.main()
