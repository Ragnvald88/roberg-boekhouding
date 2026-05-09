# Werkdag-popup Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maak `components/werkdag_form.py` van een lineair formulier met `ui.separator()` divisies tot een strakke Apple-stijl dialog die `.settings-section` patterns hergebruikt, met humanized activiteit-codes en correct pattern-mode visueel signaal.

**Architecture:** Drie pure helpers in `domain/codes.py` (testbaar zonder NiceGUI) leveren label-rendering en activiteit-derivation. Eén pure helper in `components/utils.py` formatteert datum naar Nederlands lang formaat. Alle visuele tokens komen uit bestaande Sprint B/G CSS tokens (witte surface, lichtgrijze sections, teal accent). Werkdag-form integreert deze helpers + nieuwe CSS classes; pattern-mode disabled fields visualiseren `confirm_expected`'s niet-bewerkbare flow.

**Tech Stack:** Python 3.12, NiceGUI 3.8 + Quasar, native pywebview, pytest, raw SQL via aiosqlite (geen DB-changes deze sprint).

---

## File Structure

| Path | Responsibility |
|---|---|
| `domain/codes.py` | Pure helpers: `humanize_legacy_code`, `build_code_options`, `derive_activiteit`. Geen NiceGUI imports. |
| `components/utils.py` | `+format_datum_lang(iso_str) -> str`: ISO datum → "zaterdag 9 mei 2026". Pure stdlib. |
| `components/layout.py` | `+ui.add_css(...)` blok met ~10 nieuwe classes voor de dialog. Buiten `@layer components` (Quasar cascade rule). |
| `components/werkdag_form.py` | Volledige redesign van `open_werkdag_dialog`: header/sections/totaal/footer + pattern-mode disable + save-flow refactor met `derive_activiteit`. |
| `tests/test_codes.py` | NEW: pure-helper tests (22 cases verdeeld over 3 classes + smoke). |
| `tests/test_format_datum_lang.py` | NEW: 4 cases voor de NL-lang formatter. |
| `tests/test_werkdag_form.py` | NEW: 3 save-flow regression-tests + 3 pattern-mode source-pin tests. |

## Test plan

Run alle tests met:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

Per task: alleen de relevante test bestanden eerst, en aan het eind de full suite.

---

## Task 1: `humanize_legacy_code` pure helper

**Files:**
- Modify: `domain/codes.py` (append helper + imports)
- Test: `tests/test_codes.py` (new file)

- [ ] **Step 1: Schrijf de failing tests**

Maak `tests/test_codes.py`:

```python
"""Tests voor domain.codes pure helpers — humanize, build_code_options, derive_activiteit."""

import pytest

from domain.codes import (
    CODES,
    humanize_legacy_code,
    build_code_options,
    derive_activiteit,
)


# === humanize_legacy_code ===

class TestHumanizeLegacyCode:

    def test_empty_string_returns_geen(self):
        assert humanize_legacy_code('') == '(geen)'

    def test_wdagpraktijk_int(self):
        assert humanize_legacy_code('WDAGPRAKTIJK_70') == 'Praktijkdienst (€ 70/u)'

    def test_wdagpraktijk_decimal(self):
        assert humanize_legacy_code('WDAGPRAKTIJK_77,50') == 'Praktijkdienst (€ 77,50/u)'

    def test_anw_single_segment(self):
        assert humanize_legacy_code('ANW_WEEKEND') == 'ANW · weekend'

    def test_anw_multi_segment_keeps_2letter_caps(self):
        assert humanize_legacy_code('ANW_DR_WERKDAG_NACHT_ACHTERWACHT') == \
            'ANW · DR · werkdag · nacht · achterwacht'

    def test_anw_gr_segment(self):
        assert humanize_legacy_code('ANW_GR_WEEKEND_DAG') == 'ANW · GR · weekend · dag'

    def test_aw_werkdag(self):
        assert humanize_legacy_code('AW-WK-A') == 'AW · werkdag · A'

    def test_aw_weekend(self):
        assert humanize_legacy_code('AW-WKND-A') == 'AW · weekend · A'

    def test_titlecased_freetext_unchanged(self):
        assert humanize_legacy_code('Admin') == 'Admin'

    def test_long_uppercase_titlecased(self):
        assert humanize_legacy_code('REISTIJD') == 'Reistijd'

    def test_short_uppercase_acronym_unchanged(self):
        assert humanize_legacy_code('AQUI') == 'AQUI'

    def test_smoke_all_db_codes_non_empty(self):
        """Alle 26 codes uit live DB (snapshot 2026-05-09) leveren non-empty string op."""
        db_codes = [
            'WDAGPRAKTIJK_70', 'WDAGPRAKTIJK_77,50', 'Admin', '', 'WERKDAG',
            'ANW_WEEKEND', 'WDAGPRAKTIJK_80', 'ANW_GR_WEEKEND_DAG', 'ANW_AVOND',
            'ANW_DR_WEEKEND_DAG', 'NSCHL', 'AW-WK-A',
            'ANW_DR_WERKDAG_AVOND_ACHTERWACHT', 'ANW_DR_WEEKEND_ACHTERWACHT',
            'ANW_NACHT', 'ANW_DR_WERKDAG_AVOND', 'ANW_GR_WERKDAG_AVOND',
            'AW-WKND-A', 'AW-WK-E', 'ANW_GR_WEEKEND_AVOND', 'REISTIJD',
            'AW-WK-H', 'AQUI', 'ANW_DR_WERKDAG_NACHT_ACHTERWACHT',
            'ANW_DR_WERKDAG_NACHT', 'ANW_DR_WEEKEND_AVOND',
        ]
        for c in db_codes:
            result = humanize_legacy_code(c)
            assert isinstance(result, str)
            assert result != '', f'humanize_legacy_code({c!r}) returned empty'
```

- [ ] **Step 2: Run de tests, verwacht ImportError**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_codes.py -v
```

Expected: `ImportError: cannot import name 'humanize_legacy_code'`.

- [ ] **Step 3: Implementeer `humanize_legacy_code` in `domain/codes.py`**

Append onderaan `domain/codes.py` (na `ZERO_UREN_CODES`):

```python
import re

_WDAGPRAKTIJK_RE = re.compile(r'^WDAGPRAKTIJK_(\d+(?:,\d+)?)$')
_AW_SEGMENT_MAP = {
    'WK': 'werkdag',
    'WKND': 'weekend',
}


def humanize_legacy_code(code: str) -> str:
    """Render legacy/onbekende werkdag-codes menselijk leesbaar.

    Bestaande codes uit CODES blijven via CODES-lookup gerenderd; deze
    helper is alleen fallback voor codes die NIET in CODES zitten.

    Patronen (op basis van DB-realiteit 2026-05-09):
    - 'WDAGPRAKTIJK_NN[,NN]' (424× in DB) → 'Praktijkdienst (€ NN[,NN]/u)'
    - 'ANW_*' met _-segmenten (60×)        → 'ANW · seg1 · seg2 · ...'
                                              (2-letter caps blijven UPPERCASE)
    - 'AW-WK-*' / 'AW-WKND-*' (11×)        → 'AW · werkdag/weekend · X'
    - Vrije tekst kort / titlecased        → as-is (Admin, AQUI)
    - Lange UPPERCASE (>5 chars)           → Title-case (REISTIJD → Reistijd)
    - Lege string                          → '(geen)'
    """
    if not code:
        return '(geen)'

    # Pattern 1: WDAGPRAKTIJK_NN[,NN]
    m = _WDAGPRAKTIJK_RE.match(code)
    if m:
        return f'Praktijkdienst (€ {m.group(1)}/u)'

    # Pattern 2: AW-WK-A / AW-WKND-A
    if code.startswith('AW-'):
        parts = code.split('-')
        humanized = [_AW_SEGMENT_MAP.get(p, p) for p in parts]
        return ' · '.join(humanized)

    # Pattern 3: ANW_X_Y_Z (underscore-separated)
    if '_' in code:
        parts = code.split('_')
        humanized = [parts[0]]  # eerste segment behoudt caps (ANW)
        for p in parts[1:]:
            # 2-letter all-caps afkortingen (DR, GR) blijven uppercase
            if len(p) <= 2 and p.isupper():
                humanized.append(p)
            else:
                humanized.append(p.lower())
        return ' · '.join(humanized)

    # Fallback: free text / acronym
    if code.isupper():
        if len(code) <= 5:
            # Korte acronym blijft uppercase (AQUI, NSCHL)
            return code
        # Lange uppercase woord wordt title-case (REISTIJD → Reistijd)
        return code.title()
    # Mixed case of titlecased — onveranderd doorgeven (Admin)
    return code
