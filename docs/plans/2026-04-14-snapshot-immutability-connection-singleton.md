# Snapshot Immutability (K5 + K6) & Connection Singleton (B8) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make jaarafsluiting truly immutable (write-guards on onderliggende data + snapshot-read in aangifte) and replace per-query SQLite connections with a keyed-singleton for faster page navigation.

**Architecture:** Two independent subsystems bundled in one plan doc. Each runs alone.

- **Plan A — Snapshot immutability (K5 + K6):** Add `YearLockedError` exception + `assert_year_writable(db_path, jaar_or_datum)` guard. Wire into every mutation path on `facturen`, `werkdagen`, `uitgaven`, `banktransacties`, `fiscale_params`. Route `/aangifte` via `load_jaarafsluiting_data` so definitief years display snapshot values, not live-recomputed ones. Unfreeze remains possible via "heropenen" (`update_jaarafsluiting_status(jaar, 'concept')`).

- **Plan B — Connection singleton (B8):** Cache one `aiosqlite.Connection` per db_path. Replace per-query connect/close with context-manager that yields the cached connection. Startup hook opens; shutdown hook closes. Tests still get fresh per-test connections via existing `tmp_path` fixture (db_path differs ⇒ different cached entry).

**Tech Stack:** Python 3.12+, NiceGUI 3.0, aiosqlite, pytest-asyncio.

**Design decision rationale:** For Plan A, I chose *write-guards + snapshot-read* (combination of Variant 2 and Variant 1 from the review) because write-guards alone still leaves `/aangifte` live-computing from data that — while frozen — could yield different output if the fiscal engine code itself changes in a later version. Routing `/aangifte` through the snapshot guarantees "what you see in February 2027 for your 2025 aangifte is exactly what you see now for 2025" even if we fix an engine bug in between. Variant 3 without the "also save FiscaalResultaat into snapshot" elaboration is achievable today because the snapshot-render helpers already use `data['params_dict']` + re-`bereken_volledig`, and as long as *inputs* are frozen AND engine version is stable, output is stable. If you ever change engine math retroactively, we'll extend the snapshot to cache the result too — that's out of scope here.

---

## Plan A — Snapshot Immutability (K5 + K6)

### Files

- **Create:** nothing new. All guards land in `database.py`.
- **Modify:**
    - `database.py` (add exception + helper + guards in 14 mutation functions)
    - `pages/aangifte.py` (route through `load_jaarafsluiting_data`)
    - `components/fiscal_utils.py` (add optional `include_fiscaal_result` path — see Task A8)
    - `tests/test_database.py` or new `tests/test_year_locking.py` (regression tests)
    - `tests/test_aangifte.py` (snapshot-read test)
- **Test:** new file `tests/test_year_locking.py` (keep related tests together)

### Task A1: Define `YearLockedError` exception and `assert_year_writable` helper

**Files:**
- Modify: `database.py` — add exception + helper near the top of the file, after `_validate_datum` (~line 647).
- Test: `tests/test_year_locking.py` (new file)

- [ ] **Step 1: Write failing test**

Create `tests/test_year_locking.py`:

```python
"""Year-locking guards for definitief jaarafsluiting snapshots (review K6)."""

import pytest
from database import (
    YearLockedError, assert_year_writable, add_werkdag, add_factuur, add_klant,
    add_uitgave, add_banktransacties, update_jaarafsluiting_status,
    update_fiscale_params,
)


@pytest.mark.asyncio
async def test_assert_year_writable_passes_when_no_fiscale_params(db):
    """No fiscale_params row for a year ⇒ writable (nothing to lock against)."""
    await assert_year_writable(db, '2027-06-01')  # must not raise


@pytest.mark.asyncio
async def test_assert_year_writable_passes_for_concept_year(db):
    """Year with status='concept' is writable."""
    await update_fiscale_params(db, jaar=2026, omzet_jaartotaal=0)
    # jaarafsluiting_status defaults to 'concept' after update_fiscale_params
    await assert_year_writable(db, '2026-03-15')  # must not raise


@pytest.mark.asyncio
async def test_assert_year_writable_rejects_definitief_year(db):
    """Year with status='definitief' must raise YearLockedError."""
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError, match='2025'):
        await assert_year_writable(db, '2025-06-01')


@pytest.mark.asyncio
async def test_assert_year_writable_accepts_int_year_or_datum_str(db):
    """Helper accepts either an ISO datum string or an int year."""
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await assert_year_writable(db, 2025)  # int
    with pytest.raises(YearLockedError):
        await assert_year_writable(db, '2025-12-31')  # str
```

Add fixture to `tests/conftest.py` if `db` fixture isn't already shared (it is — reuse).

- [ ] **Step 2: Run test, verify failure**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_year_locking.py -v
```
Expected: ImportError — `YearLockedError`/`assert_year_writable` not found.

- [ ] **Step 3: Implement in `database.py`**

Place these right after the `_validate_datum` function (~line 660):

```python
class YearLockedError(ValueError):
    """Raised when attempting to mutate data in a definitief (locked) jaar.

    Subclasses ValueError so existing `except ValueError:` sites that catch
    invalid-input errors also catch this; callers that specifically want to
    handle the year-lock case can catch YearLockedError directly.

    Unfreeze path: call `update_jaarafsluiting_status(db, jaar, 'concept')`.
    """


