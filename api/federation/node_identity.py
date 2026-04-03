"""
api/federation/node_identity.py

Node identity using W3C Decentralized Identifiers (did:key method).

Each ONTO node has a unique cryptographic identity:
  - Ed25519 keypair generated at first federation startup
  - Public key encoded as did:key:z6Mk... (W3C DID, multibase base58btc)
  - Private key stored in a separate file at ONTO_FED_KEY_PATH
  - did:key (public key only) stored in federation_node_config table

The private key NEVER lives in SQLite.
Compromise of the database does not expose the signing key.

did:key format:
  did:key:z<base58btc(multicodec_prefix + ed25519_public_key_bytes)>
  Multicodec prefix for Ed25519 public key: 0xed 0x01 (varint)
  The 'z' character prefix indicates base58btc multibase encoding.

Key file format (ONTO-FEDERATION-KEY-V1):
  Line 1: "ONTO-FEDERATION-KEY-V1"
  Line 2: base64url-encoded raw 32-byte Ed25519 private key seed

  File permissions: 0o600 (owner read/write only). This mirrors the SSH
  known_hosts model. Full passphrase-based encryption is a Phase 4 upgrade.
  Operators in high-security environments should apply additional OS-level
  protections (encrypted filesystem, hardware key storage).

Rule 1.09A: Code, tests, and documentation must always agree.
"""

import base64
import os
import sqlite3
from typing import Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from modules import memory as _memory

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

_KEY_FILE_HEADER = "ONTO-FEDERATION-KEY-V1"

# Ed25519 multicodec prefix (varint encoded per multicodec spec)
_ED25519_MULTICODEC_PREFIX = bytes([0xED, 0x01])

# Base58btc alphabet (Bitcoin/IPFS standard)
_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Table name — federation-specific; never touches graph.py
_TABLE = "federation_node_config"


