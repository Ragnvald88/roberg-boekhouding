# App Redesign — Design Spec

**Goal:** Transform the app from a passive CRUD interface into an intelligent command center with professional-grade tables and visual consistency. The app should tell you what needs attention, show your financial pipeline at a glance, and make every table interaction efficient.

**Approach:** Three phases, each deliverable independently. Phase 1 (dashboard) is the highest-impact change. Phase 2 (tables) applies across all pages. Phase 3 (visual polish) is the finishing layer.

**Tech Stack:** NiceGUI 3.x / Quasar / Python 3.12+

**Validated mockups:** `.superpowers/brainstorm/68440-*/dashboard-mockup.html` and `table-mockup.html`

---

## Phase 1: Dashboard Command Center

Replace the current 8-KPI-card + charts dashboard with an intelligent home screen.

### 1.1 Aandachtspunten Strip

A row of clickable action cards at the top of the dashboard. Each card has:
- Left border color (warning/danger/info via Quasar CSS vars)
- Count number (bold, large)
- Description text
- Click navigates to the relevant page

**Data sources:**
- "X werkdagen te factureren" — `get_werkdagen_ongefactureerd_summary()` (existing)
- "X facturen > 14 dagen onbetaald" — `get_openstaande_facturen()` (existing), filter in Python by `(today - datum).days > 14`
- "X transacties te categoriseren" — NEW query: `get_uncategorized_count(db_path, jaar)` returning `SELECT COUNT(*) FROM banktransacties WHERE substr(datum,1,4)=? AND (categorie IS NULL OR categorie='') AND koppeling_type IS NULL`

Only show cards with count > 0. If everything is clean, show a single green "Alles bijgewerkt" card.

### 1.2 Geldstroom Pipeline

A horizontal 4-stage bar showing the money flow:
1. **Te factureren** — sum of ongefactureerde werkdagen (uren × tarief + km × km_tarief) | count. Data from `get_werkdagen_ongefactureerd_summary()` (existing — already returns `aantal` and `bedrag`)
2. **Openstaand** — sum + count of onbetaalde facturen. Data from `get_openstaande_facturen()` (existing)
3. **Betaald deze maand** — NEW query: `get_facturen_betaald_maand(db_path, jaar, maand)` returning facturen where `betaald=1 AND substr(betaald_datum,1,7) = 'YYYY-MM'`
4. **YTD omzet** — from `get_kpis()` (existing — returns `omzet` and factuur count via separate query)

**Implementation:** Render as a flex row of 4 `ui.column` blocks inside a `ui.card`, separated by arrow labels. "Betaald deze maand" gets a subtle `bg-teal-1` background.

### 1.3 Compact KPI Row

Replace 8 KPI cards with 4 compact KPIs in a `grid-template-columns: repeat(4, 1fr)` CSS grid:
1. **Bedrijfswinst** — YTD amount + YoY delta %
2. **Belasting prognose** — headline bij/terug amount + one-line sub (VA betaald / berekend). Click navigates to /aangifte
3. **Urencriterium** — current/target + thin progress bar
4. **Bedrijfslasten** — YTD amount + YoY delta %

Remove from dashboard: Openstaand (now in pipeline), Km-vergoeding (niche), Documenten (year-end only).

### 1.4 Quick Actions

Three outline buttons between KPI row and charts: "Werkdag toevoegen" (navigates /werkdagen), "Nieuwe factuur" (navigates /facturen), "Bank importeren" (navigates /bank).

### 1.5 Data Freshness

Show "Laatste bank import: DD-MM-YYYY" in the header area. Query: `SELECT MAX(substr(csv_bestand,1,8)) FROM banktransacties WHERE csv_bestand != ''` — the csv_bestand field stores filenames prefixed with `YYYYMMDD_HHMMSS_`. Parse the date from this prefix.

### 1.6 Charts

Keep revenue bar chart and cost donut unchanged. They render below quick actions.

### 1.7 Remove from Dashboard

- VA invoeren dialog (VA amounts are on /aangifte Prive tab with auto-save; VA PDFs are on /documenten)
- Openstaande facturen detail table (replaced by pipeline + aandachtspunten)
- Ongefactureerde werkdagen alert card (replaced by aandachtspunten)
- Documenten KPI card (year-end concern, not daily)
- Km-vergoeding KPI card (niche, available on /werkdagen)

---

## Phase 2: Table System Overhaul

Apply improvements to all data tables: facturen, werkdagen, kosten, bank. All tables use a full `body` slot (like the bank page already does) to enable left-border colors, inline actions, and status chips.

### 2.1 Filter Chips

Create `components/filter_chips.py` — a reusable filter chip row using `ui.button` styled as pills.

Each chip is a `ui.button` with `props('outline rounded-xl dense no-caps size=sm')` and a count badge. Active chip gets filled style. Clicking triggers a server-side re-query (same pattern as current year/month filter changes).

**Per page:**
- **Facturen:** Alle | Openstaand | Overdue (>14d) | Betaald
- **Werkdagen:** Alle | Ongefactureerd | Gefactureerd | Betaald
- **Kosten:** Alle | Investeringen
- **Bank:** Alle | Niet gekoppeld | Gecategoriseerd | Gekoppeld

