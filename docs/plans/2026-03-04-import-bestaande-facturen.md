# Import Bestaande Facturen — Design & Instructions

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Import all existing invoice PDFs (2023-2025) from the source directory into the boekhouding app, linking them to the correct klanten and werkdagen.

**Source directory:** `~/Library/CloudStorage/SynologyDrive-Main/02_Financieel/Boekhouding_Waarneming/`

---

## 1. Source Data Inventory

### Dagpraktijk Facturen (self-created invoices)

| Year | Count | Location | Naming Pattern | Example |
|------|-------|----------|----------------|---------|
| 2023 | 20 | `2023/Inkomsten/Dagpraktijk/` | `2023-NNNNN.pdf` then `2023-NNN.pdf` | `2023-00001.pdf`, `2023-016.pdf` |
| 2024 | 42 | `2024/Inkomsten/Dagpraktijk/` | `2024-NNN_Klantnaam.pdf` | `2024-001_Winsum.pdf`, `2024-006_Klant6.pdf` |
| 2025 | 47 | `2025/Inkomsten/Dagpraktijk/` | `2025-NNN_Klantnaam.pdf` | `2025-001_Klant7.pdf` |

**Invoice format changed 3 times:**
- **2023 early**: "RH Waarneming" header, 5-digit numbers, EUR 70/hr, EUR 0.21/km, 21-day payment
- **2024**: "TestBV huisartswaarnemer" header, 3-digit numbers, EUR 70-80/hr, EUR 0.23/km, 14-day payment
- **2025**: "TestBV Huisartswaarnemer" large header, simplified layout, EUR 77.50-80/hr, EUR 0.23/km

**Data extractable from dagpraktijk PDFs:**
- Factuurnummer (from filename AND PDF content)
- Klant naam + adres (from "Factuuradres" section)
- Factuurdatum + vervaldatum
- Per werkdag: datum, uren, tarief, km, km-tarief
- Totaal bedrag

### ANW Diensten Facturen (self-billing from HAP organizations)

| Year | Count | Location | Naming Pattern | Example |
|------|-------|----------|----------------|---------|
| 2023 | 6 | `2023/Inkomsten/ANW_Diensten/` | `YYYY-MM_Organization.pdf` | `2023-09_DokterDrenthe.pdf` |
| 2024 | 14 | `2024/Inkomsten/ANW_Diensten/` | `Organization_MM-YY.pdf` | `Drenthe_02-24.pdf` |
| 2025 | 17 | `2025/Inkomsten/ANW_Diensten/` | `MMYY_HAP_Organization.pdf` | `0225_HAP_Drenthe.pdf` |

**ANW invoices are fundamentally different:**
- Created BY the HAP organization, not by you
- Self-billing format ("Factuur uitgereikt door afnemer")
- Have dienst IDs, start/end times, tariff categories (Avond/Nacht/Weekend)
- No km reimbursement
- Different numbering: `22470-YY-NN` (Drenthe), system numbers (DDG)
- Location encoded in dienst code suffix: `-A` = Assen, `-E` = Emmen

---

## 2. Existing Data in the App

### Urenregister Import Status
The Urenregister.xlsm has already been partially imported (`import_/run_full_import.py`), but with known issues:
- **177 werkdagen have tarief=0** (wrong)
- **27+ werkdagen have DD-MM-YYYY dates** (wrong format, breaks year filters)
- **0 uitgaven imported**
- **Facturen have totaal_bedrag=0** (wrong)
- **Klanten and fiscale_params are correct**

### Current `facturen` table schema
```sql
CREATE TABLE IF NOT EXISTS facturen (
    id INTEGER PRIMARY KEY,
    nummer TEXT NOT NULL UNIQUE,
    klant_id INTEGER NOT NULL REFERENCES klanten(id),
    datum TEXT NOT NULL,
    totaal_uren REAL,
    totaal_km REAL,
    totaal_bedrag REAL NOT NULL CHECK (totaal_bedrag >= 0),
    pdf_pad TEXT DEFAULT '',
    betaald INTEGER DEFAULT 0 CHECK (betaald IN (0, 1)),
    betaald_datum TEXT DEFAULT '',
    type TEXT DEFAULT 'factuur'
);
```

