# ONTO Federation Specification 001
**Document ID:** FEDERATION-SPEC-001
**Version:** 1.1 (supersedes v1.0)
**Status:** LOCKED — Design precedes code.
**Authors:** Neo (bnyhil31-afk), Claude (Anthropic)
**Governs checklist items:** 9.01–9.12
**Rule 1.09A:** Code, tests, and documentation must agree with every
               decision recorded here before any checklist item is marked
               complete.

---

## Changes from v1.0 to v1.1

Seven issues identified in design review. All fixes are additive —
no architectural change to governing principle, adapter protocol,
absolute barriers, consent ledger, or CRDT assignments.

1. **Critical** — Private key storage moved out of SQLite to a separate
   encrypted key file. Key file path is configurable.
2. **Critical** — Conflict detection changed from timestamp proximity
   (fragile) to vector clock comparison (correct). 10ms threshold removed.
3. **Significant** — Inbound crisis detection now triggers `onto_checkpoint`
   instead of automatic trust demotion to 0.0.
4. **Significant** — `FederationManager` singleton added to package structure.
   Boot integration documented.
5. **Significant** — Outbox retry strategy changed to operator-initiated.
   Automatic retry removed. `failed_at` and `failure_reason` added.
6. **Significant** — TOFU certificate pinning documented. `peer_store.py`
   added to package structure. `federation_peer_certs` table specified.
7. **Design gap** — Rate limiting and message sequence numbers added to
   messaging architecture.

---

## Governing Principle: Addon, Not Integration

Federation is an optional addon to a complete, self-sufficient system.
An ONTO node without federation is not a degraded system. It is a fully
functional, production-ready system. Federation adds capability. It
never touches the core.

This produces one architectural rule:

**No file outside `api/federation/` is modified by Phase 3.**
The existing pipeline, graph layer, MCP interface, and session management
are untouched. Federation imports from core — core never imports from
federation.

The second rule:

**Federation is disabled by default. Every behavior is opt-in.**
An operator who installs the deps but never sets `ONTO_FEDERATION_ENABLED=true`
gets no federation. Nothing silently activates. No data leaves the device
without the operator explicitly enabling it and a user explicitly consenting.

---

## Part I — Risk Register

Every risk in this register shapes an architectural decision.
Code follows risk, not the other way around.

### 1.1 Legal Risks

| Risk | Trigger | Shield |
|------|---------|--------|
| GDPR Art 44 — cross-border transfer | Any data moving to a node in a different EEA jurisdiction | `data_residency` config per node; data never routes outside permitted region without explicit consent |
| GDPR Art 28 — processor relationship | Node A processing data on behalf of Node B's user | Inter-node agreement template required before any exchange; BAA equivalent |
| CCPA sharing | California-resident data shared with a third-party node | Opt-out mechanism present; all sharing logged |
| HIPAA BAA | PHI (classification 4+) crossing an org boundary | Classification 4+ never federates under any configuration |
| EU AI Act GPAI | ONTO as a federated AI system accessed by general-purpose AI | Capability manifest published per node; transparency obligations documented |

**Architectural response:** The `FederationAdapter` receives the data
classification of every piece of data before it is allowed to leave the
node. Classification 3+ triggers a checkpoint. Classification 4+ is a
hard block. Classification 5+ raises a CRITICAL audit event and halts
the operation.

### 1.2 Safety Risks

| Risk | Shield |
|------|--------|
| Crisis content crossing node boundaries | Absolute hard block in `can_share()` and `can_receive()`. Not configurable. Not bypassable. |
| Sensitive content reaching an untrusted node | is_sensitive=True requires peer trust_score >= ONTO_FED_SENSITIVE_TRUST_THRESHOLD (default 0.95) |
| Graph poisoning from a malicious node | All inbound data treated as source_type='derived', trust_score=ONTO_FED_INBOUND_TRUST (default 0.30). No automatic promotion without human checkpoint. |
| Inbound crisis content from a peer | `_contains_crisis()` run on every text field before processing. Payload rejected. `FEDERATION_CRISIS_RECEIVED` audit event. Operator notified via checkpoint — not automatic demotion. |
| Rumination amplification across nodes | Sensitive edges received from remote nodes receive SENSITIVE_REINFORCEMENT only |

### 1.3 Security Risks

| Risk | Shield |
|------|--------|
| Man-in-the-middle | mTLS — mutual TLS on every inter-node connection |
| Certificate impersonation | TOFU certificate pinning — first cert seen for a did:key is pinned; changes require operator checkpoint |
| Replay attack | Nonce + 30-second expiry (CRE-SPEC-001 §37.1) + sequence numbers |
| Sybil attack | Capability manifest signed by did:key; low-history nodes capped at lowest trust tier |
| Discovery poisoning | VoID descriptor validation; nodes must prove capability before receiving queries |
| Inbox flooding | Rate limit: ONTO_FED_MAX_MSGS_PER_PEER_PER_MIN=60; excess dropped and logged |
| Message ordering attack | Sequence numbers per sender; gaps trigger re-send request; unresolved gaps suspend connection |
| Audit trail gap | Every inter-node exchange generates COMMIT records on both nodes before data moves |
| Private key compromise | Key stored in separate encrypted file, never in SQLite; compromise affects identity only, not historical data |

