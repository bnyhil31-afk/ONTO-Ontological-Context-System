"""
api/federation/capability.py

Capability manifests for federation node advertisement.

Every node publishes a signed capability manifest before any peer can
route queries to it. The manifest describes what the node can do and
what data it will accept.

Manifest format follows the spec (FEDERATION-SPEC-001 §5):
  - VoID descriptor (graph statistics, edge types supported)
  - ONTO-specific capabilities (stage, tools, classification ceiling)
  - Ed25519 signature over JCS-canonical JSON (RFC 8785)
  - spec_version for forward compatibility negotiation

Signature verification:
  - Invalid signatures are rejected silently (no error log) to prevent
    timing attacks that could enumerate nodes
  - The crisis_barrier field is self-reported — can_receive() ALWAYS
    applies _contains_crisis() regardless of manifest claims

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from modules import memory as _memory

_SPEC_VERSION = "FEDERATION-SPEC-001-v1.1"


# ---------------------------------------------------------------------------
# MANIFEST CREATION
# ---------------------------------------------------------------------------

def create_manifest(
    node_did: str,
    private_key: Any,   # Ed25519PrivateKey from cryptography library
) -> Dict[str, Any]:
    """
    Create and sign a capability manifest for this node.

    The manifest snapshot reflects the current graph statistics and
    configuration. It should be regenerated periodically (e.g. on
    every federation_manager.start() and every 24 hours).

    Returns the complete signed manifest dict.
    """
    from api.federation import config as _cfg
    from api.federation.node_identity import sign_json

    manifest = _build_manifest_body(node_did)
    signature_bytes = sign_json(private_key, manifest)

    import base64
    manifest["signature"] = base64.urlsafe_b64encode(
        signature_bytes
    ).decode("ascii")

    return manifest


def _build_manifest_body(node_did: str) -> Dict[str, Any]:
    """
    Build the unsigned manifest body from current config and graph state.
    """
    from api.federation import config as _cfg

    void_descriptor = _build_void_descriptor()
    tools = _get_available_tools()
    edge_types = _get_supported_edge_types()

    return {
        "node_id":      node_did,
        "onto_version": _get_onto_version(),
        "spec_version": _SPEC_VERSION,
        "signed_at":    _iso_now(),
        "capabilities": {
            "federation_stage":     _cfg.FEDERATION_STAGE,
            "tools_available":      tools,
            "edge_types_supported": edge_types,
            "max_classification":   _cfg.MAX_SHARE_CLASSIFICATION,
            "crisis_barrier":       True,   # always True — non-negotiable
            "consent_mode":         _cfg.CONSENT_MODE,
            "data_residency":       sorted(_cfg.DATA_RESIDENCY),
            "rate_limit_per_min":   _cfg.MAX_MSGS_PER_PEER_PER_MIN,
        },
        "void_descriptor":    void_descriptor,
        "regulatory_profile": _get_regulatory_profile(),
        "min_peer_trust_score": 0.70,
        "max_graph_similarity": _cfg.MAX_GRAPH_SIMILARITY,
    }


def _build_void_descriptor() -> Dict[str, Any]:
    """
    Build a VoID (Vocabulary of Interlinked Datasets) descriptor from
    the current graph state. Used by peers for semantic query routing.
    Returns zero values safely if the graph is not available.
    """
    try:
        conn = sqlite3.connect(
            _memory.DB_PATH, check_same_thread=False, timeout=5
        )
        conn.row_factory = sqlite3.Row
        try:
            nodes = conn.execute(
                "SELECT COUNT(*) AS c FROM graph_nodes"
            ).fetchone()["c"]
            edges = conn.execute(
                "SELECT COUNT(*) AS c FROM graph_edges WHERE is_deleted = 0"
            ).fetchone()["c"]
            edge_types = conn.execute(
                "SELECT DISTINCT t.name FROM edge_types t "
                "INNER JOIN graph_edges e ON e.edge_type_id = t.id "
                "WHERE e.is_deleted = 0 ORDER BY t.name"
            ).fetchall()
            type_names = [r["name"] for r in edge_types]
        finally:
            conn.close()

        return {
            "triples":    edges,
            "nodes":      nodes,
            "predicates": type_names,
        }
    except Exception:
        return {"triples": 0, "nodes": 0, "predicates": []}


def _get_available_tools() -> List[str]:
    """
    Return list of MCP tool names this node exposes.
    Introspects the onto_server module if available.
    """
    try:
        from api.onto_server import _FASTMCP_AVAILABLE
        if _FASTMCP_AVAILABLE:
            return [
                "onto_ingest", "onto_query", "onto_surface",
                "onto_checkpoint", "onto_relate",
                "onto_schema", "onto_status", "onto_audit",
            ]
    except ImportError:
        pass
    return []


def _get_supported_edge_types() -> List[str]:
    """Return edge type names from the registry."""
    try:
        conn = sqlite3.connect(
            _memory.DB_PATH, check_same_thread=False, timeout=5
        )
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT name FROM edge_types ORDER BY id"
            ).fetchall()
            return [r["name"] for r in rows]
        finally:
            conn.close()
    except Exception:
        return ["related-to", "co-occurs-with"]


def _get_regulatory_profile() -> str:
    """Return the active decay profile as the regulatory profile hint."""
    try:
        from modules.graph import DEFAULT_DECAY_PROFILE
        return DEFAULT_DECAY_PROFILE
    except Exception:
        return "general"


def _get_onto_version() -> str:
    """Return the ONTO version string."""
    try:
        from core.config import config
        return getattr(config, "VERSION", "1.0.0")
    except Exception:
        return "1.0.0"


def _iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# MANIFEST VERIFICATION
# ---------------------------------------------------------------------------

def verify_manifest(manifest: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Verify a received capability manifest.

    Checks:
      1. Required fields are present
      2. spec_version is compatible
      3. Ed25519 signature is valid

    Returns (valid, reason).

    Invalid signatures are not logged — this function returns False
    silently to prevent timing attacks that could enumerate nodes.
    Even the reason string for signature failures is kept generic.
    """
    # Required fields
    required = {
        "node_id", "onto_version", "spec_version",
        "signed_at", "signature", "capabilities",
    }
    missing = required - set(manifest.keys())
    if missing:
        return False, f"missing fields: {sorted(missing)}"

    # spec_version compatibility check
    received_spec = manifest.get("spec_version", "")
    if not received_spec.startswith("FEDERATION-SPEC-001"):
        return (
            False,
            "incompatible spec_version; expected FEDERATION-SPEC-001",
        )

    # Signature verification
    node_did = manifest.get("node_id", "")
    if not node_did.startswith("did:key:"):
        return False, "invalid node_id format"

    try:
        import base64
        from api.federation.node_identity import verify_json

        # Rebuild the body without the signature field for verification
        body = {k: v for k, v in manifest.items() if k != "signature"}
        sig_bytes = base64.urlsafe_b64decode(manifest["signature"])

        if not verify_json(node_did, body, sig_bytes):
            return False, "signature verification failed"

    except Exception:
        return False, "signature verification failed"

    return True, "valid"


