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


# === _pill_context_actions visibility-matrix ===

def _make_pill(*, factuurnummer='', factuur_id=None, factuur_status='',
               status_label='ongefactureerd'):
    """Stub-pill met alleen velden die _pill_context_actions leest."""
    class P:
        pass
    p = P()
    p.factuurnummer = factuurnummer
    p.factuur_id = factuur_id
    p.factuur_status = factuur_status
    p.status_label = status_label
    return p


def test_pill_actions_ongefactureerd():
    """Geen factuur → bewerken/dupliceren/verwijderen toegestaan."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill()
    assert _pill_context_actions(pill) == ['edit', 'duplicate', 'delete']


def test_pill_actions_factuur_concept():
    """Concept-factuur → ontkoppel + naar facturen, geen verwijderen."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2026-001', factuur_id=10,
        factuur_status='concept', status_label='concept')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'naar_facturen', 'ontkoppel']


def test_pill_actions_factuur_verstuurd():
    """Verstuurd → alleen naar_facturen, geen ontkoppel/delete."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2026-001', factuur_id=10,
        factuur_status='verstuurd', status_label='verstuurd')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'naar_facturen']


def test_pill_actions_factuur_verstuurd_overdue():
    """Verlopen = verstuurd + vervaldatum<today → zelfde acties als verstuurd."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2026-001', factuur_id=10,
        factuur_status='verstuurd', status_label='verlopen')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'naar_facturen']


def test_pill_actions_factuur_betaald():
    """Betaald → alleen naar_facturen, géén ontkoppel."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2026-001', factuur_id=10,
        factuur_status='betaald', status_label='betaald')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'naar_facturen']


def test_pill_actions_orphan_factuurnummer():
    """factuurnummer != '' maar factuur_id is None → ontkoppel toegestaan."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2025-999', factuur_id=None,
        factuur_status='', status_label='ongefactureerd')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'ontkoppel']


def test_pill_actions_unknown_factuur_status_defensive():
    """Onbekende status → alleen naar_facturen, geen delete/ontkoppel."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2026-001', factuur_id=10,
        factuur_status='something_weird', status_label='gefactureerd')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'naar_facturen']


def test_pill_actions_no_factuur_no_orphan():
    """factuurnummer='' + factuur_id=None → standaard ongefactureerd-pad."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='', factuur_id=None,
        factuur_status='', status_label='ongefactureerd')
    assert _pill_context_actions(pill) == ['edit', 'duplicate', 'delete']


def test_pill_actions_with_real_werkdagpill_shape():
    """Smoke-test: _pill_context_actions reads de echte WerkdagPill-velden
    (factuurnummer, factuur_id, factuur_status). Code-quality review #2 —
    `getattr` met defaults zou een veld-rename in WerkdagPill silent
    maskeren; deze test breekt loud bij field-name drift.
    """
    from pages.agenda import _pill_context_actions
    from services.agenda import WerkdagPill
    w = WerkdagPill(
        id=1, klant_id=1, klant_naam='Test', code='WERKDAG',
        uren=8.0, bedrag=600.0, factuurnummer='2026-001',
        factuur_id=10, factuur_status='concept',
        factuur_vervaldatum='2026-05-29', factuur_betaald_datum='',
        overdue_days=0, status_label='concept', category='dagpraktijk',
    )
    assert _pill_context_actions(w) == [
        'edit', 'duplicate', 'naar_facturen', 'ontkoppel']


# === _pill_tooltip formatter ===

def test_pill_tooltip_ongefactureerd():
    """Ongefactureerd: geen factuurnummer in tooltip."""
    from pages.agenda import _pill_tooltip
    pill = _make_pill(status_label='ongefactureerd')
    pill.klant_naam = 'Huisartsenpraktijk \'t Ouddiep'
    pill.uren = 9.5
    pill.bedrag = 754.92
    pill.factuurnummer = ''
    text = _pill_tooltip(pill)
    assert "Huisartsenpraktijk 't Ouddiep" in text
    assert '9.5u' in text
    assert '754,92' in text
    assert 'ongefactureerd' in text
    assert 'Factuur' not in text
    assert 'concept-factuur' not in text


def test_pill_tooltip_concept():
    """Concept-status toont 'concept-factuur {nummer}'."""
    from pages.agenda import _pill_tooltip
    pill = _make_pill(status_label='concept')
    pill.klant_naam = 'S. Borgemeester'
    pill.uren = 8.0
    pill.bedrag = 1344.84
    pill.factuurnummer = '2026-024'
    text = _pill_tooltip(pill)
    assert 'concept-factuur 2026-024' in text


def test_pill_tooltip_betaald():
    """Verstuurd/verlopen/betaald tonen 'Factuur {nummer}'."""
    from pages.agenda import _pill_tooltip
    pill = _make_pill(status_label='betaald')
    pill.klant_naam = 'M. Zwart'
    pill.uren = 9.0
    pill.bedrag = 417.60
    pill.factuurnummer = '2026-027'
    text = _pill_tooltip(pill)
    assert '· Factuur 2026-027' in text
    assert 'concept-factuur' not in text


def test_pill_tooltip_verstuurd_includes_factuur():
    from pages.agenda import _pill_tooltip
    pill = _make_pill(status_label='verstuurd')
    pill.klant_naam = 'Klant'
    pill.uren = 8.0
    pill.bedrag = 837.42
    pill.factuurnummer = '2026-031'
    text = _pill_tooltip(pill)
    assert '· Factuur 2026-031' in text


def test_pill_tooltip_orphan_factuurnummer_visible():
    """Orphan-link: werkdag.factuurnummer != '' maar geen matching factuur-row.
    `derive_werkdag_status_label` mapt dit naar 'ongefactureerd', maar het
    context-menu biedt 'Ontkoppel factuur' aan. Tooltip MOET het orphan-
    nummer tonen — anders is de Ontkoppel-actie verwarrend (codex final
    review)."""
    from pages.agenda import _pill_tooltip
    pill = _make_pill(status_label='ongefactureerd')
    pill.klant_naam = 'Klant'
    pill.uren = 8.0
    pill.bedrag = 600.0
    pill.factuurnummer = '2025-999'  # orphan — geen factuur-row
    text = _pill_tooltip(pill)
    assert '2025-999' in text
    assert 'orphan-link' in text or 'Factuur' in text or 'concept' in text, (
        'orphan factuurnummer must be visible in tooltip')
