# CHANGELOG

All notable changes to ONTO are documented here.
Oldest at the bottom. Newest at the top.

Every entry includes: what changed, why it changed, and when.
This file is part of the permanent record of the project.

---

## [1.0.1] — March 2026

### Added
- Input sanitization layer in modules/intake.py
  Strips null bytes, control characters, and Unicode bidirectional
  override characters. Normalizes whitespace. Enforces length limits.
  Adds 'sanitized' and 'truncated' fields to every intake package.

- TestSanitization class — 14 tests covering sanitization behavior
- TestEdgeCases class — 12 tests covering unusual real-world inputs
- Total test count: 108 passing, 0 failing

- Type hints added to all 7 source files
  memory.py, intake.py, contextualize.py, surface.py,
  checkpoint.py, verify.py, main.py

- conftest.py — shared pytest setup for isolated test databases
- requirements-test.txt — one command test installation
- tests/README.md — plain language guide for running tests
- .gitattributes — enforces LF line endings across all platforms
- Rule 1.09A — documentation consistency rule formally established

### Fixed
- setup.sh now normalizes line endings on install
  Prevents hash verification failures on Windows systems

### Changed
- tests/test_onto.py rebuilt with shared base class (ONTOTestCase)
  Eliminates repeated setup code across test classes

---

## [1.0.0] — March 2026

### Added
- principles.txt — 13 immutable principles, sealed with SHA-256 hash
  Verified hash: b1d3054f646c5f3abaffd3a275683949aef426d135cf823e7b3665fb06a03ba5
  Public record: https://gist.github.com/bnyhil31-afk/6436e717a619b9a4d685f5b8709a53c8

- core/verify.py — principle guardian, runs on every boot
- modules/memory.py — permanent append-only SQLite audit trail
- modules/intake.py — input receiver, classifier, and safety checker
- modules/contextualize.py — living field and context builder
- modules/surface.py — honest plain language output layer
- modules/checkpoint.py — human pause point and decision recorder
- main.py — entry point and main five-step loop
- setup.sh — one command setup for any device

- MIT license
- README.md with complete install instructions
- ONTO Preservation Document
- ONTO Project Record (docs/ONTO_Project_Record.docx)
- Pre-launch checklist (docs/ONTO_PreLaunch_Checklist.txt)

### Architecture
- Five-step processing loop: intake → contextualize → surface → checkpoint → memory
- Safety flags: CRISIS, HARM, INTEGRITY — detected at intake, surfaced immediately
- Three governing forces: distance, complexity, size
- Single device target: Raspberry Pi Zero 2W and above
- Zero external dependencies beyond Python standard library

---

## How to Read This File

Each version follows this format:

  [version] — date

  Added    — new features or files
  Changed  — changes to existing behavior
  Fixed    — bug fixes
  Removed  — things that were taken out
  Security — security improvements

Versions follow semantic versioning:
  Major.Minor.Patch
  1.0.0 — first public release
  1.0.1 — patch: improvements and fixes, no breaking changes
  1.1.0 — minor: new features, backwards compatible
  2.0.0 — major: breaking changes

---

*Every change is recorded. Nothing is hidden.
This is Principle VII — Memory — applied to the project itself.*
