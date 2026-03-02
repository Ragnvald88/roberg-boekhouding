"""Dashboard pagina — KPIs, omzetgrafiek en kostenverdeling."""

from datetime import date, datetime

from nicegui import ui

from components.charts import cost_donut_chart, revenue_bar_chart
from components.layout import create_layout
from components.utils import format_euro, format_datum
from database import (
    get_kpis, get_omzet_per_maand, get_uitgaven_per_categorie,
    get_recente_facturen, get_openstaande_facturen, get_factuur_count,
    DB_PATH,
)

URENCRITERIUM = 1225


def kpi_card(label: str, value: str, icon: str, color: str = '#0F766E',
             extra=None, on_click=None):
    """Render a single KPI card, optionally clickable."""
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
        ui.label(value).classes('text-h5 q-mt-sm') \
            .style('color: #0F172A; font-weight: 700')
        if extra:
            extra()


@ui.page('/')
async def dashboard_page():
    create_layout('Dashboard', '/')

    huidig_jaar = date.today().year
    jaren = {y: str(y) for y in range(huidig_jaar + 1, 2022, -1)}

    kpi_container = {'ref': None}
    chart_container = {'ref': None}

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):

        # Year selector
        with ui.row().classes('w-full items-center gap-4'):
            ui.label('Overzicht').classes('text-h5') \
                .style('color: #0F172A; font-weight: 700')
            ui.space()
            jaar_select = ui.select(
                jaren, value=huidig_jaar, label='Jaar',
            ).classes('w-32')

        # KPI cards
        kpi_container['ref'] = ui.column().classes('w-full gap-4')

        # Charts
        chart_container['ref'] = ui.column().classes('w-full gap-4')

        # Quick actions
        with ui.row().classes('w-full gap-3'):
            ui.button(
                'Werkdag toevoegen', icon='add_circle',
                on_click=lambda: ui.navigate.to('/werkdagen'),
            ).props('outline color=primary')
            ui.button(
                'Nieuwe factuur', icon='receipt_long',
                on_click=lambda: ui.navigate.to('/facturen'),
            ).props('outline color=primary')

    async def refresh_dashboard():
        jaar = jaar_select.value
        kpis = await get_kpis(DB_PATH, jaar=jaar)
        omzet_huidig = await get_omzet_per_maand(DB_PATH, jaar=jaar)
        omzet_vorig = await get_omzet_per_maand(DB_PATH, jaar=jaar - 1)
        kosten_per_cat = await get_uitgaven_per_categorie(DB_PATH, jaar=jaar)
        recente = await get_recente_facturen(DB_PATH, limit=5)
        openstaande = await get_openstaande_facturen(DB_PATH, jaar=jaar)
        factuur_count = await get_factuur_count(DB_PATH, jaar=jaar)

        # KPI cards
        kpi_row = kpi_container['ref']
        kpi_row.clear()
        with kpi_row:
            # Row 1: Revenue KPIs
            with ui.row().classes('w-full gap-4 flex-wrap'):
                kpi_card('Bruto omzet', format_euro(kpis['omzet']),
                         'trending_up', '#0F766E',
                         on_click=lambda: ui.navigate.to('/dashboard/omzet'))

                openstaand_count = len(openstaande)
                openstaand_label = (f"{openstaand_count} ({format_euro(kpis['openstaand'])})"
                                    if openstaand_count > 0 else "0")
                kpi_card('Openstaand', openstaand_label,
                         'pending',
                         '#D97706' if openstaand_count > 0 else '#059669',
                         on_click=lambda: ui.navigate.to('/facturen'))

                resultaat = kpis['winst']
                kpi_card('Resultaat', format_euro(resultaat),
                         'account_balance',
                         '#059669' if resultaat >= 0 else '#DC2626')

            # Row 2: Operations KPIs
            with ui.row().classes('w-full gap-4 flex-wrap'):
                kpi_card('Bedrijfslasten', format_euro(kpis['kosten']),
                         'payments', '#D97706',
                         on_click=lambda: ui.navigate.to('/kosten'))

                # Urencriterium with progress
                uren = kpis['uren']
                uren_voldaan = uren >= URENCRITERIUM
                uren_hex = '#059669' if uren_voldaan else '#D97706'
                uren_pct = min(uren / URENCRITERIUM, 1.0) if URENCRITERIUM > 0 else 0

                def uren_extra():
                    ui.linear_progress(
                        value=uren_pct,
                        color='positive' if uren_voldaan else 'warning',
                    ).classes('w-full q-mt-sm').props('rounded size=8px')

                kpi_card('Urencriterium',
                         f"{uren:.0f} / {URENCRITERIUM:,} uur".replace(",", "."),
                         'schedule', uren_hex, uren_extra)

                kpi_card('Facturen', f"{factuur_count} facturen",
                         'receipt', '#0F766E',
                         on_click=lambda: ui.navigate.to('/facturen'))

        # Charts + tables
        chart_row = chart_container['ref']
        chart_row.clear()
        with chart_row:
            with ui.row().classes('w-full gap-4 flex-wrap'):
                with ui.card().classes('flex-1 min-w-80 q-pa-lg'):
                    ui.label('Omzet per maand').classes('text-subtitle1') \
                        .style('color: #0F172A; font-weight: 600')
                    ui.label(f'{jaar} vs {jaar - 1}').classes('text-body2') \
                        .style('color: #64748B')
                    revenue_bar_chart(omzet_huidig, omzet_vorig, jaar)

                with ui.card().classes('flex-1 min-w-80 q-pa-lg'):
                    ui.label('Kostenverdeling').classes('text-subtitle1') \
                        .style('color: #0F172A; font-weight: 600')
                    ui.label(str(jaar)).classes('text-body2') \
                        .style('color: #64748B')
                    if kosten_per_cat:
                        cost_donut_chart(kosten_per_cat)
                    else:
                        ui.label('Geen uitgaven gevonden.') \
                            .classes('q-pa-md').style('color: #94A3B8')

            # Openstaande facturen detail list
            if openstaande:
                with ui.card().classes('w-full q-pa-md') \
                        .style('background-color: #FFFBEB; border-color: #FCD34D'):
                    with ui.row().classes('items-center gap-2 q-mb-sm'):
                        ui.icon('warning_amber', size='1.2rem') \
                            .style('color: #D97706')
                        ui.label('Openstaande facturen') \
                            .style('color: #92400E; font-weight: 600')

                    columns = [
                        {'name': 'nummer', 'label': 'Nummer', 'field': 'nummer',
                         'align': 'left'},
                        {'name': 'klant', 'label': 'Klant', 'field': 'klant_naam',
                         'align': 'left'},
                        {'name': 'datum', 'label': 'Datum', 'field': 'datum_fmt',
                         'align': 'left'},
                        {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
                         'align': 'right'},
                        {'name': 'dagen', 'label': 'Dagen open', 'field': 'dagen_open',
                         'align': 'right'},
                    ]
                    rows = []
                    for f in openstaande:
                        try:
                            dagen = (date.today() - datetime.strptime(f.datum, '%Y-%m-%d').date()).days
                        except (ValueError, TypeError):
                            dagen = 0
                        rows.append({
                            'nummer': f.nummer,
                            'klant_naam': f.klant_naam,
                            'datum_fmt': format_datum(f.datum),
                            'bedrag_fmt': format_euro(f.totaal_bedrag),
                            'dagen_open': dagen,
                        })
                    ui.table(
                        columns=columns, rows=rows, row_key='nummer',
                    ).classes('w-full').props('dense flat')

            # Recente facturen
            if recente:
                with ui.card().classes('w-full q-pa-lg'):
                    ui.label('Recente facturen').classes('text-subtitle1') \
                        .style('color: #0F172A; font-weight: 600')
                    columns = [
                        {'name': 'nummer', 'label': 'Nummer', 'field': 'nummer',
                         'align': 'left'},
                        {'name': 'datum', 'label': 'Datum', 'field': 'datum_fmt',
                         'align': 'left'},
                        {'name': 'klant', 'label': 'Klant', 'field': 'klant_naam',
                         'align': 'left'},
                        {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
                         'align': 'right'},
                        {'name': 'status', 'label': 'Status', 'field': 'status',
                         'align': 'center'},
                    ]
                    rows = []
                    for f in recente:
                        rows.append({
                            'nummer': f.nummer,
                            'datum_fmt': format_datum(f.datum),
                            'klant_naam': f.klant_naam,
                            'bedrag_fmt': format_euro(f.totaal_bedrag),
                            'status': 'Betaald' if f.betaald else 'Openstaand',
                            'betaald': f.betaald,
                        })
                    t = ui.table(
                        columns=columns, rows=rows, row_key='nummer',
                    ).classes('w-full').props('dense flat')
                    t.add_slot('body-cell-status', '''
                        <q-td :props="props">
                            <q-badge :color="props.row.betaald ? 'positive' : 'warning'"
                                     :label="props.row.status" />
                        </q-td>
                    ''')

    jaar_select.on_value_change(lambda _: refresh_dashboard())
    await refresh_dashboard()
