# ONTO MCP Interface

**Document ID:** MCP-001
**Version:** 1.0
**Status:** Active
**Covers checklist items:** 8.01–8.14
**Server file:** `api/onto_server.py`

---

## Overview

ONTO exposes its ontological reasoning layer as an MCP server via FastMCP 3.x.
AI systems (Claude, GPT, and others) can traverse, reason over, and act upon
ONTO's knowledge graph through this interface.

The MCP layer sits on top of the existing pipeline — it calls `graph.relate()`,
`contextualize.build()`, `surface.build()`, and `memory.record()` directly.
Nothing in the existing code was modified. The HTTP API (`api/main.py`) is
untouched and continues to operate independently.

---

## Running the Server

```bash
pip install fastmcp>=2.0.0
fastmcp run api/onto_server.py
```

Or programmatically:

```python
from api.onto_server import get_server
server = get_server()
server.run()
```

Requires Python 3.10+. On Python 3.9, all MCP tests skip gracefully.

---

## Authentication

All tools (except Resources) require a valid ONTO session token.

**Header:** `Authorization: Bearer <session-token>`

Stage 1: the token is ONTO's existing 256-bit session token from `core/session.py`.
Stage 2: OAuth 2.1 + PKCE replaces validation — the header format is identical,
so clients need zero changes to upgrade.

Obtain a session token via `POST /auth` on the existing HTTP API
(`api/main.py`), then pass it to MCP tools as the `authorization` argument.

---

## Response Envelope

Every tool returns the same structure. Clients can always parse the same shape.

```json
{
    "status":              "ok | error | pending_checkpoint | degraded | crisis",
    "data":                {},
    "audit_id":            1234,
    "confidence":          0.85,
    "warnings":            [],
    "checkpoint_required": false,
    "checkpoint_context":  null,
    "schema_version":      "1.0"
}
```

`schema_version` is present from day one so clients can negotiate gracefully
when the envelope evolves.

**Status values:**

| status              | meaning                                                     |
|---------------------|-------------------------------------------------------------|
| `ok`                | Success. `data` contains the result.                        |
| `error`             | Failure. `data.message` explains why.                       |
| `pending_checkpoint`| Human decision required. See `checkpoint_context`.         |
| `crisis`            | Crisis content detected. `data` contains safe messaging.    |
| `degraded`          | Partial success. `warnings` describe what was affected.     |

---

## Tools

### `onto_ingest`

Feed text through ONTO's full 5-step pipeline.

**Arguments:**

| Argument        | Type   | Required | Default   | Description                              |
|-----------------|--------|----------|-----------|------------------------------------------|
| `text`          | string | yes      | —         | Input text to ingest                     |
| `authorization` | string | yes      | —         | Bearer token                             |
| `source_type`   | string | no       | `"human"` | Provenance type: human/sensor/llm/derived/system |
| `domain`        | string | no       | null      | Optional domain tag for ingested concepts |

**Returns (`data`):**

```json
{
    "concepts":           ["knowledge", "graph", "reasoning"],
    "nodes_created":      3,
    "nodes_reinforced":   0,
    "edges_created":      3,
    "edges_reinforced":   0,
    "sensitive_detected": false,
    "provenance_id":      42,
    "confidence":         0.5
}
```

**Crisis handling:** If the input triggers a crisis signal, the tool returns
`status="crisis"` immediately without writing anything to the graph. The crisis
response text and resources are in `data`. This cannot be disabled.

---

### `onto_query`

PPR traversal from seed concepts. Returns a ranked subgraph.

**Arguments:**

| Argument           | Type         | Required | Default | Description                              |
|--------------------|--------------|----------|---------|------------------------------------------|
| `concepts`         | list[string] | yes      | —       | Seed concept labels                      |
| `authorization`    | string       | yes      | —       | Bearer token                             |
| `alpha`            | float        | no       | `0.85`  | PPR teleport probability [0.70, 0.95]    |
| `top_k`            | int          | no       | `50`    | Maximum nodes to return                  |
| `edge_type_names`  | list[string] | no       | null    | Filter to these edge type names          |

**Returns (`data`):**

