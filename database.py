"""SQLite database: schema, connectie, en alle queries."""

import aiosqlite
from pathlib import Path
from models import (
    Bedrijfsgegevens, Klant, KlantLocatie, Werkdag, Factuur, Uitgave,
    Banktransactie, FiscaleParams, AangifteDocument,
)

_PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = _PROJECT_ROOT / "data" / "boekhouding.sqlite3"

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
    uren REAL NOT NULL CHECK (uren > 0),
    km REAL DEFAULT 0 CHECK (km >= 0),
    tarief REAL NOT NULL CHECK (tarief >= 0),
    km_tarief REAL DEFAULT 0.23,
    status TEXT DEFAULT 'ongefactureerd',
    factuurnummer TEXT DEFAULT '',
    opmerking TEXT DEFAULT '',
    urennorm INTEGER DEFAULT 1 CHECK (urennorm IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_werkdagen_datum ON werkdagen(datum);
CREATE INDEX IF NOT EXISTS idx_werkdagen_klant ON werkdagen(klant_id);
CREATE INDEX IF NOT EXISTS idx_werkdagen_status ON werkdagen(status);

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
    type TEXT DEFAULT 'factuur'
);

CREATE INDEX IF NOT EXISTS idx_facturen_klant ON facturen(klant_id);

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
    ew_forfait_pct REAL DEFAULT 0.35,
    villataks_grens REAL DEFAULT 1350000,
    wet_hillen_pct REAL DEFAULT 0,
    urencriterium REAL DEFAULT 1225,
    aov_premie REAL DEFAULT 0,
    woz_waarde REAL DEFAULT 0,
    hypotheekrente REAL DEFAULT 0,
    voorlopige_aanslag_betaald REAL DEFAULT 0
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
"""


async def get_db(db_path: Path = DB_PATH) -> aiosqlite.Connection:
    """Get a database connection with WAL mode and FK enforcement."""
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db(db_path: Path = DB_PATH) -> None:
    """Create all tables if they don't exist, then run migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()
        # Migrations: add columns to fiscale_params (idempotent)
        for col, default in [
            ('aov_premie', 0), ('woz_waarde', 0),
            ('hypotheekrente', 0), ('voorlopige_aanslag_betaald', 0),
            ('ew_forfait_pct', 0.35), ('villataks_grens', 1350000),
            ('wet_hillen_pct', 0), ('urencriterium', 1225),
            ('partner_bruto_loon', 0), ('partner_loonheffing', 0),
            ('pvv_premiegrondslag', 0),
            ('ew_naar_partner', 1), ('voorlopige_aanslag_zvw', 0),
            # Phase: fiscal overhaul v2 — PVV rates + Box 3
            ('pvv_aow_pct', 17.90), ('pvv_anw_pct', 0.10), ('pvv_wlz_pct', 9.65),
            ('box3_bank_saldo', 0), ('box3_overige_bezittingen', 0), ('box3_schulden', 0),
            ('box3_heffingsvrij_vermogen', 57000),
            ('box3_rendement_bank_pct', 1.03), ('box3_rendement_overig_pct', 6.17),
            ('box3_rendement_schuld_pct', 2.46), ('box3_tarief_pct', 36),
        ]:
            try:
                await conn.execute(
                    f"ALTER TABLE fiscale_params ADD COLUMN {col} REAL DEFAULT {default}"
                )
            except Exception:
                pass  # Column already exists

        # TEXT column migration (separate because type differs)
        try:
            await conn.execute(
                "ALTER TABLE fiscale_params ADD COLUMN arbeidskorting_brackets TEXT DEFAULT ''"
            )
        except Exception:
            pass  # Column already exists

        # Migration: add locatie_id to werkdagen
        try:
            await conn.execute(
                "ALTER TABLE werkdagen ADD COLUMN locatie_id INTEGER "
                "REFERENCES klant_locaties(id) ON DELETE SET NULL"
            )
        except Exception:
            pass  # Column already exists

        # Data migration: set correct per-year values for newly added columns
        year_data = {
            2023: {'ew_forfait_pct': 0.35, 'villataks_grens': 1200000, 'wet_hillen_pct': 83.333, 'urencriterium': 1225},
            2024: {'ew_forfait_pct': 0.35, 'villataks_grens': 1310000, 'wet_hillen_pct': 80.0, 'urencriterium': 1225},
            2025: {'ew_forfait_pct': 0.35, 'villataks_grens': 1330000, 'wet_hillen_pct': 76.667, 'urencriterium': 1225},
            2026: {'ew_forfait_pct': 0.35, 'villataks_grens': 1350000, 'wet_hillen_pct': 71.867, 'urencriterium': 1225},
        }
        for jaar, vals in year_data.items():
            # Only update if wet_hillen_pct is still 0 (= not yet migrated)
            await conn.execute(
                """UPDATE fiscale_params SET ew_forfait_pct = ?, villataks_grens = ?,
                   wet_hillen_pct = ?, urencriterium = ?
                   WHERE jaar = ? AND wet_hillen_pct = 0""",
                (vals['ew_forfait_pct'], vals['villataks_grens'],
                 vals['wet_hillen_pct'], vals['urencriterium'], jaar))
        # Data migration: populate AK brackets and Box 3 defaults for existing years
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
        await conn.commit()


# === Bedrijfsgegevens ===

async def get_bedrijfsgegevens(db_path: Path = DB_PATH) -> Bedrijfsgegevens | None:
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute("SELECT * FROM bedrijfsgegevens WHERE id = 1")
        r = await cursor.fetchone()
        if not r:
            return None
        return Bedrijfsgegevens(
            id=1, bedrijfsnaam=r['bedrijfsnaam'], naam=r['naam'],
            functie=r['functie'], adres=r['adres'],
            postcode_plaats=r['postcode_plaats'], kvk=r['kvk'],
            iban=r['iban'], thuisplaats=r['thuisplaats'],
        )
    finally:
        await conn.close()


