# Agenda Sprint 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `Nieuwe werkdag` knop bug + maak werkdag-pills in `/agenda` interactief (klik → edit, right-click → context-menu) + voeg `duplicate_werkdag` helper toe.

**Architecture:** Test-first per layer. DB-helpers eerst (`get_werkdag_by_id`, `duplicate_werkdag`), dan pure UI-helpers (`_pill_context_actions`, `_pill_tooltip`), dan integratie in `pages/agenda.py` (event-handlers + Vue context-menu via `ui.context_menu()`).

**Tech Stack:** NiceGUI 3.8.0, Quasar (`q-menu` met `context-menu=True`), aiosqlite, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-08-agenda-sprint-1-design.md`

**Commit-policy:** Per CLAUDE.md "NEVER commit changes unless the user explicitly asks". Plan staget tijdens werk maar commit niet — Final Task vraagt user-approval voor één enkele commit aan eind.

---

## Task 1: Bug-fix — wire `Nieuwe werkdag` knop

**Files:**
- Modify: `pages/agenda.py:485` (creation site) + ~regel 645-648 (wiring site)
- Test: `tests/test_agenda_page.py` (source-pin)

- [ ] **Step 1: Schrijf source-pin test**

Voeg toe in `tests/test_agenda_page.py`:

```python
def test_new_werkdag_button_is_wired():
    """Regression-pin: refs['new_btn'].on_click(...) must exist in
    pages/agenda.py — the original bug was an unwired button.
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'pages' / 'agenda.py'
    text = src.read_text(encoding='utf-8')
    assert "refs['new_btn'].on_click" in text, (
        "refs['new_btn'].on_click(...) wiring missing — "
        "Nieuwe werkdag knop zal niet werken")
```

- [ ] **Step 2: Run test to verify it fails**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_page.py::test_new_werkdag_button_is_wired -v
```
Expected: FAIL with assertion error.

- [ ] **Step 3: Add wiring**

In `pages/agenda.py`, naast bestaande wiring rond regel 645-648:

```python
    refs['prev_btn'].on_click(go_prev)
    refs['next_btn'].on_click(go_next)
    refs['today_btn'].on_click(go_today)
    refs['refresh_btn'].on_click(lambda: ui.timer(0, render, once=True))
    refs['new_btn'].on_click(
        lambda: ui.timer(
            0,
            lambda: handle_add_werkdag(state['selected']),
            once=True))
```

- [ ] **Step 4: Run test to verify it passes**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_page.py::test_new_werkdag_button_is_wired -v
```
Expected: PASS.

---

## Task 2: DB-helper `get_werkdag_by_id`

**Files:**
- Modify: `database.py` (after `get_werkdagen` definition rond regel 1575)
- Test: `tests/test_database.py`

- [ ] **Step 1: Schrijf test (happy + missing)**

Voeg toe in `tests/test_database.py` (zoek geschikte plek, bv. na bestaande werkdag-tests):

```python
@pytest.mark.asyncio
async def test_get_werkdag_by_id_returns_full_werkdag(db):
    """Happy-path: roundtrip levert volledige Werkdag terug."""
    from database import (
        add_klant, add_werkdag, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=10)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8.0,
        km=20, tarief=80, opmerking='Test')
    w = await get_werkdag_by_id(db, werkdag_id=wid)
    assert w is not None
    assert w.id == wid
    assert w.datum == '2026-05-15'
    assert w.klant_id == kid
    assert w.uren == 8.0
    assert w.opmerking == 'Test'
    assert w.klant_naam == 'Test'  # joined via _row_to_werkdag


@pytest.mark.asyncio
async def test_get_werkdag_by_id_returns_none_for_missing(db):
    """Non-existent ID → None, geen exception."""
    from database import get_werkdag_by_id
    w = await get_werkdag_by_id(db, werkdag_id=99999)
    assert w is None
```

- [ ] **Step 2: Run tests, verify FAIL**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py::test_get_werkdag_by_id_returns_full_werkdag tests/test_database.py::test_get_werkdag_by_id_returns_none_for_missing -v
```
Expected: FAIL — "ImportError: cannot import name 'get_werkdag_by_id'".

- [ ] **Step 3: Implementeer helper**

In `database.py`, direct na `get_werkdagen()` (regel ~1577):

```python
async def get_werkdag_by_id(
        db_path: Path = DB_PATH, werkdag_id: int = 0) -> Werkdag | None:
    """Single-row variant van get_werkdagen — voor edit/duplicate flows
    die een Werkdag-shape verwachten (niet een lichte WerkdagPill).

    Returns Werkdag of None als ID niet bestaat. Hergebruikt
    `_row_to_werkdag` voor consistente type-shape met /werkdagen.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT w.*, k.naam as klant_naam,
                      CASE
                          WHEN w.factuurnummer = '' OR w.factuurnummer IS NULL
                              THEN 'ongefactureerd'
                          WHEN f.status = 'betaald' THEN 'betaald'
                          ELSE 'gefactureerd'
                      END as computed_status
               FROM werkdagen w
               JOIN klanten k ON w.klant_id = k.id
               LEFT JOIN facturen f ON w.factuurnummer = f.nummer
               WHERE w.id = ?""",
            (werkdag_id,))
        row = await cur.fetchone()
    return _row_to_werkdag(row) if row else None
```

- [ ] **Step 4: Run tests, verify PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py::test_get_werkdag_by_id_returns_full_werkdag tests/test_database.py::test_get_werkdag_by_id_returns_none_for_missing -v
```
Expected: 2 passed.

---

## Task 3: DB-helper `duplicate_werkdag` (happy-path)

**Files:**
- Modify: `database.py` (na `get_werkdag_by_id`)
- Test: `tests/test_database.py`

- [ ] **Step 1: Schrijf happy-path test**

```python
@pytest.mark.asyncio
async def test_duplicate_werkdag_copies_all_fields(db):
    """Dupliceren kopieert alle velden behalve factuurnummer."""
    from database import (
        add_klant, add_klant_locatie, add_werkdag,
        get_werkdag_by_id, duplicate_werkdag,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=10)
    lid = await add_klant_locatie(
        db, klant_id=kid, naam='Locatie A', retour_km=15)
    src_id = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid,
        code='WERKDAG', activiteit='Waarneming dagpraktijk',
        locatie='Locatie A', locatie_id=lid,
        uren=8.0, km=20, tarief=80, km_tarief=0.23,
        opmerking='Bron-werkdag', urennorm=1,
        factuurnummer='2026-001')

    new_id = await duplicate_werkdag(
        db, werkdag_id=src_id, target_datum='2026-05-22')

    assert new_id != src_id
    new_w = await get_werkdag_by_id(db, werkdag_id=new_id)
    assert new_w is not None
    assert new_w.datum == '2026-05-22'
    assert new_w.klant_id == kid
    assert new_w.code == 'WERKDAG'
    assert new_w.activiteit == 'Waarneming dagpraktijk'
    assert new_w.locatie == 'Locatie A'
    assert new_w.locatie_id == lid
    assert new_w.uren == 8.0
    assert new_w.km == 20
    assert new_w.tarief == 80
    assert new_w.km_tarief == 0.23
    assert new_w.opmerking == 'Bron-werkdag'
    assert new_w.urennorm == 1
    # Factuurnummer NIET meegekopieerd.
    assert new_w.factuurnummer == ''

    # Bron is ongewijzigd.
    src_w = await get_werkdag_by_id(db, werkdag_id=src_id)
    assert src_w.datum == '2026-05-15'
    assert src_w.factuurnummer == '2026-001'
```

- [ ] **Step 2: Run test, verify FAIL**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py::test_duplicate_werkdag_copies_all_fields -v
```
Expected: ImportError op `duplicate_werkdag`.

- [ ] **Step 3: Implementeer helper**

In `database.py`, direct na `get_werkdag_by_id`:

```python
async def duplicate_werkdag(
        db_path: Path = DB_PATH, werkdag_id: int = 0,
        target_datum: str = '') -> int:
    """Kopieer een werkdag naar ``target_datum``.

    Kopieert: klant_id, code, activiteit, locatie, locatie_id, uren, km,
    tarief, km_tarief, opmerking, urennorm. Wist `factuurnummer` (nooit
    meegekopieerd — dupliceren ≠ factuur-koppeling).

    Year-lock: alleen op target_datum (bron is read-only). Source-datum
    mag in definitief jaar zitten. Year-lock-check gebeurt vóór de
    INSERT-connection — volgens bestaand pattern in `add_werkdag` etc.;
    geen volledige atomicity vs gelijktijdige jaarafsluiting nodig
    voor single-user lokale app.

    Blocker/holiday op target-datum: niet gecheckt — consistent met
    "Extra werkdag" knop in Day-Inspector die ook op blocker-dagen
    werkdagen toestaat (vakantie + dienst is geldig scenario).

    Raises:
        ValueError: target_datum invalid format of bron bestaat niet.
        YearLockedError: target_datum in definitief jaar.
    """
    _validate_datum(target_datum)
    await assert_year_writable(db_path, target_datum)
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT klant_id, code, activiteit, locatie, locatie_id, "
            "       uren, km, tarief, km_tarief, opmerking, urennorm "
            "FROM werkdagen WHERE id = ?",
            (werkdag_id,))
        src = await cur.fetchone()
        if src is None:
            raise ValueError(f"Werkdag {werkdag_id} bestaat niet")
        # `is None`-checks (NIET `or default`): valide km_tarief=0 (ANW) of
        # urennorm=0 (achterwacht/zero-uren codes) zijn truthy-falsy '0'
        # die `or X` zou platslaan op `X` — domeinregel-bug.
        cursor = await conn.execute(
            """INSERT INTO werkdagen
               (datum, klant_id, code, activiteit, locatie, uren, km,
                tarief, km_tarief, factuurnummer, opmerking, urennorm,
                locatie_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)""",
            (target_datum, src['klant_id'],
             src['code'] if src['code'] is not None else '',
             src['activiteit'] if src['activiteit'] is not None
                 else 'Waarneming dagpraktijk',
             src['locatie'] if src['locatie'] is not None else '',
             src['uren'],
             src['km'] if src['km'] is not None else 0,
             src['tarief'],
             src['km_tarief'] if src['km_tarief'] is not None else 0.23,
             src['opmerking'] if src['opmerking'] is not None else '',
             src['urennorm'] if src['urennorm'] is not None else 1,
             src['locatie_id']),
        )
        await conn.commit()
        return cursor.lastrowid
```

- [ ] **Step 4: Run test, verify PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py::test_duplicate_werkdag_copies_all_fields -v
```
Expected: PASS.

---

## Task 4: `duplicate_werkdag` — error-paths

**Files:**
- Test: `tests/test_database.py` (extend Task 3 test-block)

- [ ] **Step 1: Schrijf error-path tests**

```python
@pytest.mark.asyncio
async def test_duplicate_werkdag_raises_on_missing_source(db):
    from database import duplicate_werkdag
    with pytest.raises(ValueError, match='99999'):
        await duplicate_werkdag(
            db, werkdag_id=99999, target_datum='2026-05-22')


@pytest.mark.asyncio
async def test_duplicate_werkdag_raises_on_invalid_datum(db):
    from database import (
        add_klant, add_werkdag, duplicate_werkdag,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    src = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80)
    with pytest.raises(ValueError):
        await duplicate_werkdag(
            db, werkdag_id=src, target_datum='not-a-date')


@pytest.mark.asyncio
async def test_duplicate_werkdag_allows_blocker_on_target(db):
    """Consistent met 'Extra werkdag' op blocker-dag (vakantie + dienst)."""
    from database import (
        add_klant, add_werkdag, duplicate_werkdag,
        get_werkdag_by_id,
    )
    import services.agenda as agenda_svc
    from datetime import date as _date_cls

    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    src = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80)
    # Blocker op target-datum.
    await agenda_svc.add_blocker(
        db, datum=_date_cls(2026, 5, 22),
        kind='vacation', label='Vakantie')
    # Dupliceren mag — geen exception.
    new_id = await duplicate_werkdag(
        db, werkdag_id=src, target_datum='2026-05-22')
    new_w = await get_werkdag_by_id(db, werkdag_id=new_id)
    assert new_w.datum == '2026-05-22'


@pytest.mark.asyncio
async def test_duplicate_werkdag_preserves_zero_km_tarief(db):
    """ANW-werkdag heeft km_tarief=0 (geen reiskosten in tarief). MUST blijven 0
    in dupliceren — codex catch: `or 0.23` zou dit naar 0.23 platslaan."""
    from database import (
        add_klant, add_werkdag, duplicate_werkdag, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    src = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid,
        code='ANW', activiteit='ANW',
        uren=12, tarief=80, km_tarief=0)
    new_id = await duplicate_werkdag(
        db, werkdag_id=src, target_datum='2026-05-22')
    new_w = await get_werkdag_by_id(db, werkdag_id=new_id)
    assert new_w.km_tarief == 0


@pytest.mark.asyncio
async def test_duplicate_werkdag_preserves_zero_urennorm(db):
    """ACHTERWACHT/CONGRES-codes hebben urennorm=0 (telt niet voor 1225-norm).
    MUST blijven 0 in dupliceren — codex catch: `or 1` zou 0 → 1 maken."""
    from database import (
        add_klant, add_werkdag, duplicate_werkdag, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    src = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid,
        code='ACHTERWACHT', activiteit='Achterwacht',
        uren=0, tarief=0, urennorm=0)
    new_id = await duplicate_werkdag(
        db, werkdag_id=src, target_datum='2026-05-22')
    new_w = await get_werkdag_by_id(db, werkdag_id=new_id)
    assert new_w.urennorm == 0


@pytest.mark.asyncio
async def test_duplicate_werkdag_allows_same_date(db):
    """Dupliceren naar zelfde datum als bron — multi-shift dezelfde dag."""
    from database import (
        add_klant, add_werkdag, duplicate_werkdag, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    src = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80)
    new_id = await duplicate_werkdag(
        db, werkdag_id=src, target_datum='2026-05-15')
    assert new_id != src
    new_w = await get_werkdag_by_id(db, werkdag_id=new_id)
    assert new_w.datum == '2026-05-15'
```

- [ ] **Step 2: Run tests, verify PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py -k "duplicate_werkdag"
echo "EXIT=$?"
```
Expected: `EXIT=0`. Alle `duplicate_werkdag` tests groen — exact aantal niet pinnen (codex finding 5 round 2 — testset breidt nog uit met km_tarief=0, urennorm=0, same-date).

---

## Task 5: `duplicate_werkdag` — year-lock

**Files:**
- Test: `tests/test_year_locking.py`

- [ ] **Step 1: Schrijf year-lock tests**

In `tests/test_year_locking.py`, voeg import toe en nieuwe tests onder bestaande werkdag-tests:

```python
# Voeg toe aan import-blok bovenin:
#     duplicate_werkdag,

@pytest.mark.asyncio
async def test_duplicate_werkdag_rejects_target_in_definitief_year(db):
    """Year-lock op target-datum: dupliceren naar definitief jaar weigeren."""
    from database import (
        add_klant, add_werkdag, duplicate_werkdag,
        get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2024)
    src = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80)
    await update_jaarafsluiting_status(db, 2024, 'definitief')

    with pytest.raises(YearLockedError, match='2024'):
        await duplicate_werkdag(
            db, werkdag_id=src, target_datum='2024-12-15')


@pytest.mark.asyncio
async def test_duplicate_werkdag_allows_source_in_definitief_year(db):
    """Source mag in definitief jaar zitten — read-only voor dupliceren."""
    from database import (
        add_klant, add_werkdag, duplicate_werkdag,
        get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    # Voeg eerst werkdag in 2024 toe (jaar nog niet gesloten).
    await _seed_fiscale_params_row(db, 2024)
    src = await add_werkdag(
        db, datum='2024-06-01', klant_id=kid, uren=8, tarief=80)
    # Sluit jaar 2024 nu af.
    await update_jaarafsluiting_status(db, 2024, 'definitief')

    # Target in 2026 (writable) — dupliceren mag, ondanks bron in 2024.
    new_id = await duplicate_werkdag(
        db, werkdag_id=src, target_datum='2026-05-22')
    new_w = await get_werkdag_by_id(db, werkdag_id=new_id)
    assert new_w is not None
    assert new_w.datum == '2026-05-22'
```

- [ ] **Step 2: Run tests, verify PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_year_locking.py -k "duplicate_werkdag" -v
```
Expected: 2 passed.

---

## Task 5b: DB-helper `unlink_werkdag_from_factuur` (atomic + year-locked)

**Files:**
- Modify: `database.py` (na `duplicate_werkdag`)
- Test: `tests/test_year_locking.py` + `tests/test_database.py`

**Waarom een nieuwe helper**: codex finding 2 — handler `handle_pill_ontkoppel` doet pre-dialog status-refetch + post-dialog `update_werkdag`. Gebruiker kan in confirm-dialog wachten terwijl elders de factuur wordt verstuurd → race-window waarbij verstuurde factuur alsnog ontkoppeld zou kunnen worden. Atomic helper sluit deze gap.

- [ ] **Step 1: Schrijf tests**

In `tests/test_database.py`:

```python
@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_clears_factuurnummer_for_concept(db):
    """Concept-factuur unlink → factuurnummer leeg, factuur ongewijzigd."""
    from database import (
        add_klant, add_werkdag, add_factuur,
        unlink_werkdag_from_factuur, get_werkdag_by_id, get_facturen,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80,
        factuurnummer='2026-001')
    await add_factuur(
        db, nummer='2026-001', klant_id=kid, datum='2026-05-15',
        totaal_bedrag=640, status='concept')

    await unlink_werkdag_from_factuur(db, werkdag_id=wid)

    w = await get_werkdag_by_id(db, werkdag_id=wid)
    assert w.factuurnummer == ''
    facturen = await get_facturen(db)
    assert any(f.nummer == '2026-001' for f in facturen)


@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_clears_orphan_link(db):
    """Orphan-factuurnummer (factuur_id IS NULL) — ontkoppel mag."""
    from database import (
        add_klant, add_werkdag, unlink_werkdag_from_factuur,
        get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80,
        factuurnummer='2025-999')  # geen bijbehorende factuur-row
    await unlink_werkdag_from_factuur(db, werkdag_id=wid)
    w = await get_werkdag_by_id(db, werkdag_id=wid)
    assert w.factuurnummer == ''


@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_rejects_verstuurd(db):
    """Verstuurde factuur kan NIET ontkoppeld worden — boekhoudkundig."""
    from database import (
        add_klant, add_werkdag, add_factuur,
        unlink_werkdag_from_factuur, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80,
        factuurnummer='2026-001')
    await add_factuur(
        db, nummer='2026-001', klant_id=kid, datum='2026-05-15',
        totaal_bedrag=640, status='verstuurd')
    with pytest.raises(ValueError, match='verstuurd'):
        await unlink_werkdag_from_factuur(db, werkdag_id=wid)
    w = await get_werkdag_by_id(db, werkdag_id=wid)
    assert w.factuurnummer == '2026-001'  # ongewijzigd


@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_rejects_betaald(db):
    """Betaalde factuur — ontkoppelen ook geweigerd."""
    from database import (
        add_klant, add_werkdag, add_factuur,
        unlink_werkdag_from_factuur, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80,
        factuurnummer='2026-001')
    await add_factuur(
        db, nummer='2026-001', klant_id=kid, datum='2026-05-15',
        totaal_bedrag=640, status='betaald')
    with pytest.raises(ValueError, match='betaald'):
        await unlink_werkdag_from_factuur(db, werkdag_id=wid)


@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_rejects_no_factuurnummer(db):
    """Werkdag zonder factuurkoppeling → ValueError."""
    from database import (
        add_klant, add_werkdag, unlink_werkdag_from_factuur,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80)
    with pytest.raises(ValueError, match='niet gekoppeld'):
        await unlink_werkdag_from_factuur(db, werkdag_id=wid)


@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_rejects_missing_werkdag(db):
    from database import unlink_werkdag_from_factuur
    with pytest.raises(ValueError, match='99999'):
        await unlink_werkdag_from_factuur(db, werkdag_id=99999)
```

In `tests/test_year_locking.py`:

```python
# Voeg toe in import-blok:
#     unlink_werkdag_from_factuur,

@pytest.mark.asyncio
async def test_unlink_werkdag_rejected_in_definitief_year(db):
    """Year-lock op werkdag.datum: definitief jaar weigert unlink."""
    from database import (
        add_klant, add_werkdag, add_factuur,
        unlink_werkdag_from_factuur, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2024)
    wid = await add_werkdag(
        db, datum='2024-12-15', klant_id=kid, uren=8, tarief=80,
        factuurnummer='2024-099')
    await add_factuur(
        db, nummer='2024-099', klant_id=kid, datum='2024-12-15',
        totaal_bedrag=640, status='concept')
    await update_jaarafsluiting_status(db, 2024, 'definitief')

    with pytest.raises(YearLockedError, match='2024'):
        await unlink_werkdag_from_factuur(db, werkdag_id=wid)
    w = await get_werkdag_by_id(db, werkdag_id=wid)
    assert w.factuurnummer == '2024-099'  # ongewijzigd
```

- [ ] **Step 2: Run tests, verify FAIL**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py -k "unlink_werkdag" tests/test_year_locking.py -k "unlink_werkdag" -v
```
Expected: ImportError op `unlink_werkdag_from_factuur`.

- [ ] **Step 3: Implementeer helper**

In `database.py`, na `duplicate_werkdag`:

```python
async def unlink_werkdag_from_factuur(
        db_path: Path = DB_PATH, werkdag_id: int = 0) -> None:
    """Atomair een werkdag loskoppelen van zijn factuur.

    Toegestaan alleen voor orphan-link (factuur_id IS NULL) of een
    concept-factuur. `BEGIN IMMEDIATE` rond SELECT-status + UPDATE
    werkdagen sluit race af tussen status-check en de update — anders
    kon een tussentijds verstuurde factuur alsnog losgekoppeld worden.

    Year-lock guard via assert_year_writable op werkdag.datum (volgt
    bestaand pattern in helpers).

    Raises:
        ValueError: werkdag bestaat niet, geen factuurkoppeling, of
            factuur is verstuurd/verlopen/betaald (alleen concept en
            orphan toegestaan).
        YearLockedError: werkdag.datum in definitief jaar.
    """
    async with get_db_ctx(db_path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            cur = await conn.execute(
                "SELECT w.datum, w.factuurnummer, "
                "       f.id AS factuur_id, f.status AS factuur_status "
                "FROM werkdagen w "
                "LEFT JOIN facturen f ON w.factuurnummer = f.nummer "
                "WHERE w.id = ?", (werkdag_id,))
            row = await cur.fetchone()
            if row is None:
                await conn.rollback()
                raise ValueError(f"Werkdag {werkdag_id} bestaat niet")
            if not row['factuurnummer']:
                await conn.rollback()
                raise ValueError(
                    "Werkdag is niet gekoppeld aan een factuur")
            factuur_id = row['factuur_id']
            factuur_status = (row['factuur_status'] or '')
            if factuur_id is not None and factuur_status != 'concept':
                await conn.rollback()
                raise ValueError(
                    f"Factuur is '{factuur_status}'; ontkoppelen is "
                    f"alleen toegestaan bij concept-facturen of orphan-"
                    f"links (factuur ontbreekt)")
            await assert_year_writable(db_path, row['datum'])
            await conn.execute(
                "UPDATE werkdagen SET factuurnummer = '' WHERE id = ?",
                (werkdag_id,))
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
```

- [ ] **Step 4: Run tests, verify PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py -k "unlink_werkdag" tests/test_year_locking.py -k "unlink_werkdag" -v
```
Expected: alle unlink-tests passed.

---

## Task 6: Pure helper `_pill_context_actions` — visibility-matrix

**Files:**
- Modify: `pages/agenda.py` (add helper)
- Test: `tests/test_agenda_pure_helpers.py`

- [ ] **Step 1: Schrijf 8-scenario test**

Voeg toe in `tests/test_agenda_pure_helpers.py`:

```python
# === _pill_context_actions visibility-matrix ===

def _make_pill(*, factuurnummer='', factuur_id=None, factuur_status='',
               status_label='ongefactureerd'):
    """Stub-pill met alleen velden die _pill_context_actions leest."""
    class P:
        pass
    p = P()
    p.factuurnummer = factuurnummer
    p.factuur_id = factuur_id
    p.factuur_status = factuur_status
    p.status_label = status_label
    return p


def test_pill_actions_ongefactureerd():
    """Geen factuur → bewerken/dupliceren/verwijderen toegestaan."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill()
    assert _pill_context_actions(pill) == ['edit', 'duplicate', 'delete']


