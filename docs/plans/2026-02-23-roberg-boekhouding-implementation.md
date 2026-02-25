# TestBV Boekhouding App — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone Dutch bookkeeping web app (NiceGUI + SQLite) for a solo GP locum, replacing Moneybird and Excel.

**Architecture:** Python NiceGUI web app with SQLite database, ECharts dashboards, WeasyPrint + Jinja2 PDF invoice generation. Runs natively on macOS (`python main.py`). 6 pages: Dashboard, Werkdagen, Facturen, Kosten, Bank, Jaarafsluiting + Settings dialog.

**Tech Stack:** NiceGUI 3.x, aiosqlite, WeasyPrint, Jinja2, ECharts (native Python, no Docker)

**Design doc:** `docs/plans/2026-02-23-roberg-boekhouding-app-design.md`

**Working directory for the app:** `~/Library/CloudStorage/SynologyDrive-Main/06_Development/roberg-boekhouding/`

---

## Task 1: Project Scaffold & Database

**Files:**
- Create: `roberg-boekhouding/main.py`
- Create: `roberg-boekhouding/database.py`
- Create: `roberg-boekhouding/models.py`
- Create: `roberg-boekhouding/requirements.txt`
- Create: `roberg-boekhouding/start-boekhouding.command`
- Create: `roberg-boekhouding/.gitignore`
- Test: `roberg-boekhouding/tests/test_database.py`

**Step 1: Create project directory and requirements.txt**

```
roberg-boekhouding/
├── main.py
├── database.py
├── models.py
├── requirements.txt
├── start-boekhouding.command
├── .gitignore
├── pages/
├── components/
├── fiscal/
├── import_/
├── templates/
├── tests/
└── data/
    ├── facturen/
    ├── uitgaven/
    └── bank_csv/
```

```
# requirements.txt
nicegui>=3.0
aiosqlite
openpyxl
httpx
jinja2
weasyprint
pytest
pytest-asyncio
```

**Step 2: Write database.py with schema and connection**

Create `database.py` with:
- `get_db()` async context manager returning aiosqlite connection
- `init_db()` to create all 6 tables (exact SQL from design doc)
- `DB_PATH = Path("data/boekhouding.sqlite3")`
- All queries as plain async functions (no ORM): `get_klanten()`, `get_werkdagen(jaar)`, `add_werkdag(...)`, `update_werkdag(id, ...)`, `delete_werkdag(id)`, etc.
- Use parameterized queries everywhere (no f-strings in SQL)

**Database hardening (add to `init_db()`):**

```sql
-- Enable WAL mode for better concurrent reads + crash resilience
PRAGMA journal_mode = WAL;

-- Enable foreign key enforcement (SQLite ignores FK without this)
PRAGMA foreign_keys = ON;

-- Add indexes on frequently-queried columns
CREATE INDEX IF NOT EXISTS idx_werkdagen_datum ON werkdagen(datum);
CREATE INDEX IF NOT EXISTS idx_werkdagen_klant ON werkdagen(klant_id);
CREATE INDEX IF NOT EXISTS idx_werkdagen_status ON werkdagen(status);
CREATE INDEX IF NOT EXISTS idx_banktransacties_datum ON banktransacties(datum);
CREATE INDEX IF NOT EXISTS idx_uitgaven_datum ON uitgaven(datum);
CREATE INDEX IF NOT EXISTS idx_facturen_klant ON facturen(klant_id);
```

**Add CHECK constraints to schema** (prevent invalid data at DB level):

```sql
-- klanten
CHECK (actief IN (0, 1))
CHECK (tarief_uur >= 0)
CHECK (retour_km >= 0)

-- werkdagen
CHECK (uren > 0)
CHECK (tarief >= 0)
CHECK (km >= 0)
CHECK (urennorm IN (0, 1))

-- facturen
CHECK (totaal_bedrag >= 0)
CHECK (betaald IN (0, 1))

-- uitgaven
CHECK (bedrag >= 0)
CHECK (is_investering IN (0, 1))
CHECK (zakelijk_pct BETWEEN 0 AND 100)
```

**Step 3: Write models.py with dataclasses**

Plain Python dataclasses for type hints and data transfer:
```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Klant:
    id: int = 0
    naam: str = ''
    tarief_uur: float = 0.0
    retour_km: float = 0.0
    adres: str = ''
    kvk: str = ''
    actief: bool = True

@dataclass
class Werkdag:
    id: int = 0
    datum: str = ''
    klant_id: int = 0
    code: str = ''
    activiteit: str = 'Waarneming dagpraktijk'
    locatie: str = ''
    uren: float = 0.0
    km: float = 0.0
    tarief: float = 0.0
    km_tarief: float = 0.23
    status: str = 'ongefactureerd'
    factuurnummer: str = ''
    opmerking: str = ''
    urennorm: bool = True

# ... similarly for Factuur, Uitgave, Banktransactie, FiscaleParams
```

**Step 4: Write test for database init + CRUD**

```python
# tests/test_database.py
import pytest, asyncio, aiosqlite
from database import init_db, add_klant, get_klanten, add_werkdag, get_werkdagen

@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path

@pytest.mark.asyncio
async def test_init_creates_tables(db):
    async with aiosqlite.connect(db) as conn:
        cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in await cursor.fetchall()}
    assert tables >= {'klanten', 'werkdagen', 'facturen', 'uitgaven', 'banktransacties', 'fiscale_params'}

@pytest.mark.asyncio
async def test_klant_crud(db):
    kid = await add_klant(db, naam="HAP Klant6", tarief_uur=77.50, retour_km=52)
    klanten = await get_klanten(db)
    assert len(klanten) == 1
    assert klanten[0].naam == "HAP Klant6"
    assert klanten[0].tarief_uur == 77.50

@pytest.mark.asyncio
async def test_werkdag_crud(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    wid = await add_werkdag(db, datum="2026-02-23", klant_id=kid, uren=9, km=44, tarief=80)
    werkdagen = await get_werkdagen(db, jaar=2026)
    assert len(werkdagen) == 1
    assert werkdagen[0].uren == 9
```

**Step 5: Run tests**

Run: `cd roberg-boekhouding && python -m pytest tests/test_database.py -v`
Expected: all 3 tests pass.

**Step 6: Write main.py skeleton**

```python
# main.py
from nicegui import app, ui
from database import init_db
from pathlib import Path
import asyncio

DB_PATH = Path("data/boekhouding.sqlite3")

@app.on_startup
async def startup():
    Path("data/facturen").mkdir(parents=True, exist_ok=True)
    Path("data/uitgaven").mkdir(parents=True, exist_ok=True)
    Path("data/bank_csv").mkdir(parents=True, exist_ok=True)
    await init_db(DB_PATH)

@ui.page('/')
async def dashboard():
    ui.label('TestBV Boekhouding').classes('text-h4')
    ui.label('Dashboard — onder constructie')

ui.run(
    title='TestBV Boekhouding',
    storage_secret='roberg-dev-secret-change-me',
    port=8085,
    show=True,  # Opens browser on startup
)
```

```bash
#!/bin/bash
# start-boekhouding.command — double-click to launch
cd "$(dirname "$0")"
python3 main.py
```

**Step 7: Verify app starts**

Run: `cd roberg-boekhouding && pip install -r requirements.txt && python main.py`
Expected: browser opens at http://localhost:8085 showing "TestBV Boekhouding" heading.

**Step 8: Make launch script executable + Git init + commit**

