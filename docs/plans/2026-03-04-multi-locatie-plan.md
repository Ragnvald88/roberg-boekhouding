# Multi-Locatie per Klant — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add support for multiple work locations per client, with a location dropdown in the werkdag form that auto-fills km distance.

**Architecture:** New `klant_locaties` table with FK to `klanten`. Werkdag form dynamically shows a location dropdown after client selection. Location management via sub-section in the klant edit dialog on Instellingen. Seed data from Urenregister distance table.

**Tech Stack:** SQLite (aiosqlite), NiceGUI 3.8, Python 3.12+, pytest + pytest-asyncio

**Test command:** `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

---

### Task 1: Database Schema — New `klant_locaties` Table

**Files:**
- Modify: `database.py:13-149` (SCHEMA_SQL) and `database.py:161-197` (init_db migrations)
- Modify: `models.py` (add KlantLocatie dataclass)
- Modify: `tests/test_database.py:27-30` (update expected tables)

**Step 1: Add KlantLocatie to models.py**

Add after the `Klant` dataclass (after line 28):

```python
@dataclass
class KlantLocatie:
    id: int
    klant_id: int
    naam: str
    retour_km: float
```

**Step 2: Add CREATE TABLE to SCHEMA_SQL in database.py**

Insert after the `klanten` table (after line 25, before `werkdagen`):

```sql
CREATE TABLE IF NOT EXISTS klant_locaties (
    id INTEGER PRIMARY KEY,
    klant_id INTEGER NOT NULL REFERENCES klanten(id) ON DELETE CASCADE,
    naam TEXT NOT NULL,
    retour_km REAL DEFAULT 0 CHECK (retour_km >= 0),
    UNIQUE(klant_id, naam)
);
```

**Step 3: Add ALTER TABLE migration for werkdagen.locatie_id**

In `init_db()`, after the existing fiscal column migrations (after line 186), add:

```python
        # Migration: add locatie_id to werkdagen
        try:
            await conn.execute(
                "ALTER TABLE werkdagen ADD COLUMN locatie_id INTEGER REFERENCES klant_locaties(id) ON DELETE SET NULL"
            )
        except Exception:
            pass  # Column already exists
```

**Step 4: Update test_init_creates_tables**

In `tests/test_database.py:27-29`, update the expected tables set to include `klant_locaties`:

```python
    expected = {'klanten', 'klant_locaties', 'werkdagen', 'facturen', 'uitgaven',
                'banktransacties', 'fiscale_params', 'bedrijfsgegevens',
                'aangifte_documenten'}
```

**Step 5: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All 117 tests PASS (schema change is backward-compatible)

**Step 6: Commit**

```bash
git add database.py models.py tests/test_database.py
git commit -m "feat: add klant_locaties table schema and KlantLocatie model"
```

---

### Task 2: CRUD Functions for klant_locaties

**Files:**
- Modify: `database.py` (append 4 new functions after line 1233)
- Create: `tests/test_locaties.py`

**Step 1: Write the failing tests**

Create `tests/test_locaties.py`:

```python
"""Tests voor klant_locaties CRUD operaties."""

import pytest
from database import (
    init_db, add_klant, get_klant_locaties,
    add_klant_locatie, update_klant_locatie, delete_klant_locatie,
)


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path


@pytest.mark.asyncio
async def test_add_and_get_locaties(db):
    """Add locations to a klant, verify they're returned."""
    kid = await add_klant(db, naam="HAP MiddenLand", tarief_uur=124, retour_km=60)
    lid1 = await add_klant_locatie(db, klant_id=kid, naam="Assen", retour_km=60)
    lid2 = await add_klant_locatie(db, klant_id=kid, naam="Emmen", retour_km=102)
    lid3 = await add_klant_locatie(db, klant_id=kid, naam="Hoogeveen", retour_km=128)
    assert lid1 > 0
    assert lid2 > 0
    assert lid3 > 0

    locaties = await get_klant_locaties(db, klant_id=kid)
    assert len(locaties) == 3
    namen = {loc.naam for loc in locaties}
    assert namen == {"Assen", "Emmen", "Hoogeveen"}
    # Check km values
    assen = next(l for l in locaties if l.naam == "Assen")
    assert assen.retour_km == 60
    emmen = next(l for l in locaties if l.naam == "Emmen")
    assert emmen.retour_km == 102


