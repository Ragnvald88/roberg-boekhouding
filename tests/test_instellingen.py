"""Tests for fiscale_params input validation in pages/instellingen.py."""

from pages.instellingen import _validate_fiscal_params


VALID_2024 = {
    'schijf1_grens': 38883, 'schijf2_grens': 78426,
    'schijf1_pct': 35.75, 'schijf2_pct': 37.56, 'schijf3_pct': 49.50,
    'mkb_vrijstelling_pct': 12.70, 'kia_pct': 28,
    'kia_ondergrens': 2901, 'kia_bovengrens': 70602,
    'ahk_max': 3115, 'ahk_drempel': 29736, 'ahk_afbouw_pct': 6.095,
    'ak_max': 5685,
    'zelfstandigenaftrek': 3750,
    'pvv_aow_pct': 17.90, 'pvv_anw_pct': 0.10, 'pvv_wlz_pct': 9.65,
    'pvv_premiegrondslag': 38098,
    'zvw_pct': 4.85, 'zvw_max_grondslag': 66956,
    'ew_forfait_pct': 0.35, 'repr_aftrek_pct': 80,
    # Fields that became required after silent-fallback fix:
    'villataks_grens': 1_350_000, 'wet_hillen_pct': 66.0,
    'urencriterium': 1225, 'arbeidskorting_brackets': '[]',
    'box3_heffingsvrij_vermogen': 57000,
    'box3_rendement_bank_pct': 1.44, 'box3_rendement_overig_pct': 5.88,
    'box3_rendement_schuld_pct': 2.61, 'box3_tarief_pct': 36,
    'box3_drempel_schulden': 3700,
}


def test_validate_fiscal_params_accepts_valid():
    assert _validate_fiscal_params(VALID_2024) == []


def test_validate_fiscal_params_rejects_negative_grens():
    bad = dict(VALID_2024)
    bad['schijf1_grens'] = -100
    errors = _validate_fiscal_params(bad)
    assert any('schijf1_grens' in e for e in errors)


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


def test_validate_rejects_missing_repr_aftrek_pct():
    """Absent required positive-percentage field triggers explicit error,
    rather than silently being coerced to 0 (which would pass the old
    `0 <= v <= 100` check and write 0% representatie bijtelling)."""
    bad = dict(VALID_2024)
    del bad['repr_aftrek_pct']
    errors = _validate_fiscal_params(bad)
    assert any('repr_aftrek_pct' in e for e in errors)


def test_validate_rejects_none_repr_aftrek_pct():
    """Explicit None (user cleared the field) is also a validation error."""
    bad = dict(VALID_2024)
    bad['repr_aftrek_pct'] = None
    errors = _validate_fiscal_params(bad)
    assert any('repr_aftrek_pct' in e for e in errors)


def test_validate_rejects_zero_pvv_aow_pct():
    """0 is not a legitimate PVV AOW percentage — must flag."""
    bad = dict(VALID_2024)
    bad['pvv_aow_pct'] = 0
    errors = _validate_fiscal_params(bad)
    assert any('pvv_aow_pct' in e for e in errors)


def test_validate_rejects_zero_ew_forfait_pct():
    """0 is not a legitimate EW forfait percentage — must flag."""
    bad = dict(VALID_2024)
    bad['ew_forfait_pct'] = 0
    errors = _validate_fiscal_params(bad)
    assert any('ew_forfait_pct' in e for e in errors)


def test_validate_rejects_missing_ahk_afbouw_pct():
    """ahk_afbouw_pct is required — fiscal engine crashes on None."""
    bad = dict(VALID_2024)
    del bad['ahk_afbouw_pct']
    errors = _validate_fiscal_params(bad)
    assert any('ahk_afbouw_pct' in e for e in errors)


