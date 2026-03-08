"""Boekhouding — Entrypoint."""

from nicegui import app, ui
from database import init_db, DB_PATH
from import_.seed_data import seed_all

# Page imports (register @ui.page routes)
import pages.dashboard
import pages.dashboard_omzet
import pages.werkdagen
import pages.facturen
import pages.kosten
import pages.bank
import pages.jaarafsluiting
import pages.aangifte
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


app.on_exception(lambda e: print(f'Unhandled exception: {e}'))

ui.run(
    title='Boekhouding',
    storage_secret='boekhouding-app-secret',
    port=8085,
    host='127.0.0.1',
    show=False,
)
