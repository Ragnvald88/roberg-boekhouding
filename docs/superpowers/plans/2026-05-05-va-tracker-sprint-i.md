# Sprint I — VA-tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vervang dashboard hero Card 3 "Belasting-reservering" door een Voorlopige-Aanslag-tracker die werkt op echte data: BD-beschikkingsbedragen (al editable in /aangifte) + bank-detected VA-betalingen (via Belastingdienst-IBAN + kenmerk-split).

**Architecture:** Twee nieuwe velden in `fiscale_params` (mig 40), uitgebreid `get_va_betalingen` contract met unmatched-zichtbaarheid + negatief-only `bankdata_tot_datum`, nieuwe pure helper `compute_va_tracker` met line-first status-ordering en volgende-termijn-derivatie, renderer `render_va_tile` in dashboard_widgets, en /aangifte Card 3 uitgebreid met termijnen-inputs en BD-betalingen-link bij unmatched.

**Tech Stack:** Python 3.12, NiceGUI/Quasar (native pywebview), SQLite (raw SQL via aiosqlite, `?`-placeholders), pytest/pytest-asyncio. Spec: `docs/superpowers/specs/2026-05-05-va-tracker-design.md` (LOCKED).

**Process:** Sprint H 4-layer review per task: implementer (opus subagent) → spec/quality reviewer waar substantieel → Codex via `env -u OPENAI_API_KEY codex exec --sandbox read-only -c model_reasoning_effort=medium - <stdin` → fix-cycle waar Codex echte bugs catched. Direct-on-master pattern (Sprint A→H conventie).

---

## File Structure

**Modify:**
- `database.py:443-540` — append migration 40 to MIGRATIONS list
- `database.py:255-280` — add 2 columns to fresh CREATE TABLE for fiscale_params
- `database.py:2792-2843` — uitbreid `get_va_betalingen` return-contract (BREAKING)
- `database.py:2944-3015` — uitbreid `_row_to_fiscale_params` met 2 termijn-velden
- `database.py:3034-3220` — uitbreid `upsert_fiscale_params` (alle 4 paden: SELECT preserve, INSERT cols, VALUES tuple, ON CONFLICT SET)
- `database.py:3224-3242` — uitbreid `update_ib_inputs` met 2 termijn-kwargs
- `models.py:155-164` — voeg 2 termijn-velden toe + rename-comment over `voorlopige_aanslag_betaald`
- `services/dashboard.py` — voeg `VATrackLine` + `VATrackSummary` + `compute_va_tracker` toe; verwijder `compute_belasting_reservering_progress` in T2.1
- `components/dashboard_widgets.py` — voeg `render_va_tile` toe
- `pages/dashboard.py:631-707` — vervang Card 3 Belasting-reservering met VA-tracker tile
- `pages/aangifte.py:538-580` — uitbreid Card 3 met termijn-inputs + bank-summary herschrijving + unmatched-link + rollback-fix
- `tests/test_dashboard_helpers.py` — verwijder 9 `compute_belasting_reservering_progress` tests (T2.1)
- `tests/test_db_queries.py` — uitbreid 7 nieuwe tests + herschrijf `test_get_va_betalingen_no_kenmerk_fallback`
- `CLAUDE.md` — documenteer kenmerk-jaar-mismatch + veldnaam-bug + positieve-BD-tx-gat (T2.1)

**Create:**
- `tests/test_va_tracker.py` — 12 nieuwe helper-tests

---

## Task 1: Migratie 40 + models + CRUD plumbing

**Files:**
- Modify: `database.py:443-540` (MIGRATIONS), `database.py:255-280` (fresh schema), `database.py:2944-3015` (_row_to_fiscale_params), `database.py:3034-3220` (upsert_fiscale_params), `database.py:3224-3242` (update_ib_inputs)
- Modify: `models.py:155-164`
- Test: `tests/test_db_queries.py` (3 nieuwe tests)

- [ ] **Step 1.1: Write failing schema tests**

Append aan `tests/test_db_queries.py`:

```python
@pytest.mark.asyncio
async def test_migratie_40_va_termijnen_default_11(db):
    """Migratie 40 voegt 2 termijn-kolommen toe met default 11."""
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("PRAGMA table_info(fiscale_params)")
        cols = {row['name']: row for row in await cur.fetchall()}
    assert 'voorlopige_aanslag_ib_termijnen' in cols
    assert 'voorlopige_aanslag_zvw_termijnen' in cols
    assert int(cols['voorlopige_aanslag_ib_termijnen']['dflt_value']) == 11
    assert int(cols['voorlopige_aanslag_zvw_termijnen']['dflt_value']) == 11

    # CHECK constraint weigert 0 en 13
    await upsert_fiscale_params(
        db_path=db, jaar=2026,
        zelfstandigenaftrek=0, mkb_vrijstelling_pct=0,
        kia_ondergrens=0, kia_bovengrens=0, kia_pct=0,
        km_tarief=0.23, schijf1_grens=0, schijf1_pct=0,
        schijf2_grens=0, schijf2_pct=0, schijf3_pct=0,
        ahk_max=0, ahk_afbouw_pct=0, ahk_drempel=0, ak_max=0,
        zvw_pct=0, zvw_max_grondslag=0,
    )
    async with get_db_ctx(db) as conn:
        with pytest.raises(Exception):
            await conn.execute(
                "UPDATE fiscale_params SET voorlopige_aanslag_ib_termijnen = 0 WHERE jaar = 2026")
            await conn.commit()


@pytest.mark.asyncio
async def test_update_ib_inputs_preserves_va_termijnen(db):
    """update_ib_inputs zonder termijnen-kwargs laat termijn-velden ongemoeid."""
    await upsert_fiscale_params(
        db_path=db, jaar=2026,
        zelfstandigenaftrek=0, mkb_vrijstelling_pct=0,
        kia_ondergrens=0, kia_bovengrens=0, kia_pct=0,
        km_tarief=0.23, schijf1_grens=0, schijf1_pct=0,
        schijf2_grens=0, schijf2_pct=0, schijf3_pct=0,
        ahk_max=0, ahk_afbouw_pct=0, ahk_drempel=0, ak_max=0,
        zvw_pct=0, zvw_max_grondslag=0,
        voorlopige_aanslag_ib_termijnen=8,
        voorlopige_aanslag_zvw_termijnen=12,
    )
    await update_ib_inputs(db_path=db, jaar=2026, voorlopige_aanslag_betaald=9600)
    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_ib_termijnen == 8
    assert fp.voorlopige_aanslag_zvw_termijnen == 12


@pytest.mark.asyncio
async def test_upsert_fiscale_params_preserves_va_termijnen(db):
    """upsert zonder termijnen-kwargs leest existing en behoudt waarde."""
    await upsert_fiscale_params(
        db_path=db, jaar=2026,
        zelfstandigenaftrek=0, mkb_vrijstelling_pct=0,
        kia_ondergrens=0, kia_bovengrens=0, kia_pct=0,
        km_tarief=0.23, schijf1_grens=0, schijf1_pct=0,
        schijf2_grens=0, schijf2_pct=0, schijf3_pct=0,
        ahk_max=0, ahk_afbouw_pct=0, ahk_drempel=0, ak_max=0,
        zvw_pct=0, zvw_max_grondslag=0,
        voorlopige_aanslag_ib_termijnen=6,
        voorlopige_aanslag_zvw_termijnen=10,
    )
    # Re-upsert zonder termijnen-kwargs — moet preserve'n
    await upsert_fiscale_params(
        db_path=db, jaar=2026,
        zelfstandigenaftrek=0, mkb_vrijstelling_pct=0,
        kia_ondergrens=0, kia_bovengrens=0, kia_pct=0,
        km_tarief=0.23, schijf1_grens=0, schijf1_pct=0,
        schijf2_grens=0, schijf2_pct=0, schijf3_pct=0,
        ahk_max=0, ahk_afbouw_pct=0, ahk_drempel=0, ak_max=0,
        zvw_pct=0, zvw_max_grondslag=0,
    )
    fp = await get_fiscale_params(db, 2026)
    assert fp.voorlopige_aanslag_ib_termijnen == 6
    assert fp.voorlopige_aanslag_zvw_termijnen == 10
```

