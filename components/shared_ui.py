"""Shared UI components — DRY helpers used across all pages."""

import inspect
from datetime import date

from nicegui import ui

from database import (
    add_klant, update_klant,
    get_klant_locaties, add_klant_locatie, delete_klant_locatie,
    DB_PATH,
)


def year_options(include_next: bool = False, as_dict: bool = False,
                 descending: bool = True) -> list | dict:
    """Generate consistent year options for year selectors.

    Args:
        include_next: Include next year (for werkdagen/facturen planning)
        as_dict: Return {year: str(year)} dict instead of list
        descending: Newest first (True) or oldest first (False)
    """
    current = date.today().year
    end = current + 1 if include_next else current
    years = list(range(2023, end + 1))
    if descending:
        years.reverse()
    if as_dict:
        return {y: str(y) for y in years}
    return years


from components.utils import format_datum as _iso_to_nl  # reuse shared converter


def _nl_to_iso(nl_date: str) -> str:
    """Convert DD-MM-YYYY → YYYY-MM-DD for storage."""
    if nl_date and len(nl_date) == 10 and nl_date[2] == '-':
        parts = nl_date.split('-')
        if len(parts) == 3:
            return f'{parts[2]}-{parts[1]}-{parts[0]}'
    return nl_date or ''


class _DateInputWrapper:
    """Wraps ui.input to display DD-MM-YYYY while .value returns YYYY-MM-DD.

    All attribute access (classes, on, props, etc.) delegates to the
    underlying input. Chainable methods return the wrapper, not the input.
    """

    def __init__(self, input_el):
        object.__setattr__(self, '_input', input_el)

    @property
    def value(self):
        return _nl_to_iso(self._input.value) if self._input.value else ''

    @value.setter
    def value(self, iso_val):
        self._input.value = _iso_to_nl(iso_val) if iso_val else ''

    def __getattr__(self, name):
        attr = getattr(self._input, name)
        if callable(attr):
            def wrapper(*args, **kwargs):
                result = attr(*args, **kwargs)
                return self if result is self._input else result
            return wrapper
        return attr

    def __setattr__(self, name, val):
        if name == 'value':
            type(self).value.fset(self, val)
        else:
            setattr(self._input, name, val)


def date_input(label: str = 'Datum', value: str = '',
               on_change=None):
    """Reusable date input with calendar picker popup.

    Displays DD-MM-YYYY. The .value property accepts and returns
    YYYY-MM-DD (ISO) so all DB/consumer code works unchanged.
    """
    display_val = _iso_to_nl(value) if value else ''
    inp = ui.input(label, value=display_val).props('outlined dense')
    with inp:
        with ui.menu().props('no-parent-event') as menu:
            with ui.date(mask='DD-MM-YYYY').bind_value(inp) as picker:
                picker.on('update:model-value',
                          lambda: menu.close())
        with inp.add_slot('append'):
            ui.icon('edit_calendar').on('click', menu.open) \
                .classes('cursor-pointer')
    if on_change:
        inp.on('update:model-value', on_change)
    return _DateInputWrapper(inp)


async def confirm_dialog(title: str, message: str,
                         on_confirm, button_label: str = 'Verwijderen',
                         button_color: str = 'negative') -> None:
    """Show a confirmation dialog and call on_confirm if user confirms.

    Args:
        title: Dialog title
        message: Confirmation message
        on_confirm: Async or sync callable to execute on confirm
        button_label: Text for the confirm button
        button_color: Quasar color for the confirm button
    """
    with ui.dialog() as dlg, ui.card().classes('q-pa-md'):
        ui.label(title).classes('text-h6')
        ui.label(message).classes('text-body2 text-grey-7 q-my-sm')

        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
            ui.button('Annuleren', on_click=dlg.close).props('flat')

            async def do_confirm():
                dlg.close()
                result = on_confirm()
                if inspect.iscoroutine(result):
                    await result

            ui.button(button_label, on_click=do_confirm) \
                .props(f'color={button_color}')
    dlg.open()


