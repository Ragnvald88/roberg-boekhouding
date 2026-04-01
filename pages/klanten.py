"""Klanten pagina — klantenbeheer met locaties."""

from nicegui import ui

from components.layout import create_layout, page_title
from components.shared_ui import open_klant_dialog
from components.utils import format_euro
from database import (
    get_klanten, delete_klant, update_klant,
    DB_PATH,
)


@ui.page('/klanten')
async def klanten_page():
    create_layout('Klanten', '/klanten')

    # --- Dialog functions (unchanged) ---

    async def open_edit_dialog(row: dict):
        """Open shared klant dialog in edit mode."""
        await open_klant_dialog(
            klant=row,
            on_save=lambda _id, _naam: refresh_klanten(),
        )

    async def on_toggle(row: dict):
        new_actief = 0 if row['actief'] else 1
        await update_klant(DB_PATH, klant_id=row['id'],
                           actief=new_actief)
        status = 'geactiveerd' if new_actief else 'gedeactiveerd'
        ui.notify(f"{row['naam']} {status}", type='info')
        await refresh_klanten()

    async def on_delete_klant(row: dict):
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

    async def open_add_dialog():
        """Open shared klant dialog in add mode."""
        await open_klant_dialog(
            on_save=lambda _id, _naam: refresh_klanten(),
        )

    # --- Refresh: only update data ---

    async def refresh_klanten():
        """Reload klanten table rows (preserves pagination/sort state)."""
        klanten = await get_klanten(DB_PATH)
        rows = [{
            'id': k.id,
            'naam': k.naam,
            'tarief_uur': k.tarief_uur,
            'tarief_fmt': format_euro(k.tarief_uur),
            'retour_km': k.retour_km,
            'adres': k.adres,
            'kvk': k.kvk,
            'email': k.email,
            'contactpersoon': k.contactpersoon,
            'postcode': k.postcode,
            'plaats': k.plaats,
            'actief': k.actief,
            'actief_txt': 'Ja' if k.actief else 'Nee',
        } for k in klanten]
        _tbl.rows = rows
        _tbl.update()

    # === PAGE LAYOUT (created once) ===

    columns = [
        {'name': 'naam', 'label': 'Naam', 'field': 'naam',
         'align': 'left', 'sortable': True},
        {'name': 'tarief', 'label': 'Tarief/uur',
         'field': 'tarief_fmt', 'align': 'right', 'sortable': True},
        {'name': 'km', 'label': 'Retour km', 'field': 'retour_km',
         'align': 'right', 'sortable': True},
        {'name': 'adres', 'label': 'Adres', 'field': 'adres',
         'align': 'left'},
        {'name': 'actief', 'label': 'Actief', 'field': 'actief_txt',
         'align': 'center'},
        {'name': 'actions', 'label': '', 'field': 'actions',
         'align': 'center'},
    ]

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        # Header row: title + action
        with ui.row().classes('w-full items-center'):
            page_title('Klanten')
            ui.space()
            ui.button(
                'Nieuwe klant', icon='add',
                on_click=lambda: open_add_dialog(),
            ).props('color=primary')

        # --- Table (created once, rows updated via refresh_klanten) ---
        _tbl = ui.table(
            columns=columns, rows=[], row_key='id',
            pagination={'rowsPerPage': 20,
                        'rowsPerPageOptions': [10, 20, 50, 0]},
        ).classes('w-full')

        _tbl.add_slot('body-cell-actions', '''
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

        _tbl.add_slot('no-data', '''
            <q-tr><q-td colspan="100%" class="text-center q-pa-lg text-grey">
                Geen klanten gevonden.
            </q-td></q-tr>
        ''')

        _tbl.on('edit', lambda e: open_edit_dialog(e.args))
        _tbl.on('toggle', lambda e: on_toggle(e.args))
        _tbl.on('deleteklant', lambda e: on_delete_klant(e.args))

    # Initial load
    await refresh_klanten()
