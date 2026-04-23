# Bank / Kosten consolidation — design

**Status:** draft, pending user review
**Date:** 2026-04-22
**Predecessor:** `2026-04-21-kosten-rework-design.md` (closed the *data* overlap; this spec closes the remaining *UX* overlap)

---

## 1. Problem

Post-Kosten-rework (migratie 27), `uitgaven.categorie` is the single source of truth for debit categoriseringen. Data overlap solved. What remains is **UX overlap**: `/bank` and `/kosten` both render the same bank transactions and both host parts of the "process a transaction" workflow. Concretely:

| Activity | `/bank` today | `/kosten` today |
|---|---|---|
| CSV import + archive list | yes | — |
| Debit categorisation | read-only display | editable (inline / bulk / detail) |
| Positive categorisation (Omzet/Privé/Belasting/AOV) | editable | — |
| Factuur-match preview after import | yes | — |
| Bon / PDF koppelen | — | yes |
| Markeer als privé (`banktransacties.genegeerd`) | — | yes |
| Delete bank tx | yes | — |
| Manual cash uitgaven | — | yes |
| Investeringen / activastaat | — | yes (tab) |

The user lives with two "decision screens" for the same set of transactions. Other accounting tools (QuickBooks "For Review", Xero reconciliation, Moneybird transacties, YNAB approve/match) converge on **one** inbox that handles both income-matching and expense-categorising; raw bank-feed management is a thin secondary view. This spec brings the app in line with that pattern.

## 2. Goal

One transaction inbox. One overview page. No duplicate categorie-controls, no "where do I do this" question.

- **`/transacties`** (renamed from `/bank`) — the *only* screen where work happens on money movements. Bank debits + bank positives + manual cash, unified.
- **`/kosten`** — read-only overzicht: KPI's, categorie-breakdown (click-through), per-maand chart, terugkerende-kosten, activastaat.

Non-goals (out of scope):
- Schema changes (none needed)
- Rabobank API / auto-import beyond current CSV flow
- Preset/filter-saving system (URL query-params via click-through replace it)
- Year-over-year comparison, top-vendors ranking, jaar-prognose (YAGNI for v1; revisit if missed)

## 3. Page-level design

### 3.1 `/transacties` — the inbox

Header row:
- Title "Transacties"
- Actions right-aligned: `[+ Contante uitgave]` · `[Importeer CSV]` · `[Archief-PDFs importeren]` · `[Matches controleren (N)]` (shown only when unmatched proposals exist)

Filter bar (single row):
- Jaar · Maand · Status · Categorie · Type · Zoeken

Status filter values (UI label → internal keys selected):
- Alle → all statuses
- Ongecategoriseerd → `{ongecategoriseerd}`
- Bon ontbreekt → `{ontbreekt_bon}` (debits/cash only)
- Gekoppeld aan factuur → `{gekoppeld_factuur}` (positives only)
- Privé-verborgen → `{prive_verborgen}` (requires `include_genegeerd=True` in the DB call; only this filter surfaces those rows so user can un-hide)
- Compleet → `{compleet, gecategoriseerd}` (both "done" end-states — debits with cat+bon, positives with cat)

Type filter values: Alle · Bank · Contant.

Main table — unified list with a single row-model. Columns:

| Kolom | Bron | Gedrag |
|---|---|---|
| Datum | `datum` | sorteerbaar |
| Tegenpartij/omschrijving | `tegenpartij` / `omschrijving` | avatar + initials (current Kosten UI) |
| Categorie | inline `q-select`, options per-row | debits/cash → kosten-categorieën; positives → omzet/privé/belasting/AOV; wand-icoon als suggestie beschikbaar |
| Bedrag | signed, gekleurd | positief = teal, debit/cash = rood |
| Factuur/bon | chip | `Compleet` / `Bon ontbreekt` / `Nieuw` / `Gekoppeld aan factuur #…` / `Privé` / `contant` |
| Acties | | `📎 bon` · `⋮ detail` · `🗑 verwijder` |

Row colouring by status-key (same palette as today):
- teal-1 = `gekoppeld_factuur`
- amber-1 = `ontbreekt_bon`
- red-1 = `ongecategoriseerd`
- grey/muted = `prive_verborgen` (only rendered when status-filter is "Privé-verborgen")
- white = `compleet` (debits) or `gecategoriseerd` (positives) — both "done"

