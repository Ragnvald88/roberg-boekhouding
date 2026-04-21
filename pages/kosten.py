"""Kosten pagina — transacties (bank + cash) + investeringen."""

import asyncio
import json
import shutil
from datetime import date
from itertools import groupby
from pathlib import Path

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import (
    format_euro, format_datum, KOSTEN_CATEGORIEEN as CATEGORIEEN,
)
from components.shared_ui import year_options, date_input
from components.kosten_helpers import (
    derive_status, tegenpartij_color, initials,
)
from database import (
    add_uitgave, delete_uitgave, get_uitgaven, update_uitgave,
    get_fiscale_params,
    ensure_uitgave_for_banktx, mark_banktx_genegeerd,
    get_kosten_view, get_kpi_kosten, find_pdf_matches_for_banktx,
    KostenRow, KpiKosten, PdfMatch, YearLockedError,
    DB_PATH,
)
from pages.kosten_investeringen import laad_activastaat

UITGAVEN_DIR = DB_PATH.parent / 'uitgaven'

LEVENSDUUR_OPTIES = {3: '3 jaar', 4: '4 jaar', 5: '5 jaar'}


# ---------------------------------------------------------------------------
# Stub loaders — real implementations land in Tasks 10–14.
# Kept at module scope so later tasks can redefine them by editing in place.
# ---------------------------------------------------------------------------
async def _laad_kpi(container, jaar):
    if container is None:
        return
    container.clear()
    with container:
        ui.label(f'KPIs voor {jaar} (placeholder — Task 12)') \
            .classes('text-caption')


async def _laad_inbox(container, jaar, refresh):
    if container is None:
        return
    container.clear()  # nothing to show yet (Task 12)


def _view_pdf(row: dict):
    """Open the attached document file from a kosten row."""
    p = row.get('pdf_pad', '')
    if p and Path(p).exists():
        ui.download.file(p)
    else:
        ui.notify('Bon niet gevonden', type='warning')


