"""Shared Jinja2 environment for invoice templates."""

from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from components.utils import format_euro, format_datum

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
_env.filters['format_euro'] = format_euro
_env.filters['format_datum'] = format_datum
