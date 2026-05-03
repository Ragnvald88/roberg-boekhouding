"""Shared layout: header + sidebar navigatie + theming."""

from nicegui import ui

ui.card.default_props('flat bordered')
ui.card.default_classes('rounded-xl')
ui.button.default_props('unelevated no-caps')
ui.input.default_props('outlined dense')
ui.number.default_props('outlined dense')
ui.select.default_props('outlined dense')
ui.table.default_props('flat bordered separator=horizontal')

ui.add_css('''
/* === TOKENS (Sprint B) === */
:root {
    --bg: #F5F5F7;            /* page background — system gray */
    --surface: #FFFFFF;        /* cards, dialogs, header */
    --border: rgba(60,60,67,0.12);
    --text: #1C1C1E;           /* primary ink */
    --muted: #6E6E73;          /* secondary ink, labels, captions */
    --accent: #0F766E;         /* teal brand — unchanged */
    --accent-soft: rgba(15,118,110,0.10);
    --shadow: 0 2px 8px rgba(0,0,0,0.06);
    --radius: 12px;
}

/* === BASE === */
body {
    background: var(--bg);
    font-family: -apple-system, "SF Pro Text", system-ui, sans-serif;
    color: var(--text);
}
.q-page {
    font-family: -apple-system, "SF Pro Text", system-ui, sans-serif;
}
.text-h1, .text-h2, .text-h3, .text-h4, .text-h5, .text-h6 {
    font-family: -apple-system, "SF Pro Display", system-ui, sans-serif;
    /* Geen color hier — body zet color: var(--text) en headings erven dat
       via inheritance. Dit voorkomt dat we Quasar utilities overrulen
       (bv. .text-h6.text-white in de huidige donkere header tijdens
       Tier 1 progressie, of .text-primary elders). */
}

/* === QUASAR OVERRIDES (UNLAYERED — winnen van Quasar defaults) === */
/* Sprint B Codex regel: Quasar's eigen CSS is unlayered; layered styles
   verliezen ALTIJD van unlayered ongeacht specificity. Daarom alle .q-*
   overrides hier buiten @layer components plaatsen. */

/* Table header styling */
.q-table th {
    background-color: #F1F5F9;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 0.05em;
    color: #475569;
}
.q-table tbody tr:nth-child(even) {
    background-color: #F8FAFC;
}

/* Page-toolbar Quasar overrides */
.page-toolbar .q-field { min-height: unset; }

/* White pill selects inside toolbar */
.page-toolbar .q-field--outlined .q-field__control {
    background: white !important;
    border-color: transparent !important;
    border-radius: 20px !important;
    min-height: 36px !important;
    transition: box-shadow 0.15s ease;
}
.page-toolbar .q-field--outlined .q-field__control:hover {
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
}
.page-toolbar .q-field--outlined.q-field--focused .q-field__control {
    border-color: var(--q-primary) !important;
    box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.12);
}
.page-toolbar .q-field__label {
    font-size: 11px !important;
}

/* Card defaults — Sprint B token-driven */
.q-card {
    border-radius: var(--radius);
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    background: var(--surface);
}

/* Invoice-builder line-cards: bewust géén shadow (visuele rhythm in line-stack).
   Moet buiten @layer staan om de globale .q-card shadow hierboven te overrulen. */
.q-card.builder-line-card {
    box-shadow: none;
    border: 1px solid var(--q-separator-color, #e2e8f0);
}

/* Button polish — Sprint B (NIET op round/rounded modifiers — die houden Quasar's cirkel-shape) */
.q-btn:not(.q-btn--round):not(.q-btn--rounded) {
    border-radius: 8px;
}

/* Field polish — Sprint B (alleen radius op outlined fields buiten toolbar) */
.q-field--outlined .q-field__control {
    border-radius: 8px;
}

@layer components {
    /* Page toolbar — tinted bar with pill-shaped filters */
    .page-toolbar {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 14px;
        background: #EDF2F7;
        border-radius: 12px;
    }

    /* Invoice builder panel styling */
    .builder-panel-border { border-right: 1px solid var(--q-separator-color, #e2e8f0); }
    .builder-preview-bg { background: var(--q-separator-color, #e2e8f0); }

    /* Sidebar nav — Sprint B lichte variant */
    .nav-item {
        display: flex; align-items: center; gap: 10px;
        padding: 7px 14px; margin: 1px 8px;
        border-radius: 8px; cursor: pointer;
        color: var(--muted); font-size: 13px; font-weight: 400;
        transition: background 0.12s, color 0.12s;
        text-decoration: none; border: none; background: none;
        width: calc(100% - 16px);
        position: relative;
    }
    .nav-item:hover {
        background: rgba(60,60,67,0.05);
        color: var(--text);
    }
    .nav-item .nav-icon {
        font-size: 18px; width: 20px; text-align: center;
        color: var(--muted);
    }
    .nav-item:hover .nav-icon { color: var(--text); }

    .nav-item.active {
        color: var(--text);
        background: var(--accent-soft);
        font-weight: 600;
    }
    .nav-item.active .nav-icon { color: var(--accent); }
    .nav-item.active::after {
        content: '';
        width: 6px; height: 6px; border-radius: 50%;
        background: var(--accent);
        position: absolute; right: 12px; top: 50%;
        transform: translateY(-50%);
    }

    .nav-gap { height: 12px; }
    .nav-divider { height: 1px; background: var(--border); margin: 8px 16px; }

    /* Dashboard design tokens */
    .hero-label { font-size: 13px; color: #64748B; font-weight: 500; }
    .hero-value { font-size: 30px; font-weight: 700; color: #0F172A;
                  font-variant-numeric: tabular-nums; margin: 6px 0 2px; }
    .hero-value-positive { font-size: 30px; font-weight: 700; color: var(--q-positive);
                           font-variant-numeric: tabular-nums; margin: 6px 0 2px; }
    .hero-value-negative { font-size: 30px; font-weight: 700; color: var(--q-negative);
                           font-variant-numeric: tabular-nums; margin: 6px 0 2px; }
    .context-text { font-size: 12px; color: #94A3B8; }
    .section-label { font-size: 13px; font-weight: 600; color: #64748B;
                     text-transform: uppercase; letter-spacing: 0.05em; }
    .chart-title { font-size: 15px; font-weight: 600; color: #0F172A; }
    .chart-subtitle { font-size: 12px; color: #94A3B8; }
    .strip-value { font-size: 14px; font-weight: 600; color: #0F172A; }
    .strip-pct { font-size: 11px; color: #94A3B8; }
    .card-hero {
        border-radius: var(--radius);
        border: 1px solid var(--border);
        box-shadow: var(--shadow);
        background: var(--surface);
    }

    /* === REDESIGN PORT — design tokens & herbruikbare helpers ===
       Eerste introductie van het token-systeem uit
       redesign/design_handoff_boekhouding_redesign/source/styles.css.
       Initieel alleen gebruikt door de Werkdagen-pagina; later uit te
       breiden per pagina. Bestaande hex-styling blijft onveranderd. */

    .num {
        font-family: "SF Mono", ui-monospace, Menlo, monospace;
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.02em;
    }
    .mono { font-family: "SF Mono", ui-monospace, Menlo, monospace; }
    .t-micro {
        font-size: 11px; font-weight: 500;
        letter-spacing: 0.08em; text-transform: uppercase;
        color: #6b6f76;
    }

    /* Chip — kleurvariatie via modifier-klasse */
    .chip {
        display: inline-flex; align-items: center;
        padding: 2px 8px; border-radius: 6px;
        font-size: 11px; font-weight: 500; line-height: 1.4;
        background: #f5f4ef; color: #3a3d43;
        font-family: "SF Mono", ui-monospace, Menlo, monospace;
    }
    .chip.pos { background: #e6f2f0; color: #0a524c; }
    .chip.info { background: #dbeafe; color: #1e3a8a; }
    .chip.warn { background: #fef3c7; color: #854d0e; }
    .chip.neutral { background: #f5f4ef; color: #6b6f76; }
    .chip.neg { background: #fbeadb; color: #7c2d12; }

    /* Segmented tabs (Alle / Ongefactureerd / ANW) */
    .seg {
        display: inline-flex;
        border: 1px solid #e8e6df; border-radius: 7px;
        overflow: hidden; background: #ffffff;
    }
    .seg-btn {
        padding: 7px 14px; border: 0;
        border-right: 1px solid #e8e6df;
        background: #ffffff; color: #3a3d43;
        font-size: 12px; cursor: pointer;
        font-family: "SF Mono", ui-monospace, Menlo, monospace;
        transition: background 0.1s;
    }
    .seg-btn:last-child { border-right: 0; }
    .seg-btn:hover { background: #f0efe9; }
    .seg-btn.on { background: #15171a; color: #fafaf7; }

    /* Sticky selection bar voor bulk-acties */
    .selection-bar {
        position: sticky; top: 0; z-index: 5;
        background: #15171a; color: #fafaf7;
        padding: 10px 20px; border-radius: 10px;
        margin-bottom: 12px;
        display: flex; align-items: center; gap: 16px;
        box-shadow: 0 8px 24px -12px rgba(20,20,20,0.18);
    }
    .selection-bar .sb-count {
        font-family: "SF Mono", ui-monospace, Menlo, monospace; font-size: 13px;
    }
    .selection-bar .sb-meta {
        font-family: "SF Mono", ui-monospace, Menlo, monospace; font-size: 12px;
        opacity: 0.75;
    }

    /* Page subtitle (onder page_title) */
    .page-sub {
        font-size: 13px; color: #6b6f76;
        margin-top: 2px; font-family: "SF Mono", ui-monospace, Menlo, monospace;
    }

    /* Locatie-subline onder klant-naam in tabel */
    .cell-sub {
        font-size: 11px; color: #9a9ea5; margin-top: 1px;
    }

    /* === Agenda — werkdag-categorie kleuren (type-based, not per-klant) === */
    .wd-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 1px 6px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: 500;
        line-height: 1.4;
        margin: 1px 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 100%;
    }
    .wd-dagpraktijk { background: rgba(15,118,110,0.12); color: #0F766E; }
    .wd-anw         { background: rgba(126,34,206,0.12); color: #7E22CE; }
    .wd-overig      { background: rgba(100,116,139,0.12); color: #475569; }

    /* Verwachte entries (recurring) — dashed border + soft fill */
    .wd-pill.expected {
        border: 1px dashed currentColor;
        opacity: 0.7;
    }

    /* Status-bars onder werkdag-pills — per factuur-status */
    .wd-status-bar {
        display: flex;
        height: 3px;
        gap: 1px;
        margin-top: 2px;
    }
    .wd-status-bar > span {
        flex: 1;
        border-radius: 1px;
    }
    .status-ongefactureerd { background: #94A3B8; }
    .status-concept        { background: #94A3B8; opacity: 0.6; }
    .status-verstuurd      { background: #2563EB; }
    .status-verlopen       { background: #DC2626; }
    .status-betaald        { background: #16A34A; }

    /* Holiday marker (computed dutch_holidays) — top-band, niet full-fill */
    .holiday-marker {
        background: linear-gradient(180deg, rgba(220,38,38,0.08), transparent);
        border-top: 2px solid #DC2626;
    }
    .holiday-label {
        font-size: 10px;
        color: #DC2626;
        font-weight: 500;
    }

    /* Blocker overlays — per kind */
    .blocker-vacation { background: rgba(90,200,250,0.10); }
    .blocker-sick     { background: rgba(255,149,0,0.10); }
    .blocker-training { background: rgba(175,82,222,0.10); }

    /* Maandgrid cell-states */
    .agenda-cell {
        border: 1px solid #E2E8F0;
        border-radius: 4px;
        padding: 4px;
        min-height: 80px;
        cursor: pointer;
        display: flex;
        flex-direction: column;
        gap: 2px;
        background: white;
        transition: background 0.1s;
    }
    .agenda-cell:hover { background: #F1F5F9; }
    .agenda-cell.other-month { opacity: 0.4; }
    .agenda-cell.weekend { background: #F8FAFC; }
    .agenda-cell.today { box-shadow: inset 0 0 0 1px #14B8A6; }
    .agenda-cell.selected { box-shadow: inset 0 0 0 2px #0F766E; background: rgba(15,118,110,0.05); }
    .agenda-cell-day { font-size: 11px; font-weight: 500; color: #475569; }
    .agenda-cell-overflow { font-size: 9px; color: #94A3B8; }

    /* Week-summary kolom rechts van de 7 dagen */
    .week-summary {
        border: 1px solid #E2E8F0;
        border-radius: 4px;
        padding: 6px 8px;
        background: #F8FAFC;
        font-size: 11px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        gap: 1px;
    }
    .week-summary.current {
        background: linear-gradient(180deg, rgba(15,118,110,0.08), rgba(15,118,110,0.02));
    }
    .week-summary-num { font-weight: 600; color: #475569; }
    .week-summary-amt { font-weight: 600; color: #0F172A; font-variant-numeric: tabular-nums; }
    .week-summary-meta { font-size: 9px; color: #94A3B8; }
}
''', shared=True)

