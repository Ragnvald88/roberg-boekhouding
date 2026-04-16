# FIX_PATTERNS — Defect taxonomie

Gedestilleerd uit de `fix*` / `revert*` / `perf*` commits van deze repo. Elke klasse lijst het onderliggende patroon, de CLAUDE.md-regel (indien aanwezig), 3–5 historische commits, en hoe je het in HEAD detecteert.

Gebruik: `/audit-scan` leest dit bestand als checklist tegen de huidige code.

---

## silent-fallback-fiscal — Hardcoded default in plaats van required param

**Samenvatting**: `kwargs.get('xxx', 2024_default)` of `params.get('xxx', default)` voor fiscale percentages/bedragen re-introduceert stille hardcoded waarden die zijn opgeschoond uit de engine. Resultaat: verkeerde belasting-cijfers voor jaren waarin de DB-waarde ontbreekt, zonder dat iemand het ziet.

**CLAUDE.md regel**: *"Fiscale params: alle jaar-afhankelijke waarden uit DB, GEEN hardcoded fallbacks. Ontbrekende keys → loud ValueError."*

**Voorbeelden**:
- `235b76c fix(fiscal): close silent-fallback loophole in upsert + validator`
- `4482b40 fix(fiscal): fail loud on missing fiscale_params keys + graceful error UI`
- `2c270d8 fix(instellingen): remove silent 2024 bootstrap fallback`

**Hoe in HEAD te detecteren**:
- Grep: `\.get\(['"](pvv_|repr_aftrek|ew_forfait|schijf|ahk_|ak_|zvw_|kia_|mkb_|arbeidskorting_brackets|zelfstandigenaftrek|startersaftrek)` in `fiscal/`, `database.py`, `pages/aangifte.py`, `pages/instellingen.py`
- Glob scope: `fiscal/**/*.py`, `database.py`, `pages/aangifte.py`, `pages/instellingen.py`
- Handmatige check: bij elke hit, is de default een hardcode van een fiscale waarde? (0 voor "optional nul" is OK.)

---

## year-lock-guard-gap — Mutatie-entrypoint zonder `assert_year_writable`

**Samenvatting**: elke nieuwe DB-mutatie (raw UPDATE/INSERT/DELETE of helper daaromheen) op `facturen|werkdagen|uitgaven|banktransacties|fiscale_params` moet vóór de schrijving `assert_year_writable(db_path, jaar_of_datum)` aanroepen. Vergeten = stille mutatie op een definitief-afgesloten jaar.

**CLAUDE.md regel**: *"Jaar-lock (K6): zodra jaarafsluiting_status='definitief' weigert elke mutatie op facturen, werkdagen, uitgaven, banktransacties en fiscale_params van dat jaar met YearLockedError."*

**Voorbeelden**:
- `96fee33 fix(year-lock): guard apply_factuur_matches (final-review gap)`
- `8cf6b4f feat(year-lock): guard werkdag mutations`
- `24c8f09 feat(year-lock): guard factuur mutations`
- `b415e5d feat(year-lock): guard remaining fiscale_params update helpers`
- `f2ee28a feat(year-lock): add YearLockedError + assert_year_writable helper`

**Hoe in HEAD te detecteren**:
- Grep: `UPDATE\s+(facturen|werkdagen|uitgaven|banktransacties|fiscale_params)` én `INSERT INTO (facturen|werkdagen|uitgaven|banktransacties|fiscale_params)` én `DELETE FROM (facturen|werkdagen|uitgaven|banktransacties|fiscale_params)` in `database.py`
- Voor elke hit: scroll omhoog in de enclosing async function. Is er een `assert_year_writable(...)` vóór de schrijving? Zo niet → gap.
- Uitzondering (expliciet ongeguardeerd): `update_jaarafsluiting_status` — dat is de unfreeze-escape.
- Glob scope: `database.py`

---

## state-machine-bypass — Raw UPDATE buiten centrale helper

**Samenvatting**: `UPDATE facturen SET status = ?` direct uitvoeren omzeilt `update_factuur_status`, dat transitievalidatie (bv. weigert directe `betaald → concept`) én werkdagen-cascade regelt. Zelfde patroon geldt voor `banktransacties.koppeling_*` buiten `apply_factuur_matches`.

