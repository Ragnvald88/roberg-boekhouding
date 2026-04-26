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


# === Factuur-link guard (Plan 2026-04-26 Lane 1, A2) ===

async def _seed_banktx_with_factuur_link(
    db_path, id_, datum, factuur_id=42, bedrag=120.0,
):
    """Bank-tx row pre-linked to a factuur via koppeling_type."""
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, koppeling_type, koppeling_id) "
            "VALUES (?, ?, ?, 'factuur', ?)",
            (id_, datum, bedrag, factuur_id))
        await conn.commit()


@pytest.mark.asyncio
async def test_mark_genegeerd_rejects_factuur_link(db):
    """Cannot mark a factuur-linked bank-tx as privé.

    Setting genegeerd=1 on a row matched to a factuur creates a silent
    inconsistency: the factuur still claims paid, but the bank-tx is
    invisible from /transacties. Reject at DB level.
    """
    await _seed_banktx_with_factuur_link(db, 1, "2026-05-01")
    with pytest.raises(ValueError, match='factuur'):
        await mark_banktx_genegeerd(db, 1, genegeerd=1)
    # Defensive: must not have flipped the flag despite raising.
    assert await _get_genegeerd(db, 1) == 0


@pytest.mark.asyncio
async def test_mark_genegeerd_allows_unset_when_factuur_linked(db):
    """Unsetting (genegeerd=0) on a factuur-linked row must still work.

    Use case: a row was flagged privé, then later linked to a factuur.
    User wants to undo the privé flag — that path must remain open so
    the inconsistency can be repaired.
    """
    await _seed_banktx_with_factuur_link(db, 1, "2026-05-01")
    # Force genegeerd=1 directly in DB (the function would now reject it).
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "UPDATE banktransacties SET genegeerd = 1 WHERE id = 1")
        await conn.commit()
    # The unset call must succeed.
    await mark_banktx_genegeerd(db, 1, genegeerd=0)
    assert await _get_genegeerd(db, 1) == 0