### 1.4 Sovereignty Risks

| Risk | Shield |
|------|--------|
| User data shared without knowledge | Consent ledger: every share requires a consent record traceable to a human decision |
| User cannot recall shared data | `recall()` sends retraction to all peers; succeeds locally even if peers offline |
| Operator disables consent for convenience | Consent enforced at protocol level — no configuration disables it |
| Federation creates echo chamber | Anti-concentration routing: graph similarity monitored, operator notified |

---

## Part II — Package Structure

Phase 3 lives entirely in `api/federation/`. Nothing else changes.

```
api/
  federation/
    __init__.py      — Package init; graceful dep check; exposes FederationAdapter
    adapter.py       — FederationAdapter protocol definition
    manager.py       — FederationManager singleton; start/stop lifecycle (v1.1)
    local.py         — LocalAdapter: direct connection, no discovery
    intranet.py      — IntranetAdapter: mDNS discovery (zeroconf)
    node_identity.py — did:key generation, signing, verification
    peer_store.py    — TOFU certificate pinning; peer trust management (v1.1)
    capability.py    — Capability manifest: VoID descriptor + node metadata
    consent.py       — Consent ledger: record, verify, revoke
    crdt.py          — CRDT merge logic: OR-Set, LWW-Register, G-Set
    safety.py        — Absolute barriers + configurable safety controls
    audit.py         — Inter-node audit event coordination
    config.py        — All federation env vars in one place

tests/
  test_federation.py  — Phase 3 test suite
docs/
  FEDERATION-SPEC-001.md — This document
  FEDERATION.md          — Operator-facing documentation
```

### 2.1 Dependency Isolation

Federation deps are optional. If not installed, `api/federation/` imports
gracefully to no-ops using the same pattern as PPR and FastMCP:

```python
# api/federation/__init__.py
try:
    import zeroconf as _zeroconf    # type: ignore
    import crdts as _crdts          # type: ignore
    import grpcio as _grpcio        # type: ignore
    _FEDERATION_DEPS_AVAILABLE = True
except ImportError:
    _FEDERATION_DEPS_AVAILABLE = False
```

Note: `kademlia` is NOT imported in Phase 3 — it is a Phase 4 dependency
(internet-scale DHT). Phase 3 requires only zeroconf, crdts, grpcio.

Attempting to start federation without deps produces a clear error:
```
FederationDepsError: Federation requires: zeroconf, crdts, grpcio.
Run: pip install zeroconf crdts grpcio grpcio-tools
```

### 2.2 Configuration

Every federation behavior has an env var. Every env var has a safe default.
The safe default for every toggle is the most restrictive option.

```
# Master switch — disabled by default
ONTO_FEDERATION_ENABLED=false

# Deployment stage
# local    — direct connection only; no discovery; no network exposure
# intranet — mDNS discovery on local network (Phase 3 max)
# internet — Kademlia DHT (Phase 4)
# p2p      — full libp2p stack (Phase 5)
ONTO_FEDERATION_STAGE=local

# Private key file — NEVER stored in SQLite (v1.1)
# Path to the encrypted Ed25519 private key file.
# Created automatically on first federation start if absent.
ONTO_FED_KEY_PATH=~/.onto/federation/node.key

# Trust floor for ALL inbound data from federation
ONTO_FED_INBOUND_TRUST=0.30

# Trust required before sensitive content may be received from a peer
ONTO_FED_SENSITIVE_TRUST_THRESHOLD=0.95

# Maximum classification level that may leave this node
# 0 = public only, 1 = internal, 2 = personal (default)
ONTO_FED_MAX_SHARE_CLASSIFICATION=2

# Data residency — ISO 3166-1 alpha-2, comma-separated. Empty = no constraint.
ONTO_FED_DATA_RESIDENCY=

# Consent mode
# explicit — every share requires operator decision (default)
# session  — operator consents once per session per peer
# standing — standing consent record (simplified; not W3C VC until Phase 5)
ONTO_FED_CONSENT_MODE=explicit

# Anti-concentration: deprioritize connections if graph similarity exceeds this.
# 1.0 = disabled (default). 0.8 = warn if 80% concept overlap.
ONTO_FED_MAX_GRAPH_SIMILARITY=1.0

# Rate limiting per peer per minute (v1.1)
ONTO_FED_MAX_MSGS_PER_PEER_PER_MIN=60

# Consent standing re-confirmation interval in days (v1.1)
# Standing consents with no expiry require re-confirmation after this period.
ONTO_FED_STANDING_CONSENT_RECONFIRM_DAYS=90
```

### 2.3 FederationManager Boot Integration (v1.1)

`FederationManager` is a singleton analogous to `session_manager`.
`main.py` adds one conditional step at the end of the boot sequence:

