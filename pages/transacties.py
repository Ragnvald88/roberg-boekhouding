"""Transacties pagina — unified inbox for bank + cash movements.

Combines the old /bank (CSV import + positives categorisation +
factuur-match) and the /kosten transactie-tabel (debit categorisation +
bon koppelen + cash entries + privé) into a single decision surface.
"""
import asyncio
import inspect
from datetime import date, datetime
from itertools import groupby
from pathlib import Path

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import (
    format_euro, format_datum, KOSTEN_CATEGORIEEN, BANK_CATEGORIEEN,
)
from components.shared_ui import year_options, date_input
from components.transacties_helpers import (
    tegenpartij_color, initials,
)
from components.transacties_dialog import (
    _open_detail_dialog, save_upload_for_uitgave, _copy_and_link_pdf,
)
from database import (
    DB_PATH, get_transacties_view, get_categorie_suggestions,
    find_factuur_matches, set_banktx_categorie, update_uitgave,
    add_uitgave, ensure_uitgave_for_banktx,
    YearLockedError, add_banktransacties, get_imported_csv_bestanden,
    apply_factuur_matches, get_db_ctx,
    delete_banktransacties, delete_uitgave,
    mark_banktx_genegeerd,
    get_uitgaven, get_fiscale_params,
    find_banktx_matches_for_pdf,
)
from import_.rabobank_csv import parse_rabobank_csv


# Per-row category options — positives get income-side cats; debits/cash
# get expense-side cats. Injected server-side as props.row.cat_options.
POSITIVE_CAT_OPTIONS = ['', 'Omzet', 'Prive', 'Belasting', 'AOV']
DEBIT_CAT_OPTIONS = [''] + KOSTEN_CATEGORIEEN

LEVENSDUUR_OPTIES = {3: '3 jaar', 4: '4 jaar', 5: '5 jaar'}


