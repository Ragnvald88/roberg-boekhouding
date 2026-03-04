# Aangifte Documenten Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Nieuwe pagina `/aangifte` met documentchecklist, bestandsupload per categorie, partner-inkomen invoer, en voortgangsindicator voor IB-aangifte voorbereiding.

**Architecture:** Nieuwe `aangifte_documenten` tabel in SQLite voor upload-tracking. Uitbreiding `fiscale_params` met partner-velden. Bestanden in `data/aangifte/{jaar}/{categorie}/`. Nieuwe pagina `pages/aangifte.py` met dialog-based upload, consistent met de rest van de app.

**Tech Stack:** NiceGUI (Quasar/Vue), aiosqlite, raw SQL, Python 3.12+

---

## Referentie: bestaande patronen

- **DB queries**: `database.py` — async met `get_db()`, raw SQL, `?` placeholders
- **Models**: `models.py` — dataclasses
- **Page pattern**: `@ui.page('/route')`, `create_layout('Titel', '/route')`
- **Upload pattern**: `ui.upload(on_upload=handler, auto_upload=True)` → save to `data/` subdir
- **Dialog pattern**: `ui.dialog()` + `ui.card()` voor add/edit (werkdag_form.py, kosten.py)
- **Sidebar nav**: `components/layout.py` PAGES list — voeg route toe
- **Startup dirs**: `main.py` `startup()` — mkdir voor data dirs

## Vaste documenttypes (hardcoded in pagina)

```python
AANGIFTE_DOCS = [
    # (categorie, documenttype, label, meerdere_toegestaan, verplicht)
    ('eigen_woning', 'woz_beschikking', 'WOZ-beschikking', False, True),
    ('eigen_woning', 'hypotheek_jaaroverzicht', 'Hypotheek jaaroverzicht', True, True),
    ('inkomen_partner', 'jaaropgave_partner', 'Jaaropgave partner', True, True),
    ('pensioen', 'upo_eigen', 'UPO eigen pensioen', False, False),
    ('pensioen', 'upo_partner', 'UPO partner', False, False),
    ('bankzaken', 'jaaroverzicht_prive', 'Jaaroverzicht privérekening', True, False),
    ('bankzaken', 'jaaroverzicht_zakelijk', 'Jaaroverzicht zakelijke rekening', True, False),
    ('bankzaken', 'jaaroverzicht_spaar', 'Jaaroverzicht spaarrekening', True, False),
    ('studieschuld', 'duo_overzicht', 'DUO overzicht', False, False),
    ('belastingdienst', 'voorlopige_aanslag', 'Voorlopige aanslag', False, False),
    ('definitieve_aangifte', 'ingediende_aangifte', 'Ingediende aangifte (Boekhouder)', False, False),
]
```

---

### Task 1: Database — nieuwe tabel + migratie

**Files:**
- Modify: `database.py` (SCHEMA_SQL + init_db + CRUD functies)
- Modify: `models.py` (nieuwe dataclass)

**Step 1: Add AangifteDocument dataclass to models.py**

Na `FiscaleParams` toevoegen:
```python
@dataclass
class AangifteDocument:
    id: int = 0
    jaar: int = 0
    categorie: str = ''
    documenttype: str = ''
    bestandsnaam: str = ''
    bestandspad: str = ''
    upload_datum: str = ''
    notitie: str = ''
```

**Step 2: Add CREATE TABLE to SCHEMA_SQL in database.py**

Na de `bedrijfsgegevens` tabel:
```sql
CREATE TABLE IF NOT EXISTS aangifte_documenten (
    id INTEGER PRIMARY KEY,
    jaar INTEGER NOT NULL,
    categorie TEXT NOT NULL,
    documenttype TEXT NOT NULL,
    bestandsnaam TEXT NOT NULL,
    bestandspad TEXT NOT NULL,
    upload_datum TEXT NOT NULL,
    notitie TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_aangifte_docs_jaar ON aangifte_documenten(jaar);
```

**Step 3: Add partner columns migration to init_db()**

In de migratie-loop toevoegen:
```python
('partner_bruto_loon', 0), ('partner_loonheffing', 0),
```

**Step 4: Add partner fields to FiscaleParams dataclass in models.py**

```python
partner_bruto_loon: float = 0.0
partner_loonheffing: float = 0.0
```

**Step 5: Update _row_to_fiscale_params in database.py**

Toevoegen aan de _safe_get sectie:
```python
partner_bruto_loon=_safe_get(r, 'partner_bruto_loon', 0, keys),
partner_loonheffing=_safe_get(r, 'partner_loonheffing', 0, keys),
```

