# TestBV Boekhouding App

## Wat we bouwen
Standalone boekhoudapplicatie (NiceGUI + Python) voor TestBV huisartswaarnemer (eenmanszaak, KvK 00000000). Vervangt Moneybird + Urenregister.xlsm. Draait lokaal op macOS, opent in browser.

## Tech Stack
| Component | Technologie | Versie |
|-----------|------------|--------|
| UI framework | NiceGUI | >=3.0 |
| Database | SQLite via aiosqlite | raw SQL, GEEN ORM |
| Charts | ECharts (via `ui.echart`) | ingebouwd in NiceGUI |
| Factuur-PDF | WeasyPrint + Jinja2 HTML templates | `brew install weasyprint` |
| Excel lezen | openpyxl | alleen voor data-migratie |
| HTTP client | httpx | toekomstige API-integraties |

## Starten
```bash
pip install -r requirements.txt
python main.py
# → opent http://localhost:8085 in browser
```

## Architectuur
```
Browser (localhost:8085)
    ↕
NiceGUI (Python, browser mode — NIET native/pywebview)
    ↕
SQLite (data/boekhouding.sqlite3) + PDFs (data/facturen/, data/uitgaven/)
```

## Projectstructuur
```
roberg-boekhouding/
├── main.py                     # Entrypoint: ui.run(), startup, page imports
├── database.py                 # SQLite connectie, schema, alle queries
├── models.py                   # Dataclasses (geen ORM)
├── pages/
│   ├── dashboard.py            # KPIs + ECharts grafieken
│   ├── werkdagen.py            # Uren/km registratie + add/edit
│   ├── facturen.py             # Factuur aanmaken + betaalstatus
│   ├── kosten.py               # Uitgaven + categorisatie
│   ├── bank.py                 # Rabobank CSV import + koppelen
│   └── jaarafsluiting.py       # Fiscale berekeningen + rapporten
├── components/
│   ├── layout.py               # Sidebar navigatie, page header
│   ├── werkdag_form.py         # Herbruikbaar werkdag formulier
│   ├── charts.py               # ECharts bouwers (omzet, kosten)
│   └── invoice_generator.py    # WeasyPrint PDF factuur generator
├── fiscal/
│   ├── berekeningen.py         # W&V, fiscale waterval, IB-berekening
│   ├── afschrijvingen.py       # Activastaat, pro-rata, boekwaarde
│   └── heffingskortingen.py    # AHK, arbeidskorting tabellen
├── import_/                    # Underscore: vermijd conflict met Python import
│   ├── urenregister.py         # Eenmalige xlsm → SQLite migratie
│   ├── rabobank_csv.py         # Bank CSV parser
│   └── seed_data.py            # Klanten + fiscale params pre-fill
├── templates/
│   └── factuur.html            # Jinja2 HTML template voor WeasyPrint
├── tests/
│   ├── test_database.py
│   ├── test_fiscal.py          # Gevalideerd tegen Boekhouder referentiecijfers
│   ├── test_kosten.py
│   └── test_bank_import.py
├── data/                       # Persistent data (NIET in git)
│   ├── boekhouding.sqlite3
│   ├── facturen/               # Gegenereerde factuur-PDFs
│   ├── uitgaven/               # Geüploade bonnen/facturen
│   └── bank_csv/               # Gearchiveerde CSV-imports (bewaarplicht)
├── start-boekhouding.command   # Dubbelklik om te starten
└── requirements.txt
```

## Database Schema (6 tabellen)
Zie `docs/plans/2026-02-23-roberg-boekhouding-app-design.md` voor volledig SQL schema.

Tabellen: `klanten`, `werkdagen`, `facturen`, `uitgaven`, `banktransacties`, `fiscale_params`

**Regels:**
- Raw SQL met parameterized queries (`?` placeholders), GEEN f-strings in SQL
- Alle bedragen als REAL (Python float), NIET integer centen
- Datums als TEXT in ISO formaat (YYYY-MM-DD)
- `aiosqlite` voor async toegang

## Pagina's (6 + Instellingen)
| Route | Pagina | Kernfunctie |
|-------|--------|-------------|
| `/` | Dashboard | 4 KPI-kaarten, omzet bar chart (ECharts), kosten donut |
| `/werkdagen` | Werkdagen | Tabel + formulier: datum, klant (auto-fill tarief+km), uren |
| `/facturen` | Facturen | Selecteer werkdagen → genereer PDF factuur (WeasyPrint) |
| `/kosten` | Kosten | Uitgaven toevoegen, categoriseren, investering-vlag ≥€450 |
| `/bank` | Bank | Rabobank CSV import, handmatig categoriseren |
| `/jaarafsluiting` | Jaarafsluiting | W&V + balans + fiscale waterval + IB-schatting |

## Domeinkennis (essentieel voor correcte implementatie)

### Klanten
| Klant | Tarief/uur | km retour | Status |
|-------|-----------|-----------|--------|
| HAP K6 (Marum) | €77,50 | 52 | Actief |
| K. Klant7 (Marum) | €77,50 | 52 | Actief |
| HAP K14 | €80,00 | 44 | Actief |
| Klant2 (Vlagtwedde) | €70,00 | 108 | Inactief (eind 2025) |
| K. Klant15 (Nieuw-Weerdinge) | €98,44 | 0 | Actief 2026+ |

### Kostencategorieën
```
Pensioenpremie SPH        100% aftrekbaar (bedrijfskosten)
Telefoon/KPN              zakelijk deel documenteren
Verzekeringen             100% (excl. AOV → die is Box 1)
Accountancy/software      100%
Representatie             80% aftrekbaar (20% NIET aftrekbaar → fiscale bijtelling)
Lidmaatschappen           100%
Kleine aankopen (<€450)   100% direct ten laste
Scholingskosten           100%
Bankkosten                100%
Investeringen (≥€450)     via afschrijving + KIA (NIET direct ten laste)
```

