# Sprint J — VA-tracker drill-down + PDF-parse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Click op /dashboard VA-tile → nieuwe `/va-tracker/{jaar}` page met PDF-bron, termijnen-overzicht, individuele bank-tx. PDF-upload in /documenten parset bedrag/kenmerk/termijnen automatisch + sync naar fiscale_params.

**Architecture:** Nieuwe `voorlopige_aanslagen` table met FK naar `aangifte_documenten` + partial-unique-index actieve beschikking per (jaar, soort). Atomic upload-pipeline `process_voorlopige_aanslag_upload` (BEGIN IMMEDIATE: deactivate-old + insert-new + sync-fp). `services/va_parser.py` met pdftotext + regex (whitespace-genormaliseerd). `compute_va_tracker` blijft pure; nieuwe `load_va_tracker_summary` async-wrapper bevat datasource-fallback.

**Tech Stack:** Python 3.12, NiceGUI/Quasar (native pywebview), SQLite (raw SQL via aiosqlite, `?`-placeholders), pdftotext via subprocess (al in `import_/pdf_parser.py:extract_pdf_text`), pytest/pytest-asyncio. Spec: `docs/superpowers/specs/2026-05-06-va-tracker-drilldown-design.md` (LOCKED).

**Process:** Sprint H 4-layer review per task: implementer (opus) → Codex pre-commit → spec reviewer (opus) → code quality reviewer (opus). Direct-on-master pattern.

---

## File Structure

**Modify:**
- `database.py` — append migration 41 + add 4 CRUD helpers (`get_active_voorlopige_aanslag`, `process_voorlopige_aanslag_upload`, `clear_fiscale_params_va_for_jaar`, `delete_aangifte_document_with_va_cleanup`) + `get_va_betalingen_detail`
- `services/dashboard.py` — add `compute_va_termijnen_schedule`, `load_va_tracker_summary` async wrapper
- `pages/dashboard.py` — switch caller to `load_va_tracker_summary`
- `components/dashboard_widgets.py` — change `render_va_tile` click-handler to `/va-tracker/{jaar}`
- `pages/documenten.py` — extend upload-handler met parse-on-upload voor categorie='voorlopige_aanslag'
- `CLAUDE.md` — Sprint J VA-tracker drill-down sectie + sprint-state update

**Create:**
- `services/va_parser.py` — `parse_va_beschikking(pdf_path)` + `parse_va_beschikking_text(text)` + `ParsedBeschikking` dataclass + `VAParseError`
- `pages/va_tracker.py` — `/va-tracker/{jaar}` page
- `tests/test_va_parser.py` — 12 parser tests
- `tests/test_va_tracker_page.py` — 3 page/helper tests
- `tests/test_va_tracker_userflow.py` — 1 end-to-end test
- `tests/fixtures/va_beschikking_ib_2026_anon.txt` — geanonimiseerde pdftotext-output IB
- `tests/fixtures/va_beschikking_zvw_2026_anon.txt` — geanonimiseerde pdftotext-output ZVW

---

## Task 1: Migratie 41 + voorlopige_aanslagen table + CRUD helpers

> **Plan-amendment 2026-05-06 (Codex round-3, applied in commit `4d4859e`)**:
> - **`UNIQUE(document_id)` MUST be in migration 41** — anders silent multi-VA-per-doc invariant-break. Re-runs: niet wegoptimaliseren.
> - **`delete_aangifte_document_with_va_cleanup` MUST be single-tx atomic inline** — NIET delegate naar bestaande `delete_aangifte_document` met aparte `clear_fiscale_params_va_for_jaar` call. De delegate-pattern heeft een failure-window tussen commits waarin fp stale blijft als fp-clear faalt.
> - **`process_voorlopige_aanslag_upload` MUST validate document existence + categorie + jaar-match** binnen de transactie — voorkomt cross-year/non-VA stealth via foute document_id-arg.
> Zonder deze drie blijven Codex round-1+2+3 vangsten subtle herintroduceerbaar bij re-run.


**Files:**
- Modify: `database.py` MIGRATIONS list (append 41), add 4 CRUD helpers
- Test: `tests/test_db_queries.py` (7 nieuwe), `tests/test_year_locking.py` (2 nieuwe)

- [ ] **Step 1.1: Add migration 41**

In `database.py` `MIGRATIONS` list, append na laatste entry (mig 40):