Row actions / bulk:
- Click-through on categorie `q-select` → server-side handler branches: `id_bank` + debit → `set_banktx_categorie` (lazy-creates uitgave); `id_bank` + positive → `update_banktransactie.categorie`; manual (`id_uitgave` only) → `update_uitgave.categorie`. Existing `set_banktx_categorie` already branches on sign; page handler only picks between `set_banktx_categorie` and `update_uitgave`.
- `📎 bon` → Detail-dialog Factuur-tab (current `_open_detail_dialog(row, default_tab='factuur')`)
- `⋮ detail` → Detail-dialog Detail-tab (current `_open_detail_dialog(row)`)
- `🗑 verwijder` → depends on type:
  - bank tx → `delete_banktransacties([id_bank])` (cascade-revert factuur if matched, as today)
  - manual uitgave → `delete_uitgave(id_uitgave)`
- Selection → bulk bar: `Categorie wijzigen` · `Markeer als privé` (bank-only rows) · `Verwijderen`

Per-maand grouping toggle (current Kosten feature) stays — works across all row-types now.

CSV-bestanden-lijst: moves below the table as a collapsed `ui.expansion` ("Geïmporteerde CSV-bestanden (N)"). Rarely needed; keeps traceability.

Factuur-match dialog:
- Triggered after CSV import (unchanged) — pre-selects high-confidence; low-confidence requires explicit tick
- New: header button `[Matches controleren (N)]` invokes the same dialog outside the import flow so the user can review pending proposals any time. N = `len(find_factuur_matches())` on page load, refreshed after every mutation.

URL query-params (for click-through from `/kosten`):
- `?jaar=2026` · `?categorie=Telefoon/KPN` · `?status=ongecategoriseerd` · `?search=KPN`
- Consumed on page mount, preset into the filter-refs, then a single `refresh()` renders.

### 3.2 `/kosten` — the overview

Header: title only. No action buttons. (Add-uitgave / import live on `/transacties`.)

Single filter: jaar selector.

Tabs: **Overzicht** and **Investeringen**.

#### Tab Overzicht

KPI strip (4 cards, all clickable where a destination makes sense):

| Card | Value | Sub | Click destination |
|---|---|---|---|
| Totaal kosten {jaar} | `€X` | "N actieve maanden" | — |
| Te verwerken | count | `€X openstaand` | `/transacties?jaar={jaar}&status=ongecategoriseerd` |
| Afschrijvingen {jaar} | `€X` | "Zie tab Investeringen" | switch to Investeringen-tab |
| Investeringen {jaar} | count | `€X` | switch to Investeringen-tab |

Kosten per maand — `ui.echart` bar chart, 12 maanden, hover tooltip met € en #tx. Data: `get_kosten_per_maand(jaar)`.

Per categorie breakdown — current horizontal bars (categorienaam · bedrag · %), **klikbaar per regel** → `/transacties?jaar={jaar}&categorie={cat}`. Data: `get_kosten_breakdown(jaar)`.

Terugkerende kosten — card met lijstje van tegenpartijen die ≥3 uitgaven hebben in de laatste 365 dagen. Kolommen: `Tegenpartij · Aantal · Jaar-totaal · Laatste datum`. Klik → `/transacties?jaar={jaar}&search={tegenpartij}`. Data: `get_terugkerende_kosten(jaar, min_count=3, window_days=365)`.

#### Tab Investeringen

Unchanged — re-uses `pages/kosten_investeringen.py:laad_activastaat` verbatim.

## 4. Data / database changes

One tiny migration (M1 from v1.1 polish — subsumed into this work); otherwise all additions are DB-helper functions.

### 4.0 Migratie 28 — unique partial index on `uitgaven.bank_tx_id`

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_uitgaven_bank_tx_unique
  ON uitgaven(bank_tx_id)
  WHERE bank_tx_id IS NOT NULL;
