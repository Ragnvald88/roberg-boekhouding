# User-config architectuur: aliasen & skip-words (v5)

**Date**: 2026-04-28
**Status**: post-codex-round-4 — 2 must-fixes (TOCTOU + modal) verwerkt
+ PR-fasering toegevoegd. Codex round-3 row_factory issue blijft
opgelost.

## Context

Gisteren is de repo van public → private gezet en de hele git-historie
gescrubd. Tijdens die scrub zijn 3 modules gerefactored zodat ze user-data
uit gitignored `*_local.py` files in de repo-map laden. Die oplossing is
fragiel: bij een verse `git clone` zijn die files weg en breken
PDF-import herkenning + eigen-naam filter. Bovendien zijn er nog twee
customer-name leaks (`M. Zwart`, `M. de Vijlder` — nieuwe klanten ná de
scrub-lijst) die meteen worden meegenomen.

## Doel

User-data permanent uit de repo-map halen, zo'n manier dat:
1. de repo veilig publiek kan zonder leak-risico,
2. de app blijft werken zoals nu,
3. re-clone, branch-switch, of fresh install geen functionaliteit breken,
4. nieuwe alias-varianten zonder code-wijziging gevangen worden,
5. een verkeerde auto-leer-keuze later UI-corrigeerbaar is.

## Eindstaat: alle user-data in SQLite

### 1. Klant-aliassen → DB-tabel `klant_aliases` (migratie 33 + 34)

**Schema (SCHEMA_SQL voor verse DBs + migratie 33 voor upgrade):**

```sql
CREATE TABLE IF NOT EXISTS klant_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    klant_id INTEGER NOT NULL REFERENCES klanten(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('suffix', 'pdf_text', 'anw_filename')),
    pattern TEXT NOT NULL COLLATE NOCASE
        CHECK (length(trim(pattern)) >= 3),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (type, pattern)
);
CREATE INDEX IF NOT EXISTS idx_klant_aliases_lookup
    ON klant_aliases(type, pattern);
```

- `length(trim(pattern)) >= 3`: voorkomt 1- en 2-character patterns die
  als fuzzy substring alle PDFs zouden matchen.
- `COLLATE NOCASE` op de kolom: queries gebruiken direct
  `WHERE a.pattern = ?` (zonder `LOWER()`-wrapper) en de index wordt
  benut.
- `IF NOT EXISTS` in zowel SCHEMA_SQL als migratie 33.

### 2. Persoonlijke skip-words → afgeleid uit `bedrijfsgegevens`

`derive_skip_words(bg) -> tuple[str, ...]` in nieuwe module
`import_/skip_words.py`. Gebaseerd op bestaande `bedrijfsgegevens` tabel
(velden `naam, bedrijfsnaam, adres, postcode_plaats, telefoon, email,
kvk, iban` — telefoon en email worden door migratie 16 toegevoegd; voor
verify-script betekent dit: vereist een `init_db()`-passed DB).

