"""Tests voor aangifte documenten database operaties + invulhulp support."""

import pytest
from database import (
    init_db, get_db, get_aangifte_documenten, add_aangifte_document,
    delete_aangifte_document, update_ew_naar_partner,
    get_fiscale_params, upsert_fiscale_params, update_balans_inputs,
    add_uitgave, add_werkdag, add_klant, add_factuur,
    _validate_datum,
)
from components.fiscal_utils import fiscale_params_to_dict, fetch_fiscal_data, bereken_balans
from fiscal.berekeningen import bereken_volledig
from import_.seed_data import FISCALE_PARAMS


@pytest.mark.asyncio
async def test_add_aangifte_document(db):
    """Add a document, verify it's returned by get_aangifte_documenten."""
    doc_id = await add_aangifte_document(
        db, jaar=2024, categorie='eigen_woning',
        documenttype='woz_beschikking',
        bestandsnaam='WOZ_2024.pdf',
        bestandspad='/data/aangifte/2024/eigen_woning/WOZ_2024.pdf',
        upload_datum='2026-03-04',
    )
    assert doc_id > 0

    docs = await get_aangifte_documenten(db, jaar=2024)
    assert len(docs) == 1
    assert docs[0].id == doc_id
    assert docs[0].jaar == 2024
    assert docs[0].categorie == 'eigen_woning'
    assert docs[0].documenttype == 'woz_beschikking'
    assert docs[0].bestandsnaam == 'WOZ_2024.pdf'
    assert docs[0].bestandspad == '/data/aangifte/2024/eigen_woning/WOZ_2024.pdf'
    assert docs[0].upload_datum == '2026-03-04'


@pytest.mark.asyncio
async def test_delete_aangifte_document(db):
    """Delete a document, verify it's removed."""
    doc_id = await add_aangifte_document(
        db, jaar=2024, categorie='pensioen',
        documenttype='upo_eigen',
        bestandsnaam='UPO_ABP_2024.pdf',
        bestandspad='/data/aangifte/2024/pensioen/UPO_ABP_2024.pdf',
        upload_datum='2026-03-04',
    )
    assert len(await get_aangifte_documenten(db, jaar=2024)) == 1

    await delete_aangifte_document(db, doc_id=doc_id)
    assert len(await get_aangifte_documenten(db, jaar=2024)) == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_document(db):
    """Deleting a non-existent document ID does not raise."""
    await delete_aangifte_document(db, doc_id=99999)


@pytest.mark.asyncio
async def test_delete_preserves_other_documents(db):
    """Deleting one document leaves other documents intact."""
    id1 = await add_aangifte_document(
        db, jaar=2024, categorie='eigen_woning',
        documenttype='woz_beschikking',
        bestandsnaam='WOZ_2024.pdf',
        bestandspad='/data/aangifte/2024/eigen_woning/WOZ_2024.pdf',
        upload_datum='2026-03-04',
    )
    id2 = await add_aangifte_document(
        db, jaar=2024, categorie='pensioen',
        documenttype='upo_eigen',
        bestandsnaam='UPO_2024.pdf',
        bestandspad='/data/aangifte/2024/pensioen/UPO_2024.pdf',
        upload_datum='2026-03-04',
    )
    await delete_aangifte_document(db, doc_id=id1)
    docs = await get_aangifte_documenten(db, jaar=2024)
    assert len(docs) == 1
    assert docs[0].id == id2
    assert docs[0].bestandsnaam == 'UPO_2024.pdf'


