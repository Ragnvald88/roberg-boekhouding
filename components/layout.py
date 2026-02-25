"""Shared layout: header + sidebar navigatie voor alle pagina's."""

from nicegui import ui


def create_layout(title: str, active_page: str = ''):
    """Shared layout: header bar + sidebar navigation + content area."""

    PAGES = [
        ('Dashboard', 'dashboard', '/'),
        ('Werkdagen', 'schedule', '/werkdagen'),
        ('Facturen', 'receipt', '/facturen'),
        ('Kosten', 'payments', '/kosten'),
        ('Bank', 'account_balance', '/bank'),
        ('Jaarafsluiting', 'bar_chart', '/jaarafsluiting'),
    ]

    with ui.header().classes('bg-primary items-center'):
        ui.button(icon='menu', on_click=lambda: drawer.toggle()) \
            .props('flat color=white round')
        ui.label('TestBV Boekhouding').classes('text-h6 text-white q-ml-sm')
        ui.space()
        ui.label(title).classes('text-white')

    drawer = ui.left_drawer(value=True).classes('bg-blue-1')
    with drawer:
        ui.label('Navigatie').classes('text-subtitle2 q-mb-sm')
        for label, icon, target in PAGES:
            btn = ui.button(
                label, icon=icon,
                on_click=lambda t=target: ui.navigate.to(t)
            )
            btn.props('flat align=left no-caps').classes('w-full')
            if target == active_page:
                btn.classes('bg-blue-2')
        ui.separator().classes('q-my-md')
        ui.button(
            'Instellingen', icon='settings',
            on_click=lambda: ui.navigate.to('/instellingen')
        ).props('flat align=left no-caps').classes('w-full')
