"""Tests voor dashboard redesign helpers."""

from components.utils import format_euro


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
