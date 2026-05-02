import pytest
import aiosqlite

import database


@pytest.mark.asyncio
async def test_klant_recurring_patterns_table_exists(db):
    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='klant_recurring_patterns'"
        )
        row = await cur.fetchone()
    assert row is not None, "klant_recurring_patterns table missing"


@pytest.mark.asyncio
async def test_klant_recurring_patterns_has_required_columns(db):
    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute(
            "PRAGMA table_info(klant_recurring_patterns)"
        )
        cols = {row[1] for row in await cur.fetchall()}
    expected = {'id', 'klant_id', 'weekdays', 'start_minuten',
                'eind_minuten', 'code', 'activiteit',
                'valid_from', 'valid_until', 'actief'}
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


@pytest.mark.asyncio
async def test_klant_recurring_patterns_cascade_on_klant_delete(db):
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        cur = await conn.execute(
            "INSERT INTO klanten (naam, tarief_uur) VALUES ('Test', 80) RETURNING id"
        )
        klant_id = (await cur.fetchone())[0]
        await conn.execute(
            "INSERT INTO klant_recurring_patterns "
            "(klant_id, weekdays, start_minuten, eind_minuten) "
            "VALUES (?, '1,3', 480, 1020)",
            (klant_id,),
        )
        await conn.execute("DELETE FROM klanten WHERE id = ?", (klant_id,))
        await conn.commit()
        cur = await conn.execute(
            "SELECT COUNT(*) FROM klant_recurring_patterns"
        )
        count = (await cur.fetchone())[0]
    assert count == 0, "Cascade delete failed"


@pytest.mark.asyncio
async def test_klant_recurring_patterns_check_minuten_range(db):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO klanten (naam, tarief_uur) VALUES ('K', 80)"
        )
        # eind <= start should fail
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_recurring_patterns "
                "(klant_id, weekdays, start_minuten, eind_minuten) "
                "VALUES (1, '1', 600, 600)"
            )
            await conn.commit()


@pytest.mark.asyncio
async def test_blockers_table_exists(db):
    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='blockers'"
        )
        row = await cur.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_blockers_unique_datum_constraint(db):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO blockers (datum, kind, label) "
            "VALUES ('2026-05-21', 'training', 'NHG')"
        )
        await conn.commit()
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO blockers (datum, kind, label) "
                "VALUES ('2026-05-21', 'vacation', 'Holiday')"
            )
            await conn.commit()


@pytest.mark.asyncio
async def test_blockers_kind_check_constraint(db):
    async with aiosqlite.connect(db) as conn:
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO blockers (datum, kind) "
                "VALUES ('2026-05-21', 'holiday')"  # 'holiday' niet toegestaan
            )
            await conn.commit()


@pytest.fixture
async def db_with_werkdagen(db):
    """DB with klant + werkdagen + facturen for status testing."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        # Klant
        await conn.execute(
            "INSERT INTO klanten (id, naam, tarief_uur) VALUES (1, 'HAP', 80)"
        )
        # Concept factuur
        await conn.execute(
            "INSERT INTO facturen (nummer, klant_id, datum, totaal_bedrag, "
            "betaald, status) VALUES ('2026-001', 1, '2026-05-01', 800, 0, 'concept')"
        )
        # Verstuurde factuur (april — 14 dagen na 1 april = 15 april — verlopen vanaf 16 april)
        await conn.execute(
            "INSERT INTO facturen (nummer, klant_id, datum, totaal_bedrag, "
            "betaald, status) "
            "VALUES ('2026-002', 1, '2026-04-01', 800, 0, 'verstuurd')"
        )
        # Werkdagen
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, "
            "factuurnummer) VALUES (1, '2026-05-04', 1, 'WERKDAG', 10, 80, '2026-001')"
        )
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, "
            "factuurnummer) VALUES (2, '2026-04-04', 1, 'WERKDAG', 10, 80, '2026-002')"
        )
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, "
            "factuurnummer) VALUES (3, '2026-05-11', 1, 'WERKDAG', 10, 80, '')"
        )
        await conn.commit()
    return db


@pytest.mark.asyncio
async def test_get_werkdagen_met_factuur_status_returns_correct_status(db_with_werkdagen):
    rows = await database.get_werkdagen_met_factuur_status(
        str(db_with_werkdagen), 2026, 5
    )
    by_id = {r.id: r for r in rows}
    # mei: werkdag 1 (concept factuur) + werkdag 3 (ongefactureerd)
    assert by_id[1].factuur_status == 'concept'
    assert by_id[1].factuurnummer == '2026-001'
    assert by_id[1].factuur_datum == '2026-05-01'
    # vervaldatum is computed: 2026-05-01 + 14 dagen = 2026-05-15
    assert by_id[1].factuur_vervaldatum == '2026-05-15'
    assert by_id[3].factuur_status == ''
    assert by_id[3].factuurnummer == ''
    assert by_id[3].factuur_datum == ''
    assert by_id[3].factuur_vervaldatum == ''


@pytest.mark.asyncio
async def test_get_werkdagen_met_factuur_status_filters_by_month(db_with_werkdagen):
    rows = await database.get_werkdagen_met_factuur_status(
        str(db_with_werkdagen), 2026, 4
    )
    # Alleen werkdag 2 valt in april
    ids = {r.id for r in rows}
    assert ids == {2}
    by_id = {r.id: r for r in rows}
    # Werkdag 2 → factuur 2026-002 (verstuurd, datum 2026-04-01, vervaldatum 2026-04-15)
    assert by_id[2].factuur_status == 'verstuurd'
    assert by_id[2].factuur_datum == '2026-04-01'
    assert by_id[2].factuur_vervaldatum == '2026-04-15'
