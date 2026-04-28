"""Tests for klant_aliases CRUD + auto-learn helpers."""

import pytest
import aiosqlite
from database import (
    add_klant, get_db_ctx,
    get_klant_aliases, add_klant_alias,
    delete_klant_alias, update_klant_alias_target,
    remember_alias,
)


@pytest.fixture
async def db_two(db):
    k1 = await add_klant(db, naam='Klant Alpha', tarief_uur=100.0)
    k2 = await add_klant(db, naam='Klant Beta', tarief_uur=100.0)
    return db, k1, k2


# --- get / add / delete ---

async def test_add_klant_alias_inserts_row(db_two):
    db, k1, _ = db_two
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Centrum K14')
    assert aid > 0
    rows = await get_klant_aliases(db, k1)
    assert len(rows) == 1 and rows[0]['pattern'] == 'Centrum K14'


async def test_add_klant_alias_unique_violation(db_two):
    db, k1, k2 = db_two
    await add_klant_alias(db, k1, 'pdf_text', 'Centrum K14')
    with pytest.raises(aiosqlite.IntegrityError):
        await add_klant_alias(db, k2, 'pdf_text', 'Centrum K14')


async def test_add_klant_alias_short_pattern_rejected(db_two):
    db, k1, _ = db_two
    with pytest.raises(aiosqlite.IntegrityError):
        await add_klant_alias(db, k1, 'pdf_text', 'AB')


async def test_get_klant_aliases_filters_by_klant(db_two):
    db, k1, k2 = db_two
    await add_klant_alias(db, k1, 'pdf_text', 'Foo One')
    await add_klant_alias(db, k2, 'pdf_text', 'Foo Two')
    r1 = await get_klant_aliases(db, k1)
    r2 = await get_klant_aliases(db, k2)
    assert r1[0]['pattern'] == 'Foo One' and r2[0]['pattern'] == 'Foo Two'


async def test_delete_klant_alias_removes_row(db_two):
    db, k1, _ = db_two
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')
    assert await delete_klant_alias(db, aid) is True
    assert await get_klant_aliases(db, k1) == []


async def test_delete_klant_alias_unknown_id_returns_false(db_two):
    db, _, _ = db_two
    assert await delete_klant_alias(db, 99999) is False


# --- optimistic lock ---

async def test_update_klant_alias_target_success(db_two):
    db, k1, k2 = db_two
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')
    assert await update_klant_alias_target(db, aid, k1, k2) is True
    assert (await get_klant_aliases(db, k2))[0]['pattern'] == 'Foo BV'


async def test_update_klant_alias_target_stale(db_two):
    db, k1, k2 = db_two
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')
    assert await update_klant_alias_target(db, aid, 99999, k2) is False
    assert (await get_klant_aliases(db, k1))[0]['pattern'] == 'Foo BV'


# --- remember_alias (auto-learn) ---

async def test_remember_alias_inserts_new(db_two):
    db, k1, _ = db_two
    r = await remember_alias(db, k1, 'Some PDF Header', 'Suffix1')
    assert r == {'inserted': 2, 'already_correct': 0, 'conflicts': []}


async def test_remember_alias_idempotent_same_klant(db_two):
    db, k1, _ = db_two
    await remember_alias(db, k1, 'Foo BV', None)
    r = await remember_alias(db, k1, 'Foo BV', None)
    assert r == {'inserted': 0, 'already_correct': 1, 'conflicts': []}


async def test_remember_alias_conflict_detected(db_two):
    db, k1, k2 = db_two
    await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')
    r = await remember_alias(db, k2, 'Foo BV', None)
    assert r['inserted'] == 0
    assert len(r['conflicts']) == 1
    c = r['conflicts'][0]
    assert c['type'] == 'pdf_text'
    assert c['pattern'] == 'Foo BV'
    assert c['existing_klant_naam'] == 'Klant Alpha'
    assert c['existing_klant_id'] == k1


async def test_remember_alias_short_pattern_skipped(db_two):
    db, k1, _ = db_two
    r = await remember_alias(db, k1, 'AB', '12')
    assert r == {'inserted': 0, 'already_correct': 0, 'conflicts': []}


async def test_remember_alias_partial_conflict(db_two):
    db, k1, k2 = db_two
    await add_klant_alias(db, k1, 'suffix', 'OldSuffix')
    r = await remember_alias(db, k2, 'New PDF Name', 'OldSuffix')
    assert r['inserted'] == 1
    assert len(r['conflicts']) == 1


# --- process_remember_alias orchestrator ---

async def test_process_remember_alias_no_conflict(db_two):
    """No conflicts → orchestrator just inserts."""
    db, k1, _ = db_two
    from database import process_remember_alias

    async def callback(c):
        raise AssertionError('callback should not be called when no conflicts')

    result = await process_remember_alias(
        db, klant_id=k1, target_klant_naam='Klant Alpha',
        pdf_extracted_name='Foo BV', filename_suffix=None,
        on_conflict=callback)
    assert result['inserted'] == 1 and result['conflicts_resolved'] == 0


async def test_process_remember_alias_conflict_keep(db_two):
    """Conflict → callback returns 'keep' → no reassign."""
    db, k1, k2 = db_two
    from database import process_remember_alias
    await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')

    seen_conflicts = []
    async def callback(c):
        seen_conflicts.append(c)
        return 'keep'

    result = await process_remember_alias(
        db, klant_id=k2, target_klant_naam='Klant Beta',
        pdf_extracted_name='Foo BV', filename_suffix=None,
        on_conflict=callback)
    assert len(seen_conflicts) == 1
    assert result['inserted'] == 0
    assert result['conflicts_resolved'] == 0
    rows = await get_klant_aliases(db, k1)
    assert len(rows) == 1


async def test_process_remember_alias_conflict_reassign(db_two):
    """Conflict → callback returns 'reassign' → optimistic update."""
    db, k1, k2 = db_two
    from database import process_remember_alias
    await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')

    async def callback(c):
        return 'reassign'

    result = await process_remember_alias(
        db, klant_id=k2, target_klant_naam='Klant Beta',
        pdf_extracted_name='Foo BV', filename_suffix=None,
        on_conflict=callback)
    assert result['inserted'] == 0
    assert result['conflicts_resolved'] == 1
    rows1 = await get_klant_aliases(db, k1)
    rows2 = await get_klant_aliases(db, k2)
    assert rows1 == [] and len(rows2) == 1


async def test_process_remember_alias_reassign_stale_lost(db_two):
    """Conflict → reassign callback, but alias was already moved → ok=False."""
    db, k1, k2 = db_two
    from database import process_remember_alias
    aid = await add_klant_alias(db, k1, 'pdf_text', 'Foo BV')

    async def callback(c):
        # Simulate concurrent move
        await update_klant_alias_target(db, aid, k1, k2)
        return 'reassign'

    result = await process_remember_alias(
        db, klant_id=k2, target_klant_naam='Klant Beta',
        pdf_extracted_name='Foo BV', filename_suffix=None,
        on_conflict=callback)
    assert result['conflicts_lost'] == 1
