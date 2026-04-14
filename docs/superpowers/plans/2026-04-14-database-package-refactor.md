# Database Package Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 2730-line `database.py` into a focused package (`database/`) with one module per domain, preserving every public import site across the codebase without changing call semantics.

**Architecture:** Convert `database.py` → `database/__init__.py` wholesale, then extract one domain module per task in dependency order (infrastructure first, then domain modules). Each extraction moves code, adds re-exports to `__init__.py`, and verifies all 638 tests still pass. The final `__init__.py` becomes a thin re-export layer preserving `from database import X` everywhere.

**Tech Stack:** Python 3.12+, aiosqlite, pytest + pytest-asyncio. No new dependencies.

**Test command:** `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q`

**Baseline (before starting):** 638 passed, 14 skipped. Every task must end with this count unchanged (unless the task adds tests, in which case the pass count increases).

---

## Why this refactor

The final reviewer of the previous plan (`2026-04-13-codex-review-enhancements.md`) flagged `database.py` at ~2700 LOC as approaching a refactoring inflection point. This plan executes that refactor.

**Observed pain:**
- Single 2730-line file holding 85 public functions across 11 loosely-related domains.
- Merge risk: every domain change touches the same file.
- Navigation cost: jumping between "werkdag queries" and "fiscale_params queries" means scrolling 1000+ lines.
- Test-impact blast radius: any import of `from database import X` pulls in the entire module (migrations + schema + all queries), even for a simple unit test.

**Non-goals:**
- No behavior changes. Every function retains its exact signature and SQL.
- No new tests, no deleted tests. Every existing test must pass unchanged.
- No API breakage. `from database import X` continues to work for every X used in the codebase today.

---

## Public API to preserve

The following names must be importable from `database` after the refactor (from call sites across `pages/*.py`, `components/*.py`, `tests/*.py`, `main.py`, `import_/seed_data.py`, `migrate_db_location.py`):

**Infrastructure:** `DB_PATH`, `get_db`, `get_db_ctx`, `init_db`

**Dataclass re-exports:** `MatchProposal`

**Bedrijfsgegevens:** `get_bedrijfsgegevens`, `upsert_bedrijfsgegevens`

**Klanten + locaties:** `get_klanten`, `add_klant`, `update_klant`, `delete_klant`, `get_klant_locaties`, `add_klant_locatie`, `delete_klant_locatie`

**Werkdagen:** `get_werkdagen`, `add_werkdag`, `update_werkdag`, `delete_werkdag`, `get_werkdagen_ongefactureerd`

**Facturen + matching:** `get_facturen`, `add_factuur`, `get_next_factuurnummer`, `factuurnummer_exists`, `update_factuur_status`, `mark_betaald`, `update_factuur`, `delete_factuur`, `link_werkdagen_to_factuur`, `save_factuur_atomic`, `get_openstaande_facturen`, `find_factuur_matches`, `apply_factuur_matches`, `backfill_betaallinks`

**Uitgaven + afschrijvingen:** `get_uitgaven`, `add_uitgave`, `update_uitgave`, `delete_uitgave`, `get_uitgaven_per_categorie`, `get_investeringen`, `get_investeringen_voor_afschrijving`, `get_afschrijving_overrides`, `get_afschrijving_overrides_batch`, `set_afschrijving_override`, `delete_afschrijving_override`

**Banktransacties:** `get_banktransacties`, `get_imported_csv_bestanden`, `add_banktransacties`, `update_banktransactie`, `get_categorie_suggestions`, `delete_banktransacties`, `get_va_betalingen`, `backfill_betalingskenmerken`, `get_belastingdienst_betalingen`

**Fiscale params + docs + snapshots:** `get_fiscale_params`, `get_all_fiscale_params`, `upsert_fiscale_params`, `update_ib_inputs`, `update_za_sa_toggles`, `update_ew_naar_partner`, `update_box3_fiscaal_partner`, `update_box3_inputs`, `update_partner_inputs`, `update_balans_inputs`, `update_jaarafsluiting_status`, `get_aangifte_documenten`, `add_aangifte_document`, `delete_aangifte_document`, `save_jaarafsluiting_snapshot`, `load_jaarafsluiting_snapshot`, `delete_jaarafsluiting_snapshot`

**Aggregations:** `get_omzet_per_maand`, `get_kpis`, `get_kpis_tot_datum`, `get_omzet_per_klant`, `get_uren_totaal`, `get_omzet_totaal`, `get_data_counts`, `get_representatie_totaal`, `get_werkdagen_ongefactureerd_summary`, `get_health_alerts`, `get_km_totaal`, `get_debiteuren_op_peildatum`, `get_nog_te_factureren`

That's 85 names total. `__init__.py` must re-export all of them.

---

## File Map

```
database/
├── __init__.py         (re-exports only — the public API)
├── core.py             (DB_PATH, get_db, get_db_ctx, _validate_datum, _get_existing_columns, BELASTINGDIENST_IBAN, module-level DB_DIR side effect)
├── schema.py           (SCHEMA_SQL, MIGRATIONS, _run_migration_*, _MIGRATION_CALLABLES, init_db)
├── rows.py             (_row_to_werkdag, _row_to_factuur, _row_to_uitgave, _row_to_fiscale_params)
├── bedrijf.py          (2 functions: get/upsert bedrijfsgegevens)
├── klanten.py          (7 functions: klanten CRUD + klant_locaties CRUD)
├── werkdagen.py        (5 functions: werkdagen CRUD + ongefactureerd query)
├── facturen.py         (14 items: MatchProposal + 11 facturen CRUD + 2 matching + backfill_betaallinks)
├── uitgaven.py         (11 functions: uitgaven CRUD + investeringen queries + 4 afschrijving overrides)
├── banktransacties.py  (9 functions: bank CRUD + suggestions + VA/belastingdienst + backfill_betalingskenmerken)
├── fiscale_params.py   (17 functions: fiscale_params CRUD + aangifte_documenten + snapshots)
└── aggregations.py     (13 functions: dashboard aggregations + health_alerts)
```

**Dependency graph:**
- `core` has no internal dependencies (foundation)
- `rows` imports from `models` (external) and the domain dataclasses
- `schema` imports from `core`; calls `backfill_betalingskenmerken` (banktransacties) + `backfill_betaallinks` (facturen) via **lazy imports inside `init_db`**
- All domain modules import from `core`, `models`, and (where needed) `rows`
- Cross-domain calls: `aggregations` calls `get_fiscale_params` (fiscale_params domain) for `get_health_alerts` — use module-level import since there's no cycle
- `__init__.py` re-exports everything, importing from each submodule

---

## Execution notes for subagent-driven work

**Each task:**
1. Is one atomic extraction (one file created or one block of code moved)
2. Must end with `pytest tests/ -q` returning 638 passed / 14 skipped
3. Must commit with the exact message specified
4. Must NOT change any function body, signature, or SQL. The only allowed changes are:
   - Adding new imports (because the function now lives in a new file)
   - Removing content from `__init__.py` that moved to a new file
   - Adding re-export lines to `__init__.py`