**Step 6: Update update_fiscale_params in database.py**

Partner velden toevoegen aan de UPDATE query.

**Step 7: Add CRUD functies voor aangifte_documenten**

```python
async def get_aangifte_documenten(db_path, jaar):
    """Get all aangifte documents for a year."""

async def add_aangifte_document(db_path, jaar, categorie, documenttype, bestandsnaam, bestandspad, upload_datum, notitie=''):
    """Add a new aangifte document record. Returns id."""

async def delete_aangifte_document(db_path, doc_id):
    """Delete an aangifte document record."""
```

**Step 8: Run tests**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

---

### Task 2: Startup — aangifte directory aanmaken

**Files:**
- Modify: `main.py`

**Step 1: Add aangifte dir to startup()**

```python
(data_dir / "aangifte").mkdir(parents=True, exist_ok=True)
```

---

### Task 3: Sidebar navigatie — aangifte toevoegen

**Files:**
- Modify: `components/layout.py`

**Step 1: Add to PAGES list (vóór Jaarafsluiting)**

```python
('Aangifte', 'fact_check', '/aangifte'),
```

---

### Task 4: Aangifte pagina — basis + partner inkomen

**Files:**
- Create: `pages/aangifte.py`
- Modify: `main.py` (import toevoegen)

**Step 1: Register page in main.py**

```python
import pages.aangifte
```

**Step 2: Create pages/aangifte.py met basisstructuur**

Bevat:
- `@ui.page('/aangifte')` met `create_layout`
- Jaar-selector
- Partner inkomen sectie (bruto loon + loonheffing inputs, opslaan in fiscale_params)
- Voortgangsbalk placeholder
- Lege checklist container

**Partner inkomen UX:**
- Twee `ui.number` velden in een `ui.card`
- Auto-save bij value change (debounced)
- Laadt waarden uit `get_fiscale_params(jaar)`
- Slaat op via `update_fiscale_params(jaar, partner_bruto_loon=..., partner_loonheffing=...)`

---

### Task 5: Aangifte pagina — documentchecklist met upload

**Files:**
- Modify: `pages/aangifte.py`

**Step 1: Add AANGIFTE_DOCS constant**

De vaste lijst documenttypes (zie boven).

**Step 2: Build checklist render function**

Per categorie een sectie met:
- Categorie header (bold label)
- Per documenttype: status icon (✅/☐) + label + geüploade bestanden + upload knop

**Step 3: Upload handler**

Bij upload:
1. Maak `data/aangifte/{jaar}/{categorie}/` directory aan
2. Sla bestand op met originele naam
3. Insert in `aangifte_documenten` tabel
4. Refresh checklist

**Step 4: Download/delete per bestand**

- Download: `ui.download.file(bestandspad)`
- Delete: confirm dialog → delete file + DB record → refresh

**Step 5: Auto-items voor onderneming**

Items "Jaaroverzicht uren/km" en "Winst & verlies" tonen als "→ Beschikbaar via Jaarafsluiting" met link-icoon. Geen upload nodig.

---

### Task 6: Voortgangsindicator

**Files:**
- Modify: `pages/aangifte.py`

**Step 1: Calculate progress**

```python
verplichte_types = [d for d in AANGIFTE_DOCS if d[4]]  # verplicht=True
uploaded_types = set(doc.documenttype for doc in documenten)
# auto items always count as done
done = sum(1 for d in verplichte_types
           if d[1] in uploaded_types or d[1] in AUTO_TYPES)
total = len(verplichte_types)
```

**Step 2: Render progress bar**

```python
ui.linear_progress(value=done/total if total else 0, size='12px')
ui.label(f'{done}/{total} verplichte documenten')
```

---

### Task 7: Tests

**Files:**
- Create: `tests/test_aangifte.py`

**Tests:**
1. `test_add_aangifte_document` — insert + retrieve
2. `test_delete_aangifte_document` — insert + delete + verify gone
3. `test_get_aangifte_documenten_filter_by_year` — twee jaren, filter correct
4. `test_partner_fields_in_fiscale_params` — save + load partner_bruto_loon / partner_loonheffing

---

### Task 8: Verify & cleanup

**Step 1: Run full test suite**
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

**Step 2: Check IDE diagnostics**

**Step 3: Manual smoke test**
- Open `/aangifte`
- Selecteer jaar 2024
- Vul partner inkomen in → verifieer opslaan
- Upload een test-PDF bij WOZ → check bestandspad
- Download het bestand → check inhoud
- Verwijder het bestand → check cleanup
- Check voortgangsbalk update
