# Invoice Builder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the restrictive invoice creation dialog with a two-panel live-preview builder, and redesign the invoice PDF template to match the user's actual invoice style.

**Architecture:** Template-first approach: rewrite the Jinja2 template first (Task 1-2), then build the preview helper (Task 3), then the two-panel dialog (Task 4-5). Each task produces a working commit.

**Tech Stack:** NiceGUI 3.x, Jinja2, WeasyPrint, SQLite via aiosqlite, Python 3.12+

**Spec:** `docs/superpowers/specs/2026-03-21-invoice-builder-design.md`

**Test command:** `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `templates/factuur.html` | Rewrite | Invoice PDF template matching user's actual design |
| `components/invoice_generator.py` | Modify | Support QR code path, structured klant, IBAN in sender |
| `components/invoice_preview.py` | Create | Render invoice HTML for live preview (no PDF) |
| `pages/facturen.py` | Modify | Replace `open_new_factuur_dialog()` with two-panel builder |

---

### Task 1: Rewrite invoice template

**Files:**
- Rewrite: `templates/factuur.html`

The current template uses color `#1a5276`, a blue-bordered client box, paragraph-style payment info, and "Bedrag" column header. The user's actual invoices use `#1a3c5e`, plain "Factuur aan:" label, table-based BETAALINFORMATIE with QR code, and "Totaal" column header.

- [ ] **Step 1: Rewrite the template**

Replace the entire `templates/factuur.html` with a new design matching the user's actual invoices. Key changes:

```html
<!-- Key CSS changes: -->
- Color: #1a5276 → #1a3c5e everywhere
- .sender h1: 16pt (was 15pt)
- .meta h2 (FACTUUR): 27pt, font-weight 800, letter-spacing 2px (was 18pt)
- "Nummer: {{ nummer }}" format instead of table
- "Factuurdatum:" and "Vervaldatum:" as simple lines
- Client section: plain "Factuur aan:" bold label, no box/border
- Client address: {{ klant.naam }}<br>{{ klant.contactpersoon }}<br>{{ klant.adres }}<br>{{ klant.postcode }} {{ klant.plaats }}
- Line items th: last column "Totaal" (was "Bedrag"), padding 2.5mm→3mm
- Table column widths: 15% / auto / 10% / 14% / 14%
- .totals: "TOTAAL" 13pt bold + amount 16pt extra-bold, right-aligned
- BTW notice: 8pt (was 7.5pt)
- BETAALINFORMATIE: HTML table with dark navy header, label column (grey bg), value column, QR cell rowspan=5
- QR: {% if qr_path %}<img src="{{ qr_path }}" style="width:2.5cm;height:2.5cm;object-fit:contain">{% endif %}
- Footer with page numbers: @bottom-right { content: "Pagina " counter(page); }
- Sender block includes IBAN
```

The template should accept these variables:
- `nummer`, `datum`, `vervaldatum` (formatted strings)
- `klant` dict: `naam`, `contactpersoon`, `adres`, `postcode`, `plaats`
- `bedrijf` dict: `bedrijfsnaam`, `naam`, `functie`, `adres`, `postcode_plaats`, `kvk`, `iban`, `thuisplaats`
- `regels` list of dicts: `datum`, `omschrijving`, `aantal`, `tarief`, `bedrag`
- `subtotaal_werk`, `subtotaal_km`, `totaal` (floats)
- `qr_path` (string path to QR image, or empty)

- [ ] **Step 2: Run existing invoice tests**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_facturen.py -v`
Expected: all pass (tests don't verify template HTML, just DB operations)

- [ ] **Step 3: Commit**

```bash
git add templates/factuur.html
git commit -m "feat: redesign invoice template — match user's actual invoice style"
```

---

### Task 2: Update invoice generator for new template vars

**Files:**
- Modify: `components/invoice_generator.py`

Update `generate_invoice()` to:
1. Accept `qr_path` parameter (optional string path to QR image)
2. Pass `qr_path` to the template
3. Support structured klant dict (naam, contactpersoon, adres, postcode, plaats)
4. Include IBAN in the sender/bedrijf context (already passed, just ensure template uses it)

- [ ] **Step 1: Update the function signature and template rendering**

Add `qr_path: str = ''` parameter. In the `template.render()` call, add `qr_path=qr_path`. The QR path should be relative to the template directory or absolute — WeasyPrint resolves paths relative to `base_url`.

For the QR, if a file exists at `data/qr/betaal_qr.png`, pass its absolute path as a `file://` URL:

```python
qr_path_param = ''
if qr_path and Path(qr_path).exists():
    qr_path_param = Path(qr_path).resolve().as_uri()
```

- [ ] **Step 2: Ensure backward compatibility**

The existing callers pass `klant` as `{'naam': ..., 'adres': ...}`. The new template expects `contactpersoon`, `postcode`, `plaats` as separate fields. For backward compatibility, the generator should handle both:

```python
# Ensure klant has all expected fields with defaults
klant_full = {
    'naam': klant.get('naam', ''),
    'contactpersoon': klant.get('contactpersoon', ''),
    'adres': klant.get('adres', ''),
    'postcode': klant.get('postcode', ''),
    'plaats': klant.get('plaats', ''),
}
```

- [ ] **Step 3: Run tests + commit**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
git add components/invoice_generator.py
git commit -m "feat: invoice generator — QR code support, structured klant fields"
```

---

### Task 3: Create invoice preview helper

**Files:**
- Create: `components/invoice_preview.py`

A helper that renders the invoice HTML template (same as the PDF generator but WITHOUT WeasyPrint conversion). Returns HTML string for display in `ui.html()`.

- [ ] **Step 1: Create the module**

```python
"""Render invoice HTML for live preview (no PDF generation)."""

from pathlib import Path
from datetime import datetime, timedelta
from jinja2 import Environment, FileSystemLoader

from components.utils import format_euro, format_datum

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def render_invoice_html(nummer: str, klant: dict, regels: list[dict],
                        factuur_datum: str = '', bedrijfsgegevens: dict = None,
                        qr_path: str = '') -> str:
    """Render invoice template to HTML string (for live preview).

    Same interface as generate_invoice but returns HTML instead of PDF.
    """
    if bedrijfsgegevens is None:
        bedrijfsgegevens = {}

    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    env.filters['format_euro'] = format_euro
    env.filters['format_datum'] = format_datum
    template = env.get_template('factuur.html')

    if factuur_datum:
        try:
            datum = datetime.strptime(factuur_datum, '%Y-%m-%d')
        except ValueError:
            datum = datetime.now()
    else:
        datum = datetime.now()
    vervaldatum = datum + timedelta(days=14)

    # Calculate totals
    subtotaal_werk = sum(r.get('bedrag', r.get('aantal', 0) * r.get('tarief', 0))
                         for r in regels if 'Reiskosten' not in r.get('omschrijving', ''))
    subtotaal_km = sum(r.get('bedrag', r.get('aantal', 0) * r.get('tarief', 0))
                       for r in regels if 'Reiskosten' in r.get('omschrijving', ''))
    totaal = subtotaal_werk + subtotaal_km

    # Ensure klant has all fields
    klant_full = {
        'naam': klant.get('naam', ''),
        'contactpersoon': klant.get('contactpersoon', ''),
        'adres': klant.get('adres', ''),
        'postcode': klant.get('postcode', ''),
        'plaats': klant.get('plaats', ''),
    }

    # QR path for preview (use file:// URI)
    qr_uri = ''
    if qr_path and Path(qr_path).exists():
        qr_uri = Path(qr_path).resolve().as_uri()

    return template.render(
        nummer=nummer,
        datum=format_datum(datum.strftime('%Y-%m-%d')),
        vervaldatum=format_datum(vervaldatum.strftime('%Y-%m-%d')),
        klant=klant_full,
        bedrijf=bedrijfsgegevens,
        regels=regels,
        subtotaal_werk=subtotaal_werk,
        subtotaal_km=subtotaal_km,
        totaal=totaal,
        qr_path=qr_uri,
    )
```

- [ ] **Step 2: Run tests + commit**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
git add components/invoice_preview.py
git commit -m "feat: invoice preview helper — render HTML for live preview"
```

---

### Task 4: Build two-panel invoice builder dialog

**Files:**
- Modify: `pages/facturen.py` — replace `open_new_factuur_dialog()`

This is the largest task. Replace the current dialog with the two-panel builder.

- [ ] **Step 1: Replace the dialog function**

The new `open_new_factuur_dialog()` creates a large dialog with:

**Left panel (440px):**
- Factuurnummer: `ui.input` with auto-generated value from `get_next_factuurnummer()`
- Factuurdatum: `date_input()` component
- Klant section: Bedrijf input with autocomplete, Contactpersoon, Adres, Postcode, Plaats
- Line items: dynamic list of rows, each with datum/omschrijving/aantal/tarief inputs
- "+ Vrije regel" button
- "+ Werkdagen importeren" button (opens sub-dialog)
- QR upload area
- Totaal display
- Annuleren + Genereer buttons

