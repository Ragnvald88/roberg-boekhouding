"""Tests voor database schema en CRUD operaties."""

import pytest
import aiosqlite
from database import (
    init_db, get_db, get_db_ctx, add_klant, get_klanten, add_werkdag,
    get_werkdagen, update_werkdag, delete_werkdag,
    get_werkdagen_ongefactureerd,
    add_factuur, get_facturen, get_next_factuurnummer,
    add_uitgave, get_uitgaven, get_uitgaven_per_categorie,
    save_factuur_atomic,
)


@pytest.mark.asyncio
async def test_init_creates_tables(db):
    async with aiosqlite.connect(db) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in await cursor.fetchall()}
    expected = {'klanten', 'klant_locaties', 'werkdagen', 'facturen', 'uitgaven',
                'banktransacties', 'fiscale_params', 'bedrijfsgegevens',
                'aangifte_documenten'}
    assert tables >= expected


@pytest.mark.asyncio
async def test_pragma_foreign_keys(db):
    conn = await get_db(db)
    try:
        cur = await conn.execute("PRAGMA foreign_keys")
        row = await cur.fetchone()
        assert row[0] == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_pragma_wal_mode(db):
    conn = await get_db(db)
    try:
        cur = await conn.execute("PRAGMA journal_mode")
        row = await cur.fetchone()
        assert row[0] == 'wal'
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_klant_crud(db):
    kid = await add_klant(db, naam="Testpraktijk", tarief_uur=77.50, retour_km=52)
    assert kid > 0
    klanten = await get_klanten(db)
    assert len(klanten) == 1
    assert klanten[0].naam == "Testpraktijk"
    assert klanten[0].tarief_uur == 77.50
    assert klanten[0].retour_km == 52


