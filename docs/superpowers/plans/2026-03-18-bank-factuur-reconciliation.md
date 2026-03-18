# Bank-Factuur Reconciliation — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After bank CSV import, show a confirmation dialog with matched payments ↔ open facturen. User reviews and confirms before facturen are marked betaald.

**Architecture:** Split existing `match_betalingen_aan_facturen()` into `find_factuur_matches()` (read-only proposals) + `apply_factuur_matches()` (applies confirmed matches). Remove `auto_match_betaald_datum()`. Add confirmation dialog to bank page. Update jaarafsluiting to use new functions.

**Tech Stack:** Python 3.12+, aiosqlite, NiceGUI 3.8 (ui.dialog, ui.table, ui.checkbox)

**Spec:** `docs/superpowers/specs/2026-03-18-bank-factuur-reconciliation.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `database.py` | Modify (lines 1520-1710) | Replace 2 functions with `find_factuur_matches` + `apply_factuur_matches` |
| `pages/bank.py` | Modify (lines 11, 134-148) | Confirmation dialog after CSV import |
| `pages/jaarafsluiting.py` | Modify (lines 15, 44) | Switch from old to new matching functions |
| `tests/test_db_queries.py` | Modify (lines 4-13, 277-365, 453-534) | Replace tests for old functions with tests for new ones |

---

### Task 1: Write tests for `find_factuur_matches`

**Files:**
- Modify: `tests/test_db_queries.py`

- [ ] **Step 1: Remove old `match_betalingen_aan_facturen` tests and add new `find_factuur_matches` tests**

Replace the 4 tests at lines 453-534 (`test_match_betalingen_*`) with:

```python
# ============================================================
# find_factuur_matches + apply_factuur_matches
# ============================================================

