# Codex Review Enhancements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix packaging bugs, consolidate duplicated constants, add a dashboard health-alerts section, add year-end checklist gating, and add bank categorization suggestions — based on a joint Codex + Claude Opus analysis.

**Architecture:** Five independent workstreams, each producing testable, committable output. Tasks 1-2 are quick fixes (constants/requirements). Tasks 3-5 are features that build on existing data-fetching patterns and the established NiceGUI + raw-SQL codebase. All new DB functions go in `database.py` following existing patterns (async, `get_db_ctx`, `?` placeholders). All new UI follows existing Quasar-semantic-color card patterns.

**Tech Stack:** Python 3.12+, NiceGUI/Quasar, aiosqlite, pytest + pytest-asyncio

**Test command:** `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `requirements.txt` | Add missing cv2/numpy deps |
| Create | `components/archive_paths.py` | Single source of truth for ARCHIVE_BASE |
| Modify | `components/invoice_generator.py` | Import ARCHIVE_BASE from new module |
| Modify | `import_/expense_utils.py` | Import ARCHIVE_BASE from new module |
| Modify | `database.py` | Add `get_health_alerts()` + `get_categorie_suggestions()` |
| Modify | `pages/dashboard.py` | Render health alerts section |
| Modify | `pages/jaarafsluiting.py` | Extract checklist logic, gate definitief |
| Modify | `pages/bank.py` | Wire category suggestions into q-select |
| Create | `tests/test_health_alerts.py` | Tests for health alert DB queries |
| Create | `tests/test_categorie_suggestions.py` | Tests for bank suggestion DB query |
| Modify | `tests/test_jaarafsluiting_snapshot.py` | Add checklist extraction tests |

---

## Task 1: Fix missing dependencies in requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add opencv-python-headless and numpy**

`components/invoice_builder.py:14-15` imports `cv2` and `numpy` for QR decoding, but these are missing from requirements.txt. Add them:

```
# In requirements.txt, add after the weasyprint line:
opencv-python-headless
numpy
```

The full file should be:

```
nicegui>=3.8,<4.0
aiosqlite
openpyxl
jinja2
weasyprint
opencv-python-headless
numpy
pytest
pytest-asyncio
uvicorn>=0.34,<0.41
starlette>=0.49,<0.52
```

- [ ] **Step 2: Verify imports work**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -c "import cv2; import numpy; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "fix: add missing opencv-python-headless + numpy to requirements.txt

invoice_builder.py imports cv2/numpy for QR decoding but they were
not declared in requirements.txt, causing ImportError on fresh installs."
```

---

## Task 2: Consolidate ARCHIVE_BASE to single source

**Context:** `ARCHIVE_BASE` is defined in two places with different paths:
- `components/invoice_generator.py:17` → `~/…/Boekhouding_Waarneming/Inkomen en Uitgaven`
- `import_/expense_utils.py:12` → `~/…/Boekhouding_Waarneming`

The invoice generator appends `/Inkomen en Uitgaven` to the base, while expense_utils appends `/Uitgaven` dynamically. The true shared root is `~/…/Boekhouding_Waarneming`.

**Files:**
- Create: `components/archive_paths.py`
- Modify: `components/invoice_generator.py:16-18`
- Modify: `import_/expense_utils.py:11-15`

- [ ] **Step 1: Create the shared constants module**

Create `components/archive_paths.py`:

```python
"""Shared SynologyDrive archive paths — single source of truth."""

from pathlib import Path

# Root of the bookkeeping archive on SynologyDrive.
# Sub-paths: Inkomen en Uitgaven/{jaar}/Inkomsten/... (invoices)
#            {jaar}/Uitgaven/... (expenses)
ARCHIVE_BASE = (
    Path.home() / 'Library' / 'CloudStorage' / 'SynologyDrive-Main'
    / '02_Financieel' / 'Boekhouding_Waarneming'
)
```

- [ ] **Step 2: Update invoice_generator.py to import from shared module**

In `components/invoice_generator.py`, replace lines 16-18:

```python
# OLD (remove):
# SynologyDrive archief — facturen worden hier automatisch gekopieerd per type/jaar
ARCHIVE_BASE = Path.home() / 'Library' / 'CloudStorage' / 'SynologyDrive-Main' / \
    '02_Financieel' / 'Boekhouding_Waarneming' / 'Inkomen en Uitgaven'

# NEW:
from components.archive_paths import ARCHIVE_BASE
```

Then update `archive_factuur_pdf()` (currently at line 42) — the old code used `ARCHIVE_BASE / jaar / subdir` where ARCHIVE_BASE already included `Inkomen en Uitgaven`. The new code must prepend that segment:

```python
# In archive_factuur_pdf(), line 42, change:
    target_dir = ARCHIVE_BASE / jaar / subdir
# To:
    target_dir = ARCHIVE_BASE / 'Inkomen en Uitgaven' / jaar / subdir
```

