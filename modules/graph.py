"""
modules/graph.py

THE RELATIONSHIP GRAPH — the heart of ONTO.

Implements the weighted relationship graph that the entire system is
designed around. Every design decision in this file has a named
scientific basis. See docs/GRAPH_THEORY_001.md for the full reference.

Public interface (swap-in contract — see API.md):
    initialize()                      — create tables, apply pragmas
    relate(package)                   — ingest input, write weighted edges
    navigate(text, include_sensitive) — traverse graph, return context
    decay()                           — prune dead edges and orphaned nodes
    wipe()                            — GDPR right to erasure

Key changes from initial implementation (all research-backed):
    1. Power-law decay replaces exponential (Wixted 2004, Jost's Law 1897)
    2. Spacing-effect reinforcement replaces flat increment (Cepeda et al. 2006)
    3. TF-IDF Size axis replaces raw frequency (Sparck Jones 1972)
    4. PPMI-approximation edge scoring (Bullinaria & Levy 2007)
    5. ACT-R fan effect during traversal (Anderson 1983)
    6. RAKE-inspired concept extraction (Rose et al. 2010)
    7. Sensitive topic and crisis detection — wellbeing protection layer
       (Nolen-Hoeksema 1991, 2008)
    8. wipe() — GDPR Article 17 right to erasure
    9. Lazy decay — effective weight computed at read time, not batched

Design principles:
    - Zero external dependencies beyond stdlib + sqlite3
    - Stable UUID node identifiers — portable to any future backend
    - Concepts are observations, never truth claims
    - Every edge traces to an external input — no synthetic edges
    - Decay is the system's metabolism — the graph grows where used,
      fades where not, like biological memory
    - Uncertainty is a first-class output of navigate()

Stage 2 upgrade points (marked throughout):
    - RAKE -> spaCy NER + noun phrase extraction
    - BFS depth-2 -> Personalized PageRank (PPR)
    - Degree centrality -> Katz/eigenvector centrality
    - Full PPMI with global co-occurrence matrix
    - Directed edges for typed relationships

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import math
import os
import re
import sqlite3
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import memory as _memory  # noqa: E402


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Axis 1: Distance — power-law decay exponent.
# Scientific basis: Wixted (2004) meta-analysis; Rubin & Wenzel (1996)
# tested 105 forgetting functions — power law was the top performer.
# ACT-R standard: d = 0.5. Range [0.3, 0.7] is empirically reasonable.
DECAY_EXPONENT: float = float(os.environ.get("ONTO_GRAPH_DECAY_EXPONENT", "0.5"))

# Edges whose effective weight falls below this threshold are pruned.
PRUNE_THRESHOLD: float = float(os.environ.get("ONTO_GRAPH_PRUNE_THRESHOLD", "0.05"))

# Maximum results returned by navigate().
MAX_NAVIGATE_RESULTS: int = int(os.environ.get("ONTO_GRAPH_MAX_RESULTS", "20"))

# BFS depth. Scientific basis: Balota & Lorch (1986) — spreading activation
# reliably reaches depth 2; depth 3+ produces negligible signal after fan
# dilution.
MAX_NAVIGATE_DEPTH: int = int(os.environ.get("ONTO_GRAPH_MAX_DEPTH", "2"))

# Max concepts per input. Capped at 15 to limit edge explosion:
# 15 concepts = 105 pairs maximum.
MAX_CONCEPTS_PER_INPUT: int = int(os.environ.get("ONTO_GRAPH_MAX_CONCEPTS", "15"))

# Minimum token length.
MIN_CONCEPT_LENGTH: int = 3

# Base reinforcement increment. Modified at runtime by spacing effect.
BASE_REINFORCEMENT: float = float(
    os.environ.get("ONTO_GRAPH_BASE_REINFORCEMENT", "0.08")
)

# Reduced reinforcement for sensitive-topic co-occurrences.
SENSITIVE_REINFORCEMENT: float = float(
    os.environ.get("ONTO_GRAPH_SENSITIVE_REINFORCEMENT", "0.02")
)

# Write lock — WAL mode handles concurrent readers; writes are serialised.
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# WELLBEING PROTECTION LAYER
# ---------------------------------------------------------------------------
#
# Scientific basis: Nolen-Hoeksema (1991, 2008) — rumination is a core
# transdiagnostic risk factor. Uniform reinforcement of distress-related
# concepts creates a mechanism for amplifying negative associations.
# Colombetti & Roberts (2024) — technology can scaffold maladaptive
# psychological processes.
#
# Two tiers:
#   SENSITIVE — reduced reinforcement + faster decay
#   CRISIS    — NEVER stored in graph; surface resources immediately
#
# These sets are intentionally conservative.
# Mental health professional review is recommended before deployment.
# Operators must not remove or weaken this layer (TERMS_OF_USE.md).
# ---------------------------------------------------------------------------

_SENSITIVE_CONCEPTS: frozenset = frozenset({
    "anxiety", "anxious", "depressed", "depression", "sad", "sadness",
    "hopeless", "hopelessness", "worthless", "failure", "shame", "guilt",
    "trauma", "panic", "lonely", "loneliness", "grief", "loss", "abuse",
    "addiction", "relapse", "overdose", "purge", "restrict", "cutting",
    "hurt", "pain", "suffering", "fear", "worry", "stress", "burnout",
    "exhausted", "overwhelmed",
})

_CRISIS_CONCEPTS: frozenset = frozenset({
    "suicide", "suicidal", "kill myself", "kill yourself", "end my life",
    "end it all", "no reason to live", "give up on life", "goodbye forever",
    "self harm", "self-harm", "cut myself", "hurt myself", "hurt yourself",
    "want to die", "going to die", "planning to die",
})


# ---------------------------------------------------------------------------
# STOPWORDS
# ---------------------------------------------------------------------------

_STOPWORDS: frozenset = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can",
    "had", "her", "was", "one", "our", "out", "day", "get", "has",
    "him", "his", "how", "its", "may", "new", "now", "old", "see",
    "two", "way", "who", "did", "let", "put", "say", "she", "too",
    "use", "that", "this", "with", "have", "from", "they", "will",
    "been", "when", "there", "what", "your", "more", "also", "into",
    "than", "then", "some", "could", "would", "about", "which",
    "their", "said", "each", "very", "just", "does", "like", "most",
    "over", "know", "time", "year", "such", "even", "here", "much",
    "well", "only", "come", "back", "after", "other", "many", "first",
    "while", "these", "those", "being", "since", "where", "should",
    "through", "before", "between",
})


# ---------------------------------------------------------------------------
# CONNECTION
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    """
    Open a connection to the shared ONTO database.
    WAL mode: safe for concurrent readers + one serialised writer.
    """
    conn = sqlite3.connect(
        _memory.DB_PATH, check_same_thread=False, timeout=10
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA page_size=4096")
    conn.execute("PRAGMA cache_size=-32000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# PUBLIC: INITIALIZE
# ---------------------------------------------------------------------------

def initialize() -> None:
    """
    Create graph tables and indexes. Idempotent. Call at every boot.

    Schema notes:
      graph_nodes.inputs_seen  — distinct relate() calls mentioning this
                                  concept. Used for IDF (Sparck Jones 1972):
                                  rarer concepts carry more information.
      graph_nodes.is_sensitive — 1 if concept is in the sensitive set.
      graph_edges.weight       — base weight at last reinforcement. Effective
                                  weight is computed lazily at read time.
      graph_edges.is_sensitive — 1 if either concept is sensitive.
      graph_metadata           — global counters for IDF and PPMI.

    Migration safety: ALTER TABLE ADD COLUMN safely adds new columns to
    existing databases without data loss.
    """
    with _lock:
        conn = _get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    id           TEXT PRIMARY KEY,
                    concept      TEXT NOT NULL UNIQUE,
                    first_seen   TEXT NOT NULL,
                    last_seen    TEXT NOT NULL,
                    times_seen   INTEGER NOT NULL DEFAULT 1,
                    inputs_seen  INTEGER NOT NULL DEFAULT 1,
                    is_sensitive INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS graph_edges (
                    id                  TEXT PRIMARY KEY,
                    source_node_id      TEXT NOT NULL,
                    target_node_id      TEXT NOT NULL,
                    weight              REAL NOT NULL DEFAULT 0.5,
                    reinforcement_count INTEGER NOT NULL DEFAULT 1,
                    created_at          TEXT NOT NULL,
                    last_reinforced     TEXT NOT NULL,
                    is_sensitive        INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(source_node_id, target_node_id),
                    FOREIGN KEY (source_node_id) REFERENCES graph_nodes(id),
                    FOREIGN KEY (target_node_id) REFERENCES graph_nodes(id)
                );

                CREATE TABLE IF NOT EXISTS graph_metadata (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_graph_nodes_concept
                    ON graph_nodes(concept);
                CREATE INDEX IF NOT EXISTS idx_graph_edges_source
                    ON graph_edges(source_node_id);
                CREATE INDEX IF NOT EXISTS idx_graph_edges_target
                    ON graph_edges(target_node_id);
                CREATE INDEX IF NOT EXISTS idx_graph_edges_weight
                    ON graph_edges(weight DESC);
                CREATE INDEX IF NOT EXISTS idx_graph_edges_reinforced
                    ON graph_edges(last_reinforced);
            """)

            # Migration: add new columns to existing databases safely
            for stmt in (
                "ALTER TABLE graph_nodes ADD COLUMN"
                " inputs_seen INTEGER NOT NULL DEFAULT 1",
                "ALTER TABLE graph_nodes ADD COLUMN"
                " is_sensitive INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE graph_edges ADD COLUMN"
                " is_sensitive INTEGER NOT NULL DEFAULT 0",
            ):
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # Column already exists — safe to ignore

            conn.execute(
                "INSERT OR IGNORE INTO graph_metadata (key, value) VALUES (?, ?)",
                ("total_inputs_processed", "0"),
            )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# PUBLIC: RELATE
