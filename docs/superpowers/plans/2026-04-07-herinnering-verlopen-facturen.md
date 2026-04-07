# Herinnering Verlopen Facturen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Herinnering versturen" action for overdue invoices that opens Mail.app with a friendly reminder email + original PDF, and tracks when a reminder was sent.

**Architecture:** One new DB migration adds `herinnering_datum` column to `facturen`. One new function builds the reminder email body. One new handler opens Mail.app via AppleScript (mirrors existing `on_send_mail`). UI changes: new menu item in actions dropdown, tooltip on verlopen badge. Factuur dataclass and row mapper updated to carry the new field.

**Tech Stack:** Python 3.12+, SQLite/aiosqlite, NiceGUI (Quasar/Vue), AppleScript via subprocess

**Spec:** `docs/superpowers/specs/2026-04-06-herinnering-verlopen-facturen-design.md`

---

### Task 1: Database migration — add `herinnering_datum` column

**Files:**
- Modify: `database.py:353-356` (MIGRATIONS list)
- Test: `tests/test_database.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_database.py`, add a test that verifies the `herinnering_datum` column exists with a default empty string:

```python
@pytest.mark.asyncio
async def test_facturen_herinnering_datum_column(db):
    """herinnering_datum column exists with default empty string."""
    from database import get_db_ctx
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("PRAGMA table_info(facturen)")
        cols = {row['name']: row for row in await cur.fetchall()}
        assert 'herinnering_datum' in cols
        assert cols['herinnering_datum']['dflt_value'] == "''"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py::test_facturen_herinnering_datum_column -v`
Expected: FAIL — `herinnering_datum` not in cols

- [ ] **Step 3: Add the migration**

In `database.py`, add migration 24 to the `MIGRATIONS` list after line 355 (the `betaallink` migration):

```python
    (24, "add_herinnering_datum_to_facturen", [
        "ALTER TABLE facturen ADD COLUMN herinnering_datum TEXT DEFAULT ''",
    ]),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py::test_facturen_herinnering_datum_column -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: add herinnering_datum column to facturen (migration 24)"
```

---

### Task 2: Update Factuur dataclass and row mapper

**Files:**
- Modify: `models.py:66-81` (Factuur dataclass)
- Modify: `database.py:706-719` (`_row_to_factuur`)

- [ ] **Step 1: Add `herinnering_datum` field to the Factuur dataclass**

In `models.py`, add after line 80 (`betaallink: str = ''`):

```python
    herinnering_datum: str = ''
```

- [ ] **Step 2: Update `_row_to_factuur` to map the new column**

In `database.py:706-719`, update `_row_to_factuur` to include:

```python
def _row_to_factuur(r) -> Factuur:
    """Convert a joined facturen+klanten row to a Factuur dataclass."""
    return Factuur(
        id=r['id'], nummer=r['nummer'], klant_id=r['klant_id'],
        klant_naam=r['klant_naam'], datum=r['datum'],
        totaal_uren=r['totaal_uren'] or 0,
        totaal_km=r['totaal_km'] or 0,
        totaal_bedrag=r['totaal_bedrag'],
        pdf_pad=r['pdf_pad'], status=r['status'],
        betaald_datum=r['betaald_datum'],
        type=r['type'],
        bron=r['bron'] if 'bron' in r.keys() else 'app',
        betaallink=r['betaallink'] if 'betaallink' in r.keys() else '',
        herinnering_datum=r['herinnering_datum'] if 'herinnering_datum' in r.keys() else '',
    )
```

- [ ] **Step 3: Run existing facturen tests to verify no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_facturen.py -v`
Expected: All existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add models.py database.py
git commit -m "feat: add herinnering_datum to Factuur dataclass and row mapper"
```

---

### Task 3: Build herinnering email body function + tests

**Files:**
- Modify: `pages/facturen.py:37-61` (add `_build_herinnering_body` after `_build_mail_body`)
- Test: `tests/test_facturen.py`

- [ ] **Step 1: Write the failing tests**

Add two tests to `tests/test_facturen.py`:

```python
from pages.facturen import _build_herinnering_body


def test_herinnering_body_with_betaallink():
    """Herinnering body includes betaallink when provided."""
    body = _build_herinnering_body(
        nummer='2026-001', bedrag='€ 1.234,00', datum='1 februari 2026',
        iban='NL00RABO0123456789', bedrijfsnaam='Testpraktijk',
        naam='Dr. Test', telefoon='06-12345678', bg_email='test@test.nl',
        betaallink='https://pay.example.com/123',
    )
    assert 'factuur 2026-001' in body
    assert '€ 1.234,00' in body
    assert '1 februari 2026' in body
    assert 'aan uw aandacht ontsnapt' in body
    assert '7 dagen' in body
    assert 'NL00RABO0123456789' in body
    assert 'https://pay.example.com/123' in body
    assert 'Dr. Test' in body
    assert 'Testpraktijk' in body
    assert '06-12345678' in body


def test_herinnering_body_without_betaallink():
    """Herinnering body omits betaallink paragraph when empty."""
    body = _build_herinnering_body(
        nummer='2026-002', bedrag='€ 500,00', datum='15 maart 2026',
        iban='NL00RABO0123456789', bedrijfsnaam='Testpraktijk',
        naam='Dr. Test', telefoon='', bg_email='test@test.nl',
    )
    assert 'betalen via deze link' not in body
    assert 'factuur 2026-002' in body
    assert '€ 500,00' in body
    # No telefoon → no Tel: line content
    assert 'Tel: ' not in body or 'Tel: \n' in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_facturen.py::test_herinnering_body_with_betaallink tests/test_facturen.py::test_herinnering_body_without_betaallink -v`
Expected: FAIL — `_build_herinnering_body` not found

- [ ] **Step 3: Implement `_build_herinnering_body`**

In `pages/facturen.py`, add after the closing of `_build_mail_body` (after line 61):

```python
def _build_herinnering_body(nummer, bedrag, datum, iban, bedrijfsnaam, naam,
                            telefoon, bg_email, betaallink=''):
    """Build plain text herinnering email body for overdue invoices."""
    betaallink_line = (
        f'U kunt ook eenvoudig betalen via deze link:\n{betaallink}\n'
        if betaallink else ''
    )
    return (
        f'Beste klant,\n'
        f'\n'
        f'Wellicht is het aan uw aandacht ontsnapt, maar ik heb nog geen '
        f'betaling ontvangen voor factuur {nummer} van {datum} ter hoogte '
        f'van {bedrag}.\n'
        f'\n'
        f'Ik verzoek u vriendelijk het bedrag binnen 7 dagen over te maken op '
        f'rekeningnummer {iban} t.n.v. {bedrijfsnaam}, onder vermelding van '
        f'factuurnummer {nummer}.\n'
        f'\n'
        f'{betaallink_line}'
        f'Mocht de betaling reeds onderweg zijn, dan kunt u dit bericht als '
        f'niet verzonden beschouwen. Heeft u vragen, neem dan gerust contact op.\n'
        f'\n'
        f'\n'
        f'Met vriendelijke groet,\n'
        f'\n'
        f'{naam}\n'
        f'\n'
        f'{bedrijfsnaam}\n'
        f'{f"Tel: {telefoon}" if telefoon else ""}\n'
        f'{bg_email}'
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_facturen.py::test_herinnering_body_with_betaallink tests/test_facturen.py::test_herinnering_body_without_betaallink -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pages/facturen.py tests/test_facturen.py
git commit -m "feat: add _build_herinnering_body for overdue invoice reminders"
```

---

### Task 4: Add `on_send_herinnering` handler

**Files:**
- Modify: `pages/facturen.py:1099-1109` (add handler after `on_send_mail`, register event)

- [ ] **Step 1: Implement `on_send_herinnering`**

In `pages/facturen.py`, add after `on_send_mail` (after line 1099) and before the event registrations (line 1101):