@pytest.mark.asyncio
async def test_werkdag_crud(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    wid = await add_werkdag(db, datum="2026-02-23", klant_id=kid,
                            uren=9, km=44, tarief=80)
    assert wid > 0
    werkdagen = await get_werkdagen(db, jaar=2026)
    assert len(werkdagen) == 1
    assert werkdagen[0].uren == 9
    assert werkdagen[0].km == 44
    assert werkdagen[0].klant_naam == "Test"


@pytest.mark.asyncio
async def test_werkdag_update(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    wid = await add_werkdag(db, datum="2026-02-23", klant_id=kid,
                            uren=9, km=44, tarief=80)
    await update_werkdag(db, werkdag_id=wid, uren=8, opmerking="Aangepast")
    werkdagen = await get_werkdagen(db, jaar=2026)
    assert werkdagen[0].uren == 8
    assert werkdagen[0].opmerking == "Aangepast"


@pytest.mark.asyncio
async def test_werkdag_delete(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    wid = await add_werkdag(db, datum="2026-02-23", klant_id=kid,
                            uren=9, km=44, tarief=80)
    await delete_werkdag(db, werkdag_id=wid)
    werkdagen = await get_werkdagen(db, jaar=2026)
    assert len(werkdagen) == 0


@pytest.mark.asyncio
async def test_get_werkdag_by_id_returns_full_werkdag(db):
    """Happy-path: roundtrip levert volledige Werkdag terug."""
    from database import (
        add_klant, add_werkdag, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=10)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8.0,
        km=20, tarief=80, opmerking='Test')
    w = await get_werkdag_by_id(db, werkdag_id=wid)
    assert w is not None
    assert w.id == wid
    assert w.datum == '2026-05-15'
    assert w.klant_id == kid
    assert w.uren == 8.0
    assert w.opmerking == 'Test'
    assert w.klant_naam == 'Test'  # joined via _row_to_werkdag


@pytest.mark.asyncio
async def test_get_werkdag_by_id_returns_none_for_missing(db):
    """Non-existent ID → None, geen exception."""
    from database import get_werkdag_by_id
    w = await get_werkdag_by_id(db, werkdag_id=99999)
    assert w is None


@pytest.mark.asyncio
async def test_get_werkdag_by_id_computes_betaald_status(db):
    """JOIN-and-CASE pad uniek voor deze helper: gefactureerd + betaald
    levert computed_status='betaald'. Code-review #3 — locks in semantiek
    die `_row_to_werkdag` tests via `get_werkdagen` niet expliciet dekken
    voor de single-row variant."""
    from database import (
        add_klant, add_werkdag, add_factuur, mark_betaald,
        get_werkdag_by_id, link_werkdagen_to_factuur,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8.0, tarief=80)
    await add_factuur(
        db, nummer='2026-001', klant_id=kid, datum='2026-05-15',
        totaal_bedrag=640, status='concept')
    await link_werkdagen_to_factuur(
        db, werkdag_ids=[wid], factuurnummer='2026-001')
    facturen = await __import__('database').get_facturen(db)
    fid = next(f.id for f in facturen if f.nummer == '2026-001')
    await mark_betaald(db, factuur_id=fid, datum='2026-05-20')

    w = await get_werkdag_by_id(db, werkdag_id=wid)
    assert w is not None
    assert w.factuurnummer == '2026-001'
    assert w.status == 'betaald'


@pytest.mark.asyncio
async def test_duplicate_werkdag_copies_all_fields(db):
    """Dupliceren kopieert alle velden behalve factuurnummer."""
    from database import (
        add_klant, add_klant_locatie, add_werkdag,
        get_werkdag_by_id, duplicate_werkdag,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=10)
    lid = await add_klant_locatie(
        db, klant_id=kid, naam='Locatie A', retour_km=15)
    src_id = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid,
        code='WERKDAG', activiteit='Waarneming dagpraktijk',
        locatie='Locatie A', locatie_id=lid,
        uren=8.0, km=20, tarief=80, km_tarief=0.23,
        opmerking='Bron-werkdag', urennorm=1,
        factuurnummer='2026-001')

    new_id = await duplicate_werkdag(
        db, werkdag_id=src_id, target_datum='2026-05-22')

    assert new_id != src_id
    new_w = await get_werkdag_by_id(db, werkdag_id=new_id)
    assert new_w is not None
    assert new_w.datum == '2026-05-22'
    assert new_w.klant_id == kid
    assert new_w.code == 'WERKDAG'
    assert new_w.activiteit == 'Waarneming dagpraktijk'
    assert new_w.locatie == 'Locatie A'
    assert new_w.locatie_id == lid
    assert new_w.uren == 8.0
    assert new_w.km == 20
    assert new_w.tarief == 80
    assert new_w.km_tarief == 0.23
    assert new_w.opmerking == 'Bron-werkdag'
    assert new_w.urennorm == 1
    # Factuurnummer NIET meegekopieerd.
    assert new_w.factuurnummer == ''

    # Bron is ongewijzigd.
    src_w = await get_werkdag_by_id(db, werkdag_id=src_id)
    assert src_w.datum == '2026-05-15'
    assert src_w.factuurnummer == '2026-001'


@pytest.mark.asyncio
async def test_duplicate_werkdag_raises_on_missing_source(db):
    from database import duplicate_werkdag
    with pytest.raises(ValueError, match='99999'):
        await duplicate_werkdag(
            db, werkdag_id=99999, target_datum='2026-05-22')


@pytest.mark.asyncio
async def test_duplicate_werkdag_raises_on_invalid_datum(db):
    from database import (
        add_klant, add_werkdag, duplicate_werkdag,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    src = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80)
    # Tighten match — anders zou een onverwante ValueError elders in de
    # setup ook silent-pass dit assertion.
    with pytest.raises(ValueError, match='not-a-date'):
        await duplicate_werkdag(
            db, werkdag_id=src, target_datum='not-a-date')


@pytest.mark.asyncio
async def test_duplicate_werkdag_allows_blocker_on_target(db):
    """Consistent met 'Extra werkdag' op blocker-dag (vakantie + dienst)."""
    from database import (
        add_klant, add_werkdag, duplicate_werkdag,
        get_werkdag_by_id,
    )
    import services.agenda as agenda_svc
    from datetime import date as _date_cls

    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    src = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80)
    # Blocker op target-datum.
    await agenda_svc.add_blocker(
        db, datum=_date_cls(2026, 5, 22),
        kind='vacation', label='Vakantie')
    # Precondition: blocker is daadwerkelijk aangemaakt — anders test
    # silent-pass via "duplicate naar lege dag" (= Task 3 happy-path).
    blockers = await agenda_svc.list_blockers(
        db, _date_cls(2026, 5, 22), _date_cls(2026, 5, 22))
    assert len(blockers) == 1, 'precondition: blocker must exist'
    # Dupliceren mag — geen exception.
    new_id = await duplicate_werkdag(
        db, werkdag_id=src, target_datum='2026-05-22')
    new_w = await get_werkdag_by_id(db, werkdag_id=new_id)
    assert new_w.datum == '2026-05-22'


