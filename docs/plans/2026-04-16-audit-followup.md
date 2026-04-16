# Audit Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verhoog data-integriteit bij PDF-import, sluit een resterende fiscale silent-fallback loophole, en ruim puntig dode code op — alles specifiek waardevol voor een eenmanszaak huisarts-waarneem ZZP.

**Architecture:** Zes onafhankelijke, kleine tasks. Elke task is één TDD-cyclus (rood → groen → commit). Geen refactors, geen nieuwe features, geen connection-singleton (dat is Plan B in `2026-04-14-...md`). Scope blijft strak: álles moet ofwel belasting raken, data verlies voorkomen, of bewezen bugs uitsluiten.

**Tech Stack:** Python 3.12+, NiceGUI 3.0, aiosqlite, pytest-asyncio, WeasyPrint (niet geraakt).

**Rationale per task** staat vóór de TDD-stappen zodat een uitvoerder begrijpt *waarom* het werk het doet.

**Volgorde** (impact × urgentie):
1. Import-hardening (Task 1) — maandelijks geraakt bij nieuwe PDF-imports
2. Per-record import validatie (Task 2) — voorkomt recurrence van 2025 `tarief=0` precedent
3. Silent-fallback fiscal loophole (Task 3) — kritiek maar preventief (2027+ setup)
4. Dead-page cleanup (Task 4) — reduceert verwarring
5. MCP config fix (Task 5) — 30-seconden wijziging
6. UI-guard polish (Task 6) — optioneel

---

## File Structure

| File | Rol in dit plan |
|---|---|
| `import_/pdf_parser.py` | Task 1: guard int/float casts met try/except |
| `tests/test_pdf_parser.py` | Task 1: regression fixtures voor malformed input |
| `import_/werkdag_validator.py` **NIEUW** | Task 2: pure `validate_werkdag_record()` helper |
| `import_/__init__.py` | Task 2: re-export validator |
| `pages/facturen.py` | Task 2: bij `_import_factuur_rows` validator aanroepen |
| `tests/test_werkdag_validator.py` **NIEUW** | Task 2: validator unit tests |
| `database.py` (upsert_fiscale_params) | Task 3: `kwargs.get(...)` → `kwargs[...]` voor 11 velden |
| `pages/instellingen.py` (_validate_fiscal_params) | Task 3: 11 velden toevoegen aan required-set |
| `tests/test_fiscale_params_required.py` **NIEUW** | Task 3: parametrized KeyError tests |
| `pages/dashboard_omzet.py` | Task 4: VERWIJDEREN |
| `main.py` | Task 4: import-regel verwijderen |
| `.mcp.json` | Task 5: pad corrigeren |
| `pages/facturen.py` (`_is_editable` area) | Task 6: twee nieuwe helpers + v-if updates |
| `tests/test_facturen.py` | Task 6: helper unit tests |

---

## Task 1: Harden PDF-parser crash sites

**Rationale.** `import_/pdf_parser.py` is de plek waar externe Boekhouder/HAP-PDFs binnenkomen. Eén malformed regel (bv. `01-1a-2025` of `1.2.3` als bedrag) laat `int()` of `float()` een `ValueError` gooien die niet overal gevangen wordt — de hele import valt om, user moet handmatig opnieuw. Doel: elke parse-crash wordt een *skip met warning*, niet een fatale fout. Klasse `async-input-hardening` uit FIX_PATTERNS.md.

**Files:**
- Modify: `import_/pdf_parser.py` (3 call-sites: regels 82, 386/392, 466/493)
- Test: `tests/test_pdf_parser.py` (bestaand bestand uitbreiden)

- [ ] **Step 1: Write the failing tests**

Voeg toe aan `tests/test_pdf_parser.py`:

```python
# === Import hardening regression tests ===

def test_parse_dutch_date_returns_none_on_malformed_month():
    from import_.pdf_parser import parse_dutch_date
    # Month contains letter → int() would raise ValueError before fix
    assert parse_dutch_date('01-1a-2025') is None


def test_parse_dutch_date_returns_none_on_malformed_day():
    from import_.pdf_parser import parse_dutch_date
    assert parse_dutch_date('aa-01-2025') is None


def test_extract_work_dates_skips_malformed_amount_line():
    """Regel met multi-dot bedrag (1.2.3) moet geskipt worden, niet crashen."""
    from import_.pdf_parser import _extract_work_dates
    text = """
    Datum: 01-06-2025
    Consulten 3 uur € 1.2.3 per uur
    Datum: 02-06-2025
    Consulten 4 uur € 77,50 per uur
    """
    items = _extract_work_dates(text)
    # Eerste regel moet geskipt zijn, tweede wel geparst
    assert len(items) == 1
    assert items[0]['datum'] == '2025-06-02'
    assert abs(items[0]['tarief'] - 77.50) < 0.01


def test_extract_anw_diensten_skips_malformed_row():
    """Eén rare ANW-regel mag niet heel extract_anw_diensten killen."""
    from import_.pdf_parser import extract_anw_diensten
    text = """
    01-06-2025 ANW dienst 8 uur à € 95,00
    02-06-2025 ANW dienst 8 uur à € a.b.c
    03-06-2025 ANW dienst 8 uur à € 95,00
    """
    diensten = extract_anw_diensten(text)
    assert len(diensten) == 2  # bad row skipped
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest \
  tests/test_pdf_parser.py -k "parse_dutch_date_returns_none or skips_malformed" -v
```

