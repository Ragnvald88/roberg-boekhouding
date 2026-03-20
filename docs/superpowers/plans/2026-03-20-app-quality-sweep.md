# App Quality Sweep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix bugs, remove dead code, extract shared components, and improve visual consistency across the entire app — prioritized by impact.

**Architecture:** Three phases: (1) quick wins (dead code + bugs), (2) shared component extraction (DRY), (3) visual consistency. Each task is independent and produces a clean commit.

**Tech Stack:** NiceGUI 3.x, SQLite via aiosqlite, Python 3.12+

**Test command:** `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

---

## File Structure

| File | Action | Phase |
|------|--------|-------|
| `components/kpi_card.py` | Modify | 1 — remove dead `kpi_card()`, keep `kpi_strip()` |
| `components/charts.py` | Modify | 1 — remove dead code, expand DONUT_COLORS |
| `pages/klanten.py` | Modify | 1 — persistent table pattern |
| `pages/documenten.py` | Modify | 1 — fix preview path |
| `database.py` | Modify | 1 — add facturen datum index |
| `pages/facturen.py` | Modify | 1 — wrap blocking write_bytes |
| `components/shared_ui.py` | Create | 2 — date_input, confirm_dialog, year_options |
| `pages/*.py` (all pages) | Modify | 2 — use shared components |
| `components/layout.py` | Modify | 3 — add dashboard CSS classes |
| `pages/dashboard.py` | Modify | 3 — replace hardcoded hex with CSS classes |

---

## Phase 1: Quick Wins

### Task 1: Remove dead code from kpi_card.py and charts.py

**Files:**
- Modify: `components/kpi_card.py:1-36` — remove `kpi_card()` function, keep only `kpi_strip()`
- Modify: `components/charts.py:6-17,79` — remove `CHART_COLORS`, `revenue_chart` alias, expand `DONUT_COLORS`

- [ ] **Step 1: Remove `kpi_card()` from kpi_card.py**

Replace the entire file with only `kpi_strip()`:

```python
"""Shared KPI strip component for jaarafsluiting."""

from nicegui import ui

from components.utils import format_euro


def kpi_strip(omzet: float, winst: float,
              eigen_vermogen: float, balanstotaal: float):
    """4 compact KPI cards for jaarafsluiting — business-only metrics."""
    with ui.row().classes('w-full gap-3 flex-wrap'):
        for label, value, icon in [
            ('Omzet', format_euro(omzet), 'trending_up'),
            ('Winst', format_euro(winst), 'savings'),
            ('Eigen vermogen', format_euro(eigen_vermogen), 'account_balance'),
            ('Balanstotaal', format_euro(balanstotaal), 'balance'),
        ]:
            with ui.card().classes('flex-1 min-w-48 q-pa-md'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon(icon, size='1.2rem').style('color: #0F766E')
                    ui.label(label).classes('text-caption').style('color: #64748B')
                ui.label(value).classes('text-h6 q-mt-xs') \
                    .style('color: #0F172A; font-weight: 700; font-variant-numeric: tabular-nums')
```

- [ ] **Step 2: Clean up charts.py**

Remove `CHART_COLORS` (lines 6-15), remove `revenue_chart` alias (line 79). Expand `DONUT_COLORS` from 4 to 10 colors (teal gradient + complementary muted tones):

```python
DONUT_COLORS = [
    '#0F766E',  # teal-700
    '#14B8A6',  # teal-500
    '#5EEAD4',  # teal-300
    '#99F6E4',  # teal-200
    '#2DD4BF',  # teal-400
    '#0D9488',  # teal-600
    '#CCFBF1',  # teal-100
    '#115E59',  # teal-800
    '#F0FDFA',  # teal-50
    '#134E4A',  # teal-900
]
```

- [ ] **Step 3: Update jaarafsluiting import**

In `pages/jaarafsluiting.py:11`, change:
```python
from components.kpi_card import kpi_strip
```
(This should already work since we kept `kpi_strip` — just verify the import path is correct after the file rewrite.)

- [ ] **Step 4: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all 440+ pass

- [ ] **Step 5: Commit**

```bash
git add components/kpi_card.py components/charts.py
git commit -m "chore: remove dead code — kpi_card(), CHART_COLORS, revenue_chart alias; expand DONUT_COLORS to 10"
```

---

### Task 2: Fix Klanten page — persistent table pattern

**Files:**
- Modify: `pages/klanten.py`

The Klanten page currently rebuilds the entire UI (including table, page title, buttons) on every `refresh_klanten()` call. This loses pagination/sort state. All other pages use the persistent table pattern.

- [ ] **Step 1: Refactor to persistent table pattern**

The key change: create the `ui.table` ONCE in the page setup, then update only `table.rows` in the refresh function.

Current pattern (broken):
```python
async def refresh_klanten():
    container.clear()
    with container:
        page_title(...)  # rebuilt every time!
        ui.table(...)    # rebuilt every time!
```

New pattern (correct — matches kosten, werkdagen, facturen):
```python
# In page setup:
table = ui.table(columns=..., rows=[], ...)
# ... set up slots, events once ...

async def refresh_klanten():
    klanten = await get_klanten(DB_PATH)
    rows = [...]
    table.rows = rows
    table.update()
```

Read the existing `pages/klanten.py` carefully, then refactor:
1. Move `page_title()`, the "Nieuwe klant" button, and filter controls to the page setup (outside `refresh_klanten`)
2. Create `ui.table()` once in the page setup
3. Move table slot definitions and event handlers to the page setup
4. Make `refresh_klanten()` only update `table.rows` and call `table.update()`

- [ ] **Step 2: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

- [ ] **Step 3: Test manually**

Navigate to /klanten, add a klant, verify table updates without losing sort/page state.

- [ ] **Step 4: Commit**

```bash
git add pages/klanten.py
git commit -m "fix: klanten page — persistent table pattern (preserves sort/page state)"
```

---

### Task 3: Fix documenten preview path + add facturen datum index

**Files:**
- Modify: `pages/documenten.py:18,147-155` — fix static file serving for subdirectories
- Modify: `database.py` — add facturen datum index

- [ ] **Step 1: Fix documenten preview**

In `pages/documenten.py`, the preview constructs paths using just the filename:
```python
name = Path(bestandspad).name
f'/aangifte-files/{name}'
```

But files uploaded via the aangifte page may be in subdirectories. Fix by using the relative path from `AANGIFTE_DIR`:

```python
# Instead of just the name, use the path relative to AANGIFTE_DIR
rel_path = Path(bestandspad).relative_to(AANGIFTE_DIR)
url = f'/aangifte-files/{rel_path}'
```

If `bestandspad` is not under `AANGIFTE_DIR` (e.g., old data), fall back to just the filename.

- [ ] **Step 2: Add facturen datum index**

In `database.py`, after line 77 (`idx_facturen_klant`), add:

```python
CREATE INDEX IF NOT EXISTS idx_facturen_datum ON facturen(datum);
```

- [ ] **Step 3: Wrap blocking write_bytes in facturen.py**

In `pages/facturen.py:865`, change:
```python
pdf_dest.write_bytes(content)
```
to:
```python
await asyncio.to_thread(pdf_dest.write_bytes, content)
```

- [ ] **Step 4: Run full test suite**

- [ ] **Step 5: Commit**

```bash
git add pages/documenten.py database.py pages/facturen.py
git commit -m "fix: documenten preview path, facturen datum index, async write_bytes"
```

---

## Phase 2: Shared Components

### Task 4: Create `components/shared_ui.py` with reusable components

**Files:**
- Create: `components/shared_ui.py`
- Create: `tests/test_shared_ui.py`

- [ ] **Step 1: Create `components/shared_ui.py`**

```python
"""Shared UI components — DRY helpers used across all pages."""

from datetime import date

from nicegui import ui


def year_options(include_next: bool = False, as_dict: bool = False,
                 descending: bool = True) -> list | dict:
    """Generate consistent year options for year selectors.

    Args:
        include_next: Include next year (for werkdagen/facturen planning)
        as_dict: Return {year: str(year)} dict instead of list
        descending: Newest first (True) or oldest first (False)
    """
    current = date.today().year
    end = current + 1 if include_next else current
    years = list(range(2023, end + 1))
    if descending:
        years.reverse()
    if as_dict:
        return {y: str(y) for y in years}
    return years


def date_input(label: str = 'Datum', value: str = '',
               on_change=None) -> ui.input:
    """Reusable date input with calendar picker popup.

    Returns the ui.input element (value is bound to it).
    """
    inp = ui.input(label, value=value).props('outlined dense')
    with inp:
        with ui.menu().props('no-parent-event') as menu:
            with ui.date(mask='YYYY-MM-DD').bind_value(inp) as picker:
                picker.on('update:model-value',
                          lambda: menu.close())
        with inp.add_slot('append'):
            ui.icon('edit_calendar').on('click', menu.open) \
                .classes('cursor-pointer')
    if on_change:
        inp.on('update:model-value', on_change)
    return inp


async def confirm_dialog(title: str, message: str,
                         on_confirm, button_label: str = 'Verwijderen',
                         button_color: str = 'negative') -> None:
    """Show a confirmation dialog and call on_confirm if user confirms.

    Args:
        title: Dialog title
        message: Confirmation message (can include HTML)
        on_confirm: Async or sync callable to execute on confirm
        button_label: Text for the confirm button
        button_color: Quasar color for the confirm button
    """
    with ui.dialog() as dlg, ui.card().classes('q-pa-md'):
        ui.label(title).classes('text-h6')
        ui.label(message).classes('text-body2 text-grey-7 q-my-sm')

        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
            ui.button('Annuleren', on_click=dlg.close).props('flat')
            async def do_confirm():
                dlg.close()
                result = on_confirm()
                if hasattr(result, '__await__'):
                    await result

            ui.button(button_label, on_click=do_confirm) \
                .props(f'color={button_color}')
    dlg.open()
```

- [ ] **Step 2: Write tests for year_options**

Create `tests/test_shared_ui.py`:

```python
"""Tests voor shared UI components."""

from datetime import date
from unittest.mock import patch

from components.shared_ui import year_options


def test_year_options_default():
    """Default: descending list from current year to 2023."""
    result = year_options()
    assert result[0] == date.today().year
    assert result[-1] == 2023
    assert len(result) == date.today().year - 2023 + 1


def test_year_options_include_next():
    """include_next adds next year."""
    result = year_options(include_next=True)
    assert result[0] == date.today().year + 1


def test_year_options_ascending():
    """descending=False gives oldest first."""
    result = year_options(descending=False)
    assert result[0] == 2023
    assert result[-1] == date.today().year


def test_year_options_as_dict():
    """as_dict returns {year: str(year)} mapping."""
    result = year_options(as_dict=True)
    assert isinstance(result, dict)
    current = date.today().year
    assert result[current] == str(current)
```

- [ ] **Step 3: Run tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_shared_ui.py -v`
Expected: all 4 pass

- [ ] **Step 4: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add components/shared_ui.py tests/test_shared_ui.py
git commit -m "feat: shared UI components — year_options, date_input, confirm_dialog"
```

---

### Task 5: Replace year selector duplicates across all pages

**Files:**
- Modify: 9 page files (see year selector table in audit)

For each page, replace the inline year range logic with `year_options()` from `components/shared_ui`:

| Page | Current Pattern | Replace With |
|------|----------------|-------------|
| `pages/dashboard.py:30` | `{y: str(y) for y in range(huidig_jaar, 2022, -1)}` | `year_options(as_dict=True)` |
| `pages/werkdagen.py:38` | `{y: str(y) for y in range(2023, current_year + 2)}` | `year_options(include_next=True, as_dict=True, descending=False)` |
| `pages/facturen.py:45` | `{y: str(y) for y in range(2023, current_year + 2)}` | `year_options(include_next=True, as_dict=True, descending=False)` |
| `pages/kosten.py:33` | `list(range(huidig_jaar, 2022, -1))` | `year_options()` |
| `pages/bank.py:299` | `list(range(2023, current_year + 1))` | `year_options(descending=False)` |
| `pages/aangifte.py:78` | `list(range(huidig_jaar, 2022, -1))` | `year_options()` |
| `pages/jaarafsluiting.py:104` | `list(range(2023, date.today().year + 1))` | `year_options(descending=False)` |
| `pages/documenten.py:34` | `{y: str(y) for y in range(huidig_jaar, 2022, -1)}` | `year_options(as_dict=True)` |
| `pages/dashboard_omzet.py:17` | `{y: str(y) for y in range(huidig_jaar + 1, 2022, -1)}` | `year_options(include_next=True, as_dict=True)` |

- [ ] **Step 1: Add imports and replace patterns in all 9 files**

For each file, add `from components.shared_ui import year_options` and replace the inline range with the appropriate `year_options()` call.

- [ ] **Step 2: Run full test suite**

- [ ] **Step 3: Commit**

```bash
git add pages/*.py
git commit -m "refactor: replace 9 inline year range patterns with shared year_options()"
```

---

### Task 6: Replace date picker duplicates (top 3 highest-impact)

**Files:**
- Modify: `pages/kosten.py:435,626` — 2 instances in add/edit dialogs
- Modify: `pages/facturen.py:403` — edit dialog

Focus on the 3 most straightforward replacements. Leave `werkdag_form.py` (already a component) and `facturen.py:1096` (deeply nested in import dialog) for later.

- [ ] **Step 1: Replace date picker in kosten add dialog**

In `pages/kosten.py`, near line 435, replace the 8-line date picker pattern with:

```python
from components.shared_ui import date_input
# ...
input_datum = date_input('Datum', value=date.today().isoformat())
```

- [ ] **Step 2: Replace date picker in kosten edit dialog**

Near line 626, same replacement.

- [ ] **Step 3: Replace date picker in facturen edit dialog**

In `pages/facturen.py`, near line 403, same pattern.

- [ ] **Step 4: Test manually** — open each dialog, verify date picker works

- [ ] **Step 5: Run full test suite**

- [ ] **Step 6: Commit**

```bash
git add pages/kosten.py pages/facturen.py
git commit -m "refactor: use shared date_input component in kosten + facturen dialogs"
```

---

## Phase 3: Visual Consistency

### Task 7: Add dashboard CSS classes to layout.py

**Files:**
- Modify: `components/layout.py:14-50` — add CSS classes for dashboard styles

- [ ] **Step 1: Add CSS classes for dashboard design tokens**

In `components/layout.py`, add to the existing `ui.add_css()` block (after line 48):

```css
/* Dashboard hero cards */
.hero-label { font-size: 13px; color: #64748B; font-weight: 500; }
.hero-value { font-size: 30px; font-weight: 700; color: #0F172A;
              font-variant-numeric: tabular-nums; margin: 6px 0 2px; }
.hero-value-green { font-size: 30px; font-weight: 700; color: var(--q-positive);
                    font-variant-numeric: tabular-nums; margin: 6px 0 2px; }
.hero-value-red { font-size: 30px; font-weight: 700; color: var(--q-negative);
                  font-variant-numeric: tabular-nums; margin: 6px 0 2px; }
.context-text { font-size: 12px; color: #94A3B8; }
.section-label { font-size: 13px; font-weight: 600; color: #64748B;
                 text-transform: uppercase; letter-spacing: 0.05em; }
.chart-title { font-size: 15px; font-weight: 600; color: #0F172A; }
.chart-subtitle { font-size: 12px; color: #94A3B8; }
.strip-value { font-size: 14px; font-weight: 600; color: #0F172A; }
.strip-pct { font-size: 11px; color: #94A3B8; }
.card-standard { border-radius: 14px; border: 1px solid #E2E8F0; }
```

- [ ] **Step 2: Commit layout.py separately**

```bash
git add components/layout.py
git commit -m "feat: add dashboard CSS classes to shared layout"
```

---

### Task 8: Replace dashboard hardcoded styles with CSS classes

**Files:**
- Modify: `pages/dashboard.py` — replace ~78 hardcoded hex colors with CSS classes

- [ ] **Step 1: Replace inline styles in hero cards**

Replace patterns like:
```python
.style('font-size: 13px; color: #64748B; font-weight: 500')
```
With:
```python
.classes('hero-label')
```

And:
```python
.style('font-size: 30px; font-weight: 700; color: #0F172A; '
       'font-variant-numeric: tabular-nums; margin: 6px 0 2px')
```
With:
```python
.classes('hero-value')
```

Apply systematically across all hero cards, secondary strip, chart titles, and section labels.

For card borders:
```python
.style('border-radius: 14px; border: 1px solid #E2E8F0')
```
Replace with:
```python
.classes('card-standard')
```

Note: keep `.style()` only for one-off properties that are NOT in the CSS classes (like `cursor: pointer`, `height`, `width`, `display: grid`).

- [ ] **Step 2: Replace alert hardcoded styles**

The aandachtspunten section uses inline `ui.element('div').style(...)` with hardcoded alert colors. Replace with Quasar's built-in card coloring:

```python
# Old:
ui.element('div').style('background: #FFFBEB; border-radius: 10px; ...')

# New:
with ui.card().classes('q-pa-sm bg-amber-1').style(
        'border: 1px solid var(--q-warning); border-radius: 10px'):
```

- [ ] **Step 3: Run full test suite**

- [ ] **Step 4: Test manually** — verify dashboard looks identical

- [ ] **Step 5: Commit**

```bash
git add pages/dashboard.py
git commit -m "refactor: dashboard — replace 78 hardcoded hex colors with shared CSS classes"
```

---

### Task 9: Final sweep — verify all changes

- [ ] **Step 1: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 2: Test every page manually**

Navigate through: Dashboard, Werkdagen, Facturen, Kosten, Bank, Documenten, Jaarafsluiting, Aangifte, Klanten, Instellingen. Verify:
- No visual regressions
- Date pickers work in kosten + facturen dialogs
- Year selectors show correct ranges
- Klanten table preserves sort/page state
- Document previews load correctly

- [ ] **Step 3: Commit any remaining fixes**

```bash
git add -A
git commit -m "chore: final quality sweep — verify all pages"
```
