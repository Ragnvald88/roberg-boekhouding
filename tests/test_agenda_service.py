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
    assert patterns[0].weekdays == (1, 3)
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
    assert patterns[0].weekdays == (1, 5)


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


# ---- Review-fix regression tests (C2/C1/I1) ----

def test_services_agenda_no_nicegui_import():
    """C2 boundary: services.agenda must not transitively pull nicegui — UI-free invariant."""
    import importlib
    import sys
    # Snapshot existing modules to detect what services.agenda imports
    pre = set(sys.modules.keys())
    # Force re-import
    if 'services.agenda' in sys.modules:
        del sys.modules['services.agenda']
    importlib.import_module('services.agenda')
    new_modules = set(sys.modules.keys()) - pre
    nicegui_modules = [m for m in new_modules if m.startswith('nicegui')]
    assert not nicegui_modules, (
        f"services.agenda transitively imports nicegui: {nicegui_modules}"
    )


@pytest.mark.asyncio
async def test_pattern_update_weekdays_string_input_is_validated(db_with_klant):
    """C1 regression: string weekdays must be validated, not bypass."""
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    with pytest.raises(ValidationError):
        await svc.update_pattern(db_with_klant, pid, weekdays='1,8,99')


@pytest.mark.asyncio
async def test_pattern_update_weekdays_string_csv_accepted(db_with_klant):
    """Valid CSV string is accepted and parsed."""
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    await svc.update_pattern(db_with_klant, pid, weekdays='2,4')
    patterns = await svc.list_patterns_for_klant(db_with_klant, klant_id=1)
    assert patterns[0].weekdays == (2, 4)  # tuple after I2 fix


@pytest.mark.asyncio
async def test_pattern_update_weekdays_invalid_type_raises(db_with_klant):
    """Non-list/non-str raises ValidationError, not silent corruption."""
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    with pytest.raises(ValidationError):
        await svc.update_pattern(db_with_klant, pid, weekdays=42)


@pytest.mark.asyncio
async def test_pattern_update_weekdays_tuple_input_accepted(db_with_klant):
    """Round-trip Pattern.weekdays (tuple) back into update_pattern must work."""
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    patterns = await svc.list_patterns_for_klant(db_with_klant, klant_id=1)
    # Take the existing tuple weekdays and pass back unchanged
    await svc.update_pattern(db_with_klant, pid, weekdays=patterns[0].weekdays)
    # And with a new tuple
    await svc.update_pattern(db_with_klant, pid, weekdays=(2, 6))
    patterns = await svc.list_patterns_for_klant(db_with_klant, klant_id=1)
    assert patterns[0].weekdays == (2, 6)


@pytest.mark.asyncio
async def test_pattern_update_unknown_field_raises(db_with_klant):
    """I1: typos surface as ValueError, not silent OperationalError."""
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1],
        start_minuten=480, eind_minuten=1020,
    )
    with pytest.raises(ValueError):  # database.py raises ValueError directly
        await database.db_update_pattern(db_with_klant, pid, eind_minute=900)  # typo


# ---- Blocker CRUD + holiday-merge ----

@pytest.mark.asyncio
async def test_add_blocker_basic(db_with_klant):
    bid = await svc.add_blocker(
        db_with_klant, datum=date(2026, 7, 15),
        kind='vacation', label='Zomervakantie',
    )
    assert bid > 0


@pytest.mark.asyncio
async def test_add_blocker_holiday_kind_raises(db_with_klant):
    """'holiday' is computed-only, niet user-toevoegbaar."""
    with pytest.raises(ValidationError):
        await svc.add_blocker(
            db_with_klant, datum=date(2026, 7, 15),
            kind='holiday', label='X',
        )


@pytest.mark.asyncio
async def test_add_blocker_invalid_kind_raises(db_with_klant):
    with pytest.raises(ValidationError):
        await svc.add_blocker(
            db_with_klant, datum=date(2026, 7, 15),
            kind='party', label='X',
        )


