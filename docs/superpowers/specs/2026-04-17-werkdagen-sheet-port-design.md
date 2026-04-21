# Werkdagen-sheet port uit redesign — ontwerp

**Datum**: 2026-04-17
**Status**: brainstorm — wacht op user-review
**Context**: `redesign/design_handoff_boekhouding_redesign/` bevat een volledige UI-redesign. Na agent-onderbouwd onderzoek (git fix-patroon, UX-audit, redesign-inventaris) is de **Werkdagen-pagina** gekozen als eerste port: grootste workflow-winst per LOC, additief, laag risico op het weinig-churned bestand `pages/werkdagen.py`.

## Probleem

Huidige `pages/werkdagen.py` (405 LOC) werkt, maar:

1. **Ontbrekend verband met urencriterium.** De pagina is functioneel het *belangrijkste* scherm voor iemand die 1.225 uur/jaar moet halen, maar toont nergens expliciet "hoeveel uur telt mee". Urencriterium-voortgang zit alleen op het dashboard.
2. **Code-onderscheid (ANW/ACH/normaal) niet visueel.** De kolom `Code` is platte tekst. Voor de gebruiker is het cruciaal dat ANW/achterwacht-uren *niet* meetellen voor de urennorm — dit blijft nu onzichtbaar in de tabel.
3. **Status-dropdown als filter-primitief.** De #1 filter is "ongefactureerd" (dagelijks gebruik). Twee clicks (open dropdown, kies waarde) voor elke filterwissel.
4. **Bulk-actiebalk scrolt weg.** De "N werkdagen geselecteerd — Maak factuur"-balk staat inline onder de toolbar. Bij >10 geselecteerde rijen scroll je hem uit beeld terwijl je zelf nog aan het scrollen bent door de tabel.
5. **Multi-klant selectie = harde error.** `pages/werkdagen.py:148-156` geeft een warning-toast "Selectie bevat meerdere klanten" en stopt. Geen constructieve uitweg — user moet handmatig filteren/deselecteren.
6. **Locatie onzichtbaar in tabel.** `werkdagen.locatie` bestaat (al sinds migratie 6), maar staat alleen in het formulier-dialog. Dezelfde klant heeft vaak meerdere huisartsenposten; user moet klikken om te weten welke post het was.
7. **Summary onder de vouw.** Totaal-uren/km/bedrag staan *onder* de tabel. Bij 50+ rijen niet direct zichtbaar.

De redesign in `redesign/design_handoff_boekhouding_redesign/source/pages.jsx:7-126` lost 1–4, 6, 7 op. Punt 5 los ik apart op (zie scope).

## Scope

### In scope (Phase A)

- Volledige layout-port van `Werkdagen` zoals in `pages.jsx:7-126`.
- CSS-fundament: kleur-/typografietokens en tabel-/chip-klassen die overal herbruikbaar zijn. Minimaal nodig voor deze pagina, niet app-breed.
- Multi-klant bulk-flow **vervangen** door een constructieve klant-picker in plaats van error-toast (los van full redesign, maar raakt dezelfde flow — bundelen in één PR is goedkoper dan los).

### Niet in scope

- Invoice-builder suggestion-card ("3 ongefactureerde werkdagen voor deze klant"). → Phase B, aparte PR.
- `⌘K` command-palette. → Later, als appetite blijkt.
- App-brede typografie-token-pass (249 hex-kleuren vervangen). → Alleen per pagina meeporten, niet als eigen doel.
- Dark mode / density modes / accent-swatches.
- Wijzigingen aan `database.py`-queries. Alle velden (`locatie`, `code`, `urennorm`) bestaan al in de huidige `Werkdag`-dataclass.
- Wijzigingen aan `werkdag_form.py` (toevoeg-/bewerk-dialog).

## Ontwerp

### Layout (bovennaar-beneden)

```
┌───────────────────────────────────────────────────────────────┐
│ Werkdagen                                      [Import] [Nieuw]│
│ 142 dagen geregistreerd · 987 uur telt voor urencriterium     │
├───────────────────────────────────────────────────────────────┤
│ [Alle] [Ongefactureerd] [ANW]   [Klant ▾] [Jaar ▾] [Mnd ▾]    │
│                         142 rijen · ∑ 987,0u · 2.340 km · €…  │
├───────────────────────────────────────────────────────────────┤
│   ┏━ 3 geselecteerd · 24,0u · € 2.040,00   [Maak factuur] [✕] ┓
│   (sticky, top: 0, alleen zichtbaar als selectie > 0)         │
├───────────────────────────────────────────────────────────────┤
│ ☐ Datum   Klant              Code  Uren  Km  Tarief Bedrag Fact│
│ ☐ 12-04  Acme BV             [●]   8,0   18  €85   €712   —    │
│          Post Noord                                            │
│ ☒ 11-04  Zorggroep Oost  ANW [●]   8,0   0   €95   €760   —    │
│          Huisartsenpost Z                                      │
│ ☐ 10-04  Zorggroep Oost      [●]   7,5   12  €85   €659   2026-041│
└───────────────────────────────────────────────────────────────┘
```

