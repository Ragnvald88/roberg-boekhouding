# Werkdag-popup redesign — spec

**Status**: SHIPPED 2026-05-09 — pytest 1516 → 1557 (+41 tests). Master commits `4f5f3d2`, `f119623`, `267df9a`, `1f9cbd7`, `2853cb8`, `ae3ab66`.
**Datum**: 2026-05-09
**Doel**: De "Werkdag toevoegen / bewerken" dialog (`components/werkdag_form.py`) van een lineaire formulier-stack-met-separatoren omzetten naar een strakke, Apple-stijl sheet die de Sprint G `.settings-card` / `.settings-section` patterns volgt en aansluit bij de Sprint B design-tokens. Eindgebruiker is een huisartswaarnemer — invoer moet snel en rustig aanvoelen, geen bureaucratisch formulier.

**Scope**: alleen `components/werkdag_form.py` + bijbehorende CSS in `components/layout.py` + drie nieuwe pure helpers in `domain/codes.py` (`humanize_legacy_code`, `build_code_options`, `derive_activiteit`) + één pure helper `format_datum_lang` in `components/utils.py`. Geen DB-mutaties, geen schema-changes, geen nieuwe handlers, geen nieuwe pagina's.

**Out of scope**:
- Recent-gebruikte items bovenin dropdown
- Dirty-state tracking (Opslaan-knop disabled tot wijziging)
- Smooth animaties / number-tweens op totaal-update
- Read-only-mode bij definitief jaar (al afgehandeld via `YearLockedError`)
- Inline editing van klant-tarief, locaties of fiscale params
- Recurring-template-creator vanuit dialog
- Cmd+K / slash-menu / quick-add modus
- Migratie van legacy codes in de DB (alleen humaner *weergeven*)
- Responsive 1-kol fallback bij smalle viewports — app is desktop-only native pywebview, vaste 1400×900 window
- Hardcoded NL-provincie-mapping voor `ANW_GR_*` / `ANW_DR_*` codes — semantiek onbevestigd; afkortingen blijven capitalized maar onverklaard

## Visueel ontwerp (top-down)

### Container

`ui.dialog()` met one custom `ui.card().classes('werkdag-dialog-card w-full q-pa-none')`. Card heeft eigen padding=0 zodat header/body/footer hun eigen padding kunnen kiezen. Max-width van card: **680px** (huidig 576). 3-kol Vergoeding grid krijgt zo ~200px per veld.

### Header (`.werkdag-dialog-header`)

- Padding: 20px 24px 16px
- Border-bottom: 1px solid `var(--border)`
- Layout: stacked (titel boven, subtitle onder), min-height reserveren
- Titel (`.werkdag-dialog-title`): "Werkdag bewerken" of "Werkdag toevoegen". `text-h6` semantiek, font-weight 650, `color: var(--text)`.
- Subtitle (`.werkdag-dialog-subtitle`): live-formatted Nederlandse datum *"zaterdag 9 mei 2026"*. `font-size: 0.9rem`, `color: var(--muted)`. Updaten via `datum_input.on_value_change`. **Min-height** moet behouden blijven ook bij ongeldige/lege datum (anders header springt).

Geen close-X knop. Annuleren in footer + Esc dekken het.

### Body (`.werkdag-dialog-body`)

- Padding: 20px 24px
- `ui.column().classes('werkdag-dialog-body gap-4')` — 16px gap tussen secties
- Drie `.settings-section` blokken (hergebruik Sprint G class):

#### Sectie 1 — Basis

```python
with ui.column().classes('settings-section w-full'):
    ui.label('Basis').classes('settings-section-title')
    with ui.grid(columns=2).classes('w-full gap-3'):
        datum_input  # date_input(...) .classes('w-full')
        klant_select  # ui.select(..., with_input=True).classes('w-full')
    locatie_row  # alleen visible als klant locaties heeft
```

