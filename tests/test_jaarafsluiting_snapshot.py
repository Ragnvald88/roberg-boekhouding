"""Tests for jaarafsluiting_snapshots — frozen-in-time tax year records."""

import pytest

from components.fiscal_utils import fetch_fiscal_data, load_jaarafsluiting_data
from database import (
    add_factuur,
    add_klant,
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
async def test_mark_definitief_snapshots_current_state(db):
    """End-to-end: freeze data, mutate, verify snapshot is unchanged."""
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

    await add_factuur(
        db, nummer='2024-SNAP2', klant_id=kid,
        datum='2024-07-01', totaal_uren=20, totaal_km=0,
        totaal_bedrag=2000.00, status='betaald', betaald_datum='2024-07-05',
    )

    frozen = await load_jaarafsluiting_data(db, 2024)
    assert frozen['omzet'] == initial['omzet'], (
        "Snapshot moet bevroren zijn — mutaties na save mogen geen effect hebben"
    )

    live = await fetch_fiscal_data(db, 2024)
    assert live is not None
    assert live['omzet'] != initial['omzet'], "sanity: live data moet de nieuwe factuur zien"


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
