# Dashboard Redesign v2 — Command Center + Real VA Tracking

**Date**: 2026-03-20
**Status**: Approved
**Approach**: Hybrid Command Center + Smart Sections

## Problem

The current dashboard has seven concrete issues:

1. **Zero visual hierarchy** — all 8 KPI cards are identical in size/weight. Bruto omzet has the same visual presence as "Documenten 2/13 compleet."
2. **Belasting prognose card is overloaded** — embeds progress bars, sub-values, confidence badge, AND a VA entry dialog with PDF upload inside a single KPI card.
3. **Fake VA data** — "VA betaald" is `annual_va × month ÷ 12`, a mathematical estimate. The actual bank payments to Belastingdienst are never consulted. For 2026 Q1: proration says €8,369 paid, reality is €4,608.
4. **Dead data pollutes the view** — "Bedrijfslasten € 0,00 ↓-100%" and "Kostenverdeling — Geen uitgaven gevonden" for years with no expenses yet.
5. **No visual storytelling** — flat 4×2 grid → floating buttons → charts. No narrative flow.
6. **Wasted space on zero-value KPIs** — "Openstaand: 0" takes full card width when there's nothing outstanding.
7. **No trend context** — numbers exist in isolation, no sparklines or micro-trends.

Additionally, the Rabobank CSV parser drops the `Betalingskenmerk` column, which is the key to distinguishing IB from ZVW payments to the Belastingdienst.

## Design

### Layout Structure

```
┌──────────────────────────────────────────────────────────────┐
│  Overzicht                    [+ Werkdag] [+ Factuur] [2026] │
├──────────────────────────────────────────────────────────────┤
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐ │
│  │ Bruto omzet  │ │ Bedrijfswinst│ │ Belasting prognose   │ │
│  │ € 28.702     │ │ € 26.401     │ │ Bij: € 8.177         │ │
│  │ ↑ 11%        │ │ ↑ 8%         │ │ IB: 1/11 · ZVW: 1/11 │ │
│  │ ~~~sparkline │ │ ~~~sparkline │ │ ▓▓░░░░░ progress     │ │
│  └──────────────┘ └──────────────┘ └──────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│  [⏱ 282/1.225 uur ▓▓░░ 23%] [🚗 1.988 km €457] [📁 2/13 ▓░]│
├──────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────┐ ┌──────────────────────┐   │
│  │ Omzet per maand (60%)      │ │ Kostenverdeling (40%)│   │
│  │ ▌▌▌▌▌   (2026 vs 2025)    │ │     ◉ donut          │   │
│  └─────────────────────────────┘ └──────────────────────┘   │
├──────────────────────────────────────────────────────────────┤
│  AANDACHTSPUNTEN (only when relevant)                        │
│  ⚠ 12 werkdagen ongefactureerd  € 4.280         [Bekijk]   │
│  ⚠ 3 facturen openstaand  € 6.120 · oudste 28d  [Bekijk]   │
└──────────────────────────────────────────────────────────────┘
```

### Section 1: Header Row

- `page_title('Overzicht')` left-aligned
- Quick actions: two subtle buttons ("+ Werkdag", "+ Factuur") — white background, border, teal "add" icon. Integrated in header row, no longer floating between sections.
- Year selector: right-aligned, same styling as current

### Section 2: Hero KPI Cards (3 cards, equal width)

Three large cards in a `grid-template-columns: repeat(3, 1fr)` grid with 20px gap.

**Card anatomy** (all three follow this pattern):
- **Label**: 13px, `#64748B`, font-weight 500 (no uppercase, no icons — icons are only used in the secondary strip)
- **Value**: 30px, `#0F172A`, font-weight 700, `tabular-nums`, **rounded to whole euros** via `format_euro(value, decimals=0)` (€ 28.702, not € 28.702,52). Add `decimals=2` default parameter to `format_euro()` in `components/utils.py`.
- **YoY delta**: pill badge top-right (↑ 11%, green bg) — only shown when previous year data exists
- **Context line**: 12px, `#94A3B8` — "vs € 25.848 vorig jaar"
- **Sparkline** (Omzet + Winst only): 36px-high SVG area chart, 12-month data, gradient fill fading to transparent. Teal for omzet, green for winst. No axes, no labels.
- Cards are `border-radius: 14px`, `border: 1px solid #E2E8F0`, white background
- Clickable cards (Omzet → /werkdagen, Belasting → /aangifte) get `cursor: pointer`

