# Multi-Locatie per Klant — Design Document

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement the corresponding implementation plan.

**Goal:** Enable multiple work locations per client with automatic km distance lookup, so that clients like HAP MiddenLand can have Assen (60 km), Emmen (102 km), and Hoogeveen (128 km) as separate locations.

**Architecture:** New `klant_locaties` table linked to `klanten` via FK. Werkdag form gets a location dropdown that appears after client selection and auto-fills the km field. Invoice generation unchanged (already uses per-werkdag km and locatie text).

**Tech Stack:** SQLite (new table + ALTER TABLE migration), NiceGUI form components, aiosqlite async.

---

## 1. Database Schema

### New table: `klant_locaties`

```sql
CREATE TABLE IF NOT EXISTS klant_locaties (
    id INTEGER PRIMARY KEY,
    klant_id INTEGER NOT NULL REFERENCES klanten(id) ON DELETE CASCADE,
    naam TEXT NOT NULL,
    retour_km REAL DEFAULT 0 CHECK (retour_km >= 0),
    UNIQUE(klant_id, naam)
);
```

### Migration: `werkdagen` gets `locatie_id`

```sql
ALTER TABLE werkdagen ADD COLUMN locatie_id INTEGER REFERENCES klant_locaties(id) ON DELETE SET NULL;
```

### No changes to `klanten`

- `retour_km` stays as fallback for clients with no locations defined
- `adres` remains the invoice address (separate from work location)

## 2. Model

```python
@dataclass
class KlantLocatie:
    id: int
    klant_id: int
    naam: str
    retour_km: float
```

## 3. New DB Functions

- `get_klant_locaties(db, klant_id) -> list[KlantLocatie]`
- `add_klant_locatie(db, klant_id, naam, retour_km) -> int`
- `update_klant_locatie(db, locatie_id, naam, retour_km)`
- `delete_klant_locatie(db, locatie_id)`

## 4. Werkdag Form Behavior

1. User selects a klant
2. System loads klant's locations via `get_klant_locaties()`
3. If locations exist → show location dropdown: `"{naam} ({retour_km} km)"`
4. When location is selected → auto-fill km field with `locatie.retour_km`
5. If klant has 0 locations → no dropdown, km auto-fills from `klant.retour_km`
6. If klant has 1 location → pre-select it, still show dropdown
7. User can always manually override the km field
8. "Opslaan & Nieuw" preserves selected klant AND location

### On save:

- `werkdag.locatie` = location name (text) or klant.adres if no locations
- `werkdag.locatie_id` = location id (int) or NULL
- `werkdag.km` = km field value (auto-filled but editable)

## 5. Instellingen UI

In the klant edit dialog, below existing fields (naam, tarief, adres, km):

**"Locaties" section:**
- Table: Naam | Retour km (km) | Delete (icon button)
- "Locatie toevoegen" button → inline inputs for naam + retour_km + save button
- Each operation (add/delete) is immediate (separate from klant save)
- When klant has locations, show info text: "De locatie-dropdown verschijnt automatisch in het werkdagformulier"

## 6. Seed Data

From the Urenregister Stamgegevens distance table:

```python
KLANT_LOCATIES = {
    'HAP NoordOost': [
        ('Groningen', 12), ('Zuidhorn', 52), ('Stadskanaal', 47),
        ('Delfzijl', 64), ('Scheemda', 60),
    ],
    'HAP MiddenLand': [
        ('Assen', 60), ('Hoogeveen', 128), ('Emmen', 102),
    ],
    'Praktijk K2': [('Vlagtwedde', 108)],
    "Praktijk K6": [('Marum', 54)],
    'K. Klant7': [('Marum', 54)],
    'Praktijk K14': [('Winsum', 44)],
    'Praktijk K10': [('Smilde', 78)],
}
```

Seeded during `init_db` migration: match klant by naam, insert locations.

## 7. Invoice Generation

**No changes needed.** Invoices already use:
- `werkdag.locatie` for the "Reiskosten retour {thuisplaats} — {locatie}" line description
- `werkdag.km` for the km amount calculation

The location dropdown simply makes it easier to fill these fields correctly.

## 8. Files Touched

| File | Change |
|------|--------|
| `database.py` | New table, migration, CRUD functions |
| `models.py` | New `KlantLocatie` dataclass |
| `components/werkdag_form.py` | Location dropdown after klant selection |
| `pages/instellingen.py` | Location sub-section in klant edit dialog |
| `import_/seed_data.py` | KLANT_LOCATIES constant |
| `tests/test_database.py` | Update expected tables set |
| `tests/test_locaties.py` (new) | CRUD + form behavior tests |

## 9. Backward Compatibility

- Existing werkdagen with `locatie_id = NULL` work fine (TEXT `locatie` field still used)
- Existing klanten without locations → werkdag form falls back to `klant.retour_km`
- No existing data is modified; only new data gets structured location references
