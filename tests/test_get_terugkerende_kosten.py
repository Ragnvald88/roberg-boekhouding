"""Task 8 — get_terugkerende_kosten detects recurring vendors."""
import pytest
import aiosqlite
from database import get_terugkerende_kosten


async def _seed_pair(db, tx_id, datum, bedrag, tegenpartij='KPN',
                      cat='Telefoon/KPN'):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand) "
            "VALUES (?,?,?,?,?,?,?)",
            (tx_id, datum, bedrag, tegenpartij, '', '', 't.csv'))
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id, is_investering, zakelijk_pct) "
            "VALUES (?,?,?,?,?,?,?)",
            (datum, cat, '', abs(bedrag), tx_id, 0, 100))
        await conn.commit()


@pytest.mark.asyncio
async def test_fewer_than_3_not_returned(db):
    await _seed_pair(db, 1, '2026-01-15', -50)
    await _seed_pair(db, 2, '2026-02-15', -50)
    got = await get_terugkerende_kosten(db, jaar=2026)
    assert got == []


@pytest.mark.asyncio
async def test_3_or_more_returned(db):
    await _seed_pair(db, 1, '2026-01-15', -50)
    await _seed_pair(db, 2, '2026-02-15', -50)
    await _seed_pair(db, 3, '2026-03-15', -50)
    got = await get_terugkerende_kosten(db, jaar=2026)
    assert len(got) == 1
    r = got[0]
    assert r['tegenpartij'].lower() == 'kpn'
    assert r['count'] == 3
    assert r['jaar_totaal'] == 150.0
    assert r['laatste_datum'] == '2026-03-15'


@pytest.mark.asyncio
async def test_window_boundary(db):
    """Hit >365d before jaar_end is excluded from count."""
    await _seed_pair(db, 1, '2024-12-31', -50)  # >365d before 2026-12-31
    await _seed_pair(db, 2, '2026-03-15', -50)
    await _seed_pair(db, 3, '2026-06-15', -50)
    got = await get_terugkerende_kosten(
        db, jaar=2026, min_count=3, window_days=365)
    assert got == []


@pytest.mark.asyncio
async def test_case_insensitive_grouping(db):
    await _seed_pair(db, 1, '2026-01-15', -50, tegenpartij='KPN B.V.')
    await _seed_pair(db, 2, '2026-02-15', -50, tegenpartij='kpn b.v.')
    await _seed_pair(db, 3, '2026-03-15', -50, tegenpartij='Kpn B.V.')
    got = await get_terugkerende_kosten(db, jaar=2026)
    assert len(got) == 1
    assert got[0]['count'] == 3


@pytest.mark.asyncio
async def test_sorted_by_jaar_totaal_desc(db):
    await _seed_pair(db, 1, '2026-01-15', -10, tegenpartij='A', cat='X')
    await _seed_pair(db, 2, '2026-02-15', -10, tegenpartij='A', cat='X')
    await _seed_pair(db, 3, '2026-03-15', -10, tegenpartij='A', cat='X')
    await _seed_pair(db, 4, '2026-01-15', -500, tegenpartij='B', cat='Y')
    await _seed_pair(db, 5, '2026-02-15', -500, tegenpartij='B', cat='Y')
    await _seed_pair(db, 6, '2026-03-15', -500, tegenpartij='B', cat='Y')
    got = await get_terugkerende_kosten(db, jaar=2026)
    assert [r['tegenpartij'].lower() for r in got] == ['b', 'a']
