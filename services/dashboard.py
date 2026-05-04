"""Pure helpers for /dashboard page rendering.

UI-vrij — geen NiceGUI imports. Returns dataclasses or primitives that
the per-tile renderers in components/dashboard_widgets.py consume.

All functions are testable in isolation.
"""
from __future__ import annotations

from datetime import date
from typing import Literal


def compute_belasting_reservering_progress(
    berekend_jaarbelasting: float,
    va_betaald_ytd: float,
    today: date,
) -> tuple[Literal['op_koers', 'tekort', 'overreservering'], float]:
    """Returns (status, diff_amount).

    diff > 0 = je moet nog reserveren (tekort);
    diff < 0 = je hebt overgereserveerd.

    Day-precision proration: expected_va_ytd = berekend × days_elapsed
    / days_in_year. Codex T1.3-review pushed back op month-based formule
    (would expect 1/12 paid op 1 jan, conceptueel fout). Day-based is
    correct én robust voor leap-years (366 vs 365).

    Threshold: 'tekort' if (expected_va_ytd - va_betaald_ytd) > 1000;
    'overreservering' if < -2000; else 'op_koers'.

    The asymmetric threshold (1000 vs -2000) reflects user-pain bias:
    being short on tax money is more painful than being early.
    """
    year_start = date(today.year, 1, 1)
    next_year_start = date(today.year + 1, 1, 1)
    days_elapsed = (today - year_start).days + 1
    days_in_year = (next_year_start - year_start).days
    expected_va_ytd = berekend_jaarbelasting * days_elapsed / days_in_year
    diff = expected_va_ytd - va_betaald_ytd
    if diff > 1000:
        return ('tekort', diff)
    if diff < -2000:
        return ('overreservering', diff)
    return ('op_koers', diff)
