# Sprint A — Agenda met factuur-koppeling

**Datum**: 2026-05-02
**Status**: Revisie 2 — gebruiker-feedback verwerkt
**Doel**: Werkende `/agenda`-pagina met kalender, recurring patterns,
blocker-dagen, day-inspector, bevestigen-flow én **directe factuur-status
visualisatie** per werkdag-cel. Geen architectuur-refactor van bestaande
code; nieuwe code wordt zo geschreven dat een toekomstige Swift-port soepel
verloopt.

## Scope

### In scope (Sprint A)

1. **Datamodel**: `klant_recurring_patterns` + `blockers` tabellen + minimaal
   Dutch holiday algoritme + migratie 35/36 + back-up/rollback proef.
2. **Service-laag**: `services/agenda.py` met query + mutatie API. Pure
   nieuwe module — bestaande modules blijven ongewijzigd.
3. **`services/holidays.py`**: simpele lijst NL feestdagen, pure functies.
4. **/agenda pagina**: maandgrid + klant-pills + blocker-overlays + week-totalen
   + day-inspector + bevestigen-flow.
5. **Factuur-status koppeling** (zwaar): per werkdag-cel zichtbaar of de werkdag
   ongefactureerd / concept / verstuurd / verlopen / betaald is. Status komt uit
   `facturen.status` via JOIN op `werkdagen.factuurnummer`. Status-update op
   `/facturen` is direct zichtbaar bij volgende /agenda-render.
6. **Recurring-config UI**: per klant patroon-CRUD via uitbreiding bestaande
   klant-dialog.
7. **Urencriterium-projectie**: helper functie + tekst-strip op /agenda.
8. **`werkdag_form` prefill-API**: bestaande dialog krijgt optionele `prefill`
   kwarg voor bevestigen-flow.
9. **Sidebar**: `/agenda` als nieuw nav-item.

### Out of scope (Sprint A — bewust uitgesteld)

- **Architectuur-refactor**: geen `paths.py`, geen `domain/errors.py`,
  geen layering-rewrite van bestaande pages/components/database. Behouden zoals
  is. Nieuwe code volgt Swift-friendly stijl waar mogelijk (zie § Swift-friendly
  guidelines), maar niet ten koste van scope of bestaande patronen.
- Visuele refresh van bestaande pagina's (Sprint B)
- Dashboard-cards voor 6-weken/urencriterium (Sprint C)
- Polish van facturen/transacties/kosten/klanten/documenten (Sprint C)
- ANW/nachtdiensten via recurring patterns (handmatige werkdag blijft pad)
- Lustrum-logica voor Bevrijdingsdag / aparte handling Goede Vrijdag — alle 11
  NL feestdagen worden uniform getoond als feestdag-marker

## Swift-friendly guidelines voor nieuwe code

Toepassen op `services/agenda.py`, `services/holidays.py`, en nieuwe queries
in `database.py`. Niet retroactief op bestaande code.

1. **Frozen dataclasses voor view-objects**: `MaandView`, `DagView`,
   `WeekTotaal`, `Pattern`, `Blocker`, `Holiday`, `UrencriteriumState`. Mappen
   1:1 op Swift `struct`s. Use `@dataclass(frozen=True)`.
2. **Pure functies waar mogelijk**: holiday-algoritme, weekday-validatie,
   minuten-conversies. Geen DB- of UI-coupling.
3. **Typed signatures**: alle nieuwe functies hebben type hints op alle params
   en return-types. `Path | None` ipv `Optional[Path]` (PEP 604).
4. **Geen module-level mutable state**: geen globale caches in nieuwe code.
   Holiday-list lookup kan via `functools.lru_cache` op pure functions.
5. **SQL portable**: alleen SQLite-features die Swift's GRDB ook ondersteunt
   (geen Python-specifieke quirks). Gebruikt al door bestaande database.py.
6. **Errors als typed subclasses**: nieuwe `ConflictError(ValueError)` toevoegen
   aan `database.py` (naast bestaande `YearLockedError(ValueError)`). Patroon
   is identiek aan huidige conventie. Backward-compatible: alle catch-`ValueError`
   sites blijven werken.
7. **INTEGER minuten ipv REAL uren**: time-of-day als `int` (0-1440), portable
   naar Swift `Int` zonder Decimal-conversie.

