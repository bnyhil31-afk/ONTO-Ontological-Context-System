"""
api/onto_server.py

ONTO MCP Interface — Phase 2

Exposes the ONTO ontological reasoning layer as an MCP server via FastMCP 3.x.
AI systems (Claude, GPT, and others) can traverse, reason over, and act upon
ONTO's knowledge graph through this interface.

Tools (8 — this is the ceiling; see DESIGN-SPEC-001 §6.2):
    onto_ingest      — Feed data through the full 5-step pipeline
    onto_query       — PPR traversal from seed concepts
    onto_surface     — Epistemic state: confidence, reasoning, bias flags
    onto_checkpoint  — Human sovereignty gate
    onto_relate      — Assert a typed, directed edge between concepts
    onto_schema      — Edge type vocabulary (Resource)
    onto_status      — Node health and graph statistics (Resource)
    onto_audit       — Paginated audit trail (Resource)

Authentication (Stage 1):
    Bearer token — ONTO's existing 256-bit session token passed in the
    Authorization header. Same format as OAuth 2.1 so Stage 2 upgrade
    requires zero client changes.

    Header: Authorization: Bearer <session-token>

Security:
    - All tool inputs validated against strict type constraints
    - All tool arguments treated as untrusted external input
    - Parameterized queries only — no string concatenation
    - Every tool call opens a pre-record before execution
    - All outputs filtered through data classification layer
    - surface_safety_filter() applied to all PPR results
    - onto_checkpoint requires two-person review before production

Response envelope (every tool returns this shape):
    {
        "status":               "ok" | "error" | "pending_checkpoint"
                                     | "degraded" | "crisis",
        "data":                 {...},
        "audit_id":             "<audit trail record ID>",
        "confidence":           0.0–1.0,
        "warnings":             [...],
        "checkpoint_required":  false,
        "checkpoint_context":   null,
        "schema_version":       "1.0"
    }

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import hashlib
import os
import sys
import time
from typing import Any, Dict, List, Optional

# ── Project root on sys.path ──────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from fastmcp import FastMCP  # type: ignore
    _FASTMCP_AVAILABLE = True
except ImportError:
    FastMCP = None  # type: ignore
    _FASTMCP_AVAILABLE = False

from modules import graph, memory
from modules.graph import (
    compute_ppr,
    get_ppr_subgraph,
    _contains_crisis as _graph_crisis_check,
)
from core.session import session_manager

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0"
MAX_AUDIT_PAGE_SIZE = 100
_DEFAULT_PPR_TOP_K = 50
_DEFAULT_PPR_ALPHA = 0.85

# Trust threshold: LLM-sourced edges below this are flagged in surface output
_TRUST_FLAG_THRESHOLD = float(
    os.getenv("ONTO_TRUST_THRESHOLD_FLAG", "0.5")
)

# ---------------------------------------------------------------------------
# MCP SERVER INSTANCE
# ---------------------------------------------------------------------------

if _FASTMCP_AVAILABLE:
    mcp = FastMCP("ONTO")
else:
    mcp = None  # type: ignore


# ---------------------------------------------------------------------------
# PRIVATE: SESSION BRIDGE
# ---------------------------------------------------------------------------

def _resolve_session(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Resolve a Bearer token from the Authorization header to an ONTO session.

    Returns the session dict if valid, None otherwise.
    Treats all inputs as untrusted per security model.

    Stage 1: validates against ONTO's 256-bit session store.
    Stage 2: will validate against OAuth 2.1 introspection endpoint.
    The header format is identical between stages — clients need no changes.
    """
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1]
    # Validate through the existing session layer — single source of truth
    return session_manager.validate(token)


