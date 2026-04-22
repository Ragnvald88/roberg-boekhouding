# Kosten categorisation consolidation + table fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three UI defects on `/kosten` (invisible bedrag column, non-working categorie dropdown, mislabeled KPI) and consolidate bank-debit categorisation so `/bank` and `/kosten` write to the same backing column (`uitgaven.categorie`).

**Architecture:** Mostly small surgical edits. The only new data-layer moves are a callable migration (`_run_migration_27`) that back-fills existing bank-side debit categorie into linked uitgaven, and two tiny module-level helpers extracted from the `/bank` page closures so they can be unit-tested. No schema changes.

**Tech Stack:** Python 3.12, NiceGUI ≥3.0 (Quasar slots via `ui.table.add_slot`), aiosqlite, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-04-21-kosten-categorisation-consolidation-design.md`

---

## File Structure

**Files to modify:**
- `database.py` — add migration 27 (callable + MIGRATIONS entry + `_MIGRATION_CALLABLES` registration); add two helper functions for the /bank unification.
- `pages/kosten.py` — column widths, rewrite tegenpartij slot, rewrite categorie slot, remove `window.__KOSTEN_CAT_LIST__` injection, rename KPI label.
- `pages/bank.py` — use the new `get_uitgave_categorie_by_bank_tx` helper in `load_transacties`; replace `handle_categorie_change` body with a call to the new `set_banktx_categorie` helper; add caption above the table.

**Files to create:**
- `tests/test_migration_27.py` — unit tests for the back-fill migration.
- `tests/test_bank_categorie_routing.py` — unit tests for the sign-branching write path and the derived-categorie lookup helper.

**No files deleted.**

---

## Task 1: Migration 27 — back-fill bank-debit categorie into linked uitgaven

**Files:**
- Create: `tests/test_migration_27.py`
- Modify: `database.py` — add `_run_migration_27` function, entry in `MIGRATIONS` list at line 329, registration in `_MIGRATION_CALLABLES` at line 608.

- [ ] **Step 1: Write failing tests for migration 27**

Create `tests/test_migration_27.py`:

```python
"""Migration #27 — back-fill bank-debit categorie into linked uitgaven."""
import aiosqlite
import pytest


async def _seed_banktx(db_path, id_, datum, bedrag, categorie='',
                       tegenpartij='', omschrijving='', genegeerd=0):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, categorie, tegenpartij, omschrijving, "
            "genegeerd) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id_, datum, bedrag, categorie, tegenpartij, omschrijving,
             genegeerd))
        await conn.commit()


async def _seed_uitgave(db_path, id_, datum, bedrag, categorie='',
                        omschrijving='x', bank_tx_id=None):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO uitgaven "
            "(id, datum, categorie, omschrijving, bedrag, bank_tx_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id_, datum, categorie, omschrijving, bedrag, bank_tx_id))
        await conn.commit()


async def _get_uitgaven(db_path):
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT id, datum, bedrag, categorie, omschrijving, bank_tx_id "
            "FROM uitgaven ORDER BY id")
        return [dict(r) for r in await cur.fetchall()]


async def _run_migration(db_path):
    """Re-invoke _run_migration_27 on an already-initialised DB."""
    from database import _run_migration_27
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        await _run_migration_27(conn)
        await conn.commit()