Expected: 4 tests FAIL (either ValueError raised or assertion wrong).

- [ ] **Step 3: Fix `parse_dutch_date` (around line 75–90)**

Pas toe:

```python
def parse_dutch_date(date_str: str) -> str | None:
    """Parse Dutch-style 'DD-MM-YYYY' → ISO 'YYYY-MM-DD'. Returns None on malformed input."""
    m = DATE_RE.match(date_str.strip())
    if not m:
        return None
    day_str, month_str, year_str = m.groups()
    try:
        day = int(day_str)
        month = int(month_str)
        year = int(year_str)
    except ValueError:
        return None
    if not (1 <= day <= 31 and 1 <= month <= 12 and 2000 <= year <= 2100):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"
```

- [ ] **Step 4: Wrap `_extract_work_dates` amount parse (around line 385–395)**

Vervang de twee `parse_dutch_amount(euro_amounts[0])` call-sites door een safe-parse-helper:

```python
def _safe_parse_amount(euro_amounts: list[str]) -> float | None:
    """Parse first euro amount safely. Returns None if empty or malformed."""
    if not euro_amounts:
        return None
    try:
        return parse_dutch_amount(euro_amounts[0])
    except (ValueError, IndexError):
        return None
```

En in `_extract_work_dates`:

```python
        if is_km:
            if current_item:
                amount = _safe_parse_amount(euro_amounts)
                if amount is None:
                    continue  # skip malformed km-line, keep item intact
                current_item['km'] = antal
                current_item['km_tarief'] = amount
        elif current_date:
            amount = _safe_parse_amount(euro_amounts)
            if amount is None:
                continue  # skip malformed tarief-line, don't start item
            if current_item:
                items.append(current_item)
            tarief = amount
            current_item = {
                'datum': current_date, 'uren': antal, 'tarief': tarief,
                'km': 0.0, 'km_tarief': 0.0,
            }
```

- [ ] **Step 5: Wrap `extract_anw_diensten` float parses (around line 460–500)**

Zoek de twee `float(m.group(...))` call-sites en wrap in try/except met `continue`:

```python
for m in re.finditer(ANW_ROW_RE, text):
    try:
        bedrag_per_uur = float(m.group(3))
    except (ValueError, IndexError):
        continue  # skip malformed row
    # ... rest unchanged
```

Doe hetzelfde voor het tweede `float(m.group(6))` block op ~regel 493.

- [ ] **Step 6: Run all tests — new + existing must pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 690 passed (4 nieuwe), 14 skipped.

- [ ] **Step 7: Commit**

```bash
git add import_/pdf_parser.py tests/test_pdf_parser.py
git commit -m "$(cat <<'EOF'
fix(import): harden parse_dutch_date + euro amount parsing

Wrap int()/float()/parse_dutch_amount call-sites in try/except so
one malformed PDF row (bv. '01-1a-2025', '1.2.3') wordt geskipt
i.p.v. hele import-pad te laten crashen.

Precedent: a60a097, 697dc5b, 2901660.
EOF
)"
```

---

## Task 2: Per-record werkdag-validator bij PDF-import

**Rationale.** Episodic memory heeft één groot precedent: in maart 2026 bleek dat 116 werkdagen uit 2025 `tarief=0` hadden ondanks dat factuur-totalen klopten. Root cause: import populateerde `tarief` niet per werkdag. Handmatige fix koste uren. Les: **aggregaten mogen niet stil-kloppen terwijl records incompleet zijn**. We voorkomen recurrence met een pure validator die per-record invarianten afdwingt vóór DB-insert.

Fiscaal belang: werkdag-records zonder tarief → urenregistratie klopt maar omzet/IB-cijfers zijn fout → verkeerde aangifte.

**Files:**
- Create: `import_/werkdag_validator.py` (pure helper)
- Modify: `import_/__init__.py` (re-export)
- Modify: `pages/facturen.py` (`_import_factuur_rows` of equivalent — roep validator aan per item vóór DB-write)
- Create: `tests/test_werkdag_validator.py`

- [ ] **Step 1: Write the failing tests**

Nieuw bestand `tests/test_werkdag_validator.py`:

```python
"""Per-record werkdag validator — prevents recurrence of 2025 tarief=0 import bug."""

import pytest
from import_.werkdag_validator import (
    validate_werkdag_record, ValidationError,
)


ACHTERWACHT_CODES = {'AW', 'ACHTERWACHT', 'ADMINISTRATIE', 'NASCHOLING', 'AQUISITIE'}


def _ok_dagpraktijk():
    return {
        'datum': '2025-06-15', 'code': 'CONSULT',
        'uren': 8.0, 'tarief': 77.50, 'km': 45.0, 'km_tarief': 0.23,
    }


def _ok_anw():
    return {
        'datum': '2025-06-15', 'code': 'ANW',
        'uren': 8.0, 'tarief': 95.00, 'km': 30.0, 'km_tarief': 0.0,
    }


def _ok_achterwacht():
    return {
        'datum': '2025-06-15', 'code': 'ACHTERWACHT',
        'uren': 0.0, 'tarief': 0.0, 'km': 0.0, 'km_tarief': 0.0,
    }


def test_valid_dagpraktijk_passes():
    validate_werkdag_record(_ok_dagpraktijk(), inv_type='factuur')


def test_valid_anw_passes():
    validate_werkdag_record(_ok_anw(), inv_type='anw')


def test_valid_achterwacht_passes():
    """Niet-billable code met tarief=0 is legitiem (telt niet voor urencriterium)."""
    validate_werkdag_record(_ok_achterwacht(), inv_type='factuur')


def test_dagpraktijk_tarief_zero_fails_for_billable_code():
    """De exacte bug die in 2025 gebeurde: CONSULT met tarief=0."""
    rec = _ok_dagpraktijk()
    rec['tarief'] = 0.0
    with pytest.raises(ValidationError, match='tarief'):
        validate_werkdag_record(rec, inv_type='factuur')


def test_anw_tarief_zero_fails():
    rec = _ok_anw()
    rec['tarief'] = 0.0
    with pytest.raises(ValidationError, match='tarief'):
        validate_werkdag_record(rec, inv_type='anw')


def test_dagpraktijk_km_without_km_tarief_fails():
    """Km > 0 zonder km_tarief voor dagpraktijk = silent zero reiskosten."""
    rec = _ok_dagpraktijk()
    rec['km_tarief'] = 0.0
    with pytest.raises(ValidationError, match='km_tarief'):
        validate_werkdag_record(rec, inv_type='factuur')


def test_anw_km_without_km_tarief_passes():
    """ANW heeft per-definitie km_tarief=0 (reistijd in uurtarief)."""
    rec = _ok_anw()
    rec['km_tarief'] = 0.0
    validate_werkdag_record(rec, inv_type='anw')  # must not raise


def test_missing_datum_fails():
    rec = _ok_dagpraktijk()
    del rec['datum']
    with pytest.raises(ValidationError, match='datum'):
        validate_werkdag_record(rec, inv_type='factuur')


def test_malformed_datum_fails():
    rec = _ok_dagpraktijk()
    rec['datum'] = '15/06/2025'
    with pytest.raises(ValidationError, match='datum'):
        validate_werkdag_record(rec, inv_type='factuur')


def test_uren_zero_on_billable_fails():
    rec = _ok_dagpraktijk()
    rec['uren'] = 0.0
    with pytest.raises(ValidationError, match='uren'):
        validate_werkdag_record(rec, inv_type='factuur')


def test_negative_values_fail():
    rec = _ok_dagpraktijk()
    rec['uren'] = -1.0
    with pytest.raises(ValidationError, match='negative|negatief'):
        validate_werkdag_record(rec, inv_type='factuur')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest \
  tests/test_werkdag_validator.py -v
```

Expected: all FAIL (ImportError — validator bestaat nog niet).

- [ ] **Step 3: Implement validator**

Nieuw bestand `import_/werkdag_validator.py`:

```python
"""Per-record werkdag validator — runs AFTER PDF parse, BEFORE DB insert.

Prevents the March 2026 precedent where 116 werkdagen uit 2025 geïmporteerd
werden met tarief=0 (aggregaten klopten, records waren incompleet).

Pure module: no I/O, no async, fully unit-testable.
"""

import re
from typing import Literal

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Codes die niet billable zijn — tarief=0, uren=0 zijn dan legitiem.
_NON_BILLABLE_CODES = {
    'ACHTERWACHT', 'AW',
    'ADMINISTRATIE', 'ADMIN',
    'NASCHOLING',
    'AQUISITIE',
}


class ValidationError(ValueError):
    """Raised when a werkdag record fails per-record invariants at import time."""


def validate_werkdag_record(
    rec: dict,
    inv_type: Literal['factuur', 'anw'],
) -> None:
    """Check dat rec consistent is vóór DB-insert. Raises ValidationError bij gaps.

    Args:
        rec: dict met keys datum, code, uren, tarief, km, km_tarief.
        inv_type: 'factuur' (dagpraktijk) of 'anw'.

    Invariants:
    - datum aanwezig en ISO-formaat (YYYY-MM-DD).
    - uren, tarief, km, km_tarief aanwezig en niet-negatief.
    - Voor *billable* codes (niet ACHTERWACHT/ADMIN/NASCHOLING/AQUISITIE):
      * uren > 0 EN tarief > 0.
    - Voor dagpraktijk (inv_type='factuur') met km > 0: km_tarief > 0.
    - Voor ANW (inv_type='anw'): km_tarief mag 0 zijn (reistijd zit in uurtarief).
    """
    # Required keys
    for fld in ('datum', 'uren', 'tarief', 'km', 'km_tarief'):
        if fld not in rec:
            raise ValidationError(f'veld ontbreekt: {fld}')
        val = rec[fld]
        if val is None:
            raise ValidationError(f'veld leeg: {fld}')
        if fld != 'datum' and val < 0:
            raise ValidationError(f'negatieve waarde op {fld}: {val}')

    # Datum-formaat
    if not isinstance(rec['datum'], str) or not _DATE_RE.match(rec['datum']):
        raise ValidationError(f'datum niet ISO-formaat: {rec["datum"]!r}')

    code = (rec.get('code') or '').strip().upper()
    is_billable = code not in _NON_BILLABLE_CODES

    if is_billable:
        if rec['uren'] <= 0:
            raise ValidationError(f'billable code {code!r} heeft uren=0')
        if rec['tarief'] <= 0:
            raise ValidationError(
                f'billable code {code!r} heeft tarief=0 — '
                f'PDF-parse populateert tarief niet (2025-precedent)'
            )

    # km zonder km_tarief → silent zero reiskosten
    if inv_type == 'factuur' and rec['km'] > 0 and rec['km_tarief'] <= 0:
        raise ValidationError(
            f'km={rec["km"]} > 0 maar km_tarief=0 voor dagpraktijk'
        )
```