@pytest.mark.asyncio
async def test_add_blocker_duplicate_datum_raises(db_with_klant):
    """UNIQUE(datum) — second insert raises ConflictError."""
    await svc.add_blocker(
        db_with_klant, datum=date(2026, 7, 15),
        kind='vacation', label='A',
    )
    with pytest.raises(ConflictError):
        await svc.add_blocker(
            db_with_klant, datum=date(2026, 7, 15),
            kind='sick', label='B',
        )


@pytest.mark.asyncio
async def test_add_blocker_on_existing_werkdag_raises(db_with_klant):
    """Werkdag already exists on date → ConflictError."""
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief) "
            "VALUES ('2026-07-15', 1, 'WERKDAG', 8, 80)"
        )
        await conn.commit()
    with pytest.raises(ConflictError):
        await svc.add_blocker(
            db_with_klant, datum=date(2026, 7, 15),
            kind='vacation', label='X',
        )


@pytest.mark.asyncio
async def test_add_blocker_in_locked_year_raises(db_with_klant):
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (2025, 'definitief')"
        )
        await conn.commit()
    with pytest.raises(YearLockedError):
        await svc.add_blocker(
            db_with_klant, datum=date(2025, 7, 15),
            kind='vacation', label='X',
        )


@pytest.mark.asyncio
async def test_delete_blocker_basic(db_with_klant):
    bid = await svc.add_blocker(
        db_with_klant, datum=date(2026, 7, 15),
        kind='vacation', label='X',
    )
    await svc.delete_blocker(db_with_klant, bid)
    blockers = await svc.list_blockers(
        db_with_klant, vanaf=date(2026, 7, 1), tot=date(2026, 7, 31),
    )
    user_blockers = [b for b in blockers if b.kind != 'holiday']
    assert user_blockers == []


@pytest.mark.asyncio
async def test_delete_blocker_in_locked_year_raises(db_with_klant):
    bid = await svc.add_blocker(
        db_with_klant, datum=date(2026, 7, 15),
        kind='vacation', label='X',
    )
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (2026, 'definitief')"
        )
        await conn.commit()
    with pytest.raises(YearLockedError):
        await svc.delete_blocker(db_with_klant, bid)


@pytest.mark.asyncio
async def test_delete_blocker_missing_id_silent(db_with_klant):
    """Delete on non-existing id is silent no-op (idempotent)."""
    await svc.delete_blocker(db_with_klant, 99999)
    # No exception expected.


@pytest.mark.asyncio
async def test_list_blockers_includes_holidays(db_with_klant):
    """Computed dutch_holidays are merged into list_blockers result."""
    blockers = await svc.list_blockers(
        db_with_klant, vanaf=date(2026, 4, 1), tot=date(2026, 4, 30),
    )
    holiday_dates = {b.datum for b in blockers if b.kind == 'holiday'}
    # April 2026: Goede Vrijdag (3 apr), Eerste Paasdag (5 apr),
    # Tweede Paasdag (6 apr), Koningsdag (27 apr).
    assert date(2026, 4, 3) in holiday_dates
    assert date(2026, 4, 5) in holiday_dates
    assert date(2026, 4, 6) in holiday_dates
    assert date(2026, 4, 27) in holiday_dates


@pytest.mark.asyncio
async def test_list_blockers_user_blocker_with_holiday_same_date(db_with_klant):
    """User-blocker on holiday-datum is allowed; both surface in list_blockers,
    UI-laag decides which to show."""
    # Add user-blocker on Koningsdag 2026 (27 april)
    await svc.add_blocker(
        db_with_klant, datum=date(2026, 4, 27),
        kind='vacation', label='Vrije dag',
    )
    blockers = await svc.list_blockers(
        db_with_klant, vanaf=date(2026, 4, 27), tot=date(2026, 4, 27),
    )
    # Both should be present
    kinds = sorted(b.kind for b in blockers)
    assert 'holiday' in kinds
    assert 'vacation' in kinds


