"""
api/federation/intranet.py

IntranetAdapter — extends LocalAdapter with mDNS peer discovery.

Uses python-zeroconf to advertise this node and discover peers on
the local network. Zero-configuration: operators do not need to
specify peer endpoints manually when using the intranet stage.

Service type: _onto._tcp.local.
Service name: <node_did_fragment>._onto._tcp.local.

Discovery is additive: mDNS-discovered peers are merged with
any static peers configured via ONTO_FED_PEERS. Static peers
are always preferred when there is a conflict on the same DID.

mDNS privacy note (FEDERATION-SPEC-001 §6.3):
    mDNS broadcasts this node's presence to ALL devices on the LAN.
    Every device on the network can detect that an ONTO node is running.
    Operators in adversarial LAN environments should use stage=local
    with explicitly configured peers instead.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import socket
import threading
import time
from typing import Any, Dict, List, Optional

from api.federation.local import LocalAdapter, _FED_PORT
from api.federation.adapter import NodeInfo

_MDNS_SERVICE_TYPE = "_onto._tcp.local."
_MDNS_PROPS_VERSION_KEY = b"version"
_MDNS_PROPS_DID_KEY = b"did"
_MDNS_PROPS_SPEC_KEY = b"spec"


def _get_local_ip() -> str:
    """
    Determine the local LAN IP address for mDNS advertisement.
    Falls back to 127.0.0.1 if detection fails.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class _ServiceListener:
    """
    Handles mDNS service add/remove events.
    Updates the adapter's peer registry on network changes.
    """

    def __init__(self, adapter: "IntranetAdapter"):
        self._adapter = adapter

    def add_service(
        self, zc: Any, service_type: str, name: str
    ) -> None:
        try:
            info = zc.get_service_info(service_type, name)
            if info:
                self._adapter._on_peer_discovered(info)
        except Exception:
            pass

    def remove_service(
        self, zc: Any, service_type: str, name: str
    ) -> None:
        self._adapter._on_peer_removed(name)

    def update_service(
        self, zc: Any, service_type: str, name: str
    ) -> None:
        # Treat updates as re-add
        self.add_service(zc, service_type, name)


