"""
tests/test_memory_chain.py

Tests for memory.py — Merkle chain integrity, read logging, and
signature algorithm field.

Covers REVIEW_001 findings:
  C2 — Merkle chain: every record cryptographically links to the previous.
       Deletion, modification, and insertion gaps are all detectable.
  U3 — Read logging: reads of sensitive records generate READ_ACCESS events.
  U6 — Signature algorithm: every record declares its signing algorithm.

Checklist item: 1.13

Rule 1.09A: Code, tests, and documentation must always agree.

Test count: 19
  TestMerkleChain          — 11 tests
  TestReadLogging          —  6 tests
  TestSignatureAlgorithm   —  2 tests
"""

import json
import os
import sqlite3
import tempfile
import unittest

from modules import memory


# ─────────────────────────────────────────────────────────────────────────────
# SHARED SETUP MIXIN
# ─────────────────────────────────────────────────────────────────────────────

class _MemoryTestBase(unittest.TestCase):
    """Provides a fresh isolated database for every test."""

    def setUp(self):
        self._orig_db = memory.DB_PATH
        fd, self.test_db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.test_db)     # let SQLite create it fresh
        memory.DB_PATH = self.test_db
        memory.initialize()

    def tearDown(self):
        memory.DB_PATH = self._orig_db
        for path in [self.test_db, self.test_db + "-wal", self.test_db + "-shm"]:
            if os.path.exists(path):
                os.remove(path)


# ─────────────────────────────────────────────────────────────────────────────
# C2 — MERKLE CHAIN
# ─────────────────────────────────────────────────────────────────────────────

class TestMerkleChain(_MemoryTestBase):
    """
    The audit trail is a Merkle chain.
    Every record stores a SHA-256 hash of the record before it.
    Deletion, modification, or fabrication of any record breaks the chain.
    The chain cannot lie about what it has seen.
    """

    def test_genesis_record_has_null_chain_hash(self):
        """
        The first record in the chain has no predecessor.
        Its chain_hash must be NULL — not a fabricated value.
        """
        memory.record(event_type="TEST", notes="genesis")
        r = memory.read_all()[0]
        self.assertIsNone(
            r["chain_hash"],
            "Genesis record must have chain_hash=NULL. "
            "There is no previous record to hash."
        )

    def test_second_record_has_chain_hash(self):
        """
        Every record after the first must carry a chain_hash.
        A NULL chain_hash after record 1 means the chain is broken.
        """
        memory.record(event_type="TEST", notes="first")
        memory.record(event_type="TEST", notes="second")
        records = memory.read_all()
        self.assertIsNone(records[0]["chain_hash"])
        self.assertIsNotNone(
            records[1]["chain_hash"],
            "Record 2 must have a chain_hash linking it to record 1."
        )

    def test_chain_hash_is_sha256_hex(self):
        """
        chain_hash must be a 64-character lowercase hex string.
        This is the canonical SHA-256 digest format.
        """
        memory.record(event_type="TEST")
        memory.record(event_type="TEST")
        r = memory.read_all()[1]
        self.assertIsNotNone(r["chain_hash"])
        self.assertEqual(
            len(r["chain_hash"]), 64,
            "SHA-256 hex digest must be exactly 64 characters."
        )
        try:
            int(r["chain_hash"], 16)
        except ValueError:
            self.fail("chain_hash is not valid hexadecimal.")

    def test_chain_hash_links_to_previous_record(self):
        """
        record[N].chain_hash must equal SHA-256(record[N-1]).
        This is the fundamental invariant of the Merkle chain.
        """
        memory.record(event_type="TEST", notes="first")
        memory.record(event_type="TEST", notes="second")
        records = memory.read_all()
        expected = memory._hash_record_content(records[0])
        self.assertEqual(
            records[1]["chain_hash"], expected,
            "chain_hash must be the SHA-256 of the previous record's content."
        )

    def test_chain_grows_correctly_across_many_records(self):
        """
        The chain must link correctly across every record, not just the first two.
        Each record's chain_hash must equal SHA-256 of the one before it.
        """
        for i in range(10):
            memory.record(event_type="TEST", notes=f"record {i}")
        records = memory.read_all()
        for i in range(1, len(records)):
            expected = memory._hash_record_content(records[i - 1])
            self.assertEqual(
                records[i]["chain_hash"], expected,
                f"Chain broken at record {records[i]['id']}. "
                f"Expected {expected[:16]}..., "
                f"stored {str(records[i]['chain_hash'])[:16]}..."
            )

    def test_verify_chain_intact_on_clean_data(self):
        """
        verify_chain() must return intact=True on an unmodified chain.
        If this fails: the verification function itself is broken.
        """
        for i in range(5):
            memory.record(event_type="TEST", notes=f"record {i}")
        result = memory.verify_chain()
        self.assertTrue(result["intact"])
        self.assertEqual(result["total"], 5)
        self.assertEqual(len(result["gaps"]), 0)

    def test_verify_chain_single_record_is_intact(self):
        """
        A single genesis record with no chain_hash is a valid, intact chain.
        """
        memory.record(event_type="TEST")
        result = memory.verify_chain()
        self.assertTrue(result["intact"])
        self.assertEqual(result["total"], 1)

    def test_verify_chain_empty_database_is_intact(self):
        """
        An empty database is trivially intact — nothing to verify.
        """
        result = memory.verify_chain()
        self.assertTrue(result["intact"])
        self.assertEqual(result["total"], 0)
        self.assertIsNone(result["first_record_hash"])

    def test_verify_chain_detects_wrong_chain_hash(self):
        """
        verify_chain() must detect a record with a fabricated chain_hash.
        This simulates an attacker inserting a fake record into the trail.
        The chain breaks — and the system must see it.
        """
        memory.record(event_type="TEST", notes="genesis")
        # Bypass record() and insert a record with a deliberately wrong hash
        conn = sqlite3.connect(self.test_db)
        fake_hash = "a" * 64
        conn.execute(
            "INSERT INTO events (timestamp, event_type, notes, chain_hash) "
            "VALUES ('2026-01-01T00:00:00+00:00', 'FABRICATED', "
            "'tampered record', ?)",
            (fake_hash,)
        )
        conn.commit()
        conn.close()
        result = memory.verify_chain()
        self.assertFalse(
            result["intact"],
            "verify_chain() must detect a wrong chain_hash. "
            "A fabricated record must break the chain."
        )
        self.assertGreater(len(result["gaps"]), 0)

    def test_first_record_hash_is_returned(self):
        """
        verify_chain() returns the SHA-256 of the genesis record.
        This hash can be published as a genesis block anchor.
        """
        memory.record(event_type="TEST", notes="anchor")
        result = memory.verify_chain()
        self.assertIsNotNone(result["first_record_hash"])
        self.assertEqual(len(result["first_record_hash"]), 64)

    def test_hash_is_deterministic(self):
        """
        _hash_record_content() must return the same hash every time
        for the same record. Non-determinism would make verify_chain()
        unreliable.
        """
        memory.record(event_type="TEST", notes="stable content")
        r = memory.read_all()[0]
        h1 = memory._hash_record_content(r)
        h2 = memory._hash_record_content(r)
        self.assertEqual(
            h1, h2,
            "_hash_record_content() must be deterministic. "
            "The same record must always produce the same hash."
        )