- [ ] **Step 3: Update expense_utils.py to import from shared module**

In `import_/expense_utils.py`, replace lines 11-15:

```python
# OLD (remove):
# Base path of the bookkeeping archive
ARCHIVE_BASE = (
    Path.home() / 'Library' / 'CloudStorage' / 'SynologyDrive-Main'
    / '02_Financieel' / 'Boekhouding_Waarneming'
)

# NEW:
from components.archive_paths import ARCHIVE_BASE
```

No further changes needed in expense_utils — it already appends `str(year) / 'Uitgaven'` dynamically.

- [ ] **Step 4: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all existing tests pass (624+). The archive paths resolve identically to before.

- [ ] **Step 5: Commit**

```bash
git add components/archive_paths.py components/invoice_generator.py import_/expense_utils.py
git commit -m "refactor: consolidate ARCHIVE_BASE into components/archive_paths.py

Was defined in two files with subtly different paths. Now a single
source of truth, reducing maintenance risk."
```

---

## Task 3: Dashboard health alerts section

**Context:** The dashboard (`pages/dashboard.py`) already has an "AANDACHTSPUNTEN" section (lines 548-613) that shows ongefactureerde werkdagen and openstaande facturen as amber/orange alert banners. We extend this with additional health signals: uncategorized bank transactions, missing fiscal params for current year, and verlopen (overdue) invoices — all using data already fetched or cheaply queryable.

**Files:**
- Modify: `database.py` (add `get_health_alerts()`)
- Modify: `pages/dashboard.py` (call it, render results)
- Create: `tests/test_health_alerts.py`

### Step group A: Database function

- [ ] **Step A1: Write failing test for get_health_alerts**

Create `tests/test_health_alerts.py`:

```python
"""Tests for dashboard health alerts."""

import pytest
from database import (
    get_health_alerts, add_banktransacties, add_factuur, add_klant,
    upsert_fiscale_params,
)
from import_.seed_data import FISCALE_PARAMS


@pytest.mark.asyncio
async def test_health_alerts_empty_db(db):
    """Empty DB should return alerts for missing fiscal params only."""
    from datetime import date
    jaar = date.today().year
    alerts = await get_health_alerts(db, jaar)
    assert isinstance(alerts, list)
    # No fiscal params → should flag it
    assert any(a['key'] == 'missing_fiscal_params' for a in alerts)


@pytest.mark.asyncio
async def test_health_alerts_uncategorized_bank(db):
    """Uncategorized bank transactions should produce an alert."""
    from datetime import date
    jaar = date.today().year
    await add_banktransacties(db, [
        {'datum': f'{jaar}-03-15', 'bedrag': -50.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'Boodschappen'},
    ])
    alerts = await get_health_alerts(db, jaar)
    uncat = next((a for a in alerts if a['key'] == 'uncategorized_bank'), None)
    assert uncat is not None
    assert uncat['count'] == 1


@pytest.mark.asyncio
async def test_health_alerts_overdue_invoice(db):
    """Verstuurd invoice older than 14 days should trigger overdue alert."""
    from datetime import date, timedelta
    jaar = date.today().year
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    old_date = (date.today() - timedelta(days=20)).isoformat()
    await add_factuur(
        db, nummer=f'{jaar}-099', klant_id=kid,
        datum=old_date, totaal_uren=8, totaal_km=0,
        totaal_bedrag=800.0, status='verstuurd',
    )
    alerts = await get_health_alerts(db, jaar)
    overdue = next((a for a in alerts if a['key'] == 'overdue_invoices'), None)
    assert overdue is not None
    assert overdue['count'] == 1


@pytest.mark.asyncio
async def test_health_alerts_all_clear(db):
    """DB with fiscal params set should not flag missing_fiscal_params."""
    from datetime import date
    jaar = date.today().year
    # Use a year that has seed data; seed data contains all required keys
    seed_year = max(FISCALE_PARAMS.keys())
    seed = {**FISCALE_PARAMS[seed_year], 'jaar': jaar}
    await upsert_fiscale_params(db, **seed)
    alerts = await get_health_alerts(db, jaar)
    assert not any(a['key'] == 'missing_fiscal_params' for a in alerts)
```

