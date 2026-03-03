# UX & Fiscal Improvements Design

**Datum:** 2026-03-03
**Status:** Ontwerp

## Probleemanalyse

De app mist vier categorieën functionaliteit die elke vergelijkbare boekhoudapp (Moneybird, Jortt, Tellow) wel biedt:

1. **Fiscale gegevens verdwijnen** — WOZ, hypotheekrente, AOV en voorlopige aanslag worden op jaarafsluiting telkens opnieuw ingevoerd. Ze overleven geen page reload. Elke concurrent slaat deze per jaar op.
2. **Documenten niet koppelbaar** — De `pdf_pad` kolom op uitgaven bestaat, maar er is geen upload UI. Bonnen/facturen zijn niet digitaal archiveerbaar (bewaarplicht 7 jaar).
3. **Dashboard is passief** — Geen waarschuwingen over ongefactureerde werkdagen, geen vergelijking met vorig jaar, geen belastingschatting. Moneybird en FreshBooks tonen YoY-delta's en actiegerichte alerts.
4. **Geen export** — De 7-sectie jaarafsluiting is alleen in de browser zichtbaar, niet exporteerbaar als PDF voor de accountant. Geen CSV-export op tabellen.
5. **Eigenwoningforfait te simplistisch** — Hardcoded 0.35%, geen Wet Hillen-regeling.

## 1. Persist IB-inputs per jaar

### Probleem
Op de jaarafsluiting pagina voer je AOV-premie, WOZ-waarde, hypotheekrente en voorlopige aanslag handmatig in. Bij elke page reload of navigatie weg zijn deze waarden kwijt. Je moet ze telkens opnieuw opzoeken en invoeren.

### Oplossing
Voeg 4 kolommen toe aan de bestaande `fiscale_params` tabel (die al per `jaar` primary key heeft):

```sql
ALTER TABLE fiscale_params ADD COLUMN aov_premie REAL DEFAULT 0;
ALTER TABLE fiscale_params ADD COLUMN woz_waarde REAL DEFAULT 0;
ALTER TABLE fiscale_params ADD COLUMN hypotheekrente REAL DEFAULT 0;
ALTER TABLE fiscale_params ADD COLUMN voorlopige_aanslag_betaald REAL DEFAULT 0;
```

**Gedrag:**
- Bij paginalading: lees waarden uit DB voor geselecteerd jaar, vul inputs voor
- Bij Herbereken: sla huidige inputwaarden op in DB, dan herbereken
- Bij jaarwissel: sla huidige waarden op, laad waarden van nieuw jaar
- Resultaat: je voert WOZ/hypotheekrente eenmalig in per jaar, klaar

### Bestanden
- `database.py` — schema migratie + update `upsert_fiscale_params` en `get_fiscale_params`
- `models.py` — 4 nieuwe velden op `FiscaleParams`
- `pages/jaarafsluiting.py` — bereken() leest waarden uit DB, herbereken() slaat op

## 2. Eigenwoningforfait correct berekenen

### Probleem
Huidige code (`fiscal/berekeningen.py:157`): `d_ew_forfait = d_woz * D('0.0035')`. Dit is correct voor WOZ EUR 75k-1.35M maar:
- Geen Wet Hillen wanneer forfait > hypotheekrente (relevant als hypotheek bijna afgelost)
- Geen villataks boven EUR 1.35M grens (minder relevant maar incorrect)

### Oplossing
Voeg `bereken_eigenwoningforfait(woz, jaar)` toe in `fiscal/berekeningen.py`:

```python
VILLATAKS_GRENS = {2023: 1_200_000, 2024: 1_310_000, 2025: 1_330_000, 2026: 1_350_000}
WET_HILLEN_PCT = {2023: 0.83333, 2024: 0.80000, 2025: 0.76667, 2026: 0.71867}

def bereken_eigenwoningforfait(woz: float, jaar: int) -> float:
    # 0.35% voor WOZ EUR 75k - villataks_grens (veruit meest voorkomend)
    # Villataks: vast_bedrag + 2.35% boven grens
    grens = VILLATAKS_GRENS.get(jaar, 1_350_000)
    if woz <= grens:
        return woz * 0.0035
    return grens * 0.0035 + (woz - grens) * 0.0235
```

En pas `bereken_volledig()` aan:
```python
d_ew_forfait = D(str(bereken_eigenwoningforfait(woz, jaar)))
d_ew_saldo = d_ew_forfait - d_hypotheekrente

# Wet Hillen: als forfait > rente, verlaag de bijtelling
if d_ew_saldo > 0:
    hillen_pct = D(str(WET_HILLEN_PCT.get(jaar, 0)))
    d_ew_saldo -= d_ew_saldo * hillen_pct
```

