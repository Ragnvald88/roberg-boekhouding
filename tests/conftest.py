"""Shared test fixtures."""

import pytest
from database import init_db


@pytest.fixture
async def db(tmp_path):
    """Create a fresh test database with full schema + migrations."""
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path