@pytest.mark.asyncio
async def test_list_blockers_year_range_spans_years(db_with_klant):
    """Range covering 2025-12-25 to 2026-01-02 includes holidays from both years."""
    blockers = await svc.list_blockers(
        db_with_klant, vanaf=date(2025, 12, 25), tot=date(2026, 1, 2),
    )
    holiday_dates = {b.datum for b in blockers if b.kind == 'holiday'}
    assert date(2025, 12, 25) in holiday_dates  # Eerste Kerstdag
    assert date(2025, 12, 26) in holiday_dates  # Tweede Kerstdag
    assert date(2026, 1, 1) in holiday_dates    # Nieuwjaarsdag


# ---- confirm_expected ----

async def _add_test_pattern(db, klant_id=1, code='WERKDAG'):
    return await svc.add_pattern(
        db, klant_id=klant_id, weekdays=[1, 3],  # Ma, Wo
        start_minuten=480, eind_minuten=1020, code=code,
    )


@pytest.mark.asyncio
async def test_confirm_expected_creates_werkdag(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    # 4 mei 2026 = maandag
    werkdag_id = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
    )
    assert werkdag_id > 0
    async with aiosqlite.connect(db_with_klant) as conn:
        cur = await conn.execute(
            "SELECT klant_id, code, uren, urennorm FROM werkdagen WHERE id = ?",
            (werkdag_id,),
        )
        row = await cur.fetchone()
    assert row[0] == 1
    assert row[1] == 'WERKDAG'
    assert row[2] == pytest.approx(9.0)  # 480→1020 = 540 min = 9u
    assert row[3] == 1  # urennorm=1 voor WERKDAG


@pytest.mark.asyncio
async def test_confirm_expected_idempotent(db_with_klant):
    """Second call met zelfde (klant, datum) returnt zelfde werkdag-id."""
    pid = await _add_test_pattern(db_with_klant)
    id1 = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
    )
    id2 = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
    )
    assert id1 == id2
    # En slechts 1 werkdag in DB
    async with aiosqlite.connect(db_with_klant) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM werkdagen")
        count = (await cur.fetchone())[0]
    assert count == 1


@pytest.mark.asyncio
async def test_confirm_expected_with_overrides(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    werkdag_id = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
        start_minuten=540, eind_minuten=1080,  # 09:00-18:00 = 9u
    )
    async with aiosqlite.connect(db_with_klant) as conn:
        cur = await conn.execute(
            "SELECT uren FROM werkdagen WHERE id = ?", (werkdag_id,),
        )
        uren = (await cur.fetchone())[0]
    assert uren == pytest.approx(9.0)


@pytest.mark.asyncio
async def test_confirm_expected_in_locked_year_raises(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, jaarafsluiting_status) "
            "VALUES (2025, 'definitief')"
        )
        await conn.commit()
    with pytest.raises(YearLockedError):
        await svc.confirm_expected(
            db_with_klant, pattern_id=pid, datum=date(2025, 6, 2),
        )


@pytest.mark.asyncio
async def test_confirm_expected_on_deleted_pattern_raises(db_with_klant):
    """Race-protection: pattern verwijderd tussen render en confirm → ConflictError."""
    pid = await _add_test_pattern(db_with_klant)
    await svc.delete_pattern(db_with_klant, pid)
    with pytest.raises(ConflictError):
        await svc.confirm_expected(
            db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
        )


@pytest.mark.asyncio
async def test_confirm_expected_on_missing_pattern_raises(db_with_klant):
    """Pattern_id that never existed → ConflictError."""
    with pytest.raises(ConflictError):
        await svc.confirm_expected(
            db_with_klant, pattern_id=999, datum=date(2026, 5, 4),
        )


@pytest.mark.asyncio
async def test_confirm_expected_invalid_minuten_raises(db_with_klant):
    pid = await _add_test_pattern(db_with_klant)
    with pytest.raises(ValidationError):
        await svc.confirm_expected(
            db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
            start_minuten=600, eind_minuten=400,  # eind < start
        )


