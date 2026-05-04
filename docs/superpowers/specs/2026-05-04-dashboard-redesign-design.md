# Dashboard redesign — final synthesis (v3, post-discussion)

**Status**: design proposal — pending user decision on 3 items (U1/U2/U3) before writing-plans
**Date**: 2026-05-04
**Authors**: Claude (Opus 4.7) + Codex CLI (parallel) + 2-round mutual critique + bilateral discussion-round
**Trigger**: user request "verbeterde dashboard, samen met codex, grondig, neem de tijd"
**Baseline**: pytest 1300 groen, master HEAD `f9e130d` (eerdere v1-synthesis)

## Process record

1. Both agents wrote v1 plans independently (~2500w each)
2. Round-1 mutual critique → Codex caught 3 data-bugs in Claude v1; Claude added 2 huisarts-domain tiles
3. v1 synthesis (commit f9e130d) — both later judged as "too quick"
4. Deeper online research (~10 sources: Xero, QuickBooks SE, Moneybird, Acumulus, Monarch, Bonsai, SPH 2026 publicatie, Belastingdienst VA) — see §H sources
5. Both agents wrote v2 plans independently
6. Round-2 critiques (`/tmp/claude_v2_critique_of_codex_v2.md`, `/tmp/codex_v2_critique_of_claude_v2.md`) — sharper than round-1
7. **Bilateral discussion-round** (`/tmp/claude_discussion_response.md`, `/tmp/codex_discussion_response.md`) — both conceded multiple positions, refined to 3 user-decision items
8. **This v3 spec** = post-discussion synthesis

## Core thesis

V1-synthesis was a **tile catalogue**. V3 is a **dashboard that does work**. Four substantive shifts vs. current dashboard:

1. **Forward-looking als pijler** — hero wordt coherente forward-looking strip (Omzet-YTD als rear-view anchor + 3 projections); Winst-YTD verhuist naar sub-line onder Jaareinde-projectie
2. **Actie-inbox met inline-actions** — Acumulus-pattern: 4 row-types met `[Stuur herinnering]/[Categoriseer▾]/[Upload nu]/[Verstuur]`-quick-actions, NIET alleen `[Bekijk]`. Plus seasonal-row injector (apr/mei IB-aangifte countdown, nov/dec VA-laatste termijn).
3. **SPH default-on met exact-formule** — 23.94% × min(€137.800, prognose-winst − €19.172). Zelfde discipline als IB-prognose, niet rule-of-thumb.
4. **Privé-zone conditional** — AOV (geen "persoonlijke SPH" — bewezen factuele error in v2; zie discussion C1). Auto-collapse als geen AOV-tx, auto-visible bij wel.

---

## A. Layout