def test_pill_actions_factuur_concept():
    """Concept-factuur → ontkoppel + naar facturen, geen verwijderen."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2026-001', factuur_id=10,
        factuur_status='concept', status_label='concept')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'naar_facturen', 'ontkoppel']


def test_pill_actions_factuur_verstuurd():
    """Verstuurd → alleen naar_facturen, geen ontkoppel/delete."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2026-001', factuur_id=10,
        factuur_status='verstuurd', status_label='verstuurd')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'naar_facturen']


def test_pill_actions_factuur_verstuurd_overdue():
    """Verlopen = verstuurd + vervaldatum<today → zelfde acties als verstuurd."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2026-001', factuur_id=10,
        factuur_status='verstuurd', status_label='verlopen')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'naar_facturen']


def test_pill_actions_factuur_betaald():
    """Betaald → alleen naar_facturen, géén ontkoppel."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2026-001', factuur_id=10,
        factuur_status='betaald', status_label='betaald')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'naar_facturen']


def test_pill_actions_orphan_factuurnummer():
    """factuurnummer != '' maar factuur_id is None → ontkoppel toegestaan."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2025-999', factuur_id=None,
        factuur_status='', status_label='ongefactureerd')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'ontkoppel']


def test_pill_actions_unknown_factuur_status_defensive():
    """Onbekende status → alleen naar_facturen, geen delete/ontkoppel."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='2026-001', factuur_id=10,
        factuur_status='something_weird', status_label='gefactureerd')
    assert _pill_context_actions(pill) == [
        'edit', 'duplicate', 'naar_facturen']


