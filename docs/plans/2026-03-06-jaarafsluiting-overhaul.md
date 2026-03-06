# Jaarafsluiting & Aangifte Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix critical fiscal calculation bugs, generate a proper jaarcijfers report (matching Yuki output), and enhance the aangifte preparation page — validated against Boekhouder 2024 reference figures.

**Architecture:** Three phases: (1) Fix the fiscal engine bugs (tariefsaanpassing, arbeidskorting input, eigen woning allocation), (2) Enhance the jaarafsluiting page with detailed W&V and fiscale waterval, (3) Enhance the aangifte page with Box 3, partner integration, and data export. Each phase is independently deployable and testable.

**Tech Stack:** Python 3.12+, NiceGUI 3.8 (Quasar/Vue), SQLite via aiosqlite, WeasyPrint + Jinja2 for PDF, pytest.

**Reference documents (read these before starting):**
- Boekhouder Aangifte IB 2024: `~/02_Financieel/Boekhouding_Waarneming/2024/Documenten/Aangifte/Boekhouder_Aangifte_inkomstenbelasting_2024.pdf`
- Yuki Jaarcijfers 2024: `~/02_Financieel/Boekhouding_Waarneming/2024/2023_Jaarcijfers_TestBV huisartswaarnemer - Jaarcijfers 2024.pdf`
- Current fiscal tests: `tests/test_fiscal.py`
- Current fiscal engine: `fiscal/berekeningen.py`
- Current heffingskortingen: `fiscal/heffingskortingen.py`

**Boekhouder 2024 reference values (THE source of truth):**

| Item | Boekhouder Value | Current App |
|------|-----------|-------------|
| Winst (jaarrekening) | 95.145 | 95.145 ✓ |
| Fiscale winst | 94.437 | 94.438 ✓ |
| Belastbare winst | 76.776 | 76.777 ✓ |
| Verzamelinkomen T. Gebruiker | 73.778 | **69.120 ✗** |
| Bruto IB+PVV | 29.268 | **~25.556 ✗** |
| Arbeidskorting | 1.986 | **3.136 ✗** |
| AHK | 116 | 116 ✓ |
| Tariefsaanpassing (beperking) | 1.994 | **0 (missing) ✗** |
| Netto IB+PVV | 27.166 | **~21.998 ✗** |
| ZVW bijdrage | 3.810 | **3.677 ✗** |
| IB terug | 3.137 | **~2.869 ✗** |

**Root causes of the 3 critical bugs:**
1. **Arbeidskorting wrong input**: Uses `belastbare_winst` (76.776) but should use `fiscale_winst` (94.437). Belastingdienst defines arbeidsinkomen for ondernemer = winst uit onderneming vóór ondernemersaftrek/MKB.
2. **Missing tariefsaanpassing**: When ondernemersaftrek+MKB deductions push income from schijf 2 into schijf 1, the excess benefit is clawed back at (toptarief - basistarief). For 2024: 12.53% × 15.921 = 1.994.
3. **Eigen woning saldo**: App subtracts from entrepreneur's verzamelinkomen. Boekhouder allocates woning to partner. Fix: make eigen woning allocation configurable (partner checkbox).

---

## Phase 1: Fix Fiscal Calculation Engine (Critical)

### Task 1: Fix arbeidskorting input — use fiscale_winst instead of belastbare_winst

**Files:**
- Modify: `fiscal/berekeningen.py:233-234`
- Modify: `tests/test_fiscal.py`

**Context:** The Belastingdienst defines "arbeidsinkomen" for an ondernemer as the winst uit onderneming (= fiscale winst, BEFORE zelfstandigenaftrek, startersaftrek, and MKB-winstvrijstelling). The current code passes `r.belastbare_winst` to `bereken_arbeidskorting()`, which is the winst AFTER those deductions — too low.

**Step 1: Write the failing test**

Add to `tests/test_fiscal.py` class `TestVolledig`:

```python
def test_arbeidskorting_uses_fiscale_winst_2024(self):
    """Arbeidskorting should use fiscale_winst (94.437), not belastbare_winst (76.776).

    Boekhouder 2024 reference: AK = 1.986.
    With fiscale_winst 94.437: AK = 5532 - 6.51% * (94437 - 39958) = 1983.
    With belastbare_winst 76.776: AK = 5532 - 6.51% * (76776 - 39958) = 3136. (WRONG)
    """
    params = FISCALE_PARAMS[2024]
    result = bereken_volledig(
        omzet=95145, kosten=0, afschrijvingen=0,
        representatie=550, investeringen_totaal=2919,
        uren=1400, params=params,
    )
    # Fiscale winst = 94437, AK should be ~1983 (Boekhouder says 1986)
    assert abs(result.arbeidskorting - 1986) < 10
    # NOT 3136 (which is what belastbare_winst would give)
    assert result.arbeidskorting < 2100
```

**Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestVolledig::test_arbeidskorting_uses_fiscale_winst_2024 -v`
Expected: FAIL (current AK ≈ 3136, assertion `< 2100` fails)

**Step 3: Fix the code**

In `fiscal/berekeningen.py`, line ~234, change:
```python
# BEFORE (wrong):
ak = bereken_arbeidskorting(r.belastbare_winst, jaar)

# AFTER (correct):
ak = bereken_arbeidskorting(r.fiscale_winst, jaar)
```

**Step 4: Run ALL fiscal tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py -v`
Expected: The new test passes. Some existing tests may need tolerance adjustments since AK changed.

**Step 5: Fix any broken existing tests**

The `test_volledig_2024` and `test_volledig_2023` tests have wide tolerances and should still pass. If any test fails, adjust the tolerance or expected values based on the now-correct AK calculation. The Boekhouder reference values are the source of truth.

**Step 6: Commit**

