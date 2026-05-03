"""Dutch holidays — pure functions, stdlib-only.

Used by services/agenda.py to compute holiday markers in calendar view.
Returns frozen Holiday dataclass for hashability and Swift-portability.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache


@dataclass(frozen=True)
class Holiday:
    datum: date
    label: str


@lru_cache(maxsize=64)
def easter_sunday(year: int) -> date:
    """Anonymous Gregorian computation (Meeus/Jones/Butcher).

    Verified against known dates: 2020-04-12, 2025-04-20, 2026-04-05, 2030-04-21.
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    L = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * L) // 451
    month = (h + L - 7 * m + 114) // 31
    day = ((h + L - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def koningsdag(year: int) -> date:
    """27 april, of 26 april als 27 een zondag is.

    Geldig vanaf 2014 (Koningsbesluit). Pre-2014 (Koninginnedag, 30 april)
    wordt niet ondersteund — dit project beslaat alleen 2014+.
    """
    candidate = date(year, 4, 27)
    if candidate.weekday() == 6:  # zondag
        return candidate - timedelta(days=1)
    return candidate


@lru_cache(maxsize=32)
def dutch_holidays(year: int) -> tuple[Holiday, ...]:
    """Standaardlijst Nederlandse feestdagen voor het gegeven jaar.

    Returns 11 holidays als immutable tuple (lru_cache-veilig: caller kan niets
    muteren).
    - Nieuwjaarsdag, Goede Vrijdag, Eerste/Tweede Paasdag, Koningsdag,
      Bevrijdingsdag, Hemelvaart, Eerste/Tweede Pinksterdag,
      Eerste/Tweede Kerstdag.

    Geen onderscheid tussen wel/niet wettelijke vrije dag — gebruiker
    beslist zelf via UI of hij op een feestdag werkt (handmatig
    werkdag toevoegen overschrijft de holiday-marker visueel).
    """
    easter = easter_sunday(year)
    return (
        Holiday(date(year, 1, 1), 'Nieuwjaarsdag'),
        Holiday(easter - timedelta(days=2), 'Goede Vrijdag'),
        Holiday(easter, 'Eerste Paasdag'),
        Holiday(easter + timedelta(days=1), 'Tweede Paasdag'),
        Holiday(koningsdag(year), 'Koningsdag'),
        Holiday(date(year, 5, 5), 'Bevrijdingsdag'),
        Holiday(easter + timedelta(days=39), 'Hemelvaart'),
        Holiday(easter + timedelta(days=49), 'Eerste Pinksterdag'),
        Holiday(easter + timedelta(days=50), 'Tweede Pinksterdag'),
        Holiday(date(year, 12, 25), 'Eerste Kerstdag'),
        Holiday(date(year, 12, 26), 'Tweede Kerstdag'),
    )