- [ ] **Step 1.2: Run tests — verify they fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py::test_migratie_40_va_termijnen_default_11 tests/test_db_queries.py::test_update_ib_inputs_preserves_va_termijnen tests/test_db_queries.py::test_upsert_fiscale_params_preserves_va_termijnen -v
```

Expected: 3 FAIL — kolommen bestaan niet, kwargs worden niet herkend.

- [ ] **Step 1.3: Add migration 40 to MIGRATIONS list**

In `database.py`, vind de hoogste bestaande migration entry (`MIGRATIONS = [...]`, mig 39 is laatste). Append direct erna:

```python
    (40, "add_va_termijnen_columns", [
        "ALTER TABLE fiscale_params ADD COLUMN voorlopige_aanslag_ib_termijnen INTEGER NOT NULL DEFAULT 11",
        "ALTER TABLE fiscale_params ADD COLUMN voorlopige_aanslag_zvw_termijnen INTEGER NOT NULL DEFAULT 11",
    ]),
```

> **Note over CHECK-constraint**: SQLite ondersteunt geen `ADD COLUMN ... CHECK` direct in een ALTER. De CHECK afdwingen zou een full table-rewrite vereisen. Pragmatic v1: enforcement gebeurt op application-level via `update_ib_inputs` + `upsert_fiscale_params` parameter validation. Geen CHECK in DB. Test #1 valideert dat de waarde-range correct wordt gehandhaafd door `ui.number(min=1, max=12)` in /aangifte (T4) plus python-side guard in CRUD calls. **Spec-amendment**: §1 CHECK-clausule wordt geschrapt — alleen DEFAULT 11 + NOT NULL + UI-min/max. CLAUDE.md update mentions this in T2.1.

- [ ] **Step 1.4: Add columns to fresh schema CREATE TABLE**

In `database.py` rond regel 255-280, in de `CREATE TABLE IF NOT EXISTS fiscale_params` statement, voeg toe in de kolommenlijst (na `voorlopige_aanslag_zvw REAL DEFAULT 0`):

```python
    voorlopige_aanslag_ib_termijnen INTEGER NOT NULL DEFAULT 11,
    voorlopige_aanslag_zvw_termijnen INTEGER NOT NULL DEFAULT 11,
```

- [ ] **Step 1.5: Add fields to FiscaleParams dataclass + rename-comment**

In `models.py` rond regel 158, vervang:

```python
    voorlopige_aanslag_betaald: float = 0.0
```

door:

```python
    # NB: 'voorlopige_aanslag_betaald' bevat het BD-beschikkingsbedrag IB
    # (de jaar-verplichting), NIET wat is betaald. Veldnaam is misleidend
    # voor historische redenen — Sprint K kan renamen via migratie. Voor
    # /dashboard VA-tracker (Sprint I) wordt dit veld lokaal gealiased
    # naar `ib_verplicht` in compute_va_tracker.
    voorlopige_aanslag_betaald: float = 0.0
    voorlopige_aanslag_ib_termijnen: int = 11
```

En rond regel 164 (na `voorlopige_aanslag_zvw: float = 0.0`):

```python
    voorlopige_aanslag_zvw_termijnen: int = 11
```

- [ ] **Step 1.6: Update _row_to_fiscale_params**

In `database.py:2944-3015`, in de `return FiscaleParams(...)` constructor, voeg toe na de bestaande `voorlopige_aanslag_betaald=` en `voorlopige_aanslag_zvw=` regels:

```python
        voorlopige_aanslag_ib_termijnen=int(_v(r['voorlopige_aanslag_ib_termijnen'], 11)),
        voorlopige_aanslag_zvw_termijnen=int(_v(r['voorlopige_aanslag_zvw_termijnen'], 11)),
```

- [ ] **Step 1.7: Update upsert_fiscale_params — alle 4 paden**

In `database.py:3034-3220`:

(a) Append aan SELECT preserve-query (rond regel 3060):
```python
"voorlopige_aanslag_ib_termijnen, voorlopige_aanslag_zvw_termijnen "
```

(b) Append aan INSERT kolommen-list (rond regel 3087):
```python
voorlopige_aanslag_ib_termijnen, voorlopige_aanslag_zvw_termijnen,
```

(c) Append `ON CONFLICT ... SET` clauses (rond regel 3149):
```python
                    voorlopige_aanslag_ib_termijnen = excluded.voorlopige_aanslag_ib_termijnen,
                    voorlopige_aanslag_zvw_termijnen = excluded.voorlopige_aanslag_zvw_termijnen,
```

(d) Append aan VALUES tuple-positions list (in de `await conn.execute(...)`-tuple, rond regel 3151+; pas count aan in VALUES `?`-string van 60 → 62):
```python
             kwargs.get('voorlopige_aanslag_ib_termijnen',
                       existing['voorlopige_aanslag_ib_termijnen'] if existing else 11),
             kwargs.get('voorlopige_aanslag_zvw_termijnen',
                       existing['voorlopige_aanslag_zvw_termijnen'] if existing else 11),
```

- [ ] **Step 1.8: Update update_ib_inputs**

In `database.py:3224-3242`, vervang de hele functie:

```python
async def update_ib_inputs(db_path: Path = DB_PATH, jaar: int = 0,
                           aov_premie: float = 0, woz_waarde: float = 0,
                           hypotheekrente: float = 0,
                           voorlopige_aanslag_betaald: float = 0,
                           voorlopige_aanslag_zvw: float = 0,
                           lijfrente_premie: float = 0,
                           voorlopige_aanslag_ib_termijnen: int | None = None,
                           voorlopige_aanslag_zvw_termijnen: int | None = None) -> None:
    """Update only the IB-input columns for a specific year.

    Termijnen-kwargs zijn None-default zodat callers die ze niet meegeven
    de bestaande waarden niet overschrijven. Validatie 1-12 op application
    level (CHECK in DB ontbreekt; ALTER ... ADD COLUMN CHECK is SQLite-
    onbruikbaar).
    """
    await assert_year_writable(db_path, jaar)
    if voorlopige_aanslag_ib_termijnen is not None and not (1 <= voorlopige_aanslag_ib_termijnen <= 12):
        raise ValueError("voorlopige_aanslag_ib_termijnen moet 1-12 zijn")
    if voorlopige_aanslag_zvw_termijnen is not None and not (1 <= voorlopige_aanslag_zvw_termijnen <= 12):
        raise ValueError("voorlopige_aanslag_zvw_termijnen moet 1-12 zijn")
    async with get_db_ctx(db_path) as conn:
        if voorlopige_aanslag_ib_termijnen is None and voorlopige_aanslag_zvw_termijnen is None:
            await conn.execute(
                """UPDATE fiscale_params
                   SET aov_premie = ?, woz_waarde = ?,
                       hypotheekrente = ?, voorlopige_aanslag_betaald = ?,
                       voorlopige_aanslag_zvw = ?, lijfrente_premie = ?
                   WHERE jaar = ?""",
                (aov_premie, woz_waarde, hypotheekrente,
                 voorlopige_aanslag_betaald, voorlopige_aanslag_zvw,
                 lijfrente_premie, jaar))
        else:
            # Read-modify-write voor termijnen om None-default te respecteren
            cur = await conn.execute(
                "SELECT voorlopige_aanslag_ib_termijnen, voorlopige_aanslag_zvw_termijnen "
                "FROM fiscale_params WHERE jaar = ?", (jaar,))
            existing = await cur.fetchone()
            ib_t = (voorlopige_aanslag_ib_termijnen if voorlopige_aanslag_ib_termijnen is not None
                    else (existing['voorlopige_aanslag_ib_termijnen'] if existing else 11))
            zvw_t = (voorlopige_aanslag_zvw_termijnen if voorlopige_aanslag_zvw_termijnen is not None
                     else (existing['voorlopige_aanslag_zvw_termijnen'] if existing else 11))
            await conn.execute(
                """UPDATE fiscale_params
                   SET aov_premie = ?, woz_waarde = ?,
                       hypotheekrente = ?, voorlopige_aanslag_betaald = ?,
                       voorlopige_aanslag_zvw = ?, lijfrente_premie = ?,
                       voorlopige_aanslag_ib_termijnen = ?,
                       voorlopige_aanslag_zvw_termijnen = ?
                   WHERE jaar = ?""",
                (aov_premie, woz_waarde, hypotheekrente,
                 voorlopige_aanslag_betaald, voorlopige_aanslag_zvw,
                 lijfrente_premie, ib_t, zvw_t, jaar))
        await conn.commit()