async def _laad_tabel(
    container, jaar, status, categorie, search, view_mode, refresh,
):
    if container is None:
        return
    container.clear()

    rows = await get_kosten_view(
        DB_PATH, jaar=jaar, status=status,
        categorie=categorie, search=search,
    )

    columns = [
        {'name': 'datum', 'label': 'Datum', 'field': 'datum',
         'align': 'left', 'sortable': True},
        {'name': 'tegenpartij', 'label': 'Tegenpartij / Omschrijving',
         'field': 'tegenpartij', 'align': 'left'},
        {'name': 'categorie', 'label': 'Categorie', 'field': 'categorie',
         'align': 'left'},
        {'name': 'factuur', 'label': 'Factuur', 'field': 'factuur_status',
         'align': 'left'},
        {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
         'align': 'right', 'sortable': True},
        {'name': 'acties', 'label': '', 'field': 'acties',
         'align': 'center'},
    ]

    table_rows = []
    for r in rows:
        display_name = r.tegenpartij or r.omschrijving or '(onbekend)'
        table_rows.append({
            'id_bank': r.id_bank,
            'id_uitgave': r.id_uitgave,
            'datum': r.datum,
            'datum_fmt': format_datum(r.datum),
            'tegenpartij': display_name,
            'omschrijving': r.omschrijving,
            'categorie': r.categorie,
            'bedrag': r.bedrag,
            'bedrag_fmt': format_euro(r.bedrag),
            'factuur_status': r.status,
            'pdf_pad': r.pdf_pad,
            'is_manual': r.is_manual,
            'initials': initials(r.tegenpartij or r.omschrijving),
            'color': tegenpartij_color(r.tegenpartij or r.omschrijving),
            # Row key must be unique across bank-only and manual rows.
            # Manual rows have id_bank=None; bank rows always have id_bank set.
            'row_key': (f'b{r.id_bank}' if r.id_bank is not None
                        else f'u{r.id_uitgave}'),
        })

    # Inject the category list into a window global referenced by the
    # categorie-dropdown slot template below. NiceGUI doesn't expose a
    # cleaner hook for passing Python lists into per-cell slot templates.
    # json.dumps keeps us safe against apostrophes / special chars.
    ui.add_body_html(
        '<script>window.__KOSTEN_CAT_LIST__ = '
        f'{json.dumps(CATEGORIEEN)};</script>'
    )

    async def _on_set_cat(args: dict):
        row = args['row']
        cat = args['cat']
        try:
            if row['id_bank'] is not None and row['id_uitgave'] is None:
                # Bank-only row: lazy-create the linked uitgave.
                await ensure_uitgave_for_banktx(
                    DB_PATH, bank_tx_id=row['id_bank'], categorie=cat,
                )
            else:
                # Manual row or bank+linked row: update existing uitgave.
                await update_uitgave(
                    DB_PATH, uitgave_id=row['id_uitgave'], categorie=cat,
                )
            ui.notify(f'Categorie bijgewerkt naar {cat}', type='positive')
            await refresh()
        except YearLockedError as e:
            ui.notify(str(e), type='negative')

    async def _attach_pdf_dialog(row):
        """Placeholder — Task 11 routes to the Detail dialog's Factuur tab."""
        await _open_detail_dialog(row, default_tab='factuur')

    async def _open_detail_dialog(row, default_tab: str = 'detail'):
        """Stub — Task 11 replaces this with the full Detail dialog."""
        ui.notify('Detail-dialog komt in Task 11', type='info')

    with container:
        with ui.card().classes('w-full'):
            tbl = ui.table(
                columns=columns, rows=table_rows, row_key='row_key',
                selection='multiple',
                pagination={
                    'rowsPerPage': 20, 'sortBy': 'datum',
                    'descending': True,
                    'rowsPerPageOptions': [10, 20, 50, 0],
                },
            ).classes('w-full').props('flat')

            tbl.add_slot('body-cell-datum', '''
                <q-td :props="props">{{ props.row.datum_fmt }}</q-td>
            ''')

            tbl.add_slot('body-cell-tegenpartij', '''
                <q-td :props="props">
                  <div class="row items-center q-gutter-sm">
                    <div
                         :style="`background:${props.row.color};
                                   color:white;
                                   width:30px;height:30px;
                                   border-radius:7px;
                                   display:grid;place-items:center;
                                   font-weight:700;font-size:11px;
                                   flex-shrink:0;`">
                      {{ props.row.initials }}
                    </div>
                    <div>
                      <div style="font-weight:500">
                        {{ props.row.tegenpartij }}
                      </div>
                      <div class="text-caption text-grey"
                           v-if="props.row.omschrijving &&
                                  props.row.omschrijving !== props.row.tegenpartij">
                        {{ props.row.omschrijving }}
                      </div>
                    </div>
                  </div>
                </q-td>
            ''')

            tbl.add_slot('body-cell-categorie', '''
                <q-td :props="props">
                  <q-btn-dropdown flat dense
                                  no-caps
                                  :label="props.row.categorie || '— kies —'"
                                  :color="props.row.categorie ? 'primary' : 'warning'"
                                  size="sm">
                    <q-list dense>
                      <q-item v-for="c in window.__KOSTEN_CAT_LIST__"
                              :key="c"
                              clickable
                              v-close-popup
                              @click="$parent.$emit('set_cat',
                                       {row: props.row, cat: c})">
                        <q-item-section>{{ c }}</q-item-section>
                      </q-item>
                    </q-list>
                  </q-btn-dropdown>
                </q-td>
            ''')

            tbl.add_slot('body-cell-factuur', '''
                <q-td :props="props">
                  <q-chip v-if="props.row.factuur_status === 'compleet'"
                          color="positive" text-color="white"
                          size="sm" icon="check_circle" dense>
                    Compleet
                  </q-chip>
                  <q-chip v-else-if="props.row.factuur_status === 'ontbreekt'"
                          color="warning" text-color="white"
                          size="sm" icon="warning" dense>
                    Ontbreekt
                  </q-chip>
                  <q-chip v-else color="info" text-color="white"
                          size="sm" dense>
                    Nieuw
                  </q-chip>
                  <q-btn v-if="props.row.pdf_pad" flat dense round size="xs"
                         icon="attach_file" color="primary"
                         @click="$parent.$emit('view_pdf', props.row)" />
                  <q-chip v-if="props.row.is_manual" color="grey"
                          text-color="white" size="sm" dense>
                    contant
                  </q-chip>
                </q-td>
            ''')

            tbl.add_slot('body-cell-acties', '''
                <q-td :props="props">
                  <q-btn flat dense round icon="attach_file"
                         size="sm" color="primary"
                         title="Bon toevoegen"
                         @click="$parent.$emit('attach_pdf', props.row)" />
                  <q-btn flat dense round icon="more_horiz"
                         size="sm" color="grey-7"
                         @click="$parent.$emit('open_detail', props.row)" />
                </q-td>
            ''')

            tbl.add_slot('no-data', '''
                <q-tr><q-td colspan="100%"
                            class="text-center q-pa-lg text-grey">
                  Geen transacties gevonden.
                </q-td></q-tr>
            ''')

            tbl.on('set_cat',
                   lambda e: asyncio.create_task(_on_set_cat(e.args)))
            tbl.on('view_pdf',
                   lambda e: _view_pdf(e.args))
            tbl.on('attach_pdf',
                   lambda e: asyncio.create_task(
                       _attach_pdf_dialog(e.args)))
            tbl.on('open_detail',
                   lambda e: asyncio.create_task(
                       _open_detail_dialog(e.args)))


async def _laad_breakdown(container, jaar):
    if container is None:
        return
    container.clear()  # placeholder for Task 14


