"""
tests/test_classification_and_config.py

Tests for:
  5.07 — Data classification at intake (REVIEW_001 finding C3)
  5.08 — Safe messaging response text in core/config.py (REVIEW_001 finding C4)

Checklist items: 5.07, 5.08

Rule 1.09A: Code, tests, and documentation must always agree.

Test count: 16
  TestDataClassification   — 11 tests
  TestSafeMessagingConfig  —  5 tests
"""

import os
import tempfile
import unittest

from modules import intake, memory
from core.config import ONTOConfig


# ─────────────────────────────────────────────────────────────────────────────
# SHARED SETUP
# ─────────────────────────────────────────────────────────────────────────────

class _IntakeTestBase(unittest.TestCase):
    """Fresh isolated database for every test."""

    def setUp(self):
        self._orig_db = memory.DB_PATH
        fd, self.test_db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.test_db)
        memory.DB_PATH = self.test_db
        memory.initialize()

    def tearDown(self):
        memory.DB_PATH = self._orig_db
        for path in [self.test_db, self.test_db + "-wal", self.test_db + "-shm"]:
            if os.path.exists(path):
                os.remove(path)


# ─────────────────────────────────────────────────────────────────────────────
# 5.07 — DATA CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

class TestDataClassification(_IntakeTestBase):
    """
    Every input is classified at intake.
    Classification propagates through every downstream module.
    It can only increase — never decrease.

    Classification levels (crossover contract §28):
      0 — public:    No sensitivity
      2 — personal:  Individual identifying information
      3 — sensitive: Health, financial, legal, biometric
    """

    def test_default_classification_is_zero(self):
        """
        Routine input with no sensitive content must classify as 0 (public).
        The system starts with the least restrictive assumption.
        """
        result = intake.receive("What is the weather today?")
        self.assertEqual(
            result["classification"], 0,
            "Non-sensitive input must classify as 0."
        )

    def test_classification_field_always_present(self):
        """
        The classification field must always be present in the package.
        Downstream modules depend on it — its absence is a contract violation.
        """
        result = intake.receive("hello")
        self.assertIn("classification", result)
        self.assertIn("classification_basis", result)

    def test_health_keywords_classify_as_three(self):
        """Health and medical language must classify as level 3 (sensitive)."""
        inputs = [
            "I have a medical diagnosis I need help with",
            "My prescription medication is running out",
            "I have a health symptom I'm worried about",
        ]
        for text in inputs:
            result = intake.receive(text)
            self.assertEqual(
                result["classification"], 3,
                f"Expected classification 3 for: '{text}'"
            )

    def test_financial_keywords_classify_as_three(self):
        """Financial information must classify as level 3 (sensitive)."""
        inputs = [
            "My bank account number is 12345",
            "I need help with my credit card",
            "My social security number is on the form",
        ]
        for text in inputs:
            result = intake.receive(text)
            self.assertEqual(
                result["classification"], 3,
                f"Expected classification 3 for: '{text}'"
            )

    def test_password_keywords_classify_as_three(self):
        """Credential-related language must classify as level 3 (sensitive)."""
        result = intake.receive("My password for the system is stored here")
        self.assertEqual(result["classification"], 3)

    def test_legal_keywords_classify_as_three(self):
        """Legal information must classify as level 3 (sensitive)."""
        result = intake.receive("I need help with my lawyer and my lawsuit")
        self.assertEqual(result["classification"], 3)

    def test_personal_name_classifies_as_two(self):
        """Personal identifying information must classify as level 2."""
        inputs = [
            "My name is Jordan",
            "Call me Alex",
            "I'm called Sam",
        ]
        for text in inputs:
            result = intake.receive(text)
            self.assertEqual(
                result["classification"], 2,
                f"Expected classification 2 for: '{text}'"
            )

    def test_contact_info_classifies_as_two(self):
        """Contact details must classify as level 2 (personal)."""
        inputs = [
            "My email is on file",
            "My phone number has changed",
            "My address is different now",
        ]
        for text in inputs:
            result = intake.receive(text)
            self.assertEqual(
                result["classification"], 2,
                f"Expected classification 2 for: '{text}'"
            )

    def test_level_three_takes_priority_over_level_two(self):
        """
        When both personal (2) and sensitive (3) signals are present,
        the higher classification wins. Classification only increases.
        """
        result = intake.receive(
            "My name is Jordan and I have a medical diagnosis"
        )
        self.assertEqual(
            result["classification"], 3,
            "Level 3 must take priority when both levels are detected."
        )

    def test_classification_recorded_in_audit_trail(self):
        """
        The classification must be recorded in the audit trail.
        Privacy-sensitive reads are only loggable if the level is stored.
        """
        intake.receive("My bank account is overdrawn")
        records = memory.read_by_type("INTAKE")
        self.assertTrue(len(records) > 0)
        last = records[-1]
        self.assertIsNotNone(last.get("classification"))
        self.assertGreaterEqual(last["classification"], 3)

    def test_classification_propagates_in_package(self):
        """
        The classification field in the returned package must match
        what was detected. Downstream modules read from the package —
        if the field is wrong here, the privacy architecture fails.
        """
        result = intake.receive("My prescription medication dosage")
        self.assertGreaterEqual(result["classification"], 3)
        context_records = memory.read_by_type("INTAKE")
        stored_classification = context_records[-1].get("classification", -1)
        self.assertEqual(result["classification"], stored_classification)


