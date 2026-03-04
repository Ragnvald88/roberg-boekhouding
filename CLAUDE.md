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

# Tests (117 passing)
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

## Database
8 tabellen: `klanten`, `werkdagen`, `facturen`, `uitgaven`, `banktransacties`, `fiscale_params`, `bedrijfsgegevens`, `aangifte_documenten`

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

### NiceGUI Patronen
- `ui.table` (NIET AG Grid), `ui.echart` voor charts
- **Tabel selectie**: ALTIJD `selection='multiple'`. NOOIT custom checkbox slots met `$parent.$emit`. Gebruik `table.selected` en `table.on('selection', handler)`.
- Bij full `body` slot met selectie: `<q-checkbox v-model="props.selected" dense />` (Quasar-managed), NIET `v-model="props.row.selected"`.
- **Add/edit formulieren**: via `ui.dialog()` popup, NIET inline op de pagina. Referentie: werkdag_form.py, kosten.py, facturen.py.
- Quasar semantic kleuren (`positive`, `negative`, `warning`, `primary`) — geen hardcoded hex in pagina's

### YAGNI
Geen: user auth, BTW-administratie, loon/voorraad, email, real-time bank-API, auto-matching, CI/CD, multi-language

## Domeinkennis (fiscaal)
- **BTW-vrijgesteld** (art. 11 Wet OB) → kosten INCL BTW, geen BTW-aangifte
- **Urencriterium**: 1.225 uur/jaar. Achterwacht (urennorm=0) telt NIET mee
- **AOV**: GEEN bedrijfskosten → Box 1 inkomensvoorziening
- **KIA**: 28% bij totaal investeringen >= €2.901 (inclusive)
- **Afschrijvingen**: lineair, restwaarde 10%, eerste jaar pro-rata per maand
- **Representatie**: 80%-regeling (configureerbaar in `fiscale_params`)
- **Factuur vereisten**: naam+adres+KvK, factuurnummer YYYY-NNN, vervaldatum 14d, BTW-vrijstellingstekst

### Boekhouder referentiecijfers (tests valideren hiertegen)
- **2023**: winst €62.522 → belastbare winst €45.801 → IB terug €415
- **2024**: winst €95.145 → belastbare winst €76.776 → IB terug €3.137

## Bekende Bugs

- **DD-MM-YYYY datums**: 27+ werkdagen met verkeerd formaat in DB, onzichtbaar bij filters (`substr(datum,1,4)` faalt). Data-fix + input-validatie nodig.
- **Bank CSV geen dedup**: Alleen bestandsnaam-check, geen per-transactie dedup. Dezelfde CSV met andere naam → duplicaten.
- **delete_klant UI**: DB vangt FK violation, maar `instellingen.py` vangt de ValueError niet → geen nette foutmelding.
- **fiscale_params NULL-risico**: 15 velden in `_row_to_fiscale_params` missen NULL-guards. Geen crash nu, maar bij ontbrekende DB-waarden kan None in berekeningen terechtkomen.
