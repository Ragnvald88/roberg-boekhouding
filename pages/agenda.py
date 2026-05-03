"""Agenda pagina — kalender met recurring patterns, blockers, factuur-status.

Sprint A spec: docs/superpowers/specs/2026-05-02-agenda-sprint-a-design.md

Skeleton (Task 3.2): toolbar (prev/today/next/refresh/nieuw), placeholder
grid + inspector containers, urencriterium-strip onderaan. Volledige
MonthGrid + Day-Inspector renderers komen in Task 3.3 + 3.4.
"""
from datetime import date

from nicegui import ui

from components.layout import create_layout, page_title
from database import DB_PATH
import services.agenda as agenda_svc


@ui.page('/agenda')
async def agenda_page():
    create_layout('Agenda', '/agenda')

    # Page state — mutable refs (Python closures capture, not copy)
    today = date.today()
    state = {
        'anchor': date(today.year, today.month, 1),  # eerste van maand
        'selected': today,
    }

    # Containers we update via render()
    refs: dict = {}

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-4'):
        with ui.row().classes('w-full items-center'):
            page_title('Agenda')

        # Top toolbar
        with ui.row().classes('w-full items-center gap-2'):
            refs['prev_btn'] = ui.button(icon='chevron_left') \
                .props('flat round dense color=secondary')
            refs['today_btn'] = ui.button('Vandaag').props('flat color=secondary')
            refs['next_btn'] = ui.button(icon='chevron_right') \
                .props('flat round dense color=secondary')
            refs['month_label'] = ui.label('').classes(
                'text-xl font-medium ml-2'
            )
            ui.space()
            refs['refresh_btn'] = ui.button('Ververs', icon='refresh') \
                .props('flat dense color=secondary')
            refs['new_btn'] = ui.button('Nieuwe werkdag', icon='add') \
                .props('color=primary')

        # Main grid + inspector containers (filled by render)
        with ui.row().classes('w-full gap-4 items-start'):
            refs['grid_container'] = ui.column().classes('flex-1 gap-1')
            refs['inspector_container'] = ui.column().classes('w-80 gap-2')

        # Urencriterium-projectie strip onderaan
        refs['urencrit_strip'] = ui.label('').classes(
            'text-sm text-slate-600 mt-2'
        )

    async def render():
        """Refetch data + re-render grid + inspector + urencriterium-strip."""
        anchor = state['anchor']
        view = await agenda_svc.get_maand(
            DB_PATH, jaar=anchor.year, maand=anchor.month,
        )

        # Month label (e.g. "Mei 2026")
        nl_months = [
            'januari', 'februari', 'maart', 'april', 'mei', 'juni',
            'juli', 'augustus', 'september', 'oktober', 'november', 'december',
        ]
        refs['month_label'].text = (
            f"{nl_months[anchor.month - 1].capitalize()} {anchor.year}"
        )

        # Grid placeholder (Task 3.3 vervangt door MonthGrid renderer)
        refs['grid_container'].clear()
        with refs['grid_container']:
            ui.label(
                f"[Placeholder — {len(view.dagen)} dagen, MonthGrid komt in Task 3.3]"
            ).classes('text-slate-400 italic p-4')

        # Inspector placeholder (Task 3.4 vervangt door Day-Inspector)
        refs['inspector_container'].clear()
        with refs['inspector_container']:
            with ui.card().classes('w-full p-3'):
                ui.label(state['selected'].isoformat()).classes(
                    'text-sm font-medium'
                )
                ui.label(
                    '[Placeholder — Day-Inspector komt in Task 3.4]'
                ).classes('text-slate-400 italic text-xs')

        # Urencriterium-projectie strip
        try:
            urencrit = await agenda_svc.get_urencriterium_projectie(
                DB_PATH, anchor.year,
            )
            projected = urencrit.confirmed_uren + urencrit.expected_uren_remainder
            refs['urencrit_strip'].text = (
                f"Urencriterium {urencrit.jaar}: "
                f"{urencrit.confirmed_uren:.0f}u van {urencrit.target:.0f}u "
                f"— verwacht jaar-eind: {projected:.0f}u "
                f"{'✓ Voldoet' if urencrit.will_make else '! Krap'}"
            )
        except Exception as e:
            refs['urencrit_strip'].text = f"Urencriterium: {e}"

    def go_prev():
        a = state['anchor']
        if a.month == 1:
            state['anchor'] = date(a.year - 1, 12, 1)
        else:
            state['anchor'] = date(a.year, a.month - 1, 1)
        ui.timer(0, render, once=True)

    def go_next():
        a = state['anchor']
        if a.month == 12:
            state['anchor'] = date(a.year + 1, 1, 1)
        else:
            state['anchor'] = date(a.year, a.month + 1, 1)
        ui.timer(0, render, once=True)

    def go_today():
        t = date.today()
        state['anchor'] = date(t.year, t.month, 1)
        state['selected'] = t
        ui.timer(0, render, once=True)

    refs['prev_btn'].on_click(go_prev)
    refs['next_btn'].on_click(go_next)
    refs['today_btn'].on_click(go_today)
    refs['refresh_btn'].on_click(lambda: ui.timer(0, render, once=True))

    # Initial render
    await render()
