"""get_kosten_view — unified bank_tx + manual uitgaven list."""
import aiosqlite
import pytest
from database import get_kosten_view, ensure_uitgave_for_banktx


async def _seed_banktx(db_path, id_, datum, bedrag, tp="KPN B.V.",
                        omschr="abo", genegeerd=0):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij, omschrijving, genegeerd) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id_, datum, bedrag, tp, omschr, genegeerd))
        await conn.commit()


async def _seed_uitgave(db_path, datum, bedrag, categorie="Kantoor",
                        omschrijving="x", pdf_pad=""):
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "pdf_pad) VALUES (?, ?, ?, ?, ?)",
            (datum, categorie, omschrijving, bedrag, pdf_pad))
        await conn.commit()
        return cur.lastrowid


@pytest.mark.asyncio
async def test_view_bank_only_row_has_ongecategoriseerd_status(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    rows = await get_kosten_view(db, jaar=2026)
    assert len(rows) == 1
    assert rows[0].status == "ongecategoriseerd"
    assert rows[0].bedrag == 120.87  # ABS
    assert rows[0].tegenpartij == "KPN B.V."


@pytest.mark.asyncio
async def test_view_manual_uitgave_appears(db):
    await _seed_uitgave(db, "2026-04-05", 10.00,
                        categorie="Kantoor", pdf_pad="/tmp/x.pdf")
    rows = await get_kosten_view(db, jaar=2026)
    assert len(rows) == 1
    assert rows[0].is_manual is True
    assert rows[0].status == "compleet"


@pytest.mark.asyncio
async def test_view_linked_uitgave_shows_once(db):
    """bank_tx linked to uitgave: one row only (bank side dominates)."""
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    await ensure_uitgave_for_banktx(db, 1, categorie="Telefoon/KPN")
    rows = await get_kosten_view(db, jaar=2026)
    assert len(rows) == 1
    assert rows[0].status == "ontbreekt_bon"  # no pdf yet
    assert rows[0].is_manual is False


@pytest.mark.asyncio
async def test_view_genegeerd_hidden(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87, genegeerd=1)
    rows = await get_kosten_view(db, jaar=2026)
    assert rows == []


@pytest.mark.asyncio
async def test_view_date_range_filter(db):
    await _seed_banktx(db, 1, "2025-12-31", -100.00)
    await _seed_banktx(db, 2, "2026-01-01", -200.00)
    await _seed_banktx(db, 3, "2026-12-31", -300.00)
    await _seed_banktx(db, 4, "2027-01-01", -400.00)
    rows = await get_kosten_view(db, jaar=2026)
    bedragen = sorted(r.bedrag for r in rows)
    assert bedragen == [200.00, 300.00]


@pytest.mark.asyncio
async def test_view_excludes_credits(db):
    await _seed_banktx(db, 1, "2026-04-01", 500.00)  # positive = credit
    rows = await get_kosten_view(db, jaar=2026)
    assert rows == []


@pytest.mark.asyncio
async def test_view_status_filter(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    await _seed_uitgave(db, "2026-04-05", 10.00, pdf_pad="/x.pdf")
    rows = await get_kosten_view(db, jaar=2026, status="compleet")
    assert len(rows) == 1
    assert rows[0].is_manual is True


@pytest.mark.asyncio
async def test_view_categorie_filter(db):
    await _seed_uitgave(db, "2026-04-01", 10.00, categorie="Kantoor",
                        pdf_pad="/x.pdf")
    await _seed_uitgave(db, "2026-04-02", 20.00, categorie="Representatie",
                        pdf_pad="/y.pdf")
    rows = await get_kosten_view(db, jaar=2026, categorie="Kantoor")
    assert len(rows) == 1
    assert rows[0].categorie == "Kantoor"


@pytest.mark.asyncio
async def test_view_search_substring(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87, tp="KPN B.V.")
    await _seed_banktx(db, 2, "2026-04-02", -50.00, tp="Shell")
    rows = await get_kosten_view(db, jaar=2026, search="kpn")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_view_ordered_by_datum_desc(db):
    await _seed_banktx(db, 1, "2026-03-01", -10.00)
    await _seed_banktx(db, 2, "2026-04-01", -20.00)
    rows = await get_kosten_view(db, jaar=2026)
    assert [r.datum for r in rows] == ["2026-04-01", "2026-03-01"]