def test_pill_actions_no_factuur_no_orphan():
    """factuurnummer='' + factuur_id=None → standaard ongefactureerd-pad."""
    from pages.agenda import _pill_context_actions
    pill = _make_pill(
        factuurnummer='', factuur_id=None,
        factuur_status='', status_label='ongefactureerd')
    assert _pill_context_actions(pill) == ['edit', 'duplicate', 'delete']
```

- [ ] **Step 2: Run tests, verify FAIL**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_pure_helpers.py -k "pill_actions" -v
```
Expected: ImportError op `_pill_context_actions`.

- [ ] **Step 3: Implementeer helper**

In `pages/agenda.py`, direct na `_pill_color_style` (rond regel 62):

```python
def _pill_context_actions(pill) -> list[str]:
    """Pure helper: geeft action-IDs terug voor right-click context-menu
    op een confirmed werkdag-pill.

    Action-IDs zijn stabiele strings (renderer mapt naar labels/icons/
    callbacks). Volgorde is deterministic.

    Visibility-rules (zie spec 2026-05-08-agenda-sprint-1-design.md §C):
    - edit, duplicate: altijd
    - delete: alleen als geen factuurnummer
    - naar_facturen: alleen als factuur_id != None
    - ontkoppel: alleen bij concept of orphan-link
        (factuurnummer != '' EN (factuur_id is None OF
         factuur_status == 'concept'))

    Onbekende factuur_status met factuur_id != None gedraagt zich
    defensief: wel naar_facturen, geen ontkoppel/delete.
    """
    actions = ['edit', 'duplicate']
    has_factuurnummer = bool(getattr(pill, 'factuurnummer', '') or '')
    factuur_id = getattr(pill, 'factuur_id', None)
    factuur_status = getattr(pill, 'factuur_status', '') or ''

    if not has_factuurnummer:
        actions.append('delete')
        return actions

    # Heeft factuurnummer.
    if factuur_id is not None:
        actions.append('naar_facturen')

    # Ontkoppel: orphan (factuur_id None) OF concept-factuur.
    if factuur_id is None or factuur_status == 'concept':
        actions.append('ontkoppel')

    return actions
```