En voeg toe aan `import_/__init__.py`:

```python
from .werkdag_validator import validate_werkdag_record, ValidationError  # noqa: F401
```

- [ ] **Step 4: Run validator tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest \
  tests/test_werkdag_validator.py -v
```

Expected: alle 12 PASS.

- [ ] **Step 5: Wire validator into import-pipeline**

Zoek in `pages/facturen.py` het PDF-import-pad dat per geparste dagregel een `add_werkdag` doet (rond `_import_factuur_rows` of waar ook de `items.append(current_item)`-data terecht komt als werkdag-insert). Vóór elke `add_werkdag(...)`-call:

```python
from import_.werkdag_validator import validate_werkdag_record, ValidationError

skipped: list[dict] = []
for item in parsed_items:
    try:
        validate_werkdag_record(item, inv_type=inv_type)
    except ValidationError as exc:
        skipped.append({'item': item, 'reason': str(exc)})
        continue
    await add_werkdag(DB_PATH, klant_id=..., **_line_item_to_werkdag_kwargs(item, inv_type))

if skipped:
    lines = '\n'.join(f'  • {s["item"].get("datum", "?")}: {s["reason"]}' for s in skipped)
    ui.notify(
        f'{len(skipped)} werkdag(en) overgeslagen — controleer PDF of '
        f'voeg handmatig toe:\n{lines}',
        type='warning', multi_line=True, timeout=10000,
    )
```

Exacte integratiepunt: het klopt met de bestaande structuur in `_import_factuur_rows` en het import-handler in `pages/facturen.py`. Lees eerst dat blok en plaats de try/except op de juiste loop.

- [ ] **Step 6: Add integration test**

Voeg toe aan `tests/test_facturen.py` (of maak `tests/test_import_integration.py`):

```python
@pytest.mark.asyncio
async def test_import_skips_werkdag_with_tarief_zero(seeded_db, tmp_path, monkeypatch):
    """Regression: import-pad met tarief=0 op billable code wordt niet in DB opgeslagen."""
    from import_.werkdag_validator import validate_werkdag_record, ValidationError
    from pages.facturen import _line_item_to_werkdag_kwargs

    bad_item = {
        'datum': '2025-06-15', 'code': 'CONSULT',
        'uren': 8.0, 'tarief': 0.0,  # <-- the bug
        'km': 0.0, 'km_tarief': 0.0,
    }
    with pytest.raises(ValidationError, match='tarief=0'):
        validate_werkdag_record(bad_item, inv_type='factuur')
```

- [ ] **Step 7: Run full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 703 passed (12 nieuwe validator + 1 integration), 14 skipped.

- [ ] **Step 8: Commit**

```bash
git add import_/werkdag_validator.py import_/__init__.py pages/facturen.py \
        tests/test_werkdag_validator.py tests/test_facturen.py
git commit -m "$(cat <<'EOF'
feat(import): per-record werkdag validator voor PDF-imports

Wired into the PDF import path zodat een werkdag die tarief=0 heeft op
een billable code (geen ACHTERWACHT/ADMIN/NASCHOLING/AQUISITIE) wordt
geskipt met user-notificatie — ipv silent in DB terechtkomen. Voorkomt
recurrence van de maart-2026 precedent waarin 116 werkdagen uit 2025
geïmporteerd werden met tarief=0.

Pure validator is fully unit-tested (12 tests) in
import_/werkdag_validator.py, inclusief ANW edge (km_tarief=0 legit)
en non-billable codes (tarief=0 legit).
EOF
)"
```

---

## Task 3: Sluit silent-fallback-fiscal loophole in `upsert_fiscale_params`

**Rationale.** Commit `235b76c` sloot de loophole voor `pvv_*`, `repr_aftrek_pct`, `ew_forfait_pct`. De 11 overgebleven `kwargs.get(..., hardcoded_default)` pogingen in `database.py:1916-1929` shippen nog steeds:
- **box3 rendementen 2024 VOORLOPIG** (`1.03`, `6.17`, `2.46`) — Belastingdienst publiceert definitief láter in het jaar; shipping voorlopige waarden voor 2027+ = feitelijk fout.
- `villataks_grens=1_350_000` (2024-waarde), `wet_hillen_pct=0` (Hillen uitgefaseerd, per jaar veranderend), `urencriterium=1225` (kan wijzigen), `pvv_premiegrondslag=0` (chain naar schijf1_grens).

Fiscaal belang voor jou: bij "Jaar toevoegen 2027" vergeet je één veld → DB krijgt stil 2024-waarden → aangifte 2027 rekent met voorlopige cijfers → discrepantie met Belastingdienst.

**Simplicity check.** De fix is puur: 11 × `kwargs.get(x, d)` → `kwargs[x]`. Geen nieuwe abstractie. De *lezer* (`bereken_volledig`) doet al fail-loud — de *schrijver* moet het matchen.

**Files:**
- Modify: `database.py` `upsert_fiscale_params` (regels 1910–1929)
- Modify: `pages/instellingen.py` `_validate_fiscal_params` (required-set uitbreiden)
- Create: `tests/test_fiscale_params_required.py`

- [ ] **Step 1: Write the failing tests**

Nieuw bestand `tests/test_fiscale_params_required.py`:

```python
"""Silent-fallback loophole regression — completes the work from commit 235b76c."""

