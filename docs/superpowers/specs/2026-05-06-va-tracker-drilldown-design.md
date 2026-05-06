# Sprint J — VA-tracker drill-down + PDF-parse design

**Status**: LOCKED 2026-05-06 — post-Codex-round-2 amendments applied, awaiting user approval to invoke writing-plans
**Builds on**: Sprint I VA-tracker (master `fc18da3`, pytest 1386)
**Replaces tile click-target**: was `/aangifte?jaar=X`, wordt `/va-tracker/{jaar}` page

## Probleem

Sprint I VA-tracker hero-tile toont nu Voorlopige Aanslag-status (verplicht / betaald / resterend) op /dashboard. User-feedback 2026-05-06: tile geeft geen drill-down naar **bron** (welke BD-beschikking?) of **detail** (welke bank-transacties horen erbij?).

Bovendien: jaarbedrag + termijnen worden nu **handmatig** in /aangifte ingevuld. Belastingdienst stuurt elk jaar een PDF-beschikking met exact die info. Auto-extractie zou handmatige fouten elimineren en audit-traceerbaarheid toevoegen.

## Doel

1. **Click op VA-tile** → nieuwe `/va-tracker/{jaar}` page met:
   - PDF-link per IB en ZVW (bron-document)
   - Verplicht-bedrag uit PDF (geparseerd, traceerbaar)
   - Per-termijn-overzicht (feb-dec)
   - Bank-transacties gematched op kenmerk
2. **PDF-upload met auto-parse** in `/documenten`:
   - User uploadt VA-IB en VA-ZVW beschikking
   - App parset bedrag, kenmerk, dagtekening, termijnen
   - Sync naar `fiscale_params` (backward-compat met fiscale-engine)
3. **Audit-trail bij beschikking-revisie**: BD verstuurt soms nieuwe brief met nieuw aanslagnummer mid-year — table behoudt history, toont actieve beschikking als waarheid.

## Scope

**In v1** (Sprint J):
- Migratie 41 — nieuwe `voorlopige_aanslagen` tabel
- `services/va_parser.py` — pdftotext + regex parser
- `/documenten` upload-flow extended: parse + DB-insert + fiscale_params-sync
- Nieuwe `/va-tracker/{jaar}` page met IB/ZVW collapsible sections
- Dashboard tile click-target wijzigt: `/va-tracker/{jaar}`
- Caller-migratie: `compute_va_tracker` leest van actieve beschikking met fallback naar fiscale_params (backward-compat)

**Uitgesteld** (Sprint K of later):
- `parser_version` veld voor parser-upgrade-tracking — pas relevant bij eerste echte parser-iteratie
- `raw_text_sha256` voor PDF-deduplication — UNIQUE(aanslagnummer) dekt 90%
- Definitieve aanslag PDF-parse (ander format)
- Backfill-script voor pre-2025 jaren (geen PDFs aanwezig)
- Per-termijn payment scheduling visualisatie (cumulatieve grafiek)
- Mobile-responsive drill-down layout (single-user macOS native, niet relevant)

**Niet doen**:
- `bedrag_cents INTEGER` ipv REAL — CLAUDE.md "Bedragen REAL" conventie. BD-PDFs hebben max 2-decimal precision, geen rounding-risico binnen één boekjaar.
- Upload-flow ook in /aangifte — alleen /documenten + link "Beschikking uploaden" op /va-tracker page (consistent met andere doctypes).
- Multi-source beschikking (handmatig + PDF mengen) — bij upload wint PDF, handmatige edit in /aangifte krijgt waarschuwing op /va-tracker.

## Definition of Done (acceptatiecriteria)

- Pytest 1386 → ~1410+ groen
- Geen f-string SQL in nieuwe queries; `?`-placeholders
- Year-lock: alle muteer-paden (insert beschikking, active-switch, fiscale_params-sync) `assert_year_writable`-protected
- pdftotext-fail handled gracefully (PDF blijft opgeslagen, geen DB-record, notify naar handmatig)
- Cascade-discipline: nieuwe `.va-tracker-*` CSS buiten `@layer components` als hij `.q-card` raakt
- `services/va_parser.py` is pure (geen NiceGUI, geen DB), getest in isolatie
- Echte 2026 IB+ZVW PDFs als test-fixtures (`tests/fixtures/va_beschikking_2026_*.txt` met geparseerde pdftotext-output, om binary PDFs niet in git te hoeven committen — of we committen de PDFs zelf in `tests/fixtures/`)

