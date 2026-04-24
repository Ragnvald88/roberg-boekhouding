"""Kosten pagina — overzicht + activastaat. Read-only.

Mutations live on /transacties. This page is summary-only.
"""
import asyncio
from datetime import date
from urllib.parse import quote_plus

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
                # P2-1: refresh whichever tab is currently active — the
                # Investeringen tab used to render stale data after a
                # jaar change until the user manually re-selected it.
                if tabs.value == 'Investeringen':
                    await ververs_investeringen()
                else:
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
    """KPI strip: totaal kosten, te verwerken (→ /transacties),
    afschrijvingen, investeringen count.

    "Te verwerken" is clickable — navigates to /transacties filtered to
    ongecategoriseerd so the user can continue the reconciliation flow.
    """
    if container is None:
        return
    container.clear()
    kpi = await get_kpi_kosten(DB_PATH, jaar)

    def _card(label: str, value: str, sub: str | None = None,
              color: str = 'primary', icon: str | None = None,
              on_click=None):
        with ui.card().classes(
                'flex-1 q-pa-md cursor-pointer' if on_click
                else 'flex-1 q-pa-md') as c:
            if on_click:
                c.on('click', lambda _: on_click())
            with ui.row().classes('items-center gap-2'):
                if icon:
                    ui.icon(icon, color=color).classes('text-lg')
                ui.label(label).classes(
                    'text-caption text-uppercase text-grey')
            ui.label(value).classes('text-h5 text-bold q-mt-xs') \
                .style('font-variant-numeric: tabular-nums')
            if sub:
                ui.label(sub).classes('text-caption text-grey')

    with container:
        _card(f'Totaal kosten {jaar}',
              format_euro(kpi.totaal),
              f'{len([m for m in kpi.monthly_totals if m>0])} actieve maanden')

        _card('Te verwerken',
              str(kpi.ontbreekt_count),
              format_euro(kpi.ontbreekt_bedrag),
              color='warning', icon='warning',
              on_click=lambda: ui.navigate.to(
                  f'/transacties?status=ongecategoriseerd&jaar={jaar}'))

        _card(f'Afschrijvingen {jaar}',
              format_euro(kpi.afschrijvingen_jaar),
              'Zie tab Investeringen',
              icon='trending_down')

        _card(f'Investeringen {jaar}',
              str(kpi.investeringen_count),
              format_euro(kpi.investeringen_bedrag),
              icon='inventory_2')


async def _laad_per_maand(container, jaar):
    """Per-maand bar chart: 12 bars Jan-Dec with € amount on hover.

    Data from get_kosten_per_maand — covers debits + manual cash,
    excludes genegeerd. Gives seasonality at a glance.
    """
    if container is None:
        return
    container.clear()
    data = await get_kosten_per_maand(DB_PATH, jaar)
    months = ['Jan', 'Feb', 'Mrt', 'Apr', 'Mei', 'Jun',
              'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dec']
    with container:
        with ui.card().classes('w-full q-pa-md'):
            ui.label(f'Kosten per maand — {jaar}') \
                .classes('text-subtitle1 text-bold')
            ui.echart({
                'xAxis': {'type': 'category', 'data': months},
                'yAxis': {'type': 'value'},
                'tooltip': {
                    'trigger': 'axis',
                    'valueFormatter': (
                        "function(v){ return '€ ' + "
                        "Number(v).toLocaleString('nl-NL',"
                        "{minimumFractionDigits:2}); }"),
                },
                'series': [{
                    'type': 'bar',
                    'data': [round(v, 2) for v in data],
                    'itemStyle': {'color': '#0F766E'},
                }],
                'grid': {'left': 60, 'right': 20, 'top': 20, 'bottom': 40},
            }).classes('w-full').style('height:240px')


