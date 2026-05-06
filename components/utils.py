"""Gedeelde formatting functies en constanten."""

import asyncio
import contextlib
import os
import tempfile
from datetime import date
from pathlib import Path


async def write_pdf_atomic(
    html_string: str,
    output_path: Path,
    base_url: Path | None = None,
) -> None:
    """Render HTML naar PDF via WeasyPrint, atomair (write-then-rename).

    Schrijft eerst naar een unieke temp file in dezelfde directory, dan
    ``os.replace``. Bij crash (WeasyPrint segfault, OSError op rename,
    etc.) wordt de temp file opgeruimd en de bestaande PDF (indien
    aanwezig) blijft intact.

    K2 review: 2 call-sites delen dit patroon (factuur regen + jaarcijfers
    PDF export); helper maakt het testbaar via een gedeeld monkeypatch-
    target ipv inline copies in elke call-site.

    Codex follow-up: unieke temp filename via tempfile.NamedTemporaryFile
    (geen vaste ``<pdf>.tmp`` die collidet bij parallelle exports). Cleanup
    in ``contextlib.suppress(OSError)`` zodat de original render/replace
    error niet door een unlink-fail wordt gemaskeerd.
    """
    from weasyprint import HTML
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Unieke temp file in dezelfde dir — atomic os.replace vereist same FS
    fd, tmp_str = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=output_path.stem + '.',
        suffix='.tmp',
    )
    os.close(fd)
    tmp = Path(tmp_str)

    def _render():
        kwargs = {'base_url': str(base_url)} if base_url else {}
        HTML(string=html_string, **kwargs).write_pdf(str(tmp))

    try:
        await asyncio.to_thread(_render)
        await asyncio.to_thread(os.replace, tmp, output_path)
    except Exception:
        # Cleanup: suppress unlink-failures zodat de echte error visible blijft
        def _cleanup():
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        await asyncio.to_thread(_cleanup)
        raise

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


_DUTCH_MAANDEN_KORT = (
    'jan', 'feb', 'mrt', 'apr', 'mei', 'jun',
    'jul', 'aug', 'sep', 'okt', 'nov', 'dec',
)


def format_datum_kort_nl(d: date) -> str:
    """Format date as Dutch short '%-d {maand_kort}' (e.g. '5 mei')."""
    return f'{d.day} {_DUTCH_MAANDEN_KORT[d.month - 1]}'


def format_datum_jaar_nl(d: date) -> str:
    """Format date as Dutch '%-d {maand_kort} {YYYY}' (e.g. '5 mei 2026')."""
    return f'{d.day} {_DUTCH_MAANDEN_KORT[d.month - 1]} {d.year}'


def contrast_text_color(hex_color: str) -> str:
    """Return 'white' or 'black' as readable text-color on hex_color background.

    Uses WCAG relative-luminance formula. Threshold ~0.179 (sqrt(1.05*0.05) - 0.05),
    above which black text reads better, below which white. This is the
    decision-boundary that maximizes contrast ratio against white-or-black.

    Args:
        hex_color: hex string in #RRGGBB format (case-insensitive). Other
            formats raise ValueError.

    Returns:
        'white' or 'black' (lowercase, suitable for inline CSS).

    Examples:
        >>> contrast_text_color('#FFFFFF')  # white bg → black text
        'black'
        >>> contrast_text_color('#000000')  # black bg → white text
        'white'
        >>> contrast_text_color('#0F766E')  # teal-700 (donker) → white text
        'white'
    """
    if not (isinstance(hex_color, str)
            and len(hex_color) == 7
            and hex_color.startswith('#')):
        raise ValueError(
            f'hex_color must be #RRGGBB format, got: {hex_color!r}'
        )
    try:
        r = int(hex_color[1:3], 16) / 255
        g = int(hex_color[3:5], 16) / 255
        b = int(hex_color[5:7], 16) / 255
    except ValueError as exc:
        raise ValueError(
            f'hex_color contains non-hex chars: {hex_color!r}'
        ) from exc

    # WCAG relative luminance (sRGB → linear)
    def _channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)
    # Threshold: midpoint where contrast against white == contrast against black
    return 'black' if luminance > 0.179 else 'white'
