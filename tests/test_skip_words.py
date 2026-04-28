"""Tests for derive_skip_words and _normalize_phone_digits."""

import pytest
from types import SimpleNamespace
from import_.skip_words import (
    GENERIC_SKIP_WORDS, derive_skip_words, _normalize_phone_digits,
)


def _bg(**overrides):
    base = dict(naam='', bedrijfsnaam='', adres='', postcode_plaats='',
                telefoon='', email='', kvk='', iban='')
    base.update(overrides)
    return SimpleNamespace(**base)


def test_normalize_phone_plain_06():
    assert _normalize_phone_digits('06 4326 7791') == '0643267791'

def test_normalize_phone_plus31():
    assert _normalize_phone_digits('+31 6 4326 7791') == '0643267791'

def test_normalize_phone_0031():
    assert _normalize_phone_digits('0031 6 4326 7791') == '0643267791'

def test_normalize_phone_compact_0031():
    assert _normalize_phone_digits('0031643267791') == '0643267791'

def test_normalize_phone_too_short():
    assert _normalize_phone_digits('06 12') is None

def test_normalize_phone_empty():
    assert _normalize_phone_digits('') is None


def test_derive_none_returns_generic():
    assert derive_skip_words(None) == GENERIC_SKIP_WORDS


def test_derive_full_bg_includes_personal_tokens():
    bg = _bg(naam='Test Persoon', bedrijfsnaam='TestBV',
             adres='Hoofdstraat 1', postcode_plaats='1234 AB Stad',
             telefoon='06 4326 7791', email='info@example.nl')
    result = derive_skip_words(bg)
    for token in ('Test Persoon', 'TestBV', 'Hoofdstraat 1',
                  '1234 AB', 'Stad',
                  '0643', '064326', '06 432', '0643267791',
                  'info@example.nl', 'info'):
        assert token in result, f'missing: {token!r}'


def test_derive_postcode_no_match_uses_full_string():
    bg = _bg(postcode_plaats='Just a city')
    result = derive_skip_words(bg)
    assert 'Just a city' in result


def test_derive_email_without_at_no_local_part():
    bg = _bg(email='broken-email')
    result = derive_skip_words(bg)
    assert 'broken-email' in result
    assert 'broken' not in result


def test_derive_postcode_no_space_variant():
    bg = _bg(postcode_plaats='1234AB Stad')
    result = derive_skip_words(bg)
    assert '1234AB' in result
    assert 'Stad' in result


def test_derive_short_telefoon_skipped():
    bg = _bg(telefoon='12345')
    result = derive_skip_words(bg)
    assert '12345' not in result
