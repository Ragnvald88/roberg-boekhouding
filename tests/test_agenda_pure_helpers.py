from datetime import date

import pytest

from services.agenda import (
    categorize_werkdag, derive_werkdag_status_label, parse_weekdays,
)
from database import ValidationError


# ---- categorize_werkdag ----

@pytest.mark.parametrize('code,expected', [
    ('WERKDAG', 'dagpraktijk'),
    ('WEEKEND_DAG', 'dagpraktijk'),
    ('', 'dagpraktijk'),  # default treated as dagpraktijk
])
def test_categorize_werkdag_dagpraktijk_codes(code, expected):
    assert categorize_werkdag(code) == expected


@pytest.mark.parametrize('code', ['ANW_AVOND', 'ANW_NACHT', 'ANW_WEEKEND', 'AVOND', 'NACHT'])
def test_categorize_werkdag_anw_codes(code):
    assert categorize_werkdag(code) == 'anw'


@pytest.mark.parametrize('code', ['ACHTERWACHT', 'CONGRES', 'OPLEIDING', 'OVERIG_ZAK', 'UNKNOWN'])
def test_categorize_werkdag_overig_codes(code):
    assert categorize_werkdag(code) == 'overig'


# ---- derive_werkdag_status_label ----

class FakeWerkdag:
    def __init__(self, factuurnummer='', factuur_status='', factuur_vervaldatum=''):
        self.factuurnummer = factuurnummer
        self.factuur_status = factuur_status
        self.factuur_vervaldatum = factuur_vervaldatum


def test_status_ongefactureerd_when_no_factuurnummer():
    w = FakeWerkdag()
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'ongefactureerd'


def test_status_concept():
    w = FakeWerkdag(factuurnummer='2026-001', factuur_status='concept')
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'concept'


def test_status_verstuurd_with_future_vervaldatum():
    w = FakeWerkdag(
        factuurnummer='2026-001',
        factuur_status='verstuurd',
        factuur_vervaldatum='2026-06-01',
    )
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'verstuurd'


def test_status_verlopen_when_vervaldatum_past():
    w = FakeWerkdag(
        factuurnummer='2026-001',
        factuur_status='verstuurd',
        factuur_vervaldatum='2026-04-15',
    )
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'verlopen'


def test_status_verstuurd_today_is_not_verlopen():
    """Vervaldatum == today should still be 'verstuurd' (not yet expired)."""
    w = FakeWerkdag(
        factuurnummer='2026-001',
        factuur_status='verstuurd',
        factuur_vervaldatum='2026-05-13',
    )
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'verstuurd'


def test_status_betaald():
    w = FakeWerkdag(factuurnummer='2026-001', factuur_status='betaald')
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'betaald'


def test_status_unknown_status_falls_back_to_ongefactureerd():
    """Defensive: if factuur_status is unexpected (e.g. 'verstuurd' without vervaldatum),
    or some new status we haven't handled, return 'ongefactureerd' as safe default."""
    w = FakeWerkdag(factuurnummer='2026-001', factuur_status='unknown_future_status')
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'ongefactureerd'


# ---- parse_weekdays ----

def test_parse_weekdays_valid_csv():
    assert parse_weekdays('1,3,5') == [1, 3, 5]


def test_parse_weekdays_single_value():
    assert parse_weekdays('1') == [1]


def test_parse_weekdays_sorted():
    """Output should be sorted regardless of input order."""
    assert parse_weekdays('5,1,3') == [1, 3, 5]


def test_parse_weekdays_empty_raises():
    with pytest.raises(ValidationError):
        parse_weekdays('')


def test_parse_weekdays_invalid_value_raises():
    with pytest.raises(ValidationError):
        parse_weekdays('1,8,3')  # 8 is invalid


def test_parse_weekdays_zero_raises():
    with pytest.raises(ValidationError):
        parse_weekdays('0,1')  # 0 is invalid (ISO weekdays start at 1)


def test_parse_weekdays_duplicates_raise():
    with pytest.raises(ValidationError):
        parse_weekdays('1,3,1')


def test_parse_weekdays_non_numeric_raises():
    with pytest.raises(ValidationError):
        parse_weekdays('a,b')


def test_parse_weekdays_whitespace_tolerant():
    """Tolerate spaces around commas (e.g. from copy-paste)."""
    assert parse_weekdays('1, 3, 5') == [1, 3, 5]
