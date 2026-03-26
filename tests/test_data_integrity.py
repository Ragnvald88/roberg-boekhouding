"""Tests voor data-integriteitsregels (delete guards, status checks)."""

import pytest
from database import (
    add_klant, add_werkdag, delete_werkdag,
    add_factuur, delete_factuur, update_factuur_status,
    link_werkdagen_to_factuur, get_werkdagen,
)


async def _create_werkdag(db, linked=False):
    """Helper: maak een klant + werkdag, optioneel gekoppeld aan factuur."""
    kid = await add_klant(db, naam="Testpraktijk", tarief_uur=80, retour_km=30)
    factuurnummer = '2025-999' if linked else ''
    wid = await add_werkdag(
        db, datum='2025-01-15', klant_id=kid, uren=8, km=0,
        tarief=100, km_tarief=0, factuurnummer=factuurnummer,
    )
    return wid


@pytest.mark.asyncio
async def test_delete_ongefactureerd_werkdag_succeeds(db):
    """Ongefactureerde werkdagen mogen gewoon verwijderd worden."""
    wid = await _create_werkdag(db, linked=False)
    # Should not raise
    await delete_werkdag(db, werkdag_id=wid)


@pytest.mark.asyncio
async def test_delete_linked_werkdag_raises(db):
    """Aan factuur gekoppelde werkdagen mogen NIET verwijderd worden."""
    wid = await _create_werkdag(db, linked=True)
    with pytest.raises(ValueError, match='factuur'):
        await delete_werkdag(db, werkdag_id=wid)


# --- Factuur deletion guards ---

async def _create_factuur(db, status='concept'):
    """Helper: maak klant + werkdag + factuur met opgegeven status."""
    kid = await add_klant(db, naam="Testpraktijk", tarief_uur=80, retour_km=30)
    wid = await add_werkdag(
        db, datum='2025-01-15', klant_id=kid, uren=8, km=0,
        tarief=100, km_tarief=0,
    )
    fid = await add_factuur(
        db, nummer='2025-999', klant_id=kid, datum='2025-01-31',
        totaal_bedrag=800,
    )
    await link_werkdagen_to_factuur(db, werkdag_ids=[wid], factuurnummer='2025-999')
    if status != 'concept':
        await update_factuur_status(db, factuur_id=fid, status=status)
    return fid, wid


@pytest.mark.asyncio
async def test_delete_concept_factuur_succeeds(db):
    """Concept facturen mogen verwijderd worden; werkdagen worden ongefactureerd."""
    fid, wid = await _create_factuur(db, status='concept')
    # Should not raise
    await delete_factuur(db, factuur_id=fid)
    # Werkdag should be reset to ongefactureerd
    werkdagen = await get_werkdagen(db, jaar=2025)
    assert len(werkdagen) == 1
    assert werkdagen[0].status == 'ongefactureerd'


@pytest.mark.asyncio
async def test_delete_betaald_factuur_raises(db):
    """Betaalde facturen mogen NIET verwijderd worden."""
    fid, _wid = await _create_factuur(db, status='betaald')
    with pytest.raises(ValueError, match='betaald'):
        await delete_factuur(db, factuur_id=fid)


@pytest.mark.asyncio
async def test_delete_verstuurd_factuur_raises(db):
    """Verstuurde facturen mogen NIET verwijderd worden."""
    fid, _wid = await _create_factuur(db, status='verstuurd')
    with pytest.raises(ValueError, match='verstuurd'):
        await delete_factuur(db, factuur_id=fid)


# --- Status transition validation ---

@pytest.mark.asyncio
async def test_invalid_status_transition_raises(db):
    """Cannot go from betaald back to concept."""
    klant_id = await add_klant(db, naam='Test', tarief_uur=100)
    f_id = await add_factuur(db, nummer='2025-099', klant_id=klant_id,
                              datum='2025-01-31', totaal_bedrag=800)
    await update_factuur_status(db, f_id, 'betaald', '2025-02-15')
    with pytest.raises(ValueError, match='niet toegestaan'):
        await update_factuur_status(db, f_id, 'concept')


@pytest.mark.asyncio
async def test_valid_status_transitions(db):
    """Valid transitions should work: concept->verstuurd->betaald."""
    klant_id = await add_klant(db, naam='Test', tarief_uur=100)
    f_id = await add_factuur(db, nummer='2025-098', klant_id=klant_id,
                              datum='2025-01-31', totaal_bedrag=800)
    await update_factuur_status(db, f_id, 'verstuurd')
    await update_factuur_status(db, f_id, 'betaald', '2025-02-15')
    # Should not raise


# --- Non-werkdag business km (uren=0) ---

@pytest.mark.asyncio
async def test_add_werkdag_zero_uren_succeeds(db):
    """Werkdag with uren=0 for non-patient business km should work."""
    klant_id = await add_klant(db, naam='Test', tarief_uur=100)
    wd_id = await add_werkdag(db, datum='2025-03-15', klant_id=klant_id,
                               uren=0, km=30, tarief=0, km_tarief=0.23,
                               urennorm=0, activiteit='Congres KNMG')
    rows = await get_werkdagen(db)
    assert len(rows) == 1
    assert rows[0].uren == 0
    assert rows[0].km == 30
    assert rows[0].urennorm == 0