Geen rewrite van bestaande modules. Alleen voor nieuwe agenda-laag toepassen.

## Datamodel

### Tabel: `klant_recurring_patterns`

```sql
CREATE TABLE IF NOT EXISTS klant_recurring_patterns (
    id INTEGER PRIMARY KEY,
    klant_id INTEGER NOT NULL REFERENCES klanten(id) ON DELETE CASCADE,
    weekdays TEXT NOT NULL,           -- ISO csv "1,3,5" (Ma=1..Zo=7)
    start_minuten INTEGER NOT NULL CHECK (start_minuten >= 0 AND start_minuten < 1440),
    eind_minuten INTEGER NOT NULL CHECK (eind_minuten > start_minuten AND eind_minuten <= 1440),
    code TEXT NOT NULL DEFAULT 'WERKDAG',  -- werkdag-code, bepaalt categorisatie + kleur
    activiteit TEXT DEFAULT 'Waarneming dagpraktijk',
    valid_from TEXT DEFAULT '',       -- '' = altijd, anders YYYY-MM-DD
    valid_until TEXT DEFAULT '',      -- '' = open einde, anders YYYY-MM-DD
    actief INTEGER NOT NULL DEFAULT 1 CHECK (actief IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_klant_patterns_klant
    ON klant_recurring_patterns(klant_id, actief);
```

**`code`-veld**: spiegelt `werkdagen.code` (bestaand), zodat bij `confirm_expected`
de werkdag automatisch de juiste code krijgt. Toegestane waarden: zelfde set als
`pages/werkdagen.py:_CODE_LABELS` (`WERKDAG`, `WEEKEND_DAG`, `ANW_AVOND`,
`ANW_NACHT`, `ANW_WEEKEND`, `ACHTERWACHT`, `CONGRES`, `OPLEIDING`, `OVERIG_ZAK`).
Default `WERKDAG` (dagpraktijk).

**Service-laag validatie** (in `add_pattern`/`update_pattern`):
- `weekdays`: niet leeg, alle waarden in {1,2,3,4,5,6,7}, geen duplicaten
- `start_minuten` < `eind_minuten`
- `valid_from` ≤ `valid_until` als beide gevuld
- `code` in de toegestane set

### Tabel: `blockers`

```sql
CREATE TABLE IF NOT EXISTS blockers (
    id INTEGER PRIMARY KEY,
    datum TEXT NOT NULL UNIQUE,                      -- één blocker per dag
    kind TEXT NOT NULL CHECK (kind IN ('vacation', 'sick', 'training')),
    label TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_blockers_datum ON blockers(datum);
```

**Service-laag conflict-regels**:
- Bestaande werkdag op datum: raise `ConflictError`
- Bestaande blocker op datum (via UNIQUE): raise `ConflictError`
- `kind='holiday'` geweigerd: holidays zijn computed, niet stored

### Migratie 35 + 36

```python
(35, "add_klant_recurring_patterns", [
    """CREATE TABLE IF NOT EXISTS klant_recurring_patterns (
        id INTEGER PRIMARY KEY,
        klant_id INTEGER NOT NULL REFERENCES klanten(id) ON DELETE CASCADE,
        weekdays TEXT NOT NULL,
        start_minuten INTEGER NOT NULL CHECK (start_minuten >= 0 AND start_minuten < 1440),
        eind_minuten INTEGER NOT NULL CHECK (eind_minuten > start_minuten AND eind_minuten <= 1440),
        code TEXT NOT NULL DEFAULT 'WERKDAG',
        activiteit TEXT DEFAULT 'Waarneming dagpraktijk',
        valid_from TEXT DEFAULT '',
        valid_until TEXT DEFAULT '',
        actief INTEGER NOT NULL DEFAULT 1 CHECK (actief IN (0, 1)))""",
    "CREATE INDEX IF NOT EXISTS idx_klant_patterns_klant ON klant_recurring_patterns(klant_id, actief)",
]),
(36, "add_blockers", [
    """CREATE TABLE IF NOT EXISTS blockers (
        id INTEGER PRIMARY KEY,
        datum TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL CHECK (kind IN ('vacation', 'sick', 'training')),
        label TEXT NOT NULL DEFAULT '')""",
    "CREATE INDEX IF NOT EXISTS idx_blockers_datum ON blockers(datum)",
]),
```

