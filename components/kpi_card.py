"""Shared KPI card components for dashboard and jaarafsluiting."""

from nicegui import ui

from components.utils import format_euro


def kpi_card(label: str, value: str, icon: str, color: str = '#0F766E',
             extra=None, on_click=None, delta_pct: float = None):
    """Render a single KPI card, optionally clickable, with optional YoY delta."""
    card_props = 'q-pa-lg flex-1 min-w-52 kpi-card'
    if on_click:
        card_props += ' cursor-pointer'
    card = ui.card().classes(card_props)
    if on_click:
        card.on('click', on_click)
        card.style('transition: box-shadow 0.15s').props('hover')
    with card:
        with ui.row().classes('items-center justify-between w-full'):
            ui.label(label).classes('text-body2').style('color: #64748B')
            ui.icon(icon, size='1.5rem') \
                .style(f'color: {color}; background-color: {color}15; '
                       'border-radius: 8px; padding: 8px')
        with ui.row().classes('items-end gap-2 q-mt-sm'):
            ui.label(value).classes('text-h5') \
                .style('color: #0F172A; font-weight: 700; font-variant-numeric: tabular-nums')
            if delta_pct is not None:
                sign = '+' if delta_pct >= 0 else ''
                d_color = '#059669' if delta_pct >= 0 else '#DC2626'
                d_icon = 'trending_up' if delta_pct >= 0 else 'trending_down'
                with ui.row().classes('items-center gap-0'):
                    ui.icon(d_icon, size='0.9rem').style(f'color: {d_color}')
                    ui.label(f'{sign}{delta_pct:.0f}%').classes(
                        'text-caption').style(f'color: {d_color}')
        if extra:
            extra()


def kpi_strip(omzet: float, winst: float,
              eigen_vermogen: float, balanstotaal: float):
    """4 compact KPI cards for jaarafsluiting — business-only metrics."""
    with ui.row().classes('w-full gap-3 flex-wrap'):
        for label, value, icon in [
            ('Omzet', format_euro(omzet), 'trending_up'),
            ('Winst', format_euro(winst), 'savings'),
            ('Eigen vermogen', format_euro(eigen_vermogen), 'account_balance'),
            ('Balanstotaal', format_euro(balanstotaal), 'balance'),
        ]:
            with ui.card().classes('flex-1 min-w-48 q-pa-md'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon(icon, size='1.2rem').style('color: #0F766E')
                    ui.label(label).classes('text-caption').style('color: #64748B')
                ui.label(value).classes('text-h6 q-mt-xs') \
                    .style('color: #0F172A; font-weight: 700; font-variant-numeric: tabular-nums')