```json
{
    "nodes": [{"id": 1, "label": "machine learning", "score": 0.42, ...}],
    "edges": [{"source": 1, "target": 2, "type": "related-to", "weight": 0.8}],
    "metadata": {"seed_concepts": [...], "alpha": 0.85, "hardware_tier": "laptop"}
}
```

**Safety:** Sensitive nodes (`is_sensitive=True`) are automatically excluded
from results and listed in `warnings`. Use `onto_checkpoint` to authorize
access to sensitive content.

**Alpha guidance:** Higher alpha = more local (stays near seeds).
Lower alpha = more global (explores the broader graph).

- `0.80` — surface/presentation (local neighborhood)
- `0.85` — general context (default)
- `0.90` — memory/discovery (structural importance)

---

### `onto_surface`

Return ONTO's epistemic state for text. Read-only — does not write to the graph.

**Arguments:**

| Argument             | Type   | Required | Default | Description                         |
|----------------------|--------|----------|---------|-------------------------------------|
| `text`               | string | yes      | —       | Query text                          |
| `authorization`      | string | yes      | —       | Bearer token                        |
| `include_reasoning`  | bool   | no       | `true`  | Include full reasoning trace        |

**Returns (`data`):**

```json
{
    "confidence":         0.72,
    "weight":             0.65,
    "related_context":    [...],
    "sensitive_detected": false,
    "classification":     0,
    "reasoning":          "Context summary...",
    "display":            "Formatted display string..."
}
```

The surface layer is epistemically honest by design. It presents accurate data
with visible reasoning paths, not conclusions. It never flatters. It flags
uncertainty explicitly. This is architectural, not cosmetic.

---

### `onto_checkpoint`

Human sovereignty gate. The boundary between AI autonomy and human decision.

This is the most security-sensitive tool. No irreversible action is ever taken
without a confirmed human decision. Requires two-person review before any
production deployment.

**Two-step flow:**

**Step 1 — Request checkpoint (no `human_decision`):**

```python
onto_checkpoint(
    authorization=token,
    context_summary="Should we delete the user's graph?",
    proposed_action="delete_graph",
)
# Returns: status="pending_checkpoint"
# Present checkpoint_context to the human for review.
```

**Step 2 — Submit decision (`human_decision` provided):**

```python
onto_checkpoint(
    authorization=token,
    context_summary="Should we delete the user's graph?",
    proposed_action="delete_graph",
    human_decision="proceed",  # or: veto | flag | defer
)
# Returns: status="ok", data.authorized=True/False
```

**Arguments:**

| Argument              | Type   | Required | Default | Description                         |
|-----------------------|--------|----------|---------|-------------------------------------|
| `authorization`       | string | yes      | —       | Bearer token                        |
| `context_summary`     | string | yes      | —       | Plain-language description          |
| `proposed_action`     | string | yes      | —       | What the system proposes to do      |
| `human_decision`      | string | no       | null    | One of: proceed, veto, flag, defer  |
| `audit_reference_id`  | int    | no       | null    | Related audit record ID             |

**Valid decisions:**

| Decision  | Effect                                                      |
|-----------|-------------------------------------------------------------|
| `proceed` | Authorized. `data.authorized=True`, `data.action=proposed` |
| `veto`    | Blocked. `data.authorized=False`, `data.action="halted"`   |
| `flag`    | Flagged for review. `data.authorized=False`                 |
| `defer`   | Deferred to later. `data.authorized=False`                  |

Every decision is written permanently to the audit trail regardless of outcome.
The `automation_bias_warning` in `checkpoint_context` is required by EU AI Act
Article 14(4)(b): users must be helped to remain aware of automation bias.

---

### `onto_relate`

Assert a typed, directed edge between two concepts in the ontology.

**Arguments:**

| Argument          | Type   | Required | Default       | Description                         |
|-------------------|--------|----------|---------------|-------------------------------------|
| `source_concept`  | string | yes      | —             | Source concept label                |
| `target_concept`  | string | yes      | —             | Target concept label                |
| `authorization`   | string | yes      | —             | Bearer token                        |
| `edge_type_name`  | string | no       | `"related-to"`| Edge type from registry             |
| `confidence`      | float  | no       | `1.0`         | Confidence in this relationship     |
| `source_type`     | string | no       | `"human"`     | Provenance source type              |

