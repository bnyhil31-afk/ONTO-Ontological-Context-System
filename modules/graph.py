"""
modules/graph.py

THE RELATIONSHIP GRAPH — the heart of ONTO.

Phase 1: Ontology Core v2 (DESIGN-SPEC-001 v1.1)

New in Phase 1:
    - Typed directed edges (edge_types registry, 16 standard types)
    - Provenance and trust scoring (source_type, trust_score)
    - Personalized PageRank via fast-pagerank (BFS fallback for small graphs)
    - PPMI incremental counters with lazy weight computation
    - Per-user decay profiles (5 seeded profiles, env var selection)
    - YAKE-inspired concept extraction (replaces RAKE, pluggable interface)
    - All Phase 2-4 schema columns added now (NULL until activated)
    - One-time 14-step migration — no future ALTER TABLE ever needed

Governing axiom (DESIGN-SPEC-001):
    One schema migration, ever. All columns for all phases are present
    after the first Phase 1 boot. Logic activates in each phase. No
    future ALTER TABLE. No migration scripts. No operator downtime.

Scientific basis (Stage 1, preserved):
    - Power-law decay (Wixted 2004, Jost's Law 1897)
    - Spacing-effect reinforcement (Cepeda et al. 2006)
    - TF-IDF Size axis (Sparck Jones 1972)
    - PPMI-approximation (Bullinaria & Levy 2007; Levy et al. 2015)
    - ACT-R fan effect (Anderson 1983)
    - Wellbeing protection (Nolen-Hoeksema 1991, 2008)
    - GDPR Article 17 right to erasure

Scientific basis (Phase 1, new):
    - Personalized PageRank (Page et al. 1999; Gleich 2015)
    - YAKE keyword extraction (Campos et al. 2020)
    - Context smoothing α=0.75 (Levy, Goldberg & Dagan 2015)

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import math
import os
import re
import sqlite3
import sys
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import memory as _memory  # noqa: E402

# ---------------------------------------------------------------------------
# OPTIONAL DEPENDENCIES (graceful fallback if not installed)
# ---------------------------------------------------------------------------

try:
    from fast_pagerank import pagerank_power  # type: ignore
    import scipy.sparse as _sp               # type: ignore
    import numpy as _np                       # type: ignore
    _PPR_AVAILABLE = True
except ImportError:
    pagerank_power = None  # type: ignore
    _sp = None             # type: ignore
    _np = None             # type: ignore
    _PPR_AVAILABLE = False

try:
    import psutil as _psutil  # type: ignore
    _PSUTIL_AVAILABLE = True
except ImportError:
    _psutil = None            # type: ignore
    _PSUTIL_AVAILABLE = False

# ---------------------------------------------------------------------------
# HARDWARE TIER DETECTION
# ---------------------------------------------------------------------------

def _detect_hardware_tier() -> str:
    """Detect available RAM and return hardware tier string."""
    if _PSUTIL_AVAILABLE:
        available_mb = _psutil.virtual_memory().available / (1024 * 1024)
        if available_mb < 512:
            return "pi"
        if available_mb < 2048:
            return "laptop"
        return "enterprise"
    return "laptop"  # safe default

_HARDWARE_TIER: str = _detect_hardware_tier()
_MAX_PPR_NODES: int = {
    "pi": 5_000,
    "laptop": 50_000,
    "enterprise": 500_000,
}[_HARDWARE_TIER]

# ---------------------------------------------------------------------------
# CONFIGURATION — Stage 1 (preserved)
# ---------------------------------------------------------------------------

DECAY_EXPONENT = float(os.getenv("ONTO_GRAPH_DECAY_EXPONENT", "0.5"))
PRUNE_THRESHOLD = float(os.getenv("ONTO_GRAPH_PRUNE_THRESHOLD", "0.05"))
MAX_RESULTS = int(os.getenv("ONTO_GRAPH_MAX_RESULTS", "20"))
MAX_DEPTH = int(os.getenv("ONTO_GRAPH_MAX_DEPTH", "2"))
MAX_CONCEPTS_PER_INPUT = int(os.getenv("ONTO_GRAPH_MAX_CONCEPTS", "15"))
BASE_REINFORCEMENT = float(os.getenv("ONTO_GRAPH_BASE_REINFORCEMENT", "0.08"))
SENSITIVE_REINFORCEMENT = float(
    os.getenv("ONTO_GRAPH_SENSITIVE_REINFORCEMENT", "0.02")
)

# Phase 1 — PPR
_PPR_MIN_GRAPH_SIZE = 200    # below this, BFS is more meaningful than PPR
_PPR_MIN_AVG_DEGREE = 3.0   # below this, PPR degenerates toward uniform
PPR_ALPHA_CONTEXTUALIZE = float(os.getenv("ONTO_PPR_ALPHA_CONTEXTUALIZE", "0.85"))
PPR_ALPHA_SURFACE       = float(os.getenv("ONTO_PPR_ALPHA_SURFACE",       "0.80"))
PPR_ALPHA_MEMORY        = float(os.getenv("ONTO_PPR_ALPHA_MEMORY",        "0.90"))

# Phase 1 — PPMI
PPMI_PRUNE_THRESHOLD  = float(os.getenv("ONTO_PPMI_PRUNE_THRESHOLD", "0.5"))
_PPMI_SMOOTHING_ALPHA = 0.75  # Levy et al. (2015) — not user-configurable

# Phase 1 — Trust
TRUST_THRESHOLD_FLAG       = float(os.getenv("ONTO_TRUST_THRESHOLD_FLAG",       "0.5"))
TRUST_THRESHOLD_CHECKPOINT = float(os.getenv("ONTO_TRUST_THRESHOLD_CHECKPOINT", "0.2"))

# Phase 1 — Decay profile selection
DEFAULT_DECAY_PROFILE = os.getenv("ONTO_DECAY_PROFILE", "standard")

# Phase 4 (present, dormant until Phase 4 activates it)
EMBEDDING_ALPHA = float(os.getenv("ONTO_EMBEDDING_ALPHA", "0.7"))

# ---------------------------------------------------------------------------
# WELLBEING PROTECTION LAYER (Stage 1 — preserved exactly)
# Scientific basis: Nolen-Hoeksema (1991, 2008); Colombetti & Roberts (2024)
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
# CONCEPT EXTRACTOR PROTOCOL + YAKE IMPLEMENTATION (DESIGN-SPEC-001 §5)
# ---------------------------------------------------------------------------

class ConceptExtractor(Protocol):
    """
    The extractor contract. Implement this to replace the default extractor.
    Never raises. Returns empty list on failure.
    Called by: tests (MockExtractor), Phase 4 boot (SpacyExtractor).
    """
    def extract(self, text: str, max_concepts: int = 15) -> List[str]: ...
    def get_version(self) -> str: ...
    def get_model_name(self) -> str: ...


class YAKEExtractor:
    """
    YAKE-inspired concept extractor. stdlib only, zero dependencies.

    Five features mapped to ONTO's three governing axes:
        Casing + Position  → Distance (how central is this concept?)
        Frequency          → Size (how common is this concept?)
        Context diversity
        + Sentence spread  → Complexity (how many contexts?)

    Scientific basis: Campos et al. (2020) "YAKE! Keyword extraction
    from single documents using multiple local features."
    Outperforms RAKE on F1 across standard benchmarks.

    Stage 1 upgrade from RAKE: adds casing and position signals,
    replaces degree/frequency ratio with full five-feature score.
    Contract: receives str, returns list[str]. Unchanged from RAKE.
    """

    def get_version(self) -> str:
        return "1.0.0"

    def get_model_name(self) -> str:
        return "yake-stdlib"

    def extract(self, text: str, max_concepts: int = 15) -> List[str]:
        if not text or not text.strip():
            return []
        try:
            return _yake_extract(text, max_concepts)
        except Exception:
            return []


_EXTRACTOR: ConceptExtractor = YAKEExtractor()
_extractor_lock = threading.Lock()


def set_extractor(extractor: ConceptExtractor) -> None:
    """
    Swap the active concept extractor. Thread-safe.
    Change is written to audit trail.
    Called by tests (MockExtractor) and Phase 4 boot (SpacyExtractor).
    """
    global _EXTRACTOR
    with _extractor_lock:
        old_name = _EXTRACTOR.get_model_name()
        _EXTRACTOR = extractor
    try:
        _memory.record(
            event_type="EXTRACTOR_SWAP",
            notes=(
                f"Concept extractor changed: "
                f"{old_name} → {extractor.get_model_name()}"
            ),
            context={"from": old_name, "to": extractor.get_model_name()},
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# MODULE-LEVEL STATE
# ---------------------------------------------------------------------------

_lock = threading.RLock()  # RLock: same thread can re-enter (PPR + navigate)

# PPR cache — invalidated after every graph.relate() write
_ppr_matrix: Optional[Any] = None
_ppr_node_ids: Optional[List[int]] = None
_ppr_cache_valid: bool = False

# ---------------------------------------------------------------------------
# PRIVATE: DATABASE CONNECTION
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
# PRIVATE: SCHEMA HELPERS
# ---------------------------------------------------------------------------

def _safe_add_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    typedef: str,
) -> None:
    """
    Add a column if it does not already exist. Idempotent.
    SQLite raises OperationalError on duplicate column — we catch it.
    """
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")
    except sqlite3.OperationalError:
        pass  # column already exists — correct behavior


def _backfill_provenance(conn: sqlite3.Connection) -> None:
    """
    Create a synthetic provenance record and assign it to all graph_nodes
    and graph_edges where provenance_id IS NULL.

    Runs exactly once (checks for existing backfill record before creating).
    Decision: DESIGN-SPEC-001 Part X, Decision 2.
    source_type='system', trust_score=0.90.
    """
    existing = conn.execute(
        "SELECT id FROM provenance WHERE source_id = 'historical_backfill' LIMIT 1"
    ).fetchone()
    if existing:
        return

    now = datetime.now(timezone.utc).timestamp()
    with conn:
        conn.execute(
            "INSERT INTO provenance (source_type, source_id, trust_score, created_at) "
            "VALUES ('system', 'historical_backfill', 0.90, ?)",
            (now,),
        )
        prov_row = conn.execute(
            "SELECT id FROM provenance WHERE source_id = 'historical_backfill'"
        ).fetchone()
        if not prov_row:
            return
        prov_id = prov_row["id"]
        conn.execute(
            "UPDATE graph_nodes SET provenance_id = ? WHERE provenance_id IS NULL",
            (prov_id,),
        )
        conn.execute(
            "UPDATE graph_edges SET provenance_id = ? WHERE provenance_id IS NULL",
            (prov_id,),
        )


def _seed_ppmi_counters(conn: sqlite3.Connection) -> None:
    """
    Seed ppmi_counters from existing edge data if the table is empty.
    Gives existing graphs a starting point for PPMI computation.
    Uses edge degree as the initial marginal count approximation.
    """
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM ppmi_counters"
    ).fetchone()["c"]
    if count > 0:
        return  # already seeded

    with conn:
        conn.execute("""
            INSERT OR IGNORE INTO ppmi_counters (node_id, marginal_count)
            SELECT source_node_id, COUNT(*)
            FROM graph_edges
            GROUP BY source_node_id
        """)
        conn.execute("""
            INSERT INTO ppmi_counters (node_id, marginal_count)
            SELECT target_node_id, COUNT(*)
            FROM graph_edges
            GROUP BY target_node_id
            ON CONFLICT(node_id) DO UPDATE
            SET marginal_count = marginal_count + excluded.marginal_count
        """)
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM graph_edges"
        ).fetchone()["c"]
        conn.execute(
            "UPDATE ppmi_global SET value = ? WHERE key = 'total_co_occurrences'",
            (float(total),),
        )


# ---------------------------------------------------------------------------
# PRIVATE: PROVENANCE HELPERS
# ---------------------------------------------------------------------------

_TRUST_BY_SOURCE: Dict[str, float] = {
    "human":   0.95,
    "sensor":  0.85,
    "llm":     0.30,
    "derived": 0.60,
    "system":  0.90,
}


def _create_provenance(
    conn: sqlite3.Connection,
    source_type: str = "human",
    session_hash: Optional[str] = None,
    content_hash: Optional[str] = None,
) -> int:
    """
    Insert a provenance record and return its integer id.
    trust_score is set from the source_type default table.
    """
    trust = _TRUST_BY_SOURCE.get(source_type, 0.50)
    now = datetime.now(timezone.utc).timestamp()
    cursor = conn.execute(
        "INSERT INTO provenance (source_type, session_hash, trust_score, "
        "content_hash, created_at) VALUES (?, ?, ?, ?, ?)",
        (source_type, session_hash, trust, content_hash, now),
    )
    return cursor.lastrowid  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# PRIVATE: PPMI HELPERS
# ---------------------------------------------------------------------------

def _update_ppmi_counters(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
) -> None:
    """
    Increment PPMI marginal counts for source and target.
    Increment the global total co-occurrence counter.
    Invalidate cached ppmi_weight for this edge.
    Called inside relate() after every edge write.
    """
    for node_id in (source_id, target_id):
        conn.execute(
            "INSERT INTO ppmi_counters (node_id, marginal_count) "
            "VALUES (?, 1.0) "
            "ON CONFLICT(node_id) DO UPDATE "
            "SET marginal_count = marginal_count + 1.0",
            (node_id,),
        )
    conn.execute(
        "UPDATE ppmi_global SET value = value + 1.0 "
        "WHERE key = 'total_co_occurrences'"
    )
    conn.execute(
        "UPDATE graph_edges "
        "SET ppmi_weight = NULL, ppmi_at = NULL "
        "WHERE source_node_id = ? AND target_node_id = ?",
        (source_id, target_id),
    )


def _compute_ppmi(
    source_id: int,
    target_id: int,
    edge_weight: float,
    conn: sqlite3.Connection,
) -> float:
    """
    Lazily compute PPMI for an edge from stored counters.

    Formula: max(0, log₂(P(A,B) / (P(A) × P(B)^α)))
    Context smoothing α=0.75 applied to target (Levy et al. 2015).
    Returns 0.0 if counters are insufficient for computation.
    """
    try:
        total_row = conn.execute(
            "SELECT value FROM ppmi_global WHERE key = 'total_co_occurrences'"
        ).fetchone()
        if not total_row or total_row["value"] <= 0:
            return 0.0
        total_n = total_row["value"]

        src_row = conn.execute(
            "SELECT marginal_count FROM ppmi_counters WHERE node_id = ?",
            (source_id,),
        ).fetchone()
        tgt_row = conn.execute(
            "SELECT marginal_count FROM ppmi_counters WHERE node_id = ?",
            (target_id,),
        ).fetchone()
        if not src_row or not tgt_row:
            return 0.0

        p_ab = edge_weight / total_n
        p_a = src_row["marginal_count"] / total_n
        p_b_smoothed = (tgt_row["marginal_count"] / total_n) ** _PPMI_SMOOTHING_ALPHA

        if p_a <= 0 or p_b_smoothed <= 0 or p_ab <= 0:
            return 0.0

        return max(0.0, math.log2(p_ab / (p_a * p_b_smoothed)))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# PRIVATE: PPR HELPERS
# ---------------------------------------------------------------------------

def _build_ppr_matrix(
    conn: sqlite3.Connection,
    edge_type_ids: Optional[List[int]] = None,
) -> Tuple[Optional[Any], Optional[List[int]]]:
    """
    Build a scipy CSR matrix from graph_edges for PPR computation.
    Respects hardware tier node limit.
    Returns (matrix, node_ids_list) or (None, None) on any failure.
    """
    if not _PPR_AVAILABLE:
        return None, None

    nodes = conn.execute(
        "SELECT id FROM graph_nodes ORDER BY id LIMIT ?",
        (_MAX_PPR_NODES,),
    ).fetchall()
    if len(nodes) < _PPR_MIN_GRAPH_SIZE:
        return None, None

    node_ids = [r["id"] for r in nodes]
    id_to_idx: Dict[int, int] = {nid: i for i, nid in enumerate(node_ids)}
    n = len(node_ids)

    if edge_type_ids:
        placeholders = ",".join("?" * len(edge_type_ids))
        edges = conn.execute(
            f"SELECT source_node_id, target_node_id, weight "
            f"FROM graph_edges WHERE edge_type_id IN ({placeholders}) "
            f"AND is_deleted = 0",
            edge_type_ids,
        ).fetchall()
    else:
        edges = conn.execute(
            "SELECT source_node_id, target_node_id, weight "
            "FROM graph_edges WHERE is_deleted = 0"
        ).fetchall()

    rows: List[int] = []
    cols: List[int] = []
    data: List[float] = []

    for e in edges:
        src = id_to_idx.get(e["source_node_id"])
        tgt = id_to_idx.get(e["target_node_id"])
        if src is None or tgt is None:
            continue
        w = float(e["weight"]) if e["weight"] and e["weight"] > 0 else 1.0
        rows.append(src); cols.append(tgt); data.append(w)
        rows.append(tgt); cols.append(src); data.append(w)  # undirected

    if not rows:
        return None, None

    matrix = _sp.csr_matrix(
        (_np.array(data), (_np.array(rows), _np.array(cols))),
        shape=(n, n),
    )
    return matrix, node_ids


# ---------------------------------------------------------------------------
# PUBLIC: INITIALIZE — 14-step migration (DESIGN-SPEC-001 §9.2)
# ---------------------------------------------------------------------------

def initialize() -> None:
    """
    Create all tables, indexes, and seed data. Idempotent. Call at every boot.

    Runs the full 14-step migration in a single transaction. Any failure
    rolls back completely — the database is never left in a partial state.

    Governing axiom: One schema migration, ever.
    All columns for all phases (P1-P4) are added here. Logic for P2-P4
    columns activates in their respective phases. No future ALTER TABLE.
    """
    conn = _get_conn()
    try:
        with conn:
            now = datetime.now(timezone.utc).timestamp()

            # -----------------------------------------------------------------
            # Ensure Stage 1 base tables exist (idempotent)
            # -----------------------------------------------------------------
            conn.execute("""
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid            TEXT    UNIQUE NOT NULL,
                    concept         TEXT    UNIQUE NOT NULL,
                    weight          REAL    NOT NULL DEFAULT 0.0,
                    times_seen      INTEGER NOT NULL DEFAULT 0,
                    inputs_seen     INTEGER NOT NULL DEFAULT 0,
                    is_sensitive    INTEGER NOT NULL DEFAULT 0,
                    created_at      REAL    NOT NULL,
                    last_reinforced REAL    NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS graph_edges (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_node_id  INTEGER NOT NULL REFERENCES graph_nodes(id),
                    target_node_id  INTEGER NOT NULL REFERENCES graph_nodes(id),
                    weight          REAL    NOT NULL DEFAULT 0.0,
                    times_seen      INTEGER NOT NULL DEFAULT 0,
                    is_sensitive    INTEGER NOT NULL DEFAULT 0,
                    last_reinforced REAL    NOT NULL,
                    UNIQUE(source_node_id, target_node_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS graph_metadata (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT OR IGNORE INTO graph_metadata (key, value) "
                "VALUES ('total_inputs_processed', '0')"
            )

            # -----------------------------------------------------------------
            # STEP 1: edge_types registry
            # -----------------------------------------------------------------
            conn.execute("""
                CREATE TABLE IF NOT EXISTS edge_types (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT    UNIQUE NOT NULL,
                    category    TEXT    NOT NULL
                                        CHECK (category IN (
                                            'taxonomic','mereological','causal',
                                            'associative','temporal','spatial',
                                            'epistemic'
                                        )),
                    inverse_id  INTEGER REFERENCES edge_types(id),
                    description TEXT    NOT NULL,
                    is_directed INTEGER NOT NULL DEFAULT 1,
                    created_at  REAL    NOT NULL,
                    is_sealed   INTEGER NOT NULL DEFAULT 0
                )
            """)

            # -----------------------------------------------------------------
            # STEP 2: Seed 16 standard edge types
            # -----------------------------------------------------------------
            _EDGE_TYPES = [
                # (id, name, category, inverse_id, description, is_directed)
                (1,  "related-to",     "associative",  None, "General association (SKOS skos:related)",          0),
                (2,  "co-occurs-with", "associative",  None, "Statistical co-occurrence (ONTO native, default)", 0),
                (3,  "is-a",           "taxonomic",    4,    "Subclass/subtype (RDFS rdfs:subClassOf)",          1),
                (4,  "has-subtype",    "taxonomic",    3,    "Inverse of is-a",                                  1),
                (5,  "instance-of",    "taxonomic",    6,    "Instance of a class (OWL classAssertion)",         1),
                (6,  "has-instance",   "taxonomic",    5,    "Inverse of instance-of",                           1),
                (7,  "part-of",        "mereological", 8,    "Constituent part (BFO RO:0001001)",                1),
                (8,  "has-part",       "mereological", 7,    "Inverse of part-of",                               1),
                (9,  "causes",         "causal",       10,   "Causal relationship (RO:0002410)",                 1),
                (10, "caused-by",      "causal",       9,    "Inverse of causes",                                1),
                (11, "precedes",       "temporal",     12,   "Temporal precedence (OWL-Time time:before)",       1),
                (12, "follows",        "temporal",     11,   "Inverse of precedes",                              1),
                (13, "located-in",     "spatial",      14,   "Spatial containment (GeoSPARQL)",                  1),
                (14, "contains",       "spatial",      13,   "Inverse of located-in",                            1),
                (15, "supports",       "epistemic",    16,   "Evidential support (ONTO native)",                 1),
                (16, "supported-by",   "epistemic",    15,   "Inverse of supports",                              1),
            ]
            # Pass 1: insert all rows without inverse_id to avoid self-referential
            # FK violations (e.g. inserting id=3 with inverse_id=4 before id=4 exists).
            for et in _EDGE_TYPES:
                conn.execute(
                    "INSERT OR IGNORE INTO edge_types "
                    "(id, name, category, description, is_directed, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (et[0], et[1], et[2], et[4], et[5], now),
                )
            # Pass 2: set inverse_id now that all sibling rows exist.
            for et in _EDGE_TYPES:
                if et[3] is not None:
                    conn.execute(
                        "UPDATE edge_types SET inverse_id = ? "
                        "WHERE id = ? AND inverse_id IS NULL",
                        (et[3], et[0]),
                    )

            # -----------------------------------------------------------------
            # STEP 3: provenance (W3C PROV-DM compatible from day one)
            # P1 fields active; P2-P3 fields present but NULL
            # -----------------------------------------------------------------
            conn.execute("""
                CREATE TABLE IF NOT EXISTS provenance (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type      TEXT    NOT NULL
                                             CHECK (source_type IN (
                                                 'human','sensor','llm',
                                                 'derived','system')),
                    source_id        TEXT,
                    session_hash     TEXT,
                    trust_score      REAL    NOT NULL
                                             CHECK (trust_score >= 0.0
                                                AND trust_score <= 1.0),
                    content_hash     TEXT,
                    model_version    TEXT,
                    created_at       REAL    NOT NULL,
                    verified_at      REAL,
                    verified_by      TEXT,
                    prov_entity_id   TEXT,
                    prov_agent_id    TEXT,
                    prov_activity_id TEXT,
                    consent_id       TEXT,
                    origin_node_id   TEXT
                )
            """)

            # -----------------------------------------------------------------
            # STEP 4: ppmi_counters
            # -----------------------------------------------------------------
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ppmi_counters (
                    node_id        INTEGER PRIMARY KEY REFERENCES graph_nodes(id),
                    marginal_count REAL    NOT NULL DEFAULT 0.0,
                    last_decay_at  REAL
                )
            """)

            # -----------------------------------------------------------------
            # STEP 5: ppmi_global + seed rows
            # -----------------------------------------------------------------
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ppmi_global (
                    key   TEXT PRIMARY KEY,
                    value REAL NOT NULL
                )
            """)
            for k, v in [
                ("total_co_occurrences", 0.0),
                ("smoothing_alpha", _PPMI_SMOOTHING_ALPHA),
                ("decay_lambda", 0.95),
            ]:
                conn.execute(
                    "INSERT OR IGNORE INTO ppmi_global (key, value) VALUES (?, ?)",
                    (k, v),
                )

            # -----------------------------------------------------------------
            # STEP 6: decay_profiles + 5 seeded profiles
            # -----------------------------------------------------------------
            conn.execute("""
                CREATE TABLE IF NOT EXISTS decay_profiles (
                    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                    name                 TEXT    UNIQUE NOT NULL,
                    description          TEXT    NOT NULL,
                    lambda               REAL    NOT NULL DEFAULT 0.95
                                                 CHECK (lambda > 0.0 AND lambda <= 1.0),
                    epoch_seconds        INTEGER NOT NULL DEFAULT 86400,
                    min_weight           REAL    NOT NULL DEFAULT 0.01,
                    domain               TEXT,
                    is_default           INTEGER NOT NULL DEFAULT 0,
                    created_at           REAL    NOT NULL,
                    regulatory_framework TEXT,
                    min_retention_days   INTEGER
                )
            """)
            _PROFILES = [
                # (name, description, lambda, epoch_seconds, domain, is_default,
                #  regulatory_framework, min_retention_days)
                ("standard", "Default decay profile",
                 0.95, 86400,  "general",   1, "general", None),
                ("slow",     "Slow decay for medical or archival contexts",
                 0.99, 86400,  "medical",   0, "HIPAA",   365),
                ("fast",     "Fast decay for real-time event streams",
                 0.85, 3600,   "realtime",  0, "general", None),
                ("personal", "Personal knowledge assistant",
                 0.97, 43200,  "personal",  0, "GDPR",    None),
                ("financial","Financial services regulatory retention",
                 0.98, 86400,  "financial", 0, "GLBA",    2555),
            ]
            for p in _PROFILES:
                conn.execute(
                    "INSERT OR IGNORE INTO decay_profiles "
                    "(name, description, lambda, epoch_seconds, domain, "
                    "is_default, created_at, regulatory_framework, "
                    "min_retention_days) VALUES (?,?,?,?,?,?,?,?,?)",
                    (p[0], p[1], p[2], p[3], p[4], p[5], now, p[6], p[7]),
                )

            # -----------------------------------------------------------------
            # STEP 7: session_config (thin override layer)
            # -----------------------------------------------------------------
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_config (
                    session_hash       TEXT    PRIMARY KEY,
                    decay_profile_id   INTEGER REFERENCES decay_profiles(id),
                    regulatory_profile TEXT,
                    data_residency     TEXT,
                    created_at         REAL    NOT NULL
                )
            """)

            # -----------------------------------------------------------------
            # STEP 8: mcp_session_map (all phases present)
            # -----------------------------------------------------------------
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mcp_session_map (
                    mcp_session_id   TEXT PRIMARY KEY,
                    onto_token_hash  TEXT NOT NULL,
                    created_at       REAL NOT NULL,
                    last_active      REAL NOT NULL,
                    oauth_subject    TEXT,
                    oauth_scope      TEXT,
                    oauth_expires_at REAL,
                    origin_node_id   TEXT
                )
            """)

            # -----------------------------------------------------------------
            # STEP 9: ALTER TABLE graph_nodes — all P1-P4 columns
            # All idempotent via _safe_add_column
            # -----------------------------------------------------------------
            # [P1]
            _safe_add_column(conn, "graph_nodes", "provenance_id",     "INTEGER")
            _safe_add_column(conn, "graph_nodes", "domain",            "TEXT")
            # [P2]
            _safe_add_column(conn, "graph_nodes", "did_key",           "TEXT")
            _safe_add_column(conn, "graph_nodes", "valid_from",        "REAL")
            _safe_add_column(conn, "graph_nodes", "valid_to",          "REAL")
            _safe_add_column(conn, "graph_nodes", "is_deleted",
                             "INTEGER NOT NULL DEFAULT 0")
            # [P3]
            _safe_add_column(conn, "graph_nodes", "origin_node_id",    "TEXT")
            _safe_add_column(conn, "graph_nodes", "vector_clock",      "TEXT")
            _safe_add_column(conn, "graph_nodes", "crdt_state",        "TEXT")
            # [P4]
            _safe_add_column(conn, "graph_nodes", "embedding",         "BLOB")
            _safe_add_column(conn, "graph_nodes", "embedding_model",   "TEXT")
            _safe_add_column(conn, "graph_nodes", "embedding_version", "TEXT")
            _safe_add_column(conn, "graph_nodes", "embedding_hash",    "TEXT")
            _safe_add_column(conn, "graph_nodes", "embedded_at",       "REAL")

            # -----------------------------------------------------------------
            # STEP 10: ALTER TABLE graph_edges — all P1-P3 columns
            # -----------------------------------------------------------------
            # [P1]
            _safe_add_column(conn, "graph_edges", "edge_type_id",
                             "INTEGER DEFAULT 2")
            _safe_add_column(conn, "graph_edges", "direction",
                             "TEXT DEFAULT 'undirected'")
            _safe_add_column(conn, "graph_edges", "provenance_id",     "INTEGER")
            _safe_add_column(conn, "graph_edges", "confidence",
                             "REAL DEFAULT 1.0")
            _safe_add_column(conn, "graph_edges", "ppmi_weight",       "REAL")
            _safe_add_column(conn, "graph_edges", "ppmi_at",           "REAL")
            # [P2]
            _safe_add_column(conn, "graph_edges", "valid_from",        "REAL")
            _safe_add_column(conn, "graph_edges", "valid_to",          "REAL")
            _safe_add_column(conn, "graph_edges", "is_deleted",
                             "INTEGER NOT NULL DEFAULT 0")
            # [P3]
            _safe_add_column(conn, "graph_edges", "origin_node_id",    "TEXT")
            _safe_add_column(conn, "graph_edges", "crdt_lww_ts",       "REAL")
            _safe_add_column(conn, "graph_edges", "vector_clock",      "TEXT")

            # -----------------------------------------------------------------
            # STEP 11: Indexes (partial WHERE keeps footprint small at P1 scale)
            # -----------------------------------------------------------------
            _indexes = [
                # Stage 1 — preserved for backward compatibility
                ("idx_graph_nodes_concept",
                 "graph_nodes(concept)"),
                ("idx_graph_edges_source",
                 "graph_edges(source_node_id)"),
                # Phase 1
                ("idx_edges_source_type",
                 "graph_edges(source_node_id, edge_type_id) WHERE is_deleted = 0"),
                ("idx_edges_target_type",
                 "graph_edges(target_node_id, edge_type_id) WHERE is_deleted = 0"),
                ("idx_edges_ppmi_stale",
                 "graph_edges(ppmi_at) "
                 "WHERE ppmi_weight IS NULL OR ppmi_at IS NULL"),
                ("idx_provenance_type_time",
                 "provenance(source_type, created_at)"),
                ("idx_nodes_valid",
                 "graph_nodes(valid_from, valid_to) WHERE valid_from IS NOT NULL"),
                ("idx_nodes_origin",
                 "graph_nodes(origin_node_id) WHERE origin_node_id IS NOT NULL"),
                ("idx_nodes_embedding_stale",
                 "graph_nodes(embedding_version) WHERE embedding IS NOT NULL"),
            ]
            for idx_name, idx_expr in _indexes:
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_expr}"
                )

        # Steps 12-14 run after the main CREATE TABLE transaction commits
        # so that FK lookups against graph_nodes.id resolve correctly.

        # -----------------------------------------------------------------
        # STEP 12: Provenance backfill (one-time, idempotent)
        # -----------------------------------------------------------------
        _backfill_provenance(conn)

        # -----------------------------------------------------------------
        # STEP 13: Seed ppmi_global from existing edge counts (one-time)
        # -----------------------------------------------------------------
        _seed_ppmi_counters(conn)

        # -----------------------------------------------------------------
        # STEP 14: Existing Stage 1 columns (idempotent safety net)
        # graph_nodes.inputs_seen and is_sensitive already exist from Stage 1.
        # Listed here so the migration sequence is self-documenting.
        # -----------------------------------------------------------------
        # (no-ops on any Stage 1 database — columns already present)

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PUBLIC: INVALIDATE PPR CACHE
# ---------------------------------------------------------------------------