- [ ] **Step A2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_health_alerts.py -v`
Expected: ImportError — `get_health_alerts` does not exist yet.

- [ ] **Step A3: Implement get_health_alerts in database.py**

Add at the end of the "Aggregation/Dashboard" section (after `get_werkdagen_ongefactureerd_summary`, around line 2085):

```python
async def get_health_alerts(db_path: Path = DB_PATH, jaar: int = 2026) -> list[dict]:
    """Return actionable health alerts for the dashboard.

    Each alert is a dict with keys:
      key: str         — identifier (e.g. 'uncategorized_bank')
      severity: str    — 'warning' or 'info'
      message: str     — human-readable Dutch description
      count: int       — number of items (for display)
      link: str        — page route to navigate to
    Returns empty list when everything is healthy.
    """
    from datetime import date, timedelta
    alerts = []
    jaar_start = f'{jaar}-01-01'
    jaar_end = f'{jaar + 1}-01-01'
    overdue_cutoff = (date.today() - timedelta(days=14)).isoformat()

    async with get_db_ctx(db_path) as conn:
        # 1. Uncategorized bank transactions (no category, no koppeling)
        cur = await conn.execute(
            "SELECT COUNT(*) FROM banktransacties "
            "WHERE datum >= ? AND datum < ? "
            "AND (categorie IS NULL OR categorie = '') "
            "AND (koppeling_type IS NULL OR koppeling_type = '')",
            (jaar_start, jaar_end))
        uncat = (await cur.fetchone())[0]
        if uncat > 0:
            alerts.append({
                'key': 'uncategorized_bank',
                'severity': 'info',
                'message': f'{uncat} banktransacties niet gecategoriseerd',
                'count': uncat,
                'link': '/bank',
            })

        # 2. Overdue invoices (verstuurd + datum > 14 days ago)
        cur = await conn.execute(
            "SELECT COUNT(*) FROM facturen "
            "WHERE status = 'verstuurd' AND datum < ? "
            "AND datum >= ? AND datum < ?",
            (overdue_cutoff, jaar_start, jaar_end))
        overdue = (await cur.fetchone())[0]
        if overdue > 0:
            alerts.append({
                'key': 'overdue_invoices',
                'severity': 'warning',
                'message': f'{overdue} facturen verlopen (> 14 dagen)',
                'count': overdue,
                'link': '/facturen',
            })

        # 3. Concept invoices still in draft
        cur = await conn.execute(
            "SELECT COUNT(*) FROM facturen "
            "WHERE status = 'concept' "
            "AND datum >= ? AND datum < ?",
            (jaar_start, jaar_end))
        concepts = (await cur.fetchone())[0]
        if concepts > 0:
            alerts.append({
                'key': 'concept_invoices',
                'severity': 'info',
                'message': f'{concepts} facturen nog in concept',
                'count': concepts,
                'link': '/facturen',
            })

    # 4. Missing fiscal params (outside connection — uses own)
    params = await get_fiscale_params(db_path, jaar)
    if params is None:
        alerts.append({
            'key': 'missing_fiscal_params',
            'severity': 'warning',
            'message': f'Fiscale parameters {jaar} niet ingesteld',
            'count': 0,
            'link': '/instellingen',
        })

    return alerts
```

- [ ] **Step A4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_health_alerts.py -v`
Expected: 4 passed.

- [ ] **Step A5: Run full test suite for regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all tests pass.

- [ ] **Step A6: Commit**

```bash
git add database.py tests/test_health_alerts.py
git commit -m "feat: add get_health_alerts() for dashboard health section

Returns actionable alerts: uncategorized bank txns, overdue invoices,
concept invoices, missing fiscal params. All tested."
```

### Step group B: Dashboard UI rendering

- [ ] **Step B1: Add import and data fetch**

In `pages/dashboard.py`, add `get_health_alerts` to the database import (line 14-19):

```python
from database import (
    get_kpis, get_kpis_tot_datum, get_omzet_per_maand,
    get_uitgaven_per_categorie, get_openstaande_facturen,
    get_werkdagen_ongefactureerd_summary, get_km_totaal,
    get_fiscale_params, get_aangifte_documenten,
    get_va_betalingen, get_health_alerts, DB_PATH,
)
```

In `refresh_dashboard()`, add `get_health_alerts` to the `asyncio.gather()` call (around line 185). Add it as a 13th element:

```python
        (kpis, kpis_vorig, omzet_huidig, omzet_vorig, kosten_per_cat,
         openstaande, ongefact, km_data,
         ib_resultaat, fp, va_data, aangifte_docs,
         health_alerts) = await asyncio.gather(
            get_kpis(DB_PATH, jaar=jaar),
            get_kpis(DB_PATH, jaar=jaar - 1),
            get_omzet_per_maand(DB_PATH, jaar=jaar),
            get_omzet_per_maand(DB_PATH, jaar=jaar - 1),
            get_uitgaven_per_categorie(DB_PATH, jaar=jaar),
            get_openstaande_facturen(DB_PATH, jaar=jaar),
            get_werkdagen_ongefactureerd_summary(DB_PATH, jaar=jaar),
            get_km_totaal(DB_PATH, jaar=jaar),
            _compute_ib_estimate(jaar),
            get_fiscale_params(DB_PATH, jaar),
            get_va_betalingen(DB_PATH, jaar),
            get_aangifte_documenten(DB_PATH, jaar),
            get_health_alerts(DB_PATH, jaar=jaar),
        )
```

- [ ] **Step B2: Render health alerts in the AANDACHTSPUNTEN section**

