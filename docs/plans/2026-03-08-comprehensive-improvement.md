# Comprehensive Improvement Plan — Roberg Boekhouding

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all known bugs, verify fiscal data, improve expense workflow, add fiscal advisory intelligence, and harden reliability — progressing from quick wins to high-value features.

**Architecture:** Progressive improvement using Approach B (interleaved value delivery). Each phase delivers visible value while cleaning up architecture in touched areas. TDD for all data/logic changes. Existing NiceGUI patterns preserved (dialog-based forms, `ui.table`, Quasar colors).

**Tech Stack:** NiceGUI 3.8+, SQLite (aiosqlite), Python 3.12+, WeasyPrint, pytest-asyncio

**Data source for expenses:** `/Users/macbookpro_test/Library/CloudStorage/SynologyDrive-Main/02_Financieel/Boekhouding_Waarneming/{year}/Uitgaven/` — 458 PDFs organized by year + category. Amounts are NOT parseable from PDFs — user enters values manually via upload dialog.

---

## Phase 1: Critical Fixes & Cleanup

### Task 1.1: Fix 2026 Seed Data (Box 3)

**Files:**
- Modify: `import_/seed_data.py:45,153-186`
- Modify: `tests/test_seed.py`
- Modify: `database.py` (add migration for existing DBs)

