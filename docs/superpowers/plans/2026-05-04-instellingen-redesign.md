# /instellingen redesign — Sprint G Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Codex 4-layer review (per CLAUDE.md "Codex-samenwerking als kwaliteitsstandaard") draait per task.

**Spec:** `docs/superpowers/specs/2026-05-04-instellingen-redesign-design.md`

**Goal.** Visueel opfrissen van `/instellingen` (3 tabs) naar Apple-rustige settings-pagina via section-cards + section-blocks pattern, met behoud van alle bestaande validatie/save-flows.

**Architecture.** Twee nieuwe lokale CSS-classes (`settings-card`, `settings-section`) gebouwd op bestaande globale tokens. Bedrijfsgegevens-tab herstructureert van wand-van-inputs naar 4 section-cards met één gecombineerde Opslaan-knop. Logo-upload herbruikt bestaand hidden-upload + `pickFiles()` JS-trigger pattern uit `components/invoice_builder.py:691-701`. Fiscaal-tab krijgt subtielere `settings-section`-blocks per subgroep zonder de `ui.expansion`-per-jaar te raken. Backup-tab krijgt 2 cards inclusief copy-to-clipboard voor de DB-pad. Geen wijzigingen aan validation-logica, fiscale engine, of database-schema.

**Tech Stack.** NiceGUI 3.x + Quasar/Vue (Python-side), CSS custom properties (de 13 globale tokens), pytest-based cascade-lint regression test.

**Baseline.** Pytest 1298 groen, master HEAD `01cc2d9` (laatste spec-fix-commit). Sprint A→F + 2 post-merge audits afgerond.

---

## Architectuur-keuzes (lees eerst)

**1. Direct op master, geen feature-branch.** Project-conventie sinds Sprint A→F (zie `project_sprint_cdef.md`). Per-task atomic commits + Codex 4-layer review per task = veiligheidsnet. Werktree-isolatie zou over-engineering zijn voor 1-user app.

**2. Cascade-discipline verplicht.** `.settings-card` zit op een `ui.card` (Quasar `.q-card`). Mitigation = chained selector `.q-card.settings-card { ... }` + opname in `tests/test_visual_css.py:190 QUASAR_APPLIED_APP_CLASSES`-allow-list. Belt-and-suspenders. Zonder dit verliest `.settings-card` van Quasar's unlayered `.q-card`-defaults, wat in Sprint F al twee keer bewezen is gebeurd (`.alert-link`, `.severity-fg`).

**3. Logo-upload pattern verplicht reuse.** `components/invoice_builder.py:691-701` heeft een hidden-`ui.upload` + `getElement(id).$refs.qRef.pickFiles()` JS-trigger pattern dat in productie werkt sinds Sprint A. Niet opnieuw uitvinden — `ui.upload` zelf stylen leidt tot verloren tijd (de `q-uploader__list`/`q-uploader__header` Quasar-componenten zijn niet betrouwbaar weg te krijgen via CSS).

**4. Eén Opslaan onderaan Bedrijfsgegevens.** Codex-amendment: één logisch profiel = één save. Per-card-save zou riskante gedeeltelijke state op disk geven (bv. nieuwe naam wel, oud KvK-nummer nog). Dirty-state-indicator per card lost het visuele "wat is gewijzigd"-probleem op zonder split-save te vereisen.

**5. Dirty-state via `on('change')` per input → parent-card-class-mutation.** NiceGUI's `ui.input(on_change=...)` shortcut werkt voor input/checkbox/select. Closures binden parent-card aan elke input. Na succesvol save: loop door alle cards en `card.classes(remove='is-dirty')`.

**6. Fiscaal mini-cards = section-blocks (NIET volle cards).** Codex-amendment: card-in-expansion-in-card geeft visuele noise. `.settings-section` heeft lichte achtergrond + hairline border + geen schaduw. Veel zachter ritme dan `.settings-card`. Wel consistent grid-pattern (2-koloms voor velden) met Bedrijfsgegevens.

**7. PVV + Box 3 + AK-schijven uit `ui.row(flex-wrap)` naar grid binnen section.** Huidige inconsistentie: deze 3 groepen staan in losse rows naast de gegroepeerde grids. Naar 2-koloms `ui.grid` binnen hun eigen section trekken = visueel consistent met IB/Ondernemersaftrek/etc. AK-schijven blijft tabel-achtig (table-rows met w-32/w-44 widths) maar wel binnen section met juiste padding.

**8. Geen wijzigingen aan `_validate_fiscal_params` of `_validate_arbeidskorting_brackets`.** UI-wrapping verandert, validation-logica niet. `tests/test_instellingen.py` (45+ validation-tests) moet onveranderd groen blijven — dit is een pure UI-redesign, geen logic-refactor.

**9. Clipboard-copy voor DB-pad via `ui.run_javascript('navigator.clipboard.writeText(...)')`.** Browser-standard API, werkt in pywebview (WebKit). Geen extra dependency. NiceGUI/Quasar heeft geen native clipboard-helper.

**10. Geen tests-driven-development voor visuele UI.** TDD past hier slecht — visuele rendering kan niet headless getoetst worden. Wel:
- Cascade-lint tests in `tests/test_visual_css.py` (uitbreiding QUASAR_APPLIED_APP_CLASSES + nieuwe contract-test voor `.settings-card`/`.settings-section` definities)
- Bestaande `tests/test_instellingen.py` validation-tests blijven groen
- Manuele rooktest per tab (Task 6) door gebruiker in pywebview

---

## File Structure

| Pad | Verantwoordelijkheid | Mode |
|---|---|---|
| `components/layout.py` | Toevoegen van `.settings-card`/`.settings-section` CSS BUITEN `@layer components` (na de bestaande Sprint F unlayered block). Geen wijziging aan globale tokens. | modify |
| `tests/test_visual_css.py` | `'settings-card'` toevoegen aan `QUASAR_APPLIED_APP_CLASSES` (regel 190). Eén nieuwe contract-test die controleert dat `.settings-card`-definitie als chained selector `.q-card.settings-card` bestaat (anti-regressie tegen impliciete `.settings-card { ... }`-write). | modify |
| `pages/instellingen.py:272-403` | Bedrijfsgegevens tab: vervangen van wand-van-inputs door 4 section-cards + media-row logo + één Opslaan + dirty-state wiring. | modify |
| `pages/instellingen.py:405-871` | Fiscaal tab: subgroepen wrappen in `.settings-section`, PVV/Box3/AK uit losse `ui.row` naar grid binnen section, locked-banner BEM-fix (`alert-card alert-card--warning`). | modify |
| `pages/instellingen.py:873-921` | Backup tab: 2 `.settings-card`-blocks + copy-to-clipboard voor DB-pad. | modify |

---

## Task 1 — CSS foundation + cascade-lint regression

**Files:**
- Modify: `components/layout.py` (CSS toevoegen na bestaande Sprint F unlayered block, rond regel 446-450)
- Modify: `tests/test_visual_css.py:190` (uitbreiden allow-list + nieuwe contract-test)

**Doel.** CSS-classes `.settings-card` en `.settings-section` introduceren, cascade-veilig (chained selector + allow-list). Eén nieuwe regressie-test die de structuur enforced.

- [ ] **Step 1.1: Lees huidige `components/layout.py` Sprint F unlayered block + omgeving**

```bash
grep -n "Sprint F\|alert-card\|severity-card\|@layer components\|Quasar-overrules BUITEN" /Users/macbookpro_ronald/Library/CloudStorage/SynologyDrive-Main/06_Development/1_roberg-boekhouding/components/layout.py
```

Expected: laat zien waar `.alert-card .alert-icon` etc. zijn gedefinieerd in de "Quasar-overrules BUITEN @layer"-comment-block (rond regel 422-446).

- [ ] **Step 1.2: Schrijf de failing cascade-lint contract-test**

Voeg toe aan `tests/test_visual_css.py` direct ná `test_sprint_f_alert_severity_modifiers_complete` (rond regel 280):