@pytest.mark.asyncio
async def test_confirm_expected_anw_pattern_keeps_anw_code(db_with_klant):
    """Pattern code='ANW_AVOND' propagates to werkdag.code."""
    pid = await _add_test_pattern(db_with_klant, code='ANW_AVOND')
    werkdag_id = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
    )
    async with aiosqlite.connect(db_with_klant) as conn:
        cur = await conn.execute(
            "SELECT code, urennorm FROM werkdagen WHERE id = ?", (werkdag_id,),
        )
        row = await cur.fetchone()
    assert row[0] == 'ANW_AVOND'
    assert row[1] == 1  # ANW telt voor urencriterium


@pytest.mark.asyncio
async def test_confirm_expected_achterwacht_urennorm_zero(db_with_klant):
    """ACHTERWACHT pattern → urennorm=0 (telt niet voor 1225)."""
    pid = await _add_test_pattern(db_with_klant, code='ACHTERWACHT')
    werkdag_id = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
    )
    async with aiosqlite.connect(db_with_klant) as conn:
        cur = await conn.execute(
            "SELECT urennorm FROM werkdagen WHERE id = ?", (werkdag_id,),
        )
        row = await cur.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_confirm_expected_congres_urennorm_zero(db_with_klant):
    """CONGRES (in ZERO_UREN_CODES) → urennorm=0."""
    pid = await _add_test_pattern(db_with_klant, code='CONGRES')
    werkdag_id = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
    )
    async with aiosqlite.connect(db_with_klant) as conn:
        cur = await conn.execute(
            "SELECT urennorm FROM werkdagen WHERE id = ?", (werkdag_id,),
        )
        row = await cur.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_confirm_expected_on_existing_blocker_raises(db_with_klant):
    """Defense-in-depth: blocker on date prevents confirm_expected."""
    pid = await _add_test_pattern(db_with_klant)
    await svc.add_blocker(
        db_with_klant, datum=date(2026, 5, 4),
        kind='vacation', label='Vrije dag',
    )
    with pytest.raises(ConflictError):
        await svc.confirm_expected(
            db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
        )


@pytest.mark.asyncio
async def test_confirm_expected_uses_current_klant_tarief_not_pattern_creation_value(db_with_klant):
    """Klant-tarief change after pattern creation: confirm uses NEW tarief."""
    pid = await _add_test_pattern(db_with_klant)
    # Pattern created when klant.tarief_uur=80. Now change klant tarief to 95.
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "UPDATE klanten SET tarief_uur = 95, retour_km = 30, "
            "adres = 'Nieuwe Lokatie' WHERE id = 1"
        )
        await conn.commit()
    werkdag_id = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
    )
    async with aiosqlite.connect(db_with_klant) as conn:
        cur = await conn.execute(
            "SELECT tarief, km, locatie FROM werkdagen WHERE id = ?",
            (werkdag_id,),
        )
        row = await cur.fetchone()
    # Werkdag uses CURRENT klant data, not pattern-creation snapshot
    assert row[0] == 95.0
    assert row[1] == 30.0
    assert row[2] == 'Nieuwe Lokatie'


@pytest.mark.asyncio
async def test_confirm_expected_returns_existing_werkdag_with_different_code(db_with_klant):
    """Idempotency contract: any existing werkdag for (klant, datum) suffices,
    regardless of pattern code."""
    pid = await _add_test_pattern(db_with_klant, code='WERKDAG')
    # Manually add a werkdag with different code
    async with aiosqlite.connect(db_with_klant) as conn:
        cur = await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief) "
            "VALUES ('2026-05-04', 1, 'ANW_AVOND', 6, 90) RETURNING id"
        )
        manual_id = (await cur.fetchone())[0]
        await conn.commit()
    # Confirm via WERKDAG pattern → returns the existing ANW row
    confirmed_id = await svc.confirm_expected(
        db_with_klant, pattern_id=pid, datum=date(2026, 5, 4),
    )
    assert confirmed_id == manual_id
    # Werkdag NOT mutated — still has ANW code
    async with aiosqlite.connect(db_with_klant) as conn:
        cur = await conn.execute(
            "SELECT code FROM werkdagen WHERE id = ?", (manual_id,),
        )
        code = (await cur.fetchone())[0]
    assert code == 'ANW_AVOND'


