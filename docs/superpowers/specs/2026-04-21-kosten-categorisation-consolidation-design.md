# Kosten categorisation consolidation + table fixes

**Date**: 2026-04-21
**Status**: design — not yet implemented
**Supersedes nothing** — builds on `2026-04-21-kosten-rework-design.md`

## Problem

The Kosten page has three user-visible defects and one structural defect that surface together when the user opens `/kosten` for the first time after the Kosten rework shipped:

1. **Bedrag column is invisible in windowed mode.** The `Tegenpartij / Omschrijving` cell renders the full raw Rabobank omschrijving (≈170 chars of POS metadata for card transactions — e.g. `Rotterdam, 3012 CN, NLD, 07:43 . Pas: 5xxxx7118 Terminal: TERMBNET. Appr Cd: 418C24 Apple Pay Token: 5xxxx1610`). Table columns have no explicit widths, so Quasar auto-sizes to the longest cell. Tegenpartij eats the viewport; Categorie and Bedrag get pushed off-screen.

2. **Categorie dropdown ("— kies —") does nothing.** The `body-cell-categorie` slot uses a `q-btn-dropdown` with a teleported `q-menu`. `q-item @click="$parent.$emit('set_cat', …)"` fires into the teleported popup's parent — not the `q-table`. `tbl.on('set_cat', …)` never receives the event.

3. **"Factuur ontbreekt 101 / €51.439" KPI is mislabeled.** The count aggregates `ontbreekt + ongecategoriseerd` (database.py:3264) — both are "needs attention" states. The label claims only the former.

4. **Two-source categorisation.** `banktransacties.categorie` and `uitgaven.categorie` both exist. `get_kosten_view` reads only the latter (database.py:3139). Categorie set on `/bank` for a debit is invisible everywhere: KPIs, breakdown, aangifte. Users who used /bank to categorise pre-Kosten-rework have their work orphaned. Users coming fresh see two places offering the same action and reasonably conclude the app is inconsistent.

## Goals

- `/kosten` table is readable in a default 1400×900 native window, with bedrag always visible.
- Clicking `— kies —` on a row and picking a category persists it and updates the row status badge.
- The KPI label matches what the number actually counts.
- Categorisation of a bank debit persists to exactly one backing column (`uitgaven.categorie`), regardless of which page the user initiates the change from. `/bank` and `/kosten` always agree for any given debit.
- No categorisation data is lost from prior `/bank` sessions.

## Non-goals

- Auto-hiding own-transfer / Belastingdienst / owner-draw rows (deferred to a follow-up spec; rule-based classifiers need real data before designing).
- Suggestion-toverstaf on `/kosten` (deferred; exists on `/bank` and can port later).
- Changes to the inbox card, breakdown card, investeringen tab, or dialogs.
- Changes to the fiscal engine, `/facturen`, `/aangifte`, or any aggregation downstream of `uitgaven.categorie`.

## Design

### 1. Table column widths

Add explicit `style` directives to the columns at `pages/kosten.py:609-622`. Quasar's default `table-layout: auto` can override a bare `width:` — both `min-width` and `max-width` are needed for actual enforcement.

| Name | Label | Style (applied to `style` and `headerStyle`) | Align |
|---|---|---|---|
| datum | Datum | `width: 110px; min-width: 110px` | left |
| tegenpartij | Tegenpartij / Omschrijving | *(no width — flex fills remainder)* | left |
| categorie | Categorie | `width: 180px; min-width: 180px; max-width: 180px` | left |
| factuur | Factuur | `width: 130px; min-width: 130px; max-width: 130px` | left |
| bedrag | Bedrag | `width: 120px; min-width: 120px; max-width: 120px; font-variant-numeric: tabular-nums` | right |
| acties | (empty) | `width: 90px; min-width: 90px; max-width: 90px` | center |

No change to the underlying fields or sort behaviour.

### 2. Omschrijving truncation

In the `body-cell-tegenpartij` slot (kosten.py:827-852), constrain the secondary `<div>` so long Rabobank POS metadata truncates cleanly. Flexbox pitfall: the text-wrapper (sibling of the avatar) must have `min-width: 0` — flex children default to `min-width: auto` which prevents shrinking below content size, and ellipsis never fires otherwise.