```python
def test_sprint_g_settings_card_chained_selector():
    """Sprint G cascade-rule: .settings-card MUST be defined as chained
    selector .q-card.settings-card (not naked .settings-card) to win from
    Quasar's unlayered .q-card defaults via specificity + source order.

    Naked .settings-card { ... } would lose to .q-card { background: white }
    on equal specificity since Quasar declares its defaults later in the
    cascade. Same lesson as agenda-cell.holiday-marker (Sprint A) and
    .alert-link (Sprint F).
    """
    css = _strip_comments(_extract_css())

    # Naked .settings-card declaration without .q-card prefix would match
    # this regex; chained .q-card.settings-card would not.
    naked_pattern = r"(?<![.\w-])\.settings-card\s*\{"
    naked_matches = re.findall(naked_pattern, css)

    chained_pattern = r"\.q-card\.settings-card\s*\{"
    chained_matches = re.findall(chained_pattern, css)

    assert chained_matches, (
        "Sprint G: .settings-card MUST be defined as chained selector "
        ".q-card.settings-card { ... } in components/layout.py — naked "
        ".settings-card loses to Quasar's unlayered .q-card defaults."
    )
    assert not naked_matches, (
        f"Sprint G: found naked .settings-card definition(s). Use chained "
        f"selector .q-card.settings-card { { ... } } instead. Hits: {naked_matches}"
    )


def test_sprint_g_settings_section_defined():
    """Sprint G: .settings-section MUST be defined in CSS (no chained-
    selector requirement — applied to plain ui.column, not q-card)."""
    css = _strip_comments(_extract_css())
    pattern = r"\.settings-section\s*\{"
    matches = re.findall(pattern, css)
    assert matches, ".settings-section selector missing in components/layout.py"
```

- [ ] **Step 1.3: Run de twee nieuwe tests, verifieer dat ze falen**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_visual_css.py::test_sprint_g_settings_card_chained_selector tests/test_visual_css.py::test_sprint_g_settings_section_defined -v
```

Expected: 2 FAIL — beide met "missing"-melding.

- [ ] **Step 1.4: Voeg `.settings-card` aan `QUASAR_APPLIED_APP_CLASSES`-allow-list toe**

In `tests/test_visual_css.py:190-195`, vervang het hele `QUASAR_APPLIED_APP_CLASSES`-blok door:

```python
QUASAR_APPLIED_APP_CLASSES = [
    'nav-icon',         # used on `ui.icon(...)` in components/layout.py:_nav_item
    'alert-icon',       # used on `ui.icon(...)` in pages/dashboard.py
    'alert-link',       # used on `ui.button(...)` in pages/dashboard.py
    'severity-fg',      # used on `ui.icon(...)` + `ui.button(...)` in pages/dashboard.py
    'settings-card',    # Sprint G — applied to ui.card (= .q-card) in pages/instellingen.py
]
```

- [ ] **Step 1.5: Voeg de CSS toe aan `components/layout.py` BUITEN `@layer components`**

Plak het volgende blok DIRECT NA `.severity-card .severity-dark { color: var(--severity-dark); }` (eind van Sprint F unlayered block, na huidige regel 445-446) maar VÓÓR een eventuele `=== ... ===`-comment of EOF. Zoek de exact-locatie via:

```bash
grep -n "severity-card .severity-dark\|severity-card .severity-fg" components/layout.py | tail -3
```

Voeg toe:

```css
/* === Sprint G — /instellingen redesign (settings-card + settings-section)
   Defined OUTSIDE @layer components for cascade-safety. .settings-card is
   applied to ui.card (= .q-card), so chained selector .q-card.settings-card
   is required to win from Quasar's unlayered .q-card { background: white }.
   .settings-section sits on a plain ui.column — chained-selector not needed
   but kept here next to .settings-card for readability. */
.q-card.settings-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    box-shadow: var(--shadow);
    margin-bottom: 16px;
}
.q-card.settings-card .q-card__section {
    /* settings-card has its own padding; suppress Quasar's wrapper-pad */
    padding: 0;
}
.q-card.settings-card.is-dirty {
    /* Subtle visual cue when user has changed inputs but not yet saved */
    border-left: 3px solid var(--accent);
}
.settings-card-title {
    font-weight: 600;
    color: var(--text);
    margin-bottom: 4px;
    font-size: 1rem;
}
.settings-card-subtitle {
    color: var(--muted);
    font-size: 0.875rem;
    margin-bottom: 16px;
}
.settings-section {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: calc(var(--radius) * 0.66);
    padding: 16px;
    margin-bottom: 12px;
}
.settings-section-title {
    font-weight: 600;
    color: var(--text);
    margin-bottom: 12px;
    font-size: 0.95rem;
}
```

Het CSS leeft als plain string in een `ui.add_head_html('<style>...</style>')`-call elders in `layout.py`. Kijk eerst naar de bestaande structuur (`grep -n "add_head_html\|<style>" components/layout.py | head -5`) en plaats het nieuwe blok in dezelfde stylesheet-string.

- [ ] **Step 1.6: Run de hele suite — verifieer dat alle tests groen blijven én de 2 nieuwe pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1300 passed (1298 baseline + 2 nieuwe). Geen failures.

- [ ] **Step 1.7: Commit**

```bash
git add components/layout.py tests/test_visual_css.py
git commit -m "$(cat <<'EOF'
feat(sprint-g): CSS foundation settings-card + settings-section

Sprint G T1 — twee nieuwe lokale CSS-classes voor /instellingen redesign:
- .q-card.settings-card (chained selector — verliest niet van Quasar
  .q-card defaults), met .is-dirty modifier voor unsaved-state visual
- .settings-section (op ui.column, lichter ritme dan settings-card)

Cascade-discipline volgt Sprint B+F lessons: BUITEN @layer components,
chained selector waar nodig, allow-list opname in test_visual_css.

+2 regressie-tests:
- test_sprint_g_settings_card_chained_selector
- test_sprint_g_settings_section_defined

Pytest 1298 → 1300, geen regressies.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 1.8: Codex 4-layer review trigger**

Per CLAUDE.md verplicht voor non-trivial werk:

```bash
SKIP_CODEX_REVIEW= env -u OPENAI_API_KEY codex exec --sandbox read-only - <<'EOF'
Review de diff van HEAD (Sprint G T1 — CSS foundation). Specifieke vragen:
1. Cascade-discipline correct toegepast (chained selector + allow-list)?
2. Tokens correct hergebruikt (var(--surface), var(--border), etc.) of
   per ongeluk nieuwe globale tokens geintroduceerd?
3. .is-dirty modifier specificity sterk genoeg om te winnen van Quasar?
4. Selectors-naming consistent met bestaande Sprint F (.alert-card patroon)?
EOF
```

Bevindingen evalueren via `superpowers:receiving-code-review` principes. Echte bugs fixen vóór door naar Task 2.

---

## Task 2 — Bedrijfsgegevens tab redesign (4 cards + één Opslaan + dirty-state)

**Files:**
- Modify: `pages/instellingen.py:272-403` (de hele `with ui.tab_panel(tab_bedrijf):` block + helpers binnen `refresh_bedrijf`)

**Doel.** Vervang de huidige wand-van-10-inputs door 4 section-cards (Identiteit, Contact, Fiscaal & financieel, Logo & visueel) met 2-koloms grid-layouts, één gecombineerde Opslaan-knop onderaan, en dirty-state wiring per card. Logo-pattern zelf komt in Task 3 — gebruik in Task 2 een placeholder-`ui.column()` voor de logo-tile-locatie.

- [ ] **Step 2.1: Lees de huidige Bedrijfsgegevens-tab code**

```bash
sed -n '272,403p' pages/instellingen.py
```

Lees + begrijp: de bestaande validatie (IBAN/Naam/KvK), de tooltip-tekst voor de klant-kleur-toggle, en de huidige logo-card structuur (regel 352-401).

- [ ] **Step 2.2: Vervang het `refresh_bedrijf()`-body**

