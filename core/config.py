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

    # ─────────────────────────────────────────────────────────────────────────
    # RATE LIMITING (item 2.05)
    # ─────────────────────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────────────────────
    # DATABASE (item 2.01 — encryption key location)
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def DB_ENCRYPTION_KEY(self) -> Optional[str]:
        """
        Encryption key for the memory database.
        Default: None (unencrypted — acceptable for local dev only).
        Set ONTO_DB_ENCRYPTION_KEY to a strong random value for
        any deployment handling sensitive data.

        IMPORTANT: Never put this value in the codebase.
        Always set it as an environment variable.
        Generate: python3 -c "import secrets; print(secrets.token_hex(32))"
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

    # ─────────────────────────────────────────────────────────────────────────
    # AUTHENTICATION (item 2.02)
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def AUTH_PASSPHRASE_HASH(self) -> Optional[str]:
        """
        SHA-256 hash of the operator passphrase.
        Default: None (no passphrase required — local dev only).
        Set ONTO_AUTH_PASSPHRASE_HASH to require passphrase at boot.
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

    # ─────────────────────────────────────────────────────────────────────────
    # INPUT LIMITS
    # ─────────────────────────────────────────────────────────────────────────

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

    # ─────────────────────────────────────────────────────────────────────────
    # ENVIRONMENT
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def ENVIRONMENT(self) -> str:
        """
        Deployment environment.
        Default: development.
        Set ONTO_ENVIRONMENT to: development | staging | production
        """
        value = os.environ.get("ONTO_ENVIRONMENT", "development")
        if value.lower() in ("development", "staging", "production"):
            return value.lower()
        return "development"

    @property
    def IS_PRODUCTION(self) -> bool:
        """True if running in production environment."""
        return self.ENVIRONMENT == "production"

    # ─────────────────────────────────────────────────────────────────────────
    # SAFE MESSAGING (item C4 — REVIEW_001)
    # Response text displayed when a CRISIS signal is detected.
    #
    # These defaults follow safe messaging guidelines from AFSP, SAMHSA,
    # and WHO for technology systems. They can be overridden via environment
    # variables for localization or deployment-specific needs.
    #
    # Guidelines followed:
    #   - Acknowledge without dismissing
    #   - Do NOT ask clarifying questions that pull the person deeper
    #   - Provide crisis resources immediately
    #   - Do NOT lecture or moralize
    #   - Be brief and warm
    #   - Veto/no-action is always the default
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def CRISIS_RESPONSE_TEXT(self) -> str:
        """
        Text displayed to the operator when a CRISIS signal is detected.
        This is shown at the GOVERN checkpoint before any other action.

        The default follows safe messaging guidelines. Override with
        ONTO_CRISIS_RESPONSE_TEXT for localization.

        Design principles:
          - Warm, not clinical
          - Acknowledges without interrogating
          - Provides resources immediately
          - Does not ask questions that pull deeper
          - Human decision is always required — system never auto-responds
        """
        default = (
            "\n"
            "  ─────────────────────────────────────────────────────\n"
            "  Something in this message may indicate someone is\n"
            "  struggling. Please read it carefully before proceeding.\n"
            "\n"
            "  If this person is in crisis, the most important thing\n"
            "  you can do is connect them with support:\n"
            "\n"
            "  Crisis Text Line:         Text HOME to 741741\n"
            "  988 Suicide & Crisis Line: Call or text 988 (US)\n"
            "  International resources:  findahelpline.com\n"
            "\n"
            "  You are the human in this loop.\n"
            "  Your judgment matters more than anything this system says.\n"
            "  ─────────────────────────────────────────────────────\n"
        )
        return os.environ.get("ONTO_CRISIS_RESPONSE_TEXT", default)

    @property
    def CRISIS_RESOURCES_BRIEF(self) -> str:
        """
        A brief one-line crisis resource reference.
        Used in contexts where the full response text is too long.
        Override with ONTO_CRISIS_RESOURCES_BRIEF for localization.
        """
        default = (
            "988 (call/text) | Crisis Text Line: text HOME to 741741 "
            "| findahelpline.com"
        )
        return os.environ.get("ONTO_CRISIS_RESOURCES_BRIEF", default)

    # ─────────────────────────────────────────────────────────────────────────
    # AUTOMATION BIAS WARNING (item U4 — REVIEW_001)
    # Displayed at checkpoint per EU AI Act Article 14(4)(b).
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def AUTOMATION_BIAS_WARNING(self) -> str:
        """
        Warning displayed at every GOVERN checkpoint.
        Required by EU AI Act Article 14(4)(b): systems must help users
        remain aware of the tendency to over-rely on AI outputs.

        Plain English: This system shows you what it sees.
        It does not tell you what to do.
        Disagreeing with it is always correct when your judgment says so.

        Override with ONTO_AUTOMATION_BIAS_WARNING for localization.
        """
        default = (
            "\n  REMINDER: This system presents examined context, "
            "not conclusions.\n"
            "  The decision is yours. "
            "Disagreeing with this output is always valid.\n"
        )
        return os.environ.get("ONTO_AUTOMATION_BIAS_WARNING", default)

    # ─────────────────────────────────────────────────────────────────────────
    # SESSION MANAGEMENT (item 2.09)
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def SESSION_IDLE_TIMEOUT_SECONDS(self) -> int:
        """
        Seconds of inactivity before a session expires.
        Default: 1800 (30 minutes).
        Set ONTO_SESSION_IDLE_TIMEOUT to override.
        """
        value = os.environ.get("ONTO_SESSION_IDLE_TIMEOUT", "1800")
        try:
            return max(60, int(value))
        except ValueError:
            return 1800

    @property
    def SESSION_MAX_DURATION_SECONDS(self) -> int:
        """
        Maximum absolute session lifetime in seconds, regardless of activity.
        Default: 28800 (8 hours).
        Set ONTO_SESSION_MAX_DURATION to override.
        """
        value = os.environ.get("ONTO_SESSION_MAX_DURATION", "28800")
        try:
            return max(300, int(value))
        except ValueError:
            return 28800

    # ─────────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────────────────────────────

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
            (
                "DB encryption:        "
                f"{'SET' if self.DB_ENCRYPTION_KEY else 'NOT SET (dev only)'}"
            ),
            f"Auth required:        {self.AUTH_REQUIRED}",
            (
                "Auth passphrase:      "
                f"{'SET' if self.AUTH_PASSPHRASE_HASH else 'NOT SET (dev only)'}"
            ),
            f"Session idle timeout: {self.SESSION_IDLE_TIMEOUT_SECONDS}s",
            f"Session max duration: {self.SESSION_MAX_DURATION_SECONDS}s",
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