async def _laad_breakdown(container, jaar):
    """Per-categorie breakdown: clickable bars → /transacties?categorie=...

    M7 polish (from 2026-04-21 Kosten rework review): the empty-categorie
    bucket renders as a separate muted card ABOVE the bar list so it
    doesn't visually dwarf real categories.
    """
    if container is None:
        return
    container.clear()
    totals = await get_kosten_breakdown(DB_PATH, jaar)
    if not totals:
        return

    # Extract the uncategorised bucket
    uncat_amount = totals.pop('', 0.0)
    sorted_totals = sorted(totals.items(),
                             key=lambda kv: kv[1], reverse=True)
    grand = sum(totals.values()) + uncat_amount

    with container:
        # P1-3: the uncategorised bucket now routes to /transacties
        # (mirroring the "Te verwerken" KPI card) so the user can click
        # straight through from overview to reconciliation.
        if uncat_amount > 0:
            uncat_card = ui.card().classes(
                'w-full q-pa-md cursor-pointer') \
                .style('background:#f8fafc;'
                        'border-left:4px solid #f59e0b')
            with uncat_card:
                with ui.row().classes('w-full items-center'):
                    ui.icon('warning', color='warning').classes('text-lg')
                    ui.label('Nog te categoriseren') \
                        .classes('text-body2')
                    ui.space()
                    ui.label(format_euro(uncat_amount)) \
                        .classes('text-body2 text-bold') \
                        .style('font-variant-numeric:tabular-nums')
                ui.label(
                    'Klik om deze op /transacties te categoriseren.') \
                    .classes('text-caption text-grey')
            uncat_card.on(
                'click',
                lambda _=None: ui.navigate.to(
                    f'/transacties?status=ongecategoriseerd&jaar={jaar}'))

        # Real categories — clickable bars
        with ui.card().classes('w-full q-pa-md'):
            with ui.row().classes('w-full items-center'):
                ui.label(f'Kosten per categorie — {jaar}') \
                    .classes('text-subtitle1 text-bold')
                ui.space()
                ui.label(f'Totaal {format_euro(grand)}') \
                    .classes('text-caption text-grey')

            for name, amt in sorted_totals:
                pct = (amt / grand * 100) if grand else 0
                row = ui.column().classes(
                    'w-full gap-0 q-my-xs cursor-pointer')
                with row:
                    with ui.row().classes('w-full'):
                        ui.label(name).classes('text-body2')
                        ui.space()
                        ui.label(
                            f'{format_euro(amt)} · {pct:.1f}%') \
                            .classes('text-body2 text-bold') \
                            .style('font-variant-numeric:tabular-nums')
                    ui.linear_progress(value=pct / 100) \
                        .props('color=primary size=6px')
                row.on('click', lambda _=None, n=name:
                        ui.navigate.to(
                            f'/transacties?jaar={jaar}'
                            f'&categorie={quote_plus(n)}'))


async def _laad_terugkerend(container, jaar):
    """Terugkerende kosten: vendors with >=3 betalingen in the last 12mnd.

    Lets the user see at a glance which abonnementen / vaste lasten run.
    Each row navigates to /transacties?search=<tegenpartij> so the user
    can review or reconcile in one click.
    """
    if container is None:
        return
    container.clear()
    items = await get_terugkerende_kosten(DB_PATH, jaar=jaar)
    if not items:
        return
    with container:
        with ui.card().classes('w-full q-pa-md'):
            ui.label(f'Terugkerende kosten — {jaar}') \
                .classes('text-subtitle1 text-bold')
            ui.label('Tegenpartijen met 3 of meer betalingen in de '
                      'laatste 12 maanden.') \
                .classes('text-caption text-grey q-mb-sm')
            for item in items:
                row = ui.row().classes(
                    'w-full items-center q-py-xs cursor-pointer')
                with row:
                    ui.label(item['tegenpartij']) \
                        .classes('text-body2').style('flex:1')
                    ui.label(str(item['count'])) \
                        .classes('text-caption text-grey') \
                        .style('width:40px')
                    ui.label(item['laatste_datum']) \
                        .classes('text-caption text-grey') \
                        .style('width:110px')
                    ui.label(format_euro(item['jaar_totaal'])) \
                        .classes('text-body2 text-bold') \
                        .style('font-variant-numeric:tabular-nums;'
                                'width:110px;text-align:right')
                row.on('click', lambda _=None, tp=item['tegenpartij']:
                        ui.navigate.to(
                            f'/transacties?jaar={jaar}'
                            f'&search={quote_plus(tp)}'))
