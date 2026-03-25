"""Tests voor untested database query functions (KPIs, omzet, debiteuren, etc.)."""

import pytest
from database import (
    add_klant, add_werkdag, add_factuur, add_uitgave,
    add_banktransacties, mark_betaald,
    get_omzet_totaal, get_representatie_totaal,
    get_debiteuren_op_peildatum,
    find_factuur_matches, apply_factuur_matches,
    get_nog_te_factureren, get_kpis, get_data_counts,
    get_afschrijving_overrides, get_afschrijving_overrides_batch,
    set_afschrijving_override, delete_afschrijving_override,
    get_db_ctx, get_va_betalingen,
)


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
                      datum="2026-01-15", totaal_bedrag=1000, type='factuur',
                      status='verstuurd')
    await add_factuur(db, nummer="2026-002", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=500, type='anw',
                      status='verstuurd')
    assert await get_omzet_totaal(db, jaar=2026) == 1500


@pytest.mark.asyncio
async def test_get_omzet_totaal_filters_by_year(db):
    """Only facturen in the given year are summed."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2025-001", klant_id=kid,
                      datum="2025-12-15", totaal_bedrag=1000, status='verstuurd')
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=750, status='verstuurd')
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
                      datum="2026-01-15", totaal_bedrag=1300, status='betaald')
    await add_factuur(db, nummer="2026-002", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=700, status='verstuurd')
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
                      datum="2026-12-15", totaal_bedrag=1000, status='verstuurd')
    await add_factuur(db, nummer="2026-002", klant_id=kid,
                      datum="2026-11-15", totaal_bedrag=500, status='verstuurd')
    assert await get_debiteuren_op_peildatum(db, peildatum='2026-12-31') == 1500.0


@pytest.mark.asyncio
async def test_debiteuren_peildatum_paid_after_yearend(db):
    """Facturen paid AFTER peildatum are receivables at year-end."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    # Paid before year-end → NOT a receivable
    f1 = await add_factuur(db, nummer="2026-001", klant_id=kid,
                           datum="2026-11-15", totaal_bedrag=1000,
                           status='betaald', betaald_datum='2026-12-20')
    # Paid AFTER year-end → IS a receivable
    f2 = await add_factuur(db, nummer="2026-002", klant_id=kid,
                           datum="2026-12-20", totaal_bedrag=700,
                           status='betaald', betaald_datum='2027-01-10')
    # Paid after year-end, different year invoice → still a receivable
    f3 = await add_factuur(db, nummer="2025-001", klant_id=kid,
                           datum="2025-12-28", totaal_bedrag=300,
                           status='betaald', betaald_datum='2027-02-01')
    assert await get_debiteuren_op_peildatum(db, peildatum='2026-12-31') == 1000.0
    # 700 (2026-002) + 300 (2025-001) = 1000


@pytest.mark.asyncio
async def test_debiteuren_peildatum_no_datum_excluded(db):
    """Paid facturen without betaald_datum are assumed paid (not receivables)."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-12-15", totaal_bedrag=1000,
                      status='betaald')  # no betaald_datum
    assert await get_debiteuren_op_peildatum(db, peildatum='2026-12-31') == 0.0


@pytest.mark.asyncio
async def test_debiteuren_peildatum_future_invoices_excluded(db):
    """Facturen issued AFTER peildatum are not receivables for that year."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2027-001", klant_id=kid,
                      datum="2027-01-05", totaal_bedrag=500, status='verstuurd')
    assert await get_debiteuren_op_peildatum(db, peildatum='2026-12-31') == 0.0


# ============================================================
# find_factuur_matches + apply_factuur_matches
# ============================================================

