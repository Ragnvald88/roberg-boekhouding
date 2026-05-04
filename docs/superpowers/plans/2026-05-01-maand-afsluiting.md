# Maandafsluiting + bank-import-status — Implementation Plan

> **🅿️ PARKED** — niet uitgevoerd. Sprint A→F + post-audits hebben
> voorrang gekregen. Plan blijft staan als reference voor toekomstig
> werk (geen `feature/maand-afsluiting` branch meer in repo).

*Plan-datum: 2026-05-01 • Branch: `feature/maand-afsluiting` (parked)*
*Author: Claude (Opus 4.7) + Codex CLI (2 review-rondes) consensus*

> **⚠️ STALE PLAN — bijwerken vóór uitvoering.** Sprint A heeft sinds dit plan
> **migratie 35 + 36** in beslag genomen (`klant_recurring_patterns` + `blockers`,
> gemerged 2026-05-03 via `d70dbb3`). Dit plan claimt nog migratie **35** voor
> `maand_afsluitingen` — vóór uitvoering opnieuw nummeren naar **migratie 37**.
> Test-baselines in dit document (`~1054`, `~1086`) zijn pre-Sprint-A. Werkelijke
> baseline op master is nu **1261**; nieuwe-test-counts moeten daarboven worden
> toegevoegd, niet vanaf 1054. Verifieer ook dat geen referenties naar
> `maand_afsluitingen` botsen met de nieuwe agenda-tabellen vóór schema-werk.

> **Voor de uitvoerder:** dit plan implementeert één afgebakende feature met TDD per task. Stappen gebruiken `- [ ]`-checkboxes. Elke task eindigt met een commit en een groene module-test-run. Volledige suite draait alleen op Task 10. Codex-review (`codex-review` skill) draait éénmaal aan het einde, niet na elk commit.

**Goal.** Geef de gebruiker per kalendermaand een sluitende status-pagina die data-issues (ongecategoriseerde bank-rijen, ongefactureerde werkdagen, verlopen facturen, ontbrekende bonnen) per maand toont, en laat hem een maand markeren als "afgesloten". Bij CSV-import die data bevat in een afgesloten maand toont de app een waarschuwing.

**Scope-disclaimer.** "Afgesloten" is in v1 een **status-sticker** plus **CSV-import-waarschuwing**, niet een mutation-block. Hard-lock blijft op jaar-niveau via bestaande `assert_year_writable`. Cross-cutting mutation-warnings voor andere paden (categorize-bank-tx, edit-factuur, etc.) zijn expliciet v2-werk.

**Architecture.** Eén nieuwe SQLite-tabel `maand_afsluitingen (jaar, maand, status, closed_at, updated_at)` met PK `(jaar, maand)`. Eén nieuwe pagina `/maand-afsluiting` met een 12-cards grid per gekozen jaar, sequentieel gerenderd in één DB-connectie. Pure helper `compute_maand_checklist_issues(conn, jaar, maand) → list[(severity, message, link)]` (zelfde tuple-vorm als bestaande jaarafsluiting-checklist) gebruikt de gecentraliseerde `FACTUREERBARE_WERKDAG_FILTER` constant. Een eerlijke bank-import-status `get_bank_import_status(db, jaar, maand)` met expliciet beperkte uitspraken (geen "compleet"-claim — alleen "data t/m datum X" of "geen data"). Health-alert `month_close_overdue` flagt maanden met activiteit > 60 dagen oud zonder afsluit-stempel; activiteit-bronnen via `UNION` over werkdagen + banktransacties + uitgaven.

**Tech stack.** Python 3.12, aiosqlite (3.32+ vereist voor CTE-VALUES — bevestigd 3.53 in `.venv`), NiceGUI 3 native, raw SQL met `?` placeholders, pytest + pytest-asyncio. Geen nieuwe runtime-dependencies.

---

## Architectuur-keuzes (lees eerst)

**1. Aparte pagina i.p.v. tab op `/jaarafsluiting`.** Maand-afsluiting is operationeel-routine (12×/jaar); jaarafsluiting is fiscaal-rituaal (1×/jaar). Verschillende gebruiksritmes; jaarafsluiting heeft al 5 tabs. Aparte route maakt deeplinks vanuit health-alerts mogelijk.

**2. Géén hard-lock per maand.** Een maand kan een half jaar later corrigeerbaar moeten zijn (terugvinden bonnetje). Hard-lock zou vragen om "heropenen"-flow voor elke kleine correctie — frictie. We kiezen voor **status-sticker**: `closed_at`-stempel zichtbaar in UI, gebruiker kan toch wijzigen. Enige actieve gedrag van de status: CSV-import toont waarschuwing als upload-data een afgesloten maand raakt.

**3. Eerlijke bank-import-status, geen "dekking".** Met alleen `csv_bestand`-naam in `banktransacties` is volledigheid niet bewijsbaar (een losse maart-tx + april-import bewijst niet dat 1-24 maart geïmporteerd is). UI-taal beperkt zich tot **"Bankdata t/m DD-MM-YYYY"** of **"Geen bankdata voor deze maand"**. Echte gap-detectie of import-batch-metadata is v2.

**4. Activiteit-detectie voor health-alert telt 3 bronnen.** Werkdagen + banktransacties + uitgaven met datum in de maand — minimaal één hit = "actief". Alleen werkdagen telt zou maanden zonder waarnemingen maar met bonnetjes-uitgaven over het hoofd zien.

**5. Migratie 35 schema-keuzes.** PK `(jaar, maand)`. Geen index — `WHERE jaar = ?` gebruikt PK-prefix. Velden: `status` (CHECK 'open'|'afgesloten'), `closed_at` (ISO-stamp bij afsluiten, leeg bij heropenen), `updated_at` (laatste write — voor toekomstige audit-views). Geen `notes` in v1.

**6. `FACTUREERBARE_WERKDAG_FILTER` hergebruik.** Constant gedefinieerd in `database.py:374`. De maand-checklist gebruikt hem voor consistentie met `get_werkdagen_ongefactureerd_summary` en jaarafsluiting-pre-flight. Alternatief was de filter dupliceren — slechte stijl per CLAUDE.md "gecentraliseerde predicate"-regel.

**7. `_today_iso()` monkeypatch-veilig.** `components/maand_afsluiting.py` doet `import database as _db` en roept `_db._today_iso()` aan. Een direct `from database import _today_iso` zou de lokale referentie aan import-tijd binden, waardoor `monkeypatch.setattr(database, '_today_iso', ...)` in tests niet door zou werken.

**8. Sequentiële render: één hoofd-connectie + 12 korte status-queries.** `pages/maand_afsluiting.py:render_grid` opent één `get_db_ctx` voor de checklist-passes (gedeelde `conn`-arg aan `compute_maand_checklist_issues`), en roept daarnaast `get_bank_import_status` 12× sequentieel aan — die helper opent zijn eigen korte connectie per call. Geen `asyncio.gather`: voor lokaal single-user SQLite levert parallel-IO geen merkbare winst en maakt de control-flow rommelig. Een toekomstige `get_bank_import_status_for_year(jaar) -> dict[int, dict]` bulk-helper kan dit naar 1 + 1 = 2 connecties terugbrengen, maar dat is v2.

---

## File Structure

| Pad | Verantwoordelijkheid | Mode |
|---|---|---|
| `database.py` | Migratie 35 (na entry 34); helpers `get_maand_afsluitingen`, `update_maand_afsluiting_status`, `get_bank_import_status`, `detect_csv_overlap_with_closed_months`; uitbreiding van `get_health_alerts` met `month_close_overdue`. | modify |
| `components/maand_afsluiting.py` | Pure functies: `compute_maand_checklist_issues(conn, jaar, maand)`, `format_bank_status_label(status_dict, jaar, maand)`, gedeelde constante `MAAND_NAMEN`. | create |
| `pages/maand_afsluiting.py` | NiceGUI-pagina `/maand-afsluiting`: jaar-selector, 12-maands-grid, expandable detail per maand, afsluit/heropen-knop. | create |
| `main.py` | Eén regel: `import pages.maand_afsluiting` zodat `@ui.page` route-binding gebeurt. | modify |
| `components/layout.py` | Eén regel toegevoegd in `NAV_GROUPS`: derde groep krijgt vierde item naast Documenten, Jaarafsluiting, Aangifte. | modify |
| `pages/transacties.py` | CSV-upload-handler roept `detect_csv_overlap_with_closed_months` aan na parse, vóór insert; toont `ui.notify` als overlap. Importeert `MAAND_NAMEN` uit `components.maand_afsluiting`. | modify |
| `tests/test_maand_afsluiting.py` | Migratie + helpers + checklist + bank-status + CSV-overlap + edge-cases. | create |
| `tests/test_health_alerts.py` | Vier nieuwe tests voor `month_close_overdue` (drempel + UNION-bronnen + skip-afgesloten + jaargrens). | modify |
| `CLAUDE.md` | Korte sectie over `maand_afsluitingen` onder Database. | modify |

