# Dashboard Redesign v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the dashboard with 3-tier visual hierarchy (hero KPIs with sparklines, secondary strip, contextual alerts) and real VA bank payment tracking via betalingskenmerk.

**Architecture:** Data-layer first (schema migration, CSV parser, VA query), then UI rewrite (dashboard page from scratch). The `kpi_card()` component is replaced by inline rendering in the dashboard since hero cards have a fundamentally different anatomy than the old cards. `kpi_strip()` for jaarafsluiting is unchanged.

**Tech Stack:** NiceGUI 3.x (Quasar/Vue), SQLite via aiosqlite, ECharts via `ui.echart`, Python 3.12+

**Spec:** `docs/superpowers/specs/2026-03-20-dashboard-redesign-v2.md`

**Test command:** `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `components/utils.py` | Modify | Add `decimals` param to `format_euro()` |
| `import_/rabobank_csv.py` | Modify | Capture `Betalingskenmerk` column |
| `database.py` | Modify | Migration **13** (betalingskenmerk), `add_banktransacties` INSERT, `get_banktransacties` mapping, new `get_va_betalingen()`, `backfill_betalingskenmerken()` |
| `models.py` | Modify | Add `betalingskenmerk` field to `Banktransactie` dataclass |
| `components/charts.py` | Modify | Monochromatic teal donut palette |
| `pages/dashboard.py` | Rewrite | Complete new layout with hero cards, sparklines, secondary strip, alerts |
| `pages/aangifte.py` | Modify | Add VA entry section (moved from dashboard) |
| `tests/test_bank_import.py` | Modify | Tests for betalingskenmerk in parser + CSV helper |
| `tests/test_db_queries.py` | Modify | Tests for `get_va_betalingen()` |
| `tests/test_dashboard.py` | Create | Tests for `format_euro(decimals=0)`, sparkline data, and hero card logic |

---

### Task 1: Add `decimals` parameter to `format_euro()`

**Files:**
- Modify: `components/utils.py:35-39`
- Test: `tests/test_dashboard.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_dashboard.py`:

```python
"""Tests voor dashboard redesign helpers."""

from components.utils import format_euro


def test_format_euro_default_2_decimals():
    assert format_euro(1234.56) == '\u20ac 1.234,56'


def test_format_euro_zero_decimals():
    assert format_euro(1234.56, decimals=0) == '\u20ac 1.235'


def test_format_euro_zero_decimals_thousands():
    assert format_euro(28702.52, decimals=0) == '\u20ac 28.703'


def test_format_euro_none_zero_decimals():
    assert format_euro(None, decimals=0) == '\u20ac 0'


def test_format_euro_negative_zero_decimals():
    assert format_euro(-8177.95, decimals=0) == '\u20ac -8.178'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: FAIL — `format_euro() got an unexpected keyword argument 'decimals'`

- [ ] **Step 3: Implement `decimals` parameter**

In `components/utils.py`, replace the `format_euro` function:

```python
def format_euro(value: float, decimals: int = 2) -> str:
    """Format als Nederlands bedrag: € 1.234,56 (or € 1.235 with decimals=0)"""
    if value is None:
        value = 0
    formatted = f"{value:,.{decimals}f}"
    return f"\u20ac {formatted}".replace(",", "X").replace(".", ",").replace("X", ".")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite to check no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all 418+ PASS (existing callers use default `decimals=2`)

- [ ] **Step 6: Commit**

```bash
git add components/utils.py tests/test_dashboard.py
git commit -m "feat: add decimals parameter to format_euro()"
```

---

### Task 2: Capture `Betalingskenmerk` in Rabobank CSV parser

**Files:**
- Modify: `import_/rabobank_csv.py:80-86`
- Modify: `tests/test_bank_import.py:26-41`

- [ ] **Step 1: Write failing test**

Add to `tests/test_bank_import.py` — first update `make_csv_row` to accept `betalingskenmerk` parameter, then add a test:

Update `make_csv_row` signature to:

```python
def make_csv_row(
    datum: str = "2026-01-15",
    bedrag: str = "-77,50",
    tegenrekening: str = "NL12RABO0123456789",
    tegenpartij: str = "Klant A",
    omschrijving1: str = "Betaling factuur",
    omschrijving2: str = "januari 2026",
    omschrijving3: str = "",
    betalingskenmerk: str = "",
) -> str:
    """Build a single Rabobank CSV data row."""
    return (
        f'"NL00TEST0000000001";"EUR";"RABONL2U";"000000000000001234";'
        f'"{datum}";"{datum}";"{bedrag}";"+1234,56";'
        f'"{tegenrekening}";"{tegenpartij}";"";"";"RABONL2U";"ba";"";"";"";"";'
        f'"{betalingskenmerk}";'
        f'"{omschrijving1}";"{omschrijving2}";"{omschrijving3}";"";"";"";""'
    )
```

Then add test:

```python
def test_parse_betalingskenmerk():
    """Betalingskenmerk column is captured when present."""
    csv_bytes = build_csv([
        make_csv_row(
            tegenrekening="NL86INGB0002445588",
            tegenpartij="Belastingdienst",
            bedrag="-2800,00",
            betalingskenmerk="0124412647060001",
            omschrijving1="",
        ),
        make_csv_row(
            tegenrekening="NL86INGB0002445588",
            tegenpartij="Belastingdienst",
            bedrag="-1808,00",
            betalingskenmerk="0124412647560014",
            omschrijving1="",
        ),
    ])
    result = parse_rabobank_csv(csv_bytes)
    assert len(result) == 2
    assert result[0]['betalingskenmerk'] == '0124412647060001'
    assert result[1]['betalingskenmerk'] == '0124412647560014'