@pytest.mark.asyncio
async def test_find_matches_by_nummer(db):
    """Pass 1: match by invoice number in bank omschrijving."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-001', klant_id=kid,
                       datum='2026-01-15', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-01-20', 'bedrag': 640.00, 'tegenpartij': 'Test BV',
         'omschrijving': '2026-001 jan', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1
    assert matches[0]['factuur_nummer'] == '2026-001'
    assert matches[0]['bank_datum'] == '2026-01-20'
    assert matches[0]['match_type'] == 'nummer'

    # Verify NO changes applied yet (read-only)
    async with get_db_ctx(db) as conn:
        cur = await conn.execute('SELECT status FROM facturen WHERE nummer=?',
                                  ('2026-001',))
        assert (await cur.fetchone())['status'] == 'verstuurd'


@pytest.mark.asyncio
async def test_find_matches_by_amount(db):
    """Pass 2: match by amount when no nummer found in omschrijving."""
    kid = await add_klant(db, naam="Test", tarief_uur=77.50, retour_km=52)
    await add_factuur(db, nummer='2026-010', klant_id=kid,
                       datum='2026-02-10', totaal_uren=9, totaal_km=52,
                       totaal_bedrag=709.46, status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-02-15', 'bedrag': 709.46, 'tegenpartij': 'Klant',
         'omschrijving': 'betaling feb', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1
    assert matches[0]['factuur_nummer'] == '2026-010'
    assert matches[0]['match_type'] == 'bedrag'


@pytest.mark.asyncio
async def test_find_matches_skips_betaald(db):
    """Already-paid facturen are not matched."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-005', klant_id=kid,
                       datum='2026-03-01', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='betaald', betaald_datum='2026-03-05')
    await add_banktransacties(db, [
        {'datum': '2026-03-05', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': '2026-005', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 0


@pytest.mark.asyncio
async def test_find_matches_skips_linked_bank(db):
    """Bank transactions already linked are not reused."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-020', klant_id=kid,
                       datum='2026-03-10', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-03-15', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': '2026-020', 'categorie': ''},
    ], csv_bestand='test.csv')
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "UPDATE banktransacties SET koppeling_type='factuur' WHERE bedrag=640")
        await conn.commit()

    matches = await find_factuur_matches(db)
    assert len(matches) == 0


@pytest.mark.asyncio
async def test_find_matches_same_amount_chronological(db):
    """Two facturen with same amount: first by date wins."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-A', klant_id=kid,
                       datum='2026-01-10', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    await add_factuur(db, nummer='2026-B', klant_id=kid,
                       datum='2026-01-20', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-01-25', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1
    assert matches[0]['factuur_nummer'] == '2026-A'


@pytest.mark.asyncio
async def test_find_matches_anw_nummer(db):
    """ANW factuurnummers with special format are matched correctly."""
    kid = await add_klant(db, naam="ANW Diensten", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='22470-26-27', klant_id=kid,
                       datum='2026-01-10', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-01-20', 'bedrag': 640.00, 'tegenpartij': 'ANW',
         'omschrijving': 'Betaling 22470-26-27', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1
    assert matches[0]['match_type'] == 'nummer'


@pytest.mark.asyncio
async def test_find_matches_amount_outside_tolerance(db):
    """Amount difference > EUR 1 → no match."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-X', klant_id=kid,
                       datum='2026-02-01', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-02-10', 'bedrag': 650.00, 'tegenpartij': 'Test',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 0


@pytest.mark.asyncio
async def test_find_matches_empty_db(db):
    """No facturen, no bank transactions → empty list."""
    matches = await find_factuur_matches(db)
    assert matches == []


@pytest.mark.asyncio
async def test_apply_matches(db):
    """apply_factuur_matches marks factuur betaald and links bank transaction."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    fid = await add_factuur(db, nummer='2026-030', klant_id=kid,
                             datum='2026-03-01', totaal_uren=8, totaal_km=0,
                             totaal_bedrag=640.00, status='verstuurd')
    await add_werkdag(db, datum='2026-03-01', klant_id=kid,
                       uren=8, tarief=80, km=0, km_tarief=0.23,
                       status='gefactureerd', factuurnummer='2026-030')
    await add_banktransacties(db, [
        {'datum': '2026-03-10', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': '2026-030', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1

    count = await apply_factuur_matches(db, matches)
    assert count == 1

    async with get_db_ctx(db) as conn:
        cur = await conn.execute('SELECT status, betaald_datum FROM facturen WHERE id=?', (fid,))
        row = await cur.fetchone()
        assert row['status'] == 'betaald'
        assert row['betaald_datum'] == '2026-03-10'

        cur = await conn.execute(
            "SELECT koppeling_type, koppeling_id FROM banktransacties WHERE bedrag=640")
        row = await cur.fetchone()
        assert row['koppeling_type'] == 'factuur'
        assert row['koppeling_id'] == fid

        cur = await conn.execute(
            "SELECT status FROM werkdagen WHERE factuurnummer='2026-030'")
        row = await cur.fetchone()
        assert row['status'] == 'betaald'


@pytest.mark.asyncio
async def test_apply_matches_empty(db):
    """Empty match list → no changes, returns 0."""
    count = await apply_factuur_matches(db, [])
    assert count == 0


@pytest.mark.asyncio
async def test_find_matches_14_day_boundary_pass(db):
    """Payment exactly 14 days before factuur date should match (Pass 2)."""
    kid = await add_klant(db, naam="Boundary", tarief_uur=80, retour_km=0)
    # Factuur dated 2026-03-15
    await add_factuur(db, nummer='2026-BND', klant_id=kid,
                       datum='2026-03-15', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    # Payment 14 days before = 2026-03-01 (exactly on boundary)
    await add_banktransacties(db, [
        {'datum': '2026-03-01', 'bedrag': 640.00, 'tegenpartij': 'Someone',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1
    assert matches[0]['match_type'] == 'bedrag'


@pytest.mark.asyncio
async def test_find_matches_15_day_boundary_fail(db):
    """Payment 15 days before factuur date should NOT match."""
    kid = await add_klant(db, naam="Boundary", tarief_uur=80, retour_km=0)
    # Factuur dated 2026-03-16
    await add_factuur(db, nummer='2026-BND2', klant_id=kid,
                       datum='2026-03-16', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    # Payment 15 days before = 2026-03-01
    await add_banktransacties(db, [
        {'datum': '2026-03-01', 'bedrag': 640.00, 'tegenpartij': 'Someone',
         'omschrijving': 'betaling', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 0


# ============================================================
# Afschrijving overrides CRUD
# ============================================================

@pytest.mark.asyncio
async def test_set_and_get_override(db):
    """Set an override and retrieve it."""
    uid = await add_uitgave(db, datum='2024-06-01', categorie='Apparatuur',
                            omschrijving='Test asset', bedrag=1000,
                            is_investering=1, levensduur_jaren=5,
                            aanschaf_bedrag=1000)
    await set_afschrijving_override(db, uitgave_id=uid, jaar=2024, bedrag=200)
    overrides = await get_afschrijving_overrides(db, uitgave_id=uid)
    assert overrides == {2024: 200.0}


@pytest.mark.asyncio
async def test_override_upsert(db):
    """Setting override twice updates the value."""
    uid = await add_uitgave(db, datum='2024-06-01', categorie='Apparatuur',
                            omschrijving='Test', bedrag=1000,
                            is_investering=1, levensduur_jaren=5,
                            aanschaf_bedrag=1000)
    await set_afschrijving_override(db, uitgave_id=uid, jaar=2024, bedrag=200)
    await set_afschrijving_override(db, uitgave_id=uid, jaar=2024, bedrag=300)
    overrides = await get_afschrijving_overrides(db, uitgave_id=uid)
    assert overrides[2024] == 300.0


@pytest.mark.asyncio
async def test_delete_override(db):
    """Delete removes a specific override."""
    uid = await add_uitgave(db, datum='2024-06-01', categorie='Apparatuur',
                            omschrijving='Test', bedrag=1000,
                            is_investering=1, levensduur_jaren=5,
                            aanschaf_bedrag=1000)
    await set_afschrijving_override(db, uitgave_id=uid, jaar=2024, bedrag=200)
    await set_afschrijving_override(db, uitgave_id=uid, jaar=2025, bedrag=180)
    await delete_afschrijving_override(db, uitgave_id=uid, jaar=2024)
    overrides = await get_afschrijving_overrides(db, uitgave_id=uid)
    assert 2024 not in overrides
    assert overrides[2025] == 180.0


@pytest.mark.asyncio
async def test_batch_overrides(db):
    """Batch fetch returns overrides for multiple investments."""
    uid1 = await add_uitgave(db, datum='2024-01-01', categorie='Apparatuur',
                             omschrijving='A1', bedrag=1000,
                             is_investering=1, levensduur_jaren=5,
                             aanschaf_bedrag=1000)
    uid2 = await add_uitgave(db, datum='2024-06-01', categorie='Apparatuur',
                             omschrijving='A2', bedrag=2000,
                             is_investering=1, levensduur_jaren=5,
                             aanschaf_bedrag=2000)
    await set_afschrijving_override(db, uitgave_id=uid1, jaar=2024, bedrag=100)
    await set_afschrijving_override(db, uitgave_id=uid2, jaar=2024, bedrag=400)

    batch = await get_afschrijving_overrides_batch(db, [uid1, uid2])
    assert batch[uid1] == {2024: 100.0}
    assert batch[uid2] == {2024: 400.0}


@pytest.mark.asyncio
async def test_batch_overrides_empty(db):
    """Batch with empty list returns empty dict."""
    batch = await get_afschrijving_overrides_batch(db, [])
    assert batch == {}


@pytest.mark.asyncio
async def test_override_cascade_delete(db):
    """Deleting the uitgave should cascade-delete its overrides."""
    from database import delete_uitgave
    uid = await add_uitgave(db, datum='2024-06-01', categorie='Apparatuur',
                            omschrijving='Test', bedrag=1000,
                            is_investering=1, levensduur_jaren=5,
                            aanschaf_bedrag=1000)
    await set_afschrijving_override(db, uitgave_id=uid, jaar=2024, bedrag=200)
    await delete_uitgave(db, uitgave_id=uid)
    overrides = await get_afschrijving_overrides(db, uitgave_id=uid)
    assert overrides == {}


# ============================================================
# get_va_betalingen (IB/ZVW split from bank transactions)
# ============================================================

BELASTINGDIENST_IBAN = 'NL86INGB0002445588'


@pytest.mark.asyncio
async def test_get_va_betalingen_splits_ib_zvw(db):
    """VA payments are split by betalingskenmerk into IB and ZVW."""
    txns = [
        {'datum': '2026-02-23', 'bedrag': -2800.0,
         'tegenrekening': BELASTINGDIENST_IBAN, 'tegenpartij': 'Belastingdienst',
         'omschrijving': '', 'betalingskenmerk': '0124412647060001'},
        {'datum': '2026-01-22', 'bedrag': -1808.0,
         'tegenrekening': BELASTINGDIENST_IBAN, 'tegenpartij': 'Belastingdienst',
         'omschrijving': '', 'betalingskenmerk': '0124412647560014'},
    ]
    await add_banktransacties(db, txns)

    result = await get_va_betalingen(db, 2026)
    assert result['has_bank_data'] is True
    assert result['ib_betaald'] == pytest.approx(2800.0)
    assert result['ib_termijnen'] == 1
    assert result['zvw_betaald'] == pytest.approx(1808.0)
    assert result['zvw_termijnen'] == 1
    assert result['totaal_betaald'] == pytest.approx(4608.0)


@pytest.mark.asyncio
async def test_get_va_betalingen_no_data(db):
    """Returns has_bank_data=False when no Belastingdienst payments exist."""
    result = await get_va_betalingen(db, 2026)
    assert result['has_bank_data'] is False
    assert result['totaal_betaald'] == 0


@pytest.mark.asyncio
async def test_get_va_betalingen_no_kenmerk_fallback(db):
    """Without betalingskenmerk, sums all BD payments as combined."""
    txns = [
        {'datum': '2025-05-28', 'bedrag': -1900.0,
         'tegenrekening': BELASTINGDIENST_IBAN, 'tegenpartij': 'Belastingdienst',
         'omschrijving': '', 'betalingskenmerk': ''},
    ]
    await add_banktransacties(db, txns)

    result = await get_va_betalingen(db, 2025)
    assert result['has_bank_data'] is True
    assert result['totaal_betaald'] == pytest.approx(1900.0)
    assert result['ib_termijnen'] == 0
    assert result['zvw_termijnen'] == 0


