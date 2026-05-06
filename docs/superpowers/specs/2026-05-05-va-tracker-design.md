# Sprint I — VA-tracker design (Voorlopige Aanslag)

**Status**: LOCKED 2026-05-05 — awaiting user approval to invoke `writing-plans`. Synthese over 4 Codex-rondes (parallel-plan, spec-review, fresh-review, discussion).
**Replaces**: dashboard hero Card 3 "Belasting-reservering" (`pages/dashboard.py:631-707`)
**Helper to retire**: `services/dashboard.compute_belasting_reservering_progress` (+ 9 tests in `tests/test_dashboard_helpers.py`)

## Definition of Done (acceptatiecriteria)

- Pytest 1355 → ~1364 (zie §8 — 19 nieuwe, 9 verwijderd, 1 herschreven, netto +9) groen
- Geen f-string SQL in nieuwe queries; alle SQL via `?`-placeholders
- Year-lock: `update_ib_inputs` blijft `assert_year_writable`-protected; `/aangifte` save-handler vangt `YearLockedError` en toont notify; alle inputs (jaarbedragen + termijnen) zijn `disabled` wanneer `jaarafsluiting_status='definitief'`
- Cascade-discipline: nieuwe CSS (indien nodig) buiten `@layer components` als hij `.q-card` of `.q-btn` raakt; `.dashboard-hero-tile` is hergebruikt zonder wijziging
- `compute_va_tracker` is pure (geen NiceGUI imports), getest in isolatie
- Renderer in `components/dashboard_widgets.py` — geen mutatie van DB-state
- Breaking-change-doc (zie §4) — contract van `get_va_betalingen` wijzigt; alle callers worden in dezelfde sprint gemigreerd

## Probleem

Sprint H zette een "Belasting-reservering"-tile op `/dashboard`. Die helper extrapoleert `engine_jaarbelasting × dagen_elapsed / 365` om te tonen "hoeveel moet er nu op de spaarrekening staan". User-quote 2026-05-05: *"de berekeningen op dashboard slaan nergens op"*. Twee abstractie-lagen op elkaar (omzet-extrapolatie → IB+ZVW-prognose → proratie) maken het getal niet auditbaar; het staat los van wat de Belastingdienst werkelijk in rekening brengt.

## Doel

Vervang Card 3 met een **Voorlopige-Aanslag-tracker** die werkt op echte data:
- BD's beschikkingsbedrag IB en ZVW als **verplichting** (al editable in `/aangifte` Card 3)
- `database.get_va_betalingen(jaar)` als **betaald** uit `banktransacties` (al werkend, IBAN+kenmerk-detectie)
- Termijn-info uit `fiscale_params` (NIEUW, mig 40)

Tile toont per IB en ZVW: betaald, verplicht, resterend, termijnbedrag, aantal voldane termijnen. Plus één samenvattend hero-getal "Nog te betalen". Geen extrapolatie, geen prognose.

## Scope

**In v1** (Sprint I):
- Migratie 40 — 2 termijnen-velden in `fiscale_params`
- Helper `services.dashboard.compute_va_tracker` + dataclasses
- `get_va_betalingen` return-contract uitbreiden met `unmatched_betaald` + `unmatched_termijnen` (Codex pushback — was er al lokaal, alleen niet zichtbaar)
- Renderer `components.dashboard_widgets.render_va_tile`
- `pages/dashboard.py:631-707` vervanging
- `/aangifte` Card 3: termijnen-input + bank-summary herschrijven met IB/ZVW-split + unmatched-link "Controleer in transacties"
- 12 tests

**Uitgesteld** (Sprint J of later):
- PDF-parse van VA-beschikking
- Nieuwe `voorlopige_aanslag` table met audit-trail per beschikking-revisie
- Kenmerk-jaardigit gebruiken om jan-betalingen aan vorig-jaar toe te wijzen
- Splitsing IB-vs-ZVW termijnen-aantal in praktijk wanneer BD asymmetrische beschikking stuurt

**Niet doen**:
- Velden voor "VA reeds betaald handmatig" — dat zou een schaduwadministratie naast bankdata maken (Codex pushback). Alleen bankdata is bron van waarheid voor "betaald".

## 1. Schema diff (migratie 40)

