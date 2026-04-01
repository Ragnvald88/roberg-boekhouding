"""Heffingskortingen berekeningen.

Arbeidskorting brackets come from the database (fiscale_params.arbeidskorting_brackets).
Seed data in import_/seed_data.py is the single source of truth for year-specific values.
"""

import json


def bereken_algemene_heffingskorting(verzamelinkomen: float, jaar: int,
                                     params: dict) -> float:
    """Calculate algemene heffingskorting based on income and year.

    Args:
        verzamelinkomen: Taxable income (Box 1 verzamelinkomen).
        jaar: Tax year.
        params: Dict with keys 'ahk_max', 'ahk_afbouw_pct', 'ahk_drempel'.

    Returns:
        Algemene heffingskorting in euros (rounded to 2 decimals).
    """
    ahk_max = params['ahk_max']
    ahk_drempel = params['ahk_drempel']
    ahk_afbouw_pct = params['ahk_afbouw_pct']

    if verzamelinkomen <= ahk_drempel:
        return ahk_max

    afbouw = (ahk_afbouw_pct / 100) * (verzamelinkomen - ahk_drempel)
    return max(0, round(ahk_max - afbouw, 2))


def bereken_arbeidskorting(arbeidsinkomen: float, jaar: int,
                           brackets_json: str = '') -> float:
    """Calculate arbeidskorting using DB-driven bracket tables.

    Args:
        arbeidsinkomen: Labour income (winst uit onderneming counts).
        jaar: Tax year.
        brackets_json: JSON string with bracket definitions from DB.
            Format: [{"lower": 0, "upper": 11491, "rate": 0.08425, "base": 0}, ...]

    Returns:
        Arbeidskorting in euros (rounded to 2 decimals, minimum 0).
    """
    if not brackets_json:
        return 0.0

    brackets = json.loads(brackets_json)
    for b in brackets:
        lower, upper, rate, base = b['lower'], b['upper'], b['rate'], b['base']
        if upper is None or arbeidsinkomen <= upper:
            korting = base + rate * (arbeidsinkomen - lower)
            return round(max(0, korting), 2)

    return 0.0
