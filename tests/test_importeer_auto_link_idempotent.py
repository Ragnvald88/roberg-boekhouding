"""M1 polish — second import for same bank_tx must not raise or duplicate."""
import pytest
import aiosqlite
from database import ensure_uitgave_for_banktx


async def _seed_banktx(db, tx_id, datum='2026-03-01', bedrag=-50.0):
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "omschrijving, tegenrekening, csv_bestand) "
            "VALUES (?,?,?,?,?,?,?)",
            (tx_id, datum, bedrag, 'KPN', '', '', 't.csv'))
        await conn.commit()


@pytest.mark.asyncio
async def test_ensure_is_idempotent(db):
    await _seed_banktx(db, 1)
    uid1 = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    uid2 = await ensure_uitgave_for_banktx(db, bank_tx_id=1)
    assert uid1 == uid2


@pytest.mark.asyncio
async def test_second_call_respects_unique_index(db):
    """With migratie 28, a racing add_uitgave(bank_tx_id=1) would fail.
    ensure_uitgave_for_banktx must short-circuit and not attempt insert."""
    await _seed_banktx(db, 1)
    uid1 = await ensure_uitgave_for_banktx(db, bank_tx_id=1,
                                             categorie='Telefoon/KPN')
    # Second call with overrides — should return same id, NOT re-insert
    uid2 = await ensure_uitgave_for_banktx(db, bank_tx_id=1,
                                             categorie='Automatisering')
    assert uid1 == uid2
    # ensure is a create-or-return; it does not update categorie on
    # already-linked rows. Verify the second call did NOT overwrite:
    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute(
            "SELECT categorie FROM uitgaven WHERE id = ?", (uid1,))
        row = await cur.fetchone()
        assert row[0] == 'Telefoon/KPN'
