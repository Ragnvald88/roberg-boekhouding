"""One-time full data import: fiscal params, werkdagen, facturen, bedrijfsgegevens."""

import asyncio
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import init_db, DB_PATH, upsert_bedrijfsgegevens, get_klanten, update_klant
from import_.seed_data import seed_all
from import_.urenregister import import_urenregister, import_facturen_from_pdfs

# Source data
XLSM_PATH = Path(
    "~/Library/CloudStorage/SynologyDrive-Main/02_Financieel/"
    "Boekhouding_Waarneming/Urenregister.xlsm"
).expanduser()

BOEKHOUDING_BASE = Path(
    "~/Library/CloudStorage/SynologyDrive-Main/02_Financieel/"
    "Boekhouding_Waarneming"
).expanduser()

# Customer name mapping: Excel names → cleaner display names
KLANT_MAPPING = {
    "Praktijk K6": "HAP K6",
    "Praktijk K14": "HAP K14",
    "Praktijk K2": "Klant2",
}

# Business info
BEDRIJFSGEGEVENS = {
    'bedrijfsnaam': 'TestBV',
    'naam': 'R.J.P. Gebruiker',
    'functie': 'Waarnemend huisarts',
    'adres': 'Prinsesseweg 36',
    'postcode_plaats': '9717 HA Groningen',
    'kvk': '00000000',
    'iban': 'NL69 RABO 0379 3899 63',
    'thuisplaats': 'Groningen',
}


async def main():
    print(f"Database: {DB_PATH}")

    # Delete existing DB for clean import
    if DB_PATH.exists():
        DB_PATH.unlink()
        print("Deleted existing database")

    # Init fresh DB + seed fiscal params
    await init_db(DB_PATH)
    await seed_all(DB_PATH)
    print("Created database + seeded fiscal parameters")

    # Import werkdagen from Urenregister.xlsm
    if XLSM_PATH.exists():
        result = await import_urenregister(XLSM_PATH, DB_PATH, klant_mapping=KLANT_MAPPING)
        print(f"Werkdagen imported: {result['imported']}, skipped: {result['skipped']}")
        if result['errors']:
            print(f"Errors: {result['errors'][:5]}")
    else:
        print(f"WARNING: {XLSM_PATH} not found, skipping werkdagen import")

    # Import factuur PDFs
    if BOEKHOUDING_BASE.exists():
        result = await import_facturen_from_pdfs(BOEKHOUDING_BASE, DB_PATH)
        print(f"Facturen imported: {result['imported']}, skipped: {result['skipped']}")
    else:
        print(f"WARNING: {BOEKHOUDING_BASE} not found, skipping facturen import")

    # Set active customers and correct tariffs/km
    ACTIEVE_KLANTEN = {
        "HAP K6": {'tarief_uur': 77.50, 'retour_km': 52, 'adres': 'Hoofdstraat 3, 9363 EV Marum'},
        "K. Klant7": {'tarief_uur': 77.50, 'retour_km': 52, 'adres': 'Hoofdstraat 3, 9363 EV Marum'},
        "HAP K14": {'tarief_uur': 80.00, 'retour_km': 44, 'adres': 'Hoofdstraat 1, 1234 AB Plaats14'},
        "K. Klant15": {'tarief_uur': 98.44, 'retour_km': 0, 'adres': 'Nieuw-Weerdinge'},
    }
    klanten = await get_klanten(DB_PATH)
    for k in klanten:
        if k.naam in ACTIEVE_KLANTEN:
            info = ACTIEVE_KLANTEN[k.naam]
            await update_klant(DB_PATH, klant_id=k.id, actief=1,
                               tarief_uur=info['tarief_uur'],
                               retour_km=info['retour_km'],
                               adres=info['adres'])
            print(f"  Activated: {k.naam}")
    print(f"Active customers set ({len(ACTIEVE_KLANTEN)} active)")

    # Set up bedrijfsgegevens
    await upsert_bedrijfsgegevens(DB_PATH, **BEDRIJFSGEGEVENS)
    print("Bedrijfsgegevens saved")

    print("\nDone! Start the app with: python main.py")


if __name__ == '__main__':
    asyncio.run(main())
