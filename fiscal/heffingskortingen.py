"""Heffingskortingen berekeningen voor TestBV Boekhouding.

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
        (0, 11491, 0.08425, 0),
        (11491, 24821, 0.31433, 968),
        (24821, 39958, 0.02471, 5158),
        (39958, 124935, -0.06510, 5532),
        (124935, None, 0, 0),
    ],
    2025: [
        (0, 12169, 0.08053, 0),
        (12169, 26288, 0.30030, 980),
        (26288, 43071, 0.02258, 5220),
        (43071, 129078, -0.06510, 5599),
        (129078, None, 0, 0),
    ],
    2026: [
        (0, 12740, 0.08425, 0),
        (12740, 27461, 0.30030, 1073),
        (27461, 43836, 0.02258, 5491),
        (43836, 131072, -0.06510, 5685),
        (131072, None, 0, 0),
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


def bereken_arbeidskorting(arbeidsinkomen: float, jaar: int) -> float:
    """Calculate arbeidskorting using full year-specific bracket tables.

    Args:
        arbeidsinkomen: Labour income (winst uit onderneming counts).
        jaar: Tax year (must be in ARBEIDSKORTING_BRACKETS).

    Returns:
        Arbeidskorting in euros (rounded to 2 decimals, minimum 0).

    Raises:
        ValueError: If no bracket table exists for the given year.
    """
    brackets = ARBEIDSKORTING_BRACKETS.get(jaar)
    if not brackets:
        raise ValueError(f"Geen arbeidskorting-tabel voor jaar {jaar}")

    for lower, upper, rate, base in brackets:
        if upper is None or arbeidsinkomen <= upper:
            korting = base + rate * (arbeidsinkomen - lower)
            return round(max(0, korting), 2)

    return 0.0
