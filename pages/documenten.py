"""Documenten pagina — document management per boekjaar."""

import asyncio
import contextlib
import logging
import os
import tempfile
from datetime import date
from pathlib import Path

from nicegui import app, events, ui

log = logging.getLogger(__name__)

from components.document_specs import AANGIFTE_DOCS, AUTO_TYPES, CATEGORIE_LABELS
from components.layout import create_layout, page_title
from components.shared_ui import year_options
from database import (
    get_aangifte_documenten, add_aangifte_document,
    delete_aangifte_document_with_va_cleanup,
    process_voorlopige_aanslag_upload, get_fiscale_params,
    DB_PATH, YearLockedError, assert_year_writable,
)
from services.va_parser import parse_va_beschikking, VAParseError

AANGIFTE_DIR = DB_PATH.parent / 'aangifte'
AANGIFTE_DIR.mkdir(parents=True, exist_ok=True)
app.add_static_files('/aangifte-files', str(AANGIFTE_DIR))


def _safe_documenten_basename(
    fname: str,
    allowed_suffixes: tuple[str, ...] = ('.pdf', '.jpg', '.jpeg', '.png'),
) -> str:
    """Sanitize an upload filename for AANGIFTE_DIR storage.

    Loud-fails (ValueError) on:
      - empty / NUL byte
      - any path component (slash, backslash, '..')
      - leading dot (silent dot-stripping is rejected: '.env.pdf' may NOT
        be silently turned into 'env.pdf' — user must see the rejection)
      - disallowed file extensions

    Design: loud-fail, never silent-sanitize.
    """
    if not fname or '\x00' in fname:
        raise ValueError("Ongeldige bestandsnaam (leeg of NUL byte)")
    if '/' in fname or '\\' in fname or '..' in fname:
        raise ValueError("Bestandsnaam mag geen pad-componenten bevatten")
    if fname.startswith('.'):
        raise ValueError("Bestandsnaam mag niet beginnen met een punt")
    suffix = Path(fname).suffix.lower()
    if suffix not in allowed_suffixes:
        raise ValueError(f"Bestandstype {suffix!r} niet toegestaan")
    return fname


