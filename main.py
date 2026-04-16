"""Boekhouding — Entrypoint."""

# Enable pywebview's download handler BEFORE NiceGUI imports webview
# internally. pywebview 6.x ships with `ALLOW_DOWNLOADS=False` by default,
# which silently drops every `ui.download*` call (CSV exports, factuur-PDFs,
# backup-ZIP, etc.) — the click appears to do nothing. Flipping this one
# flag makes them save to ~/Downloads via Cocoa's NSDownloadsDirectory.
# Must be set on the module object both here (parent process) and in the
# pywebview multiprocessing-spawn child — because the child re-imports
# main.py, the assignment here covers both.
import webview  # noqa: E402
webview.settings['ALLOW_DOWNLOADS'] = True

from nicegui import app, ui  # noqa: E402
from database import init_db, DB_PATH  # noqa: E402
from import_.seed_data import seed_all  # noqa: E402

PORT = 8085

# No port-in-use guard here: native mode spawns its own pywebview subprocess
# which re-imports this module, and that child must NOT short-circuit on
# seeing the parent's bound port. The AppleScript launcher handles the
# "already running → focus existing window" path before spawning Python;
# uvicorn raises a clear OSError if a foreign process holds the port.

# Page imports (register @ui.page routes)
import pages.dashboard
import pages.werkdagen
import pages.facturen
import pages.klanten
import pages.kosten
import pages.bank
import pages.jaarafsluiting
import pages.aangifte
import pages.documenten
import pages.instellingen


@app.on_startup
async def startup():
    data_dir = DB_PATH.parent
    (data_dir / "facturen").mkdir(parents=True, exist_ok=True)
    (data_dir / "uitgaven").mkdir(parents=True, exist_ok=True)
    (data_dir / "bank_csv").mkdir(parents=True, exist_ok=True)
    (data_dir / "aangifte").mkdir(parents=True, exist_ok=True)
    await init_db(DB_PATH)
    await seed_all(DB_PATH)


def _handle_exception(e: Exception) -> None:
    """Log to console + try to notify user (may fail without client context)."""
    import traceback
    traceback.print_exc()
    try:
        ui.notify(f'Er is een fout opgetreden: {e}', type='negative', timeout=10000)
    except Exception:
        pass  # No client context available


app.on_exception(_handle_exception)

ui.run(
    title='Boekhouding',
    storage_secret='boekhouding-app-secret',
    port=PORT,
    host='127.0.0.1',
    native=True,
    window_size=(1400, 900),
    reload=False,
)
