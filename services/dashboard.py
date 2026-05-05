"""Pure helpers for /dashboard page rendering.

UI-vrij — geen NiceGUI imports. Returns dataclasses or primitives that
the per-tile renderers in components/dashboard_widgets.py consume.

All functions are testable in isolation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Literal

log = logging.getLogger(__name__)

DASHBOARD_CONFIG_SCHEMA_VERSION = 1

# SPH (Stichting Pensioenfonds Huisartsen) — premium parameters voor
# pensioengrondslag berekening. Publicatie 2026; als het bestuur de
# percentages later wijzigt, voeg per-jaar branch toe in
# compute_sph_prognose ipv constants overschrijven.
SPH_PREMIUM_RATE_2026 = 0.2394
SPH_FRANCHISE_2026 = 19_172
SPH_GRONDSLAG_CAP_2026 = 137_800


def compute_sph_prognose(winst_extrapolatie: float, jaar: int) -> dict:
    """Computeer geprognoseerde SPH-jaarverplichting.

    Formula 2026: 23.94% × min(€137.800, max(0, winst − €19.172))

    Returns dict: {'pensioengrondslag', 'jaarverplichting',
                   'rate', 'cap', 'franchise'}.

    Voor jaren ≠ 2026: same formule (publicatie 2026 — als premies
    later wijzigen, update deze constants per-jaar).
    """
    grondslag = max(
        0.0,
        min(SPH_GRONDSLAG_CAP_2026, winst_extrapolatie - SPH_FRANCHISE_2026),
    )
    jaarverplichting = grondslag * SPH_PREMIUM_RATE_2026
    return {
        'pensioengrondslag': grondslag,
        'jaarverplichting': jaarverplichting,
        'rate': SPH_PREMIUM_RATE_2026,
        'cap': SPH_GRONDSLAG_CAP_2026,
        'franchise': SPH_FRANCHISE_2026,
    }

DEFAULT_WIDGETS: dict[str, bool] = {
    'I-1': True,   # Cumulatieve omzet YoY
    'I-2': True,   # Kosten breakdown donut
    'I-3': True,   # SPH-status (T4b.1)
    'I-4': True,   # 6-weken prognose (T4b.1)
    'I-5': False,  # Top klanten (T4b.2)
    'I-6': False,  # Documenten checklist (T4b.2)
    'I-7': False,  # Cash-positie (T4b.3)
    'I-8': False,  # Tax-calendar full (T4b.3)
}


def _defaults_dict() -> dict:
    return {
        'schema_version': DASHBOARD_CONFIG_SCHEMA_VERSION,
        'widgets': dict(DEFAULT_WIDGETS),
        'prive_section_collapsed': None,
    }


def load_dashboard_widgets_config(raw_json: str | None) -> dict:
    """Load + validate dashboard config with 5 defensiveness rules:

    1. NULL → defaults
    2. Invalid JSON → defaults + log warning
    3. Not a dict → defaults
    4. schema_version mismatch → defaults + log warning (do NOT migrate silently)
    5. Unknown widget keys → ignored
    6. Missing widget keys → fall through to DEFAULT_WIDGETS

    Returns: {'schema_version': N, 'widgets': {...},
              'prive_section_collapsed': null | bool}
    """
    if raw_json is None:
        return _defaults_dict()

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        log.warning('dashboard_widgets_json invalid JSON, using defaults')
        return _defaults_dict()

    if not isinstance(parsed, dict):
        log.warning('dashboard_widgets_json not a dict, using defaults')
        return _defaults_dict()

    if parsed.get('schema_version') != DASHBOARD_CONFIG_SCHEMA_VERSION:
        log.warning(
            'dashboard_widgets_json schema_version mismatch '
            f'({parsed.get("schema_version")} != {DASHBOARD_CONFIG_SCHEMA_VERSION}), '
            'using defaults'
        )
        return _defaults_dict()

    user_widgets = parsed.get('widgets', {})
    if not isinstance(user_widgets, dict):
        return _defaults_dict()

    # Merge: known keys → user value if present + bool, else default
    merged = {}
    for key, default in DEFAULT_WIDGETS.items():
        user_val = user_widgets.get(key)
        merged[key] = user_val if isinstance(user_val, bool) else default

    # Defensiveness: prive_section_collapsed must be bool | None per contract;
    # any other type (string, dict, int) → None to avoid leaking junk to UI.
    raw_collapsed = parsed.get('prive_section_collapsed')
    prive_section_collapsed = raw_collapsed if isinstance(raw_collapsed, bool) else None

    return {
        'schema_version': DASHBOARD_CONFIG_SCHEMA_VERSION,
        'widgets': merged,
        'prive_section_collapsed': prive_section_collapsed,
    }


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


def tax_calendar(jaar: int) -> list[dict]:
    """Returns list of known Belastingdienst-deadlines for the year.

    Each entry: {'kind': str, 'date': date, 'label': str}.

    Hardcoded per-jaar — Belastingdienst publishes deadlines annually.
    Add new years here when next-year support is needed.
    """
    if jaar == 2026:
        return [
            {'kind': 'ib_aangifte', 'date': date(2026, 5, 1),
             'label': 'IB-aangifte deadline (rentevrij)'},
            {'kind': 'va_laatste_termijn', 'date': date(2026, 12, 31),
             'label': 'Laatste VA-termijn'},
            {'kind': 'va_uitbetaling', 'date': date(2026, 12, 15),
             'label': 'VA-uitbetaling teruggave'},
        ]
    if jaar == 2027:
        return [
            {'kind': 'ib_aangifte', 'date': date(2027, 5, 1),
             'label': 'IB-aangifte deadline (rentevrij)'},
            {'kind': 'va_laatste_termijn', 'date': date(2027, 12, 31),
             'label': 'Laatste VA-termijn'},
            {'kind': 'va_uitbetaling', 'date': date(2027, 12, 15),
             'label': 'VA-uitbetaling teruggave'},
        ]
    return []


def _seasonal_action_rows(today: date) -> list[ActionRow]:
    """Emit seasonal context-rows for action-inbox.

    Apr/Mei: IB-aangifte countdown
    Nov/Dec: VA-laatste termijn reminder

    Severity escalates as deadline approaches: <14 days = critical,
    <30 days = warning, else info.
    """
    rows: list[ActionRow] = []
    cal = tax_calendar(today.year)
    for entry in cal:
        deadline = entry['date']
        days_remaining = (deadline - today).days
        if days_remaining < 0 or days_remaining > 60:
            continue

        # Map kind → action-row kind
        if entry['kind'] == 'ib_aangifte':
            kind = 'ib_aangifte_deadline'
            link = '/aangifte'
        elif entry['kind'] == 'va_laatste_termijn':
            kind = 'va_laatste_termijn'
            link = '/aangifte'
        else:
            continue

        if days_remaining < 14:
            severity = 'critical'
        elif days_remaining < 30:
            severity = 'warning'
        else:
            severity = 'info'

        rows.append(ActionRow(
            kind=kind,
            severity=severity,
            message=f'{entry["label"]} over {days_remaining} dagen',
            action_kind=None,  # info-only, geen inline action
            link=link,
            age_days=0,
            metadata={'deadline': deadline.isoformat()},
        ))
    return rows
