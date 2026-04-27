"""Utilities for scanning the expense PDF archive and extracting metadata.

Scans the Boekhouding_Waarneming/{year}/Uitgaven/ archive for expense PDFs,
extracts dates from filenames, maps folder names to app categories, and
detects already-imported files.
"""

import re
from pathlib import Path

from components import archive_paths

# Mapping: archive folder name → app KOSTEN_CATEGORIEEN value
# Note: 'AoV' is deliberately excluded — AOV is not a business expense,
# it's tracked as aov_premie in fiscale_params.
FOLDER_TO_CATEGORIE = {
    'Accountancy': 'Accountancy/software',
    'Software': 'Accountancy/software',
    'Pensioenpremie': 'Pensioenpremie SPH',
    'Verzekeringen': 'Verzekeringen',
    'KPN': 'Telefoon/KPN',
    'Kleine_Aankopen': 'Kleine aankopen',
    'Lidmaatschappen': 'Lidmaatschappen',
    'Investeringen': 'Investeringen',
    'Representatie': 'Representatie',
    'Scholingskosten': 'Scholingskosten',
}


def extract_date_from_filename(filename: str, year: int) -> str | None:
    """Try to extract a date from filename prefix. Returns YYYY-MM-DD or None.

    Supported patterns (in priority order):
    - YYYY-MM-DD_...  (e.g. "2024-02-29_Boekhouder.pdf" → 2024-02-29)
    - MMDDYY_...      (e.g. "123125_Wijgergangs.pdf" → 2025-12-31)
    - MM_YY_... or MM-YY_...  (e.g. "03_25_Boekhouder.pdf" → 2025-03-01)
    - MMYY_...         (e.g. "0125_KPN.pdf" → 2025-01-01, when YY matches year)
    - YYMM_...         (e.g. "2501_Pensioenpremie.pdf" → 2025-01-01, when YY matches year)

    The 4-digit pattern MMYY vs YYMM is disambiguated by checking which pair
    of digits matches the folder year. Files with 4-digit prefixes that don't
    match the year (like invoice numbers) return None.
    """
    stem = Path(filename).stem
    yy = year % 100  # e.g. 25 for 2025

    # Pattern 1: YYYY-MM-DD (ISO date)
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', stem)
    if m:
        y, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2020 <= y <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
            return f'{y}-{month:02d}-{day:02d}'

    # Pattern 2: MMDDYY (6 digits, e.g. "123125" = 12/31/25)
    m = re.match(r'^(\d{2})(\d{2})(\d{2})[_-]', stem)
    if m:
        month, day, file_yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31 and 20 <= file_yy <= 30:
            return f'20{file_yy}-{month:02d}-{day:02d}'

    # Pattern 3: MM_YY or MM-YY (e.g. "03_25" or "01-24")
    m = re.match(r'^(\d{2})[_-](\d{2})[_-]', stem)
    if m:
        month, file_yy = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 20 <= file_yy <= 30:
            return f'20{file_yy}-{month:02d}-01'

    # Pattern 4: 4-digit prefix — disambiguate MMYY vs YYMM vs invoice number
    m = re.match(r'^(\d{4})[_-]', stem)
    if m:
        digits = m.group(1)
        d1, d2 = int(digits[:2]), int(digits[2:])

        # Try MMYY: first 2 = month (01-12), last 2 = year
        if d2 == yy and 1 <= d1 <= 12:
            return f'{year}-{d1:02d}-01'

        # Try YYMM: first 2 = year, last 2 = month (01-12)
        if d1 == yy and 1 <= d2 <= 12:
            return f'{year}-{d2:02d}-01'

    return None


def scan_archive(year: int, existing_filenames: set[str] | None = None) -> list[dict]:
    """Scan the expense archive for a given year.

    Returns list of dicts:
    {
        'path': Path,           # Full path to PDF
        'filename': str,        # Just the filename
        'folder': str,          # Archive folder name (e.g. 'KPN')
        'categorie': str,       # Mapped app category (e.g. 'Telefoon/KPN')
        'datum': str | None,    # Extracted date (YYYY-MM-DD) or None
        'already_imported': bool # True if filename found in existing_filenames
    }

    Args:
        year: The fiscal year to scan
        existing_filenames: Set of filenames already imported (for dedup display).
                           These are the pdf_pad values from the uitgaven table.
    """
    archive_dir = archive_paths.jaar_dir(year) / 'Uitgaven'
    if not archive_dir.exists():
        return []

    existing = existing_filenames or set()
    results = []

    for folder in sorted(archive_dir.iterdir()):
        if not folder.is_dir():
            continue
        categorie = FOLDER_TO_CATEGORIE.get(folder.name)
        if not categorie:
            continue  # Skip unmapped folders (e.g. AoV)

        for pdf_file in sorted(folder.rglob('*.pdf')):
            datum = extract_date_from_filename(pdf_file.name, year)
            # Check dedup: match filename against existing pdf_pad values
            already = pdf_file.name in existing or any(
                pdf_file.name in fn for fn in existing
            )
            results.append({
                'path': pdf_file,
                'filename': pdf_file.name,
                'folder': folder.name,
                'categorie': categorie,
                'datum': datum,
                'already_imported': already,
            })

    return results
