# Codebase Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the app resilient against silent failures, NiceGUI version changes, and fiscal data drift.

**Architecture:** Three phases of targeted hardening. Phase 1 fixes fragile patterns (7 independent changes). Phase 2 replaces ad-hoc schema migrations with a versioned system. Phase 3 adds tests for uncovered edge cases and consolidates duplicated test data.

**Tech Stack:** Python 3.12+, NiceGUI/Quasar, SQLite/aiosqlite, pytest

**Spec:** `docs/superpowers/specs/2026-03-19-codebase-hardening-design.md`

**Test command:** `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

---

## Phase 1: Safety & Correctness

### Task 1: Fix private `._props` access in jaarafsluiting

**Files:**
- Modify: `pages/jaarafsluiting.py:143-157`

- [ ] **Step 1: Replace `._props['color']` on status_badge (line 144)**

Replace:
```python
        status_badge._props['color'] = 'positive' if is_definitief else 'warning'
        status_badge.update()
```
With:
```python
        status_badge.props(f"color={'positive' if is_definitief else 'warning'}")
```

- [ ] **Step 2: Replace `._props` on status_btn (lines 151-157)**

Replace:
```python
        if is_definitief:
            status_btn.set_text('Heropenen')
            status_btn._props['icon'] = 'lock_open'
            status_btn._props['color'] = 'warning'
        else:
            status_btn.set_text('Markeer als definitief')
            status_btn._props['icon'] = 'check_circle'
            status_btn._props['color'] = 'primary'
        status_btn.update()
```
With:
```python
        if is_definitief:
            status_btn.set_text('Heropenen')
            status_btn.props('icon=lock_open color=warning')
        else:
            status_btn.set_text('Markeer als definitief')
            status_btn.props('icon=check_circle color=primary')
```

- [ ] **Step 3: Run full test suite to verify no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass (these are UI changes not covered by unit tests, but ensure no import/syntax errors)

- [ ] **Step 4: Commit**

```bash
git add pages/jaarafsluiting.py
git commit -m "fix: replace private ._props access with public .props() API in jaarafsluiting"
```

---

### Task 2: Catch specific exceptions in database migrations

**Files:**
- Modify: `database.py:225-251`

- [ ] **Step 1: Add sqlite3 import at top of file**

Check if `import sqlite3` already exists at the top of `database.py`. If not, add it.

- [ ] **Step 2: Replace first `except Exception: pass` (REAL columns loop, line 229)**

Replace:
```python
            except Exception:
                pass  # Column already exists
```
With:
```python
            except sqlite3.OperationalError as e:
                if 'duplicate column' not in str(e).lower():
                    raise
```

- [ ] **Step 3: Replace second `except Exception: pass` (TEXT columns loop, line 241)**

Same replacement as Step 2.

- [ ] **Step 4: Replace third `except Exception: pass` (werkdagen locatie_id, line 251)**

Same replacement as Step 2.

- [ ] **Step 5: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add database.py
git commit -m "fix: catch only sqlite3.OperationalError in migrations, re-raise real errors"
```

---

### Task 3: Wrap blocking `write_bytes` calls in `to_thread`

**Files:**
- Modify: `pages/bank.py:132`
- Modify: `pages/documenten.py:153`

- [ ] **Step 1: Add `import asyncio` to bank.py**

`pages/bank.py` currently does NOT import asyncio (only imports `from datetime import datetime`). Add `import asyncio` after the existing imports at the top of the file.

- [ ] **Step 2: Fix bank.py line 132**

Replace:
```python
        archive_path.write_bytes(content)
```
With:
```python
        await asyncio.to_thread(archive_path.write_bytes, content)
```

- [ ] **Step 3: Fix documenten.py line 153**

Replace:
```python
                                        dest.write_bytes(content)
```
With:
```python
                                        await asyncio.to_thread(dest.write_bytes, content)
```

Check that `import asyncio` exists at top of `pages/documenten.py`. If not, add it.

- [ ] **Step 4: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add pages/bank.py pages/documenten.py
git commit -m "fix: wrap write_bytes in asyncio.to_thread to prevent event loop blocking"
```

---

### Task 4: Add notification for silent auto-matching in jaarafsluiting

**Files:**
- Modify: `pages/jaarafsluiting.py:43-46`

- [ ] **Step 1: Add notification after apply_factuur_matches**

Replace:
```python
    matches = await find_factuur_matches(DB_PATH)
    if matches:
        await apply_factuur_matches(DB_PATH, matches)
