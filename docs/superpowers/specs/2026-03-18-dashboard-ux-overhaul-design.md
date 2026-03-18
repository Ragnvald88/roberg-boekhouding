# Dashboard & Reporting UX Overhaul — Design Spec

## Problem

The dashboard tax forecast feeds raw YTD revenue into the fiscal engine as if it were the full-year amount. In March with €25k revenue, the engine computes tax on €25k income — dramatically understating the likely annual tax bill. This makes the "Belasting prognose" KPI misleading for 11 of 12 months. Additionally, if the user hasn't entered current-year personal data (hypotheekrente, WOZ, AOV), the forecast uses zero instead of reasonable estimates. The year report W&V lacks year-over-year comparison and hides km-vergoeding inside an aggregate number.

## Goals

1. Dashboard tax forecast extrapolates annual income from YTD data and shows a confidence indicator
2. Missing personal data falls back to prior-year values with a visible hint
3. Dashboard KPI layout uses responsive CSS grid, removes low-value elements
4. Jaarafsluiting W&V shows km-vergoeding as separate line and includes a year-over-year comparison
5. Navigation improvements: global year selector, move Klanten below separator, VA cross-link

## Non-Goals

- No new DB tables or schema changes (all data already exists)
- No new pages — changes are to existing dashboard.py, jaarafsluiting.py, layout.py, fiscal_utils.py
- No FAB button or keyboard shortcuts
- No bank reconciliation UI
- No dark mode

---

## Design

### 1. Income Extrapolation (`components/fiscal_utils.py`)

New function `extrapoleer_jaaromzet(db_path, jaar)` returns:
- `ytd_omzet`: actual YTD revenue
- `extrapolated_omzet`: projected annual revenue
- `confidence`: 'low' (≤2 months), 'medium' (3-5), 'high' (6+)
- `basis_maanden`: complete months used (current month excluded if before 15th)

**Algorithm:** Linear extrapolation `ytd * (12 / complete_months)`, weighted 70/30 with prior-year monthly pattern when available (captures mild seasonality). Investments and depreciation are NOT extrapolated — they are known quantities.

**Cost extrapolation:** Regular costs (kosten_excl_inv) extrapolated linearly. Investments kept at actual YTD.

### 2. Prior-Year Data Fallback (`components/fiscal_utils.py`)

New function `get_personal_data_with_fallback(params_current, params_prior)` returns each personal field with source annotation ('current', 'prior', 'none'). Fields: woz_waarde, hypotheekrente, aov_premie, partner_bruto_loon, partner_loonheffing, box3 saldi.

Dashboard shows hint when fallbacks are used: "Gebruikt 2025 waarden voor hypotheek, WOZ"

### 3. Enhanced `_compute_ib_estimate` (`pages/dashboard.py`)

For the current year:
1. Call `extrapoleer_jaaromzet` for projected revenue
2. Extrapolate regular costs by same factor
3. Use `get_personal_data_with_fallback` for missing personal data
4. Pass FULL annual VA (not prorated) for the jaarprognose — answers "what will my definitieve aanslag say?"
5. Return enriched dict with confidence, fallbacks, extrapolated values

For past years: unchanged (use actual data).

### 4. Dashboard KPI Layout (`pages/dashboard.py`)

Replace three `ui.row` wrappers with a single CSS grid:
```css
display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px;
```

KPI cards (order):
1. Bruto omzet (with YoY delta)
2. Resultaat (W&V winst from fiscal engine)
3. Belasting prognose (enhanced — see below)
4. Bedrijfslasten (with YoY delta)
5. Urencriterium (with progress bar)
6. Openstaand (with count)
7. Km-vergoeding (if km > 0)

Remove: "Facturen (count)" KPI — low value, user goes to facturen page.
Remove: "Recente facturen" section — no actionable value, user goes to facturen page.

### 5. Enhanced Belasting Prognose Card (`pages/dashboard.py`)

The KPI extra section shows:
- Two progress bars: "Berekend" (red) vs "VA betaald" (green) — visual ratio
- Confidence badge: "Schatting (weinig data)" / "Prognose" / "Prognose (betrouwbaar)"
- Fallback hint: "Gebruikt 2025 waarden voor hypotheek, WOZ" (grey italic)
- Link: "VA aanpassen →" navigating to `/aangifte`

### 6. W&V Year-over-Year Comparison (`pages/jaarafsluiting.py`)

Extend `render_wv` to accept optional `vorig_jaar_data` dict and `vorig_winst` float. When present, render a second column with % delta:

```
                                    2025         2024       Δ%
Netto-omzet                    € 126.251    € 123.176    +2.5%
Km-vergoeding                  €   6.432    €   5.890    +9.2%
Overige bedrijfskosten         €  22.429    €  22.342    +0.4%
Afschrijvingen                 €   2.100    €     532   +294.7%
Winst                          €  95.290    €  94.412    +0.9%
```

Km-vergoeding shown as a separate line (data already available in `fetch_fiscal_data` return dict).

### 7. Navigation Improvements (`components/layout.py`, `pages/*.py`)

**Move Klanten below separator:** It's a setup page visited ~5x/year, not a daily page.

**Global year selector:** Store in `app.storage.user['geselecteerd_jaar']`. Each page reads from it on load and writes to it on change. Show year in header: "Boekhouding — 2026".

---

## Testing Strategy

- Unit tests for `extrapoleer_jaaromzet` with mock monthly revenue data
- Unit tests for `get_personal_data_with_fallback` with various missing-data scenarios
- Existing fiscal tests remain unchanged (engine not modified)
- Manual verification of dashboard layout and W&V comparison rendering
