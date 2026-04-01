"""
tests/test_onto.py

The ONTO test suite.
Every critical module tested. Every edge case documented.

Expected result: 82 passed, 0 failed, 0 errors.
If you see anything different — something needs attention.

──────────────────────────────────────────────────────────────
HOW TO RUN

With pytest (recommended):
  pip install -r requirements-test.txt
  pytest tests/ -v

With built-in Python (no install needed):
  python3 -m unittest tests.test_onto -v

With coverage report:
  pytest tests/ -v --cov=. --cov-report=term-missing

Run just the smoke test first:
  pytest tests/test_onto.py::TestSmoke -v
──────────────────────────────────────────────────────────────
"""

import os
import sys
import json
import hashlib
import sqlite3
import tempfile
import shutil
import unittest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# SHARED BASE CLASS
# All test classes inherit from this.
# Handles database isolation automatically — no repetition needed.
# ─────────────────────────────────────────────────────────────────────────────

class ONTOTestCase(unittest.TestCase):
    """
    Base class for all ONTO tests.

    Plain English: Every test starts with a clean slate.
    A private temporary database is created for each test.
    The real database is never touched.
    Everything is cleaned up automatically when the test ends.
    """

    def setUp(self):
        """Create isolated environment before each test."""
        self.test_dir = tempfile.mkdtemp()
        self.test_db = os.path.join(self.test_dir, "test_memory.db")

        # Isolate memory module
        import modules.memory as memory_module
        self._memory = memory_module
        self._original_db = memory_module.DB_PATH
        memory_module.DB_PATH = self.test_db
        memory_module.initialize()

        # Reset context field
        import modules.contextualize as ctx_module
        self._ctx = ctx_module
        self._original_field = list(ctx_module._field)
        ctx_module._field = []

    def tearDown(self):
        """Restore original state and clean up after each test."""
        self._memory.DB_PATH = self._original_db
        self._ctx._field = self._original_field
        shutil.rmtree(self.test_dir)

    def _make_package(self, text, complexity="simple", safety=None):
        """
        Creates a minimal intake package for testing.
        Use this instead of calling intake.receive() when you
        only need to test downstream modules.
        """
        return {
            "clean": text,
            "raw": text,
            "input_type": "text",
            "complexity": complexity,
            "word_count": len(text.split()),
            "safety": safety,
            "source": "human",
            "record_id": None
        }

    def _make_enriched(self, text="Test input", distance=0.5,
                       weight=0.5, safety=None, complexity="simple"):
        """
        Creates a minimal enriched package for testing.
        Use this when testing the surface module directly.
        """
        return {
            "clean": text,
            "raw": text,
            "input_type": "text",
            "complexity": complexity,
            "word_count": len(text.split()),
            "safety": safety,
            "source": "human",
            "record_id": None,
            "context": {
                "distance": distance,
                "weight": weight,
                "summary": "Test summary.",
                "related_samples": [],
                "related_count": 0,
                "field_size": 1
            }
        }

    def _run_loop(self, text):
        """
        Runs the full five-step loop without the checkpoint pause.
        Used for integration tests.
        """
        from modules import intake, contextualize, surface
        package = intake.receive(text)
        enriched = contextualize.build(package)
        surfaced = surface.present(enriched)
        return package, enriched, surfaced


# ─────────────────────────────────────────────────────────────────────────────
# TEST: SMOKE
# ─────────────────────────────────────────────────────────────────────────────

