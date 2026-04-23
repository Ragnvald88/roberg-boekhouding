"""Kosten pagina — overzicht + activastaat. Read-only.

Mutations live on /transacties. This page is summary-only.
"""
import asyncio
from datetime import date

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import format_euro
from components.shared_ui import year_options
from database import (
    DB_PATH, get_kpi_kosten, get_kosten_breakdown,
    get_kosten_per_maand, get_terugkerende_kosten,
)
from pages.kosten_investeringen import laad_activastaat


@ui.page('/kosten')
async def kosten_page():
    create_layout('Kosten', '/kosten')
    huidig_jaar = date.today().year
    filter_jaar = {'value': huidig_jaar}

    kpi_container = {'ref': None}
    chart_container = {'ref': None}
    breakdown_container = {'ref': None}
    terugkerend_container = {'ref': None}
    activa_container = {'ref': None}

    async def ververs_overview():
        await _laad_kpi(kpi_container['ref'], filter_jaar['value'])
        await _laad_per_maand(chart_container['ref'], filter_jaar['value'])
        await _laad_breakdown(breakdown_container['ref'],
                                filter_jaar['value'])
        await _laad_terugkerend(terugkerend_container['ref'],
                                  filter_jaar['value'])

    async def ververs_investeringen():
        await laad_activastaat(
            activa_container['ref'], filter_jaar['value'],
            ververs_overview)

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):
        with ui.row().classes('w-full items-center'):
            page_title('Kosten')

        with ui.row().classes('items-center gap-2'):
            jaar_select = ui.select(
                {j: str(j) for j in year_options()},
                label='Jaar', value=huidig_jaar,
            ).classes('w-28')

            async def on_jaar_change():
                filter_jaar['value'] = jaar_select.value
                await ververs_overview()

            jaar_select.on('update:model-value',
                            lambda _=None: on_jaar_change())

        with ui.tabs().classes('w-full') as tabs:
            tab_overview = ui.tab('Overzicht', icon='insights')
            tab_inv = ui.tab('Investeringen', icon='inventory_2')

        with ui.tab_panels(tabs, value=tab_overview).classes('w-full'):
            with ui.tab_panel(tab_overview):
                kpi_container['ref'] = ui.row().classes('w-full gap-4')
                chart_container['ref'] = ui.column().classes('w-full')
                breakdown_container['ref'] = ui.column().classes('w-full')
                terugkerend_container['ref'] = \
                    ui.column().classes('w-full')

            with ui.tab_panel(tab_inv):
                activa_container['ref'] = \
                    ui.column().classes('w-full gap-2')

        async def on_tab_change():
            if tabs.value == 'Investeringen':
                await ververs_investeringen()

        tabs.on('update:model-value',
                 lambda _: asyncio.create_task(on_tab_change()))

    await ververs_overview()


# -------------------------------------------------------------- #
# Loader stubs — filled in Tasks 21-24                           #
# -------------------------------------------------------------- #
async def _laad_kpi(container, jaar):
    """KPI strip — wired in Task 21."""
    pass


async def _laad_per_maand(container, jaar):
    """Per-maand bar chart — wired in Task 22."""
    pass


async def _laad_breakdown(container, jaar):
    """Categorie breakdown clickable + uncat M7 card — wired in Task 23."""
    pass


async def _laad_terugkerend(container, jaar):
    """Terugkerende kosten card — wired in Task 24."""
    pass
