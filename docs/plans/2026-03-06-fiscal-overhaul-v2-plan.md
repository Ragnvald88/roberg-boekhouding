# Fiscal Overhaul v2 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make every fiscal parameter DB-configurable (zero code changes for new tax years), complete the jaarafsluiting display, and transform the aangifte page into a tax filing preparation tool with Box 1+3 summary and PDF export.

**Architecture:** Six phases: (1) Fix data discrepancies + add DB columns, (2) DB-driven AK brackets + PVV rates + Box 3 engine, (3) Complete jaarafsluiting display + PDF, (4) Instellingen UI for new params, (5) Aangifte page overhaul with tabs, (6) Docs cleanup. Each phase is independently testable and deployable.

**Tech Stack:** Python 3.12+, NiceGUI 3.8 (Quasar/Vue), SQLite via aiosqlite, WeasyPrint + Jinja2 for PDF, pytest.

**Reference:**
- Design: `docs/plans/2026-03-06-fiscal-overhaul-v2-design.md`
- Tests: `tests/test_fiscal.py` (97 passing)
- Engine: `fiscal/berekeningen.py`, `fiscal/heffingskortingen.py`
- Test command: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

---

## Phase 1: Data Foundation

### Task 1: Fix startersaftrek 2026 + minor ZVW rounding

**Files:**
- Modify: `import_/seed_data.py:93` (startersaftrek 2026)
- Modify: `tests/test_fiscal.py` (test params for 2026)

**Context:** Web research confirmed startersaftrek is NOT abolished in 2026 — it remains €2,123. Our seed data has `None`. Also fix minor ZVW max rounding: 2024 should be 71624 (not 71628), 2025 should be 75860 (not 75864). These are minor but we should be precise.

**Step 1: Fix seed_data.py**

In `import_/seed_data.py`, change line 93:
```python
# BEFORE:
'startersaftrek': None,

# AFTER:
'startersaftrek': 2123,
```

Also fix ZVW max values (line 55 and 82):
```python
# 2024 (line 55): BEFORE: 71628 → AFTER: 71624
# 2025 (line 82): BEFORE: 75864 → AFTER: 75860
```

**Step 2: Fix test_fiscal.py params**

In `tests/test_fiscal.py`, find the `FISCALE_PARAMS` dict and apply the same fixes:
- 2026 `startersaftrek`: `None` → `2123`
- 2024 `zvw_max_grondslag`: `71628` → `71624`
- 2025 `zvw_max_grondslag`: `75864` → `75860`

**Step 3: Add test for startersaftrek 2026**

Add to `tests/test_fiscal.py` in `TestVolledig`:
```python
def test_startersaftrek_2026_not_abolished(self):
    """Startersaftrek 2026 is still €2,123 (confirmed by Belastingdienst)."""
    params = FISCALE_PARAMS[2026].copy()
    result = bereken_volledig(
        omzet=80000, kosten=0, afschrijvingen=0,
        representatie=0, investeringen_totaal=0,
        uren=1400, params=params,
    )
    assert result.startersaftrek == 2123
```

**Step 4: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py -v`
Expected: All pass (Boekhouder 2024 ZVW test may need tolerance adjustment for the 4-euro ZVW change).

If the Boekhouder 2024 ZVW test fails: The test asserts `abs(result.zvw - 4084) < 5`. With zvw_max 71624 instead of 71628, the ZVW changes by 5.32% × 4 ≈ €0.21. Should still pass within tolerance.

**Step 5: Commit**

```bash
git add import_/seed_data.py tests/test_fiscal.py
git commit -m "fix: startersaftrek 2026 = 2123 (not abolished), fix ZVW max rounding"
```

---

### Task 2: Add new DB columns for AK brackets, PVV rates, and Box 3

**Files:**
- Modify: `database.py:176-183` (migration loop in `init_db`)
- Modify: `database.py:813-852` (`_row_to_fiscale_params`)
- Modify: `database.py:877-921` (`upsert_fiscale_params`)
- Modify: `models.py:104-144` (`FiscaleParams` dataclass)

**Context:** Add 11 new columns to `fiscale_params`: arbeidskorting_brackets (TEXT), pvv_aow/anw/wlz_pct (3 REAL), box3 input fields (3 REAL), box3 parameter fields (5 REAL). Follow the existing idempotent ALTER TABLE migration pattern.

**Step 1: Add fields to FiscaleParams dataclass**

In `models.py`, add after `partner_loonheffing` (line 144):
```python
    # Arbeidskorting brackets as JSON (DB-driven, fallback to code constants)
    arbeidskorting_brackets: str = ''
    # PVV component rates (DB-driven, fallback to hardcoded constants)
    pvv_aow_pct: float = 17.90
    pvv_anw_pct: float = 0.10
    pvv_wlz_pct: float = 9.65
    # Box 3 per-year inputs (peildatum 1 jan)
    box3_bank_saldo: float = 0.0
    box3_overige_bezittingen: float = 0.0
    box3_schulden: float = 0.0
    # Box 3 per-year fiscal parameters
    box3_heffingsvrij_vermogen: float = 57000
    box3_rendement_bank_pct: float = 1.03
    box3_rendement_overig_pct: float = 6.17
    box3_rendement_schuld_pct: float = 2.46
    box3_tarief_pct: float = 36.0
```

**Step 2: Add migration in init_db**

In `database.py`, in the migration loop (after line 183), add new columns:
```python
            ('arbeidskorting_brackets', "''"),  # TEXT needs quoted default
            ('pvv_aow_pct', 17.90),
            ('pvv_anw_pct', 0.10),
            ('pvv_wlz_pct', 9.65),
            ('box3_bank_saldo', 0),
            ('box3_overige_bezittingen', 0),
            ('box3_schulden', 0),
            ('box3_heffingsvrij_vermogen', 57000),
            ('box3_rendement_bank_pct', 1.03),
            ('box3_rendement_overig_pct', 6.17),
            ('box3_rendement_schuld_pct', 2.46),
            ('box3_tarief_pct', 36),
```

**IMPORTANT:** The `arbeidskorting_brackets` column is TEXT, not REAL. The current migration loop uses `REAL DEFAULT {default}`. We need to handle this specially:

Change the migration loop to detect TEXT columns:
```python
        for col, default in [
            # ... existing columns ...
            ('pvv_aow_pct', 17.90),
            ('pvv_anw_pct', 0.10),
            ('pvv_wlz_pct', 9.65),
            ('box3_bank_saldo', 0),
            ('box3_overige_bezittingen', 0),
            ('box3_schulden', 0),
            ('box3_heffingsvrij_vermogen', 57000),
            ('box3_rendement_bank_pct', 1.03),
            ('box3_rendement_overig_pct', 6.17),
            ('box3_rendement_schuld_pct', 2.46),
            ('box3_tarief_pct', 36),
        ]:
            try:
                await conn.execute(
                    f"ALTER TABLE fiscale_params ADD COLUMN {col} REAL DEFAULT {default}"
                )
            except Exception:
                pass

        # TEXT column migration (separate because type differs)
        try:
            await conn.execute(
                "ALTER TABLE fiscale_params ADD COLUMN arbeidskorting_brackets TEXT DEFAULT ''"
            )
        except Exception:
            pass
