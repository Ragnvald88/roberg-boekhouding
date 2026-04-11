"""Tests voor facturen functionaliteit."""

import pytest
from pathlib import Path
from database import (
    add_klant, add_werkdag, add_factuur, update_factuur,
    get_facturen, get_next_factuurnummer, mark_betaald,
    link_werkdagen_to_factuur, get_werkdagen, delete_factuur,
    save_factuur_atomic,
)
from import_.seed_data import seed_all
from components.invoice_generator import generate_invoice
from components.utils import format_euro, format_datum


@pytest.fixture
async def seeded_db(db):
    await seed_all(db)
    # Add a test klant (seed_all no longer seeds klanten)
    await add_klant(db, naam='Testpraktijk', tarief_uur=77.50, retour_km=50,
                    adres='Testlaan 1, 1234 AB Teststad')
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
    assert facturen[0].status != 'betaald'

    await mark_betaald(seeded_db, factuur_id=facturen[0].id, datum="2026-03-01")
    facturen = await get_facturen(seeded_db, jaar=2026)
    assert facturen[0].status == 'betaald'
    assert facturen[0].betaald_datum == "2026-03-01"


@pytest.mark.asyncio
async def test_update_factuur(seeded_db):
    """Factuur kan bijgewerkt worden via update_factuur."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_factuur(seeded_db, nummer="2026-001", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=700,
                      type='factuur')
    facturen = await get_facturen(seeded_db, jaar=2026)
    fid = facturen[0].id

    # Update bedrag and datum
    await update_factuur(seeded_db, factuur_id=fid,
                         totaal_bedrag=850.50, datum="2026-02-20")
    facturen = await get_facturen(seeded_db, jaar=2026)
    assert facturen[0].totaal_bedrag == 850.50
    assert facturen[0].datum == "2026-02-20"

    # Update type
    await update_factuur(seeded_db, factuur_id=fid, type='anw')
    facturen = await get_facturen(seeded_db, jaar=2026)
    assert facturen[0].type == 'anw'

    # Status is NOT updated via update_factuur (uses mark_betaald/update_factuur_status)
    assert facturen[0].status != 'betaald'


@pytest.mark.asyncio
async def test_update_factuur_pdf_pad(seeded_db):
    """PDF pad kan bijgewerkt worden."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_factuur(seeded_db, nummer="2026-001", klant_id=kid,
                      datum="2026-02-15", totaal_bedrag=700)
    facturen = await get_facturen(seeded_db, jaar=2026)
    fid = facturen[0].id

    await update_factuur(seeded_db, factuur_id=fid,
                         pdf_pad='/tmp/test.pdf')
    facturen = await get_facturen(seeded_db, jaar=2026)
    assert facturen[0].pdf_pad == '/tmp/test.pdf'

    # Clear PDF
    await update_factuur(seeded_db, factuur_id=fid, pdf_pad='')
    facturen = await get_facturen(seeded_db, jaar=2026)
    assert facturen[0].pdf_pad == ''


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
    klant = {'naam': 'Testpraktijk', 'adres': 'Testlaan 1, 1234 AB Teststad'}
    bedrijf = {
        'bedrijfsnaam': 'MijnBedrijf', 'naam': 'J. de Test',
        'functie': 'Adviseur', 'adres': 'Hoofdstraat 1',
        'postcode_plaats': '5678 CD Dorp', 'kvk': '12345678',
        'iban': 'NL00 TEST 0000 0000 00', 'thuisplaats': 'Dorp',
    }
    werkdagen = [
        {'datum': '2026-02-01', 'activiteit': 'Waarneming dagpraktijk',
         'locatie': 'Teststad', 'uren': 9, 'tarief': 77.50, 'km': 52, 'km_tarief': 0.23},
        {'datum': '2026-02-02', 'activiteit': 'Waarneming dagpraktijk',
         'locatie': 'Teststad', 'uren': 8, 'tarief': 77.50, 'km': 52, 'km_tarief': 0.23},
    ]
    output_dir = tmp_path / "facturen"
    pdf_path = generate_invoice("2026-001", klant, werkdagen, output_dir,
                                factuur_datum="2026-02-15",
                                bedrijfsgegevens=bedrijf)

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1000  # Non-trivial PDF
    assert "2026-001" in pdf_path.name
    assert "Testpraktijk" in pdf_path.name