```
┌────────────────────────────────────────────────────────────────────┐
│ HEADER                                                              │
│ "Overzicht 2026"   [+ Werkdag] [+ Factuur] [+ Uitgave]   [Jaar▾]   │
├────────────────────────────────────────────────────────────────────┤
│ ZONE 1 — HERO STRIP (4 fixed tiles, no toggle)                     │
│ ┌──────────────┬───────────────┬─────────────────┬──────────────┐ │
│ │ Omzet YTD    │ Jaareinde-    │ Belasting-      │ Urencrit-    │ │
│ │ + YoY        │ projectie     │ reservering     │ projectie    │ │
│ │ + sparkline  │ (winst-proj.) │ (engine-exact)  │ (1340/1180)  │ │
│ │              │ + confidence  │ + .is-tekort    │ + groen/rood │ │
│ │              │ Winst-YTD ─┐  │   modifier      │              │ │
│ │              │ als sub-line │ bij tekort >€1k │              │ │
│ └──────────────┴──┬──────────┘──┴─────────────────┴──────────────┘ │
├────────────────────────────────────────────────────────────────────┤
│ ZONE 2 — ACTIE-INBOX (1 full-width card, fixed)                    │
│ "Vandaag te doen" — geprioriteerde rows met INLINE actions         │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ ▲ 2 facturen verlopen >30d         [Stuur herinnering] [Bekijk]│ │
│ │ ⚠ 4 bank-tx ongecategoriseerd      [Categoriseer▾]             │ │
│ │ • Aangifte-doc 'Jaaropg. SPH' mist [Upload nu]                 │ │
│ │ • Concept-factuur 18 dagen stale   [Verstuur]                  │ │
│ │ ⓘ IB-aangifte over 18 dagen        (seizoens-row, apr/mei)     │ │
│ │ + 2 meer in /audit-page                                        │ │
│ └────────────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────┤
│ ZONE 3 — INZICHT-GRID (configurable, max 6 visible, 2-col)         │
│ ┌──────────────────┬────────────────────┐                          │
│ │ I-1 Cumulatief   │ I-2 Kosten donut   │                          │
│ ├──────────────────┼────────────────────┤                          │
│ │ I-3 SPH-status   │ I-4 6-wk prognose  │                          │
│ └──────────────────┴────────────────────┘                          │
│ ⚙ Tegels aanpassen → /instellingen → Dashboard                     │
├────────────────────────────────────────────────────────────────────┤
│ ZONE 4 — PRIVÉ-VASTE-LASTEN (conditional, auto-collapse)            │
│ ┌────────────────────────────────────────────────────────────────┐ │
│ │ Privé · AOV YTD: €4.8k · "niet aftrekbaar als bedrijfskost"    │ │
│ └────────────────────────────────────────────────────────────────┘ │
│ (Auto-collapse als geen AOV-tx in current jaar; toggleable)        │
└────────────────────────────────────────────────────────────────────┘
```

---

## B. Tile inventory

### Quick-actions header (3 CTAs)

| CTA | Target | Visual |
|---|---|---|
| `+ Werkdag` | `/agenda` (Sprint A planning-flow) | `unelevated color=primary` |
| `+ Factuur` | `/facturen?nieuw=1` (existing deep-link) | `unelevated color=primary` |
| `+ Uitgave` | `/transacties?dialog=cash` (existing) | `unelevated color=primary` |

Replace huidige grijze `flat dense color=secondary` knoppen — geen CTA-recognizable nu.

### ZONE 1 — Hero strip (4 fixed tiles)

| # | Tile | Data source | Notes |
|---|---|---|---|
| H1 | **Omzet YTD + YoY** | `get_kpis(jaar)` + `get_kpis_tot_datum(jaar-1)` | Behouden + sparkline (alleen tot today) |
| H2 | **Jaareinde-projectie** | `extrapoleer_jaaromzet(jaar)` (bestaand) | Toon: winst-projectie + confidence-badge. **Winst-YTD als sub-line eronder** ("YTD: €X · projectie: €Y") — **U1**: 1 of 2 numbers? |
| H3 | **Belasting-reservering** | `_compute_ib_estimate.netto_ib + zvw - va_betaald` (engine-exact) | Toon getal + progress-bar. **`.is-tekort` modifier-class** wanneer `(berekend_jaarbelasting × maand/12 - va_betaald) > €1000` (Sprint G `.is-dirty` precedent — geen banner) |
| H4 | **Urencriterium-projectie** | `services.agenda.get_urencriterium_projectie` (Sprint A — al bestaand) | "Bij dit tempo: 1340 (groen) / 1180 (rood)" |

### ZONE 2 — Action-inbox (1 fixed card)

**4 row-types met inline-actions in Phase 3** + 1 deferred:

| Row type | Data source | Inline action | Phase |
|---|---|---|---|
| `verlopen_factuur` | `get_openstaande_facturen` filter on overdue | `[Stuur herinnering]` (reuse `_build_herinnering_body` + `open_mail_with_attachment` uit `pages/facturen.py`) — **U3**: inline send of confirm-dialog? | 3 |
| `bank_tx_ongecategoriseerd` | `get_health_alerts.uncategorized_bank` | inline `q-select` met sign-aware categorieën (zelfde patroon als `/transacties`) | 3 |
| `documenten_ontbreken` | `get_aangifte_documenten` diff `AANGIFTE_DOCS` | `[Upload nu]` file-picker direct (bypass `/documenten` navigation) | 3 |
| `concept_factuur_stale_>14d` | `get_facturen` filter `status='concept'` AND `datum<today-14d` | `[Verstuur]` status-flip via `update_factuur_status` | 3 |
| `werkdag_ongefactureerd` | `get_werkdagen_ongefactureerd_summary` | `[Genereer factuur]` deep-link (vereist nieuwe `/facturen?nieuw=1&werkdagen=ids` flow OR reuse Sprint A "Factureer geselecteerde"-pattern; **decide tijdens Phase 6**) | 6 |

**Seasonal-row injector** (`_seasonal_action_rows(today) → list[ActionRow]`):
- Apr/Mei: "IB-aangifte over X dagen" (severity escalates van info→warning→critical bij <14d)
- Nov/Dec: "VA-laatste termijn vóór 31 dec" (info als VA-tx YTD < expected; critical als <14d)
- Nov-Jan: "Jaarafsluiting vorig jaar nog niet definitief" (info; absorb hier ipv aparte tile)

Pure helper `prioritise_actions(...) -> list[ActionRow]` met severity-volgorde + age-tiebreak. Max 5 visible + ghost-link "+N meer in /audit".

**Vervangt** huidige losse `alert-card` + `severity-card` wand onderaan dashboard.

### ZONE 3 — Inzicht-grid (8 toggleable tiles, max 6 visible, default 4-on)

| # | Tile | Data | Default | Notes |
|---|---|---|---|---|
| I-1 | Cumulatieve omzet YoY | `get_omzet_per_maand_tot_datum` (bestaand) | ON | Behouden uit huidig dashboard |
| I-2 | Kosten breakdown donut | `get_kosten_breakdown` (bestaand) | ON | Behouden |
| I-3 | **SPH-status met geprognoseerde 2026-verplichting** | `SUM(uitgaven WHERE categorie='Pensioenpremie SPH' AND jaar=current)` + computed: `0.2394 × min(€137.800, max(0, winst_extrapolatie - €19.172))` met tooltip "Geschat — werkelijke 2026-verplichting wordt op pensioenbasis 3 jaar terug berekend en kan ±20% afwijken" | ON | Default-on want huisarts-pijler. v1.1 may add optional `pensioenbasis_3jr_terug` input in /instellingen voor exacte berekening. |
| I-4 | 6-weken omzet-prognose | `services.agenda.get_zes_weken_prognose` (Sprint A reuse) | ON | Forward pipeline |
| I-5 | Top 5 klanten + concentratie | `get_omzet_per_klant` (bestaand, unused on dashboard nu) | OFF | Klant-risico signaal |
| I-6 | Aangifte-documenten DETAIL checklist | `get_aangifte_documenten` + `AANGIFTE_DOCS` diff | OFF | Q1-Q2 trigger |
| I-7 | Cash-positie + flow YTD | `fiscale_params.balans_bank_saldo` (opening, **NULL-check niet =0**) + SUM(banktx.bedrag waar jaar=current) | OFF | Empty-state: "Vul opening-saldo in /instellingen" met deep-link |
| I-8 | Tax-calendar (alle 5 deadlines) | hardcoded per-jaar tabel in `services/dashboard.py:tax_calendar(jaar)` | OFF | Volledig overzicht; seasonal-row injector toont alleen meest-relevante |

**Cap**: max 6 visible. 7e toggle aan → toast "Limiet 6 tegels bereikt — verberg eerst een andere tegel om deze toe te voegen". Geen disabled-checkbox (silent), wel duidelijke feedback.

### ZONE 4 — Privé-vaste-lasten (conditional, auto-collapse)

