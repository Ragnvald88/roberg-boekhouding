"""Tests voor format_datum_lang — ISO datum → Nederlands lang formaat."""

from components.utils import format_datum_lang


def test_zaterdag_9_mei_2026():
    assert format_datum_lang('2026-05-09') == 'zaterdag 9 mei 2026'


def test_donderdag_31_december_2026():
    assert format_datum_lang('2026-12-31') == 'donderdag 31 december 2026'


def test_empty_string_returns_empty():
    assert format_datum_lang('') == ''


def test_invalid_string_returns_empty():
    assert format_datum_lang('niet-een-datum') == ''
