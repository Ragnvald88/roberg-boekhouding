"""WeasyPrint PDF factuur generator + SynologyDrive archivering."""

import logging
import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from components import archive_paths
from components.template_env import TEMPLATE_DIR, _env
from components.utils import format_datum
from database import DB_PATH

DATA_DIR = DB_PATH.parent

log = logging.getLogger(__name__)

_TYPE_TO_SUBDIR = {
    'factuur': 'Inkomsten/Dagpraktijk',
    'anw': 'Inkomsten/ANW_Diensten',
    'vergoeding': 'Inkomsten',
}


def _safe_archive_basename(
    archive_filename: str | None, fallback: str) -> str:
    """Return a safe basename for the archive destination.

    Strips path components from `archive_filename` so a malicious or
    typo'd upload name like '../../etc/passwd' or '/abs/path/file.pdf'
    can't escape `target_dir`. Rejects embedded NUL (would raise
    ValueError in shutil.copy2 — POSIX paths can't contain \\0). Falls
    back to `fallback` (the local pdf_path.name) when the result would
    be empty, a non-name like '.' / '..', or contain NUL.
    """
    if archive_filename and '\x00' not in archive_filename:
        stripped = Path(archive_filename).name
        if stripped and stripped not in ('.', '..') and '\x00' not in stripped:
            return stripped
    return fallback


def _is_free_path(target: Path) -> bool:
    """True if no file/symlink/directory entry exists at `target`.

    `Path.exists()` returns False for dangling symlinks, which would
    let `shutil.copy2` follow the symlink and write outside the
    intended dir. `os.path.lexists` catches this case.
    """
    return not os.path.lexists(str(target))


def _files_identical(a: Path, b: Path) -> bool:
    """Byte-equal content check, robust against transient FS errors."""
    try:
        return (a.stat().st_size == b.stat().st_size
                and a.read_bytes() == b.read_bytes())
    except OSError:
        return False


def _resolve_collision(target: Path, source: Path) -> tuple[Path, bool]:
    """Pick the destination path and whether a copy is still needed.

    Returns ``(path, needs_write)``:
    - ``(target, True)`` if the spot is free.
    - ``(existing_path, False)`` if the same content is already archived
      at ``target`` or any ``_N`` suffix — idempotent re-import.
    - ``(_N_candidate, True)`` for a fresh suffix slot when content
      differs (closes the silent-overwrite case where two HAP-uploads
      with the same filename but different months would otherwise stomp
      on each other).
    """
    if _is_free_path(target):
        return target, True
    if _files_identical(target, source):
        return target, False
    stem, suffix = target.stem, target.suffix
    n = 2
    while True:
        candidate = target.with_name(f"{stem}_{n}{suffix}")
        if _is_free_path(candidate):
            return candidate, True
        if _files_identical(candidate, source):
            return candidate, False
        n += 1


def archive_factuur_pdf(
    pdf_path: Path,
    factuur_type: str = 'factuur',
    factuur_datum: str = '',
    archive_filename: str | None = None,
) -> Path | None:
    """Copy a factuur PDF to the SynologyDrive financial archive.

    Target: archive_paths.jaar_dir(jaar) / {type_subdir} / {filename}.
    `archive_filename` (optional) overrides the destination basename so
    imported PDFs can keep the user's original filename convention
    (e.g. `0224_HAP_Drenthe.pdf`) rather than the app's internal
    `{nummer}.pdf` form. When None, falls back to pdf_path.name.

    Path-traversal protected: archive_filename is stripped to its
    basename before use. Collision-aware: identical content under the
    same archive name is skipped (idempotent re-import); different
    content gets a `_N` suffix instead of silently overwriting.

    Returns the archive path on success, None on failure (offline,
    permissions, etc). Never raises — archiving failure must not block
    the main workflow.
    """
    if not pdf_path.exists():
        return None
    jaar = factuur_datum[:4] if factuur_datum and len(factuur_datum) >= 4 else str(datetime.now().year)
    subdir = _TYPE_TO_SUBDIR.get(factuur_type, 'Inkomsten')
    target_dir = archive_paths.jaar_dir(jaar) / subdir
    target_name = _safe_archive_basename(archive_filename, pdf_path.name)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / target_name
        resolved, needs_write = _resolve_collision(target, pdf_path)
        if not needs_write:
            log.info(
                "Factuur al gearchiveerd (identieke content): %s", resolved)
            return resolved
        shutil.copy2(str(pdf_path), str(resolved))
        log.info("Factuur gearchiveerd: %s", resolved)
        return resolved
    except (OSError, ValueError) as exc:
        # ValueError covers embedded-NUL paths that slip past the
        # basename sanitizer (shutil/POSIX reject \0 in paths).
        log.warning("Archivering mislukt: %s", exc)
        return None