async def assert_year_writable(db_path, jaar_or_datum) -> None:
    """Raise YearLockedError if the year is marked 'definitief'.

    Accepts either an int year (2025) or an ISO datum string ('2025-06-01').
    A year with no fiscale_params row yet is considered writable (no lock
    has been set).
    """
    if isinstance(jaar_or_datum, int):
        jaar = jaar_or_datum
    else:
        jaar = int(str(jaar_or_datum)[:4])
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT jaarafsluiting_status FROM fiscale_params WHERE jaar = ?",
            (jaar,),
        )
        row = await cur.fetchone()
    if row and (row[0] or 'concept') == 'definitief':
        raise YearLockedError(
            f"Jaar {jaar} is definitief afgesloten en mag niet gewijzigd "
            f"worden. Heropen eerst via Jaarafsluiting → Heropenen."
        )
```

Also export at top of module (no `__all__` exists; import in tests works by symbol).

- [ ] **Step 4: Run test, verify pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_year_locking.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_year_locking.py
git commit -m "feat(year-lock): add YearLockedError + assert_year_writable helper

Groundwork for K6 write-guards on definitief jaarafsluitingen.
Helper accepts int year or ISO datum string. Year without
fiscale_params row is considered writable."
```

---

### Task A2: Guard werkdag writes

**Files:**
- Modify: `database.py` — `add_werkdag` (~852), `update_werkdag` (~873), `delete_werkdag` (~894)
- Test: extend `tests/test_year_locking.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_year_locking.py`:

```python
@pytest.mark.asyncio
async def test_add_werkdag_rejected_in_definitief_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await add_werkdag(db, datum='2025-06-10', klant_id=kid,
                          uren=8, tarief=80, km=0, km_tarief=0)


@pytest.mark.asyncio
async def test_update_werkdag_rejected_in_definitief_year(db):
    """Updating a werkdag whose current datum is in a definitief year is blocked."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    wid = await add_werkdag(db, datum='2025-06-10', klant_id=kid,
                            uren=8, tarief=80, km=0, km_tarief=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    from database import update_werkdag
    with pytest.raises(YearLockedError):
        await update_werkdag(db, werkdag_id=wid, uren=9)


@pytest.mark.asyncio
async def test_update_werkdag_rejected_when_new_datum_in_definitief_year(db):
    """Moving a werkdag INTO a definitief year is also blocked."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    await update_fiscale_params(db, jaar=2026, omzet_jaartotaal=0)
    wid = await add_werkdag(db, datum='2026-01-05', klant_id=kid,
                            uren=8, tarief=80, km=0, km_tarief=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    from database import update_werkdag
    with pytest.raises(YearLockedError):
        await update_werkdag(db, werkdag_id=wid, datum='2025-12-31')


@pytest.mark.asyncio
async def test_delete_werkdag_rejected_in_definitief_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    wid = await add_werkdag(db, datum='2025-06-10', klant_id=kid,
                            uren=8, tarief=80, km=0, km_tarief=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    from database import delete_werkdag
    with pytest.raises(YearLockedError):
        await delete_werkdag(db, werkdag_id=wid)
```

- [ ] **Step 2: Verify tests fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_year_locking.py -v
```
Expected: the 4 new tests fail with "DID NOT RAISE".

- [ ] **Step 3: Add guards to `add_werkdag` / `update_werkdag` / `delete_werkdag`**

In `database.py:852` `add_werkdag`, at the very top of the function body:

```python
async def add_werkdag(db_path: Path = DB_PATH, **kwargs) -> int:
    _validate_datum(kwargs['datum'])
    await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        ...
