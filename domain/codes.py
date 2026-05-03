"""Werkdag codes — single source of truth.

UI-free: no nicegui imports. Used by both components/werkdag_form (UI dropdown)
and services/agenda (validation). Keeps services-layer pure.
"""

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