```

- [ ] **Step 4: Run de tests, verwacht PASS**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_codes.py::TestHumanizeLegacyCode -v
```

Expected: `12 passed`.

- [ ] **Step 5: Commit**

```bash
git add domain/codes.py tests/test_codes.py
git commit -m "$(cat <<'EOF'
feat(domain): humanize_legacy_code voor onbekende activiteit-codes

Pure helper rendert legacy DB-codes menselijk:
- WDAGPRAKTIJK_77,50 → "Praktijkdienst (€ 77,50/u)"
- ANW_DR_WERKDAG_NACHT → "ANW · DR · werkdag · nacht"
- AW-WK-A → "AW · werkdag · A"
- '' → "(geen)"

UI-only render-helper: opgeslagen DB-waarden veranderen niet.
Onderdeel van werkdag-popup redesign (Sprint K-vervolg).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `build_code_options` pure helper

**Files:**
- Modify: `domain/codes.py` (append helper)
- Test: `tests/test_codes.py` (append `TestBuildCodeOptions` class)

- [ ] **Step 1: Schrijf de failing tests**

Append in `tests/test_codes.py`:

```python
# === build_code_options ===

class TestBuildCodeOptions:

    def test_none_returns_codes_dict(self):
        result = build_code_options(None)
        assert result == CODES

    def test_known_code_returns_codes_dict(self):
        result = build_code_options('WERKDAG')
        assert result == CODES
        assert 'WERKDAG' in result

    def test_legacy_code_added_with_humanized_label(self):
        result = build_code_options('WDAGPRAKTIJK_77,50')
        assert result['WDAGPRAKTIJK_77,50'] == 'Praktijkdienst (€ 77,50/u)'
        # Original CODES entries still present
        assert result['WERKDAG'] == 'Waarneming dagpraktijk'

    def test_empty_string_added_as_geen(self):
        result = build_code_options('')
        assert result[''] == '(geen)'

    def test_unknown_acronym_added_with_humanizer_fallback(self):
        result = build_code_options('AQUI')
        assert result['AQUI'] == 'AQUI'

    def test_does_not_mutate_codes_dict(self):
        """Belangrijk: CODES is module-level, mag NIET muteren."""
        before = dict(CODES)
        build_code_options('WDAGPRAKTIJK_99')
        assert CODES == before
```

- [ ] **Step 2: Run de tests, verwacht ImportError op `build_code_options`**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_codes.py::TestBuildCodeOptions -v
```

Expected: `ImportError: cannot import name 'build_code_options'`.

- [ ] **Step 3: Implementeer `build_code_options` in `domain/codes.py`**

Append in `domain/codes.py`:

```python
def build_code_options(existing_code: str | None) -> dict[str, str]:
    """Build dropdown options-dict voor werkdag-activiteit dropdown.

    - Returns een nieuwe dict (CODES wordt NIET gemuteerd)
    - existing_code in CODES of None → exact CODES-inhoud
    - existing_code niet in CODES → entry {existing_code: humanize_legacy_code(...)} toegevoegd
    - existing_code == '' → entry {'': '(geen)'} toegevoegd, zodat lege code
      een expliciete dropdown-keuze blijft (anders zou 'lege werkdag' bij
      edit-save stilletjes naar 'WERKDAG' muteren)
    """
    options = dict(CODES)
    if existing_code is None:
        return options
    if existing_code in options:
        return options
    options[existing_code] = humanize_legacy_code(existing_code)
    return options
```

- [ ] **Step 4: Run de tests, verwacht PASS**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_codes.py::TestBuildCodeOptions -v
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add domain/codes.py tests/test_codes.py
git commit -m "$(cat <<'EOF'
feat(domain): build_code_options helper voor activiteit-dropdown

Pure helper voor de werkdag-form Activiteit-dropdown. Voegt onbekende of
lege legacy-codes toe als extra entry (met humanized label) zodat edit-
mode geen stille CODES-mismatch krijgt. CODES blijft immutable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `derive_activiteit` pure helper

**Files:**
- Modify: `domain/codes.py` (append helper)
- Test: `tests/test_codes.py` (append `TestDeriveActiviteit` class)

- [ ] **Step 1: Schrijf de failing tests**

Append in `tests/test_codes.py`:

```python
# === derive_activiteit ===

class TestDeriveActiviteit:

    def test_known_code_returns_canonical_label(self):
        assert derive_activiteit('WERKDAG', None) == 'Waarneming dagpraktijk'

    def test_known_code_canonical_wins_over_current(self):
        """Canonical CODES-label heeft voorrang op current_activiteit voor known codes."""
        assert derive_activiteit('WERKDAG', 'Custom tekst') == 'Waarneming dagpraktijk'

    def test_legacy_code_preserves_historic_activiteit(self):
        """Legacy code + historische activiteit → behoud historische tekst (geen overschrijving)."""
        assert derive_activiteit('WDAGPRAKTIJK_77,50', 'Praktijk Dr. X') == 'Praktijk Dr. X'

    def test_legacy_code_no_history_falls_back_to_humanizer(self):
        assert derive_activiteit('WDAGPRAKTIJK_77,50', None) == 'Praktijkdienst (€ 77,50/u)'

    def test_empty_code_preserves_current(self):
        assert derive_activiteit('', 'Vrije tekst') == 'Vrije tekst'

    def test_empty_code_no_current_returns_empty(self):
        assert derive_activiteit('', None) == ''
```

- [ ] **Step 2: Run de tests, verwacht ImportError**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_codes.py::TestDeriveActiviteit -v
```

Expected: `ImportError: cannot import name 'derive_activiteit'`.

- [ ] **Step 3: Implementeer `derive_activiteit` in `domain/codes.py`**

Append in `domain/codes.py`:

```python
def derive_activiteit(code: str, current_activiteit: str | None) -> str:
    """Bepaal activiteit-tekst voor save.

    - Code in CODES → CODES[code] (canonical label voor known codes)
    - Code niet in CODES + current_activiteit truthy → current_activiteit
      (preserve historische tekst voor legacy codes; voorkomt dat edit-save
      van WDAGPRAKTIJK_77,50 zijn historische activiteit-tekst verliest)
    - Code niet in CODES + geen current → humanize_legacy_code(code)
    - Lege code + geen current → ''
    """
    if code in CODES:
        return CODES[code]
    if current_activiteit:
        return current_activiteit
    if not code:
        return ''
    return humanize_legacy_code(code)
