"""Import historical facturen from PDF invoices into the boekhouding app.

Phases:
  A. Fix existing data quality issues (dates, tarieven)
  B. Delete broken facturen (all have totaal_bedrag=0)
  C. Import dagpraktijk facturen from PDFs
  D. Import ANW facturen from PDFs
  E. Link werkdagen to facturen by matching date + klant
  F. Copy PDFs to app data directory

Usage:
    python -m import_.import_facturen [--dry-run]
"""

import asyncio
import re
import shutil
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_db, get_klanten, add_klant
from import_.pdf_parser import parse_dagpraktijk_pdf, parse_anw_pdf
from import_.klant_mapping import (
    resolve_klant, resolve_anw_klant,
    SUFFIX_TO_KLANT, NEW_KLANTEN,
)

# Source directory
BOEKHOUDING_BASE = Path(
    "~/Library/CloudStorage/SynologyDrive-Main/02_Financieel/"
    "Boekhouding_Waarneming"
).expanduser()

# Target directory for PDF copies
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FACTUREN_DIR = DATA_DIR / "facturen"
ANW_DIR = FACTUREN_DIR / "anw"


def _extract_filename_suffix(filename: str) -> str | None:
    """Extract klant suffix from filename like '2024-001_Winsum.pdf' → 'Winsum'.

    Also handles space separator: '2024-031 Klant10.pdf' → 'Klant10'.
    """
    name = Path(filename).stem  # Remove .pdf
    # Try underscore separator
    if '_' in name:
        return name.split('_', 1)[1]
    # Try space separator (e.g., '2024-031 Klant10')
    m = re.match(r'\d{4}-\d{2,5}\s+(.+)', name)
    if m:
        return m.group(1)
    return None


async def fix_werkdagen_dates(db_path: Path) -> int:
    """Fix DD-MM-YYYY dates in werkdagen → YYYY-MM-DD.

    Also fixes DD/MM/YYYY format if present.
    """
    conn = await get_db(db_path)
    try:
        # Fix DD-MM-YYYY format
        cursor = await conn.execute(
            "SELECT id, datum FROM werkdagen WHERE datum LIKE '__-__-____'"
        )
        rows = await cursor.fetchall()
        fixed = 0
        for row in rows:
            wid, datum = row['id'], row['datum']
            parts = datum.split('-')
            if len(parts) == 3:
                new_datum = f"{parts[2]}-{parts[1]}-{parts[0]}"
                await conn.execute(
                    "UPDATE werkdagen SET datum = ? WHERE id = ?",
                    (new_datum, wid),
                )
                fixed += 1

        # Fix DD/MM/YYYY format (if any)
        cursor = await conn.execute(
            "SELECT id, datum FROM werkdagen WHERE datum LIKE '__/__/____'"
        )
        rows = await cursor.fetchall()
        for row in rows:
            wid, datum = row['id'], row['datum']
            parts = datum.split('/')
            if len(parts) == 3:
                new_datum = f"{parts[2]}-{parts[1]}-{parts[0]}"
                await conn.execute(
                    "UPDATE werkdagen SET datum = ? WHERE id = ?",
                    (new_datum, wid),
                )
                fixed += 1

        await conn.commit()
        return fixed
    finally:
        await conn.close()


async def delete_broken_facturen(db_path: Path) -> int:
    """Delete facturen with totaal_bedrag=0 (broken imports) and unlink their werkdagen.

    Only deletes broken records, preserves correctly imported ones.
    """
    conn = await get_db(db_path)
    try:
        # Get nummers of broken facturen
        cursor = await conn.execute(
            "SELECT nummer FROM facturen WHERE totaal_bedrag = 0"
        )
        broken = [row['nummer'] for row in await cursor.fetchall()]
        if not broken:
            return 0

        # Unlink werkdagen linked to broken facturen
        placeholders = ','.join('?' * len(broken))
        await conn.execute(
            f"UPDATE werkdagen SET factuurnummer = '', status = 'ongefactureerd' "
            f"WHERE factuurnummer IN ({placeholders})",
            broken,
        )

        # Delete broken facturen
        await conn.execute(
            f"DELETE FROM facturen WHERE totaal_bedrag = 0"
        )

        await conn.commit()
        return len(broken)
    finally:
        await conn.close()