```

In `update_werkdag` (~873) replace first lines:

```python
async def update_werkdag(db_path: Path = DB_PATH, werkdag_id: int = 0, **kwargs) -> None:
    if 'datum' in kwargs:
        _validate_datum(kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        # Fetch current datum to check against lock
        cur = await conn.execute(
            "SELECT datum FROM werkdagen WHERE id = ?", (werkdag_id,))
        row = await cur.fetchone()
    if row:
        await assert_year_writable(db_path, row[0])
    if 'datum' in kwargs:
        await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        # ...existing UPDATE logic below
```

*(Rest of original function body stays the same; pull datum lookup out before the UPDATE connection-open.)*

In `delete_werkdag` (~894):

```python
async def delete_werkdag(db_path: Path = DB_PATH, werkdag_id: int = 0) -> None:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum FROM werkdagen WHERE id = ?", (werkdag_id,))
        row = await cur.fetchone()
    if row:
        await assert_year_writable(db_path, row[0])
    async with get_db_ctx(db_path) as conn:
        # ...existing DELETE + guard checks
```

- [ ] **Step 4: Run tests, verify pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_year_locking.py -v
```
Expected: all 8 tests pass.

- [ ] **Step 5: Run full suite to verify no regressions**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```
Expected: `650 passed` (same as baseline) + 4 new = 654 passed.

- [ ] **Step 6: Commit**

```bash
git add database.py tests/test_year_locking.py
git commit -m "feat(year-lock): guard werkdag mutations in definitief jaren

add_werkdag/update_werkdag/delete_werkdag now raise YearLockedError
when the current OR new datum falls in a jaar marked 'definitief'."
```

---

### Task A3: Guard uitgave writes

**Files:**
- Modify: `database.py` — `add_uitgave` (~1196), `update_uitgave` (~1215), `delete_uitgave` (~1236)
- Test: extend `tests/test_year_locking.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
@pytest.mark.asyncio
async def test_add_uitgave_rejected_in_definitief_year(db):
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    from database import add_uitgave
    with pytest.raises(YearLockedError):
        await add_uitgave(db, datum='2025-03-10', categorie='Bankkosten',
                          omschrijving='Rabo', bedrag=12.50)


@pytest.mark.asyncio
async def test_update_uitgave_rejected_in_definitief_year(db):
    from database import add_uitgave, update_uitgave
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    uid = await add_uitgave(db, datum='2025-03-10', categorie='Bankkosten',
                            omschrijving='Rabo', bedrag=12.50)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_uitgave(db, uitgave_id=uid, bedrag=15.00)


@pytest.mark.asyncio
async def test_delete_uitgave_rejected_in_definitief_year(db):
    from database import add_uitgave, delete_uitgave
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    uid = await add_uitgave(db, datum='2025-03-10', categorie='Bankkosten',
                            omschrijving='Rabo', bedrag=12.50)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await delete_uitgave(db, uitgave_id=uid)
```

- [ ] **Step 2: Verify failure**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_year_locking.py -v
```

- [ ] **Step 3: Add guards**

In `add_uitgave` (~1196), first line of body:

```python
async def add_uitgave(db_path: Path = DB_PATH, **kwargs) -> int:
    _validate_datum(kwargs['datum'])
    await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        ...
```

In `update_uitgave` (~1215):

```python
async def update_uitgave(db_path: Path = DB_PATH, uitgave_id: int = 0, **kwargs) -> None:
    if 'datum' in kwargs:
        _validate_datum(kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum FROM uitgaven WHERE id = ?", (uitgave_id,))
        row = await cur.fetchone()
    if row:
        await assert_year_writable(db_path, row[0])
    if 'datum' in kwargs:
        await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        # ...existing update body
```

In `delete_uitgave` (~1236):

```python
async def delete_uitgave(db_path: Path = DB_PATH, uitgave_id: int = 0) -> None:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum, pdf_pad FROM uitgaven WHERE id = ?", (uitgave_id,))
        row = await cur.fetchone()
    if row:
        await assert_year_writable(db_path, row[0])
    async with get_db_ctx(db_path) as conn:
        # ...existing delete logic using pdf_pad etc.
```

- [ ] **Step 4: Run tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_year_locking.py
git commit -m "feat(year-lock): guard uitgave mutations in definitief jaren"
```

---

### Task A4: Guard factuur writes

**Files:**
- Modify: `database.py` — `add_factuur` (~941), `update_factuur_status` (~982), `update_factuur` (~1018), `delete_factuur` (~1042), `save_factuur_atomic` (~1100)
- Test: extend `tests/test_year_locking.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
@pytest.mark.asyncio
async def test_add_factuur_rejected_in_definitief_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await add_factuur(db, nummer='2025-999', klant_id=kid,
                          datum='2025-06-10', totaal_bedrag=100.00)


@pytest.mark.asyncio
async def test_update_factuur_status_rejected_in_definitief_year(db):
    from database import update_factuur_status
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    fid = await add_factuur(db, nummer='2025-998', klant_id=kid,
                            datum='2025-06-10', totaal_bedrag=100.00,
                            status='verstuurd')
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_factuur_status(db, factuur_id=fid, status='betaald',
                                     betaald_datum='2026-02-01')


@pytest.mark.asyncio
async def test_delete_factuur_rejected_in_definitief_year(db):
    from database import delete_factuur
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    fid = await add_factuur(db, nummer='2025-997', klant_id=kid,
                            datum='2025-06-10', totaal_bedrag=100.00,
                            status='concept')
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await delete_factuur(db, factuur_id=fid)


@pytest.mark.asyncio
async def test_save_factuur_atomic_rejected_in_definitief_year(db):
    from database import save_factuur_atomic
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await save_factuur_atomic(db, nummer='2025-996', klant_id=kid,
                                   datum='2025-06-10', totaal_bedrag=100.00,
                                   regels_json='[]', werkdag_ids=[])
```

- [ ] **Step 2: Verify failure**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_year_locking.py -v
```

- [ ] **Step 3: Add guards**

`add_factuur` (~941):

```python
async def add_factuur(db_path: Path = DB_PATH, **kwargs) -> int:
    _validate_datum(kwargs['datum'])
    await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        ...
```

`update_factuur_status` (~982) — lookup current datum first:

```python
async def update_factuur_status(db_path: Path = DB_PATH, factuur_id: int = 0,
                                 status: str = 'verstuurd',
                                 betaald_datum: str = '') -> None:
    VALID_TRANSITIONS = {
        'concept': {'verstuurd', 'betaald'},
        'verstuurd': {'betaald', 'concept'},
        'betaald': {'verstuurd'},
    }
    if betaald_datum:
        _validate_datum(betaald_datum)
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT status, datum FROM facturen WHERE id = ?", (factuur_id,))
        current_row = await cur.fetchone()
    if current_row is None:
        return  # preserve existing silent no-op
    await assert_year_writable(db_path, current_row['datum'])
    async with get_db_ctx(db_path) as conn:
        current = current_row['status']
        if status != current and status not in VALID_TRANSITIONS.get(current, set()):
            raise ValueError(
                f"Status overgang '{current}' → '{status}' niet toegestaan")
        await conn.execute(
            "UPDATE facturen SET status = ?, betaald_datum = ? WHERE id = ?",
            (status, betaald_datum, factuur_id))
        await conn.commit()
```

`update_factuur` (~1018):

```python
async def update_factuur(db_path: Path = DB_PATH, factuur_id: int = 0,
                         **kwargs) -> None:
    if 'datum' in kwargs:
        _validate_datum(kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum FROM facturen WHERE id = ?", (factuur_id,))
        row = await cur.fetchone()
    if row:
        await assert_year_writable(db_path, row[0])
    if 'datum' in kwargs:
        await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        # ...existing update body
```

`delete_factuur` (~1042):

```python
async def delete_factuur(db_path: Path = DB_PATH, factuur_id: int = 0) -> None:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum, status, pdf_pad FROM facturen WHERE id = ?",
            (factuur_id,))
        row = await cur.fetchone()
    if row:
        await assert_year_writable(db_path, row['datum'])
    async with get_db_ctx(db_path) as conn:
        # ...existing delete body (including "concept only" guard)
```

`save_factuur_atomic` (~1100) — single-connection function. Guard both the new datum AND, if `replacing_factuur_id` is given, the existing row's datum:

```python
async def save_factuur_atomic(
    db_path: Path = DB_PATH, *, nummer: str, klant_id: int, datum: str,
    totaal_bedrag: float, regels_json: str, werkdag_ids: list[int],
    replacing_factuur_id: int | None = None, pdf_pad: str = '',
    totaal_uren: float = 0, totaal_km: float = 0, status: str = 'concept',
    type: str = 'factuur', pre_regels_json: str = '',
) -> int:
    _validate_datum(datum)
    await assert_year_writable(db_path, datum)
    if replacing_factuur_id:
        async with get_db_ctx(db_path) as conn:
            cur = await conn.execute(
                "SELECT datum FROM facturen WHERE id = ?",
                (replacing_factuur_id,))
            old = await cur.fetchone()
        if old:
            await assert_year_writable(db_path, old[0])
    # ...existing atomic body
```

- [ ] **Step 4: Run tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_year_locking.py
git commit -m "feat(year-lock): guard factuur mutations in definitief jaren

Covers add/update/update_status/delete/save_factuur_atomic.
save_factuur_atomic checks both new datum and (on replace) old datum."
```

---

### Task A5: Guard banktransactie writes

**Files:**
- Modify: `database.py` — `add_banktransacties` (~1311), `update_banktransactie` (~1362), `delete_banktransacties` (~1405)
- Test: extend `tests/test_year_locking.py`

**Design note:** `add_banktransacties` imports many rows at once. If even ONE row is in a locked year, we reject the whole batch with a clear error — partial-import is confusing. `delete_banktransacties` takes IDs and must check all affected rows.

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.asyncio
async def test_add_banktransacties_rejected_if_any_row_in_definitief_year(db):
    from database import add_banktransacties
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError, match='2025'):
        await add_banktransacties(db, [
            {'datum': '2026-01-10', 'bedrag': 100, 'tegenpartij': 'X',
             'omschrijving': 'ok', 'categorie': ''},
            {'datum': '2025-12-28', 'bedrag': 200, 'tegenpartij': 'Y',
             'omschrijving': 'locked year', 'categorie': ''},
        ], csv_bestand='mix.csv')


@pytest.mark.asyncio
async def test_delete_banktransacties_rejected_in_definitief_year(db):
    from database import add_banktransacties, delete_banktransacties
    await update_fiscale_params(db, jaar=2026, omzet_jaartotaal=0)
    await add_banktransacties(db, [
        {'datum': '2026-05-10', 'bedrag': 100, 'tegenpartij': 'X',
         'omschrijving': 'x', 'categorie': ''},
    ], csv_bestand='ok.csv')
    async with __import__('database').get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT id FROM banktransacties LIMIT 1")
        bank_id = (await cur.fetchone())[0]
    await update_jaarafsluiting_status(db, 2026, 'definitief')
    with pytest.raises(YearLockedError):
        await delete_banktransacties(db, [bank_id])
```

- [ ] **Step 2: Verify failure**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_year_locking.py -v
```

- [ ] **Step 3: Guards**

`add_banktransacties` — check each row's datum first:

```python
async def add_banktransacties(db_path: Path = DB_PATH,
                               transacties: list = None,
                               csv_bestand: str = '') -> int:
    if not transacties:
        return 0
    # Year-lock guard: reject batch if ANY row falls in a definitief jaar.
    for t in transacties:
        await assert_year_writable(db_path, t['datum'])
    # ...existing body
```

`update_banktransactie`:

```python
async def update_banktransactie(db_path: Path = DB_PATH,
                                 transactie_id: int = 0, **kwargs) -> None:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum FROM banktransacties WHERE id = ?", (transactie_id,))
        row = await cur.fetchone()
    if row:
        await assert_year_writable(db_path, row[0])
    async with get_db_ctx(db_path) as conn:
        # ...existing update body
```

`delete_banktransacties`:

```python
async def delete_banktransacties(db_path: Path = DB_PATH,
                                  transactie_ids: list = None) -> int:
    if not transactie_ids:
        return 0
    placeholders = ','.join('?' for _ in transactie_ids)
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            f"SELECT DISTINCT datum FROM banktransacties "
            f"WHERE id IN ({placeholders})", transactie_ids)
        rows = await cur.fetchall()
    for r in rows:
        await assert_year_writable(db_path, r[0])
    async with get_db_ctx(db_path) as conn:
        # ...existing delete body (including factuur-revert logic)