**CLAUDE.md regel**: *"update_factuur_status() cascades to linked werkdagen. Revenue queries exclude concept invoices."* (impliceert centrale router).

**Voorbeelden**:
- `444b586 fix(bank): prevent silent wrong-invoice-paid via best-match scoring + preview` (routeert via `update_factuur_status`, geen raw UPDATE meer)
- `96fee33 fix(year-lock): guard apply_factuur_matches` (final-review gap toonde raw UPDATE die statussen wijzigde)

**Hoe in HEAD te detecteren**:
- Grep: `UPDATE\s+facturen\s+SET\s+status` — **elke hit** die niet binnen `update_factuur_status` zelf staat is verdacht.
- Grep: `UPDATE\s+banktransacties\s+SET\s+koppeling` — zelfde regel voor `apply_factuur_matches`.
- Glob scope: `database.py`, `pages/**/*.py`

---

## pdf-path-not-self-healing — Directe `Path.exists()` i.p.v. `_resolve_pdf_pad`

**Samenvatting**: code die `row.get('pdf_pad')` leest en direct `Path(...).exists()` doet, faalt na een data-dir-move. De juiste weg is `_resolve_pdf_pad(row)` — dat valt terug op basename-lookup in `PDF_DIR` + `PDF_DIR/imports/` en update de DB silently bij een fallback-hit.

**CLAUDE.md regel**: *"PDF-pad resolutie: lees pdf_pad nooit direct — gebruik _resolve_pdf_pad(row) uit pages/facturen.py."*

**Voorbeelden**:
- `8eba858 fix(facturen): self-healing PDF path resolution` (update aan 5 callers tegelijk)

**Hoe in HEAD te detecteren**:
- Grep: `row\.get\(['"]pdf_pad['"]` **of** `\[['"]pdf_pad['"]\]` — voor elke hit: is de volgende `Path(...).exists()`-check gevolgd door directe consumption, of gaat het via `_resolve_pdf_pad`?
- Glob scope: `pages/**/*.py`, `components/**/*.py`
- Handmatige check: nieuwe callers (e.g. een nieuwe button in facturen.py) kunnen per ongeluk het oude patroon overnemen.

---

## sql-quote-escape-interpolation — f-string SQL zonder quote-escape

**Samenvatting**: waar bind-parameters (`?`) niet werken (VACUUM INTO, PRAGMA met padnaam, schema-DDL), moet je toch single quotes in de ingevoegde waarde escapen (`str.replace("'", "''")`). Zonder dat: path met een apostrof breekt VACUUM en riskeert injectie.

**CLAUDE.md regel**: *"Raw SQL, ? placeholders — GEEN f-strings in SQL"* + uitzondering voor VACUUM/PRAGMA.

**Voorbeelden**:
- `e0f2548 fix(safety): escape SQL quotes in VACUUM INTO`

**Hoe in HEAD te detecteren**:
- Grep: `VACUUM INTO` — voor elke hit: wordt de path via `replace("'", "''")` geëscaped?
- Grep: `PRAGMA\s+\w+\s*=\s*['"][^?]` — PRAGMA's met ingevoegde waarden (bv. database paths).
- Grep: f-string met SQL keywords: `f".*\b(SELECT|INSERT|UPDATE|DELETE|ATTACH)` — elke match is een violation van "geen f-strings in SQL", tenzij het een tabel/kolom-naam is waar bind-params niet kunnen.
- Glob scope: `database.py`, `migrate_db_location.py`, `pages/**/*.py`

---

## async-blocking-io — Sync I/O binnen `async def` zonder `asyncio.to_thread`

**Samenvatting**: `Path.unlink()`, `shutil.copy*`, `subprocess.run`, `weasyprint.write_pdf`, `pdftotext` calls binnen een async functie blokkeren de event loop. Moet via `await asyncio.to_thread(...)`.

**CLAUDE.md regel**: *"Blocking I/O: wrap WeasyPrint, PDF extraction, file copies in asyncio.to_thread()"*.

**Voorbeelden**:
- `59178be refactor(db): wrap pdf unlink in asyncio.to_thread`
- `7f8c945 fix: harden pages — status error handling, async file I/O, KPI concept exclusion`

