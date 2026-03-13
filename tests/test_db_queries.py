"""Tests voor untested database query functions (KPIs, omzet, debiteuren, etc.)."""

import pytest
from database import (
    init_db, add_klant, add_werkdag, add_factuur, add_uitgave,
    add_banktransacties, mark_betaald,
    get_omzet_totaal, get_representatie_totaal, get_openstaande_debiteuren,
    get_debiteuren_op_peildatum, auto_match_betaald_datum,
    get_nog_te_factureren, get_kpis, get_data_counts,
)


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path


# ============================================================
# get_omzet_totaal
# ============================================================

@pytest.mark.asyncio
async def test_get_omzet_totaal_empty(db):
    """No facturen → omzet is 0."""
    assert await get_omzet_totaal(db, jaar=2026) == 0


@pytest.mark.asyncio
async def test_get_omzet_totaal_sums_all_types(db):
    """Omzet sums both factuur and anw types."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=1000, type='factuur')
    await add_factuur(db, nummer="2026-002", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=500, type='anw')
    assert await get_omzet_totaal(db, jaar=2026) == 1500


@pytest.mark.asyncio
async def test_get_omzet_totaal_filters_by_year(db):
    """Only facturen in the given year are summed."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2025-001", klant_id=kid,
                      datum="2025-12-15", totaal_bedrag=1000)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=750)
    assert await get_omzet_totaal(db, jaar=2026) == 750
    assert await get_omzet_totaal(db, jaar=2025) == 1000


# ============================================================
# get_representatie_totaal
# ============================================================

@pytest.mark.asyncio
async def test_get_representatie_totaal_empty(db):
    """No uitgaven → representatie is 0."""
    assert await get_representatie_totaal(db, jaar=2026) == 0


@pytest.mark.asyncio
async def test_get_representatie_totaal_only_representatie(db):
    """Only 'Representatie' category is summed."""
    await add_uitgave(db, datum="2026-01-10", categorie="Representatie",
                      omschrijving="Lunch", bedrag=45.00)
    await add_uitgave(db, datum="2026-01-15", categorie="Representatie",
                      omschrijving="Diner", bedrag=75.00)
    await add_uitgave(db, datum="2026-01-20", categorie="Bankkosten",
                      omschrijving="Rabo", bedrag=12.50)
    assert await get_representatie_totaal(db, jaar=2026) == 120.00


@pytest.mark.asyncio
async def test_get_representatie_totaal_filters_by_year(db):
    """Only representatie in the given year is summed."""
    await add_uitgave(db, datum="2025-06-01", categorie="Representatie",
                      omschrijving="2025 lunch", bedrag=30.00)
    await add_uitgave(db, datum="2026-01-10", categorie="Representatie",
                      omschrijving="2026 lunch", bedrag=45.00)
    assert await get_representatie_totaal(db, jaar=2026) == 45.00


# ============================================================
# get_openstaande_debiteuren
# ============================================================

@pytest.mark.asyncio
async def test_get_openstaande_debiteuren_empty(db):
    """No facturen → debiteuren is 0."""
    assert await get_openstaande_debiteuren(db, jaar=2026) == 0.0


@pytest.mark.asyncio
async def test_get_openstaande_debiteuren_excludes_paid(db):
    """Only unpaid (betaald=0) facturen are counted."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=1000, betaald=0)
    await add_factuur(db, nummer="2026-002", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=500, betaald=1)
    assert await get_openstaande_debiteuren(db, jaar=2026) == 1000.0


@pytest.mark.asyncio
async def test_get_openstaande_debiteuren_filters_by_year(db):
    """Only unpaid facturen in the given year are counted."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2025-001", klant_id=kid,
                      datum="2025-12-15", totaal_bedrag=800, betaald=0)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=600, betaald=0)
    assert await get_openstaande_debiteuren(db, jaar=2026) == 600.0


# ============================================================
# get_nog_te_factureren
# ============================================================

@pytest.mark.asyncio
async def test_get_nog_te_factureren_empty(db):
    """No werkdagen → 0."""
    assert await get_nog_te_factureren(db, jaar=2026) == 0.0


