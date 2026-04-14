"""Shared Jinja2 environment for invoice templates."""

from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from components.utils import format_euro, format_datum

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(['html']),
)
_env.filters['format_euro'] = format_euro
_env.filters['format_datum'] = format_datum


def _euro_no_decimals(value):
    """Euro format without decimals, for year-end reports."""
    if value is None:
        return '€ 0'
    return f"€ {value:,.0f}".replace(',', '.')


_env.filters['euro'] = _euro_no_decimals