In `pages/dashboard.py`, after the existing AANDACHTSPUNTEN block (after line 613, before `jaar_select.on_value_change`), add rendering for health alerts. Only render if there are alerts beyond what AANDACHTSPUNTEN already covers (ongefact + openstaand are already shown):

```python
            # Health alerts — additional signals beyond ongefact/openstaand
            if health_alerts:
                if not (has_ongefact or has_openstaand):
                    # Only show header if AANDACHTSPUNTEN wasn't already rendered
                    ui.label('AANDACHTSPUNTEN').classes('section-label')

                _severity_style = {
                    'warning': (
                        'background: #FEF2F2; border: 1px solid #FECACA;',
                        '#DC2626', '#991B1B',
                    ),
                    'info': (
                        'background: #EFF6FF; border: 1px solid #BFDBFE;',
                        '#2563EB', '#1E40AF',
                    ),
                }
                for alert in health_alerts:
                    bg_style, icon_color, text_color = _severity_style.get(
                        alert['severity'], _severity_style['info'])
                    with ui.element('div').style(
                            f'{bg_style} border-radius: 10px; '
                            f'padding: 14px 18px; display: flex; '
                            f'align-items: center; '
                            f'justify-content: space-between'):
                        with ui.row().classes('items-center gap-2'):
                            icon = ('warning' if alert['severity'] == 'warning'
                                    else 'info_outline')
                            ui.icon(icon, size='20px').style(
                                f'color: {icon_color}')
                            ui.html(
                                f'<span style="font-size:13px;font-weight:600;'
                                f'color:{text_color}">'
                                f'{alert["message"]}</span>')
                        if alert.get('link'):
                            ui.button(
                                'Bekijk',
                                on_click=lambda l=alert['link']: ui.navigate.to(l),
                            ).props('flat dense size=sm') \
                                .style(f'border: 1px solid {icon_color}; '
                                       f'border-radius: 6px; '
                                       f'color: {icon_color}; font-size: 12px')
```

- [ ] **Step B3: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step B4: Manual verification**

Start the app and check the dashboard:
```bash
source .venv/bin/activate && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py
```
Verify: health alert banners appear below the existing amber/orange banners. They should show relevant alerts (uncategorized bank txns, etc.) with clickable "Bekijk" buttons that navigate to the correct page.

- [ ] **Step B5: Commit**

```bash
git add pages/dashboard.py
git commit -m "feat: render health alerts on dashboard

Shows uncategorized bank txns, overdue invoices, concept invoices, and
missing fiscal params as colored alert banners with navigation links."
```

---

## Task 4: Year-end checklist gating

**Context:** `pages/jaarafsluiting.py` has a Controles tab (line 501) that computes data-integrity issues — ongefactureerde werkdagen, facturen zonder werkdagen, missing VA docs, etc. The `set_definitief()` function (line 771) currently shows a simple confirmation dialog with no pre-flight checks. We extract the checklist logic into a shared function and gate the definitief dialog.

**Files:**
- Modify: `pages/jaarafsluiting.py` (extract + gate)
- Modify: `tests/test_jaarafsluiting_snapshot.py` (add checklist tests)

### Step group A: Extract checklist logic

- [ ] **Step A1: Write failing test for checklist extraction**

Add to `tests/test_jaarafsluiting_snapshot.py`:

```python
@pytest.mark.asyncio
async def test_compute_checklist_issues_empty_db(db):
    """Empty DB for a year should return issues for missing data."""
    from pages.jaarafsluiting import compute_checklist_issues
    issues = await compute_checklist_issues(db, 2026)
    assert isinstance(issues, list)
    # No facturen, no uitgaven → should flag these
    assert any('facturen' in i[1].lower() for i in issues)


@pytest.mark.asyncio
async def test_compute_checklist_issues_clean_year(db):
    """Year with complete data should return fewer/no issues."""
    from pages.jaarafsluiting import compute_checklist_issues
    from database import add_klant, add_factuur, add_uitgave, upsert_fiscale_params
    from import_.seed_data import FISCALE_PARAMS
    # Seed fiscal params using real seed data (upsert needs all keys)
    seed = {**FISCALE_PARAMS[max(FISCALE_PARAMS.keys())], 'jaar': 2026}
    await upsert_fiscale_params(db, **seed)
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    await add_factuur(
        db, nummer='2026-001', klant_id=kid,
        datum='2026-06-15', totaal_uren=8, totaal_km=0,
        totaal_bedrag=800.0, status='betaald',
    )
    await add_uitgave(db, datum='2026-03-01', omschrijving='Pennen',
                      bedrag=25.0, categorie='Kantoorkosten')
    issues = await compute_checklist_issues(db, 2026)
    # Should NOT flag missing facturen or uitgaven
    assert not any('geen facturen' in i[1].lower() for i in issues)
    assert not any('geen uitgaven' in i[1].lower() for i in issues)
```