```

**Step 3: Update _row_to_fiscale_params**

In `database.py`, add after `partner_loonheffing` line (851):
```python
        arbeidskorting_brackets=_safe_get(r, 'arbeidskorting_brackets', '', keys) or '',
        pvv_aow_pct=_safe_get(r, 'pvv_aow_pct', 17.90, keys),
        pvv_anw_pct=_safe_get(r, 'pvv_anw_pct', 0.10, keys),
        pvv_wlz_pct=_safe_get(r, 'pvv_wlz_pct', 9.65, keys),
        box3_bank_saldo=_safe_get(r, 'box3_bank_saldo', 0, keys),
        box3_overige_bezittingen=_safe_get(r, 'box3_overige_bezittingen', 0, keys),
        box3_schulden=_safe_get(r, 'box3_schulden', 0, keys),
        box3_heffingsvrij_vermogen=_safe_get(r, 'box3_heffingsvrij_vermogen', 57000, keys),
        box3_rendement_bank_pct=_safe_get(r, 'box3_rendement_bank_pct', 1.03, keys),
        box3_rendement_overig_pct=_safe_get(r, 'box3_rendement_overig_pct', 6.17, keys),
        box3_rendement_schuld_pct=_safe_get(r, 'box3_rendement_schuld_pct', 2.46, keys),
        box3_tarief_pct=_safe_get(r, 'box3_tarief_pct', 36, keys),
```

**Step 4: Update upsert_fiscale_params**

This function needs the new columns added to both the INSERT column list and the VALUES. Also need to preserve box3 input values (like IB-inputs) across upserts.

Add to the `SELECT existing` query (line 882):
```sql
"box3_bank_saldo, box3_overige_bezittingen, box3_schulden"
```

Add to the INSERT columns and VALUES lists:
```python
# After pvv_premiegrondslag in INSERT:
arbeidskorting_brackets, pvv_aow_pct, pvv_anw_pct, pvv_wlz_pct,
box3_heffingsvrij_vermogen, box3_rendement_bank_pct,
box3_rendement_overig_pct, box3_rendement_schuld_pct, box3_tarief_pct,
box3_bank_saldo, box3_overige_bezittingen, box3_schulden
```

For the VALUES tuple, use `kwargs.get()` for configurable params and `existing[col]` for input fields.

**Step 5: Run database tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py -v`
Expected: All pass (schema migration is idempotent).

**Step 6: Commit**

```bash
git add database.py models.py
git commit -m "feat: add DB columns for AK brackets, PVV rates, Box 3"
```

---

### Task 3: Seed AK brackets as JSON + Box 3 defaults per year

**Files:**
- Modify: `import_/seed_data.py`
- Modify: `database.py` (data migration in `init_db`)

**Context:** Populate the `arbeidskorting_brackets` column with JSON for years 2023-2026, and set correct Box 3 rendement defaults per year.

**Step 1: Add AK bracket data + Box 3 defaults to seed_data.py**

Add to each year's params dict in `FISCALE_PARAMS`:

```python
import json

# At module level, define the brackets:
AK_BRACKETS = {
    2023: [
        {"lower": 0, "upper": 10741, "rate": 0.08231, "base": 0},
        {"lower": 10741, "upper": 23201, "rate": 0.29861, "base": 884},
        {"lower": 23201, "upper": 37691, "rate": 0.03085, "base": 4605},
        {"lower": 37691, "upper": 115295, "rate": -0.06510, "base": 5052},
        {"lower": 115295, "upper": None, "rate": 0, "base": 0},
    ],
    2024: [
        {"lower": 0, "upper": 11491, "rate": 0.08425, "base": 0},
        {"lower": 11491, "upper": 24821, "rate": 0.31433, "base": 968},
        {"lower": 24821, "upper": 39958, "rate": 0.02471, "base": 5158},
        {"lower": 39958, "upper": 124935, "rate": -0.06510, "base": 5532},
        {"lower": 124935, "upper": None, "rate": 0, "base": 0},
    ],
    2025: [
        {"lower": 0, "upper": 12169, "rate": 0.08053, "base": 0},
        {"lower": 12169, "upper": 26288, "rate": 0.30030, "base": 980},
        {"lower": 26288, "upper": 43071, "rate": 0.02258, "base": 5220},
        {"lower": 43071, "upper": 129078, "rate": -0.06510, "base": 5599},
        {"lower": 129078, "upper": None, "rate": 0, "base": 0},
    ],
    2026: [
        {"lower": 0, "upper": 11965, "rate": 0.08324, "base": 0},
        {"lower": 11965, "upper": 25845, "rate": 0.31009, "base": 996},
        {"lower": 25845, "upper": 45592, "rate": 0.01950, "base": 5300},
        {"lower": 45592, "upper": 132920, "rate": -0.06510, "base": 5685},
        {"lower": 132920, "upper": None, "rate": 0, "base": 0},
    ],
}

BOX3_DEFAULTS = {
    2023: {'heffingsvrij': 57000, 'bank': 0.36, 'overig': 6.17, 'schuld': 2.57, 'tarief': 32},
    2024: {'heffingsvrij': 57000, 'bank': 1.03, 'overig': 6.17, 'schuld': 2.46, 'tarief': 36},
    2025: {'heffingsvrij': 57684, 'bank': 1.28, 'overig': 6.04, 'schuld': 2.47, 'tarief': 36},
    2026: {'heffingsvrij': 57684, 'bank': 1.28, 'overig': 6.00, 'schuld': 2.70, 'tarief': 36},
}
```

Add to each year dict in FISCALE_PARAMS:
```python
'arbeidskorting_brackets': json.dumps(AK_BRACKETS[year]),
'pvv_aow_pct': 17.90,
'pvv_anw_pct': 0.10,
'pvv_wlz_pct': 9.65,
'box3_heffingsvrij_vermogen': BOX3_DEFAULTS[year]['heffingsvrij'],
'box3_rendement_bank_pct': BOX3_DEFAULTS[year]['bank'],
'box3_rendement_overig_pct': BOX3_DEFAULTS[year]['overig'],
'box3_rendement_schuld_pct': BOX3_DEFAULTS[year]['schuld'],
'box3_tarief_pct': BOX3_DEFAULTS[year]['tarief'],
```

**Step 2: Add data migration in init_db for existing DBs**

