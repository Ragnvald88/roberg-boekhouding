"""Migration #26 — bank_tx_id on uitgaven, genegeerd on banktransacties."""
import aiosqlite
import pytest


async def _get_columns(db_path, table: str) -> set[str]:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(f"PRAGMA table_info({table})")
        return {r[1] for r in await cur.fetchall()}


async def _get_indexes(db_path, table: str) -> set[str]:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(f"PRAGMA index_list({table})")
        return {r[1] for r in await cur.fetchall()}


@pytest.mark.asyncio
async def test_migration_26_adds_bank_tx_id(db):
    cols = await _get_columns(db, "uitgaven")
    assert "bank_tx_id" in cols


@pytest.mark.asyncio
async def test_migration_26_adds_genegeerd(db):
    cols = await _get_columns(db, "banktransacties")
    assert "genegeerd" in cols


@pytest.mark.asyncio
async def test_migration_26_default_values(db):
    """Fresh row defaults: bank_tx_id NULL; genegeerd 0."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag) "
            "VALUES ('2026-01-01', 'Kantoor', 'pen', 2.50)")
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag) "
            "VALUES ('2026-01-01', -2.50)")
        await conn.commit()
        cur = await conn.execute("SELECT bank_tx_id FROM uitgaven")
        assert (await cur.fetchone())[0] is None
        cur = await conn.execute("SELECT genegeerd FROM banktransacties")
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_migration_26_indexes_exist(db):
    u_idx = await _get_indexes(db, "uitgaven")
    b_idx = await _get_indexes(db, "banktransacties")
    assert "idx_uitgaven_bank_tx" in u_idx
    assert "idx_bank_genegeerd" in b_idx


@pytest.mark.asyncio
async def test_migration_26_fk_set_null_on_delete(db):
    """Deleting a banktransactie sets uitgaven.bank_tx_id to NULL (no cascade)."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag) "
            "VALUES (1, '2026-01-01', -10.00)")
        await conn.execute(
            "INSERT INTO uitgaven "
            "(datum, categorie, omschrijving, bedrag, bank_tx_id) "
            "VALUES ('2026-01-01', 'Kantoor', 'x', 10.00, 1)")
        await conn.commit()
        await conn.execute("DELETE FROM banktransacties WHERE id = 1")
        await conn.commit()
        cur = await conn.execute("SELECT bank_tx_id FROM uitgaven")
        assert (await cur.fetchone())[0] is None
