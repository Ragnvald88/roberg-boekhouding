"""get_kpi_kosten — KPI strip aggregates."""
import aiosqlite
import pytest
from database import get_kpi_kosten


async def _seed_banktx(db_path, id_, datum, bedrag):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij) "
            "VALUES (?, ?, ?, 'X')", (id_, datum, bedrag))
        await conn.commit()


async def _seed_uitgave(db_path, datum, bedrag, categorie="Kantoor",
                        is_investering=0, zakelijk_pct=100,
                        aanschaf_bedrag=None, levensduur=None, pdf_pad=""):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO uitgaven "
            "(datum, categorie, omschrijving, bedrag, pdf_pad, "
            " is_investering, zakelijk_pct, aanschaf_bedrag, levensduur_jaren) "
            "VALUES (?, ?, 'x', ?, ?, ?, ?, ?, ?)",
            (datum, categorie, bedrag, pdf_pad,
             is_investering, zakelijk_pct, aanschaf_bedrag, levensduur))
        await conn.commit()


@pytest.mark.asyncio
async def test_kpi_totaal_sums_abs(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    await _seed_uitgave(db, "2026-04-05", 10.00)
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.totaal == pytest.approx(130.87)


@pytest.mark.asyncio
async def test_kpi_monthly_totals_length_12(db):
    kpi = await get_kpi_kosten(db, 2026)
    assert len(kpi.monthly_totals) == 12
    assert sum(kpi.monthly_totals) == 0.0


@pytest.mark.asyncio
async def test_kpi_monthly_totals_by_month(db):
    await _seed_banktx(db, 1, "2026-01-15", -50.00)
    await _seed_banktx(db, 2, "2026-03-20", -30.00)
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.monthly_totals[0] == pytest.approx(50.00)
    assert kpi.monthly_totals[2] == pytest.approx(30.00)
    assert kpi.monthly_totals[6] == 0.0


@pytest.mark.asyncio
async def test_kpi_ontbreekt_counts_bank_only_rows(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.ontbreekt_count == 1
    assert kpi.ontbreekt_bedrag == pytest.approx(120.87)


@pytest.mark.asyncio
async def test_kpi_investeringen(db):
    await _seed_uitgave(db, "2026-03-01", 1200.00,
                        is_investering=1, zakelijk_pct=100,
                        aanschaf_bedrag=1200.00, levensduur=5)
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.investeringen_count == 1
    assert kpi.investeringen_bedrag == pytest.approx(1200.00)


@pytest.mark.asyncio
async def test_kpi_afschrijvingen_nonzero_with_investment(db):
    await _seed_uitgave(db, "2026-01-01", 1200.00,
                        is_investering=1, zakelijk_pct=100,
                        aanschaf_bedrag=1200.00, levensduur=5)
    kpi = await get_kpi_kosten(db, 2026)
    # Aanschaf 1200 * (1-0.10) / 5 = 216 over full year (12 months)
    assert kpi.afschrijvingen_jaar == pytest.approx(216.0, rel=0.02)


@pytest.mark.asyncio
async def test_kpi_ontbreekt_counts_linked_uitgave_missing_pdf(db):
    """Regression: debit with linked uitgave + categorie but no pdf_pad
    must count as ontbreekt_bon (status rename from "ontbreekt"
    → "ontbreekt_bon" in Task 2)."""
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO uitgaven "
            "(datum, categorie, omschrijving, bedrag, pdf_pad, "
            " bank_tx_id, is_investering, zakelijk_pct) "
            "VALUES (?, 'Kantoor', 'x', ?, '', ?, 0, 100)",
            ("2026-04-01", 120.87, 1))
        await conn.commit()
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.ontbreekt_count >= 1
    assert kpi.ontbreekt_bedrag == pytest.approx(120.87)


@pytest.mark.asyncio
async def test_kpi_excludes_genegeerd(db):
    await _seed_banktx(db, 1, "2026-04-01", -100.00)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "UPDATE banktransacties SET genegeerd = 1 WHERE id = 1")
        await conn.commit()
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.totaal == 0.0
    assert kpi.ontbreekt_count == 0


@pytest.mark.asyncio
async def test_kpi_totaal_excludes_investeringen(db):
    """P1-1 regression: Totaal kosten must not include the aanschafprijs
    of investeringen. Those are depreciated via afschrijvingen and shown
    in their own KPI card."""
    # Investering + regular uitgave in the same jaar.
    await _seed_uitgave(db, "2026-01-10", 5000.00,
                         categorie="Automatisering",
                         is_investering=1, zakelijk_pct=100,
                         aanschaf_bedrag=5000.00, levensduur=5)
    await _seed_uitgave(db, "2026-02-10", 100.00, categorie="Bankkosten")
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.totaal == pytest.approx(100.00), (
        "investering leaked into Totaal kosten — should only be reflected "
        "via investeringen_bedrag + afschrijvingen_jaar")
    # January month should be 0 (the €5000 lived there but is an investering).
    assert kpi.monthly_totals[0] == 0.0
    assert kpi.monthly_totals[1] == pytest.approx(100.00)
    # The investering still counts in its own KPI + contributes to afschrijving.
    assert kpi.investeringen_count == 1
    assert kpi.investeringen_bedrag == pytest.approx(5000.00)
    assert kpi.afschrijvingen_jaar > 0
