"""Two-panel invoice builder with live preview."""

import asyncio
import base64
import inspect
import shutil
import tempfile
from datetime import date
from pathlib import Path

from nicegui import app, ui

from components.invoice_generator import generate_invoice
from components.invoice_preview import render_invoice_html
from components.shared_ui import date_input, open_klant_dialog
from components.utils import format_euro, format_datum
from database import (
    DB_PATH, add_factuur, add_klant, get_bedrijfsgegevens, get_klanten,
    get_next_factuurnummer, get_werkdagen, get_werkdagen_ongefactureerd,
    link_werkdagen_to_factuur,
)

PDF_DIR = DB_PATH.parent / "facturen"
QR_DIR = DB_PATH.parent / "qr"
LOGO_DIR = DB_PATH.parent / "logo"
QR_DIR.mkdir(parents=True, exist_ok=True)
LOGO_DIR.mkdir(parents=True, exist_ok=True)
app.add_static_files('/qr-files', str(QR_DIR))
app.add_static_files('/logo-files', str(LOGO_DIR))


def _werkdagen_to_line_items(werkdagen, thuisplaats: str = '') -> list[dict]:
    """Convert werkdag objects/dicts to line_item dicts for the builder.

    Each werkdag produces a single line_item with optional km fields.
    Reiskosten are split out into separate PDF regels by _build_regels.
    """
    items = []
    for w in werkdagen:
        # Support both objects (with attrs) and dicts
        datum = w.datum if hasattr(w, 'datum') else w['datum']
        activiteit = (w.activiteit if hasattr(w, 'activiteit')
                      else w.get('activiteit', 'Waarneming dagpraktijk'))
        uren = w.uren if hasattr(w, 'uren') else w['uren']
        tarief = w.tarief if hasattr(w, 'tarief') else w['tarief']
        km = (w.km if hasattr(w, 'km') else w.get('km', 0)) or 0
        km_tarief = (w.km_tarief if hasattr(w, 'km_tarief')
                     else w.get('km_tarief', 0))
        locatie = (w.locatie if hasattr(w, 'locatie')
                   else w.get('locatie', ''))
        wid = w.id if hasattr(w, 'id') else w.get('id')

        # Build reiskosten omschrijving
        if km > 0:
            if locatie and thuisplaats:
                km_omschr = f'Reiskosten (retour {thuisplaats} \u2013 {locatie})'
            elif locatie:
                km_omschr = f'Reiskosten (retour \u2013 {locatie})'
            else:
                km_omschr = 'Reiskosten'
        else:
            km_omschr = ''

        items.append({
            'datum': datum,
            'omschrijving': activiteit or 'Waarneming dagpraktijk',
            'aantal': uren,
            'tarief': tarief,
            'werkdag_id': wid,
            'is_reiskosten': False,
            'km': km,
            'km_tarief': km_tarief,
            'km_omschrijving': km_omschr,
        })
    return items


def _build_regels(line_items: list[dict]) -> list[dict]:
    """Convert line_items state into regels dicts for invoice rendering.

    Splits km fields back into separate reiskosten regels for the PDF.
    """
    regels = []
    for li in line_items:
        aantal = li.get('aantal', 0) or 0
        tarief = li.get('tarief', 0) or 0
        regels.append({
            'datum': li.get('datum', ''),
            'omschrijving': li.get('omschrijving', ''),
            'aantal': aantal,
            'tarief': tarief,
            'bedrag': aantal * tarief,
            'is_reiskosten': li.get('is_reiskosten', False),
        })
        # Split km into separate reiskosten regel for PDF
        km = li.get('km', 0) or 0
        km_tarief = li.get('km_tarief', 0) or 0
        if km > 0:
            regels.append({
                'datum': li.get('datum', ''),
                'omschrijving': li.get('km_omschrijving', 'Reiskosten'),
                'aantal': km,
                'tarief': km_tarief,
                'bedrag': km * km_tarief,
                'is_reiskosten': True,
            })
    return regels


