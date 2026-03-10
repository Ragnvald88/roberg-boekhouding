"""Seed 2024 expenses from bank CSV + archive PDFs.

One-time migration script. Reads the 2024 bank statement, categorizes
expense transactions, matches to archive PDFs, and inserts into uitgaven.

Usage:
    python import_/seed_2024_expenses.py [--dry-run]
"""

import csv
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'data' / 'boekhouding.sqlite3'
BANK_CSV = Path(
    '/Users/macbookpro_test/Library/CloudStorage/SynologyDrive-Main'
    '/02_Financieel/Boekhouding_Waarneming/2024/Documenten'
    '/bankafschrift_2024_cleaned.csv'
)
ARCHIVE_DIR = Path(
    '/Users/macbookpro_test/Library/CloudStorage/SynologyDrive-Main'
    '/02_Financieel/Boekhouding_Waarneming/2024/Uitgaven'
)

# --- Bank transaction → expense category rules ---
# (counterparty_pattern, category, zakelijk_pct, description_override)
# Order matters: first match wins.
BANK_RULES = [
    ('ST PENSF HUISARTSEN', 'Pensioenpremie SPH', 100, None),
    ('BOEKHOUDER BELASTINGADVISEURS', 'Accountancy/software', 100, 'Boekhouder Belastingadviseurs'),
    ('SkillSource', 'Accountancy/software', 100, 'e-Boekhouden.nl'),
    ('KPN - Mobiel', 'Telefoon/KPN', 67, None),
    ('KPN B.V.', 'Telefoon/KPN', 67, None),
    ('Boekhouder SCHADEVERZEKERINGEN', 'Verzekeringen', 100, 'Boekhouder Verzekering'),
    ('Kosten', 'Bankkosten', 100, 'Rabobank maandkosten'),
    ('Debetrente', 'Bankkosten', 100, 'Rabobank debetrente'),
    ('NEDERLANDS HUISARTSEN GENOOTSCHAP', 'Lidmaatschappen', 100, 'NHG jaarabonnement'),
    ('VERENIGING Boekhouder', 'Lidmaatschappen', 100, 'Boekhouder jaarlidmaatschap'),
    ('BOEKHOUDER FINANC-ECONOM', 'Lidmaatschappen', 100, 'Boekhouder Fin-Econ Advies'),
    ('MICROSOFT', 'Lidmaatschappen', 100, 'Microsoft 365'),
    ('Paxwinkel', 'Kleine aankopen', 100, 'Paxwinkel ampullenetui'),
    ('Praxisdienst', 'Kleine aankopen', 100, 'Praxisdienst thermometer'),
    ('bol.com', 'Kleine aankopen', 100, 'Bol.com stethoscoop'),
    ('Stichting beheer derdengelden', 'Lidmaatschappen', 100, 'Stichting beheer derdengelden'),
    # Representatie (restaurants)
    ('Bodega Y Tapas', 'Representatie', 100, 'Bodega Y Tapas Groningen'),
    ('Ugly Duck', 'Representatie', 100, 'Ugly Duck Groningen'),
    ('Stadtlander', 'Representatie', 100, 'Stadtlander Groningen'),
    ('Tapaseria Cata', 'Representatie', 100, 'Tapaseria Cata Groningen'),
    # SKIP patterns (matched but not inserted)
    ('Belastingdienst', '_SKIP', 0, None),
    ('Inkomensverzekeringen', '_SKIP', 0, None),  # AOV
    ('T. Gebruiker', '_SKIP', 0, None),  # Privé
    ('Jumbo', '_SKIP', 0, None),  # Privé
    ('Jortt', '_SKIP', 0, None),  # Negligible test txn
]

# Archive folder → category for PDF matching
FOLDER_CATEGORY = {
    'Accountancy': 'Accountancy/software',
    'Pensioenpremie': 'Pensioenpremie SPH',
    'KPN': 'Telefoon/KPN',
    'Verzekeringen': 'Verzekeringen',
    'Lidmaatschappen': 'Lidmaatschappen',
    'Kleine_Aankopen': 'Kleine aankopen',
    'Representatie': 'Representatie',
    'Scholingskosten': 'Scholingskosten',
    'Investeringen': 'Investeringen',
}


