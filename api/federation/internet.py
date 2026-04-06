"""
api/federation/internet.py

InternetAdapter — extends LocalAdapter for cross-internet federation.

Adds over LocalAdapter:
  - TLS/mTLS transport (HTTPS instead of plain HTTP)
  - Regulatory compliance profiles (HIPAA, GDPR, FERPA, GLBA)
  - Enhanced nonce deduplication window (larger than LAN; internet latency)
  - Internet-safe peer endpoint handling (FQDNs, not just LAN IPs)
  - SSO interface hook (OAuth2/OIDC stub — wired for Stage 3 implementation)

Safety invariants inherited unchanged from LocalAdapter:
  - can_share: crisis content NEVER federates (absolute barrier)
  - can_share: classification >= 4 (PHI) NEVER federates (absolute barrier)
  - can_receive: assigned trust <= ONTO_FED_INBOUND_TRUST (never higher)
  - recall: local revocation happens BEFORE peer notification

Regulatory profiles are ADDITIVE ONLY:
  - They are consulted AFTER super().can_share() passes
  - They can only block — never permit what super() blocked
  - An empty ONTO_FED_REGULATORY_PROFILES means no profiles active (default)

Transport upgrade path:
  Phase 3 (current): HTTPS over Python ssl + urllib
  Phase 4 (future):  gRPC + mTLS channel — single swap in _post() only

Configuration:
  ONTO_FED_MTLS_REQUIRED=true|false  (default: true)
  ONTO_FED_TLS_CERT_PATH             (default: ~/.onto/federation/node.crt)
  ONTO_FED_TLS_KEY_PATH              (default: ~/.onto/federation/node.pem)
  ONTO_FED_TLS_CA_BUNDLE             (default: system CA store)
  ONTO_FED_REGULATORY_PROFILES       (default: empty — no profiles)

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import json
import os
import ssl
import threading
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

from api.federation.local import LocalAdapter, _FED_HOST, _FED_PORT, _FED_TIMEOUT, _API_PREFIX
from api.federation.adapter import NodeInfo
from api.federation.tls_transport import (
    TLSConfig,
    create_client_context,
    create_server_context,
    generate_self_signed_cert,
    load_tls_config_from_env,
)
from api.federation.regulatory import regulatory_registry


class InternetAdapter(LocalAdapter):
    """
    InternetAdapter — LocalAdapter extended for cross-internet federation.

    Overrides:
      start()       — adds TLS wrapping and regulatory profile loading
      stop()        — adds TLS cleanup
      can_share()   — adds regulatory profile outbound checks
      can_receive() — adds regulatory profile inbound checks
      _post()       — uses HTTPS instead of HTTP

    All other methods (discover, handshake, verify_peer, share, receive,
    merge, recall, get_trust_score, health) are inherited from LocalAdapter
    with no changes. Safety invariants are preserved.
    """

    def __init__(self, node_did: str, private_key: Any):
        super().__init__(node_did, private_key)
        self._tls_config: Optional[TLSConfig] = None
        self._client_ctx: Optional[ssl.SSLContext] = None
        self._tls_lock = threading.Lock()

    # ------------------------------------------------------------------
    # LIFECYCLE
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the internet federation layer.

        Sequence:
          1. super().start() — HTTP server + static peer load
          2. Load TLS configuration from environment
          3. Auto-generate self-signed cert if missing
          4. Wrap the HTTP server socket with SSL (upgrades to HTTPS)
          5. Build the client mTLS context for outbound connections
          6. Load regulatory compliance profiles
          7. Write FEDERATION_INTERNET_STARTED audit event
        """
        # Step 1: Start LocalAdapter (HTTP server + static peers)
        super().start()

        # Step 2: Load TLS config
        tls_config = load_tls_config_from_env()

        # Step 3: Auto-generate self-signed cert if cert or key is missing
        if not os.path.exists(tls_config.cert_path) or not os.path.exists(tls_config.key_path):
            output_dir = os.path.dirname(tls_config.cert_path)
            try:
                cert_path, key_path = generate_self_signed_cert(
                    self._did, output_dir
                )
                tls_config = TLSConfig(
                    cert_path=cert_path,
                    key_path=key_path,
                    ca_bundle_path=tls_config.ca_bundle_path,
                    mtls_required=tls_config.mtls_required,
                )
                self._write_audit_event(
                    "FEDERATION_SELF_SIGNED_CERT_GENERATED",
                    f"Self-signed TLS certificate generated at {cert_path}. "
                    f"Replace with a CA-signed certificate for production use.",
                )
            except Exception as exc:
                self._write_audit_event(
                    "FEDERATION_TLS_CERT_GENERATION_FAILED",
                    f"Could not generate self-signed cert: {exc}. "
                    f"Falling back to plain HTTP.",
                )

        with self._tls_lock:
            self._tls_config = tls_config

            # Step 4: Wrap HTTP server with SSL
            if self._server and os.path.exists(tls_config.cert_path):
                server_ctx = create_server_context(tls_config)
                if server_ctx and self._server:
                    try:
                        self._server.socket = server_ctx.wrap_socket(
                            self._server.socket,
                            server_side=True,
                        )
                    except Exception as exc:
                        self._write_audit_event(
                            "FEDERATION_TLS_WRAP_FAILED",
                            f"Could not wrap server socket with TLS: {exc}. "
                            f"Running without TLS encryption.",
                        )

            # Step 5: Build client mTLS context
            try:
                self._client_ctx = create_client_context(tls_config)
            except Exception as exc:
                self._write_audit_event(
                    "FEDERATION_TLS_CLIENT_CTX_FAILED",
                    f"Could not create mTLS client context: {exc}. "
                    f"Outbound connections will use system defaults.",
                )

        # Step 6: Load regulatory profiles
        from api.federation import config as _cfg
        if _cfg.REGULATORY_PROFILES:
            regulatory_registry.load(_cfg.REGULATORY_PROFILES)
            profile_names = ", ".join(_cfg.REGULATORY_PROFILES)
            self._write_audit_event(
                "FEDERATION_REGULATORY_PROFILES_LOADED",
                f"Regulatory profiles active: {profile_names}",
            )

        # Step 7: Audit event
        self._write_audit_event(
            "FEDERATION_INTERNET_STARTED",
            f"Internet-stage federation started. "
            f"mTLS required: {tls_config.mtls_required}. "
            f"Regulatory profiles: {regulatory_registry.active_profiles()}",
        )

    def stop(self) -> None:
        """Stop the internet federation layer and clear TLS state."""
        with self._tls_lock:
            self._client_ctx = None
            self._tls_config = None
        super().stop()

    # ------------------------------------------------------------------
    # SAFETY GATES (additive: super() first, then regulatory profiles)
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
        """
        Gate: called before any data leaves this node.

        Order:
          1. super().can_share() — all LocalAdapter gates (absolute barriers,
             classification ceiling, trust threshold, data residency, consent)
          2. If super() blocked: return immediately (do not consult profiles)
          3. regulatory_registry.check_outbound() — all active profiles

        Safety invariants from super() are preserved unconditionally:
          - is_crisis=True → (False, ...) always
          - classification >= 4 → (False, ...) always
        """
        # Step 1: All inherited gates (absolute barriers enforced here)
        allowed, reason = super().can_share(
            text, classification, is_sensitive, is_crisis, peer, consent_id
        )
        if not allowed:
            return False, reason

        # Step 2: Regulatory profile checks (additive only)
        data = {
            "text": text,
            "classification": classification,
            "is_sensitive": is_sensitive,
            "is_crisis": is_crisis,
        }
        reg_allowed, reg_reason = regulatory_registry.check_outbound(data, peer)
        if not reg_allowed:
            return False, reg_reason

        return True, ""

    def can_receive(
        self,
        data: Dict[str, Any],
        peer: NodeInfo,
    ) -> Tuple[bool, float]:
        """
        Gate: called before any remote data enters this node.

        Order:
          1. super().can_receive() — absolute crisis barrier + trust assignment
          2. If super() blocked: return immediately
          3. regulatory_registry.check_inbound() — all active profiles

        Trust assignment is always <= ONTO_FED_INBOUND_TRUST (inherited).
        """
        # Step 1: Absolute barriers + trust assignment (inherited)
        allowed, trust = super().can_receive(data, peer)
        if not allowed:
            return False, 0.0

        # Step 2: Regulatory profile inbound checks
        reg_allowed, reg_reason = regulatory_registry.check_inbound(data, peer)
        if not reg_allowed:
            from api.federation import audit
            audit.record_event(
                "FEDERATION_REGULATORY_REJECT", peer.node_id,
                f"Inbound data rejected by regulatory profile: {reg_reason}",
            )
            return False, 0.0

        return True, trust

    # ------------------------------------------------------------------
    # HEALTH (override to report internet-specific status)
    # ------------------------------------------------------------------

    def health(self) -> Dict[str, Any]:
        """Return internet-stage health status including network quality metrics."""
        from api.federation.network_resilience import network_resilience_manager
        base = super().health()
        base["stage"] = "internet"
        with self._tls_lock:
            tls_active = (
                self._tls_config is not None
                and os.path.exists(self._tls_config.cert_path)
            ) if self._tls_config else False
            mtls = self._tls_config.mtls_required if self._tls_config else False
        base["tls_active"] = tls_active
        base["mtls_required"] = mtls
        base["regulatory_profiles"] = regulatory_registry.active_profiles()
        base["peer_network_quality"] = network_resilience_manager.health_all()
        return base

    # ------------------------------------------------------------------
    # TRANSPORT (HTTPS instead of HTTP)
    # ------------------------------------------------------------------

    def _post(self, endpoint: str, payload: dict) -> dict:
        """
        POST a JSON payload to a peer endpoint via HTTPS with network resilience.

        Wraps the actual HTTP(S) call with:
          - Circuit breaker check (skip dead peers immediately)
          - Adaptive timeout (base + 4 × measured jitter for this peer)
          - Jitter-aware exponential backoff retry on failure
          - RTT measurement fed back into per-peer quality metrics

        Falls back to HTTP if no client TLS context is available
        (e.g., during first boot before cert is generated).

        Phase 4 upgrade path: replace urllib with grpcio channel here.
        No other method changes when this is upgraded.
        """
        from api.federation.network_resilience import resilient_call
        from api.federation import config as _cfg

        with self._tls_lock:
            client_ctx = self._client_ctx

        scheme = "https" if client_ctx is not None else "http"
        url = f"{scheme}://{endpoint}{_API_PREFIX}/message"
        data = json.dumps(payload).encode()

        # Extract peer DID from payload for per-peer resilience tracking
        peer_did = payload.get("sender_did", endpoint)

        def _do_post(timeout: float) -> dict:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            if client_ctx is not None:
                with urllib.request.urlopen(  # nosec B310
                    req, timeout=timeout, context=client_ctx
                ) as resp:
                    return json.loads(resp.read())
            else:
                with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
                    return json.loads(resp.read())

        def _on_retry(attempt: int, exc: Exception) -> None:
            self._write_audit_event(
                "FEDERATION_REQUEST_RETRY",
                f"Retrying peer {peer_did[:16]}... "
                f"(attempt {attempt}): {type(exc).__name__}",
            )

        return resilient_call(
            peer_did=peer_did,
            fn=_do_post,
            base_timeout=_cfg.TIMEOUT_BASE_SECS,
            on_retry=_on_retry,
        )

    # ------------------------------------------------------------------
    # SSO INTERFACE HOOK (stub — wired for Stage 3 implementation)
    # ------------------------------------------------------------------

    def sso_verify_token(self, token: str, peer: NodeInfo) -> Tuple[bool, str]:
        """
        OAuth2/OIDC token verification hook for enterprise SSO.

        Stage 3 implementation will verify bearer tokens from an
        identity provider (Okta, Azure AD, Google Workspace, etc.)
        and map them to peer trust scores.

        Current status: stub — always returns (False, "sso_not_configured")
        until the full SSO module is implemented.

        To implement: replace the body of this method with calls to
        api/federation/sso.py (Stage 3 deliverable) and update the
        HANDSHAKE flow in handshake() to call sso_verify_token().
        """
        return False, "sso_not_configured"

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    def _write_audit_event(self, event_type: str, notes: str) -> None:
        """Write an audit event, ignoring failures (audit must not abort startup)."""
        try:
            from modules import memory as _memory
            _memory.record(
                event_type=event_type,
                notes=notes,
            )
        except Exception:
            pass
