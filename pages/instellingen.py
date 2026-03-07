"""Instellingen pagina — klanten beheer, fiscale parameters, backup."""

from datetime import date
import io
import json
import zipfile

from nicegui import ui

from components.layout import create_layout
from components.utils import format_euro
from database import (
    get_klanten, add_klant, update_klant, delete_klant,
    get_klant_locaties, add_klant_locatie, delete_klant_locatie,
    get_all_fiscale_params, upsert_fiscale_params,
    get_bedrijfsgegevens, upsert_bedrijfsgegevens, DB_PATH,
)


@ui.page('/instellingen')
async def instellingen_page():
    create_layout('Instellingen', '/instellingen')

    with ui.column().classes('w-full p-6 max-w-7xl mx-auto gap-6'):
        ui.label('Instellingen').classes('text-h5') \
            .style('color: #0F172A; font-weight: 700')

        with ui.tabs().classes('w-full') as tabs:
            tab_bedrijf = ui.tab('Bedrijfsgegevens')
            tab_klanten = ui.tab('Klanten')
            tab_fiscaal = ui.tab('Fiscale parameters')
            tab_backup = ui.tab('Backup')

        with ui.tab_panels(tabs, value=tab_bedrijf).classes('w-full'):

            # === TAB: Bedrijfsgegevens ===
            with ui.tab_panel(tab_bedrijf):
                bedrijf_container = ui.column().classes('w-full')

                async def refresh_bedrijf():
                    bedrijf_container.clear()
                    bg = await get_bedrijfsgegevens(DB_PATH)

                    with bedrijf_container:
                        ui.label(
                            'Deze gegevens worden gebruikt op facturen.'
                        ).classes('text-body2 text-grey q-mb-md')

                        with ui.card().classes('w-full'):
                            fields = {}
                            for label, key in [
                                ('Bedrijfsnaam', 'bedrijfsnaam'),
                                ('Naam', 'naam'),
                                ('Functie', 'functie'),
                                ('Adres', 'adres'),
                                ('Postcode + Plaats', 'postcode_plaats'),
                                ('KvK-nummer', 'kvk'),
                                ('IBAN', 'iban'),
                                ('Thuisplaats (voor reiskosten)', 'thuisplaats'),
                            ]:
                                val = getattr(bg, key, '') if bg else ''
                                fields[key] = ui.input(
                                    label, value=val or ''
                                ).classes('w-full')

                            async def save_bedrijf():
                                kwargs = {k: v.value or '' for k, v in fields.items()}
                                await upsert_bedrijfsgegevens(DB_PATH, **kwargs)
                                ui.notify('Bedrijfsgegevens opgeslagen', type='positive')

                            ui.button(
                                'Opslaan', icon='save', on_click=save_bedrijf
                            ).props('color=primary').classes('q-mt-md')

                await refresh_bedrijf()

            # === TAB: Klanten ===
            with ui.tab_panel(tab_klanten):
                klanten_container = ui.column().classes('w-full')

                async def refresh_klanten():
                    klanten_container.clear()
                    klanten = await get_klanten(DB_PATH)

                    with klanten_container:
                        # Add form
                        with ui.card().classes('w-full q-mb-md'):
                            ui.label('Klant toevoegen').classes('text-subtitle1 text-bold')
                            with ui.row().classes('w-full items-end gap-4 flex-wrap'):
                                new_naam = ui.input('Naam').classes('w-48')
                                new_tarief = ui.number('Tarief/uur (€)', value=0,
                                                        min=0, step=0.50).classes('w-32')
                                new_km = ui.number('Retour km', value=0,
                                                    min=0).classes('w-24')
                                new_adres = ui.input('Adres').classes('w-64')

                                async def add_new():
                                    if not new_naam.value:
                                        ui.notify('Vul een naam in', type='warning')
                                        return
                                    await add_klant(DB_PATH, naam=new_naam.value,
                                                    tarief_uur=new_tarief.value or 0,
                                                    retour_km=new_km.value or 0,
                                                    adres=new_adres.value or '')
                                    ui.notify(f'Klant {new_naam.value} toegevoegd',
                                              type='positive')
                                    new_naam.value = ''
                                    new_adres.value = ''
                                    await refresh_klanten()

                                ui.button('Toevoegen', icon='add',
                                          on_click=add_new).props('color=primary')

                        # Klanten table
                        if not klanten:
                            ui.label('Geen klanten gevonden.').classes('text-grey')
                        else:
                            columns = [
                                {'name': 'naam', 'label': 'Naam', 'field': 'naam',
                                 'align': 'left'},
                                {'name': 'tarief', 'label': 'Tarief/uur',
                                 'field': 'tarief_fmt', 'align': 'right'},
                                {'name': 'km', 'label': 'Retour km', 'field': 'retour_km',
                                 'align': 'right'},
                                {'name': 'adres', 'label': 'Adres', 'field': 'adres',
                                 'align': 'left'},
                                {'name': 'actief', 'label': 'Actief', 'field': 'actief_txt',
                                 'align': 'center'},
                                {'name': 'actions', 'label': '', 'field': 'actions',
                                 'align': 'center'},
                            ]

                            rows = [{
                                'id': k.id,
                                'naam': k.naam,
                                'tarief_uur': k.tarief_uur,
                                'tarief_fmt': format_euro(k.tarief_uur),
                                'retour_km': k.retour_km,
                                'adres': k.adres,
                                'actief': k.actief,
                                'actief_txt': 'Ja' if k.actief else 'Nee',
                            } for k in klanten]

                            table = ui.table(
                                columns=columns, rows=rows, row_key='id',
                            ).classes('w-full')

                            table.add_slot('body-cell-actions', '''
                                <q-td :props="props">
                                    <q-btn icon="edit" flat dense round size="sm"
                                        @click="() => $parent.$emit('edit', props.row)" />
                                    <q-btn :icon="props.row.actief ? 'visibility_off' : 'visibility'"
                                        flat dense round size="sm"
                                        :color="props.row.actief ? 'orange' : 'green'"
                                        @click="() => $parent.$emit('toggle', props.row)" />
                                    <q-btn icon="delete" flat dense round size="sm"
                                        color="negative"
                                        @click="() => $parent.$emit('deleteklant', props.row)" />
                                </q-td>
                            ''')

                            async def on_edit(e):
                                row = e.args
                                with ui.dialog() as dialog, ui.card().classes('w-96'):
                                    ui.label('Klant bewerken').classes('text-h6')
                                    ed_naam = ui.input('Naam', value=row['naam']).classes('w-full')
                                    ed_tarief = ui.number('Tarief/uur (€)',
                                                          value=row['tarief_uur']).classes('w-full')
                                    ed_km = ui.number('Retour km',
                                                      value=row['retour_km']).classes('w-full')
                                    ed_adres = ui.input('Adres',
                                                        value=row['adres']).classes('w-full')

                                    # --- Locaties sub-section ---
                                    ui.separator().classes('q-my-sm')
                                    ui.label('Locaties').classes(
                                        'text-subtitle2 text-weight-medium')
                                    ui.label(
                                        'Werklocaties met retourafstand (km). '
                                        'Verschijnt als dropdown in het '
                                        'werkdagformulier.'
                                    ).classes('text-caption text-grey')

                                    loc_container = ui.column().classes(
                                        'w-full gap-1')

                                    async def refresh_locaties():
                                        loc_container.clear()
                                        klant_id = row['id']
                                        locaties = await get_klant_locaties(
                                            DB_PATH, klant_id)
                                        with loc_container:
                                            for loc in locaties:
                                                with ui.row().classes(
                                                    'w-full items-center gap-2'
                                                ):
                                                    ui.label(loc.naam).classes(
                                                        'flex-grow')
                                                    ui.label(
                                                        f'{loc.retour_km:.0f} km'
                                                    ).classes(
                                                        'text-caption text-grey')

                                                    async def del_loc(
                                                        lid=loc.id,
                                                    ):
                                                        await delete_klant_locatie(
                                                            DB_PATH, lid)
                                                        ui.notify(
                                                            'Locatie verwijderd',
                                                            type='info')
                                                        await refresh_locaties()

                                                    ui.button(
                                                        icon='close',
                                                        on_click=del_loc,
                                                    ).props(
                                                        'flat dense round '
                                                        'size=sm color=negative'
                                                    )

                                            # Add new location row
                                            with ui.row().classes(
                                                'w-full items-end gap-2'
                                            ):
                                                new_loc_naam = ui.input(
                                                    'Locatienaam',
                                                ).classes(
                                                    'flex-grow'
                                                ).props('dense')
                                                new_loc_km = ui.number(
                                                    'Km retour', value=0,
                                                    min=0,
                                                ).classes('w-24').props('dense')

                                                async def add_loc():
                                                    naam = new_loc_naam.value
                                                    km = new_loc_km.value or 0
                                                    if not naam:
                                                        ui.notify(
                                                            'Vul een locatienaam'
                                                            ' in',
                                                            type='warning')
                                                        return
                                                    try:
                                                        await add_klant_locatie(
                                                            DB_PATH, row['id'],
                                                            naam, km)
                                                    except Exception:
                                                        ui.notify(
                                                            f'Locatie "{naam}" '
                                                            f'bestaat al',
                                                            type='warning')
                                                        return
                                                    ui.notify(
                                                        f'Locatie "{naam}" '
                                                        f'toegevoegd',
                                                        type='positive')
                                                    await refresh_locaties()

                                                ui.button(
                                                    icon='add',
                                                    on_click=add_loc,
                                                ).props(
                                                    'flat dense round '
                                                    'color=primary'
                                                )

                                    await refresh_locaties()

                                    with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                                        ui.button('Annuleren', on_click=dialog.close).props('flat')

                                        async def save_edit():
                                            await update_klant(
                                                DB_PATH, klant_id=row['id'],
                                                naam=ed_naam.value,
                                                tarief_uur=ed_tarief.value,
                                                retour_km=ed_km.value,
                                                adres=ed_adres.value,
                                            )
                                            dialog.close()
                                            ui.notify('Klant bijgewerkt', type='positive')
                                            await refresh_klanten()

                                        ui.button('Opslaan', on_click=save_edit) \
                                            .props('color=primary')
                                dialog.open()

                            async def on_toggle(e):
                                row = e.args
                                new_actief = 0 if row['actief'] else 1
                                await update_klant(DB_PATH, klant_id=row['id'],
                                                   actief=new_actief)
                                status = 'geactiveerd' if new_actief else 'gedeactiveerd'
                                ui.notify(f"{row['naam']} {status}", type='info')
                                await refresh_klanten()

                            async def on_delete_klant(e):
                                row = e.args
                                with ui.dialog() as dialog, ui.card():
                                    ui.label(f"Klant '{row['naam']}' verwijderen?").classes('text-h6')
                                    ui.label(
                                        'Let op: werkdagen en facturen gekoppeld aan deze '
                                        'klant worden NIET verwijderd.'
                                    ).classes('text-body2 text-grey')
                                    with ui.row().classes('w-full justify-end gap-2 q-mt-md'):
                                        ui.button('Annuleren', on_click=dialog.close).props('flat')

                                        async def confirm_del(kid=row['id'], dlg=dialog):
                                            await delete_klant(DB_PATH, klant_id=kid)
                                            dlg.close()
                                            ui.notify(f"Klant verwijderd", type='positive')
                                            await refresh_klanten()

                                        ui.button('Verwijderen', on_click=confirm_del) \
                                            .props('color=negative')
                                dialog.open()

                            table.on('edit', on_edit)
                            table.on('toggle', on_toggle)
                            table.on('deleteklant', on_delete_klant)

                await refresh_klanten()

            # === TAB: Fiscale parameters ===
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
                                # Copy from most recent year as template
                                if params_list:
                                    latest = params_list[-1]
                                    kwargs = {
                                        'jaar': jaar,
                                        'zelfstandigenaftrek': latest.zelfstandigenaftrek,
                                        'startersaftrek': latest.startersaftrek,
                                        'mkb_vrijstelling_pct': latest.mkb_vrijstelling_pct,
                                        'kia_ondergrens': latest.kia_ondergrens,
                                        'kia_bovengrens': latest.kia_bovengrens,
                                        'kia_pct': latest.kia_pct,
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
                                    }
                                else:
                                    kwargs = {'jaar': jaar, 'zelfstandigenaftrek': 0,
                                              'mkb_vrijstelling_pct': 12.70,
                                              'kia_ondergrens': 2901, 'kia_bovengrens': 70602,
                                              'kia_pct': 28, 'km_tarief': 0.23,
                                              'schijf1_grens': 38883, 'schijf1_pct': 35.75,
                                              'schijf2_grens': 78426, 'schijf2_pct': 37.56,
                                              'schijf3_pct': 49.50, 'ahk_max': 3115,
                                              'ahk_afbouw_pct': 6.398, 'ahk_drempel': 29736,
                                              'ak_max': 5685, 'zvw_pct': 4.85,
                                              'zvw_max_grondslag': 79409}
                                await upsert_fiscale_params(DB_PATH, **kwargs)
                                ui.notify(f'Jaar {jaar} toegevoegd (kopieer van {params_list[-1].jaar if params_list else "standaard"})',
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
                                with ui.grid(columns=2).classes('gap-2 w-full'):
                                    fields = [
                                        ('Zelfstandigenaftrek', 'zelfstandigenaftrek'),
                                        ('Startersaftrek', 'startersaftrek'),
                                        ('MKB-vrijstelling %', 'mkb_vrijstelling_pct'),
                                        ('KIA ondergrens', 'kia_ondergrens'),
                                        ('KIA bovengrens', 'kia_bovengrens'),
                                        ('KIA %', 'kia_pct'),
                                        ('Km-tarief', 'km_tarief'),
                                        ('Representatie aftrek %', 'repr_aftrek_pct'),
                                        ('Schijf 1 grens', 'schijf1_grens'),
                                        ('Schijf 1 %', 'schijf1_pct'),
                                        ('Schijf 2 grens', 'schijf2_grens'),
                                        ('Schijf 2 %', 'schijf2_pct'),
                                        ('Schijf 3 %', 'schijf3_pct'),
                                        ('PVV premiegrondslag', 'pvv_premiegrondslag'),
                                        ('AHK max', 'ahk_max'),
                                        ('AHK afbouw %', 'ahk_afbouw_pct'),
                                        ('AHK drempel', 'ahk_drempel'),
                                        ('AK max', 'ak_max'),
                                        ('ZVW %', 'zvw_pct'),
                                        ('ZVW max grondslag', 'zvw_max_grondslag'),
                                        ('EW forfait %', 'ew_forfait_pct'),
                                        ('Villataks grens', 'villataks_grens'),
                                        ('Wet Hillen %', 'wet_hillen_pct'),
                                        ('Urencriterium', 'urencriterium'),
                                    ]
                                    inputs = {}
                                    for label, key in fields:
                                        val = getattr(params, key)
                                        inp = ui.number(
                                            label, value=val if val is not None else 0,
                                            format='%.2f'
                                        ).classes('w-full')
                                        inputs[key] = inp

                                # --- PVV premies ---
                                ui.label('PVV premies').classes(
                                    'text-subtitle2 mt-4')
                                pvv_fields = [
                                    ('AOW premie %', 'pvv_aow_pct'),
                                    ('Anw premie %', 'pvv_anw_pct'),
                                    ('Wlz premie %', 'pvv_wlz_pct'),
                                ]
                                with ui.row().classes('gap-4'):
                                    for label, key in pvv_fields:
                                        val = getattr(params, key)
                                        inp = ui.number(
                                            label,
                                            value=val if val is not None else 0,
                                            format='%.2f', step=0.01,
                                        )
                                        inputs[key] = inp

                                # --- Box 3 parameters ---
                                ui.label('Box 3 parameters').classes(
                                    'text-subtitle2 mt-4')
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
                                with ui.row().classes('gap-4 flex-wrap'):
                                    for label, key, fmt, step in box3_fields:
                                        val = getattr(params, key)
                                        inp = ui.number(
                                            label,
                                            value=val if val is not None else 0,
                                            format=fmt, step=step,
                                        )
                                        inputs[key] = inp

                                # --- Arbeidskorting schijven (read-only) ---
                                ui.label('Arbeidskorting schijven').classes(
                                    'text-subtitle2 mt-4')
                                if params.arbeidskorting_brackets:
                                    try:
                                        brackets = json.loads(
                                            params.arbeidskorting_brackets)
                                        ak_columns = [
                                            {'name': 'lower',
                                             'label': 'Ondergrens',
                                             'field': 'lower',
                                             'align': 'right'},
                                            {'name': 'upper',
                                             'label': 'Bovengrens',
                                             'field': 'upper',
                                             'align': 'right'},
                                            {'name': 'rate',
                                             'label': 'Tarief %',
                                             'field': 'rate',
                                             'align': 'right'},
                                            {'name': 'base',
                                             'label': 'Basisbedrag',
                                             'field': 'base',
                                             'align': 'right'},
                                        ]
                                        ak_rows = []
                                        for b in brackets:
                                            ak_rows.append({
                                                'lower': (
                                                    f"\u20ac {b['lower']:,.0f}"),
                                                'upper': (
                                                    f"\u20ac {b['upper']:,.0f}"
                                                    if b['upper']
                                                    else '\u221e'),
                                                'rate': (
                                                    f"{b['rate']*100:.3f}%"),
                                                'base': (
                                                    f"\u20ac {b['base']:,.0f}"),
                                            })
                                        ui.table(
                                            columns=ak_columns, rows=ak_rows,
                                        ).classes('w-full').props(
                                            'dense flat')
                                    except (json.JSONDecodeError, KeyError):
                                        ui.label(
                                            'Geen bracket data beschikbaar'
                                        ).classes('text-grey')
                                else:
                                    ui.label(
                                        'Brackets uit standaard Python-code'
                                    ).classes('text-grey')

                                # --- Save button ---
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
                                    ak_json=params.arbeidskorting_brackets,
                                ):
                                    kwargs = {'jaar': jaar}
                                    for _label, key in af:
                                        val = inps[key].value
                                        kwargs[key] = val if val else 0
                                    # Pass through AK brackets unchanged
                                    kwargs['arbeidskorting_brackets'] = ak_json
                                    await upsert_fiscale_params(
                                        DB_PATH, **kwargs)
                                    ui.notify(
                                        f'Parameters {jaar} opgeslagen',
                                        type='positive')

                                ui.button(
                                    f'Opslaan {params.jaar}', icon='save',
                                    on_click=save_params
                                ).props('color=primary').classes('q-mt-sm')

                await refresh_fiscaal()

            # === TAB: Backup ===
            with ui.tab_panel(tab_backup):
                ui.label('Database backup').classes('text-subtitle1 text-bold q-mb-md')
                ui.label(
                    'Download een kopie van de database en alle bijbehorende bestanden. '
                    'De database wordt ook automatisch gesynchroniseerd via SynologyDrive.'
                ).classes('text-body2 text-grey q-mb-md')

                async def download_backup():
                    """Create a ZIP with the SQLite database."""
                    if not DB_PATH.exists():
                        ui.notify('Database niet gevonden', type='warning')
                        return

                    backup_name = f"boekhouding_backup_{date.today().isoformat()}.zip"
                    backup_path = DB_PATH.parent / backup_name

                    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                        # Database
                        if DB_PATH.exists():
                            zf.write(DB_PATH, 'boekhouding.sqlite3')
                        # Include all data subdirectories
                        for subdir in ['facturen', 'uitgaven', 'jaarafsluiting', 'bank_csv', 'aangifte']:
                            dir_path = DB_PATH.parent / subdir
                            if dir_path.exists():
                                for f in dir_path.rglob('*'):
                                    if f.is_file():
                                        zf.write(f, f"{subdir}/{f.relative_to(dir_path)}")

                    ui.download(str(backup_path))
                    ui.notify(f'Backup {backup_name} aangemaakt', type='positive')

                ui.button('Download backup', icon='download',
                          on_click=download_backup).props('color=primary')

                ui.separator().classes('q-my-lg')
                ui.label('Database locatie').classes('text-subtitle2')
                ui.label(str(DB_PATH.resolve())).classes('text-caption text-grey')
