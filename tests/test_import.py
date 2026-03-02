"""Tests voor data migratie / import."""

import pytest
from pathlib import Path
from database import init_db, get_werkdagen, get_klanten
from import_.seed_data import seed_all
from import_.urenregister import import_urenregister


XLSM_PATH = Path(
    "~/Library/CloudStorage/SynologyDrive-Main/02_Financieel/"
    "Boekhouding_Waarneming/Urenregister.xlsm"
).expanduser()


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    await seed_all(db_path)
    return db_path


@pytest.mark.skipif(not XLSM_PATH.exists(), reason="Urenregister.xlsm not found")
@pytest.mark.asyncio
async def test_import_urenregister(db):
    """Import Urenregister.xlsm and verify row counts."""
    result = await import_urenregister(XLSM_PATH, db)

    assert result['imported'] > 500, f"Expected 500+ rows, got {result['imported']}"
    assert len(result['errors']) == 0, f"Errors: {result['errors'][:5]}"

    # Verify werkdagen in DB
    all_werkdagen = await get_werkdagen(db)
    assert len(all_werkdagen) == result['imported']

    # Verify klanten were created from Excel data
    klanten = await get_klanten(db)
    assert len(klanten) >= 5  # At least 5 unique customers in Excel


@pytest.mark.skipif(not XLSM_PATH.exists(), reason="Urenregister.xlsm not found")
@pytest.mark.asyncio
async def test_import_achterwacht_urennorm(db):
    """Achterwacht werkdagen should have urennorm=0."""
    await import_urenregister(XLSM_PATH, db)

    all_werkdagen = await get_werkdagen(db)
    achterwacht = [w for w in all_werkdagen if 'ACHTERWACHT' in w.code.upper()]
    for w in achterwacht:
        assert not w.urennorm, f"Achterwacht {w.code} should have urennorm=0"


@pytest.mark.skipif(not XLSM_PATH.exists(), reason="Urenregister.xlsm not found")
@pytest.mark.asyncio
async def test_import_status_mapping(db):
    """Status 'betaald' maps correctly."""
    await import_urenregister(XLSM_PATH, db)

    all_werkdagen = await get_werkdagen(db)
    statuses = {w.status for w in all_werkdagen}
    assert 'betaald' in statuses