```python
# main.py — Step 5 (conditional, no-op if federation disabled)
from api.federation.manager import federation_manager
if federation_manager.is_enabled():
    federation_manager.start()
    # Registers shutdown hook to call federation_manager.stop()
```

`federation_manager.is_enabled()` reads `ONTO_FEDERATION_ENABLED` and
checks that deps are available. Returns False if either condition fails.
The rest of `main.py` never changes.

---

## Part III — FederationAdapter Protocol

The protocol is the contract. Every federation behavior routes through it.
Any concern — legal, safety, security — is addressed by wrapping or replacing
the adapter. The rest of the codebase never changes.

```python
# api/federation/adapter.py
from typing import Any, Dict, List, Optional, Tuple, Protocol


class NodeInfo:
    """Everything known about a peer node."""
    node_id: str           # did:key identifier
    endpoint: str          # mTLS endpoint (host:port)
    trust_score: float     # accumulated trust score for this node
    capabilities: Dict     # VoID descriptor + capability manifest
    data_residency: str    # ISO country code(s) this node may hold
    last_seen: float       # epoch
    cert_hash: str         # SHA-256 of pinned TLS certificate (TOFU)


class FederationAdapter(Protocol):
    """
    The complete federation contract.

    Safety invariants encoded in the protocol (not in config):
      - can_share()   ALWAYS returns (False, reason) for crisis content
      - can_share()   ALWAYS returns (False, reason) for classification >= 4
      - can_receive() ALWAYS assigns trust_score <= ONTO_FED_INBOUND_TRUST
      - recall()      ALWAYS succeeds locally, even if peers are offline

    These are non-negotiable. A compliant implementation cannot violate them.
    """

    def start(self) -> None:
        """Start the federation layer. Idempotent."""
        ...

    def stop(self) -> None:
        """Stop the federation layer. Release all resources."""
        ...

    def discover(self) -> List[NodeInfo]:
        """
        Discover available peer nodes using this adapter's discovery protocol.
        Returns empty list if no peers found — never raises.
        """
        ...

    def handshake(self, peer: NodeInfo) -> bool:
        """
        Exchange capability manifests with a peer. Verify their identity
        and pin their certificate (TOFU). Returns True if handshake
        succeeded and peer is trustworthy. Writes FEDERATION_HANDSHAKE
        audit event on both nodes.
        """
        ...

    def verify_peer(self, peer: NodeInfo) -> Tuple[bool, str]:
        """
        Verify a peer's capability manifest signature against their did:key.
        Returns (valid, reason). Called before any data exchange.
        A peer with an invalid signature is rejected and logged.
        """
        ...

    def can_share(
        self,
        text: str,
        classification: int,
        is_sensitive: bool,
        is_crisis: bool,
        peer: NodeInfo,
        consent_id: str,
    ) -> Tuple[bool, str]:
        """
        Gate function. Called before any data leaves this node.
        Returns (allowed, reason).

        INVARIANTS (not configurable):
          is_crisis=True     → always (False, "crisis content never federates")
          classification >= 4 → always (False, "PHI/privileged never federates")

        Returns (False, reason) for:
          classification > ONTO_FED_MAX_SHARE_CLASSIFICATION
          is_sensitive=True and peer.trust_score < ONTO_FED_SENSITIVE_TRUST_THRESHOLD
          peer.data_residency not in permitted regions
          no valid consent record for consent_id
          peer cert changed since pinning (triggers checkpoint)
        """
        ...

    def can_receive(
        self,
        data: Dict[str, Any],
        peer: NodeInfo,
    ) -> Tuple[bool, float]:
        """
        Gate function. Called before any remote data enters this node.
        Runs _contains_crisis() on all text fields in data.
        Returns (allowed, assigned_trust_score).
        assigned_trust_score is always <= ONTO_FED_INBOUND_TRUST.
        The sender's claimed trust score is ignored entirely.
        Crisis content detected → (False, 0.0) + checkpoint triggered.
        """
        ...

    def share(
        self,
        data: Dict[str, Any],
        peer: NodeInfo,
        consent_id: str,
    ) -> Optional[str]:
        """
        Send data to a peer after can_share() gate passes.
        Returns the remote audit record ID on success, None on failure.
        Failure recorded in outbox with failed_at and failure_reason.
        Retry is operator-initiated, not automatic.
        Writes FEDERATION_SHARE audit events on both nodes.
        """
        ...

    def receive(
        self,
        raw_data: Dict[str, Any],
        peer: NodeInfo,
        sequence_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Receive data from a peer after can_receive() gate passes.
        Validates sequence_id — requests re-send if gap detected.
        Strips all trust claims from sender — assigns our own trust score.
        Writes FEDERATION_RECEIVE audit event.
        """
        ...

    def merge(
        self,
        local_state: Dict[str, Any],
        remote_state: Dict[str, Any],
        local_vclock: Dict[str, int],
        remote_vclock: Dict[str, int],
        peer: NodeInfo,
    ) -> Tuple[Dict[str, Any], Dict[str, int]]:
        """
        CRDT merge: combine local and remote graph state.
        Detects concurrent writes using vector clock comparison (v1.1).
        True conflicts (neither vclock dominates) escalated to checkpoint.
        Returns (merged_state, merged_vclock).
        Never raises — falls back to local state on error.
        """
        ...

    def recall(self, consent_id: str) -> List[str]:
        """
        Retract previously shared data. Sends retraction to all peers
        that received data under this consent_id.
        Returns list of peer node_ids that were notified.
        Succeeds locally first — sovereignty cannot be blocked by offline peers.
        Records FEDERATION_RECALL in audit trail.
        """
        ...

    def get_trust_score(self, peer_did: str) -> float:
        """
        Return the current accumulated trust score for a peer node.
        Returns 0.0 if peer is unknown.
        """
        ...

    def health(self) -> Dict[str, Any]:
        """Return federation health. Safe to call at any time. Never raises."""
        ...
```