### Bestanden
- `fiscal/berekeningen.py` — eigenwoningforfait functie + Wet Hillen in bereken_volledig
- Bestaande tests updaten/uitbreiden

## 3. Document upload bij uitgaven

### Probleem
De `uitgaven.pdf_pad` kolom bestaat maar er is geen manier om bestanden te uploaden. Bonnen en facturen voor kosten kunnen niet digitaal gekoppeld worden.

### Oplossing
Simpele upload per uitgave, bestanden opgeslagen op disk in `data/uitgaven/`.

**Upload toevoegen op 2 plekken in kosten.py:**

a) **In de "Uitgave toevoegen" sectie**: optioneel upload-veld na het formulier
b) **In de edit dialog**: upload-knop als er nog geen bon is, download/verwijder als er wel een is
c) **In de tabel**: paperclip-icoon bij rijen waar `pdf_pad` niet leeg is

**Bestandsopslag:**
```
data/uitgaven/
├── uitgave_42_KPN_factuur.pdf
├── uitgave_55_verzekering.pdf
└── ...
```

Bestandsnaam: `uitgave_{id}_{originele_naam}`. Pad opslaan als absolute path in `pdf_pad`.

**Tabel-indicator:**
```vue
<q-btn v-if="props.row.pdf_pad" icon="attach_file" flat dense round size="sm"
       @click="() => $parent.$emit('viewdoc', props.row)" title="Bekijk bon" />
```

### Bestanden
- `pages/kosten.py` — upload in form + edit dialog + tabel indicator
- `database.py` — geen wijzigingen nodig (pdf_pad kolom bestaat al)

## 4. Dashboard verbeteringen

### 4a. Year-over-year delta op KPIs
Elke KPI toont een delta-percentage versus vorig jaar:
- "Bruto omzet: EUR 95.000 (+52%)" met groen pijltje
- "Bedrijfslasten: EUR 12.000 (+8%)" met oranje pijltje
- Delta = (huidig - vorig) / vorig * 100

### 4b. Geschatte IB-afdracht KPI
Nieuwe KPI card: "Geschatte IB" die `bereken_volledig()` aanroept met de opgeslagen IB-inputs uit de DB. Toont het `resultaat` veld (negatief = teruggave, positief = bijbetalen). Klikt door naar `/jaarafsluiting`.

### 4c. Ongefactureerde werkdagen alert
Waarschuwingskaart (amber achtergrond, net als de openstaande facturen kaart):
- "X ongefactureerde werkdagen (EUR Y)" met knop naar `/werkdagen`
- Alleen zichtbaar als er ongefactureerde werkdagen zijn

### 4d. Km-vergoeding YTD
In het operations KPI-rijtje: totaal gereden km dit jaar met berekende vergoeding.

### Bestanden
- `pages/dashboard.py` — nieuwe KPIs, alert card, YoY berekening
- `database.py` — nieuwe query `get_werkdagen_ongefactureerd_summary()`, `get_km_totaal()`

## 5. Export functionaliteit

### 5a. Jaarafsluiting PDF export
Knop "Exporteer als PDF" naast de Herbereken-knop. Genereert een WeasyPrint PDF van alle 7 secties.

**Aanpak:** Jinja2 HTML template (net als factuur template), gevuld met FiscaalResultaat data, gerenderd via WeasyPrint naar `data/jaarafsluiting/jaarafsluiting_{jaar}.pdf`.

### 5b. CSV export op tabellen
Exportknop op werkdagen, facturen en uitgaven pagina's. Gebruikt Python `csv` module, biedt download aan.

### Bestanden
- `templates/jaarafsluiting.html` — nieuw Jinja2 template
- `pages/jaarafsluiting.py` — export knop + PDF generatie
- `pages/werkdagen.py`, `pages/facturen.py`, `pages/kosten.py` — CSV export knop

## Implementatievolgorde

1. **database.py + models.py** — schema migratie voor IB-inputs (foundation)
2. **fiscal/berekeningen.py** — eigenwoningforfait + Wet Hillen fix
3. **pages/jaarafsluiting.py** — persist IB-inputs + herbereken slaat op
4. **pages/kosten.py** — document upload
5. **pages/dashboard.py** — YoY delta's, geschatte IB, alerts
6. **Export** — jaarafsluiting PDF template + CSV exports
7. **Tests** — uitbreiden voor nieuwe functionaliteit

## Wat NIET in scope is (YAGNI)

- OCR/automatisch parsen van hypotheek-jaaroverzichten (te fragiel, elke bank verschilt)
- Recurring expenses (handmatige invoer is prima voor ~10 maandelijkse posten)
- Audit trail/change history (overkill voor eenmanszaak)
- Tax deadline reminders (statische data, weinig waarde)
- Global search bar (filters per pagina zijn voldoende)
- Dashboard customization (vaste layout is prima)