```bash
cd roberg-boekhouding
chmod +x start-boekhouding.command
git init
git add .
git commit -m "feat: project scaffold with database, models, launch script"
```

---

## Task 2: Layout & Navigation

**Files:**
- Create: `components/layout.py`
- Modify: `main.py` (add page imports)
- Create: `pages/dashboard.py` (stub)
- Create: `pages/werkdagen.py` (stub)
- Create: `pages/facturen.py` (stub)
- Create: `pages/kosten.py` (stub)
- Create: `pages/bank.py` (stub)
- Create: `pages/jaarafsluiting.py` (stub)

**Step 1: Build shared layout component**

```python
# components/layout.py
from nicegui import ui

def create_layout(title: str, active_page: str = ''):
    """Shared layout: header bar + sidebar navigation + content area."""

    PAGES = [
        ('Dashboard', 'dashboard', '/'),
        ('Werkdagen', 'schedule', '/werkdagen'),
        ('Facturen', 'receipt', '/facturen'),
        ('Kosten', 'payments', '/kosten'),
        ('Bank', 'account_balance', '/bank'),
        ('Jaarafsluiting', 'bar_chart', '/jaarafsluiting'),
    ]

    with ui.header().classes('bg-primary items-center'):
        ui.button(icon='menu', on_click=lambda: drawer.toggle()).props('flat color=white round')
        ui.label('TestBV Boekhouding').classes('text-h6 text-white q-ml-sm')
        ui.space()
        ui.label(title).classes('text-white')

    drawer = ui.left_drawer(value=True).classes('bg-blue-1')
    with drawer:
        ui.label('Navigatie').classes('text-subtitle2 q-mb-sm')
        for label, icon, target in PAGES:
            btn = ui.button(label, icon=icon,
                           on_click=lambda t=target: ui.navigate.to(t))
            btn.props('flat align=left no-caps').classes('w-full')
            if target == active_page:
                btn.classes('bg-blue-2')
        ui.separator().classes('q-my-md')
        ui.button('Instellingen', icon='settings',
                  on_click=lambda: ui.notify('TODO: Instellingen')
                  ).props('flat align=left no-caps').classes('w-full')
```

**Step 2: Create stub pages**

Each page file follows this pattern:
```python
# pages/werkdagen.py
from nicegui import ui
from components.layout import create_layout

@ui.page('/werkdagen')
async def werkdagen_page():
    create_layout('Werkdagen', '/werkdagen')
    with ui.column().classes('w-full p-4 max-w-6xl mx-auto'):
        ui.label('Werkdagen — onder constructie').classes('text-h5')
```

Create all 6 pages as stubs.

**Step 3: Update main.py to import pages**

```python
# Add to main.py, after imports:
import pages.dashboard
import pages.werkdagen
import pages.facturen
import pages.kosten
import pages.bank
import pages.jaarafsluiting
```

**Step 4: Test navigation manually**

Run: `python main.py`
Click through all sidebar items. Verify each page loads with its title.

**Step 5: Commit**

```bash
git add .
git commit -m "feat: layout with sidebar navigation and 6 page stubs"
```

---

## Task 3: Seed Data (Klanten + Fiscale Parameters)

**Files:**
- Create: `import_/seed_data.py`
- Modify: `database.py` (add seed-on-first-run logic)
- Test: `tests/test_seed.py`

**Step 1: Write seed_data.py**

Pre-fill klanten (from existing data) and fiscale_params (2023-2027, all values from design doc + fiscale-berekening skill).

```python
# import_/seed_data.py

KLANTEN = [
    {"naam": "HAP K6", "tarief_uur": 77.50, "retour_km": 52,
     "adres": "Hoofdstraat 3, 9363 EV Marum", "actief": 1},
    {"naam": "K. Klant7", "tarief_uur": 77.50, "retour_km": 52,
     "adres": "Hoofdstraat 3, 9363 EV Marum", "actief": 1},
    {"naam": "HAP K14", "tarief_uur": 80.00, "retour_km": 44,
     "adres": "Hoofdstraat 1, 1234 AB Plaats14", "actief": 1},
    {"naam": "Klant2", "tarief_uur": 70.00, "retour_km": 108,
     "adres": "Hoofdstraat 2, 1234 AB Plaats2", "actief": 0},
    {"naam": "K. Klant15", "tarief_uur": 98.44, "retour_km": 0,
     "adres": "Nieuw-Weerdinge", "actief": 1},
]

FISCALE_PARAMS = {
    2023: {"zelfstandigenaftrek": 5030, "startersaftrek": 2123, "mkb_vrijstelling_pct": 14.0,
           "kia_ondergrens": 2401, "kia_bovengrens": 69764, "kia_pct": 28,
           "km_tarief": 0.21, "schijf1_grens": 73031, "schijf1_pct": 36.93,  # NB: km was €0.21 in 2023
           "schijf2_grens": 73031, "schijf2_pct": 36.93, "schijf3_pct": 49.50,
           "ahk_max": 3070, "ahk_afbouw_pct": 6.095, "ahk_drempel": 22660,
           "ak_max": 5052, "zvw_pct": 5.43, "zvw_max_grondslag": 66956, "repr_aftrek_pct": 80},
    2024: {"zelfstandigenaftrek": 3750, "startersaftrek": 2123, "mkb_vrijstelling_pct": 13.31,
           "kia_ondergrens": 2801, "kia_bovengrens": 69764, "kia_pct": 28,
           "km_tarief": 0.23, "schijf1_grens": 75518, "schijf1_pct": 36.97,
           "schijf2_grens": 75518, "schijf2_pct": 36.97, "schijf3_pct": 49.50,
           "ahk_max": 3362, "ahk_afbouw_pct": 6.63, "ahk_drempel": 24812,
           "ak_max": 5532, "zvw_pct": 5.32, "zvw_max_grondslag": 71628, "repr_aftrek_pct": 80},
    2025: {"zelfstandigenaftrek": 2470, "startersaftrek": 2123, "mkb_vrijstelling_pct": 12.70,
           "kia_ondergrens": 2901, "kia_bovengrens": 70602, "kia_pct": 28,
           "km_tarief": 0.23, "schijf1_grens": 38441, "schijf1_pct": 35.82,
           "schijf2_grens": 76817, "schijf2_pct": 37.48, "schijf3_pct": 49.50,
           "ahk_max": 3068, "ahk_afbouw_pct": 6.337, "ahk_drempel": 28406,
           "ak_max": 5599, "zvw_pct": 5.26, "zvw_max_grondslag": 75864, "repr_aftrek_pct": 80},
    2026: {"zelfstandigenaftrek": 1200, "startersaftrek": None, "mkb_vrijstelling_pct": 12.70,
           "kia_ondergrens": 2901, "kia_bovengrens": 70602, "kia_pct": 28,
           "km_tarief": 0.23, "schijf1_grens": 38883, "schijf1_pct": 35.75,
           "schijf2_grens": 78426, "schijf2_pct": 37.56, "schijf3_pct": 49.50,
           "ahk_max": 3115, "ahk_afbouw_pct": 6.337, "ahk_drempel": 28800,
           "ak_max": 5685, "zvw_pct": 4.85, "zvw_max_grondslag": 79409, "repr_aftrek_pct": 80},
}

async def seed_klanten(db_path): ...
async def seed_fiscale_params(db_path): ...
async def seed_all(db_path): ...
```

Note: startersaftrek for 2026 is None because TestBV has used it 3x (2023-2025).