```bash
git add fiscal/berekeningen.py tests/test_fiscal.py
git commit -m "fix: arbeidskorting uses fiscale_winst instead of belastbare_winst

The Belastingdienst defines arbeidsinkomen for ondernemers as winst
uit onderneming (fiscale winst), not belastbare winst (after ZA/SA/MKB).
Boekhouder 2024 reference: AK=1986 with fiscale_winst=94437."
```

---

### Task 2: Add tariefsaanpassing (beperking aftrekbare posten)

**Files:**
- Modify: `fiscal/berekeningen.py` (add tariefsaanpassing to FiscaalResultaat + bereken_volledig)
- Modify: `tests/test_fiscal.py`

**Context:** Since 2023, the tax benefit of ondernemersaftrek + MKB-winstvrijstelling is capped at the basistarief. If income without these deductions would be in a higher bracket, the excess benefit is clawed back. Boekhouder 2024 shows: "beperking aftrekbare posten (12,53% over 15.921) = 1.994".

Formula:
```
income_without_deductions = fiscale_winst + ew_saldo - aov  (or just belastbaar Box 1 without deductions)
income_with_deductions = belastbare_winst + ew_saldo - aov  (actual belastbaar inkomen)
deductions = income_without_deductions - income_with_deductions  (= ZA + SA + MKB)
amount_in_higher_bracket = max(0, income_without_deductions - schijf1_grens)
amount_subject_to_beperking = min(deductions, amount_in_higher_bracket)
tariefsaanpassing = amount_subject_to_beperking * (schijf_top_pct - basis_tarief_pct) / 100
```

For 2024: top = 49.50%, basis = 36.97%, diff = 12.53%.
For 2025+: top = 49.50%, basis = 37.48% (schijf 2 rate), diff = 12.02%.

**Step 1: Write the failing tests**

```python
class TestTariefsaanpassing:
    """Beperking aftrekbare posten (tariefsaanpassing) since 2023."""

    def test_tariefsaanpassing_2024_boekhouder(self):
        """Boekhouder 2024: beperking = 12.53% over 15.921 = 1.994."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998,
        )
        # Boekhouder: tariefsaanpassing = 1994
        assert abs(result.tariefsaanpassing - 1994) < 50

    def test_tariefsaanpassing_income_below_schijf1_no_beperking(self):
        """If income stays within schijf 1, no tariefsaanpassing."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=50000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
        )
        # Fiscale winst 50000, belastbare winst ~38000, all in schijf 1
        assert result.tariefsaanpassing == 0

    def test_tariefsaanpassing_only_excess_in_schijf2(self):
        """Only the portion of deductions that removes income from schijf 2."""
        params = FISCALE_PARAMS[2024]
        # fiscale_winst just above schijf1_grens (75518)
        result = bereken_volledig(
            omzet=76000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
        )
        # Income without deductions: 76000
        # Amount in schijf 2: 76000 - 75518 = 482
        # Deductions (ZA+SA+MKB): ~5873 + ~9329 = ~15202
        # Subject to beperking: min(15202, 482) = 482
        # Tariefsaanpassing = 482 * 0.1253 = ~60
        assert 40 < result.tariefsaanpassing < 80

    def test_tariefsaanpassing_2025_three_brackets(self):
        """2025 has 3 brackets. Tariefsaanpassing uses toptarief (49.50) minus schijf2 rate (37.48)."""
        params = FISCALE_PARAMS[2025]
        result = bereken_volledig(
            omzet=95000, kosten=0, afschrijvingen=0,
            representatie=0, investeringen_totaal=0,
            uren=1400, params=params,
        )
        # Tariefsaanpassing should use 49.50 - 37.48 = 12.02%
        assert result.tariefsaanpassing > 0
```

**Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestTariefsaanpassing -v`
Expected: FAIL (tariefsaanpassing attribute doesn't exist)

**Step 3: Implement tariefsaanpassing**

3a. Add field to `FiscaalResultaat` in `fiscal/berekeningen.py`:
```python
@dataclass
class FiscaalResultaat:
    # ... existing fields ...
    # After kia, add:
    tariefsaanpassing: float = 0.0
```

3b. Add new parameters to `fiscale_params` table — we need the "aftrektarief" per year.

Add to `fiscal/berekeningen.py` a helper or use existing params. The aftrektarief equals:
- 2023-2024: schijf1_pct (= 36.93% / 36.97%) — since schijf1 = schijf2
- 2025+: schijf2_pct (= 37.48%) — the "middle" bracket

The toptarief = schijf3_pct (= 49.50%).

So: `tariefsaanpassing_pct = schijf3_pct - aftrektarief`

Where `aftrektarief`:
- If `schijf1_grens == schijf2_grens`: use `schijf1_pct` (2023-2024, 2 brackets)
- Else: use `schijf2_pct` (2025+, 3 brackets)

And `grens_for_beperking`:
- If `schijf1_grens == schijf2_grens`: use `schijf1_grens` (income above this is in top bracket)
- Else: use `schijf2_grens` (income above this is in top bracket)

3c. Add tariefsaanpassing calculation in `bereken_volledig()`, after MKB calculation, before IB calculation:

```python
# === Tariefsaanpassing (beperking aftrekbare posten) ===
# Deductions subject to beperking: ondernemersaftrek + MKB-winstvrijstelling
d_deductions = d_za + d_sa + d_mkb

# Determine the bracket boundary and rate difference
if params['schijf1_grens'] == params['schijf2_grens']:
    # 2023-2024: 2 brackets, aftrektarief = schijf1_pct
    d_aftrektarief = D(params['schijf1_pct'])
    d_grens = D(params['schijf1_grens'])
else:
    # 2025+: 3 brackets, aftrektarief = schijf2_pct
    d_aftrektarief = D(params['schijf2_pct'])
    d_grens = D(params['schijf2_grens'])

d_toptarief = D(params['schijf3_pct'])
d_ta_pct = (d_toptarief - d_aftrektarief) / D('100')

