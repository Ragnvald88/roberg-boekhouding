# Bank / Kosten consolidation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse `/bank` and `/kosten` into one transaction-inbox (`/transacties`) + one read-only overview (`/kosten`). Eliminate duplicate decision surfaces. Roll in v1.1 polish items M1/M5/M7 while the code is being touched anyway.

**Architecture:** One small DDL migration (unique partial index on `uitgaven.bank_tx_id`). Four new DB helpers (`get_transacties_view`, `get_kosten_breakdown`, `get_kosten_per_maand`, `get_terugkerende_kosten`) + one targeted helper (`get_uitgave_by_id`) + one updated helper (`get_categorie_suggestions`). New page `pages/transacties.py` (absorbs old `bank.py` + most of `kosten.py`). New component `components/transacties_dialog.py` (extracted detail dialog). Slimmed `pages/kosten.py` (overview only). Sidebar relabel + soft-redirect `/bank → /transacties`. Rename `KostenRow → TransactieRow`, `kosten_helpers → transacties_helpers`. No fiscal code touched.

**Tech Stack:** Python 3.12+ · NiceGUI ≥3.0 (Quasar/Vue) · aiosqlite · raw SQL with `?` placeholders · pytest-asyncio · pywebview (native).

**Spec:** `docs/superpowers/specs/2026-04-22-bank-kosten-consolidation-design.md` — **source of truth**. If plan and spec disagree, stop and reconcile.

**Test command:**
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

---

## File map

**New:**
- `components/transacties_dialog.py` — Detail/Factuur/Historie dialog, extracted from `pages/kosten.py`
- `pages/transacties.py` — the inbox page
- `tests/test_migration_28.py`
- `tests/test_get_transacties_view.py`
- `tests/test_get_uitgave_by_id.py`
- `tests/test_get_kosten_breakdown.py`
- `tests/test_get_kosten_per_maand.py`
- `tests/test_get_terugkerende_kosten.py`
- `tests/test_get_categorie_suggestions_debits.py`

**Modified:**
- `database.py` — migration #28, 4 new + 1 new-targeted helpers, 1 updated helper (`get_categorie_suggestions`), expanded `derive_status`, new `TransactieRow` dataclass
- `components/kosten_helpers.py` → renamed `components/transacties_helpers.py`, `derive_status` expanded
- `pages/kosten.py` — shrunk to overview (KPI + per-maand chart + breakdown + terugkerende + activastaat tab)
- `pages/bank.py` — becomes a 10-line redirect stub
- `components/layout.py` — sidebar label "Bank" → "Transacties"
- `tests/test_kosten_helpers.py` → renamed `tests/test_transacties_helpers.py`, cases added for new statuses
- Multiple test files — replace `KostenRow` → `TransactieRow`, `get_kosten_view` → `get_transacties_view` where applicable
- `CLAUDE.md`

**Untouched:**
- `pages/kosten_investeringen.py`, `pages/facturen.py`, `pages/werkdagen.py`, `pages/dashboard.py`, all `fiscal/*`, `components/mail_*`, `components/invoice_generator.py`, `import_/*` (except `expense_utils.py` behaviour is called differently), `database.py` fiscal functions.

---

## Phase 1 — DB layer (Tasks 1-10)

All Phase 1 tasks are zero-UI-impact. `/bank` and `/kosten` continue to work unchanged. After Task 10, full test suite must be green.

---

### Task 1: Migration 28 — unique partial index on `uitgaven.bank_tx_id`

Closes the duplicate-link race (M1 polish item). Partial index allows NULL (cash uitgaven); enforces at-most-one-uitgave per bank_tx at DB level.

**Files:**
- Modify: `database.py` — add entry at end of `MIGRATIONS` list (currently ends line 463 with `(27, …)`)
- Create: `tests/test_migration_28.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration_28.py`:
```python
"""Migration #28 — unique partial index on uitgaven.bank_tx_id (NULL allowed)."""
import aiosqlite
import pytest


async def _index_exists(db_path, index_name: str) -> bool:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute("PRAGMA index_list(uitgaven)")
        return index_name in {r[1] for r in await cur.fetchall()}


@pytest.mark.asyncio
async def test_migration_28_creates_unique_partial_index(db):
    assert await _index_exists(db, "idx_uitgaven_bank_tx_unique")


@pytest.mark.asyncio
async def test_migration_28_enforces_uniqueness_on_non_null(db):
    async with aiosqlite.connect(db) as conn:
        # Seed one bank tx + one linked uitgave
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand) "
            "VALUES (1, '2026-03-01', -50.0, 'KPN', '', '', 't.csv')")
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id) VALUES ('2026-03-01', 'Telefoon/KPN', '', 50.0, 1)")
        await conn.commit()

        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
                "bank_tx_id) VALUES ('2026-03-01', 'Telefoon/KPN', '', 50.0, 1)")
            await conn.commit()


@pytest.mark.asyncio
async def test_migration_28_allows_multiple_null_bank_tx_id(db):
    """Cash uitgaven (bank_tx_id NULL) must stay allowed."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id) VALUES ('2026-03-01', 'Bankkosten', 'a', 1.0, NULL)")
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id) VALUES ('2026-03-02', 'Bankkosten', 'b', 2.0, NULL)")
        await conn.commit()
        cur = await conn.execute(
            "SELECT COUNT(*) FROM uitgaven WHERE bank_tx_id IS NULL")
        assert (await cur.fetchone())[0] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_migration_28.py -v
```
Expected: 3 failures (index does not exist; duplicate insert succeeds).

- [ ] **Step 3: Add migration 28 to the `MIGRATIONS` list**

Edit `database.py`, replace the closing `]` of `MIGRATIONS` (line 464) with:

```python
    (27, "migrate_bank_categorie_to_uitgaven", None),
    (28, "unique_partial_index_uitgaven_bank_tx", [
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_uitgaven_bank_tx_unique "
        "ON uitgaven(bank_tx_id) WHERE bank_tx_id IS NOT NULL",
    ]),
]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_migration_28.py -v
```
Expected: 3 passes.

- [ ] **Step 5: Run full suite to ensure no regressions**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add database.py tests/test_migration_28.py
git commit -m "feat(db): migratie 28 — unique partial index on uitgaven.bank_tx_id"
```

---

### Task 2: Expand `derive_status` to 8 sign-aware cases

Spec §4.1 steps 1-8. Current 4 statuses (`hidden`/`ongecategoriseerd`/`ontbreekt`/`compleet`) expand to 6 (`prive_verborgen`/`gekoppeld_factuur`/`ongecategoriseerd`/`ontbreekt_bon`/`compleet`/`gecategoriseerd`). File stays `components/kosten_helpers.py` for this task; renamed in Task 23.

**Files:**
- Modify: `components/kosten_helpers.py:9-24` (function body)
- Modify: `tests/test_kosten_helpers.py` (cases added; existing 4 cases rewritten with new keys)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_kosten_helpers.py`:
```python
def test_derive_status_prive_verborgen_wins():
    row = {"id_bank": 1, "id_uitgave": 5, "genegeerd": 1,
           "categorie": "Telefoon/KPN", "pdf_pad": "/p.pdf",
           "bedrag": -10.0, "koppeling_type": None}
    from components.kosten_helpers import derive_status
    assert derive_status(row) == "prive_verborgen"


def test_derive_status_gekoppeld_factuur_for_positive_with_match():
    row = {"id_bank": 1, "id_uitgave": None, "genegeerd": 0,
           "categorie": "", "pdf_pad": "",
           "bedrag": 100.0, "koppeling_type": "factuur", "koppeling_id": 42}
    from components.kosten_helpers import derive_status
    assert derive_status(row) == "gekoppeld_factuur"


def test_derive_status_gecategoriseerd_positive():
    row = {"id_bank": 1, "id_uitgave": None, "genegeerd": 0,
           "categorie": "Omzet", "pdf_pad": "",
           "bedrag": 200.0, "koppeling_type": None}
    from components.kosten_helpers import derive_status
    assert derive_status(row) == "gecategoriseerd"


def test_derive_status_ongecategoriseerd_positive():
    row = {"id_bank": 2, "id_uitgave": None, "genegeerd": 0,
           "categorie": "", "pdf_pad": "",
           "bedrag": 300.0, "koppeling_type": None}
    from components.kosten_helpers import derive_status
    assert derive_status(row) == "ongecategoriseerd"


def test_derive_status_debit_ontbreekt_bon():
    row = {"id_bank": 3, "id_uitgave": 9, "genegeerd": 0,
           "categorie": "Kleine aankopen", "pdf_pad": "",
           "bedrag": -50.0, "koppeling_type": None}
    from components.kosten_helpers import derive_status
    assert derive_status(row) == "ontbreekt_bon"


def test_derive_status_debit_compleet():
    row = {"id_bank": 4, "id_uitgave": 11, "genegeerd": 0,
           "categorie": "Kleine aankopen", "pdf_pad": "/tmp/x.pdf",
           "bedrag": -50.0, "koppeling_type": None}
    from components.kosten_helpers import derive_status
    assert derive_status(row) == "compleet"


def test_derive_status_debit_ongecategoriseerd_no_uitgave():
    row = {"id_bank": 5, "id_uitgave": None, "genegeerd": 0,
           "categorie": "", "pdf_pad": "",
           "bedrag": -10.0, "koppeling_type": None}
    from components.kosten_helpers import derive_status
    assert derive_status(row) == "ongecategoriseerd"


def test_derive_status_debit_ongecategoriseerd_empty_cat():
    row = {"id_bank": 6, "id_uitgave": 13, "genegeerd": 0,
           "categorie": "", "pdf_pad": "",
           "bedrag": -10.0, "koppeling_type": None}
    from components.kosten_helpers import derive_status
    assert derive_status(row) == "ongecategoriseerd"
```

Update existing cases in `tests/test_kosten_helpers.py` that expect the old keys `"hidden"`, `"ontbreekt"` — replace with `"prive_verborgen"` and `"ontbreekt_bon"` respectively.

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kosten_helpers.py -v
```
Expected: new cases fail; old cases fail (renamed keys).

- [ ] **Step 3: Expand `derive_status`**

Replace `components/kosten_helpers.py:9-24` with:
```python
def derive_status(row: dict) -> str:
    """Sign-aware, priority-ordered status. See spec §4.1 steps 1-8.

    Returns one of:
      'prive_verborgen' | 'gekoppeld_factuur' | 'ongecategoriseerd' |
      'ontbreekt_bon' | 'compleet' | 'gecategoriseerd'

    Sequential and mutually exclusive.
    """
    if row.get("id_bank") is not None and row.get("genegeerd"):
        return "prive_verborgen"
    if (row.get("koppeling_type") == "factuur"
            and row.get("id_bank") is not None):
        return "gekoppeld_factuur"

    bedrag = row.get("bedrag") or 0.0
    cat = (row.get("categorie") or "").strip()
    pdf = (row.get("pdf_pad") or "").strip()

    if bedrag < 0:
        if row.get("id_uitgave") is None:
            return "ongecategoriseerd"
        if not cat:
            return "ongecategoriseerd"
        if not pdf:
            return "ontbreekt_bon"
        return "compleet"
    else:
        # Positive / income-side (no bon-concept for positives).
        if not cat:
            return "ongecategoriseerd"
        return "gecategoriseerd"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kosten_helpers.py -v
```
Expected: all green.

- [ ] **Step 5: Run full suite — some callers still expect old keys**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

Likely failures in `tests/test_kosten_view.py` expecting `"hidden"`/`"ontbreekt"`. Fix each by search/replacing old status strings with new keys in that test file. Same for any non-test file that compares status strings — `grep -rn "'hidden'\|\"hidden\"\|'ontbreekt'\|\"ontbreekt\"" pages/ components/ tests/` — and update. (The UI layer in `pages/kosten.py` currently renders chips keyed by `factuur_status` — update those comparisons too: `'ontbreekt'` → `'ontbreekt_bon'`, `'hidden'` → `'prive_verborgen'`.)

- [ ] **Step 6: Commit**

```bash
git add components/kosten_helpers.py tests/test_kosten_helpers.py tests/test_kosten_view.py pages/kosten.py
git commit -m "feat(kosten): expand derive_status to 8 sign-aware cases"
```

---

### Task 3: `TransactieRow` dataclass + `get_transacties_view` query (no filters yet)

Adds the unified row dataclass and the UNION ALL query from spec §4.1. Post-filters (status/categorie/type/search/maand) come in Task 4 — this task only verifies the raw union returns all three row-types.

**Files:**
- Modify: `database.py` — add `TransactieRow` dataclass (near existing `KostenRow` line 3231 area), add `get_transacties_view` function
- Create: `tests/test_get_transacties_view.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_get_transacties_view.py`:
```python
"""Task 3 — get_transacties_view unified query (bank debits + positives + manual)."""
import aiosqlite
import pytest

from database import get_transacties_view, TransactieRow


async def _seed_banktx(db, id_, datum, bedrag, tegenpartij='KPN',
                        omschrijving='factuur', tegenrekening='NL00BANK01',
                        categorie='', koppeling_type=None, koppeling_id=None,
                        genegeerd=0):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij, omschrijving, tegenrekening, "
            " categorie, koppeling_type, koppeling_id, genegeerd, csv_bestand) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (id_, datum, bedrag, tegenpartij, omschrijving, tegenrekening,
             categorie, koppeling_type, koppeling_id, genegeerd, 't.csv'))
        await conn.commit()


async def _seed_uitgave(db, datum, bedrag, categorie='', omschrijving='',
                        pdf_pad='', bank_tx_id=None, is_investering=0):
    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "pdf_pad, bank_tx_id, is_investering, zakelijk_pct) "
            "VALUES (?,?,?,?,?,?,?,?) RETURNING id",
            (datum, categorie, omschrijving, bedrag, pdf_pad, bank_tx_id,
             is_investering, 100))
        uid = (await cur.fetchone())[0]
        await conn.commit()
    return uid


@pytest.mark.asyncio
async def test_returns_bank_debit_row(db):
    await _seed_banktx(db, 1, '2026-03-10', -42.00, tegenpartij='KPN B.V.')
    rows = await get_transacties_view(db, jaar=2026)
    assert len(rows) == 1
    r = rows[0]
    assert isinstance(r, TransactieRow)
    assert r.source == 'bank_debit'
    assert r.id_bank == 1
    assert r.id_uitgave is None
    assert r.bedrag == -42.0
    assert r.tegenpartij == 'KPN B.V.'
    assert r.is_manual is False


@pytest.mark.asyncio
async def test_returns_bank_credit_row(db):
    await _seed_banktx(db, 2, '2026-03-11', 1000.00, tegenpartij='Ziekenhuis X')
    rows = await get_transacties_view(db, jaar=2026)
    assert len(rows) == 1
    r = rows[0]
    assert r.source == 'bank_credit'
    assert r.id_bank == 2
    assert r.id_uitgave is None
    assert r.bedrag == 1000.0


@pytest.mark.asyncio
async def test_returns_manual_cash_row(db):
    await _seed_uitgave(db, '2026-03-12', 9.50,
                         categorie='Kleine aankopen', omschrijving='parkeer',
                         bank_tx_id=None)
    rows = await get_transacties_view(db, jaar=2026)
    assert len(rows) == 1
    r = rows[0]
    assert r.source == 'manual'
    assert r.id_bank is None
    assert r.bedrag == -9.50  # normalised negative for uniform display
    assert r.is_manual is True


