"""Dashboard pagina — KPIs, omzetgrafiek en kostenverdeling."""

import asyncio
from datetime import date, datetime

from nicegui import ui

from components.charts import cost_donut_chart, revenue_bar_chart
from components.kpi_card import kpi_card
from components.layout import create_layout, page_title
from components.utils import format_euro, format_datum
from database import (
    get_kpis, get_omzet_per_maand, get_uitgaven_per_categorie,
    get_openstaande_facturen,
    get_werkdagen_ongefactureerd_summary, get_km_totaal,
    get_fiscale_params, update_ib_inputs, add_aangifte_document,
    get_aangifte_documenten, DB_PATH,
)
from components.fiscal_utils import fetch_fiscal_data, extrapoleer_jaaromzet
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
            page_title('Overzicht')
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

    async def _compute_ib_estimate(jaar: int) -> dict | None:
        """Compute IB estimate based on BUSINESS data only.

        Dashboard = business performance. Personal deductions (hypotheek, WOZ,
        AOV, lijfrente) belong on the Aangifte page. The VA beschikking from BD
        already includes those deductions, so the bij/terug comparison still works.
        """
        data = await fetch_fiscal_data(DB_PATH, jaar)
        if data is None:
            return None

        try:
            huidig_jaar = date.today().year
            annual_va_ib = data['voorlopige_aanslag']
            annual_va_zvw = data['voorlopige_aanslag_zvw']

            if jaar == huidig_jaar:
                month = date.today().month

                # Extrapolate income
                projection = await extrapoleer_jaaromzet(DB_PATH, jaar)
                complete_months = projection['basis_maanden'] or 1
                kosten_factor = 12 / complete_months

                omzet = projection['extrapolated_omzet']
                kosten = data['kosten_excl_inv'] * kosten_factor
                repr_ = data['representatie'] * kosten_factor
                uren = data['uren'] * kosten_factor

                # Prorate VA for "how much have I paid so far"
                va_ib_ytd = round(annual_va_ib * month / 12, 2)
                va_zvw_ytd = round(annual_va_zvw * month / 12, 2)
            else:
                omzet = data['omzet']
                kosten = data['kosten_excl_inv']
                repr_ = data['representatie']
                uren = data['uren']
                va_ib_ytd = annual_va_ib
                va_zvw_ytd = annual_va_zvw
                month = 12
                projection = {
                    'confidence': 'high',
                    'basis_maanden': 12,
                    'extrapolated_omzet': omzet,
                    'ytd_omzet': omzet,
                }

            # Business-only calculation — NO personal deductions
            f = bereken_volledig(
                omzet=omzet, kosten=kosten,
                afschrijvingen=data['totaal_afschrijvingen'],
                representatie=repr_,
                investeringen_totaal=data['inv_totaal_dit_jaar'],
                uren=uren, params=data['params_dict'],
                aov=0, lijfrente=0,       # personal → Aangifte
                woz=0, hypotheekrente=0,  # personal → Aangifte
                voorlopige_aanslag=annual_va_ib,
                voorlopige_aanslag_zvw=annual_va_zvw,
                ew_naar_partner=True,
            )

            ytd_winst = (data['omzet'] - data['kosten_excl_inv']
                         - data['totaal_afschrijvingen'])

            return {
                'resultaat': f.resultaat,
                'netto_ib': f.netto_ib,
                'zvw': f.zvw,
                'winst': f.winst,
                'ytd_winst': ytd_winst,
                'va_ib_betaald': va_ib_ytd,
                'va_zvw_betaald': va_zvw_ytd,
                'prorated': jaar == huidig_jaar,
                'month': month,
                'confidence': projection['confidence'],
                'basis_maanden': projection['basis_maanden'],
            }
        except Exception:
            import traceback
            traceback.print_exc()
            return None

    async def refresh_dashboard():
        jaar = jaar_select.value

        # Run all independent DB calls concurrently
        (kpis, kpis_vorig, omzet_huidig, omzet_vorig, kosten_per_cat,
         openstaande, ongefact, km_data,
         ib_resultaat, fp) = await asyncio.gather(
            get_kpis(DB_PATH, jaar=jaar),
            get_kpis(DB_PATH, jaar=jaar - 1),
            get_omzet_per_maand(DB_PATH, jaar=jaar),
            get_omzet_per_maand(DB_PATH, jaar=jaar - 1),
            get_uitgaven_per_categorie(DB_PATH, jaar=jaar),
            get_openstaande_facturen(DB_PATH, jaar=jaar),
            get_werkdagen_ongefactureerd_summary(DB_PATH, jaar=jaar),
            get_km_totaal(DB_PATH, jaar=jaar),
            _compute_ib_estimate(jaar),
            get_fiscale_params(DB_PATH, jaar),
        )

        uren_criterium = int(fp.urencriterium) if fp else URENCRITERIUM_DEFAULT

        _MND = {1: 'jan', 2: 'feb', 3: 'mrt', 4: 'apr',
                5: 'mei', 6: 'jun', 7: 'jul', 8: 'aug',
                9: 'sep', 10: 'okt', 11: 'nov', 12: 'dec'}

        # KPI cards — responsive CSS grid
        kpi_row = kpi_container['ref']
        kpi_row.clear()
        with kpi_row:
            with ui.element('div').classes('w-full').style(
                    'display: grid; grid-template-columns: '
                    'repeat(auto-fill, minmax(260px, 1fr)); gap: 16px'):

                # 1. Bruto omzet
                kpi_card('Bruto omzet', format_euro(kpis['omzet']),
                         'trending_up', '#0F766E',
                         on_click=lambda: ui.navigate.to('/werkdagen'),
                         delta_pct=_yoy_delta(kpis['omzet'],
                                              kpis_vorig['omzet']))

                # 2. Resultaat (actual YTD winst — NOT extrapolated)
                if ib_resultaat is not None:
                    resultaat = ib_resultaat.get('ytd_winst', ib_resultaat['winst'])
                else:
                    resultaat = kpis['winst']
                kpi_card('Resultaat', format_euro(resultaat),
                         'account_balance',
                         '#059669' if resultaat >= 0 else '#DC2626')

                # 3. Belasting prognose (enhanced)
                if ib_resultaat is not None:
                    ib_data = ib_resultaat
                    belasting_totaal = ib_data['netto_ib'] + ib_data['zvw']

                    # Check if VA has been entered (annual amounts, not YTD)
                    va_ib_annual = fp.voorlopige_aanslag_betaald if fp else 0
                    va_zvw_annual = fp.voorlopige_aanslag_zvw if fp else 0
                    has_va = (va_ib_annual or 0) > 0 or (va_zvw_annual or 0) > 0

                    va_ytd = ib_data['va_ib_betaald'] + ib_data['va_zvw_betaald']

                    if has_va:
                        # VA is entered — show bij/terug result
                        res = ib_data['resultaat']
                        if res < 0:
                            ib_label = f'Terug: {format_euro(abs(res))}'
                            ib_color = '#059669'
                        elif res > 0:
                            ib_label = f'Bij: {format_euro(res)}'
                            ib_color = '#DC2626'
                        else:
                            ib_label = format_euro(0)
                            ib_color = '#0F766E'
                    else:
                        # VA NOT entered — show computed tax, NOT "bij"
                        ib_label = format_euro(belasting_totaal)
                        ib_color = '#0F766E'

                    def ib_extra(d=ib_data, _has_va=has_va, _vt=va_ytd,
                                 _bel=belasting_totaal, _jaar=jaar):
                        with ui.column().classes('gap-1 q-mt-xs w-full'):
                            if _has_va:
                                # Show progress bars: berekend vs VA betaald
                                va_label = (f"VA t/m {_MND[d['month']]}"
                                            if d['prorated'] else 'VA betaald')
                                for label, value, color in [
                                    ('Berekend', _bel, 'negative'),
                                    (va_label, -_vt, 'positive'),
                                ]:
                                    with ui.row().classes(
                                            'w-full items-center gap-2'):
                                        ui.label(label).classes('text-caption') \
                                            .style('width: 80px; color: #64748B')
                                        max_val = max(abs(_bel), abs(_vt), 1)
                                        ui.linear_progress(
                                            value=min(abs(value) / max_val, 1.0),
                                            color=color,
                                        ).classes('flex-grow') \
                                            .props('rounded size=6px')
                                        ui.label(format_euro(value)) \
                                            .classes('text-caption') \
                                            .style(
                                                'min-width: 80px; text-align: right; '
                                                'font-variant-numeric: tabular-nums')
                            else:
                                # VA not entered — show clear message + button
                                ui.label('Berekende jaarbelasting (IB + ZVW)') \
                                    .classes('text-caption text-grey-6')

                                async def open_va_dialog():
                                    import asyncio as _aio
                                    from pathlib import Path as _P

                                    _fp = await get_fiscale_params(DB_PATH, _jaar)
                                    cur_ib = _fp.voorlopige_aanslag_betaald if _fp else 0
                                    cur_zvw = _fp.voorlopige_aanslag_zvw if _fp else 0

                                    # Track uploaded files
                                    uploads = {'ib': None, 'zvw': None}

                                    with ui.dialog() as dlg, \
                                            ui.card().classes('w-full max-w-lg q-pa-md'):
                                        ui.label('Voorlopige aanslagen invoeren') \
                                            .classes('text-h6')
                                        ui.label(
                                            f'Vul de jaarbedragen in van je VA '
                                            f'beschikking {_jaar} en upload de PDF\'s.'
                                        ).classes('text-body2 text-grey-7 q-mb-sm')

                                        # IB section
                                        with ui.card().classes('w-full q-pa-sm') \
                                                .style('background: #F8FAFC'):
                                            ui.label('Inkomstenbelasting') \
                                                .classes('text-subtitle2')
                                            with ui.row().classes(
                                                    'w-full items-end gap-4'):
                                                va_ib_in = ui.number(
                                                    'Jaarbedrag',
                                                    value=cur_ib or 0,
                                                    format='%.2f', prefix='\u20ac',
                                                ).classes('flex-grow')
                                                ui.upload(
                                                    label='PDF beschikking',
                                                    auto_upload=True,
                                                    on_upload=lambda e:
                                                        uploads.update({'ib': e}),
                                                ).classes('w-48').props(
                                                    'flat bordered dense '
                                                    'accept=".pdf"')

                                        # ZVW section
                                        with ui.card().classes('w-full q-pa-sm') \
                                                .style('background: #F8FAFC'):
                                            ui.label('Zorgverzekeringswet') \
                                                .classes('text-subtitle2')
                                            with ui.row().classes(
                                                    'w-full items-end gap-4'):
                                                va_zvw_in = ui.number(
                                                    'Jaarbedrag',
                                                    value=cur_zvw or 0,
                                                    format='%.2f', prefix='\u20ac',
                                                ).classes('flex-grow')
                                                ui.upload(
                                                    label='PDF beschikking',
                                                    auto_upload=True,
                                                    on_upload=lambda e:
                                                        uploads.update({'zvw': e}),
                                                ).classes('w-48').props(
                                                    'flat bordered dense '
                                                    'accept=".pdf"')

                                        async def save_va():
                                            # Validate: require amounts
                                            ib_val = float(va_ib_in.value or 0)
                                            zvw_val = float(va_zvw_in.value or 0)
                                            if ib_val <= 0 and zvw_val <= 0:
                                                ui.notify(
                                                    'Vul minimaal één jaarbedrag in',
                                                    type='warning')
                                                return

                                            # Save amounts
                                            await update_ib_inputs(
                                                DB_PATH, jaar=_jaar,
                                                aov_premie=_fp.aov_premie or 0,
                                                woz_waarde=_fp.woz_waarde or 0,
                                                hypotheekrente=_fp.hypotheekrente or 0,
                                                voorlopige_aanslag_betaald=float(
                                                    va_ib_in.value or 0),
                                                voorlopige_aanslag_zvw=float(
                                                    va_zvw_in.value or 0),
                                                lijfrente_premie=_fp.lijfrente_premie or 0,
                                            )

                                            # Save uploaded PDFs
                                            aangifte_dir = DB_PATH.parent / 'aangifte'
                                            aangifte_dir.mkdir(exist_ok=True)
                                            today = date.today().isoformat()

                                            for key, doctype in [
                                                ('ib', 'va_ib_beschikking'),
                                                ('zvw', 'va_zvw_beschikking'),
                                            ]:
                                                evt = uploads.get(key)
                                                if evt is None:
                                                    continue
                                                fname = _P(evt.file.name).name
                                                dest = aangifte_dir / fname
                                                content = await evt.file.read()
                                                await _aio.to_thread(
                                                    dest.write_bytes, content)
                                                await add_aangifte_document(
                                                    DB_PATH, jaar=_jaar,
                                                    categorie='voorlopige_aanslag',
                                                    documenttype=doctype,
                                                    bestandsnaam=fname,
                                                    bestandspad=str(dest),
                                                    upload_datum=today,
                                                )

                                            dlg.close()
                                            ui.notify('VA opgeslagen', type='positive')
                                            await refresh_dashboard()

                                        with ui.row().classes(
                                                'w-full justify-end gap-2 q-mt-md'):
                                            ui.button('Annuleren',
                                                      on_click=dlg.close) \
                                                .props('flat')
                                            ui.button('Opslaan', icon='save',
                                                      on_click=save_va) \
                                                .props('color=primary')
                                    dlg.open()

                                ui.button(
                                    'VA invoeren', icon='edit',
                                    on_click=open_va_dialog,
                                ).props('flat dense color=primary size=sm') \
                                    .classes('q-mt-xs')

                            # Confidence badge
                            conf = d.get('confidence', 'high')
                            conf_map = {
                                'low': ('warning', 'Schatting'),
                                'medium': ('primary', 'Prognose'),
                                'high': ('positive', 'Betrouwbaar'),
                            }
                            c_color, c_label = conf_map.get(conf, ('grey', ''))
                            ui.badge(c_label, color=c_color) \
                                .classes('text-xs q-mt-xs')

                    kpi_card(
                        'Belasting prognose', ib_label,
                        'calculate', ib_color,
                        extra=ib_extra,
                        on_click=(lambda: ui.navigate.to('/aangifte'))
                        if has_va else None,
                    )

                # 4. Bedrijfslasten
                kpi_card('Bedrijfslasten', format_euro(kpis['kosten']),
                         'payments', '#D97706',
                         on_click=lambda: ui.navigate.to('/kosten'),
                         delta_pct=_yoy_delta(kpis['kosten'],
                                              kpis_vorig['kosten']))

                # 5. Urencriterium
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

                # 6. Openstaand
                openstaand_count = len(openstaande)
                openstaand_label = (
                    f"{openstaand_count} ({format_euro(kpis['openstaand'])})"
                    if openstaand_count > 0 else "0")
                kpi_card('Openstaand', openstaand_label,
                         'pending',
                         '#D97706' if openstaand_count > 0 else '#059669',
                         on_click=lambda: ui.navigate.to('/facturen'))

                # 7. Km-vergoeding (if applicable)
                if km_data['km'] > 0:
                    km_label = (f"{km_data['km']:.0f} km "
                                f"({format_euro(km_data['vergoeding'])})")
                    kpi_card('Km-vergoeding', km_label,
                             'directions_car', '#0F766E')

                # 8. Documenten completeness
                docs = await get_aangifte_documenten(DB_PATH, jaar)
                done_docs = len({d.documenttype for d in docs})
                # 13 document types defined in aangifte.py AANGIFTE_DOCS
                total_docs = 13
                doc_color = '#059669' if done_docs >= total_docs else '#D97706'

                def doc_extra(_done=done_docs, _total=total_docs):
                    ratio = _done / _total if _total else 0
                    ui.linear_progress(
                        value=ratio,
                        color='positive' if ratio == 1 else 'warning',
                    ).classes('w-full q-mt-sm').props('rounded size=8px')

                kpi_card('Documenten',
                         f'{done_docs}/{total_docs} compleet',
                         'folder', doc_color, doc_extra,
                         on_click=lambda: ui.navigate.to('/aangifte'))

        # Charts + alerts
        chart_row = chart_container['ref']
        chart_row.clear()
        with chart_row:
            # Alerts first (actionable items above charts)
            if ongefact['aantal'] > 0:
                with ui.card().classes('w-full q-pa-md bg-orange-1') \
                        .style('border-color: var(--q-warning)'):
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
                with ui.card().classes('w-full q-pa-md bg-yellow-1') \
                        .style('border-color: var(--q-warning)'):
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

            # Charts
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
                            .classes('q-pa-md').style('color: #64748B')


    jaar_select.on_value_change(lambda _: refresh_dashboard())
    await refresh_dashboard()