Niet betrokken: `fiscal/`, `import_/`, `templates/`, andere pages.

---

## Task 0: Bootstrap

**Files:** —

- [ ] **Step 1.** Maak feature-branch.
```bash
cd /Users/macbookpro_ronald/Library/CloudStorage/SynologyDrive-Main/06_Development/1_roberg-boekhouding
git checkout -b feature/maand-afsluiting
```

- [ ] **Step 2.** Verifieer baseline.
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```
Verwacht: ~1054 passed (noteer exacte count voor latere vergelijking).

---

## Task 1: Migratie 35 — `maand_afsluitingen` tabel

**Files:**
- Modify: `database.py` (de `MIGRATIONS` lijst, vóór de afsluitende `]`)
- Test: `tests/test_maand_afsluiting.py` (nieuw)

- [ ] **Step 1.** Schrijf falende tests in `tests/test_maand_afsluiting.py`:

```python
"""Tests voor maand-afsluiting workflow (Plan 2026-05-01)."""

import aiosqlite
import pytest
from database import get_db_ctx


@pytest.mark.asyncio
async def test_migration_35_creates_maand_afsluitingen_table(db):
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='maand_afsluitingen'")
        row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_migration_35_pk_is_jaar_maand(db):
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("PRAGMA table_info(maand_afsluitingen)")
        cols = {r['name']: r for r in await cur.fetchall()}
    assert cols['jaar']['pk'] >= 1
    assert cols['maand']['pk'] >= 1
    assert cols['status']['dflt_value'] == "'open'"
    assert 'updated_at' in cols
    assert 'notes' not in cols  # YAGNI: geen UI in v1


@pytest.mark.asyncio
async def test_migration_35_status_check_constraint(db):
    async with aiosqlite.connect(db) as conn:
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO maand_afsluitingen "
                "(jaar, maand, status) VALUES (2026, 3, 'invalid')")
            await conn.commit()


@pytest.mark.asyncio
async def test_migration_35_maand_range_check(db):
    async with aiosqlite.connect(db) as conn:
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO maand_afsluitingen (jaar, maand) "
                "VALUES (2026, 0)")
            await conn.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO maand_afsluitingen (jaar, maand) "
                "VALUES (2026, 13)")
            await conn.commit()
```

- [ ] **Step 2.** Run, bevestig falen.
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest \
  tests/test_maand_afsluiting.py -v
```
Verwacht: 4 failures.

- [ ] **Step 3.** In `database.py`: zoek `(34, "seed_klant_aliases_from_local_if_present", None),` en voeg DAARNA toe (vóór de `]`-regel die `MIGRATIONS` afsluit):

```python
    (35, "add_maand_afsluitingen_table", [
        # Soft-lock per kalendermaand (Plan 2026-05-01).
        # PK (jaar, maand) volstaat voor (jaar=?) prefix-lookups.
        # updated_at houdt laatste-write bij; closed_at is leeg bij 'open'.
        """CREATE TABLE IF NOT EXISTS maand_afsluitingen (
            jaar INTEGER NOT NULL,
            maand INTEGER NOT NULL CHECK (maand BETWEEN 1 AND 12),
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'afgesloten')),
            closed_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (jaar, maand)
        )""",
    ]),
```

- [ ] **Step 4.** Run, bevestig groen.
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest \
  tests/test_maand_afsluiting.py -v
```
Verwacht: 4 passed.

- [ ] **Step 5.** Commit.
```bash
git add database.py tests/test_maand_afsluiting.py
git commit -m "feat(maand): migratie 35 — maand_afsluitingen tabel"
```

---

## Task 2: Helpers `get_maand_afsluitingen` + `update_maand_afsluiting_status`

**Files:**
- Modify: `database.py`
- Modify: `tests/test_maand_afsluiting.py`

- [ ] **Step 1.** Voeg toe aan `tests/test_maand_afsluiting.py`:

```python
from database import (
    get_maand_afsluitingen, update_maand_afsluiting_status,
)


@pytest.mark.asyncio
async def test_get_maand_afsluitingen_empty_year_returns_12_open(db):
    rows = await get_maand_afsluitingen(db, 2026)
    assert len(rows) == 12
    assert [r['maand'] for r in rows] == list(range(1, 13))
    assert all(r['status'] == 'open' for r in rows)
    assert all(r['closed_at'] == '' for r in rows)


@pytest.mark.asyncio
async def test_update_creates_row_with_closed_at(db):
    await update_maand_afsluiting_status(db, 2026, 3, 'afgesloten')
    rows = await get_maand_afsluitingen(db, 2026)
    maart = next(r for r in rows if r['maand'] == 3)
    assert maart['status'] == 'afgesloten'
    assert maart['closed_at']
    assert maart['updated_at']


@pytest.mark.asyncio
async def test_update_reopen_clears_closed_at(db):
    await update_maand_afsluiting_status(db, 2026, 3, 'afgesloten')
    await update_maand_afsluiting_status(db, 2026, 3, 'open')
    rows = await get_maand_afsluitingen(db, 2026)
    maart = next(r for r in rows if r['maand'] == 3)
    assert maart['status'] == 'open'
    assert maart['closed_at'] == ''
    assert maart['updated_at']  # blijft gevuld na heropen


@pytest.mark.asyncio
async def test_update_rejects_invalid_status(db):
    with pytest.raises(ValueError, match='status'):
        await update_maand_afsluiting_status(db, 2026, 3, 'klaar')


@pytest.mark.asyncio
async def test_update_rejects_invalid_maand(db):
    with pytest.raises(ValueError, match='maand'):
        await update_maand_afsluiting_status(db, 2026, 13, 'open')
    with pytest.raises(ValueError, match='maand'):
        await update_maand_afsluiting_status(db, 2026, 0, 'open')


@pytest.mark.asyncio
async def test_update_dec_no_off_by_one(db):
    """December (maand=12) moet werken — geen overflow naar maand 13."""
    await update_maand_afsluiting_status(db, 2026, 12, 'afgesloten')
    rows = await get_maand_afsluitingen(db, 2026)
    dec = next(r for r in rows if r['maand'] == 12)
    assert dec['status'] == 'afgesloten'
```

- [ ] **Step 2.** Run, bevestig falen (`ImportError`).

- [ ] **Step 3.** Implementeer in `database.py`. Zoek met `grep -n "async def update_jaarafsluiting_status" database.py`. Plaats DIRECT NA de bestaande `update_jaarafsluiting_status`-functie:

```python
# === Maandafsluiting helpers (Plan 2026-05-01) ===
#
# v1 scope: status-sticker per kalendermaand + CSV-import-waarschuwing.
# Geen YearLockedError-stijl mutation-block (zie Plan §3 scope).
# Hard-lock blijft uitsluitend op jaar-niveau via assert_year_writable.

