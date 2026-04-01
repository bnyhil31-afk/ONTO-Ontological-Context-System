"""
core/session.py

Session management layer for ONTO.
Implements item 2.09 of the pre-launch security checklist.

Design decisions (all from THREAT_MODEL_001, REVIEW_001, and CRE-SPEC-001):

  TOKEN SECURITY
  - Session token is 32 bytes (256-bit) of cryptographic randomness.
  - _sessions is keyed by the raw token string. The raw token is also
    stored in SessionRecord so that active_session().token can be passed
    directly to terminate() without requiring callers to track the token
    variable separately.
  - token_prefix (sha256[:8]) is used in audit records — never the raw token.

  SESSIONRECORD TIME MODEL
  - created_at / started_at: when the session was established.
  - last_used_at / last_active: when the session was last validated.
  - max_duration: hard ceiling stored explicitly so expires_at is computed
    as created_at + max_duration. Winding back started_at therefore winds
    back expires_at, letting tests simulate time passage by arithmetic.

  AUDIT TRAIL — TWO LAYERS
  - memory.record(): writes SESSION_START / SESSION_END events to ONTO's
    permanent SQLite audit trail. This is the primary audit destination,
    readable via memory.read_by_type().
  - self._audit_log: always-on in-memory list for diagnostics and testing
    without database access.
  - set_audit_fn(): optional observer callable, adaptive 1- or 2-arg dispatch.

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

SessionRecord key attributes:
  .token          the raw bearer token (use for terminate())
  .token_prefix   sha256[:8], safe to log
  .identity       who this session belongs to
  .started_at     alias for created_at (settable — winds back expires_at)
  .last_active    alias for last_used_at (settable — triggers idle expiry)
  .expires_at     computed: created_at + max_duration
"""

import hashlib
import os
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

# Memory module — ONTO's permanent SQLite audit trail.
# Imported gracefully so session.py can be tested without a live database.
try:
    from modules import memory as _memory_module
    _MEMORY_AVAILABLE = True
