# Revenue Consistency & Vergoeding Type — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `type='vergoeding'` for ad-hoc facturen without werkdagen, fix 2025 orphan data, and make the distinction visible in the UI.

**Architecture:** Single migration (21) handles data linkage + type classification. Invoice builder auto-detects type on save. Facturen page shows type-based icons and filter. Dashboard uren label clarified.

**Tech Stack:** Python 3.12, SQLite (aiosqlite), NiceGUI/Quasar, pytest

**Spec:** `docs/superpowers/specs/2026-03-26-revenue-consistency-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `database.py` | Modify | Migration 21 (callable), fix `get_openstaande_facturen` |
| `components/invoice_builder.py` | Modify (line ~703) | Auto-detect type on factuur save |
| `pages/facturen.py` | Modify (lines 86-96, 115-122, 174-196, 653-679, 758) | Type icons, filter, CSV, edit dialog |
| `pages/dashboard.py` | Modify (line ~393) | Uren label "(urencriterium)" |
| `CLAUDE.md` | Modify | Document type='vergoeding' |
| `tests/test_db_queries.py` | Modify | Migration + openstaande_facturen tests |
| `tests/test_facturen.py` | Modify | Auto-detect type tests |

---

### Task 1: Database migration 21 + fix get_openstaande_facturen

**Files:**
- Modify: `database.py` — add `(21, "classify_vergoeding_type", None)` to `MIGRATIONS` list (after line 353), add `_run_migration_21` callable (after line 476), register in `_MIGRATION_CALLABLES` (line 478), fix `get_openstaande_facturen` (line 1697)
- Test: `tests/test_db_queries.py`

- [ ] **Step 1: Write test for vergoeding classification query**

The migration runs during `init_db` before test data is inserted, so we test the classification SQL directly. In `tests/test_db_queries.py`:

```python
@pytest.mark.asyncio
async def test_classify_orphan_facturen_as_vergoeding(tmp_path):
    """Facturen without linked werkdagen get type='vergoeding' when classified."""
    db = tmp_path / "test.sqlite3"
    await init_db(db)
    klant_id = await add_klant(db, naam="Test Klant")

    # Factuur WITH werkdagen — should stay type='factuur'
    await add_factuur(db, nummer="2025-001", klant_id=klant_id,
                      datum="2025-01-15", totaal_bedrag=500.0, status="betaald")
    await add_werkdag(db, datum="2025-01-15", klant_id=klant_id,
                      uren=8.0, tarief=62.50, factuurnummer="2025-001")

    # Factuur WITHOUT werkdagen — should become vergoeding
    await add_factuur(db, nummer="2025-099", klant_id=klant_id,
                      datum="2025-03-01", totaal_bedrag=300.0, status="betaald")

    # Concept factuur WITHOUT werkdagen — should stay factuur (WIP)
    await add_factuur(db, nummer="2025-100", klant_id=klant_id,
                      datum="2025-04-01", totaal_bedrag=100.0, status="concept")

    # Run classification query (same SQL as migration 21)
    async with get_db_ctx(db) as conn:
        await conn.execute("""
            UPDATE facturen SET type = 'vergoeding'
            WHERE type = 'factuur'
            AND NOT EXISTS (
                SELECT 1 FROM werkdagen w WHERE w.factuurnummer = facturen.nummer
            )
            AND status != 'concept'
        """)
        await conn.commit()

    facturen = await get_facturen(db)
    by_nummer = {f.nummer: f for f in facturen}
    assert by_nummer["2025-001"].type == 'factuur'
    assert by_nummer["2025-099"].type == 'vergoeding'
    assert by_nummer["2025-100"].type == 'factuur'  # concept stays factuur
