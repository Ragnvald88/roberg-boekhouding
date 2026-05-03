# /agenda Factuur-koppeling End-to-End Rooktest

**Doel**: verifieer dat de factuur-status van een werkdag direct in `/agenda` zichtbaar
is bij elke fase van de factuur-lifecycle (kern-feature van Sprint A).

**Uitvoeren door**: gebruiker, op productie-DB, na merge `d70dbb3` op master
(Sprint A SHIPPED 2026-05-03). Niet door een agent — dit vereist visuele
verificatie in pywebview.

## Setup

```bash
cd ~/Library/CloudStorage/SynologyDrive-Main/06_Development/1_roberg-boekhouding
source .venv/bin/activate
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py
# OF: open -a Boekhouding
```

App opent in pywebview. Houd dev-tools open (rechtermuisklik → Inspect) om
console errors te monitoren.

## Stap 0: Voorbereiding — kies een toekomstige datum + klant

Open `/klanten`. Bewerk een actieve klant (bv. "HAP X"). In de sectie
"Vast rooster", voeg een patroon toe:
- Dagen: Ma + Wo
- Start: 08:00
- Eind: 17:00
- Code: WERKDAG

Open `/agenda`. Navigeer naar een toekomstige maand (bv. juli 2026).
Verifieer in een Maandag of Woensdag cel:
- ☑️ Verwacht een dashed pill met klant-naam + 9.0u (`wd-pill expected wd-dagpraktijk`)
- ☑️ Geen status-bar (expected entries hebben geen factuur-status)

## Stap 1: Bevestig verwachte werkdag → ongefactureerd

1. Klik op de Maandag in de agenda-cel.
2. Day-Inspector toont expected entry met klant + tijden + bedrag.
3. Klik **"Bevestigen"**.
4. Werkdag-dialog opent gepre-vuld met datum, klant, uren=9.
5. Klik **"Opslaan"**.
6. Toast: "Werkdag bevestigd".

**Verifieer in cel:**
- ☑️ Pill is nu vol (niet dashed) — `wd-pill wd-dagpraktijk` zonder `.expected`
- ☑️ Status-bar onderaan = grijs (`status-ongefactureerd`)

**Verifieer in inspector:**
- ☑️ Werkdag-card met status-chip "Ongefactureerd" (grijs/grey-7 badge)
- ☑️ "Maak factuur" knop zichtbaar onderaan
- ☑️ "Extra werkdag" knop ook zichtbaar (multi-shifts pad)

## Stap 2: Maak concept-factuur → cel wordt grijs-blauw

1. Klik **"Maak factuur"** in de inspector.
2. Browser navigeert naar `/facturen?nieuw=1&werkdagen=<id>`.
3. Invoice-builder opent direct met die werkdag pre-selected.
4. Bewaar als concept (Opslaan zonder verzenden — knop "Opslaan als concept" of
   navigate-back zonder verzenden).

**Verifieer in `/agenda` (terug-navigeren of refresh-knop):**
- ☑️ Status-bar = `status-concept` (grijs-blauw, opacity 0.6)

**Verifieer in inspector:**
- ☑️ Status-chip "Concept" (grijs)
- ☑️ Factuurnummer-link zichtbaar (klikbaar → /facturen?factuur_id=X)
- ☑️ "Maak factuur" knop verdwenen

## Stap 3: Markeer factuur als verstuurd → cel wordt blauw

1. Open `/facturen` → vind de zojuist gemaakte factuur.
2. Markeer als verstuurd (via row-menu of bewerk-dialog).
3. Terug naar `/agenda` (klik in sidebar of refresh).

**Verifieer in cel:**
- ☑️ Status-bar = `status-verstuurd` (blauw `#2563EB`)

**Verifieer in inspector:**
- ☑️ Status-chip "Verstuurd" (blue)
- ☑️ Factuur-link nog steeds klikbaar

## Stap 4: Vervaldatum verstrijkt → cel wordt rood

Vervaldatum = factuur.datum + 14 dagen (computed). Om "verlopen" te triggeren
zonder 2 weken wachten: zet de factuur-datum kunstmatig 15+ dagen terug.

