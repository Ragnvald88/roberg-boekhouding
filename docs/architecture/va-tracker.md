# VA-tracker (Voorlopige Aanslag)

Drill-down + PDF-parse + dashboard tile voor Voorlopige Aanslagen van de Belastingdienst. Sprint I (basis) + Sprint J (PDF-parse + drill-down + redesign + backfill).

## Schema

`voorlopige_aanslagen` tabel (mig 41): FK CASCADE naar `aangifte_documenten`. Invarianten:
- `UNIQUE(aanslagnummer)`
- `UNIQUE(document_id)` — garandeert 1-1 koppeling doc↔VA-row. Zonder dit zou `delete_aangifte_document_with_va_cleanup` fp niet deterministisch kunnen clearen. **NIET wegoptimaliseren bij re-runs.**
- Partial unique index `WHERE is_active=1` — max 1 actieve per (jaar, soort)
- Audit-trail per beschikkings-revisie via `is_active=0` op oude rows

## Veldnaam-bug (NIET renamen v1)

`fiscale_params.voorlopige_aanslag_betaald` HEET "betaald" maar bevat het BD-beschikkingsbedrag (= jaar-verplichting), NIET wat is betaald. Helpers gebruiken lokale alias `ib_verplicht`. Sprint K kan migration-rename overwegen.

## Type-detect via aanslagnummer-suffix

- `1244.12.646.H.60.01` → IB (`H` = Hoofdbelasting/IB+PVV)
- `1244.12.646.W.60.01.4` → ZVW (`W` = Werknemersverzekering/ZVW)
- Header-tekst is fallback
- Betalingskenmerk = 16 digits, genormaliseerd via `database._normalize_va_kenmerk` (strip non-digits — BD-portaal copy-paste voegt punten/spaties toe)
- Positie [10:12] splitst IB vs ZVW (<50 = IB, ≥50 = ZVW)

## PDF-parser strategy (`services/va_parser.py`)

Pure helper-pair `parse_va_beschikking(pdf_path)` + `parse_va_beschikking_text(text)` + `ParsedBeschikking` frozen dataclass + `VAParseError`. Hergebruikt `import_/pdf_parser.extract_pdf_text` (pdftotext subprocess).

- **Whitespace-normalize ÉÉN keer** (`re.sub(r'\s+', ' ', text)`) vóór regex — multi-line layout uit pdftotext-layout breekt anders
- `_BEDRAG_RE` met specifiek `Te betalen\s*:\s*€` separator (uniek voor betaalblok; PDF heeft 4 "Te betalen" varianten waarvan alleen deze het bedrag heeft)
- Critical fields raise `VAParseError`: aanslagnummer, jaar, dagtekening, bedrag, kenmerk
- Termijnen optional (default 11 als regex faalt of buiten 1-12)

## Atomic upload pipeline

`database.process_voorlopige_aanslag_upload(*, document_id, parsed)` doet ALLES in één `BEGIN IMMEDIATE`-tx:
1. Doc-validation (existence + categorie + jaar-match) vóór mutaties
2. Idempotent skip op duplicate `aanslagnummer`
3. Deactivate-old (`is_active=0` op vorige rij voor dat jaar+soort)
4. Insert-new (`is_active=1`)
5. Sync `fiscale_params.voorlopige_aanslag_*`

Bij ANY exception: full ROLLBACK. Hergebruikt door `/documenten` upload én `services.va_backfill`.

## `delete_aangifte_document_with_va_cleanup` is single-tx atomic

**NIET delegate** naar `delete_aangifte_document` met aparte fp-clear. De delegate-pattern heeft een failure-window tussen 2 commits waarin fp stale blijft. Naam suggereert "wrap" maar implementatie is bewust inline — comment in code waarschuwt re-runners.

## Backfill voor pre-Sprint-J uploads

`services/va_backfill.backfill_voorlopige_aanslag_documents(jaar) → BackfillSummary` met 4 result-categorieën (processed/skipped/failed/locked). Per-doc soft-fail. Detect via `database.get_unprocessed_voorlopige_aanslag_documents(jaar)` LEFT JOIN. `/va-tracker` toont banner + "PDFs verwerken"-CTA.