```python
import re

GENERIC_SKIP_WORDS = (
    'Datum', 'FACTUUR', 'Tel', 'KvK', 'IBAN', 'Mail:', 'Bank:',
    # Voor scrubbed test fixtures (zie test_pdf_parser.py):
    'TestBV', 'huisartswaarnemer', 'Test Gebruiker', 'T. Gebruiker',
    'Teststraat 1', '1234 AB', '1234AB', 'testuser', '06 000', '0600',
    '@example.com',
)

def _normalize_phone_digits(telefoon: str) -> str | None:
    """Return canonical 10-digit national form (`'0612345678'`), or None.

    Examples:
      '06 4326 7791'    → '0643267791'
      '+31 6 4326 7791' → '0643267791'  (strips '+31', prepends '0')
      '0031 6 4326 ...'  → '0643267791'  (strips '0031', prepends '0')
    """
    digits = ''.join(c for c in telefoon if c.isdigit())
    if digits.startswith('0031'):
        digits = '0' + digits[4:]    # 4-char prefix
    elif digits.startswith('31') and len(digits) == 11:
        digits = '0' + digits[2:]
    if len(digits) < 6:
        return None
    return digits

def derive_skip_words(bg) -> tuple[str, ...]:
    """Generic + tokens uit bedrijfsgegevens row."""
    if bg is None:
        return GENERIC_SKIP_WORDS
    derived: list[str] = []
    for field in (bg.naam, bg.bedrijfsnaam, bg.adres, bg.email):
        if field:
            derived.append(field)
    if bg.email and '@' in bg.email:
        derived.append(bg.email.split('@', 1)[0])
    if bg.postcode_plaats:
        m = re.match(r'^([0-9]{4}\s?[A-Z]{2})\s+(.+)$',
                     bg.postcode_plaats.strip())
        if m:
            derived.extend(m.groups())
        else:
            derived.append(bg.postcode_plaats.strip())
    digits = _normalize_phone_digits(bg.telefoon or '')
    if digits:
        derived.append(digits[:4])
        derived.append(digits[:6])
        derived.append(f'{digits[:2]} {digits[2:5]}')
        derived.append(digits)
    return GENERIC_SKIP_WORDS + tuple(derived)
```

### 3. `KLANT_LOCATIES` seed → schrappen na audit

**Pre-flight check** (`scripts/audit_missing_locaties.py`, run vóór
deletie). Print-only; geen automatische actie.

DB-status (28 april 2026): meerdere klanten zonder locaties
(`H.C. Spijker`, `Huisartspraktijk de Wilp`, `M. Zandwijk`, `M. Zwart`,
`M. de Vijlder`, `P.P. de Jonge`, `RoBerg Huisartswaarnemer`).
Seed-bestand had alleen entries voor 1 daarvan onder een verkeerde naam
(`Huisartsenpraktijk de Wilp` vs DB `Huisartspraktijk de Wilp`).
Effectief niet load-bearing → schrappen.

## Refactor van `resolve_klant` / `resolve_anw_klant`

**Strategy order (v4, alle stappen case-insensitive consistent):**

```python
async def resolve_klant(db_path, pdf_name, filename_suffix) -> tuple[name, kid]:
    """Resolve klant via klant_aliases + klanten tables.

    1. Exact suffix → klant_aliases WHERE type='suffix' AND pattern = ?
    2. Exact pdf_text → klant_aliases WHERE type='pdf_text' AND pattern = ?
    3. Direct klanten.naam match → klanten WHERE naam = ? COLLATE NOCASE
    4. Fuzzy substring → klant_aliases WHERE type='pdf_text'
       AND length(pattern) ≥ 3
       AND (instr(LOWER(pdf_name), LOWER(pattern)) > 0
         OR instr(LOWER(pattern), LOWER(pdf_name)) > 0)
       ORDER BY length(pattern) DESC, klant_id ASC LIMIT 1
    """
```

**Strategy 3 SQL (NOCASE-consistent):**

```sql
SELECT id, naam FROM klanten
WHERE naam = ? COLLATE NOCASE
ORDER BY id ASC LIMIT 1;
```

`ORDER BY id ASC` is safety-net voor het zeldzame geval dat twee
klanten dezelfde naam zouden hebben (zou anders een UNIQUE-constraint
op klanten.naam aan kunnen — out of scope).

`resolve_anw_klant` analoog: alleen fuzzy match op `type='anw_filename'`.

**Productie-callers**: `pages/facturen.py:1500` en `:1504`. Beide al
binnen `async def handle_import_loop` — toevoegen van `await` is
mechanisch.

## Auto-learn alias met conflict-detectie + UI-corrigeerbaarheid

Codex round-3 finding 2: `INSERT OR IGNORE` maskeert conflicten. Twee
pijlers:

### Pijler A: Race-vrije insert + expliciete conflict-detectie

Codex round-4 finding 1: SELECT-then-INSERT is niet atomair. Fix via
INSERT-first met `IntegrityError`-catch, dan re-read voor conflict-info:

```python
import aiosqlite

async def remember_alias(db_path, klant_id: int,
                         pdf_extracted_name: str | None,
                         filename_suffix: str | None) -> dict:
    """Insert klant_aliases rows; race-vrij via INSERT + IntegrityError-catch.

    Returns dict:
      'inserted': int                (rows freshly inserted)
      'conflicts': list[dict]        (existing patterns mapped to *other* klant)
        each: {alias_id, type, pattern, existing_klant_id, existing_klant_naam}

    'already_correct': int            (existing patterns already mapped to this klant)
    """
    candidates = [
        ('pdf_text', pdf_extracted_name),
        ('suffix', filename_suffix),
    ]
    inserted = 0
    already_correct = 0
    conflicts: list[dict] = []
    async with get_db_ctx(db_path) as conn:
        prev_factory = conn.row_factory
        conn.row_factory = aiosqlite.Row
        try:
            for type_name, pattern in candidates:
                if not pattern or len(pattern.strip()) < 3:
                    continue
                pattern = pattern.strip()
                try:
                    await conn.execute(
                        "INSERT INTO klant_aliases (klant_id, type, pattern) "
                        "VALUES (?, ?, ?)",
                        (klant_id, type_name, pattern))
                    inserted += 1
                except aiosqlite.IntegrityError:
                    # UNIQUE conflict — existing row, find owner
                    row = await (await conn.execute(
                        "SELECT a.id, a.klant_id, k.naam FROM klant_aliases a "
                        "JOIN klanten k ON k.id = a.klant_id "
                        "WHERE a.type = ? AND a.pattern = ?",
                        (type_name, pattern))).fetchone()
                    if row is None:
                        # Vanished between INSERT and SELECT (extremely rare:
                        # would require concurrent DELETE). Skip silently —
                        # next import attempt will INSERT freshly.
                        continue
                    if row['klant_id'] == klant_id:
                        already_correct += 1
                    else:
                        conflicts.append({
                            'alias_id': row['id'],
                            'type': type_name,
                            'pattern': pattern,
                            'existing_klant_id': row['klant_id'],
                            'existing_klant_naam': row['naam'],
                        })
            await conn.commit()
        finally:
            conn.row_factory = prev_factory
    return {'inserted': inserted, 'already_correct': already_correct,
            'conflicts': conflicts}
```

### UI-flow met expliciete modal (geen silent notify)

Codex round-4 finding 2: `ui.notify` is geen blokkerend confirm. Fix met
echte `ui.dialog`:

```python
async def show_conflict_dialog(conflict: dict, target_klant_naam: str) -> str:
    """Show modal: keep existing alias or reassign.

    Returns: 'reassign' or 'keep'.
    Closing the dialog (X-button or click-outside) = 'keep' (safe default).
    """
    with ui.dialog() as dialog, ui.card():
        ui.label(f"Alias '{conflict['pattern']}' is al gekoppeld aan "
                 f"'{conflict['existing_klant_naam']}'.").classes('text-lg')
        ui.label(f"Wil je 'm verplaatsen naar '{target_klant_naam}'?")
        with ui.row():
            ui.button('Behoud', on_click=lambda: dialog.submit('keep'))
            ui.button('Verplaats', color='warning',
                      on_click=lambda: dialog.submit('reassign'))
    result = await dialog
    return result if result in ('keep', 'reassign') else 'keep'
```

### Pijler A.bis: Optimistic-lock op reassign (codex round-4 finding 2b)

```python
async def update_klant_alias_target(db_path, alias_id: int,
                                     expected_old_klant_id: int,
                                     new_klant_id: int) -> bool:
    """Atomic re-assign with optimistic lock. Returns True if applied."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "UPDATE klant_aliases SET klant_id = ? "
            "WHERE id = ? AND klant_id = ?",
            (new_klant_id, alias_id, expected_old_klant_id))
        await conn.commit()
        return cur.rowcount == 1
```

Als `rowcount == 0`: alias is intussen door iemand anders aangepast →
notify user en abort de reassign. Voor deze single-user app is concurrent
edits zeldzaam, maar de invariant is wel correct (geen blind overwrite).

