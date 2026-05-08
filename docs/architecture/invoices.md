# Invoices (facturen)

## Status lifecycle

```
Concept (grey) → Verstuurd (blue/info) → Betaald (green/positive)
                       ↓
                  Verlopen (red/negative, computed: verstuurd + past due)
```

- New invoices start als `'concept'` — freely editable
- "Verstuur via e-mail" opens Mail.app via NSSharingService → marks verstuurd
- Revenue queries (`get_omzet_*`, `get_kpis`) excluderen concept-facturen
- `update_factuur_status()` cascades to linked werkdagen

## Edit-menu visibiliteitsregels (factuur row-menu)

- **Bewerken** zichtbaar alleen voor concept + niet-geïmporteerd (`type != 'anw'` EN `bron != 'import'`). Altijd route naar invoice builder; er is GEEN tweede legacy-dialog.
- **Markeer als concept** zichtbaar voor verstuurd/betaald + niet-geïmporteerd. Toont waarschuwingspopup. Bij betaald: twee-staps-transitie (betaald→verstuurd→concept) — `update_factuur_status` weigert directe `betaald→concept` met ValueError.
- Geïmporteerde facturen (ANW of `bron='import'`) zijn **bevroren**: nooit Bewerken, nooit Markeer-als-concept.

Helpers in `pages/facturen.py`: `_is_editable(row)` en `_can_revert_to_concept(row)` spiegelen Vue `v-if` regels en zijn unit-getest.

## Invoice builder save invariants

- **Beide save-paths serializen `regels_json`** = `{'line_items', 'klant_fields'}`. `opslaan_als_concept` én `genereer_factuur` moeten dit doen, anders verliest een latere Bewerken de vrije regels en reconstrueert vanuit werkdagen (lossy). De `_ensure_factuur_pdf` regeneratie-fallback leest deze JSON eerst.
- **`save_factuur_atomic` stap 4 conditioneel**: unlink de oude PDF ALLEEN als `old.pdf_pad != factuur_kwargs.get('pdf_pad', '')`. Regenereren met zelfde nummer schrijft naar hetzelfde bestand — onvoorwaardelijk unlink zou de net-geschreven PDF verwijderen (F-3).
- **Close-after-refresh**: in `genereer_factuur` + `opslaan_als_concept` loopt `on_save()` (refresh_table) VÓÓR `dlg.close()`. Anders ziet gebruiker stale `pdf_pad` in row-menu tijdens refresh-window, leidt tot "PDF niet gevonden" clicks.
- **`pre_datum` op concept-reopen**: `_reopen_concept_in_builder` geeft `pre_datum=row['datum']` door aan `open_invoice_builder`. Builder initialiseert `datum_input` met `pre_datum or date.today().isoformat()`. Werkdag-import flows mogen factuurdatum NIET overschrijven (F-1/F-2 regressie-risico — er zijn geen `datum_input.value = max(dates)` assignments meer; houd het zo).

## PDF-pad resolutie

Row-menu actions (Preview/Download/OpenFinder/SendMail/SendHerinnering) gebruiken ALLEMAAL `_ensure_factuur_pdf(row)` uit `pages/facturen.py`:
1. Probeert `_resolve_pdf_pad` (stored path → basename-lookup in `PDF_DIR`/imports/, self-healing DB-update op fallback-hit)
2. Bij missend bestand: `_regenerate_factuur_pdf` rendert opnieuw vanuit `regels_json` → linked werkdagen, `pdf_pad` bijwerken (YearLockedError wordt geslikt — fiscale data blijft ongewijzigd, alleen metadata pdf_pad), archiveert naar SynologyDrive

ANW-imports en `bron='import'` worden geweigerd. Pure bron-kiezer `_compute_regen_sources(row)` is apart unit-getest.

## Mail flows (factuur + herinnering)

`_build_mail_body` en `_build_herinnering_body` geven **HTML** terug met clickable `<a href="…">deze link</a>` op de betaallink. User-controlled waarden via `html.escape` gefilterd.

Versturen loopt via `components/mail_helper.py → open_mail_with_attachment(..., body_html=...)` → `components/mail_compose_helper.py` dat Mail.app's Cocoa Share-Sheet compose-API (`com.apple.share.Mail.compose`) aanroept via pyobjc.

**Niet** via AppleScript's `html content`-property — die is door Apple gedeprecateerd ("Does nothing at all") op macOS 14+ en werkt niet meer met attachments.

**UTF-8 wrapping**: `_build_mail_body` geeft een HTML-fragment terug; `mail_compose_helper._ensure_utf8_html` wikkelt dat in een `<!DOCTYPE html>` + `<meta charset=UTF-8>` shell vóórdat bytes naar `NSAttributedString` gaan, anders valt Cocoa terug op Windows-1252 en wordt `€` → `â‚¬`. Idempotent.
