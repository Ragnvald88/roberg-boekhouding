"""Klant name resolution for invoice import.

Maps PDF-extracted klant names and filename suffixes to DB klant names.

The actual mapping tables live in `klant_mapping_local.py` (gitignored)
because they contain real customer-identifying data. If that file is
missing, the maps are empty and `resolve_klant` / `resolve_anw_klant`
return (None, None) — manual klant selection in the UI.
"""

SUFFIX_TO_KLANT: dict[str, str] = {}
PDF_KLANT_TO_DB: dict[str, str] = {}
ANW_FILENAME_TO_KLANT: dict[str, str] = {}

try:
    from .klant_mapping_local import (  # type: ignore[import-not-found]
        SUFFIX_TO_KLANT,
        PDF_KLANT_TO_DB,
        ANW_FILENAME_TO_KLANT,
    )
except ImportError:
    pass


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
    if filename_suffix and filename_suffix in SUFFIX_TO_KLANT:
        db_name = SUFFIX_TO_KLANT[filename_suffix]
        if db_name in klant_lookup:
            return db_name, klant_lookup[db_name]

    if pdf_name and pdf_name in PDF_KLANT_TO_DB:
        db_name = PDF_KLANT_TO_DB[pdf_name]
        if db_name in klant_lookup:
            return db_name, klant_lookup[db_name]

    if pdf_name:
        for pdf_variant, db_name in PDF_KLANT_TO_DB.items():
            if pdf_variant.lower() in pdf_name.lower() or pdf_name.lower() in pdf_variant.lower():
                if db_name in klant_lookup:
                    return db_name, klant_lookup[db_name]

    if pdf_name and pdf_name in klant_lookup:
        return pdf_name, klant_lookup[pdf_name]

    return None, None


def resolve_anw_klant(filename: str, klant_lookup: dict[str, int]) -> tuple[str | None, int | None]:
    """Resolve ANW klant from filename pattern."""
    for pattern, db_name in ANW_FILENAME_TO_KLANT.items():
        if pattern.lower() in filename.lower():
            if db_name in klant_lookup:
                return db_name, klant_lookup[db_name]
    return None, None