## 1. Schema diff (migratie 41)

```sql
CREATE TABLE voorlopige_aanslagen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jaar INTEGER NOT NULL,
    soort TEXT NOT NULL CHECK (soort IN ('ib', 'zvw')),
    document_id INTEGER NOT NULL REFERENCES aangifte_documenten(id) ON DELETE CASCADE,
    aanslagnummer TEXT NOT NULL,
    dagtekening TEXT NOT NULL,                       -- ISO date
    bedrag REAL NOT NULL CHECK (bedrag >= 0),
    betalingskenmerk TEXT NOT NULL,                  -- 16-digit genormaliseerd
    termijnen INTEGER NOT NULL DEFAULT 11
        CHECK (termijnen BETWEEN 1 AND 12),
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE(aanslagnummer),
    UNIQUE(document_id)  -- 1-1 doc↔VA-row invariant; deterministische delete-cleanup
);

-- Partial unique index — exact één actieve per (jaar, soort)
CREATE UNIQUE INDEX idx_va_active
    ON voorlopige_aanslagen(jaar, soort)
    WHERE is_active = 1;
```

> **Amendment Codex round-2**: `eerste_vervaldatum` + `laatste_vervaldatum` velden geschrapt — derivable uit `termijnen + jaar` via `services.dashboard.compute_va_termijnen_schedule`. YAGNI voor v1; Sprint K kan toevoegen indien BD-revisie afwijkende schema's ondersteunt.

**Beslissingen**:
- **REAL bedrag**, niet `bedrag_cents INTEGER`. Codebase-consistency (CLAUDE.md). 2-decimal precision is voldoende.
- **FK naar aangifte_documenten** met CASCADE — verwijderen van het document via /documenten verwijdert ook de parse-record.
- **Partial unique index op `(jaar, soort) WHERE is_active=1`** — DB-niveau garantie van max 1 actieve beschikking per type per jaar. Bij revisie: oude rij krijgt `is_active=0`, nieuwe rij krijgt `is_active=1`.
- **UNIQUE(aanslagnummer)** — voorkomt duplicate-insert bij her-upload van zelfde PDF.
- **UNIQUE(document_id)** (Plan-amendment T1.1 Codex round-3) — garandeert 1-1 koppeling tussen aangifte_documenten en voorlopige_aanslagen. Voorkomt scenario waarin één doc → meerdere VA-rows zou kunnen genereren, met als gevolg dat delete-cleanup maar één fp-veld zou wissen. Re-runners: NIET weghalen.
- **GEEN parser_version of raw_text_sha256** v1 (YAGNI). Sprint K kan toevoegen indien nodig.

## 2. PDF-parse strategie

**Library**: `pdftotext -layout` via subprocess. Hergebruik `import_/pdf_parser.py:extract_pdf_text` (al bestaand pattern + 30s-timeout + error-handling). Nieuwe wrapper niet nodig.

**Locatie**: `services/va_parser.py` — pure helper, UI-vrij + DB-vrij. Imports `_extract_text_from_pdf` uit `import_/pdf_parser.py`.

**API**:

```python
@dataclass(frozen=True)
class ParsedBeschikking:
    jaar: int
    soort: Literal['ib', 'zvw']
    aanslagnummer: str          # '1244.12.646.H.60.01'
    dagtekening: date           # uit "31 januari 2026"
    bedrag: float               # 30670.00
    betalingskenmerk: str       # '0124412647060001' (16 digits, no spaces)
    termijnen: int              # 11
    # eerste/laatste_vervaldatum geschrapt — derive uit jaar+termijnen in render-laag (Codex amendment round-2)


def parse_va_beschikking(pdf_path: Path) -> ParsedBeschikking:
    """Parse BD voorlopige aanslag PDF.

    Raises:
        VAParseError: missing critical field (aanslagnummer, bedrag, kenmerk).
                      Caller (UI) vangt af → notify "PDF opgeslagen, lezen mislukt"
                      → fallback naar handmatige invoer.
    """
```