### Header + subtitle

Behoudt bestaand `page_title('Werkdagen')`. Toevoeging: subtitle-label direct eronder met dynamische tekst. **Scope: jaar-breed, niet gefilterd door segment/klant/maand** (anders spring je cijfers op elke filterwissel, verwarrend).

```python
# Altijd over álle werkdagen van het geselecteerde jaar,
# ongeacht segment/klant/maand-filter
all_year = await get_werkdagen(db, jaar=year)
f"{len(all_year)} dagen in {year} · {urencriterium_uren:.0f} uur telt voor urencriterium"
```

`urencriterium_uren` = `sum(w.uren for w in all_year if w.urennorm)` (ANW + achterwacht hebben `urennorm=False`). Subtitle ververst alleen bij jaar-wissel; segment/klant/maand raken hem niet.

Kleurclass: `.t-small` stijl, grijs (`--ink-3`).

Actieknoppen rechts: "Nieuwe werkdag" (primary) blijft. "Import CSV" wordt **niet** toegevoegd — bestaat niet in huidige app en is geen onderdeel van deze port.

### Filter strip

Segmented tabs vervangen de Status-dropdown:

- **Alle** (default)
- **Ongefactureerd** — filtert op `factuurnummer == ''`
- **ANW** — filtert op `code.startswith('ANW_')` (matcht `ANW_AVOND`/`ANW_NACHT`/`ANW_WEEKEND`)

De `betaald`-waarde verdwijnt als apart filter (call: werkdagen-pagina tracked *werk*, betaling hoort op facturen-pagina). Als user dit filter vaak gebruikt → als 4e tab terug.

Rechts van de tabs blijven: Klant-dropdown, Jaar-dropdown, **Maand-dropdown** (behouden — maandelijkse reconciliatie is een reëel workflow-punt).

Helemaal rechts van de strip (margin-left: auto) een mono-counter:

```
{n_rows} rijen · ∑ {uren:.1f}u · {km:.0f}km · € {bedrag}
```

CSV-downloadknoppen (Urenregistratie, Km-logboek, generieke CSV) verhuizen naar een kebab-menu ("⋯") rechts van de nieuwe-werkdag knop. Behouden, minder beeldruimte.

### Selectie-bar (sticky)

Shows als `table.selected` lengte > 0. Positie: `position: sticky; top: 0;` binnen de content-column.

Inhoud:
- Links: "N geselecteerd" in mono
- Midden: "X,X uur · € Y,YY" in mono (opacity 0.7)
- Rechts: "Maak factuur" (primary, accent bg) + "✕" (deselecteer alles)

Styling: donker (ink bg, bg-text), radius 10px, shadow-md. Verschijnt/verdwijnt via `ui.row().set_visibility()` — geen animatie nodig voor MVP.

### Tabel

Kolommen (weg van de huidige 10-kolomstabel):

| # | Kolom | Breedte | Inhoud | Toelichting |
|---|---|---|---|---|
| 1 | ☐ | 32px | checkbox | Klik-op-rij toggled selectie; checkbox is puur visueel. |
| 2 | Datum | 90px | mono 12px | `dd-mm-yyyy` |
| 3 | Klant | flex | naam + locatie-subline | Locatie klein, `--ink-3`, onder klant-naam |
| 4 | Code | 80px | **chip** | Kleur via `urennorm` + code-prefix: `urennorm=True` → **pos**; `code.startswith('ANW_')` → **info**; `code == 'ACHTERWACHT'` → **neutral**; `code in {'CONGRES','OPLEIDING','OVERIG_ZAK'}` → **warn**. Label op chip = leesbare afkorting: `DAG`/`WKD`/`AV`/`NA`/`ACH`/`ANW-AV`/`ANW-NA`/`ANW-WE`/`CON`/`OPL`/`OVG` |
| 5 | Uren | 60px | mono, right | 1 decimaal |
| 6 | Km | 50px | mono, right | geheel getal |
| 7 | Tarief | 80px | mono, right | `€ X,XX` |
| 8 | Bedrag | 90px | mono, right, 500 | `€ X,XX` |
| 9 | Factuur | 100px | mono 11px | nummer of `—` in `--neg` |
| 10 | ⋯ | 40px | kebab | bewerken/verwijderen/ontkoppelen (laatste alleen als factuurnummer gezet) |