async def upsert_bedrijfsgegevens(db_path: Path = DB_PATH, **kwargs) -> None:
    conn = await get_db(db_path)
    try:
        await conn.execute(
            """INSERT OR REPLACE INTO bedrijfsgegevens
               (id, bedrijfsnaam, naam, functie, adres, postcode_plaats, kvk, iban, thuisplaats)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kwargs.get('bedrijfsnaam', ''), kwargs.get('naam', ''),
             kwargs.get('functie', ''), kwargs.get('adres', ''),
             kwargs.get('postcode_plaats', ''), kwargs.get('kvk', ''),
             kwargs.get('iban', ''), kwargs.get('thuisplaats', ''))
        )
        await conn.commit()
    finally:
        await conn.close()


# === Klanten ===

async def get_klanten(db_path: Path = DB_PATH, alleen_actief: bool = False) -> list[Klant]:
    conn = await get_db(db_path)
    try:
        sql = "SELECT * FROM klanten"
        if alleen_actief:
            sql += " WHERE actief = 1"
        sql += " ORDER BY naam"
        cursor = await conn.execute(sql)
        rows = await cursor.fetchall()
        return [Klant(
            id=r['id'], naam=r['naam'], tarief_uur=r['tarief_uur'],
            retour_km=r['retour_km'], adres=r['adres'] or '',
            kvk=r['kvk'] or '', actief=bool(r['actief'])
        ) for r in rows]
    finally:
        await conn.close()


async def add_klant(db_path: Path = DB_PATH, **kwargs) -> int:
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            "INSERT INTO klanten (naam, tarief_uur, retour_km, adres, kvk, actief) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (kwargs['naam'], kwargs.get('tarief_uur', 0), kwargs.get('retour_km', 0),
             kwargs.get('adres', ''), kwargs.get('kvk', ''), kwargs.get('actief', 1))
        )
        await conn.commit()
        return cursor.lastrowid
    finally:
        await conn.close()


async def update_klant(db_path: Path = DB_PATH, klant_id: int = 0, **kwargs) -> None:
    conn = await get_db(db_path)
    try:
        fields = []
        values = []
        for key in ('naam', 'tarief_uur', 'retour_km', 'adres', 'kvk', 'actief'):
            if key in kwargs:
                fields.append(f"{key} = ?")
                values.append(kwargs[key])
        if fields:
            values.append(klant_id)
            await conn.execute(
                f"UPDATE klanten SET {', '.join(fields)} WHERE id = ?", values
            )
            await conn.commit()
    finally:
        await conn.close()


async def delete_klant(db_path: Path = DB_PATH, klant_id: int = 0) -> None:
    conn = await get_db(db_path)
    try:
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
    finally:
        await conn.close()


# === Werkdagen ===

async def get_werkdagen(db_path: Path = DB_PATH, jaar: int = None,
                        maand: int = None, klant_id: int = None) -> list[Werkdag]:
    conn = await get_db(db_path)
    try:
        sql = """SELECT w.*, k.naam as klant_naam
                 FROM werkdagen w JOIN klanten k ON w.klant_id = k.id
                 WHERE 1=1"""
        params = []
        if jaar:
            sql += " AND substr(w.datum, 1, 4) = ?"
            params.append(str(jaar))
        if maand:
            sql += " AND substr(w.datum, 6, 2) = ?"
            params.append(f"{maand:02d}")
        if klant_id:
            sql += " AND w.klant_id = ?"
            params.append(klant_id)
        sql += " ORDER BY w.datum DESC"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [Werkdag(
            id=r['id'], datum=r['datum'], klant_id=r['klant_id'],
            klant_naam=r['klant_naam'], code=r['code'] or '',
            activiteit=r['activiteit'] or 'Waarneming dagpraktijk',
            locatie=r['locatie'] or '', uren=r['uren'], km=r['km'] or 0,
            tarief=r['tarief'], km_tarief=r['km_tarief'] or 0.23,
            status=r['status'] or 'ongefactureerd',
            factuurnummer=r['factuurnummer'] or '',
            opmerking=r['opmerking'] or '',
            urennorm=bool(r['urennorm']),
            locatie_id=r['locatie_id'],
        ) for r in rows]
    finally:
        await conn.close()


async def add_werkdag(db_path: Path = DB_PATH, **kwargs) -> int:
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            """INSERT INTO werkdagen
               (datum, klant_id, code, activiteit, locatie, uren, km,
                tarief, km_tarief, status, factuurnummer, opmerking, urennorm,
                locatie_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kwargs['datum'], kwargs['klant_id'],
             kwargs.get('code', ''), kwargs.get('activiteit', 'Waarneming dagpraktijk'),
             kwargs.get('locatie', ''), kwargs['uren'], kwargs.get('km', 0),
             kwargs['tarief'], kwargs.get('km_tarief', 0.23),
             kwargs.get('status', 'ongefactureerd'), kwargs.get('factuurnummer', ''),
             kwargs.get('opmerking', ''), kwargs.get('urennorm', 1),
             kwargs.get('locatie_id'))
        )
        await conn.commit()
        return cursor.lastrowid
    finally:
        await conn.close()