- [ ] **Step A2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_jaarafsluiting_snapshot.py::test_compute_checklist_issues_empty_db -v`
Expected: ImportError — `compute_checklist_issues` does not exist.

- [ ] **Step A3: Extract compute_checklist_issues from render_controles**

In `pages/jaarafsluiting.py`, add a module-level async function (before the `@ui.page` decorator) that extracts the data-integrity checks from `render_controles` (lines 557-681). This function should be importable for tests and reusable in the definitief gate.

```python
async def compute_checklist_issues(db_path, jaar: int) -> list[tuple[str, str, str | None]]:
    """Compute data-integrity issues for a given year.

    Returns list of (severity, message, link) tuples — same format as
    render_controles uses internally. Empty list = year is clean.
    """
    from components.document_specs import AANGIFTE_DOCS

    issues = []
    async with get_db_ctx(db_path) as conn:
        # 1. Ongefactureerde werkdagen
        cur = await conn.execute(
            "SELECT COUNT(*) FROM werkdagen "
            "WHERE substr(datum,1,4)=? "
            "AND (factuurnummer = '' OR factuurnummer IS NULL) "
            "AND tarief > 0", (str(jaar),))
        ongefact = (await cur.fetchone())[0]
        if ongefact > 0:
            issues.append((
                'warning',
                f'{ongefact} ongefactureerde werkdagen met tarief > 0',
                '/werkdagen'))

        # 2. Facturen zonder werkdagen
        cur = await conn.execute(
            "SELECT nummer, totaal_bedrag FROM facturen "
            "WHERE substr(datum,1,4)=? AND type='factuur' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM werkdagen w "
            "  WHERE w.factuurnummer = facturen.nummer"
            ")", (str(jaar),))
        orphans = await cur.fetchall()
        if orphans:
            nrs = ', '.join(r[0] for r in orphans[:5])
            issues.append((
                'warning',
                f'{len(orphans)} facturen zonder werkdagen: {nrs}',
                '/facturen'))

        # 3. Betaalde facturen zonder betaald_datum
        cur = await conn.execute(
            "SELECT COUNT(*) FROM facturen "
            "WHERE substr(datum,1,4)=? AND status = 'betaald' "
            "AND (betaald_datum IS NULL OR betaald_datum='')",
            (str(jaar),))
        no_date = (await cur.fetchone())[0]
        if no_date > 0:
            issues.append((
                'info',
                f'{no_date} betaalde facturen zonder betaaldatum',
                '/facturen'))

        # 4. Niet-gecategoriseerde banktransacties
        cur = await conn.execute(
            "SELECT COUNT(*) FROM banktransacties "
            "WHERE substr(datum,1,4)=? "
            "AND (categorie IS NULL OR categorie='') "
            "AND koppeling_type IS NULL",
            (str(jaar),))
        uncat = (await cur.fetchone())[0]
        if uncat > 0:
            issues.append((
                'info',
                f'{uncat} banktransacties niet gecategoriseerd',
                '/bank'))

    # 5. VA bedragen zonder beschikking PDF
    params = await get_fiscale_params(db_path, jaar)
    if params:
        va_total = (params.voorlopige_aanslag_betaald or 0) + \
                   (params.voorlopige_aanslag_zvw or 0)
        docs = await get_aangifte_documenten(db_path, jaar)
        doc_types = {d.documenttype for d in docs}
        has_va_docs = ('va_ib_beschikking' in doc_types or
                       'va_zvw_beschikking' in doc_types)
        if va_total > 0 and not has_va_docs:
            issues.append((
                'warning',
                f'VA bedragen ingevuld ({format_euro(va_total)}) '
                f'maar geen beschikking PDF geupload',
                '/documenten'))
        elif va_total == 0:
            issues.append((
                'warning',
                'Voorlopige aanslag niet ingevuld',
                '/aangifte'))

        # 6. Persoonlijke gegevens
        missing_personal = []
        if (params.woz_waarde or 0) == 0:
            missing_personal.append('WOZ-waarde')
        if (params.hypotheekrente or 0) == 0:
            missing_personal.append('Hypotheekrente')
        if (params.aov_premie or 0) == 0:
            missing_personal.append('AOV premie')
        if missing_personal:
            issues.append((
                'info',
                f'Persoonlijke gegevens ontbreken: '
                f'{", ".join(missing_personal)}',
                '/aangifte'))

    # 7. Missing data
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM uitgaven WHERE substr(datum,1,4)=?",
            (str(jaar),))
        n_uitgaven = (await cur.fetchone())[0]
        if n_uitgaven == 0:
            issues.append(('warning', 'Geen uitgaven ingevoerd', '/kosten'))

        cur = await conn.execute(
            "SELECT COUNT(*) FROM facturen WHERE substr(datum,1,4)=?",
            (str(jaar),))
        n_facturen = (await cur.fetchone())[0]
        if n_facturen == 0:
            issues.append(('warning', 'Geen facturen gevonden', '/facturen'))

    return issues
