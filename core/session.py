"""
core/session.py

Session management layer for ONTO.
Implements item 2.09 of the pre-launch security checklist.

Design decisions (all from THREAT_MODEL_001, REVIEW_001, and CRE-SPEC-001):

  TOKEN SECURITY
  - Session token is 32 bytes (256-bit) of cryptographic randomness.
  - The raw token is NEVER stored — only its SHA-256 hash is held in memory.
    This means even if the session store is read, tokens cannot be replayed.
  - Tokens are rotated on each authenticated request, limiting the replay
    window for any intercepted token (T-013 mitigation).

  CONNECTION BINDING (T-013)
  - Sessions are optionally bound to a connection fingerprint (e.g., IP address
    hash). A token presented from an unrecognized connection is rejected.
    This is configurable — binding can be disabled for legitimate roaming
    clients (e.g., mobile users on changing IPs).

  REGULATORY FORWARD-COMPATIBILITY
  - Every session carries a user_id field. For Stage 1 single-user deployment
    this is always "local". For Stage 2 multi-user it becomes a real identity.
    The schema does not change between stages — only the value.
  - Every session carries a consent_reference field. For Stage 1 this is None
    (the local user owns the system; implicit consent). For Stage 2 this will
    point to the consent ledger record that authorizes this session. This
    satisfies GDPR Article 7 (conditions for consent) and CCPA's right-to-know
    requirement without requiring a schema migration later.
  - data_classification tracks the highest-sensitivity classification of any
    data touched during the session. This is required for GDPR Article 30
    (records of processing activities) and informs retention decisions.

  AUDIT TRAIL
  - Every session lifecycle event is written to the audit trail:
    SESSION_START, SESSION_END, SESSION_EXPIRED, SESSION_ROTATED,
    SESSION_INVALID_TOKEN, SESSION_BINDING_VIOLATION.
  - Tokens are NEVER written to the audit trail — only their hash prefix
    (first 8 hex characters) for correlation without exposure.

  STAGE 1 CONSTRAINTS
  - Single session at a time (MAX_CONCURRENT_SESSIONS = 1).
    A new authentication while a session is active invalidates the prior
    session and records a SESSION_SUPERSEDED event.
  - Thread-safe: a lock protects all session state mutations. This is
    over-engineered for Stage 1 single-user, but it costs nothing and
    means the session manager is safe for Stage 2 concurrent use without
    modification.

  EXPIRY MODEL
  - Absolute TTL: session expires at created_at + TTL regardless of activity.
  - Sliding TTL: session expiry extends on each valid use, up to a
    configurable maximum lifetime. Disabled by default (absolute mode).
  - Configurable via environment variables (see core/config.py).

Architecture:
  Stage 1 (now):    Single user, local passphrase auth, absolute TTL.
  Stage 2 (future): Multi-user, roles, consent references, sliding TTL.
  Stage 3 (future): Federated sessions, cross-node token verification.

Swap interface contract:
  create_session(user_id, connection_fingerprint) -> SessionToken
  validate_session(token, connection_fingerprint)  -> SessionValidation
  end_session(token)                               -> None

Usage:
    from core.session import session_manager
    from core.audit import write_audit_event  # injected at startup

    token = session_manager.create_session(
        user_id="local",
        connection_fingerprint=request_ip_hash,
        audit_fn=write_audit_event
    )

    validation = session_manager.validate_session(
        token=bearer_token,
        connection_fingerprint=request_ip_hash,
        audit_fn=write_audit_event
    )
    if not validation.valid:
        return 401

    session_manager.end_session(token, audit_fn=write_audit_event)
"""

import hashlib
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

# ---------------------------------------------------------------------------
# CONSTANTS — all overridable via environment variables (see core/config.py)
# ---------------------------------------------------------------------------

# Raw token length in bytes. 32 bytes = 256 bits of entropy.
TOKEN_BYTES = 32

# Default session lifetime in seconds. 1 hour is a reasonable default
# that balances usability (you don't get logged out mid-work) with
# security (a stolen token has a limited window).
DEFAULT_TTL_SECONDS = int(os.environ.get("ONTO_SESSION_TTL_SECONDS", "3600"))

