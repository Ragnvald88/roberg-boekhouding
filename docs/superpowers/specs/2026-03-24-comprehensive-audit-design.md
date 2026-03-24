# Comprehensive Audit: Roberg Boekhouding

**Date**: 2026-03-24
**Goal**: Determine if the app can fully replace Boekhouder for 2025+ IB-aangifte filing
**Approach**: Domain-driven audit (fiscal correctness, data integrity, completeness, operational safety)
**Scope**: Conservative — real bugs, proven gaps, filing-critical issues only

## Context

- Standalone NiceGUI + SQLite bookkeeping app for a Dutch eenmanszaak huisartswaarnemer
- 19k lines of Python, 484 tests, 10 pages, 10 DB tables
- Fiscal engine validated against Boekhouder 2023/2024 reports
- Cross-referenced against actual Yuki jaarcijfers PDFs (2023 + 2024)
- User wants to file 2025 aangifte independently without accountant review

## Cross-Reference: Boekhouder/Yuki Jaarcijfers vs App

### W&V 2024

| Line | Yuki | App | Gap | Cause |
|---|---|---|---|---|
| Omzet | 124,337 | 123,176 | -1,161 | Work-date vs invoice-date (cross-year factuur 2024-002) |
| Pensioenpremie SPH | 18,387 | in "Pensioenpremie SPH" | — | Category exists, mapping OK |
| Km-vergoeding | 3,622 | computed from werkdagen | — | Structural difference (not an expense, computed) |
| Representatie | 534 | in "Representatie" | — | Category exists |
| Adviseurs | 1,627 | in "Accountancy/software" | — | Category exists |
| Telefoon/internet | 985 | in "Telefoon/KPN" | — | Category exists |
| Contributies | 494 | in "Lidmaatschappen" | — | Category exists |
| Kleine aanschaffen | 398 | in "Kleine aankopen" | — | Category exists |
| Automatiseringskosten | 35 | **No clear category** | ~35 | Force-fit into Accountancy/software or Kleine aankopen |
| Verzekeringen | 2,031 | in "Verzekeringen" | — | Category exists |
| Bankkosten | 281 | in "Bankkosten" | — | Category exists |
| Betalingsverschillen | -0.15 | **Not modelled** | ~0 | Immaterial |
| Opleidingskosten | 30 | in "Scholingskosten" | — | Category exists |
| Privé-gebruik | -446 | **Not a category** | ~446 | Uses zakelijk_pct on assets instead |
| Overige kosten | 255 | **No "Overig" category** | ~255 | Must be force-fit |
| Totaal Bedrijfslasten | 28,232 | 28,861 | +629 | Privé-gebruik +446, categories, km diff |
| Afschrijvingen | 960 | 532 | -428 | Mystery asset (~457) + monthly vs daily pro-rata |
| **Winst** | **95,146** | **93,783** | **-1,363** | Sum of above gaps |

### Balans 2024

| Line | Yuki | App | Gap | Issue |
|---|---|---|---|---|
| Vaste activa | 5,896 | ~5,364 | -532 | Mystery asset book value (Boekhouder artifact, self-reconciled) |
| Debiteuren | 5,964 | 7,391 (combined) | — | App's get_debiteuren_op_peildatum ≈ Yuki debit + NTF |
| Nog te factureren | 1,428 | in above | — | Included in app's debiteuren figure |
| Nog te ontvangen g&d | 304 | **Not modelled** | -304 | Prepaid expenses missing from app |
| Bank | 618 | 618 | 0 | Manual input, matches |
| Crediteuren | 2,919 | 2,919 | 0 | Manual input, matches |
| Overlopende passiva | 26 | in overige_schulden | — | Small |
| **Eigen vermogen** | **11,264** | calculated | — | Depends on activa completeness |

### Expense Category Mapping (App → Yuki)