```sql
ALTER TABLE fiscale_params
ADD COLUMN voorlopige_aanslag_ib_termijnen INTEGER NOT NULL DEFAULT 11
  CHECK (voorlopige_aanslag_ib_termijnen BETWEEN 1 AND 12);

ALTER TABLE fiscale_params
ADD COLUMN voorlopige_aanslag_zvw_termijnen INTEGER NOT NULL DEFAULT 11
  CHECK (voorlopige_aanslag_zvw_termijnen BETWEEN 1 AND 12);
```

**Default 11** — BD-standaard voor jaar-eerste beschikking is feb–dec = 11 termijnen. User kan in `/aangifte` overrulen naar 12 (jan-start) of korter (mid-year revisie). Bestaande rows krijgen 11.

**Twee velden, niet één gedeeld** — BD kan IB en ZVW met verschillende termijnen sturen (bijv. ZVW pas later opgelegd). De gedeelde-veld-aanname uit mijn v1 was broos.

**CHECK 1-12** — defensief tegen data-corruptie en tegen verkeerde `update_ib_inputs`-calls.

**Updates aan**:
- `models.FiscaleParams` dataclass — 2 nieuwe velden, `int = 11` default
- `database._row_to_fiscale_params` — coerce NULL → 11 (vergelijkbaar met andere kolommen)
- `database.upsert_fiscale_params` — kwargs accepteren, **expliciet in alle vier de paden meenemen**: (1) de `SELECT existing` query, (2) de INSERT-VALUES tuple, (3) de `ON CONFLICT ... SET excluded.<col>` clausule, (4) de preserve-fallback `existing['voorlopige_aanslag_ib_termijnen'] if existing else 11` (let op default 11, niet 0). Zonder dit kan `/instellingen` de termijnen onbedoeld terugzetten op default bij een upsert die de kwargs niet meegeeft.
- `database.update_ib_inputs` — 2 kwargs `voorlopige_aanslag_ib_termijnen` + `voorlopige_aanslag_zvw_termijnen` (consistent met bestaande `voorlopige_aanslag_betaald`/`_zvw` kwarg-naming), year-lock blijft staan
- Tests `test_db_queries.py` — migratie-test + round-trip + preserve-test

## 2. Tile-vorm — combined met interne IB/ZVW split

```
┌─────────────────────────────────────────┐
│ Voorlopige aanslag 2026             ⚠   │
│                                          │
│ Nog te betalen   €4.820                 │
│                                          │
│ IB    €3.600 / €9.600  ·  rest €6.000   │
│       3 v.d. 11   ± €873 p/m            │
│ ZVW   €2.180 / €3.000  ·  rest €820     │
│       2 v.d. 11   ± €273 p/m            │
│                                          │
│ Volgende termijn: 30 juni               │  ← conditioneel
│ Bankdata t/m 5 mei                      │
└─────────────────────────────────────────┘
```

**Hero-value** = `totaal_resterend` = (IB.verplicht − IB.betaald) + (ZVW.verplicht − ZVW.betaald), elk gecapt op 0 (geen negatieven bij overbetaald).

**Body-lines** per soort (IB, ZVW): `betaald / verplicht · rest €X` + `N v.d. M termijnen ± €Y p/m`. Niet eerst alles totaliseren — IB-vs-ZVW staat conceptueel los, beide hebben een eigen kenmerk-stroom in de bank, en de huisarts beoordeelt per BD-aanslag.

**Footer** "Bankdata t/m {datum}" — geeft een eerlijke indicatie hoe vers de detect is. Contract: `bankdata_tot_datum: date | None` = `max(banktransacties.datum)` over **negatieve** BD-rows in jaar-scope (consistent met `betaald`-filter; positieve correcties tellen niet voor versheid). `None` als er geen negatieve BD-rows zijn voor het jaar. Bij `None` wordt de regel weggelaten — `today` invullen zou liegen over data-versheid.

**Warning-icon** ⚠ wanneer `status == 'achter'` (achterstand > €1) of `summary.has_overbetaald` flag (totaal_resterend == 0 én een lijn heeft `betaald > verplicht`). `.is-tekort` modifier-class hergebruikt — semantiek wordt: "hier moet je naar kijken", niet meer "engine-prognose tekort".

**Volgende-termijn footer** (alleen tonen wanneer `status in ('achter', 'bij')` AND `totaal_resterend > 0`): toont één gecombineerde regel "Volgende termijn: {datum}" — laatste-dag-van-volgende-betaalmaand, gederiveerd uit `eerste_maand = 13 - termijnen` + max(betaalde_termijnen, expected_terms_elapsed) + 1. Per IB en ZVW apart toonbaar in v2 — voor v1 nemen we de eerstvolgende van de twee. Bij `status='voldaan'` of `'overbetaald'`-flag wordt deze regel weggelaten zodat de gebruiker geen stale "moet nog"-suggestie ziet.