- **AOV ONLY** (geen "persoonlijke SPH" — SPH is bedrijfskost in ons model, zie CLAUDE.md "Pensioenpremie SPH: WEL bedrijfskosten")
- Data: `SUM(banktransacties WHERE categorie='AOV' AND year=current)`
- Tooltip: "Niet aftrekbaar als bedrijfskost — wel relevant voor netto-inkomen"
- **Auto-collapse**: als geen AOV-tx bestaat in jaar (`SELECT EXISTS(...)` query at render-time), collapse default. Anders auto-visible.
- **Manual override** persisteert in `dashboard_widgets_json.prive_section_collapsed` (gebruiker kan permanent collapsed/visible zetten)

---

## C. Customization architecture

**Locatie**: nieuwe **6e tab "Dashboard"** in `/instellingen` (sluit aan op Sprint G pattern).

**Discoverability**: `⚙ Tegels aanpassen`-link onderaan zone 3 → deep-link naar `/instellingen?tab=dashboard`. **U2**: wording + locatie?

**Persistence**: nieuwe column `bedrijfsgegevens.dashboard_widgets_json TEXT NULL` (NULL = defaults) via migratie 39. Format:

```json
{
  "schema_version": 1,
  "widgets": {
    "I-1": true, "I-2": true, "I-3": true, "I-4": true,
    "I-5": false, "I-6": false, "I-7": false, "I-8": false
  },
  "prive_section_collapsed": null  /* null = auto-detect; true/false = manual override */
}
```

**Render-rules** (4 defensiveness-cases):
1. `dashboard_widgets_json IS NULL` → use `DEFAULT_WIDGETS = {I-1..I-4 ON, I-5..I-8 OFF}`
2. `schema_version` ≠ huidige version → fall through to defaults + warning-log (do NOT migrate silently)
3. Unknown widget keys (e.g. `I-99`) → ignore
4. Missing widget keys → fall through to default-on/-off per `DEFAULT_WIDGETS`

**Hero-strip + Action-inbox NIET configureerbaar** (pijler-functies altijd visible).

---

## D. Phasing (post-discussion, 7 phases)

| Phase | Scope | Risk | Effort | Tests |
|---|---|---|---|---|
| **1** | Visual cleanup + page-title-year + Belasting-reservering hero-tile + `.is-tekort` modifier-class + drop misleidende winst-sparkline + drop dead `hero-value-pos/-neg` classes + fix documenten-link → `/aangifte/documenten` | LOW | ~4u | 1 unit `compute_belasting_reservering_progress` (zie §F1) + cascade-lint |
| **2** | Hero re-shape: Jaareinde-projectie hero-tile + Urencriterium-projectie hero (reuse `services.agenda.get_urencriterium_projectie` — al bestaand!) + Quick-actions header (3 CTAs unelevated primary) | LOW | ~3u | 4 unit `compute_jaareinde_projectie_display` (early year/mid/dec/empty) |
| **3** | Action-inbox met **4 inline actions** (Stuur herinnering, Categoriseer, Upload nu, Verstuur) + seasonal-row injector | MED | ~5-6u | 8 unit `prioritise_actions` (severity-volgorde, age-tiebreak, max-5, info-rows) + 4 unit `_seasonal_action_rows` (apr/mei/nov/dec edges) + 4 integration click-handler tests |
| **4a** | Customisation infra (mig 39 + /instellingen "Dashboard" tab + render-loop config + 4 defensiveness-tests) | MED | ~3-4u | 4 round-trip + defensiveness tests |
| **4b** | 5 inzicht-tiles bouwen: I-3 SPH (exact-formule + tooltip) · I-4 6-wk prognose · I-5 Top klanten · I-6 Documenten checklist · I-7 Cash-positie (NULL-empty-state) · I-8 Tax-calendar full | MED | ~6u | 4-5 unit tests per tile |
| **5** | Privé-zone (AOV only, conditional auto-collapse via EXISTS query, manual override persistence) | LOW | ~2u | 2 unit `should_show_prive_zone` (empty/non-empty + manual override) |
| **6** | `Genereer factuur` deep-link (Phase 3 deferred row-type) — design `/facturen?nieuw=1&werkdagen=ids` OR reuse Sprint A "Factureer geselecteerde"-pattern + post-merge audit (Codex + code-quality reviewer parallel) + cascade-lint nieuwe classes + memory update | LOW | ~3u | smoke-tests + audit |

