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
