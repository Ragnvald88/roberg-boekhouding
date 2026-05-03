# Boekhouding App

Standalone boekhoudapplicatie (NiceGUI + Python) voor een eenmanszaak huisartswaarnemer. Draait lokaal op macOS als native venster (pywebview). Data in `~/Library/Application Support/Boekhouding/data/` (niet in git, niet op cloud-sync).

## Werkwijze met de gebruiker

Gebruiker is huisartswaarnemer, geen coding-expert. Optimaliseer voor begrijpelijke, werkende code — niet voor cleverness of jargon.

- **Vóór niet-triviaal werk**: herformuleer in één zin wat je denkt dat het doel is + flag ambiguïteit vóór je code aanraakt. Triviale edits (typo, één-regel-fix) slaan dit over.
- **Multi-step werk → TodoWrite**: zo ziet de gebruiker voortgang. Markeer items af zodra écht klaar (niet batchen).
- **Proeflezen vóór "klaar"**: (1) lees je eigen diff terug, (2) draai relevante tests (zie Quality Gates), (3) controleer dat de oorspronkelijke vraag écht beantwoord is — niet alleen "code compileert / tests groen".
- **Trade-offs in gewone taal**: als je kiest tussen aanpak A en B, noem 't in één zin zonder library-jargon-dump.
- **Push back op foute aannames**: als de prompt iets aanneemt dat de codebase weerspreekt (verkeerde tabel, niet-bestaande functie, achterhaalde regel), zeg het in één zin vóór je bouwt. Beter dan netjes het verkeerde implementeren.
- **Geen ongevraagde meegeleverde refactors**: een bugfix is een bugfix. Cleanup-suggesties mogen, maar als losse vervolgstap — niet stiekem in dezelfde diff.
- **Bij niet-triviaal werk: toon de afweging kort** (2-3 aanpakken overwogen, welke gekozen, waarom). Triviaal werk hoeft dit niet — globale CLAUDE.md regelt de rest.
- **Codex auto-review (verplicht na code-changes)**: na Edit/Write op `.py`/`.html`/`.sql`-files in deze repo, vóór "klaar"-rapportage: invoke de `codex-review` skill. Die runt OpenAI Codex CLI als second opinion. Bevindingen zelf evalueren (`superpowers:receiving-code-review` principes), niet blind overnemen. Skip voor pure docs/comment changes. Kill switch: `SKIP_CODEX_REVIEW=1`.

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
14 tabellen: `klanten`, `klant_locaties`, `klant_aliases`, `werkdagen`, `facturen`, `uitgaven`, `banktransacties`, `fiscale_params`, `bedrijfsgegevens`, `aangifte_documenten`, `afschrijving_overrides`, `jaarafsluiting_snapshots`, `klant_recurring_patterns` (mig 35), `blockers` (mig 36)

- Raw SQL, `?` placeholders — GEEN f-strings in SQL
- Bedragen REAL, datums TEXT (YYYY-MM-DD)
- `aiosqlite` async, WAL mode, foreign keys ON
- **Connection pattern**: `async with get_db_ctx(db_path) as conn:` — dit is de enige standaard; raw `aiosqlite.connect` alleen in `init_db`, tests, en bestaande legacy-paden die nog migreren. `get_db_ctx` zet row_factory en `PRAGMA foreign_keys = ON` automatisch.
- `werkdagen.status`: derived at query time from `factuurnummer` + `facturen.status`
- `facturen.status` TEXT: `'concept'`, `'verstuurd'`, `'betaald'`
- `facturen.type` TEXT: `'factuur'` (werkdag-backed), `'anw'` (imported ANW), `'vergoeding'` (ad-hoc)
- `uitgaven.bank_tx_id` INTEGER nullable FK → `banktransacties(id) ON DELETE SET NULL` (migratie 26). Een uitgave kan 0-of-1-op-1 aan een bank-tx gekoppeld zijn. `NULL` = cash/contant-uitgave. Cascade-bij-delete is uitgesloten — fiscale records blijven altijd staan.
- Migratie 28: `UNIQUE INDEX idx_uitgaven_bank_tx_unique ON uitgaven(bank_tx_id) WHERE bank_tx_id IS NOT NULL` — enforces at-most-one uitgave per bank_tx at DB level (closes Importeer duplicate-link race). Partial index; NULL cash uitgaven remain unconstrained.
- `banktransacties.genegeerd` INTEGER NOT NULL DEFAULT 0 CHECK (0|1) — `1` = niet-zakelijk (privé-storting, ATM, overboeking), verborgen uit Kosten-overzicht. Alleen toggle via `mark_banktx_genegeerd()` (year-locked). Weigert óók `genegeerd=1` op factuur-gekoppelde rijen (`koppeling_type='factuur'`) — dat zou de factuur stil desync'en met een onzichtbaar geworden bank-tx. `genegeerd=0` blijft onvoorwaardelijk zodat een eerder ontstaan inconsistente staat repareerbaar is.
- `klant_aliases` (migratie 33): FK naar `klanten` met `ON DELETE CASCADE`. Schema: `(klant_id, type, pattern)` waarbij `type` IN `('suffix', 'pdf_text', 'anw_filename')`, `pattern COLLATE NOCASE` met `CHECK length(trim) >= 3` en `UNIQUE(type, pattern)`. Bevat de PDF-import naam-resolutie aliassen (gisteren `import_/klant_mapping_local.py`, nu DB-driven). Alle `resolve_klant` / `resolve_anw_klant` queries draaien hierop. Migratie 34 seedt eenmalig vanuit `klant_mapping_local.py` (als die nog bestaat) of uit `~/Library/Application Support/Boekhouding/config/klant_aliases_backup.json` als JSON-fallback. Migratie 34 blijft permanent in de list als idempotente no-op via `INSERT OR IGNORE`.
- `klant_recurring_patterns` (migratie 35, Sprint A): FK naar `klanten` met `ON DELETE CASCADE`. Schema: `(klant_id, weekdays TEXT csv "1,3,5", start_minuten INTEGER 0-1439, eind_minuten INTEGER 1-1440 met CHECK eind > start, code TEXT default 'WERKDAG', activiteit TEXT, valid_from/valid_until TEXT '' = altijd, actief INTEGER 0/1 default 1)`. Recurring werkdag-templates voor `/agenda` verwachte entries. **NIET year-locked** — projectie-data, geen fiscale feiten. Soft-delete via `actief=0` voor history-behoud. CRUD via `database.db_*_pattern` + `services.agenda.{add,list,update,delete}_pattern`. Service-laag valideert weekdays (1-7, no dups, non-empty), minuten-range, code via `domain.codes.CODES` whitelist.
- `blockers` (migratie 36, Sprint A): `(datum TEXT NOT NULL UNIQUE, kind TEXT CHECK IN ('vacation','sick','training'), label TEXT NOT NULL DEFAULT '')`. User-blockers (vakantie/ziek/nascholing) voor `/agenda`. **`UNIQUE(datum)` — één blocker per dag.** `kind='holiday'` is geweigerd: holidays zijn computed via `services.holidays.dutch_holidays(year)`, niet stored. CRUD via `database.db_*_blocker` + `services.agenda.{add,delete,list}_blockers`. `add_blocker` is **year-locked** (datum), checkt op werkdag-conflict (raise `ConflictError`). `list_blockers(vanaf, tot)` MERGES user-blockers + computed holidays in één tuple-result; holidays krijgen `id=None`.
- SQLite op lokaal filesystem (`~/Library/Application Support/Boekhouding/data/`), NIET op cloud-sync (WAL+SynologyDrive/iCloud = silent corruption). Override via `BOEKHOUDING_DB_DIR` env var voor tests.
- **Backup**: `VACUUM INTO` (atomair), NOOIT live-file copy van `.sqlite3`
- **PDF archivering**: factuur-PDFs worden automatisch gekopieerd naar SynologyDrive financieel archief (`Inkomen en Uitgaven/{jaar}/Inkomsten/{Dagpraktijk|ANW_Diensten}/` voor types `factuur`/`anw`; `Inkomsten/` flat voor type `vergoeding`). Best-effort, niet-blokkerend. **Drie trigger-paden** (alle via `archive_factuur_pdf`): (1) builder-finalize (`invoice_builder.py:genereer_factuur`), (2) PDF-regeneratie via `_ensure_factuur_pdf` self-healing, (3) factuur-upload-import in `pages/facturen.py:handle_import_loop` (round-2 fix — was hier missing). Imports gebruiken het optionele `archive_filename` arg om de oorspronkelijke upload-naam (bv `0224_HAP_Drenthe.pdf`) te bewaren ipv de lokale `{nummer}.pdf` conventie. Pad-traversal en NUL-byte injection worden via `_safe_archive_basename` afgevangen; collisions met andere content krijgen `_2.pdf`, `_3.pdf` suffix; identieke content (idempotent re-import) skipt de copy.

