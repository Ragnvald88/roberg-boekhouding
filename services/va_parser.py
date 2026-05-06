"""Voorlopige aanslag (BD beschikking) PDF parser — pure helpers, UI-vrij + DB-vrij.

Parses Belastingdienst voorlopige-aanslag-PDFs (IB en ZVW) naar een
:class:`ParsedBeschikking`-record. Caller ((``/documenten`` upload-flow)
delegeert hier naartoe en geeft het resultaat door aan
``database.process_voorlopige_aanslag_upload``.

Spec: ``docs/superpowers/specs/2026-05-06-va-tracker-drilldown-design.md`` § 2.

Design-keuzes:

- Strict-pure: geen NiceGUI, geen DB. Testbaar via ``parse_va_beschikking_text``
  zonder PDF-fixture (subprocess te broos voor unit tests).
- pdftotext via ``import_/pdf_parser.extract_pdf_text`` (al bestaand patroon
  + 30s timeout + foutafhandeling).
- Whitespace-normalize VOOR matching: PDF layout breekt soms velden over
  meerdere regels.
- Critical fields raise :class:`VAParseError` met diagnostiek (welk veld);
  caller kan dan handmatig pad aanbieden en behoudt PDF-upload.
- Type-detect via aanslagnummer-suffix (``.H.`` → IB, ``.W.`` → ZVW).
  Dit is robuuster dan header-string-match (BD wisselt soms layout).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal


class VAParseError(ValueError):
    """Critical field missing of malformed — caller toont fallback naar handmatig."""


@dataclass(frozen=True)
class ParsedBeschikking:
    """Geparseerde Belastingdienst voorlopige-aanslag-beschikking.

    ``soort`` = ``'ib'`` (Inkomstenbelasting + premie volksverzekeringen)
    of ``'zvw'`` (Zorgverzekeringswet).
    """
    jaar: int
    soort: Literal['ib', 'zvw']
    aanslagnummer: str          # '9999.99.999.H.60.01' of '9999.99.999.W.60.01.4'
    dagtekening: date
    bedrag: float               # heeltal of 2-decimal precision
    betalingskenmerk: str       # 16 digits, geen spaties
    termijnen: int              # default 11; range 1-12


# --- Regex patterns (op whitespace-genormaliseerde tekst) -----------------

# Aanslagnummer: 9999.99.999.H.60.01 of 9999.99.999.W.60.01.4
_AANSLAG_RE = re.compile(
    r'\b(\d{4}\.\d{2}\.\d{3}\.[HW]\.\d{2}\.\d{2}(?:\.\d+)?)\b',
)
_JAAR_RE = re.compile(r'Voorlopige aanslag (\d{4})\b')
_DAGTEKENING_RE = re.compile(r'Dagtekening (\d{1,2}) ([a-zA-Z]+) (\d{4})')
# Bedrag-spec uit het betaalblok: "Te betalen : € 30.670,00".
# De PDF heeft 4 "Te betalen" varianten; alleen het betaalblok gebruikt
# de `:` separator + komma-precisie, dus we ankerknopen daarop.
#
# Patroon: 1-3 digits, gevolgd door 0+ groepen van (.NNN) thousands,
# optionele (,NN) decimal. Trailing `(?![\d.,])` voorkomt dat malformed
# bedragen ('30670,00' zonder thousands-dot, '30.67,50' met te-korte
# tussen-groep, '1.234.56' met 2-digit "thousands"-tail) silent
# gedeeltelijk parsen — caller krijgt VAParseError ipv junk-bedrag.
_BEDRAG_RE = re.compile(
    r'Te betalen\s*:\s*€\s*'
    r'([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?)'
    r'(?![\d.,])',
)
# Betalingskenmerk: BD-format is consistent NNNN NNNN NNNN NNNN (4 groups of 4
# digits, single space separator). We capture exactly dat patroon met optionele
# enkele-spatie-separator. De trailing `(?!\s*\d)` lookahead reject óók een
# losstaand digit *na whitespace* — anders zou '1234 5678 9012 3456 7' silent
# de eerste 16 digits accepteren en de trailing 7 negeren (Codex-catch).
_KENMERK_RE = re.compile(
    r'Betalingskenmerk\s*:?\s*'
    r'(\d{4}\s?\d{4}\s?\d{4}\s?\d{4})'
    r'(?!\s*\d)',
)
_TERMIJNEN_RE = re.compile(r'(\d+) (?:gelijke )?maandelijkse? termijnen')


# Nederlandse maand-naam → maand-nummer (1-12). Hergebruik niet
# `format_datum_*_nl` — die zijn output-only; we hebben hier reverse-map nodig.
_DUTCH_MAANDEN_REVERSE: dict[str, int] = {
    'januari': 1,
    'februari': 2,
    'maart': 3,
    'april': 4,
    'mei': 5,
    'juni': 6,
    'juli': 7,
    'augustus': 8,
    'september': 9,
    'oktober': 10,
    'november': 11,
    'december': 12,
}


def _parse_dutch_bedrag(s: str) -> float:
    """Parse Belastingdienst bedrag-string naar float.

    BD-formaat: punt-thousands + optionele komma-decimaal.

    Voorbeelden:
        '30.670' → 30670.0
        '30.670,50' → 30670.50
        '2.808,00' → 2808.0
        '500' → 500.0

    Raises:
        VAParseError: niet-parseerbaar (lege string, alleen separators, etc.)
    """
    s = (s or '').strip()
    if not s:
        raise VAParseError('bedrag: lege string')
    # Replace dots (thousands) eerst, dan comma → dot voor float-cast.
    normalised = s.replace('.', '').replace(',', '.')
    try:
        return float(normalised)
    except ValueError as exc:
        raise VAParseError(f'bedrag: kan {s!r} niet als getal lezen') from exc


def _parse_dutch_dagtekening(day: str, month_name: str, year: str) -> date:
    """Parse '31 januari 2026' → date(2026, 1, 31)."""
    month = _DUTCH_MAANDEN_REVERSE.get(month_name.lower())
    if month is None:
        raise VAParseError(
            f'dagtekening: onbekende Nederlandse maand-naam {month_name!r}',
        )
    try:
        return date(int(year), month, int(day))
    except ValueError as exc:
        raise VAParseError(
            f'dagtekening: ongeldige datum {day} {month_name} {year} ({exc})',
        ) from exc


def _detect_soort(aanslagnummer: str) -> Literal['ib', 'zvw']:
    """Bepaal soort via aanslagnummer-suffix.

    Format: ``9999.99.999.H.60.01`` of ``9999.99.999.W.60.01.4``
    Suffix-positie [3] is ``H`` (Inkomstenbelasting) of ``W`` (Zorgverzekeringswet).
    """
    parts = aanslagnummer.split('.')
    if len(parts) < 4:
        raise VAParseError(
            f'aanslagnummer: onverwacht format {aanslagnummer!r} '
            f'(verwacht minimaal 4 punt-separated delen)',
        )
    suffix = parts[3]
    if suffix == 'H':
        return 'ib'
    if suffix == 'W':
        return 'zvw'
    raise VAParseError(
        f'aanslagnummer: onbekende suffix {suffix!r} '
        f'(verwacht H of W) in {aanslagnummer!r}',
    )


def parse_va_beschikking_text(text: str) -> ParsedBeschikking:
    """Pure parser-helper — neemt al-geëxtraheerde PDF-tekst, returnt parsed record.

    Caller (UI/upload-flow) gebruikt :func:`parse_va_beschikking` voor
    de PDF→text→parse pipeline. Tests gebruiken deze helper direct met
    geanonimiseerde text-fixtures (subprocess pdftotext te broos voor
    unit-tests).

    Raises:
        VAParseError: critical field (aanslagnummer, jaar, dagtekening,
            bedrag, betalingskenmerk) ontbreekt of is malformed.
    """
    # Whitespace-normalize: collapse newlines + multi-space naar enkele spatie.
    # PDF layout breekt sommige velden over regels (bijv. "Het laatste
    # bedrag moet\nuiterlijk op 31 december 2026"). Normalize maakt
    # regex-matchen op multi-line content triviaal.
    norm = re.sub(r'\s+', ' ', text)

    # --- Critical: aanslagnummer (drives soort-detect) ---
    m_aan = _AANSLAG_RE.search(norm)
    if not m_aan:
        raise VAParseError(
            'aanslagnummer: geen match — verwacht patroon '
            'NNNN.NN.NNN.[HW].NN.NN(.N)',
        )
    aanslagnummer = m_aan.group(1)
    soort = _detect_soort(aanslagnummer)

    # --- Critical: jaar ---
    m_jaar = _JAAR_RE.search(norm)
    if not m_jaar:
        raise VAParseError(
            'jaar: geen match op "Voorlopige aanslag YYYY"',
        )
    jaar = int(m_jaar.group(1))

    # --- Critical: dagtekening ---
    m_dag = _DAGTEKENING_RE.search(norm)
    if not m_dag:
        raise VAParseError(
            'dagtekening: geen match op "Dagtekening DD maand YYYY"',
        )
    dagtekening = _parse_dutch_dagtekening(
        m_dag.group(1), m_dag.group(2), m_dag.group(3),
    )

    # --- Critical: bedrag ---
    m_bedrag = _BEDRAG_RE.search(norm)
    if not m_bedrag:
        raise VAParseError(
            'bedrag: geen match op "Te betalen : € N.NNN,NN" in betaalblok',
        )
    bedrag = _parse_dutch_bedrag(m_bedrag.group(1))

    # --- Critical: betalingskenmerk ---
    m_ken = _KENMERK_RE.search(norm)
    if not m_ken:
        raise VAParseError(
            'betalingskenmerk: geen match op "Betalingskenmerk : NNNN..."',
        )
    kenmerk_digits = re.sub(r'[^0-9]', '', m_ken.group(1))
    if len(kenmerk_digits) != 16:
        raise VAParseError(
            f'betalingskenmerk: na strippen {len(kenmerk_digits)} digits — '
            f'verwacht exact 16 (bron: {m_ken.group(1)!r})',
        )

    # --- Optional: termijnen (default 11) ---
    # Spec § 2: default 11 als regex faalt OF buiten 1-12 range. Bewuste
    # keuze voor resilience boven hard-fail: BD-PDFs schrijven praktisch
    # altijd 11 (soms 12); een edge-case '00 termijnen' in een gemangelde
    # PDF mag niet de hele upload blokkeren — bedrag + kenmerk zijn de
    # kritieke velden voor betaal-tracking.
    termijnen = 11
    m_term = _TERMIJNEN_RE.search(norm)
    if m_term:
        try:
            candidate = int(m_term.group(1))
        except ValueError:
            candidate = 11
        if 1 <= candidate <= 12:
            termijnen = candidate
        # else: out-of-range → silently fall back to default 11

    return ParsedBeschikking(
        jaar=jaar,
        soort=soort,
        aanslagnummer=aanslagnummer,
        dagtekening=dagtekening,
        bedrag=bedrag,
        betalingskenmerk=kenmerk_digits,
        termijnen=termijnen,
    )


def parse_va_beschikking(pdf_path: Path) -> ParsedBeschikking:
    """Parse BD voorlopige-aanslag-PDF → :class:`ParsedBeschikking`.

    Pipeline: pdftotext-subprocess (via ``import_.pdf_parser.extract_pdf_text``)
    → :func:`parse_va_beschikking_text`.

    Raises:
        VAParseError: critical field missing of malformed in extracted text.
        RuntimeError: pdftotext binary missing of subprocess-fail
            (propagateert uit ``extract_pdf_text``). Caller mag dit
            wrappen in een eigen UI-notify; we converteren niet ter plekke
            zodat pdftotext-installatie-issues distinct blijven van
            parse-issues in logs.
    """
    # Lazy import om de circular-risk en subprocess-overhead in pure-tests
    # te vermijden. tests/test_va_parser.py gebruikt parse_va_beschikking_text
    # rechtstreeks, dus de subprocess-pad raakt alleen integratie-paths.
    from import_.pdf_parser import extract_pdf_text

    text = extract_pdf_text(pdf_path)
    return parse_va_beschikking_text(text)