**`geen_data`-fallback shape**: zelfde card-frame, hero "—", body-tekst "Geen beschikking of bankbetalingen voor {jaar}", click-doel `/aangifte`.

**`geen_beschikking`-fallback shape**: bankdata wel, beschikking-bedrag = 0. Body toont alleen `IB betaald €X · 3 termijnen` zonder rest-bedrag, hero "—", subtekst "Vul beschikking in op /aangifte". Voorkomt fictief "resterend"-getal.

**Overbetaald-rendering**: wanneer `summary.has_overbetaald == True` (= `totaal_resterend == 0` AND minstens één lijn heeft `betaald > verplicht`), toon naast de hero-value een kleine badge "overbetaald €X" met `X = sum(line.overbetaald for line in [ib, zvw])`. Geen per-line subsegments — line-first status-ordering (zie §3) lost de gemengde-staat-issue al op zonder visuele drukte.

## 3. Computation helper

`services/dashboard.py` — pure UI-vrij, twee frozen dataclasses + één compute-functie:

```python
@dataclass(frozen=True)
class VATrackLine:
    soort: Literal['IB', 'ZVW']
    verplicht: float           # = jaarbedrag uit fiscale_params (alias voor
                               # het misleidend genaamde voorlopige_aanslag_betaald
                               # resp. voorlopige_aanslag_zvw)
    betaald: float             # uit get_va_betalingen
    betaalde_termijnen: int    # uit get_va_betalingen
    totaal_termijnen: int      # uit fiscale_params
    termijnbedrag: float       # verplicht / totaal_termijnen
    resterend: float           # max(verplicht - betaald, 0)
    achterstand: float         # max(expected_terms - betaalde_termijnen, 0) × termijnbedrag
                               # Termijn-count × bedrag (NIET puur EUR-diff): BD rekent
                               # vervaltermijnen, niet EUR-totalen. Lump-sum-ahead met
                               # gemiste termijn moet zichtbaar blijven.
    overbetaald: float         # max(betaald - verplicht, 0)


@dataclass(frozen=True)
class VATrackSummary:
    ib: VATrackLine
    zvw: VATrackLine
    totaal_verplicht: float
    totaal_betaald: float
    totaal_resterend: float
    totaal_achterstand: float
    unmatched_betaald: float       # bankdata zonder bruikbaar kenmerk
    unmatched_termijnen: int
    has_bank_data: bool
    bankdata_tot_datum: date | None  # voor "Bankdata t/m {datum}" footer
    status: Literal['geen_data', 'geen_beschikking',
                    'bij', 'achter', 'voldaan']
    has_overbetaald: bool          # attribute (NIET status); zie line-first ordering


def compute_va_tracker(
    *,
    jaar: int,
    va_data: dict,             # uit get_va_betalingen — uitgebreid contract
    ib_verplicht: float,       # fp.voorlopige_aanslag_betaald
    zvw_verplicht: float,      # fp.voorlopige_aanslag_zvw
    ib_termijnen: int = 11,    # fp.voorlopige_aanslag_ib_termijnen
    zvw_termijnen: int = 11,   # fp.voorlopige_aanslag_zvw_termijnen
    today: date,
) -> VATrackSummary:
    ...
```

**Verwachte-termijnen formule** (correct voor zowel 11- als 12-termijnen):

```python
def _expected_terms_elapsed(termijnen: int, today_ym: tuple[int, int],
                             jaar: int) -> int:
    """Aantal termijnen dat tot vandaag betaald had moeten zijn.

    Convention: aantal termijnen N impliceert eerste-termijn-maand =
    13 - N (d.w.z. N=11 → feb-start, N=12 → jan-start). Dit klopt voor
    BD's gebruikelijke jaareerste-beschikking (feb-dec=11) en
    rondom-jaargrens-beschikking (jan-dec=12).
    """
    if today_ym[0] < jaar:
        return 0
    if today_ym[0] > jaar:
        return termijnen
    eerste_maand = 13 - termijnen
    return min(termijnen, max(0, today_ym[1] - eerste_maand + 1))
```