def test_validate_rejects_missing_zvw_max_grondslag():
    """zvw_max_grondslag is required — fiscal engine crashes on None."""
    bad = dict(VALID_2024)
    del bad['zvw_max_grondslag']
    errors = _validate_fiscal_params(bad)
    assert any('zvw_max_grondslag' in e for e in errors)


def test_validate_rejects_missing_pvv_premiegrondslag():
    """pvv_premiegrondslag is required — wrong PVV if zero."""
    bad = dict(VALID_2024)
    del bad['pvv_premiegrondslag']
    errors = _validate_fiscal_params(bad)
    assert any('pvv_premiegrondslag' in e for e in errors)


def test_validate_accepts_zero_for_optional_aftrekposten():
    """startersaftrek = 0 is legitimate (user no longer in starter window)."""
    p = dict(VALID_2024)
    p['startersaftrek'] = 0
    p['zelfstandigenaftrek'] = 3500
    errors = _validate_fiscal_params(p)
    assert not any('startersaftrek' in e for e in errors)
    assert not any('zelfstandigenaftrek' in e for e in errors)


def test_validate_rejects_missing_villataks_grens():
    """villataks_grens is required — hardcoded silent default removed."""
    bad = dict(VALID_2024)
    del bad['villataks_grens']
    errors = _validate_fiscal_params(bad)
    assert any('villataks_grens' in e for e in errors)


def test_validate_rejects_missing_urencriterium():
    bad = dict(VALID_2024)
    del bad['urencriterium']
    errors = _validate_fiscal_params(bad)
    assert any('urencriterium' in e for e in errors)


def test_validate_rejects_missing_box3_heffingsvrij_vermogen():
    bad = dict(VALID_2024)
    del bad['box3_heffingsvrij_vermogen']
    errors = _validate_fiscal_params(bad)
    assert any('box3_heffingsvrij_vermogen' in e for e in errors)


def test_validate_rejects_missing_box3_rendement_bank_pct():
    bad = dict(VALID_2024)
    del bad['box3_rendement_bank_pct']
    errors = _validate_fiscal_params(bad)
    assert any('box3_rendement_bank_pct' in e for e in errors)


def test_validate_accepts_zero_wet_hillen_pct():
    """wet_hillen_pct = 0 is legitimate (post-uitfasering)."""
    p = dict(VALID_2024)
    p['wet_hillen_pct'] = 0
    errors = _validate_fiscal_params(p)
    assert not any('wet_hillen_pct' in e for e in errors)


def test_validate_rejects_missing_wet_hillen_pct():
    """Absent wet_hillen_pct must flag — presence required, even if value 0."""
    bad = dict(VALID_2024)
    del bad['wet_hillen_pct']
    errors = _validate_fiscal_params(bad)
    assert any('wet_hillen_pct' in e for e in errors)


def test_validate_accepts_zero_box3_rendement_schuld_pct():
    """Rendement op schulden = 0 is legitiem voor wie geen Box-3-schulden heeft."""
    p = dict(VALID_2024)
    p['box3_rendement_schuld_pct'] = 0
    errors = _validate_fiscal_params(p)
    assert not any('box3_rendement_schuld_pct' in e for e in errors)


def test_validate_accepts_zero_box3_drempel_schulden():
    """Drempel schulden = 0 is legitiem (geen schulden)."""
    p = dict(VALID_2024)
    p['box3_drempel_schulden'] = 0
    errors = _validate_fiscal_params(p)
    assert not any('box3_drempel_schulden' in e for e in errors)


def test_validate_rejects_empty_arbeidskorting_brackets():
    bad = dict(VALID_2024)
    bad['arbeidskorting_brackets'] = ''
    errors = _validate_fiscal_params(bad)
    assert any('arbeidskorting_brackets' in e for e in errors)


def test_validate_rejects_missing_arbeidskorting_brackets():
    bad = dict(VALID_2024)
    del bad['arbeidskorting_brackets']
    errors = _validate_fiscal_params(bad)
    assert any('arbeidskorting_brackets' in e for e in errors)
