"""Dashboard pagina — KPIs, omzetgrafiek en kostenverdeling."""

from datetime import date
from pathlib import Path

from nicegui import ui

from components.charts import cost_donut_chart, revenue_bar_chart
from components.layout import create_layout
from database import get_kpis, get_omzet_per_maand, get_uitgaven_per_categorie

DB_PATH = Path("data/boekhouding.sqlite3")

URENCRITERIUM = 1225


def format_euro(value: float) -> str:
    """Format float as Dutch euro string: € 1.234,56"""
    return f"\u20ac {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def kpi_card(label: str, value: str, icon: str, color: str = 'primary',
             extra=None):
    """Render a single KPI card.

    Args:
        label: Description text above the value.
        value: Formatted value string to display.
        icon: Material icon name.
        color: Quasar color name (primary, green, red, amber, etc.).
        extra: Optional callable that adds extra UI elements inside the card.
    """
    with ui.card().classes('q-pa-md flex-1 min-w-48'):
        with ui.row().classes('items-center no-wrap'):
            ui.icon(icon).classes(f'text-{color} text-3xl q-mr-md')
            with ui.column().classes('gap-0'):
                ui.label(label).classes('text-caption text-grey')
                ui.label(value).classes('text-h6 text-weight-bold')
        if extra:
            extra()


@ui.page('/')
async def dashboard_page():
    create_layout('Dashboard', '/')

    huidig_jaar = date.today().year
    jaren = {y: str(y) for y in range(huidig_jaar + 1, 2022, -1)}

    # Containers that will be cleared and rebuilt on year change
    kpi_container = {'ref': None}
    chart_container = {'ref': None}

    with ui.column().classes('w-full p-4 max-w-6xl mx-auto gap-4'):

        # --- Year selector ---
        with ui.row().classes('w-full items-center gap-4'):
            ui.label('Jaar:').classes('text-subtitle1')
            jaar_select = ui.select(
                jaren, value=huidig_jaar, label='Jaar',
            ).classes('w-32')

        # --- KPI cards ---
        kpi_container['ref'] = ui.row().classes(
            'w-full gap-4 flex-wrap'
        )

        # --- Charts ---
        chart_container['ref'] = ui.column().classes('w-full gap-4')

        # --- Quick actions ---
        with ui.row().classes('w-full gap-4 q-mt-md'):
            ui.button(
                'Werkdag toevoegen', icon='add_circle',
                on_click=lambda: ui.navigate.to('/werkdagen'),
            ).props('outline')
            ui.button(
                'Nieuwe factuur', icon='receipt_long',
                on_click=lambda: ui.navigate.to('/facturen'),
            ).props('outline')

    # --- Refresh logic ---

    async def refresh_dashboard():
        """Reload all KPIs and charts for the selected year."""
        jaar = jaar_select.value

        # Fetch data
        kpis = await get_kpis(DB_PATH, jaar=jaar)
        omzet_huidig = await get_omzet_per_maand(DB_PATH, jaar=jaar)
        omzet_vorig = await get_omzet_per_maand(DB_PATH, jaar=jaar - 1)
        kosten_per_cat = await get_uitgaven_per_categorie(DB_PATH, jaar=jaar)

        # --- Rebuild KPI cards ---
        kpi_row = kpi_container['ref']
        kpi_row.clear()
        with kpi_row:
            # 1. Netto-omzet
            kpi_card(
                label='Netto-omzet',
                value=format_euro(kpis['omzet']),
                icon='trending_up',
                color='primary',
            )

            # 2. Resultaat (green if positive, red if negative)
            resultaat = kpis['winst']
            kpi_card(
                label='Resultaat',
                value=format_euro(resultaat),
                icon='account_balance',
                color='green' if resultaat >= 0 else 'red',
            )

            # 3. Bedrijfslasten
            kpi_card(
                label='Bedrijfslasten',
                value=format_euro(kpis['kosten']),
                icon='payments',
            )

            # 4. Urencriterium with progress bar
            uren = kpis['uren']
            uren_voldaan = uren >= URENCRITERIUM
            uren_color = 'green' if uren_voldaan else 'amber'
            uren_pct = min(uren / URENCRITERIUM, 1.0) if URENCRITERIUM > 0 else 0

            def uren_extra():
                ui.linear_progress(
                    value=uren_pct, color=uren_color,
                ).classes('w-full q-mt-sm').props('rounded')

            kpi_card(
                label='Urencriterium',
                value=f"{uren:.0f} / {URENCRITERIUM:,} uur".replace(",", "."),
                icon='schedule',
                color=uren_color,
                extra=uren_extra,
            )

        # --- Rebuild charts ---
        chart_row = chart_container['ref']
        chart_row.clear()
        with chart_row:
            # Revenue bar chart
            with ui.card().classes('w-full'):
                ui.label(f'Omzet per maand — {jaar} vs {jaar - 1}').classes(
                    'text-subtitle1 text-bold q-mb-sm'
                )
                revenue_bar_chart(omzet_huidig, omzet_vorig, jaar)

            # Cost donut chart
            with ui.card().classes('w-full'):
                ui.label(f'Kostenverdeling {jaar}').classes(
                    'text-subtitle1 text-bold q-mb-sm'
                )
                if kosten_per_cat:
                    cost_donut_chart(kosten_per_cat)
                else:
                    ui.label('Geen uitgaven gevonden.').classes(
                        'text-grey q-pa-md'
                    )

            # Openstaande facturen indicator
            if kpis['openstaand'] > 0:
                with ui.card().classes('w-full bg-orange-1'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('warning').classes('text-orange text-2xl')
                        ui.label(
                            f"Openstaande facturen: {format_euro(kpis['openstaand'])}"
                        ).classes('text-subtitle1 text-orange')

    # Refresh on year change
    jaar_select.on_value_change(lambda _: refresh_dashboard())

    # Initial load
    await refresh_dashboard()