@pytest.mark.asyncio
async def test_get_nog_te_factureren_only_ongefactureerd(db):
    """Only ongefactureerde werkdagen are counted."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    await add_werkdag(db, datum="2026-01-10", klant_id=kid,
                      uren=8, tarief=80, km=44, km_tarief=0.23,
                      status='ongefactureerd')
    await add_werkdag(db, datum="2026-01-11", klant_id=kid,
                      uren=9, tarief=80, km=44, km_tarief=0.23,
                      status='gefactureerd')
    # Expected: 8*80 + 44*0.23 = 640 + 10.12 = 650.12
    result = await get_nog_te_factureren(db, jaar=2026)
    assert abs(result - 650.12) < 0.01


@pytest.mark.asyncio
async def test_get_nog_te_factureren_calculates_correctly(db):
    """Revenue = uren*tarief + km*km_tarief per werkdag."""
    kid = await add_klant(db, naam="Test", tarief_uur=77.50, retour_km=52)
    await add_werkdag(db, datum="2026-02-01", klant_id=kid,
                      uren=9, tarief=77.50, km=52, km_tarief=0.23)
    await add_werkdag(db, datum="2026-02-02", klant_id=kid,
                      uren=8, tarief=77.50, km=52, km_tarief=0.23)
    # Expected: (9*77.50 + 52*0.23) + (8*77.50 + 52*0.23)
    # = (697.50 + 11.96) + (620 + 11.96) = 709.46 + 631.96 = 1341.42
    result = await get_nog_te_factureren(db, jaar=2026)
    assert abs(result - 1341.42) < 0.01


# ============================================================
# get_kpis
# ============================================================

@pytest.mark.asyncio
async def test_get_kpis_empty(db):
    """Empty DB → all KPIs are 0."""
    kpis = await get_kpis(db, jaar=2026)
    assert kpis['omzet'] == 0
    assert kpis['kosten'] == 0
    assert kpis['winst'] == 0
    assert kpis['uren'] == 0
    assert kpis['openstaand'] == 0


@pytest.mark.asyncio
async def test_get_kpis_with_data(db):
    """KPIs correctly combine facturen, uitgaven, werkdagen."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    # Facturen: 2000 total, 700 unpaid
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=1300, betaald=1)
    await add_factuur(db, nummer="2026-002", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=700, betaald=0)
    # Uitgaven: 100 regular + 500 investment (investment excluded from kosten)
    await add_uitgave(db, datum="2026-01-10", categorie="Bankkosten",
                      omschrijving="Rabo", bedrag=100)
    await add_uitgave(db, datum="2026-01-20", categorie="Apparatuur",
                      omschrijving="Laptop", bedrag=500, is_investering=1,
                      levensduur_jaren=5)
    # Werkdagen: 17 uren (urennorm=1), 8 uren achterwacht (urennorm=0)
    await add_werkdag(db, datum="2026-01-10", klant_id=kid,
                      uren=9, tarief=80, urennorm=1)
    await add_werkdag(db, datum="2026-01-11", klant_id=kid,
                      uren=8, tarief=80, urennorm=1)
    await add_werkdag(db, datum="2026-01-12", klant_id=kid,
                      uren=8, tarief=50, urennorm=0)  # achterwacht

    kpis = await get_kpis(db, jaar=2026)
    assert kpis['omzet'] == 2000
    assert kpis['kosten'] == 100  # excludes investment
    assert kpis['winst'] == 1900  # 2000 - 100
    assert kpis['uren'] == 17  # excludes urennorm=0
    assert kpis['openstaand'] == 700


# ============================================================
# get_data_counts
# ============================================================

@pytest.mark.asyncio
async def test_get_data_counts_empty(db):
    """Empty DB → all counts 0."""
    counts = await get_data_counts(db, jaar=2026)
    assert counts['n_facturen'] == 0
    assert counts['n_uitgaven'] == 0
    assert counts['n_werkdagen'] == 0


@pytest.mark.asyncio
async def test_get_data_counts_with_data(db):
    """Counts all records per table for the year."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=700)
    await add_factuur(db, nummer="2026-002", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=500)
    await add_factuur(db, nummer="2025-001", klant_id=kid,
                      datum="2025-12-15", totaal_bedrag=300)  # different year
    await add_uitgave(db, datum="2026-01-10", categorie="Bankkosten",
                      omschrijving="Rabo", bedrag=12.50)
    await add_werkdag(db, datum="2026-01-10", klant_id=kid,
                      uren=8, tarief=80)
    await add_werkdag(db, datum="2026-01-11", klant_id=kid,
                      uren=9, tarief=80)
    await add_werkdag(db, datum="2026-01-12", klant_id=kid,
                      uren=8, tarief=80)

    counts = await get_data_counts(db, jaar=2026)
    assert counts['n_facturen'] == 2  # not the 2025 one
    assert counts['n_uitgaven'] == 1
    assert counts['n_werkdagen'] == 3


# ============================================================
# get_debiteuren_op_peildatum (year-end receivables)
# ============================================================

@pytest.mark.asyncio
async def test_debiteuren_peildatum_empty(db):
    """No facturen → 0 receivables."""
    assert await get_debiteuren_op_peildatum(db, peildatum='2026-12-31') == 0.0


@pytest.mark.asyncio
async def test_debiteuren_peildatum_unpaid_included(db):
    """Unpaid facturen issued before peildatum are receivables."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-12-15", totaal_bedrag=1000, betaald=0)
    await add_factuur(db, nummer="2026-002", klant_id=kid,
                      datum="2026-11-15", totaal_bedrag=500, betaald=0)
    assert await get_debiteuren_op_peildatum(db, peildatum='2026-12-31') == 1500.0


