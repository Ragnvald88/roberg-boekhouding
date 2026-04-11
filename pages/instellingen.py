"""Instellingen pagina — bedrijfsgegevens, fiscale parameters, backup."""

import asyncio
from datetime import date
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from nicegui import ui

from components.layout import create_layout, page_title
from database import (
    get_all_fiscale_params, upsert_fiscale_params,
    get_bedrijfsgegevens, upsert_bedrijfsgegevens, get_db_ctx, DB_PATH,
)


def _validate_fiscal_params(p: dict) -> list[str]:
    """Return a list of human-readable Dutch validation errors, or [] if valid."""
    errors: list[str] = []

    s1_grens = p.get('schijf1_grens', 0) or 0
    s2_grens = p.get('schijf2_grens', 0) or 0
    if s1_grens <= 0:
        errors.append('Schijf 1 grens moet groter dan 0 zijn')
    if s2_grens < s1_grens:
        errors.append('Schijf 2 grens moet groter of gelijk zijn aan schijf 1 grens')

    for fld in ('schijf1_pct', 'schijf2_pct', 'schijf3_pct'):
        v = p.get(fld, 0) or 0
        if not (0 < v < 100):
            errors.append(f'{fld} moet tussen 0 en 100 liggen (nu: {v})')

    for fld in ('mkb_vrijstelling_pct', 'kia_pct'):
        v = p.get(fld, 0) or 0
        if not (0 <= v <= 100):
            errors.append(f'{fld} moet tussen 0 en 100 liggen (nu: {v})')

    for fld in ('ahk_max', 'ahk_drempel', 'ak_max',
                'kia_ondergrens', 'kia_bovengrens',
                'zelfstandigenaftrek'):
        v = p.get(fld, 0) or 0
        if v < 0:
            errors.append(f'{fld} mag niet negatief zijn')

    kia_onder = p.get('kia_ondergrens', 0) or 0
    kia_boven = p.get('kia_bovengrens', 0) or 0
    if kia_boven < kia_onder:
        errors.append('KIA bovengrens moet groter of gelijk zijn aan KIA ondergrens')

    for fld in ('pvv_aow_pct', 'pvv_anw_pct', 'pvv_wlz_pct', 'zvw_pct',
                'ew_forfait_pct', 'repr_aftrek_pct'):
        v = p.get(fld, 0) or 0
        if not (0 <= v <= 100):
            errors.append(f'{fld} moet tussen 0 en 100 liggen (nu: {v})')

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
                                ('Telefoon', 'telefoon'),
                                ('E-mail', 'email'),
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

                        # Logo upload section
                        with ui.card().classes('w-full q-mt-md'):
                            ui.label('Bedrijfslogo').classes(
                                'text-subtitle2 text-grey-8')
                            ui.label(
                                'Upload een logo dat op facturen wordt getoond.'
                            ).classes('text-caption text-grey')

                            logo_dir = DB_PATH.parent / 'logo'
                            logo_dir.mkdir(parents=True, exist_ok=True)
                            logo_files = list(logo_dir.glob('logo.*'))

                            logo_preview = ui.column().classes('q-mt-sm')
                            if logo_files:
                                with logo_preview:
                                    ui.image(
                                        f'/logo-files/{logo_files[0].name}'
                                    ).classes('w-48')

                            async def handle_logo_upload(e):
                                content = await e.file.read()
                                ext = e.file.name.rsplit('.', 1)[-1].lower()
                                # Remove any existing logo files
                                for f in logo_dir.glob('logo.*'):
                                    await asyncio.to_thread(f.unlink)
                                dest = logo_dir / f'logo.{ext}'
                                await asyncio.to_thread(dest.write_bytes, content)
                                logo_preview.clear()
                                with logo_preview:
                                    ui.image(
                                        f'/logo-files/logo.{ext}'
                                    ).classes('w-48')
                                ui.notify('Logo opgeslagen', type='positive')

                            ui.upload(
                                label='Upload logo', auto_upload=True,
                                on_upload=handle_logo_upload,
                                max_file_size=5_000_000,
                            ).props(
                                'flat bordered accept=".png,.jpg,.jpeg,.svg"'
                            ).classes('w-full q-mt-sm')

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
                                        'kia_drempel_per_item': latest.kia_drempel_per_item,
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
                                    }
                                else:
                                    kwargs = {'jaar': jaar, 'zelfstandigenaftrek': 0,
                                              'mkb_vrijstelling_pct': 12.70,
                                              'kia_ondergrens': 2901, 'kia_bovengrens': 70602,
                                              'kia_pct': 28, 'kia_drempel_per_item': 450,
                                              'km_tarief': 0.23,
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
                                    # Grouped fields with section headers
                                    grouped_fields = [
                                        ('IB Schijven', [
                                            ('Schijf 1 grens', 'schijf1_grens'),
                                            ('Schijf 1 %', 'schijf1_pct'),
                                            ('Schijf 2 grens', 'schijf2_grens'),
                                            ('Schijf 2 %', 'schijf2_pct'),
                                            ('Schijf 3 %', 'schijf3_pct'),
                                            ('PVV premiegrondslag', 'pvv_premiegrondslag'),
                                        ]),
                                        ('Ondernemersaftrek', [
                                            ('Zelfstandigenaftrek', 'zelfstandigenaftrek'),
                                            ('Startersaftrek', 'startersaftrek'),
                                            ('MKB-vrijstelling %', 'mkb_vrijstelling_pct'),
                                        ]),
                                        ('Investeringsaftrek', [
                                            ('KIA %', 'kia_pct'),
                                            ('KIA ondergrens', 'kia_ondergrens'),
                                            ('KIA bovengrens', 'kia_bovengrens'),
                                            ('KIA drempel per item', 'kia_drempel_per_item'),
                                        ]),
                                        ('Heffingskortingen', [
                                            ('AHK max', 'ahk_max'),
                                            ('AHK afbouw %', 'ahk_afbouw_pct'),
                                            ('AHK drempel', 'ahk_drempel'),
                                            ('AK max', 'ak_max'),
                                        ]),
                                        ('ZVW', [
                                            ('ZVW %', 'zvw_pct'),
                                            ('ZVW max grondslag', 'zvw_max_grondslag'),
                                        ]),
                                        ('Eigen woning', [
                                            ('EW forfait %', 'ew_forfait_pct'),
                                            ('Villataks grens', 'villataks_grens'),
                                            ('Wet Hillen %', 'wet_hillen_pct'),
                                        ]),
                                        ('Overig', [
                                            ('Km-tarief', 'km_tarief'),
                                            ('Representatie aftrek %', 'repr_aftrek_pct'),
                                            ('Urencriterium', 'urencriterium'),
                                        ]),
                                    ]
                                    # Flat list for save logic
                                    fields = []
                                    inputs = {}
                                    for section, section_fields in grouped_fields:
                                        ui.label(section).classes(
                                            'text-subtitle2 text-weight-bold '
                                            'text-grey-7 col-span-2 q-mt-md')
                                        for label, key in section_fields:
                                            fields.append((label, key))
                                            val = getattr(params, key)
                                            inp = ui.number(
                                                label, value=val if val is not None else 0,
                                                format='%.2f'
                                            ).classes('w-full')
                                            inputs[key] = inp
                                ui.label('Ondernemersaftrek toggles').classes(
                                    'text-subtitle2 mt-4')
                                za_cb = ui.checkbox(
                                    'ZA actief',
                                    value=params.za_actief,
                                )
                                inputs['za_actief'] = za_cb
                                sa_cb = ui.checkbox(
                                    'SA actief (max 3x in eerste 5 jaar)',
                                    value=params.sa_actief,
                                )
                                inputs['sa_actief'] = sa_cb
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
                                    # ZA/SA toggles (checkbox .value is bool)
                                    kwargs['za_actief'] = int(inps['za_actief'].value)
                                    kwargs['sa_actief'] = int(inps['sa_actief'].value)

                                    validation_errors = _validate_fiscal_params(kwargs)
                                    if validation_errors:
                                        for err in validation_errors:
                                            ui.notify(err, type='negative', timeout=5000)
                                        return

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

            with ui.tab_panel(tab_backup):
                ui.label('Database backup').classes('text-subtitle1 text-bold q-mb-md')
                ui.label(
                    'Download een atomaire snapshot van de database en alle bijbehorende bestanden. '
                    'Bewaar backups buiten deze machine (externe schijf, NAS, of cloudmap). '
                    'NB: deze snapshot is veilig tijdens gebruik — geen WAL races.'
                ).classes('text-body2 text-grey q-mb-md')

                async def download_backup():
                    if not DB_PATH.exists():
                        ui.notify('Database niet gevonden', type='warning')
                        return

                    stem = f"boekhouding_backup_{date.today().isoformat()}"
                    tmp_dir = Path(tempfile.mkdtemp(prefix='boekhouding_backup_'))
                    dump_path = tmp_dir / f"{stem}.sqlite3"
                    zip_path = tmp_dir / f"{stem}.zip"

                    # VACUUM INTO produces an atomic, consistent snapshot — no WAL races.
                    # Escape single quotes in the path for SQL safety (VACUUM INTO can't use bound params)
                    safe_dump_path = str(dump_path).replace("'", "''")
                    async with get_db_ctx(DB_PATH) as conn:
                        await conn.execute(f"VACUUM INTO '{safe_dump_path}'")

                    def _create_zip():
                        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                            zf.write(dump_path, 'boekhouding.sqlite3')
                            for subdir in ['facturen', 'uitgaven', 'jaarafsluiting', 'bank_csv', 'aangifte', 'logo']:
                                dir_path = DB_PATH.parent / subdir
                                if dir_path.exists():
                                    for f in dir_path.rglob('*'):
                                        if f.is_file():
                                            zf.write(f, f"{subdir}/{f.relative_to(dir_path)}")

                    await asyncio.to_thread(_create_zip)
                    ui.download(str(zip_path))
                    ui.notify(f'Backup {zip_path.name} aangemaakt', type='positive')

                    async def _cleanup():
                        await asyncio.sleep(300)
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    asyncio.create_task(_cleanup())

                ui.button('Download backup', icon='download',
                          on_click=download_backup).props('color=primary')

                ui.separator().classes('q-my-lg')
                ui.label('Database locatie').classes('text-subtitle2')
                ui.label(str(DB_PATH.resolve())).classes('text-caption text-grey')