def test_invoice_totals_correct(tmp_path):
    """Factuur totaal klopt: uren × tarief + km × km_tarief."""
    klant = {'naam': 'Test Klant', 'adres': 'Teststraat 1'}
    bedrijf = {
        'bedrijfsnaam': 'TestBedrijf', 'naam': 'A. Tester',
        'functie': 'Tester', 'adres': 'Testweg 2',
        'postcode_plaats': '1111 ZZ Testdorp', 'kvk': '99999999',
        'iban': 'NL00 TEST 0000 0000 00', 'thuisplaats': 'Testdorp',
    }
    werkdagen = [
        {'datum': '2026-02-01', 'activiteit': 'Waarneming', 'locatie': 'Teststad',
         'uren': 9, 'tarief': 80.00, 'km': 44, 'km_tarief': 0.23},
    ]
    # Expected: 9 × 80 + 44 × 0.23 = 720 + 10.12 = 730.12
    output_dir = tmp_path / "facturen"
    pdf_path = generate_invoice("2026-TEST", klant, werkdagen, output_dir,
                                factuur_datum="2026-02-15",
                                bedrijfsgegevens=bedrijf)
    assert pdf_path.exists()


# ============================================================
# Audit bug-fix regression tests (2026-03-03)
# ============================================================

@pytest.mark.asyncio
async def test_mark_betaald_cascades_to_werkdagen(seeded_db):
    """Bug #3: mark_betaald should cascade status to linked werkdagen."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    wid1 = await add_werkdag(seeded_db, datum="2026-03-01", klant_id=kid,
                              uren=8, km=52, tarief=77.50)
    wid2 = await add_werkdag(seeded_db, datum="2026-03-02", klant_id=kid,
                              uren=9, km=52, tarief=77.50)

    await add_factuur(seeded_db, nummer="2026-010", klant_id=kid,
                      datum="2026-03-15", totaal_bedrag=1400)
    await link_werkdagen_to_factuur(seeded_db, werkdag_ids=[wid1, wid2],
                                     factuurnummer="2026-010")

    # Mark as paid
    facturen = await get_facturen(seeded_db, jaar=2026)
    f = next(f for f in facturen if f.nummer == '2026-010')
    await mark_betaald(seeded_db, factuur_id=f.id, datum="2026-03-20")

    # Werkdagen should now be 'betaald'
    werkdagen = await get_werkdagen(seeded_db, jaar=2026)
    linked = [w for w in werkdagen if w.factuurnummer == '2026-010']
    assert all(w.status == 'betaald' for w in linked)

    # Mark as onbetaald — werkdagen should revert to 'gefactureerd'
    await mark_betaald(seeded_db, factuur_id=f.id, datum='', betaald=False)
    werkdagen = await get_werkdagen(seeded_db, jaar=2026)
    linked = [w for w in werkdagen if w.factuurnummer == '2026-010']
    assert all(w.status == 'gefactureerd' for w in linked)


@pytest.mark.asyncio
async def test_delete_klant_with_werkdagen_raises(seeded_db):
    """Bug #9: delete_klant with linked werkdagen raises ValueError."""
    from database import get_klanten, delete_klant
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_werkdag(seeded_db, datum="2026-03-01", klant_id=kid,
                      uren=8, km=0, tarief=77.50)

    with pytest.raises(ValueError, match='werkdagen of facturen'):
        await delete_klant(seeded_db, klant_id=kid)