async def update_werkdag(db_path: Path = DB_PATH, werkdag_id: int = 0, **kwargs) -> None:
    conn = await get_db(db_path)
    try:
        fields = []
        values = []
        allowed = ('datum', 'klant_id', 'code', 'activiteit', 'locatie', 'uren',
                    'km', 'tarief', 'km_tarief', 'status', 'factuurnummer',
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
    finally:
        await conn.close()


async def delete_werkdag(db_path: Path = DB_PATH, werkdag_id: int = 0) -> None:
    conn = await get_db(db_path)
    try:
        await conn.execute("DELETE FROM werkdagen WHERE id = ?", (werkdag_id,))
        await conn.commit()
    finally:
        await conn.close()


async def get_werkdagen_ongefactureerd(db_path: Path = DB_PATH,
                                        klant_id: int = None) -> list[Werkdag]:
    conn = await get_db(db_path)
    try:
        sql = """SELECT w.*, k.naam as klant_naam
                 FROM werkdagen w JOIN klanten k ON w.klant_id = k.id
                 WHERE w.status = 'ongefactureerd'"""
        params = []
        if klant_id:
            sql += " AND w.klant_id = ?"
            params.append(klant_id)
        sql += " ORDER BY w.datum"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [Werkdag(
            id=r['id'], datum=r['datum'], klant_id=r['klant_id'],
            klant_naam=r['klant_naam'], code=r['code'] or '',
            activiteit=r['activiteit'] or 'Waarneming dagpraktijk',
            locatie=r['locatie'] or '', uren=r['uren'], km=r['km'] or 0,
            tarief=r['tarief'], km_tarief=r['km_tarief'] or 0.23,
            status=r['status'], factuurnummer=r['factuurnummer'] or '',
            opmerking=r['opmerking'] or '', urennorm=bool(r['urennorm']),
            locatie_id=r['locatie_id'],
        ) for r in rows]
    finally:
        await conn.close()


# === Facturen ===

async def get_facturen(db_path: Path = DB_PATH, jaar: int = None) -> list[Factuur]:
    conn = await get_db(db_path)
    try:
        sql = """SELECT f.*, k.naam as klant_naam
                 FROM facturen f JOIN klanten k ON f.klant_id = k.id
                 WHERE 1=1"""
        params = []
        if jaar:
            sql += " AND substr(f.datum, 1, 4) = ?"
            params.append(str(jaar))
        sql += " ORDER BY f.nummer DESC"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [Factuur(
            id=r['id'], nummer=r['nummer'], klant_id=r['klant_id'],
            klant_naam=r['klant_naam'], datum=r['datum'],
            totaal_uren=r['totaal_uren'] or 0,
            totaal_km=r['totaal_km'] or 0,
            totaal_bedrag=r['totaal_bedrag'],
            pdf_pad=r['pdf_pad'] or '', betaald=bool(r['betaald']),
            betaald_datum=r['betaald_datum'] or '',
            type=r['type'] or 'factuur'
        ) for r in rows]
    finally:
        await conn.close()


async def add_factuur(db_path: Path = DB_PATH, **kwargs) -> int:
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            """INSERT INTO facturen
               (nummer, klant_id, datum, totaal_uren, totaal_km,
                totaal_bedrag, pdf_pad, betaald, betaald_datum, type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kwargs['nummer'], kwargs['klant_id'], kwargs['datum'],
             kwargs.get('totaal_uren', 0), kwargs.get('totaal_km', 0),
             kwargs['totaal_bedrag'], kwargs.get('pdf_pad', ''),
             kwargs.get('betaald', 0), kwargs.get('betaald_datum', ''),
             kwargs.get('type', 'factuur'))
        )
        await conn.commit()
        return cursor.lastrowid
    finally:
        await conn.close()


async def get_next_factuurnummer(db_path: Path = DB_PATH, jaar: int = 2026) -> str:
    """Get next sequential invoice number: YYYY-NNN format, no gaps."""
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            "SELECT MAX(CAST(substr(nummer, 6) AS INTEGER)) FROM facturen WHERE nummer LIKE ?",
            (f"{jaar}-%",)
        )
        row = await cursor.fetchone()
        next_num = (row[0] or 0) + 1
        return f"{jaar}-{next_num:03d}"
    finally:
        await conn.close()


async def mark_betaald(db_path: Path = DB_PATH, factuur_id: int = 0,
                       datum: str = '', betaald: bool = True) -> None:
    conn = await get_db(db_path)
    try:
        await conn.execute(
            "UPDATE facturen SET betaald = ?, betaald_datum = ? WHERE id = ?",
            (1 if betaald else 0, datum, factuur_id)
        )
        # Cascade status to linked werkdagen
        cursor = await conn.execute(
            "SELECT nummer FROM facturen WHERE id = ?", (factuur_id,)
        )
        row = await cursor.fetchone()
        if row and row['nummer']:
            new_status = 'betaald' if betaald else 'gefactureerd'
            await conn.execute(
                "UPDATE werkdagen SET status = ? WHERE factuurnummer = ?",
                (new_status, row['nummer'])
            )
        await conn.commit()
    finally:
        await conn.close()


async def delete_factuur(db_path: Path = DB_PATH, factuur_id: int = 0) -> None:
    """Delete a factuur: unlink werkdagen, remove PDF, delete record."""
    conn = await get_db(db_path)
    try:
        # Get factuur nummer and pdf_pad
        cursor = await conn.execute(
            "SELECT nummer, pdf_pad FROM facturen WHERE id = ?", (factuur_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return
        nummer = row['nummer']
        pdf_pad = row['pdf_pad']

        # Unlink werkdagen
        await conn.execute(
            "UPDATE werkdagen SET status = 'ongefactureerd', factuurnummer = '' "
            "WHERE factuurnummer = ?", (nummer,)
        )

        # Delete factuur record
        await conn.execute("DELETE FROM facturen WHERE id = ?", (factuur_id,))
        await conn.commit()

        # Remove PDF file if it exists
        if pdf_pad:
            pdf_file = Path(pdf_pad)
            if pdf_file.exists():
                pdf_file.unlink()
    finally:
        await conn.close()


async def link_werkdagen_to_factuur(db_path: Path = DB_PATH,
                                     werkdag_ids: list[int] = None,
                                     factuurnummer: str = '') -> None:
    conn = await get_db(db_path)
    try:
        if werkdag_ids:
            placeholders = ','.join('?' for _ in werkdag_ids)
            await conn.execute(
                f"UPDATE werkdagen SET status = 'gefactureerd', factuurnummer = ? "
                f"WHERE id IN ({placeholders}) "
                f"AND (status = 'ongefactureerd' OR factuurnummer = '' OR factuurnummer IS NULL)",
                [factuurnummer] + werkdag_ids
            )
            await conn.commit()
    finally:
        await conn.close()


# === Uitgaven ===

async def get_uitgaven(db_path: Path = DB_PATH, jaar: int = None,
                       categorie: str = None) -> list[Uitgave]:
    conn = await get_db(db_path)
    try:
        sql = "SELECT * FROM uitgaven WHERE 1=1"
        params = []
        if jaar:
            sql += " AND substr(datum, 1, 4) = ?"
            params.append(str(jaar))
        if categorie:
            sql += " AND categorie = ?"
            params.append(categorie)
        sql += " ORDER BY datum DESC"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [Uitgave(
            id=r['id'], datum=r['datum'], categorie=r['categorie'],
            omschrijving=r['omschrijving'], bedrag=r['bedrag'],
            pdf_pad=r['pdf_pad'] or '', is_investering=bool(r['is_investering']),
            restwaarde_pct=r['restwaarde_pct'] or 10,
            levensduur_jaren=r['levensduur_jaren'],
            aanschaf_bedrag=r['aanschaf_bedrag'],
            zakelijk_pct=r['zakelijk_pct'] or 100
        ) for r in rows]
    finally:
        await conn.close()


async def add_uitgave(db_path: Path = DB_PATH, **kwargs) -> int:
    conn = await get_db(db_path)
    try:
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
    finally:
        await conn.close()


async def update_uitgave(db_path: Path = DB_PATH, uitgave_id: int = 0, **kwargs) -> None:
    conn = await get_db(db_path)
    try:
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
    finally:
        await conn.close()


async def delete_uitgave(db_path: Path = DB_PATH, uitgave_id: int = 0) -> None:
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            "SELECT pdf_pad FROM uitgaven WHERE id = ?", (uitgave_id,))
        row = await cursor.fetchone()
        await conn.execute("DELETE FROM uitgaven WHERE id = ?", (uitgave_id,))
        await conn.commit()
        if row and row['pdf_pad']:
            pdf_file = Path(row['pdf_pad'])
            if pdf_file.exists():
                pdf_file.unlink()
    finally:
        await conn.close()


async def get_uitgaven_per_categorie(db_path: Path = DB_PATH,
                                      jaar: int = None) -> list[dict]:
    conn = await get_db(db_path)
    try:
        sql = "SELECT categorie, SUM(bedrag) as totaal FROM uitgaven"
        params = []
        if jaar:
            sql += " WHERE substr(datum, 1, 4) = ?"
            params.append(str(jaar))
        sql += " GROUP BY categorie ORDER BY totaal DESC"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [{'categorie': r['categorie'], 'totaal': r['totaal']} for r in rows]
    finally:
        await conn.close()


async def get_investeringen(db_path: Path = DB_PATH, jaar: int = None) -> list[Uitgave]:
    conn = await get_db(db_path)
    try:
        sql = "SELECT * FROM uitgaven WHERE is_investering = 1"
        params = []
        if jaar:
            sql += " AND substr(datum, 1, 4) = ?"
            params.append(str(jaar))
        sql += " ORDER BY datum"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [Uitgave(
            id=r['id'], datum=r['datum'], categorie=r['categorie'],
            omschrijving=r['omschrijving'], bedrag=r['bedrag'],
            pdf_pad=r['pdf_pad'] or '', is_investering=True,
            restwaarde_pct=r['restwaarde_pct'] or 10,
            levensduur_jaren=r['levensduur_jaren'],
            aanschaf_bedrag=r['aanschaf_bedrag'],
            zakelijk_pct=r['zakelijk_pct'] or 100
        ) for r in rows]
    finally:
        await conn.close()


# === Banktransacties ===

async def get_banktransacties(db_path: Path = DB_PATH,
                               jaar: int = None) -> list[Banktransactie]:
    conn = await get_db(db_path)
    try:
        sql = "SELECT * FROM banktransacties WHERE 1=1"
        params = []
        if jaar:
            sql += " AND substr(datum, 1, 4) = ?"
            params.append(str(jaar))
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
            csv_bestand=r['csv_bestand'] or ''
        ) for r in rows]
    finally:
        await conn.close()


async def add_banktransacties(db_path: Path = DB_PATH,
                               transacties: list[dict] = None,
                               csv_bestand: str = '') -> int:
    """Insert batch of bank transactions. Returns count inserted."""
    conn = await get_db(db_path)
    try:
        count = 0
        for t in (transacties or []):
            await conn.execute(
                """INSERT INTO banktransacties
                   (datum, bedrag, tegenrekening, tegenpartij, omschrijving, csv_bestand)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (t['datum'], t['bedrag'], t.get('tegenrekening', ''),
                 t.get('tegenpartij', ''), t.get('omschrijving', ''), csv_bestand)
            )
            count += 1
        await conn.commit()
        return count
    finally:
        await conn.close()


