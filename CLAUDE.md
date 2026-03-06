# Boekhouding App

Standalone boekhoudapplicatie (NiceGUI + Python) voor een eenmanszaak huisartswaarnemer. Draait lokaal op macOS, opent in browser. Data in `data/` (niet in git).

## Tech Stack
- **UI**: NiceGUI >=3.0 (Quasar/Vue), browser mode (`ui.run(host='127.0.0.1', port=8085)`)
- **Database**: SQLite via aiosqlite, raw SQL met `?` placeholders, GEEN ORM
- **PDF**: WeasyPrint + Jinja2, **Charts**: ECharts via `ui.echart`
- **Python**: 3.12+

## Commands
```bash
# Start
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py  # → http://127.0.0.1:8085

# Tests (260 passing)
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

## Database
9 tabellen: `klanten`, `klant_locaties`, `werkdagen`, `facturen`, `uitgaven`, `banktransacties`, `fiscale_params`, `bedrijfsgegevens`, `aangifte_documenten`

- Raw SQL, `?` placeholders — GEEN f-strings in SQL
- Bedragen REAL, datums TEXT (YYYY-MM-DD)
- `aiosqlite` async, WAL mode, foreign keys ON
- `bedrijfsgegevens` = single-row (CHECK id=1)
- SQLite op lokaal filesystem, NIET via SMB (WAL faalt)

## Ontwikkelregels

### Architectuur
- Browser mode ALTIJD — NOOIT native/pywebview
- Shared layout via `components/layout.py`
- Elke pagina is `@ui.page('/route')` in eigen bestand
- `format_euro`/`format_datum` ALLEEN uit `components/utils.py`
- **Fiscal utils**: `components/fiscal_utils.py` (shared `fiscale_params_to_dict` + `fetch_fiscal_data`)
- **Fiscal engine**: `fiscal/berekeningen.py` (bereken_volledig waterfall + bereken_box3)
- **Heffingskortingen**: `fiscal/heffingskortingen.py` (AK brackets + AHK)

### NiceGUI Patronen
- `ui.table` (NIET AG Grid), `ui.echart` voor charts
- **Tabel selectie**: ALTIJD `selection='multiple'`. NOOIT custom checkbox slots met `$parent.$emit`. Gebruik `table.selected` en `table.on('selection', handler)`.
- Bij full `body` slot met selectie: `<q-checkbox v-model="props.selected" dense />` (Quasar-managed), NIET `v-model="props.row.selected"`.
- **Add/edit formulieren**: via `ui.dialog()` popup, NIET inline op de pagina. Referentie: werkdag_form.py, kosten.py, facturen.py.
- Quasar semantic kleuren (`positive`, `negative`, `warning`, `primary`) — geen hardcoded hex in pagina's

### YAGNI
Geen: user auth, BTW-administratie, loon/voorraad, email, real-time bank-API, auto-matching, CI/CD, multi-language

## Domeinkennis (fiscaal)

### Basisregels
- **BTW-vrijgesteld** (art. 11 Wet OB) → kosten INCL BTW, geen BTW-aangifte
- **Urencriterium**: 1.225 uur/jaar. Achterwacht (urennorm=0) telt NIET mee
- **AOV**: GEEN bedrijfskosten → Box 1 inkomensvoorziening
- **KIA**: 28% bij totaal investeringen >= €2.901 (inclusive)
- **Afschrijvingen**: lineair, restwaarde 10%, eerste jaar pro-rata per maand
- **Representatie**: 80%-regeling (configureerbaar in `fiscale_params`)
- **Factuur vereisten**: naam+adres+KvK, factuurnummer YYYY-NNN, vervaldatum 14d, BTW-vrijstellingstekst

### DB-driven parameters (alle configureerbaar in Instellingen)
- **Arbeidskorting**: JSON brackets in `arbeidskorting_brackets` column, fallback to Python constants in `heffingskortingen.py`
- **PVV rates**: `pvv_aow/anw/wlz_pct` columns (default 17.90/0.10/9.65), fallback to constants
- **Box 3**: Per-jaar rendementen (bank/overig/schuld), heffingsvrij vermogen, tarief
- **Alle andere**: ZA, SA, MKB%, KIA, AHK, AK, ZVW, schijf1/2/3, EW forfait, villataks, Wet Hillen, etc.
- **Input velden** (preserved across param upserts): AOV, WOZ, hypotheekrente, VA IB, VA ZVW, partner, Box 3 saldi, ew_naar_partner

### Fiscal engine
- **Arbeidskorting input** = fiscale_winst (vóór ZA/SA/MKB), NOT belastbare_winst
- **Tariefsaanpassing**: Since 2023, deductions at basistarief only. Excess clawed back.
- **Eigen woning**: Configurable `ew_naar_partner`. Default True (Boekhouder practice).
- **ZVW grondslag** = belastbare_winst, NOT verzamelinkomen
- **PVV** = 27.65% over min(verzamelinkomen, premiegrondslag)
- **PVV premiegrondslag**: 2024=38098, 2025+ = schijf1_grens

### Boekhouder referentiecijfers (tests valideren hiertegen)
- **2023**: winst €62.522 → belastbare winst €45.801 → IB terug €415
- **2024**: winst €95.145 → belastbare winst €76.776 → IB terug €3.137

## Aangifte pagina (Invulhulp)
5-tab invulhulp mirroring Belastingdienst IB-aangifte structure. Year defaults to vorig jaar.
Each value shows BD field label + copy-to-clipboard (raw integer for portal input).
Tabs: Winst uit onderneming, Prive & aftrek (inputs save to DB), Box 3 (inputs+calc), Overzicht (final summary), Documenten (upload checklist)

## Bekende Bugs

- **Bank CSV geen dedup**: Alleen bestandsnaam-check, geen per-transactie dedup. Dezelfde CSV met andere naam → duplicaten.
- **delete_klant UI**: DB vangt FK violation, maar `instellingen.py` vangt de ValueError niet → geen nette foutmelding.
