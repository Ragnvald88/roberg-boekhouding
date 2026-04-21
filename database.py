"""SQLite database: schema, connectie, en alle queries."""

import asyncio
import json
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta

import aiosqlite
from pathlib import Path
from models import (
    Bedrijfsgegevens, Klant, KlantLocatie, Werkdag, Factuur, Uitgave,
    Banktransactie, FiscaleParams, AangifteDocument,
)


@dataclass
class MatchProposal:
    """Proposal to link a bank transaction to an invoice.

    Returned by ``find_factuur_matches`` — does NOT mutate DB state.
    Apply via ``apply_factuur_matches``.

    Attributes:
        factuur_id: The factuur being proposed for payment.
        bank_id: The banktransactie row to link.
        delta: abs(bank_bedrag - factuur_bedrag).
        confidence: 'high' (safe to auto-apply) or 'low' (ambiguous — user must confirm).
        alternatives: Other bank_ids within tolerance (populated when confidence='low').
        match_type: 'nummer' (Pass 1: number in omschrijving) or 'bedrag' (Pass 2: amount only).
        factuur_nummer, factuur_bedrag, factuur_datum: Factuur context for UI.
        bank_datum, bank_bedrag, bank_tegenpartij: Banktxn context for UI.
    """
    factuur_id: int
    bank_id: int
    delta: float
    confidence: str  # 'high' | 'low'
    match_type: str  # 'nummer' | 'bedrag'
    factuur_nummer: str = ''
    factuur_bedrag: float = 0.0
    factuur_datum: str = ''
    bank_datum: str = ''
    bank_bedrag: float = 0.0
    bank_tegenpartij: str = ''
    alternatives: list = field(default_factory=list)


@dataclass
class PdfMatch:
    path: Path
    filename: str
    categorie: str
    score: int  # higher = better; for v1: tegenpartij token count
    has_bedrag_match: bool = False  # reserved for v1.1


_DEFAULT_DB_DIR = Path.home() / "Library" / "Application Support" / "Boekhouding" / "data"
_ENV_OVERRIDE = os.environ.get("BOEKHOUDING_DB_DIR")
_DB_DIR = Path(_ENV_OVERRIDE).expanduser() if _ENV_OVERRIDE else _DEFAULT_DB_DIR
_DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = _DB_DIR / "boekhouding.sqlite3"

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS klanten (
    id INTEGER PRIMARY KEY,
    naam TEXT NOT NULL,
    tarief_uur REAL NOT NULL CHECK (tarief_uur >= 0),
    retour_km REAL DEFAULT 0 CHECK (retour_km >= 0),
    adres TEXT DEFAULT '',
    kvk TEXT DEFAULT '',
    actief INTEGER DEFAULT 1 CHECK (actief IN (0, 1))
);

CREATE TABLE IF NOT EXISTS klant_locaties (
    id INTEGER PRIMARY KEY,
    klant_id INTEGER NOT NULL REFERENCES klanten(id) ON DELETE CASCADE,
    naam TEXT NOT NULL,
    retour_km REAL DEFAULT 0 CHECK (retour_km >= 0),
    UNIQUE(klant_id, naam)
);

