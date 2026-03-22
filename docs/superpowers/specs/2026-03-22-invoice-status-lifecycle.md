# Invoice Status Lifecycle — Concept → Verstuurd → Betaald

**Date**: 2026-03-22
**Status**: Approved

## Problem

Invoices currently have only two states: betaald (paid) or not. There's no draft/concept state — invoices go straight to "official" on creation. There's no send mechanism (email/print), and no way to easily edit a just-created invoice.

## Design

### Status Model

Three stored states + one computed:

| Status | Stored | Badge | Color | Meaning |
|--------|--------|-------|-------|---------|
| Concept | `'concept'` | Concept | `secondary` (grey) | Draft, freely editable |
| Verstuurd | `'verstuurd'` | Verstuurd | `info` (blue) | Sent to client |
| Verlopen | computed | Verlopen | `negative` (red) | Verstuurd + past due |
| Betaald | `'betaald'` | Betaald | `positive` (green) | Paid |

### Status Transitions

```
                          ┌─── Verstuur via e-mail
Concept ──────────────────┼─── Print
                          └─── Markeer als verstuurd
                                    │
                                    ▼
                              Verstuurd ───── Markeer betaald ────▶ Betaald
                                    │                                  │
                                    ▼                                  │
                              Verlopen (auto)    Markeer onbetaald ◄──┘
```

### Database Changes

**Migration (add `status` column):**
```sql
ALTER TABLE facturen ADD COLUMN status TEXT DEFAULT 'concept';
UPDATE facturen SET status = CASE WHEN betaald = 1 THEN 'betaald' ELSE 'verstuurd' END;
```

The existing `betaald` column stays in the schema (non-destructive) but all code reads/writes `status` instead. `betaald_datum` remains as-is (tracks when payment was received).

**Add email to klanten:**
```sql
ALTER TABLE klanten ADD COLUMN email TEXT DEFAULT '';
```

### Factuur Dataclass Update

```python
@dataclass
class Factuur:
    ...
    status: str = 'concept'  # 'concept', 'verstuurd', 'betaald'
    betaald_datum: str = ''
    # betaald: bool — REMOVED (replaced by status)
```

### New/Modified DB Functions

**`update_factuur_status(db_path, factuur_id, status, betaald_datum='')`** — replaces `mark_betaald()`:
- Sets `facturen.status` and optionally `betaald_datum`
- Cascades to werkdagen: concept→verstuurd keeps 'gefactureerd', verstuurd→betaald sets 'betaald', betaald→verstuurd reverts to 'gefactureerd'

**`get_openstaande_facturen()`** — filter changes from `betaald = 0` to `status = 'verstuurd'` (excludes concept)

**`add_factuur()`** — accepts `status='concept'` instead of `betaald=0`

### Per-Status Actions (three-dot menu)

**Concept:**
- Bewerken (reopens invoice builder)
- Verstuur via e-mail → verstuurd
- Print → verstuurd
- Markeer als verstuurd → verstuurd
- Verwijderen

**Verstuurd / Verlopen:**
- Download PDF
- Verstuur opnieuw (email)
- Markeer betaald → betaald
- Bewerken (edit dialog)
- Verwijderen

**Betaald:**
- Download PDF
- Markeer onbetaald → verstuurd

### Email Sending (macOS)

AppleScript opens Mail.app with pre-composed email + PDF attached:

```
Subject: Factuur {nummer}

Body:
Bijgaand stuur ik u factuur {nummer}.

Het totaalbedrag van {bedrag} verzoek ik u binnen 14 dagen over te maken
op rekeningnummer {iban} t.n.v. {bedrijfsnaam}, onder vermelding van
factuurnummer {nummer}.

Mocht u vragen hebben, dan hoor ik het graag.

Met vriendelijke groet,

{naam}

{bedrijfsnaam}
Tel: {tel}
{email}
```

Attachment: the PDF file. If klant has email stored, To field is pre-filled.

### Financial Reports Impact

- **Dashboard omzet/openstaand**: only `verstuurd` + `betaald` (concept excluded)
- **Jaarafsluiting**: only `verstuurd` + `betaald`
- **Verlopen calculation**: only applies to `verstuurd` invoices

### New Invoice Flow

1. User clicks "Nieuwe factuur" → invoice builder opens
2. User fills in data, sees live preview
3. Clicks "Genereer factuur" → PDF created, saved with `status='concept'`
4. Back on facturen page, invoice shows grey "Concept" badge
5. User clicks ⋮ → "Verstuur via e-mail" → Mail.app opens → user sends → status becomes 'verstuurd'

## Files to Modify

| File | Changes |
|------|---------|
| `database.py` | Migration, `update_factuur_status()`, update `add_factuur`, `get_facturen`, `get_openstaande_facturen`, all `WHERE betaald` SQL |
| `models.py` | Replace `betaald: bool` with `status: str` |
| `pages/facturen.py` | Status badges, filters, menu actions, email send, KPIs |
| `pages/bank.py` | Update raw SQL `WHERE betaald = 0` |
| `pages/jaarafsluiting.py` | Update raw SQL integrity check |
| `components/invoice_builder.py` | Set `status='concept'` on creation |
| `tests/test_facturen.py` | Update all `betaald=` kwargs and assertions |
| `tests/test_db_queries.py` | Same |
| `tests/test_aangifte.py` | Same |