**Step 2: Write test**

```python
# tests/test_seed.py
@pytest.mark.asyncio
async def test_seed_creates_5_klanten(db):
    await seed_all(db)
    klanten = await get_klanten(db)
    assert len(klanten) == 5
    assert klanten[0].naam == "HAP K6"

@pytest.mark.asyncio
async def test_seed_creates_fiscale_params(db):
    await seed_all(db)
    params = await get_fiscale_params(db, 2025)
    assert params.zelfstandigenaftrek == 2470
    assert params.mkb_vrijstelling_pct == 12.70
```

**Step 3: Run test, verify pass**

**Step 4: Hook seed into main.py startup (only if tables empty)**

**Step 5: Commit**

```bash
git add .
git commit -m "feat: seed data for klanten and fiscale params 2023-2027"
```

---

## Task 4: Werkdagen Page (Core Feature)

**Files:**
- Modify: `pages/werkdagen.py` (full implementation)
- Create: `components/werkdag_form.py`
- Modify: `database.py` (add werkdag queries if not yet complete)
- Test: `tests/test_werkdagen.py`

**Step 1: Write database queries for werkdagen**

In `database.py`:
- `get_werkdagen(db_path, jaar=None, maand=None, klant_id=None)` — returns list of Werkdag with klant_naam joined
- `add_werkdag(db_path, **kwargs)` → returns new id
- `update_werkdag(db_path, id, **kwargs)`
- `delete_werkdag(db_path, id)`
- `get_werkdagen_ongefactureerd(db_path, klant_id=None)` — for invoice creation

**Step 2: Write werkdag_form.py component**

A reusable form card:
- Datum: `ui.date` with calendar popup
- Klant: `ui.select` from klanten table — on change: auto-fills tarief + km
- Uren: `ui.number(step=0.5, min=0, max=24)`
- Code: `ui.select` with common codes (WERKDAG, WEEKEND_DAG, NACHTDIENST, etc.)
- Opmerking: `ui.input` (optional)
- Display auto-calculated: `Totaal: {uren} x EUR {tarief} = EUR {totaal}`
- Display: `Km-vergoeding: {km} x EUR 0,23 = EUR {km_vergoeding}`
- Urennorm toggle (default on, off for achterwacht)
- "Opslaan" button → calls add_werkdag, refreshes table

**Step 3: Build werkdagen page**

Layout:
1. Year/month filter row (ui.select for year, ui.select for month, ui.select for klant)
2. Werkdag form card (right side or collapsible)
3. `ui.table` with columns: Datum, Klant, Uren, Km, Tarief, Totaal, Status
4. Each row: edit button (opens form pre-filled), delete button (with confirm)
5. Checkbox column for bulk selection
6. "Maak factuur" button (enabled when rows selected)
7. Summary row at bottom: totaal uren, totaal km, totaal bedrag

Table configuration:
```python
columns = [
    {'name': 'datum', 'label': 'Datum', 'field': 'datum', 'sortable': True},
    {'name': 'klant', 'label': 'Klant', 'field': 'klant_naam', 'sortable': True},
    {'name': 'uren', 'label': 'Uren', 'field': 'uren', 'sortable': True},
    {'name': 'km', 'label': 'Km', 'field': 'km'},
    {'name': 'tarief', 'label': 'Tarief', 'field': 'tarief',
     'format': lambda v: f'EUR {v:,.2f}'},
    {'name': 'totaal', 'label': 'Totaal', 'field': 'totaal',
     'format': lambda v: f'EUR {v:,.2f}'},
    {'name': 'status', 'label': 'Status', 'field': 'status'},
]
```

Status color coding: use slot template with colored chips.

**Step 4: Write tests**

```python
# tests/test_werkdagen.py
@pytest.mark.asyncio
async def test_add_werkdag_calculates_totals(db):
    await seed_all(db)
    klanten = await get_klanten(db)
    kid = klanten[0].id  # Klant6
    wid = await add_werkdag(db, datum='2026-02-23', klant_id=kid,
                            uren=9, km=52, tarief=77.50)
    werkdagen = await get_werkdagen(db, jaar=2026)
    assert len(werkdagen) == 1
    assert werkdagen[0].uren == 9
    assert werkdagen[0].km == 52

@pytest.mark.asyncio
async def test_filter_werkdagen_by_year(db):
    # add werkdagen for 2025 and 2026, verify filter works
    ...
```

**Step 5: Run tests, verify pass**

**Step 6: Manual test — open browser, add a werkdag, verify it appears in table**

**Step 7: Commit**

```bash
git add .
git commit -m "feat: werkdagen page with add/edit/delete and filtering"
```

---

## Task 5: Facturen Page (Invoice Generation)

**Files:**
- Modify: `pages/facturen.py`
- Create: `components/invoice_generator.py`
- Create: `templates/factuur.html` (Jinja2 HTML template for WeasyPrint)
- Modify: `database.py` (add factuur queries)
- Test: `tests/test_facturen.py`

**Step 1: Create Jinja2 HTML invoice template**

Create `templates/factuur.html` — a professional HTML/CSS invoice template that WeasyPrint renders to PDF. Must include all wettelijke vereisten:

```
Template layout:
- Header: TestBV logo/naam, KvK 00000000, adres, IBAN
- Factuur metadata: nummer (YYYY-NNN), datum, vervaldatum (+14 dagen)
- Klant blok: naam, adres
- Tabel: line items (datum, omschrijving, uren, tarief, bedrag)
  - Per werkdag: "Waarneming dagpraktijk" + datum
  - Per werkdag met km: "Reiskosten retour Groningen – [locatie]" + km × €0,23
- Totaal bedrag
- BTW-tekst: "BTW vrijgesteld op grond van artikel 11, lid 1, sub g,
              Wet op de omzetbelasting 1968"
- Betaalinformatie: IBAN, factuurnummer als referentie
```

Use CSS `@page` rules for A4 formatting, clean typography.
Reference design: see `suggestions_AI/claude_response.md` Section 5 for a complete,
production-ready HTML/CSS invoice template with professional styling.

**Euro formatting utility** (for PDF template and display):
```python
def format_euro(value: float) -> str:
    """Format as Dutch currency: € 1.234,56"""
    if value is None:
        return "€ 0,00"
    return f"€ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def format_datum(iso_date: str) -> str:
    """Convert YYYY-MM-DD to DD-MM-YYYY for display."""
    if not iso_date:
        return ""
    parts = iso_date.split("-")
    return f"{parts[2]}-{parts[1]}-{parts[0]}"
```
Register as Jinja2 filters in the invoice generator for use in `factuur.html`.

**Step 2: Write invoice_generator.py**

