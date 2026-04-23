"""Task 5 (M5 polish) — get_uitgave_by_id targeted fetch."""
import pytest
import aiosqlite
from database import get_uitgave_by_id, Uitgave


async def _seed(db, **kwargs):
    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "pdf_pad, is_investering, zakelijk_pct, bank_tx_id) "
            "VALUES (?,?,?,?,?,?,?,?) RETURNING id",
            (kwargs.get('datum', '2026-03-01'),
             kwargs.get('categorie', 'Bankkosten'),
             kwargs.get('omschrijving', ''),
             kwargs.get('bedrag', 5.0),
             kwargs.get('pdf_pad', ''),
             kwargs.get('is_investering', 0),
             kwargs.get('zakelijk_pct', 100),
             kwargs.get('bank_tx_id', None)))
        uid = (await cur.fetchone())[0]
        await conn.commit()
    return uid


@pytest.mark.asyncio
async def test_returns_none_when_missing(db):
    assert await get_uitgave_by_id(db, 999) is None


@pytest.mark.asyncio
async def test_returns_populated_uitgave(db):
    uid = await _seed(db, categorie='Telefoon/KPN', bedrag=42.0,
                       omschrijving='test note')
    got = await get_uitgave_by_id(db, uid)
    assert isinstance(got, Uitgave)
    assert got.id == uid
    assert got.categorie == 'Telefoon/KPN'
    assert got.bedrag == 42.0
    assert got.omschrijving == 'test note'
