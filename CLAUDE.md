# Boekhouding App

Standalone boekhoudapplicatie (NiceGUI + Python) voor een eenmanszaak huisartswaarnemer. Draait lokaal op macOS als native venster (pywebview). Data in `~/Library/Application Support/Boekhouding/data/` (niet in git, niet op cloud-sync).

## Tech Stack
- **UI**: NiceGUI >=3.0 (Quasar/Vue), **native mode** via pywebview: `ui.run(native=True, window_size=(1400, 900))`. Één proces, één venster, eigen dock-icon. `Boekhouding.app` is een thin AppleScript-launcher die enkel `main.py` spawnt of — als de app al draait — de pywebview-window naar voren brengt; zie `Boekhouding.applescript`.
- **Database**: SQLite via aiosqlite, raw SQL met `?` placeholders, GEEN ORM
- **PDF**: WeasyPrint + Jinja2 (`templates/factuur.html`), **Charts**: ECharts via `ui.echart`
- **Python**: 3.12+

## Commands
```bash
# Start (end-user): double-click Boekhouding.app, or
open -a Boekhouding
# — spawnt main.py en opent een native pywebview-venster; bij hernieuwde klik
#   focust de launcher het bestaande venster in plaats van een tweede instance.

# Start (development, direct): slaat de launcher over zodat stdout/stderr direct
# in je terminal verschijnen — handig voor debug.
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py   # opent native venster (NiceGUI `native=True`)

# Rebuild van Boekhouding.app na wijziging in Boekhouding.applescript of build-app.sh
bash build-app.sh

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
- **Native mode via pywebview** (`ui.run(native=True, ...)`). Browser-mode (`show=True`) is verlaten: de dock-icon/tab-juggling met AppleScript was broos (TCC-resets bij rebuild, Arc/Firefox geen tab-scripting, tab-accumulatie). Native geeft één proces, één venster, macOS regelt focus-op-dockklik zelf.
- **Geen top-level side-effects in `main.py`** — NiceGUI native spawnt een pywebview-child dat `main.py` opnieuw importeert. Een `sys.exit()`-guard op port-in-use doodt dan die child en de app valt om vóór het venster zichtbaar is. Als je een startup-check toevoegt: plaats 'm in een `if __name__ == '__main__':` blok of laat uvicorn de binding-error zelf opgooien.
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
- "Verstuur via e-mail" opens Mail.app via NSSharingService with HTML body + PDF attached → marks verstuurd
- Revenue queries (`get_omzet_*`, `get_kpis`) exclude concept invoices
- `update_factuur_status()` cascades to linked werkdagen

### Edit-menu visibiliteitsregels (factuur row-menu)
- **Bewerken** is zichtbaar alleen voor concept + niet-geïmporteerd (`type != 'anw'` EN `bron != 'import'`). Altijd route naar de invoice builder; er is GEEN tweede legacy-dialog.
- **Markeer als concept** is zichtbaar voor verstuurd/betaald + niet-geïmporteerd. Toont waarschuwingspopup; bij betaald: twee-staps-transitie (betaald→verstuurd→concept) omdat `update_factuur_status` een directe `betaald→concept` weigert met ValueError.
- Geïmporteerde facturen (ANW of `bron='import'`) zijn **bevroren**: nooit Bewerken, nooit Markeer-als-concept.
- Helpers in `pages/facturen.py`: `_is_editable(row)` en `_can_revert_to_concept(row)` spiegelen de Vue `v-if` regels en zijn unit-getest.

### Kwaliteitseisen
- Bij NiceGUI upload events: ALTIJD `await e.file.read()` en `e.file.name`. NOOIT `e.content.read()` of `e.name`.
- Bij SQL queries op `facturen`: controleer altijd of `status != 'concept'` filtering nodig is
- Bij `werkdagen` data: `factuurnummer = ''` = ongefactureerd. Oude werkdagen kunnen extern gefactureerd zijn.
- **Gebruiker boven data**: als de gebruiker zegt dat data niet klopt, onderzoek root cause — vertrouw niet blindelings op DB-waarden.
- **Factuur/herinnering e-mail via NSSharingService**: `_build_mail_body` en `_build_herinnering_body` geven **HTML** terug met clickable `<a href="…">deze link</a>` op de betaallink. User-controlled waarden worden via `html.escape` gefilterd. Versturen loopt via `components/mail_helper.py → open_mail_with_attachment(..., body_html=...)`; die shellt uit naar `components/mail_compose_helper.py` dat Mail.app's Cocoa Share-Sheet compose-API (`com.apple.share.Mail.compose`) aanroept via pyobjc. **Niet** via AppleScript's `html content`-property — die is door Apple gedeprecateerd met omschrijving "Does nothing at all" op macOS 14+ (zie `sdef /System/Applications/Mail.app`) en werkt niet meer samen met attachments.
- **Fiscale params**: alle jaar-afhankelijke waarden uit DB (`fiscale_params`), GEEN hardcoded fallbacks. Ontbrekende keys → loud ValueError, aangifte-pagina toont error-card met link naar Instellingen.
- **Jaarafsluiting definitief**: maakt een echte JSON snapshot (`jaarafsluiting_snapshots` tabel). Render-pad leest snapshot voor definitief-jaren, live data voor concept. Snapshot is schema-tolerant (altijd `dict.get(key, default)` in render code). `/aangifte` leest ook via `load_jaarafsluiting_data` zodat cijfers op scherm + Jaarcijfers-PDF consistent blijven, óók na engine-fixes.
- **Jaar-lock (K6)**: zodra `jaarafsluiting_status='definitief'` weigert elke mutatie op facturen, werkdagen, uitgaven, banktransacties en fiscale_params van dat jaar met `YearLockedError` (subclass van `ValueError`). Guard zit in `assert_year_writable(db_path, jaar_of_datum)` helper. Unfreeze-escape: `update_jaarafsluiting_status(jaar, 'concept')` — die functie is als enige ongeguarded zodat "Heropenen" altijd werkt. Na heropenen → correcties → opnieuw definitief maken overschrijft het snapshot. Alle guards zijn getest in `tests/test_year_locking.py`.
- **Bank matching**: `find_factuur_matches` retourneert `MatchProposal` met `confidence='high'|'low'`. Preview-dialoog gating: user bevestigt matches vóór toepassing. `apply_factuur_matches` gaat via `update_factuur_status`.
- **PDF-pad resolutie**: lees `pdf_pad` nooit direct — gebruik `_resolve_pdf_pad(row)` uit `pages/facturen.py`. Die probeert de stored path, valt terug op basename-lookup in `PDF_DIR` en `PDF_DIR/imports/`, en update de DB stilletjes bij fallback-hit (self-healing bij data-dir moves). Pure variant `_find_pdf_by_filename(stored, base)` is unit-getest met tmp_path.
- **Category suggestions op bank**: `get_categorie_suggestions(db)` bouwt een lowercase `tegenpartij → most-used categorie` map. Tie-breaker: `cnt DESC, MAX(datum) DESC`. UI toont toverstaf-knop (`auto_fix_high`) naast q-select voor one-click toepassing op ongecategoriseerde rijen.
- **Dashboard health alerts**: `get_health_alerts(db, jaar)` geeft `list[dict]` met keys `key/severity/message/count/link`. Types: `uncategorized_bank`, `overdue_invoices`, `concept_invoices`, `missing_fiscal_params`. Rendered in `pages/dashboard.py` onder de AANDACHTSPUNTEN-sectie.
- **Jaarafsluiting pre-flight**: `compute_checklist_issues(db_path, jaar)` in `pages/jaarafsluiting.py` geeft `list[tuple[severity, message, link]]`. Gebruikt door zowel de Controles-tab als de definitief-gate (soft gate, user kan doorgaan).

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