async def update_banktransactie(db_path: Path = DB_PATH, transactie_id: int = 0,
                                 **kwargs) -> None:
    conn = await get_db(db_path)
    try:
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
    finally:
        await conn.close()


async def delete_banktransacties(db_path: Path = DB_PATH,
                                  transactie_ids: list[int] = None) -> int:
    """Delete bank transactions by IDs. Returns count deleted."""
    if not transactie_ids:
        return 0
    conn = await get_db(db_path)
    try:
        placeholders = ','.join('?' for _ in transactie_ids)
        cursor = await conn.execute(
            f"DELETE FROM banktransacties WHERE id IN ({placeholders})",
            transactie_ids,
        )
        await conn.commit()
        return cursor.rowcount
    finally:
        await conn.close()


# === Fiscale Parameters ===

def _safe_get(r, key, default, keys):
    """Get value from row, returning default if column missing or NULL."""
    if key not in keys:
        return default
    val = r[key]
    return val if val is not None else default


def _row_to_fiscale_params(r) -> FiscaleParams:
    """Convert a database row to FiscaleParams, handling missing/NULL columns."""
    keys = r.keys() if hasattr(r, 'keys') else []
    return FiscaleParams(
        jaar=r['jaar'],
        zelfstandigenaftrek=r['zelfstandigenaftrek'] or 0,
        startersaftrek=r['startersaftrek'] or 0,
        mkb_vrijstelling_pct=r['mkb_vrijstelling_pct'],
        kia_ondergrens=r['kia_ondergrens'],
        kia_bovengrens=r['kia_bovengrens'],
        kia_pct=r['kia_pct'],
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
        repr_aftrek_pct=r['repr_aftrek_pct'] or 80,
        ew_forfait_pct=_safe_get(r, 'ew_forfait_pct', 0.35, keys),
        villataks_grens=_safe_get(r, 'villataks_grens', 1_350_000, keys),
        wet_hillen_pct=_safe_get(r, 'wet_hillen_pct', 0, keys),
        urencriterium=_safe_get(r, 'urencriterium', 1225, keys),
        aov_premie=_safe_get(r, 'aov_premie', 0, keys),
        woz_waarde=_safe_get(r, 'woz_waarde', 0, keys),
        hypotheekrente=_safe_get(r, 'hypotheekrente', 0, keys),
        voorlopige_aanslag_betaald=_safe_get(
            r, 'voorlopige_aanslag_betaald', 0, keys
        ),
        pvv_premiegrondslag=_safe_get(r, 'pvv_premiegrondslag', 0, keys),
        ew_naar_partner=bool(_safe_get(r, 'ew_naar_partner', 1, keys)),
        voorlopige_aanslag_zvw=_safe_get(r, 'voorlopige_aanslag_zvw', 0, keys),
        partner_bruto_loon=_safe_get(r, 'partner_bruto_loon', 0, keys),
        partner_loonheffing=_safe_get(r, 'partner_loonheffing', 0, keys),
        arbeidskorting_brackets=_safe_get(r, 'arbeidskorting_brackets', '', keys) or '',
        pvv_aow_pct=_safe_get(r, 'pvv_aow_pct', 17.90, keys),
        pvv_anw_pct=_safe_get(r, 'pvv_anw_pct', 0.10, keys),
        pvv_wlz_pct=_safe_get(r, 'pvv_wlz_pct', 9.65, keys),
        box3_bank_saldo=_safe_get(r, 'box3_bank_saldo', 0, keys),
        box3_overige_bezittingen=_safe_get(r, 'box3_overige_bezittingen', 0, keys),
        box3_schulden=_safe_get(r, 'box3_schulden', 0, keys),
        box3_heffingsvrij_vermogen=_safe_get(r, 'box3_heffingsvrij_vermogen', 57000, keys),
        box3_rendement_bank_pct=_safe_get(r, 'box3_rendement_bank_pct', 1.03, keys),
        box3_rendement_overig_pct=_safe_get(r, 'box3_rendement_overig_pct', 6.17, keys),
        box3_rendement_schuld_pct=_safe_get(r, 'box3_rendement_schuld_pct', 2.46, keys),
        box3_tarief_pct=_safe_get(r, 'box3_tarief_pct', 36, keys),
    )


