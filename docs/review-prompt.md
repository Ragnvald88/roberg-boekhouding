# Review Prompt: Boekhouding App voor Huisartswaarnemer

## Context

I'm building a standalone bookkeeping application (NiceGUI + Python + SQLite) for a Dutch solo GP locum (huisartswaarnemer, eenmanszaak). The app replaces Moneybird + an Excel-based Urenregister. It runs locally on macOS in the browser.

The app has 7 pages (dashboard, werkdagen/hours, facturen/invoices, kosten/expenses, bank CSV import, jaarafsluiting/year-end fiscal, instellingen/settings), a fiscal calculation engine validated against accountant reference figures, and a WeasyPrint PDF invoice generator.

## Current State

The app's UI and page logic works. 82 tests pass. The fiscal engine produces correct results validated against Boekhouder accountant figures for 2023 and 2024.

**However, the historical data import is broken:**

### Problem 1: Invoice Import (118 facturen, ALL broken)
The import only parses PDF filenames — it does NOT read PDF content. All 118 invoices have:
- `totaal_bedrag = 0` (should be real amounts from €500-€6000 each)
- `datum = YYYY-01-01` (should be the actual invoice date)
- `totaal_uren = NULL`, `totaal_km = NULL`
- Many assigned to wrong klant (2023 filenames have no klant name, so fallback is random)

The source data is an Excel Urenregister.xlsm with 587 workday rows containing: datum, klant, code, uren, tarief, km, km_tarief, factuurnummer, status. The workdays (werkdagen) are the ground truth — each invoice is derived from a set of workdays for one klant.

### Problem 2: Workday Data Quality (593 werkdagen, partially broken)
- **177 werkdagen have tarief=0** despite having real hours (openpyxl read formula cells as None/0)
- **27+ werkdagen have DD-MM-YYYY date format** instead of YYYY-MM-DD
- Only 45 of 593 have a factuurnummer set; 437 are status="betaald" but unlinked
- Revenue from correct werkdagen: €81K (2023), €124K (2024), €35K (2025), €17K (2026)

### Problem 3: Zero Expenses Imported
228+ expense PDFs exist (organized by category: Pensioenpremie, KPN, Verzekeringen, Accountancy, Investeringen, Representatie, Lidmaatschappen, Scholingskosten, Bankkosten) but none were imported. The app has a manual expense entry form but no batch import capability.

### Problem 4: Investment/Depreciation Data Missing
Known investments from PDF files:
- 2023: Camera (cameranu), some other items
- 2024: MacBook Pro (€2,919)
- 2025: iPhone 17 Pro Max, NAS Synology DS1525+, Ubiquiti U7 Pro XGS, Dermatoscoop

These need proper depreciation (lineair, 10% restwaarde, first year pro-rata by month) and KIA calculation.

## Domain Rules (Dutch Fiscal)

- **BTW-vrijgesteld** (art. 11 lid 1 sub g Wet OB) — all costs booked INCLUDING VAT, no VAT administration needed
- **Urencriterium**: 1,225 hours/year minimum for entrepreneur deductions. "Achterwacht" (on-call standby) does NOT count
- **AOV insurance**: NOT a business cost — it's a Box 1 personal income provision (reduces verzamelinkomen, not business profit)
- **Km-vergoeding**: €0.21/km (2023), €0.23/km (2024-2026)
- **KIA (Kleinschaligheidsinvesteringsaftrek)**: 28% × total investments when total is €2,901-€70,602/year. Items <€450 are expensed directly, not via depreciation
- **Afschrijvingen**: Linear, 10% residual value, first year pro-rata per month (December purchase = 1/12 of annual)
- **Representatie**: 80% deductible rule (20% non-deductible, added back as "bijtelling" in fiscal profit calculation)
- **Fiscal waterfall**: Winst → +repr bijtelling → -KIA → fiscale winst → -zelfstandigenaftrek → -startersaftrek → na ondernemersaftrek → -MKB-winstvrijstelling → belastbare winst → +eigenwoningforfait → -hypotheekrente → -AOV → verzamelinkomen → IB schijventarief → -AHK → -arbeidskorting → netto IB → +ZVW → -voorlopige aanslag → resultaat

## Invoice Types

