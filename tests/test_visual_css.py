"""Cascade-lint tests for components/layout.py CSS.

Sprint B introduced the cascade-rule: Quasar `.q-*` overrides MUST live
OUTSIDE `@layer components { ... }` because layered styles always lose
to Quasar's unlayered defaults regardless of specificity. App-only
classes (`.app-card`, `.nav-item`, `.wd-pill`, etc.) live INSIDE the
layer.

These tests parse the CSS embedded in `components/layout.py` and assert
the cascade-rule + a few specific invariants that previously broke
silently (holiday/blocker fills overruled by `.agenda-cell` base).
"""

from __future__ import annotations

import re
from pathlib import Path


LAYOUT_PY = Path(__file__).parent.parent / 'components' / 'layout.py'


def _extract_css() -> str:
    """Extract the CSS string from `ui.add_css('''...''')` in layout.py."""
    src = LAYOUT_PY.read_text()
    # Match ui.add_css('''...''') including newlines
    match = re.search(
        r"ui\.add_css\('''(.*?)'''\s*,\s*shared=True\)",
        src,
        re.DOTALL,
    )
    assert match is not None, (
        "Could not find ui.add_css('''...''') block in layout.py"
    )
    return match.group(1)


def _extract_layer_components(css: str) -> str:
    """Extract content of `@layer components { ... }` using brace-counting.

    Naive approaches (`awk` ranges, regex .*?}) break on nested braces.
    We scan from `@layer components {` and count braces until back to 0.
    """
    start_pat = re.compile(r"@layer\s+components\s*\{")
    m = start_pat.search(css)
    assert m is not None, "@layer components block not found in CSS"

    open_idx = m.end()
    depth = 1
    i = open_idx
    while i < len(css) and depth > 0:
        ch = css[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        i += 1
    assert depth == 0, "Unbalanced braces in @layer components block"
    # `i` is now one PAST the closing `}` of the layer
    return css[open_idx:i - 1]


def _strip_comments(css: str) -> str:
    """Remove /* ... */ comments so selector-pattern matches don't false-positive."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def test_no_q_star_selectors_inside_layer_components():
    """Sprint B cascade-rule (NARROW scope): selectors literally starting
    with `.q-` MUST NOT be inside @layer components.

    **Caveat (Codex post-Sprint-F audit)**: this test catches only
    selectors that begin with `.q-` (e.g. `.q-card`, `.q-table th`).
    The actual cascade rule is broader — ANY app-class that gets
    APPLIED to a Quasar element via NiceGUI `.classes(...)` (e.g.
    `.alert-icon` on `q-icon`, `.alert-link` on `q-btn`, `.nav-icon`
    on `q-icon`) loses to Quasar's unlayered defaults if it lives
    inside @layer. See `test_known_quasar_applied_classes_unlayered`
    below for an explicit allow-list of those.

    Allowed exception in this test: `.q-*` references inside
    `var(--q-...)` are Quasar's own CSS custom properties (e.g.
    `var(--q-primary)`) and don't count as selectors.
    """
    css = _extract_css()
    layer_content = _extract_layer_components(css)
    layer_no_comments = _strip_comments(layer_content)

    # Find all selectors. A selector is anything before `{` at start of
    # a line (modulo whitespace). We split on `{` and `}` to avoid
    # matching inside rule bodies.
    bad_selectors = []
    for line in layer_no_comments.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('/*'):
            continue
        # Look for selector lines (end with `{` or `,`)
        if '{' in stripped:
            selector_part = stripped.split('{')[0].strip()
            # Check if selector contains `.q-` (Quasar selector)
            # but NOT inside `var(--q-...)` (which is a CSS custom prop)
            # Strip out var() expressions before checking
            selector_clean = re.sub(r"var\([^)]*\)", "", selector_part)
            if re.search(r"\.q-", selector_clean):
                bad_selectors.append(selector_part)

    assert not bad_selectors, (
        f"Found {len(bad_selectors)} `.q-*` selector(s) inside "
        f"@layer components (cascade-rule violation — these will lose to "
        f"Quasar's unlayered defaults): {bad_selectors}"
    )


def test_q_card_is_unlayered():
    """Sprint B T6 invariant: `.q-card { ... }` must be defined OUTSIDE
    @layer components so it wins over Quasar's defaults."""
    css = _extract_css()
    layer_content = _extract_layer_components(css)

    # `.q-card` (exact, no chained selectors like `.q-card.builder-line-card`)
    # must NOT be inside layer
    inside_layer = bool(re.search(
        r"^\s*\.q-card\s*\{", layer_content, re.MULTILINE
    ))
    assert not inside_layer, (
        "`.q-card { ... }` must be defined OUTSIDE @layer components "
        "(Sprint B T6 cascade-discipline)"
    )

    # And it must exist somewhere (= outside layer, since not inside)
    css_full = _strip_comments(css)
    has_q_card = bool(re.search(
        r"^\s*\.q-card\s*\{", css_full, re.MULTILINE
    ))
    assert has_q_card, "`.q-card` definition missing entirely from layout.py"


