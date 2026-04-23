"""Kosten pagina — transacties (bank + cash) + investeringen."""

import asyncio
import base64
import inspect
import json
import shutil
from datetime import date, datetime
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
from components.transacties_dialog import (
    save_upload_for_uitgave, _copy_and_link_pdf, _open_detail_dialog,
)
from database import (
    add_uitgave, delete_uitgave, get_uitgaven, update_uitgave,
    get_fiscale_params,
    ensure_uitgave_for_banktx, mark_banktx_genegeerd,
    get_kosten_view, get_kpi_kosten, find_pdf_matches_for_banktx,
    find_banktx_matches_for_pdf,
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
    kpi = await get_kpi_kosten(DB_PATH, jaar)

    def _card(label: str, value: str, sub: str | None = None,
              color: str = 'primary', icon: str | None = None,
              on_click=None):
        with ui.card().classes('flex-1 q-pa-md cursor-pointer' if on_click
                                else 'flex-1 q-pa-md') as c:
            if on_click:
                c.on('click', lambda _: on_click())
            with ui.row().classes('items-center gap-2'):
                if icon:
                    ui.icon(icon, color=color).classes('text-lg')
                ui.label(label) \
                    .classes('text-caption text-uppercase text-grey')
            ui.label(value) \
                .classes('text-h5 text-bold q-mt-xs') \
                .style('font-variant-numeric: tabular-nums')
            if sub:
                ui.label(sub).classes('text-caption text-grey')
        return c

    with container:
        _card(
            f'Totaal kosten {jaar}',
            format_euro(kpi.totaal),
            f"{len([m for m in kpi.monthly_totals if m>0])} actieve maanden")

        _card(
            'Te verwerken',
            str(kpi.ontbreekt_count),
            format_euro(kpi.ontbreekt_bedrag),
            color='warning', icon='warning',
            on_click=lambda: None)  # filter via status dropdown manually

        _card(
            f'Afschrijvingen {jaar}',
            format_euro(kpi.afschrijvingen_jaar),
            'Zie tab Investeringen',
            icon='trending_down')

        _card(
            f'Investeringen {jaar}',
            str(kpi.investeringen_count),
            format_euro(kpi.investeringen_bedrag),
            icon='inventory_2')


async def _laad_inbox(container, jaar, refresh):
    if container is None:
        return
    container.clear()
    rows = await get_kosten_view(DB_PATH, jaar=jaar)
    needs = [r for r in rows
             if r.status in ('ongecategoriseerd', 'ontbreekt_bon')]
    if not needs:
        return

    needs.sort(key=lambda r: r.datum, reverse=True)
    top4 = needs[:4]

    with container:
        with ui.card() \
                .classes('w-full q-pa-md') \
                .style('background:linear-gradient(135deg,#fff7ed,#ffffff);'
                        'border:1px solid #fed7aa'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('warning', color='warning').classes('text-2xl')
                with ui.column().classes('flex-1 gap-0'):
                    ui.label(
                        f'{len(needs)} transactie(s) hebben nog aandacht nodig') \
                        .classes('text-subtitle2 text-bold')
                    ui.label(
                        'Klik om te categoriseren of een bon toe te voegen.') \
                        .classes('text-caption text-grey')

            with ui.row().classes('w-full gap-2 q-mt-md'):
                for r in top4:
                    card = ui.card() \
                        .classes('q-pa-sm flex-1 cursor-pointer') \
                        .style('min-width:220px')
                    with card:
                        with ui.row().classes('w-full items-baseline'):
                            ui.label(
                                r.tegenpartij or r.omschrijving or '(—)') \
                                .classes('text-body2 text-bold')
                            ui.space()
                            ui.label(format_euro(r.bedrag)) \
                                .classes('text-body2 text-bold') \
                                .style('font-variant-numeric:tabular-nums')
                        ui.label(format_datum(r.datum)) \
                            .classes('text-caption text-grey')

                    async def _on_click(row=r):
                        row_dict = {
                            'id_bank': row.id_bank,
                            'id_uitgave': row.id_uitgave,
                            'datum': row.datum,
                            'bedrag': row.bedrag,
                            'tegenpartij': row.tegenpartij,
                            'omschrijving': row.omschrijving,
                            'categorie': row.categorie,
                            'pdf_pad': row.pdf_pad,
                            'is_manual': row.is_manual,
                            'iban': row.iban,
                        }
                        await _open_detail_dialog(row_dict, refresh)

                    card.on('click', lambda _=None, r=r:
                            asyncio.create_task(_on_click(r)))


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
         'align': 'left', 'sortable': True,
         'style': 'width: 110px; min-width: 110px',
         'headerStyle': 'width: 110px; min-width: 110px'},
        {'name': 'tegenpartij', 'label': 'Tegenpartij / Omschrijving',
         'field': 'tegenpartij', 'align': 'left'},
        {'name': 'categorie', 'label': 'Categorie', 'field': 'categorie',
         'align': 'left',
         'style': 'width: 180px; min-width: 180px; max-width: 180px',
         'headerStyle': 'width: 180px; min-width: 180px; max-width: 180px'},
        {'name': 'factuur', 'label': 'Factuur', 'field': 'factuur_status',
         'align': 'left',
         'style': 'width: 130px; min-width: 130px; max-width: 130px',
         'headerStyle': 'width: 130px; min-width: 130px; max-width: 130px'},
        {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
         'align': 'right', 'sortable': True,
         'style': 'width: 120px; min-width: 120px; max-width: 120px; '
                   'font-variant-numeric: tabular-nums',
         'headerStyle': 'width: 120px; min-width: 120px; max-width: 120px'},
        {'name': 'acties', 'label': '', 'field': 'acties',
         'align': 'center',
         'style': 'width: 90px; min-width: 90px; max-width: 90px',
         'headerStyle': 'width: 90px; min-width: 90px; max-width: 90px'},
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
        """Thin wrapper: routes the 'attach_pdf' row-action to the
        Detail dialog with the Factuur tab pre-selected."""
        await _open_detail_dialog(row, refresh, default_tab='factuur')

    async def _open_row_dialog(row):
        """Thin wrapper: routes the 'open_detail' row-action to the
        module-level detail dialog, forwarding the page's refresh fn."""
        await _open_detail_dialog(row, refresh, default_tab='detail')

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

            # ---------------- Bulk action bar ----------------
            # Appears when 1+ rows are selected; hidden otherwise.
            # Handlers close over ``tbl`` (for ``tbl.selected``) and
            # ``refresh`` so the page reflows after bulk ops.
            bulk_row = ui.row() \
                .classes('w-full items-center gap-2 q-py-sm') \
                .style('background:#0f172a;color:white;border-radius:8px;'
                        'padding:8px 16px')
            bulk_row.set_visibility(False)
            with bulk_row:
                bulk_label = ui.label('')

                async def bulk_set_cat():
                    with ui.dialog() as dlg, ui.card():
                        ui.label('Nieuwe categorie voor selectie') \
                            .classes('text-h6')
                        sel = ui.select(CATEGORIEEN, label='Categorie') \
                            .classes('w-full')
                        with ui.row() \
                                .classes('w-full justify-end gap-2 q-mt-md'):
                            ui.button('Annuleren', on_click=dlg.close) \
                                .props('flat')

                            async def apply():
                                n_ok, n_skip = 0, 0
                                for r in tbl.selected:
                                    # Skip synthetic month-divider rows
                                    # in per-maand view (no id_* keys).
                                    if r.get('__maand_header__'):
                                        continue
                                    id_bank = r.get('id_bank')
                                    id_uitgave = r.get('id_uitgave')
                                    try:
                                        if id_uitgave is None \
                                                and id_bank is not None:
                                            await ensure_uitgave_for_banktx(
                                                DB_PATH,
                                                bank_tx_id=id_bank,
                                                categorie=sel.value or '')
                                        elif id_uitgave is not None:
                                            await update_uitgave(
                                                DB_PATH,
                                                uitgave_id=id_uitgave,
                                                categorie=sel.value or '')
                                        else:
                                            # Neither id_bank nor id_uitgave —
                                            # nothing to update.
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

                            ui.button('Toepassen', on_click=apply) \
                                .props('color=primary')
                    dlg.open()

                ui.button('Categorie wijzigen', icon='label',
                          on_click=bulk_set_cat) \
                    .props('outline color=white size=sm')

                async def bulk_negeren():
                    n_ok, n_skip = 0, 0
                    for r in tbl.selected:
                        # Skip synthetic month-divider rows
                        # in per-maand view (no id_* keys).
                        if r.get('__maand_header__'):
                            continue
                        id_bank = r.get('id_bank')
                        if id_bank is None:
                            continue
                        try:
                            await mark_banktx_genegeerd(
                                DB_PATH, bank_tx_id=id_bank,
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
                    n_ok, n_skip = 0, 0
                    for r in tbl.selected:
                        # Skip synthetic month-divider rows
                        # in per-maand view (no id_* keys).
                        if r.get('__maand_header__'):
                            continue
                        id_uitgave = r.get('id_uitgave')
                        if id_uitgave is None:
                            continue
                        try:
                            await delete_uitgave(
                                DB_PATH, uitgave_id=id_uitgave)
                            n_ok += 1
                        except YearLockedError:
                            n_skip += 1
                    msg = f'{n_ok} uitgave(n) verwijderd'
                    if n_skip:
                        msg += f', {n_skip} overgeslagen'
                    ui.notify(msg,
                              type='positive' if n_ok else 'warning')
                    await refresh()

                ui.button('Verwijderen', icon='delete',
                          on_click=bulk_delete) \
                    .props('outline color=white size=sm')

            def update_bulk():
                n = len(tbl.selected)
                if n > 0:
                    bulk_row.set_visibility(True)
                    bulk_label.text = f'{n} geselecteerd'
                else:
                    bulk_row.set_visibility(False)

            tbl.on('selection', lambda _: update_bulk())

            tbl.add_slot('body-cell-datum', '''
                <q-td :props="props">{{ props.row.datum_fmt }}</q-td>
            ''')

            tbl.add_slot('body-cell-tegenpartij', '''
                <q-td :props="props">
                  <div class="row items-center q-gutter-sm"
                       style="width: 100%; flex-wrap: nowrap;">
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
                    <div style="min-width: 0; flex: 1;">
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
            ''')

            tbl.add_slot('body-cell-categorie', r"""
                <q-td :props="props"
                      :class="props.row.categorie ? '' : 'bg-orange-1'">
                  <q-select
                    :model-value="props.row.categorie"
                    :options='""" + json.dumps(CATEGORIEEN) + r"""'
                    dense borderless emit-value map-options
                    placeholder="— kies —"
                    @update:model-value="val => $parent.$emit('set_cat',
                                                              {row: props.row,
                                                               cat: val})"
                    style="min-width: 160px" />
                </q-td>
            """)

            tbl.add_slot('body-cell-factuur', '''
                <q-td :props="props">
                  <q-chip v-if="props.row.factuur_status === 'compleet'"
                          color="positive" text-color="white"
                          size="sm" icon="check_circle" dense>
                    Compleet
                  </q-chip>
                  <q-chip v-else-if="props.row.factuur_status === 'ontbreekt_bon'"
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
                       _open_row_dialog(e.args)))

            # ---------------- Per-maand view ----------------
            # Inserts synthetic divider rows between month groups, each
            # rendered via the ``top-row`` slot by matching the
            # ``__maand_header__`` flag. ``rows`` in the table are sorted
            # already (descending datum) by Quasar pagination, but we
            # honour the original ``table_rows`` order and let Quasar
            # re-sort if the user changes sort column.
            if view_mode == 'maand':
                tbl.add_slot('top-row', '''
                    <q-tr v-if="props.row.__maand_header__">
                      <q-td colspan="100%"
                            class="text-weight-medium text-grey"
                            style="background:#f1f5f9;letter-spacing:0.05em;
                                   text-transform:uppercase;font-size:11px;
                                   padding:8px 14px">
                        {{ props.row.__maand__ }}
                        <span style="float:right;font-variant-numeric:tabular-nums">
                          {{ props.row.__maand_total__ }}
                        </span>
                      </q-td>
                    </q-tr>
                ''')
                grouped: list[dict] = []
                current_month = None
                month_buf: list[dict] = []
                for tr in table_rows:
                    m = tr['datum'][:7]
                    if m != current_month:
                        if month_buf:
                            total = sum(x['bedrag'] for x in month_buf)
                            grouped.append({
                                '__maand_header__': True,
                                '__maand__': current_month,
                                '__maand_total__': format_euro(total),
                                'row_key': f'__hdr_{current_month}',
                                'datum': current_month + '-00',
                            })
                            grouped.extend(month_buf)
                            month_buf = []
                        current_month = m
                    month_buf.append(tr)
                if month_buf:
                    total = sum(x['bedrag'] for x in month_buf)
                    grouped.append({
                        '__maand_header__': True,
                        '__maand__': current_month,
                        '__maand_total__': format_euro(total),
                        'row_key': f'__hdr_{current_month}',
                        'datum': current_month + '-00',
                    })
                    grouped.extend(month_buf)
                tbl.rows = grouped
                tbl.update()


async def _laad_breakdown(container, jaar):
    if container is None:
        return
    container.clear()
    rows = await get_kosten_view(DB_PATH, jaar=jaar)
    totals: dict[str, float] = {}
    for r in rows:
        key = r.categorie or '(nog te categoriseren)'
        totals[key] = totals.get(key, 0.0) + r.bedrag
    if not totals:
        return
    sorted_totals = sorted(totals.items(), key=lambda kv: kv[1],
                           reverse=True)
    grand = sum(totals.values())

    with container:
        with ui.card().classes('w-full q-pa-md'):
            with ui.row().classes('w-full items-center'):
                ui.label(f'Kosten per categorie — {jaar}') \
                    .classes('text-subtitle1 text-bold')
                ui.space()
                ui.label(f'Totaal {format_euro(grand)}') \
                    .classes('text-caption text-grey')

            for name, amt in sorted_totals:
                pct = (amt / grand * 100) if grand else 0
                with ui.column().classes('w-full gap-0 q-my-xs'):
                    with ui.row().classes('w-full'):
                        ui.label(name).classes('text-body2')
                        ui.space()
                        ui.label(
                            f'{format_euro(amt)} · {pct:.1f}%') \
                            .classes('text-body2 text-bold') \
                            .style('font-variant-numeric:tabular-nums')
                    ui.linear_progress(value=pct / 100) \
                        .props('color=primary size=6px')


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

                # Pass through the prefill's bank_tx_id so Importeer can auto-link.
                # Route through ensure_uitgave_for_banktx (idempotent) when a bank_tx_id
                # is present — guards against duplicate-link races at migratie-28 level
                # and makes repeated-import a no-op instead of an IntegrityError.
                bank_tx_id = prefill.get('bank_tx_id') if prefill else None

                try:
                    if bank_tx_id is not None:
                        uitgave_id = await ensure_uitgave_for_banktx(
                            DB_PATH, bank_tx_id=bank_tx_id,
                            datum=kwargs.get('datum'),
                            categorie=kwargs.get('categorie', ''),
                            omschrijving=kwargs.get('omschrijving', ''))
                        # Apply remaining kwargs (investeringen fields, bedrag override) —
                        # ensure() only sets the basics + enforces bedrag = ABS(bank_tx.bedrag).
                        update_kwargs = {k: v for k, v in kwargs.items()
                                         if k not in ('datum', 'categorie', 'omschrijving',
                                                       'bedrag')}
                        if update_kwargs:
                            await update_uitgave(DB_PATH, uitgave_id=uitgave_id,
                                                  **update_kwargs)
                    else:
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
                        if inspect.iscoroutinefunction(on_saved):
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

                # Pre-compute bank-tx match hints for unmatched items
                # (one async pass; subsequent rendering is sync).
                match_map: dict[str, list] = {}
                match_tasks = [
                    (it['filename'],
                     find_banktx_matches_for_pdf(
                         DB_PATH, it['filename'], jaar))
                    for it in items if not it['already_imported']
                ]
                if match_tasks:
                    results = await asyncio.gather(
                        *(t[1] for t in match_tasks))
                    for (fname, _), res in zip(match_tasks, results):
                        match_map[fname] = res

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
                                        item_matches = match_map.get(
                                            item['filename'], [])
                                        top_match = (item_matches[0]
                                                     if item_matches else None)

                                        async def do_import(
                                            it=item, bank_match=top_match,
                                        ):
                                            prefill = {
                                                'datum': (
                                                    it['datum']
                                                    or (bank_match[1]
                                                        if bank_match
                                                        else date.today()
                                                        .isoformat())
                                                ),
                                                'categorie':
                                                    it['categorie'],
                                                'pdf_path':
                                                    str(it['path']),
                                            }
                                            if bank_match:
                                                prefill['bank_tx_id'] = (
                                                    bank_match[0])
                                            await open_add_uitgave_dialog(
                                                prefill=prefill,
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
                                        if top_match:
                                            # (bank_tx_id, datum, bedrag,
                                            #  tegenpartij)
                                            ui.label(
                                                f'↔ {top_match[3]} · '
                                                f'{format_datum(top_match[1])} · '
                                                f'{format_euro(top_match[2])}'
                                            ).classes(
                                                'text-caption text-primary')

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
                        'ontbreekt_bon': 'Ontbreekt',
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
