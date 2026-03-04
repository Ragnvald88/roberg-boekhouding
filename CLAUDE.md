# Boekhouding App

## Wat dit is
Standalone boekhoudapplicatie (NiceGUI + Python) voor een eenmanszaak huisartswaarnemer. Vervangt Moneybird + Urenregister.xlsm. Draait lokaal op macOS, opent in browser. Geen persoonlijke data in de codebase — alles configureerbaar via Instellingen.

## Tech Stack
| Component | Technologie |
|-----------|------------|
| UI framework | NiceGUI >=3.0 (Quasar/Vue) |
| Database | SQLite via aiosqlite, raw SQL, GEEN ORM |
| Charts | ECharts via `ui.echart` (ingebouwd in NiceGUI) |
| Factuur-PDF | WeasyPrint + Jinja2 HTML template |
| Excel lezen | openpyxl (alleen eenmalige data-migratie) |
| Python | 3.12+ |

## Starten
```bash
# Vanuit projectroot:
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib  # nodig voor WeasyPrint
python main.py
# → http://127.0.0.1:8085

# Of: dubbelklik start-boekhouding.command
```

## Tests
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
# 109 tests, alle passing
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
├── database.py                 # SQLite schema + alle queries (31KB, ~850 regels)
├── models.py                   # Dataclasses: Bedrijfsgegevens, Klant, Werkdag, Factuur, Uitgave, Banktransactie, FiscaleParams
├── pages/
│   ├── dashboard.py            # KPIs + ECharts grafieken
│   ├── werkdagen.py            # Uren/km registratie met tabel + formulier
│   ├── facturen.py             # Factuur aanmaken + betaalstatus
│   ├── kosten.py               # Uitgaven + categorisatie + investering
│   ├── bank.py                 # Rabobank CSV import + categoriseren
│   ├── jaarafsluiting.py       # Fiscale berekeningen (7 secties)
│   └── instellingen.py         # Bedrijfsgegevens, klanten, fiscale params, backup
├── components/
│   ├── layout.py               # Shared layout: dark sidebar, header, theme, CSS
│   ├── utils.py                # format_euro(), format_datum() — ENIGE bron
│   ├── werkdag_form.py         # Herbruikbaar werkdag add/edit formulier
│   ├── charts.py               # ECharts: revenue_bar_chart, cost_donut_chart
│   └── invoice_generator.py    # WeasyPrint PDF factuur generator
├── fiscal/
│   ├── berekeningen.py         # W&V, fiscale waterval, IB-berekening (Decimal)
│   ├── afschrijvingen.py       # Lineair, pro-rata, restwaarde
│   └── heffingskortingen.py    # AHK + arbeidskorting tabellen 2023-2026
├── import_/
│   ├── run_full_import.py      # Eenmalige volledige data-import script
│   ├── urenregister.py         # xlsm → SQLite werkdagen + facturen
│   ├── rabobank_csv.py         # Bank CSV parser (UTF-8/ISO-8859-1, NL decimalen)
│   └── seed_data.py            # Fiscale params pre-fill (2023-2026)
├── templates/
│   └── factuur.html            # Jinja2 HTML factuur template
├── tests/                      # 9 testbestanden, 109 tests
├── docs/plans/                 # Design + implementatie docs (referentie)
├── data/                       # NIET in git: SQLite + PDFs + CSV archief
├── start-boekhouding.command   # macOS dubbelklik launcher
├── requirements.txt
└── pyproject.toml
```

## Database (7 tabellen)
`klanten`, `werkdagen`, `facturen`, `uitgaven`, `banktransacties`, `fiscale_params`, `bedrijfsgegevens`

**Regels:**
- Raw SQL met `?` placeholders, GEEN f-strings in SQL
- Bedragen als REAL (float), datums als TEXT (YYYY-MM-DD)
- `aiosqlite` voor async, WAL mode, foreign keys ON
- `bedrijfsgegevens` is single-row tabel (CHECK id=1)

## Pagina's
| Route | Pagina | Status |
|-------|--------|--------|
| `/` | Dashboard | Werkend — 4 KPIs, omzet bar chart, kosten donut |
| `/werkdagen` | Werkdagen | Werkend — tabel met filters, selectie, bulk delete, paginatie, add/edit/delete formulier |
| `/facturen` | Facturen | Werkend — factuur genereren vanuit werkdagen, PDF, betaalstatus |
| `/kosten` | Kosten | Werkend — uitgaven CRUD, categorieën, investering-vlag |
| `/bank` | Bank | Werkend — CSV upload, inline categorisatie |
| `/jaarafsluiting` | Jaarafsluiting | Werkend — 7-sectie fiscaal rapport met herbereken |
| `/instellingen` | Instellingen | Werkend — bedrijfsgegevens, klanten, fiscale params, backup |

## Design System (teal-slate)
- **Primary**: `#0F766E` (teal) — knoppen, actieve navigatie, charts
- **Sidebar/header**: `#0F172A` (dark navy)
- **Page background**: `#F8FAFC` (off-white)
- **Muted text**: `#64748B` (slate)
- **Positive**: `#059669`, **Negative**: `#DC2626`, **Warning**: `#D97706`, **Accent**: `#F59E0B`
- Component defaults in `components/layout.py`: flat bordered cards, outlined dense inputs, unelevated no-caps buttons
- Alle pages: `p-6 max-w-7xl mx-auto gap-6`, heading met `text-h5` + `color: #0F172A; font-weight: 700`
- `format_euro` en `format_datum` ALLEEN uit `components/utils.py` importeren (invoice_generator heeft nog een duplicaat — opruimen)