```

- [ ] **Step 4: Run de tests, verwacht PASS**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_codes.py::TestDeriveActiviteit -v
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add domain/codes.py tests/test_codes.py
git commit -m "$(cat <<'EOF'
feat(domain): derive_activiteit helper preserveert legacy historic tekst

Voorkomt dat edit-save van legacy code (bv. WDAGPRAKTIJK_77,50) de
historische activiteit-tekst overschrijft met een generieke fallback.
- Known code (in CODES): canonical label wint
- Legacy + history aanwezig: history blijft
- Legacy + geen history: humanize_legacy_code fallback

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `format_datum_lang` Nederlandse-datum formatter

**Files:**
- Modify: `components/utils.py` (append helper)
- Test: `tests/test_format_datum_lang.py` (new file)

- [ ] **Step 1: Schrijf de failing tests**

Maak `tests/test_format_datum_lang.py`:

```python
"""Tests voor format_datum_lang — ISO datum → Nederlands lang formaat."""

from components.utils import format_datum_lang


def test_zaterdag_9_mei_2026():
    assert format_datum_lang('2026-05-09') == 'zaterdag 9 mei 2026'


def test_donderdag_31_december_2026():
    assert format_datum_lang('2026-12-31') == 'donderdag 31 december 2026'


def test_empty_string_returns_empty():
    assert format_datum_lang('') == ''


def test_invalid_string_returns_empty():
    assert format_datum_lang('niet-een-datum') == ''
```

- [ ] **Step 2: Run de tests, verwacht ImportError**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_format_datum_lang.py -v
```

Expected: `ImportError: cannot import name 'format_datum_lang'`.

- [ ] **Step 3: Implementeer `format_datum_lang` in `components/utils.py`**

Voeg toe aan `components/utils.py` ná `format_datum_jaar_nl` (rond line 126):

```python
_DUTCH_WEEKDAGEN = (
    'maandag', 'dinsdag', 'woensdag', 'donderdag',
    'vrijdag', 'zaterdag', 'zondag',
)
_DUTCH_MAANDEN_LANG = (
    'januari', 'februari', 'maart', 'april', 'mei', 'juni',
    'juli', 'augustus', 'september', 'oktober', 'november', 'december',
)


def format_datum_lang(iso_date: str) -> str:
    """ISO YYYY-MM-DD → 'weekdag D maand YYYY' (Nederlands lang).

    - '2026-05-09' → 'zaterdag 9 mei 2026'
    - Lege of ongeldige input → ''
    """
    if not iso_date:
        return ''
    try:
        d = date.fromisoformat(iso_date)
    except (ValueError, TypeError):
        return ''
    return f'{_DUTCH_WEEKDAGEN[d.weekday()]} {d.day} {_DUTCH_MAANDEN_LANG[d.month - 1]} {d.year}'
```

Verifieer dat `from datetime import date` al bovenaan `utils.py` is geïmporteerd. Lees eerst de eerste 5 regels van het bestand om te checken; zo niet, voeg `from datetime import date` toe.

- [ ] **Step 4: Run de tests, verwacht PASS**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_format_datum_lang.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add components/utils.py tests/test_format_datum_lang.py
git commit -m "$(cat <<'EOF'
feat(utils): format_datum_lang voor Nederlands lang datum-formaat

ISO datum → 'zaterdag 9 mei 2026'. Pure stdlib (geen babel-dependency).
Bestemd voor de werkdag-popup header-subtitle die mee-update met datum-input.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: CSS classes voor de werkdag-dialog

**Files:**
- Modify: `components/layout.py` (in `ui.add_css('''...''', shared=True)` block, **buiten** `@layer components`)

- [ ] **Step 1: Lees de huidige `ui.add_css(...)` afsluiter**

Lees `components/layout.py` lines 495-515 om te zien hoe het CSS-blok eindigt (de string sluit met `''', shared=True)`). De nieuwe classes komen direct daarvóór, na de bestaande Sprint H dashboard-hero-tile classes.

- [ ] **Step 2: Voeg de werkdag-dialog CSS-classes toe**

In `components/layout.py`, vlak voor de afsluiter `''', shared=True)` (waarschijnlijk rond regel 512):

```css
/* === Werkdag-popup redesign — Apple-stijl sheet (2026-05-09)
   Defined OUTSIDE @layer components for cascade-safety. .q-card chained
   selector is required to win van Quasar's unlayered .q-card defaults.
   Same pattern as Sprint G's .settings-card en Sprint H's
   .dashboard-hero-tile. */
.q-card.werkdag-dialog-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0;
    overflow: hidden;
    max-width: 680px;
    width: 100%;
}
.werkdag-dialog-header {
    padding: 20px 24px 16px;
    border-bottom: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-height: 70px;
}
.werkdag-dialog-title {
    font-size: 1.15rem;
    font-weight: 650;
    color: var(--text);
}
.werkdag-dialog-subtitle {
    font-size: 0.9rem;
    color: var(--muted);
    min-height: 1.2em;
}
.werkdag-dialog-body {
    padding: 20px 24px;
}
.werkdag-dialog-footer {
    padding: 14px 24px 18px;
    border-top: 1px solid var(--border);
    display: flex;
    justify-content: flex-end;
    gap: 8px;
}
.werkdag-pattern-hint {
    background: var(--bg-info-soft);
    border: 1px solid rgba(37, 99, 235, 0.18);
    border-radius: 10px;
    padding: 10px 14px;
    color: var(--muted);
    font-size: 0.85rem;
    line-height: 1.4;
    margin-bottom: 16px;
}
.werkdag-locatie-caption {
    color: var(--muted);
    font-size: 0.85rem;
    margin-top: 4px;
}
.werkdag-totaal-strook {
    background: var(--accent-soft);
    border: 1px solid rgba(15, 118, 110, 0.18);
    border-radius: 10px;
    padding: 14px 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-top: 4px;
}
.werkdag-totaal-label {
    color: var(--text);
    font-size: 0.95rem;
    font-weight: 600;
}
.werkdag-totaal-breakdown {
    color: var(--muted);
    font-size: 0.85rem;
    font-variant-numeric: tabular-nums;
    word-wrap: break-word;
}
.werkdag-totaal-bedrag {
    color: var(--accent);
    font-size: 1.25rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
.q-field.werkdag-textarea .q-field__native {
    min-height: 36px;
    max-height: 96px;
    overflow-y: auto;
}
```

- [ ] **Step 3: Run cascade-test om te bevestigen dat geen `.q-*` selectors in `@layer` zitten**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_visual_css.py -v
```

Expected: `passed` (alle existing tests nog groen, plus impliciet dat de nieuwe `.q-card.werkdag-dialog-card` en `.q-field.werkdag-textarea` selectors buiten `@layer components` staan).

- [ ] **Step 4: Run full test-suite om te controleren dat niets breekt**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: alle tests nog groen.

- [ ] **Step 5: Commit**

```bash
git add components/layout.py
git commit -m "$(cat <<'EOF'
feat(css): werkdag-dialog tokens (Apple-stijl sheet)

11 nieuwe classes voor de redesign-popup, allemaal buiten @layer components
(Quasar cascade-rule). Hergebruikt Sprint B/G design-tokens (--surface,
--accent-soft, --border, --radius). Volgt .settings-card/.dashboard-hero-tile
chained-selector patroon.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Save-flow refactor — `derive_activiteit` voor legacy preservation

**Files:**
- Modify: `components/werkdag_form.py` (alleen save-flow, geen visuele wijzigingen)
- Test: `tests/test_werkdag_form.py` (new file)

- [ ] **Step 1: Schrijf de failing regression-tests**

Maak `tests/test_werkdag_form.py`:

```python
"""Save-flow regression-tests voor werkdag_form.

NiceGUI dialog is niet headless te renderen, dus we testen save-flow via
een minimale mock-harness die de save-functie binnen open_werkdag_dialog
'extraheert' en met fake inputs aanroept.
"""

import inspect
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

import pytest

from domain.codes import derive_activiteit


def _fake_werkdag(**overrides):
    base = dict(
        id=1, datum='2026-05-09', klant_id=10, klant_naam='Test',
        code='WERKDAG', activiteit='Waarneming dagpraktijk',
        locatie='Praktijk', uren=8.0, km=0, tarief=90.0, km_tarief=0.23,
        urennorm=1, opmerking='', factuurnummer='',
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# === Save-flow voor activiteit-derivation ===

class TestSaveFlowLegacyCode:

    def test_known_code_uses_canonical_label(self):
        """code='WERKDAG' → activiteit='Waarneming dagpraktijk' (canonical wins)."""
        result = derive_activiteit(
            code='WERKDAG',
            current_activiteit='Custom legacy tekst',
        )
        assert result == 'Waarneming dagpraktijk'

    def test_legacy_code_preserves_historic_activiteit(self):
        """Edit-save van WDAGPRAKTIJK_77,50 mag activiteit-tekst NIET overschrijven."""
        wd = _fake_werkdag(code='WDAGPRAKTIJK_77,50', activiteit='Praktijk Dr. X')
        result = derive_activiteit(
            code=wd.code,
            current_activiteit=wd.activiteit,
        )
        assert result == 'Praktijk Dr. X'
        # Negatief: NIET de generieke fallback
        assert result != 'Waarneming dagpraktijk'

    def test_empty_code_preserves_freetext_activiteit(self):
        """code='' edit-save: activiteit blijft 'Vrije tekst'."""
        wd = _fake_werkdag(code='', activiteit='Vrije tekst')
        result = derive_activiteit(
            code=wd.code,
            current_activiteit=wd.activiteit,
        )
        assert result == 'Vrije tekst'

    def test_save_flow_imports_derive_activiteit(self):
        """Source-pin: werkdag_form moet derive_activiteit importeren."""
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'derive_activiteit' in source, \
            'werkdag_form moet derive_activiteit gebruiken voor activiteit-bepaling'
```

- [ ] **Step 2: Run de tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_werkdag_form.py::TestSaveFlowLegacyCode -v
```

Expected: 3/4 PASS (helper-only tests groen), `test_save_flow_imports_derive_activiteit` faalt — `derive_activiteit not in source`.

- [ ] **Step 3: Refactor save-flow in `werkdag_form.py`**

In `components/werkdag_form.py`:

(a) Pas import op regel 16 aan:

```python
from domain.codes import (
    CODES,
    ZERO_UREN_CODES as _ZERO_UREN_CODES,
    derive_activiteit,
)
```

(b) Vervang in de `save()` functie (rond regel 274-276) deze code:

```python
            k = klant_data[kid]
            code = code_select.value or 'WERKDAG'
            activiteit = CODES.get(code, 'Waarneming dagpraktijk')
```

door:

```python
            k = klant_data[kid]
            # Code: preserve '' explicit (build_code_options biedt '(geen)' aan
            # in dropdown bij edit van een werkdag met code=''). None betekent
            # 'no selection at all' (valt terug op WERKDAG default).
            code = code_select.value if code_select.value is not None else 'WERKDAG'
            activiteit = derive_activiteit(
                code=code,
                current_activiteit=werkdag.activiteit if is_edit else None,
            )
```

- [ ] **Step 4: Run de tests, verwacht PASS**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_werkdag_form.py::TestSaveFlowLegacyCode -v
```

Expected: `4 passed`.

- [ ] **Step 5: Run full suite om regressies te checken**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: alle tests groen.

- [ ] **Step 6: Codex review**

```bash
env -u OPENAI_API_KEY codex exec --sandbox read-only - <<'PROMPT'
Review the save-flow refactor in components/werkdag_form.py rond de save()
functie. Specifiek:
1. Is `code = code_select.value if code_select.value is not None else 'WERKDAG'`
   correct voor het preserveren van '' (explicit empty selection) maar None
   (geen selectie) als 'WERKDAG' default?
2. Wordt derive_activiteit correct aangeroepen met huidige werkdag.activiteit
   bij edit-mode?
3. Zijn er regressie-risico's voor de pattern-mode flow (confirm_expected,
   geen overrides)?

Geef pushback ALLEEN op concrete issues. <300 woorden.
PROMPT
```

Lees output, evalueer pushback per `superpowers:receiving-code-review` principes (verifieer claims tegen code/spec; push back met technische redenen op false positives; fix concrete issues inline). Commit pas na evaluatie.

- [ ] **Step 7: Commit**

```bash
git add components/werkdag_form.py tests/test_werkdag_form.py
git commit -m "$(cat <<'EOF'
fix(werkdag-form): preserveer historische activiteit bij legacy code-save

Edit-save van een werkdag met legacy code (bv. WDAGPRAKTIJK_77,50)
overschreef stilletjes activiteit naar 'Waarneming dagpraktijk' via
CODES.get(code, fallback). Vervangen door derive_activiteit() helper:
- Known code: canonical CODES-label wint
- Legacy + history: history blijft
- Empty code: history blijft, anders ''

Plus: code-select waarde wordt nu 'is None'-checked ipv 'or default',
zodat lege expliciete selectie (build_code_options '(geen)') niet
stilletjes naar 'WERKDAG' muteert.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Pattern-mode disabled-state + "Bevestigen" button-label

**Files:**
- Modify: `components/werkdag_form.py` (alleen pattern-mode wiring + button-label, nog geen UI redesign)
- Test: `tests/test_werkdag_form.py` (append `TestPatternMode`)

- [ ] **Step 1: Schrijf de failing source-pin tests**

Append in `tests/test_werkdag_form.py`:

```python
# === Pattern-mode source-pin ===

class TestPatternMode:

    def test_pattern_mode_disables_inputs(self):
        """In pattern-mode (pattern_id is set) zijn klant/code/uren/etc disabled.

        Source-pin: vereist code-pad dat klant_select/code_select met
        .props('disable') én uren_input/tarief_input/km_input/km_tarief_input
        met .props('readonly') configureert wanneer pattern_id is not None.
        """
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        # Verwacht een if-blok dat op pattern_id triggered en disable/readonly toepast
        assert "pattern_id is not None" in source, \
            'Pattern-mode disabled-state moet expliciet op pattern_id branchen'
        assert ".props('disable')" in source or ".props('readonly')" in source, \
            'Pattern-mode moet inputs disabled/readonly maken'

    def test_pattern_mode_button_label_bevestigen(self):
        """Footer-knop label is 'Bevestigen' ipv 'Opslaan' in pattern-mode."""
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert "'Bevestigen'" in source, \
            'Pattern-mode footer moet "Bevestigen" knop tonen'

    def test_pattern_mode_no_opslaan_en_nieuw(self):
        """Source-pin: 'Opslaan & Nieuw' knop wordt NIET aangemaakt in pattern-mode.

        Bestaand: button is gegateerd op `not is_edit and pattern_id is None`.
        Test pinneert dat deze guard intact blijft.
        """
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert "not is_edit and pattern_id is None" in source, \
            'Opslaan & Nieuw moet niet getoond worden in pattern-mode'
```

- [ ] **Step 2: Run de tests, verwacht 1-2 failures**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_werkdag_form.py::TestPatternMode -v
```

Expected: `test_pattern_mode_no_opslaan_en_nieuw` PASS (al aanwezig). Twee andere falen.

- [ ] **Step 3: Voeg pattern-mode disable + Bevestigen-button toe in `werkdag_form.py`**