CREATE TABLE IF NOT EXISTS werkdagen (
    id INTEGER PRIMARY KEY,
    datum TEXT NOT NULL,
    klant_id INTEGER NOT NULL REFERENCES klanten(id),
    code TEXT DEFAULT '',
    activiteit TEXT DEFAULT 'Waarneming dagpraktijk',
    locatie TEXT DEFAULT '',
    uren REAL NOT NULL CHECK (uren >= 0),
    km REAL DEFAULT 0 CHECK (km >= 0),
    tarief REAL NOT NULL CHECK (tarief >= 0),
    km_tarief REAL DEFAULT 0.23,
    factuurnummer TEXT DEFAULT '',
    opmerking TEXT DEFAULT '',
    urennorm INTEGER DEFAULT 1 CHECK (urennorm IN (0, 1)),
    -- Migration 6 column
    locatie_id INTEGER REFERENCES klant_locaties(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_werkdagen_datum ON werkdagen(datum);
CREATE INDEX IF NOT EXISTS idx_werkdagen_klant ON werkdagen(klant_id);
CREATE INDEX IF NOT EXISTS idx_werkdagen_factuurnummer ON werkdagen(factuurnummer);

CREATE TABLE IF NOT EXISTS facturen (
    id INTEGER PRIMARY KEY,
    nummer TEXT NOT NULL UNIQUE,
    klant_id INTEGER NOT NULL REFERENCES klanten(id),
    datum TEXT NOT NULL,
    totaal_uren REAL,
    totaal_km REAL,
    totaal_bedrag REAL NOT NULL CHECK (totaal_bedrag >= 0),
    pdf_pad TEXT DEFAULT '',
    betaald INTEGER DEFAULT 0 CHECK (betaald IN (0, 1)),
    betaald_datum TEXT DEFAULT '',
    type TEXT DEFAULT 'factuur',
    bron TEXT DEFAULT 'app',
    regels_json TEXT DEFAULT '',
    betaallink TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_facturen_klant ON facturen(klant_id);
CREATE INDEX IF NOT EXISTS idx_facturen_datum ON facturen(datum);

CREATE TABLE IF NOT EXISTS uitgaven (
    id INTEGER PRIMARY KEY,
    datum TEXT NOT NULL,
    categorie TEXT NOT NULL,
    omschrijving TEXT NOT NULL,
    bedrag REAL NOT NULL CHECK (bedrag >= 0),
    pdf_pad TEXT DEFAULT '',
    is_investering INTEGER DEFAULT 0 CHECK (is_investering IN (0, 1)),
    restwaarde_pct REAL DEFAULT 10,
    levensduur_jaren INTEGER,
    aanschaf_bedrag REAL,
    zakelijk_pct REAL DEFAULT 100 CHECK (zakelijk_pct BETWEEN 0 AND 100)
);

CREATE INDEX IF NOT EXISTS idx_uitgaven_datum ON uitgaven(datum);

CREATE TABLE IF NOT EXISTS banktransacties (
    id INTEGER PRIMARY KEY,
    datum TEXT NOT NULL,
    bedrag REAL NOT NULL,
    tegenrekening TEXT DEFAULT '',
    tegenpartij TEXT DEFAULT '',
    omschrijving TEXT DEFAULT '',
    categorie TEXT DEFAULT '',
    koppeling_type TEXT DEFAULT '',
    koppeling_id INTEGER,
    csv_bestand TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_banktransacties_datum ON banktransacties(datum);

CREATE TABLE IF NOT EXISTS fiscale_params (
    jaar INTEGER PRIMARY KEY,
    zelfstandigenaftrek REAL,
    startersaftrek REAL,
    mkb_vrijstelling_pct REAL,
    kia_ondergrens REAL,
    kia_bovengrens REAL,
    kia_pct REAL,
    kia_drempel_per_item REAL DEFAULT 450,
    km_tarief REAL,
    schijf1_grens REAL,
    schijf1_pct REAL,
    schijf2_grens REAL,
    schijf2_pct REAL,
    schijf3_pct REAL,
    ahk_max REAL,
    ahk_afbouw_pct REAL,
    ahk_drempel REAL,
    ak_max REAL,
    zvw_pct REAL,
    zvw_max_grondslag REAL,
    repr_aftrek_pct REAL DEFAULT 80,
    -- Migration 1 columns
    aov_premie REAL DEFAULT 0,
    woz_waarde REAL DEFAULT 0,
    hypotheekrente REAL DEFAULT 0,
    voorlopige_aanslag_betaald REAL DEFAULT 0,
    -- Migration 2 columns
    ew_forfait_pct REAL DEFAULT 0.35,
    villataks_grens REAL DEFAULT 1350000,
    wet_hillen_pct REAL DEFAULT 0,
    urencriterium REAL DEFAULT 1225,
    partner_bruto_loon REAL DEFAULT 0,
    partner_loonheffing REAL DEFAULT 0,
    pvv_premiegrondslag REAL DEFAULT 0,
    ew_naar_partner REAL DEFAULT 1,
    voorlopige_aanslag_zvw REAL DEFAULT 0,
    -- Migration 3 columns
    pvv_aow_pct REAL DEFAULT 17.90,
    pvv_anw_pct REAL DEFAULT 0.10,
    pvv_wlz_pct REAL DEFAULT 9.65,
    box3_bank_saldo REAL DEFAULT 0,
    box3_overige_bezittingen REAL DEFAULT 0,
    box3_schulden REAL DEFAULT 0,
    box3_heffingsvrij_vermogen REAL DEFAULT 57000,
    box3_rendement_bank_pct REAL DEFAULT 1.03,
    box3_rendement_overig_pct REAL DEFAULT 6.17,
    box3_rendement_schuld_pct REAL DEFAULT 2.46,
    box3_tarief_pct REAL DEFAULT 36,
    -- Migration 4 columns
    box3_drempel_schulden REAL DEFAULT 3700,
    balans_bank_saldo REAL DEFAULT 0,
    balans_crediteuren REAL DEFAULT 0,
    balans_overige_vorderingen REAL DEFAULT 0,
    balans_overige_schulden REAL DEFAULT 0,
    za_actief REAL DEFAULT 1,
    sa_actief REAL DEFAULT 0,
    lijfrente_premie REAL DEFAULT 0,
    box3_fiscaal_partner REAL DEFAULT 1,
    -- Migration 5 columns
    arbeidskorting_brackets TEXT DEFAULT '',
    jaarafsluiting_status TEXT DEFAULT 'concept'
);

CREATE TABLE IF NOT EXISTS bedrijfsgegevens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    bedrijfsnaam TEXT NOT NULL DEFAULT '',
    naam TEXT NOT NULL DEFAULT '',
    functie TEXT NOT NULL DEFAULT '',
    adres TEXT NOT NULL DEFAULT '',
    postcode_plaats TEXT NOT NULL DEFAULT '',
    kvk TEXT NOT NULL DEFAULT '',
    iban TEXT NOT NULL DEFAULT '',
    thuisplaats TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS aangifte_documenten (
    id INTEGER PRIMARY KEY,
    jaar INTEGER NOT NULL,
    categorie TEXT NOT NULL,
    documenttype TEXT NOT NULL,
    bestandsnaam TEXT NOT NULL,
    bestandspad TEXT NOT NULL,
    upload_datum TEXT NOT NULL,
    notitie TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_aangifte_docs_jaar ON aangifte_documenten(jaar);

CREATE TABLE IF NOT EXISTS afschrijving_overrides (
    id INTEGER PRIMARY KEY,
    uitgave_id INTEGER NOT NULL REFERENCES uitgaven(id) ON DELETE CASCADE,
    jaar INTEGER NOT NULL,
    bedrag REAL NOT NULL CHECK (bedrag >= 0),
    UNIQUE(uitgave_id, jaar)
);

CREATE TABLE IF NOT EXISTS jaarafsluiting_snapshots (
    jaar INTEGER PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    balans_json TEXT NOT NULL,
    gesnapshot_op TEXT NOT NULL,
    fiscale_params_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


async def get_db(db_path: Path = DB_PATH) -> aiosqlite.Connection:
    """Get a database connection with WAL mode, FK enforcement, and performance pragmas."""
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA foreign_keys = ON")
    await conn.execute("PRAGMA synchronous = NORMAL")
    await conn.execute("PRAGMA cache_size = 10000")
    await conn.execute("PRAGMA temp_store = MEMORY")
    conn.row_factory = aiosqlite.Row
    return conn


@asynccontextmanager
async def get_db_ctx(db_path: Path = DB_PATH):
    """Async context manager for database connections."""
    conn = await get_db(db_path)
    try:
        yield conn
    finally:
        await conn.close()


async def _get_existing_columns(conn, table: str) -> set[str]:
    """Get set of column names for a table via PRAGMA."""
    cur = await conn.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return {row[1] for row in rows}


# --- Versioned migrations ---
# Each tuple: (version, description, sql_list_or_None)
# sql_list=None means a callable handles it (see MIGRATION_CALLABLES).
MIGRATIONS = [
    # Schema migrations — ADD COLUMN for fiscale_params REAL columns
    (1, "add_aov_woz_hypotheek_va_columns", [
        "ALTER TABLE fiscale_params ADD COLUMN aov_premie REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN woz_waarde REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN hypotheekrente REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN voorlopige_aanslag_betaald REAL DEFAULT 0",
    ]),
    (2, "add_ew_uren_partner_pvv_columns", [
        "ALTER TABLE fiscale_params ADD COLUMN ew_forfait_pct REAL DEFAULT 0.35",
        "ALTER TABLE fiscale_params ADD COLUMN villataks_grens REAL DEFAULT 1350000",
        "ALTER TABLE fiscale_params ADD COLUMN wet_hillen_pct REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN urencriterium REAL DEFAULT 1225",
        "ALTER TABLE fiscale_params ADD COLUMN partner_bruto_loon REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN partner_loonheffing REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN pvv_premiegrondslag REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN ew_naar_partner REAL DEFAULT 1",
        "ALTER TABLE fiscale_params ADD COLUMN voorlopige_aanslag_zvw REAL DEFAULT 0",
    ]),
    (3, "add_pvv_box3_columns", [
        "ALTER TABLE fiscale_params ADD COLUMN pvv_aow_pct REAL DEFAULT 17.90",
        "ALTER TABLE fiscale_params ADD COLUMN pvv_anw_pct REAL DEFAULT 0.10",
        "ALTER TABLE fiscale_params ADD COLUMN pvv_wlz_pct REAL DEFAULT 9.65",
        "ALTER TABLE fiscale_params ADD COLUMN box3_bank_saldo REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN box3_overige_bezittingen REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN box3_schulden REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN box3_heffingsvrij_vermogen REAL DEFAULT 57000",
        "ALTER TABLE fiscale_params ADD COLUMN box3_rendement_bank_pct REAL DEFAULT 1.03",
        "ALTER TABLE fiscale_params ADD COLUMN box3_rendement_overig_pct REAL DEFAULT 6.17",
        "ALTER TABLE fiscale_params ADD COLUMN box3_rendement_schuld_pct REAL DEFAULT 2.46",
        "ALTER TABLE fiscale_params ADD COLUMN box3_tarief_pct REAL DEFAULT 36",
    ]),
    (4, "add_balans_za_sa_lijfrente_columns", [
        "ALTER TABLE fiscale_params ADD COLUMN box3_drempel_schulden REAL DEFAULT 3700",
        "ALTER TABLE fiscale_params ADD COLUMN balans_bank_saldo REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN balans_crediteuren REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN balans_overige_vorderingen REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN balans_overige_schulden REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN za_actief REAL DEFAULT 1",
        "ALTER TABLE fiscale_params ADD COLUMN sa_actief REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN lijfrente_premie REAL DEFAULT 0",
        "ALTER TABLE fiscale_params ADD COLUMN box3_fiscaal_partner REAL DEFAULT 1",
    ]),
    (5, "add_text_columns", [
        "ALTER TABLE fiscale_params ADD COLUMN arbeidskorting_brackets TEXT DEFAULT ''",
        "ALTER TABLE fiscale_params ADD COLUMN jaarafsluiting_status TEXT DEFAULT 'concept'",
    ]),
    (6, "add_werkdagen_locatie_id", [
        "ALTER TABLE werkdagen ADD COLUMN locatie_id INTEGER REFERENCES klant_locaties(id) ON DELETE SET NULL",
    ]),
    # Data migrations — all idempotent via WHERE guards
    (7, "set_ew_uren_per_year", None),  # handled by callable
    (8, "populate_ak_brackets_and_box3", None),  # handled by callable
    (9, "fix_box3_2025_definitief", [
        """UPDATE fiscale_params SET
           box3_rendement_bank_pct = 1.37,
           box3_rendement_overig_pct = 5.88,
           box3_rendement_schuld_pct = 2.70
           WHERE jaar = 2025 AND box3_rendement_bank_pct = 1.28""",
    ]),
    (10, "set_sa_actief_first_years", [
        "UPDATE fiscale_params SET sa_actief = 1 WHERE jaar = 2023 AND sa_actief = 0",
        "UPDATE fiscale_params SET sa_actief = 1 WHERE jaar = 2024 AND sa_actief = 0",
        "UPDATE fiscale_params SET sa_actief = 1 WHERE jaar = 2025 AND sa_actief = 0",
    ]),
    (11, "fix_2026_box3_heffingsvrij", [
        """UPDATE fiscale_params
           SET box3_heffingsvrij_vermogen = 59357, box3_drempel_schulden = 3800
           WHERE jaar = 2026 AND box3_heffingsvrij_vermogen = 57684""",
    ]),
    (12, "fix_date_format", [
        """UPDATE uitgaven
           SET datum = substr(datum,7,4) || '-' || substr(datum,4,2) || '-' || substr(datum,1,2)
           WHERE datum GLOB '[0-3][0-9]-[0-1][0-9]-[0-9][0-9][0-9][0-9]'""",
        """UPDATE werkdagen
           SET datum = substr(datum,7,4) || '-' || substr(datum,4,2) || '-' || substr(datum,1,2)
           WHERE datum GLOB '[0-3][0-9]-[0-1][0-9]-[0-9][0-9][0-9][0-9]'""",
    ]),
    (13, "add_betalingskenmerk_to_banktransacties", [
        "ALTER TABLE banktransacties ADD COLUMN betalingskenmerk TEXT DEFAULT ''",
    ]),
    (14, "add_factuur_status_column", [
        "ALTER TABLE facturen ADD COLUMN status TEXT DEFAULT 'concept'",
        "UPDATE facturen SET status = CASE WHEN betaald = 1 THEN 'betaald' ELSE 'verstuurd' END",
    ]),
    (15, "add_klant_email", [
        "ALTER TABLE klanten ADD COLUMN email TEXT DEFAULT ''",
    ]),
    (16, "add_bedrijf_telefoon_email", [
        "ALTER TABLE bedrijfsgegevens ADD COLUMN telefoon TEXT DEFAULT ''",
        "ALTER TABLE bedrijfsgegevens ADD COLUMN email TEXT DEFAULT ''",
        "UPDATE bedrijfsgegevens SET telefoon = '06 0000 0000', email = 'info@testbedrijf.nl' WHERE id = 1",
    ]),
    (17, "add_klant_address_fields", [
        "ALTER TABLE klanten ADD COLUMN contactpersoon TEXT DEFAULT ''",
        "ALTER TABLE klanten ADD COLUMN postcode TEXT DEFAULT ''",
        "ALTER TABLE klanten ADD COLUMN plaats TEXT DEFAULT ''",
    ]),
    (18, "relax_werkdagen_uren_check_gte_zero", None),  # handled by callable
    (19, "add_factuur_bron_column", [
        "ALTER TABLE facturen ADD COLUMN bron TEXT DEFAULT 'app'",
        # All existing facturen were imported — only future builder-created ones are 'app'
        "UPDATE facturen SET bron = 'import'",
    ]),
    (20, "drop_werkdagen_status_column", None),  # handled by callable
    (21, "classify_vergoeding_type", None),  # handled by callable
    (22, "add_regels_json_to_facturen", [
        "ALTER TABLE facturen ADD COLUMN regels_json TEXT DEFAULT ''",
    ]),
    (23, "add_betaallink_to_facturen", [
        "ALTER TABLE facturen ADD COLUMN betaallink TEXT DEFAULT ''",
    ]),
    (24, "add_herinnering_datum_to_facturen", [
        "ALTER TABLE facturen ADD COLUMN herinnering_datum TEXT DEFAULT ''",
    ]),
    (25, "add_jaarafsluiting_snapshots_table", [
        """CREATE TABLE IF NOT EXISTS jaarafsluiting_snapshots (
            jaar INTEGER PRIMARY KEY,
            snapshot_json TEXT NOT NULL,
            balans_json TEXT NOT NULL,
            gesnapshot_op TEXT NOT NULL,
            fiscale_params_json TEXT NOT NULL
        )""",
    ]),
    (26, "add_kosten_rework_columns", [
        "ALTER TABLE uitgaven ADD COLUMN bank_tx_id INTEGER "
        "REFERENCES banktransacties(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS idx_uitgaven_bank_tx "
        "ON uitgaven(bank_tx_id)",
        "ALTER TABLE banktransacties ADD COLUMN genegeerd INTEGER "
        "NOT NULL DEFAULT 0 CHECK (genegeerd IN (0, 1))",
        "CREATE INDEX IF NOT EXISTS idx_bank_genegeerd "
        "ON banktransacties(genegeerd)",
    ]),
]


async def _run_migration_7(conn):
    """Data migration: set correct per-year EW/uren values."""
    year_data = {
        2023: {'ew_forfait_pct': 0.35, 'villataks_grens': 1200000, 'wet_hillen_pct': 83.333, 'urencriterium': 1225},
        2024: {'ew_forfait_pct': 0.35, 'villataks_grens': 1310000, 'wet_hillen_pct': 80.0, 'urencriterium': 1225},
        2025: {'ew_forfait_pct': 0.35, 'villataks_grens': 1330000, 'wet_hillen_pct': 76.667, 'urencriterium': 1225},
        2026: {'ew_forfait_pct': 0.35, 'villataks_grens': 1350000, 'wet_hillen_pct': 71.867, 'urencriterium': 1225},
    }
    for jaar, vals in year_data.items():
        await conn.execute(
            """UPDATE fiscale_params SET ew_forfait_pct = ?, villataks_grens = ?,
               wet_hillen_pct = ?, urencriterium = ?
               WHERE jaar = ? AND wet_hillen_pct = 0""",
            (vals['ew_forfait_pct'], vals['villataks_grens'],
             vals['wet_hillen_pct'], vals['urencriterium'], jaar))


async def _run_migration_8(conn):
    """Data migration: populate AK brackets and Box 3 defaults."""
    from import_.seed_data import AK_BRACKETS, BOX3_DEFAULTS
    import json as _json
    for jaar in [2023, 2024, 2025, 2026]:
        await conn.execute(
            "UPDATE fiscale_params SET arbeidskorting_brackets = ? "
            "WHERE jaar = ? AND (arbeidskorting_brackets IS NULL OR arbeidskorting_brackets = '')",
            (_json.dumps(AK_BRACKETS.get(jaar, [])), jaar))
        b3 = BOX3_DEFAULTS.get(jaar)
        if b3:
            await conn.execute(
                "UPDATE fiscale_params SET "
                "box3_heffingsvrij_vermogen = ?, box3_rendement_bank_pct = ?, "
                "box3_rendement_overig_pct = ?, box3_rendement_schuld_pct = ?, "
                "box3_tarief_pct = ? "
                "WHERE jaar = ? AND box3_rendement_bank_pct = 1.03 "
                "AND box3_heffingsvrij_vermogen = 57000",
                (b3['heffingsvrij'], b3['bank'], b3['overig'], b3['schuld'], b3['tarief'], jaar))
            if 'drempel_schulden' in b3:
                await conn.execute(
                    "UPDATE fiscale_params SET box3_drempel_schulden = ? "
                    "WHERE jaar = ? AND box3_drempel_schulden = 3700",
                    (b3['drempel_schulden'], jaar))


async def _run_migration_18(conn):
    """Recreate werkdagen table with CHECK (uren >= 0) instead of CHECK (uren > 0).

    This allows non-patient business km entries (congresses, opleiding, etc.)
    with uren=0.
    """
    # Check if status column exists (won't on fresh DBs after migration 20 schema)
    cur = await conn.execute("PRAGMA table_info(werkdagen)")
    columns = [row[1] for row in await cur.fetchall()]
    has_status = 'status' in columns

    if has_status:
        select_cols = ("id, datum, klant_id, code, activiteit, locatie, uren, km, "
                       "tarief, km_tarief, factuurnummer, opmerking, urennorm, locatie_id")
    else:
        select_cols = "*"

    await conn.execute("""
        CREATE TABLE werkdagen_new (
            id INTEGER PRIMARY KEY,
            datum TEXT NOT NULL,
            klant_id INTEGER NOT NULL REFERENCES klanten(id),
            code TEXT DEFAULT '',
            activiteit TEXT DEFAULT 'Waarneming dagpraktijk',
            locatie TEXT DEFAULT '',
            uren REAL NOT NULL CHECK (uren >= 0),
            km REAL DEFAULT 0 CHECK (km >= 0),
            tarief REAL NOT NULL CHECK (tarief >= 0),
            km_tarief REAL DEFAULT 0.23,
            factuurnummer TEXT DEFAULT '',
            opmerking TEXT DEFAULT '',
            urennorm INTEGER DEFAULT 1 CHECK (urennorm IN (0, 1)),
            locatie_id INTEGER REFERENCES klant_locaties(id) ON DELETE SET NULL
        )""")
    await conn.execute(f"INSERT INTO werkdagen_new SELECT {select_cols} FROM werkdagen")
    await conn.execute("DROP TABLE werkdagen")
    await conn.execute("ALTER TABLE werkdagen_new RENAME TO werkdagen")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_werkdagen_datum ON werkdagen(datum)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_werkdagen_klant ON werkdagen(klant_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_werkdagen_factuurnummer ON werkdagen(factuurnummer)")


async def _run_migration_20(conn):
    """Drop werkdagen.status column — status is now derived from factuurnummer + facturen.status."""
    cur = await conn.execute("PRAGMA table_info(werkdagen)")
    columns = [row[1] for row in await cur.fetchall()]
    if 'status' not in columns:
        return  # Already without status (fresh DB or migration 18 handled it)

    await conn.execute("""
        CREATE TABLE werkdagen_new (
            id INTEGER PRIMARY KEY,
            datum TEXT NOT NULL,
            klant_id INTEGER NOT NULL REFERENCES klanten(id),
            code TEXT DEFAULT '',
            activiteit TEXT DEFAULT 'Waarneming dagpraktijk',
            locatie TEXT DEFAULT '',
            uren REAL NOT NULL CHECK (uren >= 0),
            km REAL DEFAULT 0 CHECK (km >= 0),
            tarief REAL NOT NULL CHECK (tarief >= 0),
            km_tarief REAL DEFAULT 0.23,
            factuurnummer TEXT DEFAULT '',
            opmerking TEXT DEFAULT '',
            urennorm INTEGER DEFAULT 1 CHECK (urennorm IN (0, 1)),
            locatie_id INTEGER REFERENCES klant_locaties(id) ON DELETE SET NULL
        )""")
    await conn.execute(
        "INSERT INTO werkdagen_new "
        "SELECT id, datum, klant_id, code, activiteit, locatie, uren, km, "
        "       tarief, km_tarief, factuurnummer, opmerking, urennorm, locatie_id "
        "FROM werkdagen")
    await conn.execute("DROP TABLE werkdagen")
    await conn.execute("ALTER TABLE werkdagen_new RENAME TO werkdagen")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_werkdagen_datum ON werkdagen(datum)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_werkdagen_klant ON werkdagen(klant_id)")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_werkdagen_factuurnummer ON werkdagen(factuurnummer)")


async def _run_migration_21(conn):
    """Link 2025 orphan werkdagen to their facturen, then classify orphan facturen as vergoeding."""
    # Step A: Link 2025 orphan werkdagen to their correct facturen
    werkdag_links = [
        (392, '2025-002'), (397, '2025-002'), (400, '2025-002'),
        (492, '2025-025'), (493, '2025-026'), (495, '2025-027'), (496, '2025-028'),
    ]
    for wd_id, factuurnummer in werkdag_links:
        await conn.execute(
            "UPDATE werkdagen SET factuurnummer = ? WHERE id = ? AND factuurnummer = ''",
            (factuurnummer, wd_id))

    # Step B: Classify all orphan facturen (no werkdagen, not concept) as vergoeding
    await conn.execute("""
        UPDATE facturen SET type = 'vergoeding'
        WHERE type = 'factuur'
        AND NOT EXISTS (SELECT 1 FROM werkdagen w WHERE w.factuurnummer = facturen.nummer)
        AND status != 'concept'
    """)


_MIGRATION_CALLABLES = {7: _run_migration_7, 8: _run_migration_8, 18: _run_migration_18, 20: _run_migration_20, 21: _run_migration_21}


async def init_db(db_path: Path = DB_PATH) -> None:
    """Create all tables if they don't exist, then run versioned migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()

        # Determine current schema version
        cur = await conn.execute(
            "SELECT MAX(version) FROM schema_version")
        row = await cur.fetchone()
        current_version = row[0] or 0

        # First-run detection: if schema_version is empty but tables exist,
        # introspect to find which migrations are already applied
        if current_version == 0:
            fp_cols = await _get_existing_columns(conn, 'fiscale_params')
            wd_cols = await _get_existing_columns(conn, 'werkdagen')

            # Check marker columns for each schema migration group
            if ('locatie_id' in wd_cols
                    and 'jaarafsluiting_status' in fp_cols
                    and 'box3_fiscaal_partner' in fp_cols):
                current_version = 6
            elif 'jaarafsluiting_status' in fp_cols:
                current_version = 5
            elif 'box3_fiscaal_partner' in fp_cols:
                current_version = 4
            elif 'pvv_aow_pct' in fp_cols:
                current_version = 3
            elif 'ew_forfait_pct' in fp_cols:
                current_version = 2
            elif 'aov_premie' in fp_cols:
                current_version = 1

            # Record detected version
            if current_version > 0:
                from datetime import datetime as _dt
                now = _dt.now().isoformat()
                for v in range(1, current_version + 1):
                    desc = next(
                        (d for ver, d, _ in MIGRATIONS if ver == v),
                        f'migration_{v}')
                    await conn.execute(
                        "INSERT OR IGNORE INTO schema_version "
                        "(version, description, applied_at) VALUES (?, ?, ?)",
                        (v, desc, now))
                await conn.commit()

        # Apply pending migrations
        for version, description, sql_list in MIGRATIONS:
            if version <= current_version:
                continue
            try:
                if sql_list is not None:
                    for sql in sql_list:
                        try:
                            await conn.execute(sql)
                        except sqlite3.OperationalError as e:
                            if 'duplicate column' not in str(e).lower():
                                raise
                elif version in _MIGRATION_CALLABLES:
                    await _MIGRATION_CALLABLES[version](conn)

                from datetime import datetime as _dt
                await conn.execute(
                    "INSERT INTO schema_version "
                    "(version, description, applied_at) VALUES (?, ?, ?)",
                    (version, description, _dt.now().isoformat()))
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    # One-time backfill for betalingskenmerk
    await backfill_betalingskenmerken(db_path)
    # Backfill betaallinks from existing QR files on disk
    await backfill_betaallinks(db_path)


def _validate_datum(datum: str) -> str:
    """Validate datum is a valid YYYY-MM-DD date. Raises ValueError if not."""
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', datum):
        raise ValueError(
            f"Datum moet YYYY-MM-DD formaat zijn, kreeg: '{datum}'"
        )
    # Also validate it's an actual calendar date
    try:
        _date.fromisoformat(datum)
    except ValueError:
        raise ValueError(
            f"Ongeldige datum: '{datum}'"
        )
    return datum


class YearLockedError(ValueError):
    """Raised when attempting to mutate data in a definitief (locked) jaar.

    Subclasses ValueError so existing `except ValueError:` sites that catch
    invalid-input errors also catch this; callers that specifically want to
    handle the year-lock case can catch YearLockedError directly.

    Unfreeze path: call `update_jaarafsluiting_status(db, jaar, 'concept')`.
    """


async def assert_year_writable(db_path, jaar_or_datum) -> None:
    """Raise YearLockedError if the year is marked 'definitief'.

    Accepts either an int year (2025) or an ISO datum string ('2025-06-01').
    A year with no fiscale_params row yet is considered writable (no lock
    has been set).
    """
    if isinstance(jaar_or_datum, int):
        jaar = jaar_or_datum
    else:
        jaar = int(str(jaar_or_datum)[:4])
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT jaarafsluiting_status FROM fiscale_params WHERE jaar = ?",
            (jaar,),
        )
        row = await cur.fetchone()
    if row and (row[0] or 'concept') == 'definitief':
        raise YearLockedError(
            f"Jaar {jaar} is definitief afgesloten en mag niet gewijzigd "
            f"worden. Heropen eerst via Jaarafsluiting → Heropenen."
        )


# === Bedrijfsgegevens ===

async def get_bedrijfsgegevens(db_path: Path = DB_PATH) -> Bedrijfsgegevens | None:
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute("SELECT * FROM bedrijfsgegevens WHERE id = 1")
        r = await cursor.fetchone()
        if not r:
            return None
        return Bedrijfsgegevens(
            id=1, bedrijfsnaam=r['bedrijfsnaam'], naam=r['naam'],
            functie=r['functie'], adres=r['adres'],
            postcode_plaats=r['postcode_plaats'], kvk=r['kvk'],
            iban=r['iban'], thuisplaats=r['thuisplaats'],
            telefoon=r['telefoon'] if 'telefoon' in r.keys() else '',
            email=r['email'] if 'email' in r.keys() else '',
        )


async def upsert_bedrijfsgegevens(db_path: Path = DB_PATH, **kwargs) -> None:
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            """INSERT OR REPLACE INTO bedrijfsgegevens
               (id, bedrijfsnaam, naam, functie, adres, postcode_plaats,
                kvk, iban, thuisplaats, telefoon, email)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kwargs.get('bedrijfsnaam', ''), kwargs.get('naam', ''),
             kwargs.get('functie', ''), kwargs.get('adres', ''),
             kwargs.get('postcode_plaats', ''), kwargs.get('kvk', ''),
             kwargs.get('iban', ''), kwargs.get('thuisplaats', ''),
             kwargs.get('telefoon', ''), kwargs.get('email', ''))
        )
        await conn.commit()


# === Klanten ===

async def get_klanten(db_path: Path = DB_PATH, alleen_actief: bool = False) -> list[Klant]:
    async with get_db_ctx(db_path) as conn:
        sql = "SELECT * FROM klanten"
        if alleen_actief:
            sql += " WHERE actief = 1"
        sql += " ORDER BY naam"
        cursor = await conn.execute(sql)
        rows = await cursor.fetchall()
        return [Klant(
            id=r['id'], naam=r['naam'], tarief_uur=r['tarief_uur'],
            retour_km=r['retour_km'], adres=r['adres'] or '',
            kvk=r['kvk'] or '', actief=bool(r['actief']),
            email=r['email'] or '',
            contactpersoon=r['contactpersoon'] or '',
            postcode=r['postcode'] or '',
            plaats=r['plaats'] or '',
        ) for r in rows]


async def add_klant(db_path: Path = DB_PATH, **kwargs) -> int:
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "INSERT INTO klanten (naam, tarief_uur, retour_km, adres, kvk, actief, "
            "email, contactpersoon, postcode, plaats) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kwargs['naam'], kwargs.get('tarief_uur', 0), kwargs.get('retour_km', 0),
             kwargs.get('adres', ''), kwargs.get('kvk', ''), kwargs.get('actief', 1),
             kwargs.get('email', ''), kwargs.get('contactpersoon', ''),
             kwargs.get('postcode', ''), kwargs.get('plaats', ''))
        )
        await conn.commit()
        return cursor.lastrowid


async def update_klant(db_path: Path = DB_PATH, klant_id: int = 0, **kwargs) -> None:
    async with get_db_ctx(db_path) as conn:
        fields = []
        values = []
        for key in ('naam', 'tarief_uur', 'retour_km', 'adres', 'kvk', 'actief',
                    'email', 'contactpersoon', 'postcode', 'plaats'):
            if key in kwargs:
                fields.append(f"{key} = ?")
                values.append(kwargs[key])
        if fields:
            values.append(klant_id)
            await conn.execute(
                f"UPDATE klanten SET {', '.join(fields)} WHERE id = ?", values
            )
            await conn.commit()


async def delete_klant(db_path: Path = DB_PATH, klant_id: int = 0) -> None:
    async with get_db_ctx(db_path) as conn:
        try:
            await conn.execute("DELETE FROM klanten WHERE id = ?", (klant_id,))
            await conn.commit()
        except Exception as exc:
            if 'FOREIGN KEY' in str(exc):
                raise ValueError(
                    'Kan klant niet verwijderen: er zijn werkdagen of facturen '
                    'gekoppeld aan deze klant.'
                ) from exc
            raise


# === Row-to-model helpers (DRY) ===

def _row_to_werkdag(r) -> Werkdag:
    """Convert a joined werkdagen+klanten(+facturen) row to a Werkdag dataclass."""
    fn = r['factuurnummer'] or ''
    # Derive status: if computed_status column is present (from JOIN), use it;
    # otherwise derive from factuurnummer presence.
    if 'computed_status' in r.keys():
        status = r['computed_status']
    elif fn:
        status = 'gefactureerd'
    else:
        status = 'ongefactureerd'
    return Werkdag(
        id=r['id'], datum=r['datum'], klant_id=r['klant_id'],
        klant_naam=r['klant_naam'], code=r['code'] or '',
        activiteit=r['activiteit'] or 'Waarneming dagpraktijk',
        locatie=r['locatie'] or '', uren=r['uren'], km=r['km'] or 0,
        tarief=r['tarief'], km_tarief=r['km_tarief'] if r['km_tarief'] is not None else 0.23,
        factuurnummer=fn,
        status=status,
        opmerking=r['opmerking'] or '',
        urennorm=bool(r['urennorm']),
        locatie_id=r['locatie_id'],
    )


def _row_to_factuur(r) -> Factuur:
    """Convert a joined facturen+klanten row to a Factuur dataclass."""
    return Factuur(
        id=r['id'], nummer=r['nummer'], klant_id=r['klant_id'],
        klant_naam=r['klant_naam'], datum=r['datum'],
        totaal_uren=r['totaal_uren'] or 0,
        totaal_km=r['totaal_km'] or 0,
        totaal_bedrag=r['totaal_bedrag'],
        pdf_pad=r['pdf_pad'] or '', status=r['status'] or 'concept',
        betaald_datum=r['betaald_datum'] or '',
        type=r['type'] or 'factuur',
        bron=r['bron'] if 'bron' in r.keys() else 'app',
        betaallink=r['betaallink'] if 'betaallink' in r.keys() else '',
        herinnering_datum=r['herinnering_datum'] if 'herinnering_datum' in r.keys() else '',
        regels_json=r['regels_json'] if 'regels_json' in r.keys() else '',
    )


def _row_to_uitgave(r) -> Uitgave:
    """Convert an uitgaven row to an Uitgave dataclass."""
    return Uitgave(
        id=r['id'], datum=r['datum'], categorie=r['categorie'],
        omschrijving=r['omschrijving'], bedrag=r['bedrag'],
        pdf_pad=r['pdf_pad'] or '', is_investering=bool(r['is_investering']),
        restwaarde_pct=r['restwaarde_pct'] if r['restwaarde_pct'] is not None else 10,
        levensduur_jaren=r['levensduur_jaren'],
        aanschaf_bedrag=r['aanschaf_bedrag'],
        zakelijk_pct=r['zakelijk_pct'] if r['zakelijk_pct'] is not None else 100,
    )


# === Werkdagen ===

async def get_werkdagen(db_path: Path = DB_PATH, jaar: int = None,
                        maand: int = None, klant_id: int = None) -> list[Werkdag]:
    async with get_db_ctx(db_path) as conn:
        sql = """SELECT w.*, k.naam as klant_naam,
                        CASE
                            WHEN w.factuurnummer = '' OR w.factuurnummer IS NULL THEN 'ongefactureerd'
                            WHEN f.status = 'betaald' THEN 'betaald'
                            ELSE 'gefactureerd'
                        END as computed_status
                 FROM werkdagen w
                 JOIN klanten k ON w.klant_id = k.id
                 LEFT JOIN facturen f ON w.factuurnummer = f.nummer
                 WHERE 1=1"""
        params = []
        if jaar:
            sql += " AND w.datum >= ? AND w.datum < ?"
            params.extend([f'{jaar}-01-01', f'{jaar+1}-01-01'])
        if maand:
            sql += " AND substr(w.datum, 6, 2) = ?"
            params.append(f"{maand:02d}")
        if klant_id:
            sql += " AND w.klant_id = ?"
            params.append(klant_id)
        sql += " ORDER BY w.datum DESC"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_werkdag(r) for r in rows]


async def add_werkdag(db_path: Path = DB_PATH, **kwargs) -> int:
    _validate_datum(kwargs['datum'])
    await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """INSERT INTO werkdagen
               (datum, klant_id, code, activiteit, locatie, uren, km,
                tarief, km_tarief, factuurnummer, opmerking, urennorm,
                locatie_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kwargs['datum'], kwargs['klant_id'],
             kwargs.get('code', ''), kwargs.get('activiteit', 'Waarneming dagpraktijk'),
             kwargs.get('locatie', ''), kwargs['uren'], kwargs.get('km', 0),
             kwargs['tarief'], kwargs.get('km_tarief', 0.23),
             kwargs.get('factuurnummer', ''),
             kwargs.get('opmerking', ''), kwargs.get('urennorm', 1),
             kwargs.get('locatie_id'))
        )
        await conn.commit()
        return cursor.lastrowid


async def update_werkdag(db_path: Path = DB_PATH, werkdag_id: int = 0, **kwargs) -> None:
    if 'datum' in kwargs:
        _validate_datum(kwargs['datum'])
    # Fetch current datum to enforce year-lock on the existing row
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum FROM werkdagen WHERE id = ?", (werkdag_id,)
        )
        row = await cur.fetchone()
    if row:
        await assert_year_writable(db_path, row[0])
    if 'datum' in kwargs:
        await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        fields = []
        values = []
        allowed = ('datum', 'klant_id', 'code', 'activiteit', 'locatie', 'uren',
                    'km', 'tarief', 'km_tarief', 'factuurnummer',
                    'opmerking', 'urennorm', 'locatie_id')
        for key in allowed:
            if key in kwargs:
                fields.append(f"{key} = ?")
                values.append(kwargs[key])
        if fields:
            values.append(werkdag_id)
            await conn.execute(
                f"UPDATE werkdagen SET {', '.join(fields)} WHERE id = ?", values
            )
            await conn.commit()


async def delete_werkdag(db_path: Path = DB_PATH, werkdag_id: int = 0) -> None:
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "SELECT factuurnummer, datum FROM werkdagen WHERE id = ?", (werkdag_id,)
        )
        row = await cursor.fetchone()
    if row and row[0]:
        raise ValueError(
            f"Werkdag kan niet verwijderd worden: gekoppeld aan factuur '{row[0]}'"
        )
    if row:
        await assert_year_writable(db_path, row[1])
    async with get_db_ctx(db_path) as conn:
        await conn.execute("DELETE FROM werkdagen WHERE id = ?", (werkdag_id,))
        await conn.commit()


async def get_werkdagen_ongefactureerd(db_path: Path = DB_PATH,
                                        klant_id: int = None) -> list[Werkdag]:
    async with get_db_ctx(db_path) as conn:
        sql = """SELECT w.*, k.naam as klant_naam
                 FROM werkdagen w JOIN klanten k ON w.klant_id = k.id
                 WHERE (w.factuurnummer = '' OR w.factuurnummer IS NULL)"""
        params = []
        if klant_id:
            sql += " AND w.klant_id = ?"
            params.append(klant_id)
        sql += " ORDER BY w.datum"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_werkdag(r) for r in rows]


# === Facturen ===

async def get_facturen(db_path: Path = DB_PATH, jaar: int = None) -> list[Factuur]:
    async with get_db_ctx(db_path) as conn:
        sql = """SELECT f.*, k.naam as klant_naam
                 FROM facturen f JOIN klanten k ON f.klant_id = k.id
                 WHERE 1=1"""
        params = []
        if jaar:
            sql += " AND f.datum >= ? AND f.datum < ?"
            params.extend([f'{jaar}-01-01', f'{jaar+1}-01-01'])
        sql += " ORDER BY f.nummer DESC"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_factuur(r) for r in rows]


async def add_factuur(db_path: Path = DB_PATH, **kwargs) -> int:
    _validate_datum(kwargs['datum'])
    await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """INSERT INTO facturen
               (nummer, klant_id, datum, totaal_uren, totaal_km,
                totaal_bedrag, pdf_pad, status, betaald_datum, type, bron,
                regels_json, betaallink)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kwargs['nummer'], kwargs['klant_id'], kwargs['datum'],
             kwargs.get('totaal_uren', 0), kwargs.get('totaal_km', 0),
             kwargs['totaal_bedrag'], kwargs.get('pdf_pad', ''),
             kwargs.get('status', 'concept'), kwargs.get('betaald_datum', ''),
             kwargs.get('type', 'factuur'), kwargs.get('bron', 'app'),
             kwargs.get('regels_json', ''), kwargs.get('betaallink', ''))
        )
        await conn.commit()
        return cursor.lastrowid


