"""
core/session.py

Session management layer for ONTO.
Implements item 2.09 of the pre-launch security checklist.

Design decisions (all from THREAT_MODEL_001, REVIEW_001, and CRE-SPEC-001):

  TOKEN SECURITY
  - Session token is 32 bytes (256-bit) of cryptographic randomness.
  - _sessions is keyed by the raw token string. Token lives in memory
    only -- never logged, persisted, or included in audit records.
    Only the 8-char hash prefix (token_prefix) appears in audit events.

  SESSION TOKEN AS STRING
  - SessionToken inherits from str. Passes isinstance(token, str), works
    with int(token, 16), len(token), set/dict membership, all str ops.
    Extra attributes: .expires_at, .identity, .token_prefix, .token.

  SESSIONRECORD TIME MODEL
  - created_at / started_at: when the session was established.
  - last_used_at / last_active: when the session was last validated.
  - max_duration: the hard ceiling in seconds (stored, not derived).
  - expires_at: computed as created_at + max_duration. Winding back
    started_at (= created_at) therefore winds back expires_at too,
    allowing tests to simulate time passage without sleeping.
  - idle_timeout: seconds of inactivity before expiry (checked against
    last_used_at). Winding back last_active triggers idle expiry.

  AUDIT TRAIL
  - self._audit_log: always-on internal list, appended on every event.
  - self._audit_fn: registered observer via set_audit_fn().
  - Adaptive dispatch: tries fn(event_type, details), falls back to
    fn(event_type) on TypeError -- supports 1- or 2-arg callables.

  REGULATORY FORWARD-COMPATIBILITY
  - identity: "local" in Stage 1; real user identity in Stage 2.
  - consent_reference: None in Stage 1; consent ledger pointer in Stage 2
    (GDPR Art. 7, CCPA right-to-know).
  - data_classification: highest sensitivity touched (GDPR Art. 30).

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
  is_active()                         -> bool
  active_session()                    -> Optional[SessionRecord]
  active_session_count()              -> int
  reset()                             -> None

SessionRecord attributes (all read/write):
  .identity            .token_prefix       .data_classification
  .created_at          .started_at         (alias for created_at, settable)
  .last_used_at        .last_active        (alias for last_used_at, settable)
  .expires_at                              (computed: created_at + max_duration)
  .max_duration        .idle_timeout       .consent_reference

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

TOKEN_BYTES = 32

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

    Time model:
      created_at + max_duration = expires_at (computed, not stored)
      Winding back started_at (= created_at) winds back expires_at too.
      Winding back last_active (= last_used_at) triggers idle expiry.
      This lets tests simulate time passage by subtraction, no sleep needed.

    Regulatory fields:
      identity          -- who this session belongs to (GDPR Art. 30)
      consent_reference -- which consent record authorizes it (GDPR Art. 7)
      data_classification -- highest sensitivity touched (GDPR Art. 30)
    """
    token_prefix: str
    identity: str
    created_at: float
    last_used_at: float
    idle_timeout: float
    max_duration: float
    connection_fingerprint_hash: Optional[str]
    consent_reference: Optional[str]
    data_classification: str = "UNCLASSIFIED"
    rotated_at: Optional[float] = None

    # ------------------------------------------------------------------
    # COMPUTED EXPIRY
    # ------------------------------------------------------------------

    @property
    def expires_at(self) -> float:
        """Hard expiry: created_at + max_duration. Updates when started_at changes."""
        return self.created_at + self.max_duration

    # ------------------------------------------------------------------
    # READ/WRITE FIELD ALIASES
    # ------------------------------------------------------------------

    @property
    def started_at(self) -> float:
        """Alias for created_at. When the session was established."""
        return self.created_at

    @started_at.setter
    def started_at(self, value: float) -> None:
        """Write-through to created_at. Winding back expires_at automatically."""
        self.created_at = value

    @property
    def last_active(self) -> float:
        """Alias for last_used_at. When the session was last validated."""
        return self.last_used_at

    @last_active.setter
    def last_active(self, value: float) -> None:
        """Write-through to last_used_at. Winding back triggers idle expiry."""
        self.last_used_at = value

    @property
    def token(self) -> str:
        """Stable string handle. Returns token_prefix (safe to log)."""
        return self.token_prefix

    # ------------------------------------------------------------------
    # EXPIRY CHECKS
    # ------------------------------------------------------------------

    def is_idle_expired(self) -> bool:
        return (time.time() - self.last_used_at) > self.idle_timeout

    def is_hard_expired(self) -> bool:
        return time.time() > self.expires_at

    def is_expired(self) -> bool:
        return self.is_idle_expired() or self.is_hard_expired()


