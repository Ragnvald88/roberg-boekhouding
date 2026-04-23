"""Detail / Factuur / Historie dialog for /transacties (and legacy /kosten).

Extracted from pages/kosten.py during the bank/kosten consolidation
(Phase 2 Task 11). Uses get_uitgave_by_id for bootstrap (M5 — avoids the
list-and-filter silent-None race). Historie tab uses get_transacties_view
filtered to bedrag < 0 (debit + manual scope).
"""
import asyncio
import base64
import shutil
from datetime import datetime
from pathlib import Path

from nicegui import ui

from components.utils import (
    format_euro, format_datum, KOSTEN_CATEGORIEEN as CATEGORIEEN,
)
from database import (
    DB_PATH, ensure_uitgave_for_banktx, update_uitgave, delete_uitgave,
    get_uitgave_by_id, get_transacties_view, get_uitgaven,
    find_pdf_matches_for_banktx, YearLockedError,
)

UITGAVEN_DIR = DB_PATH.parent / 'uitgaven'

LEVENSDUUR_OPTIES = {3: '3 jaar', 4: '4 jaar', 5: '5 jaar'}


# ---------------------------------------------------------------------------
# File helpers — shared between the add/edit dialogs and the Task-11 detail
# dialog. Module-level so the Detail/Factuur tab can use them without
# capturing closures from ``kosten_page``.
# ---------------------------------------------------------------------------
async def save_upload_for_uitgave(uitgave_id: int, upload_event):
    """Save an uploaded file and link it to an uitgave."""
    UITGAVEN_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(upload_event.file.name).name.replace(' ', '_')
    filename = f'uitgave_{uitgave_id}_{safe_name}'
    filepath = UITGAVEN_DIR / filename
    content = await upload_event.file.read()
    await asyncio.to_thread(filepath.write_bytes, content)
    await update_uitgave(DB_PATH, uitgave_id=uitgave_id,
                         pdf_pad=str(filepath))
    return filepath


async def _copy_and_link_pdf(uitgave_id: int, source_path: Path):
    """Copy a PDF from archive to data/uitgaven/ and link to uitgave."""
    UITGAVEN_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = source_path.name.replace(' ', '_')
    filename = f'uitgave_{uitgave_id}_{safe_name}'
    dest = UITGAVEN_DIR / filename
    await asyncio.to_thread(shutil.copy2, source_path, dest)
    await update_uitgave(DB_PATH, uitgave_id=uitgave_id, pdf_pad=str(dest))


