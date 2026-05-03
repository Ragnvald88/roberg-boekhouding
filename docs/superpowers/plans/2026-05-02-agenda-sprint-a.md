# Agenda Sprint A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Werkende `/agenda`-pagina met kalender, recurring patterns, blocker-dagen, day-inspector, bevestigen-flow én directe factuur-status visualisatie per werkdag-cel.

**Architecture:** Nieuwe `services/`-laag voor agenda + holidays. Twee nieuwe SQLite-tabellen (`klant_recurring_patterns`, `blockers`) via migratie 35+36. Bestaande `database.py`/`fiscal/`/`pages/` blijven onaangeraakt — alleen kleine uitbreidingen waar de spec dat vraagt (nieuwe query, prefill-API, sidebar-item). Type-based coloring (dagpraktijk/anw/overig) via pure functie. Factuur-status komt uit JOIN `werkdagen` × `facturen`, en "verlopen" is een pure function op `today` zodat geen achtergrondproces nodig is.

**Tech Stack:** NiceGUI 3.x + Quasar/Vue, aiosqlite, raw SQL, Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-05-02-agenda-sprint-a-design.md`

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `services/__init__.py` | Empty package init. |
| `services/holidays.py` | Pure functions: `easter_sunday()`, `koningsdag()`, `dutch_holidays()`. Returns `Holiday` frozen dataclass. No DB or UI imports. |
| `services/agenda.py` | Agenda business operations: read (`get_maand`, `get_dag`, `get_zes_weken_prognose`, `get_urencriterium_projectie`, `list_blockers`, `list_patterns_for_klant`), mutate (`confirm_expected`, `add_blocker`, `delete_blocker`, `add_pattern`, `update_pattern`, `delete_pattern`). Pure helpers: `categorize_werkdag`, `derive_werkdag_status_label`, `parse_weekdays`. |
| `pages/agenda.py` | NiceGUI page handler `@ui.page('/agenda')`. Composes `MonthGrid` + `DayInspector` + urencriterium-strip. |
| `tests/test_holidays.py` | Easter golden vectors, Koningsdag-zondag-shift, full holiday-list per jaar. |
| `tests/test_agenda_service.py` | All service-level tests (~24 cases). |
| `tests/test_agenda_pure_helpers.py` | `categorize_werkdag`, `derive_werkdag_status_label`, `parse_weekdays`. |
| `tests/test_database_agenda_tables.py` | Schema, constraints, migrations 35/36, `get_werkdagen_met_factuur_status`. |
| `tests/test_agenda_page.py` | Smoke tests (page renders, no errors). |

### Modified files

| Path | Change |
|---|---|
| `database.py` | Add migrations 35+36 to `MIGRATIONS` list. Add `ConflictError(ValueError)` and `ValidationError(ValueError)` next to `YearLockedError`. Add `get_werkdagen_met_factuur_status` query. Add CRUD helpers for patterns + blockers. |
| `components/layout.py` | Add `/agenda` nav-item between Dashboard and Werkdagen. Add CSS classes `wd-dagpraktijk`/`wd-anw`/`wd-overig` + status-bar styles. |
| `components/werkdag_form.py` | Add `prefill: dict | None = None` kwarg to `open_werkdag_dialog`. When `prefill['pattern_id']` set: dialog calls `services.agenda.confirm_expected` instead of `add_werkdag`. |
| `components/shared_ui.py` | Add "Vast rooster" section to `open_klant_dialog` (edit mode only): list patterns, add-form, delete buttons. |

---

## Sessie 1 — Datamodel + Holidays (2-3u)

### Task 1.1: Migratie 35 — `klant_recurring_patterns` tabel

**Files:**
- Modify: `database.py:400` (MIGRATIONS list)
- Test: `tests/test_database_agenda_tables.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_database_agenda_tables.py
import pytest
import aiosqlite
from pathlib import Path

import database


@pytest.fixture
async def fresh_db(tmp_path):
    """Fresh DB with all migrations applied."""
    db = tmp_path / 'test.sqlite3'
    await database.init_db(str(db))
    return db


@pytest.mark.asyncio
async def test_klant_recurring_patterns_table_exists(fresh_db):
    async with aiosqlite.connect(fresh_db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='klant_recurring_patterns'"
        )
        row = await cur.fetchone()
    assert row is not None, "klant_recurring_patterns table missing"


@pytest.mark.asyncio
async def test_klant_recurring_patterns_has_required_columns(fresh_db):
    async with aiosqlite.connect(fresh_db) as conn:
        cur = await conn.execute(
            "PRAGMA table_info(klant_recurring_patterns)"
        )
        cols = {row[1] for row in await cur.fetchall()}
    expected = {'id', 'klant_id', 'weekdays', 'start_minuten',
                'eind_minuten', 'code', 'activiteit',
                'valid_from', 'valid_until', 'actief'}
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


@pytest.mark.asyncio
async def test_klant_recurring_patterns_cascade_on_klant_delete(fresh_db):
    async with aiosqlite.connect(fresh_db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        cur = await conn.execute(
            "INSERT INTO klanten (naam, tarief_uur) VALUES ('Test', 80) RETURNING id"
        )
        klant_id = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO klant_recurring_patterns "
            "(klant_id, weekdays, start_minuten, eind_minuten) "
            "VALUES (?, '1,3', 480, 1020)",
            (klant_id,),
        )
        await conn.execute("DELETE FROM klanten WHERE id = ?", (klant_id,))
        await conn.commit()
        cur = await conn.execute(
            "SELECT COUNT(*) FROM klant_recurring_patterns"
        )
        count = (await cur.fetchone())[0]
    assert count == 0, "Cascade delete failed"


@pytest.mark.asyncio
async def test_klant_recurring_patterns_check_minuten_range(fresh_db):
    async with aiosqlite.connect(fresh_db) as conn:
        await conn.execute(
            "INSERT INTO klanten (naam, tarief_uur) VALUES ('K', 80)"
        )
        # eind <= start should fail
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_recurring_patterns "
                "(klant_id, weekdays, start_minuten, eind_minuten) "
                "VALUES (1, '1', 600, 600)"
            )
            await conn.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database_agenda_tables.py -v
```

Expected: FAIL with "no such table: klant_recurring_patterns"

- [ ] **Step 3: Add migration 35 in `database.py`**

Find the `MIGRATIONS` list (starts around line 400). Append after the last existing entry (currently `(34, "seed_klant_aliases_from_local", None)`):

```python
    (35, "add_klant_recurring_patterns", [
        """CREATE TABLE IF NOT EXISTS klant_recurring_patterns (
            id INTEGER PRIMARY KEY,
            klant_id INTEGER NOT NULL REFERENCES klanten(id) ON DELETE CASCADE,
            weekdays TEXT NOT NULL,
            start_minuten INTEGER NOT NULL CHECK (start_minuten >= 0 AND start_minuten < 1440),
            eind_minuten INTEGER NOT NULL CHECK (eind_minuten > start_minuten AND eind_minuten <= 1440),
            code TEXT NOT NULL DEFAULT 'WERKDAG',
            activiteit TEXT DEFAULT 'Waarneming dagpraktijk',
            valid_from TEXT DEFAULT '',
            valid_until TEXT DEFAULT '',
            actief INTEGER NOT NULL DEFAULT 1 CHECK (actief IN (0, 1)))""",
        "CREATE INDEX IF NOT EXISTS idx_klant_patterns_klant ON klant_recurring_patterns(klant_id, actief)",
    ]),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database_agenda_tables.py -v
```

Expected: 4 cases PASS

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database_agenda_tables.py
git commit -m "feat(agenda): migratie 35 — klant_recurring_patterns tabel

CASCADE op klant-delete + CHECK constraints op minuten-range.
Code-veld default 'WERKDAG' voor type-based coloring (dagpraktijk/anw/overig).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 1.2: Migratie 36 — `blockers` tabel

**Files:**
- Modify: `database.py` (MIGRATIONS list)
- Test: `tests/test_database_agenda_tables.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_database_agenda_tables.py`:

```python
@pytest.mark.asyncio
async def test_blockers_table_exists(fresh_db):
    async with aiosqlite.connect(fresh_db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='blockers'"
        )
        row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_blockers_unique_datum_constraint(fresh_db):
    async with aiosqlite.connect(fresh_db) as conn:
        await conn.execute(
            "INSERT INTO blockers (datum, kind, label) "
            "VALUES ('2026-05-21', 'training', 'NHG')"
        )
        await conn.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO blockers (datum, kind, label) "
                "VALUES ('2026-05-21', 'vacation', 'Holiday')"
            )
            await conn.commit()


@pytest.mark.asyncio
async def test_blockers_kind_check_constraint(fresh_db):
    async with aiosqlite.connect(fresh_db) as conn:
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO blockers (datum, kind) "
                "VALUES ('2026-05-21', 'holiday')"  # 'holiday' niet toegestaan
            )
            await conn.commit()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database_agenda_tables.py -v -k blocker
```

Expected: FAIL "no such table: blockers"

- [ ] **Step 3: Add migration 36**

Append in `database.py` `MIGRATIONS` list after migration 35:

```python
    (36, "add_blockers", [
        """CREATE TABLE IF NOT EXISTS blockers (
            id INTEGER PRIMARY KEY,
            datum TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL CHECK (kind IN ('vacation', 'sick', 'training')),
            label TEXT NOT NULL DEFAULT '')""",
        "CREATE INDEX IF NOT EXISTS idx_blockers_datum ON blockers(datum)",
    ]),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database_agenda_tables.py -v
```

Expected: 7 cases PASS

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database_agenda_tables.py
git commit -m "feat(agenda): migratie 36 — blockers tabel

UNIQUE(datum) — één blocker per dag. CHECK kind in (vacation/sick/training).
Holiday is computed via dutch_holidays(), niet stored.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 1.3: Back-up + rollback proef (manueel scenario)

**Files:**
- Create: `docs/superpowers/runbooks/agenda-migration-backup-test.md`

- [ ] **Step 1: Write runbook document**

```markdown
# Backup + Rollback Proef — Migratie 35+36

## Voorbereiding

```bash
DB="${HOME}/Library/Application Support/Boekhouding/data/db.sqlite3"
BACKUP="${HOME}/Library/Application Support/Boekhouding/data/pre-35-backup.sqlite3"
```

## Stap 1: Backup huidige DB

```bash
sqlite3 "$DB" "VACUUM INTO '$BACKUP'"
ls -lh "$BACKUP"  # verifieer bestand bestaat
```

## Stap 2: Apply migraties (start app)

```bash
cd ~/Library/CloudStorage/SynologyDrive-Main/06_Development/1_roberg-boekhouding
source .venv/bin/activate
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py
# Open /agenda — sluit de app
```

## Stap 3: Verifieer schema-versie + nieuwe tabellen

```bash
sqlite3 "$DB" "SELECT version FROM schema_version"
# Expected: 36

sqlite3 "$DB" "SELECT COUNT(*) FROM klant_recurring_patterns"
# Expected: 0

sqlite3 "$DB" "SELECT COUNT(*) FROM blockers"
# Expected: 0

sqlite3 "$DB" "SELECT COUNT(*) FROM werkdagen"
# Expected: same as before backup (record this manually)
```

## Stap 4: Rollback test

```bash
cp "$BACKUP" "$DB"
sqlite3 "$DB" "SELECT version FROM schema_version"
# Expected: 34 (or whatever pre-35 was)
```

## Stap 5: Re-apply (idempotency)

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python -c "import asyncio, database; asyncio.run(database.init_db('$DB'))"
sqlite3 "$DB" "SELECT version FROM schema_version"
# Expected: 36

# Run twice:
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python -c "import asyncio, database; asyncio.run(database.init_db('$DB'))"
sqlite3 "$DB" "SELECT version FROM schema_version"
# Expected: still 36 (idempotent)
```

## Result-log

| Stap | Verwacht | Gemeten | OK |
|---|---|---|---|
| Backup created | $BACKUP exists | _ | _ |
| Schema version after migrate | 36 | _ | _ |
| werkdagen unchanged | <pre-count> | _ | _ |
| Rollback to 34 | 34 | _ | _ |
| Re-apply idempotent | 36 → 36 | _ | _ |

Cleanup: `rm "$BACKUP"` na succesvolle test.
```

- [ ] **Step 2: Execute the runbook**

Run de stappen volgens de runbook. Vul de result-log in.

- [ ] **Step 3: Commit runbook + completed log**

```bash
git add docs/superpowers/runbooks/agenda-migration-backup-test.md
git commit -m "docs(agenda): backup+rollback runbook voor migraties 35+36"
```

---

### Task 1.4: Easter algoritme (`services/holidays.py`)

**Files:**
- Create: `services/__init__.py`
- Create: `services/holidays.py`
- Test: `tests/test_holidays.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_holidays.py
from datetime import date

import pytest

from services.holidays import easter_sunday, koningsdag, dutch_holidays, Holiday


def test_easter_2020():
    assert easter_sunday(2020) == date(2020, 4, 12)


def test_easter_2025():
    assert easter_sunday(2025) == date(2025, 4, 20)


def test_easter_2026():
    assert easter_sunday(2026) == date(2026, 4, 5)


def test_easter_2030():
    assert easter_sunday(2030) == date(2030, 4, 21)


def test_koningsdag_2025_falls_on_saturday_april_26():
    """27 april 2025 = zondag, dus Koningsdag = zaterdag 26 april."""
    assert koningsdag(2025) == date(2025, 4, 26)


def test_koningsdag_2026_falls_on_monday_april_27():
    """27 april 2026 = maandag, geen shift."""
    assert koningsdag(2026) == date(2026, 4, 27)


def test_koningsdag_2031_falls_on_saturday():
    """27 april 2031 = zondag → 26 april."""
    assert koningsdag(2031) == date(2031, 4, 26)


def test_dutch_holidays_2026_count():
    """11 standaard NL feestdagen per jaar."""
    holidays = dutch_holidays(2026)
    assert len(holidays) == 11


def test_dutch_holidays_2026_includes_known_dates():
    holidays = {h.datum: h.label for h in dutch_holidays(2026)}
    assert holidays[date(2026, 1, 1)] == 'Nieuwjaarsdag'
    assert holidays[date(2026, 4, 27)] == 'Koningsdag'
    assert holidays[date(2026, 5, 5)] == 'Bevrijdingsdag'
    assert holidays[date(2026, 12, 25)] == 'Eerste Kerstdag'
    assert holidays[date(2026, 12, 26)] == 'Tweede Kerstdag'
    # Easter 2026 = 5 april
    assert holidays[date(2026, 4, 3)] == 'Goede Vrijdag'
    assert holidays[date(2026, 4, 5)] == 'Eerste Paasdag'
    assert holidays[date(2026, 4, 6)] == 'Tweede Paasdag'
    assert holidays[date(2026, 5, 14)] == 'Hemelvaart'
    assert holidays[date(2026, 5, 24)] == 'Eerste Pinksterdag'
    assert holidays[date(2026, 5, 25)] == 'Tweede Pinksterdag'


def test_holiday_is_frozen_dataclass():
    """Holiday must be hashable + immutable for set/dict use."""
    h = Holiday(datum=date(2026, 1, 1), label='Nieuwjaarsdag')
    with pytest.raises((AttributeError, Exception)):
        h.datum = date(2026, 1, 2)  # frozen, should fail


def test_holidays_no_external_imports():
    """Pure module — only stdlib (datetime, dataclasses)."""
    import services.holidays as mod
    import ast
    src = open(mod.__file__).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module in ('datetime', 'dataclasses', 'functools'), \
                f"Unexpected import: {node.module}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name in ('datetime', 'dataclasses', 'functools'), \
                    f"Unexpected import: {alias.name}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_holidays.py -v
```

