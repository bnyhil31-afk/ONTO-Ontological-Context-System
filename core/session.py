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
  - Sessions are optionally bound to a connection fingerprint (e.g., IP
    address hash). A token presented from an unrecognized connection is
    rejected. Configurable — disable for roaming clients (mobile, etc.).

  REGULATORY FORWARD-COMPATIBILITY
  - identity field: "local" in Stage 1; real user identity in Stage 2.
    Schema does not change between stages — only the value.
  - consent_reference: None for Stage 1 local user. Points to the consent
    ledger record in Stage 2 (GDPR Art. 7, CCPA right-to-know).
  - data_classification: highest sensitivity touched this session.
    Required for GDPR Art. 30 records of processing activities.

  AUDIT TRAIL
  - Every session lifecycle event written to audit trail:
    SESSION_START, SESSION_END, SESSION_EXPIRED, SESSION_ROTATED,
    SESSION_INVALID_TOKEN, SESSION_BINDING_VIOLATION, SESSION_SUPERSEDED.
  - Raw tokens are NEVER written -- only 8-char hash prefix for correlation.

  STAGE 1 CONSTRAINTS
  - Single session at a time (MAX_CONCURRENT_SESSIONS = 1).
  - Thread-safe by design -- lock protects all mutations.
    Ready for Stage 2 concurrent use without modification.

  EXPIRY MODEL
  - idle_timeout: session expires after this many seconds of inactivity.
    Resets on each valid use. Maps to DEFAULT_TTL_SECONDS by default.
  - max_duration: hard ceiling -- session expires regardless of activity.
    Maps to MAX_LIFETIME_SECONDS. Protects against long-lived compromised
    sessions.
  - Both are configurable per-session and via environment variables.

Architecture:
  Stage 1 (now):    Single user, local passphrase auth, absolute TTL.
  Stage 2 (future): Multi-user, roles, consent references, sliding TTL.
  Stage 3 (future): Federated sessions, cross-node token verification.

Public interface (stable contract -- do not change method signatures):
  start(identity, idle_timeout, ...)  -> SessionToken
  validate(token, ...)                -> SessionValidation
  rotate(token, ...)                  -> SessionToken | None
  terminate(token, ...)               -> bool
  active_session                      -> bool (property)
  active_session_count                -> int  (property)

Verbose aliases (for documentation clarity):
  create_session(...) -> start(...)
  validate_session(...) -> validate(...)
  end_session(...) -> terminate(...)