def invalidate_ppr_cache() -> None:
    """Mark PPR cache as stale. Called after every graph.relate() write."""
    global _ppr_cache_valid
    _ppr_cache_valid = False


# ---------------------------------------------------------------------------
# PUBLIC: COMPUTE PPR
# ---------------------------------------------------------------------------

def compute_ppr(
    seed_node_ids: List[int],
    alpha: float = PPR_ALPHA_CONTEXTUALIZE,
    edge_type_ids: Optional[List[int]] = None,
    top_k: int = 50,
    min_score: float = 0.001,
) -> List[Tuple[int, float]]:
    """
    Compute Personalized PageRank from one or more seed nodes.

    Returns [(node_id, score), ...] sorted descending.
    Falls back gracefully:
      - Returns [] if fast-pagerank not installed
      - Returns [] if graph < PPR_MIN_GRAPH_SIZE nodes (BFS is better)
      - Returns [] on any error (logs to audit trail)

    alpha: teleport probability. Use pipeline constants:
        PPR_ALPHA_CONTEXTUALIZE (0.85) for contextualize step
        PPR_ALPHA_SURFACE (0.80)       for surface step
        PPR_ALPHA_MEMORY (0.90)        for memory step

    Scientific basis: Page et al. (1999); Gleich (2015) survey of PPR.
    """
    global _ppr_matrix, _ppr_node_ids, _ppr_cache_valid

    if not _PPR_AVAILABLE or not seed_node_ids:
        return []

    try:
        with _lock:
            conn = _get_conn()
            try:
                if not _ppr_cache_valid or _ppr_matrix is None:
                    _ppr_matrix, _ppr_node_ids = _build_ppr_matrix(
                        conn, edge_type_ids
                    )
                    _ppr_cache_valid = True

                if _ppr_matrix is None or _ppr_node_ids is None:
                    return []

                n = len(_ppr_node_ids)
                id_to_idx: Dict[int, int] = {
                    nid: i for i, nid in enumerate(_ppr_node_ids)
                }

                personalize = _np.zeros(n)
                valid_seeds = [
                    id_to_idx[sid]
                    for sid in seed_node_ids
                    if sid in id_to_idx
                ]
                if not valid_seeds:
                    return []

                weight = 1.0 / len(valid_seeds)
                for idx in valid_seeds:
                    personalize[idx] = weight

                scores = pagerank_power(
                    _ppr_matrix,
                    p=alpha,
                    personalize=personalize,
                    tol=1e-6,
                )

                results = [
                    (_ppr_node_ids[i], float(scores[i]))
                    for i in range(n)
                    if scores[i] >= min_score
                ]
                results.sort(key=lambda x: x[1], reverse=True)
                return results[:top_k]

            finally:
                conn.close()

    except Exception as exc:
        try:
            _memory.record(
                event_type="PPR_ERROR",
                notes=str(exc),
                context={"seed_node_ids": seed_node_ids, "alpha": alpha},
            )
        except Exception:
            pass
        return []


