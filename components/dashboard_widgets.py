"""Per-tile renderers for /dashboard. NiceGUI-coupled.

Each render_* function takes raw data + a parent container, draws a
self-contained widget. Pure-data helpers live in services/dashboard.py.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from nicegui import ui

from components.utils import (
    format_datum_jaar_nl, format_datum_kort_nl, format_euro,
)
from services.dashboard import ActionRow, VATrackSummary


# Severity → icon/color mapping. Critical uses Quasar negative token
# (cascade-safe — token-driven), warning uses amber hex (no token yet —
# matches confidence-badge pattern in dashboard.py for consistency),
# info uses --accent for brand-coupling.
_SEVERITY_ICON = {
    'critical': 'error',
    'warning': 'warning',
    'info': 'info_outline',
}
_SEVERITY_COLOR = {
    'critical': 'var(--q-negative)',
    'warning': '#D97706',  # amber — matches confidence-badge pattern
    'info': 'var(--accent)',
}


def render_action_inbox(
    rows: list[ActionRow],
    on_action: Callable[[ActionRow, str], None],
) -> None:
    """Render the consolidated action-inbox card.

    `on_action(row, action_kind)` is the dispatcher — receives the row
    and inline-action-kind, performs the action (open dialog, send mail,
    update status, etc.). Caller wires this to handlers.

    Replaces the previous wall of separate alert-card / severity-card
    items with one prioritised work-inbox (Acumulus-pattern).

    Inline actions zijn beperkt tot de 4 spec'd kinds (T3.4):
    stuur_herinnering, categoriseer, upload_nu, verstuur_concept.
    Andere row.action_kind waarden tonen alleen "Bekijk" via row.link.
    """
    with ui.card().classes('action-inbox w-full q-pa-md').style(
            'border: 1px solid var(--border); background: var(--surface)'):
        ui.label('Vandaag te doen').style(
            'font-weight: 600; font-size: 14px; '
            'color: var(--text); margin-bottom: 12px')

        if not rows:
            ui.label('Geen acties — alles bij.').classes(
                'text-caption text-grey-6')
            return

        for row in rows:
            with ui.row().classes(
                    'action-inbox-row w-full items-center gap-2'
                ).style(
                    'padding: 8px 4px; '
                    'border-bottom: 1px solid var(--border)'):
                icon = _SEVERITY_ICON.get(row.severity, 'info_outline')
                color = _SEVERITY_COLOR.get(row.severity, 'var(--accent)')
                ui.icon(icon, size='18px').style(f'color: {color}')
                ui.label(row.message).style('flex: 1; font-size: 13px')

                # Inline action knop (per row.action_kind). lambda r=row
                # closure captures row at definition time — voorkomt
                # late-binding bug waar alle buttons de laatste row zouden
                # zien als de loop variable na render verandert.
                if row.action_kind == 'stuur_herinnering':
                    ui.button(
                        'Stuur herinnering',
                        on_click=lambda r=row: on_action(r, 'stuur_herinnering'),
                    ).props('flat dense color=primary size=sm')
                elif row.action_kind == 'categoriseer':
                    ui.button(
                        'Categoriseer',
                        on_click=lambda r=row: on_action(r, 'categoriseer'),
                    ).props('flat dense color=primary size=sm')
                elif row.action_kind == 'upload_nu':
                    ui.button(
                        'Upload nu',
                        on_click=lambda r=row: on_action(r, 'upload_nu'),
                    ).props('flat dense color=primary size=sm')
                elif row.action_kind == 'verstuur_concept':
                    ui.button(
                        'Verstuur',
                        on_click=lambda r=row: on_action(r, 'verstuur_concept'),
                    ).props('flat dense color=primary size=sm')

                # Always: Bekijk (navigation) als link is gegeven
                if row.link:
                    ui.button(
                        'Bekijk',
                        on_click=lambda r=row: ui.navigate.to(r.link),
                    ).props('flat dense size=sm')


def render_sph_tile(
    sph_betaald_ytd: float,
    sph_prognose: dict,
) -> None:
    """Render I-3 SPH-status tile.

    Toont berekende jaarverplichting (op basis van winst-projectie) +
    YTD-betaald + progress-bar. Disclaimer benadrukt dat de echte
    SPH-aanslag op pensioenbasis 3 jaar terug wordt berekend (kan
    significant afwijken van projectie).
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('SPH-pensioen status').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        verplicht = sph_prognose['jaarverplichting']
        with ui.row().classes('items-baseline gap-2'):
            ui.label(f'Berekend {format_euro(verplicht, decimals=0)}').classes(
                'text-h6 num').style('color: var(--text)')
            ui.label('voor jaar').classes('text-caption text-grey-6')

        ui.label(f'Betaald YTD: {format_euro(sph_betaald_ytd, decimals=0)}').classes(
            'text-body2')

        if verplicht > 0:
            pct = min(100, sph_betaald_ytd / verplicht * 100)
            ui.linear_progress(value=pct / 100, size='6px',
                               color='positive' if pct > 80 else 'warning')

        ui.label(
            'Geschat — werkelijke verplichting wordt op pensioenbasis '
            '3 jaar terug berekend en kan ±20% afwijken.'
        ).classes('text-caption text-grey-6').style('margin-top: 8px')