async def get_maand_afsluitingen(
    db_path: Path = DB_PATH, jaar: int = 0,
) -> list[dict]:
    """Geef 12 rijen voor het gegeven jaar — defaults invullen voor maanden zonder rij."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT jaar, maand, status, closed_at, updated_at "
            "FROM maand_afsluitingen WHERE jaar = ?",
            (jaar,))
        stored = {r['maand']: dict(r) for r in await cur.fetchall()}
    return [
        stored.get(m, {
            'jaar': jaar, 'maand': m, 'status': 'open',
            'closed_at': '', 'updated_at': '',
        })
        for m in range(1, 13)
    ]


async def update_maand_afsluiting_status(
    db_path: Path = DB_PATH, jaar: int = 0, maand: int = 0,
    status: str = 'open',
) -> None:
    """UPSERT status voor (jaar, maand). 'afgesloten' stempelt closed_at, 'open' wist hem."""
    if status not in ('open', 'afgesloten'):
        raise ValueError(
            f"status moet 'open' of 'afgesloten' zijn, niet {status!r}")
    if not (1 <= maand <= 12):
        raise ValueError(f"maand moet 1..12 zijn, niet {maand}")
    from datetime import datetime
    now_iso = datetime.now().isoformat(timespec='seconds')
    closed_at = now_iso if status == 'afgesloten' else ''
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "INSERT INTO maand_afsluitingen "
            "(jaar, maand, status, closed_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(jaar, maand) DO UPDATE SET "
            "status = excluded.status, "
            "closed_at = excluded.closed_at, "
            "updated_at = excluded.updated_at",
            (jaar, maand, status, closed_at, now_iso))
        await conn.commit()
```

- [ ] **Step 4.** Run, bevestig groen.
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest \
  tests/test_maand_afsluiting.py -v
```
Verwacht: 10 passed (4 + 6 nieuw).

- [ ] **Step 5.** Commit.
```bash
git add database.py tests/test_maand_afsluiting.py
git commit -m "feat(maand): get/update_maand_afsluiting_status helpers"
```

---

## Task 3: `get_bank_import_status`

**Files:**
- Modify: `database.py`
- Modify: `tests/test_maand_afsluiting.py`

**Naamgeving expliciet.** Niet "dekking" — we doen geen volledigheids-bewering, alleen "data t/m DD-MM" of "geen data".

- [ ] **Step 1.** Voeg toe aan tests:

```python
from database import get_bank_import_status, add_banktransacties


@pytest.mark.asyncio
async def test_bank_status_no_data_returns_empty(db):
    s = await get_bank_import_status(db, 2026, 3)
    assert s['has_data'] is False
    assert s['n_in_maand'] == 0
    assert s['last_tx_date'] == ''
    assert s['has_post_maand_data'] is False


@pytest.mark.asyncio
async def test_bank_status_in_maand_only(db):
    await add_banktransacties(db, [
        {'datum': '2026-03-05', 'bedrag': -10.0, 'tegenpartij': 'A'},
        {'datum': '2026-03-25', 'bedrag': -10.0, 'tegenpartij': 'B'},
    ])
    s = await get_bank_import_status(db, 2026, 3)
    assert s['has_data'] is True
    assert s['n_in_maand'] == 2
    assert s['last_tx_date'] == '2026-03-25'
    assert s['has_post_maand_data'] is False


@pytest.mark.asyncio
async def test_bank_status_with_post_maand(db):
    await add_banktransacties(db, [
        {'datum': '2026-03-05', 'bedrag': -10.0, 'tegenpartij': 'A'},
        {'datum': '2026-04-02', 'bedrag': -10.0, 'tegenpartij': 'B'},
    ])
    s = await get_bank_import_status(db, 2026, 3)
    assert s['has_data'] is True
    assert s['has_post_maand_data'] is True


@pytest.mark.asyncio
async def test_bank_status_only_post_no_in_maand(db):
    """Alleen tx ná de maand — has_data blijft False."""
    await add_banktransacties(db, [
        {'datum': '2026-04-15', 'bedrag': -10.0, 'tegenpartij': 'A'},
    ])
    s = await get_bank_import_status(db, 2026, 3)
    assert s['has_data'] is False
    assert s['has_post_maand_data'] is True


@pytest.mark.asyncio
async def test_bank_status_december_year_rollover(db):
    """December → next_maand_start moet jaar+1 zijn."""
    await add_banktransacties(db, [
        {'datum': '2026-12-15', 'bedrag': -10.0, 'tegenpartij': 'A'},
        {'datum': '2027-01-04', 'bedrag': -10.0, 'tegenpartij': 'B'},
    ])
    s = await get_bank_import_status(db, 2026, 12)
    assert s['has_data'] is True
    assert s['has_post_maand_data'] is True


@pytest.mark.asyncio
async def test_bank_status_invalid_maand(db):
    with pytest.raises(ValueError):
        await get_bank_import_status(db, 2026, 0)
    with pytest.raises(ValueError):
        await get_bank_import_status(db, 2026, 13)
```

- [ ] **Step 2.** Run, bevestig falen.

- [ ] **Step 3.** Implementeer in `database.py`, direct na `update_maand_afsluiting_status`:

```python
def _maand_range(jaar: int, maand: int) -> tuple[str, str]:
    """ISO-strings (start_inclusive, next_start_exclusive) voor (jaar, maand)."""
    if not (1 <= maand <= 12):
        raise ValueError(f"maand moet 1..12 zijn, niet {maand}")
    start = f'{jaar}-{maand:02d}-01'
    if maand == 12:
        return start, f'{jaar + 1}-01-01'
    return start, f'{jaar}-{maand + 1:02d}-01'


async def get_bank_import_status(
    db_path: Path = DB_PATH, jaar: int = 0, maand: int = 0,
) -> dict:
    """Eerlijke import-status — geen volledigheids-claim.

    Returns dict met:
      has_data: bool — minstens 1 banktx IN de maand
      n_in_maand: int — aantal tx in de maand
      last_tx_date: str — MAX(datum) van tx in de maand, '' als geen
      has_post_maand_data: bool — minstens 1 tx ná maand-einde
        (aanwijzing dat gebruiker over maand-grens importeerde, GEEN
        bewijs van volledigheid binnen de maand zelf)
    """
    start, nxt = _maand_range(jaar, maand)
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) AS n, MAX(datum) AS last_in "
            "FROM banktransacties WHERE datum >= ? AND datum < ?",
            (start, nxt))
        in_row = await cur.fetchone()
        cur = await conn.execute(
            "SELECT COUNT(*) AS n FROM banktransacties WHERE datum >= ?",
            (nxt,))
        post_row = await cur.fetchone()
    return {
        'has_data': (in_row['n'] or 0) > 0,
        'n_in_maand': in_row['n'] or 0,
        'last_tx_date': in_row['last_in'] or '',
        'has_post_maand_data': (post_row['n'] or 0) > 0,
    }
```

- [ ] **Step 4.** Run, bevestig groen (16 passed totaal).

- [ ] **Step 5.** Commit.
```bash
git add database.py tests/test_maand_afsluiting.py
git commit -m "feat(maand): get_bank_import_status (eerlijke signalen, geen completeness-claim)"
```

---

## Task 4: `compute_maand_checklist_issues` + `format_bank_status_label`

**Files:**
- Create: `components/maand_afsluiting.py`
- Modify: `tests/test_maand_afsluiting.py`

- [ ] **Step 1.** Voeg toe aan tests:

```python
from components.maand_afsluiting import (
    compute_maand_checklist_issues, format_bank_status_label,
    MAAND_NAMEN,
)
from database import (
    add_klant, add_werkdag,
    get_banktransacties, mark_banktx_genegeerd,
    update_banktransactie,
)


@pytest.mark.asyncio
async def test_checklist_clean_month_returns_empty(db):
    async with get_db_ctx(db) as conn:
        issues = await compute_maand_checklist_issues(conn, 2026, 3)
    assert issues == []


@pytest.mark.asyncio
async def test_checklist_uncategorized_bank_warning(db):
    await add_banktransacties(db, [
        {'datum': '2026-03-15', 'bedrag': -50.0, 'tegenpartij': 'AH'},
    ])
    async with get_db_ctx(db) as conn:
        issues = await compute_maand_checklist_issues(conn, 2026, 3)
    msgs = [m for _, m, _ in issues]
    assert any('niet gecategoriseerd' in m for m in msgs)


@pytest.mark.asyncio
async def test_checklist_genegeerde_bank_telt_niet(db):
    """genegeerd=1 mag niet als ongecategoriseerd tellen."""
    await add_banktransacties(db, [
        {'datum': '2026-03-15', 'bedrag': -50.0, 'tegenpartij': 'AH'},
    ])
    txs = await get_banktransacties(db, jaar=2026)
    await mark_banktx_genegeerd(db, txs[0].id, 1)
    async with get_db_ctx(db) as conn:
        issues = await compute_maand_checklist_issues(conn, 2026, 3)
    assert not any('gecategoriseerd' in m for _, m, _ in issues)


@pytest.mark.asyncio
async def test_checklist_factuur_gekoppelde_bank_telt_niet(db):
    """Banktx met koppeling_type='factuur' telt niet als ongecategoriseerd.
    Note: add_banktransacties accepteert geen koppeling_type, dus zetten via
    update_banktransactie na insert."""
    await add_banktransacties(db, [
        {'datum': '2026-03-15', 'bedrag': 850.0, 'tegenpartij': 'HAP X'},
    ])
    txs = await get_banktransacties(db, jaar=2026)
    await update_banktransactie(
        db, transactie_id=txs[0].id,
        koppeling_type='factuur', koppeling_id=999)
    async with get_db_ctx(db) as conn:
        issues = await compute_maand_checklist_issues(conn, 2026, 3)
    assert not any('gecategoriseerd' in m for _, m, _ in issues)


@pytest.mark.asyncio
async def test_checklist_unfactured_werkdag(db, monkeypatch):
    import database as _db
    monkeypatch.setattr(_db, '_today_iso', lambda: '2026-04-01')
    kid = await add_klant(db, naam='HAP X', tarief_uur=85)
    await add_werkdag(
        db, klant_id=kid, datum='2026-03-10', uren=8,
        code='A', tarief=85, km=0, urennorm=1)
    async with get_db_ctx(db) as conn:
        issues = await compute_maand_checklist_issues(conn, 2026, 3)
    assert any('ongefactureerd' in m.lower() for _, m, _ in issues)


@pytest.mark.asyncio
async def test_checklist_future_werkdag_skipped(db, monkeypatch):
    """Werkdag in toekomst (datum > vandaag) telt NIET als ongefactureerd."""
    import database as _db
    monkeypatch.setattr(_db, '_today_iso', lambda: '2026-03-15')
    kid = await add_klant(db, naam='HAP X', tarief_uur=85)
    await add_werkdag(
        db, klant_id=kid, datum='2026-03-25', uren=8,
        code='A', tarief=85, km=0, urennorm=1)
    async with get_db_ctx(db) as conn:
        issues = await compute_maand_checklist_issues(conn, 2026, 3)
    assert not any('ongefactureerd' in m.lower() for _, m, _ in issues)


@pytest.mark.asyncio
async def test_checklist_year_scoping(db):
    await add_banktransacties(db, [
        {'datum': '2026-04-15', 'bedrag': -50.0, 'tegenpartij': 'AH'},
    ])
    async with get_db_ctx(db) as conn:
        issues = await compute_maand_checklist_issues(conn, 2026, 3)
    assert issues == []


@pytest.mark.asyncio
async def test_checklist_december_no_overflow(db):
    """December moet zonder fout werken (next_maand_start = 2027-01-01)."""
    await add_banktransacties(db, [
        {'datum': '2026-12-15', 'bedrag': -50.0, 'tegenpartij': 'AH'},
    ])
    async with get_db_ctx(db) as conn:
        issues = await compute_maand_checklist_issues(conn, 2026, 12)
    assert any('niet gecategoriseerd' in m for _, m, _ in issues)


@pytest.mark.asyncio
async def test_checklist_invalid_maand(db):
    async with get_db_ctx(db) as conn:
        with pytest.raises(ValueError):
            await compute_maand_checklist_issues(conn, 2026, 0)


def test_format_bank_status_no_data():
    label = format_bank_status_label(
        {'has_data': False, 'has_post_maand_data': False,
         'last_tx_date': '', 'n_in_maand': 0}, 2026, 3)
    assert 'geen' in label.lower()


def test_format_bank_status_with_data_no_post():
    label = format_bank_status_label(
        {'has_data': True, 'has_post_maand_data': False,
         'last_tx_date': '2026-03-25', 'n_in_maand': 5}, 2026, 3)
    # Eerlijk: alleen "data t/m datum X", geen completeness-claim
    assert '25' in label  # toont datum
    assert 'compleet' not in label.lower()
    assert 'volledig' not in label.lower()


def test_format_bank_status_with_post_maand_data():
    label = format_bank_status_label(
        {'has_data': True, 'has_post_maand_data': True,
         'last_tx_date': '2026-03-30', 'n_in_maand': 12}, 2026, 3)
    # Mag "na maand-einde geïmporteerd" zeggen, geen "compleet"-claim.
    assert 'compleet' not in label.lower()
    assert 'volledig' not in label.lower()


def test_maand_namen_constant():
    assert MAAND_NAMEN[1] == 'januari'
    assert MAAND_NAMEN[12] == 'december'
    assert len(MAAND_NAMEN) == 13  # index 0 = leeg
```

- [ ] **Step 2.** Run, bevestig falen.

- [ ] **Step 3.** Maak `components/maand_afsluiting.py`:

```python
"""Maand-afsluiting checklist + label-helpers (Plan 2026-05-01).