# ---------------------------------------------------------------------------
# PUBLIC: GET PPR SUBGRAPH (Phase 2 MCP interface)
# ---------------------------------------------------------------------------

def get_ppr_subgraph(
    seed_node_ids: List[int],
    alpha: float = PPR_ALPHA_CONTEXTUALIZE,
    edge_type_ids: Optional[List[int]] = None,
    top_k: int = 50,
) -> Dict[str, Any]:
    """
    PPR-ranked subgraph as a JSON-serializable dict.
    Used by the MCP onto_query tool (Phase 2).

    Returns:
        {
            "nodes": [{"id": int, "label": str, "score": float, ...}],
            "edges": [{"source": int, "target": int, "type": str, ...}],
            "metadata": {"seed_nodes": [...], "alpha": float, ...}
        }
    """
    ppr_results = compute_ppr(seed_node_ids, alpha, edge_type_ids, top_k)
    timestamp = datetime.now(timezone.utc).timestamp()

    if not ppr_results:
        return {
            "nodes": [],
            "edges": [],
            "metadata": {
                "seed_nodes": seed_node_ids,
                "alpha": alpha,
                "timestamp": timestamp,
                "fallback": "ppr_unavailable_or_graph_too_small",
                "hardware_tier": _HARDWARE_TIER,
            },
        }

    node_scores: Dict[int, float] = {nid: score for nid, score in ppr_results}
    result_ids = list(node_scores.keys())
    placeholders = ",".join("?" * len(result_ids))

    conn = _get_conn()
    try:
        node_rows = conn.execute(
            f"SELECT id, concept, is_sensitive, domain "
            f"FROM graph_nodes WHERE id IN ({placeholders})",
            result_ids,
        ).fetchall()

        nodes = sorted(
            [
                {
                    "id": r["id"],
                    "label": r["concept"],
                    "score": node_scores.get(r["id"], 0.0),
                    "is_sensitive": bool(r["is_sensitive"]),
                    "domain": r["domain"],
                }
                for r in node_rows
            ],
            key=lambda x: x["score"],
            reverse=True,
        )

        edge_rows = conn.execute(
            f"SELECT e.source_node_id, e.target_node_id, e.weight, "
            f"t.name AS type_name "
            f"FROM graph_edges e "
            f"LEFT JOIN edge_types t ON t.id = e.edge_type_id "
            f"WHERE e.source_node_id IN ({placeholders}) "
            f"AND e.target_node_id IN ({placeholders}) "
            f"AND e.is_deleted = 0",
            result_ids + result_ids,
        ).fetchall()

        edges = [
            {
                "source": r["source_node_id"],
                "target": r["target_node_id"],
                "weight": r["weight"],
                "type": r["type_name"] or "co-occurs-with",
            }
            for r in edge_rows
        ]

        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "seed_nodes": seed_node_ids,
                "alpha": alpha,
                "timestamp": timestamp,
                "hardware_tier": _HARDWARE_TIER,
                "ppr_available": _PPR_AVAILABLE,
            },
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PUBLIC: RELATE
# ---------------------------------------------------------------------------

