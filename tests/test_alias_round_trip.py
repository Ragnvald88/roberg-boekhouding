"""Smoke test for the alias CRUD round-trip via DB helpers (the layer the
/klanten dialog calls)."""

import pytest
import aiosqlite
from database import (
    add_klant, add_klant_alias, get_klant_aliases,
    delete_klant_alias, update_klant_alias_target,
)


async def test_alias_round_trip(db):
    k = await add_klant(db, naam='Klant Test', tarief_uur=100.0)
    aid = await add_klant_alias(db, k, 'pdf_text', 'Initial Pattern')
    rows = await get_klant_aliases(db, k)
    assert len(rows) == 1 and rows[0]['pattern'] == 'Initial Pattern'

    deleted = await delete_klant_alias(db, aid)
    assert deleted is True
    assert await get_klant_aliases(db, k) == []


async def test_alias_reassign_round_trip(db):
    k1 = await add_klant(db, naam='Klant A', tarief_uur=100.0)
    k2 = await add_klant(db, naam='Klant B', tarief_uur=100.0)
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Shared Name')
    ok = await update_klant_alias_target(db, aid, k1, k2)
    assert ok is True
    rows1 = await get_klant_aliases(db, k1)
    rows2 = await get_klant_aliases(db, k2)
    assert rows1 == [] and len(rows2) == 1


async def test_alias_validation_rejects_short_pattern(db):
    """UI calls add_klant_alias; validation comes from DB CHECK constraint."""
    k = await add_klant(db, naam='Klant', tarief_uur=100.0)
    with pytest.raises(aiosqlite.IntegrityError):
        await add_klant_alias(db, k, 'pdf_text', 'AB')