```vue
<q-td :props="props">
  <div class="row items-center q-gutter-sm"
       style="width: 100%; flex-wrap: nowrap;">
    <div :style="`background:${props.row.color};
                  color:white; width:30px; height:30px;
                  border-radius:7px;
                  display:grid; place-items:center;
                  font-weight:700; font-size:11px;
                  flex-shrink:0;`">
      {{ props.row.initials }}
    </div>
    <div style="min-width: 0; flex: 1;">
      <div style="font-weight: 500;
                  white-space: nowrap;
                  overflow: hidden;
                  text-overflow: ellipsis;"
           :title="props.row.tegenpartij">
        {{ props.row.tegenpartij }}
      </div>
      <div class="text-caption text-grey"
           v-if="props.row.omschrijving &&
                 props.row.omschrijving !== props.row.tegenpartij"
           :title="props.row.omschrijving"
           style="white-space: nowrap;
                  overflow: hidden;
                  text-overflow: ellipsis;">
        {{ props.row.omschrijving }}
      </div>
    </div>
  </div>
</q-td>
```

The `:title` attribute provides a native browser tooltip so the full omschrijving stays reachable on hover. Truncation applies to the tegenpartij line too — rarely needed but defends against long vendor names.

### 3. Categorie dropdown — replace with `q-select`

Replace the current `q-btn-dropdown` in `body-cell-categorie` (kosten.py:854-873) with an inline `q-select` mirroring the working pattern on `/bank` (bank.py:466-481). The key behavioural change: `q-select`'s `@update:model-value` emit fires from the component itself (not from a teleported menu item), so `$parent.$emit('set_cat', …)` reaches the `q-table`.

Interpolate the options list directly into the slot template with `json.dumps(KOSTEN_CATEGORIEEN)` — matches the /bank pattern (bank.py:470) and drops the `window.__KOSTEN_CAT_LIST__` global, the `ui.add_body_html` injection on kosten.py:1031-1034, and the race-at-mount concern.

```python
tbl.add_slot('body-cell-categorie', r"""
    <q-td :props="props" :class="props.row.categorie ? '' : 'bg-orange-1'">
      <q-select
        :model-value="props.row.categorie"
        :options='""" + json.dumps(CATEGORIEEN) + r"""'
        dense borderless emit-value map-options
        placeholder="— kies —"
        @update:model-value="val => $parent.$emit('set_cat',
                                                   {row: props.row, cat: val})"
        style="min-width: 160px" />
    </q-td>
""")
```

(Mirrors the `r"""..."""` + concatenated `json.dumps(...)` style already used by bank.py:446-490.)

No JS contract change for the Python handler `_on_set_cat` (kosten.py:648-666) — it already accepts `{row, cat}` dicts and routes through `ensure_uitgave_for_banktx` / `update_uitgave`.

**Related cleanup**: delete the `ui.add_body_html('<script>window.__KOSTEN_CAT_LIST__ = ...</script>')` call at kosten.py:1031-1034 since nothing else references it after this change.

**Visual note**: `q-select borderless dense` renders without the outlined box, close to the lightweight aesthetic of the current dropdown. The cell gets a soft `bg-orange-1` tint when the categorie is empty and no tint when it's set — same signal as today's warning-coloured button label.

### 4. KPI relabel

`pages/kosten.py:505` — change the card title from `'Factuur ontbreekt'` to `'Te verwerken'`. The sublabel `format_euro(kpi.ontbreekt_bedrag)` and the count stay unchanged. Icon `warning` stays. No change to `get_kpi_kosten` semantics — the aggregation of `ontbreekt + ongecategoriseerd` into `ontbreekt_count` is correct for this KPI, the label was just wrong.

### 5. `/bank` — unify the write path for debit categorie

**Revised approach (replaces the earlier "remove dropdown" draft).** Keep the existing `q-select` categorie cell on `/bank` for both positive and negative rows — *but* change what happens when the user picks a value on a **debit** row. Instead of writing to `banktransacties.categorie`, route the write through `ensure_uitgave_for_banktx` so the categorie lands on `uitgaven.categorie` — the same column `/kosten` uses. Both pages now agree, no orphan data is ever produced, and no user-visible workflow changes.

Rationale for this revision: removing the dropdown is more invasive, breaks existing reflexes (the user has a working mental model of "click categorie, pick from list"), and requires a read-only fallback label plus a caption. Routing the write is a single-branch change in one handler, with zero UI diff.

**Display side** (`pages/bank.py:37-81` `load_transacties`): for each transaction, supply the displayed categorie from whichever table is authoritative for that sign:
- Positive rows (`bedrag >= 0`): continue to use `banktransacties.categorie` as today.
- Negative rows: read `uitgaven.categorie` via a linked-uitgave lookup.

