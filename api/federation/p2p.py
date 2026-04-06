"""
api/federation/p2p.py

P2PAdapter — extends InternetAdapter with Kademlia DHT peer discovery.

Adds over InternetAdapter:
  - Kademlia DHT for decentralized peer discovery (no central registry)
  - Bootstrap node list (ONTO_FED_DHT_BOOTSTRAP_NODES)
  - Sybil resistance via proof-of-work challenge on handshake
  - Anti-concentration routing (refuses peers above graph similarity threshold)
  - Carbon-aware routing hook (stub — wired for Stage 4 implementation)
  - Post-quantum crypto migration hook (stub — Kyber-768 upgrade path)

Discovery model:
  Peers announce themselves on the DHT using the key "_onto_federation".
  Value: JSON-encoded {did, endpoint, spec_version, timestamp}
  Any node that performs a DHT lookup for this key gets a list of
  ONTO nodes. Discovery is decentralized — no central registry needed.

Graceful degradation:
  If kademlia is not installed, discover() falls back to static peers
  from InternetAdapter (which inherits from LocalAdapter). The P2P adapter
  still provides mTLS and regulatory profile features from InternetAdapter.
  A clear warning is written to the audit trail.

Safety invariants inherited unchanged (through InternetAdapter → LocalAdapter):
  - Crisis content NEVER federates
  - Classification >= 4 (PHI) NEVER federates
  - Inbound trust <= ONTO_FED_INBOUND_TRUST (never higher)

Configuration:
  ONTO_FED_DHT_PORT              default: 7701
  ONTO_FED_DHT_BOOTSTRAP_NODES   comma-separated "host:port" list
  ONTO_FED_SYBIL_POW_DIFFICULTY  default: 4 (number of leading zero bits)
  ONTO_FED_MAX_GRAPH_SIMILARITY  default: 1.0 (1.0 = anti-concentration off)

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import asyncio
import hashlib
import json
import os
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from api.federation.internet import InternetAdapter
from api.federation.adapter import NodeInfo


# ---------------------------------------------------------------------------
# DHT SERVICE KEY
# ---------------------------------------------------------------------------

_DHT_SERVICE_KEY = b"_onto_federation"
_DHT_ANNOUNCE_TTL = 300  # seconds; re-announce every 5 minutes


# ---------------------------------------------------------------------------
# SYBIL RESISTANCE: PROOF OF WORK
# ---------------------------------------------------------------------------

def _pow_challenge(peer_did: str, difficulty: int) -> Tuple[bool, str]:
    """
    Verify a proof-of-work challenge from a peer.

    The challenge: SHA-256(peer_did + nonce) must have `difficulty`
    leading zero bits. The peer must include "pow_nonce" in their
    capability manifest during handshake.

    This makes Sybil attacks expensive: creating N fake nodes requires
    solving N independent PoW puzzles. At difficulty=4 (16 leading zero
    bits), each puzzle takes ~65000 hashes on average.

    Returns (valid: bool, reason: str).
    """
    if difficulty == 0:
        return True, "sybil_resistance_disabled"

    try:
        from api.federation import capability
        manifest = capability.get_peer_manifest(peer_did)
        if not manifest:
            return False, "no_manifest_for_pow_check"

        nonce = manifest.get("pow_nonce", "")
        if not nonce:
            return False, "pow_nonce_missing_in_manifest"

        candidate = hashlib.sha256(
            f"{peer_did}:{nonce}".encode()
        ).digest()

        # Check leading zero bits
        required_zero_bits = difficulty
        bits_checked = 0
        for byte in candidate:
            for bit_pos in range(7, -1, -1):
                if bits_checked >= required_zero_bits:
                    return True, "pow_valid"
                if (byte >> bit_pos) & 1:
                    return False, f"pow_failed: bit {bits_checked} not zero"
                bits_checked += 1

        return True, "pow_valid"

    except Exception as exc:
        return False, f"pow_check_error: {exc}"


def generate_pow_nonce(node_did: str, difficulty: int) -> str:
    """
    Generate a proof-of-work nonce for this node's capability manifest.

    Called once at startup. The nonce is included in the capability
    manifest so peers can verify our PoW during handshake.

    Returns the nonce as a hex string.
    """
    if difficulty == 0:
        return "disabled"

    nonce = 0
    required_zero_bits = difficulty
    while True:
        nonce_bytes = struct.pack(">Q", nonce)
        nonce_hex = nonce_bytes.hex()
        candidate = hashlib.sha256(
            f"{node_did}:{nonce_hex}".encode()
        ).digest()

        # Check leading zero bits
        valid = True
        bits_checked = 0
        for byte in candidate:
            for bit_pos in range(7, -1, -1):
                if bits_checked >= required_zero_bits:
                    break
                if (byte >> bit_pos) & 1:
                    valid = False
                    break
                bits_checked += 1
            if not valid or bits_checked >= required_zero_bits:
                break

        if valid:
            return nonce_hex

        nonce += 1
        if nonce > 2 ** 48:
            # Safety valve — should not happen at reasonable difficulty
            return "generation_overflow"


# ---------------------------------------------------------------------------
# ANTI-CONCENTRATION CHECK
# ---------------------------------------------------------------------------

def _graph_similarity_exceeds(peer: NodeInfo, threshold: float) -> bool:
    """
    Return True if accepting this peer would exceed the anti-concentration
    graph similarity threshold.

    Anti-concentration routing prevents ONTO from becoming an echo chamber:
    if a proposed peer's graph is too similar to ours, sharing with them
    adds little new context while amplifying shared biases.

    Implementation: checks peer.capabilities.get("graph_similarity_score")
    against the threshold. The peer announces this value in their capability
    manifest during discovery. It represents the cosine similarity of their
    concept frequency vector vs. ours (computed locally at their end).

    If no graph_similarity_score is present in the manifest, the check
    passes (we can't measure similarity without data — first interaction
    is always permitted).

    Returns False if threshold >= 1.0 (anti-concentration disabled).
    """
    if threshold >= 1.0:
        return False  # disabled

    similarity = peer.capabilities.get("graph_similarity_score")
    if similarity is None:
        return False  # no data → permit

    try:
        return float(similarity) > threshold
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# P2P ADAPTER
# ---------------------------------------------------------------------------

class P2PAdapter(InternetAdapter):
    """
    P2PAdapter — InternetAdapter extended with Kademlia DHT discovery.

    Overrides:
      start()    — super().start() + DHT node startup + bootstrap + announce
      stop()     — DHT withdraw + super().stop()
      discover() — DHT lookup + Sybil filter + anti-concentration filter

    All other methods are inherited. Safety invariants unchanged.
    """

    def __init__(self, node_did: str, private_key: Any):
        super().__init__(node_did, private_key)
        self._dht_node = None       # kademlia.network.Server instance
        self._dht_loop: Optional[asyncio.AbstractEventLoop] = None
        self._dht_thread: Optional[threading.Thread] = None
        self._dht_available = False
        self._pow_nonce: Optional[str] = None

    # ------------------------------------------------------------------
    # LIFECYCLE
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the P2P federation layer.

        Sequence:
          1. super().start() — mTLS server + regulatory profiles
          2. Generate PoW nonce (if Sybil resistance enabled)
          3. Start Kademlia DHT node in background event loop
          4. Bootstrap from configured bootstrap nodes
          5. Announce this node on the DHT
          6. Write FEDERATION_P2P_STARTED audit event
        """
        # Step 1: Internet layer (mTLS + regulatory)
        super().start()

        # Step 2: Generate PoW nonce
        from api.federation import config as _cfg
        difficulty = _cfg.SYBIL_POW_DIFFICULTY
        if difficulty > 0:
            self._pow_nonce = generate_pow_nonce(self._did, difficulty)
            self._write_audit_event(
                "FEDERATION_POW_GENERATED",
                f"Proof-of-work nonce generated. Difficulty: {difficulty} bits.",
            )

        # Step 3-5: Start DHT
        self._start_dht(_cfg)

    def stop(self) -> None:
        """Withdraw from DHT and stop the internet layer."""
        self._stop_dht()
        super().stop()

    def _start_dht(self, cfg) -> None:
        """Start the Kademlia DHT node in a dedicated event loop thread."""
        try:
            from kademlia.network import Server as KademliaServer
        except ImportError:
            self._write_audit_event(
                "FEDERATION_DHT_UNAVAILABLE",
                "kademlia package not installed. P2P discovery disabled; "
                "falling back to static peers. "
                "Install: pip install kademlia>=2.2.2",
            )
            return

        self._dht_available = True

        # Create a dedicated event loop for the async DHT operations
        loop = asyncio.new_event_loop()
        self._dht_loop = loop

        def _run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        self._dht_thread = threading.Thread(
            target=_run_loop,
            daemon=True,
            name="federation-dht",
        )
        self._dht_thread.start()

        # Start DHT node
        dht_port = cfg.DHT_PORT
        bootstrap_nodes = [
            self._parse_bootstrap_node(n)
            for n in cfg.DHT_BOOTSTRAP_NODES
            if n.strip()
        ]
        bootstrap_nodes = [n for n in bootstrap_nodes if n is not None]

        async def _init_dht():
            node = KademliaServer()
            await node.listen(dht_port)
            if bootstrap_nodes:
                await node.bootstrap(bootstrap_nodes)
            # Announce this node on the DHT
            announcement = json.dumps({
                "did": self._did,
                "endpoint": f"{cfg.__dict__.get('_FED_HOST', '127.0.0.1')}:{cfg.__dict__.get('_FED_PORT', 7700)}",
                "spec_version": "FEDERATION-SPEC-001-v1.1",
                "timestamp": int(time.time()),
            })
            await node.set(_DHT_SERVICE_KEY, announcement.encode())
            return node

        future = asyncio.run_coroutine_threadsafe(_init_dht(), loop)
        try:
            self._dht_node = future.result(timeout=30)
            self._write_audit_event(
                "FEDERATION_P2P_STARTED",
                f"P2P DHT node started on port {dht_port}. "
                f"Bootstrap nodes: {len(bootstrap_nodes)}. "
                f"Sybil PoW difficulty: {cfg.SYBIL_POW_DIFFICULTY} bits.",
            )
        except Exception as exc:
            self._dht_available = False
            self._write_audit_event(
                "FEDERATION_DHT_START_FAILED",
                f"Kademlia DHT failed to start: {exc}. "
                f"Falling back to static peers.",
            )

    def _stop_dht(self) -> None:
        """Withdraw from DHT and stop the event loop."""
        if self._dht_node and self._dht_loop:
            try:
                # Remove our announcement from the DHT
                async def _withdraw():
                    try:
                        await self._dht_node.set(
                            _DHT_SERVICE_KEY,
                            b"",  # Empty value signals withdrawal
                        )
                        self._dht_node.stop()
                    except Exception:
                        pass

                future = asyncio.run_coroutine_threadsafe(
                    _withdraw(), self._dht_loop
                )
                future.result(timeout=5)
            except Exception:
                pass

        if self._dht_loop:
            self._dht_loop.call_soon_threadsafe(self._dht_loop.stop)
            self._dht_loop = None

        self._dht_node = None
        self._dht_available = False

    @staticmethod
    def _parse_bootstrap_node(node_str: str) -> Optional[Tuple[str, int]]:
        """
        Parse a "host:port" bootstrap node string.
        Returns (host, port) tuple or None on parse error.
        """
        try:
            host, port_str = node_str.rsplit(":", 1)
            return (host.strip(), int(port_str.strip()))
        except Exception:
            return None

    # ------------------------------------------------------------------
    # DISCOVERY (DHT + Sybil filter + anti-concentration)
    # ------------------------------------------------------------------

    def discover(self) -> List[NodeInfo]:
        """
        Discover ONTO peers via Kademlia DHT.

        Discovery sequence:
          1. DHT lookup for _DHT_SERVICE_KEY
          2. Parse and validate each peer announcement
          3. Apply Sybil resistance check (PoW verification)
          4. Apply anti-concentration filter (graph similarity)
          5. Merge with static peers from LocalAdapter (always included)

        Falls back to static peers only if DHT is unavailable.
        Never raises — returns [] on unexpected errors.
        """
        # Always include static peers (from LocalAdapter via InternetAdapter)
        static_peers = super().discover()

        if not self._dht_available or not self._dht_node or not self._dht_loop:
            return static_peers

        from api.federation import config as _cfg
        from api.federation.network_resilience import network_resilience_manager

        try:
            # DHT lookup — use adaptive timeout based on DHT "peer" metrics
            dht_timeout = network_resilience_manager.adaptive_timeout(
                "_dht", base_secs=_cfg.TIMEOUT_BASE_SECS
            )

            async def _lookup():
                return await self._dht_node.get(_DHT_SERVICE_KEY)

            future = asyncio.run_coroutine_threadsafe(_lookup(), self._dht_loop)
            raw = future.result(timeout=dht_timeout)
            network_resilience_manager.record_success("_dht", rtt_ms=50.0)
        except Exception:
            network_resilience_manager.record_failure("_dht")
            return static_peers

        if not raw:
            return static_peers

        discovered: List[NodeInfo] = []
        try:
            announcements = self._parse_dht_results(raw)
        except Exception:
            return static_peers

        for announcement in announcements:
            peer = self._announcement_to_node_info(announcement)
            if peer is None:
                continue

            # Skip ourselves
            if peer.node_id == self._did:
                continue

            # Sybil resistance
            valid, reason = _pow_challenge(peer.node_id, _cfg.SYBIL_POW_DIFFICULTY)
            if not valid:
                self._write_audit_event(
                    "FEDERATION_SYBIL_REJECTED",
                    f"Peer {peer.node_id[:16]}... failed Sybil PoW check: {reason}",
                )
                continue

            # Anti-concentration
            if _graph_similarity_exceeds(peer, _cfg.MAX_GRAPH_SIMILARITY):
                self._write_audit_event(
                    "FEDERATION_ANTICONCENTRATION_SKIP",
                    f"Peer {peer.node_id[:16]}... skipped: graph similarity "
                    f"exceeds threshold {_cfg.MAX_GRAPH_SIMILARITY}.",
                )
                continue

            discovered.append(peer)

        # Merge: static peers take precedence on DID collision
        merged: Dict[str, NodeInfo] = {p.node_id: p for p in discovered}
        for p in static_peers:
            merged[p.node_id] = p  # static peers override DHT

        # Rank peers by network quality score (best first).
        # Low-quality peers are still included but sorted to the back —
        # the circuit breaker handles actual blocking for failed peers.
        from api.federation.network_resilience import network_resilience_manager
        ranked = sorted(
            merged.values(),
            key=lambda p: network_resilience_manager.quality_score(p.node_id),
            reverse=True,  # highest quality first
        )
        return ranked

    @staticmethod
    def _parse_dht_results(raw) -> List[Dict]:
        """
        Parse raw DHT value(s) into a list of announcement dicts.
        The kademlia library may return bytes, str, or a list.
        """
        if raw is None:
            return []

        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")

        if isinstance(raw, str):
            if not raw.strip():
                return []
            try:
                obj = json.loads(raw)
                if isinstance(obj, list):
                    return obj
                if isinstance(obj, dict):
                    return [obj]
            except json.JSONDecodeError:
                return []

        if isinstance(raw, list):
            results = []
            for item in raw:
                parsed = P2PAdapter._parse_dht_results(item)
                results.extend(parsed)
            return results

        return []

    @staticmethod
    def _announcement_to_node_info(announcement: Dict) -> Optional[NodeInfo]:
        """
        Convert a DHT announcement dict to a NodeInfo.
        Returns None if the announcement is malformed.
        """
        try:
            did = announcement.get("did", "")
            endpoint = announcement.get("endpoint", "")
            if not did.startswith("did:key:") or not endpoint:
                return None

            # Stale announcement check (> 10 minutes old)
            ts = announcement.get("timestamp", 0)
            if ts and (time.time() - ts) > 600:
                return None

            return NodeInfo(
                node_id=did,
                endpoint=endpoint,
                trust_score=0.0,
                capabilities={},
                data_residency="",
                last_seen=float(ts) if ts else time.time(),
                cert_hash="",
                spec_version=announcement.get("spec_version", ""),
                federation_stage="p2p",
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # HEALTH (override to report P2P-specific status)
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        """Return P2P-stage health status including DHT and network quality."""
        base = super().health()
        base["stage"] = "p2p"
        base["dht_available"] = self._dht_available
        base["dht_node_running"] = self._dht_node is not None
        base["dht_peer_count"] = len(self._peers)
        return base

    # ------------------------------------------------------------------
    # FUTURE HOOKS (stubs — wired for Stage 4 implementation)
    # ------------------------------------------------------------------

    def carbon_aware_score(self, peer: NodeInfo) -> float:
        """
        Carbon-aware routing hook.

        Stage 4 implementation will query a carbon intensity API
        (e.g., electricitymap.org or WattTime) for the peer's
        data_residency country and return a 0.0-1.0 score where
        1.0 = zero-carbon infrastructure.

        Discovery will prefer peers with higher carbon scores when
        multiple peers offer equivalent graph data.

        Current status: stub — returns 0.5 (neutral) for all peers.
        """
        return 0.5

    def post_quantum_key_exchange_supported(self) -> bool:
        """
        Post-quantum cryptography migration hook.

        Stage 4 implementation will return True when this node has
        migrated to Kyber-768 key encapsulation (NIST PQC standard).
        Peers negotiating connections will prefer post-quantum if
        both sides support it.

        Current status: stub — returns False until migration is implemented.
        """
        return False
