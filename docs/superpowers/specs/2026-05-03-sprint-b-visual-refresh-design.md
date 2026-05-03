# Sprint B — Visual refresh (Apple-stijl, YAGNI-versie)

> **🚫 SHIPPED — historische spec.** Volledig geïmplementeerd en gemerged
> naar `master` via merge-commit `7d1d14e` (--no-ff) op 2026-05-03. Tier 2
> per-page user-smoke (T11-T17) en Tier 3 fiscale spot-check (T18) zijn
> deferred — uitvoeren tijdens normaal app-gebruik. Voor huidige
> conventies: zie `CLAUDE.md` § Visuele tokens. Voor implementation-trail:
> zie `docs/superpowers/plans/2026-05-03-sprint-b-visual-refresh.md`
> (ook met SHIPPED-banner) en auto-memory `project_visual_refresh.md`.

**Datum**: 2026-05-03
**Status**: SHIPPED 2026-05-03
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
  `/transacties`, `/kosten`, `/bank` (legacy stub, 12 LoC, **wordt
  geschrapt** in Sprint B),
  `/documenten`, `/jaarafsluiting`, `/aangifte`, `/klanten`,
  `/instellingen`.

## Aanvullende design-checks (na review-ronde 2)

Tweede review-ronde (Codex onafhankelijk + eigen audit) heeft 10 punten
opgeleverd, allemaal verwerkt in deze spec. Belangrijkste impact:

1. `/bank` is een client-side ineffectieve redirect — wordt **verwijderd**
   (file weg, import uit `main.py` weg). Geen server-side redirect nodig
   voor 1-user app.
2. Body-background wordt nu via inline `ui.query('body').style(...)`
   gezet (`layout.py:331`) — die regel **moet expliciet mee** in de
   token-blok-commit, anders wint inline van CSS-token.
3. Quasar `.q-*` overrides die NU binnen `@layer components` zitten
   (6 regels): `.q-table th`, `.q-table tbody tr:nth-child(even)`,
   `.page-toolbar .q-field`, 3× `.page-toolbar .q-field--outlined .q-field__control`
   varianten, `.page-toolbar .q-field__label` — **allemaal**
   verhuizen naar buiten layer (Codex' algemene regel; geen
   YAGNI-uitzondering voor scoped overrides).
4. Tier 3 is **eerlijker** geformuleerd: `/aangifte` + `/jaarafsluiting`
   + `/instellingen` krijgen **wél** de globale `.q-card` (radius/shadow)
   en `.q-table` (zebra) wijzigingen. Wat behouden blijft: rij-hoogte,
   kolom-breedtes, getal-precisie, layout-structuur.
5. Numeric-alignment-pass (89 `format_euro` callers in pages/) is
   **uit scope** — `.num` is nu nergens in `pages/*.py` gebruikt en een
   pass over 89 plekken is geen "kleine pickup". Sprint B raakt alleen
   de `.num`-class-definitie zelf (font-family). Bestaande pages krijgen
   SF Mono pas wanneer ze in een latere sprint `.num` adopteren.
6. JetBrains Mono staat in 5 extra classes (`.chip`, `.seg-btn`,
   `.selection-bar .sb-count`, `.selection-bar .sb-meta`, `.page-sub`) —
   font-family in al deze classes wijzigen naar SF Mono in dezelfde
   commit als CDN-link removal (anders silent fallback naar Menlo).
7. Smoke-tests uitgebreid met gevaarlijke subflows (zie § Testing).
8. Test-baseline wordt eerst gemeten in writable env vóór Tier 1 begint
   (geen hardcoded count meer).

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
   - **`/bank`**: route + bestand wordt **verwijderd** (`pages/bank.py`
     weg, `import pages.bank` uit `main.py` weg). Geen redirect — voor
     1-user lokale app is een 404 op een nooit-bezochte legacy-URL
     acceptabel; `ui.navigate.to` is client-side ineffectief en
     server-side redirect-middleware is overkill.
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
   `layout.py:286-290`) **plus** font-family rewrite naar
   `"SF Mono", ui-monospace, Menlo, monospace` op alle 7 classes die
   nu JetBrains Mono noemen: `.num`, `.mono`, `.chip`, `.seg-btn`,
   `.selection-bar .sb-count`, `.selection-bar .sb-meta`, `.page-sub`.
   Atomaire commit — anders fallback naar Menlo zodra CDN weg is.
