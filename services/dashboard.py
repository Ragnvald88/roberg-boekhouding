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


def should_show_prive_zone(
    aov_count: int,
    user_override_collapsed: bool | None,
) -> tuple[bool, bool]:
    """Returns (should_render, is_collapsed_by_default).

    Auto-detect: geen AOV-tx → don't render at all (clean dashboard for
    users zonder AOV-flag). Met AOV → render visible. User-override
    (bedrijfsgegevens.dashboard_widgets_json.prive_section_collapsed)
    overrules auto-detect zodat de user de zone kan tonen/dichthouden
    onafhankelijk van DB-staat.

    Logic:
    - user_override_collapsed=True  → render but collapsed (user pinned dicht)
    - user_override_collapsed=False → render visible        (user pinned open)
    - user_override_collapsed=None  → auto-detect via aov_count
        - aov_count > 0  → render visible
        - aov_count == 0 → don't render
    """
    if user_override_collapsed is True:
        return (True, True)
    if user_override_collapsed is False:
        return (True, False)
    # auto-detect
    if aov_count > 0:
        return (True, False)
    return (False, False)


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


# === VA-tracker (Sprint I) ============================================

@dataclass(frozen=True)
class VATrackLine:
    """Per-soort (IB of ZVW) voortgang van de voorlopige aanslag.

    `verplicht` = BD-beschikkingsbedrag voor het jaar (alias voor het
    misleidend genaamde `voorlopige_aanslag_betaald` resp. `_zvw` veld
    in fiscale_params — zie models.FiscaleParams comment).

    `betaald` + `betaalde_termijnen` komen uit get_va_betalingen op basis
    van bankdata + kenmerk-positie [10:12] split.

    `achterstand` is in EUR maar **termijn-count-based**:
    `max(expected_terms - betaalde_termijnen, 0) × termijnbedrag`. Niet
    EUR-based (`verwacht - betaald`) — dat zou off-schedule lump-sum
    payments per ongeluk als "op koers" zien terwijl er feitelijk een
    termijn-vervaldatum is gemist (Codex round-3 motivatie: BD rekent
    termijn-vervaltermijnen, niet EUR-totalen).

    `overbetaald` is een @property — derive uit betaald/verplicht zonder
    state. Voorkomt inconsistentie als velden ooit handmatig worden gezet.
    """
    soort: str  # 'IB' | 'ZVW'
    verplicht: float
    betaald: float
    betaalde_termijnen: int
    totaal_termijnen: int
    termijnbedrag: float
    resterend: float
    achterstand: float

    @property
    def overbetaald(self) -> float:
        return max(self.betaald - self.verplicht, 0.0)


@dataclass(frozen=True)
class VATrackSummary:
    """Combined IB + ZVW tracker-state voor /dashboard tile."""
    ib: VATrackLine
    zvw: VATrackLine
    totaal_verplicht: float
    totaal_betaald: float          # excl. unmatched (na BREAKING contract)
    totaal_resterend: float
    totaal_achterstand: float
    unmatched_betaald: float       # bankdata zonder bruikbaar kenmerk
    unmatched_termijnen: int
    has_bank_data: bool
    bankdata_tot_datum: date | None
    status: str                    # geen_data|geen_beschikking|bij|achter|voldaan
    has_overbetaald: bool          # attribute, niet status (line-first ordering)
    volgende_termijn_datum: date | None  # None bij voldaan/closed/geen-data


def _expected_terms_elapsed(termijnen: int, today: date, jaar: int) -> int:
    """Aantal termijnen dat tot vandaag betaald had moeten zijn.

    Convention: aantal termijnen N impliceert eerste-termijn-maand =
    13 - N (N=11 → feb-start, N=12 → jan-start). Onze heuristiek, geen
    BD-bron-waarheid; documenteren in CLAUDE.md (T2.1).
    """
    if today.year < jaar:
        return 0
    if today.year > jaar:
        return termijnen
    eerste_maand = 13 - termijnen
    return min(termijnen, max(0, today.month - eerste_maand + 1))


def _last_day_of_month(year: int, month: int) -> date:
    """Laatste kalenderdag van de maand (BD betaalt typisch ultimo)."""
    if month == 12:
        return date(year, 12, 31)
    next_month_first = date(year, month + 1, 1)
    return date.fromordinal(next_month_first.toordinal() - 1)