**Status-kolom verdwijnt.** Oude waarden:
- `ongefactureerd` → Factuur-cel toont `—` in `--neg`
- `gefactureerd` / `betaald` → Factuur-cel toont nummer. Onderscheid betaald/onbetaald verloren op deze pagina.

**Kebab-menu** per rij (i.p.v. twee icoontjes): "Bewerken" + "Verwijderen" + "Ontkoppel factuur" (alleen bij factuurnummer). Verwijderen kan geblokkeerd zijn door jaar-lock of gefactureerd-status — nu gebruiken we de bestaande `ValueError`-paden, geen nieuwe logica.

**Actieknoppen-disabled-reden tonen.** Huidige app geeft alleen een toast *na* de klik. Voorstel: als `_is_deletable(w)` False, toon het item disabled met tooltip "Gefactureerde werkdag — ontkoppel eerst". Klein, maar directe helderheid.

### Multi-klant bulk-flow

Vervangt huidige error-pad (`werkdagen.py:148-156`).

Als `len(set(r['klant_id'] for r in selected)) > 1`:

1. Selectie-bar toont i.p.v. "Maak factuur": **"Maak factuur per klant ▾"** (primary-button met dropdown).
2. Dropdown toont de N klanten gesorteerd op aantal dagen, per klant een item: "Acme BV — 3 dagen · 24,0u · € 2.040", "Zorggroep Oost — 2 dagen · 15,0u · € 1.275".
3. Klik op een klant → `table.selected` wordt beperkt tot alleen die klant, daarna bestaande `ga_naar_factuur` flow (navigeer naar `/facturen`, builder opent met die werkdagen).
4. Voor de tweede klant: user komt terug naar `/werkdagen`, selecteert opnieuw en herhaalt. **Geen chaining.** Simpel, KISS, geen extra state.

Deze aanpak geeft altijd een werkende vervolgstap — geen doodlopende toast meer. **Geen nieuwe DB-functies nodig, geen nieuwe session-state.**

*Optioneel later*: na afronden factuur klant-A, als er nog ongefactureerde werkdagen van klant-B in de selectie waren, toon op werkdagen-pagina een banner "1 klant nog te gaan (2 werkdagen voor Zorggroep Oost) — [Verder]". Pas toevoegen als het echt pijn blijkt.

### CSS-fundament (scoped)

Toegevoegd aan `components/layout.py` `@layer components`-block:

- **Design tokens** (als CSS variabelen op `:root`, uit `redesign/source/styles.css`):
  - `--bg: #fafaf7`, `--bg-elev: #ffffff`, `--bg-sunk: #f5f4ef`, `--bg-hover: #f0efe9`
  - `--line: #e8e6df`, `--line-strong: #d8d5cc`
  - `--ink: #15171a`, `--ink-2: #3a3d43`, `--ink-3: #6b6f76`, `--ink-4: #9a9ea5`
  - `--accent: #0f766e`, `--accent-soft: #e6f2f0`, `--accent-ink: #0a524c`
  - `--pos: #0f766e`, `--neg: #b45309`, `--warn: #a16207`, `--info: #1e40af`
- **Typografie-helpers**:
  - `.num { font-family: JetBrains Mono; font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }`
  - `.mono { font-family: JetBrains Mono; }`
  - `.t-micro { font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-4); }`
- **Chip** (klein, herbruikbaar voor StatusChip + code-chip):
  - `.chip { display: inline-flex; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 500; }`
  - Modifiers: `.chip.pos`, `.chip.neg`, `.chip.info`, `.chip.warn`, `.chip.neutral`
- **Segmented tabs**:
  - `.seg { display: inline-flex; border: 1px solid var(--line); border-radius: 7px; overflow: hidden; }`
  - `.seg button { padding: 7px 14px; border: 0; background: var(--bg-elev); color: var(--ink-2); }`
  - `.seg button.on { background: var(--ink); color: var(--bg); }`
- **Sticky selection bar**: één regel met positie-/kleur-regels.

JetBrains Mono via `@font-face` met Google Fonts-link (`fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500`). Inter niet nodig voor Phase A — Quasar's default font blijft.

**Niet** toegevoegd in deze PR: dark-mode-tokens, density-vars, accent-varianten, `.t-display` / Instrument Serif. Die zijn voor toekomstige scope.

### Bestaande `ui.colors(...)` blijft staan