**Hoe in HEAD te detecteren**:
- Per-bestand: grep `^async def` om async functies te identificeren, zoek daarbinnen naar `\.unlink\(|shutil\.(copy|move|rmtree)|subprocess\.(run|Popen|call)|weasyprint|pdftotext`.
- Accepteer alleen wanneer voorafgegaan door `await asyncio.to_thread(`.
- Glob scope: `database.py`, `pages/**/*.py`, `components/**/*.py`, `import_/**/*.py`

---

## ui-guard-mirrors-backend — Quasar `v-if` uit sync met Python helper

**Samenvatting**: een menu-item toont "Bewerken" of "Markeer als concept" alleen wanneer de backend het toestaat. Python-helpers (`_is_editable`, `_can_revert_to_concept`) en de template `v-if` moeten exact dezelfde predikaat uitdrukken. Divergentie = UI biedt een actie aan die backend weigert (of omgekeerd).

**CLAUDE.md regel**: *"Edit-menu visibiliteitsregels (factuur row-menu)"* expliciet gedocumenteerd met helpers.

**Voorbeelden**:
- `0886ea0 fix(facturen): restrict edit to concept-only, add Markeer als concept`
- `b846445 fix(facturen): show Bewerken for all statuses, route by status+type+bron` (voorloper — later strenger gemaakt)

**Hoe in HEAD te detecteren**:
- Grep in `pages/facturen.py`: alle `v-if="props.row` predikaten extraheren.
- Cross-check met Python-helpers: voor elke menu-item die een mutatie triggert, moet er een matchende `_is_*` / `_can_*` helper zijn én de tekst moet semantisch matchen.
- Nieuwe menu-items zonder helper → rode vlag.
- Glob scope: `pages/facturen.py` (en elke andere pagina met row-menus op mutaties).

---

## async-input-hardening — Parsing zonder guard/timeout/try-except

**Samenvatting**: `float(x)`, `int(x)`, `json.loads(x)` op user-input, CSV-cellen, of externe tool-output zonder empty-guard, try/except, of timeout. Faalt op edge cases (lege string, malformed, hangt).

**CLAUDE.md regel**: impliciet — bewezen door meerdere fixes.

**Voorbeelden**:
- `a60a097 fix: harden input parsing — amount edge cases, pdftotext timeout, kenmerk safety`
- `da87b0f fix: add empty-input guard and try/except to _decode_qr_url`
- `697dc5b fix: add TimeoutExpired handler for pdftotext + fix test docstring`
- `2901660 fix: skip zero-euro reiskosten line for ANW + null guard in ongefactureerd bedrag`

**Hoe in HEAD te detecteren**:
- Grep: `subprocess\.run\(.*pdftotext` — heeft de call een `timeout=` kwarg en `TimeoutExpired`-handler?
- Grep: `float\(` / `int\(` / `json\.loads\(` in import/parse-modules — followed by try/except?
- Glob scope: `import_/**/*.py`, `components/pdf_*.py`, `pages/**/*.py`

---

## anw-edge-case — ANW-specifiek pad mist 0-tarief / null-guard

**Samenvatting**: ANW-diensten hebben `km_tarief=0` (reistijd zit in uurtarief). Elke code die factuurregels genereert, km-vergoeding berekent, of ANW-werkdagen importeert moet dit expliciet respecteren.

**CLAUDE.md regel**: *"ANW diensten: km tracked but km_tarief=0 (travel included in ANW tarief)"* + *"nog_te_factureren excludeert tarief=0"*.

**Voorbeelden**:
- `80bc29a fix(facturen): ANW werkdagen get km_tarief=0 on import`
- `2901660 fix: skip zero-euro reiskosten line for ANW + null guard in ongefactureerd bedrag`

**Hoe in HEAD te detecteren**:
- Grep: `km_tarief` — elke berekening/branch die ANW-vs-regulier onderscheidt, moet het 0-geval niet stilzwijgend overslaan of negatief uitdraaien.
- Grep: branches op `type == 'anw'` / `type != 'anw'` — controleer consistentie.
- Glob scope: `components/invoice_*.py`, `pages/facturen.py`, `pages/werkdagen.py`, `import_/**/*.py`, `database.py` (factuur/werkdag helpers).

---

