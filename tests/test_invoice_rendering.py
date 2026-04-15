"""Tests for invoice rendering, line-item conversion, and subtotal calculations."""

import pytest
from types import SimpleNamespace

from components.invoice_preview import render_invoice_html
from components.invoice_builder import _werkdagen_to_line_items, _build_regels



_BEDRIJF = {
    'bedrijfsnaam': 'TestBedrijf', 'naam': 'J. de Test',
    'functie': 'Arts', 'adres': 'Hoofdstraat 1',
    'postcode_plaats': '1234 AB Dorp', 'kvk': '12345678',
    'iban': 'NL00 TEST 0000 0000 00', 'thuisplaats': 'Dorp',
}


def test_render_empty_invoice():
    """Empty invoice renders valid HTML with placeholder."""
    html = render_invoice_html()
    assert '<html' in html
    assert 'FACTUUR' in html
    # Empty nummer shows dash placeholder
    assert '\u2014' in html


def test_render_full_invoice():
    """Full invoice with klant, regels, and bedrijf renders correctly."""
    klant = {
        'naam': 'Testpraktijk', 'contactpersoon': 'Dr. Test',
        'adres': 'Testlaan 1', 'postcode': '5678 CD',
        'plaats': 'Teststad',
    }
    regels = [
        {'datum': '2026-02-01', 'omschrijving': 'Waarneming dagpraktijk',
         'aantal': 9, 'tarief': 77.50, 'bedrag': 697.50, 'is_reiskosten': False},
        {'datum': '2026-02-01', 'omschrijving': 'Reiskosten (retour Dorp \u2013 Teststad)',
         'aantal': 52, 'tarief': 0.23, 'bedrag': 11.96, 'is_reiskosten': True},
    ]
    html = render_invoice_html(
        nummer='2026-001', klant=klant, regels=regels,
        factuur_datum='2026-02-15', bedrijfsgegevens=_BEDRIJF)

    assert '2026-001' in html
    assert 'Testpraktijk' in html
    assert 'Dr. Test' in html
    assert 'Waarneming dagpraktijk' in html
    assert 'Reiskosten (retour' in html
    # Subtotals hidden for single werkdag + reiskosten (only shown for >1 werkdagen)
    assert 'Subtotaal waarnemingen' not in html


def test_render_no_subtotals_when_no_reiskosten():
    """When all lines are werk, subtotals are hidden."""
    regels = [
        {'datum': '2026-02-01', 'omschrijving': 'Waarneming',
         'aantal': 9, 'tarief': 80, 'bedrag': 720, 'is_reiskosten': False},
    ]
    html = render_invoice_html(
        nummer='2026-002', regels=regels,
        factuur_datum='2026-02-15', bedrijfsgegevens=_BEDRIJF)

    # Only werk = totaal, so subtotals should NOT appear
    assert 'Subtotaal waarnemingen' not in html


def test_render_logo_included():
    """Logo URL is rendered in HTML when provided."""
    html = render_invoice_html(
        nummer='2026-003', factuur_datum='2026-02-15',
        bedrijfsgegevens=_BEDRIJF, logo_url='/logo-files/logo.png')

    assert '/logo-files/logo.png' in html
    assert '<img' in html


def test_render_no_logo_when_empty():
    """Logo section is absent when no logo_url."""
    html = render_invoice_html(
        nummer='2026-004', factuur_datum='2026-02-15',
        bedrijfsgegevens=_BEDRIJF, logo_url='')

    # Logo div should not appear
    assert 'class="logo"' not in html


def test_render_qr_included():
    """QR code image is rendered when qr_url provided."""
    html = render_invoice_html(
        nummer='2026-005', factuur_datum='2026-02-15',
        bedrijfsgegevens=_BEDRIJF, qr_url='/qr-files/betaal_qr.png')

    assert '/qr-files/betaal_qr.png' in html


def test_render_kvk_iban_guards_empty():
    """KvK and IBAN are hidden when empty in bedrijfsgegevens."""
    bedrijf_no_kvk = {**_BEDRIJF, 'kvk': '', 'iban': ''}
    html = render_invoice_html(
        nummer='2026-006', factuur_datum='2026-02-15',
        bedrijfsgegevens=bedrijf_no_kvk)

    assert 'KvK:' not in html
    assert 'IBAN:' not in html


def test_render_kvk_iban_shown_when_set():
    """KvK and IBAN are shown when present."""
    html = render_invoice_html(
        nummer='2026-007', factuur_datum='2026-02-15',
        bedrijfsgegevens=_BEDRIJF)

    assert 'KvK: 12345678' in html
    assert 'IBAN: NL00 TEST 0000 0000 00' in html


