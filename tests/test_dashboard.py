"""Tests voor dashboard + facturen helpers."""

from datetime import date, timedelta

import pytest

from components.utils import format_euro
from pages.facturen import _is_verlopen


def test_format_euro_default_2_decimals():
    assert format_euro(1234.56) == '\u20ac 1.234,56'


def test_format_euro_zero_decimals():
    assert format_euro(1234.56, decimals=0) == '\u20ac 1.235'


def test_format_euro_zero_decimals_thousands():
    assert format_euro(28702.52, decimals=0) == '\u20ac 28.703'


def test_format_euro_none_zero_decimals():
    assert format_euro(None, decimals=0) == '\u20ac 0'


def test_format_euro_negative_zero_decimals():
    assert format_euro(-8177.95, decimals=0) == '\u20ac -8.178'




def test_verlopen_13_days_ago_not_overdue():
    d = (date.today() - timedelta(days=13)).isoformat()
    assert _is_verlopen(d) is False


def test_verlopen_15_days_ago_is_overdue():
    d = (date.today() - timedelta(days=15)).isoformat()
    assert _is_verlopen(d) is True


def test_verlopen_14_days_ago_not_overdue():
    """Day 14 = vervaldatum itself, not yet verlopen (strict < comparison)."""
    d = (date.today() - timedelta(days=14)).isoformat()
    assert _is_verlopen(d) is False


def test_verlopen_invalid_date():
    assert _is_verlopen('not-a-date') is False


def test_verlopen_empty_string():
    assert _is_verlopen('') is False


# === Lane 4: _has_va_data helper (Plan 2026-04-26) ===

from pages.dashboard import _has_va_data
from models import FiscaleParams


def _fp(va_ib=0.0, va_zvw=0.0):
    """Minimal FiscaleParams for VA-detection tests."""
    return FiscaleParams(
        jaar=2026,
        voorlopige_aanslag_betaald=va_ib,
        voorlopige_aanslag_zvw=va_zvw,
    )


def test_has_va_data_false_when_nothing_entered():
    """No fiscale_params + no bank data → no VA at all."""
    assert _has_va_data(None, {'has_bank_data': False}) is False


def test_has_va_data_false_when_fp_zero_and_no_bank():
    fp = _fp(va_ib=0.0, va_zvw=0.0)
    assert _has_va_data(fp, {'has_bank_data': False}) is False


def test_has_va_data_true_when_only_ib_va_entered():
    fp = _fp(va_ib=12000.0, va_zvw=0.0)
    assert _has_va_data(fp, {'has_bank_data': False}) is True


def test_has_va_data_true_when_only_zvw_va_entered():
    """The bug we're fixing: ZVW-only manual entry must register as VA."""
    fp = _fp(va_ib=0.0, va_zvw=2400.0)
    assert _has_va_data(fp, {'has_bank_data': False}) is True


def test_has_va_data_true_when_only_bank_data():
    """Bank-imported VA payments (no manual entry) still register."""
    assert _has_va_data(None, {'has_bank_data': True}) is True
    fp = _fp(va_ib=0.0, va_zvw=0.0)
    assert _has_va_data(fp, {'has_bank_data': True}) is True


def test_has_va_data_handles_missing_va_data_key():
    """va_data without 'has_bank_data' key (defensive) should not crash."""
    fp = _fp(va_ib=0.0, va_zvw=0.0)
    assert _has_va_data(fp, {}) is False
    fp2 = _fp(va_ib=100.0, va_zvw=0.0)
    assert _has_va_data(fp2, {}) is True



from components.utils import generate_csv


def test_generate_csv_basic():
    """Headers + rows → semicolon-separated output."""
    headers = ['Naam', 'Bedrag', 'Datum']
    rows = [
        ['Testpraktijk', '1234.56', '2026-01-15'],
        ['Andere Praktijk', '500.00', '2026-02-20'],
    ]
    result = generate_csv(headers, rows)
    lines = result.strip().splitlines()
    assert len(lines) == 3
    assert lines[0].strip() == 'Naam;Bedrag;Datum'
    assert lines[1].strip() == 'Testpraktijk;1234.56;2026-01-15'
    assert lines[2].strip() == 'Andere Praktijk;500.00;2026-02-20'


def test_generate_csv_special_chars():
    """Commas and quotes in data → properly escaped."""
    headers = ['Omschrijving', 'Bedrag']
    rows = [
        ['Lunch, diner & borrel', '45.00'],
        ['Item "special"', '10.00'],
    ]
    result = generate_csv(headers, rows)
    lines = result.strip().split('\n')
    # Semicolon delimiter: commas in data should NOT cause extra fields
    # The CSV writer should quote fields containing special characters
    assert 'Lunch, diner & borrel' in lines[1]
    assert '45.00' in lines[1]
    # Quotes in data should be escaped (doubled)
    assert '"special"' in lines[2] or 'special' in lines[2]
    # Verify the line parses back correctly with semicolon delimiter
    import csv
    import io
    reader = csv.reader(io.StringIO(result), delimiter=';')
    parsed = list(reader)
    assert parsed[1][0] == 'Lunch, diner & borrel'
    assert parsed[2][0] == 'Item "special"'


