# Agenda-pagina (`/agenda`)

Calendar-driven planning + factuur-status visualisatie naast bestaande tabel-driven `/werkdagen`. Sprint A.

## Service-layer

`services.agenda` (UI-vrij, ~926 LoC). **Géén `from nicegui ...` import** — boundary-test in `tests/test_agenda_service.py:test_services_agenda_no_nicegui_import` enforced.

**Read-API**:
- `get_maand(jaar, maand) → MaandView`
- `get_dag(datum) → DagView`
- `get_zes_weken_prognose(vanaf) → tuple[WeekTotaal, ...]`
- `get_urencriterium_projectie(jaar) → UrencriteriumState`
- `list_blockers(vanaf, tot) → tuple[Blocker, ...]` (merged user-blockers + computed holidays)
- `list_patterns_for_klant(klant_id) → tuple[Pattern, ...]`

**Mutate-API**:
- `confirm_expected(pattern_id, datum, ...) → werkdag.id` (atomic via BEGIN IMMEDIATE)
- `add_blocker/delete_blocker` (year-locked op datum)
- `add_pattern/update_pattern/delete_pattern` (NIET year-locked — patterns zijn projectie-data)

## Pure helpers

- `categorize_werkdag(code) → 'dagpraktijk'|'anw'|'overig'` (type-based coloring)
- `derive_werkdag_status_label(werkdag, today) → 'ongefactureerd'|'concept'|'verstuurd'|'verlopen'|'betaald'` (verlopen = pure function op `factuur_vervaldatum < today`, geen DB-update nodig)
- `compute_overdue_days(werkdag, today)` (alleen voor `verstuurd`-status)
- `parse_weekdays(csv) → list[int]` (1-7, no dups, whitespace-tolerant)

## DB layer

**`get_werkdagen_met_factuur_status(jaar, maand)`** in `database.py`: LEFT JOIN `werkdagen` × `facturen` via `factuurnummer`. Returns `WerkdagMetStatus` frozen dataclass: `id, datum, klant_id, klant_naam, code, activiteit, uren, km, tarief, km_tarief, factuurnummer, factuur_id, factuur_datum, factuur_status, factuur_betaald_datum, factuur_vervaldatum (computed +14d in __post_init__)`.

Orphan factuurnummer (factuur_status='' maar factuurnummer != '') wordt door `derive_werkdag_status_label` als `ongefactureerd` behandeld — UI mag apart `factuurnummer != '' AND factuur_status == ''` checken voor warning-indicator.

## Bron-van-waarheid

- Bevestigde werkdagen = DB-rij in `werkdagen`
- Verwachte entries = computed at-query-time uit patterns minus werkdagen minus blockers minus holidays, **alleen voor `datum > today`**
- Holiday-blocker (`kind='holiday'`) wint over user-blocker bij display-conflict
- Holiday-blocker onderdrukt verwachte entries (user kan handmatig werkdag toevoegen via "Werkdag plannen" override)

## `confirm_expected` invariants

- **Atomic**: `BEGIN IMMEDIATE` write-lock wrap rond SELECT-existing + INSERT (race-protectie tegen `asyncio.gather(5×)`). Test `tests/test_agenda_service.py:test_confirm_expected_atomic_under_parallel_calls` bewijst single werkdag.
- **Idempotent**: bestaande werkdag op `(klant_id, datum)` — ongeacht of door dit pattern gemaakt — return existing.id. Documented contract.
- **Race-protected**: pattern_id moet bestaan + `actief=1`, anders `ConflictError("Patroon X is verwijderd of inactief — refresh agenda")`.
- **Blocker-check**: weigert als blocker op datum bestaat (defense-in-depth).
- **Klant-data uit klant** op moment van bevestigen (tarief, retour_km, adres) — NIET uit pattern. Pattern is rooster-template, geen tarief-snapshot.
- **km_tarief**: uit `fiscale_params.km_tarief` per jaar via `_get_km_tarief_for_year` helper. Fallback `0.23` ALLEEN als geen fiscale_params row bestaat — bewuste planning-context-uitzondering: /agenda is planning-tool, niet aangifte-engine.
- **urennorm**: 0 voor `ACHTERWACHT` of `ZERO_UREN_CODES (CONGRES/OPLEIDING/OVERIG_ZAK)`, anders 1.

