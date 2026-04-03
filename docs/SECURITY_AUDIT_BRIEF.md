# ONTO — Security Audit Brief

**For:** Security auditors and penetration testers
**Version:** 1.0 — April 2026
**Contact:** Neo (bnyhil31-afk), GitHub: github.com/bnyhil31-afk/ONTO-Ontological-Context-System
**License:** LGPL-2.1
**Audit scope:** Stage 1 (single-node) + Phase 3 federation (local/intranet)

---

## What ONTO Is

ONTO is an open-source ontological reasoning system. It ingests natural
language input, builds a weighted knowledge graph, and surfaces context
for human-supervised decision-making. It exposes two interfaces:

1. **HTTP API** (`api/main.py`) — FastAPI, five endpoints, local deployment
2. **MCP Interface** (`api/onto_server.py`) — FastMCP 3.x, 8 tools,
   for AI system integration (Claude, GPT, etc.)

Phase 3 adds optional peer-to-peer federation for sharing graph context
between nodes on a local network.

---

## Attack Surface Summary

### Tier 1 — Internet-facing (if deployed externally)

| Surface | File | Authentication |
|---------|------|----------------|
| HTTP API | `api/main.py` | Bearer token (256-bit, Argon2id) |
| MCP Server | `api/onto_server.py` | Bearer token (same session) |
| Federation HTTP | `api/federation/local.py` | did:key manifest + TOFU cert |

### Tier 2 — Local (always present)

| Surface | File | Authentication |
|---------|------|----------------|
| SQLite database | `data/memory.db` | AES-256-GCM at rest |
| Node identity key | `~/.onto/federation/node.key` | File permissions (0600) |

### What is NOT in scope for Stage 1

- Internet-scale federation (Kademlia DHT) — Phase 4, not built
- Enterprise SSO — Phase 4, not built
- Full mTLS (gRPC) — Phase 4, not built

---

## Threat Model (Pre-existing, 28 threats)

Full threat model: `docs/THREAT_MODEL_001.txt`

**Open/Critical threats to focus on:**

| ID | Threat | Current status |
|----|--------|----------------|
| T-001 | Database tampering | Merkle chain + append-only triggers |
| T-002 | Principle tampering | SHA-256 sealed hash, verified at boot |
| T-004 | Encrypted DB size oracle | AES-256-GCM + file padding |
| T-011 | Passphrase storage | Argon2id derivation, key in memory only |
| T-013 | Session token replay | Token rotation every request, connection binding |
| T-014 | Brute force passphrase | Exponential backoff lockout |
| T-015 | Evil maid attack | Full disk encryption required on Pi (documented) |
| T-016 | Cold boot key recovery | Key cleared at session end |

**New attack surface from Phase 3 federation:**

| Surface | Threat | Mitigation |
|---------|--------|------------|
| Inbound payloads | Graph poisoning | trust_score=0.30 floor; no auto-promotion |
| mDNS advertising | Discovery enumeration | mDNS privacy note documented |
| Peer handshake | Manifest signature forgery | Ed25519 + JCS verification |
| Certificate | MITM on LAN | TOFU pinning; changes require operator checkpoint |
| Inbox flooding | DoS | 60 msg/min rate limit + exponential backoff |
| Message ordering | Replay / reorder | Sequence numbers per sender |
| Crisis content | Cross-node propagation | Absolute barrier: never passes any gate |

---

## Cryptography Inventory

| Use | Algorithm | Implementation | Key storage |
|-----|-----------|----------------|-------------|
| Database encryption | AES-256-GCM | Python `cryptography` library | Memory only during session |
| Key derivation | Argon2id | `argon2-cffi` | Passphrase never stored |
| Passphrase hashing | Argon2id | `argon2-cffi` | Hash in DB, salt per-install |
| Audit chain integrity | SHA-256 | stdlib `hashlib` | Hash in DB |
| Node identity signing | Ed25519 | Python `cryptography` library | `~/.onto/federation/node.key` |
| Manifest signing | Ed25519 + JCS (RFC 8785) | stdlib `json` + `cryptography` | Same key file |
| Certificate fingerprint | SHA-256 | stdlib `hashlib` | Hash in DB only |
| Session tokens | 256-bit random | stdlib `secrets` | Memory only |

**Post-quantum status:**
- AES-256 and SHA-256: quantum-resistant at current security level
- Ed25519: quantum-vulnerable; ML-DSA (NIST FIPS 204) planned for Phase 4
- Argon2id: quantum-resistant (memory-hard)
- Full PQC migration plan: `docs/PQC_MIGRATION_PLAN.txt`

---

## Key Files for Audit