**Pre-process**: normaliseer alle whitespace (incl newlines) naar enkele spaties via `re.sub(r'\s+', ' ', text)` BEFORE matching. PDF-layout breekt sommige fields over regels (bijv. `Het laatste bedrag moet\nuiterlijk op 31 december 2026`); whitespace-normalize maakt patterns eenvoudig.

**Regex-patterns** (op whitespace-genormaliseerde tekst, originele tekst behouden voor debug):

```python
AANSLAG_RE = r'\b(\d{4}\.\d{2}\.\d{3}\.[HW]\.\d{2}\.\d{2}(?:\.\d+)?)\b'
JAAR_RE = r'Voorlopige aanslag (\d{4})\b'
DAGTEKENING_RE = r'Dagtekening (\d{1,2}) ([a-zA-Z]+) (\d{4})'
# Bedrag: gebruik specifiek de "Te betalen : €" pattern uit het betaalblok
# (uniek met `:` separator). De PDF heeft 4 "Te betalen" varianten;
# dit is de enige met komma-precisie en `:` punct.
BEDRAG_RE = r'Te betalen\s*:\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?)'
KENMERK_RE = r'Betalingskenmerk\s*:?\s*([0-9 ]{16,24})'
TERMIJNEN_RE = r'(\d+) (?:gelijke )?maandelijkse? termijnen'
```

**Type-detectie**: primair via aanslagnummer-suffix `.H.` → `'ib'`, `.W.` → `'zvw'`. Fallback header-match op `'Inkomstenbelasting'` resp. `'Zorgverzekeringswet'`. Beide niet-vindbaar → raise `VAParseError`.


**Bedrag-parsing**: punt-thousands + optionele komma-decimaal. `'30.670'` → `30670.0`. `'30.670,50'` → `30670.50`. Replace `.` (thousands) eerst, dan `,` → `.` voor float-cast.

**Datum-parsing**: Nederlandse maanden expliciet mappen via `_DUTCH_MAANDEN_REVERSE = {'januari': 1, 'februari': 2, 'maart': 3, ...}`. Hergebruik niet bestaande `format_datum_*_nl`-helpers (die zijn output-only); maak nieuwe constant.

**Critical fields** (raise als missing): aanslagnummer, bedrag, betalingskenmerk, dagtekening.
**Optional fields** (default als missing): termijnen (default 11), eerste/laatste vervaldatum (None).

**Edge cases**:
- Beschikking-revisie krijgt nieuw aanslagnummer (60.01 → 60.02) → nieuwe row, `is_active=1`, oude wordt `is_active=0`.
- pdftotext-fout: existing `RuntimeError` propageert naar UI als VAParseError.
- Onverwacht format: `VAParseError` met diagnostiek (welk veld miste).

## 3. DB CRUD helpers

`database.py` extensies:

```python
async def get_active_voorlopige_aanslag(
    db_path: Path = DB_PATH, jaar: int = 0, soort: str = '',
) -> dict | None:
    """Latest actieve beschikking voor (jaar, soort). None als niet aanwezig.
    Returns dict met alle table-kolommen + parsed dagtekening als date.
    """


async def process_voorlopige_aanslag_upload(
    db_path: Path = DB_PATH, *,
    document_id: int,
    parsed: ParsedBeschikking,
) -> dict:
    """Atomic upload-pipeline (Codex round-2 critical fix).

    In één BEGIN IMMEDIATE transaction:
    1. assert_year_writable(parsed.jaar) — anders YearLockedError + abort
    2. Check UNIQUE(aanslagnummer) — als bestaand: idempotent skip,
       return {'action': 'skip', 'reason': 'duplicate'}
    3. SET is_active=0 op bestaande actieve rij voor (jaar, soort)
    4. INSERT nieuwe row met is_active=1
    5. UPDATE fiscale_params SET voorlopige_aanslag_{betaald|zvw} = ?,
       voorlopige_aanslag_{ib|zvw}_termijnen = ? WHERE jaar = ?
    6. COMMIT

    Bij ANY foutroute: ROLLBACK. document_id blijft staan in
    aangifte_documenten (caller verantwoordelijk voor cleanup als gewenst).

    Returns: {'action': 'inserted'|'replaced'|'skip', 'beschikking_id': int}
    """


async def clear_fiscale_params_va_for_jaar(
    db_path: Path = DB_PATH, jaar: int = 0, soort: str = '',
) -> None:
    """Zet voorlopige_aanslag_{betaald|zvw} + termijnen op default.
    Aangeroepen door delete-hook (zie hieronder). Year-locked."""


async def delete_aangifte_document_with_va_cleanup(
    db_path: Path = DB_PATH, document_id: int = 0,
) -> None:
    """Wrapper rond bestaande delete_aangifte_document.
    Voor categorie='voorlopige_aanslag' documenten: na delete (CASCADE
    verwijdert VA-row vanzelf), check of er nog ANDERE actieve beschikking
    voor (jaar, soort) is. Zo nee → clear_fiscale_params_va_for_jaar
    om stale data in fp.voorlopige_aanslag_betaald te voorkomen.
    Year-locked. (Codex round-2 critical fix: cascade-stale-fp gat.)
    """
```

