"""Dashboard pagina — KPIs, omzetgrafiek en kostenverdeling."""

from datetime import date, datetime

from nicegui import ui

from components.charts import cost_donut_chart, revenue_bar_chart
from components.kpi_card import kpi_card
from components.layout import create_layout
from components.utils import format_euro, format_datum
from database import (
    get_kpis, get_omzet_per_maand, get_uitgaven_per_categorie,
    get_recente_facturen, get_openstaande_facturen, get_factuur_count,
    get_werkdagen_ongefactureerd_summary, get_km_totaal,
    get_fiscale_params, get_uren_totaal, get_omzet_totaal,
    get_representatie_totaal, get_investeringen,
    get_investeringen_voor_afschrijving,
    DB_PATH,
)
from fiscal.afschrijvingen import bereken_afschrijving
from fiscal.berekeningen import bereken_volledig

URENCRITERIUM_DEFAULT = 1225


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

    def _yoy_delta(current: float, previous: float) -> float | None:
        """Calculate YoY delta percentage. Returns None if no previous data."""
        if previous and previous > 0:
            return (current - previous) / previous * 100
        return None

    async def _compute_ib_estimate(jaar: int) -> float | None:
        """Compute estimated IB resultaat from DB data. Returns None if no params."""
        params = await get_fiscale_params(DB_PATH, jaar)
        if not params:
            return None
        from components.fiscal_utils import fiscale_params_to_dict
        params_dict = fiscale_params_to_dict(params)
        omzet = await get_omzet_totaal(DB_PATH, jaar)
        repr_totaal = await get_representatie_totaal(DB_PATH, jaar)
        kosten_per_cat = await get_uitgaven_per_categorie(DB_PATH, jaar)
        totaal_kosten = sum(r['totaal'] for r in kosten_per_cat)
        inv_dit_jaar = await get_investeringen(DB_PATH, jaar=jaar)
        inv_bedrag = sum((u.aanschaf_bedrag or u.bedrag) for u in inv_dit_jaar)
        kosten_excl_inv = totaal_kosten - inv_bedrag
        investeringen = await get_investeringen_voor_afschrijving(
            DB_PATH, tot_jaar=jaar)
        totaal_afschr = 0.0
        for u in investeringen:
            aanschaf = (u.aanschaf_bedrag or u.bedrag) * (
                (u.zakelijk_pct or 100) / 100)
            result = bereken_afschrijving(
                aanschaf_bedrag=aanschaf,
                restwaarde_pct=u.restwaarde_pct or 10,
                levensduur=u.levensduur_jaren or 5,
                aanschaf_maand=int(u.datum[5:7]),
                aanschaf_jaar=int(u.datum[0:4]),
                bereken_jaar=jaar,
            )
            totaal_afschr += result['afschrijving']
        inv_totaal = sum(
            (u.aanschaf_bedrag or u.bedrag) * ((u.zakelijk_pct or 100) / 100)
            for u in inv_dit_jaar
        )
        uren = await get_uren_totaal(DB_PATH, jaar, urennorm_only=True)
        fiscaal = bereken_volledig(
            omzet=omzet, kosten=kosten_excl_inv,
            afschrijvingen=totaal_afschr, representatie=repr_totaal,
            investeringen_totaal=inv_totaal, uren=uren,
            params=params_dict,
            aov=params.aov_premie or 0, woz=params.woz_waarde or 0,
            hypotheekrente=params.hypotheekrente or 0,
            voorlopige_aanslag=params.voorlopige_aanslag_betaald or 0,
        )
        return fiscaal.resultaat

    async def refresh_dashboard():
        jaar = jaar_select.value
        kpis = await get_kpis(DB_PATH, jaar=jaar)
        kpis_vorig = await get_kpis(DB_PATH, jaar=jaar - 1)
        omzet_huidig = await get_omzet_per_maand(DB_PATH, jaar=jaar)
        omzet_vorig = await get_omzet_per_maand(DB_PATH, jaar=jaar - 1)
        kosten_per_cat = await get_uitgaven_per_categorie(DB_PATH, jaar=jaar)
        recente = await get_recente_facturen(DB_PATH, limit=5)
        openstaande = await get_openstaande_facturen(DB_PATH, jaar=jaar)
        factuur_count = await get_factuur_count(DB_PATH, jaar=jaar)
        ongefact = await get_werkdagen_ongefactureerd_summary(DB_PATH, jaar=jaar)
        km_data = await get_km_totaal(DB_PATH, jaar=jaar)
        ib_resultaat = await _compute_ib_estimate(jaar)

        # Read urencriterium from DB (fall back to default)
        fp = await get_fiscale_params(DB_PATH, jaar)
        uren_criterium = int(fp.urencriterium) if fp else URENCRITERIUM_DEFAULT

        # KPI cards
        kpi_row = kpi_container['ref']
        kpi_row.clear()
        with kpi_row:
            # Row 1: Revenue KPIs
            with ui.row().classes('w-full gap-4 flex-wrap'):
                kpi_card('Bruto omzet', format_euro(kpis['omzet']),
                         'trending_up', '#0F766E',
                         on_click=lambda: ui.navigate.to('/werkdagen'),
                         delta_pct=_yoy_delta(kpis['omzet'],
                                              kpis_vorig['omzet']))

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
                         '#059669' if resultaat >= 0 else '#DC2626',
                         delta_pct=_yoy_delta(kpis['winst'],
                                              kpis_vorig['winst']))

            # Row 2: Operations KPIs
            with ui.row().classes('w-full gap-4 flex-wrap'):
                kpi_card('Bedrijfslasten', format_euro(kpis['kosten']),
                         'payments', '#D97706',
                         on_click=lambda: ui.navigate.to('/kosten'),
                         delta_pct=_yoy_delta(kpis['kosten'],
                                              kpis_vorig['kosten']))

                # Urencriterium with progress
                uren = kpis['uren']
                uren_voldaan = uren >= uren_criterium
                uren_hex = '#059669' if uren_voldaan else '#D97706'
                uren_pct = min(uren / uren_criterium, 1.0) if uren_criterium > 0 else 0

                def uren_extra():
                    ui.linear_progress(
                        value=uren_pct,
                        color='positive' if uren_voldaan else 'warning',
                    ).classes('w-full q-mt-sm').props('rounded size=8px')

                kpi_card('Urencriterium',
                         f"{uren:.0f} / {uren_criterium:,} uur".replace(",", "."),
                         'schedule', uren_hex, uren_extra)

                kpi_card('Facturen', f"{factuur_count} facturen",
                         'receipt', '#0F766E',
                         on_click=lambda: ui.navigate.to('/facturen'))

            # Row 3: IB + Km
            with ui.row().classes('w-full gap-4 flex-wrap'):
                if ib_resultaat is not None:
                    if ib_resultaat < 0:
                        ib_label = f'Terug: {format_euro(abs(ib_resultaat))}'
                        ib_color = '#059669'
                    elif ib_resultaat > 0:
                        ib_label = f'Bij: {format_euro(ib_resultaat)}'
                        ib_color = '#DC2626'
                    else:
                        ib_label = format_euro(0)
                        ib_color = '#0F766E'
                    kpi_card('Geschatte IB', ib_label,
                             'calculate', ib_color,
                             on_click=lambda: ui.navigate.to('/aangifte'))

                if km_data['km'] > 0:
                    km_label = f"{km_data['km']:.0f} km ({format_euro(km_data['vergoeding'])})"
                    kpi_card('Km-vergoeding', km_label,
                             'directions_car', '#0F766E')

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

            # Ongefactureerde werkdagen alert
            if ongefact['aantal'] > 0:
                with ui.card().classes('w-full q-pa-md') \
                        .style('background-color: #FFF7ED; border-color: #FDBA74'):
                    with ui.row().classes('items-center justify-between w-full'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('assignment_late', size='1.2rem') \
                                .style('color: #D97706')
                            ui.label(
                                f"{ongefact['aantal']} ongefactureerde werkdagen "
                                f"({format_euro(ongefact['bedrag'])})"
                            ).style('color: #92400E; font-weight: 600')
                        ui.button('Bekijk', icon='arrow_forward',
                                  on_click=lambda: ui.navigate.to('/werkdagen')
                                  ).props('flat dense color=warning')

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
