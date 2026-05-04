# /instellingen page redesign — Sprint G design

**Status**: design approved — pending writing-plans → implementation
**Date**: 2026-05-04
**Trigger**: user feedback "afthans lelijke pagina" + "upload vlak heel lelijk" tijdens Sprint D klant-color visuele validatie.
**Scope**: visual polish + small structural improvements (no feature additions, no fiscal/data changes).
**Baseline**: pytest 1298 groen, master HEAD `6d0017a`, Sprint A→F + 2 post-merge audits afgerond.

## Problem statement

`/instellingen` heeft 3 tabs (Bedrijfsgegevens / Fiscale parameters / Backup). Visuele kwaliteit ligt achter bij de rest van de app post-Sprint A→F:

- **Bedrijfsgegevens**: 10 inputs full-width vertikaal in één card — visuele "muur van velden", geen subgroepering, geen 2-koloms gebruik van de 1400px-window. Logo-upload is NiceGUI's `ui.upload` met `flat bordered` defaults — onzichtbare drop-zone, los floating preview, geen frame.
- **Fiscale parameters**: heeft al subsectie-titels en 2-koloms grid in deel van de form, maar inconsistent — PVV-veld + Box 3-velden + Arbeidskorting-schijven staan in losse `ui.row()` constructs naast de grid, breken het visuele ritme.
- **Backup**: spartaans maar functioneel — laagste prioriteit.

Page voelt als "developer ingericht", niet als settings-pagina van een app die overigens Apple-rustig styling heeft.

## User decisions captured

- **Scope**: B (visual polish + kleine structurele verbeteringen, geen feature-uitbreiding).
- **Fiscaal jaar-pattern**: a (huidige `ui.expansion`-per-jaar blijft — geen pill-row of vertical sidebar).
- **Direction**: Richting 2 — section-cards everywhere, met Codex-amendments toegepast (zie §"Codex amendments").

## Codex amendments toegepast op Richting 2

Per Codex second-opinion van 2026-05-04:

1. **Niet "cards everywhere" letterlijk**: Bedrijfsgegevens echte section-cards, Fiscaal subtielere section-blocks (lichte achtergrond + hairline border + title-row, geen schaduw). Voorkomt card-in-expansion-in-card visuele noise.
2. **Padding-strategie**: GEEN nieuwe globale tokens. Lokale `settings-card` en `settings-section` classes bovenop bestaande 13 globale tokens.
3. **Save-pattern Bedrijfsgegevens**: één `Opslaan`-knop onderaan voor alle 4 cards. Eén logisch profiel, voorkomt gedeeltelijke save.
4. **Logo-upload**: media-row pattern — preview links + "Logo vervangen" rechts + bestandsinfo + "Verwijderen" text-link. Geen drag-drop area.
5. **Cascade-discipline**: nieuwe Quasar-overrides (`.q-card__section` reset, `.q-field` margin-tweaks waar nodig) altijd buiten `@layer components`. Bestaande regel uit Sprint B+F.
6. **Dirty/validation state**: subtiele visuele indicator wanneer user inputs gewijzigd heeft maar nog niet opgeslagen.
7. **Accessibility**: native file-input, alt-text op preview, empty-state placeholder, keyboard-focusable verwijder-actie, status-notify na save.

## Design

### A. Cross-cutting

#### A1. CSS classes (in `components/layout.py`)

Twee nieuwe app-classes BUITEN `@layer components` (anders verliezen ze van Quasar `.q-card` defaults):