In `database.py` after the year_data migration block, add:
```python
        # Populate AK brackets for years that don't have them yet
        from import_.seed_data import AK_BRACKETS, BOX3_DEFAULTS
        import json
        for jaar in [2023, 2024, 2025, 2026]:
            await conn.execute(
                "UPDATE fiscale_params SET arbeidskorting_brackets = ? "
                "WHERE jaar = ? AND (arbeidskorting_brackets IS NULL OR arbeidskorting_brackets = '')",
                (json.dumps(AK_BRACKETS.get(jaar, [])), jaar)
            )
            b3 = BOX3_DEFAULTS.get(jaar, {})
            if b3:
                await conn.execute(
                    "UPDATE fiscale_params SET "
                    "box3_heffingsvrij_vermogen = ?, box3_rendement_bank_pct = ?, "
                    "box3_rendement_overig_pct = ?, box3_rendement_schuld_pct = ?, "
                    "box3_tarief_pct = ? "
                    "WHERE jaar = ? AND box3_heffingsvrij_vermogen = 57000 AND box3_rendement_bank_pct = 1.03",
                    (b3['heffingsvrij'], b3['bank'], b3['overig'], b3['schuld'], b3['tarief'], jaar)
                )
```

**Step 3: Run tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All pass.

**Step 4: Commit**

```bash
git add import_/seed_data.py database.py
git commit -m "feat: seed AK brackets as JSON + Box 3 defaults per year"
```

---

## Phase 2: Engine Flexibility

### Task 4: DB-driven arbeidskorting brackets

**Files:**
- Modify: `fiscal/heffingskortingen.py:66-90`
- Modify: `fiscal/berekeningen.py:306`
- Modify: `pages/jaarafsluiting.py:54` (pass brackets through params_dict)
- Test: `tests/test_fiscal.py`

**Step 1: Write failing tests**

Add to `tests/test_fiscal.py`:
```python
class TestDBDrivenArbeidskorting:
    """Arbeidskorting should work with JSON brackets from DB."""

    def test_json_brackets_match_python_constants_2024(self):
        """JSON brackets produce same result as Python constants."""
        import json
        brackets_json = json.dumps([
            {"lower": 0, "upper": 11491, "rate": 0.08425, "base": 0},
            {"lower": 11491, "upper": 24821, "rate": 0.31433, "base": 968},
            {"lower": 24821, "upper": 39958, "rate": 0.02471, "base": 5158},
            {"lower": 39958, "upper": 124935, "rate": -0.06510, "base": 5532},
            {"lower": 124935, "upper": None, "rate": 0, "base": 0},
        ])
        # Python constant result
        from_constant = bereken_arbeidskorting(94437, 2024)
        # JSON bracket result
        from_json = bereken_arbeidskorting(94437, 2024, brackets_json=brackets_json)
        assert from_json == from_constant

    def test_json_brackets_custom_future_year(self):
        """Custom brackets for a year not in Python constants."""
        import json
        brackets_json = json.dumps([
            {"lower": 0, "upper": 50000, "rate": 0.10, "base": 0},
            {"lower": 50000, "upper": None, "rate": 0, "base": 5000},
        ])
        result = bereken_arbeidskorting(30000, 2030, brackets_json=brackets_json)
        assert result == 3000.0  # 10% of 30000

    def test_empty_json_falls_back_to_constants(self):
        """Empty JSON string falls back to Python constants."""
        result = bereken_arbeidskorting(94437, 2024, brackets_json='')
        from_constant = bereken_arbeidskorting(94437, 2024)
        assert result == from_constant
```

**Step 2: Run to verify tests fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestDBDrivenArbeidskorting -v`
Expected: FAIL (bereken_arbeidskorting doesn't accept brackets_json parameter)

**Step 3: Implement DB-driven brackets in heffingskortingen.py**

Change `bereken_arbeidskorting` signature and body:
```python
def bereken_arbeidskorting(arbeidsinkomen: float, jaar: int,
                            brackets_json: str = '') -> float:
    """Calculate arbeidskorting using bracket tables.

    Uses JSON brackets from DB if provided, else falls back to Python constants.

    Args:
        arbeidsinkomen: Labour income (winst uit onderneming counts).
        jaar: Tax year.
        brackets_json: Optional JSON string of brackets from DB.
            Format: [{"lower": 0, "upper": 11491, "rate": 0.08425, "base": 0}, ...]
    """
    brackets = None

    if brackets_json:
        import json
        try:
            parsed = json.loads(brackets_json)
            brackets = [(b['lower'], b.get('upper'), b['rate'], b['base'])
                        for b in parsed]
        except (json.JSONDecodeError, KeyError, TypeError):
            brackets = None

    if not brackets:
        brackets = ARBEIDSKORTING_BRACKETS.get(jaar)
    if not brackets:
        known_years = sorted(ARBEIDSKORTING_BRACKETS.keys())
        if not known_years:
            return 0.0
        brackets = ARBEIDSKORTING_BRACKETS[known_years[-1]]

    for lower, upper, rate, base in brackets:
        if upper is None or arbeidsinkomen <= upper:
            korting = base + rate * (arbeidsinkomen - lower)
            return round(max(0, korting), 2)

    return 0.0
```

**Step 4: Update callers to pass brackets**

In `fiscal/berekeningen.py:306`, change:
```python
# BEFORE:
ak = bereken_arbeidskorting(r.fiscale_winst, jaar)

# AFTER:
ak = bereken_arbeidskorting(r.fiscale_winst, jaar,
                             brackets_json=params.get('arbeidskorting_brackets', ''))
```

In `pages/jaarafsluiting.py:54`, add to `_fiscale_params_to_dict`:
```python
'arbeidskorting_brackets': params.arbeidskorting_brackets,
```

**Step 5: Run ALL tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py -v`
Expected: All pass (new tests + existing tests, since JSON brackets produce same results).

**Step 6: Commit**

```bash
git add fiscal/heffingskortingen.py fiscal/berekeningen.py pages/jaarafsluiting.py tests/test_fiscal.py
git commit -m "feat: DB-driven arbeidskorting brackets with JSON fallback"
```

---

### Task 5: DB-driven PVV rates

**Files:**
- Modify: `fiscal/berekeningen.py:288-291`
- Modify: `pages/jaarafsluiting.py` (pass PVV params)
- Test: `tests/test_fiscal.py`

**Step 1: Write failing test**

```python
class TestDBDrivenPVV:
    """PVV rates should be configurable from DB params."""

    def test_pvv_from_params_matches_constants(self):
        """DB-driven PVV rates produce same result as constants."""
        params = FISCALE_PARAMS[2024].copy()
        params['pvv_aow_pct'] = 17.90
        params['pvv_anw_pct'] = 0.10
        params['pvv_wlz_pct'] = 9.65
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params, aov=2998,
            woz=655000, hypotheekrente=6951,
            voorlopige_aanslag=30303, voorlopige_aanslag_zvw=2667,
            ew_naar_partner=True,
        )
        # Same as Boekhouder 2024 reference
        assert abs(result.pvv - 10526) < 5

    def test_pvv_custom_rates(self):
        """Custom PVV rates change the calculation."""
        params = FISCALE_PARAMS[2024].copy()
        params['pvv_aow_pct'] = 10.0  # Lower AOW rate
        params['pvv_anw_pct'] = 0.10
        params['pvv_wlz_pct'] = 9.65
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
        )
        # Total PVV rate = 19.75% instead of 27.65%
        # PVV should be lower than with standard rates
        params_default = FISCALE_PARAMS[2024].copy()
        result_default = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params_default,
        )
        assert result.pvv < result_default.pvv
```

