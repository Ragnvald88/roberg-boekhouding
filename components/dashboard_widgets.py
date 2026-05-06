"""Per-tile renderers for /dashboard. NiceGUI-coupled.

Each render_* function takes raw data + a parent container, draws a
self-contained widget. Pure-data helpers live in services/dashboard.py.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from nicegui import ui

from components.utils import (
    format_datum_jaar_nl, format_euro,
)
from services.dashboard import ActionRow, VATrackSummary


# Severity → icon/color mapping. Critical uses Quasar negative token
# (cascade-safe — token-driven), warning uses amber hex (no token yet —
# matches confidence-badge pattern in dashboard.py for consistency),
# info uses --accent for brand-coupling.
_SEVERITY_ICON = {
    'critical': 'error',
    'warning': 'warning',
    'info': 'info_outline',
}
_SEVERITY_COLOR = {
    'critical': 'var(--q-negative)',
    'warning': '#D97706',  # amber — matches confidence-badge pattern
    'info': 'var(--accent)',
}


def render_action_inbox(
    rows: list[ActionRow],
    on_action: Callable[[ActionRow, str], None],
) -> None:
    """Render the consolidated action-inbox card.

    `on_action(row, action_kind)` is the dispatcher — receives the row
    and inline-action-kind, performs the action (open dialog, send mail,
    update status, etc.). Caller wires this to handlers.

    Replaces the previous wall of separate alert-card / severity-card
    items with one prioritised work-inbox (Acumulus-pattern).

    Inline actions zijn beperkt tot de 4 spec'd kinds (T3.4):
    stuur_herinnering, categoriseer, upload_nu, verstuur_concept.
    Andere row.action_kind waarden tonen alleen "Bekijk" via row.link.
    """
    with ui.card().classes('action-inbox w-full q-pa-md').style(
            'border: 1px solid var(--border); background: var(--surface)'):
        ui.label('Vandaag te doen').style(
            'font-weight: 600; font-size: 14px; '
            'color: var(--text); margin-bottom: 12px')

        if not rows:
            ui.label('Geen acties — alles bij.').classes(
                'text-caption text-grey-6')
            return

        for row in rows:
            with ui.row().classes(
                    'action-inbox-row w-full items-center gap-2'
                ).style(
                    'padding: 8px 4px; '
                    'border-bottom: 1px solid var(--border)'):
                icon = _SEVERITY_ICON.get(row.severity, 'info_outline')
                color = _SEVERITY_COLOR.get(row.severity, 'var(--accent)')
                ui.icon(icon, size='18px').style(f'color: {color}')
                ui.label(row.message).style('flex: 1; font-size: 13px')

                # Inline action knop (per row.action_kind). lambda r=row
                # closure captures row at definition time — voorkomt
                # late-binding bug waar alle buttons de laatste row zouden
                # zien als de loop variable na render verandert.
                if row.action_kind == 'stuur_herinnering':
                    ui.button(
                        'Stuur herinnering',
                        on_click=lambda r=row: on_action(r, 'stuur_herinnering'),
                    ).props('flat dense color=primary size=sm')
                elif row.action_kind == 'categoriseer':
                    ui.button(
                        'Categoriseer',
                        on_click=lambda r=row: on_action(r, 'categoriseer'),
                    ).props('flat dense color=primary size=sm')
                elif row.action_kind == 'upload_nu':
                    ui.button(
                        'Upload nu',
                        on_click=lambda r=row: on_action(r, 'upload_nu'),
                    ).props('flat dense color=primary size=sm')
                elif row.action_kind == 'verstuur_concept':
                    ui.button(
                        'Verstuur',
                        on_click=lambda r=row: on_action(r, 'verstuur_concept'),
                    ).props('flat dense color=primary size=sm')

                # Always: Bekijk (navigation) als link is gegeven
                if row.link:
                    ui.button(
                        'Bekijk',
                        on_click=lambda r=row: ui.navigate.to(r.link),
                    ).props('flat dense size=sm')


def render_sph_tile(
    sph_betaald_ytd: float,
    sph_prognose: dict,
) -> None:
    """Render I-3 SPH-status tile.

    Toont berekende jaarverplichting (op basis van winst-projectie) +
    YTD-betaald + progress-bar. Disclaimer benadrukt dat de echte
    SPH-aanslag op pensioenbasis 3 jaar terug wordt berekend (kan
    significant afwijken van projectie).
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('SPH-pensioen status').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        verplicht = sph_prognose['jaarverplichting']
        with ui.row().classes('items-baseline gap-2'):
            ui.label(f'Berekend {format_euro(verplicht, decimals=0)}').classes(
                'text-h6 num').style('color: var(--text)')
            ui.label('voor jaar').classes('text-caption text-grey-6')

        ui.label(f'Betaald YTD: {format_euro(sph_betaald_ytd, decimals=0)}').classes(
            'text-body2')

        if verplicht > 0:
            pct = min(100, sph_betaald_ytd / verplicht * 100)
            ui.linear_progress(value=pct / 100, size='6px',
                               color='positive' if pct > 80 else 'warning')

        ui.label(
            'Geschat — werkelijke verplichting wordt op pensioenbasis '
            '3 jaar terug berekend en kan ±20% afwijken.'
        ).classes('text-caption text-grey-6').style('margin-top: 8px')


