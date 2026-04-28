# User-Config Architectuur Implementation Plan (v3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move user-specific data (klant aliases + personal skip-words for PDF parser) from gitignored `*_local.py` files in the repo directory to SQLite, so the repo can safely become public again without losing functionality on re-clone.

**Architecture:** New `klant_aliases` table (FK to `klanten`, ON DELETE CASCADE, schema migration 33 + data migration 34 with JSON-fallback). `derive_skip_words(bg)` derives header-skip tokens at runtime from the existing `bedrijfsgegevens` row. Resolution flow becomes async-DB based with auto-learn alias UI in `/klanten` (via `components/shared_ui.py:open_klant_dialog`) and per-row remember-checkbox in the `/facturen` import-preview.

**Tech Stack:** Python 3.12, NiceGUI 3.0, aiosqlite, pytest-asyncio (`asyncio_mode = auto`), WeasyPrint, pywebview.

**Reference spec:** `docs/superpowers/specs/2026-04-28-user-config-architecture-design.md` (commit 9928aac, post-codex round 6 GROEN).

**Plan-review history:**
- v1 → codex review-1 → 7 must-fixes
- v2 → 7 verwerkt; codex review-2 → 2 blockers + 3 majors
- v3 → blockers + majors verwerkt: testbare helpers (`_get_local_aliases` / `_get_json_aliases`) zodat JSON-fallback echt geïsoleerd te testen is; `parse_anw_text` ongewijzigd (heeft eigen extractor, geen `skip_words` param); rollback-pad in Task 13 via JSON-snapshot i.p.v. git history; auto-learn confirm-loop geëxtraheerd als testbare helper; TDD-volgorde overal: failing test in step 1.

**Phasing:**
- **Phase 1 (Tasks 1-7)** — foundation: schema + helpers + parser/resolver refactor + tests + Klant16-scrub. Every commit is fully green.
- **Phase 2 (Tasks 8-15)** — UI + cleanup: auto-learn flow, alias-CRUD UI, audit, public-safe verify, _local.py cleanup, push.

---

## Phase 1 — Foundation

### Task 1: Add `klant_aliases` table (schema migration 33)

**Files:**
- Modify: `database.py` — extend `SCHEMA_SQL` and `MIGRATIONS`
- Create: `tests/test_klant_aliases.py`

- [ ] **Step 1: Write failing tests for the schema constraints**

```python
# tests/test_klant_aliases.py
"""Schema tests for klant_aliases (migration 33)."""

import pytest
import aiosqlite
from database import add_klant, get_db_ctx


@pytest.fixture
async def db_with_klanten(db):
    k1 = await add_klant(db, naam='Klant Alpha', tarief_uur=100.0)
    k2 = await add_klant(db, naam='Klant Beta', tarief_uur=100.0)
    return db, k1, k2


async def test_klant_aliases_table_exists(db):
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='klant_aliases'")
        row = await cur.fetchone()
    assert row is not None


async def test_unique_type_pattern(db_with_klanten):
    db, k1, k2 = db_with_klanten
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
            (k1,))
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
                (k2,))


async def test_unique_is_case_insensitive(db_with_klanten):
    db, k1, k2 = db_with_klanten
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
            (k1,))
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'foo bv')",
                (k2,))


async def test_pattern_min_length_3(db_with_klanten):
    db, k1, _ = db_with_klanten
    async with get_db_ctx(db) as conn:
        for short in ('', '  ', 'a', 'ab', '  ab '):
            with pytest.raises(aiosqlite.IntegrityError):
                await conn.execute(
                    "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', ?)",
                    (k1, short))


async def test_type_check_constraint(db_with_klanten):
    db, k1, _ = db_with_klanten
    async with get_db_ctx(db) as conn:
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'invalid_type', 'Foo BV')",
                (k1,))


async def test_cascade_delete_on_klant_removal(db_with_klanten):
    db, k1, _ = db_with_klanten
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
            (k1,))
        await conn.commit()
        await conn.execute("DELETE FROM klanten WHERE id = ?", (k1,))
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM klant_aliases WHERE klant_id = ?", (k1,))
        cnt = (await cur.fetchone())[0]
    assert cnt == 0


async def test_index_exists(db):
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_klant_aliases_lookup'")
        row = await cur.fetchone()
    assert row is not None
```

- [ ] **Step 2: Run tests, expect FAIL (table does not exist)**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_klant_aliases.py -v
```
Expected: 7 fails. Two with assertion-fail (table-not-found returns None → fail assertion), the others with `OperationalError: no such table`.

- [ ] **Step 3: Add CREATE TABLE to SCHEMA_SQL**

In `database.py`, find `SCHEMA_SQL = """` (line ~93) and locate the closing `"""` of that constant. Insert just **before** the closing `"""`:

```sql

CREATE TABLE IF NOT EXISTS klant_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    klant_id INTEGER NOT NULL REFERENCES klanten(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('suffix', 'pdf_text', 'anw_filename')),
    pattern TEXT NOT NULL COLLATE NOCASE
        CHECK (length(trim(pattern)) >= 3),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (type, pattern)
);
CREATE INDEX IF NOT EXISTS idx_klant_aliases_lookup
    ON klant_aliases(type, pattern);
```

- [ ] **Step 4: Add migration 33 to MIGRATIONS list**

In `database.py`, append to `MIGRATIONS` list (right after the `(32, ...)` entry, before the closing `]`):

```python
    (33, "add_klant_aliases_table", [
        """CREATE TABLE IF NOT EXISTS klant_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            klant_id INTEGER NOT NULL REFERENCES klanten(id) ON DELETE CASCADE,
            type TEXT NOT NULL CHECK (type IN ('suffix', 'pdf_text', 'anw_filename')),
            pattern TEXT NOT NULL COLLATE NOCASE
                CHECK (length(trim(pattern)) >= 3),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (type, pattern)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_klant_aliases_lookup ON klant_aliases(type, pattern)",
    ]),
```

- [ ] **Step 5: Run tests, expect 7 PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_klant_aliases.py -v
```

- [ ] **Step 6: Run full suite to confirm no regression**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 7: Commit**

```bash
git add database.py tests/test_klant_aliases.py
git commit -m "feat(db): add klant_aliases table (migration 33)"
```

---

### Task 2: Migration 34 — seed klant_aliases from local module + JSON fallback

**Files:**
- Modify: `database.py` — add `_seed_klant_aliases_from_local`; register in MIGRATIONS + `_MIGRATION_CALLABLES` (note the underscore prefix)
- Modify: `tests/test_klant_aliases.py` — add migration tests

- [ ] **Step 1: Write failing tests**

Append to `tests/test_klant_aliases.py`:

```python
import sys
import json
from types import SimpleNamespace


async def test_migration_34_no_op_when_no_source(db, monkeypatch, tmp_path):
    """Fresh install: no local module, no JSON file → no-op."""
    monkeypatch.delitem(sys.modules, 'import_.klant_mapping_local', raising=False)
    monkeypatch.setenv('BOEKHOUDING_CONFIG_DIR', str(tmp_path))
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM klant_aliases")
        before = (await cur.fetchone())[0]
    from database import _seed_klant_aliases_from_local
    async with get_db_ctx(db) as conn:
        await _seed_klant_aliases_from_local(conn)
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM klant_aliases")
        after = (await cur.fetchone())[0]
    assert before == 0 and after == 0


async def test_migration_34_uses_module_source_when_returned(db, monkeypatch):
    """If `_get_local_module_aliases` returns rows, those are used."""
    k1 = await add_klant(db, naam='HAP K14', tarief_uur=100.0)
    import database as dbm
    monkeypatch.setattr(dbm, '_get_local_module_aliases', lambda: [
        ('HAP K14', 'suffix', 'Winsum'),
        ('HAP K14', 'suffix', 'XX'),  # < 3 chars → must be skipped
        ('HAP K14', 'pdf_text', 'Centrum K14'),
        ('Klant Niet In DB', 'pdf_text', 'GHOST'),  # klant absent → skipped
        ('HAP K14', 'anw_filename', 'DDG'),
    ])
    monkeypatch.setattr(dbm, '_get_json_snapshot_aliases', lambda: None)

    from database import _seed_klant_aliases_from_local
    async with get_db_ctx(db) as conn:
        await _seed_klant_aliases_from_local(conn)
        await conn.commit()
        cur = await conn.execute(
            "SELECT type, pattern FROM klant_aliases ORDER BY type, pattern")
        rows = [(r[0], r[1]) for r in await cur.fetchall()]
    assert ('anw_filename', 'DDG') in rows
    assert ('pdf_text', 'Centrum K14') in rows
    assert ('suffix', 'Winsum') in rows
    assert ('suffix', 'XX') not in rows
    assert ('pdf_text', 'GHOST') not in rows


async def test_migration_34_falls_back_to_json_when_module_returns_none(db, monkeypatch):
    """When `_get_local_module_aliases` returns None, JSON snapshot is used."""
    k1 = await add_klant(db, naam='HAP K14', tarief_uur=100.0)
    import database as dbm
    monkeypatch.setattr(dbm, '_get_local_module_aliases', lambda: None)
    monkeypatch.setattr(dbm, '_get_json_snapshot_aliases', lambda: [
        ('HAP K14', 'pdf_text', 'Centrum K14'),
        ('HAP K14', 'suffix', 'Winsum'),
    ])
    from database import _seed_klant_aliases_from_local
    async with get_db_ctx(db) as conn:
        await _seed_klant_aliases_from_local(conn)
        await conn.commit()
        cur = await conn.execute(
            "SELECT type, pattern FROM klant_aliases ORDER BY type")
        rows = [(r[0], r[1]) for r in await cur.fetchall()]
    assert ('pdf_text', 'Centrum K14') in rows
    assert ('suffix', 'Winsum') in rows


async def test_migration_34_no_op_when_both_sources_empty(db, monkeypatch):
    """No source available → no-op."""
    import database as dbm
    monkeypatch.setattr(dbm, '_get_local_module_aliases', lambda: None)
    monkeypatch.setattr(dbm, '_get_json_snapshot_aliases', lambda: None)
    from database import _seed_klant_aliases_from_local
    async with get_db_ctx(db) as conn:
        await _seed_klant_aliases_from_local(conn)
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM klant_aliases")
        cnt = (await cur.fetchone())[0]
    assert cnt == 0


async def test_migration_34_idempotent(db, monkeypatch):
    """Running migration 34 twice does not duplicate."""
    k1 = await add_klant(db, naam='HAP K14', tarief_uur=100.0)
    import database as dbm
    monkeypatch.setattr(dbm, '_get_local_module_aliases', lambda: [
        ('HAP K14', 'suffix', 'Winsum'),
    ])
    monkeypatch.setattr(dbm, '_get_json_snapshot_aliases', lambda: None)
    from database import _seed_klant_aliases_from_local
    async with get_db_ctx(db) as conn:
        await _seed_klant_aliases_from_local(conn)
        await _seed_klant_aliases_from_local(conn)
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM klant_aliases")
        cnt = (await cur.fetchone())[0]
    assert cnt == 1


def test_get_json_snapshot_aliases_reads_file(tmp_path, monkeypatch):
    """Pure-function test for the JSON loader."""
    import json
    from database import _get_json_snapshot_aliases
    monkeypatch.setenv('BOEKHOUDING_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'klant_aliases_backup.json').write_text(json.dumps([
        {'klant_naam': 'A', 'type': 'pdf_text', 'pattern': 'PA'},
        {'klant_naam': 'B', 'type': 'suffix', 'pattern': 'PB'},
    ]))
    rows = _get_json_snapshot_aliases()
    assert rows == [('A', 'pdf_text', 'PA'), ('B', 'suffix', 'PB')]


def test_get_json_snapshot_aliases_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv('BOEKHOUDING_CONFIG_DIR', str(tmp_path))
    from database import _get_json_snapshot_aliases
    assert _get_json_snapshot_aliases() is None
```