class IntranetAdapter(LocalAdapter):
    """
    IntranetAdapter adds mDNS peer discovery to LocalAdapter.

    Start sequence:
        1. super().start()  — HTTP server + static peer load
        2. _start_mdns()    — register service + start browser

    Stop sequence:
        1. _stop_mdns()     — unregister + close Zeroconf
        2. super().stop()   — shutdown HTTP server

    If zeroconf is not installed, falls back to LocalAdapter behavior
    (static peers only) with a clear log message — never crashes.
    """

    def __init__(self, node_did: str, private_key: Any):
        super().__init__(node_did, private_key)
        self._zeroconf: Optional[Any] = None
        self._browser: Optional[Any] = None
        self._service_info: Optional[Any] = None
        self._local_ip = _get_local_ip()

    # ------------------------------------------------------------------
    # LIFECYCLE
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start HTTP server then mDNS advertisement and discovery."""
        super().start()
        self._start_mdns()

    def stop(self) -> None:
        """Stop mDNS then HTTP server."""
        self._stop_mdns()
        super().stop()

    def _start_mdns(self) -> None:
        """
        Register this node on mDNS and start browsing for peers.
        Gracefully does nothing if zeroconf is not installed.
        """
        try:
            from zeroconf import Zeroconf, ServiceInfo, ServiceBrowser

            # Build service name from first 16 chars of DID for readability
            did_fragment = self._did.split(":")[-1][:16]
            service_name = f"{did_fragment}.{_MDNS_SERVICE_TYPE}"

            # Service properties advertised to peers
            props = {
                _MDNS_PROPS_DID_KEY:      self._did.encode(),
                _MDNS_PROPS_VERSION_KEY:  b"1.0.0",
                _MDNS_PROPS_SPEC_KEY:     b"FEDERATION-SPEC-001-v1.1",
            }

            try:
                addr_bytes = socket.inet_aton(self._local_ip)
            except OSError:
                addr_bytes = socket.inet_aton("127.0.0.1")

            self._service_info = ServiceInfo(
                _MDNS_SERVICE_TYPE,
                service_name,
                addresses=[addr_bytes],
                port=_FED_PORT,
                properties=props,
                server=f"{socket.gethostname()}.local.",
            )

            self._zeroconf = Zeroconf()
            self._zeroconf.register_service(self._service_info)

            listener = _ServiceListener(self)
            self._browser = ServiceBrowser(
                self._zeroconf, _MDNS_SERVICE_TYPE, listener
            )

            from api.federation import audit
            audit.record_event(
                "FEDERATION_MDNS_STARTED", self._did,
                f"mDNS advertised on {self._local_ip}:{_FED_PORT}",
            )

        except ImportError:
            # zeroconf not installed — fall back to static peers only
            from api.federation import audit
            audit.record_event(
                "FEDERATION_MDNS_UNAVAILABLE", self._did,
                "zeroconf not installed; using static peers only. "
                "Run: pip install zeroconf",
            )

        except Exception as exc:
            from api.federation import audit
            audit.record_event(
                "FEDERATION_MDNS_ERROR", self._did,
                f"mDNS startup failed: {exc}",
            )

    def _stop_mdns(self) -> None:
        """Unregister service and close Zeroconf cleanly."""
        try:
            if self._zeroconf and self._service_info:
                self._zeroconf.unregister_service(self._service_info)
                self._zeroconf.close()
        except Exception:
            pass
        finally:
            self._zeroconf = None
            self._browser = None
            self._service_info = None

    # ------------------------------------------------------------------
    # DISCOVERY
    # ------------------------------------------------------------------

    def discover(self) -> List[NodeInfo]:
        """
        Return all known peers: mDNS-discovered + static.
        mDNS peers are populated asynchronously as they are found.
        Static peers from ONTO_FED_PEERS are always included.
        """
        # Static peers come from super()
        static = super().discover()
        static_dids = {p.node_id for p in static}

        # mDNS peers: any peers not in the static list
        with self._lock:
            mdns_only = [
                p for did, p in self._peers.items()
                if did not in static_dids and p.federation_stage == "intranet"
            ]

        return static + mdns_only

    # ------------------------------------------------------------------
    # mDNS PEER EVENTS (called by _ServiceListener)
    # ------------------------------------------------------------------

    def _on_peer_discovered(self, info: Any) -> None:
        """
        Called when a new ONTO node is found on the LAN.
        Extracts the peer's DID and endpoint, stores in peer registry.
        Does NOT automatically handshake — operator controls connections.
        """
        try:
            props = info.properties or {}

            # Extract DID from service properties
            raw_did = props.get(_MDNS_PROPS_DID_KEY, b"")
            peer_did = (
                raw_did.decode("utf-8")
                if isinstance(raw_did, bytes) else str(raw_did)
            )
            if not peer_did.startswith("did:key:"):
                return

            # Skip ourselves
            if peer_did == self._did:
                return

            # Build endpoint from mDNS address + port
            if not info.addresses:
                return
            addr = socket.inet_ntoa(info.addresses[0])
            port = info.port
            endpoint = f"{addr}:{port}"

            with self._lock:
                if peer_did not in self._peers:
                    self._peers[peer_did] = NodeInfo(
                        node_id=peer_did,
                        endpoint=endpoint,
                        trust_score=0.0,
                        capabilities={},
                        data_residency="",
                        last_seen=time.time(),
                        cert_hash="",
                        federation_stage="intranet",
                    )

            from api.federation import audit
            audit.record_event(
                "FEDERATION_PEER_DISCOVERED", peer_did,
                f"mDNS: peer found at {endpoint}",
            )

        except Exception:
            pass  # Never crash on mDNS events

    def _on_peer_removed(self, service_name: str) -> None:
        """
        Called when an ONTO node disappears from the LAN.
        Marks the peer as last_seen but does not remove them —
        they may reconnect. The operator controls permanent removal.
        """
        try:
            # service_name format: "<did_fragment>._onto._tcp.local."
            # We find the matching peer by service name fragment
            fragment = service_name.split(".")[0]
            with self._lock:
                for did, peer in self._peers.items():
                    if did.split(":")[-1][:16] == fragment:
                        peer.last_seen = time.time()
                        break
        except Exception:
            pass

    # ------------------------------------------------------------------
    # HEALTH (extends LocalAdapter)
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        """Return intranet-stage health including mDNS status."""
        base = super().health()
        base["stage"] = "intranet"
        base["mdns_active"] = self._zeroconf is not None
        base["local_ip"] = self._local_ip
        return base