# ---------------------------------------------------------------------------

def relate(package: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ingest an input package. Extract concepts. Write weighted edges.

    Scientific basis:
      Hebbian learning — co-occurrence strengthens associative links.
      Collins & Loftus (1975) — spreading activation via weighted edges.
      Spacing effect (Cepeda et al. 2006) — reinforcement is more durable
        when time has elapsed since last access. See _spacing_increment().

    Safety (highest priority):
      Crisis concepts are NEVER stored. Returns immediately with
        crisis_detected=True. The caller must surface crisis resources.
      Sensitive concepts receive SENSITIVE_REINFORCEMENT to prevent
        rumination loop amplification.
      (Nolen-Hoeksema 1991, 2008; Colombetti & Roberts 2024)

    Returns:
        {
          "concepts":           list[str],
          "nodes_created":      int,
          "nodes_reinforced":   int,
          "edges_created":      int,
          "edges_reinforced":   int,
          "crisis_detected":    bool,  — NEVER store; surface resources now
          "sensitive_detected": bool,  — input touched sensitive topics
        }
    """
    text = package.get("clean") or package.get("raw") or ""
    if not text or not text.strip():
        return _empty_relate_result()

    # Crisis check first — do not persist under any circumstances
    if _contains_crisis(text):
        result = _empty_relate_result()
        result["crisis_detected"] = True
        return result

    sensitive_detected = _contains_sensitive(text)
    concepts = _extract_concepts(text)

    if not concepts:
        result = _empty_relate_result()
        result["sensitive_detected"] = sensitive_detected
        return result

    now = _now()
    nodes_created = 0
    nodes_reinforced = 0
    edges_created = 0
    edges_reinforced = 0

    with _lock:
        conn = _get_conn()
        try:
            node_ids: Dict[str, str] = {}

            for concept in concepts:
                is_node_sensitive = int(concept in _SENSITIVE_CONCEPTS)
                node_id, created = _upsert_node(
                    conn, concept, now, is_node_sensitive
                )
                node_ids[concept] = node_id
                if created:
                    nodes_created += 1
                else:
                    nodes_reinforced += 1

            for src_id, tgt_id, src_concept, tgt_concept in _concept_pairs(
                node_ids
            ):
                edge_is_sensitive = int(
                    src_concept in _SENSITIVE_CONCEPTS
                    or tgt_concept in _SENSITIVE_CONCEPTS
                    or sensitive_detected
                )
                reinforcement = (
                    SENSITIVE_REINFORCEMENT
                    if edge_is_sensitive
                    else BASE_REINFORCEMENT
                )
                created = _upsert_edge(
                    conn, src_id, tgt_id, now, reinforcement, edge_is_sensitive
                )
                if created:
                    edges_created += 1
                else:
                    edges_reinforced += 1

            # Increment global input counter (required for IDF computation)
            conn.execute(
                """UPDATE graph_metadata
                   SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)
                   WHERE key = 'total_inputs_processed'"""
            )
            conn.commit()

        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return _empty_relate_result()
        finally:
            conn.close()

    return {
        "concepts": concepts,
        "nodes_created": nodes_created,
        "nodes_reinforced": nodes_reinforced,
        "edges_created": edges_created,
        "edges_reinforced": edges_reinforced,
        "crisis_detected": False,
        "sensitive_detected": sensitive_detected,
    }


# ---------------------------------------------------------------------------
# PUBLIC: NAVIGATE
# ---------------------------------------------------------------------------

def navigate(text: str, include_sensitive: bool = False) -> List[Dict[str, Any]]:
    """
    Traverse the graph from concepts in the query. Return ranked context.

    Scientific basis:
      BFS at depth 2 (Balota & Lorch 1986) — activation reliably reaches
        depth 2; depth 3+ is below threshold after fan dilution.
      Fan effect (ACT-R, Anderson 1983) — activation divides among all
        connections; high-degree nodes spread less activation per path.
      Power-law decay (Wixted 2004) — weight x (1 + days)^(-d).
      TF-IDF Size axis (Sparck Jones 1972) — common concepts downweighted.
      PPMI approximation (Bullinaria & Levy 2007) — co-occurrence above
        chance is rewarded over raw frequency.

    Safety: sensitive edges excluded by default.
    Set include_sensitive=True only for authorised clinical use cases.

    Returns list of dicts sorted by effective_weight descending:
        {
          "concept":           str,
          "effective_weight":  float,   # 0.0-1.0, all axes applied
          "times_seen":        int,
          "inputs_seen":       int,
          "source":            str,     # always "graph"
          "days_since":        float,
          "complexity":        int,     # degree of this node
          "is_sensitive":      bool,
        }
    """
    if not text or not text.strip():
        return []

    concepts = _extract_concepts(text)
    if not concepts:
        return []

    try:
        conn = _get_conn()
        try:
            total_inputs = _get_total_inputs(conn)
            return _bfs_navigate(conn, concepts, total_inputs, include_sensitive)
        finally:
            conn.close()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# PUBLIC: DECAY
# ---------------------------------------------------------------------------

def decay() -> Dict[str, int]:
    """
    Prune edges whose effective weight has fallen below PRUNE_THRESHOLD.
    Remove orphaned nodes (nodes with no surviving edges).

    Design — lazy decay:
      stored weight = base weight at last reinforcement time.
      Effective weight is computed at read time in navigate() using the
      power-law formula. This function only removes what is inaccessible.
      No bulk UPDATE of stored weights — avoids write storms on large graphs
      and is more accurate than batched approximations.

    Scientific basis: Power-law decay (Wixted 2004). Forgetting is
    accessibility loss, not deletion. Edges below the pruning threshold
    are effectively inaccessible and consume traversal resources.

    Sensitive edges use steeper decay (DECAY_EXPONENT * 1.4) to prevent
    long-term persistence of distress-related associations.

    Returns:
        {"edges_pruned": int, "nodes_pruned": int}
    """
    now_dt = datetime.now(timezone.utc)
    edges_pruned = 0
    nodes_pruned = 0

    with _lock:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT id, weight, last_reinforced, is_sensitive "
                "FROM graph_edges"
            ).fetchall()

            for row in rows:
                days_elapsed = _days_since(row["last_reinforced"], now_dt)
                exponent = (
                    DECAY_EXPONENT * 1.4
                    if row["is_sensitive"]
                    else DECAY_EXPONENT
                )
                decayed = row["weight"] * (1.0 + days_elapsed) ** (-exponent)
                if decayed < PRUNE_THRESHOLD:
                    conn.execute(
                        "DELETE FROM graph_edges WHERE id = ?", (row["id"],)
                    )
                    edges_pruned += 1

            # Remove orphaned nodes
            orphans = conn.execute("""
                SELECT n.id FROM graph_nodes n
                WHERE NOT EXISTS (
                    SELECT 1 FROM graph_edges e
                    WHERE e.source_node_id = n.id
                       OR e.target_node_id = n.id
                )
            """).fetchall()
            for row in orphans:
                conn.execute(
                    "DELETE FROM graph_nodes WHERE id = ?", (row["id"],)
                )
                nodes_pruned += 1

            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()

    return {"edges_pruned": edges_pruned, "nodes_pruned": nodes_pruned}


# ---------------------------------------------------------------------------
# PUBLIC: WIPE
# ---------------------------------------------------------------------------

def wipe() -> Dict[str, int]:
    """
    Delete the entire relationship graph.

    Legal basis: GDPR Article 17 — right to erasure. The graph stores
    personal associative data derived from user inputs. Users have an
    unconditional right to delete it.

    The audit trail in memory.py is NOT affected. It records only that
    a wipe occurred — not the content. See docs/PRIVACY_GDPR.md for
    the architectural separation of graph (erasable) vs trail (append-only).

    Returns:
        {"nodes_deleted": int, "edges_deleted": int}
    """
    with _lock:
        conn = _get_conn()
        try:
            edge_count = conn.execute(
                "SELECT COUNT(*) AS c FROM graph_edges"
            ).fetchone()["c"]
            node_count = conn.execute(
                "SELECT COUNT(*) AS c FROM graph_nodes"
            ).fetchone()["c"]

            conn.execute("DELETE FROM graph_edges")
            conn.execute("DELETE FROM graph_nodes")
            conn.execute(
                "UPDATE graph_metadata SET value = '0' "
                "WHERE key = 'total_inputs_processed'"
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return {"nodes_deleted": 0, "edges_deleted": 0}
        finally:
            conn.close()

    # Record the wipe in the audit trail AFTER the lock is released.
    # Audit failure must never block a legitimate GDPR erasure request.
    try:
        _memory.record(
            event_type="GRAPH_WIPE",
            notes=f"{node_count} nodes and {edge_count} edges deleted.",
            context={"nodes_deleted": node_count, "edges_deleted": edge_count},
        )
    except Exception:
        pass

    return {"nodes_deleted": node_count, "edges_deleted": edge_count}


# ---------------------------------------------------------------------------
# INTERNAL: CONCEPT EXTRACTION — RAKE-inspired
# ---------------------------------------------------------------------------

def _extract_concepts(text: str) -> List[str]:
    """
    Extract meaningful concepts using a RAKE-inspired scoring approach.

    Scientific basis: RAKE (Rose et al. 2010) — content-bearing words
    co-occur with many distinct other words (high degree) while functional
    words repeat frequently in isolation (high frequency). Score =
    degree / frequency rewards content-bearing words over functional.

    Stage 2 upgrade: replace entirely with spaCy NER + noun phrases.
    Contract: receives str, returns list[str]. No other code changes.
    """
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9]*", text.lower())
    filtered = [
        t for t in tokens
        if len(t) >= MIN_CONCEPT_LENGTH and t not in _STOPWORDS
    ]

    if not filtered:
        return []

    # Build local word co-occurrence graph for RAKE scoring
    word_freq: Dict[str, int] = {}
    word_degree: Dict[str, int] = {}

    for i, word in enumerate(filtered):
        word_freq[word] = word_freq.get(word, 0) + 1
        # Co-occurrence window: ±2 positions
        window = filtered[max(0, i - 2): i] + filtered[i + 1: i + 3]
        word_degree[word] = word_degree.get(word, 0) + len(window)

    # RAKE score: degree/frequency
    seen: Set[str] = set()
    scored: List[Tuple[float, str]] = []
    for word in filtered:
        if word not in seen:
            score = (word_degree.get(word, 0) + 1.0) / word_freq.get(word, 1)
            scored.append((score, word))
            seen.add(word)

    scored.sort(reverse=True)
    top_words = [w for _, w in scored]
    top_word_set = set(top_words[:20])

    # Build bigrams from adjacent top-scored filtered tokens
    bigrams: List[str] = []
    for i in range(len(filtered) - 1):
        if filtered[i] in top_word_set and filtered[i + 1] in top_word_set:
            bigrams.append(filtered[i] + " " + filtered[i + 1])
    bigrams = list(dict.fromkeys(bigrams))

    # Bigrams first (more specific), then top unigrams
    combined = list(dict.fromkeys(bigrams + top_words))
    return combined[:MAX_CONCEPTS_PER_INPUT]


# ---------------------------------------------------------------------------
# INTERNAL: SENSITIVITY DETECTION
# ---------------------------------------------------------------------------

def _contains_crisis(text: str) -> bool:
    """Crisis-level content detection. These are NEVER stored."""
    t = text.lower()
    return any(c in t for c in _CRISIS_CONCEPTS)


def _contains_sensitive(text: str) -> bool:
    """Sensitive content detection. Triggers reduced reinforcement."""
    t = text.lower()
    return any(c in t for c in _SENSITIVE_CONCEPTS)


# ---------------------------------------------------------------------------
# INTERNAL: NODE OPERATIONS
# ---------------------------------------------------------------------------

def _upsert_node(
    conn: sqlite3.Connection,
    concept: str,
    now: str,
    is_sensitive: int,
) -> Tuple[str, bool]:
    """
    Insert a new node or reinforce an existing one.
    Increments times_seen (total mentions) and inputs_seen (distinct inputs).
    inputs_seen is the IDF denominator — never double-counted within a session
    because relate() is called once per user input.
    Returns (node_id, created: bool).
    """
    row = conn.execute(
        "SELECT id FROM graph_nodes WHERE concept = ?", (concept,)
    ).fetchone()

    if row:
        conn.execute(
            """UPDATE graph_nodes
               SET last_seen    = ?,
                   times_seen   = times_seen + 1,
                   inputs_seen  = inputs_seen + 1,
                   is_sensitive = MAX(is_sensitive, ?)
               WHERE id = ?""",
            (now, is_sensitive, row["id"]),
        )
        return row["id"], False

    node_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO graph_nodes
           (id, concept, first_seen, last_seen, times_seen, inputs_seen, is_sensitive)
           VALUES (?, ?, ?, ?, 1, 1, ?)""",
        (node_id, concept, now, now, is_sensitive),
    )
    return node_id, True