async def get_fiscale_params(db_path: Path = DB_PATH, jaar: int = 0) -> FiscaleParams:
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute("SELECT * FROM fiscale_params WHERE jaar = ?", (jaar,))
        r = await cursor.fetchone()
        if not r:
            return None
        return _row_to_fiscale_params(r)
    finally:
        await conn.close()


async def get_all_fiscale_params(db_path: Path = DB_PATH) -> list[FiscaleParams]:
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute("SELECT * FROM fiscale_params ORDER BY jaar")
        rows = await cursor.fetchall()
        return [_row_to_fiscale_params(r) for r in rows]
    finally:
        await conn.close()


async def upsert_fiscale_params(db_path: Path = DB_PATH, **kwargs) -> None:
    conn = await get_db(db_path)
    try:
        # Preserve IB-input, partner, and box3 input values when overwriting from Instellingen
        cur = await conn.execute(
            "SELECT aov_premie, woz_waarde, hypotheekrente, "
            "voorlopige_aanslag_betaald, voorlopige_aanslag_zvw, "
            "partner_bruto_loon, partner_loonheffing, "
            "box3_bank_saldo, box3_overige_bezittingen, box3_schulden "
            "FROM fiscale_params WHERE jaar = ?",
            (kwargs['jaar'],))
        existing = await cur.fetchone()
        await conn.execute(
            """INSERT OR REPLACE INTO fiscale_params
               (jaar, zelfstandigenaftrek, startersaftrek, mkb_vrijstelling_pct,
                kia_ondergrens, kia_bovengrens, kia_pct, km_tarief,
                schijf1_grens, schijf1_pct, schijf2_grens, schijf2_pct, schijf3_pct,
                ahk_max, ahk_afbouw_pct, ahk_drempel, ak_max,
                zvw_pct, zvw_max_grondslag, repr_aftrek_pct,
                ew_forfait_pct, villataks_grens, wet_hillen_pct, urencriterium,
                pvv_premiegrondslag,
                arbeidskorting_brackets, pvv_aow_pct, pvv_anw_pct, pvv_wlz_pct,
                box3_heffingsvrij_vermogen, box3_rendement_bank_pct,
                box3_rendement_overig_pct, box3_rendement_schuld_pct, box3_tarief_pct,
                aov_premie, woz_waarde, hypotheekrente, voorlopige_aanslag_betaald,
                voorlopige_aanslag_zvw, partner_bruto_loon, partner_loonheffing,
                box3_bank_saldo, box3_overige_bezittingen, box3_schulden)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?)""",
            (kwargs['jaar'], kwargs['zelfstandigenaftrek'], kwargs.get('startersaftrek'),
             kwargs['mkb_vrijstelling_pct'], kwargs['kia_ondergrens'],
             kwargs['kia_bovengrens'], kwargs['kia_pct'], kwargs['km_tarief'],
             kwargs['schijf1_grens'], kwargs['schijf1_pct'],
             kwargs['schijf2_grens'], kwargs['schijf2_pct'], kwargs['schijf3_pct'],
             kwargs['ahk_max'], kwargs['ahk_afbouw_pct'], kwargs['ahk_drempel'],
             kwargs['ak_max'], kwargs['zvw_pct'], kwargs['zvw_max_grondslag'],
             kwargs.get('repr_aftrek_pct', 80),
             kwargs.get('ew_forfait_pct', 0.35),
             kwargs.get('villataks_grens', 1_350_000),
             kwargs.get('wet_hillen_pct', 0),
             kwargs.get('urencriterium', 1225),
             kwargs.get('pvv_premiegrondslag', 0),
             kwargs.get('arbeidskorting_brackets', ''),
             kwargs.get('pvv_aow_pct', 17.90),
             kwargs.get('pvv_anw_pct', 0.10),
             kwargs.get('pvv_wlz_pct', 9.65),
             kwargs.get('box3_heffingsvrij_vermogen', 57000),
             kwargs.get('box3_rendement_bank_pct', 1.03),
             kwargs.get('box3_rendement_overig_pct', 6.17),
             kwargs.get('box3_rendement_schuld_pct', 2.46),
             kwargs.get('box3_tarief_pct', 36),
             existing['aov_premie'] if existing else 0,
             existing['woz_waarde'] if existing else 0,
             existing['hypotheekrente'] if existing else 0,
             existing['voorlopige_aanslag_betaald'] if existing else 0,
             existing['voorlopige_aanslag_zvw'] if existing else 0,
             existing['partner_bruto_loon'] if existing else 0,
             existing['partner_loonheffing'] if existing else 0,
             existing['box3_bank_saldo'] if existing else 0,
             existing['box3_overige_bezittingen'] if existing else 0,
             existing['box3_schulden'] if existing else 0)
        )
        await conn.commit()
    finally:
        await conn.close()