def test_parse_empty_betalingskenmerk():
    """Missing betalingskenmerk defaults to empty string."""
    csv_bytes = build_csv([make_csv_row()])
    result = parse_rabobank_csv(csv_bytes)
    assert result[0].get('betalingskenmerk', '') == ''
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_bank_import.py::test_parse_betalingskenmerk -v`
Expected: FAIL — `KeyError: 'betalingskenmerk'`

- [ ] **Step 3: Add betalingskenmerk capture to parser**

In `import_/rabobank_csv.py`, add after line 78 (tegenrekening):

```python
        betalingskenmerk = row.get('Betalingskenmerk', '').strip().strip('"')
```

And add to the dict at line 85:

```python
            'betalingskenmerk': betalingskenmerk,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_bank_import.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add import_/rabobank_csv.py tests/test_bank_import.py
git commit -m "feat: capture Betalingskenmerk from Rabobank CSV"
```

---

### Task 3: Schema migration + `add_banktransacties` update

**Files:**
- Modify: `database.py` — MIGRATIONS list (~line 244), `add_banktransacties()` (~line 949)
- Test: `tests/test_bank_import.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_bank_import.py`:

```python
@pytest.mark.asyncio
async def test_add_banktransacties_with_betalingskenmerk(db):
    """Betalingskenmerk is stored when provided."""
    txns = [{
        'datum': '2026-02-23',
        'bedrag': -2800.0,
        'tegenrekening': 'NL86INGB0002445588',
        'tegenpartij': 'Belastingdienst',
        'omschrijving': '',
        'betalingskenmerk': '0124412647060001',
    }]
    count = await add_banktransacties(db, txns, csv_bestand='test.csv')
    assert count == 1

    result = await get_banktransacties(db)
    assert len(result) == 1
    assert result[0].betalingskenmerk == '0124412647060001'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_bank_import.py::test_add_banktransacties_with_betalingskenmerk -v`
Expected: FAIL — column `betalingskenmerk` does not exist

- [ ] **Step 3: Add migration and update INSERT**

In `database.py`, add migration **13** to the MIGRATIONS list (after version 12 at line 323, before the closing `]`):

```python
    (13, "add_betalingskenmerk_to_banktransacties", [
        "ALTER TABLE banktransacties ADD COLUMN betalingskenmerk TEXT DEFAULT ''",
    ]),
