# Invoice Status Lifecycle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the binary `betaald` flag with a three-state status lifecycle (concept → verstuurd → betaald) with email sending and proper status transitions.

**Architecture:** Schema-first approach. Add migration, update model, then sweep all code references. Email sending via macOS AppleScript.

**Tech Stack:** NiceGUI 3.x, SQLite via aiosqlite, Python 3.12+, AppleScript (macOS mail)

**Spec:** `docs/superpowers/specs/2026-03-22-invoice-status-lifecycle.md`

**Test command:** `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

---

## File Structure

| File | Action | What |
|------|--------|------|
| `database.py` | Modify | Migration 14+15, `update_factuur_status()`, update all `WHERE betaald` SQL |
| `models.py` | Modify | Replace `betaald: bool` with `status: str` in Factuur |
| `pages/facturen.py` | Modify | Status badges, filters, menu actions, KPIs, email send |
| `pages/bank.py` | Modify | Update 1 raw SQL query |
| `pages/jaarafsluiting.py` | Modify | Update 1 raw SQL integrity check |
| `components/invoice_builder.py` | Modify | Set `status='concept'` on creation |
| `tests/test_facturen.py` | Modify | Update all betaald references |
| `tests/test_db_queries.py` | Modify | Update all betaald references |
| `tests/test_aangifte.py` | Modify | Update betaald kwargs |

---

### Task 1: Schema migration + model update + core DB functions

**Files:**
- Modify: `database.py` — add migrations 14 (status column) + 15 (klant email), rewrite `mark_betaald` → `update_factuur_status`, update `add_factuur`, `get_facturen` row mapping, all `WHERE betaald` SQL
- Modify: `models.py` — update Factuur dataclass

**Migrations to add (after existing migration 13):**

```python
(14, "add_factuur_status_column", [
    "ALTER TABLE facturen ADD COLUMN status TEXT DEFAULT 'concept'",
    "UPDATE facturen SET status = CASE WHEN betaald = 1 THEN 'betaald' ELSE 'verstuurd' END",
]),
(15, "add_klant_email", [
    "ALTER TABLE klanten ADD COLUMN email TEXT DEFAULT ''",
]),
```

**Model change in `models.py`:**

Replace `betaald: bool = False` with `status: str = 'concept'`. Keep `betaald_datum: str = ''`.

**`get_facturen()` row mapping:**

Replace `betaald=bool(r['betaald'])` with `status=r['status'] or 'concept'`.

**New `update_factuur_status()` function** (replaces `mark_betaald`):**

```python
async def update_factuur_status(db_path, factuur_id, status, betaald_datum=''):
    """Update factuur status and cascade to werkdagen.

    Status: 'concept', 'verstuurd', 'betaald'
    Werkdagen cascade: betaald→'betaald', others→'gefactureerd'
    """
```

**Keep `mark_betaald()` as a thin wrapper** for backward compatibility (bank matching code calls it):

```python
async def mark_betaald(db_path, factuur_id, datum='', betaald=True):
    status = 'betaald' if betaald else 'verstuurd'
    await update_factuur_status(db_path, factuur_id, status, betaald_datum=datum)
```

**Update all `WHERE betaald = 0` SQL queries:**

| Function | Current | New |
|----------|---------|-----|
| `get_openstaande_facturen` | `WHERE f.betaald = 0` | `WHERE f.status = 'verstuurd'` |
| `get_debiteuren_op_peildatum` | `betaald = 0 OR (betaald = 1 AND ...)` | `status != 'betaald' OR (status = 'betaald' AND ...)` |
| `find_factuur_matches` (line 1779) | `WHERE betaald = 0` | `WHERE status IN ('verstuurd', 'concept')` |
| `auto_match_betaald_datum` (line 1868) | `SET betaald = 1, betaald_datum = ?` | `SET status = 'betaald', betaald_datum = ?` |
| KPIs `get_kpis` (line 1467) | `WHERE betaald = 0` | `WHERE status = 'verstuurd'` |

**`add_factuur()` update:** Accept `status='concept'` instead of `betaald=0`. Insert `status` column.

- [ ] **Step 1: Add migrations, update model, rewrite DB functions**
- [ ] **Step 2: Run tests — expect FAILURES in test files (they still use `betaald=`)**
- [ ] **Step 3: Commit database + model changes**

```bash
git add database.py models.py
git commit -m "feat: invoice status lifecycle — migration 14+15, update_factuur_status, status column"
```

---

### Task 2: Update all test files

**Files:**
- Modify: `tests/test_facturen.py`
- Modify: `tests/test_db_queries.py`
- Modify: `tests/test_aangifte.py`

Replace all `betaald=0` with `status='verstuurd'`, `betaald=1` with `status='betaald'` in `add_factuur()` calls.

Replace `f.betaald` / `assert row['betaald'] == 1` assertions with `f.status` / `assert row['status'] == 'betaald'`.

Update `test_mark_betaald` to test `update_factuur_status` (or keep testing via the `mark_betaald` wrapper).

- [ ] **Step 1: Update all test files**
- [ ] **Step 2: Run tests — all should pass now**
- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test: update all tests for factuur status lifecycle (betaald → status)"
```