**Step 2: Run to verify tests fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestDBDrivenPVV -v`
Expected: First test MAY pass (if params are ignored and constants used), second MUST fail.

**Step 3: Implement DB-driven PVV**

In `fiscal/berekeningen.py`, change lines 288-291:
```python
    # === 6b. IB/PVV split ===
    d_premie_grondslag = D(params.get('pvv_premiegrondslag', 0))
    if d_premie_grondslag == 0:
        d_premie_grondslag = D(params['schijf1_grens'])
    d_pvv_basis = min(d_vi, d_premie_grondslag)

    # Use params-driven PVV rates, fallback to module constants
    d_aow_pct = D(str(params.get('pvv_aow_pct', PVV_AOW_PCT)))
    d_anw_pct = D(str(params.get('pvv_anw_pct', PVV_ANW_PCT)))
    d_wlz_pct = D(str(params.get('pvv_wlz_pct', PVV_WLZ_PCT)))

    d_pvv_aow = d_pvv_basis * d_aow_pct / D('100')
    d_pvv_anw = d_pvv_basis * d_anw_pct / D('100')
    d_pvv_wlz = d_pvv_basis * d_wlz_pct / D('100')
    d_pvv = d_pvv_aow + d_pvv_anw + d_pvv_wlz
```

In `pages/jaarafsluiting.py`, add to `_fiscale_params_to_dict`:
```python
'pvv_aow_pct': params.pvv_aow_pct,
'pvv_anw_pct': params.pvv_anw_pct,
'pvv_wlz_pct': params.pvv_wlz_pct,
```

**Step 4: Run ALL tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add fiscal/berekeningen.py pages/jaarafsluiting.py tests/test_fiscal.py
git commit -m "feat: DB-driven PVV rates with fallback to constants"
```

---

### Task 6: Box 3 calculation function

**Files:**
- Modify: `fiscal/berekeningen.py` (add Box3Resultaat + bereken_box3)
- Test: `tests/test_fiscal.py`

**Step 1: Write failing tests**

```python
from fiscal.berekeningen import Box3Resultaat, bereken_box3

class TestBox3:
    """Box 3 sparen & beleggen berekening."""

    def test_basic_box3_2024(self):
        """Basic Box 3 calculation for 2024."""
        params = {
            'box3_bank_saldo': 80000,
            'box3_overige_bezittingen': 0,
            'box3_schulden': 15000,
            'box3_heffingsvrij_vermogen': 57000,
            'box3_rendement_bank_pct': 1.03,
            'box3_rendement_overig_pct': 6.17,
            'box3_rendement_schuld_pct': 2.46,
            'box3_tarief_pct': 36,
        }
        result = bereken_box3(params, fiscaal_partner=True)
        # Bezittingen: 80000, Schulden: 15000
        # Rendement bank: 80000 * 1.03% = 824
        # Rendement schuld: 15000 * 2.46% = -369
        # Totaal rendement: 824 - 369 = 455
        # Heffingsvrij: 57000 * 2 = 114000 (met partner)
        # Grondslag: max(0, (80000 - 15000) - 114000) = max(0, -49000) = 0
        # No tax: grondslag = 0
        assert result.belasting == 0

    def test_box3_above_heffingsvrij(self):
        """Box 3 with vermogen above heffingsvrij."""
        params = {
            'box3_bank_saldo': 200000,
            'box3_overige_bezittingen': 50000,
            'box3_schulden': 0,
            'box3_heffingsvrij_vermogen': 57000,
            'box3_rendement_bank_pct': 1.03,
            'box3_rendement_overig_pct': 6.17,
            'box3_rendement_schuld_pct': 2.46,
            'box3_tarief_pct': 36,
        }
        result = bereken_box3(params, fiscaal_partner=False)
        # Grondslag: 200000 + 50000 - 57000 = 193000
        # Rendement bank: 200000 * 1.03% = 2060
        # Rendement overig: 50000 * 6.17% = 3085
        # Totaal rendement: 5145
        # Pro-rata over grondslag: rendement * (grondslag / bezittingen)
        # Actually: forfaitair = bank_rendement + overig_rendement - schuld_rendement
        # Then: grondslag = max(0, netto_vermogen - heffingsvrij)
        # voordeel = forfaitair * (grondslag / netto_vermogen)
        # belasting = voordeel * tarief
        assert result.grondslag == 193000
        assert result.belasting > 0

    def test_box3_zero_vermogen(self):
        """No assets = no tax."""
        params = {
            'box3_bank_saldo': 0,
            'box3_overige_bezittingen': 0,
            'box3_schulden': 0,
            'box3_heffingsvrij_vermogen': 57000,
            'box3_rendement_bank_pct': 1.03,
            'box3_rendement_overig_pct': 6.17,
            'box3_rendement_schuld_pct': 2.46,
            'box3_tarief_pct': 36,
        }
        result = bereken_box3(params)
        assert result.belasting == 0
        assert result.grondslag == 0
```

**Step 2: Implement Box 3 calculation**

