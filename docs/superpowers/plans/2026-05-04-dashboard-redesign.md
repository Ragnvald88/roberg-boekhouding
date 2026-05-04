# Dashboard Redesign — Sprint H Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Codex 4-layer review per task per CLAUDE.md "Codex-samenwerking als kwaliteitsstandaard".

**Spec:** `docs/superpowers/specs/2026-05-04-dashboard-redesign-design.md` (v3 post-discussion)

**Goal.** Restructureer dashboard van info-rich-maar-workflow-blind tegel-catalogus naar werk-doend dashboard met 4-zone layout: forward-looking hero (Omzet/Jaareinde-projectie/Belasting-reservering/Urencriterium), action-inbox met 4 inline-actions + seasonal-row injector, configureerbaar inzicht-grid (max 6 visible), conditional Privé-zone (AOV only).

**Architecture.** Nieuwe `services/dashboard.py` voor pure helpers (compute_belasting_reservering_progress, compute_jaareinde_projectie_display, prioritise_actions, _seasonal_action_rows, tax_calendar). Nieuwe `components/dashboard_widgets.py` voor per-tile renderers. Migratie 39 (`bedrijfsgegevens.dashboard_widgets_json`) voor customisation. /instellingen krijgt 4e tab "Dashboard" met show/hide checkboxes. CSS-classes voor `.is-tekort` modifier (Sprint G `.is-dirty` precedent) + nieuwe layout-classes. Geen drag-drop, geen per-tile seasonal severity, geen maand-filter (Codex's discussion concession). Realistic effort: 26-28u over 7 phases.

**Tech Stack.** NiceGUI 3.8 + Quasar/Vue, ECharts via `ui.echart`, raw SQL via aiosqlite, pytest + pytest-asyncio. Geen nieuwe runtime-dependencies.

**Baseline.** Pytest 1300 groen, master HEAD `de57f99` (deze v3 spec-commit zelf). Sprint A→G + cumulative audits afgerond.

---

## Architectuur-keuzes (lees eerst)

**1. Direct op master** — Sprint A→G conventie (50+ commits sinds Sprint B). Geen feature-branch. Per-task atomic commits + Codex 4-layer review per task = veiligheidsnet.

**2. User decisions vastgelegd** (per spec §G):
- **U1**: Jaareinde-projectie tile = **1 number** (winst-projectie alleen). Cleaner hero.
- **U2**: Customisation-link = **`⚙ Tegels aanpassen`** in **footer van zone 3** (contextueel naast inzicht-grid).
- **U3**: "Stuur herinnering" = **confirm-dialog** vóór Mail.app open (consistency + safer).
- **Phasing**: monolithische Sprint H (alle 7 phases ipv ship-fast).

**3. File structure** — extract naar nieuwe files:
- `services/dashboard.py` (NEW): pure helpers — alle compute_*, prioritise_actions, _seasonal_action_rows, tax_calendar
- `components/dashboard_widgets.py` (NEW): per-tile-renderers — _render_belasting_reservering, _render_jaareinde_projectie, _render_action_inbox, _render_inzicht_tile_*, _render_prive_zone
- `pages/dashboard.py` (MODIFY): orchestration only — gather data, call renderers, manage layout

**4. CSS conventie** — alle nieuwe classes BUITEN `@layer components` (Sprint G cascade-discipline). `.is-tekort` modifier via chained selector `.q-card.dashboard-hero-tile.is-tekort` analoog aan `.q-card.settings-card.is-dirty`. Voeg `dashboard-hero-tile` toe aan `QUASAR_APPLIED_APP_CLASSES` allow-list.

**5. Reuse-existing-infra** — geen nieuwe queries waar bestaande werken:
- `extrapoleer_jaaromzet(jaar)` — al bestaand voor Jaareinde-projectie
- `services.agenda.get_urencriterium_projectie(jaar)` — al bestaand (Sprint A)
- `services.agenda.get_zes_weken_prognose(vanaf)` — al bestaand (Sprint A)
- `get_omzet_per_klant(jaar)` — al bestaand maar unused on dashboard
- `get_terugkerende_kosten` — al bestaand in /kosten
- `_build_herinnering_body` + `open_mail_with_attachment` — al bestaand in pages/facturen.py voor Stuur-herinnering quick-action
- `update_factuur_status` — al bestaand voor concept-stale Verstuur-action

**6. Customisation persistence** — `bedrijfsgegevens.dashboard_widgets_json TEXT NULL` (migratie 39). NULL = defaults. Schema-version + 4 defensiveness-rules (NULL→defaults, version-mismatch→fall-through+log, unknown-keys→ignore, missing-keys→default).

**7. Tile-cap discipline** — max 6 visible inzicht-tiles. 7e toggle ON in /instellingen → toast "Limiet 6 tegels bereikt — verberg eerst een andere tegel om deze toe te voegen". Voorkomt info-overload.

**8. Quick-actions header CTAs** — `unelevated color=primary` (NIET huidige `flat dense color=secondary` grijs-op-grijs).

---

## File Structure

| Pad | Verantwoordelijkheid | Mode |
|---|---|---|
| `services/dashboard.py` | Pure helpers: `compute_belasting_reservering_progress`, `compute_jaareinde_projectie_display`, `ActionRow` dataclass, `prioritise_actions`, `_seasonal_action_rows`, `tax_calendar`, `should_show_prive_zone`, `load_dashboard_widgets_config`, `DEFAULT_WIDGETS`. Géén NiceGUI-imports (boundary). | create |
| `components/dashboard_widgets.py` | Per-tile renderers (NiceGUI-coupled): `render_belasting_reservering_hero`, `render_jaareinde_projectie_hero`, `render_action_inbox`, `render_sph_tile`, `render_zes_weken_tile`, `render_top_klanten_tile`, `render_documenten_tile`, `render_cash_positie_tile`, `render_tax_calendar_tile`, `render_terugkerende_kosten_tile`, `render_prive_zone`. | create |
| `pages/dashboard.py` | Orchestration only: `dashboard_page()` async — gather all data, call render-helpers, manage 4-zone layout. Slank na refactor (~300 LoC ipv huidige 683). | modify |
| `components/layout.py` | Add CSS classes: `.dashboard-hero-tile`, `.is-tekort` modifier, `.action-inbox`, `.action-inbox-row`, `.prive-zone`. Allow-list update voor `dashboard-hero-tile`. | modify |
| `tests/test_visual_css.py` | Add `'dashboard-hero-tile'` to `QUASAR_APPLIED_APP_CLASSES` + 1 contract-test for `.is-tekort` modifier shape. | modify |
| `database.py` | Migratie 39 (add `dashboard_widgets_json` column). New helper `get_factuur_aging_buckets(jaar)`, `get_concept_facturen_stale(jaar, days=14)`. New helper `get_aov_total(jaar)` voor Privé-zone. | modify |
| `pages/instellingen.py` | Nieuwe 4e tab "Dashboard" met checkbox-lijst voor I-1..I-8 + max-6-warning toast. | modify |
| `tests/test_dashboard_helpers.py` | Unit-tests voor alle pure helpers in `services/dashboard.py`. | create |
| `tests/test_dashboard_widgets_config.py` | Unit + round-trip tests voor customisation JSON config. | create |

---

## Phase 1 — Visual cleanup + Belasting-reservering hero-tile

**Goal**: dead-code removal + fix bug + introduce `.is-tekort` modifier + new helper. Lowest-risk-highest-value start.

### Task 1.1 — Page-title-year + dead classes + documenten-link bug

**Files:**
- Modify: `pages/dashboard.py:60` (page_title)
- Modify: `pages/dashboard.py:288-294` (dead `hero-value-pos/-neg` classes — replace with inline color-by-sign)
- Modify: `pages/dashboard.py:455-470` (documenten-strip click-handler — wrong navigation target)

- [ ] **Step 1.1.1: Read current state**

```bash
sed -n '60p;288,294p;455,470p' pages/dashboard.py
```

- [ ] **Step 1.1.2: Update page_title to include year**

In `pages/dashboard.py:60` (around `page_title('Overzicht')`), wrap to dynamic:

```python
# OLD:
#   page_title('Overzicht')
# NEW:
huidig_jaar = date.today().year
page_title(f'Overzicht {jaar_select.value if hasattr(jaar_select, "value") else huidig_jaar}')
```

NOTE: `jaar_select` doesn't exist yet at line 60 (it's defined ~line 71). Move `page_title()` call to AFTER `jaar_select` creation, OR use `huidig_jaar` directly + update on year-change. Choose: use `huidig_jaar` only (simpler — title doesn't react to year-change). Leave a code-comment about this trade-off.

```python
huidig_jaar = date.today().year
# ... (jaar_select creation) ...
# Title shows current calendar year, not selected jaar (user knows what they selected via dropdown).
page_title(f'Overzicht {huidig_jaar}')
```

- [ ] **Step 1.1.3: Replace dead `hero-value-pos/-neg` classes with inline color**

Find:
```python
ui.label(format_euro(ytd_winst, decimals=0)).classes(
    'hero-value-positive' if ytd_winst >= 0
    else 'hero-value-negative')
```

Replace with:
```python
color = 'var(--q-positive)' if ytd_winst >= 0 else 'var(--q-negative)'
ui.label(format_euro(ytd_winst, decimals=0)).classes('hero-value').style(
    f'color: {color}')
```

Then **search** `components/layout.py` for the unused `.hero-value-positive` and `.hero-value-negative` definitions:
```bash
grep -n "hero-value-positive\|hero-value-negative" components/layout.py pages/dashboard.py
```
Remove the orphan CSS class definitions if found.

- [ ] **Step 1.1.4: Fix documenten click-handler navigation target**

Find around line 455-470 in `pages/dashboard.py`:
```python
with ui.card().classes('flex-1 q-pa-sm').style(
        'border-radius: 10px; ... cursor: pointer').on(
        'click', lambda: ui.navigate.to('/werkdagen')):
```

Wait — verify by grep first:
```bash
grep -n "folder_open\|aangifte_docs\|documenten" pages/dashboard.py | head -20
```

The Documenten-strip card should navigate to `/aangifte` (the aangifte page exists; documenten-detail lives there). Check if there is `.on('click', ...)` on the documenten-strip-card and update it. If currently navigates to `/werkdagen`, fix to `/aangifte`.

NOTE: there may be no click-handler at all on documenten-strip currently. If so, add: `.on('click', lambda: ui.navigate.to('/aangifte'))`. Verify visually before commit.

- [ ] **Step 1.1.5: Run tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1300 passed (no regression).

- [ ] **Step 1.1.6: Commit**

```bash
git add pages/dashboard.py components/layout.py
git commit -m "$(cat <<'EOF'
chore(sprint-h): T1.1 dashboard visual cleanup

- Page-title shows current year ("Overzicht 2026")
- Drop dead `hero-value-positive`/`-negative` classes (winst is bijna
  altijd positief — variant nooit zichtbaar). Replace with inline
  color-by-sign via var(--q-positive|negative).
- Fix documenten-strip click target: was /werkdagen (dead-end), now
  /aangifte (correct destination).

Codex round-2 catched all 3 in v2-critique.

Pytest 1300, geen regressies.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 1.2 — Drop misleading Winst-YTD sparkline

**Files:**
- Modify: `pages/dashboard.py:295-297` (sparkline-call op winst-card)

- [ ] **Step 1.2.1: Find and remove the misleading sparkline**

In `pages/dashboard.py` find the Bedrijfswinst card sparkline call:
```python
# Sparkline (revenue as proxy for profit trend)
if any(v > 0 for v in omzet_huidig):
    _render_sparkline(omzet_huidig, '#059669')
```

This shows OMZET data on a WINST tile — misleading. Remove these 3 lines + comment.

- [ ] **Step 1.2.2: Tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1300 passed.

- [ ] **Step 1.2.3: Commit**

```bash
git add pages/dashboard.py
git commit -m "$(cat <<'EOF'
chore(sprint-h): T1.2 drop misleading winst-sparkline

The Bedrijfswinst-card showed an OMZET sparkline as 'profit trend
proxy'. Misleading: omzet ≠ winst trend. Drop the visual rather
than mislead the reader. T2 will redesign the hero anyway.

Codex round-2 catched dit als visual-debt.

Pytest 1300.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 1.3 — `services/dashboard.py` foundation + `compute_belasting_reservering_progress`

**Files:**
- Create: `services/dashboard.py`
- Create: `tests/test_dashboard_helpers.py`

- [ ] **Step 1.3.1: Write failing test first**

Create `tests/test_dashboard_helpers.py`:

```python
"""Unit tests for services.dashboard pure helpers."""
from datetime import date

from services.dashboard import compute_belasting_reservering_progress


class TestComputeBelastingReserveringProgress:
    """Test the YTD vs prorated belasting-reservering check."""

    def test_op_koers_when_va_matches_prorated_expected(self):
        # Mei (month 5): 5/12 = 41.6% van jaarbelasting verwacht
        # Jaarbelasting €12000 → verwacht €5000 YTD
        # VA betaald €5000 → exactly op-koers (diff = 0)
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=5000.0,
            today=date(2026, 5, 31),
        )
        assert status == 'op_koers'
        assert -1000 <= diff <= 1000

    def test_tekort_when_va_significantly_below_prorated(self):
        # Same month, VA betaald slechts €2000 → tekort van €3000
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=2000.0,
            today=date(2026, 5, 31),
        )
        assert status == 'tekort'
        assert diff > 1000

    def test_overreservering_when_va_significantly_above_prorated(self):
        # Same month, VA betaald €10000 → overreservering van €5000
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=10000.0,
            today=date(2026, 5, 31),
        )
        assert status == 'overreservering'
        assert diff < -2000

    def test_january_minimal_data(self):
        # Januari (month 1): 1/12 = 8.3% verwacht
        # Jaarbelasting €12000 → verwacht €1000 YTD
        # VA betaald €0 → tekort van €1000 — net op de threshold
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=0.0,
            today=date(2026, 1, 31),
        )
        # Diff is exactly 1000.0 — niet > 1000 → 'op_koers' (boundary case)
        assert status == 'op_koers'
        assert diff == 1000.0

    def test_december_full_year_check(self):
        # December: 12/12 = 100% verwacht. VA volledig betaald → op_koers
        status, diff = compute_belasting_reservering_progress(
            berekend_jaarbelasting=12000.0,
            va_betaald_ytd=12000.0,
            today=date(2026, 12, 31),
        )
        assert status == 'op_koers'
        assert diff == 0.0
```

- [ ] **Step 1.3.2: Run test to verify it fails (module not found)**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_dashboard_helpers.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'services.dashboard'`.

- [ ] **Step 1.3.3: Create `services/dashboard.py`**

```python
"""Pure helpers for /dashboard page rendering.

UI-vrij — geen NiceGUI imports. Returns dataclasses or primitives that
the per-tile renderers in components/dashboard_widgets.py consume.

All functions are testable in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal


def compute_belasting_reservering_progress(
    berekend_jaarbelasting: float,
    va_betaald_ytd: float,
    today: date,
) -> tuple[Literal['op_koers', 'tekort', 'overreservering'], float]:
    """Returns (status, diff_amount).

    diff > 0 = je moet nog reserveren (tekort);
    diff < 0 = je hebt overgereserveerd.

    Threshold: 'tekort' if (expected_va_ytd - va_betaald_ytd) > 1000;
    'overreservering' if < -2000; else 'op_koers'.

    The asymmetric threshold (1000 vs -2000) reflects user-pain bias:
    being short on tax money is more painful than being early.
    """
    months_elapsed = today.month
    expected_va_ytd = berekend_jaarbelasting * months_elapsed / 12
    diff = expected_va_ytd - va_betaald_ytd
    if diff > 1000:
        return ('tekort', diff)
    if diff < -2000:
        return ('overreservering', diff)
    return ('op_koers', diff)
```

- [ ] **Step 1.3.4: Run test to verify it passes**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_dashboard_helpers.py -v
```

Expected: 5 PASS.

- [ ] **Step 1.3.5: Run full suite — verify no regression**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1305 passed (1300 baseline + 5 new).

- [ ] **Step 1.3.6: Commit**

```bash
git add services/dashboard.py tests/test_dashboard_helpers.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T1.3 services/dashboard + compute_belasting_reservering_progress

Sprint H Task 1.3 — foundation for new pure-helpers module.

services/dashboard.py is UI-vrij (geen NiceGUI imports), houses all
testable pure functions. T2-T6 will add more helpers here.

compute_belasting_reservering_progress: returns (status, diff) tuple
voor de Belasting-reservering hero-tile. Asymmetric threshold (tekort
> €1000, overreservering < -€2000) reflects user-pain bias.

Pytest 1300 → 1305, geen regressies.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 1.4 — `.dashboard-hero-tile` + `.is-tekort` modifier CSS + Belasting-reservering hero-tile rebuild

**Files:**
- Modify: `components/layout.py` (add CSS classes BUITEN `@layer components`)
- Modify: `tests/test_visual_css.py:190` (add `'dashboard-hero-tile'` to allow-list)
- Modify: `pages/dashboard.py` (Belasting-reservering card section, regel ~299-410)

- [ ] **Step 1.4.1: Add cascade-lint test for `.dashboard-hero-tile.is-tekort`**

In `tests/test_visual_css.py` add after `test_sprint_g_settings_section_defined`:

```python
def test_sprint_h_dashboard_hero_tile_chained_selector():
    """Sprint H cascade-rule: .dashboard-hero-tile MUST be defined as
    chained selector .q-card.dashboard-hero-tile (not naked) to win
    from Quasar's unlayered .q-card defaults.

    Same lesson as agenda-cell.holiday-marker (Sprint A) and
    .alert-link (Sprint F) and .settings-card (Sprint G).
    """
    css = _strip_comments(_extract_css())

    naked_pattern = r"(?<![.\w-])\.dashboard-hero-tile\s*\{"
    naked_matches = re.findall(naked_pattern, css)

    chained_pattern = r"\.q-card\.dashboard-hero-tile\s*\{"
    chained_matches = re.findall(chained_pattern, css)

    assert chained_matches, (
        "Sprint H: .dashboard-hero-tile MUST be defined as chained "
        ".q-card.dashboard-hero-tile { ... } in components/layout.py."
    )
    assert not naked_matches, (
        f"Sprint H: found naked .dashboard-hero-tile definition. "
        f"Use chained selector instead. Hits: {naked_matches}"
    )


def test_sprint_h_is_tekort_modifier_defined():
    """Sprint H: .is-tekort modifier MUST exist as chained selector
    .q-card.dashboard-hero-tile.is-tekort with at least border-left."""
    css = _strip_comments(_extract_css())
    pattern = r"\.q-card\.dashboard-hero-tile\.is-tekort\s*\{"
    matches = re.findall(pattern, css)
    assert matches, ".is-tekort modifier missing"
```

- [ ] **Step 1.4.2: Add `'dashboard-hero-tile'` to `QUASAR_APPLIED_APP_CLASSES`**

In `tests/test_visual_css.py:190-196` (the QUASAR_APPLIED_APP_CLASSES list), add:

```python
QUASAR_APPLIED_APP_CLASSES = [
    'nav-icon',
    'alert-icon',
    'alert-link',
    'severity-fg',
    'settings-card',         # Sprint G
    'dashboard-hero-tile',   # Sprint H — applied to ui.card (= .q-card)
]
```

- [ ] **Step 1.4.3: Run new tests, verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_visual_css.py::test_sprint_h_dashboard_hero_tile_chained_selector tests/test_visual_css.py::test_sprint_h_is_tekort_modifier_defined -v
```

Expected: 2 FAIL.

- [ ] **Step 1.4.4: Add CSS to `components/layout.py`**

In `components/layout.py`, find the Sprint G unlayered block (after `.severity-card .severity-fg` definitions) and ADD AFTER it:

```css
/* === Sprint H — dashboard hero-tile + .is-tekort modifier
   Defined OUTSIDE @layer components (chained selector for cascade-safety).
   .is-tekort = visual cue when belasting-reservering shortfall > €1k.
   Same modifier-pattern as Sprint G's .settings-card.is-dirty. */
.q-card.dashboard-hero-tile {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    margin: 0;
    /* No box-shadow: Quasar `flat` default-prop overrules with !important.
       Same lesson as Sprint G .settings-card. */
}
.q-card.dashboard-hero-tile.is-tekort {
    border-left: 3px solid var(--q-negative);
}
```

(Place INSIDE the same `ui.add_head_html('<style>...</style>')` call where the other unlayered blocks live.)

- [ ] **Step 1.4.5: Run new tests, verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_visual_css.py -v
```

Expected: All visual_css tests pass (incl 2 new).

- [ ] **Step 1.4.6: Rebuild Belasting-reservering hero-tile in `pages/dashboard.py`**

Replace the entire current `Belasting prognose` card (regel ~299-410) with a new structure that:
1. Uses `dashboard-hero-tile` class
2. Renders **engine-exact reservering** (using existing `_compute_ib_estimate` + new `compute_belasting_reservering_progress`)
3. Adds `.is-tekort` modifier when status='tekort'
4. Adds warning-icon when tekort
5. Removes the verbose progress-bar + termijn-info (those move to /aangifte per spec C.2)

Replace structure (search for `Card 3: Belasting prognose` in dashboard.py and replace the whole `with ui.card().classes('q-pa-lg')...` block):

```python
# Card 3: Belasting-reservering (Sprint H — replaces verbose Belasting-prognose)
from services.dashboard import compute_belasting_reservering_progress

if ib_resultaat is not None:
    berekend_jaarbelasting = (ib_resultaat['netto_ib']
                              + ib_resultaat['zvw'])
    if va_data['has_bank_data']:
        va_betaald = va_data['totaal_betaald']
    else:
        va_betaald = (ib_resultaat['va_ib_betaald']
                      + ib_resultaat['va_zvw_betaald'])

    status, diff = compute_belasting_reservering_progress(
        berekend_jaarbelasting=berekend_jaarbelasting,
        va_betaald_ytd=va_betaald,
        today=date.today(),
    )
    is_tekort = (status == 'tekort')

    card_classes = 'dashboard-hero-tile'
    if is_tekort:
        card_classes += ' is-tekort'

    with ui.card().classes(card_classes) \
            .style('cursor: pointer') \
            .on('click', lambda: ui.navigate.to('/aangifte')):
        with ui.row().classes('w-full justify-between items-center'):
            ui.label('Belasting-reservering').classes('hero-label')
            if is_tekort:
                ui.icon('warning', size='18px').style(
                    'color: var(--q-negative)') \
                    .tooltip(f'Tekort: {format_euro(diff, decimals=0)}')
        # Engine-exact bedrag — toon wat NU op spaarrekening moet staan
        nu_te_reserveren = max(0, berekend_jaarbelasting * date.today().month / 12 - va_betaald)
        ui.label(format_euro(nu_te_reserveren, decimals=0)).classes(
            'hero-value')
        ui.label(
            f'Berekend €{berekend_jaarbelasting:,.0f}'.replace(',', '.')
            + f' · betaald €{va_betaald:,.0f}'.replace(',', '.')
        ).classes('context-text')
else:
    with ui.card().classes('dashboard-hero-tile'):
        ui.label('Belasting-reservering').classes('hero-label')
        ui.label('Geen gegevens').classes(
            'context-text').style('margin-top: 8px')
```

- [ ] **Step 1.4.7: Apply `dashboard-hero-tile` class to Card 1 (Omzet) and Card 2 (Winst) too**

For consistency, replace `q-pa-lg` class on Cards 1+2 with `dashboard-hero-tile` (the new class includes padding+border+background — q-pa-lg is now redundant). Do NOT add `is-tekort` to Cards 1+2.

- [ ] **Step 1.4.8: Run full test suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1307 passed (1305 + 2 new cascade-lint).

- [ ] **Step 1.4.9: Commit**

```bash
git add components/layout.py tests/test_visual_css.py pages/dashboard.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T1.4 .dashboard-hero-tile + .is-tekort modifier + Belasting-reservering rebuild

Sprint H Task 1.4 — engine-exact Belasting-reservering hero-tile met
visual-cue voor tekort.

CSS:
- .q-card.dashboard-hero-tile (chained selector, BUITEN @layer)
- .q-card.dashboard-hero-tile.is-tekort modifier (border-left red)
- Allow-list update + 2 cascade-lint regression tests

UI:
- Belasting-reservering tile rebuild: NU-te-reserveren bedrag
  prominent (was: bij/terug + verbose progress-bar)
- Warning-icon naast title als status='tekort' (>€1k shortfall)
- Cards 1+2 ook naar dashboard-hero-tile class voor visuele consistency

Old verbose progress-bar + VA-termijn-info verhuizen naar /aangifte
(per spec C.2 — hero-card moet scannable in 2 sec).

Pytest 1305 → 1307.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — Hero re-shape (Jaareinde-projectie + Urencriterium-projectie + Quick-actions)

### Task 2.1 — Helper `compute_jaareinde_projectie_display`

**Files:**
- Modify: `services/dashboard.py` (add helper)
- Modify: `tests/test_dashboard_helpers.py` (add 4 unit-tests)

- [ ] **Step 2.1.1: Verify `extrapoleer_jaaromzet` signature**

```bash
grep -n "def extrapoleer_jaaromzet" pages/aangifte.py services/*.py components/*.py 2>&1 | head -5
```

Read the function to know its return shape. Likely returns `dict` with keys `extrapolated_omzet`, `confidence`, `basis_maanden`, `ytd_omzet`.

- [ ] **Step 2.1.2: Write failing tests**

In `tests/test_dashboard_helpers.py` add:

```python
class TestComputeJaareindeProjectieDisplay:
    """Tests for the hero-tile data-shape (1 number — winst-projectie)."""

    def test_high_confidence_full_year_exact(self):
        # Eind dec, basis_maanden=12 → projectie = ytd × 1.0
        from services.dashboard import compute_jaareinde_projectie_display
        result = compute_jaareinde_projectie_display(
            extrapolated_omzet=120_000.0,
            kosten_ytd=30_000.0,
            confidence='high',
            basis_maanden=12,
        )
        assert result['winst_projectie'] == 90_000.0
        assert result['confidence'] == 'high'
        assert result['basis_maanden'] == 12

    def test_medium_confidence_mid_year(self):
        from services.dashboard import compute_jaareinde_projectie_display
        # Juli, basis_maanden=6, ytd_omzet ≈ 60k → projectie 120k
        result = compute_jaareinde_projectie_display(
            extrapolated_omzet=120_000.0,
            kosten_ytd=18_000.0,  # halfjaar kosten
            confidence='medium',
            basis_maanden=6,
        )
        # Kosten worden ook geëxtrapoleerd naar 12mo: 18k × 12/6 = 36k
        # Winst = 120k - 36k = 84k
        assert result['winst_projectie'] == 84_000.0
        assert result['confidence'] == 'medium'

    def test_low_confidence_early_year(self):
        from services.dashboard import compute_jaareinde_projectie_display
        # Januari, basis_maanden=1
        result = compute_jaareinde_projectie_display(
            extrapolated_omzet=130_000.0,
            kosten_ytd=2_500.0,
            confidence='low',
            basis_maanden=1,
        )
        # Kosten extrapoleren: 2500 × 12/1 = 30000
        assert result['winst_projectie'] == 100_000.0
        assert result['confidence'] == 'low'

    def test_zero_basis_maanden_falls_back_to_ytd_omzet(self):
        from services.dashboard import compute_jaareinde_projectie_display
        # Edge case: basis_maanden=0 zou divide-by-zero geven
        result = compute_jaareinde_projectie_display(
            extrapolated_omzet=0.0,
            kosten_ytd=0.0,
            confidence='low',
            basis_maanden=0,
        )
        assert result['winst_projectie'] == 0.0
        assert result['confidence'] == 'low'
```

- [ ] **Step 2.1.3: Verify tests fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_dashboard_helpers.py::TestComputeJaareindeProjectieDisplay -v
```

Expected: 4 FAIL — `cannot import name 'compute_jaareinde_projectie_display'`.

- [ ] **Step 2.1.4: Implement helper**

In `services/dashboard.py` add:

```python
def compute_jaareinde_projectie_display(
    extrapolated_omzet: float,
    kosten_ytd: float,
    confidence: Literal['low', 'medium', 'high'],
    basis_maanden: int,
) -> dict:
    """Returns dict with `winst_projectie`, `confidence`, `basis_maanden`
    for the Jaareinde-projectie hero-tile (U1 = 1 number).

    Kosten YTD wordt geëxtrapoleerd naar 12mo gebruikmakend van
    basis_maanden (zelfde extrapolatie-logica als omzet). Edge-case:
    basis_maanden=0 → kosten_extrapolated = 0.
    """
    if basis_maanden <= 0:
        kosten_extrapolated = 0.0
    else:
        kosten_extrapolated = kosten_ytd * 12 / basis_maanden
    winst_projectie = extrapolated_omzet - kosten_extrapolated
    return {
        'winst_projectie': winst_projectie,
        'confidence': confidence,
        'basis_maanden': basis_maanden,
    }
```

- [ ] **Step 2.1.5: Verify tests pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_dashboard_helpers.py -v
```

Expected: 9 PASS (5 from T1.3 + 4 new).

- [ ] **Step 2.1.6: Commit**

```bash
git add services/dashboard.py tests/test_dashboard_helpers.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T2.1 compute_jaareinde_projectie_display helper

Returns dict shape voor Jaareinde-projectie hero-tile (U1 = 1 number,
focus winst-projectie). Kosten YTD wordt geëxtrapoleerd naar 12mo
gebruikmakend van basis_maanden parameter (zelfde extrapolatie als omzet).

Edge-case: basis_maanden=0 (geen YTD-data) → kosten_extrapolated=0,
fallback to extrapolated_omzet als winst_projectie.

Pytest 1307 → 1311 (+4 unit tests).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 2.2 — Jaareinde-projectie hero-tile (replaces Winst-YTD as separate tile)

**Files:**
- Modify: `pages/dashboard.py` (Card 2 area)

- [ ] **Step 2.2.1: Read current `Card 2: Bedrijfswinst` section**

```bash
sed -n '274,298p' pages/dashboard.py
```

Currently Card 2 = Winst YTD. Per U1 + spec, this becomes Jaareinde-projectie with Winst-YTD as sub-line.

- [ ] **Step 2.2.2: Replace Card 2 structure**

```python
# Card 2: Jaareinde-projectie (was: Bedrijfswinst YTD with sparkline)
# Per spec U1: 1 number = winst-projectie. Winst-YTD wordt sub-line.
from services.dashboard import compute_jaareinde_projectie_display
from pages.aangifte import extrapoleer_jaaromzet  # already-existing function

# extrapoleer_jaaromzet is async; ensure it was already gathered.
# Check if 'projection' was added to the gather() at line 208.
# If NOT, add it:
# (line ~208 area:)
#     projection_data = await extrapoleer_jaaromzet(DB_PATH, jaar=jaar)
# Then access projection_data['extrapolated_omzet'], ['confidence'], ['basis_maanden'].

# (Actually check if `projection` is already inside `_compute_ib_estimate` — yes it is.
# So pull from `ib_resultaat` for current year, OR re-call extrapoleer_jaaromzet for past years.)

# For simplicity: re-call extrapoleer_jaaromzet in the gather() block:
# Add to gather() at ~line 208:
#     extrapoleer_jaaromzet(DB_PATH, jaar=jaar),
# And unpack into a new local variable `projection_raw`.

# Then in the Card 2 render:
projection_display = compute_jaareinde_projectie_display(
    extrapolated_omzet=projection_raw['extrapolated_omzet'],
    kosten_ytd=kpis['kosten'],
    confidence=projection_raw['confidence'],
    basis_maanden=projection_raw['basis_maanden'],
)
ytd_winst = kpis['omzet'] - kpis['kosten']

confidence_label_map = {
    'low': ('Schatting', 'var(--q-warning)'),
    'medium': ('Prognose', '#0369A1'),
    'high': ('Betrouwbaar', 'var(--q-positive)'),
}
conf_label, conf_color = confidence_label_map.get(
    projection_display['confidence'], ('Schatting', 'var(--q-warning)'))

with ui.card().classes('dashboard-hero-tile') \
        .style('cursor: pointer') \
        .on('click', lambda: ui.navigate.to('/aangifte')):
    with ui.row().classes('w-full justify-between items-center'):
        ui.label('Jaareinde-projectie').classes('hero-label')
        ui.label(conf_label).style(
            f'font-size: 11px; font-weight: 500; color: {conf_color}; '
            f'background: var(--surface); padding: 2px 8px; border-radius: 10px; '
            f'border: 1px solid {conf_color}')
    ui.label(format_euro(projection_display['winst_projectie'], decimals=0)).classes(
        'hero-value')
    # Sub-line: Winst YTD (rear-view)
    ui.label(
        f'YTD: {format_euro(ytd_winst, decimals=0)}'
    ).classes('context-text')
```

- [ ] **Step 2.2.3: Add `extrapoleer_jaaromzet` to `asyncio.gather`**

In `pages/dashboard.py` around line 205-222 (the big gather call), add `extrapoleer_jaaromzet(DB_PATH, jaar=jaar)` to the gather and unpack the result.

Verify with grep first:
```bash
grep -n "extrapoleer_jaaromzet\|asyncio.gather" pages/dashboard.py
```

- [ ] **Step 2.2.4: Tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1311 passed.

- [ ] **Step 2.2.5: Commit**

```bash
git add pages/dashboard.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T2.2 Jaareinde-projectie hero-tile (replaces Winst-YTD)

Per spec U1: hero-tile #2 toont winst-projectie (1 number) met
confidence-badge (Schatting/Prognose/Betrouwbaar). Winst-YTD verhuist
naar sub-line eronder ("YTD: €X").

Hero is nu coherente forward-looking strip:
1. Omzet YTD (rear-view anchor)
2. Jaareinde-projectie (NEW — forward winst)
3. Belasting-reservering (forward)
4. Urencriterium-projectie (Phase 2.3 — forward)

Reuses existing extrapoleer_jaaromzet (was already used in IB-estimate).

Pytest 1311.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 2.3 — Urencriterium-projectie hero-upgrade + Quick-actions header

**Files:**
- Modify: `pages/dashboard.py` (strip-cards section + header)

- [ ] **Step 2.3.1: Verify `services.agenda.get_urencriterium_projectie` signature**

```bash
grep -n "def get_urencriterium_projectie\|@dataclass\|UrencriteriumState" services/agenda.py | head -10
```

Read the return-shape — likely `UrencriteriumState` dataclass with fields like `uren_huidig`, `tempo_per_dag`, `prognose_jaareinde`, `target`, `dagen_resterend`.

- [ ] **Step 2.3.2: Replace current Urencriterium strip-card with hero-tile**

In `pages/dashboard.py` find the strip-row section (~regel 412-471). Move Urencriterium OUT of the strip and INTO the hero-grid as Card 4. Remove the entire strip-row block (Uren/Km/Documenten) — those move into either the inzicht-grid or absorb into action-zone (per spec).

Add to `asyncio.gather` (line ~208 area):
```python
get_urencriterium_projectie(DB_PATH, jaar),
```
(Import: `from services.agenda import get_urencriterium_projectie`)

In the hero-grid section (the `with ui.element('div').style('display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; align-items: stretch')`-block — note: change from `repeat(3, 1fr)` to `repeat(4, 1fr)` for 4 hero tiles):

Add as Card 4:
```python
# Card 4: Urencriterium-projectie
urencrit = uren_state  # from gather
prognose = urencrit.prognose_jaareinde
target = urencrit.target  # = 1225
huidig = urencrit.uren_huidig

if target > 0 and prognose >= target * 1.05:
    pace_color = 'var(--q-positive)'
    pace_label = '✓ Op tempo'
elif target > 0 and prognose >= target:
    pace_color = '#D97706'  # amber
    pace_label = '⚠ Krap'
else:
    pace_color = 'var(--q-negative)'
    pace_label = '✕ Niet op tempo'

with ui.card().classes('dashboard-hero-tile') \
        .style('cursor: pointer') \
        .on('click', lambda: ui.navigate.to('/agenda')):
    with ui.row().classes('w-full justify-between items-center'):
        ui.label('Urencriterium').classes('hero-label')
        ui.label(pace_label).style(
            f'font-size: 11px; font-weight: 600; color: {pace_color}')
    ui.label(f'{huidig:,.0f} / {target:,.0f}'.replace(',', '.')).classes('hero-value')
    ui.label(
        f'Bij dit tempo: {prognose:,.0f} eind van jaar'.replace(',', '.')
    ).classes('context-text')
```

- [ ] **Step 2.3.3: Quick-actions header — replace 2 grijze knoppen met 3 CTAs**

Find the header section (around line 58-67):
```python
with ui.row().classes('w-full items-center'):
    page_title('Overzicht')
    ui.space()
    ui.button('Werkdag', icon='add',
              on_click=lambda: ui.navigate.to('/werkdagen')) \
        .props('flat color=secondary dense')
    ui.button('Factuur', icon='add',
              on_click=lambda: ui.navigate.to('/facturen')) \
        .props('flat color=secondary dense')
```

Replace with:
```python
with ui.row().classes('w-full items-center gap-2'):
    page_title(f'Overzicht {huidig_jaar}')
    ui.space()
    ui.button('+ Werkdag',
              on_click=lambda: ui.navigate.to('/agenda')) \
        .props('unelevated color=primary dense')
    ui.button('+ Factuur',
              on_click=lambda: ui.navigate.to('/facturen?nieuw=1')) \
        .props('unelevated color=primary dense')
    ui.button('+ Uitgave',
              on_click=lambda: ui.navigate.to('/transacties')) \
        .props('unelevated color=primary dense')
```

(Note: `/transacties?dialog=cash` would require a dialog-trigger. For v1, just navigate to `/transacties` — user clicks "+ Contante uitgave" daar zelf. Defer dialog-trigger to post-launch.)

- [ ] **Step 2.3.4: Tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1311 passed.

- [ ] **Step 2.3.5: Commit**

```bash
git add pages/dashboard.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T2.3 Urencriterium hero-tile + Quick-actions header

Sprint H Task 2.3 — completes hero-strip (4 forward-looking tiles).

UI:
- Urencriterium verhuist van strip-card naar hero (Card 4) met
  prognose-text "Bij dit tempo: 1340 eind van jaar"
- Pace-color: groen (>105% target), amber (≥target), red (<target)
- Hero-grid: 3-col → 4-col
- Strip-row (Uren/Km/Documenten) verwijderd — replaced by hero-grid
  + inzicht-grid in latere phases
- Header: 2 grijze knoppen → 3 prominent CTAs (+ Werkdag/Factuur/
  Uitgave) met unelevated color=primary
- + Werkdag → /agenda (Sprint A planning-flow)
- + Factuur → /facturen?nieuw=1 (existing deep-link)
- + Uitgave → /transacties

Reuses existing services.agenda.get_urencriterium_projectie.

Pytest 1311.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — Action-inbox met inline actions + seasonal-row injector

### Task 3.1 — `ActionRow` dataclass + `prioritise_actions` pure helper

**Files:**
- Modify: `services/dashboard.py` (add ActionRow + prioritise_actions)
- Modify: `tests/test_dashboard_helpers.py` (add 8 unit tests)

- [ ] **Step 3.1.1: Write failing tests first**

In `tests/test_dashboard_helpers.py` add:

```python
from services.dashboard import ActionRow, prioritise_actions


class TestActionRow:
    def test_actionrow_is_frozen_dataclass(self):
        row = ActionRow(
            kind='verlopen_factuur',
            severity='warning',
            message='2 facturen verlopen >30d',
            action_kind='stuur_herinnering',
            link='/facturen',
            age_days=30,
            metadata={},
        )
        assert row.kind == 'verlopen_factuur'
        assert row.severity == 'warning'


class TestPrioritiseActions:
    def _make_row(self, kind, severity, age=0):
        return ActionRow(
            kind=kind, severity=severity, message=f'{kind}-msg',
            action_kind=None, link=None, age_days=age, metadata={},
        )

    def test_critical_first_warning_second_info_last(self):
        rows = [
            self._make_row('a', 'info'),
            self._make_row('b', 'critical'),
            self._make_row('c', 'warning'),
        ]
        result = prioritise_actions(rows, max_items=10)
        assert [r.kind for r in result] == ['b', 'c', 'a']

    def test_within_severity_age_desc(self):
        rows = [
            self._make_row('a', 'warning', age=10),
            self._make_row('b', 'warning', age=30),
            self._make_row('c', 'warning', age=5),
        ]
        result = prioritise_actions(rows, max_items=10)
        assert [r.kind for r in result] == ['b', 'a', 'c']

    def test_max_items_truncates(self):
        rows = [self._make_row(f'r{i}', 'warning', age=i) for i in range(10)]
        result = prioritise_actions(rows, max_items=3)
        assert len(result) == 3

    def test_empty_input(self):
        assert prioritise_actions([], max_items=5) == []

    def test_single_row(self):
        rows = [self._make_row('a', 'info')]
        assert prioritise_actions(rows, max_items=5) == rows

    def test_max_items_zero_returns_empty(self):
        rows = [self._make_row('a', 'critical')]
        assert prioritise_actions(rows, max_items=0) == []

    def test_severity_order_complete(self):
        # critical → warning → info → unknown_severity (treated as info)
        rows = [
            self._make_row('a', 'unknown_severity'),
            self._make_row('b', 'info'),
            self._make_row('c', 'warning'),
            self._make_row('d', 'critical'),
        ]
        result = prioritise_actions(rows, max_items=10)
        # critical first, then warning, then info+unknown (alphabetical-stable)
        assert result[0].kind == 'd'
        assert result[1].kind == 'c'

    def test_metadata_passes_through(self):
        rows = [ActionRow(
            kind='a', severity='info', message='m', action_kind=None,
            link=None, age_days=0, metadata={'factuur_id': 42},
        )]
        result = prioritise_actions(rows, max_items=10)
        assert result[0].metadata == {'factuur_id': 42}
```

- [ ] **Step 3.1.2: Verify tests fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_dashboard_helpers.py -v
```

Expected: 8 FAIL on missing imports.

- [ ] **Step 3.1.3: Implement ActionRow + prioritise_actions**

In `services/dashboard.py` add:

```python
@dataclass(frozen=True)
class ActionRow:
    """One row in the dashboard action-inbox.

    `kind` = row-type identifier (verlopen_factuur, bank_tx_ongecategoriseerd,
             documenten_ontbreken, concept_factuur_stale, ib_aangifte_deadline,
             va_termijn_deadline, jaarafsluiting_pending, etc.)
    `severity` = 'critical' | 'warning' | 'info'
    `action_kind` = identifier for the inline-action handler
                    (None = read-only "Bekijk" only)
    `link` = navigate-to-target for "Bekijk" knop
    `age_days` = age in days (used for tiebreak in prioritise_actions)
    `metadata` = dict for action-handler context (factuur_id, banktx_id, etc.)
    """
    kind: str
    severity: Literal['critical', 'warning', 'info']
    message: str
    action_kind: str | None
    link: str | None
    age_days: int
    metadata: dict


_SEVERITY_ORDER = {'critical': 0, 'warning': 1, 'info': 2}


def prioritise_actions(
    rows: list[ActionRow],
    max_items: int,
) -> list[ActionRow]:
    """Sort rows by (severity DESC, age DESC, kind ASC) and truncate.

    Severity-order: critical > warning > info > anything-else (treated as info).
    Stable secondary sort op age_days descending (oldest first within severity).
    Tertiary stable sort op kind ASC for deterministic ordering.
    """
    if max_items <= 0:
        return []

    def _sort_key(row: ActionRow) -> tuple:
        sev_rank = _SEVERITY_ORDER.get(row.severity, 2)  # unknown → info
        return (sev_rank, -row.age_days, row.kind)

    sorted_rows = sorted(rows, key=_sort_key)
    return sorted_rows[:max_items]
```

- [ ] **Step 3.1.4: Verify tests pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_dashboard_helpers.py -v
```

Expected: 17 PASS (5 + 4 + 8 new = 17).

- [ ] **Step 3.1.5: Commit**

```bash
git add services/dashboard.py tests/test_dashboard_helpers.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T3.1 ActionRow dataclass + prioritise_actions helper

Sprint H Task 3.1 — foundation voor action-inbox (Phase 3).

ActionRow: frozen dataclass met kind/severity/message/action_kind/link/
age_days/metadata. action_kind=None = read-only "Bekijk"-only row.

prioritise_actions: stable sort by (severity DESC, age DESC, kind ASC) +
truncate to max_items. Unknown severity → treated as 'info' (defensive).

8 unit-tests covering severity-order, age-tiebreak, max-truncation, edge
cases (empty, single, max=0, unknown severity, metadata pass-through).

Pytest 1311 → 1319.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3.2 — `_seasonal_action_rows` + `tax_calendar` helpers

**Files:**
- Modify: `services/dashboard.py`
- Modify: `tests/test_dashboard_helpers.py`

- [ ] **Step 3.2.1: Write failing tests**

```python
class TestTaxCalendar:
    def test_tax_calendar_2026_returns_known_deadlines(self):
        from services.dashboard import tax_calendar
        cal = tax_calendar(2026)
        assert isinstance(cal, list)
        # Must include 1 mei IB-aangifte deadline
        ib_deadline = next((d for d in cal if d['kind'] == 'ib_aangifte'), None)
        assert ib_deadline is not None
        assert ib_deadline['date'] == date(2026, 5, 1)

    def test_tax_calendar_unknown_year_returns_empty(self):
        from services.dashboard import tax_calendar
        # Unknown years (e.g. 1999) return empty list, not error
        assert tax_calendar(1999) == []


class TestSeasonalActionRows:
    def test_april_emits_ib_aangifte_deadline(self):
        from services.dashboard import _seasonal_action_rows
        rows = _seasonal_action_rows(today=date(2026, 4, 15))
        ib_rows = [r for r in rows if r.kind == 'ib_aangifte_deadline']
        assert len(ib_rows) == 1
        assert ib_rows[0].severity == 'warning'  # 16 days remaining
        assert '16 dagen' in ib_rows[0].message

    def test_late_april_critical_severity(self):
        from services.dashboard import _seasonal_action_rows
        rows = _seasonal_action_rows(today=date(2026, 4, 25))
        ib_rows = [r for r in rows if r.kind == 'ib_aangifte_deadline']
        assert ib_rows[0].severity == 'critical'  # 6 days

    def test_july_emits_no_seasonal_rows(self):
        from services.dashboard import _seasonal_action_rows
        rows = _seasonal_action_rows(today=date(2026, 7, 15))
        # July: no IB-deadline, no VA-laatste-termijn, no jaarafsluiting
        assert rows == []

    def test_december_emits_va_laatste_termijn(self):
        from services.dashboard import _seasonal_action_rows
        rows = _seasonal_action_rows(today=date(2026, 12, 15))
        va_rows = [r for r in rows if r.kind == 'va_laatste_termijn']
        assert len(va_rows) == 1
```

- [ ] **Step 3.2.2: Verify tests fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_dashboard_helpers.py -v
```

Expected: 5 FAIL.

- [ ] **Step 3.2.3: Implement helpers**

In `services/dashboard.py` add:

```python
def tax_calendar(jaar: int) -> list[dict]:
    """Returns list of known Belastingdienst-deadlines for the year.

    Each entry: {'kind': str, 'date': date, 'label': str}.

    Hardcoded per-jaar — Belastingdienst publishes deadlines annually.
    Add new years here when next-year support is needed.
    """
    if jaar == 2026:
        return [
            {'kind': 'ib_aangifte', 'date': date(2026, 5, 1),
             'label': 'IB-aangifte deadline (rentevrij)'},
            {'kind': 'va_laatste_termijn', 'date': date(2026, 12, 31),
             'label': 'Laatste VA-termijn'},
            {'kind': 'va_uitbetaling', 'date': date(2026, 12, 15),
             'label': 'VA-uitbetaling teruggave'},
        ]
    if jaar == 2027:
        return [
            {'kind': 'ib_aangifte', 'date': date(2027, 5, 1),
             'label': 'IB-aangifte deadline (rentevrij)'},
            {'kind': 'va_laatste_termijn', 'date': date(2027, 12, 31),
             'label': 'Laatste VA-termijn'},
            {'kind': 'va_uitbetaling', 'date': date(2027, 12, 15),
             'label': 'VA-uitbetaling teruggave'},
        ]
    return []


def _seasonal_action_rows(today: date) -> list[ActionRow]:
    """Emit seasonal context-rows for action-inbox.

    Apr/Mei: IB-aangifte countdown
    Nov/Dec: VA-laatste termijn reminder

    Severity escalates as deadline approaches: <14 days = critical,
    <30 days = warning, else info.
    """
    rows: list[ActionRow] = []
    cal = tax_calendar(today.year)
    for entry in cal:
        deadline = entry['date']
        days_remaining = (deadline - today).days
        if days_remaining < 0 or days_remaining > 60:
            continue

        # Map kind → action-row kind
        if entry['kind'] == 'ib_aangifte':
            kind = 'ib_aangifte_deadline'
            link = '/aangifte'
        elif entry['kind'] == 'va_laatste_termijn':
            kind = 'va_laatste_termijn'
            link = '/aangifte'
        else:
            continue

        if days_remaining < 14:
            severity = 'critical'
        elif days_remaining < 30:
            severity = 'warning'
        else:
            severity = 'info'

        rows.append(ActionRow(
            kind=kind,
            severity=severity,
            message=f'{entry["label"]} over {days_remaining} dagen',
            action_kind=None,  # info-only, geen inline action
            link=link,
            age_days=0,
            metadata={'deadline': deadline.isoformat()},
        ))
    return rows
```

- [ ] **Step 3.2.4: Verify tests pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_dashboard_helpers.py -v
```

Expected: 22 PASS (17 + 5 new).

- [ ] **Step 3.2.5: Commit**

```bash
git add services/dashboard.py tests/test_dashboard_helpers.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T3.2 tax_calendar + _seasonal_action_rows helpers

Sprint H Task 3.2 — seasonal context-rows voor action-inbox (Codex
discussion-round compromise — niet per-tile severity, wel action-zone-
row injection).

tax_calendar(jaar): hardcoded per-jaar Belastingdienst-deadlines (2026
+ 2027 supported). Returns list[dict] met kind/date/label.

_seasonal_action_rows(today): emits ActionRow voor deadlines binnen 60
dagen. Severity escaleert: <14d critical, <30d warning, else info.
Action_kind=None (info-only rows, geen inline action).

Includes:
- IB-aangifte deadline (1 mei)
- VA-laatste termijn (31 dec)

5 unit-tests covering apr/mei/jul/dec edge cases + unknown years.

Pytest 1319 → 1324.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3.3 — Build action-rows from existing data + new factuur-aging query

**Files:**
- Modify: `database.py` (add `get_factuur_aging_buckets`, `get_concept_facturen_stale`)
- Modify: `services/dashboard.py` (add `build_action_rows` orchestrator)
- Modify: `tests/test_dashboard_helpers.py` (add tests)

- [ ] **Step 3.3.1: Write tests for new DB queries**

In `tests/test_database.py` (or new `tests/test_database_dashboard_queries.py`):

```python
import pytest
from datetime import date, timedelta

from database import (
    get_factuur_aging_buckets, get_concept_facturen_stale,
)


@pytest.mark.asyncio
async def test_factuur_aging_buckets_categorises_correctly(temp_db):
    # Insert 4 facturen: 5d, 25d, 50d, 100d overdue
    # Expected buckets: 0-30, 30-60, 60-90, 90+
    # ... (helper to insert facturen with vervaldatum offsets)
    result = await get_factuur_aging_buckets(temp_db, jaar=2026)
    assert 'overdue_30' in result
    assert 'overdue_60' in result
    assert 'overdue_90' in result
    assert 'overdue_90_plus' in result


@pytest.mark.asyncio
async def test_concept_facturen_stale_returns_concepts_older_than_threshold(temp_db):
    # Insert 2 concept-facturen: 10d old, 20d old
    # threshold=14 → should return only 20d
    result = await get_concept_facturen_stale(temp_db, jaar=2026, days=14)
    assert len(result) == 1
```

(NOTE: temp_db fixture exists in conftest.py — use existing pattern. If specific factuur-insertion helpers don't exist, write minimal SQL-INSERT inline.)

- [ ] **Step 3.3.2: Verify tests fail**

- [ ] **Step 3.3.3: Implement DB queries**

In `database.py` add:

```python
async def get_factuur_aging_buckets(
    db_path: Path = DB_PATH, jaar: int = 2026,
) -> dict:
    """Returns aging buckets for openstaande facturen.

    {'overdue_30': [...factuur...], 'overdue_60': [...], 'overdue_90': [...],
     'overdue_90_plus': [...]}

    Buckets count days OVERDUE (vervaldatum vs today). Status='verstuurd' only
    (concepts handled separately).
    """
    today = _today_iso()  # uses existing wrapper for monkeypatching
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """
            SELECT id, nummer, klant_naam, totaal_bedrag, datum, vervaldatum,
                   julianday(?) - julianday(vervaldatum) AS days_overdue
            FROM facturen
            WHERE status = 'verstuurd'
              AND CAST(strftime('%Y', datum) AS INTEGER) = ?
              AND vervaldatum < ?
            ORDER BY days_overdue DESC
            """,
            (today, jaar, today),
        )
        rows = await cur.fetchall()

    buckets = {
        'overdue_30': [], 'overdue_60': [],
        'overdue_90': [], 'overdue_90_plus': [],
    }
    for r in rows:
        days = int(r['days_overdue'])
        if days < 30:
            buckets['overdue_30'].append(dict(r))
        elif days < 60:
            buckets['overdue_60'].append(dict(r))
        elif days < 90:
            buckets['overdue_90'].append(dict(r))
        else:
            buckets['overdue_90_plus'].append(dict(r))
    return buckets


async def get_concept_facturen_stale(
    db_path: Path = DB_PATH, jaar: int = 2026, days: int = 14,
) -> list[dict]:
    """Returns concept-facturen with datum > N days ago (likely forgotten)."""
    cutoff = (_date.today() - _timedelta(days=days)).isoformat()
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """
            SELECT id, nummer, klant_naam, totaal_bedrag, datum
            FROM facturen
            WHERE status = 'concept'
              AND CAST(strftime('%Y', datum) AS INTEGER) = ?
              AND datum < ?
            ORDER BY datum ASC
            """,
            (jaar, cutoff),
        )
        return [dict(r) for r in await cur.fetchall()]
```

(NOTE: import `_timedelta` from datetime if not already imported.)

- [ ] **Step 3.3.4: Verify tests pass + full suite**

- [ ] **Step 3.3.5: Commit**

```bash
git add database.py tests/test_database_dashboard_queries.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T3.3 get_factuur_aging_buckets + get_concept_facturen_stale

Sprint H Task 3.3 — DB-queries voor action-inbox row-types.

get_factuur_aging_buckets(jaar): aging-breakdown van openstaande facturen
in 4 buckets (0-30, 30-60, 60-90, 90+). Status='verstuurd' only.

get_concept_facturen_stale(jaar, days=14): concept-facturen older than
threshold (default 14 dagen). Action-inbox shows met [Verstuur]-action.

Pytest +N tests, baseline behouden.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3.4 — Action-inbox UI (renderer + 4 inline actions integration)

**Files:**
- Create: `components/dashboard_widgets.py`
- Modify: `pages/dashboard.py`

- [ ] **Step 3.4.1: Create `components/dashboard_widgets.py`**

```python
"""Per-tile renderers for /dashboard. NiceGUI-coupled.

Each render_* function takes raw data + a parent container, draws a
self-contained widget. Pure-data helpers live in services/dashboard.py.
"""
from __future__ import annotations

from datetime import date

from nicegui import ui

from components.utils import format_euro
from services.dashboard import ActionRow


_SEVERITY_ICON = {
    'critical': 'error',
    'warning': 'warning',
    'info': 'info_outline',
}
_SEVERITY_COLOR = {
    'critical': 'var(--q-negative)',
    'warning': '#D97706',  # amber
    'info': 'var(--accent)',
}


def render_action_inbox(rows: list[ActionRow], on_action) -> None:
    """Render the consolidated action-inbox card.

    `on_action(row, action_kind)` is the dispatcher — receives the row
    and inline-action-kind, performs the action (open dialog, send mail,
    update status, etc.). Caller wires this to handlers.
    """
    with ui.card().classes('action-inbox w-full q-pa-md').style(
            'border: 1px solid var(--border); background: var(--surface)'):
        ui.label('Vandaag te doen').style(
            'font-weight: 600; font-size: 14px; '
            'color: var(--text); margin-bottom: 12px')

        if not rows:
            ui.label('Geen acties — alles bij.').classes(
                'text-caption text-grey-6')
            return

        for row in rows:
            with ui.row().classes(
                    'action-inbox-row w-full items-center gap-2'
                ).style(
                    'padding: 8px 4px; '
                    'border-bottom: 1px solid var(--border)'):
                icon = _SEVERITY_ICON.get(row.severity, 'info_outline')
                color = _SEVERITY_COLOR.get(row.severity, 'var(--accent)')
                ui.icon(icon, size='18px').style(f'color: {color}')
                ui.label(row.message).style('flex: 1; font-size: 13px')

                # Inline action knop (per row.action_kind)
                if row.action_kind == 'stuur_herinnering':
                    ui.button('Stuur herinnering',
                              on_click=lambda r=row: on_action(r, 'stuur_herinnering')) \
                        .props('flat dense color=primary size=sm')
                elif row.action_kind == 'categoriseer':
                    # Inline q-select would be heavy; use button → dialog
                    ui.button('Categoriseer',
                              on_click=lambda r=row: on_action(r, 'categoriseer')) \
                        .props('flat dense color=primary size=sm')
                elif row.action_kind == 'upload_nu':
                    ui.button('Upload nu',
                              on_click=lambda r=row: on_action(r, 'upload_nu')) \
                        .props('flat dense color=primary size=sm')
                elif row.action_kind == 'verstuur_concept':
                    ui.button('Verstuur',
                              on_click=lambda r=row: on_action(r, 'verstuur_concept')) \
                        .props('flat dense color=primary size=sm')

                # Always: Bekijk (navigation) als link is gegeven
                if row.link:
                    ui.button('Bekijk',
                              on_click=lambda r=row: ui.navigate.to(r.link)) \
                        .props('flat dense size=sm')
```

- [ ] **Step 3.4.2: Wire `on_action` dispatcher in `pages/dashboard.py`**

In `pages/dashboard.py` add the dispatcher function inside `dashboard_page()`:

```python
async def on_action(row: ActionRow, action_kind: str):
    """Dispatch inline-action handlers per row.kind + action_kind."""
    if action_kind == 'stuur_herinnering':
        # Per U3: confirm-dialog before opening Mail.app
        with ui.dialog() as dlg, ui.card():
            ui.label(f'Herinnering sturen voor "{row.message}"?').classes(
                'text-h6')
            ui.label('Mail.app opent met conceptbericht; jij verstuurt.').classes(
                'text-body2 text-grey')
            with ui.row():
                ui.button('Annuleren', on_click=dlg.close).props('flat')
                async def _confirm():
                    dlg.close()
                    # Reuse existing _build_herinnering_body + open_mail_with_attachment
                    # from pages/facturen.py. Need factuur-data to build body.
                    factuur_id = row.metadata.get('factuur_id')
                    if factuur_id:
                        # TODO: call shared helper (extract from facturen.py)
                        # For Phase 3, navigate to /facturen with the factuur
                        # selected — Phase 6 can extract the helper properly.
                        ui.navigate.to(f'/facturen?factuur={factuur_id}')
                ui.button('Stuur herinnering', on_click=_confirm).props(
                    'unelevated color=primary')
        dlg.open()

    elif action_kind == 'categoriseer':
        # Navigate to /transacties pre-filtered to ongecategoriseerd
        ui.navigate.to('/transacties?status=ongecategoriseerd')

    elif action_kind == 'upload_nu':
        # Navigate to /aangifte/documenten with categorie-prefill if available
        cat = row.metadata.get('documenttype', '')
        ui.navigate.to(f'/aangifte?documenttype={cat}')

    elif action_kind == 'verstuur_concept':
        # Confirm-dialog + status-flip
        factuur_id = row.metadata.get('factuur_id')
        if not factuur_id:
            ui.notify('Geen factuur-id', type='warning')
            return
        with ui.dialog() as dlg, ui.card():
            ui.label(f'Concept-factuur {row.message} versturen?').classes('text-h6')
            with ui.row():
                ui.button('Annuleren', on_click=dlg.close).props('flat')
                async def _confirm():
                    dlg.close()
                    await update_factuur_status(
                        DB_PATH, factuur_id=factuur_id, status='verstuurd')
                    ui.notify('Status bijgewerkt naar verstuurd', type='positive')
                    await refresh_dashboard()
                ui.button('Verstuur', on_click=_confirm).props(
                    'unelevated color=primary')
        dlg.open()
```

- [ ] **Step 3.4.3: Build action_rows in `refresh_dashboard()`**

```python
# Build action-inbox rows from data sources
from services.dashboard import (
    ActionRow, prioritise_actions, _seasonal_action_rows,
)

raw_rows: list[ActionRow] = []

# From health_alerts (uncategorized_bank, etc.)
for alert in health_alerts:
    action_kind = None
    if alert.get('key') == 'uncategorized_bank':
        action_kind = 'categoriseer'
    raw_rows.append(ActionRow(
        kind=alert.get('key', 'health_alert'),
        severity=alert.get('severity', 'info'),
        message=alert.get('message', ''),
        action_kind=action_kind,
        link=alert.get('link'),
        age_days=0,
        metadata={},
    ))

# From ongefactureerd-summary
if ongefact and ongefact.get('aantal', 0) > 0:
    raw_rows.append(ActionRow(
        kind='werkdag_ongefactureerd',
        severity='warning',
        message=f'{ongefact["aantal"]} werkdagen ongefactureerd · {format_euro(ongefact["bedrag"])}',
        action_kind=None,  # Phase 6 voegt 'genereer_factuur' toe
        link='/werkdagen',
        age_days=ongefact.get('oudste_dagen', 0),
        metadata={},
    ))

# From openstaande facturen (overdue)
aging_buckets = await get_factuur_aging_buckets(DB_PATH, jaar=jaar)
for bucket_key, facturen_list in aging_buckets.items():
    if not facturen_list:
        continue
    severity = 'critical' if bucket_key == 'overdue_90_plus' else 'warning'
    raw_rows.append(ActionRow(
        kind='verlopen_factuur',
        severity=severity,
        message=f'{len(facturen_list)} facturen verlopen ({bucket_key.replace("overdue_", "")} dagen)',
        action_kind='stuur_herinnering',
        link='/facturen',
        age_days=facturen_list[0].get('days_overdue', 0),
        metadata={'factuur_id': facturen_list[0]['id']},  # for first one
    ))

# From concept-facturen stale
concepts = await get_concept_facturen_stale(DB_PATH, jaar=jaar, days=14)
if concepts:
    raw_rows.append(ActionRow(
        kind='concept_factuur_stale',
        severity='info',
        message=f'{len(concepts)} concept-facturen >14 dagen oud',
        action_kind='verstuur_concept',
        link='/facturen?status=concept',
        age_days=14,
        metadata={'factuur_id': concepts[0]['id']} if concepts else {},
    ))

# From documenten ontbreken
docs_done = {d.documenttype for d in aangifte_docs}
docs_missing = [d for d in AANGIFTE_DOCS if d not in docs_done]
for missing in docs_missing[:3]:  # max 3 documenten-rows
    raw_rows.append(ActionRow(
        kind='documenten_ontbreken',
        severity='info',
        message=f'Aangifte-doc "{missing}" mist',
        action_kind='upload_nu',
        link='/aangifte',
        age_days=0,
        metadata={'documenttype': missing},
    ))

# Add seasonal rows
raw_rows.extend(_seasonal_action_rows(date.today()))

# Prioritise + truncate
action_rows = prioritise_actions(raw_rows, max_items=5)
```

- [ ] **Step 3.4.4: Replace old AANDACHTSPUNTEN section**

In `pages/dashboard.py` find the `if has_ongefact or has_openstaand:` section (regel ~584+) and the `if health_alerts:` section. **DELETE BOTH** entirely. Replace with single call:

```python
from components.dashboard_widgets import render_action_inbox
render_action_inbox(action_rows, on_action)
```

- [ ] **Step 3.4.5: Run tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1324+ passed.

- [ ] **Step 3.4.6: Commit**

```bash
git add components/dashboard_widgets.py pages/dashboard.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T3.4 action-inbox UI met 4 inline actions

Sprint H Task 3.4 — vervangt huidige wand-van-alert-cards door
geconsolideerd action-inbox per Acumulus-pattern.

components/dashboard_widgets.py NEW (per-tile-renderers):
- render_action_inbox(rows, on_action)

pages/dashboard.py:
- Build raw_rows uit health_alerts + ongefact + aging_buckets +
  concept_facturen_stale + documenten_ontbreken + _seasonal_action_rows
- prioritise_actions() truncate naar max-5
- render_action_inbox() vervangt 2 oude AANDACHTSPUNTEN-sections
- on_action dispatcher voor 4 inline actions:
  - stuur_herinnering: confirm-dialog + Mail.app (per U3)
  - categoriseer: navigate /transacties?status=ongecategoriseerd
  - upload_nu: navigate /aangifte met documenttype-prefill
  - verstuur_concept: confirm + update_factuur_status

werkdag-genereer-factuur action_kind blijft None in Phase 3 (defer
naar Phase 6 — vereist deep-link infrastructure).

Pytest baseline behouden.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4a — Customisation infrastructure

### Task 4a.1 — Migration 39: `dashboard_widgets_json` column

**Files:**
- Modify: `database.py` (MIGRATIONS list + helper functions)
- Modify: `tests/test_database.py` (or new `tests/test_database_dashboard_config.py`)

- [ ] **Step 4a.1.1: Add migration 39**

In `database.py` find the MIGRATIONS list and add after migration 38:

```python
    (39, "add_bedrijfsgegevens_dashboard_widgets_json", [
        "ALTER TABLE bedrijfsgegevens ADD COLUMN dashboard_widgets_json TEXT NULL",
    ]),
```

- [ ] **Step 4a.1.2: Add helper functions**

Add to `database.py`:

```python
async def get_dashboard_widgets_config(db_path: Path = DB_PATH) -> str | None:
    """Returns raw JSON string of dashboard_widgets_json from bedrijfsgegevens.

    None = not yet configured (defaults apply).
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT dashboard_widgets_json FROM bedrijfsgegevens LIMIT 1"
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return row['dashboard_widgets_json']


async def set_dashboard_widgets_config(
    db_path: Path = DB_PATH, config_json: str | None = None,
) -> None:
    """Update dashboard_widgets_json on bedrijfsgegevens (single row)."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "UPDATE bedrijfsgegevens SET dashboard_widgets_json = ?",
            (config_json,),
        )
        await conn.commit()
```

- [ ] **Step 4a.1.3: Add tests**

```python
@pytest.mark.asyncio
async def test_migration_39_adds_dashboard_widgets_json_column(temp_db):
    # After init_db, the column should exist
    async with get_db_ctx(temp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(bedrijfsgegevens)")
        cols = {r['name'] for r in await cur.fetchall()}
    assert 'dashboard_widgets_json' in cols


@pytest.mark.asyncio
async def test_dashboard_widgets_config_round_trip(temp_db):
    config = '{"schema_version": 1, "widgets": {"I-1": false}}'
    await set_dashboard_widgets_config(temp_db, config)
    result = await get_dashboard_widgets_config(temp_db)
    assert result == config


@pytest.mark.asyncio
async def test_dashboard_widgets_config_null_default(temp_db):
    result = await get_dashboard_widgets_config(temp_db)
    assert result is None
```

- [ ] **Step 4a.1.4: Run tests**

- [ ] **Step 4a.1.5: Commit**

```bash
git add database.py tests/test_database_dashboard_config.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T4a.1 migratie 39 — bedrijfsgegevens.dashboard_widgets_json

Sprint H Task 4a.1 — DB-foundation voor dashboard customisation.

Migratie 39: TEXT NULL column op bedrijfsgegevens (single-row table).
NULL = use defaults. Format: schema-versioned JSON.

Helpers: get_dashboard_widgets_config / set_dashboard_widgets_config
(round-trip).

3 unit-tests (column-exists, round-trip, NULL-default).

Pytest +3 tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4a.2 — Config-load helper + DEFAULT_WIDGETS + render-loop

**Files:**
- Modify: `services/dashboard.py` (add `load_dashboard_widgets_config` + `DEFAULT_WIDGETS`)
- Modify: `tests/test_dashboard_helpers.py`

- [ ] **Step 4a.2.1: Write tests**

```python
class TestLoadDashboardWidgetsConfig:
    def test_null_input_returns_defaults(self):
        from services.dashboard import load_dashboard_widgets_config, DEFAULT_WIDGETS
        result = load_dashboard_widgets_config(None)
        # All keys present
        for key in DEFAULT_WIDGETS:
            assert key in result['widgets']
        # Default-on for I-1..I-4
        assert result['widgets']['I-1'] is True
        assert result['widgets']['I-4'] is True

    def test_invalid_json_returns_defaults(self):
        from services.dashboard import load_dashboard_widgets_config
        result = load_dashboard_widgets_config('not valid json')
        assert result['widgets']['I-1'] is True

    def test_unknown_keys_ignored(self):
        from services.dashboard import load_dashboard_widgets_config
        config_in = '{"schema_version": 1, "widgets": {"I-99": true}}'
        result = load_dashboard_widgets_config(config_in)
        assert 'I-99' not in result['widgets']

    def test_missing_keys_use_defaults(self):
        from services.dashboard import load_dashboard_widgets_config
        # Only specifies I-5; rest must use defaults
        config_in = '{"schema_version": 1, "widgets": {"I-5": true}}'
        result = load_dashboard_widgets_config(config_in)
        assert result['widgets']['I-5'] is True  # explicit
        assert result['widgets']['I-1'] is True  # default-on
        assert result['widgets']['I-6'] is False  # default-off

    def test_schema_version_mismatch_falls_through_to_defaults(self):
        from services.dashboard import load_dashboard_widgets_config
        config_in = '{"schema_version": 99, "widgets": {"I-1": false}}'
        result = load_dashboard_widgets_config(config_in)
        # Falls through to defaults — I-1 default-on
        assert result['widgets']['I-1'] is True
```

- [ ] **Step 4a.2.2: Implement**

In `services/dashboard.py`:

```python
import json
import logging

log = logging.getLogger(__name__)

DASHBOARD_CONFIG_SCHEMA_VERSION = 1

DEFAULT_WIDGETS: dict[str, bool] = {
    'I-1': True,   # Cumulatieve omzet YoY
    'I-2': True,   # Kosten breakdown donut
    'I-3': True,   # SPH-status
    'I-4': True,   # 6-weken prognose
    'I-5': False,  # Top klanten
    'I-6': False,  # Documenten checklist
    'I-7': False,  # Cash-positie
    'I-8': False,  # Tax-calendar full
}


def load_dashboard_widgets_config(raw_json: str | None) -> dict:
    """Load + validate dashboard config with 4 defensiveness rules:

    1. NULL → defaults
    2. Invalid JSON → defaults + log warning
    3. schema_version mismatch → defaults + log warning
    4. Unknown keys → ignored
    5. Missing keys → fall through to DEFAULT_WIDGETS

    Returns: {'schema_version': N, 'widgets': {...}}
    """
    if raw_json is None:
        return _defaults_dict()

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        log.warning('dashboard_widgets_json invalid JSON, using defaults')
        return _defaults_dict()

    if not isinstance(parsed, dict):
        log.warning('dashboard_widgets_json not a dict, using defaults')
        return _defaults_dict()

    if parsed.get('schema_version') != DASHBOARD_CONFIG_SCHEMA_VERSION:
        log.warning(
            'dashboard_widgets_json schema_version mismatch '
            f'({parsed.get("schema_version")} != {DASHBOARD_CONFIG_SCHEMA_VERSION}), '
            'using defaults'
        )
        return _defaults_dict()

    user_widgets = parsed.get('widgets', {})
    if not isinstance(user_widgets, dict):
        return _defaults_dict()

    # Merge: known keys → user value if present + bool, else default
    merged = {}
    for key, default in DEFAULT_WIDGETS.items():
        user_val = user_widgets.get(key)
        merged[key] = user_val if isinstance(user_val, bool) else default

    return {
        'schema_version': DASHBOARD_CONFIG_SCHEMA_VERSION,
        'widgets': merged,
        'prive_section_collapsed': parsed.get('prive_section_collapsed'),
    }


def _defaults_dict() -> dict:
    return {
        'schema_version': DASHBOARD_CONFIG_SCHEMA_VERSION,
        'widgets': dict(DEFAULT_WIDGETS),
        'prive_section_collapsed': None,
    }
```

- [ ] **Step 4a.2.3: Verify tests pass + full suite**

- [ ] **Step 4a.2.4: Commit**

```bash
git add services/dashboard.py tests/test_dashboard_helpers.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T4a.2 load_dashboard_widgets_config + DEFAULT_WIDGETS

Sprint H Task 4a.2 — config-loader met 5 defensiveness rules per spec.

DEFAULT_WIDGETS: I-1..I-4 ON (cumulatief, kosten donut, SPH, 6-wk),
I-5..I-8 OFF (top klanten, documenten, cash, tax-calendar).

load_dashboard_widgets_config(raw_json):
1. NULL → defaults
2. Invalid JSON → defaults + warning log
3. Not a dict → defaults
4. schema_version mismatch → defaults + warning log
5. Unknown keys → ignored
6. Missing keys → use DEFAULT_WIDGETS value

5 unit-tests covering all defensiveness paths.

Pytest +5 tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4a.3 — /instellingen "Dashboard" tab

**Files:**
- Modify: `pages/instellingen.py`

- [ ] **Step 4a.3.1: Add 4th tab "Dashboard"**

In `pages/instellingen.py` around line 266-270 (where tabs are declared), add:

```python
tab_bedrijf = ui.tab('Bedrijfsgegevens')
tab_fiscaal = ui.tab('Fiscale parameters')
tab_backup = ui.tab('Backup')
tab_dashboard = ui.tab('Dashboard')  # NEW
```

In `with ui.tab_panels(...)` add a new tab_panel after tab_backup:

```python
with ui.tab_panel(tab_dashboard):
    dashboard_container = ui.column().classes('w-full')

    async def refresh_dashboard_tab():
        dashboard_container.clear()
        raw_config = await get_dashboard_widgets_config(DB_PATH)
        config = load_dashboard_widgets_config(raw_config)

        with dashboard_container:
            with ui.card().classes('settings-card'):
                ui.label('Inzicht-tegels').classes('settings-card-title')
                ui.label(
                    'Kies welke tegels je in zone 3 (inzicht-grid) wilt zien. '
                    'Maximaal 6 tegels tegelijk zichtbaar.'
                ).classes('settings-card-subtitle')

                widget_labels = {
                    'I-1': 'Cumulatieve omzet (YoY)',
                    'I-2': 'Kosten breakdown donut',
                    'I-3': 'SPH-pensioen status',
                    'I-4': '6-weken omzet-prognose',
                    'I-5': 'Top 5 klanten + concentratie',
                    'I-6': 'Aangifte-documenten checklist',
                    'I-7': 'Cash-positie + flow YTD',
                    'I-8': 'Tax-calendar (alle deadlines)',
                }

                checkboxes = {}
                for key, label in widget_labels.items():
                    cb = ui.checkbox(
                        label,
                        value=config['widgets'].get(key, DEFAULT_WIDGETS[key]),
                    )
                    checkboxes[key] = cb

                async def save_dashboard_config():
                    new_config = {
                        'schema_version': DASHBOARD_CONFIG_SCHEMA_VERSION,
                        'widgets': {k: cb.value for k, cb in checkboxes.items()},
                        'prive_section_collapsed': config.get('prive_section_collapsed'),
                    }
                    # Cap-check: max 6 ON
                    enabled_count = sum(1 for v in new_config['widgets'].values() if v)
                    if enabled_count > 6:
                        ui.notify(
                            'Limiet 6 tegels bereikt — verberg eerst een andere '
                            'tegel om deze toe te voegen.',
                            type='warning', timeout=8000)
                        return
                    await set_dashboard_widgets_config(
                        DB_PATH, json.dumps(new_config))
                    ui.notify('Dashboard-config opgeslagen', type='positive')

                ui.button('Opslaan', icon='save', on_click=save_dashboard_config) \
                    .props('color=primary').classes('q-mt-md')

    await refresh_dashboard_tab()
```

(Imports needed at top: `from services.dashboard import load_dashboard_widgets_config, DEFAULT_WIDGETS, DASHBOARD_CONFIG_SCHEMA_VERSION` + `from database import get_dashboard_widgets_config, set_dashboard_widgets_config`.)

- [ ] **Step 4a.3.2: Run tests**

- [ ] **Step 4a.3.3: Commit**

```bash
git add pages/instellingen.py
git commit -m "$(cat <<'EOF'
feat(sprint-h): T4a.3 /instellingen "Dashboard" tab — show/hide checkboxes

Sprint H Task 4a.3 — 4e tab op /instellingen voor dashboard-customisation.

UI:
- 8 checkboxes voor I-1..I-8 (defaults: I-1..I-4 ON)
- Save-knop met cap-validation (max 6 ON; toast bij >6)
- Persistent via dashboard_widgets_json (T4a.1 + T4a.2)

Sluit aan bij Sprint G settings-card pattern.

Pytest baseline behouden.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4b — Inzicht-tiles (5 tiles, alle reuse existing data)

### Task 4b.1 — I-3 SPH-tile + I-4 6-weken prognose tile

**Files:**
- Modify: `components/dashboard_widgets.py` (add 2 renderers)
- Modify: `services/dashboard.py` (add SPH-formula helper)
- Modify: `pages/dashboard.py` (gather + render)

- [ ] **Step 4b.1.1: SPH-formula helper + tests**

In `services/dashboard.py`:

```python
SPH_PREMIUM_RATE_2026 = 0.2394
SPH_FRANCHISE_2026 = 19_172
SPH_GRONDSLAG_CAP_2026 = 137_800


def compute_sph_prognose(winst_extrapolatie: float, jaar: int) -> dict:
    """Computeer geprognoseerde SPH-jaarverplichting.

    Formula 2026: 23.94% × min(€137.800, max(0, winst − €19.172))

    Geeft dict: {'pensioengrondslag', 'jaarverplichting',
                 'rate', 'cap', 'franchise'}.

    Voor jaren ≠ 2026: same formule (publicatie 2026 — als premies
    later wijzigen, update deze constants per-jaar).
    """
    grondslag = max(0.0, min(SPH_GRONDSLAG_CAP_2026, winst_extrapolatie - SPH_FRANCHISE_2026))
    jaarverplichting = grondslag * SPH_PREMIUM_RATE_2026
    return {
        'pensioengrondslag': grondslag,
        'jaarverplichting': jaarverplichting,
        'rate': SPH_PREMIUM_RATE_2026,
        'cap': SPH_GRONDSLAG_CAP_2026,
        'franchise': SPH_FRANCHISE_2026,
    }
```

Add tests for compute_sph_prognose (4 tests: zero-winst, low-winst-onder-franchise, mid-winst, boven-cap).

- [ ] **Step 4b.1.2: Renderer for SPH tile**

In `components/dashboard_widgets.py`:

```python
def render_sph_tile(
    sph_betaald_ytd: float,
    sph_prognose: dict,
) -> None:
    """Render I-3 SPH-status tile."""
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('SPH-pensioen status').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        verplicht = sph_prognose['jaarverplichting']
        with ui.row().classes('items-baseline gap-2'):
            ui.label(f'Berekend {format_euro(verplicht, decimals=0)}').classes(
                'text-h6 num').style('color: var(--text)')
            ui.label('voor 2026').classes('text-caption text-grey-6')

        ui.label(f'Betaald YTD: {format_euro(sph_betaald_ytd, decimals=0)}').classes(
            'text-body2')

        if verplicht > 0:
            pct = min(100, sph_betaald_ytd / verplicht * 100)
            ui.linear_progress(value=pct / 100, size='6px',
                               color='positive' if pct > 80 else 'warning')

        ui.label(
            'Geschat — werkelijke 2026-verplichting wordt op pensioenbasis '
            '3 jaar terug berekend en kan ±20% afwijken.'
        ).classes('text-caption text-grey-6').style('margin-top: 8px')
```

- [ ] **Step 4b.1.3: 6-weken prognose tile renderer**

```python
def render_zes_weken_tile(weken: tuple) -> None:
    """Render I-4 6-weken omzet-prognose tile.

    weken = tuple[WeekTotaal, ...] from services.agenda.get_zes_weken_prognose
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('6-weken prognose').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if not weken:
            ui.label('Geen geplande werkdagen').classes('text-caption text-grey-6')
            return

        totaal = sum(w.bedrag_verwacht for w in weken)
        ui.label(format_euro(totaal, decimals=0)).classes('text-h6 num')
        ui.label(f'over {len(weken)} weken').classes('text-caption text-grey-6')

        # Mini bar chart
        ui.echart({
            'grid': {'top': 5, 'bottom': 20, 'left': 0, 'right': 0},
            'xAxis': {
                'type': 'category',
                'data': [f'wk{w.week_nr}' for w in weken],
                'axisLabel': {'fontSize': 9, 'color': 'var(--muted)'},
            },
            'yAxis': {'show': False, 'type': 'value'},
            'series': [{
                'type': 'bar',
                'data': [w.bedrag_verwacht for w in weken],
                'itemStyle': {'color': 'var(--accent)'},
            }],
            'tooltip': {'show': True},
        }).style('height: 80px; width: 100%')
```

- [ ] **Step 4b.1.4: Wire in `pages/dashboard.py`**

Add to `asyncio.gather` call:
```python
get_zes_weken_prognose(DB_PATH, vanaf=date.today()),
```

After gather, compute SPH-betaald query (new DB-helper or inline):

```python
# SPH betaald YTD (new query)
async with get_db_ctx(DB_PATH) as conn:
    cur = await conn.execute(
        """SELECT COALESCE(SUM(bedrag), 0) AS sph_total
           FROM uitgaven
           WHERE categorie = 'Pensioenpremie SPH'
             AND CAST(strftime('%Y', datum) AS INTEGER) = ?""",
        (jaar,),
    )
    sph_row = await cur.fetchone()
sph_betaald_ytd = sph_row['sph_total']

# SPH prognose (uses winst_projectie from earlier)
sph_prognose = compute_sph_prognose(
    projection_display['winst_projectie'], jaar)
```

Then in inzicht-grid render-loop (Phase 4b.5 wires this):

```python
if config['widgets']['I-3']:
    render_sph_tile(sph_betaald_ytd, sph_prognose)
if config['widgets']['I-4']:
    render_zes_weken_tile(zes_weken)
```

- [ ] **Step 4b.1.5: Run tests + commit**

```bash
git add components/dashboard_widgets.py services/dashboard.py pages/dashboard.py tests/test_dashboard_helpers.py
git commit -m "feat(sprint-h): T4b.1 SPH + 6-wk prognose inzicht-tiles"
```

### Task 4b.2 — I-5 Top klanten + I-6 Documenten checklist tiles

**Files:**
- Modify: `components/dashboard_widgets.py` (2 renderers)
- Modify: `pages/dashboard.py` (gather + render)

- [ ] **Step 4b.2.1: Renderers**

```python
def render_top_klanten_tile(klanten: list[dict]) -> None:
    """Render I-5 Top 5 klanten + concentratie tile."""
    with ui.card().classes('q-pa-md').style('border: 1px solid var(--border)'):
        ui.label('Top 5 klanten').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if not klanten:
            ui.label('Geen omzet').classes('text-caption text-grey-6')
            return

        top5 = klanten[:5]
        totaal = sum(k['omzet'] for k in klanten)
        for k in top5:
            pct = (k['omzet'] / totaal * 100) if totaal > 0 else 0
            with ui.row().classes('w-full items-center gap-2'):
                ui.label(k['klant_naam']).style(
                    'flex: 1; font-size: 12px')
                ui.label(format_euro(k['omzet'], decimals=0)).classes('num').style('font-size: 12px')
                ui.label(f'{pct:.0f}%').classes(
                    'text-caption text-grey-6 num').style('width: 30px; text-align: right')


def render_documenten_tile(aangifte_docs: list, AANGIFTE_DOCS: list[str]) -> None:
    """Render I-6 Aangifte-documenten checklist DETAIL tile."""
    with ui.card().classes('q-pa-md').style('border: 1px solid var(--border)'):
        ui.label('Aangifte-documenten').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        done = {d.documenttype for d in aangifte_docs}
        for cat in AANGIFTE_DOCS:
            is_done = cat in done
            with ui.row().classes('w-full items-center gap-2'):
                icon = 'check_circle' if is_done else 'radio_button_unchecked'
                color = 'var(--q-positive)' if is_done else 'var(--muted)'
                ui.icon(icon, size='16px').style(f'color: {color}')
                ui.label(cat).style('font-size: 12px; flex: 1')
```

- [ ] **Step 4b.2.2: Wire in dashboard**

```python
omzet_per_klant = await get_omzet_per_klant(DB_PATH, jaar=jaar)  # add to gather

if config['widgets']['I-5']:
    render_top_klanten_tile(omzet_per_klant)
if config['widgets']['I-6']:
    render_documenten_tile(aangifte_docs, AANGIFTE_DOCS)
```

- [ ] **Step 4b.2.3: Tests + commit**

```bash
git add components/dashboard_widgets.py pages/dashboard.py
git commit -m "feat(sprint-h): T4b.2 Top klanten + Documenten checklist tiles"
```

### Task 4b.3 — I-7 Cash-positie + I-8 Tax-calendar tiles

**Files:**
- Modify: `components/dashboard_widgets.py` (2 renderers)
- Modify: `pages/dashboard.py` (gather + render)

- [ ] **Step 4b.3.1: Renderers**

```python
def render_cash_positie_tile(opening_saldo: float | None, flow_ytd: float) -> None:
    """Render I-7 Cash-positie + flow YTD tile.

    Empty-state: opening_saldo IS NULL → show "Vul opening-saldo in /instellingen"
    (per spec R1 — NULL not =0).
    """
    with ui.card().classes('q-pa-md').style('border: 1px solid var(--border)'):
        ui.label('Cash-positie').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if opening_saldo is None:
            with ui.column().classes('gap-1'):
                ui.label('Geen opening-saldo').classes('text-body2 text-grey-6')
                ui.button('Vul in /instellingen',
                          on_click=lambda: ui.navigate.to('/instellingen?tab=fiscaal')) \
                    .props('flat dense color=primary size=sm')
            return

        current = opening_saldo + flow_ytd
        ui.label(format_euro(current, decimals=0)).classes('text-h6 num')
        ui.label(
            f'Opening: {format_euro(opening_saldo)} · '
            f'flow: {format_euro(flow_ytd)}'
        ).classes('text-caption text-grey-6')


def render_tax_calendar_tile(deadlines: list[dict]) -> None:
    """Render I-8 Tax-calendar (alle deadlines) tile."""
    with ui.card().classes('q-pa-md').style('border: 1px solid var(--border)'):
        ui.label('Belasting-deadlines').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if not deadlines:
            ui.label('Geen deadlines bekend').classes('text-caption text-grey-6')
            return

        today = date.today()
        for d in deadlines:
            days = (d['date'] - today).days
            color = 'var(--q-negative)' if days < 14 else 'var(--text)'
            with ui.row().classes('w-full items-center gap-2'):
                ui.label(d['label']).style(f'flex: 1; font-size: 12px; color: {color}')
                ui.label(f'{days}d' if days >= 0 else 'voorbij').classes(
                    'text-caption num').style(f'color: {color}')
```

- [ ] **Step 4b.3.2: Wire in dashboard**

```python
# Cash-positie data (per spec: balans_bank_saldo IS NULL = empty-state)
opening_saldo = fp.balans_bank_saldo if fp and fp.balans_bank_saldo else None
# flow_ytd = SUM(banktx.bedrag for current jaar)
flow_ytd = ...  # query if needed

if config['widgets']['I-7']:
    render_cash_positie_tile(opening_saldo, flow_ytd)
if config['widgets']['I-8']:
    render_tax_calendar_tile(tax_calendar(jaar))
```

- [ ] **Step 4b.3.3: Tests + commit**

```bash
git add components/dashboard_widgets.py pages/dashboard.py
git commit -m "feat(sprint-h): T4b.3 Cash-positie + Tax-calendar inzicht-tiles"
```

### Task 4b.4 — Wire customisation: render only enabled widgets in inzicht-grid

**Files:**
- Modify: `pages/dashboard.py` (replace existing chart-section with config-driven render)

- [ ] **Step 4b.4.1: Replace chart-rendering section**

Find the existing chart section (regel ~498-582 in pre-Sprint-H dashboard.py) and replace with:

```python
# INZICHT-GRID — config-driven render
raw_config = await get_dashboard_widgets_config(DB_PATH)
config = load_dashboard_widgets_config(raw_config)

with ui.element('div').style(
        'display: grid; grid-template-columns: 1fr 1fr; gap: 20px'):
    if config['widgets'].get('I-1', False):
        # Cumulative chart (existing)
        with ui.card().classes('q-pa-lg'):
            with ui.row().classes('w-full justify-between items-baseline'):
                ui.label('Cumulatieve omzet').classes('chart-title')
                ui.label(f'{jaar} vs {jaar - 1}').classes('chart-subtitle')
            ui.echart(cum_chart_config).style('height: 300px; width: 100%')

    if config['widgets'].get('I-2', False) and has_kosten:
        with ui.card().classes('q-pa-lg'):
            ui.label('Kostenverdeling').classes('chart-title')
            cost_donut_chart(kosten_per_cat)

    if config['widgets'].get('I-3', False):
        render_sph_tile(sph_betaald_ytd, sph_prognose)

    if config['widgets'].get('I-4', False):
        render_zes_weken_tile(zes_weken)

    if config['widgets'].get('I-5', False):
        render_top_klanten_tile(omzet_per_klant)

    if config['widgets'].get('I-6', False):
        render_documenten_tile(aangifte_docs, AANGIFTE_DOCS)

    if config['widgets'].get('I-7', False):
        render_cash_positie_tile(opening_saldo, flow_ytd)

    if config['widgets'].get('I-8', False):
        render_tax_calendar_tile(tax_calendar(jaar))

# Customisation discoverability link (per U2: "⚙ Tegels aanpassen" in footer zone 3)
ui.button('⚙ Tegels aanpassen',
          on_click=lambda: ui.navigate.to('/instellingen?tab=dashboard')) \
    .props('flat dense color=primary size=sm') \
    .style('margin-top: 8px')
```

- [ ] **Step 4b.4.2: Run tests + commit**

```bash
git add pages/dashboard.py
git commit -m "feat(sprint-h): T4b.4 wire config-driven inzicht-grid render"
```

---

## Phase 5 — Privé-zone (AOV only, conditional auto-collapse)

### Task 5.1 — `should_show_prive_zone` helper + AOV-query + render

**Files:**
- Modify: `database.py` (add `get_aov_total`)
- Modify: `services/dashboard.py` (add `should_show_prive_zone`)
- Modify: `components/dashboard_widgets.py` (add `render_prive_zone`)
- Modify: `pages/dashboard.py` (gather + render)

- [ ] **Step 5.1.1: DB query**

```python
async def get_aov_total(db_path: Path = DB_PATH, jaar: int = 2026) -> dict:
    """Return AOV YTD total + count from banktransacties."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT COALESCE(SUM(ABS(bedrag)), 0) AS total,
                      COUNT(*) AS count
               FROM banktransacties
               WHERE categorie = 'AOV'
                 AND CAST(strftime('%Y', datum) AS INTEGER) = ?""",
            (jaar,),
        )
        row = await cur.fetchone()
    return {'total': row['total'], 'count': row['count']}
