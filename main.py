"""TestBV Boekhouding — Entrypoint."""

from nicegui import app, ui
from database import init_db
from import_.seed_data import seed_all
from pathlib import Path

# Page imports (register @ui.page routes)
import pages.dashboard
import pages.werkdagen
import pages.facturen
import pages.kosten
import pages.bank
import pages.jaarafsluiting
import pages.instellingen

DB_PATH = Path("data/boekhouding.sqlite3")


@app.on_startup
async def startup():
    Path("data/facturen").mkdir(parents=True, exist_ok=True)
    Path("data/uitgaven").mkdir(parents=True, exist_ok=True)
    Path("data/bank_csv").mkdir(parents=True, exist_ok=True)
    await init_db(DB_PATH)
    await seed_all(DB_PATH)


ui.run(
    title='TestBV Boekhouding',
    storage_secret='roberg-dev-secret-change-me',
    port=8085,
    host='127.0.0.1',
    show=False,
)