`locatie_row`: full-width `ui.select` voor locatie. Onder het veld een muted caption (`.werkdag-locatie-caption`, `font-size: 0.85rem`, `color: var(--muted)`):
- Locatie geselecteerd met `retour_km > 0` → `Retour: 42 km`
- Locatie geselecteerd met `retour_km == 0` → caption hidden (geen muted regel zonder waarde)
- Geen klant gekozen of klant heeft geen locaties → hele `locatie_row` hidden via `set_visibility(False)` (huidige flow)

#### Sectie 2 — Werk

```python
with ui.column().classes('settings-section w-full'):
    ui.label('Werk').classes('settings-section-title')
    with ui.grid(columns=2).classes('w-full gap-3'):
        code_select  # activiteit dropdown met humanized labels
        uren_input  # ui.number(...).classes('w-full')
    urennorm_check  # 'Telt mee voor urencriterium' — onder de grid
```

#### Sectie 3 — Vergoeding

```python
with ui.column().classes('settings-section w-full'):
    ui.label('Vergoeding').classes('settings-section-title')
    with ui.grid(columns=3).classes('w-full gap-3'):
        tarief_input = ui.number(
            'Tarief', value=..., format='%.2f', min=0, step=0.50,
            suffix='€/uur',
        ).classes('w-full')
        km_input = ui.number(
            'Km retour', value=..., min=0, step=1,
        ).classes('w-full')
        km_tarief_input = ui.number(
            'Km-tarief', value=..., format='%.2f', min=0, step=0.01,
            suffix='€/km',
        ).classes('w-full')
```

Korte labels (geen `(€/uur)` of `(€/km)` in label-tekst meer). Euro-suffix via NiceGUI's **native `suffix=` parameter** (NIET `.props('suffix=€/uur')` — Quasar-prop-string parser breekt op ongequote `€` en `/`).

### Totaal-strook (`.werkdag-totaal-strook`)

Tussen Vergoeding en Opmerking-textarea, **buiten** de drie `.settings-section` blokken (eigen visuele identiteit):

- Background: `var(--accent-soft)` (teal 10% tint)
- Border: 1px solid `rgba(15,118,110,0.18)` (subtiele teal-rand)
- Border-radius: 10px
- Padding: 14px 16px
- Layout: row, justify-between, items-center
- Linker kant (column, gap-1):
  - Label `Totaal` (font-weight 600, `color: var(--text)`, `font-size: 0.95rem`)
  - Breakdown muted (`color: var(--muted)`, `font-size: 0.85rem`, `font-variant-numeric: tabular-nums`):
    - Met data: `8,0u × € 90,00 + 50 km × € 0,23`
    - Zonder data: `Vul uren en tarief in`
- Rechter kant:
  - Bedrag groot (`color: var(--accent)`, `font-size: 1.25rem`, `font-weight: 700`, `font-variant-numeric: tabular-nums`):
    - Met data: `€ 731,50`
    - Zonder data: `€ 0,00`

### Opmerking (geen aparte sectie-titel)

Onder het totaal-strookje, geen `.settings-section` wrap — gewoon een vrijstaande textarea:

```python
opmerking_input = ui.textarea(
    label='Opmerking',
    value=werkdag.opmerking if is_edit else '',
).props('autogrow').classes('w-full werkdag-textarea')
```

CSS clamp:

```css
.werkdag-textarea .q-field__native {
    min-height: 36px;
    max-height: 96px; /* ~3 regels — voorkomt dat footer uit beeld glijdt */
    overflow-y: auto;
}
```

### Footer (`.werkdag-dialog-footer`)

- Padding: 14px 24px 18px
- Border-top: 1px solid `var(--border)`
- Layout: row, justify-end, gap-2
- Volgorde rechts → links:
  1. **Opslaan** — `unelevated color=primary`, save-icoon
  2. **Opslaan & Nieuw** — `outline color=primary`, add-icoon. Alleen renderen als `not is_edit and pattern_id is None`.
  3. **Annuleren** — `flat`. Op `dialog.close`.