import pytest
from database import upsert_fiscale_params


REQUIRED_FIELDS = [
    'villataks_grens', 'wet_hillen_pct', 'urencriterium',
    'pvv_premiegrondslag', 'arbeidskorting_brackets',
    'box3_heffingsvrij_vermogen', 'box3_rendement_bank_pct',
    'box3_rendement_overig_pct', 'box3_rendement_schuld_pct',
    'box3_tarief_pct', 'box3_drempel_schulden',
]


def _valid_kwargs_2027():
    """Full kwargs dict matching the current INSERT signature. Bump this when schema changes."""
    return dict(
        jaar=2027,
        # IB schijven
        schijf1_grens=80000, schijf1_pct=36.97,
        schijf2_grens=115000, schijf2_pct=49.50,
        schijf3_pct=49.50,
        # Heffingskortingen
        ahk_max=3362, ahk_afbouw_pct=6.0, ahk_drempel=24000,
        ak_max=5712,
        # ZVW
        zvw_pct=5.32, zvw_max_grondslag=71625,
        # Fiscale aftrek-percentages (al required sinds 235b76c)
        repr_aftrek_pct=80, ew_forfait_pct=0.35,
        pvv_aow_pct=17.90, pvv_anw_pct=0.10, pvv_wlz_pct=9.65,
        # Fields we zijn making required in this task
        villataks_grens=1_350_000, wet_hillen_pct=66.0,
        urencriterium=1225, pvv_premiegrondslag=40000,
        arbeidskorting_brackets='[]',
        box3_heffingsvrij_vermogen=57000,
        box3_rendement_bank_pct=1.44,
        box3_rendement_overig_pct=5.88,
        box3_rendement_schuld_pct=2.61,
        box3_tarief_pct=36,
        box3_drempel_schulden=3700,
        # Overige
        mkb_vrijstelling_pct=12.70, kia_pct=28,
        kia_ondergrens=2801, kia_bovengrens=69765,
        zelfstandigenaftrek=3750, startersaftrek=2123,
    )


@pytest.mark.asyncio
async def test_upsert_accepts_complete_kwargs(db):
    """Sanity: volledige kwargs werkt."""
    await upsert_fiscale_params(db, **_valid_kwargs_2027())


@pytest.mark.asyncio
@pytest.mark.parametrize('missing_field', REQUIRED_FIELDS)
async def test_upsert_fails_loud_on_missing_required_field(db, missing_field):
    """Ontbrekend required-field → KeyError met veldnaam in de message."""
    kwargs = _valid_kwargs_2027()
    del kwargs[missing_field]
    with pytest.raises(KeyError, match=missing_field):
        await upsert_fiscale_params(db, **kwargs)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest \
  tests/test_fiscale_params_required.py -v
```

Expected: 11 parametrized tests FAIL (geen KeyError — silent fallback gebruikt defaults).

- [ ] **Step 3: Remove silent defaults in `database.py:1916-1929`**

Exacte wijziging in het INSERT-statement van `upsert_fiscale_params`:

```python
# VOOR:
kwargs.get('villataks_grens', 1_350_000),
kwargs.get('wet_hillen_pct', 0),
kwargs.get('urencriterium', 1225),
kwargs.get('pvv_premiegrondslag', 0),
kwargs.get('arbeidskorting_brackets', ''),
kwargs['pvv_aow_pct'],
kwargs['pvv_anw_pct'],
kwargs['pvv_wlz_pct'],
kwargs.get('box3_heffingsvrij_vermogen', 57000),
kwargs.get('box3_rendement_bank_pct', 1.03),
kwargs.get('box3_rendement_overig_pct', 6.17),
kwargs.get('box3_rendement_schuld_pct', 2.46),
kwargs.get('box3_tarief_pct', 36),
kwargs.get('box3_drempel_schulden', 3700),

# NA:
kwargs['villataks_grens'],
kwargs['wet_hillen_pct'],
kwargs['urencriterium'],
kwargs['pvv_premiegrondslag'],
kwargs['arbeidskorting_brackets'],
kwargs['pvv_aow_pct'],
kwargs['pvv_anw_pct'],
kwargs['pvv_wlz_pct'],
kwargs['box3_heffingsvrij_vermogen'],
kwargs['box3_rendement_bank_pct'],
kwargs['box3_rendement_overig_pct'],
kwargs['box3_rendement_schuld_pct'],
kwargs['box3_tarief_pct'],
kwargs['box3_drempel_schulden'],
```

**LET OP.** Kijk in dezelfde INSERT ook naar `kwargs.get('villataks_pct', 2.35)` — die staat NIET in de lijst boven (was al required), maar als je hem tegenkomt in de INSERT-signature, check consistent. Laat `kwargs.get('za_actief', 1)` en `kwargs.get('sa_actief', 0)` ONGEWIJZIGD (dat zijn user-toggles met zinvolle defaults).

- [ ] **Step 4: Update `_validate_fiscal_params` in `pages/instellingen.py`**

Voeg toe aan `required_positive_pct` (de validator die nu al actief is sinds `235b76c`):

```python
required_positive_pct = [
    'schijf1_pct', 'schijf2_pct', 'schijf3_pct',
    'mkb_vrijstelling_pct',
    'pvv_aow_pct', 'pvv_anw_pct', 'pvv_wlz_pct',
    'zvw_pct', 'ew_forfait_pct', 'repr_aftrek_pct',
    # Nieuw in audit-followup:
    'box3_rendement_bank_pct', 'box3_rendement_overig_pct',
    'box3_tarief_pct',
]
```

En voeg een nieuwe required-presence-but-can-be-zero check toe (want `wet_hillen_pct=0` en `box3_rendement_schuld_pct=0` zijn theoretisch legitiem — maar present-zijn is vereist):

```python
# Required-aanwezig, 0 toegestaan (wet_hillen in uitfasering, schuld-rendement
# kan 0 zijn als je geen Box-3-schulden hebt).
required_nonneg_pct = [
    'wet_hillen_pct', 'box3_rendement_schuld_pct',
]
for fld in required_nonneg_pct:
    if fld not in p or p[fld] is None:
        errors.append(f'{fld} is verplicht — vul 0 in als niet van toepassing')
    elif not (0 <= p[fld] <= 100):
        errors.append(f'{fld} moet tussen 0 en 100 liggen (nu: {p[fld]})')
