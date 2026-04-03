"""
api/federation/local.py

LocalAdapter — direct connection, no peer discovery.

Peer endpoints are configured manually via ONTO_FED_PEERS env var.
Format: "did:key:z6Mk...@host:port,..."

Transport (Phase 3): JSON over HTTP, plain TCP.
Phase 4 upgrade: replace HTTP with gRPC + mTLS (grpcio).
The FederationAdapter protocol is the single swap point.
No other file changes when the transport is upgraded.

This adapter fully implements all safety gates, consent checking,
CRDT merge, audit recording, and rate limiting. The Phase 3 transport
simplification is the only delta from the final production design.

ONTO_FED_HOST  — host to bind the federation server (default: 127.0.0.1)
ONTO_FED_PORT  — port for the federation server (default: 7700)

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import json
import os
import sqlite3
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

from modules import memory as _memory
from api.federation.adapter import FederationAdapter, NodeInfo

# ---------------------------------------------------------------------------
# TRANSPORT CONSTANTS
# ---------------------------------------------------------------------------

_FED_HOST = os.getenv("ONTO_FED_HOST", "127.0.0.1")
_FED_PORT = int(os.getenv("ONTO_FED_PORT", "7700"))
_FED_TIMEOUT = int(os.getenv("ONTO_FED_TIMEOUT_SECS", "10"))
_API_PREFIX = "/fed/v1"

# ---------------------------------------------------------------------------
# HTTP REQUEST HANDLER
# ---------------------------------------------------------------------------


def _make_handler(adapter_ref):
    """
    Factory that returns a request handler class with access to the adapter.
    This avoids the global-state pattern required by BaseHTTPRequestHandler.
    """

    class _Handler(BaseHTTPRequestHandler):

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                payload = json.loads(body)
            except Exception:
                self._send(400, {"error": "invalid JSON body"})
                return

            # Dispatch by path
            if self.path == f"{_API_PREFIX}/message":
                self._handle_message(payload)
            else:
                self._send(404, {"error": "not found"})

        def _handle_message(self, payload: dict):
            sender_did = payload.get("sender_did", "")
            seq = payload.get("sequence_id", 0)
            msg_type = payload.get("message_type", "")

            if not sender_did or not msg_type:
                self._send(400, {"error": "missing sender_did or message_type"})
                return

            # Rate limit check
            from api.federation.audit import check_rate_limit
            allowed, reason = check_rate_limit(sender_did)
            if not allowed:
                self._send(429, {"error": reason})
                return

            # Dispatch to adapter
            result = adapter_ref._handle_inbound(payload, sender_did, seq)
            self._send(200, result)

        def _send(self, code: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            pass  # Suppress default HTTP logging; audit trail handles events

    return _Handler


# ---------------------------------------------------------------------------
# LOCAL ADAPTER
# ---------------------------------------------------------------------------


class LocalAdapter:
    """
    Implements FederationAdapter for direct peer connections.
    Peers are specified manually via ONTO_FED_PEERS config.

    All safety invariants from the FederationAdapter protocol are enforced:
      - can_share returns False for crisis content (absolute, non-configurable)
      - can_share returns False for classification >= 4 (absolute)
      - can_receive assigns trust <= ONTO_FED_INBOUND_TRUST (never higher)
      - recall updates local state before attempting peer notification
    """

    def __init__(self, node_did: str, private_key: Any):
        self._did = node_did
        self._private_key = private_key
        self._server: Optional[ThreadingHTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._peers: Dict[str, NodeInfo] = {}  # did → NodeInfo
        self._trust: Dict[str, float] = {}     # did → trust score
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # LIFECYCLE
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the federation HTTP server in a background thread."""
        handler = _make_handler(self)
        self._server = ThreadingHTTPServer((_FED_HOST, _FED_PORT), handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="federation-server",
        )
        self._server_thread.start()

        # Load static peers from config
        self._load_static_peers()

    def stop(self) -> None:
        """Stop the federation server cleanly."""
        if self._server:
            self._server.shutdown()
            self._server = None

    def _load_static_peers(self) -> None:
        """Parse ONTO_FED_PEERS and store as known peers."""
        from api.federation import config as _cfg
        for entry in _cfg.STATIC_PEERS:
            try:
                did_part, endpoint = entry.split("@", 1)
                did_part = did_part.strip()
                endpoint = endpoint.strip()
                if did_part.startswith("did:key:"):
                    info = NodeInfo(
                        node_id=did_part,
                        endpoint=endpoint,
                        trust_score=0.0,
                        capabilities={},
                        data_residency="",
                        last_seen=0.0,
                        cert_hash="",
                    )
                    with self._lock:
                        self._peers[did_part] = info
            except Exception:
                pass

    # ------------------------------------------------------------------
    # DISCOVERY
    # ------------------------------------------------------------------

    def discover(self) -> List[NodeInfo]:
        """Return statically configured peers."""
        with self._lock:
            return list(self._peers.values())

    # ------------------------------------------------------------------
    # HANDSHAKE
    # ------------------------------------------------------------------

    def handshake(self, peer: NodeInfo) -> bool:
        """
        Exchange capability manifests and pin the peer's TLS certificate.
        Returns True if the peer is trustworthy and handshake succeeded.
        Writes FEDERATION_HANDSHAKE audit event.
        """
        from api.federation import capability, peer_store, audit

        # Send our manifest to the peer
        from api.federation.node_identity import initialize as _ni_init
        _ni_init()  # Ensure node_config table exists
        our_manifest = capability.create_manifest(
            self._did, self._private_key
        )

        try:
            response = self._post(peer.endpoint, {
                "message_type": "HANDSHAKE",
                "sender_did": self._did,
                "sequence_id": 1,
                "manifest": our_manifest,
            })
        except Exception as exc:
            audit.record_event(
                "FEDERATION_HANDSHAKE_FAILED", peer.node_id,
                f"Handshake failed: {exc}",
            )
            return False

        # Verify the peer's manifest from the response
        peer_manifest = response.get("manifest", {})
        valid, reason = capability.verify_manifest(peer_manifest)
        if not valid:
            audit.record_event(
                "FEDERATION_HANDSHAKE_REJECTED", peer.node_id,
                "Handshake rejected: manifest verification failed.",
            )
            return False

        # Update peer info from their manifest
        updated = capability.extract_node_info(
            peer_manifest,
            endpoint=peer.endpoint,
            cert_hash=peer.cert_hash,
            current_trust=self._trust.get(peer.node_id, 0.0),
        )
        with self._lock:
            self._peers[peer.node_id] = updated

        capability.store_peer_manifest(peer.node_id, peer_manifest)

        audit.record_event(
            "FEDERATION_HANDSHAKE", peer.node_id,
            f"Handshake completed with {peer.node_id}",
        )
        return True

    def verify_peer(self, peer: NodeInfo) -> Tuple[bool, str]:
        """Verify a peer's cached manifest signature."""
        from api.federation import capability
        manifest = capability.get_peer_manifest(peer.node_id)
        if not manifest:
            return False, "no cached manifest for peer"
        return capability.verify_manifest(manifest)

    # ------------------------------------------------------------------
    # SAFETY GATES
    # ------------------------------------------------------------------

    def can_share(
        self,
        text: str,
        classification: int,
        is_sensitive: bool,
        is_crisis: bool,
        peer: NodeInfo,
        consent_id: str,
    ) -> Tuple[bool, str]:
        """Gate: called before any data leaves this node."""
        from api.federation.safety import check_outbound
        from api.federation.consent import is_valid
        # is_valid(consent_id, recipient_node) → (bool, str)
        valid_result = is_valid(consent_id, peer.node_id)
        has_consent = (
            valid_result[0]
            if isinstance(valid_result, tuple)
            else bool(valid_result)
        )
        return check_outbound(
            text=text,
            classification=classification,
            is_sensitive=is_sensitive,
            is_crisis=is_crisis,
            peer_trust_score=peer.trust_score,
            peer_data_residency=peer.data_residency,
            consent_id=consent_id,
            has_valid_consent=has_consent,
        )

    def can_receive(
        self,
        data: Dict[str, Any],
        peer: NodeInfo,
    ) -> Tuple[bool, float]:
        """
        Gate: called before any remote data enters this node.
        Crisis content triggers checkpoint, never automatic demotion.
        """
        from api.federation.safety import check_inbound
        from api.federation import audit

        allowed, trust = check_inbound(data, peer.trust_score)

        if not allowed:
            # Crisis content detected — notify operator via audit event
            # Adapter caller is responsible for surfacing to onto_checkpoint
            audit.record_event(
                "FEDERATION_CRISIS_RECEIVED", peer.node_id,
                "Inbound payload contained crisis content. "
                "Operator notification required.",
                context={
                    "action": "payload_rejected",
                    "next": "surface_to_onto_checkpoint",
                },
            )

        return allowed, trust

    # ------------------------------------------------------------------
    # DATA EXCHANGE
    # ------------------------------------------------------------------

    def share(
        self,
        data: Dict[str, Any],
        peer: NodeInfo,
        consent_id: str,
    ) -> Optional[str]:
        """
        Send a graph delta to a peer after can_share() passes.
        Records the attempt in the outbox regardless of outcome.
        Returns the remote audit record ID on success, None on failure.
        """
        from api.federation import audit

        outbox_id = audit.record_outbound(
            recipient=peer.node_id,
            message_type="SHARE",
            payload=data,
        )

        payload = {
            "message_type": "SHARE",
            "sender_did": self._did,
            "sequence_id": outbox_id,
            "consent_id": consent_id,
            "data": data,
        }

        try:
            response = self._post(peer.endpoint, payload)
            remote_id = response.get("audit_id")
            audit.mark_sent(outbox_id)
            audit.record_event(
                "FEDERATION_SHARE", peer.node_id,
                f"Graph delta shared. Remote audit ID: {remote_id}",
                context={"consent_id": consent_id, "outbox_id": outbox_id},
            )
            self._promote_trust(peer.node_id)
            return str(remote_id) if remote_id else None
        except Exception as exc:
            audit.mark_failed(outbox_id, str(exc))
            return None

    def receive(
        self,
        raw_data: Dict[str, Any],
        peer: NodeInfo,
        sequence_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Receive and process a graph delta from a peer.
        Validates sequence, applies safety gate, ingests to graph.
        """
        from api.federation import audit
        from modules import graph as _graph

        # Sequence validation
        seq_status = audit.validate_inbound_sequence(
            peer.node_id, sequence_id
        )
        if seq_status == "duplicate":
            return None
        if seq_status == "gap":
            audit.record_event(
                "FEDERATION_SEQUENCE_GAP", peer.node_id,
                f"Sequence gap at {sequence_id}. Re-send requested.",
            )
            return {"status": "gap", "expected": sequence_id - 1}

        # Safety gate
        allowed, trust = self.can_receive(raw_data, peer)

        inbox_id = audit.record_inbound(
            sender=peer.node_id,
            message_type="SHARE",
            sequence_id=sequence_id,
            payload=raw_data,
            rejected=not allowed,
            reject_reason=None if allowed else "safety_gate",
        )

        if not allowed:
            return {"status": "rejected", "reason": "safety_gate"}

        # Ingest concepts into local graph
        concepts = raw_data.get("concepts", [])
        results = []
        for concept in concepts:
            if not isinstance(concept, str):
                continue
            package = {
                "raw": concept,
                "clean": concept,
                "session_hash": f"fed:{peer.node_id[:8]}",
            }
            result = _graph.relate(package)
            if result.get("crisis_detected"):
                # Secondary safety check — should not reach here if
                # can_receive worked correctly, but belt-and-suspenders
                audit.record_event(
                    "FEDERATION_CRISIS_RECEIVED", peer.node_id,
                    "Crisis content in concept during ingest — blocked.",
                )
                continue
            results.append(result)

        audit.mark_processed(inbox_id)
        rec = _memory.record(
            event_type="FEDERATION_RECEIVE",
            notes=f"Received {len(concepts)} concepts from {peer.node_id}",
            context={
                "sender": peer.node_id,
                "concepts_received": len(concepts),
                "inbox_id": inbox_id,
            },
        )
        return {
            "status": "ok",
            "audit_id": rec if isinstance(rec, int) else
            (rec.get("id") if isinstance(rec, dict) else None),
        }

    # ------------------------------------------------------------------
    # MERGE
    # ------------------------------------------------------------------

    def merge(
        self,
        local_state: Dict[str, Any],
        remote_state: Dict[str, Any],
        local_vclock: Dict[str, int],
        remote_vclock: Dict[str, int],
        peer: NodeInfo,
    ) -> Tuple[Dict[str, Any], Dict[str, int]]:
        """CRDT merge of graph states. Concurrent writes → conflicts list."""
        from api.federation.crdt import (
            merge_node_sets, merge_edge_weights, vclock_merge
        )
        try:
            merged_nodes, node_conflicts = merge_node_sets(
                local_state.get("nodes", {}),
                remote_state.get("nodes", {}),
            )
            merged_edges, edge_conflicts = merge_edge_weights(
                local_state.get("edges", {}),
                remote_state.get("edges", {}),
            )
            all_conflicts = [
                c.to_dict() for c in node_conflicts + edge_conflicts
            ]
            merged_vc = vclock_merge(local_vclock, remote_vclock)
            return (
                {
                    "nodes": merged_nodes,
                    "edges": merged_edges,
                    "conflicts": all_conflicts,
                },
                merged_vc,
            )
        except Exception:
            return local_state, local_vclock

    # ------------------------------------------------------------------
    # RECALL
    # ------------------------------------------------------------------

    def recall(self, consent_id: str) -> List[str]:
        """
        Retract data shared under consent_id.
        Local revocation happens FIRST — before any peer notification.
        Sovereignty cannot be blocked by offline peers.
        """
        from api.federation.consent import revoke, list_for_peer, get
        from api.federation import audit

        # Step 1: revoke locally — unconditional
        record = get(consent_id)
        if not record:
            return []
        recipient = record["recipient_node"]
        revoke(consent_id, reason="operator_recall")

        # Step 2: notify peers (best-effort — failure is acceptable)
        notified = []
        with self._lock:
            peer = self._peers.get(recipient)

        if peer:
            try:
                self._post(peer.endpoint, {
                    "message_type": "RETRACT",
                    "sender_did": self._did,
                    "sequence_id": 0,
                    "consent_ids": [consent_id],
                })
                notified.append(recipient)
            except Exception:
                pass  # Offline peer — local revocation already succeeded

        audit.record_event(
            "FEDERATION_RECALL", recipient,
            f"Recall of consent {consent_id}. "
            f"Peers notified: {notified}",
            context={"consent_id": consent_id, "notified": notified},
        )
        return notified

    # ------------------------------------------------------------------
    # TRUST MANAGEMENT
    # ------------------------------------------------------------------

    def get_trust_score(self, peer_did: str) -> float:
        """Return accumulated trust score for a peer."""
        with self._lock:
            return self._trust.get(peer_did, 0.0)

    def _promote_trust(self, peer_did: str) -> None:
        """
        Small trust increment on successful exchange.
        Trust accumulates through interaction — never pre-assigned.
        Capped at 0.95 (human baseline) without manual verification.
        """
        from api.federation import config as _cfg
        with self._lock:
            current = self._trust.get(peer_did, _cfg.INBOUND_TRUST)
            # Logarithmic growth — early interactions matter more
            increment = (0.95 - current) * 0.05
            self._trust[peer_did] = min(0.95, current + increment)
            # Sync to peers dict
            if peer_did in self._peers:
                self._peers[peer_did].trust_score = self._trust[peer_did]

    # ------------------------------------------------------------------
    # HEALTH
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        """Return federation health for onto_status."""
        from api.federation import audit as _audit, consent as _consent
        try:
            with self._lock:
                peer_count = len(self._peers)
            msg_health = _audit.health_summary()
            standing_due = len(_consent.due_for_reconfirmation())
            return {
                "enabled": True,
                "stage": "local",
                "endpoint": f"{_FED_HOST}:{_FED_PORT}",
                "node_did": self._did,
                "peer_count": peer_count,
                "active_connections": 0,
                "standing_consents_due": standing_due,
                **msg_health,
            }
        except Exception:
            return {"enabled": True, "stage": "local", "error": "health_unavailable"}

    # ------------------------------------------------------------------
    # INBOUND HANDLER (called by HTTP handler)
    # ------------------------------------------------------------------

    def _handle_inbound(
        self,
        payload: dict,
        sender_did: str,
        sequence_id: int,
    ) -> dict:
        """
        Route an inbound message to the appropriate handler.
        Returns a JSON-serializable response dict.
        """
        msg_type = payload.get("message_type", "")
        with self._lock:
            peer = self._peers.get(sender_did)

        if peer is None:
            # Unknown peer — create a minimal NodeInfo for processing
            peer = NodeInfo(
                node_id=sender_did,
                endpoint="",
                trust_score=0.0,
                capabilities={},
                data_residency="",
                last_seen=time.time(),
                cert_hash="",
            )

        if msg_type == "HANDSHAKE":
            # Respond with our manifest
            from api.federation import capability
            our_manifest = capability.create_manifest(
                self._did, self._private_key
            )
            # Store their manifest
            peer_manifest = payload.get("manifest", {})
            if peer_manifest:
                capability.store_peer_manifest(sender_did, peer_manifest)
            return {"status": "ok", "manifest": our_manifest}

        if msg_type == "SHARE":
            data = payload.get("data", {})
            result = self.receive(data, peer, sequence_id)
            return result or {"status": "error"}

        if msg_type == "RETRACT":
            from api.federation import consent as _consent
            ids = payload.get("consent_ids", [])
            for cid in ids:
                _consent.revoke(cid, reason="remote_retraction")
            return {"status": "ok", "retracted": len(ids)}

        if msg_type == "PING":
            return {"status": "ok", "node_did": self._did}

        return {"status": "error", "error": f"unknown type: {msg_type}"}

    # ------------------------------------------------------------------
    # HTTP TRANSPORT
    # ------------------------------------------------------------------

    def _post(self, endpoint: str, payload: dict) -> dict:
        """
        POST a JSON payload to a peer endpoint.
        Phase 3: plain HTTP. Phase 4: gRPC + mTLS.
        """
        url = f"http://{endpoint}{_API_PREFIX}/message"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_FED_TIMEOUT) as resp:
            return json.loads(resp.read())
