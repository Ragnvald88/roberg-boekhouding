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

# Tests (418 passing)
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

## Database
10 tabellen: `klanten`, `klant_locaties`, `werkdagen`, `facturen`, `uitgaven`, `banktransacties`, `fiscale_params`, `bedrijfsgegevens`, `aangifte_documenten`, `afschrijving_overrides`

- Raw SQL, `?` placeholders — GEEN f-strings in SQL
- Bedragen REAL, datums TEXT (YYYY-MM-DD)
- `aiosqlite` async, WAL mode, foreign keys ON
- **Connection pattern**: `async with get_db_ctx(db_path) as conn:` — all DB functions use this context manager (guarantees connection cleanup)
- `bedrijfsgegevens` = single-row (CHECK id=1)
- `werkdagen.status` CHECK constraint: `('ongefactureerd', 'gefactureerd', 'betaald')`
- SQLite op lokaal filesystem, NIET via SMB (WAL faalt)

## Ontwikkelregels

### Architectuur
- Browser mode ALTIJD — NOOIT native/pywebview
- Shared layout via `components/layout.py` (includes `page_title` helper)
- Elke pagina is `@ui.page('/route')` in eigen bestand
- `format_euro`/`format_datum` ALLEEN uit `components/utils.py`
- **Fiscal utils**: `components/fiscal_utils.py` (shared `fiscale_params_to_dict` + `fetch_fiscal_data` + `extrapoleer_jaaromzet` + `get_personal_data_with_fallback`)
- **Fiscal engine**: `fiscal/berekeningen.py` (bereken_volledig waterfall + bereken_box3)
- **Heffingskortingen**: `fiscal/heffingskortingen.py` (AK brackets + AHK)
- **KPI cards**: `components/kpi_card.py` (shared kpi_card + kpi_strip)

### NiceGUI Patronen
- `ui.table` (NIET AG Grid), `ui.echart` voor charts
- **Tabel selectie**: ALTIJD `selection='multiple'`. NOOIT custom checkbox slots met `$parent.$emit`. Gebruik `table.selected` en `table.on('selection', handler)`.
- Bij full `body` slot met selectie: `<q-checkbox v-model="props.selected" dense />` (Quasar-managed), NIET `v-model="props.row.selected"`.
- **Add/edit formulieren**: via `ui.dialog()` popup, NIET inline op de pagina.
- Quasar semantic kleuren (`positive`, `negative`, `warning`, `primary`) — geen hardcoded hex in pagina's
- **Persistent tables**: Create `ui.table` once with slots/events, update via `table.rows = rows; table.update()` (preserves pagination/sort state).
- **Blocking I/O**: Wrap WeasyPrint, PDF extraction, file copies in `asyncio.to_thread()` to prevent event loop stalling

### YAGNI
Geen: user auth, BTW-administratie, loon/voorraad, email, real-time bank-API, auto-matching, CI/CD, multi-language

## Domeinkennis (fiscaal)

### Basisregels
- **BTW-vrijgesteld** (art. 11 Wet OB) → kosten INCL BTW, geen BTW-aangifte
- **Urencriterium**: 1.225 uur/jaar. Achterwacht (urennorm=0) telt NIET mee
- **Pensioenpremie SPH**: WEL bedrijfskosten, **AOV**: GEEN bedrijfskosten → Box 1 inkomensvoorziening
- **KIA**: 28% bij investeringen >= ondergrens, per-item drempel configureerbaar per jaar
- **Afschrijvingen**: lineair, restwaarde 10%, eerste jaar pro-rata per maand. Per-jaar override via `afschrijving_overrides` tabel. Voorgaande jaren vergrendeld (reeds aangegeven bij BD).
- **Representatie**: 80%-regeling, 20% bijtelling op fiscale winst
- **Factuur vereisten**: naam+adres+KvK, factuurnummer YYYY-NNN, vervaldatum 14d, BTW-vrijstellingstekst
- **Factuur datum = last werkdag date** (work-date based, NOT invoice issue date)

### DB-driven parameters (alle configureerbaar in Instellingen)
Alle fiscale waarden in `fiscale_params` tabel (55 kolommen): ZA, SA, MKB%, KIA, AHK, AK, ZVW, schijven, EW forfait, villataks, Wet Hillen, arbeidskorting brackets (JSON), PVV rates, Box 3 rendementen. Input velden (AOV, WOZ, hypotheek, VA's, partner, Box 3 saldi) preserved across upserts.

### Fiscal engine regels
- **Arbeidskorting input** = fiscale_winst (vóór ZA/SA/MKB), NOT belastbare_winst
- **Tariefsaanpassing**: Since 2023, deductions at basistarief only
- **Eigen woning**: Configurable `ew_naar_partner`. Default True (Boekhouder practice)
- **ZVW grondslag** = belastbare_winst, NOT verzamelinkomen
- **PVV** = 27.65% over min(verzamelinkomen, premiegrondslag)
- **PVV premiegrondslag**: Must be set explicitly per year in DB. Falls back to `schijf1_grens` if 0 (only correct for 2025+)
- **Box 3 drempel schulden**: Per-persoon, doubled if partner. Schulden below drempel ignored
- **Box 3 rendementen**: Must use DEFINITIEVE percentages (not voorlopig)
- **Dashboard tax forecast**: Extrapolates YTD income to annual (`extrapoleer_jaaromzet`), falls back to prior-year personal data (`get_personal_data_with_fallback`), shows confidence badge + progress bars. Uses FULL annual VA for jaarprognose. Aangifte always uses full annual VA.
- **W&V jaarafsluiting**: Shows km-vergoeding as separate line + year-over-year comparison columns with Δ%.