Add to `fiscal/berekeningen.py`:
```python
@dataclass
class Box3Resultaat:
    """Box 3 sparen & beleggen resultaat."""
    bank_saldo: float = 0.0
    overige_bezittingen: float = 0.0
    schulden: float = 0.0
    netto_vermogen: float = 0.0
    rendement_bank: float = 0.0
    rendement_overig: float = 0.0
    rendement_schuld: float = 0.0
    totaal_rendement: float = 0.0
    heffingsvrij: float = 0.0
    grondslag: float = 0.0
    voordeel: float = 0.0
    belasting: float = 0.0


def bereken_box3(params: dict, fiscaal_partner: bool = True) -> Box3Resultaat:
    """Calculate Box 3 forfaitair rendement (2023+ method).

    Since 2023, rendement is calculated per asset category:
    - Bank: low rate (savings)
    - Overig: high rate (investments)
    - Schuld: deducted at schuld rate

    Grondslag = max(0, netto_vermogen - heffingsvrij)
    Voordeel = totaal_rendement * (grondslag / netto_vermogen) if netto > 0
    Belasting = voordeel * box3_tarief
    """
    r = Box3Resultaat()

    bank = params.get('box3_bank_saldo', 0) or 0
    overig = params.get('box3_overige_bezittingen', 0) or 0
    schuld = params.get('box3_schulden', 0) or 0

    r.bank_saldo = bank
    r.overige_bezittingen = overig
    r.schulden = schuld

    netto = bank + overig - schuld
    r.netto_vermogen = round(netto, 2)

    if netto <= 0:
        return r

    # Forfaitair rendement per category
    bank_pct = (params.get('box3_rendement_bank_pct', 1.03) or 0) / 100
    overig_pct = (params.get('box3_rendement_overig_pct', 6.17) or 0) / 100
    schuld_pct = (params.get('box3_rendement_schuld_pct', 2.46) or 0) / 100

    r.rendement_bank = round(bank * bank_pct, 2)
    r.rendement_overig = round(overig * overig_pct, 2)
    r.rendement_schuld = round(schuld * schuld_pct, 2)
    r.totaal_rendement = round(r.rendement_bank + r.rendement_overig - r.rendement_schuld, 2)

    # Heffingsvrij vermogen
    heffingsvrij_pp = params.get('box3_heffingsvrij_vermogen', 57000) or 57000
    r.heffingsvrij = heffingsvrij_pp * (2 if fiscaal_partner else 1)

    # Grondslag
    grondslag = max(0, netto - r.heffingsvrij)
    r.grondslag = round(grondslag, 2)

    if grondslag <= 0 or r.totaal_rendement <= 0:
        return r

    # Voordeel = pro-rata rendement over grondslag
    r.voordeel = round(r.totaal_rendement * (grondslag / netto), 2)

    # Belasting
    tarief = (params.get('box3_tarief_pct', 36) or 36) / 100
    r.belasting = round(r.voordeel * tarief, 2)

    return r
```

**Step 3: Run tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestBox3 -v`
Expected: All pass.

**Step 4: Commit**

```bash
git add fiscal/berekeningen.py tests/test_fiscal.py
git commit -m "feat: Box 3 forfaitair rendement calculation"
```

---

## Phase 3: Jaarafsluiting Display

### Task 7: Enhanced jaarafsluiting page display

**Files:**
- Modify: `pages/jaarafsluiting.py:314-355` (Section 6 render)

**Context:** The engine already computes tariefsaanpassing, IB/PVV split, separate resultaat_ib/resultaat_zvw. The page just doesn't show them.

**Step 1: Add tariefsaanpassing + IB/PVV split + separate results to _render_resultaat**

In `pages/jaarafsluiting.py`, replace the IB section (lines ~314-355) with:

After "Bruto inkomstenbelasting" line (315-316), add tariefsaanpassing:
```python
                if fiscaal.tariefsaanpassing > 0:
                    _waterfall_line('  waarvan tariefsaanpassing (beperking aftrekbare posten)',
                                    fiscaal.tariefsaanpassing)
```

After bruto_ib, add expandable IB/PVV split:
```python
                with ui.expansion('IB/PVV uitsplitsing', icon='account_balance').classes('w-full'):
                    _waterfall_line('IB (excl. premies volksverzekeringen)',
                                    fiscaal.ib_alleen)
                    _waterfall_line('PVV premies volksverzekeringen',
                                    fiscaal.pvv, bold=True)
                    params_d = berekening_state['params_dict']
                    aow_pct = params_d.get('pvv_aow_pct', 17.90)
                    anw_pct = params_d.get('pvv_anw_pct', 0.10)
                    wlz_pct = params_d.get('pvv_wlz_pct', 9.65)
                    _waterfall_line(f'  AOW ({aow_pct}%)', fiscaal.pvv_aow)
                    _waterfall_line(f'  Anw ({anw_pct}%)', fiscaal.pvv_anw)
                    _waterfall_line(f'  Wlz ({wlz_pct}%)', fiscaal.pvv_wlz)
```

Replace the single resultaat block with separate IB + ZVW results:
```python
                ui.separator().classes('my-2')

                # Separate IB and ZVW results
                _waterfall_line('IB resultaat (netto IB - VA IB)',
                                fiscaal.resultaat_ib, bold=True)
                if fiscaal.voorlopige_aanslag_zvw > 0:
                    _waterfall_line('ZVW resultaat (ZVW - VA ZVW)',
                                    fiscaal.resultaat_zvw, bold=True)

                ui.separator().classes('my-2')

                # Total result with color
                resultaat = fiscaal.resultaat
                ...  # existing color-coded display
```

**Step 2: Verify visually**

Start the app and navigate to `/jaarafsluiting`. Verify:
- Tariefsaanpassing line appears in IB section
- IB/PVV expansion panel opens and shows component breakdown
- Separate IB and ZVW result lines show

**Step 3: Commit**

```bash
git add pages/jaarafsluiting.py
git commit -m "feat: show tariefsaanpassing, IB/PVV split, separate VA results"
```

---

### Task 8: Updated PDF template

**Files:**
- Modify: `templates/jaarafsluiting.html:162-174`

**Step 1: Add tariefsaanpassing + IB/PVV split + separate results to HTML**

After bruto IB line (162), add:
```html
{% if f.tariefsaanpassing > 0 %}
<tr><td class="label" style="padding-left: 8mm">waarvan tariefsaanpassing</td>
    <td class="value">{{ f.tariefsaanpassing|euro }}</td></tr>
{% endif %}
<tr><td class="label" style="padding-left: 4mm">IB (excl. PVV)</td>
    <td class="value">{{ f.ib_alleen|euro }}</td></tr>
<tr><td class="label" style="padding-left: 4mm">PVV premies</td>
    <td class="value">{{ f.pvv|euro }}</td></tr>
<tr><td class="label" style="padding-left: 8mm; font-size: 8pt">AOW {{ f.pvv_aow|euro }} · Anw {{ f.pvv_anw|euro }} · Wlz {{ f.pvv_wlz|euro }}</td>
    <td></td></tr>
