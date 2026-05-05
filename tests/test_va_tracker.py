"""Unit-tests voor compute_va_tracker (Sprint I).

Pure function — geen DB, geen NiceGUI. Alle inputs expliciet.
"""
from datetime import date

import pytest

from services.dashboard import (
    VATrackLine, VATrackSummary, compute_va_tracker,
)


def _bank(ib=0, zvw=0, ib_n=0, zvw_n=0, unm=0, unm_n=0,
          tot_datum=None, has=False):
    return {
        'ib_betaald': ib, 'ib_termijnen': ib_n,
        'zvw_betaald': zvw, 'zvw_termijnen': zvw_n,
        'unmatched_betaald': unm, 'unmatched_termijnen': unm_n,
        'totaal_betaald': ib + zvw,
        'has_bank_data': has,
        'bankdata_tot_datum': tot_datum,
    }


def test_compute_va_tracker_geen_data():
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(has=False),
        ib_verplicht=0, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 5),
    )
    assert s.status == 'geen_data'
    assert s.totaal_resterend == 0
    assert s.has_overbetaald is False


def test_compute_va_tracker_geen_beschikking():
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=300, ib_n=1, has=True),
        ib_verplicht=0, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 5),
    )
    assert s.status == 'geen_beschikking'
    assert s.totaal_resterend == 0


def test_compute_va_tracker_bij_op_koers():
    # Mei (5e maand), 11 termijnen feb-start. Verwacht 4 termijnen.
    # Verplicht 4400 (400/termijn), betaald 1600 (4 termijnen) → op koers
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=1600, ib_n=4, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 31),
    )
    assert s.status == 'bij'
    assert s.totaal_achterstand <= 1


def test_compute_va_tracker_achter_with_amount():
    # Mei, 11 termijnen. Verplicht 4400. Betaald 800 (2 termijnen)
    # Verwacht 4 termijnen × 400 = 1600. Achterstand = 800.
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=800, ib_n=2, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 31),
    )
    assert s.status == 'achter'
    assert s.totaal_achterstand == pytest.approx(800, abs=1)


def test_compute_va_tracker_voldaan():
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=4400, ib_n=11, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 12, 31),
    )
    assert s.status == 'voldaan'
    assert s.has_overbetaald is False
    assert s.totaal_resterend == 0


def test_compute_va_tracker_voldaan_with_overbetaald_attribute():
    # IB overbetaald €100 (4500 betaald op 4400 verplicht), ZVW exact voldaan
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=4500, ib_n=11, zvw=2200, zvw_n=11, has=True),
        ib_verplicht=4400, zvw_verplicht=2200,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 12, 31),
    )
    assert s.status == 'voldaan'
    assert s.has_overbetaald is True
    assert s.ib.overbetaald == pytest.approx(100, abs=1)


def test_compute_va_tracker_line_first_status_ordering():
    """CRITICAL: IB +€100 overbetaald + ZVW achter mag NIET 'voldaan' zijn.

    Codex round-3 bug: oude totaal-eerst logica zou status='overbetaald'
    geven of 'voldaan' bij gemixte staat. Line-first checkt elke lijn.
    """
    # Augustus, 11 termijnen feb-start. Verwacht 7 termijnen × 400 = 2800 IB,
    # × 200 = 1400 ZVW. IB betaald 4500 (ver vooruit, overbetaald 100),
    # ZVW betaald 1000 (4 termijnen, achter 3 termijnen × 200 = 600 achter).
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=4500, ib_n=11, zvw=1000, zvw_n=4, has=True),
        ib_verplicht=4400, zvw_verplicht=2200,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 8, 31),
    )
    # Line-first: ZVW achterstand wint over IB-overbetaling
    assert s.status == 'achter'
    assert s.has_overbetaald is True  # IB-overbetaling alsnog gedetecteerd
    assert s.ib.overbetaald == pytest.approx(100, abs=1)
    assert s.zvw.achterstand > 500


def test_compute_va_tracker_closed_year_voldaan():
    s = compute_va_tracker(
        jaar=2025, va_data=_bank(ib=4400, ib_n=11, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 5),  # 2025 is closed
    )
    assert s.status == 'voldaan'


def test_compute_va_tracker_eerste_termijn_maand_11_termijnen():
    """Januari, 11 termijnen → expected_terms = 0 (feb-start)."""
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(has=False),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 1, 31),
    )
    # Geen achterstand in januari met 11-termijn-feb-start
    assert s.totaal_achterstand <= 1


def test_compute_va_tracker_eerste_termijn_maand_12_termijnen():
    """Januari, 12 termijnen → expected_terms = 1 (jan-start)."""
    # Verplicht 4800 over 12 termijnen = 400/termijn. Betaald 0 in jan.
    # Verwacht 1 termijn = 400. Achterstand = 400.
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(has=False),
        ib_verplicht=4800, zvw_verplicht=0,
        ib_termijnen=12, zvw_termijnen=12,
        today=date(2026, 1, 31),
    )
    assert s.status == 'achter'
    assert s.totaal_achterstand == pytest.approx(400, abs=1)


def test_compute_va_tracker_volgende_termijn_alleen_bij_open_resterend():
    # status='voldaan' → volgende_termijn_datum=None
    s_voldaan = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=4400, ib_n=11, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 12, 31),
    )
    assert s_voldaan.volgende_termijn_datum is None

    # status='bij' + resterend>0 → datum gevuld
    s_bij = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=1600, ib_n=4, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 31),
    )
    assert s_bij.volgende_termijn_datum is not None
    assert s_bij.volgende_termijn_datum.year == 2026


def test_compute_va_tracker_unmatched_in_summary_not_in_totaal():
    s = compute_va_tracker(
        jaar=2026,
        va_data=_bank(ib=800, ib_n=2, unm=120, unm_n=1, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 31),
    )
    assert s.unmatched_betaald == 120
    assert s.totaal_betaald == 800  # excludeert unmatched