### Pijler B: Alias CRUD-UI in `/klanten` (in scope!)

In `pages/klanten.py`, per klant een uitklapbare detail-rij of pop-up
dialog met:

- Lijst aliases (type + pattern + delete-knop)
- "+ Nieuwe alias" formulier (type-dropdown + pattern-input + save)
- Sortering: nieuwste eerst
- Delete is direct (geen extra confirm — alias is metadata, niet
  fiscale data; 1-klik delete is acceptable)

Database-helpers (in `database.py`):

```python
async def get_klant_aliases(db_path, klant_id) -> list[dict]:
    ...

async def add_klant_alias(db_path, klant_id, type_name, pattern):
    ...  # raises on UNIQUE violation; UI shows error

async def delete_klant_alias(db_path, alias_id):
    ...

async def update_klant_alias_target(db_path, alias_id: int,
                                     expected_old_klant_id: int,
                                     new_klant_id: int) -> bool:
    ...  # optimistic-lock; see Pijler A.bis
```

Default checkbox in import-dialog: **UNCHECKED** (codex round-2 finding).

ANW-filename aliases worden niet auto-geleerd (te variabel).

## PDF parser API: skip_words als parameter

```python
def _extract_klant_name(text, skip_words=None) -> str | None:
    skip_words = skip_words or GENERIC_SKIP_WORDS
    skip_lower = tuple(s.lower() for s in skip_words)
    ...
    if not any(s in candidate.lower() for s in skip_lower):
        return candidate

def parse_dagpraktijk_text(text, filename, skip_words=None) -> dict:
    ...
```

**Productie-caller** in `pages/facturen.py`:
```python
bg = await get_bedrijfsgegevens(db_path)
skip_words = derive_skip_words(bg)
result = parse_dagpraktijk_text(text, filename, skip_words=skip_words)
```

## Eenmalige data-migratie (callable in MIGRATIONS list)

**Codex round-3 finding 1**: `aiosqlite.connect` levert tuples; `row['naam']`
crasht. Fix via `conn.row_factory = aiosqlite.Row` (mirror migratie 27
patroon, [database.py:674](database.py)).

```python
async def _seed_klant_aliases_from_local(conn) -> None:
    """Migration 34: read klant_mapping_local.py if present;
    seed klant_aliases via INSERT OR IGNORE. No-op if module missing.
    """
    try:
        from import_ import klant_mapping_local as src
    except ImportError:
        return  # Fresh install or already cleaned up

    prev_factory = conn.row_factory
    conn.row_factory = aiosqlite.Row
    try:
        cur = await conn.execute("SELECT id, naam FROM klanten")
        rows = await cur.fetchall()
        klant_id_by_naam = {row['naam']: row['id'] for row in rows}
    finally:
        conn.row_factory = prev_factory

    for type_name, source_dict in (
        ('suffix', src.SUFFIX_TO_KLANT),
        ('pdf_text', src.PDF_KLANT_TO_DB),
        ('anw_filename', src.ANW_FILENAME_TO_KLANT),
    ):
        for pattern, klant_naam in source_dict.items():
            klant_id = klant_id_by_naam.get(klant_naam)
            if not klant_id or len(pattern.strip()) < 3:
                continue
            await conn.execute(
                "INSERT OR IGNORE INTO klant_aliases "
                "(klant_id, type, pattern) VALUES (?, ?, ?)",
                (klant_id, type_name, pattern.strip()))


MIGRATIONS = [
    ...,
    (33, "add_klant_aliases_table", [
        # CREATE TABLE + CREATE INDEX (zie sectie 1)
    ]),
    (34, "seed_klant_aliases_from_local_if_present", None),
]
MIGRATION_CALLABLES = {
    ...,
    34: _seed_klant_aliases_from_local,
}
```

Migratie 34 blijft permanent in de list als idempotente no-op (na 2027
gebruikt, als jouw DB allang up-to-date is, doet INSERT OR IGNORE niets;
voor nieuwe users is `_local.py` er niet → `return`).

