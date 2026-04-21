"""ensure_uitgave_for_banktx — idempotent lazy-create, year-locked."""
import aiosqlite
import pytest
from database import (
    ensure_uitgave_for_banktx, get_uitgaven,
    update_jaarafsluiting_status, YearLockedError,
)


async def _seed_banktx(db_path, id_: int, datum: str, bedrag: float,
                        tegenpartij: str = "KPN B.V.",
                        omschrijving: str = "abo") -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij, omschrijving) "
            "VALUES (?, ?, ?, ?, ?)",
            (id_, datum, bedrag, tegenpartij, omschrijving))
        await conn.commit()


async def _seed_fiscale_params(db_path, jaar: int) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar) VALUES (?)", (jaar,))
        await conn.commit()


@pytest.mark.asyncio
async def test_ensure_creates_new_when_absent(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    uitgave_id = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    assert uitgave_id > 0
    uitgaven = await get_uitgaven(db, jaar=2026)
    u = next(u for u in uitgaven if u.id == uitgave_id)
    assert u.datum == "2026-04-01"
    assert u.bedrag == 120.87  # ABS of bank_tx.bedrag
    assert u.omschrijving == "KPN B.V."  # defaults to tegenpartij
    assert u.categorie == ""  # caller fills in


@pytest.mark.asyncio
async def test_ensure_is_idempotent(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    first = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    second = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    assert first == second


@pytest.mark.asyncio
async def test_ensure_accepts_overrides(db):
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    uid = await ensure_uitgave_for_banktx(
        db, bank_tx_id=1, categorie="Telefoon/KPN")
    uitgaven = await get_uitgaven(db, jaar=2026)
    u = next(u for u in uitgaven if u.id == uid)
    assert u.categorie == "Telefoon/KPN"


@pytest.mark.asyncio
async def test_ensure_falls_back_to_omschrijving_when_tegenpartij_empty(db):
    await _seed_banktx(db, 1, "2026-04-01", -50.00,
                        tegenpartij="", omschrijving="handmatige storting")
    uid = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    u = next(u for u in (await get_uitgaven(db, jaar=2026)) if u.id == uid)
    assert u.omschrijving == "handmatige storting"


@pytest.mark.asyncio
async def test_ensure_year_locked_raises(db):
    await _seed_fiscale_params(db, 2024)
    await update_jaarafsluiting_status(db, 2024, "definitief")
    await _seed_banktx(db, 1, "2024-06-01", -100.00)
    with pytest.raises(YearLockedError):
        await ensure_uitgave_for_banktx(db, bank_tx_id=1)


@pytest.mark.asyncio
async def test_ensure_raises_for_unknown_bank_tx(db):
    with pytest.raises(ValueError):
        await ensure_uitgave_for_banktx(db, bank_tx_id=999)


@pytest.mark.asyncio
async def test_ensure_idempotent_ignores_overrides_on_second_call(db):
    """Second call with different overrides returns existing id unchanged."""
    await _seed_banktx(db, 1, "2026-04-01", -120.87)
    first = await ensure_uitgave_for_banktx(
        db, bank_tx_id=1, categorie="Telefoon/KPN")
    second = await ensure_uitgave_for_banktx(
        db, bank_tx_id=1, categorie="SOMETHING_ELSE")
    assert first == second
    uitgaven = await get_uitgaven(db, jaar=2026)
    u = next(u for u in uitgaven if u.id == first)
    assert u.categorie == "Telefoon/KPN"


@pytest.mark.asyncio
async def test_ensure_bedrag_is_abs_for_positive_bank_tx(db):
    """Rare but possible: bank tx with positive bedrag (refund/reversal)."""
    await _seed_banktx(db, 1, "2026-04-01", 42.50)
    uid = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    u = next(u for u in (await get_uitgaven(db, jaar=2026)) if u.id == uid)
    assert u.bedrag == 42.50