```python
        async def on_send_herinnering(e):
            """Send reminder email for overdue invoice via macOS Mail.app."""
            row = e.args
            pdf_path = row.get('pdf_pad', '')
            nummer = row['nummer']

            if not pdf_path or not Path(pdf_path).exists():
                ui.notify('Geen PDF gevonden voor deze factuur', type='warning')
                return

            all_klanten = await get_klanten(DB_PATH, alleen_actief=False)
            bg = await get_bedrijfsgegevens(DB_PATH)
            klant_obj = next(
                (k for k in all_klanten if k.id == row.get('klant_id')), None)
            klant_email = (klant_obj.email or '') if klant_obj and hasattr(klant_obj, 'email') else ''

            bedrag = format_euro(row['totaal_bedrag'])
            datum_fmt = format_datum(row['datum'])
            iban = bg.iban if bg else ''
            bedrijfsnaam = bg.bedrijfsnaam if bg else ''
            naam = bg.naam if bg else ''
            telefoon = bg.telefoon if bg else ''
            bg_email_addr = bg.email if bg else ''

            betaallink = ''
            async with get_db_ctx(DB_PATH) as conn:
                cur = await conn.execute(
                    "SELECT betaallink FROM facturen WHERE id = ?", (row['id'],))
                r = await cur.fetchone()
                if r and r['betaallink']:
                    betaallink = r['betaallink']

            subject = f'Herinnering: Factuur {nummer}'
            body = _build_herinnering_body(
                nummer, bedrag, datum_fmt, iban, bedrijfsnaam, naam,
                telefoon, bg_email_addr, betaallink)

            body_osa = body.replace('\\', '\\\\').replace('"', '\\"')
            subject_osa = subject.replace('"', '\\"')
            pdf_path_abs = str(Path(pdf_path).resolve())

            to_line = ''
            if klant_email:
                to_line = f'make new to recipient with properties {{address:"{klant_email}"}}'

            applescript = (
                'tell application "Mail"\n'
                f'  set newMsg to make new outgoing message with properties '
                f'{{subject:"{subject_osa}", content:"{body_osa}", visible:true}}\n'
                f'  tell newMsg\n'
                f'    {to_line}\n'
                f'    make new attachment with properties '
                f'{{file name:POSIX file "{pdf_path_abs}"}} '
                f'at after last paragraph of content\n'
                f'  end tell\n'
                f'  activate\n'
                f'end tell'
            )

            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ['osascript', '-e', applescript],
                    capture_output=True, timeout=15)
                if result.returncode != 0:
                    err = result.stderr.decode().strip() if result.stderr else 'onbekende fout'
                    ui.notify(f'Mail.app fout: {err}', type='negative')
                    return

                # Store herinnering date
                async with get_db_ctx(DB_PATH) as conn:
                    await conn.execute(
                        "UPDATE facturen SET herinnering_datum = ? WHERE id = ?",
                        (date.today().isoformat(), row['id']))
                    await conn.commit()

                ui.notify(f'Herinnering voor {nummer} geopend in Mail.app',
                          type='positive')
                await refresh_table()
            except subprocess.TimeoutExpired:
                ui.notify('Mail.app reageerde niet — probeer handmatig',
                          type='warning')
            except Exception as ex:
                ui.notify(f'Fout bij openen Mail.app: {ex}', type='negative')
```

- [ ] **Step 2: Register the event**

In `pages/facturen.py`, in the event registration block (around line 1101-1109), add:

```python
        table.on('sendherinnering', on_send_herinnering)
```

Add it after the existing `table.on('sendmail', on_send_mail)` line.

- [ ] **Step 3: Run full test suite to verify no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add pages/facturen.py
git commit -m "feat: add on_send_herinnering handler with AppleScript Mail.app integration"
```

---

### Task 5: Add "Herinnering versturen" menu item + herinnering indicator on badge

**Files:**
- Modify: `pages/facturen.py:332-340` (actions dropdown — add menu item after "Verstuur via e-mail")
- Modify: `pages/facturen.py:279-286` (status badge slot — add tooltip)
- Modify: `pages/facturen.py:438-456` (refresh_table row data — add `herinnering_datum`)

- [ ] **Step 1: Add `herinnering_datum` to the row data in `refresh_table`**

In `pages/facturen.py`, inside `refresh_table()`, in the `rows.append({...})` block (around line 438-456), add `herinnering_datum` to the row dict. After the `'bron': f.bron,` line add:

```python
                    'herinnering_datum': f.herinnering_datum,
