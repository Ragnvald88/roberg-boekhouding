"""Shared KPI strip component for jaarafsluiting."""

from nicegui import ui

from components.utils import format_euro


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
