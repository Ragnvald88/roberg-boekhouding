# Herinnering voor verlopen facturen

## Summary

Add a "Herinnering versturen" action to the facturen page for overdue (verlopen) invoices. Opens Mail.app with a pre-filled friendly reminder email and the original invoice PDF attached. Tracks when a herinnering was sent per invoice.

## Context

- Verlopen = computed status: `facturen.status == 'verstuurd'` AND `datum + 14 days < today`
- Current email flow: AppleScript opens Mail.app with plain text body + PDF attachment
- No reminder functionality exists yet

## Design

### 1. Database: new column

Add `herinnering_datum TEXT DEFAULT ''` to `facturen` table via the next migration in `database.py`.

Stores the ISO date (YYYY-MM-DD) of the last herinnering sent. Empty string means no herinnering sent.

### 2. Email body: `_build_herinnering_body()`

New function in `pages/facturen.py`, adjacent to existing `_build_mail_body()`. Plain text, friendly tone:

```
Beste {klant_naam},

Wellicht is het aan uw aandacht ontsnapt, maar ik heb nog geen betaling ontvangen voor factuur {nummer} van {datum} ter hoogte van {bedrag}.

Ik verzoek u vriendelijk het bedrag binnen 7 dagen over te maken op rekeningnummer {iban} t.n.v. {bedrijfsnaam}, onder vermelding van factuurnummer {nummer}.

U kunt ook eenvoudig betalen via deze link:
{betaallink}

Mocht de betaling reeds onderweg zijn, dan kunt u dit bericht als niet verzonden beschouwen. Heeft u vragen, neem dan gerust contact op.

Met vriendelijke groet,

{naam}

{bedrijfsnaam}
Tel: {telefoon}
{email}
```

- Betaallink paragraph only included when betaallink is non-empty (same pattern as `_build_mail_body()`)
- Subject line: `Herinnering: Factuur {nummer}`
- `{bedrag}` formatted with `format_euro()`
- `{datum}` formatted with `format_datum()`

### 3. AppleScript: `on_send_herinnering()`

New handler in `pages/facturen.py`, mirrors the existing `on_send_mail()` flow:

1. Load factuur + klant data from DB
2. Check PDF exists (if not, show error notification — don't auto-generate for reminders)
3. Build herinnering body via `_build_herinnering_body()`
4. Execute AppleScript to open Mail.app with:
   - Subject: `Herinnering: Factuur {nummer}`
   - To: `klant.email` (if available)
   - Body: herinnering text
   - Attachment: original invoice PDF
5. On success: update `herinnering_datum` to today's date in DB
6. Refresh table to reflect the change

Same patterns as existing `on_send_mail()`:
- `asyncio.to_thread()` for AppleScript execution
- 15-second timeout
- Error handling with `ui.notify()`
- Does NOT change the invoice status (stays verstuurd/verlopen)

### 4. UI: actions dropdown menu item

In the per-row actions dropdown (lines 294-394 of `pages/facturen.py`):

- Add **"Herinnering versturen"** menu item with `notification` icon
- Visible only when `props.row.verlopen == true`
- Position: after "Verstuur via e-mail", before "Markeer als verstuurd"
- Emits a `'sendherinnering'` event with the row's factuur id

### 5. UI: herinnering indicator on verlopen badge

When a verlopen invoice has a non-empty `herinnering_datum`:

- Add a tooltip to the verlopen status badge showing "Herinnering verstuurd op {datum}"
- Optionally show a small `mark_email_read` icon next to the badge

### 6. Table row data

In `refresh_table()`, add `herinnering_datum` to the row dict so it's available for the badge tooltip and the actions menu logic.

## Scope exclusions

- No automatic/scheduled sending
- No 2e/3e herinnering escalation
- No separate herinnering PDF template
- No new page or dialog
- No changes to status lifecycle (herinnering does not change status)

## Files modified

| File | Change |
|------|--------|
| `database.py` | Migration: add `herinnering_datum` column |
| `pages/facturen.py` | `_build_herinnering_body()`, `on_send_herinnering()`, actions menu item, badge tooltip, row data |

## Testing

- Unit test for `_build_herinnering_body()` output (correct placeholders, betaallink conditional)
- Test that herinnering action only appears for verlopen invoices
- Test that `herinnering_datum` is stored after sending
- Test migration adds column with default empty string
