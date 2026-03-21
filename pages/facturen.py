"""Facturen pagina — factuur aanmaken, overzicht en betaalstatus."""

import asyncio
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from nicegui import app, events, ui

from components.layout import create_layout, page_title
from components.invoice_generator import generate_invoice
from components.utils import format_euro, format_datum, generate_csv
from database import (
    get_facturen, add_factuur, get_next_factuurnummer,
    mark_betaald, delete_factuur, update_factuur,
    get_klanten, get_werkdagen_ongefactureerd,
    link_werkdagen_to_factuur, get_bedrijfsgegevens, get_db_ctx, add_werkdag,
    get_fiscale_params, DB_PATH,
)
from components.shared_ui import year_options, date_input
from import_.pdf_parser import (
    extract_pdf_text, detect_invoice_type,
    parse_dagpraktijk_text, parse_anw_text,
)
from import_.klant_mapping import resolve_klant, resolve_anw_klant

PDF_DIR = DB_PATH.parent / "facturen"

# Serve factuur PDFs for in-browser preview
PDF_DIR.mkdir(parents=True, exist_ok=True)
app.add_static_files('/facturen-files', str(PDF_DIR))


def _is_verlopen(datum_str: str) -> bool:
    """Check if an invoice is overdue (>14 days past datum and unpaid)."""
    try:
        d = datetime.strptime(datum_str, '%Y-%m-%d').date()
        return (d + timedelta(days=14)) < date.today()
    except (ValueError, TypeError):
        return False


