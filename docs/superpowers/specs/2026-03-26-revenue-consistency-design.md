# Revenue Consistency & Vergoeding Type — Design Spec

## Problem

Dashboard "Bruto omzet" (from `facturen.totaal_bedrag`) and werkdagen page "Bedrag" (from `SUM(uren * tarief + km * km_tarief)`) show different numbers. For 2026: €30,729 vs €29,412 — a gap of €1,387.

Root causes:
1. **Ad-hoc facturen without werkdagen** — dienst-overname vergoedingen (2 in 2026, 6 in 2025, 11 total across all years = €6,452). These are legitimate revenue but not work days.
2. **Orphaned data in 2025** — 6 facturen without werkdagen + 7 werkdagen without factuurnummer that should be linked.
3. **Dashboard uren (292) vs werkdagen uren (344)** — dashboard correctly excludes achterwacht (urennorm=0) for urencriterium, but this isn't labeled.

## Design Decisions

- **Dagpraktijk and diensten (achterwacht/ANW) are both werkdagen** — they stay in the werkdagen table together.
- **Ad-hoc vergoedingen are NOT werkdagen** — they are facturen without werkdag backing.
- **Dashboard omzet stays facturen-based** — total revenue is total revenue, no split needed between werkdagen-omzet and overige omzet.
- **Vergoedingen are managed on the facturen page** — they ARE facturen. No new page or werkdagen tab needed.

## Changes

### 1. Datamodel: facturen.type = 'vergoeding'

**Current type values:** `'factuur'`, `'anw'`

**New value:** `'vergoeding'` — for facturen with zero linked werkdagen (pure free-form lines).

**Add CHECK constraint** on `facturen.type` for `('factuur', 'anw', 'vergoeding')` — consistent with existing CHECK pattern on werkdagen.

**Classification logic:**
- Factuur has ≥1 werkdag-backed line → `type='factuur'` (even if it also has free-form lines)
- Factuur has zero werkdag-backed lines → `type='vergoeding'`
- Imported ANW → `type='anw'` (unchanged, set by import flow)

A single factuur can combine werkdag lines + achterwacht lines + free-form vergoeding lines. The type reflects the *presence* of werkdagen, not the composition. Mixed facturen stay `type='factuur'`.

**Edge case — manual unlink:** If werkdagen are later unlinked from a factuur, the type is NOT automatically updated. This is a known limitation; given this is a single-user local app, the probability is near zero and re-derivation logic would be YAGNI.

**Migration order:** Linkage fix FIRST (step 5), then type classification. Otherwise 2025 facturen that should be `type='factuur'` (after linking) get incorrectly marked as `type='vergoeding'`.

**Migration:** Set `type='vergoeding'` on existing facturen that have no linked werkdagen AND are not type='anw'. Based on current data, this affects:
- 2026: 2026-007 (K. Klant15, €885.96), 2026-018 (M. de Vijlder, €501.44)
- 2025: Remaining orphans after linkage fix
- Other years: Remaining orphans after linkage fix

### 2. Auto-detection in invoice builder

In `components/invoice_builder.py`, when saving a factuur:

```python
has_werkdagen = any(li.get('werkdag_id') for li in line_items)
factuur_type = 'factuur' if has_werkdagen else 'vergoeding'
```

No user interaction needed. The builder already tracks which lines have `werkdag_id`.

### 3. Facturen page: visual distinction + type filter

**Icon per type** replaces current bron-based icons (nummer column slot). Type is more semantically meaningful than bron:
- `type='factuur'`: teal `edit` icon
- `type='anw'`: grey `upload` icon
- `type='vergoeding'`: amber `receipt_long` icon

**Type filter** added to the filter bar (next to existing klant + jaar filters):
- Options: `Alle | Werkdag | ANW/Dienst | Vergoeding`
- Filters on `facturen.type` field

**Edit dialog:** Type badge updated to handle all three values (`'Dagpraktijk'` / `'ANW'` / `'Vergoeding'`). Type is display-only (auto-derived), not user-editable — prevents contradiction with auto-detection.

