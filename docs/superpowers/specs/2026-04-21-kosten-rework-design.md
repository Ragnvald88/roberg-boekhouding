# Kosten page rework — design spec

**Date:** 2026-04-21
**Route affected:** `/kosten`
**Reference mockup:** `~/Downloads/Kosten.html`
**Status:** Design approved, awaiting implementation plan

## 1. Goal

Rework the Kosten page around a unified, bank-transaction-centric reconciliation list while preserving all existing fiscal logic (activastaat, afschrijvingen, KIA, year-lock). The `uitgaven` table becomes the fiscal side-record, linked 0-or-1 to 1 with a `banktransacties` row via a new FK. The existing investment/depreciation UI moves into a second tab on the same route, unchanged.

## 2. Why this approach

The reference HTML centres the workflow on bank transactions with invoice PDFs attached. In the current app, `uitgaven` (manual expense entries, optionally with PDF) and `banktransacties` (raw CSV-imported debits/credits) are separate concepts. They tell overlapping stories about the same payment events, with no relationship in the schema.

Three options were considered:

- **Merge the two tables.** Rejected: breaks cash/contant expenses, requires data migration, couples UI change to a fiscal-code-touching refactor.
- **Parallel unified view, no FK.** Rejected: row identity is ambiguous; duplicate-detection becomes heuristic and fragile.
- **Keep both tables, add nullable FK `uitgaven.bank_tx_id`.** Accepted. Minimal schema change, zero data migration, fully rollback-able, preserves every existing code path.

Cash receipts keep working (uitgave with `bank_tx_id = NULL`). Bank page keeps working untouched (matches outgoing facturen via the unrelated `koppeling_type/koppeling_id` columns). Investments keep working (they are still ordinary uitgaven with `is_investering=1`).

## 3. Constraints (non-negotiable)

- **WAL-safe, additive schema only.** `ALTER TABLE ADD COLUMN` + new indexes. No rename, no drop, no data migration.
- **Year-lock everywhere.** Every new write path calls `assert_year_writable(db_path, datum)` against the relevant date.
- **Raw SQL with `?` placeholders.** No f-strings in SQL. Connection pattern `async with get_db_ctx(db_path) as conn:`.
- **Datum range filter, not `strftime`.** Use `datum >= 'YYYY-01-01' AND datum < 'YYYY+1-01-01'` so the existing `idx_uitgaven_datum` and `idx_banktransacties_datum` indexes are hit.
- **Public API of fiscal helpers is frozen.** `bereken_afschrijving`, `get_afschrijving_overrides_batch`, `get_investeringen_voor_afschrijving`, all aangifte/jaarafsluiting functions stay as-is.
- **NiceGUI conventions.** Edit/add in `ui.dialog` — no `ui.drawer` (not used anywhere in the codebase). Quasar semantic colors only (`positive`, `negative`, `warning`, `primary`, `info`). Persistent `ui.table` updated via `table.rows = rows; table.update()`.
- **Art. 11 vrijgesteld.** No BTW UI on this page (no BTW segmented, no "BTW aftrekbaar" KPI).
- **No drag-and-drop of PDFs onto rows in v1.** Per-row paperclip button opens file picker instead.

## 4. Schema changes

Exactly two new columns, applied via the existing `_run_migrations` / `PRAGMA user_version` pattern in `database.py`.

```sql
ALTER TABLE uitgaven ADD COLUMN bank_tx_id INTEGER
    REFERENCES banktransacties(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_uitgaven_bank_tx ON uitgaven(bank_tx_id);

ALTER TABLE banktransacties ADD COLUMN genegeerd INTEGER NOT NULL DEFAULT 0
    CHECK (genegeerd IN (0, 1));
CREATE INDEX IF NOT EXISTS idx_bank_genegeerd ON banktransacties(genegeerd);
```

Semantics:
- `uitgaven.bank_tx_id` — nullable; `NULL` means cash/contant. `ON DELETE SET NULL` so deleting a bank tx never cascades into fiscal records.
- `banktransacties.genegeerd` — `1` means "private / non-business; hide from Kosten forever". Used for owner withdrawals, ATM, personal transfers.

## 5. Row status derivation (single source of truth)

