"""Documenten pagina — centraal overzicht van alle beschikkingen en jaaroverzichten."""

import asyncio
from datetime import date
from pathlib import Path

from nicegui import events, ui

from components.document_specs import AANGIFTE_DOCS, AUTO_TYPES, CATEGORIE_LABELS
from components.layout import create_layout, page_title
from database import (
    get_aangifte_documenten, add_aangifte_document, delete_aangifte_document,
    DB_PATH,
)

AANGIFTE_DIR = DB_PATH.parent / 'aangifte'


@ui.page('/documenten')
async def documenten_page():
    create_layout('Documenten', '/documenten')

    huidig_jaar = date.today().year

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        with ui.row().classes('w-full items-center gap-4'):
            page_title('Documenten')
            ui.space()
            jaar_select = ui.select(
                {y: str(y) for y in range(huidig_jaar + 1, 2022, -1)},
                value=huidig_jaar, label='Jaar',
            ).classes('w-32')

        progress_container = ui.column().classes('w-full')
        checklist_container = ui.column().classes('w-full gap-4')

    async def refresh():
        jaar = jaar_select.value
        docs = await get_aangifte_documenten(DB_PATH, jaar)
        uploaded_types = {d.documenttype for d in docs}
        docs_by_type: dict[str, list] = {}
        for d in docs:
            docs_by_type.setdefault(d.documenttype, []).append(d)

        # Check for auto-generated docs (jaarafsluiting PDFs)
        pdf_dir = DB_PATH.parent / 'pdf' / str(jaar)
        auto_done = any(
            f.name.startswith('Jaarcijfers')
            for f in pdf_dir.glob('*.pdf')
        ) if pdf_dir.exists() else False

        # Progress bar
        verplichte = [d for d in AANGIFTE_DOCS if d.verplicht]
        done = sum(1 for d in verplichte
                   if d.documenttype in uploaded_types
                   or (d.documenttype in AUTO_TYPES and auto_done))
        total = len(verplichte)
        all_done = sum(1 for d in AANGIFTE_DOCS
                       if d.documenttype in uploaded_types
                       or (d.documenttype in AUTO_TYPES and auto_done))
        all_total = len(AANGIFTE_DOCS)
        ratio = done / total if total else 0

        progress_container.clear()
        with progress_container:
            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center gap-4'):
                    ui.linear_progress(
                        value=ratio, size='12px', show_value=False,
                        color='positive' if ratio == 1 else 'primary',
                    ).classes('flex-grow')
                    ui.label(f'{all_done}/{all_total} documenten').classes(
                        'text-caption text-grey-7 whitespace-nowrap')

        # Checklist per category
        categories: dict[str, list] = {}
        for item in AANGIFTE_DOCS:
            categories.setdefault(item.categorie, []).append(item)

        checklist_container.clear()
        with checklist_container:
            for cat_key, items in categories.items():
                cat_label = CATEGORIE_LABELS.get(cat_key, cat_key)
                with ui.card().classes('w-full'):
                    ui.label(cat_label).classes('text-subtitle1 text-weight-bold')
                    ui.separator()

                    for spec in items:
                        existing = docs_by_type.get(spec.documenttype, [])
                        is_auto = spec.documenttype in AUTO_TYPES
                        has_doc = len(existing) > 0 or (is_auto and auto_done)

                        with ui.row().classes('w-full items-center q-py-xs gap-2'):
                            if has_doc:
                                ui.icon('check_circle', color='positive') \
                                    .classes('text-lg')
                            else:
                                ui.icon('radio_button_unchecked', color='grey-5') \
                                    .classes('text-lg')

                            label_text = spec.label
                            if spec.verplicht and not is_auto:
                                label_text += ' *'
                            ui.label(label_text).classes('flex-grow')

                            if is_auto:
                                ui.button(
                                    'Ga naar Jaarafsluiting', icon='link',
                                    on_click=lambda: ui.navigate.to(
                                        '/jaarafsluiting'),
                                ).props('flat dense color=primary size=sm')
                            else:
                                # Show existing files
                                for doc in existing:
                                    with ui.row().classes('items-center gap-1'):
                                        ui.icon('description', size='sm') \
                                            .classes('text-grey-6')
                                        ui.label(doc.bestandsnaam).classes(
                                            'text-caption text-grey-7')
                                        if doc.bestandspad and Path(
                                                doc.bestandspad).exists():
                                            ui.button(
                                                icon='download',
                                                on_click=lambda p=doc.bestandspad:
                                                    ui.download(p),
                                            ).props(
                                                'flat dense round size=sm '
                                                'color=primary')

                                        async def del_doc(did=doc.id, fname=doc.bestandsnaam):
                                            with ui.dialog() as del_dlg, ui.card():
                                                ui.label('Document verwijderen?').classes('text-h6')
                                                ui.label(fname).classes('text-grey')
                                                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                                                    ui.button('Annuleren', on_click=del_dlg.close).props('flat')

                                                    async def confirm_del():
                                                        await delete_aangifte_document(DB_PATH, doc_id=did)
                                                        del_dlg.close()
                                                        ui.notify('Verwijderd', type='info')
                                                        await refresh()
                                                    ui.button('Verwijderen', on_click=confirm_del).props('color=negative')
                                            del_dlg.open()

                                        ui.button(
                                            icon='delete',
                                            on_click=del_doc,
                                        ).props(
                                            'flat dense round size=sm '
                                            'color=negative')

                                # Upload button
                                if not existing or spec.meerdere:
                                    async def handle_upload(
                                        e: events.UploadEventArguments,
                                        _spec=spec, _jaar=jaar,
                                    ):
                                        AANGIFTE_DIR.mkdir(
                                            parents=True, exist_ok=True)
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
                                        ui.notify(
                                            f'{_spec.label} geüpload',
                                            type='positive')
                                        await refresh()

                                    ui.upload(
                                        label='Uploaden',
                                        auto_upload=True,
                                        on_upload=handle_upload,
                                    ).props(
                                        'flat color=primary dense '
                                        'accept=".pdf,.jpg,.jpeg,.png"'
                                    ).classes('w-32')

    jaar_select.on_value_change(lambda _: refresh())
    await refresh()
