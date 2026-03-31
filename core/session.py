"""
core/session.py

Session management for ONTO.
Implements item 2.09 of the pre-launch security checklist.

Addresses threat model T-013 (Session Token Portability):
  - Tokens are 256-bit cryptographically random — not guessable
  - Short-lived: idle timeout + maximum duration enforced
  - One active session at a time (Stage 1 is single-user)
  - Every session event recorded in the permanent audit trail
  - Tokens live in memory only — never written to disk

Design decisions:
  - Sessions are in-memory for Stage 1 (local, single-user)
  - Token rotation on sensitive operations reduces replay window
  - Audit trail records start, rotation, expiry, and termination
  - Swap interface: same contract as auth — replace without touching
    anything else in the system

Stage 1 (now):   In-memory, single session, local only
Stage 2 (future): Multi-session, network-bound tokens, SSO integration

Usage:
    from core.session import session_manager
    token = session_manager.start(identity="operator")
    record = session_manager.validate(token)
    if record:
        new_token = session_manager.rotate(token)
    session_manager.terminate(token)
"""

import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from modules import memory

# ─────────────────────────────────────────────────────────────────────────────
# DEFAULTS — overridden by core/config.py if available
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_IDLE_TIMEOUT = 1800       # 30 minutes idle
_DEFAULT_MAX_DURATION = 28800      # 8 hours absolute maximum
_TOKEN_BYTES = 32                  # 256-bit token