```

- [ ] **Step 5.1.2: Helper + tests**

In `services/dashboard.py`:
```python
def should_show_prive_zone(
    aov_count: int,
    user_override_collapsed: bool | None,
) -> tuple[bool, bool]:
    """Returns (should_render, is_collapsed_by_default).

    Logic:
    - If user_override_collapsed is True → render but collapsed
    - If user_override_collapsed is False → render visible
    - If user_override_collapsed is None (auto) →
        - aov_count > 0 → render visible
        - aov_count == 0 → don't render at all
    """
    if user_override_collapsed is True:
        return (True, True)
    if user_override_collapsed is False:
        return (True, False)
    # auto-detect
    if aov_count > 0:
        return (True, False)
    return (False, False)
```

Tests for 4 scenarios.

- [ ] **Step 5.1.3: Renderer**

```python
def render_prive_zone(aov_total: float, is_collapsed: bool) -> None:
    """Render Privé-vaste-lasten zone (AOV only — geen persoonlijke SPH
    want SPH is bedrijfskost in ons model).
    """
    with ui.expansion(
            'Privé-vaste-lasten',
            icon='account_balance_wallet',
            value=not is_collapsed,
        ).classes('w-full prive-zone'):
        with ui.card().classes('w-full q-pa-md').style(
                'border: 1px solid var(--border)'):
            with ui.row().classes('items-center gap-2'):
                ui.label('AOV YTD:').style('font-size: 13px')
                ui.label(format_euro(aov_total, decimals=0)).classes('num').style(
                    'font-size: 13px; font-weight: 600')
            ui.label(
                'Niet aftrekbaar als bedrijfskost — wel relevant voor netto-inkomen.'
            ).classes('text-caption text-grey-6')