@pytest.mark.asyncio
async def test_all_three_sources_returned_sorted_desc(db):
    await _seed_banktx(db, 1, '2026-01-05', -10)
    await _seed_banktx(db, 2, '2026-05-05', 500)
    await _seed_uitgave(db, '2026-03-15', 20, categorie='Bankkosten')
    rows = await get_transacties_view(db, jaar=2026)
    assert [r.datum for r in rows] == ['2026-05-05', '2026-03-15', '2026-01-05']


@pytest.mark.asyncio
async def test_year_range_excludes_other_years(db):
    await _seed_banktx(db, 1, '2025-12-31', -10)
    await _seed_banktx(db, 2, '2026-01-01', -20)
    await _seed_banktx(db, 3, '2027-01-01', -30)
    rows = await get_transacties_view(db, jaar=2026)
    ids = [r.id_bank for r in rows]
    assert ids == [2]


@pytest.mark.asyncio
async def test_bank_debit_join_picks_up_linked_uitgave(db):
    await _seed_banktx(db, 1, '2026-03-10', -50)
    uid = await _seed_uitgave(db, '2026-03-10', 50, categorie='Telefoon/KPN',
                               pdf_pad='/tmp/x.pdf', bank_tx_id=1)
    rows = await get_transacties_view(db, jaar=2026)
    assert len(rows) == 1
    r = rows[0]
    assert r.id_bank == 1
    assert r.id_uitgave == uid
    assert r.categorie == 'Telefoon/KPN'
    assert r.pdf_pad == '/tmp/x.pdf'
    assert r.status == 'compleet'
```

- [ ] **Step 2: Run tests to verify they fail (import error)**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_get_transacties_view.py -v
```
Expected: ImportError — `TransactieRow` and `get_transacties_view` not defined.

- [ ] **Step 3: Add `TransactieRow` dataclass to `database.py`**

Locate the existing `KostenRow` dataclass (around line 3231 area). Add `TransactieRow` immediately after it:

```python
@dataclass
class TransactieRow:
    """Unified row for /transacties. Covers bank-debit, bank-credit, manual cash.

    ``bedrag`` is signed: + for income (bank credits), − for costs (debits +
    manual). This uniformity lets the UI colour cells by sign without needing
    ``source`` lookups.
    """
    source: str                    # 'bank_debit' | 'bank_credit' | 'manual'
    id_bank: int | None
    id_uitgave: int | None
    datum: str
    bedrag: float                  # signed
    tegenpartij: str
    omschrijving: str
    iban: str
    categorie: str
    pdf_pad: str
    is_investering: bool
    zakelijk_pct: int | None
    koppeling_type: str | None
    koppeling_id: int | None
    genegeerd: int
    status: str                    # derived via derive_status
    is_manual: bool                # True only for source == 'manual'
```

- [ ] **Step 4: Add `get_transacties_view` function to `database.py`**

Append after `get_kosten_view` (around line 3338):

```python
async def get_transacties_view(
    db_path: Path,
    jaar: int,
) -> list[TransactieRow]:
    """Unified view — bank debits + bank credits + manual cash uitgaven.

    Post-filtering (status / categorie / type / search / maand /
    include_genegeerd) is added in Task 4. This base version excludes
    ``genegeerd=1`` rows by default; inclusion lands in Task 4.
    """
    from components.kosten_helpers import derive_status

    jaar_start = f"{jaar:04d}-01-01"
    jaar_end = f"{jaar + 1:04d}-01-01"

    sql = """
    SELECT * FROM (
        SELECT 'bank_debit' AS source,
               b.id AS id_bank, u.id AS id_uitgave,
               b.datum AS datum, b.bedrag AS bedrag,
               COALESCE(b.tegenpartij, '') AS tegenpartij,
               COALESCE(NULLIF(u.omschrijving, ''), b.omschrijving, '')
                 AS omschrijving,
               COALESCE(b.tegenrekening, '') AS iban,
               COALESCE(u.categorie, '') AS categorie,
               COALESCE(u.pdf_pad, '') AS pdf_pad,
               COALESCE(u.is_investering, 0) AS is_investering,
               u.zakelijk_pct AS zakelijk_pct,
               b.koppeling_type AS koppeling_type,
               b.koppeling_id AS koppeling_id,
               b.genegeerd AS genegeerd
        FROM banktransacties b
        LEFT JOIN uitgaven u ON u.bank_tx_id = b.id
        WHERE b.bedrag < 0 AND b.genegeerd = 0
          AND b.datum >= ? AND b.datum < ?

        UNION ALL

        SELECT 'bank_credit' AS source,
               b.id AS id_bank, NULL AS id_uitgave,
               b.datum, b.bedrag,
               COALESCE(b.tegenpartij, ''), COALESCE(b.omschrijving, ''),
               COALESCE(b.tegenrekening, ''), COALESCE(b.categorie, ''),
               '' AS pdf_pad, 0 AS is_investering, NULL AS zakelijk_pct,
               b.koppeling_type, b.koppeling_id, b.genegeerd
        FROM banktransacties b
        WHERE b.bedrag >= 0 AND b.genegeerd = 0
          AND b.datum >= ? AND b.datum < ?

        UNION ALL

        SELECT 'manual' AS source,
               NULL AS id_bank, u.id AS id_uitgave,
               u.datum, -ABS(u.bedrag) AS bedrag,
               '' AS tegenpartij, u.omschrijving, '' AS iban,
               u.categorie, COALESCE(u.pdf_pad, ''),
               u.is_investering, u.zakelijk_pct,
               NULL AS koppeling_type, NULL AS koppeling_id, 0 AS genegeerd
        FROM uitgaven u
        WHERE u.bank_tx_id IS NULL
          AND u.datum >= ? AND u.datum < ?
    )
    ORDER BY datum DESC
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            sql,
            (jaar_start, jaar_end, jaar_start, jaar_end,
             jaar_start, jaar_end))
        raw = await cur.fetchall()

    out: list[TransactieRow] = []
    for r in raw:
        row_dict = {
            "id_bank": r["id_bank"],
            "id_uitgave": r["id_uitgave"],
            "genegeerd": r["genegeerd"],
            "categorie": r["categorie"],
            "pdf_pad": r["pdf_pad"],
            "bedrag": r["bedrag"],
            "koppeling_type": r["koppeling_type"],
        }
        out.append(TransactieRow(
            source=r["source"],
            id_bank=r["id_bank"],
            id_uitgave=r["id_uitgave"],
            datum=r["datum"],
            bedrag=r["bedrag"],
            tegenpartij=r["tegenpartij"],
            omschrijving=r["omschrijving"],
            iban=r["iban"],
            categorie=r["categorie"],
            pdf_pad=r["pdf_pad"],
            is_investering=bool(r["is_investering"]),
            zakelijk_pct=r["zakelijk_pct"],
            koppeling_type=r["koppeling_type"],
            koppeling_id=r["koppeling_id"],
            genegeerd=r["genegeerd"],
            status=derive_status(row_dict),
            is_manual=(r["source"] == "manual"),
        ))
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_get_transacties_view.py -v
```
Expected: 6 green.

- [ ] **Step 6: Run full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add database.py tests/test_get_transacties_view.py
git commit -m "feat(db): add TransactieRow + get_transacties_view unified query"
```

---

### Task 4: `get_transacties_view` post-filters (status, categorie, type, search, maand, include_genegeerd)

**Files:**
- Modify: `database.py` — expand `get_transacties_view` signature + filter logic
- Modify: `tests/test_get_transacties_view.py` — add filter cases

- [ ] **Step 1: Append failing tests**

Append to `tests/test_get_transacties_view.py`:
```python
@pytest.mark.asyncio
async def test_type_filter_bank_excludes_manual(db):
    await _seed_banktx(db, 1, '2026-03-01', -10)
    await _seed_uitgave(db, '2026-03-02', 20, categorie='Bankkosten')
    rows = await get_transacties_view(db, jaar=2026, type='bank')
    assert [r.source for r in rows] == ['bank_debit']


@pytest.mark.asyncio
async def test_type_filter_contant_excludes_bank(db):
    await _seed_banktx(db, 1, '2026-03-01', -10)
    await _seed_uitgave(db, '2026-03-02', 20, categorie='Bankkosten')
    rows = await get_transacties_view(db, jaar=2026, type='contant')
    assert [r.source for r in rows] == ['manual']


@pytest.mark.asyncio
async def test_status_filter_ongecategoriseerd(db):
    await _seed_banktx(db, 1, '2026-03-01', -10)     # no uitgave → ongecat
    bid2 = 2
    await _seed_banktx(db, bid2, '2026-03-02', -20)  # cat + bon → compleet
    await _seed_uitgave(db, '2026-03-02', 20,
                         categorie='Bankkosten', pdf_pad='/x.pdf',
                         bank_tx_id=bid2)
    rows = await get_transacties_view(
        db, jaar=2026, status='ongecategoriseerd')
    assert [r.id_bank for r in rows] == [1]


@pytest.mark.asyncio
async def test_status_filter_gekoppeld_factuur(db):
    await _seed_banktx(db, 1, '2026-03-01', 100,
                        koppeling_type='factuur', koppeling_id=42)
    await _seed_banktx(db, 2, '2026-03-02', 200)  # unmatched
    rows = await get_transacties_view(
        db, jaar=2026, status='gekoppeld_factuur')
    assert [r.id_bank for r in rows] == [1]


@pytest.mark.asyncio
async def test_categorie_filter(db):
    await _seed_banktx(db, 1, '2026-03-01', -10)
    await _seed_uitgave(db, '2026-03-01', 10,
                         categorie='Telefoon/KPN', bank_tx_id=1)
    await _seed_banktx(db, 2, '2026-03-02', -20)
    await _seed_uitgave(db, '2026-03-02', 20,
                         categorie='Bankkosten', bank_tx_id=2)
    rows = await get_transacties_view(
        db, jaar=2026, categorie='Telefoon/KPN')
    assert [r.id_bank for r in rows] == [1]


@pytest.mark.asyncio
async def test_search_filter_on_tegenpartij(db):
    await _seed_banktx(db, 1, '2026-03-01', -10, tegenpartij='KPN B.V.')
    await _seed_banktx(db, 2, '2026-03-02', -20, tegenpartij='Shell')
    rows = await get_transacties_view(db, jaar=2026, search='kpn')
    assert [r.id_bank for r in rows] == [1]


@pytest.mark.asyncio
async def test_maand_filter(db):
    await _seed_banktx(db, 1, '2026-02-28', -10)
    await _seed_banktx(db, 2, '2026-03-01', -20)
    await _seed_banktx(db, 3, '2026-03-31', -30)
    await _seed_banktx(db, 4, '2026-04-01', -40)
    rows = await get_transacties_view(db, jaar=2026, maand=3)
    assert sorted(r.id_bank for r in rows) == [2, 3]


@pytest.mark.asyncio
async def test_include_genegeerd_default_excludes(db):
    await _seed_banktx(db, 1, '2026-03-01', -10, genegeerd=1)
    rows = await get_transacties_view(db, jaar=2026)
    assert rows == []


@pytest.mark.asyncio
async def test_include_genegeerd_true_returns_row(db):
    await _seed_banktx(db, 1, '2026-03-01', -10, genegeerd=1)
    rows = await get_transacties_view(
        db, jaar=2026, include_genegeerd=True)
    assert len(rows) == 1
    assert rows[0].status == 'prive_verborgen'
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: TypeError — unexpected keyword args.

- [ ] **Step 3: Expand `get_transacties_view` signature + post-filter logic**

Replace the `get_transacties_view` function added in Task 3. New signature + body:

```python
async def get_transacties_view(
    db_path: Path,
    jaar: int,
    maand: int | None = None,
    status: str | None = None,
    categorie: str | None = None,
    type: str | None = None,                   # 'bank' | 'contant' | None
    search: str | None = None,
    include_genegeerd: bool = False,
) -> list[TransactieRow]:
    """Unified view — bank debits + bank credits + manual cash uitgaven.

    Post-filters are applied in Python at single-user scale. The date range
    uses the idx_banktransacties_datum / idx_uitgaven_datum indexes.

    ``include_genegeerd=True`` is required to surface privé-verborgen rows.
    """
    from components.kosten_helpers import derive_status

    jaar_start = f"{jaar:04d}-01-01"
    jaar_end = f"{jaar + 1:04d}-01-01"

    # genegeerd filter moves into the WHERE clause conditionally.
    gen_bank = "" if include_genegeerd else "AND b.genegeerd = 0 "

    sql = f"""
    SELECT * FROM (
        SELECT 'bank_debit' AS source,
               b.id AS id_bank, u.id AS id_uitgave,
               b.datum AS datum, b.bedrag AS bedrag,
               COALESCE(b.tegenpartij, '') AS tegenpartij,
               COALESCE(NULLIF(u.omschrijving, ''), b.omschrijving, '')
                 AS omschrijving,
               COALESCE(b.tegenrekening, '') AS iban,
               COALESCE(u.categorie, '') AS categorie,
               COALESCE(u.pdf_pad, '') AS pdf_pad,
               COALESCE(u.is_investering, 0) AS is_investering,
               u.zakelijk_pct AS zakelijk_pct,
               b.koppeling_type AS koppeling_type,
               b.koppeling_id AS koppeling_id,
               b.genegeerd AS genegeerd
        FROM banktransacties b
        LEFT JOIN uitgaven u ON u.bank_tx_id = b.id
        WHERE b.bedrag < 0 {gen_bank}
          AND b.datum >= ? AND b.datum < ?

        UNION ALL

        SELECT 'bank_credit' AS source,
               b.id AS id_bank, NULL AS id_uitgave,
               b.datum, b.bedrag,
               COALESCE(b.tegenpartij, ''), COALESCE(b.omschrijving, ''),
               COALESCE(b.tegenrekening, ''), COALESCE(b.categorie, ''),
               '' AS pdf_pad, 0 AS is_investering, NULL AS zakelijk_pct,
               b.koppeling_type, b.koppeling_id, b.genegeerd
        FROM banktransacties b
        WHERE b.bedrag >= 0 {gen_bank}
          AND b.datum >= ? AND b.datum < ?

        UNION ALL

        SELECT 'manual' AS source,
               NULL AS id_bank, u.id AS id_uitgave,
               u.datum, -ABS(u.bedrag) AS bedrag,
               '' AS tegenpartij, u.omschrijving, '' AS iban,
               u.categorie, COALESCE(u.pdf_pad, ''),
               u.is_investering, u.zakelijk_pct,
               NULL AS koppeling_type, NULL AS koppeling_id, 0 AS genegeerd
        FROM uitgaven u
        WHERE u.bank_tx_id IS NULL
          AND u.datum >= ? AND u.datum < ?
    )
    ORDER BY datum DESC
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            sql,
            (jaar_start, jaar_end, jaar_start, jaar_end,
             jaar_start, jaar_end))
        raw = await cur.fetchall()

    rows: list[TransactieRow] = []
    for r in raw:
        row_dict = {
            "id_bank": r["id_bank"],
            "id_uitgave": r["id_uitgave"],
            "genegeerd": r["genegeerd"],
            "categorie": r["categorie"],
            "pdf_pad": r["pdf_pad"],
            "bedrag": r["bedrag"],
            "koppeling_type": r["koppeling_type"],
        }
        rows.append(TransactieRow(
            source=r["source"],
            id_bank=r["id_bank"],
            id_uitgave=r["id_uitgave"],
            datum=r["datum"],
            bedrag=r["bedrag"],
            tegenpartij=r["tegenpartij"],
            omschrijving=r["omschrijving"],
            iban=r["iban"],
            categorie=r["categorie"],
            pdf_pad=r["pdf_pad"],
            is_investering=bool(r["is_investering"]),
            zakelijk_pct=r["zakelijk_pct"],
            koppeling_type=r["koppeling_type"],
            koppeling_id=r["koppeling_id"],
            genegeerd=r["genegeerd"],
            status=derive_status(row_dict),
            is_manual=(r["source"] == "manual"),
        ))

    # Python-side post-filters
    if type == 'bank':
        rows = [r for r in rows if not r.is_manual]
    elif type == 'contant':
        rows = [r for r in rows if r.is_manual]
    if maand is not None:
        mm = f"{maand:02d}"
        rows = [r for r in rows if r.datum[5:7] == mm]
    if status is not None:
        rows = [r for r in rows if r.status == status]
    if categorie:
        rows = [r for r in rows if r.categorie == categorie]
    if search:
        q = search.lower()
        rows = [r for r in rows if (
            q in r.tegenpartij.lower()
            or q in r.omschrijving.lower()
            or q in f"{abs(r.bedrag):.2f}"
        )]
    return rows
```

