"""Kosten pagina — uitgaven registratie + categorisatie."""

import asyncio
import shutil
from datetime import date
from itertools import groupby
from pathlib import Path

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import format_euro, format_datum, generate_csv, KOSTEN_CATEGORIEEN as CATEGORIEEN
from database import (
    add_uitgave, delete_uitgave, get_uitgaven, get_uitgaven_per_categorie,
    get_investeringen_voor_afschrijving, update_uitgave, get_fiscale_params,
    get_afschrijving_overrides, get_afschrijving_overrides_batch,
    set_afschrijving_override, delete_afschrijving_override,
    DB_PATH,
)
from components.shared_ui import year_options, date_input
from fiscal.afschrijvingen import bereken_afschrijving

UITGAVEN_DIR = DB_PATH.parent / 'uitgaven'

LEVENSDUUR_OPTIES = {3: '3 jaar', 4: '4 jaar', 5: '5 jaar'}

@ui.page('/kosten')
async def kosten_page():
    create_layout('Kosten', '/kosten')
    huidig_jaar = date.today().year
    jaren = year_options()
    filter_jaar = {'value': huidig_jaar}
    filter_categorie = {'value': None}  # None = alle

    # Read fiscal params from DB
    fp = await get_fiscale_params(DB_PATH, jaar=huidig_jaar)
    repr_aftrek_pct = int(fp.repr_aftrek_pct) if fp else 80

    # References to dynamic UI elements
    kosten_table = {'ref': None}
    summary_container = {'ref': None}
    activastaat_container = {'ref': None}
    update_bulk_bar_ref = {'fn': None}

    kosten_columns = [
        {'name': 'bon', 'label': '', 'field': 'has_bon', 'align': 'center'},
        {'name': 'datum', 'label': 'Datum', 'field': 'datum', 'sortable': True,
         'align': 'left'},
        {'name': 'categorie', 'label': 'Categorie', 'field': 'categorie',
         'sortable': True, 'align': 'left'},
        {'name': 'omschrijving', 'label': 'Omschrijving', 'field': 'omschrijving',
         'align': 'left'},
        {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag',
         'sortable': True, 'align': 'right'},
        {'name': 'investering', 'label': 'Inv.', 'field': 'investering',
         'align': 'center'},
        {'name': 'levensduur', 'label': 'Levensduur', 'field': 'levensduur_fmt',
         'align': 'center'},
        {'name': 'boekwaarde', 'label': 'Boekwaarde', 'field': 'boekwaarde_fmt',
         'align': 'right'},
        {'name': 'acties', 'label': 'Acties', 'field': 'acties', 'align': 'center'},
    ]
    async def laad_tabel():
        """Reload the expenses table rows (preserves pagination/sort state)."""
        table = kosten_table['ref']
        if table is None:
            return
        jaar = filter_jaar['value']
        cat = filter_categorie['value']
        uitgaven = await get_uitgaven(DB_PATH, jaar=jaar, categorie=cat)

        # Fetch overrides for investments in this view
        inv_ids = [u.id for u in uitgaven if u.is_investering]
        all_overrides = await get_afschrijving_overrides_batch(
            DB_PATH, inv_ids) if inv_ids else {}

        rows = []
        for u in uitgaven:
            row = {
                'id': u.id,
                'datum': u.datum,
                'datum_fmt': format_datum(u.datum),
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
                aanschaf = (u.aanschaf_bedrag or u.bedrag) * ((u.zakelijk_pct if u.zakelijk_pct is not None else 100) / 100)
                overrides = all_overrides.get(u.id)
                result = bereken_afschrijving(
                    aanschaf_bedrag=aanschaf,
                    restwaarde_pct=u.restwaarde_pct or 10,
                    levensduur=u.levensduur_jaren,
                    aanschaf_maand=int(u.datum[5:7]),
                    aanschaf_jaar=int(u.datum[0:4]),
                    bereken_jaar=jaar,
                    overrides=overrides,
                )
                row['boekwaarde_fmt'] = format_euro(result['boekwaarde'])
            rows.append(row)

        table.rows = rows
        table.selected.clear()
        table.update()
        if update_bulk_bar_ref['fn']:
            update_bulk_bar_ref['fn']()

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

        # Fetch all overrides in one batch
        all_overrides = await get_afschrijving_overrides_batch(
            DB_PATH, [u.id for u in investeringen])

        with container:
            ui.label(f'Activastaat per 31-12-{jaar}').classes('text-subtitle1 text-bold')
            activa_rows = []
            for u in investeringen:
                aanschaf = (u.aanschaf_bedrag or u.bedrag) * ((u.zakelijk_pct if u.zakelijk_pct is not None else 100) / 100)
                overrides = all_overrides.get(u.id)
                result = bereken_afschrijving(
                    aanschaf_bedrag=aanschaf,
                    restwaarde_pct=u.restwaarde_pct or 10,
                    levensduur=u.levensduur_jaren or 5,
                    aanschaf_maand=int(u.datum[5:7]),
                    aanschaf_jaar=int(u.datum[0:4]),
                    bereken_jaar=jaar,
                    overrides=overrides,
                )
                activa_rows.append({
                    'id': u.id,
                    'omschrijving': u.omschrijving,
                    'aanschaf': format_euro(aanschaf),
                    'afschr_dit_jaar': format_euro(result['afschrijving']),
                    'boekwaarde': format_euro(result['boekwaarde']),
                    'has_override': result.get('has_override', False),
                    # Raw data for edit dialog
                    '_aanschaf_bedrag': aanschaf,
                    '_restwaarde_pct': u.restwaarde_pct or 10,
                    '_levensduur': u.levensduur_jaren or 5,
                    '_aanschaf_maand': int(u.datum[5:7]),
                    '_aanschaf_jaar': int(u.datum[0:4]),
                })

            columns = [
                {'name': 'omschrijving', 'label': 'Omschrijving',
                 'field': 'omschrijving', 'align': 'left'},
                {'name': 'aanschaf', 'label': 'Aanschaf (zakelijk)',
                 'field': 'aanschaf', 'align': 'right'},
                {'name': 'afschr_dit_jaar', 'label': f'Afschr {jaar}',
                 'field': 'afschr_dit_jaar', 'align': 'right'},
                {'name': 'boekwaarde', 'label': 'Boekwaarde',
                 'field': 'boekwaarde', 'align': 'right'},
                {'name': 'acties', 'label': '', 'field': 'acties',
                 'align': 'center'},
            ]
            activa_tbl = ui.table(
                columns=columns, rows=activa_rows, row_key='id',
            ).classes('w-full').props('dense flat')
            activa_tbl.add_slot('body-cell-afschr_dit_jaar', '''
                <q-td :props="props">
                    <span>{{ props.row.afschr_dit_jaar }}</span>
                    <q-icon v-if="props.row.has_override" name="edit"
                            size="xs" color="primary" class="q-ml-xs" />
                </q-td>
            ''')
            activa_tbl.add_slot('body-cell-acties', '''
                <q-td :props="props">
                    <q-btn flat dense icon="tune" size="sm"
                           color="primary" title="Afschrijving aanpassen"
                           @click="$parent.$emit('edit_afschr', props.row)" />
                </q-td>
            ''')
            activa_tbl.on('edit_afschr',
                          lambda e: open_afschrijving_dialog(e.args))
    async def open_afschrijving_dialog(row: dict):
        """Open dialog to view/edit per-year depreciation for an investment.

        Past years (before filter year) are locked — already filed with BD.
        Current + future years are editable.
        Levensduur is editable and recalculates the schedule.
        """
        uitgave_id = row['id']
        aanschaf = row['_aanschaf_bedrag']
        restwaarde_pct = row['_restwaarde_pct']
        levensduur_state = {'value': row['_levensduur']}
        aanschaf_maand = row['_aanschaf_maand']
        aanschaf_jaar = row['_aanschaf_jaar']
        huidige_jaar = filter_jaar['value']

        # Fetch existing overrides
        overrides = await get_afschrijving_overrides(DB_PATH, uitgave_id)

        with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl q-pa-md'):
            ui.label(f'Afschrijving — {row["omschrijving"]}').classes(
                'text-h6 q-mb-sm')

            # Asset info + editable levensduur
            with ui.row().classes('w-full items-end gap-4'):
                ui.label(f'Aanschaf: {format_euro(aanschaf)}').classes(
                    'text-caption text-grey')
                ui.label(f'Restwaarde: {restwaarde_pct:.0f}%').classes(
                    'text-caption text-grey')
                levensduur_input = ui.select(
                    LEVENSDUUR_OPTIES, label='Levensduur',
                    value=levensduur_state['value'],
                ).classes('w-28')

            ui.separator().classes('q-my-sm')

            # Build year-by-year schedule
            schedule_container = ui.column().classes('w-full gap-0')
            inputs_by_year: dict[int, ui.number | None] = {}

            def build_schedule():
                schedule_container.clear()
                inputs_by_year.clear()
                lv = levensduur_state['value']
                laatste_jaar = aanschaf_jaar + lv
                toon_tot = max(laatste_jaar, huidige_jaar)

                with schedule_container:
                    # Header row
                    with ui.row().classes('w-full items-center gap-2 q-pb-xs') \
                            .style('border-bottom: 1px solid #E2E8F0'):
                        ui.label('Jaar').classes('text-caption text-bold') \
                            .style('width: 60px')
                        ui.label('Berekend').classes(
                            'text-caption text-bold text-right') \
                            .style('width: 90px')
                        ui.label('Handmatig').classes(
                            'text-caption text-bold') \
                            .style('width: 120px')
                        ui.label('Boekwaarde').classes(
                            'text-caption text-bold text-right') \
                            .style('width: 90px')

                    # Year rows
                    for y in range(aanschaf_jaar, toon_tot + 1):
                        # Auto value (without override)
                        auto = bereken_afschrijving(
                            aanschaf_bedrag=aanschaf,
                            restwaarde_pct=restwaarde_pct,
                            levensduur=lv,
                            aanschaf_maand=aanschaf_maand,
                            aanschaf_jaar=aanschaf_jaar,
                            bereken_jaar=y,
                        )
                        auto_val = auto['afschrijving']

                        # Book value with overrides
                        result_with = bereken_afschrijving(
                            aanschaf_bedrag=aanschaf,
                            restwaarde_pct=restwaarde_pct,
                            levensduur=lv,
                            aanschaf_maand=aanschaf_maand,
                            aanschaf_jaar=aanschaf_jaar,
                            bereken_jaar=y,
                            overrides=overrides,
                        )

                        has_ov = y in overrides
                        override_val = overrides.get(y)
                        is_locked = y < huidige_jaar  # past = filed with BD

                        with ui.row().classes('w-full items-center gap-2 q-py-xs') \
                                .style('border-bottom: 1px solid #F1F5F9'):
                            # Year label
                            lbl = ui.label(str(y)).style('width: 60px')
                            if y == huidige_jaar:
                                lbl.classes('text-bold text-primary')
                            else:
                                lbl.classes('text-caption')

                            # Auto-calculated value
                            ui.label(format_euro(auto_val)).classes(
                                'text-caption text-grey text-right') \
                                .style('width: 90px')

                            if is_locked:
                                # Past year: show value read-only with lock icon
                                if has_ov:
                                    ui.label(format_euro(override_val)).classes(
                                        'text-caption text-bold').style(
                                        'width: 120px')
                                else:
                                    ui.label('—').classes(
                                        'text-caption text-grey').style(
                                        'width: 120px')
                                inputs_by_year[y] = None  # not editable
                            else:
                                # Current/future: editable
                                inp = ui.number(
                                    value=override_val if has_ov else None,
                                    format='%.2f', min=0, step=0.01,
                                    placeholder=f'{auto_val:.2f}',
                                ).classes('w-28').props(
                                    'dense outlined hide-bottom-space')
                                inputs_by_year[y] = inp

                            # Book value
                            bw_label = ui.label(
                                format_euro(result_with['boekwaarde'])
                            ).classes('text-caption text-right') \
                                .style('width: 90px')
                            if has_ov:
                                bw_label.classes('text-bold')

                    # Locked years hint
                    if any(y < huidige_jaar
                           for y in range(aanschaf_jaar, toon_tot + 1)):
                        ui.label(
                            'Voorgaande jaren zijn vergrendeld (reeds aangegeven).'
                        ).classes('text-caption text-grey q-mt-sm')

            def on_levensduur_change():
                levensduur_state['value'] = levensduur_input.value
                build_schedule()

            levensduur_input.on('update:model-value',
                                lambda: on_levensduur_change())

            build_schedule()

            # Action buttons
            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')

                async def opslaan():
                    """Save overrides + levensduur."""
                    # Save levensduur if changed
                    new_lv = levensduur_state['value']
                    if new_lv != row['_levensduur']:
                        await update_uitgave(DB_PATH, uitgave_id=uitgave_id,
                                             levensduur_jaren=new_lv)

                    # Save overrides (only editable years)
                    for y, inp in inputs_by_year.items():
                        if inp is None:
                            continue  # locked year
                        val = inp.value
                        if val is not None and val >= 0:
                            await set_afschrijving_override(
                                DB_PATH, uitgave_id, y, val)
                            overrides[y] = val
                        elif y in overrides:
                            await delete_afschrijving_override(
                                DB_PATH, uitgave_id, y)
                            del overrides[y]
                    dialog.close()
                    ui.notify('Afschrijvingen opgeslagen', type='positive')
                    await ververs()

                ui.button('Opslaan', icon='save',
                          on_click=opslaan).props('color=primary')

        dialog.open()

    async def ververs():
        """Refresh table, summary and activastaat."""
        await laad_tabel()
        await laad_summary()
        await laad_activastaat()
    async def open_add_uitgave_dialog(prefill: dict | None = None,
                                     on_saved: callable | None = None):
        """Open dialog to add a new expense.

        Args:
            prefill: Optional dict with pre-fill values (datum, categorie,
                     omschrijving, pdf_path).
            on_saved: Optional callback invoked after successful save
                      (e.g. for archive import "next item" workflow).
        """
        upload_file = {}

        with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg q-pa-md'):
            ui.label('Uitgave toevoegen').classes('text-h6 q-mb-md')

            input_datum = date_input(
                'Datum',
                value=prefill.get('datum', date.today().isoformat())
                if prefill else date.today().isoformat(),
            )

            input_categorie = ui.select(
                CATEGORIEEN, label='Categorie',
                value=prefill.get('categorie') if prefill else None,
            ).classes('w-full')

            input_omschrijving = ui.input(
                'Omschrijving',
                value=prefill.get('omschrijving', '') if prefill else '',
            ).classes('w-full')

            input_bedrag = ui.number(
                'Bedrag incl. BTW (\u20ac)', format='%.2f',
                min=0.01, step=0.01,
            ).classes('w-full')

            # Investering section (always visible)
            input_investering = ui.checkbox('Dit is een investering', value=False)

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
            def on_investering_change():
                investering_velden.set_visibility(input_investering.value)

            input_investering.on('update:model-value', lambda: on_investering_change())

            def on_categorie_change():
                representatie_note.set_visibility(
                    input_categorie.value == 'Representatie'
                )

            input_categorie.on('update:model-value', lambda: on_categorie_change())

            # Document upload / pre-filled PDF
            ui.separator().classes('q-my-sm')
            ui.label('Bon/factuur (optioneel)').classes(
                'text-caption').style('color: #64748B')
            add_upload = None
            if prefill and prefill.get('pdf_path'):
                pdf_source = Path(prefill['pdf_path'])
                ui.label(f'Bon: {pdf_source.name}').classes(
                    'text-caption text-primary')
            else:
                add_upload = ui.upload(
                    label='Sleep bestand of klik', auto_upload=True,
                    on_upload=lambda e: upload_file.update({'event': e}),
                    max_file_size=10_000_000,
                ).classes('w-full').props(
                    'flat bordered accept=".pdf,.jpg,.jpeg,.png"')

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

                # Duplicate check
                try:
                    existing = await get_uitgaven(
                        DB_PATH, jaar=int(input_datum.value[:4]))
                    dupes = [
                        u for u in existing
                        if u.datum == input_datum.value
                        and u.categorie == input_categorie.value
                        and abs(u.bedrag - input_bedrag.value) < 0.01
                    ]
                    if dupes and not getattr(opslaan, '_confirmed_dupe', False):
                        ui.notify(
                            'Let op: vergelijkbare uitgave bestaat al voor '
                            'deze datum/categorie/bedrag. Klik nogmaals op '
                            'Opslaan om toch door te gaan.',
                            type='warning', timeout=5000,
                        )
                        opslaan._confirmed_dupe = True
                        return
                except Exception:
                    pass  # Don't block save if dupe check fails
                opslaan._confirmed_dupe = False

                kwargs = {
                    'datum': input_datum.value,
                    'categorie': input_categorie.value,
                    'omschrijving': input_omschrijving.value,
                    'bedrag': input_bedrag.value,
                }

                bedrag = input_bedrag.value
                if input_investering.value:
                    kwargs['is_investering'] = 1
                    kwargs['levensduur_jaren'] = input_levensduur.value
                    kwargs['restwaarde_pct'] = input_restwaarde.value or 10
                    kwargs['zakelijk_pct'] = input_zakelijk.value or 100
                    kwargs['aanschaf_bedrag'] = bedrag

                try:
                    uitgave_id = await add_uitgave(DB_PATH, **kwargs)

                    # Handle PDF: from prefill path or from upload widget
                    if prefill and prefill.get('pdf_path'):
                        await _copy_and_link_pdf(
                            uitgave_id, Path(prefill['pdf_path']))
                    elif upload_file.get('event'):
                        await save_upload_for_uitgave(
                            uitgave_id, upload_file['event'])

                    ui.notify('Uitgave opgeslagen', type='positive')
                    await ververs()

                    if and_new:
                        # Reset form — keep categorie
                        saved_cat = input_categorie.value
                        input_datum.value = date.today().isoformat()
                        input_omschrijving.value = ''
                        input_bedrag.value = None
                        input_investering.value = False
                        investering_velden.set_visibility(False)
                        representatie_note.set_visibility(
                            saved_cat == 'Representatie')
                        upload_file.clear()
                        if add_upload is not None:
                            add_upload.reset()
                    elif on_saved:
                        dialog.close()
                        if asyncio.iscoroutinefunction(on_saved):
                            await on_saved()
                        else:
                            on_saved()
                    else:
                        dialog.close()
                except Exception as e:
                    ui.notify(f'Fout bij opslaan: {e}', type='negative')

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
    async def open_edit_dialog(row: dict):
        """Open dialog to edit an existing expense."""
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg q-pa-md'):
            ui.label('Uitgave bewerken').classes('text-h6')

            edit_datum = date_input('Datum', value=row['datum'])

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

            # Investering fields visibility follows checkbox

            # Document section
            ui.separator().classes('q-my-sm')
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
                        with ui.dialog() as confirm_dlg, ui.card():
                            ui.label('Bon verwijderen?')
                            ui.label('Het bonbestand wordt permanent verwijderd.') \
                                .classes('text-grey')
                            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                                ui.button('Annuleren',
                                          on_click=confirm_dlg.close).props('flat')

                                async def do_remove():
                                    await update_uitgave(
                                        DB_PATH, uitgave_id=row['id'],
                                        pdf_pad='')
                                    p = Path(existing_pdf)
                                    if p.exists():
                                        await asyncio.to_thread(p.unlink)
                                    confirm_dlg.close()
                                    dialog.close()
                                    ui.notify('Bon verwijderd', type='positive')
                                    await ververs()

                                ui.button('Verwijderen',
                                          on_click=do_remove) \
                                    .props('color=negative')
                        confirm_dlg.open()

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

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')

                async def bewaar_wijziging():
                    if not edit_bedrag.value or edit_bedrag.value <= 0:
                        ui.notify('Vul een positief bedrag in', type='warning')
                        return
                    kwargs = {
                        'datum': edit_datum.value,
                        'categorie': edit_categorie.value,
                        'omschrijving': edit_omschrijving.value,
                        'bedrag': edit_bedrag.value,
                    }
                    if edit_investering.value:
                        kwargs['is_investering'] = 1
                        kwargs['levensduur_jaren'] = edit_levensduur.value
                        kwargs['restwaarde_pct'] = edit_restwaarde.value or 10
                        kwargs['zakelijk_pct'] = edit_zakelijk.value or 100
                        kwargs['aanschaf_bedrag'] = edit_bedrag.value
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
    async def confirm_delete(row: dict):
        """Confirm and delete an expense."""
        with ui.dialog() as dialog, ui.card():
            ui.label('Weet je zeker dat je deze uitgave wilt verwijderen?')
            ui.label(f"{row['datum']} — {row['omschrijving']} — "
                     f"{format_euro(row['bedrag'])}").classes('text-grey')
            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
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
        content = await upload_event.file.read()
        await asyncio.to_thread(filepath.write_bytes, content)
        await update_uitgave(DB_PATH, uitgave_id=uitgave_id,
                             pdf_pad=str(filepath))
        return filepath

    async def _copy_and_link_pdf(uitgave_id: int, source_path: Path):
        """Copy a PDF from archive to data/uitgaven/ and link to uitgave."""
        UITGAVEN_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = source_path.name.replace(' ', '_')
        filename = f'uitgave_{uitgave_id}_{safe_name}'
        dest = UITGAVEN_DIR / filename
        await asyncio.to_thread(shutil.copy2, source_path, dest)
        await update_uitgave(DB_PATH, uitgave_id=uitgave_id, pdf_pad=str(dest))
    async def open_import_dialog():
        """Open dialog to browse and import expense PDFs from archive."""
        from import_.expense_utils import scan_archive

        with ui.dialog() as import_dialog, \
                ui.card().classes('w-full q-pa-lg').style('max-width: 800px'):
            ui.label('Uitgaven importeren').classes('text-h5 q-mb-md')

            import_jaar = {'value': filter_jaar['value']}
            list_container = {'ref': None}

            async def load_archive():
                """Scan archive and render file list."""
                container = list_container['ref']
                if not container:
                    return
                container.clear()

                jaar = import_jaar['value']

                # Get existing pdf_pad values for dedup detection
                existing_uitgaven = await get_uitgaven(DB_PATH, jaar=jaar)
                existing_filenames = set()
                for u in existing_uitgaven:
                    if u.pdf_pad:
                        existing_filenames.add(Path(u.pdf_pad).name)

                items = scan_archive(jaar, existing_filenames)
                if not items:
                    with container:
                        ui.label(
                            f'Geen uitgaven gevonden in archief voor {jaar}'
                        ).classes('text-grey q-pa-md')
                    return

                imported_count = sum(1 for i in items if i['already_imported'])

                with container:
                    ui.label(
                        f'{len(items)} bestanden gevonden, '
                        f'{imported_count} al geïmporteerd'
                    ).classes('text-caption text-grey q-mb-sm')

                    # Group by category
                    items_sorted = sorted(items, key=lambda x: x['categorie'])
                    for cat, group_iter in groupby(
                        items_sorted, key=lambda x: x['categorie']
                    ):
                        group_list = list(group_iter)
                        cat_imported = sum(
                            1 for g in group_list if g['already_imported']
                        )

                        with ui.expansion(
                            f'{cat} ({len(group_list)})',
                            caption=(f'{cat_imported} geïmporteerd'
                                     if cat_imported else None),
                        ).classes('w-full'):
                            for item in group_list:
                                with ui.row().classes(
                                    'w-full items-center gap-2 q-py-xs'
                                ):
                                    if item['already_imported']:
                                        ui.icon(
                                            'check_circle', color='positive'
                                        ).classes('text-lg')
                                        ui.label(
                                            item['filename']
                                        ).classes('text-grey')
                                        if item['datum']:
                                            ui.label(
                                                item['datum']
                                            ).classes(
                                                'text-caption text-grey')
                                    else:
                                        async def do_import(it=item):
                                            await open_add_uitgave_dialog(
                                                prefill={
                                                    'datum': (
                                                        it['datum']
                                                        or date.today()
                                                        .isoformat()
                                                    ),
                                                    'categorie':
                                                        it['categorie'],
                                                    'pdf_path':
                                                        str(it['path']),
                                                },
                                                on_saved=load_archive,
                                            )

                                        ui.icon(
                                            'upload_file', color='primary'
                                        ).classes('text-lg')
                                        ui.link(
                                            item['filename'],
                                            on_click=do_import,
                                        ).classes(
                                            'text-primary cursor-pointer')
                                        if item['datum']:
                                            ui.label(
                                                item['datum']
                                            ).classes(
                                                'text-caption text-grey')
                                        else:
                                            ui.label(
                                                'datum onbekend'
                                            ).classes(
                                                'text-caption text-orange')

            # Year selector
            import_jaar_select = ui.select(
                {j: str(j) for j in jaren},
                label='Jaar',
                value=import_jaar['value'],
            ).classes('w-32')

            async def on_import_jaar_change():
                import_jaar['value'] = import_jaar_select.value
                await load_archive()

            import_jaar_select.on(
                'update:model-value',
                lambda: on_import_jaar_change(),
            )

            # File list container
            with ui.scroll_area().classes('w-full').style(
                'max-height: 60vh'
            ):
                list_container['ref'] = ui.column().classes('w-full')

            # Footer
            with ui.row().classes('w-full justify-end q-mt-md'):
                ui.button(
                    'Sluiten', on_click=import_dialog.close
                ).props('flat')

            # Initial load
            await load_archive()

        async def on_import_close():
            await ververs()

        import_dialog.on('hide', on_import_close)
        import_dialog.open()

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):

        # Header row: title + primary action
        with ui.row().classes('w-full items-center'):
            page_title('Kosten')
            ui.space()
            ui.button(
                'Importeer', icon='folder_open',
                on_click=lambda: open_import_dialog(),
            ).props('flat color=secondary dense')
            ui.button(
                'Nieuwe uitgave', icon='add',
                on_click=lambda: open_add_uitgave_dialog(),
            ).props('color=primary')

        # Filter bar
        with ui.element('div').classes('page-toolbar w-full'):
            jaar_select = ui.select(
                {j: str(j) for j in jaren},
                label='Jaar', value=huidig_jaar,
            ).classes('w-28')

            cat_opties = {'': 'Alle'}
            cat_opties.update({c: c for c in CATEGORIEEN})
            cat_select = ui.select(
                cat_opties, label='Categorie', value='',
            ).classes('w-44')

            ui.space()

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

            ui.button(icon='download',
                      on_click=export_csv_kosten) \
                .props('flat round color=secondary size=sm') \
                .tooltip('Exporteer CSV')

            async def on_filter_change():
                filter_jaar['value'] = jaar_select.value
                filter_categorie['value'] = cat_select.value or None
                await ververs()

            jaar_select.on('update:model-value', lambda: on_filter_change())
            cat_select.on('update:model-value', lambda: on_filter_change())
        with ui.card().classes('w-full'):
            ui.label('Uitgaven').classes('text-subtitle1 text-bold')

            bulk_bar = ui.row().classes('w-full items-center gap-4')
            bulk_bar.set_visibility(False)
            with bulk_bar:
                bulk_label = ui.label('')

                async def verwijder_selectie():
                    tbl = kosten_table['ref']
                    if not tbl or not tbl.selected:
                        return
                    ids = [r['id'] for r in tbl.selected]

                    async def confirm_bulk_delete():
                        for uid in ids:
                            await delete_uitgave(DB_PATH, uitgave_id=uid)
                        dlg.close()
                        ui.notify(
                            f'{len(ids)} uitgave(n) verwijderd',
                            type='positive')
                        await ververs()

                    with ui.dialog() as dlg, ui.card():
                        ui.label(f'{len(ids)} uitgave(n) verwijderen?') \
                            .classes('text-h6')
                        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                            ui.button('Annuleren', on_click=dlg.close) \
                                .props('flat')
                            ui.button('Ja, verwijderen',
                                      on_click=confirm_bulk_delete) \
                                .props('color=negative')
                    dlg.open()

                ui.button(
                    'Verwijder selectie', icon='delete',
                    on_click=verwijder_selectie,
                ).props('color=negative outline')

            def update_bulk_bar():
                tbl = kosten_table['ref']
                selected = tbl.selected if tbl else []
                n = len(selected) if selected else 0
                if n > 0:
                    bulk_bar.set_visibility(True)
                    bulk_label.text = f'{n} uitgave(n) geselecteerd'
                else:
                    bulk_bar.set_visibility(False)

            update_bulk_bar_ref['fn'] = update_bulk_bar

            kosten_table['ref'] = ui.table(
                columns=kosten_columns, rows=[], row_key='id',
                selection='multiple',
                pagination={'rowsPerPage': 20, 'sortBy': 'datum',
                            'descending': True,
                            'rowsPerPageOptions': [10, 20, 50, 0]},
            ).classes('w-full')
            _tbl = kosten_table['ref']
            _tbl.on('selection', lambda _: update_bulk_bar())
            _tbl.add_slot('body-cell-bon', '''
                <q-td :props="props">
                    <q-btn v-if="props.row.has_bon" icon="attach_file" flat dense
                           round size="sm" color="primary"
                           @click="$parent.$emit('viewdoc', props.row)"
                           title="Bekijk bon" />
                </q-td>
            ''')
            _tbl.add_slot('body-cell-datum', '''
                <q-td :props="props">{{ props.row.datum_fmt }}</q-td>
            ''')
            _tbl.add_slot('body-cell-bedrag', '''
                <q-td :props="props" style="text-align:right">{{ props.row.bedrag_fmt }}</q-td>
            ''')
            _tbl.add_slot('body-cell-acties', '''
                <q-td :props="props">
                    <q-btn flat dense icon="edit" color="primary" size="sm"
                           @click="$parent.$emit('edit', props.row)"
                           title="Bewerken" />
                    <q-btn flat dense icon="delete" color="negative" size="sm"
                           @click="$parent.$emit('delete', props.row)"
                           title="Verwijderen" />
                </q-td>
            ''')
            _tbl.add_slot('no-data', '''
                <q-tr><q-td colspan="100%" class="text-center q-pa-lg text-grey">
                    Geen uitgaven gevonden.
                </q-td></q-tr>
            ''')
            _tbl.on('edit', lambda e: open_edit_dialog(e.args))
            _tbl.on('delete', lambda e: confirm_delete(e.args))
            _tbl.on('viewdoc', lambda e: view_document(e.args))
        with ui.card().classes('w-full'):
            summary_container['ref'] = ui.column().classes('w-full gap-1')
        with ui.card().classes('w-full'):
            activastaat_container['ref'] = ui.column().classes('w-full gap-1')

    # Initial load
    await ververs()