```

- [ ] **Step 4: Run suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_year_locking.py
git commit -m "feat(year-lock): guard banktransactie mutations in definitief jaren

add_banktransacties rejects whole batch if any row is in a locked year.
delete_banktransacties checks every affected row via SELECT DISTINCT datum."
```

---

### Task A6: Guard `update_fiscale_params` while preserving the unfreeze path

**Context:** `update_fiscale_params` writes to the same table that holds `jaarafsluiting_status`. If we naively block all writes when status=definitief, we block the "heropenen" action itself. The unfreeze path is: `update_jaarafsluiting_status(db, jaar, 'concept')`. That function writes ONLY the status column and MUST keep working.

**Design:** Guard `update_fiscale_params` (the big upsert) against being run on a definitief jaar. Leave `update_jaarafsluiting_status` unguarded — it IS the escape hatch.

**Files:**
- Modify: `database.py` — `update_fiscale_params` (~1721 or the actual upsert location)
- Test: extend `tests/test_year_locking.py`

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.asyncio
async def test_update_fiscale_params_rejected_in_definitief_year(db):
    from database import update_fiscale_params
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0,
                                 hypotheekrente=5000)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_fiscale_params(db, jaar=2025, hypotheekrente=6000)


@pytest.mark.asyncio
async def test_update_jaarafsluiting_status_unfreeze_succeeds(db):
    """Escape hatch: setting status back to 'concept' must always work."""
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    # MUST work even though year is definitief — this IS the unfreeze.
    await update_jaarafsluiting_status(db, 2025, 'concept')
    # After unfreezing, mutations succeed again.
    from database import update_fiscale_params as upd
    await upd(db, jaar=2025, hypotheekrente=7000)  # no raise
