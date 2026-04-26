"""Dashboard pagina — hero KPIs, sparklines, contextual alerts."""

import asyncio
import logging
from datetime import date, datetime

log = logging.getLogger(__name__)

from nicegui import ui

from components.charts import cost_donut_chart, revenue_bar_chart
from components.layout import create_layout, page_title
from components.utils import format_euro
from database import (
    get_kpis, get_kpis_tot_datum, get_omzet_per_maand,
    get_uitgaven_per_categorie, get_openstaande_facturen,
    get_werkdagen_ongefactureerd_summary, get_km_totaal,
    get_fiscale_params, get_aangifte_documenten,
    get_va_betalingen, get_health_alerts, DB_PATH,
)
from components.document_specs import AANGIFTE_DOCS
from components.fiscal_utils import fetch_fiscal_data, extrapoleer_jaaromzet
from components.shared_ui import year_options
from fiscal.berekeningen import bereken_volledig
from fiscal.constants import URENCRITERIUM_DEFAULT


def _has_va_data(fp, va_data) -> bool:
    """Return True iff any voorlopige aanslag is registered for the year.

    Three independent sources count:
    - manual IB-VA: fp.voorlopige_aanslag_betaald
    - manual ZVW-VA: fp.voorlopige_aanslag_zvw  (was missed before; bug A5)
    - bank-imported VA payments: va_data['has_bank_data']

    fp may be None (no fiscale_params row yet for the year). va_data is
    expected to be a dict with optional 'has_bank_data' key.
    """
    if not fp:
        return bool(va_data.get('has_bank_data', False))
    return bool(
        (getattr(fp, 'voorlopige_aanslag_betaald', 0) or 0) > 0
        or (getattr(fp, 'voorlopige_aanslag_zvw', 0) or 0) > 0
        or va_data.get('has_bank_data', False)
    )