```bash
DB="${HOME}/Library/Application Support/Boekhouding/data/db.sqlite3"
# Vervang FACTUURNUMMER hieronder met je echte nummer
sqlite3 "$DB" "UPDATE facturen SET datum = '$(date -v-15d +%Y-%m-%d)' WHERE nummer = 'XXXX-XXX'"
```

(Of, als bash `date -v` niet werkt op je shell: gebruik `date -d "-15 days" +%Y-%m-%d`
op linux-style date binary; macOS heeft default BSD-date dus `-v-15d` is correct.)

In `/agenda`, klik **"Ververs"** in topbar (of navigeer weg+terug).

**Verifieer in cel:**
- ☑️ Status-bar = `status-verlopen` (rood `#DC2626`)

**Verifieer in inspector:**
- ☑️ Status-chip "Verlopen" (red)
- ☑️ "X dgn te laat" label zichtbaar (overdue_days uit `compute_overdue_days`)

## Stap 5: Markeer als betaald → cel wordt groen

1. `/facturen` → markeer factuur als betaald (vul betaaldatum in).
2. Terug naar `/agenda` + ververs.

**Verifieer in cel:**
- ☑️ Status-bar = `status-betaald` (groen `#16A34A`)

**Verifieer in inspector:**
- ☑️ Status-chip "Betaald" (green)
- ☑️ "op X mei" label (factuur_betaald_datum, kort-formatted via
  `_format_short_date`)
- ☑️ Factuur-link nog steeds klikbaar

## Stap 6: Cleanup (optioneel)

Verwijder de test-werkdag, factuur en pattern via UI, of restore via DB-backup.

## Result-log

Vul in tijdens uitvoering:

| Stap | Verwachte UI | Gemeten | OK |
|---|---|---|---|
| 0. Pattern toegevoegd, expected pill zichtbaar | dashed pill met 9.0u | _ | _ |
| 1. Bevestigd ongefactureerd | grijze status-bar | _ | _ |
| 2. Concept | grijs-blauw status-bar | _ | _ |
| 3. Verstuurd | blauw status-bar | _ | _ |
| 4. Verlopen (vervaldatum < today) | rode status-bar + "X dgn te laat" | _ | _ |
| 5. Betaald | groene status-bar + "op X mei" | _ | _ |

## Bijkomende rooktests (Sessie 3+4)

Verifieer ook:

- ☑️ **Holiday-cel**: navigeer naar 27 april 2026 (Koningsdag). Cel toont
  `holiday-marker` top-band + label "Koningsdag". Inspector toont
  celebration-icon + "Werkdag plannen"-knop.
- ☑️ **User-blocker**: klik op een lege toekomstige dag → klik **Vakantie**
  → cel krijgt `blocker-vacation` overlay. Klik op die dag → inspector toont
  "Verwijderen"-knop.
- ☑️ **Year-lock**: probeer een blocker te verwijderen op een datum in een
  afgesloten jaar → toast warning, geen mutatie.
- ☑️ **Idempotent confirm**: klik 2× snel achter elkaar op "Bevestigen"
  voor dezelfde verwachte entry → één werkdag in de DB (atomic via BEGIN
  IMMEDIATE).
- ☑️ **Recurring config UI**: in `/klanten` bewerk-dialog → vast rooster →
  patroon toevoegen + verwijderen werkt + reflecteert direct in /agenda
  expected entries.

## Bij problemen

- **Console errors**: open dev-tools, kopieer + raadpleer `pages/agenda.py`
- **Status-bar verkeerde kleur**: check CSS classes in `components/layout.py`
  + `derive_werkdag_status_label` in `services/agenda.py`
- **Factuur-link werkt niet**: verifieer `WerkdagPill.factuur_id` is gevuld
  (JOIN-query in `database.get_werkdagen_met_factuur_status`)
- **Bevestigen geeft duplicaten**: race-test in
  `tests/test_agenda_service.py:test_confirm_expected_atomic_under_parallel_calls`
  zou dit moeten beschermen — als reproduceerbaar, escaleer naar maintainer.