**Code-comment toegevoegd:**
```python
# Migration 34 is permanently retained as an idempotent no-op:
# - Existing users: ran once on first startup after upgrade; subsequent
#   startups are no-op via INSERT OR IGNORE.
# - New users: import fails (klant_mapping_local.py is gone), early return.
# Removing this entry would break the migration sequence numbering for
# any DB stuck at version 33. Safe to leave forever.
```

## PR-fasering (codex round-4 finding 4)

Codex adviseert: dit is groot, splitsen in 2 PRs reduceert risico. Op
mijn single-user setup is dat moeilijk handhaafbaar (geen reviewer) maar
**ik commit het wel als 2 logische commits achter elkaar** (ook na
force-push). Als phase-1 stuk gaat is phase-2 makkelijk uit te zetten:

**Phase 1 — foundation** (één commit):
- Migration 33 (schema) + 34 (data callable)
- `klant_aliases` DB-helpers (`get_/add_/delete_/update_klant_alias`)
- `import_/skip_words.py` met `derive_skip_words`
- Refactor `import_/klant_mapping.py` naar async DB-queries
- Refactor `import_/pdf_parser.py` naar `skip_words` parameter
- Update `pages/facturen.py` callers (await + skip_words injection)
- `tests/test_pdf_parser.py` refactor + 4 nieuwe test-files
- Scrub `Zwart` in `tests/test_archive_factuur.py`

**Phase 2 — UI + cleanup** (volgende commit):
- Auto-learn checkbox + conflict-modal in `pages/facturen.py`
  import-flow
- Alias-CRUD UI in `pages/klanten.py`
- `tests/test_remember_alias.py` + `tests/test_klanten_page_aliases.py`
- Verwijder `KLANT_LOCATIES` + `seed_klant_locaties` uit `seed_data.py`
- Run `audit_missing_locaties.py` + `verify_public_safe.py`
- Verwijder de 3 `_local.py` files + `.gitignore` regels
- Verwijder de 2 scripts
- Force-push naar GitHub

Tussen phase 1 en 2: volledige test-suite groen, app handmatig getest
via dev-startup.

## Cleanup-stappen

Na succesvolle migratie + groene tests + verificatie counts:

1. Run audit: `python scripts/audit_missing_locaties.py`
2. Run safety check: `python scripts/verify_public_safe.py` →
   moet 0 leaks tonen
3. `rm import_/{klant_mapping,seed_data,pdf_parser}_local.py`
4. Verwijder de 3 ignore-regels uit `.gitignore`
5. Verwijder `KLANT_LOCATIES` + `seed_klant_locaties` + de oproep in
   `seed_all`
6. Verwijder `scripts/audit_missing_locaties.py` en
   `scripts/verify_public_safe.py`

## Public-safety verificatie (refined — codex round-3 finding 4)

Vorige versie zou `Groningen` flaggen door `Doktersdienst Groningen`
(false positive op stadsnaam). Refined approach:

```python
# scripts/verify_public_safe.py
# Categoriseer tokens per type, flag alleen wat écht persoonlijk is.

import sqlite3, pathlib, subprocess, sys

DB = pathlib.Path.home() / 'Library/Application Support/Boekhouding/data/boekhouding.sqlite3'

CITY_ALLOWLIST = {  # publieke geografie — niet leak-worthy
    'Groningen', 'Zuidhorn', 'Stadskanaal', 'Delfzijl', 'Scheemda',
    'Assen', 'Hoogeveen', 'Emmen', 'Vlagtwedde', 'Marum', 'Winsum',
    'Smilde', 'Sellingen', 'De Wilp', 'Drenthe',
}
GENERIC_ALLOWLIST = {  # algemene vakwoorden
    'Huisarts', 'Huisartsen', 'Huisartsenpraktijk', 'Huisartspraktijk',
    'HAP', 'Centrum', 'Praktijk', 'Spoedpost', 'Doktersdienst',
}

conn = sqlite3.connect(DB)

# Volledige strings = altijd checken (nooit alleen fragments)
full_tokens = set()
for r in conn.execute('SELECT naam FROM klanten'):
    full_tokens.add(r[0])
bg = conn.execute('SELECT naam, bedrijfsnaam, adres, postcode_plaats, '
                  'telefoon, email, kvk, iban FROM bedrijfsgegevens'
                  ).fetchone() or ()
full_tokens.update(t for t in bg if t and len(t) >= 4)

# Persoonlijke fragments: achternamen uit klanten (na splitsing).
# Een fragment telt als "persoonlijk" als:
#   - len >= 4
#   - capitalised (eerste letter upper)
#   - NIET in CITY_ALLOWLIST of GENERIC_ALLOWLIST
fragment_tokens = set()
for naam in [r[0] for r in conn.execute('SELECT naam FROM klanten')]:
    for part in naam.replace('.', ' ').split():
        if (len(part) >= 4 and part[0].isupper()
            and part not in CITY_ALLOWLIST
            and part not in GENERIC_ALLOWLIST):
            fragment_tokens.add(part)

leaks = []
for token in sorted(full_tokens | fragment_tokens):
    result = subprocess.run(['git', 'grep', '-l', '-F', token],
                            capture_output=True, text=True)
    if result.stdout.strip():
        for path in result.stdout.strip().split('\n'):
            if 'verify_public_safe' in path or '.git-scrub' in path:
                continue
            # Show context (first matching line)
            ctx = subprocess.run(['git', 'grep', '-n', '-F', token, path],
                                 capture_output=True, text=True).stdout.strip().split('\n')[0]
            leaks.append((token, path, ctx))

if leaks:
    print(f'❌ {len(leaks)} potential leaks (review context):')
    for token, path, ctx in leaks:
        print(f'  [{token}] {ctx}')
    sys.exit(1)
print('✅ public-safe: 0 leaks')
```

Run dit als laatste stap vóór force-push.

## Test-strategie

Bestaande pytest fixture `db` (`tests/conftest.py:18`) — async DB via
`init_db(tmp_path/'test.sqlite3')`.

**Tests gebruiken `add_klant()` helper** (codex round-2 finding 8) want
`klanten.tarief_uur REAL NOT NULL CHECK >= 0`:

```python
@pytest.fixture
async def db_with_aliases(db):
    from database import add_klant, get_db_ctx
    k1 = await add_klant(db, naam='HAP K14', tarief_uur=100.0)
    k2 = await add_klant(db, naam='Klant2', tarief_uur=100.0)
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES "
            "(?, 'suffix', 'Winsum'), "
            "(?, 'pdf_text', 'Centrum K14'), "
            "(?, 'suffix', 'Klant2')",
            (k1, k1, k2))
        await conn.commit()
    return db, k1, k2
```

**Nieuwe tests:**
- `tests/test_klant_aliases.py`: schema (UNIQUE, COLLATE NOCASE,
  CHECK length, CASCADE delete via klant-removal)
- `tests/test_derive_skip_words.py`: bg=None, normale bg, +31, 0031,
  lege telefoon (< 6 digits), lege email
- `tests/test_remember_alias.py`: insert + conflict-detect + idempotent
  same-klant
- `tests/test_resolve_klant_strategy_order.py`: direct-name vóór fuzzy;
  length>=3 filtert 1-char aliases; tie-break deterministisch
- `tests/test_klanten_page_aliases.py`: `/klanten` UI test — voeg alias
  toe, verschijnt in lijst, delete werkt

**Refactored:**
- `TestResolveKlant` + `TestResolveANWKlant` (`tests/test_pdf_parser.py`):
  monkeypatch fixture verdwijnt; gebruiken `db_with_aliases`. ≈17 tests
  worden async en krijgen DB-fixture.

**Geschatte totaal**: 1008 → 1025-1035 (incl. nieuwe tests). Exact
aantal hangt af van breakdown van CRUD-UI tests.