**If the implementer finds that a function depends on something they haven't extracted yet:** the dependency stays in `__init__.py` (because `__init__.py` is progressively being emptied) and the new module imports from `database` directly — that works because Python's module system resolves the package's `__init__.py`. Example: `werkdagen.py` needs `_row_to_werkdag` which hasn't been moved yet — it can do `from database.rows import _row_to_werkdag` once `rows.py` exists, or `from database import _row_to_werkdag` before (but this would cycle on package import).

**The safe import pattern within the package:** always `from database.core import X`, never `from database import X`. This prevents circular imports because submodules never go through `__init__.py`.

**Test running:** after every step's code change, run the full suite — catching regressions early is cheaper than debugging them later. The full suite takes ~4 seconds.

---

## Task 1: Move `database.py` to `database/__init__.py`

**Goal:** Wholesale move with zero content changes. Establishes the package structure.

**Files:**
- Delete: `database.py`
- Create: `database/__init__.py` (identical content to the deleted file)

- [ ] **Step 1: Create the package directory and move the file**

```bash
mkdir -p database
git mv database.py database/__init__.py
```

- [ ] **Step 2: Run the full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q`
Expected: `638 passed, 14 skipped`

If any tests fail, the refactor premise is broken — investigate before proceeding. Likely causes: an editor or tool auto-converted the file; the `mkdir` somehow conflicted with existing files; `git mv` rename detection isn't cleanly tracked.

- [ ] **Step 3: Commit**

```bash
git add database/
git commit -m "refactor(database): move to package (wholesale move, no content changes)

Step 1 of the database package refactor. The file is now located at
database/__init__.py with identical content. Subsequent commits will
extract domain modules incrementally."
```

---

## Task 2: Extract `database/core.py`

**Goal:** Extract the foundational connection primitives and path setup that every other module depends on.

**Files:**
- Create: `database/core.py`
- Modify: `database/__init__.py` (remove extracted content, add re-exports)

### What goes in core.py

From `database/__init__.py`, cut and move to `database/core.py`:

1. **Imports at the top of `__init__.py`** that `core.py` needs:
   - `import os`
   - `import re` (needed by `_validate_datum`)
   - `from contextlib import asynccontextmanager`
   - `from datetime import date as _date` (needed by `_validate_datum`)
   - `import aiosqlite`
   - `from pathlib import Path`

2. **Module-level constants (currently lines 50-54):**
```python
_DEFAULT_DB_DIR = Path.home() / "Library" / "Application Support" / "Boekhouding" / "data"
_ENV_OVERRIDE = os.environ.get("BOEKHOUDING_DB_DIR")
_DB_DIR = Path(_ENV_OVERRIDE).expanduser() if _ENV_OVERRIDE else _DEFAULT_DB_DIR
_DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = _DB_DIR / "boekhouding.sqlite3"
```

3. **Constant (currently around line 1445):**
```python
BELASTINGDIENST_IBAN = 'NL86INGB0002445588'
```

4. **Functions:**
   - `get_db` (currently lines 263-272)
   - `get_db_ctx` (currently lines 276-282)
   - `_get_existing_columns` (currently line 285)
   - `_validate_datum` (currently line 647)

- [ ] **Step 1: Create `database/core.py` with the extracted content**

**CRITICAL:** The function bodies must be copied VERBATIM from `database/__init__.py`. Do not retype or "improve" them. Open the source, find the exact lines, copy-paste into the new file. The skeleton below shows only module structure — every `...` placeholder must be replaced with the exact function body from the source line range.

Create `database/core.py` with this structure:

```python
"""Core database primitives: connection, path, validation.

This module is imported by every other database submodule. It must have
no internal dependencies on other database/* modules.
"""

import os
import re
from contextlib import asynccontextmanager
from datetime import date as _date
from pathlib import Path

import aiosqlite

# Module-level constants and mkdir side effect (source lines 50-54).
# Copy these 5 lines VERBATIM:
_DEFAULT_DB_DIR = ...
_ENV_OVERRIDE = ...
_DB_DIR = ...
# _DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = ...

# Constant (source line 1445):
BELASTINGDIENST_IBAN = 'NL86INGB0002445588'


# Function: get_db — copy VERBATIM from source lines 263-272.
# Includes PRAGMAs: journal_mode=WAL, foreign_keys=ON, synchronous=NORMAL,
# cache_size=10000, temp_store=MEMORY. row_factory is assigned LAST.
async def get_db(db_path: Path = DB_PATH) -> aiosqlite.Connection:
    ...


# Function: get_db_ctx — copy VERBATIM from source lines 275-282.
# Decorated with @asynccontextmanager.
@asynccontextmanager
async def get_db_ctx(db_path: Path = DB_PATH):
    ...


# Function: _get_existing_columns — copy VERBATIM from source lines 285-289.
async def _get_existing_columns(conn, table: str) -> set[str]:
    ...


# Function: _validate_datum — copy VERBATIM from source lines 647-660.
# NOTE: returns `str` (the datum), not None. Uses inline re.match, no precompiled pattern.
def _validate_datum(datum: str) -> str:
    ...
```

After pasting, run `python -c "from database.core import get_db, get_db_ctx, _validate_datum, DB_PATH; print('OK')"` to catch syntax errors immediately.

- [ ] **Step 2: Remove the extracted content from `database/__init__.py`**

In `database/__init__.py`:
1. Delete the module-level constants `_DEFAULT_DB_DIR`, `_ENV_OVERRIDE`, `_DB_DIR`, the `mkdir` side effect, and `DB_PATH`.
2. Delete `BELASTINGDIENST_IBAN`.
3. Delete `get_db`, `get_db_ctx`, `_get_existing_columns`, `_validate_datum`.

Leave in `__init__.py`: everything else (imports that remain needed, dataclass, constants used by other functions, all unmoved functions).

At the TOP of `__init__.py`, add this re-export block (after the existing imports, before the remaining code):

```python
# Re-exports: preserve public `from database import X` API during refactor.
from database.core import (
    DB_PATH,
    get_db,
    get_db_ctx,
    _validate_datum,
    _get_existing_columns,
    BELASTINGDIENST_IBAN,
)
```

**Why `_validate_datum` and `_get_existing_columns` are re-exported despite the underscore:** they're used by code that's still in `__init__.py` (migrations, werkdag CRUD, facturen CRUD, etc.), so keeping them in the `database` namespace avoids sprinkling `from database.core import _validate_datum` throughout the soon-to-be-empty shell.

- [ ] **Step 3: Verify no test files or external callers reference the deleted module-level names directly on `database`**

Grep to confirm: `grep -rn "database._DB_DIR\|database._DEFAULT_DB_DIR\|database._ENV_OVERRIDE" --include="*.py" .`
Expected: no matches (these are truly private).

- [ ] **Step 4: Run the full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q`
Expected: `638 passed, 14 skipped`

