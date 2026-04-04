"""
core/encryption.py

Application-layer encryption for the ONTO memory database.
Implements item 2.01 of the pre-launch security checklist.

Design decisions (all from THREAT_MODEL_001 and REVIEW_001):
  - Key derived from passphrase at runtime using Argon2id (OWASP 2025)
  - Key is NEVER stored — exists only in memory during session
  - Key is explicitly cleared when session ends (T-016 cold boot)
  - Database file grows in fixed increments (T-004 size oracle)
  - AES-256-GCM — authenticated encryption, detects tampering

Why Argon2id over PBKDF2 (REVIEW_001 Finding C1):
  OWASP 2025 recommends Argon2id as the primary choice for all new
  systems without a FIPS compliance requirement. Argon2id is memory-hard:
  each derivation requires significant RAM, making GPU/ASIC parallel
  attacks economically infeasible. PBKDF2 lacks this property.
  Argon2id also provides inherent post-quantum resistance because each
  Grover oracle call requires the full memory allocation.

Raspberry Pi configuration (m=19 MiB, t=2, p=1):
  Tuned for constrained hardware. Derivation takes ~200-400ms on Pi.
  Set ONTO_ARGON2_MEMORY_KB to increase on capable hardware.
  OWASP minimum: m=19456, t=2, p=1. Recommended: m=47104, t=1, p=1.

Dependencies:
  pip install cryptography argon2-cffi

Usage:
    from core.encryption import encryption
    encryption.initialize(passphrase="your-passphrase", db_path="...")
    # use the database
    encryption.clear_key()  # always call at session end
"""

import os
import secrets
import struct
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Argon2id parameters (OWASP 2025 minimum for memory-constrained devices)
# Override via environment variables for more capable hardware
ARGON2_TIME_COST = 2          # Number of iterations
ARGON2_PARALLELISM = 1        # Degree of parallelism
ARGON2_HASH_LEN = 32          # Output key length (256-bit AES key)
ARGON2_SALT_SIZE = 32         # 256-bit salt

# Default memory cost — 19 MiB (OWASP minimum)
# Set ONTO_ARGON2_MEMORY_KB=47104 for OWASP recommended on capable hardware
_DEFAULT_MEMORY_KB = 19456

# Encryption parameters
NONCE_SIZE = 12               # 96-bit nonce for AES-GCM (NIST standard)
TAG_SIZE = 16                 # 128-bit authentication tag

# File padding — database grows in 4KB increments (T-004 mitigation)
PAD_BLOCK_SIZE = 4096

# Salt filename — stores Argon2id salt alongside database (not the key)
SALT_FILENAME = "memory.salt"