# ---------------------------------------------------------------------------
# INTERNAL: EDGE OPERATIONS
# ---------------------------------------------------------------------------

def _upsert_edge(
    conn: sqlite3.Connection,
    source_id: str,
    target_id: str,
    now: str,
    reinforcement: float,
    is_sensitive: int,
) -> bool:
    """
    Insert a new edge or reinforce an existing one.

    Spacing effect (Cepeda et al. 2006; Pavlik & Anderson 2005):
      The reinforcement increment scales with days since last access.
      Revisiting after partial decay is more durable than immediate review.
      Implemented via _spacing_increment().

    Direction normalised by UUID comparison — (A,B) and (B,A) are the
    same edge. Symmetric co-occurrence is correct for Stage 1.
    Stage 2: directed edges for typed relationships (is-a, causes, etc).

    Returns True if created, False if reinforced.
    """
    a, b = (
        (source_id, target_id)
        if source_id < target_id
        else (target_id, source_id)
    )

    row = conn.execute(
        """SELECT id, weight, last_reinforced
           FROM graph_edges
           WHERE source_node_id = ? AND target_node_id = ?""",
        (a, b),
    ).fetchone()

    if row:
        days_since = _days_since(
            row["last_reinforced"], datetime.now(timezone.utc)
        )
        scaled = _spacing_increment(reinforcement, days_since)
        new_weight = min(1.0, row["weight"] + scaled)
        conn.execute(
            """UPDATE graph_edges
               SET weight              = ?,
                   reinforcement_count = reinforcement_count + 1,
                   last_reinforced     = ?,
                   is_sensitive        = MAX(is_sensitive, ?)
               WHERE id = ?""",
            (round(new_weight, 4), now, is_sensitive, row["id"]),
        )
        return False

    conn.execute(
        """INSERT INTO graph_edges
           (id, source_node_id, target_node_id, weight,
            reinforcement_count, created_at, last_reinforced, is_sensitive)
           VALUES (?, ?, ?, 0.5, 1, ?, ?, ?)""",
        (str(uuid.uuid4()), a, b, now, now, is_sensitive),
    )
    return True