---

## Data Import Status (KRITIEK)

De eenmalige import (`import_/run_full_import.py`) heeft ernstige problemen:

### Facturen: VOLLEDIG KAPOT
- 118 facturen geimporteerd, maar ALLE hebben `totaal_bedrag = 0`, `totaal_uren = NULL`
- Alle datums staan op `YYYY-01-01` (altijd 1 januari) — geen echte factuurdatums
- Import parsed alleen PDF bestandsnamen, NIET de inhoud
- Klant-matching is fout: 2023 PDFs hebben geen klantnaam in filename → fallback naar verkeerde klant
- **Moet opnieuw**: facturen rebuilden vanuit werkdagen-koppeling

### Werkdagen: GEDEELTELIJK KAPOT
- 593 werkdagen geimporteerd, maar:
  - **177 werkdagen hebben tarief=0** terwijl er uren staan (openpyxl las formule-cellen als None)
  - **27+ werkdagen hebben DD-MM-YYYY datumformaat** i.p.v. YYYY-MM-DD (sortering/filtering kapot)
  - Slechts 45 van 593 werkdagen gekoppeld aan een factuurnummer
  - 437 status "betaald" maar zonder factuurnummer-koppeling
- Revenue vanuit werkdagen (waar tarief correct is): €81K (2023), €124K (2024), €35K (2025), €17K (2026)

### Uitgaven: NIET GEIMPORTEERD
- 0 uitgaven in DB — 228+ uitgaven-PDFs bestaan in brondata maar zijn nooit geimporteerd
- Geen automatische import mogelijk (uitgaven zijn los PDF-bestanden per categorie)
- Moeten handmatig ingevoerd worden OF via een slim import-script per categorie

### Wat wel werkt
- Klanten (13 stuks) zijn correct aangemaakt met mapping
- 4 actieve klanten correct geconfigureerd met tarief/km/adres
- Fiscale params 2023-2026 correct geseed
- Bedrijfsgegevens correct ingevuld

### Brondata locatie
```
~/Library/CloudStorage/SynologyDrive-Main/02_Financieel/Boekhouding_Waarneming/
├── Urenregister.xlsm           # MASTER: 587 datarijen, sheets: Urentabel, Stamgegevens, Facturatie
├── {2023,2024,2025,2026}/
│   ├── Inkomsten/
│   │   ├── Dagpraktijk/        # Eigen facturen: 120 PDFs (YYYY-NNN[_Klant].pdf)
│   │   └── ANW_Diensten/       # HAP facturen: 40 PDFs (diverse formaten)
│   └── Uitgaven/               # 228 PDFs in subcategorieën
│       ├── Accountancy/
│       ├── Investeringen/      # MacBook €2.919, iPhone, NAS, dermatoscoop, camera
│       ├── KPN/
│       ├── Pensioenpremie/
│       ├── Representatie/
│       ├── Verzekeringen/
│       └── ...
└── Scripts/backups/            # Urenregister backups + CSV exports
```