**Back-up + rollback proef** (verplicht vóór deploy):
1. `VACUUM INTO 'pre-35-backup.sqlite3'`
2. App start → migratie 35+36 toegepast
3. Verifieer: `SELECT version FROM schema_version` = 36, oude tabel-counts unchanged
4. Rollback: backup terug, `schema_version` = 34
5. Re-apply: idempotent, `schema_version` = 36

## Holiday-algoritme (simpel)

```python
# services/holidays.py — pure functions

@dataclass(frozen=True)
class Holiday:
    datum: date
    label: str

def easter_sunday(year: int) -> date:
    """Anonymous Gregorian computation."""

def dutch_holidays(year: int) -> list[Holiday]:
    """Standaardlijst Nederlandse feestdagen voor jaar:
      - Nieuwjaarsdag (1 jan)
      - Goede Vrijdag (Easter - 2)
      - Eerste Paasdag (Easter)
      - Tweede Paasdag (Easter + 1)
      - Koningsdag (27 april; 26 april als 27 zondag is)
      - Bevrijdingsdag (5 mei) — getoond als feestdag-marker
      - Hemelvaart (Easter + 39)
      - Eerste Pinksterdag (Easter + 49)
      - Tweede Pinksterdag (Easter + 50)
      - Eerste Kerstdag (25 dec)
      - Tweede Kerstdag (26 dec)
    Allemaal uniform getoond als feestdag in agenda. Geen lustrum-onderscheid.
    Geen 'suppresses_workday' flag — alle holidays verbergen verwachte
    entries (recurring patterns), gebruiker kan handmatig werkdag toevoegen
    indien hij wel werkt."""
```

**Uitleg**: het is voor één huisartswaarnemer, niet voor een algemene HR-tool.
Hij weet zelf welke feestdagen hij wel/niet werkt. Het algoritme markeert,
gebruiker beslist.

## Bron-van-waarheid

| Type | Opslag | Wanneer | UI |
|---|---|---|---|
| **Bevestigd** (werkdag) | `werkdagen` tabel | Verleden + heden + future-plans | Vol gekleurd, klant-color, **factuur-status-bar onderaan** |
| **Verwacht** | Géén DB-rij. Berekend at-query-time uit patterns minus werkdagen minus blockers minus holidays. | `datum > today` only | Dashed border, klant-color soft, géén status-bar |
| **Blocker (user)** | `blockers` tabel | User-toegevoegd | Vol blocker-color + kind-label |
| **Holiday** | Computed via `dutch_holidays()` | Per jaar | Holiday-marker (rood band), expected entries verborgen |

**Invariants**:
1. Verwachte entries verschijnen alleen voor `datum > today`.
2. Holiday verbergt verwachte entries op die datum.
3. Werkdag op holiday-datum is toegestaan (user kan op koningsdag werken).
4. `confirm_expected` op een pattern dat sinds page-load is verwijderd → `ConflictError`.

## Factuur-status koppeling — kern-feature

### Database-laag

Nieuwe query in `database.py`:

```python
async def get_werkdagen_met_factuur_status(
    db: Path, jaar: int, maand: int
) -> list[WerkdagMetStatus]:
    """JOIN werkdagen LEFT JOIN facturen ON werkdagen.factuurnummer = facturen.nummer.
    Returns werkdag-data + factuur.status (None, 'concept', 'verstuurd', 'betaald')
    + factuur.vervaldatum (voor 'verlopen' detectie).
    Filtert op datum jaar+maand."""

@dataclass(frozen=True)
class WerkdagMetStatus:
    id: int
    datum: str           # YYYY-MM-DD
    klant_id: int
    klant_naam: str
    uren: float
    bedrag: float        # uren * tarief + km * km_tarief
    factuurnummer: str   # '' = ongefactureerd
    factuur_status: str  # '' | 'concept' | 'verstuurd' | 'betaald'
    factuur_vervaldatum: str  # '' if no factuur
```

### Service-laag interpretatie

In `services/agenda.py`:

```python
def derive_werkdag_status_label(w: WerkdagMetStatus, today: date) -> str:
    """Returns one of:
        'ongefactureerd'   — w.factuurnummer == ''
        'concept'           — factuur status='concept'
        'verstuurd'         — factuur status='verstuurd' AND vervaldatum >= today
        'verlopen'          — factuur status='verstuurd' AND vervaldatum < today
        'betaald'           — factuur status='betaald'
    Pure function. Spiegelt huidige derive_status logica in
    components/transacties_helpers.py — niet identiek (andere domein) maar
    consistent qua filosofie."""
```

### UI-rendering (kleur-mapping)

| Status-label | Kleur (semantisch) | Indicator |
|---|---|---|
| `ongefactureerd` | grijs (`gray-500`) | zachte balk onder cel |
| `concept` | grijs-blauw (`slate-400`) | balk met dashed-border |
| `verstuurd` | blauw (`info`) | volle balk |
| `verlopen` | rood (`negative`) | volle balk + waarschuwingsicoon |
| `betaald` | groen (`positive`) | volle balk + check-icoon |

In `MonthGrid` cellen: per werkdag-pill een **status-bar onderaan** met de
juiste kleur. Bij meerdere werkdagen: meerdere bars naast elkaar (gestackt).

### Day-inspector — factuur-detail

In day-inspector per bevestigde werkdag-card:
- Status-chip met label + kleur (uit kleurmapping boven)
- Indien gefactureerd: factuurnummer als clickable link → `/facturen?factuurnummer=X`
- Indien betaald: betaal-datum tonen
- Indien verlopen: "X dagen te laat" + actie-knop "Stuur herinnering"
- Indien ongefactureerd: "Maak factuur" knop bij ≥1 ongefactureerde werkdag op dag

### Sync-gedrag

Single-user lokale app: geen pubsub nodig. /agenda render doet altijd verse
DB-query. Concrete flows:

1. User markeert factuur als betaald op `/facturen` → tab-switch naar `/agenda`
   → bij render zien werkdagen van die factuur direct groene status-bar.
2. User stuurt factuur (status concept→verstuurd) → /agenda toont blauwe bars.
3. User klikt "Bevestigen" op verwachte werkdag → werkdag toegevoegd
   (status='ongefactureerd', grijs) → bij volgende factuur-creatie via day-inspector
   wordt het concept (grijs-blauw).
4. Vervaldatum verstrijkt zonder betaling → `derive_werkdag_status_label`
   returnt 'verlopen' → /agenda toont rode bar **automatisch** (geen DB-update nodig,
   pure functie op `today`).

**Manueel refresh**: knop in topbar van /agenda voor expliciete re-render.
Voor MVP voldoende; geen websockets/auto-poll.

## /agenda — UI

### Sidebar

In `components/layout.py` toevoegen tussen Dashboard en Werkdagen:
```python
{'route': '/agenda', 'icon': 'calendar_month', 'label': 'Agenda'}
```

### Layout

```
@ui.page('/agenda')
async def agenda_page():
    create_layout('Agenda', '/agenda')
    # Top: maand-navigatie + Vandaag-knop + Refresh-knop + Nieuwe-werkdag-knop
    # Center-left: maandgrid (7 dagen + week-summary kolom)
    # Right: day-inspector card (sticky)
    # Bottom: urencriterium-projectie strip
```

### Maandgrid per dag-cel

- Dag-nummer (linksboven)
- Tot 3 entries (klant-pills): klant-naam-short + uren
- Bij >3: "+N meer"
- Status-bars-strip onderaan: per werkdag een gekleurde balk (uit factuur-status
  kleurmapping)
- Bij blocker: kind-label + user-label, geen werkdag-pills (blocker dekt cel)
- Bij holiday: holiday-marker + holiday-label, expected entries verborgen,
  bevestigde werkdagen wel zichtbaar (user werkt op koningsdag = toegestaan)
- Today: dunne accent-ring; Selected: dikkere ring; Other-month: gedimd; Weekend: subtiel

### Werkdag-categorisatie en kleuren

In plaats van per-klant-kleuren werkt Sprint A met **type-based coloring**: een
werkdag-pill kleurt op basis van wat voor soort dienst het is (dagpraktijk vs ANW
vs overig). Dat geeft een huisartswaarnemer in één blik overzicht: "wanneer doe ik
patiëntenzorg, wanneer ANW, wanneer iets anders".

**Pure functie** in `services/agenda.py`:

```python
def categorize_werkdag(code: str) -> Literal['dagpraktijk', 'anw', 'overig']:
    """Categorize a werkdag by code:
        'dagpraktijk' — code in ('WERKDAG', 'WEEKEND_DAG', '')
        'anw'         — code starts with 'ANW_' or in ('AVOND', 'NACHT')
        'overig'      — all other codes (ACHTERWACHT, CONGRES, OPLEIDING, OVERIG_ZAK)
    Pure function. Used for entry-pill coloring in MonthGrid + filtering."""
```

**Kleur-mapping** (Quasar semantic):

| Categorie | Kleur | CSS class |
|---|---|---|
| dagpraktijk | teal/primary (warme tint, primaire werk) | `wd-dagpraktijk` |
| anw | paars/secondary (out-of-hours, afwijkend) | `wd-anw` |
| overig | grijs/neutral | `wd-overig` |

Concrete hex-waarden via Quasar variables in `components/layout.py` —
geen hardcoded hex in pages. Verwachte entries (recurring) gebruiken
dezelfde kleurset maar dan met soft fill + dashed border.

**Klant-kleuren als optionele toekomstige feature**:
- Sprint A: alleen type-based.
- Latere sprint (optioneel, user-toggle): `klanten.color` kolom + UI-knop in
  Instellingen "Kleuren per klant gebruiken" → bij aan: pills kleuren op klant,
  type wordt subtieler (bv. via icon-badge). Buiten scope van Sprint A.

### Day-inspector states

| State | Trigger | UI |
|---|---|---|
| **Empty future** | Geen werkdag, geen blocker, geen pattern | "Geen registratie" + "Werkdag toevoegen" knop |
| **Empty past** | Geen werkdag op verleden-datum | "Geen registratie op deze dag" |
| **Blocker (user)** | `blockers.datum=X` | kind-icoon + label + "Verwijderen" |
| **Holiday** | Holiday op datum | holiday-icoon + label + "Werkdag plannen" knop |
| **Expected** | Future + pattern matched + geen werkdag | per entry: klant + tijden + bedrag + "Bevestigen" + "Aanpassen" |
| **Confirmed** | ≥1 werkdag op datum | per werkdag: klant + tijden + uren + km + bedrag + **factuur-status-chip** + factuur-link of "Maak factuur" knop |

### `werkdag_form` prefill-API

```python
async def open_werkdag_dialog(
    on_save=None,
    werkdag=None,                  # bestaande edit-mode
    prefill: dict | None = None,   # NEW
) -> None:
    """prefill keys (alle optioneel):
        datum: str (YYYY-MM-DD)
        klant_id: int
        start_minuten: int
        eind_minuten: int
        activiteit: str
        pattern_id: int  # voor confirm_expected referentie

    Als prefill+pattern_id: dialog roept services.agenda.confirm_expected aan
    bij Opslaan. Idempotent."""
```

### "Maak factuur" knop

In day-inspector footer bij ≥1 ongefactureerde werkdag op datum.
Klik → navigeer naar `/facturen` met query-param `?nieuw=1&werkdagen=<ids>`.
**Sessie 4 verifieert**: bestaande `/facturen` ondersteunt deze deep-link of
implementeer als kleine uitbreiding (1-2u extra).

### Urencriterium-projectie strip

```
Urencriterium 2026: 640u van 1.225u — verwacht jaar-eind: 1.310u ✓ Voldoet
```

Tekst-strip onder maandgrid. State uit `services.agenda.get_urencriterium_projectie`.
Stylized card-versie verschuift naar dashboard in Sprint C.

## Service-API (`services/agenda.py`)