**Plaatsing**: tussen het einde van de input/edit-mode/prefill setup en de bestaande regel `# Initial calculation` op regel 260. In huidige code: vlak **vóór** regel 260 (`# Initial calculation` / `update_totaal()`), zodat het disable-pakket de laatste configuratie-stap is voordat de dialog interactief wordt.

(a) Voeg toe direct vóór regel 260 (`# Initial calculation`):

```python
        # Pattern-mode (vanuit /agenda Bevestigen-flow): velden read-only
        # zichtbaar maken — confirm_expected accepteert geen overrides, dus
        # user-edits zouden anders stil verloren gaan. Datum blijft editable
        # zodat de gebruiker op een andere dag kan bevestigen.
        if pattern_id is not None:
            klant_select.props('disable')
            locatie_select.props('disable')
            code_select.props('disable')
            uren_input.props('readonly')
            tarief_input.props('readonly')
            km_input.props('readonly')
            km_tarief_input.props('readonly')
            urennorm_check.props('disable')
            opmerking_input.props('readonly')
```

(b) In de buttons-row (rond regel 348), vervang:

```python
        # Buttons
        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
            ui.button('Annuleren', on_click=dialog.close).props('flat')
            # "Opslaan & Nieuw" verbergen in pattern-mode: pattern_id blijft
            # actief in de closure na de eerste save, dus een tweede
            # confirm_expected op een andere datum zou semantisch fout zijn
            # (pattern hoort bij één expected-occurrence, niet bij elke
            # vervolg-werkdag).
            if not is_edit and pattern_id is None:
                ui.button(
                    'Opslaan & Nieuw', icon='add',
                    on_click=lambda: save(and_new=True),
                ).props('outline color=primary')
            ui.button(
                'Opslaan', icon='save',
                on_click=lambda: save(and_new=False),
            ).props('color=primary')
```

door:

```python
        # Buttons
        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
            ui.button('Annuleren', on_click=dialog.close).props('flat')
            # "Opslaan & Nieuw" verbergen in pattern-mode: pattern_id blijft
            # actief in de closure na de eerste save, dus een tweede
            # confirm_expected op een andere datum zou semantisch fout zijn
            # (pattern hoort bij één expected-occurrence, niet bij elke
            # vervolg-werkdag).
            if not is_edit and pattern_id is None:
                ui.button(
                    'Opslaan & Nieuw', icon='add',
                    on_click=lambda: save(and_new=True),
                ).props('outline color=primary')
            # Pattern-mode toont "Bevestigen" ipv "Opslaan" zodat het visueel
            # duidelijk is dat dit geen vrije save maar een patroon-bevestiging is.
            primary_label = 'Bevestigen' if pattern_id is not None else 'Opslaan'
            primary_icon = 'check' if pattern_id is not None else 'save'
            ui.button(
                primary_label, icon=primary_icon,
                on_click=lambda: save(and_new=False),
            ).props('color=primary')
```

- [ ] **Step 4: Run de tests, verwacht PASS**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_werkdag_form.py::TestPatternMode -v
```

Expected: `3 passed`.

- [ ] **Step 5: Run full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: alle tests groen.

- [ ] **Step 6: Codex review**

```bash
env -u OPENAI_API_KEY codex exec --sandbox read-only - <<'PROMPT'
Review components/werkdag_form.py — specifiek de nieuwe pattern-mode
disable-block en de "Bevestigen"-button label-switch.

Vragen:
1. Werkt locatie_select.props('disable') ook als locatie_row hidden is
   (set_visibility(False))? Geen runtime-error?
2. Is de volgorde correct: eerst alle inputs aanmaken in `_load_klant_data`
   (async!), dan pattern-mode disable toepassen? Kan dat een race-condition
   zijn waar disable verloren gaat na een latere klant-change?
3. Is 'check' het juiste Quasar/material-icon voor "Bevestigen"?

Pushback alleen op concrete issues. <300 woorden.
PROMPT
```

Evalueer pushback. Fix concrete issues; push back op false positives.

- [ ] **Step 7: Commit**

```bash
git add components/werkdag_form.py tests/test_werkdag_form.py
git commit -m "$(cat <<'EOF'
feat(werkdag-form): pattern-mode disabled state + Bevestigen-knop

Pattern-mode (vanuit /agenda Bevestigen-flow) gaf voorheen een formulier
waar user kon editen, terwijl confirm_expected() geen overrides accepteert.
Edits werden stil verloren.

Fix: in pattern-mode worden alle non-datum inputs disabled/readonly. Knop-
label wijzigt naar "Bevestigen" (icon check) zodat het visueel duidelijk
is dat dit geen vrije save is.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Visuele redesign — header, sections, totaal-strookje, opmerking-textarea, footer

**Files:**
- Modify: `components/werkdag_form.py` (volledige rewrite van de dialog body)
- Test: `tests/test_werkdag_form.py` (append `TestVisualRedesign`)

Dit is de grootste taak. Source-pin tests vangen verloren imports en visuele primitives (geen `ui.separator()` meer). Visuele check is manueel in Step 7.

- [ ] **Step 0: Schrijf failing source-pin tests**

Append in `tests/test_werkdag_form.py`:

```python
# === Visuele redesign source-pins ===

class TestVisualRedesign:

    def test_imports_format_datum_lang(self):
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'format_datum_lang' in source, \
            'werkdag_form moet format_datum_lang importeren voor de header-subtitle'

    def test_imports_build_code_options(self):
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'build_code_options' in source, \
            'werkdag_form moet build_code_options gebruiken voor activiteit-dropdown'

    def test_no_ui_separator_calls(self):
        """Sprint K-redesign: geen ui.separator() meer — sections vervangen lijnen."""
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'ui.separator()' not in source, \
            'ui.separator() is verwijderd — gebruik .settings-section blokken'

    def test_uses_werkdag_dialog_card_class(self):
        """Source-pin: nieuwe CSS class wordt op de outer card gezet."""
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'werkdag-dialog-card' in source, \
            'werkdag-dialog-card class moet op de outer card staan voor styling'

    def test_uses_settings_section_thrice(self):
        """Drie sections (Basis / Werk / Vergoeding) gebruiken settings-section."""
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert source.count("settings-section w-full") >= 3, \
            'Verwacht 3+ settings-section blokken (Basis/Werk/Vergoeding)'

    def test_default_focus_on_klant_in_add_mode(self):
        """Add-mode zonder klant-prefill: focus op klant_select.

        Source-pin: code-pad triggert .run_method('focus') of vergelijkbare
        focus-call op klant_select wanneer not is_edit en geen prefill klant_id.
        """
        import components.werkdag_form
        source = inspect.getsource(components.werkdag_form)
        assert 'klant_select.run_method' in source or '.props(\'autofocus\')' in source, \
            'Add-mode moet focus op klant_select zetten via run_method of autofocus'
```

- [ ] **Step 1: Run de tests, verwacht 6 failures**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_werkdag_form.py::TestVisualRedesign -v
```

Expected: 6 failed (geen van de imports/classes/focus zit nog in werkdag_form).

- [ ] **Step 2: Lees huidige `open_werkdag_dialog` volledig**

```bash
sed -n '1,366p' components/werkdag_form.py
```

Identificeer de delen die ongewijzigd blijven (`async def save()` body — die is in Task 6 al geüpdatet; klant-load logic, code-change handler, edit-mode restore, prefill-toepassing).

**Replacement scope voor Step 4**: alles **binnen** de `with ui.dialog() as dialog:` block, vanaf de openings-`with ui.card(...)` regel **tot en met** de oude buttons-row die in Task 7 is geüpdatet. Concreet in post-Task-7 file: van `with ui.dialog() as dialog, ui.card()...` (regel 56) tot en met de afsluitende `).props('color=primary')` van de "Opslaan/Bevestigen" button (eind van de buttons-row, ongeveer regel 363). De `async def save()` body en de allerlaatste `dialog.open()` blijven onaangetast — buiten de replacement.

- [ ] **Step 3: Update imports en helpers in `werkdag_form.py`**

Bovenaan `components/werkdag_form.py`, vervang de imports rond regel 1-16 door:

```python
"""Werkdag dialog — add/edit werkdag via popup."""

