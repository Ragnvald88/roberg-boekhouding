# VA Beschikkingen Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual VA input with beschikking-based entry and automatic bank transaction matching, so "betaald" reflects actual payments.

**Architecture:** New `va_*` columns on `fiscale_params` store beschikking data. Bank transactions are matched to VA IB/ZVW via `koppeling_type`/`koppeling_id` (existing unused columns). New VA tab on Aangifte shows beschikking + matched payments. Dashboard uses bank-based totals with theoretical fallback.

**Tech Stack:** NiceGUI 3.8, aiosqlite, SQLite (raw SQL, `?` placeholders), pytest

**Spec:** `docs/superpowers/specs/2026-03-13-va-beschikkingen-design.md`

**Test command:** `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

---

## Chunk 1: Database + Model + Fiscal Utils

### Task 1: Model + Migration

**Files:**
- Modify: `models.py:104-174` (FiscaleParams dataclass)
- Modify: `database.py:202-240` (migration loops)

- [ ] **Step 1: Add 4 fields to FiscaleParams dataclass**

In `models.py`, after `jaarafsluiting_status` (last field, ~line 174), add:

```python
    va_termijnen: int = 11
    va_start_maand: int = 2
    va_ib_kenmerk: str = ''
    va_zvw_kenmerk: str = ''
```

- [ ] **Step 2: Add migration for INTEGER columns**

In `database.py`, in the REAL migration loop (lines 202-222), add before the closing `]:`:

```python
            ('va_termijnen', 11), ('va_start_maand', 2),
```

Note: these are INTEGER but SQLite is type-flexible. The REAL DEFAULT loop works for integers too.

- [ ] **Step 3: Add migration for TEXT columns**

In `database.py`, in the TEXT migration loop (lines 231-233), add before the closing `]:`:

```python
            ('va_ib_kenmerk', "''"), ('va_zvw_kenmerk', "''"),
```

- [ ] **Step 4: Update `_row_to_fiscale_params()`**

In `database.py` function `_row_to_fiscale_params` (~line 916-977), add 4 new fields before the closing `)`:

```python
        va_termijnen=int(_safe_get(r, 'va_termijnen', 11)),
        va_start_maand=int(_safe_get(r, 'va_start_maand', 2)),
        va_ib_kenmerk=_safe_get(r, 'va_ib_kenmerk', ''),
        va_zvw_kenmerk=_safe_get(r, 'va_zvw_kenmerk', ''),
```

- [ ] **Step 5: Update `upsert_fiscale_params()` preserve-SELECT**

In `database.py` function `upsert_fiscale_params` (~line 999-1009), add to the SELECT:

```python
             "va_termijnen, va_start_maand, va_ib_kenmerk, va_zvw_kenmerk, "
```

And in the INSERT OR REPLACE block (~line 1061-1077), add preservation logic:

```python
            existing['va_termijnen'] if existing else 11,
            existing['va_start_maand'] if existing else 2,
            existing['va_ib_kenmerk'] if existing else '',
            existing['va_zvw_kenmerk'] if existing else '',
```

Ensure the corresponding column names are added to the INSERT column list and VALUES placeholders.

- [ ] **Step 6: Run all tests to verify migration doesn't break anything**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All 412 tests PASS

- [ ] **Step 7: Commit**

```bash
git add models.py database.py
git commit -m "feat(va): add beschikking columns to FiscaleParams + migration"
```

### Task 2: New DB Functions — Tests First

**Files:**
- Create: `tests/test_va_beschikkingen.py`
- Modify: `database.py`

- [ ] **Step 1: Write test file with all DB function tests**

Create `tests/test_va_beschikkingen.py`:

```python
"""Tests for VA beschikkingen DB functions and matching."""
import pytest
from pathlib import Path
from database import (
    init_db, upsert_fiscale_params, update_va_beschikking,
    auto_match_va_betalingen, get_va_betalingen, get_va_betaald_totaal,
    koppel_va_betaling, ontkoppel_va_betaling, get_db_ctx,
)
from models import Banktransactie


@pytest.fixture
async def db(tmp_path):
    """Create a fresh test DB with fiscale_params for 2025."""
    p = tmp_path / 'test.sqlite3'
    await init_db(p)
    await upsert_fiscale_params(p, jaar=2025, schijf1_grens=38441,
                                schijf1_pct=8.17, schijf2_grens=76817,
                                schijf2_pct=37.48, schijf3_pct=49.50)
    return p