**Total realistic**: **~26-28u** verspreid over 7 atomic-shippable phases (~6-8 dagen part-time werk met 4-layer review per task).

**Critical-path**: Phases 1+2 alone (~7u) leveren ~60% van de waarde. Optie om Phase 1+2 als v1-release te shippen + Phase 3-6 als sprint H.5 — **U(extra)**: ship-fast-iterate of monolithic? (zie §F2)

---

## E. Risk register v3

| # | Risico | Kans | Impact | Mitigatie |
|---|---|---|---|---|
| R1 | Cash-positie I-7 toont onjuist saldo als `balans_bank_saldo IS NULL` per jaar | M | M | Empty-state-detection via `IS NULL` per jaar (NIET `=0` — Codex round-2 catch). Toon "Vul opening-saldo in /instellingen → Bedrijf" met deep-link |
| R2 | SPH-tile I-3 tonen verkeerd door inkomen-extrapolatie ongelijk aan AOW-pensioeninkomen | M | L | Tooltip "Geschat — werkelijke 2026-verplichting wordt op pensioenbasis 3 jaar terug berekend en kan ±20% afwijken". v1.1 kan optional input-veld in /instellingen toevoegen |
| R3 | Customisation JSON schema-evolution wanneer widget-keys toekomstig veranderen | L | M | `schema_version` field + render-loop tolerates unknown keys + missing keys = default-on/-off per `DEFAULT_WIDGETS`. Geen silent migration. |
| R4 | "Stuur herinnering" inline action breekt huidige Mail.app integration | L | M | Reuse exact `_build_herinnering_body` + `open_mail_with_attachment` (geen fork). Behoud bestaande UTF-8 wrap + pyobjc-flow |
| R5 | Tax-calendar I-8 + seasonal-row injector hardcoded → verouderd in 2027 | L | L | `services/dashboard.py:tax_calendar(jaar) -> list[dict]` met per-jaar tabel. Jaar-update is 1 PR/year (low-touch) |
| R6 | Action-zone consolidation breekt toegankelijkheid huidige health-alert links | M | M | Behoud `link`-field uit `get_health_alerts`; render exact zoals voor in nieuwe action-row. Behavioral test. |
| R7 | dashboard.py file-size growth (683 → 1100+ LoC) | M | L | Extract: `services/dashboard.py` (action-zone helpers + projection-helpers + tax_calendar + seasonal-row), `components/dashboard_widgets.py` (per-tile renderers). Eén-file-per-domein consistentie met `services/agenda.py` pattern |
| R8 | Tile-cap max-6 toast firing dynamic — UX-friction bij user die 7e toggle wil | L | L | Toast met clear next-step ("verberg eerst een andere tegel om deze toe te voegen"). Niet disabled-checkbox (silent) |
| R9 | Phase 6 deep-link werkdag→factuur — geen bestaand pattern, Sprint A precedent mis-cited in eerdere drafts | M | M | Phase 6 design-decision: of nieuwe deep-link (geconsulteerde NiceGUI/router-pattern) OR reuse Sprint A "Factureer geselecteerde"-knop in /werkdagen. **Decide tijdens Phase 6 implementation, niet pre-commit** |
| R10 | Privé-zone auto-collapse query (`SELECT EXISTS`) per render kost performance | L | L | Eén EXISTS-query naast bestaande 13 in `asyncio.gather`. <5ms expected. Cache zou over-engineering zijn |

---

## F. Specifications for newly-named functions

### F1. `compute_belasting_reservering_progress`

