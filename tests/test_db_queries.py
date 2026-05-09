"""Tests voor untested database query functions (KPIs, omzet, debiteuren, etc.)."""

from datetime import date

import pytest
from database import (
    add_klant, add_werkdag, add_factuur, add_uitgave,
    add_banktransacties, delete_banktransacties,
    ensure_uitgave_for_banktx,
    get_banktransacties, get_uitgaven_per_categorie,
    get_werkdagen_ongefactureerd, get_werkdagen_ongefactureerd_summary,
    mark_banktx_genegeerd,
    get_omzet_totaal, get_omzet_per_maand, get_representatie_totaal,
    get_debiteuren_op_peildatum,
    find_factuur_matches, apply_factuur_matches, MatchProposal,
    get_nog_te_factureren, get_kpis, get_kpis_tot_datum, get_data_counts,
    get_omzet_per_maand_tot_datum,
    get_afschrijving_overrides, get_afschrijving_overrides_batch,
    set_afschrijving_override, delete_afschrijving_override,
    get_db_ctx, get_va_betalingen, get_openstaande_facturen,
    update_factuur_status, update_uitgave,
    upsert_fiscale_params, get_fiscale_params, update_ib_inputs,
)



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


@pytest.mark.asyncio
async def test_get_representatie_totaal_excludes_investments(db):
    """Regression (review K1): a representatie-categorised investment must NOT
    be summed into the representation total.

    If it were, the 20% bijtelling on fiscale winst would double-count: once
    via this sum AND once via depreciation in activastaat.
    """
    # Ordinary representation expense — counts.
    await add_uitgave(db, datum="2026-01-10", categorie="Representatie",
                      omschrijving="Lunch relaties", bedrag=120.00)
    # Representation-category investment (e.g. a zakelijk kunstwerk that
    # will be depreciated over multiple years) — must be excluded.
    await add_uitgave(db, datum="2026-03-01", categorie="Representatie",
                      omschrijving="Kunstwerk wachtkamer", bedrag=3000.00,
                      is_investering=1, levensduur_jaren=10,
                      aanschaf_bedrag=3000.00, zakelijk_pct=100)
    assert await get_representatie_totaal(db, jaar=2026) == 120.00



@pytest.mark.asyncio
async def test_get_nog_te_factureren_empty(db):
    """No werkdagen → 0."""
    assert await get_nog_te_factureren(db, jaar=2026) == 0.0