Spiegelt pages/jaarafsluiting.py:compute_checklist_issues maar:
  - per (jaar, maand) i.p.v. per jaar
  - alleen data-checks (geen fiscale-params-checks; jaar-scope)
  - severity-tuple format: (severity, message, link)

De banktransacties-uncategorized-check spiegelt EXACT de SQL uit
database.get_health_alerts (sign-aware uitgaven.categorie voor debits,
banktransacties.categorie voor credits) en
components.transacties_helpers.derive_status (TRIM(...) = '').

De werkdagen-check gebruikt de gecentraliseerde
database.FACTUREERBARE_WERKDAG_FILTER constant — sluit toekomstige
werkdagen + tarief=0 + al-gefactureerd uit.
"""

from __future__ import annotations

# Belangrijk: import als module-attribuut zodat tests
# `monkeypatch.setattr(database, '_today_iso', ...)` ook hier doorwerkt.
# Een `from database import _today_iso` zou de lokale referentie aan
# import-tijd binden; monkeypatch raakt die niet meer.
import database as _db
from components.utils import format_datum


MAAND_NAMEN = (
    '', 'januari', 'februari', 'maart', 'april', 'mei', 'juni',
    'juli', 'augustus', 'september', 'oktober', 'november', 'december',
)


def _maand_range(jaar: int, maand: int) -> tuple[str, str]:
    if not (1 <= maand <= 12):
        raise ValueError(f"maand moet 1..12 zijn, niet {maand}")
    start = f'{jaar}-{maand:02d}-01'
    if maand == 12:
        return start, f'{jaar + 1}-01-01'
    return start, f'{jaar}-{maand + 1:02d}-01'


async def compute_maand_checklist_issues(
    conn, jaar: int, maand: int,
) -> list[tuple[str, str, str | None]]:
    """Data-integrity checks voor één kalendermaand."""
    start, nxt = _maand_range(jaar, maand)
    today = _db._today_iso()
    issues: list[tuple[str, str, str | None]] = []

    # 1. Ongecategoriseerde banktransacties (sign-aware, exact gespiegeld
    # op database.get_health_alerts:uncategorized_bank).
    cur = await conn.execute(
        "SELECT COUNT(*) FROM banktransacties bt "
        "LEFT JOIN uitgaven u ON u.bank_tx_id = bt.id "
        "WHERE bt.datum >= ? AND bt.datum < ? "
        "AND (bt.koppeling_type IS NULL OR bt.koppeling_type = '') "
        "AND (bt.genegeerd = 0 OR bt.genegeerd IS NULL) "
        "AND CASE WHEN bt.bedrag < 0 "
        "  THEN TRIM(COALESCE(u.categorie, '')) = '' "
        "  ELSE TRIM(COALESCE(bt.categorie, '')) = '' END",
        (start, nxt))
    uncat = (await cur.fetchone())[0]
    if uncat > 0:
        issues.append((
            'warning',
            f'{uncat} banktransacties niet gecategoriseerd',
            f'/transacties?status=ongecategoriseerd'
            f'&jaar={jaar}&maand={maand}&type=bank',
        ))

    # 2. Ongefactureerde werkdagen — gebruik gecentraliseerde
    # FACTUREERBARE_WERKDAG_FILTER (datum<=today + tarief>0 +
    # factuurnummer leeg).
    cur = await conn.execute(
        f"SELECT COUNT(*) FROM werkdagen "
        f"WHERE datum >= ? AND datum < ? "
        f"AND {_db.FACTUREERBARE_WERKDAG_FILTER}",
        (start, nxt, today))
    ongefact = (await cur.fetchone())[0]
    if ongefact > 0:
        issues.append((
            'warning',
            f'{ongefact} werkdagen ongefactureerd',
            f'/werkdagen?jaar={jaar}',
        ))

    # 3. Concept-facturen >14d oud (binnen deze maand).
    cur = await conn.execute(
        "SELECT COUNT(*) FROM facturen "
        "WHERE datum >= ? AND datum < ? "
        "AND status = 'concept' "
        "AND datum <= date(?, '-14 day')",
        (start, nxt, today))
    stale_concepts = (await cur.fetchone())[0]
    if stale_concepts > 0:
        issues.append((
            'warning',
            f'{stale_concepts} concept-facturen al > 14 dagen oud',
            '/facturen',
        ))

    # 4. Verlopen facturen (>14d) zonder herinnering.
    cur = await conn.execute(
        "SELECT COUNT(*) FROM facturen "
        "WHERE datum >= ? AND datum < ? "
        "AND status = 'verstuurd' "
        "AND datum <= date(?, '-14 day') "
        "AND (herinnering_datum IS NULL OR herinnering_datum = '')",
        (start, nxt, today))
    no_reminder = (await cur.fetchone())[0]
    if no_reminder > 0:
        issues.append((
            'info',
            f'{no_reminder} verlopen facturen zonder herinnering',
            '/facturen',
        ))

    # 5. Uitgaven zonder PDF-bon. Spiegel derive_status én de date-keuze
    # van get_transacties_view: voor bank-gekoppelde uitgaven gebruikt
    # /transacties b.datum als rij-datum (zie database.py:get_transacties_view
    # — `b.datum AS datum` voor bank-tx-rijen). Voor cash-uitgaven (bank_tx_id
    # NULL) gebruikt het u.datum. We moeten dezelfde keuze hier maken zodat
    # de count exact overeenkomt met /transacties?status=ontbreekt_bon&maand=N.
    # Filter zakelijk: bank-gekoppelde debits via zichtbare-zakelijke-uitgave
    # predicate; cash blijft onvoorwaardelijk meegenomen.
    cur = await conn.execute(
        "SELECT COUNT(*) FROM uitgaven u "
        "LEFT JOIN banktransacties b ON b.id = u.bank_tx_id "
        "WHERE (CASE WHEN u.bank_tx_id IS NULL THEN u.datum ELSE b.datum END) "
        "      >= ? "
        "AND (CASE WHEN u.bank_tx_id IS NULL THEN u.datum ELSE b.datum END) "
        "      < ? "
        "AND TRIM(COALESCE(u.categorie, '')) != '' "
        "AND (u.pdf_pad IS NULL OR u.pdf_pad = '') "
        "AND (u.bank_tx_id IS NULL "
        "     OR (COALESCE(b.genegeerd, 0) = 0 AND b.bedrag < 0))",
        (start, nxt))
    no_pdf = (await cur.fetchone())[0]
    if no_pdf > 0:
        issues.append((
            'info',
            f'{no_pdf} uitgaven zonder bon-PDF',
            f'/transacties?status=ontbreekt_bon&jaar={jaar}&maand={maand}',
        ))

    return issues


def format_bank_status_label(status: dict, jaar: int, maand: int) -> str:
    """UI-tekst voor de bank-import-status. Geen completeness-claim."""
    naam = MAAND_NAMEN[maand]
    if not status.get('has_data'):
        return f'Geen banktransacties geïmporteerd voor {naam} {jaar}'
    last = status.get('last_tx_date', '')
    last_human = format_datum(last) if last else ''
    if status.get('has_post_maand_data'):
        return (f'Bankdata aanwezig t/m {last_human} '
                f'(na maand-einde geïmporteerd)')
    return (f'Bankdata t/m {last_human} — controleer of alle '
            f'transacties van {naam} {jaar} aanwezig zijn')
```

- [ ] **Step 4.** Run, bevestig groen (~26 passed totaal).

- [ ] **Step 5.** Commit.
```bash
git add components/maand_afsluiting.py tests/test_maand_afsluiting.py
git commit -m "feat(maand): compute_maand_checklist_issues + format_bank_status_label"
```

---

## Task 5: Health-alert `month_close_overdue`

**Files:**
- Modify: `database.py` (`get_health_alerts`)
- Modify: `tests/test_health_alerts.py`

**Drempel.** 60 dagen na maand-einde. Activiteit-bronnen via UNION (werkdagen + banktransacties + uitgaven).

- [ ] **Step 1.** Voeg toe aan `tests/test_health_alerts.py`:

```python
@pytest.mark.asyncio
async def test_health_alerts_month_close_overdue_via_werkdag(db, monkeypatch):
    import database as _db
    monkeypatch.setattr(_db, '_today_iso', lambda: '2026-06-15')
    kid = await add_klant(db, naam='HAP X', tarief_uur=85)
    await add_werkdag(
        db, klant_id=kid, datum='2026-03-15', uren=8,
        code='A', tarief=85, km=0, urennorm=1)
    alerts = await get_health_alerts(db, 2026)
    overdue = next((a for a in alerts
                    if a['key'] == 'month_close_overdue'), None)
    assert overdue is not None
    assert overdue['severity'] == 'warning'
    assert '2026-03' in overdue['message']
    assert overdue['link'] == '/maand-afsluiting?jaar=2026'


@pytest.mark.asyncio
async def test_health_alerts_month_close_overdue_via_banktx(db, monkeypatch):
    """Activiteit telt ook via banktransacties (niet alleen werkdagen)."""
    import database as _db
    monkeypatch.setattr(_db, '_today_iso', lambda: '2026-06-15')
    await add_banktransacties(db, [
        {'datum': '2026-03-10', 'bedrag': -25.0, 'tegenpartij': 'X'},
    ])
    alerts = await get_health_alerts(db, 2026)
    assert any(a['key'] == 'month_close_overdue' for a in alerts)


@pytest.mark.asyncio
async def test_health_alerts_month_close_overdue_via_uitgave(db, monkeypatch):
    """Activiteit via cash-uitgave telt ook."""
    import database as _db
    monkeypatch.setattr(_db, '_today_iso', lambda: '2026-06-15')
    from database import add_uitgave
    # add_uitgave accepteert geen 'tegenpartij' kolom — dat staat op
    # banktransacties. Vereiste kwargs: datum, bedrag, categorie, omschrijving.
    await add_uitgave(db, datum='2026-03-12', bedrag=15.0,
                      categorie='Praktijkkosten', omschrijving='Test')
    alerts = await get_health_alerts(db, 2026)
    assert any(a['key'] == 'month_close_overdue' for a in alerts)


@pytest.mark.asyncio
async def test_health_alerts_month_close_overdue_via_factuur(db, monkeypatch):
    """Activiteit via factuur telt óók (UNION moet 4 bronnen omvatten)."""
    import database as _db
    monkeypatch.setattr(_db, '_today_iso', lambda: '2026-06-15')
    from database import add_factuur
    kid = await add_klant(db, naam='HAP X', tarief_uur=85)
    await add_factuur(
        db, nummer='2026-001', klant_id=kid, datum='2026-03-15',
        totaal_uren=8, totaal_km=0, totaal_bedrag=680.0,
        status='verstuurd')
    alerts = await get_health_alerts(db, 2026)
    assert any(a['key'] == 'month_close_overdue' for a in alerts)


@pytest.mark.asyncio
async def test_health_alerts_month_close_overdue_skips_recent(db, monkeypatch):
    """Maand <60 dagen oud → geen alert."""
    import database as _db
    monkeypatch.setattr(_db, '_today_iso', lambda: '2026-04-20')
    kid = await add_klant(db, naam='HAP X', tarief_uur=85)
    await add_werkdag(
        db, klant_id=kid, datum='2026-03-15', uren=8,
        code='A', tarief=85, km=0, urennorm=1)
    alerts = await get_health_alerts(db, 2026)
    assert not any(a['key'] == 'month_close_overdue' for a in alerts)


@pytest.mark.asyncio
async def test_health_alerts_month_close_overdue_skips_afgesloten(db, monkeypatch):
    """Maand met status='afgesloten' triggert geen alert."""
    import database as _db
    monkeypatch.setattr(_db, '_today_iso', lambda: '2026-06-15')
    kid = await add_klant(db, naam='HAP X', tarief_uur=85)
    await add_werkdag(
        db, klant_id=kid, datum='2026-03-15', uren=8,
        code='A', tarief=85, km=0, urennorm=1)
    from database import update_maand_afsluiting_status
    await update_maand_afsluiting_status(db, 2026, 3, 'afgesloten')
    alerts = await get_health_alerts(db, 2026)
    assert not any(a['key'] == 'month_close_overdue' for a in alerts)
```

- [ ] **Step 2.** Run, bevestig falen.

- [ ] **Step 3.** In `database.py:get_health_alerts`, **BINNEN de bestaande `async with get_db_ctx(db_path) as conn:`-block** (zoek met `grep -n "stale werkdagen\|werkdag_stale" database.py`), direct na de "stale werkdagen"-alert, vóór de dedent die de `async with` afsluit. Dit moet de `conn`-variabele kunnen blijven gebruiken — als je het ná de dedent plaatst, is `conn` al gesloten:

```python
        # 5. Maandafsluiting overdue (Plan 2026-05-01).
        # Drempel: maand-einde minstens 60 dagen geleden + status !=
        # 'afgesloten' + minstens 1 activiteit (werkdag/banktx/uitgave/
        # factuur) in de maand. UNION over alle vier bronnen zodat een
        # maand met alleen bonnetjes-uitgaven, bank-incasso's, of
        # ANW/ad-hoc factuur-imports ook detectabel is.
        # Boundary: maand-einde precies 60d geleden TRIGGERT alert (>= 60d).
        from datetime import date as _date, timedelta as _td
        today_d = _date.fromisoformat(_today_iso())
        cutoff_60 = (today_d - _td(days=60)).isoformat()
        cur = await conn.execute(
            """
            WITH activiteit AS (
                SELECT substr(datum, 1, 7) AS ym FROM werkdagen
                  WHERE datum >= ? AND datum < ?
                UNION
                SELECT substr(datum, 1, 7) FROM banktransacties
                  WHERE datum >= ? AND datum < ?
                UNION
                SELECT substr(datum, 1, 7) FROM uitgaven
                  WHERE datum >= ? AND datum < ?
                UNION
                SELECT substr(datum, 1, 7) FROM facturen
                  WHERE datum >= ? AND datum < ?
            )
            SELECT a.ym
            FROM activiteit a
            WHERE
              -- maand-einde = eerste-dag-volgende-maand; >= 60d voor today
              date(a.ym || '-01', '+1 month') <= date(?)
              AND NOT EXISTS (
                SELECT 1 FROM maand_afsluitingen m
                WHERE m.jaar = CAST(substr(a.ym, 1, 4) AS INTEGER)
                  AND m.maand = CAST(substr(a.ym, 6, 2) AS INTEGER)
                  AND m.status = 'afgesloten'
              )
            ORDER BY a.ym
            """,
            (jaar_start, jaar_end,
             jaar_start, jaar_end,
             jaar_start, jaar_end,
             jaar_start, jaar_end,
             cutoff_60))
        overdue_months = [r['ym'] for r in await cur.fetchall()]
        if overdue_months:
            alerts.append({
                'key': 'month_close_overdue',
                'severity': 'warning',
                'message': (f'{len(overdue_months)} maand(en) niet '
                            f'afgesloten: {", ".join(overdue_months)}'),
                'count': len(overdue_months),
                'link': f'/maand-afsluiting?jaar={jaar}',
            })
```

- [ ] **Step 4.** Run, bevestig groen (5 nieuwe + bestaande health-alert tests).

- [ ] **Step 5.** Commit.
```bash
git add database.py tests/test_health_alerts.py
git commit -m "feat(maand): health alert month_close_overdue (UNION-activiteit, 60d drempel)"
```

---

## Task 6: `detect_csv_overlap_with_closed_months`

**Files:**
- Modify: `database.py`
- Modify: `tests/test_maand_afsluiting.py`

- [ ] **Step 1.** Voeg toe aan tests:

```python
from database import detect_csv_overlap_with_closed_months


@pytest.mark.asyncio
async def test_csv_overlap_no_closed_months(db):
    overlap = await detect_csv_overlap_with_closed_months(
        db, ['2026-03-15', '2026-04-10'])
    assert overlap == []


@pytest.mark.asyncio
async def test_csv_overlap_finds_one_closed_month(db):
    await update_maand_afsluiting_status(db, 2026, 3, 'afgesloten')
    overlap = await detect_csv_overlap_with_closed_months(
        db, ['2026-03-15', '2026-04-10'])
    assert overlap == [(2026, 3)]


@pytest.mark.asyncio
async def test_csv_overlap_dedupes_within_maand(db):
    await update_maand_afsluiting_status(db, 2026, 3, 'afgesloten')
    overlap = await detect_csv_overlap_with_closed_months(
        db, ['2026-03-01', '2026-03-15', '2026-03-30'])
    assert overlap == [(2026, 3)]


@pytest.mark.asyncio
async def test_csv_overlap_finds_multiple_closed_months(db):
    await update_maand_afsluiting_status(db, 2026, 3, 'afgesloten')
    await update_maand_afsluiting_status(db, 2026, 4, 'afgesloten')
    overlap = await detect_csv_overlap_with_closed_months(
        db, ['2026-03-15', '2026-04-10', '2026-05-05'])
    assert overlap == [(2026, 3), (2026, 4)]


@pytest.mark.asyncio
async def test_csv_overlap_skips_open_months(db):
    """Maand=4 niet afgesloten — niet in overlap."""
    await update_maand_afsluiting_status(db, 2026, 3, 'afgesloten')
    overlap = await detect_csv_overlap_with_closed_months(
        db, ['2026-04-15'])
    assert overlap == []


@pytest.mark.asyncio
async def test_csv_overlap_handles_malformed_dates(db):
    """Lege of foute datums worden stil overgeslagen, niet geraised."""
    await update_maand_afsluiting_status(db, 2026, 3, 'afgesloten')
    overlap = await detect_csv_overlap_with_closed_months(
        db, ['', 'invalid', '2026-03-15'])
    assert overlap == [(2026, 3)]


@pytest.mark.asyncio
async def test_csv_overlap_empty_input(db):
    assert await detect_csv_overlap_with_closed_months(db, []) == []
    assert await detect_csv_overlap_with_closed_months(db, None) == []
```

- [ ] **Step 2.** Run, bevestig falen.

- [ ] **Step 3.** Implementeer in `database.py`, direct na `get_bank_import_status`:

```python
def _safe_parse_year_month(datum: str) -> tuple[int, int] | None:
    """Tolerante (jaar, maand) parser — None bij malformed input."""
    if not datum or len(datum) < 7:
        return None
    try:
        y = int(datum[:4])
        m = int(datum[5:7])
    except ValueError:
        return None
    if not (1 <= m <= 12):
        return None
    return (y, m)


async def detect_csv_overlap_with_closed_months(
    db_path: Path = DB_PATH, datums: list[str] | None = None,
) -> list[tuple[int, int]]:
    """Geef de unieke (jaar, maand) paren uit `datums` die afgesloten zijn.

    Pure read; geen mutaties. Malformed-datums worden stil overgeslagen.
    """
    if not datums:
        return []
    seen: set[tuple[int, int]] = set()
    for d in datums:
        ym = _safe_parse_year_month(d)
        if ym is not None:
            seen.add(ym)
    if not seen:
        return []
    ym_sorted = sorted(seen)
    # SQLite CTE met VALUES — ondersteund sinds 3.32 (2020).
    # `.venv` heeft 3.53 — bevestigd OK.
    values_clause = ', '.join('(?, ?)' for _ in ym_sorted)
    flat: list[int] = []
    for y, m in ym_sorted:
        flat.extend([y, m])
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            f"WITH q(jaar, maand) AS (VALUES {values_clause}) "
            f"SELECT m.jaar, m.maand FROM maand_afsluitingen m "
            f"JOIN q ON q.jaar = m.jaar AND q.maand = m.maand "
            f"WHERE m.status = 'afgesloten' "
            f"ORDER BY m.jaar, m.maand",
            flat)
        return [(r['jaar'], r['maand']) for r in await cur.fetchall()]
```

- [ ] **Step 4.** Run, bevestig groen.

- [ ] **Step 5.** Commit.
```bash
git add database.py tests/test_maand_afsluiting.py
git commit -m "feat(maand): detect_csv_overlap_with_closed_months (CTE)"
```

---

## Task 7: Pagina `/maand-afsluiting`

**Files:**
- Create: `pages/maand_afsluiting.py`
- Modify: `main.py` (één import-regel)
- Modify: `components/layout.py` (één nav-item-regel)

- [ ] **Step 1.** Maak `pages/maand_afsluiting.py`:

```python
"""Maand-afsluiting pagina (/maand-afsluiting). Plan 2026-05-01.

