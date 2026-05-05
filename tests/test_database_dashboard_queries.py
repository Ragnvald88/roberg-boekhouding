"""Tests for dashboard-specific DB queries (Sprint H T3.3).

Covers get_factuur_aging_buckets + get_concept_facturen_stale, the two
queries die T3.4's action-inbox UI gebruikt om openstaande / stale
factuur-rows te tonen.
"""
import pytest
from datetime import date, timedelta

import database
from database import (
    get_factuur_aging_buckets,
    get_concept_facturen_stale,
    get_db_ctx,
)


async def _insert_klant(db_path, klant_id=1, naam='Test HAP'):
    """Insert a minimal klant for foreign-key satisfaction."""
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO klanten (id, naam, tarief_uur) "
            "VALUES (?, ?, 80)",
            (klant_id, naam),
        )
        await conn.commit()


async def _insert_factuur(db_path, *, nummer, status, datum,
                          klant_id=1, totaal_bedrag=500.0):
    """Helper for test factuur-rows.

    NB: facturen-tabel heeft GEEN vervaldatum-kolom — die is computed als
    datum + 14 dagen (Dutch convention). Caller geeft daarom alleen datum;
    de queries onder test berekenen vervaldatum zelf in SQL.
    """
    async with get_db_ctx(db_path) as conn:
        await conn.execute(
            """INSERT INTO facturen (nummer, klant_id, datum,
               totaal_bedrag, status, type, regels_json)
               VALUES (?, ?, ?, ?, ?, 'factuur', '[]')""",
            (nummer, klant_id, datum, totaal_bedrag, status),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_factuur_aging_buckets_categorises_correctly(db, monkeypatch):
    """4 facturen overdue 5d/25d/50d/100d → 4 buckets correct verdeeld.

    Vervaldatum = datum + 14 dagen, dus om N dagen overdue te krijgen
    moet datum = today - (N + 14) dagen zijn.
    """
    today_iso = '2026-06-01'
    monkeypatch.setattr(database, '_today_iso', lambda: today_iso)

    await _insert_klant(db)
    today_date = date(2026, 6, 1)
    # offset_overdue → datum N+14 dagen geleden, zodat days_overdue = N
    for offset_overdue, nummer in [(5, '1'), (25, '2'), (50, '3'), (100, '4')]:
        datum = (today_date - timedelta(days=offset_overdue + 14)).isoformat()
        await _insert_factuur(db, nummer=nummer, status='verstuurd',
                              datum=datum)

    result = await get_factuur_aging_buckets(db, jaar=2026)

    # 5d + 25d → overdue_30 (<30 dagen overdue)
    assert len(result['overdue_30']) == 2
    assert {r['nummer'] for r in result['overdue_30']} == {'1', '2'}
    # 50d → overdue_60 (30-59)
    assert len(result['overdue_60']) == 1
    assert result['overdue_60'][0]['nummer'] == '3'
    # niets in 60-89
    assert len(result['overdue_90']) == 0
    # 100d → overdue_90_plus (≥90)
    assert len(result['overdue_90_plus']) == 1
    assert result['overdue_90_plus'][0]['nummer'] == '4'


@pytest.mark.asyncio
async def test_factuur_aging_buckets_excludes_concept_and_betaald(db, monkeypatch):
    """Aging-buckets bevatten alleen status='verstuurd'."""
    monkeypatch.setattr(database, '_today_iso', lambda: '2026-06-01')
    await _insert_klant(db)
    # All have datum so vervaldatum is past
    datum = '2026-04-01'  # vervaldatum 2026-04-15, ~47d overdue
    await _insert_factuur(db, nummer='c1', status='concept', datum=datum)
    await _insert_factuur(db, nummer='b1', status='betaald', datum=datum)
    await _insert_factuur(db, nummer='v1', status='verstuurd', datum=datum)

    result = await get_factuur_aging_buckets(db, jaar=2026)
    all_nummers = {r['nummer'] for bucket in result.values() for r in bucket}
    assert all_nummers == {'v1'}


@pytest.mark.asyncio
async def test_factuur_aging_buckets_filters_by_year(db, monkeypatch):
    """Facturen uit ander jaar tellen niet mee."""
    monkeypatch.setattr(database, '_today_iso', lambda: '2026-06-01')
    await _insert_klant(db)
    # 2025 factuur — shouldn't appear in jaar=2026 result
    await _insert_factuur(db, nummer='2025-1', status='verstuurd',
                          datum='2025-12-01')
    # 2026 factuur — should appear
    await _insert_factuur(db, nummer='2026-1', status='verstuurd',
                          datum='2026-04-01')

    result = await get_factuur_aging_buckets(db, jaar=2026)
    all_nummers = {r['nummer'] for bucket in result.values() for r in bucket}
    assert all_nummers == {'2026-1'}


@pytest.mark.asyncio
async def test_factuur_aging_buckets_includes_klant_naam(db, monkeypatch):
    """Result-rows bevatten klant_naam via JOIN."""
    monkeypatch.setattr(database, '_today_iso', lambda: '2026-06-01')
    await _insert_klant(db, klant_id=1, naam='HAP Drenthe')
    await _insert_factuur(db, nummer='1', status='verstuurd',
                          datum='2026-04-01', klant_id=1)

    result = await get_factuur_aging_buckets(db, jaar=2026)
    row = result['overdue_60'][0]
    assert row['klant_naam'] == 'HAP Drenthe'
    assert row['totaal_bedrag'] == 500.0
    assert 'days_overdue' in row


@pytest.mark.asyncio
async def test_concept_facturen_stale_returns_concepts_older_than_threshold(db):
    """2 concept-facturen: 10d en 20d oud. threshold=14 → alleen 20d."""
    today_date = date.today()
    await _insert_klant(db)

    datum_10d = (today_date - timedelta(days=10)).isoformat()
    datum_20d = (today_date - timedelta(days=20)).isoformat()
    await _insert_factuur(db, nummer='c1', status='concept', datum=datum_10d)
    await _insert_factuur(db, nummer='c2', status='concept', datum=datum_20d)

    result = await get_concept_facturen_stale(
        db, jaar=today_date.year, days=14)
    assert len(result) == 1
    assert result[0]['nummer'] == 'c2'
    assert result[0]['klant_naam'] == 'Test HAP'


@pytest.mark.asyncio
async def test_concept_facturen_stale_excludes_verstuurd_and_betaald(db):
    """Stale-query bevat alleen status='concept'."""
    today_date = date.today()
    await _insert_klant(db)
    old_datum = (today_date - timedelta(days=30)).isoformat()
    await _insert_factuur(db, nummer='c1', status='concept', datum=old_datum)
    await _insert_factuur(db, nummer='v1', status='verstuurd', datum=old_datum)
    await _insert_factuur(db, nummer='b1', status='betaald', datum=old_datum)

    result = await get_concept_facturen_stale(
        db, jaar=today_date.year, days=14)
    assert len(result) == 1
    assert result[0]['nummer'] == 'c1'