```

After the result box, add separate IB/ZVW lines:
```html
<table style="margin-top: 2mm">
<tr><td>IB resultaat (netto IB - VA IB)</td>
    <td class="value">{{ f.resultaat_ib|euro }}</td></tr>
{% if f.voorlopige_aanslag_zvw > 0 %}
<tr><td>ZVW resultaat (ZVW - VA ZVW)</td>
    <td class="value">{{ f.resultaat_zvw|euro }}</td></tr>
{% endif %}
</table>
```

**Step 2: Test PDF export**

Run the app, navigate to jaarafsluiting, click "Exporteer PDF". Verify new lines appear in PDF.

**Step 3: Commit**

```bash
git add templates/jaarafsluiting.html
git commit -m "feat: jaarafsluiting PDF with tariefsaanpassing and IB/PVV split"
```

---

## Phase 4: Instellingen Enhancement

### Task 9: AK bracket editor + PVV editor in Instellingen

**Files:**
- Modify: `pages/instellingen.py:410-457` (within fiscale params tab)

**Context:** Add a bracket editor UI and PVV rate fields to each year's expansion panel. The bracket editor shows 5 rows (one per bracket) with 4 columns. PVV shows 3 number fields.

**Step 1: Add AK bracket editor after existing fields**

In `pages/instellingen.py`, inside each year's expansion panel (after the existing fields grid at ~line 443), add:

```python
                                # --- AK Brackets editor ---
                                ui.separator().classes('q-my-sm')
                                ui.label('Arbeidskorting schijven').classes(
                                    'text-subtitle2 text-weight-medium')

                                import json as _json
                                ak_raw = getattr(params, 'arbeidskorting_brackets', '') or ''
                                try:
                                    ak_data = _json.loads(ak_raw) if ak_raw else []
                                except _json.JSONDecodeError:
                                    ak_data = []

                                # Ensure 5 brackets
                                while len(ak_data) < 5:
                                    ak_data.append({'lower': 0, 'upper': None, 'rate': 0, 'base': 0})

                                ak_inputs = []
                                for i, b in enumerate(ak_data):
                                    with ui.row().classes('w-full gap-2 items-end'):
                                        lower_inp = ui.number(f'Ondergrens', value=b['lower'],
                                                              format='%.0f').classes('w-28').props('dense')
                                        upper_val = b.get('upper')
                                        upper_inp = ui.number(f'Bovengrens', value=upper_val if upper_val else 0,
                                                              format='%.0f').classes('w-28').props('dense')
                                        rate_inp = ui.number(f'Tarief', value=b['rate'],
                                                             format='%.5f', step=0.001).classes('w-28').props('dense')
                                        base_inp = ui.number(f'Basis', value=b['base'],
                                                             format='%.0f').classes('w-28').props('dense')
                                        ak_inputs.append((lower_inp, upper_inp, rate_inp, base_inp))

                                # --- PVV rates ---
                                ui.separator().classes('q-my-sm')
                                ui.label('PVV premies volksverzekeringen').classes(
                                    'text-subtitle2 text-weight-medium')
                                with ui.row().classes('w-full gap-4'):
                                    pvv_aow_inp = ui.number('AOW %',
                                        value=getattr(params, 'pvv_aow_pct', 17.90),
                                        format='%.2f', step=0.01).classes('w-28')
                                    pvv_anw_inp = ui.number('Anw %',
                                        value=getattr(params, 'pvv_anw_pct', 0.10),
                                        format='%.2f', step=0.01).classes('w-28')
                                    pvv_wlz_inp = ui.number('Wlz %',
                                        value=getattr(params, 'pvv_wlz_pct', 9.65),
                                        format='%.2f', step=0.01).classes('w-28')
```

**Step 2: Update save_params to include new fields**

In the `save_params` closure, add:
```python
                                    # Serialize AK brackets to JSON
                                    brackets = []
                                    for lower_inp, upper_inp, rate_inp, base_inp in ak_inputs:
                                        upper_v = upper_inp.value
                                        brackets.append({
                                            'lower': lower_inp.value or 0,
                                            'upper': upper_v if upper_v else None,
                                            'rate': rate_inp.value or 0,
                                            'base': base_inp.value or 0,
                                        })
                                    kwargs['arbeidskorting_brackets'] = _json.dumps(brackets)
                                    kwargs['pvv_aow_pct'] = pvv_aow_inp.value or 17.90
                                    kwargs['pvv_anw_pct'] = pvv_anw_inp.value or 0.10
                                    kwargs['pvv_wlz_pct'] = pvv_wlz_inp.value or 9.65
```

**Step 3: Update upsert_fiscale_params to handle new fields**

Ensure `upsert_fiscale_params` in database.py includes the new columns in its INSERT statement.

**Step 4: Test visually**

Start app, go to Instellingen > Fiscale parameters. Verify:
- AK bracket table appears per year with correct values
- PVV rates appear per year
- Saving persists values

**Step 5: Commit**

```bash
git add pages/instellingen.py database.py
git commit -m "feat: AK bracket editor + PVV rate editor in Instellingen"
```

---

### Task 10: Box 3 parameters in Instellingen

**Files:**
- Modify: `pages/instellingen.py` (add Box 3 section per year)

**Step 1: Add Box 3 parameter fields**

After the PVV section in each year's expansion panel, add:
```python
                                # --- Box 3 parameters ---
                                ui.separator().classes('q-my-sm')
                                ui.label('Box 3 parameters').classes(
                                    'text-subtitle2 text-weight-medium')
                                with ui.grid(columns=2).classes('gap-2 w-full'):
                                    b3_hv = ui.number('Heffingsvrij vermogen/pp',
                                        value=getattr(params, 'box3_heffingsvrij_vermogen', 57000),
                                        format='%.0f').classes('w-full')
                                    b3_bank = ui.number('Rendement bank %',
                                        value=getattr(params, 'box3_rendement_bank_pct', 1.03),
                                        format='%.2f', step=0.01).classes('w-full')
                                    b3_overig = ui.number('Rendement overig %',
                                        value=getattr(params, 'box3_rendement_overig_pct', 6.17),
                                        format='%.2f', step=0.01).classes('w-full')
                                    b3_schuld = ui.number('Rendement schuld %',
                                        value=getattr(params, 'box3_rendement_schuld_pct', 2.46),
                                        format='%.2f', step=0.01).classes('w-full')
                                    b3_tarief = ui.number('Box 3 tarief %',
                                        value=getattr(params, 'box3_tarief_pct', 36),
                                        format='%.1f', step=0.1).classes('w-full')
```

Add to `save_params` kwargs:
```python
                                    kwargs['box3_heffingsvrij_vermogen'] = b3_hv.value or 57000
                                    kwargs['box3_rendement_bank_pct'] = b3_bank.value or 0
                                    kwargs['box3_rendement_overig_pct'] = b3_overig.value or 0
                                    kwargs['box3_rendement_schuld_pct'] = b3_schuld.value or 0
                                    kwargs['box3_tarief_pct'] = b3_tarief.value or 36
```

Also add these to the "Jaar toevoegen" copy logic.

**Step 2: Test visually + commit**

```bash
git add pages/instellingen.py
git commit -m "feat: Box 3 parameters in Instellingen"
```

---

## Phase 5: Aangifte Overhaul

### Task 11: Aangifte page tab structure

**Files:**
- Modify: `pages/aangifte.py` (restructure into tabs)

**Context:** Transform the single-page layout into a tabbed interface with 5 tabs: Overzicht, Box 3, Partner, Documenten, Export.

**Step 1: Restructure page into tabs**

Replace the current page body with:
```python
    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('IB-aangifte').classes('text-h5') \
                .style('color: #0F172A; font-weight: 700')
            jaar_select = ui.select(
                {j: str(j) for j in jaren}, value=huidig_jaar, label='Jaar',
                on_change=lambda e: on_jaar_change(e.value),
            ).classes('w-32')

        with ui.tabs().classes('w-full') as tabs:
            tab_overzicht = ui.tab('Overzicht')
            tab_box3 = ui.tab('Box 3')
            tab_partner = ui.tab('Partner')
            tab_docs = ui.tab('Documenten')
            tab_export = ui.tab('Export')

        with ui.tab_panels(tabs, value=tab_overzicht).classes('w-full'):
            with ui.tab_panel(tab_overzicht):
                overzicht_container = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_box3):
                box3_container = ui.column().classes('w-full gap-4')
            with ui.tab_panel(tab_partner):
                partner_card = ui.card().classes('w-full')
            with ui.tab_panel(tab_docs):
                progress_container = ui.column().classes('w-full')
                checklist_container = ui.column().classes('w-full gap-2')
            with ui.tab_panel(tab_export):
                export_container = ui.column().classes('w-full gap-4')
