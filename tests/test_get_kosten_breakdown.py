"""Task 6 — get_kosten_breakdown per-categorie sum for /kosten overview."""
import pytest
import aiosqlite
from database import get_kosten_breakdown


async def _seed_banktx(db, id_, datum, bedrag, genegeerd=0):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand, genegeerd) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (id_, datum, bedrag, '', '', '', 't.csv', genegeerd))
        await conn.commit()


async def _seed_uitgave(db, datum, bedrag, categorie, bank_tx_id=None):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id, is_investering, zakelijk_pct) VALUES (?,?,?,?,?,?,?)",
            (datum, categorie, '', bedrag, bank_tx_id, 0, 100))
        await conn.commit()


@pytest.mark.asyncio
async def test_sums_bank_debits_via_linked_uitgave(db):
    await _seed_banktx(db, 1, '2026-03-01', -50)
    await _seed_uitgave(db, '2026-03-01', 50, 'Telefoon/KPN', bank_tx_id=1)
    got = await get_kosten_breakdown(db, jaar=2026)
    assert got == {'Telefoon/KPN': 50.0}


@pytest.mark.asyncio
async def test_sums_manual_cash(db):
    await _seed_uitgave(db, '2026-03-01', 20, 'Bankkosten')
    await _seed_uitgave(db, '2026-03-02', 30, 'Bankkosten')
    got = await get_kosten_breakdown(db, jaar=2026)
    assert got == {'Bankkosten': 50.0}


@pytest.mark.asyncio
async def test_excludes_genegeerd(db):
    await _seed_banktx(db, 1, '2026-03-01', -50, genegeerd=1)
    await _seed_uitgave(db, '2026-03-01', 50, 'Telefoon/KPN', bank_tx_id=1)
    got = await get_kosten_breakdown(db, jaar=2026)
    assert got == {}


@pytest.mark.asyncio
async def test_empty_categorie_bucketed_as_empty_string(db):
    await _seed_uitgave(db, '2026-03-01', 10, '')
    got = await get_kosten_breakdown(db, jaar=2026)
    assert got == {'': 10.0}


@pytest.mark.asyncio
async def test_multiple_categories_summed(db):
    await _seed_uitgave(db, '2026-03-01', 10, 'Bankkosten')
    await _seed_uitgave(db, '2026-03-02', 20, 'Bankkosten')
    await _seed_uitgave(db, '2026-03-03', 30, 'Telefoon/KPN')
    got = await get_kosten_breakdown(db, jaar=2026)
    assert got == {'Bankkosten': 30.0, 'Telefoon/KPN': 30.0}