# ---------------------------------------------------------------------------
# Detail dialog — Detail / Factuur / Historie tabs (Task 11).
# ---------------------------------------------------------------------------
async def _open_detail_dialog(row, refresh, default_tab: str = 'detail'):
    """Detail dialog with Detail / Factuur / Historie tabs.

    ``row`` is a dict from the kosten table's body — has ``id_bank``,
    ``id_uitgave``, ``datum``, ``bedrag``, ``categorie``, ``pdf_pad``,
    ``is_manual``, ``tegenpartij``, ``omschrijving`` etc. For bank-only
    rows (``id_uitgave is None``) we lazy-create the uitgave on open so
    downstream closures can capture the fresh id.
    """
    # Lazy-create uitgave for bank-only rows so all tabs have a target.
    try:
        if row.get('id_uitgave') is None and row.get('id_bank') is not None:
            uid = await ensure_uitgave_for_banktx(
                DB_PATH, bank_tx_id=row['id_bank'])
            row['id_uitgave'] = uid  # mutate so closures see the fresh id
    except YearLockedError as e:
        ui.notify(str(e), type='negative')
        return

    # Re-load fresh uitgave data via targeted fetch (M5 — avoids the
    # list-and-filter silent-None race when a tx is on a different year).
    u = (await get_uitgave_by_id(DB_PATH, row['id_uitgave'])
         if row.get('id_uitgave') is not None else None)
    if u is None and not row.get('is_manual'):
        ui.notify('Fout: uitgave niet gevonden na aanmaken', type='negative')
        return

    bank_linked = row.get('id_bank') is not None

    with ui.dialog() as dialog, ui.card() \
            .classes('w-full').style('max-width: 760px'):
        ui.label(f"Transactie — {row['tegenpartij']}") \
            .classes('text-h6 q-mb-sm')

        with ui.tabs() as tabs:
            t_detail = ui.tab('Detail', icon='edit')
            t_factuur = ui.tab('Factuur', icon='description')
            t_hist = ui.tab('Historie', icon='history')

        initial_tab = {
            'detail': t_detail,
            'factuur': t_factuur,
            'historie': t_hist,
        }.get(default_tab, t_detail)

        # Refs populated inside the Detail tab; read by opslaan() below.
        edit_bedrag = None
        edit_cat = None
        edit_omschr = None
        edit_inv = None
        edit_lv = None
        edit_rest = None
        edit_zak = None

        with ui.tab_panels(tabs, value=initial_tab).classes('w-full'):
            # ---------------- DETAIL ----------------
            with ui.tab_panel(t_detail):
                with ui.row().classes('items-baseline gap-3 q-mb-sm'):
                    ui.label(format_euro(row['bedrag'])) \
                        .classes('text-h5 text-bold')
                    ui.label(format_datum(row['datum'])) \
                        .classes('text-caption text-grey')

                if bank_linked:
                    ui.label(f"IBAN: {row.get('iban', '') or '—'}") \
                        .classes('text-caption text-grey')

                # bedrag: editable only for manual uitgaven — bank rows
                # stay locked to bank_tx.bedrag.
                if not bank_linked:
                    edit_bedrag = ui.number(
                        'Bedrag (€)', value=row['bedrag'],
                        format='%.2f', min=0.01, step=0.01) \
                        .classes('w-full')

                edit_cat = ui.select(
                    CATEGORIEEN, label='Categorie',
                    value=u.categorie if u else '').classes('w-full')

                edit_omschr = ui.textarea(
                    'Omschrijving / notitie',
                    value=(u.omschrijving if u
                           else row.get('omschrijving', ''))) \
                    .classes('w-full').props('autogrow')

                edit_inv = ui.checkbox(
                    'Dit is een investering',
                    value=bool(u.is_investering) if u else False)
                inv_box = ui.column().classes('pl-8 gap-2')
                inv_box.set_visibility(edit_inv.value)
                with inv_box:
                    with ui.row().classes('items-end gap-4'):
                        edit_lv = ui.select(
                            LEVENSDUUR_OPTIES, label='Levensduur',
                            value=(u.levensduur_jaren
                                   if u and u.levensduur_jaren else 5)) \
                            .classes('w-28')
                        edit_rest = ui.number(
                            'Restwaarde %',
                            value=(u.restwaarde_pct
                                   if u and u.restwaarde_pct else 10),
                            min=0, max=100).classes('w-28')
                        edit_zak = ui.number(
                            'Zakelijk %',
                            value=(u.zakelijk_pct
                                   if u and u.zakelijk_pct else 100),
                            min=0, max=100).classes('w-28')

                edit_inv.on('update:model-value',
                            lambda: inv_box.set_visibility(edit_inv.value))

                if bank_linked and u is not None:
                    async def ontkoppel():
                        try:
                            await update_uitgave(
                                DB_PATH, uitgave_id=u.id, bank_tx_id=None)
                        except YearLockedError as e:
                            ui.notify(str(e), type='negative')
                            return
                        ui.notify('Bank-transactie ontkoppeld',
                                  type='positive')
                        dialog.close()
                        await refresh()

                    ui.button('Ontkoppel bank-transactie', icon='link_off',
                              on_click=ontkoppel) \
                        .props('flat dense color=grey-7 size=sm')

            # ---------------- FACTUUR ----------------
            with ui.tab_panel(t_factuur):
                pdf_box = ui.column().classes('w-full')
                await _render_factuur_tab(
                    pdf_box, u, row, refresh, dialog)

            # ---------------- HISTORIE ----------------
            with ui.tab_panel(t_hist):
                hist_box = ui.column().classes('w-full')
                await _render_historie_tab(hist_box, row)

        # Footer
        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
            ui.button('Annuleren', on_click=dialog.close).props('flat')
            if u is not None:
                async def verwijder():
                    with ui.dialog() as confirm, ui.card():
                        ui.label('Uitgave verwijderen?').classes('text-h6')
                        ui.label(
                            f"{row['datum']} — "
                            f"{row.get('omschrijving') or row['tegenpartij']}"
                            f" — {format_euro(row['bedrag'])}") \
                            .classes('text-grey')
                        with ui.row().classes('w-full justify-end gap-2'):
                            ui.button('Annuleren',
                                      on_click=confirm.close).props('flat')

                            async def do_del():
                                try:
                                    await delete_uitgave(
                                        DB_PATH, uitgave_id=u.id)
                                except YearLockedError as e:
                                    ui.notify(str(e), type='negative')
                                    return
                                confirm.close()
                                dialog.close()
                                ui.notify('Uitgave verwijderd',
                                          type='positive')
                                await refresh()

                            ui.button('Verwijderen', on_click=do_del) \
                                .props('color=negative')
                    confirm.open()

                ui.button('Verwijder', icon='delete',
                          on_click=verwijder) \
                    .props('flat color=negative')

            async def opslaan():
                try:
                    kwargs = {
                        'categorie': edit_cat.value or '',
                        'omschrijving': edit_omschr.value or '',
                    }
                    if edit_bedrag is not None:
                        kwargs['bedrag'] = edit_bedrag.value
                    if edit_inv.value:
                        kwargs['is_investering'] = 1
                        kwargs['levensduur_jaren'] = edit_lv.value
                        kwargs['restwaarde_pct'] = edit_rest.value or 10
                        kwargs['zakelijk_pct'] = edit_zak.value or 100
                        kwargs['aanschaf_bedrag'] = (
                            edit_bedrag.value if edit_bedrag is not None
                            else row['bedrag'])
                    else:
                        kwargs['is_investering'] = 0
                        kwargs['levensduur_jaren'] = None
                        kwargs['aanschaf_bedrag'] = None
                    await update_uitgave(
                        DB_PATH, uitgave_id=row['id_uitgave'], **kwargs)
                    ui.notify('Opgeslagen', type='positive')
                    dialog.close()
                    await refresh()
                except YearLockedError as e:
                    ui.notify(str(e), type='negative')

            ui.button('Opslaan', icon='save', on_click=opslaan) \
                .props('color=primary')

    dialog.open()