@pytest.mark.asyncio
async def test_get_nog_te_factureren_only_ongefactureerd(db):
    """Only ongefactureerde werkdagen are counted."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    await add_werkdag(db, datum="2026-01-10", klant_id=kid,
                      uren=8, tarief=80, km=44, km_tarief=0.23)
    await add_werkdag(db, datum="2026-01-11", klant_id=kid,
                      uren=9, tarief=80, km=44, km_tarief=0.23,
                      factuurnummer='2026-099')
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
    assert matches[0].factuur_nummer == '2026-001'
    assert matches[0].bank_datum == '2026-01-20'
    assert matches[0].match_type == 'nummer'
    assert matches[0].confidence == 'high'

    # Verify NO changes applied yet (read-only)
    async with get_db_ctx(db) as conn:
        cur = await conn.execute('SELECT status FROM facturen WHERE nummer=?',
                                  ('2026-001',))
        row = await cur.fetchone()
        assert row is not None
        assert row['status'] == 'verstuurd'


@pytest.mark.asyncio
async def test_find_matches_by_nummer_rejects_substring_collision(db):
    """Regression (review K3): Pass 1 must NOT substring-match longer numbers.

    Factuur 2026-001 should NOT match a bank line whose omschrijving contains
    only 2026-0012 (an unrelated longer invoice number). Otherwise the user
    gets a 'high confidence' pre-selected match pointing to the wrong factuur
    — a silent wrong-invoice-paid bug.
    """
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    # Two invoices whose numbers differ only by trailing digits.
    await add_factuur(db, nummer='2026-001', klant_id=kid,
                      datum='2026-01-15', totaal_uren=8, totaal_km=0,
                      totaal_bedrag=640.00, status='verstuurd')
    await add_factuur(db, nummer='2026-0012', klant_id=kid,
                      datum='2026-01-16', totaal_uren=8, totaal_km=0,
                      totaal_bedrag=640.00, status='verstuurd')
    # Bank line mentions ONLY 2026-0012.
    await add_banktransacties(db, [
        {'datum': '2026-01-20', 'bedrag': 640.00, 'tegenpartij': 'Test BV',
         'omschrijving': 'factuur 2026-0012 betaald', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    # Only 2026-0012 should match via Pass 1 (nummer). 2026-001 must NOT.
    nummer_matches = [m for m in matches if m.match_type == 'nummer']
    assert len(nummer_matches) == 1
    assert nummer_matches[0].factuur_nummer == '2026-0012'


@pytest.mark.asyncio
async def test_find_matches_by_nummer_rejects_prefix_collision(db):
    """Regression (review K3): Pass 1 must NOT match when nummer appears as
    prefix of a longer digit run (reverse case of the substring test)."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2024-01', klant_id=kid,
                      datum='2024-01-15', totaal_uren=8, totaal_km=0,
                      totaal_bedrag=640.00, status='verstuurd')
    # Omschrijving accidentally contains "2024-010" (longer digit sequence
    # sharing the 2024-01 prefix).
    await add_banktransacties(db, [
        {'datum': '2024-01-20', 'bedrag': 640.00, 'tegenpartij': 'Test BV',
         'omschrijving': 'ref 2024-010 jan', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    nummer_matches = [m for m in matches if m.match_type == 'nummer']
    # 2024-01 must NOT substring-match 2024-010.
    assert len(nummer_matches) == 0


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
    assert matches[0].factuur_nummer == '2026-010'
    assert matches[0].match_type == 'bedrag'
    assert matches[0].confidence == 'high'


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
async def test_find_matches_same_amount_flagged_ambiguous(db):
    """Two facturen with IDENTICAL amount + one bank txn → both flagged ambiguous.

    Old behaviour (pre-best-match refactor): first factuur by date silently
    won, even though the user should have been asked. New behaviour: both
    facturen produce a low-confidence proposal referencing the same bank
    transaction, so the preview dialog surfaces the collision.
    """
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
    # Both facturen get a proposal so the ambiguity is visible.
    nummers = sorted(m.factuur_nummer for m in matches)
    assert nummers == ['2026-A', '2026-B']
    # Both are low confidence (identical amount → same delta on same bank txn).
    assert all(m.confidence == 'low' for m in matches)
    # Both point at the same bank transaction (the collision).
    assert len({m.bank_id for m in matches}) == 1


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
    assert matches[0].match_type == 'nummer'


@pytest.mark.asyncio
async def test_find_matches_amount_outside_tolerance(db):
    """Amount difference > EUR 0.05 (pass 2) → no match."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-X', klant_id=kid,
                       datum='2026-02-01', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-02-10', 'bedrag': 640.06, 'tegenpartij': 'Test',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 0


@pytest.mark.asyncio
async def test_find_matches_amount_within_rounding_tolerance(db):
    """Amount difference < EUR 0.05 (pass 2) → match."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-RT', klant_id=kid,
                       datum='2026-02-01', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-02-10', 'bedrag': 640.04, 'tegenpartij': 'Test',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1
    assert matches[0].match_type == 'bedrag'


@pytest.mark.asyncio
async def test_find_matches_empty_db(db):
    """No facturen, no bank transactions → empty list."""
    matches = await find_factuur_matches(db)
    assert matches == []


@pytest.mark.asyncio
async def test_find_factuur_matches_flags_ambiguous_pass2(db):
    """Pass 2: two facturen within tolerance of the same bank txn must be
    flagged as low-confidence so the user can disambiguate.

    Regression for the 'silent wrong-invoice-paid' bug where the first
    factuur chronologically would win even if the other was a better match.
    """
    klant_id = await add_klant(db, naam="AmbiguityTest", tarief_uur=100, retour_km=0)
    fid1 = await add_factuur(
        db, nummer='2025-AMB1', klant_id=klant_id,
        datum='2025-01-10', totaal_bedrag=640.00,
        status='verstuurd', type='factuur',
    )
    fid2 = await add_factuur(
        db, nummer='2025-AMB2', klant_id=klant_id,
        datum='2025-01-12', totaal_bedrag=640.03,
        status='verstuurd', type='factuur',
    )
    await add_banktransacties(db, [{
        'datum': '2025-01-15', 'bedrag': 640.01,
        'tegenpartij': 'AmbiguityTest', 'omschrijving': 'betaling',
    }])

    proposals = await find_factuur_matches(db)
    amb_proposals = [p for p in proposals if p.factuur_id in (fid1, fid2)]
    # Both facturen should have a proposal — neither silently dropped.
    assert len(amb_proposals) >= 1
    # At least one must be marked low-confidence.
    low = [p for p in amb_proposals if p.confidence == 'low']
    assert len(low) >= 1, (
        f"Expected low-confidence flag for ambiguous match, got: {amb_proposals}"
    )


@pytest.mark.asyncio
async def test_find_factuur_matches_ambiguous_at_exact_tolerance_boundary(
        db, monkeypatch):
    """Regression (review K4): two facturen whose delta-difference equals
    _MATCH_AMOUNT_TOL exactly must BOTH be flagged ambiguous.

    Uses a monkeypatched TOL of 0.125 (exactly representable in IEEE-754
    float, unlike 0.05) so the boundary is hit without FP rounding drift.

    Old code used strict `<`: two matches 0.125 apart were deemed
    unambiguous and silently disambiguated. `<=` surfaces both.
    """
    import database
    monkeypatch.setattr(database, '_MATCH_AMOUNT_TOL', 0.125)

    klant_id = await add_klant(db, naam="BoundaryTest", tarief_uur=100, retour_km=0)
    # A exactly matches bank. B is 0.125 away. alt_delta - best_delta == 0.125.
    fid_a = await add_factuur(
        db, nummer='2025-BND-A', klant_id=klant_id,
        datum='2025-06-10', totaal_bedrag=500.00,
        status='verstuurd', type='factuur',
    )
    fid_b = await add_factuur(
        db, nummer='2025-BND-B', klant_id=klant_id,
        datum='2025-06-11', totaal_bedrag=500.125,
        status='verstuurd', type='factuur',
    )
    await add_banktransacties(db, [{
        'datum': '2025-06-15', 'bedrag': 500.00,
        'tegenpartij': 'BoundaryTest', 'omschrijving': 'betaling',
    }])

    proposals = await find_factuur_matches(db)
    ours = [p for p in proposals if p.factuur_id in (fid_a, fid_b)]
    assert len(ours) == 2, (
        f"Both facturen within TOL of bank must surface; got {ours}"
    )
    # Neither may be silently marked high-confidence at the boundary.
    low = [p for p in ours if p.confidence == 'low']
    assert len(low) >= 1, (
        f"Exact-TOL boundary must flag ambiguity; got {ours}"
    )


@pytest.mark.asyncio
async def test_find_factuur_matches_pass2_high_confidence_when_unambiguous(db):
    """Pass 2: one factuur in tolerance window → high confidence, no alternatives."""
    klant_id = await add_klant(db, naam="ClearTest", tarief_uur=100, retour_km=0)
    fid = await add_factuur(
        db, nummer='2025-CLEAR', klant_id=klant_id,
        datum='2025-02-01', totaal_bedrag=500.00,
        status='verstuurd', type='factuur',
    )
    await add_banktransacties(db, [{
        'datum': '2025-02-03', 'bedrag': 500.00,
        'tegenpartij': 'ClearTest', 'omschrijving': 'betaling',
    }])

    proposals = await find_factuur_matches(db)
    our_prop = [p for p in proposals if p.factuur_id == fid]
    assert len(our_prop) == 1
    assert our_prop[0].confidence == 'high'
    assert our_prop[0].alternatives == []


@pytest.mark.asyncio
async def test_apply_matches(db):
    """apply_factuur_matches marks factuur betaald and links bank transaction."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    fid = await add_factuur(db, nummer='2026-030', klant_id=kid,
                             datum='2026-03-01', totaal_uren=8, totaal_km=0,
                             totaal_bedrag=640.00, status='verstuurd')
    await add_werkdag(db, datum='2026-03-01', klant_id=kid,
                       uren=8, tarief=80, km=0, km_tarief=0.23,
                       factuurnummer='2026-030')
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
        assert row is not None
        assert row['status'] == 'betaald'
        assert row['betaald_datum'] == '2026-03-10'

        cur = await conn.execute(
            "SELECT koppeling_type, koppeling_id FROM banktransacties WHERE bedrag=640")
        row = await cur.fetchone()
        assert row is not None
        assert row['koppeling_type'] == 'factuur'
        assert row['koppeling_id'] == fid

        # Werkdag status is now derived — verify the linked factuur is betaald
        cur = await conn.execute(
            "SELECT f.status FROM werkdagen w "
            "JOIN facturen f ON w.factuurnummer = f.nummer "
            "WHERE w.factuurnummer='2026-030'")
        row = await cur.fetchone()
        assert row is not None
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
    assert matches[0].match_type == 'bedrag'


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


@pytest.mark.asyncio
async def test_find_matches_90_day_upper_bound_pass(db):
    """Payment 89 days after factuur date should still match."""
    kid = await add_klant(db, naam="Late", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-LATE', klant_id=kid,
                       datum='2026-01-01', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    # 89 days after 2026-01-01 = 2026-03-31
    await add_banktransacties(db, [
        {'datum': '2026-03-31', 'bedrag': 640.00, 'tegenpartij': 'Late',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_find_matches_91_day_upper_bound_fail(db):
    """Payment 91 days after factuur date should NOT match."""
    kid = await add_klant(db, naam="TooLate", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-TLATE', klant_id=kid,
                       datum='2026-01-01', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    # 91 days after 2026-01-01 = 2026-04-02
    await add_banktransacties(db, [
        {'datum': '2026-04-02', 'bedrag': 640.00, 'tegenpartij': 'TooLate',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 0



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
    """No-kenmerk → unmatched_betaald, niet totaal_betaald (post-Sprint-I)."""
    BD = 'NL86INGB0002445588'
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2025-06-15', -500, BD, '', 'BD geen kenmerk'))
        await conn.commit()

    out = await get_va_betalingen(db, jaar=2025)
    assert out['totaal_betaald'] == 0  # was 500 in pre-Sprint-I
    assert out['unmatched_betaald'] == 500
    assert out['has_bank_data'] is True


@pytest.mark.asyncio
async def test_get_va_betalingen_excludes_unmatched_from_totaal_betaald(db):
    """BREAKING: totaal_betaald = ib + zvw, NIET inclusief unmatched."""
    BD = 'NL86INGB0002445588'
    async with get_db_ctx(db) as conn:
        # 1 IB-betaling (kenmerk pos 10-11 = '12' < 50)
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving, categorie) VALUES (?,?,?,?,?,?)",
            ('2026-03-15', -800, BD, '0123456789120000', 'VA IB', 'Belasting'))
        # 1 ZVW-betaling (kenmerk pos 10-11 = '50' >= 50)
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving, categorie) VALUES (?,?,?,?,?,?)",
            ('2026-04-15', -300, BD, '0123456789500000', 'VA ZVW', 'Belasting'))
        # 1 unmatched (kenmerk te kort)
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving, categorie) VALUES (?,?,?,?,?,?)",
            ('2026-05-15', -200, BD, '12345', 'BD onbekend', 'Belasting'))
        await conn.commit()

    out = await get_va_betalingen(db, jaar=2026)
    assert out['ib_betaald'] == 800
    assert out['zvw_betaald'] == 300
    assert out['unmatched_betaald'] == 200
    assert out['unmatched_termijnen'] == 1
    assert out['totaal_betaald'] == 1100  # ib + zvw, NIET +200
    assert out['has_bank_data'] is True


@pytest.mark.asyncio
async def test_get_va_betalingen_bankdata_tot_datum_negative_only(db):
    """bankdata_tot_datum max van negatieve BD-rows; positieve genegeerd."""
    BD = 'NL86INGB0002445588'
    from datetime import date as _date
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-03-15', -800, BD, '0123456789120000', 'VA IB'))
        # Positief = correctie/teruggave; negeren voor zowel betaald als datum
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-08-20', 100, BD, '0123456789120000', 'BD teruggave'))
        await conn.commit()

    out = await get_va_betalingen(db, jaar=2026)
    assert out['bankdata_tot_datum'] == _date(2026, 3, 15)
    assert out['ib_betaald'] == 800  # positieve genegeerd


@pytest.mark.asyncio
async def test_get_va_betalingen_bankdata_tot_datum_none_when_no_negative_rows(db):
    """Geen negatieve BD-rijen → bankdata_tot_datum is None."""
    out = await get_va_betalingen(db, jaar=2026)
    assert out['bankdata_tot_datum'] is None
    assert out['has_bank_data'] is False


@pytest.mark.asyncio
async def test_get_va_betalingen_return_contract_shape(db):
    """Return-dict heeft exact 9 keys in zowel no-data als data-pad."""
    expected_keys = {
        'ib_betaald', 'ib_termijnen',
        'zvw_betaald', 'zvw_termijnen',
        'unmatched_betaald', 'unmatched_termijnen',
        'totaal_betaald', 'has_bank_data',
        'bankdata_tot_datum',
    }
    # No-data path
    out_empty = await get_va_betalingen(db, jaar=2026)
    assert set(out_empty.keys()) == expected_keys

    # Data path
    BD = 'NL86INGB0002445588'
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-03-15', -800, BD, '0123456789120000', 'VA IB'))
        await conn.commit()
    out_data = await get_va_betalingen(db, jaar=2026)
    assert set(out_data.keys()) == expected_keys


@pytest.mark.asyncio
async def test_get_va_betalingen_only_positive_rows_treated_as_no_data(db):
    """Alleen positieve BD-tx (correctie/teruggave) → has_bank_data False."""
    BD = 'NL86INGB0002445588'
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-08-20', 100, BD, '0123456789120000', 'BD teruggave'))
        await conn.commit()

    out = await get_va_betalingen(db, jaar=2026)
    assert out['has_bank_data'] is False
    assert out['bankdata_tot_datum'] is None
    assert out['totaal_betaald'] == 0
    assert out['ib_betaald'] == 0
    assert out['zvw_betaald'] == 0
    assert out['unmatched_betaald'] == 0
    assert out['unmatched_termijnen'] == 0


@pytest.mark.asyncio
async def test_get_va_betalingen_unmatched_kenmerk_variants(db):
    """3 kenmerk-edge-cases vallen alle in unmatched."""
    BD = 'NL86INGB0002445588'
    async with get_db_ctx(db) as conn:
        # Te kort kenmerk
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-02-15', -100, BD, '12345', 'kort'))
        # Niet-numerieke chars (alleen letters)
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-03-15', -150, BD, 'ABCDEFGHIJ123', 'letters'))
        # Lege kenmerk
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-04-15', -200, BD, '', 'leeg'))
        await conn.commit()

    out = await get_va_betalingen(db, jaar=2026)
    assert out['unmatched_termijnen'] == 3
    assert out['unmatched_betaald'] == 450
    assert out['ib_betaald'] == 0
    assert out['zvw_betaald'] == 0



CLASSIFY_VERGOEDING_SQL = """
    UPDATE facturen SET type = 'vergoeding'
    WHERE type = 'factuur'
    AND NOT EXISTS (SELECT 1 FROM werkdagen w WHERE w.factuurnummer = facturen.nummer)
    AND status != 'concept'
"""


@pytest.mark.asyncio
async def test_classify_orphan_facturen_as_vergoeding(db):
    """Orphan facturen (no werkdagen) are classified as vergoeding,
    but concept facturen and werkdag-backed facturen stay as 'factuur'."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)

    # Orphan factuur (verstuurd, no werkdagen) → should become vergoeding
    await add_factuur(db, nummer="2026-V01", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=500,
                      status='verstuurd', type='factuur')

    # Orphan factuur (betaald, no werkdagen) → should become vergoeding
    await add_factuur(db, nummer="2026-V02", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=300,
                      status='betaald', type='factuur')

    # Concept factuur (no werkdagen) → should stay 'factuur'
    await add_factuur(db, nummer="2026-C01", klant_id=kid,
                      datum="2026-03-01", totaal_bedrag=200,
                      status='concept', type='factuur')

    # Werkdag-backed factuur → should stay 'factuur'
    await add_factuur(db, nummer="2026-F01", klant_id=kid,
                      datum="2026-01-20", totaal_bedrag=640,
                      status='verstuurd', type='factuur')
    await add_werkdag(db, datum="2026-01-20", klant_id=kid,
                      uren=8, tarief=80, factuurnummer='2026-F01')

    # ANW factuur (no werkdagen) → already type='anw', should not change
    await add_factuur(db, nummer="2026-A01", klant_id=kid,
                      datum="2026-01-25", totaal_bedrag=400,
                      status='verstuurd', type='anw')

    # Run the classification SQL directly (migration runs before test data)
    async with get_db_ctx(db) as conn:
        await conn.execute(CLASSIFY_VERGOEDING_SQL)
        await conn.commit()

        # Verify results
        cur = await conn.execute(
            "SELECT nummer, type FROM facturen ORDER BY nummer")
        rows = {r['nummer']: r['type'] for r in await cur.fetchall()}

    assert rows['2026-V01'] == 'vergoeding'  # orphan verstuurd → vergoeding
    assert rows['2026-V02'] == 'vergoeding'  # orphan betaald → vergoeding
    assert rows['2026-C01'] == 'factuur'     # concept → stays factuur
    assert rows['2026-F01'] == 'factuur'     # has werkdagen → stays factuur
    assert rows['2026-A01'] == 'anw'         # anw → unchanged


@pytest.mark.asyncio
async def test_openstaande_facturen_includes_vergoedingen(db):
    """Verstuurd vergoedingen appear in openstaande facturen."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)

    # Regular verstuurd factuur
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=1000,
                      status='verstuurd', type='factuur')

    # Verstuurd vergoeding
    await add_factuur(db, nummer="2026-099", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=500,
                      status='verstuurd', type='vergoeding')

    # Betaald vergoeding → should NOT appear
    await add_factuur(db, nummer="2026-100", klant_id=kid,
                      datum="2026-03-15", totaal_bedrag=200,
                      status='betaald', type='vergoeding')

    # Verstuurd ANW → should also appear
    await add_factuur(db, nummer="2026-A01", klant_id=kid,
                      datum="2026-04-15", totaal_bedrag=300,
                      status='verstuurd', type='anw')

    openstaand = await get_openstaande_facturen(db)
    nummers = [f.nummer for f in openstaand]
    assert "2026-001" in nummers   # regular factuur
    assert "2026-099" in nummers   # vergoeding
    assert "2026-A01" in nummers   # anw
    assert "2026-100" not in nummers  # betaald excluded



@pytest.mark.asyncio
async def test_debiteuren_peildatum_excludes_concept(db):
    """Concept facturen should NOT appear in debiteuren (receivables)."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    # Verstuurd → IS a receivable
    await add_factuur(db, nummer="2026-D01", klant_id=kid,
                      datum="2026-11-15", totaal_bedrag=1000, status='verstuurd')
    # Concept → should NOT be a receivable
    await add_factuur(db, nummer="2026-D02", klant_id=kid,
                      datum="2026-12-01", totaal_bedrag=500, status='concept')
    result = await get_debiteuren_op_peildatum(db, peildatum='2026-12-31')
    assert result == 1000.0  # only the verstuurd one


@pytest.mark.asyncio
async def test_find_matches_excludes_concept(db):
    """Concept facturen should NOT be candidates for bank matching."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    # Concept factuur — should NOT be matched
    await add_factuur(db, nummer='2026-C01', klant_id=kid,
                       datum='2026-01-15', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='concept')
    # Verstuurd factuur — should be matched
    await add_factuur(db, nummer='2026-S01', klant_id=kid,
                       datum='2026-01-15', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-01-20', 'bedrag': 640.00, 'tegenpartij': 'Test BV',
         'omschrijving': '2026-C01 payment', 'categorie': ''},
        {'datum': '2026-01-21', 'bedrag': 640.00, 'tegenpartij': 'Test BV',
         'omschrijving': '2026-S01 payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    # Only verstuurd should match, not concept
    assert len(matches) == 1
    assert matches[0].factuur_nummer == '2026-S01'


@pytest.mark.asyncio
async def test_omzet_excludes_concept_regression(db):
    """Regression: get_omzet_totaal must exclude concept facturen."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2026-R01", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=1000, status='verstuurd')
    await add_factuur(db, nummer="2026-R02", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=500, status='concept')
    assert await get_omzet_totaal(db, jaar=2026) == 1000  # concept excluded



@pytest.mark.asyncio
async def test_apply_matches_only_verstuurd(db):
    """apply_factuur_matches should only transition verstuurd→betaald,
    not concept→betaald."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    # Create a concept factuur
    fid_concept = await add_factuur(db, nummer='2026-C10', klant_id=kid,
                                     datum='2026-03-01', totaal_uren=8, totaal_km=0,
                                     totaal_bedrag=640.00, status='concept')
    # Create a verstuurd factuur
    fid_verstuurd = await add_factuur(db, nummer='2026-V10', klant_id=kid,
                                       datum='2026-03-01', totaal_uren=8, totaal_km=0,
                                       totaal_bedrag=640.00, status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-03-10', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': 'pay1', 'categorie': ''},
        {'datum': '2026-03-11', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': 'pay2', 'categorie': ''},
    ], csv_bestand='test.csv')

    # Manually craft matches that include both concept and verstuurd
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT id FROM banktransacties ORDER BY datum")
        bank_rows = list(await cur.fetchall())

    fake_matches = [
        MatchProposal(
            factuur_id=fid_concept, bank_id=bank_rows[0]['id'],
            delta=0.0, confidence='high', match_type='bedrag',
            bank_datum='2026-03-10',
        ),
        MatchProposal(
            factuur_id=fid_verstuurd, bank_id=bank_rows[1]['id'],
            delta=0.0, confidence='high', match_type='bedrag',
            bank_datum='2026-03-11',
        ),
    ]

    count = await apply_factuur_matches(db, fake_matches)
    # Only the verstuurd one should have been applied
    assert count == 1

    async with get_db_ctx(db) as conn:
        cur = await conn.execute('SELECT status FROM facturen WHERE id=?', (fid_concept,))
        row = await cur.fetchone()
        assert row is not None
        assert row['status'] == 'concept'  # unchanged!

        cur = await conn.execute('SELECT status FROM facturen WHERE id=?', (fid_verstuurd,))
        row = await cur.fetchone()
        assert row is not None
        assert row['status'] == 'betaald'  # changed!



@pytest.mark.asyncio
async def test_kpis_omzet_excludes_concept(db):
    """KPI omzet must exclude concept invoices."""
    klant_id = await add_klant(db, naam='Test Klant')
    await add_factuur(db, nummer='2024-001', klant_id=klant_id,
                      datum='2024-03-01', totaal_bedrag=5000.00,
                      status='verstuurd')
    await add_factuur(db, nummer='2024-002', klant_id=klant_id,
                      datum='2024-04-01', totaal_bedrag=1000.00,
                      status='concept')
    kpis = await get_kpis(db, jaar=2024)
    assert kpis['omzet'] == 5000.00, f"Concept should be excluded from KPI omzet, got {kpis['omzet']}"



@pytest.mark.asyncio
async def test_duplicate_factuurnummer_rejected(db):
    """Inserting a duplicate factuurnummer should raise an error."""
    import sqlite3
    klant_id = await add_klant(db, naam='Test Klant')
    await add_factuur(db, nummer='2024-001', klant_id=klant_id,
                      datum='2024-01-01', totaal_bedrag=100.00)
    with pytest.raises(sqlite3.IntegrityError):
        await add_factuur(db, nummer='2024-001', klant_id=klant_id,
                          datum='2024-02-01', totaal_bedrag=200.00)



@pytest.mark.asyncio
async def test_kpis_tot_datum_basic(db):
    """Revenue up to a specific date, excluding later facturen."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2025-001', klant_id=kid,
                       datum='2025-02-10', totaal_bedrag=500.00,
                       status='verstuurd')
    await add_factuur(db, nummer='2025-002', klant_id=kid,
                       datum='2025-04-15', totaal_bedrag=700.00,
                       status='verstuurd')

    result = await get_kpis_tot_datum(db, jaar=2025, max_datum='2025-03-31')
    assert result['omzet'] == 500.00  # only Feb factuur


@pytest.mark.asyncio
async def test_kpis_tot_datum_includes_exact_date(db):
    """Factuur on exact max_datum is included."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2025-010', klant_id=kid,
                       datum='2025-03-15', totaal_bedrag=600.00,
                       status='verstuurd')

    result = await get_kpis_tot_datum(db, jaar=2025, max_datum='2025-03-15')
    assert result['omzet'] == 600.00


@pytest.mark.asyncio
async def test_kpis_tot_datum_excludes_concepts(db):
    """Concept facturen are excluded from YoY comparison."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2025-020', klant_id=kid,
                       datum='2025-02-01', totaal_bedrag=1000.00,
                       status='concept')
    await add_factuur(db, nummer='2025-021', klant_id=kid,
                       datum='2025-02-15', totaal_bedrag=500.00,
                       status='verstuurd')

    result = await get_kpis_tot_datum(db, jaar=2025, max_datum='2025-12-31')
    assert result['omzet'] == 500.00  # concept excluded