---

### Task 3: Update facturen page — badges, filters, menu actions

**Files:**
- Modify: `pages/facturen.py`

**Status badge slot** (replaces current 3-state):
```html
<q-badge v-if="props.row.status === 'betaald'" color="positive" label="Betaald" />
<q-badge v-else-if="props.row.verlopen" color="negative" label="Verlopen" />
<q-badge v-else-if="props.row.status === 'verstuurd'" color="info" label="Verstuurd" />
<q-badge v-else color="grey" label="Concept" />
```

**Status filter** — update options:
```python
{'': 'Alle', 'concept': 'Concept', 'verstuurd': 'Verstuurd', 'verlopen': 'Verlopen', 'betaald': 'Betaald'}
```

**Filter logic:**
```python
if status_val == 'concept':
    facturen = [f for f in facturen if f.status == 'concept']
elif status_val == 'verstuurd':
    facturen = [f for f in facturen if f.status == 'verstuurd' and not _is_verlopen(f.datum)]
elif status_val == 'verlopen':
    facturen = [f for f in facturen if f.status == 'verstuurd' and _is_verlopen(f.datum)]
elif status_val == 'betaald':
    facturen = [f for f in facturen if f.status == 'betaald']
```

**Verlopen computation:** Only for `status == 'verstuurd'` (not concept).

**Menu actions** — update `v-if` conditions:
```html
<!-- Concept actions -->
<q-item v-if="props.row.status === 'concept'" @click="$parent.$emit('sendmail', props.row)">
    Verstuur via e-mail
</q-item>
<q-item v-if="props.row.status === 'concept'" @click="$parent.$emit('markverstuurd', props.row)">
    Markeer als verstuurd
</q-item>

<!-- Verstuurd actions -->
<q-item v-if="props.row.status === 'verstuurd'" @click="$parent.$emit('markbetaald', props.row)">
    Markeer betaald
</q-item>

<!-- Betaald actions -->
<q-item v-if="props.row.status === 'betaald'" @click="$parent.$emit('markonbetaald', props.row)">
    Markeer onbetaald
</q-item>
```

**Row data:** Replace `'betaald': f.betaald` with `'status': f.status`.

**KPI strip:** Update to use status:
```python
openstaand = sum(f.totaal_bedrag for f in facturen if f.status == 'verstuurd')
```

**CSV export:** Replace `'Betaald' if f.betaald else 'Openstaand'` with `f.status.capitalize()`.

**Edit dialog betaald checkbox:** Replace with status select:
```python
edit_status = ui.select(
    {'concept': 'Concept', 'verstuurd': 'Verstuurd', 'betaald': 'Betaald'},
    label='Status', value=row['status'])
```

- [ ] **Step 1: Update all facturen.py references**
- [ ] **Step 2: Run tests**
- [ ] **Step 3: Commit**

```bash
git add pages/facturen.py
git commit -m "feat: facturen page — 4-state status badges, filters, menu actions"
```

---

### Task 4: Update bank.py, jaarafsluiting.py, invoice_builder.py

**Files:**
- Modify: `pages/bank.py:150` — change `WHERE f.betaald = 0` to `WHERE f.status IN ('verstuurd', 'concept')`
- Modify: `pages/jaarafsluiting.py:564-577` — change `WHERE betaald=1` to `WHERE status = 'betaald'`
- Modify: `components/invoice_builder.py` — set `status='concept'` in `add_factuur()` call

- [ ] **Step 1: Update all three files**
- [ ] **Step 2: Run full test suite**
- [ ] **Step 3: Commit**