# Maximum lifetime for sliding TTL mode. Even a highly active session
# must re-authenticate after this period. Protects against sessions
# that were legitimately started but later compromised.
MAX_LIFETIME_SECONDS = int(os.environ.get("ONTO_SESSION_MAX_LIFETIME_SECONDS", "28800"))  # 8 hours

# Whether to use sliding TTL (extends on use) or absolute TTL.
# Absolute is the secure default. Sliding is more user-friendly for
# long working sessions but widens the stolen-token window.
SLIDING_TTL = os.environ.get("ONTO_SESSION_SLIDING_TTL", "false").lower() == "true"

# Whether to enforce connection binding. True = reject tokens presented
# from a different connection fingerprint than the one used to create them.
# Set to False only if your deployment involves legitimate connection changes
# (e.g., mobile clients that change IP addresses mid-session).
ENFORCE_CONNECTION_BINDING = (
    os.environ.get("ONTO_SESSION_BINDING", "true").lower() == "true"
)

# Maximum concurrent sessions. 1 for Stage 1 single-user.
# Increase to support multi-user in Stage 2 without changing this file.
MAX_CONCURRENT_SESSIONS = int(os.environ.get("ONTO_MAX_SESSIONS", "1"))


# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------

@dataclass
class SessionRecord:
    """
    The internal representation of an active session.

    This record lives only in memory — it is never written to disk.
    The token_hash is the SHA-256 of the raw token. The raw token
    exists only as the string returned to the client at creation time.

    Regulatory fields:
      user_id           — who this session belongs to (GDPR Art. 30)
      consent_reference — which consent record authorizes this session
                          (GDPR Art. 7). None for Stage 1 local user.
      data_classification — highest sensitivity level touched this session.
                            Used for GDPR Art. 30 records of processing
                            and CCPA right-to-know compliance.
    """
    token_hash: str                             # SHA-256 hex of raw token — stored, not the token
    token_prefix: str                           # First 8 hex chars — for audit log correlation only
    user_id: str                                # "local" in Stage 1; real identity in Stage 2
    created_at: float                           # Unix timestamp
    expires_at: float                           # Absolute expiry Unix timestamp
    last_used_at: float                         # Updated on each valid use
    connection_fingerprint_hash: Optional[str]  # SHA-256 of connection identifier (e.g., IP)
    consent_reference: Optional[str]            # Pointer to consent ledger record (Stage 2+)
    data_classification: str = "UNCLASSIFIED"   # Escalates as session touches sensitive data
    rotated_at: Optional[float] = None          # Timestamp of last token rotation


@dataclass
class SessionToken:
    """
    What is returned to the caller after a successful session creation
    or token rotation. This is the ONLY moment the raw token is visible.
    The caller must store it securely and present it on subsequent requests.
    """
    token: str          # The raw bearer token — treat like a password
    expires_at: float   # When this token expires (Unix timestamp)
    user_id: str        # Who this session belongs to
    token_prefix: str   # First 8 hex chars — safe to log for correlation


@dataclass
class SessionValidation:
    """
    The result of validating a presented token. This is the swap
    interface contract — any session module returns this shape.

    valid:     True if the token was accepted.
    reason:    Why it was rejected (if valid is False).
    session:   The full session record (if valid is True).
    new_token: Present only if the token was rotated during validation.
               The caller must use this token for all subsequent requests.
    """
    valid: bool
    reason: Optional[str] = None
    session: Optional[SessionRecord] = None
    new_token: Optional[SessionToken] = None


# ---------------------------------------------------------------------------
# SESSION MANAGER
# ---------------------------------------------------------------------------