```

- [ ] **Step 2: Write test for get_openstaande_facturen including vergoedingen**

```python
@pytest.mark.asyncio
async def test_openstaande_facturen_includes_vergoedingen(tmp_path):
    """Unpaid vergoedingen must appear in openstaande facturen."""
    db = tmp_path / "test.sqlite3"
    await init_db(db)
    klant_id = await add_klant(db, naam="Test Klant")

    await add_factuur(db, nummer="2026-099", klant_id=klant_id,
                      datum="2026-03-01", totaal_bedrag=500.0,
                      status="verstuurd", type="vergoeding")

    openstaand = await get_openstaande_facturen(db)
    nummers = [f.nummer for f in openstaand]
    assert "2026-099" in nummers
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py::test_classify_orphan_facturen_as_vergoeding tests/test_db_queries.py::test_openstaande_facturen_includes_vergoedingen -v`

Expected: First test passes (query works on fresh data), second FAILS (`get_openstaande_facturen` excludes vergoedingen).

- [ ] **Step 4: Implement migration 21**

In `database.py`:

**A)** Add to `MIGRATIONS` list (after line 353, before the `]`):
```python
(21, "classify_vergoeding_type", None),  # handled by callable
```

**B)** Add callable (after `_run_migration_20`, before `_MIGRATION_CALLABLES`):
```python
async def _run_migration_21(conn):
    """Link 2025 orphan werkdagen to facturen, classify vergoeding type."""
    # Step A: Link 2025 orphan werkdagen to their facturen
    linkages = [
        # 't Klant6: 3 werkdagen → 2025-002
        ("UPDATE werkdagen SET factuurnummer = '2025-002' WHERE id IN (392, 397, 400)"),
        # Klant12 → 2025-025
        ("UPDATE werkdagen SET factuurnummer = '2025-025' WHERE id = 492"),
        # 't Klant6 → 2025-026
        ("UPDATE werkdagen SET factuurnummer = '2025-026' WHERE id = 493"),
        # Klant11 → 2025-027
        ("UPDATE werkdagen SET factuurnummer = '2025-027' WHERE id = 495"),
        # de Wilp → 2025-028
        ("UPDATE werkdagen SET factuurnummer = '2025-028' WHERE id = 496"),
    ]
    for sql in linkages:
        await conn.execute(sql)

    # Step B: Classify orphan facturen as vergoeding
    # (facturen with no linked werkdagen, not ANW, not concept)
    await conn.execute("""
        UPDATE facturen SET type = 'vergoeding'
        WHERE type = 'factuur'
        AND NOT EXISTS (
            SELECT 1 FROM werkdagen w
            WHERE w.factuurnummer = facturen.nummer
        )
        AND status != 'concept'
    """)
```

**C)** Register in `_MIGRATION_CALLABLES` (line 478):
```python
_MIGRATION_CALLABLES = {7: _run_migration_7, 8: _run_migration_8, 18: _run_migration_18, 20: _run_migration_20, 21: _run_migration_21}
```

- [ ] **Step 5: Fix get_openstaande_facturen — remove type filter**

In `database.py` line 1697, change:

```python
# Before:
WHERE f.status = 'verstuurd' AND f.type = 'factuur'

# After:
WHERE f.status = 'verstuurd'
```

Any verstuurd invoice (werkdag, ANW, or vergoeding) is openstaand. Note: this also includes ANW invoices which were previously excluded — correct behavior.

- [ ] **Step 6: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py -v`

Expected: ALL PASS

- [ ] **Step 7: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

Expected: All 487+ tests pass, no regressions.

- [ ] **Step 8: Commit**

```bash
git add database.py tests/test_db_queries.py
git commit -m "feat: migration 21 — link 2025 orphans + classify vergoeding type

Links 6 orphan werkdagen to their 2025 facturen.
Classifies facturen without werkdagen as type='vergoeding'.
Fixes get_openstaande_facturen to include vergoedingen and ANW."
```

---

### Task 2: Invoice builder auto-detection

**Files:**
- Modify: `components/invoice_builder.py` — around line 703, pass auto-detected type
- Test: `tests/test_facturen.py`

- [ ] **Step 1: Write tests for type parameter in add_factuur**

In `tests/test_facturen.py`:

```python
@pytest.mark.asyncio
async def test_factuur_type_vergoeding_round_trip(tmp_path):
    """Factuur with type='vergoeding' persists correctly."""
    db = tmp_path / "test.sqlite3"
    await init_db(db)
    klant_id = await add_klant(db, naam="Test Klant")

    await add_factuur(db, nummer="2026-099", klant_id=klant_id,
                      datum="2026-03-01", totaal_bedrag=500.0,
                      type="vergoeding")
    facturen = await get_facturen(db)
    f = [f for f in facturen if f.nummer == "2026-099"][0]
    assert f.type == 'vergoeding'


@pytest.mark.asyncio
async def test_factuur_type_defaults_to_factuur(tmp_path):
    """Factuur without explicit type stays type='factuur'."""
    db = tmp_path / "test.sqlite3"
    await init_db(db)
    klant_id = await add_klant(db, naam="Test Klant")

    await add_factuur(db, nummer="2026-100", klant_id=klant_id,
                      datum="2026-03-01", totaal_bedrag=500.0)
    facturen = await get_facturen(db)
    f = [f for f in facturen if f.nummer == "2026-100"][0]
    assert f.type == 'factuur'
```