async def get_next_factuurnummer(db_path: Path = DB_PATH, jaar: int = 2026) -> str:
    """Get next sequential invoice number: YYYY-NNN format, no gaps."""
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "SELECT MAX(CAST(substr(nummer, 6) AS INTEGER)) FROM facturen WHERE nummer LIKE ?",
            (f"{jaar}-%",)
        )
        row = await cursor.fetchone()
        next_num = (row[0] or 0) + 1
        return f"{jaar}-{next_num:03d}"


async def factuurnummer_exists(db_path: Path = DB_PATH,
                               nummer: str = '') -> bool:
    """Check if a factuurnummer already exists."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM facturen WHERE nummer = ?", (nummer,))
        return await cur.fetchone() is not None


async def update_factuur_status(db_path: Path = DB_PATH, factuur_id: int = 0,
                                 status: str = 'verstuurd',
                                 betaald_datum: str = '') -> None:
    """Update factuur status.

    Status: 'concept', 'verstuurd', 'betaald'
    """
    VALID_TRANSITIONS = {
        'concept': {'verstuurd', 'betaald'},
        'verstuurd': {'betaald', 'concept'},
        'betaald': {'verstuurd'},
    }
    if betaald_datum:
        _validate_datum(betaald_datum)
    # Fetch current row (status + datum) and validate transition before guarding year-lock.
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT status, datum FROM facturen WHERE id = ?", (factuur_id,))
        current_row = await cur.fetchone()
    if current_row:
        current = current_row['status']
        if status != current and status not in VALID_TRANSITIONS.get(current, set()):
            raise ValueError(
                f"Status overgang '{current}' → '{status}' niet toegestaan")
        await assert_year_writable(db_path, current_row['datum'])
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "UPDATE facturen SET status = ?, betaald_datum = ? WHERE id = ?",
            (status, betaald_datum, factuur_id))
        await conn.commit()


async def mark_betaald(db_path: Path = DB_PATH, factuur_id: int = 0,
                       datum: str = '', betaald: bool = True) -> None:
    """Backward-compatible wrapper around update_factuur_status."""
    status = 'betaald' if betaald else 'verstuurd'
    await update_factuur_status(db_path, factuur_id, status, betaald_datum=datum)


async def update_factuur(db_path: Path = DB_PATH, factuur_id: int = 0,
                         **kwargs) -> None:
    """Update factuur fields (datum, klant_id, totaal_bedrag, type, pdf_pad)."""
    if 'datum' in kwargs:
        _validate_datum(kwargs['datum'])
    # Fetch current datum to enforce year-lock on the existing row
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum FROM facturen WHERE id = ?", (factuur_id,))
        row = await cur.fetchone()
    if row:
        await assert_year_writable(db_path, row[0])
    if 'datum' in kwargs:
        await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        fields = []
        values = []
        allowed = ('datum', 'klant_id', 'totaal_uren', 'totaal_km',
                    'totaal_bedrag', 'pdf_pad', 'type', 'regels_json')
        for key in allowed:
            if key in kwargs:
                fields.append(f'{key} = ?')
                values.append(kwargs[key])
        if not fields:
            return
        values.append(factuur_id)
        await conn.execute(
            f"UPDATE facturen SET {', '.join(fields)} WHERE id = ?",
            values
        )
        await conn.commit()


async def delete_factuur(db_path: Path = DB_PATH, factuur_id: int = 0) -> None:
    """Delete a factuur: unlink werkdagen, remove PDF, delete record.

    Only concept facturen can be deleted. Raises ValueError for
    verstuurd or betaald facturen to prevent data loss.
    """
    async with get_db_ctx(db_path) as conn:
        # Get factuur nummer, pdf_pad, status, and datum
        cursor = await conn.execute(
            "SELECT nummer, pdf_pad, status, datum FROM facturen WHERE id = ?",
            (factuur_id,)
        )
        row = await cursor.fetchone()
    if not row:
        return
    nummer = row['nummer']
    pdf_pad = row['pdf_pad']
    status = row['status']
    datum = row['datum']

    # Concept-only guard runs BEFORE year-lock so users get the more
    # specific error message when they try to delete a sent/paid invoice.
    if status in ('verstuurd', 'betaald'):
        raise ValueError(
            f"Factuur {nummer} heeft status '{status}' en kan niet "
            f"verwijderd worden. Alleen concept-facturen mogen verwijderd "
            f"worden."
        )

    await assert_year_writable(db_path, datum)

    async with get_db_ctx(db_path) as conn:
        # Unlink werkdagen
        await conn.execute(
            "UPDATE werkdagen SET factuurnummer = '' "
            "WHERE factuurnummer = ?", (nummer,)
        )

        # Delete factuur record
        await conn.execute("DELETE FROM facturen WHERE id = ?", (factuur_id,))
        await conn.commit()

    # Remove PDF file if it exists
    if pdf_pad:
        pdf_file = Path(pdf_pad)
        if pdf_file.exists():
            await asyncio.to_thread(pdf_file.unlink)


async def link_werkdagen_to_factuur(db_path: Path = DB_PATH,
                                     werkdag_ids: list[int] = None,
                                     factuurnummer: str = '') -> None:
    async with get_db_ctx(db_path) as conn:
        if werkdag_ids:
            placeholders = ','.join('?' for _ in werkdag_ids)
            await conn.execute(
                f"UPDATE werkdagen SET factuurnummer = ? "
                f"WHERE id IN ({placeholders}) "
                f"AND (factuurnummer = '' OR factuurnummer IS NULL)",
                [factuurnummer] + werkdag_ids
            )
            await conn.commit()


async def save_factuur_atomic(
    db_path: Path = DB_PATH,
    replacing_factuur_id: int = None,
    werkdag_ids: list[int] = None,
    **factuur_kwargs,
) -> int:
    """Atomically save a factuur: optionally delete old concept, insert new, link werkdagen.

    All operations happen in a single connection + single commit.
    If any step fails, the entire operation is rolled back.

    Returns the new factuur row ID.
    """
    _validate_datum(factuur_kwargs['datum'])
    # Year-lock guards run BEFORE the atomic connection opens so we never
    # nest get_db_ctx calls. If replacing, we also check the old row's
    # datum in a short read-only connection.
    await assert_year_writable(db_path, factuur_kwargs['datum'])
    if replacing_factuur_id:
        async with get_db_ctx(db_path) as conn:
            cur = await conn.execute(
                "SELECT datum FROM facturen WHERE id = ?",
                (replacing_factuur_id,))
            old_row = await cur.fetchone()
        if old_row:
            await assert_year_writable(db_path, old_row['datum'])
    async with get_db_ctx(db_path) as conn:
        try:
            # Step 1: Delete old concept (if replacing)
            if replacing_factuur_id:
                cur = await conn.execute(
                    "SELECT nummer, pdf_pad, status FROM facturen WHERE id = ?",
                    (replacing_factuur_id,))
                old = await cur.fetchone()
                if old and old['status'] in ('verstuurd', 'betaald'):
                    raise ValueError(
                        f"Factuur {old['nummer']} kan niet vervangen worden "
                        f"(status: {old['status']})")
                if old:
                    await conn.execute(
                        "UPDATE werkdagen SET factuurnummer = '' "
                        "WHERE factuurnummer = ?", (old['nummer'],))
                    await conn.execute(
                        "DELETE FROM facturen WHERE id = ?",
                        (replacing_factuur_id,))

            # Step 2: Insert new factuur
            cursor = await conn.execute(
                """INSERT INTO facturen
                   (nummer, klant_id, datum, totaal_uren, totaal_km,
                    totaal_bedrag, pdf_pad, status, betaald_datum, type, bron,
                    regels_json, betaallink)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (factuur_kwargs['nummer'], factuur_kwargs['klant_id'],
                 factuur_kwargs['datum'],
                 factuur_kwargs.get('totaal_uren', 0),
                 factuur_kwargs.get('totaal_km', 0),
                 factuur_kwargs['totaal_bedrag'],
                 factuur_kwargs.get('pdf_pad', ''),
                 factuur_kwargs.get('status', 'concept'),
                 factuur_kwargs.get('betaald_datum', ''),
                 factuur_kwargs.get('type', 'factuur'),
                 factuur_kwargs.get('bron', 'app'),
                 factuur_kwargs.get('regels_json', ''),
                 factuur_kwargs.get('betaallink', '')))

            # Step 3: Link werkdagen
            if werkdag_ids:
                placeholders = ','.join('?' for _ in werkdag_ids)
                await conn.execute(
                    f"UPDATE werkdagen SET factuurnummer = ? "
                    f"WHERE id IN ({placeholders}) "
                    f"AND (factuurnummer = '' OR factuurnummer IS NULL)",
                    [factuur_kwargs['nummer']] + werkdag_ids)

            await conn.commit()

            # Step 4: Clean up old PDF (outside transaction — non-critical)
            if replacing_factuur_id and old and old['pdf_pad']:
                pdf_file = Path(old['pdf_pad'])
                if pdf_file.exists():
                    await asyncio.to_thread(pdf_file.unlink)

            return cursor.lastrowid
        except Exception:
            await conn.rollback()
            raise


