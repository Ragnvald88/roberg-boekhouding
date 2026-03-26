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

    /* Page toolbar — tinted bar with pill-shaped filters */
    .page-toolbar {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 14px;
        background: #EDF2F7;
        border-radius: 12px;
    }
    .page-toolbar .q-field { min-height: unset; }

    /* White pill selects inside toolbar */
    .page-toolbar .q-field--outlined .q-field__control {
        background: white !important;
        border-color: transparent !important;
        border-radius: 20px !important;
        min-height: 36px !important;
        transition: box-shadow 0.15s ease;
    }
    .page-toolbar .q-field--outlined .q-field__control:hover {
        box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    }
    .page-toolbar .q-field--outlined.q-field--focused .q-field__control {
        border-color: var(--q-primary) !important;
        box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.12);
    }
    .page-toolbar .q-field__label {
        font-size: 11px !important;
    }

    .toolbar-divider {
        width: 1px;
        height: 24px;
        background: #CBD5E1;
        flex-shrink: 0;
    }

    /* Invoice builder panel styling */
    .builder-panel-border { border-right: 1px solid var(--q-separator-color, #e2e8f0); }
    .builder-line-card { border: 1px solid var(--q-separator-color, #e2e8f0); box-shadow: none; }
    .builder-preview-bg { background: var(--q-separator-color, #e2e8f0); }

    /* KPI card hover */
    .kpi-card {
        transition: box-shadow 0.2s ease;
    }
    .kpi-card:hover {
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
    }

    /* Sidebar nav — clean minimal style */
    .nav-item {
        display: flex; align-items: center; gap: 10px;
        padding: 7px 14px; margin: 1px 8px;
        border-radius: 6px; cursor: pointer;
        color: #94A3B8; font-size: 13px; font-weight: 400;
        transition: all 0.15s;
        text-decoration: none; border: none; background: none;
        width: calc(100% - 16px);
    }
    .nav-item:hover { background: rgba(255,255,255,0.06); color: #E2E8F0; }
    .nav-item .nav-icon { font-size: 18px; width: 20px; text-align: center; }

    .nav-item.active {
        color: #5EEAD4;
        background: rgba(94,234,212,0.08);
        font-weight: 500;
        border-left: 3px solid #14B8A6;
        margin-left: 5px;
        padding-left: 11px;
    }

    .nav-gap { height: 12px; }
    .nav-divider { height: 1px; background: #1E293B; margin: 8px 16px; }

    /* Dashboard design tokens */
    .hero-label { font-size: 13px; color: #64748B; font-weight: 500; }
    .hero-value { font-size: 30px; font-weight: 700; color: #0F172A;
                  font-variant-numeric: tabular-nums; margin: 6px 0 2px; }
    .hero-value-positive { font-size: 30px; font-weight: 700; color: var(--q-positive);
                           font-variant-numeric: tabular-nums; margin: 6px 0 2px; }
    .hero-value-negative { font-size: 30px; font-weight: 700; color: var(--q-negative);
                           font-variant-numeric: tabular-nums; margin: 6px 0 2px; }
    .context-text { font-size: 12px; color: #94A3B8; }
    .section-label { font-size: 13px; font-weight: 600; color: #64748B;
                     text-transform: uppercase; letter-spacing: 0.05em; }
    .chart-title { font-size: 15px; font-weight: 600; color: #0F172A; }
    .chart-subtitle { font-size: 12px; color: #94A3B8; }
    .strip-value { font-size: 14px; font-weight: 600; color: #0F172A; }
    .strip-pct { font-size: 11px; color: #94A3B8; }
    .card-hero { border-radius: 14px; border: 1px solid #E2E8F0; }
}
''', shared=True)


def page_title(text: str):
    """Render a consistent page title label."""
    return ui.label(text).classes('text-h5') \
        .style('color: #0F172A; font-weight: 700')


def create_layout(title: str, active_page: str = ''):
    """Shared layout: teal header, dark sidebar, off-white content."""

    # Navigation groups (separated by whitespace, no headers)
    NAV_GROUPS = [
        [('Dashboard', 'space_dashboard', '/'),
         ('Werkdagen', 'event_note', '/werkdagen')],
        [('Facturen', 'receipt_long', '/facturen'),
         ('Kosten', 'shopping_bag', '/kosten'),
         ('Bank', 'account_balance_wallet', '/bank')],
        [('Documenten', 'folder_open', '/documenten'),
         ('Jaarafsluiting', 'assessment', '/jaarafsluiting'),
         ('Aangifte', 'assignment', '/aangifte')],
    ]
    SETUP_PAGES = [
        ('Klanten', 'people_outline', '/klanten'),
        ('Instellingen', 'tune', '/instellingen'),
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
        .props('width=180')

    def _nav_item(label, icon, target):
        """Render a single nav item with active state."""
        is_active = (target == active_page
                     or target.split('?')[0] == active_page)
        cls = 'nav-item active' if is_active else 'nav-item'
        with ui.element('div').classes(cls) \
                .on('click', lambda t=target: ui.navigate.to(t)):
            ui.icon(icon).classes('nav-icon')
            ui.label(label)

    with drawer:
        ui.element('div').style('height: 12px')  # top spacing

        for i, group in enumerate(NAV_GROUPS):
            if i > 0:
                ui.element('div').classes('nav-gap')
            for label, icon, target in group:
                _nav_item(label, icon, target)

        ui.element('div').classes('nav-divider')

        for label, icon, target in SETUP_PAGES:
            _nav_item(label, icon, target)