def extract_node_info(
    manifest: Dict[str, Any],
    endpoint: str,
    cert_hash: str,
    current_trust: float = 0.0,
) -> "NodeInfo":
    """
    Convert a verified capability manifest into a NodeInfo object.
    Should only be called after verify_manifest() returns (True, ...).
    """
    from api.federation.adapter import NodeInfo

    caps = manifest.get("capabilities", {})
    residency_list = caps.get("data_residency", [])
    residency = ",".join(residency_list) if residency_list else ""

    return NodeInfo(
        node_id=manifest["node_id"],
        endpoint=endpoint,
        trust_score=current_trust,
        capabilities=caps,
        data_residency=residency,
        last_seen=time.time(),
        cert_hash=cert_hash,
        onto_version=manifest.get("onto_version", ""),
        spec_version=manifest.get("spec_version", ""),
        federation_stage=caps.get("federation_stage", "local"),
    )


# ---------------------------------------------------------------------------
# MANIFEST STORAGE
# ---------------------------------------------------------------------------

def store_peer_manifest(
    peer_did: str,
    manifest: Dict[str, Any],
) -> None:
    """
    Cache a peer's manifest in federation_node_config for quick retrieval.
    Overwrites any previous manifest for this peer.
    Key format: "peer_manifest:{peer_did}"
    """
    import json
    from api.federation.node_identity import _config_set as _cfg_set
    key = f"peer_manifest:{peer_did}"
    try:
        _cfg_set(key, json.dumps(manifest, sort_keys=True))
    except Exception:
        pass


def get_peer_manifest(peer_did: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a cached peer manifest. Returns None if not found.
    """
    import json
    from api.federation.node_identity import _config_get
    key = f"peer_manifest:{peer_did}"
    raw = _config_get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None
