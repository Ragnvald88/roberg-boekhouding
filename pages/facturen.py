"""Facturen pagina — factuur aanmaken, overzicht en betaalstatus."""

import asyncio
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from nicegui import app, events, ui

from components.layout import create_layout, page_title
from components.invoice_builder import open_invoice_builder
from components.utils import format_euro, format_datum, generate_csv
from database import (
    get_facturen, add_factuur,
    delete_factuur, update_factuur,
    update_factuur_status, get_klanten,
    get_bedrijfsgegevens,
    link_werkdagen_to_factuur, get_db_ctx, add_werkdag,
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
            status_options = {'': 'Alle', 'concept': 'Concept', 'verstuurd': 'Verstuurd',
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
                status_labels = {'concept': 'Concept', 'verstuurd': 'Verstuurd',
                                 'betaald': 'Betaald'}
                rows = [[f.nummer, f.datum, f.klant_naam, f.totaal_uren,
                         f.totaal_km, f.totaal_bedrag,
                         status_labels.get(f.status, f.status.capitalize())]
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
                      on_click=lambda: open_invoice_builder(
                          on_save=refresh_table)) \
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
                <q-badge v-if="props.row.status === 'betaald'" color="positive" label="Betaald" />
                <q-badge v-else-if="props.row.verlopen" color="negative" label="Verlopen" />
                <q-badge v-else-if="props.row.status === 'verstuurd'" color="info" label="Verstuurd" />
                <q-badge v-else color="grey-6" label="Concept" />
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
                            <q-item v-if="props.row.status === 'concept'" clickable
                                @click="() => $parent.$emit('edit', props.row)">
                                <q-item-section side>
                                    <q-icon name="edit" size="xs"
                                            color="primary" />
                                </q-item-section>
                                <q-item-section>Bewerken</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.pdf_pad && props.row.status !== 'concept'" clickable
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
                            <q-item v-if="props.row.status === 'concept'" clickable
                                @click="() => $parent.$emit('sendmail', props.row)">
                                <q-item-section side>
                                    <q-icon name="email" size="xs"
                                            color="info" />
                                </q-item-section>
                                <q-item-section>Verstuur via e-mail</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.status === 'concept'" clickable
                                @click="() => $parent.$emit('markverstuurd', props.row)">
                                <q-item-section side>
                                    <q-icon name="send" size="xs"
                                            color="info" />
                                </q-item-section>
                                <q-item-section>Markeer als verstuurd</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.status === 'verstuurd' || props.row.verlopen" clickable
                                @click="() => $parent.$emit('sendmail', props.row)">
                                <q-item-section side>
                                    <q-icon name="email" size="xs" />
                                </q-item-section>
                                <q-item-section>Verstuur opnieuw</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.status === 'verstuurd' || props.row.verlopen" clickable
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
                            <q-item v-if="props.row.status === 'betaald'" clickable
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
            if status_val == 'concept':
                facturen = [f for f in facturen if f.status == 'concept']
            elif status_val == 'verstuurd':
                facturen = [f for f in facturen
                            if f.status == 'verstuurd' and not _is_verlopen(f.datum)]
            elif status_val == 'verlopen':
                facturen = [f for f in facturen
                            if f.status == 'verstuurd' and _is_verlopen(f.datum)]
            elif status_val == 'betaald':
                facturen = [f for f in facturen if f.status == 'betaald']

            rows = []
            totaal = 0
            openstaand = 0
            for f in facturen:
                # Compute verlopen status (only applies to verstuurd invoices)
                is_verlopen = f.status == 'verstuurd' and _is_verlopen(f.datum)
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
                    'status': f.status,
                    'betaald_datum': f.betaald_datum,
                    'pdf_pad': f.pdf_pad,
                    'type': f.type,
                })
                totaal += f.totaal_bedrag
                if f.status != 'betaald' and f.status != 'concept':
                    openstaand += f.totaal_bedrag

            table.rows = rows
            table.selected.clear()
            table.update()
            update_bulk_bar()

            # Update KPI strip
            verlopen_bedrag = sum(r['totaal_bedrag'] for r in rows
                                  if r.get('verlopen') and r.get('status') == 'verstuurd')
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
                        await update_factuur_status(DB_PATH, factuur_id=row['id'],
                                                    status='betaald',
                                                    betaald_datum=date.today().isoformat())
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
                        await update_factuur_status(DB_PATH, factuur_id=row['id'],
                                                    status='verstuurd',
                                                    betaald_datum='')
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
                            if row.get('status') != 'betaald':
                                await update_factuur_status(
                                    DB_PATH, factuur_id=row['id'],
                                    status='betaald',
                                    betaald_datum=today)
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

                # Status
                ui.separator().classes('q-my-sm')
                with ui.row().classes('w-full items-center gap-4'):
                    edit_status = ui.select(
                        {'concept': 'Concept', 'verstuurd': 'Verstuurd',
                         'betaald': 'Betaald'},
                        label='Status', value=row['status'],
                    ).classes('w-40')
                    edit_betaald_datum = ui.input(
                        'Betaaldatum',
                        value=row.get('betaald_datum', ''),
                    ).classes('w-40')
                    edit_betaald_datum.bind_visibility_from(
                        edit_status, 'value',
                        backward=lambda v: v == 'betaald')

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

                        # Handle status change (cascades to werkdagen)
                        new_status = edit_status.value
                        if new_status != row['status']:
                            betaald_datum = ''
                            if new_status == 'betaald':
                                betaald_datum = (edit_betaald_datum.value
                                                 or date.today().isoformat())
                            await update_factuur_status(
                                DB_PATH, factuur_id=row['id'],
                                status=new_status,
                                betaald_datum=betaald_datum)
                        elif (new_status == 'betaald'
                              and edit_betaald_datum.value
                              != row.get('betaald_datum', '')):
                            await update_factuur_status(
                                DB_PATH, factuur_id=row['id'],
                                status='betaald',
                                betaald_datum=edit_betaald_datum.value)

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

        async def on_mark_verstuurd(e):
            row = e.args
            await update_factuur_status(DB_PATH, factuur_id=row['id'],
                                        status='verstuurd')
            ui.notify(f"Factuur {row['nummer']} gemarkeerd als verstuurd",
                      type='positive')
            await refresh_table()

        async def on_send_mail(e):
            """Send invoice via email using macOS Mail.app, then mark as verstuurd."""
            row = e.args
            pdf_path = row.get('pdf_pad', '')
            if not pdf_path or not Path(pdf_path).exists():
                ui.notify('PDF niet gevonden — genereer eerst de factuur', type='warning')
                return

            # Get klant email if available
            klant_id = row.get('klant_id')
            klant_email = ''
            if klant_id:
                all_klanten = await get_klanten(DB_PATH, alleen_actief=False)
                klant = next((k for k in all_klanten if k.id == klant_id), None)
                if klant and hasattr(klant, 'email'):
                    klant_email = klant.email or ''

            # Get business info for email body
            bg = await get_bedrijfsgegevens(DB_PATH)

            nummer = row['nummer']
            bedrag = format_euro(row['totaal_bedrag'])
            iban = bg.iban if bg else 'NL00 TEST 0000 0000 00'
            bedrijfsnaam = bg.bedrijfsnaam if bg else 'TestBV huisartswaarnemer'
            naam = bg.naam if bg else 'Test Gebruiker'

            subject = f'Factuur {nummer}'
            body = (
                f'Bijgaand stuur ik u factuur {nummer}.\\n'
                f'\\n'
                f'Het totaalbedrag van {bedrag} verzoek ik u binnen 14 dagen '
                f'over te maken op rekeningnummer {iban} t.n.v. {bedrijfsnaam}, '
                f'onder vermelding van factuurnummer {nummer}.\\n'
                f'\\n'
                f'Mocht u vragen hebben, dan hoor ik het graag.\\n'
                f'\\n'
                f'\\n'
                f'Met vriendelijke groet,\\n'
                f'\\n'
                f'{naam}\\n'
                f'\\n'
                f'{bedrijfsnaam}\\n'
                f'Tel: 06 0000 0000\\n'
                f'info@testbedrijf.nl'
            )

            # Escape for AppleScript (double backslash for quotes)
            body_osa = body.replace('\\', '\\\\').replace('"', '\\\\"')
            subject_osa = subject.replace('"', '\\\\"')
            pdf_path_abs = str(Path(pdf_path).resolve())

            # Build AppleScript
            to_line = ''
            if klant_email:
                to_line = f'make new to recipient with properties {{address:"{klant_email}"}}'

            applescript = (
                'tell application "Mail"\n'
                f'  set newMsg to make new outgoing message with properties '
                f'{{subject:"{subject_osa}", content:"{body_osa}", visible:true}}\n'
                f'  tell newMsg\n'
                f'    {to_line}\n'
                f'    make new attachment with properties '
                f'{{file name:POSIX file "{pdf_path_abs}"}} '
                f'at after last paragraph of content\n'
                f'  end tell\n'
                f'  activate\n'
                f'end tell'
            )

            try:
                await asyncio.to_thread(
                    subprocess.run,
                    ['osascript', '-e', applescript],
                    capture_output=True, timeout=15)

                # Mark as verstuurd if currently concept
                if row.get('status') == 'concept':
                    await update_factuur_status(
                        DB_PATH, factuur_id=row['id'], status='verstuurd')

                ui.notify(f'Factuur {nummer} geopend in Mail.app', type='positive')
                await refresh_table()
            except subprocess.TimeoutExpired:
                ui.notify('Mail.app reageerde niet — probeer handmatig', type='warning')
            except Exception as ex:
                ui.notify(f'Fout bij openen Mail.app: {ex}', type='negative')

        table.on('markbetaald', on_mark_betaald)
        table.on('markonbetaald', on_mark_onbetaald)
        table.on('markverstuurd', on_mark_verstuurd)
        table.on('sendmail', on_send_mail)
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
                                status='betaald' if opt_betaald['value'] else 'verstuurd',
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

        jaar_select.on_value_change(lambda _: refresh_table())
        await refresh_table()

        # Auto-open invoice builder if coming from werkdagen with pre-selected IDs
        pre_selected = app.storage.user.pop('selected_werkdagen', None)
        if pre_selected:
            await open_invoice_builder(
                on_save=refresh_table,
                pre_selected_werkdag_ids=pre_selected)