```python
# Read
async def get_maand(db: Path, jaar: int, maand: int,
                    include_expected: bool = True) -> MaandView:
    """Returns dataclass: dagen[], week_totalen[6], blockers, holidays."""

async def get_dag(db: Path, datum: date,
                  include_expected: bool = True) -> DagView:
    """One-day view voor inspector-refresh."""

async def get_zes_weken_prognose(db: Path, vanaf: date) -> list[WeekTotaal]:
    """6 consecutive weeks vanaf de Maandag van vanaf-week."""

async def get_urencriterium_projectie(db: Path, jaar: int) -> UrencriteriumState:
    """Confirmed YTD + expected remainder + target (default 1225 of fiscale_params)."""

async def list_blockers(db: Path, vanaf: date, tot: date) -> list[Blocker]:
    """User-blockers + computed holidays gemerged."""

async def list_patterns_for_klant(db: Path, klant_id: int,
                                   include_inactive: bool = False) -> list[Pattern]:
    """Voor klant-dialog recurring-config UI."""

# Mutatie
async def confirm_expected(
    db: Path,
    pattern_id: int,
    datum: date,
    start_minuten: int | None = None,
    eind_minuten: int | None = None,
    activiteit: str | None = None,
) -> int:
    """Promote virtual expected entry → werkdag via add_werkdag.
    Idempotent: bestaande werkdag voor (klant_id, datum, pattern_id) → return existing.id.

    Raises:
      YearLockedError: datum in afgesloten jaar
      ConflictError:   pattern_id niet meer actief
      ValidationError: invalid tijden"""

async def add_blocker(db: Path, datum: date, kind: str, label: str = '') -> int:
    """Raises YearLockedError, ConflictError (werkdag exists, blocker exists)."""

async def delete_blocker(db: Path, blocker_id: int) -> None:
    """Raises YearLockedError if blocker.datum in afgesloten year."""

async def add_pattern(db: Path, klant_id: int, weekdays: list[int],
                      start_minuten: int, eind_minuten: int,
                      code: str = 'WERKDAG',
                      activiteit: str = 'Waarneming dagpraktijk') -> int:
    """NIET year-locked (patterns zijn projectie-data, geen fiscale feiten).
    Service-side validatie van weekdays + tijden + code."""

async def update_pattern(db: Path, pattern_id: int, **fields) -> None:
    """Idem validatie. NIET year-locked."""

async def delete_pattern(db: Path, pattern_id: int) -> None:
    """Soft delete: SET actief=0. NIET year-locked."""
```

**Errors**: `YearLockedError` blijft bestaan in `database.py`. Voeg
`ConflictError(ValueError)` en `ValidationError(ValueError)` toe in `database.py`
naast bestaande error — same pattern, geen nieuwe module.

## Tests

### Per laag

**`tests/test_holidays.py`** (nieuw):
- Easter golden vectors: 2020-04-12, 2025-04-20, 2026-04-05, 2030-04-21
- Koningsdag: 2025=26 april (zondag → zaterdag), 2026=27 april
- `dutch_holidays(2026)` returnt 11 entries met juiste datums

**`tests/test_agenda_service.py`** (nieuw):
- `test_get_maand_returns_correct_structure`
- `test_get_maand_excludes_blockers_from_expected`
- `test_get_maand_excludes_holidays_from_expected`
- `test_get_maand_returns_factuur_status_per_werkdag`  ← kern-feature test
- `test_get_dag_returns_single_day_view`
- `test_zes_weken_prognose_returns_6_weeks`
- `test_urencriterium_projectie_excludes_urennorm_zero`
- `test_urencriterium_projectie_uses_fiscale_params_target_if_present`
- `test_confirm_expected_creates_werkdag`
- `test_confirm_expected_idempotent_returns_existing_id`
- `test_confirm_expected_in_locked_year_raises_year_locked`
- `test_confirm_expected_on_deleted_pattern_raises_conflict`
- `test_add_blocker_in_locked_year_raises_year_locked`
- `test_add_blocker_on_existing_werkdag_raises_conflict`
- `test_add_blocker_on_existing_blocker_raises_conflict`
- `test_add_blocker_holiday_kind_raises_validation`
- `test_pattern_crud_add_list_update_delete`
- `test_pattern_invalid_weekdays_raises_validation`
- `test_pattern_eind_before_start_raises_validation`
- `test_pattern_not_year_locked_can_modify_in_locked_year`
- `test_categorize_werkdag_dagpraktijk_codes`
- `test_categorize_werkdag_anw_codes`
- `test_categorize_werkdag_overig_codes`
- `test_pattern_invalid_code_raises_validation`

**`tests/test_database_agenda_tables.py`** (nieuw):
- `test_klant_recurring_patterns_table_exists`
- `test_klant_recurring_patterns_cascade_on_klant_delete`
- `test_blockers_table_exists`
- `test_blockers_unique_datum_constraint`
- `test_blockers_kind_check_constraint`
- `test_migration_35_idempotent`
- `test_migration_36_idempotent`
- `test_get_werkdagen_met_factuur_status_returns_correct_status` ← kern-feature

