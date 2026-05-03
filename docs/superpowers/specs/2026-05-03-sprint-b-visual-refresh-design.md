# Sprint B — Visual refresh (Apple-stijl, YAGNI-versie)

**Datum**: 2026-05-03
**Status**: Spec — wachten op user-review vóór implementatie-plan
**Doel**: De bestaande Boekhouding-UI rustiger, scherper en consistenter
maken in een lichte Apple-stijl, zonder layout-rewrites en zonder business-
logic te raken. Sprint A heeft de Apple-stijl al naar `/agenda` gebracht;
Sprint B doet de rest van de app in dezelfde geest, maar met YAGNI-houding
(geen glassmorphism, geen Rounded headings, geen brede sidebar, geen
token-explosie).

## Context — wat nu live is

- Sprint A heeft `components/layout.py` opgerekt naar 367 LoC, met een
  redesign-port-blok (regels 105-281) dat tokens (`.num`, `.chip`, `.seg`,
  `.t-micro`) en de hele agenda-CSS bevat (`.wd-pill`, `.agenda-cell`,
  `.week-summary` etc.).
- Header + sidebar zijn nog donker (`#0F172A`) met teal-mint nav-active.
- Body-background is `#F8FAFC` (slate-50).
- Numbers gebruiken JetBrains Mono via een Google Fonts CDN-link.
- `/agenda` (Sprint A) is in scope als referentie van "hoe Apple-stijl
  voelt in deze app", niet om opnieuw aangeraakt te worden.
- 12 routes totaal: `/`, `/agenda`, `/werkdagen`, `/facturen`,
  `/transacties`, `/kosten`, `/bank` (legacy stub, 12 LoC),
  `/documenten`, `/jaarafsluiting`, `/aangifte`, `/klanten`,
  `/instellingen`.

## Vier scope-keuzes (vastgelegd na brainstorm + Codex-pushback)

1. **Brand-kleur**: teal blijft (`#0F766E`). Geen iOS-blue. Apple-tokens
   komen erbij, niet in plaats van.
2. **Sidebar/header**: licht. Sidebar krijgt zachte gradient
   (white → soft tint → bg-gray) en behoudt **180px breedte**
   (geen 260px — content-width op tabellen blijft beschermd).
   Header wordt **opaque white** met 1px border-bottom — **geen**
   `backdrop-filter: blur(...)` (Codex-cut: geen meaningful content
   erachter, GPU-cost zonder winst).
3. **Pagina-tier-aanpak**:
   - **Tier 1 — chrome (raakt alle routes via `layout.py`)**: header,
     sidebar, globale tokens, font-stack, body-background.
   - **Tier 2 — deep visual port (high-traffic)**: `/`, `/werkdagen`,
     `/facturen`, `/transacties`, `/kosten`, `/klanten`, `/documenten`.
     Tabel-rows, KPI-strips, dialoog-styling, segmented-tabs.
   - **Tier 3 — chrome-only polish (fiscale density behouden)**:
     `/aangifte`, `/jaarafsluiting`, `/instellingen`. Krijgen Tier 1
     chrome automatisch + typography-tokens, maar geen layout-rewrite.
   - **`/agenda` (Sprint A klaar)**: agenda-**content** (kalender,
     pills, day-inspector) blijft visueel onveranderd; chrome/body/font
     uit Tier 1 mag wél doorwerken (lichte sidebar, system font, body-
     background). Smoke-check op /agenda = "calendar-grid pixel-identiek
     aan vóór Sprint B; sidebar/header zijn lichter, dat is OK".
   - **`/bank`**: redirect naar `/transacties`.
4. **Typography**: pure `-apple-system` system stack voor body+headings
   + SF Mono voor numbers. **Geen** SF Pro Rounded (Codex-cut: Rounded
   is voor casual apps zoals Calendar/Find My; financial app moet rustig
   en betrouwbaar voelen, niet speels). Google Fonts CDN-link voor
   JetBrains Mono **wordt verwijderd**.

## In scope

1. `components/layout.py` uitbreiden met:
   - 9 design-tokens (zie § Tokens).
   - System-font stack op `body` + `.q-page`.
   - SF Mono toegepast op `.num`, `.mono`, `.numeric` cell-types.
   - Lichte sidebar (gradient, light-active state, dot-marker rechts).
   - Opaque white header (1px border-bottom, geen blur).
   - Quasar `.q-*` overrides **buiten** `@layer components`
     (Codex-waarschuwing: cascade-layers verliezen van unlayered
     Quasar defaults).
   - App-only classes (`.app-card`, `.kpi-strip`, `.sb-item`, etc.)
     **binnen** `@layer components`.