@pytest.mark.asyncio
async def test_get_aangifte_documenten_filter_by_year(db):
    """Documents from different years are filtered correctly."""
    await add_aangifte_document(
        db, jaar=2023, categorie='eigen_woning',
        documenttype='woz_beschikking',
        bestandsnaam='WOZ_2023.pdf',
        bestandspad='/data/aangifte/2023/eigen_woning/WOZ_2023.pdf',
        upload_datum='2025-03-01',
    )
    await add_aangifte_document(
        db, jaar=2024, categorie='eigen_woning',
        documenttype='woz_beschikking',
        bestandsnaam='WOZ_2024.pdf',
        bestandspad='/data/aangifte/2024/eigen_woning/WOZ_2024.pdf',
        upload_datum='2026-03-04',
    )
    await add_aangifte_document(
        db, jaar=2024, categorie='pensioen',
        documenttype='upo_eigen',
        bestandsnaam='UPO_2024.pdf',
        bestandspad='/data/aangifte/2024/pensioen/UPO_2024.pdf',
        upload_datum='2026-03-04',
    )

    docs_2023 = await get_aangifte_documenten(db, jaar=2023)
    assert len(docs_2023) == 1
    assert docs_2023[0].bestandsnaam == 'WOZ_2023.pdf'

    docs_2024 = await get_aangifte_documenten(db, jaar=2024)
    assert len(docs_2024) == 2
    assert {d.documenttype for d in docs_2024} == {'woz_beschikking', 'upo_eigen'}

    docs_2025 = await get_aangifte_documenten(db, jaar=2025)
    assert len(docs_2025) == 0


@pytest.mark.asyncio
async def test_partner_fields_in_fiscale_params(db):
    """Save and load partner income fields via fiscale_params."""
    conn = await get_db(db)
    await conn.execute(
        "INSERT INTO fiscale_params (jaar) VALUES (?)", (2024,))
    await conn.commit()
    await conn.close()

    # Default values should be 0
    params = await get_fiscale_params(db, jaar=2024)
    assert params.partner_bruto_loon == 0.0
    assert params.partner_loonheffing == 0.0


@pytest.mark.asyncio
async def test_upsert_preserves_partner_fields(db):
    """upsert_fiscale_params preserves partner income when re-saving fiscal params."""
    # Use 2024 seed data as base
    params_2024 = FISCALE_PARAMS[2024]
    await upsert_fiscale_params(db, **params_2024)

    # Set partner income via direct SQL (simulating aangifte page save)
    from database import get_db_ctx
    async with get_db_ctx(db) as conn:
        await conn.execute(
            "UPDATE fiscale_params SET partner_bruto_loon = ?, partner_loonheffing = ? WHERE jaar = ?",
            (42000.00, 11000.00, 2024))
        await conn.commit()

    # Re-save fiscal params (simulating Instellingen save)
    await upsert_fiscale_params(db, **params_2024)

    # Verify partner fields survived the upsert
    params = await get_fiscale_params(db, jaar=2024)
    assert params.partner_bruto_loon == 42000.00
    assert params.partner_loonheffing == 11000.00


# ============================================================
# DD-MM-YYYY datum migration tests
# ============================================================

@pytest.mark.asyncio
async def test_ddmmyyyy_migration_fixes_uitgaven(tmp_path):
    """init_db migrates DD-MM-YYYY dates to YYYY-MM-DD in uitgaven."""
    db_path = tmp_path / "test_migration.sqlite3"

    # Create tables via SCHEMA_SQL but without running migrations
    import aiosqlite
    from database import SCHEMA_SQL
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()
        # Insert bad dates before init_db runs migrations
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag) "
            "VALUES ('15-03-2024', 'kantoor', 'Test', 50.00)")
        await conn.execute(
            "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag) "
            "VALUES ('2024-03-15', 'kantoor', 'Good', 25.00)")
        await conn.commit()

    # Run init_db — migration 12 should fix the bad date
    await init_db(db_path)

    conn = await get_db(db_path)
    cursor = await conn.execute("SELECT datum FROM uitgaven ORDER BY id")
    rows = await cursor.fetchall()
    await conn.close()

    assert rows[0]['datum'] == '2024-03-15'
    assert rows[1]['datum'] == '2024-03-15'


