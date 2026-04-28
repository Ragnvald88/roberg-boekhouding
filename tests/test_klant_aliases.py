"""Schema tests for klant_aliases (migration 33)."""

import pytest
import aiosqlite
from database import add_klant, get_db_ctx


@pytest.fixture
async def db_with_klanten(db):
    k1 = await add_klant(db, naam='Klant Alpha', tarief_uur=100.0)
    k2 = await add_klant(db, naam='Klant Beta', tarief_uur=100.0)
    return db, k1, k2


async def test_klant_aliases_table_exists(db):
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='klant_aliases'")
        row = await cur.fetchone()
    assert row is not None


async def test_unique_type_pattern(db_with_klanten):
    db, k1, k2 = db_with_klanten
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
            (k1,))
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
                (k2,))


async def test_unique_is_case_insensitive(db_with_klanten):
    db, k1, k2 = db_with_klanten
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
            (k1,))
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'foo bv')",
                (k2,))


async def test_pattern_min_length_3(db_with_klanten):
    db, k1, _ = db_with_klanten
    async with get_db_ctx(db) as conn:
        for short in ('', '  ', 'a', 'ab', '  ab '):
            with pytest.raises(aiosqlite.IntegrityError):
                await conn.execute(
                    "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', ?)",
                    (k1, short))


async def test_type_check_constraint(db_with_klanten):
    db, k1, _ = db_with_klanten
    async with get_db_ctx(db) as conn:
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'invalid_type', 'Foo BV')",
                (k1,))


async def test_cascade_delete_on_klant_removal(db_with_klanten):
    db, k1, _ = db_with_klanten
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "INSERT INTO klant_aliases (klant_id, type, pattern) VALUES (?, 'pdf_text', 'Foo BV')",
            (k1,))
        await conn.commit()
        await conn.execute("DELETE FROM klanten WHERE id = ?", (k1,))
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM klant_aliases WHERE klant_id = ?", (k1,))
        cnt = (await cur.fetchone())[0]
    assert cnt == 0


async def test_index_exists(db):
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_klant_aliases_lookup'")
        row = await cur.fetchone()
    assert row is not None


# --- Migration 34: data callable + JSON fallback ---


async def test_migration_34_uses_module_source_when_returned(db, monkeypatch):
    """If `_get_local_module_aliases` returns rows, those are used."""
    k1 = await add_klant(db, naam='HAP K14', tarief_uur=100.0)
    import database as dbm
    monkeypatch.setattr(dbm, '_get_local_module_aliases', lambda: [
        ('HAP K14', 'suffix', 'Winsum'),
        ('HAP K14', 'suffix', 'XX'),  # < 3 chars → must be skipped
        ('HAP K14', 'pdf_text', 'Centrum K14'),
        ('Klant Niet In DB', 'pdf_text', 'GHOST'),  # klant absent → skipped
        ('HAP K14', 'anw_filename', 'DDG'),
    ])
    monkeypatch.setattr(dbm, '_get_json_snapshot_aliases', lambda: None)

    from database import _seed_klant_aliases_from_local
    async with get_db_ctx(db) as conn:
        await _seed_klant_aliases_from_local(conn)
        await conn.commit()
        cur = await conn.execute(
            "SELECT type, pattern FROM klant_aliases ORDER BY type, pattern")
        rows = [(r[0], r[1]) for r in await cur.fetchall()]
    assert ('anw_filename', 'DDG') in rows
    assert ('pdf_text', 'Centrum K14') in rows
    assert ('suffix', 'Winsum') in rows
    assert ('suffix', 'XX') not in rows
    assert ('pdf_text', 'GHOST') not in rows


async def test_migration_34_falls_back_to_json_when_module_returns_none(db, monkeypatch):
    """When `_get_local_module_aliases` returns None, JSON snapshot is used."""
    k1 = await add_klant(db, naam='HAP K14', tarief_uur=100.0)
    import database as dbm
    monkeypatch.setattr(dbm, '_get_local_module_aliases', lambda: None)
    monkeypatch.setattr(dbm, '_get_json_snapshot_aliases', lambda: [
        ('HAP K14', 'pdf_text', 'Centrum K14'),
        ('HAP K14', 'suffix', 'Winsum'),
    ])
    from database import _seed_klant_aliases_from_local
    async with get_db_ctx(db) as conn:
        await _seed_klant_aliases_from_local(conn)
        await conn.commit()
        cur = await conn.execute(
            "SELECT type, pattern FROM klant_aliases ORDER BY type")
        rows = [(r[0], r[1]) for r in await cur.fetchall()]
    assert ('pdf_text', 'Centrum K14') in rows
    assert ('suffix', 'Winsum') in rows


async def test_migration_34_no_op_when_both_sources_empty(db, monkeypatch):
    """No source available → no-op."""
    import database as dbm
    monkeypatch.setattr(dbm, '_get_local_module_aliases', lambda: None)
    monkeypatch.setattr(dbm, '_get_json_snapshot_aliases', lambda: None)
    from database import _seed_klant_aliases_from_local
    async with get_db_ctx(db) as conn:
        await _seed_klant_aliases_from_local(conn)
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM klant_aliases")
        cnt = (await cur.fetchone())[0]
    assert cnt == 0


async def test_migration_34_idempotent(db, monkeypatch):
    """Running migration 34 twice does not duplicate."""
    k1 = await add_klant(db, naam='HAP K14', tarief_uur=100.0)
    import database as dbm
    monkeypatch.setattr(dbm, '_get_local_module_aliases', lambda: [
        ('HAP K14', 'suffix', 'Winsum'),
    ])
    monkeypatch.setattr(dbm, '_get_json_snapshot_aliases', lambda: None)
    from database import _seed_klant_aliases_from_local
    async with get_db_ctx(db) as conn:
        await _seed_klant_aliases_from_local(conn)
        await _seed_klant_aliases_from_local(conn)
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM klant_aliases")
        cnt = (await cur.fetchone())[0]
    assert cnt == 1


def test_get_json_snapshot_aliases_reads_file(tmp_path, monkeypatch):
    """Pure-function test for the JSON loader."""
    import json
    from database import _get_json_snapshot_aliases
    monkeypatch.setenv('BOEKHOUDING_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'klant_aliases_backup.json').write_text(json.dumps([
        {'klant_naam': 'A', 'type': 'pdf_text', 'pattern': 'PA'},
        {'klant_naam': 'B', 'type': 'suffix', 'pattern': 'PB'},
    ]))
    rows = _get_json_snapshot_aliases()
    assert rows == [('A', 'pdf_text', 'PA'), ('B', 'suffix', 'PB')]


def test_get_json_snapshot_aliases_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv('BOEKHOUDING_CONFIG_DIR', str(tmp_path))
    from database import _get_json_snapshot_aliases
    assert _get_json_snapshot_aliases() is None
