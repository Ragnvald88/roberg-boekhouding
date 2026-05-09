# Agenda Sprint 1 — Bug-fix + klikbare pills + context-menu

**Status**: SHIPPED 2026-05-09 (commit `617798c`) — pytest 1485 → 1516, 4 codex-rondes op spec, 4 codex-rondes op plan, per-task spec+code-quality reviews via subagent-driven-development.
**Datum**: 2026-05-08

## Aanleiding

`/agenda` heeft drie concrete tekortkomingen gemeld door de gebruiker:

1. **Bug**: `Nieuwe werkdag`-knop in toolbar doet niets bij klik.
2. Werkdag-pills in agenda-cellen zijn niet interactief — gebruiker moet via Day-Inspector aan rechterkant naar acties.
3. Geen right-click context-menu voor snelle delete/copy/edit.

Gebruiker (huisartswaarnemer, single-user lokale app) wil de pagina "extreem nuttig" maken zonder over-engineering.

## Scope (Sprint 1)

**In:**
- A. Bug-fix `Nieuwe werkdag` knop wiren
- B. Confirmed pill: left-click opent edit-dialog
- C. Confirmed pill: right-click opent context-menu (Bewerken / Dupliceren / Verwijderen / Naar facturen / Ontkoppel)
- D. Pill hover-tooltip: klant volledige naam + tijden + uren + bedrag + factuurstatus
- E. Nieuwe DB-helper `duplicate_werkdag(werkdag_id, target_datum)` voor "Dupliceren" actie
- F. Nieuwe `delete_werkdag` UI-flow vanuit context-menu (helper bestaat al, alleen UI-binding)

**Out (Sprint 2 of later):**
- "Wat nog te factureren per klant" CTA — codex-suggestie, deferred
- Diepere urencriterium-projectie ("nog X uur nodig", "verwachte eindstand") — deferred
- Week-view alternatief naast maand-view — deferred
- Drag/drop tussen dagen — raakt year-lock + blockers + factuurstatus, expliciet uit Sprint 1
- Factuur-deeplink (`?nummer=...` highlight in /facturen) — buiten scope; "Naar facturen" navigeert wel zoals nu
- Conflict-indicators (vakantie + werkdag overlap, oude ongefactureerde) — Sprint 2
- Right-click op expected pill (recurring) — gebruikt bestaande Day-Inspector flow

## Decision points + rationale

### A. Bug-fix `Nieuwe werkdag`

**Probleem**: `pages/agenda.py:485` maakt `refs['new_btn']` aan met `.props('color=primary')` maar krijgt nooit `.on_click(...)` (vergelijk regels 645-648 waar prev/next/today/refresh wél gewired worden).

**Fix**: één regel wiring direct naast de andere:

```python
refs['new_btn'].on_click(
    lambda: ui.timer(0,
        lambda: handle_add_werkdag(state['selected']), once=True))
```

`handle_add_werkdag(state['selected'])` is correct — zelfde signature die de Day-Inspector gebruikt voor de empty-state knop. Default datum = momenteel geselecteerde dag.

### B. Pill left-click — open edit-dialog

**Alleen op confirmed pills**. Expected pills (recurring) hebben geen `werkdag_id` en blijven via cell-click → Day-Inspector verlopen (huidig gedrag, niet wijzigen).

**stopPropagation verplicht** — pill zit binnen clickable cel. Zonder stop krijgt user *zowel* edit-dialog *als* day-select+rerender. NiceGUI 3.8.0 pattern:

```python
pill.on('click',
    handler=lambda _e=None, wid=w.id: edit_werkdag(wid),
    js_handler='(e) => { e.stopPropagation(); emit(); }')
```

`WerkdagPill` (uit `services/agenda.py:399`) bevat geen volledig Werkdag-model — `open_werkdag_dialog(werkdag=...)` verwacht de zware shape uit `/werkdagen`. Daarom: nieuwe DB-helper `get_werkdag_by_id(db, werkdag_id) → Werkdag | None` in `database.py` (codex pushback). Helper hergebruikt door duplicate-flow + delete-flow voor consistente handlers.

