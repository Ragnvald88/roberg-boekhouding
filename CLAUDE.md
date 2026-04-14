# Boekhouding App

Standalone boekhoudapplicatie (NiceGUI + Python) voor een eenmanszaak huisartswaarnemer. Draait lokaal op macOS, opent in browser. Data in `~/Library/Application Support/Boekhouding/data/` (niet in git, niet op cloud-sync).

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

# Tests
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
# MANDATORY: run after every code change, confirm 0 failures before reporting done
```

## Database
11 tabellen: `klanten`, `klant_locaties`, `werkdagen`, `facturen`, `uitgaven`, `banktransacties`, `fiscale_params`, `bedrijfsgegevens`, `aangifte_documenten`, `afschrijving_overrides`, `jaarafsluiting_snapshots`

- Raw SQL, `?` placeholders — GEEN f-strings in SQL
- Bedragen REAL, datums TEXT (YYYY-MM-DD)
- `aiosqlite` async, WAL mode, foreign keys ON
- **Connection pattern**: `async with get_db_ctx(db_path) as conn:`
- `werkdagen.status`: derived at query time from `factuurnummer` + `facturen.status`
- `facturen.status` TEXT: `'concept'`, `'verstuurd'`, `'betaald'`
- `facturen.type` TEXT: `'factuur'` (werkdag-backed), `'anw'` (imported ANW), `'vergoeding'` (ad-hoc)
- SQLite op lokaal filesystem (`~/Library/Application Support/Boekhouding/data/`), NIET op cloud-sync (WAL+SynologyDrive/iCloud = silent corruption). Override via `BOEKHOUDING_DB_DIR` env var voor tests.
- **Backup**: `VACUUM INTO` (atomair), NOOIT live-file copy van `.sqlite3`
- **PDF archivering**: factuur-PDFs worden automatisch gekopieerd naar SynologyDrive financieel archief (`Inkomen en Uitgaven/{jaar}/Inkomsten/Dagpraktijk|ANW_Diensten/`). Best-effort, niet-blokkerend.

## Ontwikkelregels

### Architectuur
- Browser mode ALTIJD — NOOIT native/pywebview
- Shared layout via `components/layout.py`
- Elke pagina is `@ui.page('/route')` in eigen bestand
- `format_euro(value, decimals=2)`/`format_datum` ALLEEN uit `components/utils.py`

### NiceGUI Patronen
- `ui.table` (NIET AG Grid), `ui.echart` voor charts
- **Tabel selectie**: ALTIJD `selection='multiple'`. Gebruik `table.selected` en `table.on('selection', handler)`.
- **Add/edit formulieren**: via `ui.dialog()` popup, NIET inline op de pagina
- Quasar semantic kleuren (`positive`, `negative`, `warning`, `primary`, `info`) — geen hardcoded hex
- **Persistent tables**: Create `ui.table` once with slots/events, update via `table.rows = rows; table.update()`
- **Blocking I/O**: Wrap WeasyPrint, PDF extraction, file copies in `asyncio.to_thread()`
- **Invoice preview**: `<iframe>` met base64 data URI (voorkomt Quasar CSS interference)

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

### Kwaliteitseisen
- Bij NiceGUI upload events: ALTIJD `await e.file.read()` en `e.file.name`. NOOIT `e.content.read()` of `e.name`.
- Bij SQL queries op `facturen`: controleer altijd of `status != 'concept'` filtering nodig is
- Bij `werkdagen` data: `factuurnummer = ''` = ongefactureerd. Oude werkdagen kunnen extern gefactureerd zijn.
- **Gebruiker boven data**: als de gebruiker zegt dat data niet klopt, onderzoek root cause — vertrouw niet blindelings op DB-waarden.
- **AppleScript email**: altijd plain text (HTML content + attachments is broken in Mail.app). Betaallink als URL in tekst. `_build_mail_body` geeft één string terug, geen tuple. Helper in `components/mail_helper.py`.
- **Fiscale params**: alle jaar-afhankelijke waarden uit DB (`fiscale_params`), GEEN hardcoded fallbacks. Ontbrekende keys → loud ValueError, aangifte-pagina toont error-card met link naar Instellingen.
- **Jaarafsluiting definitief**: maakt een echte JSON snapshot (`jaarafsluiting_snapshots` tabel). Render-pad leest snapshot voor definitief-jaren, live data voor concept. Snapshot is schema-tolerant (altijd `dict.get(key, default)` in render code).
- **Bank matching**: `find_factuur_matches` retourneert `MatchProposal` met `confidence='high'|'low'`. Preview-dialoog gating: user bevestigt matches vóór toepassing. `apply_factuur_matches` gaat via `update_factuur_status`.

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
- **Belastingdienst IBAN**: NL86INGB0002445588

### Fiscal engine regels
- **Arbeidskorting input** = fiscale_winst (vóór ZA/SA/MKB), NOT belastbare_winst
- **Tariefsaanpassing**: Since 2023, deductions at basistarief only
- **Eigen woning**: Configurable `ew_naar_partner`. Default True (Boekhouder practice)
- **ZVW grondslag** = belastbare_winst, NOT verzamelinkomen
- **PVV** = 27.65% over min(verzamelinkomen, premiegrondslag)
- **Box 3 rendementen**: Must use DEFINITIEVE percentages (not voorlopig)
