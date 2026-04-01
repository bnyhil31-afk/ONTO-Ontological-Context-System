# API Reference

**Project:** ONTO — Ontological Context System  
**Version:** 1.0

This document describes the public API of every ONTO module.
All public functions are stable. Internal functions (prefixed with `_`)
are implementation details and may change without notice.

---

## The five-step loop

Every input travels through five steps in order:

```
intake.receive(raw)
    → contextualize.build(package)
    → surface.present(enriched)
    → checkpoint.run(surfaced, enriched)
    → memory.record(...)  # called internally by each step
```

Each step returns a dict that is passed to the next. You can call
individual modules directly or run the full loop via `main.py`.

---

## modules/intake.py

The front door. Every input enters here first.

### `receive(raw_input) → dict`

Receives any string input, sanitizes it, classifies it, checks for
safety signals, and returns a package for downstream modules.

**Arguments:**

| Name | Type | Description |
|---|---|---|
| `raw_input` | `str` | Any input string from any source |

**Returns:** A dict with these fields:

| Field | Type | Description |
|---|---|---|
| `raw` | `str` | The original, unmodified input |
| `clean` | `str` | Sanitized input (safe to process) |
| `input_type` | `str` | `question`, `command`, `text`, `number`, or `unknown` |
| `source` | `str` | Always `"human"` in Stage 1 |
| `word_count` | `int` | Number of words in the clean input |
| `complexity` | `str` | `empty`, `simple`, `moderate`, or `complex` |
| `safety` | `dict` or `None` | Safety signal if detected, otherwise `None` |
| `sanitized` | `bool` | `True` if the input was modified during sanitization |
| `truncated` | `bool` | `True` if the input exceeded `MAX_INPUT_LENGTH` |
| `record_id` | `int` | Audit trail ID for this intake event |
| `classification` | `int` | Sensitivity level: 0 (public) to 5 (critical) |
| `classification_basis` | `str` | How classification was determined |

**Safety signal fields** (when `safety` is not `None`):

| Field | Type | Description |
|---|---|---|
| `level` | `str` | `CRISIS`, `HARM`, or `INTEGRITY` |
| `message` | `str` | Human-readable description |
| `requires_human` | `bool` | Whether human review is required |
| `detection` | `str` | Detection method used |

**Classification levels:**

| Level | Label | Meaning |
|---|---|---|
| 0 | public | No sensitivity |
| 1 | internal | Organizational sensitivity |
| 2 | personal | Individual identifying information |
| 3 | sensitive | Health, financial, legal, biometric |
| 4 | privileged | Attorney-client, clinical, clergy |
| 5 | critical | Set explicitly — not auto-detected |

**Example:**
```python
from modules import intake
package = intake.receive("What time is it?")
print(package["input_type"])      # "question"
print(package["complexity"])      # "simple"
print(package["safety"])          # None
print(package["classification"])  # 0
```

---

## modules/contextualize.py

Builds understanding. Places the input in the context of everything
the system has seen before.

### `build(package) → dict`

Takes an intake package and returns an enriched package with graph-backed
context, examination results, distance, and weight.

**Arguments:**

| Name | Type | Description |
|---|---|---|
| `package` | `dict` | Output of `intake.receive()` |

**Returns:** The original package dict with these fields added:

| Field | Type | Description |
|---|---|---|
| `context` | `dict` | Context summary (see below) |
| `distance` | `float` | 0.0 = very familiar, 1.0 = completely new |
| `weight` | `float` | Combined relevance score (0.0–1.0) |
| `graph_context` | `list` | Raw navigate results from the graph |
| `examination` | `dict` | Four-question examination results |
| `relate_result` | `dict` | Result of the RELATE operation |

**Context dict fields:**

| Field | Type | Description |
|---|---|---|
| `related_count` | `int` | Number of related prior observations found |
| `related_samples` | `list` | Top related concepts (strings) |
| `distance` | `float` | Same as top-level distance |
| `weight` | `float` | Same as top-level weight |
| `field_size` | `int` | Total number of past entries in memory |
| `summary` | `str` | Plain language summary of context |

**Examination dict fields:**

| Field | Type | Description |
|---|---|---|
| `consistency` | `str` | `aligned`, `contradicted`, or `new` |
| `novelty` | `str` | `first_seen`, `emerging`, or `established` |
| `source_diversity` | `int` | Number of distinct input sources contributing |
| `total_observations` | `int` | Total observations across all results |
| `diversity_ratio` | `float` | Ratio of sources to observations |
| `contradiction_flags` | `list` | Detected contradictions (strings) |
| `depth_signal` | `str` | Recommended display depth: `simple`, `moderate`, `complex` |

