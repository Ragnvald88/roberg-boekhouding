# VA Beschikkingen: Beschikking-gebaseerde invoer + Bankmatching

## Samenvatting

Vervang de huidige handmatige VA-invoer (twee losse bedragvelden op de Aangifte Prive-tab) door een beschikking-gebaseerd systeem met automatische koppeling aan bankbetalingen. VA "betaald" wordt gebaseerd op werkelijke banktransacties, niet op theoretische proration.

## Probleemstelling

1. **VA-invoer is verstopt**: twee bedragvelden op Aangifte Tab 2, card 3 — niet vindbaar
2. **Proration is fout**: dashboard berekent `jaarbedrag x maand/12`, maar VA heeft 11 termijnen (feb-dec), niet 12
3. **Geen koppeling met bank**: 61 Belastingdienst-transacties in de DB, allemaal ongebruikt
4. **"Betaald" is een aanname**: app neemt aan dat je alle termijnen betaald hebt, maar weet het niet zeker

## Design

### 1. Database

#### 1a. Nieuwe kolommen op `fiscale_params`

| Kolom | Type | Default | Doel |
|---|---|---|---|
| `va_termijnen` | INTEGER | 11 | Aantal termijnen per beschikking |
| `va_start_maand` | INTEGER | 2 | Eerste termijn maand (2=feb) |
| `va_ib_kenmerk` | TEXT | '' | Betalingskenmerk IB (optioneel, voor matching) |
| `va_zvw_kenmerk` | TEXT | '' | Betalingskenmerk ZVW (optioneel, voor matching) |

Bestaande kolommen blijven:
- `voorlopige_aanslag_betaald` REAL = IB jaarbedrag
- `voorlopige_aanslag_zvw` REAL = ZVW jaarbedrag

`va_termijnen` en `va_start_maand` zijn gedeeld voor IB en ZVW (altijd zelfde schema uit beschikking).

#### 1b. Gebruik bestaande `banktransacties` koppeling-kolommen

`koppeling_type` en `koppeling_id` bestaan al op `banktransacties` maar zijn nooit gebruikt (0 van 928 gevuld).

Nieuwe koppeling-waarden:
- `koppeling_type = 'va_ib'`, `koppeling_id = <jaar>` (bv. 2025)
- `koppeling_type = 'va_zvw'`, `koppeling_id = <jaar>`

#### 1c. Migratie

- `ALTER TABLE fiscale_params ADD COLUMN va_termijnen INTEGER DEFAULT 11`
- `ALTER TABLE fiscale_params ADD COLUMN va_start_maand INTEGER DEFAULT 2`
- `ALTER TABLE fiscale_params ADD COLUMN va_ib_kenmerk TEXT DEFAULT ''`
- `ALTER TABLE fiscale_params ADD COLUMN va_zvw_kenmerk TEXT DEFAULT ''`

Defaults zijn correct voor alle bestaande data (2023-2026 beschikkingen zijn altijd 11 termijnen, start feb).

**Migratie-implementatie**: `va_termijnen` en `va_start_maand` toevoegen aan de INTEGER-migratieloop (samen met de REAL-kolommen, met correcte type-aanduiding). `va_ib_kenmerk` en `va_zvw_kenmerk` toevoegen aan de TEXT-migratieloop.

#### 1d. Wijziging bestaande functies

**`_row_to_fiscale_params()`**: 4 nieuwe `_safe_get()` calls toevoegen met defaults (11, 2, '', '').

**`upsert_fiscale_params()`**: De 4 nieuwe kolommen toevoegen aan de preserve-SELECT (regels ~999-1009) zodat Instellingen → opslaan de VA-kolommen niet overschrijft.

### 2. Nieuwe DB-functies

#### `update_va_beschikking(db_path, jaar, va_ib, va_zvw, termijnen, start_maand, va_ib_kenmerk, va_zvw_kenmerk)`