async def update_ib_inputs(db_path: Path = DB_PATH, jaar: int = 0,
                           aov_premie: float = 0, woz_waarde: float = 0,
                           hypotheekrente: float = 0,
                           voorlopige_aanslag_betaald: float = 0,
                           voorlopige_aanslag_zvw: float = 0) -> None:
    """Update only the IB-input columns for a specific year."""
    conn = await get_db(db_path)
    try:
        await conn.execute(
            """UPDATE fiscale_params
               SET aov_premie = ?, woz_waarde = ?,
                   hypotheekrente = ?, voorlopige_aanslag_betaald = ?,
                   voorlopige_aanslag_zvw = ?
               WHERE jaar = ?""",
            (aov_premie, woz_waarde, hypotheekrente,
             voorlopige_aanslag_betaald, voorlopige_aanslag_zvw, jaar))
        await conn.commit()
    finally:
        await conn.close()


async def update_box3_inputs(db_path: Path = DB_PATH, jaar: int = 0,
                             bank_saldo: float = 0,
                             overige_bezittingen: float = 0,
                             schulden: float = 0) -> bool:
    """Update Box 3 input fields in fiscale_params for a year.

    Returns True if a row was updated, False if no fiscale_params row exists.
    """
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            """UPDATE fiscale_params
               SET box3_bank_saldo = ?,
                   box3_overige_bezittingen = ?,
                   box3_schulden = ?
               WHERE jaar = ?""",
            (bank_saldo, overige_bezittingen, schulden, jaar))
        await conn.commit()
        return cursor.rowcount > 0
    finally:
        await conn.close()


# === Aggregation queries (voor dashboard + jaarafsluiting) ===

async def get_omzet_per_maand(db_path: Path = DB_PATH, jaar: int = 2026) -> list[float]:
    """Returns list of 12 monthly revenue totals."""
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            """SELECT substr(datum, 6, 2) as maand, SUM(totaal_bedrag) as totaal
               FROM facturen
               WHERE substr(datum, 1, 4) = ? AND type = 'factuur'
               GROUP BY maand ORDER BY maand""",
            (str(jaar),)
        )
        rows = await cursor.fetchall()
        maand_map = {r['maand']: r['totaal'] for r in rows}
        return [maand_map.get(f"{m:02d}", 0) for m in range(1, 13)]
    finally:
        await conn.close()