---

## Part IV — Node Identity (9.01)

Identity uses `did:key` — W3C Decentralized Identifiers, key method.

**Why did:key:** Self-sovereign (no registry), cryptographically verifiable
(public key embedded in DID), portable (follows the node, not hardware),
AT Protocol compatible, generates immediately with no network call.

**Key format:** `did:key:z6Mk...` (Ed25519, base58-encoded)

### 4.1 Key Storage (v1.1 — corrected from v1.0)

The Ed25519 private key is **never stored in SQLite**.

**Storage location:** `ONTO_FED_KEY_PATH` (default `~/.onto/federation/node.key`)
- Encrypted with Argon2id key derived from the operator's passphrase
- Same encryption infrastructure as the main database key
- Separate file — compromise of the database does not expose the key
- The `did:key` (public key only) is stored in the `node_config` table

**Generation on first federation start:**
1. Generate Ed25519 keypair using `cryptography` library (already a dep)
2. Encrypt private key with Argon2id-derived key, write to key file
3. Store `did:key` (public) in `node_config` table
4. Write `FEDERATION_IDENTITY_CREATED` audit event

**Key backup guidance (operator docs):**
Back up `ONTO_FED_KEY_PATH`. If lost, the node identity is lost. A new
identity can be generated, but existing peer handshakes must be re-established
and peers will treat the new node as unknown (trust score reset to 0.0).

### 4.2 Key Rotation

Key rotation creates a new identity. The old identity is retired with a
signed retirement notice sent to all known peers. Old connections must
re-handshake. Rotation is an explicit, operator-initiated, audited action.
It is not automatic and is not done lightly.

### 4.3 Identity Is the Node, Not the Operator

If the operator changes, the node identity persists.
If the hardware changes but the database and key file are migrated, the identity
persists. This matches CRE-SPEC-001 §22.

---

## Part V — Capability Manifest (9.02)

Every node publishes a signed capability manifest. Signature is over the
canonical JSON representation using JCS (JSON Canonicalization Scheme,
RFC 8785) — not ad-hoc serialization.

```json
{
    "node_id":       "did:key:z6Mk...",
    "onto_version":  "1.0.0",
    "spec_version":  "FEDERATION-SPEC-001-v1.1",
    "signed_at":     "2026-04-02T12:00:00Z",
    "signature":     "<Ed25519 over JCS-canonical JSON, base64url>",

    "capabilities": {
        "federation_stage":     "intranet",
        "tools_available":      ["onto_ingest", "onto_query", "onto_surface"],
        "edge_types_supported": ["related-to", "co-occurs-with", "is-a"],
        "max_classification":   2,
        "crisis_barrier":       true,
        "consent_mode":         "explicit",
        "data_residency":       ["US"],
        "rate_limit_per_min":   60
    },

    "void_descriptor": {
        "triples":    12840,
        "classes":    ["foaf:Person", "schema:Event"],
        "predicates": ["related-to", "co-occurs-with"]
    },

    "regulatory_profile":   "general",
    "min_peer_trust_score": 0.70,
    "max_graph_similarity": 1.0
}
```

**Important:** `crisis_barrier: true` is a self-claimed field. Peers verify
the claim behaviourally — the absolute barrier in `can_receive()` runs
`_contains_crisis()` on all inbound text regardless of what the manifest
claims. A peer that claims `crisis_barrier: true` but sends crisis content
is flagged and the operator is notified via checkpoint.

Peers validate manifest signature before accepting any data.
An invalid signature is rejected silently — logging it would allow timing
attacks to enumerate nodes.

---

## Part VI — Discovery Architecture (9.03–9.04)

### 6.1 Stage-Gated Discovery

| Stage | Discovery | Network exposure | Phase |
|-------|-----------|-----------------|-------|
| local | None — operator provides peer endpoints manually | Zero | 3 |
| intranet | mDNS via python-zeroconf | LAN only | 3 |
| internet | Kademlia DHT | Internet | 4 |
| p2p | Full libp2p | Internet | 5 |

**Phase 3 delivers local and intranet stages only.**

Peer endpoints for the `local` stage are provided via config:
```
ONTO_FED_PEERS=did:key:z6MkAbc@192.168.1.10:7700,did:key:z6MkDef@192.168.1.11:7700
```