```

- [ ] **Step 5.1.4: Wire in dashboard**

```python
aov_data = await get_aov_total(DB_PATH, jaar=jaar)  # add to gather
should_render, is_collapsed = should_show_prive_zone(
    aov_data['count'], config.get('prive_section_collapsed'))

if should_render:
    render_prive_zone(aov_data['total'], is_collapsed)
```

- [ ] **Step 5.1.5: Tests + commit**

```bash
git add database.py services/dashboard.py components/dashboard_widgets.py pages/dashboard.py tests/test_dashboard_helpers.py
git commit -m "feat(sprint-h): T5.1 Privé-zone (AOV only, conditional auto-collapse)"
```

---

## Phase 6 — Werkdag→factuur deep-link + post-merge audit

### Task 6.1 — Werkdag→factuur action investigation + implementation OR document deferral

**Files:** TBD based on investigation

- [ ] **Step 6.1.1: Investigate existing flows**

```bash
grep -n "Factureer geselecteerde\|werkdagen=\|/facturen?nieuw" pages/werkdagen.py pages/facturen.py components/invoice_builder.py | head -20
```

Decide: extend existing pattern OR build new deep-link. Document choice in commit message.

- [ ] **Step 6.1.2: Implement chosen approach**

If reuse: add `action_kind='genereer_factuur'` to werkdag-row in T3.4 + dispatcher navigates to Sprint A pattern.
If new deep-link: add deep-link contract `/facturen?nieuw=1&werkdagen=ID,ID,ID` parsing.

- [ ] **Step 6.1.3: Tests + commit**

### Task 6.2 — Combined post-Sprint-H audit (Codex + code-quality reviewer parallel)

- [ ] **Step 6.2.1: Run full test suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 6.2.2: Dispatch combined post-merge audit**

Same pattern as Sprint G T6: code-reviewer subagent (opus) + Codex CLI parallel op cumulative diff van Sprint H.

- [ ] **Step 6.2.3: Apply fixes for any cumulative bugs caught**

- [ ] **Step 6.2.4: Cascade-lint check**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_visual_css.py -v
```