Expected: FAIL "ModuleNotFoundError: No module named 'services.holidays'"

- [ ] **Step 3: Implement `services/holidays.py`**

```python
# services/__init__.py
"""Service-layer business operations. UI-free, DB-aware."""
```

```python
# services/holidays.py
"""Dutch holidays — pure functions, stdlib-only.

Used by services/agenda.py to compute holiday markers in calendar view.
Returns frozen Holiday dataclass for hashability and Swift-portability.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache


@dataclass(frozen=True)
class Holiday:
    datum: date
    label: str


@lru_cache(maxsize=64)
def easter_sunday(year: int) -> date:
    """Anonymous Gregorian computation (Meeus/Jones/Butcher).

    Verified against known dates: 2020-04-12, 2025-04-20, 2026-04-05, 2030-04-21.
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    L = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * L) // 451
    month = (h + L - 7 * m + 114) // 31
    day = ((h + L - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def koningsdag(year: int) -> date:
    """27 april, of 26 april als 27 een zondag is.

    Wettelijke regel sinds Koningsbesluit 2014. Pre-2014 gold zelfde shift
    voor Koninginnedag op zondag-30-april.
    """
    candidate = date(year, 4, 27)
    if candidate.weekday() == 6:  # zondag
        return candidate - timedelta(days=1)
    return candidate


@lru_cache(maxsize=32)
def dutch_holidays(year: int) -> list[Holiday]:
    """Standaardlijst Nederlandse feestdagen voor het gegeven jaar.

    Returns 11 holidays:
    - Nieuwjaarsdag, Goede Vrijdag, Eerste/Tweede Paasdag, Koningsdag,
      Bevrijdingsdag, Hemelvaart, Eerste/Tweede Pinksterdag,
      Eerste/Tweede Kerstdag.

    Geen onderscheid tussen wel/niet wettelijke vrije dag — gebruiker
    beslist zelf via UI of hij op een feestdag werkt (handmatig
    werkdag toevoegen overschrijft de holiday-marker visueel).
    """
    easter = easter_sunday(year)
    return [
        Holiday(date(year, 1, 1), 'Nieuwjaarsdag'),
        Holiday(easter - timedelta(days=2), 'Goede Vrijdag'),
        Holiday(easter, 'Eerste Paasdag'),
        Holiday(easter + timedelta(days=1), 'Tweede Paasdag'),
        Holiday(koningsdag(year), 'Koningsdag'),
        Holiday(date(year, 5, 5), 'Bevrijdingsdag'),
        Holiday(easter + timedelta(days=39), 'Hemelvaart'),
        Holiday(easter + timedelta(days=49), 'Eerste Pinksterdag'),
        Holiday(easter + timedelta(days=50), 'Tweede Pinksterdag'),
        Holiday(date(year, 12, 25), 'Eerste Kerstdag'),
        Holiday(date(year, 12, 26), 'Tweede Kerstdag'),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_holidays.py -v
```

Expected: 11 cases PASS

- [ ] **Step 5: Commit**

```bash
git add services/__init__.py services/holidays.py tests/test_holidays.py
git commit -m "feat(agenda): NL holiday algoritme (services/holidays.py)

Easter (Meeus/Jones/Butcher), Koningsdag-zondag-shift, 11 standaard NL
feestdagen. Pure stdlib-only, frozen Holiday dataclass.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 1.5: `get_werkdagen_met_factuur_status` query

**Files:**
- Modify: `database.py` (add new query function + dataclass)
- Test: `tests/test_database_agenda_tables.py` (extend)

- [ ] **Step 1: Write failing test**

Append to `tests/test_database_agenda_tables.py`:

```python
from datetime import date


@pytest.fixture
async def db_with_werkdagen(fresh_db):
    """DB with klant + werkdagen + facturen for status testing."""
    async with aiosqlite.connect(fresh_db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        # Klant
        await conn.execute(
            "INSERT INTO klanten (id, naam, tarief_uur) VALUES (1, 'HAP', 80)"
        )
        # Concept factuur
        await conn.execute(
            "INSERT INTO facturen (nummer, klant_id, datum, totaal_bedrag, "
            "betaald, status) VALUES ('2026-001', 1, '2026-05-01', 800, 0, 'concept')"
        )
        # Verstuurde factuur (verlopen — vervaldatum in verleden)
        await conn.execute(
            "INSERT INTO facturen (nummer, klant_id, datum, totaal_bedrag, "
            "betaald, status, vervaldatum) "
            "VALUES ('2026-002', 1, '2026-04-01', 800, 0, 'verstuurd', '2026-04-15')"
        )
        # Werkdagen
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, "
            "factuurnummer) VALUES (1, '2026-05-04', 1, 'WERKDAG', 10, 80, '2026-001')"
        )
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, "
            "factuurnummer) VALUES (2, '2026-04-04', 1, 'WERKDAG', 10, 80, '2026-002')"
        )
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, "
            "factuurnummer) VALUES (3, '2026-05-11', 1, 'WERKDAG', 10, 80, '')"
        )
        await conn.commit()
    return fresh_db


@pytest.mark.asyncio
async def test_get_werkdagen_met_factuur_status_returns_correct_status(db_with_werkdagen):
    rows = await database.get_werkdagen_met_factuur_status(
        str(db_with_werkdagen), 2026, 5
    )
    by_id = {r.id: r for r in rows}
    # mei: werkdag 1 (concept factuur) + werkdag 3 (ongefactureerd)
    assert by_id[1].factuur_status == 'concept'
    assert by_id[1].factuurnummer == '2026-001'
    assert by_id[3].factuur_status == ''
    assert by_id[3].factuurnummer == ''


@pytest.mark.asyncio
async def test_get_werkdagen_met_factuur_status_filters_by_month(db_with_werkdagen):
    rows = await database.get_werkdagen_met_factuur_status(
        str(db_with_werkdagen), 2026, 4
    )
    # Alleen werkdag 2 valt in april
    ids = {r.id for r in rows}
    assert ids == {2}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database_agenda_tables.py::test_get_werkdagen_met_factuur_status_returns_correct_status -v
```

Expected: FAIL "AttributeError: module 'database' has no attribute 'get_werkdagen_met_factuur_status'"

- [ ] **Step 3: Add dataclass + query in `database.py`**

Add near top of `database.py` (after existing dataclass definitions):

```python
@dataclass(frozen=True)
class WerkdagMetStatus:
    id: int
    datum: str
    klant_id: int
    klant_naam: str
    code: str
    activiteit: str
    uren: float
    km: float
    tarief: float
    km_tarief: float
    factuurnummer: str
    factuur_status: str        # '' | 'concept' | 'verstuurd' | 'betaald'
    factuur_vervaldatum: str   # '' if no factuur
```

Add query function (anywhere in `database.py`, e.g. near `get_werkdagen`):

```python
async def get_werkdagen_met_factuur_status(
    db_path, jaar: int, maand: int
) -> list['WerkdagMetStatus']:
    """Werkdagen voor (jaar, maand) met factuur-status JOIN.

    LEFT JOIN op facturen via werkdagen.factuurnummer = facturen.nummer.
    factuur_status='' bij ongefactureerde werkdagen.
    """
    maand_str = f"{jaar:04d}-{maand:02d}"
    query = """
        SELECT
            w.id, w.datum, w.klant_id, k.naam,
            w.code, w.activiteit, w.uren, w.km, w.tarief, w.km_tarief,
            COALESCE(w.factuurnummer, '') AS factuurnummer,
            COALESCE(f.status, '') AS factuur_status,
            COALESCE(f.vervaldatum, '') AS factuur_vervaldatum
        FROM werkdagen w
        JOIN klanten k ON k.id = w.klant_id
        LEFT JOIN facturen f ON f.nummer = w.factuurnummer
                            AND w.factuurnummer != ''
        WHERE substr(w.datum, 1, 7) = ?
        ORDER BY w.datum, w.id
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(query, (maand_str,))
        rows = await cur.fetchall()
    return [
        WerkdagMetStatus(
            id=r[0], datum=r[1], klant_id=r[2], klant_naam=r[3],
            code=r[4] or '', activiteit=r[5] or '',
            uren=r[6] or 0.0, km=r[7] or 0.0,
            tarief=r[8] or 0.0, km_tarief=r[9] or 0.0,
            factuurnummer=r[10], factuur_status=r[11],
            factuur_vervaldatum=r[12],
        )
        for r in rows
    ]
```

**Note**: `facturen.vervaldatum` may not exist in current schema. Check first:

```bash
sqlite3 ~/Library/Application\ Support/Boekhouding/data/db.sqlite3 "PRAGMA table_info(facturen)" | grep -i verval
```

If absent, fall back to using `datum + 14 days` heuristic in `derive_werkdag_status_label` (Sessie 2). Note this in test fixture and skip the vervaldatum-driven `'verlopen'` test in this task.

- [ ] **Step 4: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database_agenda_tables.py -v
```

Expected: 9 cases PASS

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database_agenda_tables.py
git commit -m "feat(agenda): get_werkdagen_met_factuur_status query

LEFT JOIN werkdagen × facturen voor status visualisatie per cel.
WerkdagMetStatus frozen dataclass; factuur_status='' bij ongefactureerd.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Sessie 2 — Service-laag + Errors (3-4u)

### Task 2.1: `ConflictError` + `ValidationError` in `database.py`

**Files:**
- Modify: `database.py` (around line 1003 next to `YearLockedError`)
- Test: existing tests must remain green

- [ ] **Step 1: Add error classes**

In `database.py`, around line 1003 after `class YearLockedError(ValueError):`:

```python
class ConflictError(ValueError):
    """Raised when an operation conflicts with current state.

    e.g. confirm_expected on deleted pattern, blocker on existing werkdag,
    UNIQUE-constraint violation surfaced as user-friendly conflict.

    Subclasses ValueError for backward-compat with existing
    `except ValueError` catch-sites.
    """


class ValidationError(ValueError):
    """Raised when user-provided input fails validation rules.

    e.g. invalid weekdays in pattern, eind_minuten <= start_minuten,
    invalid code value.

    Subclasses ValueError for backward-compat.
    """
```

- [ ] **Step 2: Run all tests to verify backcompat**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: 1054+ tests still PASS — no behavioral change.

- [ ] **Step 3: Commit**

```bash
git add database.py
git commit -m "feat(agenda): ConflictError + ValidationError naast YearLockedError

Beide ValueError-subclasses, zelfde patroon als YearLockedError.
Geen wijziging aan bestaande catch-sites; nieuwe code in services/agenda
gebruikt deze types.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.2: Pure helpers — `categorize_werkdag` + `derive_werkdag_status_label` + `parse_weekdays`

**Files:**
- Create: `services/agenda.py` (skeleton + 3 pure functions)
- Test: `tests/test_agenda_pure_helpers.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agenda_pure_helpers.py
from datetime import date

import pytest

from services.agenda import (
    categorize_werkdag, derive_werkdag_status_label, parse_weekdays,
)
from database import ValidationError


# ---- categorize_werkdag ----

@pytest.mark.parametrize('code,expected', [
    ('WERKDAG', 'dagpraktijk'),
    ('WEEKEND_DAG', 'dagpraktijk'),
    ('', 'dagpraktijk'),  # default treated as dagpraktijk
])
def test_categorize_werkdag_dagpraktijk_codes(code, expected):
    assert categorize_werkdag(code) == expected


@pytest.mark.parametrize('code', ['ANW_AVOND', 'ANW_NACHT', 'ANW_WEEKEND', 'AVOND', 'NACHT'])
def test_categorize_werkdag_anw_codes(code):
    assert categorize_werkdag(code) == 'anw'


@pytest.mark.parametrize('code', ['ACHTERWACHT', 'CONGRES', 'OPLEIDING', 'OVERIG_ZAK', 'UNKNOWN'])
def test_categorize_werkdag_overig_codes(code):
    assert categorize_werkdag(code) == 'overig'


# ---- derive_werkdag_status_label ----

class FakeWerkdag:
    def __init__(self, factuurnummer='', factuur_status='', factuur_vervaldatum=''):
        self.factuurnummer = factuurnummer
        self.factuur_status = factuur_status
        self.factuur_vervaldatum = factuur_vervaldatum


def test_status_ongefactureerd_when_no_factuurnummer():
    w = FakeWerkdag()
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'ongefactureerd'


def test_status_concept():
    w = FakeWerkdag(factuurnummer='2026-001', factuur_status='concept')
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'concept'


def test_status_verstuurd_with_future_vervaldatum():
    w = FakeWerkdag(
        factuurnummer='2026-001',
        factuur_status='verstuurd',
        factuur_vervaldatum='2026-06-01',
    )
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'verstuurd'


def test_status_verlopen_when_vervaldatum_past():
    w = FakeWerkdag(
        factuurnummer='2026-001',
        factuur_status='verstuurd',
        factuur_vervaldatum='2026-04-15',
    )
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'verlopen'


def test_status_betaald():
    w = FakeWerkdag(factuurnummer='2026-001', factuur_status='betaald')
    assert derive_werkdag_status_label(w, date(2026, 5, 13)) == 'betaald'


# ---- parse_weekdays ----

def test_parse_weekdays_valid_csv():
    assert parse_weekdays('1,3,5') == [1, 3, 5]


def test_parse_weekdays_single_value():
    assert parse_weekdays('1') == [1]


def test_parse_weekdays_empty_raises():
    with pytest.raises(ValidationError):
        parse_weekdays('')


def test_parse_weekdays_invalid_value_raises():
    with pytest.raises(ValidationError):
        parse_weekdays('1,8,3')  # 8 is invalid


def test_parse_weekdays_duplicates_raise():
    with pytest.raises(ValidationError):
        parse_weekdays('1,3,1')


def test_parse_weekdays_non_numeric_raises():
    with pytest.raises(ValidationError):
        parse_weekdays('a,b')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_pure_helpers.py -v
```

Expected: FAIL "ModuleNotFoundError: No module named 'services.agenda'"

- [ ] **Step 3: Implement skeleton + 3 pure functions**

```python
# services/agenda.py
"""Agenda service-layer.