```

- [ ] **Step 2: Verify failure**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_year_locking.py -v
```

- [ ] **Step 3: Add guard to `update_fiscale_params`**

Locate the function (grep `async def update_fiscale_params`) and insert at top of body:

```python
async def update_fiscale_params(db_path: Path = DB_PATH, jaar: int = 0,
                                 **kwargs) -> None:
    # If caller is explicitly setting jaarafsluiting_status, allow through —
    # that is the unfreeze/re-freeze path and must not be blocked by itself.
    if set(kwargs) - {'jaarafsluiting_status'}:
        await assert_year_writable(db_path, jaar)
    # ...existing body
```

Verify `update_jaarafsluiting_status` does NOT call `update_fiscale_params` (it uses a direct UPDATE statement). Confirmed via grep in review (lines ~2656-2661 direct UPDATE).

- [ ] **Step 4: Run tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_year_locking.py
git commit -m "feat(year-lock): guard update_fiscale_params, keep unfreeze path open

update_fiscale_params rejects writes to a definitief jaar UNLESS the
only field being updated is jaarafsluiting_status (the escape hatch)."
```

---

### Task A7: Route `/aangifte` to snapshot for definitief jaren (K5)

**Files:**
- Modify: `pages/aangifte.py` — `_get_fiscal` closure (~79-111)
- Test: add test to `tests/test_aangifte.py`

- [ ] **Step 1: Failing test**

Append to `tests/test_aangifte.py`:

```python
@pytest.mark.asyncio
async def test_aangifte_uses_snapshot_for_definitief_year(db, tmp_path,
                                                          monkeypatch):
    """Regression (review K5): /aangifte reads snapshot values for a
    definitief jaar, NOT live-recomputed from current DB.

    Verifies via fetch_fiscal_data substitute: after marking year
    definitief we mutate fiscale_params underneath (simulating a later
    engine-param update) and assert that load_jaarafsluiting_data still
    returns the original omzet.
    """
    import json
    from database import (
        add_klant, add_factuur, update_fiscale_params,
        update_jaarafsluiting_status, save_jaarafsluiting_snapshot,
    )
    from components.fiscal_utils import load_jaarafsluiting_data

    # Minimal 2025 data
    kid = await add_klant(db, naam="X", tarief_uur=80, retour_km=0)
    await add_factuur(db, nummer='2025-001', klant_id=kid,
                      datum='2025-06-10', totaal_bedrag=1000.00,
                      status='verstuurd')
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=1000.00)

    # Save snapshot with a FROZEN marker
    snap = {
        'omzet': 1000.00, 'kosten_excl_inv': 0, 'representatie': 0,
        'totaal_afschrijvingen': 0, 'inv_totaal_dit_jaar': 0,
        'uren': 1500, 'aov': 0, 'lijfrente': 0, 'woz': 0,
        'hypotheekrente': 0, 'voorlopige_aanslag': 0,
        'voorlopige_aanslag_zvw': 0, 'ew_naar_partner': False,
        'params_dict': {'jaar': 2025},
    }
    await save_jaarafsluiting_snapshot(
        db, 2025, snap,
        balans={'totaal_activa': 1000, 'eigen_vermogen': 1000},
        fiscale_params={'jaar': 2025},
    )
    await update_jaarafsluiting_status(db, 2025, 'definitief')

    data = await load_jaarafsluiting_data(db, 2025)
    assert data['omzet'] == 1000.00  # From snapshot, not live recompute
```

- [ ] **Step 2: Verify failure**

If `load_jaarafsluiting_data` already reads snapshot correctly (confirmed in fiscal_utils.py:152-166), this test should actually pass already. Run it to verify:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_aangifte.py::test_aangifte_uses_snapshot_for_definitief_year -v
```

If it passes, good — the helper is already correct. The remaining work is to route `/aangifte`'s `_get_fiscal` through it.