**Right panel (flex):**
- `ui.html()` element showing rendered invoice preview
- Wrapped in a paper-styled container (white bg, shadow, A4 proportions, scaled)

**Key implementation details:**

1. The klant input uses `ui.input(autocomplete=[k.naam for k in klanten])`. On blur, check if the value matches a known klant name — if so, auto-fill address fields and enable werkdagen import.

2. Line items stored as a list of dicts. Each row renders as a set of NiceGUI inputs. Adding/removing rows rebuilds the container.

3. The preview updates via a `update_preview()` function called on every input change. It calls `render_invoice_html()` and sets the result as `preview_html.content`.

4. The preview container uses CSS to look like a paper:
```python
with ui.element('div').style(
        'background: #E2E8F0; padding: 24px; display: flex; '
        'justify-content: center; overflow-y: auto; flex: 1'):
    preview_html = ui.html('').style(
        'background: white; width: 595px; min-height: 842px; '
        'box-shadow: 0 2px 20px rgba(0,0,0,0.15); '
        'padding: 48px; transform: scale(0.82); '
        'transform-origin: top center')
```

5. QR upload: `ui.upload(auto_upload=True, on_upload=handle_qr)` saves to `data/qr/betaal_qr.png`.

6. "Werkdagen importeren" sub-dialog: shows ongefactureerde werkdagen for the matched klant with checkboxes. "Toevoegen" converts selected werkdagen to line items.

7. "Genereer factuur": validates, calls `generate_invoice()` via `asyncio.to_thread()`, saves DB record, links werkdagen, closes dialog.

- [ ] **Step 2: Test manually**

Start the app, navigate to /facturen, click "Nieuwe factuur". Verify:
- Two-panel layout renders correctly
- Klant autocomplete works
- Address auto-fills from existing klant
- Manual line items can be added/removed
- Preview updates live
- Werkdagen import works
- PDF generation works
- The generated PDF matches the preview

- [ ] **Step 3: Run full test suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add pages/facturen.py
git commit -m "feat: two-panel invoice builder with live preview"
```

---

### Task 5: QR code persistence + cleanup

**Files:**
- Modify: `pages/facturen.py` — QR upload handler
- Modify: `components/invoice_generator.py` — auto-detect QR file

- [ ] **Step 1: QR storage**

The QR upload handler saves to `data/qr/betaal_qr.png`:

```python
async def handle_qr_upload(e):
    qr_dir = DB_PATH.parent / 'qr'
    qr_dir.mkdir(exist_ok=True)
    qr_path = qr_dir / 'betaal_qr.png'
    content = e.content.read()
    await asyncio.to_thread(qr_path.write_bytes, content)
    ui.notify('QR-code opgeslagen', type='positive')
    update_preview()  # refresh preview with QR
```

- [ ] **Step 2: Auto-detect QR in generator**

In `generate_invoice()`, if no explicit `qr_path` is passed, check for the default location:

```python
if not qr_path:
    default_qr = output_dir.parent / 'qr' / 'betaal_qr.png'
    if default_qr.exists():
        qr_path = str(default_qr)
```

- [ ] **Step 3: Clean up old dialog code**

Remove the old `open_new_factuur_dialog()` function and all its nested helpers (klant_state toggle, manual_lines, etc.). The new builder replaces it entirely.

Also remove the unused imports from the old dialog (if any).

- [ ] **Step 4: Run full test suite + commit**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
git add pages/facturen.py components/invoice_generator.py
git commit -m "feat: QR code persistence + invoice generator auto-detection"
```

---

### Task 6: Final verification and polish

- [ ] **Step 1: Run full test suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

- [ ] **Step 2: Generate a test invoice and compare with user's actual invoices**

Create a test invoice for "Huisartspraktijk 't Klant6" with a single werkdag. Download the PDF and visually compare:
- Header layout and font sizes
- Client section formatting
- Line items table proportions
- TOTAAL section styling
- BETAALINFORMATIE table alignment
- QR code placement and sizing
- Footer content

- [ ] **Step 3: Test edge cases**

- Create invoice with manual klant (not in DB)
- Create invoice with only manual line items (no werkdagen)
- Create invoice with mixed werkdagen + manual lines
- Create invoice with QR code uploaded
- Override factuurnummer to a custom value
- Create invoice with many line items (test multi-page)

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: invoice builder polish after manual testing"
```