# ─────────────────────────────────────────────────────────────────────────────
# SESSION RECORD
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionRecord:
    """
    Represents a single active session.

    token:            256-bit hex token — the session's identity
    identity:         Who this session belongs to (from auth)
    started_at:       Monotonic clock at session start
    last_active:      Monotonic clock at last validated use
    idle_timeout:     Seconds of inactivity before expiry
    max_duration:     Maximum session lifetime in seconds (hard cap)
    terminated:       True if explicitly terminated
    record_id:        Audit trail ID of the SESSION_START event
    """
    token: str
    identity: str
    started_at: float
    last_active: float
    idle_timeout: int
    max_duration: int
    terminated: bool = False
    record_id: int = 0
    rotation_count: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# SESSION MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class SessionManager:
    """
    Manages active sessions for ONTO.

    Stage 1 design: single-user, in-memory, local only.
    Starting a new session terminates any existing active session.
    This enforces the single-session invariant without raising errors.

    The swap interface contract:
        start(identity)  → token
        validate(token)  → Optional[SessionRecord]
        rotate(token)    → new_token
        terminate(token) → None

    Any module satisfying this contract is a valid session module.
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionRecord] = {}

    # ── PUBLIC INTERFACE ─────────────────────────────────────────────────────

    def start(
        self,
        identity: str = "operator",
        idle_timeout: Optional[int] = None,
        max_duration: Optional[int] = None,
    ) -> str:
        """
        Starts a new session for the given identity.

        Stage 1: terminates any existing active session before starting
        a new one. One session at a time.

        Args:
            identity:     Who this session belongs to
            idle_timeout: Override idle timeout (seconds)
            max_duration: Override maximum duration (seconds)

        Returns:
            str: The session token (256-bit hex)
        """
        # Load config values — fall back to defaults if unavailable
        timeout, max_dur = self._load_timeouts(idle_timeout, max_duration)

        # Stage 1: one session at a time — terminate any active session
        self._terminate_all_silent()

        # Generate token
        token = secrets.token_hex(_TOKEN_BYTES)
        now = time.monotonic()

        session = SessionRecord(
            token=token,
            identity=identity,
            started_at=now,
            last_active=now,
            idle_timeout=timeout,
            max_duration=max_dur,
        )

        # Record before storing — fail safe
        record_id = memory.record(
            event_type="SESSION_START",
            human_decision=identity,
            notes=f"Session started. Idle timeout: {timeout}s. "
                  f"Max duration: {max_dur}s.",
        )
        session.record_id = record_id
        self._sessions[token] = session

        return token

    def validate(self, token: str) -> Optional[SessionRecord]:
        """
        Validates a session token.

        Checks:
          - Token exists
          - Session not terminated
          - Idle timeout not exceeded
          - Maximum duration not exceeded

        On success: updates last_active timestamp.
        On failure: terminates the session and records the reason.

        Args:
            token: The session token to validate

        Returns:
            SessionRecord if valid, None otherwise
        """
        # Clean up expired sessions before validating
        self._cleanup_expired()

        session = self._sessions.get(token)
        if session is None:
            return None

        if session.terminated:
            return None

        now = time.monotonic()

        # Check idle timeout
        if (now - session.last_active) > session.idle_timeout:
            self._expire(token, reason="idle_timeout")
            return None

        # Check maximum duration
        if (now - session.started_at) > session.max_duration:
            self._expire(token, reason="max_duration")
            return None

        # Valid — update last active
        session.last_active = now
        return session

    def rotate(self, token: str) -> Optional[str]:
        """
        Rotates the session token.

        The old token is immediately invalidated.
        A new token is issued for the same session.
        This reduces the replay window for intercepted tokens (T-013).

        Args:
            token: Current valid session token

        Returns:
            New token string, or None if the session is invalid
        """
        session = self.validate(token)
        if session is None:
            return None

        # Issue new token
        new_token = secrets.token_hex(_TOKEN_BYTES)
        now = time.monotonic()

        new_session = SessionRecord(
            token=new_token,
            identity=session.identity,
            started_at=session.started_at,    # preserve original start time
            last_active=now,
            idle_timeout=session.idle_timeout,
            max_duration=session.max_duration,
            record_id=session.record_id,
            rotation_count=session.rotation_count + 1,
        )

        # Remove old, add new
        del self._sessions[token]
        self._sessions[new_token] = new_session

        memory.record(
            event_type="SESSION_ROTATE",
            human_decision=session.identity,
            notes=f"Token rotated. Rotation #{new_session.rotation_count}. "
                  f"Old token invalidated.",
        )

        return new_token

    def terminate(self, token: str) -> bool:
        """
        Explicitly terminates a session.

        The token is immediately invalidated.
        The termination is recorded in the audit trail.

        Args:
            token: Session token to terminate

        Returns:
            True if the session existed and was terminated, False otherwise
        """
        session = self._sessions.get(token)
        if session is None or session.terminated:
            return False

        session.terminated = True
        duration = round(time.monotonic() - session.started_at, 1)

        memory.record(
            event_type="SESSION_END",
            human_decision=session.identity,
            notes=f"Session terminated by operator. "
                  f"Duration: {duration}s. "
                  f"Rotations: {session.rotation_count}.",
        )

        del self._sessions[token]
        return True

    def active_session(self) -> Optional[SessionRecord]:
        """
        Returns the current active session, or None if no valid session exists.
        Validates and updates last_active on the returned session.
        """
        for token in list(self._sessions.keys()):
            session = self.validate(token)
            if session is not None:
                return session
        return None

    def is_active(self) -> bool:
        """True if there is a currently valid active session."""
        return self.active_session() is not None

    # ── INTERNAL ─────────────────────────────────────────────────────────────

    def _expire(self, token: str, reason: str) -> None:
        """Marks a session as expired and records it."""
        session = self._sessions.get(token)
        if session is None:
            return

        session.terminated = True
        duration = round(time.monotonic() - session.started_at, 1)

        memory.record(
            event_type="SESSION_EXPIRED",
            human_decision=session.identity,
            notes=f"Session expired: {reason}. Duration: {duration}s.",
        )

        del self._sessions[token]

    def _terminate_all_silent(self) -> int:
        """
        Terminates all active sessions without raising errors.
        Used internally before starting a new session (Stage 1 invariant).
        Returns the count of sessions terminated.
        """
        count = 0
        for token in list(self._sessions.keys()):
            session = self._sessions.get(token)
            if session and not session.terminated:
                session.terminated = True
                duration = round(time.monotonic() - session.started_at, 1)
                memory.record(
                    event_type="SESSION_END",
                    human_decision=session.identity,
                    notes=f"Session terminated — new session started. "
                          f"Duration: {duration}s.",
                )
                count += 1
        self._sessions.clear()
        return count

    def _cleanup_expired(self) -> None:
        """Removes sessions that have exceeded their timeouts."""
        now = time.monotonic()
        to_expire = []

        for token, session in self._sessions.items():
            if session.terminated:
                to_expire.append((token, "terminated"))
            elif (now - session.last_active) > session.idle_timeout:
                to_expire.append((token, "idle_timeout"))
            elif (now - session.started_at) > session.max_duration:
                to_expire.append((token, "max_duration"))

        for token, reason in to_expire:
            if reason == "terminated":
                del self._sessions[token]
            else:
                self._expire(token, reason)

    def _load_timeouts(
        self,
        idle_override: Optional[int],
        max_override: Optional[int],
    ) -> tuple:
        """Loads timeout values from config, falling back to defaults."""
        try:
            from core.config import config
            idle = idle_override or config.SESSION_IDLE_TIMEOUT_SECONDS
            max_dur = max_override or config.SESSION_MAX_DURATION_SECONDS
        except (ImportError, AttributeError):
            idle = idle_override or _DEFAULT_IDLE_TIMEOUT
            max_dur = max_override or _DEFAULT_MAX_DURATION
        return idle, max_dur


# ─────────────────────────────────────────────────────────────────────────────
# SHARED INSTANCE
# ─────────────────────────────────────────────────────────────────────────────

# Single shared instance — import this everywhere
session_manager = SessionManager()
