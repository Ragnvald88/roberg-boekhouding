"""Schema tests for klant_aliases (migration 33)."""

import pytest
import aiosqlite
from database import add_klant, get_db_ctx


@pytest.fixture
async def db_with_klanten(db):
    k1 = await add_klant(db, naam='Klant Alpha', tarief_uur=100.0)
    k2 = await add_klant(db, naam='Klant Beta', tarief_uur=100.0)
    return db, k1, k2


async def test_klant_aliases_table_exists(db):
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='klant_aliases'")
        row = await cur.fetchone()
    assert row is not None


async def test_unique_type_pattern(db_with_klanten):
    db, k1, k2 = db_with_klanten
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
            (k1,))
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
                (k2,))


async def test_unique_is_case_insensitive(db_with_klanten):
    db, k1, k2 = db_with_klanten
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
            (k1,))
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'foo bv')",
                (k2,))


async def test_pattern_min_length_3(db_with_klanten):
    db, k1, _ = db_with_klanten
    async with get_db_ctx(db) as conn:
        for short in ('', '  ', 'a', 'ab', '  ab '):
            with pytest.raises(aiosqlite.IntegrityError):
                await conn.execute(
                    "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', ?)",
                    (k1, short))


async def test_type_check_constraint(db_with_klanten):
    db, k1, _ = db_with_klanten
    async with get_db_ctx(db) as conn:
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'invalid_type', 'Foo BV')",
                (k1,))


async def test_cascade_delete_on_klant_removal(db_with_klanten):
    db, k1, _ = db_with_klanten
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
            (k1,))
        await conn.commit()
        await conn.execute("DELETE FROM klanten WHERE id = ?", (k1,))
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM klant_aliases WHERE klant_id = ?", (k1,))
        cnt = (await cur.fetchone())[0]
    assert cnt == 0


async def test_index_exists(db):
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_klant_aliases_lookup'")
        row = await cur.fetchone()
    assert row is not None
