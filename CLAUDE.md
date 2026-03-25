# Boekhouding App

Standalone boekhoudapplicatie (NiceGUI + Python) voor een eenmanszaak huisartswaarnemer. Draait lokaal op macOS, opent in browser. Data in `data/` (niet in git).

## Tech Stack
- **UI**: NiceGUI >=3.0 (Quasar/Vue), browser mode (`ui.run(host='127.0.0.1', port=8085)`)
- **Database**: SQLite via aiosqlite, raw SQL met `?` placeholders, GEEN ORM
- **PDF**: WeasyPrint + Jinja2 (`templates/factuur.html`), **Charts**: ECharts via `ui.echart`
- **Python**: 3.12+

## Commands
```bash
# Start
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py  # → http://127.0.0.1:8085

# Tests (488 passing, 14 skipped)
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

## Database
10 tabellen: `klanten`, `klant_locaties`, `werkdagen`, `facturen`, `uitgaven`, `banktransacties`, `fiscale_params`, `bedrijfsgegevens`, `aangifte_documenten`, `afschrijving_overrides`

- Raw SQL, `?` placeholders — GEEN f-strings in SQL
- Bedragen REAL, datums TEXT (YYYY-MM-DD)
- `aiosqlite` async, WAL mode, foreign keys ON
- **Connection pattern**: `async with get_db_ctx(db_path) as conn:`
- `werkdagen.status` CHECK: `('ongefactureerd', 'gefactureerd', 'betaald')`
- `facturen.status` TEXT: `'concept'`, `'verstuurd'`, `'betaald'` (migration 14)
- `klanten.email` TEXT (migration 15)
- `banktransacties.betalingskenmerk` TEXT (migration 13)
- SQLite op lokaal filesystem, NIET via SMB (WAL faalt)

## Ontwikkelregels

### Architectuur
- Browser mode ALTIJD — NOOIT native/pywebview
- Shared layout via `components/layout.py` (includes `page_title` helper + dashboard CSS classes)
- Elke pagina is `@ui.page('/route')` in eigen bestand
- `format_euro(value, decimals=2)`/`format_datum` ALLEEN uit `components/utils.py`
- **Shared UI**: `components/shared_ui.py` (year_options, date_input, confirm_dialog)
- **Invoice builder**: `components/invoice_builder.py` (two-panel dialog with live iframe preview)
- **Invoice generator**: `components/invoice_generator.py` (WeasyPrint PDF with QR support)
- **Invoice preview**: `components/invoice_preview.py` (Jinja2 HTML for iframe preview)
- **Charts**: `components/charts.py` (revenue_bar_chart, cost_donut_chart)
- **KPI strip**: `components/kpi_card.py` (kpi_strip for jaarafsluiting only)
- **Fiscal utils**: `components/fiscal_utils.py` (fetch_fiscal_data, extrapoleer_jaaromzet)
- **Fiscal engine**: `fiscal/berekeningen.py` (bereken_volledig waterfall + bereken_box3)

### NiceGUI Patronen
- `ui.table` (NIET AG Grid), `ui.echart` voor charts
- **Tabel selectie**: ALTIJD `selection='multiple'`. Gebruik `table.selected` en `table.on('selection', handler)`.
- **Add/edit formulieren**: via `ui.dialog()` popup, NIET inline op de pagina.
- Quasar semantic kleuren (`positive`, `negative`, `warning`, `primary`, `info`) — geen hardcoded hex in pagina's
- **Persistent tables**: Create `ui.table` once with slots/events, update via `table.rows = rows; table.update()`
- **Blocking I/O**: Wrap WeasyPrint, PDF extraction, file copies in `asyncio.to_thread()`
- **Invoice preview isolation**: Use `<iframe>` with base64 data URI for CSS-isolated template preview (prevents Quasar CSS interference)

### Invoice Status Lifecycle
```
Concept (grey) → Verstuurd (blue/info) → Betaald (green/positive)
                       ↓
                  Verlopen (red/negative, computed: verstuurd + past due)
```
- New invoices start as `'concept'` — freely editable
- "Verstuur via e-mail" opens Mail.app via AppleScript with PDF attached → marks verstuurd
- Revenue queries (`get_omzet_*`, `get_kpis`) exclude concept invoices
- `update_factuur_status()` cascades to linked werkdagen

### YAGNI
Geen: user auth, BTW-administratie, loon/voorraad, real-time bank-API, auto-matching, CI/CD, multi-language

## Domeinkennis (fiscaal)

### Basisregels
- **BTW-vrijgesteld** (art. 11 Wet OB) → kosten INCL BTW, geen BTW-aangifte
- **Urencriterium**: 1.225 uur/jaar. Achterwacht (urennorm=0) telt NIET mee
- **Pensioenpremie SPH**: WEL bedrijfskosten, **AOV**: GEEN bedrijfskosten → Box 1 inkomensvoorziening
- **KIA**: 28% bij investeringen >= ondergrens, per-item drempel configureerbaar per jaar
- **Afschrijvingen**: lineair, restwaarde 10%, eerste jaar pro-rata per maand
- **Representatie**: 80%-regeling, 20% bijtelling op fiscale winst
- **Factuur vereisten**: naam+adres+KvK, factuurnummer YYYY-NNN, vervaldatum 14d, BTW-vrijstellingstekst
- **Factuur datum = last werkdag date** (work-date based, NOT invoice issue date)
- **ANW diensten**: km tracked but km_tarief=0 (travel included in ANW tarief)

### Fiscal engine regels
- **Arbeidskorting input** = fiscale_winst (vóór ZA/SA/MKB), NOT belastbare_winst
- **Tariefsaanpassing**: Since 2023, deductions at basistarief only
- **Eigen woning**: Configurable `ew_naar_partner`. Default True (Boekhouder practice)
- **ZVW grondslag** = belastbare_winst, NOT verzamelinkomen
- **PVV** = 27.65% over min(verzamelinkomen, premiegrondslag)
- **Box 3 rendementen**: Must use DEFINITIEVE percentages (not voorlopig)

### Dashboard
- Hero KPIs (omzet, winst, belasting) with sparklines + secondary strip + contextual alerts
- Real VA tracking from bank transactions via `betalingskenmerk` column
- YoY delta uses day-precise comparison (`get_kpis_tot_datum`), not full-month
- Revenue queries exclude concept invoices

### VA bank matching
- `banktransacties.betalingskenmerk` captures Rabobank CSV payment reference
- `get_va_betalingen()` splits IB/ZVW by kenmerk digit pattern (position 10-11: <50=IB, ≥50=ZVW)
- `backfill_betalingskenmerken()` runs on startup to populate existing transactions
- Belastingdienst IBAN: NL86INGB0002445588