UPDATE fiscale_params SET de 6 VA-kolommen WHERE jaar=?. Gescheiden van `update_ib_inputs()`.

#### `auto_match_va_betalingen(db_path, jaar)`

Koppelt ongelinkte Belastingdienst-transacties aan VA IB of ZVW voor een specifiek jaar.

**Guards**: Skip matching voor een type als het jaarbedrag == 0 (voorkom foute koppelingen als de user slechts één beschikking heeft ingevuld).

**Identificatie BD-transacties:**
- `tegenpartij = 'Belastingdienst'` OF `tegenrekening = 'NL86INGB0002445588'`
- `bedrag < 0` (uitgaand)
- `datum LIKE '{jaar}-%'` (strict jaarmatch, geen cross-year buffer — als een december-betaling op 1 jan geboekt wordt, verschijnt die in "niet-gekoppeld" en kan handmatig gekoppeld worden)
- `koppeling_type = ''` (nog niet gekoppeld)

**Matching-strategie (volgorde):**

1. **Betalingskenmerk**: Als `omschrijving` het opgeslagen kenmerk bevat (punten/spaties gestript) → 100% match
2. **Bedrag-match**: Bereken verwacht termijnbedrag (jaarbedrag / termijnen). Vergelijk `|bedrag|` met termijnbedrag. Tolerance: 5%. Omdat IB en ZVW typisch factor 5-10x verschillen, is dit betrouwbaar.
3. **Niet-matchbaar**: Transactie blijft ongekoppeld, zichtbaar op VA-tab als "niet-gekoppeld"

**Na match**: `UPDATE banktransacties SET koppeling_type=?, koppeling_id=? WHERE id=?`

#### `get_va_betalingen(db_path, jaar, va_type)` → list[Banktransactie]

Haal gekoppelde transacties op: `WHERE koppeling_type=? AND koppeling_id=?`

#### `get_va_betaald_totaal(db_path, jaar, va_type)` → float

Haal totaal betaald bedrag op: `SELECT COALESCE(SUM(ABS(bedrag)), 0) FROM banktransacties WHERE koppeling_type=? AND koppeling_id=?`. Retourneert een scalar (float). Gebruikt door dashboard voor snelle lookup zonder hele transactielijst.

#### `ontkoppel_va_betaling(db_path, tx_id)`

Reset `koppeling_type=''`, `koppeling_id=NULL` voor handmatige correctie. Triggert GEEN automatische re-match — de transactie verschijnt in de "niet-gekoppeld" sectie voor handmatige toewijzing.

#### `koppel_va_betaling(db_path, tx_id, va_type, jaar)`

Handmatig koppelen: `SET koppeling_type=?, koppeling_id=?`

### 3. Helper: `bereken_va_betaald_theoretisch()`

In `components/fiscal_utils.py`:

```python
def bereken_va_betaald_theoretisch(jaarbedrag: float, termijnen: int,
                                    start_maand: int, peildatum: date) -> tuple[float, int]:
    """Theoretisch betaald bedrag op basis van termijnschema (fallback als geen bankdata).
    Telt de huidige maand als betaald (kan aan begin van de maand 1 over-tellen,
    acceptabel als dashboard-schatting)."""
    if jaarbedrag <= 0 or termijnen <= 0:
        return 0.0, 0
    betaalde = max(0, min(peildatum.month - start_maand + 1, termijnen))
    bedrag = round(betaalde * (jaarbedrag / termijnen), 2)
    return bedrag, betaalde
```

Dit is de fallback als er geen bankdata beschikbaar is (bv. 2023 zonder bank-import).

**Primaire bron** voor "betaald" is altijd `get_va_betaald_totaal()` (SUM van gekoppelde banktransacties).

### 4. Wijziging `update_ib_inputs()`

VA-parameters verwijderen uit `update_ib_inputs()`. Wordt:

```python
async def update_ib_inputs(db_path, jaar, aov_premie, woz_waarde,
                           hypotheekrente, lijfrente_premie):
```