# === Uitgaven ===

async def get_uitgaven(db_path: Path = DB_PATH, jaar: int = None,
                       categorie: str = None) -> list[Uitgave]:
    async with get_db_ctx(db_path) as conn:
        sql = "SELECT * FROM uitgaven WHERE 1=1"
        params = []
        if jaar:
            sql += " AND datum >= ? AND datum < ?"
            params.extend([f'{jaar}-01-01', f'{jaar+1}-01-01'])
        if categorie:
            sql += " AND categorie = ?"
            params.append(categorie)
        sql += " ORDER BY datum DESC"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_uitgave(r) for r in rows]


async def add_uitgave(db_path: Path = DB_PATH, **kwargs) -> int:
    _validate_datum(kwargs['datum'])
    await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """INSERT INTO uitgaven
               (datum, categorie, omschrijving, bedrag, pdf_pad,
                is_investering, restwaarde_pct, levensduur_jaren,
                aanschaf_bedrag, zakelijk_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kwargs['datum'], kwargs['categorie'], kwargs['omschrijving'],
             kwargs['bedrag'], kwargs.get('pdf_pad', ''),
             kwargs.get('is_investering', 0), kwargs.get('restwaarde_pct', 10),
             kwargs.get('levensduur_jaren'), kwargs.get('aanschaf_bedrag'),
             kwargs.get('zakelijk_pct', 100))
        )
        await conn.commit()
        return cursor.lastrowid


async def ensure_uitgave_for_banktx(
    db_path: Path,
    bank_tx_id: int,
    **overrides,
) -> int:
    """Return the uitgave.id linked to this bank_tx; create if absent.

    Idempotent. Enforces uitgave.bedrag = ABS(bank_tx.bedrag) at creation.
    Year-locked against bank_tx.datum.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum, bedrag, tegenpartij, omschrijving "
            "FROM banktransacties WHERE id = ?", (bank_tx_id,))
        bt = await cur.fetchone()
        if bt is None:
            raise ValueError(f"banktransactie {bank_tx_id} not found")

        # Already linked?
        cur = await conn.execute(
            "SELECT id FROM uitgaven WHERE bank_tx_id = ?", (bank_tx_id,))
        existing = await cur.fetchone()
        if existing is not None:
            return existing[0]

    # Not linked — create. Year-lock against the bank tx datum.
    await assert_year_writable(db_path, bt["datum"])

    kwargs = {
        "datum": bt["datum"],
        "bedrag": abs(bt["bedrag"]),
        "omschrijving": (bt["tegenpartij"] or "").strip()
                        or (bt["omschrijving"] or "").strip() or "(bank tx)",
        "categorie": "",
    }
    kwargs.update(overrides)

    # Use add_uitgave so existing validation/year-lock stays DRY.
    # add_uitgave does its own year-lock check, which is redundant but safe.
    uitgave_id = await add_uitgave(db_path, **kwargs)

    # Link it.
    async with get_db_ctx(db_path) as conn:
        # Crash between add_uitgave commit and this linking UPDATE would leave
        # an orphan uitgave; acceptable given the single-user local SQLite model.
        await conn.execute(
            "UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
            (bank_tx_id, uitgave_id))
        await conn.commit()

    return uitgave_id


async def update_uitgave(db_path: Path = DB_PATH, uitgave_id: int = 0, **kwargs) -> None:
    if 'datum' in kwargs:
        _validate_datum(kwargs['datum'])
    # Fetch current datum to enforce year-lock on the existing row
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum FROM uitgaven WHERE id = ?", (uitgave_id,)
        )
        row = await cur.fetchone()
    if row:
        await assert_year_writable(db_path, row[0])
    if 'datum' in kwargs:
        await assert_year_writable(db_path, kwargs['datum'])
    async with get_db_ctx(db_path) as conn:
        fields = []
        values = []
        allowed = ('datum', 'categorie', 'omschrijving', 'bedrag', 'pdf_pad',
                    'is_investering', 'restwaarde_pct', 'levensduur_jaren',
                    'aanschaf_bedrag', 'zakelijk_pct')
        for key in allowed:
            if key in kwargs:
                fields.append(f"{key} = ?")
                values.append(kwargs[key])
        if fields:
            values.append(uitgave_id)
            await conn.execute(
                f"UPDATE uitgaven SET {', '.join(fields)} WHERE id = ?", values
            )
            await conn.commit()


async def delete_uitgave(db_path: Path = DB_PATH, uitgave_id: int = 0) -> None:
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "SELECT pdf_pad, datum FROM uitgaven WHERE id = ?", (uitgave_id,))
        row = await cursor.fetchone()
    if row:
        await assert_year_writable(db_path, row['datum'])
    async with get_db_ctx(db_path) as conn:
        await conn.execute("DELETE FROM uitgaven WHERE id = ?", (uitgave_id,))
        await conn.commit()
    if row and row['pdf_pad']:
        pdf_file = Path(row['pdf_pad'])
        if pdf_file.exists():
            await asyncio.to_thread(pdf_file.unlink)


async def get_uitgaven_per_categorie(db_path: Path = DB_PATH,
                                      jaar: int = None) -> list[dict]:
    async with get_db_ctx(db_path) as conn:
        sql = "SELECT categorie, SUM(bedrag) as totaal FROM uitgaven WHERE is_investering = 0"
        params = []
        if jaar:
            sql += " AND datum >= ? AND datum < ?"
            params.extend([f'{jaar}-01-01', f'{jaar+1}-01-01'])
        sql += " GROUP BY categorie ORDER BY totaal DESC"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [{'categorie': r['categorie'], 'totaal': r['totaal']} for r in rows]


async def get_investeringen(db_path: Path = DB_PATH, jaar: int = None) -> list[Uitgave]:
    async with get_db_ctx(db_path) as conn:
        sql = "SELECT * FROM uitgaven WHERE is_investering = 1"
        params = []
        if jaar:
            sql += " AND datum >= ? AND datum < ?"
            params.extend([f'{jaar}-01-01', f'{jaar+1}-01-01'])
        sql += " ORDER BY datum"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_uitgave(r) for r in rows]


# === Banktransacties ===

async def get_banktransacties(db_path: Path = DB_PATH,
                               jaar: int = None) -> list[Banktransactie]:
    async with get_db_ctx(db_path) as conn:
        sql = "SELECT * FROM banktransacties WHERE 1=1"
        params = []
        if jaar:
            sql += " AND datum >= ? AND datum < ?"
            params.extend([f'{jaar}-01-01', f'{jaar+1}-01-01'])
        sql += " ORDER BY datum DESC"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [Banktransactie(
            id=r['id'], datum=r['datum'], bedrag=r['bedrag'],
            tegenrekening=r['tegenrekening'] or '',
            tegenpartij=r['tegenpartij'] or '',
            omschrijving=r['omschrijving'] or '',
            categorie=r['categorie'] or '',
            koppeling_type=r['koppeling_type'] or '',
            koppeling_id=r['koppeling_id'],
            csv_bestand=r['csv_bestand'] or '',
            betalingskenmerk=r['betalingskenmerk'] or '',
        ) for r in rows]