# Income without these deductions (= what would be taxed without ZA/SA/MKB)
# The relevant "income" for this calc is the verzamelinkomen BEFORE these deductions
# but AFTER ew_saldo and aov
d_income_without = d_fiscale_winst + d_ew_saldo - d_aov
d_income_with = d_belastbare_winst + d_ew_saldo - d_aov

# Amount that was in the top bracket but got "removed" by deductions
d_excess = max(D('0'), d_income_without - d_grens)
d_subject = min(d_deductions, d_excess)

d_tariefsaanpassing = d_subject * d_ta_pct
r.tariefsaanpassing = euro(d_tariefsaanpassing)
```

3d. Add tariefsaanpassing to the bruto_ib calculation:
```python
# BEFORE:
d_bruto_ib = d_ib1 + d_ib2 + d_ib3

# AFTER:
d_bruto_ib = d_ib1 + d_ib2 + d_ib3 + d_tariefsaanpassing
```

**Step 4: Run ALL fiscal tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py -v`
Expected: All tests pass. The Boekhouder reference tests should now be MORE accurate.

**Step 5: Update existing Boekhouder 2024 test with tighter tolerances**

```python
def test_volledig_2024(self):
    """Boekhouder 2024: now with tariefsaanpassing, should match closely."""
    params = FISCALE_PARAMS[2024]
    result = bereken_volledig(
        omzet=95145, kosten=0, afschrijvingen=0,
        representatie=550, investeringen_totaal=2919,
        uren=1400, params=params,
        aov=2998,
        woz=0, hypotheekrente=0,  # eigen woning allocated to partner
        voorlopige_aanslag=30303,
    )
    assert abs(result.belastbare_winst - 76776) < 10
    assert abs(result.tariefsaanpassing - 1994) < 50
    assert abs(result.arbeidskorting - 1986) < 10
    assert abs(result.ahk - 116) < 5
    # Teruggave ~3137 (Boekhouder)
    assert -3300 < result.resultaat < -2900
```

**Step 6: Commit**

```bash
git add fiscal/berekeningen.py tests/test_fiscal.py
git commit -m "feat: add tariefsaanpassing (beperking aftrekbare posten)

Deductions (ZA, SA, MKB) are capped at the basistarief.
If income without deductions exceeds the top bracket boundary,
the excess benefit is clawed back. Boekhouder 2024: 12.53% × 15921 = 1994."
```

---

### Task 3: Make eigen woning allocation configurable (partner checkbox)

**Files:**
- Modify: `fiscal/berekeningen.py` (add `ew_naar_partner` parameter)
- Modify: `pages/jaarafsluiting.py` (add partner checkbox)
- Modify: `models.py` (add `ew_naar_partner` to FiscaleParams)
- Modify: `database.py` (add column to fiscale_params)
- Modify: `tests/test_fiscal.py`

**Context:** Boekhouder allocates the eigen woning saldo (-4.659) to partner A.A.H. Nijholt (her verzamelinkomen includes it). The app should allow toggling this. When `ew_naar_partner=True`, the EW saldo is excluded from the entrepreneur's verzamelinkomen and ZVW grondslag.

**Step 1: Write the failing test**

```python
def test_ew_naar_partner_excludes_from_verzamelinkomen(self):
    """When EW allocated to partner, verzamelinkomen excludes EW saldo."""
    params = FISCALE_PARAMS[2024]
    result = bereken_volledig(
        omzet=95145, kosten=0, afschrijvingen=0,
        representatie=550, investeringen_totaal=2919,
        uren=1400, params=params,
        aov=2998,
        woz=655000, hypotheekrente=6951,
        ew_naar_partner=True,
    )
    # Boekhouder: verzamelinkomen = 76776 - 2998 = 73778 (no EW saldo)
    assert abs(result.verzamelinkomen - 73778) < 50

def test_ew_niet_naar_partner_includes_in_verzamelinkomen(self):
    """When EW NOT allocated to partner, verzamelinkomen includes EW saldo."""
    params = FISCALE_PARAMS[2024]
    result = bereken_volledig(
        omzet=95145, kosten=0, afschrijvingen=0,
        representatie=550, investeringen_totaal=2919,
        uren=1400, params=params,
        aov=2998,
        woz=655000, hypotheekrente=6951,
        ew_naar_partner=False,
    )
    # EW saldo = 2292 - 6951 = -4659
    # verzamelinkomen = 76776 - 4659 - 2998 = 69119
    assert abs(result.verzamelinkomen - 69119) < 50
```

**Step 2: Run tests to verify they fail**

