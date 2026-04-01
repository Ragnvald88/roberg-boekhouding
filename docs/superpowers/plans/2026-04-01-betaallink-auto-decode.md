# Betaallink Auto-Decode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-extract Rabobank betaalverzoek URLs from uploaded QR images and include them as clickable hyperlinks in invoice emails.

**Architecture:** When a QR image is uploaded in the invoice builder, `cv2.QRCodeDetector` decodes the URL. The URL is stored in a new `betaallink` column on the `facturen` table. The email template switches to HTML content when a betaallink exists, embedding the link as a clickable `<a>` tag in the mail body.

**Tech Stack:** opencv-python (cv2.QRCodeDetector), AppleScript `html content` property for Mail.app

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `database.py` | Modify | Migration 23: add `betaallink` column to facturen |
| `models.py` | Modify | Add `betaallink` field to Factuur dataclass |
| `components/invoice_builder.py` | Modify | Decode QR on upload, show link, pass to save |
| `pages/facturen.py` | Modify | Fetch betaallink for email, switch to HTML content |
| `tests/test_database.py` | Modify | Test migration 23, betaallink persistence |
| `tests/test_facturen.py` | Modify | Test HTML email body generation |

---

### Task 1: Database — add betaallink column

**Files:**
- Modify: `database.py:62-76` (SCHEMA_SQL facturen table)
- Modify: `database.py:354-357` (MIGRATIONS list)
- Modify: `models.py:66-80` (Factuur dataclass)
- Test: `tests/test_database.py`

- [ ] **Step 1: Write failing test for betaallink column**

In `tests/test_database.py`, add:

```python
@pytest.mark.asyncio
async def test_factuur_betaallink_persisted(tmp_db):
    """Betaallink is stored and retrieved from facturen."""
    kid = await add_klant(tmp_db, naam='Test')
    fid = await save_factuur_atomic(
        tmp_db, nummer='2026-099', klant_id=kid, datum='2026-01-01',
        totaal_bedrag=100.0, pdf_pad='', type='factuur',
        betaallink='https://betaalverzoek.rabobank.nl/betaalverzoek/?id=abc123',
    )
    facturen = await get_facturen(tmp_db)
    f = next(f for f in facturen if f.id == fid)
    assert f.betaallink == 'https://betaalverzoek.rabobank.nl/betaalverzoek/?id=abc123'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py::test_factuur_betaallink_persisted -v`
Expected: FAIL — `betaallink` not a valid column / attribute

- [ ] **Step 3: Add betaallink to schema, model, and migration**

In `database.py` SCHEMA_SQL, add to the `facturen` CREATE TABLE (after `regels_json`):

```sql
    betaallink TEXT DEFAULT ''
```

In `database.py` MIGRATIONS list, after migration 22, add:

```python
    (23, "add_betaallink_to_facturen", [
        "ALTER TABLE facturen ADD COLUMN betaallink TEXT DEFAULT ''",
    ]),
```

In `models.py` Factuur dataclass, add field:

```python
    betaallink: str = ''
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_database.py::test_factuur_betaallink_persisted -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -x -q`
Expected: All pass, 0 failures

- [ ] **Step 6: Commit**

```bash
git add database.py models.py tests/test_database.py
git commit -m "feat: add betaallink column to facturen (migration 23)"
```

---

### Task 2: Invoice builder — auto-decode QR and store betaallink

**Files:**
- Modify: `components/invoice_builder.py:656-664` (handle_qr_upload)
- Modify: `components/invoice_builder.py:681-711` (_render_qr_indicator)
- Modify: `components/invoice_builder.py:888-900` (save_factuur_atomic call in generate)
- Modify: `components/invoice_builder.py:970-984` (save_factuur_atomic call in concept save)

- [ ] **Step 1: Add QR decode helper function**

At the top of `components/invoice_builder.py`, add import:

```python
import cv2
import numpy as np
```

