# Accountant Replacement: Complete Reconciliation & Gap Analysis

**Date**: 2026-03-09
**Purpose**: Analyze Boekhouder accountant reports (2023-2024), reconcile with app data, identify gaps for full accountant replacement.

## Executive Summary

The app can fully replace the accountant for **2024 onwards**. The fiscal engine is validated against Boekhouder and matches all 20 intermediate calculation values. The **critical blocker** is expense import — 458 PDFs exist in the archive but zero are imported in the DB.

For **2023**, the app cannot replicate the full tax calculation because Test had additional income sources (SBOH training + UWV) that are outside the app's scope. 2023 should be treated as historical reference only.

---

## 1. Revenue Reconciliation

### 2023 Revenue (3 sources, all reconciled)

| Source | Amount | Basis |
|---|---|---|
| DB (work-date) | **80,216.82** | All 28 factuur amounts by work month |
| Yuki | **80,756.82** | Accrual (includes betaald werkdagen) |
| Boekhouder fiscal | **79,451** | Fiscal netto-omzet (adjusted) |

**Gaps explained:**
- **DB→Yuki (+540.00)**: "Betaald werkdagen" — work paid directly via bank without formal invoice. Yuki booked these from bank transactions.
- **Yuki→Fiscal (-1,305.82)**: First-year fiscal adjustment. Boekhouder used lower netto-omzet than Yuki. Yuki vorderingen (9,408) vs fiscal (8,103) = 1,305 gap. Likely NTF (nog te factureren) not fully recognized in fiscal year 1.

### 2024 Revenue (4 sources, all reconciled)

| Source | Amount | Basis |
|---|---|---|
| DB (work-date) | **121,129.57** | 54 facturen by work month |
| Yuki | **124,337.36** | Accrual |
| Boekhouder fiscal | **124,337** | = Yuki (no adjustment) |
| Bank | **124,637.73** | Cash received in calendar year |

**Gaps explained:**
- **DB→Yuki/Fiscal (+3,207.79)**: Three components:
  - EUR 1,310: Cross-year factuur 2024-002 (Dec 2023 + Jan 2024 work → attributed to 2023 in DB)
  - EUR 1,428: NTF — Dec 2024 work invoiced Jan 2025 (factuur 22470-25-16, HAP MiddenLand)
  - EUR 470: Betaald werkdagen timing reversal
- **Bank→Yuki (+300.37)**: Minor year-end payment timing

### 2025 Revenue (app is source of truth)

| Source | Amount |
|---|---|
| DB (work-date) | **126,250.79** |

No accountant/Yuki data exists for 2025. The app IS the authoritative source going forward.

---

## 2. Expense Reconciliation

### CRITICAL: Zero expenses imported in DB

The app has 458 expense PDFs in the archive, NONE imported. This is the #1 blocker.

### 2023 Expenses (Yuki reference: EUR 18,235.27)

| Category | Yuki Amount | Yuki Account | Archive PDFs |
|---|---|---|---|
| Pensioenpremie SPH | 12,093.16 | 40150 | 7 files |
| Kilometervergoeding | 2,103.99 | 42500 | (calculated from werkdagen) |
| Representatie | 458.13 | 44400 | 7 files |
| Accountantskosten | 1,026.26 | 45500 | 8 files |
| Telefoon/internet | 375.41 | 45100 | 12 files |
| Contributies | 322.68 | 45200 | 1 file |
| Kleine aanschaffen | 213.50 | 45310 | 2 files |
| Automatisering | 105.30 | 45350 | 1 file |
| Verzekeringen | 1,252.97 | 45400 | 13 files |
| Bankkosten | 121.61 | 45800 | (no PDF — bank statement) |
| Betalingsverschillen | -18.54 | 45900 | (no PDF — rounding) |
| Prive-gebruik | -181.35 | 45920 | (correction, no PDF) |
| Overige | 330.00 | 45990 | ? |
| **Subtotal bedrijfslasten** | **18,203.12** | | |
| Afschr. inventaris | 0.93 | 49200 | (calculated) |
| Afschr. hardware | 31.22 | 49300 | (calculated) |
| **Total incl. afschrijvingen** | **18,235.27** | | **54 PDFs** |