def parse_bank_csv():
    """Read and parse the 2024 bank CSV."""
    rows = []
    with open(BANK_CSV, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            bedrag = float(r['Bedrag'].replace('.', '').replace(',', '.'))
            datum_parts = r['Datum'].split('-')
            datum_iso = f'{datum_parts[2]}-{datum_parts[1]}-{datum_parts[0]}'
            rows.append({
                'datum': datum_iso,
                'bedrag': bedrag,
                'tegenpartij': r['Naam tegenpartij'].strip(),
                'omschrijving': r['Omschrijving - 1'].strip(),
            })
    return rows


def categorize_transaction(txn):
    """Match a bank transaction to a category. Returns (category, zakelijk_pct, description) or None."""
    for pattern, category, zak_pct, desc_override in BANK_RULES:
        if pattern.lower() in txn['tegenpartij'].lower():
            if category == '_SKIP':
                return None
            desc = desc_override or txn['tegenpartij']
            return category, zak_pct, desc
    return None  # Unmatched


def build_pdf_index():
    """Build index of archive PDFs by category."""
    index = {}  # category → list of filenames
    for folder_name, category in FOLDER_CATEGORY.items():
        folder = ARCHIVE_DIR / folder_name
        if folder.exists():
            pdfs = sorted(f.name for f in folder.rglob('*.pdf'))
            if category not in index:
                index[category] = []
            index[category].extend(pdfs)
    return index


def match_pdf(category, datum, pdf_index, used_pdfs):
    """Try to find a matching PDF for an expense. Returns filename or ''."""
    candidates = pdf_index.get(category, [])
    if not candidates:
        return ''

    month = datum[5:7]  # e.g. '01' from '2024-01-15'
    year_short = datum[2:4]  # e.g. '24'

    # Try to match by month pattern in filename
    for pdf in candidates:
        if pdf in used_pdfs:
            continue
        pdf_lower = pdf.lower()
        # Match patterns like "01_24", "01-24", "pensioen_01_24"
        if f'{month}_{year_short}' in pdf_lower or f'{month}-{year_short}' in pdf_lower:
            used_pdfs.add(pdf)
            return pdf
        # Match "KPN_Internet_Factuur_9702-{month_num}" pattern
        month_num = str(int(month))
        if f'9702-{month_num}.' in pdf or f'9702-{month_num}' == pdf.split('.')[-2].split('-')[-1]:
            used_pdfs.add(pdf)
            return pdf

    # Fallback: take first unused PDF in the category
    for pdf in candidates:
        if pdf not in used_pdfs:
            used_pdfs.add(pdf)
            return pdf

    return ''


def add_manual_expenses():
    """Expenses not in bank CSV but known from archive/Yuki."""
    return [
        # AED Scholingskosten (€30, paid by different method)
        {
            'datum': '2024-10-30',
            'categorie': 'Scholingskosten',
            'omschrijving': 'AED Reanimatie Sappemeer',
            'bedrag': 30.00,
            'pdf_pad': 'AED Factuur oktober 30 2024 30 okt 2024.pdf',
            'zakelijk_pct': 100,
        },
        # SKGE registration (€102.50, may be via iDEAL or not in bank)
        {
            'datum': '2024-01-15',
            'categorie': 'Lidmaatschappen',
            'omschrijving': 'SKGE kwaliteitsregister',
            'bedrag': 102.50,
            'pdf_pad': 'SKGE.pdf',
            'zakelijk_pct': 100,
        },
        # Mofongo dinner (not in bank, paid differently)
        {
            'datum': '2024-07-07',
            'categorie': 'Representatie',
            'omschrijving': 'Diner collega Mofongo',
            'bedrag': 100.00,
            'pdf_pad': 'Diner_Collega_Mofongo_07-07-24.pdf',
            'zakelijk_pct': 100,
        },
        # CIBG UZI (from Lidmaatschappen archive, exact amount unknown)
        # Boekhouder Zorgservice (in archive but may overlap with Schadeverzekeringen bank txns)
    ]


def main():
    dry_run = '--dry-run' in sys.argv

    # 1. Parse bank
    all_txns = parse_bank_csv()
    expenses_2024 = [t for t in all_txns
                     if t['bedrag'] < 0 and t['datum'].startswith('2024')]

    print(f'Bank: {len(all_txns)} total, {len(expenses_2024)} outgoing in 2024')

    # 2. Build PDF index
    pdf_index = build_pdf_index()
    used_pdfs = set()

    # 3. Check existing expenses (avoid duplication)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    existing = conn.execute(
        "SELECT datum, categorie, bedrag FROM uitgaven WHERE substr(datum,1,4)='2024'"
    ).fetchall()
    existing_set = {(r['datum'], r['categorie'], round(r['bedrag'], 2)) for r in existing}
    print(f'DB: {len(existing)} existing 2024 expenses')

    # 4. Categorize bank transactions
    to_insert = []
    skipped = []
    unmatched = []

    for txn in expenses_2024:
        result = categorize_transaction(txn)
        if result is None:
            if txn['tegenpartij'] not in ('Belastingdienst', 'T. Gebruiker',
                                           'Inkomensverzekeringen', 'Jumbo Foodmarkt',
                                           'Jortt   Boekhouden met een Glimlach via Stichting Mollie Payments'):
                unmatched.append(txn)
            continue

        category, zak_pct, description = result
        bedrag_abs = abs(txn['bedrag'])

        # Apply zakelijk percentage
        if zak_pct < 100:
            bedrag_zakelijk = round(bedrag_abs * zak_pct / 100, 2)
        else:
            bedrag_zakelijk = bedrag_abs

        # Find matching PDF
        pdf_name = match_pdf(category, txn['datum'], pdf_index, used_pdfs)

        # Check for duplicate
        key = (txn['datum'], category, round(bedrag_zakelijk, 2))
        if key in existing_set:
            skipped.append((txn['datum'], category, bedrag_zakelijk, 'already exists'))
            continue

        to_insert.append({
            'datum': txn['datum'],
            'categorie': category,
            'omschrijving': description,
            'bedrag': bedrag_zakelijk,
            'pdf_pad': pdf_name,
            'zakelijk_pct': zak_pct,
        })

    # 5. Add manual expenses (not in bank)
    for manual in add_manual_expenses():
        key = (manual['datum'], manual['categorie'], round(manual['bedrag'], 2))
        if key not in existing_set:
            to_insert.append(manual)

    # 6. Report
    print(f'\n=== To insert: {len(to_insert)} expenses ===')
    by_cat = {}
    for item in to_insert:
        cat = item['categorie']
        by_cat.setdefault(cat, []).append(item)

    for cat in sorted(by_cat):
        items = by_cat[cat]
        total = sum(i['bedrag'] for i in items)
        print(f'\n  {cat}: {len(items)} items, total €{total:,.2f}')
        for item in items:
            pdf_tag = f'  [{item["pdf_pad"][:40]}]' if item.get('pdf_pad') else ''
            zak = f' ({item["zakelijk_pct"]}%)' if item.get('zakelijk_pct', 100) < 100 else ''
            print(f'    {item["datum"]}  €{item["bedrag"]:>8.2f}{zak}{pdf_tag}')

    if skipped:
        print(f'\n  Skipped (already exist): {len(skipped)}')
    if unmatched:
        print(f'\n  Unmatched bank transactions: {len(unmatched)}')
        for u in unmatched:
            print(f'    {u["datum"]}  €{u["bedrag"]:>8.2f}  {u["tegenpartij"][:50]}')

    # 7. Insert
    if dry_run:
        print('\n[DRY RUN] No changes made.')
    else:
        cursor = conn.cursor()
        for item in to_insert:
            cursor.execute(
                """INSERT INTO uitgaven
                   (datum, categorie, omschrijving, bedrag, pdf_pad,
                    is_investering, restwaarde_pct, levensduur_jaren,
                    aanschaf_bedrag, zakelijk_pct)
                   VALUES (?, ?, ?, ?, ?, 0, 10, NULL, NULL, ?)""",
                (item['datum'], item['categorie'], item['omschrijving'],
                 item['bedrag'], item.get('pdf_pad', ''),
                 item.get('zakelijk_pct', 100))
            )
        conn.commit()
        print(f'\n[INSERTED] {len(to_insert)} expenses into DB.')

    # 8. Yuki reference totals for validation
    print('\n=== Yuki 2024 reference (target) ===')
    yuki_ref = {
        'Pensioenpremie SPH': 18386.81,
        'Accountancy/software': 1662.00,  # 1627.49 accountancy + 34.50 automatisering
        'Telefoon/KPN': 985.22,
        'Verzekeringen': 2030.69,
        'Representatie': 533.55,
        'Lidmaatschappen': 493.60,  # contributies
        'Kleine aankopen': 398.04,
        'Bankkosten': 281.28,
        'Scholingskosten': 30.00,
    }
    grand_total_yuki = sum(yuki_ref.values())
    grand_total_app = sum(i['bedrag'] for i in to_insert)

    for cat, ref in sorted(yuki_ref.items()):
        app_total = sum(i['bedrag'] for i in to_insert if i['categorie'] == cat)
        diff = app_total - ref
        status = '✓' if abs(diff) < 1 else f'Δ {diff:+.2f}'
        print(f'  {cat:30s}  Yuki: {ref:>10,.2f}  App: {app_total:>10,.2f}  {status}')

    print(f'  {"TOTAL":30s}  Yuki: {grand_total_yuki:>10,.2f}  App: {grand_total_app:>10,.2f}')

    conn.close()


if __name__ == '__main__':
    main()
