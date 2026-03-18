# Dashboard & Reporting UX Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard tax forecast accurate by extrapolating annual income from YTD data, falling back to prior-year personal data when missing, and improving the W&V year report with km-vergoeding detail and year-over-year comparison.

**Architecture:** Add two helper functions to `components/fiscal_utils.py` (extrapolation + fallback), rewrite `_compute_ib_estimate` in `pages/dashboard.py` to use them, restructure dashboard KPI layout to CSS grid, and extend `render_wv` in `pages/jaarafsluiting.py` with a comparison column. Navigation improvements in `components/layout.py`.

**Tech Stack:** NiceGUI 3.8+, Python 3.12+, SQLite/aiosqlite, ECharts, Quasar/Vue

**Spec:** `docs/superpowers/specs/2026-03-18-dashboard-ux-overhaul-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `components/fiscal_utils.py` | Modify | Add `extrapoleer_jaaromzet()` and `get_personal_data_with_fallback()` |
| `pages/dashboard.py` | Modify | Rewrite `_compute_ib_estimate`, CSS grid KPIs, enhanced prognose card |
| `pages/jaarafsluiting.py` | Modify | W&V km-vergoeding line, year-over-year comparison |
| `components/layout.py` | Modify | Move Klanten below separator, add global year to header |
| `tests/test_fiscal.py` | Modify | Add tests for extrapolation and fallback functions |

---

### Task 1: Income Extrapolation Helper

**Files:**
- Modify: `components/fiscal_utils.py` (add function after `bereken_balans`, ~line 193)
- Test: `tests/test_fiscal.py` (add new test class at end)

- [ ] **Step 1: Write failing tests for `extrapoleer_jaaromzet`**

```python
# tests/test_fiscal.py — add at end