# ---- get_maand / get_dag ----

@pytest.fixture
def fake_today_2026_05_01(monkeypatch):
    """Pin today to 2026-05-01 (Friday) for deterministic expected-entry tests."""
    monkeypatch.setattr(svc, '_today', lambda: date(2026, 5, 1))


@pytest.mark.asyncio
async def test_get_maand_returns_correct_structure(db_with_klant, fake_today_2026_05_01):
    pid = await _add_test_pattern(db_with_klant)  # weekdays=[1,3], 480-1020
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    assert view.jaar == 2026
    assert view.maand == 5
    assert len(view.dagen) == 31  # mei 2026 has 31 days
    assert all(d.datum.year == 2026 and d.datum.month == 5 for d in view.dagen)


@pytest.mark.asyncio
async def test_get_maand_expected_only_for_future_dates(db_with_klant, fake_today_2026_05_01):
    """Today=2026-05-01 (vrijdag). Pattern op Ma+Wo. Expected entries alleen
    voor dagen >= today+1 (toekomst)."""
    pid = await _add_test_pattern(db_with_klant)  # Ma+Wo
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    by_date = {d.datum: d for d in view.dagen}
    # Maandag 4 mei (toekomst, Ma) — expected aanwezig
    assert len(by_date[date(2026, 5, 4)].expected) == 1
    # Maandag 27 april valt buiten mei
    # Vrijdag 1 mei (today) — geen expected (today is niet toekomst)
    assert by_date[date(2026, 5, 1)].expected == ()
    # Donderdag 7 mei — Pattern niet op Do, dus geen expected
    assert by_date[date(2026, 5, 7)].expected == ()


@pytest.mark.asyncio
async def test_get_maand_expected_blocked_by_existing_werkdag(db_with_klant, fake_today_2026_05_01):
    """Werkdag op datum onderdrukt expected entry op die datum."""
    pid = await _add_test_pattern(db_with_klant)
    # Werkdag op 4 mei (Ma) — pattern-day
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief) "
            "VALUES ('2026-05-04', 1, 'WERKDAG', 9, 80)"
        )
        await conn.commit()
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    by_date = {d.datum: d for d in view.dagen}
    dag = by_date[date(2026, 5, 4)]
    assert len(dag.werkdagen) == 1
    assert dag.expected == ()  # onderdrukt door werkdag


@pytest.mark.asyncio
async def test_get_maand_expected_blocked_by_blocker(db_with_klant, fake_today_2026_05_01):
    """Blocker op datum onderdrukt expected entry."""
    pid = await _add_test_pattern(db_with_klant)
    await svc.add_blocker(
        db_with_klant, datum=date(2026, 5, 4),
        kind='vacation', label='Vrije dag',
    )
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    by_date = {d.datum: d for d in view.dagen}
    dag = by_date[date(2026, 5, 4)]
    assert dag.expected == ()
    assert dag.blocker is not None
    assert dag.blocker.kind == 'vacation'


@pytest.mark.asyncio
async def test_get_maand_expected_blocked_by_holiday(db_with_klant, fake_today_2026_05_01):
    """Computed holiday onderdrukt expected entry."""
    pid = await _add_test_pattern(db_with_klant)  # Ma+Wo, dus 27-april (Ma=Koningsdag) match
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=4)
    by_date = {d.datum: d for d in view.dagen}
    koningsdag = by_date[date(2026, 4, 27)]
    assert koningsdag.expected == ()
    assert koningsdag.blocker is not None
    assert koningsdag.blocker.kind == 'holiday'


