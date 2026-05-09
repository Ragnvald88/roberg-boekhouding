# Boekhouding App

Standalone boekhoudapplicatie (NiceGUI + Python) voor een eenmanszaak huisartswaarnemer. Draait lokaal op macOS als native venster (pywebview). Data in `~/Library/Application Support/Boekhouding/data/` (niet in git, niet op cloud-sync).

## Werkwijze met de gebruiker

Gebruiker is huisartswaarnemer, geen coding-expert. Optimaliseer voor begrijpelijke, werkende code — niet voor cleverness of jargon.

- **Vóór niet-triviaal werk**: herformuleer in één zin wat je denkt dat het doel is + flag ambiguïteit vóór je code aanraakt. Triviale edits (typo, één-regel-fix) slaan dit over.
- **Multi-step werk → TodoWrite**: zo ziet de gebruiker voortgang. Markeer items af zodra écht klaar (niet batchen).
- **Proeflezen vóór "klaar"**: (1) lees je eigen diff terug, (2) draai relevante tests, (3) controleer dat de oorspronkelijke vraag écht beantwoord is — niet alleen "code compileert / tests groen".
- **Trade-offs in gewone taal**: als je kiest tussen aanpak A en B, noem 't in één zin zonder library-jargon-dump.
- **Push back op foute aannames**: als de prompt iets aanneemt dat de codebase weerspreekt, zeg het in één zin vóór je bouwt.
- **Geen ongevraagde meegeleverde refactors**: een bugfix is een bugfix. Cleanup-suggesties mogen, maar als losse vervolgstap.
- **Bij niet-triviaal werk: toon de afweging kort** (2-3 aanpakken overwogen, welke gekozen, waarom).
- **Codex auto-review (verplicht na code-changes)**: na Edit/Write op `.py`/`.html`/`.sql`/`.css`-files, vóór "klaar"-rapportage: invoke de `codex-review` skill. Bevindingen zelf evalueren (`superpowers:receiving-code-review` principes), niet blind overnemen. Skip voor pure docs/comment changes. Kill switch: `SKIP_CODEX_REVIEW=1`. Zie `docs/architecture/codex-collab.md` voor 4-layer review-pattern.

## Quality gates — MANDATORY before claiming done

- Run pytest: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v`. 0 failures vereist.
- Bij bug-fix: demonstreer dat het scenario werkt.
- `.codex/hooks/quality-gate.sh` blokkeert Stop bij failing tests (Claude Code Stop hook).
- `.codex/hooks/codex-claude-review.sh` (symmetric Stop hook) → Claude reviewt elke directe `codex exec` diff. Kill switch: `SKIP_CLAUDE_REVIEW=1`.
- `tests/test_documentation.py` bewaakt CLAUDE.md/AGENTS.md grootte + structuur.
- `tests/test_visual_css.py` bewaakt cascade-discipline.

## Tech stack

- **UI**: NiceGUI ≥3.0 (Quasar/Vue), **native via pywebview** (`ui.run(native=True, window_size=(1400, 900))`). Eén proces, één venster, eigen dock-icon. `Boekhouding.app` is een thin AppleScript-launcher.
- **Database**: SQLite via aiosqlite, raw SQL met `?` placeholders, GEEN ORM. Zie `docs/architecture/database.md`.
- **PDF**: WeasyPrint + Jinja2 (`templates/factuur.html`). **Charts**: ECharts via `ui.echart` (NIET AG Grid).
- **Python**: 3.12+

## Commands

```bash
# Start (end-user)
open -a Boekhouding

# Start (development, direct stdout/stderr in terminal)
source .venv/bin/activate
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
python main.py

# Rebuild Boekhouding.app na launcher-wijziging
bash build-app.sh

