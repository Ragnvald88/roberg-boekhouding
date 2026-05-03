"""Agenda pagina — kalender met recurring patterns, blockers, factuur-status.

Sprint A spec: docs/superpowers/specs/2026-05-02-agenda-sprint-a-design.md

Task 3.3: MonthGrid renderer met factuur-status-bars + week-summary kolom.
Day-Inspector + bevestigen-flow komen in Task 3.4.
"""
from datetime import date, timedelta

from nicegui import ui

from components.layout import create_layout, page_title
from database import DB_PATH
import services.agenda as agenda_svc


DOW_LABELS_NL = ['Ma', 'Di', 'Wo', 'Do', 'Vr', 'Za', 'Zo']
NL_MONTHS = [
    'januari', 'februari', 'maart', 'april', 'mei', 'juni',
    'juli', 'augustus', 'september', 'oktober', 'november', 'december',
]


def _start_of_week(d: date) -> date:
    """Maandag van de week waar `d` in valt."""
    return d - timedelta(days=d.isoweekday() - 1)


def _iso_week_number(d: date) -> int:
    return d.isocalendar()[1]


def _render_month_grid(container, view, on_day_click, selected: date) -> None:
    """Render 6×7 day grid + week-summary kolom rechts.

    view: MaandView from services.agenda.get_maand
    on_day_click: callback(date) → set state['selected'], rerender
    selected: currently selected date (for highlight)
    """
    container.clear()
    first = date(view.jaar, view.maand, 1)
    grid_start = _start_of_week(first)
    today = date.today()

    # DagView lookup by datum (only voor dagen IN de maand — outer-month
    # dagen hebben geen werkdag/expected/blocker data via get_maand, render
    # leeg).
    dagen_by_datum = {d.datum: d for d in view.dagen}

    with container:
        # Header row (DOW labels + Week label)
        with ui.row().classes('w-full gap-1 mb-1'):
            for label in DOW_LABELS_NL:
                weekend_cls = ' text-slate-400' if label in ('Za', 'Zo') else ''
                ui.label(label).classes(
                    f'flex-1 text-xs font-semibold text-slate-500'
                    f' uppercase px-2 py-1{weekend_cls}'
                ).style('text-align: center; min-width: 0;')
            ui.label('Week').classes(
                'w-24 text-xs font-semibold text-slate-500 uppercase px-2 py-1'
            ).style('text-align: center;')

        # 6 weeks
        for w in range(6):
            with ui.row().classes('w-full gap-1'):
                week_total_amt = 0.0
                week_dagen_count = 0
                for i in range(7):
                    d = grid_start + timedelta(days=w * 7 + i)
                    dag = dagen_by_datum.get(d)
                    is_other = d.month != view.maand
                    is_today = d == today
                    is_selected = d == selected
                    is_weekend = d.isoweekday() >= 6

                    cell_classes = ['agenda-cell', 'flex-1']
                    if is_other:
                        cell_classes.append('other-month')
                    if is_weekend:
                        cell_classes.append('weekend')
                    if is_today:
                        cell_classes.append('today')
                    if is_selected:
                        cell_classes.append('selected')
                    if dag and dag.blocker and dag.blocker.kind != 'holiday':
                        cell_classes.append(f'blocker-{dag.blocker.kind}')
                    if dag and dag.blocker and dag.blocker.kind == 'holiday':
                        cell_classes.append('holiday-marker')

                    cell = ui.element('div').classes(' '.join(cell_classes)) \
                        .style('min-width: 0;')
                    cell.on('click', lambda _e=None, dt=d: on_day_click(dt))
                    with cell:
                        # Day number (top-left)
                        ui.label(str(d.day)).classes('agenda-cell-day')

                        # Holiday label (only for holiday-blocker)
                        if dag and dag.blocker and dag.blocker.kind == 'holiday':
                            ui.label(dag.blocker.label).classes('holiday-label')
                        # User-blocker label
                        elif dag and dag.blocker:
                            ui.label(
                                dag.blocker.label or dag.blocker.kind.capitalize()
                            ).classes('text-[10px] text-slate-600')

                        if dag and not dag.blocker:
                            # Combine werkdagen + expected (max 3 visible)
                            all_pills = list(dag.werkdagen) + list(dag.expected)
                            for pill in all_pills[:3]:
                                pill_classes = ['wd-pill', f'wd-{pill.category}']
                                # ExpectedEntry has pattern_id; WerkdagPill
                                # does not — distinguish via attribute presence.
                                if hasattr(pill, 'pattern_id'):
                                    pill_classes.append('expected')
                                with ui.element('div').classes(
                                    ' '.join(pill_classes)
                                ):
                                    klant_short = pill.klant_naam[:10]
                                    ui.label(
                                        f'{klant_short} {pill.uren:.1f}u'
                                    )
                            if len(all_pills) > 3:
                                ui.label(f'+{len(all_pills) - 3} meer').classes(
                                    'agenda-cell-overflow'
                                )

                            # Status-bars onderaan (alleen voor confirmed werkdagen)
                            if dag.werkdagen:
                                with ui.element('div').classes('wd-status-bar'):
                                    for pill in dag.werkdagen:
                                        ui.element('span').classes(
                                            f'status-{pill.status_label}'
                                        )

                        # Accumulate week-summary data (alleen confirmed)
                        if dag and dag.werkdagen:
                            for pill in dag.werkdagen:
                                week_total_amt += pill.bedrag
                            week_dagen_count += 1

                # Week-summary kolom (rechts)
                week_start_date = grid_start + timedelta(days=w * 7)
                wnum = _iso_week_number(week_start_date)
                is_current_week = (
                    week_start_date <= today
                    < week_start_date + timedelta(days=7)
                )
                ws_classes = ['week-summary', 'w-24']
                if is_current_week:
                    ws_classes.append('current')
                with ui.element('div').classes(' '.join(ws_classes)):
                    ui.label(f'W{wnum}').classes('week-summary-num')
                    if week_total_amt > 0:
                        ui.label(f'€ {week_total_amt:,.0f}'.replace(',', '.')) \
                            .classes('week-summary-amt')
                        ui.label(
                            f'{week_dagen_count} dgn'
                        ).classes('week-summary-meta')


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

    def select_day(d: date) -> None:
        """Click-handler voor agenda-cell. Wisselt naar maand van d indien
        outer-month klik."""
        state['selected'] = d
        if d.month != state['anchor'].month or d.year != state['anchor'].year:
            state['anchor'] = date(d.year, d.month, 1)
        ui.timer(0, render, once=True)

    async def render():
        """Refetch data + re-render grid + inspector + urencriterium-strip."""
        anchor = state['anchor']
        view = await agenda_svc.get_maand(
            DB_PATH, jaar=anchor.year, maand=anchor.month,
        )

        # Month label (e.g. "Mei 2026")
        refs['month_label'].text = (
            f"{NL_MONTHS[anchor.month - 1].capitalize()} {anchor.year}"
        )

        _render_month_grid(
            refs['grid_container'], view,
            on_day_click=select_day,
            selected=state['selected'],
        )

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
