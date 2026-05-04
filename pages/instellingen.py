"""Instellingen pagina — bedrijfsgegevens, fiscale parameters, backup."""

import asyncio
from datetime import date
import json
import math
import shutil
import tempfile
import zipfile
from pathlib import Path

from nicegui import ui

from components.layout import create_layout, page_title
from database import (
    get_all_fiscale_params, upsert_fiscale_params,
    get_bedrijfsgegevens, upsert_bedrijfsgegevens, get_db_ctx, DB_PATH,
    YearLockedError,
)


def _validate_arbeidskorting_brackets(brackets: list[dict]) -> list[str]:
    """Return Dutch validation errors for an arbeidskorting brackets list.

    Rules:
    - Must be a non-empty list
    - Each bracket has keys: lower, upper, rate, base
    - lower must be ascending and >= 0
    - upper of bracket N must equal lower of bracket N+1 (contiguous)
    - Last bracket may have upper=None (means infinity)
    - Only the LAST bracket may have upper=None
    - rate between -1.0 and 1.0
    - base >= 0
    """
    errors: list[str] = []
    if not isinstance(brackets, list) or not brackets:
        errors.append('Arbeidskorting moet minstens 1 schijf bevatten')
        return errors

    for i, b in enumerate(brackets):
        if not isinstance(b, dict):
            errors.append(f'Schijf {i + 1}: ongeldig formaat')
            continue
        for key in ('lower', 'upper', 'rate', 'base'):
            if key not in b:
                errors.append(
                    f'Schijf {i + 1}: ontbrekend veld "{key}"')

    if errors:
        return errors

    def _is_num(x):
        # L8/U3 (codex follow-up): also reject NaN and ±Infinity. A
        # malformed JSON literal like {"lower": NaN} would otherwise pass
        # the isinstance check, then produce numerically meaningless
        # results when the engine compared against it (NaN compares False
        # to everything, so brackets silently went unused). Bool is
        # excluded for the usual reason — bool is subclass of int in
        # Python, but `True/False` should not be a tarief/grens.
        if isinstance(x, bool):
            return False
        if not isinstance(x, (int, float)):
            return False
        return not (math.isnan(x) or math.isinf(x))

    last = len(brackets) - 1
    for i, b in enumerate(brackets):
        lower = b.get('lower')
        upper = b.get('upper')
        rate = b.get('rate')
        base = b.get('base')

        if not _is_num(lower):
            errors.append(
                f'Schijf {i + 1}: ondergrens moet een getal zijn'
                f' (nu: {lower!r})')
        elif lower < 0:
            errors.append(
                f'Schijf {i + 1}: ondergrens moet ≥ 0 (nu: {lower})')

        if i == last:
            # Last bracket may have upper=None (infinity)
            if upper is not None:
                if not _is_num(upper):
                    errors.append(
                        f'Schijf {i + 1}: bovengrens moet een getal of leeg'
                        f' zijn (nu: {upper!r})')
                elif _is_num(lower) and upper < lower:
                    errors.append(
                        f'Schijf {i + 1}: bovengrens moet ≥ ondergrens'
                        f' (nu: {upper} < {lower})')
        else:
            if upper is None:
                errors.append(
                    f'Schijf {i + 1}: alleen de laatste schijf mag een open '
                    f'bovengrens (∞) hebben')
            elif not _is_num(upper):
                errors.append(
                    f'Schijf {i + 1}: bovengrens moet een getal zijn'
                    f' (nu: {upper!r})')
            elif _is_num(lower) and upper < lower:
                errors.append(
                    f'Schijf {i + 1}: bovengrens moet ≥ ondergrens'
                    f' (nu: {upper} < {lower})')

        if not _is_num(rate):
            errors.append(
                f'Schijf {i + 1}: tarief moet een getal zijn'
                f' (nu: {rate!r})')
        elif not (-1.0 <= rate <= 1.0):
            errors.append(
                f'Schijf {i + 1}: tarief moet tussen -1.0 en 1.0 liggen'
                f' (nu: {rate})')

        if not _is_num(base):
            errors.append(
                f'Schijf {i + 1}: basisbedrag moet een getal zijn'
                f' (nu: {base!r})')
        elif base < 0:
            errors.append(
                f'Schijf {i + 1}: basisbedrag moet ≥ 0 (nu: {base})')

    # Contiguity check: upper of N == lower of N+1
    for i in range(len(brackets) - 1):
        cur_upper = brackets[i].get('upper')
        next_lower = brackets[i + 1].get('lower')
        if not (_is_num(cur_upper) and _is_num(next_lower)):
            continue
        if cur_upper != next_lower:
            errors.append(
                f'Schijven moeten aaneensluiten: bovengrens schijf {i + 1}'
                f' (€ {cur_upper:,.0f}) moet gelijk zijn aan ondergrens'
                f' schijf {i + 2} (€ {next_lower:,.0f})')

    # Ascending lower
    for i in range(len(brackets) - 1):
        a = brackets[i].get('lower')
        b = brackets[i + 1].get('lower')
        if not (_is_num(a) and _is_num(b)):
            continue
        if b <= a:
            errors.append(
                f'Schijf {i + 2}: ondergrens moet groter zijn dan schijf'
                f' {i + 1} ondergrens')

    return errors