async def _safe_atomic_write(
    dest_dir: Path,
    name: str,
    content: bytes,
) -> tuple[Path, bool]:
    """Write `content` atomically into `dest_dir/name` with collision handling.

    Returns ``(final_path, is_new_write)``.
    - ``is_new_write=False`` betekent idempotent: bestaande file met identieke
      content; geen schrijf-actie. Caller mag deze NIET ``unlink`` op DB-fail.
    - ``is_new_write=True`` betekent: file is daadwerkelijk geschreven. Caller
      MAG (en moet) deze opruimen als de DB-row niet committeert.

    Atomiciteit: schrijft naar ``{dest}.tmp``, dan ``os.replace``. Bij crash
    wordt ``.tmp`` opgeruimd en exception propageert.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    candidate = dest_dir / name

    # Idempotent shortcut + collision-suffix scan
    if candidate.exists():
        existing = await asyncio.to_thread(candidate.read_bytes)
        if existing == content:
            return candidate, False
        # Verschillende content op zelfde naam — vind vrij _N suffix
        stem, suffix = candidate.stem, candidate.suffix
        n = 2
        while True:
            candidate = dest_dir / f"{stem}_{n}{suffix}"
            if not candidate.exists():
                break
            existing = await asyncio.to_thread(candidate.read_bytes)
            if existing == content:
                return candidate, False
            n += 1

    # Codex K2 follow-up: unique tempfile in same dir (geen vaste .tmp die
    # collidet bij parallel uploads), en cleanup in suppress() zodat een
    # falende unlink de oorspronkelijke OSError niet maskeert.
    fd, tmp_str = tempfile.mkstemp(
        dir=dest_dir,
        prefix=candidate.stem + '.',
        suffix='.tmp',
    )
    os.close(fd)
    tmp = Path(tmp_str)
    try:
        await asyncio.to_thread(tmp.write_bytes, content)
        await asyncio.to_thread(os.replace, tmp, candidate)
    except Exception:
        def _cleanup():
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        await asyncio.to_thread(_cleanup)
        raise
    return candidate, True

async def _confirm_pdf_overrides_manual(
    pdf_bedrag: float, manual_bedrag: float,
) -> bool:
    """Toon confirm-dialog als PDF-bedrag afwijkt van handmatige fp-waarde.

    Returns True als user OK kiest (PDF wint), False als annuleert OF
    de dialog dismisses (escape/click-outside) — safe default voor
    destructive overwrite.

    Gebruikt NiceGUI's built-in `Dialog.__await__` + `submit(value)` —
    geen handmatige asyncio.Future nodig (T1.3 code-quality reviewer
    catched dit als reinvented wheel).
    """
    with ui.dialog() as dlg, ui.card().classes('q-pa-md'):
        ui.label(
            f'PDF zegt €{pdf_bedrag:.0f}, je had handmatig '
            f'€{manual_bedrag:.0f}.'
        ).classes('text-h6')
        ui.label('PDF-waarde gebruiken?').classes('text-sm text-grey-7')
        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
            ui.button('Annuleren',
                      on_click=lambda: dlg.submit(False)).props('flat')
            ui.button('PDF gebruiken',
                      on_click=lambda: dlg.submit(True)).props('color=primary')
    # __await__ opens dialog, blocks until submit() of dismissal.
    # Dismissal via escape/click-outside levert None → bool(None) = False.
    result = await dlg
    return bool(result)


_DOCUMENTTYPE_TO_SOORT = {
    'va_ib_beschikking': 'ib',
    'va_zvw_beschikking': 'zvw',
}


async def _auto_backfill_va_for_jaar(jaar: int) -> None:
    """Auto-backfill VA-PDFs op /documenten page-load (Sprint J round-3).

    Detecteert ongekoppelde VA-documenten (geen voorlopige_aanslagen-row)
    en parset ze automatisch. Zichtbare notify per resultaat. Idempotent
    — 2e bezoek doet niets als alles al gekoppeld is.

    Vervangt expliciete CTA-banner op /va-tracker. Architectuur:
    `/documenten` is een write/manage-page (uploads, deletes, categorize),
    auto-derive metadata daar past. `/va-tracker` blijft pure read-page.

    Soft-fail: parse-error op één doc blokkeert niet anderen. Year-locked:
    process_voorlopige_aanslag_upload weigert per-doc.
    """
    from services.va_backfill import backfill_voorlopige_aanslag_documents
    summary = await backfill_voorlopige_aanslag_documents(DB_PATH, jaar)
    if summary.total == 0:
        return  # niets te doen, silent
    # Alleen succes-notifies — failed/skipped/locked blijven als log-only.
    # Reden (Codex audit fix #3): failed-parse PDFs worden niet automatisch
    # opgeruimd, dus zonder log-only zou elke /documenten page-load opnieuw
    # dezelfde warning-notify spammen. De gefaalde docs blijven zichtbaar
    # in de standaard-doc-lijst — user kan ze handmatig deleten of fixen.
    for r in summary.processed:
        ui.notify(
            f'Auto-verwerkt: {r.message}',
            type='positive', timeout=6000)
    for r in summary.skipped:
        log.info('Backfill skipped: doc %s (%s)', r.document_id, r.message)
    for r in summary.failed:
        log.warning(
            'Backfill failed (auto): doc %s (%s) — %s',
            r.document_id, r.bestandsnaam, r.message)
    for r in summary.locked:
        log.info(
            'Backfill skipped (locked): doc %s (%s)',
            r.document_id, r.bestandsnaam)


async def _post_save_va_parse(
    document_id: int, pdf_path: Path,
    documenttype: str | None = None,
) -> None:
    """Parse-on-upload pipeline voor een net opgeslagen VA-beschikking.

    Stappen:
      1. parse_va_beschikking (blocking subprocess → to_thread)
      2. documenttype↔parsed.soort sanity-check (info-notify bij mismatch)
      3. mismatch-check tegen bestaande fp-waarde → user-confirm
      4. process_voorlopige_aanslag_upload (atomic insert/replace/skip)
      5. skip-action → cleanup duplicate document
      6. notify outcome

    Faalt soft: bij parse-error blijft het document staan (user kan
    handmatig invullen via /aangifte). Bij YearLockedError notify we
    en doen niets verder (document blijft als upload zonder VA-row).
    """
    # 1. Parse PDF
    try:
        parsed = await asyncio.to_thread(parse_va_beschikking, pdf_path)
    except VAParseError as err:
        ui.notify(
            f'PDF opgeslagen, automatisch lezen mislukt: {err}. '
            f'Vul handmatig in via /aangifte.',
            type='warning', timeout=8000,
        )
        return
    except Exception as err:  # pragma: no cover — defense-in-depth
        log.exception('Onverwachte parse-error voor VA-beschikking %s', pdf_path)
        ui.notify(
            f'PDF opgeslagen, parse-error: {err}',
            type='warning', timeout=8000,
        )
        return

    # 2. Documenttype↔soort sanity-check (T1.3 code-quality reviewer fix).
    # User kan bv. een VA-IB PDF in het VA-ZVW-slot uploaden — DB accepteert
    # dat (alleen categorie+jaar gevalideerd), maar /documenten badge zou
    # dan ZVW-checkbox groen tonen terwijl het IB-bedrag wordt gesynced.
    # We laten de upload doorgaan (parser is single source of truth voor
    # soort), maar waarschuwen de user expliciet zodat ze bewust zijn.
    if documenttype:
        expected_soort = _DOCUMENTTYPE_TO_SOORT.get(documenttype)
        if expected_soort and expected_soort != parsed.soort:
            ui.notify(
                f'Let op: PDF is een VA-{parsed.soort.upper()}-beschikking '
                f'maar geüpload als {documenttype}-slot. Het bedrag wordt '
                f'verwerkt als VA-{parsed.soort.upper()}.',
                type='info', timeout=8000,
            )

    # 3. Mismatch-check (UI-laag, vóór atomic insert)
    fp = await get_fiscale_params(DB_PATH, parsed.jaar)
    if fp is not None:
        existing_bedrag = (
            fp.voorlopige_aanslag_betaald if parsed.soort == 'ib'
            else fp.voorlopige_aanslag_zvw
        )
        if existing_bedrag and abs(existing_bedrag - parsed.bedrag) > 1:
            ok = await _confirm_pdf_overrides_manual(
                parsed.bedrag, existing_bedrag)
            if not ok:
                # User koos annuleren — handmatige fp-waarde behouden.
                # Document blijft staan als upload zonder VA-row.
                ui.notify(
                    'PDF-waarde genegeerd; handmatige bedrag behouden.',
                    type='info')
                return

    # 4. Atomic DB-pipeline
    try:
        result = await process_voorlopige_aanslag_upload(
            db_path=DB_PATH, document_id=document_id, parsed=parsed,
        )
    except YearLockedError as exc:
        ui.notify(str(exc), type='warning')
        return
    except ValueError as exc:
        # Defensieve guard van process_voorlopige_aanslag_upload (jaar
        # mismatch / categorie mismatch) — zou niet moeten gebeuren omdat
        # we de doc zelf net inserted'en als categorie='voorlopige_aanslag'
        # met dezelfde jaar; toch tonen en niet crashen.
        ui.notify(f'VA-verwerking afgewezen: {exc}', type='warning')
        return

    # 5. Skip → duplicate, ruim het net-uploadedde document op
    if result['action'] == 'skip':
        try:
            await delete_aangifte_document_with_va_cleanup(
                DB_PATH, doc_id=document_id)
        except YearLockedError:
            # Cleanup faalt op locked jaar — info-melding, document blijft.
            ui.notify(
                'Beschikking al verwerkt; duplicate document kon niet '
                'worden opgeruimd (jaar afgesloten).',
                type='info')
            return
        ui.notify(
            'Beschikking al verwerkt — duplicate upload opgeruimd',
            type='info')
        return

    # 6. inserted / replaced
    action_label = (
        'vervangen' if result['action'] == 'replaced' else 'bijgewerkt')
    ui.notify(
        f"VA {parsed.soort.upper()} {action_label} naar "
        f"€{parsed.bedrag:.0f}, {parsed.termijnen} termijnen",
        type='positive')


@ui.page('/documenten')
async def documenten_page(jaar: int | None = None):
    create_layout('Documenten', '/documenten')

    # Sprint J post-merge audit fix: respect ?jaar=X query-param uit
    # /va-tracker deep-link. Fall back op today.year als param missing of
    # niet in jaar-options range.
    today_year = date.today().year
    jaren_dict = year_options(as_dict=True)
    available_years = set(jaren_dict.keys()) if isinstance(jaren_dict, dict) else set()
    if jaar is not None and jaar in available_years:
        huidig_jaar = jaar
    else:
        huidig_jaar = today_year

    # Auto-backfill ongekoppelde VA-PDFs voor het zichtbare jaar (Sprint J
    # round-3 architectuur — Codex: read-page mag niet muteren, maar
    # /documenten is geen read-page; auto-process is document-indexering
    # met zichtbare notify, geen stille fiscale correctie). User-feedback:
    # backfill-banner op /va-tracker was extra wrijving — auto-flow op
    # /documenten lost dat op. Idempotent: 2e bezoek = 0 ongekoppelde docs.
    await _auto_backfill_va_for_jaar(huidig_jaar)

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        # Header row
        with ui.row().classes('w-full items-center'):
            page_title('Documenten')
            progress_badge = ui.badge('0/0', color='primary').classes('text-sm q-ml-md')

        # Filter bar
        with ui.element('div').classes('page-toolbar w-full'):
            jaar_select = ui.select(
                year_options(as_dict=True),
                value=huidig_jaar, label='Jaar',
            ).classes('w-28')

        # Upload drop zone
        with ui.card().classes('w-full'):
            with ui.column().classes('w-full items-center q-pa-lg'):
                ui.icon('cloud_upload', size='2.5rem', color='primary')
                ui.label('Sleep een bestand hierheen of klik om te uploaden') \
                    .classes('text-body2 text-grey-6 q-mt-sm')

                async def handle_drop_upload(e: events.UploadEventArguments):
                    """Handle file from the top upload zone — ask for category."""
                    content = await e.file.read()
                    fname = e.file.name

                    with ui.dialog() as cat_dlg, \
                            ui.card().classes('w-full max-w-lg q-pa-md'):
                        ui.label('Document categoriseren').classes('text-h6')
                        with ui.row().classes('items-center gap-2 q-mb-md'):
                            ui.icon('description', color='primary')
                            ui.label(fname).classes('text-grey-7')

                        cat_select = ui.select(
                            CATEGORIE_LABELS, label='Categorie',
                        ).classes('w-full')
                        type_select = ui.select(
                            {}, label='Documenttype',
                        ).classes('w-full')

                        def update_types():
                            cat = cat_select.value
                            if not cat:
                                return
                            types = {
                                d.documenttype: d.label
                                for d in AANGIFTE_DOCS
                                if d.categorie == cat
                                and d.documenttype not in AUTO_TYPES
                            }
                            # Reset eerst — voorkomt dat een type uit een
                            # andere categorie blijft staan als user wisselt
                            # (Codex audit fix #5: save_categorized's "niet
                            # leeg"-check accepteerde dan een type dat NIET
                            # bij de gekozen categorie hoort → DB-mismatch).
                            type_select.value = None
                            type_select.options = types
                            type_select.update()
                            if len(types) == 1:
                                type_select.value = list(types.keys())[0]

                        cat_select.on_value_change(lambda _: update_types())

                        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                            ui.button('Annuleren',
                                      on_click=cat_dlg.close).props('flat')

                            async def save_categorized():
                                if not cat_select.value or not type_select.value:
                                    ui.notify(
                                        'Selecteer categorie en documenttype',
                                        type='warning')
                                    return
                                # K1: 4-step safe upload sequence
                                # 1. Year-lock preflight
                                try:
                                    await assert_year_writable(
                                        DB_PATH, jaar_select.value)
                                except YearLockedError as exc:
                                    ui.notify(str(exc), type='warning')
                                    return
                                # 2. Sanitize filename (loud-fail)
                                try:
                                    safe_name = _safe_documenten_basename(fname)
                                except ValueError as exc:
                                    ui.notify(str(exc), type='negative')
                                    return
                                # 3. Atomic write + collision resolution
                                try:
                                    final_path, is_new = await _safe_atomic_write(
                                        AANGIFTE_DIR, safe_name, content)
                                except Exception as exc:
                                    ui.notify(
                                        f'Schrijven mislukt: {exc}',
                                        type='negative')
                                    return
                                # 4. DB-row + cleanup-on-fail (alleen als WIJ schreven)
                                try:
                                    document_id = await add_aangifte_document(
                                        DB_PATH, jaar=jaar_select.value,
                                        categorie=cat_select.value,
                                        documenttype=type_select.value,
                                        bestandsnaam=final_path.name,
                                        bestandspad=str(final_path),
                                        upload_datum=date.today().isoformat(),
                                    )
                                except YearLockedError as exc:
                                    if is_new:
                                        await asyncio.to_thread(
                                            final_path.unlink,
                                            missing_ok=True)
                                    ui.notify(str(exc), type='warning')
                                    return
                                except Exception as exc:
                                    if is_new:
                                        await asyncio.to_thread(
                                            final_path.unlink,
                                            missing_ok=True)
                                    ui.notify(
                                        f'Database-fout: {exc}',
                                        type='negative')
                                    return
                                cat_dlg.close()
                                lbl = next(
                                    (d.label for d in AANGIFTE_DOCS
                                     if d.documenttype == type_select.value),
                                    final_path.name)
                                ui.notify(f'{lbl} opgeslagen', type='positive')
                                # Sprint J: parse-on-upload voor VA beschikkingen.
                                # Soft-fail: parse-error blokkeert nooit het
                                # opslaan zelf (PDF blijft staan).
                                if cat_select.value == 'voorlopige_aanslag':
                                    await _post_save_va_parse(
                                        document_id, final_path,
                                        documenttype=type_select.value)
                                await refresh()

                            ui.button('Opslaan', icon='save',
                                      on_click=save_categorized) \
                                .props('color=primary')
                    cat_dlg.open()

                ui.upload(
                    auto_upload=True,
                    on_upload=handle_drop_upload,
                ).props(
                    'flat color=primary '
                    'accept=".pdf,.jpg,.jpeg,.png" '
                    'label="Bestand kiezen"'
                ).classes('q-mt-sm')

        # Progress bar
        progress_container = ui.row().classes('w-full')

        # Category cards
        cards_container = ui.column().classes('w-full gap-4')
    async def show_preview(bestandspad: str, bestandsnaam: str):
        """Show document preview in a dialog."""
        with ui.dialog() as dlg, \
                ui.card().classes('w-full max-w-4xl q-pa-md'):
            with ui.row().classes('w-full items-center'):
                ui.label(bestandsnaam).classes('text-h6 flex-grow')
                ui.button(
                    icon='download',
                    on_click=lambda: ui.download(bestandspad),
                ).props('flat round color=primary')
                ui.button(icon='close', on_click=dlg.close) \
                    .props('flat round')
            ui.separator().classes('q-my-sm')

            try:
                rel_path = Path(bestandspad).relative_to(AANGIFTE_DIR)
                url = f'/aangifte-files/{rel_path}'
            except ValueError:
                # File not under AANGIFTE_DIR — use just filename as fallback
                url = f'/aangifte-files/{Path(bestandspad).name}'

            ext = Path(bestandsnaam).suffix.lower()
            if ext == '.pdf':
                ui.html(
                    f'<iframe src="{url}" '
                    f'style="width:100%;height:70vh;border:none;'
                    f'border-radius:8px;"></iframe>',
                    sanitize=False,
                )
            elif ext in ('.jpg', '.jpeg', '.png', '.gif'):
                ui.image(url).classes('w-full')
            else:
                ui.label('Preview niet beschikbaar.') \
                    .classes('text-grey-6 q-pa-lg text-center')
        dlg.open()

    async def refresh():
        jaar = jaar_select.value
        docs = await get_aangifte_documenten(DB_PATH, jaar)
        uploaded_types = {d.documenttype for d in docs}
        docs_by_type: dict[str, list] = {}
        for d in docs:
            docs_by_type.setdefault(d.documenttype, []).append(d)

        # Auto-generated docs (jaarafsluiting PDFs)
        pdf_dir = DB_PATH.parent / 'pdf' / str(jaar)
        auto_done = any(
            f.name.startswith('Jaarcijfers')
            for f in pdf_dir.glob('*.pdf')
        ) if pdf_dir.exists() else False

        # Progress badge
        all_done = sum(1 for d in AANGIFTE_DOCS
                       if d.documenttype in uploaded_types
                       or (d.documenttype in AUTO_TYPES and auto_done))
        all_total = len(AANGIFTE_DOCS)
        progress_badge.set_text(f'{all_done}/{all_total}')
        progress_badge.props(
            f"color={'positive' if all_done >= all_total else 'primary'}")

        # Progress bar (verplichte documenten)
        verplichte = [d for d in AANGIFTE_DOCS if d.verplicht]
        done_v = sum(1 for d in verplichte
                     if d.documenttype in uploaded_types
                     or (d.documenttype in AUTO_TYPES and auto_done))
        total_v = len(verplichte)
        ratio = done_v / total_v if total_v else 0

        progress_container.clear()
        with progress_container:
            with ui.row().classes('w-full items-center gap-3'):
                ui.linear_progress(
                    value=ratio, size='10px', show_value=False,
                    color='positive' if ratio == 1 else 'primary',
                ).classes('flex-grow').props('rounded')
                ui.label(f'{done_v}/{total_v} verplicht').classes(
                    'text-caption text-grey-6 whitespace-nowrap')

        # Category cards
        categories: dict[str, list] = {}
        for item in AANGIFTE_DOCS:
            categories.setdefault(item.categorie, []).append(item)

        cards_container.clear()
        with cards_container:
            for cat_key, specs in categories.items():
                cat_label = CATEGORIE_LABELS.get(cat_key, cat_key)
                cat_done = sum(
                    1 for s in specs
                    if s.documenttype in uploaded_types
                    or (s.documenttype in AUTO_TYPES and auto_done))
                cat_total = len(specs)

                with ui.card().classes('w-full'):
                    # Category header with folder icon + count
                    with ui.row().classes('w-full items-center'):
                        ui.icon('folder', color='primary').classes('text-lg')
                        ui.label(cat_label).classes(
                            'text-subtitle1 text-weight-bold flex-grow')
                        badge_color = ('positive'
                                       if cat_done >= cat_total else 'grey-6')
                        ui.badge(f'{cat_done}/{cat_total}',
                                 color=badge_color).classes('text-xs')
                    ui.separator().classes('q-my-sm')

                    for spec in specs:
                        existing = docs_by_type.get(spec.documenttype, [])
                        is_auto = spec.documenttype in AUTO_TYPES
                        has_doc = len(existing) > 0 or (is_auto and auto_done)

                        if is_auto:
                            _render_auto_row(spec, auto_done)
                        elif has_doc:
                            _render_uploaded_rows(
                                spec, existing, jaar, show_preview, refresh)
                        else:
                            _render_missing_row(spec, jaar, refresh)

    async def _on_year_change():
        # Auto-backfill triggert óók bij jaar-wissel via dropdown — anders
        # blijven ongekoppelde VA-PDFs in andere jaren onverwerkt zolang de
        # user die jaar niet via deep-link bezoekt (Codex audit fix #1).
        await _auto_backfill_va_for_jaar(jaar_select.value)
        await refresh()

    jaar_select.on_value_change(lambda _: _on_year_change())
    await refresh()
def _render_auto_row(spec, auto_done: bool):
    """Render a row for auto-generated documents (jaarafsluiting)."""
    with ui.row().classes('w-full items-center q-py-sm gap-3'):
        ui.icon(
            'check_circle' if auto_done else 'hourglass_empty',
            color='positive' if auto_done else 'grey-5',
        ).classes('text-lg')
        with ui.column().classes('flex-grow gap-0'):
            ui.label(spec.label).classes('text-body2')
            ui.label('Automatisch via Jaarafsluiting') \
                .classes('text-caption text-grey-6')
        ui.button(
            'Jaarafsluiting', icon='link',
            on_click=lambda: ui.navigate.to('/jaarafsluiting'),
        ).props('flat dense color=primary size=sm')

def _render_uploaded_rows(spec, existing, jaar, show_preview_fn, refresh_fn):
    """Render rows for uploaded documents."""
    for doc in existing:
        file_exists = doc.bestandspad and Path(doc.bestandspad).exists()
        ext = Path(doc.bestandsnaam).suffix.lower()
        icon_name = ('picture_as_pdf' if ext == '.pdf'
                     else 'image' if ext in ('.jpg', '.jpeg', '.png')
                     else 'description')

        with ui.row().classes('w-full items-center q-py-sm gap-3').style(
                'background: var(--bg); border-radius: 8px; '
                'padding: 8px 12px'):
            ui.icon(icon_name, color='primary').classes('text-lg')
            with ui.column().classes('flex-grow gap-0'):
                ui.label(doc.bestandsnaam).classes('text-body2')
                with ui.row().classes('gap-2'):
                    ui.label(spec.label).classes(
                        'text-caption text-grey-6')
                    if doc.upload_datum:
                        ui.label(f'Geupload {doc.upload_datum}') \
                            .classes('text-caption text-grey-5')

            if file_exists:
                ui.button(
                    icon='visibility',
                    on_click=lambda p=doc.bestandspad,
                    n=doc.bestandsnaam: show_preview_fn(p, n),
                ).props('flat dense round size=sm color=primary')
                ui.button(
                    icon='download',
                    on_click=lambda p=doc.bestandspad: ui.download(p),
                ).props('flat dense round size=sm color=primary')

            async def del_doc(did=doc.id, fname=doc.bestandsnaam):
                with ui.dialog() as del_dlg, ui.card():
                    ui.label('Document verwijderen?').classes('text-h6')
                    ui.label(fname).classes('text-grey')
                    with ui.row().classes(
                            'w-full justify-end gap-2 q-mt-md'):
                        ui.button('Annuleren',
                                  on_click=del_dlg.close).props('flat')

                        async def confirm_del():
                            # Sprint J post-merge audit fix: gebruik
                            # cleanup-wrapper zodat fp.voorlopige_aanslag_*
                            # ook ge-cleared wordt bij delete van een
                            # VA-document. Niet-VA docs: wrapper delegeert
                            # alleen de delete (geen extra side-effects).
                            try:
                                await delete_aangifte_document_with_va_cleanup(
                                    DB_PATH, doc_id=did)
                            except YearLockedError as exc:
                                del_dlg.close()
                                ui.notify(str(exc), type='warning')
                                return
                            del_dlg.close()
                            ui.notify('Verwijderd', type='info')
                            await refresh_fn()
                        ui.button('Verwijderen',
                                  on_click=confirm_del) \
                            .props('color=negative')
                del_dlg.open()

            ui.button(
                icon='delete', on_click=del_doc,
            ).props('flat dense round size=sm color=negative')

    # "Add another" upload for types that allow multiple
    if spec.meerdere:
        async def handle_extra(
            e: events.UploadEventArguments,
            _spec=spec, _jaar=jaar,
        ):
            # K1: 4-step safe upload sequence
            try:
                await assert_year_writable(DB_PATH, _jaar)
            except YearLockedError as exc:
                ui.notify(str(exc), type='warning')
                return
            try:
                safe_name = _safe_documenten_basename(e.file.name)
            except ValueError as exc:
                ui.notify(str(exc), type='negative')
                return
            content = await e.file.read()
            try:
                final_path, is_new = await _safe_atomic_write(
                    AANGIFTE_DIR, safe_name, content)
            except Exception as exc:
                ui.notify(f'Schrijven mislukt: {exc}', type='negative')
                return
            try:
                document_id = await add_aangifte_document(
                    DB_PATH, jaar=_jaar,
                    categorie=_spec.categorie,
                    documenttype=_spec.documenttype,
                    bestandsnaam=final_path.name,
                    bestandspad=str(final_path),
                    upload_datum=date.today().isoformat(),
                )
            except YearLockedError as exc:
                if is_new:
                    await asyncio.to_thread(
                        final_path.unlink, missing_ok=True)
                ui.notify(str(exc), type='warning')
                return
            except Exception as exc:
                if is_new:
                    await asyncio.to_thread(
                        final_path.unlink, missing_ok=True)
                ui.notify(f'Database-fout: {exc}', type='negative')
                return
            ui.notify(f'{_spec.label} toegevoegd', type='positive')
            # Sprint J: parse-on-upload voor VA beschikkingen.
            if _spec.categorie == 'voorlopige_aanslag':
                await _post_save_va_parse(document_id, final_path,
                                          documenttype=_spec.documenttype)
            await refresh_fn()

        with ui.row().classes('q-mt-xs'):
            ui.upload(
                label='Nog een toevoegen',
                auto_upload=True,
                on_upload=handle_extra,
            ).props(
                'flat color=primary dense '
                'accept=".pdf,.jpg,.jpeg,.png"'
            ).classes('w-40')

def _render_missing_row(spec, jaar, refresh_fn):
    """Render a row for a missing (not yet uploaded) document."""
    with ui.row().classes('w-full items-center q-py-sm gap-3').style(
            'border: 1px dashed var(--border); border-radius: 8px; '
            'padding: 8px 12px'):
        ui.icon('upload_file', color='grey-5').classes('text-lg')
        with ui.column().classes('flex-grow gap-0'):
            label_text = spec.label
            if spec.verplicht:
                label_text += ' *'
            ui.label(label_text).classes('text-body2 text-grey-7')

        async def handle_upload(
            e: events.UploadEventArguments,
            _spec=spec, _jaar=jaar,
        ):
            # K1: 4-step safe upload sequence
            try:
                await assert_year_writable(DB_PATH, _jaar)
            except YearLockedError as exc:
                ui.notify(str(exc), type='warning')
                return
            try:
                safe_name = _safe_documenten_basename(e.file.name)
            except ValueError as exc:
                ui.notify(str(exc), type='negative')
                return
            content = await e.file.read()
            try:
                final_path, is_new = await _safe_atomic_write(
                    AANGIFTE_DIR, safe_name, content)
            except Exception as exc:
                ui.notify(f'Schrijven mislukt: {exc}', type='negative')
                return
            try:
                document_id = await add_aangifte_document(
                    DB_PATH, jaar=_jaar,
                    categorie=_spec.categorie,
                    documenttype=_spec.documenttype,
                    bestandsnaam=final_path.name,
                    bestandspad=str(final_path),
                    upload_datum=date.today().isoformat(),
                )
            except YearLockedError as exc:
                if is_new:
                    await asyncio.to_thread(
                        final_path.unlink, missing_ok=True)
                ui.notify(str(exc), type='warning')
                return
            except Exception as exc:
                if is_new:
                    await asyncio.to_thread(
                        final_path.unlink, missing_ok=True)
                ui.notify(f'Database-fout: {exc}', type='negative')
                return
            ui.notify(f'{_spec.label} geupload', type='positive')
            # Sprint J: parse-on-upload voor VA beschikkingen.
            if _spec.categorie == 'voorlopige_aanslag':
                await _post_save_va_parse(document_id, final_path,
                                          documenttype=_spec.documenttype)
            await refresh_fn()

        ui.upload(
            label='Uploaden',
            auto_upload=True,
            on_upload=handle_upload,
        ).props(
            'flat color=primary dense '
            'accept=".pdf,.jpg,.jpeg,.png"'
        ).classes('w-36')