> **Convention-disclaimer**: `eerste_maand = 13 - termijnen` is *onze* heuristiek, geen BD-bron-waarheid. BD geeft de eerste-termijn-datum impliciet via de beschikking; wij leiden 'm af uit het aantal-termijnen-veld dat de user invult. In zeldzame BD-revisies (mid-year) klopt deze afleiding niet. Mitigatie: aanvaard de afwijking voor v1; user kan termijnen-aantal handmatig overtypen om de afleiding te corrigeren. Sprint J kan een `eerste_termijn_maand` veld toevoegen indien dit pijn doet.

Codex's eerdere `today.month` is correct voor 12 termijnen maar fout voor 11 (zou in januari 1 termijn verwachten terwijl die pas in februari komt). Mijn `13 - termijnen` afleidt eerste-maand consistent.

**Status-rangschikking — line-first ordering (Codex round-3 catch)**:

```
not has_input and not has_bank_data                       → 'geen_data'
not has_input and has_bank_data                           → 'geen_beschikking'
any(line.achterstand > 1 for line in [ib, zvw])           → 'achter'   ← line-first
totaal_resterend == 0 and totaal_verplicht > 0            → 'voldaan'  ← incl overbetaling
otherwise                                                 → 'bij'
```

`has_overbetaald` is een aparte attribute (NIET een status), gezet wanneer `any(line.overbetaald > 0)` — guard `totaal_resterend == 0` is bewust **gedropt** zodat asymmetrische gemengde staten (IB overbetaald €100 + ZVW achter €600) zichtbaar blijven (line-first principe). Renderer-conditional bepaalt of de overbetaald-badge getoond wordt: alleen wanneer `status == 'voldaan' AND has_overbetaald` (anders zou een gemengde 'achter'-staat een verwarrende "overbetaald"-badge naast warning-icon krijgen). Voor 'achter'-status wordt has_overbetaald wel geëxporteerd voor diagnostiek/logging maar niet visueel gerenderd v1.

Tolerantie €1 vermijdt false positives door bank-rounding.

## 4. `get_va_betalingen` contract-uitbreiding (BREAKING)

```python
# huidig (database.py:2792):
{ib_betaald, ib_termijnen, zvw_betaald, zvw_termijnen, totaal_betaald, has_bank_data}
# waarbij totaal_betaald = ib_betaald + zvw_betaald + unmatched (unmatched stil meegeteld)

# nieuw (Sprint I):
{ib_betaald, ib_termijnen, zvw_betaald, zvw_termijnen,
 unmatched_betaald, unmatched_termijnen,    # NIEUW — was lokaal, nu zichtbaar
 totaal_betaald, has_bank_data,             # SEMANTIEK GEWIJZIGD: zie hieronder
 bankdata_tot_datum: date | None}           # NIEUW — voor "Bankdata t/m" footer
```

**Breaking semantic change**: `totaal_betaald = ib_betaald + zvw_betaald` (zonder unmatched). De huidige helper sumt unmatched in `totaal_betaald` op (regel `'totaal_betaald': round(ib_betaald + zvw_betaald + unmatched, 2)`). Reden voor wijziging: de ratio "betaald/verplicht" wordt misleidend opgedreven door BD-correcties met onleesbaar kenmerk.

**Caller-migratie binnen dezelfde sprint** (geen achtergebleven callers):
- `pages/dashboard.py:_compute_ib_estimate` — gebruikt `va_data['totaal_betaald']` voor de oude Belasting-reservering tile (lijnen 639-643). Die hele path verdwijnt in T2.1 (helper-deletion).
- `tests/test_db_queries.py:test_get_va_betalingen_no_kenmerk_fallback` — verifieert huidige inclusie van unmatched in totaal_betaald. Wordt herschreven naar nieuwe contract (T1.2).
- `pages/aangifte.py` toont gesplitste IB/ZVW + unmatched apart (zie §6); leest niet meer `totaal_betaald`.

Caller (de tile) toont `unmatched_betaald` apart als sub-line wanneer > 0. `/aangifte`-blok krijgt expliciete "Niet toegewezen: €X"-regel.

## 5. Edge cases

