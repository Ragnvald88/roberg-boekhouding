# Jaarafsluiting Redesign — Pure Business Annual Report

## Problem
Jaarafsluiting mixes business annual report with personal tax calculations (IB, ZVW, Box 3).
This duplicates content with the aangifte page and doesn't match standard Dutch jaarcijfers format.

## Design Decision
Jaarafsluiting becomes a pure business report matching Yuki/standard format:
Balans + W&V + Toelichting. All tax content moves to aangifte (follow-up task).

## New Tab Structure (5 tabs)
1. **Balans** — Activa + Passiva + Kapitaalsvergelijking. Manual inputs (bank, crediteuren, overige) via edit toggle. Prior year comparison.
2. **W&V** — Omzet, kosten per categorie, afschrijvingen, winst. Data counts. Prior year comparison.
3. **Toelichting** — Activastaat (MVA verloopoverzicht), grondslagen.
4. **Controles** — Business checks: kosten/omzet ratio, urencriterium, balans check, missing data warnings.
5. **Document** — Inline HTML preview + PDF export.

## KPI Strip
Omzet | Winst | Eigen vermogen | Balanstotaal

## Status Workflow
- `concept` (orange) → `definitief` (green)
- New column `jaarafsluiting_status` in fiscale_params (default 'concept')
- Definitief locks editing; Heropenen reverts with warning

## Edit Mode
- "Bewerken" button on Balans tab toggles manual inputs
- Disabled when status = definitief

## Removed from Jaarafsluiting
- Invoer tab (balans inputs → inline; personal inputs → aangifte later)
- Fiscaal tab (fiscal waterfall → aangifte later)
- Belasting tab (IB/ZVW/Box3 → aangifte later)
- Fiscal advisory panel (→ aangifte later)
- Personal KPIs (IB+ZVW, Resultaat)

## Navigation Order
New: Bank → Jaarafsluiting → Aangifte → Instellingen

## PDF
Cover → Balans (with prior year) → W&V → Toelichting. No IB/Box3.

## Status: DONE (jaarafsluiting v2 implemented, 284 tests passing)

---

# Phase 2: Aangifte + Dashboard Update

## Bugs to fix
1. Dashboard "Geschatte IB" KPI links to /jaarafsluiting (line 202 dashboard.py) → should link to /aangifte
2. Aangifte auto-doc detection checks wrong path: `DB_PATH.parent / 'jaarafsluiting'` (line 753 aangifte.py) → should check `DB_PATH.parent / 'pdf' / {year}/`

## Aangifte changes needed
1. **Add lijfrente input** to Prive & aftrek tab (alongside AOV). Currently not editable anywhere in main workflow. The save_prive function already preserves lijfrente from DB (line 469) — just needs an input field + include in update_ib_inputs call.
2. **Add ZA/SA toggles** to Winst tab. User should be able to toggle while reviewing fiscal waterfall. Currently only editable in Instellingen. Import `update_za_sa_toggles` from database.
3. **Add fiscal advisory panel**. Was on old jaarafsluiting Controles tab. Options: (a) new "Advies" tab on aangifte, or (b) integrated into Overzicht tab. Content: ZA trajectory, SA tracking (max 3x in 5 years), KIA check, lijfrente/jaarruimte hints, belastingdruk analysis.
4. **Add missing data warnings**. Prominent alerts when: no uitgaven for year, no AOV entered, jaarafsluiting not definitief. Similar to jaarafsluiting's missing data warnings.
5. **Add jaarafsluiting status check**. Show badge "Jaarafsluiting {year}: Concept/Definitief" with link. Warn if not definitief.

## Dashboard changes needed
- "Geschatte IB" KPI: fix link to /aangifte
- Consider whether dashboard should remain business-focused (no IB KPI) to match jaarafsluiting separation. The fiscal engine call in dashboard (_compute_ib_estimate) duplicates work.

## Key files to modify
- `pages/aangifte.py` — main changes
- `pages/dashboard.py` — fix link + consider removing IB KPI
- `database.py` — no schema changes needed (all columns exist)

## Principle
Aangifte becomes the SINGLE place for all personal tax inputs and calculations. Jaarafsluiting = business only. Dashboard = business overview.
