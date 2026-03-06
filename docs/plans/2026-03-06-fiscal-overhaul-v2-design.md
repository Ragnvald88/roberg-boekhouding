# Fiscal Overhaul v2 — Design Document

> **Date:** 2026-03-06
> **Branch:** `feature/jaarafsluiting-overhaul`
> **Status:** Design approved, ready for implementation planning

## Goal

Make every fiscal parameter DB-configurable (zero code changes for new tax years), complete the jaarafsluiting display, and transform the aangifte page into a real tax filing preparation tool with Box 1+3 summary and export.

## Context

- Fiscal engine (`berekeningen.py`) is solid — 97 tests pass, Boekhouder 2024 validated to 21 assertions
- Arbeidskorting brackets are hardcoded in Python (`heffingskortingen.py`) — requires code change per year
- PVV rates are hardcoded constants — stable but not configurable
- Jaarafsluiting page computes tariefsaanpassing, IB/PVV split, separate VA results but doesn't display them
- Aangifte page is only a document checklist — no tax summary, no Box 3, no export
- Several data discrepancies found via web verification (startersaftrek 2026, villataks per year)

## Verified Discrepancies (via Belastingdienst sources)

| Issue | Current | Correct |
|-------|---------|---------|
| Startersaftrek 2026 | `None` (treated as abolished) | **€2,123** (still active) |
| Villataks grens 2024 | €1,350,000 (2026 value) | **€1,310,000** |
| ZVW max 2024 | €71,628 | **€71,624** (minor) |
| ZVW max 2025 | €75,864 | **€75,860** (minor) |
| AHK 2024 | Needs verification | max=€3,362, drempel=€24,812, afbouw=6.63% |
| Schijf1 grens 2026 | €38,883 | €38,883 (confirmed, web €38,884 is off-by-one notation) |

## Architecture: 6 Phases

### Phase 1: Data Foundation

**Files:** `database.py`, `models.py`, `import_/seed_data.py`

#### 1.1 Fix data discrepancies

Update seed values and add migration for existing DB:
- `startersaftrek` 2026 = 2123
- `villataks_grens`: 2024=1310000, 2025=1330000, 2026=1350000
- `zvw_max_grondslag`: 2024=71624, 2025=75860
- Verify AHK 2024 values

#### 1.2 New DB columns in `fiscale_params`

```sql
-- Arbeidskorting brackets as JSON per year
arbeidskorting_brackets TEXT DEFAULT ''

-- PVV component rates
pvv_aow_pct REAL DEFAULT 17.90
pvv_anw_pct REAL DEFAULT 0.10
pvv_wlz_pct REAL DEFAULT 9.65

-- Box 3 per-year inputs (peildatum 1 jan)
box3_bank_saldo REAL DEFAULT 0
box3_overige_bezittingen REAL DEFAULT 0
box3_schulden REAL DEFAULT 0

-- Box 3 per-year fiscal parameters
box3_heffingsvrij_vermogen REAL DEFAULT 57000
box3_rendement_bank_pct REAL DEFAULT 1.03
box3_rendement_overig_pct REAL DEFAULT 6.17
box3_rendement_schuld_pct REAL DEFAULT 2.46
box3_tarief_pct REAL DEFAULT 36
```

#### 1.3 Box 3 rendement values by year

| Year | Bank | Overig | Schuld | Heffingsvrij/pp | Tarief |
|------|------|--------|--------|-----------------|--------|
| 2024 | 1.03% | 6.17% | 2.46% | €57,000 | 36% |
| 2025 | 1.28% | 6.04% | 2.47% | €57,684 | 36% |
| 2026 | 1.28% | 6.00% | 2.70% | €57,684 | 36% |

#### 1.4 Model changes (`models.py`)

Add to `FiscaleParams` dataclass:
- `arbeidskorting_brackets: str = ''`
- `pvv_aow_pct: float = 17.90`
- `pvv_anw_pct: float = 0.10`
- `pvv_wlz_pct: float = 9.65`
- Box 3 input fields (6 fields)
- Box 3 param fields (5 fields)