```

Update `add_banktransacties()` INSERT statement (line 987-992) to include betalingskenmerk:

```python
                await conn.execute(
                    """INSERT INTO banktransacties
                       (datum, bedrag, tegenrekening, tegenpartij, omschrijving,
                        betalingskenmerk, csv_bestand)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (t['datum'], t['bedrag'], t.get('tegenrekening', ''),
                     t.get('tegenpartij', ''), t.get('omschrijving', ''),
                     t.get('betalingskenmerk', ''), csv_bestand)
                )
```

Also update the `Banktransactie` dataclass in `models.py` to add the field:

```python
    betalingskenmerk: str = ''
```

Also update `get_banktransacties()` in `database.py` (line 937-946) to map the new column:

```python
        return [Banktransactie(
            id=r['id'], datum=r['datum'], bedrag=r['bedrag'],
            tegenrekening=r['tegenrekening'] or '',
            tegenpartij=r['tegenpartij'] or '',
            omschrijving=r['omschrijving'] or '',
            categorie=r['categorie'] or '',
            koppeling_type=r['koppeling_type'] or '',
            koppeling_id=r['koppeling_id'],
            csv_bestand=r['csv_bestand'] or '',
            betalingskenmerk=r['betalingskenmerk'] or '',
        ) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_bank_import.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add database.py models.py tests/test_bank_import.py
git commit -m "feat: add betalingskenmerk column to banktransacties (migration 10)"
```

---

### Task 4: `get_va_betalingen()` DB function

**Files:**
- Modify: `database.py` — add new function
- Test: `tests/test_db_queries.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_db_queries.py`:

```python
from database import get_va_betalingen

BELASTINGDIENST_IBAN = 'NL86INGB0002445588'


@pytest.mark.asyncio
async def test_get_va_betalingen_splits_ib_zvw(db):
    """VA payments are split by betalingskenmerk into IB and ZVW."""
    txns = [
        {'datum': '2026-02-23', 'bedrag': -2800.0,
         'tegenrekening': BELASTINGDIENST_IBAN, 'tegenpartij': 'Belastingdienst',
         'omschrijving': '', 'betalingskenmerk': '0124412647060001'},
        {'datum': '2026-01-22', 'bedrag': -1808.0,
         'tegenrekening': BELASTINGDIENST_IBAN, 'tegenpartij': 'Belastingdienst',
         'omschrijving': '', 'betalingskenmerk': '0124412647560014'},
    ]
    await add_banktransacties(db, txns)

    result = await get_va_betalingen(db, 2026)
    assert result['has_bank_data'] is True
    assert result['ib_betaald'] == pytest.approx(2800.0)
    assert result['ib_termijnen'] == 1
    assert result['zvw_betaald'] == pytest.approx(1808.0)
    assert result['zvw_termijnen'] == 1
    assert result['totaal_betaald'] == pytest.approx(4608.0)


@pytest.mark.asyncio
async def test_get_va_betalingen_no_data(db):
    """Returns has_bank_data=False when no Belastingdienst payments exist."""
    result = await get_va_betalingen(db, 2026)
    assert result['has_bank_data'] is False
    assert result['totaal_betaald'] == 0


@pytest.mark.asyncio
async def test_get_va_betalingen_no_kenmerk_fallback(db):
    """Without betalingskenmerk, sums all BD payments as combined."""
    txns = [
        {'datum': '2025-05-28', 'bedrag': -1900.0,
         'tegenrekening': BELASTINGDIENST_IBAN, 'tegenpartij': 'Belastingdienst',
         'omschrijving': '', 'betalingskenmerk': ''},
    ]
    await add_banktransacties(db, txns)

    result = await get_va_betalingen(db, 2025)
    assert result['has_bank_data'] is True
    assert result['totaal_betaald'] == pytest.approx(1900.0)
    # Without kenmerk, IB/ZVW split is unknown
    assert result['ib_termijnen'] == 0
    assert result['zvw_termijnen'] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py::test_get_va_betalingen_splits_ib_zvw -v`
Expected: FAIL — `ImportError: cannot import name 'get_va_betalingen'`

- [ ] **Step 3: Implement `get_va_betalingen()`**

Add to `database.py`:

```python
BELASTINGDIENST_IBAN = 'NL86INGB0002445588'


async def get_va_betalingen(db_path: Path = DB_PATH, jaar: int = 0) -> dict:
    """Get actual VA payments from bank transactions for a given year.

    Matches by Belastingdienst IBAN. Uses betalingskenmerk to split IB vs ZVW.
    The IB kenmerk contains digits '...X06...' pattern (lower), ZVW has '...X56...'
    (higher). When no kenmerk is available, all payments are summed as combined.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT ABS(bedrag) as amount, betalingskenmerk
               FROM banktransacties
               WHERE tegenrekening = ?
                 AND datum >= ? AND datum <= ?
                 AND bedrag < 0""",
            (BELASTINGDIENST_IBAN, f'{jaar}-01-01', f'{jaar}-12-31')
        )
        rows = await cur.fetchall()

    if not rows:
        return {
            'ib_betaald': 0, 'ib_termijnen': 0,
            'zvw_betaald': 0, 'zvw_termijnen': 0,
            'totaal_betaald': 0, 'has_bank_data': False,
        }

    ib_betaald = 0.0
    ib_count = 0
    zvw_betaald = 0.0
    zvw_count = 0
    unmatched = 0.0

    # IB kenmerken have lower digits at position 10-11 (03-06),
    # ZVW kenmerken have higher digits (53-56).
    # Reliable heuristic: if the 2-digit substring at pos 10 >= 50, it's ZVW.
    for amount, kenmerk in rows:
        if kenmerk and len(kenmerk) >= 12:
            year_type_digits = int(kenmerk[10:12])
            if year_type_digits >= 50:
                zvw_betaald += amount
                zvw_count += 1
            else:
                ib_betaald += amount
                ib_count += 1
        else:
            unmatched += amount

    return {
        'ib_betaald': round(ib_betaald, 2),
        'ib_termijnen': ib_count,
        'zvw_betaald': round(zvw_betaald, 2),
        'zvw_termijnen': zvw_count,
        'totaal_betaald': round(ib_betaald + zvw_betaald + unmatched, 2),
        'has_bank_data': True,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py -k va_betalingen -v`
Expected: all 3 PASS

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_db_queries.py
git commit -m "feat: add get_va_betalingen() — real VA payment tracking from bank"
```

---

### Task 5: Backfill migration for existing transactions

**Files:**
- Modify: `database.py` — add `backfill_betalingskenmerken()` + call from `init_db`

- [ ] **Step 1: Write failing test**

Add to `tests/test_bank_import.py`:

```python
from database import backfill_betalingskenmerken
import asyncio


@pytest.mark.asyncio
async def test_backfill_betalingskenmerken(db, tmp_path):
    """Backfill reads archived CSVs and updates betalingskenmerk on existing rows."""
    # Insert a transaction without betalingskenmerk
    txns = [{'datum': '2026-02-23', 'bedrag': -2800.0,
             'tegenrekening': 'NL86INGB0002445588',
             'tegenpartij': 'Belastingdienst', 'omschrijving': ''}]
    await add_banktransacties(db, txns)

    # Create a CSV archive that has the betalingskenmerk
    csv_dir = tmp_path / 'bank_csv'
    csv_dir.mkdir()
    csv_content = build_csv([
        make_csv_row(datum='23-02-2026', bedrag='-2.800,00',
                     tegenrekening='NL86INGB0002445588',
                     tegenpartij='Belastingdienst',
                     betalingskenmerk='0124412647060001',
                     omschrijving1=''),
    ])
    (csv_dir / 'test.csv').write_bytes(csv_content)

    count = await backfill_betalingskenmerken(db, csv_dir)
    assert count >= 1

    result = await get_banktransacties(db)
    assert result[0].betalingskenmerk == '0124412647060001'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_bank_import.py::test_backfill_betalingskenmerken -v`
Expected: FAIL — `ImportError: cannot import name 'backfill_betalingskenmerken'`

- [ ] **Step 3: Implement backfill function**

Add to `database.py`:

```python
async def backfill_betalingskenmerken(db_path: Path = DB_PATH,
                                       csv_dir: Path = None) -> int:
    """One-time backfill: read archived CSVs to populate betalingskenmerk
    on existing bank transactions that are missing it.

    Matches by (datum, bedrag, tegenpartij, omschrijving) — same dedup key
    as add_banktransacties. Returns count of rows updated.
    """
    from import_.rabobank_csv import parse_rabobank_csv

    if csv_dir is None:
        csv_dir = db_path.parent / 'bank_csv'
    if not csv_dir.exists():
        return 0

    # Check if backfill is needed: any BD transactions without kenmerk?
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT COUNT(*) FROM banktransacties
               WHERE tegenrekening = 'NL86INGB0002445588'
                 AND (betalingskenmerk IS NULL OR betalingskenmerk = '')"""
        )
        needs_backfill = (await cur.fetchone())[0]
    if needs_backfill == 0:
        return 0

    # Parse all archived CSVs
    kenmerk_map = {}  # (datum, bedrag, tegenpartij, omschrijving) -> kenmerk
    for csv_file in sorted(csv_dir.glob('*.csv')):
        try:
            content = csv_file.read_bytes()
            txns = parse_rabobank_csv(content)
            for t in txns:
                k = t.get('betalingskenmerk', '')
                if k:
                    key = (t['datum'], t['bedrag'],
                           t.get('tegenpartij', ''), t.get('omschrijving', ''))
                    kenmerk_map[key] = k
        except Exception:
            continue

    if not kenmerk_map:
        return 0

    # Update existing rows
    count = 0
    async with get_db_ctx(db_path) as conn:
        for key, kenmerk in kenmerk_map.items():
            cur = await conn.execute(
                """UPDATE banktransacties SET betalingskenmerk = ?
                   WHERE datum = ? AND bedrag = ? AND tegenpartij = ?
                     AND omschrijving = ?
                     AND (betalingskenmerk IS NULL OR betalingskenmerk = '')""",
                (kenmerk, *key)
            )
            count += cur.rowcount
        await conn.commit()
    return count
