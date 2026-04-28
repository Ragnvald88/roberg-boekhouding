"""Derive PDF-parser skip-words from the user's `bedrijfsgegevens` row.

Replaces the old `import_/pdf_parser_local.py` static-tuple approach.
The skip-words for header lines (own name, bedrijfsnaam, adres,
telefoon-fragments, email-localpart, postcode/plaats) are derived at
runtime from a single source of truth (the bedrijfsgegevens DB row).
"""

from __future__ import annotations
import re

GENERIC_SKIP_WORDS: tuple[str, ...] = (
    'Datum', 'FACTUUR', 'Tel', 'KvK', 'IBAN', 'Mail:', 'Bank:',
    # Tokens used by scrubbed test fixtures (tests/test_pdf_parser.py):
    'TestBV', 'huisartswaarnemer', 'Test Gebruiker', 'T. Gebruiker',
    'Teststraat 1', '1234 AB', '1234AB', 'testuser', '06 000', '0600',
    '@example.com',
)


def _normalize_phone_digits(telefoon: str) -> str | None:
    """Return canonical 10-digit national form, or None.

    '06 1234 5678'         → '0612345678'
    '+31 6 4326 7791'      → '0612345678'
    '0031 6 4326 7791'     → '0612345678'
    '0031643267791'        → '0612345678'
    """
    digits = ''.join(c for c in telefoon if c.isdigit())
    if digits.startswith('0031'):
        digits = '0' + digits[4:]
    elif digits.startswith('31') and len(digits) == 11:
        digits = '0' + digits[2:]
    if len(digits) < 6:
        return None
    return digits


def derive_skip_words(bg) -> tuple[str, ...]:
    """Return GENERIC_SKIP_WORDS + tokens derived from a bedrijfsgegevens row.

    `bg` may be None (no row in DB yet) or any object with the standard
    bedrijfsgegevens attributes (naam, bedrijfsnaam, adres, postcode_plaats,
    telefoon, email, kvk, iban). All attributes tolerant of empty/None.
    """
    if bg is None:
        return GENERIC_SKIP_WORDS
    derived: list[str] = []

    for field in (getattr(bg, 'naam', ''),
                  getattr(bg, 'bedrijfsnaam', ''),
                  getattr(bg, 'adres', ''),
                  getattr(bg, 'email', '')):
        if field:
            derived.append(field)

    email = getattr(bg, 'email', '') or ''
    if email and '@' in email:
        derived.append(email.split('@', 1)[0])

    postcode_plaats = (getattr(bg, 'postcode_plaats', '') or '').strip()
    if postcode_plaats:
        m = re.match(r'^([0-9]{4}\s?[A-Z]{2})\s+(.+)$', postcode_plaats)
        if m:
            derived.extend(m.groups())
        else:
            derived.append(postcode_plaats)

    digits = _normalize_phone_digits(getattr(bg, 'telefoon', '') or '')
    if digits:
        derived.append(digits[:4])
        derived.append(digits[:6])
        derived.append(f'{digits[:2]} {digits[2:5]}')
        derived.append(digits)

    return GENERIC_SKIP_WORDS + tuple(derived)
