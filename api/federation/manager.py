"""
api/federation/manager.py

FederationManager — singleton that owns the federation lifecycle.

Analogous to session_manager in core/session.py.
One instance exists per process. Created at module import.
Does not start federation at import — start() is explicit.

Boot integration (main.py, no modification needed):

    from api.federation.manager import federation_manager
    if federation_manager.is_enabled():
        federation_manager.start()

Shutdown:

    federation_manager.stop()

is_enabled() is safe to call at any time — returns False if federation
is disabled or deps are not installed. Never raises.

start() initializes all federation tables, loads or generates the node
identity, creates the appropriate adapter, and starts the server.
Raises ValueError on invalid configuration.
Raises FederationDepsError if required deps are missing.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import threading
from typing import Optional

from api.federation.adapter import FederationAdapter


class FederationManager:
    """
    Singleton that manages the full federation layer lifecycle.

    Thread-safe: start() and stop() acquire the internal lock.
    get_adapter() returns the current adapter or None without locking.
    """

    def __init__(self):
        self._adapter: Optional[FederationAdapter] = None
        self._node_did: Optional[str] = None
        self._lock = threading.Lock()
        self._started = False

    # ------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """
        Return True if federation is configured and deps are available.
        Safe to call at any time — never raises.

        Returns False if:
          - ONTO_FEDERATION_ENABLED is false (or not set)
          - Required deps for the configured stage are not installed
          - Any exception occurs during the check
        """
        try:
            from api.federation import config as _cfg, _GRPCIO_AVAILABLE
            if not _cfg.FEDERATION_ENABLED:
                return False
            # Minimum dep: grpcio (required for all stages)
            if not _GRPCIO_AVAILABLE:
                return False
            # Intranet stage also needs zeroconf
            if _cfg.FEDERATION_STAGE == "intranet":
                from api.federation import _ZEROCONF_AVAILABLE
                if not _ZEROCONF_AVAILABLE:
                    return False
            # P2P stage also needs kademlia
            if _cfg.FEDERATION_STAGE == "p2p":
                from api.federation import _KADEMLIA_AVAILABLE
                if not _KADEMLIA_AVAILABLE:
                    return False
            return True
        except Exception:
            return False

    def is_started(self) -> bool:
        """Return True if federation is currently running."""
        return self._started

    # ------------------------------------------------------------------
    # START
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Initialize all federation tables, load/generate node identity,
        create the correct adapter, and start the federation server.

        Raises:
            FederationDepsError: if required deps are not installed
            ValueError:          if config validation fails

        Idempotent: calling start() when already started is a no-op.
        """
        with self._lock:
            if self._started:
                return
            self._start_locked()

    def _start_locked(self) -> None:
        """Internal start — must be called with self._lock held."""
        from api.federation import (
            require_deps,
            config as _cfg,
        )
        from api.federation import (
            node_identity,
            peer_store,
            consent,
            audit,
        )
        from modules import memory as _memory

        # 1. Validate deps for the configured stage
        require_deps(_cfg.FEDERATION_STAGE)

        # 2. Validate configuration — fail fast with clear errors
        errors = _cfg.validate()
        if errors:
            raise ValueError(
                "Federation configuration invalid:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        # 3. Initialize all federation database tables
        node_identity.initialize()
        peer_store.initialize()
        consent.initialize()
        audit.initialize()

        # 4. Generate or load node identity
        did, private_key = node_identity.generate_or_load(
            _cfg.FEDERATION_KEY_PATH
        )
        self._node_did = did

        # 5. Create the adapter for the configured stage
        if _cfg.FEDERATION_STAGE == "p2p":
            from api.federation.p2p import P2PAdapter
            adapter = P2PAdapter(did, private_key)
        elif _cfg.FEDERATION_STAGE == "internet":
            from api.federation.internet import InternetAdapter
            adapter = InternetAdapter(did, private_key)
        elif _cfg.FEDERATION_STAGE == "intranet":
            from api.federation.intranet import IntranetAdapter
            adapter = IntranetAdapter(did, private_key)
        else:
            from api.federation.local import LocalAdapter
            adapter = LocalAdapter(did, private_key)

        # 6. Start the adapter (HTTP server + optional mDNS)
        adapter.start()
        self._adapter = adapter
        self._started = True

        # 7. Write FEDERATION_STARTED audit event
        try:
            _memory.record(
                event_type="FEDERATION_STARTED",
                notes=(
                    f"Federation started. "
                    f"Stage: {_cfg.FEDERATION_STAGE}. "
                    f"Node: {did}"
                ),
                context={
                    "did": did,
                    "stage": _cfg.FEDERATION_STAGE,
                    "config": _cfg.summary(),
                },
            )
        except Exception:
            pass  # Audit failure must not abort federation startup

    # ------------------------------------------------------------------
    # STOP
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """
        Stop the federation layer cleanly.
        Releases discovery resources and shuts down the HTTP server.
        Idempotent: calling stop() when not started is a no-op.
        """
        with self._lock:
            if not self._started:
                return
            try:
                if self._adapter:
                    self._adapter.stop()
            except Exception:
                pass
            finally:
                self._adapter = None
                self._node_did = None
                self._started = False

        # Write shutdown audit event outside the lock
        from modules import memory as _memory
        try:
            _memory.record(
                event_type="FEDERATION_STOPPED",
                notes="Federation stopped cleanly.",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # ACCESSOR
    # ------------------------------------------------------------------

    def get_adapter(self) -> Optional[FederationAdapter]:
        """
        Return the current FederationAdapter, or None if not started.
        The caller should check for None before using the adapter.

        Pattern:
            adapter = federation_manager.get_adapter()
            if adapter:
                result = adapter.can_share(...)
        """
        return self._adapter

    def get_node_did(self) -> Optional[str]:
        """Return the node's did:key, or None if not started."""
        return self._node_did

    # ------------------------------------------------------------------
    # STATUS SUMMARY (for onto_status MCP resource)
    # ------------------------------------------------------------------

    def status_summary(self) -> dict:
        """
        Return a health summary suitable for inclusion in onto_status.
        Never raises — returns a degraded status dict on error.
        """
        if not self._started or not self._adapter:
            from api.federation import config as _cfg
            return {
                "enabled": _cfg.FEDERATION_ENABLED,
                "started": False,
                "stage":   _cfg.FEDERATION_STAGE,
            }
        try:
            health = self._adapter.health()
            health["node_did"] = self._node_did
            return health
        except Exception:
            return {
                "enabled": True,
                "started": True,
                "error":   "health_unavailable",
            }


# ---------------------------------------------------------------------------
# MODULE-LEVEL SINGLETON
# ---------------------------------------------------------------------------

#: The global FederationManager instance.
#: Used by main.py boot integration and onto_status reporting.
#:
#: Usage:
#:   from api.federation.manager import federation_manager
#:   if federation_manager.is_enabled():
#:       federation_manager.start()
federation_manager = FederationManager()
