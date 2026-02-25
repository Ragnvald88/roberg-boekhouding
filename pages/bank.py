"""Bank pagina — Rabobank CSV import + categoriseren."""

from datetime import datetime
from pathlib import Path

from nicegui import ui

from components.layout import create_layout
from database import (
    get_banktransacties, add_banktransacties, update_banktransactie,
)
from import_.rabobank_csv import parse_rabobank_csv

DB_PATH = Path("data/boekhouding.sqlite3")

BANK_CATEGORIEEN = [
    '', 'Omzet', 'Pensioenpremie SPH', 'Telefoon/KPN', 'Verzekeringen',
    'Accountancy/software', 'Representatie', 'Lidmaatschappen',
    'Kleine aankopen', 'Scholingskosten', 'Bankkosten', 'Investeringen',
    'Prive', 'Belasting', 'AOV',
]


def format_euro(value: float) -> str:
    """Format float as Dutch euro string: € 1.234,56."""
    return f"\u20ac {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@ui.page('/bank')
async def bank_page():
    create_layout('Bank', '/bank')

    # --- State ---
    current_year = datetime.now().year
    selected_jaar = {'value': current_year}
    selected_maand = {'value': 0}  # 0 = alle maanden

    table_ref = {'table': None}
    csv_list_container = {'ref': None}

    # --- Helper functions ---

    async def load_transacties() -> list[dict]:
        """Load transactions from DB, apply year/month filter."""
        transacties = await get_banktransacties(DB_PATH, jaar=selected_jaar['value'])

        if selected_maand['value'] > 0:
            maand_str = f"{selected_maand['value']:02d}"
            transacties = [t for t in transacties if t.datum[5:7] == maand_str]

        rows = []
        for t in transacties:
            # Determine status for color coding
            if t.koppeling_type and t.koppeling_id:
                status = 'gekoppeld'
            elif t.categorie:
                status = 'gecategoriseerd'
            else:
                status = 'niet-gekoppeld'

            rows.append({
                'id': t.id,
                'datum': t.datum,
                'bedrag': t.bedrag,
                'bedrag_fmt': format_euro(t.bedrag),
                'tegenpartij': t.tegenpartij,
                'omschrijving': t.omschrijving[:80] + ('...' if len(t.omschrijving) > 80 else ''),
                'omschrijving_full': t.omschrijving,
                'categorie': t.categorie,
                'koppeling': f"{t.koppeling_type} #{t.koppeling_id}" if t.koppeling_type else '',
                'status': status,
                'csv_bestand': t.csv_bestand,
            })
        return rows

    async def refresh_table():
        """Reload data and update the table."""
        rows = await load_transacties()
        if table_ref['table']:
            table_ref['table'].rows = rows
            table_ref['table'].update()

    async def refresh_csv_list():
        """Reload the list of imported CSV files."""
        if csv_list_container['ref'] is None:
            return
        csv_list_container['ref'].clear()
        transacties = await get_banktransacties(DB_PATH, jaar=selected_jaar['value'])
        csv_files = sorted(set(t.csv_bestand for t in transacties if t.csv_bestand))
        with csv_list_container['ref']:
            if not csv_files:
                ui.label('Nog geen CSV-bestanden geimporteerd.').classes('text-grey')
            else:
                for csv_file in csv_files:
                    count = sum(1 for t in transacties if t.csv_bestand == csv_file)
                    ui.label(f"{csv_file} ({count} transacties)").classes('text-sm')

    async def handle_upload(e):
        """Handle CSV file upload: parse, archive, insert."""
        content = e.content.read()
        filename = e.name

        try:
            transacties = parse_rabobank_csv(content)
        except ValueError as exc:
            ui.notify(f"Fout bij parsing: {exc}", type='negative')
            return

        if not transacties:
            ui.notify("Geen transacties gevonden in CSV.", type='warning')
            return

        # Archive CSV to data/bank_csv/
        csv_dir = Path("data/bank_csv")
        csv_dir.mkdir(parents=True, exist_ok=True)
        archive_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
        archive_path = csv_dir / archive_name
        archive_path.write_bytes(content)

        # Insert into database
        count = await add_banktransacties(DB_PATH, transacties, csv_bestand=archive_name)

        ui.notify(f"{count} transacties geimporteerd uit {filename}", type='positive')
        await refresh_table()
        await refresh_csv_list()

    async def handle_categorie_change(row_id: int, new_cat: str):
        """Update category for a bank transaction."""
        await update_banktransactie(DB_PATH, transactie_id=row_id, categorie=new_cat)
        await refresh_table()

    async def handle_jaar_change(new_jaar):
        selected_jaar['value'] = new_jaar
        await refresh_table()
        await refresh_csv_list()

    async def handle_maand_change(new_maand):
        selected_maand['value'] = new_maand
        await refresh_table()

    # --- Page layout ---
    with ui.column().classes('w-full p-4 max-w-7xl mx-auto'):
        ui.label('Banktransacties').classes('text-h5')

        # Top bar: filters + upload
        with ui.row().classes('w-full items-center gap-4 q-mb-md'):
            # Year selector
            jaren = list(range(2023, current_year + 1))
            ui.select(
                label='Jaar',
                options=jaren,
                value=current_year,
                on_change=lambda e: handle_jaar_change(e.value),
            ).classes('w-32')

            # Month selector
            maand_opties = {0: 'Alle maanden'}
            for m in range(1, 13):
                maand_opties[m] = datetime(2026, m, 1).strftime('%B').capitalize()
            # Dutch month names
            nl_maanden = {
                0: 'Alle maanden', 1: 'Januari', 2: 'Februari', 3: 'Maart',
                4: 'April', 5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Augustus',
                9: 'September', 10: 'Oktober', 11: 'November', 12: 'December',
            }
            ui.select(
                label='Maand',
                options=nl_maanden,
                value=0,
                on_change=lambda e: handle_maand_change(e.value),
            ).classes('w-40')

            ui.space()

            # CSV upload button
            ui.upload(
                label='Importeer CSV',
                on_upload=handle_upload,
                auto_upload=True,
            ).props('accept=".csv" flat color=primary').classes('w-48')

        # Transactions table
        columns = [
            {'name': 'datum', 'label': 'Datum', 'field': 'datum', 'sortable': True,
             'align': 'left'},
            {'name': 'bedrag_fmt', 'label': 'Bedrag', 'field': 'bedrag_fmt',
             'sortable': True, 'align': 'right'},
            {'name': 'tegenpartij', 'label': 'Tegenpartij', 'field': 'tegenpartij',
             'sortable': True, 'align': 'left'},
            {'name': 'omschrijving', 'label': 'Omschrijving', 'field': 'omschrijving',
             'align': 'left'},
            {'name': 'categorie', 'label': 'Categorie', 'field': 'categorie',
             'sortable': True, 'align': 'left'},
            {'name': 'koppeling', 'label': 'Koppeling', 'field': 'koppeling',
             'align': 'left'},
        ]

        initial_rows = await load_transacties()

        table = ui.table(
            columns=columns,
            rows=initial_rows,
            row_key='id',
            pagination={'rowsPerPage': 25, 'sortBy': 'datum', 'descending': True},
        ).classes('w-full')
        table_ref['table'] = table

        # Custom cell rendering for bedrag color and categorie dropdown
        table.add_slot('body', r'''
            <q-tr :props="props"
                   :class="{
                       'bg-green-1': props.row.status === 'gekoppeld',
                       'bg-orange-1': props.row.status === 'gecategoriseerd',
                       'bg-red-1': props.row.status === 'niet-gekoppeld'
                   }">
                <q-td key="datum" :props="props">{{ props.row.datum }}</q-td>
                <q-td key="bedrag_fmt" :props="props"
                       :class="props.row.bedrag >= 0 ? 'text-green-8 text-bold' : 'text-red-8 text-bold'"
                       style="text-align: right">
                    {{ props.row.bedrag_fmt }}
                </q-td>
                <q-td key="tegenpartij" :props="props">{{ props.row.tegenpartij }}</q-td>
                <q-td key="omschrijving" :props="props">
                    <span :title="props.row.omschrijving_full">{{ props.row.omschrijving }}</span>
                </q-td>
                <q-td key="categorie" :props="props">
                    <q-select
                        v-model="props.row.categorie"
                        :options="''' + str(BANK_CATEGORIEEN) + r'''"
                        dense outlined
                        emit-value map-options
                        @update:model-value="(val) => $parent.$emit('cat_change', {id: props.row.id, cat: val})"
                        style="min-width: 160px"
                    />
                </q-td>
                <q-td key="koppeling" :props="props">{{ props.row.koppeling }}</q-td>
            </q-tr>
        ''')

        table.on('cat_change', lambda e: handle_categorie_change(e.args['id'], e.args['cat']))

        # Imported CSV files section
        ui.separator().classes('q-my-lg')
        ui.label('Geimporteerde CSV-bestanden').classes('text-h6 q-mb-sm')

        csv_container = ui.column().classes('w-full')
        csv_list_container['ref'] = csv_container
        await refresh_csv_list()
