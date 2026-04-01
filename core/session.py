"""
core/session.py

Session management layer for ONTO.
Implements item 2.09 of the pre-launch security checklist.

Design decisions (all from THREAT_MODEL_001, REVIEW_001, and CRE-SPEC-001):

  TOKEN SECURITY
  - Session token is 32 bytes (256-bit) of cryptographic randomness.
  - _sessions is keyed by the raw token string. The token lives in memory
    only and is never logged, persisted, or included in audit records.
    Only the 8-char hash prefix (token_prefix) appears in audit events.
  - Tokens are rotated on each explicit rotate() call (T-013 mitigation).

  SESSION TOKEN AS STRING
  - SessionToken inherits from str. Passes isinstance(token, str), works
    with int(token, 16), len(token), set/dict membership, and all str ops.
    Extra attributes: .expires_at, .identity, .token_prefix, .token.

  AUDIT TRAIL
  - self._audit_log: always-on internal list, appended on every event.
  - self._audit_fn: registered observer via set_audit_fn(). Dispatched
    with adaptive signature: tries (event_type, details) first, falls
    back to (event_type,) if TypeError -- supports any 1- or 2-arg callable.
  - Per-call audit_fn: also accepted on every method with same adaptation.

  REGULATORY FORWARD-COMPATIBILITY
  - identity: "local" in Stage 1; real user identity in Stage 2.
  - consent_reference: None in Stage 1; consent ledger pointer in Stage 2
    (GDPR Art. 7, CCPA right-to-know).
  - data_classification: highest sensitivity touched (GDPR Art. 30).

  STAGE 1 CONSTRAINTS
  - Single session at a time (MAX_CONCURRENT_SESSIONS = 1).
  - Thread-safe -- lock protects all mutations.

Architecture:
  Stage 1 (now):    Single user, local passphrase, idle + hard expiry.
  Stage 2 (future): Multi-user, roles, consent references.
  Stage 3 (future): Federated sessions, cross-node token verification.

Public interface (stable):
  set_audit_fn(fn)                    -> None
  start(identity, idle_timeout, ...)  -> SessionToken (is a str)
  validate(token, ...)                -> Optional[SessionRecord]
  rotate(token, ...)                  -> Optional[SessionToken]
  terminate(token, ...)               -> bool
  is_active()                         -> bool  (no args -- any session active?)
  active_session()                    -> Optional[SessionRecord]
  active_session_count()              -> int
  reset()                             -> None

SessionRecord attributes:
  .identity            .token_prefix       .data_classification
  .created_at          .started_at         (alias for created_at)
  .last_used_at        .last_active        (alias for last_used_at)
  .expires_at          .idle_timeout       .consent_reference
  .is_expired()        .is_idle_expired()  .is_hard_expired()

Verbose aliases:
  create_session(**kw) -> start(**kw)
  validate_session(**kw) -> validate(**kw)
  end_session(**kw) -> terminate(**kw)
"""