**Atomic upload pipeline (Codex round-2 critical fix)**:

`process_voorlopige_aanslag_upload` doet alle DB-mutaties in één `BEGIN IMMEDIATE`-transaction:

```sql
BEGIN IMMEDIATE;
  -- guards
  -- year-lock check (Python-side raise)
  -- duplicate-aanslagnummer check
  -- existing active deactivate
  UPDATE voorlopige_aanslagen SET is_active=0
    WHERE jaar=? AND soort=? AND is_active=1;
  -- new active
  INSERT INTO voorlopige_aanslagen (...) VALUES (...);
  -- sync fiscale_params
  UPDATE fiscale_params SET ... WHERE jaar=?;
COMMIT;
```

Bij YearLockedError of ANY exception: ROLLBACK. Voorkomt partial state (oude inactive + new failed insert + stale fp).

`clear_fiscale_params_va_for_jaar` zet `voorlopige_aanslag_{betaald|zvw}` op 0 én termijnen op DEFAULT 11. Aangeroepen vanuit delete-hook **alleen als geen andere actieve beschikking** voor `(jaar, soort)` overblijft (er kan nog een handmatige situatie zijn met meerdere docs).

## 4. Auto-fill flow in /documenten

`/documenten` heeft al upload-handlers per `(categorie, slot)`. VA-IB beschikking en VA-ZVW beschikking zijn al slots in `AANGIFTE_DOCS`. Sprint J extension:

```python
async def handle_upload(e):
    # Bestaand: sla upload op naar AANGIFTE_DIR/{jaar}/{categorie}/{filename}
    document_id = await save_aangifte_document(...)

    # NIEUW Sprint J: parse-on-upload voor VA beschikkingen
    if categorie == 'voorlopige_aanslag':
        try:
            parsed = await asyncio.to_thread(parse_va_beschikking, pdf_path)
        except VAParseError as err:
            ui.notify(
                f'PDF opgeslagen, automatisch lezen mislukt: {err}. '
                f'Vul handmatig in via /aangifte.',
                type='warning', timeout=8000,
            )
            return  # document blijft staan, geen DB-mutatie

        # Mismatch-check VOOR de transactie (UI-niveau, los van atomic insert)
        existing_fp = await get_fiscale_params(jaar=parsed.jaar)
        existing_bedrag = (existing_fp.voorlopige_aanslag_betaald
                          if parsed.soort == 'ib'
                          else existing_fp.voorlopige_aanslag_zvw) if existing_fp else 0
        if existing_bedrag and abs(existing_bedrag - parsed.bedrag) > 1:
            ok = await _confirm_dialog(
                f'PDF zegt €{parsed.bedrag:.0f}, '
                f'je had handmatig €{existing_bedrag:.0f}. '
                f'PDF-waarde gebruiken?'
            )
            if not ok:
                return  # behoud handmatige waarde, document blijft

        # Atomic DB-mutatie via process_voorlopige_aanslag_upload
        try:
            result = await process_voorlopige_aanslag_upload(
                document_id=document_id, parsed=parsed,
            )
            if result['action'] == 'skip':
                ui.notify('Beschikking al verwerkt (zelfde aanslagnummer)',
                          type='info')
            else:
                ui.notify(
                    f"VA {parsed.soort.upper()} bijgewerkt naar "
                    f"€{parsed.bedrag:.0f}, {parsed.termijnen} termijnen",
                    type='positive')
        except YearLockedError as e:
            ui.notify(str(e), type='warning')
            return
```

