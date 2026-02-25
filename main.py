"""TestBV Boekhouding — Entrypoint."""

from nicegui import app, ui
from database import init_db
from pathlib import Path

DB_PATH = Path("data/boekhouding.sqlite3")


@app.on_startup
async def startup():
    Path("data/facturen").mkdir(parents=True, exist_ok=True)
    Path("data/uitgaven").mkdir(parents=True, exist_ok=True)
    Path("data/bank_csv").mkdir(parents=True, exist_ok=True)
    await init_db(DB_PATH)


@ui.page('/')
async def index():
    ui.label('TestBV Boekhouding').classes('text-h4')
    ui.label('Dashboard — onder constructie')


ui.run(
    title='TestBV Boekhouding',
    storage_secret='roberg-dev-secret-change-me',
    port=8085,
    host='127.0.0.1',
    show=False,
)