def _spacing_increment(base: float, days_since: float) -> float:
    """
    Scale reinforcement by time elapsed since last access.

    Scientific basis: Pavlik & Anderson (2005) — benefit of a practice
    event is greater when the memory has partially decayed (spacing effect).

    At 0 days:  factor = 1.00 — immediate re-study, full base increment
    At 1 day:   factor ≈ 1.20
    At 7 days:  factor ≈ 1.61
    At 30 days: factor = 2.00 — maximum, after month-long gap
    """
    factor = 1.0 + min(1.0, math.log1p(days_since) / math.log1p(30))
    return base * factor


def _concept_pairs(
    node_ids: Dict[str, str],
) -> List[Tuple[str, str, str, str]]:
    """
    Generate all unique concept pairs from the input.
    Returns (source_id, target_id, source_concept, target_concept).

    O(N²) — capped at MAX_CONCEPTS_PER_INPUT=15 -> 105 pairs maximum.
    Stage 2: sliding-window or PPMI-threshold filtering to reduce
    spurious long-distance edges.
    """
    items = list(node_ids.items())  # [(concept, id), ...]
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            src_concept, src_id = items[i]
            tgt_concept, tgt_id = items[j]
            pairs.append((src_id, tgt_id, src_concept, tgt_concept))
    return pairs


