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

# Project root — same anchor used by all modules that resolve file paths.
_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ONTOConfig:
    """
    Loads and validates all configuration from environment variables.
    Every value has a documented default that is safe for local use.
    Production deployments should override defaults via environment.
    """

    def __init__(self) -> None:
        # Override slots — used by tests; None means "use env var".
        self._is_production_override = None  # type: Optional[bool]

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
    def GLOBAL_RATE_LIMIT_PER_MINUTE(self) -> int:
        """
        Maximum total requests accepted per time window across ALL clients
        combined. This is an aggregate ceiling — it limits total system load
        regardless of how many different callers are active.

        Default: 0 (disabled). Set ONTO_GLOBAL_RATE_LIMIT_PER_MINUTE to
        a positive integer to enable.

        When enabled, the global limit is checked BEFORE the per-client
        limit — a rejection at the global level returns 429 immediately.

        Example: set to 300 to allow no more than 300 requests/minute in
        total across all clients, even if each individual client is within
        their 60/minute quota.
        """
        value = os.environ.get("ONTO_GLOBAL_RATE_LIMIT_PER_MINUTE", "0")
        try:
            return max(0, int(value))
        except ValueError:
            return 0

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
        Always set it as an environment variable (SECRETS_BACKEND=env) or
        store it in HashiCorp Vault / AWS SSM (see ONTO_SECRETS_BACKEND).
        Generate: python3 -c "import secrets; print(secrets.token_hex(32))"
        """
        return self._get_secret("ONTO_DB_ENCRYPTION_KEY", "db_encryption_key")

    @property
    def DB_PATH(self) -> str:
        """
        Absolute path to the SQLite memory database.
        Default: <project_root>/data/memory.db.
        Set ONTO_DB_PATH to override (relative paths are resolved from
        the project root, not the working directory).
        """
        raw = os.environ.get("ONTO_DB_PATH", "")
        if raw:
            return raw if os.path.isabs(raw) else os.path.join(_ROOT, raw)
        return os.path.join(_ROOT, "data", "memory.db")

    # ─────────────────────────────────────────────────────────────────────────
    # AUTHENTICATION (item 2.02)
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def AUTH_PASSPHRASE_HASH(self) -> Optional[str]:
        """
        SHA-256 hash of the operator passphrase.
        Default: None (no passphrase required — local dev only).
        Set ONTO_AUTH_PASSPHRASE_HASH to require passphrase at boot, or
        store it in HashiCorp Vault / AWS SSM (see ONTO_SECRETS_BACKEND).
        """
        return self._get_secret("ONTO_AUTH_PASSPHRASE_HASH", "auth_passphrase_hash")

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
    def REQUEST_TIMEOUT_SECONDS(self) -> int:
        """
        Maximum time in seconds that any single HTTP request may take to
        complete before the server returns 503 Service Unavailable.

        Default: 30 seconds. Set ONTO_REQUEST_TIMEOUT_SECONDS to override.
        Set to 0 to disable (not recommended — leaves no protection against
        hung connections).

        /health is exempt from this timeout — it must remain unconditionally
        reachable for infrastructure health checks.
        """
        value = os.environ.get("ONTO_REQUEST_TIMEOUT_SECONDS", "30")
        try:
            return max(0, int(value))
        except ValueError:
            return 30

    @property
    def MAX_BODY_BYTES(self) -> int:
        """
        Maximum allowed HTTP request body size in bytes, enforced at the ASGI
        layer before any parsing occurs. This provides a first line of defence
        against oversized-body DoS attempts, independent of Pydantic validation.

        Default: 1048576 (1 MiB) — well above the maximum JSON envelope for a
        10,000-character input (~10 KB), with headroom for future fields.
        Set ONTO_MAX_BODY_BYTES to override.
        Set to 0 to disable the check (not recommended for production).
        """
        value = os.environ.get("ONTO_MAX_BODY_BYTES", "1048576")
        try:
            return max(0, int(value))
        except ValueError:
            return 1_048_576

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
    def LOG_FORMAT(self) -> str:
        """
        Log output format for the structured logger (core/logging.py).
        Options: json | text
        Default: json in production, text in development.
        Set ONTO_LOG_FORMAT to override.

        json — newline-delimited JSON records, suitable for SIEM ingestion
               (ELK, Splunk, Datadog, CloudWatch, etc.)
        text — human-readable lines for local development and debugging
        """
        value = os.environ.get("ONTO_LOG_FORMAT", "")
        if value.lower() in ("json", "text"):
            return value.lower()
        # Default: json in production, text elsewhere
        return "json" if self.IS_PRODUCTION else "text"

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
        if self._is_production_override is not None:
            return self._is_production_override
        return self.ENVIRONMENT == "production"

    @IS_PRODUCTION.setter
    def IS_PRODUCTION(self, value: bool) -> None:
        """Allow tests to override the production flag without env var changes."""
        self._is_production_override = bool(value)

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
        override = os.environ.get("ONTO_CRISIS_RESPONSE_TEXT", "")
        if override:
            # A-7: Validate that the override still contains at least one
            # recognizable crisis resource. A malicious or misconfigured
            # deployment must not replace safe-messaging text with harmful
            # content. If validation fails, log and use the safe default.
            _crisis_markers = ("988", "741741", "crisis", "helpline", "samaritans")
            if any(m in override.lower() for m in _crisis_markers):
                return override
            import sys as _sys
            print(
                "[ONTO WARNING] ONTO_CRISIS_RESPONSE_TEXT override did not "
                "contain a recognizable crisis resource reference. "
                "Falling back to safe default.",
                file=_sys.stderr,
            )
        return default

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
    # AUDIT CHAIN INTEGRITY
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def CHAIN_VERIFY_ON_STARTUP(self) -> bool:
        """
        Whether to verify the Merkle chain integrity of the audit trail on
        every server startup.
        Default: True — any gap is immediately detected.
        Set ONTO_CHAIN_VERIFY_ON_STARTUP=false to skip (not recommended).
        """
        value = os.environ.get("ONTO_CHAIN_VERIFY_ON_STARTUP", "true")
        return value.lower() not in ("false", "0", "no")

    @property
    def CHAIN_INTEGRITY_HALT_ON_FAILURE(self) -> bool:
        """
        If True, the server refuses to start when chain integrity verification
        fails (a gap is detected in the Merkle chain).
        Default: False — log a loud warning and continue, so the system remains
        available even if historical tampering is detected. Operators may choose
        to set this to True in high-assurance deployments.
        Set ONTO_CHAIN_INTEGRITY_HALT_ON_FAILURE=true to enable hard stop.
        """
        value = os.environ.get("ONTO_CHAIN_INTEGRITY_HALT_ON_FAILURE", "false")
        return value.lower() in ("true", "1", "yes")

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
    # COMPLIANCE
    # Configurable compliance posture. All Stage 1 defaults are safe for
    # single-operator local use. Override via environment for deployment.
    # Stage 2 will expand these with consent ledger and RBAC integration.
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def COMPLIANCE_STAGE(self) -> str:
        """
        Deployment compliance stage. Machine-readable marker.
        Default: "1" (single-user, local).
        Stage 2 = multi-user with consent ledger and RBAC.
        Set ONTO_COMPLIANCE_STAGE to override.
        """
        return os.environ.get("ONTO_COMPLIANCE_STAGE", "1")

    @property
    def COMPLIANCE_LEGAL_BASIS_DEFAULT(self) -> str:
        """
        GDPR Article 6 legal basis annotated in every INTAKE audit record.
        Default: "legitimate_interest_single_operator" (Stage 1, operator = subject).
        Set ONTO_COMPLIANCE_LEGAL_BASIS to override.
        Valid values: legitimate_interest_single_operator | consent |
                      contract | legal_obligation
        Stage 2: replaced by per-request consent ledger lookup.
        """
        return os.environ.get(
            "ONTO_COMPLIANCE_LEGAL_BASIS",
            "legitimate_interest_single_operator",
        )

    @property
    def COMPLIANCE_DATA_CONTROLLER(self) -> str:
        """
        GDPR Article 13/14 data controller identity.
        Returned by GET /system/transparency.
        Default: "local_operator".
        Set ONTO_COMPLIANCE_DATA_CONTROLLER to the name of the deploying entity.
        """
        return os.environ.get("ONTO_COMPLIANCE_DATA_CONTROLLER", "local_operator")

    @property
    def COMPLIANCE_TRANSPARENCY_CONTACT(self) -> str:
        """
        Data subject rights contact point (GDPR Art. 13/14).
        Returned by GET /system/transparency.
        Default: "" (empty = self-service; operator = subject in Stage 1).
        Set ONTO_COMPLIANCE_TRANSPARENCY_CONTACT for multi-user deployments.
        """
        return os.environ.get("ONTO_COMPLIANCE_TRANSPARENCY_CONTACT", "")

    @property
    def COMPLIANCE_EXPORT_ALL_CLASSIFICATIONS(self) -> bool:
        """
        If True, GET /data/export includes all records regardless of
        classification level. If False (default), only records with
        classification >= 2 (personal data) are included.
        Set ONTO_COMPLIANCE_EXPORT_ALL=true to override.
        Stage 2: replaced by per-requester RBAC authorization level.
        """
        value = os.environ.get("ONTO_COMPLIANCE_EXPORT_ALL", "false")
        return value.lower() in ("true", "1", "yes")

    @property
    def COMPLIANCE_TRANSPARENCY_KNOWN_LIMITATIONS(self) -> str:
        """
        Pipe-delimited list of known system limitations for GET /system/transparency.
        Operators may add deployment-specific caveats without a code change.
        Default: hardcoded list describing Stage 1 heuristic constraints.
        Set ONTO_COMPLIANCE_TRANSPARENCY_LIMITATIONS to override or extend.

        EU AI Act Art. 13(1)(b) — providers must disclose known limitations.

        Format: "limitation one|limitation two|limitation three"
        Each item is trimmed and returned as a separate string in the response.
        """
        default = (
            "Classification is keyword-heuristic only — not ML-based at Stage 1."
            "|CRISIS detection is keyword-based — not a clinical assessment tool."
            "|Graph relationships are derived from inputs, not verified ground truth."
            "|Consent ledger is not yet active — deferred to Stage 2."
            "|Single-user deployment only — no RBAC at Stage 1."
            "|Right to correct is not supported (append-only audit trail)."
            "|Bias monitoring is designed but not yet implemented (Stage 2)."
            "|Field-level encryption for HIPAA PHI is deferred to Stage 2."
        )
        return os.environ.get("ONTO_COMPLIANCE_TRANSPARENCY_LIMITATIONS", default)

    @property
    def DATA_RETENTION_DAYS(self) -> int:
        """
        Number of days after which record payloads (input, context, output,
        notes) are eligible for pruning via memory.prune_payload_by_age().

        Default: 0 — indefinite retention (no pruning).

        When non-zero, operators should call prune_payload_by_age(days) on a
        schedule (e.g. daily cron) or via the POST /admin/prune endpoint.
        Pruning nullifies personal-content fields while retaining the audit
        shell (id, timestamp, event_type, classification, chain_hash) to
        preserve Merkle chain integrity.

        Set ONTO_DATA_RETENTION_DAYS to override.
        Legal basis: GDPR Art. 5(1)(e) — storage limitation principle.
        """
        value = os.environ.get("ONTO_DATA_RETENTION_DAYS", "0")
        try:
            return max(0, int(value))
        except ValueError:
            return 0

    # STAGE-2: add COMPLIANCE_CONSENT_LEDGER_URL property (reserved, empty default)

    # ─────────────────────────────────────────────────────────────────────────
    # CORS
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def CORS_ALLOW_NULL_ORIGIN(self) -> bool:
        """
        Whether to include the "null" origin in the CORS allowed-origins list.
        The "null" origin is sent by browsers for requests from file:// URLs
        (e.g. a local dashboard HTML file opened directly in the browser).

        Default: True — allows local file:// UIs to reach the API.
        Set ONTO_CORS_ALLOW_NULL_ORIGIN=false to disable.

        NOTE: Enabling this in production is unusual. validate_production_posture()
        will emit a warning (not an error) if this is True in a production
        deployment, so operators are aware.
        """
        value = os.environ.get("ONTO_CORS_ALLOW_NULL_ORIGIN", "true")
        return value.lower() not in ("false", "0", "no")

    # ─────────────────────────────────────────────────────────────────────────
    # SECRETS BACKEND
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def SECRETS_BACKEND(self) -> str:
        """
        Which secrets backend to use for sensitive configuration values.

        Options:
          env      — Read from environment variables (default, no extra deps).
          vault    — HashiCorp Vault KV v2 (requires: pip install hvac).
          aws_ssm  — AWS SSM Parameter Store (requires: pip install boto3).

        Set ONTO_SECRETS_BACKEND to override.

        The "env" backend is identical to the previous behavior — all existing
        deployments continue to work without any changes.
        """
        value = os.environ.get("ONTO_SECRETS_BACKEND", "env").lower().strip()
        if value in ("env", "vault", "aws_ssm"):
            return value
        import sys as _sys
        _sys.stderr.write(
            f"[ONTO WARNING] Unknown ONTO_SECRETS_BACKEND '{value}'. "
            f"Falling back to 'env'.\n"
        )
        return "env"

    def _get_secret(self, env_key: str, secret_name: str) -> Optional[str]:
        """
        Retrieve a secret value through the configured secrets backend.

        Arguments:
            env_key:     The environment variable name used by the 'env' backend
                         (e.g. "ONTO_DB_ENCRYPTION_KEY").
            secret_name: The key/parameter name used by external backends
                         (e.g. "db_encryption_key").

        Returns:
            The secret value as a string, or None if not set.

        The 'env' backend reads os.environ[env_key] directly — no behavior
        change for existing deployments. External backends are only invoked
        when ONTO_SECRETS_BACKEND is set to their name.
        """
        backend = self.SECRETS_BACKEND

        if backend == "env":
            return os.environ.get(env_key, None)

        if backend == "vault":
            try:
                from core.secrets_backends.vault import get_secret
                return get_secret(secret_name)
            except (ImportError, RuntimeError) as exc:
                import sys as _sys
                _sys.stderr.write(
                    f"[ONTO ERROR] Vault secrets backend failed for "
                    f"'{secret_name}': {exc}\n"
                )
                return None

        if backend == "aws_ssm":
            try:
                from core.secrets_backends.aws_ssm import get_secret
                return get_secret(secret_name)
            except (ImportError, RuntimeError) as exc:
                import sys as _sys
                _sys.stderr.write(
                    f"[ONTO ERROR] AWS SSM secrets backend failed for "
                    f"'{secret_name}': {exc}\n"
                )
                return None

        return os.environ.get(env_key, None)

    # ─────────────────────────────────────────────────────────────────────────
    # METRICS
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def METRICS_ENABLED(self) -> bool:
        """
        Whether the GET /metrics Prometheus endpoint is active.
        Default: False — the endpoint returns 404 when disabled.
        Set ONTO_METRICS_ENABLED=true to enable.
        """
        value = os.environ.get("ONTO_METRICS_ENABLED", "false")
        return value.lower() in ("true", "1", "yes")

    @property
    def METRICS_REQUIRE_AUTH(self) -> bool:
        """
        Whether GET /metrics requires a valid session token.
        Default: True — metrics are internal operational data.
        Set ONTO_METRICS_REQUIRE_AUTH=false to allow unauthenticated scraping
        (only do this if the metrics endpoint is not internet-accessible).
        """
        value = os.environ.get("ONTO_METRICS_REQUIRE_AUTH", "true")
        return value.lower() not in ("false", "0", "no")

    # ─────────────────────────────────────────────────────────────────────────
    # PRODUCTION POSTURE VALIDATION
    # Called at server startup before memory is initialized.
    # A production deployment with auth or encryption disabled is a
    # misconfiguration — refuse to start rather than silently run insecurely.
    # ─────────────────────────────────────────────────────────────────────────

    def validate_production_posture(self) -> None:
        """
        Raise RuntimeError if the current configuration is unsafe for production.

        Rules enforced only when IS_PRODUCTION is True:
          1. Authentication must be required (AUTH_REQUIRED must be True).
          2. Database encryption key must be set (DB_ENCRYPTION_KEY must not be None).

        This method is called by the server lifespan on startup (after
        verify_principles(), before memory.initialize()). On failure the
        caller is expected to write to stderr and call sys.exit(1) — matching
        the pattern already used by verify_principles().

        Safe to call in development mode: all checks are gated on IS_PRODUCTION,
        so local dev runs are unaffected.
        """
        if not self.IS_PRODUCTION:
            return

        errors = []

        if not self.AUTH_REQUIRED:
            errors.append(
                "ONTO_AUTH_REQUIRED is not set to true. "
                "Production deployments must require authentication. "
                "Set ONTO_AUTH_REQUIRED=true and configure ONTO_AUTH_PASSPHRASE_HASH."
            )

        if self.DB_ENCRYPTION_KEY is None:
            errors.append(
                "ONTO_DB_ENCRYPTION_KEY is not set. "
                "Production deployments must encrypt the memory database. "
                "Generate a key with: "
                "python3 -c \"import secrets; print(secrets.token_hex(32))\""
            )

        if errors:
            raise RuntimeError(
                "Production security posture check failed:\n"
                + "\n".join(f"  • {e}" for e in errors)
            )

        # Non-fatal warnings — print to stderr but do not halt.
        import sys as _sys
        if self.CORS_ALLOW_NULL_ORIGIN:
            _sys.stderr.write(
                "[ONTO WARNING] ONTO_CORS_ALLOW_NULL_ORIGIN is True in production. "
                "The 'null' origin (used by file:// UIs) is allowed. "
                "Set ONTO_CORS_ALLOW_NULL_ORIGIN=false if no local file:// UI is in use.\n"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────────────────────────────────

    def diff_from_defaults(self) -> dict:
        """
        Returns a dict of configuration properties whose current values
        differ from their coded defaults.

        Format: {property_name: {"current": current_value, "default": default_value}}

        This method compares each property's current value (read from the
        environment) against the value it would have with no ONTO_* env vars
        set. Secret values (DB_ENCRYPTION_KEY, AUTH_PASSPHRASE_HASH) are
        redacted — only whether they are set is shown.

        Safe to print to logs and operator consoles. Never reveals secrets.

        Usage:
            diff = config.diff_from_defaults()
            if diff:
                for name, change in diff.items():
                    print(f"{name}: {change['default']} → {change['current']}")
        """
        import os as _os

        # Build a "clean" config instance with no ONTO_* env vars to get defaults.
        onto_vars = {k: v for k, v in _os.environ.items() if k.startswith("ONTO_")}
        for k in onto_vars:
            del _os.environ[k]

        defaults_instance = ONTOConfig()
        # Collect default values
        _PROPERTIES = [
            "RATE_LIMIT_PER_MINUTE",
            "RATE_LIMIT_WINDOW_SECONDS",
            "GLOBAL_RATE_LIMIT_PER_MINUTE",
            "REQUEST_TIMEOUT_SECONDS",
            "MAX_BODY_BYTES",
            "MAX_INPUT_LENGTH",
            "DB_PATH",
            "AUTH_REQUIRED",
            "SESSION_IDLE_TIMEOUT_SECONDS",
            "SESSION_MAX_DURATION_SECONDS",
            "CHAIN_VERIFY_ON_STARTUP",
            "CHAIN_INTEGRITY_HALT_ON_FAILURE",
            "ENVIRONMENT",
            "IS_PRODUCTION",
            "LOG_FORMAT",
            "CORS_ALLOW_NULL_ORIGIN",
            "DATA_RETENTION_DAYS",
            "COMPLIANCE_STAGE",
            "COMPLIANCE_LEGAL_BASIS_DEFAULT",
            "COMPLIANCE_DATA_CONTROLLER",
        ]
        _SECRET_PROPERTIES = {"DB_ENCRYPTION_KEY", "AUTH_PASSPHRASE_HASH"}

        defaults: dict = {}
        for prop in _PROPERTIES:
            try:
                defaults[prop] = getattr(defaults_instance, prop)
            except Exception:
                pass
        for prop in _SECRET_PROPERTIES:
            try:
                defaults[prop] = "SET" if getattr(defaults_instance, prop) else "NOT SET"
            except Exception:
                pass

        # Restore env vars
        _os.environ.update(onto_vars)

        # Compare current values against defaults
        diff: dict = {}
        for prop in _PROPERTIES:
            try:
                current = getattr(self, prop)
                default = defaults.get(prop)
                if current != default:
                    diff[prop] = {"current": current, "default": default}
            except Exception:
                pass
        for prop in _SECRET_PROPERTIES:
            try:
                current_display = "SET" if getattr(self, prop) else "NOT SET"
                default_display = defaults.get(prop, "NOT SET")
                if current_display != default_display:
                    diff[prop] = {
                        "current": current_display,
                        "default": default_display,
                    }
            except Exception:
                pass

        return diff

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
            f"Compliance stage:     {self.COMPLIANCE_STAGE}",
            f"Legal basis default:  {self.COMPLIANCE_LEGAL_BASIS_DEFAULT}",
            f"Data controller:      {self.COMPLIANCE_DATA_CONTROLLER}",
            (
                "Transparency contact: "
                f"{'SET' if self.COMPLIANCE_TRANSPARENCY_CONTACT else 'not set'}"
            ),
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