@pytest.mark.asyncio
async def test_kpis_tot_datum_includes_kosten(db):
    """Kosten are also filtered by max_datum."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2025-030', klant_id=kid,
                       datum='2025-01-15', totaal_bedrag=1000.00,
                       status='verstuurd')
    await add_uitgave(db, datum='2025-01-20', categorie='Kantoor',
                       omschrijving='Pen', bedrag=10.00)
    await add_uitgave(db, datum='2025-06-01', categorie='Kantoor',
                       omschrijving='Paper', bedrag=25.00)

    result = await get_kpis_tot_datum(db, jaar=2025, max_datum='2025-03-31')
    assert result['omzet'] == 1000.00
    assert result['kosten'] == 10.00  # only Jan uitgave



@pytest.mark.asyncio
async def test_omzet_per_maand_basic(db):
    """Monthly revenue breakdown returns 12-element list."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2025-040', klant_id=kid,
                       datum='2025-01-15', totaal_bedrag=1000.00,
                       status='verstuurd')
    await add_factuur(db, nummer='2025-041', klant_id=kid,
                       datum='2025-03-20', totaal_bedrag=500.00,
                       status='betaald')
    await add_factuur(db, nummer='2025-042', klant_id=kid,
                       datum='2025-03-25', totaal_bedrag=300.00,
                       status='verstuurd')

    months = await get_omzet_per_maand(db, jaar=2025)
    assert len(months) == 12
    assert months[0] == 1000.00  # Jan
    assert months[1] == 0        # Feb
    assert months[2] == 800.00   # Mar (500 + 300)
    assert all(m == 0 for m in months[3:])  # Apr-Dec