- [ ] **Step 4: Run tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_get_transacties_view.py -v
```
Expected: all green.

- [ ] **Step 5: Run full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add database.py tests/test_get_transacties_view.py
git commit -m "feat(db): get_transacties_view filter params (status/type/cat/search/maand/genegeerd)"
```

---

### Task 5: `get_uitgave_by_id` (M5 polish)

Replaces the list-and-filter pattern in the Detail dialog's bootstrap. Returns a single `Uitgave` or `None`.

**Files:**
- Modify: `database.py` — add function after existing `get_uitgaven` (line 1372)
- Create: `tests/test_get_uitgave_by_id.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_get_uitgave_by_id.py`:
```python
import pytest
import aiosqlite
from database import get_uitgave_by_id, Uitgave


async def _seed(db, **kwargs):
    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "pdf_pad, is_investering, zakelijk_pct, bank_tx_id) "
            "VALUES (?,?,?,?,?,?,?,?) RETURNING id",
            (kwargs.get('datum', '2026-03-01'),
             kwargs.get('categorie', 'Bankkosten'),
             kwargs.get('omschrijving', ''),
             kwargs.get('bedrag', 5.0),
             kwargs.get('pdf_pad', ''),
             kwargs.get('is_investering', 0),
             kwargs.get('zakelijk_pct', 100),
             kwargs.get('bank_tx_id', None)))
        uid = (await cur.fetchone())[0]
        await conn.commit()
    return uid


@pytest.mark.asyncio
async def test_returns_none_when_missing(db):
    assert await get_uitgave_by_id(db, 999) is None


@pytest.mark.asyncio
async def test_returns_populated_uitgave(db):
    uid = await _seed(db, categorie='Telefoon/KPN', bedrag=42.0,
                       omschrijving='test note')
    got = await get_uitgave_by_id(db, uid)
    assert isinstance(got, Uitgave)
    assert got.id == uid
    assert got.categorie == 'Telefoon/KPN'
    assert got.bedrag == 42.0
    assert got.omschrijving == 'test note'
```

- [ ] **Step 2: Run to verify it fails**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_get_uitgave_by_id.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement**

Append to `database.py` after `get_uitgaven` (around line 1387):
```python
async def get_uitgave_by_id(db_path: Path, uitgave_id: int) -> Uitgave | None:
    """Targeted fetch — single uitgave by id. Returns None if not found.

    Replaces the list-and-filter pattern (``get_uitgaven(jaar=…)`` then
    ``next(x for x in … if x.id == …)``) used in the detail-dialog bootstrap,
    which silently returns None on degenerate races. See polish item M5.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT * FROM uitgaven WHERE id = ?", (uitgave_id,))
        row = await cur.fetchone()
    return _row_to_uitgave(row) if row else None
```

- [ ] **Step 4: Run tests**

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_get_uitgave_by_id.py
git commit -m "feat(db): add get_uitgave_by_id (M5 polish — targeted fetch)"
```

---

### Task 6: `get_kosten_breakdown`

Cheap SQL-sum per categorie for the `/kosten` overview. Covers debits + manual, excludes genegeerd. Returns `{categorie: total}` sorted implicitly by magnitude by caller.

**Files:**
- Modify: `database.py` — add function
- Create: `tests/test_get_kosten_breakdown.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_get_kosten_breakdown.py`:
```python
import pytest
import aiosqlite
from database import get_kosten_breakdown


async def _seed_banktx(db, id_, datum, bedrag, genegeerd=0):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand, genegeerd) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (id_, datum, bedrag, '', '', '', 't.csv', genegeerd))
        await conn.commit()


async def _seed_uitgave(db, datum, bedrag, categorie, bank_tx_id=None):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id, is_investering, zakelijk_pct) VALUES (?,?,?,?,?,?,?)",
            (datum, categorie, '', bedrag, bank_tx_id, 0, 100))
        await conn.commit()


@pytest.mark.asyncio
async def test_sums_bank_debits_via_linked_uitgave(db):
    await _seed_banktx(db, 1, '2026-03-01', -50)
    await _seed_uitgave(db, '2026-03-01', 50, 'Telefoon/KPN', bank_tx_id=1)
    got = await get_kosten_breakdown(db, jaar=2026)
    assert got == {'Telefoon/KPN': 50.0}


@pytest.mark.asyncio
async def test_sums_manual_cash(db):
    await _seed_uitgave(db, '2026-03-01', 20, 'Bankkosten')
    await _seed_uitgave(db, '2026-03-02', 30, 'Bankkosten')
    got = await get_kosten_breakdown(db, jaar=2026)
    assert got == {'Bankkosten': 50.0}


@pytest.mark.asyncio
async def test_excludes_genegeerd(db):
    await _seed_banktx(db, 1, '2026-03-01', -50, genegeerd=1)
    await _seed_uitgave(db, '2026-03-01', 50, 'Telefoon/KPN', bank_tx_id=1)
    got = await get_kosten_breakdown(db, jaar=2026)
    assert got == {}


@pytest.mark.asyncio
async def test_empty_categorie_bucketed_as_empty_string(db):
    await _seed_uitgave(db, '2026-03-01', 10, '')
    got = await get_kosten_breakdown(db, jaar=2026)
    assert got == {'': 10.0}


@pytest.mark.asyncio
async def test_multiple_categories_summed(db):
    await _seed_uitgave(db, '2026-03-01', 10, 'Bankkosten')
    await _seed_uitgave(db, '2026-03-02', 20, 'Bankkosten')
    await _seed_uitgave(db, '2026-03-03', 30, 'Telefoon/KPN')
    got = await get_kosten_breakdown(db, jaar=2026)
    assert got == {'Bankkosten': 30.0, 'Telefoon/KPN': 30.0}
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement**

Append to `database.py`:
```python
async def get_kosten_breakdown(db_path: Path, jaar: int) -> dict[str, float]:
    """Sum of ABS(bedrag) per categorie for /kosten overzicht.

    Sources: bank debits with a linked uitgave (use uitgave.categorie), plus
    manual cash uitgaven. Excludes genegeerd bank txs. Empty categorie is
    bucketed as ``''`` so the caller can surface the "nog te categoriseren"
    group separately.
    """
    jaar_start = f"{jaar:04d}-01-01"
    jaar_end = f"{jaar + 1:04d}-01-01"
    sql = """
    SELECT COALESCE(u.categorie, '') AS cat, SUM(ABS(u.bedrag)) AS total
    FROM uitgaven u
    LEFT JOIN banktransacties b ON u.bank_tx_id = b.id
    WHERE u.datum >= ? AND u.datum < ?
      AND (b.id IS NULL OR b.genegeerd = 0)
    GROUP BY COALESCE(u.categorie, '')
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(sql, (jaar_start, jaar_end))
        raw = await cur.fetchall()
    return {r["cat"]: float(r["total"]) for r in raw}
```

- [ ] **Step 4: Run tests + full suite**

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_get_kosten_breakdown.py
git commit -m "feat(db): add get_kosten_breakdown (per-categorie sum for overview)"
```

---

### Task 7: `get_kosten_per_maand`

12-slot list. Used by per-maand bar-chart on `/kosten`.

**Files:**
- Modify: `database.py`
- Create: `tests/test_get_kosten_per_maand.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_get_kosten_per_maand.py`:
```python
import pytest
import aiosqlite
from database import get_kosten_per_maand


async def _seed_uitgave(db, datum, bedrag, categorie='Bankkosten'):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id, is_investering, zakelijk_pct) VALUES (?,?,?,?,?,?,?)",
            (datum, categorie, '', bedrag, None, 0, 100))
        await conn.commit()


@pytest.mark.asyncio
async def test_returns_12_slots(db):
    got = await get_kosten_per_maand(db, jaar=2026)
    assert len(got) == 12
    assert got == [0.0] * 12


@pytest.mark.asyncio
async def test_bucket_per_month(db):
    await _seed_uitgave(db, '2026-01-15', 10)
    await _seed_uitgave(db, '2026-01-20', 5)
    await _seed_uitgave(db, '2026-03-01', 100)
    await _seed_uitgave(db, '2026-12-31', 50)
    got = await get_kosten_per_maand(db, jaar=2026)
    assert got[0] == 15.0
    assert got[2] == 100.0
    assert got[11] == 50.0
    for i in [1, 3, 4, 5, 6, 7, 8, 9, 10]:
        assert got[i] == 0.0
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement**

Append to `database.py`:
```python
async def get_kosten_per_maand(db_path: Path, jaar: int) -> list[float]:
    """12 slots indexed by month-1 (Jan=0 … Dec=11). ABS sum per maand.

    Mirror of the debit+manual filter used by ``get_kosten_breakdown``.
    """
    jaar_start = f"{jaar:04d}-01-01"
    jaar_end = f"{jaar + 1:04d}-01-01"
    sql = """
    SELECT CAST(substr(u.datum, 6, 2) AS INTEGER) AS m,
           SUM(ABS(u.bedrag)) AS total
    FROM uitgaven u
    LEFT JOIN banktransacties b ON u.bank_tx_id = b.id
    WHERE u.datum >= ? AND u.datum < ?
      AND (b.id IS NULL OR b.genegeerd = 0)
    GROUP BY m
    """
    out = [0.0] * 12
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(sql, (jaar_start, jaar_end))
        for r in await cur.fetchall():
            idx = (r["m"] or 1) - 1
            if 0 <= idx < 12:
                out[idx] = float(r["total"])
    return out
```

- [ ] **Step 4: Run tests + full suite**

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_get_kosten_per_maand.py
git commit -m "feat(db): add get_kosten_per_maand (12-slot monthly totals)"
```

---

### Task 8: `get_terugkerende_kosten`

Tegenpartijen with ≥`min_count` uitgaven in `window_days`, sorted by `jaar_totaal` DESC.

**Files:**
- Modify: `database.py`
- Create: `tests/test_get_terugkerende_kosten.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_get_terugkerende_kosten.py`:
```python
import pytest
import aiosqlite
from datetime import date, timedelta
from database import get_terugkerende_kosten


async def _seed_pair(db, tx_id, datum, bedrag, tegenpartij='KPN',
                      cat='Telefoon/KPN'):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand) "
            "VALUES (?,?,?,?,?,?,?)",
            (tx_id, datum, bedrag, tegenpartij, '', '', 't.csv'))
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id, is_investering, zakelijk_pct) "
            "VALUES (?,?,?,?,?,?,?)",
            (datum, cat, '', abs(bedrag), tx_id, 0, 100))
        await conn.commit()


@pytest.mark.asyncio
async def test_fewer_than_3_not_returned(db):
    await _seed_pair(db, 1, '2026-01-15', -50)
    await _seed_pair(db, 2, '2026-02-15', -50)
    got = await get_terugkerende_kosten(db, jaar=2026)
    assert got == []


@pytest.mark.asyncio
async def test_3_or_more_returned(db):
    await _seed_pair(db, 1, '2026-01-15', -50)
    await _seed_pair(db, 2, '2026-02-15', -50)
    await _seed_pair(db, 3, '2026-03-15', -50)
    got = await get_terugkerende_kosten(db, jaar=2026)
    assert len(got) == 1
    r = got[0]
    assert r['tegenpartij'].lower() == 'kpn'
    assert r['count'] == 3
    assert r['jaar_totaal'] == 150.0
    assert r['laatste_datum'] == '2026-03-15'


@pytest.mark.asyncio
async def test_window_boundary(db):
    """Hit on day 366 before the end of the year window is excluded."""
    await _seed_pair(db, 1, '2024-12-31', -50)  # >365d before 2026-12-31
    await _seed_pair(db, 2, '2026-03-15', -50)
    await _seed_pair(db, 3, '2026-06-15', -50)
    got = await get_terugkerende_kosten(
        db, jaar=2026, min_count=3, window_days=365)
    # Only 2 hits in the 365d-lookback window ending at jaar-end — below
    # threshold, not returned.
    assert got == []


@pytest.mark.asyncio
async def test_case_insensitive_grouping(db):
    await _seed_pair(db, 1, '2026-01-15', -50, tegenpartij='KPN B.V.')
    await _seed_pair(db, 2, '2026-02-15', -50, tegenpartij='kpn b.v.')
    await _seed_pair(db, 3, '2026-03-15', -50, tegenpartij='Kpn B.V.')
    got = await get_terugkerende_kosten(db, jaar=2026)
    assert len(got) == 1
    assert got[0]['count'] == 3


@pytest.mark.asyncio
async def test_sorted_by_jaar_totaal_desc(db):
    await _seed_pair(db, 1, '2026-01-15', -10, tegenpartij='A', cat='X')
    await _seed_pair(db, 2, '2026-02-15', -10, tegenpartij='A', cat='X')
    await _seed_pair(db, 3, '2026-03-15', -10, tegenpartij='A', cat='X')
    await _seed_pair(db, 4, '2026-01-15', -500, tegenpartij='B', cat='Y')
    await _seed_pair(db, 5, '2026-02-15', -500, tegenpartij='B', cat='Y')
    await _seed_pair(db, 6, '2026-03-15', -500, tegenpartij='B', cat='Y')
    got = await get_terugkerende_kosten(db, jaar=2026)
    assert [r['tegenpartij'].lower() for r in got] == ['b', 'a']
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement**

Append to `database.py`:
```python
async def get_terugkerende_kosten(
    db_path: Path,
    jaar: int,
    min_count: int = 3,
    window_days: int = 365,
) -> list[dict]:
    """Tegenpartijen met ≥min_count uitgaven in de laatste window_days.

    The count threshold uses a rolling window ending at jaar-end; the total
    reported is the SUM over the full jaar (Jan 1 → Dec 31). Excludes
    genegeerd bank txs.

    Returns: list of {'tegenpartij', 'count', 'jaar_totaal', 'laatste_datum'}
    sorted by jaar_totaal DESC.
    """
    jaar_start = f"{jaar:04d}-01-01"
    jaar_end = f"{jaar + 1:04d}-01-01"
    # Window ends at jaar_end; rolls back window_days
    from datetime import datetime as _dt, timedelta as _td
    window_start = (_dt.strptime(jaar_end, "%Y-%m-%d")
                    - _td(days=window_days)).strftime("%Y-%m-%d")

    sql = """
    SELECT LOWER(b.tegenpartij) AS tp_lower,
           MAX(b.tegenpartij)   AS tp_display,
           COUNT(*)             AS cnt,
           SUM(CASE WHEN u.datum >= ? AND u.datum < ?
                    THEN ABS(u.bedrag) ELSE 0 END) AS jaar_totaal,
           MAX(u.datum)         AS laatste
    FROM uitgaven u
    JOIN banktransacties b ON u.bank_tx_id = b.id
    WHERE b.genegeerd = 0
      AND u.datum >= ? AND u.datum < ?
      AND TRIM(COALESCE(b.tegenpartij, '')) != ''
    GROUP BY LOWER(b.tegenpartij)
    HAVING COUNT(*) >= ?
    ORDER BY jaar_totaal DESC
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            sql,
            (jaar_start, jaar_end,           # jaar_totaal CASE
             window_start, jaar_end,         # WHERE window
             min_count))
        raw = await cur.fetchall()
    return [
        {'tegenpartij': r['tp_display'],
         'count': r['cnt'],
         'jaar_totaal': float(r['jaar_totaal']),
         'laatste_datum': r['laatste']}
        for r in raw
    ]
```

