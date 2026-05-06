"""VA-tracker drill-down page — Sprint J T1.4.

Click-doel van de /dashboard VA-tile. Toont per IB en ZVW:
- Actieve beschikking (PDF-link, aanslagnummer, dagtekening, bedrag)
- Per-termijn schedule (feb-dec voor 11-termijn, jan-dec voor 12)
  met paid / expected / future status
- Bank-transacties gematched op kenmerk-classificatie
- Unmatched BD-tx onderaan (audit-zichtbaarheid)

Year-lock policy: bij definitief jaar wordt geen upload-CTA getoond
(read-only audit-view). Mutaties leven in /documenten en /aangifte —
deze page is puur een drill-down view.
"""
from datetime import date
from pathlib import Path

from nicegui import ui

from components.layout import create_layout, page_title
from components.utils import format_euro, format_datum_kort_nl
from database import (
    DB_PATH,
    get_active_voorlopige_aanslag,
    get_fiscale_params,
    get_va_betalingen_detail,
)
from services.dashboard import compute_va_termijnen_schedule

AANGIFTE_DIR = DB_PATH.parent / 'aangifte'

# /aangifte-files static-mount wordt al door pages/documenten.py
# geregistreerd. Idempotente herregistratie zou een SecondLifecycle
# error geven, dus we leunen op de import-volgorde in main.py
# (pages.documenten is altijd geïmporteerd vóór pages.va_tracker).


def _doc_preview_url(bestandspad: str | None) -> str | None:
    """Return /aangifte-files-relatieve URL of None bij missing/buiten dir."""
    if not bestandspad:
        return None
    p = Path(bestandspad)
    if not p.exists():
        return None
    try:
        rel = p.relative_to(AANGIFTE_DIR)
        return f'/aangifte-files/{rel}'
    except ValueError:
        return f'/aangifte-files/{p.name}'


@ui.page('/va-tracker/{jaar}')
async def va_tracker_page(jaar: int):
    """Drill-down view voor de Voorlopige Aanslag van één boekjaar."""
    create_layout(f'Voorlopige aanslag {jaar}', '/va-tracker')

    fp = await get_fiscale_params(DB_PATH, jaar)
    is_locked = (
        fp is not None
        and getattr(fp, 'jaarafsluiting_status', 'concept') == 'definitief'
    )

    ib_b = await get_active_voorlopige_aanslag(DB_PATH, jaar, 'ib')
    zvw_b = await get_active_voorlopige_aanslag(DB_PATH, jaar, 'zvw')
    bank_detail = await get_va_betalingen_detail(DB_PATH, jaar)

    today = date.today()

    with ui.column().classes('w-full p-6 max-w-5xl mx-auto gap-4'):
        with ui.row().classes('w-full items-center justify-between'):
            page_title(f'Voorlopige aanslag {jaar}')
            ui.button(
                'Naar /aangifte',
                icon='arrow_outward',
                on_click=lambda j=jaar: ui.navigate.to(f'/aangifte?jaar={j}'),
            ).props('flat')

        if is_locked:
            with ui.row().classes('w-full items-center q-pa-sm'):
                ui.icon('lock').classes('text-warning')
                ui.label(
                    f'Jaar {jaar} is afgesloten — read-only weergave.'
                ).classes('text-warning text-sm q-ml-sm')

        # IB section
        await _render_soort_section(
            soort='ib', label='Inkomstenbelasting',
            beschikking=ib_b, fp=fp,
            bank_detail=[t for t in bank_detail
                         if t['classification'] == 'ib_matched'],
            today=today, jaar=jaar, is_locked=is_locked,
        )

        # ZVW section
        await _render_soort_section(
            soort='zvw', label='Zorgverzekeringswet',
            beschikking=zvw_b, fp=fp,
            bank_detail=[t for t in bank_detail
                         if t['classification'] == 'zvw_matched'],
            today=today, jaar=jaar, is_locked=is_locked,
        )

        # Unmatched BD-betalingen (audit)
        unmatched = [t for t in bank_detail
                     if t['classification'] == 'unmatched']
        if unmatched:
            total_unmatched = sum(t['bedrag'] for t in unmatched)
            with ui.expansion(
                f'Niet-toegewezen Belastingdienst-betalingen '
                f'({len(unmatched)} · {format_euro(total_unmatched)})',
                icon='warning',
            ).classes('w-full'):
                ui.label(
                    'Deze BD-betalingen hebben een kenmerk dat niet als IB '
                    'of ZVW herkend wordt (positie [10:12] van het '
                    '16-cijferige kenmerk). Controleer in /transacties.'
                ).classes('text-sm text-grey-7')
                with ui.column().classes('w-full gap-1 q-mt-sm'):
                    for tx in unmatched:
                        with ui.row().classes('w-full items-center text-sm'):
                            ui.label(format_datum_kort_nl(
                                date.fromisoformat(tx['datum']))
                            ).classes('w-20')
                            ui.label(format_euro(tx['bedrag'])).classes('w-24')
                            ui.label(
                                tx['betalingskenmerk'] or '(geen kenmerk)'
                            ).classes('q-ml-md text-grey')