Sequential and mutually exclusive. One function `derive_status(row)` lives in `components/kosten_helpers.py`, tested in isolation, used by both the view query and the UI badge logic.

```
if bank_tx present and bank_tx.genegeerd == 1:
    → (hidden from all tabs, shown only via explicit "Toon genegeerd")
elif bank_tx present and uitgave is None:
    → 'ongecategoriseerd'
elif uitgave.categorie == '':
    → 'ongecategoriseerd'
elif not uitgave.pdf_pad:
    → 'ontbreekt'
else:
    → 'compleet'

# Manual uitgave (bank_tx_id IS NULL) always carries the 'contant' badge
# plus the derived status above (applied to the uitgave fields).
```

Tabs: **Alle · Ongecategoriseerd · Ontbreekt · Compleet**. Counts derived from the same function.

## 6. New database functions (in `database.py`)

All are year-locked where they mutate, via `assert_year_writable`.

### 6.1 `get_kosten_view(db_path, jaar, status=None, categorie=None, search=None) → list[KostenRow]`

Returns the unified list. `KostenRow` is a small dataclass with fields:

```
id_bank: int | None     # bank_tx.id
id_uitgave: int | None  # uitgave.id
datum: str              # YYYY-MM-DD
bedrag: float           # ABS — always positive
tegenpartij: str        # bank_tx.tegenpartij or '' if manual
omschrijving: str       # uitgave.omschrijving preferred, else bank_tx.omschrijving
iban: str               # bank_tx.tegenrekening or ''
categorie: str          # uitgave.categorie or '' (never bank_tx.categorie)
pdf_pad: str            # uitgave.pdf_pad or ''
is_investering: bool
zakelijk_pct: float | None
status: str             # from derive_status
is_manual: bool         # bank_tx_id IS NULL
```

Query:
```sql
-- bank side
SELECT 'bank' AS source, b.id AS id_bank, b.datum, ABS(b.bedrag) AS bedrag,
       b.tegenpartij, COALESCE(u.omschrijving, b.omschrijving) AS omschrijving,
       b.tegenrekening AS iban,
       u.id AS id_uitgave, COALESCE(u.categorie,'') AS categorie,
       COALESCE(u.pdf_pad,'') AS pdf_pad,
       COALESCE(u.is_investering,0) AS is_investering,
       u.zakelijk_pct
FROM banktransacties b
LEFT JOIN uitgaven u ON u.bank_tx_id = b.id
WHERE b.bedrag < 0
  AND b.genegeerd = 0
  AND b.datum >= ? AND b.datum < ?

UNION ALL

-- manual side
SELECT 'manual', NULL, u.datum, u.bedrag,
       '', u.omschrijving, '',
       u.id, u.categorie, COALESCE(u.pdf_pad,''),
       u.is_investering, u.zakelijk_pct
FROM uitgaven u
WHERE u.bank_tx_id IS NULL
  AND u.datum >= ? AND u.datum < ?

ORDER BY datum DESC;
```

Post-filter in Python (small result sets): status, categorie, search. Search is case-insensitive substring over tegenpartij + omschrijving + `str(bedrag)`.

### 6.2 `ensure_uitgave_for_banktx(db_path, bank_tx_id, **overrides) → int`

Idempotent. If a uitgave with this `bank_tx_id` exists, returns its id. Otherwise inserts a new uitgave with:

- `datum = bank_tx.datum`
- `bedrag = ABS(bank_tx.bedrag)` (enforced equality at creation time; the Detail dialog does not expose `bedrag` for editing when `bank_tx_id` is set, so divergence cannot happen through the UI)
- `omschrijving = bank_tx.tegenpartij` (falls back to `bank_tx.omschrijving` if tegenpartij is empty)
- `categorie = ''` (caller fills in)
- plus any `**overrides` fields

Year-locked against `bank_tx.datum`.

### 6.3 `mark_banktx_genegeerd(db_path, bank_tx_id, genegeerd=1) → None`

Toggles the flag. Year-locked against `bank_tx.datum`.

### 6.4 `find_pdf_matches_for_banktx(db_path, bank_tx_id, jaar) → list[PdfMatch]`

Uses existing `scan_archive(jaar, existing_filenames)`. For each archive file not already imported, computes a match score against this bank_tx:

- bedrag match (if filename includes a parseable amount): equal within €0.01
- tegenpartij token overlap: normalize both sides (lowercase, strip punctuation, split on whitespace/`_`/`-`), require at least one shared token of length ≥ 4

Returns matches sorted by (has_bedrag_match, tegenpartij_token_count) desc. The inbox's "Slimme suggestie" button only surfaces when the top result has `has_bedrag_match=True` AND `tegenpartij_token_count >= 1`; otherwise the row shows the generic "Bon koppelen / Categoriseren" action.

`PdfMatch` has `path: Path`, `filename: str`, `categorie: str` (from folder via `FOLDER_TO_CATEGORIE`; files in unmapped folders are already filtered out by `scan_archive`), `score: int`.

### 6.5 `get_kpi_kosten(db_path, jaar) → KpiKosten`

Single pass. Returns:

```
totaal: float
ontbreekt_count: int
ontbreekt_bedrag: float
afschrijvingen_jaar: float  # sum via bereken_afschrijving over all is_investering=1
investeringen_count: int
investeringen_bedrag: float  # sum of ABS(aanschaf_bedrag * zakelijk_pct/100) for this year
monthly_totals: list[float]  # length 12
```

## 7. Page structure (`pages/kosten.py`)

```
page_title('Kosten')  + [Importeer] [Nieuwe uitgave]    ← top-right

ui.tabs:  [ Transacties ] [ Investeringen ]

# Transacties panel:
  Toolbar: Jaar | Status tabs | View toggle (Lijst/Per maand) | Export CSV
  Search field + categorie chips row
  Reconciliation inbox band (only if ongecat+ontbreekt > 0, max 4 cards, datum desc)
  KPI strip (4 cards)
  Bulk action bar (appears on selection)
  Main ui.table (persistent, updated via rows + update())
  Categorie breakdown card (horizontal bars per categorie)

# Investeringen panel:
  (Today's activastaat UI — lifted verbatim into pages/kosten_investeringen.py
   and imported here. No behavior change.)
```

## 8. KPI strip (4 cards)

1. **Totaal kosten {jaar}** — `SUM(ABS(bedrag))` over the unified list; sparkline = `monthly_totals`.
2. **Factuur ontbreekt** — count + summed bedrag; warn color; click → Ontbreekt tab.
3. **Afschrijvingen dit jaar** — `afschrijvingen_jaar`; click → Investeringen tab.
4. **Investeringen dit jaar** — `investeringen_count` + `investeringen_bedrag`; click → Investeringen tab.

No BTW KPI (art. 11). No "Terugkerend" KPI (not actionable).

## 9. Reconciliation inbox

Renders only when `ongecat_count + ontbreekt_count > 0`. Top 4 rows by datum desc.

Each card:
- Tegenpartij + datum + bedrag header
- If `find_pdf_matches_for_banktx` returns exactly one high-confidence match: "Slimme suggestie: `{filename}` — Koppel" button. Click → copies PDF into `UITGAVEN_DIR` via existing `_copy_and_link_pdf`, calls `ensure_uitgave_for_banktx` with `categorie` from folder, sets `pdf_pad`, refreshes.
- Otherwise: "Bon koppelen / Categoriseren" button → opens detail dialog.

"Alles bekijken" chev-right button → switches to Ontbreekt tab.

## 10. Main table

`ui.table` with `selection='multiple'`, `pagination={'rowsPerPage': 20, 'sortBy': 'datum', 'descending': True, 'rowsPerPageOptions': [10, 20, 50, 0]}`.

Columns:
- `☐` (selection)
- `datum` (formatted, tabular-nums)
- Tegenpartij + omschrijving (avatar chip with initials, color deterministic from tegenpartij string)
- Categorie pill (`q-btn-dropdown` with `KOSTEN_CATEGORIEEN` values; click sets categorie — lazy-creates uitgave via `ensure_uitgave_for_banktx`)
- Factuur status (pill: `compleet` positive · `ontbreekt` warning · `ongecategoriseerd` info; `contant` badge appended for manual rows; paperclip icon linking to PDF when `pdf_pad` present)
- Bedrag (right, tabular-nums, `format_euro`)
- Actions (overflow menu: Open detail · Markeer als privé — only for bank_tx rows · Verwijder uitgave — only for uitgaven)

