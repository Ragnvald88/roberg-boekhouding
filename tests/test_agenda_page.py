"""Smoke tests voor /agenda — verifieert dat module importeert + page geregistreerd."""


def test_agenda_module_imports():
    """Module should import zonder error."""
    import pages.agenda
    assert hasattr(pages.agenda, 'agenda_page')


def test_agenda_page_is_registered():
    """Should be registered under /agenda route."""
    import pages.agenda  # noqa: F401 — ensures registration
    from nicegui import app
    routes = {
        getattr(r, 'path', None) for r in app.routes
        if hasattr(r, 'path')
    }
    assert '/agenda' in routes


def test_agenda_page_handler_is_async():
    """Page handler should be async coroutine function (NiceGUI requirement)."""
    import inspect
    import pages.agenda
    assert inspect.iscoroutinefunction(pages.agenda.agenda_page)


def test_new_werkdag_button_is_wired():
    """Regression-pin: refs['new_btn'].on_click(...) must exist in
    pages/agenda.py AND wire to handle_add_werkdag(state['selected']) —
    voorkomt dat een refactor het wel-gewired-maar-leeg patroon
    (lambda: None) per ongeluk re-introduceert.
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'pages' / 'agenda.py'
    text = src.read_text(encoding='utf-8')
    assert "refs['new_btn'].on_click" in text, (
        "refs['new_btn'].on_click(...) wiring missing — "
        "Nieuwe werkdag knop zal niet werken")
    # Tighten: ook de call-target controleren — code-quality review #2.
    assert "handle_add_werkdag(state['selected'])" in text, (
        "wiring exists maar roept handle_add_werkdag(state['selected']) "
        "niet aan — knop opent geen dialog")


def _render_loop_slice() -> str:
    """Return de pill-render-loop body uit pages/agenda.py.

    Slice tussen `for pill in all_pills[:3]:` (begin) en
    `if len(all_pills) > 3:` (overflow-handler) — alle pill-handler-
    code zit binnen deze regio.
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'pages' / 'agenda.py'
    text = src.read_text(encoding='utf-8')
    start = text.find('for pill in all_pills[:3]:')
    end = text.find('if len(all_pills) > 3:')
    assert start > 0 and end > start, (
        'render-loop ankers veranderd — update test')
    return text[start:end]


def test_pill_render_loop_uses_stop_propagation():
    """Pill click MUST call e.stopPropagation() — anders bubblet event
    naar cell-click en triggert day-select bovenop edit-dialog."""
    slice_text = _render_loop_slice()
    assert 'e.stopPropagation()' in slice_text


def test_pill_render_loop_uses_native_context_menu():
    """Right-click via ui.context_menu() (NiceGUI native), niet @contextmenu."""
    slice_text = _render_loop_slice()
    assert 'ui.context_menu()' in slice_text


def test_pill_render_loop_renders_tooltip():
    slice_text = _render_loop_slice()
    assert 'ui.tooltip(' in slice_text


def test_pill_handlers_only_under_is_expected_guard():
    """Tooltip + click + context-menu moeten ALLE drie ná `if not is_expected:`
    binnen de render-loop staan — anders krijgen expected pills (recurring)
    de handlers ook, wat het Day-Inspector-pad zou doorbreken.
    """
    slice_text = _render_loop_slice()
    guard_idx = slice_text.find('if not is_expected:')
    assert guard_idx > 0, "is_expected guard missing from render-loop"
    # Single-token markers (formatting-stable).
    for marker in ('ui.tooltip(', 'ui.context_menu()'):
        marker_idx = slice_text.find(marker)
        assert marker_idx > guard_idx, (
            f"{marker!r} appears before `if not is_expected:` — "
            f"expected pills would also get this handler")
    # Click-handler kan over meerdere regels gesplitst zijn (Black-formatting):
    #   pill_el.on(\n    'click', ...
    # Zoek `pill_el.on(` dan `'click'` daarna — niet als één string.
    on_idx = slice_text.find('pill_el.on(')
    assert on_idx > guard_idx, (
        "pill_el.on(...) appears before `if not is_expected:`")
    click_idx = slice_text.find("'click'", on_idx)
    assert click_idx > on_idx, (
        "pill_el.on(...) found but no 'click' arg after it")