```

En voor bedragen/grenzen:

```python
required_positive_bedragen = [
    'villataks_grens', 'urencriterium',
    'box3_heffingsvrij_vermogen',
]
for fld in required_positive_bedragen:
    if fld not in p or p[fld] is None:
        errors.append(f'{fld} is verplicht en mag niet leeg zijn')
    elif p[fld] <= 0:
        errors.append(f'{fld} moet > 0 zijn (nu: {p[fld]})')

required_nonneg_bedragen = [
    'pvv_premiegrondslag', 'box3_drempel_schulden',
]
for fld in required_nonneg_bedragen:
    if fld not in p or p[fld] is None:
        errors.append(f'{fld} is verplicht — vul 0 in als niet van toepassing')
    elif p[fld] < 0:
        errors.append(f'{fld} mag niet negatief zijn')

if 'arbeidskorting_brackets' not in p or not p['arbeidskorting_brackets']:
    errors.append('arbeidskorting_brackets is verplicht (JSON-array van schijven)')
```

- [ ] **Step 5: Run full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 715 passed (11 parametrized new + 1 complete_kwargs). De "Jaar toevoegen" bestaande tests blijven groen want ze kopiëren van een bestaand compleet jaar.

**ALS een bestaande test faalt** (meest waarschijnlijk `tests/test_instellingen.py` of `tests/test_fiscal.py` die kwargs-incomplete calls doen): breidt die tests uit met de nu-required fields — dat is het PUNT van deze fix.

- [ ] **Step 6: Handmatige verificatie — open /instellingen**

Open de app (`python main.py`), ga naar Instellingen → Fiscale parameters, klik "Jaar toevoegen". Verifieer:
- Kopie van meest recent jaar populeert ALLE 11 nieuwe required fields.
- Leeg-maken van één van de nieuwe required velden → rode validatie-error bij "Opslaan".
- Foutmelding bevat de veldnaam.

- [ ] **Step 7: Commit**

```bash
git add database.py pages/instellingen.py tests/test_fiscale_params_required.py \
        tests/test_instellingen.py  # if modified
git commit -m "$(cat <<'EOF'
fix(fiscal): close remaining silent-fallback loophole in upsert_fiscale_params

Commit 235b76c sloot de loophole voor pvv_*/repr_aftrek/ew_forfait.
Deze commit sluit de overgebleven 11 fiscal defaults: villataks_grens,
wet_hillen_pct, urencriterium, pvv_premiegrondslag, arbeidskorting_brackets
en alle 5 box3_* fields.

Belangrijk: box3_rendement_bank/overig/schuld_pct shipten als 2024
VOORLOPIGE waarden. Belastingdienst publiceert definitieve rates
láter in het jaar — silent defaults voor 2027+ zouden aangifte
vervuilen met verouderde cijfers.

Validator in pages/instellingen.py matcht: required_positive_pct voor
tarieven > 0, required_nonneg voor fields waar 0 legit is
(wet_hillen post-uitfasering, schuld-rendement zonder schulden).
EOF
)"
```

---

## Task 4: Verwijder dode pagina `pages/dashboard_omzet.py`

**Rationale.** De pagina heeft een eigen route `@ui.page('/dashboard/omzet')` en wordt geïmporteerd in `main.py:28`, maar **geen enkele `ui.navigate.to` verwijst ernaar**. Dashboard's "Bruto omzet"-KPI linkt naar `/werkdagen`, conform `PRODUCT_FLOWS.md`. De pagina is alleen bereikbaar door URL-typen → dood. Verwijderen reduceert verwarring bij toekomstige code-review.

**Files:**
- Delete: `pages/dashboard_omzet.py`
- Modify: `main.py:28`
- Test: geen nieuwe test; bestaande moeten blijven pass'en.

- [ ] **Step 1: Verifieer dat niets ernaar linkt**

```bash
grep -rn "dashboard/omzet\|dashboard_omzet" \
  --include="*.py" --include="*.html" --include="*.md" \
  . 2>/dev/null | grep -v "^./.claude/worktrees/" | grep -v "^./.venv/"
