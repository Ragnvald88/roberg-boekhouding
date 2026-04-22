"""Migration #27 — back-fill bank-debit categorie into linked uitgaven."""
import aiosqlite
import pytest


async def _seed_banktx(db_path, id_, datum, bedrag, categorie='',
                       tegenpartij='', omschrijving='', genegeerd=0):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, categorie, tegenpartij, omschrijving, "
            "genegeerd) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id_, datum, bedrag, categorie, tegenpartij, omschrijving,
             genegeerd))
        await conn.commit()


async def _seed_uitgave(db_path, id_, datum, bedrag, categorie='',
                        omschrijving='x', bank_tx_id=None):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO uitgaven "
            "(id, datum, categorie, omschrijving, bedrag, bank_tx_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id_, datum, categorie, omschrijving, bedrag, bank_tx_id))
        await conn.commit()


async def _get_uitgaven(db_path):
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT id, datum, bedrag, categorie, omschrijving, bank_tx_id "
            "FROM uitgaven ORDER BY id")
        return [dict(r) for r in await cur.fetchall()]


async def _run_migration(db_path):
    """Re-invoke _run_migration_27 on an already-initialised DB."""
    from database import _run_migration_27
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await _run_migration_27(conn)
        await conn.commit()


@pytest.mark.asyncio
async def test_lazy_creates_uitgave_for_debit_with_categorie(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Telefoon/KPN', tegenpartij='KPN BV')
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert len(rows) == 1
    assert rows[0]['bank_tx_id'] == 1
    assert rows[0]['categorie'] == 'Telefoon/KPN'
    assert rows[0]['bedrag'] == 50.0
    assert rows[0]['omschrijving'] == 'KPN BV'


@pytest.mark.asyncio
async def test_copies_categorie_into_empty_linked_uitgave(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Verzekeringen', tegenpartij='Boekhouder')
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='', bank_tx_id=1)
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert len(rows) == 1
    assert rows[0]['id'] == 10
    assert rows[0]['categorie'] == 'Verzekeringen'


@pytest.mark.asyncio
async def test_does_not_overwrite_nonempty_uitgave_categorie(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Verzekeringen')
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='Representatie', bank_tx_id=1)
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows[0]['categorie'] == 'Representatie'


@pytest.mark.asyncio
async def test_skips_definitief_year(db):
    await _seed_banktx(db, 1, '2025-03-15', -50.0,
                       categorie='Telefoon/KPN')
    # Mark 2025 as definitief.
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (?, ?)", (2025, 'definitief'))
        await conn.commit()
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows == []


@pytest.mark.asyncio
async def test_skips_genegeerd_rows(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Telefoon/KPN', genegeerd=1)
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows == []


@pytest.mark.asyncio
async def test_skips_debits_with_empty_categorie(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0, categorie='')
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows == []


@pytest.mark.asyncio
async def test_skips_positive_transactions(db):
    await _seed_banktx(db, 1, '2026-03-15', +100.0,
                       categorie='Omzet')
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows == []


@pytest.mark.asyncio
async def test_idempotent(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Telefoon/KPN', tegenpartij='KPN BV')
    await _run_migration(db)
    first = await _get_uitgaven(db)
    await _run_migration(db)
    second = await _get_uitgaven(db)

    assert first == second


@pytest.mark.asyncio
async def test_fallback_omschrijving_when_no_tegenpartij(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Bankkosten',
                       tegenpartij='', omschrijving='rente')
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows[0]['omschrijving'] == 'rente'


@pytest.mark.asyncio
async def test_fallback_omschrijving_when_all_empty(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Bankkosten',
                       tegenpartij='', omschrijving='')
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows[0]['omschrijving'] == '(bank tx)'
