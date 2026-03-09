"""Import 19 missing invoice PDFs into the database.

Handles:
- 1 dagpraktijk from 2025 (2025-046)
- 13 dagpraktijk from 2026 (2026-001 to 2026-013)
- 1 ANW from 2025 (Dec 2025 Groningen)
- 4 ANW from 2026
- Date fix for 2025-046 werkdag (PDF typo: 2026-12-29 → 2025-12-29)
"""

import sqlite3
import subprocess
import shutil
import sys
from pathlib import Path

# Setup paths
APP_ROOT = Path("/Users/macbookpro_test/Library/CloudStorage/SynologyDrive-Main/06_Development/roberg-boekhouding")
DB_PATH = APP_ROOT / "data" / "boekhouding.sqlite3"
ARCHIVE = Path("/Users/macbookpro_test/Library/CloudStorage/SynologyDrive-Main/02_Financieel/Boekhouding_Waarneming")
FACTUREN_DIR = APP_ROOT / "data" / "facturen"
ANW_DIR = FACTUREN_DIR / "anw"

sys.path.insert(0, str(APP_ROOT))

from import_.pdf_parser import (
    detect_invoice_type, parse_dagpraktijk_text, parse_anw_text,
    extract_dagpraktijk_line_items, extract_anw_diensten
)
from import_.klant_mapping import resolve_klant, resolve_anw_klant, SUFFIX_TO_KLANT

# The 19 PDFs to import
PDFS = [
    # 2025 dagpraktijk
    ARCHIVE / "2025/Inkomsten/Dagpraktijk/2025-046.pdf",
    # 2026 dagpraktijk
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-001_Winsum.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-002_Klant7.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-003_Klant6.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-004_Klant6.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-005_Klant6.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-006_Klant6.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-007_Klant15.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-008_Klant7.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-009_Klant6.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-010_Klant6.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-011_Klant2.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-012_Klant7.pdf",
    ARCHIVE / "2026/Inkomsten/Dagpraktijk/2026-013_Klant6.pdf",
    # ANW
    ARCHIVE / "2025/Inkomsten/ANW_Diensten/2512_Gr_Factuur.pdf",
    ARCHIVE / "2026/Inkomsten/ANW_Diensten/2601_HAP NoordOost.pdf",
    ARCHIVE / "2026/Inkomsten/ANW_Diensten/2601_DokterDrenthe.pdf",
    ARCHIVE / "2026/Inkomsten/ANW_Diensten/2602_HAP NoordOost.pdf",
    ARCHIVE / "2026/Inkomsten/ANW_Diensten/2602_DokterDrenthe.pdf",
]


def extract_text(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True
    )
    return result.stdout


def get_klant_lookup(conn: sqlite3.Connection) -> dict[str, int]:
    """Build klant name → id lookup from DB."""
    cursor = conn.execute("SELECT id, naam FROM klanten")
    return {row[1]: row[0] for row in cursor.fetchall()}


def get_existing_nummers(conn: sqlite3.Connection) -> set[str]:
    """Get all existing factuurnummers."""
    cursor = conn.execute("SELECT nummer FROM facturen")
    return {row[0] for row in cursor.fetchall()}


def get_existing_werkdagen(conn: sqlite3.Connection) -> set[tuple]:
    """Get (datum, klant_id) pairs for dedup."""
    cursor = conn.execute("SELECT datum, klant_id FROM werkdagen")
    return {(row[0], row[1]) for row in cursor.fetchall()}


