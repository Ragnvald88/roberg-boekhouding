"""SQLite database: schema, connectie, en alle queries voor TestBV Boekhouding."""

import aiosqlite
from pathlib import Path
from models import (
    Klant, Werkdag, Factuur, Uitgave, Banktransactie, FiscaleParams
)

DB_PATH = Path("data/boekhouding.sqlite3")

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
    repr_aftrek_pct REAL DEFAULT 80
);
"""


async def get_db(db_path: Path = DB_PATH) -> aiosqlite.Connection:
    """Get a database connection with WAL mode and FK enforcement."""
    conn = await aiosqlite.connect(db_path)
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db(db_path: Path = DB_PATH) -> None:
    """Create all tables if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()


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
        await conn.execute("DELETE FROM klanten WHERE id = ?", (klant_id,))
        await conn.commit()
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
            urennorm=bool(r['urennorm'])
        ) for r in rows]
    finally:
        await conn.close()


async def add_werkdag(db_path: Path = DB_PATH, **kwargs) -> int:
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute(
            """INSERT INTO werkdagen
               (datum, klant_id, code, activiteit, locatie, uren, km,
                tarief, km_tarief, status, factuurnummer, opmerking, urennorm)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kwargs['datum'], kwargs['klant_id'],
             kwargs.get('code', ''), kwargs.get('activiteit', 'Waarneming dagpraktijk'),
             kwargs.get('locatie', ''), kwargs['uren'], kwargs.get('km', 0),
             kwargs['tarief'], kwargs.get('km_tarief', 0.23),
             kwargs.get('status', 'ongefactureerd'), kwargs.get('factuurnummer', ''),
             kwargs.get('opmerking', ''), kwargs.get('urennorm', 1))
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
                    'opmerking', 'urennorm')
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
            opmerking=r['opmerking'] or '', urennorm=bool(r['urennorm'])
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
                       datum: str = '') -> None:
    conn = await get_db(db_path)
    try:
        await conn.execute(
            "UPDATE facturen SET betaald = 1, betaald_datum = ? WHERE id = ?",
            (datum, factuur_id)
        )
        await conn.commit()
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
                f"WHERE id IN ({placeholders})",
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
        await conn.execute("DELETE FROM uitgaven WHERE id = ?", (uitgave_id,))
        await conn.commit()
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


# === Fiscale Parameters ===

async def get_fiscale_params(db_path: Path = DB_PATH, jaar: int = 0) -> FiscaleParams:
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute("SELECT * FROM fiscale_params WHERE jaar = ?", (jaar,))
        r = await cursor.fetchone()
        if not r:
            return None
        return FiscaleParams(
            jaar=r['jaar'],
            zelfstandigenaftrek=r['zelfstandigenaftrek'],
            startersaftrek=r['startersaftrek'],
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
        )
    finally:
        await conn.close()


async def get_all_fiscale_params(db_path: Path = DB_PATH) -> list[FiscaleParams]:
    conn = await get_db(db_path)
    try:
        cursor = await conn.execute("SELECT * FROM fiscale_params ORDER BY jaar")
        rows = await cursor.fetchall()
        return [FiscaleParams(
            jaar=r['jaar'],
            zelfstandigenaftrek=r['zelfstandigenaftrek'],
            startersaftrek=r['startersaftrek'],
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
        ) for r in rows]
    finally:
        await conn.close()


async def upsert_fiscale_params(db_path: Path = DB_PATH, **kwargs) -> None:
    conn = await get_db(db_path)
    try:
        await conn.execute(
            """INSERT OR REPLACE INTO fiscale_params
               (jaar, zelfstandigenaftrek, startersaftrek, mkb_vrijstelling_pct,
                kia_ondergrens, kia_bovengrens, kia_pct, km_tarief,
                schijf1_grens, schijf1_pct, schijf2_grens, schijf2_pct, schijf3_pct,
                ahk_max, ahk_afbouw_pct, ahk_drempel, ak_max,
                zvw_pct, zvw_max_grondslag, repr_aftrek_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kwargs['jaar'], kwargs['zelfstandigenaftrek'], kwargs.get('startersaftrek'),
             kwargs['mkb_vrijstelling_pct'], kwargs['kia_ondergrens'],
             kwargs['kia_bovengrens'], kwargs['kia_pct'], kwargs['km_tarief'],
             kwargs['schijf1_grens'], kwargs['schijf1_pct'],
             kwargs['schijf2_grens'], kwargs['schijf2_pct'], kwargs['schijf3_pct'],
             kwargs['ahk_max'], kwargs['ahk_afbouw_pct'], kwargs['ahk_drempel'],
             kwargs['ak_max'], kwargs['zvw_pct'], kwargs['zvw_max_grondslag'],
             kwargs.get('repr_aftrek_pct', 80))
        )
        await conn.commit()
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

        # Kosten
        cur = await conn.execute(
            "SELECT COALESCE(SUM(bedrag), 0) FROM uitgaven "
            "WHERE substr(datum, 1, 4) = ?", (jaar_str,)
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