class TestExtrapoleerJaaromzet:
    """Tests for annual income extrapolation."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Create temp DB with test data."""
        import asyncio
        from database import init_db, add_klant
        db = tmp_path / 'test.db'
        asyncio.run(init_db(db))
        # Add a klant
        asyncio.run(add_klant(db, naam='Test', tarief_uur=80, retour_km=0))
        return db

    def test_past_year_returns_actual(self, db_path):
        """Past year: no extrapolation, use actual totals."""
        import asyncio
        from database import add_factuur
        from components.fiscal_utils import extrapoleer_jaaromzet
        asyncio.run(add_factuur(db_path, nummer='2024-001', klant_id=1,
                                 datum='2024-06-15', totaal_uren=8,
                                 totaal_km=0, totaal_bedrag=10000))
        result = asyncio.run(extrapoleer_jaaromzet(db_path, 2024))
        assert result['method'] == 'actual'
        assert result['extrapolated_omzet'] == 10000
        assert result['confidence'] == 'high'

    def test_extrapolation_linear(self, db_path):
        """Current year: linear extrapolation from YTD."""
        import asyncio
        from datetime import date
        from database import add_factuur
        from components.fiscal_utils import extrapoleer_jaaromzet
        # Add 3 months of revenue (Jan-Mar)
        for m in range(1, 4):
            asyncio.run(add_factuur(db_path, nummer=f'2026-{m:03d}', klant_id=1,
                                     datum=f'2026-{m:02d}-15', totaal_uren=80,
                                     totaal_km=0, totaal_bedrag=10000))
        result = asyncio.run(extrapoleer_jaaromzet(db_path, date.today().year))
        # 30000 YTD in ~3 months → ~120000 annual
        assert result['ytd_omzet'] == 30000
        assert 100000 < result['extrapolated_omzet'] < 140000
        assert result['confidence'] in ('low', 'medium')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestExtrapoleerJaaromzet -v`
Expected: FAIL with ImportError (function doesn't exist yet)

- [ ] **Step 3: Implement `extrapoleer_jaaromzet`**

Add to `components/fiscal_utils.py` after `bereken_balans`:

```python
async def extrapoleer_jaaromzet(db_path: Path, jaar: int) -> dict:
    """Extrapolate annual revenue from YTD data.

    Returns dict with ytd_omzet, extrapolated_omzet, method, confidence, basis_maanden.
    Past years return actual data with confidence='high'.
    Current year extrapolates linearly, weighted with prior-year pattern if available.
    """
    from datetime import date as _d
    huidig_jaar = _d.today().year

    ytd_omzet = await get_omzet_totaal(db_path, jaar)

    if jaar != huidig_jaar:
        return {
            'ytd_omzet': ytd_omzet,
            'extrapolated_omzet': ytd_omzet,
            'method': 'actual',
            'confidence': 'high',
            'basis_maanden': 12,
        }

    month = _d.today().month
    complete_months = month if _d.today().day >= 15 else max(month - 1, 1)

    if complete_months == 0 or ytd_omzet == 0:
        return {
            'ytd_omzet': 0,
            'extrapolated_omzet': 0,
            'method': 'ytd_linear',
            'confidence': 'low',
            'basis_maanden': 0,
        }

    linear = ytd_omzet * (12 / complete_months)

    # Weight with prior-year monthly pattern if available
    # NOTE: get_omzet_per_maand returns list[float] (index 0=Jan .. 11=Dec)
    prior_maanden = await get_omzet_per_maand(db_path, jaar - 1)
    prior_total = sum(prior_maanden)

    if prior_total > 0 and complete_months >= 3:
        prior_ytd = sum(prior_maanden[:month])
        prior_fraction = prior_ytd / prior_total if prior_total > 0 else (month / 12)
        if prior_fraction > 0.05:
            pattern = ytd_omzet / prior_fraction
            extrapolated = round(0.7 * linear + 0.3 * pattern, 2)
        else:
            extrapolated = round(linear, 2)
    else:
        extrapolated = round(linear, 2)

    if complete_months <= 2:
        confidence = 'low'
    elif complete_months <= 5:
        confidence = 'medium'
    else:
        confidence = 'high'

    return {
        'ytd_omzet': ytd_omzet,
        'extrapolated_omzet': extrapolated,
        'method': 'weighted' if prior_total > 0 and complete_months >= 3 else 'ytd_linear',
        'confidence': confidence,
        'basis_maanden': complete_months,
    }