def test_holiday_blocker_use_chained_selectors():
    """Sprint B post-merge fix #1: `.holiday-marker` and `.blocker-*`
    must be chained with `.agenda-cell.X` to win over `.agenda-cell`'s
    base `background: white;`. Naked `.holiday-marker { background: ... }`
    or `.blocker-vacation { background: ... }` lose source-order.
    """
    css = _strip_comments(_extract_css())

    # Naked `.holiday-marker { ... background ... }` is FORBIDDEN
    # (would be overruled by .agenda-cell). Chained `.agenda-cell.holiday-marker`
    # is REQUIRED.
    naked_holiday = re.search(
        r"^\s*\.holiday-marker\s*\{[^}]*background", css, re.MULTILINE | re.DOTALL
    )
    assert not naked_holiday, (
        "Naked `.holiday-marker { background: ... }` lost cascade-fight "
        "with `.agenda-cell` base. Use `.agenda-cell.holiday-marker` instead."
    )

    chained_holiday = re.search(
        r"\.agenda-cell\.holiday-marker\s*\{[^}]*background", css, re.DOTALL
    )
    assert chained_holiday, (
        "Required `.agenda-cell.holiday-marker { background: ... }` "
        "chained selector missing — holidays will not show fill."
    )

    # Same for blockers
    for kind in ('vacation', 'sick', 'training'):
        naked = re.search(
            rf"^\s*\.blocker-{kind}\s*\{{[^}}]*background", css, re.MULTILINE | re.DOTALL
        )
        assert not naked, (
            f"Naked `.blocker-{kind} {{ background: ... }}` lost cascade-fight. "
            f"Use `.agenda-cell.blocker-{kind}` instead."
        )

        chained = re.search(
            rf"\.agenda-cell\.blocker-{kind}\s*\{{[^}}]*background", css, re.DOTALL
        )
        assert chained, (
            f"Required `.agenda-cell.blocker-{kind} {{ background: ... }}` "
            f"chained selector missing — {kind}-blockers will not show overlay."
        )


# Classes-applied-to-Quasar-elements registry (Codex post-Sprint-F audit).
# These app-only classes are documented as targeting `q-icon` / `q-btn` via
# NiceGUI `.classes(...)`. They MUST be defined OUTSIDE @layer components
# because Quasar's unlayered defaults (e.g. `q-icon { color: inherit }`,
# `q-btn { color: inherit; border: 0 }`) win over layered styles.
# Add to this list whenever you create a new such class.
QUASAR_APPLIED_APP_CLASSES = [
    'nav-icon',         # used on `ui.icon(...)` in components/layout.py:_nav_item
    'alert-icon',       # used on `ui.icon(...)` in pages/dashboard.py
    'alert-link',       # used on `ui.button(...)` in pages/dashboard.py
    'severity-fg',      # used on `ui.icon(...)` + `ui.button(...)` in pages/dashboard.py
    'settings-card',    # Sprint G — applied to ui.card (= .q-card) in pages/instellingen.py
    'dashboard-hero-tile',  # Sprint H — applied to ui.card (= .q-card) in pages/dashboard.py
]


def test_known_quasar_applied_classes_unlayered():
    """Sprint B/F cascade-rule (BROAD): app-classes applied to Quasar
    elements MUST be defined outside @layer components.

    Catches the regression that bit Sprint F (commit 25cc442 → 5618c15
    fix): `.alert-link`/`.alert-icon`/`.severity-fg` were placed inside
    @layer and silently lost color/border to Quasar defaults. Same for
    `.nav-icon` (Codex post-Sprint-F audit catch).

    See QUASAR_APPLIED_APP_CLASSES list — add entries when introducing
    a new class that gets attached to ui.icon / ui.button / ui.q_td etc.
    """
    css = _strip_comments(_extract_css())
    layer_content = _strip_comments(_extract_layer_components(css))

    leaked = []
    for cls in QUASAR_APPLIED_APP_CLASSES:
        # Look for `.cls` selector appearing as part of any rule (handles
        # both `.cls { ... }` and `.parent .cls { ... }` etc.) inside
        # @layer. We accept the class anywhere in a selector.
        # Match `.cls` followed by whitespace, `{`, `,`, `:`, or `>`
        # (ie. CSS-selector boundary), but NOT `.cls-something` (longer name).
        pattern = rf"\.{re.escape(cls)}(?=[\s{{,:>]|$)"
        if re.search(pattern, layer_content, re.MULTILINE):
            leaked.append(cls)

    assert not leaked, (
        f"App-classes applied to Quasar elements found INSIDE "
        f"@layer components: {leaked}. These will lose color/border to "
        f"Quasar's unlayered defaults. Move them to the unlayered "
        f"`/* === Quasar-overrules BUITEN @layer === */` block in "
        f"components/layout.py."
    )


