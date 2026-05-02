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
        db_with_werkdagen, 2026, 5
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
        db_with_werkdagen, 2026, 4
    )
    # Alleen werkdag 2 valt in april
    ids = {r.id for r in rows}
    assert ids == {2}
    by_id = {r.id: r for r in rows}
    # Werkdag 2 → factuur 2026-002 (verstuurd, datum 2026-04-01, vervaldatum 2026-04-15)
    assert by_id[2].factuur_status == 'verstuurd'
    assert by_id[2].factuur_datum == '2026-04-01'
    assert by_id[2].factuur_vervaldatum == '2026-04-15'


def test_werkdag_met_status_replace_clears_vervaldatum():
    """Regression: dataclasses.replace(factuur_datum='') must reset vervaldatum."""
    import dataclasses
    w1 = database.WerkdagMetStatus(
        id=1, datum='2026-05-04', klant_id=1, klant_naam='X',
        code='WERKDAG', activiteit='', uren=8, km=0, tarief=80, km_tarief=0.23,
        factuurnummer='2026-001', factuur_id=42,
        factuur_datum='2026-05-01', factuur_status='concept',
        factuur_betaald_datum='',
    )
    assert w1.factuur_vervaldatum == '2026-05-15'
    w2 = dataclasses.replace(w1, factuur_datum='2026-06-10')
    assert w2.factuur_vervaldatum == '2026-06-24'
    w3 = dataclasses.replace(w1, factuur_datum='')
    assert w3.factuur_vervaldatum == ''


def test_werkdag_met_status_factuur_vervaldatum_not_init_field():
    """factuur_vervaldatum is derived, not constructable directly."""
    import dataclasses
    fields = {f.name: f for f in dataclasses.fields(database.WerkdagMetStatus)}
    assert fields['factuur_vervaldatum'].init is False, \
        "factuur_vervaldatum must be init=False (derived field)"


@pytest.fixture
async def db_with_betaald_factuur(db):
    """DB with werkdag linked to a betaald factuur — for status='betaald' coverage."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute("INSERT INTO klanten (id, naam, tarief_uur) VALUES (1, 'HAP', 80)")
        await conn.execute(
            "INSERT INTO facturen (nummer, klant_id, datum, totaal_bedrag, "
            "betaald, status, betaald_datum) "
            "VALUES ('2026-003', 1, '2026-03-01', 800, 1, 'betaald', '2026-03-15')"
        )
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, factuurnummer) "
            "VALUES (10, '2026-03-04', 1, 'WERKDAG', 10, 80, '2026-003')"
        )
        await conn.commit()
    return db


@pytest.mark.asyncio
async def test_get_werkdagen_met_factuur_status_betaald(db_with_betaald_factuur):
    rows = await database.get_werkdagen_met_factuur_status(
        db_with_betaald_factuur, 2026, 3,
    )
    assert len(rows) == 1
    assert rows[0].factuur_status == 'betaald'
    assert rows[0].factuurnummer == '2026-003'


@pytest.fixture
async def db_with_orphan_factuurnummer(db):
    """DB where werkdag has a factuurnummer that points to a non-existing factuur."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute("INSERT INTO klanten (id, naam, tarief_uur) VALUES (1, 'HAP', 80)")
        # Werkdag with orphan factuurnummer (no matching factuur row)
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, factuurnummer) "
            "VALUES (20, '2026-07-04', 1, 'WERKDAG', 8, 80, '2026-DELETED')"
        )
        await conn.commit()
    return db


@pytest.mark.asyncio
async def test_get_werkdagen_met_factuur_status_orphan_factuurnummer(db_with_orphan_factuurnummer):
    """Orphan: werkdag.factuurnummer != '' but no matching factuur. Should still
    surface the werkdag with empty factuur_status (LEFT JOIN miss). UI logic
    must distinguish 'factuurnummer != "" AND factuur_status == ""' as orphan.
    Documents this contract."""
    rows = await database.get_werkdagen_met_factuur_status(
        db_with_orphan_factuurnummer, 2026, 7,
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.factuurnummer == '2026-DELETED'  # preserved
    assert r.factuur_status == ''             # LEFT JOIN miss
    assert r.factuur_datum == ''
    assert r.factuur_vervaldatum == ''


@pytest.fixture
async def db_with_multi_werkdagen_same_day(db):
    """Two werkdagen for the same klant on the same day."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute("INSERT INTO klanten (id, naam, tarief_uur) VALUES (1, 'HAP', 80)")
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, factuurnummer) "
            "VALUES (30, '2026-08-04', 1, 'WERKDAG', 4, 80, '')"
        )
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, factuurnummer) "
            "VALUES (31, '2026-08-04', 1, 'ANW_AVOND', 6, 90, '')"
        )
        await conn.commit()
    return db


@pytest.mark.asyncio
async def test_get_werkdagen_met_factuur_status_multiple_same_day(db_with_multi_werkdagen_same_day):
    """Schema toestaat 2+ werkdagen op zelfde datum/klant — both must be returned."""
    rows = await database.get_werkdagen_met_factuur_status(
        db_with_multi_werkdagen_same_day, 2026, 8,
    )
    assert len(rows) == 2
    assert {r.id for r in rows} == {30, 31}
    assert {r.code for r in rows} == {'WERKDAG', 'ANW_AVOND'}


@pytest.fixture
async def db_with_month_boundary_werkdagen(db):
    """Werkdagen on first/last day of month + adjacent months for boundary testing."""
    async with aiosqlite.connect(db) as conn:
        await conn.execute("INSERT INTO klanten (id, naam, tarief_uur) VALUES (1, 'HAP', 80)")
        # December 2026 boundary
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, factuurnummer) "
            "VALUES (40, '2026-12-01', 1, 'WERKDAG', 8, 80, '')"
        )
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, factuurnummer) "
            "VALUES (41, '2026-12-31', 1, 'WERKDAG', 8, 80, '')"
        )
        # January 2027 (must NOT be in december query)
        await conn.execute(
            "INSERT INTO werkdagen (id, datum, klant_id, code, uren, tarief, factuurnummer) "
            "VALUES (42, '2027-01-01', 1, 'WERKDAG', 8, 80, '')"
        )
        await conn.commit()
    return db


@pytest.mark.asyncio
async def test_get_werkdagen_met_factuur_status_december_boundary(db_with_month_boundary_werkdagen):
    """December query includes 1st AND 31st, excludes 2027-01-01."""
    rows = await database.get_werkdagen_met_factuur_status(
        db_with_month_boundary_werkdagen, 2026, 12,
    )
    assert {r.id for r in rows} == {40, 41}


@pytest.mark.asyncio
async def test_get_werkdagen_met_factuur_status_january_boundary(db_with_month_boundary_werkdagen):
    """January 2027 query includes 2027-01-01, excludes 2026-12-* rows."""
    rows = await database.get_werkdagen_met_factuur_status(
        db_with_month_boundary_werkdagen, 2027, 1,
    )
    assert {r.id for r in rows} == {42}
