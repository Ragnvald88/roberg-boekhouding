"""Jaarafsluiting pagina — tab-based UI with fiscal engine + PDF export."""

import re
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from nicegui import ui

from components.fiscal_utils import (
    bereken_balans, fetch_fiscal_data, fiscale_params_to_dict,
)
from components.kpi_card import kpi_strip
from components.layout import create_layout
from components.utils import format_euro
from database import (
    update_balans_inputs,
    update_ib_inputs,
    update_ew_naar_partner,
    update_za_sa_toggles,
    DB_PATH,
)
from fiscal.berekeningen import FiscaalResultaat, bereken_box3, bereken_volledig


# === Shared helpers ===

def _wv_line(label: str, value: float, prefix: str = '', bold: bool = False):
    """Render a W&V line with label and euro value."""
    css = 'text-bold' if bold else ''
    with ui.row().classes('w-full justify-between'):
        text = f'{prefix}  {label}' if prefix else label
        ui.label(text).classes(css)
        ui.label(format_euro(value)).classes(f'{css} text-right') \
            .style('min-width: 120px; font-variant-numeric: tabular-nums')


def _waterfall_line(label: str, value: float, bold: bool = False,
                    is_subtotal: bool = False, is_total: bool = False,
                    indent: int = 0, prefix: str = '', grey: bool = False):
    """Render a fiscal waterfall line with alignment and styling."""
    css_parts = []
    if bold:
        css_parts.append('text-bold')
    row_style = ''
    if is_total:
        row_style = 'background-color: #f0fdfa; border-top: 2px solid #0F766E; padding: 4px 0'
    elif is_subtotal:
        row_style = 'border-top: 1px solid #CBD5E1; padding-top: 2px'

    indent_px = indent * 16
    text = f'{prefix} {label}'.strip() if prefix else label
    text_style = f'padding-left: {indent_px}px'
    if grey:
        text_style += '; color: #94A3B8; font-style: italic'

    with ui.row().classes(f'w-full justify-between {" ".join(css_parts)}').style(row_style):
        ui.label(text).style(text_style)
        ui.label(format_euro(value)).classes('text-right') \
            .style('min-width: 120px; font-variant-numeric: tabular-nums')


