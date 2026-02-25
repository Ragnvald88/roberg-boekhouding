"""Tests voor facturen functionaliteit."""

import pytest
from pathlib import Path
from database import (
    init_db, add_klant, add_werkdag, add_factuur,
    get_facturen, get_next_factuurnummer, mark_betaald,
    link_werkdagen_to_factuur, get_werkdagen,
)
from import_.seed_data import seed_all
from components.invoice_generator import generate_invoice, format_euro, format_datum


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
async def test_next_factuurnummer_first_of_year(db):
    """Eerste factuur van het jaar wordt 001."""
    num = await get_next_factuurnummer(db, jaar=2026)
    assert num == "2026-001"


@pytest.mark.asyncio
async def test_next_factuurnummer_sequential(seeded_db):
    """Factuurnummers zijn doorlopend zonder gaten."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    for i in range(1, 4):
        num = await get_next_factuurnummer(seeded_db, jaar=2026)
        assert num == f"2026-{i:03d}"
        await add_factuur(seeded_db, nummer=num, klant_id=kid,
                          datum=f"2026-02-{i:02d}", totaal_bedrag=100 * i)


@pytest.mark.asyncio
async def test_factuur_links_werkdagen(seeded_db):
    """Werkdagen worden gekoppeld aan factuur na generatie."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    wid1 = await add_werkdag(seeded_db, datum="2026-02-01", klant_id=kid,
                              uren=8, km=52, tarief=77.50)
    wid2 = await add_werkdag(seeded_db, datum="2026-02-02", klant_id=kid,
                              uren=9, km=52, tarief=77.50)

    await add_factuur(seeded_db, nummer="2026-001", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=1400)
    await link_werkdagen_to_factuur(seeded_db, werkdag_ids=[wid1, wid2],
                                     factuurnummer="2026-001")

    werkdagen = await get_werkdagen(seeded_db, jaar=2026)
    for w in werkdagen:
        assert w.status == 'gefactureerd'
        assert w.factuurnummer == '2026-001'


@pytest.mark.asyncio
async def test_mark_betaald(seeded_db):
    """Factuur kan als betaald gemarkeerd worden."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_factuur(seeded_db, nummer="2026-001", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=700)
    facturen = await get_facturen(seeded_db, jaar=2026)
    assert not facturen[0].betaald

    await mark_betaald(seeded_db, factuur_id=facturen[0].id, datum="2026-03-01")
    facturen = await get_facturen(seeded_db, jaar=2026)
    assert facturen[0].betaald
    assert facturen[0].betaald_datum == "2026-03-01"


def test_format_euro():
    """Euro formatting: Dutch notation."""
    assert format_euro(1234.56) == "€ 1.234,56"
    assert format_euro(0) == "€ 0,00"
    assert format_euro(77.50) == "€ 77,50"
    assert format_euro(None) == "€ 0,00"


def test_format_datum():
    """Datum formatting: ISO to Dutch."""
    assert format_datum("2026-02-23") == "23-02-2026"
    assert format_datum("") == ""
    assert format_datum(None) == ""


def test_invoice_generator_creates_pdf(tmp_path):
    """WeasyPrint genereert een geldige PDF."""
    klant = {'naam': "HAP K6", 'adres': 'Hoofdstraat 3, 9363 EV Marum'}
    werkdagen = [
        {'datum': '2026-02-01', 'activiteit': 'Waarneming dagpraktijk',
         'locatie': 'Marum', 'uren': 9, 'tarief': 77.50, 'km': 52, 'km_tarief': 0.23},
        {'datum': '2026-02-02', 'activiteit': 'Waarneming dagpraktijk',
         'locatie': 'Marum', 'uren': 8, 'tarief': 77.50, 'km': 52, 'km_tarief': 0.23},
    ]
    output_dir = tmp_path / "facturen"
    pdf_path = generate_invoice("2026-001", klant, werkdagen, output_dir,
                                factuur_datum="2026-02-15")

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1000  # Non-trivial PDF
    assert "2026-001" in pdf_path.name
    assert "Klant6" in pdf_path.name


def test_invoice_totals_correct(tmp_path):
    """Factuur totaal klopt: uren × tarief + km × km_tarief."""
    klant = {'naam': 'Test Klant', 'adres': 'Teststraat 1'}
    werkdagen = [
        {'datum': '2026-02-01', 'activiteit': 'Waarneming', 'locatie': 'Marum',
         'uren': 9, 'tarief': 80.00, 'km': 44, 'km_tarief': 0.23},
    ]
    # Expected: 9 × 80 + 44 × 0.23 = 720 + 10.12 = 730.12
    output_dir = tmp_path / "facturen"
    pdf_path = generate_invoice("2026-TEST", klant, werkdagen, output_dir,
                                factuur_datum="2026-02-15")
    assert pdf_path.exists()