```

Then update `render_controles` to call `compute_checklist_issues` instead of duplicating the logic. Replace lines 557-681 (the `issues = []` block through the document completeness check) with:

```python
            issues = await compute_checklist_issues(DB_PATH, jaar)
            ok_checks = []  # OK checks still computed in render_controles
            # ... keep the existing ok_checks logic and rendering below
```

**Important:** The `ok_checks` list and the document completeness / kengetallen rendering stays in `render_controles` since those are UI-only concerns. Only the `issues` computation moves to the shared function.

- [ ] **Step A4: Run tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_jaarafsluiting_snapshot.py -v`
Expected: all pass including the 2 new ones.

- [ ] **Step A5: Run full suite for regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step A6: Commit**

```bash
git add pages/jaarafsluiting.py tests/test_jaarafsluiting_snapshot.py
git commit -m "refactor: extract compute_checklist_issues from render_controles

Shared async function computes data-integrity issues for a year.
Used by both the Controles tab and the upcoming definitief gate."
```

### Step group B: Gate the definitief action

- [ ] **Step B1: Add checklist to the definitief confirmation dialog**

In `pages/jaarafsluiting.py`, modify `set_definitief()` (the `else:` branch starting at line 796). Before the existing confirmation dialog, call `compute_checklist_issues` and show warnings:

Replace the dialog construction (lines 798-849) with:

```python
            # Pre-flight checklist
            preflight_issues = await compute_checklist_issues(DB_PATH, jaar)
            warnings = [i for i in preflight_issues if i[0] == 'warning']

            with ui.dialog() as dlg, ui.card().style('min-width: 500px'):
                ui.label('Markeren als definitief?').classes('text-h6')

                if warnings:
                    with ui.card().classes('w-full q-pa-sm q-mb-md').style(
                            'background: #FEF3C7; border: 1px solid #FDE68A'):
                        with ui.row().classes('items-center gap-2 q-mb-xs'):
                            ui.icon('warning', color='warning')
                            ui.label(f'{len(warnings)} aandachtspunten') \
                                .classes('text-subtitle2 text-weight-bold')
                        for _sev, msg, link in warnings:
                            with ui.row().classes('items-center gap-1'):
                                ui.icon('chevron_right', size='xs',
                                        color='warning')
                                lbl = ui.label(msg).classes(
                                    'text-caption text-grey-8')

                ui.label(
                    'De huidige jaarcijfers worden vastgelegd als snapshot. '
                    'Latere wijzigingen in onderliggende data (uitgaven, '
                    'facturen) veranderen deze cijfers niet meer. '
                    'U kunt later heropenen indien nodig.'
                ).classes('q-mb-md')

                with ui.row().classes('w-full justify-end gap-2'):
                    ui.button('Annuleren', on_click=dlg.close).props('flat')
                    async def confirm_definitief():
                        live_data = await fetch_fiscal_data(DB_PATH, jaar)
                        if live_data is None:
                            ui.notify(
                                f'Geen fiscale data voor {jaar} — kan niet afsluiten',
                                type='negative')
                            dlg.close()
                            return
                        live_winst = (live_data['omzet']
                                      - live_data['kosten_excl_inv']
                                      - live_data['totaal_afschrijvingen'])
                        vj_result = await _load_prior_year(jaar - 1)
                        vj_begin_vermogen = 0.0
                        if (vj_result is not None
                                and vj_result[1] is not None):
                            vj_begin_vermogen = vj_result[1].get(
                                'eigen_vermogen', 0.0)
                        live_balans = await bereken_balans(
                            DB_PATH, jaar, live_data['activastaat'],
                            winst=live_winst,
                            begin_vermogen=vj_begin_vermogen)
                        params_dict = live_data.get('params_dict', {}) or {}
                        snapshot_data = {
                            k: v for k, v in live_data.items() if k != 'params'
                        }
                        await save_jaarafsluiting_snapshot(
                            DB_PATH, jaar, snapshot_data, live_balans, params_dict)
                        await update_jaarafsluiting_status(
                            DB_PATH, jaar, 'definitief')
                        dlg.close()
                        ui.notify(
                            f'Jaar {jaar} definitief gemaakt en vastgelegd',
                            type='positive')
                        await render_all()
                    btn_label = ('Toch markeren als definitief' if warnings
                                 else 'Markeer definitief')
                    ui.button(btn_label, on_click=confirm_definitief) \
                        .props('color=positive')
            dlg.open()
```

Note: the `confirm_definitief` body is identical to the existing code. The only change is the pre-flight issues display and the button label changing when there are warnings.

- [ ] **Step B2: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step B3: Manual verification**

Start the app, navigate to Jaarafsluiting for a year with known issues (e.g. uncategorized bank transactions). Click "Markeer als definitief". Verify: the dialog shows amber warnings listing the issues, and the button says "Toch markeren als definitief". For a clean year, verify: no warnings, button says "Markeer definitief".