```bash
git add pages/bank.py pages/jaarafsluiting.py components/invoice_builder.py
git commit -m "feat: update bank, jaarafsluiting, invoice builder for status lifecycle"
```

---

### Task 5: Email sending via AppleScript

**Files:**
- Modify: `pages/facturen.py` — add `send_invoice_email()` handler

Add a function that composes an email in Mail.app:

```python
async def send_invoice_email(row):
    """Open Mail.app with pre-composed invoice email + PDF attached."""
    pdf_path = row.get('pdf_pad', '')
    if not pdf_path or not Path(pdf_path).exists():
        ui.notify('PDF niet gevonden', type='warning')
        return

    # Get klant email
    klant_id = row.get('klant_id')
    klant_email = ''
    if klant_id:
        klanten_list = await get_klanten(DB_PATH, alleen_actief=False)
        klant = next((k for k in klanten_list if k.id == klant_id), None)
        if klant:
            klant_email = getattr(klant, 'email', '') or ''

    # Get business info
    bg = await get_bedrijfsgegevens(DB_PATH)

    nummer = row['nummer']
    bedrag = format_euro(row['totaal_bedrag'])
    iban = bg.iban if bg else ''
    bedrijfsnaam = bg.bedrijfsnaam if bg else ''
    naam = bg.naam if bg else ''

    subject = f'Factuur {nummer}'
    body = (
        f'Bijgaand stuur ik u factuur {nummer}.\n\n'
        f'Het totaalbedrag van {bedrag} verzoek ik u binnen 14 dagen '
        f'over te maken op rekeningnummer {iban} t.n.v. {bedrijfsnaam}, '
        f'onder vermelding van factuurnummer {nummer}.\n\n'
        f'Mocht u vragen hebben, dan hoor ik het graag.\n\n\n'
        f'Met vriendelijke groet,\n\n'
        f'{naam}\n\n'
        f'{bedrijfsnaam}\n'
    )
    if bg:
        body += f'Tel: 06 0000 0000\ninfo@testbedrijf.nl'

    # Escape for AppleScript
    body_escaped = body.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    subject_escaped = subject.replace('"', '\\"')

    applescript = f'''
    tell application "Mail"
        set newMessage to make new outgoing message with properties {{subject:"{subject_escaped}", content:"{body_escaped}", visible:true}}
        tell newMessage
            {"make new to recipient with properties {address:" + '"' + klant_email + '"' + "}" if klant_email else ""}
            make new attachment with properties {{file name:POSIX file "{pdf_path}"}} at after last paragraph of content
        end tell
        activate
    end tell
    '''

    await asyncio.to_thread(
        subprocess.run, ['osascript', '-e', applescript],
        capture_output=True, timeout=10)

    # Update status to verstuurd
    await update_factuur_status(DB_PATH, row['id'], 'verstuurd')
    ui.notify(f'Factuur {nummer} geopend in Mail', type='positive')
    await refresh_table()
```

Wire to event: `table.on('sendmail', lambda e: send_invoice_email(e.args))`

Also add "Markeer als verstuurd" handler:
```python
async def on_mark_verstuurd(e):
    row = e.args
    await update_factuur_status(DB_PATH, row['id'], 'verstuurd')
    ui.notify(f"Factuur {row['nummer']} gemarkeerd als verstuurd", type='positive')
    await refresh_table()
```

- [ ] **Step 1: Add email send + mark verstuurd handlers**
- [ ] **Step 2: Test manually — create concept invoice, send via email**
- [ ] **Step 3: Run full test suite**
- [ ] **Step 4: Commit**

```bash
git add pages/facturen.py
git commit -m "feat: email sending via AppleScript + mark verstuurd action"
```

---

### Task 6: Final verification

- [ ] **Step 1: Run full test suite**
- [ ] **Step 2: Test the complete lifecycle manually:**
  - Create new invoice → should be "Concept" (grey)
  - Click "Bewerken" on concept → should reopen builder
  - Click "Verstuur via e-mail" → Mail.app opens with email + PDF → status becomes "Verstuurd" (blue)
  - Wait for due date or click "Markeer betaald" → status becomes "Betaald" (green)
  - Click "Markeer onbetaald" → reverts to "Verstuurd"
  - Check dashboard — concept invoices should NOT count in omzet
  - Check status filter — all 4 options work
  - Check KPI strip — shows correct amounts per status
- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: invoice status lifecycle — final polish"
```