import hashlib
import os
import secrets
import threading
import time
from dataclasses import dataclass
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

    Field aliases (for test and application compatibility):
      .started_at   -- alias for .created_at
      .last_active  -- alias for .last_used_at
      .token        -- alias for .token_prefix (stable string handle)

    Regulatory fields:
      identity          -- who this session belongs to (GDPR Art. 30)
      consent_reference -- which consent record authorizes it (GDPR Art. 7)
      data_classification -- highest sensitivity touched (GDPR Art. 30)
    """
    token_prefix: str                           # sha256(raw_token)[:8] -- safe to log
    identity: str
    created_at: float
    expires_at: float
    last_used_at: float
    idle_timeout: float
    connection_fingerprint_hash: Optional[str]
    consent_reference: Optional[str]
    data_classification: str = "UNCLASSIFIED"
    rotated_at: Optional[float] = None

    # ------------------------------------------------------------------
    # FIELD ALIASES
    # ------------------------------------------------------------------

    @property
    def started_at(self) -> float:
        """Alias for created_at. When the session was first established."""
        return self.created_at

    @property
    def last_active(self) -> float:
        """Alias for last_used_at. When the session was last validated."""
        return self.last_used_at

    @property
    def token(self) -> str:
        """Stable string handle. Returns token_prefix (safe to log)."""
        return self.token_prefix

    # ------------------------------------------------------------------
    # EXPIRY CHECKS
    # ------------------------------------------------------------------

    def is_idle_expired(self) -> bool:
        """True if inactive longer than idle_timeout."""
        return (time.time() - self.last_used_at) > self.idle_timeout

    def is_hard_expired(self) -> bool:
        """True if past the hard expiry ceiling."""
        return time.time() > self.expires_at

    def is_expired(self) -> bool:
        """True if expired by either idle timeout or hard ceiling."""
        return self.is_idle_expired() or self.is_hard_expired()


class SessionToken(str):
    """
    A bearer token returned after session creation or rotation.

    Inherits from str -- passes isinstance(token, str), works with
    int(token, 16), len(token), set/dict membership, all str operations.
    The string value IS the raw bearer token.

    Extra attributes:
      .expires_at    -- Unix timestamp when this token expires
      .identity      -- who this session belongs to
      .token_prefix  -- first 8 hex chars of sha256, safe to log
      .token         -- returns self (the raw token string)
    """

    def __new__(
        cls,
        token: str,
        expires_at: float,
        identity: str,
        token_prefix: str,
    ) -> "SessionToken":
        instance = super().__new__(cls, token)
        instance.expires_at = expires_at
        instance.identity = identity
        instance.token_prefix = token_prefix
        return instance

    @property
    def token(self) -> str:
        """The raw token string. Provided for backward compatibility."""
        return str(self)

    def __repr__(self) -> str:
        return f"SessionToken(prefix={self.token_prefix!r}, identity={self.identity!r})"


# ---------------------------------------------------------------------------
# SESSION MANAGER
# ---------------------------------------------------------------------------

class SessionManager:
    """
    Thread-safe session manager for ONTO.

    _sessions is keyed by the raw token string (the bearer token itself),
    allowing direct access via _sessions[token] in tests and diagnostics.
    The raw token never appears in logs or audit records.

    Audit observers registered via set_audit_fn() receive events with
    adaptive dispatch: fn(event_type, details) or fn(event_type) -- both
    signatures are supported. Any callable that accepts 1 or 2 positional
    arguments works.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionRecord] = {}
        self._audit_log: List[dict] = []
        self._audit_fn: Optional[Callable] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # AUDIT OBSERVER REGISTRATION
    # ------------------------------------------------------------------

    def set_audit_fn(self, fn: Optional[Callable]) -> None:
        """
        Register an audit observer callable.

        Supported signatures (both work):
          fn(event_type: str, details: dict)
          fn(event_type: str)

        Set fn=None to deregister.
        """
        with self._lock:
            self._audit_fn = fn

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _prefix(raw_token: str) -> str:
        """First 8 hex chars of sha256(raw_token). Safe to log."""
        return hashlib.sha256(str(raw_token).encode()).hexdigest()[:8]

    def _hash_fingerprint(self, fingerprint: Optional[str]) -> Optional[str]:
        if fingerprint is None:
            return None
        return hashlib.sha256(fingerprint.encode()).hexdigest()

    @staticmethod
    def _call_fn(fn: Callable, event_type: str, details: dict) -> None:
        """
        Call an audit observer with adaptive signature handling.
        Tries (event_type, details) first; falls back to (event_type,)
        if the callable only accepts one positional argument.
        All exceptions are silenced -- audit failure must never break
        session operations.
        """
        try:
            fn(event_type, details)
        except TypeError:
            try:
                fn(event_type)
            except Exception:
                pass
        except Exception:
            pass

    def _dispatch(
        self,
        event_type: str,
        details: dict,
        audit_fn: Optional[Callable] = None,
    ) -> None:
        """
        Append event to _audit_log and dispatch to all registered observers.
        Always-on -- every lifecycle event is recorded.
        Raw tokens never appear in event details.
        """
        entry = {"event_type": event_type, "timestamp": time.time(), **details}
        self._audit_log.append(entry)

        # Registered observer
        if self._audit_fn is not None:
            self._call_fn(self._audit_fn, event_type, details)

        # Per-call observer (only if different from registered one)
        if audit_fn is not None and audit_fn is not self._audit_fn:
            self._call_fn(audit_fn, event_type, details)

    def _purge_expired(self, audit_fn: Optional[Callable] = None) -> None:
        """
        Remove expired sessions. Called inside lock on every public op.
        GDPR Art. 5(1)(c) -- data minimization.
        """
        now = time.time()
        expired = [t for t, s in self._sessions.items() if s.is_expired()]
        for raw_token in expired:
            session = self._sessions.pop(raw_token)
            self._dispatch(
                "SESSION_EXPIRED",
                {
                    "token_prefix": session.token_prefix,
                    "identity": session.identity,
                    "created_at": session.created_at,
                    "expired_at": now,
                    "data_classification": session.data_classification,
                },
                audit_fn,
            )

    def _do_rotate(
        self,
        old_raw_token: str,
        session: SessionRecord,
        audit_fn: Optional[Callable] = None,
    ) -> "SessionToken":
        """Internal rotation -- must be called with lock already held."""
        new_raw = secrets.token_hex(TOKEN_BYTES)
        new_prefix = self._prefix(new_raw)
        old_prefix = session.token_prefix

        del self._sessions[old_raw_token]
        session.token_prefix = new_prefix
        session.rotated_at = time.time()
        self._sessions[new_raw] = session

        self._dispatch(
            "SESSION_ROTATED",
            {
                "old_token_prefix": old_prefix,
                "new_token_prefix": new_prefix,
                "identity": session.identity,
            },
            audit_fn,
        )

        return SessionToken(
            token=new_raw,
            expires_at=session.expires_at,
            identity=session.identity,
            token_prefix=new_prefix,
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
    ) -> "SessionToken":
        """
        Create a new session and return the bearer token.
        Returns a SessionToken which IS a str -- passes isinstance(x, str).
        """
        _idle = idle_timeout if idle_timeout is not None else float(DEFAULT_TTL_SECONDS)
        _max = max_duration if max_duration is not None else float(MAX_LIFETIME_SECONDS)

        with self._lock:
            self._purge_expired(audit_fn)

            if len(self._sessions) >= MAX_CONCURRENT_SESSIONS:
                oldest_key = min(
                    self._sessions,
                    key=lambda t: self._sessions[t].created_at
                )
                superseded = self._sessions.pop(oldest_key)
                self._dispatch(
                    "SESSION_SUPERSEDED",
                    {
                        "token_prefix": superseded.token_prefix,
                        "identity": superseded.identity,
                        "reason": "new_session_created_at_capacity",
                    },
                    audit_fn,
                )

            raw_token = secrets.token_hex(TOKEN_BYTES)
            token_prefix = self._prefix(raw_token)
            now = time.time()

            session = SessionRecord(
                token_prefix=token_prefix,
                identity=identity,
                created_at=now,
                expires_at=now + _max,
                last_used_at=now,
                idle_timeout=_idle,
                connection_fingerprint_hash=self._hash_fingerprint(connection_fingerprint),
                consent_reference=consent_reference,
            )
            self._sessions[raw_token] = session

            self._dispatch(
                "SESSION_START",
                {
                    "token_prefix": token_prefix,
                    "identity": identity,
                    "expires_at": now + _max,
                    "idle_timeout": _idle,
                    "connection_bound": connection_fingerprint is not None,
                    "consent_reference": consent_reference,
                },
                audit_fn,
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
        Returns the SessionRecord if valid, None if not found or expired.
        """
        with self._lock:
            self._purge_expired(audit_fn)

            raw_token = str(token)
            session = self._sessions.get(raw_token)

            if session is None:
                self._dispatch(
                    "SESSION_INVALID_TOKEN",
                    {"token_prefix": self._prefix(raw_token), "reason": "token_not_found"},
                    audit_fn,
                )
                return None

            if ENFORCE_CONNECTION_BINDING and session.connection_fingerprint_hash is not None:
                if self._hash_fingerprint(connection_fingerprint) != session.connection_fingerprint_hash:
                    self._dispatch(
                        "SESSION_BINDING_VIOLATION",
                        {
                            "token_prefix": session.token_prefix,
                            "identity": session.identity,
                            "reason": "connection_fingerprint_mismatch",
                        },
                        audit_fn,
                    )
                    del self._sessions[raw_token]
                    return None

            session.last_used_at = time.time()
            return session

    def rotate(
        self,
        token: str,
        audit_fn: Optional[Callable] = None,
    ) -> Optional["SessionToken"]:
        """
        Rotate a session token. Old token is immediately invalidated.
        Returns new SessionToken, or None if token not found.
        """
        with self._lock:
            self._purge_expired(audit_fn)
            raw_token = str(token)
            session = self._sessions.get(raw_token)
            if session is None:
                return None
            return self._do_rotate(raw_token, session, audit_fn)

    def terminate(
        self,
        token: str,
        audit_fn: Optional[Callable] = None,
    ) -> bool:
        """
        Explicitly end a session. Record removed immediately.
        Returns True if found and ended, False otherwise.
        GDPR Art. 5(1)(c) -- processing stops when purpose is achieved.
        """
        with self._lock:
            raw_token = str(token)
            session = self._sessions.pop(raw_token, None)
            if session is None:
                return False
            self._dispatch(
                "SESSION_END",
                {
                    "token_prefix": session.token_prefix,
                    "identity": session.identity,
                    "duration_seconds": round(time.time() - session.created_at, 2),
                    "data_classification": session.data_classification,
                    "consent_reference": session.consent_reference,
                },
                audit_fn,
            )
            return True

    def is_active(self) -> bool:
        """
        Return True if any session is currently active (not expired).
        No-argument check -- use validate(token) to check a specific token.
        """
        with self._lock:
            return any(not s.is_expired() for s in self._sessions.values())

    def active_session(self) -> Optional[SessionRecord]:
        """
        Return the active SessionRecord if one exists, None otherwise.
        Falsy when None; truthy with .identity, .started_at, etc. when active.
        """
        with self._lock:
            for s in self._sessions.values():
                if not s.is_expired():
                    return s
            return None

    def active_session_count(self) -> int:
        """Number of currently active (non-expired) sessions."""
        with self._lock:
            return sum(1 for s in self._sessions.values() if not s.is_expired())

    def update_data_classification(
        self,
        token: str,
        classification: str,
        audit_fn: Optional[Callable] = None,
    ) -> bool:
        """
        Escalate data classification if more sensitive. Never downgrades.
        GDPR Art. 30 records of processing.
        Order: UNCLASSIFIED < INTERNAL < CONFIDENTIAL < RESTRICTED < SENSITIVE
        """
        sensitivity_order = {
            "UNCLASSIFIED": 0, "INTERNAL": 1, "CONFIDENTIAL": 2,
            "RESTRICTED": 3, "SENSITIVE": 4,
        }
        with self._lock:
            raw_token = str(token)
            session = self._sessions.get(raw_token)
            if session is None:
                return False
            current = sensitivity_order.get(session.data_classification, 0)
            new = sensitivity_order.get(classification, 0)
            if new > current:
                old = session.data_classification
                session.data_classification = classification
                self._dispatch(
                    "SESSION_CLASSIFICATION_ESCALATED",
                    {
                        "token_prefix": session.token_prefix,
                        "identity": session.identity,
                        "from": old,
                        "to": classification,
                    },
                    audit_fn,
                )
                return True
            return False

    def clear_audit_log(self) -> None:
        """Clear the internal audit log in place. For use between tests."""
        with self._lock:
            self._audit_log.clear()

    def reset(self) -> None:
        """
        Clear all sessions and audit log. For test setUp().
        Does not deregister a registered audit_fn.
        """
        with self._lock:
            self._sessions.clear()
            self._audit_log.clear()

    # ------------------------------------------------------------------
    # VERBOSE ALIASES
    # ------------------------------------------------------------------

    def create_session(self, **kwargs) -> "SessionToken":
        """Verbose alias for start()."""
        return self.start(**kwargs)

    def validate_session(self, **kwargs) -> Optional[SessionRecord]:
        """Verbose alias for validate()."""
        return self.validate(**kwargs)

    def end_session(self, **kwargs) -> bool:
        """Verbose alias for terminate()."""
        return self.terminate(**kwargs)


# ---------------------------------------------------------------------------
# MODULE-LEVEL SINGLETON
# ---------------------------------------------------------------------------

# Import this instance everywhere. Do not instantiate SessionManager directly.
session_manager = SessionManager()