```python
# components/invoice_generator.py
from pathlib import Path
from datetime import datetime, timedelta
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

TEMPLATE_DIR = Path("templates")

def generate_invoice(factuur_nummer: str, klant: dict, werkdagen: list[dict],
                     output_dir: Path) -> Path:
    """Render Jinja2 HTML template to PDF via WeasyPrint."""
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template('factuur.html')

    datum = datetime.now()
    vervaldatum = datum + timedelta(days=14)

    # Calculate line items + totals
    regels = []
    totaal = 0.0
    for wd in werkdagen:
        bedrag = wd['uren'] * wd['tarief']
        regels.append({
            'datum': wd['datum'],
            'omschrijving': wd.get('activiteit', 'Waarneming dagpraktijk'),
            'aantal': wd['uren'],
            'tarief': wd['tarief'],
            'bedrag': bedrag,
        })
        totaal += bedrag

        if wd['km'] > 0:
            km_bedrag = wd['km'] * 0.23
            regels.append({
                'datum': wd['datum'],
                'omschrijving': f"Reiskosten retour Groningen – {wd.get('locatie', '')}",
                'aantal': wd['km'],
                'tarief': 0.23,
                'bedrag': km_bedrag,
            })
            totaal += km_bedrag

    html_content = template.render(
        nummer=factuur_nummer,
        datum=datum.strftime('%d-%m-%Y'),
        vervaldatum=vervaldatum.strftime('%d-%m-%Y'),
        klant=klant,
        regels=regels,
        totaal=totaal,
    )

    output_path = output_dir / f"{factuur_nummer}_{klant['naam']}.pdf"
    HTML(string=html_content).write_pdf(output_path)
    return output_path
```

Direct PDF output — no manual conversion step needed.

**Step 3: Write facturen database queries**

- `get_facturen(db_path, jaar=None)` — with klant_naam joined
- `add_factuur(db_path, **kwargs)` → returns new id
- `get_next_factuurnummer(db_path, jaar)` → "YYYY-NNN" (sequential, no gaps)
- `mark_betaald(db_path, factuur_id)`
- `link_werkdagen_to_factuur(db_path, werkdag_ids, factuur_id, factuurnummer)`

**Step 4: Build facturen page**

1. Table: all facturen with columns (nummer, datum, klant, bedrag, status)
2. "Nieuwe factuur" button → opens dialog:
   - Select klant (dropdown)
   - Shows ongefactureerde werkdagen for that klant (checkboxes)
   - Preview totals
   - "Genereer factuur" → calls invoice_generator → marks werkdagen → saves factuur record
3. Row actions: "Betaald" toggle, "Download" button
4. Creditnota: separate "Creditnota" button (negative amount)

**Step 5: Write tests**

```python
@pytest.mark.asyncio
async def test_next_factuurnummer_sequential(db):
    # Add facturen 2026-001, 2026-002, verify next is 2026-003
    ...

@pytest.mark.asyncio
async def test_next_factuurnummer_first_of_year(db):
    # No facturen yet for 2026, verify returns 2026-001
    ...

def test_invoice_generator_creates_pdf(tmp_path):
    # Call generate_invoice with mock data, verify PDF file exists and is non-empty
    ...
```

**Step 6: Run tests, manual test**

**Step 7: Commit**

```bash
git add .
git commit -m "feat: facturen page with WeasyPrint PDF invoice generation"
```

---

## Task 6: Kosten Page

**Files:**
- Modify: `pages/kosten.py`
- Modify: `database.py` (add uitgaven queries)
- Test: `tests/test_kosten.py`

**Step 1: Write uitgaven database queries**

- `get_uitgaven(db_path, jaar=None, categorie=None)`
- `add_uitgave(db_path, **kwargs)`
- `update_uitgave(db_path, id, **kwargs)`
- `delete_uitgave(db_path, id)`
- `get_uitgaven_per_categorie(db_path, jaar)` — grouped sums
- `get_investeringen(db_path, jaar=None)` — where is_investering=1

**Step 2: Define expense categories**

```python
CATEGORIEEN = [
    'Pensioenpremie SPH',
    'Telefoon/KPN',
    'Verzekeringen',
    'Accountancy/software',
    'Representatie',
    'Lidmaatschappen',
    'Kleine aankopen',
    'Scholingskosten',
    'Bankkosten',
    'Investeringen',
]
```

**Step 3: Build kosten page**

1. Filter row: year, category dropdowns
2. "Uitgave toevoegen" form card:
   - Datum (date picker)
   - Categorie (dropdown)
   - Omschrijving (text)
   - Bedrag incl. BTW (number, EUR prefix)
   - Bestand (optional file upload → saves to `data/uitgaven/`)
   - Auto: if bedrag >= 450: show "Investering?" checkbox
   - If investering: show levensduur (dropdown: 3/4/5 jaar), restwaarde% (default 10), zakelijk% (default 100)
   - If Representatie: show note "80% aftrekbaar, 20% bijtelling"
3. Table: all uitgaven for selected year/category
4. Summary: totaal per categorie at bottom

**Step 4: Write tests + run**

**Step 5: Commit**

```bash
git add .
git commit -m "feat: kosten page with expense tracking and investment flagging"
```

---

## Task 7: Bank CSV Import Page

**Files:**
- Modify: `pages/bank.py`
- Create: `import_/rabobank_csv.py`
- Modify: `database.py` (add banktransacties queries)
- Test: `tests/test_bank_import.py`

**Step 1: Research Rabobank CSV format**

Rabobank CSV columns (semicolon-separated, UTF-8):
```
"IBAN/BBAN","Munt","BIC","Volgnr","Datum","Rentedatum","Bedrag","Saldo na trn",
"Tegenrekening IBAN/BBAN","Naam tegenpartij","Naam uiteindelijke partij",
"Naam initiërende partij","BIC tegenpartij","Code","Batch ID","Transactiereferentie",
"Machtigingskenmerk","Incassant ID","Betalingskenmerk","Omschrijving-1",
"Omschrijving-2","Omschrijving-3","Reden retour","Oorspr bedrag","Oorspr munt",
"Koers"
```

**Step 2: Write rabobank_csv.py parser**

```python
# import_/rabobank_csv.py
import csv
import io
from pathlib import Path
from datetime import datetime

def parse_rabobank_csv(file_path: Path) -> list[dict]:
    """Parse Rabobank CSV export into list of transaction dicts.

    Handles encoding changes (UTF-8-sig → ISO-8859-1 fallback)
    and date format variations (YYYY-MM-DD or DD-MM-YYYY).
    """
    raw = file_path.read_bytes()

    # Rabobank has changed encodings over the years
    for encoding in ('utf-8-sig', 'iso-8859-1'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Kan CSV-bestand niet decoderen")

    reader = csv.DictReader(io.StringIO(text))
    transactions = []

    for row in reader:
        # Parse date (handle both YYYY-MM-DD and DD-MM-YYYY)
        datum_str = row.get('Datum', '').strip()
        if not datum_str:
            continue
        try:
            datum = datetime.strptime(datum_str, '%Y-%m-%d').date().isoformat()
        except ValueError:
            datum = datetime.strptime(datum_str, '%d-%m-%Y').date().isoformat()

        # Amount: comma→dot for Dutch decimal notation
        bedrag = float(row.get('Bedrag', '0').replace(',', '.').strip('"'))

        # Merge description fields (Rabobank splits across 3 columns)
        omschrijving = ' '.join(filter(None, [
            row.get('Omschrijving-1', '').strip(),
            row.get('Omschrijving-2', '').strip(),
            row.get('Omschrijving-3', '').strip(),
        ]))

        transactions.append({
            'datum': datum,
            'bedrag': bedrag,
            'tegenrekening': row.get('Tegenrekening IBAN/BBAN', '').strip(),
            'tegenpartij': row.get('Naam tegenpartij', '').strip(),
            'omschrijving': omschrijving,
        })
    return transactions
```

Note: verify exact column names against the actual Rabobank export in
`2024/Documenten/bankafschrift_2024.csv` before finalizing.

**Step 3: Build bank page**

1. "Importeer CSV" file upload → calls parser → inserts into banktransacties
2. Archive original CSV to `data/bank_csv/`
3. Table: all transactions, color-coded by status
4. Uncategorized rows: dropdown to assign categorie or link to factuur/uitgave
5. Running saldo display (if available from CSV)
6. Filter by year/month