2. Verwijderen van Google Fonts CDN-link (`<link>` in
   `layout.py:286-290`).
3. Tabel-leesbaarheid: row-height ≥ 36px, zebra-stripes
   (`.q-table tbody tr:nth-child(even)`), header-contrast (al gedaan
   in Sprint A — checken), numeric alignment via `.num` op
   bedrag-kolommen die het nog niet hebben.
4. KPI-cards subtieler: consistente radius (`var(--radius)`), zachte
   shadow (`var(--shadow)`), border-color via `var(--border)`. Vervangt
   ad-hoc `border: 1px solid #E2E8F0` op `.card-hero` etc.
5. Forms/dialogs consistent: input border-radius, label-typography,
   button-spacing — via Quasar overrides.
6. `/bank` route → redirect naar `/transacties` (`pages/bank.py` wordt
   2-regel redirect-handler).
7. Smoke-test elke Tier 2 + Tier 3 pagina na `.q-*`-wijzigingen
   (handmatig in pywebview — zie § Testing).
8. Volledige pytest-suite groen houden (1261 tests baseline na merge
   van Sprint A).

## Out of scope (bewust)

- **iOS-blue als primary**. Teal blijft.
- **`backdrop-filter` glassmorphism** waar dan ook in de app.
- **SF Pro Rounded** voor headings.
- **Sidebar-widening** naar 260px (Codex-cut).
- **Per-page CSS-files** (`components/styles/dashboard.css` etc.) —
  Aanpak 1 = single CSS-laag in `layout.py`.
- **Klant-specifieke kleuren** in agenda-cellen (parked als Sprint C+
  optioneel feature met DB-kolom + Instellingen-toggle).
- **Layout-rewrite van `/aangifte` of `/jaarafsluiting`** (Tier 3:
  alleen chrome-pickup + typography).
- **Token-explosie**: geen `--ink-1..4`, geen `--shadow-sm/-md/-lg`,
  geen `--accent-soft-2`, geen `--surface-2`, tenzij een concrete
  component erom vraagt en het daar wordt geïntroduceerd.
- **CSS-inventaris matrix-document** (Codex zelf-correctie: te
  enterprise voor 1-dev app — smoke-test is genoeg).
- **DB/schema/service/business-logic wijzigingen.** Visueel-only sprint.
- **`services/agenda.py` boundary** — blijft 0 NiceGUI-imports
  (boundary-test in `tests/test_agenda_service.py` blijft groen).

## Tokens (minimum levensvatbare set — 9)

```css
:root {
    --bg: #F5F5F7;            /* page background — system gray */
    --surface: #FFFFFF;        /* cards, dialogs, header */
    --border: rgba(60,60,67,0.12);
    --text: #1C1C1E;           /* primary ink */
    --muted: #6E6E73;          /* secondary ink, labels, captions */
    --accent: #0F766E;         /* teal brand — unchanged */
    --accent-soft: rgba(15,118,110,0.10);
    --shadow: 0 2px 8px rgba(0,0,0,0.06);
    --radius: 12px;
}
```

Sprint A heeft een paar vergelijkbare ad-hoc tokens via `.card-hero`
(`#E2E8F0`, eigen radius). Tijdens Sprint B vervangen deze de hardcoded
hex-values, maar **alleen op plekken die we toch al raken** — geen
"refactor pass over the whole codebase" omdat een token nu beschikbaar
is. YAGNI.

## CSS-architectuur (Aanpak 1 + Codex-correctie)

`components/layout.py` houdt één `ui.add_css(..., shared=True)` blok.
Geordend in expliciete sub-secties met visuele headers:

```css
/* === TOKENS === */
:root { --bg: ...; ... }

/* === BASE === */
body, .q-page { font-family: -apple-system, ...; background: var(--bg); ... }

/* === QUASAR OVERRIDES (UNLAYERED — wint van Quasar defaults) === */
.q-card { border-radius: var(--radius); box-shadow: var(--shadow); ... }
.q-table thead th { ... }
.q-field--outlined .q-field__control { ... }
.q-btn { ... }

@layer components {
    /* === CHROME === */
    .header-light { ... }
    .sidebar-light { ... }
    .sb-item, .sb-item.active { ... }

    /* === SHARED COMPONENTS === */
    .app-card { ... }
    .kpi-strip { ... }

    /* === SPRINT A (AGENDA — UNCHANGED) === */
    .wd-pill, .wd-dagpraktijk, .wd-anw, .wd-overig { ... }
    .agenda-cell, .week-summary { ... }
    .holiday-marker, .blocker-vacation, .blocker-sick, .blocker-training { ... }

    /* === EXISTING DASHBOARD/REDESIGN-PORT TOKENS === */
    /* `.num` en `.mono` font-family wijzigt: JetBrains Mono →
       "SF Mono", ui-monospace, Menlo, monospace.
       Verwijder de Google Fonts <link> in layout.py:286-290.
       `.t-micro`, `.chip`, `.seg`, `.selection-bar`, `.page-sub`
       blijven verder ongewijzigd (alleen font-family inherit
       waar van toepassing). */
    .num, .mono { font-family: "SF Mono", ui-monospace, Menlo, monospace; ... }
    .t-micro, .chip, .seg, .selection-bar, .page-sub { ... }
}
```

**Waarom `.q-*` overrides buiten de layer?** Cascade-layers staan in de
cascade-order vóór specificity: unlayered styles winnen *altijd* van
layered styles, ongeacht selector-specificity. Quasar's eigen CSS is
unlayered. Als wij `.q-card` binnen `@layer components` zouden zetten,
zou Quasar's volgende update onze override kunnen overrulen — fragile.
Buiten de layer zijn we expliciet de winnaars.

**Estimate**: 367 → ~520 LoC (~150 nieuwe regels, niet 600+ zoals
oorspronkelijk geschat — Codex-cuts hebben de scope ingedikt).

## Per-tier acties

### Tier 1 — chrome (één PR, raakt alle routes)

Wijzigingen in `components/layout.py`:

1. **Tokens-blok bovenaan** met de 9 tokens.
2. **Body**: `background: var(--bg)`, system font-stack.
3. **Header**: opaque white achtergrond (`background: var(--surface)`),
   `border-bottom: 1px solid var(--border)`, dark text/icons.
   - Title-label (`text-h6`) wordt dark (`var(--text)`).
   - Subtitle (`text-subtitle1`) wordt muted (`var(--muted)`).
   - Menu-toggle button: dark icon op witte achtergrond.
4. **Sidebar**: lichte gradient, lichte text, active = soft accent
   gradient + dot-marker rechts.
5. **Google Fonts CDN-link verwijderen.** SF Mono is OS-native; geen
   download nodig.
6. **Quasar `.q-card`**: radius + shadow + border via tokens.
7. **Quasar `.q-table th` migratie**: Sprint A heeft deze regel
   binnen `@layer components` staan (`#F1F5F9` background, uppercase
   header etc.). Per Codex' cascade-layer regel hoort hij **buiten**
   de layer. Tier 1 verplaatst de regel met **identieke styling**
   (geen visuele wijziging, alleen scope-relocatie). Architecturele
   consistentie zonder visuele impact.
8. **Quasar `.q-btn`**: dense padding, radius, no-cap props blijven
   (Sprint A defaults).
9. **Quasar `.q-field--outlined .q-field__control`**: radius + border-color.

### Tier 2 — deep visual port (per pagina, kleine commits)

**Pagina's**: `/`, `/werkdagen`, `/facturen`, `/transacties`, `/kosten`,
`/klanten`, `/documenten`.

Per pagina:
- KPI-cards / strip-cards: `.card-hero` → swap hardcoded styling met
  `app-card` of token-references. Geen layout-rewrite.
- Tabel-row-height ≥ 36px (huidige `dense` props blijven).
- Numeric cells krijgen `.num` class waar nog niet aanwezig (bedrag-,
  uren-, km-kolommen).
- Page-toolbar (`.page-toolbar`) blijft bestaand patroon.

**Niet** doen:
- Section-rewrites
- Nieuwe component-types introduceren
- Tabel-kolommen herordenen of toevoegen
- Dialog-flows wijzigen

### Tier 3 — chrome-only polish

**Pagina's**: `/aangifte`, `/jaarafsluiting`, `/instellingen`.

