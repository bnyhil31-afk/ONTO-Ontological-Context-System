"""
core/session.py

Session management layer for ONTO.
Implements item 2.09 of the pre-launch security checklist.

Design decisions (all from THREAT_MODEL_001, REVIEW_001, and CRE-SPEC-001):

  TOKEN SECURITY
  - Session token is 32 bytes (256-bit) of cryptographic randomness.
  - The raw token is NEVER stored -- only its SHA-256 hash is held in memory.
    This means even if the session store is read, tokens cannot be replayed.
  - Tokens are rotated on each authenticated request, limiting the replay
    window for any intercepted token (T-013 mitigation).

  CONNECTION BINDING (T-013)
  - Sessions are optionally bound to a connection fingerprint (e.g., IP
    address hash). Configurable -- disable for roaming clients.

  REGULATORY FORWARD-COMPATIBILITY
  - identity: "local" in Stage 1; real user identity in Stage 2.
  - consent_reference: None in Stage 1; consent ledger pointer in Stage 2
    (GDPR Art. 7, CCPA right-to-know).
  - data_classification: highest sensitivity touched this session
    (GDPR Art. 30 records of processing activities).

  AUDIT TRAIL
  - Every lifecycle event is appended to self._audit_log (always on).
  - An optional audit_fn callable is also invoked if provided, enabling
    integration with ONTO's SQLite audit trail without tight coupling.
  - Raw tokens are NEVER recorded -- only the 8-char hash prefix.

  STAGE 1 CONSTRAINTS
  - Single session at a time (MAX_CONCURRENT_SESSIONS = 1).
  - Thread-safe -- lock protects all state mutations.
    Ready for Stage 2 concurrent use without modification.

  EXPIRY MODEL
  - idle_timeout: expires after N seconds of inactivity (sliding).
  - max_duration: hard ceiling regardless of activity.

Architecture:
  Stage 1 (now):    Single user, local passphrase, idle + hard expiry.
  Stage 2 (future): Multi-user, roles, consent references.
  Stage 3 (future): Federated sessions, cross-node token verification.

Public interface (stable -- do not change signatures):
  start(identity, idle_timeout, ...)  -> SessionToken
  validate(token, ...)                -> Optional[SessionRecord]
  rotate(token, ...)                  -> Optional[SessionToken]
  terminate(token, ...)               -> bool
  active_session()                    -> bool
  active_session_count()              -> int
  _audit_log                          -> list (internal, inspectable by tests)

Verbose aliases:
  create_session(...) -> start(...)
  validate_session(...) -> validate(...)
  end_session(...) -> terminate(...)
"""

import hashlib
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# CONSTANTS
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
    token_prefix: str
    identity: str
    created_at: float
    expires_at: float
    last_used_at: float
    idle_timeout: float
    connection_fingerprint_hash: Optional[str]
    consent_reference: Optional[str]
    data_classification: str = "UNCLASSIFIED"
    rotated_at: Optional[float] = None

    def is_idle_expired(self) -> bool:
        return (time.time() - self.last_used_at) > self.idle_timeout

    def is_hard_expired(self) -> bool:
        return time.time() > self.expires_at

    def is_expired(self) -> bool:
        return self.is_idle_expired() or self.is_hard_expired()


@dataclass
class SessionToken:
    """
    Returned after session creation or rotation.
    The ONLY moment the raw token is visible.

    Behaves like a string:
      str(session_token)    -> raw token string
      len(session_token)    -> len of raw token string
      session_token.encode() -> raw token as bytes
      hash(session_token)   -> stable hash for use in sets/dicts
    """
    token: str
    expires_at: float
    identity: str
    token_prefix: str

    def __str__(self) -> str:
        return self.token

    def __repr__(self) -> str:
        return f"SessionToken(prefix={self.token_prefix!r}, identity={self.identity!r})"

    def __len__(self) -> int:
        return len(self.token)

    def __hash__(self) -> int:
        return hash(self.token)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SessionToken):
            return self.token == other.token
        if isinstance(other, str):
            return self.token == other
        return NotImplemented

    def encode(self, encoding: str = "utf-8") -> bytes:
        """Return the raw token as bytes."""
        return self.token.encode(encoding)


# ---------------------------------------------------------------------------
# SESSION MANAGER
# ---------------------------------------------------------------------------