**Step 4: Write tests**

Test the CSV parser with a mock CSV file.

**Step 5: Commit**

```bash
git add .
git commit -m "feat: bank page with Rabobank CSV import and manual categorization"
```

---

## Task 8: Dashboard with ECharts

**Files:**
- Modify: `pages/dashboard.py`
- Create: `components/charts.py`
- Modify: `database.py` (add aggregation queries)

**Step 1: Write aggregation queries**

- `get_omzet_per_maand(db_path, jaar)` → list of (maand, totaal)
- `get_kosten_per_categorie(db_path, jaar)` → list of (categorie, totaal)
- `get_uren_ytd(db_path, jaar)` → total qualifying hours (urennorm=1)
- `get_kpis(db_path, jaar)` → dict with omzet, kosten, winst, uren, openstaand

**Step 2: Build charts.py**

```python
# components/charts.py
from nicegui import ui

def revenue_bar_chart(data_current: list, data_previous: list, jaar: int):
    """Monthly revenue bar chart with year-over-year comparison."""
    maanden = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun',
               'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dec']
    return ui.echart({
        'tooltip': {'trigger': 'axis'},
        'legend': {'data': [str(jaar), str(jaar - 1)]},
        'xAxis': {'type': 'category', 'data': maanden},
        'yAxis': {'type': 'value',
                  'axisLabel': {'formatter': 'EUR {value}'}},
        'series': [
            {'name': str(jaar), 'type': 'bar', 'data': data_current,
             'itemStyle': {'color': '#1976D2'}},
            {'name': str(jaar - 1), 'type': 'bar', 'data': data_previous,
             'itemStyle': {'color': '#E0E0E0'}},
        ],
    }).classes('w-full h-72')

def cost_donut_chart(data: list[dict]):
    """Cost breakdown donut chart."""
    return ui.echart({
        'tooltip': {'trigger': 'item',
                    'formatter': '{b}: EUR {c} ({d}%)'},
        'series': [{
            'type': 'pie', 'radius': ['40%', '70%'],
            'data': [{'value': d['totaal'], 'name': d['categorie']}
                     for d in data],
        }],
    }).classes('w-full h-72')
```

**Step 3: Build dashboard page**

1. Year selector at top (default: current year)
2. 4 KPI cards in a row:
   - Netto-omzet: `EUR {omzet:,.2f}` with bar_chart icon
   - Resultaat: `EUR {winst:,.2f}`
   - Bedrijfslasten: `EUR {kosten:,.2f}`
   - Urencriterium: `{uren} / 1.225 uur` with progress bar
3. Revenue bar chart (current year vs previous)
4. Cost donut chart
5. Quick action buttons: "Werkdag toevoegen" → navigate to /werkdagen, "Nieuwe factuur" → navigate to /facturen

KPI card component:
```python
def kpi_card(label: str, value: str, icon: str, color: str = 'primary'):
    with ui.card().classes('q-pa-md'):
        with ui.row().classes('items-center no-wrap'):
            ui.icon(icon).classes(f'text-{color} text-3xl q-mr-md')
            with ui.column().classes('gap-0'):
                ui.label(label).classes('text-caption text-grey')
                ui.label(value).classes('text-h6 text-weight-bold')
```

**Step 4: Manual test — verify dashboard loads with seed data**

**Step 5: Commit**

```bash
git add .
git commit -m "feat: dashboard with KPI cards, revenue chart, and cost breakdown"
```

---

## Task 9: Fiscal Calculation Engine

**Files:**
- Create: `fiscal/berekeningen.py`
- Create: `fiscal/afschrijvingen.py`
- Create: `fiscal/heffingskortingen.py`
- Test: `tests/test_fiscal.py`

**Step 1: Write afschrijvingen.py**

```python
# fiscal/afschrijvingen.py

def bereken_afschrijving(aanschaf_bedrag: float, restwaarde_pct: float,
                         levensduur: int, aanschaf_maand: int,
                         aanschaf_jaar: int, bereken_jaar: int) -> dict:
    """Calculate depreciation for a given year (pro-rata first year)."""
    restwaarde = aanschaf_bedrag * (restwaarde_pct / 100)
    afschrijfbaar = aanschaf_bedrag - restwaarde
    per_jaar = afschrijfbaar / levensduur

    # Years since purchase
    jaren_verstreken = bereken_jaar - aanschaf_jaar
    if jaren_verstreken < 0:
        return {'afschrijving': 0, 'boekwaarde': aanschaf_bedrag}

    # First year: pro-rata
    if jaren_verstreken == 0:
        maanden = 13 - aanschaf_maand  # dec=1, jan=12
        afschrijving = per_jaar * (maanden / 12)
    else:
        afschrijving = per_jaar

    # Cumulative depreciation
    cum = 0
    for j in range(jaren_verstreken + 1):
        if j == 0:
            maanden = 13 - aanschaf_maand
            cum += per_jaar * (maanden / 12)
        else:
            cum += per_jaar

    boekwaarde = max(aanschaf_bedrag - cum, restwaarde)
    afschrijving_dit_jaar = min(afschrijving, aanschaf_bedrag - cum + afschrijving - restwaarde)
    afschrijving_dit_jaar = max(afschrijving_dit_jaar, 0)

    return {
        'afschrijving': round(afschrijving_dit_jaar, 2),
        'boekwaarde': round(boekwaarde, 2),
        'per_jaar': round(per_jaar, 2),
    }
```

**Step 2: Write heffingskortingen.py**

Full bracket implementation, year-parameterized. Bracket tables are stored in Python dicts
(not DB) because they change annually and must be verified against belastingdienst.nl.

```python
# fiscal/heffingskortingen.py

# Year-specific arbeidskorting bracket tables
# Source: Belastingdienst tabellen per jaar
ARBEIDSKORTING_BRACKETS = {
    2023: [
        (0, 10741, 0.08231, 0),          # 8.231% van arbeidsinkomen
        (10741, 23201, 0.29861, 884),     # 884 + 29.861% boven 10.741
        (23201, 37691, 0.03085, 4605),    # 4605 + 3.085% boven 23.201
        (37691, 115295, -0.06510, 5052),  # 5052 - 6.510% boven 37.691 (afbouw)
        (115295, None, 0, 0),             # 0 boven afbouwgrens
    ],
    2024: [
        (0, 11491, 0.08425, 0),
        (11491, 24821, 0.31433, 968),
        (24821, 39958, 0.02471, 5158),
        (39958, 124935, -0.06510, 5532),
        (124935, None, 0, 0),
    ],
    2025: [
        (0, 12169, 0.08053, 0),
        (12169, 26288, 0.30030, 980),
        (26288, 43071, 0.02258, 5220),
        (43071, 129078, -0.06510, 5599),
        (129078, None, 0, 0),
    ],
    2026: [
        (0, 12740, 0.08425, 0),
        (12740, 27461, 0.30030, 1073),
        (27461, 43836, 0.02258, 5491),
        (43836, 131072, -0.06510, 5685),
        (131072, None, 0, 0),
    ],
}

def bereken_algemene_heffingskorting(verzamelinkomen: float, jaar: int, params: dict) -> float:
    """Calculate algemene heffingskorting based on income and year."""
    if verzamelinkomen <= params['ahk_drempel']:
        return params['ahk_max']
    afbouw = params['ahk_afbouw_pct'] / 100 * (verzamelinkomen - params['ahk_drempel'])
    return max(0, round(params['ahk_max'] - afbouw, 2))

def bereken_arbeidskorting(arbeidsinkomen: float, jaar: int) -> float:
    """Calculate arbeidskorting using full year-specific bracket tables."""
    brackets = ARBEIDSKORTING_BRACKETS.get(jaar)
    if not brackets:
        raise ValueError(f"Geen arbeidskorting-tabel voor jaar {jaar}")

    for lower, upper, rate, base in brackets:
        if upper is None or arbeidsinkomen <= upper:
            korting = base + rate * (arbeidsinkomen - lower)
            return round(max(0, korting), 2)
    return 0
```