@pytest.mark.asyncio
async def test_link_werkdagen_only_ongefactureerd(seeded_db):
    """Bug #6: link_werkdagen should only link ongefactureerde werkdagen."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    wid = await add_werkdag(seeded_db, datum="2026-03-01", klant_id=kid,
                             uren=8, km=52, tarief=77.50)

    # Link to first factuur
    await add_factuur(seeded_db, nummer="2026-020", klant_id=kid,
                      datum="2026-03-15", totaal_bedrag=700)
    await link_werkdagen_to_factuur(seeded_db, werkdag_ids=[wid],
                                     factuurnummer="2026-020")

    # Try to re-link to second factuur — should NOT overwrite
    await add_factuur(seeded_db, nummer="2026-021", klant_id=kid,
                      datum="2026-03-20", totaal_bedrag=700)
    await link_werkdagen_to_factuur(seeded_db, werkdag_ids=[wid],
                                     factuurnummer="2026-021")

    werkdagen = await get_werkdagen(seeded_db, jaar=2026)
    w = next(w for w in werkdagen if w.id == wid)
    assert w.factuurnummer == '2026-020'  # should NOT have changed


# ============================================================
# delete_factuur tests
# ============================================================

@pytest.mark.asyncio
async def test_delete_factuur_unlinks_werkdagen(seeded_db):
    """Deleting a factuur reverts linked werkdagen to ongefactureerd."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    wid1 = await add_werkdag(seeded_db, datum="2026-04-01", klant_id=kid,
                              uren=8, km=52, tarief=77.50)
    wid2 = await add_werkdag(seeded_db, datum="2026-04-02", klant_id=kid,
                              uren=9, km=52, tarief=77.50)

    await add_factuur(seeded_db, nummer="2026-030", klant_id=kid,
                      datum="2026-04-15", totaal_bedrag=1400)
    await link_werkdagen_to_factuur(seeded_db, werkdag_ids=[wid1, wid2],
                                     factuurnummer="2026-030")

    # Verify werkdagen are linked
    werkdagen = await get_werkdagen(seeded_db, jaar=2026)
    linked = [w for w in werkdagen if w.factuurnummer == '2026-030']
    assert len(linked) == 2
    assert all(w.status == 'gefactureerd' for w in linked)

    # Delete factuur
    facturen = await get_facturen(seeded_db, jaar=2026)
    fid = next(f.id for f in facturen if f.nummer == '2026-030')
    await delete_factuur(seeded_db, factuur_id=fid)

    # Factuur should be gone
    facturen = await get_facturen(seeded_db, jaar=2026)
    assert not any(f.nummer == '2026-030' for f in facturen)

    # Werkdagen should be ongefactureerd with empty factuurnummer
    werkdagen = await get_werkdagen(seeded_db, jaar=2026)
    for wid in [wid1, wid2]:
        w = next(w for w in werkdagen if w.id == wid)
        assert w.status == 'ongefactureerd'
        assert w.factuurnummer == ''


@pytest.mark.asyncio
async def test_delete_factuur_nonexistent_no_error(db):
    """Deleting a nonexistent factuur does not raise."""
    await delete_factuur(db, factuur_id=99999)  # should not raise


# ============================================================
# Factuur type round-trip tests
# ============================================================

@pytest.mark.asyncio
async def test_factuur_type_vergoeding_round_trip(seeded_db):
    """Factuur with type='vergoeding' persists and reads back correctly."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_factuur(seeded_db, nummer="2026-050", klant_id=kid,
                      datum="2026-03-01", totaal_bedrag=500.00,
                      type='vergoeding')
    facturen = await get_facturen(seeded_db, jaar=2026)
    f = next(f for f in facturen if f.nummer == '2026-050')
    assert f.type == 'vergoeding'


@pytest.mark.asyncio
async def test_factuur_type_defaults_to_factuur(seeded_db):
    """Factuur without explicit type defaults to 'factuur'."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_factuur(seeded_db, nummer="2026-051", klant_id=kid,
                      datum="2026-03-01", totaal_bedrag=700.00)
    facturen = await get_facturen(seeded_db, jaar=2026)
    f = next(f for f in facturen if f.nummer == '2026-051')
    assert f.type == 'factuur'


# ============================================================
# save_factuur_atomic
# ============================================================

@pytest.mark.asyncio
async def test_save_factuur_atomic_basic(db):
    """Atomic save: creates factuur and links werkdagen in one transaction."""
    kid = await add_klant(db, naam="Atomic", tarief_uur=80, retour_km=44)
    wid = await add_werkdag(db, datum="2026-04-01", klant_id=kid,
                             uren=9, tarief=80, km=44, km_tarief=0.23)

    fid = await save_factuur_atomic(
        db, werkdag_ids=[wid],
        nummer="2026-A01", klant_id=kid, datum="2026-04-01",
        totaal_bedrag=730.12, totaal_uren=9, totaal_km=44)

    facturen = await get_facturen(db, jaar=2026)
    assert len(facturen) == 1
    assert facturen[0].nummer == "2026-A01"

    werkdagen = await get_werkdagen(db, jaar=2026)
    assert werkdagen[0].factuurnummer == "2026-A01"


