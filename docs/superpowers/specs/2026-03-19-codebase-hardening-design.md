# Codebase Hardening — Design Spec

**Date**: 2026-03-19
**Branch**: TBD (new branch off main)
**Scope**: Correctness fixes, migration safety, targeted test coverage

## Goal

Make the app resilient against silent failures, NiceGUI version changes, and fiscal data drift — without adding unnecessary complexity.

## Non-goals

- No file splitting (database.py stays as one file)
- No new features
- No UI redesign
- No polish/cosmetic changes

---

## Phase 1: Safety & Correctness (7 changes)

### 1.1 Fix private `._props` access in jaarafsluiting.py

**File**: `pages/jaarafsluiting.py:144-156`
**Problem**: Direct mutation of `._props['color']` and `._props['icon']` bypasses NiceGUI public API. Will break on internal refactors.
**Fix**: Replace with `.props('color=positive')` / `.props('icon=lock_open')` public API calls.

### 1.2 Catch specific exceptions in database migrations

**File**: `database.py:225-251`
**Problem**: Three `except Exception: pass` blocks (one looping over ~30 REAL columns, one for 2 TEXT columns, one for werkdagen.locatie_id) swallow ALL errors — disk full, permission denied, corruption. App continues with broken schema, fails mysteriously later.
**Fix**: Catch only `sqlite3.OperationalError`, verify message contains "duplicate column" or "already exists". Re-raise anything else.

### 1.3 Wrap `write_bytes` in `to_thread` — bank.py

**File**: `pages/bank.py:132`
**Problem**: `archive_path.write_bytes(content)` blocks event loop during CSV archive.
**Fix**: `await asyncio.to_thread(archive_path.write_bytes, content)`

### 1.4 Wrap `write_bytes` in `to_thread` — documenten.py

**File**: `pages/documenten.py:153`
**Problem**: Same blocking I/O pattern.
**Fix**: Same `asyncio.to_thread` wrap.

### 1.5 Add notification for silent auto-matching

**File**: `pages/jaarafsluiting.py:44-46`
**Problem**: `find_factuur_matches` + `apply_factuur_matches` mutates data on every page load. If it matches wrong, user never knows.
**Fix**: After `apply_factuur_matches`, show `ui.notify(f'{len(matches)} facturen automatisch als betaald gemarkeerd', type='info')`.

### 1.6 Remove dead code

**File**: `database.py` — `get_recente_facturen` and `get_factuur_count`
**Problem**: Neither function is called from any page, component, or test. Left over from removed "recente facturen" dashboard section.
**Fix**: Delete both functions.

### 1.7 Move inline import to top-level

**File**: `pages/dashboard.py:495`
**Problem**: `from components.document_specs import AANGIFTE_DOCS` imported inside `refresh_dashboard()` on every call.
**Fix**: Move to top-level imports. (Functionally identical due to module caching, but follows project conventions and is cleaner.)

---

## Phase 2: Migration System (1 structural change)

### 2.1 Versioned migration system

**File**: `database.py` — `init_db()` function
**Problem**: Three `except Exception: pass` blocks (covering ~30 column additions) plus ~10 conditional `UPDATE` statements with no version tracking. No way to know what's been applied. New schema changes require adding more try/except blocks.

**Current structure** (to be replaced):
- Loop 1: ~30 REAL columns on `fiscale_params` — `except Exception: pass`
- Loop 2: 2 TEXT columns on `fiscale_params` — `except Exception: pass`
- Single: `locatie_id` on `werkdagen` — `except Exception: pass`
- 6 conditional `UPDATE` blocks with WHERE guards (e.g. `WHERE wet_hillen_pct = 0`)
- These data migrations are idempotent via their WHERE guards but there's no record of execution

**Fix**:

1. Add `schema_version` table: `CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, description TEXT, applied_at TEXT)`
2. Convert existing migrations into numbered entries in a `MIGRATIONS` list
3. `run_migrations()` checks current version, applies only new ones, records each in `schema_version`
4. Each migration runs in a transaction — failure rolls back and raises (instead of silently continuing)
5. **First-run detection for existing databases**: On first run, if `schema_version` doesn't exist but the main tables do exist, introspect columns via `PRAGMA table_info(fiscale_params)` to determine which schema migrations have already been applied. Set `schema_version` to the highest already-applied migration. Data migrations that have idempotent WHERE guards can safely re-run; non-idempotent ones must be skipped based on the introspected version. Specifically:
   - Schema migrations (ALTER TABLE): detectable by checking if column exists
   - Data migrations with WHERE guards (e.g. `WHERE wet_hillen_pct = 0`): safe to re-run (they no-op if already applied)
   - Date format fix (`WHERE datum GLOB '[0-3][0-9]-*'`): safe to re-run (GLOB won't match already-fixed dates)

---

## Phase 3: Test Hardening (3 changes)

### 3.1 Test `extrapoleer_jaaromzet` January boundary

**Why**: On Jan 1-14, `month-1 = 0`, falls back to `max(0, 1) = 1`. Extrapolation from ~0 days data could produce inflated/meaningless estimate. No existing test covers this edge case (existing tests use current date or past year).
**Test**: Mock `date.today()` to Jan 5, seed minimal data, verify confidence='low' and no division by zero.

### 3.2 Test `find_factuur_matches` 14-day boundary

**Why**: Pass 2 (amount matching) has a `date_ok` helper allowing payments up to 14 days before factuur date. Existing tests use 5-10 day offsets — none test the exact boundary.
**Test**: Payment exactly 14 days before factuur date (should match), 15 days before (should not match in Pass 2).

### 3.3 Import `FISCALE_PARAMS` from seed_data in tests

**Why**: `test_fiscal.py:22` has a near-identical copy of `FISCALE_PARAMS` with comment "identiek aan seed_data.py". `test_aangifte.py` already imports from seed_data correctly. If a rate changes in seed_data, test_fiscal.py would silently use stale values.
**Fix**: Replace duplicated dict with `from import_.seed_data import FISCALE_PARAMS`.

**Note**: The following were originally proposed but already have adequate test coverage:
- `get_kpis`: 2 tests in `test_db_queries.py:133-166`
- `apply_factuur_matches` werkdagen cascade: tested at `test_db_queries.py:448-451`
- `bereken_balans` edge cases: 7 tests in `test_aangifte.py:364-457`

---

## Verification

Every change must:
1. Have a failing test first (where applicable)
2. Pass all existing tests after implementation
3. Be verified with `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

## Execution Order

1. Phase 1 (correctness) — independent fixes, can be parallelized
2. Phase 2 (migrations) — depends on 1.2 being done first
3. Phase 3 (tests) — can run in parallel, independent of Phase 1/2
