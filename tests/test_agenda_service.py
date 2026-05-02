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