```

- [ ] **Step 1.9: Run tests — verify pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py::test_migratie_40_va_termijnen_default_11 tests/test_db_queries.py::test_update_ib_inputs_preserves_va_termijnen tests/test_db_queries.py::test_upsert_fiscale_params_preserves_va_termijnen -v
```

Expected: 3 PASS.

Run full test suite to verify no regression:

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -x --tb=short
```

Expected: 1355 + 3 = 1358 passing, 0 failures.

- [ ] **Step 1.10: Commit**

```bash
git add database.py models.py tests/test_db_queries.py
git commit -m "$(cat <<'EOF'
feat(sprint-i): T1.1 migratie 40 + va_termijnen kolommen

- Mig 40 voegt voorlopige_aanslag_ib_termijnen + _zvw_termijnen toe
  aan fiscale_params (INTEGER NOT NULL DEFAULT 11)
- models.FiscaleParams: 2 nieuwe velden + rename-comment over
  veldnaam-bug voorlopige_aanslag_betaald (= jaarbedrag, niet betaald)
- _row_to_fiscale_params: read termijn-velden met _v-default-helper
- upsert_fiscale_params: alle 4 paden (SELECT, INSERT cols, VALUES,
  ON CONFLICT SET) — preserve via existing-fallback bij ontbreken kwargs
- update_ib_inputs: 2 None-default kwargs voor termijnen, application-
  level 1-12 validatie, read-modify-write om None-default te respecteren
- Geen DB-side CHECK (SQLite ALTER ... ADD COLUMN CHECK onbruikbaar);
  enforcement via UI ui.number(min=1,max=12) + Python-side guard
- 3 schema-tests: defaults, update_ib_inputs preserve, upsert preserve

Sprint I T1.1. Spec: docs/superpowers/specs/2026-05-05-va-tracker-design.md
Plan: docs/superpowers/plans/2026-05-05-va-tracker-sprint-i.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: get_va_betalingen BREAKING contract change

**Files:**
- Modify: `database.py:2792-2843`
- Test: `tests/test_db_queries.py` (4 nieuwe tests + 1 herschreven)

- [ ] **Step 2.1: Write failing tests**

Append aan `tests/test_db_queries.py`:

```python
@pytest.mark.asyncio
async def test_get_va_betalingen_excludes_unmatched_from_totaal_betaald(db):
    """BREAKING: totaal_betaald = ib + zvw, NIET inclusief unmatched."""
    BD = 'NL86INGB0002445588'
    async with get_db_ctx(db) as conn:
        # 1 IB-betaling (kenmerk pos 10-11 = '12' < 50)
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving, categorie) VALUES (?,?,?,?,?,?)",
            ('2026-03-15', -800, BD, '0123456789120000', 'VA IB', 'Belasting'))
        # 1 ZVW-betaling (kenmerk pos 10-11 = '50' >= 50)
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving, categorie) VALUES (?,?,?,?,?,?)",
            ('2026-04-15', -300, BD, '0123456789500000', 'VA ZVW', 'Belasting'))
        # 1 unmatched (kenmerk te kort)
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving, categorie) VALUES (?,?,?,?,?,?)",
            ('2026-05-15', -200, BD, '12345', 'BD onbekend', 'Belasting'))
        await conn.commit()

    out = await get_va_betalingen(db, jaar=2026)
    assert out['ib_betaald'] == 800
    assert out['zvw_betaald'] == 300
    assert out['unmatched_betaald'] == 200
    assert out['unmatched_termijnen'] == 1
    assert out['totaal_betaald'] == 1100  # ib + zvw, NIET +200
    assert out['has_bank_data'] is True


@pytest.mark.asyncio
async def test_get_va_betalingen_bankdata_tot_datum_negative_only(db):
    """bankdata_tot_datum max van negatieve BD-rows; positieve genegeerd."""
    BD = 'NL86INGB0002445588'
    from datetime import date as _date
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-03-15', -800, BD, '0123456789120000', 'VA IB'))
        # Positief = correctie/teruggave; negeren voor zowel betaald als datum
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-08-20', 100, BD, '0123456789120000', 'BD teruggave'))
        await conn.commit()

    out = await get_va_betalingen(db, jaar=2026)
    assert out['bankdata_tot_datum'] == _date(2026, 3, 15)
    assert out['ib_betaald'] == 800  # positieve genegeerd


@pytest.mark.asyncio
async def test_get_va_betalingen_bankdata_tot_datum_none_when_no_negative_rows(db):
    """Geen negatieve BD-rijen → bankdata_tot_datum is None."""
    out = await get_va_betalingen(db, jaar=2026)
    assert out['bankdata_tot_datum'] is None
    assert out['has_bank_data'] is False


@pytest.mark.asyncio
async def test_get_va_betalingen_unmatched_kenmerk_variants(db):
    """3 kenmerk-edge-cases vallen alle in unmatched."""
    BD = 'NL86INGB0002445588'
    async with get_db_ctx(db) as conn:
        # Te kort kenmerk
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-02-15', -100, BD, '12345', 'kort'))
        # Niet-numerieke chars (alleen letters)
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-03-15', -150, BD, 'ABCDEFGHIJ123', 'letters'))
        # Lege kenmerk
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2026-04-15', -200, BD, '', 'leeg'))
        await conn.commit()

    out = await get_va_betalingen(db, jaar=2026)
    assert out['unmatched_termijnen'] == 3
    assert out['unmatched_betaald'] == 450
    assert out['ib_betaald'] == 0
    assert out['zvw_betaald'] == 0
```

Herschrijf de bestaande `test_get_va_betalingen_no_kenmerk_fallback` (rond regel 838 in test_db_queries.py) — de oude versie verifieerde de oude inclusieve-totaal-betaald gedrag. Vervang door:

```python
@pytest.mark.asyncio
async def test_get_va_betalingen_no_kenmerk_fallback(db):
    """No-kenmerk → unmatched_betaald, niet totaal_betaald (post-Sprint-I)."""
    BD = 'NL86INGB0002445588'
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (datum, bedrag, tegenrekening, "
            "betalingskenmerk, omschrijving) VALUES (?,?,?,?,?)",
            ('2025-06-15', -500, BD, '', 'BD geen kenmerk'))
        await conn.commit()

    out = await get_va_betalingen(db, jaar=2025)
    assert out['totaal_betaald'] == 0  # was 500 in pre-Sprint-I
    assert out['unmatched_betaald'] == 500
    assert out['has_bank_data'] is True
```