```

Move existing code into appropriate containers:
- `render_progress` + `render_checklist` → Documenten tab
- `render_partner` → Partner tab
- New `render_overzicht` → Overzicht tab
- New `render_box3` → Box 3 tab
- New `render_export` → Export tab

**Step 2: Test that existing functionality still works**

Navigate to `/aangifte`, verify all 5 tabs exist and Documenten/Partner tabs work as before.

**Step 3: Commit**

```bash
git add pages/aangifte.py
git commit -m "refactor: aangifte page into tabbed interface"
```

---

### Task 12: Aangifte Tax Summary tab (Overzicht)

**Files:**
- Modify: `pages/aangifte.py` (add render_overzicht)

**Context:** Auto-populate a read-only tax summary by running the fiscal engine with saved params. Shows Box 1 breakdown, IB calculation, ZVW, results.

**Step 1: Implement render_overzicht**

```python
    async def render_overzicht():
        overzicht_container.clear()
        jaar = state['jaar']

        params = await get_fiscale_params(DB_PATH, jaar)
        if not params:
            with overzicht_container:
                ui.label(f'Geen fiscale parameters voor {jaar}').classes('text-negative')
            return

        # Fetch same data as jaarafsluiting
        from database import (
            get_omzet_totaal, get_uitgaven_per_categorie,
            get_representatie_totaal, get_investeringen_voor_afschrijving,
            get_investeringen, get_uren_totaal,
        )
        from fiscal.berekeningen import bereken_volledig, bereken_box3

        omzet = await get_omzet_totaal(DB_PATH, jaar)
        kosten_per_cat = await get_uitgaven_per_categorie(DB_PATH, jaar)
        representatie = await get_representatie_totaal(DB_PATH, jaar)
        investeringen = await get_investeringen_voor_afschrijving(DB_PATH, tot_jaar=jaar)
        inv_dit_jaar = await get_investeringen(DB_PATH, jaar=jaar)
        uren = await get_uren_totaal(DB_PATH, jaar, urennorm_only=True)

        # Calculate costs and depreciation (same logic as jaarafsluiting)
        from fiscal.afschrijvingen import bereken_afschrijving
        totaal_kosten = sum(r['totaal'] for r in kosten_per_cat)
        inv_bedrag = sum((u.aanschaf_bedrag or u.bedrag) for u in inv_dit_jaar)
        kosten_excl_inv = totaal_kosten - inv_bedrag

        totaal_afschr = 0.0
        for u in investeringen:
            ab = (u.aanschaf_bedrag or u.bedrag) * ((u.zakelijk_pct or 100) / 100)
            result = bereken_afschrijving(ab, u.restwaarde_pct, u.levensduur_jaren or 5,
                                          int(u.datum[5:7]), int(u.datum[0:4]), jaar)
            totaal_afschr += result['afschrijving']

        inv_totaal = sum((u.aanschaf_bedrag or u.bedrag) * ((u.zakelijk_pct or 100) / 100)
                         for u in inv_dit_jaar)

        params_dict = _fiscale_params_to_dict(params)  # import this helper
        ew_naar_partner = getattr(params, 'ew_naar_partner', True)

        fiscaal = bereken_volledig(
            omzet=omzet, kosten=kosten_excl_inv, afschrijvingen=totaal_afschr,
            representatie=representatie, investeringen_totaal=inv_totaal,
            uren=uren, params=params_dict,
            aov=params.aov_premie or 0, woz=params.woz_waarde or 0,
            hypotheekrente=params.hypotheekrente or 0,
            voorlopige_aanslag=params.voorlopige_aanslag_betaald or 0,
            voorlopige_aanslag_zvw=params.voorlopige_aanslag_zvw or 0,
            ew_naar_partner=ew_naar_partner,
        )

        box3 = bereken_box3(params_dict, fiscaal_partner=True)

        with overzicht_container:
            # Render summary cards
            _render_box1_summary(fiscaal)
            _render_ib_summary(fiscaal)
            _render_zvw_summary(fiscaal)
            _render_box3_summary(box3)
            _render_totaal(fiscaal, box3)
```

Then implement each `_render_*_summary` helper as a `ui.card()` with `_waterfall_line` style.

**Step 2: Test visually**

Navigate to `/aangifte` > Overzicht tab. Verify all values appear.

**Step 3: Commit**

```bash
git add pages/aangifte.py
git commit -m "feat: aangifte tax summary tab (Overzicht)"
```

---

### Task 13: Aangifte Box 3 tab

**Files:**
- Modify: `pages/aangifte.py` (add render_box3)
- Modify: `database.py` (add update_box3_inputs function)

**Step 1: Add update_box3_inputs to database.py**

```python
async def update_box3_inputs(db_path: Path = DB_PATH, jaar: int = 0,
                              bank_saldo: float = 0, overige_bezittingen: float = 0,
                              schulden: float = 0) -> None:
    """Update Box 3 input values for a specific year."""
    conn = await get_db(db_path)
    try:
        await conn.execute(
            """UPDATE fiscale_params
               SET box3_bank_saldo = ?, box3_overige_bezittingen = ?,
                   box3_schulden = ?
               WHERE jaar = ?""",
            (bank_saldo, overige_bezittingen, schulden, jaar))
        await conn.commit()
    finally:
        await conn.close()
