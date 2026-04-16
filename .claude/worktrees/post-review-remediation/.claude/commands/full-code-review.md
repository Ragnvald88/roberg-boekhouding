Doe een grondige, kritische code review van deze hele codebase. Dit is een Python NiceGUI + SQLite boekhoudapp voor een eenmanszaak huisartswaarnemer. Lees eerst CLAUDE.md en MEMORY.md voor context.

Ik wil ECHTE problemen — bugs, rekenfouten, data-integriteit issues, architectuurproblemen. Geen beleefde "looks good" review. Geef het eerlijke oordeel dat een sceptische senior engineer zou geven.

BELANGRIJK: Gebruik altijd `model: "opus"` voor alle subagents/agents die je dispatcht.

## Scope

Lees en analyseer ALLES:
1. Alle bestanden in `pages/` (alle pagina-modules)
2. Alle bestanden in `components/` (shared UI, utils, fiscal logic, invoice builder/generator/preview)
3. `fiscal/berekeningen.py` (de fiscale engine — meest kritisch)
4. `database.py` (DB-laag, migraties, queries)
5. `templates/factuur.html` (factuur template)
6. Tests in `tests/` — beoordeel kwaliteit en coverage gaps

Gebruik subagents (altijd opus model) om bestanden parallel te lezen waar nodig.

## Wat te controleren

### Kritiek (bugs die foute bedragen produceren of data verliezen)
- Fiscale berekeningen: arbeidskorting, ZVW, PVV, tariefsaanpassing, Box 3, KIA, afschrijvingen
- Omzet-queries: sluiten ze concept-facturen correct uit? Day-precise YoY?
- Bank matching: betalingskenmerk parsing, IB/ZVW split, tolerantie-matching
- Status lifecycle: concept → verstuurd → betaald cascade, werkdagen status updates
- SQL injection via f-strings (alleen ? placeholders toegestaan)
- Data-verlies: delete cascades, WAL mode, concurrent writes

### Belangrijk (architectuurproblemen)
- Code duplicatie tussen pagina's
- Inconsistente error handling
- Te lange functies / te veel verantwoordelijkheden
- Async: blocking I/O niet in asyncio.to_thread()?
- DB connection leaks (alles via get_db_ctx?)
- Hardcoded waarden die uit fiscal_params moeten komen

### Domeinlogica
- Matcht de fiscale engine de Boekhouder accountant referentiewaarden?
- Alle fiscale jaarwaarden uit DB, niet hardcoded?
- Factuurnummering (YYYY-NNN) correct afgedwongen?
- ANW diensten (km_tarief=0) overal correct?
- nog_te_factureren excludeert tarief=0?

### Test kwaliteit
- Testen ze echte logica of mocken ze alles weg?
- Welke kritieke paden hebben GEEN test coverage?
- Fiscale edge cases gedekt (inkomen nabij schijfgrenzen)?

## Output formaat

### KRITIEK (Moet gefixt)
Per item: file:line, wat is fout, waarom het ertoe doet, bewijs

### BELANGRIJK (Zou gefixt moeten worden)
Per item: file:line, wat is fout, impact

### MINOR (Opmerkenswaardig)
Korte lijst

### STERKTES
Wat is oprecht goed gedaan (specifiek, geen generiek compliment)

### COVERAGE GAPS
Specifieke functies/paden zonder test coverage die het wel nodig hebben

### ARCHITECTUUR BEOORDELING
Eén paragraaf: is deze codebase onderhoudbaar? Wat is het grootste structurele risico?

Wees grondig. Lees elk bestand voordat je conclusies trekt. Ik heb liever een lange, specifieke review dan een korte, vage.