```python
    (41, "add_voorlopige_aanslagen_table", [
        """CREATE TABLE voorlopige_aanslagen (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jaar INTEGER NOT NULL,
            soort TEXT NOT NULL CHECK (soort IN ('ib', 'zvw')),
            document_id INTEGER NOT NULL REFERENCES aangifte_documenten(id) ON DELETE CASCADE,
            aanslagnummer TEXT NOT NULL,
            dagtekening TEXT NOT NULL,
            bedrag REAL NOT NULL CHECK (bedrag >= 0),
            betalingskenmerk TEXT NOT NULL,
            termijnen INTEGER NOT NULL DEFAULT 11
                CHECK (termijnen BETWEEN 1 AND 12),
            is_active INTEGER NOT NULL DEFAULT 1
                CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            UNIQUE(aanslagnummer)
        )""",
        """CREATE UNIQUE INDEX idx_va_active
            ON voorlopige_aanslagen(jaar, soort)
            WHERE is_active = 1""",
    ]),
```

- [ ] **Step 1.2: Add CRUD helpers (alle 4)**

Append aan `database.py` na bestaande VA-related helpers (rond regel 2843):

```python
async def get_active_voorlopige_aanslag(
    db_path: Path = DB_PATH, jaar: int = 0, soort: str = '',
) -> dict | None:
    """Return active beschikking row als dict, None als geen actieve."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT * FROM voorlopige_aanslagen "
            "WHERE jaar = ? AND soort = ? AND is_active = 1",
            (jaar, soort),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return dict(row)


async def process_voorlopige_aanslag_upload(
    db_path: Path = DB_PATH, *,
    document_id: int,
    parsed,  # ParsedBeschikking — niet imported (services depends on db)
) -> dict:
    """Atomic upload-pipeline (Codex round-2 critical fix).

    Steps in BEGIN IMMEDIATE:
    1. assert_year_writable(parsed.jaar) — raise YearLockedError
    2. Check duplicate aanslagnummer — return {'action': 'skip'} idempotent
    3. SET is_active=0 op bestaande actieve rij voor (jaar, soort)
    4. INSERT nieuwe rij met is_active=1
    5. UPDATE fiscale_params voorlopige_aanslag_{betaald|zvw} + termijnen
    6. COMMIT (of ROLLBACK bij ANY exception)

    Returns: {'action': 'inserted'|'replaced'|'skip', 'beschikking_id': int}
    """
    await assert_year_writable(db_path, parsed.jaar)
    fp_field = ('voorlopige_aanslag_betaald' if parsed.soort == 'ib'
                else 'voorlopige_aanslag_zvw')
    termijnen_field = (f'voorlopige_aanslag_{parsed.soort}_termijnen')
    async with get_db_ctx(db_path) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            # Idempotency check
            cur = await conn.execute(
                "SELECT id FROM voorlopige_aanslagen WHERE aanslagnummer = ?",
                (parsed.aanslagnummer,),
            )
            existing = await cur.fetchone()
            if existing:
                await conn.execute("ROLLBACK")
                return {'action': 'skip', 'beschikking_id': existing['id']}

            # Check of er active row was → 'replaced' vs 'inserted'
            cur = await conn.execute(
                "SELECT id FROM voorlopige_aanslagen "
                "WHERE jaar = ? AND soort = ? AND is_active = 1",
                (parsed.jaar, parsed.soort),
            )
            old_active = await cur.fetchone()
            action = 'replaced' if old_active else 'inserted'

            # Deactivate oude
            if old_active:
                await conn.execute(
                    "UPDATE voorlopige_aanslagen SET is_active = 0 "
                    "WHERE id = ?", (old_active['id'],),
                )

            # Insert nieuwe
            cur = await conn.execute(
                """INSERT INTO voorlopige_aanslagen
                   (jaar, soort, document_id, aanslagnummer, dagtekening,
                    bedrag, betalingskenmerk, termijnen, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (parsed.jaar, parsed.soort, document_id,
                 parsed.aanslagnummer, parsed.dagtekening.isoformat(),
                 parsed.bedrag, parsed.betalingskenmerk, parsed.termijnen),
            )
            beschikking_id = cur.lastrowid

            # Sync fp — UPDATE alleen als row al bestaat (no auto-insert)
            await conn.execute(
                f"UPDATE fiscale_params SET {fp_field} = ?, "
                f"{termijnen_field} = ? WHERE jaar = ?",
                (parsed.bedrag, parsed.termijnen, parsed.jaar),
            )
            await conn.execute("COMMIT")
            return {'action': action, 'beschikking_id': beschikking_id}
        except Exception:
            await conn.execute("ROLLBACK")
            raise


async def clear_fiscale_params_va_for_jaar(
    db_path: Path = DB_PATH, jaar: int = 0, soort: str = '',
) -> None:
    """Reset voorlopige_aanslag_{betaald|zvw} + termijnen op default 0/11.
    Year-locked. Called by delete-hook als geen andere actieve beschikking
    voor (jaar, soort) overblijft.
    """
    await assert_year_writable(db_path, jaar)
    fp_field = ('voorlopige_aanslag_betaald' if soort == 'ib'
                else 'voorlopige_aanslag_zvw')
    termijnen_field = (f'voorlopige_aanslag_{soort}_termijnen')
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            f"UPDATE fiscale_params SET {fp_field} = 0, "
            f"{termijnen_field} = 11 WHERE jaar = ?",
            (jaar,),
        )
        await conn.commit()


async def delete_aangifte_document_with_va_cleanup(
    db_path: Path = DB_PATH, document_id: int = 0,
) -> None:
    """Wrapper: delete aangifte_document + clear fp als laatste VA-row weg.

    Year-locked (delegates naar bestaande delete_aangifte_document).
    Voor categorie='voorlopige_aanslag': na CASCADE-delete van VA-row,
    check of er nog andere actieve beschikking voor (jaar, soort) is.
    Zo nee → clear_fiscale_params_va_for_jaar.
    """
    # Lookup categorie + jaar + soort BEFORE delete (cascade vernietigt info)
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT ad.jaar AS doc_jaar, ad.categorie AS doc_categorie, "
            "va.soort AS va_soort, va.jaar AS va_jaar "
            "FROM aangifte_documenten ad "
            "LEFT JOIN voorlopige_aanslagen va ON va.document_id = ad.id "
            "WHERE ad.id = ?",
            (document_id,),
        )
        info = await cur.fetchone()

    # Delegate to existing delete (year-locked + CASCADE)
    await delete_aangifte_document(db_path, document_id)

    # Post-delete cleanup voor VA-categorie
    if info and info['doc_categorie'] == 'voorlopige_aanslag' and info['va_soort']:
        # Check of nog andere actieve VA voor (jaar, soort)
        remaining = await get_active_voorlopige_aanslag(
            db_path, info['va_jaar'], info['va_soort'])
        if remaining is None:
            await clear_fiscale_params_va_for_jaar(
                db_path, info['va_jaar'], info['va_soort'])
```

