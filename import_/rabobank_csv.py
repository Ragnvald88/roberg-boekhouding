"""Rabobank CSV parser — semicolon-separated, Dutch formatting."""

import csv
import io
from datetime import datetime


def parse_rabobank_csv(file_content: bytes) -> list[dict]:
    """Parse Rabobank CSV export.

    Handles:
    - Encoding: UTF-8-sig (BOM) and ISO-8859-1 fallback
    - Separator: semicolon (Rabobank default), comma fallback
    - Dates: YYYY-MM-DD and DD-MM-YYYY formats
    - Amounts: Dutch decimal comma (e.g. "-7,50" → -7.50)
    - Quoted fields with leading +/- on amounts and saldo
    """
    # Try encodings: UTF-8-sig first (handles BOM), then ISO-8859-1
    text = None
    for encoding in ('utf-8-sig', 'iso-8859-1'):
        try:
            text = file_content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        raise ValueError("Kan CSV-bestand niet decoderen")

    # Detect separator (semicolon for Rabobank, but handle comma too)
    first_line = text.split('\n')[0]
    sep = ';' if ';' in first_line else ','

    reader = csv.DictReader(io.StringIO(text), delimiter=sep)
    transactions = []

    for row in reader:
        # Parse date (YYYY-MM-DD or DD-MM-YYYY)
        datum_str = row.get('Datum', '').strip().strip('"')
        if not datum_str:
            continue

        datum = None
        for fmt in ('%Y-%m-%d', '%d-%m-%Y'):
            try:
                datum = datetime.strptime(datum_str, fmt).date().isoformat()
                break
            except ValueError:
                continue

        if datum is None:
            continue

        # Amount: Dutch formatting uses dot for thousands, comma for decimal
        # e.g. "-2.919,00" → remove dots → "-2919,00" → comma→dot → -2919.00
        bedrag_str = row.get('Bedrag', '0').strip().strip('"')
        bedrag_str = bedrag_str.replace('.', '').replace(',', '.')
        try:
            bedrag = float(bedrag_str)
        except ValueError:
            continue

        # Merge description fields (Rabobank splits over 3 columns)
        # Column names vary between export formats:
        #   Semicolon export: "Omschrijving-1" (no spaces)
        #   Comma export:     "Omschrijving - 1" (with spaces)
        omschrijving_parts = []
        for suffix in ('1', '2', '3'):
            val = (row.get(f'Omschrijving-{suffix}', '')
                   or row.get(f'Omschrijving - {suffix}', ''))
            val = val.strip().strip('"')
            if val:
                omschrijving_parts.append(val)
        omschrijving = ' '.join(omschrijving_parts)

        # Tegenrekening column name varies between formats
        tegenrekening = (row.get('Tegenrekening IBAN/BBAN', '')
                         or row.get('IBAN/BBAN tegenpartij', ''))

        transactions.append({
            'datum': datum,
            'bedrag': bedrag,
            'tegenrekening': tegenrekening.strip().strip('"'),
            'tegenpartij': row.get('Naam tegenpartij', '').strip().strip('"'),
            'omschrijving': omschrijving,
        })

    return transactions