@pytest.mark.asyncio
async def test_lazy_creates_uitgave_for_debit_with_categorie(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Telefoon/KPN', tegenpartij='KPN BV')
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert len(rows) == 1
    assert rows[0]['bank_tx_id'] == 1
    assert rows[0]['categorie'] == 'Telefoon/KPN'
    assert rows[0]['bedrag'] == 50.0
    assert rows[0]['omschrijving'] == 'KPN BV'


@pytest.mark.asyncio
async def test_copies_categorie_into_empty_linked_uitgave(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Verzekeringen', tegenpartij='Boekhouder')
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='', bank_tx_id=1)
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert len(rows) == 1
    assert rows[0]['id'] == 10
    assert rows[0]['categorie'] == 'Verzekeringen'


@pytest.mark.asyncio
async def test_does_not_overwrite_nonempty_uitgave_categorie(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Verzekeringen')
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='Representatie', bank_tx_id=1)
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows[0]['categorie'] == 'Representatie'


@pytest.mark.asyncio
async def test_skips_definitief_year(db):
    await _seed_banktx(db, 1, '2025-03-15', -50.0,
                       categorie='Telefoon/KPN')
    # Mark 2025 as definitief.
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (?, ?)", (2025, 'definitief'))
        await conn.commit()
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows == []


@pytest.mark.asyncio
async def test_skips_genegeerd_rows(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Telefoon/KPN', genegeerd=1)
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows == []


@pytest.mark.asyncio
async def test_skips_debits_with_empty_categorie(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0, categorie='')
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows == []


@pytest.mark.asyncio
async def test_skips_positive_transactions(db):
    await _seed_banktx(db, 1, '2026-03-15', +100.0,
                       categorie='Omzet')
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows == []


@pytest.mark.asyncio
async def test_idempotent(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Telefoon/KPN', tegenpartij='KPN BV')
    await _run_migration(db)
    first = await _get_uitgaven(db)
    await _run_migration(db)
    second = await _get_uitgaven(db)

    assert first == second


@pytest.mark.asyncio
async def test_fallback_omschrijving_when_no_tegenpartij(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Bankkosten',
                       tegenpartij='', omschrijving='rente')
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows[0]['omschrijving'] == 'rente'


@pytest.mark.asyncio
async def test_fallback_omschrijving_when_all_empty(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0,
                       categorie='Bankkosten',
                       tegenpartij='', omschrijving='')
    await _run_migration(db)

    rows = await _get_uitgaven(db)
    assert rows[0]['omschrijving'] == '(bank tx)'
```

- [ ] **Step 2: Run test file to confirm it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_migration_27.py -v`
Expected: all tests FAIL with `ImportError: cannot import name '_run_migration_27' from 'database'`.

- [ ] **Step 3: Add `_run_migration_27` function to `database.py`**

Insert the following function in `database.py` after the existing migration callables block (after `_run_migration_21`, around line 608 — just before the `_MIGRATION_CALLABLES` dict):

```python
async def _run_migration_27(conn):
    """Copy banktransacties.categorie (debits only) into uitgaven.categorie.

    Pre-rework, users categorised debits via /bank, writing to
    banktransacties.categorie. Post-rework, get_kosten_view only reads
    uitgaven.categorie, so that data became orphaned. This migration
    reconciles: for each bank debit with a non-empty categorie, either
    update the linked uitgave (if empty-categorie) or lazy-create a new
    uitgave carrying the categorie.

    Skipped:
    - Bank rows marked genegeerd=1 (privé — not business expenses).
    - Rows whose year is jaarafsluiting_status='definitief' (frozen —
      snapshot-rendered; retroactive uitgaven creation would drift the
      underlying data from the snapshot).
    - Linked uitgaven whose categorie is already non-empty (user's own
      /kosten entry wins — never overwritten).

    Idempotent: re-running is a no-op.
    """
    cur = await conn.execute(
        "SELECT jaar FROM fiscale_params "
        "WHERE jaarafsluiting_status = 'definitief'")
    frozen = {r[0] for r in await cur.fetchall()}

    cur = await conn.execute("""
        SELECT b.id AS b_id, b.datum AS datum, b.bedrag AS bedrag,
               b.tegenpartij AS tegenpartij, b.omschrijving AS omschrijving,
               b.categorie AS categorie, u.id AS uitgave_id,
               u.categorie AS uitgave_cat
        FROM banktransacties b
        LEFT JOIN uitgaven u ON u.bank_tx_id = b.id
        WHERE b.bedrag < 0
          AND b.genegeerd = 0
          AND b.categorie IS NOT NULL
          AND b.categorie != ''
    """)
    candidates = await cur.fetchall()

    for row in candidates:
        jaar = int(row['datum'][:4])
        if jaar in frozen:
            continue

        if row['uitgave_id'] is not None:
            if not (row['uitgave_cat'] or '').strip():
                await conn.execute(
                    "UPDATE uitgaven SET categorie = ? WHERE id = ?",
                    (row['categorie'], row['uitgave_id']))
        else:
            omschrijving = (
                (row['tegenpartij'] or '').strip()
                or (row['omschrijving'] or '').strip()
                or '(bank tx)')
            await conn.execute(
                "INSERT INTO uitgaven "
                "(datum, categorie, omschrijving, bedrag, bank_tx_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (row['datum'], row['categorie'], omschrijving,
                 abs(row['bedrag']), row['b_id']))
```

- [ ] **Step 4: Register migration 27 in the `MIGRATIONS` list**

In `database.py`, find the `MIGRATIONS` list (starts at line 329) and append a new tuple after the existing `(26, "add_kosten_rework_columns", …)` entry (line 453-462). The list ends with `]` at line 463:

```python
    (26, "add_kosten_rework_columns", [
        "ALTER TABLE uitgaven ADD COLUMN bank_tx_id INTEGER "
        "REFERENCES banktransacties(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS idx_uitgaven_bank_tx "
        "ON uitgaven(bank_tx_id)",
        "ALTER TABLE banktransacties ADD COLUMN genegeerd INTEGER "
        "NOT NULL DEFAULT 0 CHECK (genegeerd IN (0, 1))",
        "CREATE INDEX IF NOT EXISTS idx_bank_genegeerd "
        "ON banktransacties(genegeerd)",
    ]),
    (27, "migrate_bank_categorie_to_uitgaven", None),
]
```

- [ ] **Step 5: Register `_run_migration_27` in `_MIGRATION_CALLABLES`**

In `database.py` line 608, change:

```python
_MIGRATION_CALLABLES = {7: _run_migration_7, 8: _run_migration_8, 18: _run_migration_18, 20: _run_migration_20, 21: _run_migration_21}
```

to:

```python
_MIGRATION_CALLABLES = {7: _run_migration_7, 8: _run_migration_8, 18: _run_migration_18, 20: _run_migration_20, 21: _run_migration_21, 27: _run_migration_27}
```

- [ ] **Step 6: Run the migration tests — confirm PASS**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_migration_27.py -v`
Expected: 10 tests PASS.

- [ ] **Step 7: Run the full test suite — no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all existing tests PASS (0 failures).

- [ ] **Step 8: Commit**

```bash
git add database.py tests/test_migration_27.py
git commit -m "$(cat <<'EOF'
feat(kosten): migrate bank-debit categorie into uitgaven (migratie 27)

Back-fill categorie from banktransacties (debits) into linked/new
uitgaven so /kosten's unified view surfaces data that was previously
orphaned on the bank-side column. Idempotent; skips definitief years
and genegeerd rows.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `/kosten` table — fix column widths

**Files:**
- Modify: `pages/kosten.py:609-622` (the `columns = [...]` list inside `_laad_tabel`).

- [ ] **Step 1: Replace the columns list**

In `pages/kosten.py`, find the `columns = [...]` block at line 609 and replace it with:

```python
    columns = [
        {'name': 'datum', 'label': 'Datum', 'field': 'datum',
         'align': 'left', 'sortable': True,
         'style': 'width: 110px; min-width: 110px',
         'headerStyle': 'width: 110px; min-width: 110px'},
        {'name': 'tegenpartij', 'label': 'Tegenpartij / Omschrijving',
         'field': 'tegenpartij', 'align': 'left'},
        {'name': 'categorie', 'label': 'Categorie', 'field': 'categorie',
         'align': 'left',
         'style': 'width: 180px; min-width: 180px; max-width: 180px',
         'headerStyle': 'width: 180px; min-width: 180px; max-width: 180px'},
        {'name': 'factuur', 'label': 'Factuur', 'field': 'factuur_status',
         'align': 'left',
         'style': 'width: 130px; min-width: 130px; max-width: 130px',
         'headerStyle': 'width: 130px; min-width: 130px; max-width: 130px'},
        {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
         'align': 'right', 'sortable': True,
         'style': 'width: 120px; min-width: 120px; max-width: 120px; '
                   'font-variant-numeric: tabular-nums',
         'headerStyle': 'width: 120px; min-width: 120px; max-width: 120px'},
        {'name': 'acties', 'label': '', 'field': 'acties',
         'align': 'center',
         'style': 'width: 90px; min-width: 90px; max-width: 90px',
         'headerStyle': 'width: 90px; min-width: 90px; max-width: 90px'},
    ]
```

- [ ] **Step 2: Run the full test suite — no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: 0 failures.

- [ ] **Step 3: Commit**

```bash
git add pages/kosten.py
git commit -m "$(cat <<'EOF'
fix(kosten): set explicit column widths so bedrag stays visible

Quasar's table-layout: auto needs both min-width and max-width to
actually enforce column sizing. Tegenpartij column remains flex;
all other columns get hard widths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `/kosten` tegenpartij slot — truncate omschrijving

**Files:**
- Modify: `pages/kosten.py:827-852` (the `body-cell-tegenpartij` slot template inside `_laad_tabel`).

- [ ] **Step 1: Replace the slot template**

Find the block starting with `tbl.add_slot('body-cell-tegenpartij', '''` (line 827) and ending with `''')` (line 852). Replace the entire `add_slot` call with:

```python
            tbl.add_slot('body-cell-tegenpartij', '''
                <q-td :props="props">
                  <div class="row items-center q-gutter-sm"
                       style="width: 100%; flex-wrap: nowrap;">
                    <div
                         :style="`background:${props.row.color};
                                   color:white;
                                   width:30px;height:30px;
                                   border-radius:7px;
                                   display:grid;place-items:center;
                                   font-weight:700;font-size:11px;
                                   flex-shrink:0;`">
                      {{ props.row.initials }}
                    </div>
                    <div style="min-width: 0; flex: 1;">
                      <div style="font-weight:500;
                                   white-space:nowrap;
                                   overflow:hidden;
                                   text-overflow:ellipsis;"
                           :title="props.row.tegenpartij">
                        {{ props.row.tegenpartij }}
                      </div>
                      <div class="text-caption text-grey"
                           v-if="props.row.omschrijving &&
                                  props.row.omschrijving !== props.row.tegenpartij"
                           :title="props.row.omschrijving"
                           style="white-space:nowrap;
                                   overflow:hidden;
                                   text-overflow:ellipsis;">
                        {{ props.row.omschrijving }}
                      </div>
                    </div>
                  </div>
                </q-td>
            ''')
```

- [ ] **Step 2: Run the full test suite — no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: 0 failures.

- [ ] **Step 3: Commit**

```bash
git add pages/kosten.py
git commit -m "$(cat <<'EOF'
fix(kosten): truncate POS omschrijving with ellipsis + title tooltip

Long Rabobank POS metadata (terminal/apple-pay tokens) no longer
blows out the tegenpartij column. min-width:0 on the flex child
lets the ellipsis actually fire. Tooltip on hover preserves the
full string for the rare inspection case.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `/kosten` categorie slot — fix the dropdown bug

**Files:**
- Modify: `pages/kosten.py:854-873` (the `body-cell-categorie` slot template) and `pages/kosten.py:1031-1034` (the `ui.add_body_html` call).

- [ ] **Step 1: Replace the categorie slot template**

Find the block starting with `tbl.add_slot('body-cell-categorie', '''` (line 854) and ending with `''')` (line 873). Replace with:

```python
            tbl.add_slot('body-cell-categorie', r"""
                <q-td :props="props"
                      :class="props.row.categorie ? '' : 'bg-orange-1'">
                  <q-select
                    :model-value="props.row.categorie"
                    :options='""" + json.dumps(CATEGORIEEN) + r"""'
                    dense borderless emit-value map-options
                    placeholder="— kies —"
                    @update:model-value="val => $parent.$emit('set_cat',
                                                              {row: props.row,
                                                               cat: val})"
                    style="min-width: 160px" />
                </q-td>
            """)
```

(The `json` module is already imported at kosten.py line 6; `CATEGORIEEN` is already imported from `components.utils` at line 16.)

- [ ] **Step 2: Remove the `window.__KOSTEN_CAT_LIST__` injection**

Find the block at kosten.py line 1031-1034:

```python
    ui.add_body_html(
        '<script>window.__KOSTEN_CAT_LIST__ = '
        f'{json.dumps(CATEGORIEEN)};</script>'
    )
```

Delete these four lines entirely. Also delete the comment block immediately above (lines 1027-1030) which describes the now-removed injection:

```python
    # Inject the category list into a window global referenced by the
    # categorie-dropdown slot template inside the kosten table. Runs
    # once on page mount — previously lived inside _laad_tabel which
    # made it fire on every filter/refresh tick.
```

- [ ] **Step 3: Run the full test suite — no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: 0 failures.

- [ ] **Step 4: Commit**

```bash
git add pages/kosten.py
git commit -m "$(cat <<'EOF'
fix(kosten): replace categorie q-btn-dropdown with q-select

The previous q-btn-dropdown teleported its q-menu to body, so
q-item @click emits fired into a detached parent and the handler
never received them — clicking '— kies —' did nothing. q-select's
@update:model-value fires from the cell itself, reaching the
q-table as intended. Drops the window.__KOSTEN_CAT_LIST__ global;
options are now interpolated inline like /bank does.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `/kosten` KPI label rename

**Files:**
- Modify: `pages/kosten.py:505` (the string passed as the first positional arg to the `_card(...)` call for the `ontbreekt` KPI).

- [ ] **Step 1: Rename the KPI label**

Find the `_card(...)` call at kosten.py line 504-509:

```python
        _card(
            'Factuur ontbreekt',
            str(kpi.ontbreekt_count),
            format_euro(kpi.ontbreekt_bedrag),
            color='warning', icon='warning',
            on_click=lambda: None)  # filter via status dropdown manually
```

Change the first argument from `'Factuur ontbreekt'` to `'Te verwerken'`:

```python
        _card(
            'Te verwerken',
            str(kpi.ontbreekt_count),
            format_euro(kpi.ontbreekt_bedrag),
            color='warning', icon='warning',
            on_click=lambda: None)  # filter via status dropdown manually
```

- [ ] **Step 2: Run the full test suite — no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: 0 failures.

- [ ] **Step 3: Commit**

```bash
git add pages/kosten.py
git commit -m "$(cat <<'EOF'
fix(kosten): rename 'Factuur ontbreekt' KPI to 'Te verwerken'

The KPI counts ongecategoriseerd + ontbreekt (see database.py
get_kpi_kosten). The old label overclaimed; 'Te verwerken'
matches what the number actually represents.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Extract `get_uitgave_categorie_by_bank_tx` helper + test

**Files:**
- Create: `tests/test_bank_categorie_routing.py`
- Modify: `database.py` — add `get_uitgave_categorie_by_bank_tx` after the existing bank/uitgave helpers (put it adjacent to `get_categorie_suggestions`; grep to find that).

- [ ] **Step 1: Write failing tests for `get_uitgave_categorie_by_bank_tx`**

Create `tests/test_bank_categorie_routing.py`:

```python
"""Routing of /bank debit-categorie writes and display into uitgaven.*"""
import aiosqlite
import pytest

from database import (
    get_uitgave_categorie_by_bank_tx,
    set_banktx_categorie,
)


async def _seed_banktx(db_path, id_, datum, bedrag, categorie='',
                       tegenpartij=''):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, categorie, tegenpartij) "
            "VALUES (?, ?, ?, ?, ?)",
            (id_, datum, bedrag, categorie, tegenpartij))
        await conn.commit()


async def _seed_uitgave(db_path, id_, datum, bedrag, categorie='',
                        bank_tx_id=None):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO uitgaven "
            "(id, datum, categorie, omschrijving, bedrag, bank_tx_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id_, datum, categorie, 'x', bedrag, bank_tx_id))
        await conn.commit()


async def _get_banktx_categorie(db_path, id_):
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT categorie FROM banktransacties WHERE id = ?", (id_,))
        return (await cur.fetchone())[0]


async def _uitgave_count_for(db_path, bank_tx_id):
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM uitgaven WHERE bank_tx_id = ?",
            (bank_tx_id,))
        return (await cur.fetchone())[0]


async def _get_uitgave_categorie(db_path, bank_tx_id):
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT categorie FROM uitgaven WHERE bank_tx_id = ?",
            (bank_tx_id,))
        row = await cur.fetchone()
        return row[0] if row else None


# ---------- get_uitgave_categorie_by_bank_tx ----------

@pytest.mark.asyncio
async def test_returns_empty_dict_when_no_linked_uitgaven(db):
    result = await get_uitgave_categorie_by_bank_tx(db)
    assert result == {}


@pytest.mark.asyncio
async def test_returns_mapping_for_linked_uitgaven(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0)
    await _seed_banktx(db, 2, '2026-03-16', -30.0)
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='Telefoon/KPN', bank_tx_id=1)
    await _seed_uitgave(db, 11, '2026-03-16', 30.0,
                        categorie='Bankkosten', bank_tx_id=2)

    result = await get_uitgave_categorie_by_bank_tx(db)
    assert result == {1: 'Telefoon/KPN', 2: 'Bankkosten'}


@pytest.mark.asyncio
async def test_excludes_manual_uitgaven(db):
    # Manual uitgave = bank_tx_id NULL. Must not appear in the map.
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='Kantoor', bank_tx_id=None)
    result = await get_uitgave_categorie_by_bank_tx(db)
    assert result == {}


# ---------- set_banktx_categorie ----------

@pytest.mark.asyncio
async def test_set_categorie_on_debit_writes_to_uitgave(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0, tegenpartij='KPN')
    await set_banktx_categorie(db, bank_tx_id=1, categorie='Telefoon/KPN')

    # uitgave lazy-created with categorie set
    assert await _uitgave_count_for(db, 1) == 1
    assert await _get_uitgave_categorie(db, 1) == 'Telefoon/KPN'
    # bank row's categorie column is untouched
    assert await _get_banktx_categorie(db, 1) == ''


@pytest.mark.asyncio
async def test_set_categorie_on_positive_writes_to_banktransacties(db):
    await _seed_banktx(db, 1, '2026-03-15', +100.0)
    await set_banktx_categorie(db, bank_tx_id=1, categorie='Omzet')

    assert await _get_banktx_categorie(db, 1) == 'Omzet'
    assert await _uitgave_count_for(db, 1) == 0  # no uitgave created


@pytest.mark.asyncio
async def test_set_categorie_on_debit_updates_existing_uitgave(db):
    await _seed_banktx(db, 1, '2026-03-15', -50.0)
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='', bank_tx_id=1)
    await set_banktx_categorie(db, bank_tx_id=1, categorie='Telefoon/KPN')

    assert await _uitgave_count_for(db, 1) == 1
    assert await _get_uitgave_categorie(db, 1) == 'Telefoon/KPN'


@pytest.mark.asyncio
async def test_set_categorie_on_debit_overrides_existing_categorie(db):
    # User had previously categorised as Representatie; now picks
    # Telefoon/KPN on /bank. The update must land even when the linked
    # uitgave already had a non-empty categorie.
    await _seed_banktx(db, 1, '2026-03-15', -50.0)
    await _seed_uitgave(db, 10, '2026-03-15', 50.0,
                        categorie='Representatie', bank_tx_id=1)
    await set_banktx_categorie(db, bank_tx_id=1, categorie='Telefoon/KPN')

    assert await _get_uitgave_categorie(db, 1) == 'Telefoon/KPN'


@pytest.mark.asyncio
async def test_set_categorie_on_debit_year_locked_raises(db):
    from database import YearLockedError
    await _seed_banktx(db, 1, '2025-03-15', -50.0)
    await _seed_uitgave(db, 10, '2025-03-15', 50.0,
                        categorie='', bank_tx_id=1)
    # Directly INSERT the fiscale_params row so the year-lock gate fires.
    # (update_jaarafsluiting_status is pure UPDATE; it would be a no-op
    # without an existing row.)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (?, ?)", (2025, 'definitief'))
        await conn.commit()

    with pytest.raises(YearLockedError):
        await set_banktx_categorie(
            db, bank_tx_id=1, categorie='Telefoon/KPN')


@pytest.mark.asyncio
async def test_set_categorie_missing_banktx_raises(db):
    with pytest.raises(ValueError):
        await set_banktx_categorie(db, bank_tx_id=999, categorie='Kantoor')
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_bank_categorie_routing.py -v`
Expected: all tests FAIL with `ImportError: cannot import name 'get_uitgave_categorie_by_bank_tx' from 'database'`.

- [ ] **Step 3: Implement `get_uitgave_categorie_by_bank_tx` in `database.py`**

Find `get_categorie_suggestions` in `database.py` (grep for the name) and add the following function **after** it:

```python
async def get_uitgave_categorie_by_bank_tx(
    db_path: Path = DB_PATH,
) -> dict[int, str]:
    """Return {bank_tx_id: categorie} for every uitgave linked to a bank tx.

    Used by /bank to surface the authoritative categorie for debit rows
    (since the debit's own banktransacties.categorie is no longer the
    source of truth after the Kosten rework). Single round-trip.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT bank_tx_id, categorie FROM uitgaven "
            "WHERE bank_tx_id IS NOT NULL")
        rows = await cur.fetchall()
    return {r[0]: (r[1] or '') for r in rows}
```

- [ ] **Step 4: Implement `set_banktx_categorie` in `database.py`**

Add the following function **directly after** `get_uitgave_categorie_by_bank_tx`:

```python
async def set_banktx_categorie(
    db_path: Path,
    bank_tx_id: int,
    categorie: str,
) -> None:
    """Write a categorie for a bank tx, routing by sign.

    Debits (bedrag < 0) → route into uitgaven.categorie via
    ensure_uitgave_for_banktx so /bank and /kosten agree.
    Positives (bedrag >= 0) → stay on banktransacties.categorie.

    Year-locked: the call chain (ensure_uitgave_for_banktx on create,
    update_uitgave on update, update_banktransactie on positives) each
    enforce assert_year_writable, so YearLockedError surfaces naturally.

    Raises ValueError if the bank tx doesn't exist.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT bedrag FROM banktransacties WHERE id = ?",
            (bank_tx_id,))
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"banktransactie {bank_tx_id} not found")

    if row['bedrag'] < 0:
        # ensure_uitgave_for_banktx returns the uitgave id (creating if
        # missing). On the create path it sets categorie via overrides;
        # on the already-linked path it returns early without touching
        # categorie — so we call update_uitgave explicitly afterwards.
        # update_uitgave re-enforces the year-lock on the existing row.
        uitgave_id = await ensure_uitgave_for_banktx(
            db_path, bank_tx_id=bank_tx_id, categorie=categorie)
        await update_uitgave(
            db_path, uitgave_id=uitgave_id, categorie=categorie)
    else:
        await update_banktransactie(
            db_path, transactie_id=bank_tx_id, categorie=categorie)
```

- [ ] **Step 5: Run the routing tests — confirm PASS**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_bank_categorie_routing.py -v`
Expected: 9 tests PASS.

- [ ] **Step 6: Run the full test suite — no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: 0 failures.

- [ ] **Step 7: Commit**

```bash
git add database.py tests/test_bank_categorie_routing.py
git commit -m "$(cat <<'EOF'
feat(database): extract bank-debit categorie routing helpers

Adds get_uitgave_categorie_by_bank_tx (display-side lookup) and
set_banktx_categorie (sign-branching write path). Both are covered
by tests and will be wired into pages/bank.py next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `/bank` display-side — show debit categorie from uitgaven

**Files:**
- Modify: `pages/bank.py` — the `load_transacties` closure (around line 37-81) and the imports at the top.

- [ ] **Step 1: Add the helper to the `database` import in `pages/bank.py`**

Find the existing import block at pages/bank.py line 11-16:

```python
from database import (
    get_banktransacties, get_imported_csv_bestanden,
    add_banktransacties, update_banktransactie,
    delete_banktransacties, find_factuur_matches, apply_factuur_matches,
    get_categorie_suggestions, get_db_ctx, DB_PATH,
)
```

Add `get_uitgave_categorie_by_bank_tx` and `set_banktx_categorie`:

```python
from database import (
    get_banktransacties, get_imported_csv_bestanden,
    add_banktransacties, update_banktransactie,
    delete_banktransacties, find_factuur_matches, apply_factuur_matches,
    get_categorie_suggestions, get_uitgave_categorie_by_bank_tx,
    set_banktx_categorie, get_db_ctx, DB_PATH,
)
```

- [ ] **Step 2: Override the displayed categorie for debits inside `load_transacties`**

Find `async def load_transacties` in `pages/bank.py` (around line 37). Locate the `rows = []` line and the `for t in transacties:` loop immediately after it (around line 50). Just **before** the `rows = []` line, add one call to fetch the override map:

```python
        # For debit rows, the authoritative categorie lives on the linked
        # uitgave (post-Kosten-rework). Fetch the override map once.
        debit_cat_map = await get_uitgave_categorie_by_bank_tx(DB_PATH)
```

Then **inside** the `for t in transacties:` loop, after the existing `status = ...` / `suggested = ...` block but **before** the `rows.append({ ... })` dict literal, replace the `'categorie': t.categorie,` line in the appended dict so that debits read from the override map. Concretely, the full updated loop body should read:

```python
        for t in transacties:
            # Determine status for color coding
            if t.koppeling_type and t.koppeling_id:
                status = 'gekoppeld'
            elif t.categorie:
                status = 'gecategoriseerd'
            else:
                status = 'niet-gekoppeld'

            # Default: no suggestion
            suggested = ''
            # Apply suggestion for uncategorized rows with known counterparty
            if not t.categorie and t.tegenpartij:
                suggested = cat_suggestions['map'].get(t.tegenpartij.lower(), '')

            # Debits display the linked-uitgave categorie (unified source);
            # positives keep their own banktransacties.categorie.
            if t.bedrag < 0:
                displayed_cat = debit_cat_map.get(t.id, '')
            else:
                displayed_cat = t.categorie

            # Re-evaluate status for debits based on the unified categorie.
            if t.bedrag < 0 and displayed_cat and not (t.koppeling_type and t.koppeling_id):
                status = 'gecategoriseerd'
            elif t.bedrag < 0 and not displayed_cat and not (t.koppeling_type and t.koppeling_id):
                status = 'niet-gekoppeld'

            rows.append({
                'id': t.id,
                'datum': t.datum,
                'datum_fmt': format_datum(t.datum),
                'bedrag': t.bedrag,
                'bedrag_fmt': format_euro(t.bedrag),
                'tegenpartij': t.tegenpartij,
                'omschrijving': t.omschrijving[:80] + ('...' if len(t.omschrijving) > 80 else ''),
                'omschrijving_full': t.omschrijving,
                'categorie': displayed_cat,
                'suggested_categorie': suggested,
                'koppeling': f"{t.koppeling_type} #{t.koppeling_id}" if t.koppeling_type else '',
                'status': status,
                'csv_bestand': t.csv_bestand,
            })
```

- [ ] **Step 3: Run the full test suite — no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: 0 failures.

- [ ] **Step 4: Commit**

```bash
git add pages/bank.py
git commit -m "$(cat <<'EOF'
feat(bank): display debit categorie from linked uitgave

After the Kosten rework, uitgaven.categorie is the authoritative
source for bank-debit categorie. /bank now reads from it on display
so both pages agree. Positive rows continue to use
banktransacties.categorie (Omzet/Prive/etc.).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `/bank` write-side — route debit categorie into uitgaven

**Files:**
- Modify: `pages/bank.py` — the `handle_categorie_change` closure (around line 248-252).

- [ ] **Step 1: Replace `handle_categorie_change` body**

Find the closure at pages/bank.py line 248-252:

```python
    async def handle_categorie_change(row_id: int, new_cat: str):
        """Update category for a bank transaction."""
        await update_banktransactie(DB_PATH, transactie_id=row_id, categorie=new_cat)
        ui.notify('Categorie bijgewerkt', type='positive')
        await refresh_table()
```

Replace it with:

```python
    async def handle_categorie_change(row_id: int, new_cat: str):
        """Update category for a bank transaction.

        Debits route into uitgaven.categorie (unified with /kosten);
        positives stay on banktransacties.categorie.
        """
        try:
            await set_banktx_categorie(
                DB_PATH, bank_tx_id=row_id, categorie=new_cat)
        except ValueError as e:
            ui.notify(str(e), type='negative')
            return
        ui.notify('Categorie bijgewerkt', type='positive')
        await refresh_table()
```

- [ ] **Step 2: Run the full test suite — no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: 0 failures.

- [ ] **Step 3: Commit**

```bash
git add pages/bank.py
git commit -m "$(cat <<'EOF'
feat(bank): route debit categorie writes into uitgaven.categorie

handle_categorie_change now delegates to set_banktx_categorie which
branches on bedrag sign. /bank and /kosten write to the same backing
column for debits — no more orphan data.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `/bank` — add clarifying caption above the table

**Files:**
- Modify: `pages/bank.py` — insert a caption between the bank-page filter bar and the legend/table (look for the `# Color legend` comment, around line 400).

- [ ] **Step 1: Add the caption**

Find the `# Color legend` block at pages/bank.py (search for `'Gekoppeld aan factuur'` to locate it). Just **before** the `# Color legend` comment block and its `with ui.row()` that follows, insert:

```python
        ui.label(
            'Categorieën op debit-regels worden centraal in Kosten '
            'opgeslagen.'
        ).classes('text-caption text-grey-7 q-mb-xs')
```

- [ ] **Step 2: Run the full test suite — no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: 0 failures.

- [ ] **Step 3: Commit**

```bash
git add pages/bank.py
git commit -m "$(cat <<'EOF'
docs(bank): clarify that debit categorieën live in Kosten

One-line caption explaining the unified backing so a user editing
categorieën on /bank knows why the same data appears on /kosten.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Widget acceptance test + final regression pass

**Files:** none modified — this is the ship gate.

- [ ] **Step 1: Run the full test suite one more time**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: 0 failures, all tests green.

- [ ] **Step 2: Launch the app in native mode**

```bash
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py
```

A 1400×900 pywebview window should open.

- [ ] **Step 3: `/kosten` visual + click-through checks**

Navigate to `/kosten` for the current year. Confirm each bullet:

- All six columns are visible without horizontal scroll; Bedrag sits flush on the right edge.
- A Coolblue row (or any card-POS row) shows its description truncated with `…`. Hovering shows the full POS metadata in a browser tooltip.
- Rows with no categorie show an orange-tinted cell and the placeholder `— kies —`.
- Click a `— kies —` cell → dropdown opens.
- Pick `Telefoon/KPN`. Confirm:
  - Toast "Categorie bijgewerkt naar Telefoon/KPN" appears.
  - Cell's orange tint disappears; cell now shows `Telefoon/KPN`.
  - Factuur badge for that row changes from `Nieuw` to `Ontbreekt` (amber).
  - The KPI "Te verwerken" count does NOT change (both `ongecategoriseerd` and `ontbreekt` count towards it).

If any bullet fails, stop and investigate before proceeding.

- [ ] **Step 4: `/bank` cross-page consistency checks**

Navigate to `/bank`. Confirm:

- Caption "Categorieën op debit-regels worden centraal in Kosten opgeslagen." appears above the table.
- Find the same bank row you just categorised on /kosten. Its categorie cell already shows `Telefoon/KPN` (unified backing).
- Pick `Bankkosten` on a different debit row. Confirm toast appears.
- Navigate to `/kosten`. Confirm that bank row now shows `Bankkosten` in the categorie cell.
- Back on `/bank`, pick `Omzet` on a positive (green) row. Confirm toast.
- Navigate to `/kosten`. Confirm that positive row does NOT appear in the kosten view (positives are excluded from `get_kosten_view`).

- [ ] **Step 5: Regression smoke-tests**

Still in the running app:

- On `/kosten`, select 2 rows and open the bulk "Categorie wijzigen" dialog; apply `Overige kosten`. Confirm toast and that both rows reflect the change.
- On `/kosten`, click "Nieuwe uitgave"; fill in datum, categorie (`Representatie`), omschrijving (`test lunch`), bedrag (`25.00`); save. Confirm the new row appears in the table.
- On `/bank`, import a test CSV (if you have one) or just verify the match-preview dialog has no errors on page load.

- [ ] **Step 6: Close the app and verify the commit history**

Quit the app. Run:

```bash
git log --oneline -15
```

Expected: 9 new commits from this plan — one per task (2 through 9), plus the migration commit from task 1. Task 10 is verification only, no commit.

- [ ] **Step 7: Nothing to commit — done**

If every check passed, the feature is ready. No final commit needed — tasks 1-9 each committed their own work.

If any step failed, rollback and investigate: `git log --oneline` to identify the offending task; `git revert <sha>` for that task; re-run the affected plan task.

---

## Out-of-scope — do NOT implement in this plan

Per the spec, these are explicitly deferred:

- Auto-hiding own-IBAN / Belastingdienst / owner-draw rows.
- Suggestion-toverstaf on `/kosten`.
- Inbox card redesign.
- Removal of `banktransacties.categorie` column.
- Filtering the `/bank` dropdown options for positive rows.

If any of these seem relevant while implementing, note them for a follow-up spec — do not sneak them in.
