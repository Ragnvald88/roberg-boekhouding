from datetime import date

import pytest

from services.holidays import easter_sunday, koningsdag, dutch_holidays, Holiday


def test_easter_2020():
    assert easter_sunday(2020) == date(2020, 4, 12)


def test_easter_2025():
    assert easter_sunday(2025) == date(2025, 4, 20)


def test_easter_2026():
    assert easter_sunday(2026) == date(2026, 4, 5)


def test_easter_2030():
    assert easter_sunday(2030) == date(2030, 4, 21)


def test_koningsdag_2025_falls_on_saturday_april_26():
    """27 april 2025 = zondag, dus Koningsdag = zaterdag 26 april."""
    assert koningsdag(2025) == date(2025, 4, 26)


def test_koningsdag_2026_falls_on_monday_april_27():
    """27 april 2026 = maandag, geen shift."""
    assert koningsdag(2026) == date(2026, 4, 27)


def test_koningsdag_2031_falls_on_saturday():
    """27 april 2031 = zondag → 26 april."""
    assert koningsdag(2031) == date(2031, 4, 26)


def test_dutch_holidays_2026_count():
    """11 standaard NL feestdagen per jaar."""
    holidays = dutch_holidays(2026)
    assert len(holidays) == 11


def test_dutch_holidays_2026_includes_known_dates():
    holidays = {h.datum: h.label for h in dutch_holidays(2026)}
    assert holidays[date(2026, 1, 1)] == 'Nieuwjaarsdag'
    assert holidays[date(2026, 4, 27)] == 'Koningsdag'
    assert holidays[date(2026, 5, 5)] == 'Bevrijdingsdag'
    assert holidays[date(2026, 12, 25)] == 'Eerste Kerstdag'
    assert holidays[date(2026, 12, 26)] == 'Tweede Kerstdag'
    # Easter 2026 = 5 april
    assert holidays[date(2026, 4, 3)] == 'Goede Vrijdag'
    assert holidays[date(2026, 4, 5)] == 'Eerste Paasdag'
    assert holidays[date(2026, 4, 6)] == 'Tweede Paasdag'
    assert holidays[date(2026, 5, 14)] == 'Hemelvaart'
    assert holidays[date(2026, 5, 24)] == 'Eerste Pinksterdag'
    assert holidays[date(2026, 5, 25)] == 'Tweede Pinksterdag'


def test_holiday_is_frozen_dataclass():
    """Holiday must be hashable + immutable for set/dict use."""
    h = Holiday(datum=date(2026, 1, 1), label='Nieuwjaarsdag')
    with pytest.raises((AttributeError, Exception)):
        h.datum = date(2026, 1, 2)  # frozen, should fail


def test_holidays_no_external_imports():
    """Pure module — only stdlib (datetime, dataclasses, functools)."""
    import services.holidays as mod
    import ast
    src = open(mod.__file__).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module in ('datetime', 'dataclasses', 'functools'), \
                f"Unexpected import: {node.module}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name in ('datetime', 'dataclasses', 'functools'), \
                    f"Unexpected import: {alias.name}"