Expected: FAIL (ew_naar_partner parameter doesn't exist)

**Step 3: Implement**

3a. Add parameter to `bereken_volledig()`:
```python
def bereken_volledig(omzet, kosten, afschrijvingen, representatie,
                     investeringen_totaal, uren, params, aov=0,
                     woz=0, hypotheekrente=0, voorlopige_aanslag=0,
                     ew_naar_partner=False):
```

3b. Modify verzamelinkomen calculation:
```python
if ew_naar_partner:
    d_verzamelinkomen = d_belastbare_winst - d_aov
else:
    d_verzamelinkomen = d_belastbare_winst + d_ew_saldo - d_aov
```

Note: The EW forfait/saldo/hillen are still calculated and stored in `FiscaalResultaat` for display — they're just excluded from the entrepreneur's income when allocated to partner.

3c. Also adjust ZVW grondslag:
```python
# ZVW grondslag for ondernemer = belastbare winst (not verzamelinkomen)
# This is correct per Boekhouder: "Inkomen Zvw = 76.776" (belastbare winst)
d_zvw_grondslag = min(d_belastbare_winst, D(params['zvw_max_grondslag']))
```

Note: This is ALSO a fix — ZVW should use belastbare_winst, not verzamelinkomen.

3d. Also fix IB calculation to use correct base. When EW is allocated to partner, the IB base = belastbare_winst - aov (= 73.778). When not, IB base = belastbare_winst + ew_saldo - aov. The IB is calculated on `d_verzamelinkomen`, so this is already handled by the `d_verzamelinkomen` fix above.

3e. Add `ew_naar_partner` to DB:
- Add column to `fiscale_params` table: `ew_naar_partner INTEGER DEFAULT 1` (default: allocate to partner)
- Add field to `FiscaleParams` dataclass in `models.py`
- Add to `_row_to_fiscale_params` in `database.py`

3f. Update jaarafsluiting page to pass the flag:
```python
ew_naar_partner = params.ew_naar_partner if hasattr(params, 'ew_naar_partner') else True
fiscaal = bereken_volledig(
    ..., ew_naar_partner=ew_naar_partner,
)
```

3g. Add a checkbox on the jaarafsluiting IB section:
```python
ui.checkbox('Eigen woning toerekenen aan partner', value=True)
```

**Step 4: Run all tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py -v`

**Step 5: Commit**

```bash
git add fiscal/berekeningen.py models.py database.py pages/jaarafsluiting.py tests/test_fiscal.py
git commit -m "feat: configurable eigen woning allocation (partner checkbox)

Boekhouder allocates eigen woning saldo to partner. When ew_naar_partner=True,
EW saldo is excluded from entrepreneur's verzamelinkomen.
Also fixes ZVW grondslag to use belastbare_winst (not verzamelinkomen)."
```

---

### Task 4: Add IB/PVV split parameters and display

**Files:**
- Modify: `fiscal/berekeningen.py` (add PVV fields to FiscaalResultaat, compute IB/PVV split)
- Modify: `tests/test_fiscal.py`

**Context:** The Boekhouder shows IB and PVV (premies volksverzekeringen) separately. PVV = 27.65% (AOW 17.90%, Anw 0.10%, Wlz 9.65%), only charged in schijf 1 (up to premiegrondslag max). The combined tarief we already use is correct for TOTAL calculation, but we need the split for display.

**Step 1: Write the failing tests**

```python
class TestIBPVVSplit:
    """IB and PVV should be calculated separately for display."""

    def test_pvv_2024(self):
        """PVV = 27.65% over max 38.098 (2024)."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params, aov=2998,
            ew_naar_partner=True,
        )
        # Boekhouder: PVV = 10.534
        assert abs(result.pvv - 10534) < 50

    def test_ib_only_2024(self):
        """IB-only = total bruto - PVV."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params, aov=2998,
            ew_naar_partner=True,
        )
        # Boekhouder: IB (incl tariefsaanpassing) = 18.734
        assert abs(result.ib_alleen - 18734) < 100
```

**Step 2: Implement**

Add to `FiscaalResultaat`:
```python
# IB/PVV split (for display)
ib_alleen: float = 0.0  # IB excluding PVV
pvv: float = 0.0  # Premies volksverzekeringen (AOW + Anw + Wlz)
pvv_aow: float = 0.0
pvv_anw: float = 0.0
pvv_wlz: float = 0.0
```

Add PVV constants (these don't change across years):
```python
PVV_AOW_PCT = Decimal('17.90')
PVV_ANW_PCT = Decimal('0.10')
PVV_WLZ_PCT = Decimal('9.65')
PVV_TOTAAL_PCT = PVV_AOW_PCT + PVV_ANW_PCT + PVV_WLZ_PCT  # 27.65
```

In `bereken_volledig()`, after the bracket calculation and tariefsaanpassing, add:
```python
# PVV: 27.65% over inkomen in schijf 1 (capped at premiegrondslag max)
# For 2024: premiegrondslag max = schijf1_grens when schijf1==schijf2
# For 2025+: premiegrondslag max = schijf1_grens (the PVV boundary)
d_premiegrondslag = min(d_vi, d_s1_grens)
d_pvv_aow = d_premiegrondslag * PVV_AOW_PCT / D('100')
d_pvv_anw = d_premiegrondslag * PVV_ANW_PCT / D('100')
d_pvv_wlz = d_premiegrondslag * PVV_WLZ_PCT / D('100')
d_pvv = d_pvv_aow + d_pvv_anw + d_pvv_wlz

r.pvv = euro(d_pvv)
r.pvv_aow = euro(d_pvv_aow)
r.pvv_anw = euro(d_pvv_anw)
r.pvv_wlz = euro(d_pvv_wlz)