async def open_invoice_builder(on_save=None, pre_selected_werkdag_ids=None):
    """Open the two-panel invoice builder dialog.

    Args:
        on_save: async callback after successful save (refresh table)
        pre_selected_werkdag_ids: list of werkdag IDs pre-selected from werkdagen page
    """
    # Load reference data
    klanten = await get_klanten(DB_PATH, alleen_actief=True)
    klant_by_name = {k.naam: k for k in klanten}
    bg = await get_bedrijfsgegevens(DB_PATH)
    bg_dict = {}
    if bg:
        bg_dict = {
            'bedrijfsnaam': bg.bedrijfsnaam, 'naam': bg.naam,
            'functie': bg.functie, 'adres': bg.adres,
            'postcode_plaats': bg.postcode_plaats, 'kvk': bg.kvk,
            'iban': bg.iban, 'thuisplaats': bg.thuisplaats,
            'telefoon': bg.telefoon, 'email': bg.email,
        }

    jaar = date.today().year
    next_nummer = await get_next_factuurnummer(DB_PATH, jaar=jaar)

    # Load ongefactureerde werkdagen grouped by klant
    all_ongefactureerd = await get_werkdagen_ongefactureerd(DB_PATH)
    klant_by_id = {k.id: k for k in klanten}
    ongefactureerd_per_klant = {}  # klant_id -> list[Werkdag]
    for w in all_ongefactureerd:
        if w.tarief > 0:  # exclude admin/study hours
            ongefactureerd_per_klant.setdefault(w.klant_id, []).append(w)

    # --- State ---
    line_items = []  # list of dicts: {datum, omschrijving, aantal, tarief, werkdag_id}
    matched_klant_id = {'value': None}
    preview_timer = {'handle': None}

    # QR code state
    qr_path = QR_DIR / 'betaal_qr.png'
    qr_url = '/qr-files/betaal_qr.png' if qr_path.exists() else ''

    # Logo state — check for any image in logo dir
    logo_files = list(LOGO_DIR.glob('logo.*'))
    logo_url = ''
    if logo_files:
        logo_url = f'/logo-files/{logo_files[0].name}'

    # --- Dialog ---
    with ui.dialog().props('maximized') as dlg, \
            ui.card().classes('w-full h-full q-pa-none'):

        with ui.row().classes('w-full h-full no-wrap'):
            # ═══════════════ LEFT PANEL ═══════════════
            with ui.column().classes(
                'q-pa-lg builder-panel-border'
            ).style(
                'width: 500px; min-width: 500px; overflow-y: auto; '
                'height: 100vh;'
            ):
                # Header
                with ui.row().classes('w-full items-center'):
                    ui.label('Nieuwe factuur').classes(
                        'text-h5 text-weight-bold')
                    ui.space()
                    ui.button(
                        icon='settings', on_click=lambda: ui.navigate.to(
                            '/instellingen', new_tab=True),
                    ).props('flat round dense size=sm color=grey-6').tooltip(
                        'Bedrijfsgegevens bewerken')
                    ui.badge('Live preview', color='positive').props(
                        'rounded')

                ui.separator().classes('q-my-sm')

                # ── Nummer + Datum ──
                with ui.row().classes('w-full gap-2'):
                    nummer_input = ui.input(
                        'Factuurnummer', value=next_nummer,
                    ).props('outlined dense').classes('flex-1')
                    datum_input = date_input(
                        'Factuurdatum', value=date.today().isoformat(),
                    ).classes('flex-1')

                # ── Klantgegevens ──
                ui.label('Klantgegevens').classes(
                    'text-subtitle2 text-grey-8 q-mt-md')

                klant_options = {k.naam: k.naam for k in klanten}
                with ui.row().classes('w-full items-end gap-1 no-wrap'):
                    bedrijf_input = ui.select(
                        klant_options,
                        label='Bedrijf / Praktijk',
                        with_input=True,
                    ).props('outlined dense use-input input-debounce=0'
                             ).classes('flex-grow')

                    async def open_quick_add_klant():
                        async def after_save(new_id, naam):
                            new_klanten = await get_klanten(
                                DB_PATH, alleen_actief=True)
                            klant_by_name.clear()
                            klant_by_name.update(
                                {k.naam: k for k in new_klanten})
                            bedrijf_input.options = {
                                k.naam: k.naam
                                for k in new_klanten}
                            bedrijf_input.update()
                            bedrijf_input.value = naam
                            matched_klant_id['value'] = new_id
                            # Pre-fill all address fields from new klant
                            kl = klant_by_name.get(naam)
                            if kl:
                                if kl.adres:
                                    adres_input.value = kl.adres
                                if kl.contactpersoon:
                                    contact_input.value = kl.contactpersoon
                                if kl.postcode:
                                    postcode_input.value = kl.postcode
                                if kl.plaats:
                                    plaats_input.value = kl.plaats
                            unmatched_warning.set_visibility(False)
                            schedule_preview_update()

                        await open_klant_dialog(on_save=after_save)

                    ui.button(
                        icon='person_add',
                        on_click=open_quick_add_klant,
                    ).props(
                        'flat round dense size=sm color=primary'
                    ).tooltip('Nieuwe klant toevoegen')

                unmatched_warning = ui.label(
                    'Klantnaam niet gevonden — wordt aangemaakt bij opslaan'
                ).classes('text-caption text-warning')
                unmatched_warning.set_visibility(False)

                contact_input = ui.input(
                    'Contactpersoon',
                ).props('outlined dense').classes('w-full')

                adres_input = ui.input(
                    'Adres',
                ).props('outlined dense').classes('w-full')

                with ui.row().classes('w-full gap-2'):
                    postcode_input = ui.input(
                        'Postcode',
                    ).props('outlined dense').classes('flex-1')
                    plaats_input = ui.input(
                        'Plaats',
                    ).props('outlined dense').classes('flex-1')

                # Klant autocomplete match handler
                def on_klant_match(_=None):
                    name = bedrijf_input.value
                    if name in klant_by_name:
                        k = klant_by_name[name]
                        prev_id = matched_klant_id['value']
                        matched_klant_id['value'] = k.id
                        # Auto-fill address fields when klant actually changed
                        if k.id != prev_id:
                            if k.adres:
                                adres_input.value = k.adres
                            if k.contactpersoon:
                                contact_input.value = k.contactpersoon
                            if k.postcode:
                                postcode_input.value = k.postcode
                            if k.plaats:
                                plaats_input.value = k.plaats
                        unmatched_warning.set_visibility(False)
                    else:
                        matched_klant_id['value'] = None
                        # Show warning if user typed something
                        unmatched_warning.set_visibility(
                            bool(name and len(name) >= 2))
                    schedule_preview_update()

                bedrijf_input.on('blur', on_klant_match)
                bedrijf_input.on('update:model-value', on_klant_match)

                def _read_klant_fields() -> dict:
                    """Read current klant fields from the form inputs."""
                    return {
                        'naam': bedrijf_input.value or '',
                        'contactpersoon': contact_input.value or '',
                        'adres': adres_input.value or '',
                        'postcode': postcode_input.value or '',
                        'plaats': plaats_input.value or '',
                    }

                # Wire klant fields to preview
                for inp in [contact_input, adres_input,
                            postcode_input, plaats_input]:
                    inp.on('blur', lambda _=None: schedule_preview_update())

                # ── Ongefactureerde werkdagen suggesties ──
                ongefact_container = ui.column().classes('w-full gap-1')

                def _render_ongefactureerd():
                    ongefact_container.clear()
                    if not ongefactureerd_per_klant:
                        return
                    with ongefact_container:
                        ui.label('Ongefactureerde werkdagen').classes(
                            'text-subtitle2 text-grey-8 q-mt-md')
                        for kid, wds in sorted(
                                ongefactureerd_per_klant.items(),
                                key=lambda x: -len(x[1])):
                            kl = klant_by_id.get(kid)
                            if not kl:
                                continue
                            n = len(wds)
                            bedrag = sum(
                                w.uren * w.tarief + w.km * w.km_tarief
                                for w in wds)
                            label = (f'1 dag' if n == 1
                                     else f'{n} dagen')

                            def make_importer(klant, werkdagen):
                                def do_import():
                                    # Fill klant fields
                                    bedrijf_input.value = klant.naam
                                    matched_klant_id['value'] = klant.id
                                    if klant.adres:
                                        adres_input.value = klant.adres
                                    if klant.contactpersoon:
                                        contact_input.value = (
                                            klant.contactpersoon)
                                    if klant.postcode:
                                        postcode_input.value = klant.postcode
                                    if klant.plaats:
                                        plaats_input.value = klant.plaats

                                    # Import werkdagen
                                    thuisplaats = bg_dict.get(
                                        'thuisplaats', '')
                                    line_items.clear()
                                    line_items.extend(
                                        _werkdagen_to_line_items(
                                            werkdagen, thuisplaats))

                                    # Set datum to last werkdag
                                    dates = [li['datum']
                                             for li in line_items
                                             if li['datum']]
                                    if dates:
                                        datum_input.value = max(dates)

                                    render_line_items()
                                    schedule_preview_update()

                                    # Hide the suggestions
                                    ongefact_container.clear()
                                return do_import

                            with ui.row().classes(
                                'w-full items-center gap-3 q-py-xs '
                                'q-px-sm rounded'
                            ).style(
                                'border: 1px solid #E2E8F0; '
                                'border-radius: 8px; cursor: pointer'
                            ).on(
                                'click', make_importer(kl, wds)
                            ):
                                ui.icon('work', size='sm',
                                        color='teal')
                                ui.label(kl.naam).classes(
                                    'text-body2 flex-grow')
                                ui.label(label).classes(
                                    'text-caption text-grey-6')
                                ui.label(
                                    format_euro(bedrag)
                                ).classes(
                                    'text-body2 text-weight-bold'
                                ).style(
                                    'font-variant-numeric: tabular-nums')
                                ui.icon('arrow_forward', size='xs',
                                        color='grey-5')

                _render_ongefactureerd()

                # ── Factuurregels ──
                with ui.row().classes('w-full items-center q-mt-md'):
                    ui.label('Factuurregels').classes(
                        'text-subtitle2 text-grey-8')
                    lines_count_badge = ui.badge('0').props(
                        'rounded color=grey-5')
                    lines_count_badge.set_visibility(False)

                lines_container = ui.column().classes('w-full gap-2')

                def render_line_items():
                    """Rebuild the line items UI from state."""
                    lines_container.clear()
                    with lines_container:
                        for idx, item in enumerate(line_items):
                            _render_line_row(idx, item)
                    # Update count badge
                    n = len(line_items)
                    lines_count_badge.text = str(n)
                    lines_count_badge.set_visibility(n > 0)

                def _render_line_row(idx, item):
                    """Render a single line item as compact card."""
                    with ui.card().classes(
                        'w-full q-pa-sm builder-line-card'
                    ):
                        # Row 1: datum + omschrijving + delete
                        with ui.row().classes(
                            'w-full items-center gap-2 no-wrap'
                        ):
                            d_inp = date_input(
                                'Datum', value=item.get('datum', ''),
                            ).classes('w-32')

                            o_inp = ui.input(
                                'Omschrijving',
                                value=item.get('omschrijving', ''),
                            ).props('outlined dense').classes('flex-grow')

                            def make_remover(i):
                                def remove():
                                    line_items.pop(i)
                                    render_line_items()
                                    schedule_preview_update()
                                return remove

                            ui.button(
                                icon='close', on_click=make_remover(idx),
                            ).props(
                                'flat round dense size=sm color=negative')

                        # Row 2: aantal + tarief + bedrag
                        with ui.row().classes(
                            'w-full items-center gap-2 no-wrap'
                        ):
                            a_inp = ui.number(
                                'Uren' if not item.get('is_reiskosten') else 'Aantal',
                                value=item.get('aantal', 0),
                                format='%.2f', min=0, step=0.5,
                            ).props('outlined dense').classes('w-24')

                            t_inp = ui.number(
                                'Tarief', value=item.get('tarief', 0),
                                format='%.2f', min=0, step=0.50,
                            ).props('outlined dense').classes('w-28')

                            # Km field (inline, only for non-reiskosten items)
                            km_val = item.get('km', 0) or 0
                            km_inp = None
                            if not item.get('is_reiskosten'):
                                km_inp = ui.number(
                                    'Km', value=km_val,
                                    format='%.0f', min=0, step=1,
                                ).props('outlined dense').classes('w-20')

                            ui.space()

                            uren_bedrag = (item.get('aantal', 0) or 0) * (
                                item.get('tarief', 0) or 0)
                            km_bedrag = km_val * (item.get('km_tarief', 0) or 0)
                            bedrag_label = ui.label(
                                format_euro(uren_bedrag + km_bedrag),
                            ).classes(
                                'text-body1 text-weight-bold text-right'
                            ).style(
                                'font-variant-numeric: tabular-nums'
                            )

                        def make_updater(i, d_ref, o_ref, a_ref, t_ref,
                                         km_ref, b_ref):
                            def update(_=None):
                                line_items[i]['datum'] = d_ref.value or ''
                                line_items[i]['omschrijving'] = (
                                    o_ref.value or '')
                                line_items[i]['aantal'] = float(
                                    a_ref.value or 0)
                                line_items[i]['tarief'] = float(
                                    t_ref.value or 0)
                                if km_ref is not None:
                                    line_items[i]['km'] = float(
                                        km_ref.value or 0)
                                uren_b = (line_items[i]['aantal']
                                          * line_items[i]['tarief'])
                                km_b = (line_items[i].get('km', 0)
                                        * line_items[i].get('km_tarief', 0))
                                b_ref.text = format_euro(uren_b + km_b)
                                schedule_preview_update()
                            return update

                        updater = make_updater(
                            idx, d_inp, o_inp, a_inp, t_inp,
                            km_inp, bedrag_label)
                        d_inp.on(
                            'update:model-value',
                            lambda _=None, u=updater: u())
                        o_inp.on('blur', updater)
                        a_inp.on_value_change(updater)
                        t_inp.on_value_change(updater)
                        if km_inp is not None:
                            km_inp.on_value_change(updater)

                # Buttons: add free line + import werkdagen
                with ui.row().classes('w-full gap-2 q-mt-xs'):
                    def add_free_line():
                        line_items.append({
                            'datum': date.today().isoformat(),
                            'omschrijving': '',
                            'aantal': 0, 'tarief': 0,
                            'werkdag_id': None,
                            'is_reiskosten': False,
                        })
                        render_line_items()
                        schedule_preview_update()

                    ui.button(
                        '+ Vrije regel', icon='add',
                        on_click=add_free_line,
                    ).props('flat dense color=primary no-caps')

                    async def open_werkdagen_import():
                        kid = matched_klant_id['value']
                        if not kid:
                            ui.notify(
                                'Selecteer eerst een klant (bedrijf)',
                                type='warning')
                            return
                        werkdagen = await get_werkdagen_ongefactureerd(
                            DB_PATH, klant_id=kid)
                        if not werkdagen:
                            ui.notify(
                                'Geen ongefactureerde werkdagen voor '
                                'deze klant',
                                type='info')
                            return

                        with ui.dialog() as wd_dlg, \
                                ui.card().classes(
                                    'w-full max-w-2xl q-pa-md'):
                            ui.label('Werkdagen importeren').classes(
                                'text-h6 q-mb-sm')

                            checks = {}
                            for w in werkdagen:
                                bedrag = (w.uren * w.tarief
                                          + w.km * w.km_tarief)
                                km_part = (f' + {w.km} km'
                                           if w.km else '')
                                cb = ui.checkbox(
                                    f'{format_datum(w.datum)} — '
                                    f'{w.activiteit} — '
                                    f'{w.uren}u x {format_euro(w.tarief)}'
                                    f'{km_part} = '
                                    f'{format_euro(bedrag)}',
                                    value=True,
                                )
                                checks[w.id] = (cb, w)

                            with ui.row().classes(
                                'w-full justify-end gap-2 q-mt-md'
                            ):
                                ui.button(
                                    'Annuleren', on_click=wd_dlg.close,
                                ).props('flat')

                                def do_add_werkdagen():
                                    thuisplaats = bg_dict.get(
                                        'thuisplaats', '')
                                    selected_wds = [
                                        w for _, (cb, w) in checks.items()
                                        if cb.value]
                                    line_items.extend(
                                        _werkdagen_to_line_items(
                                            selected_wds, thuisplaats))
                                    wd_dlg.close()
                                    render_line_items()
                                    schedule_preview_update()
                                    # Set datum to last werkdag date
                                    dates = [
                                        li['datum'] for li in line_items
                                        if li['datum']]
                                    if dates:
                                        datum_input.value = max(dates)

                                ui.button(
                                    'Toevoegen', icon='add',
                                    on_click=do_add_werkdagen,
                                ).props('color=primary')
                        wd_dlg.open()

                    ui.button(
                        '+ Werkdagen importeren', icon='work',
                        on_click=open_werkdagen_import,
                    ).props('flat dense color=primary no-caps')

                # ── QR code ──
                has_qr = qr_path.exists()
                qr_container = ui.column().classes('w-full q-mt-md gap-0')

                # Hidden upload element — triggered by clicking the card
                async def handle_qr_upload(e):
                    nonlocal qr_url
                    content = await e.file.read()
                    await asyncio.to_thread(qr_path.write_bytes, content)
                    qr_url = '/qr-files/betaal_qr.png'
                    _render_qr_card(True)
                    ui.notify('QR-code opgeslagen', type='positive')
                    schedule_preview_update()

                _qr_upload = ui.upload(
                    label='', auto_upload=True,
                    on_upload=handle_qr_upload,
                    max_file_size=2_000_000,
                ).props('flat accept=".png,.jpg,.jpeg"')
                _qr_upload.style(
                    'visibility: hidden; height: 0; overflow: hidden')

                def _pick_qr():
                    _qr_upload.run_method('pickFiles')

                def _render_qr_card(exists: bool):
                    qr_container.clear()
                    with qr_container:
                        if exists:
                            with ui.row().classes('w-full items-center gap-3') \
                                    .style('padding: 10px 14px; background: #F0FDF4; '
                                           'border: 1px solid #BBF7D0; border-radius: 10px'):
                                ui.image(f'/qr-files/betaal_qr.png?t={id(qr_container)}') \
                                    .classes('rounded').style(
                                    'width: 48px; height: 48px; object-fit: contain')
                                with ui.column().classes('gap-0 flex-grow'):
                                    ui.label('Betaal QR-code').classes(
                                        'text-body2 text-weight-medium')
                                    ui.label('Wordt getoond op factuur').classes(
                                        'text-caption text-grey-6')
                                ui.button('Vervangen', icon='swap_horiz',
                                          on_click=_pick_qr) \
                                    .props('flat dense color=primary size=sm')
                        else:
                            with ui.element('div').classes('w-full') \
                                    .style('padding: 16px; border: 2px dashed #CBD5E1; '
                                           'border-radius: 10px; text-align: center; '
                                           'cursor: pointer') \
                                    .on('click', _pick_qr):
                                ui.icon('qr_code_2', size='28px').classes('text-grey-4')
                                ui.label('Betaal QR-code toevoegen').classes(
                                    'text-body2 text-grey-5 q-mt-xs')

                _render_qr_card(has_qr)

                # ── Totaal bar ──
                ui.separator().classes('q-mt-md')
                subtotaal_container = ui.column().classes(
                    'w-full items-end gap-0 q-mt-xs')
                totaal_label = ui.label('Totaal: \u20ac 0,00').classes(
                    'text-h6 text-weight-bold text-right w-full',
                ).style('font-variant-numeric: tabular-nums')

                # ── Action buttons ──
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button(
                        'Annuleren', on_click=dlg.close,
                    ).props('flat')

                    async def download_preview():
                        """Generate a preview PDF and trigger download."""
                        if not line_items:
                            ui.notify(
                                'Voeg eerst factuurregels toe',
                                type='warning')
                            return
                        klant_dict = _read_klant_fields()
                        regels = _build_regels(line_items)
                        tmp_dir = None
                        try:
                            tmp_dir = Path(tempfile.mkdtemp())
                            pdf_path = await asyncio.to_thread(
                                generate_invoice,
                                nummer_input.value or 'preview',
                                klant_dict, [], tmp_dir,
                                factuur_datum=(
                                    datum_input.value
                                    or date.today().isoformat()),
                                bedrijfsgegevens=bg_dict,
                                pre_regels=regels,
                            )
                            # Read bytes before cleanup — ui.download is
                            # async and the file must not be deleted yet
                            pdf_bytes = await asyncio.to_thread(
                                pdf_path.read_bytes)
                            ui.download.content(
                                pdf_bytes, filename=pdf_path.name)
                        except Exception as ex:
                            ui.notify(
                                f'PDF preview mislukt: {ex}',
                                type='negative')
                        finally:
                            if tmp_dir and tmp_dir.exists():
                                shutil.rmtree(tmp_dir, ignore_errors=True)

                    ui.button(
                        'Download PDF', icon='download',
                        on_click=download_preview,
                    ).props('outline color=primary')

                    async def genereer_factuur():
                        # Validate
                        naam = bedrijf_input.value
                        if not naam:
                            ui.notify(
                                'Vul een bedrijfsnaam in', type='warning')
                            return
                        if not line_items:
                            ui.notify(
                                'Voeg minstens een factuurregel toe',
                                type='warning')
                            return

                        nummer = nummer_input.value
                        factuur_datum = (
                            datum_input.value
                            or date.today().isoformat())

                        # Resolve klant_id
                        kid = matched_klant_id['value']
                        if not kid:
                            # Try matching by name one more time
                            if naam in klant_by_name:
                                kid = klant_by_name[naam].id
                            else:
                                # Unknown klant — auto-create with
                                # confirmation
                                with ui.dialog() as cd, \
                                        ui.card().classes('q-pa-md'):
                                    ui.label('Klant niet gevonden'
                                             ).classes('text-h6')
                                    ui.label(
                                        f'"{naam}" bestaat niet. '
                                        f'Klant aanmaken en factuur '
                                        f'genereren?'
                                    ).classes('text-body2 q-my-sm')
                                    with ui.row().classes(
                                        'w-full justify-end gap-2 q-mt-md'
                                    ):
                                        ui.button(
                                            'Annuleren',
                                            on_click=cd.close,
                                        ).props('flat')

                                        async def do_create_and_save():
                                            new_id = await add_klant(
                                                DB_PATH, naam=naam)
                                            new_kl = await get_klanten(
                                                DB_PATH,
                                                alleen_actief=True)
                                            klant_by_name.clear()
                                            klant_by_name.update(
                                                {k.naam: k
                                                 for k in new_kl})
                                            bedrijf_input.options = {
                                                k.naam: k.naam
                                                for k in new_kl}
                                            bedrijf_input.update()
                                            matched_klant_id['value'] = (
                                                new_id)
                                            unmatched_warning \
                                                .set_visibility(False)
                                            cd.close()
                                            ui.notify(
                                                f'Klant "{naam}" '
                                                f'aangemaakt',
                                                type='positive')
                                            # Re-trigger save
                                            await genereer_factuur()

                                        ui.button(
                                            'Aanmaken & factureren',
                                            icon='person_add',
                                            on_click=do_create_and_save,
                                        ).props('color=primary')
                                cd.open()
                                return

                        # Build klant dict and regels for PDF
                        klant_dict = _read_klant_fields()
                        regels = _build_regels(line_items)

                        # Generate PDF
                        try:
                            pdf_path = await asyncio.to_thread(
                                generate_invoice,
                                nummer, klant_dict, [], PDF_DIR,
                                factuur_datum=factuur_datum,
                                bedrijfsgegevens=bg_dict,
                                pre_regels=regels,
                            )
                        except Exception as ex:
                            ui.notify(
                                f'PDF generatie mislukt: {ex}',
                                type='negative')
                            return

                        # Calculate totals (km now on same item, not separate)
                        totaal_uren = sum(
                            li.get('aantal', 0) for li in line_items
                            if not li.get('is_reiskosten'))
                        totaal_km = sum(
                            li.get('km', 0) or 0 for li in line_items)
                        totaal_bedrag = sum(
                            (li.get('aantal', 0) or 0)
                            * (li.get('tarief', 0) or 0)
                            + (li.get('km', 0) or 0)
                            * (li.get('km_tarief', 0) or 0)
                            for li in line_items)

                        # Auto-detect type: werkdag-linked = factuur, free-form = vergoeding
                        has_werkdagen = any(li.get('werkdag_id') for li in line_items)
                        factuur_type = 'factuur' if has_werkdagen else 'vergoeding'

                        # Save factuur record
                        await add_factuur(
                            DB_PATH,
                            nummer=nummer,
                            klant_id=kid,
                            datum=factuur_datum,
                            totaal_uren=totaal_uren,
                            totaal_km=totaal_km,
                            totaal_bedrag=totaal_bedrag,
                            pdf_pad=str(pdf_path),
                            type=factuur_type,
                        )

                        # Link werkdagen
                        werkdag_ids = [
                            li['werkdag_id'] for li in line_items
                            if li.get('werkdag_id')]
                        if werkdag_ids:
                            await link_werkdagen_to_factuur(
                                DB_PATH,
                                werkdag_ids=werkdag_ids,
                                factuurnummer=nummer,
                            )

                        dlg.close()
                        ui.notify(
                            f'Factuur {nummer} aangemaakt '
                            f'({format_euro(totaal_bedrag)})',
                            type='positive')

                        if on_save:
                            result = on_save()
                            if inspect.iscoroutine(result):
                                await result

                    async def opslaan_als_concept():
                        """Save factuur as concept without generating PDF."""
                        naam = bedrijf_input.value
                        if not naam:
                            ui.notify('Vul een bedrijfsnaam in',
                                      type='warning')
                            return
                        if not line_items:
                            ui.notify('Voeg minstens een factuurregel toe',
                                      type='warning')
                            return

                        nummer = nummer_input.value
                        factuur_datum = (
                            datum_input.value
                            or date.today().isoformat())

                        kid = matched_klant_id['value']
                        if not kid:
                            if naam in klant_by_name:
                                kid = klant_by_name[naam].id
                            else:
                                kid = await add_klant(DB_PATH, naam=naam)

                        totaal_uren = sum(
                            li.get('aantal', 0) for li in line_items
                            if not li.get('is_reiskosten'))
                        totaal_km = sum(
                            li.get('km', 0) or 0 for li in line_items)
                        totaal_bedrag = sum(
                            (li.get('aantal', 0) or 0)
                            * (li.get('tarief', 0) or 0)
                            + (li.get('km', 0) or 0)
                            * (li.get('km_tarief', 0) or 0)
                            for li in line_items)

                        has_werkdagen = any(
                            li.get('werkdag_id') for li in line_items)
                        factuur_type = ('factuur' if has_werkdagen
                                        else 'vergoeding')

                        await add_factuur(
                            DB_PATH,
                            nummer=nummer,
                            klant_id=kid,
                            datum=factuur_datum,
                            totaal_uren=totaal_uren,
                            totaal_km=totaal_km,
                            totaal_bedrag=totaal_bedrag,
                            pdf_pad='',
                            type=factuur_type,
                            status='concept',
                        )

                        werkdag_ids = [
                            li['werkdag_id'] for li in line_items
                            if li.get('werkdag_id')]
                        if werkdag_ids:
                            await link_werkdagen_to_factuur(
                                DB_PATH,
                                werkdag_ids=werkdag_ids,
                                factuurnummer=nummer,
                            )

                        dlg.close()
                        ui.notify(
                            f'Concept {nummer} opgeslagen '
                            f'({format_euro(totaal_bedrag)})',
                            type='info')

                        if on_save:
                            result = on_save()
                            if inspect.iscoroutine(result):
                                await result

                    ui.button(
                        'Opslaan als concept', icon='save',
                        on_click=opslaan_als_concept,
                    ).props('outline color=primary')
                    ui.button(
                        'Genereer factuur', icon='receipt',
                        on_click=genereer_factuur,
                    ).props('color=primary')

            # ═══════════════ RIGHT PANEL (preview) ═══════════════
            with ui.element('div').classes('builder-preview-bg').style(
                'flex: 1; overflow-y: auto; '
                'display: flex; justify-content: center; '
                'padding: 24px 0; height: 100vh;'
            ):
                # Use iframe for CSS isolation — template styles
                # won't conflict with NiceGUI's Quasar CSS
                preview_iframe = ui.html('', sanitize=False).style(
                    'width: 100%; max-width: 620px; height: calc(100vh - 48px); '
                )

        # --- Preview update logic ---
        def schedule_preview_update():
            """Debounced preview update (avoids re-render on every keystroke)."""
            if preview_timer['handle']:
                preview_timer['handle'].cancel()
            loop = asyncio.get_running_loop()
            preview_timer['handle'] = loop.call_later(
                0.3, lambda: asyncio.ensure_future(update_preview()))

        async def update_preview():
            """Render the invoice HTML and update the preview panel."""
            regels = _build_regels(line_items)

            subtotaal_werk = sum(
                r['bedrag'] for r in regels
                if not r.get('is_reiskosten'))
            subtotaal_km = sum(
                r['bedrag'] for r in regels
                if r.get('is_reiskosten'))
            totaal = subtotaal_werk + subtotaal_km

            # Update subtotaal breakdown
            subtotaal_container.clear()
            if subtotaal_werk and subtotaal_km:
                with subtotaal_container:
                    ui.label(
                        f'Waarnemingen: {format_euro(subtotaal_werk)}'
                    ).classes('text-caption text-grey-7').style(
                        'font-variant-numeric: tabular-nums')
                    ui.label(
                        f'Reiskosten: {format_euro(subtotaal_km)}'
                    ).classes('text-caption text-grey-7').style(
                        'font-variant-numeric: tabular-nums')
            totaal_label.text = f'Totaal: {format_euro(totaal)}'

            invoice_html = render_invoice_html(
                nummer=nummer_input.value or '',
                klant=_read_klant_fields(),
                regels=regels,
                factuur_datum=datum_input.value or '',
                bedrijfsgegevens=bg_dict,
                qr_url=qr_url,
                logo_url=logo_url,
            )
            # Render in isolated iframe via base64 data URI
            # This prevents NiceGUI/Quasar CSS from interfering
            b64 = base64.b64encode(invoice_html.encode('utf-8')).decode('ascii')
            preview_iframe.content = (
                f'<iframe src="data:text/html;base64,{b64}" '
                f'style="width:100%;height:100%;border:none;'
                f'box-shadow:0 2px 20px rgba(0,0,0,0.15);'
                f'background:white;"></iframe>'
            )

        # Wire nummer + datum to preview
        nummer_input.on('blur', lambda _=None: schedule_preview_update())
        datum_input.on(
            'update:model-value',
            lambda _=None: schedule_preview_update())

        # --- Handle pre-selected werkdagen ---
        if pre_selected_werkdag_ids:
            all_werkdagen = await get_werkdagen(DB_PATH)
            pre_wds = [
                w for w in all_werkdagen
                if w.id in pre_selected_werkdag_ids]
            if pre_wds:
                # Determine klant from first werkdag
                first_klant_id = pre_wds[0].klant_id
                klant_obj = next(
                    (k for k in klanten if k.id == first_klant_id), None)
                if klant_obj:
                    bedrijf_input.value = klant_obj.naam
                    matched_klant_id['value'] = klant_obj.id
                    if klant_obj.adres:
                        adres_input.value = klant_obj.adres
                    if klant_obj.contactpersoon:
                        contact_input.value = klant_obj.contactpersoon
                    if klant_obj.postcode:
                        postcode_input.value = klant_obj.postcode
                    if klant_obj.plaats:
                        plaats_input.value = klant_obj.plaats

                thuisplaats = bg_dict.get('thuisplaats', '')
                line_items.extend(
                    _werkdagen_to_line_items(pre_wds, thuisplaats))

                # Set datum to last werkdag date
                dates = [li['datum'] for li in line_items if li['datum']]
                if dates:
                    datum_input.value = max(dates)

                render_line_items()

        # Initial preview render
        await update_preview()

    dlg.open()
