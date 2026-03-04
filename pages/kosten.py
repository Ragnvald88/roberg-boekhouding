"""Kosten pagina — uitgaven registratie + categorisatie."""

from datetime import date
from pathlib import Path

from nicegui import ui

from components.layout import create_layout
from components.utils import format_euro, generate_csv, KOSTEN_CATEGORIEEN as CATEGORIEEN
from database import (
    add_uitgave, delete_uitgave, get_uitgaven, get_uitgaven_per_categorie,
    get_investeringen_voor_afschrijving, update_uitgave, get_fiscale_params,
    DB_PATH,
)
from fiscal.afschrijvingen import bereken_afschrijving

UITGAVEN_DIR = DB_PATH.parent / 'uitgaven'

LEVENSDUUR_OPTIES = {3: '3 jaar', 4: '4 jaar', 5: '5 jaar'}


@ui.page('/kosten')
async def kosten_page():
    create_layout('Kosten', '/kosten')

    # --- State ---
    huidig_jaar = date.today().year
    jaren = list(range(huidig_jaar, 2022, -1))  # 2026 down to 2023
    filter_jaar = {'value': huidig_jaar}
    filter_categorie = {'value': None}  # None = alle

    # Read representatie percentage from DB
    fp = await get_fiscale_params(DB_PATH, jaar=huidig_jaar)
    repr_aftrek_pct = int(fp.repr_aftrek_pct) if fp else 80

    # References to dynamic UI elements
    tabel_container = {'ref': None}
    summary_container = {'ref': None}
    activastaat_container = {'ref': None}

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
            row = {
                'id': u.id,
                'datum': u.datum,
                'categorie': u.categorie,
                'omschrijving': u.omschrijving,
                'bedrag': u.bedrag,
                'bedrag_fmt': format_euro(u.bedrag),
                'investering': 'Ja' if u.is_investering else '',
                'is_investering': u.is_investering,
                'restwaarde_pct': u.restwaarde_pct,
                'levensduur_jaren': u.levensduur_jaren,
                'zakelijk_pct': u.zakelijk_pct,
                'levensduur_fmt': '',
                'boekwaarde_fmt': '',
                'has_bon': bool(u.pdf_pad),
                'pdf_pad': u.pdf_pad,
            }
            if u.is_investering and u.levensduur_jaren:
                row['levensduur_fmt'] = f'{u.levensduur_jaren} jaar'
                aanschaf = (u.aanschaf_bedrag or u.bedrag) * ((u.zakelijk_pct or 100) / 100)
                result = bereken_afschrijving(
                    aanschaf_bedrag=aanschaf,
                    restwaarde_pct=u.restwaarde_pct or 10,
                    levensduur=u.levensduur_jaren,
                    aanschaf_maand=int(u.datum[5:7]),
                    aanschaf_jaar=int(u.datum[0:4]),
                    bereken_jaar=jaar,
                )
                row['boekwaarde_fmt'] = format_euro(result['boekwaarde'])
            rows.append(row)

        columns = [
            {'name': 'bon', 'label': '', 'field': 'has_bon', 'align': 'center'},
            {'name': 'datum', 'label': 'Datum', 'field': 'datum', 'sortable': True,
             'align': 'left'},
            {'name': 'categorie', 'label': 'Categorie', 'field': 'categorie',
             'sortable': True, 'align': 'left'},
            {'name': 'omschrijving', 'label': 'Omschrijving', 'field': 'omschrijving',
             'align': 'left'},
            {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
             'sortable': True, 'align': 'right'},
            {'name': 'investering', 'label': 'Inv.', 'field': 'investering',
             'align': 'center'},
            {'name': 'levensduur', 'label': 'Levensduur', 'field': 'levensduur_fmt',
             'align': 'center'},
            {'name': 'boekwaarde', 'label': 'Boekwaarde', 'field': 'boekwaarde_fmt',
             'align': 'right'},
            {'name': 'acties', 'label': 'Acties', 'field': 'acties', 'align': 'center'},
        ]

        with container:
            table = ui.table(
                columns=columns, rows=rows, row_key='id',
                pagination={'rowsPerPage': 20},
            ).classes('w-full')
            table.add_slot('body-cell-bon', '''
                <q-td :props="props">
                    <q-btn v-if="props.row.has_bon" icon="attach_file" flat dense
                           round size="sm" color="primary"
                           @click="$parent.$emit('viewdoc', props.row)"
                           title="Bekijk bon" />
                </q-td>
            ''')
            table.add_slot('body-cell-acties', '''
                <q-td :props="props">
                    <q-btn flat dense icon="edit" color="primary" size="sm"
                           @click="$parent.$emit('edit', props.row)" />
                    <q-btn flat dense icon="delete" color="negative" size="sm"
                           @click="$parent.$emit('delete', props.row)" />
                </q-td>
            ''')
            table.add_slot('no-data', '''
                <q-tr><q-td colspan="100%" class="text-center q-pa-lg text-grey">
                    Geen uitgaven gevonden.
                </q-td></q-tr>
            ''')
            table.on('edit', lambda e: open_edit_dialog(e.args))
            table.on('delete', lambda e: confirm_delete(e.args))
            table.on('viewdoc', lambda e: view_document(e.args))

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

    async def laad_activastaat():
        """Render activastaat card showing current book values."""
        container = activastaat_container['ref']
        if container is None:
            return
        container.clear()
        jaar = filter_jaar['value']
        investeringen = await get_investeringen_voor_afschrijving(DB_PATH, tot_jaar=jaar)
        if not investeringen:
            return

        with container:
            ui.label(f'Activastaat per 31-12-{jaar}').classes('text-subtitle1 text-bold')
            activa_rows = []
            for u in investeringen:
                aanschaf = (u.aanschaf_bedrag or u.bedrag) * ((u.zakelijk_pct or 100) / 100)
                result = bereken_afschrijving(
                    aanschaf_bedrag=aanschaf,
                    restwaarde_pct=u.restwaarde_pct or 10,
                    levensduur=u.levensduur_jaren or 5,
                    aanschaf_maand=int(u.datum[5:7]),
                    aanschaf_jaar=int(u.datum[0:4]),
                    bereken_jaar=jaar,
                )
                activa_rows.append({
                    'omschrijving': u.omschrijving,
                    'aanschaf': format_euro(aanschaf),
                    'afschr_jaar': format_euro(result['per_jaar']),
                    'boekwaarde': format_euro(result['boekwaarde']),
                })

            columns = [
                {'name': 'omschrijving', 'label': 'Omschrijving',
                 'field': 'omschrijving', 'align': 'left'},
                {'name': 'aanschaf', 'label': 'Aanschaf (zakelijk)',
                 'field': 'aanschaf', 'align': 'right'},
                {'name': 'afschr_jaar', 'label': 'Afschr/jaar',
                 'field': 'afschr_jaar', 'align': 'right'},
                {'name': 'boekwaarde', 'label': 'Boekwaarde',
                 'field': 'boekwaarde', 'align': 'right'},
            ]
            ui.table(
                columns=columns, rows=activa_rows, row_key='omschrijving',
            ).classes('w-full').props('dense flat')

    async def ververs():
        """Refresh table, summary and activastaat."""
        await laad_tabel()
        await laad_summary()
        await laad_activastaat()

    # --- Add dialog ---

    async def open_add_uitgave_dialog(and_new_state: dict | None = None):
        """Open dialog to add a new expense."""
        upload_file = {}

        with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg q-pa-md'):
            ui.label('Uitgave toevoegen').classes('text-h6 q-mb-md')

            input_datum = ui.input(
                'Datum', value=and_new_state.get('datum', date.today().isoformat())
                if and_new_state else date.today().isoformat(),
            ).classes('w-40')
            with input_datum:
                with ui.menu().props('no-parent-event') as datum_menu:
                    with ui.date(value=input_datum.value).bind_value(
                            input_datum) as datum_picker:
                        datum_picker.on('update:model-value',
                                        lambda: datum_menu.close())
                with input_datum.add_slot('append'):
                    ui.icon('edit_calendar').on('click', datum_menu.open) \
                        .classes('cursor-pointer')

            input_categorie = ui.select(
                CATEGORIEEN, label='Categorie',
                value=and_new_state.get('categorie') if and_new_state else None,
            ).classes('w-full')

            input_omschrijving = ui.input('Omschrijving').classes('w-full')

            input_bedrag = ui.number(
                'Bedrag incl. BTW (\u20ac)', format='%.2f',
                min=0.01, step=0.01,
            ).classes('w-full')

            # Investering section
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
            bijtelling_pct = 100 - repr_aftrek_pct
            representatie_note = ui.label(
                f'{repr_aftrek_pct}% aftrekbaar, {bijtelling_pct}% bijtelling'
            ).classes('text-caption text-orange')
            representatie_note.set_visibility(False)

            # Dynamic visibility
            def on_bedrag_change():
                val = input_bedrag.value or 0
                if val >= 450:
                    input_investering.set_visibility(True)
                else:
                    input_investering.set_visibility(False)
                    input_investering.value = False
                    investering_velden.set_visibility(False)

            input_bedrag.on('update:model-value', lambda: on_bedrag_change())

            def on_investering_change():
                investering_velden.set_visibility(input_investering.value)

            input_investering.on('update:model-value', lambda: on_investering_change())

            def on_categorie_change():
                representatie_note.set_visibility(
                    input_categorie.value == 'Representatie'
                )

            input_categorie.on('update:model-value', lambda: on_categorie_change())

            # Document upload
            ui.separator().classes('q-my-sm')
            ui.label('Bon/factuur (optioneel)').classes(
                'text-caption').style('color: #64748B')
            add_upload = ui.upload(
                label='Sleep bestand of klik', auto_upload=True,
                on_upload=lambda e: upload_file.update({'event': e}),
                max_file_size=10_000_000,
            ).classes('w-full').props('flat bordered accept=".pdf,.jpg,.jpeg,.png"')

            async def opslaan(and_new: bool = False):
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

                uitgave_id = await add_uitgave(DB_PATH, **kwargs)

                if upload_file.get('event'):
                    await save_upload_for_uitgave(uitgave_id, upload_file['event'])

                ui.notify('Uitgave opgeslagen', type='positive')
                await ververs()

                if and_new:
                    # Reset form — keep categorie
                    saved_cat = input_categorie.value
                    input_datum.value = date.today().isoformat()
                    input_omschrijving.value = ''
                    input_bedrag.value = None
                    input_investering.value = False
                    input_investering.set_visibility(False)
                    investering_velden.set_visibility(False)
                    representatie_note.set_visibility(saved_cat == 'Representatie')
                    upload_file.clear()
                    add_upload.reset()
                else:
                    dialog.close()

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')
                ui.button(
                    'Opslaan & Nieuw', icon='add',
                    on_click=lambda: opslaan(and_new=True),
                ).props('outline color=primary')
                ui.button(
                    'Opslaan', icon='save',
                    on_click=lambda: opslaan(and_new=False),
                ).props('color=primary')

        dialog.open()

    # --- Edit dialog ---

    async def open_edit_dialog(row: dict):
        """Open dialog to edit an existing expense."""
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg q-pa-md'):
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
                'Bedrag incl. BTW (\u20ac)', value=row['bedrag'],
                format='%.2f', min=0.01, step=0.01
            ).classes('w-full')

            # Investering fields
            is_inv = row.get('is_investering', False)
            edit_investering = ui.checkbox('Dit is een investering', value=is_inv)
            with ui.column().bind_visibility_from(edit_investering, 'value'):
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
            if (row.get('bedrag', 0) or 0) < 450:
                edit_investering.set_visibility(False)

            # Document section
            ui.separator().classes('my-2')
            edit_upload_file = {}
            existing_pdf = row.get('pdf_pad', '')
            if existing_pdf and Path(existing_pdf).exists():
                with ui.row().classes('items-center gap-2'):
                    ui.icon('attach_file', color='primary')
                    ui.label(Path(existing_pdf).name).classes('text-body2')
                    ui.button('Download', icon='download',
                              on_click=lambda: ui.download.file(existing_pdf)
                              ).props('flat dense size=sm')

                    async def remove_bon():
                        await update_uitgave(DB_PATH, uitgave_id=row['id'],
                                             pdf_pad='')
                        p = Path(existing_pdf)
                        if p.exists():
                            p.unlink()
                        ui.notify('Bon verwijderd', type='positive')
                        dialog.close()
                        await ververs()

                    ui.button('Verwijder bon', icon='delete',
                              on_click=remove_bon).props(
                                  'flat dense size=sm color=negative')
            else:
                ui.upload(
                    label='Bon uploaden', auto_upload=True,
                    on_upload=lambda e: edit_upload_file.update({'event': e}),
                    max_file_size=10_000_000,
                ).classes('w-full').props(
                    'flat bordered accept=".pdf,.jpg,.jpeg,.png"')

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
                    if edit_upload_file.get('event'):
                        await save_upload_for_uitgave(
                            row['id'], edit_upload_file['event'])
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
                    ui.notify('Uitgave verwijderd', type='positive')
                    dialog.close()
                    await ververs()

                ui.button('Verwijderen', on_click=verwijder).props('color=negative')
        dialog.open()

    def view_document(row: dict):
        """Open the attached document file."""
        pdf_pad = row.get('pdf_pad', '')
        if pdf_pad and Path(pdf_pad).exists():
            ui.download.file(pdf_pad)
        else:
            ui.notify('Bestand niet gevonden', type='warning')

    async def save_upload_for_uitgave(uitgave_id: int, upload_event):
        """Save an uploaded file and link it to an uitgave."""
        UITGAVEN_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = Path(upload_event.file.name).name.replace(' ', '_')
        filename = f'uitgave_{uitgave_id}_{safe_name}'
        filepath = UITGAVEN_DIR / filename
        await upload_event.file.save(filepath)
        await update_uitgave(DB_PATH, uitgave_id=uitgave_id,
                             pdf_pad=str(filepath))
        return filepath

    # === PAGE LAYOUT ===

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):

        # --- Header + filter row ---
        with ui.row().classes('w-full items-center gap-4'):
            ui.label('Kosten').classes('text-h5') \
                .style('color: #0F172A; font-weight: 700')
            ui.space()
            jaar_select = ui.select(
                {j: str(j) for j in jaren},
                label='Jaar', value=huidig_jaar,
            ).classes('w-32')

            async def export_csv_kosten():
                uitgaven = await get_uitgaven(
                    DB_PATH, jaar=filter_jaar['value'],
                    categorie=filter_categorie['value'])
                headers = ['Datum', 'Categorie', 'Omschrijving', 'Bedrag',
                           'Investering', 'Zakelijk %']
                rows = [[u.datum, u.categorie, u.omschrijving, u.bedrag,
                         'Ja' if u.is_investering else 'Nee',
                         u.zakelijk_pct] for u in uitgaven]
                csv_str = generate_csv(headers, rows)
                ui.download.content(
                    csv_str.encode('utf-8-sig'),
                    f'kosten_{filter_jaar["value"]}.csv')

            ui.button('CSV', icon='download',
                      on_click=export_csv_kosten).props('outline color=primary')

            cat_opties = {'': 'Alle'}
            cat_opties.update({c: c for c in CATEGORIEEN})
            cat_select = ui.select(
                cat_opties, label='Categorie', value='',
            ).classes('w-48')

            ui.button(
                'Nieuwe uitgave', icon='add',
                on_click=lambda: open_add_uitgave_dialog(),
            ).props('color=primary')

            async def on_filter_change():
                filter_jaar['value'] = jaar_select.value
                filter_categorie['value'] = cat_select.value or None
                await ververs()

            jaar_select.on('update:model-value', lambda: on_filter_change())
            cat_select.on('update:model-value', lambda: on_filter_change())

        # --- Table ---
        with ui.card().classes('w-full'):
            ui.label('Uitgaven').classes('text-subtitle1 text-bold')
            tabel_container['ref'] = ui.column().classes('w-full')

        # --- Summary ---
        with ui.card().classes('w-full'):
            summary_container['ref'] = ui.column().classes('w-full gap-1')

        # --- Activastaat ---
        with ui.card().classes('w-full'):
            activastaat_container['ref'] = ui.column().classes('w-full gap-1')

    # Initial load
    await ververs()
