# Kosten page rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `/kosten` around a bank-transaction-centric reconciliation list, linking `banktransacties` ↔ `uitgaven` via a new nullable FK, while preserving all existing fiscal logic (activastaat, afschrijvingen, KIA, year-lock).

**Architecture:** Additive schema (two columns, two indexes), a pure helpers module, five new DB helpers, and a rewritten `pages/kosten.py` with two tabs (Transacties / Investeringen). Activastaat UI is lifted verbatim into `pages/kosten_investeringen.py`. No fiscal code, no existing API, and no data migration are touched.

**Tech Stack:** Python 3.12+ · NiceGUI ≥3.0 (Quasar/Vue) · aiosqlite · raw SQL with `?` placeholders · pytest-asyncio · pywebview (native mode).

**Spec:** `docs/superpowers/specs/2026-04-21-kosten-rework-design.md` (single source of truth; if this plan and the spec disagree, the spec wins — stop and reconcile).

**Test command (always):**
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

---

## File map

**New files:**
- `components/kosten_helpers.py` — pure helpers (status derivation, token match, avatar color, initials)
- `pages/kosten_investeringen.py` — lifted activastaat UI (same code, same behavior)
- `tests/test_kosten_migrations.py`
- `tests/test_kosten_helpers.py`
- `tests/test_ensure_uitgave.py`
- `tests/test_bank_genegeerd.py`
- `tests/test_kosten_matching.py`
- `tests/test_kosten_view.py`
- `tests/test_kpi_kosten.py`

**Modified files:**
- `database.py` — migration #26 + 5 new helpers
- `pages/kosten.py` — rewrite
- (optional) `import_/expense_utils.py` — may add `extract_bedrag_from_filename`; deferrable

**Untouched (do not edit):**
- `pages/bank.py`, `fiscal/afschrijvingen.py`, `pages/aangifte.py`, `pages/jaarafsluiting.py`, `components/layout.py`

---

## Task 1: Schema migration (#26) — add `bank_tx_id` + `genegeerd`

**Files:**
- Modify: `database.py` (MIGRATIONS list, around line ~410)
- Create: `tests/test_kosten_migrations.py`

- [ ] **Step 1.1: Write the failing test**

```python
# tests/test_kosten_migrations.py
"""Migration #26 — bank_tx_id on uitgaven, genegeerd on banktransacties."""
import aiosqlite
import pytest


async def _get_columns(db_path, table: str) -> set[str]:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(f"PRAGMA table_info({table})")
        return {r[1] for r in await cur.fetchall()}


async def _get_indexes(db_path, table: str) -> set[str]:
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(f"PRAGMA index_list({table})")
        return {r[1] for r in await cur.fetchall()}


@pytest.mark.asyncio
async def test_migration_26_adds_bank_tx_id(db):
    cols = await _get_columns(db, "uitgaven")
    assert "bank_tx_id" in cols


@pytest.mark.asyncio
async def test_migration_26_adds_genegeerd(db):
    cols = await _get_columns(db, "banktransacties")
    assert "genegeerd" in cols


@pytest.mark.asyncio
async def test_migration_26_default_values(db):
    """Fresh row defaults: bank_tx_id NULL; genegeerd 0."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag) "
            "VALUES ('2026-01-01', 'Kantoor', 'pen', 2.50)")
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag) "
            "VALUES ('2026-01-01', -2.50)")
        await conn.commit()
        cur = await conn.execute("SELECT bank_tx_id FROM uitgaven")
        assert (await cur.fetchone())[0] is None
        cur = await conn.execute("SELECT genegeerd FROM banktransacties")
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_migration_26_indexes_exist(db):
    u_idx = await _get_indexes(db, "uitgaven")
    b_idx = await _get_indexes(db, "banktransacties")
    assert "idx_uitgaven_bank_tx" in u_idx
    assert "idx_bank_genegeerd" in b_idx


@pytest.mark.asyncio
async def test_migration_26_fk_set_null_on_delete(db):
    """Deleting a banktransactie sets uitgaven.bank_tx_id to NULL (no cascade)."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag) "
            "VALUES (1, '2026-01-01', -10.00)")
        await conn.execute(
            "INSERT INTO uitgaven "
            "(datum, categorie, omschrijving, bedrag, bank_tx_id) "
            "VALUES ('2026-01-01', 'Kantoor', 'x', 10.00, 1)")
        await conn.commit()
        await conn.execute("DELETE FROM banktransacties WHERE id = 1")
        await conn.commit()
        cur = await conn.execute("SELECT bank_tx_id FROM uitgaven")
        assert (await cur.fetchone())[0] is None
```

- [ ] **Step 1.2: Run the tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kosten_migrations.py -v
```
Expected: 5 FAIL with "no such column: bank_tx_id" / "no such column: genegeerd".

- [ ] **Step 1.3: Add migration #26 to the MIGRATIONS list**

Append to `MIGRATIONS` list in `database.py` (after entry 25):

```python
    (26, "add_kosten_rework_columns", [
        "ALTER TABLE uitgaven ADD COLUMN bank_tx_id INTEGER "
        "REFERENCES banktransacties(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS idx_uitgaven_bank_tx "
        "ON uitgaven(bank_tx_id)",
        "ALTER TABLE banktransacties ADD COLUMN genegeerd INTEGER "
        "NOT NULL DEFAULT 0 CHECK (genegeerd IN (0, 1))",
        "CREATE INDEX IF NOT EXISTS idx_bank_genegeerd "
        "ON banktransacties(genegeerd)",
    ]),
```

- [ ] **Step 1.4: Run the tests to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kosten_migrations.py -v
```
Expected: 5 PASS.

- [ ] **Step 1.5: Run the full suite to confirm nothing regressed**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```
Expected: all PASS, 5 new tests added.

- [ ] **Step 1.6: Commit**

```bash
git add database.py tests/test_kosten_migrations.py
git commit -m "$(cat <<'EOF'
feat(kosten): migration 26 — bank_tx_id + genegeerd columns

Additive schema change: uitgaven.bank_tx_id (FK to banktransacties,
ON DELETE SET NULL) and banktransacties.genegeerd (bool flag).
Two new indexes. No data migration needed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Pure helpers — `components/kosten_helpers.py`

**Files:**
- Create: `components/kosten_helpers.py`
- Create: `tests/test_kosten_helpers.py`

- [ ] **Step 2.1: Write the failing tests**

```python
# tests/test_kosten_helpers.py
"""Pure helpers for the kosten page — no DB."""
from components.kosten_helpers import (
    derive_status, match_tokens, tegenpartij_color, initials,
)


def test_derive_status_hidden_when_genegeerd():
    row = {"id_bank": 1, "genegeerd": 1, "id_uitgave": None,
           "categorie": "", "pdf_pad": ""}
    assert derive_status(row) == "hidden"


def test_derive_status_ongecat_when_no_uitgave():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": None,
           "categorie": "", "pdf_pad": ""}
    assert derive_status(row) == "ongecategoriseerd"


def test_derive_status_ongecat_when_empty_categorie():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "", "pdf_pad": ""}
    assert derive_status(row) == "ongecategoriseerd"


def test_derive_status_ontbreekt_when_no_pdf():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "Kantoor", "pdf_pad": ""}
    assert derive_status(row) == "ontbreekt"


def test_derive_status_compleet():
    row = {"id_bank": 1, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "Kantoor", "pdf_pad": "/tmp/x.pdf"}
    assert derive_status(row) == "compleet"


def test_derive_status_manual_compleet():
    """Manual uitgave: id_bank None, id_uitgave set."""
    row = {"id_bank": None, "genegeerd": 0, "id_uitgave": 5,
           "categorie": "Kantoor", "pdf_pad": "/tmp/x.pdf"}
    assert derive_status(row) == "compleet"


def test_match_tokens_hit_simple():
    assert match_tokens("KPN B.V.", "KPN_maart2026") >= 1


def test_match_tokens_hit_case_and_punct():
    assert match_tokens(
        "Boekhouder Verzekering",
        "boekhouder-verzekering_q2") >= 1


def test_match_tokens_miss():
    assert match_tokens("Shell", "Apple") == 0


def test_match_tokens_ignores_short_tokens():
    """Tokens < 4 chars don't count."""
    # 'BV' is 2 chars, 'NL' is 2 chars — both ignored.
    assert match_tokens("BV NL", "BV NL other") == 0


def test_match_tokens_multi_hit():
    assert match_tokens(
        "Microsoft Ireland",
        "microsoft365-ireland_2026") >= 1


def test_tegenpartij_color_deterministic():
    assert tegenpartij_color("KPN B.V.") == tegenpartij_color("KPN B.V.")
    assert tegenpartij_color("A") != tegenpartij_color("B")


def test_tegenpartij_color_is_hsl():
    color = tegenpartij_color("KPN B.V.")
    assert color.startswith("hsl(")


def test_initials_two_word():
    assert initials("Test Berg") == "RB"


def test_initials_one_word():
    assert initials("KPN") == "KP"


def test_initials_many_words():
    assert initials("SPH Pensioenfonds Nederland") == "SP"


def test_initials_empty():
    assert initials("") == "?"


def test_initials_strips_punct():
    assert initials("Boekhouder Verzekering") == "VS"
```

- [ ] **Step 2.2: Run to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kosten_helpers.py -v
```
Expected: FAIL with `ModuleNotFoundError: components.kosten_helpers`.

- [ ] **Step 2.3: Implement the module**

```python
# components/kosten_helpers.py
"""Pure helpers for the Kosten page — no DB, no NiceGUI imports.

Keep this file IO-free so it stays trivially unit-testable.
"""
import re
from pathlib import Path


def derive_status(row: dict) -> str:
    """Return one of: 'hidden' | 'ongecategoriseerd' | 'ontbreekt' | 'compleet'.

    Sequential and mutually exclusive. See spec §5.
    """
    if row.get("id_bank") is not None and row.get("genegeerd"):
        return "hidden"
    if row.get("id_uitgave") is None:
        # bank-tx without a linked uitgave (can't happen for manual rows since
        # id_uitgave is always set there; the None case is bank-only)
        return "ongecategoriseerd"
    if not (row.get("categorie") or "").strip():
        return "ongecategoriseerd"
    if not (row.get("pdf_pad") or "").strip():
        return "ontbreekt"
    return "compleet"


_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _normalize_tokens(s: str) -> set[str]:
    """Lowercase tokens of length >= 4, alphanumeric only."""
    return {m.group(0).lower() for m in _WORD_RE.finditer(s or "")
            if len(m.group(0)) >= 4}


def match_tokens(tegenpartij: str, filename_stem: str) -> int:
    """Return the number of shared tokens (len >= 4) between the two strings.

    Case-insensitive. Punctuation, whitespace, underscores, hyphens are split.
    """
    a = _normalize_tokens(tegenpartij)
    b = _normalize_tokens(Path(filename_stem).stem)
    return len(a & b)


def tegenpartij_color(s: str) -> str:
    """Deterministic HSL color from a string (mirrors the HTML mockup helper)."""
    h = 0
    for c in s or "":
        h = (h * 31 + ord(c)) % 360
    return f"hsl({h} 55% 48%)"


def initials(s: str) -> str:
    """First letters of the first two alphanumeric tokens.

    Returns '?' for empty input. Uppercases.
    """
    tokens = _WORD_RE.findall(s or "")
    if not tokens:
        return "?"
    picked = tokens[:2]
    return "".join(t[0] for t in picked).upper()
```

- [ ] **Step 2.4: Run to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kosten_helpers.py -v
```
Expected: all PASS.

- [ ] **Step 2.5: Commit**

```bash
git add components/kosten_helpers.py tests/test_kosten_helpers.py
git commit -m "$(cat <<'EOF'
feat(kosten): pure helpers — status, token-match, color, initials

Isolated in components/kosten_helpers.py so no DB/NiceGUI imports.
Exhaustive status-derivation cases covered; token matching ignores
short tokens (<4 chars) to avoid BV/NL/etc. noise.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `ensure_uitgave_for_banktx` — idempotent lazy-create

**Files:**
- Modify: `database.py` (add function near other uitgaven helpers)
- Create: `tests/test_ensure_uitgave.py`

- [ ] **Step 3.1: Write the failing tests**

```python
# tests/test_ensure_uitgave.py
"""ensure_uitgave_for_banktx — idempotent lazy-create, year-locked."""
import aiosqlite
import pytest
from database import (
    ensure_uitgave_for_banktx, get_uitgaven,
    update_jaarafsluiting_status, YearLockedError,
)


async def _seed_banktx(db_path, id_: int, datum: str, bedrag: float,
                        tegenpartij: str = "KPN B.V.",
                        omschrijving: str = "abo") -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij, omschrijving) "
            "VALUES (?, ?, ?, ?, ?)",
            (id_, datum, bedrag, tegenpartij, omschrijving))
        await conn.commit()


async def _seed_fiscale_params(db_path, jaar: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar) VALUES (?)", (jaar,))
        await conn.commit()


