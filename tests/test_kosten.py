"""Tests voor kosten (uitgaven) database operaties."""

import pytest
from database import (
    init_db, add_uitgave, get_uitgaven, get_uitgaven_per_categorie,
    get_investeringen, update_uitgave, delete_uitgave,
)


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path


@pytest.mark.asyncio
async def test_add_uitgave(db):
    """Add an expense, verify it's returned by get_uitgaven."""
    uid = await add_uitgave(
        db, datum="2026-02-15", categorie="Bankkosten",
        omschrijving="Rabobank maandkosten", bedrag=12.50,
    )
    assert uid > 0

    uitgaven = await get_uitgaven(db)
    assert len(uitgaven) == 1
    assert uitgaven[0].id == uid
    assert uitgaven[0].datum == "2026-02-15"
    assert uitgaven[0].categorie == "Bankkosten"
    assert uitgaven[0].omschrijving == "Rabobank maandkosten"
    assert uitgaven[0].bedrag == 12.50
    assert uitgaven[0].is_investering is False


@pytest.mark.asyncio
async def test_uitgaven_filter_by_year(db):
    """Add expenses in different years, verify year filter works."""
    await add_uitgave(
        db, datum="2025-06-10", categorie="Telefoon/KPN",
        omschrijving="KPN juni", bedrag=25.00,
    )
    await add_uitgave(
        db, datum="2026-01-10", categorie="Telefoon/KPN",
        omschrijving="KPN jan", bedrag=27.50,
    )
    await add_uitgave(
        db, datum="2026-03-01", categorie="Bankkosten",
        omschrijving="Rabo", bedrag=12.50,
    )

    u_all = await get_uitgaven(db)
    assert len(u_all) == 3

    u_2025 = await get_uitgaven(db, jaar=2025)
    assert len(u_2025) == 1
    assert u_2025[0].omschrijving == "KPN juni"

    u_2026 = await get_uitgaven(db, jaar=2026)
    assert len(u_2026) == 2

    # Also filter by category within a year
    u_2026_bank = await get_uitgaven(db, jaar=2026, categorie="Bankkosten")
    assert len(u_2026_bank) == 1
    assert u_2026_bank[0].bedrag == 12.50


@pytest.mark.asyncio
async def test_uitgaven_per_categorie(db):
    """Add expenses in different categories, verify grouped sums."""
    await add_uitgave(
        db, datum="2026-01-15", categorie="Bankkosten",
        omschrijving="Rabo jan", bedrag=12.50,
    )
    await add_uitgave(
        db, datum="2026-02-15", categorie="Bankkosten",
        omschrijving="Rabo feb", bedrag=12.50,
    )
    await add_uitgave(
        db, datum="2026-01-20", categorie="Telefoon/KPN",
        omschrijving="KPN", bedrag=45.00,
    )
    await add_uitgave(
        db, datum="2026-03-01", categorie="Representatie",
        omschrijving="Etentje klant", bedrag=80.00,
    )

    result = await get_uitgaven_per_categorie(db, jaar=2026)
    cats = {r['categorie']: r['totaal'] for r in result}

    assert cats['Bankkosten'] == 25.00
    assert cats['Telefoon/KPN'] == 45.00
    assert cats['Representatie'] == 80.00
    assert len(cats) == 3

    # Without year filter: same result (all are 2026)
    result_all = await get_uitgaven_per_categorie(db)
    cats_all = {r['categorie']: r['totaal'] for r in result_all}
    assert cats_all == cats


@pytest.mark.asyncio
async def test_investering_flag(db):
    """Add expense >= 450 with is_investering=1, verify get_investeringen returns it."""
    # Normal expense (< 450)
    await add_uitgave(
        db, datum="2026-01-10", categorie="Kleine aankopen",
        omschrijving="Muismat", bedrag=25.00,
    )
    # Investment (>= 450)
    uid_inv = await add_uitgave(
        db, datum="2026-02-01", categorie="Investeringen",
        omschrijving="MacBook Air M3", bedrag=1499.00,
        is_investering=1, levensduur_jaren=5,
        restwaarde_pct=10, zakelijk_pct=100,
        aanschaf_bedrag=1499.00,
    )
    # Another investment in a different year
    await add_uitgave(
        db, datum="2025-06-15", categorie="Investeringen",
        omschrijving="iPhone 15", bedrag=899.00,
        is_investering=1, levensduur_jaren=4,
        restwaarde_pct=10, zakelijk_pct=100,
        aanschaf_bedrag=899.00,
    )

    # Get all investments
    inv_all = await get_investeringen(db)
    assert len(inv_all) == 2
    assert all(i.is_investering for i in inv_all)

    # Filter by year
    inv_2026 = await get_investeringen(db, jaar=2026)
    assert len(inv_2026) == 1
    assert inv_2026[0].id == uid_inv
    assert inv_2026[0].omschrijving == "MacBook Air M3"
    assert inv_2026[0].bedrag == 1499.00
    assert inv_2026[0].levensduur_jaren == 5
    assert inv_2026[0].restwaarde_pct == 10
    assert inv_2026[0].zakelijk_pct == 100

    # Normal expense should not appear in investments
    inv_2025 = await get_investeringen(db, jaar=2025)
    assert len(inv_2025) == 1
    assert inv_2025[0].omschrijving == "iPhone 15"


@pytest.mark.asyncio
async def test_update_uitgave(db):
    """Update an expense, verify changes persist."""
    uid = await add_uitgave(
        db, datum="2026-01-10", categorie="Bankkosten",
        omschrijving="Rabo", bedrag=12.50,
    )
    await update_uitgave(
        db, uitgave_id=uid,
        omschrijving="Rabobank zakelijk", bedrag=15.00,
        categorie="Accountancy/software",
    )
    uitgaven = await get_uitgaven(db)
    assert len(uitgaven) == 1
    assert uitgaven[0].omschrijving == "Rabobank zakelijk"
    assert uitgaven[0].bedrag == 15.00
    assert uitgaven[0].categorie == "Accountancy/software"


@pytest.mark.asyncio
async def test_delete_uitgave(db):
    """Delete an expense, verify it's removed."""
    uid = await add_uitgave(
        db, datum="2026-01-10", categorie="Bankkosten",
        omschrijving="Rabo", bedrag=12.50,
    )
    assert len(await get_uitgaven(db)) == 1
    await delete_uitgave(db, uitgave_id=uid)
    assert len(await get_uitgaven(db)) == 0
