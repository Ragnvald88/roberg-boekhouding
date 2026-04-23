"""Transacties pagina — unified inbox for bank + cash movements.

Combines the old /bank (CSV import + positives categorisation +
factuur-match) and the /kosten transactie-tabel (debit categorisation +
bon koppelen + cash entries + privé) into a single decision surface.
"""
import asyncio
from datetime import datetime

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import (
    format_euro, format_datum, KOSTEN_CATEGORIEEN, BANK_CATEGORIEEN,
)
from components.shared_ui import year_options
from components.kosten_helpers import (
    tegenpartij_color, initials,
)
from components.transacties_dialog import _open_detail_dialog
from database import (
    DB_PATH, get_transacties_view, get_categorie_suggestions,
    find_factuur_matches, set_banktx_categorie, update_uitgave,
    YearLockedError, add_banktransacties, get_imported_csv_bestanden,
    apply_factuur_matches, get_db_ctx,
    delete_banktransacties, delete_uitgave,
    mark_banktx_genegeerd,
)
from import_.rabobank_csv import parse_rabobank_csv


# Per-row category options — positives get income-side cats; debits/cash
# get expense-side cats. Injected server-side as props.row.cat_options.
POSITIVE_CAT_OPTIONS = ['', 'Omzet', 'Prive', 'Belasting', 'AOV']
DEBIT_CAT_OPTIONS = [''] + KOSTEN_CATEGORIEEN


