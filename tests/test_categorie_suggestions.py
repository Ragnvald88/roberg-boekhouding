"""Tests for bank transaction category suggestions."""

import pytest
from database import get_categorie_suggestions, add_banktransacties, update_banktransactie


@pytest.mark.asyncio
async def test_suggestions_empty_db(db):
    """No transactions → empty suggestions dict."""
    result = await get_categorie_suggestions(db)
    assert result == {}


@pytest.mark.asyncio
async def test_suggestions_from_categorized_transactions(db):
    """Categorized transactions should produce suggestions by tegenpartij."""
    from database import get_banktransacties
    # Add 3 transactions from same counterparty, 2 with same category
    await add_banktransacties(db, [
        {'datum': '2026-01-15', 'bedrag': -50.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'Boodschappen'},
        {'datum': '2026-02-15', 'bedrag': -45.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'Boodschappen'},
        {'datum': '2026-03-15', 'bedrag': -60.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'Boodschappen'},
    ])
    # Categorize 2 as Representatie, 1 as Kantoorkosten
    txns = await get_banktransacties(db)
    await update_banktransactie(db, txns[0].id, categorie='Representatie')
    await update_banktransactie(db, txns[1].id, categorie='Representatie')
    await update_banktransactie(db, txns[2].id, categorie='Kantoorkosten')

    result = await get_categorie_suggestions(db)
    # Most common category for 'albert heijn' (lowercased key)
    assert result.get('albert heijn') == 'Representatie'


@pytest.mark.asyncio
async def test_suggestions_case_insensitive_grouping(db):
    """Tegenpartij matching should be case-insensitive."""
    await add_banktransacties(db, [
        {'datum': '2026-01-15', 'bedrag': -50.0,
         'tegenpartij': 'ALBERT HEIJN', 'omschrijving': 'x'},
        {'datum': '2026-02-15', 'bedrag': -45.0,
         'tegenpartij': 'Albert Heijn', 'omschrijving': 'x'},
    ])
    from database import get_banktransacties
    txns = await get_banktransacties(db)
    for t in txns:
        await update_banktransactie(db, t.id, categorie='Representatie')

    result = await get_categorie_suggestions(db)
    # Key is always lowercased
    assert 'albert heijn' in result
    assert result['albert heijn'] == 'Representatie'


@pytest.mark.asyncio
async def test_suggestions_ignores_uncategorized(db):
    """Transactions without a category should not produce suggestions."""
    await add_banktransacties(db, [
        {'datum': '2026-01-15', 'bedrag': -50.0,
         'tegenpartij': 'Bol.com', 'omschrijving': 'Bestelling'},
    ])
    result = await get_categorie_suggestions(db)
    assert 'Bol.com' not in result
    assert 'bol.com' not in result