## Activiteit-humanizer

Nieuwe pure helper in `domain/codes.py`:

```python
def humanize_legacy_code(code: str) -> str:
    """Render legacy/onbekende werkdag-codes menselijk leesbaar.

    Bestaande codes uit CODES blijven via CODES-lookup gerenderd; deze
    helper is alleen fallback voor codes die NIET in CODES zitten.

    Patronen (op basis van DB-realiteit 2026-05-09):
    - 'WDAGPRAKTIJK_NN[,NN]' (424× in DB) → 'Praktijkdienst (€ NN[,NN]/u)'
    - 'ANW_*' met _-segmenten (60×)        → 'ANW · seg1 · seg2 · ...'
    - 'AW-WK-A' / 'AW-WKND-*' (11×)        → 'AW · werkdag/weekend · X'
    - Vrije tekst kort (Admin, NSCHL, AQUI, REISTIJD, ...) → code.title()
    - Lege string                          → '(geen)'
    """
```

**Crucial invariant**: deze helper is *alleen voor display*. De opgeslagen DB-waarde is altijd de oorspronkelijke `code` string. Save-flow gebruikt `code_select.value`, niet de gehumaniseerde label.

UI-integratie via een **pure helper** in `domain/codes.py` (testbaar zonder NiceGUI):

```python
def build_code_options(existing_code: str | None) -> dict[str, str]:
    """Build dropdown options for werkdag activiteit.

    - Returns CODES dict (human labels per known code)
    - If `existing_code` is provided AND not in CODES (legacy/onbekend):
      adds entry `{existing_code: humanize_legacy_code(existing_code)}`
    - If `existing_code == ''`:
      adds entry `{'': '(geen)'}` — maakt expliciete "geen activiteit"-keuze
      mogelijk in dropdown ipv stille mute naar 'WERKDAG'
    """
```

In `werkdag_form.py`:

```python
existing_code = werkdag.code if is_edit else None
code_options = build_code_options(existing_code)
initial_code = werkdag.code if is_edit else 'WERKDAG'
```

### Save-flow voor legacy codes (NIET overschrijven)