### `load_from_memory() → int`

Rebuilds the in-memory field from past sessions. Called at boot.
Returns the number of past entries loaded.

---

## modules/surface.py

Presents the examined context to the human.

### `present(enriched_package) → dict`

Takes an enriched package and returns a presentation dict with a
human-readable display string and confidence assessment.

**Arguments:**

| Name | Type | Description |
|---|---|---|
| `enriched_package` | `dict` | Output of `contextualize.build()` |

**Returns:**

| Field | Type | Description |
|---|---|---|
| `display` | `str` | Human-readable output — what to show the user |
| `confidence` | `float` | Confidence score 0.0–1.0 |
| `safe` | `bool` | `False` if a safety signal was present |
| `record_id` | `int` | Audit trail ID for this surface event |
| `weight` | `float` | Weight from the enriched package |
| `examination` | `dict` | Full examination results |
| `depth` | `str` | Display depth used: `simple`, `moderate`, `complex` |
| `epistemic_status` | `str` | `known`, `inferred`, or `unknown` |
| `contradiction_flags` | `list` | Any contradictions detected |
| `gap_flags` | `list` | Any context gaps identified |

**Confidence thresholds:**

| Value | Meaning | Language used |
|---|---|---|
| >= 0.7 | High | "Confident — strong match with prior context." |
| >= 0.4 | Moderate | "Moderate confidence." |
| > 0.0 | Low | "Low confidence — limited prior context. Human judgment recommended." |
| == 0.0 | None | "Confidence: none — new territory." |

---

## modules/checkpoint.py

Asks the human. Records the decision. Nothing significant happens
without this step.

### `run(surface, enriched_package) → dict`

Presents the surface output to the human operator and records their
decision permanently.

**Arguments:**

| Name | Type | Description |
|---|---|---|
| `surface` | `dict` | Output of `surface.present()` |
| `enriched_package` | `dict` | Output of `contextualize.build()` |

**Returns:**

| Field | Type | Description |
|---|---|---|
| `decision` | `str` | What the human chose: `proceed`, `veto`, `flag`, `defer`, `AUTO_PROCEED`, `NO_ACTION` |
| `action` | `str` | System action: `PROCEED`, `VETO`, `FLAG_FOR_REVIEW`, `DEFER`, `CRISIS_FOLLOWUP`, `SAFETY_FOLLOWUP` |
| `skipped` | `bool` | `True` if checkpoint was auto-proceeded (low weight, high confidence) |
| `record_id` | `int` | Audit trail ID for this checkpoint event |

**Auto-proceed thresholds** (configurable):

| Condition | Threshold |
|---|---|
| Weight below | 0.65 |
| Confidence above | 0.50 |

If weight is below `ALWAYS_ASK_WEIGHT` **and** confidence is above
`ALWAYS_ASK_CONFIDENCE`, the checkpoint auto-proceeds without asking.
All other inputs always ask the human.

---

## modules/memory.py

Permanent, append-only audit trail. Everything is recorded here.
Records can never be deleted or modified — the database enforces this.

### `initialize() → bool`

Creates the database and tables if they do not exist. Safe to call
multiple times. Returns `True` when ready.

### `record(...) → int`

Records a single event permanently. Returns the record ID.

**Arguments:**

| Name | Type | Default | Description |
|---|---|---|---|
| `event_type` | `str` | required | Event type (see below) |
| `input_data` | `str` | `None` | Input text |
| `context` | `dict` | `None` | Context dict |
| `output` | `str` | `None` | Output text |
| `confidence` | `float` | `None` | Confidence score |
| `human_decision` | `str` | `None` | Human decision at checkpoint |
| `notes` | `str` | `None` | Additional notes |
| `classification` | `int` | `0` | Data sensitivity level (0–5) |
| `signature_algorithm` | `str` | `"Ed25519"` | Signing algorithm |

**Event types:**

| Type | When recorded |
|---|---|
| `BOOT` | System startup |
| `HALT` | System shutdown |
| `INTAKE` | Every input received |
| `CONTEXTUALIZE` | Every contextualize pass |
| `SURFACE` | Every surface pass |
| `CHECKPOINT` | Every checkpoint interaction |
| `SESSION_START` | Session begins |
| `SESSION_END` | Session ends |
| `SESSION_ROTATE` | Session token rotated |
| `SESSION_EXPIRED` | Session expired (idle or max duration) |
| `READ_ACCESS` | Sensitive record read (classification ≥ 2) |

### `read_all() → list`

Returns all records in chronological order (oldest first).

### `read_recent(n=10) → list`

Returns the `n` most recent records (newest first).

### `read_by_id(record_id) → dict or None`