Krijgen via `layout.py`-changes automatisch:
- Lichte sidebar/header
- System font-stack op body
- SF Mono op `.num` cells (waar al toegepast)
- Token-driven `.q-card` border/shadow/radius

Wat **niet**:
- Geen aanraking van fiscale tabel-density (rij-hoogte, kolom-breedtes,
  number-precisie).
- Geen herstructurering van Box-1/Box-3 tab-layout in /aangifte.
- Geen wijziging van Jaarafsluiting checklist-rendering.

### `/bank` redirect

`pages/bank.py` (nu 12 regels stub) wordt:

```python
from nicegui import ui

@ui.page('/bank')
def bank_page():
    ui.navigate.to('/transacties', new_tab=False)
```

(of equivalent via `app.router.add_redirect` als NiceGUI dat netter
ondersteunt — implementatie-detail voor implementatie-plan.)

## Testing

### Bestaande pytest-suite
**Vereist**: 1261 tests blijven groen na elke Tier-1/Tier-2 wijziging.
Visuele changes raken geen `services/` of `database.py`, dus pytest
zou ongevoelig moeten zijn. Eén risico: als bestaande tests UI-strings
controleren die we hernoemen — niet verwacht voor deze sprint.

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

### Smoke-test (handmatig per pagina)

**Geen matrix-document.** Wel: na elke `.q-*`-wijziging in `layout.py`,
loop deze checklist door per pagina in de native pywebview-app.

**Generieke checklist per pagina:**
- [ ] Page loads zonder console-errors
- [ ] Tabel rendert met juiste row-height + zebra
- [ ] Dialoog opent, knoppen aanklikbaar, sluit netjes
- [ ] Form-input focusable + outlined
- [ ] Dropdown / q-select toont menu **én klikken in menu landt event**
      (zie risico-tabel: portal-teleport regression)

**Subflow-checks per route** (sterker dan "page loads", catch portal-bugs):
- `/` (dashboard): KPI-cards renderen + click op "Te verwerken" navigeert
  naar `/transacties?status=ongecategoriseerd`.
- `/werkdagen`: tabel + filter-toolbar + werkdag-dialog (add) opent en
  bewaart.
- `/facturen`: tabel + rij-menu opent **én** "Bewerken"-actie binnen
  het menu landt → invoice builder opent. Import-flow (PDF-upload)
  test pij vóór commit. PDF-preview iframe rendert.
- `/transacties`: q-select voor categorie werkt **per rij** (event landt,
  cat wordt geschreven). "Matches controleren"-header-knop opent dialog.
  Bulk-acties bevestigingsdialog opent en sluit netjes.
- `/kosten`: tab "Overzicht" + tab "Investeringen" beide laden. KPI-cards
  klikbaar.
- `/klanten`: tabel + klant-dialog (add+edit) + alias-CRUD-sectie binnen
  edit.
- `/documenten`: upload-veld werkt (file selectie + opslaan), filter-
  toolbar werkt.
- `/aangifte` (Tier 3): tabs (Box 1 / Box 3 / etc.) wisselen, fiscale
  cijfers leesbaar (geen layout-druk door nieuwe spacing).
- `/jaarafsluiting` (Tier 3): tabs (Controles / Snapshot / Heropenen) +
  "Definitief maken"-flow opent dialog.
- `/instellingen` (Tier 3): jaar-selector werkt + Arbeidskorting-brackets
  editor laadt + opslaan-knop landt.
- `/agenda` (Sprint A regression): kalender-grid pixel-vergelijkbaar met
  vóór Sprint B; alleen sidebar/header lichter is acceptabel.

### Codex auto-review

Conform CLAUDE.md: `codex-review` skill na elke `.py`/`.html`/`.css`
wijziging vóór "klaar"-rapportage. Sprint B = veel CSS-changes, dus
de skill moet ook op `.css`-diffs draaien (skill ondersteunt al `.css`).

## Risico's en mitigatie