@pytest.mark.asyncio
async def test_find_matches_by_nummer(db):
    """Pass 1: match by invoice number in bank omschrijving."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-001', klant_id=kid,
                       datum='2026-01-15', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, betaald=0)
    await add_banktransacties(db, [
        {'datum': '2026-01-20', 'bedrag': 640.00, 'tegenpartij': 'Test BV',
         'omschrijving': '2026-001 jan', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1
    assert matches[0]['factuur_nummer'] == '2026-001'
    assert matches[0]['bank_datum'] == '2026-01-20'
    assert matches[0]['match_type'] == 'nummer'

    # Verify NO changes applied yet (read-only)
    async with get_db_ctx(db) as conn:
        cur = await conn.execute('SELECT betaald FROM facturen WHERE nummer=?',
                                  ('2026-001',))
        assert (await cur.fetchone())['betaald'] == 0


@pytest.mark.asyncio
async def test_find_matches_by_amount(db):
    """Pass 2: match by amount when no nummer found in omschrijving."""
    kid = await add_klant(db, naam="Test", tarief_uur=77.50, retour_km=52)
    await add_factuur(db, nummer='2026-010', klant_id=kid,
                       datum='2026-02-10', totaal_uren=9, totaal_km=52,
                       totaal_bedrag=709.46, betaald=0)
    await add_banktransacties(db, [
        {'datum': '2026-02-15', 'bedrag': 709.46, 'tegenpartij': 'Klant',
         'omschrijving': 'betaling feb', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1
    assert matches[0]['factuur_nummer'] == '2026-010'
    assert matches[0]['match_type'] == 'bedrag'


@pytest.mark.asyncio
async def test_find_matches_skips_betaald(db):
    """Already-paid facturen are not matched."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-005', klant_id=kid,
                       datum='2026-03-01', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, betaald=1, betaald_datum='2026-03-05')
    await add_banktransacties(db, [
        {'datum': '2026-03-05', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': '2026-005', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 0


@pytest.mark.asyncio
async def test_find_matches_skips_linked_bank(db):
    """Bank transactions already linked are not reused."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-020', klant_id=kid,
                       datum='2026-03-10', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, betaald=0)
    await add_banktransacties(db, [
        {'datum': '2026-03-15', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': '2026-020', 'categorie': ''},
    ], csv_bestand='test.csv')
    # Pre-link the bank transaction
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "UPDATE banktransacties SET koppeling_type='factuur' WHERE bedrag=640")
        await conn.commit()

    matches = await find_factuur_matches(db)
    assert len(matches) == 0


@pytest.mark.asyncio
async def test_find_matches_same_amount_chronological(db):
    """Two facturen with same amount: first by date wins."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-A', klant_id=kid,
                       datum='2026-01-10', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, betaald=0)
    await add_factuur(db, nummer='2026-B', klant_id=kid,
                       datum='2026-01-20', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, betaald=0)
    await add_banktransacties(db, [
        {'datum': '2026-01-25', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1
    assert matches[0]['factuur_nummer'] == '2026-A'  # first by date


@pytest.mark.asyncio
async def test_find_matches_anw_nummer(db):
    """ANW factuurnummers with special format are matched correctly."""
    kid = await add_klant(db, naam="ANW Diensten", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='22470-26-27', klant_id=kid,
                       datum='2026-01-10', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, betaald=0)
    await add_banktransacties(db, [
        {'datum': '2026-01-20', 'bedrag': 640.00, 'tegenpartij': 'ANW',
         'omschrijving': 'Betaling 22470-26-27', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1
    assert matches[0]['match_type'] == 'nummer'


@pytest.mark.asyncio
async def test_find_matches_amount_outside_tolerance(db):
    """Amount difference > EUR 1 → no match."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2026-X', klant_id=kid,
                       datum='2026-02-01', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, betaald=0)
    await add_banktransacties(db, [
        {'datum': '2026-02-10', 'bedrag': 650.00, 'tegenpartij': 'Test',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 0


@pytest.mark.asyncio
async def test_find_matches_empty_db(db):
    """No facturen, no bank transactions → empty list."""
    matches = await find_factuur_matches(db)
    assert matches == []


@pytest.mark.asyncio
async def test_apply_matches(db):
    """apply_factuur_matches marks factuur betaald and links bank transaction."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    fid = await add_factuur(db, nummer='2026-030', klant_id=kid,
                             datum='2026-03-01', totaal_uren=8, totaal_km=0,
                             totaal_bedrag=640.00, betaald=0)
    await add_werkdag(db, datum='2026-03-01', klant_id=kid,
                       uren=8, tarief=80, km=0, km_tarief=0.23,
                       status='gefactureerd', factuurnummer='2026-030')
    await add_banktransacties(db, [
        {'datum': '2026-03-10', 'bedrag': 640.00, 'tegenpartij': 'Test',
         'omschrijving': '2026-030', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1

    count = await apply_factuur_matches(db, matches)
    assert count == 1

    # Verify factuur is betaald
    async with get_db_ctx(db) as conn:
        cur = await conn.execute('SELECT betaald, betaald_datum FROM facturen WHERE id=?', (fid,))
        row = await cur.fetchone()
        assert row['betaald'] == 1
        assert row['betaald_datum'] == '2026-03-10'

        # Verify bank transaction linked
        cur = await conn.execute(
            "SELECT koppeling_type, koppeling_id FROM banktransacties WHERE bedrag=640")
        row = await cur.fetchone()
        assert row['koppeling_type'] == 'factuur'
        assert row['koppeling_id'] == fid

        # Verify werkdag status updated
        cur = await conn.execute(
            "SELECT status FROM werkdagen WHERE factuurnummer='2026-030'")
        row = await cur.fetchone()
        assert row['status'] == 'betaald'


@pytest.mark.asyncio
async def test_apply_matches_empty(db):
    """Empty match list → no changes, returns 0."""
    count = await apply_factuur_matches(db, [])
    assert count == 0
```

Also update the imports at the top (lines 4-13) to replace `match_betalingen_aan_facturen` with `find_factuur_matches, apply_factuur_matches`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py -k "find_matches or apply_matches" -v`
Expected: FAIL with ImportError (functions don't exist yet)

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_db_queries.py
git commit -m "test: add failing tests for find_factuur_matches + apply_factuur_matches"
```

---

### Task 2: Implement `find_factuur_matches` and `apply_factuur_matches`

**Files:**
- Modify: `database.py` (lines 1520-1710)

- [ ] **Step 1: Replace `match_betalingen_aan_facturen` with `find_factuur_matches` + `apply_factuur_matches`**

Remove `match_betalingen_aan_facturen` (lines 1520-1627) and replace with two new functions. Key differences from the removed function:
- `find_factuur_matches`: returns proposals WITHOUT applying. Pass 1 uses EUR 1 tolerance (not 5%). Adds `match_type` field.
- `apply_factuur_matches`: takes a list of match dicts, applies them. Uses `factuur_nummer` from dict directly for werkdagen update (no extra query).

Also remove `auto_match_betaald_datum` (lines 1629-1710).

- [ ] **Step 2: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py -k "find_matches or apply_matches" -v`
Expected: All 9 tests PASS

- [ ] **Step 3: Run full test suite to check for regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q`
Expected: Some failures in old `test_auto_match_*` tests (they reference removed functions). Fix imports in tests that reference `auto_match_betaald_datum` — remove those 5 tests (lines 277-365) since the function they test no longer exists.

- [ ] **Step 4: Run full suite again — all pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q`
Expected: All pass, 0 failures

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_db_queries.py
git commit -m "feat: split match_betalingen into find + apply, remove auto_match_betaald_datum"
```

---

### Task 3: Add confirmation dialog to bank page

**Files:**
- Modify: `pages/bank.py` (lines 11, 134-148)

- [ ] **Step 1: Update imports**

Replace `match_betalingen_aan_facturen` with `find_factuur_matches, apply_factuur_matches` in the import block (line 11). Also add `get_db_ctx` for querying remaining open facturen.

- [ ] **Step 2: Replace auto-apply with confirmation dialog**

Replace the current post-import matching code (lines 134-148) with:
1. Call `find_factuur_matches(DB_PATH)` to get proposals
2. Query remaining open facturen not in proposals
3. If proposals or open facturen exist, show `ui.dialog`:
   - Matches section: table with checkboxes (pre-checked)
   - Open facturen section: informational list
   - "Bevestig" button: apply checked matches, close dialog, refresh, notify
   - "Annuleren" button: close without applying
4. If nothing to show, just show the import count notification

The dialog should use `ui.table` for the matches (columns: Factuur, Bedrag, Tegenpartij, Bankdatum) and a simple list for open facturen. Use `format_euro` for amounts.

- [ ] **Step 3: Verify module imports cleanly**

Run: `.venv/bin/python -c "import pages.bank; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add pages/bank.py
git commit -m "feat: bank import shows confirmation dialog for matched payments"
```

---

### Task 4: Update jaarafsluiting to use new functions

**Files:**
- Modify: `pages/jaarafsluiting.py` (lines 15, 44)

- [ ] **Step 1: Update import**

Line 15: Replace `auto_match_betaald_datum` with `find_factuur_matches, apply_factuur_matches`.

- [ ] **Step 2: Update the call site**

Line 44: Replace:
```python
await auto_match_betaald_datum(DB_PATH)
```
with:
```python
matches = await find_factuur_matches(DB_PATH)
if matches:
    await apply_factuur_matches(DB_PATH, matches)
```

- [ ] **Step 3: Verify module imports cleanly**

Run: `.venv/bin/python -c "import pages.jaarafsluiting; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add pages/jaarafsluiting.py
git commit -m "fix: jaarafsluiting uses new find+apply matching functions"
```

---

### Task 5: Full verification

- [ ] **Step 1: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass, 0 failures

- [ ] **Step 2: Verify all modules import**

```bash
.venv/bin/python -c "
import pages.dashboard, pages.bank, pages.jaarafsluiting
import pages.facturen, pages.werkdagen, pages.kosten
import pages.aangifte, pages.documenten, pages.klanten
import pages.instellingen, database
print('All modules import successfully')
"
```

- [ ] **Step 3: Verify no references to removed functions remain**

```bash
grep -rn "auto_match_betaald_datum\|match_betalingen_aan_facturen" --include="*.py" . | grep -v __pycache__ | grep -v docs/
```
Expected: No results (all references removed)

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: verify bank-factuur reconciliation complete, all tests pass"
```
