"""Tests for dashboard health alerts."""

import pytest
from database import (
    get_health_alerts, add_banktransacties, add_factuur, add_klant,
    upsert_fiscale_params,
)
from import_.seed_data import FISCALE_PARAMS


@pytest.mark.asyncio
async def test_health_alerts_empty_db(db):
    """Empty DB should return alerts for missing fiscal params only."""
    from datetime import date
    jaar = date.today().year
    alerts = await get_health_alerts(db, jaar)
    assert isinstance(alerts, list)
    # No fiscal params → should flag it
    assert any(a['key'] == 'missing_fiscal_params' for a in alerts)


@pytest.mark.asyncio
async def test_health_alerts_uncategorized_bank(db):
    """Uncategorized bank transactions should produce an alert."""
    from datetime import date
    jaar = date.today().year
    await add_banktransacties(db, [
        {'datum': f'{jaar}-03-15', 'bedrag': -50.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'Boodschappen'},
    ])
    alerts = await get_health_alerts(db, jaar)
    uncat = next((a for a in alerts if a['key'] == 'uncategorized_bank'), None)
    assert uncat is not None
    assert uncat['count'] == 1


@pytest.mark.asyncio
async def test_health_alerts_overdue_invoice(db):
    """Verstuurd invoice older than 14 days should trigger overdue alert."""
    from datetime import date, timedelta
    jaar = date.today().year
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    old_date = (date.today() - timedelta(days=20)).isoformat()
    await add_factuur(
        db, nummer=f'{jaar}-099', klant_id=kid,
        datum=old_date, totaal_uren=8, totaal_km=0,
        totaal_bedrag=800.0, status='verstuurd',
    )
    alerts = await get_health_alerts(db, jaar)
    overdue = next((a for a in alerts if a['key'] == 'overdue_invoices'), None)
    assert overdue is not None
    assert overdue['count'] == 1


@pytest.mark.asyncio
async def test_health_alerts_all_clear(db):
    """DB with fiscal params set should not flag missing_fiscal_params."""
    from datetime import date
    jaar = date.today().year
    # Use a year that has seed data; seed data contains all required keys
    seed_year = max(FISCALE_PARAMS.keys())
    seed = {**FISCALE_PARAMS[seed_year], 'jaar': jaar}
    await upsert_fiscale_params(db, **seed)
    alerts = await get_health_alerts(db, jaar)
    assert not any(a['key'] == 'missing_fiscal_params' for a in alerts)