def compute_va_tracker(
    *,
    jaar: int,
    va_data: dict,
    ib_verplicht: float,
    zvw_verplicht: float,
    ib_termijnen: int = 11,
    zvw_termijnen: int = 11,
    today: date,
) -> VATrackSummary:
    """Pure helper voor VA-tracker tile op /dashboard.

    Status-rangschikking is line-first (Codex round-3 catch — voorkomt
    dat IB-overbetaling een ZVW-achterstand maskeert).
    """
    def _clamp_terms(n: int) -> int:
        return min(12, max(1, int(n or 11)))

    def _line(soort: str, verplicht: float, betaald: float,
              betaalde_termijnen: int, termijnen: int) -> VATrackLine:
        termijnen = _clamp_terms(termijnen)
        verplicht = max(0.0, float(verplicht or 0))
        betaald = max(0.0, float(betaald or 0))
        bet_n = int(betaalde_termijnen or 0)
        termijnbedrag = verplicht / termijnen if verplicht > 0 else 0.0
        expected_n = _expected_terms_elapsed(termijnen, today, jaar)
        # Achterstand is termijn-count-based (not EUR-based): off-schedule
        # payments — bv. 1 lump-sum bedrag — kunnen anders per ongeluk
        # achterstand maskeren (Codex round-3 motivatie). Termijnen-diff
        # is wat de Belastingdienst zelf rekent voor vervaldatum-achterstand.
        missing_terms = max(expected_n - bet_n, 0)
        return VATrackLine(
            soort=soort,
            verplicht=verplicht,
            betaald=betaald,
            betaalde_termijnen=bet_n,
            totaal_termijnen=termijnen,
            termijnbedrag=termijnbedrag,
            resterend=max(verplicht - betaald, 0.0),
            achterstand=missing_terms * termijnbedrag,
        )

    ib = _line('IB', ib_verplicht, va_data.get('ib_betaald', 0),
               va_data.get('ib_termijnen', 0), ib_termijnen)
    zvw = _line('ZVW', zvw_verplicht, va_data.get('zvw_betaald', 0),
                va_data.get('zvw_termijnen', 0), zvw_termijnen)

    totaal_verplicht = ib.verplicht + zvw.verplicht
    totaal_betaald = ib.betaald + zvw.betaald
    totaal_resterend = ib.resterend + zvw.resterend
    totaal_achterstand = ib.achterstand + zvw.achterstand
    has_bank_data = bool(va_data.get('has_bank_data'))
    has_input = totaal_verplicht > 0

    # Status — line-first ordering
    if not has_input and not has_bank_data:
        status = 'geen_data'
    elif not has_input and has_bank_data:
        status = 'geen_beschikking'
    elif any(line.achterstand > 1 for line in [ib, zvw]):
        status = 'achter'
    elif totaal_resterend == 0 and has_input:
        status = 'voldaan'
    else:
        status = 'bij'

    # has_overbetaald detecteert ELKE lijn met overbetaling — ook als
    # totaal_resterend > 0 (bv. IB overbetaald + ZVW nog open). Codex
    # round-3 line-first principle: nooit een overbetaling verbergen
    # achter een totaal-aggregate.
    has_overbetaald = any(line.overbetaald > 0 for line in [ib, zvw])

    # Volgende termijn — alleen bij open verplichting (Codex D-1)
    volgende: date | None = None
    if status in ('achter', 'bij') and totaal_resterend > 0:
        # Voor 'achter': toon oudste onbetaalde termijn (overdue date) —
        # antwoord op "wanneer had ik moeten betalen?". Voor 'bij': toon
        # eerstvolgende toekomstige termijn (Codex round-2 finding 2).
        candidates: list[date] = []
        for line in (ib, zvw):
            if line.resterend > 0 and line.verplicht > 0:
                eerste_maand = 13 - line.totaal_termijnen
                if status == 'achter':
                    next_idx = line.betaalde_termijnen + 1
                else:  # 'bij'
                    expected = _expected_terms_elapsed(line.totaal_termijnen,
                                                        today, jaar)
                    next_idx = max(line.betaalde_termijnen, expected) + 1
                if next_idx > line.totaal_termijnen:
                    continue
                next_maand = eerste_maand + next_idx - 1
                if 1 <= next_maand <= 12:
                    candidates.append(_last_day_of_month(jaar, next_maand))
        if candidates:
            volgende = min(candidates)

    return VATrackSummary(
        ib=ib, zvw=zvw,
        totaal_verplicht=totaal_verplicht,
        totaal_betaald=totaal_betaald,
        totaal_resterend=totaal_resterend,
        totaal_achterstand=totaal_achterstand,
        unmatched_betaald=float(va_data.get('unmatched_betaald', 0) or 0),
        unmatched_termijnen=int(va_data.get('unmatched_termijnen', 0) or 0),
        has_bank_data=has_bank_data,
        bankdata_tot_datum=va_data.get('bankdata_tot_datum'),
        status=status,
        has_overbetaald=has_overbetaald,
        volgende_termijn_datum=volgende,
    )


# === VA-tracker drill-down (Sprint J T1.4) ============================
# Per-termijn schedule + async wrapper voor /va-tracker page render.

@dataclass(frozen=True)
class TermijnRow:
    """Eén termijn-rij in de drill-down schedule.

    `vervaldatum` = ultimo van de maand (BD-conventie).
    `status`:
      - 'betaald'   → bank-tx in deze maand gevonden
      - 'verwacht'  → vervaldatum in het verleden, geen bank-tx (overdue)
      - 'toekomst'  → vervaldatum in de toekomst
    """
    maand: int                       # 1-12
    vervaldatum: date
    bedrag: float                    # termijn-bedrag = verplicht / N
    status: Literal['betaald', 'verwacht', 'toekomst']
    betaald_op: date | None
    betaald_bedrag: float | None