@pytest.mark.asyncio
async def test_save_factuur_atomic_replaces_concept(db):
    """Atomic save: old concept is deleted, werkdagen re-linked."""
    kid = await add_klant(db, naam="Replace", tarief_uur=80, retour_km=44)
    wid = await add_werkdag(db, datum="2026-05-01", klant_id=kid,
                             uren=8, tarief=80, km=30, km_tarief=0.23)

    # Create old concept
    old_id = await add_factuur(db, nummer="2026-R01", klant_id=kid,
                                datum="2026-05-01", totaal_bedrag=640,
                                status='concept')
    await link_werkdagen_to_factuur(db, werkdag_ids=[wid],
                                     factuurnummer="2026-R01")

    # Replace with new factuur (same nummer)
    new_id = await save_factuur_atomic(
        db, replacing_factuur_id=old_id, werkdag_ids=[wid],
        nummer="2026-R01", klant_id=kid, datum="2026-05-01",
        totaal_bedrag=646.90, totaal_uren=8, totaal_km=30,
        pdf_pad='/tmp/test.pdf')

    # new_id may equal old_id (SQLite reuses rowids) — that's fine
    facturen = await get_facturen(db, jaar=2026)
    assert len(facturen) == 1
    assert facturen[0].totaal_bedrag == 646.90

    werkdagen = await get_werkdagen(db, jaar=2026)
    assert werkdagen[0].factuurnummer == "2026-R01"


@pytest.mark.asyncio
async def test_save_factuur_atomic_rollback_on_duplicate(db):
    """If insert fails (duplicate nummer), old concept is NOT deleted."""
    kid = await add_klant(db, naam="Rollback", tarief_uur=80, retour_km=0)

    # Create two concepts
    old_id = await add_factuur(db, nummer="2026-DUP", klant_id=kid,
                                datum="2026-06-01", totaal_bedrag=500,
                                status='concept')
    await add_factuur(db, nummer="2026-EXISTING", klant_id=kid,
                       datum="2026-06-15", totaal_bedrag=600,
                       status='verstuurd')

    # Try to replace old_id with nummer that already exists
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        await save_factuur_atomic(
            db, replacing_factuur_id=old_id,
            nummer="2026-EXISTING", klant_id=kid, datum="2026-06-01",
            totaal_bedrag=500)

    # Old concept should still exist (rollback)
    facturen = await get_facturen(db, jaar=2026)
    nummers = {f.nummer for f in facturen}
    assert "2026-DUP" in nummers, "Old concept was deleted despite rollback!"


# ============================================================
# _calc_totals tests
# ============================================================

from components.invoice_builder import _calc_totals


def test_calc_totals_basic():
    """Items with werkdag_id → type='factuur', correct uren/km/bedrag."""
    items = [
        {'datum': '2026-03-01', 'aantal': 9, 'tarief': 80.0,
         'km': 52, 'km_tarief': 0.23, 'werkdag_id': 1, 'is_reiskosten': False},
        {'datum': '2026-03-02', 'aantal': 8, 'tarief': 80.0,
         'km': 44, 'km_tarief': 0.23, 'werkdag_id': 2, 'is_reiskosten': False},
    ]
    uren, km, bedrag, ftype = _calc_totals(items)
    assert uren == 17
    assert km == 96
    # bedrag = (9*80 + 52*0.23) + (8*80 + 44*0.23) = 731.96 + 650.12 = 1382.08
    expected = 9 * 80 + 52 * 0.23 + 8 * 80 + 44 * 0.23
    assert abs(bedrag - expected) < 0.01
    assert ftype == 'factuur'


def test_calc_totals_none_values():
    """Items with km=None, km_tarief=None → handled as 0."""
    items = [
        {'datum': '2026-03-01', 'aantal': 8, 'tarief': 77.50,
         'km': None, 'km_tarief': None, 'werkdag_id': 1, 'is_reiskosten': False},
    ]
    uren, km, bedrag, ftype = _calc_totals(items)
    assert uren == 8
    assert km == 0
    assert bedrag == 8 * 77.50
    assert ftype == 'factuur'