@pytest.mark.asyncio
async def test_debiteuren_peildatum_paid_after_yearend(db):
    """Facturen paid AFTER peildatum are receivables at year-end."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    # Paid before year-end → NOT a receivable
    f1 = await add_factuur(db, nummer="2026-001", klant_id=kid,
                           datum="2026-11-15", totaal_bedrag=1000,
                           betaald=1, betaald_datum='2026-12-20')
    # Paid AFTER year-end → IS a receivable
    f2 = await add_factuur(db, nummer="2026-002", klant_id=kid,
                           datum="2026-12-20", totaal_bedrag=700,
                           betaald=1, betaald_datum='2027-01-10')
    # Paid after year-end, different year invoice → still a receivable
    f3 = await add_factuur(db, nummer="2025-001", klant_id=kid,
                           datum="2025-12-28", totaal_bedrag=300,
                           betaald=1, betaald_datum='2027-02-01')
    assert await get_debiteuren_op_peildatum(db, peildatum='2026-12-31') == 1000.0
    # 700 (2026-002) + 300 (2025-001) = 1000


@pytest.mark.asyncio
async def test_debiteuren_peildatum_no_datum_excluded(db):
    """Paid facturen without betaald_datum are assumed paid (not receivables)."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-12-15", totaal_bedrag=1000,
                      betaald=1)  # no betaald_datum
    assert await get_debiteuren_op_peildatum(db, peildatum='2026-12-31') == 0.0


@pytest.mark.asyncio
async def test_debiteuren_peildatum_future_invoices_excluded(db):
    """Facturen issued AFTER peildatum are not receivables for that year."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2027-001", klant_id=kid,
                      datum="2027-01-05", totaal_bedrag=500, betaald=0)
    assert await get_debiteuren_op_peildatum(db, peildatum='2026-12-31') == 0.0


# ============================================================
# auto_match_betaald_datum
# ============================================================

@pytest.mark.asyncio
async def test_auto_match_simple(db):
    """Matches a paid factuur to a bank transaction by amount."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    fid = await add_factuur(db, nummer="2026-001", klant_id=kid,
                            datum="2026-01-15", totaal_bedrag=1234.56,
                            betaald=1)  # no betaald_datum
    await add_banktransacties(db, transacties=[
        {'datum': '2026-02-01', 'bedrag': 1234.56,
         'tegenpartij': 'Test', 'omschrijving': 'Betaling'},
    ])

    count = await auto_match_betaald_datum(db)
    assert count == 1

    # Now the peildatum query should see it as a receivable at 31-01
    assert await get_debiteuren_op_peildatum(db, '2026-01-31') == 1234.56
    # But not at 28-02 (paid by then)
    assert await get_debiteuren_op_peildatum(db, '2026-02-28') == 0.0


@pytest.mark.asyncio
async def test_auto_match_tolerance(db):
    """Matches within €1 tolerance for rounding differences."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=2569.68,
                      betaald=1)
    await add_banktransacties(db, transacties=[
        {'datum': '2026-02-01', 'bedrag': 2569.83,  # €0.15 difference
         'tegenpartij': 'Test', 'omschrijving': 'Betaling'},
    ])

    count = await auto_match_betaald_datum(db)
    assert count == 1


@pytest.mark.asyncio
async def test_auto_match_no_double_use(db):
    """Each bank transaction is used at most once."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    # Two facturen with same amount
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=500, betaald=1)
    await add_factuur(db, nummer="2026-002", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=500, betaald=1)
    # Only ONE bank transaction
    await add_banktransacties(db, transacties=[
        {'datum': '2026-02-01', 'bedrag': 500,
         'tegenpartij': 'Test', 'omschrijving': 'Betaling'},
    ])

    count = await auto_match_betaald_datum(db)
    assert count == 1  # only one match, not two


@pytest.mark.asyncio
async def test_auto_match_idempotent(db):
    """Running auto_match twice doesn't change already-matched facturen."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=800, betaald=1)
    await add_banktransacties(db, transacties=[
        {'datum': '2026-02-01', 'bedrag': 800,
         'tegenpartij': 'Test', 'omschrijving': 'Betaling'},
    ])

    count1 = await auto_match_betaald_datum(db)
    assert count1 == 1
    count2 = await auto_match_betaald_datum(db)
    assert count2 == 0  # already matched, no changes


@pytest.mark.asyncio
async def test_auto_match_ignores_negative_bank(db):
    """Outgoing (negative) bank transactions are not matched."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=300, betaald=1)
    await add_banktransacties(db, transacties=[
        {'datum': '2026-02-01', 'bedrag': -300,  # outgoing
         'tegenpartij': 'Test', 'omschrijving': 'Uitgave'},
    ])

    count = await auto_match_betaald_datum(db)
    assert count == 0