Implementation: after loading the transaction list, issue a single secondary query
```sql
SELECT bank_tx_id, categorie FROM uitgaven WHERE bank_tx_id IS NOT NULL
```
and build a dict `{bank_tx_id: uitgave_categorie}`. For each row with `bedrag < 0`, set `row['categorie']` from the dict (default `''`). Keeps one DB round-trip per page load.

**Write side** (`pages/bank.py:248-252` `handle_categorie_change`): branch on the sign of the transaction:
```python
async def handle_categorie_change(row_id: int, new_cat: str):
    # Look up the bank tx to decide where the categorie lives.
    async with get_db_ctx(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT bedrag FROM banktransacties WHERE id = ?", (row_id,))
        r = await cur.fetchone()
    if r is None:
        return
    if r['bedrag'] < 0:
        # Debit → route into uitgaven.categorie (unified with /kosten).
        await ensure_uitgave_for_banktx(
            DB_PATH, bank_tx_id=row_id, categorie=new_cat)
    else:
        # Positive (deposit / refund) → stays on banktransacties.categorie.
        await update_banktransactie(
            DB_PATH, transactie_id=row_id, categorie=new_cat)
    ui.notify('Categorie bijgewerkt', type='positive')
    await refresh_table()
```

Note: `ensure_uitgave_for_banktx` already handles the lazy-create-then-update-categorie path and is year-locked, so YearLockedError surfaces automatically. The positive-row path continues to update `banktransacties.categorie` directly — those rows never have a linked uitgave (get_kosten_view filters `bedrag < 0`), so there's nothing to unify there.

**Tiny caption** above the bank table (one line, grey caption style):

> *Categorieën op debit-regels worden centraal in Kosten opgeslagen.*

This explains why categorising here "just works" without exposing the implementation detail. Optional — can drop if it feels over-explained.

**What this change does NOT do**: does not filter the `q-select` options for positive rows. `BANK_CATEGORIEEN` still includes kosten categories (`Telefoon/KPN`, etc.) on positive rows, which is nonsensical semantically but mirrors status quo. Out of scope — a separate cleanup.

### 6. One-off data migration (migratie 27)

Callable migration, same pattern as `_run_migration_7`, `_18`, `_20`, `_21` (database.py:466+). Add to the `MIGRATIONS` list and register in `_MIGRATION_CALLABLES`:

```python
MIGRATIONS = [
    ...existing through 26...
    (27, "migrate_bank_categorie_to_uitgaven", None),
]
_MIGRATION_CALLABLES = {
    7: _run_migration_7, 8: _run_migration_8,
    18: _run_migration_18, 20: _run_migration_20, 21: _run_migration_21,
    27: _run_migration_27,
}
```

**Why callable, not inline SQL**: the migration needs year-by-year guarding (`jaarafsluiting_status = 'definitief'` skip) and must distinguish "insert new uitgave" vs "update existing empty-categorie uitgave" — neither expressible cleanly as one SQL statement. Using a callable also lets us reuse `init_db`'s connection instead of opening a nested `get_db_ctx` (which would risk WAL-mode writer-lock contention).

**Procedure**:

```python
async def _run_migration_27(conn):
    """Copy banktransacties.categorie (debits only) into uitgaven.categorie.

    Pre-rework, users categorised debits via /bank, writing to
    banktransacties.categorie. Post-rework, get_kosten_view only reads
    uitgaven.categorie, so that data became orphaned. This migration
    reconciles: for each bank debit with a non-empty categorie, either
    update the linked uitgave (if empty-categorie) or lazy-create a new
    uitgave carrying the categorie.

    Skipped:
    - Bank rows marked genegeerd=1 (privé — not business expenses).
    - Rows whose year is jaarafsluiting_status='definitief' (frozen —
      snapshot-rendered, retroactive uitgaven creation would drift the
      underlying data from the snapshot).
    - Linked uitgaven whose categorie is already non-empty (user's own
      data on /kosten wins — never overwritten).

    Idempotent: re-running is a no-op (the non-empty-categorie guard on
    updates, and the linked-uitgave guard on inserts, both eliminate
    their own target sets after one successful pass).
    """
    # Which years are frozen?
    cur = await conn.execute(
        "SELECT jaar FROM fiscale_params "
        "WHERE jaarafsluiting_status = 'definitief'")
    frozen = {r[0] for r in await cur.fetchall()}

    # Candidate bank debits (categorie set, not ignored).
    cur = await conn.execute("""
        SELECT b.id, b.datum, b.bedrag, b.tegenpartij,
               b.omschrijving, b.categorie, u.id AS uitgave_id,
               u.categorie AS uitgave_cat
        FROM banktransacties b
        LEFT JOIN uitgaven u ON u.bank_tx_id = b.id
        WHERE b.bedrag < 0
          AND b.genegeerd = 0
          AND b.categorie IS NOT NULL
          AND b.categorie != ''
    """)
    candidates = await cur.fetchall()

    for row in candidates:
        jaar = int(row['datum'][:4])
        if jaar in frozen:
            continue

        if row['uitgave_id'] is not None:
            # Path A: linked uitgave exists. Only fill in if empty —
            # never overwrite user's own /kosten categorie.
            if not (row['uitgave_cat'] or '').strip():
                await conn.execute(
                    "UPDATE uitgaven SET categorie = ? WHERE id = ?",
                    (row['categorie'], row['uitgave_id']))
        else:
            # Path B: no linked uitgave — lazy-create. Match the
            # omschrijving convention from ensure_uitgave_for_banktx
            # (tegenpartij or fallback) so migrated rows are
            # indistinguishable from future-lazy-created rows.
            omschrijving = (
                (row['tegenpartij'] or '').strip()
                or (row['omschrijving'] or '').strip()
                or '(bank tx)')
            await conn.execute("""
                INSERT INTO uitgaven
                    (datum, categorie, omschrijving, bedrag, bank_tx_id)
                VALUES (?, ?, ?, ?, ?)
            """, (row['datum'], row['categorie'], omschrijving,
                  abs(row['bedrag']), row['id']))
    # Note: no explicit commit — init_db's migration loop commits once per
    # version on success.
```

**Why not drop `banktransacties.categorie` entirely**: positive rows still use it (see §5). The column stays in the schema. Only the debit values get a partner uitgave row.

**Migration-skipped rows (definitief years) behaviour**: their `banktransacties.categorie` data stays orphaned. `get_kosten_view` won't surface it. If the user re-opens the year via Jaarafsluiting → Heropenen, the migration re-runs on the next app start (it's idempotent and the year is no longer in `frozen`) and picks them up. Acceptable.

**Honest scope note**: on a fresh install or an install where `/bank` was never used for debit categorisation, this migration finds zero candidates and is a no-op. Shipping it is cheap insurance, not a hot path.

### 7. Testing

**Unit tests** (add to `tests/test_migrations.py` — or a new `tests/test_migration_27.py`):

