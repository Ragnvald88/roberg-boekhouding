"""Shared SynologyDrive archive paths — single source of truth."""

from pathlib import Path

# Root of the bookkeeping archive on SynologyDrive.
# Sub-paths: Inkomen en Uitgaven/{jaar}/Inkomsten/... (invoices)
#            {jaar}/Uitgaven/... (expenses)
ARCHIVE_BASE = (
    Path.home() / 'Library' / 'CloudStorage' / 'SynologyDrive-Main'
    / '02_Financieel' / 'Boekhouding_Waarneming'
)