- [ ] **Step 4: Run tests, verify PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_pure_helpers.py -k "pill_actions" -v
```
Expected: 8 passed.

---

## Task 7: Pure helper `_pill_tooltip` — formatter

**Files:**
- Modify: `pages/agenda.py` (add helper)
- Test: `tests/test_agenda_pure_helpers.py`

- [ ] **Step 1: Schrijf 4-scenario test**

```python
# === _pill_tooltip formatter ===

def test_pill_tooltip_ongefactureerd():
    """Ongefactureerd: geen factuurnummer in tooltip."""
    from pages.agenda import _pill_tooltip
    pill = _make_pill(status_label='ongefactureerd')
    pill.klant_naam = 'Huisartsenpraktijk \'t Ouddiep'
    pill.uren = 9.5
    pill.bedrag = 754.92
    pill.factuurnummer = ''
    text = _pill_tooltip(pill)
    assert "Huisartsenpraktijk 't Ouddiep" in text
    assert '9.5u' in text
    assert '754,92' in text
    assert 'ongefactureerd' in text
    assert 'Factuur' not in text
    assert 'concept-factuur' not in text


def test_pill_tooltip_concept():
    """Concept-status toont 'concept-factuur {nummer}'."""
    from pages.agenda import _pill_tooltip
    pill = _make_pill(status_label='concept')
    pill.klant_naam = 'S. Borgemeester'
    pill.uren = 8.0
    pill.bedrag = 1344.84
    pill.factuurnummer = '2026-024'
    text = _pill_tooltip(pill)
    assert 'concept-factuur 2026-024' in text