### Urenregister kolommen (A-U)
Datum, CODE, Klant, Activiteit, Locatie, Uren, Visite_km, Retourafstand_km, Uurtarief, Kilometertarief, TotUren, TotKm, Totaalbedrag, Factuurnummer, Status, Opmerkingen

### Investeringen in brondata (activastaat nodig)
| Item | Jaar | Bedrag | Levensduur |
|------|------|--------|------------|
| Kaldi (camera?) | 2023 | ? | 5 jaar |
| Camera (cameranu) | 2023 | ? | 5 jaar |
| MacBook Pro | 2024 | €2.919 | 4 jaar |
| iPhone 17 Pro Max | 2025 | ? | 4 jaar |
| NAS Synology DS1525+ | 2025 | ? | 5 jaar |
| Ubiquiti U7 Pro XGS | 2025 | ? | 5 jaar |
| Dermatoscoop | 2025 | ? | 5 jaar |

---

## Bekende Bugs (prioriteit: hoog → laag)

Volledige audit: `docs/audit-2026-03-03.md`

### KRITIEK — Foute belastingberekening
1. **bereken_ib() vs bereken_volledig() divergentie**: Verschillende inkomensbasis voor arbeidskorting. €498 verschil bij 2024 Boekhouder case. NB: bereken_ib() wordt alleen in tests gebruikt, niet in de app.
2. **mark_betaald cascadeert NIET naar werkdagen**: `database.py:466` — werkdagen blijven `gefactureerd` na factuur betaald markeren.

### HOOG — Crashes / data-integriteit
3. **NULL doorgifte in _row_to_fiscale_params**: `database.py:749` — `in keys` is True bij NULL waarde → `Decimal(None)` crash.
4. **link_werkdagen_to_factuur overschrijft bestaande koppeling**: `database.py:512` — geen check op status.
5. **DD-MM-YYYY datums onzichtbaar**: `database.py:296` — `substr('15-03-2026',1,4)='15-0'`, 27+ werkdagen verborgen. Data-fix nodig.
6. **Bank CSV: geen dedup op DB-niveau**: `database.py:687` — zelfde CSV importeren maakt duplicaten.
7. **delete_klant crasht op FK violation**: `database.py:277` — onafgehandelde IntegrityError.
8. **Investment kostenaftrek negeert zakelijk_pct**: `jaarafsluiting.py:443` — trekt bruto af, niet zakelijk deel.

### MEDIUM — Randgevallen / UX
9. **Wet Hillen: pct > 100** → negatief saldo (geen clamping).
10. **Backup: geen WAL checkpoint** voor consistente snapshot.
11. **€450 investeringsdrempel hardcoded** op 4 plekken in kosten.py.

### OPGELOST (eerder gemeld, nu gefixt)
- ~~Werkdagen selectie-checkboxen~~ → Werkend (Phase 1), herschreven met `selection='multiple'` (Phase 4)
- ~~Bank selectie-checkboxen~~ → Werkend met `selection='multiple'` + `props.selected` (Phase 4)
- ~~Async/lambda pattern~~ → NiceGUI 3.8 handled dit automatisch (bewezen via source code audit)
- ~~Mark-als-betaald bevestigingsdialog~~ → Toegevoegd (Phase 1)
- ~~Eigenwoningforfait hardcoded~~ → Nu in DB (Phase 3)
- ~~IB-inputs verliezen waarden~~ → Persisted per jaar (Phase 2)
- ~~Lege tabellen~~ → no-data slots toegevoegd (Phase 1)
- ~~Factuur verwijderen~~ → Delete + bulk delete (Phase 1)
- ~~Bon uploaden bij uitgave~~ → Upload widget (Phase 2)
- ~~Jaarafsluiting PDF export~~ → WeasyPrint (Phase 2)
- ~~KIA grens `<` i.p.v. `<=`~~ → Gefixt, `<=` op berekeningen.py:145
- ~~ZeroDivisionError bij levensduur=0~~ → Input validation in afschrijvingen.py:24
- ~~Afschrijving negatieve levensduur~~ → Geclamped in afschrijvingen.py:24
- ~~Afschrijving maand=0~~ → Geclamped in afschrijvingen.py:27
- ~~format_datum keert NL-datums om~~ → Correct: DD-MM-YYYY passthrough (utils.py:47)
- ~~Backup mist uitgaven/jaarafsluiting/bank_csv dirs~~ → Alle data dirs in ZIP (Phase 4)
- ~~Kosten/omzet ratio kleur omgekeerd~~ → Laag = groen (Phase 4)
- ~~Dashboard URENCRITERIUM hardcoded~~ → Leest uit DB (Phase 4)
- ~~Representatie "80%" label hardcoded~~ → Leest repr_aftrek_pct uit DB (Phase 4)

