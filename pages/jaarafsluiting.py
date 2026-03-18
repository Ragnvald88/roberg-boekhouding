"""Jaarafsluiting pagina — pure business annual report (Balans + W&V + Toelichting)."""

import asyncio
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from nicegui import ui

from components.fiscal_utils import bereken_balans, fetch_fiscal_data
from components.kpi_card import kpi_strip
from components.layout import create_layout
from components.utils import format_euro
from database import (
    auto_match_betaald_datum,
    update_balans_inputs,
    update_jaarafsluiting_status,
    get_bedrijfsgegevens,
    get_fiscale_params,
    get_aangifte_documenten,
    get_db_ctx,
    DB_PATH,
)


# === Shared helpers ===


def _balans_line(label: str, value: float, bold: bool = False, indent: bool = False):
    """Render a balance sheet line."""
    css = 'text-bold' if bold else ''
    ml = 'q-ml-md' if indent else ''
    with ui.row().classes(f'w-full justify-between {ml}'):
        ui.label(label).classes(css)
        ui.label(format_euro(value)).classes(f'{css} text-right') \
            .style('min-width: 120px; font-variant-numeric: tabular-nums')


# === Data loading ===

async def _load_year_data(jaar: int):
    """Load all business data for a year. Returns (data, balans, winst, vorig_jaar_balans) or None."""
    # Auto-match betaald_datum from bank transactions for accurate year-end receivables
    await auto_match_betaald_datum(DB_PATH)
    data = await fetch_fiscal_data(DB_PATH, jaar)
    if data is None:
        return None

    # Calculate winst (business profit)
    winst = data['omzet'] - data['kosten_excl_inv'] - data['totaal_afschrijvingen']

    # Calculate prior year balans for comparison
    vorig_jaar_data = await fetch_fiscal_data(DB_PATH, jaar - 1)
    vorig_jaar_balans = None
    begin_vermogen = 0.0
    if vorig_jaar_data:
        vj_winst = (vorig_jaar_data['omzet']
                     - vorig_jaar_data['kosten_excl_inv']
                     - vorig_jaar_data['totaal_afschrijvingen'])
        # For prior year's begin_vermogen, try year before that
        vvj_data = await fetch_fiscal_data(DB_PATH, jaar - 2)
        vj_begin = 0.0
        if vvj_data:
            vvj_winst = (vvj_data['omzet']
                         - vvj_data['kosten_excl_inv']
                         - vvj_data['totaal_afschrijvingen'])
            vvj_balans = await bereken_balans(
                DB_PATH, jaar - 2, vvj_data['activastaat'], winst=vvj_winst)
            vj_begin = vvj_balans['eigen_vermogen']
        vorig_jaar_balans = await bereken_balans(
            DB_PATH, jaar - 1, vorig_jaar_data['activastaat'],
            winst=vj_winst, begin_vermogen=vj_begin)
        begin_vermogen = vorig_jaar_balans['eigen_vermogen']

    balans = await bereken_balans(
        DB_PATH, jaar, data['activastaat'],
        winst=winst, begin_vermogen=begin_vermogen)

    vj_w = vj_winst if vorig_jaar_data else None
    return data, balans, winst, vorig_jaar_balans, vorig_jaar_data, vj_w


# === Page ===