## Ontwikkelregels

### Architectuur
- **Native mode via pywebview** (`ui.run(native=True, ...)`). Browser-mode (`show=True`) is verlaten: de dock-icon/tab-juggling met AppleScript was broos (TCC-resets bij rebuild, Arc/Firefox geen tab-scripting, tab-accumulatie). Native geeft één proces, één venster, macOS regelt focus-op-dockklik zelf.
- **Geen top-level side-effects in `main.py`** — NiceGUI native spawnt een pywebview-child dat `main.py` opnieuw importeert. Een `sys.exit()`-guard op port-in-use doodt dan die child en de app valt om vóór het venster zichtbaar is. Als je een startup-check toevoegt: plaats 'm in een `if __name__ == '__main__':` blok of laat uvicorn de binding-error zelf opgooien.
- Shared layout via `components/layout.py`
- Elke pagina is `@ui.page('/route')` in eigen bestand
- `format_euro(value, decimals=2)`/`format_datum` ALLEEN uit `components/utils.py`
- **Layered architectuur (Sprint A en later)**: nieuwe code volgt 4-laags structuur, oude code blijft als-is.
  - `domain/` — UI-vrije + DB-vrije constants/value-objects (stdlib only). Sprint A: `domain/codes.py` met `CODES` (werkdag-types) + `ZERO_UREN_CODES`. Single source of truth voor codes — `components/werkdag_form.py` re-exporteert hieruit (was bron, nu wrapper).
  - `services/` — UI-vrije business operations. **Géén `from nicegui ...` import** (boundary-test in `tests/test_agenda_service.py:test_services_agenda_no_nicegui_import` enforced). Mag `database.py`, `domain/`, `fiscal/` importeren. Sprint A: `services/holidays.py`, `services/agenda.py`. Returns frozen dataclasses + tuples (Swift-port-vriendelijke value-types).
  - `database.py` — SQL queries + schema + raw aiosqlite. UI-vrij (al lang).
  - `pages/` + `components/` — NiceGUI-coupled UI. Importeert van services/domain/database.
- **Atomic check-and-insert pattern** voor idempotente DB-mutaties die race-protected moeten zijn (Sprint A `confirm_expected`): wrap SELECT-existing + INSERT in `BEGIN IMMEDIATE` write-lock binnen één `get_db_ctx` connectie. Voorbeeld in `services/agenda.confirm_expected`. **NIET** SELECT in één connectie + INSERT in andere — dat racet onder `asyncio.gather`. Test dit altijd met `asyncio.gather(*[fn() for _ in range(5)])` om idempotency-claim te valideren.

### NiceGUI Patronen
- `ui.table` (NIET AG Grid), `ui.echart` voor charts
- **Tabel selectie**: ALTIJD `selection='multiple'`. Gebruik `table.selected` en `table.on('selection', handler)`.
- **Add/edit formulieren**: via `ui.dialog()` popup, NIET inline op de pagina
- Quasar semantic kleuren (`positive`, `negative`, `warning`, `primary`, `info`) — geen hardcoded hex
- **Persistent tables**: Create `ui.table` once with slots/events, update via `table.rows = rows; table.update()`
- **Blocking I/O**: Wrap WeasyPrint, PDF extraction, file copies in `asyncio.to_thread()`
- **Invoice preview**: `<iframe>` met base64 data URI (voorkomt Quasar CSS interference)
- **`q-btn-dropdown` + `$parent.$emit` werkt NIET**: het `q-menu` wordt via portal naar `<body>` geteleporteerd, dus `$parent` in de menu-items verwijst naar de popup-context, niet de `q-table`. Emits bereiken de table-handler nooit (zichtbaar als "dropdown doet niks bij klikken"). Fix: gebruik een inline `q-select` met `@update:model-value` — die emit komt van het componentzelf, niet van een teleported item. Dit was de root-cause van de categorie-dropdown-bug in de eerste Kosten-rework.

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