Read + mutation API for the /agenda page. Pure helpers (categorize_werkdag,
derive_werkdag_status_label, parse_weekdays) sit at the top so they can be
imported standalone for testing without DB setup.

UI-free: no nicegui imports. DB-aware: imports from database.py.
Frozen dataclasses for view-objects to keep Swift-port mental model intact.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date, timedelta
from typing import Literal

from database import ValidationError


# ---------------------------------------------------------------------------
# Pure helpers (no DB, no UI)
# ---------------------------------------------------------------------------

WerkdagCategory = Literal['dagpraktijk', 'anw', 'overig']

_DAGPRAKTIJK_CODES = frozenset({'WERKDAG', 'WEEKEND_DAG', ''})
_ANW_CODES_PREFIX = 'ANW_'
_ANW_LEGACY_CODES = frozenset({'AVOND', 'NACHT'})


def categorize_werkdag(code: str) -> WerkdagCategory:
    """Categorize a werkdag by code for type-based coloring.

    Returns:
        'dagpraktijk' for WERKDAG/WEEKEND_DAG/empty
        'anw' for ANW_* codes and legacy AVOND/NACHT
        'overig' for all other codes (ACHTERWACHT/CONGRES/OPLEIDING/OVERIG_ZAK/unknown)
    """
    if code in _DAGPRAKTIJK_CODES:
        return 'dagpraktijk'
    if code.startswith(_ANW_CODES_PREFIX) or code in _ANW_LEGACY_CODES:
        return 'anw'
    return 'overig'


WerkdagStatusLabel = Literal[
    'ongefactureerd', 'concept', 'verstuurd', 'verlopen', 'betaald'
]


def derive_werkdag_status_label(werkdag, today: _date) -> WerkdagStatusLabel:
    """Derive UI status label from werkdag + factuur state.

    werkdag must have attributes: factuurnummer, factuur_status, factuur_vervaldatum.

    'verlopen' is a pure-function derivation: factuur is 'verstuurd' AND
    vervaldatum < today. No DB-update needed for this transition.
    """
    if not werkdag.factuurnummer:
        return 'ongefactureerd'
    status = werkdag.factuur_status
    if status == 'concept':
        return 'concept'
    if status == 'betaald':
        return 'betaald'
    if status == 'verstuurd':
        verval = werkdag.factuur_vervaldatum
        if verval and _date.fromisoformat(verval) < today:
            return 'verlopen'
        return 'verstuurd'
    # Unknown status — treat as ongefactureerd (defensive)
    return 'ongefactureerd'


def parse_weekdays(csv: str) -> list[int]:
    """Parse weekdays CSV ("1,3,5") to sorted unique list of ints 1-7.

    Raises ValidationError on empty, non-numeric, out-of-range, or duplicates.
    """
    if not csv:
        raise ValidationError("weekdays mag niet leeg zijn")
    try:
        parts = [int(p.strip()) for p in csv.split(',')]
    except ValueError:
        raise ValidationError(f"weekdays bevat niet-numerieke waarde: '{csv}'")
    if any(p < 1 or p > 7 for p in parts):
        raise ValidationError(f"weekdays moeten tussen 1-7 liggen, kreeg: {parts}")
    if len(set(parts)) != len(parts):
        raise ValidationError(f"weekdays bevat duplicaten: {parts}")
    return sorted(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_pure_helpers.py -v
```

Expected: 14 cases PASS

- [ ] **Step 5: Commit**

```bash
git add services/agenda.py tests/test_agenda_pure_helpers.py
git commit -m "feat(agenda): pure helpers — categorize/derive_status/parse_weekdays

Type-based coloring (dagpraktijk/anw/overig). Status-label derivation
incl. pure 'verlopen' detectie via today-vergelijking met vervaldatum.
Weekday-CSV validatie met ValidationError.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.3: Pattern CRUD in `database.py` + service-API

**Files:**
- Modify: `database.py` (add CRUD helpers)
- Modify: `services/agenda.py` (add `Pattern` dataclass + service functions)
- Test: `tests/test_agenda_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agenda_service.py
from datetime import date

import pytest
import aiosqlite

import database
import services.agenda as svc
from database import ConflictError, ValidationError, YearLockedError


@pytest.fixture
async def db_with_klant(tmp_path):
    """Fresh DB met één klant."""
    db = tmp_path / 'test.sqlite3'
    await database.init_db(str(db))
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO klanten (id, naam, tarief_uur) VALUES (1, 'HAP', 80)"
        )
        await conn.commit()
    return str(db)


# ---- Pattern CRUD ----

@pytest.mark.asyncio
async def test_pattern_add_basic(db_with_klant):
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1, 3],
        start_minuten=480, eind_minuten=1020, code='WERKDAG',
    )
    assert pid > 0


@pytest.mark.asyncio
async def test_pattern_list_for_klant(db_with_klant):
    await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1, 3],
        start_minuten=480, eind_minuten=1020,
    )
    patterns = await svc.list_patterns_for_klant(db_with_klant, klant_id=1)
    assert len(patterns) == 1
    assert patterns[0].weekdays == [1, 3]
    assert patterns[0].code == 'WERKDAG'


@pytest.mark.asyncio
async def test_pattern_invalid_weekdays_raises(db_with_klant):
    with pytest.raises(ValidationError):
        await svc.add_pattern(
            db_with_klant, klant_id=1, weekdays=[1, 8, 3],
            start_minuten=480, eind_minuten=1020,
        )


@pytest.mark.asyncio
async def test_pattern_eind_before_start_raises(db_with_klant):
    with pytest.raises(ValidationError):
        await svc.add_pattern(
            db_with_klant, klant_id=1, weekdays=[1],
            start_minuten=1020, eind_minuten=480,
        )


@pytest.mark.asyncio
async def test_pattern_invalid_code_raises(db_with_klant):
    with pytest.raises(ValidationError):
        await svc.add_pattern(
            db_with_klant, klant_id=1, weekdays=[1],
            start_minuten=480, eind_minuten=1020, code='INVALID',
        )


@pytest.mark.asyncio
async def test_pattern_update(db_with_klant):
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    await svc.update_pattern(db_with_klant, pid, weekdays=[1, 5], eind_minuten=990)
    patterns = await svc.list_patterns_for_klant(db_with_klant, klant_id=1)
    assert patterns[0].weekdays == [1, 5]
    assert patterns[0].eind_minuten == 990


@pytest.mark.asyncio
async def test_pattern_delete_soft(db_with_klant):
    """Delete = SET actief=0, behoud history."""
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    await svc.delete_pattern(db_with_klant, pid)
    active = await svc.list_patterns_for_klant(db_with_klant, klant_id=1)
    assert active == []
    all_patterns = await svc.list_patterns_for_klant(
        db_with_klant, klant_id=1, include_inactive=True,
    )
    assert len(all_patterns) == 1
    assert all_patterns[0].actief is False


@pytest.mark.asyncio
async def test_pattern_not_year_locked(db_with_klant, monkeypatch):
    """Pattern modificaties zijn projectie-data — niet year-locked."""
    # Lock 2026
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (2026, 'definitief')"
        )
        await conn.commit()
    # Add pattern moet werken ook in locked jaar
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    assert pid > 0
    # Update + delete ook
    await svc.update_pattern(db_with_klant, pid, weekdays=[2])
    await svc.delete_pattern(db_with_klant, pid)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_service.py -v
```

Expected: FAIL "AttributeError: module 'services.agenda' has no attribute 'add_pattern'"

- [ ] **Step 3: Add Pattern dataclass + DB-helpers + service functions**

In `database.py` (add near other CRUD helpers):

```python
@dataclass(frozen=True)
class RecurringPattern:
    id: int
    klant_id: int
    weekdays: str          # CSV "1,3,5"
    start_minuten: int
    eind_minuten: int
    code: str
    activiteit: str
    valid_from: str
    valid_until: str
    actief: bool


async def db_add_pattern(db_path, klant_id: int, weekdays: str,
                          start_minuten: int, eind_minuten: int,
                          code: str = 'WERKDAG',
                          activiteit: str = 'Waarneming dagpraktijk',
                          valid_from: str = '', valid_until: str = '') -> int:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """INSERT INTO klant_recurring_patterns
               (klant_id, weekdays, start_minuten, eind_minuten,
                code, activiteit, valid_from, valid_until)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            (klant_id, weekdays, start_minuten, eind_minuten,
             code, activiteit, valid_from, valid_until),
        )
        pid = (await cur.fetchone())[0]
        await conn.commit()
    return pid


async def db_list_patterns_for_klant(db_path, klant_id: int,
                                      include_inactive: bool = False) -> list[RecurringPattern]:
    where = "WHERE klant_id = ?"
    args = [klant_id]
    if not include_inactive:
        where += " AND actief = 1"
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            f"""SELECT id, klant_id, weekdays, start_minuten, eind_minuten,
                       code, activiteit, valid_from, valid_until, actief
                FROM klant_recurring_patterns {where}
                ORDER BY id""",
            args,
        )
        rows = await cur.fetchall()
    return [
        RecurringPattern(
            id=r[0], klant_id=r[1], weekdays=r[2],
            start_minuten=r[3], eind_minuten=r[4],
            code=r[5], activiteit=r[6],
            valid_from=r[7], valid_until=r[8],
            actief=bool(r[9]),
        ) for r in rows
    ]


async def db_update_pattern(db_path, pattern_id: int, **fields) -> None:
    if not fields:
        return
    cols = ', '.join(f"{k} = ?" for k in fields)
    args = list(fields.values()) + [pattern_id]
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            f"UPDATE klant_recurring_patterns SET {cols} WHERE id = ?",
            args,
        )
        await conn.commit()


async def db_delete_pattern_soft(db_path, pattern_id: int) -> None:
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "UPDATE klant_recurring_patterns SET actief = 0 WHERE id = ?",
            (pattern_id,),
        )
        await conn.commit()


async def db_get_pattern(db_path, pattern_id: int) -> RecurringPattern | None:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT id, klant_id, weekdays, start_minuten, eind_minuten,
                       code, activiteit, valid_from, valid_until, actief
                FROM klant_recurring_patterns WHERE id = ?""",
            (pattern_id,),
        )
        r = await cur.fetchone()
    if not r:
        return None
    return RecurringPattern(
        id=r[0], klant_id=r[1], weekdays=r[2],
        start_minuten=r[3], eind_minuten=r[4],
        code=r[5], activiteit=r[6],
        valid_from=r[7], valid_until=r[8],
        actief=bool(r[9]),
    )
```

In `services/agenda.py`, append below the pure helpers:

```python
from components.werkdag_form import CODES as _WERKDAG_CODES

import database

_VALID_PATTERN_CODES = frozenset(_WERKDAG_CODES.keys())


@dataclass(frozen=True)
class Pattern:
    id: int
    klant_id: int
    weekdays: list[int]    # parsed from CSV
    start_minuten: int
    eind_minuten: int
    code: str
    activiteit: str
    valid_from: str
    valid_until: str
    actief: bool


def _validate_pattern_code(code: str) -> None:
    if code not in _VALID_PATTERN_CODES:
        raise ValidationError(
            f"Ongeldige code '{code}'. Toegestaan: {sorted(_VALID_PATTERN_CODES)}"
        )


def _validate_pattern_minuten(start: int, eind: int) -> None:
    if not (0 <= start < 1440):
        raise ValidationError(f"start_minuten {start} buiten 0-1439")
    if not (0 < eind <= 1440):
        raise ValidationError(f"eind_minuten {eind} buiten 1-1440")
    if eind <= start:
        raise ValidationError(f"eind_minuten ({eind}) moet > start_minuten ({start})")


async def add_pattern(db_path, klant_id: int, weekdays: list[int],
                       start_minuten: int, eind_minuten: int,
                       code: str = 'WERKDAG',
                       activiteit: str = 'Waarneming dagpraktijk',
                       valid_from: str = '', valid_until: str = '') -> int:
    """NIET year-locked. Validates weekdays + minuten + code."""
    if not weekdays:
        raise ValidationError("weekdays mag niet leeg zijn")
    if any(w < 1 or w > 7 for w in weekdays):
        raise ValidationError(f"weekdays moeten 1-7 zijn, kreeg: {weekdays}")
    if len(set(weekdays)) != len(weekdays):
        raise ValidationError(f"weekdays bevat duplicaten: {weekdays}")
    _validate_pattern_minuten(start_minuten, eind_minuten)
    _validate_pattern_code(code)
    csv = ','.join(str(w) for w in sorted(set(weekdays)))
    return await database.db_add_pattern(
        db_path, klant_id=klant_id, weekdays=csv,
        start_minuten=start_minuten, eind_minuten=eind_minuten,
        code=code, activiteit=activiteit,
        valid_from=valid_from, valid_until=valid_until,
    )


async def list_patterns_for_klant(db_path, klant_id: int,
                                   include_inactive: bool = False) -> list[Pattern]:
    rows = await database.db_list_patterns_for_klant(
        db_path, klant_id, include_inactive=include_inactive,
    )
    return [
        Pattern(
            id=r.id, klant_id=r.klant_id,
            weekdays=parse_weekdays(r.weekdays),
            start_minuten=r.start_minuten, eind_minuten=r.eind_minuten,
            code=r.code, activiteit=r.activiteit,
            valid_from=r.valid_from, valid_until=r.valid_until,
            actief=r.actief,
        ) for r in rows
    ]


async def update_pattern(db_path, pattern_id: int, **fields) -> None:
    """NIET year-locked. Validates known fields if provided."""
    # Convert weekdays list -> CSV
    if 'weekdays' in fields:
        wd = fields['weekdays']
        if not wd or any(w < 1 or w > 7 for w in wd) or len(set(wd)) != len(wd):
            raise ValidationError(f"invalid weekdays: {wd}")
        fields['weekdays'] = ','.join(str(w) for w in sorted(set(wd)))
    if 'start_minuten' in fields or 'eind_minuten' in fields:
        existing = await database.db_get_pattern(db_path, pattern_id)
        start = fields.get('start_minuten', existing.start_minuten if existing else 0)
        eind = fields.get('eind_minuten', existing.eind_minuten if existing else 1)
        _validate_pattern_minuten(start, eind)
    if 'code' in fields:
        _validate_pattern_code(fields['code'])
    await database.db_update_pattern(db_path, pattern_id, **fields)


async def delete_pattern(db_path, pattern_id: int) -> None:
    """Soft delete: SET actief=0. NIET year-locked."""
    await database.db_delete_pattern_soft(db_path, pattern_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_service.py -v
```

Expected: 8 cases PASS

- [ ] **Step 5: Commit**

```bash
git add database.py services/agenda.py tests/test_agenda_service.py
git commit -m "feat(agenda): pattern CRUD in service-laag

add/list/update/delete patterns met validatie van weekdays, minuten, code.
NIET year-locked (projectie-data, geen fiscale feiten).
Soft-delete via actief=0 voor history-behoud.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.4: Blocker CRUD in service-laag

**Files:**
- Modify: `database.py` (add blocker CRUD helpers)
- Modify: `services/agenda.py` (add Blocker dataclass + functions)
- Test: `tests/test_agenda_service.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_agenda_service.py`:

```python
# ---- Blocker CRUD ----

@pytest.mark.asyncio
async def test_add_blocker_basic(db_with_klant):
    bid = await svc.add_blocker(
        db_with_klant, datum=date(2026, 7, 15),
        kind='vacation', label='Zomervakantie',
    )
    assert bid > 0


@pytest.mark.asyncio
async def test_add_blocker_holiday_kind_raises(db_with_klant):
    with pytest.raises(ValidationError):
        await svc.add_blocker(
            db_with_klant, datum=date(2026, 7, 15),
            kind='holiday', label='X',
        )


@pytest.mark.asyncio
async def test_add_blocker_on_existing_blocker_raises(db_with_klant):
    await svc.add_blocker(
        db_with_klant, datum=date(2026, 7, 15),
        kind='vacation', label='A',
    )
    with pytest.raises(ConflictError):
        await svc.add_blocker(
            db_with_klant, datum=date(2026, 7, 15),
            kind='sick', label='B',
        )


@pytest.mark.asyncio
async def test_add_blocker_on_existing_werkdag_raises(db_with_klant):
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief) "
            "VALUES ('2026-07-15', 1, 'WERKDAG', 8, 80)"
        )
        await conn.commit()
    with pytest.raises(ConflictError):
        await svc.add_blocker(
            db_with_klant, datum=date(2026, 7, 15),
            kind='vacation', label='X',
        )


