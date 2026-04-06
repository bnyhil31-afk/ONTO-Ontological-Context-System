"""
api/federation/__init__.py

ONTO Federation Layer — Phase 3

Optional addon package. Completely separate from the core pipeline,
graph layer, MCP interface, and session management. Imports from core
— core never imports from federation.

Phase 3 required dependencies:
  zeroconf  — mDNS discovery (intranet stage)
  grpcio    — mTLS inter-node communication

Phase 4 dependencies (not required in Phase 3):
  crdts     — advanced CRDT library (Phase 3 uses stdlib implementations)
  kademlia  — internet-scale DHT discovery

To enable federation:
  1. pip install zeroconf grpcio grpcio-tools
  2. Set ONTO_FEDERATION_ENABLED=true

Governing principle: Federation is disabled by default.
Every behavior is opt-in. No data leaves the device without the operator
explicitly enabling it and a user explicitly consenting.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

# ---------------------------------------------------------------------------
# Phase 3 required dependency check
# ---------------------------------------------------------------------------

try:
    import zeroconf as _zeroconf    # type: ignore  # noqa: F401
    _ZEROCONF_AVAILABLE = True
except ImportError:
    _ZEROCONF_AVAILABLE = False

try:
    import grpcio as _grpcio        # type: ignore  # noqa: F401
    _GRPCIO_AVAILABLE = True
except ImportError:
    _GRPCIO_AVAILABLE = False

# Phase 4 — not required in Phase 3 (CRDTs implemented in stdlib)
try:
    import crdts as _crdts          # type: ignore  # noqa: F401
    _CRDTS_AVAILABLE = True
except ImportError:
    _CRDTS_AVAILABLE = False

# Phase 4 — Kademlia DHT (required for p2p stage)
try:
    import kademlia as _kademlia    # type: ignore  # noqa: F401
    _KADEMLIA_AVAILABLE = True
except ImportError:
    _KADEMLIA_AVAILABLE = False

# Phase 3 is available when zeroconf + grpcio are installed
_FEDERATION_DEPS_AVAILABLE = _ZEROCONF_AVAILABLE and _GRPCIO_AVAILABLE


def get_deps_status() -> dict:
    """
    Return the status of each federation dependency.
    Useful for operator diagnostics and onto_status reporting.
    """
    return {
        "zeroconf": _ZEROCONF_AVAILABLE,    # required (Phase 3, intranet stage)
        "grpcio":   _GRPCIO_AVAILABLE,      # required (Phase 3+)
        "crdts":    _CRDTS_AVAILABLE,       # optional (Phase 4)
        "kademlia": _KADEMLIA_AVAILABLE,    # required (p2p stage)
    }


def require_deps(stage: str = "local") -> None:
    """
    Raise FederationDepsError if required deps for the given stage
    are missing.

    local:    requires grpcio (mTLS even for direct connections)
    intranet: requires grpcio + zeroconf
    """
    missing = []

    if not _GRPCIO_AVAILABLE:
        missing.append("grpcio")

    if stage == "intranet" and not _ZEROCONF_AVAILABLE:
        missing.append("zeroconf")

    if stage == "p2p" and not _KADEMLIA_AVAILABLE:
        missing.append("kademlia")

    if missing:
        install = " ".join(missing)
        if "grpcio" in missing:
            install += " grpcio-tools"
        if "kademlia" in missing:
            install = install.strip() + " kademlia>=2.2.2"
        raise FederationDepsError(
            f"Federation stage '{stage}' requires: {', '.join(missing)}.\n"
            f"Run: pip install {install}"
        )


class FederationDepsError(RuntimeError):
    """
    Raised when federation is enabled but required dependencies
    are not installed.
    """
