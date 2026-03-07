"""Jaarafsluiting pagina — fiscale berekeningen + rapporten."""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from nicegui import ui

from components.fiscal_utils import (
    bereken_balans, fetch_fiscal_data, fiscale_params_to_dict,
)
from components.layout import create_layout
from components.utils import format_euro
from database import (
    update_balans_inputs,
    update_ib_inputs,
    DB_PATH,
)
from fiscal.berekeningen import FiscaalResultaat, bereken_box3, bereken_volledig


@ui.page('/jaarafsluiting')
async def jaarafsluiting_page():
    create_layout('Jaarafsluiting', '/jaarafsluiting')

    # --- State ---
    huidig_jaar = date.today().year
    jaren = list(range(huidig_jaar, 2022, -1))  # e.g. 2026 down to 2023
    gekozen_jaar = {'value': huidig_jaar}

    # References for dynamic containers and IB input fields
    result_container = {'ref': None}
    ib_inputs = {'aov': None, 'woz': None, 'hypotheek': None, 'voorlopig': None,
                  'voorlopig_zvw': None, 'ew_partner': None}
    balans_inputs = {'bank': None, 'crediteuren': None,
                      'overige_vorderingen': None, 'overige_schulden': None}

    # State that persists across bereken/herbereken calls
    berekening_state = {
        'omzet': 0.0,
        'kosten': 0.0,
        'afschrijvingen_totaal': 0.0,
        'representatie': 0.0,
        'investeringen_dit_jaar': 0.0,
        'uren': 0.0,
        'params_dict': {},
        'kosten_per_cat': [],
        'activastaat': [],
        'totaal_kosten_alle': 0.0,
    }

    # --- Helper rendering functions ---

    def _wv_line(label: str, value: float, prefix: str = '',
                 bold: bool = False):
        """Render a W&V line with label and euro value."""
        css = 'text-bold' if bold else ''
        with ui.row().classes('w-full justify-between'):
            text = f'{prefix}  {label}' if prefix else label
            ui.label(text).classes(css)
            ui.label(format_euro(value)).classes(f'{css} text-right')

    def _waterfall_line(label: str, value: float, bold: bool = False):
        """Render a fiscal waterfall line."""
        css = 'text-bold' if bold else ''
        with ui.row().classes('w-full justify-between'):
            ui.label(label).classes(css)
            ui.label(format_euro(value)).classes(f'{css} text-right')

    def _render_resultaat(
        container, jaar: int, fiscaal: FiscaalResultaat,
        kosten_per_cat: list[dict], activastaat: list[dict],
        totaal_kosten_alle: float, kosten_excl_inv: float,
        totaal_afschrijvingen: float,
        aov: float, woz: float, hypotheekrente: float,
        voorlopige_aanslag: float,
        voorlopige_aanslag_zvw: float = 0,
        ew_naar_partner: bool = True,
        box3_result=None,
        balans_data: dict = None,
    ):
        """Render all result sections into the container."""
        container.clear()

        with container:

            # === Section 1: W&V-rekening ===
            with ui.card().classes('w-full'):
                ui.label(f'1. Winst- en verliesrekening {jaar}').classes(
                    'text-subtitle1 text-bold')

                _wv_line('Netto-omzet', fiscaal.omzet)
                _wv_line('Bedrijfslasten (excl. investeringen)',
                         kosten_excl_inv, prefix='-/-')
                _wv_line('Afschrijvingen', totaal_afschrijvingen,
                         prefix='-/-')
                ui.separator()
                _wv_line('Winst', fiscaal.winst, bold=True)

                # Kosten per categorie (expandable)
                with ui.expansion('Kosten per categorie').classes(
                        'w-full text-caption').props('dense'):
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
                            ui.label(format_euro(totaal_kosten_alle)).classes('text-bold')
                    else:
                        ui.label('Geen uitgaven gevonden.').classes('text-grey')

            # === Section 2: Activastaat ===
            with ui.card().classes('w-full'):
                ui.label(f'2. Activastaat {jaar}').classes(
                    'text-subtitle1 text-bold')

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
                        ui.label(format_euro(totaal_afschrijvingen)).classes(
                            'text-bold')
                else:
                    ui.label('Geen investeringen / afschrijvingen.').classes(
                        'text-grey')

            # === Section 3: Fiscale winstberekening ===
            with ui.card().classes('w-full'):
                ui.label(f'3. Fiscale winstberekening {jaar}').classes(
                    'text-subtitle1 text-bold')

                _waterfall_line('Winst jaarrekening', fiscaal.winst)
                _waterfall_line('+ Bijtelling representatie (20%)',
                                fiscaal.repr_bijtelling)
                _waterfall_line(
                    '- Kleinschaligheidsinvesteringsaftrek (KIA)',
                    fiscaal.kia)
                ui.separator().classes('my-1')
                _waterfall_line('= Fiscale winst',
                                fiscaal.fiscale_winst, bold=True)

                ui.separator().classes('my-1')
                _waterfall_line('- Zelfstandigenaftrek',
                                fiscaal.zelfstandigenaftrek)
                if fiscaal.startersaftrek > 0:
                    _waterfall_line('- Startersaftrek',
                                    fiscaal.startersaftrek)
                _waterfall_line('= Na ondernemersaftrek',
                                fiscaal.na_ondernemersaftrek, bold=True)

                ui.separator().classes('my-1')
                _waterfall_line('- MKB-winstvrijstelling',
                                fiscaal.mkb_vrijstelling)
                _waterfall_line('= Belastbare winst',
                                fiscaal.belastbare_winst, bold=True)

            # === Section 4: IB-berekening ===
            with ui.card().classes('w-full'):
                ui.label(f'4. Inkomstenbelasting {jaar}').classes(
                    'text-subtitle1 text-bold')

                # Manual input fields for personal deductions
                ui.label(
                    'Persoonlijke gegevens (Box 1 aftrekposten)'
                ).classes('text-caption text-grey q-mt-sm')
                with ui.row().classes('w-full items-end gap-4 flex-wrap'):
                    ib_inputs['aov'] = ui.number(
                        'AOV premie (\u20ac)', value=aov,
                        format='%.2f', min=0, step=100,
                    ).classes('w-44')
                    ib_inputs['woz'] = ui.number(
                        'WOZ waarde (\u20ac)', value=woz,
                        format='%.0f', min=0, step=1000,
                    ).classes('w-44')
                    ib_inputs['hypotheek'] = ui.number(
                        'Hypotheekrente (\u20ac)', value=hypotheekrente,
                        format='%.2f', min=0, step=100,
                    ).classes('w-44')
                    ib_inputs['voorlopig'] = ui.number(
                        'Voorlopige aanslag IB (\u20ac)',
                        value=voorlopige_aanslag,
                        format='%.2f', min=0, step=100,
                    ).classes('w-52')
                    ib_inputs['voorlopig_zvw'] = ui.number(
                        'Voorlopige aanslag ZVW (\u20ac)',
                        value=voorlopige_aanslag_zvw,
                        format='%.2f', min=0, step=100,
                    ).classes('w-52')
                ib_inputs['ew_partner'] = ui.checkbox(
                    'Eigen woning toerekenen aan partner',
                    value=ew_naar_partner,
                ).classes('q-mt-sm')
                with ui.row().classes('w-full items-end gap-4 flex-wrap'):
                    ui.button(
                        'Herbereken', icon='refresh',
                        on_click=herbereken,
                    ).props('color=primary')

                ui.separator().classes('my-2')

                # Verzamelinkomen breakdown
                _waterfall_line('Belastbare winst',
                                fiscaal.belastbare_winst)
                if not ew_naar_partner and woz > 0:
                    ew_pct = berekening_state['params_dict'].get('ew_forfait_pct', 0.35)
                    _waterfall_line(
                        f'Eigenwoningforfait ({ew_pct}% van {format_euro(woz)})',
                        fiscaal.ew_forfait)
                    _waterfall_line('- Hypotheekrente', hypotheekrente)
                    if fiscaal.hillen_aftrek > 0:
                        _waterfall_line('- Wet Hillen aftrek',
                                        fiscaal.hillen_aftrek)
                    _waterfall_line('= Eigenwoningsaldo', fiscaal.ew_saldo)
                elif ew_naar_partner and woz > 0:
                    ui.label('Eigen woning \u2192 partner').classes(
                        'text-caption text-grey-7')
                if aov > 0:
                    _waterfall_line('- AOV premie', aov)
                _waterfall_line('Verzamelinkomen',
                                fiscaal.verzamelinkomen, bold=True)

                ui.separator().classes('my-1')
                _waterfall_line('Bruto inkomstenbelasting',
                                fiscaal.bruto_ib)
                if fiscaal.tariefsaanpassing > 0:
                    _waterfall_line('+ Tariefsaanpassing (beperking aftrek)',
                                    fiscaal.tariefsaanpassing)

                # IB/PVV split (expandable)
                with ui.expansion('IB/PVV uitsplitsing').classes(
                        'w-full text-caption').props('dense'):
                    _waterfall_line('IB (excl. premies)',
                                    fiscaal.ib_alleen)
                    _waterfall_line('PVV premies volksverzekeringen',
                                    fiscaal.pvv, bold=True)
                    _waterfall_line('  - AOW premie (17,90%)',
                                    fiscaal.pvv_aow)
                    _waterfall_line('  - Anw premie (0,10%)',
                                    fiscaal.pvv_anw)
                    _waterfall_line('  - Wlz premie (9,65%)',
                                    fiscaal.pvv_wlz)

                _waterfall_line('- Algemene heffingskorting',
                                fiscaal.ahk)
                _waterfall_line('- Arbeidskorting',
                                fiscaal.arbeidskorting)
                _waterfall_line('= Netto inkomstenbelasting',
                                fiscaal.netto_ib, bold=True)

                ui.separator().classes('my-1')
                _waterfall_line('ZVW-bijdrage', fiscaal.zvw)

                # Box 3 result line
                if box3_result and box3_result.belasting > 0:
                    _waterfall_line('Box 3 belasting', box3_result.belasting)

                ui.separator().classes('my-2')

                # Separate IB and ZVW results
                def _result_line(label, bedrag):
                    color = ('text-positive' if bedrag < 0
                             else 'text-negative' if bedrag > 0
                             else '')
                    prefix = 'terug' if bedrag < 0 else 'bij' if bedrag > 0 else ''
                    tekst = (f'{format_euro(abs(bedrag))} ({prefix})'
                             if bedrag != 0 else format_euro(0))
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label(label).classes('text-body2')
                        ui.label(tekst).classes(f'text-body2 {color}')

                if fiscaal.voorlopige_aanslag > 0 or fiscaal.voorlopige_aanslag_zvw > 0:
                    ui.label('Resultaat').classes('text-subtitle2 q-mt-sm')
                    _result_line(
                        f'IB: {format_euro(fiscaal.netto_ib)} \u2212 VA '
                        f'{format_euro(fiscaal.voorlopige_aanslag)}',
                        fiscaal.resultaat_ib)
                    _result_line(
                        f'ZVW: {format_euro(fiscaal.zvw)} \u2212 VA '
                        f'{format_euro(fiscaal.voorlopige_aanslag_zvw)}',
                        fiscaal.resultaat_zvw)
                    ui.separator().classes('my-1')

                # Total result (IB + ZVW + Box 3)
                box3_belasting = box3_result.belasting if box3_result else 0
                totaal_resultaat = fiscaal.resultaat + box3_belasting
                if totaal_resultaat < 0:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Totaal terug te ontvangen').classes(
                            'text-bold text-h6')
                        ui.label(format_euro(abs(totaal_resultaat))).classes(
                            'text-bold text-h6 text-positive')
                elif totaal_resultaat > 0:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Totaal bij te betalen').classes(
                            'text-bold text-h6')
                        ui.label(format_euro(totaal_resultaat)).classes(
                            'text-bold text-h6 text-negative')
                else:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Resultaat').classes('text-bold text-h6')
                        ui.label(format_euro(0)).classes('text-bold text-h6')

            # === Section 5: Box 3 ===
            if box3_result:
                with ui.card().classes('w-full'):
                    ui.label(f'5. Box 3 — Sparen en beleggen {jaar}').classes(
                        'text-subtitle1 text-bold')

                    if box3_result.totaal_bezittingen > 0 or box3_result.schulden > 0:
                        _waterfall_line('Banktegoeden', box3_result.bank_saldo)
                        _waterfall_line('Overige bezittingen',
                                        box3_result.overige_bezittingen)
                        _waterfall_line('Totaal bezittingen',
                                        box3_result.totaal_bezittingen, bold=True)
                        _waterfall_line('Schulden', box3_result.schulden)
                        ui.separator().classes('my-1')
                        _waterfall_line('Forfaitair rendement bank',
                                        box3_result.rendement_bank)
                        _waterfall_line('Forfaitair rendement overig',
                                        box3_result.rendement_overig)
                        _waterfall_line('Forfaitair rendement schuld',
                                        box3_result.rendement_schuld)
                        _waterfall_line('Totaal rendement',
                                        box3_result.totaal_rendement, bold=True)
                        ui.separator().classes('my-1')
                        _waterfall_line('Heffingsvrij vermogen',
                                        box3_result.heffingsvrij)
                        _waterfall_line('Grondslag', box3_result.grondslag)
                        _waterfall_line('Box 3 belasting',
                                        box3_result.belasting, bold=True)
                    else:
                        ui.label('Geen Box 3 vermogen opgegeven.').classes(
                            'text-grey')

            # === Section 6: Balans ===
            if balans_data:
                with ui.card().classes('w-full'):
                    ui.label(f'6. Balans per 31-12-{jaar}').classes(
                        'text-subtitle1 text-bold')

                    with ui.row().classes('w-full gap-8'):
                        # Activa column
                        with ui.column().classes('flex-1'):
                            ui.label('Activa').classes('text-subtitle2 text-bold')
                            ui.label('Vaste activa').classes(
                                'text-caption text-grey-7 q-mt-sm')
                            _waterfall_line('Materiële vaste activa',
                                            balans_data['mva'])
                            ui.label('Vlottende activa').classes(
                                'text-caption text-grey-7 q-mt-sm')
                            _waterfall_line('Debiteuren',
                                            balans_data['debiteuren'])
                            _waterfall_line('Nog te factureren',
                                            balans_data['nog_te_factureren'])
                            _waterfall_line('Overige vorderingen',
                                            balans_data['overige_vorderingen'])
                            ui.label('Liquide middelen').classes(
                                'text-caption text-grey-7 q-mt-sm')
                            _waterfall_line('Bank',
                                            balans_data['bank_saldo'])
                            ui.separator().classes('my-1')
                            _waterfall_line('Totaal activa',
                                            balans_data['totaal_activa'],
                                            bold=True)

                        # Passiva column
                        with ui.column().classes('flex-1'):
                            ui.label('Passiva').classes('text-subtitle2 text-bold')
                            ui.label('Eigen vermogen').classes(
                                'text-caption text-grey-7 q-mt-sm')
                            _waterfall_line('Ondernemingsvermogen',
                                            balans_data['eigen_vermogen'])
                            ui.label('Kortlopende schulden').classes(
                                'text-caption text-grey-7 q-mt-sm')
                            _waterfall_line('Crediteuren',
                                            balans_data['crediteuren'])
                            _waterfall_line('Overige schulden',
                                            balans_data['overige_schulden'])
                            ui.separator().classes('my-1')
                            _waterfall_line(
                                'Totaal passiva',
                                round(balans_data['eigen_vermogen']
                                      + balans_data['totaal_schulden'], 2),
                                bold=True)

                    # Manual balance sheet inputs
                    ui.separator().classes('my-2')
                    ui.label('Handmatige invoer (einde boekjaar)').classes(
                        'text-caption text-grey')
                    with ui.row().classes('w-full items-end gap-4 flex-wrap'):
                        balans_inputs['bank'] = ui.number(
                            'Bank saldo (\u20ac)',
                            value=balans_data['bank_saldo'],
                            format='%.2f', step=100,
                        ).classes('w-44')
                        balans_inputs['crediteuren'] = ui.number(
                            'Crediteuren (\u20ac)',
                            value=balans_data['crediteuren'],
                            format='%.2f', min=0, step=100,
                        ).classes('w-44')
                        balans_inputs['overige_vorderingen'] = ui.number(
                            'Overige vorderingen (\u20ac)',
                            value=balans_data['overige_vorderingen'],
                            format='%.2f', min=0, step=100,
                        ).classes('w-44')
                        balans_inputs['overige_schulden'] = ui.number(
                            'Overige schulden (\u20ac)',
                            value=balans_data['overige_schulden'],
                            format='%.2f', min=0, step=100,
                        ).classes('w-44')
                        ui.button(
                            'Opslaan balans', icon='save',
                            on_click=save_balans,
                        ).props('color=primary')

            # === Section 7: Kapitaalsvergelijking ===
            if balans_data:
                with ui.card().classes('w-full'):
                    ui.label(f'7. Kapitaalsvergelijking {jaar}').classes(
                        'text-subtitle1 text-bold')
                    _waterfall_line('Begin vermogen',
                                    balans_data['begin_vermogen'])
                    _waterfall_line('+ Winst', balans_data['winst'])
                    _waterfall_line('- Privé onttrekkingen',
                                    balans_data['prive_onttrekkingen'])
                    ui.separator().classes('my-1')
                    _waterfall_line('= Eind vermogen',
                                    balans_data['eigen_vermogen'], bold=True)

            # === Section 8: Controles ===
            with ui.card().classes('w-full'):
                section_nr = '8' if balans_data else '5'
                ui.label(f'{section_nr}. Controles').classes(
                    'text-subtitle1 text-bold')

                # Kosten/omzet ratio
                ratio = fiscaal.kosten_omzet_ratio
                ratio_color = ('positive' if ratio <= 25
                               else 'warning' if ratio <= 35
                               else 'negative')
                with ui.row().classes('items-center gap-2'):
                    ui.label('Kosten/omzet ratio:')
                    ui.badge(f'{ratio:.1f}%', color=ratio_color).classes('text-sm')

                # Urencriterium
                uren_val = fiscaal.uren_criterium
                gehaald = fiscaal.uren_criterium_gehaald
                uren_color = 'positive' if gehaald else 'negative'
                uren_text = f'{uren_val:.0f} uur'
                uren_text += ' (gehaald)' if gehaald else ' (NIET gehaald)'
                with ui.row().classes('items-center gap-2'):
                    ui.label('Urencriterium (>= 1.225 uur):')
                    ui.badge(uren_text, color=uren_color).classes('text-sm')

                # Waarschuwingen
                if fiscaal.waarschuwingen:
                    ui.separator().classes('my-2')
                    ui.label('Waarschuwingen:').classes(
                        'text-bold text-negative')
                    for w in fiscaal.waarschuwingen:
                        with ui.row().classes('items-center gap-1'):
                            ui.icon('warning', color='negative').classes(
                                'text-sm')
                            ui.label(w).classes('text-negative')

    # --- Save balans handler ---

    async def save_balans():
        """Save balance sheet manual inputs to DB and re-render."""
        jaar = gekozen_jaar['value']
        await update_balans_inputs(
            DB_PATH, jaar=jaar,
            balans_bank_saldo=float(balans_inputs['bank'].value or 0),
            balans_crediteuren=float(balans_inputs['crediteuren'].value or 0),
            balans_overige_vorderingen=float(
                balans_inputs['overige_vorderingen'].value or 0),
            balans_overige_schulden=float(
                balans_inputs['overige_schulden'].value or 0),
        )
        ui.notify('Balans opgeslagen', type='positive')
        await bereken()

    # --- Bereken handler ---

    async def bereken(aov: float = None, woz: float = None,
                      hypotheekrente: float = None,
                      voorlopige_aanslag: float = None,
                      voorlopige_aanslag_zvw: float = None):
        """Fetch data, run fiscal engine, and render all sections."""
        jaar = gekozen_jaar['value']
        container = result_container['ref']
        if container is None:
            return

        # Fetch all fiscal data via shared utility
        data = await fetch_fiscal_data(DB_PATH, jaar)
        if data is None:
            container.clear()
            with container:
                ui.label(
                    f'Geen fiscale parameters gevonden voor {jaar}. '
                    f'Voeg deze toe via Instellingen.'
                ).classes('text-negative text-subtitle1')
            return

        # Use DB values if not explicitly provided
        if aov is None:
            aov = data['aov']
        if woz is None:
            woz = data['woz']
        if hypotheekrente is None:
            hypotheekrente = data['hypotheekrente']
        if voorlopige_aanslag is None:
            voorlopige_aanslag = data['voorlopige_aanslag']
        if voorlopige_aanslag_zvw is None:
            voorlopige_aanslag_zvw = data['voorlopige_aanslag_zvw']

        ew_naar_partner = data['ew_naar_partner']
        params_dict = data['params_dict']

        # Save state for herbereken
        berekening_state.update({
            'omzet': data['omzet'],
            'kosten': data['kosten_excl_inv'],
            'afschrijvingen_totaal': data['totaal_afschrijvingen'],
            'representatie': data['representatie'],
            'investeringen_dit_jaar': data['inv_totaal_dit_jaar'],
            'uren': data['uren'],
            'params_dict': params_dict,
            'kosten_per_cat': data['kosten_per_cat'],
            'activastaat': data['activastaat'],
            'totaal_kosten_alle': data['totaal_kosten_alle'],
            'ew_naar_partner': ew_naar_partner,
        })

        # Run fiscal engine
        fiscaal = bereken_volledig(
            omzet=data['omzet'],
            kosten=data['kosten_excl_inv'],
            afschrijvingen=data['totaal_afschrijvingen'],
            representatie=data['representatie'],
            investeringen_totaal=data['inv_totaal_dit_jaar'],
            uren=data['uren'],
            params=params_dict,
            aov=aov,
            woz=woz,
            hypotheekrente=hypotheekrente,
            voorlopige_aanslag=voorlopige_aanslag,
            voorlopige_aanslag_zvw=voorlopige_aanslag_zvw,
            ew_naar_partner=ew_naar_partner,
        )

        # Box 3
        box3_result = bereken_box3(params_dict)

        # Balance sheet
        # Get previous year's vermogen for kapitaalsvergelijking
        prev_data = await fetch_fiscal_data(DB_PATH, jaar - 1)
        begin_vermogen = 0.0
        if prev_data:
            prev_balans = await bereken_balans(
                DB_PATH, jaar - 1, prev_data['activastaat'],
                winst=0, begin_vermogen=0)
            begin_vermogen = prev_balans['eigen_vermogen']

        balans_data = await bereken_balans(
            DB_PATH, jaar, data['activastaat'],
            winst=fiscaal.winst, begin_vermogen=begin_vermogen)

        # Render result
        _render_resultaat(
            container, jaar, fiscaal, data['kosten_per_cat'],
            data['activastaat'], data['totaal_kosten_alle'],
            data['kosten_excl_inv'], data['totaal_afschrijvingen'],
            aov, woz, hypotheekrente, voorlopige_aanslag,
            voorlopige_aanslag_zvw=voorlopige_aanslag_zvw,
            ew_naar_partner=ew_naar_partner,
            box3_result=box3_result,
            balans_data=balans_data,
        )

    async def herbereken():
        """Re-run fiscal engine with updated IB-input values, saving to DB."""
        s = berekening_state
        if not s['params_dict']:
            ui.notify('Voer eerst een berekening uit', type='warning')
            return

        aov_val = float(ib_inputs['aov'].value or 0)
        woz_val = float(ib_inputs['woz'].value or 0)
        hyp_val = float(ib_inputs['hypotheek'].value or 0)
        va_val = float(ib_inputs['voorlopig'].value or 0)
        va_zvw_val = float(ib_inputs['voorlopig_zvw'].value or 0)
        ew_partner_val = ib_inputs['ew_partner'].value if ib_inputs['ew_partner'] else True

        jaar = gekozen_jaar['value']

        # Save IB-inputs to DB
        await update_ib_inputs(
            DB_PATH, jaar=jaar,
            aov_premie=aov_val, woz_waarde=woz_val,
            hypotheekrente=hyp_val, voorlopige_aanslag_betaald=va_val,
            voorlopige_aanslag_zvw=va_zvw_val,
        )

        # Save ew_naar_partner to DB and update state
        from database import update_ew_naar_partner
        await update_ew_naar_partner(DB_PATH, jaar=jaar, value=ew_partner_val)
        s['ew_naar_partner'] = ew_partner_val

        # Re-run full calculation (includes balans + box3)
        await bereken(
            aov=aov_val, woz=woz_val, hypotheekrente=hyp_val,
            voorlopige_aanslag=va_val, voorlopige_aanslag_zvw=va_zvw_val,
        )

    async def export_pdf():
        """Generate PDF of the jaarafsluiting."""
        s = berekening_state
        if not s['params_dict']:
            ui.notify('Voer eerst een berekening uit', type='warning')
            return
        jaar = gekozen_jaar['value']

        # Re-run calculation with current input values
        aov_val = float(ib_inputs['aov'].value or 0)
        woz_val = float(ib_inputs['woz'].value or 0)
        hyp_val = float(ib_inputs['hypotheek'].value or 0)
        va_val = float(ib_inputs['voorlopig'].value or 0)
        va_zvw_val = float(ib_inputs['voorlopig_zvw'].value or 0)
        ew_partner_val = ib_inputs['ew_partner'].value if ib_inputs['ew_partner'] else True
        fiscaal = bereken_volledig(
            omzet=s['omzet'], kosten=s['kosten'],
            afschrijvingen=s['afschrijvingen_totaal'],
            representatie=s['representatie'],
            investeringen_totaal=s['investeringen_dit_jaar'],
            uren=s['uren'], params=s['params_dict'],
            aov=aov_val, woz=woz_val,
            hypotheekrente=hyp_val, voorlopige_aanslag=va_val,
            voorlopige_aanslag_zvw=va_zvw_val,
            ew_naar_partner=ew_partner_val,
        )

        box3_result = bereken_box3(s['params_dict'])

        # Balance sheet for PDF
        prev_data = await fetch_fiscal_data(DB_PATH, jaar - 1)
        begin_vermogen = 0.0
        if prev_data:
            prev_balans = await bereken_balans(
                DB_PATH, jaar - 1, prev_data['activastaat'],
                winst=0, begin_vermogen=0)
            begin_vermogen = prev_balans['eigen_vermogen']

        balans_data = await bereken_balans(
            DB_PATH, jaar, s['activastaat'],
            winst=fiscaal.winst, begin_vermogen=begin_vermogen)

        # Render HTML from Jinja2 template
        templates_dir = Path(__file__).resolve().parent.parent / 'templates'
        env = Environment(loader=FileSystemLoader(str(templates_dir)))
        env.filters['euro'] = lambda v: format_euro(v) if v is not None else format_euro(0)
        template = env.get_template('jaarafsluiting.html')

        from database import get_bedrijfsgegevens
        bedrijf = await get_bedrijfsgegevens(DB_PATH)

        html = template.render(
            jaar=jaar,
            datum=date.today().strftime('%d-%m-%Y'),
            bedrijfsnaam=bedrijf.bedrijfsnaam if bedrijf else '',
            kvk=bedrijf.kvk if bedrijf else '',
            f=fiscaal,
            kosten_per_cat=s['kosten_per_cat'],
            totaal_kosten=s['totaal_kosten_alle'],
            activastaat=s['activastaat'],
            totaal_afschrijvingen=s['afschrijvingen_totaal'],
            kosten_excl_inv=s['kosten'],
            aov=aov_val,
            woz=woz_val,
            hypotheekrente=hyp_val,
            ew_naar_partner=ew_partner_val,
            box3=box3_result,
            balans=balans_data,
        )

        # Generate PDF with WeasyPrint
        from weasyprint import HTML
        output_dir = DB_PATH.parent / 'jaarafsluiting'
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / f'jaarafsluiting_{jaar}.pdf'
        HTML(string=html).write_pdf(str(pdf_path))

        ui.notify(f'PDF gegenereerd: jaarafsluiting_{jaar}.pdf', type='positive')
        ui.download.file(str(pdf_path))

    # === PAGE LAYOUT ===

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):

        # --- Header + Year selector ---
        with ui.row().classes('w-full items-center gap-4'):
            ui.label('Jaarafsluiting').classes('text-h5') \
                .style('color: #0F172A; font-weight: 700')
            ui.space()
            jaar_select = ui.select(
                {j: str(j) for j in jaren},
                label='Jaar', value=huidig_jaar,
            ).classes('w-32')

            async def on_jaar_change():
                # Save current year's IB-inputs before switching
                old_jaar = gekozen_jaar['value']
                if ib_inputs['aov'] and berekening_state['params_dict']:
                    await update_ib_inputs(
                        DB_PATH, jaar=old_jaar,
                        aov_premie=float(ib_inputs['aov'].value or 0),
                        woz_waarde=float(ib_inputs['woz'].value or 0),
                        hypotheekrente=float(ib_inputs['hypotheek'].value or 0),
                        voorlopige_aanslag_betaald=float(
                            ib_inputs['voorlopig'].value or 0),
                        voorlopige_aanslag_zvw=float(
                            ib_inputs['voorlopig_zvw'].value or 0),
                    )
                gekozen_jaar['value'] = jaar_select.value
                berekening_state['params_dict'] = {}
                await bereken()

            jaar_select.on_value_change(lambda _: on_jaar_change())

            ui.button(
                'Herbereken', icon='refresh',
                on_click=herbereken,
            ).props('outline color=primary')
            ui.button(
                'Exporteer PDF', icon='picture_as_pdf',
                on_click=export_pdf,
            ).props('outline color=primary')

        # --- Results container (filled by bereken) ---
        result_container['ref'] = ui.column().classes('w-full gap-4')

    # Auto-calculate on page load
    await bereken()
