"""Tests voor seed data: fiscale parameters."""

import pytest
from database import init_db, get_klanten, get_fiscale_params, get_all_fiscale_params
from import_.seed_data import seed_fiscale_params, seed_all


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path


@pytest.mark.asyncio
async def test_seed_creates_no_klanten(db):
    """Seed should not create any klanten (they come from import)."""
    await seed_all(db)
    klanten = await get_klanten(db)
    assert len(klanten) == 0


@pytest.mark.asyncio
async def test_seed_creates_fiscale_params(db):
    count = await seed_fiscale_params(db)
    assert count == 4
    alle = await get_all_fiscale_params(db)
    assert len(alle) == 4
    jaren = {fp.jaar for fp in alle}
    assert jaren == {2023, 2024, 2025, 2026}

    # Check 2025 values in detail
    fp = await get_fiscale_params(db, jaar=2025)
    assert fp is not None
    assert fp.zelfstandigenaftrek == 2470
    assert fp.startersaftrek == 2123
    assert fp.mkb_vrijstelling_pct == 12.70
    assert fp.kia_ondergrens == 2901
    assert fp.kia_bovengrens == 70602
    assert fp.kia_pct == 28
    assert fp.km_tarief == 0.23
    assert fp.schijf1_grens == 38441
    assert fp.schijf1_pct == 35.82
    assert fp.schijf2_grens == 76817
    assert fp.schijf2_pct == 37.48
    assert fp.schijf3_pct == 49.50
    assert fp.ahk_max == 3068
    assert fp.ahk_afbouw_pct == 6.337
    assert fp.ahk_drempel == 28406
    assert fp.ak_max == 5599
    assert fp.zvw_pct == 5.26
    assert fp.zvw_max_grondslag == 75864
    assert fp.repr_aftrek_pct == 80


@pytest.mark.asyncio
async def test_seed_idempotent(db):
    # First run: inserts data
    await seed_all(db)
    params_1 = await get_all_fiscale_params(db)
    assert len(params_1) == 4

    # Second run: should NOT duplicate
    await seed_all(db)
    params_2 = await get_all_fiscale_params(db)
    assert len(params_2) == 4