**Card 1: Bruto omzet**
- Value: `format_euro(omzet)` rounded
- Sparkline: 12-month revenue data (current year), teal stroke + gradient fill
- Click: navigates to /werkdagen

**Card 2: Bedrijfswinst**
- Value: `format_euro(ytd_winst)` rounded
- Color: green if ≥ 0, red if < 0
- Sparkline: 12-month revenue data (same as omzet, since monthly expense breakdowns don't exist), green stroke + gradient fill. Revenue trend is a reasonable proxy for profit trend in a low-expense solo practice.

**Card 3: Belasting prognose**
- Value: "Bij: € X" (red) or "Terug: € X" (green) — based on `ib_data['resultaat']`
- Confidence badge: top-right pill — "Schatting" (warning), "Prognose" (blue), "Betrouwbaar" (green)
- Context line: "o.b.v. N maanden"
- Sub-detail: single progress bar showing berekend vs VA betaald
  - Text above bar: "Berekend € X" (left) · "VA betaald € Y" (right)
  - Bar: 5px height, `#F1F5F9` background, red gradient fill proportional to berekend/total
  - Below bar: "N van 11 termijnen (IB) · M van 11 termijnen (ZVW)" — real counts from bank data
- Click: navigates to /aangifte
- **No embedded VA dialog** — VA entry moves to Aangifte page (where it belongs)
- When no VA data exists: shows computed tax total (IB + ZVW) with label "Geschatte belasting" and a subtle link "VA invoeren →" pointing to /aangifte

**Removed: Bedrijfslasten card** — redundant (Winst = Omzet − Lasten). Expense totals visible in the cost donut chart below.

### Section 3: Secondary Metrics Strip

Three compact horizontal items in a `display: flex; gap: 12px` row. Each item is roughly half the height of a hero card.

**Item anatomy:**
- Material Icon (20px, semantic color) — `schedule`, `directions_car`, `folder_open`
- Value: 14px, font-weight 600
- Progress bar (where applicable): 3px height, subtle background

**Urencriterium**: icon + "282 / 1.225 uur" + percentage label + progress bar (amber if < 100%, green if met)
**Km-vergoeding**: icon + "1.988 km" + "€ 457" in muted text. Only shown when km > 0.
**Documenten**: icon + "2 / 13 documenten" + percentage + progress bar (amber if incomplete, green if complete)

### Section 4: Charts

Two charts in `grid-template-columns: 3fr 2fr` (60/40 split, 20px gap).

**Omzet per maand** (left, wider):
- Title: "Omzet per maand" (15px, weight 600)
- Subtitle: "2026 vs 2025" (12px, `#94A3B8`) — right-aligned
- Grouped bar chart via `ui.echart`: current year in teal (`#0F766E`), previous year in light gray (`#CBD5E1`)
- Legend: two small color squares with year labels, centered below chart
- Same ECharts config as current, with updated colors

**Kostenverdeling** (right, narrower):
- Title: "Kostenverdeling" (15px, weight 600)
- Donut chart via `ui.echart`: **monochromatic teal palette** (`#0F766E`, `#14B8A6`, `#5EEAD4`, `#99F6E4`) instead of category-specific colors
- Legend below donut: category name + euro amount, vertically stacked, `tabular-nums` for amounts
- **Empty state**: when no expenses exist, show centered text "Nog geen kosten dit jaar" in muted style. Do NOT show an empty donut or "Geen uitgaven gevonden."

### Section 5: Aandachtspunten (Contextual Alerts)

**This entire section only renders when there are items requiring attention.** When everything is fine, nothing appears — no empty container, no "alles in orde" message.

Section header: "AANDACHTSPUNTEN" — 13px, weight 600, `#64748B`, uppercase, letter-spacing 0.05em

Alert types (each is a horizontal bar):

**Ongefactureerde werkdagen** (only when count > 0):
- Background: `#FFFBEB`, border: `#FDE68A`
- Icon: `pending_actions` (20px, `#D97706`)
- Text: "N werkdagen ongefactureerd" (weight 600, `#92400E`) + "€ X" (weight 400, `#A16207`)
- Action: "Bekijk" button → /werkdagen

**Openstaande facturen** (only when count > 0):
- Background: `#FFF7ED`, border: `#FED7AA`
- Icon: `receipt_long` (20px, `#EA580C`)
- Text: "N facturen openstaand" (weight 600, `#9A3412`) + "€ X · oudste N dagen" (weight 400, `#C2410C`)
- Action: "Bekijk" button → /facturen

**No more detail table** for openstaande facturen on the dashboard. The count + total + age is sufficient context; the detail table belongs on the Facturen page.

### Empty States

When a year has minimal or no data:
- Hero cards show € 0 with no sparkline and no YoY delta badge
- Secondary strip items with no data are hidden (e.g., km=0 → no km item)
- Charts: revenue chart shows prior year bars only, cost donut shows empty state text
- Aandachtspunten section is hidden

## Feature: Real VA Bank Matching

### Problem

The current `_compute_ib_estimate()` calculates "VA betaald" as `annual_va × month ÷ 12`. This is fiction — actual payments to the Belastingdienst are in the bank transactions but never consulted.

The Rabobank CSV contains a `Betalingskenmerk` column that perfectly distinguishes IB from ZVW:

| Year | IB Kenmerk | ZVW Kenmerk |
|------|-----------|-------------|
| 2026 | `0124412647060001` | `0124412647560014` |
| 2025 | `1124412647050001` | `1124412647550014` |
| 2024 | `9124412647040001` | `9124412647540014` |

All payments go to IBAN `NL86INGB0002445588` (Belastingdienst). The betalingskenmerk is the only way to distinguish IB from ZVW payments in bank data.

### Data Layer Changes

**1. Schema: add `betalingskenmerk` column**

```sql
ALTER TABLE banktransacties ADD COLUMN betalingskenmerk TEXT DEFAULT '';
```

**2. Enhance `parse_rabobank_csv()`**

Capture the "Betalingskenmerk" column from the CSV and include it in the returned dict. The column name in the CSV is exactly `Betalingskenmerk`.

**3. Backfill existing transactions**

One-time migration function `backfill_betalingskenmerken()` that runs on app startup when the column exists but is empty. It re-reads archived CSVs from `data/bank_csv/`, parses them with the enhanced parser, and updates existing rows matched by `(datum, bedrag, tegenpartij, omschrijving)` — the same dedup key used in `add_banktransacties()`. This runs once and is a no-op on subsequent starts.

**4. New DB function: `get_va_betalingen(db_path, jaar)`**

```python
async def get_va_betalingen(db_path, jaar):
    """Get actual VA payments from bank transactions for a given year.

    Matches by:
    1. tegenrekening = 'NL86INGB0002445588' (Belastingdienst IBAN)
    2. datum within the year
    3. betalingskenmerk to distinguish IB vs ZVW

    Returns dict with:
    - ib_betaald: total IB payments (positive number)
    - ib_termijnen: count of IB payments
    - zvw_betaald: total ZVW payments (positive number)
    - zvw_termijnen: count of ZVW payments
    - totaal_betaald: ib + zvw
    - has_bank_data: True if any Belastingdienst payments found
    """
```

The function identifies IB vs ZVW by matching the `betalingskenmerk` against known patterns. If no betalingskenmerk is available (old imports), falls back to summing all Belastingdienst payments as combined total.

**5. Store VA beschikking kenmerken**

When the user enters VA data (on the Aangifte page, post-move), optionally store the betalingskenmerk from the beschikking. This enables exact matching. The kenmerken from the 2026 beschikkingen:
- IB: `0124 4126 4706 0000`
- ZVW: `0124 4126 4756 0014`

For now, matching by IBAN + year + betalingskenmerk pattern is sufficient without requiring user input of the kenmerk.

### Dashboard Integration

In `_compute_ib_estimate()`:

1. Call `get_va_betalingen(DB_PATH, jaar)` alongside existing queries
2. If `has_bank_data` is True: use real `ib_betaald` and `zvw_betaald`
3. If `has_bank_data` is False: fall back to proration with "geschat" label
4. Pass termijn counts to the card for display

The Belasting prognose card shows:
- When bank data available: "VA betaald € 4.608" + "N van 11 termijnen (IB) · M van 11 termijnen (ZVW)" (real per-type counts)
- When bank data available but kenmerken missing: "VA betaald € 4.608" + "N betalingen" (combined count)
- When no bank data: "VA geschat € 8.369" + "(prognose)" label

## Sparkline Implementation

Sparklines are implemented via `ui.echart` with a minimal configuration:

```python
ui.echart({
    'grid': {'top': 0, 'bottom': 0, 'left': 0, 'right': 0},
    'xAxis': {'show': False, 'type': 'category', 'data': months},
    'yAxis': {'show': False, 'type': 'value'},
    'series': [{
        'type': 'line',
        'data': monthly_values,
        'smooth': True,
        'symbol': 'none',
        'lineStyle': {'width': 2, 'color': color},
        'areaStyle': {
            'color': {'type': 'linear', 'x': 0, 'y': 0, 'x2': 0, 'y2': 1,
                       'colorStops': [
                           {'offset': 0, 'color': f'{color}20'},
                           {'offset': 1, 'color': f'{color}00'},
                       ]}
        },
    }],
    'tooltip': {'show': False},
}).style('height: 36px; width: 100%;')
```

Data source: `get_omzet_per_maand(jaar)` already returns 12-element monthly arrays, which is exactly what sparklines need.

## Data Requirements

New DB queries needed:
- `get_va_betalingen(db_path, jaar)` — sum Belastingdienst bank payments by kenmerk
- Existing `get_omzet_per_maand()` — already returns monthly data for sparklines

Modified:
- `parse_rabobank_csv()` — add betalingskenmerk capture
- `add_banktransacties()` — include betalingskenmerk in INSERT
- `_compute_ib_estimate()` — use real VA payments when available
- `refresh_dashboard()` — restructured to render new layout
- `format_euro()` in `components/utils.py` — add `decimals=2` parameter (default preserves existing behavior)
- `cost_donut_chart()` in `components/charts.py` — monochromatic teal palette instead of multi-hue

Removed from dashboard:
- `open_va_dialog()` — moves to Aangifte page
- Openstaande facturen detail table — replaced by alert bar
- Bedrijfslasten KPI card

## Visual Design Tokens

All values from the existing design system (no new colors):

| Token | Value | Usage |
|-------|-------|-------|
| Hero card value | 30px / 700 / `#0F172A` | Primary KPI numbers |
| Card label | 13px / 500 / `#64748B` | KPI labels |
| YoY badge positive | 12px / 600 / `#059669` on `#ECFDF5` | Growth indicator |
| YoY badge negative | 12px / 600 / `#DC2626` on `#FEF2F2` | Decline indicator |
| Confidence badge | 11px / 500 / blue on `#F0F9FF` | Prognose reliability |
| Context text | 12px / 400 / `#94A3B8` | Sub-labels, "vs vorig jaar" |
| Section label | 13px / 600 / `#64748B` / uppercase | "AANDACHTSPUNTEN" |
| Alert background | `#FFFBEB` / `#FFF7ED` | Amber/orange alert bars |
| Sparkline teal | `#0F766E` stroke, 12% fill | Omzet sparkline |
| Sparkline green | `#059669` stroke, 12% fill | Winst sparkline |
| Donut palette | `#0F766E`, `#14B8A6`, `#5EEAD4`, `#99F6E4` | Monochromatic teal |
| Card border-radius | 14px | Hero cards |
| Secondary border-radius | 10px | Strip items, alert bars |
| Card border | 1px solid `#E2E8F0` | All cards |
| Progress bar height | 5px (hero), 3px (secondary) | Belasting bar, uren/docs |

## Relationship to Prior Specs

This spec **supersedes** `2026-03-13-va-beschikkingen-design.md` for the VA bank matching approach. That spec proposed using `koppeling_type='va_ib'` on banktransacties; this spec uses a dedicated `betalingskenmerk` column instead, which is simpler and matches the actual Rabobank CSV structure.

The VA dialog move to the Aangifte page is specified at a high level here (it moves, period). The exact placement on the Aangifte page (which tab, which section) is deferred to the implementation plan.

## Scope Exclusions

- No changes to sidebar navigation
- No changes to other pages (except moving VA dialog to Aangifte)
- No PDF parsing/OCR of VA beschikkingen (amounts still manually entered)
- No changes to the fiscal calculation engine (`bereken_volledig`)
- No new pages or routes
