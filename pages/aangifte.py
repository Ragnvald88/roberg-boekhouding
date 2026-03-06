"""Aangifte pagina — 5-tab interface voor IB-aangifte voorbereiding.

Tabs:
  1. Overzicht — Read-only fiscale berekening (Box 1 + IB + ZVW + resultaat)
  2. Box 3 — Invoervelden + berekening sparen & beleggen
  3. Partner — Inkomen partner (bruto loon + loonheffing)
  4. Documenten — Upload checklist (bestaande functionaliteit)
  5. Export — PDF export (placeholder)
"""

from datetime import date
from pathlib import Path
from typing import NamedTuple

from nicegui import events, ui

from components.layout import create_layout
from components.utils import format_euro
from database import (
    get_fiscale_params, get_aangifte_documenten,
    add_aangifte_document, delete_aangifte_document,
    update_partner_inkomen, update_box3_inputs,
    get_omzet_totaal, get_representatie_totaal,
    get_uitgaven_per_categorie, get_uren_totaal,
    get_investeringen_voor_afschrijving, get_investeringen,
    DB_PATH,
)
from fiscal.afschrijvingen import bereken_afschrijving
from fiscal.berekeningen import bereken_volledig, bereken_box3

AANGIFTE_DIR = DB_PATH.parent / 'aangifte'


class DocSpec(NamedTuple):
    categorie: str
    documenttype: str
    label: str
    meerdere: bool
    verplicht: bool


AANGIFTE_DOCS = [
    DocSpec('eigen_woning', 'woz_beschikking', 'WOZ-beschikking', False, False),
    DocSpec('eigen_woning', 'hypotheek_jaaroverzicht', 'Hypotheek jaaroverzicht', True, False),
    DocSpec('inkomen_partner', 'jaaropgave_partner', 'Jaaropgave partner', True, False),
    DocSpec('pensioen', 'upo_eigen', 'UPO eigen pensioen', False, False),
    DocSpec('pensioen', 'upo_partner', 'UPO partner', False, False),
    DocSpec('verzekeringen', 'aov_jaaroverzicht', 'AOV jaaroverzicht', False, False),
    DocSpec('verzekeringen', 'zorgverzekering_jaaroverzicht', 'Zorgverzekering jaaroverzicht', False, False),
    DocSpec('bankzaken', 'jaaroverzicht_prive', 'Jaaroverzicht privérekening', True, False),
    DocSpec('bankzaken', 'jaaroverzicht_zakelijk', 'Jaaroverzicht zakelijke rekening', True, False),
    DocSpec('bankzaken', 'jaaroverzicht_spaar', 'Jaaroverzicht spaarrekening', True, False),
    DocSpec('studieschuld', 'duo_overzicht', 'DUO overzicht', False, False),
    DocSpec('belastingdienst', 'voorlopige_aanslag', 'Voorlopige aanslag', False, False),
    DocSpec('onderneming', 'jaaroverzicht_uren_km', 'Jaaroverzicht uren/km', False, True),
    DocSpec('onderneming', 'winst_verlies', 'Winst & verlies', False, True),
    DocSpec('definitieve_aangifte', 'ingediende_aangifte', 'Ingediende aangifte (Boekhouder)', False, False),
]

AUTO_TYPES = {'jaaroverzicht_uren_km', 'winst_verlies'}

CATEGORIE_LABELS = {
    'eigen_woning': 'Eigen woning',
    'inkomen_partner': 'Inkomen partner',
    'pensioen': 'Pensioen',
    'verzekeringen': 'Verzekeringen',
    'bankzaken': 'Bankzaken',
    'studieschuld': 'Studieschuld',
    'belastingdienst': 'Belastingdienst',
    'onderneming': 'Onderneming',
    'definitieve_aangifte': 'Definitieve aangifte',
}


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
        # Box 3 params (for bereken_box3)
        'box3_bank_saldo': params.box3_bank_saldo,
        'box3_overige_bezittingen': params.box3_overige_bezittingen,
        'box3_schulden': params.box3_schulden,
        'box3_heffingsvrij_vermogen': params.box3_heffingsvrij_vermogen,
        'box3_rendement_bank_pct': params.box3_rendement_bank_pct,
        'box3_rendement_overig_pct': params.box3_rendement_overig_pct,
        'box3_rendement_schuld_pct': params.box3_rendement_schuld_pct,
        'box3_tarief_pct': params.box3_tarief_pct,
    }