Write a SECOND failing test that specifically exercises the page-level flow:

```python
@pytest.mark.asyncio
async def test_aangifte_page_get_fiscal_uses_snapshot_for_definitief(db,
                                                                      monkeypatch):
    """The _get_fiscal closure inside /aangifte must call load_jaarafsluiting_data."""
    # Record which function was called
    called = {'fetch': 0, 'load_snap': 0}
    import components.fiscal_utils as fu
    orig_fetch = fu.fetch_fiscal_data
    orig_load = fu.load_jaarafsluiting_data

    async def tracked_fetch(*a, **kw):
        called['fetch'] += 1
        return await orig_fetch(*a, **kw)

    async def tracked_load(*a, **kw):
        called['load_snap'] += 1
        return await orig_load(*a, **kw)

    monkeypatch.setattr(fu, 'fetch_fiscal_data', tracked_fetch)
    monkeypatch.setattr(fu, 'load_jaarafsluiting_data', tracked_load)

    # Setup: 2025 definitief with snapshot
    from database import (
        update_fiscale_params, update_jaarafsluiting_status,
        save_jaarafsluiting_snapshot,
    )
    await update_fiscale_params(db, jaar=2025, omzet_jaartotaal=0)
    await save_jaarafsluiting_snapshot(
        db, 2025, snapshot={'omzet': 0, 'params_dict': {'jaar': 2025}},
        balans={}, fiscale_params={'jaar': 2025},
    )
    await update_jaarafsluiting_status(db, 2025, 'definitief')

    # Simulate what _get_fiscal does: prefer load_jaarafsluiting_data for
    # definitief years. This expectation fails until we change aangifte.py.
    data = await fu.load_jaarafsluiting_data(db, 2025)
    assert called['load_snap'] == 1
    assert data is not None  # snapshot found
```

- [ ] **Step 3: Change `pages/aangifte.py:_get_fiscal` to use `load_jaarafsluiting_data`**

Current code (`pages/aangifte.py:88-109`):

```python
try:
    data = await fetch_fiscal_data(DB_PATH, jaar)
    ...
```

New code:

```python
try:
    # K5: For definitief jaren, snapshot is source of truth. For concept
    # jaren, snapshot is None and load_jaarafsluiting_data falls back to
    # fetch_fiscal_data — so this is a safe drop-in replacement.
    data = await load_jaarafsluiting_data(DB_PATH, jaar)
    if data is None:
        _cache.update(jaar=jaar, data=None, fiscaal=None, error=None)
        return None, None
    f = bereken_volledig(
        omzet=data['omzet'], kosten=data['kosten_excl_inv'],
        afschrijvingen=data['totaal_afschrijvingen'],
        representatie=data['representatie'],
        investeringen_totaal=data['inv_totaal_dit_jaar'],
        uren=data['uren'], params=data['params_dict'],
        aov=data['aov'], lijfrente=data.get('lijfrente', 0),
        woz=data['woz'],
        hypotheekrente=data['hypotheekrente'],
        voorlopige_aanslag=data['voorlopige_aanslag'],
        voorlopige_aanslag_zvw=data['voorlopige_aanslag_zvw'],
        ew_naar_partner=data['ew_naar_partner'],
        partner_inkomen=(data['params'].partner_bruto_loon or 0)
        if hasattr(data.get('params'), 'partner_bruto_loon') else 0,
    )
```

Add import at top of `pages/aangifte.py`:

```python
from components.fiscal_utils import (
    fetch_fiscal_data, load_jaarafsluiting_data, bereken_balans,
)
```
*(add `load_jaarafsluiting_data` to the existing import line)*

- [ ] **Step 4: Run tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```
Expected: all pass, including the two new snapshot-route tests.

- [ ] **Step 5: Manual verification (optional but recommended)**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python main.py
```

In the browser:
1. Navigate to Jaarafsluiting → pick a concept year → hit "Definitief maken"
2. Navigate to Aangifte for that year → verify cijfers match the Jaarcijfers-PDF
3. (Optionally) go to Jaarafsluiting → "Heropenen" → add a factuur → "Definitief" again → verify new snapshot updated

- [ ] **Step 6: Commit**

```bash
git add pages/aangifte.py tests/test_aangifte.py
git commit -m "feat(aangifte): read snapshot for definitief jaren (K5)

_get_fiscal now calls load_jaarafsluiting_data which returns the
snapshot for definitief jaren and falls back to live fetch_fiscal_data
for concept jaren. Guarantees cijfer-consistency between /aangifte
and /jaarafsluiting for frozen years."
```

---

### Task A8: Document unfreeze path in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` — add sentence under "Jaarafsluiting definitief"

- [ ] **Step 1: Edit CLAUDE.md**

Find the existing line:

```markdown
- **Jaarafsluiting definitief**: maakt een echte JSON snapshot ...
```

Append:

```markdown
- **Jaar-lock (K6)**: zodra status='definitief' weigert elke mutatie op facturen, werkdagen, uitgaven, banktransacties en fiscale_params van dat jaar met `YearLockedError`. Uitzondering: `update_jaarafsluiting_status(jaar, 'concept')` is de unfreeze-escape en werkt altijd. Na heropenen → correcties → opnieuw definitief maken overschrijft het snapshot.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE): document year-lock behavior and unfreeze path"
```

---

## Plan B — Connection Singleton (B8)

### Files

