# Graph Entropy and Echo Chamber Monitoring

**Document ID:** ECHO-MONITOR-001
**Version:** 1.0
**Status:** Design document — implementation is Stage 2+
**Covers:** Checklist item 5.12
**Last updated:** April 2026

> This document records the design of ONTO's anti-echo-chamber
> mechanisms. Some are already implemented (federation
> concentration detection). Others are staged for future implementation.
> The design is recorded here now so it can guide decisions made today.

---

## The problem ONTO is designed to avoid

A knowledge graph that only ever reinforces what it has already seen
becomes a mirror, not a window. Every input strengthens the same
nodes. Every traversal returns the same context. The user's
understanding of the world narrows without them knowing it.

This is not a hypothetical risk. It is a predictable consequence of
uniform reinforcement without entropy monitoring. ONTO is specifically
designed to resist it — because an epistemic monoculture causes real
harm to real people.

The three axes (Distance, Complexity, Size) already work against
concentration: Distance decays old connections, Complexity penalizes
over-connected hubs during traversal, Size normalizes by frequency.
But these are passive resistances. Active monitoring adds visibility.

---

## What graph entropy measures

**Graph entropy** measures how evenly information is distributed
across the graph. A high-entropy graph has many concepts with moderate
weight. A low-entropy graph has a few hub concepts dominating
everything — the computational analog of a narrow worldview.

The measure used is **normalized Shannon entropy** over node weights:

```
H = -∑(w_i / W) × log(w_i / W)   for all nodes i
W = sum of all node weights
H_normalized = H / log(N)          where N = number of nodes
```

`H_normalized` is always in [0, 1]:
- 1.0 = perfectly uniform — every concept equally weighted
- 0.0 = single dominant concept — maximum concentration

A healthy graph sits between 0.4 and 0.9. The right range depends
on the deployment context and the user's natural vocabulary breadth.

---

## Implementation layers

### Layer 1 — Federation concentration detection (IMPLEMENTED — Phase 3)

`api/federation/config.py` already implements anti-concentration routing:

```python
ONTO_FED_MAX_GRAPH_SIMILARITY=1.0   # 1.0 = disabled (default)
                                     # 0.8 = warn at 80% concept overlap
```

The Jaccard similarity between a peer's VoID descriptor and the local
graph triggers a soft warning when it exceeds the threshold. Operators
are notified — they make the decision. This is the right pattern:
the system surfaces the signal, the human makes the call.

This is operational now. It protects against cross-node echo chambers
where two nodes reinforce each other's existing biases.

### Layer 2 — Local entropy monitoring (Stage 2 — design ready)

**Where it lives:** `modules/graph.py` — added to the existing
`graph.navigate()` response as a field in the surface output.

**When it fires:** On every `graph.decay()` call (which happens
at each session start). Entropy is computed after decay, before
the session begins. Low entropy triggers a soft warning in the
`onto_status` MCP resource.

**Implementation:**

```python
def compute_entropy() -> Dict[str, float]:
    """
    Compute normalized Shannon entropy over node weights.
    Returns:
        {
            "h_normalized": float,   # 0.0-1.0
            "node_count": int,
            "dominant_concepts": List[str],  # top 5 by weight
            "warning": bool,         # True if H < ENTROPY_WARN_THRESHOLD
        }
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT concept, weight FROM graph_nodes ORDER BY weight DESC"
    ).fetchall()
    conn.close()

    if len(rows) < 10:
        return {"h_normalized": 1.0, "node_count": len(rows),
                "dominant_concepts": [], "warning": False}

    weights = [r["weight"] for r in rows]
    W = sum(weights)
    if W == 0:
        return {"h_normalized": 1.0, "node_count": len(rows),
                "dominant_concepts": [], "warning": False}

    import math
    H = -sum((w/W) * math.log(w/W) for w in weights if w > 0)
    H_norm = H / math.log(len(weights))

    threshold = float(os.getenv("ONTO_ENTROPY_WARN_THRESHOLD", "0.3"))
    return {
        "h_normalized": round(H_norm, 4),
        "node_count": len(rows),
        "dominant_concepts": [r["concept"] for r in rows[:5]],
        "warning": H_norm < threshold,
    }
```

**Config vars:**
```
ONTO_ENTROPY_MONITOR_ENABLED=false   # disabled by default (Stage 2)
ONTO_ENTROPY_WARN_THRESHOLD=0.3      # warn below this normalized entropy
```

### Layer 3 — Rumination detection (Stage 2 — safety-critical)