# Tests
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib .venv/bin/python -m pytest tests/ -v
```

## Architecture boundaries

- **Native pywebview** (`native=True`); browser-mode is verlaten.
- **Geen top-level side-effects in `main.py`** — pywebview-child importeert `main.py` opnieuw; `sys.exit()`-guard op port-in-use doodt die child. Plaats startup-checks in `if __name__ == '__main__':` blok.
- **Layered architecture (Sprint A+)**: `domain/` (UI-vrij + DB-vrij, stdlib only) → `services/` (business operations, géén `from nicegui ...` import; getest in `tests/test_agenda_service.py`) → `database.py` (SQL + aiosqlite, UI-vrij) → `pages/` + `components/` (NiceGUI-coupled). Oude code blijft als-is.
- Shared layout via `components/layout.py`. Elke pagina is `@ui.page('/route')` in eigen bestand.
- `format_euro(value, decimals=2)` / `format_datum` ALLEEN uit `components/utils.py`.
- **Connection pattern**: `async with get_db_ctx(db_path) as conn:` — zet row_factory + foreign keys ON automatisch.

## Top gotchas (de tegels die als eerste vallen)

- **Geen f-strings in SQL** — altijd `?` placeholders.
- **Year-lock**: alle mutaties op facturen/werkdagen/uitgaven/banktransacties/fiscale_params van een definitief jaar weigeren met `YearLockedError`. Guards: `assert_year_writable`, `_assert_werkdagen_writable`. Zie `docs/architecture/year-lock.md`.
- **`ZICHTBARE_ZAKELIJKE_UITGAVE_FILTER`** (in `database.py`) is single source of truth voor "uitgave die zichtbaar als kosten telt". Vereist `u`/`b`-aliassen + LEFT JOIN. Toegepast in 9 queries — zie `docs/architecture/database.md`. Mismatch = stille kosten-discrepantie tussen dashboard / /kosten / /aangifte.
- **`FACTUREERBARE_WERKDAG_FILTER`** voor "open + tarief>0 + datum<=vandaag". Werkdagen-tabel heeft GEEN `jaar` kolom — gebruik altijd datum-range.
- **NiceGUI uploads**: ALTIJD `await e.file.read()` en `e.file.name`. NOOIT `e.content.read()` of `e.name`.
- **NiceGUI `linear_progress`**: ALTIJD `show_value=False` — default rendert raw float als overlay.
- **NiceGUI dialog idiom**: gebruik `Dialog.__await__` + `submit(value)` — NIET `asyncio.Future` met `dlg.on('hide', ...)`.
- **Add/edit formulieren**: via `ui.dialog()` popup, NIET inline. Tabel-selectie ALTIJD `selection='multiple'`.
- **`q-btn-dropdown` + `$parent.$emit` werkt NIET** (q-menu wordt naar `<body>` geteleporteerd). Fix: gebruik inline `q-select` met `@update:model-value`.
- **Click-bubbling in nested clickable elements**: als een clickable element binnen een ander clickable element zit (bv. pill-in-cell op `/agenda`), MOET de inner `pill.on('click', ..., js_handler='(e) => { e.stopPropagation(); emit(); }')` doen — anders fired óók de outer click-handler. Right-click context-menu kan via NiceGUI native `ui.context_menu()` (niet raw `@contextmenu`-event).
- **Cascade-discipline**: Quasar `.q-*` overrides + app-classes-die-op-Quasar-elementen-worden-toegepast ALTIJD buiten `@layer components`. Layered styles verliezen van Quasar's unlayered defaults. `tests/test_visual_css.py` enforced. Zie `docs/architecture/visual-css.md`.
- **Brand-coupling**: `--accent` (CSS) en `ui.colors(primary=...)` zijn handmatig gekoppeld op zelfde teal `#0F766E`. Wijzig je één, wijzig de ander. `accent` (Quasar) = amber, NIET teal.
- **Atomic check-and-insert**: voor idempotente DB-mutaties die race-protected moeten zijn, wrap SELECT+INSERT in `BEGIN IMMEDIATE` binnen één `get_db_ctx`. NIET twee aparte connecties — racet onder `asyncio.gather`. Voorbeelden: `services/agenda.confirm_expected`, `database.process_voorlopige_aanslag_upload`.
- **Blocking I/O**: wrap WeasyPrint, PDF extraction, file copies in `asyncio.to_thread()`.
- **Backup**: `VACUUM INTO` (atomair), NOOIT live-file copy van `.sqlite3`. SQLite NIET op cloud-sync (WAL+SynologyDrive/iCloud = silent corruption).
- **Fiscale params**: alle jaar-afhankelijke waarden uit DB. Ontbrekende keys → loud `ValueError`. Geen hardcoded fallbacks (uitzondering: `_get_km_tarief_for_year` voor /agenda planning-context).
- **PDF-pad resolutie**: row-menu actions gaan ALLEMAAL via `_ensure_factuur_pdf(row)` (resolve → fallback regenerate). Zie `docs/architecture/invoices.md`.
- **`delete_aangifte_document_with_va_cleanup` is single-tx atomic** — NIET delegate naar `delete_aangifte_document`. Failure-window tussen 2 commits zou fp stale laten.

