"""Task 7 — get_kosten_per_maand 12-slot monthly totals."""
import pytest
import aiosqlite
from database import get_kosten_per_maand


async def _seed_uitgave(db, datum, bedrag, categorie='Bankkosten',
                        bank_tx_id=None, is_investering=0):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id, is_investering, zakelijk_pct, "
            "aanschaf_bedrag, levensduur_jaren) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (datum, categorie, '', bedrag, bank_tx_id, is_investering, 100,
             bedrag if is_investering else None,
             5 if is_investering else None))
        await conn.commit()


async def _seed_banktx(db, id_, datum, bedrag):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand, genegeerd) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (id_, datum, bedrag, '', '', '', 't.csv', 0))
        await conn.commit()


@pytest.mark.asyncio
async def test_returns_12_slots(db):
    got = await get_kosten_per_maand(db, jaar=2026)
    assert len(got) == 12
    assert got == [0.0] * 12


@pytest.mark.asyncio
async def test_bucket_per_month(db):
    await _seed_uitgave(db, '2026-01-15', 10)
    await _seed_uitgave(db, '2026-01-20', 5)
    await _seed_uitgave(db, '2026-03-01', 100)
    await _seed_uitgave(db, '2026-12-31', 50)
    got = await get_kosten_per_maand(db, jaar=2026)
    assert got[0] == 15.0
    assert got[2] == 100.0
    assert got[11] == 50.0
    for i in [1, 3, 4, 5, 6, 7, 8, 9, 10]:
        assert got[i] == 0.0


@pytest.mark.asyncio
async def test_excludes_phantom_positive_banktx(db):
    """P0-1 regression: a uitgave linked to a positive bank-tx must not
    land in the monthly bars."""
    await _seed_banktx(db, 1, '2026-04-01', 500)  # income
    await _seed_uitgave(db, '2026-04-01', 500, bank_tx_id=1)
    got = await get_kosten_per_maand(db, jaar=2026)
    assert got == [0.0] * 12


@pytest.mark.asyncio
async def test_excludes_investeringen(db):
    """P1-1 regression: investeringen don't show up in monthly kosten."""
    await _seed_uitgave(db, '2026-01-10', 5000,
                         categorie='Automatisering', is_investering=1)
    await _seed_uitgave(db, '2026-02-10', 100)
    got = await get_kosten_per_maand(db, jaar=2026)
    assert got[0] == 0.0
    assert got[1] == 100.0
