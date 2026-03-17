"""Tests voor klant_locaties CRUD operaties."""

import pytest
from database import (
    init_db, add_klant, get_klant_locaties,
    add_klant_locatie, delete_klant_locatie,
)


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path


@pytest.mark.asyncio
async def test_add_and_get_locaties(db):
    """Add locations to a klant, verify they're returned."""
    kid = await add_klant(db, naam="HAP MiddenLand", tarief_uur=124, retour_km=60)
    lid1 = await add_klant_locatie(db, klant_id=kid, naam="Assen", retour_km=60)
    lid2 = await add_klant_locatie(db, klant_id=kid, naam="Emmen", retour_km=102)
    lid3 = await add_klant_locatie(db, klant_id=kid, naam="Hoogeveen", retour_km=128)
    assert lid1 > 0
    assert lid2 > 0
    assert lid3 > 0

    locaties = await get_klant_locaties(db, klant_id=kid)
    assert len(locaties) == 3
    namen = {loc.naam for loc in locaties}
    assert namen == {"Assen", "Emmen", "Hoogeveen"}
    assen = next(loc for loc in locaties if loc.naam == "Assen")
    assert assen.retour_km == 60
    emmen = next(loc for loc in locaties if loc.naam == "Emmen")
    assert emmen.retour_km == 102


@pytest.mark.asyncio
async def test_delete_locatie(db):
    """Delete a location, verify it's gone and others remain."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=50)
    lid1 = await add_klant_locatie(db, klant_id=kid, naam="Loc A", retour_km=50)
    lid2 = await add_klant_locatie(db, klant_id=kid, naam="Loc B", retour_km=100)
    await delete_klant_locatie(db, locatie_id=lid1)
    locaties = await get_klant_locaties(db, klant_id=kid)
    assert len(locaties) == 1
    assert locaties[0].naam == "Loc B"


@pytest.mark.asyncio
async def test_unique_constraint(db):
    """Adding duplicate (klant_id, naam) raises an error."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=50)
    await add_klant_locatie(db, klant_id=kid, naam="Loc A", retour_km=50)
    with pytest.raises(Exception):
        await add_klant_locatie(db, klant_id=kid, naam="Loc A", retour_km=60)


@pytest.mark.asyncio
async def test_get_locaties_empty(db):
    """Klant with no locations returns empty list."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=50)
    locaties = await get_klant_locaties(db, klant_id=kid)
    assert locaties == []


@pytest.mark.asyncio
async def test_cascade_delete_klant(db):
    """Deleting a klant cascades to its locations."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=50)
    await add_klant_locatie(db, klant_id=kid, naam="Loc A", retour_km=50)
    await add_klant_locatie(db, klant_id=kid, naam="Loc B", retour_km=100)
    from database import delete_klant
    await delete_klant(db, klant_id=kid)
    locaties = await get_klant_locaties(db, klant_id=kid)
    assert locaties == []