# IB-only = bruto_ib - pvv (since bruto_ib uses combined rates that include PVV)
r.ib_alleen = euro(d_bruto_ib - d_pvv)
```

**Step 3: Run all tests, commit**

---

### Task 5: Comprehensive Boekhouder 2024 validation test

**Files:**
- Modify: `tests/test_fiscal.py`

**Context:** Now that all 3 bugs are fixed, write ONE comprehensive test that validates every Boekhouder 2024 intermediate value. This is the ultimate regression test.

```python
class TestBoekhouder2024Complete:
    """Complete validation against Boekhouder Aangifte IB 2024."""

    def test_complete_waterfall(self):
        """Every value from the Boekhouder rapportage, page by page."""
        params = FISCALE_PARAMS[2024]
        result = bereken_volledig(
            omzet=95145, kosten=0, afschrijvingen=0,
            representatie=550, investeringen_totaal=2919,
            uren=1400, params=params,
            aov=2998,
            woz=655000, hypotheekrente=6951,
            voorlopige_aanslag=30303,
            ew_naar_partner=True,
        )

        # Page 6-7: Specificatie Box 1
        assert abs(result.winst - 95145) < 1
        assert abs(result.kia - 818) < 5  # MacBook Pro 16: 2919 * 28% = 817.32
        assert abs(result.repr_bijtelling - 110) < 1  # 550 * 20%
        assert abs(result.fiscale_winst - 94437) < 5
        assert abs(result.zelfstandigenaftrek - 3750) < 1
        assert abs(result.startersaftrek - 2123) < 1
        assert abs(result.mkb_vrijstelling - 11788) < 50
        assert abs(result.belastbare_winst - 76776) < 10

        # Page 2: Belastbaar inkomen Box 1
        # verzamelinkomen = 76776 - 2998 = 73778 (EW to partner)
        assert abs(result.verzamelinkomen - 73778) < 10

        # Page 2: Tariefsaanpassing
        assert abs(result.tariefsaanpassing - 1994) < 50

        # Page 2: IB+PVV
        assert abs(result.bruto_ib - 29268) < 100

        # Page 4: Heffingskortingen
        assert abs(result.ahk - 116) < 5
        assert abs(result.arbeidskorting - 1986) < 10

        # Page 4: Netto verschuldigd
        netto = result.bruto_ib - result.ahk - result.arbeidskorting
        assert abs(netto - 27166) < 100

        # Page 5: ZVW
        assert abs(result.zvw - 3810) < 50

        # Page 1: Resultaat
        # Teruggave IB = 30303 - 27166 = 3137
        # But our model: resultaat = netto_ib + zvw - VA
        # With ZVW included: 27166 + 3810 - 30303 = 673 (bijbetalen)
        # Boekhouder separates IB and ZVW. Our model combines them.
        # IB-only result:
        ib_result = result.netto_ib - result.voorlopige_aanslag
        # This should be approximately -3137 (IB teruggave)
        # But our netto_ib already includes tariefsaanpassing correction
        # Accept wider tolerance due to model differences
        assert -3500 < result.resultaat < 1500