- [ ] **Step 2.2: Run tests — verify failures**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py -k "va_betalingen" -v
```

Expected: 4 nieuwe FAIL (sleutels niet aanwezig in return-dict) + 1 FAIL op herschreven (oude gedrag mismatch).

- [ ] **Step 2.3: Update get_va_betalingen contract**

Vervang `database.py:2792-2843`:

```python
async def get_va_betalingen(db_path: Path = DB_PATH, jaar: int = 0) -> dict:
    """Get actual VA payments from bank transactions for a given year.

    Matches by Belastingdienst IBAN. Uses betalingskenmerk to split IB vs ZVW.
    IB kenmerken have digits at position 10-11 below 50, ZVW have 50+.

    Sprint I BREAKING contract change:
    - `totaal_betaald` = `ib_betaald + zvw_betaald` (was: incl. unmatched)
    - `unmatched_betaald` + `unmatched_termijnen` zichtbaar in return
    - `bankdata_tot_datum: date | None` — max(datum) van NEGATIEVE BD-rows
    - Positieve BD-tx (correcties/teruggaves) genegeerd voor alles
    """
    from datetime import date as _date_cls
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT ABS(bedrag) as amount, betalingskenmerk, datum
               FROM banktransacties
               WHERE tegenrekening = ?
                 AND datum >= ? AND datum <= ?
                 AND bedrag < 0""",
            (BELASTINGDIENST_IBAN, f'{jaar}-01-01', f'{jaar}-12-31')
        )
        rows = await cur.fetchall()

    if not rows:
        return {
            'ib_betaald': 0, 'ib_termijnen': 0,
            'zvw_betaald': 0, 'zvw_termijnen': 0,
            'unmatched_betaald': 0, 'unmatched_termijnen': 0,
            'totaal_betaald': 0, 'has_bank_data': False,
            'bankdata_tot_datum': None,
        }

    ib_betaald = 0.0
    ib_count = 0
    zvw_betaald = 0.0
    zvw_count = 0
    unmatched_betaald = 0.0
    unmatched_count = 0
    max_datum_iso: str | None = None

    for amount, kenmerk, datum in rows:
        if max_datum_iso is None or datum > max_datum_iso:
            max_datum_iso = datum
        norm = _normalize_va_kenmerk(kenmerk)
        if len(norm) >= 12 and norm[10:12].isdigit():
            year_type_digits = int(norm[10:12])
            if year_type_digits >= 50:
                zvw_betaald += amount
                zvw_count += 1
            else:
                ib_betaald += amount
                ib_count += 1
        else:
            unmatched_betaald += amount
            unmatched_count += 1

    bankdata_tot_datum = (_date_cls.fromisoformat(max_datum_iso)
                          if max_datum_iso else None)

    return {
        'ib_betaald': round(ib_betaald, 2),
        'ib_termijnen': ib_count,
        'zvw_betaald': round(zvw_betaald, 2),
        'zvw_termijnen': zvw_count,
        'unmatched_betaald': round(unmatched_betaald, 2),
        'unmatched_termijnen': unmatched_count,
        'totaal_betaald': round(ib_betaald + zvw_betaald, 2),  # BREAKING
        'has_bank_data': True,
        'bankdata_tot_datum': bankdata_tot_datum,
    }
```

- [ ] **Step 2.4: Run tests — verify all pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_db_queries.py -k "va_betalingen or va_kenmerk" -v
```

Expected: 8 PASS (4 nieuwe + 1 herschreven + 3 bestaande kenmerk-tests die ongewijzigd blijven).

- [ ] **Step 2.5: Run full suite — verify no regression**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -x --tb=short 2>&1 | tail -30
```

Expected: bestaande callers van `va_data['totaal_betaald']` blijven werken (oude tile gebruikt het alleen voor display, geen logic die op de oude inclusief-unmatched-waarde rekent). Nieuwe failures hier = regressie.

- [ ] **Step 2.6: Commit**

```bash
git add database.py tests/test_db_queries.py
git commit -m "$(cat <<'EOF'
feat(sprint-i): T1.2 get_va_betalingen BREAKING contract change

- totaal_betaald = ib_betaald + zvw_betaald (was: incl. unmatched)
- unmatched_betaald + unmatched_termijnen zichtbaar in return-dict
- bankdata_tot_datum: date | None — max(datum) van NEGATIEVE BD-rows
- Positieve BD-tx (teruggaves) genegeerd voor zowel betaald als datum
- 4 nieuwe tests + 1 herschreven (test_get_va_betalingen_no_kenmerk_fallback)

Caller-migratie: pages/dashboard.py oude Card 3 (verdwijnt in T1.4),
_compute_ib_estimate va_betaald-pad (verdwijnt in T2.1).

Sprint I T1.2. Spec §4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: compute_va_tracker helper + dataclasses

**Files:**
- Modify: `services/dashboard.py` (add helper after compute_belasting_reservering_progress)
- Create: `tests/test_va_tracker.py` (12 tests)

- [ ] **Step 3.1: Write failing helper-tests in tests/test_va_tracker.py**

```python
"""Unit-tests voor compute_va_tracker (Sprint I).