```

Closes a race in the Importeer flow where two concurrent link attempts on the same bank_tx could create two uitgaven. Partial index — NULLs stay permitted (cash uitgaven). Idempotent via `IF NOT EXISTS`. Migration runs inside existing schema-version guarded upgrader in `database.py:init_db`.

### 4.1 New: `get_transacties_view`

Signature:
```python
async def get_transacties_view(
    db_path: Path,
    jaar: int,
    maand: int | None = None,        # 1-12; None = alle maanden
    status: str | None = None,        # derive_status values + 'gekoppeld_factuur'
    categorie: str | None = None,
    type: str | None = None,          # 'bank' | 'contant' | None
    search: str | None = None,
    include_genegeerd: bool = False,  # True surfaces privé-verborgen rows
) -> list[TransactieRow]: ...
```

SQL — UNION ALL of three sources:

```sql
-- bank debits
SELECT 'bank_debit' AS source,
       b.id AS id_bank,
       u.id AS id_uitgave,
       b.datum, b.bedrag,
       COALESCE(b.tegenpartij, '') AS tegenpartij,
       COALESCE(NULLIF(u.omschrijving, ''), b.omschrijving, '') AS omschrijving,
       COALESCE(b.tegenrekening, '') AS iban,
       COALESCE(u.categorie, '') AS categorie,
       COALESCE(u.pdf_pad, '') AS pdf_pad,
       COALESCE(u.is_investering, 0) AS is_investering,
       u.zakelijk_pct AS zakelijk_pct,
       b.koppeling_type, b.koppeling_id,
       b.genegeerd
FROM banktransacties b
LEFT JOIN uitgaven u ON u.bank_tx_id = b.id
WHERE b.bedrag < 0 AND b.datum >= ? AND b.datum < ?

UNION ALL

-- bank credits (positives)
SELECT 'bank_credit', b.id, NULL, b.datum, b.bedrag,
       COALESCE(b.tegenpartij, ''), COALESCE(b.omschrijving, ''),
       COALESCE(b.tegenrekening, ''), COALESCE(b.categorie, ''),
       '' AS pdf_pad, 0 AS is_investering, NULL AS zakelijk_pct,
       b.koppeling_type, b.koppeling_id, b.genegeerd
FROM banktransacties b
WHERE b.bedrag >= 0 AND b.datum >= ? AND b.datum < ?

UNION ALL

-- manual cash uitgaven
SELECT 'manual', NULL, u.id, u.datum, -ABS(u.bedrag),  -- always negative for uniform display
       '' AS tegenpartij, u.omschrijving, '' AS iban,
       u.categorie, COALESCE(u.pdf_pad, ''),
       u.is_investering, u.zakelijk_pct,
       NULL AS koppeling_type, NULL AS koppeling_id, 0 AS genegeerd
FROM uitgaven u
WHERE u.bank_tx_id IS NULL AND u.datum >= ? AND u.datum < ?
```

Date filter uses range form so `idx_banktransacties_datum` / `idx_uitgaven_datum` fire. Post-filters (`status`, `categorie`, `type`, `search`, `maand`) are Python-side — cheap at single-user scale.

`TransactieRow` dataclass (new):
```python
@dataclass
class TransactieRow:
    source: str              # 'bank_debit' | 'bank_credit' | 'manual'
    id_bank: int | None
    id_uitgave: int | None
    datum: str
    bedrag: float            # signed; + = income, − = cost
    tegenpartij: str
    omschrijving: str
    iban: str
    categorie: str
    pdf_pad: str
    is_investering: bool
    zakelijk_pct: int | None
    koppeling_type: str | None
    koppeling_id: int | None
    genegeerd: int
    status: str              # derived
    is_manual: bool
```

Status derivation (expand `derive_status`) — priority order:

1. `genegeerd=1` → `'prive_verborgen'`
2. `koppeling_type='factuur'` and `id_bank` present → `'gekoppeld_factuur'`
3. `bedrag < 0` and `id_uitgave is None` → `'ongecategoriseerd'`
4. `bedrag < 0` and not `categorie` → `'ongecategoriseerd'`
5. `bedrag < 0` and not `pdf_pad` → `'ontbreekt_bon'`
6. `bedrag < 0` → `'compleet'`
7. `bedrag >= 0` and not `categorie` and not `koppeling_type` → `'ongecategoriseerd'`
8. `bedrag >= 0` → `'gecategoriseerd'`

(Current `derive_status` is expanded, same module — becomes sign-aware. Existing tests updated.)

### 4.2 New: `get_kosten_breakdown`

```python
async def get_kosten_breakdown(db_path: Path, jaar: int) -> dict[str, float]:
    """Sum of ABS(bedrag) per categorie for debits + manual, excluding genegeerd."""
```

Lightweight SQL sum — does not materialise rows. Used by `/kosten` breakdown and "te verwerken" KPI (pass categorie=''/NULL totals).

### 4.3 New: `get_kosten_per_maand`

```python
async def get_kosten_per_maand(db_path: Path, jaar: int) -> list[float]:
    """12 slots (Jan=0 … Dec=11), ABS(bedrag) sum per maand."""
