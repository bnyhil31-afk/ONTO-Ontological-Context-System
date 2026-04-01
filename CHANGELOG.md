# CHANGELOG

All notable changes to ONTO are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased] — License Update, Copyright Notice, IP Protection

### Changed

- **License** — Updated from MIT to GNU Lesser General Public License
  v2.1 (LGPL-2.1), version-locked (not "or later"). LGPL-2.1 requires
  that modifications to ONTO's source code be shared back under the same
  license, while permitting use in proprietary applications built on top
  of ONTO without modification. This closes the "fork, remove principles,
  ship proprietary" attack vector that MIT left open, and preserves the
  ability to pursue patent protection for the core three-axis contextual
  reasoning architecture. The LICENSE file has been updated. The NOTICE
  file has been added. All documentation references to "MIT License" have
  been corrected to "LGPL-2.1".

- **`docs/ONTO_Preservation_Document.txt`** — Updated to v1.1. Corrected
  two references to "MIT license" in Part I and Part V to reflect the
  current LGPL-2.1 license. Corrected repository URL from the legacy
  Hello-World URL to the current ONTO-Ontological-Context-System URL.

- **`docs/TERMS_OF_USE.md`** — Updated to v1.1. Corrected all references
  to "MIT License" to "LGPL-2.1". Updated Section 3 to clarify that
  modifications to the library must be shared back. Updated Section 11
  to accurately describe LGPL-2.1 terms. Added patent pending notice.

### Added

- **`NOTICE`** — Copyright assertion and intellectual property notice.
  Asserts copyright ownership. Identifies the patentable IP in the
  three-axis contextual reasoning architecture, wellbeing protection
  layer, self-preserving node design, and SOMA integration concept.
  Includes trademark notice for the ONTO name and identity. Lists
  third-party component licenses. Replace [YOUR LEGAL NAME] with your
  full legal name before any public distribution.

---

## [Unreleased] — Relationship Graph, Theoretical Foundation, Tests

### Added

