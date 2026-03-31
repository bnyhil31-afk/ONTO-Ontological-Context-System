# CHANGELOG

All notable changes to ONTO are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased] — Security Hardening and Review Pass

### Added

- **`core/encryption.py`** — Application-layer AES-256-GCM database
  encryption with Argon2id key derivation (OWASP 2025). Replaces PBKDF2.
  File-size padding prevents size oracle attack (T-004). Key exists only
  in memory during session, explicitly cleared at session end (T-016).

- **`core/auth.py`** — Modular authentication layer with Argon2id
  passphrase hashing, random per-installation salt, verification phrase
  at boot (T-012), and exponential backoff lockout (T-014). Swap-in
  interface for future SSO integration.

- **`GOVERNANCE.md`** — Formal project governance document. Defines
  current founder-leader model, transition path to Self-Appointing
  Council, values change process (90-day comment + supermajority),
  protocol fork policy, anti-concentration commitment, and cooperative
  evolution path.

- **`docs/THREAT_MODEL_001.txt`** — 28 threats across 9 categories.
  Every known attack vector named, severity and likelihood assessed,
  mitigation status tracked, checklist item cross-referenced.

- **`docs/ROADMAP_001.txt`** — Stage 0 through Stage 4 and beyond.
  POC to enterprise to P2P public commons. Each stage defined with
  exit criteria and remaining deliverables.

- **`docs/REVIEW_001.txt`** — Comprehensive review across 12 domains:
  graph architecture, cryptography, data sovereignty, federated systems,
  audit trails, human-in-the-loop AI, privacy engineering, ecological
  computing, open source governance, wellbeing detection, architecture,
  and post-quantum cryptography. 9 confirmed correct, 5 critical changes,
  7 upgrades, 9 explorations.

- **`docs/PQC_MIGRATION_PLAN.txt`** — Post-quantum cryptography migration
  plan. NIST FIPS 203/204/205 standards context, Python library landscape,
  phased hybrid approach by deployment stage.

### Changed

- **`modules/memory.py`** — Merkle chain: every record stores SHA-256
  hash of previous record content. Tamper detection is now structural,
  not optional. Added SQLite performance pragmas (WAL mode, 32MB cache,
  4KB page size). Added read logging for sensitive records (READ_ACCESS
  events). Added `chain_hash`, `signature_algorithm`, `classification`
  fields. Added `read_by_type()` function. Schema migration via ALTER
  TABLE ensures upgrade safety. `_connect()` guarantees DB directory
  exists before connecting.

- **`modules/intake.py`** — Data classification (levels 0-5) at intake,
  propagated forward through all downstream modules. Expanded crisis
  detection: indirect expressions, hopelessness language, goodbye
  patterns, future temporal markers added alongside direct patterns.
  Context dict stored in audit trail record. Complexity now
  sentence-based with word-count fallback. First-word command detection.
  Additional INTEGRITY patterns including "disable the principles".

- **`requirements-test.txt`** — Added `argon2-cffi>=21.3.0` for
  Argon2id key derivation.

### Fixed

- **`modules/contextualize.py`** — `r.get("context", {})` returns `None`
  when context field is present but `None`. Changed to `(r.get("context")
  or {})` to handle both absent and null context gracefully.

### Security

- PBKDF2 replaced with Argon2id (OWASP 2025) in encryption and auth
  layers. Memory-hard, GPU/ASIC-resistant, post-quantum resistant.
- Random per-installation salt in auth (U2) prevents rainbow table
  attacks against passphrase hashes.
- Merkle chain (C2) makes audit trail tamper-evident by construction.
- Data classification at intake (C3) enables privacy architecture.
- GitHub branch protection enabled — no direct pushes to main.
- 2FA enabled on repository owner account.

---

## [1.0.0] — 2026-03-28 — MVP

### Added

- Five-step processing loop: intake → contextualize → surface →
  checkpoint → memory
- 13 sealed principles with SHA-256 hash verification
- Append-only SQLite audit trail with delete/update triggers
- Safety flags: CRISIS, HARM, INTEGRITY
- 136 passing tests across Python 3.8–3.12
- CI/CD pipeline via GitHub Actions
- MIT license
- `docs/CROSSOVER_CONTRACT_v1.0.md` — architectural contract with CRE
- `docs/CRE-SPEC-001-v06.md` — CRE protocol specification
- `core/verify.py` — principle guardian, runs on every boot
- `core/ratelimit.py` — sliding window rate limiter
- `core/config.py` — environment variable configuration
- `tests/test_conformance.py` — 16 conformance tests
- `tests/test_security.py` — 12 security tests

---

*This changelog is part of the permanent record of ONTO.*
*Every significant change is documented here.*
*Honesty about what changed and why is how trust is built.*