Note: brackets must be verified against the official Belastingdienst tables when new
year parameters are published (typically December preceding the tax year).

**Step 3: Write berekeningen.py — full fiscal waterfall**

Use `decimal.Decimal` for all fiscal calculations to avoid floating-point drift across
the multi-step waterfall. Database stores REAL (float) — convert to Decimal on entry.
Return a comprehensive dataclass with every intermediate value (for display, testing, debugging).

```python
# fiscal/berekeningen.py
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

def D(v) -> Decimal:
    """Convert any numeric value to Decimal."""
    return Decimal(str(v))

def euro(v: Decimal) -> float:
    """Round Decimal to 2 places, return as float for display/storage."""
    return float(v.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

@dataclass
class FiscaalResultaat:
    """Complete fiscal calculation result — every intermediate value for waterfall display."""
    jaar: int
    # W&V
    omzet: float = 0.0
    kosten: float = 0.0
    afschrijvingen: float = 0.0
    winst: float = 0.0
    # Fiscale correcties
    repr_bijtelling: float = 0.0
    kia: float = 0.0
    fiscale_winst: float = 0.0
    # Ondernemersaftrek
    zelfstandigenaftrek: float = 0.0
    startersaftrek: float = 0.0
    na_ondernemersaftrek: float = 0.0
    mkb_vrijstelling: float = 0.0
    belastbare_winst: float = 0.0
    # IB
    verzamelinkomen: float = 0.0
    bruto_ib: float = 0.0
    ahk: float = 0.0
    arbeidskorting: float = 0.0
    netto_ib: float = 0.0
    zvw: float = 0.0
    # Resultaat
    voorlopige_aanslag: float = 0.0
    resultaat: float = 0.0  # positief = terug, negatief = bijbetalen
    # Controles
    uren_criterium: float = 0.0
    uren_criterium_gehaald: bool = False
    kosten_omzet_ratio: float = 0.0
    # Waarschuwingen
    waarschuwingen: list[str] = field(default_factory=list)

def bereken_volledig(omzet: float, kosten: float, afschrijvingen: float,
                     representatie: float, investeringen_totaal: float,
                     uren: float, params: dict, aov: float = 0,
                     woz: float = 0, hypotheekrente: float = 0,
                     voorlopige_aanslag: float = 0) -> FiscaalResultaat:
    """Complete fiscal waterfall using Decimal precision."""
    r = FiscaalResultaat(jaar=params.get('jaar', 0))
    w = []  # waarschuwingen

    # Convert to Decimal for calculation precision
    d_omzet = D(omzet)
    d_kosten = D(kosten)
    d_afschr = D(afschrijvingen)
    d_repr = D(representatie)
    d_invest = D(investeringen_totaal)

    # W&V
    d_winst = d_omzet - d_kosten - d_afschr
    r.omzet, r.kosten, r.afschrijvingen = omzet, kosten, afschrijvingen
    r.winst = euro(d_winst)

    # Fiscale correcties
    d_repr_bijtelling = d_repr * D('0.20')  # 20% niet-aftrekbaar
    d_kia = D(0)
    if D(params['kia_ondergrens']) < d_invest <= D(params['kia_bovengrens']):
        d_kia = d_invest * D(params['kia_pct']) / D(100)
    r.repr_bijtelling = euro(d_repr_bijtelling)
    r.kia = euro(d_kia)

    d_fiscale_winst = d_winst + d_repr_bijtelling - d_kia
    r.fiscale_winst = euro(d_fiscale_winst)

    # Ondernemersaftrek
    d_za = D(params['zelfstandigenaftrek'])
    d_sa = D(params.get('startersaftrek') or 0)
    r.zelfstandigenaftrek = euro(d_za)
    r.startersaftrek = euro(d_sa)

    d_na_oa = d_fiscale_winst - d_za - d_sa
    r.na_ondernemersaftrek = euro(d_na_oa)

    d_mkb = max(D(0), d_na_oa) * D(params['mkb_vrijstelling_pct']) / D(100)
    r.mkb_vrijstelling = euro(d_mkb)
    r.belastbare_winst = euro(max(D(0), d_na_oa - d_mkb))

    # IB berekening (schijventarief)
    # ... bracket calculation using Decimal ...
    # ... heffingskortingen using Decimal ...
    # ... ZVW bijdrage ...
    # (Full implementation follows same pattern as bereken_ib below)

    # Controles
    r.uren_criterium = uren
    r.uren_criterium_gehaald = uren >= 1225
    r.kosten_omzet_ratio = round(kosten / omzet * 100, 1) if omzet > 0 else 0
    if not r.uren_criterium_gehaald:
        w.append(f"Urencriterium niet gehaald: {uren:.0f} / 1.225 uur")
    if r.kosten_omzet_ratio > 30:
        w.append(f"Kosten/omzet ratio hoog: {r.kosten_omzet_ratio}%")
    r.waarschuwingen = w
    return r

# Also keep the individual functions for backward compatibility:

def bereken_wv(omzet: float, kosten: float, afschrijvingen: float) -> dict:
    """Winst-en-verliesrekening (simple version)."""
    winst = omzet - kosten - afschrijvingen
    return {'omzet': omzet, 'kosten': kosten, 'afschrijvingen': afschrijvingen, 'winst': winst}

def bereken_ib(verzamelinkomen: float, params: dict) -> dict:
    """IB Box 1 calculation with brackets (uses Decimal internally)."""
    d_vi = D(verzamelinkomen)

    # Schijf 1
    d_s1 = min(d_vi, D(params['schijf1_grens']))
    d_ib1 = d_s1 * D(params['schijf1_pct']) / D(100)

    # Schijf 2
    d_s2 = min(max(d_vi - D(params['schijf1_grens']), D(0)),
               D(params['schijf2_grens']) - D(params['schijf1_grens']))
    d_ib2 = d_s2 * D(params['schijf2_pct']) / D(100)

    # Schijf 3
    d_s3 = max(d_vi - D(params['schijf2_grens']), D(0))
    d_ib3 = d_s3 * D(params['schijf3_pct']) / D(100)

    d_bruto = d_ib1 + d_ib2 + d_ib3

    ahk = bereken_algemene_heffingskorting(verzamelinkomen, params['jaar'], params)
    ak = bereken_arbeidskorting(verzamelinkomen, params['jaar'])

    d_netto = max(D(0), d_bruto - D(ahk) - D(ak))
    d_zvw = min(d_vi, D(params['zvw_max_grondslag'])) * D(params['zvw_pct']) / D(100)

    return {
        'verzamelinkomen': euro(d_vi),
        'bruto_ib': euro(d_bruto),
        'ahk': ahk,
        'arbeidskorting': ak,
        'netto_ib': euro(d_netto),
        'zvw': euro(d_zvw),
    }
```