def render_zes_weken_tile(weken: tuple) -> None:
    """Render I-4 6-weken omzet-prognose tile.

    `weken` = tuple[WeekTotaal, ...] from
    services.agenda.get_zes_weken_prognose. Per week tellen we
    `confirmed_amt + expected_amt` (geboekte werkdagen + verwachte
    rooster-entries) — dat is de volledige planning-outlook, niet
    alleen het nog-niet-bevestigde deel.
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('6-weken prognose').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if not weken:
            ui.label('Geen geplande werkdagen').classes(
                'text-caption text-grey-6')
            return

        week_bedragen = [w.confirmed_amt + w.expected_amt for w in weken]
        totaal = sum(week_bedragen)
        ui.label(format_euro(totaal, decimals=0)).classes('text-h6 num')
        ui.label(f'over {len(weken)} weken').classes(
            'text-caption text-grey-6')

        # Mini bar chart (ECharts) — accent kleur, geen y-axis labels
        # om de tile compact te houden.
        ui.echart({
            'grid': {'top': 5, 'bottom': 20, 'left': 0, 'right': 0},
            'xAxis': {
                'type': 'category',
                'data': [f'wk{w.week_nummer}' for w in weken],
                'axisLabel': {'fontSize': 9, 'color': '#94A3B8'},
            },
            'yAxis': {'show': False, 'type': 'value'},
            'series': [{
                'type': 'bar',
                'data': week_bedragen,
                'itemStyle': {'color': '#0F766E'},  # accent
            }],
            'tooltip': {'show': True},
        }).style('height: 80px; width: 100%')


def render_top_klanten_tile(klanten: list[dict]) -> None:
    """Render I-5 Top 5 klanten + concentratie tile.

    `klanten` from `get_omzet_per_klant(jaar)` — list[dict] with keys
    `naam` + `bedrag` (omzet excl concept), already sorted by bedrag
    DESC. Toont top-5 + percentage van het jaar-totaal zodat de
    gebruiker concentratierisico ziet (bijv. één opdrachtgever > 50%).
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('Top 5 klanten').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if not klanten:
            ui.label('Geen omzet').classes('text-caption text-grey-6')
            return

        top5 = klanten[:5]
        totaal = sum(k.get('bedrag', 0) for k in klanten)

        for k in top5:
            bedrag = k.get('bedrag', 0)
            pct = (bedrag / totaal * 100) if totaal > 0 else 0
            with ui.row().classes('w-full items-center gap-2'):
                ui.label(k.get('naam', '?')).style(
                    'flex: 1; font-size: 12px')
                ui.label(format_euro(bedrag, decimals=0)).classes(
                    'num').style('font-size: 12px')
                ui.label(f'{pct:.0f}%').classes(
                    'text-caption text-grey-6 num').style(
                    'width: 36px; text-align: right')