def render_zes_weken_tile(weken: tuple) -> None:
    """Render I-4 6-weken omzet-prognose tile.

    `weken` = tuple[WeekTotaal, ...] from
    services.agenda.get_zes_weken_prognose. Per week tellen we
    `confirmed_amt + expected_amt` (geboekte werkdagen + verwachte
    rooster-entries) — dat is de volledige planning-outlook, niet
    alleen het nog-niet-bevestigde deel.
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('6-weken prognose').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if not weken:
            ui.label('Geen geplande werkdagen').classes(
                'text-caption text-grey-6')
            return

        week_bedragen = [w.confirmed_amt + w.expected_amt for w in weken]
        totaal = sum(week_bedragen)
        ui.label(format_euro(totaal, decimals=0)).classes('text-h6 num')
        ui.label(f'over {len(weken)} weken').classes(
            'text-caption text-grey-6')

        # Mini bar chart (ECharts) — accent kleur, geen y-axis labels
        # om de tile compact te houden.
        ui.echart({
            'grid': {'top': 5, 'bottom': 20, 'left': 0, 'right': 0},
            'xAxis': {
                'type': 'category',
                'data': [f'wk{w.week_nummer}' for w in weken],
                'axisLabel': {'fontSize': 9, 'color': '#94A3B8'},
            },
            'yAxis': {'show': False, 'type': 'value'},
            'series': [{
                'type': 'bar',
                'data': week_bedragen,
                'itemStyle': {'color': '#0F766E'},  # accent
            }],
            'tooltip': {'show': True},
        }).style('height: 80px; width: 100%')


def render_top_klanten_tile(klanten: list[dict]) -> None:
    """Render I-5 Top 5 klanten + concentratie tile.

    `klanten` from `get_omzet_per_klant(jaar)` — list[dict] with keys
    `naam` + `bedrag` (omzet excl concept), already sorted by bedrag
    DESC. Toont top-5 + percentage van het jaar-totaal zodat de
    gebruiker concentratierisico ziet (bijv. één opdrachtgever > 50%).
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('Top 5 klanten').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if not klanten:
            ui.label('Geen omzet').classes('text-caption text-grey-6')
            return

        top5 = klanten[:5]
        totaal = sum(k.get('bedrag', 0) for k in klanten)

        for k in top5:
            bedrag = k.get('bedrag', 0)
            pct = (bedrag / totaal * 100) if totaal > 0 else 0
            with ui.row().classes('w-full items-center gap-2'):
                ui.label(k.get('naam', '?')).style(
                    'flex: 1; font-size: 12px')
                ui.label(format_euro(bedrag, decimals=0)).classes(
                    'num').style('font-size: 12px')
                ui.label(f'{pct:.0f}%').classes(
                    'text-caption text-grey-6 num').style(
                    'width: 36px; text-align: right')


