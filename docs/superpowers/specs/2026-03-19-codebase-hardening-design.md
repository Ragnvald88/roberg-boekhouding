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

**File**: `database.py:200-323`
**Problem**: 30+ `except: pass` blocks swallow ALL errors — disk full, permission denied, corruption. App runs with broken schema, fails mysteriously later.
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

**File**: `database.py:1252-1300`
**Problem**: `get_recente_facturen` and `get_factuur_count` are never called (dashboard "recente facturen" section was removed in prior refactor).
**Fix**: Delete both functions.

### 1.7 Move inline import to top-level

**File**: `pages/dashboard.py:495`
**Problem**: `from components.document_specs import AANGIFTE_DOCS` imported inside `refresh_dashboard()` on every call.
**Fix**: Move to top-level imports. (Functionally identical due to module caching, but follows project conventions and is cleaner.)

---

## Phase 2: Migration System (1 structural change)

### 2.1 Versioned migration system

**File**: `database.py` — `init_db()` function
**Problem**: 30+ ad-hoc `ALTER TABLE` + `UPDATE` statements with no version tracking. No way to know what's been applied. Adding new migrations means another `try/except: pass`.
**Fix**:

1. Add `schema_version` table: `CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, description TEXT, applied_at TEXT)`
2. Convert existing 30+ migrations into numbered entries in a `MIGRATIONS` list
3. `run_migrations()` checks current version, applies only new migrations, records each in `schema_version`
4. Each migration runs in a transaction — failure rolls back that migration and raises (instead of silently continuing)
5. Existing databases that already have all columns will detect current version via introspection on first run, then track normally going forward

---

## Phase 3: Test Hardening (6 tests)

### 3.1 Test `get_kpis` aggregate function

**Why**: Powers the dashboard. Currently untested — wrong numbers = wrong business decisions.
**Test**: Seed DB with known werkdagen/facturen/uitgaven, verify all KPI fields match expected values.

### 3.2 Test `apply_factuur_matches` werkdagen cascade

**Why**: When a factuur is marked paid via matching, its werkdagen should cascade to status='betaald'. Currently untested.
**Test**: Create werkdagen → factuur → bank payment → match → verify werkdagen.status == 'betaald'.

### 3.3 Test `extrapoleer_jaaromzet` January boundary

**Why**: On Jan 1-14, `month-1 = 0`, falls back to `max(0, 1) = 1`. Extrapolation from ~0 days data produces inflated/meaningless estimate.
**Test**: Mock date to Jan 5, verify confidence='low' and that the function doesn't divide by zero or produce absurd values.

### 3.4 Test `find_factuur_matches` 14-day boundary

**Why**: Pass 1 allows bank payments up to 14 days before factuur date. Boundary not tested.
**Test**: Payment exactly 14 days before (should match), 15 days before (should not match in Pass 1).

### 3.5 Test `bereken_balans` edge cases

**Why**: Zero activa, zero omzet, negative begin_vermogen — all plausible for a startup year.
**Test**: Verify balans calculation handles zeros gracefully without division errors.

### 3.6 Import `FISCALE_PARAMS` from seed_data in tests

**Why**: `test_fiscal.py` has a near-identical copy. Rate drift between test and production data = false confidence.
**Fix**: Replace duplicated dict with `from import_.seed_data import FISCALE_PARAMS`. Add a test that asserts test params match seed params (canary for unintentional divergence).

---

## Verification

Every change must:
1. Have a failing test first (where applicable)
2. Pass all 437+ existing tests after implementation
3. Be verified with `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

## Execution Order

1. Phase 1 (correctness) — independent fixes, can be parallelized
2. Phase 2 (migrations) — depends on 1.2 being done first
3. Phase 3 (tests) — can partially run in parallel, some depend on Phase 1/2
