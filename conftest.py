"""
conftest.py

Shared test setup for the entire ONTO test suite.
pytest reads this file automatically before running any tests.

Plain English: This file sets up the shared tools
every test uses — so each test doesn't have to repeat itself.
It also makes sure tests never touch the real database.
"""

import os
import sys
import tempfile
import shutil
import pytest

# Add project root to path so all modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def isolated_memory(tmp_path):
    """
    Automatically runs before and after every test.

    Gives each test its own private database.
    Real data is never touched. Ever.
    After each test the temporary database is deleted.

    Plain English: Every test gets a clean slate.
    Nothing from one test can affect another.
    """
    import modules.memory as memory_module
    import modules.contextualize as ctx_module

    # Save original state
    original_db = memory_module.DB_PATH
    original_field = list(ctx_module._field)

    # Point to isolated test database
    test_db = str(tmp_path / "test_memory.db")
    memory_module.DB_PATH = test_db
    memory_module.initialize()

    # Clear the context field
    ctx_module._field = []

    yield  # Run the test

    # Restore original state
    memory_module.DB_PATH = original_db
    ctx_module._field = original_field