**`tests/test_derive_werkdag_status.py`** (nieuw, pure function):
- `test_ongefactureerd_returns_correct_label`
- `test_concept_returns_concept`
- `test_verstuurd_with_future_vervaldatum_returns_verstuurd`
- `test_verstuurd_with_past_vervaldatum_returns_verlopen`
- `test_betaald_returns_betaald`

**`tests/test_agenda_page.py`** (nieuw, smoke):
- `test_agenda_page_renders_for_empty_db`
- `test_agenda_page_renders_with_data`
- `test_agenda_page_handles_locked_year_navigation`

**Tests blijven groen**: bestaande 1054+ tests zonder modificatie. `ConflictError`
en `ValidationError` toevoegen in `database.py` mag bestaande catch-`ValueError`
sites niet breken (zijn beide `ValueError`-subclass).

## Definition-of-done — command-driven

| Deliverable | Commando / scenario |
|---|---|
| Migratie 35 + 36 | Back-up/rollback proef stappen 1-5 succesvol. `pytest tests/test_database_agenda_tables.py -v` 8 cases groen. `schema_version=36`. |
| Holiday-algoritme | `pytest tests/test_holidays.py -v` 8 cases groen incl. Koningsdag-zondag-shift |
| `services/agenda.py` | 11 functies geïmplementeerd. `pytest tests/test_agenda_service.py -v` ≥20 cases groen. |
| `services/holidays.py` | Pure functions, geen DB/UI imports. |
| `derive_werkdag_status_label` | `pytest tests/test_derive_werkdag_status.py -v` 5 cases groen. |
| `werkdag_form` prefill | `prefill` kwarg accepted. Bij `pattern_id`: roept `confirm_expected` aan. Manuele rooktest: confirm → werkdag verschijnt. |
| /agenda pagina | `pytest tests/test_agenda_page.py -v` 3 smoke cases groen. Manuele rooktest: navigeer maanden, klik blocker, bevestig werkdag (idempotent), voeg blocker toe, **factuur-status zichtbaar per werkdag-cel**. |
| Sidebar | `/agenda` zichtbaar tussen Dashboard en Werkdagen. |
| Recurring-config | Patroon toevoegen in klant-dialog → verwachte entries op /agenda binnen 1 maand. Patroon verwijderen → entries verdwijnen. |
| **Factuur-koppeling** (kern) | Manuele rooktest scenario: (1) bevestig verwachte werkdag → grijze status-bar, (2) maak concept-factuur op /facturen → terug naar /agenda → grijs-blauwe bar, (3) markeer verstuurd → blauwe bar, (4) wacht tot na vervaldatum (of zet vervaldatum op gisteren) → rode bar, (5) markeer betaald → groene bar. |
| Native-mode rooktest | App start in pywebview. /agenda werkt visueel correct, geen console errors. Existing flows (factuur, mail, transacties, aangifte) ongewijzigd. |
| Tests groen totaal | `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v` → 0 failures (1054 + ~50 nieuwe ≈ 1104). |

## Risico's + mitigaties

1. **Pattern aangepast tussen render en confirm** — `confirm_expected(pattern_id)`
   checkt service-side dat pattern nog `actief=1` bestaat → `ConflictError`.
2. **Double-click op Bevestigen** — idempotent return existing werkdag.id als
   match (klant_id, datum, pattern_id).
3. **User-blocker op holiday** — toegestaan in DB, UI toont alleen holiday in cel.
4. **Pattern in afgesloten jaar** — bewuste keuze: NIET year-locked.
5. **"Verlopen" status zonder DB-update** — pure functie op `today` ↔ `vervaldatum`.
   Geen cron-job nodig. Bij elke /agenda-render automatisch up-to-date.
6. **Performance** — `get_maand` doet ~31 day-checks + 1 JOIN-query. Acceptabel
   zonder caching voor één gebruiker.
7. **Onbedekt risico**: gebruiker verwart expected omzet/uren met fiscale werkelijkheid.
   Mitigatie: tooltip op verwachte entries "Verwacht via vast rooster — nog te bevestigen";
   urencriterium-strip splitst expliciet `bevestigd` en `verwacht`.