def render_documenten_tile(
    aangifte_docs: list,
    aangifte_docs_keys: list,
) -> None:
    """Render I-6 Aangifte-documenten checklist DETAIL tile.

    `aangifte_docs` = list of AangifteDocument objects from
    `get_aangifte_documenten(jaar)`.
    `aangifte_docs_keys` = list of expected document-specs. Accepts
    either:
      - list of `DocSpec` NamedTuples (e.g. `AANGIFTE_DOCS` directly), or
      - list of `(documenttype, label)` tuples, or
      - list of strings (documenttype keys; gebruikt zelf als label).
    De renderer normaliseert deze drie vormen naar `(key, label)` paren.
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('Aangifte-documenten').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        done = {d.documenttype for d in aangifte_docs}
        for spec in aangifte_docs_keys:
            # Normaliseer naar (key, label) — DocSpec NamedTuple heeft
            # documenttype + label velden; tuple/string fallbacks voor
            # callers die alleen de key meegeven.
            if hasattr(spec, 'documenttype'):
                key, label = spec.documenttype, spec.label
            elif isinstance(spec, str):
                key, label = spec, spec
            else:
                key, label = spec[0], (spec[1] if len(spec) > 1 else spec[0])
            is_done = key in done
            with ui.row().classes('w-full items-center gap-2'):
                icon = ('check_circle' if is_done
                        else 'radio_button_unchecked')
                color = ('var(--q-positive)' if is_done
                         else 'var(--muted)')
                ui.icon(icon, size='16px').style(f'color: {color}')
                ui.label(label).style('font-size: 12px; flex: 1')


def render_cash_positie_tile(
    opening_saldo: float | None,
    flow_ytd: float,
) -> None:
    """Render I-7 Cash-positie + flow YTD tile.

    `opening_saldo` from `fp.balans_bank_saldo` (None of 0 → empty-state).
    Per spec § E R1 wordt empty-state idealiter via `IS NULL` per jaar
    bepaald, maar het schema zet DEFAULT 0 zodat NULL aan de Python-kant
    altijd al naar 0 gecoerced is (zie `_row_to_fiscale_params`). Caller
    moet daarom 0 → None mappen vóór deze renderer aanroepen.

    `flow_ytd` = SUM(banktransacties.bedrag) voor het jaar — kan negatief
    zijn als kosten > inkomsten YTD.
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('Cash-positie').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if opening_saldo is None:
            with ui.column().classes('gap-1'):
                ui.label('Geen opening-saldo ingevuld').classes(
                    'text-body2 text-grey-6')
                ui.button(
                    'Vul in /instellingen',
                    on_click=lambda: ui.navigate.to(
                        '/instellingen?tab=fiscaal')) \
                    .props('flat dense color=primary size=sm')
            return

        current = opening_saldo + flow_ytd
        ui.label(format_euro(current, decimals=0)).classes('text-h6 num')
        ui.label(
            f'Opening: {format_euro(opening_saldo)} · '
            f'flow: {format_euro(flow_ytd)}'
        ).classes('text-caption text-grey-6')