- [ ] **Step 4: Run tests + full suite**

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_get_terugkerende_kosten.py
git commit -m "feat(db): add get_terugkerende_kosten (recurring vendor detection)"
```

---

### Task 9: Update `get_categorie_suggestions` — UNION debit + positive sources

Current implementation reads only `banktransacties.categorie` — debit suggestions (now stored in `uitgaven.categorie`) are silently missing. Fix by UNIONing.

**Files:**
- Modify: `database.py:1677-1700` (replace existing function body)
- Create: `tests/test_get_categorie_suggestions_debits.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_get_categorie_suggestions_debits.py`:
```python
import pytest
import aiosqlite
from database import get_categorie_suggestions


async def _seed_debit(db, tx_id, datum, tegenpartij, bedrag, cat):
    """Seed a debit bank tx + a linked uitgave with the categorie."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand) "
            "VALUES (?,?,?,?,?,?,?)",
            (tx_id, datum, bedrag, tegenpartij, '', '', 't.csv'))
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "bank_tx_id, is_investering, zakelijk_pct) VALUES (?,?,?,?,?,?,?)",
            (datum, cat, '', abs(bedrag), tx_id, 0, 100))
        await conn.commit()


async def _seed_positive(db, tx_id, datum, tegenpartij, bedrag, cat):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand, categorie) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (tx_id, datum, bedrag, tegenpartij, '', '', 't.csv', cat))
        await conn.commit()


@pytest.mark.asyncio
async def test_debit_suggestion_returned_from_uitgaven(db):
    """Debit-categories live on uitgaven.categorie (migratie 27)."""
    await _seed_debit(db, 1, '2026-03-01', 'KPN B.V.', -50, 'Telefoon/KPN')
    await _seed_debit(db, 2, '2026-04-01', 'KPN B.V.', -50, 'Telefoon/KPN')
    got = await get_categorie_suggestions(db)
    assert got.get('kpn b.v.') == 'Telefoon/KPN'


@pytest.mark.asyncio
async def test_positive_suggestion_still_returned(db):
    await _seed_positive(db, 1, '2026-03-01', 'Ziekenhuis X', 1000, 'Omzet')
    got = await get_categorie_suggestions(db)
    assert got.get('ziekenhuis x') == 'Omzet'


@pytest.mark.asyncio
async def test_most_frequent_wins(db):
    await _seed_debit(db, 1, '2026-01-01', 'Shop', -10, 'Kleine aankopen')
    await _seed_debit(db, 2, '2026-02-01', 'Shop', -10, 'Kleine aankopen')
    await _seed_debit(db, 3, '2026-03-01', 'Shop', -10, 'Automatisering')
    got = await get_categorie_suggestions(db)
    assert got.get('shop') == 'Kleine aankopen'
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Replace `get_categorie_suggestions` body**

Replace `database.py:1677-1700` with:
```python
async def get_categorie_suggestions(db_path: Path = DB_PATH) -> dict[str, str]:
    """Build a lookup of tegenpartij → most-used category.

    Considers both:
    - Debit transactions where user categorised via uitgaven.categorie (post
      migratie 27 — this is the source of truth for debits).
    - Positive transactions where user categorised via banktransacties.categorie
      (Omzet / Prive / Belasting / AOV).

    Returns lowercase-tegenpartij → most-frequent categorie. Tie-break: most
    recent wins.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """
            SELECT tp, categorie, SUM(cnt) AS cnt_total,
                   MAX(recent) AS recent_max
            FROM (
                -- debit source (via linked uitgaven)
                SELECT LOWER(b.tegenpartij) AS tp,
                       u.categorie          AS categorie,
                       COUNT(*)             AS cnt,
                       MAX(b.datum)         AS recent
                FROM uitgaven u
                JOIN banktransacties b ON u.bank_tx_id = b.id
                WHERE u.categorie IS NOT NULL AND u.categorie != ''
                  AND b.tegenpartij IS NOT NULL AND b.tegenpartij != ''
                GROUP BY LOWER(b.tegenpartij), u.categorie

                UNION ALL

                -- positive source (on banktransacties directly)
                SELECT LOWER(tegenpartij) AS tp,
                       categorie          AS categorie,
                       COUNT(*)           AS cnt,
                       MAX(datum)         AS recent
                FROM banktransacties
                WHERE bedrag >= 0
                  AND categorie IS NOT NULL AND categorie != ''
                  AND tegenpartij IS NOT NULL AND tegenpartij != ''
                GROUP BY LOWER(tegenpartij), categorie
            )
            GROUP BY tp, categorie
            ORDER BY tp, cnt_total DESC, recent_max DESC
            """
        )
        rows = await cur.fetchall()

    suggestions: dict[str, str] = {}
    for r in rows:
        tp = r["tp"]
        if tp not in suggestions:
            suggestions[tp] = r["categorie"]
    return suggestions
```

- [ ] **Step 4: Run tests + full suite**

Any existing `test_get_categorie_suggestions` test using only the positive-source path should still pass. Check `grep -rn "get_categorie_suggestions" tests/` and verify.

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_get_categorie_suggestions_debits.py
git commit -m "feat(db): get_categorie_suggestions now unions debit + positive sources"
```

---

### Task 10: Route Importeer auto-link through `ensure_uitgave_for_banktx` (M1 code-path)

M1 also has a code-path component: Importeer currently does `add_uitgave(bank_tx_id=…)` directly, which races with manual categorisation from `/transacties`. Migratie 28 prevents the DB-level corruption; this task fixes the user-visible error by routing the create through `ensure_uitgave_for_banktx` (idempotent — returns existing id).

**Files:**
- Modify: `pages/kosten.py:1230-1240` — the `opslaan()` closure inside `open_add_uitgave_dialog` that handles the `bank_tx_id` branch
- Create: `tests/test_importeer_auto_link_idempotent.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_importeer_auto_link_idempotent.py`:
```python
"""M1 polish — second import for same bank_tx must not raise or duplicate."""
import pytest
import aiosqlite
from database import ensure_uitgave_for_banktx, update_uitgave


async def _seed_banktx(db, tx_id, datum='2026-03-01', bedrag=-50.0):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand) "
            "VALUES (?,?,?,?,?,?,?)",
            (tx_id, datum, bedrag, 'KPN', '', '', 't.csv'))
        await conn.commit()


@pytest.mark.asyncio
async def test_ensure_is_idempotent(db):
    await _seed_banktx(db, 1)
    uid1 = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    uid2 = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    assert uid1 == uid2


@pytest.mark.asyncio
async def test_second_call_respects_unique_index(db):
    """With migratie 28, a racing add_uitgave(bank_tx_id=1) would fail.
    ensure_uitgave_for_banktx must short-circuit and not attempt insert."""
    await _seed_banktx(db, 1)
    uid1 = await ensure_uitgave_for_banktx(db, bank_tx_id=1,
                                             categorie='Telefoon/KPN')
    # Update via ensure — second call with overrides should NOT re-insert
    uid2 = await ensure_uitgave_for_banktx(db, bank_tx_id=1,
                                             categorie='Automatisering')
    assert uid1 == uid2
    # Note: ensure is a create-or-return; it does not update. Update lives
    # on update_uitgave. Verify that by checking categorie unchanged:
    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute(
            "SELECT categorie FROM uitgaven WHERE id = ?", (uid1,))
        row = await cur.fetchone()
        assert row[0] == 'Telefoon/KPN'
```

- [ ] **Step 2: Run to verify they pass already**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_importeer_auto_link_idempotent.py -v
```

Expected: both PASS — `ensure_uitgave_for_banktx` is already idempotent. This test is a regression guard for the routing change in step 3.

- [ ] **Step 3: Locate and modify the importeer-save closure in `pages/kosten.py`**

Read `pages/kosten.py:1226-1240` — the block starting:
```python
# Pass through the prefill's bank_tx_id so Importeer can auto-link
if prefill and prefill.get('bank_tx_id'):
    kwargs['bank_tx_id'] = prefill['bank_tx_id']

try:
    uitgave_id = await add_uitgave(DB_PATH, **kwargs)
```

Replace with:
```python
# Pass through the prefill's bank_tx_id so Importeer can auto-link.
# Route through ensure_uitgave_for_banktx (idempotent) when a bank_tx_id is
# present — this guards against duplicate-link races at migratie-28 level
# and makes repeated-import a no-op instead of an IntegrityError.
bank_tx_id = prefill.get('bank_tx_id') if prefill else None

try:
    if bank_tx_id is not None:
        uitgave_id = await ensure_uitgave_for_banktx(
            DB_PATH, bank_tx_id=bank_tx_id,
            datum=kwargs.get('datum'),
            categorie=kwargs.get('categorie', ''),
            omschrijving=kwargs.get('omschrijving', ''))
        # Apply remaining kwargs (investeringen fields, bedrag override) —
        # ensure() only sets the basics + enforces bedrag = ABS(bank_tx.bedrag).
        update_kwargs = {k: v for k, v in kwargs.items()
                         if k not in ('datum', 'categorie', 'omschrijving',
                                       'bedrag')}
        if update_kwargs:
            await update_uitgave(DB_PATH, uitgave_id=uitgave_id,
                                  **update_kwargs)
    else:
        uitgave_id = await add_uitgave(DB_PATH, **kwargs)
```

Also ensure `ensure_uitgave_for_banktx` is imported at top of `pages/kosten.py` — it already is (line 25).

- [ ] **Step 4: Run tests + full suite**

- [ ] **Step 5: Commit**

```bash
git add pages/kosten.py tests/test_importeer_auto_link_idempotent.py
git commit -m "fix(kosten): route Importeer auto-link through ensure_uitgave_for_banktx (M1)"
```

---

### Phase 1 checkpoint

After Task 10: full test suite green, `/bank` and `/kosten` work unchanged. Tag: `phase-1-db-complete`.

```bash
git tag phase-1-db-complete
```

---

## Phase 2 — new `/transacties` page (Tasks 11-19)

Phase 2 creates the new inbox alongside the old pages. Old `/bank` and `/kosten` stay operational throughout. Final flip happens in Phase 4.

---

### Task 11: Extract Detail-dialog to `components/transacties_dialog.py`

Lift `_open_detail_dialog`, `_render_factuur_tab`, `_render_historie_tab`, `save_upload_for_uitgave`, `_copy_and_link_pdf` from `pages/kosten.py` into a new module. Wire M5 (use `get_uitgave_by_id` instead of list-and-filter).

**Files:**
- Create: `components/transacties_dialog.py`
- Modify: `pages/kosten.py` — import from new module, delete lifted bodies

- [ ] **Step 1: Create `components/transacties_dialog.py`**

Copy the following functions **verbatim** from `pages/kosten.py`, rewriting only the bootstrap of `_open_detail_dialog` to use `get_uitgave_by_id`:

From `pages/kosten.py`:
- `save_upload_for_uitgave` (lines 43-53)
- `_copy_and_link_pdf` (lines 56-63)
- `_open_detail_dialog` (lines 69-275) **with M5 fix below**
- `_render_factuur_tab` (lines 278-400)
- `_render_historie_tab` (lines 403-466)

Replace the M5-relevant section in `_open_detail_dialog` — find:
```python
    # Re-load fresh uitgave data scoped to the row's year.
    uitgaven = await get_uitgaven(DB_PATH, jaar=int(row['datum'][:4]))
    u = next((x for x in uitgaven if x.id == row['id_uitgave']), None)
    if u is None and not row.get('is_manual'):
        ui.notify('Fout: uitgave niet gevonden na aanmaken', type='negative')
        return
```

Replace with:
```python
    # Re-load fresh uitgave data via targeted fetch (M5 — avoids
    # list-and-filter silent-None race).
    u = (await get_uitgave_by_id(DB_PATH, row['id_uitgave'])
         if row.get('id_uitgave') is not None else None)
    if u is None and not row.get('is_manual'):
        ui.notify('Fout: uitgave niet gevonden na aanmaken', type='negative')
        return
```

Also inside `_render_factuur_tab` — find the two places that call `get_uitgaven(DB_PATH, jaar=…)` then `next((x for x in fresh if x.id == uitgave.id), uitgave)` — replace each with `fresh_u = await get_uitgave_by_id(DB_PATH, uitgave.id) or uitgave`.

At the top of `components/transacties_dialog.py`, imports:
```python
"""Detail / Factuur / Historie dialog for /transacties (and legacy /kosten).

Extracted from pages/kosten.py during the bank/kosten consolidation.
Replaces list-and-filter uitgave fetches with get_uitgave_by_id (M5).
"""
import asyncio
import base64
import shutil
from datetime import datetime
from pathlib import Path

from nicegui import ui

from components.utils import (
    format_euro, format_datum, KOSTEN_CATEGORIEEN as CATEGORIEEN,
)
from database import (
    DB_PATH, ensure_uitgave_for_banktx, update_uitgave, delete_uitgave,
    get_uitgave_by_id, get_transacties_view,
    find_pdf_matches_for_banktx, YearLockedError,
)

UITGAVEN_DIR = DB_PATH.parent / 'uitgaven'

LEVENSDUUR_OPTIES = {3: '3 jaar', 4: '4 jaar', 5: '5 jaar'}
```

Note: `_render_historie_tab` currently calls `get_kosten_view(DB_PATH, jaar=y)` — change to `get_transacties_view(DB_PATH, jaar=y)`. `KostenRow` returned there has `id_bank`, `tegenpartij`, `omschrijving`, `datum`, `bedrag` — all present on `TransactieRow` too, no other changes needed.

- [ ] **Step 2: Update `pages/kosten.py` to import from the new module**

At top of `pages/kosten.py`, replace the local `save_upload_for_uitgave`, `_copy_and_link_pdf`, `_open_detail_dialog`, `_render_factuur_tab`, `_render_historie_tab` definitions with an import:
```python
from components.transacties_dialog import (
    save_upload_for_uitgave, _copy_and_link_pdf, _open_detail_dialog,
)
```

Delete the duplicate function bodies (lines 43-466 approximately).

- [ ] **Step 3: Run full suite — must stay green**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

- [ ] **Step 4: Manual smoke — open /kosten in dev mode, verify detail-dialog flow works**

```bash
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py
```

Navigate to /kosten, open a row's detail dialog, verify all three tabs render and actions (categorie save, bon upload, ontkoppel) work. Close.

- [ ] **Step 5: Commit**

```bash
git add components/transacties_dialog.py pages/kosten.py
git commit -m "refactor(kosten): extract detail-dialog to components/transacties_dialog (+M5)"
```

---

### Task 12: `pages/transacties.py` — scaffold (page, layout, filter bar, empty table)

Create the new page with header, filter bar, empty table skeleton. No row rendering yet. Query-param handling implemented. Page registered at `/transacties` route but not yet linked from sidebar.

**Files:**
- Create: `pages/transacties.py`
- Modify: `main.py` — ensure the new page module is imported so `@ui.page` registers

- [ ] **Step 1: Create the page scaffold**

Create `pages/transacties.py`:
```python
"""Transacties pagina — unified inbox for bank + cash movements.

Combines the old /bank (CSV import + positives categorisation +
factuur-match) and the /kosten transactie-tabel (debit categorisation +
bon koppelen + cash entries + privé) into a single decision surface.
"""
import asyncio
import json
from datetime import date, datetime

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import (
    format_euro, format_datum,
    KOSTEN_CATEGORIEEN, BANK_CATEGORIEEN,
)
from components.shared_ui import year_options, date_input
from components.kosten_helpers import (
    derive_status, tegenpartij_color, initials,
)
from components.transacties_dialog import _open_detail_dialog
from database import (
    DB_PATH, get_transacties_view, get_categorie_suggestions,
    find_factuur_matches,
    set_banktx_categorie, update_uitgave, add_uitgave,
    ensure_uitgave_for_banktx, mark_banktx_genegeerd,
    delete_banktransacties, delete_uitgave,
    YearLockedError,
)