from nicegui import ui
from components.shared_ui import date_input
from components.utils import format_euro, format_datum_lang
from database import (
    get_klanten, add_werkdag, update_werkdag, get_fiscale_params,
    get_klant_locaties, DB_PATH,
)
from datetime import date

_KM_TARIEF_FALLBACK = 0

# Activiteitscodes — single source of truth in domain.codes (UI-free).
# Re-export here for backcompat with callers that import from this module.
from domain.codes import (
    CODES,
    ZERO_UREN_CODES as _ZERO_UREN_CODES,
    derive_activiteit,
    build_code_options,
)
```

- [ ] **Step 4: Vervang de dialog body + oude buttons-row**

Verwijder vanaf regel 56 (de `with ui.dialog()...` opening) tot de afsluitende regel van de oude buttons-row (de `).props('color=primary')` van de oude Opslaan/Bevestigen-button — typisch rond regel 363 in post-Task-7 file). Vervang door:

```python
    with ui.dialog() as dialog:
        with ui.card().classes('werkdag-dialog-card q-pa-none'):
            # === HEADER ===
            with ui.column().classes('werkdag-dialog-header'):
                title_text = 'Werkdag bewerken' if is_edit else 'Werkdag toevoegen'
                ui.label(title_text).classes('werkdag-dialog-title')

                if is_edit:
                    initial_datum = werkdag.datum
                elif prefill and prefill.get('datum'):
                    initial_datum = prefill['datum']
                else:
                    initial_datum = date.today().isoformat()

                subtitle_label = ui.label(
                    format_datum_lang(initial_datum)
                ).classes('werkdag-dialog-subtitle')

            # === BODY ===
            with ui.column().classes('werkdag-dialog-body w-full gap-4'):

                # Pattern-mode hint banner
                if pattern_id is not None:
                    ui.label(
                        'Deze werkdag komt uit een terugkerend patroon. '
                        'Bewerk het patroon via /agenda → Klant → Patronen '
                        'als je waarden wilt aanpassen.'
                    ).classes('werkdag-pattern-hint')

                # --- Sectie 1: Basis ---
                with ui.column().classes('settings-section w-full'):
                    ui.label('Basis').classes('settings-section-title')
                    with ui.grid(columns=2).classes('w-full gap-3'):
                        datum_input = date_input(
                            'Datum',
                            value=initial_datum,
                        ).classes('w-full')

                        if is_edit:
                            initial_klant = werkdag.klant_id
                        elif prefill and prefill.get('klant_id'):
                            initial_klant = prefill['klant_id']
                        else:
                            initial_klant = None
                        klant_select = ui.select(
                            klant_options,
                            value=initial_klant,
                            label='Klant',
                            with_input=True,
                        ).classes('w-full')

                    locatie_row = ui.row().classes('w-full q-pa-none')
                    locatie_row.set_visibility(False)
                    with locatie_row:
                        with ui.column().classes('w-full q-pa-none gap-1'):
                            locatie_select = ui.select(
                                {}, label='Locatie', value=None,
                                on_change=lambda e: on_locatie_change(e.value),
                            ).classes('w-full')
                            locatie_caption = ui.label('').classes(
                                'werkdag-locatie-caption')
                            locatie_caption.set_visibility(False)

                # --- Sectie 2: Werk ---
                with ui.column().classes('settings-section w-full'):
                    ui.label('Werk').classes('settings-section-title')

                    # Build dropdown opties via pure helper (handelt legacy + '' af)
                    existing_code = werkdag.code if is_edit else None
                    code_options = build_code_options(existing_code)
                    initial_code = (
                        werkdag.code if is_edit and werkdag.code in code_options
                        else 'WERKDAG'
                    )

                    with ui.grid(columns=2).classes('w-full gap-3'):
                        code_select = ui.select(
                            code_options,
                            value=initial_code,
                            label='Activiteit',
                        ).classes('w-full')

                        uren_input = ui.number(
                            'Uren', value=werkdag.uren if is_edit else 8,
                            min=0, max=24, step=0.5,
                        ).classes('w-full')

                    urennorm_check = ui.checkbox(
                        'Telt mee voor urencriterium',
                        value=werkdag.urennorm if is_edit else True,
                    )

                # --- Sectie 3: Vergoeding ---
                with ui.column().classes('settings-section w-full'):
                    ui.label('Vergoeding').classes('settings-section-title')
                    with ui.grid(columns=3).classes('w-full gap-3'):
                        tarief_input = ui.number(
                            'Tarief',
                            value=werkdag.tarief if is_edit else 0,
                            format='%.2f', min=0, step=0.50,
                            suffix='€/uur',
                        ).classes('w-full')

                        km_input = ui.number(
                            'Km retour',
                            value=werkdag.km if is_edit else 0,
                            min=0, step=1,
                        ).classes('w-full')

                        km_tarief_input = ui.number(
                            'Km-tarief',
                            value=werkdag.km_tarief if is_edit else default_km_tarief,
                            format='%.2f', min=0, step=0.01,
                            suffix='€/km',
                        ).classes('w-full')

                # --- Totaal-strookje ---
                with ui.row().classes('werkdag-totaal-strook'):
                    with ui.column().classes('q-pa-none gap-1'):
                        ui.label('Totaal').classes('werkdag-totaal-label')
                        breakdown_label = ui.label('Vul uren en tarief in') \
                            .classes('werkdag-totaal-breakdown')
                    bedrag_label = ui.label('€ 0,00').classes('werkdag-totaal-bedrag')

                # --- Opmerking (geen aparte sectie-titel) ---
                opmerking_input = ui.textarea(
                    'Opmerking',
                    value=werkdag.opmerking if is_edit else '',
                ).props('autogrow').classes('w-full werkdag-textarea')

            # === FOOTER ===
            with ui.row().classes('werkdag-dialog-footer w-full'):
                ui.button('Annuleren', on_click=dialog.close).props('flat')
                if not is_edit and pattern_id is None:
                    ui.button(
                        'Opslaan & Nieuw', icon='add',
                        on_click=lambda: save(and_new=True),
                    ).props('outline color=primary')
                primary_label = 'Bevestigen' if pattern_id is not None else 'Opslaan'
                primary_icon = 'check' if pattern_id is not None else 'save'
                ui.button(
                    primary_label, icon=primary_icon,
                    on_click=lambda: save(and_new=False),
                ).props('color=primary')

            # === Update-handlers (binnen dialog-context zodat closure werkt) ===

            def update_subtitle():
                subtitle_label.text = format_datum_lang(datum_input.value or '')

            def update_totaal():
                u = uren_input.value or 0
                t = tarief_input.value or 0
                km = km_input.value or 0
                kmt = km_tarief_input.value or 0
                totaal = u * t + km * kmt
                parts = []
                if t:
                    parts.append(f'{u} × {format_euro(t)}')
                if km and kmt:
                    parts.append(f'{km:.0f} km × {format_euro(kmt)}')
                if parts:
                    breakdown_label.text = ' + '.join(parts)
                    bedrag_label.text = format_euro(totaal)
                else:
                    breakdown_label.text = 'Vul uren en tarief in'
                    bedrag_label.text = format_euro(0)

            def on_locatie_change(loc_id):
                kid = klant_select.value
                if loc_id and kid in locatie_data:
                    for loc in locatie_data[kid]:
                        if loc.id == loc_id:
                            km_input.value = loc.retour_km
                            if loc.retour_km > 0:
                                locatie_caption.text = f'Retour: {loc.retour_km} km'
                                locatie_caption.set_visibility(True)
                            else:
                                locatie_caption.set_visibility(False)
                            break
                else:
                    locatie_caption.set_visibility(False)
                update_totaal()

            async def _load_klant_data(kid):
                """Load location data and set defaults for a given klant_id."""
                if kid and kid in klant_data:
                    k = klant_data[kid]
                    tarief_input.value = k.tarief_uur

                    locaties = await get_klant_locaties(DB_PATH, kid)
                    locatie_data[kid] = locaties
                    if locaties:
                        loc_options = {loc.id: f"{loc.naam} ({loc.retour_km} km)"
                                       for loc in locaties}
                        locatie_select.options = loc_options
                        locatie_select.update()
                        locatie_row.set_visibility(True)

                        first_loc = locaties[0]
                        locatie_select.value = first_loc.id
                        km_input.value = first_loc.retour_km
                        if first_loc.retour_km > 0:
                            locatie_caption.text = f'Retour: {first_loc.retour_km} km'
                            locatie_caption.set_visibility(True)
                        else:
                            locatie_caption.set_visibility(False)
                    else:
                        locatie_row.set_visibility(False)
                        locatie_select.value = None
                        locatie_caption.set_visibility(False)
                        km_input.value = k.retour_km
                else:
                    locatie_row.set_visibility(False)
                    locatie_select.value = None
                    locatie_caption.set_visibility(False)
                update_totaal()

            datum_input.on_value_change(lambda _: update_subtitle())
            klant_select.on_value_change(lambda e: _load_klant_data(e.value))
            uren_input.on_value_change(lambda _: update_totaal())
            tarief_input.on_value_change(lambda _: update_totaal())
            km_input.on_value_change(lambda _: update_totaal())
            km_tarief_input.on_value_change(lambda _: update_totaal())

            def on_code_change(e):
                if e.value == 'ACHTERWACHT' or e.value in _ZERO_UREN_CODES:
                    urennorm_check.value = False
                else:
                    urennorm_check.value = True
                if e.value in _ZERO_UREN_CODES:
                    uren_input.value = 0
                    tarief_input.value = 0
                update_totaal()

            code_select.on_value_change(on_code_change)

            # Edit mode: load locations for existing werkdag's klant
            if is_edit:
                await _load_klant_data(werkdag.klant_id)
                if werkdag.locatie and klant_select.value in locatie_data:
                    for loc in locatie_data[klant_select.value]:
                        if loc.naam == werkdag.locatie:
                            locatie_select.value = loc.id
                            km_input.value = loc.retour_km
                            if loc.retour_km > 0:
                                locatie_caption.text = f'Retour: {loc.retour_km} km'
                                locatie_caption.set_visibility(True)
                            break
                # Restore historische tarief (A6: editen mag klant-default niet inheriten)
                tarief_input.value = werkdag.tarief
                km_input.value = werkdag.km

            # Apply non-edit prefill (pattern-driven from /agenda)
            if not is_edit and prefill:
                if prefill.get('klant_id'):
                    await _load_klant_data(prefill['klant_id'])
                if prefill.get('start_minuten') is not None and prefill.get('eind_minuten') is not None:
                    start = prefill['start_minuten']
                    eind = prefill['eind_minuten']
                    if eind > start:
                        uren_input.value = (eind - start) / 60.0
                if prefill.get('activiteit'):
                    for code_key, code_label in CODES.items():
                        if code_label == prefill['activiteit']:
                            code_select.value = code_key
                            break

            # Pattern-mode (vanuit /agenda Bevestigen-flow): velden read-only.
            # confirm_expected accepteert geen overrides; user-edits zouden
            # anders stil verloren gaan. Datum blijft editable zodat de
            # gebruiker op een andere dag kan bevestigen.
            if pattern_id is not None:
                klant_select.props('disable')
                locatie_select.props('disable')
                code_select.props('disable')
                uren_input.props('readonly')
                tarief_input.props('readonly')
                km_input.props('readonly')
                km_tarief_input.props('readonly')
                urennorm_check.props('disable')
                opmerking_input.props('readonly')

            # Default focus: in add-mode zonder klant-prefill, springt focus
            # naar het klant-zoekveld zodat gebruiker direct kan typen.
            if not is_edit and not (prefill and prefill.get('klant_id')):
                klant_select.run_method('focus')

            # Initial calculation
            update_totaal()