def parse_pdf(pdf_path: Path) -> dict:
    """Parse a single PDF and return all extracted data."""
    text = extract_text(pdf_path)
    inv_type = detect_invoice_type(text)
    filename = pdf_path.name

    if inv_type == 'dagpraktijk':
        parsed = parse_dagpraktijk_text(text, filename)
        line_items = extract_dagpraktijk_line_items(text)
        return {
            'type': 'factuur',
            'nummer': parsed.get('factuurnummer'),
            'datum': parsed.get('factuurdatum'),
            'totaal_bedrag': parsed.get('totaal_bedrag'),
            'klant_pdf': parsed.get('klant'),
            'line_items': line_items,
            'text': text,
        }
    elif inv_type == 'anw':
        parsed = parse_anw_text(text, filename)
        line_items = extract_anw_diensten(text)
        return {
            'type': 'anw',
            'nummer': parsed.get('factuurnummer'),
            'datum': parsed.get('factuurdatum'),
            'totaal_bedrag': parsed.get('totaal_bedrag'),
            'klant_pdf': parsed.get('klant'),
            'line_items': line_items,
            'text': text,
        }
    else:
        return {'type': 'unknown', 'error': f"Unknown invoice type for {filename}"}


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    klant_lookup = get_klant_lookup(conn)
    existing_nummers = get_existing_nummers(conn)
    existing_werkdagen = get_existing_werkdagen(conn)

    print(f"DB has {len(existing_nummers)} facturen, {len(existing_werkdagen)} werkdagen")
    print(f"Klanten: {klant_lookup}")
    print()

    # Phase 1: Parse all PDFs and validate
    imports = []
    total_bedrag = 0
    total_werkdagen = 0
    errors = []

    for pdf_path in PDFS:
        if not pdf_path.exists():
            errors.append(f"FILE NOT FOUND: {pdf_path}")
            continue

        parsed = parse_pdf(pdf_path)
        if parsed.get('error'):
            errors.append(f"PARSE ERROR {pdf_path.name}: {parsed['error']}")
            continue

        # Resolve klant
        filename = pdf_path.name
        suffix = filename.rsplit('.', 1)[0].split('_', 1)[-1] if '_' in filename else None

        if parsed['type'] == 'anw':
            klant_naam, klant_id = resolve_anw_klant(filename, klant_lookup)
        else:
            klant_naam, klant_id = resolve_klant(parsed['klant_pdf'], suffix, klant_lookup)

        # Fallback: extract klant from "Factuur aan:" in PDF text
        if klant_id is None and parsed.get('text'):
            import re
            m = re.search(r'Factuur aan:\s*\n\s*(.+)', parsed['text'])
            if m:
                fallback_name = m.group(1).strip()
                klant_naam, klant_id = resolve_klant(fallback_name, None, klant_lookup)

        if klant_id is None:
            errors.append(f"KLANT NOT RESOLVED: {filename} (pdf_name={parsed['klant_pdf']}, suffix={suffix})")
            continue

        # Dedup check
        nummer = parsed['nummer']
        if nummer in existing_nummers:
            errors.append(f"DUPLICATE: {nummer} already in DB")
            continue

        # Calculate totals from line items
        line_items = parsed.get('line_items', [])
        sum_uren = sum(li.get('uren', 0) for li in line_items)
        sum_km = sum(li.get('km', 0) for li in line_items)

        import_record = {
            'pdf_path': pdf_path,
            'filename': filename,
            'type': parsed['type'],
            'nummer': nummer,
            'datum': parsed['datum'],
            'totaal_bedrag': parsed['totaal_bedrag'],
            'klant_naam': klant_naam,
            'klant_id': klant_id,
            'line_items': line_items,
            'totaal_uren': sum_uren,
            'totaal_km': sum_km,
        }
        imports.append(import_record)
        total_bedrag += parsed['totaal_bedrag']
        total_werkdagen += len(line_items)

    # Print validation results
    print("=" * 90)
    print("VALIDATION RESULTS")
    print("=" * 90)

    if errors:
        print(f"\n!!! {len(errors)} ERRORS !!!")
        for e in errors:
            print(f"  ERROR: {e}")
        print()

    print(f"\n{len(imports)} invoices ready to import:")
    print(f"{'#':>2} {'Type':<8} {'Nummer':<15} {'Datum':<12} {'Bedrag':>10} {'Klant':<25} {'Items':>5}")
    print("-" * 90)

    for i, rec in enumerate(imports, 1):
        print(f"{i:>2} {rec['type']:<8} {rec['nummer']:<15} {rec['datum']:<12} "
              f"{rec['totaal_bedrag']:>10.2f} {rec['klant_naam']:<25} {len(rec['line_items']):>5}")

        # Print line items
        for li in rec['line_items']:
            datum = li.get('datum', '?')
            uren = li.get('uren', 0)
            tarief = li.get('tarief', 0)
            km = li.get('km', 0)
            km_tarief = li.get('km_tarief', 0)
            bedrag = li.get('bedrag', uren * tarief + km * km_tarief)
            print(f"     └─ {datum}  {uren:>5.1f}h × €{tarief:>6.2f} + {km:>4.0f}km × €{km_tarief:.2f} = €{bedrag:>8.2f}")

    print("-" * 90)
    print(f"TOTAL: {len(imports)} facturen, {total_werkdagen} werkdagen, €{total_bedrag:,.2f}")
    print(f"Expected: 19 facturen, €27,463.90")
    print(f"Match: {'YES' if abs(total_bedrag - 27463.90) < 0.01 and len(imports) == 19 else 'NO'}")

    if abs(total_bedrag - 27463.90) > 0.01 or len(imports) != 19:
        print("\n!!! TOTAL MISMATCH - ABORTING !!!")
        conn.close()
        return

    if errors:
        print("\n!!! ERRORS FOUND - ABORTING !!!")
        conn.close()
        return

    # Phase 2: Actually import
    print("\n" + "=" * 90)
    print("IMPORTING...")
    print("=" * 90)

    facturen_imported = 0
    werkdagen_created = 0

    for rec in imports:
        nummer = rec['nummer']
        # Copy PDF to data directory
        if rec['type'] == 'anw':
            dest = ANW_DIR / rec['filename']
        else:
            dest = FACTUREN_DIR / f"{nummer}.pdf"

        shutil.copy2(str(rec['pdf_path']), str(dest))
        pdf_pad = str(dest.relative_to(APP_ROOT))

        # Insert factuur
        conn.execute(
            """INSERT INTO facturen
               (nummer, klant_id, datum, totaal_uren, totaal_km,
                totaal_bedrag, pdf_pad, betaald, betaald_datum, type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (nummer, rec['klant_id'], rec['datum'],
             rec['totaal_uren'], rec['totaal_km'],
             rec['totaal_bedrag'], pdf_pad,
             1, rec['datum'],  # mark as paid
             rec['type'])
        )
        facturen_imported += 1
        print(f"  ✓ Factuur {nummer} ({rec['klant_naam']}) €{rec['totaal_bedrag']:.2f}")

        # Create werkdagen from line items
        for li in rec['line_items']:
            werkdag_datum = li.get('datum', rec['datum'])

            # Fix 2025-046 date typo: PDF says 29-12-2026, should be 29-12-2025
            if nummer == '2025-046' and werkdag_datum == '2026-12-29':
                werkdag_datum = '2025-12-29'
                print(f"    ⚡ Fixed date typo: 2026-12-29 → 2025-12-29")

            uren = li.get('uren', 0)
            tarief = li.get('tarief', 0)
            km = li.get('km', 0)
            km_tarief = li.get('km_tarief', 0.23)

            # Set activity based on type
            if rec['type'] == 'anw':
                activiteit = 'Achterwacht'
                urennorm = 0
                # For ANW, tarief is derived from bedrag/uren
                if uren > 0 and tarief == 0 and li.get('bedrag', 0) > 0:
                    tarief = li['bedrag'] / uren
            else:
                activiteit = 'Waarneming dagpraktijk'
                urennorm = 1

            # Check for duplicate werkdag
            key = (werkdag_datum, rec['klant_id'])
            if key in existing_werkdagen:
                print(f"    ⚠ Werkdag {werkdag_datum} for {rec['klant_naam']} already exists - linking only")
                # Link existing werkdag to this factuur
                conn.execute(
                    """UPDATE werkdagen SET status='gefactureerd', factuurnummer=?
                       WHERE datum=? AND klant_id=? AND factuurnummer=''""",
                    (nummer, werkdag_datum, rec['klant_id'])
                )
            else:
                conn.execute(
                    """INSERT INTO werkdagen
                       (datum, klant_id, code, activiteit, locatie, uren, km,
                        tarief, km_tarief, status, factuurnummer, opmerking, urennorm, locatie_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (werkdag_datum, rec['klant_id'], '', activiteit, '',
                     uren, km, tarief, km_tarief,
                     'gefactureerd', nummer, '', urennorm, None)
                )
                existing_werkdagen.add(key)
                werkdagen_created += 1

    conn.commit()
    print(f"\n✓ {facturen_imported} facturen imported, {werkdagen_created} werkdagen created")

    # Phase 3: Verify
    print("\n" + "=" * 90)
    print("VERIFICATION")
    print("=" * 90)

    # Count totals
    cursor = conn.execute("""
        SELECT substr(datum,1,4) as jaar, type, COUNT(*) as n, SUM(totaal_bedrag) as total
        FROM facturen GROUP BY jaar, type ORDER BY jaar, type
    """)
    print("\nFacturen by year and type:")
    print(f"{'Year':<6} {'Type':<10} {'Count':>6} {'Total':>12}")
    print("-" * 40)
    grand_total = 0
    for row in cursor.fetchall():
        print(f"{row[0]:<6} {row[1]:<10} {row[2]:>6} €{row[3]:>11,.2f}")
        grand_total += row[3]
    print(f"{'TOTAL':<17} {'':>6} €{grand_total:>11,.2f}")

    # Werkdagen count
    cursor = conn.execute("""
        SELECT substr(datum,1,4) as jaar, COUNT(*) as n, SUM(uren) as uren
        FROM werkdagen GROUP BY jaar ORDER BY jaar
    """)
    print("\nWerkdagen by year:")
    print(f"{'Year':<6} {'Count':>6} {'Uren':>8}")
    print("-" * 24)
    for row in cursor.fetchall():
        print(f"{row[0]:<6} {row[1]:>6} {row[2]:>8.1f}")

    # Verify new facturen exist
    cursor = conn.execute("SELECT nummer, totaal_bedrag FROM facturen WHERE nummer LIKE '2026%' ORDER BY nummer")
    print("\nNew 2026 facturen:")
    for row in cursor.fetchall():
        print(f"  {row[0]}: €{row[1]:,.2f}")

    cursor = conn.execute("SELECT nummer, totaal_bedrag FROM facturen WHERE nummer='2025-046'")
    row = cursor.fetchone()
    if row:
        print(f"\n2025-046: €{row[1]:,.2f}")

    # Verify no duplicates
    cursor = conn.execute("""
        SELECT nummer, COUNT(*) as n FROM facturen GROUP BY nummer HAVING n > 1
    """)
    dupes = cursor.fetchall()
    if dupes:
        print(f"\n!!! DUPLICATES FOUND: {dupes}")
    else:
        print("\n✓ No duplicate factuurnummers")

    # Final total for imported invoices
    nummers = [rec['nummer'] for rec in imports]
    placeholders = ','.join('?' * len(nummers))
    cursor = conn.execute(
        f"SELECT SUM(totaal_bedrag) FROM facturen WHERE nummer IN ({placeholders})",
        nummers
    )
    imported_total = cursor.fetchone()[0]
    print(f"\nImported invoices total: €{imported_total:,.2f}")
    print(f"Expected total: €27,463.90")
    print(f"Match: {'YES ✓' if abs(imported_total - 27463.90) < 0.01 else 'NO ✗'}")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
