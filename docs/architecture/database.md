# Database architecture

15 tabellen via SQLite + aiosqlite. Raw SQL met `?` placeholders, GEEN ORM.

## Tabellen

`klanten` (mig 37 + color), `klant_locaties`, `klant_aliases` (mig 33), `werkdagen`, `facturen`, `uitgaven`, `banktransacties`, `fiscale_params`, `bedrijfsgegevens` (mig 38 + 39), `aangifte_documenten`, `afschrijving_overrides`, `jaarafsluiting_snapshots`, `klant_recurring_patterns` (mig 35), `blockers` (mig 36), `voorlopige_aanslagen` (mig 41).

## Universele regels

- Raw SQL, `?` placeholders — GEEN f-strings in SQL
- Bedragen REAL, datums TEXT (YYYY-MM-DD)
- `aiosqlite` async, WAL mode, foreign keys ON
- **Connection pattern**: `async with get_db_ctx(db_path) as conn:` is de enige standaard. Raw `aiosqlite.connect` alleen in `init_db`, tests, en bestaande legacy-paden. `get_db_ctx` zet row_factory en `PRAGMA foreign_keys = ON` automatisch.
- SQLite op lokaal filesystem (`~/Library/Application Support/Boekhouding/data/`), NIET op cloud-sync (WAL+Synology/iCloud = silent corruption). Override via `BOEKHOUDING_DB_DIR` env voor tests.
- **Backup**: `VACUUM INTO` (atomair), NOOIT live-file copy van `.sqlite3`

## Status & types (cross-cutting)

- `werkdagen.status`: derived at query time from `factuurnummer` + `facturen.status` (geen kolom)
- `facturen.status` TEXT: `'concept'`, `'verstuurd'`, `'betaald'`. Verlopen = computed (`verstuurd` + past due)
- `facturen.type` TEXT: `'factuur'` (werkdag-backed), `'anw'` (imported ANW), `'vergoeding'` (ad-hoc)
- `werkdagen.factuurnummer = ''` = ongefactureerd. Oude werkdagen kunnen extern gefactureerd zijn.
- Werkdagen-tabel heeft GEEN `jaar` kolom — gebruik altijd datum-range, niet `WHERE jaar = ?`.

## Cross-cutting filter constants (single source of truth)

- `database.ZICHTBARE_ZAKELIJKE_UITGAVE_FILTER` (regel 413): `(u.bank_tx_id IS NULL OR (COALESCE(b.genegeerd, 0) = 0 AND b.bedrag < 0))`. Vereist `u`-alias voor uitgaven en `b`-alias voor banktransacties (`LEFT JOIN banktransacties b ON b.id = u.bank_tx_id`). Toegepast (via f-string) in: `get_uitgaven_per_categorie`, `get_representatie_totaal`, `get_investeringen`, `get_investeringen_voor_afschrijving`, `get_kpis`, `get_kpis_tot_datum`, `get_data_counts.n_uitgaven`, `get_kosten_breakdown`, `get_kosten_per_maand`. Cash uitgaven (`bank_tx_id IS NULL`) blijven meetellen. **Drift-warning**: enkele oudere queries (rond `database.py:2420`, `2447`, `4450`, `4775`) hebben nog inline-copies van het fragment. Bij wijziging van de filter-semantiek moeten die óók aangepast worden — of, beter, nu omgezet naar de constant. Apart als follow-up plan, niet stiekem in een onverwante diff.
- `database.FACTUREERBARE_WERKDAG_FILTER` (en `_W_PREFIX` voor JOIN-queries): `"open + tarief>0 + datum<=vandaag"` fragment. Toegepast in `get_werkdagen_ongefactureerd`, `get_werkdagen_ongefactureerd_summary`, `get_nog_te_factureren`. Caller passeert `_today_iso()` als laatste param.
- `_today_iso()` thin wrapper rond `_date.today().isoformat()` — `date.today()` is immutable builtin, niet patchbaar; tests gebruiken `monkeypatch.setattr(database, '_today_iso', ...)`.

## Atomic check-and-insert pattern

