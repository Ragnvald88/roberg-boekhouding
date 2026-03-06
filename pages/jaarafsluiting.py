"""Jaarafsluiting pagina — fiscale berekeningen + rapporten."""

from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from nicegui import ui

from components.layout import create_layout
from components.utils import format_euro
from database import (
    get_fiscale_params,
    get_investeringen_voor_afschrijving,
    get_investeringen,
    get_omzet_totaal,
    get_representatie_totaal,
    get_uitgaven_per_categorie,
    get_uren_totaal,
    update_ib_inputs,
    DB_PATH,
)
from fiscal.afschrijvingen import bereken_afschrijving
from fiscal.berekeningen import FiscaalResultaat, bereken_volledig


def _fiscale_params_to_dict(params) -> dict:
    """Convert FiscaleParams dataclass to dict for bereken_volledig."""
    return {
        'jaar': params.jaar,
        'zelfstandigenaftrek': params.zelfstandigenaftrek,
        'startersaftrek': params.startersaftrek,
        'mkb_vrijstelling_pct': params.mkb_vrijstelling_pct,
        'kia_ondergrens': params.kia_ondergrens,
        'kia_bovengrens': params.kia_bovengrens,
        'kia_pct': params.kia_pct,
        'km_tarief': params.km_tarief,
        'schijf1_grens': params.schijf1_grens,
        'schijf1_pct': params.schijf1_pct,
        'schijf2_grens': params.schijf2_grens,
        'schijf2_pct': params.schijf2_pct,
        'schijf3_pct': params.schijf3_pct,
        'ahk_max': params.ahk_max,
        'ahk_afbouw_pct': params.ahk_afbouw_pct,
        'ahk_drempel': params.ahk_drempel,
        'ak_max': params.ak_max,
        'zvw_pct': params.zvw_pct,
        'zvw_max_grondslag': params.zvw_max_grondslag,
        'repr_aftrek_pct': params.repr_aftrek_pct,
        'ew_forfait_pct': params.ew_forfait_pct,
        'villataks_grens': params.villataks_grens,
        'wet_hillen_pct': params.wet_hillen_pct,
        'urencriterium': params.urencriterium,
        'pvv_premiegrondslag': params.pvv_premiegrondslag,
        'pvv_aow_pct': params.pvv_aow_pct,
        'pvv_anw_pct': params.pvv_anw_pct,
        'pvv_wlz_pct': params.pvv_wlz_pct,
        'arbeidskorting_brackets': params.arbeidskorting_brackets,
    }


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
    ):
        """Render all result sections into the container."""
        container.clear()

        with container:

            # === Section 1: Omzet ===
            with ui.card().classes('w-full'):
                ui.label(f'1. Omzet {jaar}').classes(
                    'text-subtitle1 text-bold')
                ui.label(f'Netto-omzet: {format_euro(fiscaal.omzet)}').classes(
                    'text-h6')

            # === Section 2: Kosten per categorie ===
            with ui.card().classes('w-full'):
                ui.label(f'2. Kosten {jaar}').classes(
                    'text-subtitle1 text-bold')

                if kosten_per_cat:
                    kosten_rows = [
                        {
                            'categorie': r['categorie'],
                            'bedrag': format_euro(r['totaal']),
                        }
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

                    ui.separator()
                    with ui.row().classes('w-full justify-between'):
                        ui.label('Totaal bedrijfslasten (incl. investeringen)') \
                            .classes('text-bold')
                        ui.label(format_euro(totaal_kosten_alle)).classes(
                            'text-bold')
                else:
                    ui.label('Geen uitgaven gevonden.').classes('text-grey')

            # === Section 3: Afschrijvingen ===
            with ui.card().classes('w-full'):
                ui.label(f'3. Afschrijvingen {jaar}').classes(
                    'text-subtitle1 text-bold')

                if activastaat:
                    activa_rows = [
                        {
                            'omschrijving': a['omschrijving'],
                            'aanschaf': str(a['aanschaf_jaar']),
                            'bedrag': format_euro(a['aanschaf_bedrag']),
                            'afschr_jr': format_euro(a['afschrijving_jaar']),
                            'afschr_dit': format_euro(
                                a['afschrijving_dit_jaar']),
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

            # === Section 4: W&V-rekening ===
            with ui.card().classes('w-full'):
                ui.label(f'4. Winst- en verliesrekening {jaar}').classes(
                    'text-subtitle1 text-bold')

                _wv_line('Netto-omzet', fiscaal.omzet)
                _wv_line('Bedrijfslasten (excl. investeringen)',
                         kosten_excl_inv, prefix='-/-')
                _wv_line('Afschrijvingen', totaal_afschrijvingen,
                         prefix='-/-')
                ui.separator()
                _wv_line('Winst', fiscaal.winst, bold=True)

            # === Section 5: Fiscale winstberekening ===
            with ui.card().classes('w-full'):
                ui.label(f'5. Fiscale winstberekening {jaar}').classes(
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

            # === Section 6: IB-schatting ===
            with ui.card().classes('w-full'):
                ui.label(f'6. Inkomstenbelasting schatting {jaar}').classes(
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
                if woz > 0:
                    ew_pct = berekening_state['params_dict'].get('ew_forfait_pct', 0.35)
                    _waterfall_line(
                        f'Eigenwoningforfait ({ew_pct}% van {format_euro(woz)})',
                        fiscaal.ew_forfait)
                    _waterfall_line(
                        '- Hypotheekrente',
                        hypotheekrente)
                    if fiscaal.hillen_aftrek > 0:
                        _waterfall_line(
                            '- Wet Hillen aftrek',
                            fiscaal.hillen_aftrek)
                    _waterfall_line(
                        '= Eigenwoningsaldo',
                        fiscaal.ew_saldo)
                if aov > 0:
                    _waterfall_line('- AOV premie', aov)
                _waterfall_line('Verzamelinkomen',
                                fiscaal.verzamelinkomen, bold=True)

                ui.separator().classes('my-1')
                _waterfall_line('Bruto inkomstenbelasting',
                                fiscaal.bruto_ib)
                _waterfall_line('- Algemene heffingskorting',
                                fiscaal.ahk)
                _waterfall_line('- Arbeidskorting',
                                fiscaal.arbeidskorting)
                _waterfall_line('= Netto inkomstenbelasting',
                                fiscaal.netto_ib, bold=True)

                ui.separator().classes('my-1')
                _waterfall_line('ZVW-bijdrage', fiscaal.zvw)

                if fiscaal.voorlopige_aanslag > 0:
                    _waterfall_line('Voorlopige aanslag betaald',
                                    fiscaal.voorlopige_aanslag)

                ui.separator().classes('my-2')

                # Result with color coding
                resultaat = fiscaal.resultaat
                if resultaat < 0:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Terug te ontvangen').classes(
                            'text-bold text-h6')
                        ui.label(format_euro(abs(resultaat))).classes(
                            'text-bold text-h6 text-positive')
                elif resultaat > 0:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Bij te betalen').classes(
                            'text-bold text-h6')
                        ui.label(format_euro(resultaat)).classes(
                            'text-bold text-h6 text-negative')
                else:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Resultaat').classes(
                            'text-bold text-h6')
                        ui.label(format_euro(0)).classes(
                            'text-bold text-h6')

            # === Section 7: Controles ===
            with ui.card().classes('w-full'):
                ui.label('7. Controles').classes(
                    'text-subtitle1 text-bold')

                # Kosten/omzet ratio (low = good)
                ratio = fiscaal.kosten_omzet_ratio
                if ratio <= 25:
                    ratio_color = 'positive'
                elif ratio <= 35:
                    ratio_color = 'warning'
                else:
                    ratio_color = 'negative'

                with ui.row().classes('items-center gap-2'):
                    ui.label('Kosten/omzet ratio:')
                    ui.badge(
                        f'{ratio:.1f}%', color=ratio_color,
                    ).classes('text-sm')

                # Urencriterium
                uren_val = fiscaal.uren_criterium
                gehaald = fiscaal.uren_criterium_gehaald
                uren_color = 'positive' if gehaald else 'negative'
                uren_text = f'{uren_val:.0f} uur'
                if gehaald:
                    uren_text += ' (gehaald)'
                else:
                    uren_text += ' (NIET gehaald)'

                with ui.row().classes('items-center gap-2'):
                    ui.label('Urencriterium (>= 1.225 uur):')
                    ui.badge(
                        uren_text, color=uren_color,
                    ).classes('text-sm')

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

    # --- Bereken handler ---

    async def bereken(aov: float = None, woz: float = None,
                      hypotheekrente: float = None,
                      voorlopige_aanslag: float = None,
                      voorlopige_aanslag_zvw: float = None):
        """Fetch data, run fiscal engine, and render all sections.

        If IB-input values are None, they are loaded from DB (fiscale_params).
        """
        jaar = gekozen_jaar['value']
        container = result_container['ref']
        if container is None:
            return

        # Fetch fiscal parameters (includes IB-inputs)
        params = await get_fiscale_params(DB_PATH, jaar)
        if params is None:
            container.clear()
            with container:
                ui.label(
                    f'Geen fiscale parameters gevonden voor {jaar}. '
                    f'Voeg deze toe via Instellingen.'
                ).classes('text-negative text-subtitle1')
            return

        # Use DB values if not explicitly provided
        if aov is None:
            aov = params.aov_premie or 0
        if woz is None:
            woz = params.woz_waarde or 0
        if hypotheekrente is None:
            hypotheekrente = params.hypotheekrente or 0
        if voorlopige_aanslag is None:
            voorlopige_aanslag = params.voorlopige_aanslag_betaald or 0
        if voorlopige_aanslag_zvw is None:
            voorlopige_aanslag_zvw = params.voorlopige_aanslag_zvw or 0

        ew_naar_partner = getattr(params, 'ew_naar_partner', True)

        params_dict = _fiscale_params_to_dict(params)

        # Fetch data from database
        omzet = await get_omzet_totaal(DB_PATH, jaar)
        kosten_per_cat = await get_uitgaven_per_categorie(DB_PATH, jaar)
        representatie = await get_representatie_totaal(DB_PATH, jaar)
        investeringen = await get_investeringen_voor_afschrijving(
            DB_PATH, tot_jaar=jaar)
        inv_dit_jaar = await get_investeringen(DB_PATH, jaar=jaar)
        uren = await get_uren_totaal(DB_PATH, jaar, urennorm_only=True)

        # Total kosten from all categories (incl. investments)
        totaal_kosten_alle = sum(r['totaal'] for r in kosten_per_cat)

        # Investment amounts this year (they go via depreciation, not costs)
        inv_dit_jaar_bedrag = sum(
            (u.aanschaf_bedrag or u.bedrag) for u in inv_dit_jaar
        )
        kosten_excl_inv = totaal_kosten_alle - inv_dit_jaar_bedrag

        # Calculate depreciation per investment (activastaat)
        activastaat = []
        totaal_afschrijvingen = 0.0
        for u in investeringen:
            aanschaf_bedrag_bruto = u.aanschaf_bedrag or u.bedrag
            zakelijk_factor = (u.zakelijk_pct or 100) / 100
            aanschaf_bedrag = aanschaf_bedrag_bruto * zakelijk_factor
            levensduur = u.levensduur_jaren or 5
            aanschaf_maand = int(u.datum[5:7])
            aanschaf_jaar = int(u.datum[0:4])
            result = bereken_afschrijving(
                aanschaf_bedrag=aanschaf_bedrag,
                restwaarde_pct=u.restwaarde_pct,
                levensduur=levensduur,
                aanschaf_maand=aanschaf_maand,
                aanschaf_jaar=aanschaf_jaar,
                bereken_jaar=jaar,
            )
            activastaat.append({
                'omschrijving': u.omschrijving,
                'aanschaf_jaar': aanschaf_jaar,
                'aanschaf_bedrag': aanschaf_bedrag,
                'afschrijving_jaar': result['per_jaar'],
                'afschrijving_dit_jaar': result['afschrijving'],
                'boekwaarde': result['boekwaarde'],
            })
            totaal_afschrijvingen += result['afschrijving']

        # KIA: total investments this year (zakelijk deel)
        inv_totaal_dit_jaar = sum(
            (u.aanschaf_bedrag or u.bedrag) * ((u.zakelijk_pct or 100) / 100)
            for u in inv_dit_jaar
        )

        # Save state for herbereken
        berekening_state.update({
            'omzet': omzet,
            'kosten': kosten_excl_inv,
            'afschrijvingen_totaal': totaal_afschrijvingen,
            'representatie': representatie,
            'investeringen_dit_jaar': inv_totaal_dit_jaar,
            'uren': uren,
            'params_dict': params_dict,
            'kosten_per_cat': kosten_per_cat,
            'activastaat': activastaat,
            'totaal_kosten_alle': totaal_kosten_alle,
            'ew_naar_partner': ew_naar_partner,
        })

        # Run fiscal engine
        fiscaal = bereken_volledig(
            omzet=omzet,
            kosten=kosten_excl_inv,
            afschrijvingen=totaal_afschrijvingen,
            representatie=representatie,
            investeringen_totaal=inv_totaal_dit_jaar,
            uren=uren,
            params=params_dict,
            aov=aov,
            woz=woz,
            hypotheekrente=hypotheekrente,
            voorlopige_aanslag=voorlopige_aanslag,
            voorlopige_aanslag_zvw=voorlopige_aanslag_zvw,
            ew_naar_partner=ew_naar_partner,
        )

        # Render result
        _render_resultaat(
            container, jaar, fiscaal, kosten_per_cat, activastaat,
            totaal_kosten_alle, kosten_excl_inv, totaal_afschrijvingen,
            aov, woz, hypotheekrente, voorlopige_aanslag,
            voorlopige_aanslag_zvw=voorlopige_aanslag_zvw,
            ew_naar_partner=ew_naar_partner,
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
        container = result_container['ref']

        # Save IB-inputs to DB
        await update_ib_inputs(
            DB_PATH, jaar=jaar,
            aov_premie=aov_val, woz_waarde=woz_val,
            hypotheekrente=hyp_val, voorlopige_aanslag_betaald=va_val,
            voorlopige_aanslag_zvw=va_zvw_val,
        )

        # Update ew_naar_partner in state
        s['ew_naar_partner'] = ew_partner_val

        fiscaal = bereken_volledig(
            omzet=s['omzet'],
            kosten=s['kosten'],
            afschrijvingen=s['afschrijvingen_totaal'],
            representatie=s['representatie'],
            investeringen_totaal=s['investeringen_dit_jaar'],
            uren=s['uren'],
            params=s['params_dict'],
            aov=aov_val,
            woz=woz_val,
            hypotheekrente=hyp_val,
            voorlopige_aanslag=va_val,
            voorlopige_aanslag_zvw=va_zvw_val,
            ew_naar_partner=ew_partner_val,
        )

        _render_resultaat(
            container, jaar, fiscaal, s['kosten_per_cat'],
            s['activastaat'], s['totaal_kosten_alle'],
            s['kosten'], s['afschrijvingen_totaal'],
            aov_val, woz_val, hyp_val, va_val,
            voorlopige_aanslag_zvw=va_zvw_val,
            ew_naar_partner=ew_partner_val,
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
            f=fiscaal,
            kosten_per_cat=s['kosten_per_cat'],
            totaal_kosten=s['totaal_kosten_alle'],
            activastaat=s['activastaat'],
            totaal_afschrijvingen=s['afschrijvingen_totaal'],
            kosten_excl_inv=s['kosten'],
            aov=aov_val,
            woz=woz_val,
            hypotheekrente=hyp_val,
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
                # Clear stale state so herbereken can't mix years
                berekening_state['params_dict'] = {}
                # Load new year's values from DB (None = load from DB)
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