**CSV export:** Add type column to export headers for auditability.

### 4. Dashboard uren label

Current: `292 uur`

New: `292 uur (urencriterium)` with tooltip: "Exclusief achterwacht (urennorm=0)"

This clarifies why the number differs from werkdagen page (344 uur, which includes achterwacht). No other dashboard changes.

### 5. Datafix: 2025 orphan linkage

**Problem:** 6 facturen in 2025 have no linked werkdagen, while 7 werkdagen in 2025 have no factuurnummer. These likely belong together.

**Approach:**
- Match by klant + datum + bedrag overlap
- Link werkdagen to their facturen via `factuurnummer` field
- After linking, re-evaluate which facturen remain orphans → those get `type='vergoeding'`

**Other years:** Inventory remaining orphans in 2023/2024 after the 2025 fix. Fix where possible, accept historical gaps where data is insufficient.

### 6. Validation at factuur creation

For werkdag-backed facturen (`type='factuur'`), warn if:
- `totaal_bedrag < SUM(werkdagen)` — suggests missing werkdagen or wrong tarieven

Do NOT warn if `totaal_bedrag > SUM(werkdagen)` — this is expected when a factuur has extra free-form lines alongside werkdagen.

This validation is a UI warning (notification), not a hard block.

### 7. Existing queries — verified compatibility

- **`get_openstaande_facturen`** (database.py:1697): Currently filters on `type='factuur'`, which would exclude unpaid vergoedingen. Fix: remove the type filter (status='verstuurd' is sufficient) or expand to include 'vergoeding'.
- **`find_factuur_matches`** (bank matching): Uses `status IN ('verstuurd', 'concept')` without type filter — works correctly for vergoedingen as-is, no change needed.
- **Jaarafsluiting orphan check** (jaarafsluiting.py:542): Filters `type='factuur'` — naturally correct after migration since vergoedingen are excluded. No change needed.

## Out of Scope

- **Old achterwacht tarieven (2023-2025):** Historical data with ANW pool rates (€7-€10/hr) instead of actual rates. Not fixable without original invoices. 2026+ uses correct rates.
- **Dashboard revenue split:** User decided total omzet is total omzet — no split between werkdagen and vergoedingen on dashboard.
- **Werkdagen page changes:** Stays focused on werkdagen, no overige inkomsten shown there.
- **New CRUD for vergoedingen:** Invoice builder already supports free-form facturen. No new creation flow needed.
- **Automatic type re-derivation:** If werkdagen are manually unlinked after factuur creation, type is not auto-updated. Near-zero probability for single-user app.

## CLAUDE.md Update

Add `'vergoeding'` to the facturen.type documentation in CLAUDE.md (currently only lists `'factuur'` implicitly).

## Files Affected

| File | Change |
|------|--------|
| `database.py` | Migration: (1) 2025 linkage fix, (2) CHECK constraint on type, (3) type='vergoeding' for remaining orphans, (4) fix `get_openstaande_facturen` type filter |
| `components/invoice_builder.py` | Auto-detect type based on werkdag_id presence |
| `pages/facturen.py` | Type-based icons (replace bron), type filter, edit dialog badge, CSV export type column |
| `pages/dashboard.py` | Uren label "(urencriterium)" + tooltip |
| `CLAUDE.md` | Document type='vergoeding' |

## Test Plan

- Verify facturen without werkdagen get `type='vergoeding'` after migration
- Verify invoice builder sets `type='vergoeding'` for free-form-only facturen
- Verify invoice builder sets `type='factuur'` for mixed (werkdag + free-form) facturen
- Verify facturen page filter works for all types
- Verify facturen page shows correct icon per type
- Verify facturen page edit dialog shows correct type badge for all three types
- Verify facturen CSV export includes type column
- Verify `get_openstaande_facturen` includes vergoedingen
- Verify dashboard uren label and tooltip updated
- Verify 2025 werkdagen correctly linked after datafix
- Verify existing tests still pass (no regressions)
