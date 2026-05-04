# Dashboard redesign — synthesis plan (Sprint H)

**Status**: design proposal — pending user approval before writing-plans
**Date**: 2026-05-04
**Authors**: Claude (Opus 4.7) + Codex (parallel) + mutual critique synthesis
**Trigger**: user request "verbeterde dashboard, samen met codex, grondig"
**Baseline**: pytest 1300 groen, master HEAD `2ab5080` (Sprint G done)

## Process record

1. Both agents produced independent plans (saved at `/tmp/claude_dashboard_plan.md` + `/tmp/codex_dashboard_plan.md`)
2. Mutual critique pass (saved at `/tmp/claude_critique_of_codex.md` + `/tmp/codex_critique_of_claude.md`)
3. **Codex catched 3 real bugs in Claude's data-source claims** — all incorporated below
4. **Claude added 2 huisarts-domain tiles Codex missed** — SPH-pension reservering + tax-calendar countdown
5. **Both converged on**: action-zone werklijst consolidation, hero-focus, customization via /instellingen NOT drag-drop

## Core thesis

Huidig dashboard is **info-rich maar workflow-blind** (Codex's framing). Toont "waar sta je?" maar niet "wat moet je vandaag doen?" of "haal je 1225 uur en heb je de belasting gereserveerd?". Tegelijk mist het **huisarts-specifieke pijnpunten**: SPH-pensioenpremie tracking en tax-calendar countdown (Claude's adds). Wand van losse `alert-card`/`severity-card`'s onderaan = visual debt.

**Fix in 5 fasen**: (1) hero-focus + belasting-reservering tile, (2) actie-zone consolidation, (3) urencriterium-projectie + 6-weken prognose + quick-actions, (4) customization-laag + remaining toggleable tiles, (5) post-merge audit.

---

## Design