async def get_kpis(db_path: Path = DB_PATH, jaar: int = 2026) -> dict:
    conn = await get_db(db_path)
    try:
        jaar_str = str(jaar)
        # Omzet
        cur = await conn.execute(
            "SELECT COALESCE(SUM(totaal_bedrag), 0) FROM facturen "
            "WHERE substr(datum, 1, 4) = ? AND type = 'factuur'",
            (jaar_str,)
        )
        omzet = (await cur.fetchone())[0]

        # Kosten (excl. investeringen — die gaan via afschrijving)
        cur = await conn.execute(
            "SELECT COALESCE(SUM(bedrag), 0) FROM uitgaven "
            "WHERE substr(datum, 1, 4) = ? AND is_investering = 0", (jaar_str,)
        )
        kosten = (await cur.fetchone())[0]

        # Uren (urennorm=1 only)
        cur = await conn.execute(
            "SELECT COALESCE(SUM(uren), 0) FROM werkdagen "
            "WHERE substr(datum, 1, 4) = ? AND urennorm = 1",
            (jaar_str,)
        )
        uren = (await cur.fetchone())[0]

        # Openstaand
        cur = await conn.execute(
            "SELECT COALESCE(SUM(totaal_bedrag), 0) FROM facturen "
            "WHERE substr(datum, 1, 4) = ? AND betaald = 0 AND type = 'factuur'",
            (jaar_str,)
        )
        openstaand = (await cur.fetchone())[0]

        return {
            'omzet': omzet,
            'kosten': kosten,
            'winst': omzet - kosten,
            'uren': uren,
            'openstaand': openstaand,
        }
    finally:
        await conn.close()


async def get_omzet_per_klant(db_path: Path = DB_PATH, jaar: int = 2026) -> list[dict]:
    """Revenue breakdown per customer for a given year."""
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            """SELECT k.naam, SUM(f.totaal_uren) as uren,
                      SUM(f.totaal_km) as km, SUM(f.totaal_bedrag) as bedrag
               FROM facturen f JOIN klanten k ON f.klant_id = k.id
               WHERE substr(f.datum, 1, 4) = ? AND f.type = 'factuur'
               GROUP BY k.naam ORDER BY bedrag DESC""",
            (str(jaar),)
        )
        rows = await cursor.fetchall()
        return [{'naam': r['naam'], 'uren': r['uren'] or 0,
                 'km': r['km'] or 0, 'bedrag': r['bedrag'] or 0} for r in rows]
    finally:
        await conn.close()


async def get_recente_facturen(db_path: Path = DB_PATH,
                                limit: int = 5) -> list[Factuur]:
    """Get most recent invoices across all years."""
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            """SELECT f.*, k.naam as klant_naam
               FROM facturen f JOIN klanten k ON f.klant_id = k.id
               WHERE f.type = 'factuur'
               ORDER BY f.datum DESC LIMIT ?""",
            (limit,)
        )
        rows = await cursor.fetchall()
        return [Factuur(
            id=r['id'], nummer=r['nummer'], klant_id=r['klant_id'],
            klant_naam=r['klant_naam'], datum=r['datum'],
            totaal_uren=r['totaal_uren'] or 0, totaal_km=r['totaal_km'] or 0,
            totaal_bedrag=r['totaal_bedrag'],
            pdf_pad=r['pdf_pad'] or '', betaald=bool(r['betaald']),
            betaald_datum=r['betaald_datum'] or '',
            type=r['type'] or 'factuur'
        ) for r in rows]
    finally:
        await conn.close()


async def get_openstaande_facturen(db_path: Path = DB_PATH,
                                    jaar: int = None) -> list[Factuur]:
    """Get unpaid invoices."""
    conn = await get_db(db_path)
    try:
        sql = """SELECT f.*, k.naam as klant_naam
                 FROM facturen f JOIN klanten k ON f.klant_id = k.id
                 WHERE f.betaald = 0 AND f.type = 'factuur'"""
        params = []
        if jaar:
            sql += " AND substr(f.datum, 1, 4) = ?"
            params.append(str(jaar))
        sql += " ORDER BY f.datum"
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [Factuur(
            id=r['id'], nummer=r['nummer'], klant_id=r['klant_id'],
            klant_naam=r['klant_naam'], datum=r['datum'],
            totaal_uren=r['totaal_uren'] or 0, totaal_km=r['totaal_km'] or 0,
            totaal_bedrag=r['totaal_bedrag'],
            pdf_pad=r['pdf_pad'] or '', betaald=False,
            betaald_datum='', type=r['type'] or 'factuur'
        ) for r in rows]
    finally:
        await conn.close()


async def get_factuur_count(db_path: Path = DB_PATH, jaar: int = 2026) -> int:
    """Count invoices for a year."""
    conn = await get_db(db_path)
    try:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM facturen WHERE substr(datum, 1, 4) = ? AND type = 'factuur'",
            (str(jaar),)
        )
        return (await cur.fetchone())[0]
    finally:
        await conn.close()


async def get_uren_totaal(db_path: Path = DB_PATH, jaar: int = 2026,
                           urennorm_only: bool = True) -> float:
    conn = await get_db(db_path)
    try:
        sql = "SELECT COALESCE(SUM(uren), 0) FROM werkdagen WHERE substr(datum, 1, 4) = ?"
        params = [str(jaar)]
        if urennorm_only:
            sql += " AND urennorm = 1"
        cur = await conn.execute(sql, params)
        return (await cur.fetchone())[0]
    finally:
        await conn.close()


async def get_omzet_totaal(db_path: Path = DB_PATH, jaar: int = 2026) -> float:
    conn = await get_db(db_path)
    try:
        cur = await conn.execute(
            "SELECT COALESCE(SUM(totaal_bedrag), 0) FROM facturen "
            "WHERE substr(datum, 1, 4) = ? AND type = 'factuur'",
            (str(jaar),)
        )
        return (await cur.fetchone())[0]
    finally:
        await conn.close()


async def get_representatie_totaal(db_path: Path = DB_PATH, jaar: int = 2026) -> float:
    conn = await get_db(db_path)
    try:
        cur = await conn.execute(
            "SELECT COALESCE(SUM(bedrag), 0) FROM uitgaven "
            "WHERE substr(datum, 1, 4) = ? AND categorie = 'Representatie'",
            (str(jaar),)
        )
        return (await cur.fetchone())[0]
    finally:
        await conn.close()