Body-cell slots use the same Quasar `q-td` + `$parent.$emit` pattern as `pages/facturen.py`.

View toggle `Lijst / Per maand`:
- **Lijst** (default) — flat sorted by datum desc
- **Per maand** — a month-divider header row is inserted via a `top-row` slot; total and count displayed right-aligned

Bulk actions:
- Wijzig categorie (bulk set; for bank-tx rows without uitgave, creates them)
- Verwijder selectie (only for uitgaven rows)
- Markeer als privé (only for bank_tx rows)

Year-lock is enforced per row. If some rows are in a definitief year, the action skips those and shows a summary toast: "X rijen verwerkt, Y overgeslagen (jaar afgesloten)."

## 11. Detail dialog

One `ui.dialog` with `ui.card().classes('w-full').style('max-width: 760px')`, containing `ui.tabs` + `ui.tab_panels`: **Detail · Factuur · Historie**.

### 11.1 Detail panel
- Big bedrag (28px, bold, tabular-nums), full date (dutch long form), tegenpartij + omschrijving
- IBAN read-only line (hidden for manual uitgaven)
- Bedrag: read-only display when `bank_tx_id` is set; editable `ui.number` only for manual uitgaven (matches today's edit-dialog)
- Categorie `ui.select(KOSTEN_CATEGORIEEN)`
- `ui.checkbox('Dit is een investering')` — reveals levensduur (3/4/5 from `LEVENSDUUR_OPTIES`), restwaarde %, zakelijk % — same widgets and defaults as the current add-dialog
- Notitie `ui.textarea` → maps to `uitgaven.omschrijving`
- "Ontkoppel bank-transactie" link (only visible when both sides exist) — sets `bank_tx_id = NULL`

Save path: lazy-create uitgave via `ensure_uitgave_for_banktx` if none exists, then `update_uitgave` with all fields. Year-locked.

### 11.2 Factuur panel
- If `pdf_pad` present:
  - `<iframe>` with base64 data URI (same pattern as facturen preview; isolates from Quasar CSS)
  - Buttons: Download · Open volledig · Verwijder bon (reuses current `remove_bon` flow)
- Else:
  - `ui.upload` (auto_upload, max 10 MB, `.pdf,.jpg,.jpeg,.png`)
  - Archive suggestions list from `find_pdf_matches_for_banktx`; each row has thumbnail icon, filename, vendor, bedrag, and a "Koppel" button that calls `_copy_and_link_pdf`

### 11.3 Historie panel
- `SELECT` last 12 months' bank_tx (matching tegenpartij, case-insensitive) UNION uitgaven with matching omschrijving-substring
- Render as simple list: datum, bedrag. No extra actions.
- Informational tip if ≥ 3 hits in ≤ 120 days: "Dit lijkt terugkerend — gebruik Importeer om volgende exemplaren automatisch te categoriseren."

Footer: **Annuleren · Verwijder uitgave** (only when linked uitgave exists) **· Opslaan** (primary).

## 12. Importeer dialog (evolved, not rewritten)

Keep the existing `open_import_dialog` scan + grouped listing. Additions:

- For each unimported archive file, call `find_matching_banktx_for_pdf(...)` (inverse of `find_pdf_matches_for_banktx`). If a single high-confidence hit, show `↔ Rabobank 21-04-2026 €120,87` next to the filename in caption style.
- On "do_import": if a match was confirmed, the prefilled uitgave dialog gets `bank_tx_id` set. Otherwise behaves as today.
- Unmatched imports create a standalone uitgave (`bank_tx_id = NULL`) exactly like today.

## 13. Nieuwe uitgave dialog

`open_add_uitgave_dialog` — **unchanged**. Always creates with `bank_tx_id = NULL`. Intended for cash/contant receipts only.

## 14. Files to edit vs. add

**Edit:**
- `database.py` — migrations block (two `ALTER TABLE`, two indexes); five new helper functions listed in §6
- `pages/kosten.py` — full rewrite of page body
- `import_/expense_utils.py` — optionally add `extract_bedrag_from_filename`. If most archive filenames don't include a parseable amount (assess during implementation), skip this and let `find_pdf_matches_for_banktx` fall back to tegenpartij-token-only matching with `has_bedrag_match=False` everywhere. The high-confidence gate in §6.4 still works: it just rarely fires, which is acceptable — the inbox degrades to showing the generic action, not broken behavior.

**Add:**
- `components/kosten_helpers.py` — pure functions: `derive_status(row)`, `match_tokens(tegenpartij, filename_stem)`, `tegenpartij_color(s)`, `initials(s)`
- `pages/kosten_investeringen.py` — lifted activastaat + `open_afschrijving_dialog` (same code, separate module, no behavior change)
- `tests/test_kosten_view.py`
- `tests/test_kosten_matching.py`
- `tests/test_ensure_uitgave.py`
- `tests/test_bank_genegeerd.py`
- `tests/test_kpi_kosten.py`

**Must not touch:**
- `pages/bank.py` — raw CSV import + outgoing-factuur matching stays
- `fiscal/afschrijvingen.py` — frozen
- `pages/aangifte.py`, `pages/jaarafsluiting.py` — frozen (both still read `uitgaven` exactly as before)
- `components/layout.py`, `components/utils.py` (except confirming `KOSTEN_CATEGORIEEN` usage)

## 15. Testing matrix

| Test | What it proves |
|---|---|
| `test_kosten_view_union_mix` | bank-only, linked, and manual rows all appear with correct derived status |
| `test_kosten_view_year_range` | datum filter uses `>= && <`, not `strftime`; row on 2025-12-31 excluded when jaar=2026 |
| `test_kosten_view_genegeerd_hidden` | `genegeerd=1` rows never appear in the view |
| `test_kosten_view_sign_convention` | bedrag always positive (ABS normalization works on both sides) |
| `test_ensure_uitgave_idempotent` | second call with same `bank_tx_id` returns the same uitgave_id |
| `test_ensure_uitgave_enforces_bedrag` | uitgave.bedrag == ABS(bank_tx.bedrag) on creation |
| `test_ensure_uitgave_year_locked` | raises `YearLockedError` on a definitief year |
| `test_derive_status_matrix` | every status transition covered (hidden, ongecat, ontbreekt, compleet, contant badge) |
| `test_match_tokens_hit` | "KPN B.V." vs "KPN_maart2026.pdf" → hit |
| `test_match_tokens_miss` | "Shell" vs "Apple" → miss |
| `test_match_tokens_case_and_punct` | "Boekhouder Verzekering" vs "boekhouder-verzekering_q2.pdf" → hit |
| `test_kpi_kosten_totals` | totaal == SUM(abs(bedrag)); afschrijvingen matches `bereken_afschrijving` sum |
| `test_kpi_kosten_monthly_totals` | 12 entries, ordered Jan→Dec, sums match |
| `test_mark_genegeerd_year_locked` | `assert_year_writable` enforced |
| `test_existing_activastaat_preserved` | import `pages/kosten_investeringen.py`, smoke-assert rendering primitives unchanged |

All existing tests must continue to pass untouched. Run with `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`.

## 16. Risks & explicit deferrals

- **Bedrag mismatch between bank_tx and uitgave** — explicitly disallowed; enforced equality on creation. Sufficient for Roberg's flow.
- **Bank API (PSD2)** — out of scope.
- **Email-to-invoice pipeline** — out of scope.
- **Drag-and-drop** — deferred; paperclip button covers the use case.
- **Split tx over multiple categorieën** — deferred; would require new `uitgave_splits` table.
- **Recurring-tx auto-categorization during CSV import** — deferred to v1.1 (v1 just shows the informational tip in Historie tab when a pattern is detected).
- **Auto-linking orphan uitgaven when a matching bank_tx imports later** — deferred to v1.1.

## 17. Rollback plan

If the feature turns out to be a mistake:
- `bank_tx_id` column can stay (harmless NULL for existing rows).
- `genegeerd` column can stay (harmless `0` for existing rows).
- Revert `pages/kosten.py` to the prior version from git.
- `pages/kosten_investeringen.py` can either stay as a separate module or be inlined back.
- Existing tests continue to pass because the fiscal APIs are unchanged.

No data migration to undo. No fiscal code to revert.
