"""Tests for fiscale_params input validation in pages/instellingen.py."""

import re
from pathlib import Path

from pages.instellingen import (
    _validate_arbeidskorting_brackets,
    _validate_fiscal_params,
)


INSTELLINGEN_SRC = Path(__file__).resolve().parent.parent / 'pages' / 'instellingen.py'


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


# --- Arbeidskorting brackets validator -----------------------------------

VALID_BRACKETS = [
    {'lower': 0, 'upper': 11490, 'rate': 0.08425, 'base': 0},
    {'lower': 11490, 'upper': 24820, 'rate': 0.31433, 'base': 968},
    {'lower': 24820, 'upper': 39957, 'rate': 0.02471, 'base': 5158},
    {'lower': 39957, 'upper': 124934, 'rate': -0.06510, 'base': 5532},
    {'lower': 124934, 'upper': None, 'rate': 0, 'base': 0},
]


def test_validate_ak_brackets_accepts_canonical_2024():
    assert _validate_arbeidskorting_brackets(VALID_BRACKETS) == []


def test_validate_ak_brackets_rejects_empty_list():
    errors = _validate_arbeidskorting_brackets([])
    assert any('minstens 1 schijf' in e for e in errors)


def test_validate_ak_brackets_rejects_non_list():
    errors = _validate_arbeidskorting_brackets('not a list')  # type: ignore[arg-type]
    assert any('minstens 1 schijf' in e for e in errors)


def test_validate_ak_brackets_rejects_missing_field():
    bad = [dict(VALID_BRACKETS[0])]
    del bad[0]['rate']
    errors = _validate_arbeidskorting_brackets(bad)
    assert any('rate' in e for e in errors)


def test_validate_ak_brackets_rejects_non_contiguous():
    bad = [dict(b) for b in VALID_BRACKETS]
    # Break contiguity between schijf 1 and 2
    bad[0]['upper'] = 10000  # was 11490 = lower of bracket[1]
    errors = _validate_arbeidskorting_brackets(bad)
    assert any('aaneensluiten' in e for e in errors)


def test_validate_ak_brackets_rejects_descending_lower():
    bad = [dict(b) for b in VALID_BRACKETS]
    bad[2]['lower'] = 10  # was 24820 — now lower than bracket[1].lower
    errors = _validate_arbeidskorting_brackets(bad)
    assert any('groter zijn dan' in e for e in errors)


def test_validate_ak_brackets_rejects_open_upper_in_non_last():
    bad = [
        {'lower': 0, 'upper': None, 'rate': 0.08, 'base': 0},  # not allowed
        {'lower': 0, 'upper': None, 'rate': 0, 'base': 0},
    ]
    errors = _validate_arbeidskorting_brackets(bad)
    assert any('laatste schijf' in e for e in errors)


def test_validate_ak_brackets_accepts_open_upper_in_last():
    bracket = [
        {'lower': 0, 'upper': 100, 'rate': 0.10, 'base': 0},
        {'lower': 100, 'upper': None, 'rate': 0, 'base': 0},
    ]
    assert _validate_arbeidskorting_brackets(bracket) == []


def test_validate_ak_brackets_rejects_rate_above_one():
    bad = [{'lower': 0, 'upper': None, 'rate': 1.5, 'base': 0}]
    errors = _validate_arbeidskorting_brackets(bad)
    assert any('tarief' in e.lower() for e in errors)


def test_validate_ak_brackets_accepts_negative_rate_in_afbouw():
    """Arbeidskorting heeft een afbouwband met negatief tarief (~ -0.06510)."""
    bracket = [
        {'lower': 0, 'upper': 50000, 'rate': 0.30, 'base': 0},
        {'lower': 50000, 'upper': None, 'rate': -0.0651, 'base': 0},
    ]
    assert _validate_arbeidskorting_brackets(bracket) == []