```

In `init_db()`, after all migrations are applied (after the migration loop), add:

```python
        # One-time backfill for betalingskenmerk
        await backfill_betalingskenmerken(db_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_bank_import.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add database.py tests/test_bank_import.py
git commit -m "feat: backfill betalingskenmerken from archived CSVs on startup"
```

---

### Task 6: Monochromatic donut chart palette

**Files:**
- Modify: `components/charts.py:6-15, 61-92`

- [ ] **Step 1: Update donut palette**

In `components/charts.py`, add a dedicated donut palette constant:

```python
DONUT_COLORS = ['#0F766E', '#14B8A6', '#5EEAD4', '#99F6E4']
```

Update `cost_donut_chart()` to use it:

```python
    'color': DONUT_COLORS,
```

Also update the legend to show below the donut with amounts, and update the chart layout:

```python
def cost_donut_chart(data: list[dict]) -> ui.echart:
    """Cost breakdown donut chart — monochromatic teal palette."""
    chart_data = [
        {'value': round(d['totaal'], 2), 'name': d['categorie']}
        for d in data if d['totaal'] > 0
    ]

    return ui.echart({
        'tooltip': {
            'trigger': 'item',
            'formatter': '{b}: \u20ac {c} ({d}%)',
        },
        'legend': {
            'orient': 'vertical',
            'left': 'center',
            'bottom': '0%',
            'textStyle': {'color': '#475569', 'fontSize': 12},
            'itemWidth': 8,
            'itemHeight': 8,
            'icon': 'circle',
        },
        'color': DONUT_COLORS,
        'series': [{
            'type': 'pie',
            'radius': ['40%', '70%'],
            'center': ['50%', '40%'],
            'avoidLabelOverlap': True,
            'itemStyle': {'borderRadius': 6, 'borderColor': '#fff', 'borderWidth': 2},
            'label': {'show': False},
            'emphasis': {
                'label': {'show': True, 'fontSize': 14, 'fontWeight': 'bold'},
            },
            'data': chart_data,
        }],
    }).classes('w-full h-72')
```

- [ ] **Step 2: Run full test suite (no chart-specific tests exist)**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add components/charts.py
git commit -m "feat: monochromatic teal palette for cost donut chart"
```

---

### Task 7: Rewrite dashboard page — layout skeleton + hero KPIs

**Files:**
- Rewrite: `pages/dashboard.py`

This is the largest task. Replace the entire rendering logic in `refresh_dashboard()`. We keep the data-fetching structure but rewrite all UI rendering.

- [ ] **Step 1: Rewrite the page skeleton and header row**

Replace lines 36-61 (the page skeleton) with the new layout:

```python
    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):

        # Header row: title + quick actions + year selector
        with ui.row().classes('w-full items-center'):
            page_title('Overzicht')
            ui.space()
            with ui.row().classes('gap-2 items-center'):
                ui.button('Werkdag', icon='add',
                           on_click=lambda: ui.navigate.to('/werkdagen')) \
                    .props('flat dense').classes('text-caption') \
                    .style('background: white; border: 1px solid #E2E8F0; border-radius: 8px; color: #475569')
                ui.button('Factuur', icon='add',
                           on_click=lambda: ui.navigate.to('/facturen')) \
                    .props('flat dense').classes('text-caption') \
                    .style('background: white; border: 1px solid #E2E8F0; border-radius: 8px; color: #475569')
                jaar_select = ui.select(
                    jaren, value=huidig_jaar, label='Jaar',
                ).classes('w-28')

        # Content containers (filled by refresh_dashboard)
        content_container = {'ref': None}
        content_container['ref'] = ui.column().classes('w-full gap-5')
```

- [ ] **Step 2: Rewrite `refresh_dashboard()` data fetching**

Update the `asyncio.gather` call to include `get_va_betalingen`:

```python
        (kpis, kpis_vorig, omzet_huidig, omzet_vorig, kosten_per_cat,
         openstaande, ongefact, km_data,
         ib_resultaat, fp, va_data) = await asyncio.gather(
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
        )
```

Add import for `get_va_betalingen` at top of file.

- [ ] **Step 3: Render hero KPI cards with sparklines**

Inside the cleared content container, render the 3-card hero grid:

```python
        container = content_container['ref']
        container.clear()
        with container:
            # Hero KPI cards
            with ui.element('div').style(
                    'display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px'):

                # Card 1: Bruto omzet
                with ui.card().classes('q-pa-lg').style(
                        'border-radius: 14px; border: 1px solid #E2E8F0; cursor: pointer') \
                        .on('click', lambda: ui.navigate.to('/werkdagen')):
                    with ui.row().classes('w-full justify-between items-center'):
                        ui.label('Bruto omzet').style(
                            'font-size: 13px; color: #64748B; font-weight: 500')
                        delta = _yoy_delta(kpis['omzet'], vorig_ytd_omzet)
                        if delta is not None:
                            _render_delta_badge(delta)
                    ui.label(format_euro(kpis['omzet'], decimals=0)).style(
                        'font-size: 30px; font-weight: 700; color: #0F172A; '
                        'font-variant-numeric: tabular-nums; margin: 6px 0 2px')
                    if vorig_ytd_omzet > 0:
                        ui.label(f'vs {format_euro(vorig_ytd_omzet, decimals=0)} vorig jaar') \
                            .style('font-size: 12px; color: #94A3B8')
                    # Sparkline
                    if any(v > 0 for v in omzet_huidig):
                        _render_sparkline(omzet_huidig, '#0F766E')
```

Implement helper functions `_render_delta_badge()` and `_render_sparkline()`:

```python
    def _render_delta_badge(delta_pct: float):
        """Render YoY delta pill badge."""
        color = '#059669' if delta_pct >= 0 else '#DC2626'
        bg = '#ECFDF5' if delta_pct >= 0 else '#FEF2F2'
        arrow = '\u2191' if delta_pct >= 0 else '\u2193'
        sign = '+' if delta_pct > 0 else ''
        ui.label(f'{arrow} {sign}{delta_pct:.0f}%').style(
            f'font-size: 12px; font-weight: 600; color: {color}; '
            f'background: {bg}; padding: 2px 8px; border-radius: 10px')

    def _render_sparkline(monthly_data: list[float], color: str):
        """Render an ECharts mini sparkline inside a KPI card."""
        months = ['J', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']
        ui.echart({
            'grid': {'top': 0, 'bottom': 0, 'left': 0, 'right': 0},
            'xAxis': {'show': False, 'type': 'category', 'data': months},
            'yAxis': {'show': False, 'type': 'value', 'min': 0},
            'series': [{
                'type': 'line', 'data': monthly_data, 'smooth': True,
                'symbol': 'none',
                'lineStyle': {'width': 2, 'color': color},
                'areaStyle': {
                    'color': {
                        'type': 'linear', 'x': 0, 'y': 0, 'x2': 0, 'y2': 1,
                        'colorStops': [
                            {'offset': 0, 'color': f'{color}20'},
                            {'offset': 1, 'color': f'{color}00'},
                        ],
                    },
                },
            }],
            'tooltip': {'show': False},
        }).style('height: 36px; width: 100%; margin-top: 14px')
```

Then Card 2 (Bedrijfswinst):

```python
                # Card 2: Bedrijfswinst
                ytd_winst = ib_resultaat['ytd_winst'] if ib_resultaat else (
                    kpis['omzet'] - kpis['kosten'])
                winst_color = '#059669' if ytd_winst >= 0 else '#DC2626'
                with ui.card().classes('q-pa-lg').style(
                        'border-radius: 14px; border: 1px solid #E2E8F0'):
                    with ui.row().classes('w-full justify-between items-center'):
                        ui.label('Bedrijfswinst').style(
                            'font-size: 13px; color: #64748B; font-weight: 500')
                        vorig_winst = vorig_ytd_omzet - vorig_ytd_kosten
                        delta = _yoy_delta(ytd_winst, vorig_winst) if vorig_winst else None
                        if delta is not None:
                            _render_delta_badge(delta)
                    ui.label(format_euro(ytd_winst, decimals=0)).style(
                        f'font-size: 30px; font-weight: 700; color: {winst_color}; '
                        'font-variant-numeric: tabular-nums; margin: 6px 0 2px')
                    if vorig_winst and vorig_winst > 0:
                        ui.label(f'vs {format_euro(vorig_winst, decimals=0)} vorig jaar') \
                            .style('font-size: 12px; color: #94A3B8')
                    if any(v > 0 for v in omzet_huidig):
                        _render_sparkline(omzet_huidig, '#059669')
```

Then Card 3 (Belasting prognose) with confidence badge, progress bar, and VA data:

```python
                # Card 3: Belasting prognose
                with ui.card().classes('q-pa-lg').style(
                        'border-radius: 14px; border: 1px solid #E2E8F0; cursor: pointer') \
                        .on('click', lambda: ui.navigate.to('/aangifte')):

                    if ib_resultaat is not None:
                        has_va = (fp and (fp.voorlopige_aanslag_betaald or 0) > 0)
                        resultaat = ib_resultaat['resultaat']
                        confidence = ib_resultaat.get('confidence', 'low')

                        # Header with confidence badge
                        with ui.row().classes('w-full justify-between items-center'):
                            ui.label('Belasting prognose').style(
                                'font-size: 13px; color: #64748B; font-weight: 500')
                            # Confidence pill badge
                            conf_map = {
                                'low': ('Schatting', '#D97706', '#FEF3C7'),
                                'medium': ('Prognose', '#0369A1', '#F0F9FF'),
                                'high': ('Betrouwbaar', '#059669', '#ECFDF5'),
                            }
                            c_label, c_color, c_bg = conf_map.get(
                                confidence, conf_map['low'])
                            ui.label(c_label).style(
                                f'font-size: 11px; font-weight: 500; color: {c_color}; '
                                f'background: {c_bg}; padding: 2px 8px; border-radius: 10px')

                        if has_va:
                            # Bij/terug display
                            if resultaat >= 0:
                                val_text = f'Bij: {format_euro(resultaat, decimals=0)}'
                                val_color = '#DC2626'
                            else:
                                val_text = f'Terug: {format_euro(abs(resultaat), decimals=0)}'
                                val_color = '#059669'
                            ui.label(val_text).style(
                                f'font-size: 30px; font-weight: 700; color: {val_color}; '
                                'font-variant-numeric: tabular-nums; margin: 6px 0 2px')
                            ui.label(f'o.b.v. {ib_resultaat["basis_maanden"]} maanden') \
                                .style('font-size: 12px; color: #94A3B8; margin-bottom: 16px')

                            # Progress bar: berekend vs VA betaald
                            berekend = ib_resultaat['netto_ib'] + ib_resultaat['zvw']
                            if va_data['has_bank_data']:
                                va_betaald = va_data['totaal_betaald']
                            else:
                                va_betaald = (ib_resultaat['va_ib_betaald']
                                              + ib_resultaat['va_zvw_betaald'])
                            with ui.row().classes('w-full justify-between').style(
                                    'font-size: 11px; color: #64748B; margin-bottom: 5px'):
                                ui.label(f'Berekend {format_euro(berekend, decimals=0)}')
                                va_label = 'VA betaald' if va_data['has_bank_data'] else 'VA geschat'
                                ui.label(f'{va_label} {format_euro(va_betaald, decimals=0)}')
                            ratio = min(berekend / (berekend + va_betaald), 1.0) if (berekend + va_betaald) > 0 else 0.5
                            ui.linear_progress(value=ratio, size='5px') \
                                .style('border-radius: 3px') \
                                .props('color=negative track-color=grey-3')

                            # Termijn info from real bank data
                            if va_data['has_bank_data']:
                                if va_data['ib_termijnen'] > 0 or va_data['zvw_termijnen'] > 0:
                                    parts = []
                                    if va_data['ib_termijnen'] > 0:
                                        parts.append(f'{va_data["ib_termijnen"]} IB')
                                    if va_data['zvw_termijnen'] > 0:
                                        parts.append(f'{va_data["zvw_termijnen"]} ZVW')
                                    termijn_text = ' \u00b7 '.join(parts) + ' termijnen'
                                else:
                                    total_t = va_data['ib_termijnen'] + va_data['zvw_termijnen']
                                    termijn_text = f'{total_t} betalingen'
                                ui.label(termijn_text).style(
                                    'font-size: 10px; color: #94A3B8; margin-top: 6px; text-align: right')
                        else:
                            # No VA data — show estimated tax total
                            total_tax = ib_resultaat['netto_ib'] + ib_resultaat['zvw']
                            ui.label(format_euro(total_tax, decimals=0)).style(
                                'font-size: 30px; font-weight: 700; color: #0F172A; '
                                'font-variant-numeric: tabular-nums; margin: 6px 0 2px')
                            ui.label('Geschatte belasting').style(
                                'font-size: 12px; color: #94A3B8')
                            ui.label('VA invoeren \u2192').style(
                                'font-size: 12px; color: #0F766E; cursor: pointer; margin-top: 8px')
                    else:
                        # No fiscal data at all
                        ui.label('Belasting prognose').style(
                            'font-size: 13px; color: #64748B; font-weight: 500')
                        ui.label('Geen gegevens').style(
                            'font-size: 14px; color: #94A3B8; margin-top: 8px')
```

- [ ] **Step 4: Test manually — start the app**

Run: `source .venv/bin/activate && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py`
Open: http://127.0.0.1:8085
Verify: 3 hero cards render with sparklines and correct data

- [ ] **Step 5: Commit**

```bash
git add pages/dashboard.py
git commit -m "feat: dashboard hero KPI cards with sparklines and real VA data"
```

---

### Task 8: Secondary strip + charts + aandachtspunten

**Files:**
- Modify: `pages/dashboard.py` (continue the rewrite)

- [ ] **Step 1: Render secondary metrics strip**

After the hero cards grid, add:

```python
            # Secondary metrics strip
            with ui.row().classes('w-full gap-3'):
                # Uren
                uren = kpis.get('uren', 0)
                uren_pct = round(uren / uren_criterium * 100) if uren_criterium else 0
                with ui.card().classes('flex-1 q-pa-sm').style(
                        'border-radius: 10px; border: 1px solid #E2E8F0; '
                        'display: flex; align-items: center; gap: 10px; flex-direction: row'):
                    ui.icon('schedule', size='20px').style('color: #D97706')
                    with ui.column().classes('flex-1 gap-0'):
                        with ui.row().classes('w-full justify-between items-baseline'):
                            ui.label(f'{uren:,.0f} / {uren_criterium:,} uur').style(
                                'font-size: 14px; font-weight: 600; color: #0F172A')
                            ui.label(f'{uren_pct}%').style(
                                'font-size: 11px; color: #94A3B8')
                        bar_color = '#059669' if uren_pct >= 100 else '#D97706'
                        ui.linear_progress(
                            value=min(uren_pct / 100, 1.0), size='3px',
                            color=bar_color,
                        ).style('margin-top: 6px')

                # Km (only if > 0)
                km = km_data.get('km', 0) if km_data else 0
                km_bedrag = km_data.get('vergoeding', 0) if km_data else 0
                if km > 0:
                    with ui.card().classes('flex-1 q-pa-sm').style(
                            'border-radius: 10px; border: 1px solid #E2E8F0; '
                            'display: flex; align-items: center; gap: 10px; flex-direction: row'):
                        ui.icon('directions_car', size='20px').style('color: #0F766E')
                        with ui.row().classes('items-baseline gap-1'):
                            ui.label(f'{km:,.0f} km').style(
                                'font-size: 14px; font-weight: 600; color: #0F172A')
                            ui.label(format_euro(km_bedrag)).style(
                                'font-size: 12px; color: #94A3B8')

                # Documenten
                docs_done = sum(1 for d in await get_aangifte_documenten(DB_PATH, jaar)
                                if d.bestandspad)
                docs_total = len(AANGIFTE_DOCS)
                docs_pct = round(docs_done / docs_total * 100) if docs_total else 0
                with ui.card().classes('flex-1 q-pa-sm').style(
                        'border-radius: 10px; border: 1px solid #E2E8F0; '
                        'display: flex; align-items: center; gap: 10px; flex-direction: row'):
                    ui.icon('folder_open', size='20px').style(
                        f'color: {"#059669" if docs_pct >= 100 else "#D97706"}')
                    with ui.column().classes('flex-1 gap-0'):
                        with ui.row().classes('w-full justify-between items-baseline'):
                            ui.label(f'{docs_done} / {docs_total} documenten').style(
                                'font-size: 14px; font-weight: 600; color: #0F172A')
                            ui.label(f'{docs_pct}%').style('font-size: 11px; color: #94A3B8')
                        bar_color = '#059669' if docs_pct >= 100 else '#D97706'
                        ui.linear_progress(
                            value=min(docs_pct / 100, 1.0), size='3px', color=bar_color,
                        ).style('margin-top: 6px')
```

- [ ] **Step 2: Render charts (60/40 split)**

```python
            # Charts
            with ui.element('div').style(
                    'display: grid; grid-template-columns: 3fr 2fr; gap: 20px'):
                with ui.card().classes('q-pa-lg').style(
                        'border-radius: 14px; border: 1px solid #E2E8F0'):
                    with ui.row().classes('w-full justify-between items-baseline'):
                        ui.label('Omzet per maand').style(
                            'font-size: 15px; font-weight: 600; color: #0F172A')
                        ui.label(f'{jaar} vs {jaar - 1}').style(
                            'font-size: 12px; color: #94A3B8')
                    revenue_bar_chart(omzet_huidig, omzet_vorig, jaar)

                with ui.card().classes('q-pa-lg').style(
                        'border-radius: 14px; border: 1px solid #E2E8F0'):
                    ui.label('Kostenverdeling').style(
                        'font-size: 15px; font-weight: 600; color: #0F172A')
                    if any(d['totaal'] > 0 for d in kosten_per_cat):
                        cost_donut_chart(kosten_per_cat)
                    else:
                        with ui.element('div').style(
                                'display: flex; align-items: center; justify-content: center; '
                                'height: 200px'):
                            ui.label('Nog geen kosten dit jaar').style(
                                'font-size: 14px; color: #94A3B8')
```

- [ ] **Step 3: Render aandachtspunten (contextual alerts)**

```python
            # Aandachtspunten — only if there are items
            has_ongefact = ongefact and ongefact.get('aantal', 0) > 0
            has_openstaand = len(openstaande) > 0
            if has_ongefact or has_openstaand:
                ui.label('AANDACHTSPUNTEN').style(
                    'font-size: 13px; font-weight: 600; color: #64748B; '
                    'text-transform: uppercase; letter-spacing: 0.05em')

                if has_ongefact:
                    with ui.element('div').style(
                            'background: #FFFBEB; border-radius: 10px; padding: 14px 18px; '
                            'border: 1px solid #FDE68A; display: flex; align-items: center; '
                            'justify-content: space-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('pending_actions', size='20px').style('color: #D97706')
                            ui.html(
                                f'<span style="font-size:13px;font-weight:600;color:#92400E">'
                                f'{ongefact["aantal"]} werkdagen ongefactureerd</span>'
                                f'<span style="font-size:12px;color:#A16207;margin-left:8px">'
                                f'{format_euro(ongefact["bedrag"])}</span>')
                        ui.button('Bekijk',
                                  on_click=lambda: ui.navigate.to('/werkdagen')) \
                            .props('flat dense size=sm') \
                            .style('border: 1px solid #D97706; border-radius: 6px; '
                                   'color: #D97706; font-size: 12px')

                if has_openstaand:
                    totaal = sum(f.bedrag for f in openstaande)
                    oudste = max((date.today() - date.fromisoformat(f.datum)).days
                                 for f in openstaande)
                    with ui.element('div').style(
                            'background: #FFF7ED; border-radius: 10px; padding: 14px 18px; '
                            'border: 1px solid #FED7AA; display: flex; align-items: center; '
                            'justify-content: space-between'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('receipt_long', size='20px').style('color: #EA580C')
                            ui.html(
                                f'<span style="font-size:13px;font-weight:600;color:#9A3412">'
                                f'{len(openstaande)} facturen openstaand</span>'
                                f'<span style="font-size:12px;color:#C2410C;margin-left:8px">'
                                f'{format_euro(totaal)} \u00b7 oudste {oudste} dagen</span>')
                        ui.button('Bekijk',
                                  on_click=lambda: ui.navigate.to('/facturen')) \
                            .props('flat dense size=sm') \
                            .style('border: 1px solid #EA580C; border-radius: 6px; '
                                   'color: #EA580C; font-size: 12px')
```

- [ ] **Step 4: Remove old code**

Delete from `pages/dashboard.py`:
- The entire `open_va_dialog()` function and its surrounding logic (~lines 279-431)
- The old KPI card rendering (replace with new)
- The openstaande facturen detail table
- The old "quick actions" row
- Import of `kpi_card` from `components.kpi_card` (no longer used on dashboard)

Keep the `kpi_card` import ONLY if it's still referenced. Check: if `kpi_card` is only used in dashboard.py, remove the import. `kpi_strip` in jaarafsluiting.py is unaffected.

- [ ] **Step 5: Test manually**

Run: `source .venv/bin/activate && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py`
Open: http://127.0.0.1:8085
Verify all sections render: hero cards, secondary strip, charts (60/40), aandachtspunten

- [ ] **Step 6: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add pages/dashboard.py
git commit -m "feat: complete dashboard redesign — secondary strip, charts, alerts"
```

---

### Task 9: Update `_compute_ib_estimate()` to use real VA data

**Files:**
- Modify: `pages/dashboard.py` — `_compute_ib_estimate()` function

- [ ] **Step 1: Update the function to return VA source info**

In `_compute_ib_estimate()`, the VA data is now fetched separately via `get_va_betalingen()` in the `asyncio.gather`. Update the return dict to include a flag for whether real VA data was used:

The function itself does not need to call `get_va_betalingen()` — that happens in `refresh_dashboard()`. Instead, the Belasting prognose card rendering logic checks `va_data['has_bank_data']` to decide whether to show real or estimated VA amounts:

```python
# In the Belasting prognose card rendering:
if va_data['has_bank_data']:
    va_betaald = va_data['totaal_betaald']
    va_label = f'VA betaald {format_euro(va_betaald, decimals=0)}'
    # Termijn info
    if va_data['ib_termijnen'] > 0 or va_data['zvw_termijnen'] > 0:
        termijn_parts = []
        if va_data['ib_termijnen'] > 0:
            termijn_parts.append(f'{va_data["ib_termijnen"]} IB')
        if va_data['zvw_termijnen'] > 0:
            termijn_parts.append(f'{va_data["zvw_termijnen"]} ZVW')
        termijn_text = ' · '.join(termijn_parts) + ' termijnen'
    else:
        termijn_text = f'{va_data["ib_termijnen"] + va_data["zvw_termijnen"]} betalingen'
else:
    # Fallback to proration
    va_betaald = ib_resultaat['va_ib_betaald'] + ib_resultaat['va_zvw_betaald']
    va_label = f'VA geschat {format_euro(va_betaald, decimals=0)}'
    termijn_text = '(prognose)'
```

- [ ] **Step 2: Test manually with real data**

Run the app and verify:
- 2026: should show real VA amounts (€2,800 IB + €1,808 ZVW = €4,608) with "1 IB · 1 ZVW termijnen"
- 2025: should show real VA amounts with correct termijn counts
- 2024: should show real VA amounts

- [ ] **Step 3: Commit**

```bash
git add pages/dashboard.py
git commit -m "feat: belasting prognose uses real VA bank payments when available"
```

---

### Task 10: Move VA entry dialog to Aangifte page

**Files:**
- Modify: `pages/aangifte.py`
- Source: `pages/dashboard.py` (copy `open_va_dialog` logic, then delete original)

The VA dialog code (~lines 279-425 in the old dashboard) allows entering VA IB and VA ZVW annual amounts + uploading PDF beschikkingen. This must be accessible from the Aangifte page.

- [ ] **Step 1: Add VA section to Aangifte page**

In `pages/aangifte.py`, add a "Voorlopige aanslagen" section. Place it near the top of the aangifte page content (before the invulhulp tabs), as a card with:
- Two number inputs: VA IB (jaarbedrag) and VA ZVW (jaarbedrag)
- Two PDF upload fields (for IB and ZVW beschikkingen)
- Checkmarks for already-uploaded documents
- Save button

Reuse the same logic from the old `open_va_dialog()` but render it as a persistent card section (not a dialog popup), since this is a settings-style page.

The inputs should call `update_ib_inputs()` to save the amounts and `add_aangifte_document()` for PDF uploads — same functions as before.

- [ ] **Step 2: Verify VA entry works**

Run the app, navigate to /aangifte, enter VA amounts, upload a PDF. Verify the amounts are saved and reflected in the dashboard Belasting prognose card.

- [ ] **Step 3: Commit**

```bash
git add pages/aangifte.py
git commit -m "feat: move VA entry to aangifte page"
```

---

### Task 11: Final cleanup and full verification

- [ ] **Step 1: Remove unused imports from dashboard.py**

Check and remove: `update_ib_inputs`, `add_aangifte_document` (moved to aangifte), `kpi_card` import.

- [ ] **Step 2: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 3: Test all dashboard states manually**

- 2026 (current year, partial data): hero cards with sparklines, extrapolation, real VA
- 2025 (full year): all sections populated, YoY deltas
- 2024 (full year): all sections populated
- 2023 (limited data): graceful empty states

- [ ] **Step 4: Verify other pages still work**

Navigate through: Werkdagen, Facturen, Kosten, Bank, Jaarafsluiting, Aangifte, Documenten, Klanten, Instellingen. Ensure no regressions from `format_euro()` change or chart updates.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: dashboard redesign cleanup — remove unused imports"
```