def test_pill_tooltip_betaald():
    """Verstuurd/verlopen/betaald tonen 'Factuur {nummer}'."""
    from pages.agenda import _pill_tooltip
    pill = _make_pill(status_label='betaald')
    pill.klant_naam = 'M. Zwart'
    pill.uren = 9.0
    pill.bedrag = 417.60
    pill.factuurnummer = '2026-027'
    text = _pill_tooltip(pill)
    assert '· Factuur 2026-027' in text
    assert 'concept-factuur' not in text


def test_pill_tooltip_verstuurd_includes_factuur():
    from pages.agenda import _pill_tooltip
    pill = _make_pill(status_label='verstuurd')
    pill.klant_naam = 'Klant'
    pill.uren = 8.0
    pill.bedrag = 837.42
    pill.factuurnummer = '2026-031'
    text = _pill_tooltip(pill)
    assert '· Factuur 2026-031' in text
```

- [ ] **Step 2: Run tests, verify FAIL**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_pure_helpers.py -k "pill_tooltip" -v
```
Expected: ImportError op `_pill_tooltip`.

- [ ] **Step 3: Implementeer helper**

In `pages/agenda.py`, direct na `_pill_context_actions`:

```python
def _pill_tooltip(pill) -> str:
    """Pure helper: tooltip-tekst voor confirmed werkdag-pill.

    Format:
        {klant_naam_volledig}
        {uren:.1f}u · €{bedrag:,.2f}
        Status: {status_label}{factuur_extra}

    Factuur-extra:
        - concept → " · concept-factuur {nummer}"
        - verstuurd/verlopen/betaald → " · Factuur {nummer}"
        - ongefactureerd → ""

    Geen tijden — werkdagen-tabel slaat geen start/eind times op
    (spec §D: schema-change buiten Sprint 1).
    """
    klant = getattr(pill, 'klant_naam', '') or ''
    uren = float(getattr(pill, 'uren', 0) or 0)
    bedrag = float(getattr(pill, 'bedrag', 0) or 0)
    status = getattr(pill, 'status_label', '') or ''
    factuurnummer = getattr(pill, 'factuurnummer', '') or ''

    bedrag_fmt = f'{bedrag:,.2f}'.replace(',', 'X').replace('.', ',') \
        .replace('X', '.')

    factuur_extra = ''
    if factuurnummer:
        if status == 'concept':
            factuur_extra = f' · concept-factuur {factuurnummer}'
        elif status in ('verstuurd', 'verlopen', 'betaald'):
            factuur_extra = f' · Factuur {factuurnummer}'

    return (
        f'{klant}\n'
        f'{uren:.1f}u · €{bedrag_fmt}\n'
        f'Status: {status}{factuur_extra}'
    )
```

- [ ] **Step 4: Run tests, verify PASS**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_pure_helpers.py -k "pill_tooltip" -v
```
Expected: 4 passed.

---

## Task 8: Pill UI — left-click + tooltip + context-menu rendering

**Files:**
- Modify: `pages/agenda.py:_render_month_grid` (regel 165-172) — pill rendering loop
- Modify: `pages/agenda.py:agenda_page` — add `handle_edit_pill`, `handle_duplicate_pill`, `handle_delete_pill`, `handle_ontkoppel_pill`, `handle_naar_facturen_pill` callbacks + pass via `on_*` parameters

Dit is een grote integratie-task — opgesplitst in 4 sub-stappen.

- [ ] **Step 1: Modify `_render_month_grid` signature + pill rendering**

Vervang in `pages/agenda.py` de signature van `_render_month_grid` (regel 64) en voeg `on_pill_*` callbacks toe:

```python
def _render_month_grid(container, view, on_day_click, selected: date,
                        gebruik_klant_kleur: bool = False,
                        on_pill_edit=None, on_pill_duplicate=None,
                        on_pill_delete=None, on_pill_ontkoppel=None,
                        on_pill_naar_facturen=None) -> None:
    """Render 6×7 day grid + week-summary kolom rechts.

    on_pill_*: callbacks voor confirmed pill-acties. None → geen handler
    (test/legacy fallback). Expected pills krijgen geen pill-handlers —
    bubblen naar cell-click voor Day-Inspector flow.
    """