### 2024 Expenses (Yuki reference: EUR 29,191.67)

| Category | Yuki Amount | Yuki Account | Archive PDFs |
|---|---|---|---|
| Pensioenpremie SPH | 18,386.81 | 40150 | 11 files |
| Opleidingskosten | 30.00 | 40300 | 1 file |
| Kilometervergoeding | 3,621.81 | 42500 | (calculated) |
| Representatie | 533.55 | 44400 | 5 files |
| Accountantskosten | 1,627.49 | 45500 | 10 files |
| Telefoon/internet | 985.22 | 45100 | 27 files |
| Contributies | 493.60 | 45200 | 10 files |
| Kleine aanschaffen | 398.04 | 45310 | 3 files |
| Automatisering | 34.50 | 45350 | 0 files |
| Verzekeringen | 2,030.69 | 45400 | 15 files |
| Bankkosten | 281.28 | 45800 | (no PDF) |
| Betalingsverschillen | -0.15 | 45900 | (no PDF) |
| Prive-gebruik | -446.30 | 45920 | (correction) |
| Overige | 255.00 | 45990 | ? |
| **Subtotal bedrijfslasten** | **28,231.54** | | |
| Afschr. inventaris | 14.40 | 49200 | (calculated) |
| Afschr. hardware | 945.73 | 49300 | (calculated) |
| **Total incl. afschrijvingen** | **29,191.67** | | **83 PDFs** |

### Key expense observations

1. **Pensioenpremie SPH ≠ AOV**: The "Pensioenen" line (40150) is the Stichting Pensioenfonds Huisartsen (SPH) contribution — a legitimate business expense. AOV (Allianz Summum) is separate and is NOT a business expense (Box 1 inkomensvoorziening). AOV values: 2023=EUR 1,753, 2024=EUR 2,998.

2. **Kilometervergoeding**: Calculated from werkdagen, not from PDFs. App already tracks km per werkdag at EUR 0.23/km.

3. **Bankkosten & betalingsverschillen**: No PDFs needed — derived from bank statements.

4. **Prive-gebruik**: Correction for private use of business expenses (phone, etc). Negative amount reduces total costs.

5. **Afschrijvingen**: Calculated, not imported as expenses.

---

## 3. Balance Sheet Reconciliation

### 2023 Closing Balance (Yuki vs Fiscal)

| Item | Yuki | Fiscal | Gap |
|---|---|---|---|
| **ACTIVA** | | | |
| Materiele vaste activa | 4,380.55 | 3,938 | 442.55 |
| Vorderingen | 9,408.28 | 8,103 | 1,305.28 |
| Liquide middelen | 15.12 | 15 | 0.12 |
| **Totaal activa** | **13,803.95** | **12,056** | **1,747.95** |
| **PASSIVA** | | | |
| Eigen vermogen | 13,180.75 | 11,242 | 1,938.75 |
| Kortlopende schulden | 623.20 | 814 | -190.80 |
| **Totaal passiva** | **13,803.95** | **12,056** | **1,747.95** |

Gap explanation: The fiscal balance sheet uses rounded amounts and different vorderingen recognition (1,306 lower). This explains most of the 1,748 gap. 2023 was the first year; the fiscal accountant made opening adjustments.

### 2024 Closing Balance (Yuki vs Fiscal — ALIGNED)

| Item | Yuki | Fiscal | Gap |
|---|---|---|---|
| Materiele vaste activa | 5,896.41 | 5,896 | ~0 |
| Vorderingen | 7,694.88 | 7,695 | ~0 |
| Liquide middelen | 617.77 | 618 | ~0 |
| **Totaal activa** | **14,209.06** | **14,209** | **~0** |
| Eigen vermogen | 11,263.90 | 11,264 | ~0 |
| Kortlopende schulden | 2,945.16 | 2,945 | ~0 |
| **Totaal passiva** | **14,209.06** | **14,209** | **~0** |