# Sprint B: Google Fonts CDN-link voor JetBrains Mono verwijderd —
# alle .num/.mono/.chip/.seg-btn/.selection-bar/.page-sub classes
# gebruiken nu SF Mono (system-font, OS-native vanaf macOS 10.11).


def page_title(text: str):
    """Render a consistent page title label."""
    return ui.label(text).classes('text-h5') \
        .style('color: var(--text); font-weight: 700')


def create_layout(title: str, active_page: str = ''):
    """Shared layout: teal header, dark sidebar, off-white content."""

    # Navigation groups (separated by whitespace, no headers)
    NAV_GROUPS = [
        [('Dashboard', 'space_dashboard', '/'),
         ('Agenda', 'calendar_month', '/agenda'),
         ('Werkdagen', 'event_note', '/werkdagen')],
        [('Facturen', 'receipt_long', '/facturen'),
         ('Transacties', 'account_balance_wallet', '/transacties'),
         ('Kosten', 'shopping_bag', '/kosten')],
        [('Documenten', 'folder_open', '/documenten'),
         ('Jaarafsluiting', 'assessment', '/jaarafsluiting'),
         ('Aangifte', 'assignment', '/aangifte')],
    ]
    SETUP_PAGES = [
        ('Klanten', 'people_outline', '/klanten'),
        ('Instellingen', 'tune', '/instellingen'),
    ]

    # Brand colors
    ui.colors(
        primary='#0F766E',
        secondary='#475569',
        accent='#F59E0B',
        positive='#059669',
        negative='#DC2626',
        info='#2563EB',
        warning='#D97706',
    )

    # Background komt nu uit CSS-token --bg (zie ui.add_css blok bovenin).
    # Inline-style hier zou CSS overrulen — daarom weggehaald in Sprint B.

    with ui.header().classes('items-center') \
            .style('background-color: var(--surface); '
                   'border-bottom: 1px solid var(--border); '
                   'box-shadow: none;'):
        ui.button(icon='menu', on_click=lambda: drawer.toggle()) \
            .props('flat round dense') \
            .style('color: var(--text)')
        ui.label('Boekhouding').classes('text-h6 q-ml-sm') \
            .style('color: var(--text); font-weight: 600')
        ui.space()
        ui.label(title).classes('text-subtitle1').style('color: var(--muted)')

    drawer = ui.left_drawer(value=True, bordered=False) \
        .style('background: linear-gradient(180deg, '
               '#FAFAFA 0%, '
               'rgba(15,118,110,0.02) 30%, '
               'var(--bg) 100%); '
               'border-right: 1px solid var(--border);') \
        .props('width=180')

    def _nav_item(label, icon, target):
        """Render a single nav item with active state."""
        is_active = (target == active_page
                     or target.split('?')[0] == active_page)
        cls = 'nav-item active' if is_active else 'nav-item'
        with ui.element('div').classes(cls) \
                .on('click', lambda t=target: ui.navigate.to(t)):
            ui.icon(icon).classes('nav-icon')
            ui.label(label)

    with drawer:
        ui.element('div').style('height: 12px')  # top spacing

        for i, group in enumerate(NAV_GROUPS):
            if i > 0:
                ui.element('div').classes('nav-gap')
            for label, icon, target in group:
                _nav_item(label, icon, target)

        ui.element('div').classes('nav-divider')

        for label, icon, target in SETUP_PAGES:
            _nav_item(label, icon, target)
