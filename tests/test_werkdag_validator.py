"""Per-record werkdag validator — prevents recurrence of 2025 tarief=0 import bug."""

import pytest
from import_.werkdag_validator import (
    validate_werkdag_record, ValidationError,
)


def _ok_dagpraktijk():
    return {
        'datum': '2025-06-15', 'code': 'CONSULT',
        'uren': 8.0, 'tarief': 77.50, 'km': 45.0, 'km_tarief': 0.23,
    }


def _ok_anw():
    return {
        'datum': '2025-06-15', 'code': 'ANW',
        'uren': 8.0, 'tarief': 95.00, 'km': 30.0, 'km_tarief': 0.0,
    }


def _ok_achterwacht():
    return {
        'datum': '2025-06-15', 'code': 'ACHTERWACHT',
        'uren': 0.0, 'tarief': 0.0, 'km': 0.0, 'km_tarief': 0.0,
    }


def test_valid_dagpraktijk_passes():
    validate_werkdag_record(_ok_dagpraktijk(), inv_type='factuur')


def test_valid_anw_passes():
    validate_werkdag_record(_ok_anw(), inv_type='anw')


def test_valid_achterwacht_passes():
    """Niet-billable code met tarief=0 is legitiem (telt niet voor urencriterium)."""
    validate_werkdag_record(_ok_achterwacht(), inv_type='factuur')


def test_dagpraktijk_tarief_zero_fails_for_billable_code():
    """De exacte bug die in 2025 gebeurde: CONSULT met tarief=0."""
    rec = _ok_dagpraktijk()
    rec['tarief'] = 0.0
    with pytest.raises(ValidationError, match='tarief'):
        validate_werkdag_record(rec, inv_type='factuur')


def test_anw_tarief_zero_fails():
    rec = _ok_anw()
    rec['tarief'] = 0.0
    with pytest.raises(ValidationError, match='tarief'):
        validate_werkdag_record(rec, inv_type='anw')


def test_dagpraktijk_km_without_km_tarief_fails():
    """Km > 0 zonder km_tarief voor dagpraktijk = silent zero reiskosten."""
    rec = _ok_dagpraktijk()
    rec['km_tarief'] = 0.0
    with pytest.raises(ValidationError, match='km_tarief'):
        validate_werkdag_record(rec, inv_type='factuur')


def test_anw_km_without_km_tarief_passes():
    """ANW heeft per-definitie km_tarief=0 (reistijd in uurtarief)."""
    rec = _ok_anw()
    rec['km_tarief'] = 0.0
    validate_werkdag_record(rec, inv_type='anw')  # must not raise


def test_missing_datum_fails():
    rec = _ok_dagpraktijk()
    del rec['datum']
    with pytest.raises(ValidationError, match='datum'):
        validate_werkdag_record(rec, inv_type='factuur')


def test_malformed_datum_fails():
    rec = _ok_dagpraktijk()
    rec['datum'] = '15/06/2025'
    with pytest.raises(ValidationError, match='datum'):
        validate_werkdag_record(rec, inv_type='factuur')


def test_uren_zero_on_billable_fails():
    rec = _ok_dagpraktijk()
    rec['uren'] = 0.0
    with pytest.raises(ValidationError, match='uren'):
        validate_werkdag_record(rec, inv_type='factuur')


def test_negative_values_fail():
    rec = _ok_dagpraktijk()
    rec['uren'] = -1.0
    with pytest.raises(ValidationError, match='negative|negatief'):
        validate_werkdag_record(rec, inv_type='factuur')
