from datetime import date

import pytest
import aiosqlite

import database
import services.agenda as svc
from database import ConflictError, ValidationError, YearLockedError


@pytest.fixture
async def db_with_klant(tmp_path):
    """Fresh DB with one klant."""
    db = tmp_path / 'test.sqlite3'
    await database.init_db(db)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO klanten (id, naam, tarief_uur) VALUES (1, 'HAP', 80)"
        )
        await conn.commit()
    return db


# ---- Pattern CRUD ----

@pytest.mark.asyncio
async def test_pattern_add_basic(db_with_klant):
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1, 3],
        start_minuten=480, eind_minuten=1020, code='WERKDAG',
    )
    assert pid > 0


@pytest.mark.asyncio
async def test_pattern_list_for_klant(db_with_klant):
    await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1, 3],
        start_minuten=480, eind_minuten=1020,
    )
    patterns = await svc.list_patterns_for_klant(db_with_klant, klant_id=1)
    assert len(patterns) == 1
    assert patterns[0].weekdays == [1, 3]
    assert patterns[0].code == 'WERKDAG'
    assert patterns[0].start_minuten == 480
    assert patterns[0].eind_minuten == 1020
    assert patterns[0].actief is True


@pytest.mark.asyncio
async def test_pattern_list_excludes_inactive_by_default(db_with_klant):
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    await svc.delete_pattern(db_with_klant, pid)  # soft-delete
    active = await svc.list_patterns_for_klant(db_with_klant, klant_id=1)
    assert active == []
    all_patterns = await svc.list_patterns_for_klant(
        db_with_klant, klant_id=1, include_inactive=True,
    )
    assert len(all_patterns) == 1
    assert all_patterns[0].actief is False


@pytest.mark.asyncio
async def test_pattern_invalid_weekdays_raises(db_with_klant):
    with pytest.raises(ValidationError):
        await svc.add_pattern(
            db_with_klant, klant_id=1, weekdays=[1, 8, 3],
            start_minuten=480, eind_minuten=1020,
        )


@pytest.mark.asyncio
async def test_pattern_empty_weekdays_raises(db_with_klant):
    with pytest.raises(ValidationError):
        await svc.add_pattern(
            db_with_klant, klant_id=1, weekdays=[],
            start_minuten=480, eind_minuten=1020,
        )


@pytest.mark.asyncio
async def test_pattern_duplicate_weekdays_raises(db_with_klant):
    with pytest.raises(ValidationError):
        await svc.add_pattern(
            db_with_klant, klant_id=1, weekdays=[1, 1, 3],
            start_minuten=480, eind_minuten=1020,
        )


@pytest.mark.asyncio
async def test_pattern_eind_before_start_raises(db_with_klant):
    with pytest.raises(ValidationError):
        await svc.add_pattern(
            db_with_klant, klant_id=1, weekdays=[1],
            start_minuten=1020, eind_minuten=480,
        )


@pytest.mark.asyncio
async def test_pattern_eind_equal_start_raises(db_with_klant):
    with pytest.raises(ValidationError):
        await svc.add_pattern(
            db_with_klant, klant_id=1, weekdays=[1],
            start_minuten=600, eind_minuten=600,
        )


@pytest.mark.asyncio
async def test_pattern_invalid_code_raises(db_with_klant):
    with pytest.raises(ValidationError):
        await svc.add_pattern(
            db_with_klant, klant_id=1, weekdays=[1],
            start_minuten=480, eind_minuten=1020, code='INVALID',
        )


@pytest.mark.asyncio
async def test_pattern_anw_code_accepted(db_with_klant):
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[5],
        start_minuten=1020, eind_minuten=1380,  # 17:00-23:00
        code='ANW_AVOND',
    )
    patterns = await svc.list_patterns_for_klant(db_with_klant, klant_id=1)
    assert patterns[0].code == 'ANW_AVOND'


@pytest.mark.asyncio
async def test_pattern_update_weekdays(db_with_klant):
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    await svc.update_pattern(db_with_klant, pid, weekdays=[1, 5])
    patterns = await svc.list_patterns_for_klant(db_with_klant, klant_id=1)
    assert patterns[0].weekdays == [1, 5]


@pytest.mark.asyncio
async def test_pattern_update_minuten(db_with_klant):
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    await svc.update_pattern(db_with_klant, pid, eind_minuten=990)
    patterns = await svc.list_patterns_for_klant(db_with_klant, klant_id=1)
    assert patterns[0].eind_minuten == 990


@pytest.mark.asyncio
async def test_pattern_update_eind_before_start_raises(db_with_klant):
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    with pytest.raises(ValidationError):
        await svc.update_pattern(db_with_klant, pid, eind_minuten=400)


@pytest.mark.asyncio
async def test_pattern_delete_soft(db_with_klant):
    """Delete = SET actief=0, behoud history."""
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    await svc.delete_pattern(db_with_klant, pid)
    # Row still exists in DB, just inactive
    pattern = await database.db_get_pattern(db_with_klant, pid)
    assert pattern is not None
    assert pattern.actief is False


@pytest.mark.asyncio
async def test_pattern_not_year_locked_can_modify_in_locked_year(db_with_klant):
    """Pattern modificaties zijn projectie-data — niet year-locked."""
    # Lock 2026
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (2026, 'definitief')"
        )
        await conn.commit()
    # Add pattern moet werken ook in locked jaar
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    assert pid > 0
    # Update + delete ook
    await svc.update_pattern(db_with_klant, pid, weekdays=[2])
    await svc.delete_pattern(db_with_klant, pid)


@pytest.mark.asyncio
async def test_pattern_cascade_on_klant_delete(db_with_klant):
    """When klant is deleted, patterns are CASCADE-deleted (DB-level)."""
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute("DELETE FROM klanten WHERE id = 1")
        await conn.commit()
    pattern = await database.db_get_pattern(db_with_klant, pid)
    assert pattern is None