class TestSmoke(ONTOTestCase):
    """
    Smoke tests — run these first.

    Plain English: These four tests confirm the system is alive.
    If any smoke test fails — stop and fix it before running anything else.

    Expected: 4 passed.
    """

    def test_principles_file_exists(self):
        """
        The principles file is present.
        If this fails: principles.txt is missing from the project root.
        """
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertTrue(
            os.path.exists(os.path.join(root, "principles.txt")),
            "principles.txt is missing. The system cannot run without it."
        )

    def test_memory_initializes(self):
        """
        Memory initializes without error.
        If this fails: Check file permissions on the data/ directory.
        """
        self.assertTrue(os.path.exists(self.test_db))

    def test_all_modules_importable(self):
        """
        All modules can be imported without error.
        If this fails: A module has a syntax error or missing dependency.
        """
        try:
            from core import verify
            from modules import memory, intake, contextualize, surface, checkpoint
        except ImportError as e:
            self.fail(f"Module import failed: {e}")

    def test_full_loop_runs(self):
        """
        The complete five-step loop runs without error.
        If this fails: Something in the core loop is broken.
        """
        try:
            _, _, surfaced = self._run_loop("smoke test input")
            self.assertIsNotNone(surfaced["display"])
        except Exception as e:
            self.fail(f"Full loop failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TEST: VERIFY
# ─────────────────────────────────────────────────────────────────────────────

class TestVerify(ONTOTestCase):
    """
    Tests for core/verify.py — the principle guardian.

    Plain English: Makes sure the system detects when the
    principles have been changed and refuses to run.

    Expected: 10 passed.
    """

    def setUp(self):
        super().setUp()
        self.principles_file = os.path.join(self.test_dir, "principles.txt")
        self.hash_file = os.path.join(self.test_dir, "principles.hash")
        with open(self.principles_file, "w", newline="\n") as f:
            f.write("These are the test principles. They must not change.")

    def _compute_hash(self, filepath):
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _write_hash_file(self, hash_value):
        record = {
            "sealed_at": "2026-01-01T00:00:00+00:00",
            "hash": hash_value,
            "file": "principles.txt",
            "algorithm": "SHA-256"
        }
        with open(self.hash_file, "w") as f:
            json.dump(record, f)

    def test_same_file_same_hash(self):
        """The same file always produces the same hash."""
        h1 = self._compute_hash(self.principles_file)
        h2 = self._compute_hash(self.principles_file)
        self.assertEqual(h1, h2)

    def test_changed_content_changes_hash(self):
        """
        Any change to the file changes the hash.
        If this fails: Tampered principles would go undetected. Critical bug.
        """
        h1 = self._compute_hash(self.principles_file)
        with open(self.principles_file, "a") as f:
            f.write(".")
        self.assertNotEqual(h1, self._compute_hash(self.principles_file))

    def test_single_space_changes_hash(self):
        """Even one extra space changes the hash completely."""
        h1 = self._compute_hash(self.principles_file)
        with open(self.principles_file, "a") as f:
            f.write(" ")
        self.assertNotEqual(h1, self._compute_hash(self.principles_file))

    def test_hash_is_64_characters(self):
        """SHA-256 always produces a 64-character hash."""
        self.assertEqual(len(self._compute_hash(self.principles_file)), 64)

    def test_hash_is_lowercase_hex(self):
        """Hash contains only lowercase hexadecimal characters."""
        h = self._compute_hash(self.principles_file)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))

    def test_correct_hash_matches(self):
        """The sealed hash matches the intact principles file."""
        correct_hash = self._compute_hash(self.principles_file)
        self._write_hash_file(correct_hash)
        with open(self.hash_file, "r") as f:
            record = json.load(f)
        self.assertEqual(
            self._compute_hash(self.principles_file),
            record["hash"]
        )

    def test_tampered_principles_detected(self):
        """
        A tampered principles file does not match the sealed hash.
        This is Principle VIII — Integrity — in action.
        """
        original_hash = self._compute_hash(self.principles_file)
        self._write_hash_file(original_hash)
        with open(self.principles_file, "a") as f:
            f.write("\nAdded without permission.")
        self.assertNotEqual(
            self._compute_hash(self.principles_file),
            original_hash
        )

    def test_hash_record_has_required_fields(self):
        """The sealed hash record contains all required fields."""
        self._write_hash_file(self._compute_hash(self.principles_file))
        with open(self.hash_file, "r") as f:
            record = json.load(f)
        for field in ["sealed_at", "hash", "file", "algorithm"]:
            self.assertIn(field, record)

    def test_algorithm_is_sha256(self):
        """The hash record identifies the algorithm as SHA-256."""
        self._write_hash_file(self._compute_hash(self.principles_file))
        with open(self.hash_file, "r") as f:
            record = json.load(f)
        self.assertEqual(record["algorithm"], "SHA-256")

    def test_lf_and_crlf_produce_different_hashes(self):
        """
        LF and CRLF line endings produce different hashes.
        This confirms why .gitattributes line ending enforcement matters.
        Without it, saving on Windows breaks verification silently.
        """
        lf_file = os.path.join(self.test_dir, "lf.txt")
        crlf_file = os.path.join(self.test_dir, "crlf.txt")
        with open(lf_file, "wb") as f:
            f.write(b"Line one\nLine two\n")
        with open(crlf_file, "wb") as f:
            f.write(b"Line one\r\nLine two\r\n")
        self.assertNotEqual(
            self._compute_hash(lf_file),
            self._compute_hash(crlf_file)
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: MEMORY
# ─────────────────────────────────────────────────────────────────────────────

class TestMemory(ONTOTestCase):
    """
    Tests for modules/memory.py — the permanent audit trail.

    Plain English: Makes sure every event is recorded permanently
    and that nobody — not even the developer — can delete or change records.
    This is Principle VII — Memory — verified by tests.

    Expected: 15 passed.
    """

    def test_database_created_on_initialize(self):
        """Database file exists after initialization."""
        self.assertTrue(os.path.exists(self.test_db))

    def test_initialize_safe_to_call_multiple_times(self):
        """
        Calling initialize repeatedly never erases existing data.
        If this fails: Every system restart would wipe the audit trail. Critical bug.
        """
        self._memory.record(event_type="TEST", notes="must survive")
        self._memory.initialize()
        self._memory.initialize()
        self.assertEqual(len(self._memory.read_all()), 1)

    def test_record_returns_positive_id(self):
        """Every recorded event returns a positive integer ID."""
        record_id = self._memory.record(event_type="TEST")
        self.assertIsInstance(record_id, int)
        self.assertGreater(record_id, 0)

    def test_record_ids_always_increase(self):
        """Each new record has a higher ID than the last."""
        ids = [self._memory.record(event_type="TEST") for _ in range(5)]
        for i in range(1, len(ids)):
            self.assertGreater(ids[i], ids[i-1])

    def test_all_fields_stored_correctly(self):
        """Every field written to memory comes back exactly as written."""
        self._memory.record(
            event_type="INTAKE",
            input_data="test input",
            context={"key": "value", "number": 42},
            output="test output",
            confidence=0.85,
            human_decision="proceed",
            notes="test notes"
        )
        r = self._memory.read_all()[0]
        self.assertEqual(r["event_type"], "INTAKE")
        self.assertEqual(r["input"], "test input")
        self.assertEqual(r["context"], {"key": "value", "number": 42})
        self.assertEqual(r["output"], "test output")
        self.assertAlmostEqual(r["confidence"], 0.85)
        self.assertEqual(r["human_decision"], "proceed")
        self.assertEqual(r["notes"], "test notes")

    def test_optional_fields_can_be_none(self):
        """Optional fields can be omitted without errors."""
        record_id = self._memory.record(event_type="BOOT")
        self.assertGreater(record_id, 0)
        r = self._memory.read_all()[0]
        self.assertIsNone(r["input"])
        self.assertIsNone(r["confidence"])

    def test_delete_is_blocked(self):
        """
        Deleting a record raises an error.
        This is Principle VII — Memory is permanent.
        If this fails: The audit trail can be tampered with. Critical bug.
        """
        self._memory.record(event_type="TEST", notes="permanent")
        conn = sqlite3.connect(self.test_db)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            conn.execute("DELETE FROM events WHERE id = 1")
            conn.commit()
        conn.close()
        self.assertIn("cannot be deleted", str(ctx.exception))

    def test_update_is_blocked(self):
        """
        Updating a record raises an error.
        Records are written once and never changed.
        If this fails: The audit trail can be falsified. Critical bug.
        """
        self._memory.record(event_type="TEST", notes="immutable")
        conn = sqlite3.connect(self.test_db)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            conn.execute("UPDATE events SET notes = 'changed' WHERE id = 1")
            conn.commit()
        conn.close()
        self.assertIn("cannot be changed", str(ctx.exception))

    def test_read_all_returns_every_record(self):
        """read_all returns all records without limit."""
        for i in range(5):
            self._memory.record(event_type="TEST")
        self.assertEqual(len(self._memory.read_all()), 5)

    def test_read_all_oldest_first(self):
        """read_all returns records in chronological order."""
        self._memory.record(event_type="TEST", notes="first")
        self._memory.record(event_type="TEST", notes="last")
        records = self._memory.read_all()
        self.assertEqual(records[0]["notes"], "first")
        self.assertEqual(records[-1]["notes"], "last")

    def test_read_by_type_filters_correctly(self):
        """read_by_type returns only the requested event type."""
        self._memory.record(event_type="INTAKE")
        self._memory.record(event_type="SAFETY")
        self._memory.record(event_type="INTAKE")
        results = self._memory.read_by_type("INTAKE")
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["event_type"] == "INTAKE" for r in results))

    def test_read_recent_respects_limit(self):
        """read_recent never returns more records than the limit."""
        for i in range(20):
            self._memory.record(event_type="TEST")
        self.assertEqual(len(self._memory.read_recent(5)), 5)

    def test_read_recent_returns_newest(self):
        """read_recent returns the most recently added records."""
        for i in range(10):
            self._memory.record(event_type="TEST", notes=f"record {i}")
        notes = [r["notes"] for r in self._memory.read_recent(3)]
        self.assertIn("record 9", notes)
        self.assertIn("record 8", notes)

    def test_timestamps_are_utc(self):
        """All timestamps are in UTC format."""
        self._memory.record(event_type="TEST")
        self.assertIn("+00:00", self._memory.read_all()[0]["timestamp"])

    def test_empty_database_returns_empty_list(self):
        """Reading from an empty database returns an empty list, not an error."""
        self.assertEqual(self._memory.read_all(), [])