```

- [ ] **Step 2: Add the "Herinnering versturen" menu item**

In `pages/facturen.py`, in the actions slot (around line 332-340), add the herinnering item **after** the "Verstuur via e-mail" item (after line 340) and **before** the "Markeer als verstuurd" item (line 341):

```html
                            <q-item v-if="props.row.verlopen" clickable
                                @click="() => $parent.$emit('sendherinnering', props.row)">
                                <q-item-section side>
                                    <q-icon name="notification_important" size="xs"
                                            color="warning" />
                                </q-item-section>
                                <q-item-section>Herinnering versturen</q-item-section>
                            </q-item>
```

- [ ] **Step 3: Update the status badge to show herinnering tooltip**

In `pages/facturen.py`, replace the verlopen badge line (line 282):

```html
                <q-badge v-else-if="props.row.verlopen" color="negative" label="Verlopen" />
```

with:

```html
                <q-badge v-else-if="props.row.verlopen" color="negative" label="Verlopen">
                    <q-tooltip v-if="props.row.herinnering_datum">
                        Herinnering verstuurd op {{ props.row.herinnering_datum }}
                    </q-tooltip>
                </q-badge>
```

- [ ] **Step 4: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Manual verification**

Start the app and verify:
1. Navigate to Facturen page
2. Find or create a verlopen invoice (verstuurd + dated > 14 days ago)
3. Open the actions menu — "Herinnering versturen" should appear with a warning-colored bell icon
4. For a non-verlopen invoice, "Herinnering versturen" should NOT appear
5. If the invoice has a `herinnering_datum`, hovering the "Verlopen" badge should show the tooltip

- [ ] **Step 6: Commit**

```bash
git add pages/facturen.py
git commit -m "feat: add herinnering menu item and verlopen badge tooltip"
```

---

### Task 6: Test herinnering_datum storage

**Files:**
- Test: `tests/test_facturen.py`

- [ ] **Step 1: Write integration test for herinnering_datum storage**

Add to `tests/test_facturen.py`:

```python
@pytest.mark.asyncio
async def test_herinnering_datum_stored(seeded_db):
    """Storing herinnering_datum updates the factuur record."""
    from database import get_klanten, get_db_ctx, get_facturen
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_factuur(seeded_db, nummer='2026-010', klant_id=kid,
                      datum='2026-01-01', totaal_bedrag=500,
                      status='verstuurd')

    # Store herinnering date
    async with get_db_ctx(seeded_db) as conn:
        await conn.execute(
            "UPDATE facturen SET herinnering_datum = ? WHERE nummer = ?",
            ('2026-04-07', '2026-010'))
        await conn.commit()

    facturen = await get_facturen(seeded_db)
    f = next(f for f in facturen if f.nummer == '2026-010')
    assert f.herinnering_datum == '2026-04-07'


@pytest.mark.asyncio
async def test_herinnering_datum_default_empty(seeded_db):
    """New facturen have empty herinnering_datum by default."""
    from database import get_klanten, get_facturen
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_factuur(seeded_db, nummer='2026-011', klant_id=kid,
                      datum='2026-03-01', totaal_bedrag=300)

    facturen = await get_facturen(seeded_db)
    f = next(f for f in facturen if f.nummer == '2026-011')
    assert f.herinnering_datum == ''
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_facturen.py::test_herinnering_datum_stored tests/test_facturen.py::test_herinnering_datum_default_empty -v`
Expected: PASS (migration and mapper already in place from tasks 1-2)

- [ ] **Step 3: Run full test suite to confirm no regressions**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_facturen.py
git commit -m "test: add integration tests for herinnering_datum storage"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`
Expected: All tests PASS, 0 failures

- [ ] **Step 2: Manual end-to-end test**

Start the app with `source .venv/bin/activate && export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib && python main.py`

1. Go to Facturen page
2. Find a verlopen invoice (or create one: add werkdag > make factuur > mark verstuurd > set datum to > 14 days ago via DB)
3. Click actions menu → "Herinnering versturen"
4. Verify Mail.app opens with:
   - Subject: "Herinnering: Factuur {nummer}"
   - Friendly body text with "aan uw aandacht ontsnapt"
   - 7-day payment term
   - Betaallink if present
   - Original PDF attached
5. After Mail.app opens, verify the "Verlopen" badge now has a tooltip showing the herinnering date
6. Verify the action does NOT appear for concept, verstuurd (not yet overdue), or betaald invoices