# Extra-cats injected per-row on top of KOSTEN_CATEGORIEEN for positives.
# (Omzet / Prive / Belasting / AOV already included in BANK_CATEGORIEEN.)
POSITIVE_CAT_OPTIONS = ['', 'Omzet', 'Prive', 'Belasting', 'AOV']
DEBIT_CAT_OPTIONS = [''] + KOSTEN_CATEGORIEEN


@ui.page('/transacties')
async def transacties_page(jaar: int | None = None,
                             categorie: str | None = None,
                             status: str | None = None,
                             search: str | None = None,
                             maand: int | None = None,
                             type: str | None = None):
    create_layout('Transacties', '/transacties')
    current_year = datetime.now().year

    # Filter refs — populated from query-params on mount, mutated by
    # the filter bar's widgets, read by refresh().
    filter_jaar = {'value': jaar or current_year}
    filter_maand = {'value': maand or 0}       # 0 = alle maanden
    filter_status = {'value': status or None}  # None = alle
    filter_categorie = {'value': categorie or None}
    filter_type = {'value': type or None}      # None | 'bank' | 'contant'
    filter_search = {'value': search or ''}

    table_ref = {'table': None}
    match_btn_ref = {'button': None}
    bulk_bar_ref = {'ref': None}
    bulk_label_ref = {'ref': None}
    cat_suggestions = {'map': {}}

    async def _load_rows() -> list[dict]:
        rows = await get_transacties_view(
            DB_PATH,
            jaar=filter_jaar['value'],
            maand=filter_maand['value'] or None,
            status=filter_status['value'],
            categorie=filter_categorie['value'],
            type=filter_type['value'],
            search=filter_search['value'] or None,
            include_genegeerd=(filter_status['value'] == 'prive_verborgen'),
        )

        out: list[dict] = []
        for r in rows:
            display_name = r.tegenpartij or r.omschrijving or '(onbekend)'
            # Per-row category options: positives get income-cats only,
            # debits+cash get expense-cats.
            cat_opts = (POSITIVE_CAT_OPTIONS if r.bedrag >= 0
                        else DEBIT_CAT_OPTIONS)
            suggested = ''
            if not r.categorie and r.tegenpartij:
                suggested = cat_suggestions['map'].get(
                    r.tegenpartij.lower(), '')
            row_key = (f'b{r.id_bank}' if r.id_bank is not None
                        else f'u{r.id_uitgave}')
            out.append({
                'row_key': row_key,
                'source': r.source,
                'id_bank': r.id_bank,
                'id_uitgave': r.id_uitgave,
                'datum': r.datum,
                'datum_fmt': format_datum(r.datum),
                'tegenpartij': display_name,
                'omschrijving': r.omschrijving,
                'categorie': r.categorie,
                'suggested_categorie': suggested,
                'cat_options': cat_opts,
                'bedrag': r.bedrag,
                'bedrag_fmt': format_euro(r.bedrag),
                'pdf_pad': r.pdf_pad,
                'koppeling_type': r.koppeling_type,
                'koppeling_id': r.koppeling_id,
                'status': r.status,
                'is_manual': r.is_manual,
                'initials': initials(display_name),
                'color': tegenpartij_color(display_name),
            })
        return out

    async def _refresh_suggestions():
        cat_suggestions['map'] = await get_categorie_suggestions(DB_PATH)

    async def _refresh_match_count():
        """Update the [Matches controleren (N)] header button label."""
        if match_btn_ref['button'] is None:
            return
        n = len(await find_factuur_matches(DB_PATH))
        btn = match_btn_ref['button']
        btn.set_visibility(n > 0)
        btn.text = f'Matches controleren ({n})'

    async def refresh():
        await _refresh_suggestions()
        await _refresh_match_count()
        rows = await _load_rows()
        if table_ref['table'] is not None:
            table_ref['table'].rows = rows
            table_ref['table'].selected.clear()
            table_ref['table'].update()

    # --------------------------------------------------------------
    # Layout
    # --------------------------------------------------------------
    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):
        # Header
        with ui.row().classes('w-full items-center'):
            page_title('Transacties')
            ui.space()
            # Header buttons — cash, imports, matches (wired in later tasks).
            match_btn_ref['button'] = ui.button(
                f'Matches controleren (0)',
                icon='link',
                on_click=lambda: None)  # wired in Task 19
            match_btn_ref['button'].props('flat color=primary dense')
            match_btn_ref['button'].set_visibility(False)

        # Filter bar
        with ui.row().classes('w-full items-center gap-2'):
            jaar_select = ui.select(
                {j: str(j) for j in year_options()},
                label='Jaar', value=filter_jaar['value'],
            ).classes('w-28')

            maand_select = ui.select(
                {0: 'Alle maanden',
                 1: 'Januari', 2: 'Februari', 3: 'Maart', 4: 'April',
                 5: 'Mei', 6: 'Juni', 7: 'Juli', 8: 'Augustus',
                 9: 'September', 10: 'Oktober', 11: 'November',
                 12: 'December'},
                label='Maand', value=filter_maand['value'],
            ).classes('w-36')

            status_select = ui.select(
                {None: 'Alle',
                 'ongecategoriseerd': 'Ongecategoriseerd',
                 'ontbreekt_bon': 'Bon ontbreekt',
                 'gekoppeld_factuur': 'Gekoppeld aan factuur',
                 'prive_verborgen': 'Privé-verborgen',
                 'compleet': 'Compleet'},
                label='Status', value=filter_status['value'],
            ).classes('w-48')

            cat_opts = {'': 'Alle categorieën'}
            for c in BANK_CATEGORIEEN:
                if c:
                    cat_opts[c] = c
            categorie_select = ui.select(
                cat_opts, label='Categorie',
                value=filter_categorie['value'] or '',
            ).classes('w-48')

            type_select = ui.select(
                {None: 'Alle', 'bank': 'Bank', 'contant': 'Contant'},
                label='Type', value=filter_type['value'],
            ).classes('w-32')

            search_input = ui.input(
                placeholder='Zoek tegenpartij / omschrijving',
                value=filter_search['value']
            ).classes('w-64').props('clearable dense outlined')

        async def on_filter_change():
            filter_jaar['value'] = jaar_select.value
            filter_maand['value'] = maand_select.value
            filter_status['value'] = status_select.value
            filter_categorie['value'] = categorie_select.value or None
            filter_type['value'] = type_select.value
            filter_search['value'] = search_input.value or ''
            await refresh()

        for w in (jaar_select, maand_select, status_select,
                   categorie_select, type_select):
            w.on('update:model-value',
                  lambda _=None: on_filter_change())
        search_input.on(
            'update:model-value',
            lambda _=None: on_filter_change())

        # Bulk bar placeholder — wired in Task 16
        bulk_bar = ui.row().classes('w-full items-center gap-2 q-py-sm') \
            .style('background:#0f172a;color:white;border-radius:8px;'
                    'padding:8px 16px')
        bulk_bar.set_visibility(False)
        bulk_bar_ref['ref'] = bulk_bar
        with bulk_bar:
            bulk_label_ref['ref'] = ui.label('')

        # Table skeleton — rows/slots wired in Task 13
        columns = [
            {'name': 'datum', 'label': 'Datum', 'field': 'datum_fmt',
             'align': 'left', 'sortable': True},
            {'name': 'tegenpartij', 'label': 'Tegenpartij / Omschrijving',
             'field': 'tegenpartij', 'align': 'left'},
            {'name': 'categorie', 'label': 'Categorie', 'field': 'categorie',
             'align': 'left'},
            {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
             'align': 'right', 'sortable': True},
            {'name': 'status_chip', 'label': 'Factuur/bon',
             'field': 'status', 'align': 'center'},
            {'name': 'acties', 'label': '', 'field': 'acties',
             'align': 'center'},
        ]

        with ui.card().classes('w-full'):
            table = ui.table(
                columns=columns, rows=[], row_key='row_key',
                selection='multiple',
                pagination={
                    'rowsPerPage': 25, 'sortBy': 'datum',
                    'descending': True,
                    'rowsPerPageOptions': [10, 20, 50, 0]},
            ).classes('w-full').props('flat')
            table_ref['table'] = table

            table.add_slot('no-data', '''
                <q-tr><q-td colspan="100%"
                            class="text-center q-pa-lg text-grey">
                  Geen transacties gevonden.
                </q-td></q-tr>
            ''')

        # Initial load
        await refresh()
```

- [ ] **Step 2: Verify main.py imports `pages.transacties`**

Check `main.py` — if it imports pages by wildcard, no change needed. If explicit, add:
```python
from pages import transacties  # noqa: F401 — registers @ui.page('/transacties')
```

- [ ] **Step 3: Smoke test**

```bash
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py
```

Navigate to `http://localhost:8080/transacties`. Expect: page loads, header + filter bar visible, empty table. No row rendering yet.

Also try `/transacties?jaar=2025` — year-selector should show 2025 pre-selected.

- [ ] **Step 4: Run full suite** (should remain green — no test changes)

- [ ] **Step 5: Commit**

```bash
git add pages/transacties.py main.py
git commit -m "feat(transacties): scaffold page with filter bar + query-params"
```

---

### Task 13: `/transacties` — table body slot + inline categorie + row actions

Adds the body slot that renders each row with per-row category options, colour by status, wand-icon suggestion, row actions (bon / detail / delete). Wires the categorie handler.

**Files:**
- Modify: `pages/transacties.py` — extend table with body slot + event handlers

- [ ] **Step 1: Add the body slot**

Inside `pages/transacties.py`, after the existing `table.add_slot('no-data', …)` line, append:

```python
        table.add_slot('body', r"""
            <q-tr :props="props"
                   :class="{
                       'bg-teal-1': props.row.status === 'gekoppeld_factuur',
                       'bg-amber-1': props.row.status === 'ontbreekt_bon',
                       'bg-red-1': props.row.status === 'ongecategoriseerd',
                       'bg-grey-3': props.row.status === 'prive_verborgen',
                   }">
                <q-td auto-width>
                    <q-checkbox v-model="props.selected" dense />
                </q-td>
                <q-td key="datum" :props="props">{{ props.row.datum_fmt }}</q-td>
                <q-td key="tegenpartij" :props="props">
                    <div class="row items-center q-gutter-sm"
                         style="width:100%;flex-wrap:nowrap;">
                        <div :style="`background:${props.row.color};
                                      color:white;
                                      width:30px;height:30px;
                                      border-radius:7px;
                                      display:grid;place-items:center;
                                      font-weight:700;font-size:11px;
                                      flex-shrink:0;`">
                            {{ props.row.initials }}
                        </div>
                        <div style="min-width:0;flex:1;">
                            <div style="font-weight:500;
                                         white-space:nowrap;
                                         overflow:hidden;
                                         text-overflow:ellipsis;"
                                 :title="props.row.tegenpartij">
                                {{ props.row.tegenpartij }}
                            </div>
                            <div class="text-caption text-grey"
                                 v-if="props.row.omschrijving &&
                                        props.row.omschrijving !== props.row.tegenpartij"
                                 :title="props.row.omschrijving"
                                 style="white-space:nowrap;
                                         overflow:hidden;
                                         text-overflow:ellipsis;">
                                {{ props.row.omschrijving }}
                            </div>
                        </div>
                    </div>
                </q-td>
                <q-td key="categorie" :props="props">
                    <div style="display:flex;align-items:center;gap:4px">
                        <q-select
                            :model-value="props.row.categorie"
                            :options="props.row.cat_options"
                            dense borderless emit-value map-options
                            placeholder="— kies —"
                            @update:model-value="val => $parent.$emit('set_cat',
                                                                      {row: props.row,
                                                                       cat: val})"
                            style="min-width:160px" />
                        <q-btn v-if="props.row.suggested_categorie && !props.row.categorie"
                            icon="auto_fix_high" flat dense round size="xs" color="primary"
                            :title="'Toepassen: ' + props.row.suggested_categorie"
                            @click="() => $parent.$emit('set_cat',
                                                         {row: props.row,
                                                          cat: props.row.suggested_categorie})" />
                    </div>
                </q-td>
                <q-td key="bedrag" :props="props"
                       :class="props.row.bedrag >= 0
                                ? 'text-teal-8 text-bold'
                                : 'text-red-8 text-bold'"
                       style="text-align:right;
                              font-variant-numeric:tabular-nums">
                    {{ props.row.bedrag_fmt }}
                </q-td>
                <q-td key="status_chip" :props="props">
                    <q-chip v-if="props.row.status === 'compleet'"
                            color="positive" text-color="white" size="sm"
                            icon="check_circle" dense>Compleet</q-chip>
                    <q-chip v-else-if="props.row.status === 'ontbreekt_bon'"
                            color="warning" text-color="white" size="sm"
                            icon="warning" dense>Bon ontbreekt</q-chip>
                    <q-chip v-else-if="props.row.status === 'gekoppeld_factuur'"
                            color="info" text-color="white" size="sm"
                            icon="link" dense>Gekoppeld</q-chip>
                    <q-chip v-else-if="props.row.status === 'gecategoriseerd'"
                            color="grey-7" text-color="white" size="sm" dense>
                        {{ props.row.categorie }}
                    </q-chip>
                    <q-chip v-else-if="props.row.status === 'prive_verborgen'"
                            color="grey-5" text-color="white" size="sm"
                            icon="visibility_off" dense>Privé</q-chip>
                    <q-chip v-else color="negative" text-color="white" size="sm"
                            dense>Nieuw</q-chip>
                    <q-chip v-if="props.row.is_manual" color="grey-5"
                            text-color="white" size="sm" dense
                            style="margin-left:4px">contant</q-chip>
                </q-td>
                <q-td key="acties" :props="props">
                    <q-btn v-if="props.row.bedrag < 0" flat dense round
                           icon="attach_file" size="sm" color="primary"
                           title="Bon toevoegen"
                           @click="$parent.$emit('attach_pdf', props.row)" />
                    <q-btn flat dense round icon="more_horiz" size="sm"
                           color="grey-7"
                           @click="$parent.$emit('open_detail', props.row)" />
                    <q-btn flat dense round icon="delete" size="sm"
                           color="negative"
                           @click="$parent.$emit('delete_row', props.row)" />
                </q-td>
            </q-tr>
        """)
```

- [ ] **Step 2: Add the categorie-change handler**

