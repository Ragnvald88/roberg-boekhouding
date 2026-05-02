import pytest
import aiosqlite
from pathlib import Path

import database


@pytest.fixture
async def fresh_db(tmp_path):
    """Fresh DB with all migrations applied."""
    db = tmp_path / 'test.sqlite3'
    await database.init_db(db)
    return db


@pytest.mark.asyncio
async def test_klant_recurring_patterns_table_exists(fresh_db):
    async with aiosqlite.connect(fresh_db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='klant_recurring_patterns'"
        )
        row = await cur.fetchone()
    assert row is not None, "klant_recurring_patterns table missing"


@pytest.mark.asyncio
async def test_klant_recurring_patterns_has_required_columns(fresh_db):
    async with aiosqlite.connect(fresh_db) as conn:
        cur = await conn.execute(
            "PRAGMA table_info(klant_recurring_patterns)"
        )
        cols = {row[1] for row in await cur.fetchall()}
    expected = {'id', 'klant_id', 'weekdays', 'start_minuten',
                'eind_minuten', 'code', 'activiteit',
                'valid_from', 'valid_until', 'actief'}
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


@pytest.mark.asyncio
async def test_klant_recurring_patterns_cascade_on_klant_delete(fresh_db):
    async with aiosqlite.connect(fresh_db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        cur = await conn.execute(
            "INSERT INTO klanten (naam, tarief_uur) VALUES ('Test', 80) RETURNING id"
        )
        klant_id = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO klant_recurring_patterns "
            "(klant_id, weekdays, start_minuten, eind_minuten) "
            "VALUES (?, '1,3', 480, 1020)",
            (klant_id,),
        )
        await conn.execute("DELETE FROM klanten WHERE id = ?", (klant_id,))
        await conn.commit()
        cur = await conn.execute(
            "SELECT COUNT(*) FROM klant_recurring_patterns"
        )
        count = (await cur.fetchone())[0]
    assert count == 0, "Cascade delete failed"


@pytest.mark.asyncio
async def test_klant_recurring_patterns_check_minuten_range(fresh_db):
    async with aiosqlite.connect(fresh_db) as conn:
        await conn.execute(
            "INSERT INTO klanten (naam, tarief_uur) VALUES ('K', 80)"
        )
        # eind <= start should fail
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_recurring_patterns "
                "(klant_id, weekdays, start_minuten, eind_minuten) "
                "VALUES (1, '1', 600, 600)"
            )
            await conn.commit()
