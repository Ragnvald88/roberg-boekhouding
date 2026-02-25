"""Kosten pagina — uitgaven + categorisatie."""

from nicegui import ui
from components.layout import create_layout


@ui.page('/kosten')
async def kosten_page():
    create_layout('Kosten', '/kosten')
    with ui.column().classes('w-full p-4 max-w-6xl mx-auto'):
        ui.label('Kosten — onder constructie').classes('text-h5')