async def ensure_klanten_exist(db_path: Path) -> dict[str, int]:
    """Ensure all required klanten exist, create missing ones.

    Returns: dict mapping klant naam → klant_id
    """
    klanten = await get_klanten(db_path)
    lookup = {k.naam: k.id for k in klanten}

    for naam, info in NEW_KLANTEN.items():
        if naam not in lookup:
            klant_id = await add_klant(
                db_path, naam=naam,
                tarief_uur=info['tarief_uur'],
                retour_km=info['retour_km'],
                adres=info['adres'],
                actief=0,
            )
            lookup[naam] = klant_id
            print(f"  Created klant: {naam} (id={klant_id})")

    return lookup


async def import_dagpraktijk(db_path: Path, dry_run: bool = False) -> dict:
    """Import dagpraktijk facturen from PDFs.

    Scans {year}/Inkomsten/Dagpraktijk/ for PDFs, parses them,
    creates factuur records, and copies PDFs to data/facturen/.

    Returns: dict with imported, skipped, errors counts and details.
    """
    klant_lookup = await ensure_klanten_exist(db_path)
    conn = await get_db(db_path)

    try:
        imported = 0
        skipped = 0
        errors = []

        for year in [2023, 2024, 2025]:
            dagpraktijk_dir = BOEKHOUDING_BASE / str(year) / "Inkomsten" / "Dagpraktijk"
            if not dagpraktijk_dir.exists():
                continue

            pdfs = sorted(dagpraktijk_dir.glob("*.pdf"))
            for pdf_path in pdfs:
                try:
                    result = await _import_single_dagpraktijk(
                        conn, pdf_path, klant_lookup, dry_run,
                    )
                    if result == 'imported':
                        imported += 1
                    elif result == 'skipped':
                        skipped += 1
                except Exception as e:
                    errors.append(f"{pdf_path.name}: {e}")

        if not dry_run:
            await conn.commit()

        return {'imported': imported, 'skipped': skipped, 'errors': errors}
    finally:
        await conn.close()


async def _import_single_dagpraktijk(
    conn, pdf_path: Path, klant_lookup: dict[str, int], dry_run: bool,
) -> str:
    """Import a single dagpraktijk PDF. Returns 'imported' or 'skipped'."""
    parsed = parse_dagpraktijk_pdf(pdf_path)
    filename = pdf_path.name
    suffix = _extract_filename_suffix(filename)

    # Resolve factuurnummer
    factuurnummer = parsed['factuurnummer']
    if not factuurnummer:
        raise ValueError(f"Could not extract factuurnummer")

    # Check if already exists
    cursor = await conn.execute(
        "SELECT id FROM facturen WHERE nummer = ?", (factuurnummer,)
    )
    if await cursor.fetchone():
        return 'skipped'

    # Resolve klant
    db_naam, klant_id = resolve_klant(parsed['klant_name'], suffix, klant_lookup)
    if not klant_id:
        raise ValueError(
            f"Could not resolve klant: pdf_name={parsed['klant_name']!r}, "
            f"suffix={suffix!r}"
        )

    # Resolve datum
    datum = parsed['factuurdatum']
    if not datum:
        raise ValueError("Could not extract factuurdatum")

    # Resolve totaal
    totaal = parsed['totaal_bedrag']
    if totaal is None:
        raise ValueError("Could not extract totaal_bedrag")

    # Copy PDF to app data directory
    dest_pdf = FACTUREN_DIR / f"{factuurnummer}.pdf"
    pdf_pad = str(dest_pdf)
    if not dry_run:
        FACTUREN_DIR.mkdir(parents=True, exist_ok=True)
        if not dest_pdf.exists():
            shutil.copy2(pdf_path, dest_pdf)

    # Create factuur record
    if not dry_run:
        await conn.execute(
            """INSERT INTO facturen
               (nummer, klant_id, datum, totaal_uren, totaal_km,
                totaal_bedrag, pdf_pad, betaald, betaald_datum, type)
               VALUES (?, ?, ?, 0, 0, ?, ?, 1, '', 'factuur')""",
            (factuurnummer, klant_id, datum, totaal, pdf_pad),
        )

    print(f"  {'[DRY] ' if dry_run else ''}Dagpraktijk: {factuurnummer} "
          f"klant={db_naam} datum={datum} totaal=€{totaal:,.2f}")
    return 'imported'