| Case | Gedrag |
|---|---|
| Geen beschikking + geen bankdata | `status='geen_data'`, hero "—", click → `/aangifte` |
| Bankdata zonder beschikking | `status='geen_beschikking'`, body toont alleen IB/ZVW betaald + termijnen, geen resterend, click → `/aangifte` |
| Beschikking zonder bankdata (vroeg in jaar) | Normale tile, IB en ZVW lines met `betaald €0`, resterend = verplicht, achterstand = `verwacht_betaald` (kan al meteen tekort flaggen in feb) |
| Betaald > verplicht | `status='overbetaald'`, `resterend=0`, body sub-line "overbetaald €X" |
| Closed year (jaar < huidig) | `expected_terms_elapsed` returns `termijnen` (volle jaar). Mutatie-paden vallen onder bestaande `assert_year_writable` |
| Future year (jaar > huidig) | Dashboard rendert geen data voor toekomstige jaren — bestaand gedrag, geen tile-specifieke logica |
| Jan-betaling met VA-vorig-jaar kenmerk | Wordt door `get_va_betalingen` datum-filter aan huidig jaar gekoppeld. **v1 accepteert dit zonder waarschuwing**; gebruiker kan via /transacties handmatig kenmerk inspecteren. Sprint J kan kenmerk-jaardigit-inspectie + heuristische waarschuwing samen toevoegen |
| Positieve BD-banktransactie (correctie/teruggave) | `get_va_betalingen` filtert op `bedrag < 0`. Een terugbetaling van BD aan user (positieve tx) wordt genegeerd — `betaald` blijft de uitgaande som. Voor `'overbetaald'`-status is dit een gat: een correctie kan teruggekomen zijn maar wordt niet afgetrokken. v1 accepteert; documenteer in §9. Sprint J kan positives meetellen of als aparte "ontvangen retours"-regel tonen |
| `aantal_termijnen=0` data-corruptie | `clamp_terms` in helper zet naar `max(1, n)`, CHECK in DB voorkomt 0 nieuw te plaatsen |

## 6. `/aangifte` wijzigingen

Card 3 ("Voorlopige aanslagen") krijgt:

**(a) Termijnen-inputs** naast de bestaande IB/ZVW jaarbedragen:

```
VA Inkomstenbelasting (jaarbedrag)    [€ 9600]
   Aantal termijnen IB                 [11]

VA Zorgverzekeringswet (jaarbedrag)   [€ 3000]
   Aantal termijnen ZVW                [11]
```

`ui.number(min=1, max=12, step=1, format='%d')` voor de twee termijnen-velden. Save via dezelfde "Opslaan"-button die `update_ib_inputs` aanroept (uitgebreid met 2 kwargs).

**(b) Bank-summary herschrijven** — vervang huidige tekst "Banktotaal = alle betalingen aan Belastingdienst (IB + ZVW + evt. definitieve aanslagen)" door gesplitste regel:

```
Bankbetalingen aan Belastingdienst (t/m 5 mei)
  IB:        €3.600 betaald · 3 termijnen · rest €6.000
  ZVW:       €2.180 betaald · 2 termijnen · rest €820
  Niet toegewezen:  €0
```

"Niet toegewezen"-regel verschijnt alleen als `unmatched_betaald > 0`.

**(c) Bekijk-BD-betalingen-link bij unmatched** — wanneer `va_data['unmatched_betaald'] > 0`, toon onder de bank-summary één button "Controleer in transacties" → `ui.navigate.to(f'/transacties?search=NL86INGB0002445588&jaar={jaar}')`. Geen knop bij unmatched=0. Voorkomt dat user moet weten waar BD-IBAN vandaan komt.

> **(d) Januari-waarschuwing — niet in v1**. Round-4 cut: helemaal verplaatst naar Sprint J. Reden: (i) trigger-conditie blijft fragile zonder kenmerk-jaardigit-detect, (ii) na contract-change zou `totaal_betaald` excl. unmatched een vorig-jaar valselijk als onderbetaald kunnen flaggen, (iii) gebruiker noemde dit niet als pijnpunt — was Codex round-2 voorstel zonder hard signaal. Sprint J kan de echte fix (kenmerk-jaardigit) en de waarschuwing samen opleveren.

## 7. UI-wiring

`pages/dashboard.py:631-707` wordt:

```python
# Card 3: Voorlopige aanslag (Sprint I — vervangt Belasting-reservering)
va_summary = compute_va_tracker(
    jaar=jaar,
    va_data=va_data,
    ib_verplicht=fp.voorlopige_aanslag_betaald if fp else 0,
    zvw_verplicht=fp.voorlopige_aanslag_zvw if fp else 0,
    ib_termijnen=getattr(fp, 'voorlopige_aanslag_ib_termijnen', 11)
                 if fp else 11,
    zvw_termijnen=getattr(fp, 'voorlopige_aanslag_zvw_termijnen', 11)
                  if fp else 11,
    today=date.today(),
)
render_va_tile(va_summary, jaar=jaar)
```