@ui.page('/')
async def dashboard_page():
    create_layout('Dashboard', '/')

    huidig_jaar = date.today().year
    jaren = year_options(as_dict=True)

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):

        # Header row: title + shortcuts
        with ui.row().classes('w-full items-center'):
            page_title('Overzicht')
            ui.space()
            ui.button('Werkdag', icon='add',
                      on_click=lambda: ui.navigate.to('/werkdagen')) \
                .props('flat color=secondary dense')
            ui.button('Factuur', icon='add',
                      on_click=lambda: ui.navigate.to('/facturen')) \
                .props('flat color=secondary dense')

        # Filter bar
        with ui.element('div').classes('page-toolbar w-full'):
            jaar_select = ui.select(
                jaren, value=huidig_jaar, label='Jaar',
            ).classes('w-28')

        # Content container (filled by refresh_dashboard)
        content_container = {'ref': None}
        content_container['ref'] = ui.column().classes('w-full gap-5')

    def _yoy_delta(current: float, previous: float) -> float | None:
        """Calculate YoY delta percentage. Returns None if no previous data."""
        if previous is not None and previous != 0:
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
                aov=0, lijfrente=0,       # personal -> Aangifte
                woz=0, hypotheekrente=0,  # personal -> Aangifte
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
            log.exception('IB estimate failed for year %s', jaar)
            return None

    def _render_delta_badge(delta_pct: float):
        """Render YoY delta pill badge."""
        color = '#059669' if delta_pct >= 0 else '#DC2626'
        bg = '#ECFDF5' if delta_pct >= 0 else '#FEF2F2'
        arrow = '\u2191' if delta_pct >= 0 else '\u2193'
        sign = '+' if delta_pct > 0 else ''
        ui.label(f'{arrow} {sign}{delta_pct:.0f}%').style(
            f'font-size: 12px; font-weight: 600; color: {color}; '
            f'background: {bg}; padding: 2px 8px; border-radius: 10px')

    def _render_sparkline(monthly_data: list[float], color: str):
        """Render an ECharts mini sparkline inside a KPI card."""
        months = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']
        ui.echart({
            'grid': {'top': 0, 'bottom': 0, 'left': 0, 'right': 0},
            'xAxis': {'show': False, 'type': 'category', 'data': months},
            'yAxis': {'show': False, 'type': 'value', 'min': 0},
            'series': [{
                'type': 'line', 'data': monthly_data, 'smooth': True,
                'symbol': 'none',
                'lineStyle': {'width': 2, 'color': color},
                'areaStyle': {
                    'color': {
                        'type': 'linear', 'x': 0, 'y': 0, 'x2': 0, 'y2': 1,
                        'colorStops': [
                            {'offset': 0, 'color': f'{color}20'},
                            {'offset': 1, 'color': f'{color}00'},
                        ],
                    },
                },
            }],
            'tooltip': {'show': False},
        }).style('height: 36px; width: 100%; margin-top: 14px')

    async def refresh_dashboard():
        jaar = jaar_select.value

        # Run all independent DB calls concurrently
        (kpis, kpis_vorig, omzet_huidig, omzet_vorig, kosten_per_cat,
         openstaande, ongefact, km_data,
         ib_resultaat, fp, va_data, aangifte_docs,
         health_alerts) = await asyncio.gather(
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
            get_va_betalingen(DB_PATH, jaar),
            get_aangifte_documenten(DB_PATH, jaar),
            get_health_alerts(DB_PATH, jaar=jaar),
        )

        uren_criterium = int(fp.urencriterium) if fp else URENCRITERIUM_DEFAULT

        # For YoY delta: compare exact same calendar period
        huidig_jaar = date.today().year
        if jaar == huidig_jaar:
            # Compare up to today's date in previous year (day-precise)
            vandaag_date = date.today()
            try:
                vorig_date = vandaag_date.replace(year=vandaag_date.year - 1)
            except ValueError:  # Feb 29 → Feb 28 in non-leap year
                vorig_date = vandaag_date.replace(
                    year=vandaag_date.year - 1, day=28)
            vorig_datum = vorig_date.isoformat()
            vorig_ytd = await get_kpis_tot_datum(
                DB_PATH, jaar=jaar - 1, max_datum=vorig_datum)
            vorig_ytd_omzet = vorig_ytd['omzet']
            vorig_ytd_kosten = vorig_ytd['kosten']
        else:
            vorig_ytd_omzet = kpis_vorig['omzet']
            vorig_ytd_kosten = kpis_vorig['kosten']

        # Render into content container
        container = content_container['ref']
        container.clear()
        with container:

            with ui.element('div').style(
                    'display: grid; grid-template-columns: repeat(3, 1fr); '
                    'gap: 20px; align-items: stretch'):

                # Card 1: Bruto omzet
                with ui.card().classes('q-pa-lg card-hero') \
                        .style('cursor: pointer') \
                        .on('click', lambda: ui.navigate.to('/werkdagen')):
                    with ui.row().classes('w-full justify-between items-center'):
                        ui.label('Bruto omzet').classes('hero-label')
                        delta = _yoy_delta(kpis['omzet'], vorig_ytd_omzet)
                        if delta is not None:
                            _render_delta_badge(delta)
                    ui.label(format_euro(kpis['omzet'], decimals=0)).classes(
                        'hero-value')
                    if vorig_ytd_omzet > 0:
                        ui.label(
                            f'vs {format_euro(vorig_ytd_omzet, decimals=0)} '
                            f'vorig jaar'
                        ).classes('context-text')
                    # Sparkline
                    if any(v > 0 for v in omzet_huidig):
                        _render_sparkline(omzet_huidig, '#0F766E')

                # Card 2: Bedrijfswinst
                ytd_winst = ib_resultaat['ytd_winst'] if ib_resultaat else (
                    kpis['omzet'] - kpis['kosten'])
                vorig_winst = vorig_ytd_omzet - vorig_ytd_kosten

                with ui.card().classes('q-pa-lg card-hero') \
                        .style('cursor: pointer') \
                        .on('click', lambda: ui.navigate.to('/aangifte')):
                    with ui.row().classes('w-full justify-between items-center'):
                        ui.label('Bedrijfswinst').classes('hero-label')
                        delta = _yoy_delta(ytd_winst, vorig_winst) \
                            if vorig_winst else None
                        if delta is not None:
                            _render_delta_badge(delta)
                    ui.label(format_euro(ytd_winst, decimals=0)).classes(
                        'hero-value-positive' if ytd_winst >= 0
                        else 'hero-value-negative')
                    if vorig_winst and vorig_winst > 0:
                        ui.label(
                            f'vs {format_euro(vorig_winst, decimals=0)} vorig jaar'
                        ).classes('context-text')
                    # Sparkline (revenue as proxy for profit trend)
                    if any(v > 0 for v in omzet_huidig):
                        _render_sparkline(omzet_huidig, '#059669')

                # Card 3: Belasting prognose
                with ui.card().classes('q-pa-lg card-hero') \
                        .style('cursor: pointer') \
                        .on('click', lambda: ui.navigate.to('/aangifte')):

                    if ib_resultaat is not None:
                        has_va = _has_va_data(fp, va_data)
                        resultaat = ib_resultaat['resultaat']
                        confidence = ib_resultaat.get('confidence', 'low')

                        # Header with confidence badge
                        with ui.row().classes(
                                'w-full justify-between items-center'):
                            ui.label('Belasting prognose').classes(
                                'hero-label')
                            conf_map = {
                                'low': ('Schatting', '#D97706', '#FEF3C7'),
                                'medium': ('Prognose', '#0369A1', '#F0F9FF'),
                                'high': ('Betrouwbaar', '#059669', '#ECFDF5'),
                            }
                            c_label, c_color, c_bg = conf_map.get(
                                confidence, conf_map['low'])
                            ui.label(c_label).style(
                                f'font-size: 11px; font-weight: 500; '
                                f'color: {c_color}; background: {c_bg}; '
                                f'padding: 2px 8px; border-radius: 10px')

                        if has_va:
                            # Bij/terug display
                            if resultaat >= 0:
                                val_text = f'Bij: {format_euro(resultaat, decimals=0)}'
                            else:
                                val_text = f'Terug: {format_euro(abs(resultaat), decimals=0)}'
                            ui.label(val_text).classes(
                                'hero-value-negative' if resultaat >= 0
                                else 'hero-value-positive')
                            ui.label(
                                f'o.b.v. {ib_resultaat["basis_maanden"]} '
                                f'maanden'
                            ).classes('context-text').style(
                                    'margin-bottom: 16px')

                            # Progress bar: berekend vs VA betaald
                            berekend = (ib_resultaat['netto_ib']
                                        + ib_resultaat['zvw'])
                            if va_data['has_bank_data']:
                                va_betaald = va_data['totaal_betaald']
                                va_label_text = 'VA betaald'
                            else:
                                va_betaald = (ib_resultaat['va_ib_betaald']
                                              + ib_resultaat['va_zvw_betaald'])
                                va_label_text = 'VA geschat'

                            with ui.row().classes(
                                    'w-full justify-between').style(
                                    'font-size: 11px; color: #64748B; '
                                    'margin-bottom: 8px'):
                                ui.label(
                                    f'Berekend '
                                    f'{format_euro(berekend, decimals=0)}')
                                ui.label(
                                    f'{va_label_text} '
                                    f'{format_euro(va_betaald, decimals=0)}')

                            # Simple HTML progress bar (avoids Quasar rendering quirks)
                            pct = round(va_betaald / berekend * 100) \
                                if berekend > 0 else 0
                            ui.html(
                                f'<div style="height:6px;background:#F1F5F9;'
                                f'border-radius:3px;overflow:hidden;width:100%">'
                                f'<div style="height:100%;width:{min(pct, 100)}%;'
                                f'background:#059669;border-radius:3px">'
                                f'</div></div>'
                            )

                            # Termijn info from real bank data
                            if va_data['has_bank_data']:
                                if (va_data['ib_termijnen'] > 0
                                        or va_data['zvw_termijnen'] > 0):
                                    parts = []
                                    if va_data['ib_termijnen'] > 0:
                                        parts.append(
                                            f'{va_data["ib_termijnen"]} IB')
                                    if va_data['zvw_termijnen'] > 0:
                                        parts.append(
                                            f'{va_data["zvw_termijnen"]} ZVW')
                                    termijn_text = (
                                        ' \u00b7 '.join(parts) + ' termijnen')
                                else:
                                    termijn_text = 'geen termijnen'
                                ui.label(termijn_text).style(
                                    'font-size: 10px; color: #94A3B8; '
                                    'margin-top: 6px; text-align: right')
                        else:
                            # No VA data — show estimated tax total
                            total_tax = (ib_resultaat['netto_ib']
                                         + ib_resultaat['zvw'])
                            ui.label(format_euro(total_tax, decimals=0)).classes(
                                'hero-value')
                            ui.label('Geschatte belasting').classes(
                                'context-text')
                            ui.label('VA invoeren \u2192').style(
                                'font-size: 12px; color: #0F766E; '
                                'cursor: pointer; margin-top: 8px')
                    else:
                        # No fiscal data at all
                        ui.label('Belasting prognose').classes('hero-label')
                        ui.label('Geen gegevens').classes(
                            'context-text').style('margin-top: 8px')

            with ui.row().classes('w-full gap-3'):
                # Uren
                uren = kpis.get('uren', 0)
                with ui.card().classes('flex-1 q-pa-sm').style(
                        'border-radius: 10px; border: 1px solid #E2E8F0; '
                        'display: flex; align-items: center; gap: 10px; '
                        'flex-direction: row; cursor: pointer').on(
                        'click', lambda: ui.navigate.to('/werkdagen')):
                    ui.icon('schedule', size='20px').style('color: #0F766E')
                    with ui.row().classes('items-baseline gap-1'):
                        ui.label(
                            f'{uren:,.0f} / {uren_criterium:,} uur'.replace(',', '.')
                        ).classes('strip-value')
                        uren_pct = uren / uren_criterium * 100 if uren_criterium else 0
                        color = 'text-positive' if uren_pct >= 100 else 'text-grey-6'
                        with ui.element('span').classes(
                                f'text-caption {color}'):
                            ui.label(f'({uren_pct:.0f}% urencriterium)')
                            ui.tooltip(
                                'Exclusief achterwacht (urennorm=0)')

                # Km (only if > 0)
                km = km_data.get('km', 0) if km_data else 0
                km_bedrag = km_data.get('vergoeding', 0) if km_data else 0
                if km > 0:
                    with ui.card().classes('flex-1 q-pa-sm').style(
                            'border-radius: 10px; border: 1px solid #E2E8F0; '
                            'display: flex; align-items: center; gap: 10px; '
                            'flex-direction: row'):
                        ui.icon('directions_car', size='20px').style(
                            'color: #0F766E')
                        with ui.row().classes('items-baseline gap-1'):
                            ui.label(f'{km:,.0f} km'.replace(',', '.')).classes(
                                'strip-value')
                            ui.label(format_euro(km_bedrag)).classes(
                                'context-text')

                # Documenten
                docs = aangifte_docs
                docs_done = len({d.documenttype for d in docs})
                docs_total = len(AANGIFTE_DOCS)
                docs_pct = round(
                    docs_done / docs_total * 100) if docs_total else 0
                with ui.card().classes('flex-1 q-pa-sm').style(
                        'border-radius: 10px; border: 1px solid #E2E8F0; '
                        'display: flex; align-items: center; gap: 10px; '
                        'flex-direction: row'):
                    ui.icon('folder_open', size='20px').style(
                        f'color: {"#059669" if docs_pct >= 100 else "#D97706"}')
                    with ui.column().classes('flex-1 gap-0'):
                        with ui.row().classes(
                                'w-full justify-between items-baseline'):
                            ui.label(
                                f'{docs_done} / {docs_total} documenten'
                            ).classes('strip-value')
                            ui.label(f'{docs_pct}%').classes('strip-pct')
                        ui.linear_progress(
                            value=min(docs_pct / 100, 1.0), size='3px',
                            color='positive' if docs_pct >= 100 else 'warning',
                        ).style('margin-top: 6px')

            maanden = ['Jan', 'Feb', 'Mrt', 'Apr', 'Mei', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dec']
            has_kosten = any(d['totaal'] > 0 for d in kosten_per_cat)

            # Cumulative sums for line chart
            cum_huidig, cum_vorig = [], []
            rh, rv = 0, 0
            for i in range(12):
                rh += omzet_huidig[i]
                rv += omzet_vorig[i]
                cum_huidig.append(round(rh))
                cum_vorig.append(round(rv))

            # Chart 1: Revenue bar chart — FULL WIDTH
            with ui.card().classes('w-full q-pa-lg card-hero'):
                with ui.row().classes(
                        'w-full justify-between items-baseline'):
                    ui.label('Omzet per maand').classes('chart-title')
                    ui.label(f'{jaar} vs {jaar - 1}').classes(
                        'chart-subtitle')
                revenue_bar_chart(omzet_huidig, omzet_vorig, jaar)

            # Chart 2: Cumulative + Donut side by side (or just cumulative)
            cum_chart_config = {
                'tooltip': {'trigger': 'axis'},
                'legend': {
                    'data': [str(jaar), str(jaar - 1)],
                    'right': 0, 'top': 0,
                    'textStyle': {'color': '#94A3B8', 'fontSize': 11},
                    'itemWidth': 16, 'itemHeight': 2},
                'grid': {'left': '3%', 'right': '3%',
                         'bottom': '3%', 'top': 36,
                         'containLabel': True},
                'xAxis': {
                    'type': 'category', 'data': maanden,
                    'axisLabel': {'color': '#94A3B8', 'fontSize': 11},
                    'axisLine': {'show': False},
                    'axisTick': {'show': False},
                    'boundaryGap': False},
                'yAxis': {
                    'type': 'value',
                    'axisLabel': {'formatter': '\u20ac {value}',
                                  'color': '#94A3B8', 'fontSize': 11},
                    'splitLine': {'lineStyle': {'color': '#F1F5F9'}},
                    'axisLine': {'show': False},
                    'axisTick': {'show': False}},
                'series': [
                    {'name': str(jaar), 'type': 'line',
                     'data': cum_huidig, 'smooth': 0.3,
                     'symbol': 'circle', 'symbolSize': 6,
                     'lineStyle': {'width': 3, 'color': '#0F766E'},
                     'itemStyle': {'color': '#0F766E',
                                   'borderWidth': 2,
                                   'borderColor': '#fff'},
                     'areaStyle': {'color': {
                         'type': 'linear', 'x': 0, 'y': 0,
                         'x2': 0, 'y2': 1, 'colorStops': [
                             {'offset': 0,
                              'color': 'rgba(15,118,110,0.15)'},
                             {'offset': 1,
                              'color': 'rgba(15,118,110,0)'}]}}},
                    {'name': str(jaar - 1), 'type': 'line',
                     'data': cum_vorig, 'smooth': 0.3,
                     'symbol': 'none',
                     'lineStyle': {'width': 1.5,
                                   'color': '#CBD5E1',
                                   'type': 'dashed'}},
                ],
            }

            if has_kosten:
                # Side by side: cumulative + donut
                with ui.element('div').style(
                        'display: grid; grid-template-columns: 1fr 1fr;'
                        ' gap: 20px'):
                    with ui.card().classes('q-pa-lg card-hero'):
                        with ui.row().classes(
                                'w-full justify-between items-baseline'):
                            ui.label('Cumulatieve omzet').classes(
                                'chart-title')
                            ui.label(f'{jaar} vs {jaar - 1}').classes(
                                'chart-subtitle')
                        ui.echart(cum_chart_config).style(
                            'height: 300px; width: 100%')

                    with ui.card().classes('q-pa-lg card-hero'):
                        ui.label('Kostenverdeling').classes('chart-title')
                        cost_donut_chart(kosten_per_cat)
            else:
                # No costs — full-width cumulative
                with ui.card().classes('w-full q-pa-lg card-hero'):
                    with ui.row().classes(
                            'w-full justify-between items-baseline'):
                        ui.label('Cumulatieve omzet').classes('chart-title')
                        ui.label(f'{jaar} vs {jaar - 1}').classes(
                            'chart-subtitle')
                    ui.echart(cum_chart_config).style(
                        'height: 300px; width: 100%')

            has_ongefact = ongefact and ongefact.get('aantal', 0) > 0
            has_openstaand = len(openstaande) > 0
            if has_ongefact or has_openstaand:
                ui.label('AANDACHTSPUNTEN').classes('section-label')

                if has_ongefact:
                    with ui.element('div').style(
                            'background: #FFFBEB; border-radius: 10px; '
                            'padding: 14px 18px; '
                            'border: 1px solid #FDE68A; display: flex; '
                            'align-items: center; '
                            'justify-content: space-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('pending_actions', size='20px').style(
                                'color: #D97706')
                            ui.html(
                                f'<span style="font-size:13px;font-weight:600;'
                                f'color:#92400E">'
                                f'{ongefact["aantal"]} werkdagen '
                                f'ongefactureerd</span>'
                                f'<span style="font-size:12px;color:#A16207;'
                                f'margin-left:8px">'
                                f'{format_euro(ongefact["bedrag"])}</span>')
                        ui.button(
                            'Bekijk',
                            on_click=lambda: ui.navigate.to('/werkdagen'),
                        ).props('flat dense size=sm') \
                            .style('border: 1px solid #D97706; '
                                   'border-radius: 6px; '
                                   'color: #D97706; font-size: 12px')

                if has_openstaand:
                    totaal = sum(f.totaal_bedrag for f in openstaande)
                    try:
                        oudste = max(
                            (date.today()
                             - datetime.strptime(f.datum, '%Y-%m-%d').date()
                             ).days
                            for f in openstaande)
                    except (ValueError, TypeError):
                        oudste = 0
                    with ui.element('div').style(
                            'background: #FFF7ED; border-radius: 10px; '
                            'padding: 14px 18px; '
                            'border: 1px solid #FED7AA; display: flex; '
                            'align-items: center; '
                            'justify-content: space-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('receipt_long', size='20px').style(
                                'color: #EA580C')
                            ui.html(
                                f'<span style="font-size:13px;font-weight:600;'
                                f'color:#9A3412">'
                                f'{len(openstaande)} facturen openstaand'
                                f'</span>'
                                f'<span style="font-size:12px;color:#C2410C;'
                                f'margin-left:8px">'
                                f'{format_euro(totaal)} \u00b7 oudste '
                                f'{oudste} dagen</span>')
                        ui.button(
                            'Bekijk',
                            on_click=lambda: ui.navigate.to('/facturen'),
                        ).props('flat dense size=sm') \
                            .style('border: 1px solid #EA580C; '
                                   'border-radius: 6px; '
                                   'color: #EA580C; font-size: 12px')

            # Health alerts — additional signals beyond ongefact/openstaand
            if health_alerts:
                if not (has_ongefact or has_openstaand):
                    # Only show header if AANDACHTSPUNTEN wasn't already rendered
                    ui.label('AANDACHTSPUNTEN').classes('section-label')

                _severity_style = {
                    'critical': (
                        'background: #FEE2E2; border: 1px solid #FCA5A5;',
                        '#B91C1C', '#7F1D1D',
                    ),
                    'warning': (
                        'background: #FEF2F2; border: 1px solid #FECACA;',
                        '#DC2626', '#991B1B',
                    ),
                    'info': (
                        'background: #EFF6FF; border: 1px solid #BFDBFE;',
                        '#2563EB', '#1E40AF',
                    ),
                }
                _icon_for = {
                    'critical': 'error',
                    'warning': 'warning',
                    'info': 'info_outline',
                }
                for alert in health_alerts:
                    bg_style, icon_color, text_color = _severity_style.get(
                        alert['severity'], _severity_style['info'])
                    with ui.element('div').style(
                            f'{bg_style} border-radius: 10px; '
                            f'padding: 14px 18px; display: flex; '
                            f'align-items: center; '
                            f'justify-content: space-between'):
                        with ui.row().classes('items-center gap-2'):
                            icon = _icon_for.get(
                                alert['severity'], 'info_outline')
                            ui.icon(icon, size='20px').style(
                                f'color: {icon_color}')
                            ui.html(
                                f'<span style="font-size:13px;font-weight:600;'
                                f'color:{text_color}">'
                                f'{alert["message"]}</span>')
                        if alert.get('link'):
                            ui.button(
                                'Bekijk',
                                on_click=lambda l=alert['link']: ui.navigate.to(l),
                            ).props('flat dense size=sm') \
                                .style(f'border: 1px solid {icon_color}; '
                                       f'border-radius: 6px; '
                                       f'color: {icon_color}; font-size: 12px')

    jaar_select.on_value_change(lambda _: refresh_dashboard())
    await refresh_dashboard()
