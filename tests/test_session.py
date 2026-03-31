"""
tests/test_session.py

Tests for core/session.py — session management.

Covers checklist item 2.09 and threat model T-013
(Session Token Portability).

Rule 1.09A: Code, tests, and documentation must always agree.

Test count: 17
  TestSessionStart        —  4 tests
  TestSessionValidation   —  5 tests
  TestSessionRotation     —  3 tests
  TestSessionTermination  —  3 tests
  TestSessionAuditTrail   —  2 tests
"""

import os
import tempfile
import time
import unittest

from modules import memory
from core.session import SessionManager


# ─────────────────────────────────────────────────────────────────────────────
# SHARED SETUP
# ─────────────────────────────────────────────────────────────────────────────

class _SessionTestBase(unittest.TestCase):
    """Fresh database and fresh SessionManager for every test."""

    def setUp(self):
        self._orig_db = memory.DB_PATH
        fd, self.test_db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.test_db)
        memory.DB_PATH = self.test_db
        memory.initialize()
        # Fresh manager — no shared state between tests
        self.sm = SessionManager()

    def tearDown(self):
        memory.DB_PATH = self._orig_db
        for path in [self.test_db, self.test_db + "-wal", self.test_db + "-shm"]:
            if os.path.exists(path):
                os.remove(path)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION START
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionStart(_SessionTestBase):
    """Starting a session produces a valid, unique, cryptographic token."""

    def test_start_returns_token(self):
        """start() must return a non-empty string token."""
        token = self.sm.start()
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 0)

    def test_token_is_256_bit_hex(self):
        """Token must be a 64-character hex string (256-bit entropy)."""
        token = self.sm.start()
        self.assertEqual(len(token), 64)
        try:
            int(token, 16)
        except ValueError:
            self.fail("Token is not valid hexadecimal.")

    def test_tokens_are_unique(self):
        """Every call to start() must produce a different token."""
        tokens = {self.sm.start() for _ in range(20)}
        self.assertEqual(
            len(tokens), 20,
            "Tokens must be unique. A repeated token is a security failure."
        )

    def test_new_session_terminates_existing(self):
        """
        Stage 1 enforces one session at a time.
        Starting a new session must invalidate the old token.
        """
        token_a = self.sm.start(identity="operator")
        token_b = self.sm.start(identity="operator")
        self.assertIsNone(
            self.sm.validate(token_a),
            "Old token must be invalid after a new session starts."
        )
        self.assertIsNotNone(
            self.sm.validate(token_b),
            "New token must be valid."
        )


# ─────────────────────────────────────────────────────────────────────────────
# SESSION VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionValidation(_SessionTestBase):
    """validate() correctly accepts valid sessions and rejects invalid ones."""

    def test_valid_token_returns_session(self):
        """A freshly started session must validate successfully."""
        token = self.sm.start(identity="operator")
        record = self.sm.validate(token)
        self.assertIsNotNone(record)
        self.assertEqual(record.identity, "operator")

    def test_unknown_token_returns_none(self):
        """A token that was never issued must not validate."""
        result = self.sm.validate("a" * 64)
        self.assertIsNone(result)

    def test_terminated_token_returns_none(self):
        """A token that has been terminated must not validate."""
        token = self.sm.start()
        self.sm.terminate(token)
        self.assertIsNone(self.sm.validate(token))

    def test_idle_timeout_invalidates_session(self):
        """
        A session idle longer than idle_timeout must be rejected.
        T-013: short-lived sessions reduce replay window.
        """
        token = self.sm.start(idle_timeout=1)
        # Simulate idle timeout by backdating last_active
        self.sm._sessions[token].last_active -= 2
        result = self.sm.validate(token)
        self.assertIsNone(
            result,
            "Session must expire after idle timeout is exceeded."
        )

    def test_max_duration_invalidates_session(self):
        """
        A session running longer than max_duration must be rejected,
        regardless of activity.
        """
        token = self.sm.start(idle_timeout=3600, max_duration=1)
        # Simulate max duration exceeded by backdating started_at
        self.sm._sessions[token].started_at -= 2
        result = self.sm.validate(token)
        self.assertIsNone(
            result,
            "Session must expire when max_duration is exceeded."
        )


# ─────────────────────────────────────────────────────────────────────────────
# SESSION ROTATION
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionRotation(_SessionTestBase):
    """
    Token rotation reduces the replay window.
    Old tokens must be immediately invalid after rotation.
    """

    def test_rotate_returns_new_token(self):
        """rotate() must return a new token distinct from the old one."""
        token = self.sm.start()
        new_token = self.sm.rotate(token)
        self.assertIsNotNone(new_token)
        self.assertNotEqual(token, new_token)

    def test_old_token_invalid_after_rotation(self):
        """
        The old token must be immediately invalid after rotation.
        T-013: a stolen token intercepted before rotation cannot
        be replayed after the legitimate session rotates.
        """
        token = self.sm.start()
        self.sm.rotate(token)
        self.assertIsNone(
            self.sm.validate(token),
            "Old token must be invalid after rotation."
        )

    def test_new_token_valid_after_rotation(self):
        """The new token returned by rotate() must be valid."""
        token = self.sm.start()
        new_token = self.sm.rotate(token)
        self.assertIsNotNone(self.sm.validate(new_token))


# ─────────────────────────────────────────────────────────────────────────────
# SESSION TERMINATION
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionTermination(_SessionTestBase):

    def test_terminate_returns_true_for_active_session(self):
        """terminate() must return True when a valid session is ended."""
        token = self.sm.start()
        result = self.sm.terminate(token)
        self.assertTrue(result)

    def test_terminate_returns_false_for_unknown_token(self):
        """terminate() must return False when the token is not recognised."""
        result = self.sm.terminate("b" * 64)
        self.assertFalse(result)

    def test_is_active_false_after_terminate(self):
        """No active session must exist after the only session is terminated."""
        self.sm.start()
        token = self.sm.active_session().token
        self.sm.terminate(token)
        self.assertFalse(self.sm.is_active())


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT TRAIL
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionAuditTrail(_SessionTestBase):
    """Every session lifecycle event must be recorded permanently."""

    def test_session_start_recorded(self):
        """Starting a session must create a SESSION_START record."""
        self.sm.start(identity="operator")
        events = memory.read_by_type("SESSION_START")
        self.assertEqual(len(events), 1)
        self.assertIn("operator", events[0].get("human_decision", ""))

    def test_session_end_recorded(self):
        """Terminating a session must create a SESSION_END record."""
        token = self.sm.start()
        self.sm.terminate(token)
        events = memory.read_by_type("SESSION_END")
        self.assertEqual(len(events), 1)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