- [ ] **Step 2: Run tests — should pass** (DB already supports type param)

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_facturen.py::test_factuur_type_vergoeding_round_trip tests/test_facturen.py::test_factuur_type_defaults_to_factuur -v`

- [ ] **Step 3: Modify invoice builder to pass auto-detected type**

In `components/invoice_builder.py` around line 703, change:

```python
# Before:
await add_factuur(
    DB_PATH,
    nummer=nummer,
    klant_id=kid,
    datum=factuur_datum,
    totaal_uren=totaal_uren,
    totaal_km=totaal_km,
    totaal_bedrag=totaal_bedrag,
    pdf_pad=str(pdf_path),
)

# After:
has_werkdagen = any(li.get('werkdag_id') for li in line_items)
factuur_type = 'factuur' if has_werkdagen else 'vergoeding'

await add_factuur(
    DB_PATH,
    nummer=nummer,
    klant_id=kid,
    datum=factuur_datum,
    totaal_uren=totaal_uren,
    totaal_km=totaal_km,
    totaal_bedrag=totaal_bedrag,
    pdf_pad=str(pdf_path),
    type=factuur_type,
)
```

- [ ] **Step 4: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add components/invoice_builder.py tests/test_facturen.py
git commit -m "feat: invoice builder auto-detects type='vergoeding' for free-form facturen"
```

---

### Task 3: Facturen page — type icons, filter, edit dialog, CSV

**Files:**
- Modify: `pages/facturen.py`
  - Lines 86-96: add type filter (after status filter)
  - Lines 115-122: add type to CSV headers
  - Lines 174-196: replace bron icons with type icons
  - Lines 653-655: update type badge in edit dialog
  - Lines 675-679: replace type selector with display-only badge
  - Line 758: remove `'type': edit_type.value` from save kwargs
  - `refresh_table()`: add type filter logic

- [ ] **Step 1: Add type filter after status filter**

After line 96, add (follow the existing async handler pattern):

```python
# Type filter
type_options = {'': 'Alle types', 'factuur': 'Werkdag',
                'anw': 'ANW/Dienst', 'vergoeding': 'Vergoeding'}
filter_type = {'value': ''}

async def on_type_filter(e):
    filter_type['value'] = e.value
    await refresh_table()

ui.select(type_options, value='', label='Type',
          on_change=on_type_filter).classes('w-36')
```

- [ ] **Step 2: Apply type filter in refresh_table()**

In the `refresh_table()` function, add type filtering alongside existing klant/status filters:

```python
if filter_type['value']:
    facturen = [f for f in facturen if f.type == filter_type['value']]
```

- [ ] **Step 3: Add `type` to table row data**

Ensure the row dict includes `'type': f.type` so the Vue template can access it. Check the row construction in `refresh_table()` and add if missing.

- [ ] **Step 4: Replace bron icons with type icons**

Replace lines 174-196 (the `body-cell-nummer` slot):

```python
table.add_slot('body-cell-nummer', '''
    <q-td :props="props">
        <div class="row items-center no-wrap gap-1">
            <q-icon
                v-if="props.row.type === 'vergoeding'"
                name="receipt_long"
                size="xs"
                color="amber-8"
            >
                <q-tooltip>Vergoeding</q-tooltip>
            </q-icon>
            <q-icon
                v-else-if="props.row.bron === 'import'"
                name="upload_file"
                size="xs"
                color="grey-6"
            >
                <q-tooltip>Geïmporteerd</q-tooltip>
            </q-icon>
            <q-icon
                v-else
                name="edit_note"
                size="xs"
                color="teal"
            >
                <q-tooltip>Aangemaakt in app</q-tooltip>
            </q-icon>
            {{ props.row.nummer }}
        </div>
    </q-td>
''')
```

- [ ] **Step 5: Update edit dialog — replace type selector with display-only badge**

At lines 653-655, replace:
```python
type_label = ('ANW' if row.get('type') == 'anw'
              else 'Dagpraktijk')
ui.badge(type_label, color='info').classes('q-ml-sm')
```

With:
```python
type_labels = {'factuur': 'Dagpraktijk', 'anw': 'ANW',
               'vergoeding': 'Vergoeding'}
type_colors = {'factuur': 'teal', 'anw': 'info',
               'vergoeding': 'amber-8'}
type_val = row.get('type', 'factuur')
ui.badge(type_labels.get(type_val, type_val),
         color=type_colors.get(type_val, 'grey')).classes('q-ml-sm')
```

- [ ] **Step 6: Remove type selector dropdown from edit dialog**

Remove lines 675-679 entirely (the `edit_type` select widget):
```python
# DELETE these lines:
# Type
edit_type = ui.select(
    {'factuur': 'Dagpraktijk', 'anw': 'ANW'},
    label='Type', value=row.get('type', 'factuur'),
).classes('w-full')
```