- [ ] **Step 2: Run, expect ImportError**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_klant_aliases.py::test_migration_34_no_op_when_no_source -v
```

- [ ] **Step 3: Implement migration 34 — testbare helpers + thin orchestrator**

Codex round-2 finding 2: testing the JSON-fallback path is impossible if `klant_mapping_local.py` exists on disk because `monkeypatch.delitem` only clears the module cache; subsequent import re-loads from file. Solution: split into 2 testable helpers + 1 orchestrator.

Add in `database.py` near other migration callables (find `async def _run_migration_27`):

```python
def _get_local_module_aliases() -> list[tuple[str, str, str]] | None:
    """Return [(klant_naam, type, pattern), ...] from klant_mapping_local.py
    or None if the module is not importable."""
    try:
        from import_ import klant_mapping_local as src
    except ImportError:
        return None
    rows: list[tuple[str, str, str]] = []
    for type_name, source_dict in (
        ('suffix', getattr(src, 'SUFFIX_TO_KLANT', {})),
        ('pdf_text', getattr(src, 'PDF_KLANT_TO_DB', {})),
        ('anw_filename', getattr(src, 'ANW_FILENAME_TO_KLANT', {})),
    ):
        for pattern, klant_naam in source_dict.items():
            rows.append((klant_naam, type_name, pattern))
    return rows