**Context:** Box 3 heffingsvrij_vermogen is 57684 (copied from 2025) but should be 59357. Drempel_schulden is 3700 but should be 3800. Source: [Belastingdienst Box 3 2026](https://www.belastingdienst.nl/wps/wcm/connect/nl/box-3/content/berekening-box-3-inkomen-2026).

**Step 1: Write failing test**

```python
# In tests/test_seed.py — add after test_seed_drempel_schulden
@pytest.mark.asyncio
async def test_seed_2026_box3_values(db):
    await seed_fiscale_params(db)
    fp = await get_fiscale_params(db, jaar=2026)
    assert fp.box3_heffingsvrij_vermogen == 59357
    assert fp.box3_drempel_schulden == 3800
    # Rendement percentages (voorlopig per BD, will update when definitief)
    assert fp.box3_rendement_bank_pct == pytest.approx(1.28)
    assert fp.box3_rendement_overig_pct == pytest.approx(6.00)
    assert fp.box3_rendement_schuld_pct == pytest.approx(2.70)
    assert fp.box3_tarief_pct == 36
```

**Step 2: Run test, verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_seed.py::test_seed_2026_box3_values -v`
Expected: FAIL on `assert fp.box3_heffingsvrij_vermogen == 59357` (currently 57684)

**Step 3: Fix seed_data.py**

In `import_/seed_data.py`, line 45 (BOX3_DEFAULTS):
```python
# Change:
2026: {'heffingsvrij': 57684, 'bank': 1.28, 'overig': 6.00, 'schuld': 2.70, 'tarief': 36, 'drempel_schulden': 3700},
# To:
2026: {'heffingsvrij': 59357, 'bank': 1.28, 'overig': 6.00, 'schuld': 2.70, 'tarief': 36, 'drempel_schulden': 3800},
```

In `import_/seed_data.py`, FISCALE_PARAMS 2026 section (lines 153-186):
```python
# Change:
'box3_heffingsvrij_vermogen': 57684,
'box3_drempel_schulden': 3700,
# To:
'box3_heffingsvrij_vermogen': 59357,
'box3_drempel_schulden': 3800,
```

**Step 4: Add DB migration for existing databases**

In `database.py` `init_db()`, add a data migration after existing migrations:
```python
# Fix 2026 Box 3 heffingsvrij + drempel (was copied from 2025, now corrected)
await conn.execute("""
    UPDATE fiscale_params
    SET box3_heffingsvrij_vermogen = 59357, box3_drempel_schulden = 3800
    WHERE jaar = 2026 AND box3_heffingsvrij_vermogen = 57684
""")
```

**Step 5: Run test, verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_seed.py -v`
Expected: ALL PASS

**Step 6: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All 284+ tests pass

**Step 7: Commit**

```bash
git add import_/seed_data.py database.py tests/test_seed.py
git commit -m "fix: correct 2026 Box 3 heffingsvrij (59357) and drempel schulden (3800)"
```

---

### Task 1.2: Fix .mcp.json DB Path

**Files:**
- Modify: `.mcp.json`

**Step 1: Fix the path**

Change `boekhouding.db` to `boekhouding.sqlite3`:
```json
{
  "mcpServers": {
    "sqlite": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "mcp-server-sqlite",
        "--db-path",
        "/Users/macbookpro_test/Library/CloudStorage/SynologyDrive-Main/06_Development/roberg-boekhouding/data/boekhouding.sqlite3"
      ],
      "env": {}
    }
  }
}
```

**Step 2: Commit**

```bash
git add .mcp.json
git commit -m "fix: point .mcp.json to correct SQLite database file"
```

---

### Task 1.3: Fix delete_klant UI Error Handling

**Files:**
- Modify: `pages/instellingen.py:310-314`

**Step 1: Wrap in try/except**

At `pages/instellingen.py` line 310, change:
```python
# FROM:
async def confirm_del(kid=row['id'], dlg=dialog):
    await delete_klant(DB_PATH, klant_id=kid)
    dlg.close()
    ui.notify(f"Klant verwijderd", type='positive')
    await refresh_klanten()

# TO:
async def confirm_del(kid=row['id'], dlg=dialog):
    try:
        await delete_klant(DB_PATH, klant_id=kid)
        dlg.close()
        ui.notify('Klant verwijderd', type='positive')
        await refresh_klanten()
    except ValueError as e:
        ui.notify(str(e), type='negative')
```

**Step 2: Commit**

```bash
git add pages/instellingen.py
git commit -m "fix: catch FK violation when deleting klant with linked werkdagen"
```

---

### Task 1.4: Fix Bank CSV Per-Transaction Dedup

**Files:**
- Modify: `database.py:841-860` (add_banktransacties)
- Modify: `tests/test_bank_import.py`

**Step 1: Write failing test**

```python
# In tests/test_bank_import.py
@pytest.mark.asyncio
async def test_duplicate_transactions_rejected(db):
    """Same transaction (datum+bedrag+tegenpartij+omschrijving) should not be inserted twice."""
    transactions = [
        {'datum': '2024-01-15', 'bedrag': -50.00,
         'tegenrekening': 'NL91ABNA0417164300', 'tegenpartij': 'KPN',
         'omschrijving': 'Factuur januari'},
    ]
    count1 = await add_banktransacties(db, transacties=transactions, csv_bestand='file1.csv')
    assert count1 == 1

    # Same transaction from different CSV → should be skipped
    count2 = await add_banktransacties(db, transacties=transactions, csv_bestand='file2.csv')
    assert count2 == 0

    all_trans = await get_banktransacties(db, jaar=2024)
    assert len(all_trans) == 1
```

**Step 2: Run test, verify it fails**

Expected: FAIL — count2 == 1 (currently no dedup)

**Step 3: Implement dedup in add_banktransacties**

In `database.py`, modify `add_banktransacties()`:
```python
async def add_banktransacties(db_path: Path = DB_PATH,
                               transacties: list[dict] = None,
                               csv_bestand: str = '') -> int:
    """Insert batch of bank transactions. Dedup by datum+bedrag+tegenpartij+omschrijving."""
    conn = await get_db(db_path)
    try:
        count = 0
        for t in (transacties or []):
            # Check for duplicate (same datum, bedrag, tegenpartij, omschrijving)
            cur = await conn.execute(
                """SELECT COUNT(*) FROM banktransacties
                   WHERE datum = ? AND bedrag = ? AND tegenpartij = ? AND omschrijving = ?""",
                (t['datum'], t['bedrag'], t.get('tegenpartij', ''), t.get('omschrijving', ''))
            )
            if (await cur.fetchone())[0] > 0:
                continue  # Skip duplicate
            await conn.execute(
                """INSERT INTO banktransacties
                   (datum, bedrag, tegenrekening, tegenpartij, omschrijving, csv_bestand)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (t['datum'], t['bedrag'], t.get('tegenrekening', ''),
                 t.get('tegenpartij', ''), t.get('omschrijving', ''), csv_bestand)
            )
            count += 1
        await conn.commit()
        return count
    finally:
        await conn.close()
```

**Step 4: Run test, verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_bank_import.py -v`
Expected: ALL PASS

**Step 5: Run full test suite**

Expected: All tests pass (existing tests should still work — unique transactions are still inserted)

**Step 6: Commit**

```bash
git add database.py tests/test_bank_import.py
git commit -m "fix: add per-transaction dedup for bank CSV import"
```

---

### Task 1.5: Add SQLite Performance Pragmas

**Files:**
- Modify: `database.py:163-169` (get_db)

**Step 1: Add pragmas**

```python
async def get_db(db_path: Path = DB_PATH) -> aiosqlite.Connection:
    """Get a database connection with WAL mode, FK enforcement, and performance pragmas."""
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA synchronous = NORMAL")
    await conn.execute("PRAGMA cache_size = 10000")
    await conn.execute("PRAGMA temp_store = MEMORY")
    conn.row_factory = aiosqlite.Row
    return conn
```

**Step 2: Run full test suite to verify no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add database.py
git commit -m "perf: add SQLite performance pragmas (synchronous, cache_size, temp_store)"
```

---

### Task 1.6: Add Error Boundaries to All Pages

**Files:**
- Modify: `main.py` (add global exception handler)

**Step 1: Add global on_exception handler in main.py**

```python
from nicegui import app, ui

# Add before ui.run():
app.on_exception(lambda e: ui.notify(
    f'Er is een fout opgetreden: {e}', type='negative', timeout=10000
))
```

This catches unhandled exceptions across all pages and shows a user-friendly notification instead of silently failing.

**Step 2: Test manually** — Start app, verify it loads

**Step 3: Commit**

```bash
git add main.py
git commit -m "fix: add global error boundary for unhandled exceptions"
```

---

### Task 1.7: Remove Dead Code & Unused Dependencies

**Files:**
- Delete: `import_/run_full_import.py` (if confirmed unused — check git log)
- Modify: `requirements.txt` (remove openpyxl, httpx if unused)

**Step 1: Verify run_full_import.py is unused**

```bash
grep -r "run_full_import" --include="*.py" .
```

If only self-references → safe to delete.

**Step 2: Verify openpyxl/httpx are unused**

```bash
grep -r "import openpyxl\|import httpx\|from openpyxl\|from httpx" --include="*.py" .
```

If no references → remove from requirements.txt.

**Step 3: Clean up and commit**

```bash
git add -u
git commit -m "chore: remove unused imports and dead code"
```

---

## Phase 2: Expense System Improvements

### Task 2.1: Expense Bulk Import Workflow — Browse & Upload from Archive

**Files:**
- Modify: `pages/kosten.py` (add "Importeer uitgaven" button + dialog)
- Docs: Check `components/utils.py` for KOSTEN_CATEGORIEEN mapping

**Goal:** Add a dialog that lets the user:
1. Select a year (scans `Boekhouding_Waarneming/{year}/Uitgaven/`)
2. Shows all PDFs organized by category folder
3. User selects one or more PDFs → opens add dialog per PDF with:
   - Date pre-filled from filename (MMDD pattern → full date with year)
   - Category pre-filled from folder name → mapped to KOSTEN_CATEGORIEEN
   - PDF auto-attached
   - User enters: omschrijving, bedrag, investering fields

**Category mapping** (folder → DB category):
```python
FOLDER_TO_CATEGORIE = {
    'Accountancy': 'Accountancy/software',
    'Pensioenpremie': 'Pensioenpremie SPH',
    'Verzekeringen': 'Verzekeringen',
    'KPN': 'Telefoon/KPN',
    'Kleine_Aankopen': 'Kleine aankopen',
    'Lidmaatschappen': 'Lidmaatschappen',
    'Investeringen': 'Investeringen',
    'Representatie': 'Representatie',
    'Scholingskosten': 'Scholingskosten',
    'Software': 'Accountancy/software',
    'AoV': 'Verzekeringen',
}
```

**Date extraction from filename:**
```python
import re
def extract_date_from_filename(filename: str, year: int) -> str | None:
    """Try to extract date from filename patterns like MMDD_... or YYYYMM_..."""
    m = re.match(r'^(\d{4})(\d{2})_', filename)  # YYYYMM pattern
    if m:
        return f'{m.group(1)}-{m.group(2)}-01'
    m = re.match(r'^(\d{2})(\d{2})_', filename)  # MMDD pattern
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f'{year}-{month:02d}-{day:02d}'
    return None
```

**Implementation approach:**
1. "Importeer uitgaven" button on kosten page header
2. Opens dialog showing archive folder tree for selected year
3. Each PDF shows: filename, pre-parsed date, mapped category, [already imported] badge
4. "Already imported" detection: match by filename pattern in existing uitgaven pdf_pad
5. User clicks a PDF → opens existing add dialog, pre-filled with date/category/PDF attached
6. After save, mark that PDF as imported in the list
7. "Opslaan & Volgende" automatically advances to next unimported PDF

**Archive path:** `/Users/macbookpro_test/Library/CloudStorage/SynologyDrive-Main/02_Financieel/Boekhouding_Waarneming/`

**Tests:**
- Test `extract_date_from_filename()` with MMDD, YYYYMM, and unparseable names
- Test `FOLDER_TO_CATEGORIE` mapping completeness
- Test dedup detection (already imported = skip)

---

### Task 2.2: Expense Add Dialog Improvements

**Files:**
- Modify: `pages/kosten.py` (add dialog improvements)

**Improvements to existing add dialog:**
1. **Try/catch around save** — wrap `opslaan()` in try/except to show DB errors
2. **Duplicate warning** — before save, check if same date+categorie+bedrag exists → warn
3. **Pre-fill support** — accept optional `prefill` dict param in `open_add_uitgave_dialog()`
   - `prefill.datum`, `prefill.categorie`, `prefill.pdf_path` (auto-attach without upload)
4. **"Opslaan & Volgende" callback** — optional `on_next` callback for batch workflow

---

### Task 2.3: Expense Category Alignment

**Files:**
- Modify: `components/utils.py` (verify KOSTEN_CATEGORIEEN covers all archive folders)

**Check:** Compare KOSTEN_CATEGORIEEN with archive folder names:
- Archive: Accountancy, Pensioenpremie, Verzekeringen, KPN, Kleine_Aankopen, Lidmaatschappen, Investeringen, Representatie, Scholingskosten, Software, AoV
- DB: Pensioenpremie SPH, Telefoon/KPN, Verzekeringen, Accountancy/software, Representatie, Lidmaatschappen, Kleine aankopen, Scholingskosten, Bankkosten, Investeringen

**Missing mapping:** "AoV" (archive) → needs decision: is this "Verzekeringen" or a new category?
- **Decision:** AOV is NOT a business expense (reduces verzamelinkomen instead). The archive folder "AoV" contains AOV receipts for reference, but these should NOT be imported as uitgaven. They're tracked separately as `aov_premie` in `fiscale_params`.

---

## Phase 3: Fiscal Advisory Panel

### Task 3.1: Advisory Data Calculations

**Files:**
- Create: `fiscal/advisory.py`
- Test: `tests/test_advisory.py`

**Functions to implement:**

```python
def za_trajectory(current_year: int) -> list[dict]:
    """Show ZA decline: 2023(5030) → 2024(3750) → 2025(2470) → 2026(1200) → 2027(900)."""

def sa_usage(sa_years: list[int], start_year: int) -> dict:
    """Track SA usage: max 3 in first 5 years. Returns used/remaining/deadline."""

def kia_check(total_investments: float, kia_ondergrens: float, kia_bovengrens: float) -> dict:
    """Validate KIA eligibility + warn if approaching bracket boundary."""

def belastingdruk(resultaat: FiscaalResultaat) -> dict:
    """Calculate effective/marginal tax rates from fiscal result."""

def va_check(netto_ib: float, va_betaald: float, zvw: float, va_zvw: float) -> dict:
    """Compare voorlopige aanslag vs actual → over/underpaying indicator."""

def lijfrente_jaarruimte(winst: float, aov: float, pensioen_opbouw: float = 0) -> float:
    """Calculate max deductible lijfrente premium (jaarruimte formula)."""
```

**Tests:** Each function gets TDD tests with known inputs/outputs.

---

### Task 3.2: Advisory Panel UI

**Files:**
- Modify: `pages/aangifte.py` (add "Advies" tab as 6th tab)

**Design:** New tab in aangifte invulhulp showing:
1. **ZA Trajectory** — Timeline card showing declining ZA with impact on belastbare winst
2. **SA Counter** — "Gebruikt: 2/3 in eerste 5 jaar" with visual progress
3. **Belastingdruk** — Effective rate gauge, marginal rate, YoY comparison
4. **VA Check** — "Voorlopige aanslag te hoog/laag met €X" alert
5. **Lijfrente Hint** — "Je mag nog €X aftrekken als lijfrente (jaarruimte)"

**Pattern:** Read-only advisory cards (no inputs), refreshed when year changes.

---

### Task 3.3: Split aangifte.py into Sub-modules

**Files:**
- Create: `pages/aangifte/` directory
- Move tab render functions to separate files: `winst.py`, `prive.py`, `box3.py`, `overzicht.py`, `documenten.py`, `advies.py`
- Keep: `pages/aangifte.py` as router that imports and composes tabs

**Goal:** Reduce 986-line monolith to ~150-line router + 6 focused tab modules.

---

## Phase 4: Reliability & Auto-Matching

### Task 4.1: Auto-Match Bank Transactions to Facturen

**Files:**
- Create: `components/bank_matching.py`
- Modify: `pages/bank.py` (add "Auto-match" button)
- Test: `tests/test_bank_matching.py`

**Matching rules:**
1. **Amount match** — transaction bedrag matches factuur totaal_bedrag (within €0.01)
2. **Date proximity** — transaction within 30 days of factuur datum
3. **Tegenpartij hint** — if tegenpartij contains klant naam substring
4. **Priority:** amount + name > amount + date > amount only
5. **User confirms** — show proposed matches, user accepts/rejects each

---

### Task 4.2: Atomic Transactions for Imports

**Files:**
- Modify: `database.py` (wrap multi-step operations in explicit transactions)

**Pattern:** Use `async with conn.execute("BEGIN")` + `conn.commit()` / `conn.rollback()` for:
- `add_banktransacties()` — already batch, add rollback on error
- PDF import pipeline (factuur + werkdagen creation)

---

### Task 4.3: Automated SQLite Backup

**Files:**
- Create: `components/backup.py`
- Modify: `main.py` (run backup on startup)

**Implementation:**
```python
async def create_backup(db_path: Path) -> Path:
    """Create timestamped backup, keep last 7."""
    backup_dir = db_path.parent / 'backups'
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = backup_dir / f'boekhouding_{timestamp}.sqlite3'
    shutil.copy2(db_path, backup_path)
    # Rotate: keep only last 7 backups
    backups = sorted(backup_dir.glob('boekhouding_*.sqlite3'))
    for old in backups[:-7]:
        old.unlink()
    return backup_path
```

---

### Task 4.4: Audit Trail for Fiscal Params

**Files:**
- Modify: `database.py` (add `fiscale_params_log` table + trigger)

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS fiscale_params_log (
    id INTEGER PRIMARY KEY,
    jaar INTEGER,
    veld TEXT,
    oude_waarde TEXT,
    nieuwe_waarde TEXT,
    tijdstip TEXT DEFAULT (datetime('now', 'localtime'))
);
```

**Implementation:** Log changes in `upsert_fiscale_params()` by comparing old vs new values before UPDATE.

---

### Task 4.5: Persist Box 3 Partner Checkbox

**Files:**
- Modify: `database.py` (add `fiscaal_partner` column to fiscale_params)
- Modify: `pages/aangifte.py` (save/load partner toggle)
- Test: `tests/test_aangifte.py`

---

## Phase 5: Architecture Polish

### Task 5.1: Split Large Page Files

**Files:**
- Split `pages/facturen.py` (914 lines) → `pages/facturen/page.py` + `pages/facturen/import_dialog.py`
- Split `pages/jaarafsluiting.py` (604 lines) → extract tab renderers

---

### Task 5.2: Service Layer for Fiscal Calculations

**Files:**
- Create: `services/fiscal_service.py`
- Consolidate: `fetch_fiscal_data()` + `bereken_volledig()` + `bereken_balans()` into one coherent service

**Goal:** Pages call `fiscal_service.get_full_report(year)` instead of manually orchestrating 5 functions.

---

### Task 5.3: Connection Management

**Files:**
- Modify: `database.py`

**Pattern:** Context manager for connection reuse within a page load:
```python
@contextlib.asynccontextmanager
async def get_connection(db_path: Path = DB_PATH):
    conn = await get_db(db_path)
    try:
        yield conn
    finally:
        await conn.close()
```

Pages can then use `async with get_connection() as conn:` to share one connection across multiple queries in a single page render.

---

### Task 5.4: Test Coverage Expansion

**Files:**
- Modify: `tests/test_fiscal.py` (add tariefsaanpassing edge cases)
- Modify: `tests/test_database.py` (add FK cascade, rollback tests)
- Create: `tests/test_advisory.py` (fiscal advisory functions)

**Target areas:**
1. Tariefsaanpassing with various income levels around bracket boundaries
2. EW forfait with villataks edge case
3. Box 3 with zero assets, only debts, partner doubling
4. FK cascade behavior (delete klant with werkdagen)
5. Integration test: full workflow from werkdag → factuur → fiscal calc

---

## Execution Order & Dependencies

```
Phase 1 (1 session) ─── All 7 tasks are independent, can be parallelized
                          ↓
Phase 2 (2 sessions) ── Task 2.3 first (categories), then 2.1 (import), then 2.2 (dialog)
                          ↓
Phase 3 (2-3 sessions) ─ Task 3.1 (calcs, TDD) → 3.2 (UI) → 3.3 (split)
                          ↓
Phase 4 (2 sessions) ── Tasks 4.1-4.5 are mostly independent
                          ↓
Phase 5 (1-2 sessions) ─ Tasks 5.1-5.4 are mostly independent
```

## Verification After Each Phase

After each phase:
1. Run full test suite: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
2. Start app and manually verify changed pages: `python main.py`
3. Check git status is clean (no uncommitted files)