# ---------------------------------------------------------------------------
# INTERNAL: BFS TRAVERSAL WITH FAN EFFECT
# ---------------------------------------------------------------------------

def _bfs_navigate(
    conn: sqlite3.Connection,
    seed_concepts: List[str],
    total_inputs: int,
    include_sensitive: bool,
) -> List[Dict[str, Any]]:
    """
    Breadth-first traversal from seed nodes with ACT-R fan effect.

    Fan effect (Anderson 1983): activation from a source is divided among
    all its connections. High-degree nodes spread less per path. This
    prevents generic hub concepts from dominating context results —
    being connected to everything is not the same as being relevant.

    If a concept is reachable via multiple paths, the highest effective
    weight is kept.

    Stage 2 upgrade: Personalized PageRank (PPR). PPR handles multi-hop
    reasoning gracefully, incorporates global graph structure, and has
    been validated in HippoRAG (2024), LinearRAG (2025), MixPR (2024).
    """
    now_dt = datetime.now(timezone.utc)

    seed_ids: set = set()
    for concept in seed_concepts:
        row = conn.execute(
            "SELECT id FROM graph_nodes WHERE concept = ?", (concept,)
        ).fetchone()
        if row:
            seed_ids.add(row["id"])

    if not seed_ids:
        return []

    visited = set(seed_ids)
    frontier = set(seed_ids)
    results: Dict[str, Dict[str, Any]] = {}

    for _depth in range(MAX_NAVIGATE_DEPTH):
        if not frontier:
            break
        next_frontier: set = set()

        for node_id in frontier:
            neighbours = _get_neighbours(conn, node_id, include_sensitive)
            source_degree = len(neighbours)

            # Fan effect: dilute activation by log of source degree
            fan_dilution = (
                1.0 / math.log1p(source_degree) if source_degree > 1 else 1.0
            )

            src_row = conn.execute(
                "SELECT times_seen FROM graph_nodes WHERE id = ?", (node_id,)
            ).fetchone()
            src_times = src_row["times_seen"] if src_row else 1

            for (
                neighbour_id,
                base_weight,
                last_reinforced_str,
                r_count,
                n_is_sensitive,
            ) in neighbours:

                if neighbour_id in visited:
                    continue

                node_row = conn.execute(
                    """SELECT concept, times_seen, inputs_seen, is_sensitive
                       FROM graph_nodes WHERE id = ?""",
                    (neighbour_id,),
                ).fetchone()
                if not node_row:
                    continue

                degree = _get_degree(conn, neighbour_id)
                days_since = _days_since(last_reinforced_str, now_dt)

                effective = _effective_weight(
                    base_weight=base_weight,
                    days_since=days_since,
                    times_seen=node_row["times_seen"],
                    inputs_seen=node_row["inputs_seen"],
                    degree=degree,
                    reinforcement_count=r_count,
                    src_times_seen=src_times,
                    fan_dilution=fan_dilution,
                    total_inputs=total_inputs,
                    is_sensitive=bool(n_is_sensitive),
                )

                concept = node_row["concept"]
                if (
                    concept not in results
                    or effective > results[concept]["effective_weight"]
                ):
                    results[concept] = {
                        "concept": concept,
                        "effective_weight": round(effective, 4),
                        "times_seen": node_row["times_seen"],
                        "inputs_seen": node_row["inputs_seen"],
                        "source": "graph",
                        "days_since": round(days_since, 2),
                        "complexity": degree,
                        "is_sensitive": bool(node_row["is_sensitive"]),
                    }

                visited.add(neighbour_id)
                next_frontier.add(neighbour_id)

        frontier = next_frontier

    return sorted(
        results.values(),
        key=lambda r: r["effective_weight"],
        reverse=True,
    )[:MAX_NAVIGATE_RESULTS]