# ─────────────────────────────────────────────────────────────────────────────
# U3 — READ LOGGING
# ─────────────────────────────────────────────────────────────────────────────

class TestReadLogging(_MemoryTestBase):
    """
    Reads of sensitive records are as visible as writes.
    Every access to data at or above READ_LOG_THRESHOLD generates
    a READ_ACCESS event in the permanent audit trail.
    """

    def test_read_above_threshold_is_logged(self):
        """
        Reading a record at or above READ_LOG_THRESHOLD must generate
        a READ_ACCESS event.
        """
        record_id = memory.record(event_type="TEST", classification=2)
        log_id = memory.log_read_access(record_id, classification=2)
        self.assertIsNotNone(log_id)
        self.assertIsInstance(log_id, int)
        self.assertGreater(log_id, 0)

    def test_read_below_threshold_is_not_logged(self):
        """
        Reads below READ_LOG_THRESHOLD must not generate events.
        Routine reads of low-sensitivity data should not pollute the trail.
        """
        record_id = memory.record(event_type="TEST", classification=0)
        result = memory.log_read_access(record_id, classification=0)
        self.assertIsNone(
            result,
            "log_read_access() must return None for reads below threshold. "
            "No READ_ACCESS event should be created."
        )

    def test_read_access_event_type_is_correct(self):
        """READ_ACCESS events must use the READ_ACCESS event_type."""
        record_id = memory.record(event_type="TEST", classification=3)
        memory.log_read_access(record_id, classification=3)
        events = memory.read_by_type("READ_ACCESS")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "READ_ACCESS")

    def test_read_access_records_accessor_and_purpose(self):
        """
        The READ_ACCESS event must record who accessed the data
        and why. This is the accountability trail for sensitive reads.
        """
        record_id = memory.record(event_type="TEST", classification=2)
        memory.log_read_access(
            record_id,
            accessor_id="audit_user",
            purpose="compliance_review",
            classification=2
        )
        events = memory.read_by_type("READ_ACCESS")
        notes = json.loads(events[0]["notes"])
        self.assertEqual(notes["accessor_id"], "audit_user")
        self.assertEqual(notes["purpose"], "compliance_review")
        self.assertEqual(notes["accessed_record_id"], record_id)

    def test_read_at_threshold_is_logged(self):
        """The threshold is inclusive — reads at exactly READ_LOG_THRESHOLD are logged."""
        result = memory.log_read_access(
            1, classification=memory.READ_LOG_THRESHOLD
        )
        self.assertIsNotNone(result)

    def test_read_one_below_threshold_is_not_logged(self):
        """One below the threshold must not be logged."""
        result = memory.log_read_access(
            1, classification=memory.READ_LOG_THRESHOLD - 1
        )
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# U6 — SIGNATURE ALGORITHM
# ─────────────────────────────────────────────────────────────────────────────

class TestSignatureAlgorithm(_MemoryTestBase):
    """
    Every record declares which algorithm signed it.
    This enables migration from Ed25519 to ML-DSA (post-quantum)
    without schema changes — the field is already there.
    """

    def test_default_signature_algorithm_is_ed25519(self):
        """
        Records created without specifying an algorithm must default to Ed25519.
        This is Stage 1 — Ed25519 is the current standard.
        """
        memory.record(event_type="TEST")
        r = memory.read_all()[0]
        self.assertEqual(
            r["signature_algorithm"], "Ed25519",
            "Default signature_algorithm must be Ed25519."
        )

    def test_custom_signature_algorithm_is_stored(self):
        """
        A custom algorithm (e.g. ML-DSA-65 for post-quantum) must be stored
        exactly as specified. The field enables forward migration.
        """
        memory.record(event_type="TEST", signature_algorithm="ML-DSA-65")
        r = memory.read_all()[0]
        self.assertEqual(
            r["signature_algorithm"], "ML-DSA-65",
            "Custom signature_algorithm must be stored and returned unchanged."
        )


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