```
With:
```python
    matches = await find_factuur_matches(DB_PATH)
    if matches:
        await apply_factuur_matches(DB_PATH, matches)
        ui.notify(
            f'{len(matches)} facturen automatisch als betaald gemarkeerd',
            type='info',
        )
```

- [ ] **Step 2: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add pages/jaarafsluiting.py
git commit -m "fix: notify user when jaarafsluiting auto-matches facturen to bank payments"
```

---

### Task 5: Remove dead code from database.py

**Files:**
- Modify: `database.py` — delete `get_recente_facturen` (~line 1252) and `get_factuur_count` (~line 1283)

- [ ] **Step 1: Verify functions are truly unused**

Search the entire codebase for any references to `get_recente_facturen` or `get_factuur_count` outside of `database.py` itself. Both should return zero results.

- [ ] **Step 2: Delete `get_recente_facturen` function**

Remove the entire function (approximately lines 1252-1263):
```python
async def get_recente_facturen(db_path: Path = DB_PATH,
                                limit: int = 5) -> list[Factuur]:
    """Get most recent invoices across all years."""
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """SELECT f.*, k.naam as klant_naam
               FROM facturen f JOIN klanten k ON f.klant_id = k.id
               ORDER BY f.datum DESC LIMIT ?""",
            (limit,)
        )
        rows = await cursor.fetchall()
        return [_row_to_factuur(r) for r in rows]
```

- [ ] **Step 3: Delete `get_factuur_count` function**

Remove the entire function (approximately lines 1283-1290):
```python
async def get_factuur_count(db_path: Path = DB_PATH, jaar: int = 2026) -> int:
    """Count invoices for a year."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM facturen WHERE substr(datum, 1, 4) = ? AND type = 'factuur'",
            (str(jaar),)
        )
        return (await cur.fetchone())[0]
```

- [ ] **Step 4: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add database.py
git commit -m "refactor: remove unused get_recente_facturen and get_factuur_count"
```

---

### Task 6: Move inline import to top-level in dashboard.py

**Files:**
- Modify: `pages/dashboard.py:19,495`

- [ ] **Step 1: Add import at top-level (after line 19)**

Add to the existing imports block (around line 19-20):
```python
from components.document_specs import AANGIFTE_DOCS
```

- [ ] **Step 2: Replace inline import (line 495)**

Replace:
```python
                from components.document_specs import AANGIFTE_DOCS as _ADOCS
                total_docs = len(_ADOCS)
```
With:
```python
                total_docs = len(AANGIFTE_DOCS)
```

- [ ] **Step 3: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add pages/dashboard.py
git commit -m "refactor: move AANGIFTE_DOCS import to top-level in dashboard"
```

---

## Phase 2: Migration System

### Task 7: Implement versioned migration system

**Files:**
- Modify: `database.py:195-324` (replace entire `init_db` migration section)

- [ ] **Step 1: Write test for migration system**

Create a test that verifies:
- Fresh DB gets all migrations applied and schema_version set to latest
- DB with all columns already (simulating existing install) detects current version correctly

Add to `tests/test_database.py`:
```python
@pytest.mark.asyncio
async def test_migrations_fresh_db(tmp_path):
    """Fresh database gets all migrations applied."""
    db = tmp_path / 'test.db'
    await init_db(db)
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT MAX(version) FROM schema_version")
        row = await cur.fetchone()
        assert row[0] is not None and row[0] > 0


@pytest.mark.asyncio
async def test_migrations_idempotent(tmp_path):
    """Running init_db twice doesn't fail or re-apply migrations."""
    db = tmp_path / 'test.db'
    await init_db(db)
    await init_db(db)  # second run should be a no-op
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM schema_version")
        count = (await cur.fetchone())[0]
        assert count > 0

        # Verify fiscale_params columns exist
        cur = await conn.execute("PRAGMA table_info(fiscale_params)")
        columns = {row[1] for row in await cur.fetchall()}
        assert 'box3_fiscaal_partner' in columns
        assert 'jaarafsluiting_status' in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py::test_migrations_fresh_db tests/test_database.py::test_migrations_idempotent -v`