**Single source of truth voor flow**: `process_voorlopige_aanslag_upload` (zie § 3) doet duplicate-check + deactivate + insert + sync in één transactie. Mismatch-confirm zit in UI-laag omdat het user-decision is, niet pure data-mutatie.

**Revisie-pad**: nieuwe upload met ander aanslagnummer maar zelfde (jaar, soort) → atomic transaction deactiveert oude, inserts nieuwe. **Geen UI-confirm nodig**: aanslagnummer is pas-bekend na parse, en het feit dat BD een nieuwe brief stuurde is impliciete intent. Notify post-fact: "VA IB vervangen door revisie X (was Y)".

**Idempotent re-upload** (Codex round-2 critical fix): zelfde aanslagnummer → `process_voorlopige_aanslag_upload` returnt `{'action': 'skip'}` zonder VA-row mutatie. **Maar**: er is dan WEL een tweede `aangifte_documenten` row gemaakt (upload-handler runs vóór parse). Mitigation: bij `'skip'` action → delete het zojuist gemaakte aangifte_documenten row (cleanup duplicate file). UI-flow becomes:

```python
result = await process_voorlopige_aanslag_upload(...)
if result['action'] == 'skip':
    await delete_aangifte_document_with_va_cleanup(document_id)
    ui.notify('Beschikking al verwerkt — duplicate upload opgeruimd', type='info')
```

## 5. Drill-down `/va-tracker/{jaar}` page

Nieuwe page in `pages/va_tracker.py`. Layout:

```
┌──────────────────────────────────────────────────────────┐
│ Voorlopige aanslag {jaar}              [⤴ /aangifte]    │
│                                                          │
│ ┌─ Inkomstenbelasting ─────────────────── [▼ collapse] ┐ │
│ │ Aanslagnummer 1244.12.646.H.60.01                    │ │
│ │ Dagtekening 31 januari 2026                          │ │
│ │ Verplicht €30.670 / Betaald €5.580 / Rest €25.090    │ │
│ │ 11 termijnen × €2.788/mnd                            │ │
│ │ [📄 Open PDF]  [🔄 Vervangen]                         │ │
│ │                                                      │ │
│ │ Termijnen-overzicht                                  │ │
│ │ feb 2026  €2.788  ✓ betaald 28-2-2026               │ │
│ │ mrt 2026  €2.788  ✓ betaald 31-3-2026               │ │
│ │ apr 2026  €2.788  ⚠ verwacht — niet gevonden        │ │
│ │ ...                                                  │ │
│ │                                                      │ │
│ │ Bank-transacties (kenmerk 0124412647060001)          │ │
│ │ datum       bedrag    omschrijving                   │ │
│ │ 28-2-2026   €2.788    VA-IB 2026 termijn 1          │ │
│ │ 31-3-2026   €2.788    VA-IB 2026 termijn 2          │ │
│ │                                                      │ │
│ │ ▸ Eerdere revisies (1)                               │ │
│ └──────────────────────────────────────────────────────┘ │
│                                                          │
│ ┌─ Zorgverzekeringswet ──────────────────── [▼ collapse]┐│
│ │ ... idem ...                                         │ │
│ └──────────────────────────────────────────────────────┘ │
│                                                          │
│ Geen beschikking? [Upload via /documenten]               │
└──────────────────────────────────────────────────────────┘
```

**Helper voor termijnen-overzicht**: `services/dashboard.compute_va_termijnen_schedule(beschikking, va_betalingen, today) → list[TermijnRow]`. Returns voor elke maand feb-dec (of jan-dec bij 12 termijnen) een `TermijnRow(maand: int, vervaldatum: date, bedrag: float, status: Literal['betaald', 'verwacht', 'toekomst'], betaald_op: date | None, betaald_bedrag: float | None)`. Vervaldatum derived: `eerste_maand = 13 - termijnen` + offset, datum = laatste-dag-van-maand.

**Helper voor bank-tx detail**: nieuwe `database.get_va_betalingen_detail(jaar) → list[dict]`. Returns ALLE BD-tx voor jaar (kenmerk + bedrag + datum + omschrijving + classification ('ib_matched' / 'zvw_matched' / 'unmatched')). Caller filtert per soort + toont unmatched apart op page-niveau (Codex round-2 should-fix: drilldown moet ook unmatched audit-zichtbaar maken).

