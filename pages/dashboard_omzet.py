"""Omzet per klant detail pagina — drill-down vanuit dashboard KPI."""

from datetime import date

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import format_euro
from database import get_omzet_per_klant, DB_PATH


@ui.page('/dashboard/omzet')
async def omzet_detail_page():
    create_layout('Omzet per klant', '/')

    huidig_jaar = date.today().year
    jaren = {y: str(y) for y in range(huidig_jaar + 1, 2022, -1)}

    content_container = {'ref': None}

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):

        with ui.row().classes('w-full items-center gap-4'):
            ui.button(icon='arrow_back',
                      on_click=lambda: ui.navigate.to('/')).props('flat round')
            page_title('Omzet per klant')
            ui.space()
            jaar_select = ui.select(
                jaren, value=huidig_jaar, label='Jaar',
            ).classes('w-32')

        content_container['ref'] = ui.column().classes('w-full gap-4')

    async def refresh():
        jaar = jaar_select.value
        data = await get_omzet_per_klant(DB_PATH, jaar=jaar)
        container = content_container['ref']
        container.clear()

        with container:
            if not data:
                ui.label('Geen omzet gevonden voor dit jaar.').classes('text-grey')
                return

            totaal_bedrag = sum(r['bedrag'] for r in data)

            # Bar chart
            with ui.card().classes('w-full q-pa-lg'):
                namen = [r['naam'] for r in data]
                bedragen = [round(r['bedrag'], 2) for r in data]
                ui.echart({
                    'tooltip': {'trigger': 'axis'},
                    'xAxis': {'type': 'category', 'data': namen,
                              'axisLabel': {'rotate': 30}},
                    'yAxis': {'type': 'value',
                              'axisLabel': {'formatter': '€ {value}'}},
                    'series': [{
                        'type': 'bar',
                        'data': bedragen,
                        'itemStyle': {'color': '#0F766E'},
                    }],
                    'grid': {'bottom': 80},
                }).classes('w-full').style('height: 350px')

            # Table
            with ui.card().classes('w-full q-pa-lg'):
                columns = [
                    {'name': 'naam', 'label': 'Klant', 'field': 'naam',
                     'sortable': True, 'align': 'left'},
                    {'name': 'uren', 'label': 'Uren', 'field': 'uren_fmt',
                     'sortable': True, 'align': 'right'},
                    {'name': 'km', 'label': 'Km', 'field': 'km_fmt',
                     'align': 'right'},
                    {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
                     'sortable': True, 'align': 'right'},
                    {'name': 'pct', 'label': '% van totaal', 'field': 'pct',
                     'align': 'right'},
                ]
                rows = []
                for r in data:
                    pct = (r['bedrag'] / totaal_bedrag * 100) if totaal_bedrag > 0 else 0
                    rows.append({
                        'naam': r['naam'],
                        'uren_fmt': f"{r['uren']:.1f}",
                        'km_fmt': f"{r['km']:.0f}",
                        'bedrag_fmt': format_euro(r['bedrag']),
                        'pct': f"{pct:.1f}%",
                        'bedrag': r['bedrag'],
                    })

                ui.table(
                    columns=columns, rows=rows, row_key='naam',
                ).classes('w-full').props('dense flat')

                ui.separator()
                with ui.row().classes('w-full justify-between'):
                    ui.label('Totaal').classes('text-bold')
                    ui.label(format_euro(totaal_bedrag)).classes('text-bold')

    jaar_select.on_value_change(lambda _: refresh())
    await refresh()