Vervang de hele body van `async def refresh_bedrijf()` (regel 275-403) door onderstaande structuur. Behoud de `bedrijf_container.clear()` en de `bg = await get_bedrijfsgegevens(DB_PATH)`-aanroep aan het begin, en behoud de save-button onderaan en logo-card onderaan (laatste 2 sub-blocks).

```python
async def refresh_bedrijf():
    bedrijf_container.clear()
    bg = await get_bedrijfsgegevens(DB_PATH)

    fields: dict = {}
    cards: list = []

    def _mark_dirty(card):
        """Returns a closure that marks the given card dirty on input change."""
        def _h():
            card.classes(add='is-dirty')
        return _h

    with bedrijf_container:
        ui.label('Deze gegevens worden gebruikt op facturen.').classes(
            'text-body2 text-grey q-mb-md')

        # ─── Card 1: Identiteit ─────────────────────────────────────
        with ui.card().classes('settings-card') as card_identiteit:
            cards.append(card_identiteit)
            ui.label('Identiteit').classes('settings-card-title')
            fields['bedrijfsnaam'] = ui.input(
                'Bedrijfsnaam',
                value=getattr(bg, 'bedrijfsnaam', '') or '',
                on_change=_mark_dirty(card_identiteit),
            ).classes('w-full')
            with ui.grid(columns=2).classes('w-full gap-4'):
                fields['naam'] = ui.input(
                    'Naam', value=getattr(bg, 'naam', '') or '',
                    on_change=_mark_dirty(card_identiteit))
                fields['functie'] = ui.input(
                    'Functie', value=getattr(bg, 'functie', '') or '',
                    on_change=_mark_dirty(card_identiteit))

        # ─── Card 2: Contact ────────────────────────────────────────
        with ui.card().classes('settings-card') as card_contact:
            cards.append(card_contact)
            ui.label('Contact').classes('settings-card-title')
            fields['adres'] = ui.input(
                'Adres', value=getattr(bg, 'adres', '') or '',
                on_change=_mark_dirty(card_contact),
            ).classes('w-full')
            with ui.grid(columns=2).classes('w-full gap-4'):
                fields['postcode_plaats'] = ui.input(
                    'Postcode + Plaats',
                    value=getattr(bg, 'postcode_plaats', '') or '',
                    on_change=_mark_dirty(card_contact))
                fields['telefoon'] = ui.input(
                    'Telefoon',
                    value=getattr(bg, 'telefoon', '') or '',
                    on_change=_mark_dirty(card_contact))
            fields['email'] = ui.input(
                'E-mail', value=getattr(bg, 'email', '') or '',
                on_change=_mark_dirty(card_contact),
            ).classes('w-full')

        # ─── Card 3: Fiscaal & financieel ───────────────────────────
        with ui.card().classes('settings-card') as card_fiscaal:
            cards.append(card_fiscaal)
            ui.label('Fiscaal & financieel').classes('settings-card-title')
            with ui.grid(columns=2).classes('w-full gap-4'):
                fields['kvk'] = ui.input(
                    'KvK-nummer', value=getattr(bg, 'kvk', '') or '',
                    on_change=_mark_dirty(card_fiscaal))
                fields['iban'] = ui.input(
                    'IBAN', value=getattr(bg, 'iban', '') or '',
                    on_change=_mark_dirty(card_fiscaal))
            fields['thuisplaats'] = ui.input(
                'Thuisplaats (voor reiskosten)',
                value=getattr(bg, 'thuisplaats', '') or '',
                on_change=_mark_dirty(card_fiscaal),
            ).classes('w-full')

        # ─── Card 4: Logo & visueel ─────────────────────────────────
        with ui.card().classes('settings-card') as card_visueel:
            cards.append(card_visueel)
            ui.label('Logo & visueel').classes('settings-card-title')

            # PLACEHOLDER — Task 3 vult dit met de logo media-row.
            # Voor Task 2 alleen een column-marker zodat de structuur
            # rendert en latere tasks de container kunnen vinden.
            logo_slot = ui.column().classes('w-full q-mb-md')

            # Klant-kleur-toggle (verhuisd uit eigen "Visuele instellingen"
            # subtitle — semantisch onderdeel van branding).
            fields['gebruik_klant_kleur_in_agenda'] = ui.checkbox(
                'Klant-kleuren tonen in agenda',
                value=bool(getattr(
                    bg, 'gebruik_klant_kleur_in_agenda', False)) if bg else False,
                on_change=_mark_dirty(card_visueel),
            )
            ui.label(
                'Als aan: agenda-cellen krijgen de kleur die per klant '
                'is ingesteld (via Klanten-dialog). Klanten zonder kleur '
                'en blockers/holidays blijven type-based gestyled.'
            ).classes('text-caption text-grey')

        # ─── Save handler — één Opslaan voor alle 4 cards ───────────
        async def save_bedrijf():
            kwargs = {}
            for k, v in fields.items():
                val = v.value
                if isinstance(val, bool):
                    kwargs[k] = int(val)
                else:
                    kwargs[k] = val or ''
            if not (kwargs.get('iban') or '').strip():
                ui.notify(
                    'IBAN mag niet leeg zijn — QR-betaallink zou stuk gaan '
                    'op alle volgende facturen',
                    type='negative', timeout=8)
                return
            if not (kwargs.get('naam') or '').strip():
                ui.notify('Naam mag niet leeg zijn', type='negative')
                return
            if not (kwargs.get('kvk') or '').strip():
                ui.notify('KvK-nummer mag niet leeg zijn', type='negative')
                return
            await upsert_bedrijfsgegevens(DB_PATH, **kwargs)
            for c in cards:
                c.classes(remove='is-dirty')
            ui.notify('Bedrijfsgegevens opgeslagen', type='positive')

        ui.button(
            'Wijzigingen opslaan', icon='save', on_click=save_bedrijf
        ).props('color=primary').classes('q-mt-md')

        # ─── Logo upload section (Task 3 vervangt deze placeholder) ──
        # NOTE: Task 3 verwijdert dit hele blok en bouwt de echte
        # media-row binnen `logo_slot` van card_visueel hierboven.
        with ui.card().classes('w-full q-mt-md'):
            ui.label('Bedrijfslogo (verhuist in Task 3 naar Logo & visueel-card)') \
                .classes('text-subtitle2 text-grey-8')
            ui.label(
                'Upload een logo dat op facturen wordt getoond.'
            ).classes('text-caption text-grey')

            logo_dir = DB_PATH.parent / 'logo'
            logo_dir.mkdir(parents=True, exist_ok=True)
            logo_files = list(logo_dir.glob('logo.*'))

            logo_preview = ui.column().classes('q-mt-sm')
            if logo_files:
                with logo_preview:
                    ui.image(
                        f'/logo-files/{logo_files[0].name}'
                    ).classes('w-48')

            async def handle_logo_upload(e):
                content = await e.file.read()
                ext = e.file.name.rsplit('.', 1)[-1].lower()
                target = logo_dir / f'logo.{ext}'
                tmp = logo_dir / f'.logo.new.{ext}'
                await asyncio.to_thread(tmp.write_bytes, content)
                for old in logo_dir.glob('logo.*'):
                    if old != tmp:
                        try:
                            await asyncio.to_thread(old.unlink)
                        except OSError:
                            pass
                await asyncio.to_thread(tmp.rename, target)
                logo_preview.clear()
                with logo_preview:
                    ui.image(
                        f'/logo-files/logo.{ext}'
                    ).classes('w-48')
                ui.notify('Logo opgeslagen', type='positive')

            ui.upload(
                label='Upload logo', auto_upload=True,
                on_upload=handle_logo_upload,
                max_file_size=5_000_000,
            ).props(
                'flat bordered accept=".png,.jpg,.jpeg,.svg"'
            ).classes('w-full q-mt-sm')
```

NOTE: het oude inline-logo-block blijft staan met een waarschuwingslabel zodat de logo-functionaliteit niet wegvalt tijdens Task 2-merge. Task 3 verwijdert dit blok.

