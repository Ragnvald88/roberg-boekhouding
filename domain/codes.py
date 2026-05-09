"""Werkdag codes — single source of truth.

UI-free: no nicegui imports. Used by both components/werkdag_form (UI dropdown)
and services/agenda (validation). Keeps services-layer pure.
"""

import re

CODES = {
    'WERKDAG': 'Waarneming dagpraktijk',
    'WEEKEND_DAG': 'Waarneming weekenddienst (dag)',
    'AVOND': 'Waarneming avonddienst',
    'NACHT': 'Waarneming nachtdienst',
    'ACHTERWACHT': 'Achterwacht',
    'ANW_AVOND': 'ANW avonddienst',
    'ANW_NACHT': 'ANW nachtdienst',
    'ANW_WEEKEND': 'ANW weekenddienst',
    'CONGRES': 'Congres/nascholing',
    'OPLEIDING': 'Opleiding/cursus',
    'OVERIG_ZAK': 'Overig zakelijk (geen patiëntenzorg)',
}

# Codes where uren=0 is expected (non-patient business trips)
ZERO_UREN_CODES = frozenset({'CONGRES', 'OPLEIDING', 'OVERIG_ZAK'})

_WDAGPRAKTIJK_RE = re.compile(r'^WDAGPRAKTIJK_(\d+(?:,\d+)?)$')
_AW_SEGMENT_MAP = {
    'WK': 'werkdag',
    'WKND': 'weekend',
}


def humanize_legacy_code(code: str) -> str:
    """Render legacy/onbekende werkdag-codes menselijk leesbaar.

    Bestaande codes uit CODES blijven via CODES-lookup gerenderd; deze
    helper is alleen fallback voor codes die NIET in CODES zitten.

    Patronen (op basis van DB-realiteit 2026-05-09):
    - 'WDAGPRAKTIJK_NN[,NN]' (424× in DB) → 'Praktijkdienst (€ NN[,NN]/u)'
    - 'ANW_*' met _-segmenten (60×)        → 'ANW · seg1 · seg2 · ...'
                                              (2-letter caps blijven UPPERCASE)
    - 'AW-WK-*' / 'AW-WKND-*' (11×)        → 'AW · werkdag/weekend · X'
    - Vrije tekst kort / titlecased        → as-is (Admin, AQUI)
    - Lange UPPERCASE (>5 chars)           → Title-case (REISTIJD → Reistijd)
    - Lege string                          → '(geen)'
    """
    if not code:
        return '(geen)'

    # Pattern 1: WDAGPRAKTIJK_NN[,NN]
    m = _WDAGPRAKTIJK_RE.match(code)
    if m:
        return f'Praktijkdienst (€ {m.group(1)}/u)'

    # Pattern 2: AW-WK-A / AW-WKND-A
    if code.startswith('AW-'):
        parts = code.split('-')
        humanized = [_AW_SEGMENT_MAP.get(p, p) for p in parts]
        return ' · '.join(humanized)

    # Pattern 3: ANW_X_Y_Z (underscore-separated)
    if '_' in code:
        parts = code.split('_')
        humanized = [parts[0]]  # eerste segment behoudt caps (ANW)
        for p in parts[1:]:
            # 2-letter all-caps afkortingen (DR, GR) blijven uppercase
            if len(p) <= 2 and p.isupper():
                humanized.append(p)
            else:
                humanized.append(p.lower())
        return ' · '.join(humanized)

    # Fallback: free text / acronym
    if code.isupper():
        if len(code) <= 5:
            # Korte acronym blijft uppercase (AQUI, NSCHL)
            return code
        # Lange uppercase woord wordt title-case (REISTIJD → Reistijd)
        return code.title()
    # Mixed case of titlecased — onveranderd doorgeven (Admin)
    return code


def build_code_options(existing_code: str | None) -> dict[str, str]:
    """Build dropdown options-dict voor werkdag-activiteit dropdown.

    - Returns een nieuwe dict (CODES wordt NIET gemuteerd)
    - existing_code in CODES of None → exact CODES-inhoud
    - existing_code niet in CODES → entry {existing_code: humanize_legacy_code(...)} toegevoegd
    - existing_code == '' → entry {'': '(geen)'} toegevoegd, zodat lege code
      een expliciete dropdown-keuze blijft (anders zou 'lege werkdag' bij
      edit-save stilletjes naar 'WERKDAG' muteren)
    """
    options = dict(CODES)
    if existing_code is None:
        return options
    if existing_code in options:
        return options
    options[existing_code] = humanize_legacy_code(existing_code)
    return options


def derive_activiteit(code: str, current_activiteit: str | None) -> str:
    """Bepaal activiteit-tekst voor save.

    - Code in CODES → CODES[code] (canonical label voor known codes)
    - Code niet in CODES + current_activiteit truthy → current_activiteit
      (preserve historische tekst voor legacy codes; voorkomt dat edit-save
      van WDAGPRAKTIJK_77,50 zijn historische activiteit-tekst verliest)
    - Code niet in CODES + geen current → humanize_legacy_code(code)
    - Lege code + geen current → ''
    """
    if code in CODES:
        return CODES[code]
    if current_activiteit:
        return current_activiteit
    if not code:
        return ''
    return humanize_legacy_code(code)