Append after the slot:
```python
        async def _on_set_cat(args: dict):
            row = args['row']
            cat = args['cat'] or ''
            try:
                if row['id_bank'] is not None:
                    # Bank debit or credit — branch lives in set_banktx_categorie
                    await set_banktx_categorie(
                        DB_PATH, bank_tx_id=row['id_bank'], categorie=cat)
                else:
                    # Manual uitgave
                    await update_uitgave(
                        DB_PATH, uitgave_id=row['id_uitgave'], categorie=cat)
                ui.notify(f'Categorie: {cat or "leeggemaakt"}', type='positive')
                await refresh()
            except YearLockedError as e:
                ui.notify(str(e), type='negative')

        async def _open_detail(row: dict):
            await _open_detail_dialog(row, refresh, default_tab='detail')

        async def _open_factuur(row: dict):
            await _open_detail_dialog(row, refresh, default_tab='factuur')

        table.on('set_cat',
                  lambda e: asyncio.create_task(_on_set_cat(e.args)))
        table.on('open_detail',
                  lambda e: asyncio.create_task(_open_detail(e.args)))
        table.on('attach_pdf',
                  lambda e: asyncio.create_task(_open_factuur(e.args)))
        # delete_row wired in Task 15
```

- [ ] **Step 3: Smoke test**

Start dev server. Go to `/transacties`. Expect:
- Rows render with avatars, status colours, inline categorie dropdowns
- Click a debit's categorie dropdown → changes save → row refreshes (goes amber if no bon, green if has bon)
- Click a positive's dropdown → options are Omzet/Prive/Belasting/AOV only
- Click `…` on a row → detail dialog opens
- Click 📎 on a debit row → detail dialog opens on Factuur-tab

- [ ] **Step 4: Run full suite**

- [ ] **Step 5: Commit**

```bash
git add pages/transacties.py
git commit -m "feat(transacties): table body + inline categorie + row actions"
```

---

### Task 14: `/transacties` — CSV upload + factuur-match preview dialog

Ports the CSV flow from old `pages/bank.py` (lines 128-229). The match-preview dialog is the same logic — unchanged.

**Files:**
- Modify: `pages/transacties.py` — add CSV upload button, match-preview dialog, helper `_build_match_preview_rows`
- Modify: `pages/transacties.py` imports — add what's needed from `database` and `import_.rabobank_csv`

- [ ] **Step 1: Add imports**

In `pages/transacties.py` top:
```python
from database import (
    # …existing…
    add_banktransacties, get_imported_csv_bestanden,
    find_factuur_matches, apply_factuur_matches,
    get_db_ctx,
)
from import_.rabobank_csv import parse_rabobank_csv
```

- [ ] **Step 2: Add CSV upload button + handler + match-preview dialog**

In the page header row (replacing the placeholder `ui.button('Matches controleren…')`), add:
```python
            # Header actions
            ui.upload(
                label='Importeer CSV',
                on_upload=lambda e: asyncio.create_task(handle_csv_upload(e)),
                auto_upload=True,
            ).props('accept=".csv" flat color=primary').classes('w-44')

            match_btn_ref['button'] = ui.button(
                f'Matches controleren (0)',
                icon='link',
                on_click=lambda: asyncio.create_task(
                    _open_match_dialog_manually()))
            match_btn_ref['button'].props('flat color=primary dense')
            match_btn_ref['button'].set_visibility(False)
```

Add handlers after the existing `async def refresh()`:
```python
    async def handle_csv_upload(e):
        content = await e.file.read()
        filename = e.file.name
        try:
            transacties = parse_rabobank_csv(content)
        except ValueError as exc:
            ui.notify(f'Fout bij parsing: {exc}', type='negative')
            return
        if not transacties:
            ui.notify('Geen transacties gevonden in CSV.', type='warning')
            return

        bestaande_csvs = await get_imported_csv_bestanden(DB_PATH)
        if any(csv.endswith(f'_{filename}') for csv in bestaande_csvs):
            ui.notify(f"CSV '{filename}' is al eerder geïmporteerd",
                       type='warning')
            return

        csv_dir = DB_PATH.parent / 'bank_csv'
        csv_dir.mkdir(parents=True, exist_ok=True)
        archive_name = (f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
                         f'{filename}')
        archive_path = csv_dir / archive_name
        await asyncio.to_thread(archive_path.write_bytes, content)

        count = await add_banktransacties(DB_PATH, transacties,
                                            csv_bestand=archive_name)
        ui.notify(f'{count} transacties geïmporteerd uit {filename}',
                   type='positive')

        proposals = await find_factuur_matches(DB_PATH)
        await refresh()
        if proposals:
            await _show_match_preview_dialog(proposals, count)

    async def _open_match_dialog_manually():
        proposals = await find_factuur_matches(DB_PATH)
        if not proposals:
            ui.notify('Geen openstaande matches.', type='info')
            return
        await _show_match_preview_dialog(proposals, imported_count=0)

    async def _build_match_preview_rows(proposals):
        rows = []
        async with get_db_ctx(DB_PATH) as conn:
            for idx, p in enumerate(proposals):
                f_cur = await conn.execute(
                    "SELECT nummer, totaal_bedrag FROM facturen WHERE id = ?",
                    (p.factuur_id,))
                f_row = await f_cur.fetchone()
                b_cur = await conn.execute(
                    "SELECT tegenpartij, bedrag, datum FROM banktransacties "
                    "WHERE id = ?", (p.bank_id,))
                b_row = await b_cur.fetchone()
                if not f_row or not b_row:
                    continue
                rows.append({
                    'id': idx,
                    'confidence': p.confidence,
                    'confidence_icon': '!' if p.confidence == 'low' else 'OK',
                    'factuur': f_row['nummer'],
                    'factuur_bedrag': format_euro(f_row['totaal_bedrag']),
                    'bank': b_row['tegenpartij'] or '',
                    'bank_datum': format_datum(b_row['datum']),
                    'bank_bedrag': format_euro(b_row['bedrag']),
                    'delta': format_euro(p.delta),
                })
        return rows

    async def _show_match_preview_dialog(proposals, imported_count: int):
        rows = await _build_match_preview_rows(proposals)
        n_low = sum(1 for r in rows if r['confidence'] == 'low')

        with ui.dialog() as dialog, \
                ui.card().classes('w-full').style('max-width: 900px'):
            title = (f'{imported_count} transacties geïmporteerd - '
                      f'{len(proposals)} mogelijke koppelingen gevonden'
                      if imported_count
                      else f'{len(proposals)} openstaande koppelingen')
            ui.label(title).classes('text-h6')
            subtitle = ('Vink aan welke koppelingen je wilt toepassen. '
                         'Dubbelzinnige matches moet je zelf controleren.')
            if n_low:
                subtitle += f' ({n_low} dubbelzinnig)'
            ui.label(subtitle).classes('text-body2 q-mb-sm text-grey-8')

            columns = [
                {'name': 'confidence_icon', 'label': '',
                 'field': 'confidence_icon', 'align': 'center'},
                {'name': 'factuur', 'label': 'Factuur', 'field': 'factuur',
                 'align': 'left'},
                {'name': 'factuur_bedrag', 'label': 'Bedrag',
                 'field': 'factuur_bedrag', 'align': 'right'},
                {'name': 'bank', 'label': 'Bank tegenpartij',
                 'field': 'bank', 'align': 'left'},
                {'name': 'bank_datum', 'label': 'Bank datum',
                 'field': 'bank_datum', 'align': 'left'},
                {'name': 'bank_bedrag', 'label': 'Bank bedrag',
                 'field': 'bank_bedrag', 'align': 'right'},
                {'name': 'delta', 'label': 'Verschil', 'field': 'delta',
                 'align': 'right'},
            ]
            preview_table = ui.table(
                columns=columns, rows=rows, row_key='id',
                selection='multiple',
            ).props('flat bordered dense').classes('w-full')
            preview_table.selected = [
                r for r in rows if r['confidence'] == 'high']

            async def apply_selected():
                chosen_ids = {r['id'] for r in preview_table.selected}
                chosen = [p for idx, p in enumerate(proposals)
                           if idx in chosen_ids]
                if not chosen:
                    ui.notify('Geen koppelingen geselecteerd',
                               type='warning')
                    return
                applied = await apply_factuur_matches(DB_PATH, chosen)
                nummers = ', '.join(p.factuur_nummer for p in chosen)
                ui.notify(
                    f'{applied} facturen als betaald gemarkeerd: {nummers}',
                    type='positive')
                dialog.close()
                await refresh()

            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')
                ui.button('Geselecteerde toepassen',
                           on_click=apply_selected).props('color=primary')
        dialog.open()
```

- [ ] **Step 3: Smoke test**

Upload a CSV on `/transacties`. Verify: rows appear, match-preview dialog opens with proposals, apply selected marks facturen as paid.

Click "Matches controleren (N)" when proposals exist → same dialog opens.

- [ ] **Step 4: Run full suite**

- [ ] **Step 5: Commit**

```bash
git add pages/transacties.py
git commit -m "feat(transacties): CSV upload + factuur-match preview dialog"
```

---

### Task 15: `/transacties` — delete handlers (bank + uitgave)

Wires `delete_row` event. Branches on source (bank → `delete_banktransacties` with factuur-revert cascade; manual → `delete_uitgave`).

**Files:**
- Modify: `pages/transacties.py`

- [ ] **Step 1: Add delete handler**

After the `_open_factuur` handler in `pages/transacties.py`:
```python
    async def _on_delete_row(row: dict):
        if row.get('id_bank') is not None:
            # Bank tx — may revert linked factuur
            with ui.dialog() as dialog, ui.card():
                ui.label('Transactie verwijderen?').classes('text-h6')
                ui.label(f"{row['datum_fmt']} — {row['tegenpartij']} — "
                          f"{row['bedrag_fmt']}").classes('text-grey')
                if row.get('koppeling_type') == 'factuur':
                    ui.label(
                        'Gekoppelde factuur wordt teruggezet naar verstuurd.'
                    ).classes('text-caption text-warning q-mt-sm')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren',
                               on_click=dialog.close).props('flat')

                    async def do_delete():
                        try:
                            _n, reverted = await delete_banktransacties(
                                DB_PATH, transactie_ids=[row['id_bank']])
                        except YearLockedError as e:
                            ui.notify(str(e), type='negative')
                            return
                        dialog.close()
                        ui.notify('Transactie verwijderd', type='positive')
                        if reverted:
                            ui.notify(
                                f'{len(reverted)} factuur/facturen '
                                f'teruggezet naar verstuurd', type='info')
                        await refresh()

                    ui.button('Verwijderen', on_click=do_delete) \
                        .props('color=negative')
            dialog.open()
        elif row.get('id_uitgave') is not None:
            # Manual cash uitgave — straight delete
            with ui.dialog() as dialog, ui.card():
                ui.label('Uitgave verwijderen?').classes('text-h6')
                ui.label(f"{row['datum_fmt']} — "
                          f"{row.get('omschrijving') or row['tegenpartij']}"
                          f" — {row['bedrag_fmt']}") \
                    .classes('text-grey')
                with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                    ui.button('Annuleren',
                               on_click=dialog.close).props('flat')

                    async def do_delete_u():
                        try:
                            await delete_uitgave(
                                DB_PATH, uitgave_id=row['id_uitgave'])
                        except YearLockedError as e:
                            ui.notify(str(e), type='negative')
                            return
                        dialog.close()
                        ui.notify('Uitgave verwijderd', type='positive')
                        await refresh()

                    ui.button('Verwijderen', on_click=do_delete_u) \
                        .props('color=negative')
            dialog.open()

    table.on('delete_row',
              lambda e: asyncio.create_task(_on_delete_row(e.args)))
```

- [ ] **Step 2: Smoke test**

Click 🗑 on a bank row — confirms with factuur-revert notice if applicable, deletes. Click 🗑 on a manual cash row — plain confirm + delete.

- [ ] **Step 3: Run full suite**

- [ ] **Step 4: Commit**

```bash
git add pages/transacties.py
git commit -m "feat(transacties): row-delete handler (bank + manual)"
```

---

### Task 16: `/transacties` — bulk actions

Adds: Categorie wijzigen · Markeer als privé · Verwijderen. Mirrors current kosten.py bulk handlers. Bulk privé is bank-only (skips manual rows); bulk delete skips bank rows with matched factuur (same as today).

**Files:**
- Modify: `pages/transacties.py`

- [ ] **Step 1: Fill the bulk-bar**

Replace the existing empty bulk-bar block with:
```python
        # Bulk bar
        bulk_bar = ui.row().classes('w-full items-center gap-2 q-py-sm') \
            .style('background:#0f172a;color:white;border-radius:8px;'
                    'padding:8px 16px')
        bulk_bar.set_visibility(False)
        bulk_bar_ref['ref'] = bulk_bar
        with bulk_bar:
            bulk_label_ref['ref'] = ui.label('')

            async def bulk_set_cat():
                with ui.dialog() as dlg, ui.card():
                    ui.label('Nieuwe categorie voor selectie') \
                        .classes('text-h6')
                    sel = ui.select(BANK_CATEGORIEEN, label='Categorie') \
                        .classes('w-full')
                    with ui.row().classes(
                            'w-full justify-end gap-2 q-mt-md'):
                        ui.button('Annuleren', on_click=dlg.close) \
                            .props('flat')

                        async def apply_bulk_cat():
                            n_ok, n_skip = 0, 0
                            for r in table_ref['table'].selected:
                                try:
                                    if r.get('id_bank') is not None:
                                        await set_banktx_categorie(
                                            DB_PATH,
                                            bank_tx_id=r['id_bank'],
                                            categorie=sel.value or '')
                                    elif r.get('id_uitgave') is not None:
                                        await update_uitgave(
                                            DB_PATH,
                                            uitgave_id=r['id_uitgave'],
                                            categorie=sel.value or '')
                                    else:
                                        continue
                                    n_ok += 1
                                except YearLockedError:
                                    n_skip += 1
                            dlg.close()
                            msg = f'{n_ok} bijgewerkt'
                            if n_skip:
                                msg += f', {n_skip} overgeslagen (jaar afgesloten)'
                            ui.notify(
                                msg,
                                type='positive' if n_ok else 'warning')
                            await refresh()

                        ui.button('Toepassen', on_click=apply_bulk_cat) \
                            .props('color=primary')
                dlg.open()

            ui.button('Categorie wijzigen', icon='label',
                       on_click=bulk_set_cat) \
                .props('outline color=white size=sm')

            async def bulk_negeren():
                n_ok, n_skip = 0, 0
                for r in table_ref['table'].selected:
                    if r.get('id_bank') is None:
                        continue  # manual rows skipped
                    try:
                        await mark_banktx_genegeerd(
                            DB_PATH, bank_tx_id=r['id_bank'], genegeerd=1)
                        n_ok += 1
                    except YearLockedError:
                        n_skip += 1
                msg = f'{n_ok} rij(en) als privé gemarkeerd'
                if n_skip:
                    msg += f', {n_skip} overgeslagen'
                ui.notify(msg, type='positive' if n_ok else 'warning')
                await refresh()

            ui.button('Markeer als privé', icon='visibility_off',
                       on_click=bulk_negeren) \
                .props('outline color=white size=sm')

            async def bulk_delete():
                n_ok, n_skip = 0, 0
                for r in table_ref['table'].selected:
                    try:
                        if r.get('id_bank') is not None:
                            await delete_banktransacties(
                                DB_PATH, transactie_ids=[r['id_bank']])
                        elif r.get('id_uitgave') is not None:
                            await delete_uitgave(
                                DB_PATH, uitgave_id=r['id_uitgave'])
                        else:
                            continue
                        n_ok += 1
                    except YearLockedError:
                        n_skip += 1
                msg = f'{n_ok} verwijderd'
                if n_skip:
                    msg += f', {n_skip} overgeslagen'
                ui.notify(msg, type='positive' if n_ok else 'warning')
                await refresh()

            ui.button('Verwijderen', icon='delete', on_click=bulk_delete) \
                .props('outline color=white size=sm')

        def _update_bulk_bar():
            n = len(table_ref['table'].selected) if table_ref['table'] else 0
            if n > 0:
                bulk_bar.set_visibility(True)
                bulk_label_ref['ref'].text = f'{n} geselecteerd'
            else:
                bulk_bar.set_visibility(False)

        table.on('selection', lambda _: _update_bulk_bar())
```