And remove `'type': edit_type.value` from the save kwargs at line 758:
```python
# Before:
kwargs = {
    'datum': edit_datum.value,
    'klant_id': edit_klant.value,
    'totaal_bedrag': float(edit_bedrag.value or 0),
    'type': edit_type.value,
}

# After:
kwargs = {
    'datum': edit_datum.value,
    'klant_id': edit_klant.value,
    'totaal_bedrag': float(edit_bedrag.value or 0),
}
```

- [ ] **Step 7: Add type to CSV export**

At lines 115-122, update headers and row data:

```python
headers = ['Nummer', 'Datum', 'Klant', 'Type', 'Uren', 'Km',
           'Bedrag', 'Status']
type_labels_csv = {'factuur': 'Werkdag', 'anw': 'ANW',
                   'vergoeding': 'Vergoeding'}
rows = [[f.nummer, f.datum, f.klant_naam,
         type_labels_csv.get(f.type, f.type),
         f.totaal_uren, f.totaal_km, f.totaal_bedrag,
         status_labels.get(f.status, f.status.capitalize())]
        for f in facturen]
```

Also apply the type filter to the CSV export (same filter_type logic as table).

- [ ] **Step 8: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

Expected: All pass.

- [ ] **Step 9: Manual smoke test**

Start app: `source .venv/bin/activate && export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib && python main.py`

Verify at http://127.0.0.1:8085/facturen:
- 2026-007 and 2026-018 show amber receipt icon
- Import facturen show grey upload icon
- App facturen show teal edit icon
- Type filter works: "Vergoeding" shows only ad-hoc facturen
- Edit dialog shows correct type badge, NO type dropdown
- CSV export includes Type column

- [ ] **Step 10: Commit**

```bash
git add pages/facturen.py
git commit -m "feat: facturen page — type icons, filter, edit badge, CSV column

Vergoeding facturen show amber receipt icon. Type filter added
next to status filter. Type selector removed from edit dialog
(auto-derived). CSV export includes type column."
```

---

### Task 4: Dashboard uren label

**Files:**
- Modify: `pages/dashboard.py` — line ~393

- [ ] **Step 1: Update uren label with clarification**

In `pages/dashboard.py` around line 393, change:

```python
# Before:
ui.label(
    f'{uren:,.0f} uur'.replace(',', '.')
).classes('strip-value')

# After:
ui.label(
    f'{uren:,.0f} uur'.replace(',', '.')
).classes('strip-value')
with ui.element('span').classes('text-caption text-grey-6').style(
        'margin-left: 4px'):
    ui.label('(urencriterium)')
    ui.tooltip('Exclusief achterwacht (urennorm=0)')
```

- [ ] **Step 2: Manual verification**

Open http://127.0.0.1:8085 — verify "292 uur (urencriterium)" with tooltip on hover.

- [ ] **Step 3: Commit**

```bash
git add pages/dashboard.py
git commit -m "fix: dashboard uren label — clarify urencriterium scope"
```

---

### Task 5: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document facturen.type values**

In the Database section, after the `facturen.status` line, add:

```markdown
- `facturen.type` TEXT: `'factuur'` (werkdag-backed), `'anw'` (imported ANW), `'vergoeding'` (ad-hoc, no werkdagen)
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document facturen.type='vergoeding' in CLAUDE.md"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

Expected: All tests pass.

- [ ] **Step 2: Verify data integrity on live DB**

```python
import sqlite3
conn = sqlite3.connect('data/boekhouding.sqlite3')

# Type distribution
print("=== Type distribution ===")
for r in conn.execute("SELECT type, COUNT(*) FROM facturen GROUP BY type"):
    print(r)

# No orphan facturen with type='factuur' (except concept)
print("\n=== Remaining orphan facturen (should be 0 or concept only) ===")
for r in conn.execute("""
    SELECT nummer, type, status FROM facturen
    WHERE type = 'factuur' AND status != 'concept'
    AND NOT EXISTS (SELECT 1 FROM werkdagen w WHERE w.factuurnummer = facturen.nummer)
"""):
    print(r)

# 2025 werkdagen linked
print("\n=== 2025 linked werkdagen ===")
for r in conn.execute("SELECT id, factuurnummer FROM werkdagen WHERE id IN (392,397,400,492,493,495,496)"):
    print(r)

conn.close()
```

- [ ] **Step 3: Full app smoke test**

Test at http://127.0.0.1:8085:
- Dashboard: uren shows "(urencriterium)" with tooltip
- Facturen: type icons correct, filter works, CSV includes type
- Bank import: auto-match still works (test with page load)
- Jaarafsluiting: renders without errors
