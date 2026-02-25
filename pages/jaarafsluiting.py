"""Jaarafsluiting pagina — fiscale berekeningen + rapporten."""

from nicegui import ui
from components.layout import create_layout


@ui.page('/jaarafsluiting')
async def jaarafsluiting_page():
    create_layout('Jaarafsluiting', '/jaarafsluiting')
    with ui.column().classes('w-full p-4 max-w-6xl mx-auto'):
        ui.label('Jaarafsluiting — onder constructie').classes('text-h5')