@pytest.mark.asyncio
async def test_ensure_creates_new_when_absent(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    uitgave_id = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    assert uitgave_id > 0
    uitgaven = await get_uitgaven(db, jaar=2026)
    u = next(u for u in uitgaven if u.id == uitgave_id)
    assert u.datum == "2026-04-01"
    assert u.bedrag == 120.87  # ABS of bank_tx.bedrag
    assert u.omschrijving == "KPN B.V."  # defaults to tegenpartij
    assert u.categorie == ""  # caller fills in


@pytest.mark.asyncio
async def test_ensure_is_idempotent(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    first = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    second = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    assert first == second


@pytest.mark.asyncio
async def test_ensure_accepts_overrides(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    uid = await ensure_uitgave_for_banktx(
        db, bank_tx_id=1, categorie="Telefoon/KPN")
    uitgaven = await get_uitgaven(db, jaar=2026)
    u = next(u for u in uitgaven if u.id == uid)
    assert u.categorie == "Telefoon/KPN"


@pytest.mark.asyncio
async def test_ensure_falls_back_to_omschrijving_when_tegenpartij_empty(db):
    await _seed_banktx(db, 1, "2026-04-01", -50.00,
                        tegenpartij="", omschrijving="handmatige storting")
    uid = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    u = next(u for u in (await get_uitgaven(db, jaar=2026)) if u.id == uid)
    assert u.omschrijving == "handmatige storting"


@pytest.mark.asyncio
async def test_ensure_year_locked_raises(db):
    await _seed_fiscale_params(db, 2024)
    await update_jaarafsluiting_status(db, 2024, "definitief")
    await _seed_banktx(db, 1, "2024-06-01", -100.00)
    with pytest.raises(YearLockedError):
        await ensure_uitgave_for_banktx(db, bank_tx_id=1)


@pytest.mark.asyncio
async def test_ensure_raises_for_unknown_bank_tx(db):
    with pytest.raises(ValueError):
        await ensure_uitgave_for_banktx(db, bank_tx_id=999)
```

- [ ] **Step 3.2: Run to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_ensure_uitgave.py -v
```
Expected: FAIL with `ImportError: cannot import name 'ensure_uitgave_for_banktx'`.

- [ ] **Step 3.3: Implement the function**

Add near the other `uitgave` helpers in `database.py` (search for `async def add_uitgave` for the right location; place `ensure_uitgave_for_banktx` directly after it):

```python
async def ensure_uitgave_for_banktx(
    db_path: Path,
    bank_tx_id: int,
    **overrides,
) -> int:
    """Return the uitgave.id linked to this bank_tx; create if absent.

    Idempotent. Enforces uitgave.bedrag = ABS(bank_tx.bedrag) at creation.
    Year-locked against bank_tx.datum.
    """
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT datum, bedrag, tegenpartij, omschrijving "
            "FROM banktransacties WHERE id = ?", (bank_tx_id,))
        bt = await cur.fetchone()
        if bt is None:
            raise ValueError(f"banktransactie {bank_tx_id} not found")

        # Already linked?
        cur = await conn.execute(
            "SELECT id FROM uitgaven WHERE bank_tx_id = ?", (bank_tx_id,))
        existing = await cur.fetchone()
        if existing is not None:
            return existing[0]

    # Not linked — create. Year-lock against the bank tx datum.
    await assert_year_writable(db_path, bt["datum"])

    kwargs = {
        "datum": bt["datum"],
        "bedrag": abs(bt["bedrag"]),
        "omschrijving": (bt["tegenpartij"] or "").strip()
                        or (bt["omschrijving"] or "").strip() or "(bank tx)",
        "categorie": "",
    }
    kwargs.update(overrides)

    # Use add_uitgave so existing validation/year-lock stays DRY.
    # add_uitgave does its own year-lock check, which is redundant but safe.
    uitgave_id = await add_uitgave(db_path, **kwargs)

    # Link it.
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
            (bank_tx_id, uitgave_id))
        await conn.commit()

    return uitgave_id
```

- [ ] **Step 3.4: Run to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_ensure_uitgave.py -v
```
Expected: all PASS.

- [ ] **Step 3.5: Full suite check**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```
Expected: all PASS.

- [ ] **Step 3.6: Commit**

```bash
git add database.py tests/test_ensure_uitgave.py
git commit -m "$(cat <<'EOF'
feat(kosten): ensure_uitgave_for_banktx — idempotent lazy-create

Returns existing uitgave.id when already linked, else creates one with
datum/bedrag=ABS/omschrijving=tegenpartij defaults and links via the
new bank_tx_id column. Year-locked.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `mark_banktx_genegeerd` — year-locked toggle

**Files:**
- Modify: `database.py`
- Create: `tests/test_bank_genegeerd.py`

- [ ] **Step 4.1: Write the failing tests**

```python
# tests/test_bank_genegeerd.py
"""mark_banktx_genegeerd — toggle bank tx visibility in Kosten."""
import aiosqlite
import pytest
from database import (
    mark_banktx_genegeerd, update_jaarafsluiting_status, YearLockedError,
)


async def _seed_banktx(db_path, id_, datum, bedrag=-50.0):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag) VALUES (?, ?, ?)",
            (id_, datum, bedrag))
        await conn.commit()


async def _get_genegeerd(db_path, id_):
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT genegeerd FROM banktransacties WHERE id = ?", (id_,))
        return (await cur.fetchone())[0]


@pytest.mark.asyncio
async def test_mark_genegeerd_sets_flag(db):
    await _seed_banktx(db, 1, "2026-04-01")
    await mark_banktx_genegeerd(db, 1, genegeerd=1)
    assert await _get_genegeerd(db, 1) == 1


@pytest.mark.asyncio
async def test_mark_genegeerd_can_unset(db):
    await _seed_banktx(db, 1, "2026-04-01")
    await mark_banktx_genegeerd(db, 1, genegeerd=1)
    await mark_banktx_genegeerd(db, 1, genegeerd=0)
    assert await _get_genegeerd(db, 1) == 0


@pytest.mark.asyncio
async def test_mark_genegeerd_year_locked(db):
    async with aiosqlite.connect(db) as conn:
        await conn.execute("INSERT INTO fiscale_params (jaar) VALUES (2024)")
        await conn.commit()
    await update_jaarafsluiting_status(db, 2024, "definitief")
    await _seed_banktx(db, 1, "2024-06-01")
    with pytest.raises(YearLockedError):
        await mark_banktx_genegeerd(db, 1, genegeerd=1)


@pytest.mark.asyncio
async def test_mark_genegeerd_raises_for_unknown_id(db):
    with pytest.raises(ValueError):
        await mark_banktx_genegeerd(db, 999, genegeerd=1)
```

- [ ] **Step 4.2: Run to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_bank_genegeerd.py -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 4.3: Implement the function**

Add in `database.py` near the other banktransacties helpers (search for `update_banktransactie`):

```python
async def mark_banktx_genegeerd(
    db_path: Path,
    bank_tx_id: int,
    genegeerd: int = 1,
) -> None:
    """Set banktransacties.genegeerd flag. Year-locked against the tx datum."""
    if genegeerd not in (0, 1):
        raise ValueError("genegeerd must be 0 or 1")
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum FROM banktransacties WHERE id = ?", (bank_tx_id,))
        row = await cur.fetchone()
        if row is None:
            raise ValueError(f"banktransactie {bank_tx_id} not found")
        datum = row[0]

    await assert_year_writable(db_path, datum)

    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "UPDATE banktransacties SET genegeerd = ? WHERE id = ?",
            (genegeerd, bank_tx_id))
        await conn.commit()
```

- [ ] **Step 4.4: Run to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_bank_genegeerd.py -v
```
Expected: all PASS.

- [ ] **Step 4.5: Commit**

```bash
git add database.py tests/test_bank_genegeerd.py
git commit -m "$(cat <<'EOF'
feat(kosten): mark_banktx_genegeerd — year-locked toggle

Sets banktransacties.genegeerd so the bank tx is hidden from the
Kosten reconciliation view (for private transfers, ATM, etc.).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `find_pdf_matches_for_banktx` — tegenpartij token matching

**Files:**
- Modify: `database.py` (or `import_/expense_utils.py` — place where `scan_archive` already lives)
- Create: `tests/test_kosten_matching.py`

**Decision:** place `find_pdf_matches_for_banktx` in `database.py` alongside other `banktransacties` helpers so it's discoverable via `from database import …`. It will call `scan_archive` from `import_.expense_utils`.

- [ ] **Step 5.1: Write the failing tests**

```python
# tests/test_kosten_matching.py
"""find_pdf_matches_for_banktx — tegenpartij token + (optional) bedrag match."""
import aiosqlite
import pytest
from database import find_pdf_matches_for_banktx


async def _seed_banktx(db_path, id_, datum, bedrag, tegenpartij):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij) "
            "VALUES (?, ?, ?, ?)",
            (id_, datum, bedrag, tegenpartij))
        await conn.commit()


def _mock_archive(tmp_path, files: list[tuple[str, str]]) -> None:
    """files: list of (folder, filename). Creates empty PDFs under an
    archive root that mirrors the FOLDER_TO_CATEGORIE layout.
    """
    import os
    os.environ["ARCHIVE_BASE"] = str(tmp_path)
    for folder, fname in files:
        d = tmp_path / "Boekhouding_Waarneming" / "2026" / "Uitgaven" / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_bytes(b"%PDF-1.4\n")


@pytest.mark.asyncio
async def test_match_returns_high_confidence_tegenpartij_hit(db, tmp_path,
                                                              monkeypatch):
    from components import archive_paths
    monkeypatch.setattr(archive_paths, "ARCHIVE_BASE", tmp_path)
    _mock_archive(tmp_path, [("KPN", "2026-04-01_KPN_abo.pdf")])
    await _seed_banktx(db, 1, "2026-04-01", -120.87, "KPN B.V.")
    matches = await find_pdf_matches_for_banktx(db, 1, jaar=2026)
    assert len(matches) >= 1
    assert matches[0].filename == "2026-04-01_KPN_abo.pdf"
    assert matches[0].categorie == "Telefoon/KPN"


@pytest.mark.asyncio
async def test_match_returns_empty_when_no_overlap(db, tmp_path, monkeypatch):
    from components import archive_paths
    monkeypatch.setattr(archive_paths, "ARCHIVE_BASE", tmp_path)
    _mock_archive(tmp_path, [("KPN", "2026-04-01_KPN_abo.pdf")])
    await _seed_banktx(db, 1, "2026-04-01", -50.00, "Shell Nederland")
    matches = await find_pdf_matches_for_banktx(db, 1, jaar=2026)
    assert matches == []


@pytest.mark.asyncio
async def test_match_ignores_unknown_bank_tx(db):
    with pytest.raises(ValueError):
        await find_pdf_matches_for_banktx(db, 999, jaar=2026)


@pytest.mark.asyncio
async def test_match_multiple_returns_sorted(db, tmp_path, monkeypatch):
    from components import archive_paths
    monkeypatch.setattr(archive_paths, "ARCHIVE_BASE", tmp_path)
    _mock_archive(tmp_path, [
        ("KPN", "2026-04-01_KPN_abo.pdf"),
        ("KPN", "2026-03-01_kpn_internet.pdf"),
    ])
    await _seed_banktx(db, 1, "2026-04-01", -120.87, "KPN B.V.")
    matches = await find_pdf_matches_for_banktx(db, 1, jaar=2026)
    assert len(matches) == 2
```

- [ ] **Step 5.2: Run to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kosten_matching.py -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 5.3: Implement the function**

Add in `database.py`:

```python
from dataclasses import dataclass
from pathlib import Path as _Path

@dataclass
class PdfMatch:
    path: _Path
    filename: str
    categorie: str
    score: int  # higher = better; for v1: tegenpartij token count
    has_bedrag_match: bool = False  # reserved for v1.1


async def find_pdf_matches_for_banktx(
    db_path: Path, bank_tx_id: int, jaar: int,
) -> list[PdfMatch]:
    """Return archive PDFs that plausibly match this bank transaction.

    v1: matches by tegenpartij token overlap (len >= 4 chars).
    Empty list when nothing matches.
    """
    from components.kosten_helpers import match_tokens
    from import_.expense_utils import scan_archive

    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum, tegenpartij FROM banktransacties WHERE id = ?",
            (bank_tx_id,))
        row = await cur.fetchone()
        if row is None:
            raise ValueError(f"banktransactie {bank_tx_id} not found")
        tegenpartij = row[1] or ""

    items = scan_archive(jaar, set())  # existing_filenames empty — we re-rank
    matches: list[PdfMatch] = []
    for it in items:
        if it.get("already_imported"):
            continue
        stem = _Path(it["filename"]).stem
        score = match_tokens(tegenpartij, stem)
        if score == 0:
            continue
        matches.append(PdfMatch(
            path=_Path(it["path"]),
            filename=it["filename"],
            categorie=it["categorie"],
            score=score,
        ))
    matches.sort(key=lambda m: (m.has_bedrag_match, m.score), reverse=True)
    return matches
