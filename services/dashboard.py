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


def compute_jaareinde_projectie_display(
    extrapolated_omzet: float,
    kosten_ytd: float,
    confidence: Literal['low', 'medium', 'high'],
    basis_maanden: int,
) -> dict:
    """Returns dict with `winst_projectie`, `confidence`, `basis_maanden`
    for the Jaareinde-projectie hero-tile (per spec U1: 1 number =
    winst-projectie alleen).

    Kosten YTD wordt geëxtrapoleerd naar 12mo gebruikmakend van
    basis_maanden (zelfde extrapolatie-logica als omzet). Edge-case:
    basis_maanden=0 → kosten_extrapolated = 0, winst = extrapolated_omzet.
    """
    if basis_maanden <= 0:
        kosten_extrapolated = 0.0
    else:
        kosten_extrapolated = kosten_ytd * 12 / basis_maanden
    winst_projectie = extrapolated_omzet - kosten_extrapolated
    return {
        'winst_projectie': winst_projectie,
        'confidence': confidence,
        'basis_maanden': basis_maanden,
    }


@dataclass(frozen=True)
class ActionRow:
    """One row in the dashboard action-inbox.

    `kind` = row-type identifier (verlopen_factuur, bank_tx_ongecategoriseerd,
             documenten_ontbreken, concept_factuur_stale, ib_aangifte_deadline,
             va_termijn_deadline, jaarafsluiting_pending, etc.)
    `severity` = 'critical' | 'warning' | 'info'
    `action_kind` = identifier for the inline-action handler
                    (None = read-only "Bekijk" only)
    `link` = navigate-to-target for "Bekijk" knop
    `age_days` = age in days (used for tiebreak in prioritise_actions)
    `metadata` = dict for action-handler context (factuur_id, banktx_id, etc.)
    """
    kind: str
    severity: Literal['critical', 'warning', 'info']
    message: str
    action_kind: str | None
    link: str | None
    age_days: int
    metadata: dict


_SEVERITY_ORDER = {'critical': 0, 'warning': 1, 'info': 2}


def prioritise_actions(
    rows: list[ActionRow],
    max_items: int,
) -> list[ActionRow]:
    """Sort rows by (severity DESC, age DESC, kind ASC) and truncate.

    Severity-order: critical > warning > info > anything-else (treated as info).
    Stable secondary sort op age_days descending (oldest first within severity).
    Tertiary stable sort op kind ASC for deterministic ordering.
    """
    if max_items <= 0:
        return []

    def _sort_key(row: ActionRow) -> tuple:
        sev_rank = _SEVERITY_ORDER.get(row.severity, 2)  # unknown → info
        return (sev_rank, -row.age_days, row.kind)

    sorted_rows = sorted(rows, key=_sort_key)
    return sorted_rows[:max_items]