async def get_imported_csv_bestanden(db_path: Path = DB_PATH) -> set[str]:
    """Return set of CSV filenames already imported."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT DISTINCT csv_bestand FROM banktransacties "
            "WHERE csv_bestand != ''")
        return {r['csv_bestand'] for r in await cur.fetchall()}


async def add_banktransacties(db_path: Path = DB_PATH,
                               transacties: list[dict] = None,
                               csv_bestand: str = '') -> int:
    """Insert batch of bank transactions with count-based dedup.

    If the CSV has N rows with key (datum, bedrag, tegenpartij, omschrijving)
    and the DB already has M, inserts max(0, N-M) more. This correctly handles
    genuine repeated transactions (e.g. two identical salary transfers on the
    same date) while still preventing re-import of the same CSV.
    """
    from collections import Counter
    items = transacties or []
    if not items:
        return 0

    # Year-lock guard: reject batch if ANY row falls in a definitief jaar.
    for t in items:
        await assert_year_writable(db_path, t['datum'])

    # Count how many times each key appears in this batch
    def make_key(t):
        return (t['datum'], t['bedrag'], t.get('tegenpartij', ''),
                t.get('omschrijving', ''))

    batch_counts = Counter(make_key(t) for t in items)

    async with get_db_ctx(db_path) as conn:
        count = 0
        # For each unique key, check how many already in DB
        for key, needed in batch_counts.items():
            cur = await conn.execute(
                """SELECT COUNT(*) FROM banktransacties
                   WHERE datum = ? AND bedrag = ? AND tegenpartij = ? AND omschrijving = ?""",
                key
            )
            existing = (await cur.fetchone())[0]
            to_insert = max(0, needed - existing)

            # Find the transactions with this key (in batch order)
            matching = [t for t in items if make_key(t) == key]
            for t in matching[:to_insert]:
                await conn.execute(
                    """INSERT INTO banktransacties
                       (datum, bedrag, tegenrekening, tegenpartij, omschrijving,
                        betalingskenmerk, csv_bestand)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (t['datum'], t['bedrag'], t.get('tegenrekening', ''),
                     t.get('tegenpartij', ''), t.get('omschrijving', ''),
                     t.get('betalingskenmerk', ''), csv_bestand)
                )
                count += 1
        await conn.commit()
        return count


async def update_banktransactie(db_path: Path = DB_PATH, transactie_id: int = 0,
                                 **kwargs) -> None:
    # Read current datum to guard against year-lock.
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum FROM banktransacties WHERE id = ?", (transactie_id,))
        row = await cur.fetchone()
    if row is None:
        return
    await assert_year_writable(db_path, row['datum'])

    async with get_db_ctx(db_path) as conn:
        fields = []
        values = []
        for key in ('categorie', 'koppeling_type', 'koppeling_id'):
            if key in kwargs:
                fields.append(f"{key} = ?")
                values.append(kwargs[key])
        if fields:
            values.append(transactie_id)
            await conn.execute(
                f"UPDATE banktransacties SET {', '.join(fields)} WHERE id = ?", values
            )
            await conn.commit()


async def mark_banktx_genegeerd(
    db_path: Path,
    bank_tx_id: int,
    genegeerd: int = 1,
) -> None:
    """Set banktransacties.genegeerd flag. Year-locked against the tx datum."""
    if genegeerd not in (0, 1):
        raise ValueError("genegeerd must be 0 or 1")
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum FROM banktransacties WHERE id = ?", (bank_tx_id,))
        row = await cur.fetchone()
        if row is None:
            raise ValueError(f"banktransactie {bank_tx_id} not found")
        datum = row['datum']

    await assert_year_writable(db_path, datum)

    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "UPDATE banktransacties SET genegeerd = ? WHERE id = ?",
            (genegeerd, bank_tx_id))
        await conn.commit()


async def get_categorie_suggestions(db_path: Path = DB_PATH) -> dict[str, str]:
    """Build a lookup of tegenpartij → most-used category.

    Groups by lowercased tegenpartij, picks the category with the highest
    count. Only considers transactions that have a non-empty category.
    Returns dict mapping lowercase tegenpartij → category string.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT LOWER(tegenpartij) as tp, categorie, COUNT(*) as cnt, MAX(datum) as recent
               FROM banktransacties
               WHERE categorie IS NOT NULL AND categorie != ''
                 AND tegenpartij IS NOT NULL AND tegenpartij != ''
               GROUP BY LOWER(tegenpartij), categorie
               ORDER BY LOWER(tegenpartij), cnt DESC, recent DESC""")
        rows = await cur.fetchall()

    # For each tegenpartij, take the first row (highest count due to ORDER BY)
    suggestions = {}
    for r in rows:
        tp = r['tp']
        if tp not in suggestions:
            suggestions[tp] = r['categorie']
    return suggestions


async def delete_banktransacties(db_path: Path = DB_PATH,
                                  transactie_ids: list[int] = None) -> tuple[int, list[int]]:
    """Delete bank transactions by IDs.

    Linked facturen (koppeling_type='factuur') are automatically reverted
    from betaald to verstuurd in the same transaction.

    Returns (deleted_count, reverted_factuur_ids).
    """
    if not transactie_ids:
        return 0, []
    placeholders = ','.join('?' for _ in transactie_ids)

    # Year-lock guard: check every affected row's datum.
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            f"SELECT DISTINCT datum FROM banktransacties "
            f"WHERE id IN ({placeholders})", transactie_ids)
        datum_rows = await cur.fetchall()
    for r in datum_rows:
        await assert_year_writable(db_path, r[0])

    async with get_db_ctx(db_path) as conn:
        # Find linked facturen before deletion
        cur = await conn.execute(
            f"SELECT koppeling_id FROM banktransacties "
            f"WHERE id IN ({placeholders}) AND koppeling_type = 'factuur' "
            f"AND koppeling_id IS NOT NULL",
            transactie_ids,
        )
        linked = await cur.fetchall()
        linked_factuur_ids = [r['koppeling_id'] for r in linked]

        # Revert linked facturen betaald → verstuurd (same transaction)
        for fid in linked_factuur_ids:
            await conn.execute(
                "UPDATE facturen SET status = 'verstuurd', betaald_datum = '' "
                "WHERE id = ? AND status = 'betaald'",
                (fid,))

        # Delete the bank transactions
        cursor = await conn.execute(
            f"DELETE FROM banktransacties WHERE id IN ({placeholders})",
            transactie_ids,
        )
        await conn.commit()
        return cursor.rowcount, linked_factuur_ids


BELASTINGDIENST_IBAN = 'NL86INGB0002445588'


async def get_va_betalingen(db_path: Path = DB_PATH, jaar: int = 0) -> dict:
    """Get actual VA payments from bank transactions for a given year.

    Matches by Belastingdienst IBAN. Uses betalingskenmerk to split IB vs ZVW.
    IB kenmerken have digits at position 10-11 below 50, ZVW have 50+.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT ABS(bedrag) as amount, betalingskenmerk
               FROM banktransacties
               WHERE tegenrekening = ?
                 AND datum >= ? AND datum <= ?
                 AND bedrag < 0""",
            (BELASTINGDIENST_IBAN, f'{jaar}-01-01', f'{jaar}-12-31')
        )
        rows = await cur.fetchall()

    if not rows:
        return {
            'ib_betaald': 0, 'ib_termijnen': 0,
            'zvw_betaald': 0, 'zvw_termijnen': 0,
            'totaal_betaald': 0, 'has_bank_data': False,
        }

    ib_betaald = 0.0
    ib_count = 0
    zvw_betaald = 0.0
    zvw_count = 0
    unmatched = 0.0

    for amount, kenmerk in rows:
        if kenmerk and len(kenmerk) >= 12 and kenmerk[10:12].isdigit():
            year_type_digits = int(kenmerk[10:12])
            if year_type_digits >= 50:
                zvw_betaald += amount
                zvw_count += 1
            else:
                ib_betaald += amount
                ib_count += 1
        else:
            unmatched += amount

    return {
        'ib_betaald': round(ib_betaald, 2),
        'ib_termijnen': ib_count,
        'zvw_betaald': round(zvw_betaald, 2),
        'zvw_termijnen': zvw_count,
        'totaal_betaald': round(ib_betaald + zvw_betaald + unmatched, 2),
        'has_bank_data': True,
    }