- [ ] **Step 2.3: Run alle tests, verifieer 0 regressies**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1300 passed (zelfde count als na Task 1, geen nieuwe tests, geen regressies — `tests/test_instellingen.py` validation-tests blijven groen).

- [ ] **Step 2.4: Manuele rooktest (vraag user)**

```text
Open Boekhouding.app (sluit eerst evt. lopende instance via Activity Monitor → Python → Quit, of `lsof -tiTCP:8085 | xargs kill`).
Navigeer naar /instellingen → tab Bedrijfsgegevens.
Verifieer:
- 4 section-cards zichtbaar onder elkaar (Identiteit / Contact / Fiscaal & financieel / Logo & visueel)
- Velden in 2-koloms grid waar gespec'd
- Wijzig een veld: linker-rand van die card krijgt accent-border (dirty-state)
- Klik "Wijzigingen opslaan": dirty-borders verdwijnen, toast verschijnt
- Validatie werkt: leeg IBAN/Naam/KvK weigert opslaan met negative toast
- Logo-upload (oude placeholder onder de save-knop) werkt nog (tijdelijk)
- Klant-kleur-toggle in Logo & visueel-card werkt + persisteert
```

User rapporteert (a) ✓ alles werkt, (b) iets specifiek dat fout is. Bij (b) → fix + re-test vóór commit.

- [ ] **Step 2.5: Commit**

```bash
git add pages/instellingen.py
git commit -m "$(cat <<'EOF'
feat(sprint-g): Bedrijfsgegevens tab — 4 cards + één Opslaan + dirty-state

Sprint G T2 — herstructureer Bedrijfsgegevens-tab van wand-van-10-inputs
naar 4 section-cards (Identiteit / Contact / Fiscaal & financieel / Logo
& visueel). Eén gecombineerde Opslaan onderaan ipv inline-per-card —
voorkomt gedeeltelijke profiel-state op disk (Codex-amendment).

Dirty-state via on_change-closures per veld → parent-card.classes(add=
'is-dirty'); na succesvol save → remove='is-dirty' op alle cards.

Klant-kleur-toggle verhuisd uit eigen "Visuele instellingen" subtitle
naar Logo & visueel-card (semantisch onderdeel van branding).

Logo-upload-card blijft tijdelijk staan onder de Opslaan-knop met
waarschuwingslabel. Task 3 vervangt het door media-row pattern in de
Logo & visueel-card zelf.

Pytest 1300, geen regressies. Validation-logica (IBAN/Naam/KvK) ongewijzigd.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2.6: Codex 4-layer review trigger**

```bash
env -u OPENAI_API_KEY codex exec --sandbox read-only - <<'EOF'
Review de diff van HEAD (Sprint G T2 — Bedrijfsgegevens 4 cards). Specifieke vragen:
1. Dirty-state wiring correct? Closure-pattern per card, klopt
   on_change=_mark_dirty(card) call-time bind?
2. Save-handler validation order: blocked saves (negative toast)
   raken NIET de dirty-state — bedoelde gedrag?
3. Card-decompositie semantisch correct of zou een veld in een
   andere card horen (bv. Thuisplaats in Contact ipv Fiscaal)?
4. ui.input(on_change=...)-shortcut bestaat in NiceGUI 3.x — of
   moet het .on('update:model-value', ...) zijn?
EOF
```

Bevindingen evalueren. Bij echte bugs: fix + amend commit (NIET --amend op de gepushte commit als die al gepushed is — gebruik nieuwe commit).

---

## Task 3 — Logo media-row pattern (hidden ui.upload + pickFiles JS-trigger)

**Files:**
- Modify: `pages/instellingen.py` Bedrijfsgegevens-tab (binnen `card_visueel` `logo_slot`-container, en verwijder oude logo-card onder save-knop)

**Doel.** Vervang de placeholder + oude logo-upload-card door media-row pattern: framed 96×96 preview links + "Logo vervangen" knop rechts + "Verwijderen" link, gebruikmakend van het hidden-`ui.upload` + `getElement().pickFiles()` JS-trigger pattern uit `components/invoice_builder.py:691-701`.

- [ ] **Step 3.1: Lees het bestaande pattern in invoice_builder.py:685-705**

```bash
sed -n '685,710p' /Users/macbookpro_ronald/Library/CloudStorage/SynologyDrive-Main/06_Development/1_roberg-boekhouding/components/invoice_builder.py
```

Bestudeer: hidden-uploader styling, on_upload-handler, pickFiles JS-string-pattern, hoe de zichtbare knop de hidden uploader triggert.

- [ ] **Step 3.2: Vervang `logo_slot`-content + verwijder oude logo-card**

In `pages/instellingen.py` Task 2's `card_visueel` block — vervang de regel:

```python
            logo_slot = ui.column().classes('w-full q-mb-md')
```

door:

```python
            # ─── Logo media-row (hidden upload + JS pickFiles trigger) ─
            logo_dir = DB_PATH.parent / 'logo'
            logo_dir.mkdir(parents=True, exist_ok=True)
            logo_files = list(logo_dir.glob('logo.*'))
            current_logo = logo_files[0] if logo_files else None

            # Hidden ui.upload — wordt JS-side getriggerd via pickFiles()
            async def handle_logo_upload(e):
                content = await e.file.read()
                ext = e.file.name.rsplit('.', 1)[-1].lower()
                target = logo_dir / f'logo.{ext}'
                tmp = logo_dir / f'.logo.new.{ext}'
                await asyncio.to_thread(tmp.write_bytes, content)
                for old in logo_dir.glob('logo.*'):
                    if old != tmp:
                        try:
                            await asyncio.to_thread(old.unlink)
                        except OSError:
                            pass
                await asyncio.to_thread(tmp.rename, target)
                ui.notify('Logo opgeslagen', type='positive')
                await refresh_bedrijf()  # Re-render om preview te updaten

            _logo_upload = ui.upload(
                label='', auto_upload=True,
                on_upload=handle_logo_upload,
                max_file_size=5_000_000,
            ).props('flat accept=".png,.jpg,.jpeg,.svg"')
            _logo_upload.style(
                'visibility: hidden; height: 0; overflow: hidden;'
                ' position: absolute;')

            _pick_logo_js = (
                f'() => getElement({_logo_upload.id})'
                f'.$refs.qRef.pickFiles()')

            # Media-row: preview links | knop + info + verwijder rechts
            with ui.row().classes(
                'w-full items-center q-gutter-md q-mb-md'
            ):
                # Framed preview (klikbaar — opent ook file-picker)
                preview_box = ui.element('div').style(
                    'width: 96px; height: 96px; border-radius: 8px;'
                    ' border: 1px solid var(--border);'
                    ' background: var(--bg);'
                    ' display: flex; align-items: center;'
                    ' justify-content: center; overflow: hidden;'
                    ' cursor: pointer;')
                with preview_box:
                    if current_logo:
                        ui.image(f'/logo-files/{current_logo.name}').style(
                            'max-width: 96px; max-height: 96px;'
                            ' object-fit: contain;')
                    else:
                        ui.icon('image_not_supported').classes(
                            'text-grey').style('font-size: 32px;')
                preview_box.on('click', _pick_logo_js)

                # Right: button + file-info + delete-link
                with ui.column().classes('items-start gap-1'):
                    ui.button(
                        'Logo vervangen', icon='upload',
                        on_click=_pick_logo_js,
                    ).props('flat color=primary')
                    if current_logo:
                        size_kb = current_logo.stat().st_size // 1024
                        ui.label(
                            f'{current_logo.name} · {size_kb} KB'
                        ).classes('text-caption text-grey')

                        async def delete_logo():
                            try:
                                await asyncio.to_thread(current_logo.unlink)
                            except OSError as ex:
                                ui.notify(
                                    f'Kon logo niet verwijderen: {ex}',
                                    type='negative')
                                return
                            ui.notify('Logo verwijderd', type='positive')
                            await refresh_bedrijf()

                        ui.button(
                            'Verwijderen', on_click=delete_logo,
                        ).props('flat dense color=negative size=sm')
                    else:
                        ui.label('Geen logo geüpload').classes(
                            'text-caption text-grey')
