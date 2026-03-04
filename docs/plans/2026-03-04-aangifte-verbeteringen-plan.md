# Aangifte Documenten — Verbeteringen Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix bugs and improve robustness of the aangifte documenten feature based on 5-agent expert review.

**Architecture:** Fix critical bugs (upload API, null safety, data preservation), then consistency fixes, then polish.

**Tech Stack:** NiceGUI 3.8, aiosqlite, Python 3.12+

**Review sources:** Code quality agent, UI/UX agent, test coverage agent, Dutch fiscal domain expert, architecture agent — all opus-level deep analysis.

---

## Tier 1: MUST FIX (bugs that break functionality)

### Task 1: Fix upload API (CRITICAL — every upload crashes)

**Files:**
- Modify: `pages/aangifte.py` (handle_upload function)
- Modify: `pages/kosten.py` (save_upload_for_uitgave function)

**What:** NiceGUI 3.8 `UploadEventArguments` has `e.file` (a `FileUpload` object with `name`, `async read()`, `async save(path)`). Our code uses `e.name` and `e.content.read()` which don't exist. Also use `await e.file.save(path)` instead of manual `write_bytes`.

**Step 1: Fix aangifte.py handle_upload**

Replace the entire handle_upload function body:
```python
async def handle_upload(e: events.UploadEventArguments,
                        categorie: str, documenttype: str):
    jaar = state['jaar']
    target_dir = AANGIFTE_DIR / str(jaar) / categorie
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(e.file.name).name.replace(' ', '_')
    file_path = target_dir / safe_name
    await e.file.save(file_path)

    await add_aangifte_document(
        DB_PATH, jaar=jaar, categorie=categorie,
        documenttype=documenttype, bestandsnaam=safe_name,
        bestandspad=str(file_path),
        upload_datum=date.today().isoformat())

    ui.notify(f'{safe_name} geüpload', type='positive')
    await refresh_all()
```

**Step 2: Fix kosten.py save_upload_for_uitgave**

```python
safe_name = Path(upload_event.file.name).name.replace(' ', '_')
# ...
await upload_event.file.save(target)
```

---

### Task 2: Fix upsert_fiscale_params destroying partner fields

**Files:**
- Modify: `database.py` (upsert_fiscale_params function)

**What:** `INSERT OR REPLACE` doesn't preserve `partner_bruto_loon` and `partner_loonheffing`. Add them to the preservation logic.

**Step 1: Add partner fields to SELECT + INSERT in upsert_fiscale_params**

In the SELECT that reads existing values before replace, add:
```sql
partner_bruto_loon, partner_loonheffing
```

In the INSERT column list and VALUES, include the preserved partner values.

---

### Task 3: Fix render_partner crash when fiscale_params is None

**Files:**
- Modify: `pages/aangifte.py` (render_partner function)

**What:** `get_fiscale_params()` returns None when no row exists. Add guard.

```python
async def render_partner():
    partner_card.clear()
    params = await get_fiscale_params(DB_PATH, state['jaar'])
    with partner_card:
        ui.label('Partner inkomen').classes('text-subtitle1 text-weight-medium')
        if not params:
            ui.label(f'Geen fiscale parameters voor {state["jaar"]}. '
                     'Maak deze aan via Instellingen.').classes(
                'text-caption text-grey-7')
            return
        # ... rest unchanged
```

---

### Task 4: Fix update_partner_inkomen silent failure

**Files:**
- Modify: `database.py` (update_partner_inkomen)
- Modify: `pages/aangifte.py` (save_partner)

**What:** Return bool from update_partner_inkomen, show warning in UI if no row updated.

```python
async def update_partner_inkomen(...) -> bool:
    # ... UPDATE ...
    await conn.commit()
    return cursor.rowcount > 0
```

```python
async def save_partner(bruto, loonheffing):
    saved = await update_partner_inkomen(DB_PATH, state['jaar'], bruto, loonheffing)
    if saved:
        ui.notify('Partner inkomen opgeslagen', type='positive')
    else:
        ui.notify(f'Geen fiscale parameters voor {state["jaar"]}', type='warning')
```

---

## Tier 2: SHOULD FIX (consistency, robustness)

### Task 5: Fix UI consistency

**Files:**
- Modify: `pages/aangifte.py`

**Changes:**
1. Container: `max-w-4xl q-pa-md gap-4` → `max-w-7xl mx-auto gap-6` + `p-6`
2. Header: add `.style('color: #0F172A; font-weight: 700')`
3. Year selector: use dict `{j: str(j) for j in jaren}` instead of list
4. Add `* = verplicht` legend text below progress bar

---

### Task 6: Fix delete order + download safety

**Files:**
- Modify: `pages/aangifte.py`

**Changes:**
1. `do_delete`: delete DB record FIRST, then file from disk
2. Download: check `Path(doc.bestandspad).exists()` before download, show warning if missing
3. Use `ui.download.file()` instead of `ui.download()`

---

### Task 7: Fix verplicht flags + progress bar

**Files:**
- Modify: `pages/aangifte.py`

**Changes:**
1. Set `woz_beschikking`, `hypotheek_jaaroverzicht`, `jaaropgave_partner` to `verplicht=False`
2. Only count AUTO_TYPES as done if jaarafsluiting PDF exists for that year
3. Add `verzekeringen` category with `aov_jaaroverzicht` and `zorgverzekering_jaaroverzicht`

---

### Task 8: Replace inline ui.upload with dialog button

**Files:**
- Modify: `pages/aangifte.py`

**What:** Replace heavy `ui.upload` widget in checklist rows with compact `ui.button('Uploaden')` that opens a dialog containing the upload widget.

---

### Task 9: Add aangifte to backup + optimize DB queries

**Files:**
- Modify: `pages/instellingen.py` (add 'aangifte' to backup dirs)
- Modify: `pages/aangifte.py` (fetch docs once in refresh_all, pass to both renderers)

---

### Task 10: Add missing tests

**Files:**
- Modify: `tests/test_database.py` (add aangifte_documenten to expected tables)
- Modify: `tests/test_aangifte.py` (add tests)

**New tests:**
1. `test_update_partner_inkomen_no_row` — returns False when no fiscal row
2. `test_delete_nonexistent_doc` — does not raise
3. `test_upsert_preserves_partner_fields` — upsert keeps partner data
4. `test_delete_preserves_other_docs` — deleting one keeps others

---

## Tier 3: NICE TO HAVE

### Task 11: Code cleanup

**Changes:**
1. Remove unused `format_euro` import
2. Remove `notitie` from Python code (keep DB column, stop referencing in model/functions)
3. Rename `rel_path` to `abs_path`
4. Convert AANGIFTE_DOCS tuples to NamedTuple `DocSpec`

---

## NOT DOING (YAGNI confirmed by fiscal expert)

- Box 3 vermogensberekening
- Giften/zorgkosten tracking
- MijnBelastingdienst integration
- Multi-partner support
- Conditional verplicht flags based on fiscale_params values
- File size validation (local single-user app)