## Domeinkennis (fiscaal) — basisregels

- **BTW-vrijgesteld** (art. 11 Wet OB) → kosten INCL BTW, geen BTW-aangifte.
- **Urencriterium**: 1.225 uur/jaar. Achterwacht (urennorm=0) telt NIET mee.
- **SPH** (pensioen): WEL bedrijfskost. **AOV**: GEEN bedrijfskost → Box 1 inkomensvoorziening.
- **Afschrijvingen**: lineair, restwaarde 10%, eerste jaar pro-rata per maand.
- **Representatie**: 80%-regeling, 20% bijtelling op fiscale winst.
- **Factuur**: vereist naam+adres+KvK, factuurnummer YYYY-NNN, vervaldatum 14d, BTW-vrijstellingstekst. **Datum = issue date**, niet werkdag-datum.
- **ANW**: km tracked, `km_tarief=0` (travel inbegrepen).
- **Belastingdienst IBAN**: NL86INGB0002445588.

Engine-details (KIA-bracket, ZVW-grondslag, PVV, klant-aliases, atomic PDF write): zie `docs/architecture/fiscal-engine.md`.

## Architecture deep-dive

| Touchpoint | Lees |
|---|---|
| DB-werk, schema, filter-constants, archive paths | `docs/architecture/database.md` |
| Mutaties op fiscale data | `docs/architecture/year-lock.md` |
| `/agenda`, recurring patterns, blockers, holidays | `docs/architecture/agenda.md` |
| `/transacties`, `/kosten`, sign convention, bulk ops | `docs/architecture/transacties-kosten.md` |
| Facturen, save invariants, mail flows, PDF | `docs/architecture/invoices.md` |
| CSS, tokens, Quasar cascade | `docs/architecture/visual-css.md` |
| `/va-tracker`, BD-PDF parser, atomic upload | `docs/architecture/va-tracker.md` |
| Fiscal engine, KIA, klant-aliases | `docs/architecture/fiscal-engine.md` |
| Codex 4-layer review, sprint-A→F bug-vangsten | `docs/architecture/codex-collab.md` |

## YAGNI

Geen: user auth, BTW-administratie, loon/voorraad, real-time bank-API, auto-matching, CI/CD, multi-language.

## Session-continuity — voor nieuwe sessies

1. Lees deze CLAUDE.md (compleet) — projectinstructies + top-gotchas + pointers.
2. Sprint-state komt uit `git log --oneline | head -30` (sprint-prefixes: `sprint-j`, `sprint-i`, etc.).
3. Memory `~/.claude/projects/.../memory/MEMORY.md` heeft cross-session context per topic.
4. Recente design decisions: `docs/superpowers/specs/` + `docs/superpowers/plans/` (met SHIPPED-banners).
5. Voor diepere page/feature-context: `docs/architecture/*.md` (laden on-demand bij relevant werk).

**Geen Sprint X state-recaps in dit bestand.** CLAUDE.md beschrijft current operating constraints, niet chronologie. Sprint-historie leeft in commits + plans + memory.
