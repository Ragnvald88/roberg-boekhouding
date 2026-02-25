"""Jaarafsluiting pagina — fiscale berekeningen + rapporten."""

from datetime import date
from pathlib import Path

from nicegui import ui

from components.layout import create_layout
from database import (
    get_fiscale_params,
    get_investeringen_voor_afschrijving,
    get_omzet_totaal,
    get_representatie_totaal,
    get_uitgaven_per_categorie,
    get_uren_totaal,
    get_investeringen,
)
from fiscal.afschrijvingen import bereken_afschrijving
from fiscal.berekeningen import FiscaalResultaat, bereken_volledig

DB_PATH = Path("data/boekhouding.sqlite3")


def format_euro(value: float) -> str:
    """Format float as Dutch euro string: € 1.234,56"""
    if value is None:
        return "€ 0,00"
    return f"€ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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
    }


@ui.page('/jaarafsluiting')
async def jaarafsluiting_page():
    create_layout('Jaarafsluiting', '/jaarafsluiting')

    # --- State ---
    huidig_jaar = date.today().year
    jaren = list(range(huidig_jaar, 2022, -1))  # e.g. 2026 down to 2023
    gekozen_jaar = {'value': huidig_jaar}

    # References for dynamic containers
    result_container = {'ref': None}

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
        'activastaat': [],  # list of dicts for the table
    }

    # --- Bereken handler ---

    async def bereken(aov: float = 0, woz: float = 0,
                      hypotheekrente: float = 0,
                      voorlopige_aanslag: float = 0):
        """Run fiscal engine and render all sections."""
        jaar = gekozen_jaar['value']
        container = result_container['ref']
        if container is None:
            return

        # Fetch fiscal parameters
        params = await get_fiscale_params(DB_PATH, jaar)
        if params is None:
            container.clear()
            with container:
                ui.label(f'Geen fiscale parameters gevonden voor {jaar}. '
                         f'Voeg deze toe via Instellingen.').classes(
                    'text-negative text-subtitle1')
            return

        params_dict = _fiscale_params_to_dict(params)
        berekening_state['params_dict'] = params_dict

        # Fetch data from database
        omzet = await get_omzet_totaal(DB_PATH, jaar)
        kosten_per_cat = await get_uitgaven_per_categorie(DB_PATH, jaar)
        representatie = await get_representatie_totaal(DB_PATH, jaar)
        investeringen = await get_investeringen_voor_afschrijving(DB_PATH, tot_jaar=jaar)
        inv_dit_jaar = await get_investeringen(DB_PATH, jaar=jaar)
        uren = await get_uren_totaal(DB_PATH, jaar, urennorm_only=True)

        # Calculate total kosten (excl. investments — those go via afschrijving)
        totaal_kosten_alle = sum(r['totaal'] for r in kosten_per_cat)
        inv_dit_jaar_bedrag = sum(
            (u.aanschaf_bedrag or u.bedrag) for u in inv_dit_jaar
        )
        kosten_excl_inv = totaal_kosten_alle - inv_dit_jaar_bedrag

        # Calculate afschrijvingen (activastaat)
        activastaat = []
        totaal_afschrijvingen = 0.0
        for u in investeringen:
            aanschaf_bedrag = u.aanschaf_bedrag or u.bedrag
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

        # Investeringen totaal this year (for KIA)
        inv_totaal_dit_jaar = sum(
            (u.aanschaf_bedrag or u.bedrag) for u in inv_dit_jaar
        )

        # Save state for herbereken
        berekening_state['omzet'] = omzet
        berekening_state['kosten'] = kosten_excl_inv
        berekening_state['afschrijvingen_totaal'] = totaal_afschrijvingen
        berekening_state['representatie'] = representatie
        berekening_state['investeringen_dit_jaar'] = inv_totaal_dit_jaar
        berekening_state['uren'] = uren
        berekening_state['kosten_per_cat'] = kosten_per_cat
        berekening_state['activastaat'] = activastaat

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
        )

        # Render all sections
        _render_resultaat(
            container, jaar, fiscaal, kosten_per_cat, activastaat,
            totaal_kosten_alle, kosten_excl_inv, totaal_afschrijvingen,
            aov, woz, hypotheekrente, voorlopige_aanslag,
        )

    async def herbereken():
        """Re-run fiscal engine with IB-input values."""
        s = berekening_state
        if not s['params_dict']:
            ui.notify('Voer eerst een berekening uit', type='warning')
            return

        aov_val = float(input_aov.value or 0)
        woz_val = float(input_woz.value or 0)
        hyp_val = float(input_hypotheek.value or 0)
        va_val = float(input_voorlopig.value or 0)

        jaar = gekozen_jaar['value']
        container = result_container['ref']

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
        )

        _render_resultaat(
            container, jaar, fiscaal, s['kosten_per_cat'], s['activastaat'],
            s['kosten'] + s['investeringen_dit_jaar'],  # totaal_kosten_alle
            s['kosten'], s['afschrijvingen_totaal'],
            aov_val, woz_val, hyp_val, va_val,
        )

    def _render_resultaat(
        container, jaar: int, fiscaal: FiscaalResultaat,
        kosten_per_cat: list[dict], activastaat: list[dict],
        totaal_kosten_alle: float, kosten_excl_inv: float,
        totaal_afschrijvingen: float,
        aov: float, woz: float, hypotheekrente: float,
        voorlopige_aanslag: float,
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
                    kosten_rows = []
                    for r in kosten_per_cat:
                        kosten_rows.append({
                            'categorie': r['categorie'],
                            'bedrag': format_euro(r['totaal']),
                        })

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
                    activa_rows = []
                    for a in activastaat:
                        activa_rows.append({
                            'omschrijving': a['omschrijving'],
                            'aanschaf': str(a['aanschaf_jaar']),
                            'bedrag': format_euro(a['aanschaf_bedrag']),
                            'afschr_jr': format_euro(a['afschrijving_jaar']),
                            'afschr_dit': format_euro(a['afschrijving_dit_jaar']),
                            'boekwaarde': format_euro(a['boekwaarde']),
                        })

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
                        {'name': 'boekwaarde', 'label': f'Boekwaarde 31-12',
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
                _wv_line('Afschrijvingen', totaal_afschrijvingen, prefix='-/-')
                ui.separator()
                _wv_line('Winst', fiscaal.winst, bold=True)

            # === Section 5: Fiscale winstberekening ===
            with ui.card().classes('w-full'):
                ui.label(f'5. Fiscale winstberekening {jaar}').classes(
                    'text-subtitle1 text-bold')

                _waterfall_line('Winst jaarrekening', fiscaal.winst)
                _waterfall_line('+ Bijtelling representatie (20%)',
                                fiscaal.repr_bijtelling)
                _waterfall_line('- Kleinschaligheidsinvesteringsaftrek (KIA)',
                                fiscaal.kia)
                ui.separator().classes('my-1')
                _waterfall_line('= Fiscale winst', fiscaal.fiscale_winst,
                                bold=True)

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

                # Manual input fields
                ui.label('Persoonlijke gegevens (Box 1 aftrekposten)').classes(
                    'text-caption text-grey q-mt-sm')
                with ui.row().classes('w-full items-end gap-4 flex-wrap'):
                    nonlocal input_aov, input_woz, input_hypotheek, \
                        input_voorlopig
                    input_aov = ui.number(
                        'AOV premie (€)', value=aov,
                        format='%.2f', min=0, step=100,
                    ).classes('w-44')
                    input_woz = ui.number(
                        'WOZ waarde (€)', value=woz,
                        format='%.0f', min=0, step=1000,
                    ).classes('w-44')
                    input_hypotheek = ui.number(
                        'Hypotheekrente (€)', value=hypotheekrente,
                        format='%.2f', min=0, step=100,
                    ).classes('w-44')
                    input_voorlopig = ui.number(
                        'Voorlopige aanslag betaald (€)',
                        value=voorlopige_aanslag,
                        format='%.2f', min=0, step=100,
                    ).classes('w-52')
                    ui.button(
                        'Herbereken', icon='refresh',
                        on_click=herbereken,
                    ).props('color=primary')

                ui.separator().classes('my-2')

                # IB results
                _waterfall_line('Belastbare winst',
                                fiscaal.belastbare_winst)
                _waterfall_line('Verzamelinkomen',
                                fiscaal.verzamelinkomen, bold=True)

                ui.separator().classes('my-1')
                _waterfall_line('Bruto inkomstenbelasting',
                                fiscaal.bruto_ib)
                _waterfall_line('- Algemene heffingskorting', fiscaal.ahk)
                _waterfall_line('- Arbeidskorting', fiscaal.arbeidskorting)
                _waterfall_line('= Netto inkomstenbelasting',
                                fiscaal.netto_ib, bold=True)

                ui.separator().classes('my-1')
                _waterfall_line('ZVW-bijdrage', fiscaal.zvw)

                if fiscaal.voorlopige_aanslag > 0:
                    _waterfall_line('Voorlopige aanslag betaald',
                                    fiscaal.voorlopige_aanslag)

                ui.separator().classes('my-2')

                # Result with color
                resultaat = fiscaal.resultaat
                if resultaat < 0:
                    # Teruggave
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Terug te ontvangen').classes(
                            'text-bold text-h6')
                        ui.label(format_euro(abs(resultaat))).classes(
                            'text-bold text-h6 text-positive')
                elif resultaat > 0:
                    # Bijbetalen
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Bij te betalen').classes(
                            'text-bold text-h6')
                        ui.label(format_euro(resultaat)).classes(
                            'text-bold text-h6 text-negative')
                else:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Resultaat').classes('text-bold text-h6')
                        ui.label(format_euro(0)).classes('text-bold text-h6')

            # === Section 7: Controles ===
            with ui.card().classes('w-full'):
                ui.label('7. Controles').classes(
                    'text-subtitle1 text-bold')

                # Kosten/omzet ratio
                ratio = fiscaal.kosten_omzet_ratio
                if 20 <= ratio <= 25:
                    ratio_color = 'positive'
                elif 25 < ratio <= 30:
                    ratio_color = 'warning'
                else:
                    ratio_color = 'negative'

                with ui.row().classes('items-center gap-2'):
                    ui.label('Kosten/omzet ratio:')
                    ui.badge(f'{ratio:.1f}%', color=ratio_color).classes(
                        'text-sm')

                # Urencriterium
                uren = fiscaal.uren_criterium
                gehaald = fiscaal.uren_criterium_gehaald
                uren_color = 'positive' if gehaald else 'negative'
                uren_text = f'{uren:.0f} uur'
                uren_label = ' (gehaald)' if gehaald else ' (NIET gehaald)'

                with ui.row().classes('items-center gap-2'):
                    ui.label('Urencriterium (>= 1.225 uur):')
                    ui.badge(
                        uren_text + uren_label, color=uren_color,
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

    # === IB input fields (declared at page scope, updated in _render_resultaat) ===
    input_aov = None
    input_woz = None
    input_hypotheek = None
    input_voorlopig = None

    # === PAGE LAYOUT ===

    with ui.column().classes('w-full p-4 max-w-6xl mx-auto gap-4'):

        # --- Year selector + Bereken button ---
        with ui.row().classes('w-full items-center gap-4'):
            jaar_select = ui.select(
                {j: str(j) for j in jaren},
                label='Jaar', value=huidig_jaar,
            ).classes('w-32')

            def on_jaar_change():
                gekozen_jaar['value'] = jaar_select.value

            jaar_select.on('update:model-value', lambda: on_jaar_change())

            ui.button(
                'Bereken', icon='calculate',
                on_click=lambda: bereken(),
            ).props('color=primary')

        # --- Results container ---
        result_container['ref'] = ui.column().classes('w-full gap-4')