```python
def compute_belasting_reservering_progress(
    berekend_jaarbelasting: float,  # IB + ZVW prognose voor heel jaar
    va_betaald_ytd: float,           # som VA-betalingen tot vandaag
    today: date,
) -> tuple[Literal['op_koers', 'tekort', 'overreservering'], float]:
    """Returns (status, diff_amount). diff > 0 = je moet nog reserveren;
    < 0 = je hebt overgereserveerd.

    Threshold: 'tekort' if (expected_va_ytd - va_betaald_ytd) > 1000;
    'overreservering' if < -2000; else 'op_koers'.
    """
    months_elapsed = today.month
    expected_va_ytd = berekend_jaarbelasting * months_elapsed / 12
    diff = expected_va_ytd - va_betaald_ytd
    if diff > 1000:
        return ('tekort', diff)
    if diff < -2000:
        return ('overreservering', diff)
    return ('op_koers', diff)
```

### F2. `_seasonal_action_rows`

```python
def _seasonal_action_rows(today: date) -> list[ActionRow]:
    """Emit seasonal context-rows for action-inbox.

    Apr/Mei: IB-aangifte countdown
    Nov/Dec: VA-laatste termijn
    Nov-Jan: Vorige jaarafsluiting status
    """
    rows = []
    if today.month in (4, 5):
        deadline = date(today.year, 5, 1)
        days_remaining = (deadline - today).days
        if days_remaining > 0:
            severity = 'critical' if days_remaining < 14 else 'warning'
            rows.append(ActionRow(
                kind='ib_aangifte_deadline',
                severity=severity,
                message=f'IB-aangifte over {days_remaining} dagen',
                link='/aangifte',
            ))
    # nov/dec, nov-jan: similar logic
    return rows
```

---

## G. User decisions needed (3 items, U1-U3)

### U1. Hero "Jaareinde-projectie" — show 1 number or 2?

**Option A (1 number)**: alleen winst-projectie, simpler scan. "ga ik 'm halen?"
**Option B (2 numbers)**: omzet-projectie + winst-projectie + confidence-badge, fuller picture but more visual real-estate.

**My (Claude) lean**: A — 1 number is cleaner-hero. Codex's lean: B — fuller-snapshot.

### U2. Customisation-link wording + locatie

Wording: `⚙ Tegels aanpassen` (Codex) / `⚙ Aanpassen` (Claude) / `⚙ Dashboard instellen` / iets anders?
Locatie: footer van zone 3 (Codex) / footer van whole dashboard (Claude).

### U3. Action-zone "Stuur herinnering" — inline send of confirm-dialog?

**Inline send** (Acumulus pattern): klik = Mail.app opent direct met conceptbericht. Lower friction.
**Confirm-dialog** (consistency met rest van app): klik → "Wil je herinnering sturen voor X facturen?" → bevestigen → Mail.app. Safer.

**My lean**: dialog (consistency). Codex's lean: dialog (safer).

---

## H. Sources used

### Round-1 + round-2 research

