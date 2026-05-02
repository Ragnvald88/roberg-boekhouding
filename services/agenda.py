"""Agenda service-layer.

Read + mutation API for the /agenda page. Pure helpers (categorize_werkdag,
derive_werkdag_status_label, parse_weekdays) sit at the top so they can be
imported standalone for testing without DB setup.

UI-free: no nicegui imports. DB-aware: imports from database.py.
Frozen dataclasses for view-objects to keep Swift-port mental model intact.
"""
from __future__ import annotations

from datetime import date as _date
from typing import Literal

from database import ValidationError

# Note: orphan factuurnummer (factuurnummer != '' but factuur_status == '')
# falls through to 'ongefactureerd' here as defensive fallback. UI-laag
# (MonthGrid, Day-Inspector in Sessie 3) kan separately detecteren via
# `factuurnummer != '' and factuur_status == ''` voor een warning-indicator
# zonder dat dit de status-bar-kleur beïnvloedt.


# ---------------------------------------------------------------------------
# Pure helpers (no DB, no UI)
# ---------------------------------------------------------------------------

WerkdagCategory = Literal['dagpraktijk', 'anw', 'overig']

_DAGPRAKTIJK_CODES = frozenset({'WERKDAG', 'WEEKEND_DAG', ''})
_ANW_CODES_PREFIX = 'ANW_'
_ANW_LEGACY_CODES = frozenset({'AVOND', 'NACHT'})


def categorize_werkdag(code: str) -> WerkdagCategory:
    """Categorize a werkdag by code for type-based coloring.

    Returns:
        'dagpraktijk' for WERKDAG/WEEKEND_DAG/empty
        'anw' for ANW_* codes and legacy AVOND/NACHT
        'overig' for all other codes (ACHTERWACHT/CONGRES/OPLEIDING/OVERIG_ZAK/unknown)
    """
    if code in _DAGPRAKTIJK_CODES:
        return 'dagpraktijk'
    if code.startswith(_ANW_CODES_PREFIX) or code in _ANW_LEGACY_CODES:
        return 'anw'
    return 'overig'


WerkdagStatusLabel = Literal[
    'ongefactureerd', 'concept', 'verstuurd', 'verlopen', 'betaald'
]


def derive_werkdag_status_label(werkdag, today: _date) -> WerkdagStatusLabel:
    """Derive UI status label from werkdag + factuur state.

    werkdag must have attributes: factuurnummer, factuur_status, factuur_vervaldatum.

    'verlopen' is a pure-function derivation: factuur is 'verstuurd' AND
    vervaldatum < today. No DB-update needed for this transition.

    Returns 'ongefactureerd' as defensive fallback for unknown status values.
    """
    if not werkdag.factuurnummer:
        return 'ongefactureerd'
    status = werkdag.factuur_status
    if status == 'concept':
        return 'concept'
    if status == 'betaald':
        return 'betaald'
    if status == 'verstuurd':
        verval = werkdag.factuur_vervaldatum
        if verval:
            try:
                if _date.fromisoformat(verval) < today:
                    return 'verlopen'
            except ValueError:
                pass  # invalid datum string — fall through to 'verstuurd'
        return 'verstuurd'
    # Unknown status — defensive fallback
    return 'ongefactureerd'


def parse_weekdays(csv: str) -> list[int]:
    """Parse weekdays CSV ("1,3,5") to sorted unique list of ints 1-7.

    Tolerates whitespace around commas. Raises ValidationError on empty,
    non-numeric, out-of-range (must be 1-7), or duplicates.
    """
    if not csv:
        raise ValidationError("weekdays mag niet leeg zijn")
    try:
        parts = [int(p.strip()) for p in csv.split(',')]
    except ValueError:
        raise ValidationError(f"weekdays bevat niet-numerieke waarde: '{csv}'")
    if any(p < 1 or p > 7 for p in parts):
        raise ValidationError(f"weekdays moeten tussen 1-7 liggen, kreeg: {parts}")
    if len(set(parts)) != len(parts):
        raise ValidationError(f"weekdays bevat duplicaten: {parts}")
    return sorted(parts)
