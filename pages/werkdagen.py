"""Werkdagen pagina — uren/km registratie met tabel en dialog.

Layout-port uit redesign/design_handoff_boekhouding_redesign/source/pages.jsx
(zie docs/superpowers/specs/2026-04-17-werkdagen-sheet-port-design.md).
Behoudt ui.table voor sort/pagination, voegt urencriterium-subtitle,
segmented filter-tabs, code-chip, locatie-subline, sticky bulk-bar en
multi-klant picker toe.
"""

import asyncio
from nicegui import app, ui
from components.layout import create_layout, page_title
from components.utils import format_euro, format_datum, generate_csv
from components.werkdag_form import open_werkdag_dialog
from database import (
    get_werkdagen, get_klanten, delete_werkdag, DB_PATH,
)
from datetime import date
from components.shared_ui import year_options, confirm_dialog

MAANDEN = {
    0: 'Alle', 1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'Mei', 6: 'Jun',
    7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Okt', 11: 'Nov', 12: 'Dec',
}

# Segment-filter waarden — gedrag uit de spec
SEG_ALL = 'all'
SEG_UNINVOICED = 'uninvoiced'
SEG_ANW = 'anw'

# Code → leesbare afkorting voor de chip (max 7 chars)
_CODE_LABELS = {
    'WERKDAG': 'DAG',
    'WEEKEND_DAG': 'WKD',
    'AVOND': 'AV',
    'NACHT': 'NA',
    'ACHTERWACHT': 'ACH',
    'ANW_AVOND': 'ANW-AV',
    'ANW_NACHT': 'ANW-NA',
    'ANW_WEEKEND': 'ANW-WE',
    'CONGRES': 'CON',
    'OPLEIDING': 'OPL',
    'OVERIG_ZAK': 'OVG',
}

# Code → chip-kleurklasse. Primair signaal is urennorm (telt mee voor
# 1.225-uur eis), secundair de code-prefix. Pure helper, unit-getest.
def _chip_class_for(code: str, urennorm: bool) -> str:
    if urennorm:
        return 'pos'
    if code.startswith('ANW_'):
        return 'info'
    if code == 'ACHTERWACHT':
        return 'neutral'
    return 'warn'  # CONGRES / OPLEIDING / OVERIG_ZAK / overig zonder urennorm


def _segment_matches(w, segment: str) -> bool:
    """Filter werkdagen op het actieve segment-tab."""
    if segment == SEG_UNINVOICED:
        return not w.factuurnummer
    if segment == SEG_ANW:
        return w.code.startswith('ANW_')
    return True  # SEG_ALL