**"Open PDF"**: hergebruik `/documenten` preview-pattern (iframe in dialog of direct file-open).

**"Vervangen"**: open file-picker → upload via dezelfde `/documenten` upload-handler (parse-on-upload triggert revisie-pad).

**Geen-data fallback**: als geen actieve beschikking voor (jaar, soort) maar wel manueel `fiscale_params.voorlopige_aanslag_betaald` ingevuld: toon waarde + label "Handmatig ingevuld in /aangifte" + "Upload PDF" knop met deep-link naar `/documenten?categorie=voorlopige_aanslag&slot=va_{ib,zvw}_beschikking`. **Toon alsnog bank-aggregate (uit `get_va_betalingen`)** met IB/ZVW betaald + unmatched: zonder kenmerk om te koppelen, maar de aggregate is nuttig audit-info (Codex round-2 should-fix).

**Locked-jaar UI** (Codex round-2 should-fix): bij `jaarafsluiting_status='definitief'` → upload + "Vervangen" knoppen disabled + tooltip "Jaar gesloten — heropen via Jaarafsluiting voor wijzigingen". DB-mutaties zijn server-side gegarandeerd door `assert_year_writable` in `process_voorlopige_aanslag_upload` + `delete_aangifte_document_with_va_cleanup`.

**Geen "Eerdere revisies" UI v1** (Codex round-2 YAGNI-cut): inactive rows blijven in DB voor audit, maar UI toont alleen actieve. Sprint K kan revisie-history-sectie toevoegen.

## 6. Caller-migratie

**`compute_va_tracker`** (services/dashboard.py):
- **Signatuur en pure-status ongewijzigd** — pure helper blijft pure (Codex round-2 should-fix).
- **Nieuwe wrapper `services/dashboard.load_va_tracker_summary(db_path, jaar, today) → VATrackSummary`** — async, leest active beschikkingen + va_data, valt terug op fp, en roept `compute_va_tracker(...)` met de juiste params aan. Dashboard caller wordt 1-regel: `summary = await load_va_tracker_summary(DB_PATH, jaar, date.today())`.
- Sync via `process_voorlopige_aanslag_upload` zorgt dat `fp.voorlopige_aanslag_betaald` overeenkomt met active-beschikking — fall-through naar fp is veiligheidsnet voor handmatig-ingevulde jaren zonder PDF.

**`render_va_tile`** (components/dashboard_widgets.py):
- Click-handler wijzigt: `lambda: ui.navigate.to(f'/va-tracker/{jaar}')` ipv `/aangifte?jaar={jaar}`.

**`/aangifte` Card 3** (Codex round-2 YAGNI-cut):
- **Geen wijzigingen v1** — bedrag + termijnen blijven editable (handmatig pad). Beschikking-label en afwijkings-waarschuwing geschrapt voor v1; user ziet wijziging-status op /va-tracker page.
- Sprint K kan add: kleine label "Uit beschikking ..." + waarschuwing bij mismatch.

## 7. Tests

**`tests/test_va_parser.py`** (NIEUW, ~10 tests):
- `test_parse_va_ib_2026_real_pdf` — fixture echte 2026 IB PDF → assert alle velden
- `test_parse_va_zvw_2026_real_pdf` — idem ZVW
- `test_parse_type_detect_via_aanslagnummer_suffix_H` — `.H.` → `'ib'`
- `test_parse_type_detect_via_aanslagnummer_suffix_W` — `.W.` → `'zvw'`
- `test_parse_bedrag_dutch_thousands` — `'30.670'` → 30670.0
- `test_parse_bedrag_with_decimals` — `'30.670,50'` → 30670.50
- `test_parse_dagtekening_dutch_month` — `'31 januari 2026'` → date(2026, 1, 31)
- `test_parse_kenmerk_strips_spaces` — `'0124 4126 4706 0001'` → `'0124412647060001'`
- `test_parse_termijnen_default_11_when_missing` — geen match → 11
- `test_parse_missing_aanslagnummer_raises` — VAParseError
- `test_parse_missing_bedrag_raises` — VAParseError
- `test_parse_corrupt_pdf_raises` — pdftotext-fail → VAParseError