async def _insert_bank_tx(db_path, datum, bedrag, tegenpartij='Belastingdienst',
                          tegenrekening='NL86INGB0002445588', omschrijving=''):
    """Helper: insert a bank transaction."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenpartij, tegenrekening, omschrijving) "
            "VALUES (?, ?, ?, ?, ?)",
            (datum, bedrag, tegenpartij, tegenrekening, omschrijving))
        await conn.commit()
        return cur.lastrowid


# --- update_va_beschikking ---

@pytest.mark.asyncio
async def test_update_va_beschikking(db):
    await update_va_beschikking(
        db, jaar=2025, va_ib=29851.0, va_zvw=2859.0,
        termijnen=11, start_maand=2,
        va_ib_kenmerk='1124412647050001', va_zvw_kenmerk='1124412647550014',
    )
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT voorlopige_aanslag_betaald, voorlopige_aanslag_zvw, "
            "va_termijnen, va_start_maand, va_ib_kenmerk, va_zvw_kenmerk "
            "FROM fiscale_params WHERE jaar = 2025")
        row = await cur.fetchone()
    assert row[0] == 29851.0
    assert row[1] == 2859.0
    assert row[2] == 11
    assert row[3] == 2
    assert row[4] == '1124412647050001'
    assert row[5] == '1124412647550014'


# --- auto_match_va_betalingen ---

@pytest.mark.asyncio
async def test_auto_match_by_amount(db):
    """Match BD transactions to VA IB/ZVW by amount proximity."""
    await update_va_beschikking(db, jaar=2025, va_ib=29851.0, va_zvw=2859.0,
                                termijnen=11, start_maand=2,
                                va_ib_kenmerk='', va_zvw_kenmerk='')
    # IB termijn = 29851/11 = 2713.73
    await _insert_bank_tx(db, '2025-02-28', -2713.73)
    await _insert_bank_tx(db, '2025-03-28', -2713.73)
    # ZVW termijn = 2859/11 = 259.91
    await _insert_bank_tx(db, '2025-02-28', -259.91)

    matched = await auto_match_va_betalingen(db, 2025)
    assert matched == 3

    ib = await get_va_betalingen(db, 2025, 'va_ib')
    assert len(ib) == 2
    zvw = await get_va_betalingen(db, 2025, 'va_zvw')
    assert len(zvw) == 1


@pytest.mark.asyncio
async def test_auto_match_by_kenmerk(db):
    """Match BD transaction by betalingskenmerk in omschrijving."""
    await update_va_beschikking(db, jaar=2025, va_ib=29851.0, va_zvw=2859.0,
                                termijnen=11, start_maand=2,
                                va_ib_kenmerk='1124412647050001',
                                va_zvw_kenmerk='1124412647550014')
    # Amount doesn't match any termijn, but kenmerk does
    await _insert_bank_tx(db, '2025-12-24', -1900.0,
                          omschrijving='1124412647050001 Inkomstenbelasting 2025')

    matched = await auto_match_va_betalingen(db, 2025)
    assert matched == 1

    ib = await get_va_betalingen(db, 2025, 'va_ib')
    assert len(ib) == 1
    assert ib[0].bedrag == -1900.0


@pytest.mark.asyncio
async def test_auto_match_skips_zero_jaarbedrag(db):
    """Don't match if jaarbedrag is 0 for a type."""
    await update_va_beschikking(db, jaar=2025, va_ib=29851.0, va_zvw=0,
                                termijnen=11, start_maand=2,
                                va_ib_kenmerk='', va_zvw_kenmerk='')
    # This amount is close to what ZVW termijn would be if it existed
    await _insert_bank_tx(db, '2025-02-28', -260.00)
    # This is clearly IB
    await _insert_bank_tx(db, '2025-02-28', -2713.73)

    matched = await auto_match_va_betalingen(db, 2025)
    # Only IB should match, the 260 stays unmatched
    assert matched == 1
    ib = await get_va_betalingen(db, 2025, 'va_ib')
    assert len(ib) == 1


@pytest.mark.asyncio
async def test_auto_match_ignores_non_bd(db):
    """Only match transactions from Belastingdienst."""
    await update_va_beschikking(db, jaar=2025, va_ib=29851.0, va_zvw=2859.0,
                                termijnen=11, start_maand=2,
                                va_ib_kenmerk='', va_zvw_kenmerk='')
    await _insert_bank_tx(db, '2025-02-28', -2713.73, tegenpartij='Albert Heijn',
                          tegenrekening='NL00RABO0000000000')

    matched = await auto_match_va_betalingen(db, 2025)
    assert matched == 0


@pytest.mark.asyncio
async def test_auto_match_ignores_positive(db):
    """Only match negative (outgoing) transactions."""
    await update_va_beschikking(db, jaar=2025, va_ib=29851.0, va_zvw=2859.0,
                                termijnen=11, start_maand=2,
                                va_ib_kenmerk='', va_zvw_kenmerk='')
    # Storno/refund = positive
    await _insert_bank_tx(db, '2025-02-28', 2713.73)

    matched = await auto_match_va_betalingen(db, 2025)
    assert matched == 0


@pytest.mark.asyncio
async def test_auto_match_ignores_already_linked(db):
    """Don't re-match already linked transactions."""
    await update_va_beschikking(db, jaar=2025, va_ib=29851.0, va_zvw=2859.0,
                                termijnen=11, start_maand=2,
                                va_ib_kenmerk='', va_zvw_kenmerk='')
    tx_id = await _insert_bank_tx(db, '2025-02-28', -2713.73)
    # Pre-link it
    await koppel_va_betaling(db, tx_id, 'va_ib', 2025)

    matched = await auto_match_va_betalingen(db, 2025)
    assert matched == 0  # Already linked, skip


# --- get_va_betaald_totaal ---