```

- [ ] **Step 5.4: Run to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kosten_matching.py -v
```
Expected: all PASS.

- [ ] **Step 5.5: Commit**

```bash
git add database.py tests/test_kosten_matching.py
git commit -m "$(cat <<'EOF'
feat(kosten): find_pdf_matches_for_banktx — tegenpartij token matching

Returns ranked PdfMatch list via scan_archive + match_tokens. Bedrag
matching is deferred to v1.1 (has_bedrag_match stays False for now).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `get_kosten_view` — the unified list

**Files:**
- Modify: `database.py`
- Create: `tests/test_kosten_view.py`

- [ ] **Step 6.1: Write the failing tests**

```python
# tests/test_kosten_view.py
"""get_kosten_view — unified bank_tx + manual uitgaven list."""
import aiosqlite
import pytest
from database import get_kosten_view, ensure_uitgave_for_banktx


async def _seed_banktx(db_path, id_, datum, bedrag, tp="KPN B.V.",
                        omschr="abo", genegeerd=0):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij, omschrijving, genegeerd) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id_, datum, bedrag, tp, omschr, genegeerd))
        await conn.commit()


async def _seed_uitgave(db_path, datum, bedrag, categorie="Kantoor",
                        omschrijving="x", pdf_pad=""):
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag, "
            "pdf_pad) VALUES (?, ?, ?, ?, ?)",
            (datum, categorie, omschrijving, bedrag, pdf_pad))
        await conn.commit()
        return cur.lastrowid


