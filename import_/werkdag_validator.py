"""Per-record werkdag validator — runs AFTER PDF parse, BEFORE DB insert.

Prevents the March 2026 precedent where 116 werkdagen uit 2025 geïmporteerd
werden met tarief=0 (aggregaten klopten, records waren incompleet).

Pure module: no I/O, no async, fully unit-testable.
"""

import re
from typing import Literal

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Codes die niet billable zijn — tarief=0, uren=0 zijn dan legitiem.
_NON_BILLABLE_CODES = {
    'ACHTERWACHT', 'AW',
    'ADMINISTRATIE', 'ADMIN',
    'NASCHOLING',
    'AQUISITIE',
}


class ValidationError(ValueError):
    """Raised when a werkdag record fails per-record invariants at import time."""


def validate_werkdag_record(
    rec: dict,
    inv_type: Literal['factuur', 'anw'],
) -> None:
    """Check dat rec consistent is vóór DB-insert. Raises ValidationError bij gaps.

    Args:
        rec: dict met keys datum, code, uren, tarief, km, km_tarief.
        inv_type: 'factuur' (dagpraktijk) of 'anw'.

    Invariants:
    - datum aanwezig en ISO-formaat (YYYY-MM-DD).
    - uren, tarief, km, km_tarief aanwezig en niet-negatief.
    - Voor *billable* codes (niet ACHTERWACHT/ADMIN/NASCHOLING/AQUISITIE):
      * uren > 0 EN tarief > 0.
    - Voor dagpraktijk (inv_type='factuur') met km > 0: km_tarief > 0.
    - Voor ANW (inv_type='anw'): km_tarief mag 0 zijn (reistijd zit in uurtarief).
    """
    # Required keys
    for fld in ('datum', 'uren', 'tarief', 'km', 'km_tarief'):
        if fld not in rec:
            raise ValidationError(f'veld ontbreekt: {fld}')
        val = rec[fld]
        if val is None:
            raise ValidationError(f'veld leeg: {fld}')
        if fld != 'datum' and val < 0:
            raise ValidationError(f'negatief op {fld}: {val}')

    # Datum-formaat
    if not isinstance(rec['datum'], str) or not _DATE_RE.match(rec['datum']):
        raise ValidationError(f'datum niet ISO-formaat: {rec["datum"]!r}')

    code = (rec.get('code') or '').strip().upper()
    is_billable = code not in _NON_BILLABLE_CODES

    if is_billable:
        if rec['uren'] <= 0:
            raise ValidationError(f'billable code {code!r} heeft uren=0')
        if rec['tarief'] <= 0:
            raise ValidationError(
                f'billable code {code!r} heeft tarief=0 — '
                f'PDF-parse populateert tarief niet (2025-precedent)'
            )

    # km zonder km_tarief -> silent zero reiskosten
    if inv_type == 'factuur' and rec['km'] > 0 and rec['km_tarief'] <= 0:
        raise ValidationError(
            f'km={rec["km"]} > 0 maar km_tarief=0 voor dagpraktijk'
        )