@ui.page('/facturen')
async def facturen_page():
    create_layout('Facturen', '/facturen')

    current_year = date.today().year
    table_ref = {'ref': None}
    bulk_bar_ref = {'ref': None}
    filter_klant = {'value': None}  # None = alle klanten

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        # Header + filter
        with ui.row().classes('w-full items-center gap-4'):
            page_title('Facturen')
            ui.space()
            jaar_select = ui.select(
                year_options(include_next=True, as_dict=True, descending=False),
                value=current_year, label='Jaar',
            ).classes('w-32')

            # Klant filter
            klanten = await get_klanten(DB_PATH)
            klant_opties = {None: 'Alle klanten'}
            klant_opties.update({k.naam: k.naam for k in klanten})

            async def on_klant_filter(e):
                filter_klant['value'] = e.value
                await refresh_table()

            ui.select(klant_opties, value=None, label='Klant',
                      on_change=on_klant_filter).props('clearable').classes('w-48')

            # Status filter
            status_options = {'': 'Alle', 'openstaand': 'Openstaand',
                              'verlopen': 'Verlopen', 'betaald': 'Betaald'}
            filter_status = {'value': ''}

            async def on_status_filter(e):
                filter_status['value'] = e.value
                await refresh_table()

            ui.select(status_options, value='', label='Status',
                      on_change=on_status_filter).classes('w-40')

            async def export_csv():
                facturen = await get_facturen(DB_PATH, jaar=jaar_select.value)
                if filter_klant['value']:
                    facturen = [f for f in facturen
                                if f.klant_naam == filter_klant['value']]
                headers = ['Nummer', 'Datum', 'Klant', 'Uren', 'Km',
                           'Bedrag', 'Status']
                rows = [[f.nummer, f.datum, f.klant_naam, f.totaal_uren,
                         f.totaal_km, f.totaal_bedrag,
                         'Betaald' if f.betaald else 'Openstaand']
                        for f in facturen]
                csv_str = generate_csv(headers, rows)
                ui.download.content(
                    csv_str.encode('utf-8-sig'),
                    f'facturen_{jaar_select.value}.csv')

            ui.button('CSV', icon='download',
                      on_click=export_csv).props('outline color=primary')
            ui.button('Importeer PDF', icon='upload_file',
                      on_click=lambda: open_import_dialog()) \
                .props('outline color=primary')
            ui.button('Nieuwe factuur', icon='add',
                      on_click=lambda: open_new_factuur_dialog()) \
                .props('color=primary')

        # KPI summary strip
        kpi_strip_container = ui.row().classes('w-full gap-4')

        # Bulk action toolbar (hidden when nothing selected)
        bulk_bar = ui.row().classes('w-full items-center gap-4')
        bulk_bar.set_visibility(False)
        bulk_bar_ref['ref'] = bulk_bar
        with bulk_bar:
            bulk_label = ui.label('')
            ui.button('Markeer betaald', icon='check_circle',
                      on_click=lambda: on_bulk_betaald()) \
                .props('color=positive outline')
            ui.button('Verwijder selectie', icon='delete',
                      on_click=lambda: on_bulk_delete()) \
                .props('color=negative outline')

        # Facturen table
        columns = [
            {'name': 'nummer', 'label': 'Nummer', 'field': 'nummer',
             'sortable': True, 'align': 'left'},
            {'name': 'datum', 'label': 'Datum', 'field': 'datum_fmt',
             'sortable': True, 'align': 'left'},
            {'name': 'vervaldatum', 'label': 'Vervaldatum', 'field': 'vervaldatum_fmt',
             'sortable': True, 'align': 'left'},
            {'name': 'klant', 'label': 'Klant', 'field': 'klant_naam',
             'sortable': True, 'align': 'left'},
            {'name': 'uren', 'label': 'Uren', 'field': 'totaal_uren',
             'align': 'right'},
            {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
             'sortable': True, 'align': 'right'},
            {'name': 'status', 'label': 'Status', 'field': 'status',
             'sortable': True, 'align': 'center'},
            {'name': 'actions', 'label': '', 'field': 'actions', 'align': 'center'},
        ]

        table = ui.table(
            columns=columns, rows=[], row_key='id',
            selection='multiple',
            pagination={'rowsPerPage': 20, 'sortBy': 'nummer', 'descending': True,
                        'rowsPerPageOptions': [10, 20, 50, 0]},
        ).classes('w-full')
        table_ref['ref'] = table

        table.add_slot('body-cell-status', '''
            <q-td :props="props">
                <q-badge v-if="props.row.betaald" color="positive" label="Betaald" />
                <q-badge v-else-if="props.row.verlopen" color="negative" label="Verlopen" />
                <q-badge v-else color="warning" label="Openstaand" />
            </q-td>
        ''')

        table.add_slot('no-data', '''
            <q-tr><q-td colspan="100%" class="text-center q-pa-lg text-grey">
                Geen facturen gevonden.
            </q-td></q-tr>
        ''')

        table.add_slot('body-cell-actions', '''
            <q-td :props="props">
                <q-btn icon="more_vert" flat dense round size="sm"
                       color="grey-7">
                    <q-menu auto-close>
                        <q-list dense style="min-width: 200px">
                            <q-item clickable
                                @click="() => $parent.$emit('edit', props.row)">
                                <q-item-section side>
                                    <q-icon name="edit" size="xs"
                                            color="primary" />
                                </q-item-section>
                                <q-item-section>Bewerken</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.pdf_pad" clickable
                                @click="() => $parent.$emit('preview', props.row)">
                                <q-item-section side>
                                    <q-icon name="visibility" size="xs"
                                            color="primary" />
                                </q-item-section>
                                <q-item-section>Preview</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.pdf_pad" clickable
                                @click="() => $parent.$emit('download',
                                    props.row)">
                                <q-item-section side>
                                    <q-icon name="download" size="xs" />
                                </q-item-section>
                                <q-item-section>Download PDF</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.pdf_pad" clickable
                                @click="() => $parent.$emit('openfinder',
                                    props.row)">
                                <q-item-section side>
                                    <q-icon name="folder_open" size="xs" />
                                </q-item-section>
                                <q-item-section>Toon in Finder</q-item-section>
                            </q-item>
                            <q-separator />
                            <q-item v-if="!props.row.betaald" clickable
                                @click="() => $parent.$emit('markbetaald',
                                    props.row)">
                                <q-item-section side>
                                    <q-icon name="check_circle" size="xs"
                                            color="positive" />
                                </q-item-section>
                                <q-item-section>
                                    Markeer betaald
                                </q-item-section>
                            </q-item>
                            <q-item v-if="props.row.betaald" clickable
                                @click="() => $parent.$emit('markonbetaald',
                                    props.row)">
                                <q-item-section side>
                                    <q-icon name="undo" size="xs" />
                                </q-item-section>
                                <q-item-section>
                                    Markeer onbetaald
                                </q-item-section>
                            </q-item>
                            <q-separator />
                            <q-item clickable
                                @click="() => $parent.$emit('deletefactuur',
                                    props.row)">
                                <q-item-section side>
                                    <q-icon name="delete" size="xs"
                                            color="negative" />
                                </q-item-section>
                                <q-item-section class="text-negative">
                                    Verwijderen
                                </q-item-section>
                            </q-item>
                        </q-list>
                    </q-menu>
                </q-btn>
            </q-td>
        ''')

        # Summary
        summary_row = ui.row().classes('w-full justify-end gap-8 q-mt-sm')

        def update_bulk_bar():
            selected = table.selected
            n = len(selected) if selected else 0
            if n > 0:
                bulk_bar.set_visibility(True)
                bulk_label.text = f'{n} facturen geselecteerd'
            else:
                bulk_bar.set_visibility(False)

        table.on('selection', lambda _: update_bulk_bar())

        async def refresh_table():
            jaar = jaar_select.value
            facturen = await get_facturen(DB_PATH, jaar=jaar)
            if filter_klant['value']:
                facturen = [f for f in facturen
                            if f.klant_naam == filter_klant['value']]

            # Status filter
            status_val = filter_status['value']
            if status_val == 'betaald':
                facturen = [f for f in facturen if f.betaald]
            elif status_val == 'openstaand':
                facturen = [f for f in facturen
                            if not f.betaald and not _is_verlopen(f.datum)]
            elif status_val == 'verlopen':
                facturen = [f for f in facturen
                            if not f.betaald and _is_verlopen(f.datum)]

            rows = []
            totaal = 0
            openstaand = 0
            for f in facturen:
                # Compute verlopen status and vervaldatum
                is_verlopen = not f.betaald and _is_verlopen(f.datum)
                try:
                    factuur_date = datetime.strptime(f.datum, '%Y-%m-%d').date()
                    vervaldatum_fmt = format_datum(
                        (factuur_date + timedelta(days=14)).isoformat())
                except (ValueError, TypeError):
                    vervaldatum_fmt = ''

                rows.append({
                    'id': f.id,
                    'nummer': f.nummer,
                    'datum': f.datum,
                    'datum_fmt': format_datum(f.datum),
                    'vervaldatum_fmt': vervaldatum_fmt,
                    'verlopen': is_verlopen,
                    'klant_id': f.klant_id,
                    'klant_naam': f.klant_naam,
                    'totaal_uren': f.totaal_uren,
                    'totaal_km': f.totaal_km,
                    'bedrag_fmt': format_euro(f.totaal_bedrag),
                    'totaal_bedrag': f.totaal_bedrag,
                    'betaald': f.betaald,
                    'betaald_datum': f.betaald_datum,
                    'pdf_pad': f.pdf_pad,
                    'type': f.type,
                })
                totaal += f.totaal_bedrag
                if not f.betaald:
                    openstaand += f.totaal_bedrag

            table.rows = rows
            table.selected.clear()
            table.update()
            update_bulk_bar()

            # Update KPI strip
            verlopen_bedrag = sum(r['totaal_bedrag'] for r in rows
                                  if r.get('verlopen'))
            kpi_strip_container.clear()
            with kpi_strip_container:
                _kpi_style = 'font-variant-numeric: tabular-nums'
                with ui.card().classes('flex-1 q-pa-sm card-hero'):
                    ui.label('Gefactureerd').classes('text-caption text-grey-7')
                    ui.label(format_euro(totaal)).classes(
                        'text-subtitle1 text-weight-bold').style(_kpi_style)
                if openstaand > 0:
                    with ui.card().classes('flex-1 q-pa-sm card-hero'):
                        ui.label('Openstaand').classes(
                            'text-caption text-grey-7')
                        ui.label(format_euro(openstaand)) \
                            .style(f'color: var(--q-warning); {_kpi_style}') \
                            .classes('text-subtitle1 text-weight-bold')
                if verlopen_bedrag > 0:
                    with ui.card().classes('flex-1 q-pa-sm card-hero'):
                        ui.label('Verlopen').classes(
                            'text-caption text-grey-7')
                        ui.label(format_euro(verlopen_bedrag)) \
                            .style(f'color: var(--q-negative); {_kpi_style}') \
                            .classes('text-subtitle1 text-weight-bold')

            summary_row.clear()
            with summary_row:
                ui.label(f'{len(rows)} facturen').classes('text-body2')
                ui.label(f'Totaal: {format_euro(totaal)}') \
                    .classes('text-body1 text-weight-bold')
                if openstaand > 0:
                    ui.label(f'Openstaand: {format_euro(openstaand)}') \
                        .classes('text-body1 text-orange')

        async def on_mark_betaald(e):
            row = e.args
            with ui.dialog() as dialog, ui.card():
                ui.label(f"Factuur {row['nummer']} markeren als betaald?")
                ui.label(f"{row['klant_naam']} — {row['bedrag_fmt']}").classes('text-grey')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def do_mark():
                        await mark_betaald(DB_PATH, factuur_id=row['id'],
                                           datum=date.today().isoformat())
                        dialog.close()
                        ui.notify(f"Factuur {row['nummer']} gemarkeerd als betaald",
                                  type='positive')
                        await refresh_table()

                    ui.button('Ja, betaald', on_click=do_mark).props('color=positive')
            dialog.open()

        async def on_mark_onbetaald(e):
            row = e.args
            with ui.dialog() as dialog, ui.card():
                ui.label(f"Factuur {row['nummer']} markeren als onbetaald?") \
                    .classes('text-h6')
                ui.label(f"{row['klant_naam']} — {row['bedrag_fmt']}") \
                    .classes('text-grey')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def do_mark():
                        await mark_betaald(DB_PATH, factuur_id=row['id'],
                                           datum='', betaald=False)
                        dialog.close()
                        ui.notify(f"Factuur {row['nummer']} gemarkeerd als onbetaald",
                                  type='info')
                        await refresh_table()

                    ui.button('Ja, onbetaald', on_click=do_mark) \
                        .props('color=warning')
            dialog.open()

        async def on_delete_factuur(e):
            row = e.args
            with ui.dialog() as dialog, ui.card():
                ui.label(f"Factuur {row['nummer']} verwijderen?") \
                    .classes('text-h6')
                ui.label(f"{row['klant_naam']} — {row['bedrag_fmt']}") \
                    .classes('text-grey')
                ui.label(
                    'Werkdagen worden losgekoppeld en weer beschikbaar '
                    'voor facturatie.'
                ).classes('text-caption text-grey q-mt-sm')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def do_delete():
                        await delete_factuur(DB_PATH, factuur_id=row['id'])
                        dialog.close()
                        ui.notify(f"Factuur {row['nummer']} verwijderd",
                                  type='positive')
                        await refresh_table()

                    ui.button('Verwijderen', on_click=do_delete) \
                        .props('color=negative')
            dialog.open()

        async def on_bulk_delete():
            selected = table.selected
            if not selected:
                return
            nummers = [r['nummer'] for r in selected]
            with ui.dialog() as dialog, ui.card():
                ui.label(f'{len(selected)} facturen verwijderen?') \
                    .classes('text-h6')
                ui.label(', '.join(nummers)).classes('text-grey')
                ui.label(
                    'Werkdagen worden losgekoppeld en weer beschikbaar '
                    'voor facturatie.'
                ).classes('text-caption text-grey q-mt-sm')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def do_bulk():
                        for r in selected:
                            await delete_factuur(DB_PATH, factuur_id=r['id'])
                        dialog.close()
                        ui.notify(f'{len(selected)} facturen verwijderd',
                                  type='positive')
                        await refresh_table()

                    ui.button('Verwijderen', on_click=do_bulk) \
                        .props('color=negative')
            dialog.open()

        async def on_bulk_betaald():
            selected = table.selected
            if not selected:
                return
            n = len(selected)
            with ui.dialog() as dialog, ui.card():
                ui.label(f'{n} facturen markeren als betaald?').classes('text-h6')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def do_bulk_betaald():
                        today = date.today().isoformat()
                        for row in selected:
                            if not row.get('betaald'):
                                await mark_betaald(DB_PATH,
                                                   factuur_id=row['id'],
                                                   datum=today)
                        dialog.close()
                        ui.notify(f'{n} facturen gemarkeerd als betaald',
                                  type='positive')
                        await refresh_table()

                    ui.button('Ja, betaald', on_click=do_bulk_betaald) \
                        .props('color=positive')
            dialog.open()

        async def on_download(e):
            row = e.args
            pdf_path = row.get('pdf_pad', '')
            if pdf_path and Path(pdf_path).exists():
                ui.download(pdf_path)
            else:
                ui.notify('PDF niet gevonden', type='warning')

        async def on_open_finder(e):
            row = e.args
            pdf_path = row.get('pdf_pad', '')
            if pdf_path and Path(pdf_path).exists():
                await asyncio.to_thread(subprocess.run, ['open', '-R', pdf_path])
            else:
                ui.notify('PDF niet gevonden', type='warning')

        async def on_preview(e):
            row = e.args
            pdf_path = row.get('pdf_pad', '')
            if not pdf_path or not Path(pdf_path).exists():
                ui.notify('PDF niet gevonden', type='warning')
                return
            # Determine the correct static URL path
            p = Path(pdf_path)
            # PDFs can be in data/facturen/ or data/facturen/imports/
            try:
                rel = p.relative_to(PDF_DIR)
            except ValueError:
                ui.notify('PDF buiten facturenmap', type='warning')
                return
            url = f'/facturen-files/{rel}'
            with ui.dialog().classes('full-width') as dlg, \
                    ui.card().classes('w-full q-pa-none') \
                    .style('max-width: 900px; height: 85vh'):
                with ui.row().classes(
                    'w-full justify-between items-center q-pa-sm'
                ):
                    ui.label(f"Factuur {row['nummer']}").classes('text-h6')
                    ui.button(icon='close', on_click=dlg.close) \
                        .props('flat round dense')
                ui.html(
                    f'<iframe src="{url}" '
                    f'style="width:100%;height:calc(85vh - 56px);'
                    f'border:none"></iframe>'
                )
            dlg.open()

        async def on_edit(e):
            row = e.args
            await open_edit_dialog(row)

        async def open_edit_dialog(row):
            """Open dialog to edit factuur details."""
            klanten = await get_klanten(DB_PATH, alleen_actief=False)
            klant_options = {k.id: k.naam for k in klanten}
            upload_file = {}

            with ui.dialog() as dialog, \
                    ui.card().classes('w-full max-w-lg q-pa-md'):
                ui.label('Factuur bewerken').classes('text-h6 q-mb-md')

                # Nummer (read-only)
                with ui.row().classes('w-full items-center gap-2'):
                    ui.label('Factuurnummer:').classes(
                        'text-subtitle2 text-grey-8')
                    ui.label(row['nummer']).classes('text-subtitle2')
                    type_label = ('ANW' if row.get('type') == 'anw'
                                  else 'Dagpraktijk')
                    ui.badge(type_label, color='info').classes('q-ml-sm')

                ui.separator().classes('q-my-sm')

                # Datum
                edit_datum = date_input('Factuurdatum', value=row['datum'])

                # Klant
                edit_klant = ui.select(
                    klant_options, label='Klant',
                    value=row.get('klant_id'),
                    with_input=True,
                ).classes('w-full')

                # Bedrag
                edit_bedrag = ui.number(
                    'Totaalbedrag (€)', value=row['totaal_bedrag'],
                    format='%.2f',
                ).classes('w-full')

                # Type
                edit_type = ui.select(
                    {'factuur': 'Dagpraktijk', 'anw': 'ANW'},
                    label='Type', value=row.get('type', 'factuur'),
                ).classes('w-full')

                # Betaald
                ui.separator().classes('q-my-sm')
                with ui.row().classes('w-full items-center gap-4'):
                    edit_betaald = ui.checkbox(
                        'Betaald', value=row['betaald'])
                    edit_betaald_datum = ui.input(
                        'Betaaldatum',
                        value=row.get('betaald_datum', ''),
                    ).classes('w-40')
                    edit_betaald_datum.bind_visibility_from(
                        edit_betaald, 'value')

                # PDF section
                ui.separator().classes('q-my-sm')
                ui.label('Document').classes(
                    'text-caption').style('color: #64748B')
                existing_pdf = row.get('pdf_pad', '')
                pdf_removed = {'value': False}

                if existing_pdf and Path(existing_pdf).exists():
                    pdf_row = ui.row().classes('items-center gap-2')
                    with pdf_row:
                        ui.icon('attach_file', color='primary')
                        ui.label(
                            Path(existing_pdf).name
                        ).classes('text-body2')
                        ui.button(
                            'Download', icon='download',
                            on_click=lambda: ui.download(existing_pdf),
                        ).props('flat dense size=sm')

                        def remove_pdf():
                            pdf_removed['value'] = True
                            pdf_row.set_visibility(False)
                            ui.notify(
                                'PDF wordt verwijderd bij opslaan',
                                type='info')

                        ui.button(
                            'Verwijder', icon='delete',
                            on_click=remove_pdf,
                        ).props('flat dense size=sm color=negative')

                ui.upload(
                    label='Nieuwe PDF uploaden', auto_upload=True,
                    on_upload=lambda e: upload_file.update({'event': e}),
                    max_file_size=10_000_000,
                ).classes('w-full').props(
                    'flat bordered accept=".pdf,.jpg,.jpeg,.png"')

                # Action buttons
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button(
                        'Annuleren', on_click=dialog.close,
                    ).props('flat')

                    async def opslaan():
                        if not edit_klant.value:
                            ui.notify('Selecteer een klant', type='warning')
                            return
                        try:
                            await _do_opslaan()
                        except Exception as exc:
                            ui.notify(f'Fout bij opslaan: {exc}',
                                      type='negative')

                    async def _do_opslaan():
                        # Update main fields
                        kwargs = {
                            'datum': edit_datum.value,
                            'klant_id': edit_klant.value,
                            'totaal_bedrag': float(
                                edit_bedrag.value or 0),
                            'type': edit_type.value,
                        }
                        await update_factuur(
                            DB_PATH, factuur_id=row['id'], **kwargs)

                        # Handle betaald change (cascades to werkdagen)
                        new_betaald = edit_betaald.value
                        if new_betaald != row['betaald']:
                            await mark_betaald(
                                DB_PATH, factuur_id=row['id'],
                                datum=(edit_betaald_datum.value
                                       or date.today().isoformat())
                                if new_betaald else '',
                                betaald=bool(new_betaald))
                        elif (new_betaald
                              and edit_betaald_datum.value
                              != row.get('betaald_datum', '')):
                            await mark_betaald(
                                DB_PATH, factuur_id=row['id'],
                                datum=edit_betaald_datum.value)

                        # Handle PDF removal
                        if pdf_removed['value'] and existing_pdf:
                            await update_factuur(
                                DB_PATH, factuur_id=row['id'],
                                pdf_pad='')
                            p = Path(existing_pdf)
                            if p.exists():
                                p.unlink()

                        # Handle PDF upload
                        if upload_file.get('event'):
                            evt = upload_file['event']
                            import_dir = PDF_DIR / 'imports'
                            import_dir.mkdir(parents=True, exist_ok=True)
                            safe_name = Path(
                                evt.file.name).name.replace(' ', '_')
                            filename = (
                                f'factuur_{row["id"]}_{safe_name}')
                            filepath = import_dir / filename
                            await evt.file.save(filepath)
                            await update_factuur(
                                DB_PATH, factuur_id=row['id'],
                                pdf_pad=str(filepath))

                        ui.notify(
                            f'Factuur {row["nummer"]} bijgewerkt',
                            type='positive')
                        dialog.close()
                        await refresh_table()

                    ui.button(
                        'Opslaan', on_click=opslaan,
                    ).props('color=primary')
            dialog.open()

        table.on('markbetaald', on_mark_betaald)
        table.on('markonbetaald', on_mark_onbetaald)
        table.on('deletefactuur', on_delete_factuur)
        table.on('download', on_download)
        table.on('edit', on_edit)
        table.on('openfinder', on_open_finder)
        table.on('preview', on_preview)

        async def open_import_dialog():
            """Open dialog to import facturen from PDF files."""
            parsed_items = []

            klanten = await get_klanten(DB_PATH, alleen_actief=False)
            klant_lookup = {k.naam: k.id for k in klanten}
            klant_options = {k.id: k.naam for k in klanten}

            # Load existing factuurnummers for dedup
            async with get_db_ctx(DB_PATH) as conn:
                cursor = await conn.execute("SELECT nummer FROM facturen")
                existing_nummers = {row[0] for row in await cursor.fetchall()}

            with ui.dialog() as dlg, ui.card().classes('w-full max-w-5xl'):
                ui.label('Facturen importeren uit PDF').classes('text-h6 q-mb-sm')

                preview_container = ui.column().classes('w-full gap-2')
                bottom_container = ui.column().classes('w-full')

                opt_werkdagen = {'value': True}
                opt_betaald = {'value': True}

                async def handle_upload(e: events.UploadEventArguments):
                    content = await e.file.read()
                    filename = e.file.name

                    with tempfile.NamedTemporaryFile(
                        suffix='.pdf', delete=False,
                    ) as tmp:
                        tmp.write(content)
                        tmp_path = tmp.name

                    try:
                        text = await asyncio.to_thread(extract_pdf_text, tmp_path)
                        inv_type = detect_invoice_type(text)

                        if inv_type == 'dagpraktijk':
                            parsed = parse_dagpraktijk_text(text, filename)
                        elif inv_type == 'anw':
                            parsed = parse_anw_text(text, filename)
                        else:
                            parsed_items.append({
                                '_type': 'unknown', '_filename': filename,
                                '_status': 'fout',
                                '_error': 'Niet herkend PDF-formaat',
                            })
                            render_preview()
                            return

                        parsed['_type'] = inv_type
                        parsed['_filename'] = filename
                        parsed['_content'] = content

                        # Dedup check
                        nummer = parsed.get('factuurnummer')
                        if nummer and nummer in existing_nummers:
                            parsed['_status'] = 'duplicaat'
                        else:
                            parsed['_status'] = 'nieuw'

                        # Klant resolution
                        if inv_type == 'dagpraktijk':
                            suffix = (filename.split('_', 1)[1].replace('.pdf', '')
                                      if '_' in filename else None)
                            db_naam, klant_id = resolve_klant(
                                parsed.get('klant_name'), suffix, klant_lookup)
                        else:
                            db_naam, klant_id = resolve_anw_klant(
                                filename, klant_lookup)

                        parsed['_klant_naam'] = db_naam
                        parsed['_klant_id'] = klant_id

                        parsed_items.append(parsed)
                        render_preview()
                    except Exception as ex:
                        parsed_items.append({
                            '_type': 'error', '_filename': filename,
                            '_status': 'fout', '_error': str(ex),
                        })
                        render_preview()
                    finally:
                        Path(tmp_path).unlink()

                ui.upload(
                    multiple=True, on_upload=handle_upload, auto_upload=True,
                ).props(
                    'accept=".pdf" label="Sleep PDF-bestanden hierheen of '
                    'klik om te kiezen" flat bordered'
                ).classes('w-full')

                def render_preview():
                    preview_container.clear()
                    bottom_container.clear()

                    if not parsed_items:
                        return

                    with preview_container:
                        for i, item in enumerate(parsed_items):
                            status = item.get('_status', 'fout')

                            if status == 'nieuw':
                                bg_class = 'bg-green-1'
                            elif status == 'duplicaat':
                                bg_class = 'bg-grey-2'
                            else:
                                bg_class = 'bg-red-1'

                            with ui.row().classes(
                                f'w-full items-center gap-3 q-pa-sm '
                                f'rounded-borders {bg_class}'
                            ):
                                # Status badge
                                if status == 'nieuw':
                                    ui.badge('Nieuw', color='positive')
                                elif status == 'duplicaat':
                                    ui.badge('Duplicaat', color='grey')
                                else:
                                    ui.badge('Fout', color='negative')

                                # Type
                                inv_type = item.get('_type', '?')
                                type_label = ('Dagpraktijk' if inv_type == 'dagpraktijk'
                                              else 'ANW' if inv_type == 'anw'
                                              else '?')
                                ui.label(type_label).classes(
                                    'text-caption text-grey-8')

                                # Nummer
                                nummer = item.get('factuurnummer', '-')
                                ui.label(nummer).classes('text-weight-bold')

                                # Datum
                                datum = item.get('factuurdatum', '')
                                if datum:
                                    ui.label(format_datum(datum))

                                # Klant
                                klant_naam = item.get('_klant_naam')
                                if klant_naam:
                                    ui.label(klant_naam).classes(
                                        'text-grey-8')
                                elif status == 'nieuw':
                                    # Unresolved: show select
                                    sel = ui.select(
                                        klant_options, label='Klant',
                                        with_input=True,
                                    ).classes('w-64')

                                    def _make_klant_handler(idx, select):
                                        def handler(_):
                                            items = parsed_items
                                            items[idx]['_klant_id'] = select.value
                                            items[idx]['_klant_naam'] = (
                                                klant_options.get(select.value))
                                            render_bottom()
                                        return handler
                                    sel.on_value_change(
                                        _make_klant_handler(i, sel))

                                ui.space()

                                # Bedrag
                                bedrag = item.get('totaal_bedrag')
                                if bedrag:
                                    ui.label(format_euro(bedrag)).classes(
                                        'text-weight-bold')

                                # Werkdagen count
                                n_items = len(item.get('line_items', []))
                                if n_items:
                                    ui.badge(
                                        f'{n_items} dag{"en" if n_items != 1 else ""}',
                                        color='info')

                                # Error message
                                if status == 'fout':
                                    ui.label(
                                        item.get('_error', 'Fout')
                                    ).classes('text-negative text-caption')

                    render_bottom()

                def render_bottom():
                    bottom_container.clear()
                    new_count = sum(
                        1 for it in parsed_items
                        if it.get('_status') == 'nieuw' and it.get('_klant_id'))
                    dup_count = sum(
                        1 for it in parsed_items
                        if it.get('_status') == 'duplicaat')
                    unresolved = sum(
                        1 for it in parsed_items
                        if it.get('_status') == 'nieuw' and not it.get('_klant_id'))

                    with bottom_container:
                        if not parsed_items:
                            return

                        ui.separator().classes('q-my-sm')

                        # Options
                        with ui.row().classes('w-full items-center gap-4'):
                            cb_wd = ui.checkbox(
                                'Werkdagen aanmaken',
                                value=opt_werkdagen['value'],
                            )
                            cb_wd.on_value_change(
                                lambda e: opt_werkdagen.update(value=e.value))
                            cb_bt = ui.checkbox(
                                'Markeer als betaald',
                                value=opt_betaald['value'],
                            )
                            cb_bt.on_value_change(
                                lambda e: opt_betaald.update(value=e.value))

                        # Summary + import button
                        with ui.row().classes(
                            'w-full items-center gap-4 q-mt-sm'
                        ):
                            if dup_count:
                                ui.label(
                                    f'{dup_count} '
                                    f'{"duplicaten" if dup_count > 1 else "duplicaat"}'
                                    f' overgeslagen'
                                ).classes('text-caption text-grey')
                            if unresolved:
                                ui.label(
                                    f'{unresolved} zonder klant'
                                ).classes('text-caption text-warning')
                            ui.space()
                            ui.button(
                                'Annuleren', on_click=dlg.close,
                            ).props('flat')
                            if new_count > 0:
                                btn = ui.button(
                                    f'Importeer {new_count} '
                                    f'factu{"ren" if new_count != 1 else "ur"}',
                                    icon='file_download',
                                    on_click=do_import,
                                ).props('color=primary')
                                import_btn_ref['ref'] = btn

                import_btn_ref = {'ref': None}

                async def do_import():
                    """Import all new, resolved items."""
                    # Disable button to prevent double-click
                    if import_btn_ref['ref']:
                        import_btn_ref['ref'].disable()

                    imported = 0
                    errors = 0
                    werkdagen_created = 0
                    werkdagen_linked = 0

                    # Ensure PDF storage dirs exist
                    import_dir = PDF_DIR / 'imports'
                    import_dir.mkdir(parents=True, exist_ok=True)

                    for item in parsed_items:
                        if item.get('_status') != 'nieuw':
                            continue
                        klant_id = item.get('_klant_id')
                        if not klant_id:
                            continue

                        nummer = item.get('factuurnummer', '')

                        # Guard: skip if already imported (double-click / dup)
                        if nummer in existing_nummers:
                            continue

                        try:
                            datum = item.get('factuurdatum', '')
                            inv_jaar = int(datum[:4]) if len(datum) >= 4 else 0
                            fp_inv = await get_fiscale_params(
                                DB_PATH, inv_jaar) if inv_jaar else None
                            inv_km_tarief = (
                                fp_inv.km_tarief if fp_inv and fp_inv.km_tarief
                                else 0.23)
                            bedrag = item.get('totaal_bedrag', 0)
                            inv_type = item.get('_type', 'factuur')
                            line_items = item.get('line_items', [])

                            # Calculate totals from line items
                            totaal_uren = sum(
                                li.get('uren', 0) for li in line_items)
                            totaal_km = sum(
                                li.get('km', 0) for li in line_items)

                            # Save PDF file
                            safe_name = (nummer.replace('/', '-')
                                         if nummer else 'unknown')
                            pdf_dest = import_dir / f'{safe_name}.pdf'
                            content = item.get('_content', b'')
                            if content and not pdf_dest.exists():
                                await asyncio.to_thread(pdf_dest.write_bytes, content)
                            pdf_pad = str(pdf_dest) if content else ''

                            # Create factuur record
                            ftype = 'anw' if inv_type == 'anw' else 'factuur'
                            await add_factuur(
                                DB_PATH,
                                nummer=nummer,
                                klant_id=klant_id,
                                datum=datum,
                                totaal_uren=totaal_uren,
                                totaal_km=totaal_km,
                                totaal_bedrag=bedrag,
                                pdf_pad=pdf_pad,
                                betaald=1 if opt_betaald['value'] else 0,
                                betaald_datum=(datum if opt_betaald['value']
                                              else ''),
                                type=ftype,
                            )

                            # Track for dedup
                            existing_nummers.add(nummer)
                            imported += 1

                            # Create or link werkdagen
                            if opt_werkdagen['value'] and line_items:
                                async with get_db_ctx(DB_PATH) as conn:
                                    for li in line_items:
                                        li_datum = li.get('datum', '')
                                        if not li_datum:
                                            continue

                                        cur = await conn.execute(
                                            "SELECT id FROM werkdagen "
                                            "WHERE datum = ? AND klant_id = ?",
                                            (li_datum, klant_id),
                                        )
                                        existing_wd = await cur.fetchone()

                                        if existing_wd:
                                            await link_werkdagen_to_factuur(
                                                DB_PATH,
                                                werkdag_ids=[existing_wd[0]],
                                                factuurnummer=nummer,
                                            )
                                            werkdagen_linked += 1
                                        else:
                                            if inv_type == 'anw':
                                                code = li.get(
                                                    'dienst_code', '')
                                                activiteit = 'Achterwacht'
                                                uren = li.get('uren', 0)
                                                bedrag_li = li.get(
                                                    'bedrag', 0)
                                                tarief = (
                                                    round(bedrag_li / uren, 2)
                                                    if uren else 0)
                                                km = 0.0
                                                km_tarief = inv_km_tarief
                                                urennorm = 0
                                            else:
                                                uren_val = li.get('uren', 0)
                                                tarief_val = li.get(
                                                    'tarief', 0)
                                                code = (
                                                    f'WDAGPRAKTIJK_'
                                                    f'{tarief_val:.2f}'
                                                    .replace('.', ','))
                                                activiteit = (
                                                    'Waarneming dagpraktijk')
                                                uren = uren_val
                                                tarief = tarief_val
                                                km = li.get('km', 0)
                                                km_tarief = li.get(
                                                    'km_tarief', inv_km_tarief)
                                                urennorm = 1

                                            await add_werkdag(
                                                DB_PATH,
                                                datum=li_datum,
                                                klant_id=klant_id,
                                                code=code,
                                                activiteit=activiteit,
                                                uren=uren,
                                                km=km,
                                                tarief=tarief,
                                                km_tarief=km_tarief,
                                                status='gefactureerd',
                                                factuurnummer=nummer,
                                                urennorm=urennorm,
                                            )
                                            werkdagen_created += 1

                        except Exception as ex:
                            errors += 1
                            ui.notify(
                                f'Fout bij {nummer}: {ex}',
                                type='negative')

                    dlg.close()

                    parts = [f'{imported} facturen geïmporteerd']
                    if werkdagen_created:
                        parts.append(
                            f'{werkdagen_created} werkdagen aangemaakt')
                    if werkdagen_linked:
                        parts.append(
                            f'{werkdagen_linked} werkdagen gekoppeld')
                    if errors:
                        parts.append(f'{errors} fouten')
                    ui.notify(', '.join(parts),
                              type='positive' if not errors else 'warning')
                    await refresh_table()

            dlg.open()

        async def open_new_factuur_dialog():
            klanten = await get_klanten(DB_PATH, alleen_actief=True)

            # Check for pre-selected werkdagen from werkdagen page
            pre_selected_ids = app.storage.user.pop('selected_werkdagen', None)

            with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl q-pa-lg'):
                ui.label('Nieuwe factuur aanmaken').classes('text-h6 q-mb-md')

                # --- Klant selection: dropdown OR free text ---
                klant_options = {k.id: k.naam for k in klanten}

                pre_klant_id = None
                if pre_selected_ids:
                    from database import get_werkdagen
                    pre_werkdagen = await get_werkdagen(DB_PATH)
                    pre_klant_ids = {
                        w.klant_id for w in pre_werkdagen
                        if w.id in pre_selected_ids
                    }
                    if len(pre_klant_ids) == 1:
                        pre_klant_id = pre_klant_ids.pop()
                    else:
                        ui.notify(
                            'Selecteer werkdagen van één klant',
                            type='warning')

                klant_select = ui.select(
                    klant_options, label='Klant (of typ een naam)',
                    value=pre_klant_id,
                    with_input=True, new_value_mode='add-unique',
                ).classes('w-full').props('use-input input-debounce=0')

                # Manual klant address (shown when free-text klant is entered)
                manual_adres_container = ui.column().classes('w-full')
                manual_adres_input = {'ref': None}

                def on_klant_change(e):
                    val = klant_select.value
                    manual_adres_container.clear()
                    # If value is a string (typed), show address field
                    if isinstance(val, str) and val not in [
                            k.naam for k in klanten]:
                        with manual_adres_container:
                            manual_adres_input['ref'] = ui.input(
                                'Adres klant',
                                placeholder='Straat, Postcode Plaats',
                            ).classes('w-full')
                    else:
                        manual_adres_input['ref'] = None

                klant_select.on_value_change(
                    lambda e: (on_klant_change(e), load_werkdagen()))

                # Date input
                datum_input = date_input('Factuurdatum',
                                         value=date.today().isoformat())

                # --- Werkdagen selection ---
                werkdagen_container = ui.column().classes('w-full')
                selected_werkdagen = {'ids': set(), 'data': []}

                # --- Manual line items ---
                manual_lines = {'items': []}
                manual_container = ui.column().classes('w-full q-mt-sm')

                def add_manual_line():
                    """Add a custom line item row."""
                    line = {'omschrijving': '', 'aantal': 1, 'tarief': 0.0}
                    manual_lines['items'].append(line)
                    idx = len(manual_lines['items']) - 1

                    with manual_container:
                        with ui.row().classes('w-full gap-2 items-end'):
                            om = ui.input('Omschrijving',
                                          value='').classes('flex-grow')
                            aa = ui.number('Aantal', value=1,
                                           min=0, step=1).classes('w-20')
                            ta = ui.number('Tarief (€)', value=0,
                                           format='%.2f', min=0,
                                           step=0.50).classes('w-28')

                            def make_updater(i, om_ref, aa_ref, ta_ref):
                                def update(_=None):
                                    manual_lines['items'][i] = {
                                        'omschrijving': om_ref.value or '',
                                        'aantal': float(aa_ref.value or 0),
                                        'tarief': float(ta_ref.value or 0),
                                    }
                                    update_preview()
                                return update

                            updater = make_updater(idx, om, aa, ta)
                            om.on('blur', updater)
                            aa.on_value_change(updater)
                            ta.on_value_change(updater)

                            def make_remover(i):
                                def remove():
                                    manual_lines['items'][i] = None
                                    update_preview()
                                return remove

                            ui.button(icon='close',
                                      on_click=make_remover(idx)) \
                                .props('flat round dense size=sm color=negative')

                ui.button('+ Voeg regel toe', icon='add',
                          on_click=add_manual_line) \
                    .props('flat dense color=primary').classes('q-mt-sm')

                # --- Preview ---
                preview_container = ui.column().classes('w-full q-mt-md')

                async def load_werkdagen():
                    kid = klant_select.value
                    werkdagen_container.clear()
                    selected_werkdagen['ids'] = set()
                    selected_werkdagen['data'] = []

                    # Only load werkdagen for known DB klanten (int id)
                    if not kid or not isinstance(kid, int):
                        update_preview()
                        return

                    werkdagen = await get_werkdagen_ongefactureerd(
                        DB_PATH, klant_id=kid)
                    selected_werkdagen['data'] = werkdagen

                    with werkdagen_container:
                        if not werkdagen:
                            ui.label(
                                'Geen ongefactureerde werkdagen.') \
                                .classes('text-grey')
                        else:
                            ui.label(
                                f'{len(werkdagen)} ongefactureerde '
                                f'werkdagen:').classes('text-subtitle2')
                            for w in werkdagen:
                                bedrag = (w.uren * w.tarief
                                          + w.km * w.km_tarief)
                                cb = ui.checkbox(
                                    f'{w.datum} — {w.uren}u × '
                                    f'{format_euro(w.tarief)} '
                                    f'+ {w.km} km = '
                                    f'{format_euro(bedrag)}',
                                    value=True,
                                )
                                selected_werkdagen['ids'].add(w.id)

                                def make_handler(wid, checkbox):
                                    def handler(e):
                                        if checkbox.value:
                                            selected_werkdagen['ids'].add(
                                                wid)
                                        else:
                                            selected_werkdagen['ids'] \
                                                .discard(wid)
                                        update_preview()
                                    return handler

                                cb.on_value_change(
                                    make_handler(w.id, cb))
                    update_preview()

                def update_preview():
                    preview_container.clear()

                    # Werkdagen totals
                    ids = selected_werkdagen['ids']
                    data = selected_werkdagen['data']
                    sel_wd = [w for w in data if w.id in ids]

                    wd_uren = sum(w.uren for w in sel_wd)
                    wd_km = sum(w.km for w in sel_wd)
                    wd_werk = sum(w.uren * w.tarief for w in sel_wd)
                    wd_reis = sum(w.km * w.km_tarief for w in sel_wd)

                    # Manual line totals
                    ml_items = [m for m in manual_lines['items']
                                if m is not None]
                    ml_total = sum(
                        m['aantal'] * m['tarief'] for m in ml_items)

                    grand_total = wd_werk + wd_reis + ml_total

                    if not sel_wd and not ml_items:
                        return

                    # Default date to last werkdag
                    if sel_wd:
                        datum_input.value = max(w.datum for w in sel_wd)

                    with preview_container:
                        ui.separator()
                        ui.label('Preview').classes('text-subtitle2')
                        if sel_wd:
                            with ui.row().classes('gap-6'):
                                ui.label(f'Uren: {wd_uren:.1f}')
                                ui.label(f'Km: {wd_km:.0f}')
                                ui.label(f'Waarnemingen: '
                                         f'{format_euro(wd_werk)}')
                                if wd_reis > 0:
                                    ui.label(f'Reiskosten: '
                                             f'{format_euro(wd_reis)}')
                        if ml_items:
                            ui.label(
                                f'Handmatige regels: '
                                f'{format_euro(ml_total)}')
                        ui.label(f'Totaal: {format_euro(grand_total)}') \
                            .classes('text-h6 text-weight-bold')

                # Auto-load werkdagen if klant was pre-selected
                if pre_klant_id:
                    await load_werkdagen()

                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren',
                              on_click=dialog.close).props('flat')

                    async def genereer_factuur():
                        kid = klant_select.value
                        if not kid:
                            ui.notify('Selecteer of typ een klant',
                                      type='warning')
                            return

                        ids = selected_werkdagen['ids']
                        data = selected_werkdagen['data']
                        selected = [w for w in data if w.id in ids]
                        ml_items = [m for m in manual_lines['items']
                                    if m is not None]

                        if not selected and not ml_items:
                            ui.notify(
                                'Selecteer werkdagen of voeg regels toe',
                                type='warning')
                            return

                        # Resolve klant info
                        if isinstance(kid, int):
                            klant = next(
                                (k for k in klanten if k.id == kid), None)
                            klant_dict = {
                                'naam': klant.naam,
                                'adres': klant.adres,
                            } if klant else {'naam': str(kid), 'adres': ''}
                            db_klant_id = kid
                        else:
                            # Free-text klant
                            adres = (manual_adres_input['ref'].value
                                     if manual_adres_input['ref'] else '')
                            klant_dict = {
                                'naam': str(kid), 'adres': adres}
                            # For DB: create a temporary klant or use id=0
                            # We store with klant_id of the first active klant
                            # and note the manual name in the PDF
                            db_klant_id = klanten[0].id if klanten else 1

                        factuur_datum = (datum_input.value
                                         or date.today().isoformat())
                        jaar = int(factuur_datum[:4])
                        nummer = await get_next_factuurnummer(
                            DB_PATH, jaar=jaar)

                        # Prepare werkdagen data for invoice generator
                        wd_dicts = []
                        for w in selected:
                            loc = w.locatie
                            if isinstance(kid, int):
                                klant_obj = next(
                                    (k for k in klanten if k.id == kid),
                                    None)
                                if not loc and klant_obj:
                                    loc = klant_obj.adres
                            wd_dicts.append({
                                'datum': w.datum,
                                'activiteit': w.activiteit,
                                'locatie': loc or '',
                                'uren': w.uren,
                                'tarief': w.tarief,
                                'km': w.km,
                                'km_tarief': w.km_tarief,
                            })

                        # Add manual lines as pseudo-werkdagen
                        for m in ml_items:
                            wd_dicts.append({
                                'datum': factuur_datum,
                                'activiteit': m['omschrijving'],
                                'locatie': '',
                                'uren': m['aantal'],
                                'tarief': m['tarief'],
                                'km': 0,
                                'km_tarief': 0,
                            })

                        klant_dict_final = klant_dict

                        # Load business info for invoice
                        bg = await get_bedrijfsgegevens(DB_PATH)
                        bg_dict = {}
                        if bg:
                            bg_dict = {
                                'bedrijfsnaam': bg.bedrijfsnaam, 'naam': bg.naam,
                                'functie': bg.functie, 'adres': bg.adres,
                                'postcode_plaats': bg.postcode_plaats, 'kvk': bg.kvk,
                                'iban': bg.iban, 'thuisplaats': bg.thuisplaats,
                            }

                        # Generate PDF
                        try:
                            pdf_path = await asyncio.to_thread(
                                generate_invoice,
                                nummer, klant_dict_final,
                                wd_dicts, PDF_DIR,
                                factuur_datum=factuur_datum,
                                bedrijfsgegevens=bg_dict,
                            )
                        except Exception as ex:
                            ui.notify(f'PDF generatie mislukt: {ex}', type='negative')
                            return

                        # Calculate totals (werkdagen + manual)
                        totaal_uren = sum(w.uren for w in selected)
                        totaal_km = sum(w.km for w in selected)
                        totaal_bedrag = sum(
                            w.uren * w.tarief + w.km * w.km_tarief
                            for w in selected
                        ) + sum(
                            m['aantal'] * m['tarief'] for m in ml_items
                        )

                        # Save factuur record
                        await add_factuur(
                            DB_PATH,
                            nummer=nummer,
                            klant_id=db_klant_id,
                            datum=factuur_datum,
                            totaal_uren=totaal_uren,
                            totaal_km=totaal_km,
                            totaal_bedrag=totaal_bedrag,
                            pdf_pad=str(pdf_path),
                        )

                        # Link werkdagen
                        await link_werkdagen_to_factuur(
                            DB_PATH,
                            werkdag_ids=list(ids),
                            factuurnummer=nummer,
                        )

                        dialog.close()
                        ui.notify(
                            f'Factuur {nummer} aangemaakt ({format_euro(totaal_bedrag)})',
                            type='positive'
                        )
                        await refresh_table()

                    ui.button('Genereer factuur', icon='receipt',
                              on_click=genereer_factuur).props('color=primary')

            dialog.open()

        jaar_select.on_value_change(lambda _: refresh_table())
        await refresh_table()

        # Auto-open factuur dialog if coming from werkdagen with pre-selected IDs
        pre_selected = app.storage.user.get('selected_werkdagen', None)
        if pre_selected:
            await open_new_factuur_dialog()