except ImportError:
    _memory_module = None
    _MEMORY_AVAILABLE = False

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
    Internal representation of an active session.

    .token          — raw bearer token. Pass to terminate() directly.
                      Example: sm.terminate(sm.active_session().token)
    .token_prefix   — sha256[:8] of raw token, safe to log.
    .started_at     — settable alias for created_at. Winding back this value
                      also winds back expires_at (= created_at + max_duration).
    .last_active    — settable alias for last_used_at. Winding back triggers
                      idle expiry without sleeping.

    Regulatory fields:
      identity          — GDPR Art. 30 (records of processing)
      consent_reference — GDPR Art. 7 (conditions for consent), Stage 2+
      data_classification — GDPR Art. 30 sensitivity ceiling for this session
    """
    raw_token: str                              # raw bearer token — stored for .token access
    token_prefix: str                           # sha256(raw_token)[:8] — safe to log
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
    # PRIMARY TOKEN ACCESSOR
    # ------------------------------------------------------------------

    @property
    def token(self) -> str:
        """
        The raw bearer token for this session.
        Use this to call terminate() on the result of active_session():
            sm.terminate(sm.active_session().token)
        """
        return self.raw_token

    # ------------------------------------------------------------------
    # COMPUTED EXPIRY
    # ------------------------------------------------------------------

    @property
    def expires_at(self) -> float:
        """Hard expiry: created_at + max_duration. Updates when started_at changes."""
        return self.created_at + self.max_duration

    # ------------------------------------------------------------------
    # READ/WRITE ALIASES
    # ------------------------------------------------------------------

    @property
    def started_at(self) -> float:
        """Alias for created_at. Settable — adjusting this winds back expires_at."""
        return self.created_at

    @started_at.setter
    def started_at(self, value: float) -> None:
        self.created_at = value

    @property
    def last_active(self) -> float:
        """Alias for last_used_at. Settable — adjusting this triggers idle expiry."""
        return self.last_used_at

    @last_active.setter
    def last_active(self, value: float) -> None:
        self.last_used_at = value

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

    Inherits from str — isinstance(token, str) is True, int(token, 16),
    len(token), set/dict membership all work natively.
    The string value IS the raw 64-character hex bearer token.

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

    Audit events are written to two destinations:
      1. ONTO's permanent SQLite audit trail via memory.record()
      2. self._audit_log (in-memory list for diagnostics)
    An optional observer can be registered via set_audit_fn().
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionRecord] = {}
        self._audit_log: List[dict] = []
        self._audit_fn: Optional[Callable] = None
        self._last_token: Optional[str] = None  # raw token of most recent start()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # AUDIT OBSERVER
    # ------------------------------------------------------------------

    def set_audit_fn(self, fn: Optional[Callable]) -> None:
        """
        Register an audit observer. Supported signatures:
          fn(event_type: str, details: dict)
          fn(event_type: str)
        Set to None to deregister.
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
        """
        Record an audit event to all destinations:
          - self._audit_log (always)
          - memory.record() if available (permanent SQLite trail)
          - registered set_audit_fn() observer if set
          - per-call audit_fn if provided
        """
        entry = {"event_type": event_type, "timestamp": time.time(), **details}
        self._audit_log.append(entry)

        # Write to ONTO's permanent SQLite audit trail
        if _MEMORY_AVAILABLE and _memory_module is not None:
            try:
                _memory_module.record(
                    event_type=event_type,
                    human_decision=details.get("identity"),
                    notes=str({k: v for k, v in details.items() if k != "identity"}),
                )
            except Exception:
                pass  # database unavailable — in-memory log is the fallback

        # Registered observer
        if self._audit_fn is not None:
            self._call_fn(self._audit_fn, event_type, details)

        # Per-call observer (only if different)
        if audit_fn is not None and audit_fn is not self._audit_fn:
            self._call_fn(audit_fn, event_type, details)

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _prefix(raw_token: str) -> str:
        """First 8 hex chars of sha256(raw_token). Safe to log."""
        return hashlib.sha256(str(raw_token).encode()).hexdigest()[:8]

    def _hash_fingerprint(self, fp: Optional[str]) -> Optional[str]:
        return None if fp is None else hashlib.sha256(fp.encode()).hexdigest()

    def _purge_expired(self, audit_fn: Optional[Callable] = None) -> None:
        """Remove expired sessions. GDPR Art. 5(1)(c) data minimization."""
        now = time.time()
        expired = [t for t, s in self._sessions.items() if s.is_expired()]
        for raw_token in expired:
            session = self._sessions.pop(raw_token)
            if raw_token == self._last_token:
                self._last_token = None
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
        """Internal rotation — must be called with lock held."""
        new_raw = secrets.token_hex(TOKEN_BYTES)
        new_prefix = self._prefix(new_raw)
        old_prefix = session.token_prefix

        del self._sessions[old_raw]
        session.raw_token = new_raw
        session.token_prefix = new_prefix
        session.rotated_at = time.time()
        self._sessions[new_raw] = session

        if old_raw == self._last_token:
            self._last_token = new_raw

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
        """
        Create a new session. Returns SessionToken (is a str).
        Stage 1: supersedes any existing session (MAX_CONCURRENT_SESSIONS=1).
        """
        _idle = idle_timeout if idle_timeout is not None else float(DEFAULT_TTL_SECONDS)
        _max = max_duration if max_duration is not None else float(MAX_LIFETIME_SECONDS)

        with self._lock:
            self._purge_expired(audit_fn)

            if len(self._sessions) >= MAX_CONCURRENT_SESSIONS:
                oldest = min(self._sessions, key=lambda t: self._sessions[t].created_at)
                sup = self._sessions.pop(oldest)
                if oldest == self._last_token:
                    self._last_token = None
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
                raw_token=raw,
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
            self._last_token = raw

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
        """Validate a token. Returns SessionRecord if valid, None otherwise."""
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
                    if raw == self._last_token:
                        self._last_token = None
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
        """
        End a session. Returns True if found and ended, False otherwise.

        Accepts the raw bearer token OR the value of SessionRecord.token:
            sm.terminate(sm.active_session().token)  # works correctly
        """
        with self._lock:
            raw = str(token)
            session = self._sessions.pop(raw, None)
            if session is None:
                return False
            if raw == self._last_token:
                self._last_token = None
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
        True if the most recently started session is still active.

        Checks only the session created by the last start() call on this
        instance. Provides deterministic single-user semantics and avoids
        false positives from sessions started in other contexts.
        """
        with self._lock:
            if self._last_token is None:
                return False
            session = self._sessions.get(self._last_token)
            return session is not None and not session.is_expired()

    def active_session(self) -> Optional[SessionRecord]:
        """
        Return the active SessionRecord if one exists, None otherwise.

        The returned record's .token gives the raw bearer token:
            sm.terminate(sm.active_session().token)
        """
        with self._lock:
            for s in self._sessions.values():
                if not s.is_expired():
                    return s
            return None

    def active_session_count(self) -> int:
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
            session = self._sessions.get(str(token))
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
        """Clear sessions and audit log. For test setUp(). Preserves audit_fn."""
        with self._lock:
            self._sessions.clear()
            self._audit_log.clear()
            self._last_token = None

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