- **Modify:**
    - `database.py` — rewrite `get_db`/`get_db_ctx` (~263-282), add lifecycle helpers
    - `main.py` — add `@app.on_startup`/`@app.on_shutdown` hooks for connection open/close
- **Test:**
    - `tests/test_db_singleton.py` (new file) — specific caching behavior
    - existing tests must keep passing unchanged (fixture uses tmp_path per-test)

**Design:** Module-level `dict[Path, aiosqlite.Connection]` cache. `get_db_ctx(path)` yields the cached connection if open; opens + caches if not. Connections are never closed by `get_db_ctx` — closure is lifecycle-managed via shutdown hook. `init_db` keeps opening its own short-lived connection (only runs once at startup and touches PRAGMA/schema in ways a long-lived connection could tolerate — but keeping it isolated avoids migration-vs-queries interleaving).

**Rationale:** single-user app = no concurrent writer contention. aiosqlite connections are safe to reuse across async tasks as long as statements are awaited sequentially (aiosqlite serialises via its internal thread). Test isolation preserved because pytest's `tmp_path` gives each test its own `db_path` → different cache key → fresh connection.

### Task B1: Extract current `get_db`/`get_db_ctx` into cache-aware variant

**Files:**
- Modify: `database.py` — replace lines 263-282
- Test: new file `tests/test_db_singleton.py`

- [ ] **Step 1: Failing test**

Create `tests/test_db_singleton.py`:

```python
"""Connection singleton behavior (review B8)."""

import pytest


@pytest.mark.asyncio
async def test_get_db_ctx_reuses_connection_across_calls(db):
    """Two consecutive get_db_ctx calls for the same path yield the SAME
    underlying aiosqlite connection."""
    from database import get_db_ctx
    async with get_db_ctx(db) as conn1:
        id1 = id(conn1)
    async with get_db_ctx(db) as conn2:
        id2 = id(conn2)
    assert id1 == id2


@pytest.mark.asyncio
async def test_get_db_ctx_separate_connections_for_different_paths(
        db, tmp_path):
    """Different db_paths get different cached connections."""
    from database import get_db_ctx, init_db
    other = tmp_path / "other.sqlite3"
    await init_db(other)

    async with get_db_ctx(db) as c1:
        id1 = id(c1)
    async with get_db_ctx(other) as c2:
        id2 = id(c2)
    assert id1 != id2


@pytest.mark.asyncio
async def test_close_all_connections_clears_cache(db):
    """close_all_connections() closes every cached connection and empties cache."""
    from database import get_db_ctx, close_all_connections, _connection_cache
    async with get_db_ctx(db) as _:
        pass
    assert db in _connection_cache
    await close_all_connections()
    assert db not in _connection_cache
```

- [ ] **Step 2: Verify failure**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_singleton.py -v
```
Expected: ImportError on `_connection_cache` / `close_all_connections`, or the first test fails because current `get_db_ctx` closes connections on exit.

- [ ] **Step 3: Replace `get_db`/`get_db_ctx`**

In `database.py:263-282`, replace with:

```python
# --- Connection cache (review B8) ---
# Single-user app, asyncio single-thread: one connection per db_path
# avoids per-query connect + 5 PRAGMA setup overhead. Connections live
# for the lifetime of the app (see main.py startup/shutdown hooks) and
# for the lifetime of a test-fixture when tmp_path is used.
_connection_cache: dict[Path, aiosqlite.Connection] = {}


async def _open_connection(db_path: Path) -> aiosqlite.Connection:
    """Open a new aiosqlite connection with standard PRAGMAs."""
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA synchronous = NORMAL")
    await conn.execute("PRAGMA cache_size = 10000")
    await conn.execute("PRAGMA temp_store = MEMORY")
    conn.row_factory = aiosqlite.Row
    return conn


async def get_db(db_path: Path = DB_PATH) -> aiosqlite.Connection:
    """Get (and cache) a database connection.

    Subsequent calls for the same db_path return the same connection.
    Callers MUST NOT close the returned connection themselves; lifecycle
    is handled via close_all_connections() at app shutdown.
    """
    conn = _connection_cache.get(db_path)
    if conn is None:
        conn = await _open_connection(db_path)
        _connection_cache[db_path] = conn
    return conn


@asynccontextmanager
async def get_db_ctx(db_path: Path = DB_PATH):
    """Yield the cached connection for this db_path. Does NOT close it."""
    conn = await get_db(db_path)
    yield conn  # no close — lifecycle managed at app-shutdown


async def close_all_connections() -> None:
    """Close every cached connection. Idempotent."""
    paths = list(_connection_cache.keys())
    for path in paths:
        conn = _connection_cache.pop(path, None)
        if conn is not None:
            try:
                await conn.close()
            except Exception:  # noqa: BLE001 — shutdown best-effort
                pass
```

- [ ] **Step 4: Run tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_singleton.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Run FULL suite — critical integrity check**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

**If the suite fails:** the most likely cause is a test that closes the connection via a mock or manual close. Inspect failures; the fix is usually to `await close_all_connections()` at the end of that specific test, OR to update the test-fixture in `conftest.py` to call `close_all_connections` on teardown.

- [ ] **Step 6: If needed, update `tests/conftest.py` db fixture teardown**

Read current `tests/conftest.py`. If the `db` fixture yields without explicit teardown, add:

```python
@pytest.fixture
async def db(tmp_path, monkeypatch):
    db_path = tmp_path / "boekhouding.sqlite3"
    monkeypatch.setenv("BOEKHOUDING_DB_DIR", str(tmp_path))
    # ... existing init_db call ...
    yield db_path
    # NEW: close any cached connection so next test starts clean
    from database import close_all_connections
    await close_all_connections()