# ─────────────────────────────────────────────────────────────────────────────
# 5.08 — SAFE MESSAGING CONFIG
# ─────────────────────────────────────────────────────────────────────────────

class TestSafeMessagingConfig(unittest.TestCase):
    """
    Safe messaging response text must:
      - Be present and non-empty by default
      - Contain crisis resources
      - Be overridable via environment variable for localization
      - Never be empty — a blank crisis response is a patient safety failure
    """

    def setUp(self):
        self.cfg = ONTOConfig()
        # Clean up any env overrides before each test
        for key in [
            "ONTO_CRISIS_RESPONSE_TEXT",
            "ONTO_CRISIS_RESOURCES_BRIEF",
            "ONTO_AUTOMATION_BIAS_WARNING",
        ]:
            os.environ.pop(key, None)

    def tearDown(self):
        for key in [
            "ONTO_CRISIS_RESPONSE_TEXT",
            "ONTO_CRISIS_RESOURCES_BRIEF",
            "ONTO_AUTOMATION_BIAS_WARNING",
        ]:
            os.environ.pop(key, None)

    def test_crisis_response_text_is_non_empty(self):
        """
        The default crisis response text must never be empty.
        An empty response at a CRISIS checkpoint is a patient safety failure.
        """
        self.assertTrue(
            len(self.cfg.CRISIS_RESPONSE_TEXT.strip()) > 0,
            "CRISIS_RESPONSE_TEXT must not be empty. "
            "A blank crisis response is a patient safety failure."
        )

    def test_crisis_response_contains_resources(self):
        """
        The default crisis response must contain at least one crisis resource.
        The 988 line and Crisis Text Line are the primary US resources.
        """
        text = self.cfg.CRISIS_RESPONSE_TEXT
        has_resource = (
            "988" in text
            or "741741" in text
            or "findahelpline" in text
        )
        self.assertTrue(
            has_resource,
            "CRISIS_RESPONSE_TEXT must contain at least one crisis resource "
            "(988, 741741, or findahelpline.com)."
        )

    def test_crisis_response_overridable_via_env(self):
        """
        Deployers must be able to override crisis text for localization.
        A fixed English-only response fails non-English speakers.
        """
        os.environ["ONTO_CRISIS_RESPONSE_TEXT"] = "Custom crisis message"
        cfg = ONTOConfig()
        self.assertEqual(cfg.CRISIS_RESPONSE_TEXT, "Custom crisis message")

    def test_automation_bias_warning_is_non_empty(self):
        """
        The automation bias warning must never be empty.
        Required by EU AI Act Article 14(4)(b).
        """
        self.assertTrue(
            len(self.cfg.AUTOMATION_BIAS_WARNING.strip()) > 0,
            "AUTOMATION_BIAS_WARNING must not be empty. "
            "EU AI Act Article 14(4)(b) requires this warning."
        )

    def test_crisis_resources_brief_contains_988(self):
        """
        The brief crisis resource line must reference 988.
        This is the primary US crisis resource as of 2023.
        """
        self.assertIn(
            "988", self.cfg.CRISIS_RESOURCES_BRIEF,
            "CRISIS_RESOURCES_BRIEF must reference the 988 crisis line."
        )


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