```

Reuses the same filter as the breakdown (debits + manual, exclude genegeerd). Already computed inside `get_kpi_kosten.monthly_totals` — thin wrapper that calls it or extracts the same query.

### 4.4 New: `get_terugkerende_kosten`

```python
async def get_terugkerende_kosten(
    db_path: Path,
    jaar: int,
    min_count: int = 3,
    window_days: int = 365,
) -> list[dict]:
    """Tegenpartij met >= min_count uitgaven in laatste window_days.

    Returns: [{'tegenpartij': str, 'count': int,
               'jaar_totaal': float, 'laatste_datum': str}]
    Sorted by jaar_totaal DESC.
    """
```

SQL: groupby on `LOWER(tegenpartij)` across bank-debits (join `banktransacties.tegenpartij` to linked uitgaven or use `banktransacties.tegenpartij` directly since debits are bank-sourced). Filter by `datum >= :jaar_start - window_days AND genegeerd=0`. Sum over the jaar-window (not the lookup window — the count threshold uses 365d, the total is year-specific).

### 4.4b New: `get_uitgave_by_id`

```python
async def get_uitgave_by_id(db_path: Path, uitgave_id: int) -> Uitgave | None:
    """Targeted fetch — replaces list-and-filter in the detail-dialog bootstrap (M5)."""