@pytest.mark.asyncio
async def test_duplicate_werkdag_preserves_zero_km_tarief(db):
    """ANW-werkdag heeft km_tarief=0 (geen reiskosten in tarief). MUST blijven 0
    in dupliceren — codex catch: `or 0.23` zou dit naar 0.23 platslaan."""
    from database import (
        add_klant, add_werkdag, duplicate_werkdag, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    src = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid,
        code='ANW', activiteit='ANW',
        uren=12, tarief=80, km_tarief=0)
    new_id = await duplicate_werkdag(
        db, werkdag_id=src, target_datum='2026-05-22')
    new_w = await get_werkdag_by_id(db, werkdag_id=new_id)
    assert new_w.km_tarief == 0


@pytest.mark.asyncio
async def test_duplicate_werkdag_preserves_zero_urennorm(db):
    """ACHTERWACHT/CONGRES-codes hebben urennorm=0 (telt niet voor 1225-norm).
    MUST blijven 0 in dupliceren — codex catch: `or 1` zou 0 → 1 maken."""
    from database import (
        add_klant, add_werkdag, duplicate_werkdag, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    src = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid,
        code='ACHTERWACHT', activiteit='Achterwacht',
        uren=0, tarief=0, urennorm=0)
    new_id = await duplicate_werkdag(
        db, werkdag_id=src, target_datum='2026-05-22')
    new_w = await get_werkdag_by_id(db, werkdag_id=new_id)
    assert new_w.urennorm == 0


@pytest.mark.asyncio
async def test_duplicate_werkdag_allows_same_date(db):
    """Dupliceren naar zelfde datum als bron — multi-shift dezelfde dag."""
    from database import (
        add_klant, add_werkdag, duplicate_werkdag, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    src = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80)
    new_id = await duplicate_werkdag(
        db, werkdag_id=src, target_datum='2026-05-15')
    assert new_id != src
    new_w = await get_werkdag_by_id(db, werkdag_id=new_id)
    assert new_w.datum == '2026-05-15'


@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_clears_factuurnummer_for_concept(db):
    """Concept-factuur unlink → factuurnummer leeg, factuur ongewijzigd."""
    from database import (
        add_klant, add_werkdag, add_factuur,
        unlink_werkdag_from_factuur, get_werkdag_by_id, get_facturen,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80,
        factuurnummer='2026-001')
    await add_factuur(
        db, nummer='2026-001', klant_id=kid, datum='2026-05-15',
        totaal_bedrag=640, status='concept')

    await unlink_werkdag_from_factuur(db, werkdag_id=wid)

    w = await get_werkdag_by_id(db, werkdag_id=wid)
    assert w.factuurnummer == ''
    facturen = await get_facturen(db)
    assert any(f.nummer == '2026-001' for f in facturen)


@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_clears_orphan_link(db):
    """Orphan-factuurnummer (factuur_id IS NULL) — ontkoppel mag."""
    from database import (
        add_klant, add_werkdag, unlink_werkdag_from_factuur,
        get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80,
        factuurnummer='2025-999')  # geen bijbehorende factuur-row
    await unlink_werkdag_from_factuur(db, werkdag_id=wid)
    w = await get_werkdag_by_id(db, werkdag_id=wid)
    assert w.factuurnummer == ''


