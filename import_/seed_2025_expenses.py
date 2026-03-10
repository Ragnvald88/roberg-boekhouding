"""Seed 2025 expenses from comprehensive bank CSV + archive PDFs.

One-time migration script. Reads the Rabobank CSV, categorizes
2025 expense transactions, matches to archive PDFs, and inserts into uitgaven.

Usage:
    python import_/seed_2025_expenses.py [--dry-run]
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from import_.rabobank_csv import parse_rabobank_csv

DB_PATH = Path(__file__).parent.parent / 'data' / 'boekhouding.sqlite3'
BANK_CSV = Path(
    '/Users/macbookpro_test/Library/CloudStorage/SynologyDrive-Main'
    '/02_Financieel/Boekhouding_Waarneming/RABO_CSV_tm_260309_transacties.csv'
)
ARCHIVE_DIR = Path(
    '/Users/macbookpro_test/Library/CloudStorage/SynologyDrive-Main'
    '/02_Financieel/Boekhouding_Waarneming/2025/Uitgaven'
)

# --- Bank transaction → expense category rules ---
# (counterparty_pattern, category, zakelijk_pct, description_override, max_amount)
# max_amount: skip transactions above this (to exclude investments mixed in)
# Order matters: first match wins.
BANK_RULES = [
    # Pensioenpremie
    ('ST PENSF HUISARTSEN', 'Pensioenpremie SPH', 100, None, None),
    # Accountancy
    ('BOEKHOUDER BELASTINGADVISEURS', 'Accountancy/software', 100, 'Boekhouder Belastingadviseurs', None),
    ('Moneybird B.V.', 'Accountancy/software', 100, None, None),
    # Telefoon — KPN Mobiel exclude iPhone (>€500)
    ('KPN - Mobiel', 'Telefoon/KPN', 67, None, 500),
    ('KPN B.V.', 'Telefoon/KPN', 67, None, None),
    # Verzekeringen
    ('Boekhouder SCHADEVERZEKERINGEN', 'Verzekeringen', 100, 'Boekhouder Verzekering', None),
    # Lidmaatschappen
    ('BOEKHOUDER FINANC-ECONOM', 'Lidmaatschappen', 100, 'Boekhouder Fin-Econ Advies', None),
    ('NEDERLANDS HUISARTSEN GENOOTSCHAP', 'Lidmaatschappen', 100, 'NHG jaarabonnement', None),
    ('Vereniging Boekhouder', 'Lidmaatschappen', 100, 'Boekhouder jaarlidmaatschap', None),
    ('Microsoft', 'Lidmaatschappen', 100, 'Microsoft 365', None),
    # Bankkosten
    ('Rabobank', 'Bankkosten', 100, None, None),
    ('Kosten', 'Bankkosten', 100, 'Rabobank maandkosten', None),
    # Kleine aankopen — from archive-verified purchases
    ('Appelhoes', 'Kleine aankopen', 100, None, None),
    ('Dokterstassen.nl', 'Kleine aankopen', 100, 'Dokterstassen.nl spoedtas', None),
    ('Alternate Nederland', 'Kleine aankopen', 100, 'Alternate IronWolf Pro 14TB', None),
    ('My Media Center', 'Kleine aankopen', 100, 'Intel 10Gbit Network Card', None),
    ('Belsimpel', 'Kleine aankopen', 67, 'Anker Prime lader', None),
    ('KLARNA BANK', 'Kleine aankopen', 100, None, None),
    ('KommaGo', 'Kleine aankopen', 80, 'Ubiquiti UniFi Pro XG 8 switch', None),
    # bol.com — two purchases, handle individually in manual section
    # SKIP patterns (matched but not inserted)
    ('Belastingdienst', '_SKIP', 0, None, None),
    ('Inkomensverzekeringen', '_SKIP', 0, None, None),  # AOV
    ('T. Gebruiker', '_SKIP', 0, None, None),  # Privé
    ('Geldmaat', '_SKIP', 0, None, None),  # ATM
    # Investments already in DB
    ('wijgergangsmedical.nl', '_SKIP', 0, None, None),
    ('notebooksbilliger.de', '_SKIP', 0, None, None),
    ('Azerty.nl', '_SKIP', 0, None, None),
]

# Archive folder → category for PDF matching
FOLDER_CATEGORY = {
    'Accountancy': 'Accountancy/software',
    'Pensioenpremie': 'Pensioenpremie SPH',
    'KPN': 'Telefoon/KPN',
    'Verzekeringen': 'Verzekeringen',
    'Lidmaatschappen': 'Lidmaatschappen',
    'Kleine_Aankopen': 'Kleine aankopen',
    'Investeringen': 'Investeringen',
}


def categorize_transaction(txn):
    """Match a bank transaction to a category.

    Returns (category, zakelijk_pct, description) or None.
    """
    for pattern, category, zak_pct, desc_override, max_amt in BANK_RULES:
        if pattern.lower() in txn['tegenpartij'].lower():
            if category == '_SKIP':
                return None
            # Exclude amounts above max_amount (e.g. iPhone in KPN Mobiel)
            if max_amt and abs(txn['bedrag']) > max_amt:
                return None
            desc = desc_override or txn['tegenpartij']
            return category, zak_pct, desc
    return None  # Unmatched


def build_pdf_index():
    """Build index of archive PDFs by category."""
    index = {}
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

    month = datum[5:7]
    year_short = datum[2:4]

    for pdf in candidates:
        if pdf in used_pdfs:
            continue
        pdf_lower = pdf.lower()
        if (f'{month}{year_short}' in pdf_lower or f'{month}_{year_short}' in pdf_lower
                or f'{month}-{year_short}' in pdf_lower
                or f'{year_short}{month}' in pdf_lower):
            used_pdfs.add(pdf)
            return pdf

    # Fallback: first unused
    for pdf in candidates:
        if pdf not in used_pdfs:
            used_pdfs.add(pdf)
            return pdf

    return ''


def add_manual_expenses():
    """Expenses needing special handling (not auto-matched from bank)."""
    return [
        # bol.com €294.82 — UniFi Gateway Fiber (network, 80% zakelijk)
        # bedrag must be zakelijk amount (convention: bedrag = bruto × zak%)
        {
            'datum': '2025-12-01',
            'categorie': 'Kleine aankopen',
            'omschrijving': 'Ubiquiti UniFi Gateway Fiber',
            'bedrag': round(294.82 * 80 / 100, 2),  # 235.86
            'pdf_pad': '1225_bolcom_UniFiGatewayFiber.pdf',
            'zakelijk_pct': 80,
        },
        # bol.com €75.00 — USB-C cable
        {
            'datum': '2025-09-06',
            'categorie': 'Kleine aankopen',
            'omschrijving': 'USB-C kabel',
            'bedrag': 75.00,
            'pdf_pad': '0925_KabelUSBC.pdf',
            'zakelijk_pct': 100,
        },
        # T. Gebruiker "Lacie" €369.00 — paid personally, business purchase
        {
            'datum': '2025-09-09',
            'categorie': 'Kleine aankopen',
            'omschrijving': 'Lacie Rugged SSD Pro5 2TB',
            'bedrag': 369.00,
            'pdf_pad': 'Lacie Rugged SSD Pro5 2TB .pdf',
            'zakelijk_pct': 100,
        },
    ]


def main():
    dry_run = '--dry-run' in sys.argv

    # 1. Parse bank CSV
    all_txns = parse_rabobank_csv(BANK_CSV.read_bytes())
    expenses_2025 = [t for t in all_txns
                     if t['bedrag'] < 0 and t['datum'].startswith('2025')]
    print(f'Bank: {len(all_txns)} total, {len(expenses_2025)} outgoing in 2025')

    # 2. Build PDF index
    pdf_index = build_pdf_index()
    used_pdfs = set()

    # 3. Check existing (avoid duplication)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    existing = conn.execute(
        "SELECT datum, categorie, bedrag FROM uitgaven WHERE substr(datum,1,4)='2025'"
    ).fetchall()
    existing_set = {(r['datum'], r['categorie'], round(r['bedrag'], 2))
                    for r in existing}
    print(f'DB: {len(existing)} existing 2025 expenses')

    # 4. Categorize bank transactions
    to_insert = []
    skipped = []
    unmatched = []

    for txn in expenses_2025:
        result = categorize_transaction(txn)
        if result is None:
            # Check if it's a known skip
            tp = txn['tegenpartij'].lower()
            if not any(p.lower() in tp for p, c, *_ in BANK_RULES if c == '_SKIP'):
                # Also skip known investment counterparties
                if not any(p.lower() in tp for p in
                           ('wijgergangs', 'notebooksbilliger', 'azerty', 'bol.com')):
                    unmatched.append(txn)
            continue

        category, zak_pct, description = result
        bedrag_abs = abs(txn['bedrag'])

        if zak_pct < 100:
            bedrag_zakelijk = round(bedrag_abs * zak_pct / 100, 2)
        else:
            bedrag_zakelijk = bedrag_abs

        pdf_name = match_pdf(category, txn['datum'], pdf_index, used_pdfs)

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

    # 5. Add manual expenses
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

    grand_total = 0
    for cat in sorted(by_cat):
        items = by_cat[cat]
        total = sum(i['bedrag'] for i in items)
        grand_total += total
        print(f'\n  {cat}: {len(items)} items, total €{total:,.2f}')
        for item in items:
            pdf_tag = f'  [{item["pdf_pad"][:40]}]' if item.get('pdf_pad') else ''
            zak = f' ({item["zakelijk_pct"]}%)' if item.get('zakelijk_pct', 100) < 100 else ''
            print(f'    {item["datum"]}  €{item["bedrag"]:>8.2f}{zak}{pdf_tag}')

    print(f'\n  GRAND TOTAL: €{grand_total:,.2f}')

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

    # 8. AOV info
    aov_txns = [t for t in all_txns
                if t['datum'].startswith('2025') and 'Inkomensverzekeringen' in t['tegenpartij']]
    aov_total = abs(sum(t['bedrag'] for t in aov_txns))
    print(f'\n=== AOV 2025 (for fiscale_params) ===')
    print(f'  12 payments totaling €{aov_total:,.2f}')
    print(f'  → Set fiscale_params.aov_premie = {aov_total}')

    conn.close()


if __name__ == '__main__':
    main()