- [ ] **Step 1.3: Add `get_va_betalingen_detail`**

Append aan `database.py`:

```python
async def get_va_betalingen_detail(
    db_path: Path = DB_PATH, jaar: int = 0,
) -> list[dict]:
    """Detail bank-tx voor jaar — alle BD-rows met classification.

    Returns list of dict met: datum, bedrag, betalingskenmerk, omschrijving,
    classification ('ib_matched'|'zvw_matched'|'unmatched').
    Voor /va-tracker page detail-view.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT datum, ABS(bedrag) AS bedrag, betalingskenmerk,
                      omschrijving
               FROM banktransacties
               WHERE tegenrekening = ?
                 AND datum >= ? AND datum <= ?
                 AND bedrag < 0
               ORDER BY datum""",
            (BELASTINGDIENST_IBAN, f'{jaar}-01-01', f'{jaar}-12-31'),
        )
        rows = await cur.fetchall()

    result = []
    for row in rows:
        norm = _normalize_va_kenmerk(row['betalingskenmerk'])
        if len(norm) >= 12 and norm[10:12].isdigit():
            classification = ('zvw_matched' if int(norm[10:12]) >= 50
                              else 'ib_matched')
        else:
            classification = 'unmatched'
        result.append({
            'datum': row['datum'],
            'bedrag': row['bedrag'],
            'betalingskenmerk': row['betalingskenmerk'],
            'omschrijving': row['omschrijving'],
            'classification': classification,
        })
    return result
```

- [ ] **Step 1.4: Write 9 tests**

Append aan `tests/test_db_queries.py` 7 tests + `tests/test_year_locking.py` 2 tests. Tests dekken:
- Migratie schema, partial-unique-index, CHECK constraints
- process_voorlopige_aanslag_upload happy/replace/skip + fp-sync
- get_active_voorlopige_aanslag returns active only
- get_va_betalingen_detail classifies correctly + unmatched zichtbaar
- delete_aangifte_document_with_va_cleanup clears fp na last delete
- Year-lock: process + delete rejected in definitief