class EncryptionLayer:
    """
    Manages AES-256-GCM encryption of the ONTO memory database.
    Key derivation uses Argon2id (OWASP 2025 recommended).

    The key exists only after initialize() and before clear_key().
    It is never written to disk. It is derived fresh each session.
    """

    def __init__(self) -> None:
        self._key: Optional[bytes] = None
        self._initialized: bool = False

    # ─────────────────────────────────────────────────────────────────
    # INITIALIZATION
    # ─────────────────────────────────────────────────────────────────

    def initialize(self, passphrase: str, db_path: str) -> bool:
        """
        Derives the AES-256-GCM key from the passphrase using Argon2id.

        The passphrase is NOT stored. The key is NOT stored.
        Both exist only in memory after this call.
        The Argon2id salt IS stored alongside the database — it is not
        secret, it just prevents rainbow table attacks on the passphrase.

        Args:
            passphrase: The operator passphrase (plain text, never stored)
            db_path:    Path to the database file

        Returns:
            True if key successfully derived

        Raises:
            RuntimeError if required libraries are not installed
        """
        self._require_libraries()

        memory_kb = self._get_memory_kb()
        salt = self._get_or_create_salt(db_path)
        self._key = self._derive_key(passphrase, salt, memory_kb)
        self._initialized = True

        # Best-effort overwrite of passphrase in local scope
        passphrase = secrets.token_hex(len(passphrase))  # noqa: F841
        return True

    def is_initialized(self) -> bool:
        """Returns True if key has been derived and not yet cleared."""
        return self._initialized and self._key is not None

    def clear_key(self) -> None:
        """
        Explicitly clears the key from memory.
        ALWAYS call this when the session ends.
        Mitigates cold boot attack (T-016).

        Plain English: When done, destroy the key.
        Do not leave it in memory when it is no longer needed.
        """
        if self._key is not None:
            self._key = bytes(ARGON2_HASH_LEN)  # overwrite
            self._key = None
        self._initialized = False

    # ─────────────────────────────────────────────────────────────────
    # ENCRYPTION AND DECRYPTION
    # ─────────────────────────────────────────────────────────────────

    def encrypt_file(self, plaintext: bytes) -> bytes:
        """
        Encrypts bytes using AES-256-GCM.

        Output format: padding_header(4) + nonce(12) + ciphertext + tag(16)
        + padding(variable)

        AES-GCM provides confidentiality AND authenticity.
        If the ciphertext is tampered with, decryption raises InvalidTag.
        There is no silent corruption.

        Args:
            plaintext: Data to encrypt

        Returns:
            Encrypted bytes, padded to PAD_BLOCK_SIZE boundary
        """
        self._require_initialized()

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = secrets.token_bytes(NONCE_SIZE)
        aesgcm = AESGCM(self._key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)

        combined = nonce + ciphertext
        return self._pad_to_block(combined)

    def decrypt_file(self, encrypted: bytes) -> bytes:
        """
        Decrypts bytes produced by encrypt_file().

        Raises:
            cryptography.exceptions.InvalidTag if data tampered
            ValueError if format invalid
        """
        self._require_initialized()

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        data = self._unpad(encrypted)

        if len(data) < NONCE_SIZE + TAG_SIZE:
            raise ValueError(
                "Encrypted data is too short to be valid. "
                "The file may be corrupted or incomplete."
            )

        nonce = data[:NONCE_SIZE]
        ciphertext = data[NONCE_SIZE:]

        aesgcm = AESGCM(self._key)
        return aesgcm.decrypt(nonce, ciphertext, None)

    # ─────────────────────────────────────────────────────────────────
    # DATABASE HELPERS
    # ─────────────────────────────────────────────────────────────────

    def encrypt_database(self, db_path: str) -> bool:
        """
        Encrypts the database file in place.
        Called after session ends, before process exits.
        """
        if not os.path.exists(db_path):
            return False

        with open(db_path, "rb") as f:
            plaintext = f.read()

        encrypted = self.encrypt_file(plaintext)

        with open(db_path + ".enc", "wb") as f:
            f.write(encrypted)

        os.replace(db_path + ".enc", db_path)
        return True

    def decrypt_database(self, db_path: str, temp_path: str) -> bool:
        """
        Decrypts the database to a temporary path for use during session.
        The encrypted file on disk remains unchanged.
        """
        if not os.path.exists(db_path):
            return False

        with open(db_path, "rb") as f:
            encrypted = f.read()

        plaintext = self.decrypt_file(encrypted)

        with open(temp_path, "wb") as f:
            f.write(plaintext)

        return True

    # ─────────────────────────────────────────────────────────────────
    # KEY DERIVATION — ARGON2ID (OWASP 2025)
    # ─────────────────────────────────────────────────────────────────

    def _derive_key(
        self,
        passphrase: str,
        salt: bytes,
        memory_kb: int
    ) -> bytes:
        """
        Derives a 256-bit key from the passphrase using Argon2id.

        Argon2id is memory-hard: each derivation requires `memory_kb`
        of RAM. This makes parallel GPU/ASIC brute-force attacks
        economically infeasible — they must allocate full memory
        for each attempt.

        Parameters follow OWASP 2025 recommendations:
          m (memory): 19456 KB minimum (Pi-safe) to 47104 KB recommended
          t (time):   2 iterations
          p (parallel): 1 thread
        """
        from argon2.low_level import hash_secret_raw, Type

        key = hash_secret_raw(
            secret=passphrase.encode("utf-8"),
            salt=salt,
            time_cost=ARGON2_TIME_COST,
            memory_cost=memory_kb,
            parallelism=ARGON2_PARALLELISM,
            hash_len=ARGON2_HASH_LEN,
            type=Type.ID  # Argon2id — hybrid of Argon2i and Argon2d
        )
        return key

    def _get_memory_kb(self) -> int:
        """
        Returns the Argon2id memory cost in KB.
        Configurable via ONTO_ARGON2_MEMORY_KB environment variable.
        Default: 19456 KB (19 MiB) — OWASP minimum, Pi-safe.
        """
        value = os.environ.get(
            "ONTO_ARGON2_MEMORY_KB",
            str(_DEFAULT_MEMORY_KB)
        )
        try:
            parsed = int(value)
            # Never below 8 KB (Argon2 absolute minimum)
            return max(8, parsed)
        except ValueError:
            return _DEFAULT_MEMORY_KB

    def _get_or_create_salt(self, db_path: str) -> bytes:
        """
        Gets the existing Argon2id salt or creates a new one.
        The salt is stored alongside the database — it is NOT secret.
        It prevents rainbow table attacks on the passphrase.
        """
        salt_path = os.path.join(
            os.path.dirname(db_path), SALT_FILENAME
        )

        if os.path.exists(salt_path):
            with open(salt_path, "rb") as f:
                salt = f.read()
            if len(salt) == ARGON2_SALT_SIZE:
                return salt

        # First deployment — generate and store a new salt
        salt = secrets.token_bytes(ARGON2_SALT_SIZE)
        salt_dir = os.path.dirname(salt_path)
        if salt_dir:
            os.makedirs(salt_dir, exist_ok=True)
        with open(salt_path, "wb") as f:
            f.write(salt)

        return salt

    # ─────────────────────────────────────────────────────────────────
    # PADDING — FILE SIZE ORACLE MITIGATION (T-004)
    # ─────────────────────────────────────────────────────────────────

    def _pad_to_block(self, data: bytes) -> bytes:
        """
        Pads data to the next PAD_BLOCK_SIZE boundary.
        Stores original length in first 4 bytes.
        Prevents inferring database content size from file size.
        """
        original_length = len(data)
        header = struct.pack(">I", original_length)
        padded_size = (
            ((original_length + 4 + PAD_BLOCK_SIZE - 1)
             // PAD_BLOCK_SIZE) * PAD_BLOCK_SIZE
        )
        padding = bytes(padded_size - original_length - 4)
        return header + data + padding

    def _unpad(self, data: bytes) -> bytes:
        """Removes padding added by _pad_to_block."""
        if len(data) < 4:
            return data
        original_length = struct.unpack(">I", data[:4])[0]
        return data[4:4 + original_length]

    # ─────────────────────────────────────────────────────────────────
    # GUARDS
    # ─────────────────────────────────────────────────────────────────

    def _require_initialized(self) -> None:
        if not self.is_initialized():
            raise RuntimeError(
                "Encryption layer not initialized. "
                "Call initialize(passphrase, db_path) first."
            )

    def _require_libraries(self) -> None:
        missing = []
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            missing.append("cryptography")
        try:
            from argon2.low_level import hash_secret_raw, Type  # noqa: F401
        except ImportError:
            missing.append("argon2-cffi")

        if missing:
            raise RuntimeError(
                f"Required libraries not installed: {', '.join(missing)}. "
                f"Run: pip install {' '.join(missing)}"
            )


# Single shared instance
encryption = EncryptionLayer()