#### 1.5 Seed AK bracket data

Populate `arbeidskorting_brackets` for years 2023-2026 with JSON-encoded bracket tables from current Python constants.

---

### Phase 2: Engine Flexibility

**Files:** `fiscal/berekeningen.py`, `fiscal/heffingskortingen.py`, `tests/test_fiscal.py`

#### 2.1 DB-driven arbeidskorting

Modify `bereken_arbeidskorting()` signature:
```python
def bereken_arbeidskorting(arbeidsinkomen: float, jaar: int,
                            brackets_json: str = '') -> float:
```
- If `brackets_json` is non-empty, parse and use those brackets
- Else fall back to `ARBEIDSKORTING_BRACKETS[jaar]` (existing behavior)
- The Python constants remain as fallback (no data loss if DB is empty)

Update `bereken_volledig()` to pass brackets from params:
```python
ak = bereken_arbeidskorting(
    r.fiscale_winst, jaar,
    brackets_json=params.get('arbeidskorting_brackets', ''))
```

#### 2.2 DB-driven PVV rates

In `bereken_volledig()`, read PVV rates from params with fallback:
```python
pvv_aow = D(params.get('pvv_aow_pct', '17.90'))
pvv_anw = D(params.get('pvv_anw_pct', '0.10'))
pvv_wlz = D(params.get('pvv_wlz_pct', '9.65'))
```

Keep the module-level `PVV_*_PCT` constants as defaults only.

#### 2.3 Box 3 calculation

New function:
```python
@dataclass
class Box3Resultaat:
    bank_saldo: float = 0.0
    overige_bezittingen: float = 0.0
    schulden: float = 0.0
    totaal_bezittingen: float = 0.0
    rendement_bank: float = 0.0
    rendement_overig: float = 0.0
    rendement_schuld: float = 0.0
    totaal_rendement: float = 0.0
    heffingsvrij: float = 0.0
    grondslag: float = 0.0
    belasting: float = 0.0

def bereken_box3(params: dict, fiscaal_partner: bool = True) -> Box3Resultaat:
    """Calculate Box 3 forfaitair rendement."""
```

#### 2.4 Tests

- Test AK from JSON brackets matches Python constants
- Test AK with custom brackets (future year)
- Test PVV from params vs constants
- Test Box 3 calculation (with/without partner, zero values, etc.)

---

### Phase 3: Jaarafsluiting Display

**Files:** `pages/jaarafsluiting.py`, `templates/jaarafsluiting.html`

#### 3.1 Enhanced Section 6 (IB-schatting)

After "Bruto inkomstenbelasting" line, add:

```
+ Tariefsaanpassing (beperking aftrekbare posten)    € 1.994

  [Expandable: IB/PVV uitsplitsing]
    IB (excl. premies)                                € 18.542
    PVV premies volksverzekeringen                    € 10.526
      - AOW premie (17.90%)                           €  6.817
      - Anw premie (0.10%)                            €    38
      - Wlz premie (9.65%)                            €  3.671

- Algemene heffingskorting                            €    116
- Arbeidskorting                                      €  1.986
= Netto inkomstenbelasting                            € 27.166

ZVW-bijdrage (5.32% van belastbare winst)             €  4.084

--- Resultaat ---
IB resultaat:  netto IB € 27.166 - VA IB € 30.303    = -€ 3.137 (terug)
ZVW resultaat: ZVW € 4.084 - VA ZVW € 2.667          = +€ 1.417 (bij)
Totaal resultaat                                      = -€ 1.720 (terug)
```

#### 3.2 Updated PDF template

Mirror all new fields in `templates/jaarafsluiting.html`.

---

### Phase 4: Instellingen Enhancement

**Files:** `pages/instellingen.py`

#### 4.1 AK Bracket Editor