4 kolommen i.p.v. 6. VA wordt opgeslagen via `update_va_beschikking()`.

**Bestaande tests** die `update_ib_inputs()` aanroepen met `voorlopige_aanslag_betaald`/`voorlopige_aanslag_zvw` kwargs moeten bijgewerkt worden — deze parameters verhuizen naar `update_va_beschikking()`.

### 5. Wijziging `fetch_fiscal_data()`

Toevoegen aan returned dict:
- `'va_termijnen'`: params.va_termijnen or 11
- `'va_start_maand'`: params.va_start_maand or 2
- `'va_ib_kenmerk'`: params.va_ib_kenmerk or ''
- `'va_zvw_kenmerk'`: params.va_zvw_kenmerk or ''

### 6. Aangifte — Nieuwe tab "Voorlopige Aanslagen"

#### Tab-structuur

```
[Voorlopige Aanslagen] [Winst] [Prive & aftrek] [Box 3] [Overzicht] [Documenten]
```

Nieuwe tab met icon `receipt_long`, als eerste tab. **Niet default-actief**: `ui.tab_panels(tabs, value=tab_winst)` blijft expliciet ingesteld zodat Winst de default-tab blijft ondanks dat VA visueel als eerste verschijnt.

#### Layout

Twee cards naast elkaar (`ui.row`):

**IB Card: "Inkomstenbelasting / Premie volksverzekeringen"**
- `ui.number`: Jaarbedrag (€, format %.2f, prefix €)
- `ui.input`: Betalingskenmerk (optioneel, voor matching)
- Separator "Betaalschema"
- `ui.number`: Aantal termijnen (default 11, min 1, max 12)
- `ui.select`: Eerste termijn (maand-dropdown, default februari)
- `ui.label`: Termijnbedrag (computed: jaarbedrag / termijnen)
- Separator "Betalingen"
- `ui.table`: Gekoppelde banktransacties (datum, bedrag) — readonly
- Totaalregel: "Betaald: €X (N betalingen)" / "Openstaand: €Y"
- Knop "Hermatchen" om `auto_match_va_betalingen` opnieuw te draaien

**ZVW Card: "Zorgverzekeringswet"**
- `ui.number`: Jaarbedrag
- `ui.input`: Betalingskenmerk
- Termijnen/start_maand: label "Gekoppeld aan IB" (niet apart bewerkbaar)
- Termijnbedrag (computed)
- Betalingen-tabel + totalen (zelfde structuur)

**Niet-gekoppelde BD-transacties:**
Onder de twee cards, een derde sectie (alleen zichtbaar als er ongekoppelde BD-transacties zijn):

```
─── Niet-gekoppelde Belastingdienst-transacties ───
28-05-2025   -€ 450,00   (omschrijving: ...)   [Koppel aan IB] [Koppel aan ZVW]
```

Knoppen om handmatig te koppelen aan IB of ZVW voor het geselecteerde jaar.

#### Save-flow

- Auto-save on blur voor jaarbedrag, kenmerk
- Change op termijnen/start_maand → save + herbereken termijnbedrag
- Na save: `update_va_beschikking()` → `auto_match_va_betalingen()` → `_invalidate_cache()` → refresh VA-tab + `render_overzicht()`

### 7. Verwijderen VA van Tab "Prive & aftrek"

Card 3 ("Voorlopige aanslagen") verdwijnt volledig. `save_prive()` slaat geen VA meer op.

### 8. Aangifte Overzicht (Tab 4) — Resultaat card

**Geen wijziging in berekening**: gebruikt altijd volledig jaarbedrag via `bereken_volledig()`.

**Kleine UI-verbetering**: toon bron van het betaalde bedrag:
- Als bankdata beschikbaar: "VA IB (11 betalingen): -€29.851"
- Als geen bankdata: "VA IB (beschikking): -€29.851"

### 9. Dashboard KPI "Belasting prognose"

Vervanging van proration-logica:

```python
# OUD (fout):
va_ib = round(annual_va_ib * month / 12, 2)

# NIEUW:
# 1. Probeer werkelijk betaald (bank)
va_ib_betalingen = await get_va_betaald_totaal(DB_PATH, jaar, 'va_ib')
va_zvw_betalingen = await get_va_betaald_totaal(DB_PATH, jaar, 'va_zvw')

# 2. Fallback naar theoretisch als geen bankdata
if va_ib_betalingen == 0 and annual_va_ib > 0:
    va_ib, _ = bereken_va_betaald_theoretisch(annual_va_ib, termijnen, start_maand, today)
else:
    va_ib = va_ib_betalingen
# (zelfde logica voor va_zvw)
```

KPI sub-detail: "VA betaald (3 betalingen): -€8.141" of "VA betaald (geschat 3/11): -€8.141"

### 10. Bank pagina

Gekoppelde transacties tonen label in de tabel:
- Kolom `koppeling` (bestaand maar ongebruikt): "VA IB 2025" of "VA ZVW 2025"

### 11. Edge cases

| Situatie | Gedrag |
|---|---|
| Jaarbedrag = 0 voor beide | Geen VA, betalingen-sectie verborgen, matching overgeslagen |
| Jaarbedrag IB > 0, ZVW = 0 | Alleen IB matchen, ZVW matching overgeslagen |
| Geen banktransacties geimporteerd | Fallback naar theoretische proration |
| Herziene beschikking (hoger/lager) | User overschrijft jaarbedrag, hermatchen toont of bestaande betalingen nog passen |
| Dubbele betaling (storno + herbetaling) | Beide worden gekoppeld, SUM is correct (storno = positief bedrag wordt niet gematcht want bedrag > 0) |
| BD-transactie past bij geen van beide | Toont in "niet-gekoppeld" sectie, user koppelt handmatig |
| Januari (voor eerste termijn) | 0 betalingen verwacht, voortgang toont "Eerste termijn: februari" |
| Afgesloten jaar zonder bank | Theoretische fallback: full jaarbedrag |
| Dec-betaling geboekt op 1 jan | Verschijnt in "niet-gekoppeld" van volgend jaar, handmatig koppelen aan correct jaar |
| Termijnen = 1 (eenmalige betaling) | Werkt correct, UI toont "1 termijn" i.p.v. "betaalschema" |
| Ontkoppelen van betaling | Transactie gaat naar "niet-gekoppeld" sectie, GEEN automatische re-match |

## Scope

### In scope
- Nieuwe VA-tab op Aangifte met beschikking-invoer
- Automatische matching BD-transacties → VA IB/ZVW
- Handmatige koppeling/ontkoppeling
- Dashboard proration fix (bank-based of correct theoretisch)
- Verwijderen VA van Prive-tab
- Update bestaande tests die `update_ib_inputs` met VA-args aanroepen

### Niet in scope
- PDF-parsing van beschikkingen (handmatige invoer)
- Automatische herkenning herziene beschikking
- VA voor Box 3 (bestaat niet als product van BD)
- Notificatie bij gemiste termijnen

## Bestandswijzigingen

| Bestand | Wijziging |
|---|---|
| `database.py` | Migratie + 6 nieuwe functies + wijzig `update_ib_inputs` + wijzig `upsert_fiscale_params` + wijzig `_row_to_fiscale_params` |
| `models.py` | 4 nieuwe velden op `FiscaleParams` dataclass |
| `components/fiscal_utils.py` | `bereken_va_betaald_theoretisch()` + update `fetch_fiscal_data()` |
| `pages/aangifte.py` | Nieuwe tab + verwijder VA van Prive-tab |
| `pages/dashboard.py` | Correcte proration (bank-based + fallback) |
| `pages/bank.py` | Toon koppeling-label voor VA transacties |
| `tests/` | Tests voor matching, proration, edge cases + update bestaande `update_ib_inputs` tests |