@ui.page('/werkdagen')
async def werkdagen_page():
    create_layout('Werkdagen', '/werkdagen')

    current_year = date.today().year
    klanten = await get_klanten(DB_PATH)
    klant_options = {0: 'Alle'} | {k.id: k.naam for k in klanten}

    # State
    table_ref = {'ref': None}
    summary_label = {'ref': None}
    subtitle_label = {'ref': None}
    seg_state = {'value': SEG_ALL}
    seg_buttons = {}  # key -> ui.element (for class toggling)

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):

        # --- Header met subtitle ---
        with ui.row().classes('w-full items-end'):
            with ui.column().classes('gap-0'):
                page_title('Werkdagen')
                subtitle_label['ref'] = ui.label('').classes('page-sub')
            ui.space()
            with ui.row().classes('items-center gap-2'):
                ui.button(
                    'Nieuwe werkdag', icon='add',
                    on_click=lambda: open_werkdag_dialog(on_save=refresh_table),
                ).props('color=primary')

                # Kebab voor CSV-exports (Urenregistratie, Km-logboek, generiek)
                with ui.button(icon='more_vert').props('flat round dense color=secondary'):
                    with ui.menu():
                        ui.menu_item('Exporteer werkdagen (CSV)',
                                     on_click=lambda: export_csv())
                        ui.menu_item('Exporteer urenregistratie (Belastingdienst)',
                                     on_click=lambda: export_uren_overzicht())
                        ui.menu_item('Exporteer km-logboek (Belastingdienst)',
                                     on_click=lambda: export_km_logboek())

        # --- Filter strip ---
        with ui.element('div').classes('page-toolbar w-full'):
            # Segmented tabs (Alle / Ongefactureerd / ANW)
            with ui.element('div').classes('seg'):
                for key, label in [
                    (SEG_ALL, 'Alle'),
                    (SEG_UNINVOICED, 'Ongefactureerd'),
                    (SEG_ANW, 'ANW'),
                ]:
                    btn = ui.element('button').classes(
                        'seg-btn on' if key == SEG_ALL else 'seg-btn'
                    )
                    with btn:
                        ui.label(label)
                    btn.on('click', lambda _e=None, k=key: _set_segment(k))
                    seg_buttons[key] = btn

            jaar_select = ui.select(
                year_options(include_next=True, as_dict=True, descending=False),
                value=current_year, label='Jaar',
            ).classes('w-28')

            maand_select = ui.select(
                MAANDEN, value=0, label='Maand',
            ).classes('w-28')

            klant_sel = ui.select(
                klant_options, value=0, label='Klant',
            ).classes('w-44')

            ui.space()

            # Live summary (rijen · uren · km · bedrag) — reflecteert filter
            summary_label['ref'] = ui.label('').classes('mono text-grey-7')

        # --- Sticky bulk-bar (alleen zichtbaar bij selectie) ---
        bulk_bar = ui.element('div').classes('selection-bar')
        bulk_bar.set_visibility(False)
        with bulk_bar:
            bulk_count = ui.label('').classes('sb-count')
            bulk_meta = ui.label('').classes('sb-meta')
            ui.space()
            # "Maak factuur" of "Maak factuur per klant ▾" — wisselt
            single_btn = ui.button('Maak factuur', icon='receipt') \
                .props('color=primary unelevated')
            multi_btn = ui.button('Maak factuur per klant',
                                   icon='arrow_drop_down') \
                .props('color=primary unelevated')
            multi_btn.set_visibility(False)
            with multi_btn:
                multi_menu = ui.menu()  # auto-attached as child = anchor
            ui.button(icon='delete', on_click=lambda: verwijder_selectie()) \
                .props('flat round color=white').tooltip('Verwijder selectie')
            ui.button(icon='close', on_click=lambda: _clear_selection()) \
                .props('flat round color=white').tooltip('Deselecteer alles')

        # --- Tabel ---
        _trunc = 'max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
        columns = [
            {'name': 'datum', 'label': 'Datum', 'field': 'datum', 'sortable': True,
             'align': 'left', 'style': 'width:90px'},
            {'name': 'klant', 'label': 'Klant', 'field': 'klant_naam', 'sortable': True,
             'align': 'left', 'style': _trunc},
            {'name': 'code', 'label': 'Code', 'field': 'code', 'align': 'left',
             'style': 'width:90px'},
            {'name': 'uren', 'label': 'Uren', 'field': 'uren', 'sortable': True,
             'align': 'right', 'style': 'width:60px'},
            {'name': 'km', 'label': 'Km', 'field': 'km', 'align': 'right',
             'style': 'width:50px'},
            {'name': 'tarief', 'label': 'Tarief', 'field': 'tarief_fmt', 'align': 'right',
             'style': 'width:80px'},
            {'name': 'bedrag', 'label': 'Bedrag', 'field': 'totaal_fmt', 'align': 'right',
             'style': 'width:90px'},
            {'name': 'factuur', 'label': 'Factuur', 'field': 'factuurnummer', 'align': 'left',
             'style': 'width:100px'},
            {'name': 'actions', 'label': '', 'field': 'actions', 'align': 'center',
             'style': 'width:50px'},
        ]

        table = ui.table(
            columns=columns, rows=[], row_key='id',
            selection='multiple',
            pagination={'rowsPerPage': 25, 'sortBy': 'datum', 'descending': True,
                        'rowsPerPageOptions': [10, 20, 50, 0]},
        ).classes('w-full')
        table_ref['ref'] = table

        # Datum mono
        table.add_slot('body-cell-datum', '''
            <q-td :props="props">
                <span class="num" style="font-size:12px">{{ props.row.datum_fmt }}</span>
            </q-td>
        ''')

        # Klant + locatie subline
        table.add_slot('body-cell-klant', '''
            <q-td :props="props">
                <div>{{ props.row.klant_naam }}</div>
                <div v-if="props.row.locatie" class="cell-sub">{{ props.row.locatie }}</div>
            </q-td>
        ''')

        # Code chip — kleurklasse uit row.chip_class, label uit row.code_label
        table.add_slot('body-cell-code', '''
            <q-td :props="props">
                <span :class="'chip ' + props.row.chip_class">{{ props.row.code_label }}</span>
            </q-td>
        ''')

        # Numerieke kolommen mono
        for col in ('uren', 'km', 'tarief', 'bedrag'):
            field = {'tarief': 'tarief_fmt', 'bedrag': 'totaal_fmt'}.get(col, col)
            table.add_slot(f'body-cell-{col}', f'''
                <q-td :props="props" class="text-right">
                    <span class="num">{{{{ props.row.{field} }}}}</span>
                </q-td>
            ''')

        # Factuur: nummer in mono of em-dash in --neg
        table.add_slot('body-cell-factuur', '''
            <q-td :props="props">
                <span v-if="props.row.factuurnummer"
                      class="mono" style="font-size:11px;color:#6b6f76">
                    {{ props.row.factuurnummer }}
                </span>
                <span v-else class="mono" style="font-size:11px;color:#b45309">—</span>
            </q-td>
        ''')

        table.add_slot('no-data', '''
            <q-tr><q-td colspan="100%" class="text-center q-pa-lg text-grey">
                Geen werkdagen gevonden.
            </q-td></q-tr>
        ''')

        # Kebab-menu per rij — bewerken / verwijderen / ontkoppelen
        table.add_slot('body-cell-actions', '''
            <q-td :props="props">
                <q-btn icon="more_vert" flat dense round size="sm">
                    <q-menu>
                        <q-list dense style="min-width:180px">
                            <q-item clickable v-close-popup
                                @click="() => $parent.$emit('edit', props.row)">
                                <q-item-section avatar><q-icon name="edit"/></q-item-section>
                                <q-item-section>Bewerken</q-item-section>
                            </q-item>
                            <q-item clickable v-close-popup
                                v-if="props.row.factuurnummer"
                                @click="() => $parent.$emit('ontkoppel', props.row)">
                                <q-item-section avatar><q-icon name="link_off"/></q-item-section>
                                <q-item-section>Ontkoppel factuur</q-item-section>
                            </q-item>
                            <q-separator/>
                            <q-item clickable v-close-popup
                                @click="() => $parent.$emit('delete', props.row)">
                                <q-item-section avatar><q-icon name="delete" color="negative"/></q-item-section>
                                <q-item-section class="text-negative">Verwijderen</q-item-section>
                            </q-item>
                        </q-list>
                    </q-menu>
                </q-btn>
            </q-td>
        ''')

        # --- Helpers ---
        def _set_segment(value: str):
            seg_state['value'] = value
            for k, btn in seg_buttons.items():
                btn.classes(remove='on')
                if k == value:
                    btn.classes(add='on')
            asyncio.create_task(refresh_table())

        def _clear_selection():
            tbl = table_ref['ref']
            if tbl:
                tbl.selected.clear()
                tbl.update()
            update_bulk_bar()

        def _build_multi_menu(selected_rows):
            """Bouw dropdown-items voor multi-klant picker."""
            multi_menu.clear()
            klant_groups = {}
            for r in selected_rows:
                kid = r['klant_id']
                if kid not in klant_groups:
                    klant_groups[kid] = {
                        'naam': r['klant_naam'], 'rows': [],
                    }
                klant_groups[kid]['rows'].append(r)

            # Sorteer op aantal dagen, descending
            sorted_groups = sorted(
                klant_groups.items(),
                key=lambda kv: -len(kv[1]['rows']),
            )
            with multi_menu:
                for kid, grp in sorted_groups:
                    n = len(grp['rows'])
                    uren = sum(r['uren'] for r in grp['rows'])
                    bedrag = sum(
                        r['uren'] * r['tarief_raw'] + r['km'] * r['km_tarief_raw']
                        for r in grp['rows']
                    )
                    label = (
                        f'{grp["naam"]} — {n} dag{"en" if n != 1 else ""} · '
                        f'{uren:.1f}u · {format_euro(bedrag)}'
                    )
                    ui.menu_item(label, on_click=lambda kid=kid: _factuur_voor_klant(kid))

        def _factuur_voor_klant(klant_id: int):
            """Beperkt selectie tot 1 klant en navigeer naar factuurbuilder."""
            tbl = table_ref['ref']
            if not tbl:
                return
            kept = [r for r in tbl.selected if r['klant_id'] == klant_id]
            al_gefact = [r for r in kept if r.get('factuurnummer')]
            if al_gefact:
                ui.notify(
                    f'{len(al_gefact)} werkdag(en) van deze klant zijn al '
                    f'gefactureerd — deselecteer eerst.', type='warning')
                return
            ids = [r['id'] for r in kept]
            if not ids:
                return
            app.storage.user['selected_werkdagen'] = ids
            ui.navigate.to('/facturen')

        def update_bulk_bar():
            tbl = table_ref['ref']
            selected = tbl.selected if tbl else []
            n = len(selected) if selected else 0
            if n == 0:
                bulk_bar.set_visibility(False)
                return
            klant_ids = set(r['klant_id'] for r in selected)
            uren = sum(r['uren'] for r in selected)
            bedrag = sum(
                r['uren'] * r['tarief_raw'] + r['km'] * r['km_tarief_raw']
                for r in selected
            )
            bulk_count.text = f'{n} werkdag{"en" if n != 1 else ""} geselecteerd'
            bulk_meta.text = f'{uren:.1f}u · {format_euro(bedrag)}'
            bulk_bar.set_visibility(True)

            # Single klant → "Maak factuur"; meerdere → "Maak factuur per klant"
            if len(klant_ids) > 1:
                single_btn.set_visibility(False)
                multi_btn.set_visibility(True)
                _build_multi_menu(selected)
            else:
                single_btn.set_visibility(True)
                multi_btn.set_visibility(False)

        async def ga_naar_factuur():
            """Single-klant flow — onveranderd."""
            selected = table_ref['ref'].selected
            if not selected:
                ui.notify('Selecteer eerst werkdagen', type='warning')
                return
            klant_ids = set(r['klant_id'] for r in selected)
            if len(klant_ids) > 1:
                # Defensief — UI zou hier al multi-mode moeten zijn
                ui.notify('Selectie bevat meerdere klanten — kies via dropdown.',
                          type='warning')
                return
            al_gefactureerd = [r for r in selected if r.get('factuurnummer')]
            if al_gefactureerd:
                ui.notify(
                    f'{len(al_gefactureerd)} werkdag(en) al gefactureerd — '
                    f'deselecteer deze eerst.', type='warning')
                return
            ids = [r['id'] for r in selected]
            app.storage.user['selected_werkdagen'] = ids
            ui.navigate.to('/facturen')

        single_btn.on('click', lambda _e: ga_naar_factuur())

        async def verwijder_selectie():
            selected = table_ref['ref'].selected
            if not selected:
                return
            ids = [r['id'] for r in selected]

            async def confirm_bulk_delete():
                deleted = 0
                skipped = 0
                for wid in ids:
                    try:
                        await delete_werkdag(DB_PATH, werkdag_id=wid)
                        deleted += 1
                    except ValueError:
                        skipped += 1
                if deleted:
                    ui.notify(f'{deleted} werkdag(en) verwijderd', type='positive')
                if skipped:
                    ui.notify(
                        f'{skipped} werkdag(en) overgeslagen (gefactureerd/betaald)',
                        type='warning')
                await refresh_table()

            await confirm_dialog(
                title=f'{len(ids)} werkdag(en) verwijderen?',
                message='Gefactureerde werkdagen worden overgeslagen.',
                on_confirm=confirm_bulk_delete,
                button_label='Ja, verwijderen',
            )

        # --- Exports (uit kebab) ---
        async def export_csv():
            year = jaar_select.value
            month = maand_select.value if maand_select.value != 0 else None
            klant = klant_sel.value if klant_sel.value != 0 else None
            all_wd = await get_werkdagen(DB_PATH, jaar=year, maand=month,
                                         klant_id=klant)
            werkdagen = [w for w in all_wd if _segment_matches(w, seg_state['value'])]
            headers = ['Datum', 'Klant', 'Code', 'Uren', 'Km', 'Tarief',
                       'Km-tarief', 'Totaal', 'Status']
            rows = []
            for w in werkdagen:
                totaal = w.uren * w.tarief + w.km * w.km_tarief
                rows.append([w.datum, w.klant_naam, w.code, w.uren,
                             w.km, w.tarief, w.km_tarief,
                             round(totaal, 2), w.status])
            csv_str = generate_csv(headers, rows)
            ui.download.content(csv_str.encode('utf-8-sig'),
                                f'werkdagen_{year}.csv')

        async def export_uren_overzicht():
            rows = await get_werkdagen(DB_PATH, jaar=jaar_select.value)
            uren_rows = [w for w in rows if w.urennorm]
            headers = ['Datum', 'Klant', 'Locatie', 'Uren', 'Activiteit']
            csv_rows = [[format_datum(w.datum), w.klant_naam, w.locatie or '',
                          str(w.uren), w.activiteit] for w in uren_rows]
            totaal = sum(w.uren for w in uren_rows)
            csv_rows.append(['', '', 'TOTAAL', str(totaal), ''])
            csv_data = generate_csv(headers, csv_rows)
            ui.download.content(csv_data.encode('utf-8-sig'),
                                f'urenregistratie_{jaar_select.value}.csv')

        async def export_km_logboek():
            rows = await get_werkdagen(DB_PATH, jaar=jaar_select.value)
            klanten_dict = {k.id: k for k in await get_klanten(DB_PATH)}
            km_rows = [w for w in rows if w.km and w.km > 0]
            headers = ['Datum', 'Klant', 'Locatie', 'Vertrek', 'Bestemming',
                       'Retour km', 'Doel']
            csv_rows = []
            for w in km_rows:
                klant = klanten_dict.get(w.klant_id)
                bestemming = w.locatie or (klant.naam if klant else '')
                csv_rows.append([
                    format_datum(w.datum), w.klant_naam, w.locatie or '',
                    'Thuisadres', bestemming, str(w.km),
                    'Waarneming huisartspraktijk',
                ])
            totaal = sum(w.km for w in km_rows)
            csv_rows.append(['', '', '', '', 'TOTAAL', str(totaal), ''])
            csv_data = generate_csv(headers, csv_rows)
            ui.download.content(csv_data.encode('utf-8-sig'),
                                f'km_logboek_{jaar_select.value}.csv')

        # Selection events
        table.on('selection', lambda _: update_bulk_bar())

        async def refresh_table():
            year = jaar_select.value
            month = maand_select.value if maand_select.value != 0 else None
            klant_id = klant_sel.value if klant_sel.value != 0 else None

            # Year-wide totals voor subtitle (NIET filter-afhankelijk)
            year_all = await get_werkdagen(DB_PATH, jaar=year)
            urencrit_uren = sum(w.uren for w in year_all if w.urennorm)
            subtitle_label['ref'].text = (
                f'{len(year_all)} dagen in {year} · '
                f'{urencrit_uren:.0f} uur telt voor urencriterium'
            )

            # Maand+klant via DB-query, segment via Python (geen DB-kolom)
            db_rows = await get_werkdagen(DB_PATH, jaar=year, maand=month,
                                          klant_id=klant_id)
            werkdagen = [w for w in db_rows
                         if _segment_matches(w, seg_state['value'])]

            # Update klant-dropdown options met klanten die werkdagen hebben
            seen = {}
            for w in db_rows:
                if w.klant_id not in seen:
                    seen[w.klant_id] = w.klant_naam
            new_options = {0: 'Alle'} | dict(
                sorted(seen.items(), key=lambda x: x[1])
            )
            klant_sel.options = new_options
            if klant_id and klant_id not in new_options:
                klant_sel.set_value(0)
            klant_sel.update()

            rows = []
            totaal_uren = 0.0
            totaal_km = 0.0
            totaal_bedrag = 0.0

            for w in werkdagen:
                bedrag = w.uren * w.tarief + w.km * w.km_tarief
                rows.append({
                    'id': w.id,
                    'datum': w.datum,
                    'datum_fmt': format_datum(w.datum),
                    'klant_naam': w.klant_naam,
                    'klant_id': w.klant_id,
                    'code': w.code,
                    'code_label': _CODE_LABELS.get(w.code, w.code or '—'),
                    'chip_class': _chip_class_for(w.code, w.urennorm),
                    'uren': w.uren,
                    'km': w.km,
                    'tarief_raw': w.tarief,
                    'tarief_fmt': format_euro(w.tarief),
                    'km_tarief_raw': w.km_tarief,
                    'totaal_fmt': format_euro(bedrag),
                    'locatie': w.locatie,
                    'factuurnummer': w.factuurnummer or '',
                })
                totaal_uren += w.uren
                totaal_km += w.km
                totaal_bedrag += bedrag

            table.rows = rows
            table.selected.clear()
            table.update()
            update_bulk_bar()

            summary_label['ref'].text = (
                f'{len(rows)} rijen · ∑ {totaal_uren:.1f}u · '
                f'{totaal_km:.0f}km · {format_euro(totaal_bedrag)}'
            )

        # --- Event handlers ---
        async def on_edit(e):
            row = e.args
            werkdagen_db = await get_werkdagen(DB_PATH, jaar=jaar_select.value)
            werkdag = next((w for w in werkdagen_db if w.id == row['id']), None)
            if werkdag:
                await open_werkdag_dialog(on_save=refresh_table, werkdag=werkdag)

        async def on_delete(e):
            row = e.args

            async def do_delete():
                try:
                    await delete_werkdag(DB_PATH, werkdag_id=row['id'])
                except ValueError as exc:
                    ui.notify(str(exc) or 'Kan gefactureerde werkdag niet verwijderen',
                              type='warning')
                    return
                ui.notify('Werkdag verwijderd', type='positive')
                await refresh_table()

            await confirm_dialog(
                title=f"Werkdag {format_datum(row['datum'])} verwijderen?",
                message=(f"{row.get('klant_naam', '')} — "
                         f"{row.get('uren', 0)} uur — "
                         f"{row.get('totaal_fmt', '')}"),
                on_confirm=do_delete,
                button_label='Ja, verwijderen',
            )

        async def on_ontkoppel(e):
            """Ontkoppel werkdag van factuur (factuurnummer wissen)."""
            from database import update_werkdag
            row = e.args
            nummer = row.get('factuurnummer', '')

            async def do_ontkoppel():
                try:
                    await update_werkdag(DB_PATH, werkdag_id=row['id'],
                                         factuurnummer='')
                except ValueError as exc:
                    ui.notify(str(exc), type='warning')
                    return
                ui.notify(f'Ontkoppeld van factuur {nummer}', type='positive')
                await refresh_table()

            await confirm_dialog(
                title=f'Ontkoppel werkdag van factuur {nummer}?',
                message='De werkdag wordt weer als ongefactureerd beschouwd. '
                        'De factuur zelf blijft bestaan.',
                on_confirm=do_ontkoppel,
                button_label='Ja, ontkoppel',
                button_color='primary',
            )

        table.on('edit', on_edit)
        table.on('delete', on_delete)
        table.on('ontkoppel', on_ontkoppel)

        # Filter change handlers
        jaar_select.on_value_change(lambda _: refresh_table())
        maand_select.on_value_change(lambda _: refresh_table())
        klant_sel.on_value_change(lambda _: refresh_table())

        # Initial load
        await refresh_table()