Returns a single record by ID, or `None` if not found.

### `read_by_type(event_type) → list`

Returns all records matching a given event type.

### `verify_chain() → dict`

Verifies the integrity of the Merkle chain. Returns:

| Field | Type | Description |
|---|---|---|
| `intact` | `bool` | `True` if the chain is unbroken |
| `total` | `int` | Total records checked |
| `gaps` | `list` | Record IDs where the chain breaks |
| `first_record_hash` | `str` | SHA-256 of the genesis record |

### `log_read_access(record_id, accessor_id, purpose, classification) → int or None`

Records a read access event for sensitive data. Returns the event ID
if logged (classification ≥ `READ_LOG_THRESHOLD`), or `None` if below
the threshold. Default threshold: 2 (personal data and above).

### Record dict fields

Every record returned by a read function has these fields:

| Field | Type | Description |
|---|---|---|
| `id` | `int` | Unique record ID |
| `timestamp` | `str` | ISO 8601 UTC timestamp |
| `event_type` | `str` | Event type |
| `input` | `str` or `None` | Input text |
| `context` | `dict` or `None` | Context dict |
| `output` | `str` or `None` | Output text |
| `confidence` | `float` or `None` | Confidence score |
| `human_decision` | `str` or `None` | Human decision |
| `notes` | `str` or `None` | Additional notes |
| `chain_hash` | `str` or `None` | SHA-256 of the previous record |
| `signature_algorithm` | `str` | Signing algorithm used |
| `classification` | `int` | Data sensitivity level |

---

## core/session.py

Session management. Tracks who is using the system and for how long.

### `session_manager.start(identity, idle_timeout, max_duration) → str`

Starts a new session. Terminates any existing session (Stage 1 enforces
one active session at a time). Returns a 256-bit hex token.

### `session_manager.validate(token) → SessionRecord or None`

Validates a token. Updates `last_active` on success. Returns `None`
if the token is unknown, terminated, or expired.

### `session_manager.rotate(token) → str or None`

Rotates the token. The old token is immediately invalid. Returns the
new token, or `None` if the session is not valid.

### `session_manager.terminate(token) → bool`

Explicitly terminates a session. Returns `True` if terminated,
`False` if the token was not found.

### `session_manager.is_active() → bool`

Returns `True` if there is a currently valid active session.

---

## core/config.py

All configuration is loaded from environment variables. Import the
shared instance:

```python
from core.config import config
```