```

Thin wrapper around `SELECT * FROM uitgaven WHERE id = ?`. Returns `None` when not found. Used in `components/transacties_dialog.py` after `ensure_uitgave_for_banktx` returns an id.

### 4.5 Updated: `get_categorie_suggestions`

Current implementation only reads `banktransacties.categorie`. After migratie 27 debit-categorisations live in `uitgaven.categorie`, so debit suggestions are silently missing.

New implementation: UNION two sources:
1. Debits: `SELECT LOWER(b.tegenpartij), u.categorie, COUNT(*), MAX(b.datum) FROM uitgaven u JOIN banktransacties b ON u.bank_tx_id=b.id WHERE u.categorie != '' GROUP BY LOWER(b.tegenpartij), u.categorie`
2. Positives: current query on `banktransacties` (unchanged).

Merge into the same `{tegenpartij: categorie}` map (per-tegenpartij, highest count wins, tie-break `MAX(datum)`).

### 4.6 Deprecated: `get_kosten_view`

Callers after migration: only `/kosten` breakdown + KPI.
- Breakdown: switches to `get_kosten_breakdown` (cheaper)
- KPI: `get_kpi_kosten` already does its own query — no change, but it currently calls `get_kosten_view` internally. Keep that internal call on a renamed helper `_get_debits_and_manuals_for_jaar` if needed, or point KPI at `get_transacties_view(type='bank_debit+manual')`. Decision during implementation; spec allows either.

Once callers migrated, remove `get_kosten_view` and `KostenRow`.

### 4.7 Renames

| Old | New |
|---|---|
| `components/kosten_helpers.py` | `components/transacties_helpers.py` |
| `KostenRow` | `TransactieRow` |
| `KpiKosten` | (keep — it's about the `/kosten` overview which retains the name) |
| `derive_status(row) → 'hidden' / 'ongecategoriseerd' / 'ontbreekt' / 'compleet'` | expanded per §4.1 step 1-8; `'hidden'` becomes `'prive_verborgen'`, `'ontbreekt'` becomes `'ontbreekt_bon'`, added `'gekoppeld_factuur'` + `'gecategoriseerd'` |

## 5. File / code layout after

| File | Status | Approx lines |
|---|---|---|
| `pages/transacties.py` | **new** — inbox page, combines old `bank.py` + tabel/bulk/dialogs from `kosten.py` | ~1400-1500 |
| `components/transacties_dialog.py` | **new** — Detail/Factuur/Historie dialog extracted from kosten.py | ~600 |
| `components/transacties_helpers.py` | **rename** of `kosten_helpers.py`, status-values expanded | ~80 |
| `pages/kosten.py` | **shrink** — overzicht + activastaat-tab only | ~400 |
| `pages/kosten_investeringen.py` | **unchanged** | 264 |
| `pages/bank.py` | **redirect stub** → `/transacties` for one release, then deleted | ~10 |
| `components/layout.py` | sidebar "Bank" label → "Transacties"; route unchanged in data but label updated | +/- 0 |
| `database.py` | +4 functions, 1 updated, 1 deprecated | +~200 |
| `components/utils.py` | unchanged (`KOSTEN_CATEGORIEEN` + `BANK_CATEGORIEEN` stay; now feed per-row options in transacties slot) | 0 |

## 6. Migratie — phased, each phase a separate green-test PR

### Phase 1 — DB layer

1. Implement `get_transacties_view`, `get_kosten_breakdown`, `get_kosten_per_maand`, `get_terugkerende_kosten`.
2. Update `get_categorie_suggestions` (UNION with uitgaven-source).
3. Expand `derive_status` to cover the 8 cases in §4.1.
4. Add `TransactieRow` dataclass.
5. New tests (see §7). Existing tests pass untouched.
6. CI green → merge.

### Phase 2 — new `/transacties` page (coexists with old pages)

7. Create `pages/transacties.py` — combines CSV upload/delete/match (from old `bank.py`), category inline/bulk (from `kosten.py`), detail-dialog (extracted), cash-entry button, archief-import button. **+ M1**: add migratie 28 creating `CREATE UNIQUE INDEX idx_uitgaven_bank_tx_unique ON uitgaven(bank_tx_id) WHERE bank_tx_id IS NOT NULL`. Route Importeer auto-link through `ensure_uitgave_for_banktx` (removes the duplicate-link race at DB level).
8. Extract Detail-dialog to `components/transacties_dialog.py` so both the old `kosten.py` (during transition) and new `transacties.py` can use it. **+ M5**: add `get_uitgave_by_id(db, uitgave_id)` DB helper; dialog bootstrap re-reads by returned id instead of `get_uitgaven(jaar=…)` list-and-filter.
9. Register `@ui.page('/transacties')`.
10. Implement query-param handling: read `jaar/categorie/status/search` from request query on mount.
11. Smoke: full flow end-to-end on `/transacties`. Old `/bank` and `/kosten` untouched.
12. CI green → merge.

### Phase 3 — `/kosten` slimmed

13. Delete from `pages/kosten.py`: transacties-tabel, bulk-bar, add/edit/import/detail-dialogs, aandachtspunten-banner, status/categorie/search filters.
14. Keep: KPI-strip (clickable per §3.2), activastaat-tab.
15. Add: per-maand bar-chart, click-through on breakdown balken, terugkerende-kosten-kaart. **+ M7**: the `(nog te categoriseren)` bucket rendered as a separate card above the breakdown, muted styling, not clickable — so it doesn't visually dwarf real categories.
16. The "Te verwerken" KPI-card navigates to `/transacties?status=ongecategoriseerd&jaar=X`.
17. Existing kosten-page tests updated or removed where they tested the removed UI.
18. CI green → merge.

### Phase 4 — sidebar & redirect

19. `components/layout.py`: sidebar label "Bank" → "Transacties".
20. `pages/bank.py`: body becomes `ui.navigate.to('/transacties')` soft-redirect.
21. Update CLAUDE.md: rename "Kosten-pagina (reconciliatie)" section to "Transacties-pagina"; add shorter "Kosten-pagina (overzicht)" section.

### Phase 5 — cleanup

22. Rename `KostenRow` → `TransactieRow`, `kosten_helpers` → `transacties_helpers`; grep-and-fix call-sites.
23. Deprecate `get_kosten_view`; migrate remaining callers to `get_transacties_view` or `get_kosten_breakdown`.
24. After one release with `/bank` redirect: delete `pages/bank.py`.

### Phase 6 — docs & memory

25. Close `open_plans.md` entry "Kosten rework v1.1 polish items" — which items landed naturally here (see §9), which are dropped, which moved to a separate plan.
26. Add new memory entry: `project_transacties_consolidation.md` with the 2026-04-22 date, final shape.

## 7. Testing

### New tests

- **`tests/test_get_transacties_view.py`**
  - debits returned for year
  - positives returned for year
  - manual cash returned
  - genegeerd excluded by default, included with `include_genegeerd=True`
  - type filter (`'bank'` excludes manual; `'contant'` excludes bank)
  - status filter (`ongecategoriseerd`, `gekoppeld_factuur`, `compleet`)
  - maand filter
  - search in tegenpartij / omschrijving / bedrag
  - year-range hits the index (explain-query check optional)

- **`tests/test_get_terugkerende_kosten.py`**
  - <3 hits → not returned
  - ≥3 hits within 365d → returned with correct count + total
  - window boundary: hit on day 366 excluded
  - case-insensitive grouping
  - sorted by jaar_totaal DESC

- **`tests/test_get_kosten_breakdown.py`**
  - sum per categorie over debits + manual
  - genegeerd excluded
  - empty categorie rows bucketed as `''`

- **`tests/test_get_categorie_suggestions.py`** (new or expand existing)
  - debit suggestion returned after user categorised on /transacties (reads from uitgaven.categorie via join)
  - positive suggestion returned (existing path)
  - tie-break MAX(datum) still honoured
  - mixed debit + positive for same tegenpartij → highest overall count wins

- **`tests/test_derive_status.py`** (expand)
  - all 8 cases in §4.1
  - genegeerd precedence over everything
  - factuur-match precedence over categorie

### Updated tests

- `tests/test_kosten_helpers.py` → `tests/test_transacties_helpers.py` (rename, content otherwise unchanged + cases added).
- All callers of `KostenRow` / `get_kosten_view` in tests point to `TransactieRow` / `get_transacties_view`.

### Preserved tests

- `tests/test_year_locking.py` — unchanged (all mutations still pass through guarded DB functions).
- `tests/test_invoice_editability.py` — unchanged.
- Fiscal tests — unchanged.

### Manual QA script (end of Phase 3)

1. Open `/transacties`. Filter `status=ongecategoriseerd`. Pick a debit. Choose a categorie inline. Row turns amber (bon ontbreekt). Attach a bon via 📎 action. Row turns green.
2. From filter bar: pick `type=contant`. Click `+ Contante uitgave`, save one. It appears.
3. Import a CSV. Match dialog opens. Tick high-confidence, apply. Factuur status becomes betaald.
4. Navigate to `/kosten`. Click a categorie-balk. `/transacties` opens with that categorie filter applied. Rows all match.
5. On `/kosten` click "Te verwerken" KPI. `/transacties` opens with `status=ongecategoriseerd` filter.
6. On `/kosten` Investeringen-tab: activastaat renders unchanged.
7. Soft-redirect: manually open `/bank` → lands on `/transacties`.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `q-btn-dropdown` teleport trap (CLAUDE.md) | Use `q-select` with `@update:model-value` — same pattern as current kosten.py. No dropdowns in teleported menus. |
| `ARCHIVE_BASE` monkeypatch breakage (CLAUDE.md) | When moving archief-import code to `transacties.py`, keep `from components import archive_paths` then `archive_paths.ARCHIVE_BASE` pattern. |
| Year-lock regressions | All mutations still go through `set_banktx_categorie` / `update_uitgave` / `update_banktransactie` / `mark_banktx_genegeerd` / `ensure_uitgave_for_banktx`. `YearLockedError` surfaces in UI via existing `try/except + ui.notify` pattern. Tests in `test_year_locking.py` preserved. |
| `BANK_CATEGORIEEN` vs `KOSTEN_CATEGORIEEN` mismatch in unified table | Server-side: each row gets a `cat_options` list (debits+cash → `KOSTEN_CATEGORIEEN`; positives → `['Omzet','Prive','Belasting','AOV']`). Slot binds `:options="props.row.cat_options"`. |
| Large `pages/transacties.py` file | Detail-dialog extracted to `components/transacties_dialog.py`. Match-preview dialog kept in transacties.py (small). Archief-import dialog can be extracted later if page grows past 1500 lines. |
| Soft-redirect `/bank → /transacties` surprises users who bookmarked old URL | Keep redirect for one release (no time-bomb), then remove in Phase 5 cleanup. |

## 9. Reconciliation with open Kosten-rework v1.1 polish items

Per `open_plans.md` (Kosten rework 2026-04-21 final review), 7 polish items were staged. Decisions below — items marked **[LANDS]** are rolled into the relevant phase of this plan; **[SUBSUMED]** dissolve because the surrounding code disappears; **[DEFER]** are tracked separately.

| Item | Decision | Where |
|---|---|---|
| **M1** — close duplicate-link race (unique partial index on `uitgaven(bank_tx_id)` OR route Importeer through `ensure_uitgave_for_banktx`) | **[LANDS]** — Phase 2, as part of the archief-import code move. Prefer the unique partial index (migratie 28) because it's a DB-level guarantee rather than a code-convention one. | Phase 2, step 7 |
| **M2** — single-fetch `get_kosten_view` per `ververs_transacties` tick (currently 4×) | **[SUBSUMED]** — `/kosten` shrinks to overzicht-only, no transacties-tabel; its new render path calls `get_kpi_kosten` + `get_kosten_breakdown` + `get_kosten_per_maand` + `get_terugkerende_kosten` (four *different* queries, each scoped). The original 4× duplication pattern ceases to exist. `/transacties` refresh remains a single `get_transacties_view` call per tick. | — |
| **M3** — wire "Factuur ontbreekt" / "Te verwerken" KPI card click to filter | **[SUBSUMED]** — §3.2 specifies the "Te verwerken" card navigates to `/transacties?status=ongecategoriseerd&jaar=X`. The behaviour M3 wanted is now cross-page click-through, not in-page filter mutation. | §3.2 |
| **M4** — remove stale "Stub loaders — Tasks 10–14" comment | **[SUBSUMED]** — `pages/kosten.py` is rewritten in Phase 3; the comment will not survive the rewrite. | — |
| **M5** — after `ensure_uitgave_for_banktx` succeeds in `_open_detail_dialog`, re-read by returned id, not via `get_uitgaven(jaar=…)` list-and-filter | **[LANDS]** — Phase 2, when the detail dialog is extracted to `components/transacties_dialog.py`. Add a targeted `get_uitgave_by_id(db, uitgave_id)` helper to `database.py` and use it in the dialog's bootstrap path. | Phase 2, step 8 |
| **M7** — visually separate `(nog te categoriseren)` bucket in breakdown card | **[LANDS]** — Phase 3, as the breakdown is being rewritten for click-through anyway. Uncategorised bucket gets a separator + muted styling + is non-clickable (no filter to apply). | Phase 3, step 15 |
| **Lazy-create-cancel-orphan** — Detail dialog's pre-render `ensure_uitgave_for_banktx` leaves an empty uitgave if user clicks Annuleren without editing | **[DEFER]** — fix requires deferring lazy-create to first-mutation, a design-pattern change that touches the dialog's save-path. Preserved as-is in the extracted `components/transacties_dialog.py`. Staged for a follow-up after this consolidation merges. | — (new entry in `open_plans.md`) |

### Other follow-ups from `open_plans.md`

| Item | Decision |
|---|---|
| `jaar: int = 2026` hardcoded default audit across `database.py` | **[DEFER]** — orthogonal; time-bomb for 2027-01-01 but unrelated to consolidation. Stays in open_plans. |
| AANDACHTSPUNTEN hex → Quasar semantic colors | **[SUBSUMED]** — the aandachtspunten-banner on `/kosten` is removed in Phase 3. |
| `components/invoice_generator.py:8` still uses static `from components.archive_paths import ARCHIVE_BASE` | **[DEFER]** — orthogonal; only matters when `invoice_generator.py` gets test coverage. Stays in open_plans. |
| `docs/superpowers/plans/2026-04-14-database-package-refactor.md` (database.py split) | **[DEFER]** — explicitly not-now per open_plans.md. This consolidation adds ~200 lines to database.py; revisit the split pressure after. |

## 10. Success criteria

Measurable "done" definition:
1. Single decision screen: every routine money-movement action (categoriseren, bon koppelen, factuur matchen, privé, verwijderen, cash invoeren) can be completed without leaving `/transacties`.
2. `/kosten` contains zero form controls that mutate data — read-only overview only.
3. Every current `/bank`- and `/kosten`-tabel test flow still works end-to-end on `/transacties`.
4. Click-through from `/kosten` categorie-balken lands on `/transacties` with filter pre-applied.
5. Full test suite green (0 failures).
6. Manual QA script §7 all green.
7. CLAUDE.md updated; MEMORY.md updated.

## 11. Explicit non-asks (for the record)

- **No** schema migration *other than* the single-column-spanning unique partial index (migratie 28, §4.0) that M1 pulls in.
- **No** Rabobank API auto-feed.
- **No** rule-engine for auto-categorisation beyond the existing tegenpartij-suggestion.
- **No** split-transactions (one bank-tx → N uitgaven). Schema stays 1:0-or-1. Revisit later if real need emerges.
- **No** user-level preset / saved-filter system. URL query-params via click-through replace it.
- **No** "Omzet" category cleanup (positives can still be categorised as Omzet even when a factuur-match also exists). Deferred — orthogonal.
