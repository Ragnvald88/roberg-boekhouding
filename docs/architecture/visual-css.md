# Visuele tokens + CSS cascade

`components/layout.py` definieert 13 globale CSS custom properties in `:root`:
- 9 chrome/structure: `--bg`, `--surface`, `--border`, `--text`, `--muted`, `--accent`, `--accent-soft`, `--shadow`, `--radius`
- 4 soft-bg: `--bg-success-soft`, `--bg-warning-soft`, `--bg-info-soft`, `--bg-negative-soft`

Plus **component-scope CSS-vars** (Codex-aanpak om token-explosion te voorkomen): `.alert-card` met `--alert-bg/-border/-icon/-title/-body/-link` modifiers; `.severity-card` met `--severity-bg/-border/-fg/-dark` modifiers.

**Nieuw werk**: globale tokens voor structure, component-scope vars voor variant-families.

## Settings-card precedent

`.q-card.settings-card` (chained selector verplicht — wint van Quasar's unlayered `.q-card` defaults via specificity + source order; getest via `tests/test_visual_css.py:test_sprint_g_settings_card_chained_selector`) met `.is-dirty` modifier voor unsaved-state-cue (3px linker accent-border). `.settings-section` (op `ui.column`, géén chained selector nodig) voor sub-section-blokken binnen cards/expansions. Beide BUITEN `@layer components`. `settings-card` zit in `QUASAR_APPLIED_APP_CLASSES` allow-list. Geen schaduw (Quasar's `flat` default-prop overruled box-shadow met `!important`).

## Cascade-regel (deels geënforceerd door `tests/test_visual_css.py`)

Quasar `.q-*` overrides + **app-classes die op Quasar-elementen worden toegepast** ALTIJD buiten `@layer components` plaatsen. Layered styles verliezen van Quasar's unlayered defaults, ongeacht specificity.

### Strict niet `.q-*` maar wel buiten layer

`.alert-icon` op `q-icon`, `.alert-link` op `q-btn`, `.severity-fg` op `q-icon`+`q-btn`, `.nav-icon` op `q-icon`. De `.q-*`-naam is niet de regel — het toepassings-element is. **Test dekt alleen `.q-*`-selectors**, dus voor app-classes-op-quasar moet je dit zelf herinneren.

### App-only classes binnen `@layer components` mogen

`.nav-item` (op `<div>`), `.wd-pill` (op `<div>`), `.alert-title` (op `<span>`) — geen Quasar concurrent.

### Bewuste suppressie van Quasar defaults

Chained selector `.q-card.your-class` buiten layer (zie `.q-card.builder-line-card` als precedent voor "card zonder shadow", en `.q-card.settings-card`).

### Variant-classes op `.agenda-cell` (en vergelijkbare base-cell-classes)

Gebruik **chained selectors** zoals `.agenda-cell.holiday-marker { background: ... }` — NIET naked `.holiday-marker { background: ... }`. Reden: `.agenda-cell` zelf zet `background: white` en wint van naked variant via source-order + gelijke specificity. Cascade-lint test (`test_holiday_blocker_use_chained_selectors`) vangt regressie. Patroon van toepassing op alle holiday/blocker/status-overlays die op `.agenda-cell`-achtige containers leven.

### `.q-btn` overrides

Moeten `:not()`-modifier-respect afdwingen: `.q-btn:not(.q-btn--round):not(.q-btn--rounded) { ... }` — anders breken `props('round')` icon-buttons (cirkel → afgerond vierkant).

## Brand-coupling

`--accent` (CSS) en `ui.colors(primary=...)` (NiceGUI/Quasar Python-side) zijn HANDMATIG gekoppeld op zelfde teal (`#0F766E`). Wijzig je één, wijzig de ander. Quasar's `accent` (amber `#F59E0B`) is een aparte rol — `color=accent` in markup geeft amber, NIET teal. Voor teal-accent: `color=primary` of `style="color: var(--accent)"`.

## Font-stack

Body+headings = `-apple-system` system stack (laat macOS SF Pro Text/Display zelf kiezen, geen Rounded — financial app moet rustig voelen, niet speels). Numbers = SF Mono via `.num` class. Geen webfont-CDN meer.

## Dead-code

**`.card-hero` bestaat NIET MEER** (post-merge audit Fix #6) — was dead-code class die door unlayered `.q-card` werd overruled. Niet opnieuw introduceren; gebruik `ui.card()` direct (krijgt automatisch de `.q-card` token-styling) of een chained `.q-card.your-variant` buiten layer voor specifieke afwijkingen.

## Realistic state na Sprint A→F

Sprint B/C/E/F hebben chrome + dashboard-helpers + ~75 page-callers + alert/severity cards op tokens gezet. Resterende hex (~13 in dashboard.py, kleinere in andere pages) is bewust: ECharts (geen CSS-vars), sky-700 #0369A1 (geen token), PDF render context, multi-shade design palettes. Tier-2 page-tokens-pickup is "opportunistic" — doen wanneer een pagina sowieso wordt aangeraakt.

## Tests

`tests/test_visual_css.py` — 5 cascade-lint tests die de structurele CSS-invariants enforced. ALTIJD draaien na CSS-wijzigingen.
