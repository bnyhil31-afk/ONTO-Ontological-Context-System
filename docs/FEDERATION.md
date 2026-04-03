# ONTO Federation — Operator Guide

**Document ID:** FEDERATION-001  
**Version:** 1.0  
**Covers:** Phase 3 — Local and Intranet stages  
**Spec:** `docs/FEDERATION-SPEC-001.md`

---

## What federation does

Federation lets multiple ONTO nodes share graph context while each
node maintains complete sovereignty over its own data. Each operator
controls exactly what leaves their node, to whom, and for how long.
No data moves without explicit consent.

Federation is an optional addon. An ONTO node without federation is
fully functional. Enabling federation adds capability — it changes
nothing about the existing pipeline, graph, or MCP interface.

---

## Before you start

**Federation is disabled by default.** Nothing activates automatically.

Before enabling federation you should:
- Complete the Stage 1 security review (`docs/THREAT_MODEL_001.txt`)
- Consult legal counsel if sharing data across organizational boundaries
- Review the compliance mapping (`docs/REGULATORY-MAP-002.md`) for your context
- Understand the data classification levels your node handles

---

## Quick start

**Step 1 — Install dependencies**

```bash
pip install zeroconf grpcio grpcio-tools
```

**Step 2 — Enable federation**

```bash
export ONTO_FEDERATION_ENABLED=true
export ONTO_FEDERATION_STAGE=intranet   # or: local
```

**Step 3 — Start ONTO**

```bash
python main.py
```

Federation starts automatically when `ONTO_FEDERATION_ENABLED=true`.
The node generates a cryptographic identity on first start and saves it
to `~/.onto/federation/node.key`.

---

## Deployment stages

### `local` — Direct connection (no discovery)

Peers are configured manually. No network broadcasting. No mDNS.
Use this when you want full control over which nodes connect.

```bash
ONTO_FEDERATION_STAGE=local
ONTO_FED_PEERS=did:key:z6MkAbc...@192.168.1.10:7700,did:key:z6MkDef...@192.168.1.11:7700
```

**Network exposure:** Zero beyond the configured peers.

### `intranet` — Automatic LAN discovery

Nodes find each other automatically on the local network via mDNS.
No configuration of peer endpoints required.

```bash
ONTO_FEDERATION_STAGE=intranet
```

**Network exposure:** LAN only. The node advertises its presence to all
devices on the local network. Every LAN device can see that an ONTO node
is running. Use `local` stage if this is a concern.

---

## Configuration reference

All settings use environment variables with safe defaults.
The default for every toggle is the most restrictive option.

| Variable | Default | Description |
|----------|---------|-------------|
| `ONTO_FEDERATION_ENABLED` | `false` | Master switch |
| `ONTO_FEDERATION_STAGE` | `local` | Discovery protocol (`local` or `intranet`) |
| `ONTO_FED_KEY_PATH` | `~/.onto/federation/node.key` | Private key file |
| `ONTO_FED_HOST` | `127.0.0.1` | Federation server bind address |
| `ONTO_FED_PORT` | `7700` | Federation server port |
| `ONTO_FED_PEERS` | _(empty)_ | Static peer list (`did:key@host:port,...`) |
| `ONTO_FED_INBOUND_TRUST` | `0.30` | Trust assigned to ALL inbound data |
| `ONTO_FED_SENSITIVE_TRUST_THRESHOLD` | `0.95` | Trust required to share sensitive content |
| `ONTO_FED_MAX_SHARE_CLASSIFICATION` | `2` | Max data classification that may leave this node |
| `ONTO_FED_DATA_RESIDENCY` | _(empty)_ | ISO country codes data may route to (`US,CA`) |
| `ONTO_FED_CONSENT_MODE` | `explicit` | How consent is obtained |
| `ONTO_FED_MAX_GRAPH_SIMILARITY` | `1.0` | Anti-echo-chamber threshold (1.0 = disabled) |
| `ONTO_FED_MAX_MSGS_PER_PEER_PER_MIN` | `60` | Rate limit per peer |
| `ONTO_FED_STANDING_CONSENT_RECONFIRM_DAYS` | `90` | Days before standing consent needs reconfirmation |
| `ONTO_FED_CERT_LIFETIME_DAYS` | `7` | TLS certificate lifetime |

---

## Data classification ceilings

`ONTO_FED_MAX_SHARE_CLASSIFICATION` controls what can leave your node.
The two absolute barriers cannot be overridden by any configuration:

| Level | Label | Default behavior |
|-------|-------|-----------------|
| 0 | Public | Shareable |
| 1 | Internal | Shareable |
| 2 | Personal | Shareable (default ceiling) |
| 3 | Sensitive | **Never shares** (above default ceiling) |
| 4 | PHI / Privileged | **Never shares** — absolute barrier |
| 5 | Critical | **Never shares** — absolute barrier |