- `test_migratie_27_lazy_creates_uitgave_for_debit_with_categorie`: seed a bank debit with `categorie='Telefoon/KPN'` and no linked uitgave in a concept year → run migration → assert uitgave exists with matching `categorie`, `bank_tx_id`, `bedrag=ABS(bank.bedrag)`, `omschrijving=<tegenpartij>`.
- `test_migratie_27_copies_categorie_into_empty_uitgave`: seed a bank debit linked to an uitgave with empty categorie, bank has `categorie='Verzekeringen'` → run migration → assert uitgave's categorie is now `'Verzekeringen'`.
- `test_migratie_27_does_not_overwrite_nonempty_uitgave_categorie`: seed uitgave with `categorie='Representatie'`, bank has `categorie='Verzekeringen'` → run migration → assert uitgave still `'Representatie'` (user's /kosten entry wins).
- `test_migratie_27_skips_definitief_year`: seed as first test but year is `definitief` → assert no uitgave created, no UPDATE performed.
- `test_migratie_27_skips_genegeerd_rows`: seed a bank debit with `categorie='Telefoon/KPN'`, `genegeerd=1` → assert no uitgave created.
- `test_migratie_27_skips_debits_with_empty_categorie`: seed a bank debit with `categorie=''` → assert no uitgave created.
- `test_migratie_27_skips_positive_transactions`: seed a bank row with `bedrag=+100` and `categorie='Omzet'` → assert no uitgave created (positive-row categorie stays on banktransacties).
- `test_migratie_27_idempotent`: run twice, assert uitgaven row count and values unchanged after second run.

**New unit test for the /bank write-path split** (add to `tests/test_bank.py` or a new module):

- `test_bank_categorie_change_on_debit_writes_to_uitgave`: seed a debit bank tx, call `handle_categorie_change` → assert a new uitgave exists with `bank_tx_id = <debit>`, `categorie = <new>`, and `banktransacties.categorie` for that row is unchanged (empty).
- `test_bank_categorie_change_on_positive_writes_to_banktransacties`: seed a positive bank tx, call `handle_categorie_change` with `'Omzet'` → assert `banktransacties.categorie = 'Omzet'` for that row, no new uitgave created.

**Widget acceptance test** (manual, this is the ship gate):

Launch `python main.py` in the default 1400×900 native window and:

1. Open `/kosten` with a year that has bank data. Confirm:
   - All six columns are visible without horizontal scroll — Bedrag is on the right edge.
   - The Coolblue row's POS metadata (`Rotterdam, 3012 CN…`) is truncated with `…`; hovering the cell shows the full string as a browser tooltip.
   - Rows with no categorie show an orange-tinted cell and the placeholder `— kies —`.
2. Click a `— kies —` cell. The dropdown opens.
3. Pick `Telefoon/KPN`. Confirm:
   - A toast "Categorie bijgewerkt naar Telefoon/KPN" appears.
   - The cell's orange tint disappears and now shows `Telefoon/KPN`.
   - The Factuur badge for that row changes from `Nieuw` to `Ontbreekt` (amber with a warning icon).
   - **The KPI "Te verwerken" count does NOT change** — `ontbreekt` and `ongecategoriseerd` both count towards it. (Count decreases only once BOTH categorie AND PDF are set.)
4. Open `/bank`. Pick a categorie on a debit row. Confirm:
   - Toast "Categorie bijgewerkt".
   - The row's categorie persists after page reload.
   - Navigate to `/kosten` — the same bank row now shows that categorie too (unified backing).
5. On `/bank`, pick `Omzet` on a positive row. Confirm the categorie persists and does NOT appear on `/kosten` (positive rows aren't in the kosten view).

**Regression checks**:
- `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v` — must stay at 0 failures.
- Exercise the bulk "Categorie wijzigen" action on `/kosten` on 2 selected rows — must still work (unchanged code path).
- Exercise the "Nieuwe uitgave" dialog — categorie `ui.select` must still work (uses same `KOSTEN_CATEGORIEEN` list; unchanged).
- Exercise the CSV import match-preview dialog on `/bank` — must still work (no change to that code path).

## Out-of-scope follow-ups (tracked, not designed here)

- **Rules-based auto-hiding** of owner transfers, Belastingdienst IB/ZVW, Boekhouder AOV → deferred. Needs classification research before design.
- **Suggestion-toverstaf on /kosten** — port from /bank. Small, can be a one-file PR after B ships.
- **Inbox card redesign** (4 chips → efficient bulk surface for 100+ rows) — not in this spec.
- **`banktransacties.categorie` column removal** — requires first removing the positive-row categorie workflow (deferred). Column stays for now.

## Risks

- **Quasar `q-select borderless` visual regression**: it may not perfectly match the current chip aesthetic. Acceptable if readability and function are preserved; visual polish is a follow-up. Mitigation: ship, screenshot, adjust CSS if needed.
- **Migration 27 edge case — bank debit with categorie in a definitief year**: categorie stays orphaned until the user re-opens the year. The migration re-runs idempotently on next app start and picks them up once unfrozen. Documented as accepted behaviour.
- **`load_transacties` linked-uitgave lookup on /bank**: adds one secondary query (`SELECT bank_tx_id, categorie FROM uitgaven WHERE bank_tx_id IS NOT NULL`) per page load. Single-user, thousands-of-rows max, indexed by `idx_uitgaven_bank_tx` (migratie 26). Negligible cost.
- **/bank write-path split introduces per-click async sign-lookup**: `handle_categorie_change` now issues a SELECT to decide which table to write. One extra round-trip per categorie change — imperceptible on local SQLite but worth flagging. Alternative: carry the sign of the bedrag in the Vue-side row dict (already there as `props.row.bedrag`) and pass it through the emit payload, so the Python handler gets both `id` and `bedrag` and can branch without an extra query. Marginal optimisation; default to the SELECT for simplicity unless profiling shows a hot spot.
- **Two categorie write surfaces existing simultaneously**: after this spec, `/bank` (for positives) and `/kosten` (for debits) both write categorie, but to different tables based on row sign. Concise, but a future dev may re-discover the "why two paths?" question. Mitigation: the inline comment in `handle_categorie_change` explaining the split, plus this spec in `docs/superpowers/specs/`, plus a short note in `CLAUDE.md` under the Kosten-pagina section once B lands.
