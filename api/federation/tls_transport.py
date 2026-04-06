"""
api/federation/tls_transport.py

TLS/mTLS transport helpers for internet-stage federation.

Provides server and client SSL contexts for the internet and p2p federation
stages. Phase 3 (local/intranet) uses plain HTTP. Phase 4+ (internet/p2p)
uses HTTPS with optional mutual TLS (mTLS) for node-to-node authentication.

When ONTO_FED_MTLS_REQUIRED=true (default), both sides present certificates:
  - Client verifies server cert (standard TLS)
  - Server verifies client cert (mutual auth — the 'mutual' in mTLS)

When ONTO_FED_MTLS_REQUIRED=false, TLS is used for encryption only — no
mutual cert verification. Useful during bootstrapping when a peer's cert
is not yet known, but NOT recommended for production federation.

Self-signed cert auto-generation:
  If ONTO_FED_TLS_CERT_PATH does not exist at startup, InternetAdapter
  calls generate_self_signed_cert() to create a cert bound to the node's
  did:key. This cert is added to peer_store on first handshake (TOFU model).
  An audit event is written so the operator knows a self-signed cert is in use.

Certificate pinning (TOFU) remains in peer_store.py — this module is
transport-only. It has no awareness of peer trust or safety logic.

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import datetime
import ipaddress
import os
import ssl
import tempfile
from dataclasses import dataclass, field
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# TLS CONFIGURATION
# ---------------------------------------------------------------------------

@dataclass
class TLSConfig:
    """
    Holds all paths and flags needed to create TLS/mTLS SSL contexts.

    All paths default to values from the environment, but the caller
    (InternetAdapter) may override them.
    """
    cert_path: str
    key_path: str
    ca_bundle_path: str = ""          # empty = use system CA store
    mtls_required: bool = True        # default: mutual auth required


def load_tls_config_from_env() -> TLSConfig:
    """
    Build a TLSConfig from the current federation environment variables.
    Called by InternetAdapter.start().
    """
    from api.federation import config as _cfg
    return TLSConfig(
        cert_path=_cfg.TLS_CERT_PATH,
        key_path=_cfg.TLS_KEY_PATH,
        ca_bundle_path=_cfg.TLS_CA_BUNDLE,
        mtls_required=_cfg.MTLS_REQUIRED,
    )


# ---------------------------------------------------------------------------
# SERVER CONTEXT
# ---------------------------------------------------------------------------

def create_server_context(tls_config: TLSConfig) -> Optional[ssl.SSLContext]:
    """
    Create an ssl.SSLContext for the federation HTTP server.

    Returns None if the cert or key file does not exist — caller should
    log a warning and fall back to plain HTTP in that case.

    mTLS model (mtls_required=True):
        - Server presents its certificate to clients
        - Server requests and verifies the client's certificate
        - ssl.CERT_REQUIRED on the server side

    TLS-only model (mtls_required=False):
        - Server presents its certificate to clients
        - Client certs are not verified (ssl.CERT_NONE on server)
        - Encryption is still enforced; only mutual auth is relaxed
    """
    if not os.path.exists(tls_config.cert_path):
        return None
    if not os.path.exists(tls_config.key_path):
        return None

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tls_config.cert_path, tls_config.key_path)

    if tls_config.mtls_required:
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(
            cafile=tls_config.ca_bundle_path if tls_config.ca_bundle_path else None,
            capath=None,
        )
    else:
        ctx.verify_mode = ssl.CERT_NONE

    # Enforce modern TLS only
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    return ctx


# ---------------------------------------------------------------------------
# CLIENT CONTEXT
# ---------------------------------------------------------------------------

def create_client_context(tls_config: TLSConfig) -> ssl.SSLContext:
    """
    Create an ssl.SSLContext for outbound HTTPS connections to peers.

    mTLS model (mtls_required=True):
        - Client presents its own certificate to the server
        - Client verifies the server's certificate
        - ssl.CERT_REQUIRED on the client side

    TLS-only model (mtls_required=False):
        - Client does NOT present a certificate
        - Client verifies the server's certificate (encryption enforced)

    In both cases, ONTO's TOFU certificate pinning (peer_store.py) adds a
    second layer of verification — the pinned cert hash is checked separately
    from the SSL handshake.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    if tls_config.mtls_required and os.path.exists(tls_config.cert_path):
        ctx.load_cert_chain(tls_config.cert_path, tls_config.key_path)

    if tls_config.ca_bundle_path and os.path.exists(tls_config.ca_bundle_path):
        ctx.load_verify_locations(tls_config.ca_bundle_path)
    else:
        ctx.load_default_certs()

    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True

    return ctx


# ---------------------------------------------------------------------------
# SELF-SIGNED CERTIFICATE GENERATION
# ---------------------------------------------------------------------------

def generate_self_signed_cert(
    node_did: str,
    output_dir: str,
) -> Tuple[str, str]:
    """
    Generate a self-signed X.509 certificate for a federation node.

    The certificate is tied to the node's did:key identity:
      - CN (Common Name) = short fragment of did:key
      - SubjectAltName DNS = "onto.local" (generic ONTO federation name)
      - SubjectAltName URI = full did:key identifier

    Certificate properties:
      - 2048-bit RSA key (compatible with all grpcio/ssl versions)
      - 365-day validity (ONTO_FED_CERT_LIFETIME_DAYS does not apply here;
        this cert is for TLS transport identity, not message signing)
      - Self-signed (not trusted by CAs — TOFU model provides trust)

    Returns (cert_path, key_path).

    Caller (InternetAdapter.start()) writes an audit event:
        FEDERATION_SELF_SIGNED_CERT_GENERATED
    so the operator knows a self-signed cert is in use and can replace it
    with a CA-signed cert at any time by updating the env vars.

    Raises RuntimeError if the cryptography library is not installed.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as exc:
        raise RuntimeError(
            "Self-signed cert generation requires the 'cryptography' package. "
            "Run: pip install cryptography"
        ) from exc

    os.makedirs(output_dir, exist_ok=True)

    # Generate RSA key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # Build certificate subject/issuer
    did_fragment = node_did.split(":")[-1][:16] if ":" in node_did else node_did[:16]
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"onto-{did_fragment}"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ONTO Federation Node"),
    ])

    # Certificate validity
    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("onto.local"),
                x509.UniformResourceIdentifier(node_did),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    # Write cert
    cert_path = os.path.join(output_dir, "node.crt")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    os.chmod(cert_path, 0o644)

    # Write private key (owner read/write only)
    key_path = os.path.join(output_dir, "node.pem")
    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    os.chmod(key_path, 0o600)

    return cert_path, key_path


# ---------------------------------------------------------------------------
# UTILITY: extract cert fingerprint for TOFU
# ---------------------------------------------------------------------------

def cert_fingerprint_from_file(cert_path: str) -> str:
    """
    Return the SHA-256 fingerprint of a PEM certificate file.
    Used to pre-populate peer_store when we generate our own cert,
    so the peer can verify our identity on first contact.

    Returns empty string if the file is missing or unreadable.
    """
    try:
        import hashlib
        with open(cert_path, "rb") as f:
            pem_bytes = f.read()
        return hashlib.sha256(pem_bytes).hexdigest()
    except Exception:
        return ""