@pytest.mark.asyncio
async def test_omzet_per_maand_excludes_concepts(db):
    """Concept facturen excluded from monthly breakdown."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2025-050', klant_id=kid,
                       datum='2025-06-01', totaal_bedrag=1000.00,
                       status='concept')
    await add_factuur(db, nummer='2025-051', klant_id=kid,
                       datum='2025-06-15', totaal_bedrag=400.00,
                       status='verstuurd')

    months = await get_omzet_per_maand(db, jaar=2025)
    assert months[5] == 400.00  # Jun: concept excluded


@pytest.mark.asyncio
async def test_omzet_per_maand_empty_year(db):
    """Year with no facturen returns 12 zeros."""
    months = await get_omzet_per_maand(db, jaar=2025)
    assert months == [0] * 12



from database import update_klant, get_klanten, factuurnummer_exists


@pytest.mark.asyncio
async def test_update_klant_tarief(db):
    """Change tarief_uur, verify persisted AND other fields unchanged."""
    kid = await add_klant(db, naam="Testpraktijk", tarief_uur=77.50,
                          retour_km=52, adres="Testlaan 1")
    await update_klant(db, klant_id=kid, tarief_uur=85.00)

    klanten = await get_klanten(db)
    k = next(k for k in klanten if k.id == kid)
    assert k.tarief_uur == 85.00
    # Other fields unchanged
    assert k.naam == "Testpraktijk"
    assert k.retour_km == 52
    assert k.adres == "Testlaan 1"


@pytest.mark.asyncio
async def test_update_klant_email(db):
    """Change email, verify persisted."""
    kid = await add_klant(db, naam="EmailTest", tarief_uur=80,
                          email="old@example.com")
    await update_klant(db, klant_id=kid, email="new@example.com")

    klanten = await get_klanten(db)
    k = next(k for k in klanten if k.id == kid)
    assert k.email == "new@example.com"
    assert k.naam == "EmailTest"  # unchanged




@pytest.mark.asyncio
async def test_factuurnummer_exists_true(db):
    """Create factuur, verify exists returns True."""
    kid = await add_klant(db, naam="ExistsTest", tarief_uur=80)
    await add_factuur(db, nummer="2026-EX1", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=500)
    assert await factuurnummer_exists(db, nummer="2026-EX1") is True


@pytest.mark.asyncio
async def test_factuurnummer_exists_false(db):
    """Verify non-existent nummer returns False."""
    assert await factuurnummer_exists(db, nummer="9999-ZZZ") is False


# ── Bank-match dedup tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_matches_dedup_bank_id(db):
    """Two proposals sharing one bank_id → only first applied, second skipped."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    fid_a = await add_factuur(db, nummer='2026-DA', klant_id=kid,
                               datum='2026-01-10', totaal_bedrag=640.00,
                               status='verstuurd')
    fid_b = await add_factuur(db, nummer='2026-DB', klant_id=kid,
                               datum='2026-01-20', totaal_bedrag=640.00,
                               status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-01-25', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT id FROM banktransacties")
        bank_id = (await cur.fetchone())['id']

    # Craft two proposals pointing at the same bank_id (the ambiguous case)
    proposals = [
        MatchProposal(factuur_id=fid_a, bank_id=bank_id, delta=0.0,
                      confidence='low', match_type='bedrag',
                      bank_datum='2026-01-25'),
        MatchProposal(factuur_id=fid_b, bank_id=bank_id, delta=0.0,
                      confidence='low', match_type='bedrag',
                      bank_datum='2026-01-25'),
    ]
    count = await apply_factuur_matches(db, proposals)
    assert count == 1  # only one applied

    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT status FROM facturen WHERE id=?", (fid_a,))
        assert (await cur.fetchone())['status'] == 'betaald'
        cur = await conn.execute("SELECT status FROM facturen WHERE id=?", (fid_b,))
        assert (await cur.fetchone())['status'] == 'verstuurd'  # unchanged
        # Bank row linked to first factuur only
        cur = await conn.execute(
            "SELECT koppeling_id FROM banktransacties WHERE id=?", (bank_id,))
        assert (await cur.fetchone())['koppeling_id'] == fid_a


@pytest.mark.asyncio
async def test_apply_matches_dedup_factuur_id(db):
    """Two proposals sharing one factuur_id → only first applied."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    fid = await add_factuur(db, nummer='2026-DF', klant_id=kid,
                             datum='2026-01-10', totaal_bedrag=640.00,
                             status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-01-25', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': 'pay1', 'categorie': ''},
        {'datum': '2026-01-26', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': 'pay2', 'categorie': ''},
    ], csv_bestand='test.csv')

    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT id FROM banktransacties ORDER BY datum")
        rows = await cur.fetchall()
        bid1, bid2 = rows[0]['id'], rows[1]['id']

    proposals = [
        MatchProposal(factuur_id=fid, bank_id=bid1, delta=0.0,
                      confidence='high', match_type='bedrag',
                      bank_datum='2026-01-25'),
        MatchProposal(factuur_id=fid, bank_id=bid2, delta=0.0,
                      confidence='high', match_type='bedrag',
                      bank_datum='2026-01-26'),
    ]
    count = await apply_factuur_matches(db, proposals)
    assert count == 1

    async with get_db_ctx(db) as conn:
        # Only first bank row should be linked
        cur = await conn.execute(
            "SELECT koppeling_type FROM banktransacties WHERE id=?", (bid1,))
        assert (await cur.fetchone())['koppeling_type'] == 'factuur'
        cur = await conn.execute(
            "SELECT koppeling_type FROM banktransacties WHERE id=?", (bid2,))
        assert (await cur.fetchone())['koppeling_type'] == ''  # unlinked


@pytest.mark.asyncio
async def test_apply_matches_atomic_consistency(db):
    """After apply, every betaald factuur has a corresponding bank link."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    fid = await add_factuur(db, nummer='2026-AT', klant_id=kid,
                             datum='2026-01-10', totaal_bedrag=640.00,
                             status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-01-25', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT id FROM banktransacties")
        bank_id = (await cur.fetchone())['id']

    proposals = [
        MatchProposal(factuur_id=fid, bank_id=bank_id, delta=0.0,
                      confidence='high', match_type='bedrag',
                      bank_datum='2026-01-25'),
    ]
    await apply_factuur_matches(db, proposals)

    # Consistency check: betaald factuur must have a bank link
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT status FROM facturen WHERE id=?", (fid,))
        assert (await cur.fetchone())['status'] == 'betaald'
        cur = await conn.execute(
            "SELECT koppeling_type, koppeling_id FROM banktransacties WHERE id=?",
            (bank_id,))
        row = await cur.fetchone()
        assert row['koppeling_type'] == 'factuur'
        assert row['koppeling_id'] == fid


# ── Bank deletion revert tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_linked_reverts_factuur(db):
    """Deleting a linked bank txn reverts the factuur to verstuurd."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    fid = await add_factuur(db, nummer='2026-DL', klant_id=kid,
                             datum='2026-01-10', totaal_bedrag=640.00,
                             status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-01-25', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT id FROM banktransacties")
        bank_id = (await cur.fetchone())['id']

    # Apply match (factuur becomes betaald)
    proposals = [
        MatchProposal(factuur_id=fid, bank_id=bank_id, delta=0.0,
                      confidence='high', match_type='bedrag',
                      bank_datum='2026-01-25'),
    ]
    await apply_factuur_matches(db, proposals)

    # Delete the linked bank transaction
    deleted, reverted = await delete_banktransacties(db, transactie_ids=[bank_id])
    assert deleted == 1
    assert reverted == [fid]

    # Factuur should be back to verstuurd with cleared betaald_datum
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT status, betaald_datum FROM facturen WHERE id=?", (fid,))
        row = await cur.fetchone()
        assert row['status'] == 'verstuurd'
        assert row['betaald_datum'] == ''


@pytest.mark.asyncio
async def test_delete_unlinked_no_revert(db):
    """Deleting an unlinked bank txn does not affect any factuur."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    fid = await add_factuur(db, nummer='2026-UL', klant_id=kid,
                             datum='2026-01-10', totaal_bedrag=640.00,
                             status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-01-25', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT id FROM banktransacties")
        bank_id = (await cur.fetchone())['id']

    deleted, reverted = await delete_banktransacties(db, transactie_ids=[bank_id])
    assert deleted == 1
    assert reverted == []

    # Factuur still verstuurd
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT status FROM facturen WHERE id=?", (fid,))
        assert (await cur.fetchone())['status'] == 'verstuurd'


@pytest.mark.asyncio
async def test_bulk_delete_mixed_linked_unlinked(db):
    """Bulk delete: only linked facturen are reverted."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    fid = await add_factuur(db, nummer='2026-BM', klant_id=kid,
                             datum='2026-01-10', totaal_bedrag=640.00,
                             status='verstuurd')
    await add_banktransacties(db, [
        {'datum': '2026-01-25', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': 'linked payment', 'categorie': ''},
        {'datum': '2026-01-26', 'bedrag': 100.00, 'tegenpartij': 'Other',
         'omschrijving': 'unrelated', 'categorie': ''},
    ], csv_bestand='test.csv')

    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT id FROM banktransacties ORDER BY datum")
        rows = await cur.fetchall()
        bid_linked, bid_unlinked = rows[0]['id'], rows[1]['id']

    # Link only the first bank txn
    proposals = [
        MatchProposal(factuur_id=fid, bank_id=bid_linked, delta=0.0,
                      confidence='high', match_type='bedrag',
                      bank_datum='2026-01-25'),
    ]
    await apply_factuur_matches(db, proposals)

    # Bulk delete both
    deleted, reverted = await delete_banktransacties(
        db, transactie_ids=[bid_linked, bid_unlinked])
    assert deleted == 2
    assert reverted == [fid]

    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT status FROM facturen WHERE id=?", (fid,))
        assert (await cur.fetchone())['status'] == 'verstuurd'


# === L1.1 (A1): privé filter on aangifte sums ===
# Bank-tx flagged genegeerd=1 must NOT show up in aangifte kosten totals,
# even if a categorised uitgave is linked. Cash uitgaven (bank_tx_id IS NULL)
# stay counted unconditionally.

@pytest.mark.asyncio
async def test_get_uitgaven_per_categorie_excludes_genegeerd_bank(db):
    """A debit-uitgave linked to a privé-marked bank-tx must not be summed."""
    # Bank debit, uitgave linked.
    await add_banktransacties(db, [
        {'datum': '2026-03-01', 'bedrag': -50, 'tegenpartij': 'KPN',
         'omschrijving': 'mobiel', 'categorie': ''},
    ], csv_bestand='march.csv')
    bank_id = (await get_banktransacties(db))[0].id
    await add_uitgave(
        db, datum='2026-03-01', categorie='Telefoon/KPN',
        omschrijving='KPN abonnement', bedrag=50.00, bank_tx_id=bank_id)
    # Sanity: the categorie shows up before flipping privé.
    pre = await get_uitgaven_per_categorie(db, jaar=2026)
    pre_cats = {r['categorie']: r['totaal'] for r in pre}
    assert pre_cats.get('Telefoon/KPN') == 50.00

    # User flips bank-tx to privé.
    await mark_banktx_genegeerd(db, bank_tx_id=bank_id, genegeerd=1)

    # Now the categorie must be gone (totaal would have been 0; we GROUP BY
    # categorie so it should not appear at all).
    post = await get_uitgaven_per_categorie(db, jaar=2026)
    post_cats = {r['categorie']: r['totaal'] for r in post}
    assert 'Telefoon/KPN' not in post_cats, (
        "privé-marked bank-tx is still leaking into aangifte kosten totaal"
    )


@pytest.mark.asyncio
async def test_get_uitgaven_per_categorie_includes_cash_uitgave(db):
    """Cash uitgaven (bank_tx_id IS NULL) are unaffected by the privé filter."""
    await add_uitgave(
        db, datum='2026-04-01', categorie='Bankkosten',
        omschrijving='cash betaling', bedrag=12.50)
    res = await get_uitgaven_per_categorie(db, jaar=2026)
    cats = {r['categorie']: r['totaal'] for r in res}
    assert cats.get('Bankkosten') == 12.50


@pytest.mark.asyncio
async def test_get_uitgaven_per_categorie_includes_non_genegeerd_bank(db):
    """A debit-uitgave linked to a normal (genegeerd=0) bank-tx is still summed."""
    await add_banktransacties(db, [
        {'datum': '2026-05-01', 'bedrag': -25, 'tegenpartij': 'KPN',
         'omschrijving': 'mobiel', 'categorie': ''},
    ], csv_bestand='may.csv')
    bank_id = (await get_banktransacties(db))[0].id
    await add_uitgave(
        db, datum='2026-05-01', categorie='Telefoon/KPN',
        omschrijving='KPN abonnement', bedrag=25.00, bank_tx_id=bank_id)
    res = await get_uitgaven_per_categorie(db, jaar=2026)
    cats = {r['categorie']: r['totaal'] for r in res}
    assert cats.get('Telefoon/KPN') == 25.00


@pytest.mark.asyncio
async def test_get_representatie_totaal_excludes_genegeerd_bank(db):
    """Representatie totaal must apply the same privé filter."""
    # Cash representatie (always counted)
    await add_uitgave(
        db, datum='2026-01-10', categorie='Representatie',
        omschrijving='Lunch contant', bedrag=30.00)
    # Bank-linked representatie that gets flipped to privé.
    await add_banktransacties(db, [
        {'datum': '2026-02-15', 'bedrag': -100, 'tegenpartij': 'Restaurant',
         'omschrijving': 'lunch', 'categorie': ''},
    ], csv_bestand='feb.csv')
    bank_id = (await get_banktransacties(db))[0].id
    await add_uitgave(
        db, datum='2026-02-15', categorie='Representatie',
        omschrijving='Lunch zakelijk?', bedrag=100.00, bank_tx_id=bank_id)
    # Pre-flip total = 130.
    assert await get_representatie_totaal(db, jaar=2026) == 130.00
    # Flip privé — only the cash €30 should remain.
    await mark_banktx_genegeerd(db, bank_tx_id=bank_id, genegeerd=1)
    assert await get_representatie_totaal(db, jaar=2026) == 30.00


# ---------------------------------------------------------------------------
# B1 — get_kpis / get_kpis_tot_datum / get_data_counts: privé/sign filter op uitgaven
# ---------------------------------------------------------------------------
# Round-2 review introduceerde ZICHTBARE_ZAKELIJKE_UITGAVE_FILTER op
# get_uitgaven_per_categorie, get_representatie_totaal, get_investeringen,
# get_investeringen_voor_afschrijving — maar de dashboard-KPI helpers werden
# gemist. Deze tests verifiëren dat de filter nu uniform toegepast is.


@pytest.mark.asyncio
async def test_get_kpis_excludes_prive_flagged_banktx_uitgaven(db):
    """B1: privé-gemarkeerde banktx + linked uitgave moet NIET in dashboard
    kosten meetellen. Omdat /kosten ze terecht uitsluit en dashboard moet
    consistent zijn."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2026-001", klant_id=kid,
                      datum="2026-01-15", totaal_bedrag=1000, status='betaald')
    # Bank-debit van -100 (zakelijk); maak uitgave; flip dan naar privé
    await add_banktransacties(db, [
        {'datum': '2026-01-10', 'bedrag': -100.0,
         'tegenpartij': 'Vendor', 'omschrijving': 'X', 'categorie': ''},
    ], csv_bestand='t.csv')
    txns = await get_banktransacties(db, jaar=2026)
    bank_id = txns[0].id
    uid = await ensure_uitgave_for_banktx(
        db, bank_tx_id=bank_id, categorie='Bankkosten')
    assert uid is not None

    kpis = await get_kpis(db, jaar=2026)
    assert kpis['kosten'] == 100, "uitgave moet meetellen voor we 'm privé maken"

    # Markeer privé — uitgave moet uit kosten verdwijnen
    await mark_banktx_genegeerd(db, bank_tx_id=bank_id, genegeerd=1)
    kpis = await get_kpis(db, jaar=2026)
    assert kpis['kosten'] == 0, (
        "Privé-gemarkeerde banktx-uitgave mag niet in get_kpis kosten zitten")


@pytest.mark.asyncio
async def test_get_kpis_excludes_uitgaven_linked_to_positive_banktx(db):
    """B1: een uitgave die per ongeluk gekoppeld is aan een POSITIVE
    banktx (refund/teruggave) is een phantom — mag niet als zakelijke
    kost meetellen. Test gebruik: uitgave met bedrag>0 op zelfde key
    als get_uitgaven_per_categorie hem zou skippen."""
    await add_banktransacties(db, [
        # Positive bedrag = credit (geen kost!)
        {'datum': '2026-02-05', 'bedrag': 50.0,
         'tegenpartij': 'Refund Co', 'omschrijving': 'teruggave',
         'categorie': ''},
    ], csv_bestand='t.csv')
    txns = await get_banktransacties(db, jaar=2026)
    bank_id = txns[0].id
    # Lazy-create uitgave gekoppeld aan deze positive — phantom-flow
    await ensure_uitgave_for_banktx(
        db, bank_tx_id=bank_id, categorie='Bankkosten')

    kpis = await get_kpis(db, jaar=2026)
    assert kpis['kosten'] == 0, (
        "Uitgave gekoppeld aan positieve banktx mag niet meetellen")


@pytest.mark.asyncio
async def test_get_kpis_includes_cash_uitgaven(db):
    """B1: cash uitgaven (bank_tx_id IS NULL) blijven gewoon meetellen."""
    await add_uitgave(db, datum="2026-01-10", categorie="Bankkosten",
                      omschrijving="Cash bonnetje", bedrag=42.0)
    kpis = await get_kpis(db, jaar=2026)
    assert kpis['kosten'] == 42.0


@pytest.mark.asyncio
async def test_get_kpis_tot_datum_excludes_prive(db):
    """B1: zelfde filter ook in get_kpis_tot_datum."""
    await add_banktransacties(db, [
        {'datum': '2026-03-10', 'bedrag': -75.0,
         'tegenpartij': 'V', 'omschrijving': 'x', 'categorie': ''},
    ], csv_bestand='t.csv')
    txns = await get_banktransacties(db, jaar=2026)
    bank_id = txns[0].id
    await ensure_uitgave_for_banktx(
        db, bank_tx_id=bank_id, categorie='Telefoon/KPN')
    await mark_banktx_genegeerd(db, bank_tx_id=bank_id, genegeerd=1)

    out = await get_kpis_tot_datum(
        db, jaar=2026, max_datum='2026-12-31')
    assert out['kosten'] == 0, (
        "get_kpis_tot_datum moet privé-banktx ook uitsluiten")


@pytest.mark.asyncio
async def test_get_data_counts_excludes_prive_from_uitgaven_count(db):
    """B1: get_data_counts.n_uitgaven moet zelfde filter gebruiken zodat
    'aantal uitgaven' het cijfer matcht dat /kosten toont."""
    # Cash uitgave
    await add_uitgave(db, datum="2026-01-10", categorie="Cash",
                      omschrijving="X", bedrag=10)
    # Bank-uitgave die we privé maken
    await add_banktransacties(db, [
        {'datum': '2026-01-15', 'bedrag': -50.0,
         'tegenpartij': 'V', 'omschrijving': 'x', 'categorie': ''},
    ], csv_bestand='t.csv')
    txns = await get_banktransacties(db, jaar=2026)
    bid = txns[0].id
    await ensure_uitgave_for_banktx(db, bank_tx_id=bid, categorie='Bankkosten')
    await mark_banktx_genegeerd(db, bank_tx_id=bid, genegeerd=1)

    counts = await get_data_counts(db, jaar=2026)
    assert counts['n_uitgaven'] == 1, (
        "n_uitgaven moet alleen zichtbare zakelijke uitgaven tellen "
        "(cash + niet-privé bank-debits)")


# ---------------------------------------------------------------------------
# B7 + B18 — Werkdag-queries: tarief>0 + datum<=today filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_werkdagen_ongefactureerd_summary_returns_aantal_key(db):
    """Backward-compat: dashboard verwacht return-key 'aantal' (niet 'count').
    Codex round-4 vond dat in originele plan-rewrite ik 'count' gebruikte."""
    result = await get_werkdagen_ongefactureerd_summary(db, jaar=2026)
    assert 'aantal' in result, "key moet 'aantal' zijn, niet 'count'"
    assert 'bedrag' in result


@pytest.mark.asyncio
async def test_get_werkdagen_ongefactureerd_summary_excludes_future_dates(
        db, monkeypatch):
    """B7: werkdag in de toekomst (geplande dienst) telt niet mee in banner.

    Codex round-3: monkeypatch _date.today naar fixed midyear date zodat
    de test niet flaky is rond januari/december (waar past/future
    over jaargrenzen lopen).
    """
    import database
    fixed_today = date(2026, 6, 15)
    monkeypatch.setattr(database, '_today_iso',
                         lambda: fixed_today.isoformat())

    kid = await add_klant(db, naam="Test", tarief_uur=80)
    # Past en future binnen 2026
    await add_werkdag(db, datum='2026-05-15', klant_id=kid,
                      uren=8, tarief=80, urennorm=1)  # past
    await add_werkdag(db, datum='2026-07-15', klant_id=kid,
                      uren=8, tarief=80, urennorm=1)  # future

    result = await get_werkdagen_ongefactureerd_summary(db, jaar=2026)
    assert result['aantal'] == 1, (
        "Toekomstige werkdag mag niet als 'ongefactureerd' tellen")


