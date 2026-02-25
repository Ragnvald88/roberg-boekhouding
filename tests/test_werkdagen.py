"""Tests voor werkdagen functionaliteit."""

import pytest
from database import (
    init_db, add_klant, add_werkdag, get_werkdagen,
    get_werkdagen_ongefactureerd, update_werkdag,
    link_werkdagen_to_factuur, get_uren_totaal,
)
from import_.seed_data import seed_all


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path


@pytest.fixture
async def seeded_db(db):
    await seed_all(db)
    return db


@pytest.mark.asyncio
async def test_add_werkdag_with_klant(seeded_db):
    """Werkdag toevoegen met klantgegevens."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    klant6 = next(k for k in klanten if 'Klant6' in k.naam)

    wid = await add_werkdag(
        seeded_db, datum='2026-02-23', klant_id=klant6.id,
        uren=9, km=klant6.retour_km, tarief=klant6.tarief_uur,
        code='WERKDAG', activiteit='Waarneming dagpraktijk',
    )
    assert wid > 0

    werkdagen = await get_werkdagen(seeded_db, jaar=2026)
    assert len(werkdagen) == 1
    w = werkdagen[0]
    assert w.klant_naam == klant6.naam
    assert w.uren == 9
    assert w.km == 52
    assert w.tarief == 77.50


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
                      uren=8, tarief=77.50, status='ongefactureerd')
    await add_werkdag(seeded_db, datum='2026-02-02', klant_id=kid,
                      uren=9, tarief=77.50, status='gefactureerd')
    await add_werkdag(seeded_db, datum='2026-02-03', klant_id=kid,
                      uren=8, tarief=77.50, status='betaald')

    ongefact = await get_werkdagen_ongefactureerd(seeded_db, klant_id=kid)
    assert len(ongefact) == 1
    assert ongefact[0].status == 'ongefactureerd'


@pytest.mark.asyncio
async def test_link_werkdagen_to_factuur(seeded_db):
    """Werkdagen koppelen aan factuur."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    wid1 = await add_werkdag(seeded_db, datum='2026-02-01', klant_id=kid,
                              uren=8, tarief=77.50)
    wid2 = await add_werkdag(seeded_db, datum='2026-02-02', klant_id=kid,
                              uren=9, tarief=77.50)

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