- [Xero Dashboard customization](https://www.xero.com/us/accounting-software/dashboard/) — drag-drop, watchlist, account+reconcile
- [QuickBooks Solopreneur](https://quickbooks.intuit.com/solopreneur/) — 90-day forecast, mileage tracker
- [Monarch Money customizable dashboard](https://www.monarchmoney.com/features/dashboard) — in-page Customize, goal-progress
- [Acumulus dashboard review](https://acumulus.nl/) — first-screen pattern, memos, re-send invoice
- [Bonsai Tax](https://www.hellobonsai.com/taxes) — savings-goal widget
- [SPH 2026 premie publicatie](https://www.huisartsenpensioen.nl/actueel/nieuwsberichten/uw-pensioenpremie-in-2026/) — 23.94% × (income up to 137,800 - 19,172)
- [Belastingdienst VA](https://www.belastingdienst.nl/wps/wcm/connect/nl/voorlopige-aanslag/voorlopige-aanslag) — 11 termijnen, 1 mei deadline
- [Cloudscape configurable dashboard](https://cloudscape.design/patterns/general/service-dashboard/configurable-dashboard/) — show/hide pattern
- [Pencil&Paper drag-drop UX](https://www.pencilandpaper.io/articles/ux-pattern-drag-and-drop) — drag-drop best when reorder is frequent
- [Smashing UX dashboard real-time](https://www.smashingmagazine.com/2025/09/ux-strategies-real-time-dashboards/) — sparkline+metric pairing
- [DataCamp dashboard design tutorial](https://www.datacamp.com/tutorial/dashboard-design-tutorial) — 5-7 KPIs above the fold

### Reference plans/critiques (process documents)

- `/tmp/claude_dashboard_plan.md` — Claude v1
- `/tmp/codex_dashboard_plan.md` — Codex v1
- `/tmp/claude_v2_dashboard_plan.md` — Claude v2 (post-deeper-research)
- `/tmp/codex_v2_dashboard_plan.md` — Codex v2 (parallel)
- `/tmp/claude_critique_of_codex.md` — round-1 critique
- `/tmp/codex_critique_of_claude.md` — round-1 critique
- `/tmp/claude_v2_critique_of_codex_v2.md` — round-2 critique
- `/tmp/codex_v2_critique_of_claude_v2.md` — round-2 critique
- `/tmp/claude_discussion_response.md` — bilateral discussion
- `/tmp/codex_discussion_response.md` — bilateral discussion

---

## I. Out of scope (explicit YAGNI, both agents agree)

- ❌ AOV als bedrijfskost-tile (wrong-scope per CLAUDE.md)
- ❌ "Persoonlijke SPH" (factuele error in v2 — SPH is bedrijfskost, niet privé)
- ❌ Werkdag-density heatmap (defer)
- ❌ Saved presets ("Operationeel" / "Fiscale focus" radio) — defer; show/hide is genoeg
- ❌ Drag-drop reorder (over-engineering voor 8 widgets in 1-user app)
- ❌ Sort-order in customization (defer)
- ❌ Klant-concentratie threshold-alert (banks-vraag, voor 1-user dashboard niet)
- ❌ Cashflow-projection / runway-detail (out of YAGNI v1)
- ❌ Maand-filter in header (Claude wins; defer naar `/dashboard/maand/YYYY-MM` als ooit nodig)
- ❌ Per-tile `compute_seasonal_severity()` (Claude wins; vervangen door action-zone-row injection — Codex's compromise)
- ❌ N7 changes-since-last-visit (defer)
- ❌ In-dashboard edit-mode (Monarch-pattern; over-engineering — settings-tab is genoeg)
- ❌ Mobile-specific layout (pywebview default 1400px window)
- ❌ Memos / notes (Acumulus-feature; out-of-dashboard scope tenzij user vraagt)
- ❌ Multi-bedrijf dashboard (1-user app)
- ❌ Tests voor visual rendering (NiceGUI lacks visual-regression; manual smoke-test gate per phase, like Sprint G)

---

## Bottom line

**v1-synthesis was een tegel-catalogus. v3 is een dashboard dat *werk doet*.** Vier shifts:
1. Forward-looking als pijler (Jaareinde-projectie hero, niet I-7)
2. Actie-inbox met inline-actions (4 row-types ipv passive `[Bekijk]`)
3. SPH default-on met exact-formule (huisarts-pijler)
4. Privé-zone conditional (AOV only, auto-collapse)

Plus: max-6 tile-cap discipline, `.is-tekort` modifier (geen banner), seasonal-row injector (cheap compromise), customisation via /instellingen tab + ⚙-link, Phase 4 split.

**Realistic effort**: 26-28u over 7 phases. Critical-path Phase 1+2 ~7u = 60% van de waarde indien gefaseerd shippable.

**Vraag aan jou**: 3 user-decision items (U1, U2, U3) + optioneel decision over phasing-strategy (monolithic Sprint H of Phase 1+2-eerst-iterate).
