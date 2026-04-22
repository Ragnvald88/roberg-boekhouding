"""Routing of /bank debit-categorie writes and display into uitgaven.*"""
import aiosqlite
import pytest

from database import (
    get_uitgave_categorie_by_bank_tx,
    set_banktx_categorie,
)


async def _seed_banktx(db_path, id_, datum, bedrag, categorie='',
                       tegenpartij=''):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, categorie, tegenpartij) "
            "VALUES (?, ?, ?, ?, ?)",
            (id_, datum, bedrag, categorie, tegenpartij))
        await conn.commit()


async def _seed_uitgave(db_path, id_, datum, bedrag, categorie='',
                        bank_tx_id=None):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO uitgaven "
            "(id, datum, categorie, omschrijving, bedrag, bank_tx_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id_, datum, categorie, 'x', bedrag, bank_tx_id))
        await conn.commit()


async def _get_banktx_categorie(db_path, id_):
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT categorie FROM banktransacties WHERE id = ?", (id_,))
        return (await cur.fetchone())[0]


async def _uitgave_count_for(db_path, bank_tx_id):
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM uitgaven WHERE bank_tx_id = ?",
            (bank_tx_id,))
        return (await cur.fetchone())[0]


async def _get_uitgave_categorie(db_path, bank_tx_id):
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT categorie FROM uitgaven WHERE bank_tx_id = ?",
            (bank_tx_id,))
        row = await cur.fetchone()
        return row[0] if row else None


# ---------- get_uitgave_categorie_by_bank_tx ----------

@pytest.mark.asyncio
async def test_returns_empty_dict_when_no_linked_uitgaven(db):
    result = await get_uitgave_categorie_by_bank_tx(db)
    assert result == {}


@pytest.mark.asyncio
async def test_returns_mapping_for_linked_uitgaven(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0)
    await _seed_banktx(db, 2, '2026-03-16', -30.0)
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='Telefoon/KPN', bank_tx_id=1)
    await _seed_uitgave(db, 11, '2026-03-16', 30.0,
                        categorie='Bankkosten', bank_tx_id=2)

    result = await get_uitgave_categorie_by_bank_tx(db)
    assert result == {1: 'Telefoon/KPN', 2: 'Bankkosten'}


@pytest.mark.asyncio
async def test_excludes_manual_uitgaven(db):
    # Manual uitgave = bank_tx_id NULL. Must not appear in the map.
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='Kantoor', bank_tx_id=None)
    result = await get_uitgave_categorie_by_bank_tx(db)
    assert result == {}


# ---------- set_banktx_categorie ----------

@pytest.mark.asyncio
async def test_set_categorie_on_debit_writes_to_uitgave(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0, tegenpartij='KPN')
    await set_banktx_categorie(db, bank_tx_id=1, categorie='Telefoon/KPN')

    # uitgave lazy-created with categorie set
    assert await _uitgave_count_for(db, 1) == 1
    assert await _get_uitgave_categorie(db, 1) == 'Telefoon/KPN'
    # bank row's categorie column is untouched
    assert await _get_banktx_categorie(db, 1) == ''


@pytest.mark.asyncio
async def test_set_categorie_on_positive_writes_to_banktransacties(db):
    await _seed_banktx(db, 1, '2026-03-15', +100.0)
    await set_banktx_categorie(db, bank_tx_id=1, categorie='Omzet')

    assert await _get_banktx_categorie(db, 1) == 'Omzet'
    assert await _uitgave_count_for(db, 1) == 0  # no uitgave created


@pytest.mark.asyncio
async def test_set_categorie_on_debit_updates_existing_uitgave(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0)
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='', bank_tx_id=1)
    await set_banktx_categorie(db, bank_tx_id=1, categorie='Telefoon/KPN')

    assert await _uitgave_count_for(db, 1) == 1
    assert await _get_uitgave_categorie(db, 1) == 'Telefoon/KPN'


@pytest.mark.asyncio
async def test_set_categorie_on_debit_overrides_existing_categorie(db):
    # User had previously categorised as Representatie; now picks
    # Telefoon/KPN on /bank. The update must land even when the linked
    # uitgave already had a non-empty categorie.
    await _seed_banktx(db, 1, '2026-03-15', -50.0)
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='Representatie', bank_tx_id=1)
    await set_banktx_categorie(db, bank_tx_id=1, categorie='Telefoon/KPN')

    assert await _get_uitgave_categorie(db, 1) == 'Telefoon/KPN'


@pytest.mark.asyncio
async def test_set_categorie_on_debit_year_locked_raises(db):
    from database import YearLockedError
    await _seed_banktx(db, 1, '2025-03-15', -50.0)
    await _seed_uitgave(db, 10, '2025-03-15', 50.0,
                        categorie='', bank_tx_id=1)
    # Directly INSERT the fiscale_params row so the year-lock gate fires.
    # (update_jaarafsluiting_status is pure UPDATE; it would be a no-op
    # without an existing row.)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (?, ?)", (2025, 'definitief'))
        await conn.commit()

    with pytest.raises(YearLockedError):
        await set_banktx_categorie(
            db, bank_tx_id=1, categorie='Telefoon/KPN')


@pytest.mark.asyncio
async def test_set_categorie_missing_banktx_raises(db):
    with pytest.raises(ValueError):
        await set_banktx_categorie(db, bank_tx_id=999, categorie='Kantoor')
