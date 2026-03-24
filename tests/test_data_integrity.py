"""Tests voor data-integriteitsregels (delete guards, status checks)."""

import pytest
from database import (
    init_db, add_klant, add_werkdag, update_werkdag, delete_werkdag,
)


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path


async def _create_werkdag(db, status='ongefactureerd'):
    """Helper: maak een klant + werkdag met opgegeven status."""
    kid = await add_klant(db, naam="Testpraktijk", tarief_uur=80, retour_km=30)
    wid = await add_werkdag(
        db, datum='2025-01-15', klant_id=kid, uren=8, km=0,
        tarief=100, km_tarief=0,
    )
    if status != 'ongefactureerd':
        await update_werkdag(db, werkdag_id=wid, status=status)
    return wid


@pytest.mark.asyncio
async def test_delete_ongefactureerd_werkdag_succeeds(db):
    """Ongefactureerde werkdagen mogen gewoon verwijderd worden."""
    wid = await _create_werkdag(db, status='ongefactureerd')
    # Should not raise
    await delete_werkdag(db, werkdag_id=wid)


@pytest.mark.asyncio
async def test_delete_gefactureerd_werkdag_raises(db):
    """Gefactureerde werkdagen mogen NIET verwijderd worden."""
    wid = await _create_werkdag(db, status='gefactureerd')
    with pytest.raises(ValueError, match='gefactureerd'):
        await delete_werkdag(db, werkdag_id=wid)


@pytest.mark.asyncio
async def test_delete_betaald_werkdag_raises(db):
    """Betaalde werkdagen mogen NIET verwijderd worden."""
    wid = await _create_werkdag(db, status='betaald')
    with pytest.raises(ValueError, match='betaald'):
        await delete_werkdag(db, werkdag_id=wid)