```

Belangrijk: de bestaande `async def save(...)` blijft staan na deze block (dat hebben we in Task 6 al aangepast). Ook `dialog.open()` op de allerlaatste regel blijft.

- [ ] **Step 5: Run pattern-mode + save-flow tests om te bevestigen dat ze nog passen**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_werkdag_form.py -v
```

Expected: `7 passed`. (Source-pins werken op de nieuwe code.)

- [ ] **Step 6: Run full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v 2>&1 | tail -15
```

Expected: alle tests groen — geen regressies in agenda-tests, year-lock-tests, etc.

- [ ] **Step 7: Codex review**

```bash
env -u OPENAI_API_KEY codex exec --sandbox read-only - <<'PROMPT'
Review de volledige nieuwe `open_werkdag_dialog` in components/werkdag_form.py.

Specifieke vragen:
1. NiceGUI: kunnen we `ui.column().classes('werkdag-dialog-header')` direct
   binnen een `ui.card().classes('q-pa-none')` plaatsen, of geeft Quasar
   QCard wrapper-padding-issues?
2. `ui.grid(columns=2).classes('w-full gap-3')` — werkt dit voor de
   datum+klant en activiteit+uren rows? Of moet het `ui.row()` met
   `flex-1`?
3. `ui.number(..., suffix='€/uur')` — is `suffix=` echt een geldige
   parameter voor NiceGUI's ui.number, of werkt alleen `.props('suffix=...')`?
4. `ui.textarea(...).props('autogrow')` — werkt dit met `.classes('werkdag-textarea')`?
5. Is de volgorde-inversie kritisch: `_load_klant_data` is geherdefinieerd
   IN de `with ui.dialog()` block, na de UI-elementen — heeft NiceGUI een
   issue met function-binding bij `klant_select.on_value_change(lambda e: _load_klant_data(e.value))`?
6. Race tussen `await _load_klant_data` (in is_edit branch) en `pattern_id`-
   disable: pattern-mode geldt voor non-edit-met-pattern_id, niet voor edit.
   Maar als prefill['klant_id'] is set EN pattern_id, gaat _load_klant_data
   waarden zetten die direct daarna readonly worden. Is dat OK?

