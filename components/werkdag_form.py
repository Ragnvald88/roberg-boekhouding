"""Werkdag dialog — add/edit werkdag via popup."""

from nicegui import ui
from components.utils import format_euro
from database import (
    get_klanten, add_werkdag, update_werkdag, get_fiscale_params,
    get_klant_locaties, DB_PATH,
)
from datetime import date

_KM_TARIEF_FALLBACK = 0.23

# Activiteitscodes
CODES = {
    'WERKDAG': 'Waarneming dagpraktijk',
    'WEEKEND_DAG': 'Waarneming weekenddienst (dag)',
    'AVOND': 'Waarneming avonddienst',
    'NACHT': 'Waarneming nachtdienst',
    'ACHTERWACHT': 'Achterwacht',
    'ANW_AVOND': 'ANW avonddienst',
    'ANW_NACHT': 'ANW nachtdienst',
    'ANW_WEEKEND': 'ANW weekenddienst',
}


async def open_werkdag_dialog(on_save=None, werkdag=None):
    """Open dialog for adding or editing a werkdag.

    Args:
        on_save: async callback after successful save (e.g. refresh table)
        werkdag: existing Werkdag object for edit mode, None for add mode
    """
    klanten = await get_klanten(DB_PATH, alleen_actief=True)
    klant_options = {k.id: k.naam for k in klanten}
    klant_data = {k.id: k for k in klanten}

    # Edit mode: ensure the werkdag's klant is in the options even if inactive
    if werkdag and werkdag.klant_id not in klant_options:
        alle_klanten = await get_klanten(DB_PATH, alleen_actief=False)
        for k in alle_klanten:
            if k.id == werkdag.klant_id:
                klant_options[k.id] = f'{k.naam} (inactief)'
                klant_data[k.id] = k
                break

    is_edit = werkdag is not None

    # Cache for loaded locations per klant
    locatie_data = {}  # klant_id -> list[KlantLocatie]

    # Get default km_tarief from fiscal params
    fp = await get_fiscale_params(DB_PATH, jaar=date.today().year)
    default_km_tarief = fp.km_tarief if fp else _KM_TARIEF_FALLBACK

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg q-pa-md'):
        title_label = ui.label(
            'Werkdag bewerken' if is_edit else 'Werkdag toevoegen'
        ).classes('text-h6 q-mb-md')

        # Row 1: Datum + Klant
        with ui.row().classes('w-full gap-4 items-end'):
            datum_input = ui.input(
                'Datum',
                value=werkdag.datum if is_edit else date.today().isoformat(),
            ).classes('w-40')
            with datum_input:
                with ui.menu().props('no-parent-event') as menu:
                    with ui.date(
                        value=werkdag.datum if is_edit else date.today().isoformat(),
                    ).bind_value(datum_input) as date_picker:
                        date_picker.on('update:model-value', lambda: menu.close())
                with datum_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu.open) \
                        .classes('cursor-pointer')

            klant_select = ui.select(
                klant_options,
                value=werkdag.klant_id if is_edit else None,
                label='Klant',
            ).classes('w-48')

        # Location row (hidden by default, shown when klant has locations)
        locatie_row = ui.row().classes('w-full gap-4')
        locatie_row.set_visibility(False)
        with locatie_row:
            locatie_select = ui.select(
                {}, label='Locatie', value=None,
                on_change=lambda e: on_locatie_change(e.value),
            ).classes('flex-grow')

        # Row 2: Code + Uren
        code_options = {k: k for k in CODES.keys()}
        if is_edit and werkdag.code and werkdag.code not in code_options:
            # Legacy/imported code not in standard list — include it
            code_options[werkdag.code] = werkdag.code
        initial_code = werkdag.code if is_edit and werkdag.code in code_options else 'WERKDAG'

        with ui.row().classes('w-full gap-4 items-end'):
            code_select = ui.select(
                code_options,
                value=initial_code,
                label='Code',
            ).classes('w-40')

            uren_input = ui.number(
                'Uren', value=werkdag.uren if is_edit else 8,
                min=0.5, max=24, step=0.5,
            ).classes('w-24')

        # Row 3: Tarief + Km (editable, auto-fill from klant)
        with ui.row().classes('w-full gap-4 items-end'):
            tarief_input = ui.number(
                'Tarief (\u20ac/uur)',
                value=werkdag.tarief if is_edit else 0,
                format='%.2f', min=0, step=0.50,
            ).classes('w-36')

            km_input = ui.number(
                'Km (retour)',
                value=werkdag.km if is_edit else 0,
                min=0, step=1,
            ).classes('w-28')

            km_tarief_input = ui.number(
                'Km-tarief (\u20ac/km)',
                value=werkdag.km_tarief if is_edit else default_km_tarief,
                format='%.2f', min=0, step=0.01,
            ).classes('w-36')

        # Urennorm
        urennorm_check = ui.checkbox(
            'Telt mee voor urencriterium',
            value=werkdag.urennorm if is_edit else True,
        )

        # Opmerking
        opmerking_input = ui.input(
            'Opmerking', value=werkdag.opmerking if is_edit else '',
        ).classes('w-full')

        # Live total
        totaal_label = ui.label('').classes('text-body1 text-weight-bold') \
            .style('color: #0F172A')

        def update_totaal():
            u = uren_input.value or 0
            t = tarief_input.value or 0
            km = km_input.value or 0
            kmt = km_tarief_input.value or 0
            totaal = u * t + km * kmt
            parts = []
            if t:
                parts.append(f'{u} \u00d7 {format_euro(t)}')
            if km and kmt:
                parts.append(f'{km:.0f} km \u00d7 {format_euro(kmt)}')
            calc = ' + '.join(parts)
            totaal_label.text = f'{calc} = {format_euro(totaal)}' if calc else ''

        def on_locatie_change(loc_id):
            kid = klant_select.value
            if loc_id and kid in locatie_data:
                for loc in locatie_data[kid]:
                    if loc.id == loc_id:
                        km_input.value = loc.retour_km
                        break
            update_totaal()

        # Auto-fill tarief/km when klant changes, load locations
        async def on_klant_change(e):
            kid = e.value
            if kid and kid in klant_data:
                k = klant_data[kid]
                tarief_input.value = k.tarief_uur

                # Load locations for this klant
                locaties = await get_klant_locaties(DB_PATH, kid)
                locatie_data[kid] = locaties
                if locaties:
                    loc_options = {loc.id: f"{loc.naam} ({loc.retour_km} km)"
                                   for loc in locaties}
                    locatie_select.options = loc_options
                    locatie_select.update()
                    locatie_row.set_visibility(True)

                    # Pre-select first location
                    first_loc = locaties[0]
                    locatie_select.value = first_loc.id
                    km_input.value = first_loc.retour_km
                else:
                    locatie_row.set_visibility(False)
                    locatie_select.value = None
                    km_input.value = k.retour_km
            else:
                locatie_row.set_visibility(False)
                locatie_select.value = None
            update_totaal()

        klant_select.on_value_change(on_klant_change)
        uren_input.on_value_change(lambda _: update_totaal())
        tarief_input.on_value_change(lambda _: update_totaal())
        km_input.on_value_change(lambda _: update_totaal())
        km_tarief_input.on_value_change(lambda _: update_totaal())

        # Auto-toggle urennorm for ACHTERWACHT
        def on_code_change(e):
            if e.value == 'ACHTERWACHT':
                urennorm_check.value = False
            else:
                urennorm_check.value = True

        code_select.on_value_change(on_code_change)

        # Edit mode: load locations for existing werkdag's klant
        if is_edit:
            await on_klant_change(type('E', (), {'value': werkdag.klant_id})())
            # Try to match existing locatie by name
            if werkdag.locatie and klant_select.value in locatie_data:
                for loc in locatie_data[klant_select.value]:
                    if loc.naam == werkdag.locatie:
                        locatie_select.value = loc.id
                        km_input.value = loc.retour_km
                        break
            # Restore the actual km from the werkdag (may differ from location default)
            km_input.value = werkdag.km

        # Initial calculation
        update_totaal()

        async def save(and_new: bool = False):
            kid = klant_select.value
            if not kid:
                ui.notify('Selecteer een klant', type='warning')
                return
            if not uren_input.value or uren_input.value <= 0:
                ui.notify('Vul het aantal uren in', type='warning')
                return
            if tarief_input.value is None or tarief_input.value < 0:
                ui.notify('Vul een tarief in', type='warning')
                return
            k = klant_data[kid]
            code = code_select.value or 'WERKDAG'
            activiteit = CODES.get(code, 'Waarneming dagpraktijk')

            # Determine locatie text from selected location
            loc_id = locatie_select.value
            loc_naam = ''
            if loc_id and kid in locatie_data:
                for loc in locatie_data[kid]:
                    if loc.id == loc_id:
                        loc_naam = loc.naam
                        break
            locatie_text = loc_naam or k.adres

            kwargs = dict(
                datum=datum_input.value,
                klant_id=kid,
                code=code,
                activiteit=activiteit,
                locatie=locatie_text,
                locatie_id=loc_id if loc_id else None,
                uren=uren_input.value,
                km=km_input.value,
                tarief=tarief_input.value,
                km_tarief=km_tarief_input.value,
                urennorm=1 if urennorm_check.value else 0,
                opmerking=opmerking_input.value or '',
            )

            try:
                if is_edit:
                    await update_werkdag(DB_PATH, werkdag_id=werkdag.id, **kwargs)
                    ui.notify('Werkdag bijgewerkt', type='positive')
                else:
                    await add_werkdag(DB_PATH, **kwargs)
                    ui.notify('Werkdag toegevoegd', type='positive')
            except Exception as e:
                ui.notify(str(e), type='negative')
                return

            if on_save:
                await on_save()

            if and_new and not is_edit:
                # Reset form for next entry — keep klant, location, tarief, km, km-tarief
                datum_input.value = date.today().isoformat()
                code_select.value = 'WERKDAG'
                uren_input.value = 8
                urennorm_check.value = True
                opmerking_input.value = ''
                update_totaal()
            else:
                dialog.close()

        # Buttons
        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
            ui.button('Annuleren', on_click=dialog.close).props('flat')
            if not is_edit:
                ui.button(
                    'Opslaan & Nieuw', icon='add',
                    on_click=lambda: save(and_new=True),
                ).props('outline color=primary')
            ui.button(
                'Opslaan', icon='save',
                on_click=lambda: save(and_new=False),
            ).props('color=primary')

    dialog.open()