def test_sprint_f_alert_severity_modifiers_complete():
    """Sprint F cascade-vars contract: each .alert-card-- and
    .severity-card-- modifier MUST define ALL its expected CSS-vars.

    Catches typos (e.g. --alert-bg vs --alert-background) that would
    silently leave a card transparent.
    """
    css = _strip_comments(_extract_css())

    alert_required = {'--alert-bg', '--alert-border', '--alert-icon',
                      '--alert-title', '--alert-body', '--alert-link'}
    severity_required = {'--severity-bg', '--severity-border',
                         '--severity-fg', '--severity-dark'}

    for variant in ('--warning', '--attention'):
        block_match = re.search(
            rf"\.alert-card{re.escape(variant)}\s*\{{(.*?)\}}",
            css, re.DOTALL,
        )
        assert block_match, f".alert-card{variant} block missing in CSS"
        block = block_match.group(1)
        defined = set(re.findall(r"--alert-[a-z-]+", block))
        missing = alert_required - defined
        assert not missing, (
            f".alert-card{variant} missing vars: {missing}. "
            f"Defined: {defined}. Required: {alert_required}."
        )

    for variant in ('--danger-deep', '--danger', '--info'):
        block_match = re.search(
            rf"\.severity-card{re.escape(variant)}\s*\{{(.*?)\}}",
            css, re.DOTALL,
        )
        assert block_match, f".severity-card{variant} block missing in CSS"
        block = block_match.group(1)
        defined = set(re.findall(r"--severity-[a-z-]+", block))
        missing = severity_required - defined
        assert not missing, (
            f".severity-card{variant} missing vars: {missing}. "
            f"Defined: {defined}. Required: {severity_required}."
        )


def test_sprint_g_settings_card_chained_selector():
    """Sprint G cascade-rule: .settings-card MUST be defined as chained
    selector .q-card.settings-card (not naked .settings-card) to win from
    Quasar's unlayered .q-card defaults via specificity + source order.

    Naked .settings-card { ... } would lose to .q-card { background: white }
    on equal specificity since Quasar declares its defaults later in the
    cascade. Same lesson as agenda-cell.holiday-marker (Sprint A) and
    .alert-link (Sprint F).

    Complements `test_known_quasar_applied_classes_unlayered` (broad allow-
    list test, line ~199): that test catches `.settings-card` leaking INSIDE
    @layer components; this one additionally asserts the chained form
    EXISTS (anywhere) and that no naked form exists outside the layer either.
    """
    css = _strip_comments(_extract_css())

    # Naked .settings-card declaration without .q-card prefix would match
    # this regex; chained .q-card.settings-card would not.
    naked_pattern = r"(?<![.\w-])\.settings-card\s*\{"
    naked_matches = re.findall(naked_pattern, css)

    chained_pattern = r"\.q-card\.settings-card\s*\{"
    chained_matches = re.findall(chained_pattern, css)

    assert chained_matches, (
        "Sprint G: .settings-card MUST be defined as chained selector "
        ".q-card.settings-card { ... } in components/layout.py — naked "
        ".settings-card loses to Quasar's unlayered .q-card defaults."
    )
    assert not naked_matches, (
        f"Sprint G: found naked .settings-card definition(s). Use chained "
        f"selector .q-card.settings-card { { ... } } instead. Hits: {naked_matches}"
    )


def test_sprint_g_settings_section_defined():
    """Sprint G: .settings-section MUST be defined in CSS (no chained-
    selector requirement — applied to plain ui.column, not q-card)."""
    css = _strip_comments(_extract_css())
    pattern = r"\.settings-section\s*\{"
    matches = re.findall(pattern, css)
    assert matches, ".settings-section selector missing in components/layout.py"


def test_sprint_h_dashboard_hero_tile_chained_selector():
    """Sprint H cascade-rule: .dashboard-hero-tile MUST be defined as
    chained selector .q-card.dashboard-hero-tile (not naked) to win
    from Quasar's unlayered .q-card defaults.

    Same lesson as agenda-cell.holiday-marker (Sprint A) and
    .alert-link (Sprint F) and .settings-card (Sprint G).
    """
    css = _strip_comments(_extract_css())

    naked_pattern = r"(?<![.\w-])\.dashboard-hero-tile\s*\{"
    naked_matches = re.findall(naked_pattern, css)

    chained_pattern = r"\.q-card\.dashboard-hero-tile\s*\{"
    chained_matches = re.findall(chained_pattern, css)

    assert chained_matches, (
        "Sprint H: .dashboard-hero-tile MUST be defined as chained "
        ".q-card.dashboard-hero-tile { ... } in components/layout.py."
    )
    assert not naked_matches, (
        f"Sprint H: found naked .dashboard-hero-tile definition. "
        f"Use chained selector instead. Hits: {naked_matches}"
    )


def test_sprint_h_is_tekort_modifier_defined():
    """Sprint H: .is-tekort modifier MUST exist as chained selector
    .q-card.dashboard-hero-tile.is-tekort with at least border-left."""
    css = _strip_comments(_extract_css())
    pattern = r"\.q-card\.dashboard-hero-tile\.is-tekort\s*\{"
    matches = re.findall(pattern, css)
    assert matches, ".is-tekort modifier missing"