### Fiscale kernregels
- **BTW-vrijgesteld** (art. 11 lid 1 sub g Wet OB) → kosten INCL. BTW boeken, geen BTW-aangifte
- **Urencriterium**: 1.225 uur/jaar. Achterwacht (urennorm=0) telt NIET mee
- **AOV (Allianz)**: GEEN bedrijfskosten → apart als Box 1 inkomensvoorziening
- **Km-vergoeding**: €0,21/km (2023), €0,23/km (2024+2025+2026)
- **KIA**: 28% × investeringen als totaal €2.901-€70.602/jaar. Items <€450: direct ten laste
- **Afschrijvingen**: lineair, restwaarde 10%, eerste jaar pro-rata per maand
- **Representatie**: 80%-regeling (actieve keuze in IB-aangifte)

### Fiscale parameters per jaar (seed in fiscale_params tabel)
| Jaar | Zelfst.aftrek | Startersaftrek | MKB% | Schijf 1 | Schijf 2 | Schijf 3 |
|------|-------------:|---------------:|-----:|----------|----------|----------|
| 2023 | €5.030 | €2.123 | 14,00% | 36,93% (≤€73.031) | — | 49,50% |
| 2024 | €3.750 | €2.123 | 13,31% | 36,97% (≤€75.518) | — | 49,50% |
| 2025 | €2.470 | €2.123 (3e, LAATSTE) | 12,70% | 35,82% (≤€38.441) | 37,48% (≤€76.817) | 49,50% |
| 2026 | €1.200 | n.v.t. | 12,70% | 35,75% (≤€38.883) | 37,56% (≤€78.426) | 49,50% |

### Boekhouder referentiecijfers (tests moeten hiertegen valideren)
- **2023**: winst €62.522 → belastbare winst €45.801 → IB terug €415
- **2024**: winst €95.145 → belastbare winst €76.776 → IB terug €3.137

### Factuur vereisten (wettelijk)
Elke factuur MOET bevatten:
- Naam + adres verkoper (TestBV) + KvK
- Naam + adres klant
- Factuurnummer (doorlopend, geen gaten, format YYYY-NNN)
- Factuurdatum + vervaldatum (14 dagen)
- Omschrijving diensten + datum levering
- Bedrag
- **"BTW vrijgesteld op grond van artikel 11, lid 1, sub g, Wet op de omzetbelasting 1968"**
- IBAN + betaalinformatie

## Ontwikkelregels

### Architectuur
- **Browser mode ALTIJD**: `ui.run(host='127.0.0.1', port=8085)` — NOOIT native/pywebview (macOS bugs)
- **Geen ORM**: raw SQL met `aiosqlite`, parameterized queries
- **Geen Docker**: draait native op macOS met `python main.py`
- **Data in `data/` map**: SQLite + PDFs. Map staat in `.gitignore`

### YAGNI (niet bouwen)
- Geen user auth (1 gebruiker, localhost)
- Geen BTW-administratie (BTW-vrijgesteld)
- Geen loon/voorraad
- Geen email-integratie (download PDF, mail zelf)
- Geen real-time bank-API (CSV import)
- Geen auto-matching engine (handmatig categoriseren)
- Geen CI/CD
- Geen multi-language (alleen Nederlands)

### Code stijl
- Python 3.12+, type hints op functies
- Async functies voor database operaties
- NiceGUI componenten: `ui.table` voor tabellen (NIET AG Grid), `ui.echart` voor charts
- Shared layout via `components/layout.py` (sidebar + header)
- Elke pagina is een `@ui.page('/route')` in eigen bestand
- Tests met pytest + pytest-asyncio

### Factuur generatie
- WeasyPrint + Jinja2 HTML template (`templates/factuur.html`)
- NIET openpyxl voor nieuwe facturen (dat was het oude Excel-template systeem)
- openpyxl alleen voor eenmalige data-migratie uit Urenregister.xlsm

## Implementatieplan
Volledig plan met 12 taken, exacte code, en tests:
`docs/plans/2026-02-23-roberg-boekhouding-implementation.md`

Design document met schema, pagina-specs, en architectuurbeslissingen:
`docs/plans/2026-02-23-roberg-boekhouding-app-design.md`

### Taakvolorde
```
1: Scaffold + DB → 2: Layout + Nav → 3: Seed Data
    → 4: Werkdagen (kernfunctie)
    → 5: Facturen (depends on 4)
    → 6: Kosten
    → 7: Bank CSV
    → 8: Dashboard (depends on 4, 6)
    → 9: Fiscal Engine (onafhankelijk)
    → 10: Jaarafsluiting (depends on 8, 9)
    → 11: Settings
    → 12: Data Migratie
```

## Brondata (voor migratie)
De bestaande boekhouding staat in:
`~/Library/CloudStorage/SynologyDrive-Main/02_Financieel/Boekhouding_Waarneming/`
- Urenregister.xlsm: 567 datarijen (2023-2026)
- Factuur-PDFs: 160 inkomsten (120 dagpraktijk + 40 ANW) + ~228 uitgaven
- Conceptfacturen: `2026/conceptfacturen/*.xlsx` (Excel template structuur)
- Fiscale referentiedata: `.claude/skills/fiscale-berekening/SKILL.md` (in boekhouding dir)
- Jaarafsluiting procedure: `.claude/skills/jaarafsluiting/SKILL.md` (in boekhouding dir)
- Audit rapport: `Audit_Facturen_vs_Urenregister_2023-2025.md` (100% na 16 correcties)
