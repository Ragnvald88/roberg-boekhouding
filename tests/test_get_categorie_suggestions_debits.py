"""Task 9 — get_categorie_suggestions UNIONs debit + positive sources."""
import pytest
import aiosqlite
from database import get_categorie_suggestions


async def _seed_debit(db, tx_id, datum, tegenpartij, bedrag, cat):
    """Seed a debit bank tx + a linked uitgave with the categorie."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand) "
            "VALUES (?,?,?,?,?,?,?)",
            (tx_id, datum, bedrag, tegenpartij, '', '', 't.csv'))
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id, is_investering, zakelijk_pct) VALUES (?,?,?,?,?,?,?)",
            (datum, cat, '', abs(bedrag), tx_id, 0, 100))
        await conn.commit()


async def _seed_positive(db, tx_id, datum, tegenpartij, bedrag, cat):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand, categorie) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (tx_id, datum, bedrag, tegenpartij, '', '', 't.csv', cat))
        await conn.commit()


@pytest.mark.asyncio
async def test_debit_suggestion_returned_from_uitgaven(db):
    """Debit-categories live on uitgaven.categorie (migratie 27)."""
    await _seed_debit(db, 1, '2026-03-01', 'KPN B.V.', -50, 'Telefoon/KPN')
    await _seed_debit(db, 2, '2026-04-01', 'KPN B.V.', -50, 'Telefoon/KPN')
    got = await get_categorie_suggestions(db)
    assert got.get('kpn b.v.') == 'Telefoon/KPN'


@pytest.mark.asyncio
async def test_positive_suggestion_still_returned(db):
    await _seed_positive(db, 1, '2026-03-01', 'Ziekenhuis X', 1000, 'Omzet')
    got = await get_categorie_suggestions(db)
    assert got.get('ziekenhuis x') == 'Omzet'


@pytest.mark.asyncio
async def test_most_frequent_wins(db):
    await _seed_debit(db, 1, '2026-01-01', 'Shop', -10, 'Kleine aankopen')
    await _seed_debit(db, 2, '2026-02-01', 'Shop', -10, 'Kleine aankopen')
    await _seed_debit(db, 3, '2026-03-01', 'Shop', -10, 'Automatisering')
    got = await get_categorie_suggestions(db)
    assert got.get('shop') == 'Kleine aankopen'