**`tests/test_db_queries.py`** (extend, ~7 tests):
- `test_migratie_41_voorlopige_aanslagen_table` — schema + partial unique index + CHECK constraints
- `test_process_voorlopige_aanslag_upload_inserts_and_syncs_fp` — happy path, atomic insert + fp-sync
- `test_process_voorlopige_aanslag_upload_deactivates_old_active` — revisie-pad, oude is_active=0
- `test_process_voorlopige_aanslag_upload_idempotent_on_duplicate_aanslagnummer` — return action='skip', geen mutatie
- `test_get_active_voorlopige_aanslag_returns_active_only` — inactive rows worden niet returned
- `test_get_va_betalingen_detail_classifies_ib_zvw_unmatched` — kenmerk-positie split + unmatched audit-zichtbaar
- `test_delete_aangifte_document_with_va_cleanup_clears_fp` — Codex round-2 critical: cascade + fp-clear

**`tests/test_year_locking.py`** (extend, ~2 tests):
- `test_process_voorlopige_aanslag_upload_rejected_in_definitief_year` — full transaction rollback
- `test_delete_aangifte_document_with_va_cleanup_rejected_in_definitief_year`

**`tests/test_va_tracker_page.py`** (NIEUW, ~3 tests minimaal — page-rendering broos):
- `test_compute_va_termijnen_schedule_basic` — pure helper
- `test_load_va_tracker_summary_uses_active_beschikking_when_present` — async wrapper-test
- `test_load_va_tracker_summary_falls_back_to_fp_when_no_beschikking` — backward-compat

**`tests/test_va_tracker_userflow.py`** (NIEUW, 1 end-to-end test — Codex round-2 should-fix):
- `test_va_userflow_upload_parse_sync_dashboard_delete_clears_fp`:
  1. Insert aangifte_document for VA-IB
  2. Run `process_voorlopige_aanslag_upload` with parsed data
  3. Assert active row in voorlopige_aanslagen
  4. Assert fp.voorlopige_aanslag_betaald = parsed.bedrag
  5. Assert load_va_tracker_summary uses beschikking (not fp fallback)
  6. Run `delete_aangifte_document_with_va_cleanup`
  7. Assert VA-row weg (CASCADE), fp.voorlopige_aanslag_betaald = 0

**Totaal**: ~25 nieuwe tests. Pytest 1386 → ~1411.

**Geanonimiseerde fixtures** (Codex round-2 should-fix — privacy):
NIET de echte 2026 PDFs in git. Maak `tests/fixtures/va_beschikking_ib_2026_anon.txt` en `_zvw_2026_anon.txt` — pdftotext-output met fictieve naam/adres/BSN/aanslagnummer. Parser-tests laden text-fixture en parsen direct (skip pdftotext-subprocess in unit-tests; mock of bypass via `parse_va_beschikking_text(text)`-helper).

## 8. Implementation breakdown (5 commits)

| Task | Inhoud | Geschat |
|---|---|---|
| **T1.1** | Mig 41 + `voorlopige_aanslagen` table + 4 CRUD helpers (`get_active_voorlopige_aanslag`, `process_voorlopige_aanslag_upload`, `clear_fiscale_params_va_for_jaar`, `delete_aangifte_document_with_va_cleanup`) + 9 schema/CRUD/year-lock tests | 1 commit |
| **T1.2** | `services/va_parser.py` met `parse_va_beschikking(pdf_path)` + `parse_va_beschikking_text(text)` helper-pair + `ParsedBeschikking` dataclass + 12 parser tests met geanonimiseerde fixtures + `tests/fixtures/va_beschikking_*_2026_anon.txt` | 1 commit |
| **T1.3** | /documenten upload-flow extended: parse-on-upload + mismatch-confirm UI + delegate naar atomic `process_voorlopige_aanslag_upload` + 1 integration-test (userflow upload→sync→dashboard→delete→clear) | 1 commit |
| **T1.4** | Nieuwe `/va-tracker/{jaar}` page + `compute_va_termijnen_schedule` helper + `get_va_betalingen_detail` DB-helper + `load_va_tracker_summary` async wrapper + tile click-target migratie naar /va-tracker + locked-year UI guards + 3 page/helper tests + smoke | 1 commit |
| **T2.1** | Caller-migratie naar `load_va_tracker_summary` in pages/dashboard.py + CLAUDE.md update (Sprint J VA-tracker drill-down sectie + sprint-state) + spec/plan commit + post-merge audit | 1 commit |

