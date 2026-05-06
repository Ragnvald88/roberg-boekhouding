"""VA-tracker drill-down page — Sprint J T1.4 (redesigned 2026-05-06).

Click-doel van de /dashboard VA-tile. Information architecture (top-down,
ALLES PLAT zichtbaar — geen expansions, user-feedback "geen extra klikjes"):

1. Hero — status-zin + bedragen + progress + bron-disclaimer + primary CTA
2. Twee summary-cards naast elkaar (IB + ZVW) met:
   - Header met uploaded/niet-uploaded status-badge
   - Active: volledige beschikking-details (bedrag/aanslagnr/kenmerk/datum)
   - Fallback: handmatig bedrag + per-soort upload-CTA naar /documenten
   - Betaald/resterend/progress + Open-PDF (active) of Upload-CTA (fallback)
3. Termijnen-overzicht (per-soort active/indicatief flag)
4. Bankregels — flat card-blok met chronologische lijst
5. Unmatched-audit — flat card-blok (alleen indien aanwezig)

Redesign-rationale: vorige versie was 3 disjoint feiten per sectie zonder
narrative ("extreem onduidelijk" — user feedback 2026-05-06 round-1).
Round-2 feedback: geen expansions overal + per-soort uploaded-status met
volledige beschikking-velden + per-card upload-CTA. Synthese Claude+Codex
round-2: alle informatie altijd zichtbaar, status visueel duidelijk per
soort, deep-links naar /documenten?jaar=X voor concrete actie.

Year-lock policy: bij definitief jaar wordt upload-knop disabled +
tooltip (NIET hidden) — spec § 350. DB-mutaties zijn server-side al
beschermd.
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

_SOORT_META = {
    'ib': {'label': 'Inkomstenbelasting', 'icon': 'account_balance'},
    'zvw': {'label': 'Zorgverzekeringswet', 'icon': 'health_and_safety'},
}


def _format_kenmerk_display(k: str | None) -> str:
    """Format 16-digit kenmerk als '0124 4126 4706 0001' voor leesbaarheid.

    Match BD's eigen weergave-conventie in de PDF zelf. Niet-16-digit
    input wordt onveranderd geretourneerd (defensive).
    """
    if not k:
        return '(geen kenmerk)'
    digits = ''.join(c for c in k if c.isdigit())
    if len(digits) == 16:
        return f'{digits[0:4]} {digits[4:8]} {digits[8:12]} {digits[12:16]}'
    return k


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


async def _resolve_doc_url_and_name(doc_id: int) -> tuple[str, str] | None:
    """Look-up bestandspad+naam voor VA-beschikking-doc.

    Returns (preview_url, bestandsnaam) of None als doc niet bestaat of
    bestand missing — caller skipt dan de PDF-knop (voorkomt 404 i.p.v.
    silent broken link).
    """
    from database import get_db_ctx
    async with get_db_ctx(DB_PATH) as conn:
        cur = await conn.execute(
            "SELECT bestandspad, bestandsnaam FROM aangifte_documenten "
            "WHERE id = ?",
            (doc_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    url = _doc_preview_url(row['bestandspad'])
    if url is None:
        return None
    return (url, row['bestandsnaam'] or 'beschikking.pdf')


def _show_pdf_preview(url: str, bestandsnaam: str) -> None:
    """Show PDF preview in dialog — consistent met /documenten patroon.

    pywebview native-mode: ui.navigate.to(new_tab=True) gedrag is
    inconsistent (kan extern browser openen of in-app navigeren); een
    iframe-dialog blijft binnen de app en heeft een bekend gedrag
    (Codex audit fix #4: consistent UX met /documenten show_preview).
    """
    with ui.dialog() as dlg, \
            ui.card().classes('w-full max-w-4xl q-pa-md'):
        with ui.row().classes('w-full items-center'):
            ui.label(bestandsnaam).classes('text-h6 flex-grow')
            ui.button(icon='close', on_click=dlg.close) \
                .props('flat round')
        ui.separator().classes('q-my-sm')
        ui.html(
            f'<iframe src="{url}" '
            f'style="width:100%;height:70vh;border:none;'
            f'border-radius:8px;"></iframe>',
            sanitize=False,
        )
    dlg.open()


def _per_soort_state(beschikking, fp_bedrag: float,
                     bank_total: float) -> str:
    """Per-soort state: no_data | fp_only | fp_and_bank | active.

    Bepaalt welke card-vorm en disclaimer-tekst gerenderd wordt.
    """
    if beschikking is not None:
        return 'active'
    if fp_bedrag > 0:
        return 'fp_and_bank' if bank_total > 0 else 'fp_only'
    return 'no_data'


def _page_state(ib_state: str, zvw_state: str) -> str:
    """Page-level state voor hero-zin + CTA-priority.

    Codex round-1 catched: page-state was te coarse — als IB 'active' is
    maar ZVW 'fp_only', mocht de hero NIET zeggen "alles is beschikking-
    based". Daarom 5 states (was 4):

    - empty:        beide soorten zonder data
    - fp_only:      beide soorten alleen fp, geen bank
    - fp_and_bank:  beide soorten fp + minstens één bank-betaling
    - mixed:        één soort active, andere is fp_*  → hero toont
                    bron-disclaimer + Upload-PDF-CTA blijft primary
    - all_active:   beide soorten hebben active beschikking
    """
    states = (ib_state, zvw_state)
    if all(s == 'no_data' for s in states):
        return 'empty'
    if all(s == 'active' for s in states):
        return 'all_active'
    if 'active' in states:
        return 'mixed'
    if 'fp_and_bank' in states:
        return 'fp_and_bank'
    if 'fp_only' in states:
        return 'fp_only'
    return 'empty'


def _status_zin(state: str, jaar: int, betaald: float,
                verplicht: float, achter: int) -> str:
    """Eén-zin samenvatting bovenaan hero. Past zich aan op state.

    Codex round-1 fix: mixed-state krijgt eigen zin om duidelijk te maken
    dat één soort wel/niet beschikking-based is.
    """
    if state == 'empty':
        return f'Er is nog geen voorlopige aanslag bekend voor {jaar}.'
    if state == 'fp_only':
        return (f'Je verwacht {format_euro(verplicht)} aan voorlopige aanslag. '
                f'Wacht op eerste bankbetaling.')
    if state == 'fp_and_bank':
        return (f'Je hebt {format_euro(betaald)} betaald van '
                f'{format_euro(verplicht)} verwacht.')
    if state == 'mixed':
        # Eén soort active, andere fp/no_data — bedragen blijven informatief
        return (f'Je hebt {format_euro(betaald)} betaald van '
                f'{format_euro(verplicht)} (gedeeltelijk volgens beschikking).')
    # all_active state
    if achter > 0:
        suffix = 'en' if achter > 1 else ''
        return f'Je mist waarschijnlijk {achter} termijn{suffix}.'
    if verplicht > 0 and betaald >= verplicht - 1:
        return f'Je voorlopige aanslag {jaar} is voldaan.'
    return f'Je loopt bij met de voorlopige aanslag {jaar}.'


def _bron_message(state: str) -> str | None:
    """Bron-disclaimer onder de bedragen. None = geen disclaimer.

    Codex round-1 fix: 'mixed' krijgt eigen disclaimer die expliciet
    aangeeft dat één soort nog handmatig is — anders verbergt de hero
    dat upload nog nodig is.
    """
    if state in ('fp_only', 'fp_and_bank'):
        return ('Gebaseerd op handmatige bedragen uit Aangifte. Upload de '
                'beschikking om termijnen en betalingskenmerken exact te '
                'controleren.')
    if state == 'mixed':
        return ('Eén soort heeft nog geen beschikking-PDF. Upload ook de '
                'tweede beschikking voor volledige termijn-tracking.')
    return None


def _primary_cta(state: str, jaar: int) -> tuple[str, str, str]:
    """(label, route, icon) voor primary action — past zich aan op state.

    Codex round-1 fix: 'mixed' state krijgt Upload-PDF primary, NIET
    Bekijk-betalingen. Eén kant is nog niet ge-upload — upload blijft
    de actionable next-step.
    """
    if state in ('empty', 'fp_only', 'fp_and_bank', 'mixed'):
        return ('Upload beschikking', f'/documenten?jaar={jaar}', 'upload')
    return ('Bekijk betalingen',
            f'/transacties?categorie=Belasting&jaar={jaar}', 'visibility')


def _secondary_cta(state: str, jaar: int) -> tuple[str, str, str] | None:
    """(label, route, icon) voor secondary action — None = geen tweede CTA."""
    if state in ('empty', 'fp_only', 'fp_and_bank', 'mixed'):
        return ('Bekijk betalingen',
                f'/transacties?categorie=Belasting&jaar={jaar}',
                'visibility')
    return None  # all_active state — Open-PDF zit in soort-card


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

    # Per-soort tx-lists
    ib_bank = [t for t in bank_detail if t['classification'] == 'ib_matched']
    zvw_bank = [t for t in bank_detail if t['classification'] == 'zvw_matched']
    unmatched = [t for t in bank_detail if t['classification'] == 'unmatched']

    # Per-soort verplicht-bedragen + state
    ib_verplicht = (float(ib_b['bedrag']) if ib_b
                    else (float(fp.voorlopige_aanslag_betaald) if fp else 0.0))
    zvw_verplicht = (float(zvw_b['bedrag']) if zvw_b
                     else (float(fp.voorlopige_aanslag_zvw) if fp else 0.0))
    ib_betaald = sum(float(t['bedrag']) for t in ib_bank)
    zvw_betaald = sum(float(t['bedrag']) for t in zvw_bank)

    ib_state = _per_soort_state(ib_b, ib_verplicht, ib_betaald)
    zvw_state = _per_soort_state(zvw_b, zvw_verplicht, zvw_betaald)
    page_state_str = _page_state(ib_state, zvw_state)

    # Totals voor hero
    totaal_verplicht = ib_verplicht + zvw_verplicht
    totaal_betaald = ib_betaald + zvw_betaald
    totaal_resterend = max(totaal_verplicht - totaal_betaald, 0.0)
    progress_pct = (totaal_betaald / totaal_verplicht
                    if totaal_verplicht > 0 else 0.0)

    # Per-soort termijnen — fall-through active-beschikking > fp.va_*_termijnen
    # > default 11 (Codex round-1 fix: was hardcoded 11 in fallback path,
    # negeerde fp.voorlopige_aanslag_*_termijnen). `or 11` defensief tegen
    # NULL/0 in DB-rij.
    ib_termijnen_count = (
        int(ib_b['termijnen'] or 11) if ib_b is not None
        else int(getattr(fp, 'voorlopige_aanslag_ib_termijnen', 11) or 11)
        if fp else 11
    )
    zvw_termijnen_count = (
        int(zvw_b['termijnen'] or 11) if zvw_b is not None
        else int(getattr(fp, 'voorlopige_aanslag_zvw_termijnen', 11) or 11)
        if fp else 11
    )

    # Schedules berekenen — gebruikt voor zowel achter-count (active) als
    # planning-section render. Pure helper, geen drift-risico.
    ib_schedule = compute_va_termijnen_schedule(
        bedrag=ib_verplicht, termijnen=ib_termijnen_count,
        jaar=jaar, bank_tx=ib_bank, today=today,
    ) if ib_verplicht > 0 else []
    zvw_schedule = compute_va_termijnen_schedule(
        bedrag=zvw_verplicht, termijnen=zvw_termijnen_count,
        jaar=jaar, bank_tx=zvw_bank, today=today,
    ) if zvw_verplicht > 0 else []

    # Achter-count uit alleen ACTIVE schedules. 'achter' = vervaldatum
    # voorbij + cumulatief tekort. Indicatieve mode (handmatige fp) heeft
    # geen kenmerk-match dus die count is onbetrouwbaar.
    achter_count = 0
    if ib_b is not None:
        achter_count += sum(1 for r in ib_schedule if r.status == 'achter')
    if zvw_b is not None:
        achter_count += sum(1 for r in zvw_schedule if r.status == 'achter')

    # === /va-tracker is een PURE read-page (Sprint J round-3 architectuur).
    # Auto-backfill van ongekoppelde VA-PDFs gebeurt op /documenten
    # page-load (zie pages.documenten._auto_backfill_va_for_jaar). Geen
    # banner of mutate-CTA hier — als er ongekoppelde docs zijn ziet user
    # ze als "PDF nog niet geüpload" in de soort-card en wordt gevraagd
    # naar /documenten te gaan (waar auto-process draait).

    with ui.column().classes('w-full p-6 max-w-4xl mx-auto gap-4'):
        # === Page-header (jaar + bewerk-link top-right)
        with ui.row().classes('w-full items-center justify-between'):
            page_title(f'Voorlopige aanslag {jaar}')
            ui.button(
                'Bewerk in Aangifte',
                icon='edit',
                on_click=lambda j=jaar: ui.navigate.to(f'/aangifte?jaar={j}'),
            ).props('flat dense color=primary')

        # === Locked-jaar banner
        if is_locked:
            with ui.row().classes('w-full items-center q-pa-sm') \
                    .style('background: var(--bg-warning-soft); '
                           'border-radius: 6px;'):
                ui.icon('lock').classes('text-warning')
                ui.label(
                    f'Jaar {jaar} is afgesloten — read-only weergave.'
                ).classes('text-sm q-ml-sm')

        # === HERO
        _render_hero(
            state=page_state_str, jaar=jaar,
            totaal_verplicht=totaal_verplicht,
            totaal_betaald=totaal_betaald,
            totaal_resterend=totaal_resterend,
            progress_pct=progress_pct,
            achter_count=achter_count,
            is_locked=is_locked,
        )

        # === Per-soort summary-cards (NIET expansions, side-by-side)
        if page_state_str != 'empty':
            with ui.row().classes('w-full gap-4 flex-wrap'):
                with ui.column().classes('flex-1').style('min-width: 280px;'):
                    await _render_soort_card(
                        soort='ib', state=ib_state,
                        beschikking=ib_b, verplicht=ib_verplicht,
                        betaald=ib_betaald, bank_count=len(ib_bank),
                        jaar=jaar, is_locked=is_locked,
                    )
                with ui.column().classes('flex-1').style('min-width: 280px;'):
                    await _render_soort_card(
                        soort='zvw', state=zvw_state,
                        beschikking=zvw_b, verplicht=zvw_verplicht,
                        betaald=zvw_betaald, bank_count=len(zvw_bank),
                        jaar=jaar, is_locked=is_locked,
                    )

        # === Termijnen / Indicatieve planning (alleen als bedragen bekend)
        # Per-soort indicatief-flag (Codex round-1 fix: was page-wide,
        # waardoor mixed-state ZVW (handmatig) groene checks kreeg alsof
        # het active was). Active = matched-by-kenmerk → groene ✓.
        # Indicatief = matched-by-month-only → "betaald gevonden" zonder ✓.
        if page_state_str != 'empty' and (ib_verplicht > 0 or zvw_verplicht > 0):
            _render_planning_section(
                ib_active=ib_b is not None,
                zvw_active=zvw_b is not None,
                ib_verplicht=ib_verplicht, zvw_verplicht=zvw_verplicht,
                ib_schedule=ib_schedule, zvw_schedule=zvw_schedule,
            )

        # === Bankregels — FLAT lijst, geen expansion (user-feedback:
        # "geen extra klikjes"). Gerendered binnen card voor visuele
        # afgrenzing maar zonder toggle-interactie.
        all_matched = ib_bank + zvw_bank
        if all_matched:
            with ui.card().classes('w-full q-pa-md'):
                ui.label(
                    f'{len(all_matched)} bankbetaling'
                    f'{"en" if len(all_matched) != 1 else ""} aan '
                    f'Belastingdienst ({format_euro(totaal_betaald)})'
                ).classes('text-subtitle1 text-weight-medium')
                ui.separator().classes('q-my-sm')
                with ui.column().classes('w-full gap-1'):
                    for tx in sorted(all_matched, key=lambda t: t['datum']):
                        with ui.row().classes(
                                'w-full items-center text-sm gap-2'):
                            ui.label(format_datum_kort_nl(
                                date.fromisoformat(tx['datum']))
                            ).classes('w-20')
                            soort_label = (
                                'IB' if tx['classification'] == 'ib_matched'
                                else 'ZVW')
                            ui.label(soort_label).classes(
                                'w-12 text-grey-7 text-caption')
                            ui.label(format_euro(tx['bedrag'])).classes('w-24')
                            ui.label(tx['omschrijving'] or '') \
                                .classes('q-ml-md text-grey-7')

        # === Unmatched — FLAT lijst (alleen indien aanwezig)
        if unmatched:
            total_unmatched = sum(t['bedrag'] for t in unmatched)
            with ui.card().classes('w-full q-pa-md').style(
                    'border-left: 4px solid var(--q-warning);'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('warning').classes('text-warning')
                    ui.label(
                        f'Niet-toegewezen ({len(unmatched)} · '
                        f'{format_euro(total_unmatched)})'
                    ).classes('text-subtitle1 text-weight-medium')
                ui.label(
                    'Deze BD-betalingen hebben geen herkenbaar IB/ZVW-kenmerk '
                    '(positie [10:12] van het 16-cijferige kenmerk). '
                    'Controleer in Transacties.'
                ).classes('text-sm text-grey-7 q-mt-xs')
                ui.separator().classes('q-my-sm')
                with ui.column().classes('w-full gap-1'):
                    for tx in unmatched:
                        with ui.row().classes(
                                'w-full items-center text-sm gap-2'):
                            ui.label(format_datum_kort_nl(
                                date.fromisoformat(tx['datum']))
                            ).classes('w-20')
                            ui.label(format_euro(tx['bedrag'])).classes('w-24')
                            ui.label(
                                tx['betalingskenmerk'] or '(geen kenmerk)'
                            ).classes('q-ml-md text-grey')


def _render_hero(*, state: str, jaar: int,
                 totaal_verplicht: float, totaal_betaald: float,
                 totaal_resterend: float, progress_pct: float,
                 achter_count: int, is_locked: bool) -> None:
    """Render hero-card: status-zin + bedragen + progress + bron-disclaimer + CTAs.

    Hero-color via inline style i.p.v. nieuwe CSS-class (small footprint,
    geen cascade-discipline-regel raken).
    """
    accent_color = (
        'var(--q-warning)' if state in ('fp_only', 'fp_and_bank')
        else 'var(--accent)' if state != 'empty'
        else 'var(--border)'
    )
    with ui.card().classes('w-full q-pa-md').style(
            f'background: var(--bg-info-soft); '
            f'border-left: 4px solid {accent_color};'):
        # Status zin (top, prominent)
        zin = _status_zin(state, jaar, totaal_betaald, totaal_verplicht,
                          achter_count)
        ui.label(zin).classes('text-h6 text-weight-medium')

        # Bedragen-row (skip in empty state)
        if state != 'empty':
            with ui.row().classes('items-baseline gap-2 q-mt-sm'):
                ui.label(format_euro(totaal_betaald)).classes(
                    'text-h4 text-weight-bold')
                ui.label(
                    f'van {format_euro(totaal_verplicht)} verwacht'
                ).classes('text-body2 text-grey-7')
            ui.label(
                f'Nog te betalen: {format_euro(totaal_resterend)}'
            ).classes('text-body1 text-weight-medium q-mt-xs')

            # Progress bar (show_value=False — NiceGUI default rendert de
            # raw float-waarde als tekst-overlay op de bar wat lelijk staat
            # naast onze eigen "X% betaald"-label)
            ui.linear_progress(
                value=min(progress_pct, 1.0),
                show_value=False,
                color='primary' if progress_pct < 1.0 else 'positive',
            ).props('size=10px rounded').classes('q-mt-md')
            ui.label(f'{int(progress_pct * 100)}% betaald').classes(
                'text-caption text-grey-7 q-mt-xs')

        # Bron-disclaimer
        bron_msg = _bron_message(state)
        if bron_msg:
            with ui.row().classes('items-start gap-2 q-mt-md no-wrap'):
                ui.icon('info').classes('text-warning')
                ui.label(bron_msg).classes('text-sm text-grey-8')

        # CTAs
        with ui.row().classes('w-full gap-2 q-mt-md'):
            primary_label, primary_route, primary_icon = _primary_cta(
                state, jaar)
            primary_btn = ui.button(
                primary_label, icon=primary_icon,
                on_click=lambda r=primary_route: ui.navigate.to(r),
            ).props('color=primary unelevated')
            if is_locked and primary_label == 'Upload beschikking':
                primary_btn.props('disable')
                primary_btn.tooltip(
                    'Jaar afgesloten — heropen via Jaarafsluiting voor '
                    'wijzigingen'
                )
            secondary = _secondary_cta(state, jaar)
            if secondary is not None:
                sec_label, sec_route, sec_icon = secondary
                ui.button(
                    sec_label, icon=sec_icon,
                    on_click=lambda r=sec_route: ui.navigate.to(r),
                ).props('outline color=primary')


async def _render_soort_card(*, soort: str, state: str,
                              beschikking: dict | None,
                              verplicht: float, betaald: float,
                              bank_count: int, jaar: int,
                              is_locked: bool) -> None:
    """Render één soort-summary-card (IB of ZVW). NIET expansion — alle
    info altijd zichtbaar (user-feedback: "geen extra klikjes").

    User-feedback 2026-05-06: card moet expliciet tonen of PDF geüpload
    is, en zo ja álle relevante velden uit de beschikking (aanslagnummer,
    betalingskenmerk, dagtekening). Zo niet: prominent upload-CTA per
    soort (niet alleen via hero) met deep-link naar /documenten.
    """
    meta = _SOORT_META[soort]
    soort_upper = soort.upper()
    with ui.card().classes('w-full q-pa-md').style('height: 100%;'):
        # === Header: icon + label + uploaded-status badge
        with ui.row().classes('items-center gap-2 w-full'):
            ui.icon(meta['icon']).classes('text-primary')
            ui.label(meta['label']).classes(
                'text-subtitle1 text-weight-medium')
            ui.space()
            if state == 'active':
                with ui.row().classes('items-center gap-1'):
                    ui.icon('check_circle').classes('text-positive')
                    ui.label('Beschikking geüpload').classes(
                        'text-caption text-positive')
            elif state == 'no_data':
                with ui.row().classes('items-center gap-1'):
                    ui.icon('cancel').classes('text-grey-6')
                    ui.label('Geen data').classes('text-caption text-grey-6')
            else:  # fp_only / fp_and_bank
                with ui.row().classes('items-center gap-1'):
                    ui.icon('warning').classes('text-warning')
                    ui.label('PDF nog niet geüpload').classes(
                        'text-caption text-warning')

        ui.separator().classes('q-my-sm')

        # === No-data state — minimal + upload-CTA
        if state == 'no_data':
            ui.label(
                f'Geen verwacht bedrag bekend voor {soort_upper}.'
            ).classes('text-sm text-grey-7')
            ui.label(
                'Vul handmatig in via Aangifte, of upload de '
                'beschikking-PDF.'
            ).classes('text-sm text-grey-7 q-mt-xs')
            _render_per_soort_upload_button(soort, jaar, is_locked)
            return

        # === Active state — toon volledige beschikking-details
        # Stacked layout (label-boven / value-onder) ipv justify-between:
        # voorkomt dat lange waarden (kenmerk 19 chars, aanslagnummer
        # 18+ chars) tegen het label aandrukken op smalle cards (Codex
        # round-2 layout-responsiveness fix).
        if state == 'active' and beschikking is not None:
            aanslagnummer = beschikking.get('aanslagnummer', '?')
            kenmerk_raw = beschikking.get('betalingskenmerk', '')
            kenmerk_disp = _format_kenmerk_display(kenmerk_raw)
            dagtekening_str = '?'
            if beschikking.get('dagtekening'):
                try:
                    dagtekening_str = format_datum_kort_nl(
                        date.fromisoformat(beschikking['dagtekening']))
                except (TypeError, ValueError):
                    dagtekening_str = str(beschikking['dagtekening'])

            with ui.column().classes('w-full gap-2'):
                _render_stacked_field('Bedrag', format_euro(verplicht),
                                      mono=False, emphasize=True)
                _render_stacked_field('Aanslagnummer', aanslagnummer,
                                      mono=True)
                _render_stacked_field('Betalingskenmerk', kenmerk_disp,
                                      mono=True)
                _render_stacked_field('Dagtekening', dagtekening_str,
                                      mono=False)
        else:
            # === fp_only / fp_and_bank — toon handmatig + bank-summary
            with ui.column().classes('w-full gap-1'):
                with ui.row().classes('items-baseline justify-between w-full'):
                    ui.label('Handmatig bedrag').classes(
                        'text-sm text-grey-7')
                    ui.label(format_euro(verplicht)).classes(
                        'text-sm text-weight-medium')
                ui.label('(uit Aangifte)').classes(
                    'text-caption text-grey-6')

        ui.separator().classes('q-my-sm')

        # === Betaald + Resterend + Progress (alle states behalve no_data)
        resterend = max(verplicht - betaald, 0.0)
        pct = betaald / verplicht if verplicht > 0 else 0.0

        with ui.column().classes('w-full gap-1'):
            with ui.row().classes('items-baseline justify-between w-full'):
                ui.label(
                    f'Betaald ({bank_count} bank-tx)' if bank_count
                    else 'Betaald'
                ).classes('text-sm text-grey-7')
                ui.label(format_euro(betaald)).classes('text-sm')
            with ui.row().classes('items-baseline justify-between w-full'):
                ui.label('Resterend').classes(
                    'text-sm text-weight-medium')
                ui.label(format_euro(resterend)).classes(
                    'text-sm text-weight-medium')

        ui.linear_progress(
            value=min(pct, 1.0),
            show_value=False,
            color='primary' if pct < 1.0 else 'positive',
        ).props('size=6px rounded').classes('q-mt-sm')
        ui.label(f'{int(pct * 100)}% betaald').classes(
            'text-caption text-grey-7')

        # === Footer-actie: Open PDF (active) of Upload-CTA (anders)
        if state == 'active' and beschikking is not None \
                and beschikking.get('document_id'):
            resolved = await _resolve_doc_url_and_name(
                beschikking['document_id'])
            if resolved is not None:
                doc_url, doc_name = resolved
                ui.button(
                    'Open PDF', icon='picture_as_pdf',
                    on_click=lambda u=doc_url, n=doc_name: _show_pdf_preview(
                        u, n),
                ).props('flat dense color=primary').classes('q-mt-sm')
        elif state in ('fp_only', 'fp_and_bank'):
            _render_per_soort_upload_button(soort, jaar, is_locked)


def _render_stacked_field(label: str, value: str,
                          *, mono: bool = False,
                          emphasize: bool = False) -> None:
    """Render een label-boven / value-onder veld voor compacte cards.

    Stacked layout voorkomt overflow van lange waarden (betalingskenmerk
    19 chars, aanslagnummer 18+ chars) op smalle cards waar
    justify-between de tekst tegen elkaar zou drukken.
    """
    ui.label(label).classes('text-caption text-grey-7')
    value_class = 'text-sm'
    if mono:
        value_class += ' font-mono'
    if emphasize:
        value_class += ' text-weight-medium'
    ui.label(value).classes(value_class)


def _render_per_soort_upload_button(soort: str, jaar: int,
                                    is_locked: bool) -> None:
    """Per-soort upload-CTA — deep-link naar /documenten met jaar-param.

    User-feedback: upload-CTA per soort i.p.v. alleen in de hero, zodat
    het direct duidelijk is welke soort nog niet geüpload is.
    """
    soort_label = 'IB' if soort == 'ib' else 'ZVW'
    btn = ui.button(
        f'Upload {soort_label}-beschikking',
        icon='upload',
        on_click=lambda j=jaar: ui.navigate.to(f'/documenten?jaar={j}'),
    ).props('outline color=primary').classes('q-mt-sm')
    if is_locked:
        btn.props('disable')
        btn.tooltip(
            'Jaar afgesloten — heropen via Jaarafsluiting voor wijzigingen'
        )


def _render_planning_section(*, ib_active: bool, zvw_active: bool,
                              ib_verplicht: float, zvw_verplicht: float,
                              ib_schedule: list, zvw_schedule: list) -> None:
    """Render termijnen-overzicht.

    Per-soort indicatief-flag (Codex round-1 fix): IB en ZVW kunnen
    onafhankelijk active of indicatief zijn. Mixed-case (IB active, ZVW
    handmatig) toonde voorheen ZVW met groene ✓ alsof het matched was —
    nu krijgt elke kolom zijn eigen sub-header + label.

    Verschil per kolom:
      - Active: schedule kruist bank-tx via kenmerk-classification → ✓
      - Indicatief: schedule kruist bank-tx alleen via maand → tekst zonder ✓
    """
    any_indicatief = (
        (ib_verplicht > 0 and not ib_active)
        or (zvw_verplicht > 0 and not zvw_active)
    )

    with ui.card().classes('w-full q-pa-md'):
        with ui.row().classes('items-center justify-between w-full'):
            ui.label('Termijnen-overzicht').classes(
                'text-subtitle1 text-weight-medium')
            if any_indicatief:
                ui.badge('Bevat indicatieve data',
                         color='warning').classes('text-caption')

        if any_indicatief:
            ui.label(
                'Voor handmatige soorten gebruiken we een gelijke verdeling '
                'over de termijnen. Bankbetalingen worden alleen per '
                'kalendermaand benaderd, niet op betalingskenmerk.'
            ).classes('text-sm text-grey-7 q-mt-xs')

        ui.separator().classes('q-my-sm')

        # Twee kolommen: IB + ZVW termijnen-rijen, elk met eigen header
        with ui.row().classes('w-full gap-4 flex-wrap'):
            for soort, is_active, verplicht, schedule in [
                ('ib', ib_active, ib_verplicht, ib_schedule),
                ('zvw', zvw_active, zvw_verplicht, zvw_schedule),
            ]:
                with ui.column().classes('flex-1').style('min-width: 280px;'):
                    meta = _SOORT_META[soort]
                    with ui.row().classes('items-center gap-2'):
                        ui.label(meta['label']).classes(
                            'text-sm text-weight-medium')
                        if verplicht > 0 and not is_active:
                            ui.badge('indicatief', color='warning').classes(
                                'text-caption')
                    if verplicht == 0:
                        ui.label('Geen verwacht bedrag.').classes(
                            'text-sm text-grey-7')
                        continue
                    for row in schedule:
                        with ui.row().classes(
                                'w-full items-center text-sm gap-2 no-wrap'):
                            # Termijn N + vervaldatum
                            ui.label(f'{row.termijn}/{len(schedule)}').classes(
                                'w-12 text-grey-7 text-caption')
                            ui.label(
                                format_datum_kort_nl(row.vervaldatum)
                            ).classes('w-16 text-grey-7')
                            # Cumulatief: betaald / verwacht
                            ui.label(
                                f'{format_euro(row.cumulatief_betaald, decimals=0)}'
                                f' / {format_euro(row.cumulatief_verwacht, decimals=0)}'
                            ).classes('flex-1 text-mono text-caption')
                            # Status + tekort/overschot indicator
                            _render_termijn_status(row, is_active=is_active)


def _render_termijn_status(row, *, is_active: bool) -> None:
    """Render status-icoon + tekst voor één termijn-rij.

    Cumulatief-aware: toont vooruitbetaling / tekort / overdue. Voor
    indicatieve mode (handmatige fp, geen kenmerk-match): geen ✓ icoon
    om "matched-by-kenmerk"-suggestie te vermijden.
    """
    if row.status == 'betaald':
        if is_active:
            ui.icon('check_circle').classes('text-positive')
        # Toon overschot ("vooruit") als > 0
        if row.overschot > 1:
            ui.label(
                f'{format_euro(row.overschot, decimals=0)} vooruit'
            ).classes('text-caption text-grey-7')
        else:
            ui.label('voldaan').classes('text-caption text-grey-7')
    elif row.status == 'partial':
        ui.icon('schedule').classes('text-warning')
        ui.label(
            f'{format_euro(row.tekort, decimals=0)} tekort'
        ).classes('text-caption text-warning')
    elif row.status == 'achter':
        ui.icon('warning').classes('text-negative')
        ui.label(
            f'{format_euro(row.tekort, decimals=0)} achter'
        ).classes('text-caption text-negative')
    else:  # toekomst
        ui.label('toekomst').classes('text-caption text-grey')