### A. Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ Header: "Overzicht 2026"  [+ Werkdag] [+ Factuur] [+ Uitgave]    │  ← Quick-actions
│                                                          [Jaar▾] │
├──────────────────────────────────────────────────────────────────┤
│ HERO STRIP (4 tiles, fixed, always visible)                      │
│ ┌────────────┬────────────┬────────────────┬─────────────────┐   │
│ │ Omzet YTD  │ Winst YTD  │ Belasting-     │ Urencriterium   │   │
│ │ + YoY      │ + YoY      │ reservering    │ + projectie     │   │
│ │ + spark    │ + spark    │ + confidence   │ (1340/1180 etc)│   │
│ └────────────┴────────────┴────────────────┴─────────────────┘   │
├──────────────────────────────────────────────────────────────────┤
│ ACTIE-ZONE (1 card, full-width, fixed)                           │
│ "Vandaag te doen" — max 5 prioritised rows (severity DESC)       │
├──────────────────────────────────────────────────────────────────┤
│ INZICHT-GRID (configurable, default 4-on, responsive 2-col)      │
│ ┌──────────────────┬──────────────────┐                          │
│ │ I-1 Cumulatief   │ I-2 Kosten donut │                          │
│ ├──────────────────┼──────────────────┤                          │
│ │ I-3 6-wk progn.  │ I-4 Top klanten  │                          │
│ └──────────────────┴──────────────────┘                          │
│ ⚙ Wat zie ik hier? → /instellingen → Dashboard                   │
└──────────────────────────────────────────────────────────────────┘
```

### B. Tile inventory

#### Quick-actions row (3 CTAs, fixed)

| CTA | Action | Data |
|---|---|---|
| + Werkdag | `/agenda` of `/werkdagen` (kies één — open vraag F1) | new |
| + Factuur | `/facturen?nieuw=1` | bestaande deep-link |
| + Uitgave | `/transacties` met add-cash-uitgave dialog open | bestaande |

Visueel: `unelevated color=primary` (CTA-recognizable), niet huidige `flat dense color=secondary` (grijs op grijs).

#### Hero-strip (4 fixed tiles)

| # | Tile | Data | Status |
|---|---|---|---|
| H1 | **Omzet YTD + YoY** | `get_kpis(jaar)` + `get_kpis_tot_datum(jaar-1, vorig_datum)` | already exists, keep |
| H2 | **Winst YTD + YoY** | `kpis['omzet'] - kpis['kosten']` + previous YTD | already exists, keep — **drop misleading sparkline** (was omzet-data, niet winst) |
| H3 | **Belasting-reservering** | `_compute_ib_estimate.netto_ib + zvw - va_betaald` (engine-exact, not rule-of-thumb) | NEW presentation; data already computed for huidige Belasting-prognose |
| H4 | **Urencriterium-projectie** | `kpis['uren']` + nieuwe pure helper `project_urencriterium(uren_ytd, target, today)` | NEW projection helper; existing strip-card upgrade naar hero |

Belastingprognose-card (huidig) wordt **opgesplitst**: H3 toont alleen het reserverings-getal; de huidige progress-bar + termijn-info verhuist naar /aangifte (was te dicht voor een hero-card).

#### Actie-zone (1 fixed tile, full width)

| Tile | Doel | Data sources merged |
|---|---|---|
| **"Vandaag te doen"** | Geprioriteerde top-5 acties | `get_health_alerts` + `get_werkdagen_ongefactureerd_summary` + `get_openstaande_facturen` + tax-calendar-deadlines |

Layout: één card, max 5 rows. Elke row: severity-icon + 1-line message + "Bekijk"-mini-knop. Bij >5: ghost-link "+N meer" naar bv. nieuwe page `/audit` of bestaande pagina.

**Vervangt**: huidige losse `alert-card`'s + `severity-card`'s onderaan dashboard. Geen aparte AANDACHTSPUNTEN-section meer.

Pure helper `prioritise_actions(...) -> list[ActionRow]` met severity-volgorde + age-tiebreak (testable via unit-tests).

#### Inzicht-grid (configurable, 8 toggleable tiles, default 4)

| # | Tile | Data | Default | Why |
|---|---|---|---|---|
| I-1 | Cumulatieve omzet YoY | `get_omzet_per_maand_tot_datum` (bestaand) | ON | Trend at-a-glance |
| I-2 | Kosten breakdown donut | `get_kosten_breakdown` (bestaand) | ON | Welke categorie eet meeste |
| I-3 | **6-weken omzet-prognose** | `services.agenda.get_zes_weken_prognose` (Sprint A reuse) | ON | Forward-looking pipeline |
| I-4 | **Top 5 klanten + concentratie** | `get_omzet_per_klant` (bestaand, unused on dashboard) | ON | Klant-risico signaal |
| I-5 | **Cash-positie + flow YTD** | `fiscale_params.balans_bank_saldo` (opening) + `SUM(banktransacties.bedrag WHERE jaar=current)` | OFF | Liquiditeit. **Caveat**: opening-saldo moet ingevuld zijn per jaar in /instellingen → Bedrijfsgegevens (al-bestaand veld). |
| I-6 | **SPH-pensioen reservering YTD** | `SUM(uitgaven.bedrag WHERE categorie='Pensioenpremie SPH' AND jaar=current)` + optionele target `bedrijfsgegevens.sph_target_per_maand` (NEW field, default NULL = no target) | OFF | Huisarts-verplicht (€1k-2k/mo); 3-jaar-lag SPH premie-bepaling = vooruit reserveren. |
| I-7 | **Aangifte-documenten checklist** (DETAIL) | `get_aangifte_documenten` + `AANGIFTE_DOCS` diff (welke missen?) | OFF | Q1-Q2 jaarafsluiting trigger |
| I-8 | **Tax-calendar countdown** | hardcoded BD-deadlines per kalender-jaar (statisch, ~5 entries) | OFF | "Volgende VA-betaling op 31 mei (24 dagen)" |
| I-9 | Terugkerende kosten | `get_terugkerende_kosten` (bestaand in /kosten) | OFF | Lekkende subscriptions vinden |
| I-10 | Vorige jaarafsluiting status | `jaarafsluiting_snapshots` query (NEW, ~5 LoC) | OFF | "Is 2025 al definitief?" Q1-Q2 check |

**Note**: Alle 8 tiles toggleable. Tier 1 (hero) en actie-zone NIET toggleable (pijler-functies).

### C. Dropped from both plans (explicit YAGNI)

- **AOV-kosten tracker** — AOV zit in `BANK_EXTRA_CATEGORIEEN` (bank-side only); per CLAUDE.md is AOV "GEEN bedrijfskosten → Box 1 inkomensvoorziening". AOV-tile op bedrijfs-dashboard is conceptually wrong-scope.
- **Werkdag-density heatmap** — YAGNI voor v1
- **Saved presets** ("Operationeel" / "Fiscale focus" radio) — defer; show/hide is genoeg
- **Drag-drop reorder** — over-engineering voor 5-15 widgets in 1-user app
- **Klant-concentratie threshold-alert** — banks vragen 'm voor zakelijke financiering, voor 1-user dashboard niet nodig
- **Sort-order in customization** — defer; vaste display-order is fine

### D. Customization architecture

**Locatie**: nieuwe **6e tab "Dashboard"** in `/instellingen` (sluit aan op Sprint G pattern).

**UI**:
- `settings-card` "Inzicht-tegels" met checkbox-lijst van I-1 t/m I-10
- Defaults: I-1, I-2, I-3, I-4 = ON; rest OFF
- Onderaan: één `Wijzigingen opslaan`-knop (consistent met Bedrijfsgegevens-tab)

**Persistence**: nieuwe column `bedrijfsgegevens.dashboard_widgets_json TEXT NULL` (NULL = defaults) via migratie 39. Format:
```json
{"version": 1, "widgets": {"I-5": true, "I-6": true, "I-1": false}}
```
Render-loop op dashboard.py:
- Reads JSON config; unknown keys ignored (forward-compat)
- Missing keys → use default
- Schema-version check (v1 → future v2 migration path)

**Hero-strip + Actie-zone NIET configureerbaar**.

### E. Phasing (synthesised — Codex base + Claude adjustments)

| Phase | Scope | Risk | Effort | Tests |
|---|---|---|---|---|
| **1** | Visual cleanup + page-title-year + Belasting-reservering hero-tile + drop dead `hero-value-pos/-neg` classes + drop misleading winst-sparkline | LOW | ~3-4u | 1 unit test op `compute_belasting_reservering` pure helper + cascade-lint |
| **2** | Actie-zone werklijst consolidation — kills wall-of-alerts | MED | ~3-4u | 5 unit tests op `prioritise_actions` pure helper |
| **3** | Urencriterium-projectie hero-upgrade + 6-weken prognose I-3 tile + Quick-actions header + fix documenten click-to-werkdagen → /aangifte/documenten | LOW | ~3-4u | 6 unit tests op `project_urencriterium` (jan, dec, low/high tempo, leap year, urencriterium=0 edge) |
| **4** | Customization infra (mig 39 + /instellingen Dashboard tab + render-loop config) + remaining toggleable tiles (I-4 Top klanten, I-5 Cash, I-6 SPH, I-7 Documenten checklist, I-8 Tax-calendar, I-10 Vorige jaarafsluiting). I-9 Terugkerende kosten reuse `get_terugkerende_kosten`. | MED | ~5-6u | 4-5 unit tests per nieuwe tile + 1 integration test config round-trip |
| **5** | Combined post-merge audit (Codex + code-quality reviewer parallel) + cascade-lint nieuwe classes + memory update | LOW | ~1-2u | — |

**Total realistic estimate**: ~15-20u verspreid over 5 atomic-shippable phases (~5-7 dagen part-time).

### F. Risk register

| # | Risico | Kans | Impact | Mitigatie |
|---|---|---|---|---|
| R1 | Cash-positie I-5 toont onjuist saldo als user `balans_bank_saldo` niet heeft ingevuld | M | M | Detect (=0) en toon "Vul opening-saldo in /instellingen" met deep-link, geen €0-illusie |
| R2 | SPH-target field `bedrijfsgegevens.sph_target_per_maand` is nieuw — first-run shows "geen target" | L | L | Tile rendert "YTD: €X · doel: niet ingesteld" met link naar /instellingen |
| R3 | Customization JSON schema-versioning bij toekomstige tile-additions | L | M | `version` field + render-loop tolerates unknown keys + missing keys = default-on |
| R4 | Action-zone consolidation breekt huidige health-alert links | M | M | Behoud `link`-field uit `get_health_alerts`, render als "Bekijk"-knop per row |
| R5 | Tax-calendar I-8 deadlines hardcoded → out-of-date next year | L | L | Hardcoded per-jaar-tabel in `services/dashboard.py:tax_calendar(jaar)`; jaar-update is 1 PR/year |
| R6 | Cumulative file-size growth — pages/dashboard.py = 683 LoC nu, +400-500 = 1100+ LoC | M | L | Extract helpers naar `services/dashboard.py` + `components/dashboard_widgets.py` per Codex's plan |

### G. Out of scope (explicit)

- AOV-tile (zie §C)
- Werkdag-density heatmap (zie §C)
- Drag-drop, sort-order, presets (zie §C)
- Cashflow-projection / runway-detail (defer)
- Mobile-specific layout (pywebview default 1400px window)
- Tests voor visual rendering (NiceGUI lacks visual-regression test framework — manual smoke-test gate per phase, like Sprint G)

---

## Open questions for user (4 — vereist user-input)

1. **Quick-actions header — "+ Werkdag" route**: huidige header heeft `/werkdagen`-deep-link. Met Sprint A bestaat ook `/agenda`. Welke is canonical entry voor "nieuwe werkdag" — `/agenda` (Sprint A planning-view) of `/werkdagen` (lijst-view)? **Mijn voorstel: `/agenda`** (planning-flow voelt natuurlijker).

2. **Cash-positie I-5 opening-balance UX**: gebruiken we `fiscale_params.balans_bank_saldo` (al-bestaand jaar-veld) of een nieuwe `bedrijfsgegevens.opening_bank_saldo`? **Mijn voorstel: bestaande `balans_bank_saldo`** want dat veld wordt al per jaar in jaarafsluiting ingevuld → year-rollover natuurlijk.

3. **SPH-target**: nieuw veld `bedrijfsgegevens.sph_target_per_maand` (nullable INTEGER, default NULL = "geen target") of editable per jaar via `fiscale_params`? **Mijn voorstel: bedrijfsgegevens** — target is gebruiker-pref, niet fiscale waarde.

4. **"Vandaag te doen" max items**: vast op 5 of dynamisch (bv. tot 8 max + scroll bij meer)? **Mijn voorstel: vast 5 + ghost-link "+N meer"** — voorkomt overwhelm.

---

## Vraag aan jou

- Akkoord op de 3-zone layout (hero / actie-zone / inzicht-grid)?
- Akkoord op de 4-tile hero-strip met Belasting-reservering + Urencriterium-projectie als nieuwe tiles?
- Akkoord op actie-zone consolidation (vervangt huidige wall-of-alerts)?
- Akkoord op customization via show/hide checkboxes in /instellingen Dashboard-tab (geen drag-drop)?
- Akkoord op de 4 open vragen hierboven (mijn voorstellen overnemen of redirect)?

Of bredere wijziging — bv andere tile dropping/adding, andere phase-volgorde, andere customization-aanpak.