@pytest.mark.asyncio
async def test_get_va_betaald_totaal(db):
    await _insert_bank_tx(db, '2025-02-28', -2713.73)
    await _insert_bank_tx(db, '2025-03-28', -2713.73)
    # Link them
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "UPDATE banktransacties SET koppeling_type='va_ib', koppeling_id=2025")
        await conn.commit()

    totaal = await get_va_betaald_totaal(db, 2025, 'va_ib')
    assert abs(totaal - 5427.46) < 0.01


@pytest.mark.asyncio
async def test_get_va_betaald_totaal_empty(db):
    totaal = await get_va_betaald_totaal(db, 2025, 'va_ib')
    assert totaal == 0.0


# --- koppel / ontkoppel ---

@pytest.mark.asyncio
async def test_koppel_ontkoppel_va_betaling(db):
    tx_id = await _insert_bank_tx(db, '2025-02-28', -2713.73)

    await koppel_va_betaling(db, tx_id, 'va_ib', 2025)
    betalingen = await get_va_betalingen(db, 2025, 'va_ib')
    assert len(betalingen) == 1

    await ontkoppel_va_betaling(db, tx_id)
    betalingen = await get_va_betalingen(db, 2025, 'va_ib')
    assert len(betalingen) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_va_beschikkingen.py -v`
Expected: ImportError — `update_va_beschikking` etc. not yet defined

- [ ] **Step 3: Implement all 6 DB functions**

In `database.py`, add after `update_ib_inputs()` (~line 1099):

```python
async def update_va_beschikking(db_path: Path = DB_PATH, jaar: int = 0,
                                va_ib: float = 0, va_zvw: float = 0,
                                termijnen: int = 11, start_maand: int = 2,
                                va_ib_kenmerk: str = '', va_zvw_kenmerk: str = '') -> None:
    """Update VA beschikking columns for a specific year."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            """UPDATE fiscale_params
               SET voorlopige_aanslag_betaald = ?, voorlopige_aanslag_zvw = ?,
                   va_termijnen = ?, va_start_maand = ?,
                   va_ib_kenmerk = ?, va_zvw_kenmerk = ?
               WHERE jaar = ?""",
            (va_ib, va_zvw, termijnen, start_maand,
             va_ib_kenmerk, va_zvw_kenmerk, jaar))
        await conn.commit()


async def auto_match_va_betalingen(db_path: Path = DB_PATH, jaar: int = 0) -> int:
    """Match unlinked Belastingdienst transactions to VA IB/ZVW for a year.
    Returns number of newly matched transactions."""
    async with get_db_ctx(db_path) as conn:
        # Get VA beschikking data
        cur = await conn.execute(
            "SELECT voorlopige_aanslag_betaald, voorlopige_aanslag_zvw, "
            "va_termijnen, va_ib_kenmerk, va_zvw_kenmerk "
            "FROM fiscale_params WHERE jaar = ?", (jaar,))
        row = await cur.fetchone()
        if not row:
            return 0

        va_ib, va_zvw, termijnen, ib_kenmerk, zvw_kenmerk = row
        termijnen = termijnen or 11
        ib_termijn = va_ib / termijnen if va_ib and termijnen else 0
        zvw_termijn = va_zvw / termijnen if va_zvw and termijnen else 0

        # Strip dots/spaces from kenmerken for matching
        ib_kenmerk_clean = (ib_kenmerk or '').replace('.', '').replace(' ', '')
        zvw_kenmerk_clean = (zvw_kenmerk or '').replace('.', '').replace(' ', '')

        # Get unlinked BD transactions for this year
        cur = await conn.execute(
            """SELECT id, bedrag, omschrijving FROM banktransacties
               WHERE (tegenpartij = 'Belastingdienst'
                      OR tegenrekening = 'NL86INGB0002445588')
                 AND bedrag < 0
                 AND datum LIKE ?
                 AND (koppeling_type = '' OR koppeling_type IS NULL)
               ORDER BY datum""",
            (f'{jaar}-%',))
        transactions = await cur.fetchall()

        matched = 0
        for tx in transactions:
            tx_id, bedrag, omschrijving = tx
            abs_bedrag = abs(bedrag)
            omschr_clean = (omschrijving or '').replace('.', '').replace(' ', '')
            va_type = None

            # Strategy 1: Match by betalingskenmerk
            if ib_kenmerk_clean and ib_kenmerk_clean in omschr_clean:
                va_type = 'va_ib'
            elif zvw_kenmerk_clean and zvw_kenmerk_clean in omschr_clean:
                va_type = 'va_zvw'
            # Strategy 2: Match by amount (5% tolerance)
            elif ib_termijn > 0 and abs(abs_bedrag - ib_termijn) / ib_termijn <= 0.05:
                va_type = 'va_ib'
            elif zvw_termijn > 0 and abs(abs_bedrag - zvw_termijn) / zvw_termijn <= 0.05:
                va_type = 'va_zvw'

            if va_type:
                await conn.execute(
                    "UPDATE banktransacties SET koppeling_type = ?, koppeling_id = ? WHERE id = ?",
                    (va_type, jaar, tx_id))
                matched += 1

        await conn.commit()
        return matched


async def get_va_betalingen(db_path: Path = DB_PATH, jaar: int = 0,
                            va_type: str = 'va_ib') -> list:
    """Get bank transactions linked to VA for a year. Returns list of Banktransactie."""
    from models import Banktransactie
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT id, datum, bedrag, tegenrekening, tegenpartij,
                      omschrijving, categorie, koppeling_type, koppeling_id, csv_bestand
               FROM banktransacties
               WHERE koppeling_type = ? AND koppeling_id = ?
               ORDER BY datum""",
            (va_type, jaar))
        rows = await cur.fetchall()
    return [Banktransactie(*r) for r in rows]