@pytest.mark.asyncio
async def test_add_blocker_in_locked_year_raises(db_with_klant):
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (2025, 'definitief')"
        )
        await conn.commit()
    with pytest.raises(YearLockedError):
        await svc.add_blocker(
            db_with_klant, datum=date(2025, 7, 15),
            kind='vacation', label='X',
        )


@pytest.mark.asyncio
async def test_delete_blocker(db_with_klant):
    bid = await svc.add_blocker(
        db_with_klant, datum=date(2026, 7, 15),
        kind='vacation', label='X',
    )
    await svc.delete_blocker(db_with_klant, bid)
    blockers = await svc.list_blockers(
        db_with_klant, vanaf=date(2026, 7, 1), tot=date(2026, 7, 31),
    )
    user_blockers = [b for b in blockers if b.kind != 'holiday']
    assert user_blockers == []


@pytest.mark.asyncio
async def test_delete_blocker_in_locked_year_raises(db_with_klant):
    bid = await svc.add_blocker(
        db_with_klant, datum=date(2026, 7, 15),
        kind='vacation', label='X',
    )
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (2026, 'definitief')"
        )
        await conn.commit()
    with pytest.raises(YearLockedError):
        await svc.delete_blocker(db_with_klant, bid)


@pytest.mark.asyncio
async def test_list_blockers_includes_holidays(db_with_klant):
    blockers = await svc.list_blockers(
        db_with_klant, vanaf=date(2026, 4, 1), tot=date(2026, 4, 30),
    )
    # April 2026: Goede Vrijdag, Eerste Paasdag, Tweede Paasdag, Koningsdag
    holiday_dates = {b.datum for b in blockers if b.kind == 'holiday'}
    assert date(2026, 4, 3) in holiday_dates  # Goede Vrijdag
    assert date(2026, 4, 5) in holiday_dates  # Eerste Paasdag
    assert date(2026, 4, 27) in holiday_dates  # Koningsdag
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_service.py -v -k blocker
```

Expected: FAIL "AttributeError: module 'services.agenda' has no attribute 'add_blocker'"

- [ ] **Step 3: Add blocker DB-helpers in `database.py`**

```python
@dataclass(frozen=True)
class BlockerRow:
    id: int
    datum: str
    kind: str
    label: str


async def db_add_blocker(db_path, datum: str, kind: str, label: str = '') -> int:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "INSERT INTO blockers (datum, kind, label) VALUES (?, ?, ?) RETURNING id",
            (datum, kind, label),
        )
        bid = (await cur.fetchone())[0]
        await conn.commit()
    return bid


async def db_get_blocker(db_path, blocker_id: int) -> BlockerRow | None:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT id, datum, kind, label FROM blockers WHERE id = ?",
            (blocker_id,),
        )
        r = await cur.fetchone()
    return BlockerRow(id=r[0], datum=r[1], kind=r[2], label=r[3]) if r else None


async def db_delete_blocker(db_path, blocker_id: int) -> None:
    async with get_db_ctx(db_path) as conn:
        await conn.execute("DELETE FROM blockers WHERE id = ?", (blocker_id,))
        await conn.commit()


async def db_list_blockers(db_path, vanaf: str, tot: str) -> list[BlockerRow]:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT id, datum, kind, label FROM blockers "
            "WHERE datum >= ? AND datum <= ? ORDER BY datum",
            (vanaf, tot),
        )
        rows = await cur.fetchall()
    return [BlockerRow(id=r[0], datum=r[1], kind=r[2], label=r[3]) for r in rows]


async def db_count_werkdagen_op_datum(db_path, datum: str) -> int:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM werkdagen WHERE datum = ?", (datum,),
        )
        return (await cur.fetchone())[0]
```

- [ ] **Step 4: Add blocker service-functions**

Append in `services/agenda.py`:

```python
from services.holidays import dutch_holidays


_VALID_BLOCKER_KINDS = frozenset({'vacation', 'sick', 'training'})


@dataclass(frozen=True)
class Blocker:
    id: int | None       # None for computed holidays
    datum: _date
    kind: str            # 'vacation' | 'sick' | 'training' | 'holiday'
    label: str


async def add_blocker(db_path, datum: _date, kind: str, label: str = '') -> int:
    """Add user-blocker. Raises:
        ValidationError: invalid kind (incl. 'holiday')
        ConflictError:   blocker exists OR werkdag exists on date
        YearLockedError: datum in afgesloten jaar
    """
    if kind not in _VALID_BLOCKER_KINDS:
        raise ValidationError(
            f"Invalid kind '{kind}'. Toegestaan: {sorted(_VALID_BLOCKER_KINDS)}"
        )
    datum_str = datum.isoformat()
    await database.assert_year_writable(db_path, datum_str)
    # Check werkdag conflict
    n = await database.db_count_werkdagen_op_datum(db_path, datum_str)
    if n > 0:
        raise ConflictError(
            f"Werkdag bestaat al op {datum_str} — verwijder de werkdag eerst."
        )
    # Insert (UNIQUE constraint catches existing blocker → IntegrityError)
    try:
        return await database.db_add_blocker(
            db_path, datum=datum_str, kind=kind, label=label,
        )
    except aiosqlite.IntegrityError as e:
        raise ConflictError(f"Datum {datum_str} heeft al een blocker") from e


async def delete_blocker(db_path, blocker_id: int) -> None:
    """Raises YearLockedError if blocker.datum in afgesloten jaar."""
    blocker = await database.db_get_blocker(db_path, blocker_id)
    if not blocker:
        return  # idempotent silent no-op
    await database.assert_year_writable(db_path, blocker.datum)
    await database.db_delete_blocker(db_path, blocker_id)


async def list_blockers(db_path, vanaf: _date, tot: _date) -> list[Blocker]:
    """User-blockers + computed holidays gemerged. Holidays don't have id."""
    user_rows = await database.db_list_blockers(
        db_path, vanaf.isoformat(), tot.isoformat(),
    )
    user_blockers = [
        Blocker(id=r.id, datum=_date.fromisoformat(r.datum),
                kind=r.kind, label=r.label)
        for r in user_rows
    ]
    # Compute holidays for year-range covered
    out = list(user_blockers)
    user_dates = {b.datum for b in user_blockers}
    for jaar in range(vanaf.year, tot.year + 1):
        for h in dutch_holidays(jaar):
            if not (vanaf <= h.datum <= tot):
                continue
            if h.datum in user_dates:
                continue  # user-blocker wins for the user, but we display holiday
            out.append(Blocker(id=None, datum=h.datum, kind='holiday', label=h.label))
    out.sort(key=lambda b: b.datum)
    return out
```

Add `import aiosqlite` at top of `services/agenda.py` (only place needed; we
catch IntegrityError to convert to ConflictError).

- [ ] **Step 5: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_service.py -v
```

Expected: 16 cases PASS

- [ ] **Step 6: Commit**

```bash
git add database.py services/agenda.py tests/test_agenda_service.py
git commit -m "feat(agenda): blocker CRUD + holiday-merge in service-laag

add_blocker valideert kind, checkt werkdag-conflict, year-lock.
list_blockers merged user-blockers + computed dutch_holidays voor range.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.5: `confirm_expected` met race-protectie + idempotency

**Files:**
- Modify: `services/agenda.py` (add confirm_expected)
- Test: `tests/test_agenda_service.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_agenda_service.py`:

```python
# ---- confirm_expected ----

async def _add_test_pattern(db, klant_id=1):
    return await svc.add_pattern(
        db, klant_id=klant_id, weekdays=[1, 3],  # Ma, Wo
        start_minuten=480, eind_minuten=1020, code='WERKDAG',
    )


@pytest.mark.asyncio
async def test_confirm_expected_creates_werkdag(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    # 4 mei 2026 = maandag
    werkdag_id = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
    )
    assert werkdag_id > 0
    async with aiosqlite.connect(db_with_klant) as conn:
        cur = await conn.execute(
            "SELECT klant_id, code, uren FROM werkdagen WHERE id = ?",
            (werkdag_id,),
        )
        row = await cur.fetchone()
    assert row[0] == 1
    assert row[1] == 'WERKDAG'
    assert row[2] == pytest.approx(9.0)  # 480→1020 = 540min = 9u


@pytest.mark.asyncio
async def test_confirm_expected_idempotent(db_with_klant):
    """Tweede call met zelfde (klant, datum, pattern) returnt zelfde id."""
    pid = await _add_test_pattern(db_with_klant)
    id1 = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
    )
    id2 = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
    )
    assert id1 == id2


@pytest.mark.asyncio
async def test_confirm_expected_with_overrides(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    werkdag_id = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
        start_minuten=540, eind_minuten=1080,  # 09:00-18:00 = 9u
    )
    async with aiosqlite.connect(db_with_klant) as conn:
        cur = await conn.execute(
            "SELECT uren FROM werkdagen WHERE id = ?", (werkdag_id,),
        )
        uren = (await cur.fetchone())[0]
    assert uren == pytest.approx(9.0)


@pytest.mark.asyncio
async def test_confirm_expected_in_locked_year_raises(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (2025, 'definitief')"
        )
        await conn.commit()
    with pytest.raises(YearLockedError):
        await svc.confirm_expected(
            db_with_klant, pattern_id=pid, datum=date(2025, 6, 2),
        )


@pytest.mark.asyncio
async def test_confirm_expected_on_deleted_pattern_raises(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    await svc.delete_pattern(db_with_klant, pid)
    with pytest.raises(ConflictError):
        await svc.confirm_expected(
            db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_service.py -v -k confirm
```

Expected: FAIL "AttributeError: module 'services.agenda' has no attribute 'confirm_expected'"

- [ ] **Step 3: Implement `confirm_expected`**

Append in `services/agenda.py`:

```python
async def confirm_expected(
    db_path,
    pattern_id: int,
    datum: _date,
    start_minuten: int | None = None,
    eind_minuten: int | None = None,
    activiteit: str | None = None,
) -> int:
    """Promote virtual expected entry to real werkdag.

    Idempotent: als er al een werkdag bestaat voor (klant_id, datum) waar
    deze pattern verantwoordelijk voor is, return existing werkdag.id
    zonder mutatie.

    Raises:
        ConflictError:   pattern niet meer actief
        YearLockedError: datum in afgesloten jaar
        ValidationError: tijden invalid
    """
    pattern = await database.db_get_pattern(db_path, pattern_id)
    if pattern is None or not pattern.actief:
        raise ConflictError(
            f"Patroon {pattern_id} is verwijderd of inactief — refresh agenda."
        )
    # Year-lock check via add_werkdag's eigen guard
    datum_str = datum.isoformat()
    await database.assert_year_writable(db_path, datum_str)
    # Idempotency: bestaat er al een werkdag op deze datum voor deze klant?
    async with database.get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT id FROM werkdagen WHERE datum = ? AND klant_id = ? "
            "ORDER BY id LIMIT 1",
            (datum_str, pattern.klant_id),
        )
        existing = await cur.fetchone()
    if existing:
        return existing[0]
    # Determine fields with optional overrides
    start = start_minuten if start_minuten is not None else pattern.start_minuten
    eind = eind_minuten if eind_minuten is not None else pattern.eind_minuten
    _validate_pattern_minuten(start, eind)
    uren = (eind - start) / 60.0
    act = activiteit if activiteit is not None else pattern.activiteit
    # Get klant tarief
    klant = await database.get_klant_by_id(db_path, pattern.klant_id)
    if klant is None:
        raise ConflictError(f"Klant {pattern.klant_id} bestaat niet meer.")
    # Determine urennorm: dagpraktijk + ANW = 1, ACHTERWACHT = 0, overig depends on _ZERO_UREN_CODES
    from components.werkdag_form import _ZERO_UREN_CODES
    urennorm = 0 if pattern.code in _ZERO_UREN_CODES or pattern.code == 'ACHTERWACHT' else 1
    return await database.add_werkdag(
        db_path,
        datum=datum_str,
        klant_id=pattern.klant_id,
        code=pattern.code,
        activiteit=act,
        locatie=klant.adres or '',
        locatie_id=None,
        uren=uren,
        km=klant.retour_km or 0,
        tarief=klant.tarief_uur,
        km_tarief=0.23,  # default — could be fetched from fiscale_params if needed
        urennorm=urennorm,
        opmerking='',
    )
```

**Note**: This task assumes `database.get_klant_by_id` exists. Verify:

```bash
grep "def get_klant_by_id\|async def get_klant_by_id" database.py
```

If missing, add a small helper:

```python
async def get_klant_by_id(db_path, klant_id: int) -> Klant | None:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT id, naam, tarief_uur, retour_km, adres, kvk, actief "
            "FROM klanten WHERE id = ?",
            (klant_id,),
        )
        r = await cur.fetchone()
    if not r:
        return None
    return Klant(id=r[0], naam=r[1], tarief_uur=r[2], retour_km=r[3],
                 adres=r[4], kvk=r[5], actief=bool(r[6]))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_service.py -v