| Property | Env var | Default | Description |
|---|---|---|---|
| `RATE_LIMIT_PER_MINUTE` | `ONTO_RATE_LIMIT_PER_MINUTE` | `60` | Max inputs per minute |
| `RATE_LIMIT_WINDOW_SECONDS` | `ONTO_RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window |
| `MAX_INPUT_LENGTH` | `ONTO_MAX_INPUT_LENGTH` | `10000` | Max input characters |
| `DB_PATH` | `ONTO_DB_PATH` | `data/memory.db` | Database path |
| `DB_ENCRYPTION_KEY` | `ONTO_DB_ENCRYPTION_KEY` | `None` | Database encryption key |
| `AUTH_REQUIRED` | `ONTO_AUTH_REQUIRED` | `false` | Require passphrase at boot |
| `AUTH_PASSPHRASE_HASH` | `ONTO_AUTH_PASSPHRASE_HASH` | `None` | Hashed passphrase |
| `ENVIRONMENT` | `ONTO_ENVIRONMENT` | `development` | `development`, `staging`, `production` |
| `SESSION_IDLE_TIMEOUT_SECONDS` | `ONTO_SESSION_IDLE_TIMEOUT` | `1800` | Session idle timeout |
| `SESSION_MAX_DURATION_SECONDS` | `ONTO_SESSION_MAX_DURATION` | `28800` | Max session lifetime |
| `CRISIS_RESPONSE_TEXT` | `ONTO_CRISIS_RESPONSE_TEXT` | (see config.py) | Crisis checkpoint text |
| `CRISIS_RESOURCES_BRIEF` | `ONTO_CRISIS_RESOURCES_BRIEF` | (see config.py) | Brief crisis resources |
| `AUTOMATION_BIAS_WARNING` | `ONTO_AUTOMATION_BIAS_WARNING` | (see config.py) | Bias warning text |

Call `config.summary()` to print the current configuration without
exposing secrets.

---

## Error handling

ONTO is designed to fail safely. Every module catches exceptions
internally and falls back to safe defaults rather than crashing.

If a module raises an exception that reaches `main.py`, the boot
sequence will catch it and exit cleanly. All events up to the point
of failure are preserved in the audit trail.

---

---

## modules/graph.py

The relationship graph — the heart of ONTO. Implements RELATE and
NAVIGATE as real graph operations backed by SQLite.

Import the public functions:

```python
from modules import graph
```

All functions are thread-safe and fail gracefully — none raises on
bad input or missing data.

---

### `graph.initialize() → None`

Create the `graph_nodes`, `graph_edges`, and `graph_metadata` tables
and their indexes. Apply WAL mode and performance pragmas. Fully
idempotent — safe to call at every boot. Also performs schema migration
for existing databases (adds `inputs_seen` and `is_sensitive` columns
if they do not exist).

Call after `memory.initialize()` at boot.

---

### `graph.relate(package) → dict`

Ingest an intake package. Extract concepts. Write weighted co-occurrence
edges to the graph.

| Parameter | Type | Description |
|---|---|---|
| `package` | `dict` | Intake package. Must contain `"raw"` or `"clean"`. |

**Returns:**
```json
{
  "concepts":           ["list", "of", "extracted", "concepts"],
  "nodes_created":      3,
  "nodes_reinforced":   0,
  "edges_created":      3,
  "edges_reinforced":   0,
  "crisis_detected":    false,
  "sensitive_detected": false
}
```

If `crisis_detected` is `True`, nothing was written to the graph.
The caller must surface crisis resources immediately.

---

### `graph.navigate(text, include_sensitive=False) → list[dict]`

Traverse the graph from concepts in `text`. Return a ranked list of
related context, sorted by `effective_weight` descending.

Uses BFS at depth 2 with ACT-R fan effect. Effective weight applies
all three governing axes plus PPMI approximation and fan dilution.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `text` | `str` | required | Query text. |
| `include_sensitive` | `bool` | `False` | Include sensitive edges. |

**Each result dict:**
```json
{
  "concept":          "machine learning",
  "effective_weight": 0.7234,
  "times_seen":       5,
  "inputs_seen":      4,
  "source":           "graph",
  "days_since":       1.23,
  "complexity":       3,
  "is_sensitive":     false
}
```

| Field | Description |
|---|---|
| `effective_weight` | 0.0–1.0. Distance × Size × Complexity × PPMI × Fan. |
| `inputs_seen` | Distinct inputs mentioning this concept. IDF denominator. |
| `days_since` | Days since edge was last reinforced. |
| `complexity` | Edge degree of this node. |
| `is_sensitive` | True if concept is in the sensitive set. |

Returns `[]` if text is empty or no seed concepts exist in the graph.

---

### `graph.decay() → dict`

Prune edges whose effective weight has fallen below `PRUNE_THRESHOLD`.
Remove orphaned nodes. Call at boot after `graph.initialize()`.

Stored weights are not updated — effective weight is computed lazily
at read time. Sensitive edges decay faster (exponent × 1.4).

**Returns:** `{"edges_pruned": int, "nodes_pruned": int}`

---

### `graph.wipe() → dict`

Delete the entire relationship graph. Records a `GRAPH_WIPE` audit event.

**Legal basis:** GDPR Article 17 — right to erasure.

**Returns:** `{"nodes_deleted": int, "edges_deleted": int}`

---

### Configuration

| Env var | Default | Description |
|---|---|---|
| `ONTO_GRAPH_DECAY_EXPONENT` | `0.5` | Power-law decay exponent (ACT-R standard). |
| `ONTO_GRAPH_PRUNE_THRESHOLD` | `0.05` | Minimum effective weight before pruning. |
| `ONTO_GRAPH_MAX_RESULTS` | `20` | Maximum results from `navigate()`. |
| `ONTO_GRAPH_MAX_DEPTH` | `2` | BFS depth. Validated by Balota & Lorch (1986). |
| `ONTO_GRAPH_MAX_CONCEPTS` | `15` | Max concepts per input (limits edge explosion). |
| `ONTO_GRAPH_BASE_REINFORCEMENT` | `0.08` | Base edge weight increment. |
| `ONTO_GRAPH_SENSITIVE_REINFORCEMENT` | `0.02` | Reduced increment for sensitive edges. |

See `docs/GRAPH_THEORY_001.md` for the complete theoretical basis.

---

## Extending ONTO

Every core module is designed as a swappable component. The swap
interface contracts are:

- **Authentication:** replace `core/auth.py` — implement `authenticate() → AuthResult`
- **Session management:** replace `core/session.py` — implement `start()`, `validate()`, `rotate()`, `terminate()`
- **Graph backend:** replace `modules/graph.py` — implement `relate(package)`, `navigate(text)`

Any module satisfying the contract is a valid replacement. Nothing
else in the system needs to change.

---

*This document reflects ONTO version 1.0.*  
*If you find anything inaccurate, open an issue.*
