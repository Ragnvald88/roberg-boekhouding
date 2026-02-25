"""Bank pagina — Rabobank CSV import + koppelen."""

from nicegui import ui
from components.layout import create_layout


@ui.page('/bank')
async def bank_page():
    create_layout('Bank', '/bank')
    with ui.column().classes('w-full p-4 max-w-6xl mx-auto'):
        ui.label('Bank — onder constructie').classes('text-h5')
