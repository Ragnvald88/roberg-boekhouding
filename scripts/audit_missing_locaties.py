"""One-shot audit: which klanten have 0 locaties? Cross-check with stale
seed_data_local.py entries (if still present)."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from database import DB_PATH, get_klanten, get_klant_locaties


async def main():
    klanten = await get_klanten(DB_PATH, alleen_actief=False)
    naam_set = {k.naam for k in klanten}

    print('=== Klanten zonder locaties ===')
    missing = []
    for k in klanten:
        locs = await get_klant_locaties(DB_PATH, k.id)
        if not locs:
            missing.append(k.naam)
            print(f'  {k.naam}')

    print()
    print('=== Stale seed-namen (in seed_data_local.py niet in DB) ===')
    try:
        from import_.seed_data_local import KLANT_LOCATIES  # type: ignore
        for seed_naam in KLANT_LOCATIES:
            if seed_naam not in naam_set:
                print(f'  {seed_naam}')
    except ImportError:
        print('  (seed_data_local.py al verwijderd)')

    print()
    print(f'Aktie: voor {len(missing)} klanten zonder locaties — voeg '
          'handmatig toe via /klanten als nodig.')


if __name__ == '__main__':
    asyncio.run(main())
