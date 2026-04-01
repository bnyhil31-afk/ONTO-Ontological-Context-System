# Running the ONTO Tests

Plain English guide. No assumptions. No jargon.

---

## What the tests do

They check that every part of ONTO works correctly.

If all tests pass — the system is behaving as intended.
If any test fails — something needs attention before shipping.

---

## What success looks like

```
227 passed, 0 failed, 0 errors
```

If you see anything different — something needs attention.
The output will tell you exactly which test failed and why.

---

## Step 1 — Install test tools

```bash
pip install -r requirements-test.txt
```

This installs pytest and all test dependencies.
You only need to do this once.

---

## Step 2 — Run the tests

From the project root folder:

```bash
pytest tests/ -v
```

The `-v` flag means "verbose" — it shows each test name as it runs.

---

## Step 3 — Read the results

Every line will show either:

```
PASSED   — this part of the system works correctly
FAILED   — this part needs attention
ERROR    — something unexpected happened
```

At the end you will see a summary:

```
227 passed in X.Xs
```

---

## Run with coverage report

Coverage tells you what percentage of the code is tested.

```bash
pytest tests/ -v --cov=. --cov-report=term-missing
```

Target: above 80% for all critical modules.

---

## Run a single test class

```bash
pytest tests/test_onto.py::TestMemory -v
```

---

## Run just the smoke test first

The smoke test is the fastest way to confirm the system is alive.
Run this before anything else:

```bash
pytest tests/test_onto.py::TestSmoke -v
```

If the smoke test passes — the system boots correctly.
If it fails — fix it before running anything else.

---

## Run without pytest (built-in Python only)

If you cannot install pytest, use Python's built-in test runner:

```bash
python3 -m unittest discover tests/ -v
```

Results will look slightly different but test the same things.

---

## What each test file and class covers

### tests/test_onto.py — Core system (115 tests)

Class                 | Tests | What it covers
----------------------|-------|-----------------------------------------------
TestSmoke             |   4   | System boots, principles verify, memory initializes
TestVerify            |  10   | Cryptographic hash protection of the principles
TestMemory            |  15   | Permanent append-only audit trail
TestMerkleChainCore   |   7   | Chain linking, tamper detection, verify_chain() contract
TestIntake            |  22   | Input receiving, classification, safety detection
TestContextualize     |  12   | Living field and context building
TestSurface           |  11   | Honest plain language output
TestFullLoop          |   8   | All five steps working together end to end
TestSanitization      |  14   | Input sanitization — dangerous character handling
TestEdgeCases         |  12   | Unusual but real situations the system may encounter

### tests/test_conformance.py — Crossover contract (16 tests)

Class          | Tests | What it covers
---------------|-------|-----------------------------------------------
TestRELATE     |   4   | RELATE function — input ingestion and classification
TestNAVIGATE   |   4   | NAVIGATE function — context traversal and uncertainty
TestGOVERN     |   4   | GOVERN function — human sovereignty checkpoint
TestREMEMBER   |   4   | REMEMBER function — permanent audit trail

### tests/test_security.py — Security hardening (28 tests)

Class                       | Tests | What it covers
----------------------------|-------|-----------------------------------------------
TestRateLimiter             |   8   | Sliding window rate limiting
TestPrinciplesHashProtection|   8   | principles.hash tamper detection
TestEnvironmentConfig       |  12   | Environment variable configuration safety

### tests/test_memory_chain.py — Merkle chain and audit integrity (19 tests)

Class                   | Tests | What it covers
------------------------|-------|-----------------------------------------------
TestMerkleChain         |  11   | Cryptographic chain linking, tamper detection
TestReadLogging         |   6   | READ_ACCESS events for sensitive data reads
TestSignatureAlgorithm  |   2   | Signature algorithm field stored correctly

### tests/test_classification_and_config.py — Classification and safe messaging (16 tests)

Class                  | Tests | What it covers
-----------------------|-------|-----------------------------------------------
TestDataClassification |  11   | Sensitivity classification at intake (levels 0–3)
TestSafeMessagingConfig|   5   | Crisis response text and automation bias warning

### tests/test_session.py — Session management (17 tests)

Class                  | Tests | What it covers
-----------------------|-------|-----------------------------------------------
TestSessionStart       |   4   | Token generation, uniqueness, single-session invariant
TestSessionValidation  |   5   | Valid/invalid/expired token handling
TestSessionRotation    |   3   | Token rotation — old token immediately invalid
TestSessionTermination |   3   | Explicit termination behavior
TestSessionAuditTrail  |   2   | Session events recorded permanently

### tests/test_auth.py — Authentication (11 tests)

Class                | Tests | What it covers
---------------------|-------|-----------------------------------------------
TestAuthentication   |  11   | Argon2id passphrase hashing, plaintext never stored,
                     |       | correct/wrong passphrase, clear_passphrase(),
                     |       | brute force attempt tracking, input validation,
                     |       | verification phrase T-012

Note: These tests require `argon2-cffi`. They are automatically skipped
if the library is not available (see tests/conftest.py).

### tests/test_encryption.py — AES-256-GCM encryption (8 tests)

Class                | Tests | What it covers
---------------------|-------|-----------------------------------------------
TestEncryptionLayer  |   8   | Key derivation (32 bytes), key cleared on
                     |       | clear_key(), same passphrase/salt → same key,
                     |       | different passphrase → different key,
                     |       | per-installation salt, salt file creation

Note: These tests require `cryptography` and `argon2-cffi`. They are
automatically skipped if either library is not available.

### tests/test_graph.py — Relationship graph (32 tests)

Class                   | Tests | What it covers
------------------------|-------|-----------------------------------------------
TestGraphInitialize     |   3   | Tables created, indexes exist, idempotent
TestGraphRelate         |  10   | Node/edge creation, reinforcement, input counter,
                        |       | result schema, crisis never stored (safety-critical),
                        |       | sensitive detection, sensitive edges marked
TestGraphNavigate       |   7   | Empty/unknown query, related concepts returned,
                        |       | result schema, sorted by weight, sensitive excluded
                        |       | by default, source always "graph"
TestGraphDecay          |   4   | Recent edges preserved, stale edges pruned,
                        |       | orphaned nodes removed, return counts
TestGraphWipe           |   5   | All nodes deleted, all edges deleted, counter reset,
                        |       | navigate empty after wipe, audit event recorded
TestEffectiveWeight     |   3   | Power-law decay reduces weight over time,
                        |       | sensitive edges decay faster, result clamped [0,1]
TestSpacingIncrement    |   3   | Immediate = base, 30-day = 2× base, monotonic
TestConceptExtraction   |   3   | Empty text → empty list, stopwords filtered,
                        |       | MAX_CONCEPTS_PER_INPUT respected

---

## If a test fails

1. Read the failure message carefully — it explains exactly what went wrong
2. Do not ignore it or work around it
3. Fix the underlying issue before shipping

A failing test is the system telling you something important.
Listen to it.

---

## Keeping the count accurate — Rule 1.09A

Any change to the test suite requires updating three things together:
  - The test file header (expected count)
  - This README (expected count)
  - The pre-launch checklist (current status)

All three or none. A wrong number anywhere breaks trust.

---

These tests exist because the system makes promises.
The tests make sure the system keeps them.