@ui.page('/jaarafsluiting')
async def jaarafsluiting_page():
    create_layout('Jaarafsluiting', '/jaarafsluiting')

    # --- State ---
    huidig_jaar = date.today().year
    vorig_jaar = huidig_jaar - 1
    jaren = list(range(huidig_jaar, 2022, -1))
    state = {
        'jaar': vorig_jaar,
        'data': None,
        'fiscaal': None,
        'box3': None,
        'balans': None,
        'balans_vorig_jaar': None,
        'params_dict': {},
    }

    # UI refs
    refs = {
        'kpi_container': None,
        'tab_panels': None,
        'tabs': None,
        # Invoer tab inputs
        'za_actief': None, 'sa_actief': None,
        'aov': None, 'lijfrente': None, 'woz': None, 'hypotheek': None,
        'ew_partner': None,
        'va_ib': None, 'va_zvw': None,
        'balans_bank': None, 'balans_crediteuren': None,
        'balans_overige_vorderingen': None, 'balans_overige_schulden': None,
        # Tab refs for badges
        'tab_controles': None, 'tab_invoer': None,
        # Tab panel containers
        'panel_invoer': None, 'panel_wv': None, 'panel_fiscaal': None,
        'panel_belasting': None, 'panel_balans': None, 'panel_controles': None,
    }

    # === Calculation ===

    async def _calculate(jaar: int):
        """Fetch all data and run calculations."""
        data = await fetch_fiscal_data(DB_PATH, jaar)
        if data is None:
            state.update({'data': None, 'fiscaal': None, 'box3': None,
                          'balans': None, 'balans_vorig_jaar': None, 'params_dict': {}})
            return False

        params_dict = data['params_dict']
        lijfrente = data.get('lijfrente', 0)

        fiscaal = bereken_volledig(
            omzet=data['omzet'],
            kosten=data['kosten_excl_inv'],
            afschrijvingen=data['totaal_afschrijvingen'],
            representatie=data['representatie'],
            investeringen_totaal=data['inv_totaal_dit_jaar'],
            uren=data['uren'],
            params=params_dict,
            aov=data['aov'],
            lijfrente=lijfrente,
            woz=data['woz'],
            hypotheekrente=data['hypotheekrente'],
            voorlopige_aanslag=data['voorlopige_aanslag'],
            voorlopige_aanslag_zvw=data['voorlopige_aanslag_zvw'],
            ew_naar_partner=data['ew_naar_partner'],
        )

        box3 = bereken_box3(params_dict)

        # Balance sheet — current + previous year
        prev_data = await fetch_fiscal_data(DB_PATH, jaar - 1)
        begin_vermogen = 0.0
        balans_vorig_jaar = None
        if prev_data:
            # Calculate prior year's winst from its data
            prev_winst = (prev_data['omzet'] - prev_data['kosten_excl_inv']
                          - prev_data['totaal_afschrijvingen'])
            balans_vorig_jaar = await bereken_balans(
                DB_PATH, jaar - 1, prev_data['activastaat'],
                winst=prev_winst, begin_vermogen=0)
            begin_vermogen = balans_vorig_jaar['eigen_vermogen']

        balans = await bereken_balans(
            DB_PATH, jaar, data['activastaat'],
            winst=fiscaal.winst, begin_vermogen=begin_vermogen)

        state.update({
            'data': data, 'fiscaal': fiscaal, 'box3': box3,
            'balans': balans, 'balans_vorig_jaar': balans_vorig_jaar,
            'params_dict': params_dict,
        })
        return True

    # === Save + Recalculate ===

    async def save_and_recalculate():
        """Single save handler for all inputs on Invoer tab."""
        jaar = state['jaar']

        # Save ZA/SA toggles
        za = refs['za_actief'].value if refs['za_actief'] else True
        sa = refs['sa_actief'].value if refs['sa_actief'] else False
        await update_za_sa_toggles(DB_PATH, jaar=jaar,
                                    za_actief=za, sa_actief=sa)

        # Save IB inputs + lijfrente
        await update_ib_inputs(
            DB_PATH, jaar=jaar,
            aov_premie=float(refs['aov'].value or 0),
            woz_waarde=float(refs['woz'].value or 0),
            hypotheekrente=float(refs['hypotheek'].value or 0),
            voorlopige_aanslag_betaald=float(refs['va_ib'].value or 0),
            voorlopige_aanslag_zvw=float(refs['va_zvw'].value or 0),
            lijfrente_premie=float(refs['lijfrente'].value or 0),
        )

        # Save ew_naar_partner
        ew_val = refs['ew_partner'].value if refs['ew_partner'] else True
        await update_ew_naar_partner(DB_PATH, jaar=jaar, value=ew_val)

        # Save balans inputs
        await update_balans_inputs(
            DB_PATH, jaar=jaar,
            balans_bank_saldo=float(refs['balans_bank'].value or 0),
            balans_crediteuren=float(refs['balans_crediteuren'].value or 0),
            balans_overige_vorderingen=float(refs['balans_overige_vorderingen'].value or 0),
            balans_overige_schulden=float(refs['balans_overige_schulden'].value or 0),
        )

        ui.notify('Opgeslagen en herberekend', type='positive')
        # Recalculate and update read-only tabs, but keep Invoer inputs intact
        ok = await _calculate(jaar)
        if ok:
            render_kpis()
            render_wv()
            render_fiscaal()
            render_belasting()
            render_balans()
            render_controles()
            await render_document()

    # === Reset IB inputs ===

    async def reset_ib_inputs():
        """Reset all IB input fields to zero for this year."""
        jaar = state['jaar']
        await update_ib_inputs(
            DB_PATH, jaar=jaar,
            aov_premie=0, woz_waarde=0, hypotheekrente=0,
            voorlopige_aanslag_betaald=0, voorlopige_aanslag_zvw=0,
            lijfrente_premie=0,
        )
        await update_ew_naar_partner(DB_PATH, jaar=jaar, value=True)
        await update_za_sa_toggles(DB_PATH, jaar=jaar, za_actief=True, sa_actief=False)
        await update_balans_inputs(
            DB_PATH, jaar=jaar,
            balans_bank_saldo=0, balans_crediteuren=0,
            balans_overige_vorderingen=0, balans_overige_schulden=0,
        )
        ui.notify('Invoer gereset', type='info')
        await refresh_all()

    # === Render functions ===

    def render_data_warnings():
        """Render data completeness warning banner."""
        c = refs.get('warnings_container')
        if c is None:
            return
        c.clear()
        data = state['data']
        if data is None:
            return

        warnings = []
        if data.get('n_uitgaven', 0) == 0:
            warnings.append(('Geen uitgaven ingevoerd', 'Kosten', '/kosten'))
        if data['voorlopige_aanslag'] == 0 and data['voorlopige_aanslag_zvw'] == 0:
            warnings.append(('Geen voorlopige aanslagen', 'Invoer tab', None))
        if data['aov'] == 0:
            warnings.append(('Geen AOV premie', 'Invoer tab', None))

        if not warnings:
            return

        with c:
            with ui.element('div').classes('w-full q-pa-sm rounded-borders') \
                    .style('background: #FFF7ED; border: 1px solid #FB923C'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('warning', color='warning').classes('text-lg')
                    ui.label('Onvolledige data:').classes('text-bold text-warning')
                for msg, source, link in warnings:
                    with ui.row().classes('items-center gap-1 q-ml-lg'):
                        ui.label(f'{msg}').classes('text-caption')
                        if link:
                            ui.link(f'→ {source}', link).classes(
                                'text-caption text-primary')
                        else:
                            ui.label(f'({source})').classes('text-caption text-grey-7')

    def render_kpis():
        """Update KPI strip."""
        c = refs['kpi_container']
        if c is None:
            return
        c.clear()
        f = state['fiscaal']
        if f is None:
            return
        box3_belasting = state['box3'].belasting if state['box3'] else 0
        totaal_resultaat = f.resultaat + box3_belasting
        with c:
            kpi_strip(f.winst, f.belastbare_winst,
                      f.netto_ib + f.zvw, totaal_resultaat)

    def render_invoer():
        """Render the Invoer tab content."""
        c = refs['panel_invoer']
        if c is None:
            return
        c.clear()
        data = state['data']
        if data is None:
            return
        params = data['params']
        pd = data['params_dict']

        with c:
            with ui.row().classes('w-full gap-6 flex-wrap'):
                # LEFT column
                with ui.column().classes('flex-1 min-w-80 gap-4'):
                    # Ondernemersaftrek card
                    with ui.card().classes('w-full'):
                        ui.label('Ondernemersaftrek').classes('text-subtitle2 text-bold')
                        with ui.row().classes('items-center gap-4'):
                            refs['za_actief'] = ui.checkbox(
                                'Zelfstandigenaftrek toepassen',
                                value=params.za_actief,
                            )
                            ui.label(format_euro(params.zelfstandigenaftrek)) \
                                .classes('text-grey-7')
                        with ui.row().classes('items-center gap-4'):
                            refs['sa_actief'] = ui.checkbox(
                                'Startersaftrek toepassen',
                                value=params.sa_actief,
                            )
                            ui.label(format_euro(params.startersaftrek or 0)) \
                                .classes('text-grey-7')
                        ui.label('Max 3x in eerste 5 jaar als ondernemer') \
                            .classes('text-caption text-grey-7')

                    # Persoonlijk card
                    with ui.card().classes('w-full'):
                        ui.label('Persoonlijk').classes('text-subtitle2 text-bold')
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            refs['aov'] = ui.number(
                                'AOV premie (\u20ac)', value=data['aov'],
                                format='%.2f', min=0, step=100,
                            ).classes('w-44')
                            refs['lijfrente'] = ui.number(
                                'Lijfrentepremie (\u20ac)',
                                value=data.get('lijfrente', 0),
                                format='%.2f', min=0, step=100,
                            ).classes('w-44')
                            refs['woz'] = ui.number(
                                'WOZ-waarde (\u20ac)', value=data['woz'],
                                format='%.0f', min=0, step=1000,
                            ).classes('w-44')
                            refs['hypotheek'] = ui.number(
                                'Hypotheekrente (\u20ac)',
                                value=data['hypotheekrente'],
                                format='%.2f', min=0, step=100,
                            ).classes('w-44')
                        refs['ew_partner'] = ui.checkbox(
                            'Eigen woning toerekenen aan partner',
                            value=data['ew_naar_partner'],
                        ).classes('q-mt-sm')

                    # Voorlopige aanslagen card
                    with ui.card().classes('w-full'):
                        ui.label('Voorlopige aanslagen').classes('text-subtitle2 text-bold')
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            refs['va_ib'] = ui.number(
                                'VA Inkomstenbelasting (\u20ac)',
                                value=data['voorlopige_aanslag'],
                                format='%.2f', min=0, step=100,
                            ).classes('w-52')
                            refs['va_zvw'] = ui.number(
                                'VA Zorgverzekeringswet (\u20ac)',
                                value=data['voorlopige_aanslag_zvw'],
                                format='%.2f', min=0, step=100,
                            ).classes('w-52')

                # RIGHT column
                with ui.column().classes('flex-1 min-w-80 gap-4'):
                    # Balans card
                    with ui.card().classes('w-full'):
                        ui.label('Balans per 31-12').classes('text-subtitle2 text-bold')
                        balans = state['balans'] or {}
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            refs['balans_bank'] = ui.number(
                                'Bank saldo (\u20ac)',
                                value=balans.get('bank_saldo', 0),
                                format='%.2f', step=100,
                            ).classes('w-44')
                            refs['balans_crediteuren'] = ui.number(
                                'Crediteuren (\u20ac)',
                                value=balans.get('crediteuren', 0),
                                format='%.2f', min=0, step=100,
                            ).classes('w-44')
                            refs['balans_overige_vorderingen'] = ui.number(
                                'Overige vorderingen (\u20ac)',
                                value=balans.get('overige_vorderingen', 0),
                                format='%.2f', min=0, step=100,
                            ).classes('w-44')
                            refs['balans_overige_schulden'] = ui.number(
                                'Overige schulden (\u20ac)',
                                value=balans.get('overige_schulden', 0),
                                format='%.2f', min=0, step=100,
                            ).classes('w-44')

                    # Fiscal params (read-only expansion)
                    with ui.card().classes('w-full'):
                        with ui.expansion('Fiscale parameters (alleen-lezen)') \
                                .classes('w-full').props('dense'):
                            with ui.grid(columns=2).classes('w-full gap-2'):
                                for lbl, val in [
                                    ('Zelfstandigenaftrek', format_euro(pd.get('zelfstandigenaftrek', 0))),
                                    ('Startersaftrek', format_euro(pd.get('startersaftrek', 0))),
                                    ('MKB-vrijstelling', f"{pd.get('mkb_vrijstelling_pct', 0)}%"),
                                    ('KIA', f"{pd.get('kia_pct', 0)}%"),
                                    ('KIA grenzen', f"{format_euro(pd.get('kia_ondergrens', 0))} - {format_euro(pd.get('kia_bovengrens', 0))}"),
                                    ('Urencriterium', f"{pd.get('urencriterium', 1225):.0f} uur"),
                                    ('Representatie', f"{pd.get('repr_aftrek_pct', 80)}%"),
                                ]:
                                    ui.label(lbl).classes('text-caption text-grey-7')
                                    ui.label(val).classes('text-caption')
                            ui.button(
                                'Wijzigen in Instellingen \u2192',
                                on_click=lambda: ui.navigate.to('/instellingen'),
                            ).props('flat dense color=primary').classes('q-mt-sm')

            # Save + reset buttons
            with ui.row().classes('q-mt-md gap-3 items-center'):
                ui.button(
                    'Opslaan & herbereken', icon='refresh',
                    on_click=save_and_recalculate,
                ).props('color=primary')

                async def confirm_reset():
                    with ui.dialog() as dlg, ui.card():
                        ui.label('Weet u zeker dat u alle invoervelden wilt resetten?') \
                            .classes('text-body1')
                        ui.label('Dit zet alle persoonlijke invoer (AOV, WOZ, VA, etc.) '
                                 'terug naar 0.').classes('text-caption text-grey-7')

                        async def do_reset():
                            dlg.close()
                            await reset_ib_inputs()

                        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                            ui.button('Annuleren', on_click=dlg.close) \
                                .props('flat')
                            ui.button('Reset', on_click=do_reset) \
                                .props('color=negative flat')
                    dlg.open()

                ui.button(
                    'Reset invoer', icon='restart_alt',
                    on_click=confirm_reset,
                ).props('flat color=negative')

    def render_wv():
        """Render W&V tab."""
        c = refs['panel_wv']
        if c is None:
            return
        c.clear()
        f = state['fiscaal']
        data = state['data']
        if f is None or data is None:
            return
        jaar = state['jaar']
        n_fact = data.get('n_facturen', 0)
        n_uitg = data.get('n_uitgaven', 0)
        n_werk = data.get('n_werkdagen', 0)

        with c:
            # Data source summary
            with ui.row().classes('w-full gap-3 flex-wrap items-center'):
                ui.label('Brondata:').classes('text-caption text-bold text-grey-7')
                ui.link(f'{n_fact} facturen', '/facturen').classes(
                    'text-caption text-primary')
                if n_uitg > 0:
                    ui.link(f'{n_uitg} uitgaven', '/kosten').classes(
                        'text-caption text-primary')
                else:
                    with ui.row().classes('items-center gap-1'):
                        ui.icon('warning', color='warning').classes('text-sm')
                        ui.link('0 uitgaven — toevoegen', '/kosten').classes(
                            'text-caption text-warning')
                ui.link(f'{n_werk} werkdagen ({data["uren"]:.0f} uur)',
                        '/werkdagen').classes('text-caption text-primary')

            # W&V rekening
            with ui.card().classes('w-full'):
                ui.label(f'Winst- en verliesrekening {jaar}').classes(
                    'text-subtitle1 text-bold')
                with ui.row().classes('w-full justify-between'):
                    with ui.row().classes('items-center gap-2'):
                        ui.label('Netto-omzet')
                        ui.label(f'({n_fact} facturen)').classes(
                            'text-caption text-grey-7')
                    ui.label(format_euro(f.omzet)).classes('text-right') \
                        .style('min-width: 120px; font-variant-numeric: tabular-nums')
                with ui.row().classes('w-full justify-between'):
                    with ui.row().classes('items-center gap-2'):
                        ui.label('-/-  Bedrijfslasten')
                        if n_uitg == 0:
                            ui.label('(geen uitgaven!)').classes(
                                'text-caption text-warning')
                        else:
                            ui.label(f'({n_uitg} uitgaven)').classes(
                                'text-caption text-grey-7')
                    ui.label(format_euro(data['kosten_excl_inv'])).classes('text-right') \
                        .style('min-width: 120px; font-variant-numeric: tabular-nums')
                _wv_line('Afschrijvingen', data['totaal_afschrijvingen'],
                         prefix='-/-')
                ui.separator()
                _wv_line('Winst', f.winst, bold=True)

                # Kosten per categorie
                with ui.expansion('Kosten per categorie').classes(
                        'w-full text-caption').props('dense'):
                    kosten_per_cat = data['kosten_per_cat']
                    if kosten_per_cat:
                        kosten_rows = [
                            {'categorie': r['categorie'],
                             'bedrag': format_euro(r['totaal'])}
                            for r in kosten_per_cat
                        ]
                        kosten_columns = [
                            {'name': 'categorie', 'label': 'Categorie',
                             'field': 'categorie', 'align': 'left'},
                            {'name': 'bedrag', 'label': 'Bedrag',
                             'field': 'bedrag', 'align': 'right'},
                        ]
                        ui.table(
                            columns=kosten_columns, rows=kosten_rows,
                            row_key='categorie',
                        ).classes('w-full').props('dense flat')
                        with ui.row().classes('w-full justify-between'):
                            ui.label('Totaal bedrijfslasten').classes('text-bold')
                            ui.label(format_euro(data['totaal_kosten_alle'])).classes('text-bold')
                    else:
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('warning', color='warning')
                            ui.label('Geen uitgaven ingevoerd voor dit jaar.').classes(
                                'text-warning')
                            ui.link('Kosten toevoegen →', '/kosten').classes(
                                'text-primary')

            # Activastaat
            with ui.card().classes('w-full'):
                ui.label(f'Activastaat {jaar}').classes(
                    'text-subtitle1 text-bold')
                activastaat = data['activastaat']
                if activastaat:
                    activa_rows = [
                        {
                            'omschrijving': a['omschrijving'],
                            'aanschaf': str(a['aanschaf_jaar']),
                            'bedrag': format_euro(a['aanschaf_bedrag']),
                            'afschr_jr': format_euro(a['afschrijving_jaar']),
                            'afschr_dit': format_euro(a['afschrijving_dit_jaar']),
                            'boekwaarde': format_euro(a['boekwaarde']),
                        }
                        for a in activastaat
                    ]
                    activa_columns = [
                        {'name': 'omschrijving', 'label': 'Omschrijving',
                         'field': 'omschrijving', 'align': 'left'},
                        {'name': 'aanschaf', 'label': 'Aanschaf',
                         'field': 'aanschaf', 'align': 'center'},
                        {'name': 'bedrag', 'label': 'Bedrag',
                         'field': 'bedrag', 'align': 'right'},
                        {'name': 'afschr_jr', 'label': 'Afschr/jaar',
                         'field': 'afschr_jr', 'align': 'right'},
                        {'name': 'afschr_dit', 'label': f'Afschr {jaar}',
                         'field': 'afschr_dit', 'align': 'right'},
                        {'name': 'boekwaarde', 'label': 'Boekwaarde 31-12',
                         'field': 'boekwaarde', 'align': 'right'},
                    ]
                    ui.table(
                        columns=activa_columns, rows=activa_rows,
                        row_key='omschrijving',
                    ).classes('w-full').props('dense flat')
                    ui.separator()
                    with ui.row().classes('w-full justify-between'):
                        ui.label('Totaal afschrijvingen').classes('text-bold')
                        ui.label(format_euro(data['totaal_afschrijvingen'])).classes('text-bold')
                else:
                    ui.label('Geen investeringen / afschrijvingen.').classes('text-grey')

    def render_fiscaal():
        """Render Fiscaal tab."""
        c = refs['panel_fiscaal']
        if c is None:
            return
        c.clear()
        f = state['fiscaal']
        if f is None:
            return
        jaar = state['jaar']
        pd = state['params_dict']
        za_actief = pd.get('za_actief', True)
        sa_actief = pd.get('sa_actief', False)

        with c:
            with ui.card().classes('w-full'):
                ui.label(f'Fiscale winstberekening {jaar}').classes(
                    'text-subtitle1 text-bold')

                _waterfall_line('Winst jaarrekening', f.winst)
                _waterfall_line('Bijtelling representatie (20%)',
                                f.repr_bijtelling, prefix='+')
                _waterfall_line('Kleinschaligheidsinvesteringsaftrek (KIA)',
                                f.kia, prefix='-')
                _waterfall_line('Fiscale winst', f.fiscale_winst,
                                bold=True, is_subtotal=True, prefix='=')

                ui.separator().classes('my-2')

                if za_actief:
                    _waterfall_line('Zelfstandigenaftrek',
                                    f.zelfstandigenaftrek, prefix='-')
                else:
                    _waterfall_line('Zelfstandigenaftrek: niet van toepassing',
                                    0, grey=True, prefix='-')
                if sa_actief:
                    if f.startersaftrek > 0:
                        _waterfall_line('Startersaftrek',
                                        f.startersaftrek, prefix='-')
                _waterfall_line('Na ondernemersaftrek',
                                f.na_ondernemersaftrek, bold=True,
                                is_subtotal=True, prefix='=')

                ui.separator().classes('my-2')
                _waterfall_line('MKB-winstvrijstelling',
                                f.mkb_vrijstelling, prefix='-')
                _waterfall_line('Belastbare winst',
                                f.belastbare_winst, bold=True,
                                is_total=True, prefix='=')

    def render_belasting():
        """Render Belasting tab."""
        c = refs['panel_belasting']
        if c is None:
            return
        c.clear()
        f = state['fiscaal']
        data = state['data']
        if f is None or data is None:
            return
        jaar = state['jaar']
        box3 = state['box3']
        ew_naar_partner = data['ew_naar_partner']
        woz = data['woz']
        aov = data['aov']
        lijfrente = data.get('lijfrente', 0)
        hypotheekrente = data['hypotheekrente']

        with c:
            with ui.card().classes('w-full'):
                ui.label(f'Inkomstenbelasting {jaar}').classes(
                    'text-subtitle1 text-bold')

                # Verzamelinkomen breakdown
                _waterfall_line('Belastbare winst', f.belastbare_winst)
                if not ew_naar_partner and woz > 0:
                    ew_pct = state['params_dict'].get('ew_forfait_pct', 0.35)
                    _waterfall_line(
                        f'Eigenwoningforfait ({ew_pct}% van {format_euro(woz)})',
                        f.ew_forfait, indent=1, prefix='+')
                    _waterfall_line('Hypotheekrente', hypotheekrente,
                                    indent=1, prefix='-')
                    if f.hillen_aftrek > 0:
                        _waterfall_line('Wet Hillen aftrek',
                                        f.hillen_aftrek, indent=1, prefix='-')
                    _waterfall_line('Eigenwoningsaldo', f.ew_saldo,
                                    indent=1, prefix='=')
                elif ew_naar_partner and woz > 0:
                    ui.label('Eigen woning \u2192 partner').classes(
                        'text-caption text-grey-7')
                if aov > 0:
                    _waterfall_line('AOV premie', aov, prefix='-')
                if lijfrente > 0:
                    _waterfall_line('Lijfrentepremie', lijfrente, prefix='-')
                _waterfall_line('Verzamelinkomen', f.verzamelinkomen,
                                bold=True, is_subtotal=True, prefix='=')

                ui.separator().classes('my-2')
                _waterfall_line('Bruto inkomstenbelasting', f.bruto_ib)
                if f.tariefsaanpassing > 0:
                    _waterfall_line('Tariefsaanpassing (beperking aftrek)',
                                    f.tariefsaanpassing, prefix='+')

                # IB/PVV split
                with ui.expansion('IB/PVV uitsplitsing').classes(
                        'w-full text-caption').props('dense'):
                    _waterfall_line('IB (excl. premies)', f.ib_alleen)
                    _waterfall_line('PVV premies volksverzekeringen',
                                    f.pvv, bold=True)
                    pd = state['params_dict']
                    _waterfall_line(
                        f'AOW ({pd.get("pvv_aow_pct", 17.90):.2f}%)',
                        f.pvv_aow, indent=1)
                    _waterfall_line(
                        f'Anw ({pd.get("pvv_anw_pct", 0.10):.2f}%)',
                        f.pvv_anw, indent=1)
                    _waterfall_line(
                        f'Wlz ({pd.get("pvv_wlz_pct", 9.65):.2f}%)',
                        f.pvv_wlz, indent=1)

                _waterfall_line('Algemene heffingskorting', f.ahk, prefix='-')
                _waterfall_line('Arbeidskorting', f.arbeidskorting, prefix='-')
                _waterfall_line('Netto inkomstenbelasting', f.netto_ib,
                                bold=True, is_subtotal=True, prefix='=')

                ui.separator().classes('my-2')
                _waterfall_line('ZVW-bijdrage', f.zvw)

            # Box 3
            if box3 and (box3.totaal_bezittingen > 0 or box3.schulden > 0):
                with ui.card().classes('w-full'):
                    ui.label(f'Box 3 \u2014 Sparen en beleggen {jaar}').classes(
                        'text-subtitle1 text-bold')
                    _waterfall_line('Banktegoeden', box3.bank_saldo)
                    _waterfall_line('Overige bezittingen',
                                    box3.overige_bezittingen)
                    _waterfall_line('Totaal bezittingen',
                                    box3.totaal_bezittingen, bold=True,
                                    is_subtotal=True)
                    _waterfall_line('Schulden', box3.schulden)
                    ui.separator().classes('my-1')
                    _waterfall_line('Forfaitair rendement bank',
                                    box3.rendement_bank)
                    _waterfall_line('Forfaitair rendement overig',
                                    box3.rendement_overig)
                    _waterfall_line('Forfaitair rendement schuld',
                                    box3.rendement_schuld)
                    _waterfall_line('Totaal rendement',
                                    box3.totaal_rendement, bold=True)
                    ui.separator().classes('my-1')
                    _waterfall_line('Heffingsvrij vermogen', box3.heffingsvrij)
                    _waterfall_line('Grondslag', box3.grondslag)
                    _waterfall_line('Box 3 belasting', box3.belasting,
                                    bold=True, is_total=True)

            # Result card
            box3_belasting = box3.belasting if box3 else 0
            totaal_resultaat = f.resultaat + box3_belasting
            with ui.card().classes('w-full'):
                ui.label('Resultaat').classes('text-subtitle1 text-bold')

                # Sub-results
                if f.voorlopige_aanslag > 0 or f.voorlopige_aanslag_zvw > 0:
                    def _result_line(label, bedrag):
                        color = ('text-positive' if bedrag < 0
                                 else 'text-negative' if bedrag > 0 else '')
                        prefix = 'terug' if bedrag < 0 else 'bij' if bedrag > 0 else ''
                        tekst = (f'{format_euro(abs(bedrag))} ({prefix})'
                                 if bedrag != 0 else format_euro(0))
                        with ui.row().classes('w-full justify-between items-center'):
                            ui.label(label).classes('text-body2')
                            ui.label(tekst).classes(f'text-body2 {color}')

                    _result_line(
                        f'IB: {format_euro(f.netto_ib)} \u2212 VA {format_euro(f.voorlopige_aanslag)}',
                        f.resultaat_ib)
                    _result_line(
                        f'ZVW: {format_euro(f.zvw)} \u2212 VA {format_euro(f.voorlopige_aanslag_zvw)}',
                        f.resultaat_zvw)
                    if box3_belasting > 0:
                        _result_line('Box 3 belasting', box3_belasting)
                    ui.separator().classes('my-2')

                # Grand total
                if totaal_resultaat < 0:
                    border_color = '#059669'
                    text_class = 'text-positive'
                    res_label = f'{format_euro(abs(totaal_resultaat))} terug te ontvangen'
                elif totaal_resultaat > 0:
                    border_color = '#DC2626'
                    text_class = 'text-negative'
                    res_label = f'{format_euro(totaal_resultaat)} bij te betalen'
                else:
                    border_color = '#64748B'
                    text_class = ''
                    res_label = format_euro(0)

                with ui.row().classes('w-full justify-between items-center q-pa-sm') \
                        .style(f'border-left: 5px solid {border_color}; '
                               'background: linear-gradient(90deg, #f8fafc 0%, transparent 100%)'):
                    ui.label('Totaal').classes('text-bold text-h6')
                    ui.label(res_label).classes(f'text-bold text-h6 {text_class}')

    def render_balans():
        """Render Balans tab."""
        c = refs['panel_balans']
        if c is None:
            return
        c.clear()
        balans = state['balans']
        if balans is None:
            return
        jaar = state['jaar']

        with c:
            # Activa / Passiva side by side
            with ui.row().classes('w-full gap-6 flex-wrap'):
                with ui.card().classes('flex-1 min-w-80'):
                    ui.label('Activa').classes('text-subtitle1 text-bold')
                    ui.label('Vaste activa').classes(
                        'text-caption text-grey-7 q-mt-sm')
                    _waterfall_line('Materi\u00eble vaste activa', balans['mva'])
                    ui.label('Vlottende activa').classes(
                        'text-caption text-grey-7 q-mt-sm')
                    _waterfall_line('Debiteuren', balans['debiteuren'])
                    _waterfall_line('Nog te factureren', balans['nog_te_factureren'])
                    _waterfall_line('Overige vorderingen', balans['overige_vorderingen'])
                    ui.label('Liquide middelen').classes(
                        'text-caption text-grey-7 q-mt-sm')
                    _waterfall_line('Bank', balans['bank_saldo'])
                    ui.separator().classes('my-1')
                    _waterfall_line('Totaal activa', balans['totaal_activa'],
                                    bold=True, is_total=True)

                with ui.card().classes('flex-1 min-w-80'):
                    ui.label('Passiva').classes('text-subtitle1 text-bold')
                    ui.label('Eigen vermogen').classes(
                        'text-caption text-grey-7 q-mt-sm')
                    _waterfall_line('Ondernemingsvermogen', balans['eigen_vermogen'])
                    ui.label('Kortlopende schulden').classes(
                        'text-caption text-grey-7 q-mt-sm')
                    _waterfall_line('Crediteuren', balans['crediteuren'])
                    _waterfall_line('Overige schulden', balans['overige_schulden'])
                    ui.separator().classes('my-1')
                    totaal_passiva = round(balans['eigen_vermogen'] + balans['totaal_schulden'], 2)
                    _waterfall_line('Totaal passiva', totaal_passiva,
                                    bold=True, is_total=True)

            # Balance check indicator
            verschil = round(balans['totaal_activa'] - (balans['eigen_vermogen'] + balans['totaal_schulden']), 2)
            if abs(verschil) < 0.01:
                with ui.row().classes('items-center gap-2 q-mt-sm'):
                    ui.icon('check_circle', color='positive')
                    ui.label('Balans sluit').classes('text-positive')
            else:
                with ui.row().classes('items-center gap-2 q-mt-sm'):
                    ui.icon('warning', color='negative')
                    ui.label(f'Balans verschil: {format_euro(verschil)}').classes('text-negative')

            # Kapitaalsvergelijking
            with ui.card().classes('w-full q-mt-md'):
                ui.label(f'Kapitaalsvergelijking {jaar}').classes(
                    'text-subtitle1 text-bold')
                _waterfall_line('Begin vermogen', balans['begin_vermogen'])
                _waterfall_line('Winst', balans['winst'], prefix='+')
                _waterfall_line('Priv\u00e9 onttrekkingen',
                                balans['prive_onttrekkingen'], prefix='-')
                _waterfall_line('Eind vermogen', balans['eigen_vermogen'],
                                bold=True, is_total=True, prefix='=')

    def render_controles():
        """Render Controles tab."""
        c = refs['panel_controles']
        if c is None:
            return
        c.clear()
        f = state['fiscaal']
        if f is None:
            return
        balans = state['balans']

        with c:
            with ui.card().classes('w-full'):
                ui.label('Controles').classes('text-subtitle1 text-bold')

                # Kosten/omzet ratio
                ratio = f.kosten_omzet_ratio
                ratio_color = ('positive' if ratio <= 25
                               else 'warning' if ratio <= 35
                               else 'negative')
                with ui.row().classes('items-center gap-2'):
                    ui.label('Kosten/omzet ratio:')
                    ui.badge(f'{ratio:.1f}%', color=ratio_color).classes('text-sm')

                # Urencriterium
                uren_val = f.uren_criterium
                gehaald = f.uren_criterium_gehaald
                uren_color = 'positive' if gehaald else 'negative'
                uren_text = f'{uren_val:.0f} uur'
                uren_text += ' (gehaald)' if gehaald else ' (NIET gehaald)'
                with ui.row().classes('items-center gap-2'):
                    ui.label('Urencriterium (\u2265 1.225 uur):')
                    ui.badge(uren_text, color=uren_color).classes('text-sm')

                # Balance check
                if balans:
                    verschil = round(
                        balans['totaal_activa'] - (balans['eigen_vermogen'] + balans['totaal_schulden']), 2)
                    if abs(verschil) < 0.01:
                        with ui.row().classes('items-center gap-2'):
                            ui.label('Balans:')
                            ui.badge('Sluit', color='positive').classes('text-sm')
                    else:
                        with ui.row().classes('items-center gap-2'):
                            ui.label('Balans:')
                            ui.badge(f'Verschil {format_euro(verschil)}',
                                     color='negative').classes('text-sm')

                # Waarschuwingen
                if f.waarschuwingen:
                    ui.separator().classes('my-2')
                    ui.label('Waarschuwingen:').classes('text-bold text-negative')
                    for w in f.waarschuwingen:
                        with ui.row().classes('items-center gap-1'):
                            ui.icon('warning', color='negative').classes('text-sm')
                            ui.label(w).classes('text-negative')

                # Additional checks
                data = state['data']
                if data:
                    va_ib = data['voorlopige_aanslag']
                    va_zvw = data['voorlopige_aanslag_zvw']
                    if va_ib == 0 and va_zvw == 0:
                        with ui.row().classes('items-center gap-1'):
                            ui.icon('info', color='warning').classes('text-sm')
                            ui.label('Geen voorlopige aanslagen ingevuld').classes('text-warning')
                    aov = data['aov']
                    if aov == 0:
                        with ui.row().classes('items-center gap-1'):
                            ui.icon('info', color='warning').classes('text-sm')
                            ui.label('Geen AOV premie opgegeven').classes('text-warning')

            # Fiscal advisory section
            ui.separator().classes('my-3')
            render_fiscaal_advies()

        # Update tab badge
        if refs['tab_controles']:
            if f.waarschuwingen:
                refs['tab_controles'].props('alert="negative"')
            else:
                refs['tab_controles'].props(remove='alert')

    def render_fiscaal_advies():
        """Render fiscal advisory panel within Controles tab."""
        f = state['fiscaal']
        data = state['data']
        if f is None or data is None:
            return
        jaar = state['jaar']
        pd = state['params_dict']

        # --- ZA trajectory ---
        za_bedragen = {2023: 5030, 2024: 3750, 2025: 2470, 2026: 1200, 2027: 900}
        za_actief = pd.get('za_actief', True)

        with ui.card().classes('w-full'):
            ui.label('Fiscaal advies').classes('text-subtitle1 text-bold')
            ui.separator().classes('my-1')

            # ZA info
            with ui.row().classes('items-start gap-2'):
                ui.icon('trending_down', color='primary').classes('q-mt-xs')
                with ui.column().classes('gap-0'):
                    if za_actief and f.uren_criterium_gehaald:
                        ui.label(f'Zelfstandigenaftrek {jaar}: {format_euro(f.zelfstandigenaftrek)}') \
                            .classes('text-body2')
                    elif not f.uren_criterium_gehaald:
                        ui.label('Zelfstandigenaftrek: niet toegepast (urencriterium niet gehaald)') \
                            .classes('text-body2 text-negative')
                    else:
                        ui.label('Zelfstandigenaftrek: uitgeschakeld') \
                            .classes('text-body2 text-grey-7')
                    # Show trajectory
                    toekomst = [f'{j}: {format_euro(b)}'
                                for j, b in sorted(za_bedragen.items()) if j > jaar]
                    if toekomst:
                        ui.label(f'Afbouwpad: {", ".join(toekomst[:3])}') \
                            .classes('text-caption text-grey-7')

            # SA info
            sa_actief = pd.get('sa_actief', False)
            with ui.row().classes('items-start gap-2 q-mt-sm'):
                ui.icon('star', color='primary').classes('q-mt-xs')
                with ui.column().classes('gap-0'):
                    if sa_actief:
                        ui.label(f'Startersaftrek {jaar}: {format_euro(f.startersaftrek)}') \
                            .classes('text-body2')
                    else:
                        ui.label('Startersaftrek: niet toegepast') \
                            .classes('text-body2 text-grey-7')
                    ui.label('Max 3x in eerste 5 jaar als ondernemer. '
                             'Controleer of u nog recht heeft.') \
                        .classes('text-caption text-grey-7')

            # KIA info
            inv_totaal = data['inv_totaal_dit_jaar']
            kia_onder = pd.get('kia_ondergrens', 2901)
            kia_boven = pd.get('kia_bovengrens', 70602)
            with ui.row().classes('items-start gap-2 q-mt-sm'):
                ui.icon('shopping_cart', color='primary').classes('q-mt-xs')
                with ui.column().classes('gap-0'):
                    if inv_totaal >= kia_onder:
                        ui.label(f'KIA: {format_euro(f.kia)} '
                                 f'(28% van {format_euro(inv_totaal)})') \
                            .classes('text-body2 text-positive')
                    elif inv_totaal > 0:
                        ui.label(f'Investeringen {format_euro(inv_totaal)} '
                                 f'onder KIA-grens ({format_euro(kia_onder)})') \
                            .classes('text-body2 text-warning')
                    else:
                        ui.label('Geen investeringen dit jaar').classes('text-body2 text-grey-7')

            # MKB-winstvrijstelling
            with ui.row().classes('items-start gap-2 q-mt-sm'):
                ui.icon('percent', color='primary').classes('q-mt-xs')
                ui.label(f'MKB-winstvrijstelling: {pd.get("mkb_vrijstelling_pct", 0)}% '
                         f'= {format_euro(f.mkb_vrijstelling)}').classes('text-body2')

            # Lijfrente hint
            aov = data['aov']
            lijfrente = data.get('lijfrente', 0)
            with ui.row().classes('items-start gap-2 q-mt-sm'):
                ui.icon('savings', color='primary').classes('q-mt-xs')
                with ui.column().classes('gap-0'):
                    if lijfrente > 0:
                        ui.label(f'Lijfrentepremie: {format_euro(lijfrente)} (vermindert verzamelinkomen)') \
                            .classes('text-body2')
                    elif aov > 0:
                        ui.label('Geen lijfrentepremie opgegeven. '
                                 'Jaarruimte kan extra aftrek opleveren.') \
                            .classes('text-body2 text-warning')
                    else:
                        ui.label('Geen AOV of lijfrentepremie opgegeven.') \
                            .classes('text-body2 text-grey-7')
                    # Jaarruimte hint (approximate)
                    ui.label('Jaarruimte = 30% x (premiegrondslag − AOW-franchise). '
                             'Raadpleeg uw adviseur voor het exacte bedrag.') \
                        .classes('text-caption text-grey-7')

            # Eigen woning
            ew_naar_partner = data['ew_naar_partner']
            woz = data['woz']
            with ui.row().classes('items-start gap-2 q-mt-sm'):
                ui.icon('home', color='primary').classes('q-mt-xs')
                with ui.column().classes('gap-0'):
                    if ew_naar_partner and woz > 0:
                        ui.label(f'Eigen woning toegerekend aan partner '
                                 f'(forfait {format_euro(f.ew_forfait)})') \
                            .classes('text-body2')
                    elif woz > 0:
                        saldo = f.ew_saldo
                        if saldo < 0:
                            ui.label(f'Eigenwoningsaldo: {format_euro(saldo)} (aftrekpost)') \
                                .classes('text-body2 text-positive')
                        else:
                            ui.label(f'Eigenwoningsaldo: {format_euro(saldo)} (bijtelling)') \
                                .classes('text-body2 text-warning')
                    else:
                        ui.label('Geen eigen woning opgegeven').classes('text-body2 text-grey-7')

            # Totaal belastingdruk
            ui.separator().classes('my-2')
            totaal_belasting = f.netto_ib + f.zvw
            druk_pct = round(totaal_belasting / f.winst * 100, 1) if f.winst > 0 else 0
            with ui.row().classes('items-center gap-2'):
                ui.icon('assessment', color='primary')
                ui.label(f'Effectieve belastingdruk: {druk_pct}% '
                         f'(IB {format_euro(f.netto_ib)} + ZVW {format_euro(f.zvw)} '
                         f'= {format_euro(totaal_belasting)} op winst {format_euro(f.winst)})') \
                    .classes('text-body2')

    async def refresh_all():
        """Full recalculate + re-render."""
        ok = await _calculate(state['jaar'])
        if not ok:
            # No params for this year
            if refs['kpi_container']:
                refs['kpi_container'].clear()
                with refs['kpi_container']:
                    ui.label(
                        f"Geen fiscale parameters voor {state['jaar']}. "
                        f"Voeg deze toe via Instellingen."
                    ).classes('text-negative text-subtitle1')
            return
        render_kpis()
        render_data_warnings()
        render_invoer()
        render_wv()
        render_fiscaal()
        render_belasting()
        render_balans()
        render_controles()
        await render_document()

    # === Template rendering (shared between PDF and Document tab) ===

    async def _render_jaarcijfers_html():
        """Render the jaarcijfers HTML from Jinja2 template. Used by both PDF export and document preview."""
        f = state['fiscaal']
        if f is None:
            return None
        jaar = state['jaar']
        data = state['data']
        box3 = state['box3']
        balans = state['balans']
        balans_vorig_jaar = state['balans_vorig_jaar']
        pd = state['params_dict']

        templates_dir = Path(__file__).resolve().parent.parent / 'templates'
        env = Environment(loader=FileSystemLoader(str(templates_dir)))
        env.filters['euro'] = lambda v: format_euro(v) if v is not None else format_euro(0)
        template = env.get_template('jaarafsluiting.html')

        from database import get_bedrijfsgegevens
        bedrijf = await get_bedrijfsgegevens(DB_PATH)

        return template.render(
            jaar=jaar,
            datum=date.today().strftime('%d-%m-%Y'),
            bedrijfsnaam=bedrijf.bedrijfsnaam if bedrijf else '',
            kvk=bedrijf.kvk if bedrijf else '',
            f=f,
            kosten_per_cat=data['kosten_per_cat'],
            totaal_kosten=data['totaal_kosten_alle'],
            activastaat=data['activastaat'],
            totaal_afschrijvingen=data['totaal_afschrijvingen'],
            kosten_excl_inv=data['kosten_excl_inv'],
            aov=data['aov'],
            lijfrente=data.get('lijfrente', 0),
            woz=data['woz'],
            hypotheekrente=data['hypotheekrente'],
            ew_naar_partner=data['ew_naar_partner'],
            box3=box3,
            balans=balans,
            balans_vorig_jaar=balans_vorig_jaar,
            za_actief=pd.get('za_actief', True),
            sa_actief=pd.get('sa_actief', False),
        )

    async def render_document():
        """Render the Document preview tab with inline HTML."""
        c = refs.get('panel_document')
        if c is None:
            return
        c.clear()

        html = await _render_jaarcijfers_html()
        if html is None:
            with c:
                ui.label('Voer eerst een berekening uit').classes('text-grey')
            return

        # Strip @page CSS rules (WeasyPrint-only) and page-break divs for inline display
        # Remove @page blocks
        html_preview = re.sub(r'@page[^{]*\{[^}]*(\{[^}]*\}[^}]*)*\}', '', html)
        # Replace page-break divs with visual separators
        html_preview = html_preview.replace(
            '<div class="page-break"></div>',
            '<hr style="border: none; border-top: 2px dashed #e2e8f0; margin: 8mm 0;">')

        with c:
            # Document container styled like a paper document
            with ui.column().classes('w-full items-center'):
                with ui.element('div').style(
                    'background: white; max-width: 210mm; width: 100%; '
                    'padding: 15mm 18mm; box-shadow: 0 2px 8px rgba(0,0,0,0.12); '
                    'border-radius: 4px; margin: 8px 0;'
                ):
                    ui.html(html_preview, sanitize=False)

    # === PDF Export ===

    async def export_pdf():
        """Generate PDF of the jaarafsluiting."""
        html = await _render_jaarcijfers_html()
        if html is None:
            ui.notify('Voer eerst een berekening uit', type='warning')
            return
        jaar = state['jaar']

        from weasyprint import HTML
        output_dir = DB_PATH.parent / 'jaarafsluiting'
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / f'jaarafsluiting_{jaar}.pdf'
        HTML(string=html).write_pdf(str(pdf_path))

        ui.notify(f'PDF gegenereerd: jaarafsluiting_{jaar}.pdf', type='positive')
        ui.download.file(str(pdf_path))

    # === PAGE LAYOUT ===

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):

        # Header row
        with ui.row().classes('w-full items-center gap-4'):
            ui.label('Jaarafsluiting').classes('text-h5') \
                .style('color: #0F172A; font-weight: 700')
            ui.space()
            jaar_select = ui.select(
                {j: str(j) for j in jaren},
                label='Jaar', value=vorig_jaar,
            ).classes('w-32')

            async def on_jaar_change():
                state['jaar'] = jaar_select.value
                await refresh_all()

            jaar_select.on_value_change(lambda _: on_jaar_change())

            ui.button(
                'Exporteer PDF', icon='picture_as_pdf',
                on_click=export_pdf,
            ).props('outline color=primary')

        # KPI strip
        refs['kpi_container'] = ui.row().classes('w-full')

        # Data warnings banner
        refs['warnings_container'] = ui.column().classes('w-full')

        # Tabs
        with ui.tabs().classes('w-full') as tabs:
            tab_invoer = ui.tab('Invoer', icon='edit')
            tab_wv = ui.tab('W&V', icon='receipt')
            tab_fiscaal = ui.tab('Fiscaal', icon='calculate')
            tab_belasting = ui.tab('Belasting', icon='account_balance')
            tab_balans = ui.tab('Balans', icon='balance')
            tab_controles = ui.tab('Controles', icon='verified')
            tab_document = ui.tab('Document', icon='description')

        refs['tab_invoer'] = tab_invoer
        refs['tab_controles'] = tab_controles

        with ui.tab_panels(tabs, value=tab_invoer).classes('w-full'):
            with ui.tab_panel(tab_invoer):
                refs['panel_invoer'] = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_wv):
                refs['panel_wv'] = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_fiscaal):
                refs['panel_fiscaal'] = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_belasting):
                refs['panel_belasting'] = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_balans):
                refs['panel_balans'] = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_controles):
                refs['panel_controles'] = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_document):
                refs['panel_document'] = ui.column().classes('w-full gap-4')

    # Auto-calculate on page load
    await refresh_all()
