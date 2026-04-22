"""Bank pagina — Rabobank CSV import + categoriseren."""

import asyncio
import json
from datetime import datetime

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import format_euro, format_datum, generate_csv, BANK_CATEGORIEEN
from database import (
    get_banktransacties, get_imported_csv_bestanden,
    add_banktransacties,
    delete_banktransacties, find_factuur_matches, apply_factuur_matches,
    get_categorie_suggestions, get_uitgave_categorie_by_bank_tx,
    set_banktx_categorie, get_db_ctx, DB_PATH,
)
from components.shared_ui import year_options
from import_.rabobank_csv import parse_rabobank_csv

@ui.page('/bank')
async def bank_page():
    create_layout('Bank', '/bank')
    current_year = datetime.now().year
    selected_jaar = {'value': current_year}
    selected_maand = {'value': 0}  # 0 = alle maanden
    zoek_tekst = {'value': ''}

    table_ref = {'table': None}
    csv_list_container = {'ref': None}
    bulk_bar_ref = {'ref': None}
    bulk_label_ref = {'ref': None}
    cat_suggestions = {'map': {}}  # lowercase tegenpartij → category

    async def load_suggestions():
        cat_suggestions['map'] = await get_categorie_suggestions(DB_PATH)

    async def load_transacties() -> list[dict]:
        """Load transactions from DB, apply year/month filter."""
        transacties = await get_banktransacties(DB_PATH, jaar=selected_jaar['value'])

        if selected_maand['value'] > 0:
            maand_str = f"{selected_maand['value']:02d}"
            transacties = [t for t in transacties if t.datum[5:7] == maand_str]

        if zoek_tekst['value']:
            q = zoek_tekst['value'].lower()
            transacties = [t for t in transacties
                           if q in t.tegenpartij.lower() or q in t.omschrijving.lower()]

        # For debit rows, the authoritative categorie lives on the linked
        # uitgave (post-Kosten-rework). Fetch the override map once.
        debit_cat_map = await get_uitgave_categorie_by_bank_tx(DB_PATH)

        rows = []
        for t in transacties:
            # Debits display the linked-uitgave categorie (unified source);
            # positives keep their own banktransacties.categorie.
            displayed_cat = (debit_cat_map.get(t.id, '')
                             if t.bedrag < 0 else t.categorie)

            # Status uses displayed_cat as the sole driver for the
            # uncategorised branches.
            if t.koppeling_type and t.koppeling_id:
                status = 'gekoppeld'
            elif displayed_cat:
                status = 'gecategoriseerd'
            else:
                status = 'niet-gekoppeld'

            # Apply suggestion for uncategorised rows with known counterparty.
            # Uses displayed_cat so debits already-categorised on /kosten
            # don't show a stale suggestion chip.
            suggested = ''
            if not displayed_cat and t.tegenpartij:
                suggested = cat_suggestions['map'].get(t.tegenpartij.lower(), '')

            rows.append({
                'id': t.id,
                'datum': t.datum,
                'datum_fmt': format_datum(t.datum),
                'bedrag': t.bedrag,
                'bedrag_fmt': format_euro(t.bedrag),
                'tegenpartij': t.tegenpartij,
                'omschrijving': t.omschrijving[:80] + ('...' if len(t.omschrijving) > 80 else ''),
                'omschrijving_full': t.omschrijving,
                'categorie': displayed_cat,
                'suggested_categorie': suggested,
                'koppeling': f"{t.koppeling_type} #{t.koppeling_id}" if t.koppeling_type else '',
                'status': status,
                'csv_bestand': t.csv_bestand,
            })
        return rows

    def update_bulk_bar():
        selected = table_ref['table'].selected if table_ref['table'] else []
        n = len(selected) if selected else 0
        if bulk_bar_ref['ref']:
            bulk_bar_ref['ref'].set_visibility(n > 0)
        if bulk_label_ref['ref']:
            bulk_label_ref['ref'].text = f'{n} transacties geselecteerd'

    async def refresh_table():
        """Reload data and update the table."""
        await load_suggestions()
        rows = await load_transacties()
        if table_ref['table']:
            table_ref['table'].rows = rows
            table_ref['table'].selected.clear()
            table_ref['table'].update()
        update_bulk_bar()

    async def refresh_csv_list():
        """Reload the list of imported CSV files."""
        if csv_list_container['ref'] is None:
            return
        csv_list_container['ref'].clear()
        transacties = await get_banktransacties(DB_PATH, jaar=selected_jaar['value'])
        csv_files = sorted(set(t.csv_bestand for t in transacties if t.csv_bestand))
        with csv_list_container['ref']:
            if not csv_files:
                ui.label('Nog geen CSV-bestanden geimporteerd.').classes('text-grey')
            else:
                for csv_file in csv_files:
                    count = sum(1 for t in transacties if t.csv_bestand == csv_file)
                    ui.label(f"{csv_file} ({count} transacties)").classes('text-sm')

    async def handle_upload(e):
        """Handle CSV file upload: parse, archive, insert."""
        content = await e.file.read()
        filename = e.file.name

        try:
            transacties = parse_rabobank_csv(content)
        except ValueError as exc:
            ui.notify(f"Fout bij parsing: {exc}", type='negative')
            return

        if not transacties:
            ui.notify("Geen transacties gevonden in CSV.", type='warning')
            return

        # Check for duplicate CSV import
        bestaande_csvs = await get_imported_csv_bestanden(DB_PATH)
        if any(csv.endswith(f'_{filename}') for csv in bestaande_csvs):
            ui.notify(f"CSV '{filename}' is al eerder geimporteerd", type='warning')
            return

        # Archive CSV to data/bank_csv/
        csv_dir = DB_PATH.parent / "bank_csv"
        csv_dir.mkdir(parents=True, exist_ok=True)
        archive_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        archive_path = csv_dir / archive_name
        await asyncio.to_thread(archive_path.write_bytes, content)

        # Insert into database
        count = await add_banktransacties(DB_PATH, transacties, csv_bestand=archive_name)

        ui.notify(f"{count} transacties geimporteerd uit {filename}", type='positive')

        # Find potential matches and present preview dialog — do NOT auto-apply.
        # Ambiguous (low-confidence) matches require explicit user confirmation
        # to prevent silent wrong-invoice-paid.
        proposals = await find_factuur_matches(DB_PATH)
        await refresh_table()
        await refresh_csv_list()
        if proposals:
            await _show_match_preview_dialog(proposals, count, refresh_table)

    async def _show_match_preview_dialog(proposals, imported_count, on_applied):
        """Present match proposals to the user; apply only ticked rows."""
        rows = await _build_match_preview_rows(proposals)
        n_low = sum(1 for r in rows if r['confidence'] == 'low')

        with ui.dialog() as dialog, ui.card().classes('w-full').style('max-width: 900px'):
            ui.label(
                f'{imported_count} transacties geimporteerd - '
                f'{len(proposals)} mogelijke koppelingen gevonden'
            ).classes('text-h6')
            subtitle = ('Vink aan welke koppelingen je wilt toepassen. '
                        'Dubbelzinnige matches moet je zelf controleren.')
            if n_low:
                subtitle += f' ({n_low} dubbelzinnig)'
            ui.label(subtitle).classes('text-body2 q-mb-sm text-grey-8')

            columns = [
                {'name': 'confidence_icon', 'label': '', 'field': 'confidence_icon',
                 'align': 'center'},
                {'name': 'factuur', 'label': 'Factuur', 'field': 'factuur',
                 'align': 'left'},
                {'name': 'factuur_bedrag', 'label': 'Bedrag', 'field': 'factuur_bedrag',
                 'align': 'right'},
                {'name': 'bank', 'label': 'Bank tegenpartij', 'field': 'bank',
                 'align': 'left'},
                {'name': 'bank_datum', 'label': 'Bank datum', 'field': 'bank_datum',
                 'align': 'left'},
                {'name': 'bank_bedrag', 'label': 'Bank bedrag', 'field': 'bank_bedrag',
                 'align': 'right'},
                {'name': 'delta', 'label': 'Verschil', 'field': 'delta',
                 'align': 'right'},
            ]
            preview_table = ui.table(
                columns=columns, rows=rows, row_key='id',
                selection='multiple',
            ).props('flat bordered dense').classes('w-full')
            # Pre-select only high-confidence proposals. Low-confidence rows
            # require explicit user action.
            preview_table.selected = [r for r in rows if r['confidence'] == 'high']

            async def apply_selected():
                chosen_ids = {r['id'] for r in preview_table.selected}
                # MatchProposal objects are indexed by row['id'] (enumerate index).
                chosen = [p for idx, p in enumerate(proposals) if idx in chosen_ids]
                if not chosen:
                    ui.notify('Geen koppelingen geselecteerd', type='warning')
                    return
                applied = await apply_factuur_matches(DB_PATH, chosen)
                nummers = ', '.join(p.factuur_nummer for p in chosen)
                ui.notify(
                    f'{applied} facturen als betaald gemarkeerd: {nummers}',
                    type='positive')
                dialog.close()
                await on_applied()

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')
                ui.button('Geselecteerde toepassen', on_click=apply_selected) \
                    .props('color=primary')
        dialog.open()

    async def _build_match_preview_rows(proposals):
        """Enrich proposals with display data for the preview table."""
        rows = []
        async with get_db_ctx(DB_PATH) as conn:
            for idx, p in enumerate(proposals):
                f_cur = await conn.execute(
                    "SELECT nummer, totaal_bedrag FROM facturen WHERE id = ?",
                    (p.factuur_id,))
                f_row = await f_cur.fetchone()
                b_cur = await conn.execute(
                    "SELECT tegenpartij, bedrag, datum FROM banktransacties "
                    "WHERE id = ?", (p.bank_id,))
                b_row = await b_cur.fetchone()
                if not f_row or not b_row:
                    continue
                icon = '!' if p.confidence == 'low' else 'OK'
                rows.append({
                    'id': idx,  # row key, not DB id
                    'confidence': p.confidence,
                    'confidence_icon': icon,
                    'factuur': f_row['nummer'],
                    'factuur_bedrag': format_euro(f_row['totaal_bedrag']),
                    'bank': b_row['tegenpartij'] or '',
                    'bank_datum': format_datum(b_row['datum']),
                    'bank_bedrag': format_euro(b_row['bedrag']),
                    'delta': format_euro(p.delta),
                })
        return rows

    async def handle_categorie_change(row_id: int, new_cat: str):
        """Update category for a bank transaction.

        Debits route into uitgaven.categorie (unified with /kosten);
        positives stay on banktransacties.categorie.
        """
        try:
            await set_banktx_categorie(
                DB_PATH, bank_tx_id=row_id, categorie=new_cat)
        except ValueError as e:
            ui.notify(str(e), type='negative')
            return
        ui.notify('Categorie bijgewerkt', type='positive')
        await refresh_table()

    async def handle_jaar_change(new_jaar):
        selected_jaar['value'] = new_jaar
        await refresh_table()
        await refresh_csv_list()

    async def handle_maand_change(new_maand):
        selected_maand['value'] = new_maand
        await refresh_table()

    async def on_delete_transactie(e):
        row = e.args
        with ui.dialog() as dialog, ui.card():
            ui.label('Transactie verwijderen?').classes('text-h6')
            ui.label(f"{row['datum']} — {row['tegenpartij']} — "
                     f"{row['bedrag_fmt']}").classes('text-grey')
            if row.get('koppeling'):
                ui.label(
                    'Gekoppelde factuur wordt teruggezet naar verstuurd.'
                ).classes('text-caption text-warning q-mt-sm')
            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')

                async def do_delete():
                    _count, reverted = await delete_banktransacties(
                        DB_PATH, transactie_ids=[row['id']])
                    dialog.close()
                    ui.notify('Transactie verwijderd', type='positive')
                    if reverted:
                        ui.notify(
                            f'{len(reverted)} factuur/facturen teruggezet '
                            f'naar verstuurd', type='info')
                    await refresh_table()

                ui.button('Verwijderen', on_click=do_delete) \
                    .props('color=negative')
        dialog.open()

    async def on_bulk_delete():
        selected = table_ref['table'].selected if table_ref['table'] else []
        ids = [r['id'] for r in selected]
        if not ids:
            return
        n_linked = sum(1 for r in selected if r.get('koppeling'))
        with ui.dialog() as dialog, ui.card():
            ui.label(f'{len(ids)} transacties verwijderen?').classes('text-h6')
            if n_linked:
                ui.label(
                    f'{n_linked} gekoppelde facturen worden teruggezet '
                    f'naar verstuurd.'
                ).classes('text-caption text-warning q-mt-sm')
            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')

                async def do_bulk():
                    _count, reverted = await delete_banktransacties(
                        DB_PATH, transactie_ids=ids)
                    dialog.close()
                    ui.notify(f'{len(ids)} transacties verwijderd',
                              type='positive')
                    if reverted:
                        ui.notify(
                            f'{len(reverted)} factuur/facturen teruggezet '
                            f'naar verstuurd', type='info')
                    await refresh_table()
                    await refresh_csv_list()

                ui.button('Verwijderen', on_click=do_bulk) \
                    .props('color=negative')
        dialog.open()
    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        # Header row: title + primary action
        with ui.row().classes('w-full items-center'):
            page_title('Bank')
            ui.space()
            # CSV upload button
            ui.upload(
                label='Importeer CSV',
                on_upload=handle_upload,
                auto_upload=True,
            ).props('accept=".csv" flat color=primary').classes('w-44')

        # Filter bar
        with ui.element('div').classes('page-toolbar w-full'):
            # Year selector
            jaren = year_options(descending=False)
            ui.select(
                label='Jaar',
                options=jaren,
                value=current_year,
                on_change=lambda e: handle_jaar_change(e.value),
            ).classes('w-28')

            # Month selector
            nl_maanden = {
                0: 'Alle maanden', 1: 'Januari', 2: 'Februari', 3: 'Maart',
                4: 'April', 5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Augustus',
                9: 'September', 10: 'Oktober', 11: 'November', 12: 'December',
            }
            ui.select(
                label='Maand',
                options=nl_maanden,
                value=0,
                on_change=lambda e: handle_maand_change(e.value),
            ).classes('w-36')

            # Search filter
            async def handle_zoek(new_val):
                zoek_tekst['value'] = new_val or ''
                await refresh_table()

            ui.input(label='Zoeken', placeholder='Tegenpartij / omschrijving',
                     on_change=lambda e: handle_zoek(e.value)
                     ).props('clearable').classes('w-52')

            ui.space()

            # CSV export
            async def export_csv_bank():
                rows_data = await load_transacties()
                headers = ['Datum', 'Bedrag', 'Tegenpartij', 'Omschrijving',
                           'Categorie', 'Koppeling']
                rows_out = [[r['datum'], r['bedrag'], r['tegenpartij'],
                             r['omschrijving_full'], r['categorie'], r['koppeling']]
                            for r in rows_data]
                csv_str = generate_csv(headers, rows_out)
                ui.download.content(
                    csv_str.encode('utf-8-sig'),
                    f'bank_{selected_jaar["value"]}.csv')

            ui.button(icon='download',
                      on_click=export_csv_bank) \
                .props('flat round color=secondary size=sm') \
                .tooltip('Exporteer CSV')

        # Bulk action toolbar
        bulk_bar = ui.row().classes('w-full items-center gap-4')
        bulk_bar.set_visibility(False)
        bulk_bar_ref['ref'] = bulk_bar
        with bulk_bar:
            bulk_label = ui.label('')
            bulk_label_ref['ref'] = bulk_label
            ui.button('Verwijder selectie', icon='delete',
                      on_click=lambda: on_bulk_delete()) \
                .props('color=negative outline')

        # Color legend
        with ui.row().classes('gap-4 items-center q-mb-sm'):
            for bg_class, label in [
                ('bg-teal-1', 'Gekoppeld aan factuur'),
                ('bg-amber-1', 'Gecategoriseerd'),
                ('bg-red-1', 'Niet gekoppeld'),
            ]:
                with ui.row().classes('items-center gap-1'):
                    ui.element('div').classes(f'{bg_class} rounded-sm') \
                        .style('width: 14px; height: 14px')
                    ui.label(label).classes('text-caption text-grey-7')

        # Transactions table
        columns = [
            {'name': 'datum', 'label': 'Datum', 'field': 'datum', 'sortable': True,
             'align': 'left'},
            {'name': 'bedrag_fmt', 'label': 'Bedrag', 'field': 'bedrag',
             'sortable': True, 'align': 'right'},
            {'name': 'tegenpartij', 'label': 'Tegenpartij', 'field': 'tegenpartij',
             'sortable': True, 'align': 'left'},
            {'name': 'omschrijving', 'label': 'Omschrijving', 'field': 'omschrijving',
             'align': 'left'},
            {'name': 'categorie', 'label': 'Categorie', 'field': 'categorie',
             'sortable': True, 'align': 'left'},
            {'name': 'koppeling', 'label': 'Koppeling', 'field': 'koppeling',
             'align': 'left'},
            {'name': 'actions', 'label': '', 'field': 'actions', 'align': 'center'},
        ]

        try:
            await load_suggestions()
            initial_rows = await load_transacties()
        except Exception as exc:
            initial_rows = []
            ui.notify(f'Fout bij laden transacties: {exc}', type='negative')

        table = ui.table(
            columns=columns,
            rows=initial_rows,
            row_key='id',
            selection='multiple',
            pagination={'rowsPerPage': 25, 'sortBy': 'datum', 'descending': True,
                        'rowsPerPageOptions': [10, 20, 50, 0]},
        ).classes('w-full')
        table_ref['table'] = table

        # Custom cell rendering for bedrag color, categorie dropdown, actions
        table.add_slot('body', r"""
            <q-tr :props="props"
                   :class="{
                       'bg-teal-1': props.row.status === 'gekoppeld',
                       'bg-amber-1': props.row.status === 'gecategoriseerd',
                       'bg-red-1': props.row.status === 'niet-gekoppeld'
                   }">
                <q-td auto-width>
                    <q-checkbox v-model="props.selected" dense />
                </q-td>
                <q-td key="datum" :props="props">{{ props.row.datum_fmt }}</q-td>
                <q-td key="bedrag_fmt" :props="props"
                       :class="props.row.bedrag >= 0 ? 'text-teal-8 text-bold' : 'text-red-8 text-bold'"
                       style="text-align: right">
                    {{ props.row.bedrag_fmt }}
                </q-td>
                <q-td key="tegenpartij" :props="props">{{ props.row.tegenpartij }}</q-td>
                <q-td key="omschrijving" :props="props">
                    <span :title="props.row.omschrijving_full">{{ props.row.omschrijving }}</span>
                </q-td>
                <q-td key="categorie" :props="props">
                    <div style="display:flex; align-items:center; gap:4px">
                        <q-select
                            v-model="props.row.categorie"
                            :options='""" + json.dumps(BANK_CATEGORIEEN) + r"""'
                            dense outlined
                            emit-value map-options
                            @update:model-value="(val) => $parent.$emit('cat_change', {id: props.row.id, cat: val})"
                            style="min-width: 160px"
                        />
                        <q-btn v-if="props.row.suggested_categorie && !props.row.categorie"
                            icon="auto_fix_high" flat dense round size="xs" color="primary"
                            :title="'Toepassen: ' + props.row.suggested_categorie"
                            @click="() => { props.row.categorie = props.row.suggested_categorie; $parent.$emit('cat_change', {id: props.row.id, cat: props.row.suggested_categorie}) }"
                        />
                    </div>
                </q-td>
                <q-td key="koppeling" :props="props">{{ props.row.koppeling }}</q-td>
                <q-td key="actions" :props="props">
                    <q-btn icon="delete" flat dense round size="sm" color="negative"
                        @click="() => $parent.$emit('deletetransactie', props.row)"
                        title="Verwijderen" />
                </q-td>
            </q-tr>
        """)

        table.add_slot('no-data', '''
            <q-tr><q-td colspan="100%" class="text-center q-pa-lg text-grey">
                Geen transacties gevonden.
            </q-td></q-tr>
        ''')

        table.on('cat_change', lambda e: handle_categorie_change(e.args['id'], e.args['cat']))
        table.on('selection', lambda _: update_bulk_bar())
        table.on('deletetransactie', on_delete_transactie)

        # Imported CSV files section
        ui.separator().classes('q-my-md')
        ui.label('Geimporteerde CSV-bestanden').classes('text-subtitle1') \
            .style('color: #0F172A; font-weight: 600')

        csv_container = ui.column().classes('w-full')
        csv_list_container['ref'] = csv_container
        await refresh_csv_list()