| App Category | Yuki Equivalent | Status |
|---|---|---|
| Pensioenpremie SPH | 40150 Pensioenen | OK |
| Telefoon/KPN | 45100 Telefoon- en internetkosten | OK |
| Verzekeringen | 45400 Verzekeringen algemeen | OK |
| Accountancy/software | 45500 Administratie- en accountantskosten | OK |
| Representatie | 44400 Representatiekosten | OK |
| Lidmaatschappen | 45200 Contributies en abonnementen | OK |
| Kleine aankopen | 45310 Kleine aanschaffen kantoor | OK |
| Scholingskosten | 40300 Opleidingskosten | OK |
| Bankkosten | 45800 Bankkosten | OK |
| Investeringen | (balance sheet, not W&V) | OK |
| — | 45350 Automatiseringskosten | **Missing** |
| — | 45900 Betalingsverschillen | **Missing** |
| — | 45920 Privé-gebruik kosten | **Structural diff** |
| — | 45990 Overige algemene kosten | **Missing** |

---

## Domain 1: Fiscal Correctness

Issues that could cause wrong numbers on the aangifte.

### F1: Box 3 rendement_ratio formula is non-standard
- **Severity**: Medium
- **File**: `fiscal/berekeningen.py:153-162`
- **Issue**: Uses weighted-average scaling (`rendement_ratio = totaal_rendement / (bezittingen - schulden)`) then applies to grondslag. Official BD method applies per-category rendement percentages directly. With `overige_bezittingen > 0`, result diverges.
- **Impact**: Box 3 belasting shown could differ by up to hundreds of euros from portal.

### F2: `bereken_ib` standalone omits tariefsaanpassing
- **Severity**: Low (tests only, no production path)
- **File**: `fiscal/berekeningen.py:453-505`
- **Issue**: Missing tariefsaanpassing in standalone function. Up to ~€2000 systematically low for high earners.
- **Action**: Deprecate or add tariefsaanpassing.

### F3: Partner AHK never calculated
- **Severity**: High (filing-critical)
- **File**: `fiscal/berekeningen.py` — absent
- **Issue**: Inputs exist (partner loon/loonheffing), labels say "Nodig voor berekening AHK partner", but no calculation. Boekhouder 2024 = €116.
- **Action**: Add partner AHK calculation to `bereken_volledig()`.

### F4: Missing params → KeyError crash
- **Severity**: Low
- **File**: `fiscal/berekeningen.py:237,252,266,341`
- **Issue**: `params['key']` without `.get()`. Partially filled params crash the engine.
- **Action**: Add graceful error handling or validation.

### F5: 2026 fiscal values are provisional
- **Severity**: Low (not filing year yet)
- **File**: `import_/seed_data.py`
- **Issue**: MKB 12.70% and Box 3 bank rendement 1.28% for 2026 are not definitief.
- **Action**: Flag provisional values in UI.

### F6: Extrapolation month mismatch
- **Severity**: Low (dashboard only)
- **File**: `components/fiscal_utils.py:218-237`
- **Issue**: When `day < 15`, prior-year slice uses `[:month]` but current-year uses `complete_months = month - 1`.
- **Action**: Align slices.

### F7: Boekhouder test tolerances too loose
- **Severity**: Medium
- **Files**: `tests/test_fiscal.py`
- **Issue**: Assertions use €5-50 margins. A €49 error passes silently. For filing-critical code, tolerances should be ≤ €1.
- **Action**: Tighten all fiscal test assertions.

---

## Domain 2: Data Integrity

Issues where bad input or operations could corrupt the administration.

### D1: Deleting gefactureerd/betaald werkdagen has no guard
- **Severity**: High
- **File**: `database.py:704-707`, `pages/werkdagen.py:122,311`
- **Issue**: `delete_werkdag` is a bare DELETE with no status check. Deleting a gefactureerd werkdag leaves the linked factuur with wrong totals.
- **Action**: Block deletion of werkdagen with status != 'ongefactureerd'.