async def import_anw(db_path: Path, dry_run: bool = False) -> dict:
    """Import ANW (self-billing) facturen from PDFs.

    Scans {year}/Inkomsten/ANW_Diensten/ for PDFs, parses them,
    creates factuur records with type='anw', and copies PDFs to data/facturen/anw/.
    """
    klant_lookup = await ensure_klanten_exist(db_path)
    conn = await get_db(db_path)

    try:
        imported = 0
        skipped = 0
        errors = []

        for year in [2023, 2024, 2025]:
            anw_dir = BOEKHOUDING_BASE / str(year) / "Inkomsten" / "ANW_Diensten"
            if not anw_dir.exists():
                continue

            pdfs = sorted(anw_dir.glob("*.pdf"))
            for pdf_path in pdfs:
                try:
                    result = await _import_single_anw(
                        conn, pdf_path, klant_lookup, dry_run,
                    )
                    if result == 'imported':
                        imported += 1
                    elif result == 'skipped':
                        skipped += 1
                except Exception as e:
                    errors.append(f"{pdf_path.name}: {e}")

        if not dry_run:
            await conn.commit()

        return {'imported': imported, 'skipped': skipped, 'errors': errors}
    finally:
        await conn.close()


async def _import_single_anw(
    conn, pdf_path: Path, klant_lookup: dict[str, int], dry_run: bool,
) -> str:
    """Import a single ANW PDF. Returns 'imported' or 'skipped'."""
    parsed = parse_anw_pdf(pdf_path)
    filename = pdf_path.name

    # Resolve factuurnummer
    factuurnummer = parsed['factuurnummer']
    if not factuurnummer:
        raise ValueError("Could not extract factuurnummer")

    # Check if already exists
    cursor = await conn.execute(
        "SELECT id FROM facturen WHERE nummer = ?", (factuurnummer,)
    )
    if await cursor.fetchone():
        return 'skipped'

    # Resolve klant (from filename pattern)
    db_naam, klant_id = resolve_anw_klant(filename, klant_lookup)
    if not klant_id:
        # Fallback: try PDF-extracted klant name
        db_naam, klant_id = resolve_klant(parsed['klant_name'], None, klant_lookup)
    if not klant_id:
        raise ValueError(
            f"Could not resolve klant: filename={filename!r}, "
            f"pdf_klant={parsed['klant_name']!r}"
        )

    # Resolve datum
    datum = parsed['factuurdatum']
    if not datum:
        raise ValueError("Could not extract factuurdatum")

    # Resolve totaal
    totaal = parsed['totaal_bedrag']
    if totaal is None:
        raise ValueError("Could not extract totaal_bedrag")

    # Copy PDF to app data directory
    ANW_DIR.mkdir(parents=True, exist_ok=True)
    dest_pdf = ANW_DIR / filename
    pdf_pad = str(dest_pdf)
    if not dry_run:
        if not dest_pdf.exists():
            shutil.copy2(pdf_path, dest_pdf)

    # Create factuur record
    if not dry_run:
        await conn.execute(
            """INSERT INTO facturen
               (nummer, klant_id, datum, totaal_uren, totaal_km,
                totaal_bedrag, pdf_pad, betaald, betaald_datum, type)
               VALUES (?, ?, ?, 0, 0, ?, ?, 1, '', 'anw')""",
            (factuurnummer, klant_id, datum, totaal, pdf_pad),
        )

    print(f"  {'[DRY] ' if dry_run else ''}ANW: {factuurnummer} "
          f"klant={db_naam} datum={datum} totaal=€{totaal:,.2f}")
    return 'imported'