## html-injection-mail-template — User-values zonder `html.escape`

**Samenvatting**: HTML e-mail bodies (factuur + herinnering) bevatten user-controlled waarden (naam, bedrijfsnaam, betaallink). Niet escapen = injectie risico in Mail.app.

**CLAUDE.md regel**: *"User-controlled waarden worden via html.escape gefilterd"* voor `_build_mail_body` / `_build_herinnering_body`.

**Voorbeelden**:
- `b90afed fix: html.escape user values in HTML email template`
- `d6eb3a5 fix: AppleScript quote escaping for HTML emails + error detection` (gerelateerd, andere laag)

**Hoe in HEAD te detecteren**:
- Grep: `_build_mail_body|_build_herinnering_body` — in de body, elk user-var moet door `html.escape(...)` vóór `<a>` / `<span>` insertie.
- Grep: `<a\s+href=` binnen Python f-strings — is de href-value escaped?
- Glob scope: `pages/facturen.py`, `components/mail_*.py`

---

## startup-port-process-handling — Port-in-use / stale venster / lock-probes

**Samenvatting**: launcher, main.py, migrate_db_location.py moeten elegant omgaan met de app-is-al-open-situatie. Geen port-conflict crashes, geen SQLite-lock-corruptie tijdens migration. Probe met `BEGIN IMMEDIATE` i.p.v. blind overschrijven.

**CLAUDE.md regel**: *"Geen top-level side-effects in main.py — NiceGUI native spawnt een pywebview-child dat main.py opnieuw importeert. Een sys.exit()-guard op port-in-use doodt dan die child"*.

**Voorbeelden**:
- `858d551 fix: handle port conflicts and stale processes on startup`
- `4db5509 fix(launcher): focus existing browser tab instead of opening new one`
- `e0f2548 fix(safety): escape SQL quotes in VACUUM INTO + detect running app` (probe-pattern)
- `a71de17 Revert "perf(startup): skip matplotlib + port-check..."` (top-level guard brak pywebview child)

**Hoe in HEAD te detecteren**:
- `main.py` scannen op top-level side effects (port-check, sys.exit) buiten `if __name__ == '__main__':`.
- `migrate_db_location.py` / backup-code: gebruikt een schrijflock-probe vóór de data-kopieer?
- `Boekhouding.applescript` + launcher-code: focuses bestaand venster i.p.v. tweede instance spawnen?
- Glob scope: `main.py`, `migrate_db_location.py`, `Boekhouding.applescript`, `components/archive_paths.py`.

---

## Feature-trends (uit `feat:` commits)

Drie zichtbare thema's in nieuwe features van de afgelopen maanden:

1. **Proactieve surfacing van data-problemen**: `get_health_alerts` op dashboard, pre-flight checklist op jaarafsluiting-definitief-gate, category-suggestions op bank. Patroon: data-issues worden niet stil afgehandeld; ze komen naar voren in een dedicated UI-component (alert card / checklist / toverstaf-knop).
2. **Immutability met escape hatch**: year-lock (K6) + snapshot-read voor definitief-jaren (K5). Patroon: onherstelbaar-lijkende operaties krijgen één duidelijke unfreeze-route (`update_jaarafsluiting_status → 'concept'`).
3. **Self-healing & atomicity**: self-healing PDF-pad, atomic logo replacement (write-then-rename), VACUUM INTO i.p.v. live-file copy, orphan-PDF cleanup bij save-conflict. Patroon: als iets fout gaat, moet de volgende klik gewoon werken — geen dode UI.

**Waar zou meer van hetzelfde helpen** (voor `/audit-scan` cluster D):
- Welke pagina's missen een health-alerts-equivalent? (bv. werkdagen, uitgaven, klanten)
- Welke destructieve acties missen een pre-flight checklist of confirmation dialog?
- Welke file-writes zijn nog niet atomic (write-then-rename)?

---

## Meta

- HEAD bij generatie: `08faace` (2026-04-15)
- Gesampled: 9 commits (full diff) + ~25 commits (subject-signaal) uit de laatste 150 commits
- Datum-range: 2026-03-27 → 2026-04-15 (recente fix-concentratie)
- Gebruik: `/audit-scan [domein?]`
- Ververs: `/audit-mine-commits --refresh`