**5 commits, ~2 dagen**. Pytest 1386 → ~1408 (+22 nieuwe).

## 9. Risks

**Risk 1 — BD PDF-format wijziging** (Medium kans, hoge impact)
Belastingdienst kan layout subtiel aanpassen (whitespace, label-tekst). Mitigatie: parser accepteert meerdere labels via regex-OR-patterns waar nodig; faalt hard met diagnostiek bij missing critical field; manuele invoer blijft fallback.

**Risk 2 — Bron-conflict tussen handmatig en PDF** (High kans, medium impact)
User vult /aangifte handmatig, daarna upload PDF met ander bedrag. Mitigatie: confirm-dialog bij upload (PDF wint default), zichtbare afwijkingswaarschuwing op /va-tracker als manueel-fp afwijkt van active-beschikking.

**Risk 3 — Beschikking-revisie semantiek** (Medium kans, medium impact)
BD verstuurt nieuwe beschikking met nieuw aanslagnummer mid-year. v1: nieuwste actieve beschikking is waarheid; oude blijft in history voor audit. **Geen optelling** van oud + nieuw. Mitigatie: revisie-confirm-dialog vraagt user expliciet bij upload nieuwe beschikking.

**Risk 4 — pdftotext binary missing of broken** (Low kans, hoge impact)
Bestaand patroon in `import_/pdf_parser.py` raised `RuntimeError` — vangen we al af in upload-handler. Test: parse_va_beschikking met bewust-corrupt PDF (1-byte file).

## 10. Out of scope

Zie § Scope. Alle uitgesteld-items expliciet genoemd.

## 11. Codex-review-trail (audit-trail)

- **Round 1** (parallel-plan, 2026-05-06): Claude + Codex schreven onafhankelijke v1's. Synthese:
  - Click-target: page (Codex) over dialog (Claude) — gewonnen door Codex (PDFs in modal te broos)
  - Schema: `voorlopige_aanslagen` met FK + is_active partial-index (Codex) over `voorlopige_aanslag_beschikking` met `bron`-veld (Claude)
  - Bedrag: REAL (Claude — CLAUDE.md consistency) over `bedrag_cents INTEGER` (Codex — over-engineering)
  - parser_version + raw_text_sha256 dropped (Claude YAGNI-cut)
  - /documenten primary upload (Codex) over /aangifte (Claude)
  - Parser locatie: `services/va_parser.py` (Codex) over `import_/va_beschikking_parser.py` (Claude)
- **Round 2** (spec-review, 2026-05-06): Codex Approve-with-changes. 5 critical fixes geïntegreerd:
  1. Helper-naam fout `_extract_text_from_pdf` → `extract_pdf_text` corrected
  2. Regex EERSTE/LAATSTE_VERVAL_RE matchten niet door multi-line layout — geschrapt (vervaldatums derived van termijnen+jaar i.p.v. PDF-extract). BEDRAG_RE specifieker met `:` separator.
  3. Upload-flow nu atomic via `process_voorlopige_aanslag_upload(BEGIN IMMEDIATE)` ipv 3 separate steps die partial-state konden achterlaten.
  4. CASCADE-fix: nieuwe `delete_aangifte_document_with_va_cleanup` clear/resync fp na document-delete.
  5. Idempotent re-upload: duplicate aanslagnummer → skip + cleanup duplicate aangifte_documenten row.
  Plus 6 should-fixes: `get_va_betalingen_detail` returnt unmatched, geen-data fallback toont aggregate, locked-year UI hides buttons, `load_va_tracker_summary` async wrapper houdt compute_va_tracker pure, end-to-end userflow-test, geanonimiseerde fixtures (privacy).
  Plus 3 YAGNI-cuts: eerste/laatste_vervaldatum velden weg, eerdere-revisies UI naar Sprint K, /aangifte beschikking-label naar Sprint K.
- **Round 3** (post-implementation): per-task Codex review tijdens subagent-driven implementatie + post-merge audit.