Format: `did:key@host:port`, comma-separated. Parsed at start, validated
against the peer's capability manifest during handshake.

### 6.2 Anti-Centralization by Design

Three rules, unchanged from v1.0:

1. No required bootstrap node. `local` and `intranet` work with zero
   network calls outside the LAN.
2. Discovery results are not trusted. Trust is established through
   handshake and accumulated interaction, never through discovery.
3. Anti-concentration routing: peers with high graph similarity to the local
   node are deprioritized. Mechanism present from day one; disabled by default.

### 6.3 mDNS Privacy Note

mDNS broadcasts ONTO node presence to all devices on the LAN.
Every device on the network can detect that an ONTO node is running.
For the intranet stage, this is acceptable and expected behavior.
Operators in adversarial network environments should use the `local`
stage with explicitly configured peers.

---

## Part VII — Consent Ledger (9.05)

### 7.1 Consent Record Schema

```sql
CREATE TABLE IF NOT EXISTS federation_consent (
    consent_id        TEXT    PRIMARY KEY,  -- UUID v4
    grantor_session   TEXT    NOT NULL,     -- SHA-256(session_token)
    recipient_node    TEXT    NOT NULL,     -- did:key of receiving node
    data_description  TEXT    NOT NULL,     -- human-readable; stored for audit
    data_concept_hash TEXT,                 -- SHA-256(sorted concept labels)
    classification    INTEGER NOT NULL,     -- max classification of shared data
    granted_at        REAL    NOT NULL,
    expires_at        REAL,                 -- NULL = no expiry (see below)
    last_reconfirmed  REAL,                 -- for standing consents (v1.1)
    revoked_at        REAL,
    revocation_reason TEXT,
    chain_hash        TEXT,                 -- Merkle chain integrity
    -- W3C VC forward-compatible (NULL until Phase 5)
    vc_id             TEXT,
    vc_issuer         TEXT,
    vc_proof          TEXT
);
```

### 7.2 Consent Expiry and Standing Consent (v1.1)

`expires_at = NULL` does not mean "never expires" in practice.
Standing consents (expires_at = NULL) require re-confirmation every
`ONTO_FED_STANDING_CONSENT_RECONFIRM_DAYS` days (default 90).

After 90 days without re-confirmation:
- The consent is still technically valid (not revoked)
- `onto_status` displays a standing consent warning
- The next share attempt under this consent triggers a re-confirmation
  checkpoint before proceeding

This prevents standing consents from silently persisting indefinitely.

### 7.3 Consent Lifecycle

```
GRANTED → ACTIVE → REVOKED (terminal)
             ↓
          EXPIRED (if expires_at reached)
             ↓
          NEEDS_RECONFIRMATION (if standing, after 90 days)
```

### 7.4 Consent Modes

**explicit (default):** Every share presents a checkpoint. Operator decides.
Decision is the consent record. No checkpoint → no share.

**session:** Operator consents once per session for a specific peer and
classification level. Session-scoped consent record reused within the session.

**standing:** Consent record with `expires_at=NULL` and human description.
Re-confirmation required after ONTO_FED_STANDING_CONSENT_RECONFIRM_DAYS.
Not legally equivalent to a W3C VC-based consent grant until Phase 5.
Clearly documented as such.

---

## Part VIII — CRDT Merge Logic (9.06)

### 8.1 CRDT Type Assignments

| Data structure | CRDT type | Rationale |
|----------------|-----------|-----------|
| graph_nodes (existence) | OR-Set | Add-wins; formally proven convergent (Shapiro 2011) |
| graph_edges (weight) | LWW-Register | Scalars; timestamp tiebreaker when vclocks equal |
| graph_edges (typed relationships) | LWW-Map | OR-Set key management + LWW values |
| audit trail records | G-Set | Grow-only; perfectly matches append-only design |
| consent records | G-Set + tombstone | Revocations as tombstones |
| ppmi_counters | PN-Counter | Positive-negative for marginal counts |
| edge_type registry | G-Set | Vocabulary is append-only |

### 8.2 Conflict Resolution via Vector Clocks (v1.1)

Conflict detection uses vector clock comparison — not timestamp proximity.

```
Two writes W_a and W_b are:
  Causally ordered: vclock_a ≤ vclock_b or vclock_b ≤ vclock_a
                    (one happened-before the other)
  Concurrent:       neither dominates the other
                    (true conflict requiring human resolution)

vclock_a dominates vclock_b when:
  all(vclock_a[node] >= vclock_b[node] for node in both) AND
  any(vclock_a[node] >  vclock_b[node] for node in both)

True tie: vclock_a == vclock_b
  (identical causal history — use timestamp as tiebreaker only here)
```

**On concurrent writes:** The conflict is escalated to `onto_checkpoint`.
The operator sees both versions and makes the decision. Both are in the
audit trail regardless of which is chosen. This matches ONTO's core
principle: consequential decisions belong to humans.

**Timestamp is only a tiebreaker** for the true-tie case (identical vector
clocks). It is never used as a proxy for causality.