def compute_va_termijnen_schedule(
    *,
    bedrag: float,
    termijnen: int,
    jaar: int,
    bank_tx: list[dict],
    today: date,
) -> list[TermijnRow]:
    """Bouw de per-termijn schedule voor één soort (IB of ZVW).

    Conventie: `eerste_maand = 13 - termijnen` (N=11 → feb-start, N=12 →
    jan-start). Zelfde heuristiek als `_expected_terms_elapsed`.

    Bank-tx matching is per kalendermaand (eerste tx in de maand wint).
    Caller filtert `bank_tx` zelf op kenmerk-classificatie (IB / ZVW)
    voordat de lijst hier komt — dit is een pure helper, geen DB-query.

    Returns: list[TermijnRow] met N rijen voor maanden binnen [1..12].
    """
    if termijnen <= 0:
        return []

    eerste_maand = 13 - termijnen
    termijn_bedrag = bedrag / termijnen if termijnen > 0 else 0.0

    # Group bank-tx per kalendermaand binnen `jaar`. Sorteer op datum
    # zodat de "eerste tx in de maand" deterministisch is bij meerdere
    # betalingen in dezelfde maand.
    def _to_date(v) -> date:
        return date.fromisoformat(v) if isinstance(v, str) else v

    bank_by_month: dict[int, list[dict]] = {}
    for tx in sorted(bank_tx, key=lambda t: t['datum']):
        tx_d = _to_date(tx['datum'])
        if tx_d.year == jaar:
            bank_by_month.setdefault(tx_d.month, []).append(tx)

    rows: list[TermijnRow] = []
    for offset in range(termijnen):
        maand = eerste_maand + offset
        if maand < 1 or maand > 12:
            continue
        vervaldatum = _last_day_of_month(jaar, maand)
        match = bank_by_month.get(maand)
        if match:
            tx = match[0]
            rows.append(TermijnRow(
                maand=maand,
                vervaldatum=vervaldatum,
                bedrag=termijn_bedrag,
                status='betaald',
                betaald_op=_to_date(tx['datum']),
                betaald_bedrag=float(tx['bedrag']),
            ))
        elif vervaldatum < today:
            rows.append(TermijnRow(
                maand=maand,
                vervaldatum=vervaldatum,
                bedrag=termijn_bedrag,
                status='verwacht',
                betaald_op=None,
                betaald_bedrag=None,
            ))
        else:
            rows.append(TermijnRow(
                maand=maand,
                vervaldatum=vervaldatum,
                bedrag=termijn_bedrag,
                status='toekomst',
                betaald_op=None,
                betaald_bedrag=None,
            ))
    return rows


async def load_va_tracker_summary(
    db_path,
    jaar: int,
    today: date,
) -> VATrackSummary:
    """Async wrapper: fetch beschikkingen + bankdata → compute_va_tracker.

    Datasource fall-through per soort:
      1. active beschikking (voorlopige_aanslagen, is_active=1)
      2. handmatig fp-veld (`voorlopige_aanslag_betaald` / `_zvw`)
      3. defaults (0 bedrag, 11 termijnen)

    Importing `database` lazy om service → database circulariteit te vermijden
    in scripts die alleen de pure helpers willen gebruiken.
    """
    from database import (
        get_active_voorlopige_aanslag,
        get_va_betalingen,
        get_fiscale_params,
    )

    fp = await get_fiscale_params(db_path, jaar)
    ib_b = await get_active_voorlopige_aanslag(db_path, jaar, 'ib')
    zvw_b = await get_active_voorlopige_aanslag(db_path, jaar, 'zvw')
    va_data = await get_va_betalingen(db_path, jaar)

    if ib_b is not None:
        ib_verplicht = float(ib_b['bedrag'] or 0)
        ib_termijnen = int(ib_b['termijnen'] or 11)
    else:
        ib_verplicht = float((fp.voorlopige_aanslag_betaald if fp else 0) or 0)
        ib_termijnen = int(
            (getattr(fp, 'voorlopige_aanslag_ib_termijnen', 11) if fp else 11)
            or 11
        )

    if zvw_b is not None:
        zvw_verplicht = float(zvw_b['bedrag'] or 0)
        zvw_termijnen = int(zvw_b['termijnen'] or 11)
    else:
        zvw_verplicht = float((fp.voorlopige_aanslag_zvw if fp else 0) or 0)
        zvw_termijnen = int(
            (getattr(fp, 'voorlopige_aanslag_zvw_termijnen', 11) if fp else 11)
            or 11
        )

    return compute_va_tracker(
        jaar=jaar,
        va_data=va_data,
        ib_verplicht=ib_verplicht,
        zvw_verplicht=zvw_verplicht,
        ib_termijnen=ib_termijnen,
        zvw_termijnen=zvw_termijnen,
        today=today,
    )
