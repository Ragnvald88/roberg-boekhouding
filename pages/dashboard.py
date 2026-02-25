"""Dashboard pagina — KPIs en grafieken."""

from nicegui import ui
from components.layout import create_layout


@ui.page('/')
async def dashboard_page():
    create_layout('Dashboard', '/')
    with ui.column().classes('w-full p-4 max-w-6xl mx-auto'):
        ui.label('Dashboard — onder constructie').classes('text-h5')
