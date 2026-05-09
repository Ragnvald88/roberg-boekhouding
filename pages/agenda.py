"""Agenda pagina — kalender met recurring patterns, blockers, factuur-status.

Sprint A spec: docs/superpowers/specs/2026-05-02-agenda-sprint-a-design.md

Task 3.3: MonthGrid renderer met factuur-status-bars + week-summary kolom.
Task 3.4: Day-Inspector met states (empty/blocker/holiday/expected/confirmed).
Werkdag-dialog hookup komt in Task 4.1.
"""
from datetime import date, timedelta

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import contrast_text_color
from database import DB_PATH, get_bedrijfsgegevens, YearLockedError
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


def _pill_color_style(klant_color: str | None,
                       gebruik_klant_kleur: bool) -> str:
    """Pure helper: returns inline-style string voor klant-color overlay
    op .wd-pill, of '' als geen overlay van toepassing is.

    Defensief (Codex risk #1): alleen overlay als (1) toggle aan staat,
    (2) klant_color is non-None, (3) hex format klopt (#RRGGBB), (4)
    contrast_text_color slaagt. Bij elke afwijking: lege string → pill
    valt terug op type-based .wd-{category} styling. Holidays/blockers
    renderen geen pills, dus dit raakt nooit niet-klant-gebonden cellen.

    Pure signature (Sprint D S4): accepteert losse `klant_color` ipv
    een pill-object → mock-vrij testbaar.
    """
    if not gebruik_klant_kleur:
        return ''
    if klant_color is None:
        return ''
    if not isinstance(klant_color, str):
        return ''
    if len(klant_color) != 7 or not klant_color.startswith('#'):
        return ''
    try:
        text_color = contrast_text_color(klant_color)
    except ValueError:
        return ''  # malformed hex — skip overlay, type-based fallback
    return f'background: {klant_color}; color: {text_color};'


def _pill_context_actions(pill) -> list[str]:
    """Pure helper: geeft action-IDs terug voor right-click context-menu
    op een confirmed werkdag-pill.

    Action-IDs zijn stabiele strings (renderer mapt naar labels/icons/
    callbacks). Volgorde is deterministic.

    Visibility-rules (zie spec 2026-05-08-agenda-sprint-1-design.md §C):
    - edit, duplicate: altijd
    - delete: alleen als geen factuurnummer
    - naar_facturen: alleen als factuur_id != None
    - ontkoppel: alleen bij concept of orphan-link
        (factuurnummer != '' EN (factuur_id is None OF
         factuur_status == 'concept'))

    Onbekende factuur_status met factuur_id != None gedraagt zich
    defensief: wel naar_facturen, geen ontkoppel/delete.
    """
    actions = ['edit', 'duplicate']
    has_factuurnummer = bool(getattr(pill, 'factuurnummer', '') or '')
    factuur_id = getattr(pill, 'factuur_id', None)
    factuur_status = getattr(pill, 'factuur_status', '') or ''

    if not has_factuurnummer:
        actions.append('delete')
        return actions

    # Heeft factuurnummer.
    if factuur_id is not None:
        actions.append('naar_facturen')

    # Ontkoppel: orphan (factuur_id None) OF concept-factuur.
    if factuur_id is None or factuur_status == 'concept':
        actions.append('ontkoppel')

    return actions


