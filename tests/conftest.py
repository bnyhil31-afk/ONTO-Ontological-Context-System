"""
tests/conftest.py

Pytest configuration and shared fixtures for the ONTO test suite.

CRYPTO LIBRARY GUARD
--------------------
tests/test_auth.py and tests/test_encryption.py require argon2-cffi
and cryptography. These libraries use C extensions that may not be
available in all environments.

This conftest checks for the ACTUAL sub-modules used by core/auth.py
and core/encryption.py (argon2.low_level and cryptography AESGCM),
not just the top-level package names. If the sub-modules are unavailable,
all tests in those files are automatically skipped before setUp runs.

This approach works regardless of what skip guards (if any) are present
in the individual test files.
"""

import pytest


def pytest_runtest_setup(item):
    """
    Hook called before every individual test.

    For test_auth.py and test_encryption.py, verify that the specific
    sub-modules used by the production code are importable. If not,
    skip the test with a clear reason.

    This is more reliable than class-level decorators or setUp checks
    because it runs in pytest's own setup phase, before any test code.
    """
    filepath = str(item.fspath)

    if "test_auth" in filepath:
        try:
            from argon2.low_level import hash_secret_raw, Type  # noqa: F401
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.skip(
                f"argon2-cffi not fully available ({exc}) — "
                "run: pip install argon2-cffi"
            )

    if "test_encryption" in filepath:
        try:
            from argon2.low_level import hash_secret_raw, Type  # noqa: F401
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.skip(
                f"Required cryptographic library not fully available ({exc}) — "
                "run: pip install cryptography argon2-cffi"
            )
