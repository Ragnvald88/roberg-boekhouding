"""Tests voor seed data: fiscale parameters."""

import pytest
from database import get_klanten, get_fiscale_params, get_all_fiscale_params
from import_.seed_data import seed_fiscale_params, seed_all


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
    assert fp.zvw_max_grondslag == 75860
    assert fp.repr_aftrek_pct == 80


@pytest.mark.asyncio
async def test_seed_box3_definitieve_rendementen(db):
    """Verify Box 3 uses definitive (not preliminary) percentages."""
    await seed_all(db)

    # 2023: definitief
    fp23 = await get_fiscale_params(db, jaar=2023)
    assert fp23.box3_rendement_bank_pct == 0.92  # was 0.36 (voorlopig)
    assert fp23.box3_rendement_schuld_pct == 2.46  # was 2.57
    assert fp23.box3_tarief_pct == 32

    # 2024: definitief
    fp24 = await get_fiscale_params(db, jaar=2024)
    assert fp24.box3_rendement_bank_pct == 1.44  # was 1.03
    assert fp24.box3_rendement_overig_pct == 6.04  # was 6.17
    assert fp24.box3_rendement_schuld_pct == 2.61  # was 2.46
    assert fp24.box3_tarief_pct == 36  # was 32

    # 2025: definitief (source: belastingdienst.nl)
    fp25 = await get_fiscale_params(db, jaar=2025)
    assert fp25.box3_rendement_bank_pct == 1.37  # was 1.28 (voorlopig)
    assert fp25.box3_rendement_overig_pct == 5.88  # was 6.04 (voorlopig)
    assert fp25.box3_rendement_schuld_pct == 2.70  # was 2.47 (voorlopig)


@pytest.mark.asyncio
async def test_seed_drempel_schulden(db):
    """Verify box3_drempel_schulden is set per year."""
    await seed_all(db)

    fp23 = await get_fiscale_params(db, jaar=2023)
    assert fp23.box3_drempel_schulden == 3400

    fp24 = await get_fiscale_params(db, jaar=2024)
    assert fp24.box3_drempel_schulden == 3700

    fp25 = await get_fiscale_params(db, jaar=2025)
    assert fp25.box3_drempel_schulden == 3700


@pytest.mark.asyncio
async def test_seed_2026_box3_values(db):
    """Verify 2026 Box 3 values match Belastingdienst official (not copied from 2025)."""
    await seed_fiscale_params(db)
    fp = await get_fiscale_params(db, jaar=2026)
    assert fp.box3_heffingsvrij_vermogen == 59357
    assert fp.box3_drempel_schulden == 3800
    assert fp.box3_rendement_bank_pct == pytest.approx(1.28)
    assert fp.box3_rendement_overig_pct == pytest.approx(6.00)
    assert fp.box3_rendement_schuld_pct == pytest.approx(2.70)
    assert fp.box3_tarief_pct == 36


@pytest.mark.asyncio
async def test_seed_zvw_max_2024(db):
    """Verify ZVW max grondslag 2024 = 71628 (not 71624)."""
    await seed_all(db)
    fp = await get_fiscale_params(db, jaar=2024)
    assert fp.zvw_max_grondslag == 71628


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


@pytest.mark.asyncio
async def test_seed_za_sa_toggles(db):
    """Verify za_actief/sa_actief defaults: SA active for 2023-2025, not 2026."""
    await seed_all(db)

    for jaar in [2023, 2024, 2025]:
        fp = await get_fiscale_params(db, jaar=jaar)
        assert fp.za_actief is True, f"za_actief should be True for {jaar}"
        assert fp.sa_actief is True, f"sa_actief should be True for {jaar}"

    fp26 = await get_fiscale_params(db, jaar=2026)
    assert fp26.za_actief is True
    assert fp26.sa_actief is False, "sa_actief should be False for 2026 (year 4+)"
