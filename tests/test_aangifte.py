"""Tests voor aangifte documenten database operaties + invulhulp support."""

import pytest
from database import (
    init_db, get_db, get_aangifte_documenten, add_aangifte_document,
    delete_aangifte_document, update_partner_inkomen, update_ew_naar_partner,
    get_fiscale_params, upsert_fiscale_params,
    add_uitgave, add_werkdag, add_klant,
    _validate_datum,
)
from components.fiscal_utils import fiscale_params_to_dict, fetch_fiscal_data
from import_.seed_data import FISCALE_PARAMS


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    return db_path


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

    # Update partner income
    result = await update_partner_inkomen(
        db, jaar=2024,
        partner_bruto_loon=45000.00,
        partner_loonheffing=12500.00,
    )
    assert result is True

    # Verify saved values
    params = await get_fiscale_params(db, jaar=2024)
    assert params.partner_bruto_loon == 45000.00
    assert params.partner_loonheffing == 12500.00


@pytest.mark.asyncio
async def test_update_partner_inkomen_no_row(db):
    """update_partner_inkomen returns False when no fiscale_params row exists."""
    result = await update_partner_inkomen(
        db, jaar=2099,
        partner_bruto_loon=50000.00,
        partner_loonheffing=15000.00,
    )
    assert result is False
    # Verify no row was created
    params = await get_fiscale_params(db, jaar=2099)
    assert params is None


@pytest.mark.asyncio
async def test_upsert_preserves_partner_fields(db):
    """upsert_fiscale_params preserves partner income when re-saving fiscal params."""
    # Use 2024 seed data as base
    params_2024 = FISCALE_PARAMS[2024]
    await upsert_fiscale_params(db, **params_2024)

    # Set partner income
    await update_partner_inkomen(
        db, jaar=2024,
        partner_bruto_loon=42000.00,
        partner_loonheffing=11000.00,
    )

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
    await init_db(db_path)

    # Insert a row with DD-MM-YYYY format directly (bypassing validation)
    conn = await get_db(db_path)
    await conn.execute(
        "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag) "
        "VALUES ('15-03-2024', 'kantoor', 'Test', 50.00)")
    await conn.execute(
        "INSERT INTO uitgaven (datum, categorie, omschrijving, bedrag) "
        "VALUES ('2024-03-15', 'kantoor', 'Good', 25.00)")
    await conn.commit()
    await conn.close()

    # Run init_db again — migration should fix the bad date
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
    await init_db(db_path)

    # Insert klant first (FK requirement)
    conn = await get_db(db_path)
    await conn.execute(
        "INSERT INTO klanten (naam, tarief_uur) VALUES ('Test', 80)")
    # Insert werkdag with bad date directly
    await conn.execute(
        "INSERT INTO werkdagen (datum, klant_id, uren, tarief) "
        "VALUES ('27-01-2024', 1, 8, 80)")
    await conn.commit()
    await conn.close()

    # Run init_db again
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
