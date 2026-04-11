"""Tests for fiscale_params input validation in pages/instellingen.py."""

from pages.instellingen import _validate_fiscal_params


VALID_2024 = {
    'schijf1_grens': 38883, 'schijf2_grens': 78426,
    'schijf1_pct': 35.75, 'schijf2_pct': 37.56, 'schijf3_pct': 49.50,
    'mkb_vrijstelling_pct': 12.70, 'kia_pct': 28,
    'kia_ondergrens': 2901, 'kia_bovengrens': 70602,
    'ahk_max': 3115, 'ahk_drempel': 29736, 'ak_max': 5685,
    'zelfstandigenaftrek': 3750,
    'pvv_aow_pct': 17.90, 'pvv_anw_pct': 0.10, 'pvv_wlz_pct': 9.65,
    'zvw_pct': 4.85, 'ew_forfait_pct': 0.35, 'repr_aftrek_pct': 80,
}


def test_validate_fiscal_params_accepts_valid():
    assert _validate_fiscal_params(VALID_2024) == []


def test_validate_fiscal_params_rejects_negative_grens():
    bad = dict(VALID_2024)
    bad['schijf1_grens'] = -100
    errors = _validate_fiscal_params(bad)
    assert any('Schijf 1' in e for e in errors)


def test_validate_fiscal_params_rejects_non_monotonic_grenzen():
    bad = dict(VALID_2024)
    bad['schijf1_grens'] = 50000
    bad['schijf2_grens'] = 30000
    errors = _validate_fiscal_params(bad)
    assert any('Schijf 2' in e for e in errors)


def test_validate_fiscal_params_rejects_pct_above_100():
    bad = dict(VALID_2024)
    bad['schijf1_pct'] = 150
    errors = _validate_fiscal_params(bad)
    assert any('schijf1_pct' in e for e in errors)


def test_validate_fiscal_params_rejects_negative_ahk():
    bad = dict(VALID_2024)
    bad['ahk_max'] = -1
    errors = _validate_fiscal_params(bad)
    assert any('ahk_max' in e for e in errors)


def test_validate_fiscal_params_rejects_kia_boven_below_onder():
    bad = dict(VALID_2024)
    bad['kia_bovengrens'] = 100
    bad['kia_ondergrens'] = 500
    errors = _validate_fiscal_params(bad)
    assert any('KIA' in e for e in errors)


def test_validate_fiscal_params_rejects_negative_pvv():
    bad = dict(VALID_2024)
    bad['pvv_aow_pct'] = -1
    errors = _validate_fiscal_params(bad)
    assert any('pvv_aow_pct' in e for e in errors)