```

- [ ] **Step 3.3: Verwijder de oude logo-card onder de save-knop**

Verwijder het hele `with ui.card().classes('w-full q-mt-md'):`-blok dat begint met `ui.label('Bedrijfslogo (verhuist in Task 3 ...')` en eindigt na de oude `ui.upload(...).props(...).classes(...)`-aanroep (in Task 2 toegevoegd als placeholder).

Verifieer:

```bash
grep -n "Bedrijfslogo (verhuist in Task 3" pages/instellingen.py
```

Expected: 0 hits na verwijdering.

- [ ] **Step 3.4: Run alle tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1300 passed.

- [ ] **Step 3.5: Manuele rooktest (vraag user)**

```text
Restart Boekhouding.app, navigeer naar /instellingen → Bedrijfsgegevens.
Verifieer:
- "Logo & visueel"-card bevat nu een framed 96×96 preview (of placeholder-icon "image_not_supported" als geen logo)
- Klik "Logo vervangen" knop: file-picker opent (macOS native dialog)
- Selecteer een PNG/JPG: upload werkt, preview update zichtbaar
- Klik direct op de preview-box: zelfde file-picker opent (a11y)
- "Verwijderen" knop verwijdert het logo + preview wisselt naar placeholder
- Geen oude logo-upload-card meer onder de save-knop
- Card-volgorde: Identiteit / Contact / Fiscaal & financieel / Logo & visueel / [save-knop]
```

User rapporteert. Bij issue → fix vóór commit.

- [ ] **Step 3.6: Commit**

```bash
git add pages/instellingen.py
git commit -m "$(cat <<'EOF'
feat(sprint-g): Logo media-row in Bedrijfsgegevens — hidden upload pattern

Sprint G T3 — vervang oude losse logo-card door media-row binnen
"Logo & visueel"-card: framed 96×96 preview links, "Logo vervangen"
knop + bestandsinfo + "Verwijderen" rechts. Beide knop én preview-box
triggeren een hidden ui.upload via getElement(id).$refs.qRef.pickFiles()
JS-pattern (verplicht reuse uit components/invoice_builder.py:691-701).

Geen ui.upload-styling (Quasar-coupled, niet betrouwbaar te overrulen).
Klik-op-preview opent ook picker = a11y win.

Refresh-bedrijf-na-upload zorgt voor zichtbare preview-update.

Pytest 1300, geen regressies.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3.7: Codex 4-layer review trigger**

```bash
env -u OPENAI_API_KEY codex exec --sandbox read-only - <<'EOF'
Review de diff van HEAD (Sprint G T3 — Logo media-row). Specifieke vragen:
1. Hidden-upload pattern correct gebruikt (visibility:hidden + height:0 +
   position:absolute)? Of leakt 't visueel ergens?
2. JS-trigger string correct (`getElement({id}).$refs.qRef.pickFiles()`)
   — id-interpolatie via Python f-string is veilig (id is een int)?
3. preview_box click-handler accepteert ook JS-string als handler?
   Of moet 't anders (lambda + ui.run_javascript)?
4. delete_logo handler thread-safety: race tussen unlink en read in
   parallel session — relevant voor 1-user lokale app?
5. refresh_bedrijf() na upload/delete — re-render is OK of zou een
   gerichte preview-update efficiënter zijn?
EOF
```

---

## Task 4 — Fiscale parameters tab — section-blocks + grid-consistency + locked-banner BEM-fix

**Files:**
- Modify: `pages/instellingen.py:405-871` (de hele `with ui.tab_panel(tab_fiscaal):` block)

**Doel.** Wrap elke subgroep binnen elke jaar-expansion in een `.settings-section`-block. Trek PVV/Box3/AK uit losse `ui.row()` naar consistente 2-koloms grid binnen hun section. Fix locked-banner naar BEM-naming (`alert-card alert-card--warning`).

- [ ] **Step 4.1: Lees de huidige Fiscaal-tab code**

```bash
sed -n '405,871p' pages/instellingen.py | head -100
```

Identificeer de 9 subgroepen die elk een section moeten worden:
1. IB Schijven
2. Ondernemersaftrek
3. Investeringsaftrek (KIA)
4. Heffingskortingen
5. ZVW
6. Eigen woning
7. Overig per jaar
8. Toggles & partner (gemerged: ZA/SA + EW/Box3 partner — Codex amendment §B in spec)
9. PVV premies
10. Box 3 parameters
11. Arbeidskorting schijven

(Plus de locked-banner aan het begin van elke jaar-expansion.)

- [ ] **Step 4.2: Fix locked-banner BEM-naming (regel ~518-525)**

Vervang:

```python
                if is_locked:
                    ui.label(
                        f'Jaar {params.jaar} is definitief'
                        ' afgesloten. Heropen via'
                        ' /jaarafsluiting om te wijzigen.'
                    ).classes(
                        'text-warning text-weight-medium'
                        ' q-mb-sm')
```

door:

```python
                if is_locked:
                    with ui.row().classes(
                        'alert-card alert-card--warning items-center'
                        ' q-gutter-sm q-mb-md'
                    ):
                        ui.icon('warning').classes('alert-icon')
                        with ui.column().classes('gap-0'):
                            ui.label(f'Jaar {params.jaar} is definitief afgesloten').classes(
                                'alert-title')
                            ui.label('Heropen via /jaarafsluiting om te wijzigen.').classes(
                                'alert-body')
```

- [ ] **Step 4.3: Wrap de `grouped_fields` loop (regel ~526-589) in `.settings-section`-blocks per groep**

Vervang de bestaande `with ui.grid(columns=2).classes('gap-2 w-full'):` + de loop binnen die section-fields-extraction door een per-groep section-wrap. Nieuwe structuur:

```python
                # Per-section grouped fields rendering
                grouped_fields = [
                    ('IB Schijven', [...]),  # zelfde lijst als nu
                    ('Ondernemersaftrek', [...]),
                    ('Investeringsaftrek (KIA)', [...]),
                    ('Heffingskortingen', [...]),
                    ('ZVW', [...]),
                    ('Eigen woning', [...]),
                    ('Overig per jaar', [...]),
                ]
                fields = []
                inputs = {}

                for section_label, section_fields in grouped_fields:
                    with ui.column().classes('settings-section w-full'):
                        ui.label(section_label).classes('settings-section-title')
                        with ui.grid(columns=2).classes('w-full gap-3'):
                            for label, key, fmt, step in section_fields:
                                fields.append((label, key))
                                val = getattr(params, key)
                                inp = ui.number(
                                    label, value=val if val is not None else 0,
                                    format=fmt, step=step,
                                ).classes('w-full')
                                if is_locked:
                                    inp.props('readonly')
                                inputs[key] = inp
```

(Behoud de bestaande `grouped_fields` data — de inhoud van de tuples blijft hetzelfde.)

- [ ] **Step 4.4: Merge "Ondernemersaftrek toggles" + "Partner toedeling" naar één section "Toggles & partner" (regel ~590-621)**

Vervang het hele blok van regel ~590 t/m ~621 (de twee `ui.label('text-subtitle2')` + checkboxes voor ZA/SA + EW/Box3 partner) door:

```python
                with ui.column().classes('settings-section w-full'):
                    ui.label('Toggles & partner').classes('settings-section-title')
                    with ui.column().classes('w-full gap-2'):
                        za_cb = ui.checkbox(
                            'Zelfstandigenaftrek (ZA) actief',
                            value=bool(params.za_actief),
                        )
                        if is_locked:
                            za_cb.props('disable')
                        inputs['za_actief'] = za_cb

                        sa_cb = ui.checkbox(
                            'Startersaftrek (SA) actief — max 3× in eerste 5 jaar',
                            value=bool(params.sa_actief),
                        )
                        if is_locked:
                            sa_cb.props('disable')
                        inputs['sa_actief'] = sa_cb

                        ew_partner_cb = ui.checkbox(
                            'Eigen woning saldo aan partner toerekenen',
                            value=bool(params.ew_naar_partner),
                        )
                        if is_locked:
                            ew_partner_cb.props('disable')
                        inputs['ew_naar_partner'] = ew_partner_cb

                        box3_partner_cb = ui.checkbox(
                            'Box 3 fiscaal partner (verdeling 50/50 mogelijk)',
                            value=bool(params.box3_fiscaal_partner),
                        )
                        if is_locked:
                            box3_partner_cb.props('disable')
                        inputs['box3_fiscaal_partner'] = box3_partner_cb
```

