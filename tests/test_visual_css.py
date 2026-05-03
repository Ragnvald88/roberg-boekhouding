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
    """Sprint B cascade-rule: Quasar `.q-*` overrides MUST be unlayered.

    Layered styles always lose to Quasar's unlayered defaults regardless
    of specificity. If you put `.q-card` or `.q-table th` inside
    @layer components, your override silently won't apply.

    Allowed exceptions: `.q-*` references inside `var(--q-...)` are
    Quasar's own custom-property names (e.g. var(--q-primary)) and don't
    count as selectors.
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
