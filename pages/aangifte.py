"""Aangifte Invulhulp — mirrors Belastingdienst IB-aangifte structure.

Each value shows the exact Belastingdienst field label with a copy-to-clipboard
button, so the user can directly copy values into the MijnBelastingdienst portal.

Tabs:
  1. Winst uit onderneming  (icon: business_center)
  2. Prive & aftrek          (icon: home)
  3. Box 3                   (icon: savings)
  4. Overzicht               (icon: summarize)
  5. Documenten              (icon: folder)
"""

from datetime import date
from pathlib import Path
from typing import NamedTuple

from nicegui import events, ui

from components.fiscal_utils import fetch_fiscal_data, fiscale_params_to_dict
from components.layout import create_layout
from components.utils import format_euro
from database import (
    get_fiscale_params, get_aangifte_documenten,
    add_aangifte_document, delete_aangifte_document,
    update_ib_inputs, update_box3_inputs, update_ew_naar_partner,
    update_za_sa_toggles,
    DB_PATH,
)
from fiscal.berekeningen import bereken_volledig, bereken_box3

AANGIFTE_DIR = DB_PATH.parent / 'aangifte'


# === Belastingdienst field mapping ===

BD = {
    'omzet': 'Winst > Opbrengsten > Netto-omzet',
    'kosten_totaal': 'Winst > Kosten > Totaal bedrijfslasten',
    'afschrijvingen': 'Winst > Afschrijvingen > Totaal',
    'repr_bijtelling': 'Winst > Fiscale correcties > Bijtelling representatie',
    'kia': 'Winst > Investeringsaftrek > Kleinschaligheid (KIA)',
    'fiscale_winst': 'Winst > Fiscale winst',
    'za': 'Winst > Ondernemersaftrek > Zelfstandigenaftrek',
    'sa': 'Winst > Ondernemersaftrek > Startersaftrek',
    'mkb': 'Winst > MKB-winstvrijstelling',
    'belastbare_winst': 'Winst > Belastbare winst uit onderneming',
    'woz': 'Eigen woning > WOZ-waarde',
    'ew_forfait': 'Eigen woning > Eigenwoningforfait',
    'hypotheekrente': 'Eigen woning > Betaalde rente en kosten',
    'ew_saldo': 'Eigen woning > Saldo eigen woning',
    'aov': 'Inkomensvoorzieningen > Premie AOV',
    'lijfrente': 'Inkomensvoorzieningen > Lijfrentepremie',
    'va_ib': 'Voorlopige aanslag > Bedrag IB',
    'va_zvw': 'Voorlopige aanslag > Bedrag ZVW',
    'box3_bank': 'Box 3 > Banktegoeden',
    'box3_overig': 'Box 3 > Overige bezittingen',
    'box3_schulden': 'Box 3 > Schulden',
    'box3_belasting': 'Box 3 > Belasting sparen en beleggen',
    'verzamelinkomen': 'Verzamelinkomen',
    'netto_ib': 'Verschuldigde inkomstenbelasting',
    'zvw': 'Bijdrage Zorgverzekeringswet',
}


# === Document checklist ===

class DocSpec(NamedTuple):
    categorie: str
    documenttype: str
    label: str
    meerdere: bool
    verplicht: bool


AANGIFTE_DOCS = [
    DocSpec('winst_onderneming', 'jaaroverzicht_uren_km', 'Jaaroverzicht uren/km', False, True),
    DocSpec('winst_onderneming', 'winst_verlies', 'Winst & verlies', False, True),
    DocSpec('winst_onderneming', 'km_registratie', 'Kilometerregistratie', False, False),
    DocSpec('eigen_woning', 'woz_beschikking', 'WOZ-beschikking', False, False),
    DocSpec('eigen_woning', 'hypotheek_jaaroverzicht', 'Hypotheek jaaroverzicht', True, False),
    DocSpec('inkomensvoorzieningen', 'aov_jaaroverzicht', 'AOV jaaroverzicht', False, False),
    DocSpec('box3', 'jaaroverzicht_prive', 'Jaaroverzicht privérekening', True, False),
    DocSpec('box3', 'jaaroverzicht_zakelijk', 'Jaaroverzicht zakelijke rekening', True, False),
    DocSpec('box3', 'jaaroverzicht_spaar', 'Jaaroverzicht spaarrekening', True, False),
    DocSpec('box3', 'beleggingsoverzicht', 'Beleggingsoverzicht', True, False),
    DocSpec('voorlopige_aanslag', 'va_ib_beschikking', 'VA IB beschikking', False, False),
    DocSpec('voorlopige_aanslag', 'va_zvw_beschikking', 'VA ZVW beschikking', False, False),
    DocSpec('definitieve_aangifte', 'ingediende_aangifte', 'Ingediende aangifte (Boekhouder)', False, False),
]

AUTO_TYPES = {'jaaroverzicht_uren_km', 'winst_verlies'}

