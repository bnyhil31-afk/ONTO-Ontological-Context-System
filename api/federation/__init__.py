"""
api/federation/__init__.py

ONTO Federation Layer — Phase 3

Optional addon package. This package is completely separate from the core
pipeline, graph layer, MCP interface, and session management. It imports
from core — core never imports from federation.

If federation dependencies are not installed, this package loads gracefully
as a no-op. Nothing in the existing system is affected.

To enable federation:
    1. pip install zeroconf crdts grpcio grpcio-tools
    2. Set ONTO_FEDERATION_ENABLED=true in your environment

Governing principle: Federation is disabled by default.
Every behavior is opt-in. No data leaves the device without the operator
explicitly enabling it and a user explicitly consenting.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

# ---------------------------------------------------------------------------
# Dependency check — graceful fallback if federation deps not installed
# ---------------------------------------------------------------------------

try:
    import zeroconf as _zeroconf    # type: ignore  # noqa: F401
    import crdts as _crdts          # type: ignore  # noqa: F401
    import grpcio as _grpcio        # type: ignore  # noqa: F401
    _FEDERATION_DEPS_AVAILABLE = True
except ImportError:
    _FEDERATION_DEPS_AVAILABLE = False


def get_deps_status() -> dict:
    """
    Return the status of each federation dependency.
    Useful for operator diagnostics and onto_status reporting.
    """
    status = {}
    for pkg in ("zeroconf", "crdts", "grpcio"):
        try:
            __import__(pkg)
            status[pkg] = True
        except ImportError:
            status[pkg] = False
    return status


def require_deps() -> None:
    """
    Raise FederationDepsError if any required dependency is missing.
    Called by FederationManager.start() before attempting to initialize.
    """
    missing = [
        pkg for pkg, ok in get_deps_status().items() if not ok
    ]
    if missing:
        raise FederationDepsError(
            f"Federation requires: {', '.join(missing)}.\n"
            f"Run: pip install {' '.join(missing)} grpcio-tools"
        )


class FederationDepsError(RuntimeError):
    """
    Raised when federation is enabled but required dependencies
    are not installed.
    """
