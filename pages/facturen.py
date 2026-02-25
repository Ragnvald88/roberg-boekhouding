"""Facturen pagina — factuur aanmaken + betaalstatus."""

from nicegui import ui
from components.layout import create_layout


@ui.page('/facturen')
async def facturen_page():
    create_layout('Facturen', '/facturen')
    with ui.column().classes('w-full p-4 max-w-6xl mx-auto'):
        ui.label('Facturen — onder constructie').classes('text-h5')