@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_rejects_verstuurd(db):
    """Verstuurde factuur kan NIET ontkoppeld worden — boekhoudkundig."""
    from database import (
        add_klant, add_werkdag, add_factuur,
        unlink_werkdag_from_factuur, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80,
        factuurnummer='2026-001')
    await add_factuur(
        db, nummer='2026-001', klant_id=kid, datum='2026-05-15',
        totaal_bedrag=640, status='verstuurd')
    with pytest.raises(ValueError, match='verstuurd'):
        await unlink_werkdag_from_factuur(db, werkdag_id=wid)
    w = await get_werkdag_by_id(db, werkdag_id=wid)
    assert w.factuurnummer == '2026-001'  # ongewijzigd


@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_rejects_betaald(db):
    """Betaalde factuur — ontkoppelen ook geweigerd."""
    from database import (
        add_klant, add_werkdag, add_factuur,
        unlink_werkdag_from_factuur, get_werkdag_by_id,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80,
        factuurnummer='2026-001')
    await add_factuur(
        db, nummer='2026-001', klant_id=kid, datum='2026-05-15',
        totaal_bedrag=640, status='betaald')
    with pytest.raises(ValueError, match='betaald'):
        await unlink_werkdag_from_factuur(db, werkdag_id=wid)


@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_rejects_no_factuurnummer(db):
    """Werkdag zonder factuurkoppeling → ValueError."""
    from database import (
        add_klant, add_werkdag, unlink_werkdag_from_factuur,
    )
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    wid = await add_werkdag(
        db, datum='2026-05-15', klant_id=kid, uren=8, tarief=80)
    with pytest.raises(ValueError, match='niet gekoppeld'):
        await unlink_werkdag_from_factuur(db, werkdag_id=wid)


@pytest.mark.asyncio
async def test_unlink_werkdag_from_factuur_rejects_missing_werkdag(db):
    from database import unlink_werkdag_from_factuur
    with pytest.raises(ValueError, match='99999'):
        await unlink_werkdag_from_factuur(db, werkdag_id=99999)


@pytest.mark.asyncio
async def test_werkdagen_filter_by_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    await add_werkdag(db, datum="2025-06-15", klant_id=kid, uren=8, tarief=80)
    await add_werkdag(db, datum="2026-02-23", klant_id=kid, uren=9, tarief=80)

    w2025 = await get_werkdagen(db, jaar=2025)
    w2026 = await get_werkdagen(db, jaar=2026)
    assert len(w2025) == 1
    assert len(w2026) == 1
    assert w2025[0].uren == 8
    assert w2026[0].uren == 9