3. Tabel-leesbaarheid: row-height ≥ 36px (Quasar `dense` blijft),
   zebra-stripes (`.q-table tbody tr:nth-child(even)` — bestaande regel
   migreert mee naar buiten layer), header-contrast (Sprint A regel
   `.q-table th` migreert mee naar buiten layer met identieke styling).
   **Geen numeric-alignment-pass over `format_euro` callers** — `.num`
   is nu nergens in `pages/*.py` gebruikt; een 89-edits pass is geen
   "small pickup". Sprint B raakt alleen de `.num`-class-definitie zelf
   (font-family wijziging).
4. KPI-cards subtieler: consistente radius (`var(--radius)`), zachte
   shadow (`var(--shadow)`), border-color via `var(--border)`. Vervangt
   ad-hoc `border: 1px solid #E2E8F0` op `.card-hero` etc.
5. Forms/dialogs consistent: input border-radius, label-typography,
   button-spacing — via Quasar overrides.
6. `/bank` route — `pages/bank.py` **verwijderd**, `import pages.bank`
   uit `main.py:33` weg.
7. Smoke-test elke Tier 2 + Tier 3 pagina na `.q-*`-wijzigingen
   (handmatig in pywebview — zie § Testing).
8. Volledige pytest-suite groen houden — baseline = uitkomst van
   `pytest --collect-only -q | tail -1` in writable dev env vóór
   Tier 1 begint (waarschijnlijk 1261, maar wordt herijkt per
   implementatie-start zodat eventuele master-merges sindsdien
   meegenomen worden).

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

### Tier 3 — chrome + globale token-pickup (eerlijke versie)

**Pagina's**: `/aangifte`, `/jaarafsluiting`, `/instellingen`.

**Krijgen automatisch via `layout.py`-changes** (eerlijk: dit is meer
dan "chrome-only" — deze pagina's hebben veel `ui.card` en `ui.table`
en die schuiven mee):
- Lichte sidebar/header
- System font-stack op body
- SF Mono op `.num` cells (alleen waar al toegepast — werkdagen-template,
  shared_ui mono-class)
- **`.q-card` radius (12px) + soft shadow + token-border** — dus alle
  fiscale cards in `/aangifte` (Box 1, Box 3 totalen) en
  `/jaarafsluiting` (snapshot/checklist cards) krijgen subtiel
  rondere hoeken en zachtere shadow. Geen layout-shift, wel visueel
  verschil.
- **`.q-table` zebra + header-contrast** — fiscale tabellen in
  `/jaarafsluiting` (`pages/jaarafsluiting.py:430,567`) krijgen ook
  zebra-rows en de mee-verhuisde header-styling.

Wat **niet**:
- Geen aanraking van fiscale rij-hoogte (Quasar `dense` blijft).
- Geen kolom-breedte aanpassingen.
- Geen number-precisie wijzigingen (decimals, format_euro blijft).
- Geen herstructurering van Box-1/Box-3 tab-layout in `/aangifte`.
- Geen wijziging van Jaarafsluiting checklist-rendering-logic.
- Geen `.num`-class toevoegingen aan fiscale labels (zie In-scope #3:
  Sprint B doet geen numeric-pass).

**Verifieer met user na Tier 1-PR**: visuele check op `/aangifte` —
zijn de cards-met-radius nog goed leesbaar? Als rondere hoeken visueel
storen voor fiscale dichtheid: corrigeer in Tier 1 commit (kleinere
`--radius` bv. 8px ipv 12px), niet via Tier 3-rewrite.

### `/bank` schrappen

Codex heeft geverifieerd in de geïnstalleerde NiceGUI source dat
`ui.navigate.to(...)` puur client-side is (frontend `window.open(url,
"_self")` zonder history-replace) en dat `app.router.add_redirect` niet
bestaat in de NiceGUI/FastAPI versie die we gebruiken. Een server-side
redirect via FastAPI middleware is overkill voor één route die niemand
bookmarkt in een 1-user lokale app.