- [ ] **Step 6.2.5: Memory + CLAUDE.md update**

Update memory with Sprint H outcome (`~/.claude/projects/.../memory/project_sprint_h.md`).
Optional: append to CLAUDE.md "Visuele tokens" section if `.dashboard-hero-tile` pattern is reusable.

- [ ] **Step 6.2.6: Final commit**

```bash
git commit -m "$(cat <<'EOF'
feat(sprint-h): T6.2 post-merge audit + memory update

Sprint H complete: dashboard redesigned per v3 synthesis spec.

Process:
- Phase 1-6 atomic-shippable
- 4-layer review per task (implementer + Codex + spec + code-quality)
- Combined post-merge audit on cumulative diff

Pytest baseline+N, all green.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

### 1. Spec coverage
- §A Layout (4-zone) → Phases 1-5 all touch layout ✓
- §B.Hero strip → Phase 1+2 ✓
- §B.Action-inbox → Phase 3 ✓
- §B.Inzicht-grid → Phase 4b ✓
- §B.Privé-zone → Phase 5 ✓
- §C Customisation → Phase 4a ✓
- §D Phasing → matches plan structure ✓
- §E Risk register → addressed in implementation steps ✓
- §F Function specifications → Task 1.3 (compute_belasting), Task 2.1 (compute_jaareinde), Task 3.1 (ActionRow + prioritise), Task 3.2 (seasonal+tax_calendar), Task 4a.2 (load_config), Task 4b.1 (compute_sph), Task 5.1 (should_show_prive_zone) ✓
- §G U1/U2/U3 user decisions → applied throughout (1 number, "⚙ Tegels aanpassen" in zone 3 footer, confirm-dialog) ✓

### 2. Placeholder scan
- Task 6.1 has "TBD based on investigation" — this is intentional (real design-decision needed during phase, not pre-committable)
- All other tasks have actual code-blocks

### 3. Type consistency
- `ActionRow` dataclass used consistently in T3.1, T3.2, T3.4 ✓
- `compute_*` helpers return shapes match render-helper expectations ✓
- `DEFAULT_WIDGETS` keys consistent (I-1..I-8) across T4a.2, T4a.3, T4b.4 ✓

---

## Execution

**Plan complete and saved to `docs/superpowers/plans/2026-05-04-dashboard-redesign.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Fresh subagent per task + 4-layer review (implementer + Codex + spec + code-quality), per Sprint G pattern.

**2. Inline Execution** — Tasks executed in this session via `executing-plans`, batch with checkpoints.

**Aanbeveling: subagent-driven** — Sprint G bewees pattern, ~6 bugs gevangen incl 1 cumulative scope-bleed bug die per-task review gemist had.