Year and klant dropdowns remain as secondary filters after a visual separator.

### 2.2 Visual Status Indicators

Left-border color on table rows (3px solid) using Quasar CSS variables:

**Facturen:**
- `var(--q-positive)` = betaald
- `var(--q-warning)` = openstaand (≤14d since datum)
- `var(--q-negative)` = overdue (>14d since datum, still unpaid)

**Werkdagen:**
- `#94A3B8` (grey) = ongefactureerd
- `var(--q-primary)` = gefactureerd
- `var(--q-positive)` = betaald

**Bank:** Keep existing row background colors (teal-1/amber-1/red-1).

**Implementation:** Full `body` slot with conditional `:style` on `<q-tr>`.

### 2.3 Inline Actions

**Facturen:**
- Unpaid rows: "✓ Betaald" outline button (positive color) directly in the row
- Paid rows: "↩ Onbetaald" outline button (grey) directly in the row
- PDF download icon button always visible
- Three-dot menu for: edit, delete (less frequent actions)

**Werkdagen / Kosten / Bank:** Keep current inline patterns (already have edit/delete icons or inline dropdowns).

### 2.4 Row Detail Panel

When a row is clicked, show a detail card below the table (not inside the table slot — avoids full-body-slot complexity for werkdagen/kosten).

**Facturen:** Click a row → detail panel shows linked werkdagen as a mini-table (datum, locatie, uren, tarief, bedrag). NEW query needed: `get_werkdagen_by_factuurnummer(db_path, factuurnummer)` — `SELECT * FROM werkdagen WHERE factuurnummer = ?`.

**Werkdagen:** Click a row → if `factuurnummer` is set, detail panel shows the factuur info (nummer, klant, datum, bedrag, betaald status).

The detail panel is a `ui.card` that sits below the table. It clears and re-renders when a different row is clicked. Click again to dismiss.

### 2.5 Smart Column Formatting

Apply consistently to all tables:
- Money columns: right-aligned, `font-variant-numeric: tabular-nums`, formatted via `format_euro()`
- Date columns: Dutch format DD-MM-YYYY (already done for werkdagen, verify all tables)
- Status: colored `q-badge` chips (betaald=positive, openstaand=warning, overdue=negative, ongefactureerd=grey)
- Totals: bold footer row with column sums

### 2.6 Bulk Actions

**Werkdagen:** Select multiple → "Factureer selectie" button. Navigates to /facturen with pre-selected IDs (existing flow, keep as-is — the factuur creation logic is complex and lives in facturen.py).

**Facturen:** Select multiple unpaid → "Markeer betaald" button appears. Uses today's date as `betaald_datum`. Confirmation dialog before applying.

---

## Phase 3: Visual Consistency

### 3.1 Semantic Colors

Replace hardcoded hex with Quasar semantic equivalents in page files:
- `#0F766E` → `var(--q-primary)` or `color=primary` / `text-primary`
- `#059669` → `var(--q-positive)` or `color=positive`
- `#DC2626` → `var(--q-negative)` or `color=negative`
- `#D97706` → `var(--q-warning)` or `color=warning`
- `#64748B` → `text-grey-7`

Keep hex only for layout chrome (sidebar, header — dark background values without Quasar equivalents).

**Scope:** Only change hex values in `pages/` and `components/kpi_card.py`. Do not touch `components/layout.py` CSS block (those are intentional dark-theme values) or `components/charts.py` (ECharts needs hex).

### 3.2 Spacing Fixes

Fix only the remaining inconsistencies not already fixed in the hardening branch:
- `aangifte.py`: `my-1` separators → `q-my-sm`
- Any remaining `w-96` dialog cards → `max-w-lg`
- Any remaining inline `max-width` → Quasar classes

### 3.3 Empty States

Replace "Geen X gevonden" with actionable empty states on key pages:
- **Werkdagen:** "Nog geen werkdagen voor {jaar}. Registreer je eerste werkdag." + button
- **Facturen:** "Nog geen facturen voor {jaar}." + button
- **Kosten:** "Nog geen uitgaven voor {jaar}." + button
- **Bank:** "Nog geen transacties. Importeer een Rabobank CSV." + upload prompt
- **Dashboard:** If no data for year, show guidance instead of zero-value KPIs

### 3.4 ~~Loading States~~ — DROPPED (YAGNI)

Local SQLite loads in milliseconds. Skeleton screens add complexity for no visible benefit.

---

## New DB Queries Required

1. `get_uncategorized_count(db_path, jaar)` → int — count of bank transactions without category or link
2. `get_facturen_betaald_maand(db_path, jaar, maand)` → list[Factuur] — facturen paid in a specific month
3. `get_werkdagen_by_factuurnummer(db_path, factuurnummer)` → list[Werkdag] — werkdagen linked to a factuur

---

## Out of Scope

- Sidebar notification badges
- Onboarding wizard / first-run detection
- Year-end guided workflow / stepper
- Klanten page persistent table refactor
- Aangifte.py splitting into sub-modules
- Mobile responsiveness (desktop-only app)
- OCR / document scanning