Perfectly aligned (rounding only). This means the **2024 closing balance = authoritative opening balance for 2025**.

### Key balance sheet items identified

| Item | 2023 | 2024 | Description |
|---|---|---|---|
| Debiteuren | 0 | 5,963.56 | Open: factuur 2024-034 (Klant2) |
| Nog te factureren | 8,996.66 | 1,427.52 | NTF: factuur 22470-25-16 (HAP MiddenLand) |
| Nog te ontvangen | 411.62 | 303.80 | Prepaid costs (unclear) |
| Crediteuren | 606.19 | 2,919.00 | 2024: unpaid MacBook Pro |
| Bank | 15.12 | 617.77 | Zakelijke rekening NL74RABO |

### Fixed Assets & Depreciation

| Asset | Purchase | Cost | Residual | Life | Annual Depr | Notes |
|---|---|---|---|---|---|---|
| Medical equip (inventaris) | Dec 2023 | 1,699.00 | ~10% | 5yr? | ~306 | Disposed in 2024? |
| Camera (hardware) | Dec 11, 2023 | 2,713.70 | ~10% | 5yr | ~488 | Pro-rata 2023: 31.22 |
| New hardware | 2024 | 1,255.06 | ~10% | 5yr | ~226 | What is this? |
| MacBook Pro 16 | Dec 23, 2024 | 2,919.00 | ~10% | 5yr | ~525 | Paid Jan 2025 |

Depreciation verification needed — the Yuki amounts don't perfectly match simple linear models. The accountant may have used monthly pro-rata.

---

## 4. Fiscal Calculation Validation

### 2024: App engine PERFECTLY matches Boekhouder

The app's fiscal engine (`bereken_volledig()`) has been validated against the complete Boekhouder 2024 calculation. All 20 intermediate values match:

```
Winst: 95,145 → Fiscale winst: 94,437 → Belastbare winst: 76,776
→ Verzamelinkomen: 73,778 → IB/PVV: 29,268 → Netto IB: 27,166
→ VA: -30,303 → Terug: 3,137 → ZVW: 1,143
```

### 2023: App CANNOT fully replicate (transition year)

Test had additional 2023 income:
- SBOH (training): EUR 17,613 (loonheffing 4,738)
- UWV (benefits): EUR 11,888 (loonheffing 2,418)
- Combined voorheffing: EUR 7,156

These push the 2023 verzamelinkomen from ~44,048 (business only) to 73,549 (combined). The app only handles business income and cannot replicate this. **2023 must use Boekhouder reference values.**

### 2024 Boekhouder Complete Waterfall (reference)

```
Netto-omzet (Yuki)                       124,337
 - Pensioenpremie SPH                    -18,387
 - Opleidingskosten                          -30
 - Kilometervergoedingen                  -3,622
 - Representatiekosten                      -534
 - Accountantskosten                      -1,627
 - Telefoon/internet                        -985
 - Contributies                             -494
 - Kleine aanschaffen                       -398
 - Automatisering                            -35
 - Verzekeringen                          -2,031
 - Bankkosten                              -281
 - Betalingsverschillen                      +0
 - Prive-gebruik                            +446
 - Overige                                  -255
 = Subtotal bedrijfslasten               -28,232
 - Afschrijvingen                           -960
 = WINST VOLGENS JAARREKENING             95,145

 + Niet-aftrekbare repr (20% × 534)        +110
 - KIA (28% × MacBook 2,919)               -818
 = FISCALE WINST                          94,437

 - Zelfstandigenaftrek                    -3,750
 - Startersaftrek                         -2,123
 = Winst voor MKB                         88,564
 - MKB-winstvrijstelling (13.31%)        -11,788
 = BELASTBARE WINST                       76,776

 - AOV premie (inkomensvoorziening)       -2,998
 + EW saldo (naar partner → 0)                0
 = VERZAMELINKOMEN                        73,778

IB schijf 1: 9.32% × 38,098              3,550
IB schijf 2: 36.97% × 35,680            13,190
 + Tariefsaanpassing                      1,994
 = IB                                    18,734
PVV: 27.65% × 38,098                    10,534
 = Bruto IB/PVV                          29,268
 - AHK                                     -116
 - Arbeidskorting (op fiscale winst!)     -1,986
 = NETTO IB/PVV                          27,166
 - Voorlopige aanslag                    -30,303
 = IB TERUG                               3,137

ZVW: 5.32% × min(76,776; 71,628)         3,810
 - VA ZVW                                -2,667
 = ZVW BIJBETALING                        1,143
```