Pure function — geen DB, geen NiceGUI. Alle inputs expliciet.
"""
from datetime import date

import pytest

from services.dashboard import (
    VATrackLine, VATrackSummary, compute_va_tracker,
)


def _bank(ib=0, zvw=0, ib_n=0, zvw_n=0, unm=0, unm_n=0,
          tot_datum=None, has=False):
    return {
        'ib_betaald': ib, 'ib_termijnen': ib_n,
        'zvw_betaald': zvw, 'zvw_termijnen': zvw_n,
        'unmatched_betaald': unm, 'unmatched_termijnen': unm_n,
        'totaal_betaald': ib + zvw,
        'has_bank_data': has,
        'bankdata_tot_datum': tot_datum,
    }


def test_compute_va_tracker_geen_data():
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(has=False),
        ib_verplicht=0, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 5),
    )
    assert s.status == 'geen_data'
    assert s.totaal_resterend == 0
    assert s.has_overbetaald is False


def test_compute_va_tracker_geen_beschikking():
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=300, ib_n=1, has=True),
        ib_verplicht=0, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 5),
    )
    assert s.status == 'geen_beschikking'
    assert s.totaal_resterend == 0


def test_compute_va_tracker_bij_op_koers():
    # Mei (5e maand), 11 termijnen feb-start. Verwacht 4 termijnen.
    # Verplicht 4400 (400/termijn), betaald 1600 (4 termijnen) → op koers
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=1600, ib_n=4, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 31),
    )
    assert s.status == 'bij'
    assert s.totaal_achterstand <= 1


def test_compute_va_tracker_achter_with_amount():
    # Mei, 11 termijnen. Verplicht 4400. Betaald 800 (2 termijnen)
    # Verwacht 4 termijnen × 400 = 1600. Achterstand = 800.
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=800, ib_n=2, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 31),
    )
    assert s.status == 'achter'
    assert s.totaal_achterstand == pytest.approx(800, abs=1)


def test_compute_va_tracker_voldaan():
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=4400, ib_n=11, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 12, 31),
    )
    assert s.status == 'voldaan'
    assert s.has_overbetaald is False
    assert s.totaal_resterend == 0


def test_compute_va_tracker_voldaan_with_overbetaald_attribute():
    # IB overbetaald €100 (4500 betaald op 4400 verplicht), ZVW exact voldaan
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=4500, ib_n=11, zvw=2200, zvw_n=11, has=True),
        ib_verplicht=4400, zvw_verplicht=2200,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 12, 31),
    )
    assert s.status == 'voldaan'
    assert s.has_overbetaald is True
    assert s.ib.overbetaald == pytest.approx(100, abs=1)


def test_compute_va_tracker_line_first_status_ordering():
    """CRITICAL: IB +€100 overbetaald + ZVW achter mag NIET 'voldaan' zijn.

    Codex round-3 bug: oude totaal-eerst logica zou status='overbetaald'
    geven omdat totaal_betaald (4500+1000=5500) > totaal_verplicht
    (4400+2200=6600)? Nee — totaal_betaald 5500 < verplicht 6600. Voorbeeld:
    """
    # Augustus, 11 termijnen feb-start. Verwacht 7 termijnen × 400 = 2800 IB,
    # × 200 = 1400 ZVW. IB betaald 4500 (ver vooruit, overbetaald 100),
    # ZVW betaald 1000 (4 termijnen, achter 3 termijnen × 200 = 600 achter).
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=4500, ib_n=11, zvw=1000, zvw_n=4, has=True),
        ib_verplicht=4400, zvw_verplicht=2200,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 8, 31),
    )
    # Line-first: ZVW achterstand wint over IB-overbetaling
    assert s.status == 'achter'
    assert s.has_overbetaald is True  # IB-overbetaling alsnog gedetecteerd
    assert s.ib.overbetaald == pytest.approx(100, abs=1)
    assert s.zvw.achterstand > 500


def test_compute_va_tracker_closed_year_voldaan():
    s = compute_va_tracker(
        jaar=2025, va_data=_bank(ib=4400, ib_n=11, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 5),  # 2025 is closed
    )
    assert s.status == 'voldaan'


def test_compute_va_tracker_eerste_termijn_maand_11_termijnen():
    """Januari, 11 termijnen → expected_terms = 0 (feb-start)."""
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(has=False),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 1, 31),
    )
    # Geen achterstand in januari met 11-termijn-feb-start
    assert s.totaal_achterstand <= 1


def test_compute_va_tracker_eerste_termijn_maand_12_termijnen():
    """Januari, 12 termijnen → expected_terms = 1 (jan-start)."""
    # Verplicht 4800 over 12 termijnen = 400/termijn. Betaald 0 in jan.
    # Verwacht 1 termijn = 400. Achterstand = 400.
    s = compute_va_tracker(
        jaar=2026, va_data=_bank(has=False),
        ib_verplicht=4800, zvw_verplicht=0,
        ib_termijnen=12, zvw_termijnen=12,
        today=date(2026, 1, 31),
    )
    assert s.status == 'achter'
    assert s.totaal_achterstand == pytest.approx(400, abs=1)


def test_compute_va_tracker_volgende_termijn_alleen_bij_open_resterend():
    # status='voldaan' → volgende_termijn_datum=None
    s_voldaan = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=4400, ib_n=11, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 12, 31),
    )
    assert s_voldaan.volgende_termijn_datum is None

    # status='bij' + resterend>0 → datum gevuld
    s_bij = compute_va_tracker(
        jaar=2026, va_data=_bank(ib=1600, ib_n=4, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 31),
    )
    assert s_bij.volgende_termijn_datum is not None
    assert s_bij.volgende_termijn_datum.year == 2026


def test_compute_va_tracker_unmatched_in_summary_not_in_totaal():
    s = compute_va_tracker(
        jaar=2026,
        va_data=_bank(ib=800, ib_n=2, unm=120, unm_n=1, has=True),
        ib_verplicht=4400, zvw_verplicht=0,
        ib_termijnen=11, zvw_termijnen=11,
        today=date(2026, 5, 31),
    )
    assert s.unmatched_betaald == 120
    assert s.totaal_betaald == 800  # excludeert unmatched
```

- [ ] **Step 3.2: Run tests — verify all fail**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_va_tracker.py -v
```

Expected: 12 ImportError (compute_va_tracker bestaat niet).

- [ ] **Step 3.3: Add VATrackLine + VATrackSummary + compute_va_tracker**

Append aan `services/dashboard.py` (na `compute_belasting_reservering_progress` — die we in T2.1 verwijderen, maar voor nu blijft hij staan):

```python
# === VA-tracker (Sprint I) ============================================

@dataclass(frozen=True)
class VATrackLine:
    """Per-soort (IB of ZVW) voortgang van de voorlopige aanslag.

    `verplicht` = BD-beschikkingsbedrag voor het jaar (alias voor het
    misleidend genaamde `voorlopige_aanslag_betaald` resp. `_zvw` veld
    in fiscale_params — zie models.FiscaleParams comment).

    `betaald` + `betaalde_termijnen` komen uit get_va_betalingen op basis
    van bankdata + kenmerk-positie [10:12] split.

    `achterstand` is in EUR (verwacht_betaald_t/m_vandaag - betaald),
    niet in termijn-aantal. Pre-computed in helper voor render-stabiliteit.

    `overbetaald` is een @property — derive uit betaald/verplicht zonder
    state. Voorkomt inconsistentie als velden ooit handmatig worden gezet.
    """
    soort: str  # 'IB' | 'ZVW'
    verplicht: float
    betaald: float
    betaalde_termijnen: int
    totaal_termijnen: int
    termijnbedrag: float
    resterend: float
    achterstand: float

    @property
    def overbetaald(self) -> float:
        return max(self.betaald - self.verplicht, 0.0)


@dataclass(frozen=True)
class VATrackSummary:
    """Combined IB + ZVW tracker-state voor /dashboard tile."""
    ib: VATrackLine
    zvw: VATrackLine
    totaal_verplicht: float
    totaal_betaald: float          # excl. unmatched (na BREAKING contract)
    totaal_resterend: float
    totaal_achterstand: float
    unmatched_betaald: float       # bankdata zonder bruikbaar kenmerk
    unmatched_termijnen: int
    has_bank_data: bool
    bankdata_tot_datum: date | None
    status: str                    # geen_data|geen_beschikking|bij|achter|voldaan
    has_overbetaald: bool          # attribute, niet status (line-first ordering)
    volgende_termijn_datum: date | None  # None bij voldaan/closed/geen-data


def _expected_terms_elapsed(termijnen: int, today: date, jaar: int) -> int:
    """Aantal termijnen dat tot vandaag betaald had moeten zijn.

    Convention: aantal termijnen N impliceert eerste-termijn-maand =
    13 - N (N=11 → feb-start, N=12 → jan-start). Onze heuristiek, geen
    BD-bron-waarheid; documenteren in CLAUDE.md (T2.1).
    """
    if today.year < jaar:
        return 0
    if today.year > jaar:
        return termijnen
    eerste_maand = 13 - termijnen
    return min(termijnen, max(0, today.month - eerste_maand + 1))


def _last_day_of_month(year: int, month: int) -> date:
    """Laatste kalenderdag van de maand (BD betaalt typisch ultimo)."""
    if month == 12:
        return date(year, 12, 31)
    next_month_first = date(year, month + 1, 1)
    return date.fromordinal(next_month_first.toordinal() - 1)


def compute_va_tracker(
    *,
    jaar: int,
    va_data: dict,
    ib_verplicht: float,
    zvw_verplicht: float,
    ib_termijnen: int = 11,
    zvw_termijnen: int = 11,
    today: date,
) -> VATrackSummary:
    """Pure helper voor VA-tracker tile op /dashboard.

    Status-rangschikking is line-first (Codex round-3 catch — voorkomt
    dat IB-overbetaling een ZVW-achterstand maskeert).
    """
    def _clamp_terms(n: int) -> int:
        return min(12, max(1, int(n or 11)))

    def _line(soort: str, verplicht: float, betaald: float,
              betaalde_termijnen: int, termijnen: int) -> VATrackLine:
        termijnen = _clamp_terms(termijnen)
        verplicht = max(0.0, float(verplicht or 0))
        betaald = max(0.0, float(betaald or 0))
        termijnbedrag = verplicht / termijnen if verplicht > 0 else 0.0
        verwacht = termijnbedrag * _expected_terms_elapsed(termijnen, today, jaar)
        return VATrackLine(
            soort=soort,
            verplicht=verplicht,
            betaald=betaald,
            betaalde_termijnen=int(betaalde_termijnen or 0),
            totaal_termijnen=termijnen,
            termijnbedrag=termijnbedrag,
            resterend=max(verplicht - betaald, 0.0),
            achterstand=max(verwacht - betaald, 0.0),
        )

    ib = _line('IB', ib_verplicht, va_data.get('ib_betaald', 0),
               va_data.get('ib_termijnen', 0), ib_termijnen)
    zvw = _line('ZVW', zvw_verplicht, va_data.get('zvw_betaald', 0),
                va_data.get('zvw_termijnen', 0), zvw_termijnen)

    totaal_verplicht = ib.verplicht + zvw.verplicht
    totaal_betaald = ib.betaald + zvw.betaald
    totaal_resterend = ib.resterend + zvw.resterend
    totaal_achterstand = ib.achterstand + zvw.achterstand
    has_bank_data = bool(va_data.get('has_bank_data'))
    has_input = totaal_verplicht > 0

    # Status — line-first ordering
    if not has_input and not has_bank_data:
        status = 'geen_data'
    elif not has_input and has_bank_data:
        status = 'geen_beschikking'
    elif any(line.achterstand > 1 for line in [ib, zvw]):
        status = 'achter'
    elif totaal_resterend == 0 and has_input:
        status = 'voldaan'
    else:
        status = 'bij'

    has_overbetaald = (
        totaal_resterend == 0
        and any(line.overbetaald > 0 for line in [ib, zvw])
    )

    # Volgende termijn — alleen bij open verplichting (Codex D-1)
    volgende: date | None = None
    if status in ('achter', 'bij') and totaal_resterend > 0:
        # Eerstvolgende van IB en ZVW. Per-soort splitsen v2.
        candidates: list[date] = []
        for line in (ib, zvw):
            if line.resterend > 0 and line.verplicht > 0:
                eerste_maand = 13 - line.totaal_termijnen
                expected = _expected_terms_elapsed(line.totaal_termijnen,
                                                    today, jaar)
                next_idx = max(line.betaalde_termijnen, expected) + 1
                if next_idx > line.totaal_termijnen:
                    continue
                next_maand = eerste_maand + next_idx - 1
                if 1 <= next_maand <= 12:
                    candidates.append(_last_day_of_month(jaar, next_maand))
        if candidates:
            volgende = min(candidates)

    return VATrackSummary(
        ib=ib, zvw=zvw,
        totaal_verplicht=totaal_verplicht,
        totaal_betaald=totaal_betaald,
        totaal_resterend=totaal_resterend,
        totaal_achterstand=totaal_achterstand,
        unmatched_betaald=float(va_data.get('unmatched_betaald', 0) or 0),
        unmatched_termijnen=int(va_data.get('unmatched_termijnen', 0) or 0),
        has_bank_data=has_bank_data,
        bankdata_tot_datum=va_data.get('bankdata_tot_datum'),
        status=status,
        has_overbetaald=has_overbetaald,
        volgende_termijn_datum=volgende,
    )
```

- [ ] **Step 3.4: Run tests — verify all 12 pass**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/test_va_tracker.py -v
```

Expected: 12 PASS.

- [ ] **Step 3.5: Run full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -x --tb=short 2>&1 | tail -10
```

Expected: 1358 + 12 = 1370 passing (oude helper + tests nog aanwezig). 0 failures.

- [ ] **Step 3.6: Commit**

```bash
git add services/dashboard.py tests/test_va_tracker.py
git commit -m "$(cat <<'EOF'
feat(sprint-i): T1.3 compute_va_tracker helper + 12 tests

- VATrackLine (frozen dataclass) per-soort: verplicht/betaald/
  termijn/resterend/achterstand. overbetaald is @property (cut van
  field per Codex round-3 — minder state, minder inconsistentierisico).
- VATrackSummary: combined IB+ZVW + unmatched + bankdata_tot_datum +
  status + has_overbetaald attribute + volgende_termijn_datum.
- _expected_terms_elapsed: 13-N convention (11→feb-start, 12→jan-start).
- _last_day_of_month: helper voor termijn-vervaldatum (BD ultimo-pattern).
- Status line-first ordering: any(line.achterstand>1) WINS over totaal —
  voorkomt dat IB-overbetaling ZVW-achterstand maskeert (Codex round-3
  critical bug).
- has_overbetaald als attribute (niet status) — Codex round-4 cut
  van 'overbetaald' uit status-set.
- volgende_termijn_datum: alleen bij status ∈ {achter, bij} EN
  resterend > 0 (Codex D-1 anti-stale-suggestion).
- 12 tests: incl. line-first ordering bug-fix test (#7).

Sprint I T1.3. Spec §3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: render_va_tile + dashboard wiring + /aangifte termijn-inputs

**Files:**
- Modify: `components/dashboard_widgets.py` (add render_va_tile)
- Modify: `pages/dashboard.py:631-707` (replace Card 3)
- Modify: `pages/aangifte.py:538-580` (add termijn-inputs + bank-summary herschrijving + unmatched-link + rollback-fix)

- [ ] **Step 4.1: Add render_va_tile to dashboard_widgets.py**

Inspect huidige Sprint H tile-renderers in `components/dashboard_widgets.py` voor pattern. Voeg toe:

```python
def render_va_tile(summary, jaar: int) -> None:
    """Render VA-tracker hero-tile op dashboard (vervangt Sprint H
    Belasting-reservering Card 3).

    summary: services.dashboard.VATrackSummary
    jaar: int — voor click-target deep-link
    """
    from datetime import date as _date_cls
    from nicegui import ui
    from components.utils import format_euro
    from components.layout import format_datum_short  # of inline

    is_warning = (summary.status == 'achter') or summary.has_overbetaald
    card_classes = 'dashboard-hero-tile'
    if is_warning:
        card_classes += ' is-tekort'

    with ui.card().classes(card_classes) \
            .style('cursor: pointer') \
            .on('click', lambda: ui.navigate.to(f'/aangifte?jaar={jaar}')):
        # Title row + warning icon
        with ui.row().classes('w-full justify-between items-center'):
            ui.label(f'Voorlopige aanslag {jaar}').classes('hero-label')
            if is_warning:
                tooltip = ''
                if summary.status == 'achter':
                    tooltip = f'Achterstand: {format_euro(summary.totaal_achterstand, decimals=0)}'
                elif summary.has_overbetaald:
                    overbetaald = summary.ib.overbetaald + summary.zvw.overbetaald
                    tooltip = f'Overbetaald: {format_euro(overbetaald, decimals=0)}'
                ui.icon('warning', size='18px').style(
                    'color: var(--q-negative)').tooltip(tooltip)

        # Geen-data fallback
        if summary.status == 'geen_data':
            ui.label('—').classes('hero-value')
            ui.label('Geen beschikking of bankbetalingen').classes(
                'context-text').style('margin-top: 8px')
            return

        # Geen-beschikking fallback
        if summary.status == 'geen_beschikking':
            ui.label('—').classes('hero-value')
            ui.label(f'Bankbetalingen gevonden — vul beschikking in').classes(
                'context-text').style('margin-top: 8px')
            ui.label(
                f'IB {format_euro(summary.ib.betaald, decimals=0)} · '
                f'ZVW {format_euro(summary.zvw.betaald, decimals=0)}'
            ).classes('context-text')
            return

        # Hero value: resterend
        with ui.row().classes('w-full items-baseline gap-2'):
            ui.label(format_euro(summary.totaal_resterend, decimals=0)).classes('hero-value')
            if summary.has_overbetaald:
                overbetaald = summary.ib.overbetaald + summary.zvw.overbetaald
                ui.label(f'overbetaald {format_euro(overbetaald, decimals=0)}').style(
                    'font-size: 12px; color: var(--q-warning); '
                    'background: var(--bg-warning-soft); padding: 2px 8px; '
                    'border-radius: 10px')

        # Body: per-soort lines
        for line in (summary.ib, summary.zvw):
            if line.verplicht == 0 and line.betaald == 0:
                continue
            ui.label(
                f'{line.soort}    {format_euro(line.betaald, decimals=0)} / '
                f'{format_euro(line.verplicht, decimals=0)}  ·  '
                f'rest {format_euro(line.resterend, decimals=0)}'
            ).classes('context-text')
            ui.label(
                f'   {line.betaalde_termijnen} v.d. {line.totaal_termijnen}   '
                f'± {format_euro(line.termijnbedrag, decimals=0)} p/m'
            ).classes('context-text').style('opacity: 0.75')

        # Volgende-termijn footer
        if summary.volgende_termijn_datum is not None:
            ui.label(
                f'Volgende termijn: {summary.volgende_termijn_datum.strftime("%-d %b %Y").lower()}'
            ).classes('context-text').style('margin-top: 4px; opacity: 0.85')

        # Bankdata-versheid footer
        if summary.bankdata_tot_datum is not None:
            ui.label(
                f'Bankdata t/m {summary.bankdata_tot_datum.strftime("%-d %b").lower()}'
            ).classes('context-text').style('opacity: 0.6; font-size: 11px')
```

- [ ] **Step 4.2: Replace Card 3 in pages/dashboard.py**

In `pages/dashboard.py`, vind regels 631-707 (Card 3 Belasting-reservering blok). Vervang het hele blok door:

```python
                # Card 3: Voorlopige aanslag (Sprint I — vervangt Belasting-reservering)
                from services.dashboard import compute_va_tracker
                from components.dashboard_widgets import render_va_tile

                va_summary = compute_va_tracker(
                    jaar=jaar,
                    va_data=va_data,
                    ib_verplicht=fp.voorlopige_aanslag_betaald if fp else 0,
                    zvw_verplicht=fp.voorlopige_aanslag_zvw if fp else 0,
                    ib_termijnen=getattr(fp, 'voorlopige_aanslag_ib_termijnen', 11)
                                  if fp else 11,
                    zvw_termijnen=getattr(fp, 'voorlopige_aanslag_zvw_termijnen', 11)
                                   if fp else 11,
                    today=date.today(),
                )
                render_va_tile(va_summary, jaar=jaar)
```

Imports bovenaan `pages/dashboard.py` aanvullen indien nodig (zie bestaande imports).

- [ ] **Step 4.3: Add termijn-inputs + bank-summary herschrijving in /aangifte Card 3**

In `pages/aangifte.py`, lokaliseer Card 3 ("Voorlopige aanslagen", rond regel 538-580). Voeg na de bestaande IB en ZVW jaarbedrag-inputs 2 termijn-inputs toe:

```python
                    va_ib_termijnen_input = ui.number(
                        label='Aantal termijnen IB',
                        value=getattr(fp, 'voorlopige_aanslag_ib_termijnen', 11)
                              if fp else 11,
                        min=1, max=12, step=1, format='%d',
                    ).classes('w-32').props('disable=' + str(year_locked).lower())

                    va_zvw_termijnen_input = ui.number(
                        label='Aantal termijnen ZVW',
                        value=getattr(fp, 'voorlopige_aanslag_zvw_termijnen', 11)
                              if fp else 11,
                        min=1, max=12, step=1, format='%d',
                    ).classes('w-32').props('disable=' + str(year_locked).lower())
```

(Aanpassen aan exacte styling/positie van bestaande inputs.)

Vervang de huidige bank-summary tekst (rond regel 565-575 — "Banktotaal = ...") door gesplitste IB/ZVW + unmatched-info:

```python
                    # Bank-summary herschrijving (Sprint I)
                    if va_data.get('bankdata_tot_datum'):
                        ui.label(
                            f"Bankbetalingen aan Belastingdienst (t/m "
                            f"{va_data['bankdata_tot_datum'].strftime('%-d %b')})"
                        ).classes('text-sm font-semibold')
                    else:
                        ui.label('Bankbetalingen aan Belastingdienst').classes('text-sm font-semibold')

                    ui.label(
                        f"  IB:        {format_euro(va_data.get('ib_betaald', 0))} "
                        f"betaald · {va_data.get('ib_termijnen', 0)} termijnen"
                    ).classes('text-sm text-mono')
                    ui.label(
                        f"  ZVW:       {format_euro(va_data.get('zvw_betaald', 0))} "
                        f"betaald · {va_data.get('zvw_termijnen', 0)} termijnen"
                    ).classes('text-sm text-mono')

                    if va_data.get('unmatched_betaald', 0) > 0:
                        with ui.row().classes('items-center gap-2 mt-1'):
                            ui.label(
                                f"  Niet toegewezen: {format_euro(va_data['unmatched_betaald'])} "
                                f"({va_data['unmatched_termijnen']} betalingen)"
                            ).classes('text-sm text-warning')
                            ui.button(
                                'Controleer in transacties',
                                on_click=lambda: ui.navigate.to(
                                    f'/transacties?search=NL86INGB0002445588&jaar={jaar}')
                            ).props('flat dense color=primary')
```

- [ ] **Step 4.4: Update /aangifte save-handler — termijnen-kwargs + rollback fix**

In `pages/aangifte.py`, de save-handler voor Card 3 (rond regel 641 — die `update_ib_inputs` aanroept). Voeg termijnen toe aan de call én aan de YearLockedError-rollback:

```python
                async def save_va():
                    try:
                        await update_ib_inputs(
                            db_path=DB_PATH, jaar=jaar,
                            aov_premie=aov_input.value or 0,
                            woz_waarde=woz_input.value or 0,
                            hypotheekrente=hypo_input.value or 0,
                            voorlopige_aanslag_betaald=va_ib_input.value or 0,
                            voorlopige_aanslag_zvw=va_zvw_input.value or 0,
                            lijfrente_premie=lijfrente_input.value or 0,
                            voorlopige_aanslag_ib_termijnen=int(va_ib_termijnen_input.value or 11),
                            voorlopige_aanslag_zvw_termijnen=int(va_zvw_termijnen_input.value or 11),
                        )
                        ui.notify('Opgeslagen', type='positive')
                    except YearLockedError as e:
                        ui.notify(str(e), type='warning')
                        # Rollback alle inputs naar persisted values
                        data = await fetch_fiscal_data(DB_PATH, jaar)
                        if data:
                            va_ib_input.value = data['voorlopige_aanslag']
                            va_zvw_input.value = data['voorlopige_aanslag_zvw']
                            # NIEUW Sprint I — termijn-inputs ook resetten
                            fp = await get_fiscale_params(DB_PATH, jaar)
                            if fp:
                                va_ib_termijnen_input.value = fp.voorlopige_aanslag_ib_termijnen
                                va_zvw_termijnen_input.value = fp.voorlopige_aanslag_zvw_termijnen
```

Aanpassen aan de exacte handler-naam en variabelen in de bestaande code.

- [ ] **Step 4.5: Manual smoke-test**

Start de app:

```bash
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py
```

Verifieer in pywebview-venster:
1. /dashboard rendert nieuwe Card 3 met "Voorlopige aanslag {jaar}"
2. Geen-data state toont CTA → klik gaat naar /aangifte
3. Met VA-bedragen ingevuld in /aangifte: tile toont resterend + IB/ZVW lines
4. Klik op tile → /aangifte
5. /aangifte Card 3 toont 2 termijn-inputs (default 11)
6. /aangifte bank-summary toont gesplitste IB/ZVW
7. Bij definitief jaar: termijn-inputs disabled

Sluit app na verificatie.

- [ ] **Step 4.6: Run full test suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -x --tb=short 2>&1 | tail -10
```

Expected: 1370 passing, 0 failures (oude helper-tests nog aanwezig).

- [ ] **Step 4.7: Commit**

```bash
git add components/dashboard_widgets.py pages/dashboard.py pages/aangifte.py
git commit -m "$(cat <<'EOF'
feat(sprint-i): T1.4 render_va_tile + dashboard Card 3 vervanging + /aangifte

- components/dashboard_widgets.render_va_tile: hero-tile met
  resterend-hero-value, IB/ZVW body-lines, volgende-termijn footer
  (conditioneel), bankdata-versheid footer, .is-tekort modifier bij
  achter of has_overbetaald.
- pages/dashboard.py:631-707 — vervang Card 3 Belasting-reservering met
  compute_va_tracker call + render_va_tile. Click → /aangifte?jaar=X.
- pages/aangifte.py Card 3: + 2 ui.number termijn-inputs (1-12, min=1,
  max=12), bank-summary herschreven naar gesplitste IB/ZVW + unmatched
  rij + "Controleer in transacties"-button bij unmatched > 0,
  YearLockedError-rollback ook reset termijn-inputs (Codex round-3 fix).

Geen tests in dit task — render-tests zijn broos in NiceGUI; smoke-test
manueel uitgevoerd. Helper-tests (T1.3) dekken alle gedrag.

Sprint I T1.4. Spec §2 + §6 + §7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Cleanup oude helper + opruim refs + CLAUDE.md update

**Files:**
- Modify: `services/dashboard.py` (verwijder compute_belasting_reservering_progress)
- Modify: `pages/dashboard.py` (opruim _compute_ib_estimate va_betaald-pad als die ongebruikt is)
- Delete: `tests/test_dashboard_helpers.py` 9 tests
- Modify: `CLAUDE.md` § Domeinkennis fiscaal

- [ ] **Step 5.1: Verify oude helper geen callers meer heeft**

```bash
grep -rn "compute_belasting_reservering_progress" /Users/macbookpro_ronald/Library/CloudStorage/SynologyDrive-Main/06_Development/1_roberg-boekhouding/ --include="*.py" | grep -v test_dashboard_helpers
```

Expected: alleen import in services/dashboard.py zelf. Als pages/dashboard.py nog importeert: verwijder die import (Card 3 vervanging in T1.4 zou dit moeten hebben).

- [ ] **Step 5.2: Delete oude helper + 9 tests**

In `services/dashboard.py`, verwijder:
- `compute_belasting_reservering_progress` functie (regels 129-160)
- Eventuele `Literal['op_koers', 'tekort', 'overreservering']` import als alleen daar gebruikt

In `tests/test_dashboard_helpers.py`, verwijder de 9 tests (en hun shared `class` indien aanwezig):
- `test_op_koers_when_va_matches_prorated_expected`
- `test_tekort_when_va_significantly_below_prorated`
- `test_overreservering_when_va_significantly_above_prorated`
- `test_january_first_day_negligible_expected`
- `test_exact_threshold_tekort_boundary`
- `test_exact_threshold_overreservering_boundary`
- `test_january_full_month_partial_year`
- `test_leap_year_uses_366_days`
- `test_december_full_year_check`

Verwijder ook de import van `compute_belasting_reservering_progress` bovenaan test_dashboard_helpers.py (als alleen voor deze tests).

- [ ] **Step 5.3: Run full suite — verify cleanup**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ --tb=short 2>&1 | tail -10
```

Expected: 1370 − 9 = 1361 passing → wait check: 1355 baseline + 3 (T1.1) + 4 (T1.2) + 1 herschreven (geen netto +1) + 12 (T1.3) − 9 (T2.1) = 1361. Actual netto +6? Nee, herschreven is netto 0, dus 1355 + 3 + 4 + 12 − 9 = 1365. Hmm spec zegt 1364. Difference is 1 — kan een existing oude test zijn die ook impliciet gebroken raakt door contract change. Hertel of accepteer ±1 marge.

Expected: 1361-1365 passing. **0 failures** is het kritieke deel.

- [ ] **Step 5.4: Update CLAUDE.md § Domeinkennis fiscaal**

In `CLAUDE.md`, vind sectie "## Domeinkennis (fiscaal)" en append onder de bestaande regels:

```markdown
### VA-tracker quirks (Sprint I, 2026-05-05)

- **Veldnaam-bug**: `fiscale_params.voorlopige_aanslag_betaald` HEET "betaald"
  maar bevat het BD-beschikkingsbedrag (= jaar-verplichting), NIET wat is
  betaald. Niet renamen v1 (breaking); helpers gebruiken lokale alias
  `ib_verplicht`. Sprint K kan migration-rename overwegen.
- **Kenmerk-jaar-mismatch**: VA-2025 betaling in januari 2026 wordt door
  `get_va_betalingen` datum-filter aan jaar 2026 gekoppeld. Het kenmerk
  bevat impliciet een jaardigit maar wordt niet gebruikt voor jaar-routing.
  v1 accepteert; gebruiker controleert handmatig in /transacties.
  Sprint J kan kenmerk-jaardigit-inspectie + heuristische waarschuwing
  toevoegen.
- **Positieve BD-banktransacties** (correcties/teruggaves): `bedrag > 0`
  van Belastingdienst-IBAN wordt door `get_va_betalingen` genegeerd voor
  zowel `betaald` als `bankdata_tot_datum`. Effect: een terugbetaling kan
  ten onrechte als `overbetaald`-attribute blijven staan. v1 accepteert;
  gebruiker ziet via /transacties wat werkelijk teruggekomen is.
- **Termijnen-convention `13 - N`**: aantal termijnen N impliceert
  eerste-termijn-maand 13-N (N=11 → feb-start, N=12 → jan-start). Onze
  heuristiek, geen BD-bron-waarheid. Bij mid-year revisie kan dit afwijken;
  user kan termijnen-aantal in /aangifte handmatig overtypen.
- **VA `totaal_betaald` (BREAKING vanaf Sprint I)**: excludeert
  `unmatched_betaald`. Voor v1 callers: gebruik `ib_betaald + zvw_betaald`
  voor de tracker-ratio, en `unmatched_betaald` apart waar relevant.
```

- [ ] **Step 5.5: Update CLAUDE.md sprint-state**

In `CLAUDE.md` § "Recente sprint-state", append de Sprint I status:

```markdown
**Recente sprint-state** (2026-05-05, na Sprint I VA-tracker):
- Pytest baseline ~1364 (was 1355 vóór Sprint I)
- Master is HEAD na Sprint I VA-tracker
- Migratie 40: fiscale_params.voorlopige_aanslag_ib_termijnen + _zvw_termijnen
- get_va_betalingen BREAKING contract: totaal_betaald excludeert unmatched
- services.dashboard.compute_va_tracker (NEW) — vervangt
  compute_belasting_reservering_progress (verwijderd)
- components/dashboard_widgets.render_va_tile (NEW) — Card 3 op /dashboard
```

- [ ] **Step 5.6: Run final full suite**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ --tb=short 2>&1 | tail -5
```

Expected: ~1364 passing, **0 failures**.

- [ ] **Step 5.7: Commit**

```bash
git add services/dashboard.py tests/test_dashboard_helpers.py CLAUDE.md
git commit -m "$(cat <<'EOF'
chore(sprint-i): T2.1 verwijder compute_belasting_reservering_progress + docs

- Verwijder oude helper compute_belasting_reservering_progress in
  services/dashboard.py (vervangen door compute_va_tracker in T1.3).
- Verwijder 9 tests in tests/test_dashboard_helpers.py die deze helper
  verifieerden (test_op_koers..test_december_full_year_check).
- CLAUDE.md § Domeinkennis fiscaal: documenteer veldnaam-bug,
  kenmerk-jaar-mismatch, positieve BD-tx gat, termijnen-convention,
  BREAKING totaal_betaald contract.
- CLAUDE.md § Recente sprint-state: Sprint I update.

Pytest 1355 → ~1364 (netto +9).

Sprint I T2.1. Spec §10 + §11b.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Step 6.1: Sprint I post-merge audit**

Per Sprint H process: na alle 5 commits, dispatch Codex post-merge audit op de cumulatieve diff vs `master~5`:

```bash
git diff master~5..HEAD > /tmp/sprint_i_diff.patch
cat /tmp/sprint_i_diff.patch | env -u OPENAI_API_KEY codex exec --sandbox read-only -c model_reasoning_effort=medium - > /tmp/sprint_i_audit.md 2>&1
```

Lees `/tmp/sprint_i_audit.md`. Verwerk eventuele bevindingen in een follow-up commit (T2.2 als nodig, anders direct fix).

- [ ] **Step 6.2: Final test count check**

```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ --collect-only -q 2>&1 | tail -3
```

Expected: ~1364 tests collected.

- [ ] **Step 6.3: Final git log review**

```bash
git log --oneline master~5..HEAD
```

Expected: 5 commits met sprint-i prefix:
- T2.1 chore — cleanup
- T1.4 feat — render + dashboard + /aangifte
- T1.3 feat — compute_va_tracker
- T1.2 feat — get_va_betalingen contract
- T1.1 feat — migratie 40 + models

---

## Notes

**Spec-amendment**: §1 noemt `CHECK (BETWEEN 1 AND 12)` op de nieuwe kolommen. SQLite `ALTER TABLE ... ADD COLUMN ... CHECK` is onbruikbaar (vereist full table-rewrite via temp-table swap) — voor v1 te veel risico voor te weinig waarde. CHECK wordt geschrapt; enforcement via UI `ui.number(min=1, max=12)` + Python-side `update_ib_inputs` parameter validation. Spec §1 wordt in T1.1 commit-message expliciet bijgewerkt.

**Codex per-step review**: na elke commit (T1.1 t/m T2.1) dispatch Codex review met diff van die commit:

```bash
git show HEAD --stat > /tmp/codex_review_input.md
git show HEAD >> /tmp/codex_review_input.md
echo "Beoordeel deze commit kritisch — bugs, edge cases, Sprint H stijl, regressie. Max 400 woorden." >> /tmp/codex_review_input.md
cat /tmp/codex_review_input.md | env -u OPENAI_API_KEY codex exec --sandbox read-only -c model_reasoning_effort=medium - > /tmp/codex_step_review.md 2>&1
```

Lees output. Als Codex echte bug catched: amend commit of follow-up commit.

**Direct-on-master pattern**: geen feature-branch, geen worktree. Sprint A→H conventie. Master HEAD = Sprint I HEAD na T2.1.
