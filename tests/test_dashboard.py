"""Tests voor dashboard + facturen helpers."""

from datetime import date, timedelta

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


# --- _is_verlopen tests ---


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


# --- generate_csv tests ---

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