The `type` field can distinguish between `'factuur'` (dagpraktijk, self-issued) and potentially `'creditnota'` or `'anw'` (HAP self-billing).

---

## 3. Import Strategy

### Phase A: Fix Existing Werkdagen Data
Before importing invoices, fix the known data quality issues:

1. **Fix DD-MM-YYYY dates** → Convert to YYYY-MM-DD format
2. **Fix tarief=0 werkdagen** → Look up correct tarief from Urenregister column N or klant.tarief_uur
3. **Fix totaal_bedrag=0 facturen** → Recalculate from linked werkdagen

### Phase B: Import Dagpraktijk Facturen (Priority)
For each PDF in `{year}/Inkomsten/Dagpraktijk/`:

1. **Extract factuurnummer from filename** (e.g., `2024-001` from `2024-001_Winsum.pdf`)
2. **Check if factuur already exists** in DB by nummer (skip if exists)
3. **Match klant** by name suffix in filename (e.g., `_Winsum` → Praktijk K14) or from the Urenregister Facturatie sheet
4. **Extract totaal_bedrag** — either parse the PDF or calculate from linked werkdagen in the Urenregister
5. **Create factuur record** with:
   - `nummer` from filename
   - `klant_id` matched by name
   - `datum` from Urenregister Facturatie sheet or PDF
   - `totaal_bedrag` calculated from werkdagen
   - `pdf_pad` = copy PDF to `data/facturen/{nummer}.pdf`
   - `betaald = 1` (all historical invoices are paid)
   - `type = 'factuur'`
6. **Link werkdagen** — update `werkdagen.factuurnummer` and `werkdagen.status = 'gefactureerd'` for matching werkdagen

### Phase C: Import ANW Facturen (Lower priority)
For each PDF in `{year}/Inkomsten/ANW_Diensten/`:

1. **Create factuur record** with `type = 'anw'`
2. **Copy PDF** to `data/facturen/anw/`
3. **Link to werkdagen** by matching dates and klant (HAP MiddenLand or DDG)
4. ANW invoices may need a different display treatment (they're income from the HAP, not invoices you sent)

### Phase D: Copy Invoice PDFs to App Data Directory
All imported PDFs should be COPIED (not moved) to `data/facturen/` so the app has its own copies. The source directory remains untouched as the master archive.

---

## 4. Klant Name Mapping

From the Urenregister and existing DB, the filename suffixes map to klanten:

| Filename suffix | Klant naam in DB |
|----------------|------------------|
| `Winsum` | Praktijk K14 |
| `Klant2` | Praktijk K2 |
| `Klant6` | Praktijk K6 |
| `Klant7` | K. Klant7 |
| `Klant9` | Praktijk K9 |
| `Klant10` | Praktijk K10 |
| `Klant4` | Klant4 |
| `Klant5` | (needs mapping — may not exist yet) |
| `Klant11` | Praktijk K11 |
| `Klant13` | Praktijk K13 |
| `Klant12` | Praktijk K12 |
| `Marum` | (ambiguous — multiple klanten in Marum) |
| `Vlagtwedde` | Praktijk K2 |
| `Klant8` | Klant8 |
| `DokterDrenthe` / `Drenthe` | HAP MiddenLand |
| `DDG` / `Groningen` | HAP NoordOost |

**Note:** 2023 filenames lack the klant suffix (just `2023-00001.pdf`). For these, we must match by factuurnummer from the Urenregister's Facturatie sheet or by cross-referencing werkdag dates.

---

## 5. Urenregister Cross-Reference

The Urenregister has two key sheets for matching:

### Urentabel (745 rows)
- Column T: `Factuurnummer` — links werkdagen to invoices
- Column F: `Datum` — workday date
- Column H: `Klant` — client name
- Column K: `Uren` — hours worked
- Column M: `Retourafstand woon/werk km` — round-trip km
- Column R: `Totaalbedrag` — total per workday (uren * tarief + km * km_tarief)

### Facturatie sheet
- Klant, Factuurdatum, Factuurnummer, Factuurbedrag, Factuurstatus
- Only partially filled (first ~31 rows for 2024)

**Import algorithm:**
1. For each unique factuurnummer in the Urentabel:
   - Sum `Totaalbedrag` (column R) for all rows with that factuurnummer → `totaal_bedrag`
   - Get the klant name from the first matching row → look up `klant_id`
   - Get the min datum from matching rows → use as approximate `datum`
   - Match to PDF file by factuurnummer pattern
2. Create the factuur record
3. Update all matching werkdagen with the factuurnummer and status

---

## 6. Implementation Approach

### Option A: Script-based Import (Recommended)
Create `import_/import_facturen.py` that:
1. Reads the Urenregister for factuurnummer ↔ werkdag mappings
2. Scans the source PDF directories
3. Matches PDFs to factuurnummers
4. Copies PDFs to `data/facturen/`
5. Creates factuur records
6. Links werkdagen to facturen

**Advantages:** Deterministic, repeatable, can be run multiple times safely (idempotent with UNIQUE nummer check).

### Option B: UI-based Import
Add an "Import historische facturen" button on the Facturen page with a file picker for the source directory.

**Advantages:** More user-friendly. **Disadvantages:** More UI work, harder to debug mismatches.

### Recommendation: Option A first, then optionally add a simple UI trigger that calls the script.

---

## 7. Data Quality Fixes (Pre-requisite)

Before importing facturen, fix these in a separate migration/script:

### Fix 1: DD-MM-YYYY dates in werkdagen
```sql
-- Identify affected rows
SELECT id, datum FROM werkdagen WHERE datum LIKE '__-__-____';

-- Fix: swap DD-MM-YYYY to YYYY-MM-DD
UPDATE werkdagen
SET datum = substr(datum, 7, 4) || '-' || substr(datum, 4, 2) || '-' || substr(datum, 1, 2)
WHERE datum LIKE '__-__-____';
```

### Fix 2: tarief=0 werkdagen
Cross-reference with Urenregister column N (Uurtarief) to fill in correct tarieven. If not available, use `klant.tarief_uur` as fallback.

### Fix 3: Recalculate factuur totaal_bedrag
```sql
UPDATE facturen SET totaal_bedrag = (
    SELECT COALESCE(SUM(uren * tarief + km * km_tarief), 0)
    FROM werkdagen WHERE factuurnummer = facturen.nummer
) WHERE totaal_bedrag = 0;
```

---

## 8. Files to Create/Modify

| File | Action |
|------|--------|
| `import_/import_facturen.py` (new) | Main import script |
| `import_/fix_data_quality.py` (new) | Data quality fixes (dates, tarieven, totals) |
| `database.py` | May need `get_factuur_by_nummer()` helper |
| `main.py` | Add `data/facturen` directory creation on startup |

---

## 9. Success Criteria

- [ ] All DD-MM-YYYY dates fixed to YYYY-MM-DD
- [ ] All tarief=0 werkdagen have correct tarieven
- [ ] All factuur totaal_bedrag > 0
- [ ] All dagpraktijk PDFs (2023-2025) imported and linked
- [ ] All ANW PDFs imported with type='anw'
- [ ] PDFs copied to `data/facturen/` (source untouched)
- [ ] Werkdagen linked to facturen (status='gefactureerd', factuurnummer set)
- [ ] Import is idempotent (running again doesn't create duplicates)
- [ ] Dashboard shows correct revenue figures after import
- [ ] Facturen page shows all historical invoices with PDF download links