@pytest.mark.asyncio
async def test_view_bank_only_row_has_ongecategoriseerd_status(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    rows = await get_kosten_view(db, jaar=2026)
    assert len(rows) == 1
    assert rows[0].status == "ongecategoriseerd"
    assert rows[0].bedrag == 120.87  # ABS
    assert rows[0].tegenpartij == "KPN B.V."


@pytest.mark.asyncio
async def test_view_manual_uitgave_appears(db):
    await _seed_uitgave(db, "2026-04-05", 10.00,
                        categorie="Kantoor", pdf_pad="/tmp/x.pdf")
    rows = await get_kosten_view(db, jaar=2026)
    assert len(rows) == 1
    assert rows[0].is_manual is True
    assert rows[0].status == "compleet"


@pytest.mark.asyncio
async def test_view_linked_uitgave_shows_once(db):
    """bank_tx linked to uitgave: one row only (bank side dominates)."""
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    await ensure_uitgave_for_banktx(db, 1, categorie="Telefoon/KPN")
    rows = await get_kosten_view(db, jaar=2026)
    assert len(rows) == 1
    assert rows[0].status == "ontbreekt"  # no pdf yet
    assert rows[0].is_manual is False


@pytest.mark.asyncio
async def test_view_genegeerd_hidden(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87, genegeerd=1)
    rows = await get_kosten_view(db, jaar=2026)
    assert rows == []


@pytest.mark.asyncio
async def test_view_date_range_filter(db):
    await _seed_banktx(db, 1, "2025-12-31", -100.00)
    await _seed_banktx(db, 2, "2026-01-01", -200.00)
    await _seed_banktx(db, 3, "2026-12-31", -300.00)
    await _seed_banktx(db, 4, "2027-01-01", -400.00)
    rows = await get_kosten_view(db, jaar=2026)
    bedragen = sorted(r.bedrag for r in rows)
    assert bedragen == [200.00, 300.00]


@pytest.mark.asyncio
async def test_view_excludes_credits(db):
    await _seed_banktx(db, 1, "2026-04-01", 500.00)  # positive = credit
    rows = await get_kosten_view(db, jaar=2026)
    assert rows == []


@pytest.mark.asyncio
async def test_view_status_filter(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    await _seed_uitgave(db, "2026-04-05", 10.00, pdf_pad="/x.pdf")
    rows = await get_kosten_view(db, jaar=2026, status="compleet")
    assert len(rows) == 1
    assert rows[0].is_manual is True


@pytest.mark.asyncio
async def test_view_categorie_filter(db):
    await _seed_uitgave(db, "2026-04-01", 10.00, categorie="Kantoor",
                        pdf_pad="/x.pdf")
    await _seed_uitgave(db, "2026-04-02", 20.00, categorie="Representatie",
                        pdf_pad="/y.pdf")
    rows = await get_kosten_view(db, jaar=2026, categorie="Kantoor")
    assert len(rows) == 1
    assert rows[0].categorie == "Kantoor"


@pytest.mark.asyncio
async def test_view_search_substring(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87, tp="KPN B.V.")
    await _seed_banktx(db, 2, "2026-04-02", -50.00, tp="Shell")
    rows = await get_kosten_view(db, jaar=2026, search="kpn")
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_view_ordered_by_datum_desc(db):
    await _seed_banktx(db, 1, "2026-03-01", -10.00)
    await _seed_banktx(db, 2, "2026-04-01", -20.00)
    rows = await get_kosten_view(db, jaar=2026)
    assert [r.datum for r in rows] == ["2026-04-01", "2026-03-01"]
```

- [ ] **Step 6.2: Run to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kosten_view.py -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 6.3: Implement the function**

Add in `database.py`:

```python
from dataclasses import dataclass, field

@dataclass
class KostenRow:
    id_bank: int | None
    id_uitgave: int | None
    datum: str
    bedrag: float
    tegenpartij: str
    omschrijving: str
    iban: str
    categorie: str
    pdf_pad: str
    is_investering: bool
    zakelijk_pct: float | None
    status: str
    is_manual: bool
    genegeerd: int = 0


async def get_kosten_view(
    db_path: Path,
    jaar: int,
    status: str | None = None,
    categorie: str | None = None,
    search: str | None = None,
) -> list[KostenRow]:
    """Unified reconciliation list: bank-tx debits + manual uitgaven.

    Date filter uses the range form so idx_*_datum indexes are hit.
    Status / categorie / search are Python-side post-filters.
    """
    from components.kosten_helpers import derive_status

    jaar_start = f"{jaar:04d}-01-01"
    jaar_end = f"{jaar + 1:04d}-01-01"

    sql = """
    SELECT 'bank' AS source,
           b.id AS id_bank,
           u.id AS id_uitgave,
           b.datum AS datum,
           ABS(b.bedrag) AS bedrag,
           COALESCE(b.tegenpartij, '') AS tegenpartij,
           COALESCE(NULLIF(u.omschrijving, ''), b.omschrijving, '')
             AS omschrijving,
           COALESCE(b.tegenrekening, '') AS iban,
           COALESCE(u.categorie, '') AS categorie,
           COALESCE(u.pdf_pad, '') AS pdf_pad,
           COALESCE(u.is_investering, 0) AS is_investering,
           u.zakelijk_pct AS zakelijk_pct,
           b.genegeerd AS genegeerd
    FROM banktransacties b
    LEFT JOIN uitgaven u ON u.bank_tx_id = b.id
    WHERE b.bedrag < 0
      AND b.genegeerd = 0
      AND b.datum >= ? AND b.datum < ?

    UNION ALL

    SELECT 'manual' AS source,
           NULL AS id_bank,
           u.id AS id_uitgave,
           u.datum AS datum,
           u.bedrag AS bedrag,
           '' AS tegenpartij,
           u.omschrijving AS omschrijving,
           '' AS iban,
           u.categorie AS categorie,
           COALESCE(u.pdf_pad, '') AS pdf_pad,
           u.is_investering AS is_investering,
           u.zakelijk_pct AS zakelijk_pct,
           0 AS genegeerd
    FROM uitgaven u
    WHERE u.bank_tx_id IS NULL
      AND u.datum >= ? AND u.datum < ?

    ORDER BY datum DESC
    """
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(sql, (jaar_start, jaar_end, jaar_start, jaar_end))
        raw = await cur.fetchall()

    rows: list[KostenRow] = []
    for r in raw:
        row_dict = {
            "id_bank": r["id_bank"],
            "id_uitgave": r["id_uitgave"],
            "genegeerd": r["genegeerd"],
            "categorie": r["categorie"],
            "pdf_pad": r["pdf_pad"],
        }
        rows.append(KostenRow(
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
            status=derive_status(row_dict),
            is_manual=(r["source"] == "manual"),
            genegeerd=r["genegeerd"],
        ))

    # Post-filters
    if status is not None:
        rows = [r for r in rows if r.status == status]
    if categorie is not None and categorie != "":
        rows = [r for r in rows if r.categorie == categorie]
    if search:
        q = search.lower()
        rows = [r for r in rows if
                q in r.tegenpartij.lower()
                or q in r.omschrijving.lower()
                or q in f"{r.bedrag:.2f}"]
    return rows
```

- [ ] **Step 6.4: Run to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kosten_view.py -v
```
Expected: all PASS.

- [ ] **Step 6.5: Full suite check + commit**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
git add database.py tests/test_kosten_view.py
git commit -m "$(cat <<'EOF'
feat(kosten): get_kosten_view — unified bank-tx + manual uitgaven

UNION ALL query with ABS bedrag normalization, genegeerd filter, and
range-form date filter (hits idx_*_datum). Python-side post-filters
for status/categorie/search. Derives status via kosten_helpers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `get_kpi_kosten` — aggregates

**Files:**
- Modify: `database.py`
- Create: `tests/test_kpi_kosten.py`

- [ ] **Step 7.1: Write the failing tests**

```python
# tests/test_kpi_kosten.py
"""get_kpi_kosten — KPI strip aggregates."""
import aiosqlite
import pytest
from database import get_kpi_kosten


async def _seed_banktx(db_path, id_, datum, bedrag):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij) "
            "VALUES (?, ?, ?, 'X')", (id_, datum, bedrag))
        await conn.commit()


async def _seed_uitgave(db_path, datum, bedrag, categorie="Kantoor",
                        is_investering=0, zakelijk_pct=100,
                        aanschaf_bedrag=None, levensduur=None, pdf_pad=""):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO uitgaven "
            "(datum, categorie, omschrijving, bedrag, pdf_pad, "
            " is_investering, zakelijk_pct, aanschaf_bedrag, levensduur_jaren) "
            "VALUES (?, ?, 'x', ?, ?, ?, ?, ?, ?)",
            (datum, categorie, bedrag, pdf_pad,
             is_investering, zakelijk_pct, aanschaf_bedrag, levensduur))
        await conn.commit()


@pytest.mark.asyncio
async def test_kpi_totaal_sums_abs(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    await _seed_uitgave(db, "2026-04-05", 10.00)
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.totaal == pytest.approx(130.87)


@pytest.mark.asyncio
async def test_kpi_monthly_totals_length_12(db):
    kpi = await get_kpi_kosten(db, 2026)
    assert len(kpi.monthly_totals) == 12
    assert sum(kpi.monthly_totals) == 0.0


@pytest.mark.asyncio
async def test_kpi_monthly_totals_by_month(db):
    await _seed_banktx(db, 1, "2026-01-15", -50.00)
    await _seed_banktx(db, 2, "2026-03-20", -30.00)
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.monthly_totals[0] == pytest.approx(50.00)
    assert kpi.monthly_totals[2] == pytest.approx(30.00)
    assert kpi.monthly_totals[6] == 0.0


@pytest.mark.asyncio
async def test_kpi_ontbreekt_counts_bank_only_rows(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.ontbreekt_count == 1
    assert kpi.ontbreekt_bedrag == pytest.approx(120.87)


@pytest.mark.asyncio
async def test_kpi_investeringen(db):
    await _seed_uitgave(db, "2026-03-01", 1200.00,
                        is_investering=1, zakelijk_pct=100,
                        aanschaf_bedrag=1200.00, levensduur=5)
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.investeringen_count == 1
    assert kpi.investeringen_bedrag == pytest.approx(1200.00)


@pytest.mark.asyncio
async def test_kpi_afschrijvingen_nonzero_with_investment(db):
    await _seed_uitgave(db, "2026-01-01", 1200.00,
                        is_investering=1, zakelijk_pct=100,
                        aanschaf_bedrag=1200.00, levensduur=5)
    kpi = await get_kpi_kosten(db, 2026)
    # Aanschaf 1200 * (1-0.10) / 5 = 216 over full year (12 months)
    assert kpi.afschrijvingen_jaar == pytest.approx(216.0, rel=0.02)


@pytest.mark.asyncio
async def test_kpi_excludes_genegeerd(db):
    await _seed_banktx(db, 1, "2026-04-01", -100.00)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "UPDATE banktransacties SET genegeerd = 1 WHERE id = 1")
        await conn.commit()
    kpi = await get_kpi_kosten(db, 2026)
    assert kpi.totaal == 0.0
    assert kpi.ontbreekt_count == 0
```

- [ ] **Step 7.2: Run to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kpi_kosten.py -v
```
Expected: FAIL with `ImportError`.

- [ ] **Step 7.3: Implement the function**

Add in `database.py`:

```python
@dataclass
class KpiKosten:
    totaal: float
    ontbreekt_count: int
    ontbreekt_bedrag: float
    afschrijvingen_jaar: float
    investeringen_count: int
    investeringen_bedrag: float
    monthly_totals: list[float]


async def get_kpi_kosten(db_path: Path, jaar: int) -> KpiKosten:
    """Single-pass KPI strip data. See spec §8."""
    from fiscal.afschrijvingen import bereken_afschrijving

    rows = await get_kosten_view(db_path, jaar=jaar)

    totaal = sum(r.bedrag for r in rows)
    monthly = [0.0] * 12
    for r in rows:
        try:
            m = int(r.datum[5:7])
            if 1 <= m <= 12:
                monthly[m - 1] += r.bedrag
        except (ValueError, IndexError):
            continue

    ontbreekt_rows = [r for r in rows if r.status == "ontbreekt"
                       or r.status == "ongecategoriseerd"]
    ontbreekt_count = len(ontbreekt_rows)
    ontbreekt_bedrag = sum(r.bedrag for r in ontbreekt_rows)

    # Investeringen + afschrijvingen: pull from uitgaven directly
    investeringen_count = 0
    investeringen_bedrag = 0.0
    afschrijvingen_jaar = 0.0
    overrides_batch = await get_afschrijving_overrides_batch(db_path, [])
    # cheap — will fetch per-row below if needed

    from database import get_investeringen_voor_afschrijving  # same module
    investeringen = await get_investeringen_voor_afschrijving(
        db_path, tot_jaar=jaar)
    inv_ids = [u.id for u in investeringen]
    overrides_map = await get_afschrijving_overrides_batch(db_path, inv_ids) \
        if inv_ids else {}

    for u in investeringen:
        zp = (u.zakelijk_pct if u.zakelijk_pct is not None else 100) / 100.0
        aanschaf = (u.aanschaf_bedrag or u.bedrag) * zp
        # Count investment if it belongs to THIS jaar
        if u.datum[:4] == f"{jaar:04d}":
            investeringen_count += 1
            investeringen_bedrag += aanschaf
        result = bereken_afschrijving(
            aanschaf_bedrag=aanschaf,
            restwaarde_pct=u.restwaarde_pct or 10,
            levensduur=u.levensduur_jaren or 5,
            aanschaf_maand=int(u.datum[5:7]),
            aanschaf_jaar=int(u.datum[0:4]),
            bereken_jaar=jaar,
            overrides=overrides_map.get(u.id),
        )
        afschrijvingen_jaar += result["afschrijving"]

    return KpiKosten(
        totaal=totaal,
        ontbreekt_count=ontbreekt_count,
        ontbreekt_bedrag=ontbreekt_bedrag,
        afschrijvingen_jaar=afschrijvingen_jaar,
        investeringen_count=investeringen_count,
        investeringen_bedrag=investeringen_bedrag,
        monthly_totals=monthly,
    )
```

- [ ] **Step 7.4: Run to verify they pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_kpi_kosten.py -v
```
Expected: all PASS.

- [ ] **Step 7.5: Full suite check + commit**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
git add database.py tests/test_kpi_kosten.py
git commit -m "$(cat <<'EOF'
feat(kosten): get_kpi_kosten — single-pass KPI aggregates

Uses get_kosten_view for tx-side numbers and reuses existing
bereken_afschrijving/get_investeringen_voor_afschrijving for the
investment side. 12-slot monthly_totals for the sparkline.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Lift activastaat → `pages/kosten_investeringen.py`

Mechanical refactor. Goal: extract the activastaat UI + `open_afschrijving_dialog` from the current `pages/kosten.py` into a separate module with an exported callable, **zero behavior change**.

**Files:**
- Create: `pages/kosten_investeringen.py`
- Modify: `pages/kosten.py` (import from new module)

- [ ] **Step 8.1: Create the new module**

```python
# pages/kosten_investeringen.py
"""Activastaat UI — lifted from pages/kosten.py.

Kept as a separate module so the main Kosten page body stays focused on
the bank-tx reconciliation view. Behavior is unchanged from the prior
inline implementation.
"""
from nicegui import ui

from components.utils import format_euro
from database import (
    DB_PATH,
    get_investeringen_voor_afschrijving,
    get_afschrijving_overrides,
    get_afschrijving_overrides_batch,
    set_afschrijving_override,
    delete_afschrijving_override,
    update_uitgave,
)
from fiscal.afschrijvingen import bereken_afschrijving


LEVENSDUUR_OPTIES = {3: "3 jaar", 4: "4 jaar", 5: "5 jaar"}


async def laad_activastaat(container, jaar: int, on_change) -> None:
    """Render the activastaat card into `container`. `on_change` is an async
    callable invoked after edits so the caller can refresh dependent UI.
    """
    container.clear()
    investeringen = await get_investeringen_voor_afschrijving(
        DB_PATH, tot_jaar=jaar)
    if not investeringen:
        with container:
            ui.label("Geen investeringen in dit jaar of daarvoor.") \
                .classes("text-grey")
        return

    all_overrides = await get_afschrijving_overrides_batch(
        DB_PATH, [u.id for u in investeringen])

    with container:
        ui.label(f"Activastaat per 31-12-{jaar}") \
            .classes("text-subtitle1 text-bold")
        activa_rows = []
        for u in investeringen:
            aanschaf = (u.aanschaf_bedrag or u.bedrag) * (
                (u.zakelijk_pct if u.zakelijk_pct is not None else 100) / 100)
            result = bereken_afschrijving(
                aanschaf_bedrag=aanschaf,
                restwaarde_pct=u.restwaarde_pct or 10,
                levensduur=u.levensduur_jaren or 5,
                aanschaf_maand=int(u.datum[5:7]),
                aanschaf_jaar=int(u.datum[0:4]),
                bereken_jaar=jaar,
                overrides=all_overrides.get(u.id),
            )
            activa_rows.append({
                "id": u.id,
                "omschrijving": u.omschrijving,
                "aanschaf": format_euro(aanschaf),
                "afschr_dit_jaar": format_euro(result["afschrijving"]),
                "boekwaarde": format_euro(result["boekwaarde"]),
                "has_override": result.get("has_override", False),
                "_aanschaf_bedrag": aanschaf,
                "_restwaarde_pct": u.restwaarde_pct or 10,
                "_levensduur": u.levensduur_jaren or 5,
                "_aanschaf_maand": int(u.datum[5:7]),
                "_aanschaf_jaar": int(u.datum[0:4]),
            })

        columns = [
            {"name": "omschrijving", "label": "Omschrijving",
             "field": "omschrijving", "align": "left"},
            {"name": "aanschaf", "label": "Aanschaf (zakelijk)",
             "field": "aanschaf", "align": "right"},
            {"name": "afschr_dit_jaar", "label": f"Afschr {jaar}",
             "field": "afschr_dit_jaar", "align": "right"},
            {"name": "boekwaarde", "label": "Boekwaarde",
             "field": "boekwaarde", "align": "right"},
            {"name": "acties", "label": "", "field": "acties",
             "align": "center"},
        ]
        activa_tbl = ui.table(columns=columns, rows=activa_rows,
                              row_key="id") \
            .classes("w-full").props("dense flat")
        activa_tbl.add_slot("body-cell-afschr_dit_jaar", '''
            <q-td :props="props">
                <span>{{ props.row.afschr_dit_jaar }}</span>
                <q-icon v-if="props.row.has_override" name="edit"
                        size="xs" color="primary" class="q-ml-xs" />
            </q-td>
        ''')
        activa_tbl.add_slot("body-cell-acties", '''
            <q-td :props="props">
                <q-btn flat dense icon="tune" size="sm"
                       color="primary" title="Afschrijving aanpassen"
                       @click="$parent.$emit('edit_afschr', props.row)" />
            </q-td>
        ''')
        activa_tbl.on(
            "edit_afschr",
            lambda e: open_afschrijving_dialog(e.args, jaar, on_change))


async def open_afschrijving_dialog(row: dict, huidige_jaar: int,
                                    on_change) -> None:
    """Open the per-year override dialog. `on_change` is called after save."""
    uitgave_id = row["id"]
    aanschaf = row["_aanschaf_bedrag"]
    restwaarde_pct = row["_restwaarde_pct"]
    levensduur_state = {"value": row["_levensduur"]}
    aanschaf_maand = row["_aanschaf_maand"]
    aanschaf_jaar = row["_aanschaf_jaar"]

    overrides = await get_afschrijving_overrides(DB_PATH, uitgave_id)

    with ui.dialog() as dialog, ui.card().classes("w-full max-w-xl q-pa-md"):
        ui.label(f'Afschrijving — {row["omschrijving"]}') \
            .classes("text-h6 q-mb-sm")

        with ui.row().classes("w-full items-end gap-4"):
            ui.label(f"Aanschaf: {format_euro(aanschaf)}") \
                .classes("text-caption text-grey")
            ui.label(f"Restwaarde: {restwaarde_pct:.0f}%") \
                .classes("text-caption text-grey")
            levensduur_input = ui.select(
                LEVENSDUUR_OPTIES, label="Levensduur",
                value=levensduur_state["value"]).classes("w-28")

        ui.separator().classes("q-my-sm")

        schedule_container = ui.column().classes("w-full gap-0")
        inputs_by_year: dict[int, ui.number | None] = {}

        def build_schedule():
            schedule_container.clear()
            inputs_by_year.clear()
            lv = levensduur_state["value"]
            laatste_jaar = aanschaf_jaar + lv
            toon_tot = max(laatste_jaar, huidige_jaar)

            with schedule_container:
                with ui.row().classes("w-full items-center gap-2 q-pb-xs") \
                        .style("border-bottom: 1px solid #E2E8F0"):
                    ui.label("Jaar") \
                        .classes("text-caption text-bold") \
                        .style("width: 60px")
                    ui.label("Berekend") \
                        .classes("text-caption text-bold text-right") \
                        .style("width: 90px")
                    ui.label("Handmatig") \
                        .classes("text-caption text-bold") \
                        .style("width: 120px")
                    ui.label("Boekwaarde") \
                        .classes("text-caption text-bold text-right") \
                        .style("width: 90px")

                for y in range(aanschaf_jaar, toon_tot + 1):
                    auto = bereken_afschrijving(
                        aanschaf_bedrag=aanschaf,
                        restwaarde_pct=restwaarde_pct,
                        levensduur=lv,
                        aanschaf_maand=aanschaf_maand,
                        aanschaf_jaar=aanschaf_jaar,
                        bereken_jaar=y)
                    auto_val = auto["afschrijving"]

                    result_with = bereken_afschrijving(
                        aanschaf_bedrag=aanschaf,
                        restwaarde_pct=restwaarde_pct,
                        levensduur=lv,
                        aanschaf_maand=aanschaf_maand,
                        aanschaf_jaar=aanschaf_jaar,
                        bereken_jaar=y,
                        overrides=overrides)

                    has_ov = y in overrides
                    override_val = overrides.get(y)
                    is_locked = y < huidige_jaar

                    with ui.row().classes(
                            "w-full items-center gap-2 q-py-xs") \
                            .style("border-bottom: 1px solid #F1F5F9"):
                        lbl = ui.label(str(y)).style("width: 60px")
                        if y == huidige_jaar:
                            lbl.classes("text-bold text-primary")
                        else:
                            lbl.classes("text-caption")

                        ui.label(format_euro(auto_val)) \
                            .classes("text-caption text-grey text-right") \
                            .style("width: 90px")

                        if is_locked:
                            if has_ov:
                                ui.label(format_euro(override_val)) \
                                    .classes("text-caption text-bold") \
                                    .style("width: 120px")
                            else:
                                ui.label("—") \
                                    .classes("text-caption text-grey") \
                                    .style("width: 120px")
                            inputs_by_year[y] = None
                        else:
                            inp = ui.number(
                                value=override_val if has_ov else None,
                                format="%.2f", min=0, step=0.01,
                                placeholder=f"{auto_val:.2f}") \
                                .classes("w-28") \
                                .props("dense outlined hide-bottom-space")
                            inputs_by_year[y] = inp

                        bw_label = ui.label(
                            format_euro(result_with["boekwaarde"])) \
                            .classes("text-caption text-right") \
                            .style("width: 90px")
                        if has_ov:
                            bw_label.classes("text-bold")

                if any(y < huidige_jaar
                       for y in range(aanschaf_jaar, toon_tot + 1)):
                    ui.label(
                        "Voorgaande jaren zijn vergrendeld "
                        "(reeds aangegeven).") \
                        .classes("text-caption text-grey q-mt-sm")

        def on_levensduur_change():
            levensduur_state["value"] = levensduur_input.value
            build_schedule()

        levensduur_input.on(
            "update:model-value", lambda: on_levensduur_change())
        build_schedule()

        with ui.row().classes("w-full justify-end gap-2 q-mt-md"):
            ui.button("Annuleren", on_click=dialog.close).props("flat")

            async def opslaan():
                new_lv = levensduur_state["value"]
                if new_lv != row["_levensduur"]:
                    await update_uitgave(
                        DB_PATH, uitgave_id=uitgave_id,
                        levensduur_jaren=new_lv)
                for y, inp in inputs_by_year.items():
                    if inp is None:
                        continue
                    val = inp.value
                    if val is not None and val >= 0:
                        await set_afschrijving_override(
                            DB_PATH, uitgave_id, y, val)
                        overrides[y] = val
                    elif y in overrides:
                        await delete_afschrijving_override(
                            DB_PATH, uitgave_id, y)
                        del overrides[y]
                dialog.close()
                ui.notify("Afschrijvingen opgeslagen", type="positive")
                await on_change()

            ui.button("Opslaan", icon="save",
                      on_click=opslaan).props("color=primary")

    dialog.open()
```

- [ ] **Step 8.2: Run the full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```
Expected: all PASS (the new module isn't imported yet; it's purely additive).

- [ ] **Step 8.3: Commit the lift**

```bash
git add pages/kosten_investeringen.py
git commit -m "$(cat <<'EOF'
refactor(kosten): lift activastaat into pages/kosten_investeringen.py

Pure move — functions extracted from pages/kosten.py with identical
behavior. Not imported yet; next task wires it into the new page.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Rewrite `pages/kosten.py` — scaffold (tabs + toolbar + empty table)

**Files:**
- Modify: `pages/kosten.py` (full rewrite of the page function body; keep existing `open_add_uitgave_dialog` for "Nieuwe uitgave" and `open_import_dialog` as-is)

- [ ] **Step 9.1: Replace the page body with the new scaffold**

Rewrite `pages/kosten.py` with:
- Import `ensure_uitgave_for_banktx`, `mark_banktx_genegeerd`,
  `get_kosten_view`, `get_kpi_kosten`, `find_pdf_matches_for_banktx`,
  `KostenRow`, `KpiKosten`, `PdfMatch` from `database`
- Import `laad_activastaat` from `pages.kosten_investeringen`
- Import helpers from `components.kosten_helpers`
- Keep current `open_add_uitgave_dialog`, `open_edit_dialog`,
  `confirm_delete`, `save_upload_for_uitgave`, `_copy_and_link_pdf`,
  `open_import_dialog`, `UITGAVEN_DIR` constant — these stay
- The new page body uses `ui.tabs` + `ui.tab_panels`

Write the new `kosten_page()`:

```python
@ui.page('/kosten')
async def kosten_page():
    create_layout('Kosten', '/kosten')
    huidig_jaar = date.today().year
    jaren = year_options()
    filter_jaar = {'value': huidig_jaar}
    filter_status = {'value': None}     # None = 'Alle'
    filter_categorie = {'value': None}  # None = 'Alle'
    filter_search = {'value': ''}
    view_mode = {'value': 'lijst'}      # 'lijst' or 'maand'

    fp = await get_fiscale_params(DB_PATH, jaar=huidig_jaar)
    repr_aftrek_pct = int(fp.repr_aftrek_pct) if fp else 80

    # UI refs
    kosten_table = {'ref': None}
    kpi_container = {'ref': None}
    inbox_container = {'ref': None}
    breakdown_container = {'ref': None}
    activa_container = {'ref': None}

    async def ververs_transacties():
        await _laad_kpi(kpi_container['ref'], filter_jaar['value'])
        await _laad_inbox(inbox_container['ref'], filter_jaar['value'],
                          ververs_transacties)
        await _laad_tabel(
            kosten_table['ref'], filter_jaar['value'],
            filter_status['value'], filter_categorie['value'],
            filter_search['value'], view_mode['value'])
        await _laad_breakdown(breakdown_container['ref'],
                              filter_jaar['value'])

    async def ververs_investeringen():
        await laad_activastaat(
            activa_container['ref'], filter_jaar['value'],
            ververs_transacties)

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):
        # Header
        with ui.row().classes('w-full items-center'):
            page_title('Kosten')
            ui.space()
            ui.button('Importeer', icon='folder_open',
                      on_click=lambda: open_import_dialog()) \
                .props('flat color=secondary dense')
            ui.button('Nieuwe uitgave', icon='add',
                      on_click=lambda: open_add_uitgave_dialog()) \
                .props('color=primary')

        with ui.tabs().classes('w-full') as tabs:
            tab_tx = ui.tab('Transacties', icon='list')
            tab_inv = ui.tab('Investeringen', icon='inventory_2')

        with ui.tab_panels(tabs, value=tab_tx).classes('w-full'):
            with ui.tab_panel(tab_tx):
                # filter bar (year select + status chips + view toggle)
                with ui.row().classes('w-full items-center gap-2'):
                    jaar_select = ui.select(
                        {j: str(j) for j in jaren},
                        label='Jaar', value=huidig_jaar).classes('w-28')

                    # status radio buttons
                    status_options = {
                        None: 'Alle',
                        'ongecategoriseerd': 'Ongecat.',
                        'ontbreekt': 'Ontbreekt',
                        'compleet': 'Compleet',
                    }
                    status_select = ui.select(
                        status_options, label='Status',
                        value=None).classes('w-40')

                    cat_opties = {'': 'Alle categorieën'}
                    cat_opties.update({c: c for c in CATEGORIEEN})
                    cat_select = ui.select(
                        cat_opties, label='Categorie',
                        value='').classes('w-48')

                    search_input = ui.input(
                        placeholder='Zoek…').classes('w-56') \
                        .props('clearable dense outlined')

                    ui.space()

                    view_toggle = ui.toggle(
                        {'lijst': 'Lijst', 'maand': 'Per maand'},
                        value='lijst').props('dense')

                async def on_filter_change():
                    filter_jaar['value'] = jaar_select.value
                    filter_status['value'] = status_select.value
                    filter_categorie['value'] = cat_select.value or None
                    filter_search['value'] = search_input.value or ''
                    view_mode['value'] = view_toggle.value
                    await ververs_transacties()

                for w in (jaar_select, status_select, cat_select,
                          view_toggle):
                    w.on('update:model-value',
                         lambda _=None: on_filter_change())
                search_input.on(
                    'update:model-value',
                    lambda _=None: on_filter_change())

                # KPI strip
                kpi_container['ref'] = ui.row().classes('w-full gap-4')

                # Reconciliation inbox
                inbox_container['ref'] = ui.column().classes('w-full')

                # Main table
                kosten_table['ref'] = ui.column().classes('w-full')

                # Categorie breakdown
                breakdown_container['ref'] = ui.column().classes('w-full')

            with ui.tab_panel(tab_inv):
                activa_container['ref'] = ui.column().classes('w-full gap-2')

        tabs.on('update:model-value', lambda _: _on_tab_change(
            tabs.value, tab_inv, ververs_investeringen))

    # Initial load
    await ververs_transacties()


def _on_tab_change(current_tab, inv_tab, ververs_inv):
    """Lazy-load investeringen tab content on first view."""
    if current_tab == inv_tab._props.get('name'):
        import asyncio
        asyncio.create_task(ververs_inv())
```

Leave `_laad_kpi`, `_laad_inbox`, `_laad_tabel`, `_laad_breakdown` as **stub functions** that each render a "placeholder" ui.label. This step only validates the scaffold compiles.

```python
async def _laad_kpi(container, jaar):
    if container is None:
        return
    container.clear()
    with container:
        ui.label(f'KPIs voor {jaar} (placeholder)').classes('text-caption')


async def _laad_inbox(container, jaar, refresh):
    if container is None:
        return
    container.clear()  # nothing to show yet


async def _laad_tabel(container, jaar, status, categorie, search, view_mode):
    if container is None:
        return
    container.clear()
    rows = await get_kosten_view(DB_PATH, jaar=jaar, status=status,
                                  categorie=categorie, search=search)
    with container:
        ui.label(
            f'{len(rows)} rij(en) — {view_mode} view (placeholder)') \
            .classes('text-caption text-grey')


async def _laad_breakdown(container, jaar):
    if container is None:
        return
    container.clear()
```

- [ ] **Step 9.2: Run the app manually to verify it loads**

```bash
source .venv/bin/activate
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py
```

Expected: native window opens. Navigate to `/kosten`. You should see:
- Page title "Kosten" + top-right buttons
- Two tabs: Transacties, Investeringen
- On Transacties tab: filter bar + placeholder text "N rij(en) — lijst view (placeholder)"
- On Investeringen tab: the existing activastaat card

**If crash:** read the console stderr; the most likely culprit is the tab-change lambda or the stub imports. Fix before proceeding.

- [ ] **Step 9.3: Run the full test suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```
Expected: all PASS (UI stubs don't break anything).

- [ ] **Step 9.4: Commit the scaffold**

```bash
git add pages/kosten.py
git commit -m "$(cat <<'EOF'
feat(kosten): rewrite page as Transacties + Investeringen tabs

Scaffold only — table/KPI/inbox/breakdown are placeholders; next tasks
wire them up. Investeringen tab reuses laad_activastaat from the lifted
module. Existing Nieuwe-uitgave and Importeer dialogs are preserved.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Main table + inline categorie + paperclip + status pill

**Files:**
- Modify: `pages/kosten.py` (flesh out `_laad_tabel`)

- [ ] **Step 10.1: Implement the main table**

Replace `_laad_tabel` with:

```python
async def _laad_tabel(container, jaar, status, categorie, search, view_mode):
    if container is None:
        return
    container.clear()

    rows = await get_kosten_view(
        DB_PATH, jaar=jaar, status=status,
        categorie=categorie, search=search)

    columns = [
        {'name': 'datum', 'label': 'Datum', 'field': 'datum',
         'align': 'left', 'sortable': True},
        {'name': 'tegenpartij', 'label': 'Tegenpartij / Omschrijving',
         'field': 'tegenpartij', 'align': 'left'},
        {'name': 'categorie', 'label': 'Categorie', 'field': 'categorie',
         'align': 'left'},
        {'name': 'factuur', 'label': 'Factuur', 'field': 'factuur_status',
         'align': 'left'},
        {'name': 'bedrag', 'label': 'Bedrag', 'field': 'bedrag_fmt',
         'align': 'right', 'sortable': True},
        {'name': 'acties', 'label': '', 'field': 'acties', 'align': 'center'},
    ]

    table_rows = []
    for r in rows:
        table_rows.append({
            'id_bank': r.id_bank,
            'id_uitgave': r.id_uitgave,
            'datum': r.datum,
            'datum_fmt': format_datum(r.datum),
            'tegenpartij': r.tegenpartij or r.omschrijving or '(onbekend)',
            'omschrijving': r.omschrijving,
            'categorie': r.categorie,
            'bedrag': r.bedrag,
            'bedrag_fmt': format_euro(r.bedrag),
            'factuur_status': r.status,
            'pdf_pad': r.pdf_pad,
            'is_manual': r.is_manual,
            'initials': initials(r.tegenpartij or r.omschrijving),
            'color': tegenpartij_color(r.tegenpartij or r.omschrijving),
        })

    with container:
        with ui.card().classes('w-full'):
            tbl = ui.table(
                columns=columns, rows=table_rows, row_key='id_uitgave',
                selection='multiple',
                pagination={
                    'rowsPerPage': 20, 'sortBy': 'datum',
                    'descending': True,
                    'rowsPerPageOptions': [10, 20, 50, 0],
                }).classes('w-full').props('flat')

            tbl.add_slot('body-cell-datum', '''
                <q-td :props="props">{{ props.row.datum_fmt }}</q-td>
            ''')

            tbl.add_slot('body-cell-tegenpartij', '''
                <q-td :props="props">
                  <div class="row items-center q-gutter-sm">
                    <div class="q-avatar"
                         :style="`background:${props.row.color};
                                   color:white;
                                   width:30px;height:30px;
                                   border-radius:7px;
                                   display:grid;place-items:center;
                                   font-weight:700;font-size:11px;`">
                      {{ props.row.initials }}
                    </div>
                    <div>
                      <div style="font-weight:500">
                        {{ props.row.tegenpartij }}
                      </div>
                      <div class="text-caption text-grey"
                           v-if="props.row.omschrijving &&
                                  props.row.omschrijving !== props.row.tegenpartij">
                        {{ props.row.omschrijving }}
                      </div>
                    </div>
                  </div>
                </q-td>
            ''')

            tbl.add_slot('body-cell-categorie', '''
                <q-td :props="props">
                  <q-btn-dropdown flat dense
                                  no-caps
                                  :label="props.row.categorie || '— kies —'"
                                  :color="props.row.categorie ? 'primary' : 'warning'"
                                  size="sm">
                    <q-list dense>
                      <q-item v-for="c in $parent.$root.__CAT_LIST__"
                              clickable
                              v-close-popup
                              @click="$parent.$emit('set_cat',
                                       {row: props.row, cat: c})">
                        <q-item-section>{{ c }}</q-item-section>
                      </q-item>
                    </q-list>
                  </q-btn-dropdown>
                </q-td>
            ''')

            tbl.add_slot('body-cell-factuur', '''
                <q-td :props="props">
                  <q-chip v-if="props.row.factuur_status === 'compleet'"
                          color="positive" text-color="white"
                          size="sm" icon="check_circle" dense>
                    Compleet
                  </q-chip>
                  <q-chip v-else-if="props.row.factuur_status === 'ontbreekt'"
                          color="warning" text-color="white"
                          size="sm" icon="warning" dense>
                    Ontbreekt
                  </q-chip>
                  <q-chip v-else color="info" text-color="white"
                          size="sm" dense>
                    Nieuw
                  </q-chip>
                  <q-btn v-if="props.row.pdf_pad" flat dense round size="xs"
                         icon="attach_file" color="primary"
                         @click="$parent.$emit('view_pdf', props.row)" />
                  <q-chip v-if="props.row.is_manual" color="grey"
                          text-color="white" size="sm" dense>
                    contant
                  </q-chip>
                </q-td>
            ''')

            tbl.add_slot('body-cell-acties', '''
                <q-td :props="props">
                  <q-btn flat dense round icon="attach_file"
                         size="sm" color="primary"
                         title="Bon toevoegen"
                         @click="$parent.$emit('attach_pdf', props.row)" />
                  <q-btn flat dense round icon="more_horiz"
                         size="sm" color="grey-7"
                         @click="$parent.$emit('open_detail', props.row)" />
                </q-td>
            ''')

            tbl.add_slot('no-data', '''
                <q-tr><q-td colspan="100%"
                            class="text-center q-pa-lg text-grey">
                  Geen transacties gevonden.
                </q-td></q-tr>
            ''')

            # Inject the category list into the Vue root so the template above
            # can use it. NiceGUI currently doesn't expose a cleaner hook.
            ui.add_body_html(f'''
            <script>window.__CAT_LIST__ = {list(CATEGORIEEN)!r};</script>
            ''')

            tbl.on('set_cat',
                   lambda e: _on_set_cat(e.args, ververs_transacties))
            tbl.on('view_pdf',
                   lambda e: _view_pdf(e.args))
            tbl.on('attach_pdf',
                   lambda e: _attach_pdf_dialog(e.args, ververs_transacties))
            tbl.on('open_detail',
                   lambda e: _open_detail_dialog(e.args, ververs_transacties))


async def _on_set_cat(args: dict, refresh):
    row = args['row']
    cat = args['cat']
    try:
        if row['id_bank'] is not None and row['id_uitgave'] is None:
            uid = await ensure_uitgave_for_banktx(
                DB_PATH, bank_tx_id=row['id_bank'], categorie=cat)
        else:
            await update_uitgave(
                DB_PATH, uitgave_id=row['id_uitgave'], categorie=cat)
        ui.notify(f'Categorie bijgewerkt naar {cat}', type='positive')
        await refresh()
    except YearLockedError as e:
        ui.notify(str(e), type='negative')


def _view_pdf(row: dict):
    p = row.get('pdf_pad', '')
    if p and Path(p).exists():
        ui.download.file(p)
    else:
        ui.notify('Bon niet gevonden', type='warning')


async def _attach_pdf_dialog(row, refresh):
    """Placeholder — implemented in Task 11's detail dialog.

    For this task we just route to the Detail dialog's Factuur tab."""
    await _open_detail_dialog(row, refresh, default_tab='factuur')


async def _open_detail_dialog(row, refresh, default_tab='detail'):
    """Stub — filled in Task 11."""
    ui.notify('Detail-dialog komt in Task 11', type='info')
```

Note: the `ververs_transacties` callable is defined inside `kosten_page()`; pass it down by binding closures, or make these top-level functions accept the refresh callable. Using module-level functions with the refresh passed explicitly (as shown) keeps the page body smaller. Make sure to import `YearLockedError`, `update_uitgave`, `CATEGORIEEN` at the top.

- [ ] **Step 10.2: Manual smoke test**

```bash
source .venv/bin/activate
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py
```

Check:
- `/kosten` loads; rows render with avatar initials in a colored chip
- Clicking "— kies —" dropdown offers categories; selecting one updates the row (year-lock errors show a negative toast)
- Paperclip icon shows when `pdf_pad` is set; click downloads the file
- "more_horiz" button shows the "komt in Task 11" info toast
- Filters (jaar / status / categorie / zoek / view toggle) all trigger a refresh

- [ ] **Step 10.3: Full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```
Expected: all PASS (no new tests in this task; UI is manual-smoke).

- [ ] **Step 10.4: Commit**

```bash
git add pages/kosten.py
git commit -m "$(cat <<'EOF'
feat(kosten): main table with avatar, status pill, inline categorie

Row avatar uses deterministic HSL color; categorie dropdown lazy-creates
the uitgave for bank-only rows via ensure_uitgave_for_banktx. Factuur
column renders status pill + attached-PDF link + 'contant' badge for
manual rows. Detail dialog wired to a stub (Task 11).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Detail dialog — Detail / Factuur / Historie tabs

**Files:**
- Modify: `pages/kosten.py` (replace `_open_detail_dialog` stub)

- [ ] **Step 11.1: Implement the detail dialog**

Replace the stub with the full dialog. Import needed symbols.

```python
async def _open_detail_dialog(row, refresh, default_tab='detail'):
    """Detail dialog with Detail / Factuur / Historie tabs.

    row: dict from the table's body — has id_bank, id_uitgave, datum,
         bedrag, categorie, pdf_pad, is_manual, tegenpartij,
         omschrijving, etc.
    """
    # Ensure we have an uitgave to edit. For bank-only rows, lazy-create.
    try:
        if row['id_uitgave'] is None and row['id_bank'] is not None:
            uid = await ensure_uitgave_for_banktx(
                DB_PATH, bank_tx_id=row['id_bank'])
            row['id_uitgave'] = uid
    except YearLockedError as e:
        ui.notify(str(e), type='negative')
        return

    # Re-load fresh uitgave data
    uitgaven = await get_uitgaven(DB_PATH, jaar=int(row['datum'][:4]))
    u = next((x for x in uitgaven if x.id == row['id_uitgave']), None)
    if u is None and not row['is_manual']:
        ui.notify('Fout: uitgave niet gevonden na aanmaken', type='negative')
        return

    bank_linked = row['id_bank'] is not None

    with ui.dialog() as dialog, ui.card() \
            .classes('w-full').style('max-width: 760px'):
        ui.label(f"Transactie — {row['tegenpartij']}") \
            .classes('text-h6 q-mb-sm')

        with ui.tabs() as tabs:
            t_detail = ui.tab('Detail', icon='edit')
            t_factuur = ui.tab('Factuur', icon='description')
            t_hist = ui.tab('Historie', icon='history')

        initial_tab = {'detail': t_detail, 'factuur': t_factuur,
                       'historie': t_hist}[default_tab]

        with ui.tab_panels(tabs, value=initial_tab).classes('w-full'):
            # ---------------- DETAIL ----------------
            with ui.tab_panel(t_detail):
                with ui.row().classes('items-baseline gap-3 q-mb-sm'):
                    ui.label(format_euro(row['bedrag'])) \
                        .classes('text-h5 text-bold')
                    ui.label(format_datum(row['datum'])) \
                        .classes('text-caption text-grey')

                if bank_linked:
                    ui.label(f"IBAN: {row.get('iban', '') or '—'}") \
                        .classes('text-caption text-grey')

                # bedrag: editable only for manual uitgaven
                if not bank_linked:
                    edit_bedrag = ui.number(
                        'Bedrag (€)', value=row['bedrag'],
                        format='%.2f', min=0.01, step=0.01) \
                        .classes('w-full')
                else:
                    edit_bedrag = None  # locked to bank_tx.bedrag

                edit_cat = ui.select(
                    CATEGORIEEN, label='Categorie',
                    value=u.categorie if u else '').classes('w-full')

                edit_omschr = ui.textarea(
                    'Omschrijving / notitie',
                    value=u.omschrijving if u else row['omschrijving']) \
                    .classes('w-full').props('autogrow')

                edit_inv = ui.checkbox(
                    'Dit is een investering',
                    value=bool(u.is_investering) if u else False)
                inv_box = ui.column().classes('pl-8 gap-2')
                inv_box.set_visibility(edit_inv.value)
                with inv_box:
                    with ui.row().classes('items-end gap-4'):
                        edit_lv = ui.select(
                            LEVENSDUUR_OPTIES, label='Levensduur',
                            value=(u.levensduur_jaren
                                    if u and u.levensduur_jaren else 5)) \
                            .classes('w-28')
                        edit_rest = ui.number(
                            'Restwaarde %',
                            value=(u.restwaarde_pct
                                    if u and u.restwaarde_pct else 10),
                            min=0, max=100).classes('w-28')
                        edit_zak = ui.number(
                            'Zakelijk %',
                            value=(u.zakelijk_pct
                                    if u and u.zakelijk_pct else 100),
                            min=0, max=100).classes('w-28')

                edit_inv.on('update:model-value',
                            lambda: inv_box.set_visibility(edit_inv.value))

                if bank_linked and u is not None:
                    async def ontkoppel():
                        await update_uitgave(
                            DB_PATH, uitgave_id=u.id, bank_tx_id=None)
                        ui.notify('Bank-transactie ontkoppeld',
                                  type='positive')
                        dialog.close()
                        await refresh()

                    ui.button('Ontkoppel bank-transactie', icon='link_off',
                              on_click=ontkoppel) \
                        .props('flat dense color=grey-7 size=sm')

            # ---------------- FACTUUR ----------------
            with ui.tab_panel(t_factuur):
                pdf_box = ui.column().classes('w-full')
                await _render_factuur_tab(
                    pdf_box, u, row, refresh, dialog)

            # ---------------- HISTORIE ----------------
            with ui.tab_panel(t_hist):
                hist_box = ui.column().classes('w-full')
                await _render_historie_tab(hist_box, row)

        # Footer
        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
            ui.button('Annuleren', on_click=dialog.close).props('flat')
            if u is not None:
                async def verwijder():
                    with ui.dialog() as confirm, ui.card():
                        ui.label('Uitgave verwijderen?').classes('text-h6')
                        ui.label(
                            f"{row['datum']} — "
                            f"{row['omschrijving'] or row['tegenpartij']} "
                            f"— {format_euro(row['bedrag'])}") \
                            .classes('text-grey')
                        with ui.row().classes('w-full justify-end gap-2'):
                            ui.button('Annuleren',
                                      on_click=confirm.close).props('flat')

                            async def do_del():
                                await delete_uitgave(
                                    DB_PATH, uitgave_id=u.id)
                                confirm.close()
                                dialog.close()
                                ui.notify('Uitgave verwijderd',
                                          type='positive')
                                await refresh()

                            ui.button('Verwijderen', on_click=do_del) \
                                .props('color=negative')
                    confirm.open()

                ui.button('Verwijder', icon='delete',
                          on_click=verwijder) \
                    .props('flat color=negative')

            async def opslaan():
                try:
                    kwargs = {
                        'categorie': edit_cat.value or '',
                        'omschrijving': edit_omschr.value or '',
                    }
                    if edit_bedrag is not None:
                        kwargs['bedrag'] = edit_bedrag.value
                    if edit_inv.value:
                        kwargs['is_investering'] = 1
                        kwargs['levensduur_jaren'] = edit_lv.value
                        kwargs['restwaarde_pct'] = edit_rest.value or 10
                        kwargs['zakelijk_pct'] = edit_zak.value or 100
                        kwargs['aanschaf_bedrag'] = \
                            (edit_bedrag.value if edit_bedrag is not None
                             else row['bedrag'])
                    else:
                        kwargs['is_investering'] = 0
                        kwargs['levensduur_jaren'] = None
                        kwargs['aanschaf_bedrag'] = None
                    await update_uitgave(
                        DB_PATH, uitgave_id=row['id_uitgave'], **kwargs)
                    ui.notify('Opgeslagen', type='positive')
                    dialog.close()
                    await refresh()
                except YearLockedError as e:
                    ui.notify(str(e), type='negative')

            ui.button('Opslaan', icon='save', on_click=opslaan) \
                .props('color=primary')

    dialog.open()


async def _render_factuur_tab(container, uitgave, row, refresh, dialog):
    container.clear()
    pdf = (uitgave.pdf_pad if uitgave else '') or ''
    if pdf and Path(pdf).exists():
        import base64
        data = Path(pdf).read_bytes()
        b64 = base64.b64encode(data).decode('ascii')
        suffix = Path(pdf).suffix.lower()
        mime = 'application/pdf' if suffix == '.pdf' else 'image/*'
        with container:
            ui.html(
                f'<iframe src="data:{mime};base64,{b64}" '
                f'style="width:100%;height:520px;border:1px solid #e5e7eb;'
                f'border-radius:8px"></iframe>')
            with ui.row().classes('gap-2 q-mt-sm'):
                ui.button('Download', icon='download',
                          on_click=lambda: ui.download.file(pdf)) \
                    .props('flat dense')

                async def verwijder_bon():
                    await update_uitgave(
                        DB_PATH, uitgave_id=uitgave.id, pdf_pad='')
                    p = Path(pdf)
                    if p.exists():
                        await asyncio.to_thread(p.unlink)
                    ui.notify('Bon verwijderd', type='positive')
                    await _render_factuur_tab(
                        container, uitgave, row, refresh, dialog)

                ui.button('Verwijder bon', icon='delete',
                          on_click=verwijder_bon) \
                    .props('flat dense color=negative')
        return

    # No PDF yet — upload + suggestions
    with container:
        upload_target = {'event': None}
        ui.upload(
            label='Bon uploaden', auto_upload=True,
            on_upload=lambda e: upload_target.update({'event': e}),
            max_file_size=10_000_000) \
            .classes('w-full').props(
                'flat bordered accept=".pdf,.jpg,.jpeg,.png"')

        async def do_save_upload():
            e = upload_target['event']
            if e is None:
                ui.notify('Selecteer eerst een bestand', type='warning')
                return
            await save_upload_for_uitgave(uitgave.id, e)
            ui.notify('Bon opgeslagen', type='positive')
            await refresh()
            await _render_factuur_tab(
                container, uitgave, row, refresh, dialog)

        ui.button('Koppel', on_click=do_save_upload) \
            .props('color=primary dense')

        if row.get('id_bank') is not None:
            ui.separator().classes('q-my-sm')
            ui.label('Slimme suggesties uit archief') \
                .classes('text-caption text-bold')
            matches = await find_pdf_matches_for_banktx(
                DB_PATH, row['id_bank'], int(row['datum'][:4]))
            if not matches:
                ui.label('Geen archief-suggesties gevonden') \
                    .classes('text-caption text-grey')
            for m in matches[:5]:
                with ui.row().classes(
                        'w-full items-center gap-2 q-py-xs'):
                    ui.icon('picture_as_pdf', color='red')
                    ui.label(m.filename).classes('text-body2')
                    ui.label(f'→ {m.categorie}') \
                        .classes('text-caption text-grey')
                    ui.space()

                    async def _koppel(mm=m):
                        await _copy_and_link_pdf(uitgave.id, mm.path)
                        await update_uitgave(
                            DB_PATH, uitgave_id=uitgave.id,
                            categorie=mm.categorie)
                        ui.notify('Bon gekoppeld', type='positive')
                        await refresh()
                        await _render_factuur_tab(
                            container, uitgave, row, refresh, dialog)

                    ui.button('Koppel', on_click=_koppel) \
                        .props('flat dense color=primary size=sm')


async def _render_historie_tab(container, row):
    """Last 12 months of entries matching tegenpartij / omschrijving."""
    container.clear()
    jaar = int(row['datum'][:4])
    jaren = [jaar, jaar - 1]
    tp = (row['tegenpartij'] or row['omschrijving'] or '').strip().lower()
    if not tp:
        with container:
            ui.label('Geen tegenpartij — geen historie beschikbaar.') \
                .classes('text-caption text-grey')
        return

    hits = []
    for y in jaren:
        view = await get_kosten_view(DB_PATH, jaar=y)
        for r in view:
            if r.id_bank == row['id_bank']:
                continue  # skip self
            if (tp in (r.tegenpartij or '').lower()
                    or tp in (r.omschrijving or '').lower()):
                hits.append(r)
    hits.sort(key=lambda r: r.datum, reverse=True)

    with container:
        if not hits:
            ui.label('Geen eerdere transacties gevonden.') \
                .classes('text-caption text-grey')
            return
        for h in hits[:20]:
            with ui.row().classes('w-full items-center q-py-xs'):
                ui.label(format_datum(h.datum)) \
                    .classes('text-caption text-grey').style('width:100px')
                ui.label(h.tegenpartij or h.omschrijving).classes('flex-1')
                ui.label(format_euro(h.bedrag)) \
                    .classes('text-bold').style('text-align:right')

        if len(hits) >= 3:
            recent = [h for h in hits
                      if (datetime.strptime(h.datum, '%Y-%m-%d')
                          - datetime.strptime(row['datum'], '%Y-%m-%d')).days
                      > -120]
            if len(recent) >= 3:
                with ui.row().classes(
                        'items-center gap-2 q-mt-md q-pa-sm') \
                        .style('background:#eff6ff;border-radius:8px'):
                    ui.icon('bolt', color='info')
                    ui.label(
                        'Dit lijkt een terugkerende kost — '
                        'gebruik Importeer om volgende exemplaren '
                        'automatisch te categoriseren.') \
                        .classes('text-caption')
```

Add these imports at the top of `pages/kosten.py` if missing: `from datetime import datetime`, `import base64`, `from database import ..., get_uitgaven, update_uitgave, delete_uitgave`.

- [ ] **Step 11.2: Manual smoke — all three tabs**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py
```

Check on `/kosten`:
- Click `more_horiz` on a bank-only row → dialog opens, lazy-creates uitgave, Detail tab shows
- Switch to Factuur tab → upload zone visible; archive suggestions appear if tegenpartij matches a file in `~/SynologyDrive/Financieel archief/.../Uitgaven/...`
- Upload a test PDF → saves, iframe preview appears
- Toggle Investering → reveals levensduur/restwaarde/zakelijk fields
- Click Opslaan → toast + refresh
- Switch to Historie tab → if any same-tegenpartij tx exists, it lists them; ≥3 recent = blue tip appears
- Click Verwijder → confirm dialog → deletes
- Dialog close + refresh

- [ ] **Step 11.3: Commit**

```bash
git add pages/kosten.py
git commit -m "$(cat <<'EOF'
feat(kosten): detail dialog with Detail / Factuur / Historie tabs

Lazy-creates uitgave on open for bank-only rows. Factuur tab: iframe
preview via base64 data URI, upload, + archive suggestions from
find_pdf_matches_for_banktx. Historie tab: same-tegenpartij lookup with
a 'terugkerend' tip when ≥ 3 recent hits. Bedrag is locked for
bank-linked rows; editable for manual uitgaven.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: KPI strip + Reconciliation inbox + Bulk bar

**Files:**
- Modify: `pages/kosten.py` (flesh out `_laad_kpi`, `_laad_inbox`, add bulk bar; also view-mode month dividers)

- [ ] **Step 12.1: Implement KPI strip**

Replace `_laad_kpi`:

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
                ui.label(label) \
                    .classes('text-caption text-uppercase text-grey')
            ui.label(value) \
                .classes('text-h5 text-bold q-mt-xs') \
                .style('font-variant-numeric: tabular-nums')
            if sub:
                ui.label(sub).classes('text-caption text-grey')
        return c

    with container:
        _card(
            f'Totaal kosten {jaar}',
            format_euro(kpi.totaal),
            f"{len([m for m in kpi.monthly_totals if m>0])} actieve maanden")

        _card(
            'Factuur ontbreekt',
            str(kpi.ontbreekt_count),
            format_euro(kpi.ontbreekt_bedrag),
            color='warning', icon='warning',
            on_click=lambda: None)  # filter via status dropdown manually

        _card(
            f'Afschrijvingen {jaar}',
            format_euro(kpi.afschrijvingen_jaar),
            'Zie tab Investeringen',
            icon='trending_down')

        _card(
            f'Investeringen {jaar}',
            str(kpi.investeringen_count),
            format_euro(kpi.investeringen_bedrag),
            icon='inventory_2')
```

- [ ] **Step 12.2: Implement reconciliation inbox**

Replace `_laad_inbox`:

```python
async def _laad_inbox(container, jaar, refresh):
    if container is None:
        return
    container.clear()
    rows = await get_kosten_view(DB_PATH, jaar=jaar)
    needs = [r for r in rows
             if r.status in ('ongecategoriseerd', 'ontbreekt')]
    if not needs:
        return

    needs.sort(key=lambda r: r.datum, reverse=True)
    top4 = needs[:4]

    with container:
        with ui.card() \
                .classes('w-full q-pa-md') \
                .style('background:linear-gradient(135deg,#fff7ed,#ffffff);'
                        'border:1px solid #fed7aa'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('warning', color='warning').classes('text-2xl')
                with ui.column().classes('flex-1 gap-0'):
                    ui.label(
                        f'{len(needs)} transactie(s) hebben nog aandacht nodig') \
                        .classes('text-subtitle2 text-bold')
                    ui.label(
                        'Klik om te categoriseren of een bon toe te voegen.') \
                        .classes('text-caption text-grey')

            with ui.row().classes('w-full gap-2 q-mt-md'):
                for r in top4:
                    card = ui.card() \
                        .classes('q-pa-sm flex-1 cursor-pointer') \
                        .style('min-width:220px')
                    with card:
                        with ui.row().classes('w-full items-baseline'):
                            ui.label(
                                r.tegenpartij or r.omschrijving or '(—)') \
                                .classes('text-body2 text-bold')
                            ui.space()
                            ui.label(format_euro(r.bedrag)) \
                                .classes('text-body2 text-bold') \
                                .style('font-variant-numeric:tabular-nums')
                        ui.label(format_datum(r.datum)) \
                            .classes('text-caption text-grey')

                    async def _on_click(row=r):
                        row_dict = {
                            'id_bank': row.id_bank,
                            'id_uitgave': row.id_uitgave,
                            'datum': row.datum,
                            'bedrag': row.bedrag,
                            'tegenpartij': row.tegenpartij,
                            'omschrijving': row.omschrijving,
                            'categorie': row.categorie,
                            'pdf_pad': row.pdf_pad,
                            'is_manual': row.is_manual,
                            'iban': row.iban,
                        }
                        await _open_detail_dialog(row_dict, refresh)

                    card.on('click', lambda _=None, r=r:
                            asyncio.create_task(_on_click(r)))
```

- [ ] **Step 12.3: Add bulk action bar + wire selection**

In the `_laad_tabel` function, add — *below* the `ui.table(...)` creation — a `bulk_row` that watches selection:

```python
# Below the ui.table(...) call, before the slot definitions:
bulk_row = ui.row() \
    .classes('w-full items-center gap-2 q-py-sm') \
    .style('background:#0f172a;color:white;border-radius:8px;'
            'padding:8px 16px')
bulk_row.set_visibility(False)
with bulk_row:
    bulk_label = ui.label('')

    async def bulk_set_cat():
        with ui.dialog() as dlg, ui.card():
            ui.label('Nieuwe categorie voor selectie').classes('text-h6')
            sel = ui.select(CATEGORIEEN, label='Categorie') \
                .classes('w-full')
            with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                ui.button('Annuleren', on_click=dlg.close).props('flat')

                async def apply():
                    n_ok, n_skip = 0, 0
                    for r in tbl.selected:
                        try:
                            if r['id_uitgave'] is None \
                                    and r['id_bank'] is not None:
                                await ensure_uitgave_for_banktx(
                                    DB_PATH, bank_tx_id=r['id_bank'],
                                    categorie=sel.value or '')
                            else:
                                await update_uitgave(
                                    DB_PATH, uitgave_id=r['id_uitgave'],
                                    categorie=sel.value or '')
                            n_ok += 1
                        except YearLockedError:
                            n_skip += 1
                    dlg.close()
                    msg = f'{n_ok} bijgewerkt'
                    if n_skip:
                        msg += f', {n_skip} overgeslagen (jaar afgesloten)'
                    ui.notify(msg, type='positive' if n_ok else 'warning')
                    await refresh()

                ui.button('Toepassen', on_click=apply) \
                    .props('color=primary')
        dlg.open()

    ui.button('Categorie wijzigen', icon='label',
              on_click=bulk_set_cat) \
        .props('outline color=white size=sm')

    async def bulk_negeren():
        n_ok, n_skip = 0, 0
        for r in tbl.selected:
            if r['id_bank'] is None:
                continue
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
        for r in tbl.selected:
            if r['id_uitgave'] is None:
                continue
            try:
                await delete_uitgave(DB_PATH, uitgave_id=r['id_uitgave'])
                n_ok += 1
            except YearLockedError:
                n_skip += 1
        msg = f'{n_ok} uitgave(n) verwijderd'
        if n_skip:
            msg += f', {n_skip} overgeslagen'
        ui.notify(msg, type='positive' if n_ok else 'warning')
        await refresh()

    ui.button('Verwijderen', icon='delete',
              on_click=bulk_delete) \
        .props('outline color=white size=sm')


def update_bulk():
    n = len(tbl.selected)
    if n > 0:
        bulk_row.set_visibility(True)
        bulk_label.text = f'{n} geselecteerd'
    else:
        bulk_row.set_visibility(False)


tbl.on('selection', lambda _: update_bulk())
```

- [ ] **Step 12.4: View toggle — month dividers (per-maand)**

Extend `_laad_tabel` with month-divider rendering when `view_mode == 'maand'`:

```python
if view_mode == 'maand':
    # Insert synthetic divider rows. Use a top-row slot.
    tbl.add_slot('top-row', '''
        <q-tr v-if="props.row.__maand_header__">
          <q-td colspan="100%"
                class="text-weight-medium text-grey"
                style="background:#f1f5f9;letter-spacing:0.05em;
                       text-transform:uppercase;font-size:11px;
                       padding:8px 14px">
            {{ props.row.__maand__ }}
            <span style="float:right;font-variant-numeric:tabular-nums">
              {{ props.row.__maand_total__ }}
            </span>
          </q-td>
        </q-tr>
    ''')
    # Build rows with month dividers inserted
    grouped: list[dict] = []
    current_month = None
    month_buf: list[dict] = []
    for tr in table_rows:
        m = tr['datum'][:7]
        if m != current_month:
            if month_buf:
                total = sum(x['bedrag'] for x in month_buf)
                grouped.append({
                    '__maand_header__': True,
                    '__maand__': current_month,
                    '__maand_total__': format_euro(total),
                    'id_uitgave': f'__hdr_{current_month}',
                    'datum': current_month + '-00',  # so sort stays stable
                })
                grouped.extend(month_buf)
                month_buf = []
            current_month = m
        month_buf.append(tr)
    if month_buf:
        total = sum(x['bedrag'] for x in month_buf)
        grouped.append({
            '__maand_header__': True,
            '__maand__': current_month,
            '__maand_total__': format_euro(total),
            'id_uitgave': f'__hdr_{current_month}',
            'datum': current_month + '-00',
        })
        grouped.extend(month_buf)
    tbl.rows = grouped
    tbl.update()
```

**Note:** the `top-row` slot in Quasar renders once per row if the template condition is true. If this visual is imperfect, leave the flat "lijst" view wired and ship month dividers as a v1.1 polish.

- [ ] **Step 12.5: Manual smoke test**

- KPI strip shows 4 cards with real numbers
- If any Ongecategoriseerd/Ontbreekt rows: orange inbox band appears above the table
- Clicking an inbox card opens the detail dialog
- Selecting rows → black bulk bar appears; "Categorie wijzigen" / "Markeer als privé" / "Verwijderen" all work
- "Per maand" view: month headers with totals

- [ ] **Step 12.6: Commit**

```bash
git add pages/kosten.py
git commit -m "$(cat <<'EOF'
feat(kosten): KPI strip, reconciliation inbox, bulk action bar

KPI cards driven by get_kpi_kosten. Inbox shows top 4 recent rows that
need action. Bulk bar supports Categorie-wijzigen / Markeer-als-privé /
Verwijderen with year-lock skip summary. Per-maand view inserts month
dividers with totals.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Importeer dialog — match-hint enhancement

**Files:**
- Modify: `pages/kosten.py` (the existing `open_import_dialog`)

- [ ] **Step 13.1: Add bank-tx match hint next to each archive file**

Inside `open_import_dialog`, in the block that renders each not-yet-imported item (look for the `else` branch under `if item['already_imported']`), add the match-hint. You need an inverse helper that, given a PDF filename + folder categorie, finds candidate bank txs by token overlap:

Add to `database.py`:

```python
async def find_banktx_matches_for_pdf(
    db_path: Path, filename: str, jaar: int,
) -> list[tuple[int, str, float, str]]:
    """Return (bank_tx_id, datum, bedrag_abs, tegenpartij) tuples where
    filename tokens overlap with banktransacties.tegenpartij (len>=4)."""
    from components.kosten_helpers import match_tokens
    stem = _Path(filename).stem
    jaar_start = f"{jaar:04d}-01-01"
    jaar_end = f"{jaar + 1:04d}-01-01"
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT id, datum, bedrag, tegenpartij FROM banktransacties "
            "WHERE bedrag < 0 AND genegeerd = 0 "
            "AND datum >= ? AND datum < ? "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM uitgaven WHERE bank_tx_id = banktransacties.id"
            ")",
            (jaar_start, jaar_end))
        candidates = []
        for r in await cur.fetchall():
            score = match_tokens(r["tegenpartij"] or "", stem)
            if score > 0:
                candidates.append((r["id"], r["datum"],
                                    abs(r["bedrag"]), r["tegenpartij"],
                                    score))
    candidates.sort(key=lambda x: x[4], reverse=True)
    return [c[:4] for c in candidates]
```

In `open_import_dialog`, when rendering each non-imported item row, fetch the match and show it:

```python
# inside open_import_dialog, replacing the inner loop body for a non-imported item:
async def render_item(item):
    ...
    matches = await find_banktx_matches_for_pdf(
        DB_PATH, item['filename'], jaar)
    with ui.row().classes('w-full items-center gap-2 q-py-xs'):
        ui.icon('upload_file', color='primary').classes('text-lg')

        async def _do_import(it=item, bank_match=matches[0] if matches else None):
            prefill = {
                'datum': (it['datum']
                          or (bank_match[1] if bank_match else
                              date.today().isoformat())),
                'categorie': it['categorie'],
                'pdf_path': str(it['path']),
            }
            if bank_match:
                prefill['bank_tx_id'] = bank_match[0]
            await open_add_uitgave_dialog(
                prefill=prefill, on_saved=load_archive)

        ui.link(item['filename'], on_click=_do_import) \
            .classes('text-primary cursor-pointer')
        if item['datum']:
            ui.label(item['datum']) \
                .classes('text-caption text-grey')
        if matches:
            m = matches[0]
            ui.label(
                f'↔ {m[3]} · {format_datum(m[1])} · '
                f'{format_euro(m[2])}') \
                .classes('text-caption text-primary')
```

Also extend `open_add_uitgave_dialog` to accept a `bank_tx_id` prefill and, if present, set it on the created uitgave. Find the `add_uitgave(DB_PATH, **kwargs)` call and add:

```python
if prefill and prefill.get('bank_tx_id'):
    kwargs['bank_tx_id'] = prefill['bank_tx_id']
```

…and check `add_uitgave` accepts `bank_tx_id` — if not (it likely only maps a fixed set of columns), update `add_uitgave` in `database.py` to pass through `bank_tx_id` to the INSERT.

- [ ] **Step 13.2: Add a test for `find_banktx_matches_for_pdf`**

```python
# append to tests/test_kosten_matching.py
@pytest.mark.asyncio
async def test_find_banktx_match_returns_unmatched_only(db):
    import aiosqlite
    from database import (find_banktx_matches_for_pdf,
                          ensure_uitgave_for_banktx)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij) VALUES (1, ?, ?, ?)",
            ("2026-04-01", -120.87, "KPN B.V."))
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij) VALUES (2, ?, ?, ?)",
            ("2026-04-01", -120.87, "KPN B.V."))
        await conn.commit()
    # Link the first one
    await ensure_uitgave_for_banktx(db, 1)
    hits = await find_banktx_matches_for_pdf(
        db, "2026-04-01_KPN_abo.pdf", 2026)
    ids = [h[0] for h in hits]
    assert 1 not in ids
    assert 2 in ids
```

- [ ] **Step 13.3: Run all tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```
Expected: all PASS.

- [ ] **Step 13.4: Manual smoke**

In Importeer dialog, if archive contains e.g. `2026-04-01_KPN_abo.pdf` and a matching bank tx exists, the filename row shows `↔ KPN B.V. · 01-04-2026 · € 120,87`. Clicking the link opens the prefilled Nieuwe-uitgave dialog; saving links the bank tx.

- [ ] **Step 13.5: Commit**

```bash
git add database.py pages/kosten.py tests/test_kosten_matching.py
git commit -m "$(cat <<'EOF'
feat(kosten): Importeer shows bank-tx match hint + auto-links on save

find_banktx_matches_for_pdf surfaces likely bank txs when scanning the
archive. open_add_uitgave_dialog accepts bank_tx_id in prefill and
attaches it on save. Unmatched PDFs still create standalone uitgaven.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Categorie breakdown card + final end-to-end smoke

**Files:**
- Modify: `pages/kosten.py` (flesh out `_laad_breakdown`)

- [ ] **Step 14.1: Implement the breakdown card**

```python
async def _laad_breakdown(container, jaar):
    if container is None:
        return
    container.clear()
    rows = await get_kosten_view(DB_PATH, jaar=jaar)
    totals: dict[str, float] = {}
    for r in rows:
        key = r.categorie or '(nog te categoriseren)'
        totals[key] = totals.get(key, 0.0) + r.bedrag
    if not totals:
        return
    sorted_totals = sorted(totals.items(), key=lambda kv: kv[1],
                            reverse=True)
    grand = sum(totals.values())

    with container:
        with ui.card().classes('w-full q-pa-md'):
            with ui.row().classes('w-full items-center'):
                ui.label(f'Kosten per categorie — {jaar}') \
                    .classes('text-subtitle1 text-bold')
                ui.space()
                ui.label(f'Totaal {format_euro(grand)}') \
                    .classes('text-caption text-grey')

            for name, amt in sorted_totals:
                pct = (amt / grand * 100) if grand else 0
                with ui.column().classes('w-full gap-0 q-my-xs'):
                    with ui.row().classes('w-full'):
                        ui.label(name).classes('text-body2')
                        ui.space()
                        ui.label(
                            f'{format_euro(amt)} · {pct:.1f}%') \
                            .classes('text-body2 text-bold') \
                            .style('font-variant-numeric:tabular-nums')
                    ui.linear_progress(value=pct / 100) \
                        .props('color=primary size=6px')
```

- [ ] **Step 14.2: End-to-end manual smoke test**

Run the app and exercise the full flow:

1. `/kosten` loads under Transacties tab
2. All 4 KPIs populate
3. Inbox band appears if any ongecat/ontbreekt rows exist
4. Filter by jaar / status / categorie / search — table refreshes
5. Click a bank-only row's categorie dropdown → select a value → row refreshes with new category + status transitions
6. Open detail dialog (more_horiz) → tabs work, upload works, save persists, delete works
7. Select multiple rows → bulk bar appears → Categorie wijzigen / Markeer als privé / Verwijderen all work with a summary toast when some rows are in a definitief year
8. Toggle Per maand → month dividers appear with totals
9. Switch to Investeringen tab → activastaat renders; edit afschrijving → saves
10. Breakdown card at bottom shows horizontal bars per categorie
11. Importeer dialog shows ↔ match hints; imported file links to bank tx
12. Nieuwe-uitgave button still creates standalone cash-receipt uitgaven

- [ ] **Step 14.3: Full test suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```
Expected: all PASS.

- [ ] **Step 14.4: Update MEMORY.md open_plans**

Remove or update the "database package refactor is written but intentionally unexecuted" entry if it references Kosten; leave it if unrelated. Check with:

```bash
cat /Users/macbookpro_test/.claude/projects/-Users-macbookpro-test-Library-CloudStorage-SynologyDrive-Main-06-Development-1-roberg-boekhouding/memory/open_plans.md
```

- [ ] **Step 14.5: Final commit**

```bash
git add pages/kosten.py
git commit -m "$(cat <<'EOF'
feat(kosten): categorie breakdown card + final wiring

Horizontal bars per categorie, sorted by bedrag desc. Completes the
Kosten rework: Transacties tab (unified list, KPIs, inbox, drawer-style
dialog, bulk bar, month view, breakdown) + Investeringen tab (lifted
activastaat). No fiscal API changes, no data migration.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review — spec coverage matrix

| Spec section | Task(s) covering it |
|---|---|
| §3 Constraints (WAL-safe, year-lock, raw SQL, date range, dialog-not-drawer, no BTW, no drag-drop) | Task 1 (WAL-safe + migration); Tasks 3/4/5/6/7/10/11/12/13/14 (dialog, date range, year-lock, no BTW UI) |
| §4 Schema changes | Task 1 |
| §5 Status derivation | Task 2 (`derive_status`) + Task 6 (`get_kosten_view` applies it) |
| §6.1 `get_kosten_view` | Task 6 |
| §6.2 `ensure_uitgave_for_banktx` | Task 3 |
| §6.3 `mark_banktx_genegeerd` | Task 4 |
| §6.4 `find_pdf_matches_for_banktx` | Task 5 (+ Task 13 for inverse) |
| §6.5 `get_kpi_kosten` | Task 7 |
| §7 Page structure (tabs) | Task 9 |
| §8 KPI strip | Task 12 (step 12.1) |
| §9 Reconciliation inbox | Task 12 (step 12.2) |
| §10 Main table (avatar, status pill, inline cat, paperclip, view toggle, bulk) | Tasks 10 + 12 |
| §11 Detail dialog (Detail/Factuur/Historie) | Task 11 |
| §12 Importeer dialog enhancement | Task 13 |
| §13 Nieuwe uitgave (unchanged) | Task 9 (retained; no change required) |
| §14 Files map | Tasks 2, 8, 9 (and test files scattered) |
| §15 Testing matrix | Tasks 1–7 (one test file per concern) |
| §16 Risks / deferrals | Documented in spec; no tasks required |
| §17 Rollback plan | Implicit — all changes additive + `git revert` |

Ambiguity / contradiction check passes — no duplicated symbols, no placeholders, every referenced function is defined.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-21-kosten-rework.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