@pytest.mark.asyncio
async def test_ddmmyyyy_migration_fixes_werkdagen(tmp_path):
    """init_db migrates DD-MM-YYYY dates to YYYY-MM-DD in werkdagen."""
    db_path = tmp_path / "test_migration.sqlite3"

    # Create tables via SCHEMA_SQL but without running migrations
    import aiosqlite
    from database import SCHEMA_SQL
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()
        # Insert klant + werkdag with bad date before migrations
        await conn.execute(
            "INSERT INTO klanten (naam, tarief_uur) VALUES ('Test', 80)")
        await conn.execute(
            "INSERT INTO werkdagen (datum, klant_id, uren, tarief) "
            "VALUES ('27-01-2024', 1, 8, 80)")
        await conn.commit()

    # Run init_db — migration 12 should fix the bad date
    await init_db(db_path)

    conn = await get_db(db_path)
    cursor = await conn.execute("SELECT datum FROM werkdagen")
    rows = await cursor.fetchall()
    await conn.close()

    assert rows[0]['datum'] == '2024-01-27'


def test_validate_datum_accepts_valid():
    """_validate_datum accepts YYYY-MM-DD format."""
    assert _validate_datum('2024-03-15') == '2024-03-15'


def test_validate_datum_rejects_ddmmyyyy():
    """_validate_datum rejects DD-MM-YYYY format."""
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _validate_datum('15-03-2024')


def test_validate_datum_rejects_garbage():
    """_validate_datum rejects non-date strings."""
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _validate_datum('not-a-date')


@pytest.mark.asyncio
async def test_add_uitgave_rejects_bad_date(db):
    """add_uitgave raises ValueError for DD-MM-YYYY dates."""
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        await add_uitgave(
            db, datum='15-03-2024', categorie='kantoor',
            omschrijving='Bad date', bedrag=50.00)


@pytest.mark.asyncio
async def test_add_werkdag_rejects_bad_date(db):
    """add_werkdag raises ValueError for DD-MM-YYYY dates."""
    klant_id = await add_klant(db, naam='Test', tarief_uur=80)
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        await add_werkdag(
            db, datum='27-01-2024', klant_id=klant_id, uren=8, tarief=80)


# ============================================================
# fiscal_utils tests
# ============================================================

@pytest.mark.asyncio
async def test_fiscale_params_to_dict(db):
    """fiscale_params_to_dict converts all fields correctly."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    params = await get_fiscale_params(db, jaar=2024)
    d = fiscale_params_to_dict(params)

    assert d['jaar'] == 2024
    assert d['zelfstandigenaftrek'] == FISCALE_PARAMS[2024]['zelfstandigenaftrek']
    assert d['schijf1_pct'] == FISCALE_PARAMS[2024]['schijf1_pct']
    assert 'box3_bank_saldo' in d
    assert 'arbeidskorting_brackets' in d


@pytest.mark.asyncio
async def test_fetch_fiscal_data_returns_none_without_params(db):
    """fetch_fiscal_data returns None if no params exist for year."""
    result = await fetch_fiscal_data(db, 2099)
    assert result is None


@pytest.mark.asyncio
async def test_fetch_fiscal_data_returns_data(db):
    """fetch_fiscal_data returns complete data dict with all expected keys."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    result = await fetch_fiscal_data(db, 2024)

    assert result is not None
    assert 'params' in result
    assert 'params_dict' in result
    assert 'omzet' in result
    assert 'kosten_per_cat' in result
    assert 'kosten_excl_inv' in result
    assert 'totaal_afschrijvingen' in result
    assert 'uren' in result
    assert 'activastaat' in result
    assert 'aov' in result
    assert 'ew_naar_partner' in result
    assert result['omzet'] == 0.0  # no facturen in test DB


# ============================================================
# update_ew_naar_partner tests
# ============================================================