def render_tax_calendar_tile(deadlines: list[dict]) -> None:
    """Render I-8 Tax-calendar (alle deadlines voor het jaar) tile.

    `deadlines` from `services.dashboard.tax_calendar(jaar)` — list[dict]
    met `kind`/`date`/`label` per deadline. Past en future deadlines
    worden allebei getoond (anders krimpt de tile end-of-year tot leeg);
    past deadlines tonen "voorbij" + grey, <14d future = red urgency.
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('Belasting-deadlines').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if not deadlines:
            ui.label('Geen deadlines bekend').classes(
                'text-caption text-grey-6')
            return

        today = date.today()
        for d in deadlines:
            days = (d['date'] - today).days
            # Color logic: <0 = past (muted), 0..14 = urgent (red),
            # >14 = normal (text). Exhaustive over int domain.
            if days < 0:
                color = 'var(--muted)'
                label_text = 'voorbij'
            elif days < 14:
                color = 'var(--q-negative)'
                label_text = f'{days}d'
            else:
                color = 'var(--text)'
                label_text = f'{days}d'
            with ui.row().classes('w-full items-center gap-2'):
                ui.label(d['label']).style(
                    f'flex: 1; font-size: 12px; color: {color}')
                ui.label(label_text).classes(
                    'text-caption num').style(f'color: {color}')


def render_prive_zone(aov_total: float, is_collapsed: bool) -> None:
    """Render Privé-vaste-lasten zone (AOV ONLY).

    AOV is conceptueel privé Box 1 inkomensvoorziening per CLAUDE.md
    "AOV: GEEN bedrijfskosten" — staat dus expliciet niet in de
    bedrijfs-kosten-kolom op het dashboard maar wel zichtbaar als
    privé-vaste-last (relevant voor netto-inkomen-projectie).

    GEEN persoonlijke SPH hier: SPH (Pensioenpremie SPH) is wel
    bedrijfskost in ons model, dus die hoort thuis bij /kosten en de
    SPH-tile, NIET in de privé-zone. Dit was de factuele error in
    v2-discussion die de spec heeft gecorrigeerd.

    `ui.expansion` voor collapse-gedrag. `is_collapsed=True` start
    dichtgeklapt. State-persist via toggle-handler in pages/dashboard.py
    is out-of-scope voor T5.1 — eerste render-iteratie respecteert
    alleen de inkomende `is_collapsed`-waarde uit `should_show_prive_zone`.
    """
    with ui.expansion(
            'Privé-vaste-lasten',
            icon='account_balance_wallet',
            value=not is_collapsed,
        ).classes('w-full prive-zone'):
        with ui.card().classes('w-full q-pa-md').style(
                'border: 1px solid var(--border)'):
            with ui.row().classes('items-center gap-2'):
                ui.label('AOV YTD:').style('font-size: 13px')
                ui.label(format_euro(aov_total, decimals=0)).classes(
                    'num').style('font-size: 13px; font-weight: 600')
            ui.label(
                'Niet aftrekbaar als bedrijfskost — wel relevant voor netto-inkomen.'
            ).classes('text-caption text-grey-6')


def render_va_tile(summary: VATrackSummary, jaar: int) -> None:
    """Render VA-tracker hero-tile op dashboard.

    User-feedback 2026-05-06 round-3: vorige tile had te veel detail (8
    regels: IB-line/IB-sub/ZVW-line/ZVW-sub/unmatched/volgende-termijn/
    bankdata-versheid). Hero-tile moet in 2 sec scanbaar zijn — detail
    hoort op de drill-down `/va-tracker/{jaar}` page.

    Nieuwe minimum-tile: title + hero-value (resterend) + 1 context-line.
    Click → /va-tracker/{jaar} voor alle detail.

    `.is-tekort` modifier alleen bij status='achter'. Overbetaald-badge
    alleen bij status='voldaan' AND has_overbetaald (Codex round-3
    line-first principe).
    """
    is_warning = (summary.status == 'achter')
    card_classes = 'dashboard-hero-tile'
    if is_warning:
        card_classes += ' is-tekort'

    with ui.card().classes(card_classes) \
            .style('cursor: pointer') \
            .on('click', lambda j=jaar: ui.navigate.to(f'/va-tracker/{j}')):
        # Title-row + warning icon (alleen bij echte achterstand)
        with ui.row().classes('w-full justify-between items-center'):
            ui.label(f'Voorlopige aanslag {jaar}').classes('hero-label')
            if is_warning:
                tooltip = (
                    f'Achterstand: '
                    f'{format_euro(summary.totaal_achterstand, decimals=0)}'
                )
                ui.icon('warning', size='18px').style(
                    'color: var(--q-negative)').tooltip(tooltip)

        # === Geen-data fallback
        if summary.status == 'geen_data':
            ui.label('—').classes('hero-value')
            ui.label('Geen data — klik voor uploaden').classes(
                'context-text').style('margin-top: 8px')
            return

        # === Geen-beschikking fallback (bankdata wel, beschikking niet)
        if summary.status == 'geen_beschikking':
            ui.label(format_euro(summary.totaal_betaald, decimals=0)) \
                .classes('hero-value')
            ui.label(
                'betaald — vul beschikking in voor exacte tracking'
            ).classes('context-text').style('margin-top: 8px')
            return

        # === Standaard: hero = resterend, 1 context-regel
        with ui.row().classes('w-full items-baseline gap-2'):
            ui.label(format_euro(summary.totaal_resterend, decimals=0)) \
                .classes('hero-value')
            # Overbetaald-badge: alleen bij voldaan AND has_overbetaald
            if summary.status == 'voldaan' and summary.has_overbetaald:
                overbetaald = (summary.ib.overbetaald
                               + summary.zvw.overbetaald)
                ui.label(
                    f'overbetaald {format_euro(overbetaald, decimals=0)}'
                ).style(
                    'font-size: 12px; color: var(--q-warning); '
                    'background: var(--bg-warning-soft); '
                    'padding: 2px 8px; border-radius: 10px')

        # === Eén context-line — kies de meest informatieve voor de state
        context_text = _va_tile_context_line(summary)
        if context_text:
            ui.label(context_text).classes('context-text').style(
                'margin-top: 8px')


def _va_tile_context_line(summary: VATrackSummary) -> str | None:
    """Bepaal 1 context-regel onder de hero (max signal in min tekens).

    Priority-order:
      1. status=achter   → "Achterstand: €X" (eerlijke EUR-zin, geen line-count)
      2. status=voldaan  → "voldaan"
      3. status=bij + volgende_termijn → "Volgende termijn: 30 jun 2026"
      4. status=bij      → "{N}/{M} termijnen voldaan"
      5. fallback        → None (geen extra regel)
    """
    if summary.status == 'achter':
        # Codex round-3 fix: vorige zin telde lines (1 IB-line met 3 gemiste
        # termijnen → "1 termijn verwacht" misleidend). EUR-totaal is eerlijk
        # en exact. Detail-breakdown staat op /va-tracker.
        return (f'Achterstand: '
                f'{format_euro(summary.totaal_achterstand, decimals=0)}')

    if summary.status == 'voldaan':
        return 'voldaan'

    # status='bij'
    if summary.volgende_termijn_datum is not None:
        return f'Volgende termijn: {format_datum_jaar_nl(summary.volgende_termijn_datum)}'

    # Geen volgende termijn (bv. closed-year of edge case) — toon counts
    n_betaald = (summary.ib.betaalde_termijnen
                 + summary.zvw.betaalde_termijnen)
    n_totaal = (summary.ib.totaal_termijnen
                + summary.zvw.totaal_termijnen)
    if n_totaal > 0:
        return f'{n_betaald}/{n_totaal} termijnen voldaan'
    return None