- [ ] **Step 1.5: Run tests + Codex pre-commit + commit**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py tests/test_year_locking.py -v
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -x --tb=short 2>&1 | tail -5
# Codex review:
git diff > /tmp/t11_diff.patch
echo "---" >> /tmp/t11_diff.patch
echo "Beoordeel T1.1 — schema, partial unique index, atomic process_voorlopige_aanslag_upload (BEGIN IMMEDIATE, idempotency, rollback), delete-hook met fp-clear, year-lock op alle paden. Spec: docs/superpowers/specs/2026-05-06-va-tracker-drilldown-design.md §1+§3. Max 400 woorden." >> /tmp/t11_diff.patch
cat /tmp/t11_diff.patch | env -u OPENAI_API_KEY codex exec --sandbox read-only -c model_reasoning_effort=medium - > /tmp/t11_codex.md
# After Codex clean:
git add database.py tests/test_db_queries.py tests/test_year_locking.py
git commit -m "feat(sprint-j): T1.1 mig 41 voorlopige_aanslagen + atomic upload pipeline + delete-cleanup"
```

---

## Task 2: services/va_parser.py + 12 tests + geanonimiseerde fixtures

**Files:**
- Create: `services/va_parser.py`
- Create: `tests/test_va_parser.py`
- Create: `tests/fixtures/va_beschikking_ib_2026_anon.txt` + `_zvw_2026_anon.txt`

- [ ] **Step 2.1: Create geanonimiseerde fixtures**

Generate via:
```bash
mkdir -p tests/fixtures
pdftotext -layout "/Users/macbookpro_ronald/Library/Application Support/Boekhouding/data/aangifte/2026/voorlopige_aanslag/26_VoorlopigeAanslag_Inkomstenbelasting.pdf" - > /tmp/raw_ib.txt
# Edit /tmp/raw_ib.txt → vervang naam/adres met FICTIEF en aanslagnummer met 9999.99.999.H.60.01
cp /tmp/raw_ib.txt tests/fixtures/va_beschikking_ib_2026_anon.txt
# idem ZVW: 9999.99.999.W.60.01.4
```

Belangrijk: behoud regex-relevante substrings exact (Aanslagnummer label, Te betalen `:` blok, Betalingskenmerk format, "11 gelijke maandelijkse termijnen", Dagtekening format). Vervang alleen naam, adres, BSN-prefix in aanslagnummer (bv `1244.12.646` → `9999.99.999`).

- [ ] **Step 2.2: Create services/va_parser.py**

```python
"""VA-beschikking PDF parser (Sprint J).

Pure helper — geen NiceGUI, geen DB. Parses Belastingdienst voorlopige
aanslag PDF (IB of ZVW) naar ParsedBeschikking dataclass.

Hergebruikt import_/pdf_parser.extract_pdf_text voor pdftotext-subprocess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal


class VAParseError(ValueError):
    """Raised when critical fields cannot be extracted from PDF."""


@dataclass(frozen=True)
class ParsedBeschikking:
    jaar: int
    soort: Literal['ib', 'zvw']
    aanslagnummer: str
    dagtekening: date
    bedrag: float
    betalingskenmerk: str       # 16-digit genormaliseerd
    termijnen: int


_DUTCH_MAANDEN_REVERSE = {
    'januari': 1, 'februari': 2, 'maart': 3, 'april': 4, 'mei': 5,
    'juni': 6, 'juli': 7, 'augustus': 8, 'september': 9, 'oktober': 10,
    'november': 11, 'december': 12,
}

_AANSLAG_RE = re.compile(
    r'\b(\d{4}\.\d{2}\.\d{3}\.[HW]\.\d{2}\.\d{2}(?:\.\d+)?)\b')
_JAAR_RE = re.compile(r'Voorlopige aanslag (\d{4})\b')
_DAGTEKENING_RE = re.compile(r'Dagtekening (\d{1,2}) ([a-zA-Z]+) (\d{4})')
_BEDRAG_RE = re.compile(
    r'Te betalen\s*:\s*€\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?)')
_KENMERK_RE = re.compile(r'Betalingskenmerk\s*:?\s*([0-9 ]{16,24})')
_TERMIJNEN_RE = re.compile(r'(\d+) (?:gelijke )?maandelijkse? termijnen')


def _normalize_kenmerk(k: str) -> str:
    return re.sub(r'[^0-9]', '', k or '')


def _parse_dutch_date(day: str, maand: str, year: str) -> date:
    maand_num = _DUTCH_MAANDEN_REVERSE.get(maand.lower())
    if maand_num is None:
        raise VAParseError(f'Onbekende maand: {maand}')
    return date(int(year), maand_num, int(day))


def _parse_dutch_bedrag(s: str) -> float:
    """'30.670' → 30670.0 ; '30.670,50' → 30670.50"""
    # Punt = thousands separator, komma = decimal
    s = s.replace('.', '').replace(',', '.')
    return float(s)


def parse_va_beschikking(pdf_path: Path) -> ParsedBeschikking:
    """Parse VA beschikking PDF → ParsedBeschikking.

    Raises VAParseError op missing critical field of pdftotext-fout.
    """
    from import_.pdf_parser import extract_pdf_text
    try:
        raw_text = extract_pdf_text(pdf_path)
    except Exception as e:
        raise VAParseError(f'pdftotext fout: {e}') from e
    return parse_va_beschikking_text(raw_text)


def parse_va_beschikking_text(text: str) -> ParsedBeschikking:
    """Parse VA-beschikking uit pdftotext-output. Pure function — testbaar
    zonder PDF.
    """
    # Whitespace-normalize (incl newlines) — multi-line fields worden 1-line
    norm = re.sub(r'\s+', ' ', text)

    # Aanslagnummer — critical
    m = _AANSLAG_RE.search(norm)
    if not m:
        raise VAParseError('Aanslagnummer niet gevonden')
    aanslagnummer = m.group(1)

    # Soort uit suffix
    suffix = aanslagnummer.split('.')[3]  # 'H' or 'W'
    soort: Literal['ib', 'zvw'] = 'ib' if suffix == 'H' else 'zvw'

    # Jaar — critical
    m = _JAAR_RE.search(norm)
    if not m:
        raise VAParseError('Jaar niet gevonden')
    jaar = int(m.group(1))

    # Dagtekening — critical
    m = _DAGTEKENING_RE.search(norm)
    if not m:
        raise VAParseError('Dagtekening niet gevonden')
    dagtekening = _parse_dutch_date(m.group(1), m.group(2), m.group(3))

    # Bedrag — critical
    m = _BEDRAG_RE.search(norm)
    if not m:
        raise VAParseError('Bedrag niet gevonden')
    bedrag = _parse_dutch_bedrag(m.group(1))

    # Kenmerk — critical
    m = _KENMERK_RE.search(norm)
    if not m:
        raise VAParseError('Betalingskenmerk niet gevonden')
    kenmerk = _normalize_kenmerk(m.group(1))
    if len(kenmerk) != 16:
        raise VAParseError(f'Kenmerk niet 16 digits: {kenmerk}')

    # Termijnen — optional, default 11
    m = _TERMIJNEN_RE.search(norm)
    termijnen = int(m.group(1)) if m else 11
    if not (1 <= termijnen <= 12):
        termijnen = 11

    return ParsedBeschikking(
        jaar=jaar, soort=soort, aanslagnummer=aanslagnummer,
        dagtekening=dagtekening, bedrag=bedrag,
        betalingskenmerk=kenmerk, termijnen=termijnen,
    )
```

- [ ] **Step 2.3: Write 12 parser tests**

Tests in `tests/test_va_parser.py`:
- Real fixture IB → assert all fields
- Real fixture ZVW → assert all fields + soort='zvw'
- Type detect H/W
- Bedrag dutch thousands `30.670` → 30670.0
- Bedrag with decimals `30.670,50` → 30670.50
- Dagtekening dutch month
- Kenmerk strips spaces
- Termijnen default 11 wanneer regex faalt
- Missing aanslagnummer → VAParseError
- Missing bedrag → VAParseError
- Kenmerk niet 16 digits → VAParseError
- Onbekende maand → VAParseError

- [ ] **Step 2.4: Run + Codex + commit**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_va_parser.py -v
# Codex review op T1.2 diff
git add services/va_parser.py tests/test_va_parser.py tests/fixtures/
git commit -m "feat(sprint-j): T1.2 services/va_parser + 12 tests + geanonimiseerde 2026 fixtures"
```

---

## Task 3: /documenten upload-flow extended + 1 userflow test

**Files:**
- Modify: `pages/documenten.py` (upload-handler)
- Test: `tests/test_va_tracker_userflow.py` (NEW)

- [ ] **Step 3.1: Extend upload-handler**

In `pages/documenten.py`, in de upload-handler na bestaande `save_aangifte_document(...)` call:

```python
# Sprint J: parse-on-upload voor VA beschikkingen
if categorie == 'voorlopige_aanslag':
    from services.va_parser import parse_va_beschikking, VAParseError
    from database import process_voorlopige_aanslag_upload, delete_aangifte_document_with_va_cleanup
    import asyncio

    try:
        parsed = await asyncio.to_thread(parse_va_beschikking, pdf_path)
    except VAParseError as err:
        ui.notify(
            f'PDF opgeslagen, automatisch lezen mislukt: {err}. '
            f'Vul handmatig in via /aangifte.',
            type='warning', timeout=8000,
        )
        return

    # Mismatch-check (UI-laag, vóór atomic insert)
    fp = await get_fiscale_params(jaar=parsed.jaar)
    existing_bedrag = (fp.voorlopige_aanslag_betaald if parsed.soort == 'ib'
                      else fp.voorlopige_aanslag_zvw) if fp else 0
    if existing_bedrag and abs(existing_bedrag - parsed.bedrag) > 1:
        # Confirm-dialog — implementatie volgt bestaand pattern
        ok = await _confirm_pdf_overrides_manual(parsed.bedrag, existing_bedrag)
        if not ok:
            return  # behoud handmatige waarde

    # Atomic DB-pipeline
    try:
        result = await process_voorlopige_aanslag_upload(
            document_id=document_id, parsed=parsed,
        )
    except YearLockedError as e:
        ui.notify(str(e), type='warning')
        return

    if result['action'] == 'skip':
        # Idempotent re-upload: opruim duplicate document
        await delete_aangifte_document_with_va_cleanup(document_id)
        ui.notify('Beschikking al verwerkt — duplicate upload opgeruimd',
                  type='info')
    else:
        action_label = 'vervangen' if result['action'] == 'replaced' else 'bijgewerkt'
        ui.notify(
            f"VA {parsed.soort.upper()} {action_label} naar "
            f"€{parsed.bedrag:.0f}, {parsed.termijnen} termijnen",
            type='positive')
    refresh_table()
```

- [ ] **Step 3.2: Implement `_confirm_pdf_overrides_manual` helper**

In `pages/documenten.py` toevoegen:

```python
async def _confirm_pdf_overrides_manual(pdf_bedrag: float,
                                        manual_bedrag: float) -> bool:
    """Toon confirm-dialog als PDF-bedrag afwijkt van handmatige fp-waarde.
    Returns True als user OK kiest (PDF wint), False als annuleert."""
    confirmed = asyncio.Future()
    with ui.dialog() as dlg, ui.card():
        ui.label(f'PDF zegt €{pdf_bedrag:.0f}, je had handmatig '
                 f'€{manual_bedrag:.0f}.').classes('text-h6')
        ui.label('PDF-waarde gebruiken?').classes('text-sm')
        with ui.row():
            ui.button('Annuleren', on_click=lambda: (dlg.close(),
                      confirmed.set_result(False))).props('flat')
            ui.button('PDF gebruiken', on_click=lambda: (dlg.close(),
                      confirmed.set_result(True))).props('color=primary')
    dlg.open()
    return await confirmed
```

- [ ] **Step 3.3: Write end-to-end userflow test**

`tests/test_va_tracker_userflow.py`:

```python
"""End-to-end userflow test (Codex round-2 should-fix)."""
import pytest
from datetime import date
from services.va_parser import ParsedBeschikking
from database import (
    process_voorlopige_aanslag_upload,
    delete_aangifte_document_with_va_cleanup,
    get_active_voorlopige_aanslag, get_fiscale_params,
    add_aangifte_document, upsert_fiscale_params, get_db_ctx,
)


@pytest.mark.asyncio
async def test_va_userflow_upload_parse_sync_dashboard_delete_clears_fp(db):
    """Full lifecycle: upload → parse → sync → dashboard → delete → clear."""
    # 1. Seed fp + add aangifte_document
    await upsert_fiscale_params(
        db_path=db, jaar=2026,
        zelfstandigenaftrek=0, mkb_vrijstelling_pct=0,
        kia_ondergrens=0, kia_bovengrens=0, kia_pct=0,
        km_tarief=0.23, schijf1_grens=0, schijf1_pct=0,
        schijf2_grens=0, schijf2_pct=0, schijf3_pct=0,
        ahk_max=0, ahk_afbouw_pct=0, ahk_drempel=0, ak_max=0,
        zvw_pct=0, zvw_max_grondslag=0,
    )
    document_id = await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking', bestandspad='/tmp/fake.pdf',
        bestandsnaam='test.pdf',
    )

    # 2. process_voorlopige_aanslag_upload met parsed data
    parsed = ParsedBeschikking(
        jaar=2026, soort='ib', aanslagnummer='9999.99.999.H.60.01',
        dagtekening=date(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='0124412647060001', termijnen=11,
    )
    result = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=document_id, parsed=parsed,
    )
    assert result['action'] == 'inserted'

    # 3. Active row + fp-sync
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active is not None
    assert active['bedrag'] == 30670.0
    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_betaald == 30670.0
    assert fp.voorlopige_aanslag_ib_termijnen == 11

    # 4. Delete + cleanup
    await delete_aangifte_document_with_va_cleanup(db, document_id)
    active_after = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active_after is None
    fp_after = await get_fiscale_params(db, 2026)
    assert fp_after.voorlopige_aanslag_betaald == 0
    assert fp_after.voorlopige_aanslag_ib_termijnen == 11
```

- [ ] **Step 3.4: Run + Codex + commit**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_va_tracker_userflow.py -v
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -x --tb=short 2>&1 | tail -5
git add pages/documenten.py tests/test_va_tracker_userflow.py
git commit -m "feat(sprint-j): T1.3 /documenten parse-on-upload + mismatch-confirm + end-to-end test"
```

---

## Task 4: /va-tracker page + helpers + tile click migration

**Files:**
- Create: `pages/va_tracker.py`
- Modify: `services/dashboard.py` (add `compute_va_termijnen_schedule` + `load_va_tracker_summary`)
- Modify: `pages/dashboard.py` (use `load_va_tracker_summary`)
- Modify: `components/dashboard_widgets.py` (`render_va_tile` click target)
- Test: `tests/test_va_tracker_page.py`

- [ ] **Step 4.1: Add `compute_va_termijnen_schedule` + `load_va_tracker_summary`**

In `services/dashboard.py`:

```python
@dataclass(frozen=True)
class TermijnRow:
    maand: int
    vervaldatum: date
    bedrag: float
    status: Literal['betaald', 'verwacht', 'toekomst']
    betaald_op: date | None
    betaald_bedrag: float | None


def compute_va_termijnen_schedule(
    *,
    bedrag: float, termijnen: int, jaar: int,
    bank_tx: list[dict],  # filtered op kenmerk + soort
    today: date,
) -> list[TermijnRow]:
    """Generate per-termijn schedule met paid-status uit bank-tx."""
    eerste_maand = 13 - termijnen
    termijn_bedrag = bedrag / termijnen if termijnen > 0 else 0
    rows = []
    bank_by_month = {}
    for tx in bank_tx:
        tx_date = date.fromisoformat(tx['datum'])
        if tx_date.year == jaar:
            bank_by_month.setdefault(tx_date.month, []).append(tx)

    for offset in range(termijnen):
        maand = eerste_maand + offset
        if maand > 12:
            break
        vervaldatum = _last_day_of_month(jaar, maand)
        match = bank_by_month.get(maand)
        if match:
            status = 'betaald'
            betaald_op = date.fromisoformat(match[0]['datum'])
            betaald_bedrag = match[0]['bedrag']
        elif vervaldatum < today:
            status = 'verwacht'
            betaald_op = None
            betaald_bedrag = None
        else:
            status = 'toekomst'
            betaald_op = None
            betaald_bedrag = None
        rows.append(TermijnRow(maand, vervaldatum, termijn_bedrag,
                               status, betaald_op, betaald_bedrag))
    return rows


async def load_va_tracker_summary(
    db_path, jaar: int, today: date,
) -> 'VATrackSummary':
    """Async wrapper — fetch beschikkingen + va_data → compute_va_tracker.
    Datasource fall-through: active beschikking > fp-handmatig."""
    from database import (
        get_active_voorlopige_aanslag, get_va_betalingen, get_fiscale_params,
    )
    fp = await get_fiscale_params(db_path, jaar)
    ib_b = await get_active_voorlopige_aanslag(db_path, jaar, 'ib')
    zvw_b = await get_active_voorlopige_aanslag(db_path, jaar, 'zvw')
    va_data = await get_va_betalingen(db_path, jaar)

    ib_verplicht = (ib_b['bedrag'] if ib_b
                    else (fp.voorlopige_aanslag_betaald if fp else 0))
    zvw_verplicht = (zvw_b['bedrag'] if zvw_b
                     else (fp.voorlopige_aanslag_zvw if fp else 0))
    ib_termijnen = (ib_b['termijnen'] if ib_b
                    else (fp.voorlopige_aanslag_ib_termijnen if fp else 11))
    zvw_termijnen = (zvw_b['termijnen'] if zvw_b
                     else (fp.voorlopige_aanslag_zvw_termijnen if fp else 11))

    return compute_va_tracker(
        jaar=jaar, va_data=va_data,
        ib_verplicht=ib_verplicht, zvw_verplicht=zvw_verplicht,
        ib_termijnen=ib_termijnen, zvw_termijnen=zvw_termijnen,
        today=today,
    )
```

- [ ] **Step 4.2: Update pages/dashboard.py to use load_va_tracker_summary**

Vervang in `pages/dashboard.py` Card 3 block:

```python
# Card 3: Voorlopige aanslag — Sprint J caller-migration
from services.dashboard import load_va_tracker_summary
from components.dashboard_widgets import render_va_tile

va_summary = await load_va_tracker_summary(DB_PATH, jaar, date.today())
render_va_tile(va_summary, jaar=jaar)
```

- [ ] **Step 4.3: Update render_va_tile click-target**

In `components/dashboard_widgets.py:render_va_tile`:

```python
.on('click', lambda: ui.navigate.to(f'/va-tracker/{jaar}')):
```

- [ ] **Step 4.4: Create pages/va_tracker.py**

Page met:
- `@ui.page('/va-tracker/{jaar}')` async def va_tracker_page(jaar: int)
- `create_layout('Voorlopige aanslag', '/va-tracker')`
- 2 collapsible sections (IB + ZVW) — gebruik `ui.expansion`
- Per sectie: actieve beschikking-card + termijnen-overzicht + bank-tx tabel (alleen `*_matched` voor die soort)
- Unmatched bank-tx aparte sectie onderaan
- "Geen beschikking" fallback met deep-link "Upload via /documenten"
- Year-locked → upload knoppen disabled

- [ ] **Step 4.5: Write 3 tests**

`tests/test_va_tracker_page.py`:
- `test_compute_va_termijnen_schedule_basic` — 11 termijnen feb-dec, 2 paid
- `test_load_va_tracker_summary_uses_active_beschikking` — beschikking wins over fp
- `test_load_va_tracker_summary_falls_back_to_fp` — geen beschikking → fp values

- [ ] **Step 4.6: Run + smoke-test + Codex + commit**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -x --tb=short 2>&1 | tail -5
# Manual smoke: open dashboard, click VA-tile, verify /va-tracker page renders
git add services/dashboard.py pages/dashboard.py pages/va_tracker.py components/dashboard_widgets.py tests/test_va_tracker_page.py
git commit -m "feat(sprint-j): T1.4 /va-tracker page + termijnen-schedule + load_va_tracker_summary wrapper"
```

---

## Task 5: CLAUDE.md update + spec/plan commit + post-merge audit

- [ ] **Step 5.1: Update CLAUDE.md**

§ Recente sprint-state: Sprint J update (test count, new helpers, new page).
§ Database: voeg `voorlopige_aanslagen` tabel toe aan tabel-list, mig 41.
§ Domeinkennis fiscaal: voeg sectie "VA-tracker drill-down (Sprint J)" toe met PDF-format quirks (BD-format spec, kenmerk-positie, termijnen-default 11).

- [ ] **Step 5.2: Commit CLAUDE.md + spec + plan**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-05-06-va-tracker-drilldown-design.md docs/superpowers/plans/2026-05-06-va-tracker-drilldown-sprint-j.md
git commit -m "docs(sprint-j): VA-tracker drill-down spec + plan + CLAUDE.md update"
```

- [ ] **Step 5.3: Post-merge audit (Codex + code-reviewer parallel)**

```bash
git diff fc18da3..HEAD -- ':!docs/' > /tmp/sprint_j_code_diff.patch
# Codex audit:
echo "Sprint J post-merge audit op cumulative diff. Spec: docs/superpowers/specs/2026-05-06-va-tracker-drilldown-design.md. Focus: caller-migration completeness, atomic upload bewijs onder concurrent simulate, cascade-delete + fp-clear gat, /va-tracker page edge-cases, test-coverage gaps." >> /tmp/sprint_j_code_diff.patch
cat /tmp/sprint_j_code_diff.patch | env -u OPENAI_API_KEY codex exec --sandbox read-only -c model_reasoning_effort=medium - > /tmp/sprint_j_audit.md
```

Plus parallel code-reviewer subagent. Verwerk findings in follow-up commit indien nodig.
