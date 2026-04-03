"""
api/federation/adapter.py

FederationAdapter protocol and NodeInfo dataclass.

This file is a pure protocol definition. It contains no implementation,
no network code, no database calls, no external library imports.
It is importable even when federation dependencies are not installed.

The FederationAdapter protocol is the single swap point for all
federation behavior. Any legal, safety, or security concern is
addressed by wrapping or replacing the adapter. The rest of the
codebase — pipeline, graph, MCP interface — never changes.

Safety invariants encoded in the PROTOCOL (not in config):
  - can_share()   ALWAYS returns (False, reason) for crisis content
  - can_share()   ALWAYS returns (False, reason) for classification >= 4
  - can_receive() ALWAYS assigns trust_score <= ONTO_FED_INBOUND_TRUST
  - recall()      ALWAYS succeeds locally even if peers are offline

These invariants are verified by TestAbsoluteBarriers — safety-critical
tests that block deployment if they fail.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    from typing import Protocol, runtime_checkable
except ImportError:
    from typing_extensions import Protocol, runtime_checkable  # type: ignore


# ---------------------------------------------------------------------------
# NODE INFO
# ---------------------------------------------------------------------------

@dataclass
class NodeInfo:
    """
    Everything known about a peer node.
    Populated from the peer's capability manifest during handshake.
    """
    node_id: str              # did:key identifier
    endpoint: str             # mTLS endpoint — "host:port"
    trust_score: float        # accumulated local trust score [0.0, 1.0]
    capabilities: Dict        # VoID descriptor + capability manifest
    data_residency: str       # ISO 3166-1 alpha-2 codes, comma-separated
    last_seen: float          # epoch of last successful contact
    cert_hash: str            # SHA-256 of pinned TLS certificate (TOFU)

    # Optional fields — present after extended interaction
    onto_version: str = ""
    spec_version: str = ""
    federation_stage: str = ""

    def max_share_classification(self) -> int:
        """
        Return the maximum classification this peer will accept.
        Parsed from capabilities.max_classification, default 0 (public).
        """
        return self.capabilities.get("max_classification", 0)

    def crisis_barrier_claimed(self) -> bool:
        """
        Whether this peer claims to enforce the crisis content barrier.
        WARNING: This is self-reported. can_receive() still runs
        _contains_crisis() on all inbound payloads regardless of this claim.
        """
        return bool(self.capabilities.get("crisis_barrier", False))

    def data_residency_set(self):
        """Return data_residency as a frozenset of country codes."""
        return frozenset(
            r.strip().upper()
            for r in self.data_residency.split(",")
            if r.strip()
        )


# ---------------------------------------------------------------------------
# FEDERATION ADAPTER PROTOCOL
# ---------------------------------------------------------------------------

@runtime_checkable
class FederationAdapter(Protocol):
    """
    The complete federation contract.

    Every concrete implementation (LocalAdapter, IntranetAdapter, ...) must
    implement all methods. The protocol is checkable at runtime via
    isinstance(adapter, FederationAdapter).

    Safety invariants — MUST hold in every implementation:
      can_share(is_crisis=True, ...) → (False, "crisis content never federates")
      can_share(classification>=4, ...) → (False, "classification 4+ ...")
      can_receive(data, peer) → assigned trust <= ONTO_FED_INBOUND_TRUST
      recall(consent_id) → local record updated even if peers unreachable
    """

    def start(self) -> None:
        """
        Start the federation layer. Idempotent.
        Initializes discovery, messaging tables, and identity.
        Raises FederationDepsError if required deps are missing.
        """
        ...

    def stop(self) -> None:
        """
        Stop the federation layer gracefully.
        Releases discovery resources and closes peer connections.
        """
        ...

    def discover(self) -> List[NodeInfo]:
        """
        Discover available peer nodes using this adapter's protocol.
        Returns empty list if no peers found — never raises.
        local:    returns STATIC_PEERS from config
        intranet: returns mDNS-discovered peers
        """
        ...

    def handshake(self, peer: NodeInfo) -> bool:
        """
        Exchange capability manifests and pin the peer's certificate (TOFU).
        Returns True if handshake succeeded and peer is trustworthy.
        Writes FEDERATION_HANDSHAKE audit event.

        A successful handshake:
          1. Verifies peer's capability manifest signature
          2. Pins peer's TLS certificate (or verifies against pinned value)
          3. Records NodeInfo in local peer registry
          4. Writes audit event on both nodes
        """
        ...

    def verify_peer(self, peer: NodeInfo) -> Tuple[bool, str]:
        """
        Verify a peer's capability manifest signature against their did:key.
        Returns (valid, reason).
        A peer with an invalid signature is rejected without logging the
        failure details — doing so could enable timing-based node enumeration.
        """
        ...

    def can_share(
        self,
        text: str,
        classification: int,
        is_sensitive: bool,
        is_crisis: bool,
        peer: NodeInfo,
        consent_id: str,
    ) -> Tuple[bool, str]:
        """
        Gate function. Returns (allowed, reason).
        Called BEFORE any data leaves this node.

        INVARIANTS (not configurable):
          is_crisis=True     → (False, "crisis content never federates")
          classification >= 4 → (False, "classification 4+ never federates")

        Also returns False for:
          No valid consent record for consent_id
          classification > ONTO_FED_MAX_SHARE_CLASSIFICATION
          is_sensitive and peer.trust_score < SENSITIVE_TRUST_THRESHOLD
          peer.data_residency not in permitted DATA_RESIDENCY
          peer certificate changed since TOFU pinning
        """
        ...

    def can_receive(
        self,
        data: Dict[str, Any],
        peer: NodeInfo,
    ) -> Tuple[bool, float]:
        """
        Gate function. Returns (allowed, assigned_trust_score).
        Called BEFORE any remote data enters this node.

        INVARIANTS:
          - Runs _contains_crisis() on all text fields in data
          - assigned_trust_score is always <= ONTO_FED_INBOUND_TRUST
          - The sender's claimed trust score is ignored entirely

        If crisis content is found:
          Returns (False, 0.0) and triggers onto_checkpoint notification.
          Does NOT automatically disconnect — operator decides.
        """
        ...

    def share(
        self,
        data: Dict[str, Any],
        peer: NodeInfo,
        consent_id: str,
    ) -> Optional[str]:
        """
        Send data to a peer after can_share() gate passes.
        Records the attempt in the outbox (with sequence_id).
        Returns the remote audit record ID on success, None on failure.
        Failure is recorded in outbox (failed_at, failure_reason).
        Retry is operator-initiated — no automatic retry.
        Writes FEDERATION_SHARE audit events on both nodes.
        """
        ...

    def receive(
        self,
        raw_data: Dict[str, Any],
        peer: NodeInfo,
        sequence_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Receive data from a peer after can_receive() gate passes.
        Validates sequence_id — requests re-send if gap detected.
        Strips all trust claims from the sender.
        Assigns trust_score = ONTO_FED_INBOUND_TRUST (never higher).
        Writes FEDERATION_RECEIVE audit event.
        """
        ...

    def merge(
        self,
        local_state: Dict[str, Any],
        remote_state: Dict[str, Any],
        local_vclock: Dict[str, int],
        remote_vclock: Dict[str, int],
        peer: NodeInfo,
    ) -> Tuple[Dict[str, Any], Dict[str, int]]:
        """
        CRDT merge: combine local and remote graph state.
        Uses vector clock comparison (not timestamps) for conflict detection.
        Concurrent writes are returned as conflicts for human resolution.
        Returns (merged_state, merged_vclock).
        Never raises — returns local state on error.
        """
        ...

    def recall(self, consent_id: str) -> List[str]:
        """
        Retract previously shared data by revoking consent_id.
        Sends RETRACT messages to all peers that received data under this ID.
        Returns list of peer node_ids that were notified.

        INVARIANT: Always updates the local consent record to revoked
        BEFORE attempting to notify peers. Data sovereignty cannot be
        blocked by offline or unresponsive peers.
        """
        ...

    def get_trust_score(self, peer_did: str) -> float:
        """
        Return the current accumulated trust score for a peer.
        Returns 0.0 if peer is unknown.
        """
        ...

    def health(self) -> Dict[str, Any]:
        """
        Return federation health status for onto_status.
        Safe to call at any time. Never raises.
        """
        ...