def render_documenten_tile(
    aangifte_docs: list,
    aangifte_docs_keys: list,
) -> None:
    """Render I-6 Aangifte-documenten checklist DETAIL tile.

    `aangifte_docs` = list of AangifteDocument objects from
    `get_aangifte_documenten(jaar)`.
    `aangifte_docs_keys` = list of expected document-specs. Accepts
    either:
      - list of `DocSpec` NamedTuples (e.g. `AANGIFTE_DOCS` directly), or
      - list of `(documenttype, label)` tuples, or
      - list of strings (documenttype keys; gebruikt zelf als label).
    De renderer normaliseert deze drie vormen naar `(key, label)` paren.
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('Aangifte-documenten').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        done = {d.documenttype for d in aangifte_docs}
        for spec in aangifte_docs_keys:
            # Normaliseer naar (key, label) — DocSpec NamedTuple heeft
            # documenttype + label velden; tuple/string fallbacks voor
            # callers die alleen de key meegeven.
            if hasattr(spec, 'documenttype'):
                key, label = spec.documenttype, spec.label
            elif isinstance(spec, str):
                key, label = spec, spec
            else:
                key, label = spec[0], (spec[1] if len(spec) > 1 else spec[0])
            is_done = key in done
            with ui.row().classes('w-full items-center gap-2'):
                icon = ('check_circle' if is_done
                        else 'radio_button_unchecked')
                color = ('var(--q-positive)' if is_done
                         else 'var(--muted)')
                ui.icon(icon, size='16px').style(f'color: {color}')
                ui.label(label).style('font-size: 12px; flex: 1')


def render_cash_positie_tile(
    opening_saldo: float | None,
    flow_ytd: float,
) -> None:
    """Render I-7 Cash-positie + flow YTD tile.

    `opening_saldo` from `fp.balans_bank_saldo` (None of 0 → empty-state).
    Per spec § E R1 wordt empty-state idealiter via `IS NULL` per jaar
    bepaald, maar het schema zet DEFAULT 0 zodat NULL aan de Python-kant
    altijd al naar 0 gecoerced is (zie `_row_to_fiscale_params`). Caller
    moet daarom 0 → None mappen vóór deze renderer aanroepen.

    `flow_ytd` = SUM(banktransacties.bedrag) voor het jaar — kan negatief
    zijn als kosten > inkomsten YTD.
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('Cash-positie').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if opening_saldo is None:
            with ui.column().classes('gap-1'):
                ui.label('Geen opening-saldo ingevuld').classes(
                    'text-body2 text-grey-6')
                ui.button(
                    'Vul in /instellingen',
                    on_click=lambda: ui.navigate.to(
                        '/instellingen?tab=fiscaal')) \
                    .props('flat dense color=primary size=sm')
            return

        current = opening_saldo + flow_ytd
        ui.label(format_euro(current, decimals=0)).classes('text-h6 num')
        ui.label(
            f'Opening: {format_euro(opening_saldo)} · '
            f'flow: {format_euro(flow_ytd)}'
        ).classes('text-caption text-grey-6')


def render_tax_calendar_tile(deadlines: list[dict]) -> None:
    """Render I-8 Tax-calendar (alle deadlines voor het jaar) tile.

    `deadlines` from `services.dashboard.tax_calendar(jaar)` — list[dict]
    met `kind`/`date`/`label` per deadline. Past en future deadlines
    worden allebei getoond (anders krimpt de tile end-of-year tot leeg);
    past deadlines tonen "voorbij" + grey, <14d future = red urgency.
    """
    with ui.card().classes('q-pa-md').style(
            'border: 1px solid var(--border)'):
        ui.label('Belasting-deadlines').style(
            'font-weight: 600; color: var(--text); margin-bottom: 8px')

        if not deadlines:
            ui.label('Geen deadlines bekend').classes(
                'text-caption text-grey-6')
            return

        today = date.today()
        for d in deadlines:
            days = (d['date'] - today).days
            # Color logic: <0 = past (muted), 0..14 = urgent (red),
            # >14 = normal (text). Exhaustive over int domain.
            if days < 0:
                color = 'var(--muted)'
                label_text = 'voorbij'
            elif days < 14:
                color = 'var(--q-negative)'
                label_text = f'{days}d'
            else:
                color = 'var(--text)'
                label_text = f'{days}d'
            with ui.row().classes('w-full items-center gap-2'):
                ui.label(d['label']).style(
                    f'flex: 1; font-size: 12px; color: {color}')
                ui.label(label_text).classes(
                    'text-caption num').style(f'color: {color}')