**NTP note:** Nodes in the intranet stage should have NTP enabled, but the
system does not require it. Vector clocks provide correct causality detection
independent of clock synchronization.

### 8.3 PPMI Counter Deduplication

The PN-Counter for ppmi_counters requires deduplication. If Node A and Node B
both process the same document via different paths, we would double-count.

**Mitigation:** Every relate() call that originates from federation is tagged
with the `provenance_id` of the originating node. On merge, counter increments
tagged with an already-seen `(provenance_id, edge_id)` pair are deduplicated.
A `ppmi_seen_pairs` table records seen pairs (G-Set semantics).

---

## Part IX — Messaging Architecture (9.07)

### 9.1 Inbox/Outbox Tables

```sql
CREATE TABLE IF NOT EXISTS federation_outbox (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient      TEXT    NOT NULL,    -- did:key of recipient node
    message_type   TEXT    NOT NULL,    -- SHARE | RETRACT | HANDSHAKE | PING
    sequence_id    INTEGER NOT NULL,    -- per-recipient sequence counter (v1.1)
    payload_hash   TEXT    NOT NULL,    -- SHA-256 of payload
    sent_at        REAL,                -- NULL = pending
    acked_at       REAL,                -- NULL = not acknowledged
    failed_at      REAL,                -- NULL = not failed (v1.1)
    failure_reason TEXT,                -- NULL = not failed (v1.1)
    created_at     REAL    NOT NULL
    -- Note: no max_retries — retry is operator-initiated (v1.1)
);

CREATE TABLE IF NOT EXISTS federation_inbox (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sender         TEXT    NOT NULL,    -- did:key of sending node
    message_type   TEXT    NOT NULL,
    sequence_id    INTEGER NOT NULL,    -- sender's sequence counter (v1.1)
    payload_hash   TEXT    NOT NULL,
    received_at    REAL    NOT NULL,
    processed_at   REAL,
    rejected       INTEGER NOT NULL DEFAULT 0,
    reject_reason  TEXT
);
```

Payloads are never stored in the outbox or inbox — only their hashes.
Payloads are transmitted inline and discarded after processing.

### 9.2 Message Types

| Type | Direction | Payload | Consent required |
|------|-----------|---------|-----------------|
| HANDSHAKE | bidirectional | Capability manifest | No |
| PING | bidirectional | Node health | No |
| SHARE | outbound | Normalized graph delta | Yes |
| RETRACT | outbound | consent_id list | No (revocation) |
| MERGE_REQUEST | bidirectional | Vector clock state | No |
| AUDIT_SYNC | bidirectional | G-Set delta | No |

### 9.3 Retry Policy (v1.1)

**Automatic retry is removed.** Reasons:
1. Consent scope ambiguity — was consent granted for one attempt or unlimited?
2. Replay attack surface — retried payloads extend the replay window
3. For intranet stage, delivery failures are rare

**Failed delivery behavior:**
1. Write to outbox: `failed_at=now, failure_reason="<error>"`
2. Write `FEDERATION_SEND_FAILED` audit event
3. Surface in `onto_status` federation health block
4. Operator re-initiates the share explicitly

### 9.4 Sequence Numbers and Ordering (v1.1)

Every sender maintains a monotonic `sequence_id` per recipient.
Every receiver validates the incoming sequence_id:

```
expected_seq = last_received_seq_from_sender + 1
if incoming_seq == expected_seq: process normally
if incoming_seq >  expected_seq: gap detected — request re-send
if incoming_seq <  expected_seq: duplicate — discard silently
```

Gap resolution:
1. Request re-send of missing sequence IDs from sender
2. If not resolved after 3 requests: write `FEDERATION_SEQUENCE_GAP` audit event
3. Suspend connection pending operator review (not automatic disconnect)

### 9.5 Rate Limiting (v1.1)

Per-peer rate limit: `ONTO_FED_MAX_MSGS_PER_PEER_PER_MIN=60` (default).

Messages from a peer exceeding this rate:
1. Dropped silently (no error response — avoids amplification attacks)
2. Rate limit event logged internally
3. Peer enters exponential backoff (1min → 2min → 4min → 8min max)
4. After 3 consecutive backoff cycles: `FEDERATION_RATE_LIMIT_EXCEEDED` audit
   event and operator notification

---

## Part X — mTLS Security Layer (9.09)

### 10.1 Certificate Architecture

Each node generates a self-signed certificate at federation startup.
Certificates are short-lived (default 7 days) and renewed proactively
at 50% of their lifetime (day 3.5 for 7-day certs), not reactively.

```
Certificate lifecycle:
  Generate → Active → Renewed (rolling at 50% lifetime) → Expired (refused)
                ↓
            Revoked (emergency — FEDERATION_CERT_REVOKED audit event)
```

**Why short-lived over revocation lists:** In a P2P setting, distributing CRL
or OCSP responses is complex. Short-lived certificates avoid the revocation
problem: an expired certificate is simply invalid.

### 10.2 TOFU Certificate Pinning (v1.1)