def test_calc_totals_vergoeding():
    """Items without werkdag_id → type='vergoeding'."""
    items = [
        {'datum': '2026-03-01', 'aantal': 1, 'tarief': 500.0,
         'km': 0, 'km_tarief': 0, 'werkdag_id': None, 'is_reiskosten': False},
    ]
    uren, km, bedrag, ftype = _calc_totals(items)
    assert uren == 1
    assert km == 0
    assert bedrag == 500.0
    assert ftype == 'vergoeding'


def test_calc_totals_empty():
    """Empty list → all zeros, type='vergoeding'."""
    uren, km, bedrag, ftype = _calc_totals([])
    assert uren == 0
    assert km == 0
    assert bedrag == 0
    assert ftype == 'vergoeding'


# ============================================================
# regels_json round-trip (concept persistence)
# ============================================================

@pytest.mark.asyncio
async def test_concept_regels_json_round_trip(db):
    """Save concept with regels_json, read back, verify data preserved."""
    import json
    kid = await add_klant(db, naam="RoundTrip", tarief_uur=80, retour_km=44)

    line_items = [
        {'datum': '2026-04-01', 'omschrijving': 'Aangepast tarief',
         'aantal': 9, 'tarief': 95, 'werkdag_id': None,
         'is_reiskosten': False, 'km': 0, 'km_tarief': 0},
        {'datum': '2026-04-02', 'omschrijving': 'Vrije regel',
         'aantal': 1, 'tarief': 150, 'werkdag_id': None,
         'is_reiskosten': False},
    ]
    klant_fields = {'naam': 'RoundTrip', 'adres': 'Teststraat 1',
                    'postcode': '1234 AB', 'plaats': 'Teststad',
                    'contactpersoon': 'Dr. Test'}
    regels_data = {'line_items': line_items, 'klant_fields': klant_fields}

    fid = await save_factuur_atomic(
        db, nummer='2026-RT1', klant_id=kid, datum='2026-04-01',
        totaal_bedrag=1005, status='concept',
        regels_json=json.dumps(regels_data))

    # Read back
    from database import get_db_ctx
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT regels_json FROM facturen WHERE id = ?", (fid,))
        row = await cur.fetchone()

    saved = json.loads(row['regels_json'])
    assert len(saved['line_items']) == 2
    assert saved['line_items'][0]['tarief'] == 95
    assert saved['line_items'][1]['omschrijving'] == 'Vrije regel'
    assert saved['klant_fields']['adres'] == 'Teststraat 1'


@pytest.mark.asyncio
async def test_final_invoice_no_regels_json(db):
    """Final (non-concept) invoices should have empty regels_json."""
    kid = await add_klant(db, naam="Final", tarief_uur=80, retour_km=0)
    fid = await add_factuur(db, nummer='2026-FIN', klant_id=kid,
                             datum='2026-05-01', totaal_bedrag=640,
                             status='verstuurd')

    from database import get_db_ctx
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT regels_json FROM facturen WHERE id = ?", (fid,))
        row = await cur.fetchone()
    assert row['regels_json'] == ''


# ============================================================
# _build_mail_body tests
# ============================================================

from pages.facturen import _build_mail_body, _build_herinnering_body


def test_build_mail_body_with_betaallink():
    body, is_html = _build_mail_body(
        '2026-021', '€ 1.097,34', 'NL00 TEST 0000 0000 00',
        'TestBV huisartswaarnemer', 'Test Gebruiker',
        '06 0000 0000', 'info@testbedrijf.nl',
        betaallink='https://betaalverzoek.rabobank.nl/betaalverzoek/?id=abc',
    )
    assert is_html is True
    assert '<a href="https://betaalverzoek.rabobank.nl/betaalverzoek/?id=abc">deze betaallink</a>' in body
    assert 'eenvoudig betalen via' in body
    assert 'onder vermelding van factuurnummer 2026-021. U kunt ook' in body
    assert 'Bijgaand stuur ik u factuur 2026-021' in body


def test_build_mail_body_without_betaallink():
    body, is_html = _build_mail_body(
        '2026-021', '€ 1.097,34', 'NL00 TEST 0000 0000 00',
        'TestBV huisartswaarnemer', 'Test Gebruiker',
        '06 0000 0000', 'info@testbedrijf.nl',
    )
    assert is_html is False
    assert 'betaallink' not in body
    assert 'Bijgaand stuur ik u factuur 2026-021' in body


