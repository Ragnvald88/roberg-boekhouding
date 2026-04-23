"""Task 7 — get_kosten_per_maand 12-slot monthly totals."""
import pytest
import aiosqlite
from database import get_kosten_per_maand


async def _seed_uitgave(db, datum, bedrag, categorie='Bankkosten'):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id, is_investering, zakelijk_pct) VALUES (?,?,?,?,?,?,?)",
            (datum, categorie, '', bedrag, None, 0, 100))
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