Huidige save-flow doet `activiteit = CODES.get(code, 'Waarneming dagpraktijk')` — deze fallback **overschrijft historische `werkdag.activiteit`** bij edit-save van een legacy code (bv. `WDAGPRAKTIJK_77,50`'s activiteit-tekst gaat verloren). Fix:

```python
def derive_activiteit(code: str, current_activiteit: str | None) -> str:
    """Bepaal activiteit-tekst voor save.

    - Code in CODES → CODES[code] (canonical label)
    - Code niet in CODES → behoud current_activiteit als gegeven, anders humanize_legacy_code(code)
    - Lege code → behoud current_activiteit als gegeven, anders ''
    """
```

Save-flow:
```python
activiteit = derive_activiteit(
    code=code_select.value or '',
    current_activiteit=werkdag.activiteit if is_edit else None,
)
```

## Pure helper: Nederlandse datum-formatter

Bestaande `format_datum` in `components/utils.py` retourneert `09-05-2026` (numeriek). De header-subtitle wil "zaterdag 9 mei 2026". Niet uitvinden — gebruik `babel.dates.format_date(d, format='full', locale='nl_NL')`. Babel zit al in dependencies (controleer in pyproject.toml; anders fallback handmatig met dict van weekdagen + maanden).

Of: simpele eigen helper in `components/utils.py`:

```python
def format_datum_lang(iso_str: str) -> str:
    """'2026-05-09' → 'zaterdag 9 mei 2026'. Lege/ongeldige input → ''."""
```

— met handmatige NL-arrays voor weekdagen + maanden. Geen babel-dependency toevoegen.

## CSS — nieuw + cascade-discipline

Toe te voegen aan `components/layout.py` ui.add_css block, **buiten** `@layer components` (Quasar-cascade-rule):

```css
.q-card.werkdag-dialog-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0;  /* sections + header/body/footer hebben eigen padding */
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
    min-height: 70px;  /* reserve subtitle-room — voorkomt layout-shift */
}
.werkdag-dialog-title {
    font-size: 1.15rem;
    font-weight: 650;
    color: var(--text);
}
.werkdag-dialog-subtitle {
    font-size: 0.9rem;
    color: var(--muted);
    min-height: 1.2em; /* zelfde — geen springen bij lege/ongeldige datum */
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
.werkdag-totaal-strook {
    background: var(--accent-soft);
    border: 1px solid rgba(15, 118, 110, 0.18);
    border-radius: 10px;
    padding: 14px 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
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
}
.werkdag-totaal-bedrag {
    color: var(--accent);
    font-size: 1.25rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
.werkdag-textarea .q-field__native {
    min-height: 36px;
    max-height: 96px;
    overflow-y: auto;
}
```

## Behavior invariants

1. **Save-flow ongewijzigd**: gebruikt nog steeds `add_werkdag` / `update_werkdag` / `confirm_expected` (in pattern-mode). Validatie ongewijzigd: `kid` verplicht, `uren >= 0`, `tarief >= 0`. Errors via `ui.notify(type='warning')` / `'negative'`.
2. **Pattern-mode** (`prefill['pattern_id']` is set, vanuit `/agenda` Bevestigen-flow): `confirm_expected()` accepteert GEEN overrides — gebruikt pattern-defaults voor uren/tarief/km/code. UI moet daarom expliciet maken dat user-edits genegeerd worden:
   - **Datum-veld**: editable (user kan op andere datum bevestigen)
   - **Klant, Activiteit, Uren, Tarief, Km, Km-tarief, Urennorm, Opmerking**: alle disabled (`.props('readonly')` op inputs, `.props('disable')` op selects/checkboxes) zodat het visueel duidelijk is dat de waarden uit het patroon komen
   - **Helper-tekst** als `ui.label` boven sectie-1: *"Deze werkdag komt uit een terugkerend patroon. Bewerk het patroon via /agenda → Klant → Patronen."* (`color: var(--muted)`, `font-size: 0.85rem`)
   - **Footer-knop label**: "Bevestigen" ipv "Opslaan" (visueel signaal: dit is geen vrije save)
   - **Opslaan & Nieuw**: niet tonen (zoals huidig)
3. **Klant-change** triggert `_load_klant_data` async: locaties laden, tarief overschrijven met `klant.tarief_uur`, locatie-row tonen/verbergen, eerste locatie pre-selecteren met km auto-fill.
4. **Edit-mode** restoreert historische `tarief` en `km` uit `werkdag` row NA `_load_klant_data` (zodat klant-default niet stilletjes overschrijft — A6 invariant).
5. **Code-change**: `ACHTERWACHT` of `ZERO_UREN_CODES` → `urennorm_check.value = False` + `uren = 0` + `tarief = 0`.
6. **Datum-subtitle update**: `datum_input.on_value_change` triggert `update_subtitle()` die `format_datum_lang` aanroept en label-tekst zet. Lege/ongeldige input → leeg subtitle (min-height blijft).
7. **Totaal-update**: bestaand `update_totaal()` gedrag, maar nu split in `breakdown_label.text` (links muted) + `bedrag_label.text` (rechts groot teal). Lege state: breakdown="Vul uren en tarief in", bedrag="€ 0,00".
8. **Default focus** bij toevoegen (geen edit, geen klant-prefill): focus op `klant_select`. Edit-mode: geen auto-focus.
9. **Esc**: bestaande NiceGUI-default `dialog.on_dismiss` werkt. **Enter**: bestaand Quasar QInput gedrag. Niet expliciet handlen.
10. **Humanizer is alleen UI**: `code_select.value` wordt opgeslagen, label wordt gerenderd via `code_options[code]`.

## Testing approach

### Pure helpers (unit-tests, snel, geen NiceGUI)

`tests/test_codes.py` (`TestHumanizeLegacyCode`):
- `humanize_legacy_code('')` → `'(geen)'`
- `humanize_legacy_code('WDAGPRAKTIJK_70')` → `'Praktijkdienst (€ 70/u)'`
- `humanize_legacy_code('WDAGPRAKTIJK_77,50')` → `'Praktijkdienst (€ 77,50/u)'`
- `humanize_legacy_code('ANW_WEEKEND')` → `'ANW · weekend'`
- `humanize_legacy_code('ANW_DR_WERKDAG_NACHT_ACHTERWACHT')` → `'ANW · DR · werkdag · nacht · achterwacht'` (afkortingen capitalized blijven)
- `humanize_legacy_code('ANW_GR_WEEKEND_DAG')` → `'ANW · GR · weekend · dag'`
- `humanize_legacy_code('AW-WK-A')` → `'AW · werkdag · A'`
- `humanize_legacy_code('AW-WKND-A')` → `'AW · weekend · A'`
- `humanize_legacy_code('Admin')` → `'Admin'` (al titlecase)
- `humanize_legacy_code('REISTIJD')` → `'Reistijd'`
- `humanize_legacy_code('AQUI')` → `'AQUI'` (geen patroon, geen `_`/`-`, kort all-caps blijft)
- Smoke: alle 26 echte DB-codes leveren een non-empty string op.

`tests/test_codes.py` (`TestBuildCodeOptions`):
- `build_code_options(None)` → returns exactly `CODES` dict
- `build_code_options('WERKDAG')` → returns `CODES` (al aanwezig, geen extra entry)
- `build_code_options('WDAGPRAKTIJK_77,50')` → bevat `'WDAGPRAKTIJK_77,50': 'Praktijkdienst (€ 77,50/u)'` extra
- `build_code_options('')` → bevat `'': '(geen)'` extra
- `build_code_options('AQUI')` → bevat `'AQUI': 'AQUI'` extra (humanizer fallback)

`tests/test_codes.py` (`TestDeriveActiviteit`):
- `derive_activiteit('WERKDAG', None)` → `'Waarneming dagpraktijk'` (CODES lookup)
- `derive_activiteit('WERKDAG', 'Custom tekst')` → `'Waarneming dagpraktijk'` (canonical wins voor known codes)
- `derive_activiteit('WDAGPRAKTIJK_77,50', 'Praktijk Dr. X')` → `'Praktijk Dr. X'` (preserve historische tekst voor legacy)
- `derive_activiteit('WDAGPRAKTIJK_77,50', None)` → `'Praktijkdienst (€ 77,50/u)'` (humanizer fallback)
- `derive_activiteit('', 'Vrije tekst')` → `'Vrije tekst'` (preserve voor lege code)
- `derive_activiteit('', None)` → `''`

`tests/test_format_datum_lang.py`:
- `format_datum_lang('2026-05-09')` → `'zaterdag 9 mei 2026'`
- `format_datum_lang('')` → `''`
- `format_datum_lang('invalid')` → `''`
- `format_datum_lang('2026-12-31')` → `'donderdag 31 december 2026'`

### Save-flow regression-tests

`tests/test_werkdag_form.py` (`TestSaveFlowLegacyCode`):
- **Edit-save met legacy code**: assert dat `update_werkdag` aangeroepen wordt met `code='WDAGPRAKTIJK_77,50'` ÉN `activiteit=<historische tekst>` (niet overgeschreven naar `'Waarneming dagpraktijk'`). Mock `update_werkdag` om kwargs op te vangen.
- **Edit-save met lege code**: assert dat `code=''` blijft, niet stilletjes naar `'WERKDAG'` muteert.
- **Add met known code**: `code='WERKDAG'` → `activiteit='Waarneming dagpraktijk'` (canonical wins).

### Pattern-mode source-pin

`tests/test_werkdag_form.py` (`TestPatternMode`):
- Source-pin: in pattern-mode (`pattern_id` set) zijn klant/uren/tarief/km/code/opmerking inputs disabled (regex-grep: `props('readonly')` of `props('disable')` op de relevante elementen)
- Source-pin: button-label is `'Bevestigen'` ipv `'Opslaan'` in pattern-mode
- Source-pin: `Opslaan & Nieuw` knop wordt NIET aangemaakt in pattern-mode

Geen full-render tests (NiceGUI dialog niet headless testbaar zonder browser-driver). Source-pin = inspecteer `inspect.getsource(open_werkdag_dialog)` voor verwachte string-patronen.

### Visuele test

Manueel: start `python main.py`, klik op een werkdag-pill in /agenda, valideer:
1. Dialog opent op 680px breedte
2. Header toont titel + Nederlandse datum subtitle
3. Datum wijzigen → subtitle updates live
4. Drie sections gelijke styling als /instellingen
5. Klant kiezen → locatie-row verschijnt netjes (geen vervelende layout-shift)
6. Tarief/km/km-tarief gelijke breedte, € suffix in veld
7. Bedragen correct getoond met tabular-nums
8. Lege state: "€ 0,00 — Vul uren en tarief in"
9. Esc sluit, Enter triggert Opslaan
10. Opslaan & Nieuw verschijnt alleen voor non-edit non-pattern-mode
11. Activiteit-dropdown toont "Praktijkdienst (€ 77,50/u)" voor legacy code

### Cascade-test

`tests/test_visual_css.py` enforceert dat `.q-*` overrides buiten `@layer` staan. Nieuwe `.q-card.werkdag-dialog-card` selector moet die check halen.

## Files

| Pad | Wijziging |
|---|---|
| `domain/codes.py` | `+humanize_legacy_code()`, `+build_code_options()`, `+derive_activiteit()` pure helpers |
| `components/utils.py` | `+format_datum_lang()` helper |
| `components/layout.py` | `+ui.add_css(...)` blok met ~10 nieuwe classes (buiten @layer) |
| `components/werkdag_form.py` | Volledige redesign van `open_werkdag_dialog` body — header/sections/totaal/footer + pattern-mode disabled-state + legacy save-flow fix |
| `tests/test_codes.py` | `+TestHumanizeLegacyCode` (11 cases + smoke), `+TestBuildCodeOptions` (5 cases), `+TestDeriveActiviteit` (6 cases) |
| `tests/test_format_datum_lang.py` | NEW: 4 test cases |
| `tests/test_werkdag_form.py` | NEW: `TestSaveFlowLegacyCode` (3 cases) + `TestPatternMode` (3 source-pin cases) |

## Risico's & mitigaties (codex final-review feedback)

| Risico | Mitigatie |
|---|---|
| `ui.dialog()` styling lekt naar wrapper-laag (Quasar QDialog) | `.q-card.werkdag-dialog-card` chained selector buiten @layer |
| Layout-shift bij datum-leeg/ongeldig | `min-height` op `.werkdag-dialog-header` + `.werkdag-dialog-subtitle` |
| Long breakdown breekt totaal-strook | Linker `.werkdag-totaal-breakdown` mag wrappen; bedrag rechts heeft `white-space: nowrap` |
| Autogrow textarea duwt footer uit beeld | `max-height: 96px` (~3 regels) + `overflow-y: auto` |
| Locatie-row verschijnen/verdwijnen geeft layout-shift | `set_visibility` zoals huidig (geen animatie nodig — sectie wrapt) |
| Humanizer overschrijft DB-waarde stilletjes | UI gebruikt `code_options[code]` voor display, save gebruikt `code_select.value` (= raw code) |
| Quasar QInput suffix kan lelijk wrappen | NiceGUI native `suffix='€/uur'` parameter (NIET `.props('suffix=€/uur')`); manueel checken in dialog-context, fallback: helper-text |
