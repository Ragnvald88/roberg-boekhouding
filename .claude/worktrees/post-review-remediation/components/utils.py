"""Gedeelde formatting functies en constanten."""

KOSTEN_CATEGORIEEN = [
    'Pensioenpremie SPH',
    'Telefoon/KPN',
    'Verzekeringen',
    'Accountancy/software',
    'Representatie',
    'Lidmaatschappen',
    'Kleine aankopen',
    'Scholingskosten',
    'Bankkosten',
    'Automatisering',
    'Overige kosten',
    'Investeringen',
]

BANK_EXTRA_CATEGORIEEN = ['Omzet', 'Prive', 'Belasting', 'AOV']
BANK_CATEGORIEEN = [''] + KOSTEN_CATEGORIEEN + BANK_EXTRA_CATEGORIEEN


def generate_csv(headers: list[str], rows: list[list]) -> str:
    """Generate CSV string from headers and rows (Excel-compatible: semicolon).

    Note: callers should encode with 'utf-8-sig' which adds a BOM for Excel NL.
    """
    import io
    import csv
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def format_euro(value: float | None, decimals: int = 2) -> str:
    """Format als Nederlands bedrag: € 1.234,56 (or € 1.235 with decimals=0)"""
    if value is None:
        value = 0
    formatted = f"{value:,.{decimals}f}"
    return f"\u20ac {formatted}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_datum(iso_date: str) -> str:
    """Convert YYYY-MM-DD to DD-MM-YYYY. Passes through already-NL dates."""
    if not iso_date:
        return ""
    parts = iso_date.split("-")
    if len(parts) == 3 and len(parts[0]) == 4:
        # YYYY-MM-DD → DD-MM-YYYY
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    # Already DD-MM-YYYY or unknown format — return as-is
    return iso_date