**Crisis content never shares regardless of classification level.**
This is a protocol invariant. No configuration can change it.

---

## Consent

Every share operation requires a consent record. Three modes:

**`explicit` (default):** Each share presents an `onto_checkpoint` request.
The operator's decision is the consent record. No decision → no share.

**`session`:** Operator consents once per session for a specific peer
and classification level.

**`standing`:** A standing consent record authorizes repeated sharing
without per-share checkpoints. Requires re-confirmation every
`ONTO_FED_STANDING_CONSENT_RECONFIRM_DAYS` days (default 90).
This is a simplified record — not a W3C Verifiable Credential until Phase 5.

### Revoking consent

Use the `onto_checkpoint` MCP tool with the consent_id to revoke.
The local record is revoked first — your data sovereignty is never
contingent on the peer being reachable. ONTO then sends a retraction
notice to the peer on a best-effort basis.

---

## Trust scores

All inbound data is assigned `ONTO_FED_INBOUND_TRUST` (default 0.30)
regardless of the sender's claimed trust. Trust is earned locally
through accumulated successful interaction, not asserted remotely.

Trust accumulates logarithmically — early interactions matter more.
The cap is 0.95 without manual verification. Only human-verified nodes
reach higher trust levels.

Sensitive content (`is_sensitive=True`) requires the peer's trust score
to be at or above `ONTO_FED_SENSITIVE_TRUST_THRESHOLD` (default 0.95)
before it can be shared. This means sensitive content only flows between
manually verified nodes.

---

## Your node's identity

On first federation start, ONTO generates an Ed25519 keypair:

- **Private key:** `~/.onto/federation/node.key` (permissions 0600)
- **Public key (DID):** stored in the database as your `did:key`

**Back up your key file.** If lost, your node identity is lost. A new
identity can be generated, but all peer relationships must be
re-established from scratch.

Your `did:key` is safe to share — it is your node's public identifier.
The private key file must never be shared.

---

## Certificate pinning

When your node first connects to a peer, their TLS certificate is
pinned locally (Trust On First Use — TOFU). Subsequent connections
must present the same certificate.

If a peer's certificate changes, the connection is suspended and an
`onto_checkpoint` is raised for your review. You choose:
`investigate | approve_change | disconnect`.

This protects against man-in-the-middle attacks on the local network.

---

## Health monitoring

The `onto_status` MCP resource includes a `federation` block when
federation is active:

```json
"federation": {
    "enabled":               true,
    "stage":                 "intranet",
    "node_did":              "did:key:z6Mk...",
    "peer_count":            3,
    "active_connections":    2,
    "standing_consents_due": 1,
    "outbox_pending":        0,
    "outbox_failed":         0,
    "rate_limited_peers":    []
}
```

`standing_consents_due` — the number of standing consents overdue for
re-confirmation. These are not revoked, but the next share under them
will trigger a re-confirmation checkpoint.

`outbox_failed` — sends that failed. Retry is operator-initiated.
Use the audit trail (`onto_audit` MCP resource) to inspect failures.

---

## Regulated environments

If your deployment handles health, financial, legal, or education data:

1. **Lower the classification ceiling:**
   `ONTO_FED_MAX_SHARE_CLASSIFICATION=0` (public only) or `1` (internal)
   until legal review is complete.

2. **Set data residency constraints:**
   `ONTO_FED_DATA_RESIDENCY=US` (or your applicable jurisdiction)

3. **Use explicit consent mode** (the default) for all sharing.

4. **Engage legal counsel** before federating across organizational
   boundaries. Item 4.01 in the pre-launch checklist covers this.

5. **HIPAA:** Classification 4+ data never federates under any
   configuration — this is a protocol invariant, not a setting.

---

## Troubleshooting

**Federation won't start:**
Run `python -c "from api.federation import get_deps_status; print(get_deps_status())"`.
Any `False` value indicates a missing dependency.

**Peers not discovered (intranet stage):**
Check that all nodes are on the same LAN subnet. mDNS does not cross
subnet boundaries. Use `local` stage with explicit `ONTO_FED_PEERS`
for cross-subnet scenarios.

**`outbox_failed` is growing:**
A peer may be offline or unreachable. Check the audit trail for failure
reasons. Retry is operator-initiated — ONTO does not automatically
retry failed sends.

**Standing consent warning in onto_status:**
Re-confirm via `onto_checkpoint`. The consent remains valid until
you act; the warning is a reminder, not a block.

---

## What Phase 3 does NOT include

These are reserved for later phases:

- Internet-scale discovery (Kademlia DHT) — Phase 4
- W3C Verifiable Credentials for consent — Phase 5
- Enterprise PKI / HSM key storage — Phase 5
- Full gRPC + mTLS transport (current transport is plain HTTP) — Phase 4
- Differential privacy for aggregate outputs — Phase 4+

---

*This document is part of the permanent record of ONTO.*  
*Federation is opt-in. Sovereignty is permanent.*