@ui.page('/transacties')
async def transacties_page(jaar: int | None = None,
                             categorie: str | None = None,
                             status: str | None = None,
                             search: str | None = None,
                             maand: int | None = None,
                             type: str | None = None):
    """Transacties inbox — scaffold (Task 12).

    Table rendering / dialogs / CSV upload / bulk actions are wired in
    Tasks 13-19. This scaffold provides the header + filter bar +
    query-param plumbing.
    """
    create_layout('Transacties', '/transacties')
    current_year = datetime.now().year

    # Filter refs — populated from query-params on mount, mutated by
    # the filter-bar widgets, read by refresh().
    filter_jaar = {'value': jaar or current_year}
    filter_maand = {'value': maand or 0}       # 0 = alle maanden
    filter_status = {'value': status or None}  # None = alle
    filter_categorie = {'value': categorie or None}
    filter_type = {'value': type or None}      # None | 'bank' | 'contant'
    filter_search = {'value': search or ''}

    table_ref = {'table': None}
    match_btn_ref = {'button': None}
    bulk_bar_ref = {'ref': None}
    bulk_label_ref = {'ref': None}
    cat_suggestions = {'map': {}}

    async def _load_rows() -> list[dict]:
        rows = await get_transacties_view(
            DB_PATH,
            jaar=filter_jaar['value'],
            maand=filter_maand['value'] or None,
            status=filter_status['value'],
            categorie=filter_categorie['value'],
            type=filter_type['value'],
            search=filter_search['value'] or None,
            include_genegeerd=(filter_status['value'] == 'prive_verborgen'),
        )

        out: list[dict] = []
        for r in rows:
            display_name = r.tegenpartij or r.omschrijving or '(onbekend)'
            cat_opts = (POSITIVE_CAT_OPTIONS if r.bedrag >= 0
                        else DEBIT_CAT_OPTIONS)
            suggested = ''
            if not r.categorie and r.tegenpartij:
                suggested = cat_suggestions['map'].get(
                    r.tegenpartij.lower(), '')
            row_key = (f'b{r.id_bank}' if r.id_bank is not None
                        else f'u{r.id_uitgave}')
            out.append({
                'row_key': row_key,
                'source': r.source,
                'id_bank': r.id_bank,
                'id_uitgave': r.id_uitgave,
                'datum': r.datum,
                'datum_fmt': format_datum(r.datum),
                'tegenpartij': display_name,
                'omschrijving': r.omschrijving,
                'categorie': r.categorie,
                'suggested_categorie': suggested,
                'cat_options': cat_opts,
                'bedrag': r.bedrag,
                'bedrag_fmt': format_euro(r.bedrag),
                'pdf_pad': r.pdf_pad,
                'koppeling_type': r.koppeling_type,
                'koppeling_id': r.koppeling_id,
                'status': r.status,
                'is_manual': r.is_manual,
                'initials': initials(display_name),
                'color': tegenpartij_color(display_name),
            })
        return out

    async def _refresh_suggestions():
        cat_suggestions['map'] = await get_categorie_suggestions(DB_PATH)

    async def _refresh_match_count():
        """Update the [Matches controleren (N)] header button label."""
        if match_btn_ref['button'] is None:
            return
        n = len(await find_factuur_matches(DB_PATH))
        btn = match_btn_ref['button']
        btn.set_visibility(n > 0)
        btn.text = f'Matches controleren ({n})'

    async def refresh():
        await _refresh_suggestions()
        await _refresh_match_count()
        rows = await _load_rows()
        if table_ref['table'] is not None:
            table_ref['table'].rows = rows
            table_ref['table'].selected.clear()
            table_ref['table'].update()

    # -------------------------------------------------------------- #
    # CSV upload + factuur-match preview                             #
    # -------------------------------------------------------------- #
    async def handle_csv_upload(e):
        """Parse uploaded Rabobank CSV, archive, insert, trigger match."""
        content = await e.file.read()
        filename = e.file.name
        try:
            transacties = parse_rabobank_csv(content)
        except ValueError as exc:
            ui.notify(f'Fout bij parsing: {exc}', type='negative')
            return
        if not transacties:
            ui.notify('Geen transacties gevonden in CSV.', type='warning')
            return

        # Dedup — don't import the same filename twice
        bestaande_csvs = await get_imported_csv_bestanden(DB_PATH)
        if any(csv.endswith(f'_{filename}') for csv in bestaande_csvs):
            ui.notify(f"CSV '{filename}' is al eerder geïmporteerd",
                       type='warning')
            return

        # Archive CSV to data/bank_csv/ (best-effort, blocking IO wrapped)
        csv_dir = DB_PATH.parent / 'bank_csv'
        csv_dir.mkdir(parents=True, exist_ok=True)
        archive_name = (f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
                         f'{filename}')
        archive_path = csv_dir / archive_name
        await asyncio.to_thread(archive_path.write_bytes, content)

        count = await add_banktransacties(DB_PATH, transacties,
                                            csv_bestand=archive_name)
        ui.notify(f'{count} transacties geïmporteerd uit {filename}',
                   type='positive')

        # Find unmatched factuur proposals and offer preview
        proposals = await find_factuur_matches(DB_PATH)
        await refresh()
        if proposals:
            await _show_match_preview_dialog(proposals, count)

    async def _open_match_dialog_manually():
        """Header button action — open match dialog if proposals exist."""
        proposals = await find_factuur_matches(DB_PATH)
        if not proposals:
            ui.notify('Geen openstaande matches.', type='info')
            return
        await _show_match_preview_dialog(proposals, imported_count=0)

    async def _build_match_preview_rows(proposals):
        """Shape MatchProposal objects for the preview table."""
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
                rows.append({
                    'id': idx,
                    'confidence': p.confidence,
                    'confidence_icon': ('!' if p.confidence == 'low'
                                         else 'OK'),
                    'factuur': f_row['nummer'],
                    'factuur_bedrag': format_euro(f_row['totaal_bedrag']),
                    'bank': b_row['tegenpartij'] or '',
                    'bank_datum': format_datum(b_row['datum']),
                    'bank_bedrag': format_euro(b_row['bedrag']),
                    'delta': format_euro(p.delta),
                })
        return rows

    async def _show_match_preview_dialog(proposals, imported_count: int):
        """Show match-review dialog; pre-tick high-confidence, apply on OK."""
        rows = await _build_match_preview_rows(proposals)
        n_low = sum(1 for r in rows if r['confidence'] == 'low')

        with ui.dialog() as dialog, \
                ui.card().classes('w-full').style('max-width:900px'):
            title = (f'{imported_count} transacties geïmporteerd - '
                      f'{len(proposals)} mogelijke koppelingen gevonden'
                      if imported_count
                      else f'{len(proposals)} openstaande koppelingen')
            ui.label(title).classes('text-h6')
            subtitle = ('Vink aan welke koppelingen je wilt toepassen. '
                         'Dubbelzinnige matches moet je zelf controleren.')
            if n_low:
                subtitle += f' ({n_low} dubbelzinnig)'
            ui.label(subtitle).classes('text-body2 q-mb-sm text-grey-8')

            columns = [
                {'name': 'confidence_icon', 'label': '',
                 'field': 'confidence_icon', 'align': 'center'},
                {'name': 'factuur', 'label': 'Factuur', 'field': 'factuur',
                 'align': 'left'},
                {'name': 'factuur_bedrag', 'label': 'Bedrag',
                 'field': 'factuur_bedrag', 'align': 'right'},
                {'name': 'bank', 'label': 'Bank tegenpartij',
                 'field': 'bank', 'align': 'left'},
                {'name': 'bank_datum', 'label': 'Bank datum',
                 'field': 'bank_datum', 'align': 'left'},
                {'name': 'bank_bedrag', 'label': 'Bank bedrag',
                 'field': 'bank_bedrag', 'align': 'right'},
                {'name': 'delta', 'label': 'Verschil',
                 'field': 'delta', 'align': 'right'},
            ]
            preview_table = ui.table(
                columns=columns, rows=rows, row_key='id',
                selection='multiple',
            ).props('flat bordered dense').classes('w-full')
            # Pre-tick high-confidence; low-confidence needs explicit user click.
            preview_table.selected = [
                r for r in rows if r['confidence'] == 'high']

            async def apply_selected():
                chosen_ids = {r['id'] for r in preview_table.selected}
                chosen = [p for idx, p in enumerate(proposals)
                           if idx in chosen_ids]
                if not chosen:
                    ui.notify('Geen koppelingen geselecteerd',
                               type='warning')
                    return
                applied = await apply_factuur_matches(DB_PATH, chosen)
                nummers = ', '.join(p.factuur_nummer for p in chosen)
                ui.notify(
                    f'{applied} facturen als betaald gemarkeerd: {nummers}',
                    type='positive')
                dialog.close()
                await refresh()

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')
                ui.button('Geselecteerde toepassen',
                           on_click=apply_selected).props('color=primary')
        dialog.open()

    # -------------------------------------------------------------- #
    # Layout                                                         #
    # -------------------------------------------------------------- #
    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):
        # Header
        with ui.row().classes('w-full items-center'):
            page_title('Transacties')
            ui.space()

            # CSV upload — Rabobank CSV → banktransacties + factuur-match preview
            ui.upload(
                label='Importeer CSV',
                on_upload=lambda e: asyncio.create_task(handle_csv_upload(e)),
                auto_upload=True,
            ).props('accept=".csv" flat color=primary').classes('w-44')

            match_btn_ref['button'] = ui.button(
                'Matches controleren (0)',
                icon='link',
                on_click=lambda: asyncio.create_task(_open_match_dialog_manually()))
            match_btn_ref['button'].props('flat color=primary dense')
            match_btn_ref['button'].set_visibility(False)

        # Filter bar — single row
        with ui.row().classes('w-full items-center gap-2'):
            jaar_select = ui.select(
                {j: str(j) for j in year_options()},
                label='Jaar', value=filter_jaar['value'],
            ).classes('w-28')

            maand_select = ui.select(
                {0: 'Alle maanden',
                 1: 'Januari', 2: 'Februari', 3: 'Maart', 4: 'April',
                 5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Augustus',
                 9: 'September', 10: 'Oktober', 11: 'November',
                 12: 'December'},
                label='Maand', value=filter_maand['value'],
            ).classes('w-36')

            status_select = ui.select(
                {None: 'Alle',
                 'ongecategoriseerd': 'Ongecategoriseerd',
                 'ontbreekt_bon': 'Bon ontbreekt',
                 'gekoppeld_factuur': 'Gekoppeld aan factuur',
                 'prive_verborgen': 'Privé-verborgen',
                 'compleet': 'Compleet'},
                label='Status', value=filter_status['value'],
            ).classes('w-48')

            cat_opts = {'': 'Alle categorieën'}
            for c in BANK_CATEGORIEEN:
                if c:
                    cat_opts[c] = c
            categorie_select = ui.select(
                cat_opts, label='Categorie',
                value=filter_categorie['value'] or '',
            ).classes('w-48')

            type_select = ui.select(
                {None: 'Alle', 'bank': 'Bank', 'contant': 'Contant'},
                label='Type', value=filter_type['value'],
            ).classes('w-32')

            search_input = ui.input(
                placeholder='Zoek tegenpartij / omschrijving',
                value=filter_search['value']
            ).classes('w-64').props('clearable dense outlined')

        async def on_filter_change():
            filter_jaar['value'] = jaar_select.value
            filter_maand['value'] = maand_select.value
            filter_status['value'] = status_select.value
            filter_categorie['value'] = categorie_select.value or None
            filter_type['value'] = type_select.value
            filter_search['value'] = search_input.value or ''
            await refresh()

        for w in (jaar_select, maand_select, status_select,
                   categorie_select, type_select):
            w.on('update:model-value',
                  lambda _=None: on_filter_change())
        search_input.on(
            'update:model-value',
            lambda _=None: on_filter_change())

        # Bulk bar — appears when 1+ rows selected
        bulk_bar = ui.row().classes('w-full items-center gap-2 q-py-sm') \
            .style('background:#0f172a;color:white;border-radius:8px;'
                    'padding:8px 16px')
        bulk_bar.set_visibility(False)
        bulk_bar_ref['ref'] = bulk_bar
        with bulk_bar:
            bulk_label_ref['ref'] = ui.label('')

            async def bulk_set_cat():
                """Dialog → pick categorie → apply to all selected rows."""
                with ui.dialog() as dlg, ui.card():
                    ui.label('Nieuwe categorie voor selectie') \
                        .classes('text-h6')
                    sel = ui.select(BANK_CATEGORIEEN, label='Categorie') \
                        .classes('w-full')
                    with ui.row().classes(
                            'w-full justify-end gap-2 q-mt-md'):
                        ui.button('Annuleren', on_click=dlg.close) \
                            .props('flat')

                        async def apply_bulk_cat():
                            n_ok, n_skip = 0, 0
                            for r in table_ref['table'].selected:
                                try:
                                    if r.get('id_bank') is not None:
                                        await set_banktx_categorie(
                                            DB_PATH,
                                            bank_tx_id=r['id_bank'],
                                            categorie=sel.value or '')
                                    elif r.get('id_uitgave') is not None:
                                        await update_uitgave(
                                            DB_PATH,
                                            uitgave_id=r['id_uitgave'],
                                            categorie=sel.value or '')
                                    else:
                                        continue
                                    n_ok += 1
                                except YearLockedError:
                                    n_skip += 1
                            dlg.close()
                            msg = f'{n_ok} bijgewerkt'
                            if n_skip:
                                msg += (f', {n_skip} overgeslagen '
                                          '(jaar afgesloten)')
                            ui.notify(
                                msg,
                                type='positive' if n_ok else 'warning')
                            await refresh()

                        ui.button('Toepassen', on_click=apply_bulk_cat) \
                            .props('color=primary')
                dlg.open()

            ui.button('Categorie wijzigen', icon='label',
                       on_click=bulk_set_cat) \
                .props('outline color=white size=sm')

            async def bulk_negeren():
                """Flag each selected bank row as genegeerd=1 (privé)."""
                n_ok, n_skip = 0, 0
                for r in table_ref['table'].selected:
                    if r.get('id_bank') is None:
                        continue  # manual rows skipped
                    try:
                        await mark_banktx_genegeerd(
                            DB_PATH, bank_tx_id=r['id_bank'],
                            genegeerd=1)
                        n_ok += 1
                    except YearLockedError:
                        n_skip += 1
                msg = f'{n_ok} rij(en) als privé gemarkeerd'
                if n_skip:
                    msg += f', {n_skip} overgeslagen'
                ui.notify(msg,
                           type='positive' if n_ok else 'warning')
                await refresh()

            ui.button('Markeer als privé', icon='visibility_off',
                       on_click=bulk_negeren) \
                .props('outline color=white size=sm')

            async def bulk_delete():
                """Delete each selected row (bank or manual)."""
                n_ok, n_skip = 0, 0
                for r in table_ref['table'].selected:
                    try:
                        if r.get('id_bank') is not None:
                            await delete_banktransacties(
                                DB_PATH, transactie_ids=[r['id_bank']])
                        elif r.get('id_uitgave') is not None:
                            await delete_uitgave(
                                DB_PATH, uitgave_id=r['id_uitgave'])
                        else:
                            continue
                        n_ok += 1
                    except YearLockedError:
                        n_skip += 1
                msg = f'{n_ok} verwijderd'
                if n_skip:
                    msg += f', {n_skip} overgeslagen'
                ui.notify(msg,
                           type='positive' if n_ok else 'warning')
                await refresh()

            ui.button('Verwijderen', icon='delete',
                       on_click=bulk_delete) \
                .props('outline color=white size=sm')

        def _update_bulk_bar():
            """Show/hide bulk bar and update count label based on selection."""
            n = (len(table_ref['table'].selected)
                  if table_ref['table'] else 0)
            if n > 0:
                bulk_bar.set_visibility(True)
                bulk_label_ref['ref'].text = f'{n} geselecteerd'
            else:
                bulk_bar.set_visibility(False)

        # Table skeleton — rows/slots wired in Task 13
        columns = [
            {'name': 'datum', 'label': 'Datum', 'field': 'datum_fmt',
             'align': 'left', 'sortable': True},
            {'name': 'tegenpartij', 'label': 'Tegenpartij / Omschrijving',
             'field': 'tegenpartij', 'align': 'left'},
            {'name': 'categorie', 'label': 'Categorie', 'field': 'categorie',
             'align': 'left'},
            {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
             'align': 'right', 'sortable': True},
            {'name': 'status_chip', 'label': 'Factuur/bon',
             'field': 'status', 'align': 'center'},
            {'name': 'acties', 'label': '', 'field': 'acties',
             'align': 'center'},
        ]

        with ui.card().classes('w-full'):
            table = ui.table(
                columns=columns, rows=[], row_key='row_key',
                selection='multiple',
                pagination={
                    'rowsPerPage': 25, 'sortBy': 'datum',
                    'descending': True,
                    'rowsPerPageOptions': [10, 20, 50, 0]},
            ).classes('w-full').props('flat')
            table_ref['table'] = table

            table.add_slot('no-data', '''
                <q-tr><q-td colspan="100%"
                            class="text-center q-pa-lg text-grey">
                  Geen transacties gevonden.
                </q-td></q-tr>
            ''')

            table.add_slot('body', r"""
                <q-tr :props="props"
                       :class="{
                           'bg-teal-1': props.row.status === 'gekoppeld_factuur',
                           'bg-amber-1': props.row.status === 'ontbreekt_bon',
                           'bg-red-1': props.row.status === 'ongecategoriseerd',
                           'bg-grey-3': props.row.status === 'prive_verborgen',
                       }">
                    <q-td auto-width>
                        <q-checkbox v-model="props.selected" dense />
                    </q-td>
                    <q-td key="datum" :props="props">{{ props.row.datum_fmt }}</q-td>
                    <q-td key="tegenpartij" :props="props">
                        <div class="row items-center q-gutter-sm"
                             style="width:100%;flex-wrap:nowrap;">
                            <div :style="`background:${props.row.color};
                                          color:white;
                                          width:30px;height:30px;
                                          border-radius:7px;
                                          display:grid;place-items:center;
                                          font-weight:700;font-size:11px;
                                          flex-shrink:0;`">
                                {{ props.row.initials }}
                            </div>
                            <div style="min-width:0;flex:1;">
                                <div style="font-weight:500;
                                             white-space:nowrap;
                                             overflow:hidden;
                                             text-overflow:ellipsis;"
                                     :title="props.row.tegenpartij">
                                    {{ props.row.tegenpartij }}
                                </div>
                                <div class="text-caption text-grey"
                                     v-if="props.row.omschrijving &&
                                            props.row.omschrijving !== props.row.tegenpartij"
                                     :title="props.row.omschrijving"
                                     style="white-space:nowrap;
                                             overflow:hidden;
                                             text-overflow:ellipsis;">
                                    {{ props.row.omschrijving }}
                                </div>
                            </div>
                        </div>
                    </q-td>
                    <q-td key="categorie" :props="props">
                        <div style="display:flex;align-items:center;gap:4px">
                            <q-select
                                :model-value="props.row.categorie"
                                :options="props.row.cat_options"
                                dense borderless emit-value map-options
                                placeholder="— kies —"
                                @update:model-value="val => $parent.$emit('set_cat',
                                                                          {row: props.row,
                                                                           cat: val})"
                                style="min-width:160px" />
                            <q-btn v-if="props.row.suggested_categorie && !props.row.categorie"
                                icon="auto_fix_high" flat dense round size="xs" color="primary"
                                :title="'Toepassen: ' + props.row.suggested_categorie"
                                @click="() => $parent.$emit('set_cat',
                                                             {row: props.row,
                                                              cat: props.row.suggested_categorie})" />
                        </div>
                    </q-td>
                    <q-td key="bedrag" :props="props"
                           :class="props.row.bedrag >= 0
                                    ? 'text-teal-8 text-bold'
                                    : 'text-red-8 text-bold'"
                           style="text-align:right;
                                  font-variant-numeric:tabular-nums">
                        {{ props.row.bedrag_fmt }}
                    </q-td>
                    <q-td key="status_chip" :props="props">
                        <q-chip v-if="props.row.status === 'compleet'"
                                color="positive" text-color="white" size="sm"
                                icon="check_circle" dense>Compleet</q-chip>
                        <q-chip v-else-if="props.row.status === 'ontbreekt_bon'"
                                color="warning" text-color="white" size="sm"
                                icon="warning" dense>Bon ontbreekt</q-chip>
                        <q-chip v-else-if="props.row.status === 'gekoppeld_factuur'"
                                color="info" text-color="white" size="sm"
                                icon="link" dense>Gekoppeld</q-chip>
                        <q-chip v-else-if="props.row.status === 'gecategoriseerd'"
                                color="grey-7" text-color="white" size="sm" dense>
                            {{ props.row.categorie }}
                        </q-chip>
                        <q-chip v-else-if="props.row.status === 'prive_verborgen'"
                                color="grey-5" text-color="white" size="sm"
                                icon="visibility_off" dense>Privé</q-chip>
                        <q-chip v-else color="negative" text-color="white" size="sm"
                                dense>Nieuw</q-chip>
                        <q-chip v-if="props.row.is_manual" color="grey-5"
                                text-color="white" size="sm" dense
                                style="margin-left:4px">contant</q-chip>
                    </q-td>
                    <q-td key="acties" :props="props">
                        <q-btn v-if="props.row.bedrag < 0" flat dense round
                               icon="attach_file" size="sm" color="primary"
                               title="Bon toevoegen"
                               @click="$parent.$emit('attach_pdf', props.row)" />
                        <q-btn flat dense round icon="more_horiz" size="sm"
                               color="grey-7"
                               @click="$parent.$emit('open_detail', props.row)" />
                        <q-btn flat dense round icon="delete" size="sm"
                               color="negative"
                               @click="$parent.$emit('delete_row', props.row)" />
                    </q-td>
                </q-tr>
            """)

        # -------------------------------------------------------------- #
        # Row handlers                                                   #
        # -------------------------------------------------------------- #
        async def _on_set_cat(args: dict):
            """Categorie change routed by sign.

            Bank rows (debit OR credit) → set_banktx_categorie (sign-aware
            inside — debits lazy-create uitgave; credits write to
            banktransacties.categorie). Manual rows → update_uitgave.
            Year-locked: YearLockedError surfaces via ui.notify.
            """
            row = args['row']
            cat = args['cat'] or ''
            try:
                if row['id_bank'] is not None:
                    await set_banktx_categorie(
                        DB_PATH, bank_tx_id=row['id_bank'], categorie=cat)
                else:
                    await update_uitgave(
                        DB_PATH, uitgave_id=row['id_uitgave'], categorie=cat)
                ui.notify(f'Categorie: {cat or "(leeggemaakt)"}',
                           type='positive')
                await refresh()
            except YearLockedError as e:
                ui.notify(str(e), type='negative')

        async def _open_detail(row: dict):
            await _open_detail_dialog(row, refresh, default_tab='detail')

        async def _open_factuur(row: dict):
            await _open_detail_dialog(row, refresh, default_tab='factuur')

        async def _on_delete_row(row: dict):
            """Delete a row — bank-tx (factuur-revert cascade) OR manual uitgave."""
            if row.get('id_bank') is not None:
                # Bank tx — may revert linked factuur
                with ui.dialog() as dialog, ui.card():
                    ui.label('Transactie verwijderen?').classes('text-h6')
                    ui.label(f"{row['datum_fmt']} — {row['tegenpartij']} — "
                              f"{row['bedrag_fmt']}").classes('text-grey')
                    if row.get('koppeling_type') == 'factuur':
                        ui.label(
                            'Gekoppelde factuur wordt teruggezet naar '
                            'verstuurd.'
                        ).classes('text-caption text-warning q-mt-sm')
                    with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                        ui.button('Annuleren',
                                   on_click=dialog.close).props('flat')

                        async def do_delete_bank():
                            try:
                                _n, reverted = await delete_banktransacties(
                                    DB_PATH, transactie_ids=[row['id_bank']])
                            except YearLockedError as e:
                                ui.notify(str(e), type='negative')
                                return
                            dialog.close()
                            ui.notify('Transactie verwijderd',
                                       type='positive')
                            if reverted:
                                ui.notify(
                                    f'{len(reverted)} factuur/facturen '
                                    f'teruggezet naar verstuurd',
                                    type='info')
                            await refresh()

                        ui.button('Verwijderen',
                                   on_click=do_delete_bank) \
                            .props('color=negative')
                dialog.open()
            elif row.get('id_uitgave') is not None:
                # Manual cash uitgave — straight delete
                with ui.dialog() as dialog, ui.card():
                    ui.label('Uitgave verwijderen?').classes('text-h6')
                    ui.label(f"{row['datum_fmt']} — "
                              f"{row.get('omschrijving') or row['tegenpartij']}"
                              f" — {row['bedrag_fmt']}") \
                        .classes('text-grey')
                    with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                        ui.button('Annuleren',
                                   on_click=dialog.close).props('flat')

                        async def do_delete_uitgave():
                            try:
                                await delete_uitgave(
                                    DB_PATH, uitgave_id=row['id_uitgave'])
                            except YearLockedError as e:
                                ui.notify(str(e), type='negative')
                                return
                            dialog.close()
                            ui.notify('Uitgave verwijderd',
                                       type='positive')
                            await refresh()

                        ui.button('Verwijderen',
                                   on_click=do_delete_uitgave) \
                            .props('color=negative')
                dialog.open()

        table.on('set_cat',
                  lambda e: asyncio.create_task(_on_set_cat(e.args)))
        table.on('open_detail',
                  lambda e: asyncio.create_task(_open_detail(e.args)))
        table.on('attach_pdf',
                  lambda e: asyncio.create_task(_open_factuur(e.args)))
        table.on('delete_row',
                  lambda e: asyncio.create_task(_on_delete_row(e.args)))
        table.on('selection', lambda _: _update_bulk_bar())

        # Initial load
        await refresh()
