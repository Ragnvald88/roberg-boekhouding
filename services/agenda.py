"""Agenda service-layer.

Read + mutation API for the /agenda page. Pure helpers (categorize_werkdag,
derive_werkdag_status_label, parse_weekdays) sit at the top so they can be
imported standalone for testing without DB setup.

UI-free: no nicegui imports. DB-aware: imports from database.py.
Frozen dataclasses for view-objects to keep Swift-port mental model intact.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from typing import Literal

import database
from database import ConflictError, ValidationError
from domain.codes import CODES as _WERKDAG_CODES

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


# ---------------------------------------------------------------------------
# Pattern CRUD (service-layer wrappers around database.db_*_pattern helpers)
# ---------------------------------------------------------------------------

# CODES komt uit domain.codes (UI-free) — geen NiceGUI-import via components/werkdag_form.
_VALID_PATTERN_CODES = frozenset(_WERKDAG_CODES.keys())


@dataclass(frozen=True)
class Pattern:
    """User-facing recurring-pattern view. weekdays is parsed tuple[int, ...] (vs DB-CSV)."""
    id: int
    klant_id: int
    weekdays: tuple[int, ...]
    start_minuten: int
    eind_minuten: int
    code: str
    activiteit: str
    valid_from: str
    valid_until: str
    actief: bool


def _validate_pattern_code(code: str) -> None:
    if code not in _VALID_PATTERN_CODES:
        raise ValidationError(
            f"Ongeldige code '{code}'. Toegestaan: {sorted(_VALID_PATTERN_CODES)}"
        )


def _validate_pattern_minuten(start: int, eind: int) -> None:
    if not (0 <= start < 1440):
        raise ValidationError(f"start_minuten {start} buiten 0-1439")
    if not (0 < eind <= 1440):
        raise ValidationError(f"eind_minuten {eind} buiten 1-1440")
    if eind <= start:
        raise ValidationError(f"eind_minuten ({eind}) moet > start_minuten ({start})")


def _validate_pattern_weekdays(weekdays: list[int]) -> None:
    if not weekdays:
        raise ValidationError("weekdays mag niet leeg zijn")
    if any(w < 1 or w > 7 for w in weekdays):
        raise ValidationError(f"weekdays moeten 1-7 zijn, kreeg: {weekdays}")
    if len(set(weekdays)) != len(weekdays):
        raise ValidationError(f"weekdays bevat duplicaten: {weekdays}")


async def add_pattern(db_path, klant_id: int, weekdays: list[int],
                      start_minuten: int, eind_minuten: int,
                      code: str = 'WERKDAG',
                      activiteit: str = 'Waarneming dagpraktijk',
                      valid_from: str = '', valid_until: str = '') -> int:
    """Add new recurring pattern. NIET year-locked (projection-data, not fiscal facts).

    Validates weekdays (1-7, no duplicates, non-empty), minuten range, and code.
    """
    _validate_pattern_weekdays(weekdays)
    _validate_pattern_minuten(start_minuten, eind_minuten)
    _validate_pattern_code(code)
    csv = ','.join(str(w) for w in sorted(set(weekdays)))
    return await database.db_add_pattern(
        db_path, klant_id=klant_id, weekdays=csv,
        start_minuten=start_minuten, eind_minuten=eind_minuten,
        code=code, activiteit=activiteit,
        valid_from=valid_from, valid_until=valid_until,
    )


async def list_patterns_for_klant(db_path, klant_id: int,
                                   include_inactive: bool = False) -> list[Pattern]:
    rows = await database.db_list_patterns_for_klant(
        db_path, klant_id, include_inactive=include_inactive,
    )
    return [
        Pattern(
            id=r.id, klant_id=r.klant_id,
            weekdays=tuple(parse_weekdays(r.weekdays)),
            start_minuten=r.start_minuten, eind_minuten=r.eind_minuten,
            code=r.code, activiteit=r.activiteit,
            valid_from=r.valid_from, valid_until=r.valid_until,
            actief=r.actief,
        ) for r in rows
    ]


async def update_pattern(db_path, pattern_id: int, **fields) -> None:
    """NIET year-locked. Validates known fields if provided.

    Accepts 'weekdays' as list[int] OR CSV-string ("1,3,5"); both are
    validated and canonicalised to CSV before write. Other input types
    raise ValidationError.

    Cross-field validation: if start_minuten or eind_minuten changes, fetch
    existing to verify the resulting (start, eind) pair is valid.

    Validation errors are *collected* — caller gets one ValidationError
    with all problems joined by '; ' (better UX than first-error-wins).
    """
    errors: list[str] = []

    if 'weekdays' in fields:
        wd = fields['weekdays']
        if isinstance(wd, str):
            try:
                wd = parse_weekdays(wd)
            except ValidationError as e:
                errors.append(str(e))
                wd = None
        elif isinstance(wd, tuple):
            # Pattern.weekdays is tuple — accept round-trip without coercion at caller.
            wd = list(wd)
        elif not isinstance(wd, list):
            errors.append(
                f"weekdays moet list[int]/tuple[int,...] of CSV-string zijn, "
                f"kreeg {type(wd).__name__}"
            )
            wd = None
        if wd is not None:
            try:
                _validate_pattern_weekdays(wd)
                fields['weekdays'] = ','.join(str(w) for w in sorted(set(wd)))
            except ValidationError as e:
                errors.append(str(e))

    if 'start_minuten' in fields or 'eind_minuten' in fields:
        existing = await database.db_get_pattern(db_path, pattern_id)
        if existing is None:
            raise ConflictError(f"Pattern {pattern_id} bestaat niet")
        start = fields.get('start_minuten', existing.start_minuten)
        eind = fields.get('eind_minuten', existing.eind_minuten)
        try:
            _validate_pattern_minuten(start, eind)
        except ValidationError as e:
            errors.append(str(e))

    if 'code' in fields:
        try:
            _validate_pattern_code(fields['code'])
        except ValidationError as e:
            errors.append(str(e))

    if errors:
        raise ValidationError('; '.join(errors))

    await database.db_update_pattern(db_path, pattern_id, **fields)


async def delete_pattern(db_path, pattern_id: int) -> None:
    """Soft delete: SET actief=0. NIET year-locked. Idempotent."""
    await database.db_delete_pattern_soft(db_path, pattern_id)