def relate(package: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ingest an input package. Extract concepts. Write weighted edges.

    Phase 1 additions:
      - Creates a provenance record for each relate() call.
      - Updates PPMI marginal counters for every edge written.
      - Invalidates the PPR cache after writes.
      - Tags every node and edge with provenance_id.

    Scientific basis:
      Hebbian learning — co-occurrence strengthens associative links.
      Collins & Loftus (1975) — spreading activation via weighted edges.
      Spacing effect (Cepeda et al. 2006) — reinforcement more durable
        when time has elapsed since last access.

    Safety (highest priority, unchanged from Stage 1):
      Crisis concepts are NEVER stored. Returns immediately with
        crisis_detected=True. Caller must surface crisis resources.
      Sensitive concepts receive SENSITIVE_REINFORCEMENT.
      (Nolen-Hoeksema 1991, 2008; Colombetti & Roberts 2024)

    Returns:
        {
          "concepts":           list[str],
          "nodes_created":      int,
          "nodes_reinforced":   int,
          "edges_created":      int,
          "edges_reinforced":   int,
          "crisis_detected":    bool,
          "sensitive_detected": bool,
          "provenance_id":      int | None,  (new in Phase 1)
        }
    """
    text = package.get("clean") or package.get("raw") or ""
    if not text or not text.strip():
        return _empty_relate_result()

    # Crisis check first — never persist under any circumstances
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
    provenance_id: Optional[int] = None

    with _lock:
        conn = _get_conn()
        try:
            # Create a provenance record for this relate() call
            provenance_id = _create_provenance(
                conn,
                source_type="human",
                session_hash=package.get("session_hash"),
            )

            node_ids: Dict[str, int] = {}

            for concept in concepts:
                is_node_sensitive = int(concept in _SENSITIVE_CONCEPTS)
                node_id, created = _upsert_node(
                    conn, concept, now, is_node_sensitive, provenance_id
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
                    conn,
                    src_id,
                    tgt_id,
                    now,
                    reinforcement,
                    edge_is_sensitive,
                    provenance_id,
                )
                if created:
                    edges_created += 1
                else:
                    edges_reinforced += 1

                # Update PPMI counters for every edge write
                _update_ppmi_counters(conn, src_id, tgt_id)

            conn.execute(
                "UPDATE graph_metadata "
                "SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
                "WHERE key = 'total_inputs_processed'"
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

    # Invalidate PPR cache — new edges change the graph topology
    invalidate_ppr_cache()

    return {
        "concepts": concepts,
        "nodes_created": nodes_created,
        "nodes_reinforced": nodes_reinforced,
        "edges_created": edges_created,
        "edges_reinforced": edges_reinforced,
        "crisis_detected": False,
        "sensitive_detected": sensitive_detected,
        "provenance_id": provenance_id,
    }


# ---------------------------------------------------------------------------
# PUBLIC: NAVIGATE
# ---------------------------------------------------------------------------

def navigate(
    text: str,
    include_sensitive: bool = False,
) -> List[Dict[str, Any]]:
    """
    Traverse the graph from concepts in text. Return ranked context.

    Phase 1: Uses PPR when graph >= 200 nodes and fast-pagerank installed.
    Falls back to BFS (Stage 1 behavior) when graph is small or PPR
    is unavailable. BFS fallback is documented in audit trail.

    Return schema (unchanged from Stage 1):
        [{"concept", "effective_weight", "times_seen", "inputs_seen",
          "source", "days_since", "complexity", "is_sensitive"}, ...]

    source field is always "graph" regardless of PPR or BFS path.
    """
    if not text or not text.strip():
        return []

    concepts = _extract_concepts(text)
    if not concepts:
        return []

    with _lock:
        conn = _get_conn()
        try:
            # Find seed nodes in the graph
            seed_ids: List[int] = []
            for concept in concepts:
                row = conn.execute(
                    "SELECT id FROM graph_nodes WHERE concept = ?",
                    (concept,),
                ).fetchone()
                if row:
                    seed_ids.append(row["id"])

            if not seed_ids:
                return []

            # Decide: PPR or BFS
            node_count = conn.execute(
                "SELECT COUNT(*) AS c FROM graph_nodes"
            ).fetchone()["c"]

            if _PPR_AVAILABLE and node_count >= _PPR_MIN_GRAPH_SIZE:
                return _navigate_ppr(seed_ids, include_sensitive, conn)
            else:
                return _navigate_bfs(seed_ids, include_sensitive, conn)

        finally:
            conn.close()


def _navigate_ppr(
    seed_ids: List[int],
    include_sensitive: bool,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    """
    Navigate using Personalized PageRank. Called when graph >= 200 nodes.
    Formats PPR results into the standard navigate() return schema.
    """
    ppr_results = compute_ppr(
        seed_ids,
        alpha=PPR_ALPHA_SURFACE,
        top_k=MAX_RESULTS,
    )

    if not ppr_results:
        # PPR returned nothing — fall back to BFS
        return _navigate_bfs(seed_ids, include_sensitive, conn)

    now_dt = datetime.now(timezone.utc)
    results: List[Dict[str, Any]] = []

    for node_id, ppr_score in ppr_results:
        row = conn.execute(
            "SELECT concept, times_seen, inputs_seen, is_sensitive, "
            "last_reinforced, weight "
            "FROM graph_nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if not row:
            continue

        if not include_sensitive and row["is_sensitive"]:
            continue

        degree = conn.execute(
            "SELECT COUNT(*) AS c FROM graph_edges "
            "WHERE (source_node_id = ? OR target_node_id = ?) "
            "AND is_deleted = 0",
            (node_id, node_id),
        ).fetchone()["c"]

        days = _days_since(row["last_reinforced"], now_dt)

        results.append({
            "concept":          row["concept"],
            "effective_weight": round(min(1.0, max(0.0, ppr_score)), 6),
            "times_seen":       row["times_seen"],
            "inputs_seen":      row["inputs_seen"],
            "source":           "graph",
            "days_since":       round(days, 4),
            "complexity":       degree,
            "is_sensitive":     bool(row["is_sensitive"]),
        })

    results.sort(key=lambda x: x["effective_weight"], reverse=True)
    return results[:MAX_RESULTS]


def _navigate_bfs(
    seed_ids: List[int],
    include_sensitive: bool,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    """
    BFS traversal (Stage 1 behavior). Used when graph is small or PPR
    is unavailable. Preserved exactly from Stage 1 implementation.

    Scientific basis:
      BFS at depth 2 (Balota & Lorch 1986).
      Fan effect (ACT-R, Anderson 1983).
      Power-law decay (Wixted 2004).
      TF-IDF Size axis (Sparck Jones 1972).
      PPMI approximation (Bullinaria & Levy 2007).
    """
    total_inputs_row = conn.execute(
        "SELECT value FROM graph_metadata WHERE key = 'total_inputs_processed'"
    ).fetchone()
    total_inputs = int(total_inputs_row["value"]) if total_inputs_row else 1

    now_dt = datetime.now(timezone.utc)
    visited: Set[int] = set(seed_ids)
    frontier: Set[int] = set(seed_ids)
    results: Dict[int, Dict[str, Any]] = {}

    for _depth in range(MAX_DEPTH):
        next_frontier: Set[int] = set()
        for node_id in frontier:
            rows = conn.execute(
                "SELECT e.source_node_id, e.target_node_id, "
                "e.weight, e.is_sensitive, e.last_reinforced, "
                "e.times_seen, "
                "n.concept, n.times_seen AS node_times_seen, "
                "n.inputs_seen, n.is_sensitive AS node_sensitive, "
                "n.weight AS node_weight "
                "FROM graph_edges e "
                "JOIN graph_nodes n ON ("
                "    n.id = CASE WHEN e.source_node_id = ? "
                "           THEN e.target_node_id "
                "           ELSE e.source_node_id END"
                ") "
                "WHERE (e.source_node_id = ? OR e.target_node_id = ?) "
                "AND e.is_deleted = 0",
                (node_id, node_id, node_id),
            ).fetchall()

            for row in rows:
                neighbor_id = (
                    row["target_node_id"]
                    if row["source_node_id"] == node_id
                    else row["source_node_id"]
                )
                if neighbor_id in visited:
                    continue
                if not include_sensitive and row["node_sensitive"]:
                    continue

                degree = conn.execute(
                    "SELECT COUNT(*) AS c FROM graph_edges "
                    "WHERE (source_node_id = ? OR target_node_id = ?) "
                    "AND is_deleted = 0",
                    (neighbor_id, neighbor_id),
                ).fetchone()["c"]

                ew = _effective_weight(
                    row["weight"],
                    _days_since(row["last_reinforced"], now_dt),
                    row["node_times_seen"],
                    row["inputs_seen"],
                    total_inputs,
                    degree,
                    row["is_sensitive"],
                    reinforcement_count=row["times_seen"],
                    fan_dilution=1.0 / max(1.0, math.sqrt(degree)),
                )

                if ew > 0:
                    days = _days_since(row["last_reinforced"], now_dt)
                    existing = results.get(neighbor_id)
                    if existing is None or ew > existing["effective_weight"]:
                        results[neighbor_id] = {
                            "concept":          row["concept"],
                            "effective_weight": round(ew, 6),
                            "times_seen":       row["node_times_seen"],
                            "inputs_seen":      row["inputs_seen"],
                            "source":           "graph",
                            "days_since":       round(days, 4),
                            "complexity":       degree,
                            "is_sensitive":     bool(row["node_sensitive"]),
                        }
                    next_frontier.add(neighbor_id)
                    visited.add(neighbor_id)

        frontier = next_frontier

    ranked = sorted(
        results.values(),
        key=lambda x: x["effective_weight"],
        reverse=True,
    )
    return ranked[:MAX_RESULTS]


# ---------------------------------------------------------------------------
# PUBLIC: PRUNE (soft-delete edges below PPMI threshold)
# ---------------------------------------------------------------------------

def prune(threshold: Optional[float] = None) -> Dict[str, int]:
    """
    Soft-delete edges whose PPMI weight falls below the threshold.

    threshold: if None, reads ONTO_PPMI_PRUNE_THRESHOLD env var (default 0.5).
               Read at call time, not at boot — configurable between runs.

    PPMI is computed lazily for edges where ppmi_weight IS NULL.
    Deleted edges are marked is_deleted=1 (not physically removed).
    Physical removal requires graph.wipe().

    Every prune operation is written to the audit trail.

    Returns: {"edges_pruned": int}
    """
    prune_threshold = (
        threshold
        if threshold is not None
        else float(os.getenv("ONTO_PPMI_PRUNE_THRESHOLD", "0.5"))
    )
    edges_pruned = 0

    with _lock:
        conn = _get_conn()
        try:
            # Compute lazy PPMI for any edge where it's NULL
            stale = conn.execute(
                "SELECT id, source_node_id, target_node_id, weight "
                "FROM graph_edges "
                "WHERE (ppmi_weight IS NULL OR ppmi_at IS NULL) "
                "AND is_deleted = 0"
            ).fetchall()

            now = datetime.now(timezone.utc).timestamp()
            with conn:
                for row in stale:
                    ppmi = _compute_ppmi(
                        row["source_node_id"],
                        row["target_node_id"],
                        row["weight"],
                        conn,
                    )
                    conn.execute(
                        "UPDATE graph_edges SET ppmi_weight = ?, ppmi_at = ? "
                        "WHERE id = ?",
                        (ppmi, now, row["id"]),
                    )

                # Soft-delete edges below threshold
                result = conn.execute(
                    "UPDATE graph_edges SET is_deleted = 1 "
                    "WHERE ppmi_weight < ? AND is_deleted = 0",
                    (prune_threshold,),
                )
                edges_pruned = result.rowcount

        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return {"edges_pruned": 0}
        finally:
            conn.close()

    if edges_pruned > 0:
        invalidate_ppr_cache()
        try:
            _memory.record(
                event_type="GRAPH_PRUNE",
                notes=f"{edges_pruned} edges soft-deleted below PPMI threshold {prune_threshold}.",
                context={
                    "edges_pruned": edges_pruned,
                    "threshold": prune_threshold,
                },
            )
        except Exception:
            pass

    return {"edges_pruned": edges_pruned}


# ---------------------------------------------------------------------------
# PUBLIC: DECAY
# ---------------------------------------------------------------------------

def decay() -> Dict[str, int]:
    """
    Prune edges whose effective weight has fallen below PRUNE_THRESHOLD.
    Remove orphaned nodes. Apply PPMI counter decay.

    Phase 1 additions:
      - Decays ppmi_counters.marginal_count by lambda from the active profile.
      - Decays ppmi_global total_co_occurrences by the same lambda.
      - Invalidates all cached ppmi_weight values after counter decay.

    Stored weights are NOT updated — effective weight is computed lazily
    at read time. This avoids write storms on large graphs.

    Scientific basis: Power-law decay (Wixted 2004, Jost's Law 1897).
    Forgetting is accessibility loss, not deletion. Edges below the pruning
    threshold are effectively inaccessible and consume traversal resources.
    Sensitive edges decay faster (DECAY_EXPONENT × 1.4).

    Returns:
        {"edges_pruned": int, "nodes_pruned": int}
    """
    now_dt = datetime.now(timezone.utc)
    now_epoch = now_dt.timestamp()
    edges_pruned = 0
    nodes_pruned = 0

    # Read active decay profile lambda from env var
    decay_lambda = 0.95
    try:
        conn = _get_conn()
        profile_row = conn.execute(
            "SELECT lambda FROM decay_profiles WHERE name = ?",
            (DEFAULT_DECAY_PROFILE,),
        ).fetchone()
        if profile_row:
            decay_lambda = profile_row["lambda"]
        conn.close()
    except Exception:
        pass

    with _lock:
        conn = _get_conn()
        try:
            # -----------------------------------------------------------
            # Prune edges (existing Stage 1 logic — preserved exactly)
            # -----------------------------------------------------------
            rows = conn.execute(
                "SELECT id, weight, last_reinforced, is_sensitive "
                "FROM graph_edges WHERE is_deleted = 0"
            ).fetchall()

            with conn:
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
                            "DELETE FROM graph_edges WHERE id = ?",
                            (row["id"],),
                        )
                        edges_pruned += 1

                # Remove orphaned nodes
                orphans = conn.execute("""
                    SELECT n.id FROM graph_nodes n
                    WHERE NOT EXISTS (
                        SELECT 1 FROM graph_edges e
                        WHERE (e.source_node_id = n.id
                            OR e.target_node_id = n.id)
                        AND e.is_deleted = 0
                    )
                """).fetchall()
                for row in orphans:
                    # ppmi_counters has FK to graph_nodes — delete first
                    conn.execute(
                        "DELETE FROM ppmi_counters WHERE node_id = ?",
                        (row["id"],),
                    )
                    conn.execute(
                        "DELETE FROM graph_nodes WHERE id = ?",
                        (row["id"],),
                    )
                    nodes_pruned += 1

            # -----------------------------------------------------------
            # Phase 1: Decay PPMI counters (vocabulary drift mitigation)
            # -----------------------------------------------------------
            with conn:
                conn.execute(
                    "UPDATE ppmi_counters "
                    "SET marginal_count = marginal_count * ?, "
                    "    last_decay_at  = ? "
                    "WHERE last_decay_at IS NULL OR last_decay_at < ? - 86400",
                    (decay_lambda, now_epoch, now_epoch),
                )
                conn.execute(
                    "UPDATE ppmi_global SET value = value * ? "
                    "WHERE key = 'total_co_occurrences'",
                    (decay_lambda,),
                )
                # Invalidate all cached ppmi_weight values
                conn.execute(
                    "UPDATE graph_edges SET ppmi_weight = NULL, ppmi_at = NULL "
                    "WHERE ppmi_weight IS NOT NULL"
                )

        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()

    if edges_pruned > 0 or nodes_pruned > 0:
        invalidate_ppr_cache()

    return {"edges_pruned": edges_pruned, "nodes_pruned": nodes_pruned}


# ---------------------------------------------------------------------------
# PUBLIC: WIPE
# ---------------------------------------------------------------------------

def wipe() -> Dict[str, int]:
    """
    Delete the entire relationship graph. Reset PPMI counters.

    Legal basis: GDPR Article 17 — right to erasure. The graph stores
    personal associative data derived from user inputs. Users have an
    unconditional right to delete it.

    Phase 1 additions:
      - Resets ppmi_counters (derived from graph; meaningless after wipe).
      - Resets ppmi_global total_co_occurrences to 0.
      - Invalidates PPR cache.
      - Provenance records are NOT deleted (they record that data existed,
        not the content — consistent with cryptographic erasure architecture).

    The audit trail in memory.py is NOT affected. It records only that
    a wipe occurred — not the content. See docs/PRIVACY_GDPR.md.

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

            with conn:
                # ppmi_counters has FK to graph_nodes — must delete first
                conn.execute("DELETE FROM ppmi_counters")
                conn.execute("DELETE FROM graph_edges")
                conn.execute("DELETE FROM graph_nodes")
                conn.execute(
                    "UPDATE graph_metadata SET value = '0' "
                    "WHERE key = 'total_inputs_processed'"
                )
                conn.execute(
                    "UPDATE ppmi_global SET value = 0.0 "
                    "WHERE key = 'total_co_occurrences'"
                )

        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return {"nodes_deleted": 0, "edges_deleted": 0}
        finally:
            conn.close()

    invalidate_ppr_cache()

    # Record in audit trail AFTER lock released.
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
# PRIVATE: CONCEPT EXTRACTION — YAKE-inspired (replaces RAKE)
# ---------------------------------------------------------------------------

def _extract_concepts(text: str) -> List[str]:
    """
    Extract meaningful concepts using the active ConceptExtractor.

    Phase 1: delegates to YAKE-inspired stdlib implementation by default.
    Pluggable: call set_extractor() to swap implementations.
    Phase 4: SpacyExtractor drops in with zero changes to this function.

    Contract (unchanged from Stage 1 RAKE implementation):
        receives str, returns list[str], length <= MAX_CONCEPTS_PER_INPUT.
        Never raises.
    """
    with _extractor_lock:
        extractor = _EXTRACTOR
    return extractor.extract(text, MAX_CONCEPTS_PER_INPUT)


def _yake_extract(text: str, max_concepts: int) -> List[str]:
    """
    YAKE-inspired five-feature keyword extraction. stdlib only.

    Features (mapped to ONTO's three governing axes):
        Casing (C)            → Distance: capitalized words score higher
        Position (P)          → Distance: earlier words score higher
        Frequency (F)         → Size: normalized term frequency
        Context diversity (D) → Complexity: distinct co-occurring candidates
        Sentence spread (S)   → Complexity: how many sentences contain it

    Score formula (lower = more important, consistent with original YAKE):
        score(t) = (C × F_norm) / (S × D × log(3 + position))

    Scientific basis: Campos et al. (2020).
    """
    sentences = [s.strip() for s in re.split(r"[.!?\n]+", text) if s.strip()]
    n_sentences = max(len(sentences), 1)

    # Tokenize preserving original casing for casing feature
    words_original = re.findall(r"\b[a-zA-Z]{3,}\b", text)
    words_lower = [w.lower() for w in words_original]

    if not words_lower:
        return []

    # Candidates: non-stopwords only
    candidates_lower = [w for w in words_lower if w not in _STOPWORDS]
    if not candidates_lower:
        return []

    # Feature 1: Frequency
    freq = Counter(candidates_lower)
    mean_freq = sum(freq.values()) / max(len(freq), 1)

    # Feature 2: Casing — ratio of capitalized occurrences
    cap_count: Dict[str, int] = Counter()
    for lo, orig in zip(words_lower, words_original):
        if lo not in _STOPWORDS and orig[0].isupper():
            cap_count[lo] += 1
    casing: Dict[str, float] = {
        t: max(1.0, cap_count[t] / max(freq[t], 1)) for t in freq
    }

    # Feature 3: Position — sentence index of first appearance
    first_pos: Dict[str, int] = {}
    for i, sent in enumerate(sentences):
        for w in re.findall(r"\b[a-zA-Z]{3,}\b", sent.lower()):
            if w not in _STOPWORDS and w not in first_pos:
                first_pos[w] = i

    # Feature 4: Sentence spread — distinct sentences containing this word
    sent_sets: Dict[str, Set[int]] = {}
    for i, sent in enumerate(sentences):
        for w in re.findall(r"\b[a-zA-Z]{3,}\b", sent.lower()):
            if w not in _STOPWORDS:
                sent_sets.setdefault(w, set()).add(i)

    # Feature 5: Context diversity — distinct co-occurrences in a window of 5
    co_occ: Dict[str, Set[str]] = {t: set() for t in freq}
    for i, term in enumerate(candidates_lower):
        window = candidates_lower[max(0, i - 2): i + 3]
        for w in window:
            if w != term:
                co_occ[term].add(w)

    # Compute YAKE score (lower = more important)
    scores: Dict[str, float] = {}
    for term in freq:
        f = freq[term]
        c = casing.get(term, 1.0)
        s = len(sent_sets.get(term, {0})) / n_sentences
        d = max(len(co_occ.get(term, set())), 1)
        pos = first_pos.get(term, n_sentences)
        pos_penalty = math.log(3.0 + pos)  # lower pos = lower penalty = better
        tf_norm = f / max(mean_freq, 1.0)

        try:
            score = (c * tf_norm) / (s * d * pos_penalty)
        except ZeroDivisionError:
            score = float("inf")
        scores[term] = score

    # Lower score = more important — take the lowest-scoring terms
    sorted_terms = sorted(scores, key=lambda t: scores[t])
    return sorted_terms[:max_concepts]


# ---------------------------------------------------------------------------
# PRIVATE: NODE AND EDGE HELPERS (Stage 1 — updated for Phase 1)
# ---------------------------------------------------------------------------

def _upsert_node(
    conn: sqlite3.Connection,
    concept: str,
    now: float,
    is_sensitive: int,
    provenance_id: Optional[int] = None,
) -> Tuple[int, bool]:
    """
    Insert or update a node. Returns (integer_id, created_bool).
    Phase 1: attaches provenance_id when creating new nodes.
    """
    existing = conn.execute(
        "SELECT id, times_seen, inputs_seen, last_reinforced FROM graph_nodes WHERE concept = ?",
        (concept,),
    ).fetchone()

    if existing:
        days_elapsed = _days_since(
            existing["last_reinforced"],
            datetime.now(timezone.utc),
        )
        increment = _spacing_increment(BASE_REINFORCEMENT, days_elapsed)
        conn.execute(
            "UPDATE graph_nodes "
            "SET weight = weight + ?, times_seen = times_seen + 1, "
            "    inputs_seen = inputs_seen + 1, last_reinforced = ? "
            "WHERE id = ?",
            (increment, now, existing["id"]),
        )
        return existing["id"], False
    else:
        node_uuid = str(uuid.uuid4())
        cursor = conn.execute(
            "INSERT INTO graph_nodes "
            "(uuid, concept, weight, times_seen, inputs_seen, "
            "is_sensitive, created_at, last_reinforced, provenance_id) "
            "VALUES (?, ?, ?, 1, 1, ?, ?, ?, ?)",
            (node_uuid, concept, BASE_REINFORCEMENT, is_sensitive,
             now, now, provenance_id),
        )
        return cursor.lastrowid, True  # type: ignore[return-value]


def _upsert_edge(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    now: float,
    reinforcement: float,
    is_sensitive: int,
    provenance_id: Optional[int] = None,
) -> bool:
    """
    Insert or update an edge. Returns True if created, False if reinforced.
    Phase 1: attaches provenance_id, sets edge_type_id=2 (co-occurs-with).
    """
    existing = conn.execute(
        "SELECT id, weight, times_seen, last_reinforced FROM graph_edges "
        "WHERE source_node_id = ? AND target_node_id = ?",
        (source_id, target_id),
    ).fetchone()

    if existing:
        days_elapsed = _days_since(
            existing["last_reinforced"],
            datetime.now(timezone.utc),
        )
        increment = _spacing_increment(reinforcement, days_elapsed)
        conn.execute(
            "UPDATE graph_edges "
            "SET weight = weight + ?, times_seen = times_seen + 1, "
            "    last_reinforced = ? "
            "WHERE id = ?",
            (increment * reinforcement, now, existing["id"]),
        )
        return False
    else:
        conn.execute(
            "INSERT INTO graph_edges "
            "(source_node_id, target_node_id, weight, times_seen, "
            "is_sensitive, last_reinforced, edge_type_id, "
            "direction, provenance_id, confidence) "
            "VALUES (?, ?, ?, 1, ?, ?, 2, 'undirected', ?, 1.0)",
            (source_id, target_id, reinforcement, is_sensitive,
             now, provenance_id),
        )
        return True


def _concept_pairs(
    node_ids: Dict[str, int],
) -> List[Tuple[int, int, str, str]]:
    """
    Return all unique concept pairs from the node_ids dict.
    Each pair: (src_id, tgt_id, src_concept, tgt_concept).
    """
    items = list(node_ids.items())
    pairs = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            src_concept, src_id = items[i]
            tgt_concept, tgt_id = items[j]
            pairs.append((src_id, tgt_id, src_concept, tgt_concept))
    return pairs


# ---------------------------------------------------------------------------
# PRIVATE: MATH AND TIME HELPERS (Stage 1 — preserved)
# ---------------------------------------------------------------------------

def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _days_since(epoch: float, now_dt: datetime) -> float:
    """Days elapsed since epoch timestamp."""
    try:
        then = datetime.fromtimestamp(epoch, tz=timezone.utc)
        return max(0.0, (now_dt - then).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def _spacing_increment(base_weight: float, days_elapsed: float) -> float:
    """
    Spacing-effect reinforcement based on delay since last review.

    Immediate review (0 days):  returns base_weight (factor = 1.0).
    Optimal delay (~30 days):   returns 2× base_weight (factor = 2.0).
    Cap at 2× to prevent runaway reinforcement.

    Scientific basis: Cepeda et al. (2006) spaced-repetition meta-analysis.
    Factor = min(2.0, 1.0 + days_elapsed / 30.0)

    Arguments: base_weight first, days_elapsed second.
    """
    factor = min(2.0, 1.0 + float(days_elapsed) / 30.0)
    return base_weight * factor


def _effective_weight(
    base_weight: float,
    days_since: float,
    times_seen: int,
    inputs_seen: int,
    total_inputs: int,
    degree: int,
    is_sensitive: int = 0,
    reinforcement_count: int = 1,
    src_times_seen: int = 1,
    fan_dilution: float = 1.0,
) -> float:
    """
    Three-axis effective weight (pre-computed days_since passed by caller):
      Axis 1 Distance:    power-law decay (Wixted 2004)
      Axis 2 Size:        TF-IDF downweight (Sparck Jones 1972)
      Axis 3 Complexity:  fan effect (Anderson 1983 ACT-R)
    + PPMI approximation using reinforcement_count (Bullinaria & Levy 2007)

    Caller is responsible for computing days_since from last_reinforced.
    reinforcement_count: edge times_seen (how many times this link was reinforced).
    src_times_seen:      source node times_seen (accepted for caller convenience).
    fan_dilution:        pre-computed fan dilution factor (default 1.0).
    """
    if base_weight <= 0:
        return 0.0

    exponent = DECAY_EXPONENT * 1.4 if is_sensitive else DECAY_EXPONENT
    axis1 = base_weight * (1.0 + days_since) ** (-exponent)

    idf = math.log((total_inputs + 1) / max(inputs_seen, 1))
    axis2 = axis1 * (1.0 + math.log(1 + times_seen)) * idf

    fan = max(1, degree)
    axis3 = axis2 * fan_dilution / math.sqrt(fan)

    ppmi_approx = math.log(1.0 + reinforcement_count / max(fan, 1))
    combined = axis3 * (1.0 + ppmi_approx)

    return min(1.0, max(0.0, combined))


def _contains_crisis(text: str) -> bool:
    """Check if text contains any crisis-level content. Case-insensitive."""
    lower = text.lower()
    return any(phrase in lower for phrase in _CRISIS_CONCEPTS)


def _contains_sensitive(text: str) -> bool:
    """Check if text contains sensitive concepts. Case-insensitive."""
    words = set(re.findall(r"\b\w+\b", text.lower()))
    return bool(words & _SENSITIVE_CONCEPTS)


def _empty_relate_result() -> Dict[str, Any]:
    return {
        "concepts":         [],
        "nodes_created":    0,
        "nodes_reinforced": 0,
        "edges_created":    0,
        "edges_reinforced": 0,
        "crisis_detected":  False,
        "sensitive_detected": False,
        "provenance_id":    None,
    }