async def backfill_betalingskenmerken(db_path: Path = DB_PATH,
                                       csv_dir: Path = None) -> int:
    """One-time backfill: read archived CSVs to populate betalingskenmerk
    on existing bank transactions that are missing it.

    Matches by (datum, bedrag, tegenpartij, omschrijving) — same dedup key
    as add_banktransacties. Returns count of rows updated.
    """
    from import_.rabobank_csv import parse_rabobank_csv

    if csv_dir is None:
        csv_dir = db_path.parent / 'bank_csv'
    if not csv_dir.exists():
        return 0

    # Check if backfill is needed
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT COUNT(*) FROM banktransacties
               WHERE tegenrekening = 'NL86INGB0002445588'
                 AND (betalingskenmerk IS NULL OR betalingskenmerk = '')"""
        )
        needs_backfill = (await cur.fetchone())[0]
    if needs_backfill == 0:
        return 0

    # Parse all archived CSVs
    kenmerk_map = {}
    for csv_file in sorted(csv_dir.glob('*.csv')):
        try:
            content = csv_file.read_bytes()
            txns = parse_rabobank_csv(content)
            for t in txns:
                k = t.get('betalingskenmerk', '')
                if k:
                    key = (t['datum'], t['bedrag'],
                           t.get('tegenpartij', ''), t.get('omschrijving', ''))
                    kenmerk_map[key] = k
        except Exception:
            continue

    if not kenmerk_map:
        return 0

    # Update existing rows
    count = 0
    async with get_db_ctx(db_path) as conn:
        for key, kenmerk in kenmerk_map.items():
            cur = await conn.execute(
                """UPDATE banktransacties SET betalingskenmerk = ?
                   WHERE datum = ? AND bedrag = ? AND tegenpartij = ?
                     AND omschrijving = ?
                     AND (betalingskenmerk IS NULL OR betalingskenmerk = '')""",
                (kenmerk, *key)
            )
            count += cur.rowcount
        await conn.commit()
    return count


async def backfill_betaallinks(db_path: Path = DB_PATH) -> int:
    """Backfill betaallink from QR files on disk for facturen missing it."""
    facturen_dir = db_path.parent / 'facturen'
    if not facturen_dir.exists():
        return 0
    count = 0
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT id, nummer FROM facturen "
            "WHERE betaallink IS NULL OR betaallink = ''")
        rows = await cur.fetchall()
        for row in rows:
            qr_file = facturen_dir / f"{row['nummer']}_qr.png"
            if not qr_file.exists():
                continue
            try:
                import cv2
                import numpy as np
                img_bytes = qr_file.read_bytes()
                arr = np.frombuffer(img_bytes, dtype=np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img is None:
                    continue
                data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
                if data and data.startswith('http'):
                    await conn.execute(
                        "UPDATE facturen SET betaallink = ? WHERE id = ?",
                        (data, row['id']))
                    count += 1
            except Exception:
                continue
        if count:
            await conn.commit()
    return count


# === Fiscale Parameters ===

def _row_to_fiscale_params(r) -> FiscaleParams:
    """Convert a database row to FiscaleParams.

    Uses explicit None checks (not `or`) for non-zero defaults to avoid
    silently overriding an intentional 0 value with the fallback.
    """
    def _v(val, default):
        """Return val if not None, else default. Unlike `or`, preserves 0."""
        return val if val is not None else default

    return FiscaleParams(
        jaar=r['jaar'],
        zelfstandigenaftrek=r['zelfstandigenaftrek'] or 0,
        startersaftrek=r['startersaftrek'] or 0,
        mkb_vrijstelling_pct=r['mkb_vrijstelling_pct'],
        kia_ondergrens=r['kia_ondergrens'],
        kia_bovengrens=r['kia_bovengrens'],
        kia_pct=r['kia_pct'],
        kia_drempel_per_item=_v(r['kia_drempel_per_item'], 450),
        km_tarief=r['km_tarief'],
        schijf1_grens=r['schijf1_grens'],
        schijf1_pct=r['schijf1_pct'],
        schijf2_grens=r['schijf2_grens'],
        schijf2_pct=r['schijf2_pct'],
        schijf3_pct=r['schijf3_pct'],
        ahk_max=r['ahk_max'],
        ahk_afbouw_pct=r['ahk_afbouw_pct'],
        ahk_drempel=r['ahk_drempel'],
        ak_max=r['ak_max'],
        zvw_pct=r['zvw_pct'],
        zvw_max_grondslag=r['zvw_max_grondslag'],
        repr_aftrek_pct=_v(r['repr_aftrek_pct'], 80),
        ew_forfait_pct=_v(r['ew_forfait_pct'], 0.35),
        villataks_grens=_v(r['villataks_grens'], 1_350_000),
        wet_hillen_pct=_v(r['wet_hillen_pct'], 0),
        urencriterium=_v(r['urencriterium'], 1225),
        aov_premie=r['aov_premie'] or 0,
        woz_waarde=r['woz_waarde'] or 0,
        hypotheekrente=r['hypotheekrente'] or 0,
        voorlopige_aanslag_betaald=r['voorlopige_aanslag_betaald'] or 0,
        pvv_premiegrondslag=r['pvv_premiegrondslag'] or 0,
        ew_naar_partner=bool(r['ew_naar_partner'] if r['ew_naar_partner'] is not None else 1),
        voorlopige_aanslag_zvw=r['voorlopige_aanslag_zvw'] or 0,
        partner_bruto_loon=r['partner_bruto_loon'] or 0,
        partner_loonheffing=r['partner_loonheffing'] or 0,
        arbeidskorting_brackets=r['arbeidskorting_brackets'] or '',
        pvv_aow_pct=_v(r['pvv_aow_pct'], 17.90),
        pvv_anw_pct=_v(r['pvv_anw_pct'], 0.10),
        pvv_wlz_pct=_v(r['pvv_wlz_pct'], 9.65),
        box3_bank_saldo=r['box3_bank_saldo'] or 0,
        box3_overige_bezittingen=r['box3_overige_bezittingen'] or 0,
        box3_schulden=r['box3_schulden'] or 0,
        box3_heffingsvrij_vermogen=_v(r['box3_heffingsvrij_vermogen'], 57000),
        box3_rendement_bank_pct=_v(r['box3_rendement_bank_pct'], 1.03),
        box3_rendement_overig_pct=_v(r['box3_rendement_overig_pct'], 6.17),
        box3_rendement_schuld_pct=_v(r['box3_rendement_schuld_pct'], 2.46),
        box3_tarief_pct=_v(r['box3_tarief_pct'], 36),
        box3_drempel_schulden=_v(r['box3_drempel_schulden'], 3700),
        box3_fiscaal_partner=bool(r['box3_fiscaal_partner'] if r['box3_fiscaal_partner'] is not None else 1),
        za_actief=bool(r['za_actief'] if r['za_actief'] is not None else 1),
        sa_actief=bool(r['sa_actief'] if r['sa_actief'] is not None else 0),
        lijfrente_premie=r['lijfrente_premie'] or 0,
        balans_bank_saldo=r['balans_bank_saldo'] or 0,
        balans_crediteuren=r['balans_crediteuren'] or 0,
        balans_overige_vorderingen=r['balans_overige_vorderingen'] or 0,
        balans_overige_schulden=r['balans_overige_schulden'] or 0,
        jaarafsluiting_status=r['jaarafsluiting_status'] or 'concept',
    )


async def get_fiscale_params(db_path: Path = DB_PATH, jaar: int = 0) -> FiscaleParams | None:
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute("SELECT * FROM fiscale_params WHERE jaar = ?", (jaar,))
        r = await cursor.fetchone()
        if not r:
            return None
        return _row_to_fiscale_params(r)


async def get_all_fiscale_params(db_path: Path = DB_PATH) -> list[FiscaleParams]:
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute("SELECT * FROM fiscale_params ORDER BY jaar")
        rows = await cursor.fetchall()
        return [_row_to_fiscale_params(r) for r in rows]


async def upsert_fiscale_params(db_path: Path = DB_PATH, **kwargs) -> None:
    # Year-lock guard (A6): block full upserts on a definitief jaar.
    # Exception: if caller is passing only jaarafsluiting_status (plus jaar),
    # allow it through as a re-freeze path. In practice status changes go
    # through update_jaarafsluiting_status (raw one-column UPDATE), which
    # bypasses this function entirely and is therefore not subject to this
    # guard — that is the dedicated unfreeze/re-freeze escape hatch.
    jaar = kwargs.get('jaar')
    if jaar is not None and (set(kwargs) - {'jaar', 'jaarafsluiting_status'}):
        await assert_year_writable(db_path, jaar)
    async with get_db_ctx(db_path) as conn:
        # Preserve IB-input, partner, box3 input, balans, and ew_naar_partner when overwriting from Instellingen
        cur = await conn.execute(
            "SELECT aov_premie, woz_waarde, hypotheekrente, "
            "voorlopige_aanslag_betaald, voorlopige_aanslag_zvw, "
            "partner_bruto_loon, partner_loonheffing, "
            "box3_bank_saldo, box3_overige_bezittingen, box3_schulden, "
            "box3_fiscaal_partner, "
            "ew_naar_partner, "
            "balans_bank_saldo, balans_crediteuren, "
            "balans_overige_vorderingen, balans_overige_schulden, "
            "lijfrente_premie, jaarafsluiting_status "
            "FROM fiscale_params WHERE jaar = ?",
            (kwargs['jaar'],))
        existing = await cur.fetchone()
        await conn.execute(
            """INSERT INTO fiscale_params
               (jaar, zelfstandigenaftrek, startersaftrek, mkb_vrijstelling_pct,
                kia_ondergrens, kia_bovengrens, kia_pct, kia_drempel_per_item, km_tarief,
                schijf1_grens, schijf1_pct, schijf2_grens, schijf2_pct, schijf3_pct,
                ahk_max, ahk_afbouw_pct, ahk_drempel, ak_max,
                zvw_pct, zvw_max_grondslag, repr_aftrek_pct,
                ew_forfait_pct, villataks_grens, wet_hillen_pct, urencriterium,
                pvv_premiegrondslag,
                arbeidskorting_brackets, pvv_aow_pct, pvv_anw_pct, pvv_wlz_pct,
                box3_heffingsvrij_vermogen, box3_rendement_bank_pct,
                box3_rendement_overig_pct, box3_rendement_schuld_pct, box3_tarief_pct,
                box3_drempel_schulden,
                za_actief, sa_actief,
                aov_premie, woz_waarde, hypotheekrente, voorlopige_aanslag_betaald,
                voorlopige_aanslag_zvw, partner_bruto_loon, partner_loonheffing,
                box3_bank_saldo, box3_overige_bezittingen, box3_schulden,
                box3_fiscaal_partner,
                ew_naar_partner, lijfrente_premie,
                balans_bank_saldo, balans_crediteuren,
                balans_overige_vorderingen, balans_overige_schulden,
                jaarafsluiting_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(jaar) DO UPDATE SET
                    zelfstandigenaftrek = excluded.zelfstandigenaftrek,
                    startersaftrek = excluded.startersaftrek,
                    mkb_vrijstelling_pct = excluded.mkb_vrijstelling_pct,
                    kia_ondergrens = excluded.kia_ondergrens,
                    kia_bovengrens = excluded.kia_bovengrens,
                    kia_pct = excluded.kia_pct,
                    kia_drempel_per_item = excluded.kia_drempel_per_item,
                    km_tarief = excluded.km_tarief,
                    schijf1_grens = excluded.schijf1_grens,
                    schijf1_pct = excluded.schijf1_pct,
                    schijf2_grens = excluded.schijf2_grens,
                    schijf2_pct = excluded.schijf2_pct,
                    schijf3_pct = excluded.schijf3_pct,
                    ahk_max = excluded.ahk_max,
                    ahk_afbouw_pct = excluded.ahk_afbouw_pct,
                    ahk_drempel = excluded.ahk_drempel,
                    ak_max = excluded.ak_max,
                    zvw_pct = excluded.zvw_pct,
                    zvw_max_grondslag = excluded.zvw_max_grondslag,
                    repr_aftrek_pct = excluded.repr_aftrek_pct,
                    ew_forfait_pct = excluded.ew_forfait_pct,
                    villataks_grens = excluded.villataks_grens,
                    wet_hillen_pct = excluded.wet_hillen_pct,
                    urencriterium = excluded.urencriterium,
                    pvv_premiegrondslag = excluded.pvv_premiegrondslag,
                    arbeidskorting_brackets = excluded.arbeidskorting_brackets,
                    pvv_aow_pct = excluded.pvv_aow_pct,
                    pvv_anw_pct = excluded.pvv_anw_pct,
                    pvv_wlz_pct = excluded.pvv_wlz_pct,
                    box3_heffingsvrij_vermogen = excluded.box3_heffingsvrij_vermogen,
                    box3_rendement_bank_pct = excluded.box3_rendement_bank_pct,
                    box3_rendement_overig_pct = excluded.box3_rendement_overig_pct,
                    box3_rendement_schuld_pct = excluded.box3_rendement_schuld_pct,
                    box3_tarief_pct = excluded.box3_tarief_pct,
                    box3_drempel_schulden = excluded.box3_drempel_schulden,
                    za_actief = excluded.za_actief,
                    sa_actief = excluded.sa_actief,
                    aov_premie = excluded.aov_premie,
                    woz_waarde = excluded.woz_waarde,
                    hypotheekrente = excluded.hypotheekrente,
                    voorlopige_aanslag_betaald = excluded.voorlopige_aanslag_betaald,
                    voorlopige_aanslag_zvw = excluded.voorlopige_aanslag_zvw,
                    partner_bruto_loon = excluded.partner_bruto_loon,
                    partner_loonheffing = excluded.partner_loonheffing,
                    box3_bank_saldo = excluded.box3_bank_saldo,
                    box3_overige_bezittingen = excluded.box3_overige_bezittingen,
                    box3_schulden = excluded.box3_schulden,
                    box3_fiscaal_partner = excluded.box3_fiscaal_partner,
                    ew_naar_partner = excluded.ew_naar_partner,
                    lijfrente_premie = excluded.lijfrente_premie,
                    balans_bank_saldo = excluded.balans_bank_saldo,
                    balans_crediteuren = excluded.balans_crediteuren,
                    balans_overige_vorderingen = excluded.balans_overige_vorderingen,
                    balans_overige_schulden = excluded.balans_overige_schulden,
                    jaarafsluiting_status = excluded.jaarafsluiting_status""",
            (kwargs['jaar'], kwargs['zelfstandigenaftrek'], kwargs.get('startersaftrek'),
             kwargs['mkb_vrijstelling_pct'], kwargs['kia_ondergrens'],
             kwargs['kia_bovengrens'], kwargs['kia_pct'],
             kwargs.get('kia_drempel_per_item', 450), kwargs['km_tarief'],
             kwargs['schijf1_grens'], kwargs['schijf1_pct'],
             kwargs['schijf2_grens'], kwargs['schijf2_pct'], kwargs['schijf3_pct'],
             kwargs['ahk_max'], kwargs['ahk_afbouw_pct'], kwargs['ahk_drempel'],
             kwargs['ak_max'], kwargs['zvw_pct'], kwargs['zvw_max_grondslag'],
             kwargs['repr_aftrek_pct'],
             kwargs['ew_forfait_pct'],
             kwargs['villataks_grens'],
             kwargs['wet_hillen_pct'],
             kwargs['urencriterium'],
             kwargs['pvv_premiegrondslag'],
             kwargs['arbeidskorting_brackets'],
             kwargs['pvv_aow_pct'],
             kwargs['pvv_anw_pct'],
             kwargs['pvv_wlz_pct'],
             kwargs['box3_heffingsvrij_vermogen'],
             kwargs['box3_rendement_bank_pct'],
             kwargs['box3_rendement_overig_pct'],
             kwargs['box3_rendement_schuld_pct'],
             kwargs['box3_tarief_pct'],
             kwargs['box3_drempel_schulden'],
             kwargs.get('za_actief', 1),
             kwargs.get('sa_actief', 0),
             existing['aov_premie'] if existing else 0,
             existing['woz_waarde'] if existing else 0,
             existing['hypotheekrente'] if existing else 0,
             existing['voorlopige_aanslag_betaald'] if existing else 0,
             existing['voorlopige_aanslag_zvw'] if existing else 0,
             existing['partner_bruto_loon'] if existing else 0,
             existing['partner_loonheffing'] if existing else 0,
             existing['box3_bank_saldo'] if existing else 0,
             existing['box3_overige_bezittingen'] if existing else 0,
             existing['box3_schulden'] if existing else 0,
             existing['box3_fiscaal_partner'] if existing else 1,
             existing['ew_naar_partner'] if existing else 1,
             existing['lijfrente_premie'] if existing else 0,
             existing['balans_bank_saldo'] if existing else 0,
             existing['balans_crediteuren'] if existing else 0,
             existing['balans_overige_vorderingen'] if existing else 0,
             existing['balans_overige_schulden'] if existing else 0,
             existing['jaarafsluiting_status'] if existing else 'concept')
        )
        await conn.commit()


async def update_ib_inputs(db_path: Path = DB_PATH, jaar: int = 0,
                           aov_premie: float = 0, woz_waarde: float = 0,
                           hypotheekrente: float = 0,
                           voorlopige_aanslag_betaald: float = 0,
                           voorlopige_aanslag_zvw: float = 0,
                           lijfrente_premie: float = 0) -> None:
    """Update only the IB-input columns for a specific year."""
    await assert_year_writable(db_path, jaar)
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            """UPDATE fiscale_params
               SET aov_premie = ?, woz_waarde = ?,
                   hypotheekrente = ?, voorlopige_aanslag_betaald = ?,
                   voorlopige_aanslag_zvw = ?, lijfrente_premie = ?
               WHERE jaar = ?""",
            (aov_premie, woz_waarde, hypotheekrente,
             voorlopige_aanslag_betaald, voorlopige_aanslag_zvw,
             lijfrente_premie, jaar))
        await conn.commit()


async def update_za_sa_toggles(db_path: Path = DB_PATH, jaar: int = 0,
                                za_actief: bool = True,
                                sa_actief: bool = False) -> bool:
    """Update ZA/SA toggle flags for a specific year.

    Returns True if a row was updated, False if no fiscale_params row exists.
    """
    await assert_year_writable(db_path, jaar)
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "UPDATE fiscale_params SET za_actief = ?, sa_actief = ? WHERE jaar = ?",
            (int(za_actief), int(sa_actief), jaar))
        await conn.commit()
        return cursor.rowcount > 0


async def update_ew_naar_partner(db_path: Path = DB_PATH, jaar: int = 0,
                                  value: bool = True) -> bool:
    """Update ew_naar_partner flag for a specific year.

    Returns True if a row was updated, False if no fiscale_params row exists.
    """
    await assert_year_writable(db_path, jaar)
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "UPDATE fiscale_params SET ew_naar_partner = ? WHERE jaar = ?",
            (1 if value else 0, jaar))
        await conn.commit()
        return cursor.rowcount > 0


async def update_box3_fiscaal_partner(db_path: Path = DB_PATH, jaar: int = 0,
                                      fiscaal_partner: bool = False) -> None:
    """Update Box 3 fiscaal partner flag."""
    await assert_year_writable(db_path, jaar)
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "UPDATE fiscale_params SET box3_fiscaal_partner = ? WHERE jaar = ?",
            (1 if fiscaal_partner else 0, jaar))
        await conn.commit()


async def update_box3_inputs(db_path: Path = DB_PATH, jaar: int = 0,
                             bank_saldo: float = 0,
                             overige_bezittingen: float = 0,
                             schulden: float = 0) -> bool:
    """Update Box 3 input fields in fiscale_params for a year.

    Returns True if a row was updated, False if no fiscale_params row exists.
    """
    await assert_year_writable(db_path, jaar)
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """UPDATE fiscale_params
               SET box3_bank_saldo = ?,
                   box3_overige_bezittingen = ?,
                   box3_schulden = ?
               WHERE jaar = ?""",
            (bank_saldo, overige_bezittingen, schulden, jaar))
        await conn.commit()
        return cursor.rowcount > 0


async def update_partner_inputs(db_path: Path = DB_PATH, jaar: int = 0,
                                 bruto_loon: float = 0,
                                 loonheffing: float = 0) -> bool:
    """Update partner input fields in fiscale_params for a year.

    Returns True if a row was updated, False if no fiscale_params row exists.
    """
    await assert_year_writable(db_path, jaar)
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """UPDATE fiscale_params
               SET partner_bruto_loon = ?, partner_loonheffing = ?
               WHERE jaar = ?""",
            (bruto_loon, loonheffing, jaar))
        await conn.commit()
        return cursor.rowcount > 0


# === Aggregation queries (voor dashboard + jaarafsluiting) ===

async def get_omzet_per_maand(db_path: Path = DB_PATH, jaar: int = 2026) -> list[float]:
    """Returns list of 12 monthly revenue totals."""
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """SELECT substr(datum, 6, 2) as maand, SUM(totaal_bedrag) as totaal
               FROM facturen
               WHERE datum >= ? AND datum < ? AND status != 'concept'
               GROUP BY maand ORDER BY maand""",
            (f'{jaar}-01-01', f'{jaar+1}-01-01')
        )
        rows = await cursor.fetchall()
        maand_map = {r['maand']: r['totaal'] for r in rows}
        return [maand_map.get(f"{m:02d}", 0) for m in range(1, 13)]


async def get_kpis(db_path: Path = DB_PATH, jaar: int = 2026) -> dict:
    async with get_db_ctx(db_path) as conn:
        jaar_start = f'{jaar}-01-01'
        jaar_end = f'{jaar+1}-01-01'
        # Omzet (excludes concept invoices)
        cur = await conn.execute(
            "SELECT COALESCE(SUM(totaal_bedrag), 0) FROM facturen "
            "WHERE datum >= ? AND datum < ? AND status != 'concept'",
            (jaar_start, jaar_end)
        )
        omzet = (await cur.fetchone())[0]

        # Kosten (excl. investeringen — die gaan via afschrijving)
        cur = await conn.execute(
            "SELECT COALESCE(SUM(bedrag), 0) FROM uitgaven "
            "WHERE datum >= ? AND datum < ? AND is_investering = 0", (jaar_start, jaar_end)
        )
        kosten = (await cur.fetchone())[0]

        # Uren (urennorm=1 only)
        cur = await conn.execute(
            "SELECT COALESCE(SUM(uren), 0) FROM werkdagen "
            "WHERE datum >= ? AND datum < ? AND urennorm = 1",
            (jaar_start, jaar_end)
        )
        uren = (await cur.fetchone())[0]

        # Openstaand
        cur = await conn.execute(
            "SELECT COALESCE(SUM(totaal_bedrag), 0) FROM facturen "
            "WHERE datum >= ? AND datum < ? AND status = 'verstuurd'",
            (jaar_start, jaar_end)
        )
        openstaand = (await cur.fetchone())[0]

        return {
            'omzet': omzet,
            'kosten': kosten,
            'winst': omzet - kosten,
            'uren': uren,
            'openstaand': openstaand,
        }


async def get_kpis_tot_datum(db_path: Path = DB_PATH, jaar: int = 2026,
                             max_datum: str = '') -> dict:
    """Get KPIs for a year up to a specific date (inclusive).

    Used for fair YoY comparison: compare previous year up to the same
    calendar date as today, not full months.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT COALESCE(SUM(totaal_bedrag), 0) FROM facturen "
            "WHERE datum >= ? AND datum <= ? AND status != 'concept'",
            (f'{jaar}-01-01', max_datum))
        omzet = (await cur.fetchone())[0]

        cur = await conn.execute(
            "SELECT COALESCE(SUM(bedrag), 0) FROM uitgaven "
            "WHERE datum >= ? AND datum <= ? AND is_investering = 0",
            (f'{jaar}-01-01', max_datum))
        kosten = (await cur.fetchone())[0]

        return {'omzet': omzet, 'kosten': kosten}


