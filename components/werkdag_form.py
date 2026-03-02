"""Herbruikbaar werkdag formulier component."""

from nicegui import ui
from components.utils import format_euro
from database import get_klanten, add_werkdag, update_werkdag, get_fiscale_params, DB_PATH
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


async def werkdag_form(on_save=None, werkdag=None):
    """Render werkdag add/edit form. werkdag=None for new entry."""
    klanten = await get_klanten(DB_PATH, alleen_actief=True)
    klant_options = {k.id: k.naam for k in klanten}
    klant_data = {k.id: k for k in klanten}

    is_edit = werkdag is not None

    # Get km_tarief from fiscal params for the current year (or from werkdag in edit mode)
    if is_edit:
        km_tarief = werkdag.km_tarief or _KM_TARIEF_FALLBACK
    else:
        fp = await get_fiscale_params(DB_PATH, jaar=date.today().year)
        km_tarief = fp.km_tarief if fp else _KM_TARIEF_FALLBACK

    # State
    selected_klant = werkdag.klant_id if is_edit else None
    current_tarief = werkdag.tarief if is_edit else 0
    current_km = werkdag.km if is_edit else 0

    with ui.card().classes('w-full q-pa-md'):
        ui.label('Werkdag bewerken' if is_edit else 'Werkdag toevoegen') \
            .classes('text-h6 q-mb-md')

        with ui.row().classes('w-full gap-4 items-end'):
            # Datum
            datum_input = ui.input(
                'Datum',
                value=werkdag.datum if is_edit else date.today().isoformat()
            ).classes('w-40')
            with datum_input:
                with ui.menu().props('no-parent-event') as menu:
                    with ui.date(
                        value=werkdag.datum if is_edit else date.today().isoformat()
                    ).bind_value(datum_input) as date_picker:
                        date_picker.on('update:model-value', lambda: menu.close())
                with datum_input.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu.open).classes('cursor-pointer')

            # Klant
            klant_select = ui.select(
                klant_options,
                value=selected_klant,
                label='Klant',
            ).classes('w-48')

        with ui.row().classes('w-full gap-4 items-end'):
            # Code/Activiteit
            code_select = ui.select(
                {k: k for k in CODES.keys()},
                value=werkdag.code if is_edit else 'WERKDAG',
                label='Code',
            ).classes('w-40')

            # Uren
            uren_input = ui.number(
                'Uren', value=werkdag.uren if is_edit else 8,
                min=0.5, max=24, step=0.5,
            ).classes('w-24')

            # Urennorm
            urennorm_check = ui.checkbox(
                'Telt mee voor urencriterium',
                value=werkdag.urennorm if is_edit else True,
            )

        # Auto-calculated display
        tarief_label = ui.label('').classes('text-body2').style('color: #64748B')
        km_label = ui.label('').classes('text-body2').style('color: #64748B')
        totaal_label = ui.label('').classes('text-body1 text-weight-bold') \
            .style('color: #0F172A')

        # Opmerking
        opmerking_input = ui.input(
            'Opmerking', value=werkdag.opmerking if is_edit else ''
        ).classes('w-full')

        def update_calculations():
            kid = klant_select.value
            if kid and kid in klant_data:
                k = klant_data[kid]
                t = k.tarief_uur
                km = k.retour_km
                u = uren_input.value or 0
                tarief_label.text = f'Tarief: {format_euro(t)}/uur'
                km_label.text = f'Reiskosten: {km} km × {format_euro(km_tarief)} = {format_euro(km * km_tarief)}'
                totaal_label.text = f'Totaal: {u} × {format_euro(t)} + {format_euro(km * km_tarief)} = {format_euro(u * t + km * km_tarief)}'
            else:
                tarief_label.text = ''
                km_label.text = ''
                totaal_label.text = ''

        klant_select.on_value_change(lambda _: update_calculations())
        uren_input.on_value_change(lambda _: update_calculations())

        # Set initial calculations for edit mode
        if is_edit:
            update_calculations()

        # Update urennorm based on code
        def on_code_change(e):
            if e.value == 'ACHTERWACHT':
                urennorm_check.value = False
            else:
                urennorm_check.value = True

        code_select.on_value_change(on_code_change)

        async def save():
            kid = klant_select.value
            if not kid:
                ui.notify('Selecteer een klant', type='warning')
                return
            k = klant_data[kid]
            code = code_select.value or 'WERKDAG'
            activiteit = CODES.get(code, 'Waarneming dagpraktijk')

            kwargs = dict(
                datum=datum_input.value,
                klant_id=kid,
                code=code,
                activiteit=activiteit,
                locatie=k.adres,
                uren=uren_input.value,
                km=k.retour_km,
                tarief=k.tarief_uur,
                km_tarief=km_tarief,
                urennorm=1 if urennorm_check.value else 0,
                opmerking=opmerking_input.value or '',
            )

            if is_edit:
                await update_werkdag(DB_PATH, werkdag_id=werkdag.id, **kwargs)
                ui.notify('Werkdag bijgewerkt', type='positive')
            else:
                await add_werkdag(DB_PATH, **kwargs)
                ui.notify('Werkdag toegevoegd', type='positive')

            if on_save:
                await on_save()

        ui.button(
            'Opslaan' if is_edit else 'Toevoegen',
            on_click=save, icon='save'
        ).props('color=primary').classes('q-mt-md')