`render_va_tile` zit in `components/dashboard_widgets.py` (consistent met andere Sprint H tiles). Renderer:
- Card-frame met `.dashboard-hero-tile` + (`.is-tekort` als status ∈ {achter, overbetaald})
- Click-handler op de hele card: `ui.navigate.to(f'/aangifte?jaar={jaar}')` — query-param wordt door bestaande `/aangifte` opgepakt voor jaar-selectie

Het oude `_has_va_data(fp, va_data)` helper kan blijven (wordt door andere checks in dashboard nog gebruikt) of worden vervangen door `va_summary.status != 'geen_data'`. Niet schoonvegen tot Sprint J — out of scope.

## 8. Tests

Baseline 1355 + 19 nieuw − 9 verwijderd − 1 herschreven = **netto +9 → ~1364**.

**`tests/test_va_tracker.py`** (NIEUW, 12 tests):
1. `test_compute_va_tracker_geen_data` — alle nullen, has_bank_data=False → status='geen_data'
2. `test_compute_va_tracker_geen_beschikking` — bankdata wel, verplicht=0 → status='geen_beschikking', resterend=0
3. `test_compute_va_tracker_bij_op_koers` — mei, 11 termijnen, 4 betaald op pace → status='bij', achterstand=0
4. `test_compute_va_tracker_achter_with_amount` — mei, 11 termijnen, 2 betaald → status='achter', achterstand=verwacht-betaald
5. `test_compute_va_tracker_voldaan` — betaald == verplicht → status='voldaan', has_overbetaald=False
6. `test_compute_va_tracker_voldaan_with_overbetaald_attribute` — IB overbetaald maar samen voldaan → status='voldaan', has_overbetaald=True
7. `test_compute_va_tracker_line_first_status_ordering` — IB overbetaald +€100 EN ZVW achter +€50 → status='achter' (NIET 'voldaan' of 'overbetaald'), has_overbetaald=True (Codex round-3 critical bug-fix)
8. `test_compute_va_tracker_closed_year_voldaan` — jaar<huidig + betaald=verplicht → 'voldaan'
9. `test_compute_va_tracker_eerste_termijn_maand_11_termijnen` — januari, 11 termijnen → expected_terms=0 (feb-start)
10. `test_compute_va_tracker_eerste_termijn_maand_12_termijnen` — januari, 12 termijnen → expected_terms=1 (jan-start)
11. `test_compute_va_tracker_volgende_termijn_alleen_bij_open_resterend` — status='voldaan' → volgende_termijn_datum=None; status='bij' + resterend>0 → datum gevuld; status='bij' + resterend=0 → None (Codex discussion D-1)
12. `test_compute_va_tracker_unmatched_in_summary_not_in_totaal` — va_data.unmatched_betaald=€120 → summary.unmatched_betaald=€120, totaal_betaald excludeert deze €120

**`tests/test_db_queries.py`** (extend, 7 tests):
13. `test_migratie_40_va_termijnen_default_11` — bestaande rows krijgen 11; CHECK weigert 0 en 13
14. `test_update_ib_inputs_preserves_va_termijnen` — update zonder kwargs laat termijnen ongemoeid
15. `test_upsert_fiscale_params_preserves_va_termijnen` — upsert zonder termijnen-kwargs leest existing en behoudt waarde
16. `test_get_va_betalingen_excludes_unmatched_from_totaal_betaald` — kenmerk te kort + dot-separator + niet-numeriek → unmatched > 0, totaal_betaald = ib + zvw alleen (BREAKING contract change)
17. `test_get_va_betalingen_bankdata_tot_datum_negative_only` — positief BD-tx negeren voor zowel `betaald` als `bankdata_tot_datum`; max van negatieve rows alleen
18. `test_get_va_betalingen_bankdata_tot_datum_none_when_no_negative_rows` — geen negatieve BD-rijen → None
19. `test_get_va_betalingen_unmatched_kenmerk_variants` — 3 verschillende edge-kenmerken (te kort, niet-numeriek, ongeldig BSN) → unmatched_termijnen=3, unmatched_betaald som-correct