async def get_omzet_per_klant(db_path: Path = DB_PATH, jaar: int = 2026) -> list[dict]:
    """Revenue breakdown per customer for a given year."""
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """SELECT k.naam, SUM(f.totaal_uren) as uren,
                      SUM(f.totaal_km) as km, SUM(f.totaal_bedrag) as bedrag
               FROM facturen f JOIN klanten k ON f.klant_id = k.id
               WHERE f.datum >= ? AND f.datum < ? AND f.status != 'concept'
               GROUP BY k.naam ORDER BY bedrag DESC""",
            (f'{jaar}-01-01', f'{jaar+1}-01-01')
        )
        rows = await cursor.fetchall()
        return [{'naam': r['naam'], 'uren': r['uren'] or 0,
                 'km': r['km'] or 0, 'bedrag': r['bedrag'] or 0} for r in rows]


async def get_openstaande_facturen(db_path: Path = DB_PATH,
                                    jaar: int = None) -> list[Factuur]:
    """Get unpaid invoices."""
    async with get_db_ctx(db_path) as conn:
        sql = """SELECT f.*, k.naam as klant_naam
                 FROM facturen f JOIN klanten k ON f.klant_id = k.id
                 WHERE f.status = 'verstuurd'"""
        params = []
        if jaar:
            sql += " AND f.datum >= ? AND f.datum < ?"
            params.extend([f'{jaar}-01-01', f'{jaar+1}-01-01'])
        sql += " ORDER BY f.datum"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_factuur(r) for r in rows]


async def get_uren_totaal(db_path: Path = DB_PATH, jaar: int = 2026,
                           urennorm_only: bool = True) -> float:
    async with get_db_ctx(db_path) as conn:
        sql = "SELECT COALESCE(SUM(uren), 0) FROM werkdagen WHERE datum >= ? AND datum < ?"
        params = [f'{jaar}-01-01', f'{jaar+1}-01-01']
        if urennorm_only:
            sql += " AND urennorm = 1"
        cur = await conn.execute(sql, params)
        return (await cur.fetchone())[0]


async def get_omzet_totaal(db_path: Path = DB_PATH, jaar: int = 2026) -> float:
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT COALESCE(SUM(totaal_bedrag), 0) FROM facturen "
            "WHERE datum >= ? AND datum < ? AND status != 'concept'",
            (f'{jaar}-01-01', f'{jaar+1}-01-01')
        )
        return (await cur.fetchone())[0]


async def get_data_counts(db_path: Path = DB_PATH, jaar: int = 2026) -> dict:
    """Get counts of facturen, uitgaven, and werkdagen for a year."""
    async with get_db_ctx(db_path) as conn:
        jaar_start = f'{jaar}-01-01'
        jaar_end = f'{jaar+1}-01-01'
        cur = await conn.execute(
            "SELECT COUNT(*) FROM facturen "
            "WHERE datum >= ? AND datum < ?",
            (jaar_start, jaar_end))
        n_facturen = (await cur.fetchone())[0]
        cur = await conn.execute(
            "SELECT COUNT(*) FROM uitgaven WHERE datum >= ? AND datum < ?",
            (jaar_start, jaar_end))
        n_uitgaven = (await cur.fetchone())[0]
        cur = await conn.execute(
            "SELECT COUNT(*) FROM werkdagen WHERE datum >= ? AND datum < ?",
            (jaar_start, jaar_end))
        n_werkdagen = (await cur.fetchone())[0]
        return {
            'n_facturen': n_facturen,
            'n_uitgaven': n_uitgaven,
            'n_werkdagen': n_werkdagen,
        }


async def get_representatie_totaal(db_path: Path = DB_PATH, jaar: int = 2026) -> float:
    """Sum of representatiekosten in a year, excluding investments.

    Investments in categorie 'Representatie' (rare: a business artwork, for
    example) are depreciated separately via activastaat; including their
    full purchase price here would double-count against fiscale winst (the
    20% bijtelling on the representation deduction would apply twice).
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT COALESCE(SUM(bedrag), 0) FROM uitgaven "
            "WHERE datum >= ? AND datum < ? "
            "AND categorie = 'Representatie' "
            "AND is_investering = 0",
            (f'{jaar}-01-01', f'{jaar+1}-01-01')
        )
        return (await cur.fetchone())[0]


async def get_werkdagen_ongefactureerd_summary(
        db_path: Path = DB_PATH, jaar: int = 2026) -> dict:
    """Get count and estimated amount of unfactured werkdagen for a year."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT COUNT(*) as aantal,
                      COALESCE(SUM(uren * tarief + km * km_tarief), 0) as bedrag
               FROM werkdagen
               WHERE (factuurnummer = '' OR factuurnummer IS NULL)
                 AND datum >= ? AND datum < ?""",
            (f'{jaar}-01-01', f'{jaar+1}-01-01'))
        r = await cur.fetchone()
        return {'aantal': r['aantal'], 'bedrag': r['bedrag']}


async def get_health_alerts(db_path: Path = DB_PATH, jaar: int = 2026) -> list[dict]:
    """Return actionable health alerts for the dashboard.

    Each alert is a dict with keys:
      key: str         — identifier (e.g. 'uncategorized_bank')
      severity: str    — 'warning' or 'info'
      message: str     — human-readable Dutch description
      count: int       — number of items (for display)
      link: str        — page route to navigate to
    Returns empty list when everything is healthy.
    """
    from datetime import date, timedelta
    alerts = []
    jaar_start = f'{jaar}-01-01'
    jaar_end = f'{jaar + 1}-01-01'
    overdue_cutoff = (date.today() - timedelta(days=14)).isoformat()

    async with get_db_ctx(db_path) as conn:
        # 1. Uncategorized bank transactions (no category, no koppeling)
        cur = await conn.execute(
            "SELECT COUNT(*) FROM banktransacties "
            "WHERE datum >= ? AND datum < ? "
            "AND (categorie IS NULL OR categorie = '') "
            "AND (koppeling_type IS NULL OR koppeling_type = '')",
            (jaar_start, jaar_end))
        uncat = (await cur.fetchone())[0]
        if uncat > 0:
            alerts.append({
                'key': 'uncategorized_bank',
                'severity': 'info',
                'message': f'{uncat} banktransacties niet gecategoriseerd',
                'count': uncat,
                'link': '/bank',
            })

        # 2. Overdue invoices (verstuurd + datum > 14 days ago)
        cur = await conn.execute(
            "SELECT COUNT(*) FROM facturen "
            "WHERE status = 'verstuurd' AND datum < ? "
            "AND datum >= ? AND datum < ?",
            (overdue_cutoff, jaar_start, jaar_end))
        overdue = (await cur.fetchone())[0]
        if overdue > 0:
            alerts.append({
                'key': 'overdue_invoices',
                'severity': 'warning',
                'message': f'{overdue} facturen verlopen (> 14 dagen)',
                'count': overdue,
                'link': '/facturen',
            })

        # 3. Concept invoices still in draft
        cur = await conn.execute(
            "SELECT COUNT(*) FROM facturen "
            "WHERE status = 'concept' "
            "AND datum >= ? AND datum < ?",
            (jaar_start, jaar_end))
        concepts = (await cur.fetchone())[0]
        if concepts > 0:
            alerts.append({
                'key': 'concept_invoices',
                'severity': 'info',
                'message': f'{concepts} facturen nog in concept',
                'count': concepts,
                'link': '/facturen',
            })

    # 4. Missing fiscal params (outside connection — uses own)
    params = await get_fiscale_params(db_path, jaar)
    if params is None:
        alerts.append({
            'key': 'missing_fiscal_params',
            'severity': 'warning',
            'message': f'Fiscale parameters {jaar} niet ingesteld',
            'count': 0,
            'link': '/instellingen',
        })

    return alerts


async def get_km_totaal(db_path: Path = DB_PATH, jaar: int = 2026) -> dict:
    """Get total km and km-vergoeding for a year."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT COALESCE(SUM(km), 0) as km,
                      COALESCE(SUM(km * km_tarief), 0) as vergoeding
               FROM werkdagen WHERE datum >= ? AND datum < ?""",
            (f'{jaar}-01-01', f'{jaar+1}-01-01'))
        r = await cur.fetchone()
        return {'km': r['km'], 'vergoeding': r['vergoeding']}


async def get_investeringen_voor_afschrijving(db_path: Path = DB_PATH,
                                               tot_jaar: int = 2026) -> list[Uitgave]:
    """Get all investments up to and including given year."""
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "SELECT * FROM uitgaven WHERE is_investering = 1 "
            "AND CAST(substr(datum, 1, 4) AS INTEGER) <= ? ORDER BY datum",
            (tot_jaar,)
        )
        rows = await cursor.fetchall()
        return [_row_to_uitgave(r) for r in rows]


# === Afschrijving overrides ===

async def get_afschrijving_overrides(db_path: Path = DB_PATH,
                                      uitgave_id: int = 0) -> dict[int, float]:
    """Get all depreciation overrides for a single investment.

    Returns dict mapping jaar → bedrag.
    """
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "SELECT jaar, bedrag FROM afschrijving_overrides WHERE uitgave_id = ?",
            (uitgave_id,))
        rows = await cursor.fetchall()
        return {r['jaar']: r['bedrag'] for r in rows}


async def get_afschrijving_overrides_batch(
    db_path: Path = DB_PATH,
    uitgave_ids: list[int] | None = None,
) -> dict[int, dict[int, float]]:
    """Get overrides for multiple investments.

    Returns dict mapping uitgave_id → {jaar → bedrag}.
    """
    if not uitgave_ids:
        return {}
    async with get_db_ctx(db_path) as conn:
        placeholders = ','.join('?' * len(uitgave_ids))
        cursor = await conn.execute(
            f"SELECT uitgave_id, jaar, bedrag FROM afschrijving_overrides "
            f"WHERE uitgave_id IN ({placeholders})",
            uitgave_ids)
        rows = await cursor.fetchall()
        result: dict[int, dict[int, float]] = {}
        for r in rows:
            result.setdefault(r['uitgave_id'], {})[r['jaar']] = r['bedrag']
        return result


async def set_afschrijving_override(db_path: Path = DB_PATH,
                                     uitgave_id: int = 0,
                                     jaar: int = 0,
                                     bedrag: float = 0.0) -> None:
    """Set (upsert) a depreciation override for a specific investment+year."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            """INSERT INTO afschrijving_overrides (uitgave_id, jaar, bedrag)
               VALUES (?, ?, ?)
               ON CONFLICT(uitgave_id, jaar) DO UPDATE SET bedrag = excluded.bedrag""",
            (uitgave_id, jaar, bedrag))
        await conn.commit()


async def delete_afschrijving_override(db_path: Path = DB_PATH,
                                        uitgave_id: int = 0,
                                        jaar: int = 0) -> None:
    """Delete a specific depreciation override."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "DELETE FROM afschrijving_overrides WHERE uitgave_id = ? AND jaar = ?",
            (uitgave_id, jaar))
        await conn.commit()


# === Aangifte documenten ===

async def get_aangifte_documenten(db_path: Path = DB_PATH,
                                  jaar: int = 0) -> list[AangifteDocument]:
    """Get all aangifte documents for a year."""
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "SELECT * FROM aangifte_documenten WHERE jaar = ? ORDER BY categorie, documenttype",
            (jaar,))
        rows = await cursor.fetchall()
        return [AangifteDocument(
            id=r['id'], jaar=r['jaar'], categorie=r['categorie'],
            documenttype=r['documenttype'], bestandsnaam=r['bestandsnaam'],
            bestandspad=r['bestandspad'], upload_datum=r['upload_datum'],
            notitie=r['notitie'] or ''
        ) for r in rows]


async def add_aangifte_document(db_path: Path = DB_PATH, jaar: int = 0,
                                 categorie: str = '', documenttype: str = '',
                                 bestandsnaam: str = '', bestandspad: str = '',
                                 upload_datum: str = '',
                                 notitie: str = '') -> int:
    """Add a new aangifte document record. Returns id."""
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """INSERT INTO aangifte_documenten
               (jaar, categorie, documenttype, bestandsnaam, bestandspad, upload_datum, notitie)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (jaar, categorie, documenttype, bestandsnaam, bestandspad,
             upload_datum, notitie))
        await conn.commit()
        return cursor.lastrowid


async def delete_aangifte_document(db_path: Path = DB_PATH,
                                    doc_id: int = 0) -> None:
    """Delete an aangifte document record."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "DELETE FROM aangifte_documenten WHERE id = ?", (doc_id,))
        await conn.commit()


async def get_debiteuren_op_peildatum(db_path: Path = DB_PATH,
                                       peildatum: str = '') -> float:
    """Sum of receivables outstanding as of peildatum (typically 31-12-{year}).

    An invoice is a receivable at peildatum if:
    - It was issued on or before peildatum, AND
    - It's still unpaid (status != 'betaald'), OR
    - It was paid AFTER peildatum (status = 'betaald' AND betaald_datum > peildatum)

    Invoices with status='betaald' but no betaald_datum are assumed paid within their
    invoice period (conservative — not counted as receivables).
    """
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """SELECT COALESCE(SUM(totaal_bedrag), 0) FROM facturen
               WHERE datum <= ?
                 AND status != 'concept'
                 AND (
                     status != 'betaald'
                     OR (status = 'betaald' AND betaald_datum != '' AND betaald_datum > ?)
                 )""",
            (peildatum, peildatum))
        row = await cursor.fetchone()
        return float(row[0])


_MATCH_AMOUNT_TOL = 0.05  # EUR — rounding tolerance for Pass 2 amount matching
_MATCH_NUMMER_TOL = 1.00  # EUR — sanity bound when matching by invoice number
_MATCH_DAYS_BEFORE = 14
_MATCH_DAYS_AFTER = 90


def _match_date_ok(bank_datum: str, factuur_datum: str) -> bool:
    """Is bank date within [factuur-14d, factuur+90d]?"""
    fd = _date.fromisoformat(factuur_datum)
    earliest = (fd - _timedelta(days=_MATCH_DAYS_BEFORE)).isoformat()
    latest = (fd + _timedelta(days=_MATCH_DAYS_AFTER)).isoformat()
    return earliest <= bank_datum <= latest


