"""Werkdag dialog — add/edit werkdag via popup."""

from nicegui import ui
from components.shared_ui import date_input
from components.utils import format_euro
from database import (
    get_klanten, add_werkdag, update_werkdag, get_fiscale_params,
    get_klant_locaties, DB_PATH,
)
from datetime import date

_KM_TARIEF_FALLBACK = 0

# Activiteitscodes — single source of truth in domain.codes (UI-free).
# Re-export here for backcompat with callers that import from this module.
from domain.codes import (
    CODES,
    ZERO_UREN_CODES as _ZERO_UREN_CODES,
    derive_activiteit,
)

async def open_werkdag_dialog(on_save=None, werkdag=None, prefill: dict | None = None):
    """Open dialog for adding or editing a werkdag.

    Args:
        on_save: async callback after successful save.
        werkdag: existing Werkdag object for edit mode, None for add mode.
        prefill: dict with optional pre-fill values for new werkdag (ignored in edit mode):
            datum: 'YYYY-MM-DD'
            klant_id: int
            start_minuten: int — informational, used to compute uren
            eind_minuten: int — informational
            activiteit: str — used to find matching code
            pattern_id: int — if set, calls confirm_expected instead of add_werkdag
                              (idempotent + race-protected via BEGIN IMMEDIATE)
    """
    klanten = await get_klanten(DB_PATH, alleen_actief=True)
    klant_options = {k.id: k.naam for k in klanten}
    klant_data = {k.id: k for k in klanten}

    # Edit mode: ensure the werkdag's klant is in the options even if inactive
    if werkdag and werkdag.klant_id not in klant_options:
        alle_klanten = await get_klanten(DB_PATH, alleen_actief=False)
        for k in alle_klanten:
            if k.id == werkdag.klant_id:
                klant_options[k.id] = f'{k.naam} (inactief)'
                klant_data[k.id] = k
                break

    is_edit = werkdag is not None
    pattern_id = (prefill or {}).get('pattern_id')

    # Cache for loaded locations per klant
    locatie_data = {}  # klant_id -> list[KlantLocatie]

    # Get default km_tarief from fiscal params
    fp = await get_fiscale_params(DB_PATH, jaar=date.today().year)
    default_km_tarief = fp.km_tarief if fp else _KM_TARIEF_FALLBACK

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl q-pa-lg'):
        ui.label(
            'Werkdag bewerken' if is_edit else 'Werkdag toevoegen'
        ).classes('text-h6 q-mb-md')
        # Row 1: Datum (full width)
        # Initial datum: edit-mode → werkdag.datum, prefill → prefill['datum'],
        # else today.
        if is_edit:
            initial_datum = werkdag.datum
        elif prefill and prefill.get('datum'):
            initial_datum = prefill['datum']
        else:
            initial_datum = date.today().isoformat()
        datum_input = date_input(
            'Datum',
            value=initial_datum,
        ).classes('w-full')

        # Row 2: Klant (full width, searchable)
        if is_edit:
            initial_klant = werkdag.klant_id
        elif prefill and prefill.get('klant_id'):
            initial_klant = prefill['klant_id']
        else:
            initial_klant = None
        klant_select = ui.select(
            klant_options,
            value=initial_klant,
            label='Klant',
            with_input=True,
        ).classes('w-full')

        # Row 3: Locatie (full width, visible when klant has locations)
        locatie_row = ui.row().classes('w-full')
        locatie_row.set_visibility(False)
        with locatie_row:
            locatie_select = ui.select(
                {}, label='Locatie', value=None,
                on_change=lambda e: on_locatie_change(e.value),
            ).classes('w-full')

        ui.separator().classes('q-my-sm')
        # Code options: show human-readable descriptions as labels
        code_options = dict(CODES)  # {code: description}
        if is_edit and werkdag.code and werkdag.code not in code_options:
            # Legacy/imported code not in standard list — include it
            code_options[werkdag.code] = werkdag.code
        initial_code = werkdag.code if is_edit and werkdag.code in code_options else 'WERKDAG'

        with ui.row().classes('w-full gap-4 items-end'):
            code_select = ui.select(
                code_options,
                value=initial_code,
                label='Activiteit',
            ).classes('flex-grow')

            uren_input = ui.number(
                'Uren', value=werkdag.uren if is_edit else 8,
                min=0, max=24, step=0.5,
            ).classes('w-24')

        ui.separator().classes('q-my-sm')
        with ui.row().classes('w-full gap-4 items-end'):
            tarief_input = ui.number(
                'Tarief (\u20ac/uur)',
                value=werkdag.tarief if is_edit else 0,
                format='%.2f', min=0, step=0.50,
            ).classes('flex-grow')

            km_input = ui.number(
                'Km (retour)',
                value=werkdag.km if is_edit else 0,
                min=0, step=1,
            ).classes('w-28')

            km_tarief_input = ui.number(
                'Km-tarief (\u20ac/km)',
                value=werkdag.km_tarief if is_edit else default_km_tarief,
                format='%.2f', min=0, step=0.01,
            ).classes('w-36')

        # Urennorm
        urennorm_check = ui.checkbox(
            'Telt mee voor urencriterium',
            value=werkdag.urennorm if is_edit else True,
        )

        # Opmerking
        opmerking_input = ui.input(
            'Opmerking', value=werkdag.opmerking if is_edit else '',
        ).classes('w-full')

        # Live total
        totaal_label = ui.label('').classes('text-body1 text-weight-bold') \
            .style('color: #0F172A')

        def update_totaal():
            u = uren_input.value or 0
            t = tarief_input.value or 0
            km = km_input.value or 0
            kmt = km_tarief_input.value or 0
            totaal = u * t + km * kmt
            parts = []
            if t:
                parts.append(f'{u} \u00d7 {format_euro(t)}')
            if km and kmt:
                parts.append(f'{km:.0f} km \u00d7 {format_euro(kmt)}')
            calc = ' + '.join(parts)
            totaal_label.text = f'{calc} = {format_euro(totaal)}' if calc else ''

        def on_locatie_change(loc_id):
            kid = klant_select.value
            if loc_id and kid in locatie_data:
                for loc in locatie_data[kid]:
                    if loc.id == loc_id:
                        km_input.value = loc.retour_km
                        break
            update_totaal()

        # Auto-fill tarief/km when klant changes, load locations
        async def _load_klant_data(kid):
            """Load location data and set defaults for a given klant_id."""
            if kid and kid in klant_data:
                k = klant_data[kid]
                tarief_input.value = k.tarief_uur

                # Load locations for this klant
                locaties = await get_klant_locaties(DB_PATH, kid)
                locatie_data[kid] = locaties
                if locaties:
                    loc_options = {loc.id: f"{loc.naam} ({loc.retour_km} km)"
                                   for loc in locaties}
                    locatie_select.options = loc_options
                    locatie_select.update()
                    locatie_row.set_visibility(True)

                    # Pre-select first location
                    first_loc = locaties[0]
                    locatie_select.value = first_loc.id
                    km_input.value = first_loc.retour_km
                else:
                    locatie_row.set_visibility(False)
                    locatie_select.value = None
                    km_input.value = k.retour_km
            else:
                locatie_row.set_visibility(False)
                locatie_select.value = None
            update_totaal()

        klant_select.on_value_change(lambda e: _load_klant_data(e.value))
        uren_input.on_value_change(lambda _: update_totaal())
        tarief_input.on_value_change(lambda _: update_totaal())
        km_input.on_value_change(lambda _: update_totaal())
        km_tarief_input.on_value_change(lambda _: update_totaal())

        # Auto-toggle urennorm for ACHTERWACHT and non-patient codes
        def on_code_change(e):
            if e.value == 'ACHTERWACHT' or e.value in _ZERO_UREN_CODES:
                urennorm_check.value = False
            else:
                urennorm_check.value = True
            # Pre-fill uren=0 and tarief=0 for non-patient business trips
            if e.value in _ZERO_UREN_CODES:
                uren_input.value = 0
                tarief_input.value = 0
            update_totaal()

        code_select.on_value_change(on_code_change)

        # Edit mode: load locations for existing werkdag's klant
        if is_edit:
            await _load_klant_data(werkdag.klant_id)
            # Try to match existing locatie by name
            if werkdag.locatie and klant_select.value in locatie_data:
                for loc in locatie_data[klant_select.value]:
                    if loc.naam == werkdag.locatie:
                        locatie_select.value = loc.id
                        km_input.value = loc.retour_km
                        break
            # Restore the historical tarief from the werkdag (may differ
            # from current klant default — A6: editing an old werkdag must
            # not silently inherit a later klant-tariff change).
            tarief_input.value = werkdag.tarief
            # Restore the actual km from the werkdag (may differ from location default)
            km_input.value = werkdag.km

        # Apply non-edit prefill (pattern-driven from /agenda)
        if not is_edit and prefill:
            # Load klant data if klant_id was prefilled (so locatie + tarief surface)
            if prefill.get('klant_id'):
                await _load_klant_data(prefill['klant_id'])
            # Compute uren from start/eind_minuten if both present
            if prefill.get('start_minuten') is not None and prefill.get('eind_minuten') is not None:
                start = prefill['start_minuten']
                eind = prefill['eind_minuten']
                if eind > start:
                    uren_input.value = (eind - start) / 60.0
            # Match activiteit to a known code (find first key in CODES whose value matches)
            if prefill.get('activiteit'):
                for code_key, code_label in CODES.items():
                    if code_label == prefill['activiteit']:
                        code_select.value = code_key
                        break

        # Pattern-mode (vanuit /agenda Bevestigen-flow): velden read-only.
        # confirm_expected accepteert geen overrides; user-edits zouden
        # anders stil verloren gaan. Datum blijft editable zodat de
        # gebruiker op een andere dag kan bevestigen.
        if pattern_id is not None:
            klant_select.props('disable')
            locatie_select.props('disable')
            code_select.props('disable')
            uren_input.props('readonly')
            tarief_input.props('readonly')
            km_input.props('readonly')
            km_tarief_input.props('readonly')
            urennorm_check.props('disable')
            opmerking_input.props('readonly')

        # Initial calculation
        update_totaal()

        async def save(and_new: bool = False):
            kid = klant_select.value
            if not kid:
                ui.notify('Selecteer een klant', type='warning')
                return
            if uren_input.value is None or uren_input.value < 0:
                ui.notify('Vul het aantal uren in', type='warning')
                return
            if tarief_input.value is None or tarief_input.value < 0:
                ui.notify('Vul een tarief in', type='warning')
                return
            k = klant_data[kid]
            # Code: preserve '' explicit (build_code_options biedt '(geen)' aan
            # in dropdown bij edit van een werkdag met code=''). None betekent
            # 'no selection at all' (valt terug op WERKDAG default).
            code = code_select.value if code_select.value is not None else 'WERKDAG'
            activiteit = derive_activiteit(
                code=code,
                current_activiteit=werkdag.activiteit if is_edit else None,
            )

            # Determine locatie text from selected location
            loc_id = locatie_select.value
            loc_naam = ''
            if loc_id and kid in locatie_data:
                for loc in locatie_data[kid]:
                    if loc.id == loc_id:
                        loc_naam = loc.naam
                        break
            locatie_text = loc_naam or k.adres

            kwargs = dict(
                datum=datum_input.value,
                klant_id=kid,
                code=code,
                activiteit=activiteit,
                locatie=locatie_text,
                locatie_id=loc_id if loc_id else None,
                uren=uren_input.value,
                km=km_input.value or 0,
                tarief=tarief_input.value,
                km_tarief=km_tarief_input.value or 0,
                urennorm=1 if urennorm_check.value else 0,
                opmerking=opmerking_input.value or '',
            )

            try:
                if is_edit:
                    await update_werkdag(DB_PATH, werkdag_id=werkdag.id, **kwargs)
                    ui.notify('Werkdag bijgewerkt', type='positive')
                elif pattern_id is not None:
                    # Pattern-driven (van /agenda Bevestigen-flow): use
                    # confirm_expected for atomic + idempotent semantics.
                    # Args: pattern_id + datum + optional override (start/eind/activiteit).
                    from services.agenda import confirm_expected
                    from datetime import date as _date_lib
                    # Parse start/eind to minuten (uit time-input of uren-derived).
                    # We hebben uren_input.value beschikbaar; voor minuten-precisie
                    # geven we de pattern-defaults door (None = use pattern's defaults).
                    # User's eventueel handmatige uren-aanpassing wordt door
                    # confirm_expected genegeerd (uses pattern.start/eind_minuten).
                    # Acceptabel voor MVP — fine-grained override is een latere iteratie.
                    await confirm_expected(
                        DB_PATH,
                        pattern_id=pattern_id,
                        datum=_date_lib.fromisoformat(datum_input.value),
                        # geen overrides — gebruikt pattern-defaults
                    )
                    ui.notify('Werkdag bevestigd', type='positive')
                else:
                    await add_werkdag(DB_PATH, **kwargs)
                    ui.notify('Werkdag toegevoegd', type='positive')
            except Exception as e:
                ui.notify(str(e), type='negative')
                return

            if on_save:
                await on_save()

            if and_new and not is_edit:
                # Reset form for next entry — keep klant, location, tarief, km, km-tarief
                datum_input.value = date.today().isoformat()
                code_select.value = 'WERKDAG'
                uren_input.value = 8
                urennorm_check.value = True
                opmerking_input.value = ''
                update_totaal()
            else:
                dialog.close()

        # Buttons
        with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
            ui.button('Annuleren', on_click=dialog.close).props('flat')
            # "Opslaan & Nieuw" verbergen in pattern-mode: pattern_id blijft
            # actief in de closure na de eerste save, dus een tweede
            # confirm_expected op een andere datum zou semantisch fout zijn
            # (pattern hoort bij één expected-occurrence, niet bij elke
            # vervolg-werkdag).
            if not is_edit and pattern_id is None:
                ui.button(
                    'Opslaan & Nieuw', icon='add',
                    on_click=lambda: save(and_new=True),
                ).props('outline color=primary')
            # Pattern-mode toont "Bevestigen" ipv "Opslaan" zodat het
            # visueel duidelijk is dat dit geen vrije save maar een patroon-
            # bevestiging is.
            primary_label = 'Bevestigen' if pattern_id is not None else 'Opslaan'
            primary_icon = 'check' if pattern_id is not None else 'save'
            ui.button(
                primary_label, icon=primary_icon,
                on_click=lambda: save(and_new=False),
            ).props('color=primary')

    dialog.open()