class SessionManager:
    """
    Thread-safe session manager for ONTO.

    All session state is in-memory. Every lifecycle event is written to
    self._audit_log (always on) and optionally to an injected audit_fn.

    Designed for Stage 2 from day one:
      - identity and consent_reference are first-class fields
      - Lock and concurrent session limit already in place
      - Public interface contract is stable across all stages
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionRecord] = {}
        self._audit_log: List[dict] = []
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

    def _record(
        self,
        event_type: str,
        details: dict,
        audit_fn: Optional[Callable] = None,
    ) -> None:
        """
        Write an audit event to the internal log and optionally to audit_fn.
        Always-on -- every lifecycle event is recorded regardless of audit_fn.
        Raw tokens are never included in details.
        """
        entry = {"event_type": event_type, "timestamp": time.time(), **details}
        self._audit_log.append(entry)
        if audit_fn:
            audit_fn(event_type=event_type, details=details)

    def _purge_expired(self, audit_fn: Optional[Callable] = None) -> None:
        """
        Remove all expired sessions. Called on every public operation.
        GDPR Art. 5(1)(c) -- data minimization.
        """
        expired = [h for h, s in self._sessions.items() if s.is_expired()]
        for token_hash in expired:
            session = self._sessions.pop(token_hash)
            self._record(
                event_type="SESSION_EXPIRED",
                details={
                    "token_prefix": session.token_prefix,
                    "identity": session.identity,
                    "created_at": session.created_at,
                    "expired_at": time.time(),
                    "data_classification": session.data_classification,
                },
                audit_fn=audit_fn,
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

        self._record(
            event_type="SESSION_ROTATED",
            details={
                "old_token_prefix": old_prefix,
                "new_token_prefix": new_token_prefix,
                "identity": session.identity,
            },
            audit_fn=audit_fn,
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
            max_duration:          Hard ceiling in seconds.
            connection_fingerprint: Connection identifier -- hashed before storage.
            consent_reference:     Consent ledger pointer (Stage 2+).
            audit_fn:              Optional audit trail writer callable.

        Returns:
            SessionToken. Behaves like a string -- use str(), len(), .encode().
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
                self._record(
                    event_type="SESSION_SUPERSEDED",
                    details={
                        "token_prefix": superseded.token_prefix,
                        "identity": superseded.identity,
                        "reason": "new_session_created_at_capacity",
                    },
                    audit_fn=audit_fn,
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

            self._record(
                event_type="SESSION_START",
                details={
                    "token_prefix": token_prefix,
                    "identity": identity,
                    "expires_at": now + _max,
                    "idle_timeout": _idle,
                    "connection_bound": connection_fingerprint is not None,
                    "consent_reference": consent_reference,
                },
                audit_fn=audit_fn,
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
        audit_fn: Optional[Callable] = None,
    ) -> Optional[SessionRecord]:
        """
        Validate a bearer token.

        Returns:
            The SessionRecord if the token is valid, None otherwise.
            Tests can access result.identity, result.data_classification, etc.
        """
        with self._lock:
            self._purge_expired(audit_fn)

            token_hash = self._hash_token(token)
            session = self._sessions.get(token_hash)

            if session is None:
                self._record(
                    event_type="SESSION_INVALID_TOKEN",
                    details={"token_prefix": token_hash[:8], "reason": "token_not_found"},
                    audit_fn=audit_fn,
                )
                return None

            if ENFORCE_CONNECTION_BINDING and session.connection_fingerprint_hash is not None:
                presented_fp_hash = self._hash_fingerprint(connection_fingerprint)
                if presented_fp_hash != session.connection_fingerprint_hash:
                    self._record(
                        event_type="SESSION_BINDING_VIOLATION",
                        details={
                            "token_prefix": session.token_prefix,
                            "identity": session.identity,
                            "reason": "connection_fingerprint_mismatch",
                        },
                        audit_fn=audit_fn,
                    )
                    self._sessions.pop(token_hash, None)
                    return None

            session.last_used_at = time.time()
            return session

    def rotate(
        self,
        token: str,
        audit_fn: Optional[Callable] = None,
    ) -> Optional[SessionToken]:
        """
        Rotate a session token. Old token is immediately invalidated.

        Returns the new SessionToken, or None if the token was not found.
        Caller must use the new token for all subsequent requests.
        Limits the replay window for intercepted tokens (T-013 mitigation).
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
            self._record(
                event_type="SESSION_END",
                details={
                    "token_prefix": session.token_prefix,
                    "identity": session.identity,
                    "duration_seconds": round(now - session.created_at, 2),
                    "data_classification": session.data_classification,
                    "consent_reference": session.consent_reference,
                },
                audit_fn=audit_fn,
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
                self._record(
                    event_type="SESSION_CLASSIFICATION_ESCALATED",
                    details={
                        "token_prefix": session.token_prefix,
                        "identity": session.identity,
                        "from": old,
                        "to": classification,
                    },
                    audit_fn=audit_fn,
                )
                return True
            return False

    # ------------------------------------------------------------------
    # STATUS METHODS
    # ------------------------------------------------------------------

    def active_session(self) -> bool:
        """True if there is at least one non-expired active session."""
        with self._lock:
            return any(not s.is_expired() for s in self._sessions.values())

    def active_session_count(self) -> int:
        """Number of currently active (non-expired) sessions."""
        with self._lock:
            return sum(1 for s in self._sessions.values() if not s.is_expired())

    def clear_audit_log(self) -> None:
        """Clear the internal audit log. Intended for use between tests."""
        with self._lock:
            self._audit_log.clear()

    # ------------------------------------------------------------------
    # VERBOSE ALIASES
    # ------------------------------------------------------------------

    def create_session(self, **kwargs) -> SessionToken:
        """Verbose alias for start(). Preferred in documentation."""
        return self.start(**kwargs)

    def validate_session(self, **kwargs) -> Optional[SessionRecord]:
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
