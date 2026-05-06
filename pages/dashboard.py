"""Dashboard pagina — hero KPIs, sparklines, contextual alerts."""

import asyncio
import logging
from datetime import date

log = logging.getLogger(__name__)

from nicegui import ui

from components.charts import cost_donut_chart, revenue_bar_chart
from components.layout import create_layout, page_title
from components.utils import format_euro
from database import (
    get_kpis, get_kpis_tot_datum, get_omzet_per_maand,
    get_omzet_per_maand_tot_datum,
    get_uitgaven_per_categorie, get_openstaande_facturen,
    get_werkdagen_ongefactureerd_summary, get_km_totaal,
    get_fiscale_params, get_aangifte_documenten,
    get_va_betalingen, get_health_alerts, DB_PATH,
    get_factuur_aging_buckets, get_concept_facturen_stale,
    update_factuur_status, get_db_ctx,
    get_omzet_per_klant, get_dashboard_widgets_config,
    get_aov_total,
)
from components.document_specs import AANGIFTE_DOCS
from components.fiscal_utils import fetch_fiscal_data, extrapoleer_jaaromzet
from components.shared_ui import year_options
from fiscal.berekeningen import bereken_volledig
from fiscal.constants import URENCRITERIUM_DEFAULT
from services.agenda import (
    get_urencriterium_projectie, get_zes_weken_prognose,
)
from services.dashboard import (
    compute_sph_prognose,
    compute_va_tracker,
    ActionRow, prioritise_actions, _seasonal_action_rows,
    tax_calendar, load_dashboard_widgets_config,
    should_show_prive_zone,
)
from components.dashboard_widgets import (
    render_action_inbox, render_sph_tile, render_zes_weken_tile,
    render_top_klanten_tile, render_documenten_tile,
    render_cash_positie_tile, render_tax_calendar_tile,
    render_prive_zone, render_va_tile,
)