def render_prive_zone(aov_total: float, is_collapsed: bool) -> None:
    """Render Privé-vaste-lasten zone (AOV ONLY).

    AOV is conceptueel privé Box 1 inkomensvoorziening per CLAUDE.md
    "AOV: GEEN bedrijfskosten" — staat dus expliciet niet in de
    bedrijfs-kosten-kolom op het dashboard maar wel zichtbaar als
    privé-vaste-last (relevant voor netto-inkomen-projectie).

    GEEN persoonlijke SPH hier: SPH (Pensioenpremie SPH) is wel
    bedrijfskost in ons model, dus die hoort thuis bij /kosten en de
    SPH-tile, NIET in de privé-zone. Dit was de factuele error in
    v2-discussion die de spec heeft gecorrigeerd.

    `ui.expansion` voor collapse-gedrag. `is_collapsed=True` start
    dichtgeklapt. State-persist via toggle-handler in pages/dashboard.py
    is out-of-scope voor T5.1 — eerste render-iteratie respecteert
    alleen de inkomende `is_collapsed`-waarde uit `should_show_prive_zone`.
    """
    with ui.expansion(
            'Privé-vaste-lasten',
            icon='account_balance_wallet',
            value=not is_collapsed,
        ).classes('w-full prive-zone'):
        with ui.card().classes('w-full q-pa-md').style(
                'border: 1px solid var(--border)'):
            with ui.row().classes('items-center gap-2'):
                ui.label('AOV YTD:').style('font-size: 13px')
                ui.label(format_euro(aov_total, decimals=0)).classes(
                    'num').style('font-size: 13px; font-weight: 600')
            ui.label(
                'Niet aftrekbaar als bedrijfskost — wel relevant voor netto-inkomen.'
            ).classes('text-caption text-grey-6')