def _validate_fiscal_params(p: dict) -> list[str]:
    """Return a list of human-readable Dutch validation errors, or [] if valid.

    Distinguishes missing/None from 0. Percentages that must be > 0 in real
    practice (IB schijven, PVV, ZVW, EW forfait, representatie, MKB) trigger
    an error when absent or empty — never silently coerced to 0.
    """
    errors: list[str] = []

    # Percentages where 0 is not a legitimate real-world value.
    # Missing/None/empty is a clear-field mistake; flag it explicitly.
    required_positive_pct = [
        'schijf1_pct', 'schijf2_pct', 'schijf3_pct',
        'mkb_vrijstelling_pct',
        'pvv_aow_pct', 'pvv_anw_pct', 'pvv_wlz_pct',
        'zvw_pct', 'ew_forfait_pct', 'repr_aftrek_pct',
        # Box 3 rendementen/tarief: in de praktijk > 0 per Belastingdienst
        'box3_rendement_bank_pct', 'box3_rendement_overig_pct', 'box3_tarief_pct',
    ]
    for fld in required_positive_pct:
        if fld not in p or p[fld] is None:
            errors.append(f'{fld} is verplicht en mag niet leeg zijn')
            continue
        v = p[fld]
        if not (0 < v <= 100):
            errors.append(f'{fld} moet > 0 en <= 100 zijn (nu: {v})')

    # Percentages waar 0 een legitieme waarde is (presence wel vereist).
    # wet_hillen_pct wordt uitgefaseerd en kan 0 worden; schuld-rendement is
    # 0 voor belastingplichtigen zonder Box-3-schulden.
    required_nonneg_pct = ['wet_hillen_pct', 'box3_rendement_schuld_pct']
    for fld in required_nonneg_pct:
        if fld not in p or p[fld] is None:
            errors.append(
                f'{fld} is verplicht — vul 0 in als niet van toepassing')
            continue
        v = p[fld]
        if not (0 <= v <= 100):
            errors.append(f'{fld} moet tussen 0 en 100 liggen (nu: {v})')

    # IB schijf grenzen: verplicht en strikt > 0 (monotonie-check verderop)
    for fld in ('schijf1_grens', 'schijf2_grens'):
        if fld not in p or p[fld] is None:
            errors.append(f'{fld} is verplicht en mag niet leeg zijn')
            continue
        if p[fld] <= 0:
            errors.append(f'{fld} moet groter dan 0 zijn (nu: {p[fld]})')

    if ('schijf1_grens' in p and p.get('schijf1_grens') is not None
            and 'schijf2_grens' in p and p.get('schijf2_grens') is not None):
        if p['schijf2_grens'] < p['schijf1_grens']:
            errors.append(
                'Schijf 2 grens moet groter of gelijk zijn aan schijf 1 grens')

    # KIA percentage: verplicht aanwezig, mag 0 zijn als KIA-regeling niet van toepassing
    if 'kia_pct' not in p or p['kia_pct'] is None:
        errors.append('kia_pct is verplicht en mag niet leeg zijn')
    elif not (0 <= p['kia_pct'] <= 100):
        errors.append(f'kia_pct moet tussen 0 en 100 liggen (nu: {p["kia_pct"]})')

    # Required positive amounts: crash if None because fiscal engine accesses directly
    required_positive_amt = [
        'ahk_afbouw_pct',  # heffingskortingen.py uses params['ahk_afbouw_pct']
        'zvw_max_grondslag',  # berekeningen.py uses params['zvw_max_grondslag']
        'pvv_premiegrondslag',  # berekeningen.py PVV calculation
        # Nieuw required sinds silent-fallback fix:
        'villataks_grens',  # villataks-berekening heeft een echte grens nodig
        'urencriterium',  # ZZP-check op 1225 uur
        'box3_heffingsvrij_vermogen',  # box3-berekening
    ]
    for fld in required_positive_amt:
        if fld not in p or p[fld] is None:
            errors.append(f'{fld} is verplicht en mag niet leeg zijn')
        elif p[fld] <= 0:
            errors.append(f'{fld} moet groter dan 0 zijn (nu: {p[fld]})')

    # Bedragen waar 0 een legitieme waarde is (presence wel vereist).
    required_nonneg_amt = ['box3_drempel_schulden']
    for fld in required_nonneg_amt:
        if fld not in p or p[fld] is None:
            errors.append(
                f'{fld} is verplicht — vul 0 in als niet van toepassing')
        elif p[fld] < 0:
            errors.append(f'{fld} mag niet negatief zijn (nu: {p[fld]})')

    # arbeidskorting_brackets: moet een niet-lege string zijn (JSON-array van schijven)
    if 'arbeidskorting_brackets' not in p or not p['arbeidskorting_brackets']:
        errors.append(
            'arbeidskorting_brackets is verplicht (JSON-array van schijven)')

    # Bedragen die 0 mogen zijn (bv. geen startersaftrek meer van toepassing)
    optional_nonneg = [
        'ahk_max', 'ahk_drempel', 'ak_max',
        'kia_ondergrens', 'kia_bovengrens',
        'zelfstandigenaftrek', 'startersaftrek',
    ]
    for fld in optional_nonneg:
        if fld in p and p[fld] is not None and p[fld] < 0:
            errors.append(f'{fld} mag niet negatief zijn (nu: {p[fld]})')

    kia_onder = p.get('kia_ondergrens')
    kia_boven = p.get('kia_bovengrens')
    if (kia_onder is not None and kia_boven is not None
            and kia_boven < kia_onder):
        errors.append(
            'KIA bovengrens moet groter of gelijk zijn aan KIA ondergrens')

    return errors