Use `onto_schema` to see all available edge type names.

**Returns (`data`):**

```json
{
    "source_concept":     "machine learning",
    "target_concept":     "neural network",
    "edge_type":          "related-to",
    "nodes_created":      2,
    "edges_created":      1,
    "provenance_id":      43,
    "sensitive_detected": false
}
```

---

## Resources

Resources are read-only and do not require authentication.

### `onto://schema/edge-types`

Complete edge type vocabulary organized by category. Returns all 16 standard
types with names, descriptions, directionality, and inverse relationships.

```json
{
    "schema_version": "1.0",
    "total_types": 16,
    "categories": {
        "associative": [{"id": 1, "name": "related-to", ...}],
        "taxonomic":   [{"id": 3, "name": "is-a", ...}],
        ...
    }
}
```

### `onto://status`

Node health and graph statistics. Safe to call at any time.

```json
{
    "status":         "healthy",
    "schema_version": "1.0",
    "graph": {
        "nodes": 1247,
        "edges": 8932,
        "total_inputs_processed": 423,
        "total_co_occurrences": 12840.0
    },
    "ppr": {
        "available": true,
        "cache_valid": true,
        "hardware_tier": "laptop"
    },
    "decay_profile":  "standard",
    "mcp_version":    "1.0.0"
}
```

### `onto://audit/{page}`

Paginated, read-only access to the cryptographic audit trail. 100 records per
page, newest first. Every record includes its Merkle chain hash.

```json
{
    "schema_version": "1.0",
    "page": 1,
    "total_pages": 14,
    "total_records": 1389,
    "records": [
        {
            "id": 1389,
            "event_type": "MCP_INGEST",
            "timestamp": "2026-04-02T...",
            "classification": 0,
            "chain_hash": "a3f9...",
            "notes": "onto_ingest completed."
        }
    ],
    "chain_note": "Use memory.verify_chain() to confirm integrity."
}
```

---

## Security Model

The MCP interface enforces ONTO's security model:

**Input handling:** Every tool argument is treated as untrusted external input.
Concept labels are truncated to 200 chars. All database queries are parameterized
— no string concatenation anywhere.

**Audit trail:** A pre-record is written before every tool execution. A
post-record is written after. Even a mid-execution crash leaves a trace.

**Crisis handling:** Both `onto_ingest` and `onto_surface` detect crisis
content on the raw input text using the same frozenset check as `graph.relate()`.
Crisis status is returned immediately — it cannot be suppressed or bypassed.

**Safety filter:** All PPR results pass through `_surface_safety_filter()`
before being returned. Sensitive nodes are excluded and listed in `warnings`.

**Wellbeing as highest priority:** The emotional and physical health of the
end user takes precedence over tool throughput. `onto_checkpoint` forces a
human pause at every consequential decision. Crisis signals are never
auto-processed.

---

## Error Reference

| Code       | Cause                                        | Resolution                          |
|------------|----------------------------------------------|-------------------------------------|
| `error`    | Missing/invalid auth token                   | Obtain token via POST /auth         |
| `error`    | Empty concept labels                         | Provide non-empty strings           |
| `error`    | Invalid checkpoint decision                  | Use: proceed, veto, flag, or defer  |
| `crisis`   | Crisis content in input                      | Surface safe messaging to human     |
| `degraded` | Graph not initialized or graph too small     | Call graph.initialize() at boot     |

---

## Forward Compatibility

The MCP interface is designed to evolve without breaking changes:

- `schema_version` in every response enables clients to detect envelope changes.
- Bearer token auth format is identical to OAuth 2.1 — Stage 2 upgrade is
  transparent to clients.
- Tool argument names and types are stable. New optional arguments may be added.
- `onto_schema` returns the live vocabulary — clients should query it rather
  than hardcode edge type names.

---

*This document is part of the permanent record of ONTO.*
*It is updated when the interface changes. Interfaces are contracts.*
