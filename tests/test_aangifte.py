"""Tests voor aangifte documenten database operaties + invulhulp support."""

import pytest
from database import (
    init_db, get_db, get_aangifte_documenten, add_aangifte_document,
    delete_aangifte_document, update_ew_naar_partner,
    get_fiscale_params, upsert_fiscale_params, update_balans_inputs,
    update_ib_inputs, update_box3_inputs, update_partner_inputs,
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


@pytest.mark.asyncio
async def test_upsert_fiscale_params_missing_pvv_aow_raises(db):
    """upsert_fiscale_params must fail loud if a required key is missing — no silent 2024 defaults."""
    bad_kwargs = dict(FISCALE_PARAMS[2024])
    bad_kwargs['jaar'] = 2030
    del bad_kwargs['pvv_aow_pct']
    with pytest.raises(KeyError, match='pvv_aow_pct'):
        await upsert_fiscale_params(db, **bad_kwargs)


@pytest.mark.asyncio
async def test_upsert_fiscale_params_missing_repr_aftrek_raises(db):
    """Missing repr_aftrek_pct must raise KeyError instead of silently writing 80."""
    bad_kwargs = dict(FISCALE_PARAMS[2024])
    bad_kwargs['jaar'] = 2030
    del bad_kwargs['repr_aftrek_pct']
    with pytest.raises(KeyError, match='repr_aftrek_pct'):
        await upsert_fiscale_params(db, **bad_kwargs)


@pytest.mark.asyncio
async def test_upsert_fiscale_params_missing_ew_forfait_raises(db):
    """Missing ew_forfait_pct must raise KeyError instead of silently writing 0.35."""
    bad_kwargs = dict(FISCALE_PARAMS[2024])
    bad_kwargs['jaar'] = 2030
    del bad_kwargs['ew_forfait_pct']
    with pytest.raises(KeyError, match='ew_forfait_pct'):
        await upsert_fiscale_params(db, **bad_kwargs)


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


@pytest.mark.asyncio
async def test_fiscale_params_preserves_explicit_zero(db):
    """Explicit zero values must NOT be overridden by non-zero defaults.

    Regression test for the `or non_zero_default` bug in _row_to_fiscale_params:
    `0 or 17.90` evaluates to 17.90 in Python, silently replacing the intended 0.
    The fix uses `val if val is not None else default`.
    """
    # Start with a complete set of params (2025 seed data), override zeros
    base = dict(FISCALE_PARAMS[2025])
    base['jaar'] = 2099
    # Set all fields that had non-zero defaults to explicit 0
    base['kia_drempel_per_item'] = 0
    base['ew_forfait_pct'] = 0
    base['villataks_grens'] = 0
    base['pvv_aow_pct'] = 0
    base['pvv_anw_pct'] = 0
    base['pvv_wlz_pct'] = 0
    base['repr_aftrek_pct'] = 0
    base['box3_rendement_bank_pct'] = 0
    base['box3_rendement_overig_pct'] = 0
    base['box3_rendement_schuld_pct'] = 0
    base['box3_tarief_pct'] = 0
    base['box3_heffingsvrij_vermogen'] = 0
    base['box3_drempel_schulden'] = 0
    base['urencriterium'] = 0
    base['wet_hillen_pct'] = 0

    await upsert_fiscale_params(db, **base)
    params = await get_fiscale_params(db, jaar=2099)
    assert params is not None

    # All these must be 0, NOT the old hardcoded defaults
    assert params.pvv_aow_pct == 0, f"Expected 0, got {params.pvv_aow_pct} (default 17.90 leak)"
    assert params.pvv_anw_pct == 0, f"Expected 0, got {params.pvv_anw_pct} (default 0.10 leak)"
    assert params.pvv_wlz_pct == 0, f"Expected 0, got {params.pvv_wlz_pct} (default 9.65 leak)"
    assert params.repr_aftrek_pct == 0, f"Expected 0, got {params.repr_aftrek_pct} (default 80 leak)"
    assert params.box3_rendement_bank_pct == 0, f"Expected 0, got {params.box3_rendement_bank_pct}"
    assert params.box3_rendement_overig_pct == 0, f"Expected 0, got {params.box3_rendement_overig_pct}"
    assert params.box3_rendement_schuld_pct == 0, f"Expected 0, got {params.box3_rendement_schuld_pct}"
    assert params.box3_tarief_pct == 0, f"Expected 0, got {params.box3_tarief_pct} (default 36 leak)"
    assert params.box3_heffingsvrij_vermogen == 0, f"Expected 0, got {params.box3_heffingsvrij_vermogen}"
    assert params.box3_drempel_schulden == 0, f"Expected 0, got {params.box3_drempel_schulden}"
    assert params.urencriterium == 0, f"Expected 0, got {params.urencriterium} (default 1225 leak)"
    assert params.wet_hillen_pct == 0, f"Expected 0, got {params.wet_hillen_pct}"
    assert params.kia_drempel_per_item == 0, f"Expected 0, got {params.kia_drempel_per_item} (default 450 leak)"
    assert params.ew_forfait_pct == 0, f"Expected 0, got {params.ew_forfait_pct} (default 0.35 leak)"
    assert params.villataks_grens == 0, f"Expected 0, got {params.villataks_grens} (default 1350000 leak)"


# ============================================================
# Aangifte partial updaters — auto-save roundtrips (Workstream I.4)
# ============================================================

@pytest.mark.asyncio
async def test_update_ib_inputs_roundtrip(db):
    """update_ib_inputs writes all six IB input fields and get_fiscale_params
    reads them back unchanged (aangifte auto-save flow)."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])

    await update_ib_inputs(
        db, jaar=2024,
        aov_premie=4200.00,
        woz_waarde=415000.00,
        hypotheekrente=9800.00,
        voorlopige_aanslag_betaald=12000.00,
        voorlopige_aanslag_zvw=3200.00,
        lijfrente_premie=2500.00,
    )

    params = await get_fiscale_params(db, jaar=2024)
    assert params.aov_premie == 4200.00
    assert params.woz_waarde == 415000.00
    assert params.hypotheekrente == 9800.00
    assert params.voorlopige_aanslag_betaald == 12000.00
    assert params.voorlopige_aanslag_zvw == 3200.00
    assert params.lijfrente_premie == 2500.00


@pytest.mark.asyncio
async def test_update_ib_inputs_overwrites_previous(db):
    """Second update_ib_inputs call fully replaces prior values — no partial merge."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])

    await update_ib_inputs(
        db, jaar=2024, woz_waarde=300000, hypotheekrente=5000,
    )
    params = await get_fiscale_params(db, jaar=2024)
    assert params.woz_waarde == 300000

    # Second save with different values (defaults for omitted fields)
    await update_ib_inputs(db, jaar=2024, woz_waarde=400000)
    params = await get_fiscale_params(db, jaar=2024)
    assert params.woz_waarde == 400000
    # hypotheekrente NOT passed this time -> default 0 -> overwritten
    assert params.hypotheekrente == 0


@pytest.mark.asyncio
async def test_update_box3_inputs_roundtrip(db):
    """update_box3_inputs writes bank_saldo / overige_bezittingen / schulden
    and get_fiscale_params reads them back."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])

    result = await update_box3_inputs(
        db, jaar=2024,
        bank_saldo=52000.00,
        overige_bezittingen=21000.00,
        schulden=3000.00,
    )
    assert result is True  # row existed + was updated

    params = await get_fiscale_params(db, jaar=2024)
    assert params.box3_bank_saldo == 52000.00
    assert params.box3_overige_bezittingen == 21000.00
    assert params.box3_schulden == 3000.00


@pytest.mark.asyncio
async def test_update_box3_inputs_no_row_returns_false(db):
    """update_box3_inputs returns False when no fiscale_params row exists."""
    result = await update_box3_inputs(db, jaar=2099, bank_saldo=1000)
    assert result is False


@pytest.mark.asyncio
async def test_update_partner_inputs_roundtrip(db):
    """update_partner_inputs writes bruto_loon / loonheffing and reads them back."""
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])

    result = await update_partner_inputs(
        db, jaar=2024,
        bruto_loon=42000.00,
        loonheffing=11500.00,
    )
    assert result is True

    params = await get_fiscale_params(db, jaar=2024)
    assert params.partner_bruto_loon == 42000.00
    assert params.partner_loonheffing == 11500.00


@pytest.mark.asyncio
async def test_update_partner_inputs_no_row_returns_false(db):
    """update_partner_inputs returns False when no fiscale_params row exists."""
    result = await update_partner_inputs(db, jaar=2099, bruto_loon=30000)
    assert result is False


@pytest.mark.asyncio
async def test_aangifte_data_uses_snapshot_for_definitief_year(db):
    """Regression (review K5): for a definitief jaar, /aangifte reads snapshot
    values, not live-recomputed ones. This guarantees Jaarcijfers-PDF and the
    /aangifte screen show the same numbers even after engine fixes.

    Mechanism: the `_get_fiscal` closure in pages/aangifte.py routes through
    `load_jaarafsluiting_data` (covers both concept and definitief paths).
    """
    import aiosqlite
    from components.fiscal_utils import (
        fetch_fiscal_data, load_jaarafsluiting_data,
    )
    from database import (
        add_factuur, add_klant, save_jaarafsluiting_snapshot,
        update_jaarafsluiting_status, upsert_fiscale_params,
    )
    from import_.seed_data import FISCALE_PARAMS

    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    kid = await add_klant(db, naam="Snap", tarief_uur=100, retour_km=0)
    await add_factuur(
        db, nummer='2024-A7', klant_id=kid, datum='2024-06-15',
        totaal_uren=10, totaal_km=0, totaal_bedrag=1000.00,
        status='betaald', betaald_datum='2024-06-20',
    )
    live = await fetch_fiscal_data(db, 2024)
    assert live is not None
    FROZEN_OMZET = live['omzet']

    # Freeze: save snapshot + mark definitief. From now on write-guards block
    # further mutations, but we can still simulate an engine-param "update"
    # by going around the guard via raw SQL (pretending a future Plan B-style
    # engine update happened).
    await save_jaarafsluiting_snapshot(db, 2024, live, {}, {'schijf1_pct': 35.75})
    await update_jaarafsluiting_status(db, 2024, 'definitief')

    # Simulate an engine/config change that would shift LIVE recomputed numbers.
    # Bypass the guard intentionally — we want divergence between live and snapshot.
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "UPDATE fiscale_params SET schijf1_pct = schijf1_pct + 1 WHERE jaar = 2024")
        await conn.commit()

    snapshot_data = await load_jaarafsluiting_data(db, 2024)
    assert snapshot_data is not None
    assert snapshot_data['omzet'] == FROZEN_OMZET, (
        "Definitief year must read snapshot omzet, not live-recomputed"
    )


# ============================================================
# A1 — Privé/genegeerd filter on aangifte uitgave-aggregations
# ============================================================
#
# Bug: when a bank-tx is marked privé (banktransacties.genegeerd=1) the
# linked uitgave's category survives. `get_uitgaven_per_categorie` and
# `get_representatie_totaal` previously ignored the bank flag, so the
# privé-debit was still counted as bedrijfskosten in /aangifte.
# Fix: LEFT JOIN banktransacties + filter genegeerd=0 OR bank_tx_id IS NULL.

async def _seed_banktx_row(db_path, *, id_, datum, bedrag,
                           genegeerd=0, tegenpartij='Vendor X'):
    """Insert a banktransacties row directly (cheaper than CSV-import flow)."""
    import aiosqlite
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij, "
            "genegeerd) VALUES (?, ?, ?, ?, ?)",
            (id_, datum, bedrag, tegenpartij, genegeerd))
        await conn.commit()


@pytest.mark.asyncio
async def test_get_uitgaven_per_categorie_filters_genegeerd_bank(db):
    """Bank-tx flagged genegeerd=1 → linked uitgave drops from per-cat sum."""
    from database import get_uitgaven_per_categorie, mark_banktx_genegeerd
    # Two debit bank-rows: one will be flipped privé later.
    await _seed_banktx_row(db, id_=10, datum='2024-04-10', bedrag=-50.0,
                           tegenpartij='Vendor A')
    await _seed_banktx_row(db, id_=11, datum='2024-04-11', bedrag=-30.0,
                           tegenpartij='Vendor B')
    # Two uitgaven, same category 'Telefoon', linked to the bank rows.
    uid_a = await add_uitgave(db, datum='2024-04-10', categorie='Telefoon',
                              omschrijving='A', bedrag=50.0)
    uid_b = await add_uitgave(db, datum='2024-04-11', categorie='Telefoon',
                              omschrijving='B', bedrag=30.0)
    import aiosqlite
    async with aiosqlite.connect(db) as conn:
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (10, uid_a))
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (11, uid_b))
        await conn.commit()

    # Sanity: both contribute to the totaal before genegeerd flip.
    rows = await get_uitgaven_per_categorie(db, jaar=2024)
    cats = {r['categorie']: r['totaal'] for r in rows}
    assert abs(cats.get('Telefoon', 0) - 80.0) < 1e-6

    # Mark Vendor A's bank-tx as privé.
    await mark_banktx_genegeerd(db, 10, genegeerd=1)
    rows = await get_uitgaven_per_categorie(db, jaar=2024)
    cats = {r['categorie']: r['totaal'] for r in rows}
    # Only Vendor B (€30) remains.
    assert abs(cats.get('Telefoon', 0) - 30.0) < 1e-6


@pytest.mark.asyncio
async def test_get_uitgaven_per_categorie_keeps_cash_uitgaven(db):
    """Cash uitgaven (bank_tx_id IS NULL) must still count after the JOIN fix."""
    from database import get_uitgaven_per_categorie
    await add_uitgave(db, datum='2024-05-01', categorie='Bankkosten',
                      omschrijving='Cash post', bedrag=12.50)
    rows = await get_uitgaven_per_categorie(db, jaar=2024)
    cats = {r['categorie']: r['totaal'] for r in rows}
    assert abs(cats.get('Bankkosten', 0) - 12.50) < 1e-6


@pytest.mark.asyncio
async def test_get_representatie_totaal_filters_genegeerd_bank(db):
    """Representatie sum must drop the privé-flagged bank-linked uitgave."""
    from database import get_representatie_totaal, mark_banktx_genegeerd
    await _seed_banktx_row(db, id_=20, datum='2024-06-15', bedrag=-45.0,
                           tegenpartij='Restaurant X')
    await _seed_banktx_row(db, id_=21, datum='2024-06-20', bedrag=-25.0,
                           tegenpartij='Restaurant Y')
    uid_x = await add_uitgave(db, datum='2024-06-15', categorie='Representatie',
                              omschrijving='Lunch X', bedrag=45.0)
    uid_y = await add_uitgave(db, datum='2024-06-20', categorie='Representatie',
                              omschrijving='Lunch Y', bedrag=25.0)
    import aiosqlite
    async with aiosqlite.connect(db) as conn:
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (20, uid_x))
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (21, uid_y))
        await conn.commit()

    totaal = await get_representatie_totaal(db, jaar=2024)
    assert abs(totaal - 70.0) < 1e-6

    # Mark X privé; only Y remains.
    await mark_banktx_genegeerd(db, 20, genegeerd=1)
    totaal = await get_representatie_totaal(db, jaar=2024)
    assert abs(totaal - 25.0) < 1e-6


@pytest.mark.asyncio
async def test_get_representatie_totaal_keeps_cash(db):
    """Cash representatie (no bank link) must still be summed."""
    from database import get_representatie_totaal
    await add_uitgave(db, datum='2024-07-01', categorie='Representatie',
                      omschrijving='Cash lunch', bedrag=22.5)
    totaal = await get_representatie_totaal(db, jaar=2024)
    assert abs(totaal - 22.5) < 1e-6


@pytest.mark.asyncio
async def test_aangifte_excludes_genegeerd_bank_uitgave(db):
    """A privé-flagged debit must drop out of every aangifte uitgave
    aggregation: per-categorie totaal + (when categorie='Representatie')
    representatie totaal. Exercises the JOIN filter that fetch_fiscal_data
    relies on, without depending on the full fiscale_params seed."""
    from database import (
        get_uitgaven_per_categorie, get_representatie_totaal,
        mark_banktx_genegeerd,
    )
    # One bank-linked Telefoon debit (€100), one bank-linked Representatie
    # debit (€60), one cash Telefoon (€20). After flipping the two bank rows
    # privé, only the cash row should remain.
    await _seed_banktx_row(db, id_=30, datum='2024-03-05', bedrag=-100.0,
                           tegenpartij='Phone')
    await _seed_banktx_row(db, id_=31, datum='2024-03-08', bedrag=-60.0,
                           tegenpartij='Lunch')
    uid_30 = await add_uitgave(db, datum='2024-03-05', categorie='Telefoon',
                               omschrijving='Phone', bedrag=100.0)
    uid_31 = await add_uitgave(db, datum='2024-03-08', categorie='Representatie',
                               omschrijving='Lunch', bedrag=60.0)
    await add_uitgave(db, datum='2024-03-06', categorie='Telefoon',
                      omschrijving='Cash phone', bedrag=20.0)
    import aiosqlite
    async with aiosqlite.connect(db) as conn:
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (30, uid_30))
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (31, uid_31))
        await conn.commit()

    rows_before = await get_uitgaven_per_categorie(db, jaar=2024)
    cat_before = {r['categorie']: r['totaal'] for r in rows_before}
    repr_before = await get_representatie_totaal(db, jaar=2024)
    assert abs(cat_before.get('Telefoon', 0) - 120.0) < 1e-6
    assert abs(repr_before - 60.0) < 1e-6

    await mark_banktx_genegeerd(db, 30, genegeerd=1)
    await mark_banktx_genegeerd(db, 31, genegeerd=1)

    rows_after = await get_uitgaven_per_categorie(db, jaar=2024)
    cat_after = {r['categorie']: r['totaal'] for r in rows_after}
    repr_after = await get_representatie_totaal(db, jaar=2024)
    assert abs(cat_after.get('Telefoon', 0) - 20.0) < 1e-6
    assert abs(repr_after - 0.0) < 1e-6


# ============================================================
# Lane 5 (review A13) — UI YearLockedError handling
# ============================================================

@pytest.mark.asyncio
async def test_save_prive_handlers_in_aangifte_catch_yearlocked():
    """Source-pin: each save handler in pages/aangifte.py wraps its
    update_* DB call in try/except YearLockedError. Lane 5 (review A13).

    Pure-runtime tests for these closures would need a NiceGUI page
    context; instead we pin the source so a refactor that drops the
    guard surfaces here.
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'pages' / 'aangifte.py'
    text = src.read_text(encoding='utf-8')

    # Import is wired through.
    assert 'YearLockedError' in text, (
        'pages/aangifte.py must import YearLockedError')

    # Each save handler must contain `except YearLockedError` after its
    # body. Use a coarse contains-check: the handler name plus a nearby
    # except clause within the same function body.
    for handler_marker in (
        'async def save_prive():',
        'async def save_and_calc_box3():',
        'async def _on_za_sa_change():',
        'async def handle_upload(',
        'async def do_delete(',
    ):
        idx = text.find(handler_marker)
        assert idx >= 0, f'handler missing: {handler_marker}'
        # Look for `except YearLockedError` within the next ~3000 chars.
        chunk = text[idx:idx + 3000]
        assert 'except YearLockedError' in chunk, (
            f'{handler_marker} must catch YearLockedError')


@pytest.mark.asyncio
async def test_aangifte_definitief_year_emits_lock_warning():
    """Render-helper smoke: render_warnings appends a 'definitief'-banner
    entry when jaarafsluiting_status='definitief'. Pin the message text."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'pages' / 'aangifte.py'
    text = src.read_text(encoding='utf-8')
    # The banner uses the icon='lock' branch in render_warnings.
    assert "'lock'" in text and 'definitief afgesloten' in text, (
        'aangifte.py must render a lock-banner when the jaar is definitief')


# ============================================================
# Lane 5 (review A7) — kosten_investeringen UI lock check
# ============================================================

@pytest.mark.asyncio
async def test_kosten_investeringen_locks_definitief_year(db):
    """`_is_jaar_definitief` returns True iff jaarafsluiting_status is
    'definitief'. This is the helper that drives `is_locked` in the
    afschrijving-override dialog (Lane 5 / review A7)."""
    from database import upsert_fiscale_params, update_jaarafsluiting_status
    from pages.kosten_investeringen import _is_jaar_definitief
    from import_.seed_data import FISCALE_PARAMS

    # No fiscale_params row yet → not locked.
    assert await _is_jaar_definitief(db, 2099) is False

    # Concept year → not locked.
    await upsert_fiscale_params(db, **FISCALE_PARAMS[2024])
    assert await _is_jaar_definitief(db, 2024) is False

    # Definitief year → locked.
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    assert await _is_jaar_definitief(db, 2024) is True

    # Switching back to concept unlocks again.
    await update_jaarafsluiting_status(db, 2024, 'concept')
    assert await _is_jaar_definitief(db, 2024) is False


@pytest.mark.asyncio
async def test_kosten_investeringen_save_handler_catches_yearlocked():
    """Source-pin: opslaan() in open_afschrijving_dialog wraps the
    set_afschrijving_override / delete_afschrijving_override calls in
    try/except YearLockedError. Lane 5 (review A7)."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] \
        / 'pages' / 'kosten_investeringen.py'
    text = src.read_text(encoding='utf-8')

    assert 'YearLockedError' in text, (
        'pages/kosten_investeringen.py must import YearLockedError')

    idx = text.find('async def opslaan():')
    assert idx >= 0, 'opslaan() handler missing'
    chunk = text[idx:idx + 2500]
    assert 'except YearLockedError' in chunk, (
        'opslaan() must catch YearLockedError')

    # The new lock-check is on jaarafsluiting_status, not on a year cutoff.
    assert '_is_jaar_definitief' in text and 'locked_years' in text, (
        'kosten_investeringen.py must use _is_jaar_definitief / locked_years')


@pytest.mark.asyncio
async def test_facturen_herinnering_handler_catches_yearlocked():
    """Source-pin: on_send_herinnering in pages/facturen.py wraps its
    update_factuur_herinnering_datum call in try/except YearLockedError
    (Lane 1 follow-up; Lane 5 verification)."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'pages' / 'facturen.py'
    text = src.read_text(encoding='utf-8')

    idx = text.find('async def on_send_herinnering(e):')
    assert idx >= 0, 'on_send_herinnering handler missing'
    chunk = text[idx:idx + 4000]
    assert 'except YearLockedError' in chunk, (
        'on_send_herinnering must catch YearLockedError')
    assert 'update_factuur_herinnering_datum' in chunk, (
        'on_send_herinnering must route through the year-locked helper')


# ============================================================
# L8 — codex follow-up findings (B1, B2, U1, U2, U4)
# ============================================================

@pytest.mark.asyncio
async def test_get_uitgaven_per_categorie_excludes_positive_bank_link(db):
    """B1: an uitgave linked to a POSITIVE bank-tx must drop out of the
    per-categorie totaal — same defense the /kosten queries use against
    the lazy-create-on-credit phantom path."""
    from database import get_uitgaven_per_categorie
    # One legit debit-linked uitgave (€40) + one phantom positive-linked
    # uitgave (€100). Only the debit should count.
    await _seed_banktx_row(db, id_=200, datum='2024-08-01', bedrag=-40.0,
                           tegenpartij='Vendor X')
    await _seed_banktx_row(db, id_=201, datum='2024-08-02', bedrag=+100.0,
                           tegenpartij='Income Y')
    uid_a = await add_uitgave(db, datum='2024-08-01', categorie='Telefoon',
                              omschrijving='Real cost', bedrag=40.0)
    uid_b = await add_uitgave(db, datum='2024-08-02', categorie='Telefoon',
                              omschrijving='Phantom', bedrag=100.0)
    import aiosqlite
    async with aiosqlite.connect(db) as conn:
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (200, uid_a))
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (201, uid_b))
        await conn.commit()
    rows = await get_uitgaven_per_categorie(db, jaar=2024)
    cats = {r['categorie']: r['totaal'] for r in rows}
    # Phantom must be excluded; only the €40 debit-linked uitgave remains.
    assert abs(cats.get('Telefoon', 0) - 40.0) < 1e-6


@pytest.mark.asyncio
async def test_get_representatie_totaal_excludes_positive_bank_link(db):
    """B1: representatie totaal mirrors the per-categorie filter."""
    from database import get_representatie_totaal
    await _seed_banktx_row(db, id_=210, datum='2024-09-01', bedrag=-25.0,
                           tegenpartij='Lunch real')
    await _seed_banktx_row(db, id_=211, datum='2024-09-02', bedrag=+80.0,
                           tegenpartij='Income confused as lunch')
    uid_a = await add_uitgave(db, datum='2024-09-01', categorie='Representatie',
                              omschrijving='Real lunch', bedrag=25.0)
    uid_b = await add_uitgave(db, datum='2024-09-02', categorie='Representatie',
                              omschrijving='Phantom', bedrag=80.0)
    import aiosqlite
    async with aiosqlite.connect(db) as conn:
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (210, uid_a))
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (211, uid_b))
        await conn.commit()
    totaal = await get_representatie_totaal(db, jaar=2024)
    assert abs(totaal - 25.0) < 1e-6


@pytest.mark.asyncio
async def test_get_investeringen_excludes_genegeerd_bank(db):
    """B2: investeringen linked to a privé-flagged bank-tx must drop out.
    Without this the activastaat depreciates a privé-marked aankoop."""
    from database import get_investeringen, mark_banktx_genegeerd
    await _seed_banktx_row(db, id_=300, datum='2024-02-01', bedrag=-1500.0,
                           tegenpartij='IT shop')
    inv_id = await add_uitgave(db, datum='2024-02-01', categorie='Apparatuur',
                               omschrijving='Privé laptop', bedrag=1500.0,
                               is_investering=1)
    import aiosqlite
    async with aiosqlite.connect(db) as conn:
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (300, inv_id))
        await conn.commit()
    # Sanity: investering present before privé flip.
    invs = await get_investeringen(db, jaar=2024)
    assert len(invs) == 1
    # Flip privé.
    await mark_banktx_genegeerd(db, 300, genegeerd=1)
    invs = await get_investeringen(db, jaar=2024)
    assert len(invs) == 0, (
        'A privé-flagged investering must drop out of get_investeringen')


@pytest.mark.asyncio
async def test_get_investeringen_voor_afschrijving_excludes_genegeerd(db):
    """B2 (mirror): the afschrijvings-feeder must apply the same filter.

    Without this fix a privé-marked aankoop was still depreciated via the
    activastaat / fiscal_utils.fetch_fiscal_data.
    """
    from database import (
        get_investeringen_voor_afschrijving, mark_banktx_genegeerd,
    )
    await _seed_banktx_row(db, id_=310, datum='2023-03-15', bedrag=-2000.0,
                           tegenpartij='IT supplier')
    inv_id = await add_uitgave(db, datum='2023-03-15', categorie='Apparatuur',
                               omschrijving='Privé scanner', bedrag=2000.0,
                               is_investering=1)
    import aiosqlite
    async with aiosqlite.connect(db) as conn:
        await conn.execute("UPDATE uitgaven SET bank_tx_id = ? WHERE id = ?",
                           (310, inv_id))
        await conn.commit()
    rows = await get_investeringen_voor_afschrijving(db, tot_jaar=2026)
    assert len(rows) == 1
    await mark_banktx_genegeerd(db, 310, genegeerd=1)
    rows = await get_investeringen_voor_afschrijving(db, tot_jaar=2026)
    assert len(rows) == 0


def test_definitief_year_inputs_rendered_disabled():
    """U1 (source-pin): each user-mutating input on /aangifte gets a
    `props('disable')` call when the displayed year is definitief.

    A pure runtime assertion would need a NiceGUI page context; the
    source-pin guarantees that a refactor dropping the disable-call
    surfaces here.
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'pages' / 'aangifte.py'
    text = src.read_text(encoding='utf-8')
    # is_locked computed in each render section.
    assert text.count("'jaarafsluiting_status', 'concept'") >= 3, (
        'render_winst, render_prive, and render_box3 must each derive '
        'is_locked from jaarafsluiting_status')
    # At minimum the inputs exposed in B/U1 (ZA/SA, prive, box3 inputs)
    # must each have a `.props('disable')` siphon when locked.
    for marker in (
        'za_check.props(\'disable\')',
        'sa_check.props(\'disable\')',
        'woz_input.props(\'disable\')',
        'hyp_input.props(\'disable\')',
        'aov_input.props(\'disable\')',
        'va_ib_input.props(\'disable\')',
        'va_zvw_input.props(\'disable\')',
        'partner_loon_input.props(\'disable\')',
        'partner_lh_input.props(\'disable\')',
        'bank_input.props(\'disable\')',
        'overig_input.props(\'disable\')',
        'schuld_input.props(\'disable\')',
        'partner_check.props(\'disable\')',
    ):
        assert marker in text, f'/aangifte must disable input when locked: {marker}'


def test_aangifte_upload_rejects_definitief_year_before_writing_file():
    """U2 (source-pin): handle_upload calls assert_year_writable BEFORE
    write_bytes, so a definitief-jaar upload does not corrupt an existing
    file's contents on disk before the DB rejects it.

    We compare against the actual `await asyncio.to_thread(file_path.write_bytes`
    call (not the literal string "write_bytes" which also appears in the
    rationale comment).
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'pages' / 'aangifte.py'
    text = src.read_text(encoding='utf-8')
    upload_idx = text.find('async def handle_upload(')
    assert upload_idx >= 0, 'handle_upload missing'
    body = text[upload_idx:upload_idx + 4000]
    # The pre-write guard must appear, AND it must come before write_bytes.
    assert_idx = body.find('await assert_year_writable(DB_PATH, jaar)')
    write_idx = body.find('file_path.write_bytes')
    assert assert_idx > 0, (
        'handle_upload must call assert_year_writable up-front')
    assert write_idx > 0, 'handle_upload must still call file_path.write_bytes'
    assert assert_idx < write_idx, (
        'assert_year_writable must run BEFORE write_bytes; otherwise an '
        'upload to a definitief year overwrites the file before the DB '
        'rejects.')


@pytest.mark.asyncio
async def test_upsert_fiscale_params_preserves_unspecified_kia_brackets(db):
    """B4: a partial upsert (omitting the KIA-bracket kwargs) must NOT
    overwrite the existing values with 0. Pre-fix the function passed
    `kwargs.get('kia_plateau_bedrag', 0)` which clobbered configured
    plateau/afbouw values whenever a caller did not re-pass them.
    """
    base = dict(FISCALE_PARAMS[2024])
    base['jaar'] = 2024
    # Seed with explicit KIA brackets.
    base['kia_plateau_bedrag'] = 19535
    base['kia_plateau_eind'] = 129194
    base['kia_afbouw_eind'] = 387580
    base['kia_afbouw_pct'] = 7.56
    base['kia_drempel_per_item'] = 451
    await upsert_fiscale_params(db, **base)

    # Now repeat the upsert WITHOUT the KIA-bracket kwargs. The fix
    # must coalesce missing values back to the existing row, not 0/450.
    minimal = dict(base)
    for k in ('kia_plateau_bedrag', 'kia_plateau_eind',
              'kia_afbouw_eind', 'kia_afbouw_pct',
              'kia_drempel_per_item'):
        minimal.pop(k, None)
    await upsert_fiscale_params(db, **minimal)

    params = await get_fiscale_params(db, 2024)
    assert params is not None
    # Each KIA-bracket field must have survived the partial upsert.
    assert params.kia_plateau_bedrag == 19535, (
        'kia_plateau_bedrag must be preserved when caller omits it')
    assert params.kia_plateau_eind == 129194
    assert params.kia_afbouw_eind == 387580
    assert abs(params.kia_afbouw_pct - 7.56) < 1e-6
    assert params.kia_drempel_per_item == 451


def test_kosten_investeringen_renders_lock_state_before_table():
    """U4 (source-pin): laad_activastaat computes is_jaar_locked BEFORE
    rendering the activa table, surfaces a Dutch banner, and disables the
    per-row tune-button when the displayed jaar is definitief.
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / 'pages' / 'kosten_investeringen.py'
    text = src.read_text(encoding='utf-8')
    # locked-state computed BEFORE the table render begins.
    func_idx = text.find('async def laad_activastaat(')
    assert func_idx >= 0
    body = text[func_idx:func_idx + 4000]
    is_locked_idx = body.find('is_jaar_locked = await _is_jaar_definitief(')
    table_idx = body.find('ui.table(columns=columns')
    assert is_locked_idx > 0, (
        'laad_activastaat must compute is_jaar_locked via _is_jaar_definitief')
    assert table_idx > 0, 'activa table render expected'
    assert is_locked_idx < table_idx, (
        'is_jaar_locked must be computed BEFORE ui.table render')
    # Banner shown when locked.
    assert 'definitief afgesloten' in text, (
        'kosten_investeringen.py must render a definitief-afgesloten banner')
