"""Shared layout: header + sidebar navigatie + theming."""

from nicegui import ui

# === Global component defaults ===
ui.card.default_props('flat bordered')
ui.card.default_classes('rounded-xl')
ui.button.default_props('unelevated no-caps')
ui.input.default_props('outlined dense')
ui.number.default_props('outlined dense')
ui.select.default_props('outlined dense')
ui.table.default_props('flat bordered separator=horizontal')

# === Global shared CSS ===
ui.add_css('''
@layer components {
    /* Table header styling */
    .q-table th {
        background-color: #F1F5F9;
        font-weight: 600;
        text-transform: uppercase;
        font-size: 0.7rem;
        letter-spacing: 0.05em;
        color: #475569;
    }
    .q-table tbody tr:nth-child(even) {
        background-color: #F8FAFC;
    }

    /* KPI card hover */
    .kpi-card {
        transition: box-shadow 0.2s ease;
    }
    .kpi-card:hover {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
    }

    /* Sidebar nav button active state */
    .nav-active {
        background-color: rgba(20, 184, 166, 0.15) !important;
        color: #14B8A6 !important;
        font-weight: 600;
    }

    /* Sidebar nav button hover */
    .nav-btn:hover {
        background-color: rgba(255, 255, 255, 0.05) !important;
    }
}
''', shared=True)


def create_layout(title: str, active_page: str = ''):
    """Shared layout: teal header, dark sidebar, off-white content."""

    PAGES = [
        ('DAGELIJKS', None, None),  # section header
        ('Dashboard', 'dashboard', '/'),
        ('Werkdagen', 'schedule', '/werkdagen'),
        ('Facturen', 'receipt', '/facturen'),
        ('FINANCIEEL', None, None),  # section header
        ('Kosten', 'payments', '/kosten'),
        ('Bank', 'account_balance', '/bank'),
        ('JAAREINDE', None, None),  # section header
        ('Jaarafsluiting', 'bar_chart', '/jaarafsluiting'),
        ('Aangifte', 'fact_check', '/aangifte'),
    ]

    # Brand colors
    ui.colors(
        primary='#0F766E',
        secondary='#475569',
        accent='#F59E0B',
        positive='#059669',
        negative='#DC2626',
        info='#2563EB',
        warning='#D97706',
    )

    # Off-white page background
    ui.query('body').style('background-color: #F8FAFC')

    # === Header ===
    with ui.header().classes('items-center shadow-sm') \
            .style('background-color: #0F172A'):
        ui.button(icon='menu', on_click=lambda: drawer.toggle()) \
            .props('flat color=white round dense')
        ui.label('Boekhouding').classes('text-h6 text-white q-ml-sm')
        ui.space()
        ui.label(title).classes('text-subtitle1').style('color: #CBD5E1')

    # === Dark sidebar ===
    drawer = ui.left_drawer(value=True, bordered=False) \
        .style('background-color: #0F172A') \
        .props('width=240')

    with drawer:
        for label, icon, target in PAGES:
            if target is None:
                # Section header
                ui.label(label) \
                    .classes('text-xs q-mt-lg q-mb-sm q-ml-md') \
                    .style('color: #64748B; letter-spacing: 0.1em')
                continue

            is_active = (target == active_page)
            btn = ui.button(
                label, icon=icon,
                on_click=lambda t=target: ui.navigate.to(t)
            )
            btn.props('flat align=left no-caps')
            btn.classes('w-full rounded-lg q-mb-xs')
            if is_active:
                btn.classes('nav-active')
            else:
                btn.classes('nav-btn').style('color: #CBD5E1')

        # Separator + settings
        ui.separator().classes('q-my-md').style('background-color: #1E293B')

        settings_active = active_page == '/instellingen'
        settings_btn = ui.button(
            'Instellingen', icon='settings',
            on_click=lambda: ui.navigate.to('/instellingen')
        ).props('flat align=left no-caps').classes('w-full rounded-lg')
        if settings_active:
            settings_btn.classes('nav-active')
        else:
            settings_btn.classes('nav-btn').style('color: #CBD5E1')