def _pill_tooltip(pill) -> str:
    """Pure helper: tooltip-tekst voor confirmed werkdag-pill.

    Format:
        {klant_naam_volledig}
        {uren:.1f}u · €{bedrag:,.2f}
        Status: {status_label}{factuur_extra}

    Factuur-extra:
        - concept → " · concept-factuur {nummer}"
        - verstuurd/verlopen/betaald → " · Factuur {nummer}"
        - ongefactureerd → ""

    Geen tijden — werkdagen-tabel slaat geen start/eind times op
    (spec §D: schema-change buiten Sprint 1).
    """
    klant = getattr(pill, 'klant_naam', '') or ''
    uren = float(getattr(pill, 'uren', 0) or 0)
    bedrag = float(getattr(pill, 'bedrag', 0) or 0)
    status = getattr(pill, 'status_label', '') or ''
    factuurnummer = getattr(pill, 'factuurnummer', '') or ''

    bedrag_fmt = f'{bedrag:,.2f}'.replace(',', 'X').replace('.', ',') \
        .replace('X', '.')

    factuur_extra = ''
    if factuurnummer:
        if status == 'concept':
            factuur_extra = f' · concept-factuur {factuurnummer}'
        elif status in ('verstuurd', 'verlopen', 'betaald'):
            factuur_extra = f' · Factuur {factuurnummer}'
        else:
            # Orphan-link: werkdag heeft factuurnummer maar geen
            # matching factuur-row (status_label='ongefactureerd' via
            # derive_werkdag_status_label). Context-menu biedt
            # "Ontkoppel factuur" aan — zonder dit branche zou de
            # tooltip die actie als verwarrend laten lijken (codex
            # final review).
            factuur_extra = f' · orphan-link {factuurnummer}'

    return (
        f'{klant}\n'
        f'{uren:.1f}u · €{bedrag_fmt}\n'
        f'Status: {status}{factuur_extra}'
    )


_CTX_MENU_LABELS = {
    'edit': 'Bewerken',
    'duplicate': 'Dupliceren',
    'delete': 'Verwijderen',
    'naar_facturen': 'Naar facturen',
    'ontkoppel': 'Ontkoppel factuur',
}


def _render_context_menu_item(action_id, pill, on_edit, on_duplicate,
                              on_delete, on_ontkoppel, on_naar_facturen):
    """Render één q-item in de pill context-menu, gemapt op action_id.

    NiceGUI 3.8.0 `ui.menu_item(text, on_click=..., auto_close=True)`
    rendert als clickable q-item met v-close-popup. Geen icon — Sprint 1
    KISS, plain text labels matchen de minimalistische agenda-pill UI.
    """
    label = _CTX_MENU_LABELS[action_id]
    handler_map = {
        'edit': on_edit,
        'duplicate': on_duplicate,
        'delete': on_delete,
        'ontkoppel': on_ontkoppel,
        'naar_facturen': on_naar_facturen,
    }
    handler = handler_map[action_id]
    if handler is None:
        return
    if action_id == 'naar_facturen':
        arg = getattr(pill, 'factuur_id', None)
    else:
        arg = pill.id
    ui.menu_item(label, on_click=lambda _e=None, a=arg: handler(a))


