# TestBV Boekhouding App — Design Document

**Date:** 2026-02-23
**Status:** Approved
**Stack:** NiceGUI + SQLite + ECharts + WeasyPrint + Jinja2
**Deployment:** Native Python on macOS (MacBook Pro)
**Language:** Python (100%), UI in Dutch

---

## Problem Statement

TestBV (waarnemend huisarts, eenmanszaak) currently uses 3 separate tools:
- Moneybird (web) for invoicing and bookkeeping
- Urenregister.xlsm (Excel) for hours/km tracking
- Claude Code for fiscal calculations and audits

Goal: **one standalone web app** that replaces all three, enabling independent bookkeeping without an accountant. The app runs natively on macOS (`python main.py` → localhost:8085), with data synced to NAS via SynologyDrive.

## Business Context

- ~EUR 125k revenue/year, 5 clients, ~10 expense categories
- BTW-vrijgesteld (art. 11 lid 1 sub g Wet OB) — no VAT administration
- No employees, no inventory, no payroll
- ~8-12 invoices/month, ~10 expense receipts/month
- Fiscal partner: A.A.H. Nijholt
- Bewaarplicht: 7 jaar digitaal

## Architecture

```
Browser (localhost on MacBook)
    |
    v
NiceGUI (Python, Quasar/Vue under the hood)
    |
    +-- SQLite (boekhouding.sqlite3) — all transactional data
    +-- WeasyPrint + Jinja2 — PDF invoice generation from HTML template
    +-- ECharts — dashboard charts
    +-- File storage — PDFs (receipts, invoices)
    |
    v
Native Python process on macOS (python main.py → localhost:8085)
Data synced to NAS via SynologyDrive
```

### Tech Stack

| Component | Library | Why |
|-----------|---------|-----|
| UI framework | NiceGUI 3.x | Python-only, data binding, FastAPI underneath |
| Database | aiosqlite (raw SQL) | Simple, no ORM needed for 6 tables |
| Charts | ECharts (via `ui.echart`) | Polished, built into NiceGUI |
| Invoices | WeasyPrint + Jinja2 | HTML template → PDF, direct output |
| Excel lezen | openpyxl | Alleen voor eenmalige data-migratie |
| HTTP client | httpx | Future API integrations |
| Deployment | Native macOS | `python main.py`, data synced via SynologyDrive |

### Dependencies (8 packages)

```
nicegui>=3.0
aiosqlite
openpyxl
httpx
jinja2
weasyprint
pytest
pytest-asyncio
```

## Data Model

### 6 Tables (raw SQL, no ORM)

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE klanten (
    id INTEGER PRIMARY KEY,
    naam TEXT NOT NULL,
    tarief_uur REAL NOT NULL CHECK (tarief_uur >= 0),
    retour_km REAL DEFAULT 0 CHECK (retour_km >= 0),
    adres TEXT,
    kvk TEXT,
    actief INTEGER DEFAULT 1 CHECK (actief IN (0, 1))
);

CREATE TABLE werkdagen (
    id INTEGER PRIMARY KEY,
    datum TEXT NOT NULL,          -- ISO date YYYY-MM-DD
    klant_id INTEGER NOT NULL REFERENCES klanten(id),
    code TEXT,                    -- activity code
    activiteit TEXT DEFAULT 'Waarneming dagpraktijk',
    locatie TEXT,
    uren REAL NOT NULL CHECK (uren > 0),
    km REAL DEFAULT 0 CHECK (km >= 0),
    tarief REAL NOT NULL CHECK (tarief >= 0),
    km_tarief REAL DEFAULT 0.23,
    status TEXT DEFAULT 'ongefactureerd',  -- ongefactureerd/gefactureerd/betaald
    factuurnummer TEXT,
    opmerking TEXT,
    urennorm INTEGER DEFAULT 1 CHECK (urennorm IN (0, 1))
);

CREATE INDEX idx_werkdagen_datum ON werkdagen(datum);
CREATE INDEX idx_werkdagen_klant ON werkdagen(klant_id);
CREATE INDEX idx_werkdagen_status ON werkdagen(status);

CREATE TABLE facturen (
    id INTEGER PRIMARY KEY,
    nummer TEXT NOT NULL UNIQUE,  -- YYYY-NNN format
    klant_id INTEGER NOT NULL REFERENCES klanten(id),
    datum TEXT NOT NULL,
    totaal_uren REAL,
    totaal_km REAL,
    totaal_bedrag REAL NOT NULL CHECK (totaal_bedrag >= 0),
    pdf_pad TEXT,
    betaald INTEGER DEFAULT 0 CHECK (betaald IN (0, 1)),
    betaald_datum TEXT,
    type TEXT DEFAULT 'factuur'   -- factuur/creditnota
);

