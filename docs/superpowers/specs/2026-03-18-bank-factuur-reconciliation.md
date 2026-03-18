# Bank-Factuur Reconciliation — Design Spec

## Problem

When a bank CSV is imported, the app currently auto-applies matches silently (via `match_betalingen_aan_facturen`) with only a notification. The user cannot review or reject matches before they are applied. There is also an older `auto_match_betaald_datum` function used by jaarafsluiting that serves a different purpose (backfilling dates for manually-marked-paid facturen).

## Solution

Split the existing `match_betalingen_aan_facturen()` into find + apply. After CSV import, show a confirmation panel with match proposals. The user reviews and confirms before any data changes. Replace the older `auto_match_betaald_datum` entirely.

## User Flow

```
1. Create factuur from werkdagen → factuur starts as ONBETAALD (betaald=0)
2. Import bank CSV on Bank page
3. App finds matching payments (by invoice number + amount)
4. Confirmation dialog shows matches: factuur nummer, bedrag, tegenpartij, bank datum
5. User clicks "Bevestig alle" (or unchecks individual matches)
6. Confirmed: facturen → betaald=1, bank transactions → linked, werkdagen → 'betaald'
7. Rejected/cancelled: no changes
```

## Technical Design

### database.py Changes

**Remove:** `match_betalingen_aan_facturen()` (line 1520) — replaced by split below.
**Remove:** `auto_match_betaald_datum()` (line 1629) — absorbed into new function.

**Add:** Two new functions:

#### `find_factuur_matches(db_path) -> list[dict]`

Returns match proposals WITHOUT applying them. Scope: facturen with `betaald=0`.

Each match dict:
```python
{
    'factuur_id': int,
    'factuur_nummer': str,
    'factuur_bedrag': float,
    'factuur_datum': str,
    'bank_id': int,
    'bank_datum': str,
    'bank_bedrag': float,
    'bank_tegenpartij': str,
    'match_type': 'nummer' | 'bedrag',
}
```

Algorithm (same two passes as existing code):
- **Pass 1 (nummer)**: Factuurnummer (lowercased) found as substring in bank omschrijving. Amount within 5%.
- **Pass 2 (bedrag)**: Amount within EUR 1 tolerance. Bank date >= factuur date - 14 days.
- Only incoming payments (`bedrag > 0`) with empty `koppeling_type`.
- Each bank transaction used at most once (greedy, chronological).

#### `apply_factuur_matches(db_path, matches: list[dict]) -> int`

Applies confirmed matches. For each match:
1. `UPDATE facturen SET betaald=1, betaald_datum=? WHERE id=?`
2. `UPDATE banktransacties SET koppeling_type='factuur', koppeling_id=? WHERE id=?`
3. `UPDATE werkdagen SET status='betaald' WHERE factuurnummer=?` (using `factuur_nummer` from match dict directly — no extra query)

Returns count of applied matches.

### pages/bank.py Changes

**Current** (line 139): Calls `match_betalingen_aan_facturen` which auto-applies.

**New**: After `add_banktransacties()` in `handle_upload()`:
1. Call `find_factuur_matches(DB_PATH)`
2. If no matches: continue as before (just show import count)
3. If matches found: open a `ui.dialog` with:
   - Title: "X betalingen gevonden voor open facturen"
   - Table with columns: Factuur, Bedrag, Tegenpartij, Bankdatum, Type
   - Each row has a checkbox (pre-checked)
   - "Bevestig" button: calls `apply_factuur_matches` with checked items, closes dialog, refreshes table, shows notification
   - "Annuleren" button: closes dialog without applying

**Update import**: Replace `match_betalingen_aan_facturen` with `find_factuur_matches, apply_factuur_matches`.

### pages/jaarafsluiting.py Changes

Replace `auto_match_betaald_datum()` call with:
```python
matches = await find_factuur_matches(DB_PATH)
if matches:
    await apply_factuur_matches(DB_PATH, matches)
```

Jaarafsluiting auto-confirms all matches (year-end cleanup, no user interaction needed).

**Update import**: Replace `auto_match_betaald_datum` with `find_factuur_matches, apply_factuur_matches`.

### Edge Cases

| Case | Behavior |
|------|----------|
| Two facturen same amount | First by datum wins (chronological) |
| ANW factuurnummers ("22470-26-27") | Matched by substring search |
| Partial payment | NOT matched (practices always pay in full) |
| Already betaald (betaald=1 with datum) | Skipped |
| Already linked bank txn | Skipped |
| Refund (negative amount) | Skipped |
| Amount difference > tolerance | Not matched |
| No open facturen | Empty list, no dialog shown |

## Testing Strategy

**Adapt** existing 4 tests in `tests/test_db_queries.py` (lines 449-534) for `match_betalingen_aan_facturen` → split into tests for `find_factuur_matches` and `apply_factuur_matches`.

**Remove** tests for `auto_match_betaald_datum` if they exist separately.

Tests for `find_factuur_matches`:
1. Match by nummer in omschrijving → returns proposal with match_type='nummer'
2. Match by amount → returns proposal with match_type='bedrag'
3. Skip already-betaald facturen → empty list
4. Skip already-linked bank transactions → empty list
5. Two facturen same amount → first by date wins
6. ANW nummer format → matched correctly
7. Amount outside tolerance → no match
8. Empty DB → empty list

Tests for `apply_factuur_matches`:
1. Factuur marked betaald with correct datum
2. Bank transaction linked with koppeling_type/id
3. Werkdagen status updated to 'betaald'
4. Empty list → no changes, returns 0

## Not In Scope

- Expense-bank linking (separate project)
- Recurring transaction rules
- Bank API / PSD2 integration
- Reconciliation view outside of CSV import flow