**Design decision:** `decimal.Decimal` is used **only in the fiscal engine** (berekeningen.py,
heffingskortingen.py). The rest of the app (database, UI, models) uses plain float.
This is a targeted precision improvement where it matters most — the multi-step tax waterfall.
Values enter as float, are converted to Decimal via `D()`, calculated precisely, and
returned as float via `euro()`. The Boekhouder golden tests validate correctness end-to-end.

**Step 4: Write tests — verify against Boekhouder reference data**

This is critical. Use Boekhouder 2023 and 2024 as regression tests:

```python
# tests/test_fiscal.py

def test_fiscale_winst_2024():
    """Verify against Boekhouder 2024: winst €95.145 → belastbare winst €76.776"""
    params = FISCALE_PARAMS[2024]
    result = bereken_fiscale_winst(
        winst=95145,
        representatie=550,  # 20% of €550 = €110 bijtelling
        investeringen_totaal=2919,  # MacBook Pro
        params=params
    )
    assert abs(result['belastbare_winst'] - 76776) < 50  # within EUR 50

def test_afschrijving_camera_2024():
    """Camera: €2.714, restw 10%, 4jr, aanschaf dec 2023."""
    result = bereken_afschrijving(
        aanschaf_bedrag=2714, restwaarde_pct=10,
        levensduur=4, aanschaf_maand=12, aanschaf_jaar=2023,
        bereken_jaar=2024
    )
    assert abs(result['afschrijving'] - 611) < 5
    assert abs(result['boekwaarde'] - 1492) < 10

# === Verification trace values (from Boekhouder cross-check) ===
# Use these exact intermediate values as test assertions:
#
# 2024 waterfall:
#   profit_after_kia          = 95,145
#   applied_za                = 3,750
#   applied_sa                = 2,123
#   profit_after_oa           = 89,272
#   mkb_vrijstelling          = round(89,272 × 0.1331) = 11,882
#   belastbare_winst          = 77,390
#   aov_deduction             = 614
#   verzamelinkomen           = 76,776  ✓
#   bruto_ib                  = 28,541.62
#   heffingskorting           = 0 (above phase-out)
#   arbeidskorting            = 3,135
#   netto_ib                  = 25,407
#   voorlopige_aanslag        = 28,544
#   resultaat                 = -3,137 (teruggave) ✓
#
# 2023 waterfall:
#   profit_after_kia          = 62,522
#   applied_za                = 5,030
#   applied_sa                = 2,123
#   profit_after_oa           = 55,369
#   mkb_vrijstelling          = round(55,369 × 0.14) = 7,752
#   belastbare_winst          = 47,617
#   aov_deduction             = 1,816
#   verzamelinkomen           = 45,801  ✓
#   bruto_ib                  = 16,914.31
#   heffingskorting           = 1,660
#   arbeidskorting            = 4,524
#   netto_ib                  = 10,730
#   voorlopige_aanslag        = 11,145
#   resultaat                 = -415 (teruggave) ✓
```

**Step 5: Run tests, iterate until Boekhouder reference numbers match**

**Step 6: Commit**

```bash
git add .
git commit -m "feat: fiscal engine — W&V, waterval, afschrijvingen, IB, heffingskortingen"
```

---

## Task 10: Jaarafsluiting Page

**Files:**
- Modify: `pages/jaarafsluiting.py`
- Modify: `database.py` (add year-end aggregation queries)

**Step 1: Write year-end aggregation queries**

- `get_omzet_totaal(db_path, jaar)` — sum facturen
- `get_kosten_per_categorie(db_path, jaar)` — sum uitgaven grouped by categorie
- `get_investeringen_voor_afschrijving(db_path, tot_jaar)` — all investeringen
- `get_representatie_totaal(db_path, jaar)`
- `get_uren_totaal(db_path, jaar, urennorm_only=True)`

**Step 2: Build jaarafsluiting page**

Single page with "Bereken" button. On click:

1. Fetch all data from queries
2. Call fiscal engine functions
3. Display sections (each in a ui.card):

**Section 1: Omzet**
- Totaal netto-omzet: EUR X

**Section 2: Kosten per categorie**
- Table: categorie | bedrag
- Totaal bedrijfslasten: EUR X

**Section 3: Afschrijvingen**
- Activastaat table: actief, aanschaf, bedrag, afschr/jr, boekwaarde 31-12
- Totaal afschrijvingen: EUR X

**Section 4: W&V-rekening**
- Formatted as per design doc template

**Section 5: Fiscale winstberekening**
- Full waterfall display

**Section 6: IB-schatting**
- Manual input fields: WOZ-waarde, hypotheekrente, AOV premie, voorlopige aanslag betaald
- "Herbereken" button
- Full IB waterfall display
- Resultaat: terug te ontvangen / bij te betalen

**Section 7: Controles**
- Kosten/omzet ratio (colored: groen if 20-25%, rood otherwise)
- Urencriterium: X uur (groen if > 1.225)

**Section 8: Export**
- "Download rapport" button → generates a summary (Jinja2 → HTML → download, or plain markdown)

**Step 3: Manual test with 2024 data (compare to Boekhouder)**

**Step 4: Commit**

```bash
git add .
git commit -m "feat: jaarafsluiting page with fiscal calculations and report"
```

---

## Task 11: Settings Dialog

**Files:**
- Create: `pages/instellingen.py` (or integrate into layout as dialog)
- Modify: `components/layout.py` (add settings trigger)

**Step 1: Build settings as a full-screen dialog or separate page**

Tabs:
1. **Klanten**: editable table (naam, tarief, km, adres, actief toggle)
   - Add/edit/delete buttons
2. **Fiscale parameters**: table per year, editable cells
3. **Backup**: "Download database" button → serves SQLite file
4. **Import**: "Import Urenregister" button (one-time, Task 12)

**Step 2: Commit**

```bash
git add .
git commit -m "feat: settings page with klanten management and backup"
```

---

## Task 12: Data Migration (Urenregister.xlsm Import)

**Files:**
- Create: `import_/urenregister.py`
- Test: `tests/test_import.py`

**Step 1: Write urenregister.py importer**

Read `Urenregister.xlsm` sheet 'Urentabel', columns A-U, rows 2-571.
Map to werkdagen table:
- F (Datum) → datum (convert from datetime)
- H (Klant) → match to klanten.id by name
- G (CODE) → code
- I (Activiteit) → activiteit
- J (Locatie) → locatie
- K (Uren) → uren
- L (Visite_km) → (not used directly, km comes from M)
- M (Retourafstand) → km
- N (Uurtarief) → tarief
- O (Kilometertarief) → km_tarief
- S (Status) → status
- T (Factuurnummer) → factuurnummer
- U (Opmerkingen) → opmerking
- Urennorm: check if code contains 'ACHTERWACHT' → urennorm=0

```python
import openpyxl
from pathlib import Path

def import_urenregister(xlsm_path: Path, db_path: Path):
    wb = openpyxl.load_workbook(xlsm_path, keep_vba=True, data_only=True)
    ws = wb['Urentabel']
    # ... read rows 2 to 571, map to werkdagen inserts
```

Also import facturen from existing PDF filenames:
```python
def import_facturen_from_pdfs(inkomsten_dir: Path, db_path: Path):
    """Scan YYYY/Inkomsten/**/*.pdf, parse filename for nummer + klant."""
    # Pattern: YYYY-NNN_Klant.pdf
    ...
```