### C. Pill right-click — context-menu

NiceGUI native API: `ui.context_menu()` binnen het pill-element. Quasar `QMenu` met `context-menu=True` + `touch-position=True` — werkt op WebKit/pywebview (codex bevestigt + verifieerde NiceGUI 3.8.0 source). Geen raw `@contextmenu` JS nodig.

**Pure helper `_pill_context_actions(werkdag) → list[str]`** retourneert stabiele action-IDs (codex pushback: keep helper UI-vrij). Renderer mapt ID → label/icon/callback:

| Action ID | Label | Zichtbaar wanneer |
|---|---|---|
| `edit` | Bewerken | Altijd |
| `duplicate` | Dupliceren | Altijd |
| `delete` | Verwijderen | `factuurnummer == ''` |
| `naar_facturen` | Naar facturen | `factuur_id is not None` |
| `ontkoppel` | Ontkoppel factuur | `factuurnummer != '' AND (factuur_id is None OR factuur_status == 'concept')` |

**Boekhoudkundige consistentie**: ontkoppel niet beschikbaar bij `verstuurd/verlopen/betaald` — alleen `concept` of orphan-link (factuurnummer zonder factuur_id). Codex pushback bevestigd.

**`status_label` ≠ `factuur_status`** (codex finding 5): "verlopen" is computed uit `factuur_status='verstuurd'` + vervaldatum. Helper input is de DB-`factuur_status` string + `factuur_id`. Tests gebruiken `factuur_status='verstuurd'` voor verlopen-scenario, niet de literal `'verlopen'`.

**Right-click op expected pill** — geen menu in Sprint 1. User kan via Day-Inspector "Bevestigen"/"Aanpassen". KISS.

### D. Hover-tooltip op pill

Native `<title>` attribuut of NiceGUI `ui.tooltip()` binnen pill. **Geen tijden** — `werkdagen`-tabel slaat geen start/eind times op (codex finding 1: schema-change is buiten Sprint 1).

Pure helper `_pill_tooltip(pill) → str` (codex finding 9 — voorkomt silent regressie):

```
{klant_naam_volledig}
{uren:.1f}u · €{bedrag:,.2f}
Status: {status_label}{factuur_extra}
```

Waar `factuur_extra`:
- `verstuurd/verlopen/betaald` → ` · Factuur {factuurnummer}`
- `concept` → ` · concept-factuur {factuurnummer}`
- `ongefactureerd` → `` (leeg)

Geen tooltip op expected pills (verwarrend met "verwacht via vast rooster" label).

### E. `duplicate_werkdag(werkdag_id, target_datum)` helper

**Doel**: contextmenu-actie "Dupliceren naar volgende [weekdag]" — single-shot, expliciete user-actie.

**Signatuur** (in `database.py`):

```python
async def duplicate_werkdag(
        db_path: Path, werkdag_id: int, target_datum: str) -> int:
    """Kopieer een werkdag naar target_datum.

    Kopieert: klant_id, code, activiteit, locatie, locatie_id, uren, km,
    tarief, km_tarief, opmerking, urennorm.
    Wist: factuurnummer (nooit gekoppeld aan dezelfde factuur als bron).
    Datum: target_datum (gevalideerd, year-locked).

    Atomic: één get_db_ctx + single INSERT. Bron wordt alleen gelezen,
    geen mutatie. Year-lock guard op target_datum (bron-datum mag in
    definitief jaar zitten — read-only).
    """
```

**Race-protectie**: één `get_db_ctx`, geen BEGIN IMMEDIATE nodig (geen check-and-insert). Double-click resulteert in 2 rijen — bewuste user-actie, geen idempotentie verwacht.

**Edge cases**:
- Bron werkdag bestaat niet → `ValueError`
- Target datum invalid format → `_validate_datum` → `ValueError`
- Target datum in definitief jaar → `YearLockedError` (via `assert_year_writable`)
- Duplicate naar zelfde datum als bron → toegestaan (multi-shift dezelfde dag)
- **Blocker/holiday op target-datum**: NIET checken — bestaande "Extra werkdag" knop op blocker-dag staat dit ook toe (vakantie + extra dienst is geldig scenario). Consistent gedrag, codex finding 7.

