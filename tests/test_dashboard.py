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