**`tests/test_dashboard.py`** (extend) — niet uitgebreid voor v1; smoke-test in T1.4 task verifieert dat tile rendert. Geen uitgebreide UI-tests want NiceGUI-DOM testing is broos en levert lage signaal/ruis.

**Verwijderen** (9 tests in `tests/test_dashboard_helpers.py` rond `compute_belasting_reservering_progress`):
- `test_op_koers_when_va_matches_prorated_expected`
- `test_tekort_when_va_significantly_below_prorated`
- `test_overreservering_when_va_significantly_above_prorated`
- `test_january_first_day_negligible_expected`
- `test_exact_threshold_tekort_boundary`
- `test_exact_threshold_overreservering_boundary`
- `test_january_full_month_partial_year`
- `test_leap_year_uses_366_days`
- `test_december_full_year_check`

**Aanpassen** (1 bestaande test in `test_db_queries.py`):
- `test_get_va_betalingen_no_kenmerk_fallback` — herschrijven naar nieuwe contract: no-kenmerk valt in `unmatched_betaald`, niet stil in `totaal_betaald`

## 9. Risks

**Risk 1 — Veldnaam `voorlopige_aanslag_betaald` is misleidend**
Het veld bevat het BD-beschikkingsbedrag (verplichting), niet wat is betaald. Aliasen in helper-parameter (`ib_verplicht`) en codecommentaar geeft duidelijkheid zonder breaking rename. Mitigatie: comment in `models.FiscaleParams` + parameter-naming in `compute_va_tracker`. Sprint K kan field renamen met migratie.

**Risk 2 — Kenmerk-classificatie is positioneel**
`get_va_betalingen` splitst IB/ZVW via positie [10:12] van het betalingskenmerk. Bank-tx zonder bruikbaar kenmerk vallen in `unmatched`. Mitigatie: unmatched zichtbaar maken (in tile-summary én in `/aangifte`-bank-summary). Voorkomt stille onderrapportage van betaald.

**Risk 3 — Januari-betaling vorig-jaar kenmerk**
VA-2025 betaling in januari 2026 wordt door datum-filter aan 2026 gekoppeld. v1 lost dit niet op en heeft expliciet GEEN heuristische waarschuwing (round-4 cut). Gebruiker controleert handmatig via /transacties als bedrag verdacht voorkomt. Sprint J kan kenmerk-jaardigit-inspectie + heuristische waarschuwing samen toevoegen.

**Risk 4 — Positieve BD-banktransacties (correcties/teruggaves) ongezien**
`get_va_betalingen` filtert hard op `bedrag < 0`. Een correctie/teruggave (BD stort terug aan user) is een positief bedrag en wordt genegeerd. Effect: `betaald` blijft de bruto-uitgaande som, dus een terugbetaling kan ten onrechte als `overbetaald` blijven staan. v1 accepteert; user kan via `/transacties` zien wat er werkelijk is teruggekomen. Sprint J kan positives expliciet als "BD-retour"-regel tonen of in `betaald` verrekenen.

## 10. Implementatie-taken (Sprint H process: subagent-driven, opus implementer + Codex per task)