async def _render_soort_section(
    *, soort: str, label: str,
    beschikking: dict | None, fp,
    bank_detail: list[dict],
    today: date, jaar: int, is_locked: bool,
) -> None:
    """Render één soort-sectie (IB of ZVW) als expansion-card."""
    with ui.expansion(label, icon='receipt_long') \
            .classes('w-full') \
            .props('default-opened'):

        # === Geen actieve beschikking — fallback view
        if beschikking is None:
            handmatig = (
                (fp.voorlopige_aanslag_betaald if soort == 'ib'
                 else fp.voorlopige_aanslag_zvw)
                if fp else 0
            )
            with ui.column().classes('w-full gap-2'):
                if handmatig:
                    ui.label(
                        f'Handmatig in /aangifte: {format_euro(handmatig)}'
                    ).classes('text-sm text-grey-7')
                else:
                    ui.label(
                        'Geen beschikking opgeslagen.'
                    ).classes('text-sm')
                # Upload-CTA: disabled bij locked-jaar (spec § 350) zodat de
                # gebruiker ziet dat upload bestaat maar geblokkeerd is —
                # disabled + tooltip i.p.v. silent hide. DB-mutaties zijn
                # server-side al beschermd door assert_year_writable.
                upload_btn = ui.button(
                    'Upload PDF via /documenten',
                    icon='upload',
                    on_click=lambda j=jaar: ui.navigate.to(
                        f'/documenten?jaar={j}'),
                ).props('color=primary flat')
                if is_locked:
                    upload_btn.props('disable')
                    upload_btn.tooltip(
                        'Jaar is afgesloten — heropen via Jaarafsluiting voor wijzigingen'
                    )
                if bank_detail:
                    totaal = sum(t['bedrag'] for t in bank_detail)
                    ui.label(
                        f'Bank-betalingen voor {soort.upper()} '
                        f'({len(bank_detail)}): totaal {format_euro(totaal)}'
                    ).classes('text-sm')
            return

        # === Active beschikking aanwezig
        bedrag = float(beschikking['bedrag'] or 0)
        termijnen = int(beschikking['termijnen'] or 11)
        betaald = sum(float(t['bedrag']) for t in bank_detail)
        rest = max(bedrag - betaald, 0.0)
        termijn_bedrag = bedrag / termijnen if termijnen else 0.0

        with ui.column().classes('w-full gap-1'):
            dagtekening_str = ''
            if beschikking.get('dagtekening'):
                try:
                    dagtekening_str = format_datum_kort_nl(
                        date.fromisoformat(beschikking['dagtekening']))
                except (TypeError, ValueError):
                    dagtekening_str = str(beschikking['dagtekening'])
            ui.label(
                f'Aanslagnummer {beschikking.get("aanslagnummer", "?")} · '
                f'Dagtekening {dagtekening_str}'
            ).classes('text-sm text-grey-7')
            with ui.row().classes('items-baseline gap-4 q-mt-xs'):
                ui.label(f'Verplicht {format_euro(bedrag)}')
                ui.label(f'Betaald {format_euro(betaald)}')
                ui.label(f'Rest {format_euro(rest)}') \
                    .classes('text-weight-bold')
            ui.label(
                f'{termijnen} termijnen × {format_euro(termijn_bedrag)}/mnd'
            ).classes('text-sm')

            # PDF link — alleen als document_id + bestand bestaat
            doc_id = beschikking.get('document_id')
            if doc_id:
                doc_url = await _resolve_doc_url(doc_id)
                if doc_url:
                    ui.button(
                        'Open PDF',
                        icon='picture_as_pdf',
                        on_click=lambda u=doc_url: ui.navigate.to(
                            u, new_tab=True),
                    ).props('flat color=primary').classes('q-mt-xs')

        # === Termijnen-overzicht
        ui.separator().classes('q-my-sm')
        ui.label('Termijnen-overzicht').classes('text-weight-medium')
        schedule = compute_va_termijnen_schedule(
            bedrag=bedrag, termijnen=termijnen, jaar=jaar,
            bank_tx=bank_detail, today=today,
        )
        with ui.column().classes('w-full gap-1'):
            for row in schedule:
                with ui.row().classes('w-full items-center text-sm'):
                    ui.label(
                        format_datum_kort_nl(row.vervaldatum)
                    ).classes('w-20')
                    ui.label(format_euro(row.bedrag)).classes('w-24')
                    if row.status == 'betaald':
                        ui.icon('check_circle').classes('text-positive')
                        ui.label(
                            f'betaald op {format_datum_kort_nl(row.betaald_op)}'
                            if row.betaald_op else 'betaald'
                        ).classes('q-ml-md')
                    elif row.status == 'verwacht':
                        ui.icon('warning').classes('text-warning')
                        ui.label('verwacht — niet gevonden') \
                            .classes('q-ml-md text-grey-7')
                    else:  # toekomst
                        ui.label('toekomst').classes('q-ml-md text-grey')

        # === Bank-tx tabel (gematched op kenmerk)
        ui.separator().classes('q-my-sm')
        ui.label(
            f'Bank-transacties (kenmerk-match {soort.upper()})'
        ).classes('text-weight-medium')
        if not bank_detail:
            ui.label(
                'Geen bank-transacties gematched.'
            ).classes('text-sm text-grey-7')
        else:
            with ui.column().classes('w-full gap-1'):
                for tx in bank_detail:
                    with ui.row().classes('w-full items-center text-sm'):
                        ui.label(format_datum_kort_nl(
                            date.fromisoformat(tx['datum']))
                        ).classes('w-20')
                        ui.label(format_euro(tx['bedrag'])).classes('w-24')
                        ui.label(tx['omschrijving'] or '') \
                            .classes('q-ml-md text-grey-7')


async def _resolve_doc_url(doc_id: int) -> str | None:
    """Look up het document-pad voor een VA-beschikking-rij en bouw URL.

    Returns None als doc niet bestaat of bestand niet gevonden — caller
    skipt dan het PDF-knopje (voorkomt 404 i.p.v. silent broken link).
    """
    from database import get_db_ctx
    async with get_db_ctx(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT bestandspad FROM aangifte_documenten WHERE id = ?",
            (doc_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return _doc_preview_url(row['bestandspad'])