Expected: FAIL (schema_version table doesn't exist yet)

- [ ] **Step 3: Add schema_version to SCHEMA_SQL**

In `database.py`, add to the `SCHEMA_SQL` string (after the last `CREATE TABLE`):
```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
```

- [ ] **Step 4: Create `_get_existing_columns` helper**

Add above `init_db`:
```python
async def _get_existing_columns(conn, table: str) -> set[str]:
    """Get set of column names for a table via PRAGMA."""
    cur = await conn.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return {row[1] for row in rows}
```

- [ ] **Step 5: Create `MIGRATIONS` list and `_run_migrations` function**

Replace the entire migration section inside `init_db` (lines 201-324) with:
```python
import sqlite3

MIGRATIONS = [
    # (version, description, sql_or_callable)
    # Schema migrations — ADD COLUMN for fiscale_params REAL columns
    (1, "add_aov_woz_hypotheek_va_columns", [
        "ALTER TABLE fiscale_params ADD COLUMN aov_premie REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN woz_waarde REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN hypotheekrente REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN voorlopige_aanslag_betaald REAL DEFAULT 0",
    ]),
    (2, "add_ew_uren_partner_pvv_columns", [
        "ALTER TABLE fiscale_params ADD COLUMN ew_forfait_pct REAL DEFAULT 0.35",
        "ALTER TABLE fiscale_params ADD COLUMN villataks_grens REAL DEFAULT 1350000",
        "ALTER TABLE fiscale_params ADD COLUMN wet_hillen_pct REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN urencriterium REAL DEFAULT 1225",
        "ALTER TABLE fiscale_params ADD COLUMN partner_bruto_loon REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN partner_loonheffing REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN pvv_premiegrondslag REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN ew_naar_partner REAL DEFAULT 1",
        "ALTER TABLE fiscale_params ADD COLUMN voorlopige_aanslag_zvw REAL DEFAULT 0",
    ]),
    (3, "add_pvv_box3_columns", [
        "ALTER TABLE fiscale_params ADD COLUMN pvv_aow_pct REAL DEFAULT 17.90",
        "ALTER TABLE fiscale_params ADD COLUMN pvv_anw_pct REAL DEFAULT 0.10",
        "ALTER TABLE fiscale_params ADD COLUMN pvv_wlz_pct REAL DEFAULT 9.65",
        "ALTER TABLE fiscale_params ADD COLUMN box3_bank_saldo REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN box3_overige_bezittingen REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN box3_schulden REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN box3_heffingsvrij_vermogen REAL DEFAULT 57000",
        "ALTER TABLE fiscale_params ADD COLUMN box3_rendement_bank_pct REAL DEFAULT 1.03",
        "ALTER TABLE fiscale_params ADD COLUMN box3_rendement_overig_pct REAL DEFAULT 6.17",
        "ALTER TABLE fiscale_params ADD COLUMN box3_rendement_schuld_pct REAL DEFAULT 2.46",
        "ALTER TABLE fiscale_params ADD COLUMN box3_tarief_pct REAL DEFAULT 36",
    ]),
    (4, "add_balans_za_sa_lijfrente_columns", [
        "ALTER TABLE fiscale_params ADD COLUMN box3_drempel_schulden REAL DEFAULT 3700",
        "ALTER TABLE fiscale_params ADD COLUMN balans_bank_saldo REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN balans_crediteuren REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN balans_overige_vorderingen REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN balans_overige_schulden REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN za_actief REAL DEFAULT 1",
        "ALTER TABLE fiscale_params ADD COLUMN sa_actief REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN lijfrente_premie REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN box3_fiscaal_partner REAL DEFAULT 1",
    ]),
    (5, "add_text_columns", [
        "ALTER TABLE fiscale_params ADD COLUMN arbeidskorting_brackets TEXT DEFAULT ''",
        "ALTER TABLE fiscale_params ADD COLUMN jaarafsluiting_status TEXT DEFAULT 'concept'",
    ]),
    (6, "add_werkdagen_locatie_id", [
        "ALTER TABLE werkdagen ADD COLUMN locatie_id INTEGER REFERENCES klant_locaties(id) ON DELETE SET NULL",
    ]),
    # Data migrations — all idempotent via WHERE guards
    (7, "set_ew_uren_per_year", None),  # handled by callable
    (8, "populate_ak_brackets_and_box3", None),  # handled by callable
    (9, "fix_box3_2025_definitief", [
        """UPDATE fiscale_params SET
           box3_rendement_bank_pct = 1.37,
           box3_rendement_overig_pct = 5.88,
           box3_rendement_schuld_pct = 2.70
           WHERE jaar = 2025 AND box3_rendement_bank_pct = 1.28""",
    ]),
    (10, "set_sa_actief_first_years", [
        "UPDATE fiscale_params SET sa_actief = 1 WHERE jaar = 2023 AND sa_actief = 0",
        "UPDATE fiscale_params SET sa_actief = 1 WHERE jaar = 2024 AND sa_actief = 0",
        "UPDATE fiscale_params SET sa_actief = 1 WHERE jaar = 2025 AND sa_actief = 0",
    ]),
    (11, "fix_2026_box3_heffingsvrij", [
        """UPDATE fiscale_params
           SET box3_heffingsvrij_vermogen = 59357, box3_drempel_schulden = 3800
           WHERE jaar = 2026 AND box3_heffingsvrij_vermogen = 57684""",
    ]),
    (12, "fix_date_format", [
        """UPDATE uitgaven
           SET datum = substr(datum,7,4) || '-' || substr(datum,4,2) || '-' || substr(datum,1,2)
           WHERE datum GLOB '[0-3][0-9]-[0-1][0-9]-[0-9][0-9][0-9][0-9]'""",
        """UPDATE werkdagen
           SET datum = substr(datum,7,4) || '-' || substr(datum,4,2) || '-' || substr(datum,1,2)
           WHERE datum GLOB '[0-3][0-9]-[0-1][0-9]-[0-9][0-9][0-9][0-9]'""",
    ]),
]


async def _run_migration_7(conn):
    """Data migration: set correct per-year EW/uren values."""
    year_data = {
        2023: {'ew_forfait_pct': 0.35, 'villataks_grens': 1200000, 'wet_hillen_pct': 83.333, 'urencriterium': 1225},
        2024: {'ew_forfait_pct': 0.35, 'villataks_grens': 1310000, 'wet_hillen_pct': 80.0, 'urencriterium': 1225},
        2025: {'ew_forfait_pct': 0.35, 'villataks_grens': 1330000, 'wet_hillen_pct': 76.667, 'urencriterium': 1225},
        2026: {'ew_forfait_pct': 0.35, 'villataks_grens': 1350000, 'wet_hillen_pct': 71.867, 'urencriterium': 1225},
    }
    for jaar, vals in year_data.items():
        await conn.execute(
            """UPDATE fiscale_params SET ew_forfait_pct = ?, villataks_grens = ?,
               wet_hillen_pct = ?, urencriterium = ?
               WHERE jaar = ? AND wet_hillen_pct = 0""",
            (vals['ew_forfait_pct'], vals['villataks_grens'],
             vals['wet_hillen_pct'], vals['urencriterium'], jaar))


async def _run_migration_8(conn):
    """Data migration: populate AK brackets and Box 3 defaults."""
    from import_.seed_data import AK_BRACKETS, BOX3_DEFAULTS
    import json as _json
    for jaar in [2023, 2024, 2025, 2026]:
        await conn.execute(
            "UPDATE fiscale_params SET arbeidskorting_brackets = ? "
            "WHERE jaar = ? AND (arbeidskorting_brackets IS NULL OR arbeidskorting_brackets = '')",
            (_json.dumps(AK_BRACKETS.get(jaar, [])), jaar))
        b3 = BOX3_DEFAULTS.get(jaar)
        if b3:
            await conn.execute(
                "UPDATE fiscale_params SET "
                "box3_heffingsvrij_vermogen = ?, box3_rendement_bank_pct = ?, "
                "box3_rendement_overig_pct = ?, box3_rendement_schuld_pct = ?, "
                "box3_tarief_pct = ? "
                "WHERE jaar = ? AND box3_rendement_bank_pct = 1.03 "
                "AND box3_heffingsvrij_vermogen = 57000",
                (b3['heffingsvrij'], b3['bank'], b3['overig'], b3['schuld'], b3['tarief'], jaar))
            if 'drempel_schulden' in b3:
                await conn.execute(
                    "UPDATE fiscale_params SET box3_drempel_schulden = ? "
                    "WHERE jaar = ? AND box3_drempel_schulden = 3700",
                    (b3['drempel_schulden'], jaar))

MIGRATION_CALLABLES = {7: _run_migration_7, 8: _run_migration_8}
```

- [ ] **Step 6: Rewrite `init_db` to use the migration system**

Replace the body of `init_db` (after `SCHEMA_SQL` execution) with:
```python
async def init_db(db_path: Path = DB_PATH) -> None:
    """Create all tables if they don't exist, then run migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()

        # Determine current schema version
        cur = await conn.execute(
            "SELECT MAX(version) FROM schema_version")
        row = await cur.fetchone()
        current_version = row[0] or 0

        # First-run detection: if schema_version is empty but tables exist,
        # introspect to find which migrations are already applied
        if current_version == 0:
            fp_cols = await _get_existing_columns(conn, 'fiscale_params')
            wd_cols = await _get_existing_columns(conn, 'werkdagen')

            # Check marker columns for each schema migration group
            # Must check in reverse order (highest first)
            if ('locatie_id' in wd_cols
                    and 'jaarafsluiting_status' in fp_cols
                    and 'box3_fiscaal_partner' in fp_cols):
                current_version = 6  # All schema migrations done
            elif 'jaarafsluiting_status' in fp_cols:
                current_version = 5
            elif 'box3_fiscaal_partner' in fp_cols:
                current_version = 4
            elif 'pvv_aow_pct' in fp_cols:
                current_version = 3
            elif 'ew_forfait_pct' in fp_cols:
                current_version = 2
            elif 'aov_premie' in fp_cols:
                current_version = 1

            # Record detected version
            if current_version > 0:
                from datetime import datetime as _dt
                now = _dt.now().isoformat()
                for v in range(1, current_version + 1):
                    desc = next(
                        (d for ver, d, _ in MIGRATIONS if ver == v),
                        f'migration_{v}')
                    await conn.execute(
                        "INSERT OR IGNORE INTO schema_version "
                        "(version, description, applied_at) VALUES (?, ?, ?)",
                        (v, desc, now))
                await conn.commit()

        # Apply pending migrations
        for version, description, sql_list in MIGRATIONS:
            if version <= current_version:
                continue
            try:
                if sql_list is not None:
                    for sql in sql_list:
                        try:
                            await conn.execute(sql)
                        except sqlite3.OperationalError as e:
                            if 'duplicate column' not in str(e).lower():
                                raise
                elif version in MIGRATION_CALLABLES:
                    await MIGRATION_CALLABLES[version](conn)

                from datetime import datetime as _dt
                await conn.execute(
                    "INSERT INTO schema_version "
                    "(version, description, applied_at) VALUES (?, ?, ?)",
                    (version, description, _dt.now().isoformat()))
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
```

- [ ] **Step 7: Run tests to verify migration tests pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py -v`
Expected: All pass including new migration tests

- [ ] **Step 8: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 9: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: versioned migration system with schema_version table

Replaces ad-hoc except-pass migrations with numbered, tracked migrations.
Existing databases are detected via column introspection on first run.
Each migration runs in a transaction and records execution."
```

---

## Phase 3: Test Hardening

### Task 8: Test `extrapoleer_jaaromzet` January boundary

**Files:**
- Modify: `tests/test_fiscal.py` — add test to `TestExtrapoleerJaaromzet` class (around line 1965)

- [ ] **Step 1: Write the failing test**

Add to the `TestExtrapoleerJaaromzet` class in `tests/test_fiscal.py`.

Note: `extrapoleer_jaaromzet` does `from datetime import date as _d` inside the function body, then calls `_d.today()`. Since the import is local, we need to mock `datetime.date` at the module level before calling the function.

```python
    def test_january_early_month_no_crash(self, db_path):
        """Jan 1-14: complete_months=max(0,1)=1, should not divide by zero."""
        import asyncio
        import datetime
        from database import add_factuur
        from components.fiscal_utils import extrapoleer_jaaromzet

        # Add a small amount of revenue for January
        asyncio.run(add_factuur(db_path, nummer='2026-JAN', klant_id=1,
                                 datum='2026-01-03', totaal_uren=4,
                                 totaal_km=0, totaal_bedrag=500))

        # Mock datetime.date so that date.today() returns Jan 5
        original_date = datetime.date

        class MockDate(datetime.date):
            @classmethod
            def today(cls):
                return original_date(2026, 1, 5)

        datetime.date = MockDate
        try:
            result = asyncio.run(extrapoleer_jaaromzet(db_path, 2026))
        finally:
            datetime.date = original_date

        assert result['confidence'] == 'low'
        assert result['basis_maanden'] == 1  # max(month-1, 1) = max(0, 1) = 1
        assert result['extrapolated_omzet'] > 0  # should extrapolate, not crash
        assert result['extrapolated_omzet'] == 500 * 12  # 500/1month * 12
```

- [ ] **Step 2: Run test to verify it passes (this is a boundary test, not TDD)**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestExtrapoleerJaaromzet::test_january_early_month_no_crash -v`
Expected: PASS (the code handles this case, we're documenting the behavior)

- [ ] **Step 3: Commit**

```bash
git add tests/test_fiscal.py
git commit -m "test: add January boundary test for extrapoleer_jaaromzet"
```

---

### Task 9: Test `find_factuur_matches` 14-day boundary

**Files:**
- Modify: `tests/test_db_queries.py` — add test after existing match tests (around line 458)

- [ ] **Step 1: Write the boundary tests**

Add after the existing match tests in `tests/test_db_queries.py` (around line 458). The required imports (`find_factuur_matches`, `add_klant`, `add_factuur`, `add_banktransacties`) are already at the top of the file.

```python
@pytest.mark.asyncio
async def test_find_matches_14_day_boundary_pass(db):
    """Payment exactly 14 days before factuur date should match (Pass 2)."""
    kid = await add_klant(db, naam="Boundary", tarief_uur=80, retour_km=0)
    # Factuur dated 2026-03-15
    await add_factuur(db, nummer='2026-BND', klant_id=kid,
                       datum='2026-03-15', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, betaald=0)
    # Payment 14 days before = 2026-03-01 (exactly on boundary)
    await add_banktransacties(db, [
        {'datum': '2026-03-01', 'bedrag': 640.00, 'tegenpartij': 'Someone',
         'omschrijving': 'payment', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 1
    assert matches[0]['match_type'] == 'bedrag'


@pytest.mark.asyncio
async def test_find_matches_15_day_boundary_fail(db):
    """Payment 15 days before factuur date should NOT match."""
    kid = await add_klant(db, naam="Boundary", tarief_uur=80, retour_km=0)
    # Factuur dated 2026-03-16
    await add_factuur(db, nummer='2026-BND2', klant_id=kid,
                       datum='2026-03-16', totaal_uren=8, totaal_km=0,
                       totaal_bedrag=640.00, betaald=0)
    # Payment 15 days before = 2026-03-01
    await add_banktransacties(db, [
        {'datum': '2026-03-01', 'bedrag': 640.00, 'tegenpartij': 'Someone',
         'omschrijving': 'betaling', 'categorie': ''},
    ], csv_bestand='test.csv')

    matches = await find_factuur_matches(db)
    assert len(matches) == 0
```

- [ ] **Step 2: Run tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py::test_find_matches_14_day_boundary_pass tests/test_db_queries.py::test_find_matches_15_day_boundary_fail -v`
Expected: Both PASS (documenting existing behavior)

- [ ] **Step 3: Commit**

```bash
git add tests/test_db_queries.py
git commit -m "test: add 14-day boundary tests for find_factuur_matches"
```

---

### Task 10: Import FISCALE_PARAMS from seed_data in test_fiscal.py

**Files:**
- Modify: `tests/test_fiscal.py:20-22` and the `FISCALE_PARAMS` dict definition

- [ ] **Step 1: Replace the duplicated dict with an import**

In `tests/test_fiscal.py`, replace the `FISCALE_PARAMS` definition (starting around line 20-22).

**Important differences between the two dicts:**
- `seed_data.py` uses `1`/`0` (int) for `za_actief`/`sa_actief`; test file uses `True`/`False` (bool). This is safe because `1 == True` and `0 == False` in Python, and the fiscal engine uses these values in arithmetic (`za * zelfstandigenaftrek`).
- `seed_data.py` has extra keys (`arbeidskorting_brackets`, `pvv_aow_pct`, `pvv_anw_pct`, `pvv_wlz_pct`, `box3_*` fields) that the test file doesn't have. These extra keys are harmless — `bereken_volledig` receives `params=dict` and reads only the keys it needs via `.get()`.

Replace the entire `FISCALE_PARAMS = { ... }` block (approximately lines 22-100) with:
```python
from import_.seed_data import FISCALE_PARAMS
```

After replacing, immediately run the fiscal tests to verify the extra keys and type differences don't cause failures. If any test does `assert params['za_actief'] is True` (identity check), change it to `assert params['za_actief'] == True` (equality check).

- [ ] **Step 2: Run full test suite to verify nothing breaks**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py -v`
Expected: All fiscal tests pass with imported params

- [ ] **Step 3: Run full suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/test_fiscal.py
git commit -m "refactor: import FISCALE_PARAMS from seed_data instead of duplicating in tests"
```

---

## Final Verification

### Task 11: Full test suite + commit summary

- [ ] **Step 1: Run complete test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests pass (should be original count + 4-5 new tests)

- [ ] **Step 2: Verify no unintended changes**

Run: `git diff --stat main` to see summary of all changes.
Expected: Only the files listed in this plan should be modified.