## Stappenplan + sessies

| Sessie | Inhoud | Geschat AI-werk |
|---|---|---|
| 1 | Datamodel: migratie 35+36 + back-up/rollback proef + holidays.py + holiday-tests | 2-3u |
| 2 | Service-laag: services/agenda.py 11 functies + ConflictError/ValidationError + service-tests | 3-4u |
| 3 | UI A: maandgrid + week-summary + factuur-status-bars + day-inspector states + sidebar-update | 4-5u |
| 4 | UI B: werkdag_form prefill + bevestigen-flow + recurring-config in klant-dialog + "Maak factuur" deep-link | 3-4u |
| 5 | Validatie: factuur-status-koppeling end-to-end rooktest + alle tests groen + DoD-checklist + buffer | 2-3u |

**Totaal**: 5 sessies, 14-19u AI-werk, 3-5 dagen kalender met user-review tussen
elke sessie. Codex reviewt na elke sessie.

## Wat NIET in deze spec staat (bewust)

- Visuele refresh (Sprint B)
- Dashboard-cards 6-weken/urencriterium (Sprint C)
- Polish-pagina's (Sprint C)
- Aangifte/jaarafsluiting typografie (Sprint D)
- ANW/nachtdiensten via recurring patterns (handmatige werkdag blijft pad)
- Bevrijdingsdag lustrum-onderscheid (uniform marker)
- Goede Vrijdag onderscheid (uniform marker)
- iPad/iOS UX-overwegingen
- `paths.py`, `domain/errors.py`, `docs/schema.md` — geen architectuur-refactor
- Layering refactor van bestaande pages/components/database
- **Klant-specifieke kleuren** — type-based coloring volstaat in Sprint A;
  klant-kleur-toggle via Instellingen kan later toegevoegd worden indien gewenst

## Revisie-log

- **r0** (2026-05-02 ochtend): initiële draft
- **r1** (2026-05-02 middag): codex high-reasoning review — `YearLockedError`
  backcompat, blocker-invariant, Koningsdag-zondag, race-protection, etc.
- **r3** (2026-05-02 avond): tweede gebruiker-feedback ronde:
  - **Klant-kleuren geschrapt** — vervangen door **type-based coloring**:
    dagpraktijk / anw / overig via pure functie `categorize_werkdag(code)`.
    Klant-specifieke kleuren als optionele toekomstige feature (toggle in
    Instellingen + `klanten.color` kolom).
  - **`code`-veld toegevoegd aan `klant_recurring_patterns`** — patroon weet
    of het dagpraktijk of ANW is. Default `WERKDAG`. Confirm-flow propageert
    code naar werkdag.
  - 4 extra tests (categorize_werkdag + invalid code validatie).

- **r2** (2026-05-02 avond): gebruiker-feedback verwerkt:
  - **Architectuur-refactor geschrapt**: geen `paths.py`, geen `domain/errors.py`,
    geen `docs/schema.md`, geen layering-rewrite. Bestaande structuur ongewijzigd.
    Swift-portability als zachte richtlijn op nieuwe code (frozen dataclasses,
    pure functions, INTEGER minuten, typed signatures).
  - **Holiday-algoritme vereenvoudigd**: 11 NL feestdagen uniform getoond.
    Geen lustrum-logica voor Bevrijdingsdag, geen aparte handling Goede Vrijdag.
    Koningsdag-zondag-regel behouden (eenvoudig en correct).
  - **Factuur-status koppeling als kern-feature**: nieuwe sectie. Per werkdag-cel
    zichtbare status-bar (ongefactureerd / concept / verstuurd / verlopen / betaald).
    `derive_werkdag_status_label` als pure function. End-to-end rooktest scenario
    in DoD: bevestig werkdag → maak factuur → markeer verstuurd → vervaldatum
    verstrijkt → markeer betaald, alle stappen visueel reflected in /agenda.
  - **Sessies terug naar 5** (was 7): 14-19u AI-werk. Geen foundation-sessie nodig.
  - **`ConflictError` + `ValidationError`** als nieuwe `ValueError`-subclasses in
    bestaande `database.py` — zelfde patroon als bestaande `YearLockedError`,
    geen aparte `domain/errors.py` module.
