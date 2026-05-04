"""Pure helpers for /dashboard page rendering.

UI-vrij — geen NiceGUI imports. Returns dataclasses or primitives that
the per-tile renderers in components/dashboard_widgets.py consume.

All functions are testable in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
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

    Threshold: 'tekort' if (expected_va_ytd - va_betaald_ytd) > 1000;
    'overreservering' if < -2000; else 'op_koers'.

    The asymmetric threshold (1000 vs -2000) reflects user-pain bias:
    being short on tax money is more painful than being early.
    """
    months_elapsed = today.month
    expected_va_ytd = berekend_jaarbelasting * months_elapsed / 12
    diff = expected_va_ytd - va_betaald_ytd
    if diff > 1000:
        return ('tekort', diff)
    if diff < -2000:
        return ('overreservering', diff)
    return ('op_koers', diff)