- **`modules/graph.py`** — The relationship graph — the heart of ONTO.
  Implements the weighted relationship graph that the entire system is
  designed around. Nine research-backed design decisions incorporated
  from a multi-domain research audit spanning cognitive science, graph
  theory, NLP, philosophy, safety, and compliance:
  power-law decay (Wixted 2004, Jost's Law 1897) replaces exponential
  decay; spacing-effect reinforcement (Cepeda et al. 2006) replaces flat
  increment; TF-IDF Size axis (Sparck Jones 1972) replaces raw frequency;
  PPMI-approximation edge scoring (Bullinaria & Levy 2007); ACT-R fan
  effect during traversal (Anderson 1983); RAKE-inspired concept
  extraction (Rose et al. 2010); sensitive topic and crisis detection
  wellbeing protection layer (Nolen-Hoeksema 1991, 2008) — crisis content
  is never stored, sensitive content receives reduced reinforcement and
  faster decay; wipe() implements GDPR Article 17 right to erasure; lazy
  decay computes effective weight at read time rather than batching.
  Graph schema: graph_nodes, graph_edges, graph_metadata tables in the
  shared SQLite database. Migration-safe: ALTER TABLE ADD COLUMN for
  upgrades. Stable UUID node identifiers for backend portability.

- **`docs/GRAPH_THEORY_001.md`** — Permanent theoretical basis reference
  for modules/graph.py. Records every design decision and its named
  scientific source. Documents what is deferred to Stage 2 (Personalized
  PageRank, full PPMI, spaCy NER, directed edges, per-user decay
  calibration). Corrects the philosophical framing: ONTO is a cognitive
  scaffold in the sense of Clark & Chalmers (1998) extended mind thesis —
  not autopoietic.

- **`tests/test_graph.py`** — Full test suite for modules/graph.py
  (checklist items 1.14, 1.17, 2.12). 32 tests across 7 classes:
  TestGraphInitialize (3), TestGraphRelate (10), TestGraphNavigate (7),
  TestGraphDecay (4), TestGraphWipe (5), TestEffectiveWeight (3),
  TestSpacingIncrement (3), TestConceptExtraction (3).
  Safety-critical coverage: crisis content never stored (1.17).
  GDPR coverage: wipe() records audit event, navigate() empty after
  wipe (2.12).

### Changed

- **`main.py`** — Boot sequence extended to 4 steps. Step 3 initialises
  and prunes the relationship graph (graph.initialize() + graph.decay())
  before rebuilding the context field. The word-overlap fallback in
  contextualize.py is no longer triggered — _GRAPH_AVAILABLE is True.
  Every user input now writes real weighted edges to the graph.

- **`docs/ONTO_PreLaunch_Checklist.txt`** — Updated to v9. Items 1.14,
  1.16, 1.17, 2.02, 3.14 marked complete. 19 new items added across
  sections 1–7 from the research audit. Test count updated to 227.
  New Section 6 (Stage 2 preparation) added.

- **`tests/README.md`** — Updated to reflect 227 total passing tests.
  TestGraphInitialize, TestGraphRelate, TestGraphNavigate, TestGraphDecay,
  TestGraphWipe, TestEffectiveWeight, TestSpacingIncrement,
  TestConceptExtraction added to the class table.
  TestAuthentication and TestEncryptionLayer entries added.

---

## [Unreleased] — API Layer, Session Management, Merkle Chain Tests

### Added

- **`core/session.py`** — Session management layer (checklist item 2.09).
  256-bit cryptographic tokens. Token rotation on every authenticated
  request (T-013 mitigation). Idle timeout and hard max-duration expiry.
  Adaptive audit dispatch (1- or 2-arg callable). Session events written
  permanently to SQLite audit trail via `memory.record()`. Connection
  binding, data classification escalation, GDPR-forward consent reference
  field. Thread-safe singleton. Swap-in interface for Stage 2 SSO.
  17 tests in `tests/test_session.py`.

- **`api/main.py`** — HTTP API server (checklist item 3.04). Five
  endpoints wrapping the ONTO five-step processing loop: `GET /health`,
  `POST /auth`, `POST /process`, `GET /audit`, `DELETE /session`.
  CRISIS signals never suppressed — always surfaced to client.
  Pending-checkpoint flow preserves human sovereignty at every
  consequential decision. Token rotation on every request via
  `X-Session-Token` response header. Rate limiting via existing
  `core/ratelimit.py`. Principle verification at startup — server refuses
  to start with tampered principles. Auto-generated OpenAPI documentation
  at `/docs` and `/redoc`. Checkpoint human-decision injection via
  `unittest.mock.patch` — no modification to `checkpoint.py` required.

- **`api/__init__.py`** — Package init for the `api/` module.

- **`docs/FAQ.md`** — Frequently asked questions document (checklist
  item 3.06). Covers installation, principles, audit trail, checkpoint,
  CRISIS protocol, authentication, sessions, configuration, privacy,
  and development workflow. Plain English throughout.

- **`tests/test_onto.py::TestMerkleChainCore`** — 7 Merkle chain tests
  (checklist item 1.13). Verifies: genesis record has no chain_hash,
  second record links to first, chain_hash is valid 64-char SHA-256 hex,
  hash value is independently reproducible, `verify_chain()` passes for
  intact trail, `verify_chain()` detects deliberately wrong chain_hash,
  `verify_chain()` result has all required fields. Direct SQLite INSERT
  (bypassing `record()`) used to simulate a corrupted chain_hash without
  triggering the append-only trigger.

### Changed

- **`requirements-test.txt`** — Added `fastapi>=0.115.0`,
  `uvicorn[standard]>=0.27.0`, `httpx>=0.27.0` for API server and
  testing. Added explicit `starlette>=0.45.3` pin to resolve
  GHSA-7f5h-v6xp-fcq8 (ReDoS in Range header parsing). Python 3.8
  dropped — EOL October 2024, incompatible with fixed starlette versions.

- **`.github/workflows/ci.yml`** — Python 3.8 removed from matrix.
  CI now runs across Python 3.9, 3.10, 3.11, 3.12.

- **`tests/test_onto.py`** — `tearDown` updated to use
  `shutil.rmtree(self.test_dir, ignore_errors=True)`. WAL-mode SQLite
  creates `.db-wal` and `.db-shm` sidecar files that may be auto-cleaned
  by SQLite before `tearDown` runs, causing a spurious
  `FileNotFoundError`. `ignore_errors=True` eliminates the race.

- **`tests/README.md`** — Updated test counts and class table to reflect
  195 total passing tests across all test files.

### Security

- Explicit `starlette>=0.45.3` pin resolves GHSA-7f5h-v6xp-fcq8 — ReDoS
  vulnerability in Starlette's Range header parsing. Our API does not use
  `FileResponse` or `StaticFiles`, but the pin is correct practice.
- Python 3.8 removed from CI — EOL runtimes receive no security patches.

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

- **`GOVERNANCE.md`** — Formal project governance document (checklist
  item 3.13). Defines current founder-leader model, transition path to
  Self-Appointing Council, values change process (90-day comment +
  supermajority), protocol fork policy, anti-concentration commitment,
  and cooperative evolution path.

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