def render_va_tile(summary: VATrackSummary, jaar: int) -> None:
    """Render VA-tracker hero-tile op dashboard (Sprint I — vervangt
    Sprint H Belasting-reservering Card 3).

    Toont een line-first overview: hero-value = totaal_resterend
    (verplicht − betaald), per-soort lines (IB/ZVW), volgende-termijn
    footer (alleen bij open verplichting), en bankdata-versheid footer.
    `.is-tekort` modifier alleen bij status='achter' (echte achterstand —
    user heeft een vervaldatum gemist). Overbetaald-badge verschijnt
    alleen bij status='voldaan' AND has_overbetaald (Codex round-3
    line-first principe — toont overbetaling ook bij open totaal).

    Click-target deep-linkt naar /aangifte?jaar=X zodat de gebruiker
    direct de beschikkingsbedragen + termijnen kan controleren.
    """
    is_warning = (summary.status == 'achter')
    card_classes = 'dashboard-hero-tile'
    if is_warning:
        card_classes += ' is-tekort'

    with ui.card().classes(card_classes) \
            .style('cursor: pointer') \
            .on('click', lambda j=jaar: ui.navigate.to(f'/aangifte?jaar={j}')):
        # Title row + warning icon (alleen bij echte achterstand)
        with ui.row().classes('w-full justify-between items-center'):
            ui.label(f'Voorlopige aanslag {jaar}').classes('hero-label')
            if is_warning:
                tooltip = (
                    f'Achterstand: '
                    f'{format_euro(summary.totaal_achterstand, decimals=0)}'
                )
                ui.icon('warning', size='18px').style(
                    'color: var(--q-negative)').tooltip(tooltip)

        # Geen-data fallback (geen beschikking + geen bankdata)
        if summary.status == 'geen_data':
            ui.label('—').classes('hero-value')
            ui.label(
                f'Geen beschikking of bankbetalingen voor {jaar}'
            ).classes('context-text').style('margin-top: 8px')
            return

        # Geen-beschikking fallback (bankdata wel, beschikking niet —
        # tile linkt door naar /aangifte zodat user de jaarbedragen
        # invult; we tonen alvast wat de bank aan IB/ZVW + termijnen
        # heeft gevangen, plus unmatched-regel als die er is)
        if summary.status == 'geen_beschikking':
            ui.label('—').classes('hero-value')
            ui.label('Bankbetalingen gevonden — vul beschikking in').classes(
                'context-text').style('margin-top: 8px')
            ui.label(
                f'IB  {format_euro(summary.ib.betaald, decimals=0)} '
                f'· {summary.ib.betaalde_termijnen} termijnen'
            ).classes('context-text')
            ui.label(
                f'ZVW {format_euro(summary.zvw.betaald, decimals=0)} '
                f'· {summary.zvw.betaalde_termijnen} termijnen'
            ).classes('context-text')
            if summary.unmatched_betaald > 0:
                ui.label(
                    f'Niet toegewezen: '
                    f'{format_euro(summary.unmatched_betaald, decimals=0)} '
                    f'({summary.unmatched_termijnen} betalingen)'
                ).classes('context-text').style('color: var(--q-warning)')
            return

        # Hero value: resterend (wat nog moet worden betaald aan BD)
        with ui.row().classes('w-full items-baseline gap-2'):
            ui.label(format_euro(summary.totaal_resterend, decimals=0)) \
                .classes('hero-value')
            # Overbetaald-badge: alleen bij voldaan AND has_overbetaald
            # — niet bij status='bij' want dan kan een IB-overbetaling een
            # nog-open ZVW-resterend maskeren (Codex round-3 motivatie).
            if summary.status == 'voldaan' and summary.has_overbetaald:
                overbetaald = (summary.ib.overbetaald
                               + summary.zvw.overbetaald)
                ui.label(
                    f'overbetaald {format_euro(overbetaald, decimals=0)}'
                ).style(
                    'font-size: 12px; color: var(--q-warning); '
                    'background: var(--bg-warning-soft); '
                    'padding: 2px 8px; border-radius: 10px')

        # Body: per-soort lines (IB + ZVW) — sla over als zowel
        # verplichting als betaald 0 zijn (bv. ZVW niet apart aangeslagen).
        for line in (summary.ib, summary.zvw):
            if line.verplicht == 0 and line.betaald == 0:
                continue
            ui.label(
                f'{line.soort}    '
                f'{format_euro(line.betaald, decimals=0)} / '
                f'{format_euro(line.verplicht, decimals=0)}  ·  '
                f'rest {format_euro(line.resterend, decimals=0)}'
            ).classes('context-text')
            ui.label(
                f'   {line.betaalde_termijnen} v.d. {line.totaal_termijnen}'
                f'   ± {format_euro(line.termijnbedrag, decimals=0)} p/m'
            ).classes('context-text').style('opacity: 0.75')

        # Unmatched-regel (Codex T1.4 catch — spec §4 vereist deze als
        # sub-line bij > 0). Bankbetalingen zonder bruikbaar kenmerk
        # mogen niet stil onzichtbaar blijven op het dashboard.
        if summary.unmatched_betaald > 0:
            ui.label(
                f'Niet toegewezen: '
                f'{format_euro(summary.unmatched_betaald, decimals=0)} '
                f'({summary.unmatched_termijnen} betalingen)'
            ).classes('context-text').style('color: var(--q-warning)')

        # Volgende-termijn footer — alleen bij open verplichting
        # (compute_va_tracker zet None bij voldaan/closed/geen-data).
        if summary.volgende_termijn_datum is not None:
            datum_str = format_datum_jaar_nl(summary.volgende_termijn_datum)
            ui.label(f'Volgende termijn: {datum_str}').classes(
                'context-text').style('margin-top: 4px; opacity: 0.85')

        # Bankdata-versheid footer — laat user weten t/m welke datum
        # de bankbetalingen geteld zijn (anders is "betaald = X" zonder
        # context — lijkt definitief terwijl er nog rijen later inkomen).
        if summary.bankdata_tot_datum is not None:
            datum_str = format_datum_kort_nl(summary.bankdata_tot_datum)
            ui.label(f'Bankdata t/m {datum_str}').classes(
                'context-text').style('opacity: 0.6; font-size: 11px')