def _render_month_grid(container, view, on_day_click, selected: date,
                        gebruik_klant_kleur: bool = False,
                        on_pill_edit=None, on_pill_duplicate=None,
                        on_pill_delete=None, on_pill_ontkoppel=None,
                        on_pill_naar_facturen=None) -> None:
    """Render 6×7 day grid + week-summary kolom rechts.

    view: MaandView from services.agenda.get_maand
    on_day_click: callback(date) → set state['selected'], rerender
    selected: currently selected date (for highlight)
    gebruik_klant_kleur: Sprint D — bedrijfsgegevens-toggle. Als True en
        pill.klant_color is een geldig #RRGGBB → render pill met klant-
        kleur background; anders type-based .wd-{category} styling.

    on_pill_*: callbacks voor confirmed pill-acties. None → geen handler
        (test/legacy fallback). Expected pills krijgen geen pill-handlers —
        bubblen naar cell-click voor Day-Inspector flow.
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

                        if dag:
                            # Holiday/blocker: alleen bevestigde werkdagen tonen
                            # (expected entries zijn al onderdrukt door get_maand
                            # wanneer dag.blocker is gezet). User-blocker met
                            # bevestigde werkdag = vakantie + extra dienst:
                            # tonen beide.
                            if dag.blocker:
                                all_pills = list(dag.werkdagen)  # geen expected
                            else:
                                all_pills = list(dag.werkdagen) + list(dag.expected)
                            for pill in all_pills[:3]:
                                pill_classes = ['wd-pill', f'wd-{pill.category}']
                                # ExpectedEntry has pattern_id; WerkdagPill
                                # does not — distinguish via attribute presence.
                                is_expected = hasattr(pill, 'pattern_id')
                                if is_expected:
                                    pill_classes.append('expected')
                                # Sprint D: defensieve klant-color overlay
                                # (alleen op werkdag/expected pills, NIET op
                                # blocker/holiday cellen — die renderen geen
                                # pills via deze loop).
                                pill_style = _pill_color_style(
                                    getattr(pill, 'klant_color', None),
                                    gebruik_klant_kleur,
                                )
                                pill_el = ui.element('div').classes(
                                    ' '.join(pill_classes)
                                ).style(pill_style)
                                with pill_el:
                                    klant_short = pill.klant_naam[:10]
                                    ui.label(
                                        f'{klant_short} {pill.uren:.1f}u'
                                    )
                                    # Tooltip + click + context-menu alleen
                                    # voor confirmed pills (NIET expected).
                                    if not is_expected:
                                        tooltip_text = _pill_tooltip(pill)
                                        # Quasar QTooltip default
                                        # white-space: normal collapseert
                                        # \n. pre-line preserveert de
                                        # 3-regel layout uit _pill_tooltip.
                                        ui.tooltip(tooltip_text).style(
                                            'white-space: pre-line')
                                        if on_pill_edit is not None:
                                            wid = pill.id
                                            pill_el.on(
                                                'click',
                                                lambda _e=None,
                                                       w=wid: on_pill_edit(w),
                                                js_handler=(
                                                    '(e) => { '
                                                    'e.stopPropagation(); '
                                                    'emit(); }'),
                                            )
                                        # Context-menu (right-click) — alleen
                                        # renderen wanneer er minstens één
                                        # handler is gewired (test/legacy
                                        # fallback met alle callbacks=None
                                        # zou anders een lege q-menu attachen
                                        # op elke pill — codex review I1).
                                        any_handler = any(h is not None for h in (
                                            on_pill_edit, on_pill_duplicate,
                                            on_pill_delete, on_pill_ontkoppel,
                                            on_pill_naar_facturen,
                                        ))
                                        if any_handler:
                                            action_ids = _pill_context_actions(pill)
                                            with ui.context_menu():
                                                for aid in action_ids:
                                                    _render_context_menu_item(
                                                        aid, pill,
                                                        on_pill_edit,
                                                        on_pill_duplicate,
                                                        on_pill_delete,
                                                        on_pill_ontkoppel,
                                                        on_pill_naar_facturen,
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


def _format_short_date(iso_str):
    """Format YYYY-MM-DD as 'D MMM' (e.g. '15 mei')."""
    try:
        d = date.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return iso_str
    return f'{d.day} {NL_MONTHS[d.month - 1][:3]}'


def _render_blocker_section(dag, on_add_werkdag, on_delete_blocker):
    blocker = dag.blocker
    kind = blocker.kind
    icon_name = {
        'holiday': 'celebration',
        'vacation': 'beach_access',
        'sick': 'sick',
        'training': 'school',
    }.get(kind, 'event_busy')
    kind_label = {
        'holiday': 'Feestdag',
        'vacation': 'Vakantie',
        'sick': 'Ziek',
        'training': 'Nascholing',
    }.get(kind, kind.capitalize())

    with ui.row().classes('items-center gap-2 mt-3'):
        ui.icon(icon_name).classes('text-2xl').style('color: var(--muted)')
        with ui.column().classes('gap-0 flex-1'):
            ui.label(kind_label).classes('text-sm font-medium')
            if blocker.label:
                ui.label(blocker.label).classes('text-xs text-slate-500')

    if kind == 'holiday':
        with ui.row().classes('mt-3'):
            ui.button(
                'Werkdag plannen', icon='add',
                on_click=lambda: on_add_werkdag(dag.datum),
            ).props('flat color=primary dense')
    else:
        with ui.row().classes('mt-3'):
            ui.button(
                'Verwijderen', icon='delete',
                on_click=lambda: on_delete_blocker(blocker.id),
            ).props('flat color=negative dense')


def _render_confirmed_section(dag, on_open_factuur, on_create_factuur,
                              on_add_werkdag):
    """Render bevestigde werkdagen op deze datum."""
    nog_te_factureren_ids = []

    for w in dag.werkdagen:
        with ui.card().classes('w-full p-2 mt-2 q-mt-sm'):
            with ui.row().classes('items-baseline justify-between'):
                ui.label(w.klant_naam).classes('text-sm font-medium')
                ui.label(f'{w.uren:.1f}u').classes(
                    'text-xs text-slate-500'
                )
            ui.label(
                f'€ {w.bedrag:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
            ).classes('text-xs text-slate-600 mt-1')

            # Status-chip
            chip_color = {
                'ongefactureerd': 'grey-7',
                'concept': 'grey',
                'verstuurd': 'blue',
                'verlopen': 'red',
                'betaald': 'green',
            }.get(w.status_label, 'grey')
            chip_label = {
                'ongefactureerd': 'Ongefactureerd',
                'concept': 'Concept',
                'verstuurd': 'Verstuurd',
                'verlopen': 'Verlopen',
                'betaald': 'Betaald',
            }.get(w.status_label, w.status_label)

            with ui.row().classes('items-center gap-2 mt-2'):
                ui.badge(chip_label, color=chip_color)
                if w.status_label == 'verlopen' and w.overdue_days > 0:
                    ui.label(
                        f'{w.overdue_days} dgn te laat'
                    ).classes('text-xs').style('color: var(--q-negative)')
                if w.status_label == 'betaald' and w.factuur_betaald_datum:
                    ui.label(
                        f'op {_format_short_date(w.factuur_betaald_datum)}'
                    ).classes('text-xs text-slate-500')

            # Factuur-link
            if w.factuurnummer and w.factuur_id:
                with ui.row().classes('mt-2'):
                    ui.button(
                        f'Factuur {w.factuurnummer}', icon='receipt',
                        on_click=lambda _e=None, fid=w.factuur_id:
                            on_open_factuur(fid),
                    ).props('flat dense color=primary').classes('text-xs')

            if not w.factuurnummer:
                nog_te_factureren_ids.append(w.id)

    # Footer: Maak factuur knop bij ongefactureerde werkdagen
    if nog_te_factureren_ids:
        with ui.row().classes('mt-3'):
            ui.button(
                'Maak factuur', icon='receipt_long',
                on_click=lambda: on_create_factuur(nog_te_factureren_ids),
            ).props('color=primary outline')

    # Extra werkdag toevoegen op zelfde datum (multi-shifts)
    with ui.row().classes('mt-3'):
        ui.button(
            'Extra werkdag', icon='add',
            on_click=lambda: on_add_werkdag(dag.datum),
        ).props('flat color=secondary dense')


def _render_expected_section(dag, on_confirm_expected, on_add_werkdag):
    """Render verwachte werkdag-entries (uit recurring patterns)."""
    ui.label(
        f'{len(dag.expected)} verwachte werkdag'
        f"{'en' if len(dag.expected) > 1 else ''}"
        ' uit vast rooster'
    ).classes('text-xs text-slate-500 mt-2')

    for e in dag.expected:
        with ui.card().classes('w-full p-2 mt-2 bg-slate-50'):
            ui.label('Verwacht via vast rooster').classes(
                'text-[10px] uppercase text-slate-400 tracking-wider'
            )
            with ui.row().classes('items-baseline justify-between mt-1'):
                ui.label(e.klant_naam).classes('text-sm font-medium')
                ui.label(f'{e.uren:.1f}u').classes(
                    'text-xs text-slate-500'
                )
            tijd = (
                f'{e.start_minuten // 60:02d}:'
                f'{e.start_minuten % 60:02d}'
                f'–'
                f'{e.eind_minuten // 60:02d}:'
                f'{e.eind_minuten % 60:02d}'
            )
            ui.label(
                f'{tijd} · € {e.bedrag:,.2f}'.replace(',', 'X')
                .replace('.', ',').replace('X', '.')
            ).classes('text-xs text-slate-600 mt-1')

            with ui.row().classes('mt-2 gap-1'):
                ui.button(
                    'Bevestigen', icon='check',
                    on_click=lambda _e=None, ent=e: on_confirm_expected(ent),
                ).props('color=primary dense')
                ui.button(
                    'Aanpassen', icon='edit',
                    on_click=lambda _e=None, ent=e: on_add_werkdag(
                        dag.datum, prefill_pattern=ent,
                    ),
                ).props('flat dense')


def _render_day_inspector(container, dag, on_add_werkdag, on_add_blocker,
                          on_delete_blocker, on_confirm_expected,
                          on_open_factuur, on_create_factuur):
    """Render day-inspector card based on DagView state."""
    container.clear()
    today = date.today()
    is_past = dag.datum < today

    nl_dag_names = ['maandag', 'dinsdag', 'woensdag', 'donderdag',
                    'vrijdag', 'zaterdag', 'zondag']
    weekday_label = nl_dag_names[dag.datum.isoweekday() - 1].capitalize()
    formatted_date = (
        f"{weekday_label} {dag.datum.day} "
        f"{NL_MONTHS[dag.datum.month - 1]} {dag.datum.year}"
    )

    with container:
        with ui.card().classes('w-full p-3'):
            ui.label(formatted_date).classes(
                'text-base font-medium'
            ).style('color: var(--text)')

            # ====== BLOCKER (holiday or user) ======
            if dag.blocker:
                _render_blocker_section(
                    dag, on_add_werkdag, on_delete_blocker,
                )
                # Geen early return: user kan bevestigde werkdag op
                # holiday/blocker hebben (bv. extra dienst op vrije dag).
                if dag.werkdagen:
                    ui.separator().classes('q-my-md')

            # ====== CONFIRMED WERKDAGEN ======
            if dag.werkdagen:
                _render_confirmed_section(
                    dag, on_open_factuur, on_create_factuur,
                    on_add_werkdag,
                )
                return

            # ====== EXPECTED (recurring, future only) — onderdrukt door blocker ======
            if dag.blocker:
                # We've already shown the blocker. No expected entries here.
                return

            if dag.expected:
                _render_expected_section(
                    dag, on_confirm_expected, on_add_werkdag,
                )
                return

            # ====== EMPTY ======
            if is_past:
                ui.label('Geen registratie op deze dag').classes(
                    'text-slate-500 mt-2'
                )
            else:
                ui.label('Geen registratie').classes(
                    'text-slate-500 mt-2'
                )
                with ui.row().classes('gap-2 mt-2 flex-wrap'):
                    ui.button(
                        'Werkdag', icon='add',
                        on_click=lambda: on_add_werkdag(dag.datum),
                    ).props('color=primary outline dense')
                    ui.button(
                        'Vakantie', icon='beach_access',
                        on_click=lambda: on_add_blocker(dag.datum, 'vacation'),
                    ).props('outline dense color=info')
                    ui.button(
                        'Ziek', icon='sick',
                        on_click=lambda: on_add_blocker(dag.datum, 'sick'),
                    ).props('outline dense color=warning')
                    ui.button(
                        'Nascholing', icon='school',
                        on_click=lambda: on_add_blocker(dag.datum, 'training'),
                    ).props('outline dense color=accent')


@ui.page('/agenda')
async def agenda_page():
    create_layout('Werkdagen', '/agenda')

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
            page_title('Werkdagen')

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
            refs['list_view_btn'] = ui.button(
                'Lijstweergave', icon='list',
                on_click=lambda: ui.navigate.to('/werkdagen'),
            ).props('flat color=secondary')
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

    async def handle_add_werkdag(d, prefill_pattern=None):
        """Open werkdag-dialog met prefill (datum + optionele pattern).

        prefill_pattern is een ExpectedEntry uit /agenda Day-Inspector.
        Bij Bevestigen-knop: prefill_pattern is gezet → save() roept
        confirm_expected aan (atomic + idempotent).
        Bij "Werkdag toevoegen"-knop op lege dag: prefill_pattern=None →
        save() roept add_werkdag aan met user-input.
        """
        from components.werkdag_form import open_werkdag_dialog
        prefill = {'datum': d.isoformat()}
        if prefill_pattern is not None:
            prefill.update({
                'klant_id': prefill_pattern.klant_id,
                'start_minuten': prefill_pattern.start_minuten,
                'eind_minuten': prefill_pattern.eind_minuten,
                'activiteit': prefill_pattern.activiteit,
                'pattern_id': prefill_pattern.pattern_id,
            })
        await open_werkdag_dialog(on_save=render, prefill=prefill)

    async def handle_add_blocker(d, kind):
        try:
            await agenda_svc.add_blocker(
                DB_PATH, datum=d, kind=kind, label=kind.capitalize(),
            )
            ui.notify('Blocker toegevoegd', type='positive')
            await render()
        except Exception as exc:
            ui.notify(str(exc), type='warning')

    async def handle_delete_blocker(blocker_id):
        try:
            await agenda_svc.delete_blocker(DB_PATH, blocker_id)
            ui.notify('Blocker verwijderd', type='positive')
            await render()
        except Exception as exc:
            ui.notify(str(exc), type='warning')

    async def handle_confirm_expected(entry):
        try:
            await agenda_svc.confirm_expected(
                DB_PATH, pattern_id=entry.pattern_id,
                datum=state['selected'],
            )
            ui.notify('Werkdag bevestigd', type='positive')
            await render()
        except Exception as exc:
            ui.notify(str(exc), type='warning')

    def handle_open_factuur(factuur_id):
        """Navigate to /facturen list. Sprint A: geen deep-link naar specifieke
        factuur-rij — de gebruiker scrollt/zoekt zelf in de tabel. Latere sprint
        kan ?factuur_id=X support toevoegen (scrollIntoView + highlight)."""
        ui.navigate.to('/facturen')

    def handle_create_factuur(werkdag_ids):
        ids_csv = ','.join(str(i) for i in werkdag_ids)
        ui.navigate.to(f'/facturen?nieuw=1&werkdagen={ids_csv}')

    async def handle_pill_edit(werkdag_id):
        from database import get_werkdag_by_id
        from components.werkdag_form import open_werkdag_dialog
        w = await get_werkdag_by_id(DB_PATH, werkdag_id=werkdag_id)
        if w is None:
            ui.notify('Werkdag niet gevonden', type='warning')
            return
        await open_werkdag_dialog(on_save=render, werkdag=w)

    async def handle_pill_duplicate(werkdag_id):
        from database import get_werkdag_by_id, duplicate_werkdag
        from components.shared_ui import date_input
        w = await get_werkdag_by_id(DB_PATH, werkdag_id=werkdag_id)
        if w is None:
            ui.notify('Werkdag niet gevonden', type='warning')
            return
        # Default-target: bron-datum + 7 dagen.
        try:
            src_d = date.fromisoformat(w.datum)
            default_target = (src_d + timedelta(days=7)).isoformat()
        except (ValueError, TypeError):
            default_target = date.today().isoformat()

        with ui.dialog() as dlg, ui.card():
            ui.label(
                f'Werkdag van {w.datum} ({w.klant_naam}) dupliceren'
            ).classes('text-base font-medium')
            target = date_input(
                'Naar datum', value=default_target,
            )
            with ui.row().classes('justify-end gap-2 mt-3'):
                ui.button('Annuleren', on_click=lambda: dlg.submit(None)) \
                    .props('flat')
                ui.button('Dupliceren',
                          on_click=lambda: dlg.submit(target.value)) \
                    .props('color=primary')
        result = await dlg
        if not result:
            return
        try:
            await duplicate_werkdag(
                DB_PATH, werkdag_id=werkdag_id, target_datum=result)
            ui.notify('Werkdag gedupliceerd', type='positive')
            await render()
        except YearLockedError as ex:
            ui.notify(str(ex), type='warning')
        except ValueError as ex:
            ui.notify(f'Dupliceren mislukt: {ex}', type='negative')

    async def handle_pill_delete(werkdag_id):
        from database import get_werkdag_by_id, delete_werkdag
        w = await get_werkdag_by_id(DB_PATH, werkdag_id=werkdag_id)
        if w is None:
            ui.notify('Werkdag niet gevonden', type='warning')
            return
        with ui.dialog() as dlg, ui.card():
            ui.label(
                f'Werkdag van {w.datum} bij {w.klant_naam} '
                f'verwijderen?'
            ).classes('text-base')
            with ui.row().classes('justify-end gap-2 mt-3'):
                ui.button('Annuleren',
                          on_click=lambda: dlg.submit(False)).props('flat')
                ui.button('Verwijderen',
                          on_click=lambda: dlg.submit(True)) \
                    .props('color=negative')
        if not await dlg:
            return
        try:
            await delete_werkdag(DB_PATH, werkdag_id=werkdag_id)
            ui.notify('Werkdag verwijderd', type='positive')
            await render()
        except YearLockedError as ex:
            ui.notify(str(ex), type='warning')
        except ValueError as ex:
            ui.notify(str(ex), type='negative')

    async def handle_pill_ontkoppel(werkdag_id):
        # Pre-dialog refetch is alleen voor de UI-tekst (welk factuur-
        # nummer, orphan of concept). De ECHTE check-and-update gebeurt
        # atomair in `unlink_werkdag_from_factuur` (BEGIN IMMEDIATE),
        # zodat een race tijdens dialog-wachttijd (factuur wordt elders
        # verstuurd) niet leidt tot onterecht ontkoppelen.
        from database import unlink_werkdag_from_factuur, get_db_ctx
        async with get_db_ctx(DB_PATH) as conn:
            cur = await conn.execute(
                "SELECT w.factuurnummer, "
                "       f.id AS factuur_id, f.status AS factuur_status "
                "FROM werkdagen w "
                "LEFT JOIN facturen f ON w.factuurnummer = f.nummer "
                "WHERE w.id = ?", (werkdag_id,))
            row = await cur.fetchone()
        if row is None:
            ui.notify('Werkdag niet gevonden', type='warning')
            return
        if not row['factuurnummer']:
            # Codebase-conventie: positive/warning/negative — geen 'info'.
            ui.notify('Werkdag is niet gekoppeld aan een factuur',
                      type='warning')
            return
        is_orphan = row['factuur_id'] is None
        # Fast-fail bij stale UI: status veranderde tussen render en klik.
        # Dit voorkomt een misleidende "concept-factuur"-dialog terwijl
        # de helper toch zou weigeren. De atomic helper blijft de echte
        # gate (post-dialog race wordt daar afgevangen).
        if not is_orphan and (row['factuur_status'] or '') != 'concept':
            ui.notify(
                f"Factuur is '{row['factuur_status']}'; ontkoppelen kan "
                f"alleen bij concept-facturen of orphan-links. "
                f"Refresh de agenda.", type='warning')
            await render()
            return
        factuur_descr = (
            f'orphan-factuurnummer {row["factuurnummer"]}'
            if is_orphan
            else f'concept-factuur {row["factuurnummer"]}'
        )
        with ui.dialog() as dlg, ui.card():
            ui.label(
                f'Werkdag wordt losgekoppeld van {factuur_descr}.'
            ).classes('text-base')
            ui.label(
                'De factuur en factuurregels blijven ongewijzigd. '
                'Je kunt de werkdag opnieuw koppelen of de factuur '
                'handmatig opschonen.'
            ).classes('text-sm text-slate-600 mt-2')
            with ui.row().classes('justify-end gap-2 mt-3'):
                ui.button('Annuleren',
                          on_click=lambda: dlg.submit(False)).props('flat')
                ui.button('Ontkoppel',
                          on_click=lambda: dlg.submit(True)) \
                    .props('color=warning')
        if not await dlg:
            return
        try:
            await unlink_werkdag_from_factuur(
                DB_PATH, werkdag_id=werkdag_id)
            ui.notify('Werkdag ontkoppeld', type='positive')
            await render()
        except YearLockedError as ex:
            ui.notify(str(ex), type='warning')
        except ValueError as ex:
            # Helper raised — bv. status veranderde tussen dialog en
            # bevestiging naar verstuurd/betaald.
            ui.notify(f'Ontkoppelen mislukt: {ex}', type='warning')

    def handle_pill_naar_facturen(_factuur_id):
        # Sprint 1: navigate generic. Deeplink (?nummer=…) is Sprint 2.
        ui.navigate.to('/facturen')

    async def render():
        """Refetch data + re-render grid + inspector + urencriterium-strip."""
        anchor = state['anchor']
        view = await agenda_svc.get_maand(
            DB_PATH, jaar=anchor.year, maand=anchor.month,
        )

        # Sprint D: lees klant-kleur toggle uit bedrijfsgegevens. Best-effort —
        # bij ontbrekende row of attribuut → False (= type-based fallback).
        bg = await get_bedrijfsgegevens(DB_PATH)
        gebruik_klant_kleur = bool(
            getattr(bg, 'gebruik_klant_kleur_in_agenda', False)
        ) if bg else False

        # Month label (e.g. "Mei 2026")
        refs['month_label'].text = (
            f"{NL_MONTHS[anchor.month - 1].capitalize()} {anchor.year}"
        )

        _render_month_grid(
            refs['grid_container'], view,
            on_day_click=select_day,
            selected=state['selected'],
            gebruik_klant_kleur=gebruik_klant_kleur,
            on_pill_edit=lambda wid: ui.timer(
                0, lambda: handle_pill_edit(wid), once=True),
            on_pill_duplicate=lambda wid: ui.timer(
                0, lambda: handle_pill_duplicate(wid), once=True),
            on_pill_delete=lambda wid: ui.timer(
                0, lambda: handle_pill_delete(wid), once=True),
            on_pill_ontkoppel=lambda wid: ui.timer(
                0, lambda: handle_pill_ontkoppel(wid), once=True),
            on_pill_naar_facturen=handle_pill_naar_facturen,
        )

        # Inspector
        sel_dag = await agenda_svc.get_dag(DB_PATH, state['selected'])
        _render_day_inspector(
            refs['inspector_container'], sel_dag,
            on_add_werkdag=lambda d, prefill_pattern=None:
                ui.timer(0, lambda: handle_add_werkdag(d, prefill_pattern), once=True),
            on_add_blocker=lambda d, kind:
                ui.timer(0, lambda: handle_add_blocker(d, kind), once=True),
            on_delete_blocker=lambda bid:
                ui.timer(0, lambda: handle_delete_blocker(bid), once=True),
            on_confirm_expected=lambda ent:
                ui.timer(0, lambda: handle_confirm_expected(ent), once=True),
            on_open_factuur=handle_open_factuur,
            on_create_factuur=handle_create_factuur,
        )

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
    refs['new_btn'].on_click(
        lambda: ui.timer(
            0,
            lambda: handle_add_werkdag(state['selected']),
            once=True))

    # Initial render
    await render()