```

**Step 2: Implement render_box3**

```python
    async def render_box3():
        box3_container.clear()
        jaar = state['jaar']
        params = await get_fiscale_params(DB_PATH, jaar)
        if not params:
            with box3_container:
                ui.label(f'Geen fiscale parameters voor {jaar}').classes('text-negative')
            return

        from fiscal.berekeningen import bereken_box3

        with box3_container:
            with ui.card().classes('w-full'):
                ui.label('Vermogen peildatum 1 januari').classes('text-subtitle1 text-weight-medium')
                ui.label(f'Vul uw vermogensbestanddelen in per 1 januari {jaar}').classes(
                    'text-caption text-grey-7')
                with ui.row().classes('w-full gap-4 q-mt-sm'):
                    bank_inp = ui.number('Banktegoeden €',
                        value=params.box3_bank_saldo, format='%.0f',
                        prefix='€').classes('flex-grow')
                    overig_inp = ui.number('Overige bezittingen €',
                        value=params.box3_overige_bezittingen, format='%.0f',
                        prefix='€').classes('flex-grow')
                    schuld_inp = ui.number('Schulden €',
                        value=params.box3_schulden, format='%.0f',
                        prefix='€').classes('flex-grow')
                partner_cb = ui.checkbox('Fiscaal partner', value=True).classes('q-mt-sm')

                async def herbereken_box3():
                    from pages.jaarafsluiting import _fiscale_params_to_dict
                    params_dict = _fiscale_params_to_dict(params)
                    params_dict['box3_bank_saldo'] = bank_inp.value or 0
                    params_dict['box3_overige_bezittingen'] = overig_inp.value or 0
                    params_dict['box3_schulden'] = schuld_inp.value or 0
                    box3 = bereken_box3(params_dict, fiscaal_partner=partner_cb.value)

                    await update_box3_inputs(DB_PATH, jaar,
                        bank_saldo=bank_inp.value or 0,
                        overige_bezittingen=overig_inp.value or 0,
                        schulden=schuld_inp.value or 0)

                    result_card.clear()
                    with result_card:
                        _render_box3_result(box3)
                    ui.notify('Box 3 berekend en opgeslagen', type='positive')

                ui.button('Bereken', icon='calculate',
                          on_click=herbereken_box3).props('color=primary').classes('q-mt-sm')

            result_card = ui.card().classes('w-full')
            # Initial calculation
            params_dict = _fiscale_params_to_dict(params)  # need to import
            box3 = bereken_box3(params_dict, fiscaal_partner=True)
            with result_card:
                _render_box3_result(box3)
```

**Step 3: Commit**

```bash
git add pages/aangifte.py database.py
git commit -m "feat: aangifte Box 3 tab with calculation"
```

---

### Task 14: Aangifte Export tab + PDF template

**Files:**
- Create: `templates/aangifte_overzicht.html`
- Modify: `pages/aangifte.py` (add export functionality)

**Step 1: Create aangifte PDF template**

Create `templates/aangifte_overzicht.html` based on the jaarafsluiting template style, but including:
- Box 1 summary (winst, aftrekken, belastbare winst)
- IB berekening (verzamelinkomen, bruto IB, PVV, kortingen, netto IB)
- ZVW
- Box 3 (if vermogen > 0)
- Partner (if partner data exists)
- Document checklist status
- Totaal resultaat

**Step 2: Add export button**

In the Export tab:
```python
    async def render_export():
        export_container.clear()
        with export_container:
            with ui.card().classes('w-full'):
                ui.label('Aangifte-overzicht exporteren').classes('text-subtitle1 text-weight-medium')
                ui.label('Genereer een PDF met alle gegevens voor de IB-aangifte.').classes(
                    'text-caption text-grey-7')
                ui.button('Exporteer PDF', icon='picture_as_pdf',
                          on_click=export_aangifte_pdf).props('color=primary').classes('q-mt-md')
```

**Step 3: Implement export_aangifte_pdf**

Similar to jaarafsluiting export: run calculations, render Jinja2 template, generate WeasyPrint PDF, trigger download.

**Step 4: Test export**

Navigate to `/aangifte` > Export tab. Click export. Verify PDF is generated with all sections.

**Step 5: Commit**

```bash
git add templates/aangifte_overzicht.html pages/aangifte.py
git commit -m "feat: aangifte PDF export with full tax overview"
```

---

## Phase 6: Docs Cleanup

### Task 15: Delete stale plan files

**Files:**
- Delete: `docs/plans/2026-02-23-roberg-boekhouding-app-design.md`
- Delete: `docs/plans/2026-02-23-roberg-boekhouding-implementation.md`
- Delete: `docs/plans/2026-03-04-aangifte-documenten-design.md`
- Delete: `docs/plans/2026-03-04-aangifte-documenten-plan.md`
- Delete: `docs/plans/2026-03-04-aangifte-verbeteringen-plan.md`
- Delete: `docs/plans/2026-03-04-import-bestaande-facturen.md`
- Delete: `docs/plans/2026-03-04-multi-locatie-design.md`
- Delete: `docs/plans/2026-03-04-multi-locatie-plan.md`
- Delete: `docs/plans/2026-03-06-jaarafsluiting-overhaul.md` (superseded)
- Delete: `docs/audit-2026-03-03.md`

**Step 1: Delete files**

```bash
rm docs/plans/2026-02-23-roberg-boekhouding-app-design.md
rm docs/plans/2026-02-23-roberg-boekhouding-implementation.md
rm docs/plans/2026-03-04-aangifte-documenten-design.md
rm docs/plans/2026-03-04-aangifte-documenten-plan.md
rm docs/plans/2026-03-04-aangifte-verbeteringen-plan.md
rm docs/plans/2026-03-04-import-bestaande-facturen.md
rm docs/plans/2026-03-04-multi-locatie-design.md
rm docs/plans/2026-03-04-multi-locatie-plan.md
rm docs/plans/2026-03-06-jaarafsluiting-overhaul.md
rm docs/audit-2026-03-03.md
```

**Step 2: Commit**

```bash
git add -A docs/
git commit -m "chore: delete stale plan files from completed phases"
```

---

### Task 16: Rewrite CLAUDE.md and MEMORY.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: auto-memory `MEMORY.md`

**Step 1: Rewrite CLAUDE.md**

Update with:
- Correct test count (run `pytest --co -q` to count)
- Updated fiscal domain knowledge (startersaftrek 2026 = 2123, villataks per year, AK in DB)
- Updated architecture (DB-driven params, Box 3, aangifte tabs)
- Updated known bugs (remove fixed ones, add any new)
- Updated configurable parameters list

**Step 2: Rewrite MEMORY.md**

Update with:
- Current branch status
- Completed overhaul summary
- Updated test count
- Key architecture decisions (AK in DB as JSON, PVV in DB, Box 3)

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: rewrite CLAUDE.md with updated architecture and fiscal knowledge"
```

---

## Run Order Summary

| Phase | Tasks | Estimated Commits |
|-------|-------|-------------------|
| 1. Data Foundation | 1-3 | 3 |
| 2. Engine Flexibility | 4-6 | 3 |
| 3. Jaarafsluiting Display | 7-8 | 2 |
| 4. Instellingen Enhancement | 9-10 | 2 |
| 5. Aangifte Overhaul | 11-14 | 4 |
| 6. Docs Cleanup | 15-16 | 2 |
| **Total** | **16 tasks** | **16 commits** |

Each phase can be verified independently:
- Phase 1-2: `pytest tests/test_fiscal.py -v` (all pass)
- Phase 3-4: Visual verification in browser
- Phase 5: Visual verification + PDF export test
- Phase 6: `pytest tests/ -v` (full suite passes)
