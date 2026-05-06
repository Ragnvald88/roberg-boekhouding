"""Unit-tests voor Dutch-maand short-format helpers (Sprint I T2.1).

Pure functions — geen DB, geen UI. Voorkomen dat default macOS strftime
'%-d %b' "1 may" produceert ipv het Nederlandse "1 mei".
"""
from datetime import date

import pytest

from components.utils import format_datum_kort_nl, format_datum_jaar_nl


@pytest.mark.parametrize("d, expected", [
    (date(2026, 1, 1), '1 jan'),
    (date(2026, 2, 14), '14 feb'),
    (date(2026, 3, 31), '31 mrt'),
    (date(2026, 4, 5), '5 apr'),
    (date(2026, 5, 17), '17 mei'),   # NIET 'may'
    (date(2026, 6, 30), '30 jun'),
    (date(2026, 7, 4), '4 jul'),
    (date(2026, 8, 22), '22 aug'),
    (date(2026, 9, 9), '9 sep'),
    (date(2026, 10, 10), '10 okt'),  # NIET 'oct'
    (date(2026, 11, 11), '11 nov'),
    (date(2026, 12, 25), '25 dec'),
])
def test_format_datum_kort_nl_alle_maanden(d, expected):
    assert format_datum_kort_nl(d) == expected


def test_format_datum_jaar_nl_includes_year():
    assert format_datum_jaar_nl(date(2026, 5, 17)) == '17 mei 2026'
    assert format_datum_jaar_nl(date(2025, 3, 1)) == '1 mrt 2025'