# ============================================================
# Dashboard prorata / IB estimate coverage (Workstream I.1)
#
# The dashboard's `_compute_ib_estimate` is a closure inside `dashboard_page`
# that composes three pieces: `fetch_fiscal_data`, `extrapoleer_jaaromzet`, and
# `bereken_volledig`. Extracting the closure would require passing DB_PATH and
# async helpers explicitly, a non-trivial refactor for questionable value.
#
# Instead we test the actual prorata engine (`extrapoleer_jaaromzet`) directly
# and wire up the full compose path for a past year to verify the dashboard
# orchestration produces sensible numbers.
# ============================================================


@pytest.mark.asyncio
async def test_extrapoleer_jaaromzet_past_year_returns_actual(db):
    """Past-year extrapolation must return ytd == extrapolated, high confidence."""
    from components.fiscal_utils import extrapoleer_jaaromzet
    from database import add_klant, add_factuur

    kid = await add_klant(db, naam='Past', tarief_uur=100)
    await add_factuur(
        db, nummer='2020-001', klant_id=kid,
        datum='2020-06-15', totaal_uren=10, totaal_km=0,
        totaal_bedrag=5000.00, status='verstuurd',
    )
    await add_factuur(
        db, nummer='2020-002', klant_id=kid,
        datum='2020-11-01', totaal_uren=10, totaal_km=0,
        totaal_bedrag=3000.00, status='betaald',
    )

    result = await extrapoleer_jaaromzet(db, 2020)
    assert result['ytd_omzet'] == 8000.00
    assert result['extrapolated_omzet'] == 8000.00
    assert result['method'] == 'actual'
    assert result['confidence'] == 'high'
    assert result['basis_maanden'] == 12


@pytest.mark.asyncio
async def test_extrapoleer_jaaromzet_past_year_no_data(db):
    """Past year with no data: ytd=0, extrapolated=0, confidence='high' (actual)."""
    from components.fiscal_utils import extrapoleer_jaaromzet

    result = await extrapoleer_jaaromzet(db, 2020)
    assert result['ytd_omzet'] == 0
    assert result['extrapolated_omzet'] == 0
    # Past years always use actual numbers -> high confidence even when zero
    assert result['confidence'] == 'high'
    assert result['method'] == 'actual'


@pytest.mark.asyncio
async def test_extrapoleer_jaaromzet_past_year_excludes_concept(db):
    """Concept invoices must NOT be counted in extrapolated omzet."""
    from components.fiscal_utils import extrapoleer_jaaromzet
    from database import add_klant, add_factuur

    kid = await add_klant(db, naam='ConceptTest', tarief_uur=100)
    await add_factuur(
        db, nummer='2021-001', klant_id=kid,
        datum='2021-06-15', totaal_uren=10, totaal_km=0,
        totaal_bedrag=1000.00, status='verstuurd',
    )
    await add_factuur(
        db, nummer='2021-002', klant_id=kid,
        datum='2021-07-01', totaal_uren=10, totaal_km=0,
        totaal_bedrag=2000.00, status='concept',
    )

    result = await extrapoleer_jaaromzet(db, 2021)
    assert result['ytd_omzet'] == 1000.00  # concept excluded
    assert result['extrapolated_omzet'] == 1000.00


@pytest.mark.asyncio
async def test_fetch_fiscal_data_with_seeded_past_year(db):
    """fetch_fiscal_data + the composed omzet path produces the number that
    `_compute_ib_estimate` would feed into `bereken_volledig` for a past year.

    This is the orchestration smoke test for the dashboard IB estimate path:
    past year branch (no extrapolation), so the result is deterministic and
    independent of today's date.
    """
    from components.fiscal_utils import fetch_fiscal_data
    from database import (
        add_klant, add_factuur, add_uitgave, upsert_fiscale_params,
    )
    from import_.seed_data import FISCALE_PARAMS

    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])

    kid = await add_klant(db, naam='OrchestrationTest', tarief_uur=100)
    # 80k omzet in 2024 — triggers IB in every relevant schijf
    await add_factuur(
        db, nummer='2024-X01', klant_id=kid,
        datum='2024-06-15', totaal_uren=800, totaal_km=0,
        totaal_bedrag=80000.00, status='betaald',
    )
    await add_uitgave(
        db, datum='2024-06-20', categorie='kantoor',
        omschrijving='Zakelijk', bedrag=5000.00, is_investering=0,
    )

    data = await fetch_fiscal_data(db, 2024)
    assert data is not None
    assert data['omzet'] == 80000.00
    assert data['kosten_excl_inv'] == 5000.00
    assert data['params_dict']['jaar'] == 2024

    # And now verify bereken_volledig produces a positive IB for the
    # business-only inputs the dashboard closure would pass
    from fiscal.berekeningen import bereken_volledig

    f = bereken_volledig(
        omzet=data['omzet'],
        kosten=data['kosten_excl_inv'],
        afschrijvingen=data['totaal_afschrijvingen'],
        representatie=data['representatie'],
        investeringen_totaal=data['inv_totaal_dit_jaar'],
        uren=data['uren'],
        params=data['params_dict'],
        aov=0, lijfrente=0, woz=0, hypotheekrente=0,
        voorlopige_aanslag=0,
        voorlopige_aanslag_zvw=0,
        ew_naar_partner=True,
    )
    # Sanity: business profit ~ 75000 → positive IB expected
    assert f.winst > 70000
    assert f.winst < 80000
    assert f.netto_ib > 0
    assert f.zvw > 0