- [ ] **Step B4: Commit**

```bash
git add pages/jaarafsluiting.py
git commit -m "feat: gate definitief with pre-flight checklist

Shows data-integrity warnings before allowing year-end freeze.
User can still proceed (soft gate), but sees all issues first."
```

---

## Task 5: Bank categorization suggestions

**Context:** Bank transactions are categorized via an inline `q-select` dropdown on `pages/bank.py` (line 452-459). Currently the dropdown is blank for new transactions. We add a DB function that looks up past categorizations by `tegenpartij` (counterparty name) and pre-selects the most common category. The user still controls the final choice — this is a suggestion, not auto-assignment.

**Files:**
- Modify: `database.py` (add `get_categorie_suggestions()`)
- Modify: `pages/bank.py` (pre-populate dropdown)
- Create: `tests/test_categorie_suggestions.py`

### Step group A: Database function

- [ ] **Step A1: Write failing test**

Create `tests/test_categorie_suggestions.py`:

```python
"""Tests for bank transaction category suggestions."""

import pytest
from database import get_categorie_suggestions, add_banktransacties, update_banktransactie


@pytest.mark.asyncio
async def test_suggestions_empty_db(db):
    """No transactions → empty suggestions dict."""
    result = await get_categorie_suggestions(db)
    assert result == {}


@pytest.mark.asyncio
async def test_suggestions_from_categorized_transactions(db):
    """Categorized transactions should produce suggestions by tegenpartij."""
    from database import get_banktransacties
    # Add 3 transactions from same counterparty, 2 with same category
    await add_banktransacties(db, [
        {'datum': '2026-01-15', 'bedrag': -50.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'Boodschappen'},
        {'datum': '2026-02-15', 'bedrag': -45.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'Boodschappen'},
        {'datum': '2026-03-15', 'bedrag': -60.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'Boodschappen'},
    ])
    # Categorize 2 as Representatie, 1 as Kantoorkosten
    txns = await get_banktransacties(db)
    await update_banktransactie(db, txns[0].id, categorie='Representatie')
    await update_banktransactie(db, txns[1].id, categorie='Representatie')
    await update_banktransactie(db, txns[2].id, categorie='Kantoorkosten')

    result = await get_categorie_suggestions(db)
    # Most common category for 'albert heijn' (lowercased key)
    assert result.get('albert heijn') == 'Representatie'


@pytest.mark.asyncio
async def test_suggestions_case_insensitive_grouping(db):
    """Tegenpartij matching should be case-insensitive."""
    await add_banktransacties(db, [
        {'datum': '2026-01-15', 'bedrag': -50.0,
         'tegenpartij': 'ALBERT HEIJN', 'omschrijving': 'x'},
        {'datum': '2026-02-15', 'bedrag': -45.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'x'},
    ])
    from database import get_banktransacties
    txns = await get_banktransacties(db)
    for t in txns:
        await update_banktransactie(db, t.id, categorie='Representatie')

    result = await get_categorie_suggestions(db)
    # Key is always lowercased
    assert 'albert heijn' in result
    assert result['albert heijn'] == 'Representatie'


@pytest.mark.asyncio
async def test_suggestions_ignores_uncategorized(db):
    """Transactions without a category should not produce suggestions."""
    await add_banktransacties(db, [
        {'datum': '2026-01-15', 'bedrag': -50.0,
         'tegenpartij': 'Bol.com', 'omschrijving': 'Bestelling'},
    ])
    result = await get_categorie_suggestions(db)
    assert 'Bol.com' not in result
    assert 'bol.com' not in result
```

- [ ] **Step A2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_categorie_suggestions.py -v`
Expected: ImportError — `get_categorie_suggestions` does not exist.

- [ ] **Step A3: Implement get_categorie_suggestions**

Add in `database.py` after the banktransacties section (after `update_banktransactie`, around line 1375):

```python
async def get_categorie_suggestions(db_path: Path = DB_PATH) -> dict[str, str]:
    """Build a lookup of tegenpartij → most-used category.

    Groups by lowercased tegenpartij, picks the category with the highest
    count. Only considers transactions that have a non-empty category.
    Returns dict mapping lowercase tegenpartij → category string.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT LOWER(tegenpartij) as tp, categorie, COUNT(*) as cnt
               FROM banktransacties
               WHERE categorie IS NOT NULL AND categorie != ''
                 AND tegenpartij IS NOT NULL AND tegenpartij != ''
               GROUP BY LOWER(tegenpartij), categorie
               ORDER BY LOWER(tegenpartij), cnt DESC""")
        rows = await cur.fetchall()

    # For each tegenpartij, take the first row (highest count due to ORDER BY)
    suggestions = {}
    for r in rows:
        tp = r['tp']
        if tp not in suggestions:
            suggestions[tp] = r['categorie']
    return suggestions