### Invoice builder — save invariants (niet subtiel omzeilen)
- **Beide save-paths serializen `regels_json`** = `{'line_items', 'klant_fields'}`. `opslaan_als_concept` én `genereer_factuur` moeten dit doen, anders verliest een latere Bewerken de vrije regels en reconstrueert vanuit werkdagen (lossy). De `_ensure_factuur_pdf` regeneratie-fallback leest deze JSON eerst.
- **`save_factuur_atomic` stap 4 conditioneel**: unlink de oude PDF ALLEEN als `old.pdf_pad != factuur_kwargs.get('pdf_pad', '')`. Regenereren met zelfde nummer schrijft naar hetzelfde bestand — onvoorwaardelijk unlink zou de net-geschreven PDF verwijderen (F-3).
- **Close-after-refresh**: in `genereer_factuur` + `opslaan_als_concept` loopt `on_save()` (refresh_table) VÓÓR `dlg.close()`. Anders ziet de gebruiker stale `pdf_pad` in het rij-menu tijdens de refresh-window, wat leidt tot "PDF niet gevonden" clicks op bestanden die save_factuur_atomic net heeft opgeruimd.
- **`pre_datum` op concept-reopen**: `_reopen_concept_in_builder` geeft `pre_datum=row['datum']` door aan `open_invoice_builder`. De builder initialiseert `datum_input` met `pre_datum or date.today().isoformat()`. Werkdag-import flows mogen de factuurdatum NIET overschrijven (F-1/F-2 regressie-risico — er zijn geen `datum_input.value = max(dates)` assignments meer in het bestand; houd het zo).