---

## 5. Personal Financial Data (Updated in DB)

The following data was extracted from Boekhouder reports and entered into `fiscale_params`:

| Parameter | 2023 | 2024 | 2025 | Source |
|---|---|---|---|---|
| AOV premie | 1,753 | 2,998 | TBD | Boekhouder aangifte |
| WOZ-waarde | 619,000 | 655,000 | 733,000 | WOZ taxatieverslag |
| Hypotheekrente | 7,140 | 6,951 | 7,282 | AEGON jaaroverzicht |
| EW naar partner | True | True | True | Boekhouder practice |
| VA IB | 19,893 | 30,303 | 29,851 | Belastingdienst |
| VA ZVW | 2,468 | 2,667 | 2,859 | Belastingdienst |
| Partner loon | — | 39,965 | 44,094 | Jaaropgave Nijholt |
| Partner loonheffing | — | 6,878 | 8,204 | Jaaropgave Nijholt |
| Box 3 bank | 26,162 | 27,836 | 22,471 | Bank jaaroverzichten |
| Box 3 schulden | 43,106 | 37,853 | 35,963 | DUO + creditcard |
| Balans bank | 15.12 | 617.77 | 3,830.88 | Zakelijke rekening |
| Balans crediteuren | 606.19 | 2,919.00 | TBD | Yuki/fiscal balans |

### Box 3 Detail (all included in bank saldo)

**Bankrekeningen (privé, children included):**
- NL19 RABO (gezamenlijk met partner)
- NL28 RABO (Julian, kind)
- NL55 RABO (betaalrekening)
- NL98 RABO (Jorik, kind)
- NL70 RABO (spaar, gezamenlijk)
- NL34 RABO (spaar)
- NL91 RABO (betaalrekening)

**Schulden:**
- DUO studieschuld: 2023=39,219 | 2024=37,411 | 2025=32,962
- Rabo GoldCard Visa: 2023=3,887 | 2024=442 | 2025=3,000
- Drempel schulden (per persoon, doubled for partners): 2023=3,400 | 2024=3,700 | 2025=3,700

### Eigen Woning Detail

| Parameter | 2023 | 2024 | 2025 |
|---|---|---|---|
| WOZ-waarde | 619,000 | 655,000 | 733,000 |
| EW forfait (0.35%) | 2,166 | 2,292 | 2,566 |
| Hypotheekrente | 7,140 | 6,951 | 7,282 |
| EW saldo (negatief) | -4,974 | -4,659 | -4,716 |
| Naar partner | Ja | Ja | Ja |
| Hypotheekschuld eoy | 379,648 | 367,856 | 354,831 |

### Hypotheek Detail (AEGON, 4 leningdelen)

| Leningdeel | Type | Einde 2024 | Rente 2024 |
|---|---|---|---|
| H1214133L1 | Annuiteit | 189,739 | 3,359 |
| H1214133L2 | Annuiteit | 98,065 | 1,742 |
| H1361908L1 | Annuiteit | 64,092 | 1,534 |
| H1361908L2 | Annuiteit | 15,960 | 316 |
| **Totaal** | | **367,856** | **6,951** |

---

## 6. Gap Analysis: What's Needed to Replace Accountant

### COMPLETED (already in app)
- [x] Revenue tracking (163 facturen, 602 werkdagen, cent-for-cent verified)
- [x] Fiscal engine (validated against Boekhouder 2024, all intermediate values match)
- [x] Aangifte invulhulp (BD portal mirror with copy-to-clipboard)
- [x] Personal financial data in DB (WOZ, hypotheek, AOV, VA, Box 3, partner)
- [x] Jaarafsluiting page structure (5-tab: Balans, W&V, Toelichting, Controles, Document)
- [x] ZA/SA toggles (per-year, DB-driven)

