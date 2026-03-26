"""Shared document type specifications for aangifte and documenten pages."""

from typing import NamedTuple


class DocSpec(NamedTuple):
    categorie: str
    documenttype: str
    label: str
    meerdere: bool
    verplicht: bool


AANGIFTE_DOCS = [
    DocSpec('winst_onderneming', 'jaaroverzicht_uren_km', 'Jaaroverzicht uren/km', False, True),
    DocSpec('winst_onderneming', 'winst_verlies', 'Winst & verlies', False, True),
    DocSpec('winst_onderneming', 'km_registratie', 'Kilometerregistratie', False, False),
    DocSpec('eigen_woning', 'woz_beschikking', 'WOZ-beschikking', False, False),
    DocSpec('eigen_woning', 'hypotheek_jaaroverzicht', 'Hypotheek jaaroverzicht', True, False),
    DocSpec('inkomensvoorzieningen', 'aov_jaaroverzicht', 'AOV jaaroverzicht', False, False),
    DocSpec('box3', 'jaaroverzicht_prive', 'Jaaroverzicht privérekening', True, False),
    DocSpec('box3', 'jaaroverzicht_zakelijk', 'Jaaroverzicht zakelijke rekening', True, False),
    DocSpec('box3', 'jaaroverzicht_spaar', 'Jaaroverzicht spaarrekening', True, False),
    DocSpec('box3', 'beleggingsoverzicht', 'Beleggingsoverzicht', True, False),
    DocSpec('voorlopige_aanslag', 'va_ib_beschikking', 'VA IB beschikking', False, False),
    DocSpec('voorlopige_aanslag', 'va_zvw_beschikking', 'VA ZVW beschikking', False, False),
    DocSpec('definitieve_aangifte', 'ingediende_aangifte', 'Ingediende aangifte', False, False),
]

AUTO_TYPES = {'jaaroverzicht_uren_km', 'winst_verlies'}

CATEGORIE_LABELS = {
    'winst_onderneming': 'Winst uit onderneming',
    'eigen_woning': 'Eigen woning',
    'inkomensvoorzieningen': 'Inkomensvoorzieningen',
    'box3': 'Box 3',
    'voorlopige_aanslag': 'Voorlopige aanslag',
    'definitieve_aangifte': 'Definitieve aangifte',
}