| Risico | Mitigatie |
|---|---|
| Quasar `.q-*` override breekt subtiel een dialog/upload op een pagina die we niet expliciet getest hebben | Smoke-test verplicht over alle Tier 2+3 routes vóór commit. Bij twijfel: rollback CSS-regel, kleinere scope. |
| Sprint A `.wd-pill` / `.agenda-cell` styling verandert ongewenst door nieuwe globale tokens | `/agenda` smoke-test elke ronde. `.wd-*` classes blijven exact zoals nu. |
| SF Mono renders inconsistent op pre-Big Sur macOS (onwaarschijnlijk: app draait op user's huidige macOS, nieuw genoeg) | `font-family` fallback-stack: `"SF Mono", ui-monospace, Menlo, monospace` — Menlo is gegarandeerd aanwezig. |
| Nav-active state minder leesbaar op lichte sidebar dan op donkere | Dot-marker rechts van active item + soft-accent gradient + dark-text bold. Als visueel niet sterk genoeg na Tier 1-PR: extra `border-left-accent` zoals huidige donkere variant. |
| `pages/bank.py` redirect breekt ergens een hardcoded link | Grep `/bank` in pages/+components/ vóór de redirect — verwacht: 0 hits buiten `pages/bank.py` zelf. |
| pytest faalt op een UI-string-check die we niet kenden | Eerst Tier 1-PR draaien als dry-run en pytest checken vóór commit. |
| Quasar `q-menu` / `q-btn-dropdown` / `q-select` events landen niet door portal-teleport (CLAUDE.md genoemd, eerder rootcause van Kosten-categorie-bug) — een radius/padding override op `.q-menu` of nested classes kan dit subtiel re-introduceren | Smoke-test mag NIET stoppen bij "menu opent visueel". Verplichte check: klik **binnen** het menu/dropdown en valideer dat de event-handler effect heeft (categorie wordt opgeslagen, factuur opent, etc.). Per route in subflow-checklist hierboven uitgewerkt. |

## Implementatie-volgorde (high-level — exacte tasks komen in plan)

1. Tier 1 chrome (één commit, raakt alles) → smoke-test + pytest.
2. `/bank` redirect (kleine commit).
3. Tier 2 per pagina (kleine commits, één pagina per commit voor
   reviewability) → smoke-test per pagina + pytest na elke commit.
4. Tier 3 spot-check (verifieer dat Tier 1 chrome zonder issues
   doorwerkt op `/aangifte`, `/jaarafsluiting`, `/instellingen`).
5. End-to-end smoke over alle 11 actieve routes.
6. Auto-memory update + CLAUDE.md mini-sectie over de visual-tokens.

Implementatie-plan komt in `docs/superpowers/plans/` na user-review
van deze spec.

## Definition of Done

- [ ] Tokens-blok aanwezig in `layout.py`, sub-secties met visuele
      headers (`/* === ... === */`).
- [ ] Quasar `.q-*` overrides expliciet **buiten** `@layer components`
      (incl. de Sprint A `.q-table th`-regel die mee-verhuist met
      identieke styling).
- [ ] Header opaque white, sidebar licht-gradient, beide 180px breed.
- [ ] System font-stack live (`-apple-system, ...`) op body+headings.
- [ ] Google Fonts `<link>` voor JetBrains Mono verwijderd uit
      `layout.py`.
- [ ] SF Mono toegepast op `.num` en `.mono` (font-family wijziging).
- [ ] **Numeric alignment-pass uitgevoerd**: bedrag-, uren-, en
      km-kolommen op `/dashboard`, `/werkdagen`, `/facturen`,
      `/transacties`, `/kosten` hebben `.num` class waar nog niet
      aanwezig. Verifieerbaar via grep op de page-files.
- [ ] `/bank` redirect actief; geen hardcoded `/bank`-links elders
      in pages/+components/.
- [ ] Volledige pytest-suite groen (1261 baseline).
- [ ] Smoke-test alle 11 actieve routes uitgevoerd in pywebview met
      **subflow-checks** (zie § Testing); `/agenda`-grid pixel-
      regressie-vrij.
- [ ] Portal-event-check expliciet uitgevoerd voor minimaal:
      `/transacties` q-select, `/facturen` rij-menu Bewerken,
      `/jaarafsluiting` Heropenen-flow.
- [ ] Codex-review op finale `layout.py`-diff: GEEN BEVINDINGEN of
      bewust geaccepteerde nuance.
- [ ] Auto-memory `project_visual_refresh.md` (of vergelijkbaar)
      genoteerd met tokens + scope.

## Open punten (na user-review beslissen)

Geen op dit moment — alle vier scope-keuzes en architectuur-keuze
zijn vastgelegd na Codex-pushback. Mochten tijdens implementatie
nieuwe nuances opduiken (bijv. nav-active contrast op licht), dan
behandelen we die als kleine spec-amendment in deze file.
