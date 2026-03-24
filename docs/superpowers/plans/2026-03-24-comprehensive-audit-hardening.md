# Comprehensive Audit Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the boekhouding app so it can safely replace Boekhouder for 2025+ IB-aangifte filing.

**Architecture:** Fix data integrity guards in database.py, add partner AHK to fiscal engine, tighten test tolerances, improve backup safety, add missing expense categories, and create export functions for km-logboek and uren-overzicht.

**Tech Stack:** Python 3.12, NiceGUI, aiosqlite, pytest, WeasyPrint

**Spec:** `docs/superpowers/specs/2026-03-24-comprehensive-audit-design.md`

---

## File Map

| File | Changes |
|---|---|
| `database.py` | D1: werkdag delete guard, D2: factuur delete guard, D5: status transition validation |
| `pages/werkdagen.py` | D1: filter bulk delete by status |
| `pages/facturen.py` | D2: status-aware delete confirmation |
| `pages/jaarafsluiting.py` | D3: show matches for review before applying |
| `fiscal/berekeningen.py` | F3/C1: partner AHK, F4: graceful error handling |
| `fiscal/heffingskortingen.py` | F3: reuse AHK for partner income |
| `fiscal/berekeningen.py` | F3: add partner_ahk to FiscaalResultaat + partner_inkomen param |
| `components/utils.py` | CR1: add missing expense categories |
| `pages/instellingen.py` | O1+O2: backup safety fixes |
| `tests/test_fiscal.py` | F7: tighten tolerances |
| `tests/test_database.py` | D1/D2: new guard tests |
| `tests/test_data_integrity.py` | New: status guard tests |

---

## Tier 1 — Must Fix (filing-critical / data-loss risk)

### Task 1: Guard werkdag deletion by status (D1)

**Files:**
- Modify: `database.py:704-707`
- Modify: `pages/werkdagen.py:114-134`
- Test: `tests/test_data_integrity.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_data_integrity.py`:

```python
"""Tests for data integrity guards."""
import pytest
from database import (
    add_klant, add_werkdag, delete_werkdag, get_werkdagen,
    add_factuur, link_werkdagen_to_factuur, init_db, DB_PATH,
)
from pathlib import Path

TEST_DB = Path('/tmp/test_integrity.sqlite3')


@pytest.fixture(autouse=True)
async def setup_db():
    if TEST_DB.exists():
        TEST_DB.unlink()
    await init_db(TEST_DB)
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.mark.asyncio
async def test_delete_ongefactureerd_werkdag_succeeds():
    """Werkdag with status 'ongefactureerd' can be deleted."""
    klant_id = await add_klant(TEST_DB, naam='Test', tarief_uur=100)
    wd_id = await add_werkdag(TEST_DB, datum='2025-01-15', klant_id=klant_id,
                               uren=8, km=0, tarief=100, km_tarief=0)
    await delete_werkdag(TEST_DB, werkdag_id=wd_id)
    rows = await get_werkdagen(TEST_DB)
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_delete_gefactureerd_werkdag_raises():
    """Werkdag with status 'gefactureerd' cannot be deleted."""
    klant_id = await add_klant(TEST_DB, naam='Test', tarief_uur=100)
    wd_id = await add_werkdag(TEST_DB, datum='2025-01-15', klant_id=klant_id,
                               uren=8, km=0, tarief=100, km_tarief=0)
    # Create factuur and link
    f_id = await add_factuur(TEST_DB, nummer='2025-001', klant_id=klant_id,
                              datum='2025-01-31', totaal_bedrag=800)
    await link_werkdagen_to_factuur(TEST_DB, werkdag_ids=[wd_id],
                                     factuurnummer='2025-001')
    with pytest.raises(ValueError, match='gefactureerd'):
        await delete_werkdag(TEST_DB, werkdag_id=wd_id)


@pytest.mark.asyncio
async def test_delete_betaald_werkdag_raises():
    """Werkdag with status 'betaald' cannot be deleted."""
    klant_id = await add_klant(TEST_DB, naam='Test', tarief_uur=100)
    wd_id = await add_werkdag(TEST_DB, datum='2025-01-15', klant_id=klant_id,
                               uren=8, km=0, tarief=100, km_tarief=0)
    f_id = await add_factuur(TEST_DB, nummer='2025-001', klant_id=klant_id,
                              datum='2025-01-31', totaal_bedrag=800)
    await link_werkdagen_to_factuur(TEST_DB, werkdag_ids=[wd_id],
                                     factuurnummer='2025-001')
    from database import update_factuur_status
    await update_factuur_status(TEST_DB, f_id, 'betaald', '2025-02-15')
    with pytest.raises(ValueError, match='betaald'):
        await delete_werkdag(TEST_DB, werkdag_id=wd_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_data_integrity.py -v`