def _get_json_snapshot_aliases() -> list[tuple[str, str, str]] | None:
    """Return [(klant_naam, type, pattern), ...] from
    `~/Library/Application Support/Boekhouding/config/klant_aliases_backup.json`
    (override via BOEKHOUDING_CONFIG_DIR env-var); None if file absent or invalid."""
    import os, json
    from pathlib import Path
    config_dir = os.environ.get('BOEKHOUDING_CONFIG_DIR')
    if config_dir:
        json_path = Path(config_dir) / 'klant_aliases_backup.json'
    else:
        json_path = (Path.home() / 'Library' / 'Application Support'
                     / 'Boekhouding' / 'config' / 'klant_aliases_backup.json')
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    rows: list[tuple[str, str, str]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        kn = entry.get('klant_naam')
        tn = entry.get('type')
        pt = entry.get('pattern')
        if kn and tn and pt:
            rows.append((kn, tn, pt))
    return rows


async def _seed_klant_aliases_from_local(conn) -> None:
    """Migration 34 callable: seed klant_aliases.

    Source priority:
      1. `klant_mapping_local.py` module (testable via `_get_local_module_aliases`)
      2. JSON snapshot in user config dir (testable via `_get_json_snapshot_aliases`)
      3. otherwise no-op

    Idempotent (INSERT OR IGNORE).
    Caller (migration runner) handles commit + version bump — do NOT call
    conn.commit() inside this function.
    """
    rows_to_insert = _get_local_module_aliases()
    if rows_to_insert is None:
        rows_to_insert = _get_json_snapshot_aliases()
    if not rows_to_insert:
        return

    prev_factory = conn.row_factory
    conn.row_factory = aiosqlite.Row
    try:
        cur = await conn.execute("SELECT id, naam FROM klanten")
        klant_id_by_naam = {r['naam']: r['id'] for r in await cur.fetchall()}
    finally:
        conn.row_factory = prev_factory

    for klant_naam, type_name, pattern in rows_to_insert:
        klant_id = klant_id_by_naam.get(klant_naam)
        if not klant_id or len((pattern or '').strip()) < 3:
            continue
        await conn.execute(
            "INSERT OR IGNORE INTO klant_aliases (klant_id, type, pattern) "
            "VALUES (?, ?, ?)",
            (klant_id, type_name, pattern.strip()))
```

- [ ] **Step 4: Register migration 34**

Find `_MIGRATION_CALLABLES = {` (in `database.py`) — note the **leading underscore**. Add the entry:

```python
_MIGRATION_CALLABLES = {7: _run_migration_7, 8: _run_migration_8, 18: _run_migration_18, 20: _run_migration_20, 21: _run_migration_21, 27: _run_migration_27, 34: _seed_klant_aliases_from_local}
```

And in `MIGRATIONS` list, after `(33, ...)`:

```python
    (34, "seed_klant_aliases_from_local_if_present", None),
```

- [ ] **Step 5: Run tests, expect PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_klant_aliases.py -v
```
Expected: 13 PASS (7 from Task 1 + 6 new).

- [ ] **Step 6: Confirm full suite green**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 7: Commit**

```bash
git add database.py tests/test_klant_aliases.py
git commit -m "feat(db): migration 34 — seed klant_aliases (module + JSON fallback)"
```

---

### Task 3: DB helpers (CRUD + auto-learn `remember_alias`)

**Files:**
- Modify: `database.py` — add 5 helpers near other klant CRUD
- Create: `tests/test_klant_alias_helpers.py`

- [ ] **Step 1: Write failing tests for all 5 helpers**

```python
# tests/test_klant_alias_helpers.py
"""Tests for klant_aliases CRUD + auto-learn helpers."""

import pytest
import aiosqlite
from database import (
    add_klant, get_db_ctx,
    get_klant_aliases, add_klant_alias,
    delete_klant_alias, update_klant_alias_target,
    remember_alias,
)


@pytest.fixture
async def db_two(db):
    k1 = await add_klant(db, naam='Klant Alpha', tarief_uur=100.0)
    k2 = await add_klant(db, naam='Klant Beta', tarief_uur=100.0)
    return db, k1, k2


# --- get / add / delete ---

async def test_add_klant_alias_inserts_row(db_two):
    db, k1, _ = db_two
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Centrum K14')
    assert aid > 0
    rows = await get_klant_aliases(db, k1)
    assert len(rows) == 1 and rows[0]['pattern'] == 'Centrum K14'


async def test_add_klant_alias_unique_violation(db_two):
    db, k1, k2 = db_two
    await add_klant_alias(db, k1, 'pdf_text', 'Centrum K14')
    with pytest.raises(aiosqlite.IntegrityError):
        await add_klant_alias(db, k2, 'pdf_text', 'Centrum K14')


async def test_add_klant_alias_short_pattern_rejected(db_two):
    db, k1, _ = db_two
    with pytest.raises(aiosqlite.IntegrityError):
        await add_klant_alias(db, k1, 'pdf_text', 'AB')


async def test_get_klant_aliases_filters_by_klant(db_two):
    db, k1, k2 = db_two
    await add_klant_alias(db, k1, 'pdf_text', 'Foo One')
    await add_klant_alias(db, k2, 'pdf_text', 'Foo Two')
    r1 = await get_klant_aliases(db, k1)
    r2 = await get_klant_aliases(db, k2)
    assert r1[0]['pattern'] == 'Foo One' and r2[0]['pattern'] == 'Foo Two'


async def test_delete_klant_alias_removes_row(db_two):
    db, k1, _ = db_two
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')
    assert await delete_klant_alias(db, aid) is True
    assert await get_klant_aliases(db, k1) == []


async def test_delete_klant_alias_unknown_id_returns_false(db_two):
    db, _, _ = db_two
    assert await delete_klant_alias(db, 99999) is False


# --- optimistic lock ---

async def test_update_klant_alias_target_success(db_two):
    db, k1, k2 = db_two
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')
    assert await update_klant_alias_target(db, aid, k1, k2) is True
    assert (await get_klant_aliases(db, k2))[0]['pattern'] == 'Foo BV'


async def test_update_klant_alias_target_stale(db_two):
    db, k1, k2 = db_two
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')
    assert await update_klant_alias_target(db, aid, 99999, k2) is False
    assert (await get_klant_aliases(db, k1))[0]['pattern'] == 'Foo BV'


# --- remember_alias (auto-learn) ---

async def test_remember_alias_inserts_new(db_two):
    db, k1, _ = db_two
    r = await remember_alias(db, k1, 'Some PDF Header', 'Suffix1')
    assert r == {'inserted': 2, 'already_correct': 0, 'conflicts': []}


async def test_remember_alias_idempotent_same_klant(db_two):
    db, k1, _ = db_two
    await remember_alias(db, k1, 'Foo BV', None)
    r = await remember_alias(db, k1, 'Foo BV', None)
    assert r == {'inserted': 0, 'already_correct': 1, 'conflicts': []}


async def test_remember_alias_conflict_detected(db_two):
    db, k1, k2 = db_two
    await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')
    r = await remember_alias(db, k2, 'Foo BV', None)
    assert r['inserted'] == 0
    assert len(r['conflicts']) == 1
    c = r['conflicts'][0]
    assert c['type'] == 'pdf_text'
    assert c['pattern'] == 'Foo BV'
    assert c['existing_klant_naam'] == 'Klant Alpha'
    assert c['existing_klant_id'] == k1


async def test_remember_alias_short_pattern_skipped(db_two):
    db, k1, _ = db_two
    r = await remember_alias(db, k1, 'AB', '12')
    assert r == {'inserted': 0, 'already_correct': 0, 'conflicts': []}


async def test_remember_alias_partial_conflict(db_two):
    db, k1, k2 = db_two
    await add_klant_alias(db, k1, 'suffix', 'OldSuffix')
    r = await remember_alias(db, k2, 'New PDF Name', 'OldSuffix')
    assert r['inserted'] == 1
    assert len(r['conflicts']) == 1
```

- [ ] **Step 2: Run tests, expect ImportError on the helpers**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_klant_alias_helpers.py -v
```

- [ ] **Step 3: Implement helpers in database.py**

Find `async def add_klant_locatie` (search for it; around line 3596) and add **after** the locatie-helpers group:

```python
async def get_klant_aliases(db_path: Path = DB_PATH,
                             klant_id: int | None = None) -> list[dict]:
    """Return aliases for one klant (newest first), or all if klant_id is None."""
    async with get_db_ctx(db_path) as conn:
        if klant_id is None:
            cur = await conn.execute(
                "SELECT id, klant_id, type, pattern, created_at FROM klant_aliases "
                "ORDER BY created_at DESC, id DESC")
        else:
            cur = await conn.execute(
                "SELECT id, klant_id, type, pattern, created_at FROM klant_aliases "
                "WHERE klant_id = ? ORDER BY created_at DESC, id DESC",
                (klant_id,))
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def add_klant_alias(db_path: Path, klant_id: int,
                           type_name: str, pattern: str) -> int:
    """Insert alias row. Raises aiosqlite.IntegrityError on UNIQUE/CHECK violation."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, ?, ?)",
            (klant_id, type_name, pattern.strip()))
        await conn.commit()
        return cur.lastrowid


async def delete_klant_alias(db_path: Path, alias_id: int) -> bool:
    """Delete alias by id. Returns True if a row was deleted."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "DELETE FROM klant_aliases WHERE id = ?", (alias_id,))
        await conn.commit()
        return cur.rowcount == 1


async def update_klant_alias_target(db_path: Path, alias_id: int,
                                     expected_old_klant_id: int,
                                     new_klant_id: int) -> bool:
    """Re-assign alias with optimistic lock.

    Returns True iff the alias's klant_id was exactly expected_old_klant_id at
    time of update.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "UPDATE klant_aliases SET klant_id = ? WHERE id = ? AND klant_id = ?",
            (new_klant_id, alias_id, expected_old_klant_id))
        await conn.commit()
        return cur.rowcount == 1


async def remember_alias(db_path: Path, klant_id: int,
                          pdf_extracted_name: str | None,
                          filename_suffix: str | None) -> dict:
    """Insert klant_aliases rows for an auto-learn (post manual klant pick).

    Race-vrij: try INSERT first; on UNIQUE conflict, re-read existing row to
    classify as 'already_correct' (same klant) or 'conflict' (different klant).

    Returns {'inserted': int, 'already_correct': int, 'conflicts': list[dict]}.
    Each conflict dict: {alias_id, type, pattern, existing_klant_id, existing_klant_naam}.
    """
    candidates = [
        ('pdf_text', pdf_extracted_name),
        ('suffix', filename_suffix),
    ]
    inserted = 0
    already_correct = 0
    conflicts: list[dict] = []
    async with get_db_ctx(db_path) as conn:
        prev_factory = conn.row_factory
        conn.row_factory = aiosqlite.Row
        try:
            for type_name, pattern in candidates:
                if not pattern or len(pattern.strip()) < 3:
                    continue
                pattern = pattern.strip()
                try:
                    await conn.execute(
                        "INSERT INTO klant_aliases (klant_id, type, pattern) "
                        "VALUES (?, ?, ?)",
                        (klant_id, type_name, pattern))
                    inserted += 1
                except aiosqlite.IntegrityError:
                    cur = await conn.execute(
                        "SELECT a.id, a.klant_id, k.naam FROM klant_aliases a "
                        "JOIN klanten k ON k.id = a.klant_id "
                        "WHERE a.type = ? AND a.pattern = ?",
                        (type_name, pattern))
                    row = await cur.fetchone()
                    if row is None:
                        # Vanished between INSERT and SELECT (extremely rare,
                        # would require concurrent DELETE). Skip silently.
                        continue
                    if row['klant_id'] == klant_id:
                        already_correct += 1
                    else:
                        conflicts.append({
                            'alias_id': row['id'],
                            'type': type_name,
                            'pattern': pattern,
                            'existing_klant_id': row['klant_id'],
                            'existing_klant_naam': row['naam'],
                        })
            await conn.commit()
        finally:
            conn.row_factory = prev_factory
    return {'inserted': inserted, 'already_correct': already_correct,
            'conflicts': conflicts}
```

- [ ] **Step 4: Run all helper tests, expect PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_klant_alias_helpers.py -v
```
Expected: 13 PASS.

- [ ] **Step 5: Confirm full suite green**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add database.py tests/test_klant_alias_helpers.py
git commit -m "feat(db): klant_aliases CRUD + remember_alias helpers"
```

---

### Task 4: `import_/skip_words.py` — `derive_skip_words` from bedrijfsgegevens

**Files:**
- Create: `import_/skip_words.py`
- Create: `tests/test_skip_words.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_skip_words.py
"""Tests for derive_skip_words and _normalize_phone_digits."""

import pytest
from types import SimpleNamespace
from import_.skip_words import (
    GENERIC_SKIP_WORDS, derive_skip_words, _normalize_phone_digits,
)


def _bg(**overrides):
    base = dict(naam='', bedrijfsnaam='', adres='', postcode_plaats='',
                telefoon='', email='', kvk='', iban='')
    base.update(overrides)
    return SimpleNamespace(**base)


def test_normalize_phone_plain_06():
    assert _normalize_phone_digits('06 1234 5678') == '0612345678'

def test_normalize_phone_plus31():
    assert _normalize_phone_digits('+31 6 4326 7791') == '0612345678'

def test_normalize_phone_0031():
    assert _normalize_phone_digits('0031 6 4326 7791') == '0612345678'

def test_normalize_phone_compact_0031():
    assert _normalize_phone_digits('0031643267791') == '0612345678'

def test_normalize_phone_too_short():
    assert _normalize_phone_digits('06 12') is None

def test_normalize_phone_empty():
    assert _normalize_phone_digits('') is None


def test_derive_none_returns_generic():
    assert derive_skip_words(None) == GENERIC_SKIP_WORDS


def test_derive_full_bg_includes_personal_tokens():
    bg = _bg(naam='Test Persoon', bedrijfsnaam='TestBV',
             adres='Hoofdstraat 1', postcode_plaats='1234 AB Stad',
             telefoon='06 1234 5678', email='info@example.nl')
    result = derive_skip_words(bg)
    for token in ('Test Persoon', 'TestBV', 'Hoofdstraat 1',
                  '1234 AB', 'Stad',
                  '0643', '064326', '06 432', '0612345678',
                  'info@example.nl', 'info'):
        assert token in result, f'missing: {token!r}'


def test_derive_postcode_no_match_uses_full_string():
    bg = _bg(postcode_plaats='Just a city')
    result = derive_skip_words(bg)
    assert 'Just a city' in result


def test_derive_email_without_at_no_local_part():
    bg = _bg(email='broken-email')
    result = derive_skip_words(bg)
    assert 'broken-email' in result
    assert 'broken' not in result


def test_derive_postcode_no_space_variant():
    bg = _bg(postcode_plaats='1234AB Stad')
    result = derive_skip_words(bg)
    assert '1234AB' in result
    assert 'Stad' in result


def test_derive_short_telefoon_skipped():
    bg = _bg(telefoon='12345')
    result = derive_skip_words(bg)
    assert '12345' not in result
```

- [ ] **Step 2: Run, expect ModuleNotFoundError**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_skip_words.py -v
```

- [ ] **Step 3: Create `import_/skip_words.py`**

```python
"""Derive PDF-parser skip-words from the user's `bedrijfsgegevens` row.

Replaces the old `import_/pdf_parser_local.py` static-tuple approach.
The skip-words for header lines (own name, bedrijfsnaam, adres,
telefoon-fragments, email-localpart, postcode/plaats) are derived at
runtime from a single source of truth (the bedrijfsgegevens DB row).
"""

from __future__ import annotations
import re

GENERIC_SKIP_WORDS: tuple[str, ...] = (
    'Datum', 'FACTUUR', 'Tel', 'KvK', 'IBAN', 'Mail:', 'Bank:',
    # Tokens used by scrubbed test fixtures (tests/test_pdf_parser.py):
    'TestBV', 'huisartswaarnemer', 'Test Gebruiker', 'T. Gebruiker',
    'Teststraat 1', '1234 AB', '1234AB', 'testuser', '06 000', '0600',
    '@example.com',
)


def _normalize_phone_digits(telefoon: str) -> str | None:
    """Return canonical 10-digit national form, or None.

    '06 1234 5678'         → '0612345678'
    '+31 6 4326 7791'      → '0612345678'
    '0031 6 4326 7791'     → '0612345678'
    '0031643267791'        → '0612345678'
    """
    digits = ''.join(c for c in telefoon if c.isdigit())
    if digits.startswith('0031'):
        digits = '0' + digits[4:]
    elif digits.startswith('31') and len(digits) == 11:
        digits = '0' + digits[2:]
    if len(digits) < 6:
        return None
    return digits


def derive_skip_words(bg) -> tuple[str, ...]:
    """Return GENERIC_SKIP_WORDS + tokens derived from a bedrijfsgegevens row.

    `bg` may be None (no row in DB yet) or any object with the standard
    bedrijfsgegevens attributes (naam, bedrijfsnaam, adres, postcode_plaats,
    telefoon, email, kvk, iban). All attributes tolerant of empty/None.
    """
    if bg is None:
        return GENERIC_SKIP_WORDS
    derived: list[str] = []

    for field in (getattr(bg, 'naam', ''),
                  getattr(bg, 'bedrijfsnaam', ''),
                  getattr(bg, 'adres', ''),
                  getattr(bg, 'email', '')):
        if field:
            derived.append(field)

    email = getattr(bg, 'email', '') or ''
    if email and '@' in email:
        derived.append(email.split('@', 1)[0])

    postcode_plaats = (getattr(bg, 'postcode_plaats', '') or '').strip()
    if postcode_plaats:
        m = re.match(r'^([0-9]{4}\s?[A-Z]{2})\s+(.+)$', postcode_plaats)
        if m:
            derived.extend(m.groups())
        else:
            derived.append(postcode_plaats)

    digits = _normalize_phone_digits(getattr(bg, 'telefoon', '') or '')
    if digits:
        derived.append(digits[:4])
        derived.append(digits[:6])
        derived.append(f'{digits[:2]} {digits[2:5]}')
        derived.append(digits)

    return GENERIC_SKIP_WORDS + tuple(derived)
```

- [ ] **Step 4: Run, expect 13 PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_skip_words.py -v
```

- [ ] **Step 5: Commit**

```bash
git add import_/skip_words.py tests/test_skip_words.py
git commit -m "feat(parser): derive_skip_words from bedrijfsgegevens row"
```

---

### Task 5: Refactor `pdf_parser.py` — `skip_words` parameter, case-insensitive

**Files:**
- Modify: `import_/pdf_parser.py` — replace module-level state; signature change
- Modify: `tests/test_skip_words.py` — add case-insensitive test BEFORE refactor

- [ ] **Step 1: Add a failing test for case-insensitive skip**

Append to `tests/test_skip_words.py`:

```python
def test_extract_klant_name_case_insensitive_skip():
    """Mixed-case header line should still be skipped if skip_word is canonical."""
    from import_.pdf_parser import _extract_klant_name
    text = """\
testbv huisartswaarnemer
        SomeKlant BV
"""
    # 'TestBV' canonical case in GENERIC_SKIP_WORDS; 'testbv' lowercase in fixture
    # should still be skipped via case-insensitive matching.
    result = _extract_klant_name(text, skip_words=GENERIC_SKIP_WORDS)
    assert result == 'SomeKlant BV'
```

- [ ] **Step 2: Run, expect FAIL**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_skip_words.py::test_extract_klant_name_case_insensitive_skip -v
```
Expected: TypeError or assertion fail (current `_extract_klant_name` either ignores skip_words OR fails on case).

- [ ] **Step 3: Locate the existing block to replace**

```
grep -nB1 -A8 "^PERSONAL_SKIP_WORDS\b" import_/pdf_parser.py
```

Expected: line ~23 starts `PERSONAL_SKIP_WORDS: tuple[str, ...] = (`, ends ~30 with `del _local_skip_words` then `except ImportError: pass`.

- [ ] **Step 4: Replace that whole block with import from `skip_words`**

Open `import_/pdf_parser.py`. Find the block (lines ~17 through ~33) starting from the comment `# Generic skip-tokens` up to and including `except ImportError:    pass`. Replace it with:

```python
from .skip_words import GENERIC_SKIP_WORDS
```

- [ ] **Step 5: Update `_extract_klant_name` signature + case-insensitive matching**

Find `def _extract_klant_name(text: str) -> str | None:` (search). Replace the **opening lines** of the function:

```python
def _extract_klant_name(text: str,
                         skip_words: tuple[str, ...] | None = None
                         ) -> str | None:
    """Extract klant name from invoice text.

    skip_words: optional tuple of header tokens to skip; defaults to
    GENERIC_SKIP_WORDS. Production callers pass derive_skip_words(bg).
    """
    if skip_words is None:
        skip_words = GENERIC_SKIP_WORDS
    skip_lower = tuple(s.lower() for s in skip_words)
    lines = text.split('\n')
```

Now find every check inside the function that reads `skip_words`. There are
6 occurrences in 6 strategies (search for `for s in skip_words`). For
each, change the predicate from `s in candidate` (case-sensitive) to
`s in candidate.lower()` and use `skip_lower` instead of `skip_words`.

For example:
```python
# Before
if candidate and not any(s in candidate for s in skip_words):
    return candidate
# After
if candidate and not any(s in candidate.lower() for s in skip_lower):
    return candidate
```

Apply this **identical** substitution at all 6 sites (Strategies 1, 2, 3, 4, 5, 6).

- [ ] **Step 6: Update `parse_dagpraktijk_text` signature only**

`parse_anw_text` does NOT use `_extract_klant_name` (it has its own
inline `Factuur aan: / Locatie:` extraction at lines ~615-625). Leave
its signature unchanged. Only `parse_dagpraktijk_text` needs the new arg.

```python
def parse_dagpraktijk_text(text: str, filename: str,
                           skip_words: tuple[str, ...] | None = None) -> dict:
    ...
    klant_name = _extract_klant_name(text, skip_words=skip_words)
    ...
```

- [ ] **Step 7: Run tests, expect all PASS now**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_skip_words.py tests/test_pdf_parser.py -q
```
Expected: all PASS (case-insensitive test now green; existing pdf_parser tests remain green).

- [ ] **Step 8: Run full suite**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 9: Commit**

```bash
git add import_/pdf_parser.py tests/test_skip_words.py
git commit -m "refactor(parser): skip_words param + case-insensitive match"
```

---

### Task 6: Refactor `import_/klant_mapping.py` AND `tests/test_pdf_parser.py` — atomic green commit

**Important**: this task changes both source and tests **in one commit** so the tree stays green at every commit boundary (codex round-1 plan-review must-fix #2).

**Files:**
- Modify: `import_/klant_mapping.py` (full rewrite)
- Modify: `tests/test_pdf_parser.py` (refactor TestResolveKlant + TestResolveANWKlant + remove `_stub_klant_mapping` + remove `MOCK_KLANTEN`)

- [ ] **Step 1: Rewrite `import_/klant_mapping.py`**

Replace the entire content of `import_/klant_mapping.py` with:

```python
"""Klant name resolution for invoice import.

Resolves a PDF-extracted klant name and/or filename suffix to a klant_id
via the `klant_aliases` DB table (no module-level state).

Strategy order (resolve_klant):
  1. Exact suffix match (filename_suffix → type='suffix')
  2. Exact pdf_text match (pdf_name → type='pdf_text')
  3. Direct klanten.naam match (case-insensitive)
  4. Fuzzy bidirectional substring (length(pattern) >= 3, longest pattern wins)

For ANW filenames: pattern-substring-of-filename match, case-insensitive,
longest pattern wins.
"""

from __future__ import annotations
from pathlib import Path
import aiosqlite
from database import DB_PATH, get_db_ctx


async def _query_one(db_path: Path, sql: str,
                      params: tuple) -> tuple[str, int] | None:
    """Run sql, return (naam, id) of first row or None. Uses Row factory."""
    async with get_db_ctx(db_path) as conn:
        prev_factory = conn.row_factory
        conn.row_factory = aiosqlite.Row
        try:
            cur = await conn.execute(sql, params)
            row = await cur.fetchone()
        finally:
            conn.row_factory = prev_factory
    if row is None:
        return None
    return row['naam'], row['id']


async def resolve_klant(db_path: Path = DB_PATH,
                        pdf_name: str | None = None,
                        filename_suffix: str | None = None
                        ) -> tuple[str | None, int | None]:
    """Resolve klant by PDF text and/or filename suffix.

    Returns (klant_naam, klant_id) or (None, None) if no match.
    """
    if filename_suffix:
        match = await _query_one(db_path, """
            SELECT k.naam AS naam, k.id AS id FROM klant_aliases a
            JOIN klanten k ON k.id = a.klant_id
            WHERE a.type = 'suffix' AND a.pattern = ?
            LIMIT 1
        """, (filename_suffix.strip(),))
        if match:
            return match

    if pdf_name:
        match = await _query_one(db_path, """
            SELECT k.naam AS naam, k.id AS id FROM klant_aliases a
            JOIN klanten k ON k.id = a.klant_id
            WHERE a.type = 'pdf_text' AND a.pattern = ?
            LIMIT 1
        """, (pdf_name.strip(),))
        if match:
            return match

        match = await _query_one(db_path, """
            SELECT id, naam FROM klanten
            WHERE naam = ? COLLATE NOCASE
            ORDER BY id ASC
            LIMIT 1
        """, (pdf_name.strip(),))
        if match:
            return match

        match = await _query_one(db_path, """
            SELECT k.naam AS naam, k.id AS id FROM klant_aliases a
            JOIN klanten k ON k.id = a.klant_id
            WHERE a.type = 'pdf_text'
              AND length(a.pattern) >= 3
              AND (instr(LOWER(?), LOWER(a.pattern)) > 0
                OR instr(LOWER(a.pattern), LOWER(?)) > 0)
            ORDER BY length(a.pattern) DESC, k.id ASC
            LIMIT 1
        """, (pdf_name.strip(), pdf_name.strip()))
        if match:
            return match

    return None, None


async def resolve_anw_klant(db_path: Path = DB_PATH,
                             filename: str = ''
                             ) -> tuple[str | None, int | None]:
    """Resolve ANW klant from filename via klant_aliases (type='anw_filename').

    Pattern is a substring of filename, case-insensitive. Longest pattern wins,
    then ASC klant_id for determinism. Returns (klant_naam, klant_id) or
    (None, None).
    """
    if not filename:
        return None, None
    match = await _query_one(db_path, """
        SELECT k.naam AS naam, k.id AS id FROM klant_aliases a
        JOIN klanten k ON k.id = a.klant_id
        WHERE a.type = 'anw_filename'
          AND length(a.pattern) >= 3
          AND instr(LOWER(?), LOWER(a.pattern)) > 0
        ORDER BY length(a.pattern) DESC, k.id ASC
        LIMIT 1
    """, (filename.strip(),))   # NB: 1 placeholder, 1 param (codex finding 3)
    return match if match else (None, None)
```

- [ ] **Step 2: Refactor `tests/test_pdf_parser.py` — `TestResolveKlant` + `TestResolveANWKlant`**

Open `tests/test_pdf_parser.py`. Find the section starting `# ── Klant resolution ──` (search for it; appears twice — pick the second one which precedes `class TestResolveKlant:`). Replace **everything from that header up to (and including) the last `def test_gr_factuur_matches_groningen` body** with:

```python
# ── Klant resolution ───────────────────────────────────────────────

@pytest.fixture
async def db_with_aliases(db):
    """DB seeded with placeholder klanten + aliases mirroring the old
    MOCK_KLANTEN test data."""
    from database import add_klant, get_db_ctx
    k_winsum = await add_klant(db, naam='HAP K14', tarief_uur=100.0)
    k_klant2 = await add_klant(db, naam='Klant2', tarief_uur=100.0)
    k_middenland = await add_klant(db, naam='HAP MiddenLand', tarief_uur=100.0)
    k_noordoost = await add_klant(db, naam='HAP NoordOost', tarief_uur=100.0)
    k_k6 = await add_klant(db, naam='HAP K6', tarief_uur=100.0)
    k_p9 = await add_klant(db, naam='Praktijk K9', tarief_uur=100.0)
    k_p12 = await add_klant(db, naam='Praktijk K12', tarief_uur=100.0)
    k_klant7 = await add_klant(db, naam='K. Klant7', tarief_uur=100.0)
    async with get_db_ctx(db) as conn:
        await conn.executemany(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, ?, ?)",
            [
                (k_winsum, 'suffix', 'Winsum'),
                (k_winsum, 'pdf_text', 'Centrum K14'),
                (k_winsum, 'pdf_text', 'K. Klant1'),
                (k_klant2, 'suffix', 'Klant2'),
                (k_klant2, 'suffix', 'Vlagtwedde'),
                (k_k6, 'suffix', 'Marum'),
                (k_k6, 'pdf_text', 'Praktijk K6'),
                (k_p12, 'pdf_text', 'Praktijk K12'),
                (k_klant7, 'suffix', 'Klant7'),
                (k_middenland, 'anw_filename', 'DokterDrenthe'),
                (k_middenland, 'anw_filename', 'Drenthe'),
                (k_noordoost, 'anw_filename', 'DokNoord'),
                (k_noordoost, 'anw_filename', 'DDG'),
                (k_noordoost, 'anw_filename', 'Groningen'),
                (k_noordoost, 'anw_filename', 'Gr_Factuur'),
            ])
        await conn.commit()
    return {
        'db': db,
        'HAP K14': k_winsum, 'Klant2': k_klant2,
        'HAP MiddenLand': k_middenland, 'HAP NoordOost': k_noordoost,
        'HAP K6': k_k6, 'Praktijk K9': k_p9, 'Praktijk K12': k_p12,
        'K. Klant7': k_klant7,
    }


class TestResolveKlant:
    async def test_suffix_winsum(self, db_with_aliases):
        from import_.klant_mapping import resolve_klant
        name, kid = await resolve_klant(db_with_aliases['db'], None, 'Winsum')
        assert name == 'HAP K14'
        assert kid == db_with_aliases['HAP K14']

    async def test_suffix_klant2(self, db_with_aliases):
        from import_.klant_mapping import resolve_klant
        name, kid = await resolve_klant(db_with_aliases['db'], None, 'Klant2')
        assert name == 'Klant2' and kid == db_with_aliases['Klant2']

    async def test_suffix_vlagtwedde_maps_to_klant2(self, db_with_aliases):
        from import_.klant_mapping import resolve_klant
        name, kid = await resolve_klant(db_with_aliases['db'], None, 'Vlagtwedde')
        assert name == 'Klant2'

    async def test_suffix_marum_maps_to_klant6(self, db_with_aliases):
        from import_.klant_mapping import resolve_klant
        name, kid = await resolve_klant(db_with_aliases['db'], None, 'Marum')
        assert name == 'HAP K6'

    async def test_pdf_name_centrum_k14(self, db_with_aliases):
        from import_.klant_mapping import resolve_klant
        name, kid = await resolve_klant(db_with_aliases['db'], 'Centrum K14', None)
        assert name == 'HAP K14'

    async def test_pdf_name_k_klant1(self, db_with_aliases):
        from import_.klant_mapping import resolve_klant
        name, kid = await resolve_klant(db_with_aliases['db'], 'K. Klant1', None)
        assert name == 'HAP K14'

    async def test_pdf_name_praktijk_k6(self, db_with_aliases):
        from import_.klant_mapping import resolve_klant
        name, kid = await resolve_klant(db_with_aliases['db'], 'Praktijk K6', None)
        assert name == 'HAP K6'

    async def test_pdf_name_praktijk_k12(self, db_with_aliases):
        from import_.klant_mapping import resolve_klant
        name, kid = await resolve_klant(db_with_aliases['db'], 'Praktijk K12', None)
        assert name == 'Praktijk K12'

    async def test_pdf_name_direct_klanten_match_case_insensitive(self, db_with_aliases):
        from import_.klant_mapping import resolve_klant
        name, kid = await resolve_klant(db_with_aliases['db'], 'hap noordoost', None)
        assert name == 'HAP NoordOost'

    async def test_suffix_takes_precedence(self, db_with_aliases):
        from import_.klant_mapping import resolve_klant
        name, kid = await resolve_klant(
            db_with_aliases['db'], 'Some Other Name', 'Klant7')
        assert name == 'K. Klant7'

    async def test_unknown_returns_none(self, db_with_aliases):
        from import_.klant_mapping import resolve_klant
        name, kid = await resolve_klant(
            db_with_aliases['db'], 'Unknown Practice XYZ', None)
        assert (name, kid) == (None, None)


class TestResolveANWKlant:
    async def test_drenthe_2023(self, db_with_aliases):
        from import_.klant_mapping import resolve_anw_klant
        name, kid = await resolve_anw_klant(
            db_with_aliases['db'], '2023-09_DokterDrenthe.pdf')
        assert name == 'HAP MiddenLand'

    async def test_drenthe_2024(self, db_with_aliases):
        from import_.klant_mapping import resolve_anw_klant
        name, kid = await resolve_anw_klant(
            db_with_aliases['db'], 'Drenthe_02-24.pdf')
        assert name == 'HAP MiddenLand'

    async def test_drenthe_2025(self, db_with_aliases):
        from import_.klant_mapping import resolve_anw_klant
        name, kid = await resolve_anw_klant(
            db_with_aliases['db'], '0225_HAP_Drenthe.pdf')
        assert name == 'HAP MiddenLand'

    async def test_groningen_2024(self, db_with_aliases):
        from import_.klant_mapping import resolve_anw_klant
        name, kid = await resolve_anw_klant(
            db_with_aliases['db'], 'Groningen_05-24.pdf')
        assert name == 'HAP NoordOost'

    async def test_groningen_2025(self, db_with_aliases):
        from import_.klant_mapping import resolve_anw_klant
        name, kid = await resolve_anw_klant(
            db_with_aliases['db'], '0225_HAP_Groningen.pdf')
        assert name == 'HAP NoordOost'

    async def test_gr_factuur_matches_groningen(self, db_with_aliases):
        from import_.klant_mapping import resolve_anw_klant
        name, kid = await resolve_anw_klant(
            db_with_aliases['db'], '2512_Gr_Factuur.pdf')
        assert name == 'HAP NoordOost'
```

- [ ] **Step 3: Remove the now-dead old fixtures**

In the same file, find and **delete** these blocks (search for each marker):

- The comment block starting `# Self-contained test mappings — keep tests independent`
- The constant `_TEST_SUFFIX_TO_KLANT = { ... }`
- The constant `_TEST_PDF_KLANT_TO_DB = { ... }`
- The constant `_TEST_ANW_FILENAME_TO_KLANT = { ... }`
- The fixture `def _stub_klant_mapping(monkeypatch):`
- The constant `MOCK_KLANTEN = { ... }`
- The `@pytest.mark.usefixtures('_stub_klant_mapping')` decorators on the class definitions

- [ ] **Step 4: Run affected tests**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_pdf_parser.py -v
```
Expected: all PASS (parsing tests + 17 refactored resolve tests).

- [ ] **Step 5: Run full suite**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```
Expected: green.

- [ ] **Step 6: Single commit (atomic source + test refactor)**

```bash
git add import_/klant_mapping.py tests/test_pdf_parser.py
git commit -m "refactor(klant_mapping): async DB-resolution + atomic test refactor"
```

---

### Task 7: Update `pages/facturen.py` callers (await + skip_words)

**Files:**
- Modify: `pages/facturen.py` — lines around 1423 (klant_lookup construction) and 1500-1505 (resolve_klant calls)

- [ ] **Step 1: Inspect current code**

```
sed -n '1420,1430p' pages/facturen.py
sed -n '1495,1510p' pages/facturen.py
```

Expected: line 1423 has `klant_lookup = {k.naam: k.id for k in klanten}`; lines 1500/1504 have synchronous calls to resolve_klant/resolve_anw_klant.

- [ ] **Step 2: Add skip_words derivation in the import-handler scope**

Find the function that contains both line 1423 and lines 1500-1505 (it's
the file-upload event handler, an inner async function). Right after the
line `klant_lookup = {k.naam: k.id for k in klanten}` (line 1423), add:

```python
            from import_.skip_words import derive_skip_words
            from database import get_bedrijfsgegevens
            bg = await get_bedrijfsgegevens(DB_PATH)
            skip_words_for_parse = derive_skip_words(bg)
```

(Indentation must match the surrounding code — the existing
`klant_lookup` line.)

- [ ] **Step 3: Replace synchronous calls with awaited DB calls**

Find the two calls:

```python
                                db_naam, klant_id = resolve_klant(
                                    parsed.get('klant_name'), suffix,
                                    klant_lookup)
                                ...
                                db_naam, klant_id = resolve_anw_klant(
                                    filename, klant_lookup)
```

Replace with:

```python
                                db_naam, klant_id = await resolve_klant(
                                    DB_PATH,
                                    pdf_name=parsed.get('klant_name'),
                                    filename_suffix=suffix)
                                ...
                                db_naam, klant_id = await resolve_anw_klant(
                                    DB_PATH, filename=filename)
```

- [ ] **Step 4: Inject skip_words into the dagpraktijk parser call only**

Find the call to `parse_dagpraktijk_text(...)` in `pages/facturen.py`.
Add the `skip_words` argument:

```python
parsed = parse_dagpraktijk_text(text, filename, skip_words=skip_words_for_parse)
```

**Do NOT add `skip_words=...` to `parse_anw_text(...)` calls.** ANW
parser uses its own inline klant-extraction (regex-anchored on
`Factuur aan:` / `Locatie :`); it does not call `_extract_klant_name` and
does not accept a `skip_words` param. Leaving it untouched is the correct
choice.

- [ ] **Step 5: Remove now-unused `klant_lookup` if no longer referenced**

```
grep -n "klant_lookup\b" pages/facturen.py
```

If `klant_lookup` is only constructed and used once (at the resolve calls
we just replaced), delete the construction line `klant_lookup = {...}` (it
becomes dead). Note: leave `klanten = ...` query intact if used for
something else; only remove the dict comprehension.

- [ ] **Step 6: Run full test suite**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```
Expected: green.

- [ ] **Step 7: Manual smoke test**

```
source .venv/bin/activate && export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib && python main.py
```

Open Facturen page, drag in a known PDF (e.g. one of your monthly
HAP NoordOost ANW exports). Confirm the import preview shows
the right klant resolved automatically. Close window when satisfied.

- [ ] **Step 8: Commit**

```bash
git add pages/facturen.py
git commit -m "feat(facturen): await async resolve_klant + inject derived skip_words"
```

---

### Task 7b: Scrub remaining `Klant16` leak

**Files:**
- Modify: `tests/test_archive_factuur.py`

- [ ] **Step 1: Identify lines**

```
grep -n "Klant16" tests/test_archive_factuur.py
```

- [ ] **Step 2: Replace `Klant16` → `Klant16`** (use Edit tool with `replace_all=True`)

`Klant16` → `Klant16` (replaces in `2026-027_Klant16.pdf` paths and any other
mention).

- [ ] **Step 3: Run affected tests + verify no Klant16 anywhere**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_archive_factuur.py -q
git grep -F "Klant16"   # expect empty
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_archive_factuur.py
git commit -m "test: scrub remaining 'Klant16' customer-name leak"
```

---

## Phase 1 — checkpoint

- New klant_aliases table populated by migration 34 once
- derive_skip_words from DB
- async resolve_klant query DB
- All tests green at every commit
- Manual app smoke test passed

---

## Phase 2 — UI + cleanup

### Task 8: Per-row remember-checkbox + auto-learn handling

**Files:**
- Modify: `database.py` — add testable orchestrator `process_remember_alias`
- Modify: `tests/test_klant_alias_helpers.py` — add tests for orchestrator
- Modify: `pages/facturen.py` — add `_remember_alias` flag per parsed_items entry; render checkbox; call orchestrator on confirm

- [ ] **Step 1: Add failing test for `process_remember_alias`**

Append to `tests/test_klant_alias_helpers.py`:

```python
async def test_process_remember_alias_no_conflict(db_two):
    """No conflicts → orchestrator just inserts."""
    db, k1, _ = db_two
    from database import process_remember_alias

    async def callback(c):
        raise AssertionError('callback should not be called when no conflicts')

    result = await process_remember_alias(
        db, klant_id=k1, target_klant_naam='Klant Alpha',
        pdf_extracted_name='Foo BV', filename_suffix=None,
        on_conflict=callback)
    assert result['inserted'] == 1 and result['conflicts_resolved'] == 0


async def test_process_remember_alias_conflict_keep(db_two):
    """Conflict → callback returns 'keep' → no reassign."""
    db, k1, k2 = db_two
    from database import process_remember_alias, add_klant_alias, get_klant_aliases
    await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')

    seen_conflicts = []
    async def callback(c):
        seen_conflicts.append(c)
        return 'keep'

    result = await process_remember_alias(
        db, klant_id=k2, target_klant_naam='Klant Beta',
        pdf_extracted_name='Foo BV', filename_suffix=None,
        on_conflict=callback)
    assert len(seen_conflicts) == 1
    assert result['inserted'] == 0
    assert result['conflicts_resolved'] == 0
    rows = await get_klant_aliases(db, k1)
    assert len(rows) == 1  # original unchanged


async def test_process_remember_alias_conflict_reassign(db_two):
    """Conflict → callback returns 'reassign' → optimistic update."""
    db, k1, k2 = db_two
    from database import process_remember_alias, add_klant_alias, get_klant_aliases
    await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')

    async def callback(c):
        return 'reassign'

    result = await process_remember_alias(
        db, klant_id=k2, target_klant_naam='Klant Beta',
        pdf_extracted_name='Foo BV', filename_suffix=None,
        on_conflict=callback)
    assert result['inserted'] == 0
    assert result['conflicts_resolved'] == 1
    rows1 = await get_klant_aliases(db, k1)
    rows2 = await get_klant_aliases(db, k2)
    assert rows1 == [] and len(rows2) == 1


async def test_process_remember_alias_reassign_stale_lost(db_two):
    """Conflict → reassign callback, but alias was already moved → ok=False."""
    db, k1, k2 = db_two
    from database import (process_remember_alias, add_klant_alias,
                          update_klant_alias_target, get_klant_aliases)
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')

    async def callback(c):
        # Simulate concurrent move (someone else moves alias to k2 first)
        await update_klant_alias_target(db, aid, k1, k2)
        return 'reassign'

    result = await process_remember_alias(
        db, klant_id=k2, target_klant_naam='Klant Beta',
        pdf_extracted_name='Foo BV', filename_suffix=None,
        on_conflict=callback)
    # Reassign was attempted but failed (alias already moved)
    assert result['conflicts_lost'] == 1
```

- [ ] **Step 2: Run tests, expect ImportError**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_klant_alias_helpers.py -v
```
Expected: ImportError on `process_remember_alias`.

- [ ] **Step 3: Implement `process_remember_alias` in database.py**

Add after `remember_alias` (created in Task 3):

```python
async def process_remember_alias(db_path: Path,
                                  klant_id: int,
                                  target_klant_naam: str,
                                  pdf_extracted_name: str | None,
                                  filename_suffix: str | None,
                                  on_conflict) -> dict:
    """Auto-learn orchestrator: call remember_alias, then resolve conflicts via callback.

    `on_conflict(conflict_dict) -> str`: async callback that decides each
    conflict. Must return 'keep' or 'reassign'.

    Returns:
      'inserted': int          (new aliases added)
      'already_correct': int   (alias already mapped to klant_id)
      'conflicts_resolved': int (callback said 'reassign' AND optimistic-lock succeeded)
      'conflicts_lost': int    (callback said 'reassign' but alias was concurrently moved)
      'conflicts_kept': int    (callback said 'keep')
    """
    base = await remember_alias(db_path, klant_id, pdf_extracted_name, filename_suffix)
    resolved = 0
    lost = 0
    kept = 0
    for c in base['conflicts']:
        decision = await on_conflict(c)
        if decision == 'reassign':
            ok = await update_klant_alias_target(
                db_path, c['alias_id'],
                expected_old_klant_id=c['existing_klant_id'],
                new_klant_id=klant_id)
            if ok:
                resolved += 1
            else:
                lost += 1
        else:
            kept += 1
    return {
        'inserted': base['inserted'],
        'already_correct': base['already_correct'],
        'conflicts_resolved': resolved,
        'conflicts_lost': lost,
        'conflicts_kept': kept,
    }
```

- [ ] **Step 4: Run tests, expect 4 PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_klant_alias_helpers.py::test_process_remember_alias_no_conflict tests/test_klant_alias_helpers.py::test_process_remember_alias_conflict_keep tests/test_klant_alias_helpers.py::test_process_remember_alias_conflict_reassign tests/test_klant_alias_helpers.py::test_process_remember_alias_reassign_stale_lost -v
```

- [ ] **Step 5: Trace the preview-render and confirm-submit functions in pages/facturen.py**

```
grep -nB2 -A5 "parsed_items\[\|parsed_items\.append\|render_preview\|on_confirm\|_handle_confirm\|on_submit" pages/facturen.py | head -50
```

Identify (a) where each `parsed_items` entry is constructed, (b) the
render-preview function that draws each row, (c) the confirm handler
that loops `for item in parsed_items` and inserts to DB.

- [ ] **Step 6: Initialise `_remember_alias` on each parsed_items entry**

Where each `parsed` dict is appended to `parsed_items` (search for
`parsed_items.append`), ensure each appended item has the new key:

```python
parsed['_remember_alias'] = False  # default OFF (codex round-2 finding 2)
parsed_items.append(parsed)
```

Apply this to every `parsed_items.append(parsed)` site — but only for
entries that have a `_klant_id` slot (real rows; not the `_type='unknown'`
or `_type='error'` rows where klant resolution doesn't apply).

- [ ] **Step 7: Render the checkbox per row in `render_preview`**

Find the function `render_preview` (or whatever renders parsed_items)
and inside the per-row block, after the row's klant-select dropdown,
add:

```python
def _on_remember_toggle(item, value):
    item['_remember_alias'] = bool(value)

# inside the per-row layout:
if item.get('_klant_id') is not None or item.get('_status') in ('nieuw', 'voorbeeld'):
    pdf_name_or_suffix = item.get('klant_name') or item.get('_filename', '')
    label = f'Onthoud "{pdf_name_or_suffix}"' if pdf_name_or_suffix else 'Onthoud'
    ui.checkbox(label, value=item.get('_remember_alias', False),
                on_change=lambda e, it=item: _on_remember_toggle(it, e.value))\
       .props('dense')
```

(Exact indentation/layout depends on what's there now — match existing
checkbox or button styling in the same row.)

- [ ] **Step 8: After successful insert, call `process_remember_alias` if flagged**

In the confirm handler that loops `parsed_items` and writes facturen,
after a successful insert for one item, add (still inside the loop):

```python
if item.get('_remember_alias') and item.get('_klant_id'):
    from database import process_remember_alias
    pdf_name = item.get('klant_name')
    suffix = item.get('_suffix')
    target_klant_naam = item.get('_klant_naam') or 'gekozen klant'

    async def _on_conflict(c):
        return await _show_alias_conflict_dialog(
            pattern=c['pattern'],
            existing_klant_naam=c['existing_klant_naam'],
            target_klant_naam=target_klant_naam)

    res = await process_remember_alias(
        DB_PATH, klant_id=item['_klant_id'],
        target_klant_naam=target_klant_naam,
        pdf_extracted_name=pdf_name, filename_suffix=suffix,
        on_conflict=_on_conflict)

    if res['conflicts_lost']:
        ui.notify(
            f"{res['conflicts_lost']}× alias kon niet verplaatst worden — "
            "ondertussen elders aangepast.", type='warning')
```

- [ ] **Step 9: Add the modal helper at module level**

In `pages/facturen.py`, add at module top-level (after imports):

```python
async def _show_alias_conflict_dialog(pattern: str,
                                       existing_klant_naam: str,
                                       target_klant_naam: str) -> str:
    """Modal dialog: 'keep' existing alias mapping or 'reassign' to target.

    Closing the dialog (X / click outside) → 'keep' (safe default).
    """
    with ui.dialog() as dialog, ui.card():
        ui.label(f"Alias '{pattern}' is al gekoppeld aan '{existing_klant_naam}'.").classes('text-lg')
        ui.label(f"Wil je 'm verplaatsen naar '{target_klant_naam}'?")
        with ui.row().classes('q-gutter-sm'):
            ui.button('Behoud', on_click=lambda: dialog.submit('keep'))
            ui.button('Verplaats', color='warning',
                      on_click=lambda: dialog.submit('reassign'))
    result = await dialog
    return result if result in ('keep', 'reassign') else 'keep'
```

If `_suffix` isn't currently stored in `parsed`, also persist it at
parse-time (around line 1495) so it's available later:

```python
suffix = (
    filename.split('_', 1)[1].replace('.pdf', '')
    if '_' in filename else None)
parsed['_suffix'] = suffix
```

- [ ] **Step 10: Run full test suite**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```
Expected: green (orchestrator tests added in Step 1-4 cover the loop logic; UI is glue around the tested helper).

- [ ] **Step 11: Manual UI smoke test**

Start dev server. Open Facturen page. Drag in a PDF for which there's no
existing alias. Verify:
- Checkbox `Onthoud "..."` appears, default OFF.
- Tick it, pick a klant manually, click Confirm.
- Drag the same PDF in again → klant auto-resolves.
- Drag in a PDF whose extracted name is already an alias for klant A,
  then pick klant B and tick Onthoud → conflict dialog pops; both
  Behoud and Verplaats branches work.

- [ ] **Step 12: Commit**

```bash
git add pages/facturen.py database.py tests/test_klant_alias_helpers.py
git commit -m "feat(facturen): per-row auto-learn alias + tested orchestrator + conflict modal"
```

---

### Task 9: Alias-CRUD UI in `components/shared_ui.py:open_klant_dialog`

**Files:**
- Modify: `components/shared_ui.py` — add aliases section inside the existing klant-edit dialog
- Create: `tests/test_alias_round_trip.py` (smoke test for the CRUD round-trip)

- [ ] **Step 1: Write a smoke test for the round-trip via DB helpers**

```python
# tests/test_alias_round_trip.py
"""Smoke test for the alias CRUD round-trip via DB helpers (the layer the
/klanten dialog calls)."""

import pytest
from database import (
    add_klant, add_klant_alias, get_klant_aliases,
    delete_klant_alias, update_klant_alias_target,
)


async def test_alias_round_trip(db):
    k = await add_klant(db, naam='Klant Test', tarief_uur=100.0)
    aid = await add_klant_alias(db, k, 'pdf_text', 'Initial Pattern')
    rows = await get_klant_aliases(db, k)
    assert len(rows) == 1 and rows[0]['pattern'] == 'Initial Pattern'

    deleted = await delete_klant_alias(db, aid)
    assert deleted is True
    assert await get_klant_aliases(db, k) == []


async def test_alias_reassign_round_trip(db):
    k1 = await add_klant(db, naam='Klant A', tarief_uur=100.0)
    k2 = await add_klant(db, naam='Klant B', tarief_uur=100.0)
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Shared Name')
    ok = await update_klant_alias_target(db, aid, k1, k2)
    assert ok is True
    rows1 = await get_klant_aliases(db, k1)
    rows2 = await get_klant_aliases(db, k2)
    assert rows1 == [] and len(rows2) == 1


async def test_alias_validation_rejects_short_pattern(db):
    """UI calls add_klant_alias; validation comes from DB CHECK constraint."""
    import aiosqlite
    k = await add_klant(db, naam='Klant', tarief_uur=100.0)
    with pytest.raises(aiosqlite.IntegrityError):
        await add_klant_alias(db, k, 'pdf_text', 'AB')
```

- [ ] **Step 2: Run, expect already-PASS (helpers exist from Task 3)**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_alias_round_trip.py -v
```

- [ ] **Step 3: Add aliases section inside `open_klant_dialog`**

Open `components/shared_ui.py`. Find `async def open_klant_dialog` at
line ~132. Locate the part of the dialog body just **before** the
final action-button row (the `Opslaan/Toevoegen` button). Insert:

```python
        # -- Aliases (alleen voor bestaande klanten; bij nieuwe klant nog geen id) --
        if is_edit and d.get('id') is not None:
            klant_id = d['id']
            ui.separator().classes('q-my-md')
            _section_label('Aliassen voor PDF-import')

            aliases_container = ui.column().classes('w-full q-gutter-sm')

            async def _refresh_aliases():
                from database import get_klant_aliases
                aliases_container.clear()
                with aliases_container:
                    rows = await get_klant_aliases(DB_PATH, klant_id)
                    if not rows:
                        ui.label('(geen aliassen)').classes('text-italic text-grey')
                    else:
                        for row in rows:
                            with ui.row().classes('items-center q-gutter-sm'):
                                ui.badge(row['type']).props('color=grey-6')
                                ui.label(row['pattern']).classes('q-ml-sm')
                                async def _del(aid=row['id']):
                                    from database import delete_klant_alias
                                    await delete_klant_alias(DB_PATH, aid)
                                    await _refresh_aliases()
                                ui.button(icon='delete', color='negative',
                                          on_click=_del).props('flat dense round')

            await _refresh_aliases()

            with ui.row().classes('q-gutter-sm q-mt-sm items-end'):
                _type_select = ui.select(
                    ['suffix', 'pdf_text', 'anw_filename'],
                    value='pdf_text', label='Type').classes('w-32')
                _pattern_input = ui.input('Patroon').classes('w-64')
                async def _add_alias():
                    from database import add_klant_alias
                    pat = (_pattern_input.value or '').strip()
                    if len(pat) < 3:
                        ui.notify('Patroon moet minimaal 3 tekens zijn.',
                                  type='warning')
                        return
                    try:
                        await add_klant_alias(DB_PATH, klant_id,
                                               _type_select.value, pat)
                    except Exception as e:
                        ui.notify(f'Kon niet toevoegen: {e}', type='negative')
                        return
                    _pattern_input.value = ''
                    await _refresh_aliases()
                ui.button('Toevoegen', on_click=_add_alias)
```

Required additional imports at top of `components/shared_ui.py` (if
not already present):

```python
from database import DB_PATH
```

- [ ] **Step 4: Run all tests + smoke**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```
Then manual:

```
source .venv/bin/activate && export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib && python main.py
```

Open `/klanten`, click on an existing klant to edit. Scroll to the new
"Aliassen voor PDF-import" section. Add an alias, delete an alias.
Verify persistence by closing dialog + reopening.

- [ ] **Step 5: Commit**

```bash
git add components/shared_ui.py tests/test_alias_round_trip.py
git commit -m "feat(klanten): alias CRUD section in open_klant_dialog"
```

---

### Task 10: Remove `KLANT_LOCATIES` + `seed_klant_locaties`

**Files:**
- Modify: `import_/seed_data.py`
- Modify: `tests/test_seed.py` if any tests reference removed func

- [ ] **Step 1: Find current state**

```
grep -nE "KLANT_LOCATIES|seed_klant_locaties|seed_all" import_/seed_data.py
grep -nRE "seed_klant_locaties|KLANT_LOCATIES" tests/
```

- [ ] **Step 2: Edit `import_/seed_data.py`**

Delete:
- The `KLANT_LOCATIES: dict ... = {}` definition + its comment
- The `try: from .seed_data_local import KLANT_LOCATIES ... except ImportError: pass` block
- The entire `async def seed_klant_locaties(db_path):` function

Update `seed_all`:

```python
# Before:
async def seed_all(db_path: Path) -> tuple[int, int]:
    """Seed fiscale parameters and klant locaties."""
    fp_count = await seed_fiscale_params(db_path)
    loc_count = await seed_klant_locaties(db_path)
    return fp_count, loc_count

# After:
async def seed_all(db_path: Path) -> tuple[int, int]:
    """Seed fiscale parameters. Returns (fp_count, 0); the second slot was
    formerly seed_klant_locaties (removed — locaties zijn user-data, niet
    seed-data)."""
    fp_count = await seed_fiscale_params(db_path)
    return fp_count, 0
```

- [ ] **Step 3: Update tests in `tests/test_seed.py`**

If any test calls `seed_klant_locaties` or asserts on `KLANT_LOCATIES`,
remove it. Keep tests for `seed_fiscale_params`.

- [ ] **Step 4: Run full suite**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```
Expected: green (test count may drop slightly).

- [ ] **Step 5: Commit**

```bash
git add import_/seed_data.py tests/test_seed.py
git commit -m "refactor(seed): remove KLANT_LOCATIES (dead code; locaties live in DB)"
```

---

### Task 11: Backup current klant_aliases to JSON snapshot

**Why**: Migration 34 falls back to a JSON snapshot if `klant_mapping_local.py` is gone. Create that snapshot **before** deleting the local files in Task 13, so future DB-restore-from-old-backup scenarios still seed correctly.

**Files:**
- Create: `scripts/export_klant_aliases.py` (one-shot, deleted after run)

- [ ] **Step 1: Create the export script**

```python
# scripts/export_klant_aliases.py
"""One-shot: export current klant_aliases to JSON snapshot for future migrations."""

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _config_dir() -> Path:
    override = os.environ.get('BOEKHOUDING_CONFIG_DIR')
    if override:
        return Path(override)
    return (Path.home() / 'Library' / 'Application Support'
            / 'Boekhouding' / 'config')


def main() -> int:
    db = (Path.home() / 'Library' / 'Application Support'
          / 'Boekhouding' / 'data' / 'boekhouding.sqlite3')
    conn = sqlite3.connect(db)
    rows = conn.execute("""
        SELECT k.naam AS klant_naam, a.type AS type, a.pattern AS pattern
        FROM klant_aliases a JOIN klanten k ON k.id = a.klant_id
        ORDER BY a.type, a.pattern
    """).fetchall()
    conn.close()

    out_dir = _config_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot = [{'klant_naam': r[0], 'type': r[1], 'pattern': r[2]}
                for r in rows]
    out = out_dir / 'klant_aliases_backup.json'
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    print(f'✅ Exported {len(snapshot)} aliases to {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: Run it**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/export_klant_aliases.py
```

Expected output: `Exported N aliases to ~/Library/Application Support/Boekhouding/config/klant_aliases_backup.json`.

Verify:

```
ls -la ~/Library/Application\ Support/Boekhouding/config/klant_aliases_backup.json
```

- [ ] **Step 3: Commit script (will be removed in Task 14)**

```bash
git add scripts/export_klant_aliases.py
git commit -m "chore: one-shot script to export klant_aliases to JSON snapshot"
```

---

### Task 12: Run audit_missing_locaties.py + verify_public_safe.py

**Files:**
- Create: `scripts/audit_missing_locaties.py`
- Create: `scripts/verify_public_safe.py`

- [ ] **Step 1: Create `scripts/audit_missing_locaties.py`**

```python
# scripts/audit_missing_locaties.py
"""One-shot audit: which klanten have 0 locaties? Cross-check with stale
seed_data_local.py entries (if still present)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import DB_PATH, get_klanten, get_klant_locaties


async def main():
    klanten = await get_klanten(DB_PATH, alleen_actief=False)
    naam_set = {k.naam for k in klanten}

    print('=== Klanten zonder locaties ===')
    missing = []
    for k in klanten:
        locs = await get_klant_locaties(DB_PATH, k.id)
        if not locs:
            missing.append(k.naam)
            print(f'  {k.naam}')

    print()
    print('=== Stale seed-namen (in seed_data_local.py niet in DB) ===')
    try:
        from import_.seed_data_local import KLANT_LOCATIES
        for seed_naam in KLANT_LOCATIES:
            if seed_naam not in naam_set:
                print(f'  {seed_naam}')
    except ImportError:
        print('  (seed_data_local.py al verwijderd)')

    print()
    print(f'Aktie: voor {len(missing)} klanten zonder locaties — voeg '
          'handmatig toe via /klanten als nodig.')


if __name__ == '__main__':
    asyncio.run(main())
```

- [ ] **Step 2: Run it and review**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/audit_missing_locaties.py
```

User decides: leave klanten zonder locaties as-is, OR add via `/klanten`
UI now.

- [ ] **Step 3: Create `scripts/verify_public_safe.py`**

```python
# scripts/verify_public_safe.py
"""One-shot: verify no personal-info or customer-name tokens are present
in tracked files. Use before flipping repo to public."""

import sqlite3
import pathlib
import subprocess
import sys

DB = pathlib.Path.home() / 'Library/Application Support/Boekhouding/data/boekhouding.sqlite3'

CITY_ALLOWLIST = {
    'Groningen', 'Zuidhorn', 'Stadskanaal', 'Delfzijl', 'Scheemda',
    'Assen', 'Hoogeveen', 'Emmen', 'Vlagtwedde', 'Marum', 'Winsum',
    'Smilde', 'Sellingen', 'Wilp', 'Drenthe',
}
GENERIC_ALLOWLIST = {
    'Huisarts', 'Huisartsen', 'Huisartsenpraktijk', 'Huisartspraktijk',
    'Huisartswaarnemer', 'HAP', 'Centrum', 'Praktijk', 'Spoedpost',
    'Doktersdienst', 'Test', 'TestBV',
}


def main() -> int:
    if not DB.exists():
        print(f'❌ DB not found at {DB}')
        return 2
    conn = sqlite3.connect(DB)
    full_tokens: set[str] = set()
    for r in conn.execute('SELECT naam FROM klanten'):
        if r[0]:
            full_tokens.add(r[0])
    bg_row = conn.execute(
        'SELECT naam, bedrijfsnaam, adres, postcode_plaats, telefoon, email, kvk, iban '
        'FROM bedrijfsgegevens'
    ).fetchone() or ()
    for t in bg_row:
        if t and len(str(t)) >= 4:
            full_tokens.add(str(t))

    fragment_tokens: set[str] = set()
    for r in conn.execute('SELECT naam FROM klanten'):
        if not r[0]:
            continue
        for part in r[0].replace('.', ' ').split():
            if (len(part) >= 4 and part[0].isupper()
                and part not in CITY_ALLOWLIST
                and part not in GENERIC_ALLOWLIST):
                fragment_tokens.add(part)

    leaks = []
    for token in sorted(full_tokens | fragment_tokens):
        result = subprocess.run(
            ['git', 'grep', '-l', '-F', token],
            capture_output=True, text=True)
        if not result.stdout.strip():
            continue
        for path in result.stdout.strip().split('\n'):
            if 'verify_public_safe' in path or 'audit_missing_locaties' in path:
                continue
            ctx = subprocess.run(
                ['git', 'grep', '-n', '-F', token, path],
                capture_output=True, text=True).stdout.strip().split('\n')[0]
            leaks.append((token, path, ctx))

    if leaks:
        print(f'❌ {len(leaks)} potential leaks (review context):')
        for token, path, ctx in leaks:
            print(f'  [{token}] {ctx}')
        return 1
    print('✅ public-safe: 0 leaks')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run + iterate to 0 leaks**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python scripts/verify_public_safe.py
```

For each reported leak:
- **False positive** (city/generic): add to allowlist + re-run
- **Real leak**: edit the offending file (replace token with placeholder
  or remove), commit fix, re-run
- Repeat until exit 0

- [ ] **Step 5: Commit scripts (will be removed in Task 14)**

```bash
git add scripts/audit_missing_locaties.py scripts/verify_public_safe.py
git commit -m "chore: one-shot audit + verify_public_safe scripts"
```

If any leak fixes were committed during iteration, they get their own
commits along the way.

---

### Task 13: Delete `_local.py` files + clean `.gitignore`

**Files:**
- Delete: `import_/klant_mapping_local.py`
- Delete: `import_/seed_data_local.py`
- Delete: `import_/pdf_parser_local.py`
- Modify: `.gitignore`

**Pre-conditions** (verify before deleting):
1. JSON snapshot exists at `~/Library/Application Support/Boekhouding/config/klant_aliases_backup.json` (created in Task 11)
2. `klant_aliases` table populated (`SELECT COUNT(*) FROM klant_aliases > 0`)
3. `verify_public_safe.py` returns 0 leaks (Task 12)

- [ ] **Step 1: Verify pre-conditions**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -c "
import sqlite3, pathlib, json
db = pathlib.Path.home() / 'Library/Application Support/Boekhouding/data/boekhouding.sqlite3'
conn = sqlite3.connect(db)
n = conn.execute('SELECT COUNT(*) FROM klant_aliases').fetchone()[0]
snap = pathlib.Path.home() / 'Library/Application Support/Boekhouding/config/klant_aliases_backup.json'
assert n > 0, f'klant_aliases is empty ({n} rows) — migration 34 has not run'
assert snap.exists(), f'snapshot missing at {snap}'
data = json.loads(snap.read_text())
assert len(data) == n, f'snapshot count ({len(data)}) != DB count ({n})'
print(f'✅ pre-conditions met: {n} aliases in DB, {len(data)} in snapshot')
"
```

- [ ] **Step 2: Delete the 3 files**

```bash
rm import_/klant_mapping_local.py
rm import_/seed_data_local.py
rm import_/pdf_parser_local.py
```

- [ ] **Step 3: Edit `.gitignore`**

Use the Edit tool to remove these lines (and the comment block above
them):

```
# Local overrides containing personally-identifying / customer data —
# loaded by their public counterparts via try/except ImportError.
import_/klant_mapping_local.py
import_/seed_data_local.py
import_/pdf_parser_local.py
```

- [ ] **Step 4: Run full test suite to confirm runtime is now DB-only**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 5: Manual app smoke test (REQUIRED)**

```
source .venv/bin/activate && export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib && python main.py
```

Verify: dashboard loads; drag a known-klant PDF into facturen → it
auto-resolves.

**Rollback path** if the app fails or PDFs no longer auto-resolve:

The `_local.py` files were never tracked by git (gitignored), so they
cannot be restored from `git log` / `git checkout`. The recovery source
is the JSON snapshot created in Task 11. To recover:

1. Verify snapshot still exists:
   ```
   ls -la ~/Library/Application\ Support/Boekhouding/config/klant_aliases_backup.json
   ```
2. If `klant_aliases` is empty (e.g. DB-restore-from-old-backup), re-run
   migration 34 by clearing the schema_version row for v34 and bouncing
   the app:
   ```
   sqlite3 ~/Library/Application\ Support/Boekhouding/data/boekhouding.sqlite3 \
     "DELETE FROM schema_version WHERE version = 34"
   # Then start the app — migration 34 runs and seeds from JSON snapshot.
   ```
3. If the JSON snapshot is also lost: alias auto-resolve will be empty;
   user adds via /klanten dialog as needed (auto-learn flow at next
   import will repopulate).

In other words: `_local.py` files are now permanently gone; the JSON
snapshot is the new authoritative recovery source.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: remove _local.py files (data now in klant_aliases + JSON snapshot)"
```

---

### Task 14: Delete one-shot scripts

- [ ] **Step 1: Remove**

```bash
git rm scripts/audit_missing_locaties.py
git rm scripts/verify_public_safe.py
git rm scripts/export_klant_aliases.py
git commit -m "chore: remove one-shot migration/audit scripts"
```

---

### Task 15: Push to GitHub

- [ ] **Step 1: Final test run**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 2: Verify branch state**

```
git status
git log --oneline | head -15
git remote -v
```

- [ ] **Step 3: Push**

```bash
git push origin kosten-categorisation-consolidation
```

(Not force-push — yesterday's force-push rewrote history; today's
commits are linear additions.)

- [ ] **Step 4: Verify on GitHub**

```
gh api repos/Ragnvald88/roberg-boekhouding/commits/kosten-categorisation-consolidation --jq '.sha[:7]'
```

Expected: matches `git rev-parse HEAD`.

- [ ] **Step 5: (Optional) flip repo back to public**

ONLY if user confirms:

```bash
gh repo edit Ragnvald88/roberg-boekhouding --visibility public
```

---

## Self-review

**Spec coverage check:**
- ✅ klant_aliases table → Task 1
- ✅ Migration 33 + 34 (with JSON fallback) → Tasks 1, 2, 11
- ✅ derive_skip_words → Task 4
- ✅ KLANT_LOCATIES schrap + audit → Tasks 10, 12
- ✅ resolve_klant async refactor + 4 strategies → Task 6
- ✅ resolve_anw_klant SQL with 1 placeholder → Task 6 (codex finding 3 fixed)
- ✅ pdf_parser skip_words param + case-insensitive → Task 5
- ✅ pages/facturen.py callers → Task 7
- ✅ Per-row remember-checkbox + auto-learn + conflict modal → Task 8
- ✅ Alias-CRUD UI in shared_ui.open_klant_dialog → Task 9
- ✅ Public-safety verificatie → Task 12
- ✅ Cleanup _local.py + .gitignore + JSON safety net → Tasks 11, 13
- ✅ Push → Task 15
- ✅ Klant16-leak scrub → Task 7b
- ✅ Underscore in `_MIGRATION_CALLABLES` → Task 2

**Placeholder scan:** No "TBD", "TODO" placeholders remain. Every
shell-command and code-block is concrete.

**Type / signature consistency:**
- `update_klant_alias_target(db_path, alias_id, expected_old_klant_id, new_klant_id) -> bool` — Tasks 3, 8
- `remember_alias(db_path, klant_id, pdf_extracted_name, filename_suffix) -> dict` — Tasks 3, 8
- `resolve_klant(db_path, pdf_name, filename_suffix) -> tuple` — Tasks 6, 7

**TDD coverage**:
- Task 1: 7 tests before code
- Task 2: 4 tests before code
- Task 3: 13 tests before code (CRUD + remember_alias)
- Task 4: 13 tests before code
- Task 5: 1 test before code (case-insensitive)
- Task 6: refactor with full test suite as safety net (all-in-one commit)
- Task 7, 8: manual smoke (UI; helper logic already covered)
- Task 9: 3 round-trip tests before UI

Plan v2 ready for execution.
