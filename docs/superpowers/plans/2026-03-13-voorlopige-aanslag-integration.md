# Voorlopige Aanslag Integration — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add prorated VA comparison on the dashboard for real-time tax forecasting, and redesign the aangifte Resultaat card for a clear structured breakdown.

**Architecture:** Two independent UI improvements sharing the existing fiscal engine. The dashboard prorates VA by current month for the active year (`annual_va * month / 12`), giving a live "ahead or behind" view. The aangifte Overzicht shows the full-year structured breakdown for tax filing. No DB schema changes, no fiscal engine changes — only the dashboard passes prorated VA values to `bereken_volledig()`.

**Tech Stack:** NiceGUI (Quasar/Vue), Python, existing `bereken_volledig()` engine

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `tests/test_fiscal.py` | Add 2 tests (~line 1024) | VA proration scenarios |
| `pages/dashboard.py` | Modify (lines 68-86, 166-185) | VA proration + enhanced KPI |
| `pages/aangifte.py` | Modify (lines 785-826) | Resultaat card redesign |

---

### Task 1: VA Proration Tests

**Files:**
- Test: `tests/test_fiscal.py` — add to `TestIBPVVSplit` class, after `test_backward_compat_no_va_zvw` (~line 1024)

- [ ] **Step 1: Write test for prorated VA (half year)**

Add after the `test_backward_compat_no_va_zvw` method:

```python
def test_prorated_va_half_year(self):
    """Prorated VA (6/12) gives higher result than full-year VA."""
    params = FISCALE_PARAMS[2024]
    annual_va_ib = 30303
    annual_va_zvw = 2667
    month = 6
    va_ib_prorated = annual_va_ib * month / 12   # 15151.50
    va_zvw_prorated = annual_va_zvw * month / 12  # 1333.50

    f = bereken_volledig(
        omzet=95145, kosten=0, afschrijvingen=0,
        representatie=550, investeringen_totaal=2919,
        uren=1400, params=params, aov=2998,
        woz=655000, hypotheekrente=6951,
        voorlopige_aanslag=va_ib_prorated,
        voorlopige_aanslag_zvw=va_zvw_prorated,
        ew_naar_partner=True,
    )
    # netto_ib unchanged by VA value (~27166)
    assert abs(f.netto_ib - 27166) < 10
    # resultaat_ib = netto_ib - prorated VA (higher than full-year)
    assert abs(f.resultaat_ib - (f.netto_ib - va_ib_prorated)) < 1
    assert abs(f.resultaat_zvw - (f.zvw - va_zvw_prorated)) < 1
    # Less VA subtracted → result higher than full-year (-1994)
    assert f.resultaat > -1994

def test_prorated_va_january(self):
    """In January, only 1/12 of VA is paid — large positive result."""
    params = FISCALE_PARAMS[2024]
    va_ib = 30303 * 1 / 12   # 2525.25
    va_zvw = 2667 * 1 / 12   # 222.25

    f = bereken_volledig(
        omzet=95145, kosten=0, afschrijvingen=0,
        representatie=550, investeringen_totaal=2919,
        uren=1400, params=params, aov=2998,
        woz=655000, hypotheekrente=6951,
        voorlopige_aanslag=va_ib,
        voorlopige_aanslag_zvw=va_zvw,
        ew_naar_partner=True,
    )
    # Almost no VA paid → large positive result
    assert f.resultaat_ib > 20000
    assert f.resultaat_zvw > 3000
```

- [ ] **Step 2: Run tests to verify they pass**

These pass immediately since `bereken_volledig()` already handles any VA value correctly.

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_fiscal.py::TestIBPVVSplit::test_prorated_va_half_year tests/test_fiscal.py::TestIBPVVSplit::test_prorated_va_january -v
```

Expected: 2 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_fiscal.py
git commit -m "test: add VA proration scenario tests for dashboard forecast"
```

---

### Task 2: Dashboard — Prorated VA + Enhanced Belasting Prognose KPI

**Files:**
- Modify: `pages/dashboard.py` (lines 68-86 and 166-185)

**Context:** Currently `_compute_ib_estimate(jaar)` returns a single float (`f.resultaat`) using full annual VA. The "Geschatte IB" KPI shows just a number. We need to:
1. Prorate VA for current year: `annual_va * month / 12`
2. Return a dict with breakdown data
3. Render an enhanced KPI with VA context in `extra` callback

- [ ] **Step 1: Modify `_compute_ib_estimate` to prorate VA and return dict**

Replace the function at lines 68-86 with:

```python
    async def _compute_ib_estimate(jaar):
        """Compute IB estimate. Prorates VA for current year by month."""
        data = await fetch_fiscal_data(DB_PATH, jaar)
        if data is None:
            return None

        annual_va_ib = data['voorlopige_aanslag']
        annual_va_zvw = data['voorlopige_aanslag_zvw']

        # Prorate VA for current year based on current month
        huidig_jaar = date.today().year
        if jaar == huidig_jaar:
            month = date.today().month
            va_ib = round(annual_va_ib * month / 12, 2)
            va_zvw = round(annual_va_zvw * month / 12, 2)
        else:
            month = 12
            va_ib = annual_va_ib
            va_zvw = annual_va_zvw

        f = bereken_volledig(
            omzet=data['omzet'], kosten=data['kosten_excl_inv'],
            afschrijvingen=data['totaal_afschrijvingen'],
            representatie=data['representatie'],
            investeringen_totaal=data['inv_totaal_dit_jaar'],
            uren=data['uren'], params=data['params_dict'],
            aov=data['aov'], lijfrente=data.get('lijfrente', 0),
            woz=data['woz'],
            hypotheekrente=data['hypotheekrente'],
            voorlopige_aanslag=va_ib,
            voorlopige_aanslag_zvw=va_zvw,
            ew_naar_partner=data['ew_naar_partner'],
        )
        return {
            'resultaat': f.resultaat,
            'netto_ib': f.netto_ib,
            'zvw': f.zvw,
            'va_ib_betaald': va_ib,
            'va_zvw_betaald': va_zvw,
            'prorated': jaar == huidig_jaar,
            'month': month,
        }
```

- [ ] **Step 2: Update KPI rendering (lines 166-185)**

Replace the "Row 3: IB + Km" block with:

```python
            # Row 3: Belasting prognose + Km
            with ui.row().classes('w-full gap-4 flex-wrap'):
                if ib_resultaat is not None:
                    ib_data = ib_resultaat  # dict from _compute_ib_estimate
                    res = ib_data['resultaat']
                    if res < 0:
                        ib_label = f'Terug: {format_euro(abs(res))}'
                        ib_color = '#059669'
                    elif res > 0:
                        ib_label = f'Bij: {format_euro(res)}'
                        ib_color = '#DC2626'
                    else:
                        ib_label = format_euro(0)
                        ib_color = '#0F766E'

                    va_totaal = ib_data['va_ib_betaald'] + ib_data['va_zvw_betaald']

                    def ib_extra(d=ib_data, vt=va_totaal):
                        _MND = {1: 'jan', 2: 'feb', 3: 'mrt', 4: 'apr',
                                5: 'mei', 6: 'jun', 7: 'jul', 8: 'aug',
                                9: 'sep', 10: 'okt', 11: 'nov', 12: 'dec'}
                        with ui.column().classes('gap-0 q-mt-xs'):
                            belasting = d['netto_ib'] + d['zvw']
                            ui.label(
                                f'Berekend: {format_euro(belasting)}'
                            ).classes('text-caption text-grey-6')
                            if vt > 0:
                                if d['prorated']:
                                    ui.label(
                                        f'VA t/m {_MND[d["month"]]}: '
                                        f'-{format_euro(vt)}'
                                    ).classes('text-caption text-grey-6')
                                else:
                                    ui.label(
                                        f'VA betaald: -{format_euro(vt)}'
                                    ).classes('text-caption text-grey-6')

                    kpi_card('Belasting prognose', ib_label,
                             'calculate', ib_color,
                             extra=ib_extra,
                             on_click=lambda: ui.navigate.to('/aangifte'))

                if km_data['km'] > 0:
                    km_label = (f"{km_data['km']:.0f} km "
                                f"({format_euro(km_data['vergoeding'])})")
                    kpi_card('Km-vergoeding', km_label,
                             'directions_car', '#0F766E')
```

- [ ] **Step 3: Verify app starts and dashboard renders**

```bash
cd /path/to/project && source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py
```

Manual check:
- Current year → "Belasting prognose" with prorated result + "VA t/m [maand]: -€X"
- Past year (e.g. 2024) → full result + "VA betaald: -€X"
- Year without VA data → shows result without VA sub-lines

- [ ] **Step 4: Run full test suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

Expected: All 412+ tests pass

- [ ] **Step 5: Commit**

```bash
git add pages/dashboard.py
git commit -m "feat: prorate VA on dashboard for real-time tax forecast"
```

---

### Task 3: Aangifte — Redesign Resultaat Card

**Files:**
- Modify: `pages/aangifte.py` (lines 785-826 — the Resultaat card in `render_overzicht()`)

**Context:** The current Resultaat card shows compressed one-liners like `IB: €X - VA €Y`. The redesign adds a clear structured breakdown with sections: "Berekende belasting", "Reeds betaald", and a prominent "Terug/Bij" bottom line.

- [ ] **Step 1: Replace the Resultaat card**

Replace lines 785-826 (from `# Card 5: Resultaat` to end of the `else` block before `# Tab 5: Documenten`) with:

```python
            # Card 5: Resultaat — structured breakdown
            with ui.card().classes('w-full').style(
                    'border: 2px solid #0d9488; background: #f0fdfa'):
                ui.label('Resultaat').classes('text-subtitle1 text-weight-bold')
                ui.separator().classes('my-1')

                # --- Berekende belasting ---
                ui.label('Berekende belasting').classes(
                    'text-subtitle2 text-grey-8 q-mt-sm')
                _line('Netto IB / PVV', f.netto_ib)
                _line('ZVW-bijdrage', f.zvw)
                if box3.belasting > 0:
                    _line('Box 3', box3.belasting)
                totaal_berekend = f.netto_ib + f.zvw + box3.belasting
                ui.separator().classes('my-1')
                _line('Totaal berekend', totaal_berekend, bold=True)

                # --- Reeds betaald (voorlopige aanslagen) ---
                has_va = f.voorlopige_aanslag > 0 or f.voorlopige_aanslag_zvw > 0
                if has_va:
                    ui.label('Reeds betaald (voorlopige aanslagen)').classes(
                        'text-subtitle2 text-grey-8 q-mt-md')
                    if f.voorlopige_aanslag > 0:
                        _line('VA Inkomstenbelasting',
                              -f.voorlopige_aanslag)
                    if f.voorlopige_aanslag_zvw > 0:
                        _line('VA Zorgverzekeringswet',
                              -f.voorlopige_aanslag_zvw)
                    totaal_betaald = (f.voorlopige_aanslag
                                      + f.voorlopige_aanslag_zvw)
                    ui.separator().classes('my-1')
                    _line('Totaal betaald', -totaal_betaald, bold=True)

                # --- Eindresultaat ---
                ui.separator().classes('my-2').style(
                    'border-top: 2px solid #0d9488')

                totaal = f.resultaat + box3.belasting
                if totaal < 0:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Terug te ontvangen').classes(
                            'text-bold text-h6')
                        with ui.row().classes('items-center gap-2'):
                            ui.label(format_euro(abs(totaal))).classes(
                                'text-bold text-h6 text-positive')
                            ui.button(
                                icon='content_copy',
                                on_click=lambda: _copy_value(
                                    abs(totaal), 'Totaal terug'),
                            ).props('round color=positive size=sm')
                elif totaal > 0:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Bij te betalen').classes(
                            'text-bold text-h6')
                        with ui.row().classes('items-center gap-2'):
                            ui.label(format_euro(totaal)).classes(
                                'text-bold text-h6 text-negative')
                            ui.button(
                                icon='content_copy',
                                on_click=lambda: _copy_value(
                                    totaal, 'Totaal bij'),
                            ).props('round color=negative size=sm')
                else:
                    with ui.row().classes(
                            'w-full justify-between items-center'):
                        ui.label('Resultaat').classes('text-bold text-h6')
                        ui.label(format_euro(0)).classes('text-bold text-h6')
```

**Visual result:**
```
┌─────────────────────────────────────────────────┐
│ Resultaat                                       │
│ ──────────────────────────────────────────────── │
│                                                  │
│ Berekende belasting                              │
│   Netto IB / PVV                    € 27.166,00 │
│   ZVW-bijdrage                      €  3.810,00 │
│ ──────────────────────────────────────────────── │
│   Totaal berekend                   € 30.976,00 │
│                                                  │
│ Reeds betaald (voorlopige aanslagen)             │
│   VA Inkomstenbelasting            € -30.303,00 │
│   VA Zorgverzekeringswet           €  -2.667,00 │
│ ──────────────────────────────────────────────── │
│   Totaal betaald                   € -32.970,00 │
│                                                  │
│ ══════════════════════════════════════════════════│
│ Terug te ontvangen              € 1.994,00  [⎘] │
└─────────────────────────────────────────────────┘
```

- [ ] **Step 2: Verify aangifte Overzicht renders correctly**

Start app, navigate to `/aangifte`, select year with VA data (e.g. 2024 or 2025), go to Overzicht tab.

Check:
- "Berekende belasting" section with IB + ZVW + optional Box 3
- "Reeds betaald" section with VA amounts (only if VA > 0)
- Green "Terug te ontvangen" or red "Bij te betalen" bottom line
- Copy button works on the total

- [ ] **Step 3: Run full test suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add pages/aangifte.py
git commit -m "feat: redesign aangifte Resultaat card with structured VA breakdown"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

Expected: All 412+ tests pass

- [ ] **Manual verification checklist**

1. Dashboard → Current year (2026): "Belasting prognose" KPI shows prorated result + "Berekend: €X" + "VA t/m mrt: -€Y"
2. Dashboard → Past year (2024): Shows full-year result + "VA betaald: -€X"
3. Dashboard → Year without VA (2023 if VA=0): Shows just the IB result, no VA lines
4. Aangifte → Overzicht → 2025: Structured Resultaat card with both sections
5. Aangifte → Overzicht → Year without VA: Only "Berekende belasting" section, no "Reeds betaald"
6. Copy button on Resultaat total works correctly