def _get_neighbours(
    conn: sqlite3.Connection,
    node_id: str,
    include_sensitive: bool,
) -> List[Tuple[str, float, str, int, int]]:
    """
    Return (neighbour_id, weight, last_reinforced, reinforcement_count,
    is_sensitive) for all connected edges, ordered by weight descending.

    Two explicit query strings rather than f-string interpolation — avoids
    security linter warnings even though the filter value is a static constant.
    """
    _SQL_ALL = """
        SELECT
            CASE
                WHEN source_node_id = ? THEN target_node_id
                ELSE source_node_id
            END AS neighbour_id,
            weight, last_reinforced, reinforcement_count, is_sensitive
        FROM graph_edges e
        WHERE (source_node_id = ? OR target_node_id = ?)
        ORDER BY weight DESC"""

    _SQL_SAFE = """
        SELECT
            CASE
                WHEN source_node_id = ? THEN target_node_id
                ELSE source_node_id
            END AS neighbour_id,
            weight, last_reinforced, reinforcement_count, is_sensitive
        FROM graph_edges e
        WHERE (source_node_id = ? OR target_node_id = ?)
        AND e.is_sensitive = 0
        ORDER BY weight DESC"""

    query = _SQL_ALL if include_sensitive else _SQL_SAFE
    rows = conn.execute(query, (node_id, node_id, node_id)).fetchall()
    return [
        (
            r["neighbour_id"],
            r["weight"],
            r["last_reinforced"],
            r["reinforcement_count"],
            r["is_sensitive"],
        )
        for r in rows
    ]


