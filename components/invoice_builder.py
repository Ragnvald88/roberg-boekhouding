"""Two-panel invoice builder with live preview."""

import asyncio
from datetime import date
from pathlib import Path

from nicegui import app, ui

from components.invoice_generator import generate_invoice
from components.invoice_preview import render_invoice_html
from components.shared_ui import date_input
from components.utils import format_euro, format_datum
from database import (
    DB_PATH, add_factuur, get_bedrijfsgegevens, get_klanten,
    get_next_factuurnummer, get_werkdagen, get_werkdagen_ongefactureerd,
    link_werkdagen_to_factuur,
)

PDF_DIR = DB_PATH.parent / "facturen"
QR_DIR = DB_PATH.parent / "qr"
QR_DIR.mkdir(parents=True, exist_ok=True)
app.add_static_files('/qr-files', str(QR_DIR))


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
        }

    jaar = date.today().year
    next_nummer = await get_next_factuurnummer(DB_PATH, jaar=jaar)

    # --- State ---
    line_items = []  # list of dicts: {datum, omschrijving, aantal, tarief, werkdag_id}
    klant_info = {
        'naam': '', 'contactpersoon': '', 'adres': '',
        'postcode': '', 'plaats': '',
    }
    matched_klant_id = {'value': None}
    preview_timer = {'handle': None}

    # QR code state
    qr_path = QR_DIR / 'betaal_qr.png'
    qr_url = '/qr-files/betaal_qr.png' if qr_path.exists() else ''

    # --- Dialog ---
    with ui.dialog().props('maximized') as dlg, \
            ui.card().classes('w-full h-full q-pa-none'):

        with ui.row().classes('w-full h-full no-wrap'):
            # ═══════════════ LEFT PANEL ═══════════════
            with ui.column().classes('q-pa-lg').style(
                'width: 440px; min-width: 440px; overflow-y: auto; '
                'height: 100vh; border-right: 1px solid #e2e8f0;'
            ):
                # Header
                with ui.row().classes('w-full items-center'):
                    ui.label('Nieuwe factuur').classes(
                        'text-h5 text-weight-bold')
                    ui.space()
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
                bedrijf_input = ui.select(
                    klant_options,
                    label='Bedrijf / Praktijk',
                    with_input=True,
                    new_value_mode='add-unique',
                ).props('outlined dense use-input input-debounce=0'
                         ).classes('w-full')

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
                        matched_klant_id['value'] = k.id
                        # Auto-fill address from klant
                        if k.adres and not adres_input.value:
                            adres_input.value = k.adres
                    else:
                        matched_klant_id['value'] = None
                    schedule_preview_update()

                bedrijf_input.on('blur', on_klant_match)
                bedrijf_input.on('update:model-value', on_klant_match)

                # Wire klant fields to preview
                for inp in [contact_input, adres_input,
                            postcode_input, plaats_input]:
                    inp.on('blur', lambda _=None: schedule_preview_update())

                # ── Factuurregels ──
                ui.label('Factuurregels').classes(
                    'text-subtitle2 text-grey-8 q-mt-md')

                lines_container = ui.column().classes('w-full gap-1')

                def render_line_items():
                    """Rebuild the line items UI from state."""
                    lines_container.clear()
                    with lines_container:
                        for idx, item in enumerate(line_items):
                            _render_line_row(idx, item)

                def _render_line_row(idx, item):
                    """Render a single line item row."""
                    with ui.row().classes(
                        'w-full gap-1 items-end'
                    ).style('min-height: 40px'):
                        d_inp = ui.input(
                            'Datum', value=item.get('datum', ''),
                        ).props('outlined dense').classes('w-24')

                        o_inp = ui.input(
                            'Omschrijving',
                            value=item.get('omschrijving', ''),
                        ).props('outlined dense').classes('flex-grow')

                        a_inp = ui.number(
                            'Aantal', value=item.get('aantal', 0),
                            format='%.2f', min=0, step=0.5,
                        ).props('outlined dense').classes('w-20')

                        t_inp = ui.number(
                            'Tarief', value=item.get('tarief', 0),
                            format='%.2f', min=0, step=0.50,
                        ).props('outlined dense').classes('w-24')

                        bedrag = (item.get('aantal', 0) or 0) * (
                            item.get('tarief', 0) or 0)
                        bedrag_label = ui.label(
                            format_euro(bedrag),
                        ).classes(
                            'text-body2 text-weight-bold text-right'
                        ).style(
                            'min-width: 70px; line-height: 40px; '
                            'font-variant-numeric: tabular-nums'
                        )

                        def make_updater(i, d_ref, o_ref, a_ref, t_ref,
                                         b_ref):
                            def update(_=None):
                                line_items[i]['datum'] = d_ref.value or ''
                                line_items[i]['omschrijving'] = (
                                    o_ref.value or '')
                                line_items[i]['aantal'] = float(
                                    a_ref.value or 0)
                                line_items[i]['tarief'] = float(
                                    t_ref.value or 0)
                                b = line_items[i]['aantal'] * line_items[i][
                                    'tarief']
                                b_ref.text = format_euro(b)
                                schedule_preview_update()
                            return update

                        updater = make_updater(
                            idx, d_inp, o_inp, a_inp, t_inp, bedrag_label)
                        d_inp.on('blur', updater)
                        o_inp.on('blur', updater)
                        a_inp.on_value_change(updater)
                        t_inp.on_value_change(updater)

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

                # Buttons: add free line + import werkdagen
                with ui.row().classes('w-full gap-2 q-mt-xs'):
                    def add_free_line():
                        line_items.append({
                            'datum': '', 'omschrijving': '',
                            'aantal': 0, 'tarief': 0,
                            'werkdag_id': None,
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
                                cb = ui.checkbox(
                                    f'{format_datum(w.datum)} — '
                                    f'{w.activiteit} — '
                                    f'{w.uren}u x {format_euro(w.tarief)}'
                                    f' + {w.km} km = '
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
                                    for wid, (cb, w) in checks.items():
                                        if not cb.value:
                                            continue
                                        # Waarneming row
                                        line_items.append({
                                            'datum': w.datum,
                                            'omschrijving': (
                                                w.activiteit
                                                or 'Waarneming dagpraktijk'
                                            ),
                                            'aantal': w.uren,
                                            'tarief': w.tarief,
                                            'werkdag_id': w.id,
                                        })
                                        # Reiskosten row
                                        km = w.km or 0
                                        if km > 0:
                                            loc = w.locatie or ''
                                            if loc and thuisplaats:
                                                omschr = (
                                                    f'Reiskosten retour '
                                                    f'{thuisplaats} \u2013 '
                                                    f'{loc}')
                                            elif loc:
                                                omschr = (
                                                    f'Reiskosten retour '
                                                    f'\u2013 {loc}')
                                            else:
                                                omschr = 'Reiskosten'
                                            line_items.append({
                                                'datum': w.datum,
                                                'omschrijving': omschr,
                                                'aantal': km,
                                                'tarief': w.km_tarief,
                                                'werkdag_id': None,
                                            })
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

                # ── QR upload ──
                ui.label('Betaal QR-code').classes(
                    'text-subtitle2 text-grey-8 q-mt-md')

                if qr_path.exists():
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('qr_code_2', color='positive')
                        ui.label('QR-code aanwezig').classes(
                            'text-body2 text-positive')

                async def handle_qr_upload(e):
                    nonlocal qr_url
                    content = e.content.read()
                    await asyncio.to_thread(qr_path.write_bytes, content)
                    qr_url = '/qr-files/betaal_qr.png'
                    ui.notify('QR-code opgeslagen', type='positive')
                    schedule_preview_update()

                ui.upload(
                    label='Upload QR-code', auto_upload=True,
                    on_upload=handle_qr_upload,
                    max_file_size=2_000_000,
                ).props(
                    'flat bordered accept=".png,.jpg,.jpeg"'
                ).classes('w-full')

                # ── Totaal bar ──
                ui.separator().classes('q-mt-md')
                totaal_label = ui.label('Totaal: \u20ac 0,00').classes(
                    'text-h6 text-weight-bold text-right w-full q-mt-sm',
                ).style('font-variant-numeric: tabular-nums')

                # ── Action buttons ──
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button(
                        'Annuleren', on_click=dlg.close,
                    ).props('flat')

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
                                # Fall back to first klant
                                kid = klanten[0].id if klanten else 1

                        # Build klant dict for PDF
                        klant_dict = {
                            'naam': naam,
                            'contactpersoon': contact_input.value or '',
                            'adres': adres_input.value or '',
                            'postcode': postcode_input.value or '',
                            'plaats': plaats_input.value or '',
                        }

                        # Build werkdagen-style dicts for generator
                        wd_dicts = []
                        for li in line_items:
                            wd_dicts.append({
                                'datum': li.get('datum', ''),
                                'activiteit': li.get('omschrijving', ''),
                                'locatie': '',
                                'uren': li.get('aantal', 0),
                                'tarief': li.get('tarief', 0),
                                'km': 0,
                                'km_tarief': 0,
                            })

                        # Generate PDF
                        try:
                            pdf_path = await asyncio.to_thread(
                                generate_invoice,
                                nummer, klant_dict, wd_dicts, PDF_DIR,
                                factuur_datum=factuur_datum,
                                bedrijfsgegevens=bg_dict,
                            )
                        except Exception as ex:
                            ui.notify(
                                f'PDF generatie mislukt: {ex}',
                                type='negative')
                            return

                        # Calculate totals
                        totaal_uren = sum(
                            li.get('aantal', 0) for li in line_items
                            if 'Reiskosten' not in li.get(
                                'omschrijving', ''))
                        totaal_km = sum(
                            li.get('aantal', 0) for li in line_items
                            if 'Reiskosten' in li.get(
                                'omschrijving', ''))
                        totaal_bedrag = sum(
                            (li.get('aantal', 0) or 0)
                            * (li.get('tarief', 0) or 0)
                            for li in line_items)

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
                            if hasattr(result, '__await__'):
                                await result

                    ui.button(
                        'Genereer factuur', icon='receipt',
                        on_click=genereer_factuur,
                    ).props('color=primary')

            # ═══════════════ RIGHT PANEL (preview) ═══════════════
            with ui.element('div').style(
                'flex: 1; background: #E2E8F0; overflow-y: auto; '
                'display: flex; justify-content: center; '
                'padding: 24px 0; height: 100vh;'
            ):
                # Use iframe for CSS isolation — template styles
                # won't conflict with NiceGUI's Quasar CSS
                preview_iframe = ui.html('').style(
                    'width: 100%; max-width: 620px; height: calc(100vh - 48px); '
                )

        # --- Preview update logic ---
        def schedule_preview_update():
            """Debounced preview update (avoids re-render on every keystroke)."""
            if preview_timer['handle']:
                preview_timer['handle'].cancel()
            loop = asyncio.get_event_loop()
            preview_timer['handle'] = loop.call_later(
                0.3, lambda: asyncio.ensure_future(update_preview()))

        async def update_preview():
            """Render the invoice HTML and update the preview panel."""
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
                })

            totaal = sum(r['bedrag'] for r in regels)
            totaal_label.text = f'Totaal: {format_euro(totaal)}'

            klant = {
                'naam': bedrijf_input.value or '',
                'contactpersoon': contact_input.value or '',
                'adres': adres_input.value or '',
                'postcode': postcode_input.value or '',
                'plaats': plaats_input.value or '',
            }

            invoice_html = render_invoice_html(
                nummer=nummer_input.value or '',
                klant=klant,
                regels=regels,
                factuur_datum=datum_input.value or '',
                bedrijfsgegevens=bg_dict,
                qr_url=qr_url,
            )
            # Render in isolated iframe via base64 data URI
            # This prevents NiceGUI/Quasar CSS from interfering
            import base64
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

                thuisplaats = bg_dict.get('thuisplaats', '')
                for w in pre_wds:
                    # Waarneming row
                    line_items.append({
                        'datum': w.datum,
                        'omschrijving': (
                            w.activiteit or 'Waarneming dagpraktijk'),
                        'aantal': w.uren,
                        'tarief': w.tarief,
                        'werkdag_id': w.id,
                    })
                    # Reiskosten row
                    km = w.km or 0
                    if km > 0:
                        loc = w.locatie or ''
                        if loc and thuisplaats:
                            omschr = (
                                f'Reiskosten retour {thuisplaats} '
                                f'\u2013 {loc}')
                        elif loc:
                            omschr = f'Reiskosten retour \u2013 {loc}'
                        else:
                            omschr = 'Reiskosten'
                        line_items.append({
                            'datum': w.datum,
                            'omschrijving': omschr,
                            'aantal': km,
                            'tarief': w.km_tarief,
                            'werkdag_id': None,
                        })

                # Set datum to last werkdag date
                dates = [li['datum'] for li in line_items if li['datum']]
                if dates:
                    datum_input.value = max(dates)

                render_line_items()

        # Initial preview render
        await update_preview()

    dlg.open()