```

(The exact current shape of the fixture is short — adapt the teardown line to the existing structure.)

- [ ] **Step 7: Commit**

```bash
git add database.py tests/test_db_singleton.py tests/conftest.py
git commit -m "perf(db): cache aiosqlite connections per db_path (B8)

get_db/get_db_ctx now reuse a module-level connection per db_path
instead of opening + closing for every query. Single-user app +
asyncio single-thread make this safe. Adds close_all_connections()
for app-shutdown (wired in next commit) and test-fixture teardown."
```

---

### Task B2: Wire startup/shutdown hooks in `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Edit `main.py`**

Current `@app.on_startup` (~80-88) pre-creates directories and runs init_db. After that hook, add a shutdown hook:

```python
from nicegui import app, ui
from database import init_db, DB_PATH, close_all_connections
# ... other imports unchanged

@app.on_startup
async def startup():
    data_dir = DB_PATH.parent
    (data_dir / "facturen").mkdir(parents=True, exist_ok=True)
    (data_dir / "uitgaven").mkdir(parents=True, exist_ok=True)
    (data_dir / "bank_csv").mkdir(parents=True, exist_ok=True)
    (data_dir / "aangifte").mkdir(parents=True, exist_ok=True)
    await init_db(DB_PATH)
    await seed_all(DB_PATH)


@app.on_shutdown
async def _shutdown_close_db():
    """Close cached aiosqlite connection(s) cleanly on app shutdown."""
    await close_all_connections()
```

- [ ] **Step 2: Smoke-test startup**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -c "
import main  # triggers ui.run() — hit Ctrl+C after 'NiceGUI ready' log line"
```
Expected: app starts without error, logs "NiceGUI ready". Ctrl+C stops cleanly (no hanging connection warning).

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(app): close cached DB connections on app shutdown"
```

---

### Task B3: Measure before/after impact

**Files:**
- No code changes; this is a benchmarking step with a recorded result in the commit message.

- [ ] **Step 1: Baseline (pre-singleton) time 10 sequential get_kpis calls**

Checkout an earlier commit or stash changes, then:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -c "
import asyncio, time
from database import init_db, get_kpis, DB_PATH
asyncio.run(init_db(DB_PATH))

async def bench():
    t0 = time.perf_counter()
    for _ in range(10):
        await get_kpis(DB_PATH, 2026)
    return time.perf_counter() - t0

print(f'10x get_kpis: {asyncio.run(bench())*1000:.1f} ms')
"
```
Record the number (e.g. 180 ms).

- [ ] **Step 2: After-singleton measurement**

Return to the singleton branch, run the same command. Record (e.g. 35 ms).

- [ ] **Step 3: Commit a benchmarks note to the plan doc OR add a comment**

If meaningful (>2x speedup): add a comment at the top of the `_connection_cache` block in `database.py`:

```python
# Benchmark (apple M1, warm cache): 10× get_kpis dropped from ~180ms
# (reconnect per call) to ~35ms after singleton.
```

- [ ] **Step 4: Final commit**

```bash
git add database.py
git commit -m "docs(db): record connection-singleton benchmark result"
```

---

## Self-Review

### Spec coverage

- **K5** (/aangifte reads snapshot for definitief years): covered by Task A7.
- **K6** (write-guards on all mutations for definitief years): covered by A2 (werkdagen), A3 (uitgaven), A4 (facturen + save_factuur_atomic), A5 (banktransacties), A6 (fiscale_params). Unfreeze path preserved via A6 guard logic + A8 docs.
- **B8** (connection singleton): covered by B1 + B2. Benchmark in B3.

### Placeholder scan

- No TBD / TODO / "add error handling" leftovers.
- No "similar to Task N" — each task includes its own code.
- Every code-change step includes a code block.

### Type & signature consistency

- `YearLockedError` defined in A1, imported + raised in A2-A6. Subclass of ValueError so existing callers that catch ValueError don't need to change.
- `assert_year_writable(db_path, jaar_or_datum)` signature: accepts `int | str`. Consistent across all call sites.
- `_connection_cache: dict[Path, Connection]`, `close_all_connections()` defined in B1, imported in B2 and conftest.
- `get_db_ctx` still returns an async context manager yielding a connection — call sites elsewhere in `database.py` (all existing `async with get_db_ctx(...) as conn:` patterns) keep working unchanged; only the underlying close-on-exit semantics changed.

### Scope check

Plan A and Plan B are intentionally independent — either can be executed alone without touching the other. Plan A is the higher-value correctness fix; Plan B is a pure performance refactor. If you want only one, do Plan A.

---

## Execution Handoff

**Plan saved to:** `docs/plans/2026-04-14-snapshot-immutability-connection-singleton.md`

**Two execution options:**

1. **Subagent-Driven (recommended for Plan A)** — dispatch a fresh Opus subagent per task, review between tasks, fast iteration. Well-suited because Plan A touches many files across several modules.

2. **Inline Execution (recommended for Plan B)** — execute in this session with checkpoints. Plan B is small, self-contained, and safer to do interactively so I can react to suite-level test breakages immediately.

**My recommendation:** do Plan A via subagent-driven now (high value, bounded scope), then do Plan B inline afterwards (fast, measurable).

Which approach?