@ui.page('/instellingen')
async def instellingen_page():
    create_layout('Instellingen', '/instellingen')

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        page_title('Instellingen')

        with ui.tabs().classes('w-full') as tabs:
            tab_bedrijf = ui.tab('Bedrijfsgegevens')
            tab_fiscaal = ui.tab('Fiscale parameters')
            tab_backup = ui.tab('Backup')

        with ui.tab_panels(tabs, value=tab_bedrijf).classes('w-full'):

            with ui.tab_panel(tab_bedrijf):
                bedrijf_container = ui.column().classes('w-full')

                async def refresh_bedrijf():
                    bedrijf_container.clear()
                    bg = await get_bedrijfsgegevens(DB_PATH)

                    fields: dict = {}
                    cards: list = []

                    def _mark_dirty(card):
                        """Returns a closure that marks the given card dirty on input change."""
                        def _h():
                            card.classes(add='is-dirty')
                        return _h

                    with bedrijf_container:
                        ui.label('Deze gegevens worden gebruikt op facturen.').classes(
                            'text-body2 text-grey q-mb-md')

                        # Card 1: Identiteit
                        with ui.card().classes('settings-card') as card_identiteit:
                            cards.append(card_identiteit)
                            ui.label('Identiteit').classes('settings-card-title')
                            fields['bedrijfsnaam'] = ui.input(
                                'Bedrijfsnaam',
                                value=getattr(bg, 'bedrijfsnaam', '') or '',
                                on_change=_mark_dirty(card_identiteit),
                            ).classes('w-full')
                            with ui.grid(columns=2).classes('w-full gap-3'):
                                fields['naam'] = ui.input(
                                    'Naam', value=getattr(bg, 'naam', '') or '',
                                    on_change=_mark_dirty(card_identiteit))
                                fields['functie'] = ui.input(
                                    'Functie', value=getattr(bg, 'functie', '') or '',
                                    on_change=_mark_dirty(card_identiteit))

                        # Card 2: Contact
                        with ui.card().classes('settings-card') as card_contact:
                            cards.append(card_contact)
                            ui.label('Contact').classes('settings-card-title')
                            fields['adres'] = ui.input(
                                'Adres', value=getattr(bg, 'adres', '') or '',
                                on_change=_mark_dirty(card_contact),
                            ).classes('w-full')
                            with ui.grid(columns=2).classes('w-full gap-3'):
                                fields['postcode_plaats'] = ui.input(
                                    'Postcode + Plaats',
                                    value=getattr(bg, 'postcode_plaats', '') or '',
                                    on_change=_mark_dirty(card_contact))
                                fields['telefoon'] = ui.input(
                                    'Telefoon',
                                    value=getattr(bg, 'telefoon', '') or '',
                                    on_change=_mark_dirty(card_contact))
                            fields['email'] = ui.input(
                                'E-mail', value=getattr(bg, 'email', '') or '',
                                on_change=_mark_dirty(card_contact),
                            ).classes('w-full')

                        # Card 3: Fiscaal & financieel
                        with ui.card().classes('settings-card') as card_fiscaal:
                            cards.append(card_fiscaal)
                            ui.label('Fiscaal & financieel').classes('settings-card-title')
                            with ui.grid(columns=2).classes('w-full gap-3'):
                                fields['kvk'] = ui.input(
                                    'KvK-nummer', value=getattr(bg, 'kvk', '') or '',
                                    on_change=_mark_dirty(card_fiscaal))
                                fields['iban'] = ui.input(
                                    'IBAN', value=getattr(bg, 'iban', '') or '',
                                    on_change=_mark_dirty(card_fiscaal))
                            fields['thuisplaats'] = ui.input(
                                'Thuisplaats (voor reiskosten)',
                                value=getattr(bg, 'thuisplaats', '') or '',
                                on_change=_mark_dirty(card_fiscaal),
                            ).classes('w-full')

                        # Card 4: Logo & visueel
                        with ui.card().classes('settings-card') as card_visueel:
                            cards.append(card_visueel)
                            ui.label('Logo & visueel').classes('settings-card-title')

                            # ─── Logo media-row (hidden upload + JS pickFiles trigger + local refresh) ─
                            logo_dir = DB_PATH.parent / 'logo'
                            logo_dir.mkdir(parents=True, exist_ok=True)

                            # Upload-handler bound once: ui.upload (and dus
                            # zijn registered on_upload callback) wordt eenmaal
                            # gemaakt. render_logo_row() rebuilds alleen het
                            # zichtbare row-container, dus de upload + handler
                            # blijven leven over local refreshes.
                            async def handle_logo_upload(e):
                                content = await e.file.read()
                                ext = e.file.name.rsplit('.', 1)[-1].lower()
                                target = logo_dir / f'logo.{ext}'
                                tmp = logo_dir / f'.logo.new.{ext}'
                                await asyncio.to_thread(tmp.write_bytes, content)
                                for old in logo_dir.glob('logo.*'):
                                    if old != tmp:
                                        try:
                                            await asyncio.to_thread(old.unlink)
                                        except OSError:
                                            pass
                                await asyncio.to_thread(tmp.rename, target)
                                ui.notify('Logo opgeslagen', type='positive')
                                render_logo_row()  # local refresh — preserves other inputs

                            _logo_upload = ui.upload(
                                label='', auto_upload=True,
                                on_upload=handle_logo_upload,
                                max_file_size=5_000_000,
                            ).props('flat accept=".png,.jpg,.jpeg,.svg"')
                            _logo_upload.style(
                                'visibility: hidden; height: 0; overflow: hidden;'
                                ' position: absolute;')

                            _pick_logo_js = (
                                f'() => getElement({_logo_upload.id})'
                                f'.$refs.qRef.pickFiles()')

                            # Container voor de zichtbare row — clear+rebuild bij upload/delete
                            logo_row_container = ui.column().classes('w-full q-mb-md')

                            def render_logo_row():
                                """Re-render only the logo row — preserves other inputs' state."""
                                logo_files = list(logo_dir.glob('logo.*'))
                                current_logo = logo_files[0] if logo_files else None

                                async def delete_logo():
                                    # Invariant: Verwijderen-knop wordt
                                    # alleen gerenderd binnen `if current_logo:`.
                                    # Assert ipv silent-return: faalt loud als
                                    # de invariant ooit breekt (toekomstige
                                    # refactor) en narrowt het type voor
                                    # Pyright (Path|None → Path).
                                    assert current_logo is not None
                                    try:
                                        await asyncio.to_thread(current_logo.unlink)
                                    except OSError as ex:
                                        ui.notify(
                                            f'Kon logo niet verwijderen: {ex}',
                                            type='negative')
                                        return
                                    ui.notify('Logo verwijderd', type='positive')
                                    render_logo_row()

                                logo_row_container.clear()
                                with logo_row_container:
                                    with ui.row().classes(
                                        'w-full items-center q-gutter-md'
                                    ):
                                        # Framed preview (klikbaar — opent ook file-picker)
                                        preview_box = ui.element('div').style(
                                            'width: 96px; height: 96px; border-radius: 8px;'
                                            ' border: 1px solid var(--border);'
                                            ' background: var(--bg);'
                                            ' display: flex; align-items: center;'
                                            ' justify-content: center; overflow: hidden;'
                                            ' cursor: pointer;')
                                        with preview_box:
                                            if current_logo:
                                                ui.image(f'/logo-files/{current_logo.name}').style(
                                                    'max-width: 96px; max-height: 96px;'
                                                    ' object-fit: contain;')
                                            else:
                                                ui.icon('image_not_supported').classes(
                                                    'text-grey').style('font-size: 32px;')
                                        preview_box.on('click', js_handler=_pick_logo_js)

                                        # Right: button + file-info + delete-link
                                        with ui.column().classes('items-start gap-1'):
                                            ui.button(
                                                'Logo vervangen', icon='upload',
                                            ).on(
                                                'click', js_handler=_pick_logo_js,
                                            ).props('flat color=primary')
                                            if current_logo:
                                                size_kb = current_logo.stat().st_size // 1024
                                                ui.label(
                                                    f'{current_logo.name} · {size_kb} KB'
                                                ).classes('text-caption text-grey')
                                                ui.button(
                                                    'Verwijderen', on_click=delete_logo,
                                                ).props('flat dense color=negative size=sm')
                                            else:
                                                ui.label('Geen logo geüpload').classes(
                                                    'text-caption text-grey')

                            render_logo_row()  # initial populate

                            # Klant-kleur-toggle (verhuisd uit eigen "Visuele instellingen"
                            # subtitle — semantisch onderdeel van branding).
                            fields['gebruik_klant_kleur_in_agenda'] = ui.checkbox(
                                'Klant-kleuren tonen in agenda',
                                value=bool(getattr(
                                    bg, 'gebruik_klant_kleur_in_agenda', False)) if bg else False,
                                on_change=_mark_dirty(card_visueel),
                            )
                            ui.label(
                                'Als aan: agenda-cellen krijgen de kleur die per klant '
                                'is ingesteld (via Klanten-dialog). Klanten zonder kleur '
                                'en blockers/holidays blijven type-based gestyled.'
                            ).classes('text-caption text-grey')

                        # Save handler — één Opslaan voor alle 4 cards
                        async def save_bedrijf():
                            kwargs = {}
                            for k, v in fields.items():
                                val = v.value
                                if isinstance(val, bool):
                                    kwargs[k] = int(val)
                                else:
                                    kwargs[k] = val or ''
                            if not (kwargs.get('iban') or '').strip():
                                ui.notify(
                                    'IBAN mag niet leeg zijn — QR-betaallink zou stuk gaan '
                                    'op alle volgende facturen',
                                    type='negative', timeout=8)
                                return
                            if not (kwargs.get('naam') or '').strip():
                                ui.notify('Naam mag niet leeg zijn', type='negative')
                                return
                            if not (kwargs.get('kvk') or '').strip():
                                ui.notify('KvK-nummer mag niet leeg zijn', type='negative')
                                return
                            await upsert_bedrijfsgegevens(DB_PATH, **kwargs)
                            for c in cards:
                                c.classes(remove='is-dirty')
                            ui.notify('Bedrijfsgegevens opgeslagen', type='positive')

                        ui.button(
                            'Wijzigingen opslaan', icon='save', on_click=save_bedrijf
                        ).props('color=primary').classes('q-mt-md')

                await refresh_bedrijf()

            with ui.tab_panel(tab_fiscaal):
                fiscaal_container = ui.column().classes('w-full')

                async def refresh_fiscaal():
                    fiscaal_container.clear()
                    params_list = await get_all_fiscale_params(DB_PATH)

                    with fiscaal_container:
                        # "Add year" button
                        with ui.row().classes('w-full items-center gap-4 q-mb-md'):
                            new_jaar_input = ui.number(
                                'Nieuw jaar', value=date.today().year + 1,
                                format='%.0f', min=2023, step=1,
                            ).classes('w-32')

                            async def add_jaar():
                                jaar = int(new_jaar_input.value or 0)
                                if jaar < 2023:
                                    ui.notify('Ongeldig jaar', type='warning')
                                    return
                                existing = [p.jaar for p in params_list]
                                if jaar in existing:
                                    ui.notify(f'{jaar} bestaat al', type='warning')
                                    return
                                if not params_list:
                                    ui.notify(
                                        'Er zijn nog geen fiscale parameters voor enig '
                                        'jaar. Seed eerst de database via `python -m '
                                        'import_.seed_data` of voeg handmatig een '
                                        'volledig parameterjaar toe via SQL.',
                                        type='negative', timeout=10000,
                                    )
                                    return
                                # Copy from most recent year as template.
                                # Bedoeling: gebruiker krijgt vorige-jaar
                                # waarden als startpunt, kan dan per veld
                                # alleen wat veranderd is overschrijven.
                                latest = params_list[-1]
                                kwargs = {
                                    'jaar': jaar,
                                    'zelfstandigenaftrek': latest.zelfstandigenaftrek,
                                    'startersaftrek': latest.startersaftrek,
                                    'mkb_vrijstelling_pct': latest.mkb_vrijstelling_pct,
                                    'kia_ondergrens': latest.kia_ondergrens,
                                    'kia_bovengrens': latest.kia_bovengrens,
                                    'kia_pct': latest.kia_pct,
                                    'kia_drempel_per_item': latest.kia_drempel_per_item,
                                    'kia_plateau_bedrag': latest.kia_plateau_bedrag,
                                    'kia_plateau_eind': latest.kia_plateau_eind,
                                    'kia_afbouw_eind': latest.kia_afbouw_eind,
                                    'kia_afbouw_pct': latest.kia_afbouw_pct,
                                    'km_tarief': latest.km_tarief,
                                    'schijf1_grens': latest.schijf1_grens,
                                    'schijf1_pct': latest.schijf1_pct,
                                    'schijf2_grens': latest.schijf2_grens,
                                    'schijf2_pct': latest.schijf2_pct,
                                    'schijf3_pct': latest.schijf3_pct,
                                    'pvv_premiegrondslag': latest.pvv_premiegrondslag,
                                    'ahk_max': latest.ahk_max,
                                    'ahk_afbouw_pct': latest.ahk_afbouw_pct,
                                    'ahk_drempel': latest.ahk_drempel,
                                    'ak_max': latest.ak_max,
                                    'zvw_pct': latest.zvw_pct,
                                    'zvw_max_grondslag': latest.zvw_max_grondslag,
                                    'repr_aftrek_pct': latest.repr_aftrek_pct,
                                    'ew_forfait_pct': latest.ew_forfait_pct,
                                    'villataks_grens': latest.villataks_grens,
                                    'wet_hillen_pct': latest.wet_hillen_pct,
                                    'urencriterium': latest.urencriterium,
                                    'arbeidskorting_brackets': latest.arbeidskorting_brackets,
                                    'pvv_aow_pct': latest.pvv_aow_pct,
                                    'pvv_anw_pct': latest.pvv_anw_pct,
                                    'pvv_wlz_pct': latest.pvv_wlz_pct,
                                    'box3_heffingsvrij_vermogen': latest.box3_heffingsvrij_vermogen,
                                    'box3_rendement_bank_pct': latest.box3_rendement_bank_pct,
                                    'box3_rendement_overig_pct': latest.box3_rendement_overig_pct,
                                    'box3_rendement_schuld_pct': latest.box3_rendement_schuld_pct,
                                    'box3_tarief_pct': latest.box3_tarief_pct,
                                    'box3_drempel_schulden': latest.box3_drempel_schulden,
                                    'za_actief': int(latest.za_actief),
                                    'sa_actief': int(latest.sa_actief),
                                    'ew_naar_partner': int(latest.ew_naar_partner),
                                    'box3_fiscaal_partner': int(latest.box3_fiscaal_partner),
                                }
                                try:
                                    await upsert_fiscale_params(DB_PATH, **kwargs)
                                except YearLockedError as e:
                                    ui.notify(str(e), type='warning',
                                              timeout=8000)
                                    return
                                ui.notify(
                                    f'Jaar {jaar} toegevoegd (kopie van {latest.jaar})',
                                    type='positive')
                                await refresh_fiscaal()

                            ui.button('Jaar toevoegen', icon='add',
                                      on_click=add_jaar).props('color=primary')

                        if not params_list:
                            ui.label('Geen fiscale parameters gevonden.') \
                                .classes('text-grey')
                            return

                        for params in params_list:
                            with ui.expansion(
                                f'{params.jaar}',
                                icon='calendar_month',
                            ).classes('w-full'):
                                # Locked-year banner: definitief jaren krijgen
                                # alleen-lezen UI. Heropenen via /jaarafsluiting.
                                is_locked = (
                                    params.jaarafsluiting_status
                                    == 'definitief')
                                if is_locked:
                                    with ui.row().classes(
                                        'alert-card alert-card--warning'
                                        ' items-center q-gutter-sm q-mb-md'
                                    ):
                                        ui.icon('warning').classes('alert-icon')
                                        with ui.column().classes('gap-0'):
                                            ui.label(
                                                f'Jaar {params.jaar} is'
                                                ' definitief afgesloten'
                                            ).classes('alert-title')
                                            ui.label(
                                                'Heropen via /jaarafsluiting'
                                                ' om te wijzigen.'
                                            ).classes('alert-body')
                                # Per-field metadata: label, key, format, step.
                                grouped_fields = [
                                    ('IB Schijven', [
                                        ('Schijf 1 grens €', 'schijf1_grens', '%.0f', 1),
                                        ('Schijf 1 %', 'schijf1_pct', '%.2f', 0.01),
                                        ('Schijf 2 grens €', 'schijf2_grens', '%.0f', 1),
                                        ('Schijf 2 %', 'schijf2_pct', '%.2f', 0.01),
                                        ('Schijf 3 %', 'schijf3_pct', '%.2f', 0.01),
                                        ('PVV premiegrondslag €', 'pvv_premiegrondslag', '%.0f', 1),
                                    ]),
                                    ('Ondernemersaftrek', [
                                        ('Zelfstandigenaftrek €', 'zelfstandigenaftrek', '%.0f', 1),
                                        ('Startersaftrek €', 'startersaftrek', '%.0f', 1),
                                        ('MKB-vrijstelling %', 'mkb_vrijstelling_pct', '%.2f', 0.01),
                                    ]),
                                    ('Investeringsaftrek (KIA)', [
                                        ('KIA % (binnen onder/boven)', 'kia_pct', '%.2f', 0.1),
                                        ('KIA ondergrens €', 'kia_ondergrens', '%.0f', 1),
                                        ('KIA bovengrens €', 'kia_bovengrens', '%.0f', 1),
                                        ('KIA drempel per item €', 'kia_drempel_per_item', '%.0f', 1),
                                        ('KIA plateau bedrag € (boven bovengrens)', 'kia_plateau_bedrag', '%.0f', 1),
                                        ('KIA plateau eind € (einde plateau)', 'kia_plateau_eind', '%.0f', 1),
                                        ('KIA afbouw eind € (waarop KIA = 0)', 'kia_afbouw_eind', '%.0f', 1),
                                        ('KIA afbouw % per €', 'kia_afbouw_pct', '%.4f', 0.01),
                                    ]),
                                    ('Heffingskortingen', [
                                        ('AHK max €', 'ahk_max', '%.0f', 1),
                                        ('AHK afbouw %', 'ahk_afbouw_pct', '%.3f', 0.01),
                                        ('AHK drempel €', 'ahk_drempel', '%.0f', 1),
                                        ('AK max €', 'ak_max', '%.0f', 1),
                                    ]),
                                    ('ZVW', [
                                        ('ZVW %', 'zvw_pct', '%.2f', 0.01),
                                        ('ZVW max grondslag €', 'zvw_max_grondslag', '%.0f', 1),
                                    ]),
                                    ('Eigen woning', [
                                        ('EW forfait %', 'ew_forfait_pct', '%.3f', 0.01),
                                        ('Villataks grens €', 'villataks_grens', '%.0f', 1000),
                                        ('Wet Hillen %', 'wet_hillen_pct', '%.3f', 0.01),
                                    ]),
                                    ('Overig per jaar', [
                                        ('Km-tarief €', 'km_tarief', '%.3f', 0.001),
                                        ('Representatie aftrek %', 'repr_aftrek_pct', '%.2f', 0.5),
                                        ('Urencriterium (uren)', 'urencriterium', '%.0f', 1),
                                    ]),
                                ]
                                # Flat list for save logic
                                fields = []
                                inputs = {}
                                for section_label, section_fields in grouped_fields:
                                    with ui.column().classes('settings-section w-full'):
                                        ui.label(section_label).classes(
                                            'settings-section-title')
                                        with ui.grid(columns=2).classes(
                                            'w-full gap-3'
                                        ):
                                            for label, key, fmt, step in section_fields:
                                                fields.append((label, key))
                                                val = getattr(params, key)
                                                inp = ui.number(
                                                    label,
                                                    value=val if val is not None else 0,
                                                    format=fmt, step=step,
                                                ).classes('w-full')
                                                if is_locked:
                                                    inp.props('readonly')
                                                inputs[key] = inp
                                with ui.column().classes('settings-section w-full'):
                                    ui.label('Toggles & partner').classes(
                                        'settings-section-title')
                                    with ui.column().classes('w-full gap-2'):
                                        za_cb = ui.checkbox(
                                            'Zelfstandigenaftrek (ZA) actief',
                                            value=bool(params.za_actief),
                                        )
                                        if is_locked:
                                            za_cb.props('disable')
                                        inputs['za_actief'] = za_cb

                                        sa_cb = ui.checkbox(
                                            'Startersaftrek (SA) actief —'
                                            ' max 3× in eerste 5 jaar',
                                            value=bool(params.sa_actief),
                                        )
                                        if is_locked:
                                            sa_cb.props('disable')
                                        inputs['sa_actief'] = sa_cb

                                        ew_partner_cb = ui.checkbox(
                                            'Eigen woning saldo aan partner'
                                            ' toerekenen',
                                            value=bool(params.ew_naar_partner),
                                        )
                                        if is_locked:
                                            ew_partner_cb.props('disable')
                                        inputs['ew_naar_partner'] = ew_partner_cb

                                        box3_partner_cb = ui.checkbox(
                                            'Box 3 fiscaal partner'
                                            ' (verdeling 50/50 mogelijk)',
                                            value=bool(params.box3_fiscaal_partner),
                                        )
                                        if is_locked:
                                            box3_partner_cb.props('disable')
                                        inputs['box3_fiscaal_partner'] = box3_partner_cb
                                with ui.column().classes('settings-section w-full'):
                                    ui.label('PVV premies').classes(
                                        'settings-section-title')
                                    pvv_fields = [
                                        ('AOW premie %', 'pvv_aow_pct'),
                                        ('Anw premie %', 'pvv_anw_pct'),
                                        ('Wlz premie %', 'pvv_wlz_pct'),
                                    ]
                                    with ui.grid(columns=2).classes('w-full gap-3'):
                                        for label, key in pvv_fields:
                                            val = getattr(params, key)
                                            inp = ui.number(
                                                label,
                                                value=val if val is not None else 0,
                                                format='%.2f', step=0.01,
                                            ).classes('w-full')
                                            if is_locked:
                                                inp.props('readonly')
                                            inputs[key] = inp
                                with ui.column().classes('settings-section w-full'):
                                    ui.label('Box 3 parameters').classes(
                                        'settings-section-title')
                                    box3_fields = [
                                        ('Heffingsvrij vermogen p.p. \u20ac',
                                         'box3_heffingsvrij_vermogen', '%.0f', 1),
                                        ('Rendement bank %',
                                         'box3_rendement_bank_pct', '%.2f', 0.01),
                                        ('Rendement overig %',
                                         'box3_rendement_overig_pct', '%.2f', 0.01),
                                        ('Rendement schuld %',
                                         'box3_rendement_schuld_pct', '%.2f', 0.01),
                                        ('Box 3 tarief %',
                                         'box3_tarief_pct', '%.0f', 1),
                                        ('Box 3 drempel schulden p.p. \u20ac',
                                         'box3_drempel_schulden', '%.0f', 100),
                                    ]
                                    with ui.grid(columns=2).classes('w-full gap-3'):
                                        for label, key, fmt, step in box3_fields:
                                            val = getattr(params, key)
                                            inp = ui.number(
                                                label,
                                                value=val if val is not None else 0,
                                                format=fmt, step=step,
                                            ).classes('w-full')
                                            if is_locked:
                                                inp.props('readonly')
                                            inputs[key] = inp

                                # Editable arbeidskorting brackets \u2014 list of
                                # ui.row() per schijf with delete button +
                                # add-row button. Stored as `bracket_state`
                                # (list of dicts) and re-rendered into
                                # `ak_container`. On save we json.dumps the
                                # state and pass through upsert_fiscale_params.
                                with ui.column().classes('settings-section w-full'):
                                    ui.label('Arbeidskorting schijven').classes(
                                        'settings-section-title')
                                    ui.label(
                                        'Schijven moeten oplopend en aaneensluitend '
                                        'zijn. Laatste schijf mag een open '
                                        'bovengrens (\u221e) hebben \u2014 laat het '
                                        'veld leeg om dat aan te geven. Tarief '
                                        'als fractie (bijv. 0.31433 voor 31,433%).'
                                    ).classes('text-caption text-grey')

                                    bracket_state: list[dict] = []
                                    if params.arbeidskorting_brackets:
                                        try:
                                            loaded = json.loads(
                                                params.arbeidskorting_brackets)
                                        except json.JSONDecodeError:
                                            loaded = None
                                        # Defensive: only accept a list of dicts.
                                        # Non-list JSON (e.g. {"x": 1}) would
                                        # crash render_brackets() before the
                                        # validator can show a Dutch error.
                                        if isinstance(loaded, list) and all(
                                            isinstance(b, dict) for b in loaded
                                        ):
                                            bracket_state = list(loaded)

                                    ak_container = ui.column().classes('w-full gap-1')

                                    def render_brackets():
                                        ak_container.clear()
                                        with ak_container:
                                            if not bracket_state:
                                                ui.label(
                                                    'Geen schijven \u2014 voeg '
                                                    'minstens 1 schijf toe.'
                                                ).classes('text-grey')
                                                return
                                            with ui.row().classes(
                                                'w-full gap-2 text-caption '
                                                'text-grey-7'
                                            ):
                                                ui.label('Ondergrens \u20ac').classes('w-32')
                                                ui.label('Bovengrens \u20ac (leeg = \u221e)').classes('w-44')
                                                ui.label('Tarief (fractie)').classes('w-32')
                                                ui.label('Basisbedrag \u20ac').classes('w-32')
                                                ui.label('').classes('w-12')
                                            for idx, b in enumerate(bracket_state):
                                                with ui.row().classes(
                                                    'w-full gap-2 items-center'
                                                ):
                                                    lo = ui.number(
                                                        value=b.get('lower') or 0,
                                                        format='%.0f', step=1,
                                                    ).classes('w-32').props('dense')
                                                    up_val = b.get('upper')
                                                    up = ui.number(
                                                        value=up_val if up_val is not None else None,
                                                        format='%.0f', step=1,
                                                        placeholder='\u221e (leeg)',
                                                    ).classes('w-44').props('dense clearable')
                                                    rt = ui.number(
                                                        value=b.get('rate') or 0,
                                                        format='%.5f', step=0.0001,
                                                    ).classes('w-32').props('dense')
                                                    ba = ui.number(
                                                        value=b.get('base') or 0,
                                                        format='%.0f', step=1,
                                                    ).classes('w-32').props('dense')

                                                    def make_writer(i, field, comp,
                                                                    allow_none=False):
                                                        def _w():
                                                            v = comp.value
                                                            if allow_none and (v is None or v == ''):
                                                                bracket_state[i][field] = None
                                                            elif v is None or v == '':
                                                                bracket_state[i][field] = 0
                                                            else:
                                                                bracket_state[i][field] = v
                                                        return _w
                                                    lo.on('update:model-value', make_writer(idx, 'lower', lo))
                                                    up.on('update:model-value', make_writer(idx, 'upper', up, allow_none=True))
                                                    rt.on('update:model-value', make_writer(idx, 'rate', rt))
                                                    ba.on('update:model-value', make_writer(idx, 'base', ba))

                                                    def make_remove(i):
                                                        def _r():
                                                            if 0 <= i < len(bracket_state):
                                                                bracket_state.pop(i)
                                                                render_brackets()
                                                        return _r
                                                    rm_btn = ui.button(
                                                        icon='delete',
                                                        on_click=make_remove(idx),
                                                    ).props('flat dense round color=negative')
                                                    if is_locked:
                                                        lo.props('readonly')
                                                        up.props('readonly')
                                                        rt.props('readonly')
                                                        ba.props('readonly')
                                                        rm_btn.props('disable')

                                    render_brackets()

                                    def add_bracket():
                                        last_upper = 0
                                        if bracket_state:
                                            prev_up = bracket_state[-1].get('upper')
                                            if prev_up is not None:
                                                last_upper = prev_up
                                        bracket_state.append({
                                            'lower': last_upper,
                                            'upper': None,
                                            'rate': 0.0,
                                            'base': 0,
                                        })
                                        render_brackets()
                                    add_bracket_btn = ui.button(
                                        'Schijf toevoegen', icon='add',
                                        on_click=add_bracket,
                                    ).props('flat color=primary').classes('q-mt-xs')
                                    if is_locked:
                                        add_bracket_btn.props('disable')

                                # Capture all_fields for save closure
                                all_fields = (
                                    fields
                                    + pvv_fields
                                    + [(l, k) for l, k, _f, _s
                                       in box3_fields]
                                )

                                async def save_params(
                                    jaar=params.jaar, inps=inputs,
                                    af=all_fields,
                                    bracket_ref=bracket_state,
                                    locked=is_locked,
                                ):
                                    if locked:
                                        ui.notify(
                                            f'Jaar {jaar} is definitief \u2014'
                                            ' heropen via /jaarafsluiting'
                                            ' om te wijzigen.',
                                            type='warning')
                                        return
                                    kwargs = {'jaar': jaar}
                                    for _label, key in af:
                                        val = inps[key].value
                                        # Pass None/empty through as None so
                                        # the validator can distinguish
                                        # "gebruiker heeft veld leeggemaakt"
                                        # van "gebruiker heeft 0 ingetypt".
                                        if val is None or val == '':
                                            kwargs[key] = None
                                        else:
                                            kwargs[key] = val
                                    # Validate AK brackets, then serialize.
                                    ak_errors = _validate_arbeidskorting_brackets(
                                        bracket_ref)
                                    if ak_errors:
                                        for err in ak_errors:
                                            ui.notify(err, type='negative', timeout=5000)
                                        return
                                    kwargs['arbeidskorting_brackets'] = json.dumps(
                                        bracket_ref)
                                    # ZA/SA + partner toggles
                                    kwargs['za_actief'] = int(inps['za_actief'].value)
                                    kwargs['sa_actief'] = int(inps['sa_actief'].value)
                                    kwargs['ew_naar_partner'] = int(
                                        inps['ew_naar_partner'].value)
                                    kwargs['box3_fiscaal_partner'] = int(
                                        inps['box3_fiscaal_partner'].value)

                                    validation_errors = _validate_fiscal_params(kwargs)
                                    if validation_errors:
                                        for err in validation_errors:
                                            ui.notify(err, type='negative', timeout=5000)
                                        return

                                    try:
                                        await upsert_fiscale_params(
                                            DB_PATH, **kwargs)
                                    except YearLockedError as e:
                                        ui.notify(str(e), type='warning',
                                                  timeout=8000)
                                        return
                                    ui.notify(
                                        f'Parameters {jaar} opgeslagen',
                                        type='positive')

                                save_btn = ui.button(
                                    f'Opslaan {params.jaar}', icon='save',
                                    on_click=save_params
                                ).props('color=primary').classes('q-mt-sm')
                                if is_locked:
                                    save_btn.props('disable')

                await refresh_fiscaal()

            with ui.tab_panel(tab_backup):
                with ui.column().classes('w-full gap-4'):

                    # ─── Card 1: Backup downloaden ───────────────────
                    with ui.card().classes('settings-card'):
                        ui.label('Database backup').classes('settings-card-title')
                        ui.label(
                            'Download een atomaire snapshot van de database en alle '
                            'bijbehorende bestanden. Bewaar backups buiten deze machine '
                            '(externe schijf, NAS, of cloudmap). NB: deze snapshot is '
                            'veilig tijdens gebruik — geen WAL races.'
                        ).classes('settings-card-subtitle')

                        async def download_backup():
                            if not DB_PATH.exists():
                                ui.notify('Database niet gevonden', type='warning')
                                return

                            stem = f"boekhouding_backup_{date.today().isoformat()}"
                            tmp_dir = Path(tempfile.mkdtemp(prefix='boekhouding_backup_'))
                            dump_path = tmp_dir / f"{stem}.sqlite3"
                            zip_path = tmp_dir / f"{stem}.zip"

                            safe_dump_path = str(dump_path).replace("'", "''")
                            async with get_db_ctx(DB_PATH) as conn:
                                await conn.execute(f"VACUUM INTO '{safe_dump_path}'")

                            def _create_zip():
                                with zipfile.ZipFile(
                                    zip_path, 'w', zipfile.ZIP_DEFLATED
                                ) as zf:
                                    zf.write(dump_path, 'boekhouding.sqlite3')
                                    for subdir in [
                                        'facturen', 'uitgaven', 'jaarafsluiting',
                                        'bank_csv', 'aangifte', 'logo',
                                    ]:
                                        dir_path = DB_PATH.parent / subdir
                                        if dir_path.exists():
                                            for f in dir_path.rglob('*'):
                                                if f.is_file():
                                                    zf.write(
                                                        f,
                                                        f"{subdir}/"
                                                        f"{f.relative_to(dir_path)}")

                            await asyncio.to_thread(_create_zip)
                            ui.download(str(zip_path))
                            ui.notify(
                                f'Backup {zip_path.name} aangemaakt',
                                type='positive')

                            async def _cleanup():
                                await asyncio.sleep(300)
                                shutil.rmtree(tmp_dir, ignore_errors=True)
                            asyncio.create_task(_cleanup())

                        ui.button(
                            'Download backup', icon='download',
                            on_click=download_backup,
                        ).props('color=primary')

                    # ─── Card 2: Database-locatie + copy-to-clipboard ─
                    with ui.card().classes('settings-card'):
                        ui.label('Database-locatie').classes('settings-card-title')
                        ui.label(
                            'Locatie van de SQLite-database op deze machine. '
                            'Bewaar backups (zie boven) buiten deze locatie.'
                        ).classes('settings-card-subtitle')

                        db_path_str = str(DB_PATH.resolve())

                        with ui.row().classes(
                            'w-full items-center q-gutter-sm'
                        ):
                            ui.label(db_path_str).style(
                                'font-family: "SF Mono", Menlo, monospace;'
                                ' font-size: 13px;'
                                ' background: var(--bg);'
                                ' padding: 8px 12px;'
                                ' border-radius: 6px;'
                                ' border: 1px solid var(--border);'
                                ' user-select: text;'
                                ' flex: 1;'
                                ' overflow-x: auto;')

                            def copy_path():
                                # Pywebview WebKit ondersteunt navigator.clipboard
                                ui.run_javascript(
                                    f'navigator.clipboard.writeText('
                                    f'{json.dumps(db_path_str)})')
                                ui.notify('Pad gekopieerd naar klembord',
                                          type='positive')

                            ui.button(
                                icon='content_copy', on_click=copy_path,
                            ).props('flat dense round').tooltip('Kopieer pad')
