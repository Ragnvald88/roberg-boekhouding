"""Klanten pagina — klantenbeheer met locaties."""

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import format_euro
from database import (
    get_klanten, add_klant, update_klant, delete_klant,
    get_klant_locaties, add_klant_locatie, delete_klant_locatie,
    DB_PATH,
)


@ui.page('/klanten')
async def klanten_page():
    create_layout('Klanten', '/klanten')

    klanten_container = {'ref': None}

    async def refresh_klanten():
        container = klanten_container['ref']
        if container is None:
            return
        container.clear()
        klanten = await get_klanten(DB_PATH)

        with container:
            # Add button
            with ui.row().classes('w-full items-center gap-4'):
                page_title('Klanten')
                ui.space()
                ui.button(
                    'Nieuwe klant', icon='add',
                    on_click=lambda: open_add_dialog(),
                ).props('color=primary')

            # Klanten table
            if not klanten:
                ui.label('Geen klanten gevonden.').classes('text-grey')
            else:
                columns = [
                    {'name': 'naam', 'label': 'Naam', 'field': 'naam',
                     'align': 'left'},
                    {'name': 'tarief', 'label': 'Tarief/uur',
                     'field': 'tarief_fmt', 'align': 'right'},
                    {'name': 'km', 'label': 'Retour km', 'field': 'retour_km',
                     'align': 'right'},
                    {'name': 'adres', 'label': 'Adres', 'field': 'adres',
                     'align': 'left'},
                    {'name': 'actief', 'label': 'Actief', 'field': 'actief_txt',
                     'align': 'center'},
                    {'name': 'actions', 'label': '', 'field': 'actions',
                     'align': 'center'},
                ]

                rows = [{
                    'id': k.id,
                    'naam': k.naam,
                    'tarief_uur': k.tarief_uur,
                    'tarief_fmt': format_euro(k.tarief_uur),
                    'retour_km': k.retour_km,
                    'adres': k.adres,
                    'actief': k.actief,
                    'actief_txt': 'Ja' if k.actief else 'Nee',
                } for k in klanten]

                table = ui.table(
                    columns=columns, rows=rows, row_key='id',
                    pagination={'rowsPerPage': 20,
                                'rowsPerPageOptions': [10, 20, 50, 0]},
                ).classes('w-full')

                table.add_slot('body-cell-actions', '''
                    <q-td :props="props">
                        <q-btn icon="edit" flat dense round size="sm"
                            @click="() => $parent.$emit('edit', props.row)" />
                        <q-btn :icon="props.row.actief ? 'visibility_off' : 'visibility'"
                            flat dense round size="sm"
                            :color="props.row.actief ? 'orange' : 'green'"
                            @click="() => $parent.$emit('toggle', props.row)" />
                        <q-btn icon="delete" flat dense round size="sm"
                            color="negative"
                            @click="() => $parent.$emit('deleteklant', props.row)" />
                    </q-td>
                ''')

                async def on_edit(e):
                    row = e.args
                    with ui.dialog() as dialog, ui.card().classes('w-96'):
                        ui.label('Klant bewerken').classes('text-h6')
                        ed_naam = ui.input('Naam', value=row['naam']).classes('w-full')
                        ed_tarief = ui.number('Tarief/uur (€)',
                                              value=row['tarief_uur']).classes('w-full')
                        ed_km = ui.number('Retour km',
                                          value=row['retour_km']).classes('w-full')
                        ed_adres = ui.input('Adres',
                                            value=row['adres']).classes('w-full')

                        # --- Locaties sub-section ---
                        ui.separator().classes('q-my-sm')
                        ui.label('Locaties').classes(
                            'text-subtitle2 text-weight-medium')
                        ui.label(
                            'Werklocaties met retourafstand (km). '
                            'Verschijnt als dropdown in het '
                            'werkdagformulier.'
                        ).classes('text-caption text-grey')

                        loc_container = ui.column().classes('w-full gap-1')

                        async def refresh_locaties():
                            loc_container.clear()
                            klant_id = row['id']
                            locaties = await get_klant_locaties(
                                DB_PATH, klant_id)
                            with loc_container:
                                for loc in locaties:
                                    with ui.row().classes(
                                        'w-full items-center gap-2'
                                    ):
                                        ui.label(loc.naam).classes('flex-grow')
                                        ui.label(
                                            f'{loc.retour_km:.0f} km'
                                        ).classes('text-caption text-grey')

                                        async def del_loc(
                                            lid=loc.id, lnaam=loc.naam,
                                        ):
                                            with ui.dialog() as cdlg, \
                                                    ui.card():
                                                ui.label(
                                                    f'Locatie "{lnaam}" '
                                                    'verwijderen?'
                                                ).classes('text-h6')
                                                with ui.row().classes(
                                                    'w-full justify-end '
                                                    'gap-2 mt-2'
                                                ):
                                                    ui.button(
                                                        'Annuleren',
                                                        on_click=cdlg.close,
                                                    ).props('flat')

                                                    async def do_del(_lid=lid):
                                                        await delete_klant_locatie(
                                                            DB_PATH, _lid)
                                                        cdlg.close()
                                                        ui.notify(
                                                            'Locatie verwijderd',
                                                            type='info')
                                                        await refresh_locaties()

                                                    ui.button(
                                                        'Verwijderen',
                                                        on_click=do_del,
                                                    ).props('color=negative')
                                            cdlg.open()

                                        ui.button(
                                            icon='close',
                                            on_click=del_loc,
                                        ).props(
                                            'flat dense round '
                                            'size=sm color=negative'
                                        )

                                # Add new location row
                                with ui.row().classes(
                                    'w-full items-end gap-2'
                                ):
                                    new_loc_naam = ui.input(
                                        'Locatienaam',
                                    ).classes('flex-grow').props('dense')
                                    new_loc_km = ui.number(
                                        'Km retour', value=0, min=0,
                                    ).classes('w-24').props('dense')

                                    async def add_loc():
                                        naam = new_loc_naam.value
                                        km = new_loc_km.value or 0
                                        if not naam:
                                            ui.notify(
                                                'Vul een locatienaam in',
                                                type='warning')
                                            return
                                        try:
                                            await add_klant_locatie(
                                                DB_PATH, row['id'], naam, km)
                                        except Exception:
                                            ui.notify(
                                                f'Locatie "{naam}" bestaat al',
                                                type='warning')
                                            return
                                        ui.notify(
                                            f'Locatie "{naam}" toegevoegd',
                                            type='positive')
                                        await refresh_locaties()

                                    ui.button(
                                        icon='add', on_click=add_loc,
                                    ).props('flat dense round color=primary')

                        await refresh_locaties()

                        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                            ui.button('Annuleren', on_click=dialog.close).props('flat')

                            async def save_edit():
                                await update_klant(
                                    DB_PATH, klant_id=row['id'],
                                    naam=ed_naam.value,
                                    tarief_uur=ed_tarief.value,
                                    retour_km=ed_km.value,
                                    adres=ed_adres.value,
                                )
                                dialog.close()
                                ui.notify('Klant bijgewerkt', type='positive')
                                await refresh_klanten()

                            ui.button('Opslaan', on_click=save_edit) \
                                .props('color=primary')
                    dialog.open()

                async def on_toggle(e):
                    row = e.args
                    new_actief = 0 if row['actief'] else 1
                    await update_klant(DB_PATH, klant_id=row['id'],
                                       actief=new_actief)
                    status = 'geactiveerd' if new_actief else 'gedeactiveerd'
                    ui.notify(f"{row['naam']} {status}", type='info')
                    await refresh_klanten()

                async def on_delete_klant(e):
                    row = e.args
                    with ui.dialog() as dialog, ui.card():
                        ui.label(f"Klant '{row['naam']}' verwijderen?").classes('text-h6')
                        ui.label(
                            'Verwijderen is alleen mogelijk als er geen '
                            'werkdagen of facturen aan deze klant gekoppeld zijn.'
                        ).classes('text-body2 text-grey')
                        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                            ui.button('Annuleren', on_click=dialog.close).props('flat')

                            async def confirm_del(kid=row['id'], dlg=dialog):
                                try:
                                    await delete_klant(DB_PATH, klant_id=kid)
                                    dlg.close()
                                    ui.notify('Klant verwijderd', type='positive')
                                    await refresh_klanten()
                                except ValueError as exc:
                                    ui.notify(str(exc), type='negative')

                            ui.button('Verwijderen', on_click=confirm_del) \
                                .props('color=negative')
                    dialog.open()

                table.on('edit', on_edit)
                table.on('toggle', on_toggle)
                table.on('deleteklant', on_delete_klant)

    async def open_add_dialog():
        """Dialog to add a new klant."""
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg q-pa-md'):
            ui.label('Klant toevoegen').classes('text-h6 q-mb-md')
            new_naam = ui.input('Naam').classes('w-full')
            new_tarief = ui.number('Tarief/uur (€)', value=0,
                                    min=0, step=0.50).classes('w-full')
            new_km = ui.number('Retour km', value=0, min=0).classes('w-full')
            new_adres = ui.input('Adres').classes('w-full')

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')

                async def add_new():
                    if not new_naam.value:
                        ui.notify('Vul een naam in', type='warning')
                        return
                    await add_klant(DB_PATH, naam=new_naam.value,
                                    tarief_uur=new_tarief.value or 0,
                                    retour_km=new_km.value or 0,
                                    adres=new_adres.value or '')
                    ui.notify(f'Klant {new_naam.value} toegevoegd',
                              type='positive')
                    dialog.close()
                    await refresh_klanten()

                ui.button('Toevoegen', icon='add',
                          on_click=add_new).props('color=primary')
        dialog.open()

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        klanten_container['ref'] = ui.column().classes('w-full gap-4')

    await refresh_klanten()