The research audit identified this as the most serious safety risk:
uniform reinforcement of distress-related content creates a
computational mechanism for amplifying psychological distress.

**Pattern:** User inputs crisis-adjacent content repeatedly.
Each input reinforces the relevant nodes (+0.08 per interaction).
The graph increasingly surfaces distress-related context.
Distress-related context increases distress. Loop closes.

**Mitigation design (not yet implemented):**

```python
# In graph.relate():
# If is_sensitive=True and the same concept has been reinforced
# more than RUMINATION_THRESHOLD times in the past RUMINATION_WINDOW hours:

ONTO_RUMINATION_THRESHOLD=5          # reinforcements before warning
ONTO_RUMINATION_WINDOW_HOURS=2       # time window
ONTO_RUMINATION_DECAY_MULTIPLIER=2.0 # apply 2× decay to ruminated nodes
```

When rumination is detected:
1. `RUMINATION_DETECTED` event written to audit trail
2. `onto_checkpoint` surfaced to operator with context
3. Decay multiplier applied to the ruminated concept cluster
4. Crisis resources offered (same pathway as `crisis_detected`)

This is distinct from crisis detection (which triggers on specific
language). Rumination detection triggers on behavioral patterns —
the same sensitive topic revisited repeatedly even if no crisis
language is present.

**Safety note:** This is a safety-critical feature. Implementation
requires mental health professional review (checklist item 5.09)
before deployment. The thresholds above are starting points, not
clinically validated values.

### Layer 4 — Topic diversity monitoring (Stage 3)

**Purpose:** Surface when the graph's active concepts have narrowed
to a small topical cluster — even without high individual node weights.

**Measure:** Number of distinct top-level DPV category clusters
represented in the top-50 nodes by weight. A healthy personal
knowledge graph spans multiple domains. A concentrated one
has 80%+ of its weight in one domain.

**Output:** A `topic_diversity_score` in `onto_status`:
```json
"graph_health": {
    "entropy": 0.72,
    "topic_clusters": 8,
    "dominant_cluster": "technology",
    "dominant_cluster_pct": 34,
    "diversity_warning": false
}
```

---

## What operators see

The `onto_status` MCP resource (Phase 2) is extended in Stage 2
to include graph health:

```json
"graph_health": {
    "entropy_normalized": 0.68,
    "entropy_warning": false,
    "entropy_threshold": 0.30,
    "node_count": 847,
    "dominant_concepts": ["machine learning", "context", "reasoning"],
    "rumination_alerts": 0,
    "topic_diversity_score": 0.74,
    "last_computed": "2026-04-03T14:22:00Z"
}
```

The operator sees this. They decide what to do. ONTO never acts
unilaterally — it surfaces the signal, the human makes the call.

---

## What ONTO never does

ONTO never:
- Removes or suppresses concepts from the graph without human decision
- Automatically routes around topics it classifies as harmful
- Decides what the user should be interested in
- Curates context toward any particular worldview

ONTO always:
- Surfaces entropy warnings as information, not blocks
- Gives the operator the signal and the decision
- Applies rumination decay only when the operator has confirmed it
  (via `onto_checkpoint`)
- Records every entropy event in the audit trail

This is the anti-echo-chamber commitment: visibility and human
sovereignty, not automated curation.

---

## Relationship to federation

Phase 3 federation already implements Layer 1. The `ONTO_FED_MAX_GRAPH_SIMILARITY`
config controls cross-node echo chamber detection. This is the
only currently active layer.

All other layers are designed here and deferred to Stage 2+.
The design is recorded now so implementation decisions made today
(schema, config naming, MCP resource structure) are forward-compatible.

---

## Implementation sequencing

| Layer | Description | Stage | Blocker |
|-------|-------------|-------|---------|
| 1 | Federation concentration | ✅ Phase 3 | None |
| 2 | Local entropy monitoring | Stage 2 | `ONTO_CONSENT_ENABLED` (multi-user) |
| 3 | Rumination detection | Stage 2 | Mental health professional review (5.09) |
| 4 | Topic diversity | Stage 3 | Requires DPV category mapping |

Layer 3 (rumination) must not be implemented before item 5.09
(mental health professional review) is complete. The thresholds
have real consequences for real people. Getting them wrong causes harm.

---

*This document is part of the permanent record of ONTO.*
*The system is designed to resist the very biases that unchecked*
*reinforcement systems create. That is not an accident.*
*It is a design commitment.*
