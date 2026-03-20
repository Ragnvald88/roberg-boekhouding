"""Shared UI components — DRY helpers used across all pages."""

from datetime import date

from nicegui import ui


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


def date_input(label: str = 'Datum', value: str = '',
               on_change=None) -> ui.input:
    """Reusable date input with calendar picker popup.

    Returns the ui.input element (value is bound to it).
    """
    inp = ui.input(label, value=value).props('outlined dense')
    with inp:
        with ui.menu().props('no-parent-event') as menu:
            with ui.date(mask='YYYY-MM-DD').bind_value(inp) as picker:
                picker.on('update:model-value',
                          lambda: menu.close())
        with inp.add_slot('append'):
            ui.icon('edit_calendar').on('click', menu.open) \
                .classes('cursor-pointer')
    if on_change:
        inp.on('update:model-value', on_change)
    return inp


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
                if hasattr(result, '__await__'):
                    await result

            ui.button(button_label, on_click=do_confirm) \
                .props(f'color={button_color}')
    dlg.open()
