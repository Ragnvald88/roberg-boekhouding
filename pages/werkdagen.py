"""Werkdagen pagina — uren/km registratie."""

from nicegui import ui
from components.layout import create_layout


@ui.page('/werkdagen')
async def werkdagen_page():
    create_layout('Werkdagen', '/werkdagen')
    with ui.column().classes('w-full p-4 max-w-6xl mx-auto'):
        ui.label('Werkdagen — onder constructie').classes('text-h5')