@pytest.mark.asyncio
async def test_werkdagen_ongefactureerd(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    wid1 = await add_werkdag(db, datum="2026-02-01", klant_id=kid, uren=8, tarief=80)
    wid2 = await add_werkdag(db, datum="2026-02-02", klant_id=kid, uren=9, tarief=80,
                              factuurnummer='2026-001')
    ongefact = await get_werkdagen_ongefactureerd(db)
    assert len(ongefact) == 1
    assert ongefact[0].id == wid1


@pytest.mark.asyncio
async def test_factuurnummer_sequential(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    # First invoice of year
    num1 = await get_next_factuurnummer(db, jaar=2026)
    assert num1 == "2026-001"

    await add_factuur(db, nummer=num1, klant_id=kid, datum="2026-02-23",
                      totaal_bedrag=720)
    num2 = await get_next_factuurnummer(db, jaar=2026)
    assert num2 == "2026-002"

    await add_factuur(db, nummer=num2, klant_id=kid, datum="2026-02-24",
                      totaal_bedrag=640)
    num3 = await get_next_factuurnummer(db, jaar=2026)
    assert num3 == "2026-003"


@pytest.mark.asyncio
async def test_uitgaven_per_categorie(db):
    await add_uitgave(db, datum="2026-01-15", categorie="Bankkosten",
                      omschrijving="Rabo", bedrag=12.50)
    await add_uitgave(db, datum="2026-01-20", categorie="Bankkosten",
                      omschrijving="Rabo", bedrag=12.50)
    await add_uitgave(db, datum="2026-02-01", categorie="Telefoon/KPN",
                      omschrijving="KPN", bedrag=25.00)

    result = await get_uitgaven_per_categorie(db, jaar=2026)
    cats = {r['categorie']: r['totaal'] for r in result}
    assert cats['Bankkosten'] == 25.00
    assert cats['Telefoon/KPN'] == 25.00


@pytest.mark.asyncio
async def test_check_constraint_uren_non_negative(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    # uren=0 is allowed (non-patient business km)
    wd_id = await add_werkdag(db, datum="2026-02-23", klant_id=kid,
                               uren=0, tarief=80)
    assert wd_id > 0
    # uren < 0 must still be rejected
    with pytest.raises(Exception):
        await add_werkdag(db, datum="2026-02-24", klant_id=kid,
                          uren=-1, tarief=80)  # uren must be >= 0


@pytest.mark.asyncio
async def test_check_constraint_bedrag_positive(db):
    with pytest.raises(Exception):
        await add_uitgave(db, datum="2026-01-01", categorie="Test",
                          omschrijving="Test", bedrag=-10)


@pytest.mark.asyncio
async def test_migrations_fresh_db(tmp_path):
    """Fresh database gets all migrations applied."""
    db = tmp_path / 'test.db'
    await init_db(db)
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT MAX(version) FROM schema_version")
        row = await cur.fetchone()
        assert row[0] is not None and row[0] > 0


@pytest.mark.asyncio
async def test_migrations_idempotent(tmp_path):
    """Running init_db twice doesn't fail or re-apply migrations."""
    db = tmp_path / 'test.db'
    await init_db(db)
    await init_db(db)  # second run should be a no-op
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("SELECT COUNT(*) FROM schema_version")
        count = (await cur.fetchone())[0]
        assert count > 0

        # Verify fiscale_params columns exist
        cur = await conn.execute("PRAGMA table_info(fiscale_params)")
        columns = {row[1] for row in await cur.fetchall()}
        assert 'box3_fiscaal_partner' in columns
        assert 'jaarafsluiting_status' in columns



from database import _validate_datum


def test_validate_datum_invalid_month_13():
    """Month 13 is not a valid calendar date."""
    with pytest.raises(ValueError):
        _validate_datum('2026-13-01')


def test_validate_datum_invalid_day_32():
    """Day 32 is not a valid calendar date."""
    with pytest.raises(ValueError):
        _validate_datum('2026-01-32')


def test_validate_datum_valid():
    """A valid date should not raise."""
    result = _validate_datum('2026-06-15')
    assert result == '2026-06-15'




@pytest.mark.asyncio
async def test_factuur_betaallink_persisted(db):
    """Betaallink is stored and retrieved from facturen."""
    kid = await add_klant(db, naam='Test')
    fid = await save_factuur_atomic(
        db, nummer='2026-099', klant_id=kid, datum='2026-01-01',
        totaal_bedrag=100.0, pdf_pad='', type='factuur',
        betaallink='https://betaalverzoek.rabobank.nl/betaalverzoek/?id=abc123',
    )
    facturen = await get_facturen(db)
    f = next(f for f in facturen if f.id == fid)
    assert f.betaallink == 'https://betaalverzoek.rabobank.nl/betaalverzoek/?id=abc123'


@pytest.mark.asyncio
async def test_facturen_herinnering_datum_column(db):
    """herinnering_datum column exists with default empty string."""
    from database import get_db_ctx
    async with get_db_ctx(db) as conn:
        cur = await conn.execute("PRAGMA table_info(facturen)")
        cols = {row['name']: row for row in await cur.fetchall()}
        assert 'herinnering_datum' in cols
        assert cols['herinnering_datum']['dflt_value'] == "''"


@pytest.mark.asyncio
async def test_add_klant_persists_all_fields(db):
    """add_klant with full kwargs persists address/contact fields."""
    kid = await add_klant(
        db, naam='Testpraktijk', adres='Dorpsstraat 1',
        contactpersoon='Dr. Test', postcode='1234AB', plaats='Testdorp')
    klanten = await get_klanten(db)
    kl = next(k for k in klanten if k.id == kid)
    assert kl.naam == 'Testpraktijk'
    assert kl.adres == 'Dorpsstraat 1'
    assert kl.contactpersoon == 'Dr. Test'
    assert kl.postcode == '1234AB'
    assert kl.plaats == 'Testdorp'