def test_validate_ak_brackets_rejects_negative_base():
    bad = [{'lower': 0, 'upper': None, 'rate': 0, 'base': -1}]
    errors = _validate_arbeidskorting_brackets(bad)
    assert any('basisbedrag' in e for e in errors)


def test_validate_ak_brackets_rejects_negative_lower():
    bad = [
        {'lower': -1, 'upper': 100, 'rate': 0, 'base': 0},
        {'lower': 100, 'upper': None, 'rate': 0, 'base': 0},
    ]
    errors = _validate_arbeidskorting_brackets(bad)
    assert any('ondergrens' in e for e in errors)


def test_validate_ak_brackets_rejects_string_lower_without_typeerror():
    """Malformed JSON with strings where numbers expected must produce a
    Dutch validation error, not crash with TypeError."""
    bad = [
        {'lower': 'abc', 'upper': 100, 'rate': 0.1, 'base': 0},
        {'lower': 100, 'upper': None, 'rate': 0, 'base': 0},
    ]
    # The key invariant: no TypeError raised. Errors list must be non-empty.
    errors = _validate_arbeidskorting_brackets(bad)
    assert errors
    assert any('ondergrens' in e and 'getal' in e for e in errors)


def test_validate_ak_brackets_rejects_bool_as_number():
    """isinstance check must reject booleans (which are int in Python)."""
    bad = [
        {'lower': 0, 'upper': True, 'rate': 0.1, 'base': 0},
        {'lower': True, 'upper': None, 'rate': 0, 'base': 0},
    ]
    errors = _validate_arbeidskorting_brackets(bad)
    assert errors


# === L8/U3 — _is_num NaN/Infinity defenses ===

def test_validate_arbeidskorting_brackets_rejects_nan():
    """U3: a NaN literal in lower/upper/rate/base must be rejected as
    a non-number, not silently passed through. NaN compares False to
    everything, so an undetected NaN bracket would silently fall out of
    the engine without an error.
    """
    nan = float('nan')
    bad = [
        {'lower': 0, 'upper': 100, 'rate': nan, 'base': 0},
        {'lower': 100, 'upper': None, 'rate': 0, 'base': 0},
    ]
    errors = _validate_arbeidskorting_brackets(bad)
    assert errors
    assert any('tarief' in e.lower() for e in errors)


def test_validate_arbeidskorting_brackets_rejects_infinity():
    """U3: ±Infinity must also be rejected — only the LAST bracket may
    have an open upper, and that is encoded as `None`, not Infinity.
    """
    inf = float('inf')
    bad = [
        {'lower': 0, 'upper': inf, 'rate': 0.1, 'base': 0},
        {'lower': inf, 'upper': None, 'rate': 0, 'base': 0},
    ]
    errors = _validate_arbeidskorting_brackets(bad)
    assert errors


def test_validate_arbeidskorting_brackets_rejects_negative_infinity():
    """U3: -Infinity must be rejected as a number (NaN-equivalent)."""
    neg_inf = float('-inf')
    bad = [
        {'lower': neg_inf, 'upper': 100, 'rate': 0.1, 'base': 0},
        {'lower': 100, 'upper': None, 'rate': 0, 'base': 0},
    ]
    errors = _validate_arbeidskorting_brackets(bad)
    assert errors


def test_validate_arbeidskorting_brackets_rejects_bool_as_lower():
    """U3 (defense): bool sub-classes int but is NOT a legitimate grens.
    The pre-existing `not isinstance(x, bool)` check must remain, because
    True/False would otherwise compare against a Decimal grondslag and
    silently produce 0/1 schijven.
    """
    bad = [
        {'lower': True, 'upper': 100, 'rate': 0.1, 'base': 0},
        {'lower': 100, 'upper': None, 'rate': 0, 'base': 0},
    ]
    errors = _validate_arbeidskorting_brackets(bad)
    assert errors


# --- Source-pin tests for the UI behaviour --------------------------------

