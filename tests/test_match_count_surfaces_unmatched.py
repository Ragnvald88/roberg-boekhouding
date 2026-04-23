"""Task 19 — find_factuur_matches surfaces unmatched proposals for the
`Matches controleren (N)` button on /transacties.

Seeds a sent factuur + a matching bank credit and asserts the proposal
is returned. Regression guard for the count-visible-to-user path.
"""
import pytest
import aiosqlite

from database import find_factuur_matches


async def _seed(db):
    async with aiosqlite.connect(db) as conn:
        # Seed a klant so facturen.klant_id FK resolves cleanly.
        await conn.execute(
            "INSERT INTO klanten (id, naam, tarief_uur) "
            "VALUES (1, 'Testklant', 100.0)")
        # Seed a sent factuur
        await conn.execute(
            "INSERT INTO facturen "
            "(nummer, klant_id, datum, totaal_bedrag, status, type, bron) "
            "VALUES ('2026-001', 1, '2026-03-01', 100.0, 'verstuurd', "
            "        'factuur', 'app')")
        # Seed a matching bank credit (same amount, within date range,
        # factuur-nummer in omschrijving)
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij, omschrijving, tegenrekening, "
            " csv_bestand) VALUES (1, '2026-03-05', 100.0, 'Klant', "
            "                       '2026-001', '', 't.csv')")
        await conn.commit()


@pytest.mark.asyncio
async def test_find_factuur_matches_returns_proposal(db):
    """Regression: an unmatched proposal must be countable for the
    Matches-controleren button."""
    await _seed(db)
    proposals = await find_factuur_matches(db)
    assert len(proposals) == 1
    p = proposals[0]
    assert p.factuur_nummer == '2026-001'
    assert p.bank_id == 1


@pytest.mark.asyncio
async def test_no_match_returns_empty(db):
    """Clean DB returns empty proposal list — button should hide."""
    proposals = await find_factuur_matches(db)
    assert proposals == []