@ui.page('/jaarafsluiting')
async def jaarafsluiting_page():
    create_layout('Jaarafsluiting', active_page='/jaarafsluiting')

    vorig_jaar = date.today().year - 1
    state = {'jaar': vorig_jaar, 'editing': False}

    # --- Containers ---
    with ui.column().classes('w-full max-w-6xl mx-auto q-pa-md gap-4'):
        # Top bar: year selector + status badge + actions
        with ui.row().classes('w-full items-center gap-3'):
            jaar_select = ui.select(
                options=list(range(2023, date.today().year + 1)),
                value=vorig_jaar,
                label='Boekjaar',
            ).classes('w-32')

            status_badge = ui.badge('Concept', color='warning').classes('text-sm q-ml-sm')

            ui.space()

            edit_btn = ui.button('Bewerken', icon='edit',
                                 on_click=lambda: toggle_edit()) \
                .props('outline').classes('q-mr-sm')
            status_btn = ui.button('Markeer als definitief', icon='check_circle',
                                   on_click=lambda: set_definitief())

        # KPI strip placeholder
        kpi_container = ui.row().classes('w-full')

        # Tabs
        with ui.tabs().classes('w-full') as tabs:
            tab_balans = ui.tab('Balans', icon='balance')
            tab_wv = ui.tab('W&V', icon='receipt')
            tab_toelichting = ui.tab('Toelichting', icon='description')
            tab_controles = ui.tab('Controles', icon='verified')
            tab_document = ui.tab('Document', icon='picture_as_pdf')

        with ui.tab_panels(tabs, value=tab_balans).classes('w-full'):
            balans_panel = ui.tab_panel(tab_balans)
            wv_panel = ui.tab_panel(tab_wv)
            toelichting_panel = ui.tab_panel(tab_toelichting)
            controles_panel = ui.tab_panel(tab_controles)
            document_panel = ui.tab_panel(tab_document)

    # --- Render functions ---

    async def render_all():
        """Load data and render all tabs."""
        jaar = state['jaar']
        result = await _load_year_data(jaar)

        # Update status badge
        params = await get_fiscale_params(DB_PATH, jaar)
        status = getattr(params, 'jaarafsluiting_status', 'concept') or 'concept'
        is_definitief = status == 'definitief'
        status_badge.set_text('Definitief' if is_definitief else 'Concept')
        status_badge._props['color'] = 'positive' if is_definitief else 'warning'
        status_badge.update()

        # Update button states
        edit_btn.set_visibility(not is_definitief)
        if is_definitief:
            status_btn.set_text('Heropenen')
            status_btn._props['icon'] = 'lock_open'
            status_btn._props['color'] = 'warning'
        else:
            status_btn.set_text('Markeer als definitief')
            status_btn._props['icon'] = 'check_circle'
            status_btn._props['color'] = 'primary'
        status_btn.update()

        if result is None:
            for panel in [balans_panel, wv_panel, toelichting_panel,
                          controles_panel, document_panel]:
                panel.clear()
                with panel:
                    ui.label(f'Geen fiscale parameters voor {jaar}.') \
                        .classes('text-subtitle1 text-grey-6')
            kpi_container.clear()
            return

        data, balans, winst, vorig_jaar_balans, vorig_jaar_data, vorig_winst = result

        # KPI strip
        kpi_container.clear()
        with kpi_container:
            kpi_strip(
                omzet=data['omzet'],
                winst=winst,
                eigen_vermogen=balans['eigen_vermogen'],
                balanstotaal=balans['totaal_activa'],
            )

        render_balans(data, balans, vorig_jaar_balans)
        render_wv(data, winst, vorig_jaar_data, vorig_winst)
        render_toelichting(data)
        await render_controles(data, balans, winst)
        await render_document(data, balans, winst, vorig_jaar_balans)

    def render_balans(data, balans, vorig_jaar_balans):
        """Render Balans tab."""
        balans_panel.clear()
        vj = vorig_jaar_balans
        editing = state['editing']
        jaar = state['jaar']

        with balans_panel:
            with ui.row().classes('w-full gap-6'):
                # === Activa ===
                with ui.column().classes('flex-1'):
                    ui.label('Activa').classes('text-h6 text-primary')

                    ui.label('Vaste activa').classes('text-caption text-grey-6 q-mt-md')
                    _balans_line('Materiële vaste activa', balans['mva'])

                    ui.label('Vlottende activa').classes('text-caption text-grey-6 q-mt-md')
                    _balans_line('Debiteuren', balans['debiteuren'])
                    _balans_line('Nog te factureren', balans['nog_te_factureren'])

                    if editing:
                        ov_input = ui.number(label='Overige vorderingen',
                                             value=balans['overige_vorderingen'],
                                             format='%.2f').classes('w-48')
                    else:
                        _balans_line('Overige vorderingen', balans['overige_vorderingen'])

                    ui.label('Liquide middelen').classes('text-caption text-grey-6 q-mt-md')
                    if editing:
                        bank_input = ui.number(label='Bank saldo',
                                               value=balans['bank_saldo'],
                                               format='%.2f').classes('w-48')
                    else:
                        _balans_line('Bank', balans['bank_saldo'])

                    ui.separator().classes('q-my-sm')
                    _balans_line('Totaal activa', balans['totaal_activa'], bold=True)

                # === Passiva ===
                with ui.column().classes('flex-1'):
                    ui.label('Passiva').classes('text-h6 text-primary')

                    ui.label('Eigen vermogen').classes('text-caption text-grey-6 q-mt-md')
                    _balans_line('Ondernemingsvermogen', balans['eigen_vermogen'])

                    ui.label('Kortlopende schulden').classes('text-caption text-grey-6 q-mt-md')
                    if editing:
                        cred_input = ui.number(label='Crediteuren',
                                               value=balans['crediteuren'],
                                               format='%.2f').classes('w-48')
                        os_input = ui.number(label='Overige schulden',
                                             value=balans['overige_schulden'],
                                             format='%.2f').classes('w-48')
                    else:
                        _balans_line('Crediteuren', balans['crediteuren'])
                        _balans_line('Overige schulden', balans['overige_schulden'])

                    ui.separator().classes('q-my-sm')
                    _balans_line('Totaal passiva',
                                 balans['eigen_vermogen'] + balans['totaal_schulden'],
                                 bold=True)

            # Kapitaalsvergelijking
            ui.separator().classes('q-my-md')
            ui.label('Kapitaalsvergelijking').classes('text-subtitle1 text-primary')
            with ui.column().classes('w-full max-w-md'):
                _balans_line('Begin vermogen', balans['begin_vermogen'])
                _balans_line('+ Winst', balans['winst'])
                _balans_line('- Privé onttrekkingen', balans['prive_onttrekkingen'])
                ui.separator().classes('q-my-xs')
                _balans_line('Eind vermogen', balans['eigen_vermogen'], bold=True)

            # Prior year comparison
            if vj:
                ui.separator().classes('q-my-md')
                ui.label(f'Vergelijking {jaar - 1}').classes(
                    'text-caption text-grey-6')
                columns = [
                    {'name': 'post', 'label': 'Post', 'field': 'post', 'align': 'left'},
                    {'name': 'huidig', 'label': str(jaar), 'field': 'huidig', 'align': 'right'},
                    {'name': 'vorig', 'label': str(jaar - 1), 'field': 'vorig', 'align': 'right'},
                ]
                rows = [
                    {'post': 'Totaal activa', 'huidig': format_euro(balans['totaal_activa']),
                     'vorig': format_euro(vj['totaal_activa'])},
                    {'post': 'Eigen vermogen', 'huidig': format_euro(balans['eigen_vermogen']),
                     'vorig': format_euro(vj['eigen_vermogen'])},
                    {'post': 'Totaal schulden', 'huidig': format_euro(balans['totaal_schulden']),
                     'vorig': format_euro(vj['totaal_schulden'])},
                ]
                ui.table(columns=columns, rows=rows).classes('w-full max-w-lg')

            # Save button in edit mode
            if editing:
                async def save_balans():
                    await update_balans_inputs(
                        DB_PATH, jaar=jaar,
                        balans_bank_saldo=bank_input.value or 0,
                        balans_crediteuren=cred_input.value or 0,
                        balans_overige_vorderingen=ov_input.value or 0,
                        balans_overige_schulden=os_input.value or 0,
                    )
                    state['editing'] = False
                    await render_all()
                    ui.notify('Balans opgeslagen', type='positive')

                async def cancel_edit():
                    state['editing'] = False
                    await render_all()

                with ui.row().classes('q-mt-md gap-2'):
                    ui.button('Opslaan', icon='save',
                              on_click=save_balans).props('color=positive')
                    ui.button('Annuleren', icon='close',
                              on_click=cancel_edit).props('flat')

    def render_wv(data, winst, vorig_data=None, vorig_winst=None):
        """Render W&V tab with optional year-over-year comparison."""
        wv_panel.clear()
        jaar = state['jaar']
        has_vorig = vorig_data is not None and vorig_data.get('omzet', 0) > 0

        with wv_panel:
            # Data source info
            n_f = data['n_facturen']
            n_u = data['n_uitgaven']
            n_w = data['n_werkdagen']
            with ui.row().classes('gap-4 q-mb-md'):
                ui.badge(f'{n_f} facturen', color='primary').props('outline')
                ui.badge(f'{n_u} uitgaven', color='primary').props('outline')
                ui.badge(f'{n_w} werkdagen', color='primary').props('outline')

            if n_u == 0:
                with ui.card().classes('w-full bg-orange-1 q-pa-sm q-mb-md'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('warning', color='warning')
                        ui.label('Geen uitgaven gevonden voor dit jaar.') \
                            .classes('text-warning')

            def _wv_vergelijk(label, bedrag, vorig_bedrag=None,
                              bold=False, indent=False):
                """W&V line with optional prior-year column and delta."""
                css = 'text-bold' if bold else ''
                ml = 'q-ml-md' if indent else ''
                num_style = ('text-align: right; '
                             'font-variant-numeric: tabular-nums')
                with ui.row().classes(
                        f'w-full items-center {ml}').style('min-height: 28px'):
                    ui.label(label).classes(f'{css} flex-grow')
                    ui.label(format_euro(bedrag)).classes(css) \
                        .style(f'width: 110px; {num_style}')
                    if has_vorig:
                        vb = vorig_bedrag if vorig_bedrag is not None else 0
                        ui.label(format_euro(vb)) \
                            .classes('text-grey-6') \
                            .style(f'width: 110px; {num_style}')
                        if vb and bedrag:
                            delta = (bedrag - vb) / abs(vb) * 100
                            color = ('text-positive' if delta >= 0
                                     else 'text-negative')
                            ui.label(f'{delta:+.1f}%') \
                                .classes(f'text-caption {color}') \
                                .style(f'width: 60px; {num_style}')

            # W&V
            ui.label('Winst- en verliesrekening') \
                .classes('text-h6 text-primary')
            with ui.card().classes('w-full q-pa-md'):
                # Column headers
                if has_vorig:
                    num_style = 'text-align: right'
                    with ui.row().classes('w-full items-center') \
                            .style('min-height: 24px'):
                        ui.label('').classes('flex-grow')
                        ui.label(str(jaar)) \
                            .classes('text-caption text-bold') \
                            .style(f'width: 110px; {num_style}')
                        ui.label(str(jaar - 1)) \
                            .classes('text-caption text-grey-6') \
                            .style(f'width: 110px; {num_style}')
                        ui.label('\u0394') \
                            .classes('text-caption text-grey-6') \
                            .style(f'width: 60px; {num_style}')

                vorig_omzet = vorig_data['omzet'] if has_vorig else None
                _wv_vergelijk('Netto-omzet', data['omzet'],
                              vorig_omzet, bold=True)
                ui.separator().classes('q-my-sm')

                # Km-vergoeding as separate line
                vorig_km = vorig_data.get('km_vergoeding', 0) \
                    if has_vorig else None
                _wv_vergelijk('Km-vergoeding', data['km_vergoeding'],
                              vorig_km, indent=True)

                # Overige bedrijfskosten
                overige = data['kosten_excl_inv'] - data['km_vergoeding']
                vorig_overige = (
                    vorig_data['kosten_excl_inv']
                    - vorig_data.get('km_vergoeding', 0)
                ) if has_vorig else None
                _wv_vergelijk('Overige bedrijfskosten', overige,
                              vorig_overige, indent=True)

                vorig_afschr = vorig_data['totaal_afschrijvingen'] \
                    if has_vorig else None
                _wv_vergelijk('Afschrijvingen',
                              data['totaal_afschrijvingen'], vorig_afschr)
                ui.separator().classes('q-my-sm')
                _wv_vergelijk('Winst', winst, vorig_winst, bold=True)

            # Kostenspecificatie
            if data['kosten_per_cat']:
                ui.label('Kostenspecificatie') \
                    .classes('text-subtitle1 text-primary q-mt-lg')
                columns = [
                    {'name': 'cat', 'label': 'Categorie',
                     'field': 'categorie', 'align': 'left'},
                    {'name': 'bedrag', 'label': 'Bedrag',
                     'field': 'bedrag', 'align': 'right'},
                ]
                rows = [{'categorie': k['categorie'],
                         'bedrag': format_euro(k['totaal'])}
                        for k in data['kosten_per_cat']]
                rows.append({'categorie': 'Totaal',
                             'bedrag': format_euro(
                                 data['totaal_kosten_alle'])})
                ui.table(columns=columns, rows=rows) \
                    .classes('w-full max-w-lg')

    def render_toelichting(data):
        """Render Toelichting tab (activastaat + grondslagen)."""
        toelichting_panel.clear()
        with toelichting_panel:
            # Grondslagen
            ui.label('Grondslagen van waardering').classes('text-h6 text-primary')
            with ui.card().classes('w-full q-pa-md q-mb-lg'):
                ui.label(
                    'De jaarrekening is opgesteld op basis van fiscale grondslagen. '
                    'Materiële vaste activa worden gewaardeerd tegen aanschafwaarde '
                    'verminderd met lineaire afschrijvingen (restwaarde 10%). '
                    'Vorderingen en schulden worden gewaardeerd tegen nominale waarde.'
                ).classes('text-body2').style('color: #475569')
                ui.label(
                    'De netto-omzet betreft gefactureerde honoraria voor medische '
                    'waarnemingen, vrijgesteld van BTW op grond van artikel 11 '
                    'Wet OB 1968.'
                ).classes('text-body2 q-mt-sm').style('color: #475569')

            # Activastaat
            ui.label('Verloopoverzicht materiële vaste activa') \
                .classes('text-h6 text-primary')
            if data['activastaat']:
                columns = [
                    {'name': 'omschr', 'label': 'Omschrijving',
                     'field': 'omschrijving', 'align': 'left'},
                    {'name': 'aanschaf', 'label': 'Aanschafwaarde',
                     'field': 'aanschaf', 'align': 'right'},
                    {'name': 'per_jaar', 'label': 'Afschr/jaar',
                     'field': 'per_jaar', 'align': 'right'},
                    {'name': 'dit_jaar', 'label': f'Afschr {state["jaar"]}',
                     'field': 'dit_jaar', 'align': 'right'},
                    {'name': 'boekwaarde', 'label': 'Boekwaarde 31-12',
                     'field': 'boekwaarde', 'align': 'right'},
                ]
                rows = [{
                    'omschrijving': a['omschrijving'],
                    'aanschaf': format_euro(a['aanschaf_bedrag']),
                    'per_jaar': format_euro(a['afschrijving_jaar']),
                    'dit_jaar': format_euro(a['afschrijving_dit_jaar']),
                    'boekwaarde': format_euro(a['boekwaarde']),
                } for a in data['activastaat']]
                ui.table(columns=columns, rows=rows).classes('w-full')
                ui.label(
                    f'Totaal afschrijvingen {state["jaar"]}: '
                    f'{format_euro(data["totaal_afschrijvingen"])}'
                ).classes('text-bold q-mt-sm')
            else:
                ui.label('Geen investeringen / afschrijvingen.') \
                    .classes('text-grey-6')

    async def render_controles(data, balans, _winst):
        """Render Controles tab — kengetallen + data integrity checks."""
        controles_panel.clear()
        jaar = state['jaar']

        with controles_panel:
            # === Section 1: Kengetallen ===
            ui.label('Kengetallen').classes('text-h6 text-primary')

            # Kosten/omzet ratio
            ratio = round(data['kosten_excl_inv'] / data['omzet'] * 100, 1) \
                if data['omzet'] > 0 else 0
            ratio_color = 'positive' if ratio <= 25 else 'warning' if ratio <= 30 else 'negative'
            with ui.card().classes('w-full q-pa-md q-mb-md'):
                with ui.row().classes('items-center gap-3'):
                    ui.icon('pie_chart', size='1.5rem').style('color: #0F766E')
                    ui.label('Kosten/omzet ratio').classes('text-subtitle1')
                    ui.badge(f'{ratio}%', color=ratio_color).classes('text-sm')
                if ratio > 30:
                    ui.label('Hoge kosten ten opzichte van omzet.') \
                        .classes('text-caption text-negative q-mt-xs')

            # Urencriterium
            uren = data['uren']
            norm = data['params_dict'].get('urencriterium', 1225)
            uren_ok = uren >= norm
            with ui.card().classes('w-full q-pa-md q-mb-md'):
                with ui.row().classes('items-center gap-3'):
                    ui.icon('schedule', size='1.5rem').style('color: #0F766E')
                    ui.label('Urencriterium').classes('text-subtitle1')
                    ui.badge(
                        f'{int(uren)} / {int(norm)} uur',
                        color='positive' if uren_ok else 'negative',
                    ).classes('text-sm')
                if not uren_ok:
                    ui.label(
                        f'Urencriterium niet gehaald. Nog {int(norm - uren)} uur nodig.'
                    ).classes('text-caption text-negative q-mt-xs')

            # Balans check (activa = passiva)
            totaal_passiva = balans['eigen_vermogen'] + balans['totaal_schulden']
            balans_ok = abs(balans['totaal_activa'] - totaal_passiva) < 0.01
            with ui.card().classes('w-full q-pa-md q-mb-md'):
                with ui.row().classes('items-center gap-3'):
                    ui.icon('balance', size='1.5rem').style('color: #0F766E')
                    ui.label('Balans controle').classes('text-subtitle1')
                    ui.badge(
                        'Activa = Passiva' if balans_ok else 'VERSCHIL',
                        color='positive' if balans_ok else 'negative',
                    ).classes('text-sm')
                if not balans_ok:
                    diff = balans['totaal_activa'] - totaal_passiva
                    ui.label(f'Verschil: {format_euro(diff)}') \
                        .classes('text-caption text-negative q-mt-xs')

            # === Section 2: Data-integriteit ===
            ui.label('Data-integriteit').classes('text-h6 text-primary q-mt-lg')

            issues = []
            ok_checks = []

            async with get_db_ctx(DB_PATH) as conn:
                # 1. Ongefactureerde werkdagen
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM werkdagen "
                    "WHERE substr(datum,1,4)=? AND status='ongefactureerd' "
                    "AND tarief > 0", (str(jaar),))
                ongefact = (await cur.fetchone())[0]
                if ongefact > 0:
                    issues.append((
                        'warning',
                        f'{ongefact} ongefactureerde werkdagen met tarief > 0',
                        '/werkdagen'))
                else:
                    ok_checks.append('Alle werkdagen gefactureerd')

                # 2. Facturen zonder werkdagen
                cur = await conn.execute(
                    "SELECT nummer, totaal_bedrag FROM facturen "
                    "WHERE substr(datum,1,4)=? AND type='factuur' "
                    "AND NOT EXISTS ("
                    "  SELECT 1 FROM werkdagen w "
                    "  WHERE w.factuurnummer = facturen.nummer"
                    ")", (str(jaar),))
                orphans = await cur.fetchall()
                if orphans:
                    nrs = ', '.join(r[0] for r in orphans[:5])
                    issues.append((
                        'warning',
                        f'{len(orphans)} facturen zonder werkdagen: {nrs}',
                        '/facturen'))
                else:
                    ok_checks.append('Alle facturen gekoppeld aan werkdagen')

                # 3. Betaalde facturen zonder betaald_datum
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM facturen "
                    "WHERE substr(datum,1,4)=? AND betaald=1 "
                    "AND (betaald_datum IS NULL OR betaald_datum='')",
                    (str(jaar),))
                no_date = (await cur.fetchone())[0]
                if no_date > 0:
                    issues.append((
                        'info',
                        f'{no_date} betaalde facturen zonder betaaldatum',
                        '/facturen'))
                else:
                    ok_checks.append('Alle betaalde facturen hebben betaaldatum')

                # 4. Niet-gecategoriseerde banktransacties
                cur = await conn.execute(
                    "SELECT COUNT(*) FROM banktransacties "
                    "WHERE substr(datum,1,4)=? "
                    "AND (categorie IS NULL OR categorie='') "
                    "AND koppeling_type IS NULL",
                    (str(jaar),))
                uncat = (await cur.fetchone())[0]
                if uncat > 0:
                    issues.append((
                        'info',
                        f'{uncat} banktransacties niet gecategoriseerd',
                        '/bank'))

            # 5. VA bedragen zonder beschikking PDF
            params = data['params']
            va_total = (params.voorlopige_aanslag_betaald or 0) + \
                       (params.voorlopige_aanslag_zvw or 0)
            docs = await get_aangifte_documenten(DB_PATH, jaar)
            doc_types = {d.documenttype for d in docs}
            has_va_docs = ('va_ib_beschikking' in doc_types or
                           'va_zvw_beschikking' in doc_types)
            if va_total > 0 and not has_va_docs:
                issues.append((
                    'warning',
                    f'VA bedragen ingevuld ({format_euro(va_total)}) '
                    f'maar geen beschikking PDF geüpload',
                    '/documenten'))
            elif va_total == 0:
                issues.append((
                    'warning',
                    'Voorlopige aanslag niet ingevuld',
                    '/aangifte'))
            else:
                ok_checks.append('VA bedragen + beschikking PDF aanwezig')

            # 6. Persoonlijke gegevens
            missing_personal = []
            if (params.woz_waarde or 0) == 0:
                missing_personal.append('WOZ-waarde')
            if (params.hypotheekrente or 0) == 0:
                missing_personal.append('Hypotheekrente')
            if (params.aov_premie or 0) == 0:
                missing_personal.append('AOV premie')
            if missing_personal:
                issues.append((
                    'info',
                    f'Persoonlijke gegevens ontbreken: '
                    f'{", ".join(missing_personal)}',
                    '/aangifte'))
            else:
                ok_checks.append('Persoonlijke gegevens compleet')

            # 7. Document completeness
            from components.document_specs import AANGIFTE_DOCS
            total_docs = len(AANGIFTE_DOCS)
            done_docs = len({d.documenttype for d in docs})
            if done_docs < total_docs:
                issues.append((
                    'info',
                    f'Documenten: {done_docs}/{total_docs} geüpload',
                    '/documenten'))
            else:
                ok_checks.append(f'Alle {total_docs} documenten geüpload')

            # 8. Missing data warnings (existing)
            if data['n_uitgaven'] == 0:
                issues.append(('warning', 'Geen uitgaven ingevoerd', '/kosten'))
            if data['n_facturen'] == 0:
                issues.append(('warning', 'Geen facturen gevonden', '/facturen'))
            if balans['bank_saldo'] == 0:
                issues.append((
                    'info', 'Bank saldo is €0 — vul in via Balans tab', None))

            # Render issues
            if issues:
                with ui.card().classes('w-full q-pa-md q-mb-md'):
                    with ui.row().classes('items-center gap-2 q-mb-sm'):
                        ui.icon('report_problem', color='warning')
                        ui.label(f'{len(issues)} aandachtspunten') \
                            .classes('text-subtitle1 text-weight-bold')
                    for severity, msg, link in issues:
                        icon = ('warning' if severity == 'warning'
                                else 'info_outline')
                        color = ('text-warning' if severity == 'warning'
                                 else 'text-grey-7')
                        with ui.row().classes('w-full items-center gap-2'):
                            ui.icon(icon, size='sm').classes(color)
                            ui.label(msg).classes(f'flex-grow {color}')
                            if link:
                                ui.button(
                                    icon='open_in_new',
                                    on_click=lambda l=link: ui.navigate.to(l),
                                ).props('flat dense round size=sm color=primary')

            # Render OK checks
            if ok_checks:
                with ui.card().classes('w-full q-pa-md'):
                    with ui.row().classes('items-center gap-2 q-mb-sm'):
                        ui.icon('check_circle', color='positive')
                        ui.label('Goedgekeurd').classes(
                            'text-subtitle1 text-weight-bold text-positive')
                    for msg in ok_checks:
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('check', size='sm', color='positive')
                            ui.label(msg).classes('text-grey-7')

    async def render_document(data, balans, winst, vorig_jaar_balans):
        """Render Document tab — inline HTML preview + PDF export."""
        document_panel.clear()
        jaar = state['jaar']
        params = data['params']

        # Fetch bedrijfsgegevens for PDF
        bg = await get_bedrijfsgegevens(DB_PATH)
        bg_naam = bg.bedrijfsnaam if bg else 'Onderneming'
        bg_kvk = bg.kvk if bg else ''

        # Check status
        status = getattr(params, 'jaarafsluiting_status', 'concept') or 'concept'

        with document_panel:
            if status != 'definitief':
                with ui.card().classes('w-full q-pa-md bg-blue-1 q-mb-md'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('info', color='info')
                        ui.label(
                            'Markeer de jaarafsluiting als definitief '
                            'voordat u de PDF exporteert.'
                        ).classes('text-info')

            # PDF export button
            async def export_pdf():
                html = _render_pdf_html(jaar, data, balans, winst, vorig_jaar_balans,
                                        bedrijfsnaam=bg_naam, kvk=bg_kvk)
                pdf_dir = DB_PATH.parent / 'pdf' / str(jaar)
                pdf_dir.mkdir(parents=True, exist_ok=True)
                pdf_path = pdf_dir / f'Jaarcijfers_{jaar}.pdf'
                try:
                    from weasyprint import HTML
                    await asyncio.to_thread(
                        lambda: HTML(string=html).write_pdf(str(pdf_path)))
                    ui.notify(f'PDF opgeslagen: {pdf_path.name}', type='positive')
                except Exception as e:
                    ui.notify(f'PDF fout: {e}', type='negative')

            ui.button('Exporteer PDF', icon='picture_as_pdf',
                      on_click=export_pdf).props('color=primary')

            # Inline HTML preview
            ui.separator().classes('q-my-md')
            ui.label('Preview').classes('text-subtitle1 text-grey-6')
            html = _render_pdf_html(jaar, data, balans, winst, vorig_jaar_balans,
                                    bedrijfsnaam=bg_naam, kvk=bg_kvk)
            ui.html(html).classes('w-full').style(
                'border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; '
                'background: white; max-height: 80vh; overflow-y: auto;'
            )

    # --- Actions ---

    async def toggle_edit():
        state['editing'] = not state['editing']
        await render_all()

    async def set_definitief():
        jaar = state['jaar']
        params = await get_fiscale_params(DB_PATH, jaar)
        current_status = getattr(params, 'jaarafsluiting_status', 'concept') or 'concept'

        if current_status == 'definitief':
            # Reopen
            with ui.dialog() as dlg, ui.card():
                ui.label('Jaarafsluiting heropenen?').classes('text-h6')
                ui.label(
                    'De jaarcijfers worden weer bewerkbaar. '
                    'De definitieve status wordt ingetrokken.'
                ).classes('q-mb-md')
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('Annuleren', on_click=dlg.close).props('flat')
                    async def confirm_reopen():
                        await update_jaarafsluiting_status(DB_PATH, jaar, 'concept')
                        dlg.close()
                        ui.notify('Jaarafsluiting heropend', type='info')
                        await render_all()
                    ui.button('Heropenen', on_click=confirm_reopen) \
                        .props('color=warning')
            dlg.open()
        else:
            # Mark as definitief
            with ui.dialog() as dlg, ui.card():
                ui.label('Markeren als definitief?').classes('text-h6')
                ui.label(
                    'De jaarcijfers worden vergrendeld. '
                    'U kunt later heropenen indien nodig.'
                ).classes('q-mb-md')
                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('Annuleren', on_click=dlg.close).props('flat')
                    async def confirm_definitief():
                        await update_jaarafsluiting_status(DB_PATH, jaar, 'definitief')
                        dlg.close()
                        ui.notify('Jaarafsluiting is nu definitief', type='positive')
                        await render_all()
                    ui.button('Markeer definitief', on_click=confirm_definitief) \
                        .props('color=positive')
            dlg.open()

    # Year change handler
    async def on_year_change(e):
        state['jaar'] = e.value
        state['editing'] = False
        await render_all()

    jaar_select.on('update:model-value', on_year_change)

    # Initial render
    await render_all()


# === PDF Template Rendering ===

def _render_pdf_html(jaar, data, balans, winst, vorig_jaar_balans,
                     bedrijfsnaam='', kvk=''):
    """Render the jaarcijfers PDF HTML — pure business report."""
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent.parent / 'templates')),
        autoescape=False
    )

    def euro_filter(value):
        if value is None:
            return '€ 0'
        return f"€ {value:,.0f}".replace(',', '.')

    env.filters['euro'] = euro_filter

    template = env.get_template('jaarafsluiting.html')
    return template.render(
        jaar=jaar,
        bedrijfsnaam=bedrijfsnaam,
        kvk=kvk,
        datum=date.today().strftime('%d-%m-%Y'),
        balans=balans,
        balans_vorig_jaar=vorig_jaar_balans,
        omzet=data['omzet'],
        kosten_excl_inv=data['kosten_excl_inv'],
        totaal_afschrijvingen=data['totaal_afschrijvingen'],
        winst=winst,
        kosten_per_cat=data['kosten_per_cat'],
        totaal_kosten=data['totaal_kosten_alle'],
        activastaat=data['activastaat'],
    )