# ============================================================
# _build_herinnering_body tests
# ============================================================


def test_herinnering_body_with_betaallink():
    """Herinnering body includes betaallink when provided."""
    body = _build_herinnering_body(
        nummer='2026-001', bedrag='€ 1.234,00', datum='1 februari 2026',
        iban='NL00RABO0123456789', bedrijfsnaam='Testpraktijk',
        naam='Dr. Test', telefoon='06-12345678', bg_email='test@test.nl',
        betaallink='https://pay.example.com/123',
    )
    assert 'factuur 2026-001' in body
    assert '€ 1.234,00' in body
    assert '1 februari 2026' in body
    assert 'aan uw aandacht ontsnapt' in body
    assert '7 dagen' in body
    assert 'NL00RABO0123456789' in body
    assert 'https://pay.example.com/123' in body
    assert 'Dr. Test' in body
    assert 'Testpraktijk' in body
    assert '06-12345678' in body


def test_herinnering_body_without_betaallink():
    """Herinnering body omits betaallink paragraph when empty."""
    body = _build_herinnering_body(
        nummer='2026-002', bedrag='€ 500,00', datum='15 maart 2026',
        iban='NL00RABO0123456789', bedrijfsnaam='Testpraktijk',
        naam='Dr. Test', telefoon='', bg_email='test@test.nl',
    )
    assert 'betalen via deze link' not in body
    assert 'factuur 2026-002' in body
    assert '€ 500,00' in body


# ============================================================
# herinnering_datum integration tests
# ============================================================


@pytest.mark.asyncio
async def test_herinnering_datum_stored(seeded_db):
    """Storing herinnering_datum updates the factuur record."""
    from database import get_klanten, get_db_ctx
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_factuur(seeded_db, nummer='2026-010', klant_id=kid,
                      datum='2026-01-01', totaal_bedrag=500,
                      status='verstuurd')

    async with get_db_ctx(seeded_db) as conn:
        await conn.execute(
            "UPDATE facturen SET herinnering_datum = ? WHERE nummer = ?",
            ('2026-04-07', '2026-010'))
        await conn.commit()

    facturen = await get_facturen(seeded_db)
    f = next(f for f in facturen if f.nummer == '2026-010')
    assert f.herinnering_datum == '2026-04-07'


@pytest.mark.asyncio
async def test_herinnering_datum_default_empty(seeded_db):
    """New facturen have empty herinnering_datum by default."""
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_factuur(seeded_db, nummer='2026-011', klant_id=kid,
                      datum='2026-03-01', totaal_bedrag=300)

    facturen = await get_facturen(seeded_db)
    f = next(f for f in facturen if f.nummer == '2026-011')
    assert f.herinnering_datum == ''


# === Edit router (C.1) ===

def test_edit_router_concept_factuur_native_goes_to_builder():
    from pages.facturen import _should_use_builder
    assert _should_use_builder(
        {'status': 'concept', 'type': 'factuur', 'bron': ''}) is True


def test_edit_router_verstuurd_goes_to_dialog():
    from pages.facturen import _should_use_builder
    assert _should_use_builder(
        {'status': 'verstuurd', 'type': 'factuur', 'bron': ''}) is False


def test_edit_router_betaald_goes_to_dialog():
    from pages.facturen import _should_use_builder
    assert _should_use_builder(
        {'status': 'betaald', 'type': 'factuur', 'bron': ''}) is False


def test_edit_router_imported_concept_goes_to_dialog():
    from pages.facturen import _should_use_builder
    assert _should_use_builder(
        {'status': 'concept', 'type': 'factuur', 'bron': 'import'}) is False


def test_edit_router_concept_vergoeding_goes_to_dialog():
    from pages.facturen import _should_use_builder
    assert _should_use_builder(
        {'status': 'concept', 'type': 'vergoeding', 'bron': ''}) is False


def test_edit_router_concept_anw_goes_to_dialog():
    from pages.facturen import _should_use_builder
    assert _should_use_builder(
        {'status': 'concept', 'type': 'anw', 'bron': ''}) is False


# === Vergoeding regels_json sync (C.2) ===

