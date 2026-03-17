"""Klant name resolution for invoice import.

Maps PDF-extracted klant names and filename suffixes to DB klant names.
"""

# Filename suffix (from 2024-001_Winsum.pdf → 'Winsum') → DB klant naam
SUFFIX_TO_KLANT = {
    'Winsum': 'HAP K14',
    'Klant2': 'Klant2',
    'Klant6': "HAP K6",
    'Klant7': 'K. Klant7',
    'Klant9': 'Praktijk K9',
    'Klant10': 'Praktijk K10',
    'Klant4': 'K. Klant4',
    'Klant5': 'K. Klant5',
    'Klant11': 'Praktijk K11',
    'Klant13': 'Praktijk K13',
    'Klant12': 'Praktijk K12',
    'Marum': "HAP K6",        # Same klant, location Marum
    'Vlagtwedde': 'Klant2',             # Same klant, location Vlagtwedde
    'Klant8': 'K. Klant8',
    'Klant15': 'K. Klant15',
}

# PDF-extracted klant name → DB klant naam
# Covers all name variations found across invoice formats
PDF_KLANT_TO_DB = {
    # Winsum variations
    'Centrum K14': 'HAP K14',
    'K. Klant1': 'HAP K14',
    'Praktijk K14': 'HAP K14',
    'HAP K14': 'HAP K14',

    # Klant2
    'Praktijk K2': 'Klant2',
    'K. Klant2': 'Klant2',
    'Klant2': 'Klant2',

    # Klant6 variations (with/without apostrophe, different articles)
    "Praktijk K6": "HAP K6",
    "Praktijk K6 Plaats3": "HAP K6",
    "Praktijk K6": "HAP K6",
    "HAP K6": "HAP K6",

    # Klant7
    'K. Klant7': 'K. Klant7',

    # Klant9
    'Praktijk K9': 'Praktijk K9',

    # Klant10 (with accent)
    'Praktijk K10': 'Praktijk K10',
    'K. Klant10': 'Praktijk K10',
    'Praktijk K10': 'Praktijk K10',

    # Klant11
    'Praktijk K11': 'Praktijk K11',

    # Klant12 (with/without initials)
    'Praktijk K12': 'Praktijk K12',
    'Praktijk K12': 'Praktijk K12',

    # de Wilp
    'Praktijk K13': 'Praktijk K13',
    'Praktijk K13': 'Praktijk K13',

    # Special / new klanten
    'Dhr. K. Klant4': 'K. Klant4',
    'K. Klant4': 'K. Klant4',
    'Dhr. K. Klant5': 'K. Klant5',
    'Dhr. K. Klant5': 'K. Klant5',
    'K. Klant5': 'K. Klant5',
    'K. Klant8': 'K. Klant8',

    # ANW / HAP klanten
    'HAP MiddenLand spoedpost': 'HAP MiddenLand',
    'HAP MiddenLand': 'HAP MiddenLand',
    'HAP NoordOost': 'HAP NoordOost',
    'HAP NoordOost': 'HAP NoordOost',
    'HAP NoordOost': 'HAP NoordOost',
}

# ANW filename patterns → DB klant naam
ANW_FILENAME_TO_KLANT = {
    'DokterDrenthe': 'HAP MiddenLand',
    'Drenthe': 'HAP MiddenLand',
    'HAP NoordOost': 'HAP NoordOost',
    'DDG': 'HAP NoordOost',
    'Groningen': 'HAP NoordOost',
    'Gr_Factuur': 'HAP NoordOost',
}


def resolve_klant(pdf_name: str | None, filename_suffix: str | None,
                  klant_lookup: dict[str, int]) -> tuple[str | None, int | None]:
    """Resolve a klant name from PDF or filename suffix to (db_naam, klant_id).

    Args:
        pdf_name: Klant name extracted from PDF content (may be None)
        filename_suffix: Klant suffix from filename (e.g., 'Winsum') (may be None)
        klant_lookup: dict mapping DB klant naam → klant_id

    Returns:
        (db_naam, klant_id) or (None, None) if not resolved
    """
    # Strategy 1: Filename suffix (most reliable)
    if filename_suffix and filename_suffix in SUFFIX_TO_KLANT:
        db_name = SUFFIX_TO_KLANT[filename_suffix]
        if db_name in klant_lookup:
            return db_name, klant_lookup[db_name]

    # Strategy 2: PDF-extracted name → exact mapping
    if pdf_name and pdf_name in PDF_KLANT_TO_DB:
        db_name = PDF_KLANT_TO_DB[pdf_name]
        if db_name in klant_lookup:
            return db_name, klant_lookup[db_name]

    # Strategy 3: PDF name contains a known DB klant name (fuzzy)
    if pdf_name:
        for pdf_variant, db_name in PDF_KLANT_TO_DB.items():
            if pdf_variant.lower() in pdf_name.lower() or pdf_name.lower() in pdf_variant.lower():
                if db_name in klant_lookup:
                    return db_name, klant_lookup[db_name]

    # Strategy 4: Direct match in klant_lookup
    if pdf_name and pdf_name in klant_lookup:
        return pdf_name, klant_lookup[pdf_name]

    return None, None


def resolve_anw_klant(filename: str, klant_lookup: dict[str, int]) -> tuple[str | None, int | None]:
    """Resolve ANW klant from filename pattern.

    Handles: 2023-09_DokterDrenthe.pdf, Drenthe_02-24.pdf, 0225_HAP_Drenthe.pdf, etc.
    """
    for pattern, db_name in ANW_FILENAME_TO_KLANT.items():
        if pattern.lower() in filename.lower():
            if db_name in klant_lookup:
                return db_name, klant_lookup[db_name]
    return None, None