CREATE INDEX idx_facturen_klant ON facturen(klant_id);

CREATE TABLE uitgaven (
    id INTEGER PRIMARY KEY,
    datum TEXT NOT NULL,
    categorie TEXT NOT NULL,
    omschrijving TEXT NOT NULL,
    bedrag REAL NOT NULL CHECK (bedrag >= 0),  -- altijd incl. BTW (BTW-vrijgesteld: geen aftrek)
    pdf_pad TEXT,
    is_investering INTEGER DEFAULT 0 CHECK (is_investering IN (0, 1)),
    -- for investeringen:
    restwaarde_pct REAL DEFAULT 10,
    levensduur_jaren INTEGER,
    aanschaf_bedrag REAL,
    zakelijk_pct REAL DEFAULT 100 CHECK (zakelijk_pct BETWEEN 0 AND 100)
);

CREATE INDEX idx_uitgaven_datum ON uitgaven(datum);

CREATE TABLE banktransacties (
    id INTEGER PRIMARY KEY,
    datum TEXT NOT NULL,
    bedrag REAL NOT NULL,         -- positief=bij, negatief=af
    tegenrekening TEXT,
    tegenpartij TEXT,
    omschrijving TEXT,
    categorie TEXT,               -- matched expense category or 'omzet'
    koppeling_type TEXT,          -- 'factuur'/'uitgave'/NULL
    koppeling_id INTEGER,
    csv_bestand TEXT              -- source CSV filename for bewaarplicht
);

CREATE INDEX idx_banktransacties_datum ON banktransacties(datum);