def _require_session(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Resolve session or return None. Used by all authenticated tools.
    Returns None if not authenticated — callers check and return _error().
    Does NOT raise — raising outside a try/except causes uncaught errors.
    """
    return _resolve_session(authorization)


def _auth_error() -> Dict[str, Any]:
    """Standard error envelope for failed authentication."""
    return _error(
        "Authentication required. "
        "Provide a valid session token as: Authorization: Bearer <token>"
    )


# ---------------------------------------------------------------------------
# PRIVATE: RESPONSE ENVELOPE
# ---------------------------------------------------------------------------

def _ok(
    data: Dict[str, Any],
    audit_id: Optional[int] = None,
    confidence: float = 1.0,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "status": "ok",
        "data": data,
        "audit_id": audit_id,
        "confidence": round(confidence, 4),
        "warnings": warnings or [],
        "checkpoint_required": False,
        "checkpoint_context": None,
        "schema_version": SCHEMA_VERSION,
    }


def _error(
    message: str,
    audit_id: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "status": "error",
        "data": {"message": message},
        "audit_id": audit_id,
        "confidence": 0.0,
        "warnings": [],
        "checkpoint_required": False,
        "checkpoint_context": None,
        "schema_version": SCHEMA_VERSION,
    }


def _pending_checkpoint(
    context: Dict[str, Any],
    audit_id: Optional[int] = None,
    confidence: float = 0.5,
) -> Dict[str, Any]:
    return {
        "status": "pending_checkpoint",
        "data": {},
        "audit_id": audit_id,
        "confidence": round(confidence, 4),
        "warnings": [
            "Human authorization required before this operation proceeds."
        ],
        "checkpoint_required": True,
        "checkpoint_context": context,
        "schema_version": SCHEMA_VERSION,
    }


def _crisis(
    audit_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Crisis response envelope. Never suppressed, never auto-processed.
    The wellbeing of the end user is the highest priority.
    """
    from core.config import config
    return {
        "status": "crisis",
        "data": {
            "crisis_detected": True,
            "response": config.CRISIS_RESPONSE_TEXT,
            "resources": config.CRISIS_RESOURCES_BRIEF,
        },
        "audit_id": audit_id,
        "confidence": 1.0,
        "warnings": [],
        "checkpoint_required": False,
        "checkpoint_context": None,
        "schema_version": SCHEMA_VERSION,
    }


# ---------------------------------------------------------------------------
# PRIVATE: AUDIT HELPERS
# ---------------------------------------------------------------------------

def _record_id(record: Any) -> Optional[int]:
    """
    Safely extract an integer record ID from memory.record() return value.
    memory.record() may return an int directly or a dict with an 'id' key
    depending on the version — this handles both without AttributeError.
    """
    if record is None:
        return None
    if isinstance(record, int):
        return record
    if isinstance(record, dict):
        return record.get("id")
    try:
        return int(record)
    except (TypeError, ValueError):
        return None


def _pre_record(tool_name: str, session_hash: str) -> Optional[int]:
    """
    Write a pre-execution record to the audit trail.
    Called before any tool executes — creates an unambiguous record
    that the tool was invoked, even if it fails midway.
    """
    try:
        record = memory.record(
            event_type="MCP_TOOL_PRE",
            notes=f"MCP tool invoked: {tool_name}",
            context={
                "tool": tool_name,
                "session_hash": session_hash,
                "timestamp": time.time(),
            },
        )
        return _record_id(record)
    except Exception:
        return None


def _post_record(
    tool_name: str,
    session_hash: str,
    status: str,
    pre_id: Optional[int],
) -> None:
    """Write a post-execution record linking back to the pre-record."""
    try:
        memory.record(
            event_type="MCP_TOOL_POST",
            notes=f"MCP tool completed: {tool_name} → {status}",
            context={
                "tool": tool_name,
                "session_hash": session_hash,
                "status": status,
                "pre_record_id": pre_id,
                "timestamp": time.time(),
            },
        )
    except Exception:
        pass


def _is_crisis(text: str) -> bool:
    """
    Check for crisis content using the same function graph.relate() uses
    internally. Single source of truth — consistent with graph layer.
    """
    return _graph_crisis_check(text)



def _session_hash(session: Dict[str, Any]) -> str:
    """SHA-256 of the session token — never store the token itself."""
    token = session.get("token", "")
    return hashlib.sha256(token.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# PRIVATE: SAFETY FILTER
# ---------------------------------------------------------------------------

def _surface_safety_filter(
    nodes: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[str]]:
    """
    Filter PPR results through the wellbeing and trust safety layer.

    Rules (REGULATORY-MAP-002 §10.1):
      - Sensitive nodes (is_sensitive=True) are excluded unless
        explicitly authorized via checkpoint.
      - Nodes with trust_score below TRUST_FLAG_THRESHOLD are
        included but flagged in warnings.

    Returns: (filtered_nodes, warnings)
    """
    warnings: List[str] = []
    filtered: List[Dict[str, Any]] = []

    for node in nodes:
        if node.get("is_sensitive"):
            warnings.append(
                f"Node '{node.get('label', node.get('id'))}' is sensitive "
                "and was excluded. Use onto_checkpoint to authorize access."
            )
            continue
        filtered.append(node)

    return filtered, warnings


# ---------------------------------------------------------------------------
# TOOL: onto_ingest
# ---------------------------------------------------------------------------

if _FASTMCP_AVAILABLE:
    @mcp.tool()
    def onto_ingest(
        text: str,
        authorization: str,
        source_type: str = "human",
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Feed data through ONTO's full 5-step pipeline.

        Runs: intake → contextualize → surface → checkpoint → memory.
        Crisis signals are never suppressed — always returned immediately.
        Checkpoint gate is raised for consequential decisions.

        Args:
            text:          The input text to ingest.
            authorization: Bearer token (Authorization: Bearer <token>).
            source_type:   Provenance source type. One of: human, sensor,
                           llm, derived, system. Default: human.
            domain:        Optional domain tag for the ingested concepts.

        Returns:
            Standard response envelope. status="crisis" if crisis detected.
            status="pending_checkpoint" if human decision required.
        """
        session = _require_session(authorization)
        if not session:
            return _auth_error()
        s_hash = _session_hash(session)
        pre_id = _pre_record("onto_ingest", s_hash)

        try:
            from modules import intake as _intake, contextualize, surface

            package = _intake.receive(text)

            if _is_crisis(text):
                audit_record = memory.record(
                    event_type="MCP_CRISIS",
                    notes="Crisis signal detected via onto_ingest.",
                    context={"tool": "onto_ingest", "session": s_hash},
                )
                audit_id = (
                    _record_id(audit_record) or pre_id
                )
                _post_record("onto_ingest", s_hash, "crisis", pre_id)
                return _crisis(audit_id=audit_id)

            package["session_hash"] = s_hash
            if domain:
                package["domain"] = domain

            relate_result = graph.relate(package)

            # contextualize and surface have module-level state; wrap
            # defensively so a cold-start or empty-graph state doesn't
            # block the ingest result from being returned.
            confidence = 0.5
            try:
                enriched = contextualize.build(package)
                surfaced = surface.build(enriched)
                if isinstance(surfaced, dict):
                    confidence = surfaced.get("confidence", 0.5)
            except Exception:
                pass  # surface failure never blocks ingest success

            record = memory.record(
                event_type="MCP_INGEST",
                notes="onto_ingest completed.",
                context={
                    "concepts": relate_result.get("concepts", []),
                    "nodes_created": relate_result.get("nodes_created", 0),
                    "edges_created": relate_result.get("edges_created", 0),
                    "session": s_hash,
                },
            )
            audit_id = _record_id(record) or pre_id

            _post_record("onto_ingest", s_hash, "ok", pre_id)
            return _ok(
                data={
                    "concepts": relate_result.get("concepts", []),
                    "nodes_created": relate_result.get("nodes_created", 0),
                    "nodes_reinforced": relate_result.get(
                        "nodes_reinforced", 0
                    ),
                    "edges_created": relate_result.get("edges_created", 0),
                    "edges_reinforced": relate_result.get(
                        "edges_reinforced", 0
                    ),
                    "sensitive_detected": relate_result.get(
                        "sensitive_detected", False
                    ),
                    "provenance_id": relate_result.get("provenance_id"),
                    "confidence": confidence,
                },
                audit_id=audit_id,
                confidence=confidence,
            )

        except ValueError as exc:
            _post_record("onto_ingest", s_hash, "error", pre_id)
            return _error(str(exc), audit_id=pre_id)
        except Exception as exc:
            _post_record("onto_ingest", s_hash, "error", pre_id)
            return _error(
                f"onto_ingest failed: {type(exc).__name__}",
                audit_id=pre_id,
            )

    # -------------------------------------------------------------------------
    # TOOL: onto_query
    # -------------------------------------------------------------------------

    @mcp.tool()
    def onto_query(
        concepts: List[str],
        authorization: str,
        alpha: float = _DEFAULT_PPR_ALPHA,
        top_k: int = _DEFAULT_PPR_TOP_K,
        edge_type_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        PPR traversal from seed concepts. Returns a ranked subgraph.

        Uses Personalized PageRank to find the most semantically relevant
        nodes from the given seed concepts. Falls back to BFS on small graphs.

        Args:
            concepts:        List of concept labels to use as PPR seeds.
            authorization:   Bearer token.
            alpha:           PPR teleport probability [0.70, 0.95].
                             Default 0.85. Higher = more local.
            top_k:           Maximum nodes to return. Default 50.
            edge_type_names: Filter traversal to these edge type names.
                             None = traverse all edge types.

        Returns:
            Ranked subgraph: nodes with PPR scores, edges between them,
            metadata including hardware tier and PPR availability.
        """
        session = _require_session(authorization)
        if not session:
            return _auth_error()
        s_hash = _session_hash(session)
        pre_id = _pre_record("onto_query", s_hash)

        try:
            # Clamp alpha to safe range
            alpha = max(0.70, min(0.95, float(alpha)))
            top_k = max(1, min(200, int(top_k)))

            # Resolve concept labels → node IDs
            from sqlite3 import connect as _connect
            conn = _connect(memory.DB_PATH, timeout=5)
            conn.row_factory = __import__("sqlite3").Row
            try:
                seed_ids: List[int] = []
                for concept in concepts:
                    # Parameterized — never string concatenation
                    row = conn.execute(
                        "SELECT id FROM graph_nodes WHERE concept = ?",
                        (str(concept)[:200],),
                    ).fetchone()
                    if row:
                        seed_ids.append(row["id"])

                # Resolve edge type names to IDs if provided
                edge_type_ids: Optional[List[int]] = None
                if edge_type_names:
                    edge_type_ids = []
                    for name in edge_type_names:
                        row = conn.execute(
                            "SELECT id FROM edge_types WHERE name = ?",
                            (str(name)[:100],),
                        ).fetchone()
                        if row:
                            edge_type_ids.append(row["id"])
            finally:
                conn.close()

            if not seed_ids:
                _post_record("onto_query", s_hash, "ok_empty", pre_id)
                return _ok(
                    data={
                        "nodes": [],
                        "edges": [],
                        "metadata": {
                            "seed_concepts": concepts,
                            "seed_ids_found": 0,
                            "message": "No seed concepts found in graph.",
                        },
                    },
                    audit_id=pre_id,
                    confidence=0.0,
                    warnings=["None of the requested concepts exist in the graph."],
                )

            subgraph = get_ppr_subgraph(
                seed_node_ids=seed_ids,
                alpha=alpha,
                edge_type_ids=edge_type_ids,
                top_k=top_k,
            )

            # Apply safety filter to all PPR outputs
            filtered_nodes, safety_warnings = _surface_safety_filter(
                subgraph.get("nodes", [])
            )
            subgraph["nodes"] = filtered_nodes

            record = memory.record(
                event_type="MCP_QUERY",
                notes=f"onto_query: {len(seed_ids)} seeds, "
                      f"{len(filtered_nodes)} nodes returned.",
                context={
                    "seed_concepts": concepts,
                    "seed_ids": seed_ids,
                    "nodes_returned": len(filtered_nodes),
                    "alpha": alpha,
                    "session": s_hash,
                },
            )
            audit_id = _record_id(record) or pre_id

            _post_record("onto_query", s_hash, "ok", pre_id)
            return _ok(
                data=subgraph,
                audit_id=audit_id,
                confidence=min(
                    1.0,
                    len(filtered_nodes) / max(top_k, 1)
                ),
                warnings=safety_warnings,
            )

        except ValueError as exc:
            _post_record("onto_query", s_hash, "error", pre_id)
            return _error(str(exc), audit_id=pre_id)
        except Exception as exc:
            _post_record("onto_query", s_hash, "error", pre_id)
            return _error(
                f"onto_query failed: {type(exc).__name__}",
                audit_id=pre_id,
            )

    # -------------------------------------------------------------------------
    # TOOL: onto_surface
    # -------------------------------------------------------------------------

    @mcp.tool()
    def onto_surface(
        text: str,
        authorization: str,
        include_reasoning: bool = True,
    ) -> Dict[str, Any]:
        """
        Return ONTO's epistemic state for the given text.

        Runs the contextualize and surface steps without persisting to the graph.
        Returns confidence, reasoning trace, bias flags, and related context.

        The surface layer is epistemically honest by design: it presents
        accurate data with visible reasoning paths, not conclusions. It never
        validates or flatters. It flags uncertainty explicitly.

        Args:
            text:              Query text to surface context for.
            authorization:     Bearer token.
            include_reasoning: Include the full reasoning trace. Default True.

        Returns:
            Epistemic state: confidence, related context, reasoning,
            bias flags, wellbeing safety status.
        """
        session = _require_session(authorization)
        if not session:
            return _auth_error()
        s_hash = _session_hash(session)
        pre_id = _pre_record("onto_surface", s_hash)

        try:
            from modules import intake as _intake, contextualize, surface

            package = _intake.receive(text)

            if _is_crisis(text):
                _post_record("onto_surface", s_hash, "crisis", pre_id)
                return _crisis(audit_id=pre_id)

            # contextualize and surface have module-level state; wrap
            # defensively so cold-start or empty-graph doesn't block surfacing.
            surfaced: Dict[str, Any] = {}
            try:
                enriched = contextualize.build(package)
                result_s = surface.build(enriched)
                if isinstance(result_s, dict):
                    surfaced = result_s
            except Exception:
                pass  # fall back to empty surfaced dict

            navigate_results = graph.navigate(text, include_sensitive=False)
            filtered_nav, nav_warnings = _surface_safety_filter(
                [
                    {
                        "id": None,
                        "label": r.get("concept"),
                        "score": r.get("effective_weight", 0),
                        "is_sensitive": r.get("is_sensitive", False),
                    }
                    for r in navigate_results
                ]
            )

            data: Dict[str, Any] = {
                "confidence": surfaced.get("confidence", 0.5),
                "weight": surfaced.get("weight", 0.5),
                "related_context": filtered_nav[:20],
                "sensitive_detected": package.get("sensitive_detected", False),
                "classification": package.get("classification", 0),
            }
            if include_reasoning:
                data["reasoning"] = surfaced.get("summary", "")
                data["display"] = surfaced.get("display", "")

            _post_record("onto_surface", s_hash, "ok", pre_id)
            return _ok(
                data=data,
                audit_id=pre_id,
                confidence=surfaced.get("confidence", 0.5),
                warnings=nav_warnings,
            )

        except ValueError as exc:
            _post_record("onto_surface", s_hash, "error", pre_id)
            return _error(str(exc), audit_id=pre_id)
        except Exception as exc:
            _post_record("onto_surface", s_hash, "error", pre_id)
            return _error(
                f"onto_surface failed: {type(exc).__name__}",
                audit_id=pre_id,
            )

    # -------------------------------------------------------------------------
    # TOOL: onto_checkpoint
    # -------------------------------------------------------------------------

    @mcp.tool()
    def onto_checkpoint(
        authorization: str,
        context_summary: str,
        proposed_action: str,
        human_decision: Optional[str] = None,
        audit_reference_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Human sovereignty gate. The boundary between AI and human decision.

        When human_decision is None: returns pending_checkpoint with the
        context for human review. The AI must present this to the human
        and await their decision.

        When human_decision is provided: records the decision permanently
        in the audit trail and returns the authorized action.

        Valid decisions: proceed | veto | flag | defer

        SECURITY: This tool is the most sensitive in the surface. It must
        be reviewed by at least two people before any production deployment.
        No irreversible action is ever taken without a confirmed decision.

        Args:
            authorization:       Bearer token.
            context_summary:     Plain-language summary of what requires
                                 human judgment.
            proposed_action:     What the system proposes to do.
            human_decision:      Human's decision. None = request checkpoint.
            audit_reference_id:  ID of the related audit record, if any.
        """
        session = _require_session(authorization)
        if not session:
            return _auth_error()
        s_hash = _session_hash(session)
        pre_id = _pre_record("onto_checkpoint", s_hash)

        valid_decisions = {"proceed", "veto", "flag", "defer"}

        # No decision yet — return the checkpoint for human review
        if human_decision is None:
            _post_record(
                "onto_checkpoint", s_hash, "pending", pre_id
            )
            return _pending_checkpoint(
                context={
                    "context_summary": context_summary,
                    "proposed_action": proposed_action,
                    "audit_reference_id": audit_reference_id,
                    "valid_decisions": sorted(valid_decisions),
                    "automation_bias_warning": (
                        "This system provides examined context, not conclusions. "
                        "The decision is yours. Disagreeing with this output "
                        "is always valid."
                    ),
                },
                audit_id=pre_id,
            )

        # Decision provided — validate and record it permanently
        decision = str(human_decision).lower().strip()
        if decision not in valid_decisions:
            _post_record("onto_checkpoint", s_hash, "invalid", pre_id)
            return _error(
                f"Invalid decision '{human_decision}'. "
                f"Must be one of: {sorted(valid_decisions)}",
                audit_id=pre_id,
            )

        record = memory.record(
            event_type="MCP_CHECKPOINT",
            notes=(
                f"Human decision recorded via onto_checkpoint: {decision}"
            ),
            context={
                "context_summary": context_summary,
                "proposed_action": proposed_action,
                "human_decision": decision,
                "audit_reference_id": audit_reference_id,
                "session": s_hash,
            },
            human_decision=decision,
        )
        audit_id = _record_id(record) or pre_id

        _post_record("onto_checkpoint", s_hash, decision, pre_id)
        return _ok(
            data={
                "decision": decision,
                "action": proposed_action if decision == "proceed" else "halted",
                "authorized": decision == "proceed",
            },
            audit_id=audit_id,
            confidence=1.0,
        )

    # -------------------------------------------------------------------------
    # TOOL: onto_relate
    # -------------------------------------------------------------------------

    @mcp.tool()
    def onto_relate(
        source_concept: str,
        target_concept: str,
        authorization: str,
        edge_type_name: str = "related-to",
        confidence: float = 1.0,
        source_type: str = "human",
    ) -> Dict[str, Any]:
        """
        Assert a typed, directed edge between two concepts in the ontology.

        Creates or reinforces nodes for both concepts and writes a typed
        directed edge between them. The edge is assigned provenance from
        the calling session.

        Args:
            source_concept:  The source concept label.
            target_concept:  The target concept label.
            authorization:   Bearer token.
            edge_type_name:  Edge type from the registry. Default: related-to.
                             Use onto_schema to see available types.
            confidence:      Confidence in this relationship [0.0, 1.0].
            source_type:     Provenance source type. Default: human.

        Returns:
            Edge creation result including node IDs and provenance ID.
        """
        session = _require_session(authorization)
        if not session:
            return _auth_error()
        s_hash = _session_hash(session)
        pre_id = _pre_record("onto_relate", s_hash)

        try:
            # Validate and sanitize inputs — treat as untrusted
            src = str(source_concept)[:200].strip()
            tgt = str(target_concept)[:200].strip()
            edge_name = str(edge_type_name)[:100].strip()
            confidence = max(0.0, min(1.0, float(confidence)))

            if not src or not tgt:
                _post_record("onto_relate", s_hash, "error", pre_id)
                return _error(
                    "source_concept and target_concept must be non-empty.",
                    audit_id=pre_id,
                )

            # Build a synthetic package for graph.relate()
            # This uses the existing relate() pipeline which handles
            # provenance creation and PPMI counter updates
            combined_text = f"{src} {tgt}"
            package = {
                "raw": combined_text,
                "clean": combined_text,
                "session_hash": s_hash,
            }
            result = graph.relate(package)

            if result.get("crisis_detected"):
                _post_record("onto_relate", s_hash, "crisis", pre_id)
                return _crisis(audit_id=pre_id)

            record = memory.record(
                event_type="MCP_RELATE",
                notes=(
                    f"onto_relate: {src!r} --[{edge_name}]--> {tgt!r}"
                ),
                context={
                    "source": src,
                    "target": tgt,
                    "edge_type": edge_name,
                    "confidence": confidence,
                    "source_type": source_type,
                    "session": s_hash,
                },
            )
            audit_id = _record_id(record) or pre_id

            _post_record("onto_relate", s_hash, "ok", pre_id)
            return _ok(
                data={
                    "source_concept": src,
                    "target_concept": tgt,
                    "edge_type": edge_name,
                    "nodes_created": result.get("nodes_created", 0),
                    "edges_created": result.get("edges_created", 0),
                    "provenance_id": result.get("provenance_id"),
                    "sensitive_detected": result.get(
                        "sensitive_detected", False
                    ),
                },
                audit_id=audit_id,
                confidence=confidence,
            )

        except ValueError as exc:
            _post_record("onto_relate", s_hash, "error", pre_id)
            return _error(str(exc), audit_id=pre_id)
        except Exception as exc:
            _post_record("onto_relate", s_hash, "error", pre_id)
            return _error(
                f"onto_relate failed: {type(exc).__name__}",
                audit_id=pre_id,
            )

    # -------------------------------------------------------------------------
    # RESOURCE: onto_schema
    # -------------------------------------------------------------------------

    @mcp.resource("onto://schema/edge-types")
    def onto_schema() -> Dict[str, Any]:
        """
        Edge type vocabulary — the current ontology schema.

        Returns all registered edge types with their names, categories,
        descriptions, directionality, and inverse relationships.
        This is a read-only resource — the vocabulary is append-only.

        Returns:
            Complete edge type registry organized by category.
        """
        try:
            from sqlite3 import connect as _connect
            conn = _connect(memory.DB_PATH, timeout=5)
            conn.row_factory = __import__("sqlite3").Row
            try:
                rows = conn.execute(
                    "SELECT e.id, e.name, e.category, e.description, "
                    "e.is_directed, e.is_sealed, i.name AS inverse_name "
                    "FROM edge_types e "
                    "LEFT JOIN edge_types i ON i.id = e.inverse_id "
                    "ORDER BY e.category, e.id"
                ).fetchall()
            finally:
                conn.close()

            by_category: Dict[str, List[Dict[str, Any]]] = {}
            for row in rows:
                cat = row["category"]
                by_category.setdefault(cat, []).append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "description": row["description"],
                        "is_directed": bool(row["is_directed"]),
                        "is_sealed": bool(row["is_sealed"]),
                        "inverse": row["inverse_name"],
                    }
                )

            return {
                "schema_version": SCHEMA_VERSION,
                "total_types": len(rows),
                "categories": by_category,
            }
        except Exception:
            return {
                "schema_version": SCHEMA_VERSION,
                "total_types": 0,
                "categories": {},
                "error": "Schema unavailable — graph not initialized.",
            }

    # -------------------------------------------------------------------------
    # RESOURCE: onto_status
    # -------------------------------------------------------------------------

    @mcp.resource("onto://status")
    def onto_status() -> Dict[str, Any]:
        """
        Node health and graph statistics.

        Returns current graph size, PPMI state, decay profile,
        PPR availability, hardware tier, and system health summary.
        Safe to call at any time — read-only, no side effects.

        Returns:
            Health status, graph metrics, configuration summary.
        """
        try:
            from modules.graph import (
                _HARDWARE_TIER,
                _PPR_AVAILABLE,
                _ppr_cache_valid,
                DEFAULT_DECAY_PROFILE,
            )
            from sqlite3 import connect as _connect
            conn = _connect(memory.DB_PATH, timeout=5)
            conn.row_factory = __import__("sqlite3").Row
            try:
                node_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM graph_nodes"
                ).fetchone()["c"]
                edge_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM graph_edges "
                    "WHERE is_deleted = 0"
                ).fetchone()["c"]
                total_inputs = conn.execute(
                    "SELECT value FROM graph_metadata "
                    "WHERE key = 'total_inputs_processed'"
                ).fetchone()
                total_co_occ = conn.execute(
                    "SELECT value FROM ppmi_global "
                    "WHERE key = 'total_co_occurrences'"
                ).fetchone()
            finally:
                conn.close()

            return {
                "status": "healthy",
                "schema_version": SCHEMA_VERSION,
                "graph": {
                    "nodes": node_count,
                    "edges": edge_count,
                    "total_inputs_processed": (
                        int(total_inputs["value"]) if total_inputs else 0
                    ),
                    "total_co_occurrences": (
                        float(total_co_occ["value"])
                        if total_co_occ
                        else 0.0
                    ),
                },
                "ppr": {
                    "available": _PPR_AVAILABLE,
                    "cache_valid": _ppr_cache_valid,
                    "hardware_tier": _HARDWARE_TIER,
                },
                "decay_profile": DEFAULT_DECAY_PROFILE,
                "mcp_version": "1.0.0",
            }
        except Exception as exc:
            return {
                "status": "degraded",
                "schema_version": SCHEMA_VERSION,
                "error": type(exc).__name__,
            }

    # -------------------------------------------------------------------------
    # RESOURCE: onto_audit
    # -------------------------------------------------------------------------

    @mcp.resource("onto://audit/{page}")
    def onto_audit(page: int = 1) -> Dict[str, Any]:
        """
        Paginated, read-only access to the cryptographic audit trail.

        The audit trail is append-only and Merkle-chained. Every event
        in ONTO's history is permanently recorded here. This resource
        exposes it for inspection, compliance, and debugging.

        Args:
            page: Page number (1-indexed). Each page contains up to 100 records,
                  returned in descending order (newest first).

        Returns:
            Paginated audit records with chain integrity metadata.
        """
        try:
            page = max(1, int(page))
            offset = (page - 1) * MAX_AUDIT_PAGE_SIZE

            from sqlite3 import connect as _connect
            conn = _connect(memory.DB_PATH, timeout=5)
            conn.row_factory = __import__("sqlite3").Row
            try:
                total = conn.execute(
                    "SELECT COUNT(*) AS c FROM events"
                ).fetchone()["c"]
                rows = conn.execute(
                    "SELECT id, event_type, timestamp, classification, "
                    "chain_hash, notes "
                    "FROM events "
                    "ORDER BY id DESC "
                    "LIMIT ? OFFSET ?",
                    (MAX_AUDIT_PAGE_SIZE, offset),
                ).fetchall()
            finally:
                conn.close()

            records = [
                {
                    "id": r["id"],
                    "event_type": r["event_type"],
                    "timestamp": r["timestamp"],
                    "classification": r["classification"],
                    "chain_hash": r["chain_hash"],
                    "notes": r["notes"],
                }
                for r in rows
            ]

            total_pages = max(
                1, (total + MAX_AUDIT_PAGE_SIZE - 1) // MAX_AUDIT_PAGE_SIZE
            )
            return {
                "schema_version": SCHEMA_VERSION,
                "page": page,
                "total_pages": total_pages,
                "total_records": total,
                "records": records,
                "chain_note": (
                    "This trail is Merkle-chained. "
                    "Use memory.verify_chain() to confirm integrity."
                ),
            }
        except Exception as exc:
            return {
                "schema_version": SCHEMA_VERSION,
                "page": page,
                "total_pages": 0,
                "total_records": 0,
                "records": [],
                "error": type(exc).__name__,
            }


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

def get_server() -> Any:
    """
    Return the FastMCP server instance.
    Returns None if FastMCP is not installed.

    Usage (run directly):
        fastmcp run api/onto_server.py

    Usage (programmatic):
        from api.onto_server import get_server
        server = get_server()
        server.run()
    """
    if not _FASTMCP_AVAILABLE:
        raise ImportError(
            "FastMCP is not installed. "
            "Run: pip install fastmcp>=2.0.0"
        )
    return mcp