@pytest.mark.asyncio
async def test_get_maand_returns_factuur_status_per_werkdag(db_with_klant, fake_today_2026_05_01):
    """Kern-feature: factuur-status zichtbaar per werkdag in MaandView."""
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO facturen (nummer, klant_id, datum, totaal_bedrag, "
            "betaald, status) VALUES ('2026-001', 1, '2026-05-04', 800, 0, 'concept')"
        )
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief, factuurnummer) "
            "VALUES ('2026-05-04', 1, 'WERKDAG', 8, 80, '2026-001')"
        )
        await conn.commit()
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    by_date = {d.datum: d for d in view.dagen}
    pill = by_date[date(2026, 5, 4)].werkdagen[0]
    assert pill.factuur_status == 'concept'
    assert pill.status_label == 'concept'
    assert pill.category == 'dagpraktijk'
    assert pill.bedrag == pytest.approx(8 * 80)


@pytest.mark.asyncio
async def test_get_maand_anw_werkdag_categorized_correctly(db_with_klant, fake_today_2026_05_01):
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief) "
            "VALUES ('2026-05-04', 1, 'ANW_AVOND', 6, 90)"
        )
        await conn.commit()
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    by_date = {d.datum: d for d in view.dagen}
    pill = by_date[date(2026, 5, 4)].werkdagen[0]
    assert pill.category == 'anw'


@pytest.mark.asyncio
async def test_get_maand_include_expected_false_returns_empty_expected(db_with_klant, fake_today_2026_05_01):
    pid = await _add_test_pattern(db_with_klant)
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5, include_expected=False)
    for dag in view.dagen:
        assert dag.expected == ()


@pytest.mark.asyncio
async def test_get_dag_returns_single_day(db_with_klant, fake_today_2026_05_01):
    pid = await _add_test_pattern(db_with_klant)
    dag = await svc.get_dag(db_with_klant, datum=date(2026, 5, 4))
    assert dag.datum == date(2026, 5, 4)
    assert len(dag.expected) == 1
    assert dag.expected[0].pattern_id == pid


@pytest.mark.asyncio
async def test_get_dag_blocker(db_with_klant, fake_today_2026_05_01):
    await svc.add_blocker(
        db_with_klant, datum=date(2026, 7, 15),
        kind='vacation', label='Zomer',
    )
    dag = await svc.get_dag(db_with_klant, datum=date(2026, 7, 15))
    assert dag.blocker is not None
    assert dag.blocker.kind == 'vacation'


@pytest.mark.asyncio
async def test_get_maand_expected_uses_klant_tarief(db_with_klant, fake_today_2026_05_01):
    """ExpectedEntry.bedrag computes from klant.tarief_uur (current value)."""
    pid = await _add_test_pattern(db_with_klant)  # 480-1020 = 9u
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    by_date = {d.datum: d for d in view.dagen}
    expected = by_date[date(2026, 5, 4)].expected[0]
    assert expected.uren == pytest.approx(9.0)
    assert expected.klant_naam == 'HAP'
    assert expected.code == 'WERKDAG'


@pytest.mark.asyncio
async def test_get_maand_pattern_validity_window(db_with_klant, fake_today_2026_05_01):
    """Pattern with valid_until in past should NOT generate expected."""
    pid = await svc.add_pattern(
        db_with_klant, klant_id=1, weekdays=[1, 3],
        start_minuten=480, eind_minuten=1020,
        valid_until='2026-04-30',  # only valid until april
    )
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    for dag in view.dagen:
        assert dag.expected == ()  # pattern expired


@pytest.mark.asyncio
async def test_get_maand_inactive_klant_no_expected(db_with_klant, fake_today_2026_05_01):
    """Codex B1: gedeactiveerde klanten mogen geen expected genereren,
    ook al hebben ze nog actieve patterns."""
    pid = await _add_test_pattern(db_with_klant)  # Ma+Wo
    # Deactiveer klant
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute("UPDATE klanten SET actief = 0 WHERE id = 1")
        await conn.commit()
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    for dag in view.dagen:
        assert dag.expected == ()  # geen expected van inactive klanten