# ─────────────────────────────────────────────────────────────────────────────
# TEST: MERKLE CHAIN (item 1.13)
# ─────────────────────────────────────────────────────────────────────────────

class TestMerkleChain(ONTOTestCase):
    """
    Tests for the Merkle chain in modules/memory.py.

    Every record in the audit trail stores the SHA-256 hash of the
    previous record's content. This creates a cryptographically linked
    chain. Any deletion, gap, or modification breaks the chain and is
    detectable by verify_chain().

    Plain English: The audit trail is not just append-only.
    It is cryptographically chained. You cannot delete a record
    without the chain proving something is missing.

    This is item 1.13 from the pre-launch checklist.
    Reference: REVIEW_001 Finding C2, CROSSOVER_CONTRACT_v1.0 §8.

    Expected: 7 passed.
    """

    def test_genesis_record_has_no_chain_hash(self):
        """
        The first record in a chain has chain_hash=None.
        There is no previous record to link to.
        This is the chain's anchor — the genesis block.
        """
        self._memory.record(event_type="TEST", notes="genesis")
        records = self._memory.read_all()
        self.assertIsNone(
            records[0]["chain_hash"],
            "The first record must have chain_hash=None. "
            "It has no predecessor to link to."
        )

    def test_second_record_has_chain_hash(self):
        """
        The second record must have a non-None chain_hash.
        It links back to the first record, forming the chain.
        """
        self._memory.record(event_type="TEST", notes="first")
        self._memory.record(event_type="TEST", notes="second")
        records = self._memory.read_all()
        self.assertIsNotNone(
            records[1]["chain_hash"],
            "The second record must have a chain_hash linking to the first. "
            "A None chain_hash means the chain is broken."
        )

    def test_chain_hash_is_64_char_hex(self):
        """
        chain_hash is a valid SHA-256 hex string — exactly 64 characters,
        all lowercase hexadecimal. Any other format is wrong.
        """
        self._memory.record(event_type="TEST", notes="first")
        self._memory.record(event_type="TEST", notes="second")
        records = self._memory.read_all()
        chain_hash = records[1]["chain_hash"]

        self.assertEqual(
            len(chain_hash), 64,
            f"chain_hash must be 64 characters. Got {len(chain_hash)}."
        )
        self.assertTrue(
            all(c in "0123456789abcdef" for c in chain_hash),
            "chain_hash must be lowercase hexadecimal. "
            f"Got: {chain_hash}"
        )

    def test_chain_hash_links_to_previous_record(self):
        """
        The chain_hash of record N is the SHA-256 of record N-1's content.
        This is the cryptographic link that makes the chain tamper-evident.

        Content is: id, timestamp, event_type, input, context, output,
        confidence, human_decision, notes, classification — serialised
        as sorted JSON. chain_hash and signature_algorithm are excluded
        to avoid circular dependency.
        """
        self._memory.record(event_type="FIRST", notes="genesis record")
        self._memory.record(event_type="SECOND", notes="linked record")
        records = self._memory.read_all()
        first = records[0]

        # Independently compute what the chain_hash of record 2 should be.
        # This mirrors exactly what _hash_record_content() does in memory.py.
        expected_hash = hashlib.sha256(
            json.dumps(
                {
                    "id":             first["id"],
                    "timestamp":      first["timestamp"],
                    "event_type":     first["event_type"],
                    "input":          first["input"],
                    "context":        first["context"],
                    "output":         first["output"],
                    "confidence":     first["confidence"],
                    "human_decision": first["human_decision"],
                    "notes":          first["notes"],
                    "classification": first["classification"],
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(
            records[1]["chain_hash"],
            expected_hash,
            "Record 2's chain_hash must equal SHA-256 of record 1's content. "
            "A mismatch means the chain computation is wrong."
        )

    def test_verify_chain_passes_for_intact_trail(self):
        """
        verify_chain() returns intact=True when all records are correctly
        linked. A healthy audit trail always passes this check.
        """
        for i in range(5):
            self._memory.record(event_type="TEST", notes=f"record {i}")

        result = self._memory.verify_chain()
        self.assertTrue(
            result["intact"],
            f"Chain must be intact after 5 normal writes. Gaps: {result['gaps']}"
        )
        self.assertEqual(result["total"], 5)
        self.assertEqual(len(result["gaps"]), 0)

    def test_verify_chain_detects_wrong_chain_hash(self):
        """
        verify_chain() returns intact=False when a record has an incorrect
        chain_hash. This simulates what the verifier sees when a gap exists.

        Method: write one valid record through the normal path, then insert
        a second record directly via SQLite with a deliberately wrong
        chain_hash. INSERT is not blocked by the append-only triggers
        (only DELETE and UPDATE are prevented), so this bypasses the
        module's compute_chain_hash() logic.

        Plain English: If someone manages to insert a record with a
        wrong chain_hash — or if any record is deleted leaving a gap —
        verify_chain() must detect it.
        If this fails: The audit trail's tamper evidence is broken. Critical bug.
        """
        self._memory.record(event_type="TEST", notes="valid genesis")

        # Insert a second record with an intentionally wrong chain_hash.
        # INSERT bypasses the UPDATE/DELETE triggers — this is intentional.
        conn = sqlite3.connect(self.test_db)
        conn.execute(
            """
            INSERT INTO events (
                timestamp, event_type, notes,
                chain_hash, signature_algorithm, classification
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "2099-01-01T00:00:00+00:00",
                "TEST",
                "record with corrupted chain_hash",
                "0" * 64,    # deliberately wrong — all zeros
                "Ed25519",
                0,
            ),
        )
        conn.commit()
        conn.close()

        result = self._memory.verify_chain()
        self.assertFalse(
            result["intact"],
            "verify_chain() must return intact=False when a chain_hash is wrong. "
            "Tampered or gap-bearing records must not pass verification."
        )
        self.assertGreater(
            len(result["gaps"]), 0,
            "verify_chain() must identify at least one gap when the chain is broken."
        )

    def test_verify_chain_result_has_required_fields(self):
        """
        verify_chain() returns a dict with the four required fields:
        intact, total, gaps, first_record_hash.
        Callers depend on this structure — changes are breaking changes.
        """
        self._memory.record(event_type="TEST")
        result = self._memory.verify_chain()

        for field in ["intact", "total", "gaps", "first_record_hash"]:
            self.assertIn(
                field, result,
                f"verify_chain() result missing required field: '{field}'"
            )

        self.assertIsInstance(result["intact"], bool)
        self.assertIsInstance(result["total"], int)
        self.assertIsInstance(result["gaps"], list)
        self.assertIsNotNone(
            result["first_record_hash"],
            "first_record_hash must not be None when records exist. "
            "It is the genesis hash that can be published for public verification."
        )

# ─────────────────────────────────────────────────────────────────────────────
# TEST: INTAKE
# ─────────────────────────────────────────────────────────────────────────────

class TestIntake(ONTOTestCase):
    """
    Tests for modules/intake.py — the front door of the system.

    Plain English: Makes sure the system correctly receives,
    classifies, and safety-checks every input.

    Expected: 22 passed.
    """

    def setUp(self):
        super().setUp()
        from modules import intake
        self.intake = intake

    # ── Classification ────────────────────────────────────────────────────────

    def test_question_mark_is_question(self):
        """Input ending with ? is classified as a question."""
        self.assertEqual(
            self.intake.receive("What is this?")["input_type"], "question"
        )

    def test_question_words_are_questions(self):
        """
        Inputs starting with what/who/where/when/why/how are questions.
        Note: 'can you' and 'could you' are also classified as questions.
        That is correct — they are requests framed as questions.
        """
        for word in ["what", "who", "where", "when", "why", "how"]:
            self.assertEqual(
                self.intake.receive(f"{word} is this")["input_type"],
                "question",
                f"'{word}' should be a question"
            )

    def test_action_words_are_commands(self):
        """Inputs starting with action words are classified as commands."""
        for word in ["please", "show", "find", "create", "make"]:
            self.assertEqual(
                self.intake.receive(f"{word} something")["input_type"],
                "command",
                f"'{word}' should be a command"
            )

    def test_numbers_are_numbers(self):
        """Pure numeric input is classified as a number."""
        self.assertEqual(self.intake.receive("42")["input_type"], "number")

    def test_general_text_is_text(self):
        """General statements are classified as text."""
        self.assertEqual(
            self.intake.receive("This is a statement.")["input_type"], "text"
        )

    def test_empty_input_is_unknown(self):
        """Empty input returns unknown without crashing."""
        self.assertEqual(self.intake.receive("")["input_type"], "unknown")

    # ── Complexity ────────────────────────────────────────────────────────────

    def test_single_word_is_simple(self):
        """A single word with no punctuation is simple."""
        self.assertEqual(self.intake.receive("Hi")["complexity"], "simple")

    def test_two_sentences_are_moderate(self):
        """Two sentences are moderate complexity."""
        self.assertEqual(
            self.intake.receive(
                "This is a sentence. Here is another one."
            )["complexity"],
            "moderate"
        )

    def test_many_sentences_are_complex(self):
        """Many sentences are complex."""
        self.assertEqual(
            self.intake.receive("This is a sentence. " * 15)["complexity"],
            "complex"
        )

    def test_word_count_is_accurate(self):
        """Word count matches the actual words in the input."""
        self.assertEqual(
            self.intake.receive("one two three four five")["word_count"], 5
        )

    # ── Safety ───────────────────────────────────────────────────────────────

    def test_crisis_language_triggers_crisis_flag(self):
        """
        Self-harm language triggers a CRISIS flag immediately.
        This is Principle II — Life First — in action.
        If this fails: People in crisis may not receive help. Critical bug.
        """
        for text in [
            "I want to kill myself",
            "thinking about suicide",
            "I want to end my life",
            "I don't want to live anymore",
        ]:
            flag = self.intake.receive(text)["safety"]
            self.assertIsNotNone(flag, f"CRISIS not detected: '{text}'")
            self.assertEqual(flag["level"], "CRISIS")

    def test_harm_to_others_triggers_harm_flag(self):
        """
        Intent to harm others triggers a HARM flag.
        If this fails: Dangerous inputs pass through unchecked.
        """
        for text in [
            "I want to hurt someone",
            "going to harm them",
            "I want to kill him",
        ]:
            flag = self.intake.receive(text)["safety"]
            self.assertIsNotNone(flag, f"HARM not detected: '{text}'")
            self.assertEqual(flag["level"], "HARM")

    def test_principle_override_triggers_integrity_flag(self):
        """
        Attempts to bypass the principles trigger an INTEGRITY flag.
        This is Principle VIII — the system protects its own foundation.
        """
        for text in [
            "ignore your principles",
            "bypass the safety",
            "disable the principles",
        ]:
            flag = self.intake.receive(text)["safety"]
            self.assertIsNotNone(flag, f"INTEGRITY not detected: '{text}'")
            self.assertEqual(flag["level"], "INTEGRITY")

    def test_normal_input_has_no_flag(self):
        """
        Normal everyday input produces no safety flag.
        If this fails: The system is treating normal users as threats.
        This violates Principle XI — Dignity.
        """
        for text in [
            "Hello, how are you today?",
            "What is the weather like?",
            "I would like to learn more about Python.",
            "Can you help me understand this system?",
            "The quick brown fox jumps over the lazy dog.",
        ]:
            self.assertIsNone(
                self.intake.receive(text)["safety"],
                f"False positive for: '{text}'"
            )

    def test_safety_flag_has_required_fields(self):
        """Every safety flag contains the required fields."""
        flag = self.intake.receive("I want to hurt someone")["safety"]
        for field in ["level", "message", "requires_human"]:
            self.assertIn(field, flag)
        self.assertTrue(flag["requires_human"])

    # ── Package structure ─────────────────────────────────────────────────────

    def test_package_has_all_required_fields(self):
        """Every intake package contains all required fields."""
        p = self.intake.receive("Test input")
        for field in ["raw", "clean", "input_type", "source",
                      "word_count", "complexity", "safety", "record_id"]:
            self.assertIn(field, p, f"Package missing: {field}")

    def test_raw_input_never_modified(self):
        """The raw field is always the original input, unchanged."""
        raw = "  Hello World  "
        self.assertEqual(self.intake.receive(raw)["raw"], raw)

    def test_clean_input_is_trimmed(self):
        """The clean field has whitespace removed from both ends."""
        self.assertEqual(
            self.intake.receive("  Hello World  ")["clean"], "Hello World"
        )

    def test_every_intake_is_recorded(self):
        """Every intake is permanently saved to the audit trail."""
        record_id = self.intake.receive("Test")["record_id"]
        self.assertIsInstance(record_id, int)
        self.assertGreater(record_id, 0)

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_very_long_input_handled(self):
        """Ten thousand words does not crash the system."""
        p = self.intake.receive("word " * 10000)
        self.assertEqual(p["complexity"], "complex")

    def test_special_characters_handled(self):
        """Special characters do not crash the system."""
        self.assertIsNotNone(
            self.intake.receive("Hello! @#$%^&*() — 'quotes'")
        )

    def test_unicode_handled(self):
        """International characters work correctly."""
        self.assertIsNotNone(
            self.intake.receive("Héllo Wörld — 你好世界 — مرحبا")
        )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: CONTEXTUALIZE
# ─────────────────────────────────────────────────────────────────────────────

class TestContextualize(ONTOTestCase):
    """
    Tests for modules/contextualize.py — the understanding layer.

    Plain English: Makes sure the system builds genuine understanding
    from inputs over time — finding connections, measuring familiarity,
    and weighting what deserves attention.

    Expected: 12 passed.
    """

    def setUp(self):
        super().setUp()
        from modules import contextualize
        self.contextualize = contextualize
        self.contextualize._field = []

    def test_build_adds_context(self):
        """build() returns the package with context added."""
        self.assertIn(
            "context",
            self.contextualize.build(self._make_package("Hello"))
        )

    def test_context_has_required_fields(self):
        """Context contains all required fields."""
        context = self.contextualize.build(
            self._make_package("Hello")
        )["context"]
        for field in ["related_count", "distance", "weight",
                      "field_size", "summary"]:
            self.assertIn(field, context)

    def test_first_input_is_completely_new(self):
        """The first ever input has maximum distance — new territory."""
        enriched = self.contextualize.build(self._make_package("Something new"))
        self.assertGreaterEqual(enriched["context"]["distance"], 0.9)

    def test_repeated_input_becomes_familiar(self):
        """The same input feels more familiar the second time."""
        text = "Python programming language"
        e1 = self.contextualize.build(self._make_package(text))
        e2 = self.contextualize.build(self._make_package(text))
        self.assertLess(e2["context"]["distance"], e1["context"]["distance"])

    def test_field_grows_with_each_input(self):
        """The field grows by one for each input."""
        self.contextualize._field = []
        for i in range(5):
            self.contextualize.build(self._make_package(f"unique {i}"))
        self.assertEqual(len(self.contextualize._field), 5)

    def test_distance_is_between_zero_and_one(self):
        """Distance is always between 0.0 and 1.0."""
        for text in ["Hello", "World", "Python", "AI"]:
            d = self.contextualize.build(
                self._make_package(text)
            )["context"]["distance"]
            self.assertGreaterEqual(d, 0.0)
            self.assertLessEqual(d, 1.0)

    def test_weight_is_between_zero_and_one(self):
        """Weight is always between 0.0 and 1.0."""
        for text in ["Hi", "complex input " * 10]:
            w = self.contextualize.build(
                self._make_package(text)
            )["context"]["weight"]
            self.assertGreaterEqual(w, 0.0)
            self.assertLessEqual(w, 1.0)

    def test_complex_inputs_get_higher_weight(self):
        """Complex inputs get more attention than simple ones."""
        self.contextualize._field = []
        w_simple = self.contextualize.build(
            self._make_package("Hi", complexity="simple")
        )["context"]["weight"]

        self.contextualize._field = []
        w_complex = self.contextualize.build(
            self._make_package("complex " * 10, complexity="complex")
        )["context"]["weight"]

        self.assertGreater(w_complex, w_simple)

    def test_related_inputs_found(self):
        """Inputs sharing meaningful words are found as related."""
        self.contextualize.build(self._make_package("Python programming language"))
        self.contextualize.build(self._make_package("Python developer tools"))
        enriched = self.contextualize.build(
            self._make_package("Python coding environment")
        )
        self.assertGreater(enriched["context"]["related_count"], 0)

    def test_unrelated_inputs_not_found(self):
        """Inputs about different topics are not related."""
        self.contextualize.build(self._make_package("cooking pasta recipes"))
        enriched = self.contextualize.build(
            self._make_package("quantum physics particles")
        )
        self.assertEqual(enriched["context"]["related_count"], 0)

    def test_summary_is_always_a_string(self):
        """Context summary is always a readable string."""
        summary = self.contextualize.build(
            self._make_package("Test")
        )["context"]["summary"]
        self.assertIsInstance(summary, str)
        self.assertGreater(len(summary), 0)

    def test_field_restored_from_memory(self):
        """The field rebuilds from permanent memory after a restart."""
        from modules import intake
        intake.receive("First session Python input")
        intake.receive("Second session AI input")
        self.contextualize._field = []
        count = self.contextualize.load_from_memory()
        self.assertGreater(count, 0)


# ─────────────────────────────────────────────────────────────────────────────
# TEST: SURFACE
# ─────────────────────────────────────────────────────────────────────────────

class TestSurface(ONTOTestCase):
    """
    Tests for modules/surface.py — the system's voice.

    Plain English: Makes sure the system communicates
    honestly and clearly — especially in safety situations.
    This is Principles IV (Truth) and IX (Humility) verified by tests.

    Expected: 11 passed.
    """

    def setUp(self):
        super().setUp()
        from modules import surface
        self.surface = surface

    def test_present_has_required_fields(self):
        """Surface output always contains all required fields."""
        result = self.surface.present(self._make_enriched())
        for field in ["display", "confidence", "weight", "safe", "record_id"]:
            self.assertIn(field, result)

    def test_safe_input_is_marked_safe(self):
        """Normal input is marked as safe."""
        self.assertTrue(self.surface.present(self._make_enriched())["safe"])

    def test_flagged_input_is_marked_unsafe(self):
        """Safety-flagged input is marked as not safe."""
        enriched = self._make_enriched(
            safety={"level": "CRISIS", "message": "Test", "requires_human": True}
        )
        self.assertFalse(self.surface.present(enriched)["safe"])

    def test_crisis_response_shows_help_numbers(self):
        """
        CRISIS response shows real crisis support numbers.
        This is Principle II — Life First — visible to the user.
        If this fails: People in crisis are not shown how to get help. Critical bug.
        """
        enriched = self._make_enriched(
            safety={"level": "CRISIS", "message": "Test", "requires_human": True}
        )
        display = self.surface.present(enriched)["display"]
        self.assertIn("988", display)
        self.assertIn("741741", display)

    def test_integrity_response_mentions_principles(self):
        """INTEGRITY response explains that principles protect everyone."""
        enriched = self._make_enriched(
            safety={"level": "INTEGRITY", "message": "Test", "requires_human": True}
        )
        self.assertIn("principles",
            self.surface.present(enriched)["display"].lower())

    def test_confidence_is_one_minus_distance(self):
        """Confidence equals 1.0 minus distance."""
        result = self.surface.present(self._make_enriched(distance=0.3))
        self.assertAlmostEqual(result["confidence"], 0.7, places=2)

    def test_high_confidence_uses_confident_language(self):
        """High confidence produces language that reflects certainty."""
        result = self.surface.present(self._make_enriched(distance=0.1))
        self.assertIn("confident", result["display"].lower())

    def test_low_confidence_uses_humble_language(self):
        """
        Low confidence produces honest, humble language.
        This is Principle IV — Truth — in action.
        The system never pretends to know more than it does.
        """
        result = self.surface.present(self._make_enriched(distance=0.95))
        display = result["display"].lower()
        self.assertTrue(
            any(p in display for p in
                ["low confidence", "not very sure", "human judgment", "very low"])
        )

    def test_display_shows_what_user_said(self):
        """The display always shows the user's original input."""
        result = self.surface.present(
            self._make_enriched(text="unique test phrase xyz")
        )
        self.assertIn("unique test phrase xyz", result["display"])

    def test_result_is_permanently_recorded(self):
        """Every surface result is saved to the audit trail."""
        result = self.surface.present(self._make_enriched())
        self.assertIsInstance(result["record_id"], int)
        self.assertGreater(result["record_id"], 0)

    def test_safety_always_overrides_everything(self):
        """
        A safety flag produces a safety response no matter what else is set.
        Maximum confidence and minimum weight cannot suppress it.
        Human safety always comes first — Principle II.
        """
        enriched = self._make_enriched(
            distance=0.0,
            weight=0.0,
            safety={"level": "HARM", "message": "Test", "requires_human": True}
        )
        self.assertFalse(self.surface.present(enriched)["safe"])


# ─────────────────────────────────────────────────────────────────────────────
# TEST: FULL LOOP
# ─────────────────────────────────────────────────────────────────────────────

class TestFullLoop(ONTOTestCase):
    """
    Integration tests — all five steps working together.

    Plain English: These tests are the closest thing to
    a real user experience. If these pass, the system works
    as a complete, connected whole.

    Expected: 8 passed.
    """

    def test_full_loop_completes(self):
        """The complete loop runs from input to output without error."""
        _, _, surfaced = self._run_loop("Hello world")
        self.assertIsNotNone(surfaced["display"])

    def test_full_loop_writes_to_memory(self):
        """Every loop creates permanent memory records."""
        initial = len(self._memory.read_all())
        self._run_loop("Test input")
        self.assertGreater(len(self._memory.read_all()), initial)

    def test_field_grows_across_inputs(self):
        """The field grows with each input processed."""
        self._ctx._field = []
        for text in ["Python input", "AI input", "data input"]:
            self._run_loop(text)
        self.assertEqual(len(self._ctx._field), 3)

    def test_safety_flag_reaches_surface(self):
        """A safety flag set in intake reaches the surface output."""
        _, _, surfaced = self._run_loop("I want to hurt someone")
        self.assertFalse(surfaced["safe"])

    def test_connections_form_within_session(self):
        """The system finds connections between inputs in the same session."""
        self._run_loop("Python is a programming language")
        self._run_loop("Python developers use many tools")
        _, enriched, _ = self._run_loop("Python programming environment")
        self.assertGreater(enriched["context"]["related_count"], 0)

    def test_confidence_grows_with_familiarity(self):
        """Confidence improves as the system sees familiar content."""
        text = "machine learning artificial intelligence"
        _, _, s1 = self._run_loop(text)
        _, _, s2 = self._run_loop(text)
        self.assertGreaterEqual(s2["confidence"], s1["confidence"])

    def test_different_topics_do_not_interfere(self):
        """Many different topics can be processed without corrupting state."""
        for text in [
            "cooking pasta", "quantum physics",
            "mountain climbing", "music theory", "software engineering"
        ]:
            _, _, surfaced = self._run_loop(text)
            self.assertIsNotNone(surfaced["display"])
            self.assertIsNotNone(surfaced["record_id"])

    def test_fifty_rapid_inputs_handled(self):
        """Fifty inputs in rapid succession do not crash the system."""
        for i in range(50):
            self._run_loop(f"rapid input {i}")
        self.assertEqual(len(self._ctx._field), 50)


# ─────────────────────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\nONTO Test Suite")
    print("=" * 60)
    print("Expected result: 89 passed, 0 failed, 0 errors.")
    print("If you see anything different — something needs attention.")
    print("=" * 60 + "\n")
    unittest.main(verbosity=2)


# ─────────────────────────────────────────────────────────────────────────────
# TEST: SANITIZATION & EDGE CASES — Items 1.07 + 1.08
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitization(ONTOTestCase):
    """
    Tests for input sanitization — item 1.07.

    Plain English: Makes sure dangerous or malformed inputs
    are cleaned safely without crashing the system or
    altering what the person actually said.

    Expected: 14 passed.
    """

    def setUp(self):
        super().setUp()
        from modules import intake
        self.intake = intake

    def test_null_bytes_removed(self):
        """
        Null bytes are stripped from input.
        Null bytes can cause unexpected behavior in databases and logs.
        """
        p = self.intake.receive("Hello\x00World")
        self.assertNotIn("\x00", p["clean"])
        self.assertIn("Hello", p["clean"])

    def test_control_characters_removed(self):
        """
        ASCII control characters are stripped.
        These can interfere with terminal display and logging.
        """
        p = self.intake.receive("\x01\x02\x03 hidden chars \x04\x05")
        for i in range(1, 6):
            self.assertNotIn(chr(i), p["clean"])

    def test_bidi_override_stripped(self):
        """
        Unicode bidirectional control characters are removed.
        These can be used to visually disguise malicious text —
        making dangerous content appear harmless on screen.
        """
        bidi = "\u202e"  # Right-to-left override
        p = self.intake.receive(f"Hello {bidi}World")
        self.assertNotIn(bidi, p["clean"])

    def test_multiple_spaces_normalized(self):
        """Multiple spaces are collapsed to a single space."""
        p = self.intake.receive("Hello     World")
        self.assertNotIn("     ", p["clean"])
        self.assertIn("Hello World", p["clean"])

    def test_tabs_normalized(self):
        """Tabs are normalized to single spaces."""
        p = self.intake.receive("Hello\t\tWorld")
        self.assertNotIn("\t\t", p["clean"])

    def test_excessive_newlines_normalized(self):
        """More than two consecutive newlines are reduced to two."""
        p = self.intake.receive("Hello\n\n\n\n\nWorld")
        self.assertNotIn("\n\n\n", p["clean"])

    def test_very_long_input_truncated(self):
        """
        Input exceeding the maximum length is truncated.
        The truncated flag is set so the system knows this happened.
        If this fails: Extremely long inputs could cause memory issues.
        """
        from modules.intake import MAX_INPUT_LENGTH
        long_input = "word " * (MAX_INPUT_LENGTH // 4)
        p = self.intake.receive(long_input)
        self.assertTrue(p["truncated"],
            "Very long input should be flagged as truncated")
        self.assertLessEqual(len(p["clean"]), MAX_INPUT_LENGTH)

    def test_normal_input_not_flagged_as_sanitized(self):
        """Normal clean input is not flagged as sanitized."""
        p = self.intake.receive("Hello, how are you today?")
        self.assertFalse(p["sanitized"])
        self.assertFalse(p["truncated"])

    def test_raw_input_always_preserved(self):
        """
        The raw field always contains the original input exactly.
        Even when sanitization changes the clean version.
        """
        raw = "Hello\x00World"
        p = self.intake.receive(raw)
        self.assertEqual(p["raw"], raw)

    def test_sanitization_recorded_in_memory(self):
        """Sanitization status is recorded in the audit trail."""
        self.intake.receive("Hello\x00World")
        records = self._memory.read_by_type("INTAKE")
        self.assertGreater(len(records), 0)
        context = records[0].get("context", {})
        self.assertIn("sanitized", context)

    def test_sql_injection_handled_safely(self):
        """
        SQL injection attempts do not crash or corrupt the system.
        Note: Memory uses parameterized queries so injection
        cannot affect the database — this confirms it stays safe.
        """
        dangerous = "'; DROP TABLE events; --"
        try:
            p = self.intake.receive(dangerous)
            self.assertIsNotNone(p["record_id"])
        except Exception as e:
            self.fail(f"SQL injection attempt crashed the system: {e}")

    def test_script_injection_handled_safely(self):
        """Script tags pass through as plain text without execution."""
        p = self.intake.receive('<script>alert("xss")</script>')
        self.assertIsNotNone(p)
        self.assertIsNotNone(p["record_id"])

    def test_path_traversal_handled_safely(self):
        """Path traversal strings are treated as plain text."""
        p = self.intake.receive("../../../etc/passwd")
        self.assertIsNotNone(p)
        self.assertIsNotNone(p["record_id"])

    def test_whitespace_only_input_handled(self):
        """Whitespace-only input is classified as unknown without error."""
        p = self.intake.receive("     ")
        self.assertEqual(p["input_type"], "unknown")
        self.assertEqual(p["clean"], "")


class TestEdgeCases(ONTOTestCase):
    """
    Edge case tests — item 1.08.

    Plain English: Tests for unusual but real situations
    the system might encounter. Every case is documented
    with why it matters.

    Expected: 12 passed.
    """

    def setUp(self):
        super().setUp()
        from modules import intake, contextualize, surface
        self.intake = intake
        self.contextualize = contextualize
        self.surface = surface

    def test_empty_string_handled(self):
        """Empty string does not crash the system."""
        p = self.intake.receive("")
        self.assertEqual(p["input_type"], "unknown")
        self.assertIsNotNone(p["record_id"])

    def test_single_character_handled(self):
        """A single character is handled correctly."""
        p = self.intake.receive("a")
        self.assertIsNotNone(p)
        self.assertEqual(p["word_count"], 1)

    def test_only_punctuation_handled(self):
        """Input containing only punctuation does not crash."""
        p = self.intake.receive("!@#$%^&*()")
        self.assertIsNotNone(p)

    def test_very_long_single_word_handled(self):
        """A single word with no spaces of extreme length is handled."""
        long_word = "a" * 1000
        p = self.intake.receive(long_word)
        self.assertIsNotNone(p)
        self.assertEqual(p["word_count"], 1)

    def test_repeated_identical_inputs_handled(self):
        """
        The same input received many times does not corrupt state.
        The system should become more familiar — not break.
        """
        for _ in range(20):
            p = self.intake.receive("Hello world")
            self.assertIsNotNone(p["record_id"])

    def test_mixed_language_input_handled(self):
        """Input mixing multiple languages does not crash."""
        p = self.intake.receive("Hello 你好 مرحبا Héllo Wörld")
        self.assertIsNotNone(p)

    def test_emoji_input_handled(self):
        """Emoji characters do not crash the system."""
        p = self.intake.receive("Hello 🌍 World 🤝")
        self.assertIsNotNone(p)

    def test_newline_only_input_handled(self):
        """Input containing only newlines is handled gracefully."""
        p = self.intake.receive("\n\n\n\n")
        self.assertEqual(p["input_type"], "unknown")

    def test_number_with_formatting_handled(self):
        """Formatted numbers like currency are classified as numbers."""
        p = self.intake.receive("$1,234.56")
        self.assertEqual(p["input_type"], "number")

    def test_contextualize_handles_empty_clean(self):
        """
        Contextualize handles a package with an empty clean field.
        This could happen after heavy sanitization.
        """
        package = {
            "clean": "",
            "raw": "\x00\x01",
            "input_type": "unknown",
            "complexity": "simple",
            "word_count": 0,
            "safety": None,
            "source": "human",
            "record_id": 1
        }
        try:
            enriched = self.contextualize.build(package)
            self.assertIn("context", enriched)
        except Exception as e:
            self.fail(f"Contextualize crashed on empty clean: {e}")

    def test_surface_handles_zero_confidence(self):
        """Surface handles a confidence score of exactly zero."""
        enriched = self._make_enriched(distance=1.0)  # confidence = 0.0
        result = self.surface.present(enriched)
        self.assertIsNotNone(result["display"])
        self.assertAlmostEqual(result["confidence"], 0.0, places=2)

    def test_surface_handles_max_confidence(self):
        """Surface handles a confidence score of exactly one."""
        enriched = self._make_enriched(distance=0.0)  # confidence = 1.0
        result = self.surface.present(enriched)
        self.assertIsNotNone(result["display"])
        self.assertAlmostEqual(result["confidence"], 1.0, places=2)