**Concrete actie:**
1. `git rm pages/bank.py` (12 regels stub).
2. Verwijder `import pages.bank` uit `main.py:33`.
3. Geen vervanging — een 404 op `/bank` is acceptabel.

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
  bewaart. **Plus**: rij-menu (`q-menu` teleport, `pages/werkdagen.py:244`)
  opent én Bewerken/Verwijderen/Ontkoppel binnen het menu landt event
  → portal-event-check.
- `/facturen`: tabel + rij-menu opent **én** "Bewerken"-actie landt
  → invoice builder opent. **Plus** (Codex-toevoegingen):
  - "Verstuur via mail" op een **concept**-factuur → status flipt naar
    `verstuurd` (`pages/facturen.py:1362` flow), Mail.app opent.
  - "Markeer als concept" op een **betaalde** factuur → twee-staps
    transitie (betaald→verstuurd→concept), waarschuwingsdialog opent
    (`pages/facturen.py:1215` flow).
  - "PDF preview" op een factuur waarvan de stored `pdf_pad` niet
    bestaat → `_ensure_factuur_pdf` self-healing genereert PDF opnieuw
    en preview opent (`pages/facturen.py:1133`).
  - Import-flow (PDF-upload) tester vóór commit. PDF-preview iframe
    rendert.
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
  cijfers leesbaar **ondanks `.q-card` radius/shadow wijziging**.
- `/jaarafsluiting` (Tier 3): tabs (Controles / Snapshot / Heropenen) +
  "Definitief maken"-flow opent dialog. Tabellen krijgen zebra — checken
  of dat niet visueel druk wordt op fiscale dichtheid.
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
| `pages/bank.py` schrappen breekt ergens een hardcoded link | Grep `/bank` in pages/+components/+main.py vóór de schrap — geverifieerd 2026-05-03: 0 hits buiten `pages/bank.py:10` zelf. Veilig om te verwijderen. |
| Body-token wint niet van inline style op `layout.py:331` (`ui.query('body').style(...)`) | DoD-item dat expliciet beide regels in dezelfde commit moet aanpakken. Smoke-test verifieert achtergrond-kleur in pywebview. |
| Tier 3 visuele wijziging op `.q-card` blijkt te storend voor fiscale density (radius te rond, shadow te zwaar) | User-acceptatie-check na Tier 1 PR voordat we Tier 2 starten. Mitigatie: `--radius` lager (8px ipv 12px) of `--shadow` lichter. Single-token-tweak, niet rewrite. |
| pytest faalt op een UI-string-check die we niet kenden | Eerst Tier 1-PR draaien als dry-run en pytest checken vóór commit. |
| Quasar `q-menu` / `q-btn-dropdown` / `q-select` events landen niet door portal-teleport (CLAUDE.md genoemd, eerder rootcause van Kosten-categorie-bug) — een radius/padding override op `.q-menu` of nested classes kan dit subtiel re-introduceren | Smoke-test mag NIET stoppen bij "menu opent visueel". Verplichte check: klik **binnen** het menu/dropdown en valideer dat de event-handler effect heeft (categorie wordt opgeslagen, factuur opent, etc.). Per route in subflow-checklist hierboven uitgewerkt. |

## Implementatie-volgorde (high-level — exacte tasks komen in plan)

1. **Pre-flight**: meet test-baseline (`pytest --collect-only -q | tail -1`),
   commit nummer als kennis-anker in implementatie-plan.
2. **Tier 1 chrome** (één commit, raakt alles): tokens + body-token
   (incl. layout.py:331 fix) + lichte sidebar/header + alle 6 Quasar
   `.q-*` migratie naar buiten layer + font-family rewrite (7 classes)
   + Google Fonts CDN-link verwijderen → smoke-test alle 11 routes
   + pytest baseline.
3. **`/bank` schrappen** (kleine atomic commit): `git rm pages/bank.py`
   + `import pages.bank` weg uit `main.py:33` → pytest groen.
