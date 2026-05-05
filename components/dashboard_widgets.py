"""Per-tile renderers for /dashboard. NiceGUI-coupled.

Each render_* function takes raw data + a parent container, draws a
self-contained widget. Pure-data helpers live in services/dashboard.py.
"""
from __future__ import annotations

from typing import Callable

from nicegui import ui

from components.utils import format_euro
from services.dashboard import ActionRow


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