Two distinct income streams:
1. **Dagpraktijk** (120 invoices): Self-generated invoices to GP practices. Each covers 1-9 workdays for one klant. Contains: date per workday, hours, tarief/hr, km, km-tarief. Numbered YYYY-NNN.
2. **ANW Diensten** (40 invoices): Received from HAP organizations (Doktersdienst Drenthe, HAP NoordOost). Evening/night/weekend shifts. Have their own numbering systems (22470-23-01, 232137, etc.). Different tariffs per dienst type.

## Specific Questions

### 1. Re-importing facturen from werkdagen
The werkdagen table has the real data (uren, tarief, km). The Urenregister Excel has a factuurnummer column (column S) for some rows. What's the best strategy to:
- Fix the 177 werkdagen with tarief=0 (re-read from Excel with `data_only=False` and evaluate formulas, or look up tarief from the klant master data?)
- Fix the 27 DD-MM-YYYY dates
- Rebuild facturen by grouping werkdagen per factuurnummer (where known) and per klant+month (where unknown)
- Handle ANW diensten which have external numbering systems

### 2. Expense import strategy
228 expense PDFs in categorized folders. The amounts ARE in the PDFs but parsing PDF text is fragile. Alternatives:
- Manual entry (tedious but accurate)
- Build a script that reads known patterns from filenames + folder structure to create skeleton entries, then manually verify amounts
- Use the bank CSV (Rabobank) as the source of truth for amounts (each expense was paid from the bank, so the bank CSV has the amounts)
- Something else?

Which approach would you recommend for a one-time migration?

### 3. Investment depreciation completeness
The depreciation engine handles:
- Linear depreciation with residual value
- First-year pro-rata
- KIA (28% investment deduction)

But it does NOT handle:
- `zakelijk_pct` (partial business use %) — the field is stored in the DB but never applied to the depreciation base
- Desinvestering (selling an asset before end of useful life)
- Willekeurig afschrijven (not relevant here)

Is `zakelijk_pct` important for a huisartswaarnemer? (Most assets are 100% business use since there's a separate personal phone/laptop usually.) Should I implement it or is it YAGNI?

### 4. ANW Diensten handling
ANW shifts are income received from HAP organizations with their own invoice numbers (not YYYY-NNN). Currently the app tries to import these PDFs as if they were self-generated invoices. Should these be:
- Imported as separate "type=anw" facturen with their own numbering?
- Treated as regular werkdagen with the HAP as klant, and facturen only for self-generated invoices?
- Something else?

The Urenregister already tracks these as werkdagen with codes like `ANW_DR_WERKDAG_NACHT`, `ANW_GR_WEEKEND_DAG`, etc.

### 5. Revenue calculation: facturen vs werkdagen
Currently the dashboard's "Netto-omzet" KPI queries werkdagen (SUM of uren*tarief + km*km_tarief). But shouldn't revenue be based on facturen (what was actually invoiced/billed)? What's the correct accounting approach for:
- Revenue recognition: when work is done (werkdagen) or when invoice is sent (facturen)?
- Handling discrepancies (e.g., a werkdag that was worked but never invoiced)

### 6. Bank reconciliation
The bank page lets you import Rabobank CSV and manually categorize transactions. But there's no linking to facturen or uitgaven. For a clean boekhouding:
- Is manual categorization sufficient?
- Should I implement linking (match bank transactions to specific facturen/uitgaven)?
- Or is that overengineering for a single-user app where the accountant does the final reconciliation?

### 7. What am I missing?
Given this is a eenmanszaak huisartswaarnemer in the Netherlands:
- Are there any fiscal rules or requirements I've overlooked?
- Any common bookkeeping mistakes for ZZP-ers in healthcare?
- Any Dutch-specific reporting requirements (beyond IB-aangifte) that this app should support?
- For the jaarafsluiting: is my fiscal waterfall complete? Am I missing any deductions or additions?
- Eigenwoningforfait: currently hardcoded at 0.35% of WOZ. Should this be year-dependent or WOZ-bracket dependent?

## What I'm NOT Looking For
- UI/UX advice (that's handled)
- Code review (done separately)
- Testing strategy (82 tests, all passing)
- General architecture advice (app structure is final)

I specifically want advice on the **data/domain/fiscal correctness** aspects listed above.