If a test fails with `ImportError: cannot import name 'DB_PATH' from 'database'` — double-check that the re-export block in `__init__.py` includes `DB_PATH`.

If a test fails with `ModuleNotFoundError: No module named 'database.core'` — verify that `database/core.py` exists at the expected path and is valid Python (try `python -c "from database.core import DB_PATH; print(DB_PATH)"`).

- [ ] **Step 5: Commit**

```bash
git add database/core.py database/__init__.py
git commit -m "refactor(database): extract core module (connections, path, validation)

Moves DB_PATH, get_db, get_db_ctx, _validate_datum, _get_existing_columns,
and BELASTINGDIENST_IBAN into database/core.py. database/__init__.py
re-exports them to preserve the public API."
```

---

## Task 3: Extract `database/rows.py`

**Goal:** Extract the four `_row_to_*` conversion helpers. These are pure transforms from `aiosqlite.Row` to dataclass instances.

**Files:**
- Create: `database/rows.py`
- Modify: `database/__init__.py`

### What goes in rows.py

Cut from `__init__.py`:
- `_row_to_werkdag` (currently line 766)
- `_row_to_factuur` (currently line 791)
- `_row_to_uitgave` (currently line 808)
- `_row_to_fiscale_params` (currently line 1598)

### Imports rows.py needs

```python
import json  # _row_to_fiscale_params parses arbeidskorting_brackets JSON
from models import (
    Werkdag,
    Factuur,
    Uitgave,
    FiscaleParams,
)
```

**IMPORTANT:** before writing, read the actual row-converter function bodies to see which imports they actually use. `_row_to_fiscale_params` uses JSON parsing — verify this by reading the function. If `_row_to_werkdag` uses `_date` or `_datetime` for derived-status computation, import from `datetime`.

- [ ] **Step 1: Create `database/rows.py`**

**CRITICAL:** Function bodies must be copied VERBATIM from the source line ranges. Do not retype.

Before writing: read the four `_row_to_*` functions in `database/__init__.py` and note:
- Which standard-library modules each one imports or uses (e.g., `json` for `_row_to_fiscale_params` parsing `arbeidskorting_brackets`, `datetime` helpers for `_row_to_werkdag` if it computes derived status from dates).
- Which dataclasses from `models` each one returns.

Only include imports that are actually used. If `json` is not used anywhere in the file, omit it.

Structure:

```python
"""Row converters: aiosqlite.Row → dataclass instances.

Pure transforms. No DB access. Imported by domain modules that need to
materialize query results into dataclasses.
"""

# [imports — include only what the four function bodies actually use]

# Function: _row_to_werkdag — copy VERBATIM from source lines 766-789 (approx).
def _row_to_werkdag(row) -> Werkdag:
    ...


# Function: _row_to_factuur — copy VERBATIM from source lines 791-806 (approx).
def _row_to_factuur(row) -> Factuur:
    ...


# Function: _row_to_uitgave — copy VERBATIM from source lines 808-820 (approx).
def _row_to_uitgave(row) -> Uitgave:
    ...


# Function: _row_to_fiscale_params — copy VERBATIM from source lines 1598-1666 (approx).
def _row_to_fiscale_params(row) -> FiscaleParams:
    ...
```

After pasting, run `python -c "from database.rows import _row_to_werkdag, _row_to_factuur, _row_to_uitgave, _row_to_fiscale_params; print('OK')"` to catch syntax errors.

- [ ] **Step 2: Remove the extracted helpers from `database/__init__.py`**

Delete the four `_row_to_*` function definitions. Add them to the re-export block:

```python
from database.rows import (
    _row_to_werkdag,
    _row_to_factuur,
    _row_to_uitgave,
    _row_to_fiscale_params,
)
```

The underscore-prefix re-exports preserve the existing private API for callers still inside `__init__.py`.

- [ ] **Step 3: Run the full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q`
Expected: `638 passed, 14 skipped`

- [ ] **Step 4: Commit**

```bash
git add database/rows.py database/__init__.py
git commit -m "refactor(database): extract row converters to rows.py

Moves _row_to_werkdag, _row_to_factuur, _row_to_uitgave, _row_to_fiscale_params
to database/rows.py. Pure transforms, no DB access."
```

---

## Task 4: Extract `database/schema.py`

**Goal:** Isolate schema/migration concerns. This is the largest extraction after the domain modules because SCHEMA_SQL alone is 200+ lines.

**Files:**
- Create: `database/schema.py`
- Modify: `database/__init__.py`

### What goes in schema.py

From `__init__.py`, cut and move:
1. `SCHEMA_SQL` constant (currently lines 56-260)
2. `MIGRATIONS` list (currently lines 295-419)
3. `_run_migration_7` (lines 422-436)
4. `_run_migration_8` (lines 439-462)
5. `_run_migration_18` (lines 465-504)
6. `_run_migration_20` (lines 507-540)
7. `_run_migration_21` (lines 543-561)
8. `_MIGRATION_CALLABLES` dict (line 564)
9. `init_db` function (lines 567-644)

### Imports schema.py needs

```python
import json  # _run_migration_8 uses json.dumps for arbeidskorting_brackets
from pathlib import Path
from database.core import DB_PATH, get_db_ctx, _get_existing_columns
```

### Lazy imports inside init_db

`init_db` calls `backfill_betalingskenmerken` and `backfill_betaallinks`. Those still live in `__init__.py` during this task. Use LAZY imports inside `init_db` so schema.py doesn't pull them at module load:

```python
async def init_db(db_path: Path = DB_PATH) -> None:
    # ... existing schema/migration logic ...

    # Backfills: lazy imports to avoid pulling banktransacties/facturen
    # at schema.py module load time (they import from core which we import).
    from database import backfill_betalingskenmerken, backfill_betaallinks
    await backfill_betalingskenmerken(db_path)
    await backfill_betaallinks(db_path)
```

Once tasks 9 (banktransacties) and 11 (facturen) complete, these lazy imports resolve to the extracted modules via the package re-exports. No further schema.py change needed.

- [ ] **Step 1: Create `database/schema.py`**

Structure:

```python
"""Database schema: DDL, migrations, init_db.

Owns SCHEMA_SQL and the ordered MIGRATIONS list. init_db is idempotent —
can be called on empty, partially-migrated, or up-to-date databases.
"""

import json
from pathlib import Path

from database.core import DB_PATH, get_db_ctx, _get_existing_columns

SCHEMA_SQL = """
[paste the exact multi-line SCHEMA_SQL string from __init__.py here]
"""

MIGRATIONS = [
    [paste the exact 25-entry MIGRATIONS list here]
]

# [paste _run_migration_7]
# [paste _run_migration_8]
# [paste _run_migration_18]
# [paste _run_migration_20]
# [paste _run_migration_21]

