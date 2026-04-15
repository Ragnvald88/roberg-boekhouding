"""Boekhouding — Entrypoint."""

import os
# Prevent NiceGUI from transitively importing matplotlib. We render charts
# with ECharts; matplotlib and its ~50-module subtree (pyplot, mpl_toolkits,
# pillow, pyparsing, kiwisolver, dateutil) would add 100-400ms to cold start
# for nothing. NiceGUI's `nicegui/elements/pyplot.py:15` reads this env var.
os.environ.setdefault('MATPLOTLIB', 'false')

import signal
import socket
import subprocess
import sys
import webbrowser
from urllib.request import urlopen

PORT = 8085


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def _app_responding(port: int) -> bool:
    """Check if a working NiceGUI instance is actually responding."""
    try:
        urlopen(f'http://127.0.0.1:{port}', timeout=2)
        return True
    except Exception:
        return False


def _kill_stale_process(port: int) -> None:
    """Find and kill the process holding the port."""
    try:
        result = subprocess.run(
            ['lsof', '-ti', f':{port}'], capture_output=True, text=True,
        )
        for pid_str in result.stdout.strip().split('\n'):
            pid = int(pid_str)
            if pid != os.getpid():
                print(f'Stale proces (PID {pid}) op poort {port} wordt gestopt...')
                os.kill(pid, signal.SIGTERM)
        # Wait briefly for port to free up
        import time
        for _ in range(10):
            if not _port_in_use(port):
                break
            time.sleep(0.5)
    except Exception:
        pass


# Port-check BEFORE heavy imports: if the app is already running, we only
# need to open a browser tab — no need to pay the ~300ms NiceGUI import cost.
if _port_in_use(PORT):
    if _app_responding(PORT):
        print(f'Boekhouding draait al op http://127.0.0.1:{PORT} — browser wordt geopend.')
        webbrowser.open(f'http://127.0.0.1:{PORT}')
        sys.exit(0)
    else:
        print(f'Poort {PORT} is bezet door een vastgelopen proces.')
        _kill_stale_process(PORT)
        if _port_in_use(PORT):
            print(f'FOUT: Kan poort {PORT} niet vrijmaken. Stop het proces handmatig.')
            sys.exit(1)
        print(f'Poort {PORT} is weer vrij. App wordt gestart...')

# Heavy imports deferred to here so the "app already running" path above
# exits within ~50ms instead of paying the full ~300ms NiceGUI startup.
from nicegui import app, ui
from database import init_db, DB_PATH
from import_.seed_data import seed_all

# Page imports (register @ui.page routes)
import pages.dashboard
import pages.dashboard_omzet
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
    show=True,
)