### D2: Deleting betaald factuur resets werkdagen to ongefactureerd
- **Severity**: High
- **File**: `database.py:832-859`
- **Issue**: Werkdagen go from betaald → ongefactureerd → could be re-invoiced → double revenue.
- **Action**: Block deletion of betaald/verstuurd facturen, or require explicit confirmation with warning.

### D3: Jaarafsluiting auto-matches payments without review
- **Severity**: Medium
- **File**: `pages/jaarafsluiting.py:44-51`
- **Issue**: `apply_factuur_matches` runs on every page load. False-positive match silently corrupts status.
- **Action**: Show matches for user review before applying.

### D4: Invoice number race condition
- **Severity**: Medium
- **File**: `database.py:761-770`
- **Issue**: Read-then-compute pattern. Two tabs → same number → IntegrityError crash.
- **Action**: Use INSERT with conflict detection, or SELECT MAX inside the INSERT transaction.

### D5: `update_factuur_status` accepts any string
- **Severity**: Low
- **File**: `database.py:773-798`
- **Issue**: No transition validation. UI prevents invalid transitions, but DB function doesn't.
- **Action**: Add allowed transitions check.

### D6: `update_factuur` allows changes on sent/paid invoices
- **Severity**: Low
- **File**: `database.py:808-829`
- **Issue**: No status guard. UI restricts editing, but DB function is unprotected.
- **Action**: Add status check in DB function.

### D7: Stale `betaald` INTEGER column
- **Severity**: Low
- **File**: `database.py:72`
- **Issue**: Dead column from before migration 14. Never updated. Potential confusion.
- **Action**: Drop in future migration.

### D8: Denormalized factuur totals not recomputed
- **Severity**: Low
- **File**: `database.py:816`
- **Issue**: `totaal_uren`/`totaal_km` stored at creation, not updated on werkdag edit.
- **Action**: Document or recompute on edit.

### D9: Stale locatie text on werkdag
- **Severity**: Low
- **File**: `database.py:56`
- **Issue**: `locatie` text not cleared when `locatie_id` becomes NULL (location deleted).
- **Action**: Clear locatie text in SET NULL trigger or on delete.

---

## Domain 3: Completeness

What's missing for a solo 2025+ aangifte.

### Filing-critical:

### C1: Partner AHK not calculated
- **Severity**: High
- **Detail**: See F3 above. Must be added to bereken_volledig and displayed in aangifte overzicht.

### C2: Non-werkdag business km not tracked
- **Severity**: Medium
- **File**: werkdagen table (no mechanism for non-patient km)
- **Issue**: Congresses, meetings, opleiding km are lost. Boekhouder 2024 had 683 km more than app.
- **Action**: Add a mechanism for non-werkdag business km (e.g., separate km entries or a simple km-log).

### C3: No km-logboek export
- **Severity**: Medium
- **Issue**: BD requires route-level km admin (datum, vertrek, bestemming, km, doel). App has datum + km + klant but no from/to addresses.
- **Action**: Generate km-logboek PDF/CSV from werkdagen + klant_locaties (address from locatie).

### C4: No uren-overzicht export
- **Severity**: Medium
- **Issue**: BD may verify urencriterium. Need per-day hours listing as PDF.
- **Action**: Add uren-overzicht export button on werkdagen page.

### C5: Lijfrente jaarruimte not validated
- **Severity**: Medium
- **Issue**: Any amount accepted. Overclaiming = wrong aangifte.
- **Action**: Add warning when entered amount seems high (or link to BD jaarruimte rekenhulp).

### Jaarstukken quality:

### C8: No debiteuren specificatie in PDF
- **Severity**: Low
- **Action**: List individual open facturen in jaarstukken toelichting.

### C9: No fiscal waterfall in jaarstukken PDF
- **Severity**: Low
- **Action**: Include ZA/MKB/KIA breakdown in annual report.