Expected: 2 of 3 tests FAIL (the `raises` tests, because no guard exists yet)

- [ ] **Step 3: Implement werkdag delete guard**

In `database.py`, replace `delete_werkdag` (lines 704-707):

```python
async def delete_werkdag(db_path: Path = DB_PATH, werkdag_id: int = 0) -> None:
    """Delete a werkdag. Raises ValueError if status is not 'ongefactureerd'."""
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "SELECT status FROM werkdagen WHERE id = ?", (werkdag_id,))
        row = await cursor.fetchone()
        if row and row['status'] != 'ongefactureerd':
            raise ValueError(
                f"Kan werkdag niet verwijderen: status is '{row['status']}'. "
                "Verwijder eerst de gekoppelde factuur.")
        await conn.execute("DELETE FROM werkdagen WHERE id = ?", (werkdag_id,))
        await conn.commit()
```

- [ ] **Step 4: Update werkdagen page to catch ValueError**

In `pages/werkdagen.py`, update the bulk delete handler (around line 121):

```python
async def confirm_bulk_delete():
    skipped = 0
    deleted = 0
    for wid in ids:
        try:
            await delete_werkdag(DB_PATH, werkdag_id=wid)
            deleted += 1
        except ValueError:
            skipped += 1
    dlg.close()
    msg = f'{deleted} werkdag(en) verwijderd'
    if skipped:
        msg += f', {skipped} overgeslagen (gefactureerd/betaald)'
    ui.notify(msg, type='positive' if not skipped else 'warning')
    await refresh_table()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_data_integrity.py -v`
Expected: ALL 3 PASS

- [ ] **Step 6: Run full test suite to check no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v --tb=short`
Expected: All existing tests still pass

- [ ] **Step 7: Commit**

```bash
git add database.py pages/werkdagen.py tests/test_data_integrity.py
git commit -m "fix: guard werkdag deletion — block delete of gefactureerd/betaald werkdagen (D1)"
```

---

### Task 2: Guard factuur deletion by status (D2)

**Files:**
- Modify: `database.py:832-859`
- Modify: `pages/facturen.py` (delete confirmation dialog)
- Test: `tests/test_data_integrity.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_data_integrity.py`:

```python
from database import delete_factuur, update_factuur_status


@pytest.mark.asyncio
async def test_delete_concept_factuur_succeeds():
    """Concept factuur can be deleted, werkdagen reset to ongefactureerd."""
    klant_id = await add_klant(TEST_DB, naam='Test', tarief_uur=100)
    wd_id = await add_werkdag(TEST_DB, datum='2025-01-15', klant_id=klant_id,
                               uren=8, km=0, tarief=100, km_tarief=0)
    f_id = await add_factuur(TEST_DB, nummer='2025-001', klant_id=klant_id,
                              datum='2025-01-31', totaal_bedrag=800)
    await link_werkdagen_to_factuur(TEST_DB, werkdag_ids=[wd_id],
                                     factuurnummer='2025-001')
    await delete_factuur(TEST_DB, factuur_id=f_id)
    rows = await get_werkdagen(TEST_DB)
    assert rows[0].status == 'ongefactureerd'


@pytest.mark.asyncio
async def test_delete_betaald_factuur_raises():
    """Betaald factuur cannot be deleted."""
    klant_id = await add_klant(TEST_DB, naam='Test', tarief_uur=100)
    f_id = await add_factuur(TEST_DB, nummer='2025-001', klant_id=klant_id,
                              datum='2025-01-31', totaal_bedrag=800)
    await update_factuur_status(TEST_DB, f_id, 'betaald', '2025-02-15')
    with pytest.raises(ValueError, match='betaald'):
        await delete_factuur(TEST_DB, factuur_id=f_id)