CREATE TABLE fiscale_params (
    jaar INTEGER PRIMARY KEY,
    zelfstandigenaftrek REAL,
    startersaftrek REAL,          -- NULL als niet van toepassing
    mkb_vrijstelling_pct REAL,
    kia_ondergrens REAL,
    kia_bovengrens REAL,
    kia_pct REAL,
    km_tarief REAL,
    schijf1_grens REAL,
    schijf1_pct REAL,
    schijf2_grens REAL,
    schijf2_pct REAL,
    schijf3_pct REAL,
    ahk_max REAL,                -- algemene heffingskorting
    ahk_afbouw_pct REAL,
    ahk_drempel REAL,
    ak_max REAL,                 -- arbeidskorting (simplified: max value)
    zvw_pct REAL,
    zvw_max_grondslag REAL,
    repr_aftrek_pct REAL DEFAULT 80
);
```

### Pre-seeded Data

- **klanten**: 5 rows (Klant6, Klant7, Winsum, Klant2, Klant15)
- **fiscale_params**: 2023-2027 (all known values from Belastingdienst)
- **werkdagen**: imported from Urenregister.xlsm (567 rows)
- **facturen**: imported from existing PDF inventory (160 invoices)
- **uitgaven**: imported from Moneybird export or manual entry

### Expense Categories (pre-defined)

```
Pensioenpremie SPH        100% aftrekbaar
Autokosten (km)           berekend uit werkdagen
Telefoon/KPN              zakelijk deel documenteren
Verzekeringen             100% (excl. AOV — die is Box 1)
Accountancy/software      100%
Representatie             80% aftrekbaar (20% bijtelling)
Lidmaatschappen           100%
Kleine aankopen (<EUR450) 100% direct
Scholingskosten           100%
Bankkosten                100%
Investeringen (>=EUR450)  via afschrijving + KIA
```

## Pages (6 + Settings)

### 1. Dashboard (/)

**Layout:**
- 4 KPI cards top row: Netto-omzet YTD | Resultaat (winst) | Bedrijfslasten | Urencriterium (X / 1.225 uur)
- ECharts bar chart: monthly revenue (current year in color, previous year in grey)
- ECharts donut chart: cost breakdown by category
- Quick action buttons: "Werkdag toevoegen", "Nieuwe factuur"
- Year selector dropdown

**Data source:** Aggregated queries on werkdagen, facturen, uitgaven.

### 2. Werkdagen (/werkdagen)

**Layout:**
- NiceGUI `ui.table` with all workdays, sortable + filterable
- "Toevoegen" form in a card:
  - Datum (date picker)
  - Klant (dropdown — auto-fills tarief + retour km)
  - Uren (number input, step 0.5)
  - Code/Activiteit (optional dropdown)
  - Opmerking (text, optional)
  - Auto-calculated: Totaal = uren x tarief, Km-vergoeding = km x 0.23
- Inline editing: click cell to edit directly
- Filter tabs: per year, per month, per client
- Checkbox column for bulk selection
- "Maak factuur van selectie" button
- Status indicator: colored dot (ongefactureerd=grijs, gefactureerd=blauw, betaald=groen)

**Business rules:**
- Selecting klant auto-fills tarief + km from klanten table
- Urennorm default=1, set to 0 for achterwacht entries
- Status changes when factuur is created or payment marked

### 3. Facturen (/facturen)

**Layout:**
- Table: nummer, datum, klant, bedrag, status (concept/verzonden/betaald)
- "Nieuwe factuur" flow:
  1. Select werkdagen (from /werkdagen or picker here)
  2. Preview: line items, totals, km-vergoeding
  3. Generate: renders Jinja2 HTML → WeasyPrint PDF → saves to data/facturen/
  4. Nummer auto-assigned (YYYY-NNN, sequential)
- Factuur detail view: show line items, download PDF
- "Markeer als betaald" button
- Creditnota: negative amount factuur

**Invoice generation (WeasyPrint + Jinja2):**
- Template: `templates/factuur.html` — Jinja2 HTML with CSS @page rules for A4
- Rendered via WeasyPrint directly to PDF (no Excel intermediary)
- Fields: header (TestBV info, KvK, IBAN), klant details, line items (werkdagen + reiskosten), totaal
- Footer: "BTW vrijgesteld op grond van artikel 11, lid 1, sub g, Wet op de omzetbelasting 1968"
- Save PDF to: `data/facturen/YYYY-NNN_Klant.pdf`

### 4. Kosten (/kosten)

**Layout:**
- Table: datum, categorie, omschrijving, bedrag, with year/category filter
- "Toevoegen" form:
  - Datum
  - Categorie (dropdown with pre-defined list)
  - Omschrijving
  - Bedrag (incl. BTW)
  - Bestand (optional file path or upload)
- Auto-flag: bedrag >= 450 shows "Investering?" checkbox
- If investering: additional fields (levensduur, restwaarde%, zakelijk%)
- Category-specific: Representatie auto-notes "80% aftrekbaar"
- Year totals per category at bottom

### 5. Bank (/bank)

**Layout:**
- "Importeer CSV" button (file upload, Rabobank CSV format)
- Transaction table: datum, bedrag, tegenpartij, omschrijving, categorie, koppeling
- For uncategorized rows: dropdown to assign category or link to factuur/uitgave
- Color coding: groen=gekoppeld, oranje=gecategoriseerd, rood=niet-gekoppeld
- Running saldo display
- Archive: list of imported CSV files (for bewaarplicht)

**Rabobank CSV format support:**
- Standard columns: Datum, Naam/Omschrijving, Rekening, Tegenrekening, Code, Af/Bij, Bedrag, Mutatie-soort, Mededelingen
- Parse on import, store in banktransacties table

### 6. Jaarafsluiting (/jaarafsluiting)

**Layout:**
- Year selector
- "Bereken" button → generates full report on one page:

**Report sections (all calculated, displayed in sequence):**

1. **Omzet** — totaal dagpraktijk + ANW, from facturen table
2. **Kosten per categorie** — from uitgaven table, with subtotals
3. **Afschrijvingen** — calculated from uitgaven where is_investering=1:
   - Pro-rata first year (by month of purchase)
   - Lineair, 10% restwaarde
   - Shows activastaat: item, aanschaf, afschr/jr, boekwaarde 31-12
4. **W&V-rekening** — formatted as per CLAUDE.md template
5. **Fiscale winstberekening:**
   - Winst jaarrekening
   - + Niet-aftrekbare representatie (20%)
   - - KIA (28% if applicable)
   - = Fiscale winst
   - - Zelfstandigenaftrek
   - - Startersaftrek (if applicable)
   - = Na ondernemersaftrek
   - x (1 - MKB-winstvrijstelling%)
   - = Belastbare winst
6. **IB-schatting:**
   - Belastbare winst
   - + Eigen woning saldo (manual input: WOZ, hypotheekrente)
   - - AOV premie (manual input)
   - = Verzamelinkomen
   - Bruto IB (per schijf)
   - - Heffingskortingen (berekend)
   - = Netto IB
7. **ZVW** — 5,26% x belastbare winst
8. **Controles:**
   - Kosten/omzet ratio (target ~22-23%)
   - Urencriterium check (>1.225?)
   - Compare with previous years

**Export:** "Download rapport PDF" button (generates overview)

### 7. Instellingen (dialog/drawer)

- **Klanten**: CRUD table (naam, tarief, km, adres, actief toggle)
- **Fiscale parameters**: per-year values, pre-filled through 2027
- **Categorieën**: view/edit expense categories
- **Backup**: "Download database + PDFs" as ZIP
- **Import**: one-time Urenregister.xlsm migration wizard

## Deployment

### Native macOS (MacBook Pro)

```bash
# One-time setup
cd ~/Library/CloudStorage/SynologyDrive-Main/06_Development/roberg-boekhouding
pip install -r requirements.txt