_MIGRATION_CALLABLES = {
    7: _run_migration_7,
    8: _run_migration_8,
    18: _run_migration_18,
    20: _run_migration_20,
    21: _run_migration_21,
}


async def init_db(db_path: Path = DB_PATH) -> None:
    # [paste the exact init_db body here, with backfill calls changed to lazy imports]
    ...
```

**CRITICAL:** Read the source file to copy `SCHEMA_SQL`, `MIGRATIONS`, and each `_run_migration_*` function exactly. Do not retype them. Copy-paste.

- [ ] **Step 2: Remove extracted content from `database/__init__.py`**

Delete: `SCHEMA_SQL`, `MIGRATIONS`, `_run_migration_7..21`, `_MIGRATION_CALLABLES`, `init_db`.

Add to the re-export block at the top:

```python
from database.schema import (
    init_db,
    SCHEMA_SQL,
    MIGRATIONS,
)
```

**`SCHEMA_SQL` re-export is MANDATORY** — `tests/test_aangifte.py:199,231` imports it directly via `from database import SCHEMA_SQL` to set up test fixtures that skip migrations. Removing it will break those tests.

`MIGRATIONS` is not imported externally today (verified via grep), but re-exporting it is a cheap, documentation-friendly choice — keep it.

The `_run_migration_*` functions and `_MIGRATION_CALLABLES` are internal to schema.py; no re-export needed.

- [ ] **Step 3: Verify `init_db` resolves backfills correctly**

Test the initialization path:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -c "
import asyncio
from database.schema import init_db
import tempfile, os
with tempfile.TemporaryDirectory() as td:
    os.environ['BOEKHOUDING_DB_DIR'] = td
    # re-import to pick up env
    import importlib, database.core
    importlib.reload(database.core)
    from pathlib import Path
    asyncio.run(init_db(Path(td) / 'test.sqlite3'))
    print('init_db OK')
"
```