4. **User-acceptatie-checkpoint**: na Tier 1 PR, gebruiker doet
   visuele check op `/aangifte` (en willekeurige andere route) of
   `.q-card` radius/shadow leesbaar blijft. Bij issue: token-tweak
   in Tier 1 commit (geen Tier 2 starten met klacht over Tier 1).
5. **Tier 2 per pagina** (kleine commits, één pagina per commit voor
   reviewability): `/`, `/werkdagen`, `/facturen`, `/transacties`,
   `/kosten`, `/klanten`, `/documenten` → smoke-test per pagina
   (incl. subflow-checks) + pytest na elke commit.
6. **Tier 3 spot-check**: verifieer `/aangifte`, `/jaarafsluiting`,
   `/instellingen` met subflow-checks; geen code-changes verwacht.
7. **End-to-end walk-through**: user loopt alle 11 actieve routes door
   in pywebview voor visuele acceptatie.
8. **Auto-memory update**: `project_visual_refresh.md` met de 9
   tokens + Tier-aanpak + lessons.

Implementatie-plan komt in `docs/superpowers/plans/` na user-review
van deze spec.

## Definition of Done

- [ ] Tokens-blok aanwezig in `layout.py`, sub-secties met visuele
      headers (`/* === ... === */`).
- [ ] Alle 6 huidige Quasar overrides expliciet **buiten**
      `@layer components` met identieke of bewust gewijzigde styling:
      `.q-table th`, `.q-table tbody tr:nth-child(even)`,
      `.page-toolbar .q-field`, 3× `.page-toolbar .q-field--outlined
      .q-field__control` varianten, `.page-toolbar .q-field__label`.
- [ ] Body-background komt uit `var(--bg)` en de inline
      `ui.query('body').style('background-color: ...')` op `layout.py:331`
      is aangepast naar token-referentie of weggehaald (anders wint inline).
- [ ] Header opaque white, sidebar licht-gradient, beide 180px breed.
- [ ] System font-stack live (`-apple-system, ...`) op body+headings.
- [ ] Google Fonts `<link>` voor JetBrains Mono verwijderd uit
      `layout.py` **én** font-family rewrite naar
      `"SF Mono", ui-monospace, Menlo, monospace` op alle 7 classes
      (`.num`, `.mono`, `.chip`, `.seg-btn`, `.selection-bar .sb-count`,
      `.selection-bar .sb-meta`, `.page-sub`) **in dezelfde commit**.
- [ ] `/bank` route + bestand `pages/bank.py` verwijderd; `import
      pages.bank` uit `main.py:33` verwijderd; pytest blijft groen.
- [ ] pytest-baseline gemeten (`pytest --collect-only -q | tail -1`)
      vóór Tier 1 implementatie + alle baseline-tests blijven groen
      na elke commit.
- [ ] Smoke-test alle 11 actieve routes uitgevoerd in pywebview met
      **subflow-checks** (zie § Testing); `/agenda`-grid pixel-
      regressie-vrij.
- [ ] Portal-event-check expliciet uitgevoerd voor minimaal:
      `/transacties` q-select, `/facturen` rij-menu Bewerken,
      `/werkdagen` rij-menu Bewerken, `/jaarafsluiting`
      Heropenen-flow.
- [ ] Factuur-status-flow check: concept→verstuurd via mail-knop +
      betaald→verstuurd→concept via "Markeer als concept" + PDF
      self-healing (alle 3 paden in `/facturen` één keer geklikt).
- [ ] User doet eind-acceptatie walk-through over alle 11 routes en
      bevestigt visuele consistentie (gevoels-check, geen pixel-test).
- [ ] Codex-review op finale `layout.py`-diff: GEEN BEVINDINGEN of
      bewust geaccepteerde nuance.
- [ ] Auto-memory `project_visual_refresh.md` (of vergelijkbaar)
      genoteerd met tokens + scope.

## Open punten (na user-review beslissen)

Geen op dit moment — alle vier scope-keuzes en architectuur-keuze
zijn vastgelegd na Codex-pushback. Mochten tijdens implementatie
nieuwe nuances opduiken (bijv. nav-active contrast op licht), dan
behandelen we die als kleine spec-amendment in deze file.
