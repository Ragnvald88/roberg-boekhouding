"""Tests for dashboard health alerts."""

import pytest
from database import (
    get_health_alerts, add_banktransacties, add_factuur, add_klant,
    add_werkdag, upsert_fiscale_params,
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


# === Lane 2 escalations and route fixes (Plan 2026-04-26) ===

@pytest.mark.asyncio
async def test_uncategorized_bank_link_routes_to_transacties_filter(db):
    """`/bank` is a deprecated redirect — link must filter /transacties.

    Without the filter, clicking the alert dumps the user into the full
    transacties inbox and they have to re-filter manually for the same
    set of rows the alert just counted.
    """
    from datetime import date
    jaar = date.today().year
    await add_banktransacties(db, [
        {'datum': f'{jaar}-03-15', 'bedrag': -50.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'Boodschappen'},
    ])
    alerts = await get_health_alerts(db, jaar)
    uncat = next(a for a in alerts if a['key'] == 'uncategorized_bank')
    assert uncat['link'].startswith('/transacties'), (
        f"link still points to deprecated route: {uncat['link']}"
    )
    assert 'status=ongecategoriseerd' in uncat['link']


@pytest.mark.asyncio
async def test_uncategorized_bank_link_includes_jaar(db):
    """Link must scope /transacties to the alert's jaar.

    Without jaar in the URL, clicking from a 2024 dashboard lands on
    /transacties filtered to the current calendar year, which is a
    different (often empty) set of rows.
    """
    await add_banktransacties(db, [
        {'datum': '2024-03-15', 'bedrag': -50.0,
         'tegenpartij': 'AH', 'omschrijving': 'x'},
    ])
    alerts = await get_health_alerts(db, 2024)
    uncat = next(a for a in alerts if a['key'] == 'uncategorized_bank')
    assert 'jaar=2024' in uncat['link'], (
        f"link does not scope to jaar: {uncat['link']}"
    )


@pytest.mark.asyncio
async def test_uncategorized_bank_excludes_genegeerd(db):
    """A banktx flagged privé (genegeerd=1) must not inflate the count.

    The /transacties ongecategoriseerd view hides genegeerd rows; if the
    count includes them, clicking shows fewer rows than promised.
    """
    from datetime import date
    from database import mark_banktx_genegeerd, get_banktransacties
    jaar = date.today().year
    await add_banktransacties(db, [
        {'datum': f'{jaar}-03-15', 'bedrag': -50.0,
         'tegenpartij': 'AH', 'omschrijving': 'normal'},
        {'datum': f'{jaar}-03-16', 'bedrag': -75.0,
         'tegenpartij': 'Privé', 'omschrijving': 'cashflow'},
    ])
    rows = await get_banktransacties(db)
    privé = next(r for r in rows if r.tegenpartij == 'Privé')
    await mark_banktx_genegeerd(db, bank_tx_id=privé.id, genegeerd=1)
    alerts = await get_health_alerts(db, jaar)
    uncat = next(a for a in alerts if a['key'] == 'uncategorized_bank')
    assert uncat['count'] == 1, (
        f"genegeerd row was counted: count={uncat['count']}"
    )


@pytest.mark.asyncio
async def test_concept_invoice_escalates_to_warning_when_any_old(db):
    """A concept >14 days old must escalate the alert from info to warning."""
    from datetime import date, timedelta
    jaar = date.today().year
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    old_date = (date.today() - timedelta(days=20)).isoformat()
    await add_factuur(
        db, nummer=f'{jaar}-091', klant_id=kid,
        datum=old_date, totaal_uren=8, totaal_km=0,
        totaal_bedrag=800.0, status='concept',
    )
    alerts = await get_health_alerts(db, jaar)
    concept = next(a for a in alerts if a['key'] == 'concept_invoices')
    assert concept['severity'] == 'warning', (
        "stale concept (>14d) should escalate severity"
    )


@pytest.mark.asyncio
async def test_concept_invoice_stays_info_when_all_recent(db):
    """A concept <=14 days old keeps the alert at info severity."""
    from datetime import date, timedelta
    jaar = date.today().year
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    recent_date = (date.today() - timedelta(days=3)).isoformat()
    await add_factuur(
        db, nummer=f'{jaar}-092', klant_id=kid,
        datum=recent_date, totaal_uren=8, totaal_km=0,
        totaal_bedrag=800.0, status='concept',
    )
    alerts = await get_health_alerts(db, jaar)
    concept = next(a for a in alerts if a['key'] == 'concept_invoices')
    assert concept['severity'] == 'info'


@pytest.mark.asyncio
async def test_overdue_invoice_escalates_to_critical_after_30d(db):
    """A verstuurd invoice >30 days old must trigger 'critical' severity.

    Signals "send a herinnering now" — distinct from the regular 14-30d
    overdue warning.
    """
    from datetime import date, timedelta
    jaar = date.today().year
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    very_old = (date.today() - timedelta(days=45)).isoformat()
    await add_factuur(
        db, nummer=f'{jaar}-093', klant_id=kid,
        datum=very_old, totaal_uren=8, totaal_km=0,
        totaal_bedrag=800.0, status='verstuurd',
    )
    alerts = await get_health_alerts(db, jaar)
    overdue = next(a for a in alerts if a['key'] == 'overdue_invoices')
    assert overdue['severity'] == 'critical', (
        f"overdue >30d should escalate, got {overdue['severity']}"
    )


@pytest.mark.asyncio
async def test_overdue_invoice_stays_warning_under_30d(db):
    """A 14-30 day overdue invoice stays at 'warning', not critical."""
    from datetime import date, timedelta
    jaar = date.today().year
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    moderately_old = (date.today() - timedelta(days=20)).isoformat()
    await add_factuur(
        db, nummer=f'{jaar}-094', klant_id=kid,
        datum=moderately_old, totaal_uren=8, totaal_km=0,
        totaal_bedrag=800.0, status='verstuurd',
    )
    alerts = await get_health_alerts(db, jaar)
    overdue = next(a for a in alerts if a['key'] == 'overdue_invoices')
    assert overdue['severity'] == 'warning'


@pytest.mark.asyncio
async def test_stale_werkdagen_alert_fires_after_30d(db):
    """Werkdagen >30 days old without factuurnummer should produce a warning.

    Most actionable signal for a working huisarts: 'you have N werkdagen
    from februari that you forgot to invoice'.
    """
    from datetime import date, timedelta
    jaar = date.today().year
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    stale_date = (date.today() - timedelta(days=45)).isoformat()
    await add_werkdag(
        db, datum=stale_date, klant_id=kid, uren=8, tarief=100,
        km=0, km_tarief=0)
    alerts = await get_health_alerts(db, jaar)
    stale = next((a for a in alerts if a['key'] == 'stale_werkdagen'), None)
    assert stale is not None, "stale-werkdagen alert missing entirely"
    assert stale['severity'] == 'warning'
    assert stale['count'] == 1
    assert stale['link'].startswith('/werkdagen')


@pytest.mark.asyncio
async def test_no_stale_werkdagen_when_all_recent(db):
    """A werkdag <30 days old should NOT trigger the stale alert."""
    from datetime import date, timedelta
    jaar = date.today().year
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    recent = (date.today() - timedelta(days=10)).isoformat()
    await add_werkdag(
        db, datum=recent, klant_id=kid, uren=8, tarief=100,
        km=0, km_tarief=0)
    alerts = await get_health_alerts(db, jaar)
    assert not any(a['key'] == 'stale_werkdagen' for a in alerts), (
        "stale alert fired on a recent werkdag"
    )


@pytest.mark.asyncio
async def test_no_stale_werkdagen_when_factured(db):
    """A werkdag with factuurnummer set should not be flagged stale."""
    from datetime import date, timedelta
    jaar = date.today().year
    kid = await add_klant(db, naam='Test', tarief_uur=100)
    stale_date = (date.today() - timedelta(days=45)).isoformat()
    await add_werkdag(
        db, datum=stale_date, klant_id=kid, uren=8, tarief=100,
        km=0, km_tarief=0, factuurnummer=f'{jaar}-001')
    alerts = await get_health_alerts(db, jaar)
    assert not any(a['key'] == 'stale_werkdagen' for a in alerts)