@pytest.mark.asyncio
async def test_update_ew_naar_partner_roundtrip(db):
    """update_ew_naar_partner saves and loads correctly."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])

    # Default is True (1 in DB)
    params = await get_fiscale_params(db, jaar=2024)
    assert params.ew_naar_partner is True

    # Set to False
    result = await update_ew_naar_partner(db, jaar=2024, value=False)
    assert result is True
    params = await get_fiscale_params(db, jaar=2024)
    assert params.ew_naar_partner is False

    # Set back to True
    await update_ew_naar_partner(db, jaar=2024, value=True)
    params = await get_fiscale_params(db, jaar=2024)
    assert params.ew_naar_partner is True


@pytest.mark.asyncio
async def test_update_ew_naar_partner_no_row(db):
    """update_ew_naar_partner returns False if no params row."""
    result = await update_ew_naar_partner(db, jaar=2099, value=False)
    assert result is False


@pytest.mark.asyncio
async def test_upsert_preserves_ew_naar_partner(db):
    """upsert_fiscale_params preserves ew_naar_partner when re-saving."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])

    # Set to False
    await update_ew_naar_partner(db, jaar=2024, value=False)
    params = await get_fiscale_params(db, jaar=2024)
    assert params.ew_naar_partner is False

    # Re-save fiscal params
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])

    # ew_naar_partner should still be False
    params = await get_fiscale_params(db, jaar=2024)
    assert params.ew_naar_partner is False


# ============================================================
# bereken_balans tests
# ============================================================

@pytest.mark.asyncio
async def test_bereken_balans_empty(db):
    """Empty DB with params → all values 0 except pass-through."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    result = await bereken_balans(db, jaar=2024, activastaat=[])
    assert result['mva'] == 0
    assert result['debiteuren'] == 0
    assert result['nog_te_factureren'] == 0
    assert result['totaal_activa'] == 0
    assert result['totaal_schulden'] == 0
    assert result['eigen_vermogen'] == 0


@pytest.mark.asyncio
async def test_bereken_balans_with_activastaat(db):
    """MVA is sum of boekwaarde from activastaat."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    activastaat = [
        {'omschrijving': 'MacBook', 'boekwaarde': 2000.0},
        {'omschrijving': 'Camera', 'boekwaarde': 1500.50},
    ]
    result = await bereken_balans(db, jaar=2024, activastaat=activastaat)
    assert result['mva'] == 3500.50
    assert result['totaal_activa'] == 3500.50


@pytest.mark.asyncio
async def test_bereken_balans_with_debiteuren(db):
    """Unpaid facturen show as debiteuren on balance sheet."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    kid = await add_klant(db, naam="Test", tarief_uur=80)
    await add_factuur(db, nummer="2024-001", klant_id=kid,
                      datum="2024-06-15", totaal_bedrag=2000, status='verstuurd')
    await add_factuur(db, nummer="2024-002", klant_id=kid,
                      datum="2024-07-15", totaal_bedrag=1000, status='betaald')

    result = await bereken_balans(db, jaar=2024, activastaat=[])
    assert result['debiteuren'] == 2000.0  # only unpaid
    assert result['totaal_activa'] == 2000.0


@pytest.mark.asyncio
async def test_bereken_balans_with_uninvoiced_werkdagen(db):
    """Ongefactureerde werkdagen show as nog_te_factureren."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=44)
    await add_werkdag(db, datum="2024-06-10", klant_id=kid,
                      uren=8, tarief=80, km=44, km_tarief=0.23)
    # Expected: 8*80 + 44*0.23 = 640 + 10.12 = 650.12
    result = await bereken_balans(db, jaar=2024, activastaat=[])
    assert abs(result['nog_te_factureren'] - 650.12) < 0.01
    assert abs(result['totaal_activa'] - 650.12) < 0.01


@pytest.mark.asyncio
async def test_bereken_balans_with_manual_inputs(db):
    """Manual balance inputs from fiscale_params are included."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    await update_balans_inputs(db, jaar=2024,
                                balans_bank_saldo=5000,
                                balans_crediteuren=1500,
                                balans_overige_vorderingen=200,
                                balans_overige_schulden=300)

    result = await bereken_balans(db, jaar=2024, activastaat=[])
    assert result['bank_saldo'] == 5000
    assert result['overige_vorderingen'] == 200
    assert result['crediteuren'] == 1500
    assert result['overige_schulden'] == 300
    assert result['totaal_activa'] == 5200  # 5000 + 200
    assert result['totaal_schulden'] == 1800  # 1500 + 300
    assert result['eigen_vermogen'] == 3400  # 5200 - 1800


@pytest.mark.asyncio
async def test_bereken_balans_kapitaalsvergelijking(db):
    """prive_onttrekkingen = begin_vermogen + winst - eigen_vermogen."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    await update_balans_inputs(db, jaar=2024, balans_bank_saldo=10000)

    result = await bereken_balans(db, jaar=2024, activastaat=[],
                                   winst=50000, begin_vermogen=20000)
    # eigen_vermogen = 10000 - 0 = 10000
    # prive_onttrekkingen = 20000 + 50000 - 10000 = 60000
    assert result['eigen_vermogen'] == 10000
    assert result['begin_vermogen'] == 20000
    assert result['winst'] == 50000
    assert result['prive_onttrekkingen'] == 60000