@pytest.mark.asyncio
async def test_get_werkdagen_ongefactureerd_summary_excludes_zero_tarief(db):
    """B7: werkdagen met tarief=0 (ACHTERWACHT/CONGRES/OPLEIDING) tellen
    nooit als factureerbaar — die zijn intern voor uren-criterium."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    # Reguliere werkdag (tarief>0)
    await add_werkdag(db, datum="2026-01-10", klant_id=kid,
                      uren=8, tarief=80, urennorm=1)
    # ACHTERWACHT (tarief=0)
    await add_werkdag(db, datum="2026-01-11", klant_id=kid,
                      uren=24, tarief=0, urennorm=0)

    result = await get_werkdagen_ongefactureerd_summary(db, jaar=2026)
    assert result['aantal'] == 1, "tarief=0 werkdag niet meetellen"


@pytest.mark.asyncio
async def test_get_werkdagen_ongefactureerd_excludes_future_and_zero_tarief(
        db, monkeypatch):
    """B18: get_werkdagen_ongefactureerd (de lijst-helper) moet zelfde filter
    toepassen als de summary."""
    import database
    fixed_today = date(2026, 6, 15)
    monkeypatch.setattr(database, '_today_iso',
                         lambda: fixed_today.isoformat())
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_werkdag(db, datum='2026-05-15', klant_id=kid,
                      uren=8, tarief=80, urennorm=1)
    await add_werkdag(db, datum='2026-07-15', klant_id=kid,
                      uren=8, tarief=80, urennorm=1)
    await add_werkdag(db, datum='2026-05-15', klant_id=kid,
                      uren=24, tarief=0, urennorm=0)

    result = await get_werkdagen_ongefactureerd(db)
    assert len(result) == 1, (
        "alleen past werkdag met tarief>0 mag terugkomen")


@pytest.mark.asyncio
async def test_get_werkdagen_ongefactureerd_klant_id_optional(db, monkeypatch):
    """B18: klant_id=None geeft alle factureerbare werkdagen."""
    import database
    fixed_today = date(2026, 6, 15)
    monkeypatch.setattr(database, '_today_iso',
                         lambda: fixed_today.isoformat())
    kid1 = await add_klant(db, naam="A", tarief_uur=80)
    kid2 = await add_klant(db, naam="B", tarief_uur=80)
    await add_werkdag(db, datum='2026-06-05', klant_id=kid1,
                      uren=8, tarief=80, urennorm=1)
    await add_werkdag(db, datum='2026-06-05', klant_id=kid2,
                      uren=8, tarief=80, urennorm=1)

    # Geen klant_id → alle klanten
    all_rows = await get_werkdagen_ongefactureerd(db)
    assert len(all_rows) == 2

    # Specifieke klant
    klant1_only = await get_werkdagen_ongefactureerd(db, klant_id=kid1)
    assert len(klant1_only) == 1


@pytest.mark.asyncio
async def test_get_werkdagen_ongefactureerd_returns_klant_naam(
        db, monkeypatch):
    """B18: JOIN klanten moet behouden — _row_to_werkdag verwacht klant_naam."""
    import database
    fixed_today = date(2026, 6, 15)
    monkeypatch.setattr(database, '_today_iso',
                         lambda: fixed_today.isoformat())
    kid = await add_klant(db, naam="Praktijk Acme", tarief_uur=80)
    await add_werkdag(db, datum='2026-06-10', klant_id=kid,
                      uren=8, tarief=80, urennorm=1)

    rows = await get_werkdagen_ongefactureerd(db, klant_id=kid)
    assert len(rows) == 1
    assert rows[0].klant_naam == 'Praktijk Acme'


# ---------------------------------------------------------------------------
# Codex round-3 follow-up coverage: legacy NULL genegeerd + tot_datum positive
# ---------------------------------------------------------------------------


# NB: codex round-3 vroeg om een 'NULL genegeerd legacy' test, maar het
# huidige schema (migratie 24+) heeft `genegeerd INTEGER NOT NULL DEFAULT 0`.
# NULL kan dus niet voorkomen. COALESCE in ZICHTBARE_ZAKELIJKE_UITGAVE_FILTER
# blijft als forward-compatible defensieve guard (kost niets).


@pytest.mark.asyncio
async def test_get_kpis_tot_datum_excludes_positive_banktx_uitgaven(db):
    """B1 — get_kpis_tot_datum moet ook positieve-banktx-linked uitgaven
    uitsluiten (parity met get_kpis)."""
    await add_banktransacties(db, [
        {'datum': '2026-04-05', 'bedrag': 25.0,  # positive = credit
         'tegenpartij': 'Refund', 'omschrijving': 'x', 'categorie': ''},
    ], csv_bestand='t.csv')
    txns = await get_banktransacties(db, jaar=2026)
    bid = txns[0].id
    await ensure_uitgave_for_banktx(db, bank_tx_id=bid, categorie='Bankkosten')

    out = await get_kpis_tot_datum(db, jaar=2026, max_datum='2026-12-31')
    assert out['kosten'] == 0


# ---------------------------------------------------------------------------
# B5 — VA kenmerk normalisatie
# ---------------------------------------------------------------------------
# Belastingdienst betalingskenmerken zijn 16 digits zonder separators per
# spec, maar copy-paste uit BD-portaal of bepaalde bank-CSV's voegt soms
# punten/spaties toe. Parser deed `kenmerk[10:12]` direct op raw string —
# kenmerken met separators vielen in 'unmatched'.


@pytest.mark.asyncio
async def test_va_kenmerk_with_dots_routes_correctly(db):
    """B5: kenmerk met punten moet normaliseren en correct splitten.
    BELASTINGDIENST_IBAN debit met kenmerk waar [10:12] (na strippen) >= 50."""
    from database import BELASTINGDIENST_IBAN
    await add_banktransacties(db, [
        # Raw kenmerk met dots: '1234567890512345' (digits only)
        # met separators: '1234.5678.9051.2345'
        # [10:12] na strip = '51' → ZVW
        {'datum': '2026-03-10', 'bedrag': -1000.0,
         'tegenrekening': BELASTINGDIENST_IBAN,
         'tegenpartij': 'BD', 'omschrijving': 'voorlopige aanslag',
         'betalingskenmerk': '1234.5678.9051.2345'},
    ], csv_bestand='t.csv')

    out = await get_va_betalingen(db, jaar=2026)
    assert out['zvw_betaald'] == 1000, (
        "Kenmerk met dots moet normaliseren naar ZVW (split-digits=51)")
    assert out['ib_betaald'] == 0


@pytest.mark.asyncio
async def test_va_kenmerk_with_spaces_routes_correctly(db):
    """B5: kenmerk met spaties → IB (split-digits 23 < 50)."""
    from database import BELASTINGDIENST_IBAN
    await add_banktransacties(db, [
        # '1234 5678 9012 3456' → digits '1234567890123456' → [10:12]='23' → IB
        {'datum': '2026-04-10', 'bedrag': -800.0,
         'tegenrekening': BELASTINGDIENST_IBAN,
         'tegenpartij': 'BD', 'omschrijving': 'va',
         'betalingskenmerk': '1234 5678 9012 3456'},
    ], csv_bestand='t.csv')

    out = await get_va_betalingen(db, jaar=2026)
    assert out['ib_betaald'] == 800
    assert out['zvw_betaald'] == 0


@pytest.mark.asyncio
async def test_va_kenmerk_clean_format_still_works(db):
    """B5 backward-compat: 16-digit zonder separators blijft werken."""
    from database import BELASTINGDIENST_IBAN
    await add_banktransacties(db, [
        {'datum': '2026-05-10', 'bedrag': -500.0,
         'tegenrekening': BELASTINGDIENST_IBAN,
         'tegenpartij': 'BD', 'omschrijving': 'va',
         'betalingskenmerk': '1234567890512345'},  # [10:12]='51' → ZVW
    ], csv_bestand='t.csv')

    out = await get_va_betalingen(db, jaar=2026)
    assert out['zvw_betaald'] == 500


@pytest.mark.asyncio
async def test_get_data_counts_excludes_investeringen_from_n_uitgaven(db):
    """B1 codex round-3: n_uitgaven moet investeringen niet meetellen
    (consistent met get_kpis kosten die ook is_investering=0 filtert)."""
    await add_uitgave(db, datum="2026-01-10", categorie="Bankkosten",
                      omschrijving="Cash kost", bedrag=10)
    await add_uitgave(db, datum="2026-02-10", categorie="Apparatuur",
                      omschrijving="Laptop", bedrag=2000, is_investering=1,
                      levensduur_jaren=5)
    counts = await get_data_counts(db, jaar=2026)
    assert counts['n_uitgaven'] == 1, (
        "n_uitgaven moet investeringen uitsluiten")


@pytest.mark.asyncio
async def test_get_nog_te_factureren_excludes_future_werkdagen(
        db, monkeypatch):
    """Q7 (codex round-4): get_nog_te_factureren had wel tarief>0 filter
    maar geen datum<=today filter — toekomstige werkdagen telden mee
    in 'nog te factureren' bedrag."""
    import database
    fixed_today = date(2026, 6, 15)
    monkeypatch.setattr(database, '_today_iso',
                         lambda: fixed_today.isoformat())
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_werkdag(db, datum='2026-06-05', klant_id=kid,
                      uren=8, tarief=80, urennorm=1)  # past, 8*80 = 640
    await add_werkdag(db, datum='2026-07-05', klant_id=kid,
                      uren=8, tarief=80, urennorm=1)  # future, mag niet tellen

    bedrag = await get_nog_te_factureren(db, jaar=2026)
    assert bedrag == 640, (
        "Future werkdag mag niet meetellen in nog te factureren")


# ---------------------------------------------------------------------------
# B13 — get_omzet_per_maand_tot_datum: real date-cutoff query
# ---------------------------------------------------------------------------
# Eerder gebruikte de cumulatieve grafiek voor vorig jaar de volle 12
# maanden — visueel inconsistent met day-precise YoY badge die YTD-vs-YTD
# rekent. Pro-rata cap helper was wiskundig fout voor lumpy data; juiste
# aanpak is een echte date-range query.


@pytest.mark.asyncio
async def test_get_omzet_per_maand_tot_datum_returns_12_months(db):
    """Output is altijd 12 entries (jan..dec)."""
    result = await get_omzet_per_maand_tot_datum(
        db, jaar=2025, max_datum='2025-12-31')
    assert len(result) == 12


@pytest.mark.asyncio
async def test_get_omzet_per_maand_tot_datum_april_30_cuts_correctly(db):
    """Cutoff 30-april bevatten mei-dec 0; jan-april alleen
    facturen tot en met 30-april (geen pro-rata)."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer='2025-001', klant_id=kid,
                      datum='2025-04-15', totaal_bedrag=1000,
                      status='betaald')
    await add_factuur(db, nummer='2025-002', klant_id=kid,
                      datum='2025-04-30', totaal_bedrag=500,
                      status='betaald')
    await add_factuur(db, nummer='2025-003', klant_id=kid,
                      datum='2025-05-01', totaal_bedrag=999,  # NA cutoff
                      status='betaald')

    result = await get_omzet_per_maand_tot_datum(
        db, jaar=2025, max_datum='2025-04-30')
    # april (index 3) = 1500
    assert result[3] == 1500
    # alle andere maanden 0
    assert all(r == 0 for i, r in enumerate(result) if i != 3)


@pytest.mark.asyncio
async def test_get_omzet_per_maand_tot_datum_excludes_concept(db):
    """Concept facturen tellen niet (consistent met get_kpis/get_omzet_*)."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer='2025-001', klant_id=kid,
                      datum='2025-03-15', totaal_bedrag=1000,
                      status='concept')

    result = await get_omzet_per_maand_tot_datum(
        db, jaar=2025, max_datum='2025-12-31')
    assert all(r == 0 for r in result)


@pytest.mark.asyncio
async def test_get_omzet_per_maand_tot_datum_dec_31_keeps_full_year(db):
    """Cutoff = jaar-eind = volledige jaar."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer='2025-001', klant_id=kid,
                      datum='2025-06-15', totaal_bedrag=200,
                      status='betaald')
    await add_factuur(db, nummer='2025-002', klant_id=kid,
                      datum='2025-12-30', totaal_bedrag=300,
                      status='betaald')

    result = await get_omzet_per_maand_tot_datum(
        db, jaar=2025, max_datum='2025-12-31')
    assert result[5] == 200  # juni
    assert result[11] == 300  # december