```
core/
  auth.py           — Argon2id passphrase hashing, lockout
  encryption.py     — AES-256-GCM, key derivation, session path
  session.py        — 256-bit tokens, rotation, connection binding
  verify.py         — Principle integrity checking at boot
  ratelimit.py      — Rate limiting for API endpoints
  config.py         — Environment variable configuration

api/
  main.py           — FastAPI HTTP server, 5 endpoints
  onto_server.py    — MCP server, 8 tools, Bearer auth
  federation/
    safety.py       — MOST CRITICAL: absolute barriers for crisis + PHI
    local.py        — LocalAdapter, HTTP transport, safety gate calls
    consent.py      — Consent ledger
    peer_store.py   — TOFU certificate pinning
    node_identity.py — Ed25519 keypair, key file management
    audit.py        — Rate limiting, sequence numbers, messaging tables
    manager.py      — FederationManager singleton, boot integration

modules/
  memory.py         — SQLite schema, Merkle chain, audit trail
  intake.py         — Input sanitization, classification, crisis detection
  graph.py          — Typed edge graph, PPR, crisis barrier (_contains_crisis)

tests/
  test_federation.py — Safety-critical TestAbsoluteBarriers class
  test_onto.py       — TestMerkleChainCore (tamper detection)
```

---

## Safety-Critical Code Paths

These paths have the highest consequence if bypassed. Prioritize:

**1. Crisis content barrier** (`modules/graph._contains_crisis`)
Called by: `intake.receive`, `api/federation/safety.check_absolute_barriers`,
`api/onto_server._is_crisis`. Must never be bypassable.

**2. Audit trail append-only** (`modules/memory.py`)
SQLite trigger prevents UPDATE/DELETE on `events` table.
`verify_chain()` detects gaps via Merkle chain.

**3. Session token rotation** (`core/session.py`)
Token invalidated on every authenticated request.
Previous token rejected immediately.

**4. Database key management** (`core/encryption.py`)
Key derived at boot from passphrase, cleared at shutdown.
Never written to disk.

**5. Federation safety gate** (`api/federation/safety.py`)
`check_absolute_barriers()` — crisis and classification 4+ blocks.
These must return False regardless of any configuration or peer request.

---

## Dependency Security

CI runs `pip-audit` on every push against `requirements-test.txt`.
Current status: zero known vulnerabilities.

Key deps and their roles:

| Package | Version | Purpose | Audit history |
|---------|---------|---------|---------------|
| `cryptography` | >=41.0 | AES-256-GCM, Ed25519 | Well-maintained; CVEs addressed promptly |
| `argon2-cffi` | >=21.3.0 | Argon2id key derivation | No known CVEs |
| `starlette` | >=0.45.3 | FastAPI dependency | Pinned to avoid GHSA-7f5h-v6xp-fcq8 |
| `fastapi` | >=0.115.0 | HTTP API framework | Active maintenance |
| `fastmcp` | >=2.0.0 | MCP server framework | Newer; warrants review |

---

## Known Limitations (Explicitly Accepted)

These are documented design decisions, not gaps:

1. **Federation transport is plain HTTP** (Phase 3). Full mTLS (gRPC)
   deferred to Phase 4. Operators are advised not to expose the
   federation port beyond the local network.

2. **Node identity key file uses filesystem permissions** (0600),
   not passphrase encryption. Passphrase-based key encryption is Phase 4.

3. **Standing consent without W3C VC** is a simplified record.
   Full W3C Verifiable Credentials are Phase 5.

4. **Ed25519 is quantum-vulnerable**. ML-DSA migration is planned
   for Phase 4 but not yet implemented.

5. **Single-node rate limiting** — the API rate limiter (`core/ratelimit.py`)
   operates per-process. No distributed rate limiting in Stage 1.

---

## Recommended Audit Focus Areas

Given the above, we suggest prioritizing:

1. **Safety gate bypasses** — Can `check_absolute_barriers()` return True
   for crisis content or classification 4+ data under any code path?

2. **Audit trail integrity** — Can the SQLite append-only trigger be
   circumvented? Does `verify_chain()` reliably detect all tampering?

3. **Session token security** — Can a stolen token be replayed?
   Is the rotation mechanism free of race conditions?

4. **Encryption correctness** — Is AES-256-GCM used correctly?
   Is the IV unique per encryption? Is the key cleared reliably?

5. **Input injection** — Are all SQLite queries parameterized?
   Is there any path from user input to SQL string concatenation?

6. **Federation trust model** — Can a malicious peer elevate its trust
   score above `ONTO_FED_INBOUND_TRUST` without human checkpoint?

7. **TOFU bypass** — Can a MITM on the LAN successfully impersonate
   a known peer after TOFU pinning?

---

## Running the System for Testing

```bash
# Clone and install
git clone https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System
cd ONTO-Ontological-Context-System
pip install -r requirements-test.txt

# Run tests (424 tests, all passing)
pytest tests/ -v

# Start the API server (development mode — no auth required)
AUTH_REQUIRED=false python main.py
# API docs: http://127.0.0.1:8000/docs

# Start with authentication
AUTH_REQUIRED=true ONTO_PASSPHRASE=yourpassphrase python main.py

# Run safety-critical tests only
pytest tests/test_federation.py::TestAbsoluteBarriers -v
pytest tests/test_federation.py::TestFederationSafetyFilter -v
```

---

## Contact for Questions

Open an issue on GitHub or contact the founder directly.
All security issues should be reported privately before public disclosure.
We follow coordinated disclosure with a 90-day window.

This document is part of the permanent record of ONTO.
It is honest about what is not yet done.
That is the only way trust is built.