async def open_klant_dialog(klant: dict | None = None,
                            on_save=None) -> None:
    """Shared add/edit klant dialog with all invoice-address fields + locaties.

    Args:
        klant: None for new klant, dict with klant fields for edit
        on_save: async callback(klant_id: int, naam: str) called after save
    """
    is_edit = klant is not None
    d = klant or {}
    title = 'Klant bewerken' if is_edit else 'Nieuwe klant'
    btn_label = 'Opslaan' if is_edit else 'Toevoegen'
    btn_icon = None if is_edit else 'add'

    with ui.dialog() as dlg, ui.card().classes('w-full max-w-lg q-pa-lg'):
        ui.label(title).classes('text-h6')
        ui.separator().classes('q-mb-md')

        # -- Factuuradres (matches invoice template order) --
        _section_label('Factuuradres')
        f_naam = ui.input('Praktijk / bedrijfsnaam *',
                          value=d.get('naam', '')).classes('w-full')
        f_contact = ui.input('Contactpersoon',
                             value=d.get('contactpersoon', '')) \
            .props('placeholder="t.a.v."').classes('w-full')
        f_adres = ui.input('Straat + huisnummer',
                           value=d.get('adres', '')).classes('w-full')
        with ui.row().classes('w-full gap-3'):
            f_postcode = ui.input('Postcode',
                                  value=d.get('postcode', '')).classes('w-32')
            f_plaats = ui.input('Plaats',
                                value=d.get('plaats', '')).classes('flex-grow')

        # -- Contact --
        _section_label('Contact', margin_top=True)
        with ui.row().classes('w-full gap-3'):
            f_email = ui.input('E-mail',
                               value=d.get('email', '')).classes('flex-grow')
            f_kvk = ui.input('KvK',
                             value=d.get('kvk', '')).classes('w-36')

        # -- Tarieven --
        _section_label('Tarieven', margin_top=True)
        with ui.row().classes('w-full gap-3'):
            f_tarief = ui.number('Tarief/uur (\u20ac)', value=d.get('tarief_uur', 0),
                                 min=0, step=0.50).classes('flex-grow')
            f_km = ui.number('Retour km', value=d.get('retour_km', 0),
                             min=0).classes('flex-grow')

        # -- Locaties (edit mode only) --
        if is_edit and klant.get('id'):
            ui.separator().classes('q-my-md')
            _section_label('Locaties')
            ui.label(
                'Werklocaties met retourafstand. '
                'Verschijnt als dropdown in het werkdagformulier.'
            ).classes('text-caption text-grey-5')

            loc_container = ui.column().classes('w-full gap-1 q-mt-xs')

            async def refresh_locaties():
                loc_container.clear()
                locaties = await get_klant_locaties(DB_PATH, klant['id'])
                with loc_container:
                    for loc in locaties:
                        with ui.row().classes('w-full items-center gap-2'):
                            ui.label(loc.naam).classes('flex-grow')
                            ui.label(f'{loc.retour_km:.0f} km').classes(
                                'text-caption text-grey')

                            async def del_loc(lid=loc.id, lnaam=loc.naam):
                                await confirm_dialog(
                                    f'Locatie "{lnaam}" verwijderen?',
                                    'Deze actie kan niet ongedaan worden.',
                                    on_confirm=lambda _lid=lid: _do_del_loc(_lid),
                                )

                            async def _do_del_loc(_lid):
                                await delete_klant_locatie(DB_PATH, _lid)
                                ui.notify('Locatie verwijderd', type='info')
                                await refresh_locaties()

                            ui.button(icon='close', on_click=del_loc).props(
                                'flat dense round size=sm color=negative')

                    # Add new location row
                    with ui.row().classes('w-full items-end gap-2'):
                        new_loc_naam = ui.input('Locatienaam').classes(
                            'flex-grow').props('dense')
                        new_loc_km = ui.number('Km retour', value=0,
                                               min=0).classes('w-24').props('dense')

                        async def add_loc():
                            naam = new_loc_naam.value
                            km = new_loc_km.value or 0
                            if not naam:
                                ui.notify('Vul een locatienaam in', type='warning')
                                return
                            try:
                                await add_klant_locatie(DB_PATH, klant['id'], naam, km)
                            except Exception:
                                ui.notify(f'Locatie "{naam}" bestaat al', type='warning')
                                return
                            ui.notify(f'Locatie "{naam}" toegevoegd', type='positive')
                            await refresh_locaties()

                        ui.button(icon='add', on_click=add_loc).props(
                            'flat dense round color=primary')

            await refresh_locaties()

        # -- Actions --
        with ui.row().classes('w-full justify-end gap-2 q-mt-lg'):
            ui.button('Annuleren', on_click=dlg.close).props('flat')

            async def do_save():
                naam = (f_naam.value or '').strip()
                if not naam:
                    ui.notify('Vul een naam in', type='warning')
                    return

                kwargs = dict(
                    naam=naam,
                    contactpersoon=(f_contact.value or '').strip(),
                    adres=(f_adres.value or '').strip(),
                    postcode=(f_postcode.value or '').strip(),
                    plaats=(f_plaats.value or '').strip(),
                    email=(f_email.value or '').strip(),
                    kvk=(f_kvk.value or '').strip(),
                    tarief_uur=f_tarief.value or 0,
                    retour_km=f_km.value or 0,
                )

                if is_edit:
                    await update_klant(DB_PATH, klant_id=klant['id'], **kwargs)
                    klant_id = klant['id']
                    ui.notify('Klant bijgewerkt', type='positive')
                else:
                    klant_id = await add_klant(DB_PATH, **kwargs)
                    ui.notify(f'Klant "{naam}" aangemaakt', type='positive')

                dlg.close()
                if on_save:
                    result = on_save(klant_id, naam)
                    if inspect.iscoroutine(result):
                        await result

            ui.button(btn_label, icon=btn_icon, on_click=do_save).props('color=primary')
    dlg.open()


def _section_label(text: str, margin_top: bool = False):
    """Render a small section label for form grouping."""
    cls = 'text-caption text-weight-medium text-grey-7 q-mb-xs'
    if margin_top:
        cls += ' q-mt-md'
    ui.label(text).classes(cls)
