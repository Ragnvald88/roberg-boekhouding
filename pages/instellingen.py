"""Instellingen pagina — klanten beheer, fiscale parameters, backup."""

from datetime import date
import io
import zipfile

from nicegui import ui

from components.layout import create_layout
from components.utils import format_euro
from database import (
    get_klanten, add_klant, update_klant, delete_klant,
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

                            table.on('edit', on_edit)
                            table.on('toggle', on_toggle)

                await refresh_klanten()

            # === TAB: Fiscale parameters ===
            with ui.tab_panel(tab_fiscaal):
                fiscaal_container = ui.column().classes('w-full')

                async def refresh_fiscaal():
                    fiscaal_container.clear()
                    params_list = await get_all_fiscale_params(DB_PATH)

                    with fiscaal_container:
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
                                        ('Schijf 1 grens', 'schijf1_grens'),
                                        ('Schijf 1 %', 'schijf1_pct'),
                                        ('Schijf 2 grens', 'schijf2_grens'),
                                        ('Schijf 2 %', 'schijf2_pct'),
                                        ('Schijf 3 %', 'schijf3_pct'),
                                        ('AHK max', 'ahk_max'),
                                        ('AHK afbouw %', 'ahk_afbouw_pct'),
                                        ('AHK drempel', 'ahk_drempel'),
                                        ('AK max', 'ak_max'),
                                        ('ZVW %', 'zvw_pct'),
                                        ('ZVW max grondslag', 'zvw_max_grondslag'),
                                    ]
                                    inputs = {}
                                    for label, key in fields:
                                        val = getattr(params, key)
                                        inp = ui.number(
                                            label, value=val if val is not None else 0,
                                            format='%.2f'
                                        ).classes('w-full')
                                        inputs[key] = inp

                                async def save_params(jaar=params.jaar, inps=inputs):
                                    kwargs = {'jaar': jaar, 'repr_aftrek_pct': 80}
                                    for label, key in fields:
                                        val = inps[key].value
                                        kwargs[key] = val if val else 0
                                    await upsert_fiscale_params(DB_PATH, **kwargs)
                                    ui.notify(f'Parameters {jaar} opgeslagen',
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
                        # Factuur PDFs
                        factuur_dir = DB_PATH.parent / "facturen"
                        if factuur_dir.exists():
                            for pdf in factuur_dir.glob("*.pdf"):
                                zf.write(pdf, f"facturen/{pdf.name}")

                    ui.download(str(backup_path))
                    ui.notify(f'Backup {backup_name} aangemaakt', type='positive')

                ui.button('Download backup', icon='download',
                          on_click=download_backup).props('color=primary')

                ui.separator().classes('q-my-lg')
                ui.label('Database locatie').classes('text-subtitle2')
                ui.label(str(DB_PATH.resolve())).classes('text-caption text-grey')