### Kwaliteitseisen
- Bij NiceGUI upload events: ALTIJD `await e.file.read()` en `e.file.name`. NOOIT `e.content.read()` of `e.name`.
- Bij SQL queries op `facturen`: controleer altijd of `status != 'concept'` filtering nodig is
- Bij `werkdagen` data: `factuurnummer = ''` = ongefactureerd. Oude werkdagen kunnen extern gefactureerd zijn.
- **Gebruiker boven data**: als de gebruiker zegt dat data niet klopt, onderzoek root cause — vertrouw niet blindelings op DB-waarden.
- **Factuur/herinnering e-mail via NSSharingService**: `_build_mail_body` en `_build_herinnering_body` geven **HTML** terug met clickable `<a href="…">deze link</a>` op de betaallink. User-controlled waarden worden via `html.escape` gefilterd. Versturen loopt via `components/mail_helper.py → open_mail_with_attachment(..., body_html=...)`; die shellt uit naar `components/mail_compose_helper.py` dat Mail.app's Cocoa Share-Sheet compose-API (`com.apple.share.Mail.compose`) aanroept via pyobjc. **Niet** via AppleScript's `html content`-property — die is door Apple gedeprecateerd met omschrijving "Does nothing at all" op macOS 14+ (zie `sdef /System/Applications/Mail.app`) en werkt niet meer samen met attachments. **UTF-8 wrapping**: `_build_mail_body` geeft een HTML-fragment terug; `mail_compose_helper._ensure_utf8_html` wikkelt dat in een `<!DOCTYPE html>` + `<meta charset=UTF-8>` shell vóórdat de bytes naar `NSAttributedString` gaan, anders valt Cocoa terug op Windows-1252 en wordt `€` onderweg `â‚¬`. Idempotent — callers die een volledig document met charset aanleveren worden ongewijzigd doorgezet.
- **Fiscale params**: alle jaar-afhankelijke waarden uit DB (`fiscale_params`), GEEN hardcoded fallbacks. Ontbrekende keys → loud ValueError, aangifte-pagina toont error-card met link naar Instellingen. **Alle** velden zijn editable via `/instellingen` (round-2 review 2026-04-27): KIA-bracket-velden (`kia_plateau_bedrag`, `kia_plateau_eind`, `kia_afbouw_eind`, `kia_afbouw_pct`), ZA/SA toggles, PVV-percentages, Box 3, partner-toggles (`ew_naar_partner`, `box3_fiscaal_partner`), en de **Arbeidskorting brackets editor** (was read-only display tot round-2). Gebruiker kan voor elk nieuw belastingjaar via "Jaar toevoegen" een copy-from-vorig-jaar maken en relevante percentages overtypen — geen code-wijziging nodig.
- **Jaarafsluiting definitief**: maakt een echte JSON snapshot (`jaarafsluiting_snapshots` tabel). Render-pad leest snapshot voor definitief-jaren, live data voor concept. Snapshot is schema-tolerant (altijd `dict.get(key, default)` in render code). `/aangifte` leest ook via `load_jaarafsluiting_data` zodat cijfers op scherm + Jaarcijfers-PDF consistent blijven, óók na engine-fixes.
- **Jaar-lock (K6)**: zodra `jaarafsluiting_status='definitief'` weigert elke mutatie op facturen, werkdagen, uitgaven, banktransacties en fiscale_params van dat jaar met `YearLockedError` (subclass van `ValueError`). Guard zit in `assert_year_writable(db_path, jaar_of_datum)` helper. Voor functies die een lijst werkdag-IDs muteren (`link_werkdagen_to_factuur`, `save_factuur_atomic`'s inline werkdag-UPDATE, `delete_factuur` OLD-link unlink, `save_factuur_atomic` step 1 OLD-link unlink) bestaat `_assert_werkdagen_writable(db_path, werkdag_ids)` — fetcht DISTINCT jaren van de gegeven IDs en weigert de hele batch als één daarvan in een definitief jaar valt. Round-2 review (2026-04-27) sloot de overige mutation-paths: `set/delete_afschrijving_override`, `add/delete_aangifte_document`, `delete_klant_locatie` (via gekoppelde werkdagen-jaren), en `update_factuur_herinnering_datum` (nieuwe helper — vervangt raw UPDATE in `pages/facturen.py`). `mark_banktx_genegeerd` checkt nu óók de datum van een gekoppelde uitgave (cross-year stealth-hide gedicht). Unfreeze-escape: `update_jaarafsluiting_status(jaar, 'concept')` — die functie is als enige ongeguarded zodat "Heropenen" altijd werkt. Na heropenen → correcties → opnieuw definitief maken overschrijft het snapshot. `delete_banktransacties` controleert óók de datums van gekoppelde facturen **én** gekoppelde uitgaven (via `bank_tx_id` FK). Alle guards zijn getest in `tests/test_year_locking.py`.
- **Year-lock UX**: save-handlers in `/aangifte`, `/instellingen`, en `/kosten_investeringen` vangen `YearLockedError` af → `ui.notify(type='warning')` met de Dutch error-message uit de exception. Bij definitief jaar renderen inputs als `disabled` + banner bovenaan ("Jaar X is definitief afgesloten — heropen via Jaarafsluiting voor correcties"). Geen achtergrond-tracebacks meer.
- **Privé/genegeerd filter — gecentraliseerde predicate** (round-2 + round-3 review 2026-05-01): `database.ZICHTBARE_ZAKELIJKE_UITGAVE_FILTER` is de single source of truth voor "uitgave die zichtbaar telt als kosten": `(u.bank_tx_id IS NULL OR (COALESCE(b.genegeerd, 0) = 0 AND b.bedrag < 0))`. Caller MOET `u`-alias voor uitgaven en `b`-alias voor banktransacties gebruiken (`LEFT JOIN banktransacties b ON b.id = u.bank_tx_id`). Toegepast in: `get_uitgaven_per_categorie`, `get_representatie_totaal`, `get_investeringen`, `get_investeringen_voor_afschrijving`, **`get_kpis`, `get_kpis_tot_datum`, `get_data_counts.n_uitgaven`** (round-3 dashboard fix B1), `get_kosten_breakdown`, `get_kosten_per_maand`. Effect: dashboard winst/kosten matchen met /kosten en /aangifte. `get_data_counts.n_uitgaven` excludeert óók `is_investering=1` (consistent met `get_kpis` kosten). Cash uitgaven (`bank_tx_id IS NULL`) blijven meetellen. COALESCE-NULL-safe is defensief — schema enforced NOT NULL sinds migratie 24.
- **KIA bracket-functie** (round-2 review): boven `kia_bovengrens` rekent de engine een vast plateau-bedrag (`kia_plateau_bedrag` tot `kia_plateau_eind`), daarna een lineaire afbouw (`kia_afbouw_pct` per euro tot `kia_afbouw_eind`), boven `kia_afbouw_eind` is KIA = 0. Backward-compat: jaren waar de bracket-velden 0 zijn (legacy seeds) vallen terug op het oude cliff-gedrag (KIA = 0 boven bovengrens) zodat Boekhouder-pinned tests groen blijven.
- **Werkdag tarief** (round-2): in edit-mode herstelt `werkdag_form` zowel `km` als `tarief` naar de gestockte werkdag-waarde NA `_load_klant_data` (die zet de klant-default). Voorkomt dat een tarief-wijziging bij de klant een oudere werkdag stilletjes hertarifeert.
- **Bank matching**: `find_factuur_matches` retourneert `MatchProposal` met `confidence='high'|'low'`. Preview-dialoog gating: user bevestigt matches vóór toepassing. `apply_factuur_matches` gaat via `update_factuur_status`.
- **PDF-pad resolutie**: row-menu actions (Preview/Download/OpenFinder/SendMail/SendHerinnering) gebruiken ALLEMAAL `_ensure_factuur_pdf(row)` uit `pages/facturen.py`. Die: (1) probeert `_resolve_pdf_pad` (stored path → basename-lookup in `PDF_DIR`/imports/, self-healing DB-update op fallback-hit), (2) valt bij missend bestand terug op `_regenerate_factuur_pdf`, die de PDF opnieuw rendert vanuit `regels_json` → linked werkdagen, `pdf_pad` bijwerkt (YearLockedError wordt geslikt — fiscale data blijft ongewijzigd, alleen metadata pdf_pad), en archiveert naar SynologyDrive. ANW-imports en `bron='import'` worden geweigerd. Pure bron-kiezer `_compute_regen_sources(row)` is apart unit-getest.
- **Category suggestions**: `get_categorie_suggestions(db)` bouwt een lowercase `tegenpartij → most-used categorie` map via UNION ALL van twee bronnen: debit-uitgaven (`uitgaven.categorie JOIN banktransacties` — source of truth post-migratie 27) en positieve banktransacties (`banktransacties.categorie` — Omzet/Prive/Belasting/AOV). Tie-breaker: `cnt DESC, MAX(datum) DESC`. UI toont toverstaf-knop (`auto_fix_high`) naast q-select op **alle** ongecategoriseerde rijen (debit, positief én manueel) in `/transacties`.
- **Bank-matching dialoog**: `find_factuur_matches` + `apply_factuur_matches` blijven ongewijzigd; preview-dialoog leeft nu op `/transacties` (triggert na CSV-import én via "Matches controleren (N)" header-knop zolang er proposals liggen).
- **Dashboard health alerts**: `get_health_alerts(db, jaar)` geeft `list[dict]` met keys `key/severity/message/count/link`. Types: `uncategorized_bank`, `overdue_invoices`, `concept_invoices`, `missing_fiscal_params`. Rendered in `pages/dashboard.py` onder de AANDACHTSPUNTEN-sectie. **Sign-aware uncategorized check** (B2 round-3 fix): voor debits is `uitgaven.categorie` source-of-truth (lazy-create flow), voor credits `banktransacties.categorie`. Stale `banktx.categorie` op een debit zonder linked uitgave verbergt GEEN echte uncategorized state. SQL gebruikt `CASE WHEN bedrag<0 THEN TRIM(COALESCE(u.categorie, '')) = '' ELSE TRIM(COALESCE(bt.categorie, '')) = '' END` — TRIM matcht `derive_status` `.strip()` semantiek. Alert-link forceert `&type=bank` zodat `/transacties` exact dezelfde set toont (cash-uitgaven niet vermengd). **Geen import-exclusion op concept-alert** (B17 NIET gefixt — bewust): `pages/facturen.py:793` toont "Markeer als verstuurd" voor élke concept zonder import-guard, dus imports zijn actionable en de alert is legitiem.
- **Jaarafsluiting pre-flight**: `compute_checklist_issues(db_path, jaar)` in `pages/jaarafsluiting.py` geeft `list[tuple[severity, message, link]]`. Gebruikt door zowel de Controles-tab als de definitief-gate (soft gate, user kan doorgaan).
- **Klant-aliases (PDF-import resolutie)**: `resolve_klant(db_path, pdf_name, filename_suffix)` en `resolve_anw_klant(db_path, filename)` in `import_/klant_mapping.py` zijn async DB-queries op `klant_aliases` (geen module-level state meer). 4 strategies voor `resolve_klant`: (1) exact suffix, (2) exact pdf_text, (3) directe `klanten.naam = ? COLLATE NOCASE`, (4) fuzzy bidirectional substring met `length(pattern) >= 3` en `ORDER BY length(pattern) DESC, klant_id ASC`. ANW-resolutie alleen fuzzy met `instr(LOWER(?), LOWER(pattern))`. CRUD-helpers in `database.py`: `get/add/delete_klant_alias`, `update_klant_alias_target` (optimistic-lock), `remember_alias` (race-vrij INSERT-first met `IntegrityError`-catch + conflict-detectie), `process_remember_alias` (orchestrator met `on_conflict` callback voor UI-resolutie).
- **PDF-parser skip-words**: `derive_skip_words(bg)` in `import_/skip_words.py` produceert tuple van GENERIC tokens + tokens uit `bedrijfsgegevens` row (eigen naam, bedrijfsnaam, adres, email + local-part, postcode + plaats split, telefoon-fragmenten via `_normalize_phone_digits` met +31/0031 strip). `_extract_klant_name(text, skip_words=None)` accepteert optionele override; case-insensitive substring matching. `pages/facturen.py` import-flow injecteert `derive_skip_words(bg)` per dialog.
- **Auto-learn alias UI** (`pages/facturen.py`): per parsed_items rij een `_remember_alias` checkbox (default UNCHECKED). Bij confirm: `process_remember_alias` met `_show_alias_conflict_dialog` als callback. Conflict-modal heeft expliciete Behoud/Verplaats knoppen; sluiten = behoud (safe default). Reassign gebruikt optimistic lock — als rowcount=0 → user-warning ("ondertussen elders aangepast"). Failures wrapped in try/except zodat ze nooit factuur-import blokkeren.
- **Alias-CRUD UI** (`components/shared_ui.py:open_klant_dialog` — sectie "Aliassen voor PDF-import" alleen in edit-mode): toont aliases per type (suffix/pdf_text/anw_filename), delete-knoppen, en add-form met type-dropdown + pattern-input (min 3 chars enforced via DB CHECK + UI guard).
- **Public-safety**: alle echte klant- en persoonsgegevens leven in de SQLite-DB onder `~/Library/Application Support/Boekhouding/data/` (gitignored sinds dag 1). Geen `_local.py`-files meer in de repo. JSON-snapshot van `klant_aliases` ligt op `~/Library/Application Support/Boekhouding/config/klant_aliases_backup.json` als migratie-fallback bij DB-restore. Repo is publiek; pre-commit kan via `verify_public_safe.py` als spot-check (één-shot script in commit-history).

#### Round-3 review-fixes (2026-05-01)

- **Factureerbare werkdag — gecentraliseerde predicate**: `database.FACTUREERBARE_WERKDAG_FILTER` (en `_W_PREFIX` variant voor JOIN-queries met `w.`-alias) levert het standaard "open + tarief>0 + datum<=vandaag"-fragment. Toegepast in: `get_werkdagen_ongefactureerd`, `get_werkdagen_ongefactureerd_summary` (B7+B18 — return-key blijft `aantal`), `get_nog_te_factureren` (Q7 — kreeg óók future-werkdag filter). Caller passeert `_today_iso()` als laatste param. Dashboard-banner en /werkdagen-summary tonen daarmee dezelfde set. Werkdagen-tabel heeft GEEN `jaar` kolom — gebruik altijd datum-range, niet `WHERE jaar = ?`.
- **`_today_iso()` wrapper** in `database.py`: thin wrapper rond `_date.today().isoformat()` zodat tests via `monkeypatch.setattr(database, '_today_iso', lambda: '2026-06-15')` reproduceerbare datums kunnen forceren — `datetime.date.today()` is een immutable builtin en niet direct patchbaar. Gebruikt in 3 callers (de werkdag-helpers).
- **`get_omzet_per_maand_tot_datum(db, jaar, max_datum)`** (B13): echte date-range query voor day-precise YoY cumulatieve grafiek. Eerder werd voor vorig jaar de volledige 12 maanden getoond — visueel inconsistent met de YoY badge die YTD-vs-YTD rekent. Helper clamps `max_datum` naar `{jaar}-12-31` als caller een te hoge waarde meegeeft (anders zouden volgende-jaar facturen in dezelfde maand-slots vallen door substr-based GROUP BY). Concept-facturen blijven uitgesloten. Dashboard gebruikt deze conditioneel wanneer `jaar == huidig_jaar`, anders volle vorig-jaar via `get_omzet_per_maand`.
- **`set_banktx_categorie` sign-aware blank handling** (B6 root-fix): bij `bedrag>=0` writes naar `banktransacties.categorie` direct; bij `bedrag<0` met bestaande linked uitgave update die uitgave-categorie (incl. clear via `''`); bij `bedrag<0` zonder linked uitgave + `categorie=''` → **NO-OP** (voorheen creëerde dit phantom lege uitgaven via lazy-create — silent data-pollution bij bulk-blanking met mixed-sign selectie); bij `bedrag<0` zonder linked uitgave + niet-leeg cat → single call naar `ensure_uitgave_for_banktx(categorie=...)` (geen dubbele update_uitgave nodig — overrides zetten categorie op create-pad).
- **Cross-year guards op `bank_tx_id`** (B19): `add_uitgave(bank_tx_id=X)` en `update_uitgave(bank_tx_id=Y)` checken nu óók de bank-tx datum naast de uitgave-datum. `update_uitgave` checkt bij `bank_tx_id`-WIJZIGING (`new != old`) zowel oude als nieuwe banktx-jaar. Idempotente updates (zelfde `bank_tx_id`) skippen de check zodat re-saves niet falen op een al-bestaande locked-link. Missing-row blijft silent no-op (return DIRECT vóór alle year-lock checks). Voorkomt cross-year stealth (un)link naar definitief jaar.
- **VA betalingskenmerk normalisatie** (B5): `database._normalize_va_kenmerk(k)` strips alle non-digits voor de `[10:12]` IB/ZVW-split. Belastingdienst kenmerken zijn 16-digit per spec maar copy-paste uit BD-portaal of bepaalde CSV's voegt punten/spaties toe. Eerder werkte het toevallig soms — afhankelijk van waar de separators stonden — en faalde anders.
- **on_send_mail year-lock pre-flight** (B11): conditioneel op `row.get('status') == 'concept'`. Alleen concept→verstuurd is een DB-mutatie (regel ~1349 in pages/facturen.py); voor verstuurd/verlopen is mailen puur communicatie zonder mutatie en mag dus ook in een definitief jaar. Pattern is identiek aan `on_send_herinnering`.
- **Atomic PDF write** (K2): `components/utils.write_pdf_atomic(html, output_path, base_url=None)` rendert via WeasyPrint naar een unieke `tempfile.mkstemp`-tmpfile in dezelfde directory en doet `os.replace`. Bij crash wordt de tmp opgeruimd via `contextlib.suppress(OSError)` (zodat de original render-error niet door een unlink-fail wordt gemaskeerd) en blijft de bestaande PDF intact. Toegepast in `pages/jaarafsluiting.py:export_pdf` voor jaarcijfers; `components/invoice_generator.py:generate_invoice` heeft hetzelfde patroon inline (heeft een `doc` object i.p.v. html string — helper niet 1-op-1 toepasbaar).
- **Documenten upload safety** (K1): `pages/documenten.py` heeft 2 helpers — `_safe_documenten_basename` loud-fails (ValueError) op path components, NUL bytes, leading dots, of niet-toegestane extensies (.pdf/.jpg/.jpeg/.png); `_safe_atomic_write(dest_dir, name, content)` is idempotent (returns `(path, is_new=False)` bij identieke content), kiest `_2.pdf`/`_3.pdf` collision-suffix, schrijft via `tempfile.mkstemp` + `os.replace`, en cleanup in `contextlib.suppress(OSError)`. Alle 3 upload-handlers in `/documenten` plus `pages/aangifte.py:handle_upload` (subdir-conventie `AANGIFTE_DIR/jaar/categorie/` behouden) volgen de 4-staps-volgorde: year-lock preflight → sanitize → atomic write → DB-row → cleanup-on-fail (alleen als `is_new=True`). Delete-handler wrapt `delete_aangifte_document` met try/except YearLockedError.
- **`villataks_pct` als named constant** (B3): `fiscal/constants.VILLATAKS_PCT_DEFAULT = 2.35` met expliciete bron-comment (Belastingdienst Wet IB 2001 art. 3.112 lid 2). `bereken_eigenwoningforfait` parameter default + `bereken_volledig` fallback gebruiken de constante. Eerder leefde dit als magic-fallback `params.get('villataks_pct', 2.35)`. Triggert alleen voor WOZ > €1.35M; als de BD het percentage ooit jaar-afhankelijk maakt → migreer naar fiscale_params.

### Agenda-pagina (`/agenda`) — Sprint A

Calendar-driven planning + factuur-status visualisatie naast bestaande tabel-driven `/werkdagen`. Spec: `docs/superpowers/specs/2026-05-02-agenda-sprint-a-design.md`. Plan: `docs/superpowers/plans/2026-05-02-agenda-sprint-a.md`.

**Service-layer**: `services.agenda` (UI-vrij, ~926 LoC). Read-API: `get_maand(jaar, maand) → MaandView`, `get_dag(datum) → DagView`, `get_zes_weken_prognose(vanaf) → tuple[WeekTotaal, ...]`, `get_urencriterium_projectie(jaar) → UrencriteriumState`, `list_blockers(vanaf, tot) → tuple[Blocker, ...]` (merged user-blockers + computed holidays), `list_patterns_for_klant(klant_id) → tuple[Pattern, ...]`. Mutate-API: `confirm_expected(pattern_id, datum, ...) → werkdag.id` (atomic via BEGIN IMMEDIATE), `add_blocker/delete_blocker`, `add_pattern/update_pattern/delete_pattern` (NIET year-locked — patterns zijn projectie-data).

**Pure helpers**: `categorize_werkdag(code) → 'dagpraktijk'|'anw'|'overig'` (type-based coloring), `derive_werkdag_status_label(werkdag, today) → 'ongefactureerd'|'concept'|'verstuurd'|'verlopen'|'betaald'` (verlopen = pure function op `factuur_vervaldatum < today`, geen DB-update nodig), `compute_overdue_days(werkdag, today)` (alleen voor `verstuurd`-status), `parse_weekdays(csv) → list[int]` (1-7, no dups, whitespace-tolerant).

**`get_werkdagen_met_factuur_status(jaar, maand)`** (in `database.py`): LEFT JOIN `werkdagen` × `facturen` via `factuurnummer`. Returns `WerkdagMetStatus` frozen dataclass met velden: `id, datum, klant_id, klant_naam, code, activiteit, uren, km, tarief, km_tarief, factuurnummer, factuur_id, factuur_datum, factuur_status, factuur_betaald_datum, factuur_vervaldatum (computed +14d in __post_init__)`. Orphan factuurnummer (factuur_status='' maar factuurnummer != '') wordt door `derive_werkdag_status_label` als `ongefactureerd` behandeld — UI mag apart `factuurnummer != '' AND factuur_status == ''` checken voor warning-indicator.

**Bron-van-waarheid**: bevestigde werkdagen = DB-rij in `werkdagen`, verwachte entries = computed at-query-time uit patterns minus werkdagen minus blockers minus holidays, **alleen voor `datum > today`**. Holiday-blocker (`kind='holiday'`) wint over user-blocker bij display-conflict. Holiday-blocker onderdrukt verwachte entries (user kan handmatig werkdag toevoegen via "Werkdag plannen" override).

**confirm_expected invariants**:
- **Atomic**: `BEGIN IMMEDIATE` write-lock wrap rond SELECT-existing + INSERT (race-protectie tegen `asyncio.gather(5×)`). Test `tests/test_agenda_service.py:test_confirm_expected_atomic_under_parallel_calls` bewijst single werkdag.
- **Idempotent**: bestaande werkdag op `(klant_id, datum)` — ongeacht of door dit pattern gemaakt — return existing.id. Documented contract.
- **Race-protected**: pattern_id moet bestaan + `actief=1`, anders `ConflictError("Patroon X is verwijderd of inactief — refresh agenda")`.
- **Blocker-check**: weigert als blocker op datum bestaat (defense-in-depth, asymmetrie met `add_blocker` opgelost).
- **Klant-data uit klant** op moment van bevestigen (tarief, retour_km, adres) — NIET uit pattern. Pattern is rooster-template, geen tarief-snapshot.
- **km_tarief**: uit `fiscale_params.km_tarief` per jaar via `_get_km_tarief_for_year` helper. Fallback `0.23` **alleen** als geen fiscale_params row bestaat voor het jaar — bewuste planning-context-uitzondering op de "geen hardcoded fallbacks" regel (CLAUDE.md Kwaliteitseisen): /agenda is een planning-tool, niet de aangifte-engine, en moet bruikbaar zijn vóór de gebruiker een nieuw jaar in /instellingen heeft gevuld. Voor aangifte-pagina's blijft de loud-fail-regel onverkort. Toegepast in `confirm_expected` én `_expected_for_datum` (consistente bedragen voor verwacht en bevestigd).
- **urennorm**: 0 voor `ACHTERWACHT` of `ZERO_UREN_CODES (CONGRES/OPLEIDING/OVERIG_ZAK)`, anders 1.

**Type-based coloring (Sprint A keuze, geen klant-kleuren)**: dagpraktijk = teal (#0F766E), anw = paars (#7E22CE), overig = grijs. CSS classes `.wd-dagpraktijk/.wd-anw/.wd-overig` in `components/layout.py`. Verwachte entries (recurring) krijgen `.wd-pill.expected` (dashed border + soft fill). Klant-specifieke kleuren als optionele toekomstige feature (toggle in Instellingen + `klanten.color` kolom).

**Factuur-status-bars per cel**: `.wd-status-bar` met `.status-{label}` per werkdag onderaan de cel. Kleur-mapping: ongefactureerd grijs (#94A3B8), concept grijs-dimmed, verstuurd blauw (#2563EB), verlopen rood (#DC2626), betaald groen (#16A34A). UI auto-update bij elke /agenda-render via verse DB-query — geen pubsub.

**Year-lock policy**:
- Werkdag-mutaties via `confirm_expected` → year-locked (delegate naar `add_werkdag` invariant).
- Blocker-mutaties (`add/delete_blocker`) → year-locked op blocker.datum.
- Pattern-mutaties (`add/update/delete_pattern`) → **NIET** year-locked. Patterns zijn projectie-data, geen fiscale feiten. Wijziging beïnvloedt alleen verwachte entries (virtueel). Werkelijke werkdagen in dat jaar blijven onaangeraakt.

### Transacties-pagina (`/transacties`)

Single inbox for all money-movement work — bank debits + bank positives +
manual cash uitgaven. Source: `get_transacties_view(db, jaar, maand,
status, categorie, type, search, include_genegeerd)` in `database.py`.

- **Row status** (`derive_status` in `components/transacties_helpers.py`):
  `prive_verborgen` (genegeerd=1) → `gekoppeld_factuur` (positive matched
  to factuur) → `ongecategoriseerd` → `ontbreekt_bon` (debit cat'd w/o PDF)
  → `compleet` (debit: cat+bon) → `gecategoriseerd` (positive: cat).
- **Categorie write**: UI handler branches on `id_bank` — bank rows go
  through `set_banktx_categorie` (sign-aware: debit → lazy-create uitgave
  + update; positive → update banktransacties.categorie). Manual rows go
  straight to `update_uitgave`.
- **Per-row category options**: debits+cash get `KOSTEN_CATEGORIEEN`;
  positives get `['Omzet', 'Prive', 'Belasting', 'AOV']`. Injected
  server-side as `props.row.cat_options`.
- **Detail dialog** lives in `components/transacties_dialog.py`. Bootstrap
  uses `get_uitgave_by_id` (M5 fix — no list-and-filter silent-None race).
  **Debit-only** — the dialog refuses to open on credit rows (bedrag ≥ 0);
  lazy-create would otherwise write an ABS-bedrag uitgave linked to a
  positive bank-tx and silently inflate /kosten breakdown totals. The
  template also hides the `…` and `Bon toevoegen` buttons for credits.
- **Factuur-match preview**: after CSV import + header button
  "Matches controleren (N)" for manual review.
- **Cash entries** (`+ Contante uitgave`): `add_uitgave(bank_tx_id=None)`.
- **Archief-PDFs importeren**: `scan_archive()` + `open_add_uitgave_dialog`
  with prefill. Auto-link routes through `ensure_uitgave_for_banktx` (M1).
- **Bulk**: Categorie wijzigen · Markeer als privé (bank-only) · Verwijderen.
  *Bulk-Categorie* respecteert sign van de selectie: all-debit → kosten-cats, all-credit → `['', 'Omzet', 'Prive', 'Belasting', 'AOV']`, mixed → alleen blanken (met waarschuwing). *Bulk-Verwijderen* pre-scant de selectie en vraagt expliciet bevestiging bij factuur-revert cascades en uitgave-orphans; de captured `selected` snapshot wordt doorgegeven aan de inner delete-loop om scope-widening te voorkomen als de user de selectie na dialoog-open wijzigt. **Hetzelfde snapshot-patroon** (`selected = list(table.selected or [])` aan het begin van de handler) geldt voor *Markeer als privé* (`bulk_negeren`) hier én voor `on_bulk_delete`/`on_bulk_betaald` in `pages/facturen.py`. *Markeer als privé* slaat factuur-gekoppelde rijen UI-zijdig over (snel pad) en vangt daarnaast `ValueError` van de DB-guard af.
- **Query-params**: `?jaar/maand/status/categorie/type/search` pre-populate
  filters. Used for click-through from `/kosten`.
- **Sign convention in `TransactieRow.bedrag`**: signed. Bank debits keep
  their stored negative; bank credits keep their stored positive; manual
  cash uitgaven are normalised to negative via `-ABS(u.bedrag)` in the SQL.
  UI colours by sign (teal ≥ 0, red < 0). KPI callers that need
  positive-totals (`get_kpi_kosten`) use `abs(r.bedrag)` + filter
  `r.bedrag < 0`.
- **Dynamic `ARCHIVE_BASE` reference** (monkeypatch-friendly): consumer
  modules (`import_/expense_utils.py` etc.) use `from components import
  archive_paths` + `archive_paths.ARCHIVE_BASE` (attribute lookup at call
  time), NOT `from components.archive_paths import ARCHIVE_BASE`. Tests
  monkeypatch the module attribute; the attribute form propagates, the
  direct-import form does not.
- **Archive helper `archive_paths.jaar_dir(jaar)`**: returns
  `ARCHIVE_BASE/'Inkomen en Uitgaven'/{jaar}/`. Single source of truth —
  invoice-archivering (`invoice_generator.archive_factuur_pdf`) en
  uitgaven-scan (`expense_utils.scan_archive`) gaan beide hier
  doorheen. `expense_utils` had vóór round-2 het `'Inkomen en Uitgaven'`
  segment overgeslagen waardoor "Archief-PDFs importeren" niets vond;
  fix is via deze helper en getest in `tests/test_archive_factuur.py`.

### Kosten-pagina (`/kosten`) — overzicht

Read-only. Jaar-selector + 2 tabs (Overzicht / Investeringen). No form
controls that mutate data.

- **KPI strip**: `get_kpi_kosten`. "Te verwerken" card navigates to
  `/transacties?status=ongecategoriseerd&jaar=X`. `totaal` and
  `monthly_totals` exclude `is_investering=1` rows: investeringen are
  depreciated via `afschrijvingen_jaar`, not booked as kosten in the
  purchase month/year.
- **Per-maand bar chart**: `get_kosten_per_maand` (12 slots). Excludes
  investeringen and uitgaven linked to positive bank-tx (defensive
  against the P0-1 phantom-lazy-create path).
- **Categorie breakdown**: `get_kosten_breakdown` — each bar is clickable →
  `/transacties?jaar=X&categorie=Y` (categorie is `urllib.parse.quote_plus`-ed
  so `Telefoon/KPN` and tegenpartij names with `&` survive). The
  `(nog te categoriseren)` bucket renders as a separate muted card above
  (M7 polish); clicking it now routes to `?status=ongecategoriseerd`.
  Same investering + bank-sign filters as the per-maand query.
- **Terugkerende kosten card**: `get_terugkerende_kosten` — vendors with
  ≥3 hits in 365d, sorted by jaar-totaal DESC. Click → `/transacties?
  search=tegenpartij`.
- **Investeringen tab**: unchanged, `pages/kosten_investeringen.py:
  laad_activastaat`.

### Visuele tokens (Sprint B, 2026-05-03)

`components/layout.py` definieert 9 CSS custom properties als single
source of truth voor visual styling: `--bg`, `--surface`, `--border`,
`--text`, `--muted`, `--accent`, `--accent-soft`, `--shadow`,
`--radius`. Nieuw werk gebruikt deze — geen hardcoded hex meer in
`pages/`.

**Cascade-regel**: Quasar `.q-*` overrides ALTIJD buiten
`@layer components` plaatsen — layered styles verliezen van Quasar's
unlayered defaults, ongeacht specificity. App-only classes
(`.app-card`, `.nav-item`, `.wd-pill`, etc.) horen wél binnen
`@layer components`. Voor bewuste suppressie van `.q-card` defaults:
chained selector `.q-card.your-class` buiten layer.

**`.q-btn` overrides** moeten `:not()`-modifier-respect afdwingen:
`.q-btn:not(.q-btn--round):not(.q-btn--rounded) { ... }` — anders
breken `props('round')` icon-buttons (cirkel → afgerond vierkant).

**Font-stack**: body+headings = `-apple-system` system stack (laat
macOS SF Pro Text/Display zelf kiezen, geen Rounded — financial app
moet rustig voelen, niet speels). Numbers = SF Mono via `.num` class.
Geen webfont-CDN meer.

**View-switcher pattern**: tussen `/werkdagen` en `/agenda` cross-link
buttons in beide page-toolbars (`Kalenderweergave` ↔ `Lijstweergave`).
Geen tab-merge — `/agenda` heeft eigen concepten (recurring patterns,
blockers, holidays, urencriterium-projectie) die niet "lijst-filters
op werkdagen" zijn.

`/bank` route bestaat NIET MEER (Sprint B T9 schrap — `ui.navigate.to`
client-side redirect was ineffectief, server-side middleware overkill
voor 1-user app).

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
- **Factuur datum = issue date** (defaults to today; werkdag dates stay on the line items). The builder seeds `datum_input` from `pre_datum` (on concept-reopen) or today; werkdag-import flows never overwrite this field.
- **ANW diensten**: km tracked but km_tarief=0 (travel included in ANW tarief)
- **Belastingdienst IBAN**: NL86INGB0002445588

### Fiscal engine regels
- **Arbeidskorting input** = fiscale_winst (vóór ZA/SA/MKB), NOT belastbare_winst
- **Tariefsaanpassing**: Since 2023, deductions at basistarief only
- **Eigen woning**: Configurable `ew_naar_partner`. Default True (Boekhouder practice)
- **ZVW grondslag** = belastbare_winst, NOT verzamelinkomen
- **PVV** = 27.65% over min(verzamelinkomen, premiegrondslag)
- **Box 3 rendementen**: Must use DEFINITIEVE percentages (not voorlopig)
