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
                .style('color: #0F172A; font-weight: 700')
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


def kpi_strip(winst: float, belastbare_winst: float,
              netto_ib_zvw: float, resultaat: float):
    """4 compact KPI cards for jaarafsluiting. Result card has colored left border."""
    with ui.row().classes('w-full gap-3 flex-wrap'):
        for label, value, icon in [
            ('Winst', format_euro(winst), 'trending_up'),
            ('Belastbare winst', format_euro(belastbare_winst), 'calculate'),
            ('IB + ZVW', format_euro(netto_ib_zvw), 'receipt_long'),
        ]:
            with ui.card().classes('flex-1 min-w-48 q-pa-md'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon(icon, size='1.2rem').style('color: #0F766E')
                    ui.label(label).classes('text-caption').style('color: #64748B')
                ui.label(value).classes('text-h6 q-mt-xs') \
                    .style('color: #0F172A; font-weight: 700')
        # Result card — colored left border
        border_color = '#059669' if resultaat <= 0 else '#DC2626'
        text_class = 'text-positive' if resultaat < 0 else 'text-negative' if resultaat > 0 else ''
        if resultaat < 0:
            res_label = f'{format_euro(abs(resultaat))} terug'
        elif resultaat > 0:
            res_label = f'{format_euro(resultaat)} bij'
        else:
            res_label = format_euro(0)
        with ui.card().classes('flex-1 min-w-48 q-pa-md') \
                .style(f'border-left: 4px solid {border_color}'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('account_balance_wallet', size='1.2rem').classes(text_class)
                ui.label('Resultaat').classes('text-caption').style('color: #64748B')
            ui.label(res_label).classes(f'text-h6 q-mt-xs {text_class}') \
                .style('font-weight: 700')
