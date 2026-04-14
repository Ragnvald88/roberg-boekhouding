"""Facturen pagina — factuur aanmaken, overzicht en betaalstatus."""

import asyncio
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from nicegui import app, events, ui

from components.layout import create_layout, page_title
from components.invoice_builder import open_invoice_builder, _build_regels
from components.invoice_generator import generate_invoice, archive_factuur_pdf
from components.mail_helper import open_mail_with_attachment
from components.utils import format_euro, format_datum, generate_csv
from database import (
    get_facturen, add_factuur,
    delete_factuur, update_factuur,
    update_factuur_status, get_klanten,
    get_bedrijfsgegevens,
    link_werkdagen_to_factuur, get_db_ctx, add_werkdag,
    get_fiscale_params, DB_PATH,
)
from components.shared_ui import year_options, date_input
from import_.pdf_parser import (
    extract_pdf_text, detect_invoice_type,
    parse_dagpraktijk_text, parse_anw_text,
)
from import_.klant_mapping import resolve_klant, resolve_anw_klant

PDF_DIR = DB_PATH.parent / "facturen"

# Serve factuur PDFs for in-browser preview
PDF_DIR.mkdir(parents=True, exist_ok=True)
app.add_static_files('/facturen-files', str(PDF_DIR))


def _should_use_builder(row: dict) -> bool:
    """Native concept werkdag-facturen go to the invoice builder.

    Everything else (anw, vergoeding, imported concepts, verstuurd,
    betaald) uses the simple edit dialog.
    """
    return (
        row.get('status') == 'concept'
        and row.get('type', 'factuur') == 'factuur'
        and row.get('bron', '') != 'import'
    )


def _line_item_to_werkdag_kwargs(
    li: dict,
    inv_type: str,
    inv_km_tarief: float,
) -> dict:
    """Convert a parsed PDF line item into add_werkdag kwargs.

    Centralises the inv_type-specific logic so the import loop can
    stay readable and the conversion is unit-testable. For ANW the
    km_tarief is forced to 0 because reiskosten zijn al in het
    dienst-tarief verdisconteerd (CLAUDE.md).
    """
    if inv_type == 'anw':
        uren = li.get('uren', 0)
        bedrag_li = li.get('bedrag', 0)
        tarief = round(bedrag_li / uren, 2) if uren else 0
        return {
            'code': li.get('dienst_code', ''),
            'activiteit': 'Achterwacht',
            'uren': uren,
            'km': 0.0,
            'tarief': tarief,
            'km_tarief': 0.0,
            'urennorm': 0,
        }
    uren_val = li.get('uren', 0)
    tarief_val = li.get('tarief', 0)
    code = f'WDAGPRAKTIJK_{tarief_val:.2f}'.replace('.', ',')
    return {
        'code': code,
        'activiteit': 'Waarneming dagpraktijk',
        'uren': uren_val,
        'km': li.get('km', 0),
        'tarief': tarief_val,
        'km_tarief': li.get('km_tarief', inv_km_tarief),
        'urennorm': 1,
    }


def _classify_import_item(
    nummer: str | None,
    klant_id: int | None,
    datum: str | None,
    totaal_bedrag: float | None,
    existing_nummers: set[str],
    existing_signatures: set[tuple],
) -> tuple[str, str]:
    """Classify a parsed PDF import as nieuw/duplicaat/fout.

    Returns (status, reason). reason is '' for nieuw, else a short
    Dutch label for why the import was rejected. Rules:
    - no factuurnummer → 'fout' (parser couldn't identify the invoice)
    - nummer already in DB → 'duplicaat'
    - (klant_id, datum, round(bedrag, 2)) already seen → 'duplicaat'
      (fuzzy match for PDFs that differ in layout but represent the
      same invoice)
    - otherwise → 'nieuw'
    """
    if not nummer:
        return 'fout', 'factuurnummer niet herkend'
    if nummer in existing_nummers:
        return 'duplicaat', f'nummer {nummer} bestaat al'
    if klant_id and datum and totaal_bedrag is not None:
        sig = (klant_id, datum, round(float(totaal_bedrag), 2))
        if sig in existing_signatures:
            return 'duplicaat', 'zelfde klant/datum/bedrag'
    return 'nieuw', ''


def _rebuild_vergoeding_regels_json(old_regels_json: str,
                                    new_bedrag: float) -> str:
    """Return a regels_json string with a single line item at new_bedrag.

    Preserves the omschrijving of the first existing regel if any, else
    falls back to 'Vergoeding'. Returned JSON is always a flat list with
    one entry so downstream PDF generation uses the fresh amount.
    """
    import json as _json
    omschrijving = 'Vergoeding'
    try:
        existing = _json.loads(old_regels_json or '[]')
        if isinstance(existing, list) and existing:
            first = existing[0]
            if isinstance(first, dict):
                omschrijving = first.get('omschrijving') or 'Vergoeding'
    except (ValueError, TypeError):
        pass
    return _json.dumps([{'omschrijving': omschrijving,
                         'bedrag': new_bedrag}])


def _build_mail_body(nummer, bedrag, iban, bedrijfsnaam, naam, telefoon, bg_email, betaallink=''):
    """Build plain text factuur email body. Returns a single string.

    Per CLAUDE.md: Mail.app silently breaks HTML content + attachments, so the
    body must stay plain text. Mail.app auto-links plain URLs in plain-text
    bodies, so betaallink can be included as a literal URL — no HTML needed.
    """
    betaallink_line = (
        f'U kunt ook eenvoudig betalen via deze link:\n{betaallink}\n'
        if betaallink else ''
    )
    return (
        f'Bijgaand stuur ik u factuur {nummer}.\n'
        f'\n'
        f'Het totaalbedrag van {bedrag} verzoek ik u binnen 14 dagen '
        f'over te maken op rekeningnummer {iban} t.n.v. {bedrijfsnaam}, '
        f'onder vermelding van factuurnummer {nummer}.\n'
        f'\n'
        f'{betaallink_line}'
        f'Mocht u vragen hebben, dan hoor ik het graag.\n'
        f'\n'
        f'\n'
        f'Met vriendelijke groet,\n'
        f'\n'
        f'{naam}\n'
        f'\n'
        f'{bedrijfsnaam}\n'
        f'{f"Tel: {telefoon}" if telefoon else ""}\n'
        f'{bg_email}'
    )


def _build_herinnering_body(nummer, bedrag, datum, iban, bedrijfsnaam, naam,
                            telefoon, bg_email, betaallink=''):
    """Build plain text herinnering email body for overdue invoices."""
    betaallink_line = (
        f'U kunt ook eenvoudig betalen via deze link:\n{betaallink}\n'
        if betaallink else ''
    )
    return (
        f'Beste klant,\n'
        f'\n'
        f'Wellicht is het aan uw aandacht ontsnapt, maar ik heb nog geen '
        f'betaling ontvangen voor factuur {nummer} van {datum} ter hoogte '
        f'van {bedrag}.\n'
        f'\n'
        f'Ik verzoek u vriendelijk het bedrag binnen 7 dagen over te maken op '
        f'rekeningnummer {iban} t.n.v. {bedrijfsnaam}, onder vermelding van '
        f'factuurnummer {nummer}.\n'
        f'\n'
        f'{betaallink_line}'
        f'Mocht de betaling reeds onderweg zijn, dan kunt u dit bericht als '
        f'niet verzonden beschouwen. Heeft u vragen, neem dan gerust contact op.\n'
        f'\n'
        f'\n'
        f'Met vriendelijke groet,\n'
        f'\n'
        f'{naam}\n'
        f'\n'
        f'{bedrijfsnaam}\n'
        f'{f"Tel: {telefoon}" if telefoon else ""}\n'
        f'{bg_email}'
    )