@pytest.mark.asyncio
async def test_update_locatie(db):
    """Update a location's name and km."""
    kid = await add_klant(db, naam="DDG", tarief_uur=124, retour_km=12)
    lid = await add_klant_locatie(db, klant_id=kid, naam="Groningen", retour_km=12)

    await update_klant_locatie(db, locatie_id=lid, naam="Groningen Stad", retour_km=14)

    locaties = await get_klant_locaties(db, klant_id=kid)
    assert len(locaties) == 1
    assert locaties[0].naam == "Groningen Stad"
    assert locaties[0].retour_km == 14


@pytest.mark.asyncio
async def test_delete_locatie(db):
    """Delete a location, verify it's gone and others remain."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=50)
    lid1 = await add_klant_locatie(db, klant_id=kid, naam="Loc A", retour_km=50)
    lid2 = await add_klant_locatie(db, klant_id=kid, naam="Loc B", retour_km=100)

    await delete_klant_locatie(db, locatie_id=lid1)

    locaties = await get_klant_locaties(db, klant_id=kid)
    assert len(locaties) == 1
    assert locaties[0].naam == "Loc B"


@pytest.mark.asyncio
async def test_unique_constraint(db):
    """Adding duplicate (klant_id, naam) raises an error."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=50)
    await add_klant_locatie(db, klant_id=kid, naam="Loc A", retour_km=50)

    with pytest.raises(Exception):
        await add_klant_locatie(db, klant_id=kid, naam="Loc A", retour_km=60)


@pytest.mark.asyncio
async def test_get_locaties_empty(db):
    """Klant with no locations returns empty list."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=50)
    locaties = await get_klant_locaties(db, klant_id=kid)
    assert locaties == []


@pytest.mark.asyncio
async def test_cascade_delete_klant(db):
    """Deleting a klant cascades to its locations."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=50)
    await add_klant_locatie(db, klant_id=kid, naam="Loc A", retour_km=50)
    await add_klant_locatie(db, klant_id=kid, naam="Loc B", retour_km=100)

    from database import delete_klant
    await delete_klant(db, klant_id=kid)

    locaties = await get_klant_locaties(db, klant_id=kid)
    assert locaties == []
