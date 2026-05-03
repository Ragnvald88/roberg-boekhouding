"""Integration tests for klant.color round-trip + DB CHECK enforcement.

Sprint D I1: D3 Codex-caught bug (color uit refresh_klanten weggelaten in
update-flow) had door unit-test op add/get/update gevangen kunnen worden.
"""

import aiosqlite
import pytest

from database import (
    add_klant,
    get_klant_by_id,
    update_klant,
)


async def test_add_klant_with_color_round_trip(db):
    """add_klant + get_klant_by_id should preserve hex color."""
    kid = await add_klant(db, naam='Test Praktijk', color='#0F766E')
    klant = await get_klant_by_id(db, kid)
    assert klant is not None
    assert klant.color == '#0F766E'


async def test_add_klant_without_color_returns_none(db):
    """add_klant zonder color → klant.color is None (default)."""
    kid = await add_klant(db, naam='Test Zonder Kleur')
    klant = await get_klant_by_id(db, kid)
    assert klant is not None
    assert klant.color is None


async def test_update_klant_color_round_trip(db):
    """update_klant kan color zetten + later weghalen."""
    kid = await add_klant(db, naam='Test Update')
    # Set kleur
    await update_klant(db, klant_id=kid, color='#7E22CE')
    klant = await get_klant_by_id(db, kid)
    assert klant is not None
    assert klant.color == '#7E22CE'
    # Reset naar None
    await update_klant(db, klant_id=kid, color=None)
    klant = await get_klant_by_id(db, kid)
    assert klant is not None
    assert klant.color is None


async def test_invalid_hex_rejected_by_check(db):
    """SQLite CHECK constraint weigert non-#RRGGBB hex."""
    with pytest.raises(aiosqlite.IntegrityError):
        await add_klant(db, naam='X', color='red')
