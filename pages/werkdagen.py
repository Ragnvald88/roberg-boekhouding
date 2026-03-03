"""Werkdagen pagina — uren/km registratie met tabel en formulier."""

from nicegui import app, ui
from components.layout import create_layout
from components.utils import format_euro
from components.werkdag_form import werkdag_form
from database import (
    get_werkdagen, get_klanten, delete_werkdag,
    get_werkdagen_ongefactureerd, DB_PATH,
)
from datetime import date

MAANDEN = {
    0: 'Alle', 1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'Mei', 6: 'Jun',
    7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Okt', 11: 'Nov', 12: 'Dec',
}

STATUS_COLORS = {
    'ongefactureerd': 'grey',
    'gefactureerd': 'blue',
    'betaald': 'green',
}


@ui.page('/werkdagen')
async def werkdagen_page():
    create_layout('Werkdagen', '/werkdagen')

    current_year = date.today().year
    klanten = await get_klanten(DB_PATH)
    klant_options = {0: 'Alle'} | {k.id: k.naam for k in klanten}

    # State
    year_filter = {'value': current_year}
    month_filter = {'value': 0}
    klant_filter = {'value': 0}
    selected_ids = {'value': set()}
    table_ref = {'ref': None}
    form_container = {'ref': None}
    summary_container = {'ref': None}

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        # Filter row
        with ui.row().classes('w-full items-center gap-4'):
            ui.label('Werkdagen').classes('text-h5') \
                .style('color: #0F172A; font-weight: 700')
        with ui.row().classes('w-full items-end gap-4'):
            jaar_select = ui.select(
                {y: str(y) for y in range(2023, current_year + 2)},
                value=current_year, label='Jaar',
            ).classes('w-32')

            maand_select = ui.select(
                MAANDEN, value=0, label='Maand',
            ).classes('w-32')

            klant_sel = ui.select(
                klant_options, value=0, label='Klant',
            ).classes('w-48')

            ui.space()

            ui.button(
                'Vernieuwen', icon='refresh',
                on_click=lambda: refresh_table()
            ).props('outline color=primary')

        # Table
        columns = [
            {'name': 'select', 'label': '', 'field': 'select', 'align': 'center'},
            {'name': 'datum', 'label': 'Datum', 'field': 'datum', 'sortable': True,
             'align': 'left'},
            {'name': 'klant', 'label': 'Klant', 'field': 'klant_naam', 'sortable': True,
             'align': 'left'},
            {'name': 'code', 'label': 'Code', 'field': 'code', 'align': 'left'},
            {'name': 'uren', 'label': 'Uren', 'field': 'uren', 'sortable': True,
             'align': 'right'},
            {'name': 'km', 'label': 'Km', 'field': 'km', 'align': 'right'},
            {'name': 'tarief', 'label': 'Tarief', 'field': 'tarief_fmt', 'align': 'right'},
            {'name': 'totaal', 'label': 'Totaal', 'field': 'totaal_fmt', 'align': 'right'},
            {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'center'},
            {'name': 'actions', 'label': '', 'field': 'actions', 'align': 'center'},
        ]

        table = ui.table(
            columns=columns, rows=[], row_key='id',
        ).classes('w-full')
        table_ref['ref'] = table

        # Custom cell rendering for status colors and action buttons
        table.add_slot('body-cell-status', '''
            <q-td :props="props">
                <q-badge :color="props.row.status === 'betaald' ? 'positive' :
                                  props.row.status === 'gefactureerd' ? 'primary' : 'grey'"
                         :label="props.row.status" />
            </q-td>
        ''')

        table.add_slot('body-cell-select', '''
            <q-td :props="props">
                <q-checkbox v-model="props.row.selected" dense
                    @update:model-value="() => $parent.$emit('select', props.row)" />
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
                    @click="() => $parent.$emit('edit', props.row)" />
                <q-btn icon="delete" flat dense round size="sm" color="negative"
                    @click="() => $parent.$emit('delete', props.row)" />
            </q-td>
        ''')

        # Summary row
        summary_container['ref'] = ui.row().classes('w-full justify-end gap-8 q-mt-sm')

        # Factuur button
        with ui.row().classes('w-full q-mt-md gap-4'):
            async def ga_naar_factuur():
                ids = list(selected_ids['value'])
                if not ids:
                    ui.notify('Selecteer eerst werkdagen', type='warning')
                    return
                app.storage.user['selected_werkdagen'] = ids
                ui.navigate.to('/facturen')

            factuur_btn = ui.button(
                'Maak factuur van selectie', icon='receipt',
                on_click=ga_naar_factuur,
            ).props('color=primary disabled')

        ui.separator().classes('q-my-lg')

        # Form container
        form_container['ref'] = ui.column().classes('w-full')

        async def load_form(werkdag=None):
            container = form_container['ref']
            container.clear()

            async def cancel_edit():
                await load_form()

            with container:
                await werkdag_form(
                    on_save=refresh_table,
                    werkdag=werkdag,
                    on_cancel=cancel_edit if werkdag else None,
                )

        async def refresh_table():
            year = jaar_select.value
            month = maand_select.value if maand_select.value != 0 else None
            klant_id = klant_sel.value if klant_sel.value != 0 else None

            # Fetch all werkdagen for year+month (without klant filter)
            # so we can update the klant dropdown with relevant customers
            all_werkdagen = await get_werkdagen(
                DB_PATH, jaar=year, maand=month,
            )

            # Update klant dropdown: only customers with werkdagen in this period
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

            # Filter by klant in Python (avoids second DB query)
            werkdagen = [
                w for w in all_werkdagen
                if klant_id is None or w.klant_id == klant_id
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
                    'selected': False,
                })
                totaal_uren += w.uren
                totaal_km += w.km
                totaal_bedrag += bedrag

            table.rows = rows
            table.update()

            # Update summary
            s = summary_container['ref']
            s.clear()
            with s:
                ui.label(f'Totaal: {len(rows)} werkdagen').classes('text-body2')
                ui.label(f'Uren: {totaal_uren:.1f}').classes('text-body2')
                ui.label(f'Km: {totaal_km:.0f}').classes('text-body2')
                ui.label(f'Bedrag: {format_euro(totaal_bedrag)}') \
                    .classes('text-body1 text-weight-bold')

            # Reload form (fresh)
            await load_form()

        # Event handlers
        async def on_edit(e):
            row = e.args
            werkdagen = await get_werkdagen(DB_PATH, jaar=jaar_select.value)
            werkdag = next((w for w in werkdagen if w.id == row['id']), None)
            if werkdag:
                await load_form(werkdag)

        async def on_delete(e):
            row = e.args
            with ui.dialog() as dialog, ui.card():
                ui.label(f"Werkdag {row['datum']} verwijderen?")
                with ui.row():
                    ui.button('Ja, verwijderen',
                              on_click=lambda: confirm_delete(row['id'], dialog)) \
                        .props('color=negative')
                    ui.button('Annuleren', on_click=dialog.close)
            dialog.open()

        async def confirm_delete(werkdag_id, dialog):
            await delete_werkdag(DB_PATH, werkdag_id=werkdag_id)
            dialog.close()
            ui.notify('Werkdag verwijderd', type='positive')
            await refresh_table()

        def on_select(e):
            row = e.args
            wid = row['id']
            if row.get('selected'):
                selected_ids['value'].add(wid)
            else:
                selected_ids['value'].discard(wid)
            if selected_ids['value']:
                factuur_btn.props(remove='disabled')
            else:
                factuur_btn.props('disabled')

        table.on('select', on_select)
        table.on('edit', on_edit)
        table.on('delete', on_delete)

        # Filter change handlers
        jaar_select.on_value_change(lambda _: refresh_table())
        maand_select.on_value_change(lambda _: refresh_table())
        klant_sel.on_value_change(lambda _: refresh_table())

        # Initial load
        await refresh_table()