## Type-based coloring

Dagpraktijk = teal (#0F766E), anw = paars (#7E22CE), overig = grijs. CSS classes `.wd-dagpraktijk/.wd-anw/.wd-overig` in `components/layout.py`. Verwachte entries (recurring) krijgen `.wd-pill.expected` (dashed border + soft fill).

**Klant-color feature** (Sprint D, mig 37+38): optionele kleur per klant via 8-paletje + "Geen kleur" dropdown. Toggle in Bedrijfsgegevens (`gebruik_klant_kleur_in_agenda`). Render in `/agenda` als `.wd-pill` background + WCAG `contrast_text_color()`. Defensieve guards (`pages/agenda.py:_pill_color_style`) — alleen op werkdag/expected pills, niet op blockers/holidays. Bestaande hex buiten `KLANT_KLEUR_OPTIES` krijgt ad-hoc "Aangepast (#hex)" optie zodat re-save NIET wist.

## Factuur-status-bars per cel

`.wd-status-bar` met `.status-{label}` per werkdag onderaan de cel. Kleur-mapping: ongefactureerd grijs (#94A3B8), concept grijs-dimmed, verstuurd blauw (#2563EB), verlopen rood (#DC2626), betaald groen (#16A34A). UI auto-update bij elke /agenda-render via verse DB-query — geen pubsub.

## View-switcher pattern

Tussen `/werkdagen` en `/agenda` cross-link buttons in beide page-toolbars (`Kalenderweergave` ↔ `Lijstweergave`). Geen tab-merge — `/agenda` heeft eigen concepten (recurring patterns, blockers, holidays, urencriterium-projectie) die niet "lijst-filters op werkdagen" zijn.

## Pill-interactiviteit (Sprint 1)

Confirmed werkdag-pills in `_render_month_grid` zijn klikbaar + right-click context-menu. Expected (recurring) pills zijn dat NIET — die bubblen door naar cell-click → Day-Inspector flow.

**Pure helpers** in `pages/agenda.py`:
- `_pill_context_actions(pill) → list[str]` — visibility-matrix, retourneert action-IDs `['edit', 'duplicate', 'delete'|'naar_facturen'|'ontkoppel']`. Renderer mapt naar labels.
- `_pill_tooltip(pill) → str` — 3-regel formatter. **Gebruik `ui.tooltip(text).style('white-space: pre-line')`** — Quasar QTooltip default `white-space: normal` collapseert `\n` naar één regel.

**DB-helpers** (`database.py`, year-locked):
- `get_werkdag_by_id(db, werkdag_id)` — single-row variant van `get_werkdagen` voor edit/duplicate-flows die volle `Werkdag`-shape vereisen (niet de lichte `WerkdagPill`).
- `duplicate_werkdag(db, werkdag_id, target_datum)` — kopieert klant/code/uren/locatie/etc., wist `factuurnummer`. **`is None`-checks** ipv `or default` voor `km_tarief` en `urennorm` — ANW heeft `km_tarief=0`, achterwacht `urennorm=0`; truthy-falsy-check zou die platslaan.
- `unlink_werkdag_from_factuur(db, werkdag_id)` — atomair (`BEGIN IMMEDIATE`), alleen toegestaan voor concept-factuur of orphan-link (`factuur_id IS NULL`). Boekhoudkundig: NIET voor verstuurd/betaald.

**Click-bubbling fix** (regel 305 area): pill zit binnen clickable cell. Click handler MOET `js_handler='(e) => { e.stopPropagation(); emit(); }'` — anders fired ook cell-click → day-select rerender bovenop edit-dialog.

**handle_pill_ontkoppel race-protection**: pre-dialog refetch is alleen voor UI-text (orphan vs concept). Atomic `unlink_werkdag_from_factuur` is de echte gate — als status tussen render en klik wijzigt naar verstuurd, weigert de helper alsnog.