## Risico's & mitigatie

| Risico | Impact | Mitigatie |
|---|---|---|
| Migration 34 race / row_factory crash | Eerste startup faalt na update | row_factory pattern uit migratie 27 (geverifieerd in code) |
| Auto-learn registreert verkeerd | Verkeerde import in toekomst | Conflict-detectie + UI delete in /klanten |
| `derive_skip_words` mist token-variant | Eigen header parseert als klant_name | Auto-learn + handmatige klant-keuze vangt op |
| Async-conversie breekt caller | Runtime fail | Pyright + grep verifies enige callers |
| Schrappen `KLANT_LOCATIES` verbreekt iets | Audit toont eerst | Pre-flight script + handmatig review |
| Customer-name leak (Zwart, etc.) | Repo niet veilig publiek | `verify_public_safe.py` tot 0 leaks |
| /klanten UI breekt op alias-edit edge case | Klein UI-bug | Test class voor de UI |

## Volledigheid t.o.v. doel

1. ✅ Repo veilig publiek na cleanup: `verify_public_safe.py` → 0 leaks
2. ✅ App blijft werken: `derive_skip_words` reproduceert + auto-learn
   vult gaten
3. ✅ Re-clone safe: alle data in DB; verse clone start zonder missing
   files
4. ✅ Nieuwe alias-varianten: auto-learn + manuele klant-keuze + CRUD UI
5. ✅ Verkeerde auto-leer corrigeerbaar: conflict-detectie + UI delete

## Wat dit NIET oplost (out of scope)

- Geautomatiseerde detection of NIEUWE customer-names op het moment dat
  een klant wordt toegevoegd → out of scope. `verify_public_safe.py`
  draait je periodiek handmatig (of via pre-commit hook later).
- Klant-rename ripple: als gebruiker een klant herneemt, blijven oude
  aliases met oude pattern intact (correct gedrag); maar verify-script
  flagt de oude naam mogelijk niet meer als leak — accept.
- ANW-filename auto-learn → te variabel; user kan via /klanten CRUD UI
  alias toevoegen.

## Deliverables (definitief)

1. `database.py`: SCHEMA_SQL `klant_aliases` + migratie 33 (schema) +
   migratie 34 (data callable, met row_factory pattern) +
   `get_klant_aliases` / `add_klant_alias` / `delete_klant_alias` /
   `update_klant_alias_target` helpers
2. `import_/klant_mapping.py`: 4 strategies async DB-queries; verwijder
   try-import-from-local
3. `import_/skip_words.py` (nieuw): GENERIC + `_normalize_phone_digits`
   + `derive_skip_words`
4. `import_/pdf_parser.py`: `_extract_klant_name(text, skip_words=None)`
   case-insensitive; verwijder try-import + module-state
5. `pages/facturen.py`: callers updaten (await + skip_words injection +
   auto-learn checkbox + remember_alias + conflict-resolutie dialog)
6. `pages/klanten.py`: alias-CRUD sectie per klant (lijst + add + delete)
7. `import_/seed_data.py`: verwijder `KLANT_LOCATIES` +
   `seed_klant_locaties`; pas `seed_all` aan
8. `tests/test_pdf_parser.py`: refactor naar DB-fixtures via
   `add_klant()`; verwijder `_stub_klant_mapping` + `MOCK_KLANTEN`
9. `tests/test_klant_aliases.py` (nieuw)
10. `tests/test_derive_skip_words.py` (nieuw)
11. `tests/test_remember_alias.py` (nieuw)
12. `tests/test_resolve_klant_strategy_order.py` (nieuw)
13. `tests/test_klanten_page_aliases.py` (nieuw)
14. `tests/test_archive_factuur.py`: scrub `Zwart` → placeholder
15. `scripts/audit_missing_locaties.py` (tijdelijk)
16. `scripts/verify_public_safe.py` (tijdelijk)
17. `rm` 3 `_local.py` files; clean `.gitignore`
18. Force-push naar GitHub (na verify_public_safe groen)