async def _render_factuur_tab(container, uitgave, row, refresh, dialog):
    """Render the Factuur tab: PDF preview OR upload + archive suggestions.

    Called recursively after upload / delete / koppel so the panel reflects
    the fresh state without re-opening the whole dialog.
    """
    container.clear()
    pdf = (uitgave.pdf_pad if uitgave else '') or ''
    if pdf and Path(pdf).exists():
        data = await asyncio.to_thread(Path(pdf).read_bytes)
        b64 = base64.b64encode(data).decode('ascii')
        suffix = Path(pdf).suffix.lower()
        mime = 'application/pdf' if suffix == '.pdf' else 'image/*'
        with container:
            ui.html(
                f'<iframe src="data:{mime};base64,{b64}" '
                f'style="width:100%;height:520px;border:1px solid #e5e7eb;'
                f'border-radius:8px"></iframe>')
            with ui.row().classes('gap-2 q-mt-sm'):
                ui.button('Download', icon='download',
                          on_click=lambda: ui.download.file(pdf)) \
                    .props('flat dense')

                async def verwijder_bon():
                    try:
                        await update_uitgave(
                            DB_PATH, uitgave_id=uitgave.id, pdf_pad='')
                    except YearLockedError as e:
                        ui.notify(str(e), type='negative')
                        return
                    p = Path(pdf)
                    if p.exists():
                        await asyncio.to_thread(p.unlink)
                    ui.notify('Bon verwijderd', type='positive')
                    await _render_factuur_tab(
                        container, uitgave, row, refresh, dialog)

                ui.button('Verwijder bon', icon='delete',
                          on_click=verwijder_bon) \
                    .props('flat dense color=negative')
        return

    # No PDF yet — upload widget + archive suggestions.
    with container:
        upload_target = {'event': None}
        ui.upload(
            label='Bon uploaden', auto_upload=True,
            on_upload=lambda e: upload_target.update({'event': e}),
            max_file_size=10_000_000) \
            .classes('w-full').props(
                'flat bordered accept=".pdf,.jpg,.jpeg,.png"')

        async def do_save_upload():
            e = upload_target['event']
            if e is None:
                ui.notify('Selecteer eerst een bestand', type='warning')
                return
            if uitgave is None:
                ui.notify('Geen uitgave om te koppelen', type='negative')
                return
            try:
                await save_upload_for_uitgave(uitgave.id, e)
            except YearLockedError as ex:
                ui.notify(str(ex), type='negative')
                return
            ui.notify('Bon opgeslagen', type='positive')
            await refresh()
            # Re-render with the now-linked PDF. Re-read the fresh uitgave
            # first so the pdf_pad is visible on this recursion.
            fresh_u = await get_uitgave_by_id(DB_PATH, uitgave.id) or uitgave
            await _render_factuur_tab(
                container, fresh_u, row, refresh, dialog)

        ui.button('Koppel', on_click=do_save_upload) \
            .props('color=primary dense')

        # Archive suggestions only make sense for bank-linked rows —
        # find_pdf_matches_for_banktx keys on the bank tx.
        if row.get('id_bank') is not None:
            ui.separator().classes('q-my-sm')
            ui.label('Slimme suggesties uit archief') \
                .classes('text-caption text-bold')
            matches = await find_pdf_matches_for_banktx(
                DB_PATH, row['id_bank'], int(row['datum'][:4]))
            if not matches:
                ui.label('Geen archief-suggesties gevonden') \
                    .classes('text-caption text-grey')
            for m in matches[:5]:
                with ui.row().classes(
                        'w-full items-center gap-2 q-py-xs'):
                    ui.icon('picture_as_pdf', color='red')
                    ui.label(m.filename).classes('text-body2')
                    ui.label(f'→ {m.categorie}') \
                        .classes('text-caption text-grey')
                    ui.space()

                    async def _koppel(mm=m):
                        if uitgave is None:
                            ui.notify('Geen uitgave om te koppelen',
                                      type='negative')
                            return
                        try:
                            await _copy_and_link_pdf(uitgave.id, mm.path)
                            await update_uitgave(
                                DB_PATH, uitgave_id=uitgave.id,
                                categorie=mm.categorie)
                        except YearLockedError as ex:
                            ui.notify(str(ex), type='negative')
                            return
                        ui.notify('Bon gekoppeld', type='positive')
                        await refresh()
                        fresh_u = await get_uitgave_by_id(
                            DB_PATH, uitgave.id) or uitgave
                        await _render_factuur_tab(
                            container, fresh_u, row, refresh, dialog)

                    ui.button('Koppel', on_click=_koppel) \
                        .props('flat dense color=primary size=sm')