Trust On First Use (TOFU) is the trust model for intranet deployments.

The first certificate presented by a node's `did:key` is pinned in
`federation_peer_certs`. On subsequent connections, the certificate hash
must match the pinned value.

A certificate change requires:
1. New handshake with operator present
2. Manual confirmation via `onto_checkpoint`
3. `FEDERATION_CERT_CHANGED` audit event on both nodes
4. Rotation count incremented in `federation_peer_certs`

```sql
CREATE TABLE IF NOT EXISTS federation_peer_certs (
    peer_did        TEXT    PRIMARY KEY,
    cert_hash       TEXT    NOT NULL,    -- SHA-256 of pinned TLS certificate
    pinned_at       REAL    NOT NULL,
    pinned_by       TEXT    NOT NULL,    -- SHA-256(session_token) of approver
    last_seen       REAL,
    rotation_count  INTEGER NOT NULL DEFAULT 0
);
```

### 10.3 Trust Hierarchy

```
Phase 3 (intranet):
    Self-signed certs + TOFU pinning + mDNS-discovered peers
    → Trust via handshake + capability manifest signature

Phase 4 (internet, future):
    ACME-issued certs (Let's Encrypt)
    → Trust via CA chain + DID verification

Phase 5 (enterprise, future):
    Enterprise PKI integration
    → Trust via organizational CA
```

The `FederationAdapter` interface is identical at all tiers.
The implementation swaps underneath. Core code never changes.

---

## Part XI — Anti-Concentration Routing (9.10)

### 11.1 Graph Similarity Metric

```
graph_similarity(local, peer) =
    |local_concepts ∩ peer_concepts| / |local_concepts ∪ peer_concepts|
```

Computed from the VoID descriptor in the peer's capability manifest.
No database query required on either side — the manifest carries the data.

If `graph_similarity > ONTO_FED_MAX_GRAPH_SIMILARITY` (default 1.0,
disabled): peer is deprioritized in routing and operator notified.
This is a soft control. The operator makes the final decision.

### 11.2 Network Topology in onto_status

The `onto_status` MCP resource (Phase 2) is extended in Phase 3:

```json
"federation": {
    "enabled":                  true,
    "stage":                    "intranet",
    "peer_count":               3,
    "active_connections":       2,
    "avg_graph_similarity":     0.42,
    "concentration_warning":    false,
    "data_residency_violations": 0,
    "standing_consents_due":    1,
    "failed_sends":             0,
    "rate_limited_peers":       []
}
```

---

## Part XII — Safety Filter at the Network Boundary

This is the most important section. Everything else can be configured or
relaxed. This cannot.

### 12.1 The Absolute Barriers

Implemented in `api/federation/safety.py`. These checks run in both
`can_share()` and `can_receive()`. They are not configurable.
They cannot be bypassed by configuration, code, or peer request.

```python
# api/federation/safety.py

from modules.graph import _contains_crisis
from typing import Any, Dict, Tuple


def check_absolute_barriers(
    text: str,
    classification: int,
    is_sensitive: bool,
    is_crisis: bool,
) -> Tuple[bool, str]:
    """
    Run all absolute barriers in sequence.
    Returns (allowed, reason). Returns (False, reason) on first failure.
    These checks are called before any configurable safety checks.
    Order matters — crisis is checked first.
    """
    if is_crisis or _contains_crisis(text):
        return False, "crisis content never federates"

    if classification >= 4:
        return False, "classification 4+ (PHI/privileged) never federates"

    return True, "passed"


def check_inbound_for_crisis(data: Dict[str, Any]) -> bool:
    """
    Run _contains_crisis() on every string-valued field in the received data.
    Returns True if crisis content found in any field.
    Called by can_receive() regardless of what the sender's manifest claims.
    """
    for value in _walk_strings(data):
        if _contains_crisis(value):
            return True
    return False


def _walk_strings(data: Any):
    """Recursively yield all string values from a nested dict/list."""
    if isinstance(data, str):
        yield data
    elif isinstance(data, dict):
        for v in data.values():
            yield from _walk_strings(v)
    elif isinstance(data, list):
        for item in data:
            yield from _walk_strings(item)
```

### 12.2 Inbound Crisis Detection — Checkpoint, Not Auto-Demotion (v1.1)

When `check_inbound_for_crisis()` returns True for received data:

1. Payload is rejected
2. `FEDERATION_CRISIS_RECEIVED` audit event written
3. Peer's trust score drops to `ONTO_FED_INBOUND_TRUST` (not 0.0)
4. `onto_checkpoint` is triggered — operator sees:
   *"Peer node [did] sent content flagged as crisis content. Decide:
   investigate | warn_peer | disconnect."*
5. Operator decision is recorded permanently in audit trail
6. Auto-demotion to 0.0 does NOT happen without operator confirmation

This mirrors ONTO's core principle: consequential decisions belong to humans.
A legitimate node could accidentally relay crisis content from a user.
Automatic disconnection without human review would be disproportionate.

### 12.3 Configurable Safety Controls

Defaults are maximally restrictive:

| Control | Env var | Default | Effect |
|---------|---------|---------|--------|
| Sensitive sharing threshold | ONTO_FED_SENSITIVE_TRUST_THRESHOLD | 0.95 | Required peer trust for sensitive data |
| Max outbound classification | ONTO_FED_MAX_SHARE_CLASSIFICATION | 2 | Ceiling for outbound data |
| Inbound trust floor | ONTO_FED_INBOUND_TRUST | 0.30 | Trust assigned to all inbound |
| Consent mode | ONTO_FED_CONSENT_MODE | explicit | How consent is obtained |
| Rate limit | ONTO_FED_MAX_MSGS_PER_PEER_PER_MIN | 60 | Per-peer message rate |

---

## Part XIII — Test Coverage Requirements (Rule 1.09A)

Safety-critical tests are marked ⚠️. They block deployment if they fail,
even if all other tests pass.

| Test class | Covers |
|------------|--------|
| ⚠️ TestAbsoluteBarriers | crisis=True → False always; classification 4+ → False always; check_inbound_for_crisis runs on all string fields |
| ⚠️ TestFederationSafetyFilter | All absolute barriers; all configurable controls; inbound crisis triggers checkpoint not auto-demotion |
| TestNodeIdentity | did:key generation; key stored in file not SQLite; signing; verification; persistence across restarts |
| TestCapabilityManifest | Manifest creation; JCS signing; signature validation; rejection of invalid/tampered manifests |
| TestConsentLedger | Grant; revoke; expire; standing re-confirmation after 90 days; W3C VC fields present |
| TestPeerStore | TOFU pinning; cert change triggers checkpoint; rotation_count increments |
| TestCRDTMerge | OR-Set node merge; LWW-Register edge weight; G-Set audit; vector clock concurrent detection; conflict escalation |
| TestVectorClocks | Dominance detection; concurrent detection; true-tie fallback to timestamp |
| TestLocalAdapter | Connect; handshake; verify_peer; can_share; can_receive; share; receive; recall; health |
| TestIntranetAdapter | mDNS discovery; handshake with mTLS; full share/receive cycle; TOFU enforcement |
| TestFederationManager | is_enabled(); start/stop lifecycle; graceful no-op when deps absent |
| TestMessaging | Sequence numbers; gap detection; rate limiting; retry is operator-initiated |
| TestMigration | All federation tables created; existing Phase 1/2 schema unchanged |
| TestConcentrationDetection | Graph similarity computation; soft warning at threshold |
| TestAuditIntegrity | Every federation operation writes audit events on both nodes |
| TestOfflineSovereignty | recall() succeeds locally when peer is unreachable |

---

## Part XIV — Open Questions (Answers Required Before Coding)

1. **Phase 3 scope: local only, or local + intranet?**
   *Recommendation: both in Phase 3. intranet is the main use case.*

2. **Default ONTO_FED_MAX_SHARE_CLASSIFICATION: 2 (personal) or 1 (internal)?**
   *Recommendation: 2, with prominent documentation that regulated-domain
   operators should lower to 1 or 0 pending legal review.*

3. **Standing consent without W3C VC: acceptable in Phase 3?**
   *Recommendation: yes, clearly documented as simplified record, not a
   legally equivalent VC grant until Phase 5.*

4. **Certificate authority model for intranet: self-signed per node?**
   *Recommendation: yes (Option A) for Phase 3. Each node is its own CA.
   Option B (one node as cluster CA) designed but not implemented.*

5. **ONTO_FED_MAX_GRAPH_SIMILARITY: active by default (0.8) or opt-in (1.0)?**
   *Recommendation: 1.0 (opt-in). Mechanism present; behavior not forced.*

---

## Summary — What Phase 3 Delivers

At the end of Phase 3, an ONTO operator can:

1. Enable federation with a single env var (`ONTO_FEDERATION_ENABLED=true`).
2. Configure peer endpoints manually (`local` stage) or discover automatically
   via mDNS (`intranet` stage).
3. Establish cryptographically verified, mTLS-secured, TOFU-pinned connections.
4. Share graph context with explicit consent — only below the classification
   ceiling, only to permitted regions.
5. Receive context from peers — automatically low trust, never promoted without
   human checkpoint.
6. Recall any share — retraction sent to all peers; succeeds locally even if
   peers are offline.
7. Monitor network health, similarity, rate limits, and concentration.
8. Trust that crisis content, PHI, and privileged data never cross node
   boundaries under any configuration or adversarial condition.
9. Trust that every consequential decision is a human decision.

What Phase 3 does NOT deliver (reserved for later phases):

- Internet-scale discovery (Kademlia DHT) — Phase 4
- Full libp2p stack — Phase 5
- W3C Verifiable Credentials for consent — Phase 5
- Enterprise PKI / HSM integration — Phase 5
- Differential privacy for aggregate outputs — Phase 4+
- Embedded SPARQL endpoint — Phase 5

---

*This document is part of the permanent record of ONTO.*
*Code follows design. Never the reverse.*
*Let's explore together.*