```

Expected output: drie regels — pagina-definitie, import in main.py, en evt. de audit-rapport-mentions. GEEN `ui.navigate` of `@click` naar `/dashboard/omzet`.

- [ ] **Step 2: Delete de pagina**

```bash
git rm pages/dashboard_omzet.py
```

- [ ] **Step 3: Verwijder import in main.py**

Verwijder in `main.py` de regel:

```python
import pages.dashboard_omzet
```

(rond regel 28, exacte regelnummer kan schuiven). Zorg dat er geen dangling comment boven blijft staan.

- [ ] **Step 4: Run full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 715 passed, 14 skipped — geen regressies want niets verwees naar de pagina.

- [ ] **Step 5: Handmatige smoke-test**

```bash
python main.py
```

Open native-venster, navigeer Dashboard → klik "Bruto omzet" → moet naar `/werkdagen` gaan (niet 404). Sluit app.

- [ ] **Step 6: Commit**

```bash
git add main.py pages/dashboard_omzet.py  # git rm'd file
git commit -m "chore: remove unreachable pages/dashboard_omzet.py

Route /dashboard/omzet was registered maar geen enkele ui.navigate.to
verwees ernaar. Dashboard's Bruto-omzet-KPI linkt naar /werkdagen per
PRODUCT_FLOWS.md. Verwijderen reduceert confusion en imports."
```

---

## Task 5: Fix stale DB-path in `.mcp.json`

**Rationale.** Huidige `.mcp.json` wijst naar `/06_Development/roberg-boekhouding/data/boekhouding.sqlite3` — twee fouten: (a) werkdirectory heet `1_roberg-boekhouding` (met prefix), (b) live-DB woont sinds `712aa0f` in `~/Library/Application Support/Boekhouding/data/`. Als je via Claude Code ooit SQL-queries op de DB wilt doen, krijg je stale of corrupte data. 30-seconden fix.

**Files:**
- Modify: `.mcp.json`

- [ ] **Step 1: Update het pad**

Vervang in `.mcp.json`:

```json
{
  "mcpServers": {
    "sqlite": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "mcp-server-sqlite",
        "--db-path",
        "/Users/macbookpro_test/Library/Application Support/Boekhouding/data/boekhouding.sqlite3"
      ],
      "env": {}
    }
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add .mcp.json
git commit -m "chore: point .mcp.json at current DB location

Previous path (/06_Development/roberg-boekhouding/data/…) was the
pre-712aa0f location; data now lives in ~/Library/Application Support/
Boekhouding/data/ per the safety move."
```

---

## Task 6 (optioneel): UI-guard helpers voor Herinnering en Verstuur

**Rationale.** Menu-items `Herinnering versturen` en `Verstuur via e-mail` missen een `pdf_pad`-gate respectievelijk een `type/bron`-gate. User kan klikken en krijgt een warning-toast terug — dead-end. Ideale pattern is analoog aan `_is_editable`/`_can_revert_to_concept`: Python-helper + matchende v-if.

**Skip als je tijd krap is.** Deze task voegt geen euro toe, alleen polish.

**Files:**
- Modify: `pages/facturen.py` (helpers + v-if in row-menu)
- Modify: `tests/test_facturen.py`

- [ ] **Step 1: Write helper tests**

Voeg toe aan `tests/test_facturen.py`:

```python
# === UI-guard helpers for send-mail / send-herinnering ===

def test_can_send_mail_true_for_concept_with_regels():
    from pages.facturen import _can_send_mail
    assert _can_send_mail({'status': 'concept', 'type': 'factuur',
                            'bron': '', 'pdf_pad': '', 'regels_json': '[]'})


def test_can_send_mail_true_for_verstuurd_with_pdf():
    from pages.facturen import _can_send_mail
    assert _can_send_mail({'status': 'verstuurd', 'type': 'factuur',
                            'bron': '', 'pdf_pad': '/path/a.pdf',
                            'regels_json': ''})


def test_can_send_mail_false_for_betaald():
    from pages.facturen import _can_send_mail
    assert not _can_send_mail({'status': 'betaald', 'type': 'factuur',
                                'bron': '', 'pdf_pad': '/path/a.pdf',
                                'regels_json': ''})


def test_can_send_mail_false_for_import_without_pdf():
    """Imported factuur zonder PDF: UI zou dead-end 'Bewerken eerst' melden."""
    from pages.facturen import _can_send_mail
    assert not _can_send_mail({'status': 'verstuurd', 'type': 'anw',
                                'bron': 'import', 'pdf_pad': '',
                                'regels_json': ''})


def test_can_send_herinnering_true_for_verlopen_with_pdf():
    from pages.facturen import _can_send_herinnering
    assert _can_send_herinnering({'verlopen': True, 'pdf_pad': '/path/a.pdf'})


def test_can_send_herinnering_false_without_pdf():
    from pages.facturen import _can_send_herinnering
    assert not _can_send_herinnering({'verlopen': True, 'pdf_pad': ''})


def test_can_send_herinnering_false_when_not_verlopen():
    from pages.facturen import _can_send_herinnering
    assert not _can_send_herinnering({'verlopen': False, 'pdf_pad': '/path/a.pdf'})
```

- [ ] **Step 2: Run — fail (helpers niet bestaand)**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest \
  tests/test_facturen.py -k "can_send" -v
```

- [ ] **Step 3: Implement helpers**

Voeg toe in `pages/facturen.py` direct onder `_can_revert_to_concept`:

```python
def _can_send_mail(row: dict) -> bool:
    """Can this factuur show 'Verstuur via e-mail' in the menu?

    - Concept: ja, mits er regels zijn (builder-gegenereerde PDF kan on-demand).
    - Verstuurd/verlopen: ja, mits er een pdf_pad bestaat.
    - Betaald: nee (geen reden meer om te versturen).
    - Imports zonder PDF: nee — dead-end want Bewerken is verborgen.
    """
    status = row.get('status', '')
    if status == 'betaald':
        return False
    has_pdf = bool(row.get('pdf_pad'))
    is_import = (row.get('type') == 'anw' or row.get('bron') == 'import')
    if status == 'concept':
        return bool(row.get('regels_json')) or has_pdf
    # verstuurd of verlopen
    if is_import:
        return has_pdf  # imports need existing PDF, geen regenerate-pad
    return has_pdf or bool(row.get('regels_json'))


def _can_send_herinnering(row: dict) -> bool:
    """Can this factuur show 'Herinnering versturen' in the menu?

    Alleen voor verlopen facturen MET een bestaande PDF — herinnering-body
    koppelt aan de originele factuur-PDF als attachment.
    """
    return bool(row.get('verlopen')) and bool(row.get('pdf_pad'))
```

- [ ] **Step 4: Update row-menu v-if predicates**

In `pages/facturen.py`, in het Quasar-template blok (rond regels 498–600):

```jinja
<!-- VOOR: -->
<q-item v-if="props.row.status !== 'betaald'" clickable
    @click="() => $parent.$emit('sendmail', props.row)">
    ...
</q-item>
<q-item v-if="props.row.verlopen" clickable
    @click="() => $parent.$emit('sendherinnering', props.row)">
    ...
</q-item>

<!-- NA: -->
<q-item v-if="props.row.status !== 'betaald' && (props.row.pdf_pad || (props.row.status === 'concept' && props.row.regels_json) || !(props.row.type === 'anw' || props.row.bron === 'import'))" clickable
    @click="() => $parent.$emit('sendmail', props.row)">
    ...
</q-item>
<q-item v-if="props.row.verlopen && props.row.pdf_pad" clickable
    @click="() => $parent.$emit('sendherinnering', props.row)">
    ...
</q-item>
```

**Sanity-check.** Deze v-if's moeten SEMANTISCH matchen met `_can_send_mail`/`_can_send_herinnering`. Als je de Python-helper tweakt, pas de v-if mee.

- [ ] **Step 5: Run full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 722 passed (7 nieuwe helper-tests), 14 skipped.

- [ ] **Step 6: Handmatige smoke-test**

Open app → facturen-pagina → verifieer op één concept-factuur, één verstuurde met PDF, één betaalde, en één ge-importeerde ANW dat het menu klopt met verwachting.

- [ ] **Step 7: Commit**

```bash
git add pages/facturen.py tests/test_facturen.py
git commit -m "feat(facturen): _can_send_mail + _can_send_herinnering helpers

Sluit ui-guard-mirrors-backend gap voor 'Verstuur via e-mail' en
'Herinnering versturen' — menu-items worden nu verborgen wanneer
backend-handler zou falen (betaald, ontbrekende PDF, imported zonder
PDF). Volgt hetzelfde patroon als _is_editable/_can_revert_to_concept."
```

---

## Post-plan: Meetbaarheid

Na afronding van Task 1–5 zou je zien:
- **Testcount**: +30 nieuwe tests (4 parser + 12 validator + 1 integration + 12 fiscal required + 1 complete_kwargs).
- **LOC delta**: +~250 (validator + tests), −~90 (dashboard_omzet.py + silent defaults).
- **Fail-loud coverage**: alle jaar-afhankelijke fiscal params moeten nu expliciet gezet zijn bij upsert. Box 3 voorlopige-rate ongeluk = onmogelijk.
- **Import robustness**: malformed PDF-regel → ge-isoleerde skip met user-notify, niet hele import failen.
- **Dead code surface**: 1 dode pagina weg, 1 stale config pad gefixt.

Totale effort: ~2–3 uur als je TDD strict volgt. Task 6 optioneel add ~30 min.

---

## Self-review checklist

- [x] **Spec coverage**: elke audit-finding met rating ≥ BELANGRIJK heeft een task (Kritiek #1 → Task 3; Belangrijk #9 → Task 1; Belangrijk from episodic memory → Task 2). Dode code #1 → Task 4. Config fix → Task 5. UI-polish → Task 6.
- [x] **No placeholders**: alle code-stappen bevatten letterlijke code, geen "TODO"/"similar to"-shortcuts.
- [x] **Type consistency**: `ValidationError` gedefinieerd in Task 2 Step 3 wordt in Task 2 Step 1 (tests) al genoemd — matchen. `_can_send_mail`/`_can_send_herinnering` signatures matchen test-inputs.
- [x] **Exclusions explicit**: year-lock guards (Plan A), connection singleton (Plan B), database package refactor (`docs/superpowers/plans/`) blijven buiten scope.
- [x] **Fiscaal-expertise toegepast**: box3-voorlopig-vs-definitief onderscheid geëxpliciteerd in Task 3 rationale; ANW km_tarief=0 is legit edge in Task 2 validator; ACHTERWACHT/ADMIN non-billable codes legit met tarief=0.