- [ ] **Step 4.5: PVV premies section (regel ~622-639) — wrap + grid**

Vervang:

```python
                ui.label('PVV premies').classes('text-subtitle2 mt-4')
                pvv_fields = [
                    ('AOW premie %', 'pvv_aow_pct'),
                    ('Anw premie %', 'pvv_anw_pct'),
                    ('Wlz premie %', 'pvv_wlz_pct'),
                ]
                with ui.row().classes('gap-4'):
                    for label, key in pvv_fields:
                        val = getattr(params, key)
                        inp = ui.number(
                            label,
                            value=val if val is not None else 0,
                            format='%.2f', step=0.01,
                        )
                        if is_locked:
                            inp.props('readonly')
                        inputs[key] = inp
```

door:

```python
                with ui.column().classes('settings-section w-full'):
                    ui.label('PVV premies').classes('settings-section-title')
                    pvv_fields = [
                        ('AOW premie %', 'pvv_aow_pct'),
                        ('Anw premie %', 'pvv_anw_pct'),
                        ('Wlz premie %', 'pvv_wlz_pct'),
                    ]
                    with ui.grid(columns=2).classes('w-full gap-3'):
                        for label, key in pvv_fields:
                            val = getattr(params, key)
                            inp = ui.number(
                                label,
                                value=val if val is not None else 0,
                                format='%.2f', step=0.01,
                            ).classes('w-full')
                            if is_locked:
                                inp.props('readonly')
                            inputs[key] = inp
```

- [ ] **Step 4.6: Box 3 parameters section (regel ~640-666) — wrap + grid**

Vervang:

```python
                ui.label('Box 3 parameters').classes('text-subtitle2 mt-4')
                box3_fields = [...]
                with ui.row().classes('gap-4 flex-wrap'):
                    for label, key, fmt, step in box3_fields:
                        ...
```

door:

```python
                with ui.column().classes('settings-section w-full'):
                    ui.label('Box 3 parameters').classes('settings-section-title')
                    box3_fields = [
                        ('Heffingsvrij vermogen p.p. €',
                         'box3_heffingsvrij_vermogen', '%.0f', 1),
                        ('Rendement bank %',
                         'box3_rendement_bank_pct', '%.2f', 0.01),
                        ('Rendement overig %',
                         'box3_rendement_overig_pct', '%.2f', 0.01),
                        ('Rendement schuld %',
                         'box3_rendement_schuld_pct', '%.2f', 0.01),
                        ('Box 3 tarief %',
                         'box3_tarief_pct', '%.0f', 1),
                        ('Box 3 drempel schulden p.p. €',
                         'box3_drempel_schulden', '%.0f', 100),
                    ]
                    with ui.grid(columns=2).classes('w-full gap-3'):
                        for label, key, fmt, step in box3_fields:
                            val = getattr(params, key)
                            inp = ui.number(
                                label,
                                value=val if val is not None else 0,
                                format=fmt, step=step,
                            ).classes('w-full')
                            if is_locked:
                                inp.props('readonly')
                            inputs[key] = inp
```

- [ ] **Step 4.7: Arbeidskorting schijven section (regel ~668-797) — wrap rond bestaande logica**

Wrap de hele bestaande arbeidskorting-block (van `ui.label('Arbeidskorting schijven')` tot en met de `add_bracket_btn`) in een `.settings-section`. Vervang de eerste regel:

```python
                ui.label('Arbeidskorting schijven').classes(
                    'text-subtitle2 mt-4')
```

door:

```python
                with ui.column().classes('settings-section w-full'):
                    ui.label('Arbeidskorting schijven').classes(
                        'settings-section-title')
```

en indenteer de rest van het AK-blok één niveau dieper (van `ui.label('Schijven moeten oplopend ...')` t/m `add_bracket_btn = ui.button(...)`).

Pas op: het `# Capture all_fields for save closure`-blok (regel ~798) en alles daarna (save_params + save_btn) MAG NIET binnen de `with ui.column().classes('settings-section w-full'):` indenteren — dat blijft op het oude indent-niveau (binnen de jaar-expansion, buiten de AK-section).

- [ ] **Step 4.8: Run alle tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1300 passed. Validation-tests in `tests/test_instellingen.py` blijven groen — alleen UI-wrapping verandert, geen logic.

- [ ] **Step 4.9: Manuele rooktest**

```text
Restart Boekhouding.app, /instellingen → tab Fiscale parameters.
Verifieer per jaar-expansion:
- Locked-banner (definitieve jaren) renderen als alert-card--warning
  (geel/oranje achtergrond, warning-icon links)
- Elke subgroep (IB, Ondernemersaftrek, KIA, Heffingskortingen, ZVW,
  Eigen woning, Overig per jaar, Toggles & partner, PVV, Box 3,
  Arbeidskorting schijven) is een eigen .settings-section block
  (lichte grijze achtergrond, hairline border, geen schaduw)
- 2-koloms grid binnen elke section voor velden
- PVV en Box 3 nu in grid (waren losse rows)
- AK-schijven tabel rendert correct binnen section-padding
- "Opslaan {jaar}" knop onderaan elke expansion blijft werken
- Add-jaar toolbar bovenaan onveranderd
```

- [ ] **Step 4.10: Commit**

```bash
git add pages/instellingen.py
git commit -m "$(cat <<'EOF'
feat(sprint-g): Fiscaal tab — section-blocks per subgroep + BEM-fix

Sprint G T4 — herstructureer Fiscale parameters-tab:
- Elke subgroep binnen jaar-expansion krijgt eigen .settings-section
  block (lichte bg + hairline border, geen schaduw — Codex amendment:
  subtieler dan settings-card om card-in-expansion-in-card visuele
  noise te voorkomen)
- PVV en Box 3 uit losse ui.row(flex-wrap) naar 2-koloms grid binnen
  hun section — visuele consistentie met IB/KIA/Heffingskortingen/etc.
- Toggles ZA/SA + Partner toedeling EW/Box3 gemerged in één section
  "Toggles & partner"
- Locked-banner BEM-fix: oude `text-warning text-weight-medium` →
  alert-card alert-card--warning structuur (Sprint F class reuse)

Geen wijzigingen aan _validate_fiscal_params of _validate_arbeidskorting
_brackets — pure UI-wrapping. Pytest 1300, validation-tests groen.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4.11: Codex 4-layer review trigger**

```bash
env -u OPENAI_API_KEY codex exec --sandbox read-only - <<'EOF'
Review de diff van HEAD (Sprint G T4 — Fiscaal section-blocks).
Specifieke vragen:
1. Indentation/scoping correct na de section-wrap? save_params closure
   ziet alle inputs (inputs dict) en bracket_state nog steeds?
2. Locked-banner alert-card--warning rendering — werken alert-icon
   en alert-title classes correct in deze context (waren tot nu toe
   alleen op /dashboard gebruikt)?
3. Per-section .settings-section visueel echt subtieler dan
   .settings-card, of conflicteert de border + bg met de jaar-expansion's
   eigen border?
4. Box 3 grid: 6 velden in 2-koloms grid = 3 rijen — leesbaar of te
   wide bij narrower windows (max-width: 7xl is 80rem in Tailwind)?