@ui.page('/aangifte')
async def aangifte_page():
    create_layout('Aangifte', '/aangifte')

    huidig_jaar = date.today().year
    jaren = list(range(huidig_jaar, 2022, -1))
    state = {'jaar': huidig_jaar}

    # --- Helper: line with label left, amount right ---
    def _line(label: str, amount: float, bold: bool = False, color: str = ''):
        css = 'text-bold' if bold else ''
        if color:
            css += f' {color}'
        with ui.row().classes('w-full justify-between'):
            ui.label(label).classes(css)
            ui.label(format_euro(amount)).classes(f'{css} text-right')

    def _result_color_line(label: str, bedrag: float):
        """Display a result line with color coding (green=terug, red=bij)."""
        color = ('text-positive' if bedrag < 0
                 else 'text-negative' if bedrag > 0 else '')
        prefix = 'terug' if bedrag < 0 else 'bij' if bedrag > 0 else ''
        tekst = (f'{format_euro(abs(bedrag))} ({prefix})'
                 if bedrag != 0 else format_euro(0))
        with ui.row().classes('w-full justify-between items-center'):
            ui.label(label).classes('text-body2')
            ui.label(tekst).classes(f'text-body2 {color}')

    # --- Main layout ---
    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):
        # Header row with jaar selector
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('IB-aangifte').classes('text-h5') \
                .style('color: #0F172A; font-weight: 700')
            jaar_select = ui.select(
                {j: str(j) for j in jaren}, value=huidig_jaar, label='Jaar',
                on_change=lambda e: on_jaar_change(e.value),
            ).classes('w-32')

        # --- Tabs ---
        with ui.tabs().classes('w-full') as tabs:
            tab_overzicht = ui.tab('Overzicht', icon='summarize')
            tab_box3 = ui.tab('Box 3', icon='savings')
            tab_partner = ui.tab('Partner', icon='people')
            tab_docs = ui.tab('Documenten', icon='folder')
            tab_export = ui.tab('Export', icon='download')

        with ui.tab_panels(tabs, value=tab_overzicht).classes('w-full'):
            with ui.tab_panel(tab_overzicht):
                overzicht_container = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_box3):
                box3_container = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_partner):
                partner_container = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_docs):
                # Progress bar
                progress_container = ui.column().classes('w-full')
                # Checklist
                checklist_container = ui.column().classes('w-full gap-2')
            with ui.tab_panel(tab_export):
                export_container = ui.column().classes('w-full gap-4')

    # ============================================================
    # Event handlers
    # ============================================================

    async def on_jaar_change(jaar):
        state['jaar'] = jaar
        await refresh_all()

    async def refresh_all():
        docs = await get_aangifte_documenten(DB_PATH, state['jaar'])
        await render_overzicht()
        await render_box3()
        await render_partner()
        await render_progress(docs)
        await render_checklist(docs)
        await render_export()

    # ============================================================
    # Tab 1: Overzicht (read-only tax summary)
    # ============================================================

    async def render_overzicht():
        overzicht_container.clear()
        jaar = state['jaar']

        params = await get_fiscale_params(DB_PATH, jaar)
        if params is None:
            with overzicht_container:
                ui.label(
                    f'Geen fiscale parameters voor {jaar}. '
                    'Maak deze aan via Instellingen.'
                ).classes('text-negative text-subtitle1')
            return

        params_dict = _fiscale_params_to_dict(params)

        # Fetch aggregated data
        omzet = await get_omzet_totaal(DB_PATH, jaar)
        kosten_per_cat = await get_uitgaven_per_categorie(DB_PATH, jaar)
        representatie = await get_representatie_totaal(DB_PATH, jaar)
        investeringen = await get_investeringen_voor_afschrijving(
            DB_PATH, tot_jaar=jaar)
        inv_dit_jaar = await get_investeringen(DB_PATH, jaar=jaar)
        uren = await get_uren_totaal(DB_PATH, jaar, urennorm_only=True)

        totaal_kosten_alle = sum(r['totaal'] for r in kosten_per_cat)
        inv_dit_jaar_bedrag = sum(
            (u.aanschaf_bedrag or u.bedrag) for u in inv_dit_jaar
        )
        kosten_excl_inv = totaal_kosten_alle - inv_dit_jaar_bedrag

        # Afschrijvingen
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
            totaal_afschrijvingen += result['afschrijving']

        # KIA basis
        inv_totaal_dit_jaar = sum(
            (u.aanschaf_bedrag or u.bedrag) * ((u.zakelijk_pct or 100) / 100)
            for u in inv_dit_jaar
        )

        # IB inputs from DB
        aov = params.aov_premie or 0
        woz = params.woz_waarde or 0
        hypotheekrente = params.hypotheekrente or 0
        voorlopige_aanslag = params.voorlopige_aanslag_betaald or 0
        voorlopige_aanslag_zvw = params.voorlopige_aanslag_zvw or 0
        ew_naar_partner = getattr(params, 'ew_naar_partner', True)

        # Run fiscal engine
        f = bereken_volledig(
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

        # Box 3
        box3 = bereken_box3(params_dict)

        with overzicht_container:
            # Hint for editing
            with ui.row().classes('w-full items-center gap-2'):
                ui.icon('info', color='primary').classes('text-lg')
                ui.label(
                    'Waarden worden overgenomen uit Jaarafsluiting. '
                    'Wijzig invoervelden daar.'
                ).classes('text-caption text-grey-7')

            # --- Box 1: Winst uit onderneming ---
            with ui.card().classes('w-full'):
                ui.label('Box 1 — Winst uit onderneming').classes(
                    'text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')
                _line('Omzet', f.omzet)
                _line('- Kosten', f.kosten)
                _line('- Afschrijvingen', f.afschrijvingen)
                ui.separator().classes('my-1')
                _line('= Winst', f.winst, bold=True)
                _line('+ Representatie bijtelling (20%)', f.repr_bijtelling)
                _line('- KIA', f.kia)
                ui.separator().classes('my-1')
                _line('= Fiscale winst', f.fiscale_winst, bold=True)
                _line('- Zelfstandigenaftrek', f.zelfstandigenaftrek)
                if f.startersaftrek > 0:
                    _line('- Startersaftrek', f.startersaftrek)
                _line('- MKB-winstvrijstelling', f.mkb_vrijstelling)
                ui.separator().classes('my-1')
                _line('= Belastbare winst', f.belastbare_winst, bold=True)

            # --- Box 1: Eigen woning ---
            with ui.card().classes('w-full'):
                ui.label('Box 1 — Eigen woning').classes(
                    'text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')
                if ew_naar_partner:
                    ui.label('Toegerekend aan partner').classes(
                        'text-caption text-grey-7')
                elif woz > 0:
                    _line(f'Eigenwoningforfait ({params.ew_forfait_pct}% van '
                          f'{format_euro(woz)})', f.ew_forfait)
                    _line('- Hypotheekrente', hypotheekrente)
                    if f.hillen_aftrek > 0:
                        _line('- Wet Hillen aftrek', f.hillen_aftrek)
                    _line('= Eigenwoningsaldo', f.ew_saldo, bold=True)
                else:
                    ui.label('Geen eigen woning opgegeven').classes(
                        'text-caption text-grey-7')

            # --- Box 1: Inkomensvoorziening ---
            if aov > 0:
                with ui.card().classes('w-full'):
                    ui.label('Box 1 — Inkomensvoorziening').classes(
                        'text-subtitle1 text-weight-bold')
                    ui.separator().classes('my-1')
                    _line('AOV premie', aov)

            # --- IB berekening ---
            with ui.card().classes('w-full'):
                ui.label('Inkomstenbelasting').classes(
                    'text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')
                _line('Verzamelinkomen', f.verzamelinkomen, bold=True)
                _line('Bruto IB', f.bruto_ib)
                if f.tariefsaanpassing > 0:
                    _line('+ Tariefsaanpassing (beperking aftrek)',
                          f.tariefsaanpassing)

                # IB/PVV split (expandable)
                with ui.expansion('IB/PVV uitsplitsing').classes(
                        'w-full text-caption').props('dense'):
                    _line('IB (excl. premies)', f.ib_alleen)
                    _line('PVV premies volksverzekeringen', f.pvv, bold=True)
                    _line('  - AOW premie (17,90%)', f.pvv_aow)
                    _line('  - Anw premie (0,10%)', f.pvv_anw)
                    _line('  - Wlz premie (9,65%)', f.pvv_wlz)

                _line('- Algemene heffingskorting', f.ahk)
                _line('- Arbeidskorting', f.arbeidskorting)
                ui.separator().classes('my-1')
                _line('= Netto IB', f.netto_ib, bold=True)

            # --- ZVW ---
            with ui.card().classes('w-full'):
                ui.label('ZVW').classes(
                    'text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')
                _line('ZVW-bijdrage', f.zvw, bold=True)

            # --- Box 3 (summary) ---
            if box3.belasting > 0:
                with ui.card().classes('w-full'):
                    ui.label('Box 3').classes(
                        'text-subtitle1 text-weight-bold')
                    ui.separator().classes('my-1')
                    _line('Belasting', box3.belasting, bold=True)

            # --- Voorlopige aanslagen ---
            if f.voorlopige_aanslag > 0 or f.voorlopige_aanslag_zvw > 0:
                with ui.card().classes('w-full'):
                    ui.label('Voorlopige aanslagen').classes(
                        'text-subtitle1 text-weight-bold')
                    ui.separator().classes('my-1')
                    _line('IB betaald', f.voorlopige_aanslag)
                    _line('ZVW betaald', f.voorlopige_aanslag_zvw)

            # === Resultaat ===
            with ui.card().classes('w-full').style(
                    'border: 2px solid #0d9488; background: #f0fdfa'):
                ui.label('Resultaat').classes(
                    'text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')

                if f.voorlopige_aanslag > 0 or f.voorlopige_aanslag_zvw > 0:
                    _result_color_line(
                        f'IB: {format_euro(f.netto_ib)} − VA '
                        f'{format_euro(f.voorlopige_aanslag)}',
                        f.resultaat_ib)
                    _result_color_line(
                        f'ZVW: {format_euro(f.zvw)} − VA '
                        f'{format_euro(f.voorlopige_aanslag_zvw)}',
                        f.resultaat_zvw)

                if box3.belasting > 0:
                    _result_color_line('Box 3', box3.belasting)

                ui.separator().classes('my-1')

                # Total
                totaal = f.resultaat + box3.belasting
                if totaal < 0:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Totaal terug te ontvangen').classes(
                            'text-bold text-h6')
                        ui.label(format_euro(abs(totaal))).classes(
                            'text-bold text-h6 text-positive')
                elif totaal > 0:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Totaal bij te betalen').classes(
                            'text-bold text-h6')
                        ui.label(format_euro(totaal)).classes(
                            'text-bold text-h6 text-negative')
                else:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Resultaat').classes('text-bold text-h6')
                        ui.label(format_euro(0)).classes('text-bold text-h6')

    # ============================================================
    # Tab 2: Box 3
    # ============================================================

    async def render_box3():
        box3_container.clear()
        jaar = state['jaar']

        params = await get_fiscale_params(DB_PATH, jaar)
        if params is None:
            with box3_container:
                ui.label(
                    f'Geen fiscale parameters voor {jaar}. '
                    'Maak deze aan via Instellingen.'
                ).classes('text-negative text-subtitle1')
            return

        with box3_container:
            with ui.card().classes('w-full'):
                ui.label('Box 3 — Sparen en beleggen').classes(
                    'text-subtitle1 text-weight-bold')
                ui.label('Saldi op peildatum 1 januari').classes(
                    'text-caption text-grey-7')

                with ui.row().classes('gap-4 flex-wrap q-mt-sm'):
                    bank_input = ui.number(
                        'Banktegoeden', value=params.box3_bank_saldo,
                        format='%.2f', prefix='€',
                    ).classes('w-52')
                    overig_input = ui.number(
                        'Overige bezittingen', value=params.box3_overige_bezittingen,
                        format='%.2f', prefix='€',
                    ).classes('w-52')
                    schuld_input = ui.number(
                        'Schulden', value=params.box3_schulden,
                        format='%.2f', prefix='€',
                    ).classes('w-52')

                partner_check = ui.checkbox(
                    'Fiscaal partner', value=True,
                ).classes('q-mt-sm')

                async def save_and_calc_box3():
                    bank_val = float(bank_input.value or 0)
                    overig_val = float(overig_input.value or 0)
                    schuld_val = float(schuld_input.value or 0)

                    saved = await update_box3_inputs(
                        DB_PATH, jaar=state['jaar'],
                        bank_saldo=bank_val,
                        overige_bezittingen=overig_val,
                        schulden=schuld_val,
                    )
                    if not saved:
                        ui.notify(f'Geen fiscale parameters voor {state["jaar"]}',
                                  type='warning')
                        return

                    # Build params dict with updated values
                    p = await get_fiscale_params(DB_PATH, state['jaar'])
                    pd = _fiscale_params_to_dict(p)
                    box3 = bereken_box3(pd,
                                        fiscaal_partner=partner_check.value)

                    # Update results display
                    box3_results_container.clear()
                    _render_box3_results(box3_results_container, box3)
                    ui.notify('Box 3 opgeslagen', type='positive')

                ui.button('Opslaan & bereken', icon='calculate',
                          on_click=save_and_calc_box3,
                          ).props('color=primary').classes('q-mt-sm')

            # Results card (initially computed from DB values)
            box3_results_container = ui.column().classes('w-full')

            params_dict = _fiscale_params_to_dict(params)
            box3 = bereken_box3(params_dict)
            _render_box3_results(box3_results_container, box3)

    def _render_box3_results(container, box3):
        """Render Box 3 calculation results into a container."""
        container.clear()
        with container:
            with ui.card().classes('w-full'):
                ui.label('Berekening').classes(
                    'text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')
                _line('Banktegoeden', box3.bank_saldo)
                _line('Overige bezittingen', box3.overige_bezittingen)
                _line('Totaal bezittingen', box3.totaal_bezittingen, bold=True)
                _line('Schulden', box3.schulden)
                ui.separator().classes('my-1')
                _line('Rendement bank', box3.rendement_bank)
                _line('Rendement overig', box3.rendement_overig)
                _line('- Rendement schulden', box3.rendement_schuld)
                _line('Totaal rendement', box3.totaal_rendement, bold=True)
                ui.separator().classes('my-1')
                _line('Heffingsvrij vermogen', box3.heffingsvrij)
                _line('Grondslag', box3.grondslag, bold=True)
                ui.separator().classes('my-1')
                _line('Box 3 belasting', box3.belasting, bold=True)

    # ============================================================
    # Tab 3: Partner
    # ============================================================

    async def render_partner():
        partner_container.clear()
        params = await get_fiscale_params(DB_PATH, state['jaar'])

        with partner_container:
            with ui.card().classes('w-full'):
                ui.label('Partner inkomen').classes(
                    'text-subtitle1 text-weight-bold')
                if not params:
                    ui.label(f'Geen fiscale parameters voor {state["jaar"]}. '
                             'Maak deze aan via Instellingen.').classes(
                        'text-caption text-grey-7')
                    return
                ui.label('Uit jaaropgave partner (loondienst)').classes(
                    'text-caption text-grey-7')
                with ui.row().classes('w-full gap-4 q-mt-sm'):
                    bruto_input = ui.number(
                        'Bruto loon', value=params.partner_bruto_loon,
                        format='%.2f', prefix='€',
                    ).classes('flex-grow')
                    lh_input = ui.number(
                        'Loonheffing', value=params.partner_loonheffing,
                        format='%.2f', prefix='€',
                    ).classes('flex-grow')
                    ui.button('Opslaan', icon='save',
                              on_click=lambda: save_partner(
                                  bruto_input.value or 0,
                                  lh_input.value or 0),
                              ).props('color=primary')

    async def save_partner(bruto, loonheffing):
        saved = await update_partner_inkomen(
            DB_PATH, state['jaar'], bruto, loonheffing)
        if saved:
            ui.notify('Partner inkomen opgeslagen', type='positive')
        else:
            ui.notify(f'Geen fiscale parameters voor {state["jaar"]}',
                      type='warning')

    # ============================================================
    # Tab 4: Documenten (progress bar + checklist)
    # ============================================================

    async def render_progress(docs):
        progress_container.clear()
        uploaded_types = {d.documenttype for d in docs}

        # Auto-types only count as done if jaarafsluiting PDF exists
        jaarafsluiting_dir = DB_PATH.parent / 'jaarafsluiting'
        auto_done = any(
            f.stem.endswith(str(state['jaar']))
            for f in jaarafsluiting_dir.glob('*.pdf')
        ) if jaarafsluiting_dir.exists() else False

        verplichte = [d for d in AANGIFTE_DOCS if d.verplicht]
        done = sum(1 for d in verplichte
                   if d.documenttype in uploaded_types
                   or (d.documenttype in AUTO_TYPES and auto_done))
        total = len(verplichte)
        ratio = done / total if total else 0

        with progress_container:
            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center gap-4'):
                    ui.linear_progress(
                        value=ratio, size='12px', show_value=False,
                        color='positive' if ratio == 1 else 'primary',
                    ).classes('flex-grow')
                    ui.label(f'{done}/{total} verplichte documenten').classes(
                        'text-caption text-grey-7 whitespace-nowrap')

    async def render_checklist(docs):
        checklist_container.clear()

        # Group existing docs by documenttype
        docs_by_type: dict[str, list] = {}
        for d in docs:
            docs_by_type.setdefault(d.documenttype, []).append(d)

        # Auto-types done check
        jaarafsluiting_dir = DB_PATH.parent / 'jaarafsluiting'
        auto_done = any(
            f.stem.endswith(str(state['jaar']))
            for f in jaarafsluiting_dir.glob('*.pdf')
        ) if jaarafsluiting_dir.exists() else False

        # Group AANGIFTE_DOCS by categorie (preserving order)
        categories: dict[str, list[DocSpec]] = {}
        for item in AANGIFTE_DOCS:
            categories.setdefault(item.categorie, []).append(item)

        with checklist_container:
            for cat_key, items in categories.items():
                cat_label = CATEGORIE_LABELS.get(cat_key, cat_key)
                with ui.card().classes('w-full'):
                    ui.label(cat_label).classes(
                        'text-subtitle1 text-weight-bold')
                    ui.separator()

                    for spec in items:
                        existing = docs_by_type.get(spec.documenttype, [])
                        is_auto = spec.documenttype in AUTO_TYPES
                        has_doc = len(existing) > 0 or (is_auto and auto_done)

                        with ui.row().classes(
                                'w-full items-center q-py-xs gap-2'):
                            # Status icon
                            if has_doc:
                                ui.icon('check_circle', color='positive') \
                                    .classes('text-lg')
                            else:
                                ui.icon(
                                    'radio_button_unchecked',
                                    color='grey-5',
                                ).classes('text-lg')

                            # Label
                            label_text = spec.label
                            if spec.verplicht and not is_auto:
                                label_text += ' *'
                            ui.label(label_text).classes('flex-grow')

                            # Auto items: link to jaarafsluiting
                            if is_auto:
                                ui.button(
                                    'Ga naar Jaarafsluiting', icon='link',
                                    on_click=lambda: ui.navigate.to(
                                        '/jaarafsluiting'),
                                ).props(
                                    'flat dense color=primary size=sm')
                                continue

                            # Upload button (opens dialog)
                            if spec.meerdere or not existing:
                                ui.button(
                                    'Uploaden', icon='upload',
                                    on_click=lambda dt=spec.documenttype,
                                    c=spec.categorie:
                                    open_upload_dialog(c, dt),
                                ).props('flat dense color=primary size=sm')

                        # Show existing uploaded files
                        for doc in existing:
                            with ui.row().classes(
                                    'w-full items-center q-pl-xl gap-2'):
                                ui.icon('description', color='grey-6') \
                                    .classes('text-sm')
                                ui.label(doc.bestandsnaam).classes(
                                    'text-caption text-grey-7')
                                ui.button(icon='download',
                                          on_click=lambda d=doc:
                                          do_download(d),
                                          ).props(
                                    'flat dense round size=xs color=primary')
                                ui.button(icon='delete',
                                          on_click=lambda d=doc:
                                          confirm_delete(d),
                                          ).props(
                                    'flat dense round size=xs color=negative')

    async def open_upload_dialog(categorie: str, documenttype: str):
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Document uploaden').classes(
                'text-subtitle1 text-weight-medium')
            upload_widget = ui.upload(  # noqa: F841
                auto_upload=True, max_files=1,
                on_upload=lambda e: handle_upload(e, categorie, documenttype,
                                                  dialog),
            ).props('accept=".pdf,.jpg,.png,.jpeg"').classes('w-full')
            ui.button('Annuleren', on_click=dialog.close).props('flat')
        dialog.open()

    async def handle_upload(e: events.UploadEventArguments,
                            categorie: str, documenttype: str,
                            dialog):
        jaar = state['jaar']
        target_dir = AANGIFTE_DIR / str(jaar) / categorie
        target_dir.mkdir(parents=True, exist_ok=True)

        safe_name = Path(e.file.name).name.replace(' ', '_')
        file_path = target_dir / safe_name
        await e.file.save(file_path)

        await add_aangifte_document(
            DB_PATH, jaar=jaar, categorie=categorie,
            documenttype=documenttype, bestandsnaam=safe_name,
            bestandspad=str(file_path),
            upload_datum=date.today().isoformat())

        dialog.close()
        ui.notify(f'{safe_name} geupload', type='positive')
        # Refresh only documenten tab
        docs = await get_aangifte_documenten(DB_PATH, state['jaar'])
        await render_progress(docs)
        await render_checklist(docs)

    async def do_download(doc):
        if Path(doc.bestandspad).exists():
            ui.download.file(doc.bestandspad)
        else:
            ui.notify(f'{doc.bestandsnaam} niet gevonden op schijf',
                      type='warning')

    async def confirm_delete(doc):
        with ui.dialog() as dialog, ui.card():
            ui.label(f'Weet je zeker dat je "{doc.bestandsnaam}" '
                     f'wilt verwijderen?')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Annuleren',
                          on_click=dialog.close).props('flat')
                ui.button('Verwijderen', color='negative',
                          on_click=lambda: do_delete(doc, dialog))
        dialog.open()

    async def do_delete(doc, dialog):
        # Delete DB record first, then file
        await delete_aangifte_document(DB_PATH, doc.id)
        file_path = Path(doc.bestandspad)
        if file_path.exists():
            file_path.unlink()
        dialog.close()
        ui.notify(f'{doc.bestandsnaam} verwijderd', type='warning')
        # Refresh only documenten tab
        docs = await get_aangifte_documenten(DB_PATH, state['jaar'])
        await render_progress(docs)
        await render_checklist(docs)

    # ============================================================
    # Tab 5: Export
    # ============================================================

    async def render_export():
        export_container.clear()
        with export_container:
            with ui.card().classes('w-full'):
                ui.label('Exporteer aangifte-overzicht').classes(
                    'text-subtitle1 text-weight-bold')
                ui.label(
                    'PDF met volledige belastingberekening Box 1 + Box 3'
                ).classes('text-caption text-grey-7')

                async def export_pdf():
                    ui.notify('Export functie komt binnenkort', type='info')

                ui.button('Exporteer PDF', icon='picture_as_pdf',
                          on_click=export_pdf,
                          ).props('color=primary').classes('q-mt-sm')

    # ============================================================
    # Initial render
    # ============================================================
    await refresh_all()
