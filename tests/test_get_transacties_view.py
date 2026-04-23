"""Task 3 — get_transacties_view unified query (bank debits + positives + manual)."""
import aiosqlite
import pytest

from database import get_transacties_view, TransactieRow


async def _seed_banktx(db, id_, datum, bedrag, tegenpartij='KPN',
                        omschrijving='factuur', tegenrekening='NL00BANK01',
                        categorie='', koppeling_type=None, koppeling_id=None,
                        genegeerd=0):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij, omschrijving, tegenrekening, "
            " categorie, koppeling_type, koppeling_id, genegeerd, csv_bestand) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (id_, datum, bedrag, tegenpartij, omschrijving, tegenrekening,
             categorie, koppeling_type, koppeling_id, genegeerd, 't.csv'))
        await conn.commit()


async def _seed_uitgave(db, datum, bedrag, categorie='', omschrijving='',
                        pdf_pad='', bank_tx_id=None, is_investering=0):
    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "pdf_pad, bank_tx_id, is_investering, zakelijk_pct) "
            "VALUES (?,?,?,?,?,?,?,?) RETURNING id",
            (datum, categorie, omschrijving, bedrag, pdf_pad, bank_tx_id,
             is_investering, 100))
        uid = (await cur.fetchone())[0]
        await conn.commit()
    return uid


@pytest.mark.asyncio
async def test_returns_bank_debit_row(db):
    await _seed_banktx(db, 1, '2026-03-10', -42.00, tegenpartij='KPN B.V.')
    rows = await get_transacties_view(db, jaar=2026)
    assert len(rows) == 1
    r = rows[0]
    assert isinstance(r, TransactieRow)
    assert r.source == 'bank_debit'
    assert r.id_bank == 1
    assert r.id_uitgave is None
    assert r.bedrag == -42.0
    assert r.tegenpartij == 'KPN B.V.'
    assert r.is_manual is False


@pytest.mark.asyncio
async def test_returns_bank_credit_row(db):
    await _seed_banktx(db, 2, '2026-03-11', 1000.00, tegenpartij='Ziekenhuis X')
    rows = await get_transacties_view(db, jaar=2026)
    assert len(rows) == 1
    r = rows[0]
    assert r.source == 'bank_credit'
    assert r.id_bank == 2
    assert r.id_uitgave is None
    assert r.bedrag == 1000.0


@pytest.mark.asyncio
async def test_returns_manual_cash_row(db):
    await _seed_uitgave(db, '2026-03-12', 9.50,
                         categorie='Kleine aankopen', omschrijving='parkeer',
                         bank_tx_id=None)
    rows = await get_transacties_view(db, jaar=2026)
    assert len(rows) == 1
    r = rows[0]
    assert r.source == 'manual'
    assert r.id_bank is None
    assert r.bedrag == -9.50  # normalised negative for uniform display
    assert r.is_manual is True


@pytest.mark.asyncio
async def test_all_three_sources_returned_sorted_desc(db):
    await _seed_banktx(db, 1, '2026-01-05', -10)
    await _seed_banktx(db, 2, '2026-05-05', 500)
    await _seed_uitgave(db, '2026-03-15', 20, categorie='Bankkosten')
    rows = await get_transacties_view(db, jaar=2026)
    assert [r.datum for r in rows] == ['2026-05-05', '2026-03-15', '2026-01-05']


@pytest.mark.asyncio
async def test_year_range_excludes_other_years(db):
    await _seed_banktx(db, 1, '2025-12-31', -10)
    await _seed_banktx(db, 2, '2026-01-01', -20)
    await _seed_banktx(db, 3, '2027-01-01', -30)
    rows = await get_transacties_view(db, jaar=2026)
    ids = [r.id_bank for r in rows]
    assert ids == [2]


@pytest.mark.asyncio
async def test_bank_debit_join_picks_up_linked_uitgave(db):
    await _seed_banktx(db, 1, '2026-03-10', -50)
    uid = await _seed_uitgave(db, '2026-03-10', 50, categorie='Telefoon/KPN',
                               pdf_pad='/tmp/x.pdf', bank_tx_id=1)
    rows = await get_transacties_view(db, jaar=2026)
    assert len(rows) == 1
    r = rows[0]
    assert r.id_bank == 1
    assert r.id_uitgave == uid
    assert r.categorie == 'Telefoon/KPN'
    assert r.pdf_pad == '/tmp/x.pdf'
    assert r.status == 'compleet'