@ui.page('/kosten')
async def kosten_page():
    create_layout('Kosten', '/kosten')
    huidig_jaar = date.today().year
    jaren = year_options()
    filter_jaar = {'value': huidig_jaar}
    filter_status = {'value': None}     # None = 'Alle'
    filter_categorie = {'value': None}  # None = 'Alle'
    filter_search = {'value': ''}
    view_mode = {'value': 'lijst'}      # 'lijst' or 'maand'

    fp = await get_fiscale_params(DB_PATH, jaar=huidig_jaar)
    repr_aftrek_pct = int(fp.repr_aftrek_pct) if fp else 80

    # UI refs (populated below, used by loaders)
    kosten_table = {'ref': None}
    kpi_container = {'ref': None}
    inbox_container = {'ref': None}
    breakdown_container = {'ref': None}
    activa_container = {'ref': None}

    async def ververs_transacties():
        await _laad_kpi(kpi_container['ref'], filter_jaar['value'])
        await _laad_inbox(
            inbox_container['ref'], filter_jaar['value'],
            ververs_transacties,
        )
        await _laad_tabel(
            kosten_table['ref'], filter_jaar['value'],
            filter_status['value'], filter_categorie['value'],
            filter_search['value'], view_mode['value'],
            refresh=ververs_transacties,
        )
        await _laad_breakdown(
            breakdown_container['ref'], filter_jaar['value'])

    async def ververs_investeringen():
        await laad_activastaat(
            activa_container['ref'], filter_jaar['value'],
            ververs_transacties,
        )

    # -----------------------------------------------------------------
    # Dialogs — preserved verbatim from the pre-Kosten-rework version.
    # Tasks 10–13 still depend on these; do not refactor their bodies.
    # -----------------------------------------------------------------
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
                'Bedrag incl. BTW (€)', format='%.2f',
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
                    await ververs_transacties()

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
                'Bedrag incl. BTW (€)', value=row['bedrag'],
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
                                    await ververs_transacties()

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
                    await ververs_transacties()

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
                    await ververs_transacties()

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
            await ververs_transacties()

        import_dialog.on('hide', on_import_close)
        import_dialog.open()

    # -----------------------------------------------------------------
    # Page layout
    # -----------------------------------------------------------------
    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):
        # Header
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

        with ui.tabs().classes('w-full') as tabs:
            tab_tx = ui.tab('Transacties', icon='list')
            tab_inv = ui.tab('Investeringen', icon='inventory_2')

        with ui.tab_panels(tabs, value=tab_tx).classes('w-full'):
            with ui.tab_panel(tab_tx):
                # Filter bar
                with ui.row().classes('w-full items-center gap-2'):
                    jaar_select = ui.select(
                        {j: str(j) for j in jaren},
                        label='Jaar', value=huidig_jaar,
                    ).classes('w-28')

                    status_options = {
                        None: 'Alle',
                        'ongecategoriseerd': 'Ongecat.',
                        'ontbreekt': 'Ontbreekt',
                        'compleet': 'Compleet',
                    }
                    status_select = ui.select(
                        status_options, label='Status',
                        value=None,
                    ).classes('w-40')

                    cat_opties = {'': 'Alle categorieën'}
                    cat_opties.update({c: c for c in CATEGORIEEN})
                    cat_select = ui.select(
                        cat_opties, label='Categorie', value='',
                    ).classes('w-48')

                    search_input = ui.input(
                        placeholder='Zoek…',
                    ).classes('w-56').props('clearable dense outlined')

                    ui.space()

                    view_toggle = ui.toggle(
                        {'lijst': 'Lijst', 'maand': 'Per maand'},
                        value='lijst',
                    ).props('dense')

                async def on_filter_change():
                    filter_jaar['value'] = jaar_select.value
                    filter_status['value'] = status_select.value
                    filter_categorie['value'] = cat_select.value or None
                    filter_search['value'] = search_input.value or ''
                    view_mode['value'] = view_toggle.value
                    await ververs_transacties()

                for w in (jaar_select, status_select, cat_select, view_toggle):
                    w.on('update:model-value',
                         lambda _=None: on_filter_change())
                search_input.on(
                    'update:model-value',
                    lambda _=None: on_filter_change())

                # KPI strip (Task 12)
                kpi_container['ref'] = ui.row().classes('w-full gap-4')

                # Reconciliation inbox (Task 12)
                inbox_container['ref'] = ui.column().classes('w-full')

                # Main table (Task 10)
                kosten_table['ref'] = ui.column().classes('w-full')

                # Categorie breakdown (Task 14)
                breakdown_container['ref'] = ui.column().classes('w-full')

            with ui.tab_panel(tab_inv):
                activa_container['ref'] = ui.column().classes('w-full gap-2')

        # Load activastaat when Investeringen tab is first selected.
        async def on_tab_change():
            if tabs.value == 'Investeringen':
                await ververs_investeringen()

        tabs.on('update:model-value',
                lambda _: asyncio.create_task(on_tab_change()))

    # Initial load
    await ververs_transacties()