async def get_va_betaald_totaal(db_path: Path = DB_PATH, jaar: int = 0,
                                va_type: str = 'va_ib') -> float:
    """Get total VA paid from linked bank transactions. Returns positive amount."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT COALESCE(SUM(ABS(bedrag)), 0) FROM banktransacties "
            "WHERE koppeling_type = ? AND koppeling_id = ?",
            (va_type, jaar))
        row = await cur.fetchone()
    return float(row[0])


async def koppel_va_betaling(db_path: Path = DB_PATH, tx_id: int = 0,
                             va_type: str = 'va_ib', jaar: int = 0) -> None:
    """Manually link a bank transaction to VA."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "UPDATE banktransacties SET koppeling_type = ?, koppeling_id = ? WHERE id = ?",
            (va_type, jaar, tx_id))
        await conn.commit()


async def ontkoppel_va_betaling(db_path: Path = DB_PATH, tx_id: int = 0) -> None:
    """Unlink a bank transaction from VA."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "UPDATE banktransacties SET koppeling_type = '', koppeling_id = NULL WHERE id = ?",
            (tx_id,))
        await conn.commit()
```

- [ ] **Step 4: Run VA tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_va_beschikkingen.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Run all tests to verify no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS (412 + 11 new = 423)

- [ ] **Step 6: Commit**

```bash
git add tests/test_va_beschikkingen.py database.py
git commit -m "feat(va): add VA beschikking DB functions with tests

update_va_beschikking, auto_match_va_betalingen (kenmerk + amount),
get_va_betalingen, get_va_betaald_totaal, koppel/ontkoppel."
```

### Task 3: Fiscal Utils — Helper + fetch_fiscal_data

**Files:**
- Modify: `components/fiscal_utils.py:29,108-131`
- Add to: `tests/test_va_beschikkingen.py`

- [ ] **Step 1: Write tests for bereken_va_betaald_theoretisch**

Append to `tests/test_va_beschikkingen.py`:

```python
from datetime import date
from components.fiscal_utils import bereken_va_betaald_theoretisch


# --- bereken_va_betaald_theoretisch ---

def test_va_theoretisch_mid_year():
    """March, 11 termijnen starting feb: 2 termijnen betaald."""
    bedrag, n = bereken_va_betaald_theoretisch(29851.0, 11, 2, date(2025, 3, 15))
    assert n == 2
    assert abs(bedrag - 5427.45) < 0.01  # 2 * (29851/11)


def test_va_theoretisch_january():
    """January, before first termijn (feb): 0 betaald."""
    bedrag, n = bereken_va_betaald_theoretisch(29851.0, 11, 2, date(2025, 1, 15))
    assert n == 0
    assert bedrag == 0.0


def test_va_theoretisch_december():
    """December = all 11 termijnen betaald."""
    bedrag, n = bereken_va_betaald_theoretisch(29851.0, 11, 2, date(2025, 12, 31))
    assert n == 11
    assert abs(bedrag - 29851.0) < 0.01


def test_va_theoretisch_zero_jaarbedrag():
    bedrag, n = bereken_va_betaald_theoretisch(0, 11, 2, date(2025, 6, 1))
    assert n == 0
    assert bedrag == 0.0


def test_va_theoretisch_single_termijn():
    """1 termijn in januari."""
    bedrag, n = bereken_va_betaald_theoretisch(5000.0, 1, 1, date(2025, 1, 15))
    assert n == 1
    assert bedrag == 5000.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_va_beschikkingen.py::test_va_theoretisch_mid_year -v`
Expected: ImportError

- [ ] **Step 3: Implement bereken_va_betaald_theoretisch**

In `components/fiscal_utils.py`, add at the top (after imports, before `fetch_fiscal_data`):

```python
from datetime import date as _date


def bereken_va_betaald_theoretisch(jaarbedrag: float, termijnen: int,
                                    start_maand: int, peildatum: _date) -> tuple[float, int]:
    """Theoretisch betaald bedrag op basis van termijnschema.
    Fallback als geen bankdata beschikbaar.
    Returns (betaald_bedrag, betaalde_termijnen)."""
    if jaarbedrag <= 0 or termijnen <= 0:
        return 0.0, 0
    betaalde = max(0, min(peildatum.month - start_maand + 1, termijnen))
    bedrag = round(betaalde * (jaarbedrag / termijnen), 2)
    return bedrag, betaalde
```

- [ ] **Step 4: Update fetch_fiscal_data return dict**

In `components/fiscal_utils.py`, in the return dict of `fetch_fiscal_data()` (~line 125-131), add before the closing `}`:

```python
        'va_termijnen': params.va_termijnen or 11,
        'va_start_maand': params.va_start_maand or 2,
        'va_ib_kenmerk': params.va_ib_kenmerk or '',
        'va_zvw_kenmerk': params.va_zvw_kenmerk or '',
```

- [ ] **Step 5: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add components/fiscal_utils.py tests/test_va_beschikkingen.py
git commit -m "feat(va): bereken_va_betaald_theoretisch + fetch_fiscal_data VA fields"
```

### Task 4: Clean up update_ib_inputs

**Files:**
- Modify: `database.py:1082-1099`
- Modify: `pages/aangifte.py:522-537`

- [ ] **Step 1: Remove VA params from update_ib_inputs**

In `database.py`, change `update_ib_inputs` (lines 1082-1099) to:

```python
async def update_ib_inputs(db_path: Path = DB_PATH, jaar: int = 0,
                           aov_premie: float = 0, woz_waarde: float = 0,
                           hypotheekrente: float = 0,
                           lijfrente_premie: float = 0) -> None:
    """Update only the IB-input columns for a specific year."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            """UPDATE fiscale_params
               SET aov_premie = ?, woz_waarde = ?,
                   hypotheekrente = ?, lijfrente_premie = ?
               WHERE jaar = ?""",
            (aov_premie, woz_waarde, hypotheekrente,
             lijfrente_premie, jaar))
        await conn.commit()
```

- [ ] **Step 2: Update save_prive in aangifte.py**

In `pages/aangifte.py`, update `save_prive()` (lines 522-537). Remove VA value reading and VA kwargs from the call:

```python
            async def save_prive():
                aov_val = float(aov_input.value or 0)
                woz_val = float(woz_input.value or 0)
                hyp_val = float(hyp_input.value or 0)
                ew_val = ew_partner_check.value
                lijfrente_val = float(lijfrente_input.value or 0)

                await update_ib_inputs(
                    DB_PATH, jaar=jaar,
                    aov_premie=aov_val, woz_waarde=woz_val,
                    hypotheekrente=hyp_val,
                    lijfrente_premie=lijfrente_val,
                )
```

Keep the rest of `save_prive` unchanged (ew_naar_partner, cache invalidation, render_overzicht).

- [ ] **Step 3: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add database.py pages/aangifte.py
git commit -m "refactor(va): remove VA params from update_ib_inputs

VA is now saved via update_va_beschikking on the new VA tab."
```

---

## Chunk 2: UI Changes

### Task 5: Aangifte — New VA Tab

**Files:**
- Modify: `pages/aangifte.py:192-210` (tab structure) + add `render_va()` function

- [ ] **Step 1: Add imports**

In `pages/aangifte.py`, add to imports:

```python
from database import (update_va_beschikking, auto_match_va_betalingen,
                      get_va_betalingen, get_va_betaald_totaal,
                      koppel_va_betaling, ontkoppel_va_betaling)
```

- [ ] **Step 2: Add VA tab to tab structure**

In `pages/aangifte.py`, modify tab declarations (~line 192-210):

```python
        with ui.tabs().classes('w-full') as tabs:
            tab_va = ui.tab('Voorlopige Aanslagen', icon='receipt_long')
            tab_winst = ui.tab('Winst', icon='business_center')
            tab_prive = ui.tab('Prive & aftrek', icon='home')
            tab_box3 = ui.tab('Box 3', icon='savings')
            tab_overzicht = ui.tab('Overzicht', icon='summarize')
            tab_docs = ui.tab('Documenten', icon='folder')

        with ui.tab_panels(tabs, value=tab_winst).classes('w-full'):
            with ui.tab_panel(tab_va):
                va_container = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_winst):
                winst_container = ui.column().classes('w-full gap-4')
```

Keep other tab panels unchanged.

- [ ] **Step 3: Write render_va function**

Add `render_va()` inside `aangifte_page()`, near the other render functions:

```python
    MAANDEN = {1: 'januari', 2: 'februari', 3: 'maart', 4: 'april',
               5: 'mei', 6: 'juni', 7: 'juli', 8: 'augustus',
               9: 'september', 10: 'oktober', 11: 'november', 12: 'december'}

    async def render_va():
        va_container.clear()
        jaar = state['jaar']
        data, _ = await _get_fiscal(jaar)
        if data is None:
            with va_container:
                ui.label('Geen fiscale parameters voor dit jaar.').classes('text-grey-6')
            return

        params = data['params']
        huidig_jaar = date.today().year

        # Current values
        va_ib_val = params.voorlopige_aanslag_betaald or 0
        va_zvw_val = params.voorlopige_aanslag_zvw or 0
        termijnen_val = params.va_termijnen or 11
        start_maand_val = params.va_start_maand or 2
        ib_kenmerk_val = params.va_ib_kenmerk or ''
        zvw_kenmerk_val = params.va_zvw_kenmerk or ''

        # Get matched payments
        ib_betalingen = await get_va_betalingen(DB_PATH, jaar, 'va_ib')
        zvw_betalingen = await get_va_betalingen(DB_PATH, jaar, 'va_zvw')
        ib_betaald = await get_va_betaald_totaal(DB_PATH, jaar, 'va_ib')
        zvw_betaald = await get_va_betaald_totaal(DB_PATH, jaar, 'va_zvw')

        # Get unlinked BD transactions for this year
        from database import get_db_ctx
        async with get_db_ctx(DB_PATH) as conn:
            cur = await conn.execute(
                """SELECT id, datum, bedrag, omschrijving FROM banktransacties
                   WHERE (tegenpartij = 'Belastingdienst'
                          OR tegenrekening = 'NL86INGB0002445588')
                     AND bedrag < 0 AND datum LIKE ?
                     AND (koppeling_type = '' OR koppeling_type IS NULL)
                   ORDER BY datum""",
                (f'{jaar}-%',))
            unlinked = await cur.fetchall()

        async def save_va():
            ib = float(va_ib_input.value or 0)
            zvw = float(va_zvw_input.value or 0)
            t = int(termijnen_input.value or 11)
            sm = int(start_maand_input.value or 2)
            ib_k = va_ib_kenmerk_input.value or ''
            zvw_k = va_zvw_kenmerk_input.value or ''
            await update_va_beschikking(DB_PATH, jaar=jaar, va_ib=ib, va_zvw=zvw,
                                        termijnen=t, start_maand=sm,
                                        va_ib_kenmerk=ib_k, va_zvw_kenmerk=zvw_k)
            _invalidate_cache()
            await render_overzicht()

        async def do_hermatchen():
            await save_va()
            n = await auto_match_va_betalingen(DB_PATH, jaar)
            _invalidate_cache()
            await render_va()
            await render_overzicht()
            ui.notify(f'{n} transactie(s) gekoppeld' if n else 'Geen nieuwe matches', type='info')

        async def do_koppel(tx_id, va_type):
            await koppel_va_betaling(DB_PATH, tx_id, va_type, jaar)
            _invalidate_cache()
            await render_va()
            await render_overzicht()

        async def do_ontkoppel(tx_id):
            await ontkoppel_va_betaling(DB_PATH, tx_id)
            _invalidate_cache()
            await render_va()
            await render_overzicht()

        with va_container:
            with ui.row().classes('w-full gap-4 flex-wrap items-start'):
                # --- IB Card ---
                with ui.card().classes('flex-1 min-w-[400px]'):
                    ui.label('Inkomstenbelasting / Premie volksverzekeringen'
                             ).classes('text-subtitle1 text-weight-bold')
                    ui.separator().classes('my-1')

                    with ui.row().classes('gap-4 flex-wrap'):
                        va_ib_input = ui.number(
                            'Jaarbedrag', value=va_ib_val,
                            format='%.2f', prefix='€',
                        ).classes('w-48').on('blur', save_va)
                        va_ib_kenmerk_input = ui.input(
                            'Betalingskenmerk', value=ib_kenmerk_val,
                            placeholder='bijv. 1124 4126 4705 0001',
                        ).classes('w-64').on('blur', save_va)

                    ui.label('Betaalschema').classes('text-subtitle2 text-weight-medium mt-2')
                    with ui.row().classes('gap-4'):
                        termijnen_input = ui.number(
                            'Termijnen', value=termijnen_val,
                            min=1, max=12, step=1, format='%.0f',
                        ).classes('w-28').on('change', save_va)
                        maand_options = {i: m.capitalize() for i, m in MAANDEN.items()}
                        start_maand_input = ui.select(
                            maand_options, value=start_maand_val,
                            label='Eerste termijn',
                        ).classes('w-40').on('change', save_va)

                    if va_ib_val > 0 and termijnen_val > 0:
                        termijnbedrag = va_ib_val / termijnen_val
                        ui.label(f'Termijnbedrag: € {termijnbedrag:,.2f}'
                                 ).classes('text-caption text-grey-7')

                    # Betalingen section
                    if ib_betalingen:
                        ui.label('Betalingen').classes('text-subtitle2 text-weight-medium mt-2')
                        for b in ib_betalingen:
                            with ui.row().classes('items-center gap-2'):
                                ui.label(f'{b.datum}').classes('text-body2 w-24')
                                ui.label(f'€ {abs(b.bedrag):,.2f}').classes(
                                    'text-body2 w-24 text-right tabular-nums')
                                ui.button(icon='link_off', on_click=lambda _, tid=b.id: do_ontkoppel(tid)
                                          ).props('flat dense size=sm color=grey')

                    # Totalen
                    ui.separator().classes('my-1')
                    with ui.row().classes('gap-8'):
                        ui.label(f'Betaald: € {ib_betaald:,.2f} ({len(ib_betalingen)} betalingen)'
                                 ).classes('text-body2 text-weight-medium text-positive tabular-nums')
                        if va_ib_val > 0:
                            openstaand = va_ib_val - ib_betaald
                            color = 'text-negative' if openstaand > 0 else 'text-positive'
                            ui.label(f'Openstaand: € {openstaand:,.2f}'
                                     ).classes(f'text-body2 text-weight-medium {color} tabular-nums')

                # --- ZVW Card ---
                with ui.card().classes('flex-1 min-w-[400px]'):
                    ui.label('Zorgverzekeringswet'
                             ).classes('text-subtitle1 text-weight-bold')
                    ui.separator().classes('my-1')

                    with ui.row().classes('gap-4 flex-wrap'):
                        va_zvw_input = ui.number(
                            'Jaarbedrag', value=va_zvw_val,
                            format='%.2f', prefix='€',
                        ).classes('w-48').on('blur', save_va)
                        va_zvw_kenmerk_input = ui.input(
                            'Betalingskenmerk', value=zvw_kenmerk_val,
                            placeholder='bijv. 1124 4126 4755 0014',
                        ).classes('w-64').on('blur', save_va)

                    ui.label('Betaalschema: gekoppeld aan IB'
                             ).classes('text-caption text-grey-6 mt-2')

                    if va_zvw_val > 0 and termijnen_val > 0:
                        termijnbedrag = va_zvw_val / termijnen_val
                        ui.label(f'Termijnbedrag: € {termijnbedrag:,.2f}'
                                 ).classes('text-caption text-grey-7')

                    # Betalingen section
                    if zvw_betalingen:
                        ui.label('Betalingen').classes('text-subtitle2 text-weight-medium mt-2')
                        for b in zvw_betalingen:
                            with ui.row().classes('items-center gap-2'):
                                ui.label(f'{b.datum}').classes('text-body2 w-24')
                                ui.label(f'€ {abs(b.bedrag):,.2f}').classes(
                                    'text-body2 w-24 text-right tabular-nums')
                                ui.button(icon='link_off', on_click=lambda _, tid=b.id: do_ontkoppel(tid)
                                          ).props('flat dense size=sm color=grey')

                    # Totalen
                    ui.separator().classes('my-1')
                    with ui.row().classes('gap-8'):
                        ui.label(f'Betaald: € {zvw_betaald:,.2f} ({len(zvw_betalingen)} betalingen)'
                                 ).classes('text-body2 text-weight-medium text-positive tabular-nums')
                        if va_zvw_val > 0:
                            openstaand = va_zvw_val - zvw_betaald
                            color = 'text-negative' if openstaand > 0 else 'text-positive'
                            ui.label(f'Openstaand: € {openstaand:,.2f}'
                                     ).classes(f'text-body2 text-weight-medium {color} tabular-nums')

            # Hermatchen button
            ui.button('Hermatchen met bankdata', icon='sync',
                      on_click=do_hermatchen).props('outline color=primary').classes('mt-2')

            # Unlinked BD transactions
            if unlinked:
                ui.label('Niet-gekoppelde Belastingdienst-transacties'
                         ).classes('text-subtitle2 text-weight-medium mt-4')
                ui.separator().classes('my-1')
                for tx in unlinked:
                    tx_id, datum, bedrag, omschr = tx
                    with ui.row().classes('items-center gap-2'):
                        ui.label(f'{datum}').classes('text-body2 w-24')
                        ui.label(f'€ {abs(bedrag):,.2f}').classes(
                            'text-body2 w-24 text-right tabular-nums')
                        if omschr:
                            ui.label(omschr).classes('text-body2 text-grey-6 truncate max-w-xs')
                        ui.button('IB', on_click=lambda _, tid=tx_id: do_koppel(tid, 'va_ib')
                                  ).props('flat dense size=sm color=primary')
                        ui.button('ZVW', on_click=lambda _, tid=tx_id: do_koppel(tid, 'va_zvw')
                                  ).props('flat dense size=sm color=primary')
```

- [ ] **Step 4: Add render_va to refresh_all**

Find the `refresh_all()` function and add `await render_va()` alongside the other render calls:

```python
    async def refresh_all():
        await render_warnings()
        await render_va()
        await render_winst()
        await render_prive()
        await render_box3()
        await render_overzicht()
        await render_progress()
        await render_checklist()
```

- [ ] **Step 5: Remove Card 3 (VA) from render_prive**

In `render_prive()`, remove the entire Card 3 block (~lines 505-520):
- The `ui.card` with "Voorlopige aanslagen" label
- The `va_ib_input` and `va_zvw_input` definitions
- The BD field path caption label

Also remove the now-unused `va_ib_val` and `va_zvw_val` lines from `save_prive()` and remove the blur handlers that were on the old VA inputs.

- [ ] **Step 6: Test manually**

Run: `source .venv/bin/activate && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py`
- Navigate to Aangifte page
- Verify "Voorlopige Aanslagen" tab appears first but Winst is active
- Click VA tab, verify cards show for selected year
- Enter VA IB jaarbedrag, verify auto-save
- Click Hermatchen, verify BD transactions are matched
- Switch to Overzicht tab, verify Resultaat card shows correct VA
- Switch year, verify VA tab refreshes

- [ ] **Step 7: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add pages/aangifte.py
git commit -m "feat(va): new VA Beschikkingen tab on Aangifte page

Beschikking-based input (jaarbedrag, termijnen, kenmerk) with matched
bank payments display. Remove VA from Prive tab. Auto-save + hermatchen."
```

### Task 6: Dashboard — Correct Proration

**Files:**
- Modify: `pages/dashboard.py:68-109,191-229`

- [ ] **Step 1: Update imports**

Add to imports in `pages/dashboard.py`:

```python
from database import get_va_betaald_totaal
from components.fiscal_utils import bereken_va_betaald_theoretisch
```

- [ ] **Step 2: Replace proration logic in _compute_ib_estimate**

Replace the VA proration block (~lines 74-86) with:

```python
        annual_va_ib = data['voorlopige_aanslag']
        annual_va_zvw = data['voorlopige_aanslag_zvw']
        va_termijnen = data['va_termijnen']
        va_start_maand = data['va_start_maand']

        if jaar == huidig_jaar:
            # Primary: actual bank payments
            va_ib = await get_va_betaald_totaal(DB_PATH, jaar, 'va_ib')
            va_zvw = await get_va_betaald_totaal(DB_PATH, jaar, 'va_zvw')
            # Fallback: theoretical if no bank data
            if va_ib == 0 and annual_va_ib > 0:
                va_ib, _ = bereken_va_betaald_theoretisch(
                    annual_va_ib, va_termijnen, va_start_maand, date.today())
            if va_zvw == 0 and annual_va_zvw > 0:
                va_zvw, _ = bereken_va_betaald_theoretisch(
                    annual_va_zvw, va_termijnen, va_start_maand, date.today())
            va_ib_is_bank = await get_va_betaald_totaal(DB_PATH, jaar, 'va_ib') > 0
            month = date.today().month
        else:
            va_ib = annual_va_ib
            va_zvw = annual_va_zvw
            va_ib_is_bank = False
            month = 12
```

Update the return dict to include `va_ib_is_bank`:

```python
        return {
            'resultaat': f.resultaat,
            'netto_ib': f.netto_ib,
            'zvw': f.zvw,
            'va_ib_betaald': va_ib,
            'va_zvw_betaald': va_zvw,
            'prorated': jaar == huidig_jaar,
            'month': month,
            'va_is_bank': va_ib_is_bank,
        }
```

- [ ] **Step 3: Update KPI sub-detail label**

In the `ib_extra` function (~lines 206-224), update the VA label:

```python
        def ib_extra(d=ib_data, vt=va_totaal):
            with ui.column().classes('gap-0'):
                berekend = d['netto_ib'] + d['zvw']
                ui.label(f"Berekend: € {berekend:,.2f}").classes(
                    'text-caption tabular-nums')
                if vt > 0:
                    if d.get('va_is_bank'):
                        lbl = f"VA betaald: -€ {vt:,.2f}"
                    elif d['prorated']:
                        lbl = f"VA geschat t/m {MAANDEN[d['month']]}: -€ {vt:,.2f}"
                    else:
                        lbl = f"VA betaald: -€ {vt:,.2f}"
                    ui.label(lbl).classes('text-caption tabular-nums')
```

Add `MAANDEN` dict at module level or reuse from a shared location.

- [ ] **Step 4: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Test manually**

Run app, check dashboard:
- Current year: should show bank-based VA or theoretical fallback
- Past year: should show full VA amount

- [ ] **Step 6: Commit**

```bash
git add pages/dashboard.py
git commit -m "fix(va): correct dashboard proration — bank-based with theoretical fallback

Replaces incorrect annual*month/12 with actual bank payments (primary)
or 11-termijn-based calculation (fallback)."
```

### Task 7: Bank Page — Koppeling Label

**Files:**
- Modify: `pages/bank.py:56-68`

- [ ] **Step 1: Improve koppeling display format**

In `pages/bank.py`, find the row dict construction (~line 65) and update:

```python
        'koppeling': (
            f"VA IB {t.koppeling_id}" if t.koppeling_type == 'va_ib'
            else f"VA ZVW {t.koppeling_id}" if t.koppeling_type == 'va_zvw'
            else f"{t.koppeling_type} #{t.koppeling_id}" if t.koppeling_type
            else ''
        ),
```

- [ ] **Step 2: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add pages/bank.py
git commit -m "feat(va): show VA IB/ZVW labels for linked bank transactions"
```

### Task 8: Final Integration Test + Verification

- [ ] **Step 1: Run complete test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS (412 original + ~16 new)

- [ ] **Step 2: Manual end-to-end verification**

Run: `source .venv/bin/activate && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py`

Checklist:
1. Aangifte → VA tab shows for 2025
2. Enter IB=29851, ZVW=2859, termijnen=11, start=feb
3. Enter IB kenmerk: 1124 4126 4705 0001
4. Click Hermatchen → BD transactions get linked
5. IB card shows matched payments with totals
6. Switch to Overzicht → Resultaat card shows correct VA
7. Switch year to 2024 → VA tab shows 2024 data
8. Dashboard → Belasting prognose shows bank-based VA
9. Bank page → linked transactions show "VA IB 2025" label
10. Prive & aftrek tab → no VA fields present

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(va): integration fixes from manual testing"
```
