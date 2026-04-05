"""
core/auth.py

Modular authentication layer for ONTO.
Implements item 2.02 of the pre-launch security checklist.

Changes from v1 (REVIEW_001 findings C1 and U2):
  - Passphrase hashing upgraded from PBKDF2 to Argon2id (OWASP 2025)
  - Auth salt is now randomly generated per installation, stored in
    auth.json alongside the passphrase hash (not the passphrase itself)
  - This eliminates the deterministic salt vulnerability in v1

Design decisions (all from THREAT_MODEL_001):
  - Passphrase is NEVER stored — only its Argon2id hash is stored
  - Verification phrase shown at boot to detect fake screens (T-012)
  - Exponential backoff + lockout on failed attempts (T-014)
  - Every auth event recorded in audit trail
  - Swap-in interface — enterprise SSO replaces this module without
    touching anything else in the system

Architecture:
  Stage 1 (now):    Local passphrase, single user, Argon2id
  Stage 2 (future): Multi-user with roles
  Stage 3 (future): SSO module (OAuth2/OIDC, SAML) using same interface

Swap interface contract:
  authenticate(context) → AuthResult
  Any module satisfying this contract is a valid auth module.

Usage:
    from core.auth import auth_manager
    result = auth_manager.authenticate()
    if result.success:
        from core.encryption import encryption
        encryption.initialize(result.passphrase, db_path)
        result.clear_passphrase()  # always clear after key derivation
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Argon2id parameters for passphrase hashing (OWASP 2025)
# Lower memory than encryption key derivation — auth hash is verified
# on every login and must be fast enough for interactive use
AUTH_ARGON2_MEMORY_KB = 19456  # 19 MiB — OWASP minimum
AUTH_ARGON2_TIME_COST = 2
AUTH_ARGON2_PARALLELISM = 1
AUTH_ARGON2_HASH_LEN = 32
AUTH_SALT_SIZE = 32            # 256-bit random salt per installation

# Brute force protection (T-014)
MAX_ATTEMPTS = 5
BASE_DELAY_SECONDS = 1
MAX_DELAY_SECONDS = 60
LOCKOUT_DURATION_SECONDS = 300  # 5 minutes

# Auth state file — stores hashed passphrase + salt (NOT the passphrase)
AUTH_STATE_FILENAME = "auth.json"


# ─────────────────────────────────────────────────────────────────────────────
# RESULT TYPE — THE SWAP INTERFACE CONTRACT
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AuthResult:
    """
    The result of an authentication attempt.
    This is the swap interface contract — any auth module returns this.

    success:    True if authentication passed
    identity:   Who authenticated
    reason:     Why it failed (if success is False)
    passphrase: The raw passphrase — used ONLY to derive the encryption
                key, then immediately cleared. Never stored anywhere.
    """
    success: bool
    identity: str = ""
    reason: str = ""
    passphrase: str = ""

    def clear_passphrase(self) -> None:
        """
        Clears the passphrase from this result.
        Call immediately after deriving the encryption key.
        The passphrase must not live longer than necessary.
        """
        self.passphrase = ""


# ─────────────────────────────────────────────────────────────────────────────
# AUTH MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class LocalAuthManager:
    """
    Stage 1 authentication — local passphrase, single user, Argon2id.

    Passphrase flow:
      1. User enters passphrase
      2. Argon2id hash computed with stored per-installation salt
      3. Compared to stored hash using constant-time comparison
      4. If match: AuthResult contains passphrase for key derivation
      5. Caller derives encryption key, calls result.clear_passphrase()

    Verification phrase flow (T-012):
      1. At setup, user provides a personal phrase
      2. At every boot, ONTO displays it BEFORE asking for passphrase
      3. If user does not see their phrase → fake boot screen → abort
    """

    def __init__(self) -> None:
        self._failed_attempts: int = 0
        self._last_attempt_time: float = 0.0
        self._locked_until: float = 0.0

    def _get_auth_path(self) -> str:
        """Path to the auth state file."""
        from core.config import config
        db_dir = os.path.dirname(config.DB_PATH)
        return os.path.join(db_dir, AUTH_STATE_FILENAME)

    def is_configured(self) -> bool:
        """True if a passphrase has been set up."""
        return os.path.exists(self._get_auth_path())

    # ─────────────────────────────────────────────────────────────────
    # SETUP
    # ─────────────────────────────────────────────────────────────────

    def setup(
        self,
        passphrase: str,
        verification_phrase: str,
        identity: str = "operator"
    ) -> bool:
        """
        First-time setup. Hashes passphrase with Argon2id and a
        randomly generated per-installation salt. Stores the hash
        and salt in auth.json — never the passphrase itself.

        Args:
            passphrase:          Secret passphrase (minimum 12 chars)
            verification_phrase: Personal phrase displayed at boot (T-012)
            identity:            Label for this user/operator

        Returns:
            True if setup was successful

        Raises:
            ValueError if passphrase or verification phrase too short
            RuntimeError if argon2-cffi not installed
        """
        self._require_argon2()

        if not passphrase or len(passphrase) < 12:
            raise ValueError(
                "Passphrase must be at least 12 characters. "
                "Use a phrase, not a single word."
            )

        if not verification_phrase or len(verification_phrase) < 4:
            raise ValueError(
                "Verification phrase must be at least 4 characters."
            )

        # Generate a random per-installation salt (U2 fix)
        # This salt is stored in auth.json — it is not secret
        auth_salt = secrets.token_bytes(AUTH_SALT_SIZE)
        passphrase_hash = self._hash_passphrase(passphrase, auth_salt)

        state = {
            "identity": identity,
            "passphrase_hash": passphrase_hash,
            "auth_salt": auth_salt.hex(),  # hex-encode for JSON storage
            "verification_phrase": verification_phrase,
            "setup_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "algorithm": "Argon2id",
            "algorithm_params": {
                "memory_kb": AUTH_ARGON2_MEMORY_KB,
                "time_cost": AUTH_ARGON2_TIME_COST,
                "parallelism": AUTH_ARGON2_PARALLELISM,
                "hash_len": AUTH_ARGON2_HASH_LEN,
            },
            "note": (
                "The Argon2id hash and random salt are stored here. "
                "The passphrase itself is never stored. "
                "The verification phrase is stored in plain text — "
                "it is shown at boot so the operator can detect a "
                "fake ONTO boot screen (see THREAT_MODEL_001 T-012)."
            )
        }

        auth_path = self._get_auth_path()
        auth_dir = os.path.dirname(auth_path)
        if auth_dir:
            os.makedirs(auth_dir, exist_ok=True)
        with open(auth_path, "w") as f:
            json.dump(state, f, indent=2)

        # Best-effort overwrite
        passphrase = ""  # noqa: F841
        return True

    # ─────────────────────────────────────────────────────────────────
    # AUTHENTICATE
    # ─────────────────────────────────────────────────────────────────

    def authenticate(
        self,
        passphrase_input: Optional[str] = None
    ) -> AuthResult:
        """
        Authenticates the operator.

        In development mode (no auth configured, AUTH_REQUIRED=false):
        returns success without prompting.

        In production mode (auth configured):
        1. Displays verification phrase (T-012)
        2. Prompts for passphrase
        3. Verifies with Argon2id + constant-time comparison
        4. Returns AuthResult

        Args:
            passphrase_input: Bypass prompt — for testing only.
                              In production, always pass None.
        """
        # Development mode
        if not self.is_configured():
            from core.config import config
            if not config.AUTH_REQUIRED:
                return AuthResult(
                    success=True,
                    identity="dev-operator",
                    reason="",
                    passphrase=""
                )
            else:
                return AuthResult(
                    success=False,
                    identity="",
                    reason=(
                        "Authentication is required but not configured. "
                        "Run: python3 -m core.auth setup"
                    )
                )

        # Lockout check (T-014)
        if self._is_locked_out():
            remaining = int(self._locked_until - time.monotonic())
            return AuthResult(
                success=False,
                identity="",
                reason=(
                    f"Too many failed attempts. "
                    f"Try again later (in {remaining} seconds)."
                )
            )

        # Load auth state
        with open(self._get_auth_path(), "r") as f:
            state = json.load(f)

        # Display verification phrase (T-012)
        if passphrase_input is None:
            verification = state.get("verification_phrase", "")
            print("\n" + "─" * 50)
            print("  ONTO Authentication")
            print("─" * 50)
            print(f"\n  Your verification phrase is:\n")
            print(f"      {verification}\n")
            print("  If you do not recognize this phrase,")
            print("  do NOT enter your passphrase.")
            print("  Close this window immediately.\n")
            print("─" * 50)

        # Get passphrase
        if passphrase_input is None:
            try:
                import getpass
                entered = getpass.getpass("\n  Enter passphrase: ")
            except (KeyboardInterrupt, EOFError):
                return AuthResult(
                    success=False,
                    identity="",
                    reason="Authentication cancelled."
                )
        else:
            entered = passphrase_input

        # Retrieve stored salt and hash
        stored_hash = state.get("passphrase_hash", "")
        auth_salt_hex = state.get("auth_salt", "")

        if not auth_salt_hex:
            # Legacy: no salt in state (pre-U2 auth.json).
            # The original v1 implementation hashed with an empty salt.
            # We use a fixed zero-byte sentinel so verification is
            # deterministic across calls — not a random salt per attempt.
            # Users on legacy auth.json should re-run setup to migrate.
            auth_salt = b"\x00" * AUTH_SALT_SIZE
        else:
            auth_salt = bytes.fromhex(auth_salt_hex)

        # Compute and compare — use stored params so verification works even
        # when module defaults change between versions.
        stored_params = state.get("algorithm_params", {})
        entered_hash = self._hash_passphrase(
            entered,
            auth_salt,
            time_cost=stored_params.get("time_cost", AUTH_ARGON2_TIME_COST),
            memory_cost=stored_params.get("memory_kb", AUTH_ARGON2_MEMORY_KB),
            parallelism=stored_params.get("parallelism", AUTH_ARGON2_PARALLELISM),
            hash_len=stored_params.get("hash_len", AUTH_ARGON2_HASH_LEN),
        )

        if self._constant_time_compare(entered_hash, stored_hash):
            self._failed_attempts = 0
            identity = state.get("identity", "operator")
            result = AuthResult(
                success=True,
                identity=identity,
                reason="",
                passphrase=entered
            )
            return result
        else:
            self._record_failure()
            delay = self._get_delay()

            if self._failed_attempts >= MAX_ATTEMPTS:
                self._locked_until = (
                    time.monotonic() + LOCKOUT_DURATION_SECONDS
                )
                # A-5: Do not reveal how many attempts triggered lockout.
                reason = "Too many failed attempts. Please try again later."
            else:
                # A-5: Do not disclose remaining attempt count or use the word
                # "attempt" — it gives attackers a signal to manage their
                # guessing budget. Generic message only.
                reason = "Incorrect passphrase."

            if delay > 0:
                time.sleep(delay)

            entered = ""  # noqa: F841
            return AuthResult(
                success=False,
                identity="",
                reason=reason
            )

    def get_verification_phrase(self) -> str:
        """Returns the stored verification phrase for display at boot."""
        if not self.is_configured():
            return ""
        with open(self._get_auth_path(), "r") as f:
            state = json.load(f)
        return state.get("verification_phrase", "")

    # ─────────────────────────────────────────────────────────────────
    # BRUTE FORCE PROTECTION (T-014)
    # ─────────────────────────────────────────────────────────────────

    def _record_failure(self) -> None:
        self._failed_attempts += 1
        self._last_attempt_time = time.monotonic()

    def _get_delay(self) -> float:
        """Exponential backoff — delay grows with each failure."""
        if self._failed_attempts <= 1:
            return 0
        return min(
            BASE_DELAY_SECONDS * (2 ** (self._failed_attempts - 1)),
            MAX_DELAY_SECONDS
        )

    def _is_locked_out(self) -> bool:
        return (
            self._locked_until > 0
            and time.monotonic() < self._locked_until
        )

    # ─────────────────────────────────────────────────────────────────
    # CRYPTOGRAPHIC HELPERS — ARGON2ID (OWASP 2025)
    # ─────────────────────────────────────────────────────────────────

    def _hash_passphrase(
        self,
        passphrase: str,
        salt: bytes,
        *,
        time_cost: int = AUTH_ARGON2_TIME_COST,
        memory_cost: int = AUTH_ARGON2_MEMORY_KB,
        parallelism: int = AUTH_ARGON2_PARALLELISM,
        hash_len: int = AUTH_ARGON2_HASH_LEN,
    ) -> str:
        """
        Hashes a passphrase using Argon2id with the provided salt.

        Using Argon2id instead of PBKDF2 (REVIEW_001 C1 + U2):
          - Memory-hard: requires RAM allocation per attempt
          - GPU/ASIC resistant: parallel attacks are expensive
          - Post-quantum resistant: memory-hardness defeats Grover speedup
          - Random per-installation salt: defeats rainbow tables

        Keyword args allow callers to pass stored algorithm_params so that
        verification uses the same parameters that were used during setup,
        which is required for forward compatibility when defaults change.
        """
        from argon2.low_level import hash_secret_raw, Type

        # Never substitute a random salt — the caller is always responsible
        # for providing the correct salt. A random fallback would produce
        # an irreproducible hash, making every authentication attempt fail.
        # Argon2 requires salt length >= 8 bytes; legacy auth.json files
        # that stored no auth_salt use a fixed zero-byte sentinel for
        # deterministic verification.
        effective_salt = salt if len(salt) >= 8 else b"\x00" * 8

        key = hash_secret_raw(
            secret=passphrase.encode("utf-8"),
            salt=effective_salt,
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=hash_len,
            type=Type.ID
        )
        return key.hex()

    def _constant_time_compare(self, a: str, b: str) -> bool:
        """
        Constant-time string comparison.
        Prevents timing attacks that could reveal hash length.
        """
        return hmac.compare_digest(
            a.encode("utf-8"),
            b.encode("utf-8")
        )

    # ─────────────────────────────────────────────────────────────────
    # GUARDS
    # ─────────────────────────────────────────────────────────────────

    def _require_argon2(self) -> None:
        try:
            from argon2.low_level import hash_secret_raw, Type  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "argon2-cffi is required for authentication. "
                "Run: pip install argon2-cffi"
            )


# ─────────────────────────────────────────────────────────────────────────────
# SETUP CLI — python3 -m core.auth setup
# ─────────────────────────────────────────────────────────────────────────────

def _run_setup() -> None:
    """Interactive first-time authentication setup."""
    import getpass

    print("\n" + "═" * 50)
    print("  ONTO — Authentication Setup")
    print("═" * 50)
    print("\nThis runs once. You can reset it later if needed.\n")

    print("Step 1 of 2 — Verification phrase")
    print(
        "Choose a personal phrase shown every time ONTO starts.\n"
        "It lets you detect a fake boot screen.\n"
        "Example: 'my cat is named biscuit'\n"
    )
    verification = input("  Your verification phrase: ").strip()

    print("\nStep 2 of 2 — Passphrase (minimum 12 characters)")
    print("Use a phrase, not a single word.\n")

    while True:
        passphrase = getpass.getpass("  Enter passphrase: ")
        confirm = getpass.getpass("  Confirm passphrase: ")
        if passphrase == confirm:
            break
        print("  Passphrases do not match. Try again.\n")

    manager = LocalAuthManager()
    try:
        manager.setup(passphrase, verification)
        print("\n  Authentication configured.")
        print("  Argon2id hash stored — not the passphrase.")
        print("  Random salt generated for this installation.")
        print("  Verification phrase will appear at every boot.\n")
    except ValueError as e:
        print(f"\n  Error: {e}\n")


# Single shared instance
auth_manager = LocalAuthManager()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        _run_setup()
    else:
        print("Usage: python3 -m core.auth setup")