Expected: `init_db OK`. The backfill lazy imports resolve via `from database import ...` which goes through `__init__.py` re-exports back to `__init__.py` (since those functions haven't been extracted yet). This is intentional.

- [ ] **Step 4: Run the full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q`
Expected: `638 passed, 14 skipped`

- [ ] **Step 5: Commit**

```bash
git add database/schema.py database/__init__.py
git commit -m "refactor(database): extract schema/migrations to schema.py

Moves SCHEMA_SQL, MIGRATIONS, _run_migration_*, init_db to
database/schema.py. backfill_* calls inside init_db use lazy imports
until those modules are extracted in later tasks."
```

---

## Task 5: Extract `database/bedrijf.py`

**Goal:** Smallest domain module — 2 functions. Establishes the extraction pattern for the remaining domain tasks.

**Files:**
- Create: `database/bedrijf.py`
- Modify: `database/__init__.py`

### What goes in bedrijf.py

From `__init__.py`, cut:
- `get_bedrijfsgegevens` (currently lines 665-678)
- `upsert_bedrijfsgegevens` (currently lines 681-694)

### Imports bedrijf.py needs

```python
from pathlib import Path

from database.core import DB_PATH, get_db_ctx
from models import Bedrijfsgegevens
```

- [ ] **Step 1: Create `database/bedrijf.py`**

Structure:

```python
"""Bedrijfsgegevens (company settings) CRUD."""

from pathlib import Path

from database.core import DB_PATH, get_db_ctx
from models import Bedrijfsgegevens


async def get_bedrijfsgegevens(db_path: Path = DB_PATH) -> Bedrijfsgegevens | None:
    # [paste exact function body from __init__.py]
    ...


async def upsert_bedrijfsgegevens(db_path: Path = DB_PATH, **kwargs) -> None:
    # [paste exact function body from __init__.py]
    ...
```

Copy the function bodies VERBATIM from `database/__init__.py`.

- [ ] **Step 2: Remove extracted functions from `database/__init__.py`**

Delete `get_bedrijfsgegevens` and `upsert_bedrijfsgegevens`.

Add to the re-export block:

```python
from database.bedrijf import (
    get_bedrijfsgegevens,
    upsert_bedrijfsgegevens,
)
```

- [ ] **Step 3: Run the full test suite**

Expected: `638 passed, 14 skipped`

- [ ] **Step 4: Commit**

```bash
git add database/bedrijf.py database/__init__.py
git commit -m "refactor(database): extract bedrijfsgegevens to bedrijf.py"
```

---

## Task 6: Extract `database/klanten.py`

**Goal:** Move customer CRUD + location CRUD into one module (both are about "parties in transactions").

**Files:**
- Create: `database/klanten.py`
- Modify: `database/__init__.py`

### What goes in klanten.py

From `__init__.py`, cut:
- `get_klanten` (lines 699-715)
- `add_klant` (lines 718-730)
- `update_klant` (lines 733-747)
- `delete_klant` (lines 750-761)
- `get_klant_locaties` (lines 2701-2711)
- `add_klant_locatie` (lines 2714-2722)
- `delete_klant_locatie` (lines 2725-2730)

### Imports klanten.py needs

```python
from pathlib import Path

from database.core import DB_PATH, get_db_ctx
from models import Klant, KlantLocatie
```

- [ ] **Step 1: Create `database/klanten.py`**

Copy the 7 function bodies verbatim. Order: klanten CRUD first (4 functions), then klant_locaties CRUD (3 functions). Include a section comment separating them:

```python
"""Klanten and klant_locaties CRUD."""

from pathlib import Path

from database.core import DB_PATH, get_db_ctx
from models import Klant, KlantLocatie


# ========== Klanten ==========

async def get_klanten(...): ...
async def add_klant(...): ...
async def update_klant(...): ...
async def delete_klant(...): ...


# ========== Klant locaties ==========

async def get_klant_locaties(...): ...
async def add_klant_locatie(...): ...
async def delete_klant_locatie(...): ...
```

- [ ] **Step 2: Remove extracted functions from `database/__init__.py`**

Delete the 7 functions from their current locations.

Add to the re-export block:

```python
from database.klanten import (
    get_klanten,
    add_klant,
    update_klant,
    delete_klant,
    get_klant_locaties,
    add_klant_locatie,
    delete_klant_locatie,
)
```

- [ ] **Step 3: Run the full test suite**

Expected: `638 passed, 14 skipped`

- [ ] **Step 4: Commit**

```bash
git add database/klanten.py database/__init__.py
git commit -m "refactor(database): extract klanten + klant_locaties to klanten.py"
```

---

## Task 7: Extract `database/werkdagen.py`

**Goal:** Move werkdagen (workday) CRUD.

**Files:**
- Create: `database/werkdagen.py`
- Modify: `database/__init__.py`

### What goes in werkdagen.py

From `__init__.py`, cut:
- `get_werkdagen` (lines 823-849)
- `add_werkdag` (lines 852-870)
- `update_werkdag` (lines 873-891)
- `delete_werkdag` (lines 894-905)
- `get_werkdagen_ongefactureerd` (lines 908-921)

### Imports werkdagen.py needs

```python
from pathlib import Path

from database.core import DB_PATH, get_db_ctx, _validate_datum
from database.rows import _row_to_werkdag
from models import Werkdag
```

- [ ] **Step 1: Create `database/werkdagen.py`**

Copy the 5 function bodies verbatim.

- [ ] **Step 2: Remove extracted functions from `database/__init__.py` and add re-exports**

Add:

```python
from database.werkdagen import (
    get_werkdagen,
    add_werkdag,
    update_werkdag,
    delete_werkdag,
    get_werkdagen_ongefactureerd,
)
```

- [ ] **Step 3: Run the full test suite**

Expected: `638 passed, 14 skipped`

- [ ] **Step 4: Commit**

```bash
git add database/werkdagen.py database/__init__.py
git commit -m "refactor(database): extract werkdagen CRUD to werkdagen.py"
```

---

## Task 8: Extract `database/uitgaven.py`

**Goal:** Move uitgaven (expenses) CRUD + afschrijving (depreciation) override CRUD.

**Files:**
- Create: `database/uitgaven.py`
- Modify: `database/__init__.py`

### What goes in uitgaven.py

From `__init__.py`, cut:
- `get_uitgaven` (lines 1179-1193)
- `add_uitgave` (lines 1196-1212)
- `update_uitgave` (lines 1215-1233)
- `delete_uitgave` (lines 1236-1246)
- `get_uitgaven_per_categorie` (lines 1249-1260)
- `get_investeringen` (lines 1263-1273)
- `get_investeringen_voor_afschrijving` (lines 2206-2216)
- `get_afschrijving_overrides` (lines 2221-2232)
- `get_afschrijving_overrides_batch` (lines 2235-2255)
- `set_afschrijving_override` (lines 2258-2269)
- `delete_afschrijving_override` (lines 2272-2280)

### Imports uitgaven.py needs

```python
from pathlib import Path

from database.core import DB_PATH, get_db_ctx, _validate_datum
from database.rows import _row_to_uitgave
from models import Uitgave
```

- [ ] **Step 1: Create `database/uitgaven.py`**

Copy the 11 function bodies verbatim. Order: uitgaven CRUD first, then investeringen queries, then afschrijving overrides. Use section comments:

```python
"""Uitgaven (expenses) and afschrijving (depreciation) overrides CRUD."""

# [imports]

# ========== Uitgaven ==========
# 6 functions

# ========== Investeringen ==========
# 1 function (get_investeringen_voor_afschrijving)

# ========== Afschrijving overrides ==========
# 4 functions
```

- [ ] **Step 2: Remove extracted functions from `database/__init__.py` and add re-exports**

Add:

```python
from database.uitgaven import (
    get_uitgaven,
    add_uitgave,
    update_uitgave,
    delete_uitgave,
    get_uitgaven_per_categorie,
    get_investeringen,
    get_investeringen_voor_afschrijving,
    get_afschrijving_overrides,
    get_afschrijving_overrides_batch,
    set_afschrijving_override,
    delete_afschrijving_override,
)
```

- [ ] **Step 3: Run the full test suite**

Expected: `638 passed, 14 skipped`

- [ ] **Step 4: Commit**

```bash
git add database/uitgaven.py database/__init__.py
git commit -m "refactor(database): extract uitgaven + afschrijvingen to uitgaven.py"
```

---

## Task 9: Extract `database/banktransacties.py`

**Goal:** Move bank transaction CRUD, category suggestions, VA/Belastingdienst queries, and the CSV backfill. Note: `get_belastingdienst_betalingen` lives at line 2601 (far from the main banktransacties section) but semantically belongs here.

**Files:**
- Create: `database/banktransacties.py`
- Modify: `database/__init__.py`

### What goes in banktransacties.py

From `__init__.py`, cut:
- `get_banktransacties` (lines 1278-1299)
- `get_imported_csv_bestanden` (lines 1302-1308)
- `add_banktransacties` (lines 1311-1359)
- `update_banktransactie` (lines 1362-1376)
- `get_categorie_suggestions` (lines 1379-1402)
- `delete_banktransacties` (lines 1405-1442)
- `get_va_betalingen` (lines 1448-1497)
- `backfill_betalingskenmerken` (lines 1500-1557)
- `get_belastingdienst_betalingen` (lines 2601-2615)

### Imports banktransacties.py needs

```python
from collections import Counter
from pathlib import Path

from database.core import DB_PATH, get_db_ctx, BELASTINGDIENST_IBAN
from models import Banktransactie
```

**IMPORTANT:** `backfill_betalingskenmerken` imports from `import_.rabobank_csv` inside its function body. Preserve that lazy import exactly — don't hoist it to the top of the file. Lazy imports inside functions are intentional to avoid hard import dependencies at module load.

- [ ] **Step 1: Create `database/banktransacties.py`**

Copy the 9 function bodies verbatim.

- [ ] **Step 2: Remove extracted functions from `database/__init__.py` and add re-exports**

Add:

```python
from database.banktransacties import (
    get_banktransacties,
    get_imported_csv_bestanden,
    add_banktransacties,
    update_banktransactie,
    get_categorie_suggestions,
    delete_banktransacties,
    get_va_betalingen,
    backfill_betalingskenmerken,
    get_belastingdienst_betalingen,
)
```

- [ ] **Step 3: Verify `init_db` still calls `backfill_betalingskenmerken` correctly**

The lazy import inside `init_db` (from Task 4) uses `from database import backfill_betalingskenmerken`. After this task, that resolves to the re-exported function in `__init__.py`, which resolves to the extracted module. Run:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -c "
import asyncio, tempfile, os
from pathlib import Path
with tempfile.TemporaryDirectory() as td:
    os.environ['BOEKHOUDING_DB_DIR'] = td
    import importlib, database.core
    importlib.reload(database.core)
    from database import init_db
    asyncio.run(init_db(Path(td) / 'test.sqlite3'))
    print('init_db + backfill_betalingskenmerken OK')
"
```

Expected: `init_db + backfill_betalingskenmerken OK`.

- [ ] **Step 4: Run the full test suite**

Expected: `638 passed, 14 skipped`

- [ ] **Step 5: Commit**

```bash
git add database/banktransacties.py database/__init__.py
git commit -m "refactor(database): extract banktransacties to banktransacties.py

Includes bank CRUD, categorie suggestions, VA/Belastingdienst queries,
and backfill_betalingskenmerken. get_belastingdienst_betalingen moved
from its far-away location (line 2601) to its semantic home."
```

---

## Task 10: Extract `database/facturen.py`

**Goal:** Move facturen CRUD, the `MatchProposal` dataclass, matching logic, and the `backfill_betaallinks` factuur backfill.

**Files:**
- Create: `database/facturen.py`
- Modify: `database/__init__.py`

### What goes in facturen.py

From `__init__.py`, cut:
- `MatchProposal` dataclass — the entire block starting at line 19 (`@dataclass` decorator) through line 48 (last field `alternatives: list = field(default_factory=list)`). Includes class docstring.
- All matching constants: `_MATCH_AMOUNT_TOL`, `_MATCH_NUMMER_TOL`, `_MATCH_DAYS_BEFORE`, `_MATCH_DAYS_AFTER` (lines 2353-2356)
- `get_facturen` (lines 926-938)
- `add_factuur` (lines 941-958)
- `get_next_factuurnummer` (lines 961-970)
- `factuurnummer_exists` (lines 973-979)
- `update_factuur_status` (lines 982-1008)
- `mark_betaald` (lines 1011-1015)
- `update_factuur` (lines 1018-1039)
- `delete_factuur` (lines 1042-1082)
- `link_werkdagen_to_factuur` (lines 1085-1097)
- `save_factuur_atomic` (lines 1100-1174)
- `get_openstaande_facturen` (lines 2025-2039)
- `_match_date_ok` (line 2359)
- `find_factuur_matches` (lines 2367-2527)
- `apply_factuur_matches` (lines 2530-2582)
- `backfill_betaallinks` (lines 1560-1593)

### Imports facturen.py needs

```python
from dataclasses import dataclass, field
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta
from pathlib import Path

from database.core import DB_PATH, get_db_ctx, _validate_datum
from database.rows import _row_to_factuur
from models import Factuur
```

**IMPORTANT:** `backfill_betaallinks` imports `cv2` inside its function body. Preserve that lazy import — do not hoist. Also preserve the `Path(os.environ.get(...))` pattern for resolving where QR PNGs live if that's inside the function.

- [ ] **Step 1: Create `database/facturen.py`**

Structure:

```python
"""Facturen CRUD, matching logic, and backfill_betaallinks.

MatchProposal lives here because it's exclusively produced by
find_factuur_matches and consumed by apply_factuur_matches.
"""

from dataclasses import dataclass, field
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta
from pathlib import Path

from database.core import DB_PATH, get_db_ctx, _validate_datum
from database.rows import _row_to_factuur
from models import Factuur


@dataclass
class MatchProposal:
    # [paste exact MatchProposal definition]
    ...


# ========== Facturen CRUD ==========

async def get_facturen(...): ...
async def add_factuur(...): ...
# ... 9 more ...


# ========== Matching ==========

_MATCH_AMOUNT_TOL = ...
_MATCH_NUMMER_TOL = ...
_MATCH_DAYS_BEFORE = ...
_MATCH_DAYS_AFTER = ...


def _match_date_ok(...): ...
async def find_factuur_matches(...): ...
async def apply_factuur_matches(...): ...


# ========== Backfills ==========

async def backfill_betaallinks(...): ...
```

Copy each function body and the MatchProposal definition VERBATIM.

- [ ] **Step 2: Remove extracted content from `database/__init__.py` and add re-exports**

Add:

```python
from database.facturen import (
    MatchProposal,
    get_facturen,
    add_factuur,
    get_next_factuurnummer,
    factuurnummer_exists,
    update_factuur_status,
    mark_betaald,
    update_factuur,
    delete_factuur,
    link_werkdagen_to_factuur,
    save_factuur_atomic,
    get_openstaande_facturen,
    find_factuur_matches,
    apply_factuur_matches,
    backfill_betaallinks,
)
```

- [ ] **Step 3: Verify `init_db` still calls `backfill_betaallinks` correctly**

Same test as Task 9's step 3 — run `init_db` in an isolated tempdir and confirm it completes without error.

- [ ] **Step 4: Run the full test suite**

Expected: `638 passed, 14 skipped`

- [ ] **Step 5: Commit**

```bash
git add database/facturen.py database/__init__.py
git commit -m "refactor(database): extract facturen + matching to facturen.py

Includes MatchProposal dataclass, facturen CRUD, find/apply matches
functions with their tolerance constants, and backfill_betaallinks."
```

---

## Task 11: Extract `database/fiscale_params.py`

**Goal:** Move the largest domain — fiscale_params (22 functions), aangifte_documenten (3), and snapshots (3).

**Files:**
- Create: `database/fiscale_params.py`
- Modify: `database/__init__.py`

### What goes in fiscale_params.py

From `__init__.py`, cut:
- `get_fiscale_params` (lines 1668-1674)
- `get_all_fiscale_params` (lines 1677-1681)
- `upsert_fiscale_params` (lines 1684-1826)
- `update_ib_inputs` (lines 1829-1846)
- `update_za_sa_toggles` (lines 1849-1861)
- `update_ew_naar_partner` (lines 1864-1875)
- `update_box3_fiscaal_partner` (lines 1878-1885)
- `update_box3_inputs` (lines 1888-1905)
- `update_partner_inputs` (lines 1908-1922)
- `update_balans_inputs` (lines 2618-2633)
- `update_jaarafsluiting_status` (lines 2636-2644)
- `get_aangifte_documenten` (lines 2285-2298)
- `add_aangifte_document` (lines 2301-2315)
- `delete_aangifte_document` (lines 2318-2324)
- `save_jaarafsluiting_snapshot` (lines 2647-2672)
- `load_jaarafsluiting_snapshot` (lines 2675-2690)
- `delete_jaarafsluiting_snapshot` (lines 2693-2695)

That's 17 functions total.

### Imports fiscale_params.py needs

```python
import json  # snapshots serialize/deserialize dict as JSON
from datetime import datetime as _datetime
from pathlib import Path

from database.core import DB_PATH, get_db_ctx
from database.rows import _row_to_fiscale_params
from models import FiscaleParams, AangifteDocument
```

- [ ] **Step 1: Create `database/fiscale_params.py`**

Structure with section comments:

```python
"""Fiscale params + aangifte documenten + jaarafsluiting snapshots.

All year-scoped configuration/data for the annual tax return workflow.
"""

# [imports]


# ========== Fiscale params ==========
# 11 functions: get/get_all/upsert + 8 update_* variants


# ========== Aangifte documenten ==========
# 3 functions


# ========== Snapshots ==========
# 3 functions (delete is a deliberate no-op)
```

Copy all 17 function bodies verbatim.

- [ ] **Step 2: Remove extracted functions from `database/__init__.py` and add re-exports**

Add:

```python
from database.fiscale_params import (
    get_fiscale_params,
    get_all_fiscale_params,
    upsert_fiscale_params,
    update_ib_inputs,
    update_za_sa_toggles,
    update_ew_naar_partner,
    update_box3_fiscaal_partner,
    update_box3_inputs,
    update_partner_inputs,
    update_balans_inputs,
    update_jaarafsluiting_status,
    get_aangifte_documenten,
    add_aangifte_document,
    delete_aangifte_document,
    save_jaarafsluiting_snapshot,
    load_jaarafsluiting_snapshot,
    delete_jaarafsluiting_snapshot,
)
```

- [ ] **Step 3: Run the full test suite**

Expected: `638 passed, 14 skipped`

- [ ] **Step 4: Commit**

```bash
git add database/fiscale_params.py database/__init__.py
git commit -m "refactor(database): extract fiscale_params + aangifte + snapshots

Largest single extraction (17 functions). All year-scoped tax-workflow
data and configuration lives here: fiscale_params CRUD and update
variants, aangifte_documenten CRUD, and jaarafsluiting snapshot I/O."
```

---

## Task 12: Extract `database/aggregations.py`

**Goal:** Move all dashboard aggregation queries and `get_health_alerts`. This is the final domain extraction.

**Files:**
- Create: `database/aggregations.py`
- Modify: `database/__init__.py`

### What goes in aggregations.py

From `__init__.py`, cut:
- `get_omzet_per_maand` (lines 1927-1939)
- `get_kpis` (lines 1942-1983)
- `get_kpis_tot_datum` (lines 1986-2006)
- `get_omzet_per_klant` (lines 2009-2022)
- `get_uren_totaal` (lines 2042-2050)
- `get_omzet_totaal` (lines 2053-2060)
- `get_data_counts` (lines 2063-2085)
- `get_representatie_totaal` (lines 2088-2095)
- `get_werkdagen_ongefactureerd_summary` (lines 2098-2110)
- `get_health_alerts` (lines 2113-2191)
- `get_km_totaal` (lines 2194-2203)
- `get_debiteuren_op_peildatum` (lines 2327-2350)
- `get_nog_te_factureren` (lines 2585-2598)

That's 13 functions.

### Imports aggregations.py needs

```python
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path

from database.core import DB_PATH, get_db_ctx
from database.fiscale_params import get_fiscale_params  # used by get_health_alerts
```

**Note on the cross-domain call:** `get_health_alerts` calls `get_fiscale_params`. This is a legitimate cross-domain dependency (aggregations depends on fiscale_params) — import it directly rather than via `from database import ...` to avoid touching `__init__.py` for internal resolution.

- [ ] **Step 1: Create `database/aggregations.py`**

Copy all 13 function bodies verbatim.

- [ ] **Step 2: Remove extracted functions from `database/__init__.py` and add re-exports**

Add:

```python
from database.aggregations import (
    get_omzet_per_maand,
    get_kpis,
    get_kpis_tot_datum,
    get_omzet_per_klant,
    get_uren_totaal,
    get_omzet_totaal,
    get_data_counts,
    get_representatie_totaal,
    get_werkdagen_ongefactureerd_summary,
    get_health_alerts,
    get_km_totaal,
    get_debiteuren_op_peildatum,
    get_nog_te_factureren,
)
```

- [ ] **Step 3: Run the full test suite**

Expected: `638 passed, 14 skipped`

- [ ] **Step 4: Commit**

```bash
git add database/aggregations.py database/__init__.py
git commit -m "refactor(database): extract aggregation queries to aggregations.py

Final domain extraction: 13 dashboard/reporting queries including
get_health_alerts. Depends on fiscale_params module for get_fiscale_params."
```

---

## Task 13: Final cleanup and verification

**Goal:** Ensure `database/__init__.py` is now a thin re-export layer with no dead code. Verify the full public API is preserved. Clean up any module-level code that shouldn't be there.

**Files:**
- Modify: `database/__init__.py`

- [ ] **Step 1: Inspect `database/__init__.py`**

Read the current state. It should contain ONLY:
- A module docstring
- Re-export blocks (`from database.X import ...`)
- Possibly an `__all__` list (optional but nice for documentation)

If there is any remaining code — function definitions, assignments other than re-exports, etc. — investigate and move it to the appropriate module. Report via BLOCKED status if you find something that doesn't fit any extracted module.

- [ ] **Step 2: Rewrite `database/__init__.py` as a clean re-export layer**

The final file should look like:

```python
"""Database package.

All public database functions are importable directly from `database`:

    from database import DB_PATH, get_db_ctx, get_facturen

Internally the package is organized into focused submodules by domain:
    core, schema, rows, bedrijf, klanten, werkdagen, uitgaven,
    banktransacties, facturen, fiscale_params, aggregations.

Import from submodules only within the database package itself (to
avoid circular imports via this __init__). External callers should
always import from `database` directly.
"""

from database.core import (
    DB_PATH,
    get_db,
    get_db_ctx,
    _validate_datum,
    _get_existing_columns,
    BELASTINGDIENST_IBAN,
)
from database.schema import (
    init_db,
    SCHEMA_SQL,
    MIGRATIONS,
)
from database.rows import (
    _row_to_werkdag,
    _row_to_factuur,
    _row_to_uitgave,
    _row_to_fiscale_params,
)
from database.bedrijf import (
    get_bedrijfsgegevens,
    upsert_bedrijfsgegevens,
)
from database.klanten import (
    get_klanten,
    add_klant,
    update_klant,
    delete_klant,
    get_klant_locaties,
    add_klant_locatie,
    delete_klant_locatie,
)
from database.werkdagen import (
    get_werkdagen,
    add_werkdag,
    update_werkdag,
    delete_werkdag,
    get_werkdagen_ongefactureerd,
)
from database.uitgaven import (
    get_uitgaven,
    add_uitgave,
    update_uitgave,
    delete_uitgave,
    get_uitgaven_per_categorie,
    get_investeringen,
    get_investeringen_voor_afschrijving,
    get_afschrijving_overrides,
    get_afschrijving_overrides_batch,
    set_afschrijving_override,
    delete_afschrijving_override,
)
from database.banktransacties import (
    get_banktransacties,
    get_imported_csv_bestanden,
    add_banktransacties,
    update_banktransactie,
    get_categorie_suggestions,
    delete_banktransacties,
    get_va_betalingen,
    backfill_betalingskenmerken,
    get_belastingdienst_betalingen,
)
from database.facturen import (
    MatchProposal,
    get_facturen,
    add_factuur,
    get_next_factuurnummer,
    factuurnummer_exists,
    update_factuur_status,
    mark_betaald,
    update_factuur,
    delete_factuur,
    link_werkdagen_to_factuur,
    save_factuur_atomic,
    get_openstaande_facturen,
    find_factuur_matches,
    apply_factuur_matches,
    backfill_betaallinks,
)
from database.fiscale_params import (
    get_fiscale_params,
    get_all_fiscale_params,
    upsert_fiscale_params,
    update_ib_inputs,
    update_za_sa_toggles,
    update_ew_naar_partner,
    update_box3_fiscaal_partner,
    update_box3_inputs,
    update_partner_inputs,
    update_balans_inputs,
    update_jaarafsluiting_status,
    get_aangifte_documenten,
    add_aangifte_document,
    delete_aangifte_document,
    save_jaarafsluiting_snapshot,
    load_jaarafsluiting_snapshot,
    delete_jaarafsluiting_snapshot,
)
from database.aggregations import (
    get_omzet_per_maand,
    get_kpis,
    get_kpis_tot_datum,
    get_omzet_per_klant,
    get_uren_totaal,
    get_omzet_totaal,
    get_data_counts,
    get_representatie_totaal,
    get_werkdagen_ongefactureerd_summary,
    get_health_alerts,
    get_km_totaal,
    get_debiteuren_op_peildatum,
    get_nog_te_factureren,
)
```

**Note:** Do NOT add `__all__` — it can create drift. The `from X import ...` lines already declare the public surface.

**`SCHEMA_SQL` is required** (imported by `tests/test_aangifte.py:199,231`). `MIGRATIONS` is optional but cheap to keep.

- [ ] **Step 3: Verify the fix with a comprehensive import check**

Run this script to confirm every expected name is importable:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -c "
import database as db
required = [
    'DB_PATH', 'get_db', 'get_db_ctx', 'init_db', 'MatchProposal',
    'get_bedrijfsgegevens', 'upsert_bedrijfsgegevens',
    'get_klanten', 'add_klant', 'update_klant', 'delete_klant',
    'get_klant_locaties', 'add_klant_locatie', 'delete_klant_locatie',
    'get_werkdagen', 'add_werkdag', 'update_werkdag', 'delete_werkdag',
    'get_werkdagen_ongefactureerd',
    'get_facturen', 'add_factuur', 'get_next_factuurnummer',
    'factuurnummer_exists', 'update_factuur_status', 'mark_betaald',
    'update_factuur', 'delete_factuur', 'link_werkdagen_to_factuur',
    'save_factuur_atomic', 'get_openstaande_facturen',
    'find_factuur_matches', 'apply_factuur_matches', 'backfill_betaallinks',
    'get_uitgaven', 'add_uitgave', 'update_uitgave', 'delete_uitgave',
    'get_uitgaven_per_categorie', 'get_investeringen',
    'get_investeringen_voor_afschrijving',
    'get_afschrijving_overrides', 'get_afschrijving_overrides_batch',
    'set_afschrijving_override', 'delete_afschrijving_override',
    'get_banktransacties', 'get_imported_csv_bestanden',
    'add_banktransacties', 'update_banktransactie',
    'get_categorie_suggestions', 'delete_banktransacties',
    'get_va_betalingen', 'backfill_betalingskenmerken',
    'get_belastingdienst_betalingen',
    'get_fiscale_params', 'get_all_fiscale_params', 'upsert_fiscale_params',
    'update_ib_inputs', 'update_za_sa_toggles', 'update_ew_naar_partner',
    'update_box3_fiscaal_partner', 'update_box3_inputs',
    'update_partner_inputs', 'update_balans_inputs',
    'update_jaarafsluiting_status',
    'get_aangifte_documenten', 'add_aangifte_document',
    'delete_aangifte_document',
    'save_jaarafsluiting_snapshot', 'load_jaarafsluiting_snapshot',
    'delete_jaarafsluiting_snapshot',
    'get_omzet_per_maand', 'get_kpis', 'get_kpis_tot_datum',
    'get_omzet_per_klant', 'get_uren_totaal', 'get_omzet_totaal',
    'get_data_counts', 'get_representatie_totaal',
    'get_werkdagen_ongefactureerd_summary', 'get_health_alerts',
    'get_km_totaal', 'get_debiteuren_op_peildatum', 'get_nog_te_factureren',
]
missing = [n for n in required if not hasattr(db, n)]
assert not missing, f'Missing from database: {missing}'
print(f'Import check OK: {len(required)} names importable from database')
"
```

Expected: `Import check OK: 85 names importable from database` (or similar count).

- [ ] **Step 4: Measure the line-count improvement**

Run: `wc -l database/*.py`

Expected (approximate — exact sizes depend on how the source is structured):
- `database/__init__.py`: ~100 lines (just re-exports)
- `database/core.py`: ~50 lines
- `database/schema.py`: ~400 lines (SCHEMA_SQL is ~200 of those)
- `database/rows.py`: ~100 lines
- `database/bedrijf.py`: ~30 lines
- `database/klanten.py`: ~70 lines
- `database/werkdagen.py`: ~100 lines
- `database/uitgaven.py`: ~150 lines
- `database/banktransacties.py`: ~300 lines
- `database/facturen.py`: ~500 lines (largest due to matching logic)
- `database/fiscale_params.py`: ~400 lines (largest domain)
- `database/aggregations.py`: ~250 lines

**Total:** ~2450 lines across 12 files vs. 2730 in one file. The small reduction comes from removed duplication (e.g., cross-section imports no longer need to repeat). No file is larger than ~500 lines.

- [ ] **Step 5: Run the full test suite one final time**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: `638 passed, 14 skipped`

- [ ] **Step 6: Start the app and verify it runs**

```bash
source .venv/bin/activate
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py
```

Expected: the NiceGUI server starts on `http://127.0.0.1:8085` and the dashboard loads without errors. Click through to: `/werkdagen`, `/facturen`, `/bank`, `/kosten`, `/aangifte`, `/instellingen`, `/jaarafsluiting`. Each page should load and display data normally.

Stop the server (Ctrl+C).

- [ ] **Step 7: Commit the final cleanup**

```bash
git add database/__init__.py
git commit -m "refactor(database): finalize __init__.py as thin re-export layer

All 85 public names re-exported from domain submodules. __init__.py
now contains only the package docstring and re-export blocks. Largest
submodule is ~500 lines; none exceed the 600-line soft threshold.

Refactor complete: from 2730-line monolith to 12-file package with
clear domain boundaries and zero behavior changes."
```

---

## Rollback plan

Each task is a single commit. If a regression surfaces at any point:

- **During the refactor:** `git reset --hard HEAD~1` reverts the last task. Each task leaves the codebase in a green state, so reverting one task still leaves a working app.
- **After full completion:** `git revert <task-commit-sha>` for an individual task, then re-run tests. The re-export layer in `__init__.py` means most revertions don't cascade — the function moves back to `__init__.py` and callers keep working.
- **Nuclear option:** revert all 13 commits: `git revert --no-commit <first-task-sha>..HEAD && git commit -m "revert: database package refactor"`.

---

## Success criteria

- [ ] All 638 tests pass unchanged
- [ ] `python main.py` starts the app and all pages load
- [ ] No file in `database/` exceeds ~600 lines
- [ ] `database/__init__.py` is ≤ ~120 lines (docstring + re-exports)
- [ ] Every import site in the repo (`pages/*`, `components/*`, `tests/*`, `main.py`, etc.) continues to work without modification
- [ ] Public API of `database` (~85 names) is preserved — verified via the import-check script in Task 13 step 3
- [ ] `MatchProposal` is importable as `from database import MatchProposal`
- [ ] `init_db()` completes successfully and runs all backfills
- [ ] Each of the 13 commits has a clear, scoped message explaining one domain's extraction