def generate_invoice(factuur_nummer: str, klant: dict, werkdagen: list[dict],
                     output_dir: Path, factuur_datum: str = None,
                     bedrijfsgegevens: dict = None, qr_path: str = '',
                     pre_regels: list[dict] = None) -> Path:
    """Render Jinja2 HTML template to PDF via WeasyPrint.

    Args:
        factuur_nummer: e.g. "2026-001"
        klant: dict with naam, adres
        werkdagen: list of dicts with datum, activiteit/locatie, uren, tarief, km, km_tarief
        output_dir: directory to save PDF
        factuur_datum: ISO date string, defaults to today
        bedrijfsgegevens: dict with bedrijfsnaam, naam, functie, adres, postcode_plaats, kvk, iban, thuisplaats
        qr_path: path to QR code image (per-factuur betaallink); empty = no QR
        pre_regels: pre-built line items (skips werkdagen→regels conversion if provided)

    Returns: Path to generated PDF
    """
    if bedrijfsgegevens is None:
        bedrijfsgegevens = {}
    template = _env.get_template('factuur.html')

    if factuur_datum:
        datum = datetime.strptime(factuur_datum, '%Y-%m-%d')
    else:
        datum = datetime.now()
    vervaldatum = datum + timedelta(days=14)

    # Build line items — use pre_regels if provided (from invoice builder)
    if pre_regels is not None:
        regels = pre_regels
        for r in regels:
            if 'bedrag' not in r:
                r['bedrag'] = (r.get('aantal', 0) or 0) * (
                    r.get('tarief', 0) or 0)
        subtotaal_werk = sum(r['bedrag'] for r in regels
                             if not r.get('is_reiskosten'))
        subtotaal_km = sum(r['bedrag'] for r in regels
                           if r.get('is_reiskosten'))
    else:
        regels = []
        subtotaal_werk = 0.0
        subtotaal_km = 0.0
        for wd in werkdagen:
            bedrag = wd['uren'] * wd['tarief']
            regels.append({
                'datum': wd['datum'],
                'omschrijving': wd.get('activiteit',
                                       'Waarneming dagpraktijk'),
                'aantal': wd['uren'],
                'tarief': wd['tarief'],
                'bedrag': bedrag,
                'is_reiskosten': False,
            })
            subtotaal_werk += bedrag

            km = wd.get('km', 0) or 0
            km_tarief = wd.get('km_tarief', 0)
            if km > 0 and km_tarief > 0:
                km_bedrag = km * km_tarief
                locatie = wd.get('locatie', '')
                thuisplaats = bedrijfsgegevens.get('thuisplaats', '')
                if locatie and thuisplaats:
                    omschr = (f"Reiskosten (retour {thuisplaats}"
                              f" – {locatie})")
                elif locatie:
                    omschr = f"Reiskosten (retour – {locatie})"
                else:
                    omschr = "Reiskosten"
                regels.append({
                    'datum': wd['datum'],
                    'omschrijving': omschr,
                    'aantal': km,
                    'tarief': km_tarief,
                    'bedrag': km_bedrag,
                    'is_reiskosten': True,
                })
                subtotaal_km += km_bedrag

    totaal = subtotaal_werk + subtotaal_km

    # QR code — only used when explicitly passed (per-factuur betaallink)
    qr_uri = ''
    if qr_path and Path(qr_path).exists():
        qr_uri = Path(qr_path).resolve().as_uri()

    # Auto-detect logo from default location
    logo_uri = ''
    default_logo_dir = DATA_DIR / 'logo'
    if default_logo_dir.exists():
        logo_files = list(default_logo_dir.glob('logo.*'))
        if logo_files:
            logo_uri = logo_files[0].resolve().as_uri()

    # Normalize klant for backward compatibility with structured fields
    klant_full = {
        'naam': klant.get('naam', ''),
        'contactpersoon': klant.get('contactpersoon', ''),
        'adres': klant.get('adres', ''),
        'postcode': klant.get('postcode', ''),
        'plaats': klant.get('plaats', ''),
    }

    tpl_vars = dict(
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
        logo_path=logo_uri,
    )

    # Two-pass render: first plain flow to check page count, then pin
    # betaal to page bottom via position:fixed if it fits on 1 page.
    from weasyprint import HTML
    html_plain = template.render(**tpl_vars, pin_betaal=False)
    doc_plain = HTML(string=html_plain, base_url=str(TEMPLATE_DIR)).render()

    if len(doc_plain.pages) == 1:
        # Content + betaal fits — pin betaal to bottom of page
        html_pinned = template.render(**tpl_vars, pin_betaal=True)
        doc = HTML(string=html_pinned, base_url=str(TEMPLATE_DIR)).render()
    else:
        # Multi-page — keep betaal in normal flow after content
        doc = doc_plain

    # Sanitize filename
    klant_naam = klant.get('naam', 'Onbekend').split()[-1].replace("'", '')
    output_path = output_dir / f"{factuur_nummer}_{klant_naam}.pdf"
    output_dir.mkdir(parents=True, exist_ok=True)

    doc.write_pdf(str(output_path))
    return output_path
