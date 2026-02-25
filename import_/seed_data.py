"""Seed data: klanten en fiscale parameters voor TestBV Boekhouding."""

from pathlib import Path
from database import add_klant, get_klanten, upsert_fiscale_params, get_all_fiscale_params

# === Klanten ===

KLANTEN = [
    {
        'naam': "HAP K6",
        'tarief_uur': 77.50,
        'retour_km': 52,
        'adres': 'Hoofdstraat 3, 9363 EV Marum',
        'actief': 1,
    },
    {
        'naam': 'K. Klant7',
        'tarief_uur': 77.50,
        'retour_km': 52,
        'adres': 'Hoofdstraat 3, 9363 EV Marum',
        'actief': 1,
    },
    {
        'naam': 'HAP K14',
        'tarief_uur': 80.00,
        'retour_km': 44,
        'adres': 'Hoofdstraat 1, 1234 AB Plaats14',
        'actief': 1,
    },
    {
        'naam': 'Klant2',
        'tarief_uur': 70.00,
        'retour_km': 108,
        'adres': 'Hoofdstraat 2, 1234 AB Plaats2',
        'actief': 0,
    },
    {
        'naam': 'K. Klant15',
        'tarief_uur': 98.44,
        'retour_km': 0,
        'adres': 'Nieuw-Weerdinge',
        'actief': 1,
    },
]

# === Fiscale parameters per jaar ===

FISCALE_PARAMS: dict[int, dict] = {
    2023: {
        'jaar': 2023,
        'zelfstandigenaftrek': 5030,
        'startersaftrek': 2123,
        'mkb_vrijstelling_pct': 14.0,
        'kia_ondergrens': 2401,
        'kia_bovengrens': 69764,
        'kia_pct': 28,
        'km_tarief': 0.21,
        'schijf1_grens': 73031,
        'schijf1_pct': 36.93,
        'schijf2_grens': 73031,
        'schijf2_pct': 36.93,
        'schijf3_pct': 49.50,
        'ahk_max': 3070,
        'ahk_afbouw_pct': 6.095,
        'ahk_drempel': 22660,
        'ak_max': 5052,
        'zvw_pct': 5.43,
        'zvw_max_grondslag': 66956,
        'repr_aftrek_pct': 80,
    },
    2024: {
        'jaar': 2024,
        'zelfstandigenaftrek': 3750,
        'startersaftrek': 2123,
        'mkb_vrijstelling_pct': 13.31,
        'kia_ondergrens': 2801,
        'kia_bovengrens': 69764,
        'kia_pct': 28,
        'km_tarief': 0.23,
        'schijf1_grens': 75518,
        'schijf1_pct': 36.97,
        'schijf2_grens': 75518,
        'schijf2_pct': 36.97,
        'schijf3_pct': 49.50,
        'ahk_max': 3362,
        'ahk_afbouw_pct': 6.63,
        'ahk_drempel': 24812,
        'ak_max': 5532,
        'zvw_pct': 5.32,
        'zvw_max_grondslag': 71628,
        'repr_aftrek_pct': 80,
    },
    2025: {
        'jaar': 2025,
        'zelfstandigenaftrek': 2470,
        'startersaftrek': 2123,
        'mkb_vrijstelling_pct': 12.70,
        'kia_ondergrens': 2901,
        'kia_bovengrens': 70602,
        'kia_pct': 28,
        'km_tarief': 0.23,
        'schijf1_grens': 38441,
        'schijf1_pct': 35.82,
        'schijf2_grens': 76817,
        'schijf2_pct': 37.48,
        'schijf3_pct': 49.50,
        'ahk_max': 3068,
        'ahk_afbouw_pct': 6.337,
        'ahk_drempel': 28406,
        'ak_max': 5599,
        'zvw_pct': 5.26,
        'zvw_max_grondslag': 75864,
        'repr_aftrek_pct': 80,
    },
    2026: {
        'jaar': 2026,
        'zelfstandigenaftrek': 1200,
        'startersaftrek': None,
        'mkb_vrijstelling_pct': 12.70,
        'kia_ondergrens': 2901,
        'kia_bovengrens': 70602,
        'kia_pct': 28,
        'km_tarief': 0.23,
        'schijf1_grens': 38883,
        'schijf1_pct': 35.75,
        'schijf2_grens': 78426,
        'schijf2_pct': 37.56,
        'schijf3_pct': 49.50,
        'ahk_max': 3115,
        'ahk_afbouw_pct': 6.337,
        'ahk_drempel': 28800,
        'ak_max': 5685,
        'zvw_pct': 4.85,
        'zvw_max_grondslag': 79409,
        'repr_aftrek_pct': 80,
    },
}


async def seed_klanten(db_path: Path) -> int:
    """Insert klanten if table is empty. Returns number of klanten inserted."""
    bestaande = await get_klanten(db_path)
    if bestaande:
        return 0
    count = 0
    for klant in KLANTEN:
        await add_klant(db_path, **klant)
        count += 1
    return count


async def seed_fiscale_params(db_path: Path) -> int:
    """Insert fiscale params if table is empty. Returns number of years inserted."""
    bestaande = await get_all_fiscale_params(db_path)
    if bestaande:
        return 0
    count = 0
    for params in FISCALE_PARAMS.values():
        await upsert_fiscale_params(db_path, **params)
        count += 1
    return count


async def seed_all(db_path: Path) -> None:
    """Seed klanten en fiscale parameters."""
    await seed_klanten(db_path)
    await seed_fiscale_params(db_path)