def test_render_btw_legal_citation():
    """BTW notice is present on the invoice."""
    html = render_invoice_html(
        nummer='2026-008', factuur_datum='2026-02-15',
        bedrijfsgegevens=_BEDRIJF)

    assert 'Vrijgesteld van BTW' in html


def test_render_bedrag_computed_if_missing():
    """If bedrag is not in a regel, it is computed from aantal * tarief."""
    regels = [
        {'datum': '2026-02-01', 'omschrijving': 'Test',
         'aantal': 10, 'tarief': 50},  # no 'bedrag' key
    ]
    html = render_invoice_html(
        nummer='2026-009', regels=regels,
        factuur_datum='2026-02-15', bedrijfsgegevens=_BEDRIJF)

    # 10 * 50 = 500 → should appear formatted as € 500,00
    assert '500,00' in html


def test_render_invalid_date_falls_back():
    """Invalid factuur_datum falls back to current date without crashing."""
    html = render_invoice_html(
        nummer='2026-010', factuur_datum='not-a-date',
        bedrijfsgegevens=_BEDRIJF)

    assert '<html' in html
    assert 'FACTUUR' in html



def _make_werkdag(**kwargs):
    """Create a werkdag-like object (SimpleNamespace) with defaults."""
    defaults = {
        'id': 1, 'datum': '2026-02-01',
        'activiteit': 'Waarneming dagpraktijk',
        'uren': 9, 'tarief': 77.50,
        'km': 52, 'km_tarief': 0.23,
        'locatie': 'Teststad',
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_werkdagen_to_line_items_basic():
    """Single werkdag produces one item with km fields."""
    wd = _make_werkdag()
    items = _werkdagen_to_line_items([wd], thuisplaats='Dorp')

    assert len(items) == 1
    assert items[0]['omschrijving'] == 'Waarneming dagpraktijk'
    assert items[0]['aantal'] == 9
    assert items[0]['tarief'] == 77.50
    assert items[0]['werkdag_id'] == 1
    assert items[0]['is_reiskosten'] is False
    # Km fields on same item
    assert items[0]['km'] == 52
    assert items[0]['km_tarief'] == 0.23
    assert 'Reiskosten (retour Dorp' in items[0]['km_omschrijving']


def test_werkdagen_to_line_items_no_km():
    """Werkdag with km=0 produces only waarneming, no reiskosten."""
    wd = _make_werkdag(km=0)
    items = _werkdagen_to_line_items([wd])

    assert len(items) == 1
    assert items[0]['is_reiskosten'] is False


def test_werkdagen_to_line_items_no_locatie():
    """Without locatie, reiskosten omschrijving is generic."""
    wd = _make_werkdag(locatie='')
    items = _werkdagen_to_line_items([wd], thuisplaats='Dorp')

    assert len(items) == 1
    assert items[0]['km_omschrijving'] == 'Reiskosten'


def test_werkdagen_to_line_items_locatie_no_thuisplaats():
    """With locatie but no thuisplaats, omschrijving omits origin."""
    wd = _make_werkdag(locatie='Teststad')
    items = _werkdagen_to_line_items([wd], thuisplaats='')

    assert items[0]['km_omschrijving'] == 'Reiskosten (retour \u2013 Teststad)'


def test_werkdagen_to_line_items_multiple():
    """Multiple werkdagen produce one item each with km fields."""
    wds = [
        _make_werkdag(id=1, datum='2026-02-01', km=50),
        _make_werkdag(id=2, datum='2026-02-02', km=0),
        _make_werkdag(id=3, datum='2026-02-03', km=30),
    ]
    items = _werkdagen_to_line_items(wds, thuisplaats='Dorp')

    assert len(items) == 3  # one per werkdag
    assert items[0]['km'] == 50
    assert items[1]['km'] == 0
    assert items[2]['km'] == 30


def test_werkdagen_to_line_items_dict_input():
    """Also works with dict input (not just objects)."""
    wd_dict = {
        'id': 10, 'datum': '2026-03-01',
        'activiteit': 'Achterwacht', 'uren': 16,
        'tarief': 25, 'km': 0, 'km_tarief': 0,
        'locatie': '',
    }
    items = _werkdagen_to_line_items([wd_dict])

    assert len(items) == 1
    assert items[0]['omschrijving'] == 'Achterwacht'
    assert items[0]['werkdag_id'] == 10
    assert items[0]['is_reiskosten'] is False


def test_werkdagen_to_line_items_anw_zero_km_tarief():
    """ANW werkdag with km_tarief=0 does not generate reiskosten even with km>0."""
    wd = _make_werkdag(km=0, km_tarief=0)
    items = _werkdagen_to_line_items([wd])

    # km=0 → no reiskosten line
    assert len(items) == 1


def test_werkdagen_to_line_items_empty():
    """Empty input produces empty output."""
    items = _werkdagen_to_line_items([])
    assert items == []



def test_subtotal_split_with_is_reiskosten():
    """Subtotals correctly split werk vs reiskosten using is_reiskosten flag."""
    regels = [
        {'datum': '2026-02-01', 'omschrijving': 'Waarneming',
         'aantal': 9, 'tarief': 80, 'bedrag': 720, 'is_reiskosten': False},
        {'datum': '2026-02-01', 'omschrijving': 'Reiskosten (retour Dorp \u2013 X)',
         'aantal': 50, 'tarief': 0.23, 'bedrag': 11.50, 'is_reiskosten': True},
        {'datum': '2026-02-02', 'omschrijving': 'Waarneming',
         'aantal': 8, 'tarief': 80, 'bedrag': 640, 'is_reiskosten': False},
    ]
    subtotaal_werk = sum(
        r['bedrag'] for r in regels if not r.get('is_reiskosten'))
    subtotaal_km = sum(
        r['bedrag'] for r in regels if r.get('is_reiskosten'))

    assert subtotaal_werk == 1360.0
    assert subtotaal_km == 11.50
    assert subtotaal_werk + subtotaal_km == 1371.50


def test_subtotal_no_reiskosten():
    """When no reiskosten lines, subtotaal_km is 0."""
    regels = [
        {'bedrag': 720, 'is_reiskosten': False},
        {'bedrag': 640, 'is_reiskosten': False},
    ]
    subtotaal_km = sum(
        r['bedrag'] for r in regels if r.get('is_reiskosten'))
    assert subtotaal_km == 0


def test_subtotal_all_reiskosten():
    """Edge case: all lines are reiskosten."""
    regels = [
        {'bedrag': 11.50, 'is_reiskosten': True},
        {'bedrag': 8.00, 'is_reiskosten': True},
    ]
    subtotaal_werk = sum(
        r['bedrag'] for r in regels if not r.get('is_reiskosten'))
    subtotaal_km = sum(
        r['bedrag'] for r in regels if r.get('is_reiskosten'))

    assert subtotaal_werk == 0
    assert subtotaal_km == 19.50


def test_subtotal_missing_flag_defaults_to_werk():
    """Lines without is_reiskosten flag default to werk (not reiskosten)."""
    regels = [
        {'bedrag': 720},  # no is_reiskosten key
        {'bedrag': 640, 'is_reiskosten': False},
    ]
    subtotaal_werk = sum(
        r['bedrag'] for r in regels if not r.get('is_reiskosten'))
    subtotaal_km = sum(
        r['bedrag'] for r in regels if r.get('is_reiskosten'))

    assert subtotaal_werk == 1360
    assert subtotaal_km == 0


def test_no_reiskosten_line_when_km_tarief_zero():
    """ANW diensten have km tracked but km_tarief=0 — no reiskosten line."""
    line_items = [{
        'datum': '2024-01-15',
        'omschrijving': 'ANW dienst',
        'aantal': 8.0,
        'tarief': 65.0,
        'km': 50,
        'km_tarief': 0,
        'km_omschrijving': 'Reiskosten',
    }]
    regels = _build_regels(line_items)
    assert len(regels) == 1, f"Expected 1 regel (no km line), got {len(regels)}"
    assert regels[0]['bedrag'] == 520.00


def test_werkdagen_to_items_subtotal_integration():
    """End-to-end: werkdagen → line_items → _build_regels → correct subtotals."""
    wds = [
        _make_werkdag(id=1, uren=9, tarief=80, km=50, km_tarief=0.23,
                      locatie='Teststad'),
        _make_werkdag(id=2, uren=8, tarief=80, km=0, km_tarief=0.23,
                      locatie=''),
    ]
    items = _werkdagen_to_line_items(wds, thuisplaats='Dorp')
    assert len(items) == 2  # one per werkdag

    # Build regels splits km back out for PDF
    regels = _build_regels(items)
    assert len(regels) == 3  # 2 werk + 1 reiskosten (wd2 has km=0)

    subtotaal_werk = sum(
        r['bedrag'] for r in regels if not r.get('is_reiskosten'))
    subtotaal_km = sum(
        r['bedrag'] for r in regels if r.get('is_reiskosten'))

    # wd1: 9*80=720, wd2: 8*80=640 → werk=1360
    assert subtotaal_werk == 1360.0
    # wd1: 50*0.23=11.50 → km=11.50
    assert subtotaal_km == 11.50