- [ ] **Step 2: Smoke test**

Select rows via checkbox, verify bulk bar appears with 3 buttons, each works.

- [ ] **Step 3: Run full suite + commit**

```bash
git add pages/transacties.py
git commit -m "feat(transacties): bulk bar (categorie, privé, delete)"
```

---

### Task 17: `/transacties` — "+ Contante uitgave" button (cash-entry dialog port)

Ports `open_add_uitgave_dialog` from `pages/kosten.py:1084-1279`. The function is long but verbatim except for closure references — we pass `refresh` in.

**Files:**
- Modify: `pages/transacties.py` — add cash-entry button + port the dialog

- [ ] **Step 1: Port the dialog**

Option A — move `open_add_uitgave_dialog` body into `pages/transacties.py` as a module-level async function taking `refresh` + `repr_aftrek_pct` as args. Option B — leave it in `pages/kosten.py` and import it. Option A wins because `pages/kosten.py` is being slimmed in Phase 3 anyway.

Copy `open_add_uitgave_dialog` from `pages/kosten.py:1084-1279` into `pages/transacties.py` as a module-level function. Rename its `ververs_transacties()` callback parameter to `refresh` and take `repr_aftrek_pct: int = 80` as an arg.

Change signature:
```python
async def open_add_uitgave_dialog(
    prefill: dict | None = None,
    on_saved = None,
    refresh = None,
    repr_aftrek_pct: int = 80,
):
    """Dialog to add a new manual (cash) uitgave.

    Extracted from pages/kosten.py during the consolidation. ``refresh`` is
    the caller's ververs-function; called after each successful save.
    """
    # …body identical to pages/kosten.py:1084-1279, with:
    #   await ververs_transacties()  →  await (refresh() if refresh else asyncio.sleep(0))
```

Add needed imports at top of `pages/transacties.py`:
```python
import inspect
from pathlib import Path
from database import get_uitgaven, get_fiscale_params
```

- [ ] **Step 2: Load `repr_aftrek_pct` in `transacties_page`**

At top of `transacties_page`:
```python
    fp = await get_fiscale_params(DB_PATH, jaar=datetime.now().year)
    repr_aftrek_pct = int(fp.repr_aftrek_pct) if fp else 80
```

- [ ] **Step 3: Add the `+ Contante uitgave` button**

In the header row, to the LEFT of the CSV upload:
```python
            ui.button('+ Contante uitgave', icon='add',
                       on_click=lambda: open_add_uitgave_dialog(
                           refresh=refresh,
                           repr_aftrek_pct=repr_aftrek_pct)) \
                .props('color=primary dense')
```

- [ ] **Step 4: Smoke test**

Click "+ Contante uitgave". Fill date/categorie/omschrijving/bedrag. Save. Row appears in table.

- [ ] **Step 5: Run full suite + commit**

```bash
git add pages/transacties.py
git commit -m "feat(transacties): + Contante uitgave button (cash-entry dialog)"
```

---

### Task 18: `/transacties` — "Archief-PDFs importeren" dialog

Ports `open_import_dialog` from `pages/kosten.py:1281-1463`. Same verbatim-port approach.

**Files:**
- Modify: `pages/transacties.py`

- [ ] **Step 1: Port `open_import_dialog`**

Copy the body verbatim from `pages/kosten.py:1281-1463` into `pages/transacties.py` as a module-level async function. Rename `filter_jaar` reference to take `default_jaar` arg; rename `ververs_transacties` callback to `refresh`.

Signature:
```python
async def open_import_dialog(default_jaar: int, refresh, jaren_opts,
                              repr_aftrek_pct: int = 80):
    """Archief-PDF importeer dialog. Ported from pages/kosten.py."""
    # …body identical, with:
    #   import_jaar = {'value': filter_jaar['value']}  →  {'value': default_jaar}
    #   jaren (outer closure)  →  jaren_opts
    #   on_import_close: await ververs_transacties()  →  await refresh()
```

- [ ] **Step 2: Add the button in the header**

To the right of "Importeer CSV":
```python
            ui.button('Archief-PDFs importeren', icon='folder_open',
                       on_click=lambda: open_import_dialog(
                           default_jaar=filter_jaar['value'],
                           refresh=refresh,
                           jaren_opts=year_options(),
                           repr_aftrek_pct=repr_aftrek_pct)) \
                .props('flat color=secondary dense')
```

- [ ] **Step 3: Smoke test**

Open the import dialog. Verify archive scan works. Click an item → add-uitgave dialog opens pre-filled. Save. Row on /transacties has both the bank-link (via M1 ensure route) and the uploaded PDF.

- [ ] **Step 4: Run full suite + commit**

```bash
git add pages/transacties.py
git commit -m "feat(transacties): Archief-PDFs importeren dialog"
```

---

### Task 19: `/transacties` — "Matches controleren (N)" live count

Already partially wired in Task 14. This task confirms `_refresh_match_count` runs on every `refresh()` and the button hides at N=0.

**Files:**
- Modify: `pages/transacties.py` — verify `_refresh_match_count` is called

- [ ] **Step 1: Verify the button updates**

Ensure `refresh()` (Task 12) calls `await _refresh_match_count()`. Ensure the button's `text` is re-assigned each time. In dev:
1. Import a CSV that generates proposals → button shows "Matches controleren (N)".
2. Apply matches → N drops.
3. Reach N=0 → button hides.

- [ ] **Step 2: Add a test**

Create `tests/test_match_count_surfaces_unmatched.py`:
```python
"""find_factuur_matches returns unmatched proposals across refresh calls."""
import pytest
import aiosqlite
from datetime import date
from database import find_factuur_matches


async def _seed(db):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO facturen "
            "(nummer, klant_id, datum, totaal_bedrag, status, type, bron) "
            "VALUES ('2026-001', 0, '2026-03-01', 100.0, 'verstuurd', "
            "        'factuur', 'manual')")
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij, omschrijving, tegenrekening, "
            " csv_bestand) VALUES (1, '2026-03-05', 100.0, 'Klant', "
            "                       '2026-001', '', 't.csv')")
        await conn.commit()


@pytest.mark.asyncio
async def test_find_factuur_matches_returns_proposal(db):
    await _seed(db)
    proposals = await find_factuur_matches(db)
    assert len(proposals) == 1
```

- [ ] **Step 3: Run + commit**

```bash
git add pages/transacties.py tests/test_match_count_surfaces_unmatched.py
git commit -m "feat(transacties): wire Matches controleren count + regression test"
```

---

### Phase 2 checkpoint

After Task 19: `/transacties` is fully functional. `/bank` and `/kosten` still work unchanged. Tag: `phase-2-inbox-complete`.

```bash
git tag phase-2-inbox-complete
```

Manual QA gate — go through the spec §7 manual-QA script steps 1-3 (categorise debit, add cash, import CSV + match). All must pass on `/transacties`.

---

## Phase 3 — `/kosten` slimmed (Tasks 20-24)

---

### Task 20: Slim `pages/kosten.py` — delete tabel/bulk/dialogs, keep KPI + activastaat

Strip everything that's duplicated on `/transacties`. What stays: page header (slimmer), KPI strip, categorie-breakdown, Investeringen tab.

**Files:**
- Modify: `pages/kosten.py` — aggressive delete, keep minimal skeleton

- [ ] **Step 1: Rewrite `pages/kosten.py`**

Replace the entire file with:
```python
"""Kosten pagina — overzicht + activastaat. Read-only.

Mutations live on /transacties. This page is summary-only.
"""
import asyncio
from datetime import date

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import format_euro, KOSTEN_CATEGORIEEN
from components.shared_ui import year_options
from database import (
    DB_PATH, get_kpi_kosten, get_kosten_breakdown,
    get_kosten_per_maand, get_terugkerende_kosten,
)
from pages.kosten_investeringen import laad_activastaat


@ui.page('/kosten')
async def kosten_page():
    create_layout('Kosten', '/kosten')
    huidig_jaar = date.today().year
    filter_jaar = {'value': huidig_jaar}

    kpi_container = {'ref': None}
    chart_container = {'ref': None}
    breakdown_container = {'ref': None}
    terugkerend_container = {'ref': None}
    activa_container = {'ref': None}

    async def ververs_overview():
        await _laad_kpi(kpi_container['ref'], filter_jaar['value'])
        await _laad_per_maand(chart_container['ref'], filter_jaar['value'])
        await _laad_breakdown(breakdown_container['ref'], filter_jaar['value'])
        await _laad_terugkerend(terugkerend_container['ref'],
                                  filter_jaar['value'])

    async def ververs_investeringen():
        await laad_activastaat(
            activa_container['ref'], filter_jaar['value'],
            ververs_overview)

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):
        with ui.row().classes('w-full items-center'):
            page_title('Kosten')

        with ui.row().classes('items-center gap-2'):
            jaar_select = ui.select(
                {j: str(j) for j in year_options()},
                label='Jaar', value=huidig_jaar,
            ).classes('w-28')

            async def on_jaar_change():
                filter_jaar['value'] = jaar_select.value
                await ververs_overview()

            jaar_select.on('update:model-value',
                            lambda _=None: on_jaar_change())

        with ui.tabs().classes('w-full') as tabs:
            tab_overview = ui.tab('Overzicht', icon='insights')
            tab_inv = ui.tab('Investeringen', icon='inventory_2')

        with ui.tab_panels(tabs, value=tab_overview).classes('w-full'):
            with ui.tab_panel(tab_overview):
                kpi_container['ref'] = ui.row().classes('w-full gap-4')
                chart_container['ref'] = ui.column().classes('w-full')
                breakdown_container['ref'] = ui.column().classes('w-full')
                terugkerend_container['ref'] = ui.column().classes('w-full')

            with ui.tab_panel(tab_inv):
                activa_container['ref'] = ui.column().classes('w-full gap-2')

        async def on_tab_change():
            if tabs.value == 'Investeringen':
                await ververs_investeringen()

        tabs.on('update:model-value',
                 lambda _: asyncio.create_task(on_tab_change()))

    await ververs_overview()


# Loader stubs — filled in subsequent tasks (21-24).
async def _laad_kpi(container, jaar):
    """KPI strip. Wired in Task 21."""
    pass


async def _laad_per_maand(container, jaar):
    """Per-maand bar chart. Wired in Task 22."""
    pass


async def _laad_breakdown(container, jaar):
    """Categorie breakdown (clickable). Wired in Task 23."""
    pass


async def _laad_terugkerend(container, jaar):
    """Terugkerende kosten card. Wired in Task 24."""
    pass
```

- [ ] **Step 2: Smoke test**

Open /kosten. Expect: page loads, jaar selector + 2 tabs. Overzicht is empty (stubs). Investeringen tab opens activastaat unchanged.

- [ ] **Step 3: Run full suite — may break tests that exercised the old kosten.py**

Delete any tests in `tests/test_kosten*.py` that relied on the old /kosten tabel/bulk. Keep tests for activastaat (`test_activastaat_*`).

- [ ] **Step 4: Commit**

```bash
git add pages/kosten.py tests/
git commit -m "refactor(kosten): strip tabel/bulk/dialogs — keep shell + activastaat"
```

---

### Task 21: `/kosten` — KPI strip (with click-through to `/transacties`)

Restore the KPI strip using `get_kpi_kosten`. "Te verwerken" card navigates to `/transacties?status=ongecategoriseerd&jaar=X`.

**Files:**
- Modify: `pages/kosten.py:_laad_kpi`

- [ ] **Step 1: Fill `_laad_kpi`**

Replace the `_laad_kpi` stub with:
```python
async def _laad_kpi(container, jaar):
    if container is None:
        return
    container.clear()
    kpi = await get_kpi_kosten(DB_PATH, jaar)

    def _card(label: str, value: str, sub: str | None = None,
              color: str = 'primary', icon: str | None = None,
              on_click=None):
        with ui.card().classes('flex-1 q-pa-md cursor-pointer' if on_click
                                else 'flex-1 q-pa-md') as c:
            if on_click:
                c.on('click', lambda _: on_click())
            with ui.row().classes('items-center gap-2'):
                if icon:
                    ui.icon(icon, color=color).classes('text-lg')
                ui.label(label).classes(
                    'text-caption text-uppercase text-grey')
            ui.label(value).classes('text-h5 text-bold q-mt-xs') \
                .style('font-variant-numeric: tabular-nums')
            if sub:
                ui.label(sub).classes('text-caption text-grey')

    with container:
        _card(f'Totaal kosten {jaar}',
              format_euro(kpi.totaal),
              f'{len([m for m in kpi.monthly_totals if m>0])} actieve maanden')

        _card('Te verwerken',
              str(kpi.ontbreekt_count),
              format_euro(kpi.ontbreekt_bedrag),
              color='warning', icon='warning',
              on_click=lambda: ui.navigate.to(
                  f'/transacties?status=ongecategoriseerd&jaar={jaar}'))

        _card(f'Afschrijvingen {jaar}',
              format_euro(kpi.afschrijvingen_jaar),
              'Zie tab Investeringen',
              icon='trending_down')

        _card(f'Investeringen {jaar}',
              str(kpi.investeringen_count),
              format_euro(kpi.investeringen_bedrag),
              icon='inventory_2')
```

- [ ] **Step 2: Add import**

At top of `pages/kosten.py`, add `get_kpi_kosten` — already listed in Step 1's import block.

- [ ] **Step 3: Smoke test**

Open /kosten. KPI strip renders. Click "Te verwerken" → navigates to `/transacties?status=ongecategoriseerd&jaar=2026` with filter pre-applied.

- [ ] **Step 4: Commit**

```bash
git add pages/kosten.py
git commit -m "feat(kosten): KPI strip + Te verwerken click-through"
```

---

### Task 22: `/kosten` — per-maand bar chart (`ui.echart`)

12 months, hover tooltip with `€` amount. Click-through per bar not implemented (month filter on /transacties would be nice but is YAGNI; can add later).

**Files:**
- Modify: `pages/kosten.py:_laad_per_maand`

- [ ] **Step 1: Fill `_laad_per_maand`**

```python
async def _laad_per_maand(container, jaar):
    if container is None:
        return
    container.clear()
    data = await get_kosten_per_maand(DB_PATH, jaar)
    months = ['Jan', 'Feb', 'Mrt', 'Apr', 'Mei', 'Jun',
              'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dec']
    with container:
        with ui.card().classes('w-full q-pa-md'):
            ui.label(f'Kosten per maand — {jaar}') \
                .classes('text-subtitle1 text-bold')
            ui.echart({
                'xAxis': {'type': 'category', 'data': months},
                'yAxis': {'type': 'value'},
                'tooltip': {
                    'trigger': 'axis',
                    'valueFormatter': (
                        "function(v){ return '€ ' + "
                        "Number(v).toLocaleString('nl-NL',"
                        "{minimumFractionDigits:2}); }"),
                },
                'series': [{
                    'type': 'bar',
                    'data': [round(v, 2) for v in data],
                    'itemStyle': {'color': '#0F766E'},
                }],
                'grid': {'left': 60, 'right': 20, 'top': 20, 'bottom': 40},
            }).classes('w-full').style('height:240px')
```

- [ ] **Step 2: Smoke test**