# Run
python main.py
# → opens http://localhost:8085 in default browser
```

### Launch script (double-click to start)

```bash
#!/bin/bash
# start-boekhouding.command
cd "$(dirname "$0")"
python3 main.py
```

### Data persistence

- SQLite + PDFs stored in `data/` subdirectory
- Project lives in SynologyDrive folder → auto-synced to NAS as backup
- No Docker, no server, no containers

## Project Structure

```
roberg-boekhouding/
├── main.py                     # Entry point, page registration
├── database.py                 # SQLite connection, schema, queries
├── models.py                   # Dataclasses (not ORM — plain Python)
├── pages/
│   ├── dashboard.py
│   ├── werkdagen.py
│   ├── facturen.py
│   ├── kosten.py
│   ├── bank.py
│   └── jaarafsluiting.py
├── components/
│   ├── layout.py               # Sidebar nav, page header
│   ├── werkdag_form.py         # Reusable werkdag add/edit form
│   ├── charts.py               # ECharts builders
│   └── invoice_generator.py    # WeasyPrint PDF factuur generator
├── fiscal/
│   ├── berekeningen.py         # W&V, fiscale waterval, IB
│   ├── afschrijvingen.py       # Activastaat, pro-rata
│   └── heffingskortingen.py    # AHK, arbeidskorting tables
├── import_/                    # Underscore: avoid conflict with Python import keyword
│   ├── urenregister.py         # One-time xlsm import
│   ├── rabobank_csv.py         # Bank CSV parser
│   └── seed_data.py            # Pre-fill klanten, fiscale_params
├── templates/
│   └── factuur.html            # Jinja2 HTML template for WeasyPrint PDF
├── data/                       # Persistent data (auto-synced via SynologyDrive)
│   ├── boekhouding.sqlite3
│   ├── facturen/               # Generated invoice PDFs
│   ├── uitgaven/               # Uploaded receipt PDFs
│   └── bank_csv/               # Archived CSV imports
├── start-boekhouding.command   # Double-click to launch
└── requirements.txt
```

## Not Included (YAGNI)

- No user authentication (single user, local network)
- No BTW administration (BTW-vrijgesteld)
- No payroll/inventory
- No email integration (download PDF, email manually)
- No real-time bank API (CSV import only, for now)
- No auto-matching engine (manual bank categorization)
- No ORM (raw SQL is fine for 6 tables)
- No CI/CD (local development only)
- No multi-language (Dutch only)
- No mobile-specific UI (responsive web)

## Migration Plan

1. Import Urenregister.xlsm → werkdagen table (567 rows)
2. Seed klanten from existing data (5 clients)
3. Seed facturen from existing PDF inventory (160 invoices, parsed from filenames)
4. Seed fiscale_params for 2023-2027
5. Historical uitgaven: either import from Moneybird export or enter for 2025+ only
6. Create Jinja2 HTML invoice template for WeasyPrint

## Legal Compliance Verification

| Requirement | How the app satisfies it |
|-------------|------------------------|
| Administratieplicht (Art. 52 AWR) | Complete income/expense/bank records |
| Bewaarplicht (7 jaar) | SQLite + PDFs + archived CSVs, backup function |
| Factuureisen | Template includes all required fields + BTW-vrijstelling text |
| Grootboek | Bank + kosten categorized by grootboekrekening |
| Debiteurenadministratie | Facturen with payment status |
| Crediteurenadministratie | Uitgaven with date + supplier |
| Urenregistratie | Werkdagen with urennorm flag |
| Kilometeradministratie | Werkdagen with km per client per day |
| Activastaat | Uitgaven where is_investering=1, with depreciation fields |