@pytest.mark.asyncio
async def test_get_maand_expected_includes_km_vergoeding(db_with_klant, fake_today_2026_05_01):
    """Codex B2: ExpectedEntry.bedrag = uren*tarief + retour_km*0.23
    (consistent met confirm_expected → add_werkdag)."""
    # Klant heeft retour_km=40
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute("UPDATE klanten SET retour_km = 40 WHERE id = 1")
        await conn.commit()
    pid = await _add_test_pattern(db_with_klant)  # 9u, tarief=80
    view = await svc.get_maand(db_with_klant, jaar=2026, maand=5)
    by_date = {d.datum: d for d in view.dagen}
    expected = by_date[date(2026, 5, 4)].expected[0]
    # 9 * 80 + 40 * 0.23 = 720 + 9.20 = 729.20
    assert expected.bedrag == pytest.approx(9 * 80 + 40 * 0.23)


# ---- 6-weken prognose ----

@pytest.mark.asyncio
async def test_zes_weken_prognose_returns_6_weeks(db_with_klant, fake_today_2026_05_01):
    pid = await _add_test_pattern(db_with_klant)
    weeks = await svc.get_zes_weken_prognose(
        db_with_klant, vanaf=date(2026, 5, 13),
    )
    assert len(weeks) == 6
    # Eerste week start op de Maandag van vanaf-week (11 mei)
    assert weeks[0].week_start == date(2026, 5, 11)
    assert weeks[0].week_nummer == 20  # ISO week 20
    # Laatste week begint 6 weken later
    assert weeks[5].week_start == date(2026, 6, 15)


@pytest.mark.asyncio
async def test_zes_weken_prognose_aggregates_expected(db_with_klant, fake_today_2026_05_01):
    """Pattern Ma+Wo, 9u/dag, klant.tarief_uur=80 -> expected per week:
    2 dagen x 9u x 80EUR = 1440EUR."""
    pid = await _add_test_pattern(db_with_klant)
    weeks = await svc.get_zes_weken_prognose(
        db_with_klant, vanaf=date(2026, 5, 13),
    )
    # Week 20 (11-17 mei): Ma 11 mei + Wo 13 mei - beide toekomstig vanaf today=1 mei
    w0 = weeks[0]
    # confirmed = 0, planned irrelevant in deze app, expected = 2 dagen
    assert w0.expected_dagen == 2
    assert w0.expected_uren == pytest.approx(18.0)


@pytest.mark.asyncio
async def test_zes_weken_prognose_includes_confirmed_werkdagen(db_with_klant, fake_today_2026_05_01):
    """Bevestigde werkdagen in toekomst tellen als confirmed."""
    async with aiosqlite.connect(db_with_klant) as conn:
        # Werkdag op 13 mei 2026 (week 20) - toekomstig
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief, urennorm) "
            "VALUES ('2026-05-13', 1, 'WERKDAG', 9, 80, 1)"
        )
        await conn.commit()
    weeks = await svc.get_zes_weken_prognose(
        db_with_klant, vanaf=date(2026, 5, 13),
    )
    w0 = weeks[0]
    assert w0.confirmed_uren == pytest.approx(9.0)
    assert w0.confirmed_amt == pytest.approx(720.0)


@pytest.mark.asyncio
async def test_zes_weken_prognose_blocker_counted(db_with_klant, fake_today_2026_05_01):
    """Blocker dagen in week-bereik tellen als blocked_dagen."""
    await svc.add_blocker(
        db_with_klant, datum=date(2026, 5, 14),
        kind='vacation', label='Vakantie',
    )
    weeks = await svc.get_zes_weken_prognose(
        db_with_klant, vanaf=date(2026, 5, 13),
    )
    # Week 20 (11-17 mei): 14 mei is blocker
    w0 = weeks[0]
    assert w0.blocked_dagen >= 1


# ---- urencriterium-projectie ----