```

Expected: 21 cases PASS

- [ ] **Step 5: Commit**

```bash
git add database.py services/agenda.py tests/test_agenda_service.py
git commit -m "feat(agenda): confirm_expected met race-protectie + idempotency

Pattern-deleted check raises ConflictError. Double-click veilig: returnt
bestaande werkdag.id. Year-lock via add_werkdag delegate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.6: `get_maand` + `get_dag` view-functies

**Files:**
- Modify: `services/agenda.py`
- Test: `tests/test_agenda_service.py` (extend)

- [ ] **Step 1: Write failing tests**

Append:

```python
# ---- get_maand / get_dag ----

@pytest.mark.asyncio
async def test_get_maand_returns_correct_structure(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    # Vandaag mocken op 1 mei 2026 zodat hele mei toekomstig is
    monkeypatch_today(svc, date(2026, 5, 1))
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    assert view.jaar == 2026
    assert view.maand == 5
    assert len(view.dagen) >= 28


@pytest.mark.asyncio
async def test_get_maand_excludes_blockers_from_expected(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    # Blocker op 4 mei 2026 (maandag)
    await svc.add_blocker(
        db_with_klant, datum=date(2026, 5, 4),
        kind='vacation', label='Vakantie',
    )
    monkeypatch_today(svc, date(2026, 5, 1))
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    dag_4mei = next(d for d in view.dagen if d.datum == date(2026, 5, 4))
    assert dag_4mei.expected == []
    assert dag_4mei.blocker is not None


@pytest.mark.asyncio
async def test_get_maand_excludes_holidays_from_expected(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    monkeypatch_today(svc, date(2026, 4, 1))
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=4)
    # 27 april 2026 = maandag = Koningsdag = pattern-day MA, maar holiday
    koningsdag_dag = next(d for d in view.dagen if d.datum == date(2026, 4, 27))
    assert koningsdag_dag.expected == []
    assert koningsdag_dag.blocker is not None
    assert koningsdag_dag.blocker.kind == 'holiday'


@pytest.mark.asyncio
async def test_get_maand_returns_factuur_status_per_werkdag(db_with_klant):
    """Kern-feature: factuur-status zichtbaar per werkdag."""
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO facturen (nummer, klant_id, datum, totaal_bedrag, "
            "betaald, status) VALUES ('2026-001', 1, '2026-05-04', 800, 0, 'concept')"
        )
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief, factuurnummer) "
            "VALUES ('2026-05-04', 1, 'WERKDAG', 8, 80, '2026-001')"
        )
        await conn.commit()
    monkeypatch_today(svc, date(2026, 5, 13))
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    dag = next(d for d in view.dagen if d.datum == date(2026, 5, 4))
    assert len(dag.werkdagen) == 1
    assert dag.werkdagen[0].factuur_status == 'concept'
    assert dag.werkdagen[0].status_label == 'concept'


@pytest.mark.asyncio
async def test_get_dag_returns_single_day(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    monkeypatch_today(svc, date(2026, 5, 1))
    dag = await svc.get_dag(db_with_klant, datum=date(2026, 5, 4))
    assert dag.datum == date(2026, 5, 4)
    assert len(dag.expected) == 1  # pattern matches Ma


def monkeypatch_today(module, fake_today):
    module._today = lambda: fake_today
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_service.py::test_get_maand_returns_correct_structure -v
```

Expected: FAIL

- [ ] **Step 3: Implement `MaandView`, `DagView`, `WerkdagPill`, `ExpectedEntry`, `get_maand`, `get_dag`**

Append in `services/agenda.py`:

```python
def _today() -> _date:
    """Indirection voor test-monkeypatch."""
    return _date.today()


def _iso_weekday(d: _date) -> int:
    """Mon=1..Sun=7."""
    return d.isoweekday()


@dataclass(frozen=True)
class WerkdagPill:
    id: int
    klant_id: int
    klant_naam: str
    code: str
    uren: float
    bedrag: float
    factuurnummer: str
    factuur_status: str
    factuur_vervaldatum: str
    status_label: WerkdagStatusLabel
    category: WerkdagCategory


@dataclass(frozen=True)
class ExpectedEntry:
    pattern_id: int
    klant_id: int
    klant_naam: str
    start_minuten: int
    eind_minuten: int
    uren: float
    code: str
    activiteit: str
    category: WerkdagCategory


@dataclass(frozen=True)
class DagView:
    datum: _date
    werkdagen: list[WerkdagPill]
    expected: list[ExpectedEntry]
    blocker: Blocker | None


@dataclass(frozen=True)
class MaandView:
    jaar: int
    maand: int
    dagen: list[DagView]


def _is_in_pattern_validity(pattern: Pattern, datum: _date) -> bool:
    if pattern.valid_from:
        if datum < _date.fromisoformat(pattern.valid_from):
            return False
    if pattern.valid_until:
        if datum > _date.fromisoformat(pattern.valid_until):
            return False
    return True


async def _expected_for_datum(db_path, datum: _date,
                               patterns_by_klant: dict[int, list[Pattern]],
                               klanten_by_id: dict[int, 'Klant']) -> list[ExpectedEntry]:
    """Compute expected entries for a future date."""
    if datum <= _today():
        return []
    iso = _iso_weekday(datum)
    out = []
    for klant_id, plist in patterns_by_klant.items():
        klant = klanten_by_id.get(klant_id)
        if not klant:
            continue
        for p in plist:
            if not p.actief:
                continue
            if iso not in p.weekdays:
                continue
            if not _is_in_pattern_validity(p, datum):
                continue
            uren = (p.eind_minuten - p.start_minuten) / 60.0
            out.append(ExpectedEntry(
                pattern_id=p.id,
                klant_id=klant_id,
                klant_naam=klant.naam,
                start_minuten=p.start_minuten,
                eind_minuten=p.eind_minuten,
                uren=uren,
                code=p.code,
                activiteit=p.activiteit,
                category=categorize_werkdag(p.code),
            ))
    return out


async def get_maand(db_path, jaar: int, maand: int,
                     include_expected: bool = True) -> MaandView:
    """Returns MaandView with all days of the month, populated with werkdagen,
    expected, and blockers."""
    today = _today()
    # 1. Load all werkdagen for month with factuur status
    werkdagen_raw = await database.get_werkdagen_met_factuur_status(
        db_path, jaar, maand,
    )
    werkdagen_by_datum: dict[_date, list[WerkdagPill]] = {}
    for w in werkdagen_raw:
        d = _date.fromisoformat(w.datum)
        bedrag = (w.uren or 0) * (w.tarief or 0) + (w.km or 0) * (w.km_tarief or 0)
        pill = WerkdagPill(
            id=w.id, klant_id=w.klant_id, klant_naam=w.klant_naam,
            code=w.code, uren=w.uren, bedrag=bedrag,
            factuurnummer=w.factuurnummer,
            factuur_status=w.factuur_status,
            factuur_vervaldatum=w.factuur_vervaldatum,
            status_label=derive_werkdag_status_label(w, today),
            category=categorize_werkdag(w.code),
        )
        werkdagen_by_datum.setdefault(d, []).append(pill)

    # 2. Load blockers (user + holidays) for full month
    from calendar import monthrange
    last_day = monthrange(jaar, maand)[1]
    vanaf = _date(jaar, maand, 1)
    tot = _date(jaar, maand, last_day)
    blockers = await list_blockers(db_path, vanaf, tot)
    blockers_by_datum: dict[_date, Blocker] = {b.datum: b for b in blockers}

    # 3. Load patterns + klanten for expected
    patterns_by_klant: dict[int, list[Pattern]] = {}
    klanten_by_id: dict[int, 'Klant'] = {}
    if include_expected:
        klanten = await database.get_klanten(db_path)
        for k in klanten:
            klanten_by_id[k.id] = k
            patterns_by_klant[k.id] = await list_patterns_for_klant(
                db_path, k.id, include_inactive=False,
            )

    # 4. Build DagView per day
    dagen: list[DagView] = []
    for day in range(1, last_day + 1):
        d = _date(jaar, maand, day)
        wd_list = werkdagen_by_datum.get(d, [])
        block = blockers_by_datum.get(d)
        # Expected only when no werkdag and no blocker
        if include_expected and not wd_list and not block:
            expected = await _expected_for_datum(
                db_path, d, patterns_by_klant, klanten_by_id,
            )
        else:
            expected = []
        dagen.append(DagView(
            datum=d, werkdagen=wd_list, expected=expected, blocker=block,
        ))

    return MaandView(jaar=jaar, maand=maand, dagen=dagen)


async def get_dag(db_path, datum: _date,
                   include_expected: bool = True) -> DagView:
    """Single-day view for inspector refresh."""
    view = await get_maand(db_path, datum.year, datum.month, include_expected)
    for d in view.dagen:
        if d.datum == datum:
            return d
    return DagView(datum=datum, werkdagen=[], expected=[], blocker=None)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_service.py -v
```

Expected: 26 cases PASS

- [ ] **Step 5: Commit**

```bash
git add services/agenda.py tests/test_agenda_service.py
git commit -m "feat(agenda): get_maand + get_dag view-functies

MaandView/DagView/WerkdagPill/ExpectedEntry frozen dataclasses.
Factuur-status per werkdag via JOIN-query + derive_werkdag_status_label.
Expected onderdrukt door werkdag of blocker (incl. holidays).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2.7: `get_zes_weken_prognose` + `get_urencriterium_projectie`

**Files:**
- Modify: `services/agenda.py`
- Test: `tests/test_agenda_service.py` (extend)

- [ ] **Step 1: Write failing tests**

Append:

```python
# ---- prognose + urencriterium ----

@pytest.mark.asyncio
async def test_zes_weken_prognose_returns_6_weeks(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    monkeypatch_today(svc, date(2026, 5, 1))
    weeks = await svc.get_zes_weken_prognose(
        db_with_klant, vanaf=date(2026, 5, 13),
    )
    assert len(weeks) == 6


@pytest.mark.asyncio
async def test_urencriterium_projectie_basic(db_with_klant):
    """Bevestigde uren YTD + verwachte uren tot jaar-eind."""
    monkeypatch_today(svc, date(2026, 5, 13))
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief, urennorm) "
            "VALUES ('2026-04-15', 1, 'WERKDAG', 8, 80, 1)"
        )
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief, urennorm) "
            "VALUES ('2026-04-22', 1, 'WERKDAG', 9, 80, 1)"
        )
        await conn.commit()
    state = await svc.get_urencriterium_projectie(db_with_klant, jaar=2026)
    assert state.confirmed_uren == 17.0
    assert state.target == 1225.0


@pytest.mark.asyncio
async def test_urencriterium_excludes_urennorm_zero(db_with_klant):
    """ACHTERWACHT/CONGRES (urennorm=0) telt NIET mee."""
    monkeypatch_today(svc, date(2026, 5, 13))
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief, urennorm) "
            "VALUES ('2026-04-15', 1, 'ACHTERWACHT', 12, 0, 0)"
        )
        await conn.commit()
    state = await svc.get_urencriterium_projectie(db_with_klant, jaar=2026)
    assert state.confirmed_uren == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL.

- [ ] **Step 3: Implement helpers**

Append in `services/agenda.py`:

```python
@dataclass(frozen=True)
class WeekTotaal:
    week_start: _date
    week_nummer: int
    confirmed_amt: float
    planned_amt: float       # confirmed werkdagen with future datum
    expected_amt: float
    confirmed_uren: float
    expected_uren: float
    confirmed_dagen: int
    expected_dagen: int
    blocked_dagen: int


@dataclass(frozen=True)
class UrencriteriumState:
    jaar: int
    confirmed_uren: float
    expected_uren_remainder: float
    target: float
    pace_pct: float
    will_make: bool


def _iso_week_number(d: _date) -> int:
    return d.isocalendar()[1]


def _start_of_week(d: _date) -> _date:
    return d - timedelta(days=d.isoweekday() - 1)


async def get_zes_weken_prognose(db_path, vanaf: _date) -> list[WeekTotaal]:
    """6 consecutive weeks vanaf de Maandag van vanaf-week."""
    start = _start_of_week(vanaf)
    out = []
    for i in range(6):
        ws = start + timedelta(days=7 * i)
        out.append(await _week_totaal(db_path, ws))
    return out


async def _week_totaal(db_path, week_start: _date) -> WeekTotaal:
    """Aggregate confirmed + expected for a single week."""
    confirmed_amt = 0.0
    expected_amt = 0.0
    confirmed_uren = 0.0
    expected_uren = 0.0
    confirmed_dagen = 0
    expected_dagen = 0
    blocked_dagen = 0
    for i in range(7):
        d = week_start + timedelta(days=i)
        view = await get_dag(db_path, d)
        if view.blocker:
            blocked_dagen += 1
        if view.werkdagen:
            confirmed_dagen += 1
            for w in view.werkdagen:
                confirmed_amt += w.bedrag
                confirmed_uren += w.uren
        if view.expected:
            expected_dagen += 1
            for e in view.expected:
                expected_uren += e.uren
                # Bedrag: uren * tarief — but we don't have tarief in ExpectedEntry
                # Fetch from klant lazy (below)
        if view.expected:
            klant = await database.get_klant_by_id(db_path, view.expected[0].klant_id)
            for e in view.expected:
                if e.klant_id == view.expected[0].klant_id:
                    expected_amt += e.uren * (klant.tarief_uur if klant else 0)
    return WeekTotaal(
        week_start=week_start,
        week_nummer=_iso_week_number(week_start),
        confirmed_amt=confirmed_amt,
        planned_amt=0.0,  # niet gedifferentieerd in Sprint A
        expected_amt=expected_amt,
        confirmed_uren=confirmed_uren,
        expected_uren=expected_uren,
        confirmed_dagen=confirmed_dagen,
        expected_dagen=expected_dagen,
        blocked_dagen=blocked_dagen,
    )


async def get_urencriterium_projectie(db_path, jaar: int) -> UrencriteriumState:
    """confirmed YTD + expected remainder + target."""
    today = _today()
    target = 1225.0  # default; could read fiscale_params.urencriterium
    fp = await database.get_fiscale_params(db_path, jaar)
    if fp and getattr(fp, 'urencriterium', None):
        target = float(fp.urencriterium)
    # Confirmed uren YTD (urennorm=1 only)
    async with database.get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT COALESCE(SUM(uren), 0) FROM werkdagen "
            "WHERE substr(datum,1,4) = ? AND urennorm = 1 AND datum <= ?",
            (str(jaar), today.isoformat()),
        )
        confirmed = float((await cur.fetchone())[0] or 0)
    # Expected uren tot jaar-eind
    expected_remainder = 0.0
    d = today + timedelta(days=1)
    jaareinde = _date(jaar, 12, 31)
    if d <= jaareinde:
        # Iterate maand-voor-maand om duplicate get_maand-calls te vermijden
        cur_d = d
        seen_maanden: set[tuple[int, int]] = set()
        while cur_d <= jaareinde:
            key = (cur_d.year, cur_d.month)
            if key not in seen_maanden:
                seen_maanden.add(key)
                view = await get_maand(db_path, cur_d.year, cur_d.month)
                for dag in view.dagen:
                    if dag.datum < d or dag.datum.year != jaar:
                        continue
                    for e in dag.expected:
                        if e.code in {'ACHTERWACHT', 'CONGRES', 'OPLEIDING', 'OVERIG_ZAK'}:
                            continue
                        expected_remainder += e.uren
            # Advance to next month
            if cur_d.month == 12:
                break
            cur_d = _date(cur_d.year, cur_d.month + 1, 1)
    projected = confirmed + expected_remainder
    yearstart = _date(jaar, 1, 1)
    yearlen = (_date(jaar + 1, 1, 1) - yearstart).days
    pace_pct = ((today - yearstart).days + 1) / yearlen * 100 if today.year == jaar else 100.0
    return UrencriteriumState(
        jaar=jaar,
        confirmed_uren=confirmed,
        expected_uren_remainder=expected_remainder,
        target=target,
        pace_pct=pace_pct,
        will_make=projected >= target,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_service.py -v
```