# ---------------------------------------------------------------------------
# DATABASE HELPERS
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    """Open a read/write connection to the ONTO database."""
    conn = sqlite3.connect(
        _memory.DB_PATH, check_same_thread=False, timeout=10
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize() -> None:
    """
    Create the federation_node_config table if it does not exist.
    Idempotent — safe to call on every federation start.
    Does not modify any existing table.
    """
    conn = _get_conn()
    try:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _config_get(key: str) -> Optional[str]:
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT value FROM {_TABLE} WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def _config_set(key: str, value: str) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO {_TABLE} (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# BASE58BTC ENCODING
# ---------------------------------------------------------------------------

def _b58_encode(data: bytes) -> str:
    """
    Encode bytes as base58btc (Bitcoin/IPFS alphabet).
    Used for did:key multibase encoding ('z' prefix = base58btc).
    """
    leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    n = int.from_bytes(data, "big")
    result = []
    while n > 0:
        n, remainder = divmod(n, 58)
        result.append(_B58_ALPHABET[remainder : remainder + 1])
    encoded = b"".join(reversed(result))
    return (b"1" * leading_zeros + encoded).decode("ascii")


def _b58_decode(encoded: str) -> bytes:
    """
    Decode a base58btc string to bytes.
    Raises ValueError on invalid input.
    """
    alphabet_map = {c: i for i, c in enumerate(_B58_ALPHABET)}
    n = 0
    for char in encoded.encode("ascii"):
        if char not in alphabet_map:
            raise ValueError(
                f"Invalid base58btc character: {chr(char)!r}"
            )
        n = n * 58 + alphabet_map[char]
    leading_zeros = len(encoded) - len(encoded.lstrip("1"))
    result = n.to_bytes(max(1, (n.bit_length() + 7) // 8), "big")
    return b"\x00" * leading_zeros + result


# ---------------------------------------------------------------------------
# DID:KEY ENCODING / DECODING
# ---------------------------------------------------------------------------

def public_key_bytes_to_did(pubkey_bytes: bytes) -> str:
    """
    Encode a 32-byte Ed25519 public key as a did:key DID.

    did:key:z<base58btc(0xed 0x01 + pubkey_bytes)>
    """
    prefixed = _ED25519_MULTICODEC_PREFIX + pubkey_bytes
    return "did:key:z" + _b58_encode(prefixed)


def did_to_public_key_bytes(did: str) -> bytes:
    """
    Decode a did:key DID to raw 32-byte Ed25519 public key bytes.
    Raises ValueError if the DID is malformed or not an Ed25519 key.
    """
    if not did.startswith("did:key:z"):
        raise ValueError(
            f"Not a valid did:key (must start with 'did:key:z'): {did!r}"
        )
    encoded = did[len("did:key:z") :]
    decoded = _b58_decode(encoded)
    if not decoded.startswith(_ED25519_MULTICODEC_PREFIX):
        raise ValueError(
            f"DID is not an Ed25519 key (wrong multicodec prefix): {did!r}"
        )
    return decoded[len(_ED25519_MULTICODEC_PREFIX) :]


# ---------------------------------------------------------------------------
# KEY FILE I/O
# ---------------------------------------------------------------------------

def _write_key_file(path: str, private_seed: bytes) -> None:
    """
    Write the private key seed to the key file.
    Creates parent directories if needed.
    Sets file permissions to 0o600 (owner read/write only).
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    encoded = base64.urlsafe_b64encode(private_seed).decode("ascii")
    content = f"{_KEY_FILE_HEADER}\n{encoded}\n"
    with open(path, "w") as f:
        f.write(content)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows does not support Unix file permissions


def _read_key_file(path: str) -> bytes:
    """
    Read the private key seed from the key file.
    Raises ValueError if the file format is invalid.
    Raises FileNotFoundError if the file does not exist.
    """
    with open(path, "r") as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]

    if len(lines) < 2 or lines[0] != _KEY_FILE_HEADER:
        raise ValueError(
            f"Invalid key file format at {path!r}. "
            f"Expected header: '{_KEY_FILE_HEADER}'"
        )

    try:
        seed = base64.urlsafe_b64decode(lines[1])
    except Exception as exc:
        raise ValueError(
            f"Cannot decode key data in {path!r}: {exc}"
        ) from exc

    if len(seed) != 32:
        raise ValueError(
            f"Key file at {path!r} contains {len(seed)} bytes; "
            f"expected 32 (Ed25519 seed)."
        )

    return seed


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def generate_or_load(key_path: str) -> Tuple[str, Ed25519PrivateKey]:
    """
    Load the node identity from the key file if it exists, otherwise
    generate a new Ed25519 keypair and persist it.

    Returns (did_key_str, private_key_object).

    The did:key string is also stored in the federation_node_config table.
    Writes a FEDERATION_IDENTITY_CREATED audit event on first generation.
    """
    expanded = os.path.expanduser(key_path)

    if os.path.exists(expanded):
        # Load existing key
        seed = _read_key_file(expanded)
        private_key = Ed25519PrivateKey.from_private_bytes(seed)
        pubkey_bytes = private_key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        did = public_key_bytes_to_did(pubkey_bytes)

        # Sync DID to database (idempotent)
        _config_set("did_key", did)
        return did, private_key

    # Generate a new keypair
    private_key = Ed25519PrivateKey.generate()
    seed = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    pubkey_bytes = private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    did = public_key_bytes_to_did(pubkey_bytes)

    _write_key_file(expanded, seed)
    _config_set("did_key", did)

    try:
        _memory.record(
            event_type="FEDERATION_IDENTITY_CREATED",
            notes=f"Node identity generated: {did}",
            context={"did_key": did, "key_path": expanded},
        )
    except Exception:
        pass

    return did, private_key


def get_did() -> Optional[str]:
    """
    Return the node's did:key from the database.
    Returns None if federation has not been initialized.
    """
    return _config_get("did_key")


def sign(private_key: Ed25519PrivateKey, data: bytes) -> bytes:
    """
    Sign data with the node's Ed25519 private key.
    Returns the 64-byte signature.
    """
    return private_key.sign(data)


def verify(did: str, data: bytes, signature: bytes) -> bool:
    """
    Verify a signature against a did:key public key.

    Returns True if the signature is valid.
    Returns False if invalid — never raises on verification failure.
    This matches the security principle: invalid signatures are not errors,
    they are security events that should be logged by the caller.
    """
    try:
        pubkey_bytes = did_to_public_key_bytes(did)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
        public_key = Ed25519PublicKey.from_public_bytes(pubkey_bytes)
        public_key.verify(signature, data)
        return True
    except Exception:
        return False


def sign_json(
    private_key: Ed25519PrivateKey,
    payload: dict,
) -> bytes:
    """
    Sign a dict payload using JCS (JSON Canonicalization Scheme, RFC 8785).
    Returns the 64-byte Ed25519 signature over the canonical JSON bytes.

    JCS produces a deterministic byte representation:
      - Keys sorted lexicographically
      - No insignificant whitespace
      - Unicode characters preserved (not escaped unless required)

    This is the standard for capability manifest signing.
    """
    canonical = _jcs_encode(payload)
    return sign(private_key, canonical)


def verify_json(
    did: str,
    payload: dict,
    signature: bytes,
) -> bool:
    """
    Verify a JCS-signed payload against a did:key.
    Returns True if valid, False otherwise.
    """
    canonical = _jcs_encode(payload)
    return verify(did, canonical, signature)


# ---------------------------------------------------------------------------
# JCS — JSON Canonicalization Scheme (RFC 8785)
# Minimal stdlib implementation — no external dependency.
# ---------------------------------------------------------------------------

import json as _json


def _jcs_encode(obj: object) -> bytes:
    """
    Produce a JCS-canonical UTF-8 byte representation of a JSON-serializable
    object. Keys are sorted lexicographically at every level.
    """
    return _json.dumps(
        obj,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