Voor idempotente DB-mutaties die race-protected moeten zijn (Sprint A `confirm_expected`, Sprint J `process_voorlopige_aanslag_upload`): wrap SELECT-existing + INSERT/UPDATE in `BEGIN IMMEDIATE` write-lock binnen ÉÉN `get_db_ctx` connectie. **NIET** SELECT in één connectie + INSERT in andere — racet onder `asyncio.gather`. Test altijd met `asyncio.gather(*[fn() for _ in range(5)])` om idempotency-claim te valideren.

## Schema-relevante invarianten

- `uitgaven.bank_tx_id` INTEGER nullable FK → `banktransacties(id) ON DELETE SET NULL` (mig 26). 0-of-1-op-1 koppeling. `NULL` = cash. Cascade-bij-delete uitgesloten.
- Mig 28: `UNIQUE INDEX idx_uitgaven_bank_tx_unique ON uitgaven(bank_tx_id) WHERE bank_tx_id IS NOT NULL` — partial; NULL cash uitgaven onbeperkt.
- `banktransacties.genegeerd` INTEGER NOT NULL DEFAULT 0 — `1` = niet-zakelijk. Toggle alleen via `mark_banktx_genegeerd()` (year-locked). Weigert `genegeerd=1` op factuur-gekoppelde rijen.
- `klant_aliases` (mig 33): FK CASCADE. Schema `(klant_id, type, pattern)` waarbij `type` IN `('suffix', 'pdf_text', 'anw_filename')`, `pattern COLLATE NOCASE` met `CHECK length(trim) >= 3`, `UNIQUE(type, pattern)`. Mig 34 seedt eenmalig vanuit `klant_mapping_local.py` of JSON-fallback.
- `klant_recurring_patterns` (mig 35): FK CASCADE. Soft-delete via `actief=0`. **NIET year-locked** — projectie-data, geen fiscale feiten.
- `blockers` (mig 36): `UNIQUE(datum)`. `kind='holiday'` geweigerd — holidays computed via `services.holidays.dutch_holidays(year)`. `add_blocker` year-locked.
- `voorlopige_aanslagen` (mig 41): FK CASCADE naar `aangifte_documenten`. UNIQUE(aanslagnummer) + UNIQUE(document_id) + partial unique `WHERE is_active=1`. Audit-trail per beschikkings-revisie via `is_active=0`. Zie `docs/architecture/va-tracker.md`.

## PDF archivering (best-effort, niet-blokkerend)

Factuur-PDFs worden gekopieerd naar SynologyDrive financieel archief (`Inkomen en Uitgaven/{jaar}/Inkomsten/{Dagpraktijk|ANW_Diensten}/` voor `factuur`/`anw`; `Inkomsten/` flat voor `vergoeding`). Drie trigger-paden via `archive_factuur_pdf`:
1. Builder-finalize (`components/invoice_builder.py:genereer_factuur`)
2. PDF-regeneratie via `_ensure_factuur_pdf` self-healing
3. Factuur-upload-import in `pages/facturen.py:handle_import_loop`

Imports gebruiken `archive_filename` arg om originele upload-naam te bewaren. Pad-traversal en NUL-byte injection afgevangen via `_safe_archive_basename`. Collisions met andere content krijgen `_2.pdf`, `_3.pdf` suffix; identieke content (idempotent re-import) skipt copy.

`archive_paths.jaar_dir(jaar)` → `ARCHIVE_BASE/'Inkomen en Uitgaven'/{jaar}/`. Single source of truth voor invoice-archivering EN uitgaven-scan.

**Dynamic ARCHIVE_BASE reference** (monkeypatch-friendly): consumer modules gebruiken `from components import archive_paths` + `archive_paths.ARCHIVE_BASE` (attribute lookup at call time), NIET `from components.archive_paths import ARCHIVE_BASE`. Tests monkeypatchen het attribuut.

## Public-safety

Alle echte klant- en persoonsgegevens leven in SQLite-DB onder `~/Library/Application Support/Boekhouding/data/` (gitignored sinds dag 1). Geen `_local.py`-files in repo. JSON-snapshot van `klant_aliases` ligt op `~/Library/Application Support/Boekhouding/config/klant_aliases_backup.json` als migratie-fallback. Repo is publiek; een eerdere `verify_public_safe.py` script lag als one-shot in commit-history (niet meer in de tree).
