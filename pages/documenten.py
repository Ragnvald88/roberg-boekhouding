"""Documenten pagina — document management per boekjaar."""

import asyncio
from datetime import date
from pathlib import Path

from nicegui import app, events, ui

from components.document_specs import AANGIFTE_DOCS, AUTO_TYPES, CATEGORIE_LABELS
from components.layout import create_layout, page_title
from components.shared_ui import year_options
from database import (
    get_aangifte_documenten, add_aangifte_document, delete_aangifte_document,
    DB_PATH,
)

AANGIFTE_DIR = DB_PATH.parent / 'aangifte'
AANGIFTE_DIR.mkdir(parents=True, exist_ok=True)
app.add_static_files('/aangifte-files', str(AANGIFTE_DIR))


@ui.page('/documenten')
async def documenten_page():
    create_layout('Documenten', '/documenten')

    huidig_jaar = date.today().year

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        # Header: title + year + progress badge
        with ui.row().classes('w-full items-center gap-4'):
            page_title('Documenten')
            progress_badge = ui.badge('0/0', color='primary').classes('text-sm')
            ui.space()
            jaar_select = ui.select(
                year_options(as_dict=True),
                value=huidig_jaar, label='Jaar',
            ).classes('w-32')

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
                                AANGIFTE_DIR.mkdir(parents=True, exist_ok=True)
                                dest = AANGIFTE_DIR / fname
                                await asyncio.to_thread(
                                    dest.write_bytes, content)
                                await add_aangifte_document(
                                    DB_PATH, jaar=jaar_select.value,
                                    categorie=cat_select.value,
                                    documenttype=type_select.value,
                                    bestandsnaam=fname,
                                    bestandspad=str(dest),
                                    upload_datum=date.today().isoformat(),
                                )
                                cat_dlg.close()
                                lbl = next(
                                    (d.label for d in AANGIFTE_DOCS
                                     if d.documenttype == type_select.value),
                                    fname)
                                ui.notify(f'{lbl} opgeslagen', type='positive')
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

    # --- Helpers ---

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
                    f'border-radius:8px;"></iframe>')
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

    jaar_select.on_value_change(lambda _: refresh())
    await refresh()


# --- Row renderers (extracted for readability) ---

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
                'background: #F8FAFC; border-radius: 8px; '
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
                            await delete_aangifte_document(
                                DB_PATH, doc_id=did)
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
            AANGIFTE_DIR.mkdir(parents=True, exist_ok=True)
            fname = e.file.name
            dest = AANGIFTE_DIR / fname
            content = await e.file.read()
            await asyncio.to_thread(dest.write_bytes, content)
            await add_aangifte_document(
                DB_PATH, jaar=_jaar,
                categorie=_spec.categorie,
                documenttype=_spec.documenttype,
                bestandsnaam=fname,
                bestandspad=str(dest),
                upload_datum=date.today().isoformat(),
            )
            ui.notify(f'{_spec.label} toegevoegd', type='positive')
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
            'border: 1px dashed #CBD5E1; border-radius: 8px; '
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
            AANGIFTE_DIR.mkdir(parents=True, exist_ok=True)
            fname = e.file.name
            dest = AANGIFTE_DIR / fname
            content = await e.file.read()
            await asyncio.to_thread(dest.write_bytes, content)
            await add_aangifte_document(
                DB_PATH, jaar=_jaar,
                categorie=_spec.categorie,
                documenttype=_spec.documenttype,
                bestandsnaam=fname,
                bestandspad=str(dest),
                upload_datum=date.today().isoformat(),
            )
            ui.notify(f'{_spec.label} geupload', type='positive')
            await refresh_fn()

        ui.upload(
            label='Uploaden',
            auto_upload=True,
            on_upload=handle_upload,
        ).props(
            'flat color=primary dense '
            'accept=".pdf,.jpg,.jpeg,.png"'
        ).classes('w-36')
