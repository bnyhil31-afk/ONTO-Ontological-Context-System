"""
core/secrets_backends/vault.py

HashiCorp Vault secrets backend for ONTO.

Reads secrets from a Vault KV v2 mount using the hvac client library.
hvac is an optional dependency — install it with:
    pip install hvac

Required environment variables:
  ONTO_VAULT_ADDR      — Vault server address (e.g. https://vault.example.com)
  ONTO_VAULT_TOKEN     — Vault token (or use ONTO_VAULT_ROLE_ID + ONTO_VAULT_SECRET_ID
                         for AppRole auth — see TODO below)
  ONTO_VAULT_MOUNT     — KV v2 mount path (default: "secret")
  ONTO_VAULT_PATH      — KV v2 path to the ONTO secrets (default: "onto/config")

Expected secret structure at ONTO_VAULT_PATH:
  {
    "db_encryption_key": "<32-byte hex>",
    "auth_passphrase_hash": "<argon2 hash>"
  }

Usage (via core/config.py):
  from core.secrets_backends.vault import get_secret
  value = get_secret("db_encryption_key")
"""

import os
from typing import Optional


def get_secret(key: str) -> Optional[str]:
    """
    Fetch a single secret value from HashiCorp Vault KV v2.

    Arguments:
        key: The field name within the Vault secret (e.g. "db_encryption_key").

    Returns:
        The secret value as a string, or None if not found.

    Raises:
        ImportError: If hvac is not installed.
        RuntimeError: If Vault configuration is missing or the fetch fails.
    """
    try:
        import hvac
    except ImportError:
        raise ImportError(
            "The 'hvac' package is required for the Vault secrets backend. "
            "Install it with: pip install hvac"
        )

    vault_addr = os.environ.get("ONTO_VAULT_ADDR")
    vault_token = os.environ.get("ONTO_VAULT_TOKEN")
    vault_mount = os.environ.get("ONTO_VAULT_MOUNT", "secret")
    vault_path = os.environ.get("ONTO_VAULT_PATH", "onto/config")

    if not vault_addr:
        raise RuntimeError(
            "ONTO_VAULT_ADDR is required when ONTO_SECRETS_BACKEND=vault."
        )
    if not vault_token:
        raise RuntimeError(
            "ONTO_VAULT_TOKEN is required when ONTO_SECRETS_BACKEND=vault. "
            "AppRole auth (ONTO_VAULT_ROLE_ID + ONTO_VAULT_SECRET_ID) is planned "
            "for a future release."
        )

    client = hvac.Client(url=vault_addr, token=vault_token)
    if not client.is_authenticated():
        raise RuntimeError(
            "Vault authentication failed. Check ONTO_VAULT_TOKEN and ONTO_VAULT_ADDR."
        )

    try:
        response = client.secrets.kv.v2.read_secret_version(
            path=vault_path,
            mount_point=vault_mount,
        )
        secret_data: dict = response["data"]["data"]
        return secret_data.get(key)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to fetch secret '{key}' from Vault path "
            f"'{vault_mount}/{vault_path}': {exc}"
        ) from exc
