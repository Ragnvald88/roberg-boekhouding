"""Seed data: fiscale parameters (publieke belastingdienst-gegevens)."""

import json
from pathlib import Path
from database import upsert_fiscale_params, get_all_fiscale_params

# Arbeidskorting brackets per year (same data as heffingskortingen.py constants).
# Format: [{"lower", "upper", "rate", "base"}, ...]
AK_BRACKETS = {
    2023: [
        {"lower": 0, "upper": 10741, "rate": 0.08231, "base": 0},
        {"lower": 10741, "upper": 23201, "rate": 0.29861, "base": 884},
        {"lower": 23201, "upper": 37691, "rate": 0.03085, "base": 4605},
        {"lower": 37691, "upper": 115295, "rate": -0.06510, "base": 5052},
        {"lower": 115295, "upper": None, "rate": 0, "base": 0},
    ],
    2024: [
        {"lower": 0, "upper": 11491, "rate": 0.08425, "base": 0},
        {"lower": 11491, "upper": 24821, "rate": 0.31433, "base": 968},
        {"lower": 24821, "upper": 39958, "rate": 0.02471, "base": 5158},
        {"lower": 39958, "upper": 124935, "rate": -0.06510, "base": 5532},
        {"lower": 124935, "upper": None, "rate": 0, "base": 0},
    ],
    2025: [
        {"lower": 0, "upper": 12169, "rate": 0.08053, "base": 0},
        {"lower": 12169, "upper": 26288, "rate": 0.30030, "base": 980},
        {"lower": 26288, "upper": 43071, "rate": 0.02258, "base": 5220},
        {"lower": 43071, "upper": 129078, "rate": -0.06510, "base": 5599},
        {"lower": 129078, "upper": None, "rate": 0, "base": 0},
    ],
    2026: [
        {"lower": 0, "upper": 11965, "rate": 0.08324, "base": 0},
        {"lower": 11965, "upper": 25845, "rate": 0.31009, "base": 996},
        {"lower": 25845, "upper": 45592, "rate": 0.01950, "base": 5300},
        {"lower": 45592, "upper": 132920, "rate": -0.06510, "base": 5685},
        {"lower": 132920, "upper": None, "rate": 0, "base": 0},
    ],
}

# Box 3 forfaitair rendement percentages per year (Belastingdienst)
BOX3_DEFAULTS = {
    2023: {'heffingsvrij': 57000, 'bank': 0.92, 'overig': 6.17, 'schuld': 2.46, 'tarief': 32, 'drempel_schulden': 3400},
    2024: {'heffingsvrij': 57000, 'bank': 1.44, 'overig': 6.04, 'schuld': 2.61, 'tarief': 36, 'drempel_schulden': 3700},
    2025: {'heffingsvrij': 57684, 'bank': 1.37, 'overig': 5.88, 'schuld': 2.70, 'tarief': 36, 'drempel_schulden': 3700},
    2026: {'heffingsvrij': 59357, 'bank': 1.28, 'overig': 6.00, 'schuld': 2.70, 'tarief': 36, 'drempel_schulden': 3800},
}

# === Fiscale parameters per jaar ===

