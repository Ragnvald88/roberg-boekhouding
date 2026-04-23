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
    YearLockedError,
)


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
    # Layout                                                         #
    # -------------------------------------------------------------- #
    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):
        # Header
        with ui.row().classes('w-full items-center'):
            page_title('Transacties')
            ui.space()
            # Header action buttons — CSV upload / cash-entry / archief-
            # import / matches-controleren are wired in later tasks.
            match_btn_ref['button'] = ui.button(
                'Matches controleren (0)',
                icon='link',
                on_click=lambda: None)  # wired in Task 19
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

        table.on('set_cat',
                  lambda e: asyncio.create_task(_on_set_cat(e.args)))
        table.on('open_detail',
                  lambda e: asyncio.create_task(_open_detail(e.args)))
        table.on('attach_pdf',
                  lambda e: asyncio.create_task(_open_factuur(e.args)))
        # delete_row is emitted by the trash button but wired in Task 15

        # Initial load
        await refresh()