@pytest.mark.asyncio
async def test_bereken_balans_no_params(db):
    """Without fiscale_params, manual inputs default to 0."""
    result = await bereken_balans(db, jaar=2099, activastaat=[
        {'omschrijving': 'Test', 'boekwaarde': 1000.0}
    ])
    assert result['mva'] == 1000.0
    assert result['bank_saldo'] == 0
    assert result['crediteuren'] == 0
    assert result['eigen_vermogen'] == 1000.0


# ============================================================
# fetch_fiscal_data → bereken_volledig pipeline integration test
# ============================================================

@pytest.mark.asyncio
async def test_fetch_to_bereken_pipeline(db):
    """Integration: fetch_fiscal_data → bereken_volledig produces valid result."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])

    # Add realistic test data
    kid = await add_klant(db, naam="Testpraktijk", tarief_uur=77.50, retour_km=52)
    # Add werkdagen: 10 days × 8.5h = 85 uren
    for day in range(1, 11):
        await add_werkdag(db, datum=f"2024-03-{day:02d}", klant_id=kid,
                          uren=8.5, tarief=77.50, km=52, km_tarief=0.23,
                          factuurnummer='2024-001')
    # Add a factuur
    await add_factuur(db, nummer="2024-001", klant_id=kid,
                      datum="2024-03-15", totaal_bedrag=6800, status='betaald')
    # Add some expenses
    await add_uitgave(db, datum="2024-01-15", categorie="Bankkosten",
                      omschrijving="Rabo", bedrag=12.50)
    await add_uitgave(db, datum="2024-02-01", categorie="Representatie",
                      omschrijving="Lunch", bedrag=45.00)

    # Fetch fiscal data
    data = await fetch_fiscal_data(db, 2024)
    assert data is not None
    assert data['omzet'] == 6800
    assert abs(data['representatie'] - 45.00) < 0.01
    assert data['uren'] == 85.0

    # Feed into bereken_volledig — same pattern as aangifte.py
    f = bereken_volledig(
        omzet=data['omzet'], kosten=data['kosten_excl_inv'],
        afschrijvingen=data['totaal_afschrijvingen'],
        representatie=data['representatie'],
        investeringen_totaal=data['inv_totaal_dit_jaar'],
        uren=data['uren'], params=data['params_dict'],
        aov=data['aov'], lijfrente=data.get('lijfrente', 0),
        woz=data['woz'],
        hypotheekrente=data['hypotheekrente'],
        voorlopige_aanslag=data['voorlopige_aanslag'],
        voorlopige_aanslag_zvw=data['voorlopige_aanslag_zvw'],
        ew_naar_partner=data['ew_naar_partner'],
    )

    # Verify the pipeline produces sensible results
    # winst = omzet - kosten_excl_inv (expenses + km_vergoeding)
    assert f.winst < 6800  # reduced by expenses and km_vergoeding
    assert f.winst > 6000  # but still positive
    assert f.fiscale_winst > 0
    assert f.belastbare_winst > 0
    assert f.bruto_ib > 0
    assert f.arbeidskorting > 0
    # With 85 uren (< 1225), urencriterium fails → no ZA/SA
    assert f.uren_criterium_gehaald is False
    assert f.zelfstandigenaftrek == 0
    assert f.startersaftrek == 0