@pytest.mark.asyncio
async def test_urencriterium_projectie_basic(db_with_klant, monkeypatch):
    """Bevestigde uren YTD + verwachte uren tot jaar-eind."""
    # Pin today to 13 mei 2026 — patch via svc reference (same module object
    # used by get_urencriterium_projectie via globals lookup).
    monkeypatch.setattr(svc, '_today', lambda: date(2026, 5, 13))
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief, urennorm) "
            "VALUES ('2026-04-15', 1, 'WERKDAG', 8, 80, 1)"
        )
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief, urennorm) "
            "VALUES ('2026-04-22', 1, 'WERKDAG', 9, 80, 1)"
        )
        await conn.commit()
    state = await svc.get_urencriterium_projectie(db_with_klant, jaar=2026)
    assert state.confirmed_uren == pytest.approx(17.0)
    assert state.target == 1225.0
    assert state.jaar == 2026


@pytest.mark.asyncio
async def test_urencriterium_excludes_urennorm_zero(db_with_klant, monkeypatch):
    """ACHTERWACHT/CONGRES (urennorm=0) telt NIET mee voor 1225-eis."""
    monkeypatch.setattr(svc, '_today', lambda: date(2026, 5, 13))
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief, urennorm) "
            "VALUES ('2026-04-15', 1, 'ACHTERWACHT', 12, 0, 0)"
        )
        await conn.commit()
    state = await svc.get_urencriterium_projectie(db_with_klant, jaar=2026)
    assert state.confirmed_uren == 0.0


@pytest.mark.asyncio
async def test_urencriterium_uses_fiscale_params_target_if_present(db_with_klant, monkeypatch):
    """Custom urencriterium uit fiscale_params overrules default 1225."""
    monkeypatch.setattr(svc, '_today', lambda: date(2026, 5, 13))
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar, urencriterium) VALUES (2026, 1500)"
        )
        await conn.commit()
    state = await svc.get_urencriterium_projectie(db_with_klant, jaar=2026)
    assert state.target == 1500.0


@pytest.mark.asyncio
async def test_urencriterium_will_make_true_if_projected_above_target(db_with_klant, monkeypatch):
    monkeypatch.setattr(svc, '_today', lambda: date(2026, 12, 30))
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief, urennorm) "
            "VALUES ('2026-06-01', 1, 'WERKDAG', 1300, 80, 1)"
        )
        await conn.commit()
    state = await svc.get_urencriterium_projectie(db_with_klant, jaar=2026)
    assert state.confirmed_uren == 1300.0
    assert state.will_make is True


@pytest.mark.asyncio
async def test_urencriterium_will_make_false_if_short(db_with_klant, monkeypatch):
    monkeypatch.setattr(svc, '_today', lambda: date(2026, 12, 30))
    async with aiosqlite.connect(db_with_klant) as conn:
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, code, uren, tarief, urennorm) "
            "VALUES ('2026-06-01', 1, 'WERKDAG', 500, 80, 1)"
        )
        await conn.commit()
    state = await svc.get_urencriterium_projectie(db_with_klant, jaar=2026)
    assert state.confirmed_uren == 500.0
    assert state.will_make is False


@pytest.mark.asyncio
async def test_urencriterium_pace_pct_at_year_start(db_with_klant, monkeypatch):
    """Pace=day-of-year/365 * 100. Beginning of year ~= 0%."""
    monkeypatch.setattr(svc, '_today', lambda: date(2026, 1, 1))
    state = await svc.get_urencriterium_projectie(db_with_klant, jaar=2026)
    assert state.pace_pct < 1.0  # day 1 / 365 ~= 0.27%


@pytest.mark.asyncio
async def test_urencriterium_pace_pct_at_year_end(db_with_klant, monkeypatch):
    """End of year ~= 100%."""
    monkeypatch.setattr(svc, '_today', lambda: date(2026, 12, 31))
    state = await svc.get_urencriterium_projectie(db_with_klant, jaar=2026)
    assert state.pace_pct == pytest.approx(100.0, abs=0.5)