```

Add `get_omzet_per_maand` to the import block at `fiscal_utils.py:7-20`:
```python
from database import (
    get_afschrijving_overrides_batch,
    get_data_counts,
    get_fiscale_params,
    get_investeringen,
    get_investeringen_voor_afschrijving,
    get_km_totaal,
    get_omzet_per_maand,       # ADD THIS
    get_omzet_totaal,
    get_debiteuren_op_peildatum,
    get_nog_te_factureren,
    get_representatie_totaal,
    get_uitgaven_per_categorie,
    get_uren_totaal,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestExtrapoleerJaaromzet -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add components/fiscal_utils.py tests/test_fiscal.py
git commit -m "feat: add income extrapolation helper for dashboard forecast"
```

---

### Task 2: Prior-Year Data Fallback Helper

**Files:**
- Modify: `components/fiscal_utils.py` (add function after `extrapoleer_jaaromzet`)
- Test: `tests/test_fiscal.py` (add new test class)

- [ ] **Step 1: Write failing tests**

```python
class TestPersonalDataFallback:
    """Tests for prior-year personal data fallback."""

    def test_current_year_values_preferred(self):
        from components.fiscal_utils import get_personal_data_with_fallback
        current = type('P', (), {'woz_waarde': 700000, 'hypotheekrente': 7000,
                                  'aov_premie': 3500, 'partner_bruto_loon': 0,
                                  'partner_loonheffing': 0, 'box3_bank_saldo': 0,
                                  'box3_overige_bezittingen': 0, 'box3_schulden': 0})()
        prior = type('P', (), {'woz_waarde': 650000, 'hypotheekrente': 7200,
                                'aov_premie': 3000, 'partner_bruto_loon': 40000,
                                'partner_loonheffing': 7000, 'box3_bank_saldo': 25000,
                                'box3_overige_bezittingen': 0, 'box3_schulden': 35000})()
        result, fallbacks = get_personal_data_with_fallback(current, prior)
        assert result['woz']['value'] == 700000
        assert result['woz']['source'] == 'current'
        assert 'woz_waarde' not in fallbacks

    def test_fallback_to_prior_year(self):
        from components.fiscal_utils import get_personal_data_with_fallback
        current = type('P', (), {'woz_waarde': 0, 'hypotheekrente': 0,
                                  'aov_premie': 0, 'partner_bruto_loon': 0,
                                  'partner_loonheffing': 0, 'box3_bank_saldo': 0,
                                  'box3_overige_bezittingen': 0, 'box3_schulden': 0})()
        prior = type('P', (), {'woz_waarde': 650000, 'hypotheekrente': 7200,
                                'aov_premie': 3000, 'partner_bruto_loon': 40000,
                                'partner_loonheffing': 7000, 'box3_bank_saldo': 25000,
                                'box3_overige_bezittingen': 0, 'box3_schulden': 35000})()
        result, fallbacks = get_personal_data_with_fallback(current, prior)
        assert result['woz']['value'] == 650000
        assert result['woz']['source'] == 'prior'
        assert 'woz_waarde' in fallbacks

    def test_no_prior_returns_zero(self):
        from components.fiscal_utils import get_personal_data_with_fallback
        current = type('P', (), {'woz_waarde': 0, 'hypotheekrente': 0,
                                  'aov_premie': 0, 'partner_bruto_loon': 0,
                                  'partner_loonheffing': 0, 'box3_bank_saldo': 0,
                                  'box3_overige_bezittingen': 0, 'box3_schulden': 0})()
        result, fallbacks = get_personal_data_with_fallback(current, None)
        assert result['woz']['value'] == 0
        assert result['woz']['source'] == 'none'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestPersonalDataFallback -v`
Expected: FAIL (function doesn't exist)

- [ ] **Step 3: Implement `get_personal_data_with_fallback`**

Add to `components/fiscal_utils.py`:

```python
def get_personal_data_with_fallback(params_current, params_prior) -> tuple[dict, list[str]]:
    """Use current-year data if available, fall back to prior year.

    Returns (result_dict, fallbacks_used_list).
    result_dict maps short keys to {'value': float, 'source': 'current'|'prior'|'none'}.
    """
    fields = {
        'woz_waarde': 'woz',
        'hypotheekrente': 'hypotheekrente',
        'aov_premie': 'aov',
        'partner_bruto_loon': 'partner_loon',
        'partner_loonheffing': 'partner_lh',
        'box3_bank_saldo': 'box3_bank',
        'box3_overige_bezittingen': 'box3_overig',
        'box3_schulden': 'box3_schulden',
    }

    result = {}
    fallbacks = []

    for attr, key in fields.items():
        current_val = getattr(params_current, attr, 0) or 0
        if current_val > 0:
            result[key] = {'value': current_val, 'source': 'current'}
        elif params_prior:
            prior_val = getattr(params_prior, attr, 0) or 0
            if prior_val > 0:
                result[key] = {'value': prior_val, 'source': 'prior'}
                fallbacks.append(attr)
            else:
                result[key] = {'value': 0, 'source': 'none'}
        else:
            result[key] = {'value': 0, 'source': 'none'}

    return result, fallbacks
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestPersonalDataFallback -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add components/fiscal_utils.py tests/test_fiscal.py
git commit -m "feat: add prior-year personal data fallback helper"
```

---

### Task 3: Rewrite Dashboard `_compute_ib_estimate` with Extrapolation

**Files:**
- Modify: `pages/dashboard.py` lines 68-110 (`_compute_ib_estimate` function)

- [ ] **Step 1: Rewrite `_compute_ib_estimate`**

Replace the current function at `pages/dashboard.py:68-110` with:

```python
async def _compute_ib_estimate(jaar: int) -> dict | None:
    """Compute IB estimate. For current year: extrapolates income and uses prior-year fallback."""
    data = await fetch_fiscal_data(DB_PATH, jaar)
    if data is None:
        return None

    try:
        huidig_jaar = date.today().year
        annual_va_ib = data['voorlopige_aanslag']
        annual_va_zvw = data['voorlopige_aanslag_zvw']

        if jaar == huidig_jaar:
            month = date.today().month
            # Extrapolate income
            projection = await extrapoleer_jaaromzet(DB_PATH, jaar)
            complete_months = projection['basis_maanden'] or 1
            kosten_factor = 12 / complete_months

            extrapolated_kosten = data['kosten_excl_inv'] * kosten_factor
            extrapolated_repr = data['representatie'] * kosten_factor
            extrapolated_uren = data['uren'] * kosten_factor

            # Prior-year fallback for personal data
            params_prior = await get_fiscale_params(DB_PATH, jaar - 1)
            personal, fallbacks = get_personal_data_with_fallback(data['params'], params_prior)

            # Prorate VA for "how much have I paid so far"
            va_ib_ytd = round(annual_va_ib * month / 12, 2)
            va_zvw_ytd = round(annual_va_zvw * month / 12, 2)

            f = bereken_volledig(
                omzet=projection['extrapolated_omzet'],
                kosten=extrapolated_kosten,
                afschrijvingen=data['totaal_afschrijvingen'],
                representatie=extrapolated_repr,
                investeringen_totaal=data['inv_totaal_dit_jaar'],
                uren=extrapolated_uren,
                params=data['params_dict'],
                aov=personal['aov']['value'],
                lijfrente=data.get('lijfrente', 0),
                woz=personal['woz']['value'],
                hypotheekrente=personal['hypotheekrente']['value'],
                voorlopige_aanslag=annual_va_ib,
                voorlopige_aanslag_zvw=annual_va_zvw,
                ew_naar_partner=data['ew_naar_partner'],
            )
            return {
                'resultaat': f.resultaat,
                'netto_ib': f.netto_ib,
                'zvw': f.zvw,
                'winst': f.winst,
                'va_ib_betaald': va_ib_ytd,
                'va_zvw_betaald': va_zvw_ytd,
                'prorated': True,
                'month': month,
                'confidence': projection['confidence'],
                'fallbacks': fallbacks,
                'extrapolated_omzet': projection['extrapolated_omzet'],
                'ytd_omzet': projection['ytd_omzet'],
                'basis_maanden': projection['basis_maanden'],
            }
        else:
            f = bereken_volledig(
                omzet=data['omzet'], kosten=data['kosten_excl_inv'],
                afschrijvingen=data['totaal_afschrijvingen'],
                representatie=data['representatie'],
                investeringen_totaal=data['inv_totaal_dit_jaar'],
                uren=data['uren'], params=data['params_dict'],
                aov=data['aov'], lijfrente=data.get('lijfrente', 0),
                woz=data['woz'], hypotheekrente=data['hypotheekrente'],
                voorlopige_aanslag=annual_va_ib,
                voorlopige_aanslag_zvw=annual_va_zvw,
                ew_naar_partner=data['ew_naar_partner'],
            )
            return {
                'resultaat': f.resultaat,
                'netto_ib': f.netto_ib,
                'zvw': f.zvw,
                'winst': f.winst,
                'va_ib_betaald': annual_va_ib,
                'va_zvw_betaald': annual_va_zvw,
                'prorated': False,
                'month': 12,
                'confidence': 'high',
                'fallbacks': [],
                'extrapolated_omzet': data['omzet'],
                'ytd_omzet': data['omzet'],
                'basis_maanden': 12,
            }
    except Exception:
        import traceback
        traceback.print_exc()
        return None
```

Add imports at top of `dashboard.py`:
```python
from components.fiscal_utils import fetch_fiscal_data, extrapoleer_jaaromzet, get_personal_data_with_fallback
```

- [ ] **Step 2: Verify module imports cleanly**

Run: `.venv/bin/python -c "import pages.dashboard; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add pages/dashboard.py
git commit -m "feat: dashboard tax forecast with income extrapolation and data fallback"
```

---

### Task 4: Dashboard KPI Layout Restructure

**Files:**
- Modify: `pages/dashboard.py` lines 138-236 (KPI rendering in `refresh_dashboard`)

- [ ] **Step 1: Replace three `ui.row` wrappers with CSS grid**

In `refresh_dashboard`, replace the KPI section (lines 138-236) with a single CSS grid container. Key changes:

1. Replace `with ui.row().classes('w-full gap-4 flex-wrap'):` (three instances) with one:
   ```python
   with ui.element('div').classes('w-full') \
           .style('display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px'):
   ```

2. Render all KPI cards as direct children of the grid (no row grouping).

3. Enhanced belasting prognose card extra section with progress bars:
   ```python
   def ib_extra(d=ib_data, vt=va_totaal):
       with ui.column().classes('gap-1 q-mt-xs w-full'):
           belasting = d['netto_ib'] + d['zvw']
           # Progress bars: berekend vs VA
           for label, value, color in [
               ('Berekend', belasting, 'negative'),
               ('VA betaald' if not d['prorated'] else f"VA t/m {_MND[d['month']]}", -vt, 'positive'),
           ]:
               with ui.row().classes('w-full items-center gap-2'):
                   ui.label(label).classes('text-caption').style('width: 70px; color: #64748B')
                   max_val = max(abs(belasting), abs(vt), 1)
                   ui.linear_progress(
                       value=min(abs(value) / max_val, 1.0), color=color,
                   ).classes('flex-grow').props('rounded size=6px')
                   ui.label(format_euro(value)).classes('text-caption') \
                       .style('min-width: 80px; text-align: right; font-variant-numeric: tabular-nums')
           # Confidence badge
           conf = d.get('confidence', 'high')
           conf_labels = {'low': 'Schatting', 'medium': 'Prognose', 'high': 'Betrouwbaar'}
           conf_colors = {'low': 'warning', 'medium': 'primary', 'high': 'positive'}
           ui.badge(conf_labels[conf], color=conf_colors[conf]).classes('text-xs q-mt-xs')
           # Fallback hint
           if d.get('fallbacks'):
               names = {'hypotheekrente': 'hypotheek', 'woz_waarde': 'WOZ', 'aov_premie': 'AOV'}
               items = ', '.join(names.get(f, f) for f in d['fallbacks'] if f in names)
               if items:
                   ui.label(f'Gebruikt {jaar-1} waarden: {items}') \
                       .classes('text-caption text-grey-6').style('font-style: italic')
   ```

4. Remove "Recente facturen" section (lines ~319-354 in current file).

5. Remove "Facturen (count)" KPI card.

6. Clean up unused imports and `asyncio.gather` entries: remove `get_recente_facturen`, `get_factuur_count` from the import block (line 14) and from the `asyncio.gather` call (lines 117-130). Remove corresponding variables `recente` and `factuur_count` from the unpacking.

- [ ] **Step 2: Verify layout renders correctly**

Run: `python main.py` and check dashboard at http://127.0.0.1:8085
Expected: KPI cards in responsive grid, belasting prognose shows progress bars and confidence badge.

- [ ] **Step 3: Commit**

```bash
git add pages/dashboard.py
git commit -m "feat: dashboard CSS grid KPIs with enhanced tax forecast card"
```

---

### Task 5: W&V Year-over-Year Comparison + Km-vergoeding Line

**Files:**
- Modify: `pages/jaarafsluiting.py` lines 307-349 (`render_wv` function)

- [ ] **Step 1: Load prior-year data**

In `jaarafsluiting.py`, the `_load_year_data` function (line 38) already fetches `vorig_jaar_data` at line 60 via `fetch_fiscal_data(DB_PATH, jaar - 1)` and computes `vj_winst` at line 64. Currently it returns `(data, balans, winst, vorig_jaar_balans)` at line 86.

**Modify `_load_year_data` return** to also include `vorig_jaar_data` and `vj_winst`:

```python
# Line 86: change return to include vorig_jaar_data and vj_winst
return data, balans, winst, vorig_jaar_balans, vorig_jaar_data, (vj_winst if vorig_jaar_data else None)
```

**Modify `render_all`** (line 138) which calls `_load_year_data`:

```python
# Line 182: update the unpacking
data, balans, winst, vorig_jaar_balans, vorig_jaar_data, vorig_winst = await _load_year_data(state['jaar'])
```

**Update the `render_wv` call** at line 186:

```python
render_wv(data, winst, vorig_jaar_data, vorig_winst)
```

- [ ] **Step 2: Extend `render_wv` for comparison + km-vergoeding**

Modify `render_wv` signature and body:

```python
def render_wv(data, winst, vorig_data=None, vorig_winst=None):
    """Render W&V tab with optional year-over-year comparison."""
    wv_panel.clear()
    with wv_panel:
        # ... existing data source badges ...

        has_vorig = vorig_data is not None and vorig_data['omzet'] > 0

        def _wv_line_vergelijk(label, bedrag, vorig_bedrag=None, bold=False, indent=False):
            """W&V line with optional prior-year column and delta."""
            css = 'text-bold' if bold else ''
            ml = 'q-ml-md' if indent else ''
            with ui.row().classes(f'w-full items-center {ml}').style('min-height: 28px'):
                ui.label(label).classes(f'{css} flex-grow')
                ui.label(format_euro(bedrag)).classes(css) \
                    .style('width: 110px; text-align: right; font-variant-numeric: tabular-nums')
                if has_vorig:
                    vb = vorig_bedrag if vorig_bedrag is not None else 0
                    ui.label(format_euro(vb)).classes('text-grey-6') \
                        .style('width: 110px; text-align: right; font-variant-numeric: tabular-nums')
                    if vb and bedrag:
                        delta = (bedrag - vb) / abs(vb) * 100
                        color = 'text-positive' if delta >= 0 else 'text-negative'
                        ui.label(f'{delta:+.1f}%').classes(f'text-caption {color}') \
                            .style('width: 60px; text-align: right')

        ui.label('Winst- en verliesrekening').classes('text-h6 text-primary')
        with ui.card().classes('w-full q-pa-md'):
            # Column headers
            if has_vorig:
                with ui.row().classes('w-full items-center').style('min-height: 24px'):
                    ui.label('').classes('flex-grow')
                    ui.label(str(state['jaar'])).classes('text-caption text-bold') \
                        .style('width: 110px; text-align: right')
                    ui.label(str(state['jaar'] - 1)).classes('text-caption text-grey-6') \
                        .style('width: 110px; text-align: right')
                    ui.label('Δ').classes('text-caption text-grey-6') \
                        .style('width: 60px; text-align: right')

            vorig_omzet = vorig_data['omzet'] if has_vorig else None
            _wv_line_vergelijk('Netto-omzet', data['omzet'], vorig_omzet, bold=True)
            ui.separator().classes('q-my-sm')

            # Km-vergoeding as separate line
            vorig_km = vorig_data.get('km_vergoeding', 0) if has_vorig else None
            _wv_line_vergelijk('Km-vergoeding', data['km_vergoeding'], vorig_km, indent=True)

            # Overige bedrijfskosten = kosten_excl_inv - km_vergoeding
            overige = data['kosten_excl_inv'] - data['km_vergoeding']
            vorig_overige = (vorig_data['kosten_excl_inv'] - vorig_data.get('km_vergoeding', 0)) if has_vorig else None
            _wv_line_vergelijk('Overige bedrijfskosten', overige, vorig_overige, indent=True)

            vorig_afschr = vorig_data['totaal_afschrijvingen'] if has_vorig else None
            _wv_line_vergelijk('Afschrijvingen', data['totaal_afschrijvingen'], vorig_afschr)
            ui.separator().classes('q-my-sm')
            _wv_line_vergelijk('Winst', winst, vorig_winst, bold=True)

        # Kostenspecificatie (unchanged — keep existing code)
```

- [ ] **Step 3: Verify jaarafsluiting renders correctly**

Run app and navigate to Jaarafsluiting → W&V tab for 2025 (should show 2024 comparison column).

- [ ] **Step 4: Commit**

```bash
git add pages/jaarafsluiting.py
git commit -m "feat: W&V year-over-year comparison with km-vergoeding as separate line"
```

---

### Task 6: Navigation Improvements

**Files:**
- Modify: `components/layout.py` lines 62-74 (PAGES list), header section

- [ ] **Step 1: Move Klanten below separator**

In `components/layout.py`, change the PAGES list:

```python
PAGES = [
    ('DAGELIJKS', None, None),
    ('Dashboard', 'dashboard', '/'),
    ('Werkdagen', 'schedule', '/werkdagen'),
    ('Facturen', 'receipt', '/facturen'),
    ('FINANCIEEL', None, None),
    ('Kosten', 'payments', '/kosten'),
    ('Bank', 'account_balance', '/bank'),
    ('JAAREINDE', None, None),
    ('Jaarafsluiting', 'bar_chart', '/jaarafsluiting'),
    ('Aangifte', 'fact_check', '/aangifte'),
]
```

Then render Klanten below the separator alongside Instellingen (both are "setup" pages). Find the separator + Instellingen section (around line 125-136 in `layout.py`) and add a Klanten button in the same pattern:

```python
# After the separator, before Instellingen:
ui.separator().classes('q-mx-md q-my-sm').style('border-color: #334155')

# Klanten
active_cls = 'bg-teal-9 text-white' if active_page == '/klanten' else ''
ui.button('Klanten', icon='people',
          on_click=lambda: ui.navigate.to('/klanten')) \
    .classes(f'w-full justify-start text-left q-px-md text-sm {active_cls}') \
    .props('flat no-caps align=left') \
    .style('color: #CBD5E1; border-radius: 8px')

# Instellingen (existing code)
```

- [ ] **Step 2: Add global year to header**

In the header section of `create_layout`, show the active year:

```python
# In the header row, after the main title
with ui.row().classes('items-center gap-2'):
    ui.label('Boekhouding').classes('text-h6 text-white q-ml-sm')
```

This is informational only — the actual global year persistence is a separate task if desired.

- [ ] **Step 3: Verify navigation**

Run app and check: Klanten appears below the separator, header shows app title.

- [ ] **Step 4: Commit**

```bash
git add components/layout.py
git commit -m "fix: move Klanten to setup section in sidebar navigation"
```

---

### Task 7: Full Test Suite Verification

**Files:**
- All modified files

- [ ] **Step 1: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All 412+ tests pass, 0 failures

- [ ] **Step 2: Verify all modules import**

```bash
.venv/bin/python -c "
import pages.dashboard, pages.facturen, pages.werkdagen, pages.kosten
import pages.bank, pages.instellingen, pages.jaarafsluiting, pages.klanten
import database, fiscal.berekeningen, components.fiscal_utils
print('All modules import successfully')
"
```

- [ ] **Step 3: Manual smoke test**

Run: `python main.py`
Check:
1. Dashboard shows extrapolated tax forecast for current year with confidence badge
2. Dashboard KPIs in responsive grid layout
3. Jaarafsluiting W&V shows km-vergoeding line and prior-year column for 2025
4. Klanten is below separator in sidebar
5. All existing functionality still works

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: verify all tests pass after dashboard UX overhaul"
```
