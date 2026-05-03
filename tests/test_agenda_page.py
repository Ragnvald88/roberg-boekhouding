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
