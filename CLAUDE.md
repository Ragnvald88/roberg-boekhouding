# Boekhouding App

Standalone boekhoudapplicatie (NiceGUI + Python) voor een eenmanszaak huisartswaarnemer. Draait lokaal op macOS, opent in browser. Data in `data/` (niet in git).

## Tech Stack
- **UI**: NiceGUI >=3.0 (Quasar/Vue), browser mode (`ui.run(host='127.0.0.1', port=8085)`)
- **Database**: SQLite via aiosqlite, raw SQL met `?` placeholders, GEEN ORM
- **PDF**: WeasyPrint + Jinja2, **Charts**: ECharts via `ui.echart`
- **Python**: 3.12+

## Commands
```bash
# Start
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py  # → http://127.0.0.1:8085

# Tests (362 passing)
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

## Database
9 tabellen: `klanten`, `klant_locaties`, `werkdagen`, `facturen`, `uitgaven`, `banktransacties`, `fiscale_params`, `bedrijfsgegevens`, `aangifte_documenten`

- Raw SQL, `?` placeholders — GEEN f-strings in SQL
- Bedragen REAL, datums TEXT (YYYY-MM-DD)
- `aiosqlite` async, WAL mode, foreign keys ON
- `bedrijfsgegevens` = single-row (CHECK id=1)
- SQLite op lokaal filesystem, NIET via SMB (WAL faalt)

## Ontwikkelregels

### Architectuur
- Browser mode ALTIJD — NOOIT native/pywebview
- Shared layout via `components/layout.py`
- Elke pagina is `@ui.page('/route')` in eigen bestand
- `format_euro`/`format_datum` ALLEEN uit `components/utils.py`
- **Fiscal utils**: `components/fiscal_utils.py` (shared `fiscale_params_to_dict` + `fetch_fiscal_data`)
- **Fiscal engine**: `fiscal/berekeningen.py` (bereken_volledig waterfall + bereken_box3)
- **Heffingskortingen**: `fiscal/heffingskortingen.py` (AK brackets + AHK)
- **KPI cards**: `components/kpi_card.py` (shared kpi_card + kpi_strip)

### NiceGUI Patronen
- `ui.table` (NIET AG Grid), `ui.echart` voor charts
- **Tabel selectie**: ALTIJD `selection='multiple'`. NOOIT custom checkbox slots met `$parent.$emit`. Gebruik `table.selected` en `table.on('selection', handler)`.
- Bij full `body` slot met selectie: `<q-checkbox v-model="props.selected" dense />` (Quasar-managed), NIET `v-model="props.row.selected"`.
- **Add/edit formulieren**: via `ui.dialog()` popup, NIET inline op de pagina. Referentie: werkdag_form.py, kosten.py, facturen.py.
- Quasar semantic kleuren (`positive`, `negative`, `warning`, `primary`) — geen hardcoded hex in pagina's

### YAGNI
Geen: user auth, BTW-administratie, loon/voorraad, email, real-time bank-API, auto-matching, CI/CD, multi-language

## Domeinkennis (fiscaal)

### Basisregels
- **BTW-vrijgesteld** (art. 11 Wet OB) → kosten INCL BTW, geen BTW-aangifte
- **Urencriterium**: 1.225 uur/jaar. Achterwacht (urennorm=0) telt NIET mee
- **AOV**: GEEN bedrijfskosten → Box 1 inkomensvoorziening
- **KIA**: 28% bij totaal investeringen >= €2.901 (inclusive)
- **Afschrijvingen**: lineair, restwaarde 10%, eerste jaar pro-rata per maand
- **Representatie**: 80%-regeling (configureerbaar in `fiscale_params`)
- **Factuur vereisten**: naam+adres+KvK, factuurnummer YYYY-NNN, vervaldatum 14d, BTW-vrijstellingstekst

### DB-driven parameters (alle configureerbaar in Instellingen)
- **Arbeidskorting**: JSON brackets in `arbeidskorting_brackets` column, fallback to Python constants in `heffingskortingen.py`
- **PVV rates**: `pvv_aow/anw/wlz_pct` columns (default 17.90/0.10/9.65), fallback to constants
- **Box 3**: Per-jaar rendementen (bank/overig/schuld), heffingsvrij vermogen, tarief, drempel schulden
- **Alle andere**: ZA, SA, MKB%, KIA, AHK, AK, ZVW, schijf1/2/3, EW forfait, villataks, Wet Hillen, etc.
- **ZA/SA toggles**: `za_actief`/`sa_actief` booleans per year (DB-driven, editable in Instellingen + Jaarafsluiting)
- **Lijfrentepremie**: `lijfrente_premie` per year (reduces verzamelinkomen)
- **Input velden** (preserved across param upserts): AOV, WOZ, hypotheekrente, VA IB, VA ZVW, partner, Box 3 saldi, ew_naar_partner, lijfrente_premie, balans inputs

### Fiscal engine
- **Arbeidskorting input** = fiscale_winst (vóór ZA/SA/MKB), NOT belastbare_winst
- **Tariefsaanpassing**: Since 2023, deductions at basistarief only. Excess clawed back.
- **Eigen woning**: Configurable `ew_naar_partner`. Default True (Boekhouder practice).
- **ZVW grondslag** = belastbare_winst, NOT verzamelinkomen
- **PVV** = 27.65% over min(verzamelinkomen, premiegrondslag)
- **PVV premiegrondslag**: 2024=38098, 2025+ = schijf1_grens
- **Box 3 drempel schulden**: Per-persoon (2023: 3400, 2024: 3700, 2025: 3700, 2026: 3800). Doubled if partner. Schulden below drempel ignored.
- **Box 3 rendementen**: Must use DEFINITIEVE percentages (not voorlopig/preliminary)

### Boekhouder referentiecijfers (tests valideren hiertegen)
- **2023**: winst €62.522 → belastbare winst €45.801 → IB terug €415
- **2024**: winst €95.145 → belastbare winst €76.776 → IB terug €3.137

## Jaarafsluiting pagina (Pure Business Report)
5-tab layout: Balans, W&V, Toelichting, Controles, Document. Year defaults to vorig jaar.
KPI strip: Omzet, Winst, Eigen vermogen, Balanstotaal (business-only).
Balans tab: activa/passiva with edit toggle for manual inputs (bank, crediteuren, overige).
Status workflow: concept (orange) → definitief (green), with lock/reopen. DB: `jaarafsluiting_status`.
PDF export: 4-page Yuki-style (cover+grondslagen, balans, W&V+kosten, toelichting). No IB/tax content.
Controles tab: business checks only (kosten/omzet ratio, urencriterium, balans check, missing data).
Nav order: Jaarafsluiting before Aangifte (close books first, then file taxes).

## Facturen pagina
- "Importeer PDF" button: upload dialog with multi-file PDF import
- Auto-detects dagpraktijk vs ANW format, parses line items (uren/km/tarief per werkdag)
- Klant auto-resolution via `import_/klant_mapping.py`, dedup by factuurnummer
- Creates factuur record + werkdagen from parsed line items (or links existing werkdagen)
- **PDF parser** (`import_/pdf_parser.py`): `detect_invoice_type()`, `extract_dagpraktijk_line_items()`, `extract_anw_diensten()`
- Handles 7+ invoice format variations (2024 old, 2025 Klant7/Klant2-combined, 2026 standard/Klant15, ANW HAP NoordOost/Drenthe)
- **Klant2 3-amount validation**: Only treats 3-euro-amount lines as combined format when `uren*tarief + reiskosten ≈ total`
- **Import robustness**: per-item error handling, double-click protection, single DB connection per factuur werkdagen
- **Revenue queries**: Both dagpraktijk (`type='factuur'`) and ANW (`type='anw'`) included in all omzet/KPI calculations

## Kosten pagina — Expense Import
- "Importeer uitgaven" button: opens dialog scanning `02_Financieel/Boekhouding_Waarneming/{year}/Uitgaven/`
- PDFs grouped by category (expansion panels), green checkmark for already-imported
- Click unimported PDF → opens pre-filled add dialog (date from filename, category from folder, PDF auto-attached)
- `import_/expense_utils.py`: `scan_archive()`, `extract_date_from_filename()`, `FOLDER_TO_CATEGORIE` mapping
- Date extraction supports: MMYY, YYMM, MM_YY, MM-YY, YYYY-MM-DD, MMDDYY patterns
- **AOV folder excluded** — AOV is not a business expense (tracked separately in fiscale_params)
- Duplicate warning: same datum+categorie+bedrag triggers confirmation prompt

## Aangifte pagina (Invulhulp)
5-tab invulhulp mirroring Belastingdienst IB-aangifte structure. Year defaults to vorig jaar.
Each value shows BD field label + copy-to-clipboard (raw integer for portal input).
Tabs: Winst uit onderneming, Prive & aftrek (inputs save to DB), Box 3 (inputs+calc), Overzicht (final summary), Documenten (upload checklist)
- **Winst tab**: ZA/SA toggles (auto-save + recalculate), fiscal waterfall, urencriterium badge
- **Prive tab**: AOV + lijfrente inputs, eigen woning (WOZ/hypotheek/partner toggle), voorlopige aanslagen
- **Missing data warnings**: Banner at top for missing uitgaven, no AOV, jaarafsluiting not definitief
- **Auto-doc detection**: Checks `data/pdf/{year}/Jaarcijfers_*.pdf` for auto-completion
- **Known gap**: Fiscal advisory panel (ZA trajectory, SA tracking, KIA check, belastingdruk) not yet implemented

## Bekende Bugs

- ~~**Bank CSV geen dedup**~~: Opgelost — per-transactie dedup op datum+bedrag+tegenpartij+omschrijving.
- ~~**delete_klant UI**~~: Opgelost — try/except ValueError met ui.notify foutmelding.

## Recente verbeteringen (Phase 1 — 2026-03-08)
- **2026 Box 3 fix**: heffingsvrij_vermogen 57684→59357, drempel_schulden 3700→3800 (per Belastingdienst officieel)
- **SQLite performance**: synchronous=NORMAL, cache_size=10000, temp_store=MEMORY
- **Error boundary**: app.on_exception met ui.notify + traceback
- **Cleanup**: run_full_import.py verwijderd, httpx dependency verwijderd