## Ontbrekende Features (backlog)
- **Bank koppelen aan factuur/uitgave** — `koppeling_type`/`koppeling_id` kolommen bestaan maar geen UI
- **Browser auto-open** — `main.py` heeft `show=False`, browser opent niet automatisch
- **Bank CSV per-transactie dedup** — alleen bestandsnaam-check, geen inhoudelijke dedup

---

## Domeinkennis

### Kostencategorieën
```
Pensioenpremie SPH        100% aftrekbaar
Telefoon/KPN              zakelijk deel
Verzekeringen             100% (excl. AOV → Box 1)
Accountancy/software      100%
Representatie             80% aftrekbaar (20% bijtelling)
Lidmaatschappen           100%
Kleine aankopen (<€450)   direct ten laste
Scholingskosten           100%
Bankkosten                100%
Investeringen (≥€450)     via afschrijving + KIA
```

### Fiscale kernregels
- **BTW-vrijgesteld** (art. 11 lid 1 sub g Wet OB) → kosten INCL BTW, geen BTW-aangifte
- **Urencriterium**: 1.225 uur/jaar. Achterwacht (urennorm=0) telt NIET mee
- **AOV**: GEEN bedrijfskosten → Box 1 inkomensvoorziening
- **Km-tarief**: €0,21/km (2023), €0,23/km (2024-2026)
- **KIA**: 28% × investeringen bij totaal €2.901-€70.602/jaar
- **Afschrijvingen**: lineair, restwaarde 10%, eerste jaar pro-rata per maand
- **Representatie**: 80%-regeling

### Factuur wettelijke vereisten
Elke factuur MOET bevatten: naam+adres+KvK verkoper, naam+adres klant, factuurnummer (YYYY-NNN doorlopend), factuurdatum+vervaldatum (14 dagen), omschrijving diensten+datum, bedrag, BTW-vrijstellingstekst, IBAN+betaalinfo.

### Boekhouder referentiecijfers (tests valideren hiertegen)
- **2023**: winst €62.522 → belastbare winst €45.801 → IB terug €415
- **2024**: winst €95.145 → belastbare winst €76.776 → IB terug €3.137

## Ontwikkelregels

### Architectuur
- **Browser mode ALTIJD**: `ui.run(host='127.0.0.1', port=8085)` — NOOIT native/pywebview
- **Geen ORM**: raw SQL met `aiosqlite`, parameterized queries
- **Data in `data/`**: SQLite + PDFs. In `.gitignore`
- **SQLite op lokaal filesystem**: NIET via SMB/netwerk mount (WAL faalt). `start-boekhouding.command` cd't naar CloudStorage pad

### YAGNI
Geen: user auth, BTW-administratie, loon/voorraad, email, real-time bank-API, auto-matching, CI/CD, multi-language

### Code stijl
- Python 3.12+, type hints op functies
- Async voor DB operaties
- `ui.table` (NIET AG Grid), `ui.echart` voor charts
- **Tabel selectie**: ALTIJD `selection='multiple'` op `ui.table`. NOOIT custom checkbox slots met `$parent.$emit` — die werken niet betrouwbaar. Gebruik `table.selected` (lijst van row dicts) en `table.on('selection', handler)`. Referentie: facturen.py, werkdagen.py.
- Bij full `body` slot met selectie: `<q-checkbox v-model="props.selected" dense />` (Quasar-managed), NIET `v-model="props.row.selected"`. Referentie: bank.py.
- Shared layout via `components/layout.py`
- Elke pagina is `@ui.page('/route')` in eigen bestand
- Tests met pytest + pytest-asyncio
- `format_euro`/`format_datum` ALLEEN uit `components/utils.py`
- Quasar semantic kleuren (`positive`, `negative`, `warning`, `primary`) — vermijd hardcoded hex in pagina's