```css
.settings-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;          /* genereuser dan default q-card */
    box-shadow: var(--shadow);
    margin-bottom: 16px;
}
.settings-card .settings-card-title {
    font-weight: 600;
    color: var(--text);
    margin-bottom: 4px;
}
.settings-card .settings-card-subtitle {
    color: var(--muted);
    font-size: 0.875rem;
    margin-bottom: 16px;
}
.settings-section {
    background: var(--bg);   /* iets dimmer dan card-surface, geeft "ingebed" gevoel */
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

Tokens hergebruikt: `--surface`, `--border`, `--bg`, `--text`, `--muted`, `--radius`, `--shadow`. Geen nieuwe globale tokens.

Quasar reset (BUITEN layer): `.settings-card .q-card__section { padding: 0; }` (settings-card heeft eigen padding, geen Quasar dubbele).

#### A2. Dirty-state indicator

Subtiele linker-border van 3px op `.settings-card` wanneer user inputs gewijzigd heeft maar nog niet opgeslagen:

```css
.settings-card.is-dirty {
    border-left: 3px solid var(--accent);
}
```

Implementatie: bij elke input-change `card.classes('is-dirty')`, na succesvol save `card.classes(remove='is-dirty')`. Eenvoudig, geen badge of separate notification.

#### A3. Tab-level styling

Bestaande `ui.tabs` styling blijft (al token-based via Sprint B). Geen wijzigingen aan tab-bar zelf.

### B. Tab 1 — Bedrijfsgegevens

**4 section-cards onder elkaar**, elk `.settings-card`-class. **Eén `Opslaan`-knop onderaan** alle cards (één logisch profiel).

#### B1. Card "Identiteit"
- Velden: Bedrijfsnaam, Naam, Functie
- Layout: Bedrijfsnaam volle breedte, Naam + Functie 2-koloms (`ui.grid(columns=2)`)
- Subtitle helper: geen (titel "Identiteit" is helder genoeg)

#### B2. Card "Contact"
- Velden: Adres, Postcode + Plaats, Telefoon, E-mail
- Layout: Adres volle breedte, rest 2-koloms
- Subtitle helper: geen

#### B3. Card "Fiscaal & financieel"
- Velden: KvK, IBAN, Thuisplaats
- Layout: 2-koloms (KvK + IBAN op één rij; Thuisplaats volle breedte eronder)
- Subtitle helper: "Thuisplaats wordt gebruikt voor reiskosten-berekeningen."

#### B4. Card "Logo & visueel"
- **Logo-tile (media-row pattern)**:
  - Links: framed 96×96 preview met `border-radius: 8px`, hairline border. Bij geen logo: SVG-placeholder icon (Quasar `image_not_supported` of vergelijkbaar) met "Geen logo geüpload" caption.
  - Rechts: primaire knop "Logo vervangen" (echte file-input via NiceGUI's `ui.upload` met custom styling — `flat dense color=primary`, eventueel verberg de Quasar drop-zone via `display:none` op `.q-uploader__list` als de styling nog steeds intrudes). Bestandsinfo eronder ("logo.png · 87 KB") als label. Tertiair: "Verwijderen" tekst-knop met Quasar `color=negative` (niet via CSS-var — we hebben geen `--negative` token), alleen renderen als logo bestaat.
  - Klik op preview opent ook file-picker (a11y win — preview is dan ook actionable).
- **Klant-kleur-toggle** onder logo-tile, met label "Klant-kleuren tonen in agenda" + helper-tekst (huidige tooltip wordt zichtbare caption).

#### B5. Save-knop
- Onderaan alle cards: `ui.button('Wijzigingen opslaan', icon='save').props('color=primary')`.
- Validatie: huidige IBAN/Naam/KvK-checks blijven. Loops door alle 4 cards heen.
- Na save: `ui.notify('Bedrijfsgegevens opgeslagen', type='positive')`, alle dirty-states gewist.

### C. Tab 2 — Fiscale parameters

#### C1. Toolbar (top)
- "Nieuw jaar" input + "Jaar toevoegen" button blijven onveranderd. Eventueel in compactere `ui.row` met `gap-3`, geen card.

#### C2. Per jaar-expansion
- `ui.expansion(jaar, icon='calendar_month')` blijft.
- Locked-banner voor definitieve jaren behouden — krijgt `.alert-card --warning` styling (al bestaande Sprint F class).
- **Binnen de expansion**: alle subgroepen krijgen `.settings-section`-class (subtiel, niet zwaar):
  - IB Schijven
  - Ondernemersaftrek
  - Investeringsaftrek (KIA)
  - Heffingskortingen
  - ZVW
  - Eigen woning
  - Overig per jaar
  - Toggles (ZA/SA + Partner toedeling) — gemerged in één section "Toggles & partner"
  - PVV premies — naar 2-koloms grid in section
  - Box 3 parameters — naar 2-koloms grid in section
  - Arbeidskorting schijven — section met bracket-table (huidige `ui.row`-per-bracket blijft, alleen padding/spacing token-based)
- **2-koloms grid binnen elke section** voor velden (consistent met Bedrijfsgegevens). PVV en Box 3 worden uit `ui.row(gap-4 flex-wrap)` getrokken naar grid.
- **Save per jaar onderaan blijft** (`Opslaan {jaar}`) — elk jaar is een eigen DB-row.

#### C3. Add-bracket button
- Behoud huidige `Schijf toevoegen` knop, alleen visueel uitgelijnd in section.

### D. Tab 3 — Backup

#### D1. Card "Backup downloaden"
- `.settings-card`-class.
- Title: "Backup downloaden"
- Helper-paragraaf met huidige uitleg.
- Primaire knop "Download backup" (icon=download).
- Optioneel future: laatste-backup-timestamp eronder als beschikbaar — out of scope voor nu.

#### D2. Card "Database-locatie"
- `.settings-card`-class.
- Title: "Database-locatie"
- Monospace path in een `<code>` of dimmer-styled `ui.label` met `font-family: SF Mono` + selectable. Klein "Kopieer pad" icon-knop rechts (Quasar `q-icon` clipboard).
- Caption: "Bewaar backups buiten deze machine (externe schijf, NAS, of cloudmap)."

### E. Out of scope (expliciet)

- **Geen sticky save-bar** — jaar-expansion in Fiscaal maakt sticky ambigu (welk jaar wordt opgeslagen?). Inline saves blijven.
- **Geen tab-restructure** — 3 tabs blijven (Bedrijfsgegevens / Fiscale parameters / Backup). Geen "Branding"-tab.
- **Geen pill-selector voor jaren** — user koos `a` (expansion blijft).
- **Geen nieuwe globale CSS-tokens** — alleen lokale `settings-*` classes.
- **Geen drag-drop logo-upload** — media-row pattern (preview + button) verkozen.
- **Geen wijzigingen aan fiscale calculation-engine** of aan database-schema.
- **Geen wijzigingen aan validation-logica** (`_validate_fiscal_params`, `_validate_arbeidskorting_brackets`) — alleen UI-wrapping verandert.

## Test-strategie

### E1. Bestaande tests blijven groen
- Pytest baseline 1298 — geen regressies toegestaan.
- `tests/test_visual_css.py` cascade-lint blijft groen — alle nieuwe `.q-*` overrides moeten in allow-list of buiten `@layer components`.

### E2. Nieuwe tests
- Visuele unit-tests niet realistisch (NiceGUI rendert pas in browser/pywebview). Vertrouwen op:
  - Cascade-lint regel-tests (uitbreiden voor `.settings-card`, `.settings-section` als ze op Quasar-elementen worden toegepast)
  - Manuele rooktest per tab door user in pywebview
- Smoke-test save-flows: bestaande `tests/test_instellingen.py` (indien aanwezig — anders niet toevoegen tenzij echt nodig). Bedrijfsgegevens save test dat nu inline-save doet, blijft werken met gecombineerde-save-pattern.

### E3. 4-layer review per task
Conform CLAUDE.md "Codex-samenwerking als kwaliteitsstandaard":
- implementer subagent (opus) → spec reviewer (opus) → Codex CLI → code-quality reviewer (opus)
- Geen task "klaar" zonder alle 4.

### E4. Manuele rooktest
Na elke tab afgerond — user valideert in pywebview:
- Tab 1: alle 10 velden zichtbaar in correct gegroepeerde cards, save werkt, logo-upload werkt, dirty-state visueel zichtbaar.
- Tab 2: alle jaren expandeerbaar, sections netjes binnen elke jaar, save per jaar werkt, locked-jaar disabled.
- Tab 3: backup-download werkt, path is copyable.

## Risk register

| # | Risico | Kans | Impact | Mitigatie |
|---|---|---|---|---|
| R1 | Cascade-bug: `.settings-card` of `.settings-section` overruled door Quasar default | M | M | Beide BUITEN `@layer components`, getest via uitbreiding `tests/test_visual_css.py` allow-list als nodig |
| R2 | Save-validatie breekt bij gecombineerde-save Bedrijfsgegevens | L | M | Behoud bestaande validatie-functies, alleen call-site verandert |
| R3 | Logo-upload custom styling werkt niet (NiceGUI `ui.upload` is Quasar-coupled) | M | L | Fall-back: behoud `ui.upload` maar style 'm minimaal + verberg behind eigen knop met `display:none` truc indien nodig |
| R4 | Dirty-state indicator wordt niet correct gewist na save | L | L | Test op end-of-save-handler, gebruik `card.classes(remove='is-dirty')` consequent |
| R5 | Fiscaal-tab sections worden té druk visueel | M | M | Hairline border + lichte bg + geen schaduw (Codex spec). Indien nog te druk: degradeer naar enkel title + spacing zonder border |

## References

- Sprint A→F + post-audit project memory: `~/.claude/projects/.../memory/project_sprint_cdef.md`
- Sprint B visual refresh design: `docs/superpowers/specs/2026-05-03-sprint-b-visual-refresh-design.md`
- Codex 4-layer review pattern: CLAUDE.md "Codex-samenwerking als kwaliteitsstandaard"
- Cascade-discipline rules: CLAUDE.md "Visuele tokens (Sprint B+, 2026-05-04)"
- Existing tokens: `components/layout.py` `:root` block (13 vars)
- Source files to modify: `pages/instellingen.py` (921 LoC), `components/layout.py` (CSS additions)