def _get_degree(conn: sqlite3.Connection, node_id: str) -> int:
    """Return degree (edge count) of a node — the Complexity axis."""
    row = conn.execute(
        """SELECT COUNT(*) AS degree FROM graph_edges
           WHERE source_node_id = ? OR target_node_id = ?""",
        (node_id, node_id),
    ).fetchone()
    return row["degree"] if row else 0


def _get_total_inputs(conn: sqlite3.Connection) -> int:
    """Total distinct inputs processed — denominator for IDF."""
    row = conn.execute(
        "SELECT value FROM graph_metadata WHERE key = 'total_inputs_processed'"
    ).fetchone()
    try:
        return max(1, int(row["value"])) if row else 1
    except (ValueError, TypeError):
        return 1


# ---------------------------------------------------------------------------
# INTERNAL: FIVE-FACTOR EFFECTIVE WEIGHT
# ---------------------------------------------------------------------------

def _effective_weight(
    base_weight: float,
    days_since: float,
    times_seen: int,
    inputs_seen: int,
    degree: int,
    reinforcement_count: int,
    src_times_seen: int,
    fan_dilution: float,
    total_inputs: int,
    is_sensitive: bool = False,
) -> float:
    """
    Compute the effective weight of a relationship for navigation.

    Five factors, all multiplied. Final result clamped to [0.0, 1.0].

    Axis 1 — Distance (power-law temporal decay):
        base_weight x (1 + days)^(-d)
        Scientific basis: Wixted (2004); Rubin & Wenzel (1996).
        Power law is the empirically correct forgetting model.
        Jost's Law (1897): older memories decay proportionally more slowly.
        Exponential decay violates this; power law satisfies it.
        Sensitive edges: d x 1.4 for faster forgetting of distress content.

    Axis 2 — Size (TF-IDF inspired):
        TF: log-normalised mention frequency
        IDF: log(total_inputs / inputs_seen) — rarer = more discriminative
        Scientific basis: Sparck Jones (1972); Robertson & Zaragoza (2009).
        Without IDF, generic concepts drown out specific ones.

    Axis 3 — Complexity (degree, capped at 20, +15% max):
        Well-connected nodes are slightly boosted. Capped to prevent
        hub dominance. High-degree nodes are already penalised by fan
        effect and IDF — cap prevents over-penalisation of well-connected
        but genuinely important concepts.

    PPMI approximation (Bullinaria & Levy 2007):
        Rewards pairs that co-occur more than frequency alone predicts.
        Full PPMI requires a global co-occurrence matrix (Stage 2).
        Stage 1 approximation: reinforcement_count / sqrt(times_a x times_b + 1)
        Range mapped to [0.5, 1.5].

    Fan effect (ACT-R, Anderson 1983):
        Pre-computed activation dilution. Accounts for the split of
        activation across all of the source node's connections.
    """
    # Axis 1: Distance
    exponent = DECAY_EXPONENT * 1.4 if is_sensitive else DECAY_EXPONENT
    distance_factor = (1.0 + days_since) ** (-exponent)

    # Axis 2: Size (TF-IDF)
    tf = math.log1p(times_seen) / math.log1p(100)
    idf = math.log((total_inputs + 1.0) / (inputs_seen + 1.0)) + 1.0
    idf = min(idf, 3.0)  # cap to prevent extreme scores on very rare concepts
    size_factor = 1.0 + 0.25 * tf * idf

    # Axis 3: Complexity
    complexity_factor = 1.0 + 0.15 * min(1.0, degree / 20.0)

    # PPMI approximation
    expected = math.sqrt(float(times_seen) * float(src_times_seen) + 1.0)
    pmi_raw = float(reinforcement_count) / expected
    pmi_factor = 0.5 + min(1.0, pmi_raw)  # range [0.5, 1.5]

    effective = (
        base_weight
        * distance_factor
        * size_factor
        * complexity_factor
        * pmi_factor
        * fan_dilution
    )
    return min(1.0, max(0.0, effective))


# ---------------------------------------------------------------------------
# INTERNAL: UTILITIES
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(dt_str: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _days_since(dt_str: str, now_dt: datetime) -> float:
    dt = _parse_dt(dt_str)
    if dt is None:
        return 0.0
    return max(0.0, (now_dt - dt).total_seconds() / 86400.0)


def _empty_relate_result() -> Dict[str, Any]:
    return {
        "concepts": [],
        "nodes_created": 0,
        "nodes_reinforced": 0,
        "edges_created": 0,
        "edges_reinforced": 0,
        "crisis_detected": False,
        "sensitive_detected": False,
    }
