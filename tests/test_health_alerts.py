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


@pytest.mark.asyncio
async def test_health_alerts_concept_invoices(db):
    """Concept invoices in the current year should produce an info alert."""
    from datetime import date
    jaar = date.today().year
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    await add_factuur(
        db, nummer=f'{jaar}-101', klant_id=kid,
        datum=f'{jaar}-06-01', totaal_uren=8, totaal_km=0,
        totaal_bedrag=800.0, status='concept',
    )
    alerts = await get_health_alerts(db, jaar)
    concept = next((a for a in alerts if a['key'] == 'concept_invoices'), None)
    assert concept is not None
    assert concept['severity'] == 'info'
    assert concept['count'] == 1
    assert concept['link'] == '/facturen'


@pytest.mark.asyncio
async def test_health_alerts_year_scoping(db):
    """Uncategorized bank txns outside the target year should not leak into alerts."""
    await add_banktransacties(db, [
        {'datum': '2024-12-31', 'bedrag': -50.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'Boodschappen'},
        {'datum': '2026-01-01', 'bedrag': -50.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'Boodschappen'},
    ])
    alerts = await get_health_alerts(db, 2025)
    assert not any(a['key'] == 'uncategorized_bank' for a in alerts)
