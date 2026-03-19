# UI Polish & Dashboard Improvements — Design Spec

**Goal:** Fix UI bugs, standardize inconsistencies, and improve the dashboard — in a single cohesive update that makes the app feel correct, consistent, and modern.

**Scope:** Bug fixes, consistency cleanup, and targeted dashboard improvements. Defers structural refactors (persistent klanten table, aangifte splitting, VA dialog extraction) and new features (sidebar badges, onboarding, year-end checklist) to a future spec.

**Tech Stack:** NiceGUI/Quasar, Python 3.12+

---

## Phase 1: Bug Fixes

### 1.1 Werkdagen table shows ISO dates

**Problem:** `werkdagen.py:153` uses `'field': 'datum'` (ISO: 2025-12-04) while facturen and bank tables use `'field': 'datum_fmt'` (Dutch: 04-12-2025).

**Fix:** Change the column definition to use `datum_fmt` field. The rows already contain `datum_fmt` from `format_datum()` — just the column definition points to the wrong field. Keep raw `datum` for sorting via `sort` key.

### 1.2 "Nieuwe factuur" dialog missing date picker

**Problem:** `facturen.py:1074` uses a plain `ui.input` for the date while every other date input in the app has a calendar picker (via `ui.menu` + `ui.date` + `bind_value`).

**Fix:** Add the standard date picker pattern: input with calendar icon → `ui.menu` → `ui.date(mask='YYYY-MM-DD')` bound to the input.

### 1.3 Jaarafsluiting Balans edit: reversed button order

**Problem:** `jaarafsluiting.py:297-301` has `Opslaan | Annuleren` — every other dialog in the app uses `Annuleren | Primary Action`.

**Fix:** Swap order: `Annuleren` (flat) first, then `Opslaan` (color=primary). Also change `color=positive` to `color=primary` for consistency with other save actions.

### 1.4 werkdag_form save has no error handling

**Problem:** `werkdag_form.py:254-259` — if `add_werkdag`/`update_werkdag` throws (e.g. date validation), the error silently propagates to NiceGUI's event handler. User sees nothing.

**Fix:** Wrap the save call in try/except, show `ui.notify(str(e), type='negative')` on error.

### 1.5 Mixed-klant pre-selection shows empty dialog

**Problem:** `facturen.py:983-997` — selecting werkdagen from 2+ klanten and navigating to facturen opens a blank dialog with no explanation.

**Fix:** When `len(pre_klant_ids) > 1`, show `ui.notify('Selecteer werkdagen van één klant om te factureren', type='warning')` and clear the pre-selection.

### 1.6 Mark onbetaald has no confirmation

**Problem:** `facturen.py:281-287` — instantly flips betaald status without confirmation. Mark betaald (line 259+) has a dialog.

**Fix:** Add a confirmation dialog matching the mark-betaald pattern.

---

## Phase 2: Consistency Fixes

### 2.1 Standardize spacing: Tailwind → Quasar

Replace mixed Tailwind spacing with Quasar equivalents:
- `mt-2` → `q-mt-md` (bank.py:256, facturen.py:267)
- `my-2` → `q-my-sm` (kosten.py:664)
- `mt-2` → `q-mt-md` (kosten.py:696)

### 2.2 Jaarafsluiting container alignment

**Problem:** Uses `max-w-6xl q-pa-md` while all other pages use `max-w-7xl p-6`.

**Fix:** Change to `max-w-7xl` and `p-6` (or `q-pa-lg` which is equivalent).

### 2.3 Add page_title to jaarafsluiting

**Problem:** Only page without a content-area heading.

**Fix:** Add `page_title('Jaarafsluiting')` in the top bar row, before the year selector.

### 2.4 Bank page title mismatch

**Problem:** `page_title('Banktransacties')` but sidebar says "Bank".

**Fix:** Change to `page_title('Bank')` to match sidebar.

### 2.5 Documenten: add delete confirmation

**Problem:** `documenten.py:129-134` deletes immediately with just a notify. Every other page has a confirmation dialog.

**Fix:** Add a confirmation dialog: "Document X verwijderen?" with Annuleren | Verwijderen.

### 2.6 Sidebar setup button spacing

**Problem:** Setup buttons (Klanten, Instellingen) lack `q-mb-xs` that main nav buttons have.

**Fix:** Add `.classes('q-mb-xs')` to setup nav buttons.

---

## Phase 3: Dashboard Improvements

### 3.1 Move quick actions above charts

**Problem:** "Werkdag toevoegen" and "Nieuwe factuur" buttons are below charts — often off-screen and easy to miss. These are the most common daily actions.

**Fix:** Move the quick actions row to right after the KPI cards, before alerts and charts.

### 3.2 Rename "Resultaat" KPI

**Problem:** "Resultaat" in Dutch accounting means the tax result (bij/terug), creating confusion with the separate "Belasting prognose" card that shows actual bij/terug.

**Fix:** Rename to "Bedrijfswinst" with a subtitle showing "(YTD)" for current year.

### 3.3 Block future year selection

**Problem:** Year selector includes `huidig_jaar + 1`. Selecting a future year shows confusing extrapolated/empty data.

**Fix:** Change range to end at `huidig_jaar` (inclusive), removing the +1.

### 3.4 Bank transaction color legend

**Problem:** Row colors (teal=linked, amber=categorized, red=unlinked) are meaningful but unexplained.

**Fix:** Add a compact legend row above the table with three small colored badges and labels.

### 3.5 Show factuurnummer on werkdagen table

**Problem:** After a werkdag is gefactureerd, there is no visible link to the invoice. The data exists in `werkdagen.factuurnummer` but isn't displayed.

**Fix:** Add a "Factuur" column to the werkdagen table showing the factuurnummer (when present). This creates the visible connection between work and invoicing.

### 3.6 Add data freshness context to dashboard

**Problem:** No indication of how current the data is — user doesn't know if they forgot to import bank transactions.

**Fix:** Below the KPI grid, add a subtle "Laatste bank import: {datum}" line from the most recent `csv_bestand` timestamp in banktransacties.

---

## Out of Scope (future spec)

- Sidebar notification badges (E1)
- Onboarding/first-run detection (E3)
- Year-end readiness checklist (E8)
- Aandachtspunten/action items section (D1)
- Work-to-payment pipeline strip (D2)
- Simplify belasting prognose card (D4)
- Klanten persistent table (C1)
- Dashboard VA dialog extraction (C2)
- Aangifte splitting (C6)
- Hardcoded hex → semantic colors (B5) — widespread change needing separate audit
- Loading states/skeleton screens (E9)