Expected: 29 cases PASS

- [ ] **Step 5: Commit**

```bash
git add services/agenda.py tests/test_agenda_service.py
git commit -m "feat(agenda): 6-weken prognose + urencriterium-projectie

WeekTotaal aggregeert confirmed + expected per week.
UrencriteriumState rekent YTD + expected remainder + pace + target.
ACHTERWACHT/CONGRES/OPLEIDING/OVERIG_ZAK tellen niet voor urencriterium.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Sessie 3 — UI A: Maandgrid + Day-Inspector + Sidebar (4-5u)

### Task 3.1: Sidebar nav-item `/agenda`

**Files:**
- Modify: `components/layout.py` (find nav-items list, add agenda entry)

- [ ] **Step 1: Find existing sidebar items**

```bash
grep -n "Werkdagen\|Dashboard.*'/'" components/layout.py | head -10
```

- [ ] **Step 2: Add agenda nav-item**

In `components/layout.py`, locate the sidebar nav-items list. Add between Dashboard and Werkdagen:

```python
{'route': '/agenda', 'icon': 'calendar_month', 'label': 'Agenda'},
```

- [ ] **Step 3: Add CSS classes for werkdag-categorie + status-bars**

In `components/layout.py`, in the `ui.add_css('''...''')` block, append:

```css
/* === Agenda — werkdag-categorie kleuren === */
.wd-pill {
    display: inline-flex;
    align-items: center;
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 500;
    line-height: 1.4;
    margin: 1px 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 100%;
}
.wd-dagpraktijk { background: rgba(15,118,110,0.12); color: #0F766E; }
.wd-anw         { background: rgba(126,34,206,0.12); color: #7E22CE; }
.wd-overig      { background: rgba(100,116,139,0.12); color: #475569; }

/* Verwachte entries (recurring) — dashed border + soft fill */
.wd-pill.expected {
    border: 1px dashed currentColor;
    opacity: 0.7;
}

/* Status-bars onder werkdag-pills */
.wd-status-bar {
    display: flex;
    height: 3px;
    gap: 1px;
    margin-top: 2px;
}
.wd-status-bar > span {
    flex: 1;
    border-radius: 1px;
}
.status-ongefactureerd { background: #94A3B8; }
.status-concept        { background: #94A3B8; opacity: 0.6; }
.status-verstuurd      { background: #2563EB; }
.status-verlopen       { background: #DC2626; }
.status-betaald        { background: #16A34A; }

/* Holiday marker */
.holiday-marker {
    background: linear-gradient(180deg, rgba(220,38,38,0.08), transparent);
    border-top: 2px solid #DC2626;
}
.holiday-label {
    font-size: 10px;
    color: #DC2626;
    font-weight: 500;
}

/* Blocker overlay */
.blocker-cell { background: rgba(255,149,0,0.08); }
.blocker-vacation { background: rgba(90,200,250,0.10); }
.blocker-sick { background: rgba(255,149,0,0.10); }
.blocker-training { background: rgba(175,82,222,0.10); }
```

- [ ] **Step 4: Manual smoke test**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
# Verifieer: sidebar toont Agenda nav-item tussen Dashboard en Werkdagen
# Klik /agenda → 404 (page nog niet geïmplementeerd) — OK voor nu
# Sluit app
```

- [ ] **Step 5: Commit**

```bash
git add components/layout.py
git commit -m "feat(agenda): sidebar /agenda nav-item + agenda CSS classes

Werkdag-categorie kleuren (dagpraktijk teal, anw paars, overig grijs).
Status-bar kleuren per factuur-status. Holiday-marker + blocker overlays.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.2: `pages/agenda.py` skeleton + smoke test

**Files:**
- Create: `pages/agenda.py`
- Create: `tests/test_agenda_page.py`

- [ ] **Step 1: Write failing smoke test**

```python
# tests/test_agenda_page.py
"""Smoke tests voor /agenda — verifieert dat de page laadt zonder error."""
import pytest


def test_agenda_module_imports():
    """Should import zonder error."""
    import pages.agenda
    assert hasattr(pages.agenda, 'agenda_page')


def test_agenda_page_is_registered():
    """Should be registered under /agenda route."""
    import pages.agenda  # ensures import + registration
    from nicegui import app
    routes = {r.path for r in app.routes if hasattr(r, 'path')}
    assert '/agenda' in routes
```

- [ ] **Step 2: Run test to verify it fails**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_page.py -v
```

Expected: FAIL "ModuleNotFoundError: No module named 'pages.agenda'"

- [ ] **Step 3: Implement skeleton**

```python
# pages/agenda.py
"""Agenda pagina — kalender met recurring patterns, blockers, factuur-status.

Spec: docs/superpowers/specs/2026-05-02-agenda-sprint-a-design.md
"""
from datetime import date

from nicegui import ui

from components.layout import create_layout, page_title
from database import DB_PATH
import services.agenda as agenda_svc


@ui.page('/agenda')
async def agenda_page():
    create_layout('Agenda', '/agenda')

    # State
    today = date.today()
    state = {
        'anchor': today,         # first day of displayed month
        'selected': today,
    }

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):
        with ui.row().classes('w-full items-center'):
            page_title('Agenda')

        # Top toolbar
        with ui.row().classes('w-full items-center gap-2'):
            prev_btn = ui.button(icon='chevron_left').props('flat round dense')
            today_btn = ui.button('Vandaag').props('flat')
            next_btn = ui.button(icon='chevron_right').props('flat round dense')
            month_label = ui.label('').classes('text-xl font-medium ml-2')
            ui.space()
            refresh_btn = ui.button('Ververs', icon='refresh').props('flat dense')
            new_btn = ui.button('Nieuwe werkdag', icon='add').props('color=primary')

        # Main grid + inspector
        with ui.row().classes('w-full gap-4'):
            grid_container = ui.column().classes('flex-1')
            inspector_container = ui.column().classes('w-80')

        # Urencriterium strip
        urencrit_strip = ui.label('').classes('text-sm text-slate-600')

    async def render():
        view = await agenda_svc.get_maand(
            DB_PATH, jaar=state['anchor'].year, maand=state['anchor'].month,
        )
        month_label.text = state['anchor'].strftime('%B %Y').capitalize()
        # TODO Sessie 3.3+: render MonthGrid + DayInspector + urencrit_strip
        grid_container.clear()
        with grid_container:
            ui.label(f'{len(view.dagen)} dagen, {state["anchor"].strftime("%B %Y")}')
        inspector_container.clear()
        with inspector_container:
            ui.label(f'Geselecteerd: {state["selected"].isoformat()}')
        # Urencriterium
        urencrit = await agenda_svc.get_urencriterium_projectie(
            DB_PATH, state['anchor'].year,
        )
        urencrit_strip.text = (
            f"Urencriterium {urencrit.jaar}: "
            f"{urencrit.confirmed_uren:.0f}u van {urencrit.target:.0f}u — "
            f"verwacht jaar-eind: {urencrit.confirmed_uren + urencrit.expected_uren_remainder:.0f}u "
            f"{'✓ Voldoet' if urencrit.will_make else '! Krap'}"
        )

    def go_prev():
        a = state['anchor']
        if a.month == 1:
            state['anchor'] = date(a.year - 1, 12, 1)
        else:
            state['anchor'] = date(a.year, a.month - 1, 1)
        ui.timer(0, render, once=True)

    def go_next():
        a = state['anchor']
        if a.month == 12:
            state['anchor'] = date(a.year + 1, 1, 1)
        else:
            state['anchor'] = date(a.year, a.month + 1, 1)
        ui.timer(0, render, once=True)

    def go_today():
        t = date.today()
        state['anchor'] = date(t.year, t.month, 1)
        state['selected'] = t
        ui.timer(0, render, once=True)

    prev_btn.on_click(go_prev)
    next_btn.on_click(go_next)
    today_btn.on_click(go_today)
    refresh_btn.on_click(lambda: ui.timer(0, render, once=True))

    await render()
```

- [ ] **Step 4: Register page module in `main.py`**

Check if `main.py` imports pages:

```bash
grep "import pages\." main.py | head -10
```

If pages are explicitly imported one-by-one, add:

```python
import pages.agenda  # noqa: F401 — registers /agenda route
```

If pages are auto-discovered: nothing to do.

- [ ] **Step 5: Run smoke tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_page.py -v
```

Expected: 2 cases PASS

- [ ] **Step 6: Manual smoke test**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
# Klik /agenda in sidebar
# Verifieer: page laadt, toont maand-naam, prev/next/today knoppen werken
# Sluit app
```

- [ ] **Step 7: Commit**

```bash
git add pages/agenda.py tests/test_agenda_page.py main.py
git commit -m "feat(agenda): /agenda page skeleton met maand-navigatie

Toolbar (prev/today/next/refresh/nieuw), placeholder grid + inspector,
urencriterium-strip onderaan. Volledige rendering in volgende task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.3: MonthGrid renderer met factuur-status-bars

**Files:**
- Modify: `pages/agenda.py` (vervang grid_container.clear placeholder)

- [ ] **Step 1: Implement `_render_month_grid`**

In `pages/agenda.py`, replace the placeholder rendering inside `render()`:

```python
DOW_LABELS = ['Ma', 'Di', 'Wo', 'Do', 'Vr', 'Za', 'Zo']


def _render_month_grid(container, view, on_day_click, selected):
    """Render 7-col day grid with klant-pills + status-bars + week-summary col."""
    container.clear()
    with container:
        # Day-of-week header
        with ui.element('div').classes(
            'grid grid-cols-[repeat(7,1fr)_120px] gap-1 mb-1'
        ):
            for label in DOW_LABELS:
                ui.label(label).classes('text-xs font-semibold text-slate-500 px-2 py-1')
            ui.label('Week').classes('text-xs font-semibold text-slate-500 px-2 py-1')

        # Determine week-rows
        from datetime import timedelta
        first = date(view.jaar, view.maand, 1)
        # back to Monday
        grid_start = first - timedelta(days=first.isoweekday() - 1)
        # 6 weeks of 7 days
        for w in range(6):
            with ui.element('div').classes(
                'grid grid-cols-[repeat(7,1fr)_120px] gap-1'
            ):
                week_total_amt = 0.0
                week_dagen = 0
                for i in range(7):
                    d = grid_start + timedelta(days=w * 7 + i)
                    dag = next(
                        (x for x in view.dagen if x.datum == d), None,
                    )
                    is_other = d.month != view.maand
                    is_today = d == date.today()
                    is_selected = d == selected
                    is_weekend = d.isoweekday() >= 6

                    cell_classes = [
                        'border', 'border-slate-200', 'rounded',
                        'p-1', 'min-h-[80px]', 'cursor-pointer', 'flex',
                        'flex-col', 'gap-0.5',
                    ]
                    if is_other:
                        cell_classes.append('opacity-40')
                    if is_weekend:
                        cell_classes.append('bg-slate-50')
                    if is_today:
                        cell_classes.append('ring-1 ring-teal-500')
                    if is_selected:
                        cell_classes.append('ring-2 ring-teal-600 bg-teal-50')

                    if dag and dag.blocker:
                        kind = dag.blocker.kind
                        cell_classes.append(f'blocker-{kind}' if kind != 'holiday' else '')
                        if kind == 'holiday':
                            cell_classes.append('holiday-marker')

                    cell = ui.element('div').classes(' '.join(cell_classes))
                    cell.on('click', lambda _e=None, dt=d: on_day_click(dt))
                    with cell:
                        # Day number
                        ui.label(str(d.day)).classes('text-xs font-medium')

                        if dag and dag.blocker:
                            label = dag.blocker.label or dag.blocker.kind
                            cls = 'holiday-label' if dag.blocker.kind == 'holiday' else ''
                            ui.label(label).classes(f'text-[10px] {cls}')

                        # Werkdag pills (max 3)
                        if dag:
                            for w_pill in dag.werkdagen[:3]:
                                with ui.element('div').classes(
                                    f'wd-pill wd-{w_pill.category}'
                                ):
                                    ui.label(
                                        f'{w_pill.klant_naam[:8]} {w_pill.uren:.1f}'
                                    )
                            for e_pill in dag.expected[:3 - len(dag.werkdagen)]:
                                with ui.element('div').classes(
                                    f'wd-pill wd-{e_pill.category} expected'
                                ):
                                    ui.label(
                                        f'{e_pill.klant_naam[:8]} {e_pill.uren:.1f}'
                                    )
                            extra = len(dag.werkdagen) + len(dag.expected) - 3
                            if extra > 0:
                                ui.label(f'+{extra} meer').classes(
                                    'text-[9px] text-slate-500'
                                )

                            # Status-bar voor werkdagen
                            if dag.werkdagen:
                                with ui.element('div').classes('wd-status-bar'):
                                    for w_pill in dag.werkdagen:
                                        ui.element('span').classes(
                                            f'status-{w_pill.status_label}'
                                        )

                            for w_pill in dag.werkdagen:
                                week_total_amt += w_pill.bedrag
                            if dag.werkdagen:
                                week_dagen += 1

                # Week summary col
                with ui.element('div').classes(
                    'border border-slate-200 rounded p-2 flex flex-col '
                    'justify-center text-xs bg-slate-50'
                ):
                    week_num = grid_start.isocalendar()[1] + w  # rough
                    ui.label(f'W{(grid_start + timedelta(days=w * 7)).isocalendar()[1]}').classes(
                        'font-medium'
                    )
                    if week_total_amt > 0:
                        ui.label(f'€ {week_total_amt:,.0f}').classes('font-semibold')
                        ui.label(f'{week_dagen} dgn').classes('text-[10px] text-slate-500')
```

Then in the `render()` body, replace the placeholder:

```python
        # ...
        _render_month_grid(grid_container, view,
                            on_day_click=lambda d: select_day(d),
                            selected=state['selected'])
        # ...

    def select_day(d):
        state['selected'] = d
        if d.month != state['anchor'].month:
            state['anchor'] = date(d.year, d.month, 1)
        ui.timer(0, render, once=True)
```

- [ ] **Step 2: Run smoke tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_page.py -v
```

Expected: still PASS (smoke tests don't render).

- [ ] **Step 3: Manual rooktest**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
# Klik /agenda
# Verifieer: 6 weken × 7 dagen + week-summary kolom
# Verifieer: Werkdagen tonen klant-pills met categorie-kleur
# Verifieer: Klik op een dag → highlight selected (ring-2)
# Verifieer: Holiday-marker zichtbaar op koningsdag (27 april)
# Sluit app
```

- [ ] **Step 4: Commit**

```bash
git add pages/agenda.py
git commit -m "feat(agenda): MonthGrid met klant-pills + factuur-status-bars

7-col grid + week-summary kolom. Werkdag-categorie kleuren via wd-* CSS.
Status-bars per werkdag (ongefactureerd/concept/verstuurd/verlopen/betaald).
Holiday-marker + blocker overlays. Click → select day.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3.4: Day-Inspector met states

**Files:**
- Modify: `pages/agenda.py`

- [ ] **Step 1: Implement `_render_day_inspector`**

Add helper in `pages/agenda.py`:

```python
async def _render_day_inspector(container, dag, on_confirm_expected,
                                 on_delete_blocker, on_add_werkdag,
                                 on_open_factuur):
    """Render day-inspector card based on DagView state."""
    container.clear()
    with container:
        with ui.card().classes('w-full p-3'):
            ui.label(dag.datum.strftime('%A %d %B %Y')).classes(
                'text-base font-medium capitalize'
            )

            # Empty future / past
            if not dag.werkdagen and not dag.expected and not dag.blocker:
                if dag.datum >= date.today():
                    ui.label('Geen registratie').classes('text-slate-500 mt-2')
                    ui.button(
                        'Werkdag toevoegen', icon='add',
                        on_click=lambda: on_add_werkdag(dag.datum),
                    ).props('color=primary outline').classes('mt-2')
                else:
                    ui.label('Geen registratie op deze dag').classes(
                        'text-slate-500 mt-2'
                    )
                return

            # Blocker
            if dag.blocker:
                kind = dag.blocker.kind
                with ui.row().classes('items-center gap-2 mt-2'):
                    icon_name = {
                        'holiday': 'celebration',
                        'vacation': 'beach_access',
                        'sick': 'sick',
                        'training': 'school',
                    }.get(kind, 'event')
                    ui.icon(icon_name).classes('text-2xl')
                    with ui.column().classes('gap-0'):
                        ui.label(kind.capitalize()).classes('text-sm font-medium')
                        ui.label(dag.blocker.label or '').classes(
                            'text-xs text-slate-500'
                        )
                if kind != 'holiday':
                    ui.button(
                        'Verwijderen', icon='delete',
                        on_click=lambda: on_delete_blocker(dag.blocker.id),
                    ).props('flat color=negative dense').classes('mt-2')
                else:
                    ui.button(
                        'Werkdag plannen', icon='add',
                        on_click=lambda: on_add_werkdag(dag.datum),
                    ).props('flat color=primary dense').classes('mt-2')

            # Expected entries
            for e in dag.expected:
                with ui.card().classes('w-full p-2 mt-2 bg-slate-50'):
                    ui.label('Verwacht via vast rooster').classes(
                        'text-[10px] uppercase text-slate-400'
                    )
                    ui.label(e.klant_naam).classes('text-sm font-medium')
                    start_h = f'{e.start_minuten // 60:02d}:{e.start_minuten % 60:02d}'
                    end_h = f'{e.eind_minuten // 60:02d}:{e.eind_minuten % 60:02d}'
                    ui.label(f'{start_h}–{end_h} · {e.uren:.1f}u').classes(
                        'text-xs text-slate-600'
                    )
                    with ui.row().classes('gap-1 mt-1'):
                        ui.button(
                            'Bevestigen', icon='check',
                            on_click=lambda _e=None, ent=e: on_confirm_expected(ent),
                        ).props('color=primary dense').classes('text-xs')
                        ui.button(
                            'Aanpassen', icon='edit',
                            on_click=lambda _e=None, ent=e: on_add_werkdag(
                                dag.datum, prefill_pattern=ent,
                            ),
                        ).props('flat dense').classes('text-xs')

            # Confirmed werkdagen
            for w in dag.werkdagen:
                with ui.card().classes('w-full p-2 mt-2'):
                    ui.label(w.klant_naam).classes('text-sm font-medium')
                    ui.label(
                        f'{w.uren:.1f}u · € {w.bedrag:,.2f}'
                    ).classes('text-xs text-slate-600')
                    chip_color = {
                        'ongefactureerd': 'grey',
                        'concept': 'grey-7',
                        'verstuurd': 'blue',
                        'verlopen': 'red',
                        'betaald': 'green',
                    }.get(w.status_label, 'grey')
                    chip_label = {
                        'ongefactureerd': 'Ongefactureerd',
                        'concept': 'Concept',
                        'verstuurd': 'Verstuurd',
                        'verlopen': 'Verlopen',
                        'betaald': 'Betaald',
                    }.get(w.status_label, w.status_label)
                    with ui.row().classes('items-center gap-2 mt-1'):
                        ui.badge(chip_label, color=chip_color)
                        if w.factuurnummer:
                            ui.button(
                                w.factuurnummer, icon='receipt',
                                on_click=lambda _e=None, n=w.factuurnummer: on_open_factuur(n),
                            ).props('flat dense').classes('text-xs')

            # Footer "Maak factuur" knop
            ongefactureerd = [w for w in dag.werkdagen if not w.factuurnummer]
            if ongefactureerd:
                ui.button(
                    'Maak factuur', icon='receipt_long',
                    on_click=lambda: on_open_factuur(
                        '?nieuw=1&werkdagen=' + ','.join(str(w.id) for w in ongefactureerd)
                    ),
                ).props('color=primary outline').classes('w-full mt-2')
```

In `render()`, after grid render:

```python
        sel_dag = next(
            (d for d in view.dagen if d.datum == state['selected']), None,
        )
        if sel_dag is None:
            # selected outside displayed month — fetch via service
            sel_dag = await agenda_svc.get_dag(DB_PATH, state['selected'])

        await _render_day_inspector(
            inspector_container, sel_dag,
            on_confirm_expected=lambda e: handle_confirm(e),
            on_delete_blocker=lambda bid: handle_delete_blocker(bid),
            on_add_werkdag=lambda d, prefill_pattern=None:
                handle_open_werkdag_dialog(d, prefill_pattern),
            on_open_factuur=lambda n: ui.navigate.to(f'/facturen{n}' if n.startswith("?") else f'/facturen?factuurnummer={n}'),
        )

    async def handle_confirm(entry):
        try:
            await agenda_svc.confirm_expected(
                DB_PATH, pattern_id=entry.pattern_id, datum=state['selected'],
            )
            ui.notify('Werkdag bevestigd', type='positive')
            await render()
        except Exception as e:
            ui.notify(str(e), type='warning')

    async def handle_delete_blocker(bid):
        try:
            await agenda_svc.delete_blocker(DB_PATH, bid)
            ui.notify('Blocker verwijderd', type='positive')
            await render()
        except Exception as e:
            ui.notify(str(e), type='warning')

    async def handle_open_werkdag_dialog(d, prefill_pattern=None):
        from components.werkdag_form import open_werkdag_dialog
        prefill = {'datum': d.isoformat()}
        if prefill_pattern:
            prefill.update({
                'klant_id': prefill_pattern.klant_id,
                'start_minuten': prefill_pattern.start_minuten,
                'eind_minuten': prefill_pattern.eind_minuten,
                'activiteit': prefill_pattern.activiteit,
                'pattern_id': prefill_pattern.pattern_id,
            })
        await open_werkdag_dialog(on_save=render, prefill=prefill)
```

- [ ] **Step 2: Manual rooktest**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
# Klik /agenda
# Klik op een lege toekomstige dag → "Geen registratie" + Werkdag toevoegen
# Klik op een dag met werkdag → werkdag-card + status-chip
# Klik op een holiday → holiday-icoon + Werkdag plannen knop
# Sluit app (zonder werkdag-dialog te openen — dat komt in Sessie 4)
```

- [ ] **Step 3: Commit**

```bash
git add pages/agenda.py
git commit -m "feat(agenda): day-inspector met alle states

Empty/blocker/holiday/expected/confirmed states. Status-chips + factuur-link
per werkdag. Bevestigen-knop op expected entries (mismatch met werkdag_form
prefill komt in volgende task).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Sessie 4 — UI B: Werkdag-form prefill + Recurring-config + Bevestigen-flow (3-4u)

### Task 4.1: `werkdag_form` prefill kwarg

**Files:**
- Modify: `components/werkdag_form.py`
- Test: existing tests must remain green

- [ ] **Step 1: Modify `open_werkdag_dialog` signature**

In `components/werkdag_form.py`, change:

```python
async def open_werkdag_dialog(on_save=None, werkdag=None):
```

to:

```python
async def open_werkdag_dialog(on_save=None, werkdag=None, prefill: dict | None = None):
    """Open dialog for adding or editing a werkdag.

    Args:
        on_save: async callback after successful save.
        werkdag: existing Werkdag object for edit mode.
        prefill: dict with optional pre-fill values for new werkdag:
            datum: 'YYYY-MM-DD'
            klant_id: int
            start_minuten: int (informational — werkdag uses uren)
            eind_minuten: int
            activiteit: str
            pattern_id: int — if set, calls confirm_expected instead of add_werkdag
    """
```

In the dialog body, after `is_edit = werkdag is not None`, add:

```python
    pattern_id = (prefill or {}).get('pattern_id')
```

Replace existing `datum_input.value = ...` initialization with:

```python
    if prefill and prefill.get('datum'):
        datum_input.value = prefill['datum']
```

If `prefill` has klant/tijden, set them after dialog widgets are created:

```python
    if prefill and prefill.get('klant_id') and not is_edit:
        klant_select.value = prefill['klant_id']
        await _load_klant_data(prefill['klant_id'])
        if prefill.get('eind_minuten') and prefill.get('start_minuten'):
            uren = (prefill['eind_minuten'] - prefill['start_minuten']) / 60.0
            uren_input.value = uren
        if prefill.get('activiteit'):
            # find code matching activiteit
            for code, label in CODES.items():
                if label == prefill['activiteit']:
                    code_select.value = code
                    break
```

In `save()`, before calling `add_werkdag`:

```python
        if pattern_id and not is_edit:
            # Use confirm_expected route (idempotent)
            from services.agenda import confirm_expected
            try:
                await confirm_expected(
                    DB_PATH,
                    pattern_id=pattern_id,
                    datum=date.fromisoformat(datum_input.value),
                    start_minuten=prefill.get('start_minuten'),
                    eind_minuten=prefill.get('eind_minuten'),
                    activiteit=CODES.get(code_select.value or 'WERKDAG'),
                )
                ui.notify('Werkdag bevestigd', type='positive')
            except Exception as e:
                ui.notify(str(e), type='negative')
                return
            if on_save:
                await on_save()
            dialog.close()
            return
```

- [ ] **Step 2: Run all tests to ensure no regression**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: 1054+ tests still pass.

- [ ] **Step 3: Manual rooktest**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
# Klik op /agenda → klik op een verwachte dag → klik "Aanpassen" op expected
# Verifieer: werkdag-dialog opent met klant + datum prefilled
# Sluit dialog (Annuleren) — geen save
```

- [ ] **Step 4: Commit**

```bash
git add components/werkdag_form.py
git commit -m "feat(agenda): werkdag_form prefill kwarg + confirm_expected route

prefill={datum, klant_id, start_minuten, eind_minuten, activiteit, pattern_id}.
Bij pattern_id: roept confirm_expected (idempotent) ipv add_werkdag.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4.2: Recurring-config sectie in klant-dialog

**Files:**
- Modify: `components/shared_ui.py` (find `open_klant_dialog`)
- Test: manual + smoke

- [ ] **Step 1: Find existing klant-dialog**

```bash
grep -n "def open_klant_dialog\|async def open_klant_dialog" components/shared_ui.py
```

- [ ] **Step 2: Add "Vast rooster" sectie**

In `open_klant_dialog`, in edit mode (`is_edit = klant is not None`), after the existing alias-section, add:

```python
    if is_edit and klant:
        ui.separator()
        ui.label('Vast rooster').classes('text-base font-medium mt-2')
        ui.label(
            'Patroon voor verwachte werkdagen op /agenda. Geen fiscale data.'
        ).classes('text-xs text-slate-500')

        patterns_container = ui.column().classes('w-full gap-2 mt-2')

        async def refresh_patterns():
            from services.agenda import list_patterns_for_klant
            patterns = await list_patterns_for_klant(DB_PATH, klant.id)
            patterns_container.clear()
            with patterns_container:
                if not patterns:
                    ui.label('Nog geen vast rooster.').classes(
                        'text-xs text-slate-400'
                    )
                for p in patterns:
                    with ui.card().classes('w-full p-2 flex-row items-center gap-2'):
                        days_str = ' '.join(
                            ['Ma','Di','Wo','Do','Vr','Za','Zo'][w-1]
                            for w in p.weekdays
                        )
                        sh = f'{p.start_minuten//60:02d}:{p.start_minuten%60:02d}'
                        eh = f'{p.eind_minuten//60:02d}:{p.eind_minuten%60:02d}'
                        cat = ['dagpraktijk','anw','overig'][
                            ['dagpraktijk','anw','overig'].index(
                                'dagpraktijk' if p.code in ('WERKDAG','WEEKEND_DAG','')
                                else 'anw' if p.code.startswith('ANW_') or p.code in ('AVOND','NACHT')
                                else 'overig'
                            )
                        ]
                        ui.label(f'{days_str} · {sh}–{eh} · {p.code} ({cat})').classes(
                            'flex-1 text-sm'
                        )
                        ui.button(
                            icon='delete',
                            on_click=lambda _e=None, pid=p.id: handle_delete_pattern(pid),
                        ).props('flat round dense color=negative')

        async def handle_delete_pattern(pid):
            from services.agenda import delete_pattern
            await delete_pattern(DB_PATH, pid)
            ui.notify('Patroon verwijderd', type='positive')
            await refresh_patterns()

        async def handle_add_pattern():
            from services.agenda import add_pattern
            from components.werkdag_form import CODES
            with ui.dialog() as add_dlg, ui.card().classes('w-96 p-4'):
                ui.label('Nieuw rooster-patroon').classes('text-lg font-medium')
                # Weekdays checkboxes
                ui.label('Dagen').classes('text-sm font-medium mt-2')
                day_states = {}
                with ui.row().classes('gap-1'):
                    for i, lbl in enumerate(['Ma','Di','Wo','Do','Vr','Za','Zo'], start=1):
                        cb = ui.checkbox(lbl).classes('text-xs')
                        day_states[i] = cb
                # Tijden
                with ui.row().classes('gap-2 mt-2'):
                    start_in = ui.input('Start', value='08:00').props('dense')
                    end_in = ui.input('Eind', value='17:00').props('dense')
                # Code
                code_sel = ui.select(
                    options=list(CODES.keys()), value='WERKDAG', label='Code',
                ).classes('w-full mt-2')
                # Save
                async def do_save():
                    weekdays = [w for w, cb in day_states.items() if cb.value]
                    if not weekdays:
                        ui.notify('Selecteer minimaal 1 dag', type='warning')
                        return
                    try:
                        sh, sm = map(int, start_in.value.split(':'))
                        eh, em = map(int, end_in.value.split(':'))
                        start_min = sh * 60 + sm
                        eind_min = eh * 60 + em
                    except ValueError:
                        ui.notify('Ongeldige tijd (gebruik HH:MM)', type='warning')
                        return
                    try:
                        await add_pattern(
                            DB_PATH, klant_id=klant.id, weekdays=weekdays,
                            start_minuten=start_min, eind_minuten=eind_min,
                            code=code_sel.value,
                            activiteit=CODES.get(code_sel.value, 'Waarneming dagpraktijk'),
                        )
                        ui.notify('Patroon toegevoegd', type='positive')
                        add_dlg.close()
                        await refresh_patterns()
                    except Exception as e:
                        ui.notify(str(e), type='warning')
                with ui.row().classes('w-full justify-end gap-2 mt-3'):
                    ui.button('Annuleren', on_click=add_dlg.close).props('flat')
                    ui.button('Toevoegen', on_click=do_save).props('color=primary')
            add_dlg.open()

        ui.button(
            'Patroon toevoegen', icon='add', on_click=handle_add_pattern,
        ).props('outline').classes('mt-2')

        await refresh_patterns()
```

- [ ] **Step 3: Run regression tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: still all green.

- [ ] **Step 4: Manual rooktest**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
# Open /klanten → bewerk een klant → "Vast rooster" sectie zichtbaar
# Klik "Patroon toevoegen" → vul Ma+Wo, 08:00–17:00, code=WERKDAG → Toevoegen
# Verifieer: patroon in lijst zichtbaar
# Klik /agenda → maand met die klant → expected entries op Ma/Wo zichtbaar (in toekomst)
# Klik delete op patroon → patroon weg, verwachte entries verdwijnen
```

- [ ] **Step 5: Commit**

```bash
git add components/shared_ui.py
git commit -m "feat(agenda): recurring-pattern config in klant-dialog

Vast-rooster sectie (alleen edit-mode): list/add/delete patterns.
Add-dialoog met weekday-checkboxes, tijd-inputs, code-select.
Validatie via service-laag (ValidationError → toast).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4.3: "Maak factuur" deep-link verificatie

**Files:**
- Verify: `pages/facturen.py` ondersteunt `?nieuw=1&werkdagen=...`
- Modify if needed: `pages/facturen.py`

- [ ] **Step 1: Check existing query-param support**

```bash
grep -n "app.storage\|request.query_params\|query_params" pages/facturen.py | head -20
```

- [ ] **Step 2A: If already supports → smoke test**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
# Open /facturen?nieuw=1&werkdagen=1,2 (manuele URL)
# Verifieer: invoice-builder opent met werkdagen 1+2 voorgeselecteerd
```

- [ ] **Step 2B: If NOT supported → implement**

In `pages/facturen.py`, in the page handler:

```python
@ui.page('/facturen')
async def facturen_page(request: Request):
    qp = request.query_params
    auto_open_nieuw = qp.get('nieuw') == '1'
    werkdagen_param = qp.get('werkdagen', '')
    werkdag_ids = [int(x) for x in werkdagen_param.split(',') if x.strip().isdigit()]
    # ... existing rendering ...
    if auto_open_nieuw:
        await open_invoice_builder(prefill_werkdagen=werkdag_ids)
```

In `components/invoice_builder.py`, support `prefill_werkdagen` if not yet:

```python
async def open_invoice_builder(prefill_werkdagen: list[int] | None = None, ...):
    # ...
    if prefill_werkdagen:
        for wid in prefill_werkdagen:
            # add to selection
```

- [ ] **Step 3: Run /agenda → "Maak factuur" rooktest**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
# /agenda → klik op een dag met ongefactureerde werkdag → "Maak factuur" knop
# Verifieer: navigeert naar /facturen, invoice-builder opent met die werkdag
```

- [ ] **Step 4: Commit**

```bash
git add pages/facturen.py components/invoice_builder.py
git commit -m "feat(agenda): /facturen?nieuw=1&werkdagen=ids deep-link

Voor 'Maak factuur' knop in /agenda day-inspector.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4.4: User-blocker toevoegen via day-inspector

**Files:**
- Modify: `pages/agenda.py` (extend day-inspector for empty future-day → also offer "Vakantie/Ziek/Nascholing" buttons)

- [ ] **Step 1: Add blocker-add buttons to inspector**

In `_render_day_inspector` in `pages/agenda.py`, in the empty-future branch:

```python
if dag.datum >= date.today():
    ui.label('Geen registratie').classes('text-slate-500 mt-2')
    with ui.row().classes('gap-2 mt-2'):
        ui.button(
            'Werkdag', icon='add',
            on_click=lambda: on_add_werkdag(dag.datum),
        ).props('color=primary outline dense')
        ui.button(
            'Vakantie', icon='beach_access',
            on_click=lambda: on_add_blocker(dag.datum, 'vacation'),
        ).props('outline dense')
        ui.button(
            'Ziek', icon='sick',
            on_click=lambda: on_add_blocker(dag.datum, 'sick'),
        ).props('outline dense')
        ui.button(
            'Nascholing', icon='school',
            on_click=lambda: on_add_blocker(dag.datum, 'training'),
        ).props('outline dense')
    return
```

In `render()`, add `on_add_blocker` handler:

```python
    async def handle_add_blocker(d, kind):
        try:
            await agenda_svc.add_blocker(DB_PATH, datum=d, kind=kind, label=kind.capitalize())
            ui.notify('Blocker toegevoegd', type='positive')
            await render()
        except Exception as e:
            ui.notify(str(e), type='warning')
```

Pass it to inspector:

```python
        await _render_day_inspector(
            inspector_container, sel_dag,
            on_confirm_expected=...,
            on_delete_blocker=...,
            on_add_werkdag=...,
            on_add_blocker=handle_add_blocker,  # NEW
            on_open_factuur=...,
        )
```

Add `on_add_blocker` parameter to `_render_day_inspector` signature.

- [ ] **Step 2: Manual rooktest**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
# /agenda → toekomstige lege dag → klik Vakantie → blocker zichtbaar in cel
# Klik op die dag → inspector toont blocker met Verwijderen-knop
# Verwijder → blocker weg
```

- [ ] **Step 3: Commit**

```bash
git add pages/agenda.py
git commit -m "feat(agenda): blocker quick-add buttons in day-inspector

Vakantie/Ziek/Nascholing knoppen op lege toekomstige dagen.
ConflictError op werkdag-conflict → user-friendly toast.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Sessie 5 — Validatie + End-to-End Rooktest (2-3u)

### Task 5.1: End-to-end factuur-status koppeling rooktest

**Files:**
- Create: `docs/superpowers/runbooks/agenda-factuur-koppeling-test.md`

- [ ] **Step 1: Schrijf runbook**

```markdown
# /agenda Factuur-koppeling End-to-End Rooktest

## Doel
Verifieer dat de factuur-status van een werkdag direct in /agenda zichtbaar is
bij elke fase van de factuur-lifecycle.

## Setup

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
```

## Stap 1: Maak een verwachte werkdag → ongefactureerd

1. Open /klanten → bewerk klant 'HAP X' → voeg patroon toe (Ma, 08:00-17:00, WERKDAG)
2. Open /agenda → navigeer naar een toekomstige maandag
3. Verifieer: cell toont een dashed pill (verwacht)
4. Klik op de dag → inspector toont expected entry
5. Klik "Bevestigen"
6. Verifieer in /agenda cell:
   - Pill is nu vol (niet dashed)
   - Status-bar onderaan = grijs (`status-ongefactureerd`)
7. Verifieer in inspector:
   - Werkdag-card met status-chip "Ongefactureerd" (grijs)
   - "Maak factuur" knop zichtbaar in footer

## Stap 2: Maak een concept-factuur → cell wordt grijs-blauw

1. Klik "Maak factuur" → opens /facturen invoice-builder
2. Bewaar als concept (zonder verzenden)
3. Terug naar /agenda
4. Verifieer in cell:
   - Status-bar = `status-concept` (grijs-blauw, dimmed)
5. Verifieer in inspector:
   - Status-chip "Concept"
   - Factuurnummer-link zichtbaar
   - "Maak factuur" knop verdwenen

## Stap 3: Markeer factuur als verstuurd → cell wordt blauw

1. Open /facturen → markeer factuur als verstuurd
2. Terug naar /agenda
3. Verifieer in cell: status-bar = `status-verstuurd` (blauw)
4. Verifieer in inspector: status-chip "Verstuurd"

## Stap 4: Vervaldatum verstrijkt → cell wordt rood

1. SQLite: zet vervaldatum op gisteren:
   ```bash
   sqlite3 .../db.sqlite3 "UPDATE facturen SET vervaldatum = '$(date -v-1d +%Y-%m-%d)' WHERE nummer = 'XXXX'"
   ```
2. Klik Refresh in /agenda topbar
3. Verifieer in cell: status-bar = `status-verlopen` (rood)
4. Verifieer in inspector: status-chip "Verlopen"

## Stap 5: Markeer als betaald → cell wordt groen

1. /facturen → markeer als betaald
2. Terug naar /agenda
3. Verifieer in cell: status-bar = `status-betaald` (groen)
4. Verifieer in inspector: status-chip "Betaald"

## Result-log

| Stap | Verwachte UI | OK |
|---|---|---|
| 1. Bevestigd, ongefactureerd | grijze status-bar | _ |
| 2. Concept | grijs-blauw status-bar | _ |
| 3. Verstuurd | blauw status-bar | _ |
| 4. Verlopen (vervaldatum < today) | rood status-bar | _ |
| 5. Betaald | groen status-bar | _ |
```

- [ ] **Step 2: Voer runbook uit + vul log in**

- [ ] **Step 3: Commit runbook + completed log**

```bash
git add docs/superpowers/runbooks/agenda-factuur-koppeling-test.md
git commit -m "docs(agenda): factuur-koppeling end-to-end rooktest runbook"
```

---

### Task 5.2: Alle tests groen + final smoke

**Files:**
- None (validation only)

- [ ] **Step 1: Run full test suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v 2>&1 | tee /tmp/test-output.log | tail -30
```

Expected: all green, ~1100 cases.

- [ ] **Step 2: Run native-mode rooktest checklist**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
```

Checklist:
- [ ] /agenda zichtbaar in sidebar tussen Dashboard en Werkdagen
- [ ] /agenda laadt zonder console errors
- [ ] Maand-navigatie (prev/today/next) werkt
- [ ] Klik op dag → inspector update
- [ ] Verwachte werkdag → bevestigen → werkdag verschijnt
- [ ] Bevestigen 2x → idempotent (geen duplicate)
- [ ] User-blocker toevoegen → cell update direct
- [ ] User-blocker verwijderen → cell update direct
- [ ] Holiday (27 april) toont label, geen expected entries
- [ ] Factuur-status-bar reflecteert actuele factuur-status
- [ ] /facturen → status wijzigen → terug naar /agenda → ververs → status update
- [ ] /klanten → patroon toevoegen → /agenda → expected zichtbaar
- [ ] /klanten → patroon verwijderen → /agenda → expected weg
- [ ] Bestaande pagina's (Dashboard, Werkdagen, Facturen, Transacties, Aangifte, Jaarafsluiting) ongewijzigd werkend

- [ ] **Step 3: Commit final state**

```bash
git status
# als er onverwachte wijzigingen zijn → onderzoeken
# anders:
git tag agenda-sprint-a-complete
git commit --allow-empty -m "chore(agenda): Sprint A complete

Alle 5 sessies afgerond:
- Sessie 1: datamodel + holidays
- Sessie 2: services laag (pattern + blocker + confirm + view)
- Sessie 3: UI maandgrid + day-inspector + sidebar
- Sessie 4: werkdag_form prefill + recurring-config + maak-factuur deep-link
- Sessie 5: end-to-end rooktest

Test count: 1054+ → ~1104. Native rooktest checklist groen.
Klaar voor Sprint B (visuele refresh) of pauze voor user-feedback.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Checklist (uitgevoerd door planner)

- [x] **Spec coverage**: alle in-scope items uit spec hebben een task. Foundation (paths/errors) bewust geschrapt per gebruiker-feedback.
- [x] **Placeholder scan**: geen TBD/TODO/"implement later" in plan-stappen. Code-blokken volledig.
- [x] **Type consistency**: `Pattern.weekdays: list[int]` consistent in service en tests. `WerkdagPill` velden consistent in `get_maand` output en inspector-rendering. `CODES` dict gebruikt vanuit `werkdag_form.py` (existing source of truth).
- [x] **Migrations idempotent**: alle migraties gebruiken `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`.
- [x] **Year-lock dekking**: confirm_expected (via add_werkdag), add_blocker, delete_blocker getest. Patterns niet year-locked (bewust, getest).
- [x] **Backcompat**: ConflictError + ValidationError zijn ValueError-subclasses. Bestaande catch-sites blijven werken.
- [x] **Sessie-grenzen**: elke sessie eindigt met groene tests + commit. Stoppunt na elke sessie mogelijk.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-02-agenda-sprint-a.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Ik dispatch een fresh subagent per task, review tussen tasks, snelle iteratie. Past goed bij 26 taken want context blijft schoon en jij kan tussendoor reviewen.

**2. Inline Execution** — Tasks in deze sessie, batch execution met checkpoints. Snel maar context groeit.

Welke aanpak?