async def get_werkdagen_ongefactureerd_summary(
        db_path: Path = DB_PATH, jaar: int = 2026) -> dict:
    """Get count and estimated amount of unfactured werkdagen for a year."""
    conn = await get_db(db_path)
    try:
        cur = await conn.execute(
            """SELECT COUNT(*) as aantal,
                      COALESCE(SUM(uren * tarief + km * km_tarief), 0) as bedrag
               FROM werkdagen
               WHERE status = 'ongefactureerd'
                 AND substr(datum, 1, 4) = ?""",
            (str(jaar),))
        r = await cur.fetchone()
        return {'aantal': r['aantal'], 'bedrag': r['bedrag']}
    finally:
        await conn.close()


async def get_km_totaal(db_path: Path = DB_PATH, jaar: int = 2026) -> dict:
    """Get total km and km-vergoeding for a year."""
    conn = await get_db(db_path)
    try:
        cur = await conn.execute(
            """SELECT COALESCE(SUM(km), 0) as km,
                      COALESCE(SUM(km * km_tarief), 0) as vergoeding
               FROM werkdagen WHERE substr(datum, 1, 4) = ?""",
            (str(jaar),))
        r = await cur.fetchone()
        return {'km': r['km'], 'vergoeding': r['vergoeding']}
    finally:
        await conn.close()


async def get_investeringen_voor_afschrijving(db_path: Path = DB_PATH,
                                               tot_jaar: int = 2026) -> list[Uitgave]:
    """Get all investments up to and including given year."""
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            "SELECT * FROM uitgaven WHERE is_investering = 1 "
            "AND CAST(substr(datum, 1, 4) AS INTEGER) <= ? ORDER BY datum",
            (tot_jaar,)
        )
        rows = await cursor.fetchall()
        return [Uitgave(
            id=r['id'], datum=r['datum'], categorie=r['categorie'],
            omschrijving=r['omschrijving'], bedrag=r['bedrag'],
            is_investering=True, restwaarde_pct=r['restwaarde_pct'] or 10,
            levensduur_jaren=r['levensduur_jaren'],
            aanschaf_bedrag=r['aanschaf_bedrag'],
            zakelijk_pct=r['zakelijk_pct'] or 100
        ) for r in rows]
    finally:
        await conn.close()


# === Aangifte documenten ===

async def get_aangifte_documenten(db_path: Path = DB_PATH,
                                  jaar: int = 0) -> list[AangifteDocument]:
    """Get all aangifte documents for a year."""
    conn = await get_db(db_path)
    try:
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
    finally:
        await conn.close()


async def add_aangifte_document(db_path: Path = DB_PATH, jaar: int = 0,
                                 categorie: str = '', documenttype: str = '',
                                 bestandsnaam: str = '', bestandspad: str = '',
                                 upload_datum: str = '',
                                 notitie: str = '') -> int:
    """Add a new aangifte document record. Returns id."""
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            """INSERT INTO aangifte_documenten
               (jaar, categorie, documenttype, bestandsnaam, bestandspad, upload_datum, notitie)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (jaar, categorie, documenttype, bestandsnaam, bestandspad,
             upload_datum, notitie))
        await conn.commit()
        return cursor.lastrowid
    finally:
        await conn.close()


async def delete_aangifte_document(db_path: Path = DB_PATH,
                                    doc_id: int = 0) -> None:
    """Delete an aangifte document record."""
    conn = await get_db(db_path)
    try:
        await conn.execute(
            "DELETE FROM aangifte_documenten WHERE id = ?", (doc_id,))
        await conn.commit()
    finally:
        await conn.close()


async def update_partner_inkomen(db_path: Path = DB_PATH, jaar: int = 0,
                                  partner_bruto_loon: float = 0,
                                  partner_loonheffing: float = 0) -> bool:
    """Update partner income fields in fiscale_params for a year.

    Returns True if a row was updated, False if no fiscale_params row exists.
    """
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            """UPDATE fiscale_params
               SET partner_bruto_loon = ?, partner_loonheffing = ?
               WHERE jaar = ?""",
            (partner_bruto_loon, partner_loonheffing, jaar))
        await conn.commit()
        return cursor.rowcount > 0
    finally:
        await conn.close()


# --- Klant Locaties ---


async def get_klant_locaties(db_path, klant_id):
    """Get all locations for a klant, ordered by name."""
    conn = await get_db(db_path)
    try:
        cur = await conn.execute(
            "SELECT id, klant_id, naam, retour_km FROM klant_locaties "
            "WHERE klant_id = ? ORDER BY naam",
            (klant_id,))
        rows = await cur.fetchall()
        return [KlantLocatie(id=r['id'], klant_id=r['klant_id'],
                             naam=r['naam'], retour_km=r['retour_km'])
                for r in rows]
    finally:
        await conn.close()


async def add_klant_locatie(db_path, klant_id, naam, retour_km):
    """Add a location to a klant. Returns the new location id."""
    conn = await get_db(db_path)
    try:
        cur = await conn.execute(
            "INSERT INTO klant_locaties (klant_id, naam, retour_km) "
            "VALUES (?, ?, ?)",
            (klant_id, naam, retour_km))
        await conn.commit()
        return cur.lastrowid
    finally:
        await conn.close()


async def update_klant_locatie(db_path, locatie_id, naam, retour_km):
    """Update a location's name and/or km."""
    conn = await get_db(db_path)
    try:
        await conn.execute(
            "UPDATE klant_locaties SET naam = ?, retour_km = ? WHERE id = ?",
            (naam, retour_km, locatie_id))
        await conn.commit()
    finally:
        await conn.close()


async def delete_klant_locatie(db_path, locatie_id):
    """Delete a location by id."""
    conn = await get_db(db_path)
    try:
        await conn.execute(
            "DELETE FROM klant_locaties WHERE id = ?", (locatie_id,))
        await conn.commit()
    finally:
        await conn.close()
