"""WeasyPrint PDF factuur generator."""

from pathlib import Path
from datetime import datetime, timedelta
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from components.utils import format_euro, format_datum

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def generate_invoice(factuur_nummer: str, klant: dict, werkdagen: list[dict],
                     output_dir: Path, factuur_datum: str = None,
                     bedrijfsgegevens: dict = None, qr_path: str = '') -> Path:
    """Render Jinja2 HTML template to PDF via WeasyPrint.

    Args:
        factuur_nummer: e.g. "2026-001"
        klant: dict with naam, adres
        werkdagen: list of dicts with datum, activiteit/locatie, uren, tarief, km, km_tarief
        output_dir: directory to save PDF
        factuur_datum: ISO date string, defaults to today
        bedrijfsgegevens: dict with bedrijfsnaam, naam, functie, adres, postcode_plaats, kvk, iban, thuisplaats
        qr_path: path to QR code image; auto-detects from data/qr/betaal_qr.png if empty

    Returns: Path to generated PDF
    """
    if bedrijfsgegevens is None:
        bedrijfsgegevens = {}
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    env.filters['format_euro'] = format_euro
    env.filters['format_datum'] = format_datum
    template = env.get_template('factuur.html')

    if factuur_datum:
        datum = datetime.strptime(factuur_datum, '%Y-%m-%d')
    else:
        datum = datetime.now()
    vervaldatum = datum + timedelta(days=14)

    # Build line items
    regels = []
    subtotaal_werk = 0.0
    subtotaal_km = 0.0

    for wd in werkdagen:
        bedrag = wd['uren'] * wd['tarief']
        regels.append({
            'datum': wd['datum'],
            'omschrijving': wd.get('activiteit', 'Waarneming dagpraktijk'),
            'aantal': wd['uren'],
            'tarief': wd['tarief'],
            'bedrag': bedrag,
        })
        subtotaal_werk += bedrag

        km = wd.get('km', 0) or 0
        km_tarief = wd.get('km_tarief', 0.23) or 0.23
        if km > 0:
            km_bedrag = km * km_tarief
            locatie = wd.get('locatie', '')
            thuisplaats = bedrijfsgegevens.get('thuisplaats', '')
            if locatie and thuisplaats:
                omschr = f"Reiskosten retour {thuisplaats} – {locatie}"
            elif locatie:
                omschr = f"Reiskosten retour – {locatie}"
            else:
                omschr = "Reiskosten"
            regels.append({
                'datum': wd['datum'],
                'omschrijving': omschr,
                'aantal': km,
                'tarief': km_tarief,
                'bedrag': km_bedrag,
            })
            subtotaal_km += km_bedrag

    totaal = subtotaal_werk + subtotaal_km

    # Auto-detect QR code from default location
    if not qr_path:
        default_qr = output_dir.parent / 'qr' / 'betaal_qr.png'
        if default_qr.exists():
            qr_path = str(default_qr)

    qr_uri = ''
    if qr_path and Path(qr_path).exists():
        qr_uri = Path(qr_path).resolve().as_uri()

    # Normalize klant for backward compatibility with structured fields
    klant_full = {
        'naam': klant.get('naam', ''),
        'contactpersoon': klant.get('contactpersoon', ''),
        'adres': klant.get('adres', ''),
        'postcode': klant.get('postcode', ''),
        'plaats': klant.get('plaats', ''),
    }

    html_content = template.render(
        nummer=factuur_nummer,
        datum=format_datum(datum.strftime('%Y-%m-%d')),
        vervaldatum=format_datum(vervaldatum.strftime('%Y-%m-%d')),
        klant=klant_full,
        bedrijf=bedrijfsgegevens,
        regels=regels,
        subtotaal_werk=subtotaal_werk,
        subtotaal_km=subtotaal_km,
        totaal=totaal,
        qr_path=qr_uri,
    )

    # Sanitize filename
    klant_naam = klant.get('naam', 'Onbekend').replace(' ', '_').replace("'", '')
    output_path = output_dir / f"{factuur_nummer}_{klant_naam}.pdf"
    output_dir.mkdir(parents=True, exist_ok=True)

    HTML(string=html_content, base_url=str(TEMPLATE_DIR)).write_pdf(str(output_path))
    return output_path