Open /kosten. Bar chart renders with 12 months. Hover shows €-formatted tooltip.

- [ ] **Step 3: Commit**

```bash
git add pages/kosten.py
git commit -m "feat(kosten): per-maand bar chart (ui.echart)"
```

---

### Task 23: `/kosten` — categorie breakdown (clickable) + M7 separated uncategorised card

Breakdown card from old `_laad_breakdown`, but bars are now clickable → `/transacties?jaar=X&categorie=Y`. The empty-categorie bucket (`''`) rendered as a separate muted card ABOVE the breakdown (M7).

**Files:**
- Modify: `pages/kosten.py:_laad_breakdown`

- [ ] **Step 1: Fill `_laad_breakdown`**

```python
async def _laad_breakdown(container, jaar):
    if container is None:
        return
    container.clear()
    totals = await get_kosten_breakdown(DB_PATH, jaar)
    if not totals:
        return

    uncat_amount = totals.pop('', 0.0)
    sorted_totals = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    grand = sum(totals.values()) + uncat_amount

    with container:
        # M7 — separate card for uncategorised, muted, not clickable
        if uncat_amount > 0:
            with ui.card().classes('w-full q-pa-md') \
                    .style('background:#f8fafc;border-left:4px solid #f59e0b'):
                with ui.row().classes('w-full items-center'):
                    ui.icon('warning', color='warning').classes('text-lg')
                    ui.label('Nog te categoriseren').classes('text-body2')
                    ui.space()
                    ui.label(format_euro(uncat_amount)) \
                        .classes('text-body2 text-bold') \
                        .style('font-variant-numeric:tabular-nums')
                ui.label(
                    'Verwerk deze op Transacties om ze hier te laten '
                    'landen.').classes('text-caption text-grey')

        # Real categories — bars, clickable
        with ui.card().classes('w-full q-pa-md'):
            with ui.row().classes('w-full items-center'):
                ui.label(f'Kosten per categorie — {jaar}') \
                    .classes('text-subtitle1 text-bold')
                ui.space()
                ui.label(f'Totaal {format_euro(grand)}') \
                    .classes('text-caption text-grey')

            for name, amt in sorted_totals:
                pct = (amt / grand * 100) if grand else 0
                row = ui.column().classes(
                    'w-full gap-0 q-my-xs cursor-pointer')
                with row:
                    with ui.row().classes('w-full'):
                        ui.label(name).classes('text-body2')
                        ui.space()
                        ui.label(
                            f'{format_euro(amt)} · {pct:.1f}%') \
                            .classes('text-body2 text-bold') \
                            .style('font-variant-numeric:tabular-nums')
                    ui.linear_progress(value=pct / 100) \
                        .props('color=primary size=6px')
                row.on('click', lambda _=None, n=name:
                        ui.navigate.to(
                            f'/transacties?jaar={jaar}&categorie={n}'))
```

- [ ] **Step 2: Smoke test**

Open /kosten. Verify: bars render per categorie. Uncategorised appears as separate muted card at top (if any). Click a bar → navigates to /transacties with filter.

- [ ] **Step 3: Commit**

```bash
git add pages/kosten.py
git commit -m "feat(kosten): breakdown click-through + separated uncategorised card (M7)"
```

---

### Task 24: `/kosten` — terugkerende-kosten card

**Files:**
- Modify: `pages/kosten.py:_laad_terugkerend`

- [ ] **Step 1: Fill `_laad_terugkerend`**

```python
async def _laad_terugkerend(container, jaar):
    if container is None:
        return
    container.clear()
    items = await get_terugkerende_kosten(DB_PATH, jaar=jaar)
    if not items:
        return
    with container:
        with ui.card().classes('w-full q-pa-md'):
            ui.label(f'Terugkerende kosten — {jaar}') \
                .classes('text-subtitle1 text-bold')
            ui.label('Tegenpartijen met 3 of meer betalingen in de '
                      'laatste 12 maanden.') \
                .classes('text-caption text-grey q-mb-sm')
            for item in items:
                row = ui.row().classes(
                    'w-full items-center q-py-xs cursor-pointer')
                with row:
                    ui.label(item['tegenpartij']) \
                        .classes('text-body2').style('flex:1')
                    ui.label(str(item['count'])) \
                        .classes('text-caption text-grey').style('width:40px')
                    ui.label(item['laatste_datum']) \
                        .classes('text-caption text-grey') \
                        .style('width:110px')
                    ui.label(format_euro(item['jaar_totaal'])) \
                        .classes('text-body2 text-bold') \
                        .style('font-variant-numeric:tabular-nums;'
                                'width:110px;text-align:right')
                row.on('click', lambda _=None, tp=item['tegenpartij']:
                        ui.navigate.to(
                            f'/transacties?jaar={jaar}&search={tp}'))
```

- [ ] **Step 2: Smoke test**

Open /kosten. Terugkerende-kosten card lists recurring vendors. Click row → /transacties?jaar=X&search=Tegenpartij.

- [ ] **Step 3: Commit**

```bash
git add pages/kosten.py
git commit -m "feat(kosten): terugkerende-kosten card"
```

---

### Phase 3 checkpoint

After Task 24: `/kosten` is overview-only. Full spec §7 manual QA should pass. Tag: `phase-3-kosten-overview-complete`.

```bash
git tag phase-3-kosten-overview-complete
```

---

## Phase 4 — sidebar & redirect (Tasks 25-26)

---

### Task 25: Sidebar — "Bank" → "Transacties"

**Files:**
- Modify: `components/layout.py:207-209`

- [ ] **Step 1: Update nav group**

Replace:
```python
        [('Facturen', 'receipt_long', '/facturen'),
         ('Kosten', 'shopping_bag', '/kosten'),
         ('Bank', 'account_balance_wallet', '/bank')],
```

With:
```python
        [('Facturen', 'receipt_long', '/facturen'),
         ('Transacties', 'account_balance_wallet', '/transacties'),
         ('Kosten', 'shopping_bag', '/kosten')],
```

Note order change: working flow is Facturen → Transacties → Kosten (send invoices → process transactions → review results).

- [ ] **Step 2: Smoke — click every nav item, verify routing**

- [ ] **Step 3: Commit**

```bash
git add components/layout.py
git commit -m "feat(layout): sidebar — Bank → Transacties, reorder for flow"
```

---

### Task 26: `/bank` → `/transacties` soft redirect

**Files:**
- Modify: `pages/bank.py` — replace entire body with redirect

- [ ] **Step 1: Replace `pages/bank.py`**

Replace the entire contents of `pages/bank.py` with:
```python
"""/bank — soft redirect to /transacties.

Preserves bookmarks one release. Remove this file after the next release
cuts. See docs/superpowers/specs/2026-04-22-bank-kosten-consolidation-design.md
§6 Phase 5.
"""
from nicegui import ui


@ui.page('/bank')
async def bank_redirect():
    ui.navigate.to('/transacties')
```

- [ ] **Step 2: Smoke — open /bank, lands on /transacties**

- [ ] **Step 3: Commit**

```bash
git add pages/bank.py
git commit -m "feat(bank): soft redirect /bank → /transacties"
```

---

### Phase 4 checkpoint

After Task 26: `/bank` redirects, sidebar shows Transacties. Tag: `phase-4-flip-complete`.

```bash
git tag phase-4-flip-complete
```

---

## Phase 5 — cleanup (Tasks 27-29)

---

### Task 27: Rename `KostenRow` → `TransactieRow` (grep-and-fix callers)

**Note:** If Phase 1 introduced `TransactieRow` as a NEW type (rather than rename), `KostenRow` still exists. In that case the rename step is: delete `KostenRow`, migrate any remaining callers to `TransactieRow`.

**Files:**
- Modify: `database.py` — delete `KostenRow` dataclass + the `get_kosten_view` function (if any callers remain they must use `get_transacties_view`)
- Modify: call-sites of `KostenRow` and `get_kosten_view` everywhere

- [ ] **Step 1: Grep for remaining callers**

```bash
grep -rn "KostenRow\|get_kosten_view" --include="*.py" .
```

Expected: only `database.py` (definition) and possibly `pages/kosten.py` / `components/transacties_dialog.py` if they still reference it.

- [ ] **Step 2: Replace all callers**

For each hit outside `database.py`:
- `KostenRow` → `TransactieRow`
- `get_kosten_view(...)` → `get_transacties_view(...)` (signatures are compatible for the args used)

- [ ] **Step 3: Delete `KostenRow` and `get_kosten_view` from `database.py`**

- [ ] **Step 4: Run full suite**

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add -u
git commit -m "refactor: rename KostenRow → TransactieRow, drop get_kosten_view"
```

---

### Task 28: Rename `components/kosten_helpers.py` → `components/transacties_helpers.py`

**Files:**
- Rename: `components/kosten_helpers.py` → `components/transacties_helpers.py`
- Rename: `tests/test_kosten_helpers.py` → `tests/test_transacties_helpers.py`
- Modify: all import sites

- [ ] **Step 1: Git-rename the files**

```bash
git mv components/kosten_helpers.py components/transacties_helpers.py
git mv tests/test_kosten_helpers.py tests/test_transacties_helpers.py
```

- [ ] **Step 2: Fix imports**

```bash
grep -rln "from components.kosten_helpers\|from components import kosten_helpers" --include="*.py" .
```

For each: replace `components.kosten_helpers` → `components.transacties_helpers`.

- [ ] **Step 3: Run full suite**

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "refactor: rename components.kosten_helpers → transacties_helpers"
```

---

### Task 29: Update `CLAUDE.md` + memory files

**Files:**
- Modify: `CLAUDE.md` — rewrite "Kosten-pagina (reconciliatie)" section as "Transacties-pagina"; add smaller "Kosten-pagina (overzicht)" section
- Modify: memory `MEMORY.md`, `open_plans.md`

- [ ] **Step 1: Rewrite `CLAUDE.md` section**

In `CLAUDE.md`, locate the heading `### Kosten-pagina (reconciliatie)` and replace the whole section with:

```markdown
### Transacties-pagina (`/transacties`)

Single inbox for all money-movement work — bank debits + bank positives +
manual cash uitgaven. Source: `get_transacties_view(db, jaar, maand,
status, categorie, type, search, include_genegeerd)` in `database.py`.

- **Row status** (`derive_status` in `components/transacties_helpers.py`):
  `prive_verborgen` (genegeerd=1) → `gekoppeld_factuur` (positive matched
  to factuur) → `ongecategoriseerd` → `ontbreekt_bon` (debit cat'd w/o PDF)
  → `compleet` (debit: cat+bon) → `gecategoriseerd` (positive: cat).
- **Categorie write**: UI handler branches on `id_bank` — bank rows go
  through `set_banktx_categorie` (sign-aware: debit → lazy-create uitgave
  + update; positive → update banktransacties.categorie). Manual rows go
  straight to `update_uitgave`.
- **Per-row category options**: debits+cash get `KOSTEN_CATEGORIEEN`;
  positives get `['Omzet', 'Prive', 'Belasting', 'AOV']`. Injected
  server-side as `props.row.cat_options`.
- **Detail dialog** lives in `components/transacties_dialog.py`. Re-uses
  `get_uitgave_by_id` for bootstrap (M5 fix — no list-and-filter).
- **Factuur-match preview**: after CSV import + header button
  "Matches controleren (N)" for manual review.
- **Cash entries** (`+ Contante uitgave`): `add_uitgave(bank_tx_id=None)`.
- **Archief-PDFs importeren**: `scan_archive()` + `open_add_uitgave_dialog`
  with prefill. Auto-link goes through `ensure_uitgave_for_banktx` (M1).
- **Bulk**: Categorie wijzigen · Markeer als privé (bank-only) · Verwijderen.
- **Query-params**: `?jaar/maand/status/categorie/type/search` pre-populate
  filters. Used for click-through from `/kosten`.

### Kosten-pagina (`/kosten`) — overzicht

Read-only. Jaar-selector + 2 tabs (Overzicht / Investeringen). No form
controls that mutate data.

- **KPI strip**: `get_kpi_kosten`. "Te verwerken" card navigates to
  `/transacties?status=ongecategoriseerd&jaar=X`.
- **Per-maand bar chart**: `get_kosten_per_maand` (12 slots).
- **Categorie breakdown**: `get_kosten_breakdown` — each bar is clickable →
  `/transacties?jaar=X&categorie=Y`. The `(nog te categoriseren)` bucket
  renders as a separate muted card above (M7).
- **Terugkerende kosten card**: `get_terugkerende_kosten` — vendors with
  ≥3 hits in 365d, sorted by jaar-totaal DESC. Click → `/transacties?
  search=tegenpartij`.
- **Investeringen tab**: unchanged, `pages/kosten_investeringen.py:
  laad_activastaat`.
```

Also update the "Database" section: add migration 28 note — `CREATE UNIQUE INDEX idx_uitgaven_bank_tx_unique ON uitgaven(bank_tx_id) WHERE bank_tx_id IS NOT NULL`.

- [ ] **Step 2: Update memory files**

Edit `/Users/macbookpro_test/.claude/projects/.../memory/open_plans.md`:
- Mark the Kosten v1.1 polish section: M1 `[DONE]`, M2 `[SUBSUMED]`, M3 `[SUBSUMED]`, M4 `[SUBSUMED]`, M5 `[DONE]`, M7 `[DONE]`. Lazy-create-cancel-orphan stays `[OPEN]`.

Edit `MEMORY.md` — add a line:
```
- [Bank/Kosten consolidation (2026-04-23)](project_transacties_consolidation.md) — /bank folded into /transacties inbox; /kosten reshaped as read-only overview; rename KostenRow→TransactieRow
```

Create `project_transacties_consolidation.md` with the key architectural decisions (concise).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): rewrite Kosten section as Transacties + Overzicht split"
```

---

### Phase 5 checkpoint / final

After Task 29: clean. Full test suite green, spec §10 success criteria met, manual QA script §7 green.

```bash
git tag phase-5-complete
```

Leave `pages/bank.py` redirect stub in place — delete only after one release cycle (manual follow-up; not a task in this plan).

---

## Appendix A — rollback strategy

Each phase ends with a git tag. To roll back:

- Before Phase 4 flip: `git reset --hard phase-3-kosten-overview-complete` — new page exists but sidebar still points to old /bank.
- Before Phase 5 renames: `git reset --hard phase-4-flip-complete` — `KostenRow` still exists alongside `TransactieRow`.

Database changes (migratie 28) are additive — rollback DB means dropping the partial index:
```sql
DROP INDEX IF EXISTS idx_uitgaven_bank_tx_unique;
```

## Appendix B — spec cross-reference

| Spec section | Plan tasks |
|---|---|
| §3.1 `/transacties` | 12, 13, 14, 15, 16, 17, 18, 19 |
| §3.2 `/kosten` | 20, 21, 22, 23, 24 |
| §4.0 Migratie 28 | 1 |
| §4.1 `get_transacties_view` | 3, 4 |
| §4.1 `derive_status` | 2 |
| §4.2 `get_kosten_breakdown` | 6 |
| §4.3 `get_kosten_per_maand` | 7 |
| §4.4 `get_terugkerende_kosten` | 8 |
| §4.4b `get_uitgave_by_id` | 5 |
| §4.5 `get_categorie_suggestions` | 9 |
| §4.7 renames | 27, 28 |
| §5 file layout | whole plan |
| §6 phasing | Phase headers |
| §7 testing | each task + phase checkpoints |
| §8 risks | called out where relevant |
| §9 polish items | M1→Task 1+10, M5→Task 5+11, M7→Task 23 |
| §10 success criteria | Phase 5 checkpoint |