Add a helper function (near the top, outside `open_invoice_builder`):

```python
def _decode_qr_url(image_bytes: bytes) -> str:
    """Decode a QR image and return the URL, or '' if decoding fails."""
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return ''
    data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    return data if data and data.startswith('http') else ''
```

- [ ] **Step 2: Modify handle_qr_upload to decode and store the URL**

In `handle_qr_upload` (line 656), after `_qr_bytes['data'] = content`, add decoding:

```python
async def handle_qr_upload(e):
    nonlocal preview_qr_url
    content = await e.file.read()
    _qr_bytes['data'] = content
    _b64 = base64.b64encode(content).decode('ascii')
    preview_qr_url = f'data:image/png;base64,{_b64}'
    # Decode betaallink from QR
    _qr_bytes['betaallink'] = _decode_qr_url(content)
    _render_qr_indicator(True)
    ui.notify('QR-code toegevoegd', type='positive')
    schedule_preview_update()
```

Also update `_qr_bytes` initialization (line ~180 area where it's defined) to include betaallink:

```python
_qr_bytes = {'data': b'', 'betaallink': ''}
```

And when restoring QR from concept (line ~188-192 area), also restore betaallink:

```python
if _qr_bytes['data']:
    _qr_bytes['betaallink'] = _decode_qr_url(_qr_bytes['data'])
```

- [ ] **Step 3: Show decoded betaallink in QR indicator**

In `_render_qr_indicator`, when `exists=True`, add a truncated link label:

```python
def _render_qr_indicator(exists: bool):
    qr_indicator.clear()
    with qr_indicator:
        if exists:
            ui.icon('qr_code_2', size='xs', color='positive')
            ui.label('QR-code actief').classes('text-caption text-grey-7')
            ui.space()
            ui.button(
                'Vervangen', icon='swap_horiz',
            ).on(
                'click', js_handler=_pick_qr_js,
            ).props('flat dense size=sm color=grey-7 no-caps')
            # Show decoded betaallink
            link = _qr_bytes.get('betaallink', '')
            if link:
                with ui.row().classes('w-full items-center gap-1 q-mt-xs'):
                    ui.icon('link', size='xs', color='grey-6')
                    ui.label(link[:50] + ('…' if len(link) > 50 else '')).classes(
                        'text-caption text-grey-6').style('word-break: break-all')
        else:
            ui.icon('qr_code_2', size='xs', color='grey-4')
            ui.label('Geen QR-code').classes('text-caption text-grey-5')
            ui.space()
            ui.button(
                'Toevoegen', icon='add',
            ).on(
                'click', js_handler=_pick_qr_js,
            ).props('flat dense size=sm color=primary no-caps')
```

- [ ] **Step 4: Pass betaallink to save_factuur_atomic in generate**

In the `generate_factuur` function (around line 888-900), add `betaallink` to the `save_factuur_atomic` call:

```python
await save_factuur_atomic(
    DB_PATH,
    replacing_factuur_id=replacing_factuur_id,
    werkdag_ids=werkdag_ids or None,
    nummer=nummer,
    klant_id=kid,
    datum=factuur_datum,
    totaal_uren=totaal_uren,
    totaal_km=totaal_km,
    totaal_bedrag=totaal_bedrag,
    pdf_pad=str(pdf_path),
    type=factuur_type,
    betaallink=_qr_bytes.get('betaallink', ''),
)
```

- [ ] **Step 5: Pass betaallink to save_factuur_atomic in concept save**

In `opslaan_als_concept` (around line 970-984), add `betaallink`:

```python
await save_factuur_atomic(
    DB_PATH,
    replacing_factuur_id=replacing_factuur_id,
    werkdag_ids=werkdag_ids or None,
    nummer=nummer,
    klant_id=kid,
    datum=factuur_datum,
    totaal_uren=totaal_uren,
    totaal_km=totaal_km,
    totaal_bedrag=totaal_bedrag,
    pdf_pad='',
    type=factuur_type,
    status='concept',
    regels_json=json.dumps(regels_data),
    betaallink=_qr_bytes.get('betaallink', ''),
)
```

- [ ] **Step 6: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add components/invoice_builder.py
git commit -m "feat: auto-decode betaallink from QR upload in invoice builder"
```

---

### Task 3: Email template — HTML with clickable betaallink

**Files:**
- Modify: `pages/facturen.py:919-1007` (on_send_mail function)
- Test: `tests/test_facturen.py`

- [ ] **Step 1: Write test for HTML email body with betaallink**

In `tests/test_facturen.py`, add a test that validates the email body generation logic. Since the actual email sending uses AppleScript and can't be unit-tested, extract the body-building into a testable helper. Add to `pages/facturen.py`:

```python
def _build_mail_body(nummer, bedrag, iban, bedrijfsnaam, naam, telefoon, bg_email, betaallink=''):
    """Build email body text. Returns (body, is_html) tuple."""
    tel_line = f'Tel: {telefoon}' if telefoon else ''

    if betaallink:
        body = (
            f'<div style="font-family: Helvetica, Arial, sans-serif; font-size: 14px; color: #333;">'
            f'<p>Bijgaand stuur ik u factuur {nummer}.</p>'
            f'<p>Het totaalbedrag van {bedrag} verzoek ik u binnen 14 dagen '
            f'over te maken op rekeningnummer {iban} t.n.v. {bedrijfsnaam}, '
            f'onder vermelding van factuurnummer {nummer}.</p>'
            f'<p>U kunt ook direct betalen via '
            f'<a href="{betaallink}">deze betaallink</a>.</p>'
            f'<p>Mocht u vragen hebben, dan hoor ik het graag.</p>'
            f'<br>'
            f'<p>Met vriendelijke groet,</p>'
            f'<p>{naam}<br><br>'
            f'{bedrijfsnaam}<br>'
            f'{tel_line + "<br>" if tel_line else ""}'
            f'{bg_email}</p>'
            f'</div>'
        )
        return body, True
    else:
        body = (
            f'Bijgaand stuur ik u factuur {nummer}.\n'
            f'\n'
            f'Het totaalbedrag van {bedrag} verzoek ik u binnen 14 dagen '
            f'over te maken op rekeningnummer {iban} t.n.v. {bedrijfsnaam}, '
            f'onder vermelding van factuurnummer {nummer}.\n'
            f'\n'
            f'Mocht u vragen hebben, dan hoor ik het graag.\n'
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
        return body, False
```

Test in `tests/test_facturen.py`:

```python
from pages.facturen import _build_mail_body

def test_build_mail_body_with_betaallink():
    body, is_html = _build_mail_body(
        '2026-021', '€ 1.097,34', 'NL00 TEST 0000 0000 00',
        'TestBV huisartswaarnemer', 'Test Gebruiker',
        '06 0000 0000', 'info@testbedrijf.nl',
        betaallink='https://betaalverzoek.rabobank.nl/betaalverzoek/?id=abc',
    )
    assert is_html is True
    assert '<a href="https://betaalverzoek.rabobank.nl/betaalverzoek/?id=abc">deze betaallink</a>' in body
    assert 'Bijgaand stuur ik u factuur 2026-021' in body

def test_build_mail_body_without_betaallink():
    body, is_html = _build_mail_body(
        '2026-021', '€ 1.097,34', 'NL00 TEST 0000 0000 00',
        'TestBV huisartswaarnemer', 'Test Gebruiker',
        '06 0000 0000', 'info@testbedrijf.nl',
    )
    assert is_html is False
    assert 'betaallink' not in body
    assert 'Bijgaand stuur ik u factuur 2026-021' in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_facturen.py::test_build_mail_body_with_betaallink tests/test_facturen.py::test_build_mail_body_without_betaallink -v`
Expected: FAIL — `_build_mail_body` not found

- [ ] **Step 3: Implement _build_mail_body and refactor on_send_mail**

Add `_build_mail_body` function to `pages/facturen.py` (module-level, before the page function).

Then refactor `on_send_mail` (line 919-1007) to use it:

```python
async def on_send_mail(e):
    row = e.args
    pdf_path = row.get('pdf_pad', '')
    if not pdf_path or not Path(pdf_path).exists():
        ui.notify('PDF niet gevonden — genereer eerst de factuur', type='warning')
        return

    klant_id = row.get('klant_id')
    klant_email = ''
    if klant_id:
        all_klanten = await get_klanten(DB_PATH, alleen_actief=False)
        klant = next((k for k in all_klanten if k.id == klant_id), None)
        if klant and hasattr(klant, 'email'):
            klant_email = klant.email or ''

    bg = await get_bedrijfsgegevens(DB_PATH)
    nummer = row['nummer']
    bedrag = format_euro(row['totaal_bedrag'])
    iban = bg.iban if bg else ''
    bedrijfsnaam = bg.bedrijfsnaam if bg else ''
    naam = bg.naam if bg else ''
    telefoon = bg.telefoon if bg else ''
    bg_email = bg.email if bg else ''

    # Fetch betaallink from DB
    betaallink = ''
    async with get_db_ctx(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT betaallink FROM facturen WHERE id = ?", (row['id'],))
        r = await cur.fetchone()
        if r and r['betaallink']:
            betaallink = r['betaallink']

    subject = f'Factuur {nummer}'
    body, is_html = _build_mail_body(
        nummer, bedrag, iban, bedrijfsnaam, naam, telefoon, bg_email, betaallink)

    # Escape for AppleScript
    body_osa = body.replace('\\', '\\\\').replace('"', '\\\\"')
    subject_osa = subject.replace('"', '\\\\"')
    pdf_path_abs = str(Path(pdf_path).resolve())

    to_line = ''
    if klant_email:
        to_line = f'make new to recipient with properties {{address:"{klant_email}"}}'

    # Use html content property when betaallink present
    if is_html:
        content_prop = f'html content:"{body_osa}"'
    else:
        content_prop = f'content:"{body_osa}"'

    applescript = (
        'tell application "Mail"\n'
        f'  set newMsg to make new outgoing message with properties '
        f'{{subject:"{subject_osa}", {content_prop}, visible:true}}\n'
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
        await asyncio.to_thread(
            subprocess.run,
            ['osascript', '-e', applescript],
            capture_output=True, timeout=15)

        if row.get('status') == 'concept':
            await update_factuur_status(
                DB_PATH, factuur_id=row['id'], status='verstuurd')

        ui.notify(f'Factuur {nummer} geopend in Mail.app', type='positive')
        await refresh_table()
    except subprocess.TimeoutExpired:
        ui.notify('Mail.app reageerde niet — probeer handmatig', type='warning')
    except Exception as ex:
        ui.notify(f'Fout bij openen Mail.app: {ex}', type='negative')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_facturen.py::test_build_mail_body_with_betaallink tests/test_facturen.py::test_build_mail_body_without_betaallink -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -x -q`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add pages/facturen.py tests/test_facturen.py
git commit -m "feat: HTML email with clickable betaallink from QR"
```

---

### Task 4: Manual verification

- [ ] **Step 1: Start app and test full flow**

```bash
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py
```

1. Open invoice builder for an existing klant
2. Upload a Rabobank QR code image
3. Verify the decoded betaallink URL appears below the QR indicator
4. Generate the factuur
5. From the facturen table, click "Verstuur via e-mail"
6. Verify Mail.app opens with HTML email containing clickable "deze betaallink"
7. Verify PDF is still attached
8. Test with an invoice WITHOUT QR — verify plain text email (no betaallink line)

- [ ] **Step 2: Final commit (if any tweaks needed)**

```bash
git add -A
git commit -m "fix: betaallink flow polish"
```