Pushback met technische details. <500 woorden.
PROMPT
```

Lees de output. Voor elke pushback: verifieer tegen NiceGUI/Quasar docs of broncode in `.venv/lib/python3.14/site-packages/nicegui/elements/`. Fix concrete issues; push back op false positives met technische argumentatie.

- [ ] **Step 8: Manuele rendering-check**

Start de app:

```bash
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py
```

Klik in /agenda op een bestaande werkdag-pill (linkermuisknop) → "Bewerken" → controleer:
1. Dialog opent op ~680px breedte
2. Header: "Werkdag bewerken" titel + "zaterdag 9 mei 2026"-style subtitle
3. Datum wijzigen → subtitle updates LIVE
4. Drie lichtgrijze sections (Basis / Werk / Vergoeding) met titles
5. Locatie verschijnt netjes onder klant-veld bij klant met locaties + caption "Retour: 42 km" muted
6. Tarief / Km / Km-tarief gelijke 3-kol breedte met `€/uur` en `€/km` suffix in het veld
7. Totaal-strookje teal-tinted, label + breakdown links, groot bedrag rechts
8. Lege state: "Vul uren en tarief in" + "€ 0,00"
9. Opmerking-textarea zonder sectie-titel, autogrow tot ~3 regels max
10. Footer: Annuleren · Opslaan & Nieuw · Opslaan rechts uitgelijnd
11. Esc sluit dialog
12. Activiteit-dropdown toont voor `WDAGPRAKTIJK_77,50` werkdag de label "Praktijkdienst (€ 77,50/u)"

Klik vervolgens vanuit /agenda op een lege cel met een verwachte werkdag (recurring pattern) → "Bevestigen" → controleer:
13. Dialog toont blue-tinted hint "Deze werkdag komt uit een terugkerend patroon..."
14. Klant/Activiteit/Uren/Tarief/Km/Km-tarief/Urennorm/Opmerking allemaal disabled (grayed out, niet bewerkbaar)
15. Datum WEL editable
16. Footer-knop: "Bevestigen" (icon ✓) ipv "Opslaan"
17. Geen "Opslaan & Nieuw" knop

Als (13-17) niet werkt — fix vóór Task 9.

- [ ] **Step 9: Commit**

```bash
git add components/werkdag_form.py
git commit -m "$(cat <<'EOF'
feat(werkdag-form): visuele redesign — Apple-stijl sheet

Vervangt het lineaire formulier-met-separators door een gestructureerde
dialog volgens Sprint G/B design-tokens:
- Header met titel + live Nederlandse datum subtitle (mee-update)
- Drie .settings-section blokken (Basis / Werk / Vergoeding)
- Activiteit-dropdown gebruikt build_code_options (humanized legacy labels)
- 3-kol Vergoeding grid met suffix='€/uur'/'€/km' in velden zelf
- Teal-tinted totaal-strookje met breakdown + bedrag rechts (tabular-nums)
- Lege state: "Vul uren en tarief in" + "€ 0,00"
- Opmerking als losse textarea (autogrow, max 96px)
- Locatie-caption "Retour: 42 km" mee-update
- Pattern-mode hint banner (info-soft) verklaart read-only velden

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Documentation update + finale regression

**Files:**
- Modify: `docs/architecture/agenda.md` (voeg subsection toe over werkdag-popup)
- Modify: `CLAUDE.md` (eventuele nieuwe gotcha als codex iets opgewerkt heeft)

- [ ] **Step 1: Documenteer popup-redesign in `docs/architecture/agenda.md`**

Append onderaan `docs/architecture/agenda.md`:

```markdown
## Werkdag-popup (`components/werkdag_form.py`)

Apple-stijl sheet (Sprint K-vervolg, 2026-05-09 redesign). Hergebruikt
`.settings-section` patroon uit Sprint G. Drie secties: Basis (Datum +
Klant + optionele Locatie), Werk (Activiteit + Uren + urennorm-checkbox),
Vergoeding (Tarief + Km + Km-tarief in 3-kol grid).

**Header subtitle**: live Nederlandse datum ("zaterdag 9 mei 2026") via
`format_datum_lang` (components/utils.py). Update via `datum_input.on_value_change`.

**Activiteit-dropdown**: gebouwd via `build_code_options(existing_code)`
in `domain/codes.py`. Voor edit-mode met legacy code (bv.
`WDAGPRAKTIJK_77,50`) wordt een entry toegevoegd met humanized label via
`humanize_legacy_code`. Bestaande DB-waarden veranderen NIET — alleen
het rendered label.

**Save-flow activiteit**: `derive_activiteit(code, current_activiteit)`
preserveert historische `werkdag.activiteit` voor legacy codes (anders
zou edit-save ze met `CODES.get(code, fallback)` overschrijven).

**Pattern-mode** (`prefill['pattern_id']` set, vanuit `/agenda` Bevestigen-
flow): klant/code/uren/tarief/km/km-tarief/urennorm/opmerking allemaal
disabled. Datum blijft editable. Footer-knop label: "Bevestigen" (icon
check). Hint-banner verklaart de read-only state. Reden: `confirm_expected`
accepteert geen overrides — user-edits zouden anders stil verloren gaan.

**Totaal-strookje**: teal-tinted (`var(--accent-soft)`), breakdown muted
links + bedrag groot teal rechts (`tabular-nums`). Lege state: "Vul uren
en tarief in" + "€ 0,00".

**Locatie-caption**: muted "Retour: {km} km" zichtbaar als `retour_km > 0`,
hidden bij 0 of geen locatie.
```

- [ ] **Step 2: Run finale full-suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: alle tests groen, telling +22 tests t.o.v. de baseline.

- [ ] **Step 3: Run final-codex-review op de hele branch**

```bash
git diff master...HEAD --stat
```

Bekijk wat er totaal veranderd is. Als de file-list redelijk is, run:

```bash
env -u OPENAI_API_KEY codex exec --sandbox read-only - <<'PROMPT'
Final review van de werkdag-popup redesign branch. Bekijk:
- domain/codes.py
- components/utils.py
- components/layout.py
- components/werkdag_form.py
- tests/test_codes.py, test_format_datum_lang.py, test_werkdag_form.py
- docs/superpowers/specs/2026-05-09-werkdag-popup-redesign.md
- docs/architecture/agenda.md (nieuwe sectie)

Vragen:
1. Spec → implementatie compleet? Welke spec-bullets zijn niet uitgevoerd?
2. Test-coverage voldoende voor de gewijzigde code-paths?
3. Documentatie helder voor toekomstige mij?
4. Year-lock guards intact (geen DB-mutaties zonder assert_year_writable)?
5. Cascade-discipline (alle .q-* selectors buiten @layer)?

Samenvattend verdict: APPROVED of CHANGES REQUESTED met concrete punten.
<600 woorden.
PROMPT
```

Verwerk pushback (concrete fixes inline, push back op false positives).

- [ ] **Step 4: Commit documentatie + finalisatie**

```bash
git add docs/architecture/agenda.md
git commit -m "$(cat <<'EOF'
docs(agenda): werkdag-popup architecture-doc na redesign

Documenteert de nieuwe header-subtitle, build_code_options pattern,
derive_activiteit save-flow, pattern-mode disabled state en visuele
componenten (.settings-section blokken, totaal-strookje).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review checklist

**Spec coverage**:
- [x] Visueel redesign van header/sections/totaal/footer → Task 8
- [x] `humanize_legacy_code` → Task 1
- [x] `build_code_options` → Task 2
- [x] `derive_activiteit` → Task 3
- [x] `format_datum_lang` → Task 4
- [x] CSS classes (incl. `.q-card.werkdag-dialog-card`, `.q-field.werkdag-textarea`) → Task 5
- [x] Save-flow refactor met legacy preservation → Task 6
- [x] Pattern-mode disabled state + Bevestigen → Task 7
- [x] Architecture-doc update → Task 9

**Type consistency**:
- `humanize_legacy_code(code: str) -> str` consistent gebruikt in Task 2 (`build_code_options`) en Task 3 (`derive_activiteit`)
- `build_code_options(existing_code: str | None) -> dict[str, str]` consistent in Task 8 (`existing_code = werkdag.code if is_edit else None`)
- `derive_activiteit(code: str, current_activiteit: str | None) -> str` consistent met Task 6 save-flow gebruik
- `format_datum_lang(iso_date: str) -> str` consistent met Task 8 subtitle handler

**Placeholder scan**: geen TBD/TODO/"add appropriate"/"similar to" in de plan-stappen.