CATEGORIE_LABELS = {
    'winst_onderneming': 'Winst uit onderneming',
    'eigen_woning': 'Eigen woning',
    'inkomensvoorzieningen': 'Inkomensvoorzieningen',
    'box3': 'Box 3',
    'voorlopige_aanslag': 'Voorlopige aanslag',
    'definitieve_aangifte': 'Definitieve aangifte',
}


@ui.page('/aangifte')
async def aangifte_page():
    create_layout('Aangifte', '/aangifte')

    huidig_jaar = date.today().year
    vorig_jaar = huidig_jaar - 1
    jaren = list(range(huidig_jaar, 2022, -1))
    state = {'jaar': vorig_jaar}

    # --- Cached fiscal computation (avoid triple fetch+calc) ---
    _cache = {'jaar': None, 'data': None, 'fiscaal': None}

    async def _get_fiscal(jaar: int):
        """Return (data, fiscaal) from cache or compute fresh."""
        if _cache['jaar'] == jaar and _cache['data'] is not None:
            return _cache['data'], _cache['fiscaal']
        data = await fetch_fiscal_data(DB_PATH, jaar)
        if data is None:
            _cache.update(jaar=jaar, data=None, fiscaal=None)
            return None, None
        f = bereken_volledig(
            omzet=data['omzet'], kosten=data['kosten_excl_inv'],
            afschrijvingen=data['totaal_afschrijvingen'],
            representatie=data['representatie'],
            investeringen_totaal=data['inv_totaal_dit_jaar'],
            uren=data['uren'], params=data['params_dict'],
            aov=data['aov'], lijfrente=data.get('lijfrente', 0),
            woz=data['woz'],
            hypotheekrente=data['hypotheekrente'],
            voorlopige_aanslag=data['voorlopige_aanslag'],
            voorlopige_aanslag_zvw=data['voorlopige_aanslag_zvw'],
            ew_naar_partner=data['ew_naar_partner'],
        )
        _cache.update(jaar=jaar, data=data, fiscaal=f)
        return data, f

    def _invalidate_cache():
        """Clear cache so next _get_fiscal() recalculates."""
        _cache.update(jaar=None, data=None, fiscaal=None)

    # --- Copy helper ---
    def _copy_value(amount: float, label: str = ''):
        """Copy raw integer value to clipboard (what you type in BD portal)."""
        import json
        raw = str(int(round(amount)))
        safe_label = json.dumps(f'{label}: {raw} gekopieerd')[1:-1]  # strip outer quotes
        ui.run_javascript(
            f'navigator.clipboard.writeText("{raw}").then(() => '
            f'Quasar.Notify.create({{message: "{safe_label}", type: "positive", timeout: 1500}}))'
        )

    def _invulhulp_line(bd_veld: str, label: str, amount: float,
                         bold: bool = False, show_copy: bool = True):
        """Render an invulhulp line: label + BD field path + amount + copy button."""
        css = 'text-bold' if bold else ''
        with ui.row().classes('w-full justify-between items-center q-py-xs'):
            with ui.column().classes('gap-0'):
                ui.label(label).classes(css)
                if bd_veld:
                    ui.label(bd_veld).classes('text-caption text-grey-6').style('font-size: 0.75rem')
            with ui.row().classes('items-center gap-1'):
                ui.label(format_euro(amount)).classes(f'{css} text-right whitespace-nowrap')
                if show_copy and amount != 0:
                    ui.button(icon='content_copy', on_click=lambda a=amount, l=label: _copy_value(a, l)) \
                        .props('flat dense round size=xs color=primary')

    def _line(label: str, amount: float, bold: bool = False):
        """Simple line without BD field path or copy button."""
        css = 'text-bold' if bold else ''
        with ui.row().classes('w-full justify-between items-center q-py-xs'):
            ui.label(label).classes(css)
            ui.label(format_euro(amount)).classes(f'{css} text-right')

    def _result_color_line(label: str, bedrag: float):
        """Result line with color coding (green=terug, red=bij)."""
        color = ('text-positive' if bedrag < 0
                 else 'text-negative' if bedrag > 0 else '')
        prefix = 'terug' if bedrag < 0 else 'bij' if bedrag > 0 else ''
        tekst = (f'{format_euro(abs(bedrag))} ({prefix})'
                 if bedrag != 0 else format_euro(0))
        with ui.row().classes('w-full justify-between items-center'):
            ui.label(label).classes('text-body2')
            with ui.row().classes('items-center gap-1'):
                ui.label(tekst).classes(f'text-body2 {color}')
                if bedrag != 0:
                    ui.button(icon='content_copy',
                              on_click=lambda b=abs(bedrag), l=label: _copy_value(b, l)) \
                        .props('flat dense round size=xs color=primary')

    # --- Main layout ---
    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):
        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-0'):
                ui.label('Aangifte Invulhulp').classes('text-h5') \
                    .style('color: #0F172A; font-weight: 700')
                ui.label('Kopieer waarden naar MijnBelastingdienst.nl').classes(
                    'text-caption text-grey-7')
            jaar_select = ui.select(
                {j: str(j) for j in jaren}, value=vorig_jaar, label='Aangiftejaar',
                on_change=lambda e: on_jaar_change(e.value),
            ).classes('w-36')

        # Warnings container (missing data, jaarafsluiting status)
        warnings_container = ui.column().classes('w-full gap-2')

        with ui.tabs().classes('w-full') as tabs:
            tab_winst = ui.tab('Winst', icon='business_center')
            tab_prive = ui.tab('Prive & aftrek', icon='home')
            tab_box3 = ui.tab('Box 3', icon='savings')
            tab_overzicht = ui.tab('Overzicht', icon='summarize')
            tab_docs = ui.tab('Documenten', icon='folder')

        with ui.tab_panels(tabs, value=tab_winst).classes('w-full'):
            with ui.tab_panel(tab_winst):
                winst_container = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_prive):
                prive_container = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_box3):
                box3_container = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_overzicht):
                overzicht_container = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_docs):
                progress_container = ui.column().classes('w-full')
                checklist_container = ui.column().classes('w-full gap-2')

    # ============================================================
    # Event handlers
    # ============================================================

    async def on_jaar_change(jaar):
        state['jaar'] = jaar
        _invalidate_cache()
        await refresh_all()

    async def render_warnings():
        """Show alerts for missing data and jaarafsluiting status."""
        warnings_container.clear()
        jaar = state['jaar']
        data, _ = await _get_fiscal(jaar)
        if data is None:
            return

        warnings = []
        params = data['params']

        # Jaarafsluiting status
        ja_status = getattr(params, 'jaarafsluiting_status', 'concept')
        if ja_status != 'definitief':
            warnings.append(('warning', 'fact_check',
                              f'Jaarafsluiting {jaar}: {ja_status.capitalize()}. '
                              'Sluit eerst de jaarafsluiting af.',
                              '/jaarafsluiting'))

        # Missing data checks
        if data['n_uitgaven'] == 0:
            warnings.append(('warning', 'receipt_long',
                              f'Geen uitgaven geregistreerd voor {jaar}.', None))
        if data['aov'] == 0:
            warnings.append(('info', 'health_and_safety',
                              'Geen AOV premie ingevuld. Vul deze in bij Privé & aftrek.',
                              None))

        if not warnings:
            return

        with warnings_container:
            for color, icon, text, link in warnings:
                with ui.card().classes('w-full q-pa-sm').style(
                    f'border-left: 4px solid {"#F59E0B" if color == "warning" else "#3B82F6"}'
                ):
                    with ui.row().classes('items-center gap-2 w-full'):
                        ui.icon(icon, color=color).classes('text-lg')
                        ui.label(text).classes('text-body2 flex-grow')
                        if link:
                            ui.button('Bekijken', icon='open_in_new',
                                      on_click=lambda l=link: ui.navigate.to(l)) \
                                .props('flat dense color=primary size=sm')

    async def refresh_all():
        await render_warnings()
        await render_winst()
        await render_prive()
        await render_box3()
        await render_overzicht()
        docs = await get_aangifte_documenten(DB_PATH, state['jaar'])
        await render_progress(docs)
        await render_checklist(docs)

    # ============================================================
    # Tab 1: Winst uit onderneming
    # ============================================================

    async def render_winst():
        winst_container.clear()
        jaar = state['jaar']

        data, f = await _get_fiscal(jaar)
        if data is None:
            with winst_container:
                ui.label(
                    f'Geen fiscale parameters voor {jaar}. '
                    'Maak deze aan via Instellingen.'
                ).classes('text-negative text-subtitle1')
            return

        with winst_container:
            # Card 1: Opbrengsten
            with ui.card().classes('w-full'):
                ui.label('Opbrengsten').classes('text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')
                _invulhulp_line(BD['omzet'], 'Netto-omzet', f.omzet, bold=True)

            # Card 2: Kosten
            with ui.card().classes('w-full'):
                ui.label('Kosten').classes('text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')

                kosten_per_cat = data['kosten_per_cat']
                for r in kosten_per_cat:
                    cat = r['categorie']
                    if cat.lower() == 'investering':
                        continue
                    _invulhulp_line(
                        f'Winst > Kosten > {cat}', cat, r['totaal'])

                ui.separator().classes('my-1')
                _invulhulp_line(BD['kosten_totaal'],
                                'Totaal bedrijfslasten', f.kosten, bold=True)

            # Card 3: Afschrijvingen
            activastaat = data['activastaat']
            if activastaat:
                with ui.card().classes('w-full'):
                    ui.label('Afschrijvingen').classes('text-subtitle1 text-weight-bold')
                    ui.separator().classes('my-1')

                    activa_rows = [
                        {
                            'omschrijving': a['omschrijving'],
                            'aanschaf': str(a['aanschaf_jaar']),
                            'bedrag': format_euro(a['aanschaf_bedrag']),
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
                        {'name': 'afschr_dit', 'label': f'Afschr {jaar}',
                         'field': 'afschr_dit', 'align': 'right'},
                        {'name': 'boekwaarde', 'label': 'Boekwaarde 31-12',
                         'field': 'boekwaarde', 'align': 'right'},
                    ]
                    ui.table(
                        columns=activa_columns, rows=activa_rows,
                        row_key='omschrijving',
                    ).classes('w-full').props('dense flat')

                    ui.separator().classes('my-1')
                    _invulhulp_line(BD['afschrijvingen'],
                                    'Totaal afschrijvingen', data['totaal_afschrijvingen'], bold=True)

            # Card 4: Fiscale correcties
            if f.repr_bijtelling > 0 or f.kia > 0:
                with ui.card().classes('w-full'):
                    ui.label('Fiscale correcties').classes('text-subtitle1 text-weight-bold')
                    ui.separator().classes('my-1')
                    if f.repr_bijtelling > 0:
                        _invulhulp_line(BD['repr_bijtelling'],
                                        'Representatie bijtelling (20%)', f.repr_bijtelling)
                    if f.kia > 0:
                        _invulhulp_line(BD['kia'],
                                        f'KIA ({data["params_dict"]["kia_pct"]:.0f}%)', f.kia)

            # Card 5: Fiscale winst → Belastbare winst
            with ui.card().classes('w-full'):
                ui.label('Fiscale winst → Belastbare winst').classes(
                    'text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')

                _line('Winst (omzet - kosten - afschrijvingen)', f.winst)
                if f.repr_bijtelling > 0:
                    _line('+ Representatie bijtelling', f.repr_bijtelling)
                if f.kia > 0:
                    _line('- KIA', f.kia)
                _invulhulp_line(BD['fiscale_winst'], '= Fiscale winst', f.fiscale_winst, bold=True)

                ui.separator().classes('my-1')

                # ZA/SA toggles
                za_actief = data['params_dict'].get('za_actief', True)
                sa_actief = data['params_dict'].get('sa_actief', False)

                async def _on_za_sa_change():
                    await update_za_sa_toggles(
                        DB_PATH, jaar=jaar,
                        za_actief=za_check.value,
                        sa_actief=sa_check.value,
                    )
                    _invalidate_cache()
                    await render_winst()

                with ui.row().classes('items-center gap-4'):
                    za_check = ui.checkbox(
                        'Zelfstandigenaftrek (ZA)', value=za_actief,
                        on_change=lambda: _on_za_sa_change(),
                    )
                    sa_check = ui.checkbox(
                        'Startersaftrek (SA)', value=sa_actief,
                        on_change=lambda: _on_za_sa_change(),
                    )

                # Urencriterium badge
                gehaald = f.uren_criterium_gehaald
                with ui.row().classes('items-center gap-2'):
                    ui.label(f'Urencriterium: {f.uren_criterium:.0f} uur')
                    if gehaald:
                        ui.badge('gehaald', color='positive').classes('text-xs')
                    else:
                        ui.badge('NIET gehaald', color='negative').classes('text-xs')

                _invulhulp_line(BD['za'], '- Zelfstandigenaftrek', f.zelfstandigenaftrek)
                if f.startersaftrek > 0:
                    _invulhulp_line(BD['sa'], '- Startersaftrek', f.startersaftrek)
                _line('= Na ondernemersaftrek', f.na_ondernemersaftrek)
                _invulhulp_line(BD['mkb'],
                                f'- MKB-winstvrijstelling ({data["params_dict"]["mkb_vrijstelling_pct"]}%)',
                                f.mkb_vrijstelling)

                ui.separator().classes('my-1')
                # Prominent belastbare winst
                with ui.row().classes('w-full justify-between items-center') \
                        .style('background: #f0fdfa; padding: 8px; border-radius: 4px'):
                    with ui.column().classes('gap-0'):
                        ui.label('Belastbare winst uit onderneming').classes('text-bold text-h6')
                        ui.label(BD['belastbare_winst']).classes('text-caption text-grey-6')
                    with ui.row().classes('items-center gap-2'):
                        ui.label(format_euro(f.belastbare_winst)).classes('text-bold text-h6')
                        ui.button(icon='content_copy',
                                  on_click=lambda: _copy_value(f.belastbare_winst, 'Belastbare winst')) \
                            .props('round color=primary size=sm')

    # ============================================================
    # Tab 2: Prive & aftrek
    # ============================================================

    async def render_prive():
        prive_container.clear()
        jaar = state['jaar']

        data, f = await _get_fiscal(jaar)
        if data is None:
            with prive_container:
                ui.label(
                    f'Geen fiscale parameters voor {jaar}. '
                    'Maak deze aan via Instellingen.'
                ).classes('text-negative text-subtitle1')
            return

        params = data['params']
        params_dict = data['params_dict']

        # Containers for auto-updated read-only values
        ew_results_ref = {'container': None}

        with prive_container:
            # Card 1: Eigen woning
            with ui.card().classes('w-full'):
                ui.label('Eigen woning').classes('text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')

                with ui.row().classes('gap-4 flex-wrap'):
                    woz_input = ui.number(
                        'WOZ-waarde', value=data['woz'],
                        format='%.0f', prefix='€',
                    ).classes('w-48')
                    hyp_input = ui.number(
                        'Hypotheekrente', value=data['hypotheekrente'],
                        format='%.2f', prefix='€',
                    ).classes('w-48')

                ew_partner_check = ui.checkbox(
                    'Toerekenen aan partner', value=data['ew_naar_partner'],
                ).classes('q-mt-xs')
                ui.label(BD['woz']).classes('text-caption text-grey-6')

                # Read-only calculated values
                ew_results_ref['container'] = ui.column().classes('w-full q-mt-sm')
                _render_ew_results(ew_results_ref['container'], f, data['woz'], data['hypotheekrente'],
                                    data['ew_naar_partner'], params_dict)

            # Card 2: Inkomensvoorzieningen
            with ui.card().classes('w-full'):
                ui.label('Inkomensvoorzieningen').classes('text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')

                with ui.row().classes('gap-4 flex-wrap'):
                    aov_input = ui.number(
                        'AOV premie', value=data['aov'],
                        format='%.2f', prefix='€',
                    ).classes('w-48')
                    lijfrente_input = ui.number(
                        'Lijfrentepremie', value=data.get('lijfrente', 0),
                        format='%.2f', prefix='€',
                    ).classes('w-48')
                with ui.row().classes('items-center gap-2 q-mt-xs'):
                    ui.icon('info_outline', color='warning').classes('text-lg')
                    ui.label('AOV en lijfrente zijn geen bedrijfskosten maar '
                             'persoonlijke aftrekposten (Box 1 inkomensvoorzieningen)'
                             ).classes('text-caption text-grey-7')
                ui.label(f'{BD["aov"]} / Inkomensvoorzieningen > Lijfrentepremie').classes(
                    'text-caption text-grey-6')

            # Card 3: Voorlopige aanslagen
            with ui.card().classes('w-full'):
                ui.label('Voorlopige aanslagen').classes('text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')

                with ui.row().classes('gap-4 flex-wrap'):
                    va_ib_input = ui.number(
                        'VA Inkomstenbelasting', value=data['voorlopige_aanslag'],
                        format='%.2f', prefix='€',
                    ).classes('w-52')
                    va_zvw_input = ui.number(
                        'VA Zorgverzekeringswet', value=data['voorlopige_aanslag_zvw'],
                        format='%.2f', prefix='€',
                    ).classes('w-52')
                ui.label(f'{BD["va_ib"]}, {BD["va_zvw"]}').classes('text-caption text-grey-6')

            # Save button
            async def save_prive():
                aov_val = float(aov_input.value or 0)
                woz_val = float(woz_input.value or 0)
                hyp_val = float(hyp_input.value or 0)
                va_ib_val = float(va_ib_input.value or 0)
                va_zvw_val = float(va_zvw_input.value or 0)
                ew_val = ew_partner_check.value
                lijfrente_val = float(lijfrente_input.value or 0)

                await update_ib_inputs(
                    DB_PATH, jaar=jaar,
                    aov_premie=aov_val, woz_waarde=woz_val,
                    hypotheekrente=hyp_val,
                    voorlopige_aanslag_betaald=va_ib_val,
                    voorlopige_aanslag_zvw=va_zvw_val,
                    lijfrente_premie=lijfrente_val,
                )
                await update_ew_naar_partner(DB_PATH, jaar=jaar, value=ew_val)
                ui.notify('Opgeslagen', type='positive')

                # Invalidate cache and refresh dependent views
                _invalidate_cache()
                new_data, new_f = await _get_fiscal(jaar)
                _render_ew_results(ew_results_ref['container'], new_f, woz_val, hyp_val,
                                    ew_val, new_data['params_dict'])
                await render_overzicht()
                await render_warnings()

            ui.button('Opslaan', icon='save', on_click=save_prive) \
                .props('color=primary').classes('q-mt-sm')

    def _render_ew_results(container, f, woz, hypotheekrente, ew_naar_partner, params_dict):
        """Render eigen woning computed results."""
        container.clear()
        with container:
            if ew_naar_partner:
                ui.label('Eigen woning toegerekend aan partner').classes(
                    'text-caption text-grey-7')
            elif woz > 0:
                _invulhulp_line(BD['ew_forfait'],
                                f'Eigenwoningforfait ({params_dict.get("ew_forfait_pct", 0.35)}% van {format_euro(woz)})',
                                f.ew_forfait)
                _invulhulp_line(BD['hypotheekrente'], '- Hypotheekrente', hypotheekrente)
                if f.hillen_aftrek > 0:
                    _line('- Wet Hillen aftrek', f.hillen_aftrek)
                _invulhulp_line(BD['ew_saldo'], '= Eigenwoningsaldo', f.ew_saldo, bold=True)
            else:
                ui.label('Geen eigen woning opgegeven').classes(
                    'text-caption text-grey-7')

    # ============================================================
    # Tab 3: Box 3
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

        params_dict = fiscale_params_to_dict(params)

        with box3_container:
            # Input card
            with ui.card().classes('w-full'):
                ui.label('Bezittingen & schulden per 1 januari').classes(
                    'text-subtitle1 text-weight-bold')
                ui.label(f'Peildatum: 1 januari {jaar}').classes(
                    'text-caption text-grey-7')
                ui.separator().classes('my-1')

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
                    'Fiscaal partner (verdubbelt heffingsvrij vermogen)', value=True,
                ).classes('q-mt-sm')

                ui.label(f'{BD["box3_bank"]}, {BD["box3_overig"]}, {BD["box3_schulden"]}').classes(
                    'text-caption text-grey-6')

                async def save_and_calc_box3():
                    bank_val = float(bank_input.value or 0)
                    overig_val = float(overig_input.value or 0)
                    schuld_val = float(schuld_input.value or 0)

                    saved = await update_box3_inputs(
                        DB_PATH, jaar=jaar,
                        bank_saldo=bank_val,
                        overige_bezittingen=overig_val,
                        schulden=schuld_val,
                    )
                    if not saved:
                        ui.notify(f'Geen fiscale parameters voor {jaar}', type='warning')
                        return

                    p = await get_fiscale_params(DB_PATH, jaar)
                    pd = fiscale_params_to_dict(p)
                    box3 = bereken_box3(pd, fiscaal_partner=partner_check.value)

                    box3_results_container.clear()
                    _render_box3_results(box3_results_container, box3, pd)
                    ui.notify('Box 3 opgeslagen', type='positive')

                ui.button('Opslaan & bereken', icon='calculate',
                          on_click=save_and_calc_box3,
                          ).props('color=primary').classes('q-mt-sm')

            # Results card (use same default as checkbox)
            box3_results_container = ui.column().classes('w-full')
            box3 = bereken_box3(params_dict, fiscaal_partner=partner_check.value)
            _render_box3_results(box3_results_container, box3, params_dict)

    def _render_box3_results(container, box3, params_dict):
        """Render Box 3 calculation results."""
        container.clear()
        with container:
            with ui.card().classes('w-full'):
                ui.label('Berekening Box 3').classes('text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')

                _invulhulp_line(BD['box3_bank'], 'Banktegoeden', box3.bank_saldo)
                _invulhulp_line(BD['box3_overig'], 'Overige bezittingen', box3.overige_bezittingen)
                _line('Totaal bezittingen', box3.totaal_bezittingen)
                _invulhulp_line(BD['box3_schulden'], 'Schulden', box3.schulden)

                ui.separator().classes('my-1')
                _line(f'Rendement bank ({params_dict.get("box3_rendement_bank_pct", 0)}%)',
                      box3.rendement_bank)
                _line(f'Rendement overig ({params_dict.get("box3_rendement_overig_pct", 0)}%)',
                      box3.rendement_overig)
                _line(f'- Rendement schulden ({params_dict.get("box3_rendement_schuld_pct", 0)}%)',
                      box3.rendement_schuld)
                _line('Totaal rendement', box3.totaal_rendement, bold=True)

                ui.separator().classes('my-1')
                _line('Heffingsvrij vermogen', box3.heffingsvrij)
                _line('Grondslag sparen & beleggen', box3.grondslag, bold=True)

                ui.separator().classes('my-1')
                _invulhulp_line(BD['box3_belasting'], 'Box 3 belasting',
                                box3.belasting, bold=True)

    # ============================================================
    # Tab 4: Overzicht (verification / final summary)
    # ============================================================

    async def render_overzicht():
        overzicht_container.clear()
        jaar = state['jaar']

        data, f = await _get_fiscal(jaar)
        if data is None:
            with overzicht_container:
                ui.label(
                    f'Geen fiscale parameters voor {jaar}. '
                    'Maak deze aan via Instellingen.'
                ).classes('text-negative text-subtitle1')
            return

        params_dict = data['params_dict']
        box3 = bereken_box3(params_dict)

        with overzicht_container:
            ui.label('Dit overzicht toont dezelfde waarden als het eindscherm van '
                      'MijnBelastingdienst.nl').classes('text-caption text-grey-7')

            # Card 1: Box 1
            with ui.card().classes('w-full'):
                ui.label('Box 1 — Inkomen uit werk en woning').classes(
                    'text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')
                _invulhulp_line(BD['belastbare_winst'],
                                'Belastbare winst uit onderneming', f.belastbare_winst)
                if not data['ew_naar_partner'] and data['woz'] > 0:
                    _invulhulp_line(BD['ew_saldo'], 'Eigenwoningsaldo', f.ew_saldo)
                if data['aov'] > 0:
                    _invulhulp_line(BD['aov'], '- AOV premie', data['aov'])
                if data.get('lijfrente', 0) > 0:
                    _invulhulp_line(BD['lijfrente'], '- Lijfrentepremie',
                                    data['lijfrente'])
                ui.separator().classes('my-1')
                _invulhulp_line(BD['verzamelinkomen'], 'Verzamelinkomen',
                                f.verzamelinkomen, bold=True)

            # Card 2: Belasting Box 1
            with ui.card().classes('w-full'):
                ui.label('Belasting Box 1').classes('text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')
                _line('Bruto IB', f.bruto_ib)
                if f.tariefsaanpassing > 0:
                    _line('+ Tariefsaanpassing (beperking aftrek)', f.tariefsaanpassing)

                with ui.expansion('IB/PVV uitsplitsing').classes(
                        'w-full text-caption').props('dense'):
                    _line('IB (excl. premies)', f.ib_alleen)
                    _line('PVV premies volksverzekeringen', f.pvv, bold=True)
                    pvv_aow = params_dict.get('pvv_aow_pct', 17.90)
                    pvv_anw = params_dict.get('pvv_anw_pct', 0.10)
                    pvv_wlz = params_dict.get('pvv_wlz_pct', 9.65)
                    _line(f'  - AOW premie ({pvv_aow}%)', f.pvv_aow)
                    _line(f'  - Anw premie ({pvv_anw}%)', f.pvv_anw)
                    _line(f'  - Wlz premie ({pvv_wlz}%)', f.pvv_wlz)

                _line('- Algemene heffingskorting', f.ahk)
                _line('- Arbeidskorting', f.arbeidskorting)
                ui.separator().classes('my-1')
                _invulhulp_line(BD['netto_ib'], 'Netto IB', f.netto_ib, bold=True)

            # Card 3: ZVW
            with ui.card().classes('w-full'):
                ui.label('ZVW-bijdrage').classes('text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')
                _line(f'Grondslag (belastbare winst, max {format_euro(params_dict.get("zvw_max_grondslag", 0))})',
                      min(f.belastbare_winst, params_dict.get('zvw_max_grondslag', 0)))
                _line(f'Percentage: {params_dict.get("zvw_pct", 0)}%', 0, bold=False)
                _invulhulp_line(BD['zvw'], 'ZVW-bijdrage', f.zvw, bold=True)

            # Card 4: Box 3
            if box3.belasting > 0:
                with ui.card().classes('w-full'):
                    ui.label('Box 3').classes('text-subtitle1 text-weight-bold')
                    ui.separator().classes('my-1')
                    _line('Grondslag', box3.grondslag)
                    _invulhulp_line(BD['box3_belasting'], 'Box 3 belasting',
                                    box3.belasting, bold=True)

            # Card 5: Resultaat
            with ui.card().classes('w-full').style(
                    'border: 2px solid #0d9488; background: #f0fdfa'):
                ui.label('Resultaat').classes('text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')

                if f.voorlopige_aanslag > 0 or f.voorlopige_aanslag_zvw > 0:
                    _result_color_line(
                        f'IB: {format_euro(f.netto_ib)} - VA {format_euro(f.voorlopige_aanslag)}',
                        f.resultaat_ib)
                    _result_color_line(
                        f'ZVW: {format_euro(f.zvw)} - VA {format_euro(f.voorlopige_aanslag_zvw)}',
                        f.resultaat_zvw)

                if box3.belasting > 0:
                    _result_color_line('Box 3', box3.belasting)

                ui.separator().classes('my-1')

                totaal = f.resultaat + box3.belasting
                if totaal < 0:
                    with ui.row().classes('w-full justify-between items-center'):
                        ui.label('Totaal terug te ontvangen').classes('text-bold text-h6')
                        with ui.row().classes('items-center gap-2'):
                            ui.label(format_euro(abs(totaal))).classes(
                                'text-bold text-h6 text-positive')
                            ui.button(icon='content_copy',
                                      on_click=lambda: _copy_value(abs(totaal), 'Totaal terug')) \
                                .props('round color=positive size=sm')
                elif totaal > 0:
                    with ui.row().classes('w-full justify-between items-center'):
                        ui.label('Totaal bij te betalen').classes('text-bold text-h6')
                        with ui.row().classes('items-center gap-2'):
                            ui.label(format_euro(totaal)).classes(
                                'text-bold text-h6 text-negative')
                            ui.button(icon='content_copy',
                                      on_click=lambda: _copy_value(totaal, 'Totaal bij')) \
                                .props('round color=negative size=sm')
                else:
                    with ui.row().classes('w-full justify-between items-center'):
                        ui.label('Resultaat').classes('text-bold text-h6')
                        ui.label(format_euro(0)).classes('text-bold text-h6')

    # ============================================================
    # Tab 5: Documenten
    # ============================================================

    async def render_progress(docs):
        progress_container.clear()
        uploaded_types = {d.documenttype for d in docs}

        pdf_dir = DB_PATH.parent / 'pdf' / str(state['jaar'])
        auto_done = any(
            f.name.startswith('Jaarcijfers')
            for f in pdf_dir.glob('*.pdf')
        ) if pdf_dir.exists() else False

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

        docs_by_type: dict[str, list] = {}
        for d in docs:
            docs_by_type.setdefault(d.documenttype, []).append(d)

        pdf_dir = DB_PATH.parent / 'pdf' / str(state['jaar'])
        auto_done = any(
            f.name.startswith('Jaarcijfers')
            for f in pdf_dir.glob('*.pdf')
        ) if pdf_dir.exists() else False

        categories: dict[str, list[DocSpec]] = {}
        for item in AANGIFTE_DOCS:
            categories.setdefault(item.categorie, []).append(item)

        with checklist_container:
            for cat_key, items in categories.items():
                cat_label = CATEGORIE_LABELS.get(cat_key, cat_key)
                with ui.card().classes('w-full'):
                    ui.label(cat_label).classes('text-subtitle1 text-weight-bold')
                    ui.separator()

                    for spec in items:
                        existing = docs_by_type.get(spec.documenttype, [])
                        is_auto = spec.documenttype in AUTO_TYPES
                        has_doc = len(existing) > 0 or (is_auto and auto_done)

                        with ui.row().classes('w-full items-center q-py-xs gap-2'):
                            if has_doc:
                                ui.icon('check_circle', color='positive').classes('text-lg')
                            else:
                                ui.icon('radio_button_unchecked', color='grey-5').classes('text-lg')

                            label_text = spec.label
                            if spec.verplicht and not is_auto:
                                label_text += ' *'
                            ui.label(label_text).classes('flex-grow')

                            if is_auto:
                                ui.button(
                                    'Ga naar Jaarafsluiting', icon='link',
                                    on_click=lambda: ui.navigate.to('/jaarafsluiting'),
                                ).props('flat dense color=primary size=sm')
                                continue

                            if spec.meerdere or not existing:
                                ui.button(
                                    'Uploaden', icon='upload',
                                    on_click=lambda dt=spec.documenttype,
                                    c=spec.categorie:
                                    open_upload_dialog(c, dt),
                                ).props('flat dense color=primary size=sm')

                        for doc in existing:
                            with ui.row().classes('w-full items-center q-pl-xl gap-2'):
                                ui.icon('description', color='grey-6').classes('text-sm')
                                ui.label(doc.bestandsnaam).classes('text-caption text-grey-7')
                                ui.button(icon='download',
                                          on_click=lambda d=doc: do_download(d),
                                          ).props('flat dense round size=xs color=primary')
                                ui.button(icon='delete',
                                          on_click=lambda d=doc: confirm_delete(d),
                                          ).props('flat dense round size=xs color=negative')

    async def open_upload_dialog(categorie: str, documenttype: str):
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Document uploaden').classes('text-subtitle1 text-weight-medium')
            ui.upload(
                auto_upload=True, max_files=1,
                on_upload=lambda e: handle_upload(e, categorie, documenttype, dialog),
            ).props('accept=".pdf,.jpg,.png,.jpeg"').classes('w-full')
            ui.button('Annuleren', on_click=dialog.close).props('flat')
        dialog.open()

    async def handle_upload(e: events.UploadEventArguments,
                            categorie: str, documenttype: str, dialog):
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
        docs = await get_aangifte_documenten(DB_PATH, state['jaar'])
        await render_progress(docs)
        await render_checklist(docs)

    async def do_download(doc):
        if Path(doc.bestandspad).exists():
            ui.download.file(doc.bestandspad)
        else:
            ui.notify(f'{doc.bestandsnaam} niet gevonden op schijf', type='warning')

    async def confirm_delete(doc):
        with ui.dialog() as dialog, ui.card():
            ui.label(f'Weet je zeker dat je "{doc.bestandsnaam}" wilt verwijderen?')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')
                ui.button('Verwijderen', color='negative',
                          on_click=lambda: do_delete(doc, dialog))
        dialog.open()

    async def do_delete(doc, dialog):
        # Delete file first, then DB record (if file fails, DB stays consistent)
        file_path = Path(doc.bestandspad)
        if file_path.exists():
            file_path.unlink()
        await delete_aangifte_document(DB_PATH, doc.id)
        dialog.close()
        ui.notify(f'{doc.bestandsnaam} verwijderd', type='warning')
        docs = await get_aangifte_documenten(DB_PATH, state['jaar'])
        await render_progress(docs)
        await render_checklist(docs)

    # ============================================================
    # Initial render
    # ============================================================
    await refresh_all()