FISCALE_PARAMS: dict[int, dict] = {
    2023: {
        'jaar': 2023,
        'zelfstandigenaftrek': 5030,
        'startersaftrek': 2123,
        'za_actief': 1, 'sa_actief': 1,  # First 3 years: SA active
        'mkb_vrijstelling_pct': 14.0,
        'kia_ondergrens': 2601,
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
        'ew_forfait_pct': 0.35,
        'villataks_grens': 1_200_000,
        'wet_hillen_pct': 83.333,
        'urencriterium': 1225,
        'pvv_premiegrondslag': 37149,
        'arbeidskorting_brackets': json.dumps(AK_BRACKETS[2023]),
        'pvv_aow_pct': 17.90, 'pvv_anw_pct': 0.10, 'pvv_wlz_pct': 9.65,
        'box3_heffingsvrij_vermogen': 57000, 'box3_rendement_bank_pct': 0.92,
        'box3_rendement_overig_pct': 6.17, 'box3_rendement_schuld_pct': 2.46,
        'box3_tarief_pct': 32,
        'box3_drempel_schulden': 3400,
    },
    2024: {
        'jaar': 2024,
        'zelfstandigenaftrek': 3750,
        'startersaftrek': 2123,
        'za_actief': 1, 'sa_actief': 1,  # First 3 years: SA active
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
        'ew_forfait_pct': 0.35,
        'villataks_grens': 1_310_000,
        'wet_hillen_pct': 80.0,
        'urencriterium': 1225,
        'pvv_premiegrondslag': 38098,
        'arbeidskorting_brackets': json.dumps(AK_BRACKETS[2024]),
        'pvv_aow_pct': 17.90, 'pvv_anw_pct': 0.10, 'pvv_wlz_pct': 9.65,
        'box3_heffingsvrij_vermogen': 57000, 'box3_rendement_bank_pct': 1.44,
        'box3_rendement_overig_pct': 6.04, 'box3_rendement_schuld_pct': 2.61,
        'box3_tarief_pct': 36,
        'box3_drempel_schulden': 3700,
    },
    2025: {
        'jaar': 2025,
        'zelfstandigenaftrek': 2470,
        'startersaftrek': 2123,
        'za_actief': 1, 'sa_actief': 1,  # First 3 years: SA active
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
        'zvw_max_grondslag': 75860,
        'repr_aftrek_pct': 80,
        'ew_forfait_pct': 0.35,
        'villataks_grens': 1_330_000,
        'wet_hillen_pct': 76.667,
        'urencriterium': 1225,
        'pvv_premiegrondslag': 38441,
        'arbeidskorting_brackets': json.dumps(AK_BRACKETS[2025]),
        'pvv_aow_pct': 17.90, 'pvv_anw_pct': 0.10, 'pvv_wlz_pct': 9.65,
        'box3_heffingsvrij_vermogen': 57684, 'box3_rendement_bank_pct': 1.37,
        'box3_rendement_overig_pct': 5.88, 'box3_rendement_schuld_pct': 2.70,
        'box3_tarief_pct': 36,
        'box3_drempel_schulden': 3700,
    },
    2026: {
        'jaar': 2026,
        'zelfstandigenaftrek': 1200,
        'startersaftrek': 2123,
        'za_actief': 1, 'sa_actief': 0,  # Year 4+: SA no longer active
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
        'ahk_afbouw_pct': 6.398,
        'ahk_drempel': 29736,
        'ak_max': 5685,
        'zvw_pct': 4.85,
        'zvw_max_grondslag': 79409,
        'repr_aftrek_pct': 80,
        'ew_forfait_pct': 0.35,
        'villataks_grens': 1_350_000,
        'wet_hillen_pct': 71.867,
        'urencriterium': 1225,
        'pvv_premiegrondslag': 38883,
        'arbeidskorting_brackets': json.dumps(AK_BRACKETS[2026]),
        'pvv_aow_pct': 17.90, 'pvv_anw_pct': 0.10, 'pvv_wlz_pct': 9.65,
        'box3_heffingsvrij_vermogen': 59357, 'box3_rendement_bank_pct': 1.28,
        'box3_rendement_overig_pct': 6.00, 'box3_rendement_schuld_pct': 2.70,
        'box3_tarief_pct': 36,
        'box3_drempel_schulden': 3800,
    },
}


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


KLANT_LOCATIES = {
    'HAP NoordOost': [
        ('Groningen', 12), ('Zuidhorn', 52), ('Stadskanaal', 47),
        ('Delfzijl', 64), ('Scheemda', 60),
    ],
    'HAP MiddenLand': [
        ('Assen', 60), ('Hoogeveen', 128), ('Emmen', 102),
    ],
    'Praktijk K2': [('Vlagtwedde', 108)],
    "Praktijk K6": [('Marum', 54)],
    'K. Klant7': [('Marum', 54)],
    'Praktijk K14': [('Winsum', 44)],
    'Praktijk K10': [('Smilde', 78)],
    'Praktijk K11': [('Marum', 40)],
    'Praktijk K12': [('Marum', 54)],
    'Praktijk K13': [('De Wilp', 46)],
    'Praktijk K9': [('Sellingen', 92)],
    'Klant8': [('Marum', 54)],
}


async def seed_klant_locaties(db_path):
    """Seed locations for existing klanten. Skips if locations already exist."""
    from database import get_klanten, add_klant_locatie, get_klant_locaties
    klanten = await get_klanten(db_path, alleen_actief=False)
    klant_by_naam = {k.naam: k for k in klanten}
    count = 0
    for klant_naam, locaties in KLANT_LOCATIES.items():
        klant = klant_by_naam.get(klant_naam)
        if not klant:
            continue
        existing = await get_klant_locaties(db_path, klant.id)
        if existing:
            continue  # Already seeded
        for naam, km in locaties:
            await add_klant_locatie(db_path, klant.id, naam, km)
            count += 1
    return count


async def seed_all(db_path: Path) -> tuple[int, int]:
    """Seed fiscale parameters and klant locaties."""
    fp_count = await seed_fiscale_params(db_path)
    loc_count = await seed_klant_locaties(db_path)
    return fp_count, loc_count
