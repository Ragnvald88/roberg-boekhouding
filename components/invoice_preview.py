"""Render invoice HTML for live preview (no PDF generation)."""

from datetime import datetime, timedelta

from components.template_env import _env
from components.utils import format_datum


def render_invoice_html(nummer: str = '', klant: dict = None,
                        regels: list[dict] = None,
                        factuur_datum: str = '',
                        bedrijfsgegevens: dict = None,
                        qr_url: str = '',
                        logo_url: str = '') -> str:
    """Render invoice template to HTML string for live preview.

    Args:
        nummer: factuurnummer
        klant: dict with naam, contactpersoon, adres, postcode, plaats
        regels: list of dicts with datum, omschrijving, aantal, tarief, bedrag
        factuur_datum: ISO date string (YYYY-MM-DD)
        bedrijfsgegevens: dict with business info
        qr_url: HTTP URL to QR image (for browser preview), or empty
        logo_url: HTTP URL to logo image, or empty

    Returns: HTML string
    """
    if klant is None:
        klant = {}
    if regels is None:
        regels = []
    if bedrijfsgegevens is None:
        bedrijfsgegevens = {}

    template = _env.get_template('factuur.html')

    if factuur_datum:
        try:
            datum = datetime.strptime(factuur_datum, '%Y-%m-%d')
        except ValueError:
            datum = datetime.now()
    else:
        datum = datetime.now()
    vervaldatum = datum + timedelta(days=14)

    # Compute line item bedrag if not provided
    for r in regels:
        if 'bedrag' not in r:
            r['bedrag'] = r.get('aantal', 0) * r.get('tarief', 0)

    # Calculate totals
    subtotaal_werk = sum(r['bedrag'] for r in regels
                         if not r.get('is_reiskosten'))
    subtotaal_km = sum(r['bedrag'] for r in regels
                       if r.get('is_reiskosten'))
    totaal = subtotaal_werk + subtotaal_km

    # Normalize klant
    klant_full = {
        'naam': klant.get('naam', ''),
        'contactpersoon': klant.get('contactpersoon', ''),
        'adres': klant.get('adres', ''),
        'postcode': klant.get('postcode', ''),
        'plaats': klant.get('plaats', ''),
    }

    return template.render(
        nummer=nummer or '\u2014',
        datum=format_datum(datum.strftime('%Y-%m-%d')),
        vervaldatum=format_datum(vervaldatum.strftime('%Y-%m-%d')),
        klant=klant_full,
        bedrijf=bedrijfsgegevens,
        regels=regels,
        subtotaal_werk=subtotaal_werk,
        subtotaal_km=subtotaal_km,
        totaal=totaal,
        qr_path=qr_url,
        logo_path=logo_url,
    )
