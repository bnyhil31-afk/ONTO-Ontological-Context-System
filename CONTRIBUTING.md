# Contributing to ONTO

Thank you for being here. Every contribution matters.

Before you begin — read the principles.txt file in the project root.
They are short. They apply to everyone, including contributors.
They are the foundation everything else is built on.

---

## The Documentation Consistency Goal — 1.09A

When changing the test suite, aim to update these three things together:
  - The test file header (expected count)
  - tests/README.md (expected count)
  - docs/ONTO_PreLaunch_Checklist.txt (current status)

This is a goal, not a punishment.

Mistakes happen. If you miss one — that is human and expected.
When a mismatch is found — correct it promptly and honestly.
GitHub Actions will catch discrepancies automatically.
The system enforces consistency so people don't have to be perfect.

The goal is accuracy over time, not perfection in the moment.

---

## How to Contribute

1. Fork the repository
2. Create a branch for your change
3. Make your change
4. Run the full test suite — all tests must pass
5. Update the CHANGELOG.md
6. Submit a pull request

That is it. No special tools required. No accounts beyond GitHub.

---

## Running the Tests

Install pytest first:

  pip install -r requirements-test.txt

Then run:

  pytest tests/ -v

Expected result: 108 passed, 0 failed, 0 errors.
If you see anything different — fix it before submitting.

See tests/README.md for full instructions.

---

## Updating the CHANGELOG

Every pull request must include a CHANGELOG entry.
Add your entry at the top of CHANGELOG.md under a new version heading
or under an [Unreleased] section if a version hasn't been decided yet.

Format:

  ## [Unreleased]

  ### Added
  - Brief description of what you added and why

  ### Fixed
  - Brief description of what you fixed and why

  ### Changed
  - Brief description of what you changed and why

---

## What a Good Contribution Looks Like

A good contribution:
  - Does one thing clearly
  - Includes tests that prove it works
  - Updates documentation to match
  - Does not break any existing tests
  - Is explained in plain English in the pull request

A good pull request description answers three questions:
  - What did you change?
  - Why did you change it?
  - How do you know it works?

---

## What We Will Not Accept

We will not accept contributions that:
  - Modify or weaken the principles
  - Remove or disable safety checks
  - Break the audit trail or make records deletable or editable
  - Add external dependencies without strong justification
  - Reduce accessibility or recreatability
  - Introduce code that cannot be explained in plain English

If you are unsure whether something is acceptable — open an issue
and ask before writing the code. That is always welcome.

---

## On Mistakes

Everyone makes mistakes. That includes the people who built this.

When you make one — own it, correct it, and move on.
No hiding. No deflection. No shame.
That is Principle XIII — Accountability — applied to contributors.

The project is better for honest mistakes acknowledged
than for perfect appearances maintained.

---

## On the Principles

The 13 principles are sealed with a cryptographic hash.
They cannot be changed without that change being immediately visible.

If you believe a principle needs revisiting — open an issue.
Explain your reasoning. The conversation is always welcome.
But the principles themselves are the foundation.
They protect everyone — including future contributors.

---

## Code Style

  - Python 3.7+ compatible
  - Type hints on all functions — parameters and return values
  - Plain English docstrings on every function
  - PEP8 compliant — run flake8 before submitting
  - Maximum line length: 88 characters

---

## Accessibility

Every change should be usable by anyone, regardless of ability.

  - CLI output should be readable by screen readers
  - Error messages should be in plain language
  - Nothing should require special knowledge to understand
  - If you cannot explain what your code does simply — simplify it first

---

## Questions

Open an issue. Ask openly. Every question is welcome.

This project is built on the belief that we work better together.
That applies to contributors too.

---

*The people who build this system are bound by its principles first —
before anyone else.*