### CRITICAL MISSING (blocks accountant replacement)
- [ ] **Expense import** — 458 PDFs, 0 imported. Without expenses, winst calculation is wrong.
  - 2023: 54 PDFs
  - 2024: 83 PDFs
  - 2025: 95 PDFs
  - 2026: 4 PDFs (partial year)
- [ ] **Asset register & depreciation** — No tracked assets. Need:
  - Camera (2023, 2,713.70, hardware)
  - Medical equipment (2023, 1,699.00, inventaris)
  - New hardware (2024, 1,255.06, hardware)
  - MacBook Pro 16 (2024, 2,919.00, inventaris)
  - 2025 investments: iPhone, NAS, network, dermatoscope (4 files in archive)
- [ ] **Kilometervergoeding calculation** — Data exists in werkdagen (km per day), but no automatic aggregation to annual total for W&V/fiscal
- [ ] **Balance sheet opening balances** — Need 2024 closing = 2025 opening set from Boekhouder fiscal data:
  - Vaste activa: 5,896
  - Vorderingen: 7,695
  - Liquide middelen: 618
  - Eigen vermogen: 11,264
  - Kortlopende schulden: 2,945

### NICE TO HAVE (improves accuracy/automation)
- [ ] Bank transaction import (CSV available for 2024)
- [ ] Auto-matching bank transactions to facturen/uitgaven
- [ ] Bankkosten auto-extraction from bank statements
- [ ] Betalingsverschillen auto-calculation
- [ ] Prive-gebruik correctie (phone/internet private use %)
- [ ] 2023 historical reference mode (read-only, Boekhouder numbers)
- [ ] Fiscal advisory panel (ZA trajectory, SA tracking, belastingdruk)

### NOT NEEDED (YAGNI)
- 2023 full replication (transition year with SBOH/UWV income)
- BTW administration (vrijgesteld)
- Loon/dienstverband tracking
- Multi-year NTF reconciliation engine

---

## 7. Recommended Implementation Priority

### Phase 1: Expense Import (CRITICAL)
Import all 458 expense PDFs through the existing import dialog on /kosten.
Cross-check totals against Yuki W&V for 2023 and 2024.
Categories map: Pensioenpremie → SPH, not AOV.

### Phase 2: Asset Register
Track investments with depreciation schedules.
Seed 2023-2024 assets from Yuki data.
Calculate KIA automatically from investment totals.

### Phase 3: Balance Sheet Seeding
Set 2024 closing = 2025 opening balances from Boekhouder fiscal report.
Enable jaarafsluiting workflow for 2025.

### Phase 4: Kilometervergoeding Automation
Aggregate werkdagen km × EUR 0.23/km per year.
Include in W&V and fiscal calculations automatically.

### Phase 5: Bank Import & Reconciliation
Import 2024 bank CSV, auto-categorize transactions.
Enable bankkosten and betalingsverschillen extraction.

---

## 8. Key Decisions / Conventions

1. **Revenue attribution**: Work-date based (last werkdag date). Differs from Yuki accrual by EUR 540-3,208/year. Acceptable for fiscal purposes since the differences net out over years.

2. **Expense categorization**: Follow Yuki account structure (40150 Pensioenen, 42500 Km, 44400 Repr, etc). AOV is NOT an expense — it's in fiscale_params.

3. **2023 baseline**: Use Boekhouder fiscal balance sheet as authoritative opening balance for continuity. Don't try to replicate 2023 tax calculation in-app.

4. **EW naar partner**: Default True (Boekhouder practice). Partner (Nijholt) claims the eigen woning saldo.

5. **Fiscal vs Yuki revenue**: For 2024, they match. For 2025+, app's work-date revenue IS fiscal revenue (no accountant adjustment needed). Minor NTF differences are acceptable for a ZZP huisarts.
