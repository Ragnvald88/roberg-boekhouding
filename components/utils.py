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
    'Investeringen',
]

BANK_EXTRA_CATEGORIEEN = ['Omzet', 'Prive', 'Belasting', 'AOV']
BANK_CATEGORIEEN = [''] + KOSTEN_CATEGORIEEN + BANK_EXTRA_CATEGORIEEN


def format_euro(value: float) -> str:
    """Format als Nederlands bedrag: € 1.234,56"""
    if value is None:
        return "\u20ac 0,00"
    return f"\u20ac {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_datum(iso_date: str) -> str:
    """Convert YYYY-MM-DD to DD-MM-YYYY."""
    if not iso_date:
        return ""
    parts = iso_date.split("-")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return iso_date