def _is_verlopen(datum_str: str) -> bool:
    """Check if an invoice is overdue (>14 days past datum and unpaid)."""
    try:
        d = datetime.strptime(datum_str, '%Y-%m-%d').date()
        return (d + timedelta(days=14)) < date.today()
    except (ValueError, TypeError):
        return False


def _display_status(f) -> str:
    """Return the display status for a factuur: concept/verstuurd/verlopen/betaald."""
    if f.status == 'verstuurd' and _is_verlopen(f.datum):
        return 'verlopen'
    return f.status


def _filter_facturen_by_status(facturen, status_val: str):
    """Filter facturen list by display status (including computed 'verlopen')."""
    if not status_val:
        return facturen
    return [f for f in facturen if _display_status(f) == status_val]


@ui.page('/facturen')
async def facturen_page():
    create_layout('Facturen', '/facturen')

    current_year = date.today().year
    table_ref = {'ref': None}
    bulk_bar_ref = {'ref': None}
    filter_klant = {'value': None}  # None = alle klanten

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        # Header row: title + primary action
        with ui.row().classes('w-full items-center'):
            page_title('Facturen')
            ui.space()
            ui.button('Importeer', icon='upload_file',
                      on_click=lambda: open_import_dialog()) \
                .props('flat color=secondary dense')
            ui.button('Nieuwe factuur', icon='add',
                      on_click=lambda: open_invoice_builder(
                          on_save=refresh_table)) \
                .props('color=primary')

        # Filter bar
        with ui.element('div').classes('page-toolbar w-full'):
            jaar_select = ui.select(
                year_options(include_next=True, as_dict=True, descending=False),
                value=current_year, label='Jaar',
            ).classes('w-28')

            # Klant filter
            klanten = await get_klanten(DB_PATH)
            klant_opties = {None: 'Alle klanten'}
            klant_opties.update({k.naam: k.naam for k in klanten})

            async def on_klant_filter(e):
                filter_klant['value'] = e.value
                await refresh_table()

            ui.select(klant_opties, value=None, label='Klant',
                      on_change=on_klant_filter).props('clearable').classes('w-44')

            # Status filter
            status_options = {'': 'Alle', 'concept': 'Concept', 'verstuurd': 'Verstuurd',
                              'verlopen': 'Verlopen', 'betaald': 'Betaald'}
            filter_status = {'value': ''}

            async def on_status_filter(e):
                filter_status['value'] = e.value
                await refresh_table()

            ui.select(status_options, value='', label='Status',
                      on_change=on_status_filter).classes('w-36')

            # Type filter
            type_options = {'': 'Alle types', 'factuur': 'Werkdag',
                            'anw': 'ANW/Dienst', 'vergoeding': 'Vergoeding'}
            filter_type = {'value': ''}

            async def on_type_filter(e):
                filter_type['value'] = e.value
                await refresh_table()

            ui.select(type_options, value='', label='Type',
                      on_change=on_type_filter).classes('w-36')

            ui.space()

            async def export_csv():
                facturen = await get_facturen(DB_PATH, jaar=jaar_select.value)
                if filter_klant['value']:
                    facturen = [f for f in facturen
                                if f.klant_naam == filter_klant['value']]
                facturen = _filter_facturen_by_status(
                    facturen, filter_status['value'])
                if filter_type['value']:
                    facturen = [f for f in facturen
                                if f.type == filter_type['value']]
                headers = ['Nummer', 'Datum', 'Klant', 'Type', 'Uren', 'Km',
                           'Bedrag', 'Status']
                type_labels_csv = {'factuur': 'Werkdag', 'anw': 'ANW',
                                   'vergoeding': 'Vergoeding'}
                status_labels = {'concept': 'Concept', 'verstuurd': 'Verstuurd',
                                 'verlopen': 'Verlopen', 'betaald': 'Betaald'}
                rows = [[f.nummer, f.datum, f.klant_naam,
                         type_labels_csv.get(f.type, f.type),
                         f.totaal_uren, f.totaal_km, f.totaal_bedrag,
                         status_labels.get(_display_status(f),
                                           f.status.capitalize())]
                        for f in facturen]
                csv_str = generate_csv(headers, rows)
                ui.download.content(
                    csv_str.encode('utf-8-sig'),
                    f'facturen_{jaar_select.value}.csv')

            ui.button(icon='download',
                      on_click=export_csv) \
                .props('flat round color=secondary size=sm') \
                .tooltip('Exporteer CSV')

        # KPI summary strip
        kpi_strip_container = ui.row().classes('w-full gap-4')

        # Bulk action toolbar (hidden when nothing selected)
        bulk_bar = ui.row().classes('w-full items-center gap-4')
        bulk_bar.set_visibility(False)
        bulk_bar_ref['ref'] = bulk_bar
        with bulk_bar:
            bulk_label = ui.label('')
            ui.button('Markeer betaald', icon='check_circle',
                      on_click=lambda: on_bulk_betaald()) \
                .props('color=positive outline')
            ui.button('Verwijder selectie', icon='delete',
                      on_click=lambda: on_bulk_delete()) \
                .props('color=negative outline')

        # Facturen table
        columns = [
            {'name': 'nummer', 'label': 'Nummer', 'field': 'nummer',
             'sortable': True, 'align': 'left', 'style': 'width: 100px'},
            {'name': 'datum', 'label': 'Datum', 'field': 'datum',
             'sortable': True, 'align': 'left', 'style': 'width: 100px'},
            {'name': 'klant', 'label': 'Klant', 'field': 'klant_naam',
             'sortable': True, 'align': 'left',
             'style': 'max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap'},
            {'name': 'uren', 'label': 'Uren', 'field': 'totaal_uren',
             'align': 'right', 'style': 'width: 50px'},
            {'name': 'bedrag', 'label': 'Bedrag', 'field': 'totaal_bedrag',
             'sortable': True, 'align': 'right', 'style': 'width: 90px'},
            {'name': 'status', 'label': 'Status', 'field': 'status',
             'sortable': True, 'align': 'center', 'style': 'width: 90px'},
            {'name': 'actions', 'label': '', 'field': 'actions',
             'align': 'center', 'style': 'width: 40px'},
        ]

        table = ui.table(
            columns=columns, rows=[], row_key='id',
            selection='multiple',
            pagination={'rowsPerPage': 20, 'sortBy': 'datum', 'descending': True,
                        'rowsPerPageOptions': [10, 20, 50, 0]},
        ).classes('w-full')
        table_ref['ref'] = table

        table.add_slot('body-cell-nummer', '''
            <q-td :props="props">
                <div class="row items-center no-wrap gap-1">
                    <q-icon
                        v-if="props.row.type === 'anw'"
                        name="nightlight"
                        size="xs"
                        color="info"
                    >
                        <q-tooltip>ANW-dienst</q-tooltip>
                    </q-icon>
                    <q-icon
                        v-else-if="props.row.type === 'vergoeding'"
                        name="receipt_long"
                        size="xs"
                        color="grey-6"
                    >
                        <q-tooltip>Vergoeding</q-tooltip>
                    </q-icon>
                    <q-icon
                        v-else
                        name="work"
                        size="xs"
                        color="teal"
                    >
                        <q-tooltip>Dagpraktijk</q-tooltip>
                    </q-icon>
                    <q-icon
                        v-if="props.row.bron === 'import'"
                        name="file_upload"
                        size="11px"
                        color="grey-5"
                    >
                        <q-tooltip>Geïmporteerd</q-tooltip>
                    </q-icon>
                    {{ props.row.nummer }}
                </div>
            </q-td>
        ''')

        table.add_slot('body-cell-datum', '''
            <q-td :props="props">
                {{ props.row.datum_fmt }}
            </q-td>
        ''')

        table.add_slot('body-cell-klant', '''
            <q-td :props="props" style="max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                {{ props.row.klant_naam }}
                <q-tooltip v-if="props.row.klant_naam && props.row.klant_naam.length > 25">
                    {{ props.row.klant_naam }}
                </q-tooltip>
            </q-td>
        ''')

        table.add_slot('body-cell-bedrag', '''
            <q-td :props="props" class="text-right">
                {{ props.row.bedrag_fmt }}
            </q-td>
        ''')

        table.add_slot('body-cell-status', '''
            <q-td :props="props">
                <q-badge v-if="props.row.status === 'betaald'" color="positive" label="Betaald" />
                <q-badge v-else-if="props.row.verlopen" color="negative" label="Verlopen">
                    <q-tooltip v-if="props.row.herinnering_datum">
                        Herinnering verstuurd op {{ props.row.herinnering_datum }}
                    </q-tooltip>
                </q-badge>
                <q-badge v-else-if="props.row.status === 'verstuurd'" color="info" label="Verstuurd" />
                <q-badge v-else color="grey-6" label="Concept" />
            </q-td>
        ''')

        table.add_slot('no-data', '''
            <q-tr><q-td colspan="100%" class="text-center q-pa-lg text-grey">
                Geen facturen gevonden.
            </q-td></q-tr>
        ''')

        table.add_slot('body-cell-actions', '''
            <q-td :props="props">
                <q-btn icon="more_vert" flat dense round size="sm"
                       color="grey-7">
                    <q-menu auto-close>
                        <q-list dense style="min-width: 200px">
                            <q-item clickable
                                @click="() => $parent.$emit('edit', props.row)">
                                <q-item-section side>
                                    <q-icon name="edit" size="xs"
                                            color="primary" />
                                </q-item-section>
                                <q-item-section>Bewerken</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.pdf_pad" clickable
                                @click="() => $parent.$emit('preview', props.row)">
                                <q-item-section side>
                                    <q-icon name="visibility" size="xs"
                                            color="primary" />
                                </q-item-section>
                                <q-item-section>Preview</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.pdf_pad" clickable
                                @click="() => $parent.$emit('download',
                                    props.row)">
                                <q-item-section side>
                                    <q-icon name="download" size="xs" />
                                </q-item-section>
                                <q-item-section>Download PDF</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.pdf_pad" clickable
                                @click="() => $parent.$emit('openfinder',
                                    props.row)">
                                <q-item-section side>
                                    <q-icon name="folder_open" size="xs" />
                                </q-item-section>
                                <q-item-section>Toon in Finder</q-item-section>
                            </q-item>
                            <q-separator />
                            <q-item v-if="props.row.status !== 'betaald'" clickable
                                @click="() => $parent.$emit('sendmail', props.row)">
                                <q-item-section side>
                                    <q-icon name="email" size="xs"
                                            color="info" />
                                </q-item-section>
                                <q-item-section>Verstuur via e-mail</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.verlopen" clickable
                                @click="() => $parent.$emit('sendherinnering', props.row)">
                                <q-item-section side>
                                    <q-icon name="notification_important" size="xs"
                                            color="warning" />
                                </q-item-section>
                                <q-item-section>Herinnering versturen</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.status === 'concept'" clickable
                                @click="() => $parent.$emit('markverstuurd', props.row)">
                                <q-item-section side>
                                    <q-icon name="send" size="xs"
                                            color="info" />
                                </q-item-section>
                                <q-item-section>Markeer als verstuurd</q-item-section>
                            </q-item>
                            <q-item v-if="props.row.status === 'verstuurd' || props.row.verlopen" clickable
                                @click="() => $parent.$emit('markbetaald',
                                    props.row)">
                                <q-item-section side>
                                    <q-icon name="check_circle" size="xs"
                                            color="positive" />
                                </q-item-section>
                                <q-item-section>
                                    Markeer betaald
                                </q-item-section>
                            </q-item>
                            <q-item v-if="props.row.status === 'betaald'" clickable
                                @click="() => $parent.$emit('markonbetaald',
                                    props.row)">
                                <q-item-section side>
                                    <q-icon name="undo" size="xs" />
                                </q-item-section>
                                <q-item-section>
                                    Markeer onbetaald
                                </q-item-section>
                            </q-item>
                            <q-separator />
                            <q-item clickable
                                @click="() => $parent.$emit('deletefactuur',
                                    props.row)">
                                <q-item-section side>
                                    <q-icon name="delete" size="xs"
                                            color="negative" />
                                </q-item-section>
                                <q-item-section class="text-negative">
                                    Verwijderen
                                </q-item-section>
                            </q-item>
                        </q-list>
                    </q-menu>
                </q-btn>
            </q-td>
        ''')

        # Summary
        summary_row = ui.row().classes('w-full justify-end gap-8 q-mt-sm')

        def update_bulk_bar():
            selected = table.selected
            n = len(selected) if selected else 0
            if n > 0:
                bulk_bar.set_visibility(True)
                bulk_label.text = f'{n} facturen geselecteerd'
            else:
                bulk_bar.set_visibility(False)

        table.on('selection', lambda _: update_bulk_bar())

        async def refresh_table():
            jaar = jaar_select.value
            facturen = await get_facturen(DB_PATH, jaar=jaar)
            if filter_klant['value']:
                facturen = [f for f in facturen
                            if f.klant_naam == filter_klant['value']]

            # Status filter
            facturen = _filter_facturen_by_status(
                facturen, filter_status['value'])

            # Type filter
            if filter_type['value']:
                facturen = [f for f in facturen
                            if f.type == filter_type['value']]

            rows = []
            totaal = 0
            openstaand = 0
            for f in facturen:
                is_verlopen = _display_status(f) == 'verlopen'
                try:
                    factuur_date = datetime.strptime(f.datum, '%Y-%m-%d').date()
                    vervaldatum_fmt = format_datum(
                        (factuur_date + timedelta(days=14)).isoformat())
                except (ValueError, TypeError):
                    vervaldatum_fmt = ''

                rows.append({
                    'id': f.id,
                    'nummer': f.nummer,
                    'datum': f.datum,
                    'datum_fmt': format_datum(f.datum),
                    'vervaldatum_fmt': vervaldatum_fmt,
                    'verlopen': is_verlopen,
                    'klant_id': f.klant_id,
                    'klant_naam': f.klant_naam,
                    'totaal_uren': f.totaal_uren,
                    'totaal_km': f.totaal_km,
                    'bedrag_fmt': format_euro(f.totaal_bedrag),
                    'totaal_bedrag': f.totaal_bedrag,
                    'status': f.status,
                    'betaald_datum': f.betaald_datum,
                    'pdf_pad': f.pdf_pad,
                    'type': f.type,
                    'bron': f.bron,
                    'herinnering_datum': format_datum(f.herinnering_datum) if f.herinnering_datum else '',
                })
                if f.status != 'concept':
                    totaal += f.totaal_bedrag
                if f.status != 'betaald' and f.status != 'concept':
                    openstaand += f.totaal_bedrag

            table.rows = rows
            table.selected.clear()
            table.update()
            update_bulk_bar()

            # Update KPI strip
            verlopen_bedrag = sum(r['totaal_bedrag'] for r in rows
                                  if r.get('verlopen') and r.get('status') == 'verstuurd')
            kpi_strip_container.clear()
            with kpi_strip_container:
                _kpi_style = 'font-variant-numeric: tabular-nums'
                with ui.card().classes('flex-1 q-pa-sm card-hero'):
                    ui.label('Gefactureerd').classes('text-caption text-grey-7')
                    ui.label(format_euro(totaal)).classes(
                        'text-subtitle1 text-weight-bold').style(_kpi_style)
                if openstaand > 0:
                    with ui.card().classes('flex-1 q-pa-sm card-hero'):
                        ui.label('Openstaand').classes(
                            'text-caption text-grey-7')
                        ui.label(format_euro(openstaand)) \
                            .style(f'color: var(--q-warning); {_kpi_style}') \
                            .classes('text-subtitle1 text-weight-bold')
                if verlopen_bedrag > 0:
                    with ui.card().classes('flex-1 q-pa-sm card-hero'):
                        ui.label('Verlopen').classes(
                            'text-caption text-grey-7')
                        ui.label(format_euro(verlopen_bedrag)) \
                            .style(f'color: var(--q-negative); {_kpi_style}') \
                            .classes('text-subtitle1 text-weight-bold')

            summary_row.clear()
            with summary_row:
                ui.label(f'{len(rows)} facturen').classes('text-body2')
                ui.label(f'Totaal: {format_euro(totaal)}') \
                    .classes('text-body1 text-weight-bold')
                if openstaand > 0:
                    ui.label(f'Openstaand: {format_euro(openstaand)}') \
                        .classes('text-body1 text-orange')

        async def on_mark_betaald(e):
            row = e.args
            with ui.dialog() as dialog, ui.card():
                ui.label(f"Factuur {row['nummer']} markeren als betaald?")
                ui.label(f"{row['klant_naam']} — {row['bedrag_fmt']}").classes('text-grey')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def do_mark():
                        await update_factuur_status(DB_PATH, factuur_id=row['id'],
                                                    status='betaald',
                                                    betaald_datum=date.today().isoformat())
                        dialog.close()
                        ui.notify(f"Factuur {row['nummer']} gemarkeerd als betaald",
                                  type='positive')
                        await refresh_table()

                    ui.button('Ja, betaald', on_click=do_mark).props('color=positive')
            dialog.open()

        async def on_mark_onbetaald(e):
            row = e.args
            with ui.dialog() as dialog, ui.card():
                ui.label(f"Factuur {row['nummer']} markeren als onbetaald?") \
                    .classes('text-h6')
                ui.label(f"{row['klant_naam']} — {row['bedrag_fmt']}") \
                    .classes('text-grey')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def do_mark():
                        await update_factuur_status(DB_PATH, factuur_id=row['id'],
                                                    status='verstuurd',
                                                    betaald_datum='')
                        dialog.close()
                        ui.notify(f"Factuur {row['nummer']} gemarkeerd als onbetaald",
                                  type='info')
                        await refresh_table()

                    ui.button('Ja, onbetaald', on_click=do_mark) \
                        .props('color=warning')
            dialog.open()

        async def on_delete_factuur(e):
            row = e.args
            with ui.dialog() as dialog, ui.card():
                ui.label(f"Factuur {row['nummer']} verwijderen?") \
                    .classes('text-h6')
                ui.label(f"{row['klant_naam']} — {row['bedrag_fmt']}") \
                    .classes('text-grey')
                ui.label(
                    'Werkdagen worden losgekoppeld en weer beschikbaar '
                    'voor facturatie.'
                ).classes('text-caption text-grey q-mt-sm')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def do_delete():
                        try:
                            await delete_factuur(DB_PATH, factuur_id=row['id'])
                        except ValueError as exc:
                            dialog.close()
                            ui.notify(str(exc), type='negative')
                            return
                        dialog.close()
                        ui.notify(f"Factuur {row['nummer']} verwijderd",
                                  type='positive')
                        await refresh_table()

                    ui.button('Verwijderen', on_click=do_delete) \
                        .props('color=negative')
            dialog.open()

        async def on_bulk_delete():
            selected = table.selected
            if not selected:
                return
            nummers = [r['nummer'] for r in selected]
            with ui.dialog() as dialog, ui.card():
                ui.label(f'{len(selected)} facturen verwijderen?') \
                    .classes('text-h6')
                ui.label(', '.join(nummers)).classes('text-grey')
                ui.label(
                    'Werkdagen worden losgekoppeld en weer beschikbaar '
                    'voor facturatie.'
                ).classes('text-caption text-grey q-mt-sm')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def do_bulk():
                        skipped = []
                        deleted = 0
                        for r in selected:
                            try:
                                await delete_factuur(DB_PATH, factuur_id=r['id'])
                                deleted += 1
                            except ValueError:
                                skipped.append(r['nummer'])
                        dialog.close()
                        if deleted:
                            ui.notify(f'{deleted} facturen verwijderd',
                                      type='positive')
                        if skipped:
                            ui.notify(
                                f"{', '.join(skipped)}: kan niet verwijderd "
                                f"worden (status is niet concept)",
                                type='negative',
                            )
                        await refresh_table()

                    ui.button('Verwijderen', on_click=do_bulk) \
                        .props('color=negative')
            dialog.open()

        async def on_bulk_betaald():
            selected = table.selected
            if not selected:
                return
            n = len(selected)
            with ui.dialog() as dialog, ui.card():
                ui.label(f'{n} facturen markeren als betaald?').classes('text-h6')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def do_bulk_betaald():
                        today = date.today().isoformat()
                        skipped = 0
                        for row in selected:
                            if row.get('status') == 'concept':
                                skipped += 1
                                continue
                            if row.get('status') != 'betaald':
                                await update_factuur_status(
                                    DB_PATH, factuur_id=row['id'],
                                    status='betaald',
                                    betaald_datum=today)
                        if skipped:
                            ui.notify(
                                f'{skipped} concept-facturen overgeslagen '
                                f'(verstuur eerst)',
                                type='info')
                        marked = n - skipped
                        dialog.close()
                        if marked > 0:
                            ui.notify(
                                f'{marked} facturen gemarkeerd als betaald',
                                type='positive')
                        elif not skipped:
                            ui.notify(
                                'Geen facturen gemarkeerd',
                                type='info')
                        await refresh_table()

                    ui.button('Ja, betaald', on_click=do_bulk_betaald) \
                        .props('color=positive')
            dialog.open()

        async def on_download(e):
            row = e.args
            pdf_path = row.get('pdf_pad', '')
            if pdf_path and Path(pdf_path).exists():
                ui.download(pdf_path)
            else:
                ui.notify('PDF niet gevonden', type='warning')

        async def on_open_finder(e):
            row = e.args
            pdf_path = row.get('pdf_pad', '')
            if pdf_path and Path(pdf_path).exists():
                await asyncio.to_thread(subprocess.run, ['open', '-R', pdf_path])
            else:
                ui.notify('PDF niet gevonden', type='warning')

        async def on_preview(e):
            row = e.args
            pdf_path = row.get('pdf_pad', '')
            if not pdf_path or not Path(pdf_path).exists():
                ui.notify('PDF niet gevonden', type='warning')
                return
            # Determine the correct static URL path
            p = Path(pdf_path)
            # PDFs can be in data/facturen/ or data/facturen/imports/
            try:
                rel = p.relative_to(PDF_DIR)
            except ValueError:
                ui.notify('PDF buiten facturenmap', type='warning')
                return
            url = f'/facturen-files/{rel}'
            with ui.dialog().classes('full-width') as dlg, \
                    ui.card().classes('w-full q-pa-none') \
                    .style('max-width: 900px; height: 85vh'):
                with ui.row().classes(
                    'w-full justify-between items-center q-pa-sm'
                ):
                    ui.label(f"Factuur {row['nummer']}").classes('text-h6')
                    ui.button(icon='close', on_click=dlg.close) \
                        .props('flat round dense')
                ui.html(
                    f'<iframe src="{url}" '
                    f'style="width:100%;height:calc(85vh - 56px);'
                    f'border:none"></iframe>',
                    sanitize=False,
                )
            dlg.open()

        async def on_edit(e):
            row = e.args
            if _should_use_builder(row):
                await _reopen_concept_in_builder(row)
            else:
                await open_edit_dialog(row)

        async def _reopen_concept_in_builder(row):
            """Reopen a concept factuur in the invoice builder for editing.

            The old concept is NOT deleted upfront — it stays in the DB
            as a safety net. The builder receives replacing_factuur_id
            and only deletes the old concept on successful save.
            """
            old_nummer = row['nummer']
            old_klant_id = row.get('klant_id')

            # Find linked werkdag IDs + regels_json for pre-selection
            async with get_db_ctx(DB_PATH) as conn:
                cur = await conn.execute(
                    "SELECT id FROM werkdagen WHERE factuurnummer = ?",
                    (old_nummer,))
                wd_rows = await cur.fetchall()
                cur2 = await conn.execute(
                    "SELECT regels_json FROM facturen WHERE id = ?",
                    (row['id'],))
                frow = await cur2.fetchone()
            werkdag_ids = [r['id'] for r in wd_rows]
            regels_json = frow['regels_json'] if frow else ''

            await open_invoice_builder(
                on_save=refresh_table,
                pre_selected_werkdag_ids=werkdag_ids or None,
                pre_nummer=old_nummer,
                pre_klant_id=old_klant_id,
                replacing_factuur_id=row['id'],
                pre_regels_json=regels_json,
            )

        async def open_edit_dialog(row):
            """Open dialog to edit factuur details."""
            klanten = await get_klanten(DB_PATH, alleen_actief=False)
            klant_options = {k.id: k.naam for k in klanten}
            upload_file = {}

            with ui.dialog() as dialog, \
                    ui.card().classes('w-full max-w-lg q-pa-md'):
                ui.label('Factuur bewerken').classes('text-h6 q-mb-md')

                # Nummer (read-only)
                with ui.row().classes('w-full items-center gap-2'):
                    ui.label('Factuurnummer:').classes(
                        'text-subtitle2 text-grey-8')
                    ui.label(row['nummer']).classes('text-subtitle2')
                    type_labels = {'factuur': 'Werkdag', 'anw': 'ANW',
                                   'vergoeding': 'Vergoeding'}
                    type_colors = {'factuur': 'teal', 'anw': 'info',
                                   'vergoeding': 'amber-8'}
                    type_val = row.get('type', 'factuur')
                    ui.badge(type_labels.get(type_val, type_val),
                             color=type_colors.get(type_val, 'grey')).classes('q-ml-sm')

                ui.separator().classes('q-my-sm')

                # Datum
                edit_datum = date_input('Factuurdatum', value=row['datum'])

                # Klant
                edit_klant = ui.select(
                    klant_options, label='Klant',
                    value=row.get('klant_id'),
                    with_input=True,
                ).classes('w-full')

                # Bedrag
                edit_bedrag = ui.number(
                    'Totaalbedrag (€)', value=row['totaal_bedrag'],
                    format='%.2f',
                ).classes('w-full')

                # Status
                ui.separator().classes('q-my-sm')
                with ui.row().classes('w-full items-center gap-4'):
                    edit_status = ui.select(
                        {'concept': 'Concept', 'verstuurd': 'Verstuurd',
                         'betaald': 'Betaald'},
                        label='Status', value=row['status'],
                    ).classes('w-40')
                    edit_betaald_datum = date_input(
                        'Betaaldatum',
                        value=row.get('betaald_datum', ''),
                    ).classes('w-40')
                    edit_betaald_datum.bind_visibility_from(
                        edit_status, 'value',
                        backward=lambda v: v == 'betaald')

                # PDF section
                ui.separator().classes('q-my-sm')
                ui.label('Document').classes(
                    'text-caption').style('color: #64748B')
                existing_pdf = row.get('pdf_pad', '')
                pdf_removed = {'value': False}

                if existing_pdf and Path(existing_pdf).exists():
                    pdf_row = ui.row().classes('items-center gap-2')
                    with pdf_row:
                        ui.icon('attach_file', color='primary')
                        ui.label(
                            Path(existing_pdf).name
                        ).classes('text-body2')
                        ui.button(
                            'Download', icon='download',
                            on_click=lambda: ui.download(existing_pdf),
                        ).props('flat dense size=sm')

                        def remove_pdf():
                            pdf_removed['value'] = True
                            pdf_row.set_visibility(False)
                            ui.notify(
                                'PDF wordt verwijderd bij opslaan',
                                type='info')

                        ui.button(
                            'Verwijder', icon='delete',
                            on_click=remove_pdf,
                        ).props('flat dense size=sm color=negative')

                ui.upload(
                    label='Nieuwe PDF uploaden', auto_upload=True,
                    on_upload=lambda e: upload_file.update({'event': e}),
                    max_file_size=10_000_000,
                ).classes('w-full').props(
                    'flat bordered accept=".pdf"')

                # Action buttons
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button(
                        'Annuleren', on_click=dialog.close,
                    ).props('flat')

                    async def opslaan():
                        if not edit_klant.value:
                            ui.notify('Selecteer een klant', type='warning')
                            return
                        try:
                            await _do_opslaan()
                        except Exception as exc:
                            ui.notify(f'Fout bij opslaan: {exc}',
                                      type='negative')

                    async def _do_opslaan():
                        # Update main fields
                        new_bedrag = float(edit_bedrag.value or 0)
                        kwargs = {
                            'datum': edit_datum.value,
                            'klant_id': edit_klant.value,
                            'totaal_bedrag': new_bedrag,
                        }
                        # Vergoeding: keep regels_json in sync with the
                        # new total so the PDF regenerated later shows
                        # the correct amount (bug: stale regels_json
                        # caused PDFs to diverge from the DB).
                        if (row.get('type') == 'vergoeding'
                                and abs(new_bedrag
                                        - row.get('totaal_bedrag', 0)) > 0.005):
                            async with get_db_ctx(DB_PATH) as _conn:
                                _cur = await _conn.execute(
                                    "SELECT regels_json FROM facturen "
                                    "WHERE id = ?", (row['id'],))
                                _rj = await _cur.fetchone()
                            kwargs['regels_json'] = _rebuild_vergoeding_regels_json(
                                _rj['regels_json'] if _rj else '',
                                new_bedrag)
                        await update_factuur(
                            DB_PATH, factuur_id=row['id'], **kwargs)

                        # Handle status change (cascades to werkdagen)
                        new_status = edit_status.value
                        try:
                            if new_status != row['status']:
                                betaald_datum = ''
                                if new_status == 'betaald':
                                    betaald_datum = (edit_betaald_datum.value
                                                     or date.today().isoformat())
                                await update_factuur_status(
                                    DB_PATH, factuur_id=row['id'],
                                    status=new_status,
                                    betaald_datum=betaald_datum)
                            elif (new_status == 'betaald'
                                  and edit_betaald_datum.value
                                  != row.get('betaald_datum', '')):
                                await update_factuur_status(
                                    DB_PATH, factuur_id=row['id'],
                                    status='betaald',
                                    betaald_datum=edit_betaald_datum.value)
                        except ValueError as ex:
                            ui.notify(str(ex), type='negative')
                            return

                        # Handle PDF removal
                        if pdf_removed['value'] and existing_pdf:
                            await update_factuur(
                                DB_PATH, factuur_id=row['id'],
                                pdf_pad='')
                            p = Path(existing_pdf)
                            if p.exists():
                                await asyncio.to_thread(p.unlink)

                        # Handle PDF upload
                        if upload_file.get('event'):
                            evt = upload_file['event']
                            import_dir = PDF_DIR / 'imports'
                            import_dir.mkdir(parents=True, exist_ok=True)
                            safe_name = Path(
                                evt.file.name).name.replace(' ', '_')
                            filename = (
                                f'factuur_{row["id"]}_{safe_name}')
                            filepath = import_dir / filename
                            content = await evt.file.read()
                            await asyncio.to_thread(filepath.write_bytes, content)
                            await update_factuur(
                                DB_PATH, factuur_id=row['id'],
                                pdf_pad=str(filepath))

                        ui.notify(
                            f'Factuur {row["nummer"]} bijgewerkt',
                            type='positive')
                        dialog.close()
                        await refresh_table()

                    ui.button(
                        'Opslaan', on_click=opslaan,
                    ).props('color=primary')
            dialog.open()

        async def on_mark_verstuurd(e):
            row = e.args
            with ui.dialog() as dialog, ui.card():
                ui.label(f"Factuur {row['nummer']} markeren als verstuurd?")
                ui.label(f"{row['klant_naam']} — {row['bedrag_fmt']}").classes('text-grey')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren', on_click=dialog.close).props('flat')

                    async def do_mark():
                        await update_factuur_status(
                            DB_PATH, factuur_id=row['id'],
                            status='verstuurd')
                        dialog.close()
                        ui.notify(
                            f"Factuur {row['nummer']} gemarkeerd als verstuurd",
                            type='positive')
                        await refresh_table()

                    ui.button('Ja, verstuurd', on_click=do_mark).props('color=info')
            dialog.open()

        async def on_send_mail(e):
            """Send invoice via email using macOS Mail.app, then mark as verstuurd."""
            import json as _json
            row = e.args
            pdf_path = row.get('pdf_pad', '')
            nummer = row['nummer']

            # Fetch shared data once (used for both PDF generation and email)
            all_klanten = await get_klanten(DB_PATH, alleen_actief=False)
            bg = await get_bedrijfsgegevens(DB_PATH)

            # Auto-generate PDF for concepts that don't have one yet
            if not pdf_path or not Path(pdf_path).exists():
                async with get_db_ctx(DB_PATH) as conn:
                    cur = await conn.execute(
                        "SELECT regels_json, betaallink FROM facturen WHERE id = ?",
                        (row['id'],))
                    frow = await cur.fetchone()
                regels_json = frow['regels_json'] if frow else ''
                if not regels_json:
                    ui.notify('Geen factuurregels — open de factuur eerst via Bewerken',
                              type='warning')
                    return
                regels_data = _json.loads(regels_json)
                line_items = regels_data.get('line_items', [])
                regels = _build_regels(line_items)

                # Get klant info for PDF
                klant_obj = next(
                    (k for k in all_klanten if k.id == row.get('klant_id')), None)
                klant_fields = regels_data.get('klant_fields', {})
                if not klant_fields and klant_obj:
                    klant_fields = {
                        'naam': klant_obj.naam, 'adres': klant_obj.adres or '',
                        'postcode': getattr(klant_obj, 'postcode', ''),
                        'plaats': getattr(klant_obj, 'plaats', ''),
                    }

                bg_dict = {}
                if bg:
                    for fld in ('bedrijfsnaam', 'naam', 'adres',
                                'postcode_plaats', 'kvk', 'iban',
                                'telefoon', 'email'):
                        bg_dict[fld] = getattr(bg, fld, '') or ''

                # QR code
                qr_file = DB_PATH.parent / 'facturen' / f'{nummer}_qr.png'
                gen_qr = str(qr_file) if qr_file.exists() else ''

                factuur_datum = row.get('datum', '') or date.today().isoformat()
                pdf_dir = DB_PATH.parent / 'facturen'
                try:
                    pdf_path_obj = await asyncio.to_thread(
                        generate_invoice,
                        nummer, klant_fields, [], pdf_dir,
                        factuur_datum=factuur_datum,
                        bedrijfsgegevens=bg_dict,
                        pre_regels=regels,
                        qr_path=gen_qr,
                    )
                    pdf_path = str(pdf_path_obj)
                    await update_factuur(DB_PATH, row['id'], pdf_pad=pdf_path)
                    # Archive to SynologyDrive (best-effort)
                    await asyncio.to_thread(
                        archive_factuur_pdf, pdf_path_obj,
                        factuur_type=row.get('type', 'factuur'),
                        factuur_datum=row.get('datum', ''))
                except Exception as ex:
                    ui.notify(f'PDF generatie mislukt: {ex}', type='negative')
                    return

            # Get klant email if available
            klant_id = row.get('klant_id')
            klant_email = ''
            if klant_id:
                klant = next((k for k in all_klanten if k.id == klant_id), None)
                if klant and hasattr(klant, 'email'):
                    klant_email = klant.email or ''

            bedrag = format_euro(row['totaal_bedrag'])
            iban = bg.iban if bg else ''
            bedrijfsnaam = bg.bedrijfsnaam if bg else ''
            naam = bg.naam if bg else ''
            telefoon = bg.telefoon if bg else ''
            bg_email = bg.email if bg else ''

            # Fetch betaallink from DB
            betaallink = ''
            async with get_db_ctx(DB_PATH) as conn:
                cur = await conn.execute(
                    "SELECT betaallink FROM facturen WHERE id = ?", (row['id'],))
                r = await cur.fetchone()
                if r and r['betaallink']:
                    betaallink = r['betaallink']

            subject = f'Factuur {nummer}'
            body = _build_mail_body(
                nummer, bedrag, iban, bedrijfsnaam, naam, telefoon, bg_email, betaallink)

            pdf_path_abs = str(Path(pdf_path).resolve())

            try:
                result = await asyncio.to_thread(
                    open_mail_with_attachment,
                    to=klant_email, subject=subject, body=body,
                    attachment_path=pdf_path_abs,
                )
                if result.returncode != 0:
                    err = result.stderr.decode().strip() if result.stderr else 'onbekende fout'
                    ui.notify(f'Mail.app fout: {err}', type='negative')
                    return

                # Mark as verstuurd if currently concept
                if row.get('status') == 'concept':
                    await update_factuur_status(
                        DB_PATH, factuur_id=row['id'], status='verstuurd')

                ui.notify(f'Factuur {nummer} geopend in Mail.app', type='positive')
                await refresh_table()
            except subprocess.TimeoutExpired:
                ui.notify('Mail.app reageerde niet — probeer handmatig', type='warning')
            except Exception as ex:
                ui.notify(f'Fout bij openen Mail.app: {ex}', type='negative')

        async def on_send_herinnering(e):
            """Send reminder email for overdue invoice via macOS Mail.app."""
            row = e.args
            pdf_path = row.get('pdf_pad', '')
            nummer = row['nummer']

            if not pdf_path or not Path(pdf_path).exists():
                ui.notify('Geen PDF gevonden voor deze factuur', type='warning')
                return

            all_klanten = await get_klanten(DB_PATH, alleen_actief=False)
            bg = await get_bedrijfsgegevens(DB_PATH)
            klant_obj = next(
                (k for k in all_klanten if k.id == row.get('klant_id')), None)
            klant_email = (klant_obj.email or '') if klant_obj and hasattr(klant_obj, 'email') else ''

            bedrag = format_euro(row['totaal_bedrag'])
            datum_fmt = format_datum(row['datum'])
            iban = bg.iban if bg else ''
            bedrijfsnaam = bg.bedrijfsnaam if bg else ''
            naam = bg.naam if bg else ''
            telefoon = bg.telefoon if bg else ''
            bg_email_addr = bg.email if bg else ''

            betaallink = ''
            async with get_db_ctx(DB_PATH) as conn:
                cur = await conn.execute(
                    "SELECT betaallink FROM facturen WHERE id = ?", (row['id'],))
                r = await cur.fetchone()
                if r and r['betaallink']:
                    betaallink = r['betaallink']

            subject = f'Herinnering: Factuur {nummer}'
            body = _build_herinnering_body(
                nummer, bedrag, datum_fmt, iban, bedrijfsnaam, naam,
                telefoon, bg_email_addr, betaallink)

            pdf_path_abs = str(Path(pdf_path).resolve())

            try:
                result = await asyncio.to_thread(
                    open_mail_with_attachment,
                    to=klant_email, subject=subject, body=body,
                    attachment_path=pdf_path_abs,
                )
                if result.returncode != 0:
                    err = result.stderr.decode().strip() if result.stderr else 'onbekende fout'
                    ui.notify(f'Mail.app fout: {err}', type='negative')
                    return

                # Store herinnering date
                async with get_db_ctx(DB_PATH) as conn:
                    await conn.execute(
                        "UPDATE facturen SET herinnering_datum = ? WHERE id = ?",
                        (date.today().isoformat(), row['id']))
                    await conn.commit()

                ui.notify(f'Herinnering voor {nummer} geopend in Mail.app',
                          type='positive')
                await refresh_table()
            except subprocess.TimeoutExpired:
                ui.notify('Mail.app reageerde niet — probeer handmatig',
                          type='warning')
            except Exception as ex:
                ui.notify(f'Fout bij openen Mail.app: {ex}', type='negative')

        table.on('markbetaald', on_mark_betaald)
        table.on('markonbetaald', on_mark_onbetaald)
        table.on('markverstuurd', on_mark_verstuurd)
        table.on('sendmail', on_send_mail)
        table.on('sendherinnering', on_send_herinnering)
        table.on('deletefactuur', on_delete_factuur)
        table.on('download', on_download)
        table.on('edit', on_edit)
        table.on('openfinder', on_open_finder)
        table.on('preview', on_preview)

        async def open_import_dialog():
            """Open dialog to import facturen from PDF files."""
            parsed_items = []

            klanten = await get_klanten(DB_PATH, alleen_actief=False)
            klant_lookup = {k.naam: k.id for k in klanten}
            klant_options = {k.id: k.naam for k in klanten}

            # Load existing factuurnummers + (klant, datum, bedrag)
            # fingerprints for dedup. The fingerprint catches PDFs
            # re-exported with a different layout or invoices re-sent
            # under a new nummer (rare but possible).
            async with get_db_ctx(DB_PATH) as conn:
                cursor = await conn.execute(
                    "SELECT nummer, klant_id, datum, totaal_bedrag "
                    "FROM facturen")
                _existing_rows = await cursor.fetchall()
            existing_nummers = {r['nummer'] for r in _existing_rows}
            existing_signatures: set[tuple] = {
                (r['klant_id'], r['datum'],
                 round(float(r['totaal_bedrag'] or 0), 2))
                for r in _existing_rows
            }

            with ui.dialog() as dlg, ui.card().classes(
                'w-full max-w-2xl q-pa-none'
            ):
                # Header with close button
                with ui.row().classes(
                    'w-full items-center q-pa-md q-pb-sm'
                ):
                    ui.label('Facturen importeren uit PDF').classes(
                        'text-h6')
                    ui.space()
                    ui.button(icon='close', on_click=dlg.close) \
                        .props('flat round dense')

                with ui.column().classes('w-full q-px-md q-pb-md gap-3'):
                    opt_werkdagen = {'value': True}
                    opt_betaald = {'value': True}

                    async def handle_upload(e: events.UploadEventArguments):
                        content = await e.file.read()
                        filename = e.file.name

                        with tempfile.NamedTemporaryFile(
                            suffix='.pdf', delete=False,
                        ) as tmp:
                            tmp.write(content)
                            tmp_path = tmp.name

                        try:
                            text = await asyncio.to_thread(
                                extract_pdf_text, tmp_path)
                            inv_type = detect_invoice_type(text)

                            if inv_type == 'dagpraktijk':
                                parsed = parse_dagpraktijk_text(
                                    text, filename)
                            elif inv_type == 'anw':
                                parsed = parse_anw_text(text, filename)
                            else:
                                parsed_items.append({
                                    '_type': 'unknown',
                                    '_filename': filename,
                                    '_status': 'fout',
                                    '_error': 'Niet herkend PDF-formaat',
                                })
                                render_preview()
                                return

                            parsed['_type'] = inv_type
                            parsed['_filename'] = filename
                            parsed['_content'] = content

                            # Klant resolution first — we need klant_id
                            # to compute the fuzzy dedup signature.
                            if inv_type == 'dagpraktijk':
                                suffix = (
                                    filename.split('_', 1)[1]
                                    .replace('.pdf', '')
                                    if '_' in filename else None)
                                db_naam, klant_id = resolve_klant(
                                    parsed.get('klant_name'), suffix,
                                    klant_lookup)
                            else:
                                db_naam, klant_id = resolve_anw_klant(
                                    filename, klant_lookup)

                            parsed['_klant_naam'] = db_naam
                            parsed['_klant_id'] = klant_id

                            # Dedup: reject missing nummer, known nummer,
                            # or matching (klant,datum,bedrag) fingerprint
                            status_, reason = _classify_import_item(
                                parsed.get('factuurnummer'),
                                klant_id,
                                parsed.get('factuurdatum'),
                                parsed.get('totaal_bedrag'),
                                existing_nummers,
                                existing_signatures,
                            )
                            parsed['_status'] = status_
                            if reason:
                                parsed['_error'] = reason

                            parsed_items.append(parsed)
                            render_preview()
                        except Exception as ex:
                            parsed_items.append({
                                '_type': 'error', '_filename': filename,
                                '_status': 'fout', '_error': str(ex),
                            })
                            render_preview()
                        finally:
                            await asyncio.to_thread(Path(tmp_path).unlink)

                    # Upload zone — compact dropzone style
                    ui.upload(
                        multiple=True, on_upload=handle_upload,
                        auto_upload=True,
                    ).props(
                        'accept=".pdf" flat bordered color=teal '
                        'label="Klik of sleep PDF-bestanden hierheen"'
                    ).classes('w-full').style(
                        'border-style: dashed; border-radius: 8px'
                    )

                    preview_container = ui.column().classes(
                        'w-full gap-2')
                    bottom_container = ui.column().classes('w-full')

                def render_preview():
                    preview_container.clear()
                    bottom_container.clear()

                    if not parsed_items:
                        return

                    with preview_container:
                        for i, item in enumerate(parsed_items):
                            status = item.get('_status', 'fout')
                            inv_type = item.get('_type', '?')

                            # Left border color by status
                            if status == 'nieuw':
                                border_color = 'var(--q-positive)'
                                bg = 'white'
                            elif status == 'duplicaat':
                                border_color = '#9e9e9e'
                                bg = '#fafafa'
                            else:
                                border_color = 'var(--q-negative)'
                                bg = '#fff5f5'

                            with ui.card().classes(
                                'w-full q-pa-sm'
                            ).style(
                                f'border-left: 3px solid {border_color}; '
                                f'box-shadow: none; background: {bg}'
                            ):
                                # Row 1: badges + nummer + bedrag
                                with ui.row().classes(
                                    'w-full items-center gap-2'
                                ):
                                    if status == 'nieuw':
                                        ui.badge('Nieuw',
                                                 color='positive')
                                    elif status == 'duplicaat':
                                        ui.badge('Duplicaat',
                                                 color='grey')
                                    else:
                                        ui.badge('Fout',
                                                 color='negative')

                                    type_label = (
                                        'Dagpraktijk'
                                        if inv_type == 'dagpraktijk'
                                        else 'ANW'
                                        if inv_type == 'anw' else '?')
                                    ui.badge(
                                        type_label,
                                        color=('info'
                                               if inv_type == 'anw'
                                               else 'teal-4'),
                                    ).props('outline')

                                    nummer = item.get(
                                        'factuurnummer', '-')
                                    ui.label(nummer).classes(
                                        'text-weight-bold')

                                    ui.space()

                                    bedrag = item.get('totaal_bedrag')
                                    if bedrag:
                                        ui.label(
                                            format_euro(bedrag)
                                        ).classes('text-weight-bold')

                                    n_items = len(
                                        item.get('line_items', []))
                                    if n_items:
                                        ui.badge(
                                            f'{n_items} dag'
                                            f'{"en" if n_items != 1 else ""}',
                                            color='info')

                                # Row 2: datum + klant
                                with ui.row().classes(
                                    'w-full items-center gap-2 '
                                    'q-mt-xs'
                                ):
                                    datum = item.get(
                                        'factuurdatum', '')
                                    if datum:
                                        ui.label(
                                            format_datum(datum)
                                        ).classes(
                                            'text-caption text-grey-7')

                                    klant_naam = item.get(
                                        '_klant_naam')
                                    if klant_naam:
                                        ui.label(klant_naam).classes(
                                            'text-caption text-grey-7')
                                    elif status == 'nieuw':
                                        sel = ui.select(
                                            klant_options,
                                            label='Klant',
                                            with_input=True,
                                        ).classes('w-52').props(
                                            'dense')

                                        def _make_klant_handler(
                                            idx, select
                                        ):
                                            def handler(_):
                                                parsed_items[idx][
                                                    '_klant_id'
                                                ] = select.value
                                                parsed_items[idx][
                                                    '_klant_naam'
                                                ] = klant_options.get(
                                                    select.value)
                                                render_bottom()
                                            return handler
                                        sel.on_value_change(
                                            _make_klant_handler(i, sel))

                                    if status == 'fout':
                                        ui.label(
                                            item.get('_error', 'Fout')
                                        ).classes(
                                            'text-caption text-negative')

                    render_bottom()

                def render_bottom():
                    bottom_container.clear()
                    new_count = sum(
                        1 for it in parsed_items
                        if it.get('_status') == 'nieuw'
                        and it.get('_klant_id'))
                    dup_count = sum(
                        1 for it in parsed_items
                        if it.get('_status') == 'duplicaat')
                    unresolved = sum(
                        1 for it in parsed_items
                        if it.get('_status') == 'nieuw'
                        and not it.get('_klant_id'))

                    with bottom_container:
                        if not parsed_items:
                            return

                        ui.separator().classes('q-my-sm')

                        # Options row
                        with ui.row().classes(
                            'w-full items-center gap-6'
                        ):
                            cb_wd = ui.checkbox(
                                'Werkdagen aanmaken',
                                value=opt_werkdagen['value'],
                            )
                            cb_wd.on_value_change(
                                lambda e: opt_werkdagen.update(
                                    value=e.value))
                            cb_bt = ui.checkbox(
                                'Markeer als betaald',
                                value=opt_betaald['value'],
                            )
                            cb_bt.on_value_change(
                                lambda e: opt_betaald.update(
                                    value=e.value))

                        # Summary + action buttons
                        with ui.row().classes(
                            'w-full items-center gap-4 q-mt-sm'
                        ):
                            if dup_count:
                                ui.label(
                                    f'{dup_count} '
                                    f'{"duplicaten" if dup_count > 1 else "duplicaat"}'
                                    f' overgeslagen'
                                ).classes('text-caption text-grey')
                            if unresolved:
                                ui.label(
                                    f'{unresolved} zonder klant'
                                ).classes(
                                    'text-caption text-warning')
                            ui.space()
                            ui.button(
                                'Annuleren', on_click=dlg.close,
                            ).props('flat')
                            if new_count > 0:
                                btn = ui.button(
                                    f'Importeer {new_count} '
                                    f'factu{"ren" if new_count != 1 else "ur"}',
                                    icon='file_download',
                                    on_click=do_import,
                                ).props('color=primary')
                                import_btn_ref['ref'] = btn

                import_btn_ref = {'ref': None}

                async def do_import():
                    """Import all new, resolved items."""
                    # Disable button to prevent double-click
                    if import_btn_ref['ref']:
                        import_btn_ref['ref'].disable()

                    imported = 0
                    errors = 0
                    werkdagen_created = 0
                    werkdagen_linked = 0

                    # Ensure PDF storage dirs exist
                    import_dir = PDF_DIR / 'imports'
                    import_dir.mkdir(parents=True, exist_ok=True)

                    for item in parsed_items:
                        if item.get('_status') != 'nieuw':
                            continue
                        klant_id = item.get('_klant_id')
                        if not klant_id:
                            continue

                        nummer = item.get('factuurnummer', '')

                        # Belt-and-braces: reject empty nummer even if
                        # the classifier would have caught it. Prevents
                        # an accidental future regression from writing
                        # a factuur with nummer=''.
                        if not nummer:
                            continue
                        # Guard: skip if already imported (double-click / dup)
                        if nummer in existing_nummers:
                            continue

                        try:
                            datum = item.get('factuurdatum', '')
                            inv_jaar = int(datum[:4]) if len(datum) >= 4 else 0
                            fp_inv = await get_fiscale_params(
                                DB_PATH, inv_jaar) if inv_jaar else None
                            inv_km_tarief = (
                                fp_inv.km_tarief if fp_inv and fp_inv.km_tarief
                                else 0.23)
                            bedrag = item.get('totaal_bedrag', 0)
                            inv_type = item.get('_type', 'factuur')
                            line_items = item.get('line_items', [])

                            # Calculate totals from line items
                            totaal_uren = sum(
                                li.get('uren', 0) for li in line_items)
                            totaal_km = sum(
                                li.get('km', 0) for li in line_items)

                            # Save PDF file
                            safe_name = (nummer.replace('/', '-')
                                         if nummer else 'unknown')
                            pdf_dest = import_dir / f'{safe_name}.pdf'
                            content = item.get('_content', b'')
                            if content and not pdf_dest.exists():
                                await asyncio.to_thread(pdf_dest.write_bytes, content)
                            pdf_pad = str(pdf_dest) if content else ''

                            # Create factuur record
                            ftype = 'anw' if inv_type == 'anw' else 'factuur'
                            await add_factuur(
                                DB_PATH,
                                nummer=nummer,
                                klant_id=klant_id,
                                datum=datum,
                                totaal_uren=totaal_uren,
                                totaal_km=totaal_km,
                                totaal_bedrag=bedrag,
                                pdf_pad=pdf_pad,
                                status='betaald' if opt_betaald['value'] else 'verstuurd',
                                betaald_datum=(datum if opt_betaald['value']
                                              else ''),
                                type=ftype,
                                bron='import',
                            )

                            # Track for dedup
                            existing_nummers.add(nummer)
                            existing_signatures.add(
                                (klant_id, datum, round(float(bedrag), 2)))
                            imported += 1

                            # Create or link werkdagen
                            if opt_werkdagen['value'] and line_items:
                                async with get_db_ctx(DB_PATH) as conn:
                                    for li in line_items:
                                        li_datum = li.get('datum', '')
                                        if not li_datum:
                                            continue

                                        cur = await conn.execute(
                                            "SELECT id FROM werkdagen "
                                            "WHERE datum = ? AND klant_id = ?",
                                            (li_datum, klant_id),
                                        )
                                        existing_wd = await cur.fetchone()

                                        if existing_wd:
                                            await link_werkdagen_to_factuur(
                                                DB_PATH,
                                                werkdag_ids=[existing_wd[0]],
                                                factuurnummer=nummer,
                                            )
                                            werkdagen_linked += 1
                                        else:
                                            wd_kwargs = _line_item_to_werkdag_kwargs(
                                                li, inv_type, inv_km_tarief)
                                            await add_werkdag(
                                                DB_PATH,
                                                datum=li_datum,
                                                klant_id=klant_id,
                                                factuurnummer=nummer,
                                                **wd_kwargs,
                                            )
                                            werkdagen_created += 1

                        except Exception as ex:
                            errors += 1
                            ui.notify(
                                f'Fout bij {nummer}: {ex}',
                                type='negative')

                    dlg.close()

                    parts = [f'{imported} facturen geïmporteerd']
                    if werkdagen_created:
                        parts.append(
                            f'{werkdagen_created} werkdagen aangemaakt')
                    if werkdagen_linked:
                        parts.append(
                            f'{werkdagen_linked} werkdagen gekoppeld')
                    if errors:
                        parts.append(f'{errors} fouten')
                    ui.notify(', '.join(parts),
                              type='positive' if not errors else 'warning')
                    await refresh_table()

            dlg.open()

        jaar_select.on_value_change(lambda _: refresh_table())
        await refresh_table()

        # Auto-open invoice builder if coming from werkdagen with pre-selected IDs
        pre_selected = app.storage.user.pop('selected_werkdagen', None)
        if pre_selected:
            await open_invoice_builder(
                on_save=refresh_table,
                pre_selected_werkdag_ids=pre_selected)