@pytest.mark.asyncio
async def test_delete_verstuurd_factuur_raises():
    """Verstuurd factuur cannot be deleted."""
    klant_id = await add_klant(TEST_DB, naam='Test', tarief_uur=100)
    f_id = await add_factuur(TEST_DB, nummer='2025-001', klant_id=klant_id,
                              datum='2025-01-31', totaal_bedrag=800)
    await update_factuur_status(TEST_DB, f_id, 'verstuurd')
    with pytest.raises(ValueError, match='verstuurd'):
        await delete_factuur(TEST_DB, factuur_id=f_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_data_integrity.py::test_delete_betaald_factuur_raises tests/test_data_integrity.py::test_delete_verstuurd_factuur_raises -v`
Expected: FAIL (no guard yet)

- [ ] **Step 3: Implement factuur delete guard**

In `database.py`, update `delete_factuur` (line 832):

```python
async def delete_factuur(db_path: Path = DB_PATH, factuur_id: int = 0) -> None:
    """Delete a factuur: unlink werkdagen, remove PDF, delete record.

    Raises ValueError if factuur status is 'verstuurd' or 'betaald'.
    Only concept facturen can be deleted.
    """
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "SELECT nummer, pdf_pad, status FROM facturen WHERE id = ?",
            (factuur_id,))
        row = await cursor.fetchone()
        if not row:
            return
        if row['status'] in ('verstuurd', 'betaald'):
            raise ValueError(
                f"Kan factuur niet verwijderen: status is '{row['status']}'. "
                "Zet de factuur eerst terug naar 'concept'.")
        nummer = row['nummer']
        pdf_pad = row['pdf_pad']

        # Unlink werkdagen
        await conn.execute(
            "UPDATE werkdagen SET status = 'ongefactureerd', factuurnummer = '' "
            "WHERE factuurnummer = ?", (nummer,))

        # Delete factuur record
        await conn.execute("DELETE FROM facturen WHERE id = ?", (factuur_id,))
        await conn.commit()

        # Remove PDF file if it exists
        if pdf_pad:
            pdf_file = Path(pdf_pad)
            if pdf_file.exists():
                pdf_file.unlink()
```

- [ ] **Step 4: Update facturen page delete dialog**

In `pages/facturen.py`, find the delete confirmation dialog and wrap the `delete_factuur` call in a try/except that shows a notification on ValueError. Also add the status to the confirmation message.

- [ ] **Step 5: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_data_integrity.py -v`
Expected: ALL PASS