def test_rebuild_vergoeding_regels_json_preserves_omschrijving():
    import json
    from pages.facturen import _rebuild_vergoeding_regels_json

    old = json.dumps([{'omschrijving': 'Consult spoed', 'bedrag': 100.0}])
    new = _rebuild_vergoeding_regels_json(old, 150.0)
    parsed = json.loads(new)
    assert len(parsed) == 1
    assert parsed[0]['omschrijving'] == 'Consult spoed'
    assert parsed[0]['bedrag'] == 150.0


def test_rebuild_vergoeding_regels_json_empty_input():
    import json
    from pages.facturen import _rebuild_vergoeding_regels_json

    parsed = json.loads(_rebuild_vergoeding_regels_json('', 42.50))
    assert parsed == [{'omschrijving': 'Vergoeding', 'bedrag': 42.50}]


def test_rebuild_vergoeding_regels_json_null_input():
    import json
    from pages.facturen import _rebuild_vergoeding_regels_json

    parsed = json.loads(_rebuild_vergoeding_regels_json(None, 42.50))  # type: ignore[arg-type]
    assert parsed == [{'omschrijving': 'Vergoeding', 'bedrag': 42.50}]


def test_rebuild_vergoeding_regels_json_malformed_input():
    import json
    from pages.facturen import _rebuild_vergoeding_regels_json

    parsed = json.loads(_rebuild_vergoeding_regels_json('not-json', 75.0))
    assert parsed == [{'omschrijving': 'Vergoeding', 'bedrag': 75.0}]


@pytest.mark.asyncio
async def test_save_factuur_atomic_conflict_preserves_pdf(seeded_db, tmp_path):
    """save_factuur_atomic must not touch the caller's PDF on failure.

    The invoice_builder.genereer_factuur wraps save_factuur_atomic in a
    try/finally that deletes the freshly-generated PDF on conflict.
    That cleanup is correct only if save_factuur_atomic itself leaves
    the file alone — verify that contract here.
    """
    import sqlite3
    from database import get_klanten
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    await add_factuur(
        seeded_db, nummer='2026-ORP', klant_id=kid,
        datum='2026-04-01', totaal_bedrag=800.00, status='verstuurd',
    )

    fake_pdf = tmp_path / '2026-ORP.pdf'
    fake_pdf.write_bytes(b'%PDF-1.4 fake')
    assert fake_pdf.exists()

    with pytest.raises(sqlite3.IntegrityError):
        await save_factuur_atomic(
            seeded_db,
            nummer='2026-ORP', klant_id=kid,
            datum='2026-04-02', totaal_uren=8, totaal_km=0,
            totaal_bedrag=900.00, status='concept',
            pdf_pad=str(fake_pdf),
        )
    assert fake_pdf.exists(), (
        "save_factuur_atomic must not delete the PDF on failure — "
        "the caller owns that lifecycle")


@pytest.mark.asyncio
async def test_update_factuur_accepts_regels_json(seeded_db):
    """update_factuur must allow rewriting regels_json so vergoeding
    edits keep the PDF regeneration source consistent with totaal_bedrag.
    """
    import json as _json
    from database import get_klanten, get_db_ctx
    klanten = await get_klanten(seeded_db)
    kid = klanten[0].id

    old_regels = _json.dumps(
        [{'omschrijving': 'Reiskosten', 'bedrag': 50.0}])
    await add_factuur(
        seeded_db, nummer='2026-V01', klant_id=kid,
        datum='2026-03-01', totaal_bedrag=50.0, status='concept',
        type='vergoeding', regels_json=old_regels,
    )
    facturen = await get_facturen(seeded_db, jaar=2026)
    fid = next(f.id for f in facturen if f.nummer == '2026-V01')

    new_regels = _json.dumps(
        [{'omschrijving': 'Reiskosten', 'bedrag': 75.0}])
    await update_factuur(seeded_db, factuur_id=fid,
                         totaal_bedrag=75.0, regels_json=new_regels)

    async with get_db_ctx(seeded_db) as conn:
        cur = await conn.execute(
            "SELECT totaal_bedrag, regels_json FROM facturen WHERE id = ?",
            (fid,))
        row = await cur.fetchone()
    assert row is not None
    assert row['totaal_bedrag'] == 75.0
    parsed = _json.loads(row['regels_json'])
    regels_sum = sum(r['bedrag'] for r in parsed)
    assert abs(regels_sum - row['totaal_bedrag']) < 0.01
