# Transacties + Kosten pages

`/transacties` is single inbox voor alle money-movement. `/kosten` is read-only overzicht. `/bank` bestaat NIET MEER (Sprint B T9 schrap).

## `/transacties` — single inbox

Source: `get_transacties_view(db, jaar, maand, status, categorie, type, search, include_genegeerd)` in `database.py`. Bank debits + bank positives + manual cash uitgaven.

### Row status (`derive_status` in `components/transacties_helpers.py`)

`prive_verborgen` (genegeerd=1) → `gekoppeld_factuur` (positive matched to factuur) → `ongecategoriseerd` → `ontbreekt_bon` (debit cat'd w/o PDF) → `compleet` (debit: cat+bon) → `gecategoriseerd` (positive: cat).

### Categorie write (sign-aware)

- **Bank rows** (`id_bank`-branch): `set_banktx_categorie` (sign-aware):
  - `bedrag>=0` writes naar `banktransacties.categorie` direct
  - `bedrag<0` met bestaande linked uitgave update die uitgave-categorie (incl. clear via `''`)
  - `bedrag<0` zonder linked uitgave + `categorie=''` → **NO-OP** (B6 root-fix; voorheen creëerde dit phantom lege uitgaven via lazy-create)
  - `bedrag<0` zonder linked uitgave + niet-leeg cat → single call naar `ensure_uitgave_for_banktx(categorie=...)`
- **Manual rows** (cash uitgaven): direct `update_uitgave`

### Per-row category options

Debits+cash krijgen `KOSTEN_CATEGORIEEN`; positives krijgen `['Omzet', 'Prive', 'Belasting', 'AOV']`. Injected server-side as `props.row.cat_options`.

### Detail dialog

Lives in `components/transacties_dialog.py`. Bootstrap uses `get_uitgave_by_id` (M5 fix — no list-and-filter silent-None race).

**Debit-only**: dialog refuses to open on credit rows (bedrag ≥ 0). Lazy-create would otherwise write an ABS-bedrag uitgave linked to a positive bank-tx and silently inflate /kosten breakdown totals. Template hides `…` and `Bon toevoegen` buttons for credits.

### Sign convention in `TransactieRow.bedrag`

Signed. Bank debits keep stored negative; bank credits keep stored positive; manual cash uitgaven normalised to negative via `-ABS(u.bedrag)` in SQL. UI colours by sign (teal ≥ 0, red < 0). KPI callers needing positive-totals (`get_kpi_kosten`) gebruiken `abs(r.bedrag)` + filter `r.bedrag < 0`.

### Bulk operations + selection snapshot

*Bulk-Categorie* respecteert sign van selectie: all-debit → kosten-cats, all-credit → `['', 'Omzet', 'Prive', 'Belasting', 'AOV']`, mixed → alleen blanken (met waarschuwing).

*Bulk-Verwijderen* pre-scant selectie, vraagt expliciet bevestiging bij factuur-revert cascades en uitgave-orphans. **Selection-snapshot pattern**: `selected = list(table.selected or [])` aan begin van handler, doorgegeven aan inner delete-loop om scope-widening te voorkomen als user selectie na dialoog-open wijzigt. Zelfde snapshot-pattern in `bulk_negeren` hier én `on_bulk_delete`/`on_bulk_betaald` in `pages/facturen.py`.

*Markeer als privé* slaat factuur-gekoppelde rijen UI-zijdig over (snel pad) en vangt `ValueError` van DB-guard af.

### Cash entries + Archief-import

- Cash via `+ Contante uitgave`: `add_uitgave(bank_tx_id=None)`
- Archief-PDFs via `scan_archive()` + `open_add_uitgave_dialog` met prefill. Auto-link routes through `ensure_uitgave_for_banktx` (M1).

### Factuur-match preview

`find_factuur_matches` retourneert `MatchProposal` met `confidence='high'|'low'`. Preview-dialoog gating: user bevestigt matches vóór toepassing. `apply_factuur_matches` gaat via `update_factuur_status`. Triggert na CSV-import én via "Matches controleren (N)" header-knop.

### Query-params

`?jaar/maand/status/categorie/type/search` pre-populate filters. Click-through van `/kosten` gebruikt deze.

## `/kosten` — read-only overzicht

Jaar-selector + 2 tabs (Overzicht / Investeringen). Geen form controls die data muteren.

- **KPI strip**: `get_kpi_kosten`. "Te verwerken" card → `/transacties?status=ongecategoriseerd&jaar=X`. `totaal` en `monthly_totals` excluderen `is_investering=1` (afgeschreven, niet kost in aankoop-jaar).
- **Per-maand bar chart**: `get_kosten_per_maand` (12 slots). Excluderen investeringen + uitgaven gelinkt aan positieve bank-tx (P0-1 phantom-lazy-create defensie).
- **Categorie breakdown**: `get_kosten_breakdown`. Elk staafje clickable → `/transacties?jaar=X&categorie=Y` (categorie via `urllib.parse.quote_plus`-ed). `(nog te categoriseren)` bucket renders als aparte muted card boven; klik → `?status=ongecategoriseerd`.
- **Terugkerende kosten card**: `get_terugkerende_kosten` — vendors met ≥3 hits in 365d, sorted by jaar-totaal DESC.
- **Investeringen tab**: `pages/kosten_investeringen.py:laad_activastaat`.

## Category suggestions

`get_categorie_suggestions(db)` bouwt lowercase `tegenpartij → most-used categorie` map via UNION ALL: debit-uitgaven (`uitgaven.categorie JOIN banktransacties`) + positieve banktransacties (`banktransacties.categorie`). Tie-breaker: `cnt DESC, MAX(datum) DESC`. UI toont toverstaf-knop (`auto_fix_high`) naast q-select op alle ongecategoriseerde rijen.

## Dashboard health alerts

`get_health_alerts(db, jaar)` → `list[dict]` met keys `key/severity/message/count/link`. Types: `uncategorized_bank`, `overdue_invoices`, `concept_invoices`, `missing_fiscal_params`. Sign-aware uncategorized check (B2 round-3 fix): debits → `uitgaven.categorie` source-of-truth, credits → `banktransacties.categorie`. SQL gebruikt `CASE WHEN bedrag<0 THEN TRIM(COALESCE(u.categorie, '')) = '' ELSE TRIM(COALESCE(bt.categorie, '')) = '' END` — TRIM matcht `derive_status` `.strip()` semantiek.

**Geen import-exclusion op `concept_invoices` alert** (B17, BEWUST niet gefixt): `pages/facturen.py` toont "Markeer als verstuurd" voor élke concept zonder import-guard, dus alerts blijven actionable voor imports. Niet "fixen" als simplification — zou imports stilletjes uit het alert-overzicht halen terwijl ze nog steeds actie behoeven.
