"""Year-locking guards for definitief jaarafsluiting snapshots (review K6)."""

import aiosqlite
import pytest
from database import (
    YearLockedError, assert_year_writable,
    update_jaarafsluiting_status,
)


async def _seed_fiscale_params_row(db_path, jaar: int) -> None:
    """Insert a minimal fiscale_params row for a year (defaults = 'concept')."""
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar) VALUES (?)", (jaar,))
        await conn.commit()


@pytest.mark.asyncio
async def test_assert_year_writable_passes_when_no_fiscale_params(db):
    """No fiscale_params row for a year => writable (nothing to lock against)."""
    await assert_year_writable(db, '2027-06-01')  # must not raise


@pytest.mark.asyncio
async def test_assert_year_writable_passes_for_concept_year(db):
    """Year with status='concept' is writable."""
    await _seed_fiscale_params_row(db, 2026)
    await assert_year_writable(db, '2026-03-15')  # must not raise


@pytest.mark.asyncio
async def test_assert_year_writable_rejects_definitief_year(db):
    """Year with status='definitief' must raise YearLockedError."""
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError, match='2025'):
        await assert_year_writable(db, '2025-06-01')


@pytest.mark.asyncio
async def test_assert_year_writable_accepts_int_year_or_datum_str(db):
    """Helper accepts either an ISO datum string or an int year."""
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await assert_year_writable(db, 2025)
    with pytest.raises(YearLockedError):
        await assert_year_writable(db, '2025-12-31')


def test_year_locked_error_is_value_error():
    """Backward compat: existing catch(ValueError) sites still catch this."""
    exc = YearLockedError('test')
    assert isinstance(exc, ValueError)
