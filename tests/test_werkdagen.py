"""Tests voor werkdagen functionaliteit."""

import pytest
from database import (
    add_klant, add_werkdag, get_werkdagen,
    get_werkdagen_ongefactureerd, update_werkdag,
    link_werkdagen_to_factuur, get_uren_totaal,
)
from import_.seed_data import seed_all


@pytest.fixture
async def seeded_db(db):
    await seed_all(db)
    # Add test klanten (seed_all no longer seeds klanten)
    await add_klant(db, naam='Testpraktijk A', tarief_uur=77.50, retour_km=52,
                    adres='Testlaan 1, 1234 AB Teststad')
    await add_klant(db, naam='Testpraktijk B', tarief_uur=80.00, retour_km=44,
                    adres='Testweg 2, 5678 CD Testdorp')
    return db


@pytest.mark.asyncio
async def test_add_werkdag_with_klant(seeded_db):
    """Werkdag toevoegen met klantgegevens."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    klant = klanten[0]

    wid = await add_werkdag(
        seeded_db, datum='2026-02-23', klant_id=klant.id,
        uren=9, km=klant.retour_km, tarief=klant.tarief_uur,
        code='WERKDAG', activiteit='Waarneming dagpraktijk',
    )
    assert wid > 0

    werkdagen = await get_werkdagen(seeded_db, jaar=2026)
    assert len(werkdagen) == 1
    w = werkdagen[0]
    assert w.klant_naam == klant.naam
    assert w.uren == 9
    assert w.km == klant.retour_km
    assert w.tarief == klant.tarief_uur


@pytest.mark.asyncio
async def test_filter_werkdagen_by_month(seeded_db):
    """Filteren op maand."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_werkdag(seeded_db, datum='2026-01-15', klant_id=kid,
                      uren=8, tarief=77.50)
    await add_werkdag(seeded_db, datum='2026-02-15', klant_id=kid,
                      uren=9, tarief=77.50)
    await add_werkdag(seeded_db, datum='2026-02-20', klant_id=kid,
                      uren=8, tarief=77.50)

    jan = await get_werkdagen(seeded_db, jaar=2026, maand=1)
    feb = await get_werkdagen(seeded_db, jaar=2026, maand=2)
    assert len(jan) == 1
    assert len(feb) == 2


@pytest.mark.asyncio
async def test_filter_werkdagen_by_klant(seeded_db):
    """Filteren op klant."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    k1, k2 = klanten[0], klanten[1]

    await add_werkdag(seeded_db, datum='2026-02-01', klant_id=k1.id,
                      uren=8, tarief=k1.tarief_uur)
    await add_werkdag(seeded_db, datum='2026-02-02', klant_id=k2.id,
                      uren=9, tarief=k2.tarief_uur)

    w1 = await get_werkdagen(seeded_db, jaar=2026, klant_id=k1.id)
    w2 = await get_werkdagen(seeded_db, jaar=2026, klant_id=k2.id)
    assert len(w1) == 1
    assert len(w2) == 1


@pytest.mark.asyncio
async def test_ongefactureerd_filter(seeded_db):
    """Alleen ongefactureerde werkdagen ophalen."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_werkdag(seeded_db, datum='2026-02-01', klant_id=kid,
                      uren=8, tarief=77.50)
    await add_werkdag(seeded_db, datum='2026-02-02', klant_id=kid,
                      uren=9, tarief=77.50, factuurnummer='2026-099')
    await add_werkdag(seeded_db, datum='2026-02-03', klant_id=kid,
                      uren=8, tarief=77.50, factuurnummer='2026-100')

    ongefact = await get_werkdagen_ongefactureerd(seeded_db, klant_id=kid)
    assert len(ongefact) == 1
    assert ongefact[0].status == 'ongefactureerd'


def test_werkdag_form_edit_restores_historical_tarief():
    """A6 regression: source-pin guard.

    Editing a werkdag must restore ``werkdag.tarief`` after
    ``_load_klant_data`` (which sets the *current* klant default tarief).
    Without that restoration line, opening + saving an old werkdag whose
    klant's tarief_uur changed since then would silently overwrite the
    historical tarief on the row, shifting omzet for that year.

    The behaviour lives inside an async NiceGUI dialog handler that can
    only be exercised via a UI runtime — so we pin the source line
    directly. If a future refactor moves the edit-mode block, this test
    will fail and force the author to re-verify that tarief is still
    restored before km.
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / 'components' / 'werkdag_form.py'
    text = src.read_text()

    # The edit-mode block must restore tarief from the stored werkdag,
    # *after* _load_klant_data ran (so it overrides the klant default),
    # and *before* km is restored.
    pattern = re.compile(
        r'await\s+_load_klant_data\(werkdag\.klant_id\)'
        r'.*?'
        r'tarief_input\.value\s*=\s*werkdag\.tarief'
        r'.*?'
        r'km_input\.value\s*=\s*werkdag\.km',
        re.DOTALL,
    )
    assert pattern.search(text), (
        "Expected edit-mode block to restore werkdag.tarief between "
        "_load_klant_data and km restoration. The historical tarief "
        "preservation line may have been removed (A6 regression)."
    )


@pytest.mark.asyncio
async def test_link_werkdagen_to_factuur(seeded_db):
    """Werkdagen koppelen aan factuur."""
    from database import get_klanten, add_factuur
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    wid1 = await add_werkdag(seeded_db, datum='2026-02-01', klant_id=kid,
                              uren=8, tarief=77.50)
    wid2 = await add_werkdag(seeded_db, datum='2026-02-02', klant_id=kid,
                              uren=9, tarief=77.50)

    # Create factuur so the JOIN can derive status
    await add_factuur(seeded_db, nummer='2026-001', klant_id=kid,
                      datum='2026-02-02', totaal_bedrag=1317.50,
                      status='verstuurd')

    await link_werkdagen_to_factuur(
        seeded_db, werkdag_ids=[wid1, wid2], factuurnummer='2026-001'
    )

    werkdagen = await get_werkdagen(seeded_db, jaar=2026)
    for w in werkdagen:
        assert w.status == 'gefactureerd'
        assert w.factuurnummer == '2026-001'


@pytest.mark.asyncio
async def test_uren_criterium_excludes_achterwacht(seeded_db):
    """Achterwacht (urennorm=0) telt NIET mee voor urencriterium."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    # Reguliere werkdag (telt mee)
    await add_werkdag(seeded_db, datum='2026-02-01', klant_id=kid,
                      uren=9, tarief=77.50, urennorm=1)
    # Achterwacht (telt NIET mee)
    await add_werkdag(seeded_db, datum='2026-02-02', klant_id=kid,
                      uren=12, tarief=77.50, urennorm=0)

    uren_norm = await get_uren_totaal(seeded_db, jaar=2026, urennorm_only=True)
    uren_alle = await get_uren_totaal(seeded_db, jaar=2026, urennorm_only=False)

    assert uren_norm == 9  # alleen reguliere werkdag
    assert uren_alle == 21  # beide
