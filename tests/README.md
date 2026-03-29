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
82 passed, 0 failed, 0 errors
```

If you see anything different — something needs attention.
The output will tell you exactly which test failed and why.

---

## Step 1 — Install test tools

```bash
pip install -r requirements-test.txt
```

This installs pytest — the tool that runs the tests.
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
82 passed in 4.2s
```

---

## Run with coverage report

Coverage tells you what percentage of the code is tested.

```bash
pytest tests/ -v --cov=. --cov-report=term-missing
```

Target: above 80% for all critical modules.

---

## Run a single test

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
python3 -m unittest tests.test_onto -v
```

Results will look slightly different but test the same things.

---

## What each test class covers

| Class | What it tests |
|---|---|
| TestSmoke | System boots, principles verify, memory initializes |
| TestVerify | Cryptographic hash protection of the principles |
| TestMemory | Permanent append-only audit trail |
| TestIntake | Input receiving, classification, safety detection |
| TestContextualize | Living field and context building |
| TestSurface | Honest plain language output |
| TestFullLoop | All five steps working together end to end |

---

## If a test fails

1. Read the failure message carefully — it explains exactly what went wrong
2. Do not ignore it or work around it
3. Fix the underlying issue before shipping

A failing test is the system telling you something important.
Listen to it.

---

*These tests exist because the system makes promises.
The tests make sure the system keeps them.*