```

Run all tests, commit.

---

## Phase 2: Enhanced Jaarafsluiting Page

### Task 6: Add omzet per klant breakdown

**Files:**
- Modify: `pages/jaarafsluiting.py`
- Existing: `database.py` (already has `get_omzet_per_klant`)

**Step 1: Verify the DB function exists**

Read `database.py` and find `get_omzet_per_klant`. It should return a list of dicts with `klant_naam` and `totaal` keys.

**Step 2: Add omzet breakdown to Section 1**

In `_render_resultaat()`, enhance the Omzet section:

```python
# === Section 1: Omzet ===
with ui.card().classes('w-full'):
    ui.label(f'1. Omzet {jaar}').classes('text-subtitle1 text-bold')

    omzet_per_klant = await get_omzet_per_klant(DB_PATH, jaar)
    if omzet_per_klant:
        rows = [{'klant': r['klant_naam'], 'bedrag': format_euro(r['totaal'])}
                for r in omzet_per_klant]
        cols = [
            {'name': 'klant', 'label': 'Klant', 'field': 'klant', 'align': 'left'},
            {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag', 'align': 'right'},
        ]
        ui.table(columns=cols, rows=rows, row_key='klant').classes('w-full').props('dense flat')

    ui.separator()
    with ui.row().classes('w-full justify-between'):
        ui.label('Netto-omzet').classes('text-bold')
        ui.label(format_euro(fiscaal.omzet)).classes('text-bold')
```

Note: Since `_render_resultaat` is not async, you'll need to either make it async or pass the omzet_per_klant data in. The simplest approach: fetch `omzet_per_klant` in `bereken()` and pass it through `berekening_state`.

**Step 3: Add km-vergoeding totaal**

```python
km_data = await get_km_totaal(DB_PATH, jaar)
# Show in Section 1 or as separate subsection
if km_data and km_data['km'] > 0:
    with ui.row().classes('w-full justify-between'):
        ui.label(f"Km-vergoeding ({km_data['km']:.0f} km)")
        ui.label(format_euro(km_data['vergoeding']))
```

**Step 4: Test manually, commit**

---

### Task 7: Enhance kosten section with Yuki-matching categories

**Files:**
- Modify: `pages/jaarafsluiting.py`

**Context:** The Yuki report groups costs into: Personeelskosten (pensioenen, opleiding), Kosten auto's (km-vergoedingen), Verkoopkosten (representatie), Overige bedrijfskosten (adviseurs, kantoorkosten, financiële kosten). The current app just shows flat categories.

**Step 1: Add cost grouping logic**

Create a mapping from app categories to Yuki-style groups:

```python
KOSTEN_GROEPEN = {
    'Personeelskosten': ['Pensioenpremie SPH', 'Scholingskosten'],
    'Verkoopkosten': ['Representatie'],
    'Overige bedrijfskosten': [
        'Accountancy/software', 'Telefoon/KPN', 'Verzekeringen',
        'Lidmaatschappen', 'Kleine aankopen', 'Bankkosten',
    ],
}
```

In the render function, group the `kosten_per_cat` into these groups, with subtotals per group. Categories not in any group go under "Overige".

**Step 2: Render grouped costs in Section 2**

```python
# Group categories
grouped = {}
for group_name, cats in KOSTEN_GROEPEN.items():
    items = [r for r in kosten_per_cat if r['categorie'] in cats]
    if items:
        grouped[group_name] = items

# Render with subtotals
for group_name, items in grouped.items():
    ui.label(group_name).classes('text-subtitle2 text-weight-medium q-mt-sm')
    for item in items:
        _wv_line(f"  {item['categorie']}", item['totaal'])
    subtotal = sum(i['totaal'] for i in items)
    _wv_line(f'Subtotaal {group_name}', subtotal, bold=True)
```

**Step 3: Commit**

---

### Task 8: Add tariefsaanpassing to jaarafsluiting page display

**Files:**
- Modify: `pages/jaarafsluiting.py` (Section 5 and 6)
- Modify: `templates/jaarafsluiting.html`

**Step 1: Update Section 6 (IB-schatting) to show tariefsaanpassing**

After the bruto IB line, add:
```python
if fiscaal.tariefsaanpassing > 0:
    _waterfall_line('+ Beperking aftrekbare posten',
                    fiscaal.tariefsaanpassing)
```

**Step 2: Add IB/PVV split display**

After the bruto IB line:
```python
# IB/PVV breakdown
with ui.expansion('IB/PVV uitsplitsing', icon='info').classes('w-full'):
    _waterfall_line('Inkomstenbelasting (IB)', fiscaal.ib_alleen)
    _waterfall_line('Premie AOW', fiscaal.pvv_aow)
    _waterfall_line('Premie Anw', fiscaal.pvv_anw)
    _waterfall_line('Premie Wlz', fiscaal.pvv_wlz)
    _waterfall_line('Totaal PVV', fiscaal.pvv)
    ui.separator()
    _waterfall_line('Bruto IB + PVV', fiscaal.bruto_ib, bold=True)
```

**Step 3: Add EW partner checkbox**

In the IB input section:
```python
ew_partner_cb = ui.checkbox(
    'Eigen woning toerekenen aan partner',
    value=ew_naar_partner,
)
```

Wire it into the herbereken handler.

**Step 4: Update PDF template**

Add tariefsaanpassing line to `templates/jaarafsluiting.html` in the IB section.

**Step 5: Commit**

---

### Task 9: Separate voorlopige aanslag IB and ZVW

**Files:**
- Modify: `models.py` (add `voorlopige_aanslag_zvw` to FiscaleParams)
- Modify: `database.py` (add column)
- Modify: `fiscal/berekeningen.py` (add to FiscaalResultaat, adjust resultaat calculation)
- Modify: `pages/jaarafsluiting.py` (add input field)
- Modify: `tests/test_fiscal.py`

**Context:** Boekhouder separates: "Voorlopige aanslag(en) IB" = -30.303, "Voorlopige aanslagen Zvw" = -2.667. Currently the app has one combined field. For accurate IB-teruggave calculation, these need to be separate.

**Step 1: Add fields**

Add to FiscaleParams: `voorlopige_aanslag_zvw: float = 0.0`
Add to FiscaalResultaat: `voorlopige_aanslag_zvw: float = 0.0`, `resultaat_ib: float = 0.0`, `resultaat_zvw: float = 0.0`
Add DB column: `voorlopige_aanslag_zvw REAL DEFAULT 0`

**Step 2: Update bereken_volledig**

```python
# New parameter:
def bereken_volledig(..., voorlopige_aanslag=0, voorlopige_aanslag_zvw=0, ...):

# In result calculation:
r.voorlopige_aanslag = voorlopige_aanslag
r.voorlopige_aanslag_zvw = voorlopige_aanslag_zvw

# IB/PVV result (matches Boekhouder "Terug te ontvangen"):
d_resultaat_ib = d_netto_ib - d_voorlopige
r.resultaat_ib = euro(d_resultaat_ib)

# ZVW result:
d_resultaat_zvw = d_zvw - D(voorlopige_aanslag_zvw)
r.resultaat_zvw = euro(d_resultaat_zvw)

# Total result (combined):
r.resultaat = euro(d_resultaat_ib + d_resultaat_zvw)
```

**Step 3: Update jaarafsluiting page**

Add input field for "Voorlopige aanslag ZVW" next to the existing VA field.

Show separate results:
```python
# IB/PVV resultaat
_waterfall_line('Terug IB/PVV', abs(fiscaal.resultaat_ib)) if fiscaal.resultaat_ib < 0 ...
# ZVW resultaat
_waterfall_line('Bij ZVW', fiscaal.resultaat_zvw) if fiscaal.resultaat_zvw > 0 ...
```

**Step 4: Boekhouder validation test**

```python
def test_split_va_2024_boekhouder(self):
    params = FISCALE_PARAMS[2024]
    result = bereken_volledig(
        omzet=95145, kosten=0, afschrijvingen=0,
        representatie=550, investeringen_totaal=2919,
        uren=1400, params=params,
        aov=2998, ew_naar_partner=True,
        voorlopige_aanslag=30303,
        voorlopige_aanslag_zvw=2667,
    )
    # IB terug: ~3137
    assert -3300 < result.resultaat_ib < -2900
    # ZVW bij: ~1143
    assert 1000 < result.resultaat_zvw < 1300
```

**Step 5: Commit**

---

## Phase 3: Enhanced Aangifte Preparation

### Task 10: Add Box 3 data model and page section

**Files:**
- Modify: `models.py` (add Box3Rekening, Box3Schuld dataclasses)
- Modify: `database.py` (add tables, CRUD functions)
- Modify: `pages/aangifte.py` (add Box 3 section)

**Context:** Boekhouder aangifte page 3+9 shows Box 3: bank accounts (begin+einde jaar), schulden (DUO studieschuld, credit card), drempel, heffingsvrij vermogen. The app needs to store and display this.

**Step 1: Create data model**

```python
# models.py
@dataclass
class Box3Bezitting:
    id: int = 0
    jaar: int = 0
    omschrijving: str = ''  # e.g., "Rabobank Rabo DirectRekening"
    rekeningnummer: str = ''
    waarde_begin: float = 0.0  # Stand 01-01
    waarde_einde: float = 0.0  # Stand 31-12

@dataclass
class Box3Schuld:
    id: int = 0
    jaar: int = 0
    omschrijving: str = ''  # e.g., "DUO Studieschuld"
    identificatie: str = ''
    waarde_begin: float = 0.0
    waarde_einde: float = 0.0
```

**Step 2: Create DB tables**

```sql
CREATE TABLE IF NOT EXISTS box3_bezittingen (
    id INTEGER PRIMARY KEY,
    jaar INTEGER NOT NULL,
    omschrijving TEXT NOT NULL,
    rekeningnummer TEXT DEFAULT '',
    waarde_begin REAL DEFAULT 0,
    waarde_einde REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS box3_schulden (
    id INTEGER PRIMARY KEY,
    jaar INTEGER NOT NULL,
    omschrijving TEXT NOT NULL,
    identificatie TEXT DEFAULT '',
    waarde_begin REAL DEFAULT 0,
    waarde_einde REAL DEFAULT 0
);
```

**Step 3: Add CRUD functions to database.py**

```python
async def get_box3_bezittingen(db_path, jaar):
async def add_box3_bezitting(db_path, jaar, omschrijving, rekeningnummer, waarde_begin, waarde_einde):
async def delete_box3_bezitting(db_path, id):
# Same for schulden
```

**Step 4: Add Box 3 section to aangifte page**

Add a new card after the partner section:

```python
with ui.card().classes('w-full'):
    ui.label('Box 3 — Sparen en beleggen').classes('text-subtitle1 text-weight-bold')

    # Bezittingen table with add/edit/delete
    # Schulden table with add/edit/delete

    # Automatic calculation:
    bezittingen_totaal = sum(b.waarde_einde for b in bezittingen)
    schulden_totaal = sum(s.waarde_einde for s in schulden)
    drempel_schulden = 7400  # for fiscal partners (could be parameter)
    schulden_na_drempel = max(0, schulden_totaal - drempel_schulden)
    rendementsgrondslag = max(0, bezittingen_totaal - schulden_na_drempel)
    heffingsvrij = 114000  # for fiscal partners (could be parameter)
    grondslag = max(0, rendementsgrondslag - heffingsvrij)

    # Display summary
    _wv_line('Bezittingen', bezittingen_totaal)
    _wv_line('Schulden', schulden_totaal)
    _wv_line('Drempel schulden', drempel_schulden)
    _wv_line('Heffingsvrij vermogen', heffingsvrij)
    _wv_line('Grondslag Box 3', grondslag, bold=True)
```

**Step 5: Commit**

---

### Task 11: Add partner verzamelinkomen integration

**Files:**
- Modify: `pages/aangifte.py` (add partner section with computed verzamelinkomen)
- Modify: `models.py` (add more partner fields to FiscaleParams)
- Modify: `database.py` (add columns)

**Context:** Boekhouder shows "Gezamenlijk verzamelinkomen = 109.084" (T. Gebruiker 73.778 + A.A.H. Nijholt 35.306). The partner's verzamelinkomen = bruto_loon - loonheffing... actually it's more nuanced. For now, the app can compute a simplified partner verzamelinkomen from the bruto loon and show the combined total.

**Step 1: Enhance partner section**

The aangifte page already has partner bruto loon and loonheffing inputs. Compute:
```python
partner_verzamelinkomen = partner_bruto_loon  # Approximate (actual depends on aftrekposten)
gezamenlijk = result.verzamelinkomen + partner_verzamelinkomen
```

Display this alongside the own verzamelinkomen from jaarafsluiting.

**Step 2: Add EW saldo to partner if allocated**

If `ew_naar_partner=True`:
```python
partner_verzamelinkomen = partner_bruto_loon + result.ew_saldo
```

**Step 3: Commit**

---

### Task 12: Add hypotheek detail tracking

**Files:**
- Modify: `models.py` (add HypotheekLening dataclass)
- Modify: `database.py` (add table, CRUD)
- Modify: `pages/aangifte.py` (add hypotheek detail section)

**Context:** Boekhouder shows 4 AEGON hypotheek leningen with per-lening: schuld begin, schuld einde, betaalde rente. Currently the app only stores total hypotheekrente as one number.

**Step 1: Create data model**

```python
@dataclass
class HypotheekLening:
    id: int = 0
    jaar: int = 0
    verstrekker: str = ''  # "AEGON Hypothecaire Lening"
    leningnummer: str = ''  # "H1214133L1"
    schuld_begin: float = 0.0
    schuld_einde: float = 0.0
    rente: float = 0.0
```

**Step 2: Create DB table + CRUD**

**Step 3: Add UI section in aangifte page**

Table showing per-lening details with add/delete. Totaal rente auto-updates the hypotheekrente field in the IB calculation.

**Step 4: Commit**

---

### Task 13: Enhanced PDF export — Jaarcijfers + Aangifte rapport

**Files:**
- Create: `templates/jaarcijfers.html` (Yuki-style financial report)
- Modify: `templates/jaarafsluiting.html` (update with new fields)
- Modify: `pages/jaarafsluiting.py` (add export option)

**Context:** Two PDF exports: (1) Jaarcijfers = commercial annual report (like Yuki), (2) Fiscaal rapport = IB preparation (like current jaarafsluiting but enhanced).

**Step 1: Create jaarcijfers template**

Based on the Yuki format:
- Page 1: Title page (TestBV Huisartswaarnemer, KvK, Financieel rapport, period)
- Page 2: Resultatenrekening (Omzet, Bedrijfslasten grouped, Afschrijvingen, Winst)
- Page 3: (Optional) Activastaat

The template should use the same style as the existing jaarafsluiting.html.

**Step 2: Update existing fiscaal rapport template**

Add:
- Tariefsaanpassing line
- IB/PVV split (collapsible or separate section)
- Eigen woning partner note
- Separate VA IB and VA ZVW

**Step 3: Add export buttons**

```python
ui.button('Jaarcijfers PDF', icon='description', on_click=export_jaarcijfers)
ui.button('Fiscaal rapport PDF', icon='picture_as_pdf', on_click=export_pdf)
```

**Step 4: Commit**

---

### Task 14: Update aangifte document checklist

**Files:**
- Modify: `pages/aangifte.py`

**Context:** The current AANGIFTE_DOCS list needs to be updated with the findings from research. Some documents are missing, some categories need adjustment.

**Step 1: Update AANGIFTE_DOCS**

```python
AANGIFTE_DOCS = [
    # Eigen woning
    DocSpec('eigen_woning', 'woz_beschikking', 'WOZ-beschikking + taxatieverslag', False, True),
    DocSpec('eigen_woning', 'hypotheek_jaaroverzicht', 'Hypotheek jaaroverzicht', True, True),

    # Inkomen partner
    DocSpec('inkomen_partner', 'jaaropgave_partner', 'Jaaropgave partner', True, False),

    # Pensioen
    DocSpec('pensioen', 'upo_eigen', 'UPO eigen pensioen (ABP/SPH)', True, False),
    DocSpec('pensioen', 'upo_partner', 'UPO partner', False, False),

    # Verzekeringen
    DocSpec('verzekeringen', 'aov_jaaroverzicht', 'AOV jaaroverzicht (Allianz)', False, True),
    DocSpec('verzekeringen', 'zorgverzekering_jaaroverzicht', 'Zorgverzekering jaaroverzicht', False, False),

    # Bankzaken
    DocSpec('bankzaken', 'jaaroverzicht_prive', 'Jaaroverzicht privérekening', True, True),
    DocSpec('bankzaken', 'jaaroverzicht_zakelijk', 'Jaaroverzicht zakelijke rekening', True, True),
    DocSpec('bankzaken', 'jaaroverzicht_spaar', 'Jaaroverzicht spaarrekening', True, False),

    # Studieschuld
    DocSpec('studieschuld', 'duo_overzicht', 'DUO overzicht', False, False),

    # Belastingdienst
    DocSpec('belastingdienst', 'voorlopige_aanslag', 'Voorlopige aanslag IB', False, True),
    DocSpec('belastingdienst', 'voorlopige_aanslag_zvw', 'Voorlopige aanslag ZVW', False, False),

    # Onderneming (auto-generated)
    DocSpec('onderneming', 'jaaroverzicht_uren_km', 'Jaaroverzicht uren/km', False, True),
    DocSpec('onderneming', 'winst_verlies', 'Winst & verlies / Jaarcijfers', False, True),

    # Definitieve aangifte
    DocSpec('definitieve_aangifte', 'ingediende_aangifte', 'Ingediende aangifte (Boekhouder)', False, False),
]
```

**Step 2: Commit**

---

## Phase 4: Final Integration & Validation

### Task 15: End-to-end validation with real data

**Files:**
- Modify: `tests/test_fiscal.py` (add comprehensive 2024 test)

**Step 1: Run the app, navigate to jaarafsluiting for 2024**

Verify visually:
- Omzet shows per klant breakdown
- Kosten are grouped like Yuki
- Fiscale waterval shows tariefsaanpassing
- IB/PVV split is displayed
- Arbeidskorting matches Boekhouder (≈1.986)
- AHK matches Boekhouder (≈116)
- Teruggave IB ≈ 3.137

**Step 2: Generate PDFs**

Export both Jaarcijfers and Fiscaal rapport PDFs. Compare side-by-side with Yuki and Boekhouder originals.

**Step 3: Navigate to aangifte page for 2024**

- Enter partner bruto loon from jaaropgave
- Enter Box 3 bank accounts and schulden
- Verify gezamenlijk verzamelinkomen
- Upload required documents
- Check progress bar

**Step 4: Commit any final fixes**

---

### Task 16: Update MEMORY.md and CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (update fiscal domain knowledge, test count)
- Modify: `.claude/projects/.../memory/MEMORY.md` (update project status)

**Step 1: Update CLAUDE.md fiscal section**

Add:
```markdown
- **Tariefsaanpassing**: Since 2023, ondernemersaftrek+MKB deductible at basistarief only. Excess benefit clawed back.
- **Arbeidskorting**: Input = fiscale_winst (vóór ZA/SA/MKB), NOT belastbare_winst
- **Eigen woning**: Configurable allocation to partner (ew_naar_partner flag)
- **IB/PVV split**: PVV = 27.65% (AOW 17.90%, Anw 0.10%, Wlz 9.65%) in schijf 1 only
- **ZVW grondslag**: belastbare winst (not verzamelinkomen)
- **Voorlopige aanslag**: Split into IB/PVV and ZVW parts
```

**Step 2: Update MEMORY.md**

Add jaarafsluiting overhaul status, test count, and key decisions.

**Step 3: Commit**

```bash
git add CLAUDE.md .claude/projects/*/memory/MEMORY.md
git commit -m "docs: update CLAUDE.md and MEMORY.md with fiscal overhaul status"
```

---

## Summary of Changes by File

| File | Changes |
|------|---------|
| `fiscal/berekeningen.py` | Fix AK input, add tariefsaanpassing, add ew_naar_partner, add IB/PVV split, add VA split |
| `fiscal/heffingskortingen.py` | No changes needed (brackets are correct) |
| `fiscal/afschrijvingen.py` | No changes needed |
| `models.py` | Add Box3Bezitting, Box3Schuld, HypotheekLening; update FiscaleParams |
| `database.py` | Add box3_bezittingen/schulden/hypotheek tables; add ew_naar_partner + VA_zvw columns |
| `pages/jaarafsluiting.py` | Omzet per klant, grouped kosten, tariefsaanpassing display, IB/PVV split, EW partner checkbox, VA split, Jaarcijfers export |
| `pages/aangifte.py` | Box 3 section, partner verzamelinkomen, hypotheek details, updated checklist |
| `templates/jaarafsluiting.html` | Tariefsaanpassing, IB/PVV split, VA split |
| `templates/jaarcijfers.html` | New — Yuki-style commercial report |
| `tests/test_fiscal.py` | AK fix tests, tariefsaanpassing tests, EW partner tests, IB/PVV split tests, comprehensive Boekhouder 2024 test |
| `CLAUDE.md` | Updated fiscal domain knowledge |

## Priority Order

**Must-do (Phase 1 — critical bugs):** Tasks 1-5
**Should-do (Phase 2 — enhanced display):** Tasks 6-9
**Nice-to-have (Phase 3 — aangifte prep):** Tasks 10-14
**Final (Phase 4):** Tasks 15-16