@ui.page('/')
async def dashboard_page():
    create_layout('Dashboard', '/')

    huidig_jaar = date.today().year
    jaren = year_options(as_dict=True)

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):

        # Header row: title + Quick-actions (Sprint H T2.3 — Acumulus-pattern).
        # Vervangen 2 grijze flat-knoppen door 3 prominente CTAs (unelevated
        # color=primary) zodat ze als echte calls-to-action herkenbaar zijn.
        # + Werkdag → /agenda (Sprint A planning-flow), + Factuur → builder,
        # + Uitgave → /transacties inbox.
        with ui.row().classes('w-full items-center gap-2'):
            # Title shows current calendar year (user knows selected jaar via dropdown)
            page_title(f'Overzicht {huidig_jaar}')
            ui.space()
            ui.button('+ Werkdag',
                      on_click=lambda: ui.navigate.to('/agenda')) \
                .props('unelevated color=primary dense')
            ui.button('+ Factuur',
                      on_click=lambda: ui.navigate.to('/facturen?nieuw=1')) \
                .props('unelevated color=primary dense')
            ui.button('+ Uitgave',
                      on_click=lambda: ui.navigate.to('/transacties')) \
                .props('unelevated color=primary dense')

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
                # T2.2: voor Jaareinde-projectie hero — al berekend via
                # projection['extrapolated_omzet'], hier exposed zodat
                # Card 2 geen extra extrapoleer_jaaromzet-call hoeft te doen.
                'extrapolated_omzet': projection['extrapolated_omzet'],
            }
        except Exception:
            log.exception('IB estimate failed for year %s', jaar)
            return None

    def _render_delta_badge(delta_pct: float):
        """Render YoY delta pill badge."""
        color = 'var(--q-positive)' if delta_pct >= 0 else 'var(--q-negative)'
        bg = ('var(--bg-success-soft)' if delta_pct >= 0
              else 'var(--bg-negative-soft)')
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
        # NOTE (T2.3): km_data + aangifte_docs blijven in gather() — Uren
        # wordt nu hero Card 4 (via urencrit_state), maar Km en Documenten
        # verhuizen pas in T4b naar inzicht-grid. Niet alvast verwijderen.
        (kpis, kpis_vorig, omzet_huidig, omzet_vorig, kosten_per_cat,
         openstaande, ongefact, km_data,
         ib_resultaat, fp, va_data, aangifte_docs,
         health_alerts, urencrit_state, zes_weken,
         omzet_per_klant, aov_data) = await asyncio.gather(
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
            get_urencriterium_projectie(DB_PATH, jaar),
            get_zes_weken_prognose(DB_PATH, vanaf=date.today()),
            get_omzet_per_klant(DB_PATH, jaar=jaar),
            get_aov_total(DB_PATH, jaar=jaar),
        )

        # === T4b.1: SPH-prognose data (render wired in T4b.4) ===
        # Eerst SPH betaald YTD voor het geselecteerde jaar via inline
        # query (niet de moeite waard om een generieke helper voor te
        # bouwen — categorie-string is hardcoded contract).
        async with get_db_ctx(DB_PATH) as conn:
            cur = await conn.execute(
                """SELECT COALESCE(SUM(bedrag), 0) AS sph_total
                   FROM uitgaven
                   WHERE categorie = 'Pensioenpremie SPH'
                     AND CAST(strftime('%Y', datum) AS INTEGER) = ?""",
                (jaar,),
            )
            sph_row = await cur.fetchone()
        sph_betaald_ytd = sph_row['sph_total'] if sph_row else 0.0

        # Winst-projectie voor SPH: zelfde extrapolatie-logica als de
        # Jaareinde-projectie hero-tile (Card 2). Reverse-engineer
        # total_kosten_ytd uit (omzet - ytd_winst) + extrapoleer naar 12mo
        # zodat SPH-grondslag consistent blijft met getoond projectie-getal.
        if ib_resultaat is not None:
            omzet_ytd = kpis['omzet']
            total_kosten_ytd = max(
                0.0, omzet_ytd - ib_resultaat['ytd_winst'])
            basis_m = ib_resultaat.get('basis_maanden', 12) or 1
            kosten_factor = 12 / basis_m
            winst_proj = (ib_resultaat['extrapolated_omzet']
                          - (total_kosten_ytd * kosten_factor))
        else:
            winst_proj = 0.0
        sph_prognose = compute_sph_prognose(winst_proj, jaar)

        # === T4b.3: Cash-positie data (render wired in T4b.4) ===
        # Empty-state per spec § E R1: idealiter `IS NULL` per jaar, maar
        # `_row_to_fiscale_params` coerced NULL → 0 via `or 0`. Pragmatisch:
        # 0 → None mapping hier — de tile toont dan de "vul in /instellingen"
        # CTA. Een legitiem €0-saldo gaat verloren maar dat is een edge-case
        # (huisarts-praktijk heeft altijd >0 saldo); user kan altijd handmatig
        # via /instellingen iets > 0 invullen om de tile te activeren.
        if fp is not None:
            raw_opening = fp.balans_bank_saldo
            opening_saldo = raw_opening if raw_opening else None
        else:
            opening_saldo = None

        # flow_ytd = SUM van alle banktransacties.bedrag voor het jaar
        # (signed: positives = inkomsten, negatives = uitgaven). Inline
        # query — single-purpose, geen helper waard.
        async with get_db_ctx(DB_PATH) as conn:
            cur = await conn.execute(
                """SELECT COALESCE(SUM(bedrag), 0) AS flow_total
                   FROM banktransacties
                   WHERE CAST(strftime('%Y', datum) AS INTEGER) = ?""",
                (jaar,),
            )
            flow_row = await cur.fetchone()
        flow_ytd = flow_row['flow_total'] if flow_row else 0.0

        # === T4b.3: Tax-calendar data ===
        tax_deadlines = tax_calendar(jaar)

        # T4b.4: render-calls (render_sph_tile, render_zes_weken_tile,
        # render_top_klanten_tile, render_documenten_tile,
        # render_cash_positie_tile, render_tax_calendar_tile) worden
        # verderop in de inzicht-grid wired via config-check.

        # T4b.4: Load dashboard widgets config (defaults if NULL)
        raw_widget_config = await get_dashboard_widgets_config(DB_PATH)
        widgets_config = load_dashboard_widgets_config(raw_widget_config)

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

        # === Build action-inbox rows from existing data sources (Sprint H T3.4) ===
        # Geconsolideerde work-inbox per Acumulus-pattern: 5 bronnen +
        # seasonal-rows samen, dan prioritise_actions truncate naar 5.
        raw_rows: list[ActionRow] = []

        # From health_alerts. Filter expliciet: overdue_invoices en
        # concept_invoices worden hieronder al via aging_buckets resp.
        # get_concept_facturen_stale toegevoegd → zonder filter zou de
        # user dubbele rijen zien en max-5 prioritisering verkeerd
        # bumpen (Codex T3.4 catch).
        _DUPLICATE_HEALTH_KEYS = {'overdue_invoices', 'concept_invoices'}
        for alert in health_alerts:
            if alert.get('key') in _DUPLICATE_HEALTH_KEYS:
                continue
            action_kind = None
            if alert.get('key') == 'uncategorized_bank':
                action_kind = 'categoriseer'
            raw_rows.append(ActionRow(
                kind=alert.get('key', 'health_alert'),
                severity=alert.get('severity', 'info'),
                message=alert.get('message', ''),
                action_kind=action_kind,
                link=alert.get('link'),
                age_days=0,
                metadata={},
            ))

        # From ongefactureerd-summary. `oudste_dagen` zit niet in summary
        # — fallback 0 (prioriteit-tiebreak werkt nog via severity).
        if ongefact and ongefact.get('aantal', 0) > 0:
            raw_rows.append(ActionRow(
                kind='werkdag_ongefactureerd',
                severity='warning',
                message=(
                    f'{ongefact["aantal"]} werkdagen ongefactureerd · '
                    f'{format_euro(ongefact["bedrag"])}'),
                action_kind=None,  # T6.1 voegt 'genereer_factuur' toe
                link='/werkdagen',
                age_days=ongefact.get('oudste_dagen', 0),
                metadata={},
            ))

        # From openstaande facturen aging — één rij per niet-lege bucket.
        # 90+ dagen = critical (cash-flow harm), rest = warning.
        aging_buckets = await get_factuur_aging_buckets(DB_PATH, jaar=jaar)
        for bucket_key, facturen_list in aging_buckets.items():
            if not facturen_list:
                continue
            severity = 'critical' if bucket_key == 'overdue_90_plus' else 'warning'
            raw_rows.append(ActionRow(
                kind='verlopen_factuur',
                severity=severity,
                message=(
                    f'{len(facturen_list)} facturen verlopen '
                    f'({bucket_key.replace("overdue_", "")} dagen)'),
                action_kind='stuur_herinnering',
                link='/facturen',
                age_days=int(facturen_list[0].get('days_overdue', 0)),
                metadata={'factuur_id': facturen_list[0]['id']},
            ))

        # From concept-facturen stale (>14 dagen oud).
        concepts = await get_concept_facturen_stale(DB_PATH, jaar=jaar, days=14)
        if concepts:
            raw_rows.append(ActionRow(
                kind='concept_factuur_stale',
                severity='info',
                message=f'{len(concepts)} concept-facturen >14 dagen oud',
                action_kind='verstuur_concept',
                link='/facturen?status=concept',
                age_days=14,
                metadata={'factuur_id': concepts[0]['id']},
            ))

        # From documenten ontbreken (max 3 rows — anders overstemt
        # documenten-lijst de hele inbox bij start van het jaar).
        docs_done = {d.documenttype for d in aangifte_docs}
        docs_missing = [d for d in AANGIFTE_DOCS if d not in docs_done]
        for missing in docs_missing[:3]:
            raw_rows.append(ActionRow(
                kind='documenten_ontbreken',
                severity='info',
                message=f'Aangifte-doc "{missing}" mist',
                action_kind='upload_nu',
                link='/aangifte',
                age_days=0,
                metadata={'documenttype': missing},
            ))

        # Add seasonal rows (T3.2 helper — IB-aangifte/VA-deadlines).
        raw_rows.extend(_seasonal_action_rows(date.today()))

        # Prioritise + truncate naar max 5 (cognitive-load cap).
        action_rows = prioritise_actions(raw_rows, max_items=5)

        # === Action dispatcher ===
        async def on_action(row: ActionRow, action_kind: str):
            """Dispatch inline-action handlers per action_kind.

            stuur_herinnering / verstuur_concept tonen confirm-dialog
            voor mutation-actions (Spec U3 — geen surprise sends).
            categoriseer / upload_nu zijn pure navigatie.
            """
            if action_kind == 'stuur_herinnering':
                # Per spec U3: confirm-dialog before opening Mail.app.
                # Defer naar /facturen page; T6.1 kan inline
                # _build_herinnering_body extracten naar shared helper
                # voor true inline-send zonder navigation.
                with ui.dialog() as dlg, ui.card():
                    ui.label('Herinnering versturen?').classes('text-h6')
                    ui.label(row.message).classes('text-body2 text-grey')
                    ui.label(
                        'Mail.app opent met conceptbericht; jij verstuurt.'
                    ).classes('text-caption text-grey')
                    with ui.row():
                        ui.button('Annuleren', on_click=dlg.close).props('flat')

                        def _confirm():
                            dlg.close()
                            factuur_id = row.metadata.get('factuur_id')
                            if factuur_id:
                                ui.navigate.to(f'/facturen?factuur={factuur_id}')

                        ui.button(
                            'Stuur herinnering', on_click=_confirm
                        ).props('unelevated color=primary')
                dlg.open()

            elif action_kind == 'categoriseer':
                ui.navigate.to('/transacties?status=ongecategoriseerd')

            elif action_kind == 'upload_nu':
                cat = row.metadata.get('documenttype', '')
                if cat:
                    ui.navigate.to(f'/aangifte?documenttype={cat}')
                else:
                    ui.navigate.to('/aangifte')

            elif action_kind == 'verstuur_concept':
                factuur_id = row.metadata.get('factuur_id')
                if not factuur_id:
                    ui.notify('Geen factuur-id', type='warning')
                    return
                with ui.dialog() as dlg, ui.card():
                    ui.label('Concept-factuur versturen?').classes('text-h6')
                    ui.label(row.message).classes('text-body2 text-grey')
                    with ui.row():
                        ui.button('Annuleren', on_click=dlg.close).props('flat')

                        async def _confirm():
                            dlg.close()
                            await update_factuur_status(
                                DB_PATH, factuur_id=factuur_id,
                                status='verstuurd')
                            ui.notify(
                                'Status bijgewerkt naar verstuurd',
                                type='positive')
                            await refresh_dashboard()

                        ui.button(
                            'Verstuur', on_click=_confirm
                        ).props('unelevated color=primary')
                dlg.open()

        # Render into content container
        container = content_container['ref']
        container.clear()
        with container:

            # Sprint H T2.3: 3-col → 4-col hero-grid (Card 4 = Urencriterium).
            # Strip-row (Uren/Km/Documenten) is verwijderd; Uren wordt hero,
            # Km/Documenten verhuizen naar inzicht-grid in T4b.
            with ui.element('div').style(
                    'display: grid; grid-template-columns: repeat(4, 1fr); '
                    'gap: 20px; align-items: stretch'):

                # Card 1: Bruto omzet
                with ui.card().classes('dashboard-hero-tile') \
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

                # Card 2: Jaareinde-projectie (Sprint H T2.2 — replaces
                # Winst-YTD as separate hero). Per spec U1: 1 number =
                # winst-projectie. Winst-YTD wordt sub-line eronder als
                # rear-view anchor; YoY-delta verdwijnt — confidence-badge
                # is het primaire trust-signaal voor een forward-looking
                # tile. Hero is nu coherente forward-looking strip:
                # Omzet (rear) / Winst-projectie (forward) / Belasting
                # (forward) / Urencriterium (T2.3 forward).
                ytd_winst = ib_resultaat['ytd_winst'] if ib_resultaat else (
                    kpis['omzet'] - kpis['kosten'])

                if ib_resultaat is not None:
                    from services.dashboard import (
                        compute_jaareinde_projectie_display)
                    # Codex T2.2-review fix: kpis['kosten'] excludeert
                    # afschrijvingen, maar ytd_winst (sub-line) includeert
                    # ze. Hero-projectie zou dan winst over-rapporteren
                    # vs sub-line. Reverse-engineer total_kosten_ytd uit
                    # bestaande data: omzet_ytd - ytd_winst geeft kosten +
                    # afschrijvingen samen — semantisch consistent met
                    # de YTD-winst sub-line. Geen nieuwe fields exposen.
                    omzet_ytd = kpis['omzet']
                    total_kosten_ytd = max(
                        0.0, omzet_ytd - ib_resultaat['ytd_winst'])
                    projection_display = compute_jaareinde_projectie_display(
                        extrapolated_omzet=ib_resultaat['extrapolated_omzet'],
                        kosten_ytd=total_kosten_ytd,
                        confidence=ib_resultaat['confidence'],
                        basis_maanden=ib_resultaat['basis_maanden'],
                    )

                    # Confidence badge — same labels as Belasting-prognose
                    # tile voor consistente trust-signaling.
                    confidence_label_map = {
                        'low': ('Schatting', 'var(--q-warning)'),
                        'medium': ('Prognose', '#0369A1'),
                        'high': ('Betrouwbaar', 'var(--q-positive)'),
                    }
                    conf_label, conf_color = confidence_label_map.get(
                        projection_display['confidence'],
                        ('Schatting', 'var(--q-warning)'))

                    with ui.card().classes('dashboard-hero-tile') \
                            .style('cursor: pointer') \
                            .on('click', lambda: ui.navigate.to('/aangifte')):
                        with ui.row().classes(
                                'w-full justify-between items-center'):
                            ui.label('Jaareinde-projectie').classes(
                                'hero-label')
                            ui.label(conf_label).style(
                                f'font-size: 11px; font-weight: 500; '
                                f'color: {conf_color}; '
                                f'background: var(--surface); '
                                f'padding: 2px 8px; border-radius: 10px; '
                                f'border: 1px solid {conf_color}')
                        # Hero value: winst-projectie (1 number per U1).
                        # Inline color-by-sign — winst-projectie kan
                        # negatief zijn bij verlies-jaar of zware kosten
                        # in Q1; defensief net als Card 3 belasting-tile.
                        winst_proj = projection_display['winst_projectie']
                        winst_color = ('var(--q-positive)' if winst_proj >= 0
                                       else 'var(--q-negative)')
                        ui.label(
                            format_euro(winst_proj, decimals=0)
                        ).classes('hero-value').style(
                            f'color: {winst_color}')
                        # Sub-line: Winst YTD (rear-view anchor).
                        ui.label(
                            f'YTD: {format_euro(ytd_winst, decimals=0)}'
                        ).classes('context-text')
                else:
                    # Fallback: geen ib_resultaat (lege fiscale_params) →
                    # toon alleen YTD zonder projectie. Clickable naar
                    # /aangifte zodat user fiscale_params kan invullen.
                    with ui.card().classes('dashboard-hero-tile') \
                            .style('cursor: pointer') \
                            .on('click', lambda: ui.navigate.to('/aangifte')):
                        ui.label('Jaareinde-projectie').classes('hero-label')
                        ui.label('Geen gegevens').classes(
                            'context-text').style('margin-top: 8px')
                        ui.label(
                            f'YTD-winst: {format_euro(ytd_winst, decimals=0)}'
                        ).classes('context-text')

                # Card 3: Voorlopige aanslag (Sprint I — vervangt Sprint H
                # Belasting-reservering). compute_va_tracker geeft een
                # line-first VATrackSummary met IB + ZVW progress, op basis
                # van de jaarbedragen (fp.voorlopige_aanslag_betaald/_zvw)
                # en de bank-gematchte termijnen (va_data uit
                # get_va_betalingen). Geen extrapolatie meer — alleen
                # audit-trail-traceerbare data.
                va_summary = compute_va_tracker(
                    jaar=jaar,
                    va_data=va_data,
                    ib_verplicht=(fp.voorlopige_aanslag_betaald
                                  if fp else 0) or 0,
                    zvw_verplicht=(fp.voorlopige_aanslag_zvw
                                   if fp else 0) or 0,
                    ib_termijnen=(getattr(
                        fp, 'voorlopige_aanslag_ib_termijnen', 11)
                        if fp else 11) or 11,
                    zvw_termijnen=(getattr(
                        fp, 'voorlopige_aanslag_zvw_termijnen', 11)
                        if fp else 11) or 11,
                    today=date.today(),
                )
                render_va_tile(va_summary, jaar=jaar)

                # Card 4: Urencriterium-projectie (Sprint H T2.3 — was strip-card,
                # nu hero). Toont "huidig / target" met "bij dit tempo: prognose
                # eind van jaar". Pace-color signaleert: groen op tempo (≥105%
                # target), amber krap (≥target), rood niet op tempo.
                # Sprint A's UrencriteriumState velden: confirmed_uren (YTD +
                # ingeplande future, urennorm=1), expected_uren_remainder
                # (patterns vanaf morgen tot jaareinde, exclude ZERO_UREN/
                # ACHTERWACHT), target (1225 default of fp.urencriterium).
                # Prognose = confirmed + expected_remainder (= will_make basis).
                huidig_uren = urencrit_state.confirmed_uren
                target_uren = urencrit_state.target
                prognose_uren = (urencrit_state.confirmed_uren
                                 + urencrit_state.expected_uren_remainder)

                if target_uren > 0 and prognose_uren >= target_uren * 1.05:
                    pace_color = 'var(--q-positive)'
                    pace_label = '✓ Op tempo'
                elif target_uren > 0 and prognose_uren >= target_uren:
                    pace_color = '#D97706'  # amber
                    pace_label = '⚠ Krap'
                else:
                    pace_color = 'var(--q-negative)'
                    pace_label = '✕ Niet op tempo'

                with ui.card().classes('dashboard-hero-tile') \
                        .style('cursor: pointer') \
                        .on('click', lambda: ui.navigate.to('/agenda')):
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Urencriterium').classes('hero-label')
                        ui.label(pace_label).style(
                            f'font-size: 11px; font-weight: 600; '
                            f'color: {pace_color}')
                    ui.label(
                        f'{huidig_uren:,.0f} / {target_uren:,.0f}'.replace(',', '.')
                    ).classes('hero-value')
                    ui.label(
                        f'Bij dit tempo: {prognose_uren:,.0f} eind van jaar'
                        .replace(',', '.')
                    ).classes('context-text')
                    ui.tooltip(
                        'Exclusief achterwacht (urennorm=0). '
                        'Toekomstig ingeplande werkdagen tellen mee.')

            maanden = ['Jan', 'Feb', 'Mrt', 'Apr', 'Mei', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dec']
            has_kosten = any(d['totaal'] > 0 for d in kosten_per_cat)

            # Cumulative sums for line chart
            # B13: voor day-precise consistency met YoY badge — bij huidig
            # jaar capen we vorig jaar omzet op de cutoff-datum (vandaag-
            # min-1-jaar). Volle jaar zou anders een dec-piek tonen die
            # de '+X% vs vorig jaar'-badge tegenspreekt.
            if jaar == huidig_jaar:
                # vorig_datum is reeds berekend rond regel 234 (day-precise)
                omzet_vorig_capped = await get_omzet_per_maand_tot_datum(
                    DB_PATH, jaar=jaar - 1, max_datum=vorig_datum)
            else:
                # Niet huidig jaar — beide jaren volledig is OK
                omzet_vorig_capped = omzet_vorig

            cum_huidig, cum_vorig = [], []
            rh, rv = 0, 0
            for i in range(12):
                rh += omzet_huidig[i]
                rv += omzet_vorig_capped[i]
                cum_huidig.append(round(rh))
                cum_vorig.append(round(rv))

            # Cumulatieve-omzet chart config (used by I-1 tile in
            # inzicht-grid below; defined once here zodat we hem niet in
            # de render-loop opnieuw bouwen)
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

            # Action-inbox vervangt huidige losse alert-cards (Sprint H T3.4)
            render_action_inbox(action_rows, on_action)

            # === Inzicht-grid (config-driven render, Sprint H T4b.4) ===
            # Render in fixed visual order regardless of toggle order. The
            # order matches DEFAULT_WIDGETS dict which is dict-insertion-
            # ordered (Python 3.7+). Empty-state handling leeft binnen elke
            # renderer zelf (Cash heeft expliciete "geen openingssaldo"
            # branch; overige tonen lege-lijst-tekst).
            tile_flags = widgets_config['widgets']

            with ui.element('div').style(
                    'display: grid; grid-template-columns: 1fr 1fr; '
                    'gap: 20px; align-items: start'):

                if tile_flags.get('I-1', False):
                    # Cumulatieve omzet YoY chart
                    with ui.card().classes('q-pa-lg'):
                        with ui.row().classes(
                                'w-full justify-between items-baseline'):
                            ui.label('Cumulatieve omzet').classes(
                                'chart-title')
                            ui.label(f'{jaar} vs {jaar - 1}').classes(
                                'chart-subtitle')
                        ui.echart(cum_chart_config).style(
                            'height: 300px; width: 100%')

                if tile_flags.get('I-2', False) and has_kosten:
                    with ui.card().classes('q-pa-lg'):
                        ui.label('Kostenverdeling').classes('chart-title')
                        cost_donut_chart(kosten_per_cat)

                if tile_flags.get('I-3', False):
                    render_sph_tile(sph_betaald_ytd, sph_prognose)

                if tile_flags.get('I-4', False):
                    render_zes_weken_tile(zes_weken)

                if tile_flags.get('I-5', False):
                    render_top_klanten_tile(omzet_per_klant)

                if tile_flags.get('I-6', False):
                    render_documenten_tile(aangifte_docs, AANGIFTE_DOCS)

                if tile_flags.get('I-7', False):
                    render_cash_positie_tile(opening_saldo, flow_ytd)

                if tile_flags.get('I-8', False):
                    render_tax_calendar_tile(tax_deadlines)

            # Revenue bar chart — altijd zichtbaar (page-anchor, niet
            # toggleable per spec; complement aan YoY badge in hero).
            with ui.card().classes('w-full q-pa-lg'):
                with ui.row().classes(
                        'w-full justify-between items-baseline'):
                    ui.label('Omzet per maand').classes('chart-title')
                    ui.label(f'{jaar} vs {jaar - 1}').classes(
                        'chart-subtitle')
                revenue_bar_chart(omzet_huidig, omzet_vorig, jaar)

            # Customisation footer-link (Spec U2: ⚙ Tegels aanpassen)
            with ui.row().classes('w-full justify-end').style(
                    'margin-top: 8px'):
                ui.button(
                    '⚙ Tegels aanpassen',
                    on_click=lambda: ui.navigate.to(
                        '/instellingen?tab=dashboard'),
                ).props('flat dense color=primary size=sm')

            # === T5.1: Privé-zone (AOV only, conditional auto-collapse) ===
            # Render-gate combineert auto-detect (AOV-tx aanwezig?) met
            # user-override uit dashboard_widgets_json. Geen render = clean
            # dashboard voor users zonder AOV-flagging.
            should_render, is_collapsed = should_show_prive_zone(
                aov_data['count'],
                widgets_config.get('prive_section_collapsed'),
            )
            if should_render:
                render_prive_zone(aov_data['total'], is_collapsed)

    jaar_select.on_value_change(lambda _: refresh_dashboard())
    await refresh_dashboard()
