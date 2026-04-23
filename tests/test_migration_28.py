"""Migration #28 — unique partial index on uitgaven.bank_tx_id (NULL allowed)."""
import aiosqlite
import pytest


async def _index_exists(db_path, index_name: str) -> bool:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute("PRAGMA index_list(uitgaven)")
        return index_name in {r[1] for r in await cur.fetchall()}


@pytest.mark.asyncio
async def test_migration_28_creates_unique_partial_index(db):
    assert await _index_exists(db, "idx_uitgaven_bank_tx_unique")


@pytest.mark.asyncio
async def test_migration_28_enforces_uniqueness_on_non_null(db):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand) "
            "VALUES (1, '2026-03-01', -50.0, 'KPN', '', '', 't.csv')")
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id) VALUES ('2026-03-01', 'Telefoon/KPN', '', 50.0, 1)")
        await conn.commit()

        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
                "bank_tx_id) VALUES ('2026-03-01', 'Telefoon/KPN', '', 50.0, 1)")
            await conn.commit()


@pytest.mark.asyncio
async def test_migration_28_allows_multiple_null_bank_tx_id(db):
    """Cash uitgaven (bank_tx_id NULL) must stay allowed."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id) VALUES ('2026-03-01', 'Bankkosten', 'a', 1.0, NULL)")
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id) VALUES ('2026-03-02', 'Bankkosten', 'b', 2.0, NULL)")
        await conn.commit()
        cur = await conn.execute(
            "SELECT COUNT(*) FROM uitgaven WHERE bank_tx_id IS NULL")
        assert (await cur.fetchone())[0] == 2