@pytest.mark.asyncio
async def test_get_omzet_per_maand_tot_datum_clamps_max_datum_to_jaar_end(db):
    """B13 codex round-3: max_datum > jaar-eind moet worden geclampt naar
    jaar-12-31. Anders zouden facturen uit volgend jaar door substr-based
    GROUP BY in dezelfde maand-slots geteld worden."""
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer='2025-001', klant_id=kid,
                      datum='2025-01-15', totaal_bedrag=100,
                      status='betaald')
    # 2026 factuur — moet NIET als januari-2025 geteld worden ondanks
    # de te hoge max_datum.
    await add_factuur(db, nummer='2026-001', klant_id=kid,
                      datum='2026-01-15', totaal_bedrag=999,
                      status='betaald')

    result = await get_omzet_per_maand_tot_datum(
        db, jaar=2025, max_datum='2026-01-15')  # te hoge cutoff
    assert result[0] == 100, (
        "Januari-2025 = 100; 2026-factuur mag niet meegeteld worden")


# === Sprint I T1.1: migratie 40 — VA termijn-kolommen ===

def _minimal_fiscale_params_kwargs(jaar: int) -> dict:
    """Minimal kwargs that satisfy upsert_fiscale_params required keys.

    Used in Sprint I T1.1 tests to verify VA-termijnen preservation
    without coupling tests to fiscal-data semantics.
    """
    return dict(
        jaar=jaar,
        zelfstandigenaftrek=0, mkb_vrijstelling_pct=0,
        kia_ondergrens=0, kia_bovengrens=0, kia_pct=0,
        km_tarief=0.23, schijf1_grens=0, schijf1_pct=0,
        schijf2_grens=0, schijf2_pct=0, schijf3_pct=0,
        ahk_max=0, ahk_afbouw_pct=0, ahk_drempel=0, ak_max=0,
        zvw_pct=0, zvw_max_grondslag=0, repr_aftrek_pct=80,
        ew_forfait_pct=0.35, villataks_grens=1_350_000,
        wet_hillen_pct=0, urencriterium=1225,
        pvv_premiegrondslag=0, arbeidskorting_brackets='',
        pvv_aow_pct=17.90, pvv_anw_pct=0.10, pvv_wlz_pct=9.65,
        box3_heffingsvrij_vermogen=57000,
        box3_rendement_bank_pct=1.03, box3_rendement_overig_pct=6.17,
        box3_rendement_schuld_pct=2.46, box3_tarief_pct=36,
        box3_drempel_schulden=3700,
    )


@pytest.mark.asyncio
async def test_migratie_40_va_termijnen_default_11(db):
    """Migratie 40 voegt 2 termijn-kolommen toe met default 11."""
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("PRAGMA table_info(fiscale_params)")
        cols = {row['name']: row for row in await cur.fetchall()}
    assert 'voorlopige_aanslag_ib_termijnen' in cols
    assert 'voorlopige_aanslag_zvw_termijnen' in cols
    assert int(cols['voorlopige_aanslag_ib_termijnen']['dflt_value']) == 11
    assert int(cols['voorlopige_aanslag_zvw_termijnen']['dflt_value']) == 11


@pytest.mark.asyncio
async def test_update_ib_inputs_preserves_va_termijnen(db):
    """update_ib_inputs zonder termijnen-kwargs laat termijn-velden ongemoeid."""
    await upsert_fiscale_params(
        db_path=db,
        **_minimal_fiscale_params_kwargs(2026),
        voorlopige_aanslag_ib_termijnen=8,
        voorlopige_aanslag_zvw_termijnen=12,
    )
    await update_ib_inputs(db_path=db, jaar=2026, voorlopige_aanslag_betaald=9600)
    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_ib_termijnen == 8
    assert fp.voorlopige_aanslag_zvw_termijnen == 12


@pytest.mark.asyncio
async def test_upsert_fiscale_params_preserves_va_termijnen(db):
    """upsert zonder termijnen-kwargs leest existing en behoudt waarde."""
    await upsert_fiscale_params(
        db_path=db,
        **_minimal_fiscale_params_kwargs(2026),
        voorlopige_aanslag_ib_termijnen=6,
        voorlopige_aanslag_zvw_termijnen=10,
    )
    # Re-upsert zonder termijnen-kwargs — moet preserve'n
    await upsert_fiscale_params(
        db_path=db,
        **_minimal_fiscale_params_kwargs(2026),
    )
    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_ib_termijnen == 6
    assert fp.voorlopige_aanslag_zvw_termijnen == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", [0, 13, 1.5, True, False])
async def test_upsert_fiscale_params_rejects_bad_va_termijnen(db, bad_value):
    """upsert weigert termijnen buiten 1-12 of niet-integer (incl. bool)."""
    with pytest.raises(ValueError, match="termijnen moet een integer 1-12"):
        await upsert_fiscale_params(
            db_path=db,
            **_minimal_fiscale_params_kwargs(2026),
            voorlopige_aanslag_ib_termijnen=bad_value,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_value", [0, 13, 1.5, True])
async def test_update_ib_inputs_rejects_bad_va_termijnen(db, bad_value):
    """update_ib_inputs weigert termijnen buiten 1-12 of niet-integer."""
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))
    with pytest.raises(ValueError, match="termijnen moet een integer 1-12"):
        await update_ib_inputs(
            db_path=db, jaar=2026,
            voorlopige_aanslag_ib_termijnen=bad_value)


@pytest.mark.asyncio
async def test_upsert_fiscale_params_explicit_none_preserves_va_termijnen(db):
    """Expliciete None in kwargs gedraagt zich als preserve, NIET als NULL-write.

    Regressie-guard: zonder deze fallback zou de NOT NULL kolom op NULL gezet
    worden via kwargs.get(..., default) (None is een geldige value in kwargs).
    """
    await upsert_fiscale_params(
        db_path=db,
        **_minimal_fiscale_params_kwargs(2026),
        voorlopige_aanslag_ib_termijnen=5,
        voorlopige_aanslag_zvw_termijnen=9,
    )
    await upsert_fiscale_params(
        db_path=db,
        **_minimal_fiscale_params_kwargs(2026),
        voorlopige_aanslag_ib_termijnen=None,
        voorlopige_aanslag_zvw_termijnen=None,
    )
    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_ib_termijnen == 5
    assert fp.voorlopige_aanslag_zvw_termijnen == 9


@pytest.mark.asyncio
async def test_update_ib_inputs_writes_va_termijnen(db):
    """update_ib_inputs roundtrip: termijnen kwargs persisteren."""
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))
    await update_ib_inputs(
        db_path=db, jaar=2026,
        voorlopige_aanslag_ib_termijnen=4,
        voorlopige_aanslag_zvw_termijnen=7)
    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_ib_termijnen == 4
    assert fp.voorlopige_aanslag_zvw_termijnen == 7


# === Sprint J T1.1: migratie 41 — voorlopige_aanslagen tabel ===


from dataclasses import dataclass
from datetime import date as _date_cls


@dataclass(frozen=True)
class _FakeParsed:
    """Duck-typed stand-in voor services.va_parser.ParsedBeschikking.

    Used in T1.1 tests vóór services/va_parser.py bestaat (T1.2). Houd
    veldnamen + types EXACT in sync met de echte ParsedBeschikking
    dataclass — process_voorlopige_aanslag_upload leest deze attributen.
    """
    jaar: int
    soort: str
    aanslagnummer: str
    dagtekening: _date_cls
    bedrag: float
    betalingskenmerk: str
    termijnen: int


async def _add_va_doc(db_path, jaar: int, soort: str = 'ib') -> int:
    """Insert een aangifte_documenten-rij die VA-helpers kunnen gebruiken."""
    from database import add_aangifte_document
    return await add_aangifte_document(
        db_path=db_path, jaar=jaar, categorie='voorlopige_aanslag',
        documenttype=f'va_{soort}_beschikking',
        bestandsnaam=f'VA_{soort}_{jaar}.pdf',
        bestandspad=f'/data/aangifte/{jaar}/voorlopige_aanslag/VA_{soort}.pdf',
        upload_datum=f'{jaar}-01-31',
    )


@pytest.mark.asyncio
async def test_migratie_41_voorlopige_aanslagen_table_schema(db):
    """Migratie 41 maakt voorlopige_aanslagen-tabel + partial unique index."""
    from database import get_db_ctx
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("PRAGMA table_info(voorlopige_aanslagen)")
        cols = {r['name']: r for r in await cur.fetchall()}
    # Required columns met juiste NOT NULL + defaults
    for col in ('id', 'jaar', 'soort', 'document_id', 'aanslagnummer',
                'dagtekening', 'bedrag', 'betalingskenmerk',
                'termijnen', 'is_active', 'created_at'):
        assert col in cols, f"missing column {col}"
    assert cols['termijnen']['notnull'] == 1
    assert int(cols['termijnen']['dflt_value']) == 11
    assert cols['is_active']['notnull'] == 1
    assert int(cols['is_active']['dflt_value']) == 1

    # Partial unique index aanwezig met WHERE-clause
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='index' AND name='idx_va_active'")
        row = await cur.fetchone()
    assert row is not None
    assert 'is_active = 1' in row['sql']
    assert '(jaar, soort)' in row['sql']

    # CHECK constraints werken: soort ∈ {'ib','zvw'}, bedrag>=0,
    # termijnen 1-12. Probeer een bad-row in te voegen — moet falen.
    import aiosqlite
    docid = await _add_va_doc(db, 2026, 'ib')
    docid2 = await _add_va_doc(db, 2026, 'ib')
    async with get_db_ctx(db) as conn:
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                """INSERT INTO voorlopige_aanslagen
                   (jaar, soort, document_id, aanslagnummer, dagtekening,
                    bedrag, betalingskenmerk, termijnen, is_active)
                   VALUES (?, 'andere', ?, ?, ?, ?, ?, ?, 1)""",
                (2026, docid, 'X.1', '2026-01-31', 100.0, '0' * 16, 11),
            )
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                """INSERT INTO voorlopige_aanslagen
                   (jaar, soort, document_id, aanslagnummer, dagtekening,
                    bedrag, betalingskenmerk, termijnen, is_active)
                   VALUES (?, 'ib', ?, ?, ?, ?, ?, ?, 1)""",
                (2026, docid, 'X.2', '2026-01-31', -5.0, '0' * 16, 11),
            )
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                """INSERT INTO voorlopige_aanslagen
                   (jaar, soort, document_id, aanslagnummer, dagtekening,
                    bedrag, betalingskenmerk, termijnen, is_active)
                   VALUES (?, 'ib', ?, ?, ?, ?, ?, ?, 1)""",
                (2026, docid, 'X.3', '2026-01-31', 100.0, '0' * 16, 13),
            )

    # UNIQUE(document_id) — Codex round-3 fix: één beschikking per source-PDF.
    # Garandeert dat delete-cleanup deterministisch is (LEFT JOIN fetchone
    # is exhaustief). Twee VA-rows met zelfde document_id moet falen.
    async with get_db_ctx(db) as conn:
        await conn.execute(
            """INSERT INTO voorlopige_aanslagen
               (jaar, soort, document_id, aanslagnummer, dagtekening,
                bedrag, betalingskenmerk, termijnen, is_active)
               VALUES (?, 'ib', ?, ?, ?, ?, ?, ?, 1)""",
            (2026, docid, 'OK.1', '2026-01-31', 100.0, '0' * 16, 11))
        await conn.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                """INSERT INTO voorlopige_aanslagen
                   (jaar, soort, document_id, aanslagnummer, dagtekening,
                    bedrag, betalingskenmerk, termijnen, is_active)
                   VALUES (?, 'ib', ?, ?, ?, ?, ?, ?, 0)""",
                (2026, docid, 'OK.2', '2026-01-31', 100.0, '0' * 16, 11))


@pytest.mark.asyncio
async def test_process_voorlopige_aanslag_upload_inserts_and_syncs_fp(db):
    """Happy path: nieuwe upload INSERT + fp.voorlopige_aanslag_betaald sync."""
    from database import (
        process_voorlopige_aanslag_upload, get_active_voorlopige_aanslag,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))
    docid = await _add_va_doc(db, 2026, 'ib')

    parsed = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11,
    )
    result = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=docid, parsed=parsed)

    assert result['action'] == 'inserted'
    assert isinstance(result['beschikking_id'], int)
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active is not None
    assert active['aanslagnummer'] == '1244.12.646.H.60.01'
    assert active['bedrag'] == 30670.0
    assert active['termijnen'] == 11
    assert active['is_active'] == 1

    # fp-sync
    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_betaald == 30670.0
    assert fp.voorlopige_aanslag_ib_termijnen == 11


@pytest.mark.asyncio
async def test_process_voorlopige_aanslag_upload_deactivates_old_active(db):
    """Revisie-pad: tweede upload met ander aanslagnummer → oude is_active=0."""
    from database import (
        process_voorlopige_aanslag_upload, get_active_voorlopige_aanslag,
        get_db_ctx,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    # Eerste upload
    doc1 = await _add_va_doc(db, 2026, 'ib')
    p1 = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    r1 = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc1, parsed=p1)
    assert r1['action'] == 'inserted'
    old_id = r1['beschikking_id']

    # Tweede upload met ander aanslagnummer — revisie
    doc2 = await _add_va_doc(db, 2026, 'ib')
    p2 = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.02',
        dagtekening=_date_cls(2026, 6, 15), bedrag=35000.0,
        betalingskenmerk='0124412647060002', termijnen=7)
    r2 = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc2, parsed=p2)
    assert r2['action'] == 'replaced'
    assert r2['beschikking_id'] != old_id

    # Active: nieuwste
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active['aanslagnummer'] == '1244.12.646.H.60.02'
    assert active['bedrag'] == 35000.0
    assert active['termijnen'] == 7

    # Oude rij: is_active=0 (history behouden)
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT is_active FROM voorlopige_aanslagen WHERE id = ?",
            (old_id,))
        row = await cur.fetchone()
    assert row['is_active'] == 0

    # fp-sync naar nieuwe waarden
    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_betaald == 35000.0
    assert fp.voorlopige_aanslag_ib_termijnen == 7