```

Vervang in dezelfde functie de pill-rendering loop (regel 151-172) — alleen de `for pill in all_pills[:3]:` block:

```python
                            for pill in all_pills[:3]:
                                pill_classes = ['wd-pill', f'wd-{pill.category}']
                                # ExpectedEntry has pattern_id; WerkdagPill
                                # does not — distinguish via attribute presence.
                                is_expected = hasattr(pill, 'pattern_id')
                                if is_expected:
                                    pill_classes.append('expected')
                                pill_style = _pill_color_style(
                                    getattr(pill, 'klant_color', None),
                                    gebruik_klant_kleur,
                                )
                                pill_el = ui.element('div').classes(
                                    ' '.join(pill_classes)
                                ).style(pill_style)
                                with pill_el:
                                    klant_short = pill.klant_naam[:10]
                                    ui.label(
                                        f'{klant_short} {pill.uren:.1f}u'
                                    )
                                    # Tooltip + click + context-menu alleen
                                    # voor confirmed pills (NIET expected).
                                    if not is_expected:
                                        tooltip_text = _pill_tooltip(pill)
                                        ui.tooltip(tooltip_text)
                                        if on_pill_edit is not None:
                                            wid = pill.id
                                            pill_el.on(
                                                'click',
                                                lambda _e=None,
                                                       w=wid: on_pill_edit(w),
                                                js_handler=(
                                                    '(e) => { '
                                                    'e.stopPropagation(); '
                                                    'emit(); }'),
                                            )
                                        # Context-menu (right-click)
                                        action_ids = _pill_context_actions(pill)
                                        with ui.context_menu():
                                            for aid in action_ids:
                                                _render_context_menu_item(
                                                    aid, pill,
                                                    on_pill_edit,
                                                    on_pill_duplicate,
                                                    on_pill_delete,
                                                    on_pill_ontkoppel,
                                                    on_pill_naar_facturen,
                                                )
```

- [ ] **Step 2: Add `_render_context_menu_item` helper**

Voeg toe in `pages/agenda.py`, direct na `_pill_tooltip`:

```python
_CTX_MENU_LABELS = {
    'edit': 'Bewerken',
    'duplicate': 'Dupliceren',
    'delete': 'Verwijderen',
    'naar_facturen': 'Naar facturen',
    'ontkoppel': 'Ontkoppel factuur',
}


def _render_context_menu_item(action_id, pill, on_edit, on_duplicate,
                              on_delete, on_ontkoppel, on_naar_facturen):
    """Render één q-item in de pill context-menu, gemapt op action_id.

    NiceGUI 3.8.0 `ui.menu_item(text, on_click=..., auto_close=True)`
    rendert als clickable q-item met v-close-popup. Geen icon — Sprint 1
    KISS, plain text labels matchen de minimalistische agenda-pill UI.
    """
    label = _CTX_MENU_LABELS[action_id]
    handler_map = {
        'edit': on_edit,
        'duplicate': on_duplicate,
        'delete': on_delete,
        'ontkoppel': on_ontkoppel,
        'naar_facturen': on_naar_facturen,
    }
    handler = handler_map[action_id]
    if handler is None:
        return
    if action_id == 'naar_facturen':
        arg = getattr(pill, 'factuur_id', None)
    else:
        arg = pill.id
    ui.menu_item(label, on_click=lambda _e=None, a=arg: handler(a))
```

- [ ] **Step 3: Wire callbacks in `agenda_page` + `render()`**

In `pages/agenda.py:agenda_page`, voeg tussen `handle_create_factuur` en `async def render()` toe:

```python
    async def handle_pill_edit(werkdag_id):
        from database import get_werkdag_by_id
        from components.werkdag_form import open_werkdag_dialog
        w = await get_werkdag_by_id(DB_PATH, werkdag_id=werkdag_id)
        if w is None:
            ui.notify('Werkdag niet gevonden', type='warning')
            return
        await open_werkdag_dialog(on_save=render, werkdag=w)

    async def handle_pill_duplicate(werkdag_id):
        from database import get_werkdag_by_id, duplicate_werkdag
        from components.shared_ui import date_input
        w = await get_werkdag_by_id(DB_PATH, werkdag_id=werkdag_id)
        if w is None:
            ui.notify('Werkdag niet gevonden', type='warning')
            return
        # Default-target: bron-datum + 7 dagen.
        try:
            src_d = date.fromisoformat(w.datum)
            default_target = (src_d + timedelta(days=7)).isoformat()
        except (ValueError, TypeError):
            default_target = date.today().isoformat()

        with ui.dialog() as dlg, ui.card():
            ui.label(
                f'Werkdag van {w.datum} ({w.klant_naam}) dupliceren'
            ).classes('text-base font-medium')
            target = date_input(
                'Naar datum', value=default_target,
            )
            with ui.row().classes('justify-end gap-2 mt-3'):
                ui.button('Annuleren', on_click=lambda: dlg.submit(None)) \
                    .props('flat')
                ui.button('Dupliceren',
                          on_click=lambda: dlg.submit(target.value)) \
                    .props('color=primary')
        result = await dlg
        if not result:
            return
        try:
            await duplicate_werkdag(
                DB_PATH, werkdag_id=werkdag_id, target_datum=result)
            ui.notify('Werkdag gedupliceerd', type='positive')
            await render()
        except YearLockedError as ex:
            ui.notify(str(ex), type='warning')
        except ValueError as ex:
            ui.notify(f'Dupliceren mislukt: {ex}', type='negative')

    async def handle_pill_delete(werkdag_id):
        from database import (
            get_werkdag_by_id, delete_werkdag, YearLockedError,
        )
        w = await get_werkdag_by_id(DB_PATH, werkdag_id=werkdag_id)
        if w is None:
            ui.notify('Werkdag niet gevonden', type='warning')
            return
        with ui.dialog() as dlg, ui.card():
            ui.label(
                f'Werkdag van {w.datum} bij {w.klant_naam} '
                f'verwijderen?'
            ).classes('text-base')
            with ui.row().classes('justify-end gap-2 mt-3'):
                ui.button('Annuleren',
                          on_click=lambda: dlg.submit(False)).props('flat')
                ui.button('Verwijderen',
                          on_click=lambda: dlg.submit(True)) \
                    .props('color=negative')
        if not await dlg:
            return
        try:
            await delete_werkdag(DB_PATH, werkdag_id=werkdag_id)
            ui.notify('Werkdag verwijderd', type='positive')
            await render()
        except YearLockedError as ex:
            ui.notify(str(ex), type='warning')
        except ValueError as ex:
            ui.notify(str(ex), type='negative')

    async def handle_pill_ontkoppel(werkdag_id):
        # Pre-dialog refetch is alleen voor de UI-tekst (welk factuur-
        # nummer, orphan of concept). De ECHTE check-and-update gebeurt
        # atomair in `unlink_werkdag_from_factuur` (BEGIN IMMEDIATE),
        # zodat een race tijdens dialog-wachttijd (factuur wordt elders
        # verstuurd) niet leidt tot onterecht ontkoppelen.
        from database import (
            unlink_werkdag_from_factuur, get_db_ctx, YearLockedError,
        )
        async with get_db_ctx(DB_PATH) as conn:
            cur = await conn.execute(
                "SELECT w.factuurnummer, "
                "       f.id AS factuur_id, f.status AS factuur_status "
                "FROM werkdagen w "
                "LEFT JOIN facturen f ON w.factuurnummer = f.nummer "
                "WHERE w.id = ?", (werkdag_id,))
            row = await cur.fetchone()
        if row is None:
            ui.notify('Werkdag niet gevonden', type='warning')
            return
        if not row['factuurnummer']:
            ui.notify('Werkdag is niet gekoppeld aan een factuur',
                      type='info')
            return
        is_orphan = row['factuur_id'] is None
        # Fast-fail bij stale UI: status veranderde tussen render en klik.
        # Dit voorkomt een misleidende "concept-factuur"-dialog terwijl
        # de helper toch zou weigeren. De atomic helper blijft de echte
        # gate (post-dialog race wordt daar afgevangen).
        if not is_orphan and (row['factuur_status'] or '') != 'concept':
            ui.notify(
                f"Factuur is '{row['factuur_status']}'; ontkoppelen kan "
                f"alleen bij concept-facturen of orphan-links. "
                f"Refresh de agenda.", type='warning')
            await render()
            return
        factuur_descr = (
            f'orphan-factuurnummer {row["factuurnummer"]}'
            if is_orphan
            else f'concept-factuur {row["factuurnummer"]}'
        )
        with ui.dialog() as dlg, ui.card():
            ui.label(
                f'Werkdag wordt losgekoppeld van {factuur_descr}.'
            ).classes('text-base')
            ui.label(
                'De factuur en factuurregels blijven ongewijzigd. '
                'Je kunt de werkdag opnieuw koppelen of de factuur '
                'handmatig opschonen.'
            ).classes('text-sm text-slate-600 mt-2')
            with ui.row().classes('justify-end gap-2 mt-3'):
                ui.button('Annuleren',
                          on_click=lambda: dlg.submit(False)).props('flat')
                ui.button('Ontkoppel',
                          on_click=lambda: dlg.submit(True)) \
                    .props('color=warning')
        if not await dlg:
            return
        try:
            await unlink_werkdag_from_factuur(
                DB_PATH, werkdag_id=werkdag_id)
            ui.notify('Werkdag ontkoppeld', type='positive')
            await render()
        except YearLockedError as ex:
            ui.notify(str(ex), type='warning')
        except ValueError as ex:
            # Helper raised — bv. status veranderde tussen dialog en
            # bevestiging naar verstuurd/betaald.
            ui.notify(f'Ontkoppelen mislukt: {ex}', type='warning')

    def handle_pill_naar_facturen(_factuur_id):
        # Sprint 1: navigate generic. Deeplink (?nummer=…) is Sprint 2.
        ui.navigate.to('/facturen')