Quasar-primary/positive/negative in `layout.py:134-142` blijven onaangeroerd. Tokens zijn additief; bestaande Quasar-componenten op andere pagina's blijven werken.

## Implementatieaanpak

### Keuze: `ui.table` houden, niet raw `<table>` bouwen

Redesign gebruikt raw `<table>`. In Quasar verliezen we dan sort + pagination voor niks. Plan: `ui.table` houden en alle kolommen via `body-cell-*`-slots aanpassen.

- **Rij-klik-selectie**: `table.on('row-click', ...)` bestaat in NiceGUI 3; toggelen via `table.selected.append(...)` / `.remove(...)`.
- **Row-hover styling**: bestaande Quasar-hover; kleur overridden via CSS target op `.q-table tbody tr:hover`.
- **Selected-rij styling**: in body-row slot een class zetten op basis van `props.selected`.
- **Tabel-rand + radius**: wrapper-div met `--bg-elev`, `border: 1px solid var(--line)`, `border-radius: 12px`, `overflow: hidden`.

Fidelity: ~85%. Wat we opgeven: het exacte dashed-border-between-rows patroon (Quasar gebruikt solid); exacte row-height (Quasar's densiteit is grover). Aanvaardbaar.

### Bestandswijzigingen (schatting)

| Bestand | Delta | Aard |
|---|---|---|
| `components/layout.py` | +80 LOC | CSS-tokens + helper-classes, bovenaan het bestaande `@layer components`-blok |
| `pages/werkdagen.py` | ~−120 / +220 | header-sub, filter-strip, selection-bar, multi-klant-picker, kolom-slots, kebab-menu |
| `components/shared_ui.py` | 0 | `confirm_dialog` gebruiken i.p.v. hand-rolled |
| `tests/test_werkdagen.py` | +100 LOC | nieuwe tests (zie onder) |

Geen database-wijziging, geen migraties.

### Tests

Nieuw bestand `tests/test_werkdagen_sheet.py`:

1. **`test_filter_ongefactureerd`** — filter matcht alleen rijen met `factuurnummer == ''`
2. **`test_filter_anw`** — filter matcht alleen rijen met `code == 'ANW'`
3. **`test_subtitle_only_urennorm_counts`** — subtitle-uren telt alleen rijen met `urennorm=1` (ANW/ACH tellen niet)
4. **`test_summary_counter_updates_with_filter`** — als filter actief, counter toont alleen zichtbare rijen
5. **`test_multi_klant_picker_filters_selection`** — selectie van 2 klanten, klik op klant-A → alleen A-werkdagen blijven in `table.selected`
6. **`test_multi_klant_all_apart_creates_concept_drafts`** — "Alle apart" pad roept `ga_naar_factuur` N keer aan in volgorde (mocken)
7. **`test_single_klant_flow_unchanged`** — als 1 klant geselecteerd, bestaande flow gedraagt identiek als voor de port
8. **`test_ontkoppel_menu_disabled_without_factuurnummer`** — ontkoppel-item alleen klikbaar bij gezette factuurnummer

Bestaande `tests/test_werkdagen*.py` moeten blijven slagen zonder wijzigingen.

### Risico's

- **NiceGUI/Quasar row-click-selectie**: wellicht niet 1:1 met checkbox-state. Zo niet: fallback op alleen checkbox-click. Not a blocker.
- **Google Fonts requires internet**: pywebview cached de font na eerste load; offline werkt daarna. Alternatief: fonts bundelen in `components/` — niet nu, wel als issue blijkt.
- **Kebab-menu disabled-reden**: Quasar's `q-menu` respecteert `disable=true` maar tooltips werken niet altijd op disabled items. Plan B: item blijft klikbaar maar toont een toast met reden. Not a blocker.

## Open vragen (voor user-review)

1. **Betaald-filter**: call = droppen als 4e tab. Akkoord?
2. **Multi-klant "Alle apart"-pad**: aanvaardbaar dat dit N concept-drafts maakt in één go (user kan ze daarna 1-voor-1 reviewen), of sta je erop dat user elk draft handmatig opent?
3. **CSV-export-knoppen naar kebab**: Urenregistratie + Km-logboek worden minder prominent. Die zijn jaarlijks (aangifte-moment) — akkoord dat ze in een ⋯-menu verdwijnen?
4. **Page-subtitle formulering**: "X dagen geregistreerd · Y uur telt voor urencriterium" — OK of beter iets anders?

## Vervolg

Na goedkeuring: plan-document via `writing-plans`-skill, dan implementatie per stap met tests-vóór-code waar redelijk.