EOF
```

---

## Task 5 — Backup tab — 2 cards + clipboard-copy

**Files:**
- Modify: `pages/instellingen.py:873-921` (de hele `with ui.tab_panel(tab_backup):` block)

**Doel.** Vervang de spartaanse Backup-tab door 2 `.settings-card`-blocks: één voor download-actie + uitleg, één voor DB-locatie met copy-to-clipboard knop.

- [ ] **Step 5.1: Lees de huidige Backup-tab code**

```bash
sed -n '873,921p' pages/instellingen.py
```

- [ ] **Step 5.2: Vervang het hele `with ui.tab_panel(tab_backup):`-blok**

Vervang regels 873-921 door:

```python
            with ui.tab_panel(tab_backup):
                with ui.column().classes('w-full gap-4'):

                    # ─── Card 1: Backup downloaden ───────────────────
                    with ui.card().classes('settings-card'):
                        ui.label('Database backup').classes('settings-card-title')
                        ui.label(
                            'Download een atomaire snapshot van de database en alle '
                            'bijbehorende bestanden. Bewaar backups buiten deze machine '
                            '(externe schijf, NAS, of cloudmap). NB: deze snapshot is '
                            'veilig tijdens gebruik — geen WAL races.'
                        ).classes('settings-card-subtitle')

                        async def download_backup():
                            if not DB_PATH.exists():
                                ui.notify('Database niet gevonden', type='warning')
                                return

                            stem = f"boekhouding_backup_{date.today().isoformat()}"
                            tmp_dir = Path(tempfile.mkdtemp(prefix='boekhouding_backup_'))
                            dump_path = tmp_dir / f"{stem}.sqlite3"
                            zip_path = tmp_dir / f"{stem}.zip"

                            safe_dump_path = str(dump_path).replace("'", "''")
                            async with get_db_ctx(DB_PATH) as conn:
                                await conn.execute(f"VACUUM INTO '{safe_dump_path}'")

                            def _create_zip():
                                with zipfile.ZipFile(
                                    zip_path, 'w', zipfile.ZIP_DEFLATED
                                ) as zf:
                                    zf.write(dump_path, 'boekhouding.sqlite3')
                                    for subdir in [
                                        'facturen', 'uitgaven', 'jaarafsluiting',
                                        'bank_csv', 'aangifte', 'logo',
                                    ]:
                                        dir_path = DB_PATH.parent / subdir
                                        if dir_path.exists():
                                            for f in dir_path.rglob('*'):
                                                if f.is_file():
                                                    zf.write(
                                                        f,
                                                        f"{subdir}/"
                                                        f"{f.relative_to(dir_path)}")

                            await asyncio.to_thread(_create_zip)
                            ui.download(str(zip_path))
                            ui.notify(
                                f'Backup {zip_path.name} aangemaakt',
                                type='positive')

                            async def _cleanup():
                                await asyncio.sleep(300)
                                shutil.rmtree(tmp_dir, ignore_errors=True)
                            asyncio.create_task(_cleanup())

                        ui.button(
                            'Download backup', icon='download',
                            on_click=download_backup,
                        ).props('color=primary')

                    # ─── Card 2: Database-locatie + copy-to-clipboard ─
                    with ui.card().classes('settings-card'):
                        ui.label('Database-locatie').classes('settings-card-title')
                        ui.label(
                            'Locatie van de SQLite-database op deze machine. '
                            'Bewaar backups (zie boven) buiten deze locatie.'
                        ).classes('settings-card-subtitle')

                        db_path_str = str(DB_PATH.resolve())

                        with ui.row().classes(
                            'w-full items-center q-gutter-sm'
                        ):
                            ui.label(db_path_str).style(
                                'font-family: "SF Mono", Menlo, monospace;'
                                ' font-size: 13px;'
                                ' background: var(--bg);'
                                ' padding: 8px 12px;'
                                ' border-radius: 6px;'
                                ' border: 1px solid var(--border);'
                                ' user-select: text;'
                                ' flex: 1;'
                                ' overflow-x: auto;')

                            def copy_path():
                                # Pywebview WebKit ondersteunt navigator.clipboard
                                ui.run_javascript(
                                    f'navigator.clipboard.writeText('
                                    f'{json.dumps(db_path_str)})')
                                ui.notify('Pad gekopieerd naar klembord',
                                          type='positive')

                            ui.button(
                                icon='content_copy', on_click=copy_path,
                            ).props('flat dense round').tooltip('Kopieer pad')
```

NOTE: `import json` is al bovenaan `pages/instellingen.py` aanwezig (regel 5). Geen extra import nodig.

- [ ] **Step 5.3: Run alle tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -q
```

Expected: 1300 passed.

- [ ] **Step 5.4: Manuele rooktest**

```text
Restart Boekhouding.app, /instellingen → tab Backup.
Verifieer:
- 2 settings-cards onder elkaar
- Card 1: title "Database backup", uitleg-paragraaf, primary
  "Download backup" knop. Klik werkt — zip-file gedownload.
- Card 2: title "Database-locatie", uitleg, monospace path in
  een grijze code-style box met copy-icon ernaast
- Klik copy-icon: macOS toast "Pad gekopieerd naar klembord",
  Cmd+V in een ander venster plakt het pad
```

- [ ] **Step 5.5: Commit**

```bash
git add pages/instellingen.py
git commit -m "$(cat <<'EOF'
feat(sprint-g): Backup tab — 2 cards + clipboard-copy DB-pad

Sprint G T5 — herstructureer Backup-tab van losse labels + knop naar
2 .settings-cards: één voor backup-download met uitleg + primary knop,
één voor DB-locatie met monospace path in code-styled box + clipboard-
copy via navigator.clipboard.writeText (WebKit/pywebview-compatible).

Geen functionele wijziging aan VACUUM INTO snapshot-flow.

Pytest 1300, geen regressies.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5.6: Codex 4-layer review trigger**

```bash
env -u OPENAI_API_KEY codex exec --sandbox read-only - <<'EOF'
Review de diff van HEAD (Sprint G T5 — Backup tab cards).
Specifieke vragen:
1. navigator.clipboard.writeText werkt in pywebview WebKit? Of is een
   fallback nodig (oude execCommand)?
2. json.dumps voor JS-string-escape correct (escapet quotes/backslashes
   in DB-pad)?
3. Cleanup-task `asyncio.create_task(_cleanup())` — werkt nog na
   dialog/tab change of kan 't gecancelled worden?
4. db_path_str styling — overflow-x: auto verbergt eind van lange
   paden achter scrolbar; alternatief: word-break: break-all en
   meerregelige weergave?
EOF
```

---

## Task 6 — Combined post-Sprint-G audit + manuele eindrooktest

**Files:** geen wijzigingen — dit is een verification gate.

**Doel.** Cumulative inconsistencies vangen die per-task niet zien (Sprint A→F lessons: post-merge audit-cyclus na 5+ commits ving 6 + 7 echte bugs). Plus user-side end-to-end rooktest.

- [ ] **Step 6.1: Run de hele test-suite + cascade-lint**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v 2>&1 | tail -20
```

Expected: 1300 passed in <20s. Alle tests groen, geen regressies.

- [ ] **Step 6.2: Combined Codex + code-reviewer parallel audit op de Sprint G diff**

Bepaal eerst de Sprint G start-commit:

```bash
git log --oneline | head -10
# Sprint G T1 commit identificeren — typisch ~5-6 commits geleden
```

Dispatch beide reviewers op de cumulative diff `<sprint-g-start>..HEAD`:

```bash
# Code-reviewer subagent (opus, deep architectural review)
# en parallel:
env -u OPENAI_API_KEY codex exec --sandbox read-only - <<'EOF'
Audit de cumulative Sprint G diff (5 commits, /instellingen redesign).
Look for:
1. Cumulative cascade-violations: bv. .settings-card-title /
   .settings-card-subtitle gebruikt op q-* element zonder
   cascade-mitigation? settings-section-title hetzelfde?
2. Save-handler sym-issues: Bedrijfsgegevens save vs Fiscaal save vs
   logo-upload — gebruikt elk de correcte refresh/notify pattern?
3. Dirty-state edge cases: na delete logo wordt dirty-state geactiveerd?
   Bedoeld of niet? Logo-upload bypass'ed de Opslaan-knop semantiek?
4. Token-leakage: heeft iemand stiekem var(--something) geintroduceerd
   die niet in :root staat?
5. Locked-banner BEM-fix: alert-card--warning op /jaarafsluiting werkt
   ook nog?
6. Test-coverage: zou een nieuw end-to-end test (page-renders-without-
   error per tab) waarde toevoegen, of overhead?
EOF
```