```

Voeg ook bovenaan `pages/agenda.py` import-blok `from datetime import date, timedelta` (al aanwezig); voeg `YearLockedError` toe aan database-import:

```python
from database import DB_PATH, get_bedrijfsgegevens, YearLockedError
```

- [ ] **Step 4: Pass callbacks aan `_render_month_grid` in `render()`**

In `render()` (rond regel 585) update de call:

```python
        _render_month_grid(
            refs['grid_container'], view,
            on_day_click=select_day,
            selected=state['selected'],
            gebruik_klant_kleur=gebruik_klant_kleur,
            on_pill_edit=lambda wid: ui.timer(
                0, lambda: handle_pill_edit(wid), once=True),
            on_pill_duplicate=lambda wid: ui.timer(
                0, lambda: handle_pill_duplicate(wid), once=True),
            on_pill_delete=lambda wid: ui.timer(
                0, lambda: handle_pill_delete(wid), once=True),
            on_pill_ontkoppel=lambda wid: ui.timer(
                0, lambda: handle_pill_ontkoppel(wid), once=True),
            on_pill_naar_facturen=handle_pill_naar_facturen,
        )
```

- [ ] **Step 5: Smoke-test test_agenda_page imports**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -c "import pages.agenda"
```
Expected: geen ImportError, geen syntax-error.

- [ ] **Step 6: UI source-pins op pill-render-loop slice**

Codex finding 4 (round 2) — losse string-checks zijn vals-groen omdat ze ook in commentaar/docstring kunnen staan. Beter: scope de check op de pill-render-loop slice tussen de bekende ankers `for pill in all_pills[:3]:` en `if len(all_pills) > 3:`.

Add in `tests/test_agenda_page.py`:

```python
def _render_loop_slice() -> str:
    """Return de pill-render-loop body uit pages/agenda.py.

    Slice tussen `for pill in all_pills[:3]:` (begin) en
    `if len(all_pills) > 3:` (overflow-handler) — alle pill-handler-
    code zit binnen deze regio.
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'pages' / 'agenda.py'
    text = src.read_text(encoding='utf-8')
    start = text.find('for pill in all_pills[:3]:')
    end = text.find('if len(all_pills) > 3:')
    assert start > 0 and end > start, (
        'render-loop ankers veranderd — update test')
    return text[start:end]


def test_pill_render_loop_uses_stop_propagation():
    """Pill click MUST call e.stopPropagation() — anders bubblet event
    naar cell-click en triggert day-select bovenop edit-dialog."""
    slice_text = _render_loop_slice()
    assert 'e.stopPropagation()' in slice_text


def test_pill_render_loop_uses_native_context_menu():
    """Right-click via ui.context_menu() (NiceGUI native), niet @contextmenu."""
    slice_text = _render_loop_slice()
    assert 'ui.context_menu()' in slice_text


def test_pill_render_loop_renders_tooltip():
    slice_text = _render_loop_slice()
    assert 'ui.tooltip(' in slice_text


def test_pill_handlers_only_under_is_expected_guard():
    """Tooltip + click + context-menu moeten ALLE drie ná `if not is_expected:`
    binnen de render-loop staan — anders krijgen expected pills (recurring)
    de handlers ook, wat het Day-Inspector-pad zou doorbreken.
    """
    slice_text = _render_loop_slice()
    guard_idx = slice_text.find('if not is_expected:')
    assert guard_idx > 0, "is_expected guard missing from render-loop"
    # Single-token markers (formatting-stable).
    for marker in ('ui.tooltip(', 'ui.context_menu()'):
        marker_idx = slice_text.find(marker)
        assert marker_idx > guard_idx, (
            f"{marker!r} appears before `if not is_expected:` — "
            f"expected pills would also get this handler")
    # Click-handler kan over meerdere regels gesplitst zijn (Black-formatting):
    #   pill_el.on(\n    'click', ...
    # Zoek `pill_el.on(` dan `'click'` daarna — niet als één string.
    on_idx = slice_text.find('pill_el.on(')
    assert on_idx > guard_idx, (
        "pill_el.on(...) appears before `if not is_expected:`")
    click_idx = slice_text.find("'click'", on_idx)
    assert click_idx > on_idx, (
        "pill_el.on(...) found but no 'click' arg after it")
```

Run:
```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_agenda_page.py -v
```
Expected: alle source-pin tests passed.

---

## Task 9: Volledige test-suite groen

**Files:**
- Run tests/

- [ ] **Step 1: Run hele suite + check exit code**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/
echo "EXIT=$?"
```

Expected: laatste regel toont `EXIT=0` (alle tests passed). Pin NIET op exact totaal-aantal — baseline drift met andere features. Quality-gate is "0 failed". Geen pipe naar `tail` — die maskeert pytest's exit code (codex finding 4).

Voor snelle scan-output kan `pytest tests/ -q` gebruikt worden, maar exit-code blijft de echte gate.

- [ ] **Step 2: Bij failure — diagnose en fix**

Als tests falen op `q-menu`/`ui.context_menu`-mocking issues: pure helpers zijn al getest (niet via NiceGUI runtime). Integratie-failures: verifieer NiceGUI 3.8.0 source op `ui.menu_item` vs `ui.item` API.

Geen sleep/retry-loops — fix root-cause.

---

## Task 10: Codex review op de diff

**Files:**
- Run codex against the diff

- [ ] **Step 1: Genereer diff + zend naar codex**

```
git diff HEAD -- database.py pages/agenda.py tests/ | env -u OPENAI_API_KEY codex exec --sandbox read-only - 2>&1 | tail -80
```

- [ ] **Step 2: Lees codex bevindingen**

Vergelijk tegen spec § C visibility-rules en § E duplicate_werkdag invarianten. Push back op false positives (specifiek: q-menu/$parent.$emit gotcha is voor q-btn-dropdown, niet ui.context_menu).

- [ ] **Step 3: Fix valide bevindingen + re-run pytest**

```
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/
echo "EXIT=$?"
```
Expected: `EXIT=0`.

---

## Task 11: Manual browser-verificatie (verplicht quality-gate)

**Files:**
- Geen — pure UI-test in pywebview

- [ ] **Step 1: Start app**

```
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py
```

- [ ] **Step 2: Doorloop verificatie per pill-type**

Op `/agenda`. Codex finding 9 — visibility verschilt per status, dus test de juiste actie op de juiste pill-type.

**Algemeen + bug-fix:**
1. Selecteer dag zonder werkdag. Klik toolbar "Nieuwe werkdag" → dialog opent met geselecteerde dag als default. Sluit zonder save.

**Op een ongefactureerde werkdag-pill** (bv. recente werkdag, geen factuurnummer):
2. Klik op pill → edit-dialog opent met werkdag-data. Day-selectie verandert NIET (verifieer dat kalender niet rerendert + Day-Inspector blijft op vorige dag).
3. Right-click → context-menu toont: **Bewerken / Dupliceren / Verwijderen**. Geen "Naar facturen", geen "Ontkoppel".
4. Bewerken → edit-dialog. Sluit.
5. Dupliceren → date-picker met bron+7d default, save → nieuwe pill verschijnt op target-datum.
6. Verwijderen → confirm-dialog "Werkdag van {datum} bij {klant} verwijderen?", confirm → werkdag weg, agenda re-rendered.

**Op een concept-factuur pill** (werkdag gekoppeld aan concept-factuur):
7. Right-click → context-menu toont: **Bewerken / Dupliceren / Naar facturen / Ontkoppel**. Geen "Verwijderen".
8. Naar facturen → navigeert naar /facturen.
9. Ontkoppel → confirm-dialog met expliciete tekst over factuur-regels die intact blijven. Confirm → factuurnummer wordt leeg.

**Op een verstuurde of betaalde factuur-pill:**
10. Right-click → context-menu toont: **Bewerken / Dupliceren / Naar facturen**. Geen "Verwijderen", geen "Ontkoppel" (boekhoudkundige consistentie — codex pushback).

**Op een orphan-pill** (factuurnummer gezet, factuur_id NULL — handmatig te creëren of zoek bestaande):
11. Right-click → context-menu toont: **Bewerken / Dupliceren / Ontkoppel**.

**Op een verwachte (recurring) pill**:
12. Right-click → géén context-menu verschijnt (huidig gedrag — expected pills bubblen naar cell-click → Day-Inspector).
13. Klik op expected pill → cell wordt geselecteerd, Day-Inspector toont "Bevestigen/Aanpassen" knoppen.

**Tooltip:**
14. Hover op confirmed pill → tooltip toont: klant volledige naam, uren, bedrag, status, en factuurnummer indien gefactureerd. Geen tijden (per spec).

- [ ] **Step 3: Bij UI-issue: documenteer + fix**

Geen "klaar"-rapportage zonder dat alle 7 stappen visueel bevestigd.

---

## Final Task: Diff-review + commit-decision

**Files:**
- Show diff to user

- [ ] **Step 1: Toon `git diff HEAD --stat`**

```
git diff HEAD --stat
```

- [ ] **Step 2: Toon volledige diff voor user-review**

```
git diff HEAD
```

- [ ] **Step 3: Vraag user-approval voor commit**

> "Implementatie + tests + manual-verificatie compleet. Diff hierboven. Wil je dat ik commit, of wil je eerst nog wijzigen?"

Bij approval:
```
git add database.py pages/agenda.py tests/test_agenda_page.py \
        tests/test_agenda_pure_helpers.py tests/test_database.py \
        tests/test_year_locking.py docs/superpowers/specs/2026-05-08-agenda-sprint-1-design.md \
        docs/superpowers/plans/2026-05-08-agenda-sprint-1.md
git commit -m "$(cat <<'EOF'
feat(agenda): klikbare pills + context-menu + duplicate/unlink + bug-fix Nieuwe werkdag

- Wire refs['new_btn'].on_click — bug-fix: knop deed niets
- Confirmed pill left-click → edit-dialog (met stopPropagation)
- Right-click context-menu: Bewerken/Dupliceren/Verwijderen/Naar facturen/Ontkoppel
  - Visibility-rules per factuur-status (concept/verstuurd/betaald/orphan)
- Pill hover-tooltip met klant/uren/bedrag/status/factuurnummer
- Nieuwe DB-helpers: get_werkdag_by_id, duplicate_werkdag (year-locked),
  unlink_werkdag_from_factuur (BEGIN IMMEDIATE + concept/orphan-only)
- Nieuwe tests: visibility-matrix, tooltip-formatter, helper-roundtrips,
  year-lock op duplicate + unlink, slice-based UI source-pins, bug-fix-pin

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
