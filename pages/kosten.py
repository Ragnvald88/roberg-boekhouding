"""Kosten pagina — uitgaven registratie + categorisatie."""

from datetime import date
from pathlib import Path

from nicegui import ui

from components.layout import create_layout
from database import (
    add_uitgave, delete_uitgave, get_uitgaven, get_uitgaven_per_categorie,
    update_uitgave,
)

DB_PATH = Path("data/boekhouding.sqlite3")

CATEGORIEEN = [
    'Pensioenpremie SPH',
    'Telefoon/KPN',
    'Verzekeringen',
    'Accountancy/software',
    'Representatie',
    'Lidmaatschappen',
    'Kleine aankopen',
    'Scholingskosten',
    'Bankkosten',
    'Investeringen',
]

LEVENSDUUR_OPTIES = {3: '3 jaar', 4: '4 jaar', 5: '5 jaar'}


def format_euro(value: float) -> str:
    """Format float as Dutch euro string: € 1.234,56"""
    return f"€ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@ui.page('/kosten')
async def kosten_page():
    create_layout('Kosten', '/kosten')

    # --- State ---
    huidig_jaar = date.today().year
    jaren = list(range(huidig_jaar, 2022, -1))  # 2026 down to 2023
    filter_jaar = {'value': huidig_jaar}
    filter_categorie = {'value': None}  # None = alle

    # References to dynamic UI elements
    tabel_container = {'ref': None}
    summary_container = {'ref': None}

    # --- Helpers ---

    async def laad_tabel():
        """Reload the expenses table based on current filters."""
        container = tabel_container['ref']
        if container is None:
            return
        container.clear()
        jaar = filter_jaar['value']
        cat = filter_categorie['value']
        uitgaven = await get_uitgaven(DB_PATH, jaar=jaar, categorie=cat)

        rows = []
        for u in uitgaven:
            rows.append({
                'id': u.id,
                'datum': u.datum,
                'categorie': u.categorie,
                'omschrijving': u.omschrijving,
                'bedrag': u.bedrag,
                'bedrag_fmt': format_euro(u.bedrag),
                'investering': 'Ja' if u.is_investering else 'Nee',
                'is_investering': u.is_investering,
                'restwaarde_pct': u.restwaarde_pct,
                'levensduur_jaren': u.levensduur_jaren,
                'zakelijk_pct': u.zakelijk_pct,
            })

        columns = [
            {'name': 'datum', 'label': 'Datum', 'field': 'datum', 'sortable': True,
             'align': 'left'},
            {'name': 'categorie', 'label': 'Categorie', 'field': 'categorie',
             'sortable': True, 'align': 'left'},
            {'name': 'omschrijving', 'label': 'Omschrijving', 'field': 'omschrijving',
             'align': 'left'},
            {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
             'sortable': True, 'align': 'right'},
            {'name': 'investering', 'label': 'Investering', 'field': 'investering',
             'align': 'center'},
            {'name': 'acties', 'label': 'Acties', 'field': 'acties', 'align': 'center'},
        ]

        with container:
            table = ui.table(
                columns=columns, rows=rows, row_key='id',
                pagination={'rowsPerPage': 20},
            ).classes('w-full')
            table.add_slot('body-cell-acties', '''
                <q-td :props="props">
                    <q-btn flat dense icon="edit" color="primary" size="sm"
                           @click="$parent.$emit('edit', props.row)" />
                    <q-btn flat dense icon="delete" color="negative" size="sm"
                           @click="$parent.$emit('delete', props.row)" />
                </q-td>
            ''')
            table.on('edit', lambda e: open_edit_dialog(e.args))
            table.on('delete', lambda e: confirm_delete(e.args))

    async def laad_summary():
        """Reload the summary card."""
        container = summary_container['ref']
        if container is None:
            return
        container.clear()
        jaar = filter_jaar['value']
        per_cat = await get_uitgaven_per_categorie(DB_PATH, jaar=jaar)
        totaal = sum(r['totaal'] for r in per_cat)

        with container:
            ui.label(f'Kostenoverzicht {jaar}').classes('text-subtitle1 text-bold')
            if per_cat:
                for r in per_cat:
                    with ui.row().classes('w-full justify-between'):
                        ui.label(r['categorie'])
                        ui.label(format_euro(r['totaal'])).classes('text-right')
                ui.separator()
                with ui.row().classes('w-full justify-between'):
                    ui.label('Totaal').classes('text-bold')
                    ui.label(format_euro(totaal)).classes('text-bold text-right')
            else:
                ui.label('Geen uitgaven gevonden.').classes('text-grey')

    async def ververs():
        """Refresh table and summary."""
        await laad_tabel()
        await laad_summary()

    # --- Add expense form ---

    async def opslaan_uitgave():
        """Save new expense from the form."""
        # Validate
        if not input_datum.value:
            ui.notify('Vul een datum in', type='warning')
            return
        if not input_categorie.value:
            ui.notify('Kies een categorie', type='warning')
            return
        if not input_omschrijving.value:
            ui.notify('Vul een omschrijving in', type='warning')
            return
        if not input_bedrag.value or input_bedrag.value <= 0:
            ui.notify('Vul een positief bedrag in', type='warning')
            return

        kwargs = {
            'datum': input_datum.value,
            'categorie': input_categorie.value,
            'omschrijving': input_omschrijving.value,
            'bedrag': float(input_bedrag.value),
        }

        bedrag = float(input_bedrag.value)
        if bedrag >= 450 and input_investering.value:
            kwargs['is_investering'] = 1
            kwargs['levensduur_jaren'] = input_levensduur.value
            kwargs['restwaarde_pct'] = float(input_restwaarde.value or 10)
            kwargs['zakelijk_pct'] = float(input_zakelijk.value or 100)
            kwargs['aanschaf_bedrag'] = bedrag

        await add_uitgave(DB_PATH, **kwargs)
        ui.notify('Uitgave opgeslagen', type='positive')

        # Reset form
        input_datum.value = date.today().isoformat()
        input_categorie.value = None
        input_omschrijving.value = ''
        input_bedrag.value = None
        input_investering.value = False
        input_levensduur.value = 5
        input_restwaarde.value = 10
        input_zakelijk.value = 100
        investering_velden.set_visibility(False)
        representatie_note.set_visibility(False)

        await ververs()

    # --- Edit dialog ---

    async def open_edit_dialog(row: dict):
        """Open dialog to edit an existing expense."""
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Uitgave bewerken').classes('text-h6')

            edit_datum = ui.input('Datum', value=row['datum']).classes('w-full')
            with edit_datum:
                with ui.menu().props('no-parent-event') as menu:
                    with ui.date(value=row['datum']).bind_value(edit_datum) as dp:
                        dp.on('update:model-value', lambda: menu.close())
                with edit_datum.add_slot('append'):
                    ui.icon('edit_calendar').on('click', menu.open).classes(
                        'cursor-pointer')

            edit_categorie = ui.select(
                CATEGORIEEN, label='Categorie', value=row['categorie']
            ).classes('w-full')
            edit_omschrijving = ui.input(
                'Omschrijving', value=row['omschrijving']
            ).classes('w-full')
            edit_bedrag = ui.number(
                'Bedrag incl. BTW (€)', value=row['bedrag'],
                format='%.2f', min=0.01, step=0.01
            ).classes('w-full')

            # Investering fields
            is_inv = row.get('is_investering', False)
            edit_investering = ui.checkbox('Dit is een investering', value=is_inv)
            with ui.column().bind_visibility_from(edit_investering, 'value') as inv_col:
                edit_levensduur = ui.select(
                    LEVENSDUUR_OPTIES, label='Levensduur',
                    value=row.get('levensduur_jaren', 5)
                ).classes('w-full')
                edit_restwaarde = ui.number(
                    'Restwaarde %', value=row.get('restwaarde_pct', 10),
                    min=0, max=100
                ).classes('w-full')
                edit_zakelijk = ui.number(
                    'Zakelijk %', value=row.get('zakelijk_pct', 100),
                    min=0, max=100
                ).classes('w-full')

            # Show investering checkbox only if bedrag >= 450
            def check_edit_bedrag():
                val = edit_bedrag.value or 0
                if val >= 450:
                    edit_investering.set_visibility(True)
                else:
                    edit_investering.set_visibility(False)
                    edit_investering.value = False

            edit_bedrag.on('update:model-value', lambda: check_edit_bedrag())
            # Initial visibility
            if (row.get('bedrag', 0) or 0) < 450:
                edit_investering.set_visibility(False)

            with ui.row().classes('w-full justify-end gap-2 mt-2'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')

                async def bewaar_wijziging():
                    kwargs = {
                        'datum': edit_datum.value,
                        'categorie': edit_categorie.value,
                        'omschrijving': edit_omschrijving.value,
                        'bedrag': float(edit_bedrag.value),
                    }
                    if edit_investering.value:
                        kwargs['is_investering'] = 1
                        kwargs['levensduur_jaren'] = edit_levensduur.value
                        kwargs['restwaarde_pct'] = float(edit_restwaarde.value or 10)
                        kwargs['zakelijk_pct'] = float(edit_zakelijk.value or 100)
                        kwargs['aanschaf_bedrag'] = float(edit_bedrag.value)
                    else:
                        kwargs['is_investering'] = 0
                        kwargs['levensduur_jaren'] = None
                        kwargs['aanschaf_bedrag'] = None
                    await update_uitgave(DB_PATH, uitgave_id=row['id'], **kwargs)
                    ui.notify('Uitgave bijgewerkt', type='positive')
                    dialog.close()
                    await ververs()

                ui.button('Opslaan', on_click=bewaar_wijziging).props('color=primary')
        dialog.open()

    # --- Delete confirmation ---

    async def confirm_delete(row: dict):
        """Confirm and delete an expense."""
        with ui.dialog() as dialog, ui.card():
            ui.label('Weet je zeker dat je deze uitgave wilt verwijderen?')
            ui.label(f"{row['datum']} — {row['omschrijving']} — "
                     f"{format_euro(row['bedrag'])}").classes('text-grey')
            with ui.row().classes('w-full justify-end gap-2 mt-2'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')

                async def verwijder():
                    await delete_uitgave(DB_PATH, uitgave_id=row['id'])
                    ui.notify('Uitgave verwijderd', type='negative')
                    dialog.close()
                    await ververs()

                ui.button('Verwijderen', on_click=verwijder).props('color=negative')
        dialog.open()

    # === PAGE LAYOUT ===

    with ui.column().classes('w-full p-4 max-w-6xl mx-auto gap-4'):

        # --- Filter row ---
        with ui.row().classes('w-full items-center gap-4'):
            ui.label('Filters:').classes('text-subtitle2')
            jaar_select = ui.select(
                {j: str(j) for j in jaren},
                label='Jaar', value=huidig_jaar,
            ).classes('w-32')

            cat_opties = {'': 'Alle'}
            cat_opties.update({c: c for c in CATEGORIEEN})
            cat_select = ui.select(
                cat_opties, label='Categorie', value='',
            ).classes('w-48')

            async def on_filter_change():
                filter_jaar['value'] = jaar_select.value
                filter_categorie['value'] = cat_select.value or None
                await ververs()

            jaar_select.on('update:model-value', lambda: on_filter_change())
            cat_select.on('update:model-value', lambda: on_filter_change())

        # --- Add form ---
        with ui.card().classes('w-full'):
            ui.label('Uitgave toevoegen').classes('text-subtitle1 text-bold')
            with ui.row().classes('w-full items-end gap-4 flex-wrap'):
                input_datum = ui.input(
                    'Datum', value=date.today().isoformat()
                ).classes('w-40')
                with input_datum:
                    with ui.menu().props('no-parent-event') as datum_menu:
                        with ui.date(value=date.today().isoformat()).bind_value(
                                input_datum) as datum_picker:
                            datum_picker.on('update:model-value',
                                            lambda: datum_menu.close())
                    with input_datum.add_slot('append'):
                        ui.icon('edit_calendar').on('click', datum_menu.open).classes(
                            'cursor-pointer')

                input_categorie = ui.select(
                    CATEGORIEEN, label='Categorie', value=None,
                ).classes('w-48')

                input_omschrijving = ui.input('Omschrijving').classes('w-64')

                input_bedrag = ui.number(
                    'Bedrag incl. BTW (€)', format='%.2f',
                    min=0.01, step=0.01,
                ).classes('w-40')

            # Investering section (conditionally shown)
            input_investering = ui.checkbox('Dit is een investering', value=False)
            input_investering.set_visibility(False)

            investering_velden = ui.column().classes('pl-8 gap-2')
            investering_velden.set_visibility(False)
            with investering_velden:
                with ui.row().classes('items-end gap-4'):
                    input_levensduur = ui.select(
                        LEVENSDUUR_OPTIES, label='Levensduur', value=5,
                    ).classes('w-32')
                    input_restwaarde = ui.number(
                        'Restwaarde %', value=10, min=0, max=100,
                    ).classes('w-32')
                    input_zakelijk = ui.number(
                        'Zakelijk %', value=100, min=0, max=100,
                    ).classes('w-32')

            # Representatie note
            representatie_note = ui.label(
                '80% aftrekbaar, 20% bijtelling'
            ).classes('text-caption text-orange')
            representatie_note.set_visibility(False)

            # Dynamic visibility based on bedrag
            def on_bedrag_change():
                val = input_bedrag.value or 0
                if val >= 450:
                    input_investering.set_visibility(True)
                else:
                    input_investering.set_visibility(False)
                    input_investering.value = False
                    investering_velden.set_visibility(False)

            input_bedrag.on('update:model-value', lambda: on_bedrag_change())

            # Show/hide investering fields based on checkbox
            def on_investering_change():
                investering_velden.set_visibility(input_investering.value)

            input_investering.on('update:model-value', lambda: on_investering_change())

            # Show representatie note
            def on_categorie_change():
                representatie_note.set_visibility(
                    input_categorie.value == 'Representatie'
                )

            input_categorie.on('update:model-value', lambda: on_categorie_change())

            with ui.row().classes('w-full justify-end mt-2'):
                ui.button('Opslaan', icon='save',
                          on_click=opslaan_uitgave).props('color=primary')

        # --- Table ---
        with ui.card().classes('w-full'):
            ui.label('Uitgaven').classes('text-subtitle1 text-bold')
            tabel_container['ref'] = ui.column().classes('w-full')

        # --- Summary ---
        with ui.card().classes('w-full'):
            summary_container['ref'] = ui.column().classes('w-full gap-1')

    # Initial load
    await ververs()