Bevindingen evalueren via `superpowers:receiving-code-review` principes. Echte bugs → fix-commits (R1, R2, ... naming). Hallucinations weglaten.

- [ ] **Step 6.3: User end-to-end manuele rooktest in pywebview**

```text
Restart Boekhouding.app volledig.
Doorloop alle 3 tabs:

Tab Bedrijfsgegevens:
- 4 cards rendering correct (Identiteit / Contact / Fiscaal & financieel / Logo & visueel)
- 2-koloms grid layouts kloppen
- Wijzig een veld → linker-rand-accent (dirty-state) verschijnt
- Klik "Wijzigingen opslaan" → toast positive, dirty-states wissen
- Validatie: leeg IBAN/Naam/KvK weigert opslaan met negative toast
- Logo upload: framed preview, "Logo vervangen" knop opent file-picker,
  klik op preview-box opent ook file-picker, uploaden ververst preview,
  "Verwijderen" wist het logo + preview wordt placeholder
- Klant-kleur-toggle: aan/uit + opslaan = persistent na app-restart

Tab Fiscale parameters:
- Add-jaar toolbar werkt
- Per jaar-expansion: locked-banner (definitieve jaren) is alert-card--warning styled
- Sub-sections (IB, Ondernemersaftrek, KIA, Heffingskortingen, ZVW, EW,
  Overig, Toggles & partner, PVV, Box 3, AK schijven) elk een
  .settings-section block
- 2-koloms grid binnen elke section
- Edit een waarde + save → notify positive, validation werkt (probeer
  bv. negatieve IB-grens → negative toast)
- Locked-jaar inputs zijn disabled / readonly
- AK schijven editor blijft functioneel binnen section-padding

Tab Backup:
- 2 cards
- Download-backup knop werkt → zip-bestand verschijnt in Downloads
- DB-locatie path zichtbaar in monospace box
- Copy-knop kopieert pad naar klembord (test met Cmd+V in Notes)

Cross-cutting:
- Visueel ritme tussen tabs voelt consistent
- Geen visuele regressies elders (sidebar, dashboard, /agenda) — die
  pages gebruiken globale tokens die niet veranderd zijn, dus zou OK
  moeten zijn
- App-restart preserved alle settings correct
```

- [ ] **Step 6.4: Update memory met Sprint G outcome**

Schrijf een nieuwe memory-file `~/.claude/projects/.../memory/project_sprint_g.md`:

```markdown
---
name: Sprint G — /instellingen redesign (2026-05-04)
description: Visual + small-structural redesign /instellingen page. 5 tasks gemerged. settings-card/-section CSS pattern. Logo media-row met hidden-upload pickFiles JS-trigger. Codex 4-layer review per task + combined post-audit.
type: project
---

Sprint G SHIPPED 2026-05-04 op `master`. Direct-on-master pattern (Sprint A→F conventie).

## Wat is gemerged
- T1: CSS foundation .settings-card (chained .q-card.settings-card) + .settings-section + .is-dirty modifier. Allow-list update + 2 nieuwe cascade-lint tests.
- T2: Bedrijfsgegevens — wand-van-10-inputs → 4 section-cards + één Opslaan + dirty-state wiring.
- T3: Logo media-row in Bedrijfsgegevens — hidden ui.upload + getElement().pickFiles() JS-trigger pattern (reuse uit invoice_builder.py).
- T4: Fiscaal — section-blocks per subgroep + 2-koloms grid voor PVV/Box3 + locked-banner BEM-fix (alert-card alert-card--warning).
- T5: Backup — 2 settings-cards + clipboard-copy DB-pad via navigator.clipboard.

## Bugs door Codex/code-reviewer gevangen
[invullen post-audit]

## How to apply
- Bij UI-redesign: pak het Codex-amendments-pattern over (niet "cards everywhere" letterlijk, gebruik subtielere section-blocks waar volle cards visuele noise zouden veroorzaken)
- Logo/file-upload: HERGEBRUIK invoice_builder.py:691-701 hidden-upload + pickFiles pattern, NIET ui.upload zelf stylen
- Cascade-discipline: app-class op q-card vereist .q-card.{class} chained selector + QUASAR_APPLIED_APP_CLASSES allow-list

Pytest baseline: 1298 → 1300 (+2 cascade-lint tests).
```

- [ ] **Step 6.5: CLAUDE.md update — alleen als nieuwe conventie geintroduceerd**

Sprint G introduceert geen nieuwe project-conventies (settings-card pattern is repo-intern, niet project-wide). Skip CLAUDE.md update tenzij iets ECHT overall-relevant blijkt uit post-audit.

Als wel nodig: voeg sectie toe bij "Visuele tokens (Sprint B+, ...)":

```markdown
### Sprint G additions (2026-05-04)
- `.settings-card` (op `ui.card`) en `.settings-section` (op `ui.column`)
  voor /instellingen redesign. Beide BUITEN `@layer components`.
  `.q-card.settings-card` chained selector verplicht (cascade-discipline).
- `.is-dirty` modifier op settings-card voor unsaved-state visual.
```

---

## Self-Review

**1. Spec coverage check:**
- §A1 (CSS classes) → Task 1 ✓
- §A2 (dirty-state) → Task 1 (CSS) + Task 2 (wiring) ✓
- §A3 (tab styling unchanged) → expliciet niet aangeraakt ✓
- §B1-B3 (3 cards) → Task 2 ✓
- §B4 (Logo & visueel card incl. media-row) → Task 2 (placeholder) + Task 3 (echte impl) ✓
- §B5 (één Opslaan) → Task 2 ✓
- §C1 (toolbar) → onveranderd in Task 4 ✓
- §C2 (per jaar-expansion sections + grid + locked-banner) → Task 4 ✓
- §C3 (add-bracket) → Task 4 (binnen AK section) ✓
- §D1-D2 (Backup 2 cards + clipboard) → Task 5 ✓
- §E test-strategie → Task 1 (cascade-lint) + Task 6 (manueel + audit) ✓
- §R1 (cascade) → Task 1 chained selector + allow-list + Task 6 audit ✓
- §R2 (save-validation) → Task 2 behoudt validation ✓
- §R3 (logo-fragility) → Task 3 reuse pattern ✓
- §R4 (dirty-state-wash) → Task 2 expliciete remove ✓
- §R5 (Fiscaal te druk) → Task 4 subtiele section + Task 6 audit ✓

**2. Placeholder scan:** geen TBD/TODO in plan-tekst gevonden. Code-blocks zijn complete (geen "..." midden in functies behalve waar bestaande structuur expliciet hergebruikt wordt zoals `grouped_fields = [...]` met verwijzing naar bestaande lijst — duidelijk genoeg voor implementer).

**3. Type consistency:**
- `_mark_dirty(card)` Task 2 — closure die handler returnt, gebruikt in `on_change=_mark_dirty(card_X)`. Consistent over alle 4 cards.
- `card.classes(add='is-dirty')` / `c.classes(remove='is-dirty')` — NiceGUI's `Element.classes()` accepteert `add=` en `remove=` keyword args. Consistent gebruikt.
- `_pick_logo_js` JS-string Task 3 — gebruikt in 2 plekken (`preview_box.on('click', ...)` en `ui.button(on_click=...)`). Consistent.
- `settings-section-title` class — Task 1 definieert, Task 4 gebruikt (alle 11 sub-sections). Consistent.
- `settings-card-title` / `settings-card-subtitle` classes — Task 1 definieert, Task 2 + Task 5 gebruiken. Consistent.