**Codex round-3 design-keuze**: detect-on-load + expliciete user-CTA, GEEN auto-mutate-on-render. Skip-result voor duplicate aanslagnummer geeft notify-hint "Verwijder duplicate uit /documenten" — anders blijft banner permanent.

## Compute pipeline

`services.dashboard.compute_va_tracker` (pure) + `VATrackLine` + `VATrackSummary` frozen dataclasses + `compute_va_termijnen_schedule` + `load_va_tracker_summary` async wrapper. Datasource fall-through: active beschikking → fp-handmatig → defaults. `compute_va_tracker` zelf blijft pure (geen DB-imports). Caller in `pages/dashboard.py` is 1-line.

## VA-tracker quirks

- **Kenmerk-jaar-mismatch**: VA-2025 betaling in januari 2026 wordt door `get_va_betalingen` datum-filter aan jaar 2026 gekoppeld. Gebruiker controleert handmatig in /transacties.
- **Positieve BD-banktransacties** (correcties/teruggaves): `bedrag > 0` van Belastingdienst-IBAN wordt door `get_va_betalingen` genegeerd voor zowel `betaald` als `bankdata_tot_datum`. Gebruiker ziet via /transacties wat werkelijk teruggekomen is.
- **Termijnen-convention `13 - N`**: aantal termijnen N impliceert eerste-termijn-maand 13-N. Heuristiek, geen BD-bron-waarheid. User kan termijnen-aantal in /aangifte handmatig overtypen.
- **VA `totaal_betaald` (BREAKING vanaf Sprint I)**: excludeert `unmatched_betaald`. Voor v1 callers: gebruik `ib_betaald + zvw_betaald` voor de tracker-ratio, en `unmatched_betaald` apart waar relevant.
- **`compute_va_tracker.achterstand`**: termijn-count × termijnbedrag (NIET puur EUR-diff). BD redeneert in vervaltermijnen, niet EUR-totalen. Lump-sum-ahead met gemiste termijn blijft zichtbaar als `'achter'`.
- **`has_overbetaald` line-first**: gezet wanneer ANY line is overbetaald, ook bij open totaal_resterend. Renderer toont badge alleen bij status='voldaan' AND has_overbetaald — voorkomt verwarrende badge naast warning-icon.

## `/va-tracker/{jaar}` page

Hero (status-zin + bedragen + progress + bron-disclaimer + primary CTA) + 2 side-by-side summary-cards (IB + ZVW, GEEN expansions per soort) met uploaded-badge + volledige beschikking-velden + termijnen-overzicht (per-soort active/indicatief flag) + bank-tx flat list + unmatched-audit. User-feedback driven 3 redesign-rondes: van expansions → flat → minimal tile + per-soort details.

**Locked-jaar UI**: upload-knoppen `disable` + tooltip (NIET hidden).

## Tile-minimum

Hero-tile = 2-sec scanbaar. Title + hero-value (resterend) + 1 context-line via `_va_tile_context_line` priority-ordered (achter/voldaan/volgende-termijn/counts). DETAIL hoort op `/va-tracker`, NIET op de tile.

## NiceGUI dialog idiom

Gebruik built-in `Dialog.__await__` + `submit(value)` — NIET `asyncio.Future` met `dlg.on('hide', ...)` callback (Codex catch: ~30 LoC reinvented wheel). Pattern:
```python
with ui.dialog() as dlg, ui.card():
    ...
    ui.button(on_click=lambda: dlg.submit(True))
result = await dlg
```
Dismissal returnt None → `bool(None)=False` = safe-default voor destructive overwrites.

## NiceGUI `linear_progress`

ALTIJD `show_value=False` — default rendert raw float-waarde als tekst-overlay op de bar, lelijk. Repo-wide convention.

## Privacy-conventie tests

`tests/fixtures/va_beschikking_*_2026_anon.txt` zijn geanonimiseerde pdftotext-output (`9999.99.999.[HW].60.01`, `FICTIEF NAAM`, fictieve kenmerk-digits). Echte PDFs staan in `~/Library/Application Support/Boekhouding/data/aangifte/{jaar}/voorlopige_aanslag/` (gitignored). Privacy-grep verifieert geen PII-leak in commits.