```

**Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_locaties.py -v`
Expected: FAIL with ImportError (functions don't exist yet)

**Step 3: Implement the CRUD functions**

Append to `database.py` after line 1233 (after `update_partner_inkomen`):

```python
# --- Klant Locaties ---

async def get_klant_locaties(db_path, klant_id):
    """Get all locations for a klant, ordered by name."""
    conn = await get_db(db_path)
    try:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT id, klant_id, naam, retour_km FROM klant_locaties "
            "WHERE klant_id = ? ORDER BY naam",
            (klant_id,))
        rows = await cur.fetchall()
        return [KlantLocatie(id=r['id'], klant_id=r['klant_id'],
                             naam=r['naam'], retour_km=r['retour_km'])
                for r in rows]
    finally:
        await conn.close()


async def add_klant_locatie(db_path, klant_id, naam, retour_km):
    """Add a location to a klant. Returns the new location id."""
    conn = await get_db(db_path)
    try:
        cur = await conn.execute(
            "INSERT INTO klant_locaties (klant_id, naam, retour_km) "
            "VALUES (?, ?, ?)",
            (klant_id, naam, retour_km))
        await conn.commit()
        return cur.lastrowid
    finally:
        await conn.close()


async def update_klant_locatie(db_path, locatie_id, naam, retour_km):
    """Update a location's name and/or km."""
    conn = await get_db(db_path)
    try:
        await conn.execute(
            "UPDATE klant_locaties SET naam = ?, retour_km = ? WHERE id = ?",
            (naam, retour_km, locatie_id))
        await conn.commit()
    finally:
        await conn.close()


async def delete_klant_locatie(db_path, locatie_id):
    """Delete a location by id."""
    conn = await get_db(db_path)
    try:
        await conn.execute(
            "DELETE FROM klant_locaties WHERE id = ?", (locatie_id,))
        await conn.commit()
    finally:
        await conn.close()
```

Also add the import at the top of `database.py` (around line 9, where models are imported):
```python
from models import KlantLocatie
```
(Add `KlantLocatie` to the existing import line from models.)

**Step 4: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_locaties.py -v`
Expected: All 6 tests PASS

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS (117 + 6 = 123)

**Step 5: Commit**

```bash
git add database.py tests/test_locaties.py
git commit -m "feat: add klant_locaties CRUD functions with tests"
```

---

### Task 3: Seed Data — Import Distance Table

**Files:**
- Modify: `import_/seed_data.py` (add KLANT_LOCATIES and seed function)

**Step 1: Add seed data and function**

At the end of `import_/seed_data.py` (after line 130), add:

```python
KLANT_LOCATIES = {
    'HAP NoordOost': [
        ('Groningen', 12), ('Zuidhorn', 52), ('Stadskanaal', 47),
        ('Delfzijl', 64), ('Scheemda', 60),
    ],
    'HAP MiddenLand': [
        ('Assen', 60), ('Hoogeveen', 128), ('Emmen', 102),
    ],
    'Praktijk K2': [('Vlagtwedde', 108)],
    "Praktijk K6": [('Marum', 54)],
    'K. Klant7': [('Marum', 54)],
    'Praktijk K14': [('Winsum', 44)],
    'Praktijk K10': [('Smilde', 78)],
    'Praktijk K11': [('Marum', 40)],
    'Praktijk K12': [('Marum', 54)],
    'Praktijk K13': [('De Wilp', 46)],
    'Praktijk K9': [('Sellingen', 92)],
    'Klant8': [('Marum', 54)],
}


async def seed_klant_locaties(db_path):
    """Seed locations for existing klanten. Skips if locations already exist."""
    from database import get_db, get_klanten, add_klant_locatie, get_klant_locaties
    klanten = await get_klanten(db_path, alleen_actief=False)
    klant_by_naam = {k.naam: k for k in klanten}
    count = 0
    for klant_naam, locaties in KLANT_LOCATIES.items():
        klant = klant_by_naam.get(klant_naam)
        if not klant:
            continue
        existing = await get_klant_locaties(db_path, klant.id)
        if existing:
            continue  # Already seeded
        for naam, km in locaties:
            await add_klant_locatie(db_path, klant.id, naam, km)
            count += 1
    return count
```

Update `seed_all` function (around line 128-130):

```python
async def seed_all(db_path):
    fp_count = await seed_fiscale_params(db_path)
    loc_count = await seed_klant_locaties(db_path)
    return fp_count, loc_count
```

**Step 2: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All 123 tests PASS

**Step 3: Commit**

```bash
git add import_/seed_data.py
git commit -m "feat: add klant_locaties seed data from Urenregister distance table"
```

---

### Task 4: Werkdag Form — Location Dropdown

**Files:**
- Modify: `components/werkdag_form.py` (add location dropdown after klant select)

**Step 1: Update imports**

At `components/werkdag_form.py:5`, update the import from database to include the new function:

```python
from database import get_klanten, get_klant_locaties, add_werkdag, update_werkdag, get_fiscale_params, DB_PATH
```

**Step 2: Add location dropdown to the form**

This is the core UX change. The form currently has (simplified):
- Row 1: datum + klant
- Row 2: code + uren
- Row 3: tarief + km + km_tarief

We need to add a location select between row 1 and row 2, visible only when a klant with locations is selected.

In the dialog UI section (around lines 40-113), after the klant_select (around line 63), add a location row:

```python
        # Location dropdown (hidden by default, shown when klant has locations)
        locatie_row = ui.row().classes('w-full gap-4')
        locatie_row.set_visibility(False)
        with locatie_row:
            locatie_select = ui.select(
                {}, label='Locatie', value=None,
                on_change=lambda e: on_locatie_change(e.value),
            ).classes('flex-grow')
```

**Step 3: Update the on_klant_change handler**

Replace the existing `on_klant_change` (lines 130-136) to also load locations:

```python
    async def on_klant_change(e):
        kid = e.value
        if kid and kid in klant_data:
            k = klant_data[kid]
            tarief_input.value = k.tarief_uur

            # Load locations for this klant
            locaties = await get_klant_locaties(DB_PATH, kid)
            if locaties:
                loc_options = {loc.id: f"{loc.naam} ({loc.retour_km} km)"
                               for loc in locaties}
                locatie_select.options = loc_options
                locatie_select.update()
                locatie_row.set_visibility(True)

                # Pre-select first (or single) location
                first_loc = locaties[0]
                locatie_select.value = first_loc.id
                km_input.value = first_loc.retour_km
            else:
                locatie_row.set_visibility(False)
                locatie_select.value = None
                km_input.value = k.retour_km
        else:
            locatie_row.set_visibility(False)
            locatie_select.value = None
        update_totaal()
```

Note: `on_klant_change` must be `async` now because `get_klant_locaties` is async. The NiceGUI event system handles async handlers fine.

**Step 4: Add the on_locatie_change handler**

Add a new handler after on_klant_change:

```python
    def on_locatie_change(loc_id):
        if loc_id and locatie_select.options:
            # Find the km for this location from the options text
            # Better: store locatie data in a dict
            for loc in locatie_data.get(klant_select.value, []):
                if loc.id == loc_id:
                    km_input.value = loc.retour_km
                    break
        update_totaal()
```

To make this work, we need a `locatie_data` dict. Add at the top of the dialog (near line 32):

```python
        locatie_data = {}  # klant_id -> list[KlantLocatie]
```

And in `on_klant_change`, store the loaded locaties:

```python
            locatie_data[kid] = locaties
```

**Step 5: Update save() to include locatie info**

In the `save()` function (around line 170 where `locatie=k.adres` is set), change to:

```python
            # Determine locatie text
            loc_id = locatie_select.value
            loc_naam = ''
            if loc_id and klant_select.value in locatie_data:
                for loc in locatie_data[klant_select.value]:
                    if loc.id == loc_id:
                        loc_naam = loc.naam
                        break
            locatie_text = loc_naam or k.adres

            kwargs = dict(
                datum=datum_input.value,
                klant_id=kid,
                code=code_input.value or '',
                activiteit=CODES.get(code_input.value, code_input.value or ''),
                locatie=locatie_text,
                uren=uren_input.value,
                km=km_input.value or 0,
                tarief=tarief_input.value,
                km_tarief=km_tarief_input.value,
                opmerking=opmerking_input.value or '',
                urennorm=1 if urennorm_check.value else 0,
            )
```

**Step 6: Update "Opslaan & Nieuw" reset**

In the reset after save-and-new (around line 199), preserve the klant AND location selection:

```python
                # Reset for next entry — preserve klant + locatie
                datum_input.value = datum_input.value  # keep same date
                uren_input.value = 8
                opmerking_input.value = ''
                # Do NOT reset klant_select, locatie_select, tarief, km
                update_totaal()
```

**Step 7: Handle edit mode**

When editing an existing werkdag, if it has a `locatie_id`, pre-select that location. If not, try to match by `locatie` text.

In the edit pre-fill section (around lines 115-127), after setting `klant_select.value`:

```python
        if werkdag:
            # ... existing pre-fills ...
            # Trigger klant change to load locations, then set locatie
            await on_klant_change(type('E', (), {'value': werkdag.klant_id})())
            # Try to match existing locatie by name
            if werkdag.locatie and klant_select.value in locatie_data:
                for loc in locatie_data[klant_select.value]:
                    if loc.naam == werkdag.locatie:
                        locatie_select.value = loc.id
                        break
```

**Step 8: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All 123 tests PASS

**Step 9: Manual smoke test**

1. Start app: `source .venv/bin/activate && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py`
2. Go to Werkdagen → Add werkdag
3. Select a klant that has locations → verify location dropdown appears
4. Select different locations → verify km auto-fills
5. Select a klant without locations → verify dropdown hides

**Step 10: Commit**

```bash
git add components/werkdag_form.py
git commit -m "feat: add location dropdown to werkdag form with auto-fill km"
```

---

### Task 5: Instellingen — Location Management in Klant Edit Dialog

**Files:**
- Modify: `pages/instellingen.py:160-189` (klant edit dialog)

**Step 1: Update imports**

At the top of `pages/instellingen.py`, add to the database imports:

```python
from database import (
    ...,  # existing imports
    get_klant_locaties, add_klant_locatie, update_klant_locatie, delete_klant_locatie,
)
```

**Step 2: Add locations sub-section to klant edit dialog**

In `on_edit()` (lines 160-189), after the existing edit fields (ed_naam, ed_tarief, ed_km, ed_adres) and before the save button, add:

```python
                ui.separator()
                ui.label('Locaties').classes('text-subtitle2 text-weight-medium')
                ui.label('Werklocaties met retourafstand (km). '
                         'Verschijnt als dropdown in het werkdagformulier.').classes(
                    'text-caption text-grey-7')

                loc_container = ui.column().classes('w-full gap-1')

                async def refresh_locaties():
                    loc_container.clear()
                    locaties = await get_klant_locaties(DB_PATH, row['id'])
                    with loc_container:
                        for loc in locaties:
                            with ui.row().classes('w-full items-center gap-2'):
                                ui.label(loc.naam).classes('flex-grow')
                                ui.label(f'{loc.retour_km} km').classes(
                                    'text-grey-7')
                                ui.button(icon='delete',
                                          on_click=lambda l=loc: del_loc(l.id),
                                          ).props(
                                    'flat dense round size=xs color=negative')

                        # Add new location row
                        with ui.row().classes('w-full items-center gap-2 q-mt-sm'):
                            new_loc_naam = ui.input('Locatie naam').classes(
                                'flex-grow')
                            new_loc_km = ui.number('Km retour', value=0,
                                                    format='%.0f').classes('w-24')
                            ui.button(icon='add',
                                      on_click=lambda: add_loc(
                                          new_loc_naam.value, new_loc_km.value),
                                      ).props('flat dense round color=primary')

                async def add_loc(naam, km):
                    if not naam or not naam.strip():
                        ui.notify('Vul een locatienaam in', type='warning')
                        return
                    await add_klant_locatie(DB_PATH, row['id'],
                                           naam.strip(), km or 0)
                    await refresh_locaties()

                async def del_loc(loc_id):
                    await delete_klant_locatie(DB_PATH, loc_id)
                    await refresh_locaties()

                await refresh_locaties()
```

**Step 3: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All 123 tests PASS

**Step 4: Manual smoke test**

1. Go to Instellingen → Klanten tab
2. Edit a klant → verify "Locaties" section appears below the existing fields
3. Add a location with naam + km → verify it appears in the list
4. Delete a location → verify it's removed
5. Go to Werkdagen → Add werkdag → select that klant → verify the location appears in dropdown

**Step 5: Commit**

```bash
git add pages/instellingen.py
git commit -m "feat: add location management to klant edit dialog on Instellingen"
```

---

### Task 6: Seed Locations on App Start

**Files:**
- Modify: `main.py` (call seed_klant_locaties on startup)

**Step 1: Add location seeding to startup**

In `main.py`, in the startup section where `seed_all` or `init_db` is called, add:

```python
from import_.seed_data import seed_klant_locaties
# After init_db:
await seed_klant_locaties(DB_PATH)
```

Or if startup is synchronous, check how the existing seed is called and follow the same pattern. The seed function is idempotent (skips klanten that already have locations).

**Step 2: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All 123 tests PASS

**Step 3: Manual smoke test**

1. Delete `data/roberg.sqlite3` (or use a fresh DB)
2. Start app
3. Go to Instellingen → edit "HAP MiddenLand" → verify Assen/Emmen/Hoogeveen locations exist
4. Go to Werkdagen → add werkdag → select HAP MiddenLand → verify location dropdown shows all 3

**Step 4: Commit**

```bash
git add main.py
git commit -m "feat: seed klant locations from distance table on startup"
```

---

### Task 7: Update Werkdag Model and DB to Support locatie_id

**Files:**
- Modify: `models.py` (add locatie_id to Werkdag)
- Modify: `database.py` (update add_werkdag and get_werkdagen queries)

**Step 1: Add locatie_id to Werkdag model**

In `models.py`, in the Werkdag dataclass (around line 46), add:

```python
    locatie_id: int | None = None
```

**Step 2: Update add_werkdag to accept locatie_id**

In `database.py`, in the `add_werkdag` function (line 344), add `locatie_id` to the INSERT:

The current INSERT (around line 351-357):
```sql
INSERT INTO werkdagen (datum, klant_id, code, activiteit, locatie, uren, km, tarief, km_tarief, opmerking, urennorm)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

Change to:
```sql
INSERT INTO werkdagen (datum, klant_id, code, activiteit, locatie, uren, km, tarief, km_tarief, opmerking, urennorm, locatie_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

And add `locatie_id` parameter (default None) to the function signature.

**Step 3: Update get_werkdagen to include locatie_id**

In the `get_werkdagen` SELECT query (around line 315), add `w.locatie_id` to the SELECT columns and map it in the Werkdag constructor.

**Step 4: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All 123 tests PASS (locatie_id defaults to None so existing tests still work)

**Step 5: Commit**

```bash
git add database.py models.py
git commit -m "feat: add locatie_id to werkdag model and DB queries"
```

---

### Task 8: Final — Update werkdag_form save to pass locatie_id

**Files:**
- Modify: `components/werkdag_form.py` (pass locatie_id in save kwargs)

**Step 1: Add locatie_id to save kwargs**

In the `save()` function, add `locatie_id` to the kwargs dict:

```python
            kwargs = dict(
                ...,  # existing fields
                locatie_id=locatie_select.value if locatie_select.value else None,
            )
```

**Step 2: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All 123 tests PASS

**Step 3: Full manual smoke test**

1. Start app
2. Go to Werkdagen → Add werkdag
3. Select "HAP MiddenLand" → verify location dropdown shows: Assen (60 km), Emmen (102 km), Hoogeveen (128 km)
4. Select "Emmen" → verify km field shows 102
5. Switch to "Assen" → verify km field changes to 60
6. Save → verify werkdag appears with correct km
7. Edit the werkdag → verify location is pre-selected correctly
8. Select a klant without locations (e.g., one you haven't set up) → verify no dropdown, km from klant.retour_km
9. Create a factuur from the werkdag → verify invoice shows correct location in travel line

**Step 4: Commit**

```bash
git add components/werkdag_form.py
git commit -m "feat: pass locatie_id when saving werkdag"
```

---

### Task 9: Update CLAUDE.md and MEMORY.md

**Files:**
- Modify: `CLAUDE.md` (update table count from 8 to 9)
- Modify: auto-memory MEMORY.md

**Step 1: Update CLAUDE.md**

Change "8 tabellen" to "9 tabellen" and add `klant_locaties` to the list.

**Step 2: Update MEMORY.md**

Add note about multi-location feature completion.

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with klant_locaties table"
```
