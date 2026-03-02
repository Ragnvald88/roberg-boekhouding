"""Afschrijvingsberekeningen.

Lineair, met restwaarde en pro-rata eerste jaar.
"""


def bereken_afschrijving(aanschaf_bedrag: float, restwaarde_pct: float,
                         levensduur: int, aanschaf_maand: int,
                         aanschaf_jaar: int, bereken_jaar: int) -> dict:
    """Calculate depreciation for a given year (pro-rata first year).

    Args:
        aanschaf_bedrag: Purchase price including BTW (BTW-vrijgesteld ondernemer).
        restwaarde_pct: Residual value percentage (typically 10%).
        levensduur: Useful life in years.
        aanschaf_maand: Month of purchase (1-12).
        aanschaf_jaar: Year of purchase.
        bereken_jaar: Year to calculate depreciation for.

    Returns:
        Dict with keys: afschrijving, boekwaarde, per_jaar.
    """
    restwaarde = aanschaf_bedrag * (restwaarde_pct / 100)
    afschrijfbaar = aanschaf_bedrag - restwaarde
    per_jaar = afschrijfbaar / levensduur

    # Years since purchase
    jaren_verstreken = bereken_jaar - aanschaf_jaar
    if jaren_verstreken < 0:
        return {'afschrijving': 0, 'boekwaarde': aanschaf_bedrag, 'per_jaar': round(per_jaar, 2)}

    # Cumulative depreciation up to the END of bereken_jaar
    cum = 0.0
    afschrijving_dit_jaar = 0.0
    for j in range(jaren_verstreken + 1):
        if j == 0:
            # First year: pro-rata (dec purchase = 1 month = 1/12)
            maanden = 13 - aanschaf_maand
            jaar_afschr = per_jaar * (maanden / 12)
        else:
            jaar_afschr = per_jaar

        # Don't depreciate below restwaarde
        max_nog_af = max(0, afschrijfbaar - cum)
        jaar_afschr = min(jaar_afschr, max_nog_af)

        cum += jaar_afschr
        if j == jaren_verstreken:
            afschrijving_dit_jaar = jaar_afschr

    boekwaarde = max(aanschaf_bedrag - cum, restwaarde)

    return {
        'afschrijving': round(afschrijving_dit_jaar, 2),
        'boekwaarde': round(boekwaarde, 2),
        'per_jaar': round(per_jaar, 2),
    }
