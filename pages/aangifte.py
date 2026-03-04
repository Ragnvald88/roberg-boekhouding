"""Aangifte pagina — documenten checklist + partner inkomen voor IB-aangifte."""

from datetime import date
from pathlib import Path
from typing import NamedTuple

from nicegui import events, ui

from components.layout import create_layout
from database import (
    get_fiscale_params, get_aangifte_documenten,
    add_aangifte_document, delete_aangifte_document,
    update_partner_inkomen, DB_PATH,
)

AANGIFTE_DIR = DB_PATH.parent / 'aangifte'


class DocSpec(NamedTuple):
    categorie: str
    documenttype: str
    label: str
    meerdere: bool
    verplicht: bool


AANGIFTE_DOCS = [
    DocSpec('eigen_woning', 'woz_beschikking', 'WOZ-beschikking', False, False),
    DocSpec('eigen_woning', 'hypotheek_jaaroverzicht', 'Hypotheek jaaroverzicht', True, False),
    DocSpec('inkomen_partner', 'jaaropgave_partner', 'Jaaropgave partner', True, False),
    DocSpec('pensioen', 'upo_eigen', 'UPO eigen pensioen', False, False),
    DocSpec('pensioen', 'upo_partner', 'UPO partner', False, False),
    DocSpec('verzekeringen', 'aov_jaaroverzicht', 'AOV jaaroverzicht', False, False),
    DocSpec('verzekeringen', 'zorgverzekering_jaaroverzicht', 'Zorgverzekering jaaroverzicht', False, False),
    DocSpec('bankzaken', 'jaaroverzicht_prive', 'Jaaroverzicht privérekening', True, False),
    DocSpec('bankzaken', 'jaaroverzicht_zakelijk', 'Jaaroverzicht zakelijke rekening', True, False),
    DocSpec('bankzaken', 'jaaroverzicht_spaar', 'Jaaroverzicht spaarrekening', True, False),
    DocSpec('studieschuld', 'duo_overzicht', 'DUO overzicht', False, False),
    DocSpec('belastingdienst', 'voorlopige_aanslag', 'Voorlopige aanslag', False, False),
    DocSpec('onderneming', 'jaaroverzicht_uren_km', 'Jaaroverzicht uren/km', False, True),
    DocSpec('onderneming', 'winst_verlies', 'Winst & verlies', False, True),
    DocSpec('definitieve_aangifte', 'ingediende_aangifte', 'Ingediende aangifte (Boekhouder)', False, False),
]

AUTO_TYPES = {'jaaroverzicht_uren_km', 'winst_verlies'}

CATEGORIE_LABELS = {
    'eigen_woning': 'Eigen woning',
    'inkomen_partner': 'Inkomen partner',
    'pensioen': 'Pensioen',
    'verzekeringen': 'Verzekeringen',
    'bankzaken': 'Bankzaken',
    'studieschuld': 'Studieschuld',
    'belastingdienst': 'Belastingdienst',
    'onderneming': 'Onderneming',
    'definitieve_aangifte': 'Definitieve aangifte',
}