**UI flow** (handler in `pages/agenda.py`):
1. Open kleine `ui.dialog()` met `date_input()` uit `components/shared_ui.py` (codex finding 6 — bestaande ISO-wrapper, niet raw `ui.date()`)
2. Default value: bron-datum + 7 dagen (volgende week, zelfde weekdag)
3. Confirm-knop "Dupliceren naar {format_datum}"
4. Roept helper aan, notify on success, render() opnieuw

### F. Delete-flow + Ontkoppel-flow

**Delete**: `delete_werkdag` helper bestaat al in `database.py:1868` met year-lock + factuur-koppeling-weigering. Sprint 1 voegt alleen UI-binding toe vanuit context-menu:

1. Click "Verwijderen"
2. Confirm-dialog "Werkdag van {datum} bij {klant_naam} verwijderen?"
3. Op bevestigd: `delete_werkdag(werkdag_id)` → notify → render

Verwijderen-item is al verborgen bij `factuurnummer != ''` (sectie C visibility), dus default-pad heeft geen factuur-koppeling.

**Ontkoppel**: hergebruik bestaande pattern uit `/werkdagen` — `update_werkdag(factuurnummer='')`. Confirm-dialog moet expliciet vermelden (codex finding 8): *"Werkdag wordt losgekoppeld van concept-factuur {nummer}. De factuur en factuurregels blijven ongewijzigd staan; je kunt de werkdag opnieuw koppelen of de factuur handmatig opschonen."* Alleen beschikbaar bij concept of orphan — niet broadenen.

## Architectuur & files

| File | Wijziging |
|---|---|
| `pages/agenda.py` | Wire `new_btn.on_click`. Pill-rendering: voeg click + context-menu handlers toe (alleen confirmed). Tooltip. Nieuwe handlers: `handle_edit_werkdag`, `handle_duplicate_werkdag`, `handle_delete_werkdag`, `handle_ontkoppel_factuur`, `handle_naar_facturen`. |
| `pages/agenda.py` | Pure helper `_pill_context_actions(werkdag) → list[str]` voor visibility-logic, eenheid-testbaar. |
| `database.py` | Nieuwe `duplicate_werkdag(db, werkdag_id, target_datum) → int` helper. Update `_assert_werkdagen_writable` niet nodig (single-werkdag actie, target year-lock check is voldoende). |
| `pages/agenda.py` | Reuse bestaande `ontkoppel_werkdag_van_factuur` helper als deze bestaat — anders kort SQL update via `update_werkdag(factuurnummer='')`. *Te verifiëren tijdens implementatie.* |
| `tests/test_agenda_service.py` of `tests/test_agenda_page.py` | Tests voor `_pill_context_actions` visibility-rules + `duplicate_werkdag` roundtrip. |
| `tests/test_year_locking.py` | Year-lock test voor `duplicate_werkdag` (target in definitief jaar). |

## Tests (rigoureus)

1. **Source-pin**: `refs['new_btn'].on_click` aanwezig in `pages/agenda.py` (regex-grep test) — voorkomt regressie van de oorspronkelijke bug. Dit is een zwakke check (codex finding 10) — dus ook **manual browser-verificatie verplicht** als quality-gate (zie "Verifiëren handmatig").
2. **`_pill_context_actions` visibility-matrix** — 8 scenario's, allemaal terugverwijzend naar action-IDs:
   - `factuurnummer=''`, geen factuur_id → `['edit', 'duplicate', 'delete']`
   - `factuur_status='concept'`, factuur_id != None → `['edit', 'duplicate', 'naar_facturen', 'ontkoppel']`
   - `factuur_status='verstuurd'`, factuur_id != None, vervaldatum in toekomst → `['edit', 'duplicate', 'naar_facturen']`
   - `factuur_status='verstuurd'`, factuur_id != None, vervaldatum in verleden (= status_label='verlopen') → `['edit', 'duplicate', 'naar_facturen']`
   - `factuur_status='betaald'`, factuur_id != None → `['edit', 'duplicate', 'naar_facturen']`
   - **Orphan** (factuurnummer != '', factuur_id IS None, factuur_status='') → `['edit', 'duplicate', 'ontkoppel']`
   - **Edge: onbekende factuur_status** met factuur_id != None → `['edit', 'duplicate', 'naar_facturen']` — geen ontkoppel/delete (defensive, codex finding 4)
   - **Edge: factuurnummer=''**, factuur_id IS None (basis) → `['edit', 'duplicate', 'delete']`
