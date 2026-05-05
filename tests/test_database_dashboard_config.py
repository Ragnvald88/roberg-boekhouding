"""Tests for dashboard_widgets_json column + config-helpers (Sprint H T4a.1)."""
import pytest
import pytest_asyncio

from database import (
    init_db,
    get_db_ctx,
    get_dashboard_widgets_config,
    set_dashboard_widgets_config,
    get_bedrijfsgegevens,
    upsert_bedrijfsgegevens,
)


@pytest_asyncio.fixture
async def temp_db(tmp_path):
    """Fresh DB voor elke test."""
    db_path = tmp_path / 'test.sqlite3'
    await init_db(db_path)
    return db_path


async def _ensure_bedrijfsgegevens_row(db_path):
    """Ensure single bedrijfsgegevens row exists (some helpers create it lazily)."""
    bg = await get_bedrijfsgegevens(db_path)
    if bg is None:
        await upsert_bedrijfsgegevens(db_path, naam='Test', iban='NL00TEST0000000000', kvk='12345678')


@pytest.mark.asyncio
async def test_migration_39_adds_dashboard_widgets_json_column(temp_db):
    """After init_db, the column should exist on bedrijfsgegevens."""
    async with get_db_ctx(temp_db) as conn:
        cur = await conn.execute("PRAGMA table_info(bedrijfsgegevens)")
        cols = {r['name'] for r in await cur.fetchall()}
    assert 'dashboard_widgets_json' in cols


@pytest.mark.asyncio
async def test_dashboard_widgets_config_round_trip(temp_db):
    """Write then read returns the same JSON string."""
    await _ensure_bedrijfsgegevens_row(temp_db)
    config = '{"schema_version": 1, "widgets": {"I-1": false}}'
    await set_dashboard_widgets_config(temp_db, config)
    result = await get_dashboard_widgets_config(temp_db)
    assert result == config


@pytest.mark.asyncio
async def test_dashboard_widgets_config_null_default(temp_db):
    """Without bedrijfsgegevens row OR without config set → None."""
    # No row at all
    result = await get_dashboard_widgets_config(temp_db)
    # Either None (no row) or None (NULL value)
    assert result is None

    # Row exists but no config
    await _ensure_bedrijfsgegevens_row(temp_db)
    result = await get_dashboard_widgets_config(temp_db)
    assert result is None


@pytest.mark.asyncio
async def test_set_dashboard_widgets_config_creates_row_if_missing(temp_db):
    """set_dashboard_widgets_config must lazy-create a bedrijfsgegevens row.

    Without this, a fresh-install user who opens /instellingen Dashboard tab
    before filling in bedrijfsgegevens would silently lose his config (UPDATE
    on empty table = 0 rows). Codex review T4a.1.
    """
    # Verify no row yet
    bg = await get_bedrijfsgegevens(temp_db)
    assert bg is None

    config = '{"schema_version": 1, "widgets": {"I-2": false}}'
    await set_dashboard_widgets_config(temp_db, config)

    # Config should now be persisted
    result = await get_dashboard_widgets_config(temp_db)
    assert result == config


@pytest.mark.asyncio
async def test_upsert_bedrijfsgegevens_preserves_dashboard_config(temp_db):
    """upsert_bedrijfsgegevens must NOT wipe an existing dashboard_widgets_json.

    Regression guard: INSERT OR REPLACE rebuilds the row, so any column not
    in the INSERT list reverts to its default. Without explicit preservation
    every save of bedrijfsgegevens (e.g. user updates IBAN) would silently
    nuke the dashboard customisation. Codex review T4a.1.
    """
    # Seed bedrijfsgegevens + dashboard config
    await upsert_bedrijfsgegevens(
        temp_db, naam='Test', iban='NL00TEST0000000000', kvk='12345678',
    )
    config = '{"schema_version": 1, "widgets": {"I-3": true}}'
    await set_dashboard_widgets_config(temp_db, config)

    # Sanity: config is set
    assert await get_dashboard_widgets_config(temp_db) == config

    # Now upsert bedrijfsgegevens again WITHOUT passing dashboard_widgets_json
    await upsert_bedrijfsgegevens(
        temp_db, naam='Test', iban='NL00BANK1111111111', kvk='12345678',
    )

    # Config must still be there
    assert await get_dashboard_widgets_config(temp_db) == config


@pytest.mark.asyncio
async def test_upsert_bedrijfsgegevens_explicit_dashboard_config_overrides(temp_db):
    """Explicit dashboard_widgets_json kwarg in upsert wins over preserved value."""
    await upsert_bedrijfsgegevens(temp_db, naam='Test')
    await set_dashboard_widgets_config(temp_db, '{"v": 1}')

    # Pass explicit None to clear
    await upsert_bedrijfsgegevens(
        temp_db, naam='Test2', dashboard_widgets_json=None,
    )
    assert await get_dashboard_widgets_config(temp_db) is None

    # Pass explicit value to set
    await upsert_bedrijfsgegevens(
        temp_db, naam='Test3', dashboard_widgets_json='{"v": 2}',
    )
    assert await get_dashboard_widgets_config(temp_db) == '{"v": 2}'
