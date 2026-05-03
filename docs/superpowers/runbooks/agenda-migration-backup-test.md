# Backup + Rollback Proef — Migratie 35+36

Voer deze stappen uit ÉÉN keer voordat je de app voor het eerst start na het
mergen van migraties 35+36 (klant_recurring_patterns + blockers tabellen).

## Voorbereiding

```bash
DB="${HOME}/Library/Application Support/Boekhouding/data/db.sqlite3"
BACKUP="${HOME}/Library/Application Support/Boekhouding/data/pre-35-backup.sqlite3"
```

## Stap 1: Backup huidige DB

```bash
sqlite3 "$DB" "VACUUM INTO '$BACKUP'"
ls -lh "$BACKUP"  # verifieer bestand bestaat
```

Verwacht: backup-bestand zichtbaar met grootte vergelijkbaar aan origineel.

## Stap 2: Apply migraties (start app)

Optie A — via app:
```bash
cd ~/Library/CloudStorage/SynologyDrive-Main/06_Development/1_roberg-boekhouding
source .venv/bin/activate
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python main.py
# Open /agenda in de app — sluit de app weer
```

Optie B — alleen schema-init (zonder UI):
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python -c "import asyncio, database; asyncio.run(database.init_db('$DB'))"
```

## Stap 3: Verifieer schema-versie + nieuwe tabellen

Noteer eerst je werkdagen-count VÓÓR migratie:
```bash
sqlite3 "$BACKUP" "SELECT COUNT(*) FROM werkdagen"  # bv. 142
```

Verifieer dan POST-migratie:
```bash
sqlite3 "$DB" "SELECT version FROM schema_version"
# Verwacht: 36

sqlite3 "$DB" "SELECT COUNT(*) FROM klant_recurring_patterns"
# Verwacht: 0

sqlite3 "$DB" "SELECT COUNT(*) FROM blockers"
# Verwacht: 0

sqlite3 "$DB" "SELECT COUNT(*) FROM werkdagen"
# Verwacht: zelfde getal als pre-migratie (bv. 142)

sqlite3 "$DB" "SELECT COUNT(*) FROM facturen"
# Verwacht: zelfde getal als pre-migratie

sqlite3 "$DB" "SELECT COUNT(*) FROM klanten"
# Verwacht: zelfde getal als pre-migratie
```

## Stap 4: Rollback test

Restore de backup en verifieer dat oude schema-versie terugkomt:
```bash
cp "$BACKUP" "$DB"
sqlite3 "$DB" "SELECT version FROM schema_version"
# Verwacht: 34 (pre-Sprint-A versie) — of welke versie er stond vóór migratie
```

Tabellen `klant_recurring_patterns` en `blockers` zouden niet meer moeten bestaan:
```bash
sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('klant_recurring_patterns','blockers')"
# Verwacht: leeg
```

## Stap 5: Re-apply (idempotency)

Pas de migraties opnieuw toe en verifieer dat alles weer ok is:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python -c "import asyncio, database; asyncio.run(database.init_db('$DB'))"
sqlite3 "$DB" "SELECT version FROM schema_version"
# Verwacht: 36
```

Run het ZELFDE commando NOG EEN KEER — moet identiek werken (idempotent):
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python -c "import asyncio, database; asyncio.run(database.init_db('$DB'))"
sqlite3 "$DB" "SELECT version FROM schema_version"
# Verwacht: nog steeds 36, geen errors
```

## Cleanup

Na succesvol uitvoeren van alle stappen mag je de backup verwijderen — of bewaar 'm
voor extra zekerheid:
```bash
# rm "$BACKUP"   # optioneel
```

## Result-log (vul in tijdens uitvoering)

| Stap | Verwacht | Gemeten | OK |
|---|---|---|---|
| Backup created | $BACKUP exists | _ | _ |
| Schema version after migrate | 36 | _ | _ |
| werkdagen count unchanged | <pre-count> | _ | _ |
| facturen count unchanged | <pre-count> | _ | _ |
| klanten count unchanged | <pre-count> | _ | _ |
| Rollback to pre-Sprint-A | 34 (or earlier) | _ | _ |
| Re-apply idempotent | 36 → 36 | _ | _ |

## Bij problemen

Als een stap faalt: STOP, restore backup (`cp $BACKUP $DB`), en raadpleer de Sprint A
spec (`docs/superpowers/specs/2026-05-02-agenda-sprint-a-design.md`) of vraag.