async def link_werkdagen_to_facturen(db_path: Path) -> int:
    """Link werkdagen to facturen by matching date + klant.

    For each factuur, find werkdagen with matching klant_id and datum
    that fall within the work dates parsed from the PDF.
    """
    conn = await get_db(db_path)
    try:
        # Get all facturen with their klant_id
        cursor = await conn.execute(
            "SELECT id, nummer, klant_id, datum, pdf_pad FROM facturen ORDER BY nummer"
        )
        facturen = await cursor.fetchall()

        linked_total = 0

        for fac in facturen:
            fac_id = fac['id']
            nummer = fac['nummer']
            klant_id = fac['klant_id']

            # Find ongefactureerde werkdagen for this klant
            cursor = await conn.execute(
                """SELECT id, datum FROM werkdagen
                   WHERE klant_id = ?
                     AND (status = 'ongefactureerd' OR factuurnummer = '' OR factuurnummer IS NULL)
                   ORDER BY datum""",
                (klant_id,),
            )
            wd_rows = await cursor.fetchall()
            if not wd_rows:
                continue

            # Parse PDF to get work dates
            pdf_path = Path(fac['pdf_pad']) if fac['pdf_pad'] else None
            work_dates = set()

            if pdf_path and pdf_path.exists():
                fac_type = fac.get('type', 'factuur') if hasattr(fac, 'get') else 'factuur'
                # Check type from DB
                cursor2 = await conn.execute(
                    "SELECT type FROM facturen WHERE id = ?", (fac_id,)
                )
                type_row = await cursor2.fetchone()
                fac_type = type_row['type'] if type_row else 'factuur'

                if fac_type == 'anw':
                    parsed = parse_anw_pdf(pdf_path)
                    work_dates = set(parsed.get('dienst_dates', []))
                else:
                    parsed = parse_dagpraktijk_pdf(pdf_path)
                    work_dates = set(parsed.get('work_dates', []))

            # Link werkdagen whose dates match the PDF work dates
            linked = 0
            for wd in wd_rows:
                if wd['datum'] in work_dates:
                    await conn.execute(
                        "UPDATE werkdagen SET factuurnummer = ?, status = 'gefactureerd' "
                        "WHERE id = ?",
                        (nummer, wd['id']),
                    )
                    linked += 1

            if linked > 0:
                linked_total += linked

        await conn.commit()
        return linked_total
    finally:
        await conn.close()


async def main(dry_run: bool = False):
    """Run the complete import pipeline."""
    from database import DB_PATH

    db_path = DB_PATH
    print(f"Database: {db_path}")
    print(f"Source: {BOEKHOUDING_BASE}")
    print(f"Dry run: {dry_run}")
    print()

    # Phase A: Fix werkdagen dates
    print("Phase A: Fixing werkdagen dates...")
    fixed = await fix_werkdagen_dates(db_path)
    print(f"  Fixed {fixed} werkdagen dates")
    print()

    # Phase B: Delete broken facturen
    print("Phase B: Deleting broken facturen...")
    if not dry_run:
        deleted = await delete_broken_facturen(db_path)
        print(f"  Deleted {deleted} broken facturen, unlinked werkdagen")
    else:
        print("  [DRY] Would delete broken facturen")
    print()

    # Phase C: Import dagpraktijk facturen
    print("Phase C: Importing dagpraktijk facturen...")
    result = await import_dagpraktijk(db_path, dry_run=dry_run)
    print(f"  Imported: {result['imported']}, Skipped: {result['skipped']}")
    if result['errors']:
        print(f"  Errors ({len(result['errors'])}):")
        for e in result['errors']:
            print(f"    - {e}")
    print()

    # Phase D: Import ANW facturen
    print("Phase D: Importing ANW facturen...")
    result = await import_anw(db_path, dry_run=dry_run)
    print(f"  Imported: {result['imported']}, Skipped: {result['skipped']}")
    if result['errors']:
        print(f"  Errors ({len(result['errors'])}):")
        for e in result['errors']:
            print(f"    - {e}")
    print()

    # Phase E: Link werkdagen to facturen
    print("Phase E: Linking werkdagen to facturen...")
    if not dry_run:
        linked = await link_werkdagen_to_facturen(db_path)
        print(f"  Linked {linked} werkdagen to facturen")
    else:
        print("  [DRY] Would link werkdagen")
    print()

    # Phase F: Verify
    print("Phase F: Verification...")
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute("SELECT COUNT(*) FROM facturen")
        total = (await cursor.fetchone())[0]
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM facturen WHERE totaal_bedrag > 0"
        )
        with_total = (await cursor.fetchone())[0]
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM facturen WHERE type = 'anw'"
        )
        anw = (await cursor.fetchone())[0]
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM werkdagen WHERE factuurnummer != '' AND factuurnummer IS NOT NULL"
        )
        linked_wd = (await cursor.fetchone())[0]
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM werkdagen WHERE datum LIKE '__-__-____'"
        )
        bad_dates = (await cursor.fetchone())[0]

        print(f"  Total facturen: {total}")
        print(f"  With totaal > 0: {with_total}")
        print(f"  ANW facturen: {anw}")
        print(f"  Linked werkdagen: {linked_wd}")
        print(f"  Bad dates remaining: {bad_dates}")
    finally:
        await conn.close()

    print("\nDone!")


if __name__ == '__main__':
    is_dry = '--dry-run' in sys.argv
    asyncio.run(main(dry_run=is_dry))
