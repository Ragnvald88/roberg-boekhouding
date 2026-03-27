"""Werkdagen pagina — uren/km registratie met tabel en dialog."""

from nicegui import app, ui
from components.layout import create_layout, page_title
from components.utils import format_euro, format_datum, generate_csv
from components.werkdag_form import open_werkdag_dialog
from database import (
    get_werkdagen, get_klanten, delete_werkdag, DB_PATH,
)
from datetime import date
from components.shared_ui import year_options

MAANDEN = {
    0: 'Alle', 1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'Mei', 6: 'Jun',
    7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Okt', 11: 'Nov', 12: 'Dec',
}


@ui.page('/werkdagen')
async def werkdagen_page():
    create_layout('Werkdagen', '/werkdagen')

    current_year = date.today().year
    klanten = await get_klanten(DB_PATH)
    klant_options = {0: 'Alle'} | {k.id: k.naam for k in klanten}

    # State
    table_ref = {'ref': None}
    summary_container = {'ref': None}

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        # Header row: title + primary action
        with ui.row().classes('w-full items-center'):
            page_title('Werkdagen')
            ui.space()
            ui.button(
                'Nieuwe werkdag', icon='add',
                on_click=lambda: open_werkdag_dialog(on_save=refresh_table),
            ).props('color=primary')

        # Filter bar
        with ui.element('div').classes('page-toolbar w-full'):
            jaar_select = ui.select(
                year_options(include_next=True, as_dict=True, descending=False),
                value=current_year, label='Jaar',
            ).classes('w-28')

            maand_select = ui.select(
                MAANDEN, value=0, label='Maand',
            ).classes('w-28')

            klant_sel = ui.select(
                klant_options, value=0, label='Klant',
            ).classes('w-44')

            STATUS_OPTIONS = {
                '': 'Alle',
                'ongefactureerd': 'Ongefactureerd',
                'gefactureerd': 'Gefactureerd',
                'betaald': 'Betaald',
            }
            status_sel = ui.select(
                STATUS_OPTIONS, value='', label='Status',
            ).classes('w-36')

            ui.space()

            async def export_csv():
                year = jaar_select.value
                month = maand_select.value if maand_select.value != 0 else None
                klant = klant_sel.value if klant_sel.value != 0 else None
                status = status_sel.value or None
                all_wd = await get_werkdagen(DB_PATH, jaar=year, maand=month,
                                              klant_id=klant)
                werkdagen = [w for w in all_wd
                             if status is None or w.status == status]
                headers = ['Datum', 'Klant', 'Code', 'Uren', 'Km', 'Tarief',
                           'Km-tarief', 'Totaal', 'Status']
                rows = []
                for w in werkdagen:
                    totaal = w.uren * w.tarief + w.km * w.km_tarief
                    rows.append([w.datum, w.klant_naam, w.code, w.uren,
                                 w.km, w.tarief, w.km_tarief,
                                 round(totaal, 2), w.status])
                csv_str = generate_csv(headers, rows)
                ui.download.content(csv_str.encode('utf-8-sig'),
                                    f'werkdagen_{year}.csv')

            ui.button(icon='download',
                      on_click=export_csv) \
                .props('flat round color=secondary size=sm') \
                .tooltip('Exporteer CSV')

            async def export_uren_overzicht():
                """Export uren-overzicht as CSV for urencriterium documentation."""
                rows = await get_werkdagen(DB_PATH, jaar=jaar_select.value)
                uren_rows = [w for w in rows if w.urennorm == 1]
                headers = ['Datum', 'Klant', 'Locatie', 'Uren', 'Activiteit']
                csv_rows = [[format_datum(w.datum), w.klant_naam, w.locatie or '',
                              str(w.uren), w.activiteit] for w in uren_rows]
                totaal = sum(w.uren for w in uren_rows)
                csv_rows.append(['', '', 'TOTAAL', str(totaal), ''])
                csv_data = generate_csv(headers, csv_rows)
                ui.download(
                    csv_data.encode('utf-8-sig'),
                    f'urenregistratie_{jaar_select.value}.csv')

            ui.button('Urenregistratie', icon='schedule',
                      on_click=export_uren_overzicht).props('outline size=sm')

            async def export_km_logboek():
                """Export km-logboek as CSV for Belastingdienst documentation."""
                rows = await get_werkdagen(DB_PATH, jaar=jaar_select.value)
                klanten_dict = {k.id: k for k in await get_klanten(DB_PATH)}
                km_rows = [w for w in rows if w.km and w.km > 0]
                headers = ['Datum', 'Klant', 'Locatie', 'Vertrek', 'Bestemming',
                           'Retour km', 'Doel']
                csv_rows = []
                for w in km_rows:
                    klant = klanten_dict.get(w.klant_id)
                    bestemming = w.locatie or (klant.naam if klant else '')
                    csv_rows.append([
                        format_datum(w.datum), w.klant_naam, w.locatie or '',
                        'Thuisadres', bestemming, str(w.km),
                        'Waarneming huisartspraktijk',
                    ])
                totaal = sum(w.km for w in km_rows)
                csv_rows.append(['', '', '', '', 'TOTAAL', str(totaal), ''])
                csv_data = generate_csv(headers, csv_rows)
                ui.download(
                    csv_data.encode('utf-8-sig'),
                    f'km_logboek_{jaar_select.value}.csv')

            ui.button('Km-logboek', icon='directions_car',
                      on_click=export_km_logboek).props('outline size=sm')

        # Bulk action toolbar (hidden when nothing selected)
        bulk_bar = ui.row().classes('w-full items-center gap-4')
        bulk_bar.set_visibility(False)
        with bulk_bar:
            bulk_label = ui.label('')

            async def ga_naar_factuur():
                selected = table_ref['ref'].selected
                if not selected:
                    ui.notify('Selecteer eerst werkdagen', type='warning')
                    return
                ids = [r['id'] for r in selected]
                app.storage.user['selected_werkdagen'] = ids
                ui.navigate.to('/facturen')

            ui.button(
                'Maak factuur van selectie', icon='receipt',
                on_click=ga_naar_factuur,
            ).props('color=primary')

            async def verwijder_selectie():
                selected = table_ref['ref'].selected
                if not selected:
                    return
                ids = [r['id'] for r in selected]

                async def confirm_bulk_delete():
                    deleted = 0
                    skipped = 0
                    for wid in ids:
                        try:
                            await delete_werkdag(DB_PATH, werkdag_id=wid)
                            deleted += 1
                        except ValueError:
                            skipped += 1
                    dlg.close()
                    if deleted:
                        ui.notify(f'{deleted} werkdag(en) verwijderd', type='positive')
                    if skipped:
                        ui.notify(
                            f'{skipped} werkdag(en) overgeslagen (gefactureerd/betaald)',
                            type='warning',
                        )
                    await refresh_table()

                with ui.dialog() as dlg, ui.card():
                    ui.label(f'{len(ids)} werkdag(en) verwijderen?')
                    with ui.row():
                        ui.button('Annuleren', on_click=dlg.close).props('flat')
                        ui.button('Ja, verwijderen',
                                  on_click=confirm_bulk_delete) \
                            .props('color=negative')
                dlg.open()

            ui.button(
                'Verwijder selectie', icon='delete',
                on_click=verwijder_selectie,
            ).props('color=negative outline')

        def update_bulk_bar():
            tbl = table_ref['ref']
            selected = tbl.selected if tbl else []
            n = len(selected) if selected else 0
            if n > 0:
                bulk_bar.set_visibility(True)
                bulk_label.text = f'{n} werkdag(en) geselecteerd'
            else:
                bulk_bar.set_visibility(False)

        # Table
        _trunc = 'max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
        columns = [
            {'name': 'datum', 'label': 'Datum', 'field': 'datum', 'sortable': True,
             'align': 'left', 'style': 'width:90px'},
            {'name': 'klant', 'label': 'Klant', 'field': 'klant_naam', 'sortable': True,
             'align': 'left', 'style': _trunc},
            {'name': 'code', 'label': 'Code', 'field': 'code', 'align': 'left',
             'style': 'max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'},
            {'name': 'uren', 'label': 'Uren', 'field': 'uren', 'sortable': True,
             'align': 'right', 'style': 'width:50px'},
            {'name': 'km', 'label': 'Km', 'field': 'km', 'align': 'right',
             'style': 'width:40px'},
            {'name': 'tarief', 'label': 'Tarief', 'field': 'tarief_fmt', 'align': 'right',
             'style': 'width:70px'},
            {'name': 'totaal', 'label': 'Totaal', 'field': 'totaal_fmt', 'align': 'right',
             'style': 'width:75px'},
            {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'center',
             'style': 'width:85px'},
            {'name': 'factuur', 'label': 'Factuur', 'field': 'factuurnummer', 'align': 'left',
             'style': 'width:85px'},
            {'name': 'actions', 'label': '', 'field': 'actions', 'align': 'center',
             'style': 'width:70px'},
        ]

        table = ui.table(
            columns=columns, rows=[], row_key='id',
            selection='multiple',
            pagination={'rowsPerPage': 25, 'sortBy': 'datum', 'descending': True,
                        'rowsPerPageOptions': [10, 20, 50, 0]},
        ).classes('w-full')
        table_ref['ref'] = table

        table.add_slot('body-cell-datum', '''
            <q-td :props="props">{{ props.row.datum_fmt }}</q-td>
        ''')

        table.add_slot('body-cell-status', '''
            <q-td :props="props">
                <q-badge :color="props.row.status === 'betaald' ? 'positive' :
                                  props.row.status === 'gefactureerd' ? 'primary' : 'grey'"
                         :label="props.row.status" />
            </q-td>
        ''')

        table.add_slot('no-data', '''
            <q-tr><q-td colspan="100%" class="text-center q-pa-lg text-grey">
                Geen werkdagen gevonden.
            </q-td></q-tr>
        ''')

        table.add_slot('body-cell-actions', '''
            <q-td :props="props">
                <q-btn icon="edit" flat dense round size="sm"
                    @click="() => $parent.$emit('edit', props.row)"
                    title="Bewerken" />
                <q-btn icon="delete" flat dense round size="sm" color="negative"
                    @click="() => $parent.$emit('delete', props.row)"
                    title="Verwijderen" />
            </q-td>
        ''')

        # Summary row
        summary_container['ref'] = ui.row().classes('w-full justify-end gap-8 q-mt-sm')

        table.on('selection', lambda _: update_bulk_bar())

        async def refresh_table():
            year = jaar_select.value
            month = maand_select.value if maand_select.value != 0 else None
            klant_id = klant_sel.value if klant_sel.value != 0 else None

            all_werkdagen = await get_werkdagen(
                DB_PATH, jaar=year, maand=month,
            )

            # Update klant dropdown with customers that have werkdagen
            seen = {}
            for w in all_werkdagen:
                if w.klant_id not in seen:
                    seen[w.klant_id] = w.klant_naam
            new_options = {0: 'Alle'} | dict(
                sorted(seen.items(), key=lambda x: x[1])
            )
            klant_sel.options = new_options
            if klant_id and klant_id not in new_options:
                klant_sel.set_value(0)
                klant_id = None
            klant_sel.update()

            status_filter = status_sel.value or None
            werkdagen = [
                w for w in all_werkdagen
                if (klant_id is None or w.klant_id == klant_id)
                and (status_filter is None or w.status == status_filter)
            ]

            rows = []
            totaal_uren = 0
            totaal_km = 0
            totaal_bedrag = 0

            for w in werkdagen:
                bedrag = w.uren * w.tarief + w.km * w.km_tarief
                rows.append({
                    'id': w.id,
                    'datum': w.datum,
                    'klant_naam': w.klant_naam,
                    'klant_id': w.klant_id,
                    'code': w.code,
                    'uren': w.uren,
                    'km': w.km,
                    'tarief_fmt': format_euro(w.tarief),
                    'totaal_fmt': format_euro(bedrag),
                    'status': w.status,
                    'factuurnummer': w.factuurnummer or '',
                })
                totaal_uren += w.uren
                totaal_km += w.km
                totaal_bedrag += bedrag

            table.rows = rows
            table.selected.clear()
            table.update()
            update_bulk_bar()

            s = summary_container['ref']
            s.clear()
            with s:
                ui.label(f'Totaal: {len(rows)} werkdagen').classes('text-body2')
                ui.label(f'Uren: {totaal_uren:.1f}').classes('text-body2')
                ui.label(f'Km: {totaal_km:.0f}').classes('text-body2')
                ui.label(f'Bedrag: {format_euro(totaal_bedrag)}') \
                    .classes('text-body1 text-weight-bold')

        # Event handlers
        async def on_edit(e):
            row = e.args
            werkdagen = await get_werkdagen(DB_PATH, jaar=jaar_select.value)
            werkdag = next((w for w in werkdagen if w.id == row['id']), None)
            if werkdag:
                await open_werkdag_dialog(
                    on_save=refresh_table, werkdag=werkdag,
                )

        async def on_delete(e):
            row = e.args
            with ui.dialog() as dlg, ui.card():
                ui.label(f"Werkdag {row['datum']} verwijderen?")
                ui.label(f"{row['datum']} — {row.get('klant_naam', '')} — "
                         f"{row.get('uren', 0)} uur — "
                         f"{row.get('totaal_fmt', '')}").classes('text-grey')
                with ui.row():
                    ui.button('Annuleren', on_click=dlg.close).props('flat')
                    ui.button('Ja, verwijderen',
                              on_click=lambda: confirm_delete(row['id'], dlg)) \
                        .props('color=negative')
            dlg.open()

        async def confirm_delete(werkdag_id, dlg):
            await delete_werkdag(DB_PATH, werkdag_id=werkdag_id)
            dlg.close()
            ui.notify('Werkdag verwijderd', type='positive')
            await refresh_table()

        table.on('edit', on_edit)
        table.on('delete', on_delete)

        # Filter change handlers
        jaar_select.on_value_change(lambda _: refresh_table())
        maand_select.on_value_change(lambda _: refresh_table())
        klant_sel.on_value_change(lambda _: refresh_table())
        status_sel.on_value_change(lambda _: refresh_table())

        # Initial load
        await refresh_table()