class SessionToken(str):
    """
    Bearer token returned after session creation or rotation.

    Inherits from str -- isinstance(token, str) is True, int(token, 16),
    len(token), set/dict membership all work natively.
    The string value IS the raw bearer token.

    Extra attributes: .expires_at, .identity, .token_prefix, .token
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
        return str.__str__(self)

    def __repr__(self) -> str:
        return f"SessionToken(prefix={self.token_prefix!r}, identity={self.identity!r})"


# ---------------------------------------------------------------------------
# SESSION MANAGER
# ---------------------------------------------------------------------------

class SessionManager:
    """
    Thread-safe session manager for ONTO.

    _sessions keyed by raw token string -- allows _sessions[token] directly.
    Audit observers receive (event_type, details) or (event_type,) adaptively.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionRecord] = {}
        self._audit_log: List[dict] = []
        self._audit_fn: Optional[Callable] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # AUDIT
    # ------------------------------------------------------------------

    def set_audit_fn(self, fn: Optional[Callable]) -> None:
        """
        Register an audit observer. Called as fn(event_type, details) or
        fn(event_type) -- both signatures supported. None to deregister.
        """
        with self._lock:
            self._audit_fn = fn

    @staticmethod
    def _call_fn(fn: Callable, event_type: str, details: dict) -> None:
        """Adaptive dispatch: 2-arg then 1-arg fallback. Errors silenced."""
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
        """Append to _audit_log and dispatch to all observers."""
        entry = {"event_type": event_type, "timestamp": time.time(), **details}
        self._audit_log.append(entry)
        if self._audit_fn is not None:
            self._call_fn(self._audit_fn, event_type, details)
        if audit_fn is not None and audit_fn is not self._audit_fn:
            self._call_fn(audit_fn, event_type, details)

    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------

    @staticmethod
    def _prefix(raw_token: str) -> str:
        return hashlib.sha256(str(raw_token).encode()).hexdigest()[:8]

    def _hash_fingerprint(self, fp: Optional[str]) -> Optional[str]:
        return None if fp is None else hashlib.sha256(fp.encode()).hexdigest()

    def _purge_expired(self, audit_fn: Optional[Callable] = None) -> None:
        """Remove expired sessions. GDPR Art. 5(1)(c) data minimization."""
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
        old_raw: str,
        session: SessionRecord,
        audit_fn: Optional[Callable] = None,
    ) -> "SessionToken":
        new_raw = secrets.token_hex(TOKEN_BYTES)
        new_prefix = self._prefix(new_raw)
        old_prefix = session.token_prefix
        del self._sessions[old_raw]
        session.token_prefix = new_prefix
        session.rotated_at = time.time()
        self._sessions[new_raw] = session
        self._dispatch(
            "SESSION_ROTATED",
            {"old_token_prefix": old_prefix, "new_token_prefix": new_prefix,
             "identity": session.identity},
            audit_fn,
        )
        return SessionToken(
            token=new_raw,
            expires_at=session.expires_at,
            identity=session.identity,
            token_prefix=new_prefix,
        )

    # ------------------------------------------------------------------
    # PUBLIC INTERFACE
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
        """Create a new session. Returns SessionToken (is a str)."""
        _idle = idle_timeout if idle_timeout is not None else float(DEFAULT_TTL_SECONDS)
        _max = max_duration if max_duration is not None else float(MAX_LIFETIME_SECONDS)

        with self._lock:
            self._purge_expired(audit_fn)

            if len(self._sessions) >= MAX_CONCURRENT_SESSIONS:
                oldest = min(self._sessions, key=lambda t: self._sessions[t].created_at)
                sup = self._sessions.pop(oldest)
                self._dispatch(
                    "SESSION_SUPERSEDED",
                    {"token_prefix": sup.token_prefix, "identity": sup.identity,
                     "reason": "new_session_created_at_capacity"},
                    audit_fn,
                )

            raw = secrets.token_hex(TOKEN_BYTES)
            prefix = self._prefix(raw)
            now = time.time()

            session = SessionRecord(
                token_prefix=prefix,
                identity=identity,
                created_at=now,
                last_used_at=now,
                idle_timeout=_idle,
                max_duration=_max,
                connection_fingerprint_hash=self._hash_fingerprint(connection_fingerprint),
                consent_reference=consent_reference,
            )
            self._sessions[raw] = session

            self._dispatch(
                "SESSION_START",
                {
                    "token_prefix": prefix,
                    "identity": identity,
                    "expires_at": session.expires_at,
                    "idle_timeout": _idle,
                    "connection_bound": connection_fingerprint is not None,
                    "consent_reference": consent_reference,
                },
                audit_fn,
            )

            return SessionToken(
                token=raw,
                expires_at=session.expires_at,
                identity=identity,
                token_prefix=prefix,
            )

    def validate(
        self,
        token: str,
        connection_fingerprint: Optional[str] = None,
        audit_fn: Optional[Callable] = None,
    ) -> Optional[SessionRecord]:
        """Validate token. Returns SessionRecord if valid, None otherwise."""
        with self._lock:
            self._purge_expired(audit_fn)
            raw = str(token)
            session = self._sessions.get(raw)

            if session is None:
                self._dispatch(
                    "SESSION_INVALID_TOKEN",
                    {"token_prefix": self._prefix(raw), "reason": "token_not_found"},
                    audit_fn,
                )
                return None

            if ENFORCE_CONNECTION_BINDING and session.connection_fingerprint_hash is not None:
                if self._hash_fingerprint(connection_fingerprint) != session.connection_fingerprint_hash:
                    self._dispatch(
                        "SESSION_BINDING_VIOLATION",
                        {"token_prefix": session.token_prefix, "identity": session.identity,
                         "reason": "connection_fingerprint_mismatch"},
                        audit_fn,
                    )
                    del self._sessions[raw]
                    return None

            session.last_used_at = time.time()
            return session

    def rotate(
        self,
        token: str,
        audit_fn: Optional[Callable] = None,
    ) -> Optional["SessionToken"]:
        """Rotate token. Old token immediately invalidated. None if not found."""
        with self._lock:
            self._purge_expired(audit_fn)
            raw = str(token)
            session = self._sessions.get(raw)
            if session is None:
                return None
            return self._do_rotate(raw, session, audit_fn)

    def terminate(
        self,
        token: str,
        audit_fn: Optional[Callable] = None,
    ) -> bool:
        """End a session. Returns True if found and ended, False otherwise."""
        with self._lock:
            raw = str(token)
            session = self._sessions.pop(raw, None)
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
        """True if any non-expired session currently exists."""
        with self._lock:
            return any(not s.is_expired() for s in self._sessions.values())

    def active_session(self) -> Optional[SessionRecord]:
        """Active SessionRecord if one exists, None otherwise."""
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
        """Escalate classification if more sensitive. Never downgrades."""
        order = {"UNCLASSIFIED": 0, "INTERNAL": 1, "CONFIDENTIAL": 2,
                 "RESTRICTED": 3, "SENSITIVE": 4}
        with self._lock:
            raw = str(token)
            session = self._sessions.get(raw)
            if session is None:
                return False
            if order.get(classification, 0) > order.get(session.data_classification, 0):
                old = session.data_classification
                session.data_classification = classification
                self._dispatch(
                    "SESSION_CLASSIFICATION_ESCALATED",
                    {"token_prefix": session.token_prefix, "identity": session.identity,
                     "from": old, "to": classification},
                    audit_fn,
                )
                return True
            return False

    def clear_audit_log(self) -> None:
        with self._lock:
            self._audit_log.clear()

    def reset(self) -> None:
        """Clear all sessions and audit log. For test setUp(). Preserves audit_fn."""
        with self._lock:
            self._sessions.clear()
            self._audit_log.clear()

    # ------------------------------------------------------------------
    # VERBOSE ALIASES
    # ------------------------------------------------------------------

    def create_session(self, **kwargs) -> "SessionToken":
        return self.start(**kwargs)

    def validate_session(self, **kwargs) -> Optional[SessionRecord]:
        return self.validate(**kwargs)

    def end_session(self, **kwargs) -> bool:
        return self.terminate(**kwargs)


# ---------------------------------------------------------------------------
# MODULE-LEVEL SINGLETON
# ---------------------------------------------------------------------------

session_manager = SessionManager()