3. **`_pill_tooltip` formatter** — pure helper-tests:
   - ongefactureerd: tooltip eindigt met `Status: ongefactureerd` (geen factuurnummer-extra)
   - concept: tooltip eindigt met `Status: concept · concept-factuur 2026-024`
   - betaald: tooltip eindigt met `Status: betaald · Factuur 2026-024`
4. **`get_werkdag_by_id` roundtrip** — happy-path + non-existent → `None`.
5. **`duplicate_werkdag` roundtrip**: maakt nieuwe rij, alle velden (klant_id, code, activiteit, locatie, locatie_id, uren, km, tarief, km_tarief, opmerking, urennorm) gekopieerd, `factuurnummer=''`, target_datum gezet. Bron blijft ongewijzigd.
6. **`duplicate_werkdag` year-lock**: target in definitief jaar → `YearLockedError`. Bron in definitief jaar mag (read-only).
7. **`duplicate_werkdag` non-existent bron**: `ValueError`.
8. **`duplicate_werkdag` invalid datum**: `ValueError` via `_validate_datum`.
9. **`duplicate_werkdag` blocker op target-datum**: toegestaan (consistent met "Extra werkdag" — codex finding 7).

## Open punten — moet user beslissen

1. **Klikgedrag op confirmed pill**: bevestig dat left-click → direct edit-dialog correct is (alternatief: kleine summary-popover met action-knoppen). *Voorstel: direct edit, simpelste mental-model.*
2. **Default-datum bij Dupliceren**: bron + 7 dagen (volgende week). Of: prompt zonder default? *Voorstel: bron + 7d default.*

## Toon-en-stijl

- Geen drag/drop — codex bevestigt dat dit te risicovol is voor Sprint 1
- Geen multi-select bulk-ops — bestaat al in `/werkdagen` lijst-view
- Geen undo voor delete — confirm-dialog is genoeg friction

## YAGNI — bewust níet doen

- Right-click op expected pills (recurring) → menu zou dupliceren met Day-Inspector "Bevestigen/Aanpassen"
- Right-click op blocker (vakantie/ziek/nascholing) → al verwijder-knop in inspector
- Right-click op holiday → niet wijzigbaar (NL-feestdagen, computed)
- Pill-click op leeg cel → al cell-click flow

## Verifiëren handmatig na implementatie (UI-only)

**Verplicht als quality-gate** vóór "klaar"-rapportage (codex finding 10 — source-pin tests zijn zwak voor UI-events):

1. Klik "Nieuwe werkdag" toolbar → dialog opent met **`state['selected']` als default datum**
2. Klik op pill → edit-dialog opent met juiste werkdag-data, day-selectie verandert NIET (stopPropagation werkt)
3. Right-click op pill → context-menu verschijnt op muispositie (test trackpad two-finger click in pywebview op macOS)
4. Right-click items werken end-to-end:
   - Bewerken → opent edit-dialog
   - Dupliceren → opent date-picker, default = bron+7d, save → nieuwe pill in agenda
   - Verwijderen → confirm → werkdag weg, agenda re-rendered
   - Naar facturen → navigeert naar /facturen
   - Ontkoppel (alleen concept/orphan) → confirm-dialog met expliciete uitleg, save → factuurnummer leeg
5. Hover op pill → tooltip met klant + uren + bedrag + status (+ factuurnummer indien gefactureerd)
6. Verwijderen-item verborgen bij gefactureerd; alleen Ontkoppel zichtbaar bij concept/orphan, niet bij verstuurd/betaald
