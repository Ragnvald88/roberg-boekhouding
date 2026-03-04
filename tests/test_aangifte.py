"""Tests voor aangifte documenten database operaties."""

import pytest
from database import (
    init_db, get_db, get_aangifte_documenten, add_aangifte_document,
    delete_aangifte_document, update_partner_inkomen,
    get_fiscale_params, upsert_fiscale_params,
)
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
