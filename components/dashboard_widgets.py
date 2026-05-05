"""Per-tile renderers for /dashboard. NiceGUI-coupled.

Each render_* function takes raw data + a parent container, draws a
self-contained widget. Pure-data helpers live in services/dashboard.py.
"""
from __future__ import annotations

from typing import Callable

from nicegui import ui

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
