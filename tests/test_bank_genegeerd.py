"""mark_banktx_genegeerd — toggle bank tx visibility in Kosten."""
import aiosqlite
import pytest
from database import (
    mark_banktx_genegeerd, update_jaarafsluiting_status, YearLockedError,
)


async def _seed_banktx(db_path, id_, datum, bedrag=-50.0):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag) VALUES (?, ?, ?)",
            (id_, datum, bedrag))
        await conn.commit()


async def _get_genegeerd(db_path, id_):
    async with aiosqlite.connect(db_path) as conn:
        cur = await conn.execute(
            "SELECT genegeerd FROM banktransacties WHERE id = ?", (id_,))
        return (await cur.fetchone())[0]


@pytest.mark.asyncio
async def test_mark_genegeerd_sets_flag(db):
    await _seed_banktx(db, 1, "2026-04-01")
    await mark_banktx_genegeerd(db, 1, genegeerd=1)
    assert await _get_genegeerd(db, 1) == 1


@pytest.mark.asyncio
async def test_mark_genegeerd_can_unset(db):
    await _seed_banktx(db, 1, "2026-04-01")
    await mark_banktx_genegeerd(db, 1, genegeerd=1)
    await mark_banktx_genegeerd(db, 1, genegeerd=0)
    assert await _get_genegeerd(db, 1) == 0


@pytest.mark.asyncio
async def test_mark_genegeerd_year_locked(db):
    async with aiosqlite.connect(db) as conn:
        await conn.execute("INSERT INTO fiscale_params (jaar) VALUES (2024)")
        await conn.commit()
    await update_jaarafsluiting_status(db, 2024, "definitief")
    await _seed_banktx(db, 1, "2024-06-01")
    with pytest.raises(YearLockedError):
        await mark_banktx_genegeerd(db, 1, genegeerd=1)


@pytest.mark.asyncio
async def test_mark_genegeerd_raises_for_unknown_id(db):
    with pytest.raises(ValueError):
        await mark_banktx_genegeerd(db, 999, genegeerd=1)


@pytest.mark.asyncio
async def test_mark_genegeerd_rejects_invalid_value(db):
    """Pins the validation that genegeerd must be 0 or 1, not e.g. 2 or -1."""
    await _seed_banktx(db, 1, "2026-04-01")
    with pytest.raises(ValueError):
        await mark_banktx_genegeerd(db, 1, genegeerd=2)
    with pytest.raises(ValueError):
        await mark_banktx_genegeerd(db, 1, genegeerd=-1)