Within each year's expansion panel, add a new section "Arbeidskorting schijven":
- Editable table with 5 rows: Ondergrens | Bovengrens | Tarief % | Basisbedrag
- Pre-filled from JSON in DB (or from Python constants if DB empty)
- "Opslaan" serializes table to JSON and saves to `arbeidskorting_brackets`

#### 4.2 PVV Premies Editor

Three number fields per year:
- AOW premie % (default 17.90)
- Anw premie % (default 0.10)
- Wlz premie % (default 9.65)
- Computed total shown below (readonly)

#### 4.3 Box 3 Parameters

Per year:
- Heffingsvrij vermogen per persoon (€)
- Forfaitair rendement bank %
- Forfaitair rendement overig %
- Forfaitair rendement schuld %
- Box 3 tarief %

---

### Phase 5: Aangifte Overhaul

**Files:** `pages/aangifte.py`, new `templates/aangifte_overzicht.html`

Transform `/aangifte` into a **tabbed interface**:

#### Tab 1: Overzicht (Tax Summary)

Auto-populated by running `bereken_volledig()` with saved params + IB-inputs:

**Box 1 — Winst uit onderneming:**
- Omzet → kosten → afschrijvingen → winst
- Representatie bijtelling, KIA
- ZA, SA, MKB → belastbare winst

**Box 1 — Eigen woning:**
- WOZ, forfait, hypotheekrente, Hillen
- Saldo (or "toegerekend aan partner")

**Box 1 — Inkomensvoorziening:**
- AOV premie

**Box 1 — IB berekening:**
- Verzamelinkomen
- Tariefsaanpassing
- Bruto IB + PVV split
- Heffingskortingen
- Netto IB

**ZVW:**
- Bijdrage

**Voorlopige aanslagen:**
- IB betaald, ZVW betaald

**Resultaat:**
- IB: netto IB - VA IB
- ZVW: bijdrage - VA ZVW
- Box 3: belasting
- **Totaal: terug/bij**

Color-coded: green = teruggave, red = bijbetalen.

#### Tab 2: Box 3 (Sparen & Beleggen)

Input fields (saved to fiscale_params):
- Banktegoeden peildatum 1 jan €
- Overige bezittingen (effecten, crypto) €
- Schulden (DUO, overig) €
- Fiscaal partner checkbox

Auto-calculated results:
- Rendement per categorie
- Totaal rendement
- Heffingsvrij vermogen (×2 if partner)
- Grondslag sparen en beleggen
- Box 3 belasting

#### Tab 3: Partner

Enhanced existing section:
- Bruto loon + loonheffing
- Summary line for partner's contribution to aangifte

#### Tab 4: Documenten

Current checklist — unchanged, already works well.

#### Tab 5: Export

Button: "Exporteer aangifte-overzicht PDF"
- Comprehensive PDF with all Box 1 + Box 3 + partner data
- Professional format matching Boekhouder reference style
- Includes: all waterfall values, Box 3 berekening, document checklist status

---

### Phase 6: Docs Cleanup

#### Delete stale plan files

All completed/superseded docs in `docs/plans/`:
- `2026-02-23-roberg-boekhouding-app-design.md`
- `2026-02-23-roberg-boekhouding-implementation.md`
- `2026-03-04-aangifte-documenten-design.md`
- `2026-03-04-aangifte-documenten-plan.md`
- `2026-03-04-aangifte-verbeteringen-plan.md`
- `2026-03-04-import-bestaande-facturen.md`
- `2026-03-04-multi-locatie-design.md`
- `2026-03-04-multi-locatie-plan.md`
- `2026-03-06-jaarafsluiting-overhaul.md` (superseded by this plan)

Also delete: `docs/audit-2026-03-03.md`

#### Rewrite CLAUDE.md

- Accurate test count
- Updated fiscal domain knowledge
- Updated architecture (DB-driven params, Box 3, aangifte tabs)
- Remove completed-phase references
- Update known bugs

#### Rewrite MEMORY.md

- Remove stale task tracking
- Update to reflect new state