Per kalenderjaar 12 maand-cards met:
  - status pill (open/afgesloten)
  - bank-import-status label (eerlijk, geen 'compleet'-claim)
  - issue-count uit compute_maand_checklist_issues
  - expandable detail met issue-deeplinks
  - Markeer-als-afgesloten / Heropen knop

v1 scope: status-sticker + CSV-import-waarschuwing. Andere mutaties op
afgesloten maanden worden NIET geblokkeerd of gewaarschuwd.

Render-strategie: één DB-connectie sequentieel over 12 maanden. Geen
asyncio.gather — voor lokale single-user SQLite is parallel-IO meer
overhead dan baat.
"""

from datetime import date

from nicegui import ui

from components.layout import create_layout, page_title
from components.maand_afsluiting import (
    compute_maand_checklist_issues, format_bank_status_label,
    MAAND_NAMEN,
)
from components.shared_ui import year_options
from database import (
    DB_PATH, get_db_ctx, get_maand_afsluitingen,
    update_maand_afsluiting_status, get_bank_import_status,
)


_SEVERITY_COLORS = {
    'critical': 'negative',
    'warning': 'warning',
    'info': 'info',
}


@ui.page('/maand-afsluiting')
async def maand_afsluiting_page(jaar: int | None = None):
    """Query params worden in NiceGUI 3 ontvangen als function-args op de
    `@ui.page`-handler — dezelfde patroon als pages/transacties.py:463.
    """
    create_layout('Maandafsluiting', active_page='/maand-afsluiting')

    huidig_jaar = date.today().year
    state = {'jaar': jaar or huidig_jaar}

    with ui.column().classes('w-full max-w-7xl mx-auto p-6 gap-4'):
        with ui.row().classes('w-full items-center'):
            page_title('Maandafsluiting')
            ui.space()

        with ui.element('div').classes('page-toolbar w-full'):
            jaar_select = ui.select(
                options=year_options(descending=False),
                value=state['jaar'], label='Boekjaar',
            ).classes('w-28')

        grid = ui.grid(columns=3).classes('w-full gap-3')

    async def render_grid():
        grid.clear()
        jaar = state['jaar']
        rows = await get_maand_afsluitingen(DB_PATH, jaar)

        # Sequentieel in één connectie — minder overhead dan
        # 12x get_db_ctx + asyncio.gather op lokaal SQLite.
        results: dict[int, tuple[dict, list]] = {}
        async with get_db_ctx(DB_PATH) as conn:
            for m in range(1, 13):
                # get_bank_import_status opent zelf een korte connectie;
                # we kunnen die niet "lenen" omdat de helper public-API is.
                # Dit is een afgezet 12 fast point-queries — acceptabel.
                status = await get_bank_import_status(DB_PATH, jaar, m)
                issues = await compute_maand_checklist_issues(
                    conn, jaar, m)
                results[m] = (status, issues)

        with grid:
            for row in rows:
                m = row['maand']
                status, issues = results[m]
                _render_maand_card(jaar, m, row, status, issues, render_grid)

    def _render_maand_card(jaar, maand, row, status, issues, refresh):
        afgesloten = row['status'] == 'afgesloten'
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full items-center'):
                ui.label(f'{MAAND_NAMEN[maand].capitalize()} {jaar}') \
                    .classes('text-subtitle1 text-bold')
                ui.space()
                if afgesloten:
                    ui.badge('Afgesloten', color='positive')
                else:
                    ui.badge('Open', color='warning')

            ui.label(format_bank_status_label(status, jaar, maand)) \
                .classes('text-caption text-grey-7')

            with ui.row().classes('w-full items-center'):
                if issues:
                    ui.icon('warning', color='warning')
                    ui.label(f'{len(issues)} aandachtspunt(en)') \
                        .classes('text-caption')
                else:
                    ui.icon('check_circle', color='positive')
                    ui.label('Geen openstaande punten') \
                        .classes('text-caption')

            with ui.expansion('Details', icon='expand_more').classes('w-full'):
                if issues:
                    for severity, msg, link in issues:
                        with ui.row().classes('w-full items-center'):
                            ui.icon('error_outline',
                                    color=_SEVERITY_COLORS.get(
                                        severity, 'grey'))
                            ui.label(msg).classes('text-body2')
                            ui.space()
                            if link:
                                ui.button(
                                    'Open', icon='open_in_new',
                                    on_click=lambda l=link:
                                        ui.navigate.to(l)) \
                                    .props('flat dense color=primary')
                else:
                    ui.label('Alle checks gepasseerd.') \
                        .classes('text-caption text-grey-6')

                if afgesloten and row['closed_at']:
                    ui.label(f"Afgesloten op {row['closed_at'][:16]}") \
                        .classes('text-caption text-grey-6')

            with ui.row().classes('w-full justify-end'):
                if afgesloten:
                    ui.button(
                        'Heropen', icon='lock_open',
                        on_click=lambda j=jaar, m=maand: _toggle(
                            j, m, 'open', refresh),
                    ).props('flat dense color=secondary')
                else:
                    ui.button(
                        'Markeer als afgesloten', icon='check_circle',
                        on_click=lambda j=jaar, m=maand: _toggle(
                            j, m, 'afgesloten', refresh),
                    ).props('color=primary dense')

    async def _toggle(jaar, maand, target_status, refresh):
        if target_status == 'afgesloten':
            async with get_db_ctx(DB_PATH) as conn:
                issues = await compute_maand_checklist_issues(
                    conn, jaar, maand)
            warnings = [i for i in issues
                        if i[0] in ('warning', 'critical')]
            if warnings:
                ok = await _confirm_close_with_warnings(
                    jaar, maand, warnings)
                if not ok:
                    return
        await update_maand_afsluiting_status(
            DB_PATH, jaar, maand, target_status)
        verb = 'afgesloten' if target_status == 'afgesloten' else 'heropend'
        ui.notify(f'{MAAND_NAMEN[maand].capitalize()} {jaar} {verb}',
                  type='positive')
        await refresh()

    async def _confirm_close_with_warnings(jaar, maand, warnings):
        result = {'ok': False}
        with ui.dialog() as d, ui.card():
            ui.label(
                f'{MAAND_NAMEN[maand].capitalize()} {jaar} heeft '
                f'{len(warnings)} openstaande punt(en):'
            ).classes('text-subtitle1')
            for _, msg, _ in warnings:
                ui.label(f'• {msg}').classes('text-body2')
            ui.label('Toch markeren als afgesloten?') \
                .classes('text-caption q-mt-md')
            with ui.row().classes('w-full justify-end'):
                ui.button('Annuleer', on_click=d.close).props('flat')
                def _ok():
                    result['ok'] = True
                    d.close()
                ui.button('Toch afsluiten', on_click=_ok) \
                    .props('color=warning')
        await d
        return result['ok']

    async def on_jaar_change(e):
        state['jaar'] = e.value
        await render_grid()

    jaar_select.on_value_change(on_jaar_change)
    await render_grid()
```

- [ ] **Step 2.** In `main.py` (zoek met `grep -n "import pages\." main.py`), voeg toe in het importblok (volgorde is niet alfabetisch in main.py — plaats ergens tussen `pages.documenten` en `pages.instellingen`):

```python
import pages.maand_afsluiting  # noqa: F401
```

- [ ] **Step 3.** In `components/layout.py:204` (de `NAV_GROUPS` constante in `create_layout`), wijzig de derde groep van:

```python
        [('Documenten', 'folder_open', '/documenten'),
         ('Jaarafsluiting', 'assessment', '/jaarafsluiting'),
         ('Aangifte', 'assignment', '/aangifte')],
```

naar:

```python
        [('Documenten', 'folder_open', '/documenten'),
         ('Maandafsluiting', 'event_available', '/maand-afsluiting'),
         ('Jaarafsluiting', 'assessment', '/jaarafsluiting'),
         ('Aangifte', 'assignment', '/aangifte')],
```

- [ ] **Step 4.** Hand-test.
```bash
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py
```
Acceptatie-pad in het venster:
1. Sidebar toont "Maandafsluiting" — klik → 12 cards renderen voor huidig jaar.
2. Maart-kaart toont status-label gebaseerd op aanwezigheid bankdata. Datum in NL-format DD-MM-YYYY.
3. Voeg 1 ongecategoriseerde banktx toe (via /transacties → CSV-import of een dummy via /transacties UI), terug naar /maand-afsluiting → kaart toont aandachtspunt-badge en deeplink.
4. Klik 'Markeer als afgesloten' op een schone maand → status pill flipt direct naar groen, closed_at zichtbaar in details.
5. Klik 'Heropen' → terug naar oranje "Open".
6. Wissel jaar via dropdown → grid herlaadt.
7. Sluit een maand met een open warning → bevestigingsdialoog verschijnt; "Annuleer" annuleert; "Toch afsluiten" sluit.

- [ ] **Step 5.** Commit.
```bash
git add pages/maand_afsluiting.py main.py components/layout.py
git commit -m "feat(maand): /maand-afsluiting pagina + nav"
```

---

## Task 8: CSV-import waarschuwing voor afgesloten maand

**Files:**
- Modify: `pages/transacties.py`

**Plaatsing.** Direct ná het parsen van de CSV en ná de bestaande duplicate-filename-check (zodat we geen waarschuwing tonen voor data die toch niet wordt geïmporteerd), VÓÓR de `add_banktransacties`-aanroep.

- [ ] **Step 1.** Lokaliseer de upload-handler in `pages/transacties.py`.
```bash
grep -n "rabobank\|csv_bestand\|add_banktransacties\|parse_rabobank_csv" \
  pages/transacties.py | head -20
```

- [ ] **Step 2.** Voeg imports toe aan de top van `pages/transacties.py`:

```python
# Voeg toe aan bestaande database-import:
#   detect_csv_overlap_with_closed_months
# En een nieuwe import van de gedeelde maand-namen:
from components.maand_afsluiting import MAAND_NAMEN
```

- [ ] **Step 3.** In de upload-handler, na parse + duplicate-check, vóór `add_banktransacties`:

```python
# Plan 2026-05-01: waarschuw als import-data een afgesloten maand raakt.
overlapping = await detect_csv_overlap_with_closed_months(
    DB_PATH, [t.get('datum', '') for t in transacties])
if overlapping:
    namen = ', '.join(
        f'{MAAND_NAMEN[m]} {y}' for y, m in overlapping)
    ui.notify(
        f'Let op: import bevat data uit afgesloten maanden ({namen}). '
        f'De maand-afsluiting blijft staan; ga naar Maandafsluiting '
        f'om te heropenen indien nodig.',
        type='warning', timeout=8000)
```

- [ ] **Step 4.** Hand-test.
1. Sluit een maand af in /maand-afsluiting.
2. Importeer een CSV met datums in die maand.
3. Verwacht: notify-banner verschijnt; transacties worden wél geïmporteerd; geen exception.

- [ ] **Step 5.** Commit.
```bash
git add pages/transacties.py
git commit -m "feat(maand): CSV-import waarschuwt bij overlap met afgesloten maand"
```

---

## Task 9: CLAUDE.md documentatie

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1.** Voeg toe aan `CLAUDE.md` in de Database-sectie (na de migratie-34 beschrijving, zoek met `grep -n "migratie 34\|klant_aliases" CLAUDE.md | head -3`):

```markdown
- `maand_afsluitingen` (migratie 35, Plan 2026-05-01): per (jaar, maand) een
  status-sticker `'open'` | `'afgesloten'` met `closed_at`/`updated_at`-stamps. **v1 is GEEN hard-lock**:
  een afgesloten maand blokkeert geen mutaties; alleen de CSV-import-flow toont
  een waarschuwingsnotify bij overlap. Hard-lock blijft exclusief op jaar-niveau
  via `assert_year_writable`. UI: `/maand-afsluiting` (12-cards grid, sequentieel
  gerenderd in één DB-connectie). Helpers: `get_maand_afsluitingen`,
  `update_maand_afsluiting_status`, `get_bank_import_status`,
  `detect_csv_overlap_with_closed_months`. Per-maand checklist via
  `components/maand_afsluiting.py:compute_maand_checklist_issues` (gebruikt
  gecentraliseerde `FACTUREERBARE_WERKDAG_FILTER`; sign-aware
  uncategorized-bank predicate gespiegeld op `database.get_health_alerts` +
  `derive_status`). Health alert `month_close_overdue` flagt maanden met
  activiteit (werkdag/banktx/uitgave UNION) > 60 dagen oud zonder afsluit-stempel.
  `components.maand_afsluiting` doet `import database as _db` (niet
  `from database import _today_iso`) zodat tests via
  `monkeypatch.setattr(database, '_today_iso', ...)` reproduceerbare datums
  kunnen forceren — direct-import zou de lokale referentie aan import-tijd binden.
```

- [ ] **Step 2.** Commit.
```bash
git add CLAUDE.md
git commit -m "docs(maand): documenteer maand-afsluiting in CLAUDE.md"
```

---

## Task 10: Final test sweep + codex-review

- [ ] **Step 1.** Run volledige suite — geen regressies.
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```
Verwacht: baseline (~1054) + ~30 nieuwe = ~1084 passed.

- [ ] **Step 2.** Run codex-review op de hele branch-diff.
```bash
git diff master...HEAD -- '*.py' | env -u OPENAI_API_KEY \
  codex exec --sandbox read-only --skip-git-repo-check \
  "Review de maand-afsluiting feature. Focus op: SQL-correctness (CTE-VALUES, sign-aware uncategorized-predicate, FACTUREERBARE_WERKDAG_FILTER hergebruik), year-locking-implicaties (mag geen hard-lock op maand zijn), NiceGUI-patronen (single-connection render), test-coverage (december-edge, jaargrens, malformed datum), CLAUDE.md-conventie-violations. Wees terse — max 5 bullets. Geen restyle-suggesties."
```

- [ ] **Step 3.** Per bevinding evalueer technisch (zie `superpowers:receiving-code-review` principes; codex is input, geen verdict). Maak waar van toepassing een fix-commit:
```bash
git commit -m "fix(maand): codex final-review — <korte beschrijving>"
```

- [ ] **Step 4.** Hand-acceptance van het volledige pad:
1. Dashboard zonder jaargrens-issues toont geen `month_close_overdue` voor het current-jaar.
2. /maand-afsluiting voor 2026 → 12 cards rendering.
3. Sluit een maand af; sluit de app; herstart; status nog steeds afgesloten.
4. Importeer CSV met overlap; notify verschijnt; transacties geïmporteerd.
5. Heropen; alert verschijnt na simulatie van datum 60d later (test-monkeypatch is in CI voldoende — geen DB-mutatie nodig).
6. Maand met warning-issue: sluit-knop opent bevestigingsdialoog.

- [ ] **Step 5.** Push.
```bash
git log --oneline master..HEAD
git push -u origin feature/maand-afsluiting
```

---

## Out of scope (v2-kandidaten)

- **Internal-gap-detectie binnen de maand** (>7d zonder banktx midden in de maand → suspect). Vraagt rij-niveau-analyse die nu ontbreekt.
- **Import-batch-metadata** (`csv_bestand`, `imported_at`, `min_datum`, `max_datum`, `row_count`, `sha256`) — echte completeness-claims worden dan mogelijk; rechtvaardigt sterkere UI-taal dan "data t/m DD-MM".
- **Cross-cutting "afgesloten-maand"-waarschuwing** in andere mutation-handlers (categorize-banktx, edit-factuur, mark-als-betaald, add-cash-uitgave). v1 is alleen CSV-import.
- **Bulk "Sluit alle maanden tot en met X af"** knop.
- **Snapshot/PDF-export per afgesloten maand** (zoals jaarafsluiting heeft).
- **Hard-lock per maand** (`MaandLockedError` sub-class) — bewust niet — maand-afsluiting is operationeel routine, niet rituaal.
- **Auto-suggestie "afsluiten?"** zodra alle checks groen zijn voor een maand >30d oud.
- **Integratie met /jaarafsluiting pre-flight** (toon "12/12 maanden afgesloten" als pre-flight check).

---

## Self-review

| Spec-eis | Geadresseerd in | Status |
|---|---|---|
| Banktransacties geïmporteerd t/m maand-einde — CSV-dekking-detector | Task 3 (`get_bank_import_status` + label-helper) | ✅ — eerlijk gelabeld als "Bankdata t/m DD-MM-YYYY", geen onhaalbare completeness-claim |
| Geen ongecategoriseerde bank-rijen in deze maand | Task 4 checklist-issue 1 | ✅ |
| Werkdagen van deze maand gefactureerd | Task 4 checklist-issue 2 (FACTUREERBARE_WERKDAG_FILTER) | ✅ |
| Bonnen aanwezig voor alle gecategoriseerde uitgaven | Task 4 checklist-issue 5 | ✅ |
| Verlopen facturen / concept-facturen | Task 4 checklist-issues 3-4 | ✅ |
| Knop "Markeer maand als afgesloten" | Task 7 | ✅ |
| Toekomstige imports voor afgesloten maand triggeren waarschuwing | Task 8 | ✅ — alleen CSV-import; andere paths v2 |
| Soft-lock (geen `YearLockedError`-stijl) | Plan §3 + Task 7 (geen guard, alleen sticker) | ✅ |
| Health-alert voor verlate maand-afsluiting | Task 5 (`month_close_overdue`, UNION-activiteit) | ✅ |
| Factuur-matches-review-check | Niet expliciet | ❌ v2 — impliciet via koppeling_type IS NULL filter in checklist-issue 1 |
| Snapshot-backup na afsluiten | Niet | ❌ v2 — bestaande `/instellingen` backup is goed-genoeg in v1 |

**Placeholder-scan.** Geen `TBD`, `TODO`, `similar to` of "implementeer later". Geen externe sub-skill-eis. Plan-datum overal `2026-05-01`. `MAAND_NAMEN` is een constante geëxporteerd uit `components.maand_afsluiting`. `_db._today_iso()` patroon is consistent gebruikt waar test-monkeypatch nodig is.

**Type-consistency.** `compute_maand_checklist_issues` returnt `list[tuple[str, str, str | None]]` overal. `get_bank_import_status` returnt `dict` met dezelfde keys overal. `detect_csv_overlap_with_closed_months` returnt `list[tuple[int, int]]` overal.

---

## Implementatie-omvang

- 10 commits over 10 tasks
- ~32 nieuwe tests (1054 baseline → ~1086)
- 2 nieuwe bestanden (1 page, 1 component)
- 4 gewijzigde bestanden (database.py, layout.py, main.py, transacties.py, plus tests + CLAUDE.md)
- Geschat werk: 4-6 dagen voor één developer met TDD-discipline

**Plan is ship-ready.** Drie codex-review-rondes (incl. final tactical proofread) hebben 29 bevindingen opgeleverd, allen geadresseerd:
- Round 1 (15 punten): naamgeving, soft-lock semantiek, SQL-correctness, `notes`-ballast, edge-cases.
- Round 2 (7 punten): label/test contradictie, `_today_iso` monkeypatch-veiligheid, broken testsnippets, DD-MM-YYYY format, main.py anchor, performance, suite-runs.
- Round 3 final (7 punten): `add_uitgave` missende `omschrijving`, `month_close_overdue` mist facturen-bron, `ontbreekt_bon` date-mismatch (`u.datum` vs `b.datum`), 60d off-by-one ambiguïteit, health-alert plaatsing kwetsbaar, "één DB-conn" architectuur-tekst inconsistent, plus zelf-ontdekte NiceGUI-3 query-params API-bug (functie-arg pattern in plaats van `ui.context.client.request.query_params`).
