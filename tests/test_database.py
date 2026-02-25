"""Tests voor database schema en CRUD operaties."""

import pytest
import aiosqlite
from database import (
    init_db, get_db, add_klant, get_klanten, add_werkdag, get_werkdagen,
    update_werkdag, delete_werkdag, get_werkdagen_ongefactureerd,
    add_factuur, get_facturen, get_next_factuurnummer,
    add_uitgave, get_uitgaven, get_uitgaven_per_categorie,
)


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path


@pytest.mark.asyncio
async def test_init_creates_tables(db):
    async with aiosqlite.connect(db) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in await cursor.fetchall()}
    expected = {'klanten', 'werkdagen', 'facturen', 'uitgaven',
                'banktransacties', 'fiscale_params'}
    assert tables >= expected


@pytest.mark.asyncio
async def test_pragma_foreign_keys(db):
    conn = await get_db(db)
    try:
        cur = await conn.execute("PRAGMA foreign_keys")
        row = await cur.fetchone()
        assert row[0] == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_pragma_wal_mode(db):
    conn = await get_db(db)
    try:
        cur = await conn.execute("PRAGMA journal_mode")
        row = await cur.fetchone()
        assert row[0] == 'wal'
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_klant_crud(db):
    kid = await add_klant(db, naam="HAP Klant6", tarief_uur=77.50, retour_km=52)
    assert kid > 0
    klanten = await get_klanten(db)
    assert len(klanten) == 1
    assert klanten[0].naam == "HAP Klant6"
    assert klanten[0].tarief_uur == 77.50
    assert klanten[0].retour_km == 52


@pytest.mark.asyncio
async def test_werkdag_crud(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    wid = await add_werkdag(db, datum="2026-02-23", klant_id=kid,
                            uren=9, km=44, tarief=80)
    assert wid > 0
    werkdagen = await get_werkdagen(db, jaar=2026)
    assert len(werkdagen) == 1
    assert werkdagen[0].uren == 9
    assert werkdagen[0].km == 44
    assert werkdagen[0].klant_naam == "Test"


@pytest.mark.asyncio
async def test_werkdag_update(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    wid = await add_werkdag(db, datum="2026-02-23", klant_id=kid,
                            uren=9, km=44, tarief=80)
    await update_werkdag(db, werkdag_id=wid, uren=8, opmerking="Aangepast")
    werkdagen = await get_werkdagen(db, jaar=2026)
    assert werkdagen[0].uren == 8
    assert werkdagen[0].opmerking == "Aangepast"


@pytest.mark.asyncio
async def test_werkdag_delete(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    wid = await add_werkdag(db, datum="2026-02-23", klant_id=kid,
                            uren=9, km=44, tarief=80)
    await delete_werkdag(db, werkdag_id=wid)
    werkdagen = await get_werkdagen(db, jaar=2026)
    assert len(werkdagen) == 0


@pytest.mark.asyncio
async def test_werkdagen_filter_by_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    await add_werkdag(db, datum="2025-06-15", klant_id=kid, uren=8, tarief=80)
    await add_werkdag(db, datum="2026-02-23", klant_id=kid, uren=9, tarief=80)

    w2025 = await get_werkdagen(db, jaar=2025)
    w2026 = await get_werkdagen(db, jaar=2026)
    assert len(w2025) == 1
    assert len(w2026) == 1
    assert w2025[0].uren == 8
    assert w2026[0].uren == 9


@pytest.mark.asyncio
async def test_werkdagen_ongefactureerd(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    wid1 = await add_werkdag(db, datum="2026-02-01", klant_id=kid, uren=8, tarief=80)
    wid2 = await add_werkdag(db, datum="2026-02-02", klant_id=kid, uren=9, tarief=80,
                              status='gefactureerd')
    ongefact = await get_werkdagen_ongefactureerd(db)
    assert len(ongefact) == 1
    assert ongefact[0].id == wid1


@pytest.mark.asyncio
async def test_factuurnummer_sequential(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    # First invoice of year
    num1 = await get_next_factuurnummer(db, jaar=2026)
    assert num1 == "2026-001"

    await add_factuur(db, nummer=num1, klant_id=kid, datum="2026-02-23",
                      totaal_bedrag=720)
    num2 = await get_next_factuurnummer(db, jaar=2026)
    assert num2 == "2026-002"

    await add_factuur(db, nummer=num2, klant_id=kid, datum="2026-02-24",
                      totaal_bedrag=640)
    num3 = await get_next_factuurnummer(db, jaar=2026)
    assert num3 == "2026-003"


@pytest.mark.asyncio
async def test_uitgaven_per_categorie(db):
    await add_uitgave(db, datum="2026-01-15", categorie="Bankkosten",
                      omschrijving="Rabo", bedrag=12.50)
    await add_uitgave(db, datum="2026-01-20", categorie="Bankkosten",
                      omschrijving="Rabo", bedrag=12.50)
    await add_uitgave(db, datum="2026-02-01", categorie="Telefoon/KPN",
                      omschrijving="KPN", bedrag=25.00)

    result = await get_uitgaven_per_categorie(db, jaar=2026)
    cats = {r['categorie']: r['totaal'] for r in result}
    assert cats['Bankkosten'] == 25.00
    assert cats['Telefoon/KPN'] == 25.00


@pytest.mark.asyncio
async def test_check_constraint_uren_positive(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    with pytest.raises(Exception):
        await add_werkdag(db, datum="2026-02-23", klant_id=kid,
                          uren=0, tarief=80)  # uren must be > 0


@pytest.mark.asyncio
async def test_check_constraint_bedrag_positive(db):
    with pytest.raises(Exception):
        await add_uitgave(db, datum="2026-01-01", categorie="Test",
                          omschrijving="Test", bedrag=-10)
