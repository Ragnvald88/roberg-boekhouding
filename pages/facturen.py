"""Facturen pagina — factuur aanmaken, overzicht en betaalstatus."""

from datetime import date, datetime

from nicegui import app, ui

from pathlib import Path

from components.layout import create_layout
from components.invoice_generator import generate_invoice
from components.utils import format_euro, format_datum
from database import (
    get_facturen, add_factuur, get_next_factuurnummer,
    mark_betaald, delete_factuur, get_klanten, get_werkdagen_ongefactureerd,
    link_werkdagen_to_factuur, get_bedrijfsgegevens, DB_PATH,
)

PDF_DIR = DB_PATH.parent / "facturen"


@ui.page('/facturen')
async def facturen_page():
    create_layout('Facturen', '/facturen')

    current_year = date.today().year
    table_ref = {'ref': None}
    bulk_bar_ref = {'ref': None}

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        # Header + filter
        with ui.row().classes('w-full items-center gap-4'):
            ui.label('Facturen').classes('text-h5') \
                .style('color: #0F172A; font-weight: 700')
            ui.space()
            jaar_select = ui.select(
                {y: str(y) for y in range(2023, current_year + 2)},
                value=current_year, label='Jaar',
            ).classes('w-32')

            ui.button('Nieuwe factuur', icon='add',
                      on_click=lambda: open_new_factuur_dialog()) \
                .props('color=primary')

        # Bulk action toolbar (hidden when nothing selected)
        bulk_bar = ui.row().classes('w-full items-center gap-4')
        bulk_bar.set_visibility(False)
        bulk_bar_ref['ref'] = bulk_bar
        with bulk_bar:
            bulk_label = ui.label('')
            ui.button('Verwijder selectie', icon='delete',
                      on_click=lambda: on_bulk_delete()) \
                .props('color=negative outline')

        # Facturen table
        columns = [
            {'name': 'nummer', 'label': 'Nummer', 'field': 'nummer',
             'sortable': True, 'align': 'left'},
            {'name': 'datum', 'label': 'Datum', 'field': 'datum_fmt',
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
            pagination={'rowsPerPage': 20, 'sortBy': 'nummer', 'descending': True},
        ).classes('w-full')
        table_ref['ref'] = table

        table.add_slot('body-cell-status', '''
            <q-td :props="props">
                <q-badge :color="props.row.betaald ? 'positive' : 'warning'"
                         :label="props.row.betaald ? 'Betaald' : 'Openstaand'" />
            </q-td>
        ''')

        table.add_slot('no-data', '''
            <q-tr><q-td colspan="100%" class="text-center q-pa-lg text-grey">
                Geen facturen gevonden.
            </q-td></q-tr>
        ''')

        table.add_slot('body-cell-actions', '''
            <q-td :props="props">
                <q-btn v-if="!props.row.betaald" icon="check_circle" flat dense
                       round size="sm" color="positive"
                       @click="() => $parent.$emit('markbetaald', props.row)"
                       title="Markeer als betaald" />
                <q-btn v-if="props.row.betaald" icon="undo" flat dense
                       round size="sm" color="grey"
                       @click="() => $parent.$emit('markonbetaald', props.row)"
                       title="Markeer als onbetaald" />
                <q-btn v-if="props.row.pdf_pad" icon="download" flat dense
                       round size="sm"
                       @click="() => $parent.$emit('download', props.row)"
                       title="Download PDF" />
                <q-btn icon="delete" flat dense round size="sm" color="negative"
                       @click="() => $parent.$emit('deletefactuur', props.row)"
                       title="Verwijderen" />
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
            rows = []
            totaal = 0
            openstaand = 0
            for f in facturen:
                rows.append({
                    'id': f.id,
                    'nummer': f.nummer,
                    'datum': f.datum,
                    'datum_fmt': format_datum(f.datum),
                    'klant_naam': f.klant_naam,
                    'totaal_uren': f.totaal_uren,
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
                with ui.row().classes('w-full justify-end gap-2 mt-2'):
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
            await mark_betaald(DB_PATH, factuur_id=row['id'],
                               datum='', betaald=False)
            ui.notify(f"Factuur {row['nummer']} gemarkeerd als onbetaald",
                      type='info')
            await refresh_table()

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
                with ui.row().classes('w-full justify-end gap-2 mt-2'):
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
                with ui.row().classes('w-full justify-end gap-2 mt-2'):
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

        async def on_download(e):
            row = e.args
            pdf_path = row.get('pdf_pad', '')
            if pdf_path and Path(pdf_path).exists():
                ui.download(pdf_path)
            else:
                ui.notify('PDF niet gevonden', type='warning')

        table.on('markbetaald', on_mark_betaald)
        table.on('markonbetaald', on_mark_onbetaald)
        table.on('deletefactuur', on_delete_factuur)
        table.on('download', on_download)

        async def open_new_factuur_dialog():
            klanten = await get_klanten(DB_PATH, alleen_actief=True)
            if not klanten:
                ui.notify('Geen actieve klanten gevonden', type='warning')
                return

            # Check for pre-selected werkdagen from werkdagen page
            pre_selected_ids = app.storage.user.pop('selected_werkdagen', None)

            with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl'):
                ui.label('Nieuwe factuur aanmaken').classes('text-h6 q-mb-md')

                # Step 1: Select klant
                klant_options = {k.id: k.naam for k in klanten}

                # Pre-select klant if werkdagen were pre-selected
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

                klant_select = ui.select(
                    klant_options, label='Klant',
                    value=pre_klant_id,
                ).classes('w-full q-mb-md')

                # Werkdagen selection container
                werkdagen_container = ui.column().classes('w-full')
                selected_werkdagen = {'ids': set(), 'data': []}
                preview_container = ui.column().classes('w-full q-mt-md')

                async def load_werkdagen():
                    kid = klant_select.value
                    if not kid:
                        return
                    werkdagen = await get_werkdagen_ongefactureerd(DB_PATH, klant_id=kid)
                    werkdagen_container.clear()
                    selected_werkdagen['ids'] = set()
                    selected_werkdagen['data'] = werkdagen

                    with werkdagen_container:
                        if not werkdagen:
                            ui.label('Geen ongefactureerde werkdagen voor deze klant.') \
                                .classes('text-grey')
                        else:
                            ui.label(f'{len(werkdagen)} ongefactureerde werkdagen:') \
                                .classes('text-subtitle2')
                            for w in werkdagen:
                                bedrag = w.uren * w.tarief + w.km * w.km_tarief
                                # Pre-check if this werkdag was pre-selected
                                is_pre = (pre_selected_ids and
                                          w.id in pre_selected_ids)
                                cb = ui.checkbox(
                                    f'{w.datum} — {w.uren}u × {format_euro(w.tarief)} '
                                    f'+ {w.km} km = {format_euro(bedrag)}',
                                    value=True,
                                )
                                selected_werkdagen['ids'].add(w.id)

                                def make_handler(wid, checkbox):
                                    def handler(e):
                                        if checkbox.value:
                                            selected_werkdagen['ids'].add(wid)
                                        else:
                                            selected_werkdagen['ids'].discard(wid)
                                        update_preview()
                                    return handler

                                cb.on_value_change(make_handler(w.id, cb))
                    update_preview()

                def update_preview():
                    preview_container.clear()
                    ids = selected_werkdagen['ids']
                    data = selected_werkdagen['data']
                    selected = [w for w in data if w.id in ids]

                    if not selected:
                        return

                    totaal_uren = sum(w.uren for w in selected)
                    totaal_km = sum(w.km for w in selected)
                    totaal_werk = sum(w.uren * w.tarief for w in selected)
                    totaal_reis = sum(w.km * w.km_tarief for w in selected)
                    totaal = totaal_werk + totaal_reis

                    with preview_container:
                        ui.separator()
                        ui.label('Preview').classes('text-subtitle2')
                        with ui.row().classes('gap-8'):
                            ui.label(f'Uren: {totaal_uren:.1f}')
                            ui.label(f'Km: {totaal_km:.0f}')
                            ui.label(f'Waarnemingen: {format_euro(totaal_werk)}')
                            ui.label(f'Reiskosten: {format_euro(totaal_reis)}')
                        ui.label(f'Totaal: {format_euro(totaal)}') \
                            .classes('text-h6 text-weight-bold')

                klant_select.on_value_change(lambda _: load_werkdagen())

                # Auto-load werkdagen if klant was pre-selected
                if pre_klant_id:
                    await load_werkdagen()

                # Date input
                datum_input = ui.input(
                    'Factuurdatum', value=date.today().isoformat()
                ).classes('w-48 q-mt-md')

                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def genereer_factuur():
                        kid = klant_select.value
                        if not kid:
                            ui.notify('Selecteer een klant', type='warning')
                            return

                        ids = selected_werkdagen['ids']
                        data = selected_werkdagen['data']
                        selected = [w for w in data if w.id in ids]

                        if not selected:
                            ui.notify('Selecteer werkdagen', type='warning')
                            return

                        klant = next(k for k in klanten if k.id == kid)
                        factuur_datum = datum_input.value or date.today().isoformat()
                        jaar = int(factuur_datum[:4])
                        nummer = await get_next_factuurnummer(DB_PATH, jaar=jaar)

                        # Prepare werkdagen data for invoice generator
                        wd_dicts = []
                        for w in selected:
                            wd_dicts.append({
                                'datum': w.datum,
                                'activiteit': w.activiteit,
                                'locatie': w.locatie or klant.adres,
                                'uren': w.uren,
                                'tarief': w.tarief,
                                'km': w.km,
                                'km_tarief': w.km_tarief,
                            })

                        klant_dict = {'naam': klant.naam, 'adres': klant.adres}

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
                            pdf_path = generate_invoice(
                                nummer, klant_dict, wd_dicts, PDF_DIR,
                                factuur_datum=factuur_datum,
                                bedrijfsgegevens=bg_dict,
                            )
                        except Exception as ex:
                            ui.notify(f'PDF generatie mislukt: {ex}', type='negative')
                            return

                        # Calculate totals
                        totaal_uren = sum(w.uren for w in selected)
                        totaal_km = sum(w.km for w in selected)
                        totaal_bedrag = sum(
                            w.uren * w.tarief + w.km * w.km_tarief
                            for w in selected
                        )

                        # Save factuur record
                        await add_factuur(
                            DB_PATH,
                            nummer=nummer,
                            klant_id=kid,
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