**Step 2: Write test with a subset of real data**

**Step 3: Run import against actual Urenregister.xlsm, verify row counts**

**Step 4: Commit**

```bash
git add .
git commit -m "feat: data migration from Urenregister.xlsm and existing invoice PDFs"
```

---

## Task Order & Dependencies

```
Task 1: Scaffold + DB          (no deps)
Task 2: Layout + Nav           (depends on 1)
Task 3: Seed Data              (depends on 1)
Task 4: Werkdagen Page         (depends on 2, 3)
Task 5: Facturen Page          (depends on 4)
Task 6: Kosten Page            (depends on 2, 3)
Task 7: Bank CSV Import        (depends on 2)
Task 8: Dashboard              (depends on 4, 6)
Task 9: Fiscal Engine          (depends on 1)
Task 10: Jaarafsluiting        (depends on 8, 9)
Task 11: Settings              (depends on 2, 3)
Task 12: Data Migration        (depends on 4, 5, 6)
```

Parallel tracks possible:
- Track A: Tasks 1 → 2 → 4 → 5 (werkdagen + facturen)
- Track B: Task 9 (fiscal engine, independent)
- Track C: Tasks 6, 7 (kosten + bank, after layout)
- Merge: Tasks 8, 10 (dashboard + jaarafsluiting need all data)
- Final: Tasks 11, 12

---

## Verification Checklist

After all tasks complete, verify:

- [ ] Can add a werkdag and see it in the table
- [ ] Can select werkdagen and generate a PDF invoice (WeasyPrint)
- [ ] Invoice PDF has correct totals, klant info, BTW-vrijstelling text, IBAN
- [ ] Can add an expense with category
- [ ] Can import a Rabobank CSV and categorize transactions
- [ ] Dashboard shows correct KPIs and charts
- [ ] Jaarafsluiting produces correct fiscal calculations (compare to Boekhouder 2024)
- [ ] Heffingskortingen (AHK + arbeidskorting) calculate correctly per year
- [ ] Urencriterium correctly excludes achterwacht hours
- [ ] Settings: can edit client tariffs
- [ ] Backup downloads SQLite file
- [ ] App starts with `python main.py` and opens in browser
- [ ] 567 werkdagen imported from Urenregister.xlsm
- [ ] Sequential factuurnummering works (no gaps)
- [ ] PRAGMA foreign_keys = ON enforced on every connection
- [ ] CHECK constraints prevent invalid data entry

---

## AI Review Notes (2026-02-25)

External AI models (ChatGPT, Claude, Gemini) were consulted for architecture review.
Responses captured in `suggestions_AI/`. ChatGPT and Claude provided substantive feedback.

### Adopted from ChatGPT review

| Suggestion | Applied where |
|---|---|
| `PRAGMA foreign_keys = ON` | Task 1 — database init |
| Database indexes on commonly-queried columns | Task 1 — 6 indexes added |
| CHECK constraints on key fields | Task 1 — schema hardening |
| Robust gapless invoice numbering | Task 5 — `get_next_factuurnummer` uses MAX+1 from facturen table |
| Full arbeidskorting bracket tables per year | Task 9 — replaced simplified max-value approach |
| Year-parameterized heffingskortingen | Task 9 — `bereken_arbeidskorting(inkomen, jaar)` |
| WeasyPrint for direct PDF output | Task 5 — rewritten from openpyxl to WeasyPrint + Jinja2 |
| Proof-number tests against Boekhouder | Task 9 — already planned, confirmed as correct approach |

### Adopted from Claude review

| Suggestion | Applied where |
|---|---|
| `decimal.Decimal` for fiscal engine | Task 9 — targeted use in berekeningen.py waterfall (not everywhere) |
| `FiscaalResultaat` comprehensive dataclass | Task 9 — returns all intermediate values for display/testing/debugging |
| Warnings system (`waarschuwingen: list[str]`) | Task 9 — alerts about urencriterium, kosten/omzet ratio, etc. |
| Revenue sourced from invoices (not werkdagen) | Task 10 — omzet = gefactureerd bedrag, niet gewerkte uren |
| `D()` / `euro()` helper pattern | Task 9 — clean Decimal conversion utilities |
| `PRAGMA journal_mode = WAL` | Task 1 — crash resilience + concurrent reads |
| Euro/datum formatting utilities | Task 5 — `format_euro()`, `format_datum()` as Jinja2 filters |
| Encoding + date fallback in CSV parser | Task 7 — UTF-8-sig → ISO-8859-1, YYYY-MM-DD / DD-MM-YYYY |
| Verification trace values for tests | Task 9 — exact intermediate values from Boekhouder 2023+2024 |
| 2023 km_tarief = €0.21 correction | Task 3 — was incorrectly 0.23, corrected to 0.21 |
| Professional PDF template reference | Task 5 — Claude's HTML/CSS design as starting point |

### Discarded from review (overengineering)

| Suggestion | Source | Why discarded |
|---|---|---|
| FastAPI + React + TypeScript frontend | ChatGPT | NiceGUI is single-language Python, no build step, perfect for single-user localhost |
| Flask + htmx + Alpine.js | Claude | Same reasoning — NiceGUI is simpler, fewer files, one language |
| SQLAlchemy ORM + Alembic migrations | ChatGPT | 6 tables, raw SQL is clearer and simpler |
| 16-table normalized schema | ChatGPT | 6 tables covers all use cases without unnecessary joins |
| 11-table schema with separate assets/bank_imports | Claude | 6 tables sufficient; investments tracked via `is_investering` flag |
| Integer cents for money storage | ChatGPT | Float with `round()` is fine; Decimal used only in fiscal engine |
| `Decimal` everywhere (not just fiscal) | Both | Targeted Decimal in fiscal engine; float elsewhere for simplicity |
| VOID invoice support | ChatGPT | Creditnota is the Dutch standard; single-user won't accidentally create invoices |
| Automatic backup zips | Both | SynologyDrive already syncs to NAS; manual download button suffices |
| SHA256 document hashing / CSV dedup | Both | Over-engineering for single-user; user notices duplicate imports |
| Separate `invoice_counters` table | ChatGPT | Single-user: MAX+1 query on facturen table is safe and simple |
| Normalized tax bracket/credit tables in DB | Claude | Brackets in Python dicts (change annually, need verification anyway) |
| `settings` table for business identity | Claude | Business identity rarely changes; hardcode in Jinja2 PDF template |
| `created_at`/`updated_at` on all tables | Claude | Single-user audit trail not needed; adds boilerplate |
| Separate `assets` table | Claude | Investments tracked adequately in `uitgaven` with is_investering flag |

---

## Known Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Fiscal rounding drift** | IB result off by a few euros | `decimal.Decimal` in fiscal engine + Boekhouder golden tests for 2023+2024 |
| **Tax parameter accuracy (2025+)** | Incorrect deductions | Editable in Settings page; verify against belastingdienst.nl annually |
| **WeasyPrint installation** | PDF generation fails | Document `brew install weasyprint` in setup; test early in Task 1 |
| **Rabobank CSV format changes** | Import breaks | Encoding fallback + flexible parser; raw CSV archived for manual recovery |
| **Invoice numbering during migration** | Gaps or duplicates | `MAX()+1` query on facturen table handles imported historical numbers correctly |
| **2023 km_tarief difference** | Wrong km deduction | Seed data uses €0.21 for 2023, €0.23 for 2024+; werkdagen snapshot per-row km_tarief |