def test_save_params_catches_yearlocked():
    """save_params has a try/except YearLockedError around upsert."""
    src = INSTELLINGEN_SRC.read_text()
    # Find the save_params function body inside the page closure
    save_idx = src.find('async def save_params(')
    assert save_idx != -1
    body = src[save_idx:save_idx + 4000]
    assert 'YearLockedError' in body, (
        'save_params must handle YearLockedError so a definitief-jaar save '
        'shows a Dutch warning instead of raising an unhandled background '
        'traceback')


def test_add_jaar_catches_yearlocked():
    src = INSTELLINGEN_SRC.read_text()
    add_idx = src.find('async def add_jaar(')
    assert add_idx != -1
    body = src[add_idx:add_idx + 6000]
    assert 'YearLockedError' in body


def test_add_jaar_copies_kia_bracket_fields():
    """The 'Kopieer vorig jaar' kwargs must include all 4 KIA bracket params."""
    src = INSTELLINGEN_SRC.read_text()
    add_idx = src.find('async def add_jaar(')
    assert add_idx != -1
    body = src[add_idx:add_idx + 8000]
    for fld in (
        'kia_plateau_bedrag', 'kia_plateau_eind',
        'kia_afbouw_eind', 'kia_afbouw_pct',
        'kia_drempel_per_item',
    ):
        assert f"'{fld}': latest.{fld}" in body, (
            f'add_jaar must copy {fld} from the previous year so a new'
            f' year template inherits the KIA bracket configuration')


def test_add_jaar_copies_partner_toggles():
    src = INSTELLINGEN_SRC.read_text()
    add_idx = src.find('async def add_jaar(')
    assert add_idx != -1
    body = src[add_idx:add_idx + 8000]
    assert 'ew_naar_partner' in body
    assert 'box3_fiscaal_partner' in body


def test_kia_bracket_fields_present_in_grouped_fields():
    """Investeringsaftrek section in the page exposes all 4 KIA bracket
    params as editable inputs (not just read-only text)."""
    src = INSTELLINGEN_SRC.read_text()
    for fld in (
        'kia_plateau_bedrag', 'kia_plateau_eind',
        'kia_afbouw_eind', 'kia_afbouw_pct',
    ):
        # Each field must appear as a tuple-key in the grouped_fields list.
        # The pattern is: ('label …', 'kia_xxx', '%.0f', 1)
        pattern = rf"'{re.escape(fld)}'"
        assert re.search(pattern, src), (
            f'{fld} must appear as a key in the grouped_fields metadata so'
            f' the user can edit it via /instellingen')


def test_partner_toggles_are_editable_checkboxes():
    src = INSTELLINGEN_SRC.read_text()
    assert 'ew_naar_partner' in src
    assert 'box3_fiscaal_partner' in src
    # And they must be wired as inputs (so save_params reads .value)
    assert "inputs['ew_naar_partner']" in src
    assert "inputs['box3_fiscaal_partner']" in src


def test_arbeidskorting_brackets_editable_via_save_path():
    """Save path must json.dumps(bracket_state) — proving the brackets are
    serialised back to DB rather than only displayed read-only."""
    src = INSTELLINGEN_SRC.read_text()
    assert 'json.dumps(\n                                        bracket_ref)' in src or \
           'json.dumps(bracket_ref)' in src.replace('\n', '').replace(' ', ''), (
        'save_params must serialise bracket_state back to JSON; without this '
        'the AK editor only updates the in-memory list')


def test_arbeidskorting_brackets_validated_before_save():
    src = INSTELLINGEN_SRC.read_text()
    save_idx = src.find('async def save_params(')
    assert save_idx != -1
    body = src[save_idx:save_idx + 6000]
    assert '_validate_arbeidskorting_brackets' in body


def test_locked_year_save_is_blocked():
    """A definitief-jaar save shows a warning toast instead of mutating."""
    src = INSTELLINGEN_SRC.read_text()
    save_idx = src.find('async def save_params(')
    assert save_idx != -1
    body = src[save_idx:save_idx + 6000]
    assert 'if locked:' in body
    assert 'definitief' in body