@pytest.mark.asyncio
async def test_process_voorlopige_aanslag_upload_idempotent_on_duplicate_aanslagnummer(db):
    """Duplicate aanslagnummer → action='skip', geen mutatie, geen extra rij."""
    from database import (
        process_voorlopige_aanslag_upload, get_active_voorlopige_aanslag,
        get_db_ctx,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    doc1 = await _add_va_doc(db, 2026, 'ib')
    p = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    r1 = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc1, parsed=p)
    assert r1['action'] == 'inserted'
    first_id = r1['beschikking_id']

    # Tweede upload met ZELFDE aanslagnummer → skip
    doc2 = await _add_va_doc(db, 2026, 'ib')
    r2 = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc2, parsed=p)
    assert r2['action'] == 'skip'
    assert r2['beschikking_id'] == first_id  # bestaande rij gerefereerd
    # Codex audit fix #2: skip-result moet existing.document_id meegeven
    # zodat de caller een race-self-skip kan onderscheiden van een echte
    # duplicate (race-scenario beschreven in services/va_backfill.py).
    assert r2['existing_document_id'] == doc1

    # Self-skip: zelfde doc_id 2× verwerken — bv. parallel backfill race.
    # Dan wijst existing_document_id naar de doc die we zelf net inserted'en.
    r3 = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc1, parsed=p)
    assert r3['action'] == 'skip'
    assert r3['existing_document_id'] == doc1  # self-reference

    # Geen extra rij in voorlopige_aanslagen
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT COUNT(*) AS n FROM voorlopige_aanslagen")
        cnt = (await cur.fetchone())['n']
    assert cnt == 1

    # Active row intact
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active['id'] == first_id


@pytest.mark.asyncio
async def test_process_voorlopige_aanslag_upload_skips_when_manual_has_same_aanslagnummer(db):
    """Manual VA met aanslagnummer X → daarna PDF-upload zelfde X → skip
    zonder TypeError.

    Regression: vóór deze fix deed line 3304 ``int(existing['document_id'])``
    op een NULL-veld (manual VA → document_id IS NULL na mig 42), wat
    crashte met TypeError. De caller (documenten.py) vangt alleen
    ValueError/YearLockedError af, dus dat zou de upload-flow laten
    crashen voor de gebruiker.
    """
    from database import (
        upsert_manual_voorlopige_aanslag,
        process_voorlopige_aanslag_upload,
        get_active_voorlopige_aanslag,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    # 1. Handmatige VA met een aanslagnummer dat een gebruiker daarna
    # ook in een PDF tegenkomt.
    aanslagnr = '1244.12.646.H.60.01'
    manual = await upsert_manual_voorlopige_aanslag(
        db_path=db, jaar=2026, soort='ib',
        aanslagnummer=aanslagnr, bedrag=12345.67,
        betalingskenmerk='0124412647060001',
        dagtekening=_date_cls(2026, 1, 31), termijnen=10,
    )
    manual_beschikking_id = manual['beschikking_id']

    # 2. PDF-upload met zelfde aanslagnummer.
    doc = await _add_va_doc(db, 2026, 'ib')
    parsed = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer=aanslagnr,
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    result = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc, parsed=parsed)

    # Skip-resultaat moet NULL existing_document_id meegeven (manual heeft
    # geen doc) — caller behandelt None == doc_id als False → echte
    # duplicate-cleanup, manual blijft winnen.
    assert result['action'] == 'skip'
    assert result['beschikking_id'] == manual_beschikking_id
    assert result['existing_document_id'] is None

    # Active blijft de manual rij (document_id IS NULL).
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active['id'] == manual_beschikking_id
    assert active['document_id'] is None
    assert active['bedrag'] == 12345.67


@pytest.mark.asyncio
async def test_upsert_manual_voorlopige_aanslag_no_existing(db):
    """Manual create vanaf scratch (geen vorige active) — fp gesynced."""
    from database import (
        upsert_manual_voorlopige_aanslag, get_active_voorlopige_aanslag,
        get_fiscale_params,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    result = await upsert_manual_voorlopige_aanslag(
        db_path=db, jaar=2026, soort='ib',
        aanslagnummer='MANUAL-2026-IB-A',
        bedrag=12345.67,
        betalingskenmerk='0124412647060001',
        dagtekening=_date_cls(2026, 1, 31),
        termijnen=10,
    )
    assert result['action'] == 'manual_inserted'

    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active is not None
    assert active['document_id'] is None  # manual marker
    assert active['bedrag'] == 12345.67
    assert active['termijnen'] == 10

    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_betaald == 12345.67
    assert fp.voorlopige_aanslag_ib_termijnen == 10


@pytest.mark.asyncio
async def test_upsert_manual_replaces_active_parsed_with_archive(db):
    """Manual entry over een active parsed → parsed wordt gearchiveerd
    (is_active=0), manual wordt nieuwe active."""
    from database import (
        process_voorlopige_aanslag_upload, upsert_manual_voorlopige_aanslag,
        get_active_voorlopige_aanslag,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    doc = await _add_va_doc(db, 2026, 'ib')
    parsed = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    r1 = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc, parsed=parsed)
    assert r1['action'] == 'inserted'

    # Manual override
    await upsert_manual_voorlopige_aanslag(
        db_path=db, jaar=2026, soort='ib',
        aanslagnummer='OVERRIDE-1', bedrag=99999.0,
        betalingskenmerk='', dagtekening=_date_cls(2026, 1, 31),
        termijnen=11,
    )
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active['document_id'] is None
    assert active['bedrag'] == 99999.0

    # Parsed-archief check: 2 rows total, only manual active
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM voorlopige_aanslagen "
            "WHERE jaar=2026 AND soort='ib'")
        assert (await cur.fetchone())['n'] == 2
        cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM voorlopige_aanslagen "
            "WHERE jaar=2026 AND soort='ib' AND is_active=1")
        assert (await cur.fetchone())['n'] == 1


@pytest.mark.asyncio
async def test_upsert_manual_in_place_update_same_aanslagnummer(db):
    """Tweede call met zelfde aanslagnummer + (jaar, soort) → update-in-place
    (action='manual_updated'), geen extra row."""
    from database import (
        upsert_manual_voorlopige_aanslag, get_active_voorlopige_aanslag,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    r1 = await upsert_manual_voorlopige_aanslag(
        db_path=db, jaar=2026, soort='ib',
        aanslagnummer='SAME-NR', bedrag=10000.0,
        betalingskenmerk='', dagtekening=_date_cls(2026, 1, 31),
        termijnen=11,
    )
    assert r1['action'] == 'manual_inserted'
    first_id = r1['beschikking_id']

    r2 = await upsert_manual_voorlopige_aanslag(
        db_path=db, jaar=2026, soort='ib',
        aanslagnummer='SAME-NR', bedrag=20000.0,
        betalingskenmerk='', dagtekening=_date_cls(2026, 2, 15),
        termijnen=10,
    )
    assert r2['action'] == 'manual_updated'
    assert r2['beschikking_id'] == first_id

    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active['bedrag'] == 20000.0
    assert active['termijnen'] == 10


@pytest.mark.asyncio
async def test_upsert_manual_rejects_aanslagnummer_used_elsewhere(db):
    """Aanslagnummer al in gebruik onder andere (jaar, soort) of als parsed
    → ValueError (caller moet kiezen)."""
    from database import (
        process_voorlopige_aanslag_upload, upsert_manual_voorlopige_aanslag,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    doc = await _add_va_doc(db, 2026, 'ib')
    parsed = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc, parsed=parsed)

    # Try manual met zelfde aanslagnummer onder zvw → conflict
    with pytest.raises(ValueError, match='al in gebruik'):
        await upsert_manual_voorlopige_aanslag(
            db_path=db, jaar=2026, soort='zvw',
            aanslagnummer='1244.12.646.H.60.01', bedrag=2808.0,
            betalingskenmerk='', dagtekening=_date_cls(2026, 1, 31),
            termijnen=11,
        )


@pytest.mark.asyncio
async def test_upsert_manual_validates_input(db):
    """Form-validation: bedrag, aanslagnummer, termijnen, kenmerk."""
    from database import upsert_manual_voorlopige_aanslag
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    base = dict(
        db_path=db, jaar=2026, soort='ib',
        aanslagnummer='VALID-NR', bedrag=1000.0, betalingskenmerk='',
        dagtekening=_date_cls(2026, 1, 31), termijnen=11,
    )
    # Soort onbekend
    with pytest.raises(ValueError, match='Onbekende VA soort'):
        await upsert_manual_voorlopige_aanslag(**{**base, 'soort': 'btw'})
    # Bedrag <= 0
    with pytest.raises(ValueError, match='Bedrag'):
        await upsert_manual_voorlopige_aanslag(**{**base, 'bedrag': 0})
    # Aanslagnummer < 5 chars
    with pytest.raises(ValueError, match='Aanslagnummer'):
        await upsert_manual_voorlopige_aanslag(**{**base, 'aanslagnummer': 'ab'})
    # Termijnen out of range
    with pytest.raises(ValueError, match='termijnen'):
        await upsert_manual_voorlopige_aanslag(**{**base, 'termijnen': 13})
    # Kenmerk wrong length
    with pytest.raises(ValueError, match='Betalingskenmerk'):
        await upsert_manual_voorlopige_aanslag(**{**base,
                                                  'betalingskenmerk': '12345'})


@pytest.mark.asyncio
async def test_remove_manual_restores_archived_parsed(db):
    """Remove manual met parsed-archief → parsed weer active + fp gesynced."""
    from database import (
        process_voorlopige_aanslag_upload, upsert_manual_voorlopige_aanslag,
        remove_manual_voorlopige_aanslag, get_active_voorlopige_aanslag,
        get_fiscale_params,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    # Setup: parsed → manual override
    doc = await _add_va_doc(db, 2026, 'ib')
    parsed = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc, parsed=parsed)
    await upsert_manual_voorlopige_aanslag(
        db_path=db, jaar=2026, soort='ib',
        aanslagnummer='MANUAL', bedrag=99999.0,
        betalingskenmerk='', dagtekening=_date_cls(2026, 1, 31),
        termijnen=11,
    )

    # Remove manual → parsed wordt hersteld
    result = await remove_manual_voorlopige_aanslag(
        db_path=db, jaar=2026, soort='ib')
    assert result['action'] == 'restored_parsed'

    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active['document_id'] == doc
    assert active['bedrag'] == 30670.0

    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_betaald == 30670.0


@pytest.mark.asyncio
async def test_remove_manual_clears_fp_when_no_archive(db):
    """Remove manual zonder parsed-archief → fp gecleared."""
    from database import (
        upsert_manual_voorlopige_aanslag, remove_manual_voorlopige_aanslag,
        get_active_voorlopige_aanslag, get_fiscale_params,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    await upsert_manual_voorlopige_aanslag(
        db_path=db, jaar=2026, soort='ib',
        aanslagnummer='MANUAL-ONLY', bedrag=12345.0,
        betalingskenmerk='', dagtekening=_date_cls(2026, 1, 31),
        termijnen=11,
    )
    result = await remove_manual_voorlopige_aanslag(
        db_path=db, jaar=2026, soort='ib')
    assert result['action'] == 'cleared'

    assert await get_active_voorlopige_aanslag(db, 2026, 'ib') is None
    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_betaald == 0


@pytest.mark.asyncio
async def test_remove_manual_raises_when_no_active_manual(db):
    """Remove manual zonder active manual → ValueError (caller-fout)."""
    from database import remove_manual_voorlopige_aanslag
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    with pytest.raises(ValueError, match='Geen actieve handmatige'):
        await remove_manual_voorlopige_aanslag(
            db_path=db, jaar=2026, soort='ib')


@pytest.mark.asyncio
async def test_process_upload_parsed_archived_when_manual_active(db):
    """Active manual + nieuwe PDF-upload → action='parsed_archived',
    nieuwe rij is_active=0, manual blijft winnen."""
    from database import (
        upsert_manual_voorlopige_aanslag, process_voorlopige_aanslag_upload,
        get_active_voorlopige_aanslag, get_fiscale_params,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    # Manual eerst
    await upsert_manual_voorlopige_aanslag(
        db_path=db, jaar=2026, soort='ib',
        aanslagnummer='MANUAL-FIRST', bedrag=12000.0,
        betalingskenmerk='', dagtekening=_date_cls(2026, 1, 31),
        termijnen=11,
    )
    # Dan PDF upload
    doc = await _add_va_doc(db, 2026, 'ib')
    parsed = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    result = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc, parsed=parsed)
    assert result['action'] == 'parsed_archived'

    # Active blijft manual
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active['document_id'] is None
    assert active['bedrag'] == 12000.0

    # fp blijft op manual-waarden
    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_betaald == 12000.0


@pytest.mark.asyncio
async def test_get_active_voorlopige_aanslag_returns_active_only(db):
    """get_active filtert op is_active=1 — inactive rows worden niet returned."""
    from database import (
        process_voorlopige_aanslag_upload, get_active_voorlopige_aanslag,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    # Geen rows → None
    assert await get_active_voorlopige_aanslag(db, 2026, 'ib') is None

    # Eerste upload + revisie
    doc1 = await _add_va_doc(db, 2026, 'ib')
    p1 = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc1, parsed=p1)
    doc2 = await _add_va_doc(db, 2026, 'ib')
    p2 = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.02',
        dagtekening=_date_cls(2026, 6, 15), bedrag=35000.0,
        betalingskenmerk='0124412647060002', termijnen=7)
    await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc2, parsed=p2)

    # 2 rows in DB, maar get_active geeft alleen de actieve
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active is not None
    assert active['aanslagnummer'] == '1244.12.646.H.60.02'

    # Andere soort/jaar → None
    assert await get_active_voorlopige_aanslag(db, 2026, 'zvw') is None
    assert await get_active_voorlopige_aanslag(db, 2025, 'ib') is None