@ui.page('/aangifte')
async def aangifte_page():
    create_layout('Aangifte', '/aangifte')

    huidig_jaar = date.today().year
    jaren = list(range(huidig_jaar, 2022, -1))
    state = {'jaar': huidig_jaar}

    # --- Containers ---
    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        # Header row
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('IB-aangifte documenten').classes('text-h5') \
                .style('color: #0F172A; font-weight: 700')
            jaar_select = ui.select(
                {j: str(j) for j in jaren}, value=huidig_jaar, label='Jaar',
                on_change=lambda e: on_jaar_change(e.value),
            ).classes('w-32')

        # Progress bar
        progress_container = ui.column().classes('w-full')

        # Partner inkomen
        partner_card = ui.card().classes('w-full')

        # Checklist
        checklist_container = ui.column().classes('w-full gap-2')

    async def on_jaar_change(jaar):
        state['jaar'] = jaar
        await refresh_all()

    async def refresh_all():
        docs = await get_aangifte_documenten(DB_PATH, state['jaar'])
        await render_progress(docs)
        await render_partner()
        await render_checklist(docs)

    # === Progress bar ===
    async def render_progress(docs):
        progress_container.clear()
        uploaded_types = {d.documenttype for d in docs}

        # Auto-types only count as done if jaarafsluiting PDF exists
        jaarafsluiting_dir = DB_PATH.parent / 'jaarafsluiting'
        auto_done = any(
            f.stem.endswith(str(state['jaar']))
            for f in jaarafsluiting_dir.glob('*.pdf')
        ) if jaarafsluiting_dir.exists() else False

        verplichte = [d for d in AANGIFTE_DOCS if d.verplicht]
        done = sum(1 for d in verplichte
                   if d.documenttype in uploaded_types
                   or (d.documenttype in AUTO_TYPES and auto_done))
        total = len(verplichte)
        ratio = done / total if total else 0

        with progress_container:
            with ui.card().classes('w-full'):
                with ui.row().classes('w-full items-center gap-4'):
                    ui.linear_progress(
                        value=ratio, size='12px', show_value=False,
                        color='positive' if ratio == 1 else 'primary',
                    ).classes('flex-grow')
                    ui.label(f'{done}/{total} verplichte documenten').classes(
                        'text-caption text-grey-7 whitespace-nowrap')

    # === Partner inkomen ===
    async def render_partner():
        partner_card.clear()
        params = await get_fiscale_params(DB_PATH, state['jaar'])

        with partner_card:
            ui.label('Partner inkomen').classes('text-subtitle1 text-weight-medium')
            if not params:
                ui.label(f'Geen fiscale parameters voor {state["jaar"]}. '
                         'Maak deze aan via Instellingen.').classes(
                    'text-caption text-grey-7')
                return
            ui.label('Uit jaaropgave partner (loondienst)').classes(
                'text-caption text-grey-7')
            with ui.row().classes('w-full gap-4 q-mt-sm'):
                bruto_input = ui.number(
                    'Bruto loon', value=params.partner_bruto_loon,
                    format='%.2f', prefix='€',
                ).classes('flex-grow')
                lh_input = ui.number(
                    'Loonheffing', value=params.partner_loonheffing,
                    format='%.2f', prefix='€',
                ).classes('flex-grow')
                ui.button('Opslaan', icon='save',
                          on_click=lambda: save_partner(
                              bruto_input.value or 0, lh_input.value or 0),
                          ).props('color=primary')

    async def save_partner(bruto, loonheffing):
        saved = await update_partner_inkomen(
            DB_PATH, state['jaar'], bruto, loonheffing)
        if saved:
            ui.notify('Partner inkomen opgeslagen', type='positive')
        else:
            ui.notify(f'Geen fiscale parameters voor {state["jaar"]}',
                      type='warning')

    # === Checklist ===
    async def render_checklist(docs):
        checklist_container.clear()

        # Group existing docs by documenttype
        docs_by_type: dict[str, list] = {}
        for d in docs:
            docs_by_type.setdefault(d.documenttype, []).append(d)

        # Auto-types done check
        jaarafsluiting_dir = DB_PATH.parent / 'jaarafsluiting'
        auto_done = any(
            f.stem.endswith(str(state['jaar']))
            for f in jaarafsluiting_dir.glob('*.pdf')
        ) if jaarafsluiting_dir.exists() else False

        # Group AANGIFTE_DOCS by categorie (preserving order)
        categories: dict[str, list[DocSpec]] = {}
        for item in AANGIFTE_DOCS:
            categories.setdefault(item.categorie, []).append(item)

        with checklist_container:
            for cat_key, items in categories.items():
                cat_label = CATEGORIE_LABELS.get(cat_key, cat_key)
                with ui.card().classes('w-full'):
                    ui.label(cat_label).classes(
                        'text-subtitle1 text-weight-bold')
                    ui.separator()

                    for spec in items:
                        existing = docs_by_type.get(spec.documenttype, [])
                        is_auto = spec.documenttype in AUTO_TYPES
                        has_doc = len(existing) > 0 or (is_auto and auto_done)

                        with ui.row().classes(
                                'w-full items-center q-py-xs gap-2'):
                            # Status icon
                            if has_doc:
                                ui.icon('check_circle', color='positive') \
                                    .classes('text-lg')
                            else:
                                ui.icon(
                                    'radio_button_unchecked',
                                    color='grey-5',
                                ).classes('text-lg')

                            # Label
                            label_text = spec.label
                            if spec.verplicht and not is_auto:
                                label_text += ' *'
                            ui.label(label_text).classes('flex-grow')

                            # Auto items: link to jaarafsluiting
                            if is_auto:
                                ui.button(
                                    'Ga naar Jaarafsluiting', icon='link',
                                    on_click=lambda: ui.navigate.to(
                                        '/jaarafsluiting'),
                                ).props(
                                    'flat dense color=primary size=sm')
                                continue

                            # Upload button (opens dialog)
                            if spec.meerdere or not existing:
                                ui.button(
                                    'Uploaden', icon='upload',
                                    on_click=lambda dt=spec.documenttype,
                                    c=spec.categorie:
                                    open_upload_dialog(c, dt),
                                ).props('flat dense color=primary size=sm')

                        # Show existing uploaded files
                        for doc in existing:
                            with ui.row().classes(
                                    'w-full items-center q-pl-xl gap-2'):
                                ui.icon('description', color='grey-6') \
                                    .classes('text-sm')
                                ui.label(doc.bestandsnaam).classes(
                                    'text-caption text-grey-7')
                                ui.button(icon='download',
                                          on_click=lambda d=doc:
                                          do_download(d),
                                          ).props(
                                    'flat dense round size=xs color=primary')
                                ui.button(icon='delete',
                                          on_click=lambda d=doc:
                                          confirm_delete(d),
                                          ).props(
                                    'flat dense round size=xs color=negative')

    async def open_upload_dialog(categorie: str, documenttype: str):
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('Document uploaden').classes(
                'text-subtitle1 text-weight-medium')
            upload_widget = ui.upload(
                auto_upload=True, max_files=1,
                on_upload=lambda e: handle_upload(e, categorie, documenttype,
                                                  dialog),
            ).props('accept=".pdf,.jpg,.png,.jpeg"').classes('w-full')
            ui.button('Annuleren', on_click=dialog.close).props('flat')
        dialog.open()

    async def handle_upload(e: events.UploadEventArguments,
                            categorie: str, documenttype: str,
                            dialog):
        jaar = state['jaar']
        target_dir = AANGIFTE_DIR / str(jaar) / categorie
        target_dir.mkdir(parents=True, exist_ok=True)

        safe_name = Path(e.file.name).name.replace(' ', '_')
        file_path = target_dir / safe_name
        await e.file.save(file_path)

        await add_aangifte_document(
            DB_PATH, jaar=jaar, categorie=categorie,
            documenttype=documenttype, bestandsnaam=safe_name,
            bestandspad=str(file_path),
            upload_datum=date.today().isoformat())

        dialog.close()
        ui.notify(f'{safe_name} geüpload', type='positive')
        await refresh_all()

    async def do_download(doc):
        if Path(doc.bestandspad).exists():
            ui.download.file(doc.bestandspad)
        else:
            ui.notify(f'{doc.bestandsnaam} niet gevonden op schijf',
                      type='warning')

    async def confirm_delete(doc):
        with ui.dialog() as dialog, ui.card():
            ui.label(f'Weet je zeker dat je "{doc.bestandsnaam}" '
                     f'wilt verwijderen?')
            with ui.row().classes('w-full justify-end gap-2'):
                ui.button('Annuleren',
                          on_click=dialog.close).props('flat')
                ui.button('Verwijderen', color='negative',
                          on_click=lambda: do_delete(doc, dialog))
        dialog.open()

    async def do_delete(doc, dialog):
        # Delete DB record first, then file
        await delete_aangifte_document(DB_PATH, doc.id)
        file_path = Path(doc.bestandspad)
        if file_path.exists():
            file_path.unlink()
        dialog.close()
        ui.notify(f'{doc.bestandsnaam} verwijderd', type='warning')
        await refresh_all()

    # Initial render
    await refresh_all()
