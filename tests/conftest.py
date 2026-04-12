"""Shared test fixtures."""

import os
import tempfile

# Redirect the per-user default DB dir to a throw-away temp location BEFORE
# importing database — otherwise `database.py` would create
# ~/Library/Application Support/Boekhouding/data on every test run.
os.environ.setdefault(
    "BOEKHOUDING_DB_DIR",
    tempfile.mkdtemp(prefix="boekhouding_test_default_"),
)

import pytest
from database import init_db


@pytest.fixture
async def db(tmp_path):
    """Create a fresh test database with full schema + migrations."""
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path