@pytest.mark.asyncio
async def test_get_va_betalingen_detail_classifies_ib_zvw_unmatched(db):
    """Detail classifies bank-tx via kenmerk-positie [10:12]: <50=ib, >=50=zvw,
    overige=unmatched. Unmatched-rij blijft zichtbaar voor audit."""
    from database import get_va_betalingen_detail, BELASTINGDIENST_IBAN
    # 3 BD-tx: IB (kenmerk 10:12 = '06'), ZVW ('70'), unmatched (random kenmerk)
    await add_banktransacties(db, [
        {'datum': '2026-02-28', 'bedrag': -2788.0,
         'tegenpartij': 'BD', 'omschrijving': 'VA-IB feb',
         'tegenrekening': BELASTINGDIENST_IBAN,
         'betalingskenmerk': '0124412647060001'},
        {'datum': '2026-03-31', 'bedrag': -800.0,
         'tegenpartij': 'BD', 'omschrijving': 'VA-ZVW mrt',
         'tegenrekening': BELASTINGDIENST_IBAN,
         'betalingskenmerk': '0124412647700001'},
        {'datum': '2026-04-15', 'bedrag': -100.0,
         'tegenpartij': 'BD', 'omschrijving': 'overig',
         'tegenrekening': BELASTINGDIENST_IBAN,
         'betalingskenmerk': '12345'},  # te kort → unmatched
    ], csv_bestand='va.csv')

    detail = await get_va_betalingen_detail(db, 2026)
    classifications = [r['classification'] for r in detail]
    assert 'ib_matched' in classifications
    assert 'zvw_matched' in classifications
    assert 'unmatched' in classifications
    assert len(detail) == 3

    # Bedragen positief (ABS)
    for r in detail:
        assert r['bedrag'] >= 0
    # Sorted by datum ASC
    datums = [r['datum'] for r in detail]
    assert datums == sorted(datums)


@pytest.mark.asyncio
async def test_process_voorlopige_aanslag_upload_rejects_doc_jaar_mismatch(db):
    """Codex T1.1 critical: parsed.jaar != aangifte_document.jaar → ValueError.
    Voorkomt cross-year stealth (2025-doc als bron voor 2026-VA)."""
    from database import process_voorlopige_aanslag_upload, get_db_ctx
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2025))
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))
    docid_2025 = await _add_va_doc(db, 2025, 'ib')

    parsed_2026 = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    with pytest.raises(ValueError, match='jaar-mismatch'):
        await process_voorlopige_aanslag_upload(
            db_path=db, document_id=docid_2025, parsed=parsed_2026)

    # Geen rij gemaakt
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT COUNT(*) AS n FROM voorlopige_aanslagen")
        assert (await cur.fetchone())['n'] == 0


@pytest.mark.asyncio
async def test_process_voorlopige_aanslag_upload_rejects_non_va_document(db):
    """Codex T1.1 critical: niet-VA categorie → ValueError. Voorkomt
    misbruik van WOZ-doc als VA-bron."""
    from database import process_voorlopige_aanslag_upload, add_aangifte_document
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))
    woz_doc = await add_aangifte_document(
        db, jaar=2026, categorie='eigen_woning',
        documenttype='woz_beschikking',
        bestandsnaam='WOZ.pdf',
        bestandspad='/data/aangifte/2026/eigen_woning/WOZ.pdf',
        upload_datum='2026-01-01')

    parsed = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    with pytest.raises(ValueError, match="verwacht 'voorlopige_aanslag'"):
        await process_voorlopige_aanslag_upload(
            db_path=db, document_id=woz_doc, parsed=parsed)


@pytest.mark.asyncio
async def test_process_voorlopige_aanslag_upload_rejects_missing_document(db):
    """Onbekende document_id → ValueError (geen silent insert van orphan-FK)."""
    from database import process_voorlopige_aanslag_upload
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))
    parsed = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    with pytest.raises(ValueError, match='bestaat niet'):
        await process_voorlopige_aanslag_upload(
            db_path=db, document_id=99999, parsed=parsed)


@pytest.mark.asyncio
async def test_process_voorlopige_aanslag_upload_rollback_keeps_old_active_intact(db):
    """Codex T1.1 should-fix: bewijs partial-state-protection — als de
    INSERT van de nieuwe rij faalt (bedrag<0 → CHECK IntegrityError), dan
    moet de gedeactiveerde oude rij gerestored zijn (is_active=1) en
    fp ongewijzigd. Test bewijst de ROLLBACK-claim concreet."""
    import aiosqlite
    from database import (
        process_voorlopige_aanslag_upload, get_active_voorlopige_aanslag,
        get_db_ctx,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    # Eerste valid upload
    doc1 = await _add_va_doc(db, 2026, 'ib')
    p1 = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc1, parsed=p1)
    fp_before = await get_fiscale_params(db, 2026)

    # Tweede upload met bedrag<0 — CHECK constraint faalt op INSERT
    # NA deactivate van oude rij. Rollback moet alles terugdraaien.
    doc2 = await _add_va_doc(db, 2026, 'ib')
    p_bad = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.02',
        dagtekening=_date_cls(2026, 6, 15), bedrag=-1.0,  # CHECK<0 fail
        betalingskenmerk='0124412647060002', termijnen=7)
    with pytest.raises(aiosqlite.IntegrityError):
        await process_voorlopige_aanslag_upload(
            db_path=db, document_id=doc2, parsed=p_bad)

    # Oude active gerestored (is_active=1) — niet 0!
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active is not None
    assert active['aanslagnummer'] == '1244.12.646.H.60.01'
    assert active['is_active'] == 1
    # Geen tweede rij ingevoegd
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT COUNT(*) AS n FROM voorlopige_aanslagen")
        assert (await cur.fetchone())['n'] == 1
    # fp ongewijzigd
    fp_after = await get_fiscale_params(db, 2026)
    assert fp_after.voorlopige_aanslag_betaald == fp_before.voorlopige_aanslag_betaald
    assert fp_after.voorlopige_aanslag_ib_termijnen == fp_before.voorlopige_aanslag_ib_termijnen


@pytest.mark.asyncio
async def test_voorlopige_aanslagen_partial_index_blocks_two_active_per_jaar_soort(db):
    """Codex T1.1 should-fix: bewijs partial unique index. Twee actieve
    rows voor zelfde (jaar, soort) → IntegrityError. Inactive history
    rows zijn ALLE toegestaan."""
    import aiosqlite
    from database import get_db_ctx
    docid = await _add_va_doc(db, 2026, 'ib')
    docid2 = await _add_va_doc(db, 2026, 'ib')
    async with get_db_ctx(db) as conn:
        # Eerste actieve rij — OK
        await conn.execute(
            """INSERT INTO voorlopige_aanslagen
               (jaar, soort, document_id, aanslagnummer, dagtekening,
                bedrag, betalingskenmerk, termijnen, is_active)
               VALUES (?, 'ib', ?, ?, ?, ?, ?, ?, 1)""",
            (2026, docid, 'X.1', '2026-01-31', 100.0, '0' * 16, 11))
        # Tweede actieve rij voor (2026, 'ib') — moet falen
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                """INSERT INTO voorlopige_aanslagen
                   (jaar, soort, document_id, aanslagnummer, dagtekening,
                    bedrag, betalingskenmerk, termijnen, is_active)
                   VALUES (?, 'ib', ?, ?, ?, ?, ?, ?, 1)""",
                (2026, docid2, 'X.2', '2026-01-31', 100.0, '0' * 16, 11))
        # Inactieve rij voor zelfde (jaar, soort) — toegestaan
        await conn.execute(
            """INSERT INTO voorlopige_aanslagen
               (jaar, soort, document_id, aanslagnummer, dagtekening,
                bedrag, betalingskenmerk, termijnen, is_active)
               VALUES (?, 'ib', ?, ?, ?, ?, ?, ?, 0)""",
            (2026, docid2, 'X.3', '2026-01-31', 100.0, '0' * 16, 11))
        await conn.commit()
        # 2 rijen totaal: 1 active + 1 inactive
        cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM voorlopige_aanslagen "
            "WHERE jaar=2026 AND soort='ib'")
        assert (await cur.fetchone())['n'] == 2


@pytest.mark.asyncio
async def test_process_voorlopige_aanslag_upload_zvw_syncs_zvw_field(db):
    """Codex T1.1 should-fix: ZVW-pad schrijft naar voorlopige_aanslag_zvw
    (NIET _betaald) + voorlopige_aanslag_zvw_termijnen. IB+ZVW kunnen
    naast elkaar bestaan voor zelfde jaar (verschillende soort)."""
    from database import (
        process_voorlopige_aanslag_upload, get_active_voorlopige_aanslag,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))
    doc_zvw = await _add_va_doc(db, 2026, 'zvw')

    parsed_zvw = _FakeParsed(
        jaar=2026, soort='zvw', aanslagnummer='1244.12.646.W.60.01.4',
        dagtekening=_date_cls(2026, 1, 31), bedrag=4500.0,
        betalingskenmerk='0124412647500001', termijnen=11)
    r = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc_zvw, parsed=parsed_zvw)
    assert r['action'] == 'inserted'

    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_zvw == 4500.0
    assert fp.voorlopige_aanslag_zvw_termijnen == 11
    # IB-velden ongemoeid (default)
    assert fp.voorlopige_aanslag_betaald == 0

    # IB-upload daarnaast — beide soorten coexist
    doc_ib = await _add_va_doc(db, 2026, 'ib')
    parsed_ib = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc_ib, parsed=parsed_ib)
    fp2 = await get_fiscale_params(db, 2026)
    assert fp2.voorlopige_aanslag_betaald == 30670.0
    assert fp2.voorlopige_aanslag_zvw == 4500.0  # ZVW intact
    # Beide actief
    assert (await get_active_voorlopige_aanslag(db, 2026, 'ib'))['bedrag'] == 30670.0
    assert (await get_active_voorlopige_aanslag(db, 2026, 'zvw'))['bedrag'] == 4500.0


@pytest.mark.asyncio
async def test_delete_aangifte_document_with_va_cleanup_clears_fp(db):
    """Codex round-2 critical: delete laatste VA-doc → fp.voorlopige_aanslag_*
    teruggezet naar 0 + termijnen naar 11. Voorkomt stale handmatige waarde."""
    from database import (
        process_voorlopige_aanslag_upload,
        delete_aangifte_document_with_va_cleanup,
        get_active_voorlopige_aanslag,
    )
    await upsert_fiscale_params(
        db_path=db, **_minimal_fiscale_params_kwargs(2026))

    docid = await _add_va_doc(db, 2026, 'ib')
    p = _FakeParsed(
        jaar=2026, soort='ib', aanslagnummer='1244.12.646.H.60.01',
        dagtekening=_date_cls(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11)
    await process_voorlopige_aanslag_upload(
        db_path=db, document_id=docid, parsed=p)

    # fp gevuld door process — eerst bevestigen
    fp_before = await get_fiscale_params(db, 2026)
    assert fp_before.voorlopige_aanslag_betaald == 30670.0

    # Delete via wrapper → CASCADE verwijdert VA-row + clear fp
    await delete_aangifte_document_with_va_cleanup(db, doc_id=docid)

    # VA-row weg (CASCADE)
    assert await get_active_voorlopige_aanslag(db, 2026, 'ib') is None

    # fp teruggezet naar default 0/11
    fp_after = await get_fiscale_params(db, 2026)
    assert fp_after.voorlopige_aanslag_betaald == 0
    assert fp_after.voorlopige_aanslag_ib_termijnen == 11
    # ZVW ongemoeid (geen ZVW-VA was er)
    assert fp_after.voorlopige_aanslag_zvw == 0