async def find_factuur_matches(db_path: Path = DB_PATH) -> list[MatchProposal]:
    """Find matches between open facturen and incoming bank payments.

    Returns a list of ``MatchProposal`` WITHOUT applying them. Two-pass matching:

    1. **Pass 1 (nummer)**: invoice number appears in bank omschrijving AND
       amount within EUR 1. Confidence: always ``'high'``.
    2. **Pass 2 (bedrag)**: best-match scoring on amount alone, within
       ``_MATCH_AMOUNT_TOL``. When two facturen are within tolerance of the
       SAME bank transaction (or a factuur has two bank-txn candidates), the
       proposal is flagged ``confidence='low'`` and alternative bank_ids are
       recorded. Low-confidence proposals do NOT reserve the bank txn, so both
       sides of the ambiguity surface to the caller for manual confirmation.

    Date window: 14 days before to 90 days after factuur date.

    Only facturen with status ``'verstuurd'`` are considered. Only bank
    transactions with ``bedrag > 0`` and no existing koppeling are considered.
    """
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            """SELECT id, nummer, datum, totaal_bedrag FROM facturen
               WHERE status = 'verstuurd' ORDER BY datum""")
        open_facturen = await cur.fetchall()
        if not open_facturen:
            return []

        cur = await conn.execute(
            """SELECT id, datum, bedrag, tegenpartij, omschrijving
               FROM banktransacties
               WHERE bedrag > 0
               AND (koppeling_type IS NULL OR koppeling_type = '')
               ORDER BY datum""")
        bank_txns = await cur.fetchall()

        used_bank_ids: set[int] = set()
        proposals: list[MatchProposal] = []

        # Pass 1: Match by invoice number in omschrijving + amount sanity.
        # Always high confidence; reserves the bank_id before Pass 2 runs.
        #
        # Number match uses non-digit boundaries so that invoice "2026-001"
        # does NOT match omschrijving containing "2026-0012" or "2026-00123"
        # (review K3 — silent wrong-invoice-paid via substring collision).
        for f in open_facturen:
            nummer = f['nummer'].lower()
            nummer_re = re.compile(
                r'(?<!\d)' + re.escape(nummer) + r'(?!\d)'
            )
            for b in bank_txns:
                if b['id'] in used_bank_ids:
                    continue
                if not _match_date_ok(b['datum'], f['datum']):
                    continue
                omschr = (b['omschrijving'] or '').lower()
                if nummer_re.search(omschr):
                    delta = abs(b['bedrag'] - f['totaal_bedrag'])
                    if delta > _MATCH_NUMMER_TOL:
                        continue
                    used_bank_ids.add(b['id'])
                    proposals.append(MatchProposal(
                        factuur_id=f['id'],
                        bank_id=b['id'],
                        delta=delta,
                        confidence='high',
                        match_type='nummer',
                        factuur_nummer=f['nummer'],
                        factuur_bedrag=f['totaal_bedrag'],
                        factuur_datum=f['datum'],
                        bank_datum=b['datum'],
                        bank_bedrag=b['bedrag'],
                        bank_tegenpartij=b['tegenpartij'] or '',
                    ))
                    break

        matched_factuur_ids = {p.factuur_id for p in proposals}

        # Pass 2: Best-match amount scoring with bidirectional ambiguity flagging.
        #
        # The old implementation silently took the first factuur chronologically
        # when two invoices collided with the same bank txn (e.g. EUR 640.00 and
        # EUR 640.03 both matching a EUR 640.01 payment) — silent wrong-invoice-
        # paid. We surface such collisions instead so the user decides.
        #
        # Strategy:
        # 1. Build a pool of (factuur, bank, delta) triples for every pair
        #    within tolerance and within the date window.
        # 2. Group by factuur → ambiguous if factuur has >1 candidate whose
        #    deltas are within TOL of the best.
        # 3. Group by bank → ambiguous if bank has >1 factuur whose deltas are
        #    within TOL of the best (this is the collision case the old code
        #    missed).
        # 4. Emit proposals:
        #       - unambiguous on both sides → high confidence, reserve bank_id
        #       - ambiguous in either direction → low confidence, do NOT
        #         reserve bank_id (caller sees all sides of the collision)
        remaining_facturen = [f for f in open_facturen
                              if f['id'] not in matched_factuur_ids]

        # candidate_pairs[fid] = list of (delta, bank_row) sorted by delta asc
        candidate_pairs: dict[int, list[tuple[float, dict]]] = {}
        # bank_candidates[bank_id] = list of (delta, factuur_row) sorted by delta asc
        bank_candidates: dict[int, list[tuple[float, dict]]] = {}

        for f in remaining_facturen:
            for b in bank_txns:
                if b['id'] in used_bank_ids:
                    continue
                if not _match_date_ok(b['datum'], f['datum']):
                    continue
                delta = abs(b['bedrag'] - f['totaal_bedrag'])
                if delta > _MATCH_AMOUNT_TOL:
                    continue
                candidate_pairs.setdefault(f['id'], []).append((delta, b))
                bank_candidates.setdefault(b['id'], []).append((delta, f))

        for lst in candidate_pairs.values():
            lst.sort(key=lambda x: x[0])
        for lst in bank_candidates.values():
            lst.sort(key=lambda x: x[0])

        for f in remaining_facturen:
            cands = candidate_pairs.get(f['id'])
            if not cands:
                continue

            best_delta, best_b = cands[0]

            # Factuur-side ambiguity: multiple bank txns within TOL of this factuur.
            # Uses `<=` (not `<`) so that two candidates exactly _MATCH_AMOUNT_TOL
            # apart are ALSO flagged ambiguous (review K4 — silent-collision-at-
            # exact-boundary bug: both are within tolerance of the factuur, yet
            # the old strict `<` said "not ambiguous" and silently chose one).
            ambiguous = False
            alternatives: list[int] = []
            for alt_delta, alt_b in cands[1:]:
                if (alt_delta - best_delta) <= _MATCH_AMOUNT_TOL:
                    ambiguous = True
                    alternatives.append(alt_b['id'])

            # Bank-side ambiguity: multiple facturen contend for best_b.
            # This is the collision the old code silently resolved chronologically.
            bank_side = bank_candidates.get(best_b['id'], [])
            if len(bank_side) > 1:
                bank_best_delta = bank_side[0][0]
                for alt_delta, alt_f in bank_side:
                    if alt_f['id'] == f['id']:
                        continue
                    if (alt_delta - bank_best_delta) <= _MATCH_AMOUNT_TOL:
                        ambiguous = True
                        # Don't record other-factuur ids in bank-txn alternatives;
                        # the caller can see both proposals share the same bank_id.
                        break

            proposals.append(MatchProposal(
                factuur_id=f['id'],
                bank_id=best_b['id'],
                delta=best_delta,
                confidence='low' if ambiguous else 'high',
                match_type='bedrag',
                factuur_nummer=f['nummer'],
                factuur_bedrag=f['totaal_bedrag'],
                factuur_datum=f['datum'],
                bank_datum=best_b['datum'],
                bank_bedrag=best_b['bedrag'],
                bank_tegenpartij=best_b['tegenpartij'] or '',
                alternatives=alternatives,
            ))
            if not ambiguous:
                used_bank_ids.add(best_b['id'])

        return proposals


async def apply_factuur_matches(db_path: Path = DB_PATH,
                                 proposals: list = None) -> int:
    """Apply confirmed factuur-bank matches.

    Uses a single connection for the entire batch so the factuur status
    update and bank-transaction link are committed atomically.  Duplicate
    bank_id or factuur_id entries in *proposals* are silently skipped
    (first-seen wins) to prevent one bank payment marking two invoices.

    Accepts a list of ``MatchProposal``. Returns count of applied matches.
    Non-verstuurd facturen are skipped silently.

    Year-lock (K6): if ANY proposal's factuur-datum or bank-datum falls in
    a definitief jaar, the whole batch is rejected with YearLockedError —
    applying matches would silently mutate status and koppeling fields of a
    frozen jaar. Heropen het jaar eerst via /jaarafsluiting.
    """
    if not proposals:
        return 0

    applied = 0
    seen_bank_ids: set[int] = set()
    seen_factuur_ids: set[int] = set()

    # Year-lock guard (review gap): fetch factuur datums up-front and assert
    # both sides of every proposal are in writable years BEFORE opening the
    # atomic batch. Failing fast here means no partial application.
    factuur_ids = list({p.factuur_id for p in proposals})
    if factuur_ids:
        placeholders = ','.join('?' for _ in factuur_ids)
        async with get_db_ctx(db_path) as _ycheck:
            cur = await _ycheck.execute(
                f"SELECT datum FROM facturen WHERE id IN ({placeholders})",
                factuur_ids,
            )
            factuur_datums = [r[0] for r in await cur.fetchall()]
    else:
        factuur_datums = []
    for d in factuur_datums:
        await assert_year_writable(db_path, d)
    for p in proposals:
        if p.bank_datum:
            await assert_year_writable(db_path, p.bank_datum)

    async with get_db_ctx(db_path) as conn:
        for p in proposals:
            # Deduplicate: one bank row → one invoice, one invoice → one bank row
            if p.bank_id in seen_bank_ids or p.factuur_id in seen_factuur_ids:
                continue

            # Only transition verstuurd → betaald
            cur = await conn.execute(
                "SELECT status FROM facturen WHERE id = ?", (p.factuur_id,))
            row = await cur.fetchone()
            if not row or row['status'] != 'verstuurd':
                continue

            if p.bank_datum:
                _validate_datum(p.bank_datum)

            # Mark factuur as betaald
            await conn.execute(
                "UPDATE facturen SET status = 'betaald', betaald_datum = ? "
                "WHERE id = ?",
                (p.bank_datum, p.factuur_id))

            # Link bank transaction to factuur
            await conn.execute(
                "UPDATE banktransacties SET koppeling_type = 'factuur', "
                "koppeling_id = ? WHERE id = ?",
                (p.factuur_id, p.bank_id))

            seen_bank_ids.add(p.bank_id)
            seen_factuur_ids.add(p.factuur_id)
            applied += 1

        await conn.commit()
    return applied


async def get_nog_te_factureren(db_path: Path = DB_PATH, jaar: int = 0) -> float:
    """Sum of (uren * tarief + km * km_tarief) for unfactured werkdagen in the given year.

    Excludes werkdagen with zero revenue (admin/study hours) since those are
    never invoiced — they only count toward urencriterium.
    """
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "SELECT COALESCE(SUM(uren * tarief + km * km_tarief), 0.0) FROM werkdagen "
            "WHERE (factuurnummer = '' OR factuurnummer IS NULL) AND datum >= ? AND datum < ? "
            "AND tarief > 0",
            (f'{jaar}-01-01', f'{jaar+1}-01-01'))
        row = await cursor.fetchone()
        return float(row[0])


async def get_belastingdienst_betalingen(db_path: Path = DB_PATH,
                                         jaar: int = 0) -> float:
    """Sum of payments to Belastingdienst for a given year (negative = paid out).

    Returns positive number representing total paid. Excludes Boekhouder and refunds.
    """
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """SELECT COALESCE(SUM(ABS(bedrag)), 0.0) FROM banktransacties
               WHERE LOWER(tegenpartij) LIKE '%belastingdienst%'
               AND bedrag < 0
               AND datum >= ? AND datum < ?""",
            (f'{jaar}-01-01', f'{jaar+1}-01-01'))
        row = await cursor.fetchone()
        return float(row[0])


async def update_balans_inputs(db_path: Path = DB_PATH, jaar: int = 0,
                                balans_bank_saldo: float = 0,
                                balans_crediteuren: float = 0,
                                balans_overige_vorderingen: float = 0,
                                balans_overige_schulden: float = 0) -> bool:
    """Update balance sheet manual input fields for a specific year."""
    await assert_year_writable(db_path, jaar)
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            """UPDATE fiscale_params
               SET balans_bank_saldo = ?, balans_crediteuren = ?,
                   balans_overige_vorderingen = ?, balans_overige_schulden = ?
               WHERE jaar = ?""",
            (balans_bank_saldo, balans_crediteuren,
             balans_overige_vorderingen, balans_overige_schulden, jaar))
        await conn.commit()
        return cursor.rowcount > 0


async def update_jaarafsluiting_status(db_path: Path = DB_PATH, jaar: int = 0,
                                        status: str = 'concept') -> bool:
    """Update jaarafsluiting status for a specific year ('concept' or 'definitief')."""
    async with get_db_ctx(db_path) as conn:
        cursor = await conn.execute(
            "UPDATE fiscale_params SET jaarafsluiting_status = ? WHERE jaar = ?",
            (status, jaar))
        await conn.commit()
        return cursor.rowcount > 0


async def save_jaarafsluiting_snapshot(
    db_path: Path,
    jaar: int,
    snapshot: dict,
    balans: dict,
    fiscale_params: dict,
) -> None:
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            """INSERT INTO jaarafsluiting_snapshots
                   (jaar, snapshot_json, balans_json, gesnapshot_op, fiscale_params_json)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(jaar) DO UPDATE SET
                   snapshot_json = excluded.snapshot_json,
                   balans_json = excluded.balans_json,
                   gesnapshot_op = excluded.gesnapshot_op,
                   fiscale_params_json = excluded.fiscale_params_json""",
            (
                jaar,
                json.dumps(snapshot, default=str),
                json.dumps(balans, default=str),
                _datetime.now().isoformat(),
                json.dumps(fiscale_params, default=str),
            ),
        )
        await conn.commit()


async def load_jaarafsluiting_snapshot(db_path: Path, jaar: int) -> dict | None:
    async with get_db_ctx(db_path) as conn:
        async with conn.execute(
            """SELECT snapshot_json, balans_json, fiscale_params_json, gesnapshot_op
               FROM jaarafsluiting_snapshots WHERE jaar = ?""",
            (jaar,),
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                return None
            return {
                'snapshot': json.loads(row[0]),
                'balans': json.loads(row[1]),
                'fiscale_params': json.loads(row[2]),
                'gesnapshot_op': row[3],
            }


async def delete_jaarafsluiting_snapshot(db_path: Path, jaar: int) -> None:
    """Escape hatch hook; intentionally no-op — we keep the snapshot as audit trail."""
    return None


# --- Klant Locaties ---


async def get_klant_locaties(db_path, klant_id):
    """Get all locations for a klant, ordered by name."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT id, klant_id, naam, retour_km FROM klant_locaties "
            "WHERE klant_id = ? ORDER BY naam",
            (klant_id,))
        rows = await cur.fetchall()
        return [KlantLocatie(id=r['id'], klant_id=r['klant_id'],
                             naam=r['naam'], retour_km=r['retour_km'])
                for r in rows]


async def add_klant_locatie(db_path, klant_id, naam, retour_km):
    """Add a location to a klant. Returns the new location id."""
    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "INSERT INTO klant_locaties (klant_id, naam, retour_km) "
            "VALUES (?, ?, ?)",
            (klant_id, naam, retour_km))
        await conn.commit()
        return cur.lastrowid


async def delete_klant_locatie(db_path, locatie_id):
    """Delete a location by id."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "DELETE FROM klant_locaties WHERE id = ?", (locatie_id,))
        await conn.commit()


async def find_pdf_matches_for_banktx(
    db_path: Path, bank_tx_id: int, jaar: int,
) -> list[PdfMatch]:
    """Return archive PDFs that plausibly match this bank transaction.

    v1: matches by tegenpartij token overlap (len >= 3 chars).
    Empty list when nothing matches.
    """
    from components.kosten_helpers import match_tokens
    from import_.expense_utils import scan_archive

    async with get_db_ctx(db_path) as conn:
        cur = await conn.execute(
            "SELECT datum, tegenpartij FROM banktransacties WHERE id = ?",
            (bank_tx_id,))
        row = await cur.fetchone()
        if row is None:
            raise ValueError(f"banktransactie {bank_tx_id} not found")
        tegenpartij = row["tegenpartij"] or ""

    items = scan_archive(jaar, set())  # existing_filenames empty — we re-rank
    matches: list[PdfMatch] = []
    for it in items:
        if it.get("already_imported"):
            continue
        stem = Path(it["filename"]).stem
        score = match_tokens(tegenpartij, stem)
        if score == 0:
            continue
        matches.append(PdfMatch(
            path=Path(it["path"]),
            filename=it["filename"],
            categorie=it["categorie"],
            score=score,
        ))
    matches.sort(key=lambda m: (m.has_bedrag_match, m.score), reverse=True)
    return matches
