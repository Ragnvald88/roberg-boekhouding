"""Heffingskortingen berekeningen.

Bevat jaar-specifieke tabellen voor arbeidskorting en berekening van de
algemene heffingskorting. Bron: Belastingdienst tabellen per jaar.
"""

# Year-specific arbeidskorting bracket tables.
# Format per bracket: (lower, upper, rate, base)
#   korting = base + rate * (arbeidsinkomen - lower)
# Source: Belastingdienst tabellen per jaar
ARBEIDSKORTING_BRACKETS: dict[int, list[tuple]] = {
    2023: [
        (0, 10741, 0.08231, 0),           # 8.231% van arbeidsinkomen
        (10741, 23201, 0.29861, 884),      # 884 + 29.861% boven 10.741
        (23201, 37691, 0.03085, 4605),     # 4605 + 3.085% boven 23.201
        (37691, 115295, -0.06510, 5052),   # 5052 - 6.510% boven 37.691 (afbouw)
        (115295, None, 0, 0),              # 0 boven afbouwgrens
    ],
    2024: [
        (0, 11490, 0.08425, 0),
        (11490, 24820, 0.31433, 968),
        (24820, 39957, 0.02471, 5158),
        (39957, 124934, -0.06510, 5532),
        (124934, None, 0, 0),
    ],
    2025: [
        (0, 12169, 0.08053, 0),
        (12169, 26288, 0.30030, 980),
        (26288, 43071, 0.02258, 5220),
        (43071, 129078, -0.06510, 5599),
        (129078, None, 0, 0),
    ],
    2026: [
        (0, 11965, 0.08324, 0),
        (11965, 25845, 0.31009, 996),
        (25845, 45592, 0.01950, 5300),
        (45592, 132920, -0.06510, 5685),
        (132920, None, 0, 0),
    ],
}


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
    """Calculate arbeidskorting using full year-specific bracket tables.

    Args:
        arbeidsinkomen: Labour income (winst uit onderneming counts).
        jaar: Tax year (must be in ARBEIDSKORTING_BRACKETS).
        brackets_json: Optional JSON string with bracket definitions from DB.
            Format: [{"lower": 0, "upper": 11491, "rate": 0.08425, "base": 0}, ...]
            If provided and non-empty, overrides Python constant lookup.

    Returns:
        Arbeidskorting in euros (rounded to 2 decimals, minimum 0).
        Falls back to most recent known year if no table exists.
    """
    if brackets_json:
        import json
        json_brackets = json.loads(brackets_json)
        for b in json_brackets:
            lower, upper, rate, base = b['lower'], b['upper'], b['rate'], b['base']
            if upper is None or arbeidsinkomen <= upper:
                korting = base + rate * (arbeidsinkomen - lower)
                return round(max(0, korting), 2)
        return 0.0

    brackets = ARBEIDSKORTING_BRACKETS.get(jaar)
    if not brackets:
        # Fallback to most recent known year
        known_years = sorted(ARBEIDSKORTING_BRACKETS.keys())
        if not known_years:
            return 0.0
        brackets = ARBEIDSKORTING_BRACKETS[known_years[-1]]

    for lower, upper, rate, base in brackets:
        if upper is None or arbeidsinkomen <= upper:
            korting = base + rate * (arbeidsinkomen - lower)
            return round(max(0, korting), 2)

    return 0.0
