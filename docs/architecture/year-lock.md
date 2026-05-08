# Year-lock invariant

Zodra `jaarafsluiting_status='definitief'` weigert elke mutatie op facturen, werkdagen, uitgaven, banktransacties en fiscale_params van dat jaar met `YearLockedError` (subclass van `ValueError`).

## Guards

- **`assert_year_writable(db_path, jaar_of_datum)`** — primaire guard. Toegepast in alle mutating helpers van bovenstaande tabellen.
- **`_assert_werkdagen_writable(db_path, werkdag_ids)`** — voor functies die een lijst werkdag-IDs muteren: fetcht DISTINCT jaren van de gegeven IDs, weigert de hele batch als één daarvan in een definitief jaar valt. Gebruikt door `link_werkdagen_to_factuur`, `save_factuur_atomic` (inline werkdag-UPDATE en step 1 OLD-link unlink), `delete_factuur` (OLD-link unlink).

## Volledige guarded mutation set (round-2 review 2026-04-27 + later)

- Facturen: `add_factuur`, `update_factuur`, `update_factuur_status`, `update_factuur_herinnering_datum`, `delete_factuur`, `save_factuur_atomic`
- Werkdagen: `add_werkdag`, `update_werkdag`, `delete_werkdag`, `link_werkdagen_to_factuur`
- Uitgaven: `add_uitgave`, `update_uitgave`, `delete_uitgave`, `set/delete_afschrijving_override`
- Banktransacties: `delete_banktransacties` (controleert óók datums van gekoppelde facturen ÉN gekoppelde uitgaven), `mark_banktx_genegeerd` (cross-year stealth-hide gedicht door óók uitgave-datum check)
- Fiscale_params: alle update-helpers
- Aangifte: `add/delete_aangifte_document`, `delete_aangifte_document_with_va_cleanup`
- Klant: `delete_klant_locatie` (via gekoppelde werkdagen-jaren)

## Cross-year guards op `bank_tx_id` (B19 round-3 fix)

- `add_uitgave(bank_tx_id=X)` checkt zowel uitgave-datum als bank-tx datum
- `update_uitgave(bank_tx_id=Y)`: bij `bank_tx_id`-WIJZIGING (`new != old`) checkt zowel oude als nieuwe banktx-jaar
- Idempotente updates (zelfde `bank_tx_id`) skippen check zodat re-saves niet falen op al-bestaande locked-link
- Missing-row blijft silent no-op (return DIRECT vóór alle year-lock checks)

## Unfreeze-escape

`update_jaarafsluiting_status(jaar, 'concept')` — als enige ongeguarded zodat "Heropenen" altijd werkt. Na heropenen → correcties → opnieuw definitief maken overschrijft het snapshot.

## Year-lock UX

Save-handlers in `/aangifte`, `/instellingen`, `/kosten_investeringen`, `/transacties`, `/facturen` vangen `YearLockedError` af → `ui.notify(type='warning')` met de Dutch error-message uit de exception. Bij definitief jaar renderen inputs als `disabled` + banner bovenaan. Geen achtergrond-tracebacks meer.

**Conditional pre-flight bij mail-flows**: `on_send_mail` doet year-lock check ALLEEN bij `row.get('status') == 'concept'` (concept→verstuurd is mutatie). Voor verstuurd/verlopen is mailen puur communicatie zonder mutatie en mag dus ook in een definitief jaar.

## Jaarafsluiting snapshot

`jaarafsluiting_snapshots` tabel maakt een echte JSON snapshot bij definitief-zetten. Render-pad leest snapshot voor definitief-jaren, live data voor concept. Snapshot is schema-tolerant (altijd `dict.get(key, default)` in render code). `/aangifte` leest via `load_jaarafsluiting_data` zodat cijfers op scherm + Jaarcijfers-PDF consistent blijven, óók na engine-fixes.

## Pre-flight checklist

`compute_checklist_issues(db_path, jaar)` in `pages/jaarafsluiting.py` geeft `list[tuple[severity, message, link]]`. Gebruikt door zowel Controles-tab als definitief-gate (soft gate, user kan doorgaan).

## Tests

Alle guards getest in `tests/test_year_locking.py`.