class SessionManager:
    """
    Thread-safe session manager for ONTO.

    Manages the full session lifecycle: creation, validation, rotation,
    and termination. All state is in-memory — no session data is written
    to disk. The audit trail receives lifecycle events but never raw tokens.

    This class is intentionally designed with Stage 2 in mind:
      - user_id and consent_reference are first-class fields now
      - The lock and concurrent session limit are already in place
      - The swap interface contract is defined and stable

    The singleton instance `session_manager` is imported by the API layer.
    """

    def __init__(self) -> None:
        # The active session store: token_hash -> SessionRecord
        # In Stage 1 this will never hold more than 1 entry.
        # In Stage 2, this scales to MAX_CONCURRENT_SESSIONS.
        self._sessions: Dict[str, SessionRecord] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    def _hash_token(self, token: str) -> str:
        """
        Produce the SHA-256 hash of a raw token.
        This is what we store — never the token itself.
        """
        return hashlib.sha256(token.encode()).hexdigest()

    def _hash_fingerprint(self, fingerprint: Optional[str]) -> Optional[str]:
        """
        Hash a connection fingerprint (e.g., IP address) before storing.
        We don't need to know the actual IP — just whether this request
        comes from the same connection as the one that created the session.
        Hashing prevents the session store from becoming a surveillance log.
        """
        if fingerprint is None:
            return None
        return hashlib.sha256(fingerprint.encode()).hexdigest()

    def _purge_expired(self, audit_fn: Optional[Callable] = None) -> None:
        """
        Remove expired sessions from the store. Called on every operation
        so the store never silently accumulates dead sessions.

        This is important for GDPR's data minimization principle (Art. 5(1)(c)):
        data that is no longer needed must not be retained. Session records
        in memory are personal data — they should not outlive their purpose.
        """
        now = time.time()
        expired = [h for h, s in self._sessions.items() if s.expires_at <= now]
        for token_hash in expired:
            session = self._sessions.pop(token_hash)
            if audit_fn:
                audit_fn(
                    event_type="SESSION_EXPIRED",
                    details={
                        "token_prefix": session.token_prefix,
                        "user_id": session.user_id,
                        "created_at": session.created_at,
                        "expired_at": now,
                        "data_classification": session.data_classification,
                    }
                )

    # ------------------------------------------------------------------
    # PUBLIC INTERFACE — THE SWAP CONTRACT
    # ------------------------------------------------------------------

    def create_session(
        self,
        user_id: str = "local",
        connection_fingerprint: Optional[str] = None,
        consent_reference: Optional[str] = None,
        audit_fn: Optional[Callable] = None,
    ) -> SessionToken:
        """
        Create a new authenticated session and return the raw token.

        If MAX_CONCURRENT_SESSIONS is already reached, the oldest session
        is superseded (with an audit event) and the new session replaces it.
        For Stage 1 this means a new login always invalidates the prior one —
        you cannot have two active sessions on a single-user system.

        Args:
            user_id:               Who this session belongs to.
                                   Always "local" in Stage 1.
            connection_fingerprint: A string that uniquely identifies this
                                   connection (e.g., client IP address).
                                   Hashed before storage — never stored raw.
            consent_reference:     Pointer to the consent record that
                                   authorizes this session. None for Stage 1.
            audit_fn:              Callable that writes to the audit trail.
                                   Signature: audit_fn(event_type, details).

        Returns:
            SessionToken with the raw bearer token. This is the only time
            the raw token is visible. The caller must store it securely.
        """
        with self._lock:
            self._purge_expired(audit_fn)

            # Enforce session limit — supersede oldest if at capacity
            if len(self._sessions) >= MAX_CONCURRENT_SESSIONS:
                oldest_hash = min(
                    self._sessions,
                    key=lambda h: self._sessions[h].created_at
                )
                superseded = self._sessions.pop(oldest_hash)
                if audit_fn:
                    audit_fn(
                        event_type="SESSION_SUPERSEDED",
                        details={
                            "token_prefix": superseded.token_prefix,
                            "user_id": superseded.user_id,
                            "reason": "new_session_created_at_capacity",
                        }
                    )

            # Generate a cryptographically secure random token
            raw_token = secrets.token_hex(TOKEN_BYTES)
            token_hash = self._hash_token(raw_token)
            token_prefix = token_hash[:8]   # Safe to log — not guessable from prefix alone

            now = time.time()
            expires_at = now + DEFAULT_TTL_SECONDS

            session = SessionRecord(
                token_hash=token_hash,
                token_prefix=token_prefix,
                user_id=user_id,
                created_at=now,
                expires_at=expires_at,
                last_used_at=now,
                connection_fingerprint_hash=self._hash_fingerprint(connection_fingerprint),
                consent_reference=consent_reference,
            )
            self._sessions[token_hash] = session

            if audit_fn:
                audit_fn(
                    event_type="SESSION_START",
                    details={
                        "token_prefix": token_prefix,
                        "user_id": user_id,
                        "expires_at": expires_at,
                        "connection_bound": connection_fingerprint is not None,
                        "consent_reference": consent_reference,
                        "sliding_ttl": SLIDING_TTL,
                    }
                )

            return SessionToken(
                token=raw_token,
                expires_at=expires_at,
                user_id=user_id,
                token_prefix=token_prefix,
            )

    def validate_session(
        self,
        token: str,
        connection_fingerprint: Optional[str] = None,
        rotate: bool = True,
        audit_fn: Optional[Callable] = None,
    ) -> SessionValidation:
        """
        Validate a presented bearer token and optionally rotate it.

        Token rotation means: on each successful validation, the old token
        is retired and a new one is issued. The caller receives the new token
        in the SessionValidation.new_token field and must use it going forward.
        This means a stolen token can only be replayed until the legitimate
        client makes its next request — at which point the stolen copy
        becomes invalid.

        Token rotation is a meaningful security improvement with almost no
        cost in a request/response cycle. It is enabled by default.

        Args:
            token:                  The raw bearer token from the client.
            connection_fingerprint: The connection identifier for this request.
                                   Must match the one used to create the session
                                   if ENFORCE_CONNECTION_BINDING is True.
            rotate:                 Whether to rotate the token on this validation.
                                   Set to False for read-only operations where
                                   rotation would be wasteful (e.g., health checks).
            audit_fn:               Callable for audit trail writes.

        Returns:
            SessionValidation. Check .valid before using .session or .new_token.
        """
        with self._lock:
            self._purge_expired(audit_fn)

            token_hash = self._hash_token(token)
            session = self._sessions.get(token_hash)

            # Token not found — either expired, rotated, or fabricated
            if session is None:
                if audit_fn:
                    audit_fn(
                        event_type="SESSION_INVALID_TOKEN",
                        details={
                            "token_prefix": token_hash[:8],
                            "reason": "token_not_found",
                        }
                    )
                return SessionValidation(valid=False, reason="invalid_or_expired_token")

            # Connection binding check (T-013 mitigation)
            if ENFORCE_CONNECTION_BINDING and session.connection_fingerprint_hash is not None:
                presented_fp_hash = self._hash_fingerprint(connection_fingerprint)
                if presented_fp_hash != session.connection_fingerprint_hash:
                    # This is a meaningful security event — log it prominently
                    if audit_fn:
                        audit_fn(
                            event_type="SESSION_BINDING_VIOLATION",
                            details={
                                "token_prefix": session.token_prefix,
                                "user_id": session.user_id,
                                "reason": "connection_fingerprint_mismatch",
                            }
                        )
                    # Invalidate the session — a binding violation is suspicious
                    self._sessions.pop(token_hash, None)
                    return SessionValidation(valid=False, reason="connection_binding_violation")

            now = time.time()

            # Update sliding TTL if enabled
            if SLIDING_TTL:
                new_expiry = min(now + DEFAULT_TTL_SECONDS, session.created_at + MAX_LIFETIME_SECONDS)
                session.expires_at = new_expiry

            session.last_used_at = now

            # Token rotation
            if rotate:
                new_raw_token = secrets.token_hex(TOKEN_BYTES)
                new_token_hash = self._hash_token(new_raw_token)
                new_token_prefix = new_token_hash[:8]

                # Migrate session to new token hash
                self._sessions.pop(token_hash)
                session.token_hash = new_token_hash
                session.token_prefix = new_token_prefix
                session.rotated_at = now
                se