async def open_add_uitgave_dialog(
    prefill: dict | None = None,
    on_saved=None,
    refresh=None,
    repr_aftrek_pct: int = 80,
):
    """Dialog to add a new manual (cash) uitgave, optionally pre-filled
    from an archief-import or pre-linked to a bank_tx.

    Extracted from pages/kosten.py during the consolidation. ``refresh``
    is the caller's list-refresh function; called after each successful
    save. ``on_saved`` is an optional separate callback (used by Task 18's
    archief-import dialog to chain "next item" flow).

    Routes auto-link through ``ensure_uitgave_for_banktx`` when
    ``prefill['bank_tx_id']`` is present (M1 polish — idempotent).
    """
    upload_file = {}

    with ui.dialog() as dialog, \
            ui.card().classes('w-full max-w-lg q-pa-md'):
        ui.label('Uitgave toevoegen').classes('text-h6 q-mb-md')

        input_datum = date_input(
            'Datum',
            value=prefill.get('datum', date.today().isoformat())
            if prefill else date.today().isoformat(),
        )

        input_categorie = ui.select(
            KOSTEN_CATEGORIEEN, label='Categorie',
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

        # Investering section
        input_investering = ui.checkbox(
            'Dit is een investering', value=False)

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

        # Representatie note (80%-aftrekbaar, 20% bijtelling)
        bijtelling_pct = 100 - repr_aftrek_pct
        representatie_note = ui.label(
            f'{repr_aftrek_pct}% aftrekbaar, {bijtelling_pct}% bijtelling'
        ).classes('text-caption text-orange')
        representatie_note.set_visibility(False)

        def on_investering_change():
            investering_velden.set_visibility(input_investering.value)

        input_investering.on(
            'update:model-value', lambda: on_investering_change())

        def on_categorie_change():
            representatie_note.set_visibility(
                input_categorie.value == 'Representatie')

        input_categorie.on(
            'update:model-value', lambda: on_categorie_change())

        # PDF upload / prefilled PDF
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

            # Duplicate detection: same datum + cat + bedrag already exists?
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
                pass
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

            # Route auto-link through ensure_uitgave_for_banktx (M1).
            bank_tx_id = prefill.get('bank_tx_id') if prefill else None

            try:
                if bank_tx_id is not None:
                    uitgave_id = await ensure_uitgave_for_banktx(
                        DB_PATH, bank_tx_id=bank_tx_id,
                        datum=kwargs.get('datum'),
                        categorie=kwargs.get('categorie', ''),
                        omschrijving=kwargs.get('omschrijving', ''))
                    update_kwargs = {
                        k: v for k, v in kwargs.items()
                        if k not in ('datum', 'categorie',
                                      'omschrijving', 'bedrag')}
                    if update_kwargs:
                        await update_uitgave(
                            DB_PATH, uitgave_id=uitgave_id, **update_kwargs)
                else:
                    uitgave_id = await add_uitgave(DB_PATH, **kwargs)

                # PDF: from prefill path OR from upload widget.
                if prefill and prefill.get('pdf_path'):
                    await _copy_and_link_pdf(
                        uitgave_id, Path(prefill['pdf_path']))
                elif upload_file.get('event'):
                    await save_upload_for_uitgave(
                        uitgave_id, upload_file['event'])

                ui.notify('Uitgave opgeslagen', type='positive')
                if refresh is not None:
                    await refresh()

                if and_new:
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


async def open_import_dialog(
    default_jaar: int,
    refresh,
    jaren_opts,
    repr_aftrek_pct: int = 80,
):
    """Archief-PDF importeer dialog. Scans the financieel-archief per jaar,
    groups PDFs by categorie, and offers per-file Import links that open
    open_add_uitgave_dialog with prefilled datum/categorie/pdf_path/bank_tx_id.

    Extracted from pages/kosten.py during the consolidation.
    """
    from import_.expense_utils import scan_archive

    with ui.dialog() as import_dialog, \
            ui.card().classes('w-full q-pa-lg').style('max-width: 800px'):
        ui.label('Uitgaven importeren').classes('text-h5 q-mb-md')

        import_jaar = {'value': default_jaar}
        list_container = {'ref': None}

        async def load_archive():
            """Scan archive and render file list."""
            container = list_container['ref']
            if not container:
                return
            container.clear()

            jaar = import_jaar['value']

            # Existing pdf_pad values for dedup detection
            existing_uitgaven = await get_uitgaven(DB_PATH, jaar=jaar)
            existing_filenames = set()
            for u in existing_uitgaven:
                if u.pdf_pad:
                    existing_filenames.add(Path(u.pdf_pad).name)

            # P2-2: scan_archive hits SynologyDrive — move it off-thread.
            items = await asyncio.to_thread(
                scan_archive, jaar, existing_filenames)
            if not items:
                with container:
                    ui.label(
                        f'Geen uitgaven gevonden in archief voor {jaar}'
                    ).classes('text-grey q-pa-md')
                return

            imported_count = sum(
                1 for i in items if i['already_imported'])

            # Pre-compute bank-tx match hints for unmatched items (one async
            # pass; subsequent rendering is sync).
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

                # Group by categorie
                items_sorted = sorted(
                    items, key=lambda x: x['categorie'])
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
                                            refresh=refresh,
                                            repr_aftrek_pct=repr_aftrek_pct,
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
                                        ui.label(
                                            f'↔ {top_match[3]} · '
                                            f'{format_datum(top_match[1])} · '
                                            f'{format_euro(top_match[2])}'
                                        ).classes(
                                            'text-caption text-primary')

        # Year selector
        import_jaar_select = ui.select(
            {j: str(j) for j in jaren_opts},
            label='Jaar', value=import_jaar['value'],
        ).classes('w-32')

        async def on_import_jaar_change():
            import_jaar['value'] = import_jaar_select.value
            await load_archive()

        import_jaar_select.on(
            'update:model-value', lambda: on_import_jaar_change())

        # File list
        with ui.scroll_area().classes('w-full').style(
                'max-height: 60vh'):
            list_container['ref'] = ui.column().classes('w-full')

        # Footer
        with ui.row().classes('w-full justify-end q-mt-md'):
            ui.button(
                'Sluiten', on_click=import_dialog.close
            ).props('flat')

        await load_archive()

    async def on_import_close():
        if refresh:
            await refresh()

    import_dialog.on('hide', on_import_close)
    import_dialog.open()


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

    fp = await get_fiscale_params(DB_PATH, jaar=datetime.now().year)
    repr_aftrek_pct = int(fp.repr_aftrek_pct) if fp else 80

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
    # P2-9: re-entrancy guard. NiceGUI upload fires per-file; if a user
    # double-clicks or drops multiple CSVs, the second handler can start
    # while the first is still archiving / inserting. This would double-
    # import and race the dedup check.
    csv_upload_busy = {'flag': False}

    async def handle_csv_upload(e):
        """Parse uploaded Rabobank CSV, archive, insert, trigger match."""
        if csv_upload_busy['flag']:
            ui.notify(
                'Even wachten — vorige CSV-upload is nog bezig.',
                type='warning')
            return
        csv_upload_busy['flag'] = True
        try:
            await _do_csv_upload(e)
        finally:
            csv_upload_busy['flag'] = False

    async def _do_csv_upload(e):
        content = await e.file.read()
        filename = e.file.name
        try:
            transacties = parse_rabobank_csv(content)
        except ValueError as exc:
            ui.notify(f'Fout bij parsing: {exc}', type='negative')
            return
        except Exception as exc:  # P2-9: belt-and-suspenders
            ui.notify(f'Onverwachte fout bij CSV-lezen: {exc}',
                       type='negative')
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
        if count == 0:
            ui.notify(
                f"Geen nieuwe transacties — CSV '{filename}' bevatte "
                f"alleen al geïmporteerde rijen.",
                type='info', timeout=5000)
        else:
            ui.notify(
                f'{count} transacties geïmporteerd uit {filename}',
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

            # Contante uitgave — manual cash entry
            ui.button('+ Contante uitgave', icon='add',
                       on_click=lambda: open_add_uitgave_dialog(
                           refresh=refresh,
                           repr_aftrek_pct=repr_aftrek_pct)) \
                .props('color=primary dense')

            # CSV upload — Rabobank CSV → banktransacties + factuur-match preview
            ui.upload(
                label='Importeer CSV',
                on_upload=lambda e: asyncio.create_task(handle_csv_upload(e)),
                auto_upload=True,
            ).props('accept=".csv" flat color=primary').classes('w-44')

            # Archief-PDFs importeren — scan financieel-archief, import PDFs
            ui.button('Archief-PDFs importeren', icon='folder_open',
                       on_click=lambda: open_import_dialog(
                           default_jaar=filter_jaar['value'],
                           refresh=refresh,
                           jaren_opts=year_options(),
                           repr_aftrek_pct=repr_aftrek_pct)) \
                .props('flat color=secondary dense')

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
                placeholder=(
                    'Zoek tegenpartij, omschrijving of bedrag'),
                value=filter_search['value']
            ).classes('w-64').props('clearable dense outlined')

            async def reset_filters():
                """P2-6: clear maand/status/categorie/type/search in one
                click. Jaar stays — users rarely want to drop that too."""
                maand_select.value = 0
                status_select.value = None
                categorie_select.value = ''
                type_select.value = None
                search_input.value = ''
                filter_maand['value'] = 0
                filter_status['value'] = None
                filter_categorie['value'] = None
                filter_type['value'] = None
                filter_search['value'] = ''
                await refresh()

            ui.button('Reset', icon='clear', on_click=reset_filters) \
                .props('flat dense color=grey-7')

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
                """Dialog → pick categorie → apply to all selected rows.

                P2-5: options respect the selection's sign. All debits →
                kostencats; all credits → income-side; mixed → warn and
                offer the intersection (empty category only).
                """
                selected = list(table_ref['table'].selected or [])
                has_debit = any((r.get('bedrag') or 0) < 0 for r in selected)
                has_credit = any((r.get('bedrag') or 0) >= 0
                                  for r in selected)
                if has_debit and not has_credit:
                    opts = DEBIT_CAT_OPTIONS
                elif has_credit and not has_debit:
                    opts = POSITIVE_CAT_OPTIONS
                else:
                    opts = ['']  # mixed — only blanking is safe
                with ui.dialog() as dlg, ui.card():
                    ui.label('Nieuwe categorie voor selectie') \
                        .classes('text-h6')
                    if has_debit and has_credit:
                        ui.label(
                            'Selectie bevat zowel uitgaven als '
                            'inkomsten — kies een aparte bulk-actie '
                            'per sign.') \
                            .classes('text-caption text-warning')
                    sel = ui.select(opts, label='Categorie') \
                        .classes('w-full')
                    with ui.row().classes(
                            'w-full justify-end gap-2 q-mt-md'):
                        ui.button('Annuleren', on_click=dlg.close) \
                            .props('flat')

                        async def apply_bulk_cat():
                            # A15: iterate the snapshot captured above so
                            # a stray click between iterations cannot widen
                            # the scope mid-loop. Mirrors bulk_negeren and
                            # bulk_delete.
                            n_ok, n_skip = 0, 0
                            for r in selected:
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
                """Flag each selected bank row as genegeerd=1 (privé).

                Skips rows that:
                - are manual (no id_bank)
                - are linked to a factuur (would silently desync the
                  factuur's matched state — DB guard raises ValueError)
                - belong to a definitief year (DB raises YearLockedError,
                  which is a ValueError subclass)
                """
                # Snapshot selection so a stray click between iterations
                # cannot widen the scope mid-loop.
                selected = list(table_ref['table'].selected or [])
                n_ok, n_skip = 0, 0
                for r in selected:
                    if r.get('id_bank') is None:
                        continue  # manual rows skipped silently
                    if r.get('koppeling_type') == 'factuur':
                        n_skip += 1
                        continue
                    try:
                        await mark_banktx_genegeerd(
                            DB_PATH, bank_tx_id=r['id_bank'],
                            genegeerd=1)
                        n_ok += 1
                    except ValueError:
                        # Catches YearLockedError + factuur-koppeling guard
                        # + missing-row + invalid-value. All map to "skip".
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

            async def _do_bulk_delete_now(rows_to_delete: list[dict]):
                """Actual delete loop — called only after user confirms.

                ``rows_to_delete`` is the snapshot captured when the
                confirm dialog was opened, so a spurious selection
                change after the confirm click cannot alter the scope.
                """
                n_ok, n_skip = 0, 0
                reverted_total = 0
                for r in rows_to_delete:
                    try:
                        if r.get('id_bank') is not None:
                            _n, reverted = await delete_banktransacties(
                                DB_PATH, transactie_ids=[r['id_bank']])
                            reverted_total += len(reverted)
                        elif r.get('id_uitgave') is not None:
                            await delete_uitgave(
                                DB_PATH, uitgave_id=r['id_uitgave'])
                        else:
                            continue
                        n_ok += 1
                    except YearLockedError:
                        n_skip += 1
                msg = f'{n_ok} verwijderd'
                if reverted_total:
                    msg += (f', {reverted_total} factuur/facturen '
                             'teruggezet naar verstuurd')
                if n_skip:
                    msg += f', {n_skip} overgeslagen (jaar afgesloten)'
                ui.notify(msg,
                           type='positive' if n_ok else 'warning')
                await refresh()

            async def bulk_delete():
                """P0-3: Pre-scan the selection and confirm any cascades
                (factuur-revert, uitgave-orphaning) before deleting."""
                selected = list(table_ref['table'].selected or [])
                if not selected:
                    return

                factuur_linked = [
                    r for r in selected
                    if r.get('id_bank') is not None
                    and r.get('koppeling_type') == 'factuur']
                uitgave_orphans = [
                    r for r in selected
                    if r.get('id_bank') is not None
                    and r.get('id_uitgave') is not None
                    and ((r.get('categorie') or '').strip()
                         or (r.get('pdf_pad') or '').strip())]

                with ui.dialog() as dlg, ui.card():
                    ui.label(
                        f'{len(selected)} rij(en) verwijderen?') \
                        .classes('text-h6')
                    if factuur_linked:
                        ui.label(
                            f'{len(factuur_linked)} bank-transactie(s) '
                            'zijn gekoppeld aan een factuur — die factuur '
                            'wordt teruggezet naar "verstuurd".') \
                            .classes('text-body2 text-warning q-mt-sm')
                    if uitgave_orphans:
                        ui.label(
                            f'{len(uitgave_orphans)} bank-transactie(s) '
                            'hebben een gekoppelde uitgave met categorie '
                            'of bon. De uitgave blijft bestaan als '
                            'contant-uitgave (ontkoppeld).') \
                            .classes('text-body2 text-warning q-mt-xs')
                    if not factuur_linked and not uitgave_orphans:
                        ui.label(
                            'Geen gekoppelde facturen of bonnen — '
                            'de rijen worden eenvoudig verwijderd.') \
                            .classes('text-caption text-grey q-mt-sm')
                    with ui.row().classes(
                            'w-full justify-end gap-2 q-mt-md'):
                        ui.button('Annuleren',
                                   on_click=dlg.close).props('flat')

                        async def confirm_delete():
                            dlg.close()
                            # Pass the captured selection so a late
                            # reselection can't silently broaden scope.
                            await _do_bulk_delete_now(selected)

                        ui.button('Ja, verwijderen',
                                   on_click=confirm_delete) \
                            .props('color=negative')
                dlg.open()

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
             'align': 'center', 'sortable': False},
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
                        <q-chip v-else color="warning" text-color="white" size="sm"
                                dense>Te categoriseren</q-chip>
                        <q-chip v-if="props.row.is_manual" color="grey-5"
                                text-color="white" size="sm" dense
                                style="margin-left:4px">contant</q-chip>
                    </q-td>
                    <q-td key="acties" :props="props">
                        <q-btn v-if="props.row.bedrag < 0" flat dense round
                               icon="attach_file" size="sm" color="primary"
                               title="Bon toevoegen"
                               @click="$parent.$emit('attach_pdf', props.row)" />
                        <q-btn v-if="props.row.bedrag < 0" flat dense round
                               icon="more_horiz" size="sm" color="grey-7"
                               title="Details bewerken"
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
