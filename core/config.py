"""
core/config.py

Configuration management for ONTO.
All configurable values live here.
All values load from environment variables with safe defaults.

Plain English: This is where the system reads its settings.
No secrets or credentials ever live in the code itself.
They live in environment variables — set by the operator,
not baked into the repository.

To configure: copy .env.example to .env and edit the values.
To run with custom config: set environment variables before
running python3 main.py, or use a .env loader.

Usage:
    from core.config import config
    limit = config.RATE_LIMIT_PER_MINUTE
"""

import os
from typing import Optional


class ONTOConfig:
    """
    Loads and validates all configuration from environment variables.
    Every value has a documented default that is safe for local use.
    Production deployments should override defaults via environment.
    """

    # ─────────────────────────────────────────────────────────────────
    # RATE LIMITING (item 2.05)
    # ─────────────────────────────────────────────────────────────────

    @property
    def RATE_LIMIT_PER_MINUTE(self) -> int:
        """
        Maximum number of inputs accepted per minute.
        Default: 60 (one per second on average).
        Set ONTO_RATE_LIMIT_PER_MINUTE to override.
        Set to 0 to disable rate limiting (not recommended).
        """
        value = os.environ.get("ONTO_RATE_LIMIT_PER_MINUTE", "60")
        try:
            parsed = int(value)
            return max(0, parsed)
        except ValueError:
            return 60

    @property
    def RATE_LIMIT_WINDOW_SECONDS(self) -> int:
        """
        The time window for rate limit counting, in seconds.
        Default: 60 (one minute).
        Set ONTO_RATE_LIMIT_WINDOW_SECONDS to override.
        """
        value = os.environ.get("ONTO_RATE_LIMIT_WINDOW_SECONDS", "60")
        try:
            parsed = int(value)
            return max(1, parsed)
        except ValueError:
            return 60

    # ─────────────────────────────────────────────────────────────────
    # DATABASE (item 2.01 — encryption key location)
    # ─────────────────────────────────────────────────────────────────

    @property
    def DB_ENCRYPTION_KEY(self) -> Optional[str]:
        """
        Encryption key for the memory database.
        Default: None (unencrypted — acceptable for local dev only).
        Set ONTO_DB_ENCRYPTION_KEY to a strong random value for
        any deployment handling sensitive data.

        IMPORTANT: Never put this value in the codebase.
        Always set it as an environment variable.
        Generate a key with: python3 -c "import secrets; print(secrets.token_hex(32))"
        """
        return os.environ.get("ONTO_DB_ENCRYPTION_KEY", None)

    @property
    def DB_PATH(self) -> str:
        """
        Path to the SQLite memory database.
        Default: data/memory.db (relative to project root).
        Set ONTO_DB_PATH to override.
        """
        return os.environ.get("ONTO_DB_PATH", "data/memory.db")

    # ─────────────────────────────────────────────────────────────────
    # AUTHENTICATION (item 2.02 — passphrase location)
    # ─────────────────────────────────────────────────────────────────

    @property
    def AUTH_PASSPHRASE_HASH(self) -> Optional[str]:
        """
        SHA-256 hash of the operator passphrase.
        Default: None (no passphrase required — local dev only).
        Set ONTO_AUTH_PASSPHRASE_HASH to require passphrase at boot.

        To set a passphrase:
        1. Choose a strong passphrase
        2. Hash it: python3 -c "import hashlib; print(hashlib.sha256(b'your-passphrase').hexdigest())"
        3. Set ONTO_AUTH_PASSPHRASE_HASH to the hash output
        Never store the passphrase itself — only its hash.
        """
        return os.environ.get("ONTO_AUTH_PASSPHRASE_HASH", None)

    @property
    def AUTH_REQUIRED(self) -> bool:
        """
        Whether authentication is required at startup.
        Default: False (local dev mode).
        Set ONTO_AUTH_REQUIRED=true to require passphrase.
        Automatically True if AUTH_PASSPHRASE_HASH is set.
        """
        if self.AUTH_PASSPHRASE_HASH:
            return True
        value = os.environ.get("ONTO_AUTH_REQUIRED", "false")
        return value.lower() in ("true", "1", "yes")

    # ─────────────────────────────────────────────────────────────────
    # INPUT LIMITS
    # ─────────────────────────────────────────────────────────────────

    @property
    def MAX_INPUT_LENGTH(self) -> int:
        """
        Maximum length of a single input in characters.
        Default: 10000.
        Set ONTO_MAX_INPUT_LENGTH to override.
        """
        value = os.environ.get("ONTO_MAX_INPUT_LENGTH", "10000")
        try:
            return max(1, int(value))
        except ValueError:
            return 10000

    # ─────────────────────────────────────────────────────────────────
    # ENVIRONMENT
    # ─────────────────────────────────────────────────────────────────

    @property
    def ENVIRONMENT(self) -> str:
        """
        Deployment environment.
        Default: development.
        Set ONTO_ENVIRONMENT to: development | staging | production
        Production mode enables stricter security defaults.
        """
        value = os.environ.get("ONTO_ENVIRONMENT", "development")
        if value.lower() in ("development", "staging", "production"):
            return value.lower()
        return "development"

    @property
    def IS_PRODUCTION(self) -> bool:
        """True if running in production environment."""
        return self.ENVIRONMENT == "production"

    def summary(self) -> str:
        """
        Returns a human-readable summary of current configuration.
        Never includes secrets — only shows whether they are set.
        Safe to print to logs.
        """
        lines = [
            "ONTO Configuration Summary",
            "─" * 40,
            f"Environment:          {self.ENVIRONMENT}",
            f"Rate limit/min:       {self.RATE_LIMIT_PER_MINUTE}",
            f"Rate window (sec):    {self.RATE_LIMIT_WINDOW_SECONDS}",
            f"Max input length:     {self.MAX_INPUT_LENGTH}",
            f"DB path:              {self.DB_PATH}",
            f"DB encryption:        {'SET' if self.DB_ENCRYPTION_KEY else 'NOT SET (dev only)'}",
            f"Auth required:        {self.AUTH_REQUIRED}",
            f"Auth passphrase:      {'SET' if self.AUTH_PASSPHRASE_HASH else 'NOT SET (dev only)'}",
            "─" * 40,
        ]
        if not self.IS_PRODUCTION:
            lines.append(
                "NOTE: Running in development mode. "
                "Set ONTO_ENVIRONMENT=production for stricter defaults."
            )
        return "\n".join(lines)


# Single shared instance — import this everywhere
config = ONTOConfig()