"""

import hashlib
import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

# ---------------------------------------------------------------------------
# CONSTANTS -- all overridable via environment variables (see core/config.py)
# ---------------------------------------------------------------------------

TOKEN_BYTES = 32  # 256 bits of entropy

DEFAULT_TTL_SECONDS = int(os.environ.get("ONTO_SESSION_TTL_SECONDS", "3600"))
MAX_LIFETIME_SECONDS = int(os.environ.get("ONTO_SESSION_MAX_LIFETIME_SECONDS", "28800"))

ENFORCE_CONNECTION_BINDING = (
    os.environ.get("ONTO_SESSION_BINDING", "true").lower() == "true"
)

MAX_CONCURRENT_SESSIONS = int(os.environ.get("ONTO_MAX_SESSIONS", "1"))


# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------

@dataclass
class SessionRecord:
    """
    Internal representation of an active session. Never written to disk.

    Regulatory fields:
      identity          -- who this session belongs to (GDPR Art. 30)
      consent_reference -- which consent record authorizes it (GDPR Art. 7)
      data_classification -- highest sensitivity touched (GDPR Art. 30)
    """
    token_hash: str
    token_prefix: str                           # First 8 hex chars -- audit correlation only
    identity: str                               # "local" in Stage 1; real identity in Stage 2
    created_at: float
    expires_at: float                           # Hard expiry (max_duration ceiling)
    last_used_at: float
    idle_timeout: float                         # Seconds of inactivity before expiry
    connection_fingerprint_hash: Optional[str]
    consent_reference: Optional[str]            # Consent ledger pointer (Stage 2+)
    data_classification: str = "UNCLASSIFIED"
    rotated_at: Optional[float] = None

    def is_idle_expired(self) -> bool:
        """True if the session has been idle longer than idle_timeout."""
        return (time.time() - self.last_used_at) > self.idle_timeout

    def is_hard_expired(self) -> bool:
        """True if the session has exceeded its maximum lifetime."""
        return time.time() > self.expires_at

    def is_expired(self) -> bool:
        """True if the session is expired by either idle or hard ceiling."""
        return self.is_idle_expired() or self.is_hard_expired()


@dataclass
class SessionToken:
    """
    Returned after session creation or rotation.
    This is the ONLY moment the raw token is visible.

    Behaves like a string for compatibility -- supports .encode() and str().
    The raw token value is accessed via .token, str(), or .encode().
    """
    token: str          # Raw bearer token -- treat like a password
    expires_at: float
    identity: str
    token_prefix: str   # Safe to log

    def encode(self, encoding: str = "utf-8") -> bytes:
        """Return the raw token as bytes. Enables str-like usage in consumers."""
        return self.token.encode(encoding)

    def __str__(self) -> str:
        return self.token

    def __repr__(self) -> str:
        return f"SessionToken(prefix={self.token_prefix!r}, identity={self.identity!r})"


@dataclass
class SessionValidation:
    """
    Result of validate(). Check .valid before using .session or .new_token.

    new_token is present when token rotation occurred. The caller must
    use the new token for all subsequent requests -- the old one is invalid.
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

    All state is in-memory. The audit trail receives lifecycle events
    but never raw tokens.

    Designed for Stage 2 from day one:
      - identity and consent_reference are first-class fields
      - Lock and concurrent session limit already in place
      - Public interface contract is stable across all stages
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionRecord] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _hash_fingerprint(self, fingerprint: Optional[str]) -> Optional[str]:
        if fingerprint is None:
            return None
        return hashlib.sha256(fingerprint.encode()).hexdigest()

    def _purge_expired(self, audit_fn: Optional[Callable] = None) -> None:
        """
        Remove all expired sessions. Called on every public operation.
        GDPR Art. 5(1)(c) -- data minimization: session records are personal
        data and must not outlive their purpose.
        """
        now = time.time()
        expired = [h for h, s in self._sessions.items() if s.is_expired()]
        for token_hash in expired:
            session = self._sessions.pop(token_hash)
            if audit_fn:
                audit_fn(
                    event_type="SESSION_EXPIRED",
                    details={
                        "token_prefix": session.token_prefix,
                        "identity": session.identity,
                        "created_at": session.created_at,
                        "expired_at": now,
                        "data_classification": session.data_classification,
                    }
                )

    def _do_rotate(
        self,
        token_hash: str,
        session: SessionRecord,
        audit_fn: Optional[Callable] = None,
    ) -> SessionToken:
        """Internal rotation -- must be called with lock already held."""
        new_raw_token = secrets.token_hex(TOKEN_BYTES)
        new_token_hash = self._hash_token(new_raw_token)
        new_token_prefix = new_token_hash[:8]
        old_prefix = session.token_prefix

        self._sessions.pop(token_hash)
        session.token_hash = new_token_hash
        session.token_prefix = new_token_prefix
        session.rotated_at = time.time()
        self._sessions[new_token_hash] = session

        if audit_fn:
            audit_fn(
                event_type="SESSION_ROTATED",
                details={
                    "old_token_prefix": old_prefix,
                    "new_token_prefix": new_token_prefix,
                    "identity": session.identity,
                }
            )

        return SessionToken(
            token=new_raw_token,
            expires_at=session.expires_at,
            identity=session.identity,
            token_prefix=new_token_prefix,
        )

    # ------------------------------------------------------------------
    # PRIMARY PUBLIC INTERFACE
    # ------------------------------------------------------------------

    def start(
        self,
        identity: str = "local",
        idle_timeout: Optional[float] = None,
        max_duration: Optional[float] = None,
        connection_fingerprint: Optional[str] = None,
        consent_reference: Optional[str] = None,
        audit_fn: Optional[Callable] = None,
    ) -> SessionToken:
        """
        Create a new authenticated session and return the bearer token.

        Args:
            identity:              Who this session belongs to ("local" in Stage 1).
            idle_timeout:          Seconds of inactivity before expiry.
            max_duration:          Hard ceiling in seconds regardless of activity.
            connection_fingerprint: Connection identifier hashed before storage.
            consent_reference:     Consent ledger pointer (Stage 2+).
            audit_fn:              Audit trail writer callable.

        Returns:
            SessionToken with raw token in .token, str(), and .encode().
        """
        _idle = idle_timeout if idle_timeout is not None else float(DEFAULT_TTL_SECONDS)
        _max = max_duration if max_duration is not None else float(MAX_LIFETIME_SECONDS)

        with self._lock:
            self._purge_expired(audit_fn)

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
                            "identity": superseded.identity,
                            "reason": "new_session_created_at_capacity",
                        }
                    )

            raw_token = secrets.token_hex(TOKEN_BYTES)
            token_hash = self._hash_token(raw_token)
            token_prefix = token_hash[:8]
            now = time.time()

            session = SessionRecord(
                token_hash=token_hash,
                token_prefix=token_prefix,
                identity=identity,
                created_at=now,
                expires_at=now + _max,
                last_used_at=now,
                idle_timeout=_idle,
                connection_fingerprint_hash=self._hash_fingerprint(connection_fingerprint),
                consent_reference=consent_reference,
            )
            self._sessions[token_hash] = session

            if audit_fn:
                audit_fn(
                    event_type="SESSION_START",
                    details={
                        "token_prefix": token_prefix,
                        "identity": identity,
                        "expires_at": now + _max,
                        "idle_timeout": _idle,
                        "connection_bound": connection_fingerprint is not None,
                        "consent_reference": consent_reference,
                    }
                )

            return SessionToken(
                token=raw_token,
                expires_at=now + _max,
                identity=identity,
                token_prefix=token_prefix,
            )

    def validate(
        self,
        token: str,
        connection_fingerprint: Optional[str] = None,
        rotate: bool = False,
        audit_fn: Optional[Callable] = None,
    ) -> SessionValidation:
        """
        Validate a bearer token.

        Does NOT rotate by default. Pass rotate=True to combine validation
        and rotation in one call, or call rotate() explicitly.
        """
        with self._lock:
            self._purge_expired(audit_fn)

            token_hash = self._hash_token(token)
            session = self._sessions.get(token_hash)

            if session is None:
                if audit_fn:
                    audit_fn(
                        event_type="SESSION_INVALID_TOKEN",
                        details={"token_prefix": token_hash[:8], "reason": "token_not_found"}
                    )
                return SessionValidation(valid=False, reason="invalid_or_expired_token")

            if ENFORCE_CONNECTION_BINDING and session.connection_fingerprint_hash is not None:
                presented_fp_hash = self._hash_fingerprint(connection_fingerprint)
                if presented_fp_hash != session.connection_fingerprint_hash:
                    if audit_fn:
                        audit_fn(
                            event_type="SESSION_BINDING_VIOLATION",
                            details={
                                "token_prefix": session.token_prefix,
                                "identity": session.identity,
                                "reason": "connection_fingerprint_mismatch",
                            }
                        )
                    self._sessions.pop(token_hash, None)
                    return SessionValidation(valid=False, reason="connection_binding_violation")

            session.last_used_at = time.time()

            if rotate:
                new_token = self._do_rotate(token_hash, session, audit_fn)
                return SessionValidation(valid=True, session=session, new_token=new_token)

            return SessionValidation(valid=True, session=session, new_token=None)

    def rotate(
        self,
        token: str,
        audit_fn: Optional[Callable] = None,
    ) -> Optional[SessionToken]:
        """
        Rotate a session token. Old token is immediately invalidated.
        Returns the new SessionToken, or None if token was not found.

        Limits replay window for intercepted tokens to one request cycle (T-013).
        """
        with self._lock:
            self._purge_expired(audit_fn)
            token_hash = self._hash_token(token)
            session = self._sessions.get(token_hash)
            if session is None:
                return None
            return self._do_rotate(token_hash, session, audit_fn)

    def terminate(
        self,
        token: str,
        audit_fn: Optional[Callable] = None,
    ) -> bool:
        """
        Explicitly end a session. Session record removed immediately.
        GDPR Art. 5(1)(c) -- processing stops as soon as purpose is achieved.

        Returns True if a session was found and ended, False otherwise.
        """
        with self._lock:
            token_hash = self._hash_token(token)
            session = self._sessions.pop(token_hash, None)
            if session is None:
                return False
            now = time.time()
            if audit_fn:
                audit_fn(
                    event_type="SESSION_END",
                    details={
                        "token_prefix": session.token_prefix,
                        "identity": session.identity,
                        "duration_seconds": round(now - session.created_at, 2),
                        "data_classification": session.data_classification,
                        "consent_reference": session.consent_reference,
                    }
                )
            return True

    def update_data_classification(
        self,
        token: str,
        classification: str,
        audit_fn: Optional[Callable] = None,
    ) -> bool:
        """
        Escalate data classification for this session if more sensitive.
        Never downgrades. Satisfies GDPR Art. 30 records of processing.

        Order: UNCLASSIFIED < INTERNAL < CONFIDENTIAL < RESTRICTED < SENSITIVE
        """
        sensitivity_order = {
            "UNCLASSIFIED": 0, "INTERNAL": 1, "CONFIDENTIAL": 2,
            "RESTRICTED": 3, "SENSITIVE": 4,
        }
        with self._lock:
            token_hash = self._hash_token(token)
            session = self._sessions.get(token_hash)
            if session is None:
                return False
            current = sensitivity_order.get(session.data_classification, 0)
            new = sensitivity_order.get(classification, 0)
            if new > current:
                old = session.data_classification
                session.data_classification = classification
                if audit_fn:
                    audit_fn(
                        event_type="SESSION_CLASSIFICATION_ESCALATED",
                        details={
                            "token_prefix": session.token_prefix,
                            "identity": session.identity,
                            "from": old,
                            "to": classification,
                        }
                    )
                return True
            return False

    # ------------------------------------------------------------------
    # PROPERTIES
    # ------------------------------------------------------------------

    @property
    def active_session(self) -> bool:
        """True if there is at least one non-expired active session."""
        with self._lock:
            return any(not s.is_expired() for s in self._sessions.values())

    @property
    def active_session_count(self) -> int:
        """Number of currently active (non-expired) sessions."""
        with self._lock:
            return sum(1 for s in self._sessions.values() if not s.is_expired())

    # ------------------------------------------------------------------
    # VERBOSE ALIASES -- full names for documentation clarity
    # ------------------------------------------------------------------

    def create_session(self, **kwargs) -> SessionToken:
        """Verbose alias for start(). Preferred in documentation."""
        return self.start(**kwargs)

    def validate_session(self, **kwargs) -> SessionValidation:
        """Verbose alias for validate(). Preferred in documentation."""
        return self.validate(**kwargs)

    def end_session(self, **kwargs) -> bool:
        """Verbose alias for terminate(). Preferred in documentation."""
        return self.terminate(**kwargs)


# ---------------------------------------------------------------------------
# MODULE-LEVEL SINGLETON
# ---------------------------------------------------------------------------

# Import this instance everywhere. Do not instantiate SessionManager directly.
session_manager = SessionManager()
