"""Shared SynologyDrive archive paths — single source of truth."""

from pathlib import Path

# Root of the bookkeeping archive on SynologyDrive.
# All bookkeeping data sits under `Inkomen en Uitgaven/{jaar}/...`:
#   - Inkomsten/Dagpraktijk/   {jaar}-{NNN}_{Klant}.pdf
#   - Inkomsten/ANW_Diensten/  {MMYY|YYMM}_{HAP}.pdf  (or original upload name)
#   - Inkomsten/                ad-hoc vergoedingen
#   - Uitgaven/{categorie}/    bonnen, gegroepeerd per kostencategorie
#   - Documenten/              aangiftes, polisbladen, urenregister
ARCHIVE_BASE = (
    Path.home() / 'Library' / 'CloudStorage' / 'SynologyDrive-Main'
    / '02_Financieel' / 'Boekhouding_Waarneming'
)


def jaar_dir(jaar: int | str) -> Path:
    """Resolve to ARCHIVE_BASE/Inkomen en Uitgaven/{jaar}/.

    Single source of truth — both invoice archiving (invoice_generator.py)
    and expense scanning (import_/expense_utils.py) use this. If the
    archive layout ever moves, change here only.
    """
    return ARCHIVE_BASE / 'Inkomen en Uitgaven' / str(jaar)