async def _render_historie_tab(container, row):
    """Render the Historie tab: last 12 months of entries matching the
    same tegenpartij / omschrijving as this row.

    Iterates ``[jaar, jaar-1]`` so a January row still surfaces the prior
    year's recurring expenses. ``>=3`` hits within 120 days triggers a
    'terugkerende kost' tip.
    """
    container.clear()
    jaar = int(row['datum'][:4])
    jaren = [jaar, jaar - 1]
    tp = (row.get('tegenpartij') or row.get('omschrijving') or '') \
        .strip().lower()
    if not tp:
        with container:
            ui.label('Geen tegenpartij — geen historie beschikbaar.') \
                .classes('text-caption text-grey')
        return

    hits = []
    for y in jaren:
        view = await get_transacties_view(DB_PATH, jaar=y)
        for r in view:
            # Historie scope: debits + manual cash (kosten-side only).
            # Exclude positives (inkomsten) to match the original semantics.
            if r.bedrag >= 0:
                continue
            # Skip the current row itself. For bank rows this compares
            # id_bank; for manual rows both are None and we fall through
            # to the tegenpartij filter (which excludes many matches but
            # is acceptable — manual rows rarely recur identically).
            if r.id_bank is not None and r.id_bank == row.get('id_bank'):
                continue
            if (tp in (r.tegenpartij or '').lower()
                    or tp in (r.omschrijving or '').lower()):
                hits.append(r)
    hits.sort(key=lambda r: r.datum, reverse=True)

    with container:
        if not hits:
            ui.label('Geen eerdere transacties gevonden.') \
                .classes('text-caption text-grey')
            return
        for h in hits[:20]:
            with ui.row().classes('w-full items-center q-py-xs'):
                ui.label(format_datum(h.datum)) \
                    .classes('text-caption text-grey').style('width:100px')
                ui.label(h.tegenpartij or h.omschrijving).classes('flex-1')
                ui.label(format_euro(h.bedrag)) \
                    .classes('text-bold').style('text-align:right')

        if len(hits) >= 3:
            # ``h.datum - row.datum`` is negative for past hits; "within
            # 120 days" means delta > -120.
            row_dt = datetime.strptime(row['datum'], '%Y-%m-%d')
            recent = [h for h in hits
                      if (datetime.strptime(h.datum, '%Y-%m-%d')
                          - row_dt).days > -120]
            if len(recent) >= 3:
                with ui.row().classes(
                        'items-center gap-2 q-mt-md q-pa-sm') \
                        .style('background:#eff6ff;border-radius:8px'):
                    ui.icon('bolt', color='info')
                    ui.label(
                        'Dit lijkt een terugkerende kost — '
                        'gebruik Importeer om volgende exemplaren '
                        'automatisch te categoriseren.') \
                        .classes('text-caption')