### C10: Privé-onttrekkingen not broken down
- **Severity**: Low
- **Action**: Show sub-lines matching Yuki format (opnamen, stortingen, belastingen, verzekeringen, overige).

### Validations:

### C11: "Ingediende aangifte" label says "(Boekhouder)"
- **Severity**: Low
- **Action**: Update label.

### C12: No warning when KIA drops to zero
- **Severity**: Low
- **Action**: Add explanatory message.

### C13: No warning for stale Box 3 data
- **Severity**: Low
- **Action**: Flag when peildatum values appear to be from a prior year.

### C14: No urencriterium force-majeure awareness
- **Severity**: Low
- **Action**: Add note about art. 3.6 lid 2 exception.

### Not modelled (acceptable):

- Desinvesteringen, HIR, FOR release, practice share, kasstroomoverzicht — not applicable to this business.
- Loon uit dienstverband (C6) — only if employment income resumes.
- Box 3 category split (C7) — manual split in portal is acceptable.

---

## Domain 4: Operational Safety

### O1: Backup WAL checkpoint is FULL, not TRUNCATE
- **Severity**: Medium
- **File**: `pages/instellingen.py:437-438`
- **Action**: Use `PRAGMA wal_checkpoint(TRUNCATE)`.

### O2: Backup ZIP deleted after 10 seconds
- **Severity**: Medium
- **File**: `pages/instellingen.py:456-462`
- **Action**: Track download completion or use longer timeout / user-triggered cleanup.

### O3: No restore functionality
- **Severity**: Medium
- **Action**: Add in-app restore or at minimum show instructions.

### O4: No year-lock enforcement after definitief
- **Severity**: Low
- **Action**: Prevent edits to werkdagen/facturen/uitgaven for definitief years.

### O5: Missing params → KeyError crash
- **Severity**: Low
- **Action**: See F4.

### O6: storage_secret hardcoded
- **Severity**: Low
- **File**: `main.py:46`
- **Action**: Move to environment variable.

### O7: Test tolerances too loose
- **Severity**: Low
- **Action**: See F7.

---

## Prioritized Action List

### Tier 1 — Must fix (filing-critical or data-loss risk)

| # | Item | Domain |
|---|------|--------|
| D1 | Guard werkdag deletion by status | Data integrity |
| D2 | Guard factuur deletion by status (warn for verstuurd/betaald) | Data integrity |
| C1/F3 | Calculate partner AHK in bereken_volledig | Completeness + Fiscal |
| D3 | Jaarafsluiting: show matches for review before applying | Data integrity |
| F7/O7 | Tighten Boekhouder test tolerances to ≤ €1 | Fiscal correctness |

### Tier 2 — Should fix (correctness or usability for solo filing)

| # | Item | Domain |
|---|------|--------|
| C2 | Non-werkdag business km tracking | Completeness |
| C3 | km-logboek export | Completeness |
| C4 | Uren-overzicht export | Completeness |
| C5 | Lijfrente jaarruimte warning | Completeness |
| CR1 | Add missing expense categories (Overig, Automatisering) | Cross-reference |
| CR2 | Privé-gebruik as explicit W&V line | Cross-reference |
| F1 | Fix Box 3 rendement formula | Fiscal correctness |
| O1+O2 | Fix backup (TRUNCATE + download tracking) | Operational safety |

### Tier 3 — Nice to have

| # | Item | Domain |
|---|------|--------|
| O3 | In-app restore | Operational safety |
| O4 | Year-lock after definitief | Operational safety |
| C8 | Debiteuren specificatie in PDF | Completeness |
| C9 | Fiscal waterfall in jaarstukken PDF | Completeness |
| CR3 | Model "nog te ontvangen goederen" on balance sheet | Cross-reference |
| D4 | Invoice number race condition | Data integrity |
| C11 | Update "Boekhouder" label | Completeness |
| F2 | Deprecate standalone bereken_ib | Fiscal correctness |
| D7 | Drop stale betaald column | Data integrity |
