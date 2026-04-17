"""Tests for jaarafsluiting_snapshots — frozen-in-time tax year records."""

import pytest

from components.fiscal_utils import fetch_fiscal_data, load_jaarafsluiting_data
from database import (
    add_factuur,
    add_klant,
    add_uitgave,
    add_werkdag,
    load_jaarafsluiting_snapshot,
    save_jaarafsluiting_snapshot,
    update_jaarafsluiting_status,
    upsert_fiscale_params,
)
from import_.seed_data import FISCALE_PARAMS


@pytest.mark.asyncio
async def test_snapshot_roundtrip(db):
    """Saved snapshot can be loaded back verbatim."""
    snap = {'winst_voor_belasting': 50000, 'belastbare_winst': 40000}
    balans = {'totaal_activa': 20000, 'eigen_vermogen': 15000}
    params = {'schijf1_pct': 35.75, 'ak_max': 5685}
    await save_jaarafsluiting_snapshot(db, 2024, snap, balans, params)
    loaded = await load_jaarafsluiting_snapshot(db, 2024)
    assert loaded is not None
    assert loaded['snapshot'] == snap
    assert loaded['balans'] == balans
    assert loaded['fiscale_params'] == params
    assert loaded['gesnapshot_op']


@pytest.mark.asyncio
async def test_snapshot_upsert_overwrites(db):
    """Second save with same jaar overwrites the first."""
    await save_jaarafsluiting_snapshot(db, 2024, {'a': 1}, {'b': 2}, {'c': 3})
    await save_jaarafsluiting_snapshot(db, 2024, {'a': 999}, {}, {})
    loaded = await load_jaarafsluiting_snapshot(db, 2024)
    assert loaded is not None
    assert loaded['snapshot'] == {'a': 999}


@pytest.mark.asyncio
async def test_snapshot_missing_returns_none(db):
    """Missing year returns None, not an error."""
    assert await load_jaarafsluiting_snapshot(db, 1999) is None


@pytest.mark.asyncio
async def test_mark_definitief_blocks_mutations_and_keeps_snapshot(db):
    """After K6 (review): mutations in a definitief year are BLOCKED at the
    write layer, not merely hidden by the snapshot. Both the snapshot AND
    the live data must therefore remain identical to the initial state.

    (Pre-K6 this test allowed the mutation through and asserted that only
    the snapshot stayed stable — that weaker contract is obsolete.)
    """
    from database import YearLockedError

    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    kid = await add_klant(db, naam="SnapTest", tarief_uur=100, retour_km=0)
    await add_factuur(
        db, nummer='2024-SNAP1', klant_id=kid,
        datum='2024-06-15', totaal_uren=10, totaal_km=0,
        totaal_bedrag=1000.00, status='betaald', betaald_datum='2024-06-20',
    )
    initial = await fetch_fiscal_data(db, 2024)
    assert initial is not None
    await save_jaarafsluiting_snapshot(db, 2024, initial, {}, {'schijf1_pct': 35.75})
    await update_jaarafsluiting_status(db, 2024, 'definitief')

    # Attempting to add a factuur in the definitief year must raise.
    with pytest.raises(YearLockedError):
        await add_factuur(
            db, nummer='2024-SNAP2', klant_id=kid,
            datum='2024-07-01', totaal_uren=20, totaal_km=0,
            totaal_bedrag=2000.00, status='betaald', betaald_datum='2024-07-05',
        )

    # Snapshot-read path unchanged.
    frozen = await load_jaarafsluiting_data(db, 2024)
    assert frozen['omzet'] == initial['omzet'], (
        "Snapshot moet bevroren zijn — mutaties na save mogen geen effect hebben"
    )

    # Live data must ALSO be unchanged now: the guard blocked the mutation.
    live = await fetch_fiscal_data(db, 2024)
    assert live is not None
    assert live['omzet'] == initial['omzet'], (
        "K6: year-lock moet mutaties blokkeren zodat live == snapshot blijft"
    )


@pytest.mark.asyncio
async def test_load_jaarafsluiting_data_concept_returns_live(db):
    """Non-definitief year: load_jaarafsluiting_data returns live data, not snapshot."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    kid = await add_klant(db, naam="ConceptTest", tarief_uur=100, retour_km=0)
    await add_factuur(
        db, nummer='2024-LIVE1', klant_id=kid,
        datum='2024-05-01', totaal_uren=5, totaal_km=0,
        totaal_bedrag=500.00, status='betaald', betaald_datum='2024-05-10',
    )
    # Stale snapshot (won't be used because status=concept)
    await save_jaarafsluiting_snapshot(db, 2024, {'omzet': 99999}, {}, {})

    data = await load_jaarafsluiting_data(db, 2024)
    assert data is not None
    assert data['omzet'] == 500.00, (
        "Concept jaar moet live data retourneren, niet de snapshot"
    )


@pytest.mark.asyncio
async def test_load_jaarafsluiting_data_definitief_without_snapshot_falls_back(db):
    """Definitief without snapshot: fall back to live data (defensive)."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    data = await load_jaarafsluiting_data(db, 2024)
    assert data is not None
    assert 'omzet' in data


@pytest.mark.asyncio
async def test_compute_checklist_issues_empty_db(db):
    """Empty DB for a year should return issues for missing data."""
    from pages.jaarafsluiting import compute_checklist_issues
    issues = await compute_checklist_issues(db, 2026)
    assert isinstance(issues, list)
    # No facturen, no uitgaven → should flag these
    assert any('facturen' in i[1].lower() for i in issues)


@pytest.mark.asyncio
async def test_compute_checklist_issues_clean_year(db):
    """Year with complete data should return fewer/no issues."""
    from pages.jaarafsluiting import compute_checklist_issues
    # Seed fiscal params using real seed data (upsert needs all keys)
    seed = {**FISCALE_PARAMS[max(FISCALE_PARAMS.keys())], 'jaar': 2026}
    await upsert_fiscale_params(db, **seed)
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    await add_factuur(
        db, nummer='2026-001', klant_id=kid,
        datum='2026-06-15', totaal_uren=8, totaal_km=0,
        totaal_bedrag=800.0, status='betaald',
    )
    await add_uitgave(db, datum='2026-03-01', omschrijving='Pennen',
                      bedrag=25.0, categorie='Kantoorkosten')
    issues = await compute_checklist_issues(db, 2026)
    # Should NOT flag missing facturen or uitgaven
    assert not any('geen facturen' in i[1].lower() for i in issues)
    assert not any('geen uitgaven' in i[1].lower() for i in issues)


@pytest.mark.asyncio
async def test_compute_checklist_issues_ongefactureerd_werkdag(db):
    """Werkdag met tarief > 0 en lege factuurnummer moet als warning verschijnen."""
    from pages.jaarafsluiting import compute_checklist_issues
    kid = await add_klant(db, naam='OngefactTest', tarief_uur=100)
    await add_werkdag(
        db,
        datum='2026-05-10',
        klant_id=kid,
        uren=8,
        tarief=100.0,
        km=0,
        km_tarief=0.23,
        urennorm=1,
        activiteit='Waarneming dagpraktijk',
        factuurnummer='',
    )
    issues = await compute_checklist_issues(db, 2026)
    matching = [i for i in issues if 'ongefactureerde werkdagen' in i[1].lower()]
    assert matching, f"Expected 'ongefactureerde werkdagen' issue, got: {issues}"
    severity, _message, link = matching[0]
    assert severity == 'warning'
    assert link == '/werkdagen'
