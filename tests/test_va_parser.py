"""Unit-tests voor services.va_parser.

Tests gebruiken ``parse_va_beschikking_text`` op geanonimiseerde
text-fixtures — pdftotext-subprocess is te broos/slow voor unit tests.

Fixtures (``tests/fixtures/va_beschikking_*_2026_anon.txt``) zijn een
echte 2026-PDF-output met fictieve naam/adres/aanslagnummer/kenmerk;
de structurele en regex-relevante details (labels, betaalblok,
termijnen-zin) zijn intact gehouden.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from services.va_parser import (
    ParsedBeschikking,
    VAParseError,
    parse_va_beschikking_text,
)


FIXTURES_DIR = Path(__file__).parent / 'fixtures'
IB_FIXTURE = FIXTURES_DIR / 'va_beschikking_ib_2026_anon.txt'
ZVW_FIXTURE = FIXTURES_DIR / 'va_beschikking_zvw_2026_anon.txt'


def _load(path: Path) -> str:
    return path.read_text(encoding='utf-8')


# ---- echte fixture-tests (2026 IB + ZVW) -------------------------------

def test_parse_va_ib_2026_real_fixture():
    """End-to-end op geanonimiseerde 2026 IB-beschikking-text."""
    parsed = parse_va_beschikking_text(_load(IB_FIXTURE))
    assert isinstance(parsed, ParsedBeschikking)
    assert parsed.jaar == 2026
    assert parsed.soort == 'ib'
    assert parsed.aanslagnummer == '9999.99.999.H.60.01'
    assert parsed.dagtekening == date(2026, 1, 31)
    assert parsed.bedrag == 30670.0
    assert parsed.betalingskenmerk == '9999999999990001'
    assert parsed.termijnen == 11


def test_parse_va_zvw_2026_real_fixture():
    """End-to-end op geanonimiseerde 2026 ZVW-beschikking-text."""
    parsed = parse_va_beschikking_text(_load(ZVW_FIXTURE))
    assert parsed.jaar == 2026
    assert parsed.soort == 'zvw'
    assert parsed.aanslagnummer == '9999.99.999.W.60.01.4'
    assert parsed.dagtekening == date(2026, 1, 31)
    assert parsed.bedrag == 2808.0
    assert parsed.betalingskenmerk == '9999999999990014'
    assert parsed.termijnen == 11


# ---- type-detect via aanslagnummer-suffix ------------------------------

# Minimal mock-text: alle critical fields aanwezig, alleen aanslag-suffix
# verschilt. Bedrag/kenmerk/dagtekening realistisch maar volledig fictief.
# We mimicen de echte BD-PDF-structuur: na kenmerk komt non-digit-text
# ("Betaalt u in termijnen?") vóórdat de termijnen-zin ergens later
# verschijnt — zodat de kenmerk-rechts-anker (?!\s*\d) niet ten onrechte
# de termijnen-int ('11') opslokt.
_MOCK_BASE = (
    'Voorlopige aanslag 2026 '
    'Aanslagnummer {aanslag} '
    'Dagtekening 31 januari 2026 '
    'Te betalen : € 1.000,00 '
    'Betalingskenmerk : 1234 5678 9012 3456 '
    'Betaalt u in termijnen? '
    'Het bedrag in 11 gelijke maandelijkse termijnen.'
)


def test_parse_type_detect_via_aanslagnummer_suffix_H():
    text = _MOCK_BASE.format(aanslag='1111.11.111.H.60.01')
    parsed = parse_va_beschikking_text(text)
    assert parsed.soort == 'ib'


def test_parse_type_detect_via_aanslagnummer_suffix_W():
    text = _MOCK_BASE.format(aanslag='1111.11.111.W.60.01.4')
    parsed = parse_va_beschikking_text(text)
    assert parsed.soort == 'zvw'


# ---- bedrag-parsing varianten ------------------------------------------

def test_parse_bedrag_dutch_thousands():
    """'30.670' (zonder decimaal) → 30670.0"""
    text = _MOCK_BASE.format(aanslag='1111.11.111.H.60.01').replace(
        'Te betalen : € 1.000,00',
        'Te betalen : € 30.670',
    )
    parsed = parse_va_beschikking_text(text)
    assert parsed.bedrag == 30670.0


def test_parse_bedrag_with_decimals():
    """'30.670,50' (met 2-decimal komma) → 30670.50"""
    text = _MOCK_BASE.format(aanslag='1111.11.111.H.60.01').replace(
        'Te betalen : € 1.000,00',
        'Te betalen : € 30.670,50',
    )
    parsed = parse_va_beschikking_text(text)
    assert parsed.bedrag == pytest.approx(30670.50)


# ---- dagtekening Nederlandse maand-naam --------------------------------

def test_parse_dagtekening_dutch_month():
    text = _MOCK_BASE.format(aanslag='1111.11.111.H.60.01').replace(
        'Dagtekening 31 januari 2026',
        'Dagtekening 15 mei 2026',
    )
    parsed = parse_va_beschikking_text(text)
    assert parsed.dagtekening == date(2026, 5, 15)


# ---- betalingskenmerk: spaties strippen --------------------------------

def test_parse_kenmerk_strips_spaces():
    """'9999 9999 9999 0001' (BD-format met groep-spaces) → 16 digits."""
    text = _MOCK_BASE.format(aanslag='1111.11.111.H.60.01').replace(
        'Betalingskenmerk : 1234 5678 9012 3456',
        'Betalingskenmerk : 9999 9999 9999 0001',
    )
    parsed = parse_va_beschikking_text(text)
    assert parsed.betalingskenmerk == '9999999999990001'
    assert len(parsed.betalingskenmerk) == 16


# ---- termijnen optional / default --------------------------------------

def test_parse_termijnen_default_11_when_missing():
    """Geen 'maandelijkse termijnen'-zin → fallback 11."""
    text = _MOCK_BASE.format(aanslag='1111.11.111.H.60.01').replace(
        '11 gelijke maandelijkse termijnen',
        '',
    )
    parsed = parse_va_beschikking_text(text)
    assert parsed.termijnen == 11


def test_parse_termijnen_out_of_range_falls_back_to_default():
    """Match maar buiten 1-12 range → fallback 11 (defensief)."""
    text = _MOCK_BASE.format(aanslag='1111.11.111.H.60.01').replace(
        '11 gelijke maandelijkse termijnen',
        '99 gelijke maandelijkse termijnen',
    )
    parsed = parse_va_beschikking_text(text)
    assert parsed.termijnen == 11


# ---- raise-paden voor missing critical fields --------------------------

def test_parse_missing_aanslagnummer_raises():
    """Geen aanslagnummer-match → VAParseError met diagnostiek."""
    text = (
        'Voorlopige aanslag 2026 '
        'Dagtekening 31 januari 2026 '
        'Te betalen : € 1.000,00 '
        'Betalingskenmerk : 1234 5678 9012 3456 '
        '11 gelijke maandelijkse termijnen'
    )
    with pytest.raises(VAParseError, match='aanslagnummer'):
        parse_va_beschikking_text(text)


def test_parse_missing_bedrag_raises():
    """Wel aanslagnummer + jaar + dagtekening + kenmerk, geen bedrag → raise."""
    text = (
        'Voorlopige aanslag 2026 '
        'Aanslagnummer 1111.11.111.H.60.01 '
        'Dagtekening 31 januari 2026 '
        'Betalingskenmerk : 1234 5678 9012 3456 '
        '11 gelijke maandelijkse termijnen'
    )
    with pytest.raises(VAParseError, match='bedrag'):
        parse_va_beschikking_text(text)


def test_parse_kenmerk_not_16_digits_raises():
    """Malformed kenmerk (geen 4×4-digit BD-format) → VAParseError.

    De strict 4×4-regex (NNNN NNNN NNNN NNNN) faalt op malformed input;
    caller krijgt VAParseError op het kenmerk-veld. Dit dekt user-visible
    failure-mode af: BD-PDF met afwijkend kenmerk-format wordt niet
    silently met een te kort/lang kenmerk in de DB gepompt.
    """
    text = _MOCK_BASE.format(aanslag='1111.11.111.H.60.01').replace(
        'Betalingskenmerk : 1234 5678 9012 3456',
        'Betalingskenmerk : 123 5678 9012 3456',  # 15 digits — geen 4×4 match
    )
    with pytest.raises(VAParseError, match='betalingskenmerk'):
        parse_va_beschikking_text(text)


# ---- regression: malformed bedrag/kenmerk silently parsen vermijden -------

@pytest.mark.parametrize('bad_bedrag', [
    '30670,00',     # geen thousands-dot maar wel 5 digits → was: matcht '306'
    '30.67,50',     # te-korte tussen-groep (2 digits) → was: matcht '30'
    '1.234.56',     # 2-digit "thousands"-tail (NL: zou ',56' moeten zijn)
    '30.670,5',     # 1-digit decimal (NL eist 2: ',NN')
    '30.670,500',   # 3-digit decimal (NL eist max 2: ',NN')
])
def test_parse_malformed_bedrag_raises_no_silent_partial(bad_bedrag):
    """Codex-catch: bedrag-regex zonder rechts-anker parst gedeeltelijk.

    Een rechts-anker (`(?![\\d.,])`) zorgt dat malformed bedragen falen
    ipv silent een truncate-versie te returnen. Concreet: '30670,00'
    moet VAParseError raisen (geen thousands-dot, niet BD-format),
    niet 306.0 returnen.
    """
    text = _MOCK_BASE.format(aanslag='1111.11.111.H.60.01').replace(
        'Te betalen : € 1.000,00',
        f'Te betalen : € {bad_bedrag}',
    )
    with pytest.raises(VAParseError, match='bedrag'):
        parse_va_beschikking_text(text)


def test_parse_kenmerk_with_trailing_digit_after_space_raises():
    """Codex-catch: trailing-digit-na-spatie mag niet silent geaccepteerd.

    '1234 5678 9012 3456 7' moet falen — niet de eerste 16 digits
    accepteren en de '7' negeren (was-bug: `(?!\\d)` keek niet door
    whitespace heen).
    """
    text = _MOCK_BASE.format(aanslag='1111.11.111.H.60.01').replace(
        'Betalingskenmerk : 1234 5678 9012 3456',
        'Betalingskenmerk : 1234 5678 9012 3456 7',
    )
    with pytest.raises(VAParseError, match='betalingskenmerk'):
        parse_va_beschikking_text(text)


def test_parse_unknown_dutch_month_raises():
    """Verzonnen maand-naam ('frebrul') → VAParseError."""
    text = _MOCK_BASE.format(aanslag='1111.11.111.H.60.01').replace(
        'Dagtekening 31 januari 2026',
        'Dagtekening 31 frebrul 2026',
    )
    with pytest.raises(VAParseError, match='maand'):
        parse_va_beschikking_text(text)