```

- [ ] **Step A4: Run tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_categorie_suggestions.py -v`
Expected: 4 passed.

- [ ] **Step A5: Run full suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step A6: Commit**

```bash
git add database.py tests/test_categorie_suggestions.py
git commit -m "feat: add get_categorie_suggestions() for bank page

Builds a tegenpartij→category lookup from past categorizations.
Case-insensitive grouping, picks most-used category per counterparty."
```

### Step group B: Wire into bank page UI

- [ ] **Step B1: Add import and load suggestions on page init**

In `pages/bank.py`, add `get_categorie_suggestions` to the import from database (line 11-16):

```python
from database import (
    get_banktransacties, get_imported_csv_bestanden,
    add_banktransacties, update_banktransactie,
    delete_banktransacties, find_factuur_matches, apply_factuur_matches,
    get_categorie_suggestions, get_db_ctx, DB_PATH,
)
```

Add a suggestion cache dict early in `bank_page()` (after line 30):

```python
    cat_suggestions = {'map': {}}  # lowercase tegenpartij → category

    async def load_suggestions():
        cat_suggestions['map'] = await get_categorie_suggestions(DB_PATH)
```

Call `await load_suggestions()` once at page init (before `refresh_table` is first called).

- [ ] **Step B2: Apply suggestions to uncategorized rows**

In the `load_transacties()` function (around line 32), after building each row dict, add suggestion logic. Find where rows are built (the `for t in transacties:` loop) and after setting the row's `categorie` field, apply the suggestion if the row has no category:

```python
        # Inside the row-building loop, after the row dict is created:
        if not t.categorie and t.tegenpartij:
            suggested = cat_suggestions['map'].get(t.tegenpartij.lower(), '')
            if suggested:
                row['suggested_categorie'] = suggested
```

Then update `refresh_table` to also reload suggestions (so new categorizations are picked up):

```python
    async def refresh_table():
        await load_suggestions()  # refresh suggestion cache
        # ... existing table refresh code
```

- [ ] **Step B3: Show suggestion hint in the category dropdown**

In the table's body slot template (around line 452-461), modify the `q-select` to show a hint when a suggestion exists. Replace the existing `q-select` with:

```html
<q-select
    v-model="props.row.categorie"
    :options='""" + json.dumps(BANK_CATEGORIEEN) + r"""'
    dense outlined
    emit-value map-options
    @update:model-value="(val) => $parent.$emit('cat_change', {id: props.row.id, cat: val})"
    style="min-width: 160px"
    :hint="props.row.suggested_categorie && !props.row.categorie ? 'Suggestie: ' + props.row.suggested_categorie : ''"
/>
```

Also add a small click handler that lets the user accept the suggestion with one click. Add a `q-icon` button next to the dropdown when a suggestion exists:

```html
<q-btn v-if="props.row.suggested_categorie && !props.row.categorie"
    icon="auto_fix_high" flat dense round size="xs" color="primary"
    :title="'Toepassen: ' + props.row.suggested_categorie"
    @click="() => { props.row.categorie = props.row.suggested_categorie; $parent.$emit('cat_change', {id: props.row.id, cat: props.row.suggested_categorie}) }"
/>
```

Wrap the existing `q-select` and this new button in a `<div style="display:flex;align-items:center;gap:4px">` container.

- [ ] **Step B4: Ensure suggested_categorie is in row data**

In `load_transacties()`, make sure every row dict always has the `suggested_categorie` key (empty string if no suggestion), so the Vue template doesn't error on missing property:

```python
        # Default for all rows:
        row['suggested_categorie'] = ''
        # Then apply suggestion if applicable:
        if not t.categorie and t.tegenpartij:
            suggested = cat_suggestions['map'].get(t.tegenpartij.lower(), '')
            if suggested:
                row['suggested_categorie'] = suggested
```

- [ ] **Step B5: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step B6: Manual verification**

Start the app, navigate to Bank page. Find an uncategorized transaction whose counterparty has been categorized before. Verify:
1. The hint text "Suggestie: [category]" appears below the dropdown
2. The magic wand icon appears next to the dropdown
3. Clicking the icon applies the suggestion and shows the success toast
4. After applying, the suggestion hint disappears (row now has a category)

- [ ] **Step B7: Commit**

```bash
git add pages/bank.py
git commit -m "feat: bank category suggestions from past categorizations

Shows hint + one-click apply button for uncategorized transactions
when the same counterparty was previously categorized."
```

---

## Final Verification

- [ ] **Run full test suite one last time**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all pass (624+ original + new tests).

- [ ] **Start the app and verify all features end-to-end**

```bash
source .venv/bin/activate && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py
```

Check:
1. Dashboard shows health alert banners (if applicable)
2. Jaarafsluiting definitief dialog shows pre-flight warnings
3. Bank page shows category suggestions for known counterparties
4. All existing functionality still works normally