| Task | Inhoud | Geschat |
|---|---|---|
| **T1.1** | Migratie 40 + `models.FiscaleParams` velden + `_row_to_fiscale_params` + `upsert_fiscale_params` (alle 4 paden) + `update_ib_inputs` kwargs + rename-comment in `models.FiscaleParams` (round-2 nice-to-have) + 3 schema-tests (#13-15) | 1 commit |
| **T1.2** | `get_va_betalingen` BREAKING contract: + `unmatched_betaald` + `unmatched_termijnen` + `bankdata_tot_datum: date \| None` (negatief-only) + `totaal_betaald` excludeert unmatched + 4 tests (#16-19) + herschrijf `test_get_va_betalingen_no_kenmerk_fallback` | 1 commit |
| **T1.3** | `compute_va_tracker` helper + `VATrackLine` (met `@property overbetaald`) + `VATrackSummary` + line-first status-ordering + volgende-termijn-datum derivatie + 12 helper-tests (#1-12) | 1 commit |
| **T1.4** | `render_va_tile` in `components/dashboard_widgets.py` + integration `pages/dashboard.py:631-707` + `/aangifte` Card 3 termijn-inputs + bank-summary herschrijven met "Controleer in transacties"-link bij unmatched + rollback-fix voor termijn-inputs op YearLockedError + smoke-test op render | 1 commit |
| **T2.1** | Verwijder `compute_belasting_reservering_progress` + **9** oude tests in `tests/test_dashboard_helpers.py` (round-3 catch — was 4 in mijn fout) + opruim referenties (`_compute_ib_estimate` va_betaald-pad) + documenteer kenmerk-jaar-mismatch + veldnaam-bug + positieve BD-tx gat in `CLAUDE.md` § Domeinkennis fiscaal + pytest 0-failures verifiëren | 1 commit |

**5 commits over 2 dagen** (round-3 cut van 7→5). Pytest 1355 → ~1364 (19 nieuw, 9 verwijderd, 1 herschreven, netto +9).

## 11. Open vragen

Geen — alle ontwerpkeuzes zijn besloten in synthese met Codex (vier rondes: parallel-plan + spec-review + fresh-review + discussion).

## 11b. Codex-review-trail (audit-trail)

- **Round 1** (parallel-plan, 2026-05-05): Claude + Codex schreven onafhankelijke v1's. Mutual critique leverde op: 2-velden-schema (Codex), `VATrackLine`/`VATrackSummary` shape (Codex), `geen_beschikking`-status (Codex), unmatched-zichtbaar (Codex), veldnaam-bug catched (Codex), default 11 (Claude), `13-N`-formule (Claude), `/aangifte` click-target (Codex over `/transacties`).
- **Round 2** (spec-review, 2026-05-05): Codex Approve-with-changes op v1-spec. 4 critical fixes geïntegreerd: breaking-`totaal_betaald` expliciet, `bankdata_tot_datum` ambiguïteit weg, `upsert_fiscale_params` preserve-pad expliciet (4 paden), jan-warning trigger getightened. Plus 6 should-fixes en 2 nice-to-have.
- **Round 3** (fresh-review, 2026-05-05): Codex Approve-with-changes. 5 round-3 bugs catched waaronder **status-ranking gemengde-staat-bug** (totaal-eerst maskeerde IB-overbetaald + ZVW-achter situatie) — line-first ordering ingevoerd. 3 features (volgende-termijn ADD, action-inbox-row DEFER, BD-betalingen-link ADD-minimal). 7 overengineering-cuts: `VATrackLine.overbetaald` → property, per-line overbetaald rendering kill, jan-warning kill (Sprint J), 28→19 tests, 7→5 commits.
- **Round 4** (discussion, 2026-05-05): Codex's 4 directe vragen beantwoord met agreement op alle 4 (defer action-inbox, kill jan-warning, 19 tests, geen extra blockers). 2 D-nuances toegevoegd: volgende-termijn alleen bij `status ∈ {achter, bij}` AND `totaal_resterend > 0`, en unmatched buiten dashboard-tile (alleen in /aangifte). Eindscore Codex: **"Lockwaardig"**.
- **Round 5** (post-implementation): Codex per-task review tijdens subagent-driven implementatie, plus post-merge audit op de cumulatieve diff. Volgens Sprint H process.

## 12. Out of scope (expliciet)

- PDF-parse van VA-beschikking — uitstel naar Sprint J indien user blijkt het missen
- Nieuwe `voorlopige_aanslag` table met audit-trail per beschikkingsrevisie — Sprint J
- Velden voor "VA reeds betaald handmatig" — opzettelijk niet gedaan (bankdata = single source of truth)
- Renaming `voorlopige_aanslag_betaald` → `voorlopige_aanslag_ib_jaarbedrag` — Sprint K (breaking, separate effort)
- Kenmerk-jaardigit-inspectie voor jan-betalingen vorig-jaar herverdeling — Sprint J
- **Januari-waarschuwing in /aangifte** (round-4 cut) — Sprint J samen met andere VA-features; voorkomt unmatched-bug onder nieuwe contract en bespaart 3 tests
- **VA-achterstand action-inbox row** (round-4 cut) — Sprint J; tile-warning + click-naar-/aangifte dekt v1 voldoende
- **Per-line overbetaald rendering** (round-3 cut) — line-first status-ordering lost gemengde-staat al op zonder extra UI-drukte
- Per-soort volgende-termijn-datum (IB en ZVW apart) — v1 toont gecombineerd, splitsen indien gebruikersfeedback
- Positieve BD-banktransacties (correcties/teruggaves) als aparte regel — Sprint J of accepteer
- Disabled-input UI-test bij locked-jaar (round-3 nice-to-have was overkill — DB-laag year-lock-tests dekken het)
