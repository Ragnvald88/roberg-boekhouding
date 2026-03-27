"""Tests voor shared UI components."""

from datetime import date

from components.shared_ui import year_options


def test_year_options_default():
    """Default: descending list from current year to 2023."""
    result = year_options()
    assert result[0] == date.today().year
    assert result[-1] == 2023
    assert len(result) == date.today().year - 2023 + 1


def test_year_options_include_next():
    """include_next adds next year."""
    result = year_options(include_next=True)
    assert result[0] == date.today().year + 1


def test_year_options_ascending():
    """descending=False gives oldest first."""
    result = year_options(descending=False)
    assert result[0] == 2023
    assert result[-1] == date.today().year


def test_year_options_as_dict():
    """as_dict returns {year: str(year)} mapping."""
    result = year_options(as_dict=True)
    assert isinstance(result, dict)
    current = date.today().year
    assert result[current] == str(current)


def test_year_options_include_next_as_dict():
    """include_next + as_dict combined."""
    result = year_options(include_next=True, as_dict=True)
    next_year = date.today().year + 1
    assert next_year in result
    assert result[next_year] == str(next_year)