- [ ] **Step 6: Full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v --tb=short`

- [ ] **Step 7: Commit**

```bash
git add database.py pages/facturen.py tests/test_data_integrity.py
git commit -m "fix: guard factuur deletion — block delete of verstuurd/betaald facturen (D2)"
```

---

### Task 3: Calculate partner AHK (C1/F3)

**Files:**
- Modify: `fiscal/berekeningen.py:56-100` (add partner_ahk field to FiscaalResultaat)
- Modify: `fiscal/berekeningen.py:186,384-393` (add partner_inkomen param + AHK calculation)
- Modify: `pages/aangifte.py:93-105` (pass partner_inkomen to bereken_volledig)
- Test: `tests/test_fiscal.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_fiscal.py`:

```python
class TestPartnerAHK:
    """Partner AHK berekening — Boekhouder 2024 reference: AHK partner = 116."""

    def test_partner_ahk_2024(self):
        """Boekhouder 2024: partner loon 39965, loonheffing 6878 -> AHK ~116."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998,
            woz=655000, hypotheekrente=6951,
            voorlopige_aanslag=30303,
            voorlopige_aanslag_zvw=2667,
            partner_inkomen=39965,
        )
        assert hasattr(result, 'partner_ahk')
        assert abs(result.partner_ahk - 116) < 5

    def test_partner_ahk_zero_when_no_partner(self):
        """Without partner income, partner AHK should be 0."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
        )
        assert result.partner_ahk == 0

    def test_partner_ahk_high_income_zero(self):
        """Partner with very high income gets AHK = 0 (fully phased out)."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
            partner_inkomen=120000,
        )
        assert result.partner_ahk == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestPartnerAHK -v`
Expected: FAIL (no partner_inkomen param, no partner_ahk field)

- [ ] **Step 3: Add partner_ahk field to FiscaalResultaat**

In `fiscal/berekeningen.py`, find the `FiscaalResultaat` dataclass (line 56) and add after the existing fields:

```python
partner_ahk: float = 0.0
```

- [ ] **Step 4: Add partner_inkomen param and calculation to bereken_volledig**

In `fiscal/berekeningen.py`, add `partner_inkomen: float = 0` parameter to `bereken_volledig` signature (after `ew_naar_partner`).

After the AHK calculation (around line 387), add:

```python
# Partner AHK: calculate if partner income is provided
if partner_inkomen > 0:
    r.partner_ahk = bereken_algemene_heffingskorting(
        partner_inkomen, jaar, params)
else:
    r.partner_ahk = 0.0
```

- [ ] **Step 5: Wire partner_inkomen from aangifte page to bereken_volledig**

In `pages/aangifte.py:93-105`, the call to `bereken_volledig` needs `partner_inkomen`. Add after the `ew_naar_partner` line (105):

```python
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
            partner_inkomen=data['params'].partner_bruto_loon or 0,
        )
```

- [ ] **Step 6: Display partner AHK in overzicht tab**

In `pages/aangifte.py`, in the Overzicht tab section, add a line showing `partner_ahk` under the partner details with a copy-to-clipboard button and BD field path label.

- [ ] **Step 7: Run tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestPartnerAHK -v`
Expected: ALL PASS

- [ ] **Step 8: Full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v --tb=short`

- [ ] **Step 9: Commit**

```bash
git add fiscal/berekeningen.py pages/aangifte.py tests/test_fiscal.py
git commit -m "feat: calculate partner AHK in fiscal waterfall (C1/F3)"
```

---

### Task 4: Jaarafsluiting — show matches for review before applying (D3)

**Files:**
- Modify: `pages/jaarafsluiting.py:44-51`

- [ ] **Step 1: Replace auto-apply with review dialog**

In `pages/jaarafsluiting.py`, replace lines 44-51:

```python
# Find potential matches but do NOT auto-apply
matches = await find_factuur_matches(DB_PATH)
if matches:
    # Store matches for review dialog
    async def apply_reviewed_matches():
        await apply_factuur_matches(DB_PATH, matches)
        ui.notify(
            f'{len(matches)} facturen als betaald gemarkeerd',
            type='positive')
        match_dialog.close()
        await refresh_content()

    with ui.dialog() as match_dialog, ui.card().classes('w-96'):
        ui.label('Factuur-betalingen gevonden').classes('text-h6')
        ui.label(f'{len(matches)} facturen matchen met bankbetalingen:')
        with ui.column().classes('w-full gap-1 q-my-sm'):
            for m in matches[:10]:  # Show first 10
                ui.label(f"• {m['factuur_nummer']} — €{m['factuur_bedrag']:.2f} "
                         f"→ {m['bank_datum']}").classes('text-caption')
            if len(matches) > 10:
                ui.label(f"... en {len(matches) - 10} meer").classes(
                    'text-caption text-grey')
        with ui.row().classes('w-full justify-end'):
            ui.button('Annuleren', on_click=match_dialog.close).props('flat')
            ui.button('Toepassen', on_click=apply_reviewed_matches).props(
                'color=positive')
    match_dialog.open()
```

- [ ] **Step 2: Test manually** — open jaarafsluiting page, verify dialog appears instead of auto-apply

- [ ] **Step 3: Commit**

```bash
git add pages/jaarafsluiting.py
git commit -m "fix: jaarafsluiting shows match review dialog instead of auto-applying (D3)"
```

---

### Task 5: Tighten Boekhouder test tolerances (F7)

**Files:**
- Modify: `tests/test_fiscal.py`

- [ ] **Step 1: Identify all loose tolerance assertions**

Search `tests/test_fiscal.py` for assertions with tolerance > 2:
- Lines with `< 50`, `< 100`, `< 200`, `< 300`

- [ ] **Step 2: Tighten each assertion**

For each Boekhouder-validated value, tighten to ≤ €1 where the expected value is known precisely, or ≤ €5 where it depends on float arithmetic. Update the expected values to match exact calculations.

Key assertions to tighten (from test_fiscal.py):
- `test_volledig_2024` (line 304): `< 100` → `< 5` for belastbare_winst
- `test_volledig_2024` (line 307): `< 200` → `< 5` for verzamelinkomen
- `test_volledig_2024` (line 310): `< 10` → `< 2` for arbeidskorting
- `test_volledig_2024` (line 315): `< 50` → `< 5` for tariefsaanpassing
- `test_boekhouder_2023_volledig` (line 280): `< 100` → `< 5` for verzamelinkomen

- [ ] **Step 3: Run the tightened tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py -v --tb=long`

**Important:** Some test comments note they are approximate (e.g., "EW still included", "not yet refined"). Run the tests first and check actual vs expected values before finalizing tolerances. If a tightened assertion fails by €10-20 due to known approximations in the test setup (not the engine), adjust the expected value or keep tolerance at `< 10` for that specific case. The goal is: any tolerance > €5 needs a comment explaining why.

- [ ] **Step 4: Commit**

```bash
git add tests/test_fiscal.py
git commit -m "test: tighten Boekhouder fiscal test tolerances to ≤€5 (F7)"
```

---

## Tier 2 — Should Fix

### Task 6: Add missing expense categories (CR1)

**Files:**
- Modify: `components/utils.py:3-14`

- [ ] **Step 1: Add categories**

In `components/utils.py`, update `KOSTEN_CATEGORIEEN`:

```python
KOSTEN_CATEGORIEEN = [
    'Pensioenpremie SPH',
    'Telefoon/KPN',
    'Verzekeringen',
    'Accountancy/software',
    'Representatie',
    'Lidmaatschappen',
    'Kleine aankopen',
    'Scholingskosten',
    'Bankkosten',
    'Automatisering',
    'Overige kosten',
    'Investeringen',
]
```

- [ ] **Step 2: Run tests to check no regressions** (category list is used in UI dropdowns and bank categorization)

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v --tb=short`

- [ ] **Step 3: Commit**

```bash
git add components/utils.py
git commit -m "feat: add Automatisering and Overige kosten expense categories (CR1)"
```

---

### Task 7: Fix backup safety (O1 + O2)

**Files:**
- Modify: `pages/instellingen.py:437-462`

- [ ] **Step 1: Fix WAL checkpoint**

In `pages/instellingen.py` line 438, change:
```python
await conn.execute("PRAGMA wal_checkpoint(FULL)")
```
to:
```python
await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
```

- [ ] **Step 2: Fix backup cleanup timing**

Replace the 10-second cleanup (lines 456-462) with a longer timeout:

```python
async def _cleanup():
    await asyncio.sleep(120)  # 2 minutes for download
    try:
        backup_path.unlink(missing_ok=True)
    except OSError:
        pass
asyncio.create_task(_cleanup())
```

- [ ] **Step 3: Commit**

```bash
git add pages/instellingen.py
git commit -m "fix: backup safety — TRUNCATE checkpoint + 2min cleanup delay (O1/O2)"
```

---

### Task 8: Lijfrente jaarruimte warning (C5)

**Files:**
- Modify: `fiscal/berekeningen.py` (add warning)

- [ ] **Step 1: Add warning in bereken_volledig**

After the lijfrente is applied (around where `d_lijfrente` is used), add:

```python
if lijfrente > 0:
    # Jaarruimte rough check: max ~30% of premiegrondslag is a reasonable upper bound
    max_reasonable = r.fiscale_winst * 0.30 if r.fiscale_winst > 0 else 15000
    if lijfrente > max_reasonable:
        w.append(f"Lijfrentepremie (€{lijfrente:,.0f}) lijkt hoog. "
                 "Controleer of dit binnen uw jaarruimte valt via de "
                 "Belastingdienst jaarruimte rekenhulp.")
```

- [ ] **Step 2: Run tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py -v --tb=short`

- [ ] **Step 3: Commit**

```bash
git add fiscal/berekeningen.py
git commit -m "feat: add lijfrente jaarruimte warning in fiscal waterfall (C5)"
```

---

### Task 9: Box 3 rendement formula fix (F1)

**Files:**
- Modify: `fiscal/berekeningen.py:146-162`
- Test: `tests/test_fiscal.py`

- [ ] **Step 1: Write test for correct Box 3 with mixed assets**

Add test in `tests/test_fiscal.py`:

```python
class TestBox3Correct:
    """Box 3 must use official BD per-category rendement method."""

    def test_box3_bank_only_2024(self):
        """Bank only: voordeel = bank_rendement on grondslag portion."""
        result = bereken_box3(
            bank=50000, overig=0, schulden=0,
            params=FISCALE_PARAMS[2024], fiscaal_partner=True)
        # Grondslag = 50000 - 0 - 2*57000 = 0 (under heffingsvrij)
        assert result.belasting == 0

    def test_box3_above_heffingsvrij_2024(self):
        """Bank above heffingsvrij: rendement on grondslag at bank rate."""
        result = bereken_box3(
            bank=150000, overig=0, schulden=0,
            params=FISCALE_PARAMS[2024], fiscaal_partner=True)
        # Grondslag = 150000 - 114000 = 36000
        # Voordeel = 36000 * 1.44% = 518.40
        # Belasting = 518.40 * 36% = 186.62
        assert abs(result.belasting - 186.62) < 1
```

- [ ] **Step 2: Fix the rendement formula**

Replace lines 155-160 in `fiscal/berekeningen.py`:

```python
# Official BD method: apply rendement percentages per category,
# then allocate proportionally to grondslag
netto_vermogen = totaal_bezittingen - schulden
if netto_vermogen > 0 and grondslag > 0:
    # Weighted rendement rate across all categories
    rendement_ratio = totaal_rendement / netto_vermogen
    voordeel = grondslag * rendement_ratio
else:
    voordeel = 0
```

Note: For the user's scenario (bank + schulden only, no overige bezittingen), the current weighted-average formula is mathematically equivalent to the official BD per-category method. This task adds the division-by-zero guard and tests. The full per-category BD method would only be needed if `overige_bezittingen > 0` (beleggingen/crypto), which is not the case. If that changes, revisit F1 in the spec.

- [ ] **Step 3: Run tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py -k box3 -v`

- [ ] **Step 4: Commit**

```bash
git add fiscal/berekeningen.py tests/test_fiscal.py
git commit -m "fix: Box 3 rendement formula — guard division by zero, add tests (F1)"
```

---

### Task 10: Uren-overzicht CSV export (C4)

**Files:**
- Modify: `pages/werkdagen.py` (add export button)

- [ ] **Step 1: Add format_datum import and uren-overzicht export**

In `pages/werkdagen.py` line 5, add `format_datum` to the import:
```python
from components.utils import format_euro, format_datum, generate_csv
```

Then in the toolbar area (near the existing CSV export), add:

```python
async def export_uren_overzicht():
    """Export uren-overzicht as CSV for urencriterium documentation."""
    rows = await get_werkdagen(DB_PATH, jaar=state['jaar'])
    # Filter to urennorm=1 only (achterwacht doesn't count)
    uren_rows = [w for w in rows if w.urennorm == 1]
    headers = ['Datum', 'Klant', 'Locatie', 'Uren', 'Activiteit']
    csv_rows = [[format_datum(w.datum), w.klant_naam, w.locatie or '',
                  str(w.uren), w.activiteit] for w in uren_rows]
    totaal = sum(w.uren for w in uren_rows)
    csv_rows.append(['', '', 'TOTAAL', str(totaal), ''])
    csv_data = generate_csv(headers, csv_rows)
    ui.download(
        csv_data.encode('utf-8-sig'),
        f'urenregistratie_{state["jaar"]}.csv')

ui.button('Exporteer urenregistratie', icon='schedule',
          on_click=export_uren_overzicht).props('outline')
```

- [ ] **Step 2: Test manually** — click the button, verify CSV contains per-day hours with total

- [ ] **Step 3: Commit**

```bash
git add pages/werkdagen.py
git commit -m "feat: add uren-overzicht CSV export for urencriterium documentation (C4)"
```

---

### Task 11: Km-logboek CSV export (C3)

**Files:**
- Modify: `pages/werkdagen.py` (add export button)

- [ ] **Step 1: Add km-logboek export**

```python
async def export_km_logboek():
    """Export km-logboek as CSV for Belastingdienst documentation."""
    from components.utils import generate_csv
    from database import get_klant_locaties, get_klanten
    rows = await get_werkdagen(DB_PATH, jaar=state['jaar'])
    klanten = {k.id: k for k in await get_klanten(DB_PATH)}
    km_rows = [w for w in rows if w.km and w.km > 0]
    headers = ['Datum', 'Klant', 'Locatie', 'Vertrek', 'Bestemming',
               'Retour km', 'Doel']
    csv_rows = []
    for w in km_rows:
        klant = klanten.get(w.klant_id)
        bestemming = w.locatie or (klant.naam if klant else '')
        csv_rows.append([
            format_datum(w.datum), w.klant_naam, w.locatie or '',
            'Thuisadres', bestemming, str(w.km), 'Waarneming huisartspraktijk',
        ])
    totaal = sum(w.km for w in km_rows)
    csv_rows.append(['', '', '', '', 'TOTAAL', str(totaal), ''])
    csv_data = generate_csv(headers, csv_rows)
    ui.download(
        csv_data.encode('utf-8-sig'),
        f'km_logboek_{state["jaar"]}.csv')

ui.button('Exporteer km-logboek', icon='directions_car',
          on_click=export_km_logboek).props('outline')
```

- [ ] **Step 2: Test manually**

- [ ] **Step 3: Commit**

```bash
git add pages/werkdagen.py
git commit -m "feat: add km-logboek CSV export for Belastingdienst documentation (C3)"
```

---

### Task 12: Non-werkdag business km (C2)

**Files:**
- Modify: `database.py` (add migration for werkdag type/non-patient flag)
- Modify: `pages/werkdagen.py` (allow adding km-only entries)
- Modify: `components/werkdag_form.py`

- [ ] **Step 1: Design** — The simplest approach is to allow werkdagen with `uren=0` and `urennorm=0` (already supported) but `km > 0`. These represent non-patient business trips. The werkdag form already supports custom uren/km, so the only change needed is:
  - Allow `uren=0` in the form validation (currently CHECK constraint requires `uren > 0`)
  - Add a "type" hint in the form (e.g., "Zakelijke rit (geen patiëntenzorg)")

- [ ] **Step 2: Add DB migration to relax CHECK constraint**

In `database.py` `init_db`, add a new migration. SQLite cannot ALTER a CHECK constraint, so the migration must recreate the table. Follow the existing migration pattern (see migrations 12-14 for examples). The full column list from the schema (line 43-60) must be replicated exactly, changing only `CHECK (uren > 0)` to `CHECK (uren >= 0)`:

```python
# Migration 18: Allow uren=0 for non-patient business km entries (C2)
if current_version < 18:
    await conn.executescript("""
        CREATE TABLE werkdagen_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datum TEXT NOT NULL,
            klant_id INTEGER NOT NULL REFERENCES klanten(id),
            code TEXT DEFAULT '',
            activiteit TEXT DEFAULT 'Waarneming dagpraktijk',
            locatie TEXT DEFAULT '',
            uren REAL NOT NULL CHECK (uren >= 0),
            km REAL DEFAULT 0,
            tarief REAL NOT NULL,
            km_tarief REAL DEFAULT 0.23,
            status TEXT NOT NULL DEFAULT 'ongefactureerd'
                CHECK (status IN ('ongefactureerd', 'gefactureerd', 'betaald')),
            factuurnummer TEXT DEFAULT '',
            opmerking TEXT DEFAULT '',
            urennorm INTEGER DEFAULT 1,
            locatie_id INTEGER REFERENCES klant_locaties(id) ON DELETE SET NULL
        );
        INSERT INTO werkdagen_new SELECT * FROM werkdagen;
        DROP TABLE werkdagen;
        ALTER TABLE werkdagen_new RENAME TO werkdagen;
        CREATE INDEX IF NOT EXISTS idx_werkdagen_datum ON werkdagen(datum);
        CREATE INDEX IF NOT EXISTS idx_werkdagen_klant ON werkdagen(klant_id);
    """)
```

**Warning:** This is the most complex task. The table recreation must preserve all data, foreign keys, and indices. Test with a backup of the real DB before running on production data. The werkdag_form.py also needs updating to allow uren=0 in its validation (check for min value on the uren input field).

- [ ] **Step 3: Test** — add werkdag with uren=0, km=30 for "Congres KNMG"

- [ ] **Step 4: Commit**

```bash
git add database.py pages/werkdagen.py components/werkdag_form.py
git commit -m "feat: allow non-werkdag business km entries with uren=0 (C2)"
```

---

### Deferred: CR2 — Privé-gebruik as explicit W&V line

**Rationale:** The app currently handles privé-gebruik via `zakelijk_pct` on investment assets. Yuki books it as a negative expense line (€-446 in 2024). Making this an explicit W&V line would require: (1) tracking which regular expenses have private use, (2) computing the private portion, (3) displaying it as a negative line in the jaarstukken. This is a significant modeling change for a €446 discrepancy that does not affect the fiscal waterfall (the net cost fed to `bereken_volledig` is the same). Deferred to a future iteration if W&V presentation matching Yuki format becomes a priority.

---

## Tier 3 — Nice to Have

### Task 13: Update "Boekhouder" label (C11)

**Files:**
- Modify: `components/document_specs.py`

- [ ] **Step 1: Update label**

Change `'Ingediende aangifte (Boekhouder)'` to `'Ingediende aangifte'`.

- [ ] **Step 2: Commit**

```bash
git add components/document_specs.py
git commit -m "fix: remove Boekhouder from ingediende aangifte label (C11)"
```

---

### Task 14: Status transition validation (D5)

**Files:**
- Modify: `database.py:773-798`
- Test: `tests/test_data_integrity.py`

- [ ] **Step 1: Write test**

```python
@pytest.mark.asyncio
async def test_invalid_status_transition_raises():
    """Cannot go from betaald back to concept."""
    klant_id = await add_klant(TEST_DB, naam='Test', tarief_uur=100)
    f_id = await add_factuur(TEST_DB, nummer='2025-001', klant_id=klant_id,
                              datum='2025-01-31', totaal_bedrag=800)
    await update_factuur_status(TEST_DB, f_id, 'betaald', '2025-02-15')
    with pytest.raises(ValueError, match='niet toegestaan'):
        await update_factuur_status(TEST_DB, f_id, 'concept')
```

- [ ] **Step 2: Add transition validation**

```python
VALID_TRANSITIONS = {
    'concept': {'verstuurd', 'betaald'},
    'verstuurd': {'betaald', 'concept'},  # allow revert to concept
    'betaald': {'verstuurd'},  # allow un-mark betaald
}

# In update_factuur_status, before the UPDATE:
cur = await conn.execute("SELECT status FROM facturen WHERE id = ?", (factuur_id,))
current = (await cur.fetchone())['status']
if status not in VALID_TRANSITIONS.get(current, set()):
    raise ValueError(
        f"Status overgang '{current}' → '{status}' niet toegestaan")
```

- [ ] **Step 3: Run tests + commit**

```bash
git add database.py tests/test_data_integrity.py
git commit -m "fix: validate factuur status transitions (D5)"
```

---

### Task 15: Graceful fiscal engine error handling (F4)

**Files:**
- Modify: `fiscal/berekeningen.py:207-220`

- [ ] **Step 1: Wrap Decimal conversions**

At the top of `bereken_volledig`, add input validation:

```python
required_keys = ['kia_ondergrens', 'kia_bovengrens', 'kia_pct',
                 'zelfstandigenaftrek', 'mkb_vrijstelling_pct',
                 'schijf1_grens', 'schijf1_tarief', 'schijf2_tarief',
                 'zvw_max_grondslag', 'zvw_pct']
missing = [k for k in required_keys if k not in params]
if missing:
    raise ValueError(
        f"Fiscale parameters incompleet voor {params.get('jaar', '?')}: "
        f"ontbrekend: {', '.join(missing)}")
```

- [ ] **Step 2: Run tests + commit**

```bash
git add fiscal/berekeningen.py
git commit -m "fix: validate required fiscal params before calculation (F4)"
```

---

## Summary

| Task | Finding | Tier | Est. |
|---|---|---|---|
| 1 | Werkdag delete guard | 1 | 5 min |
| 2 | Factuur delete guard | 1 | 5 min |
| 3 | Partner AHK calculation | 1 | 10 min |
| 4 | Jaarafsluiting match review | 1 | 5 min |
| 5 | Tighten test tolerances | 1 | 10 min |
| 6 | Missing expense categories | 2 | 2 min |
| 7 | Backup safety | 2 | 2 min |
| 8 | Lijfrente warning | 2 | 3 min |
| 9 | Box 3 formula | 2 | 5 min |
| 10 | Uren-overzicht export | 2 | 5 min |
| 11 | Km-logboek export | 2 | 5 min |
| 12 | Non-werkdag business km | 2 | 10 min |
| 13 | Boekhouder label fix | 3 | 1 min |
| 14 | Status transition validation | 3 | 5 min |
| 15 | Fiscal params validation | 3 | 3 min |
