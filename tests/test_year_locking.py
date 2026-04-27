"""Year-locking guards for definitief jaarafsluiting snapshots (review K6)."""

import aiosqlite
import pytest
from database import (
    YearLockedError, assert_year_writable,
    update_jaarafsluiting_status,
    add_klant, add_werkdag, update_werkdag, delete_werkdag,
    get_werkdagen,
    add_uitgave, update_uitgave, delete_uitgave, get_uitgaven,
    add_factuur, update_factuur, update_factuur_status, delete_factuur,
    save_factuur_atomic, get_facturen,
    link_werkdagen_to_factuur,
    add_banktransacties, update_banktransactie, delete_banktransacties,
    get_banktransacties,
    upsert_fiscale_params,
    update_ib_inputs, update_za_sa_toggles, update_ew_naar_partner,
    update_box3_fiscaal_partner, update_box3_inputs, update_partner_inputs,
    set_afschrijving_override, delete_afschrijving_override,
    get_afschrijving_overrides,
    add_aangifte_document, delete_aangifte_document, get_aangifte_documenten,
    update_factuur_herinnering_datum,
    add_klant_locatie, delete_klant_locatie, get_klant_locaties,
    get_db_ctx,
)
from import_.seed_data import FISCALE_PARAMS


async def _seed_fiscale_params_row(db_path, jaar: int) -> None:
    """Insert a minimal fiscale_params row for a year (defaults = 'concept')."""
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO fiscale_params (jaar) VALUES (?)", (jaar,))
        await conn.commit()


@pytest.mark.asyncio
async def test_assert_year_writable_passes_when_no_fiscale_params(db):
    """No fiscale_params row for a year => writable (nothing to lock against)."""
    await assert_year_writable(db, '2027-06-01')  # must not raise


@pytest.mark.asyncio
async def test_assert_year_writable_passes_for_concept_year(db):
    """Year with status='concept' is writable."""
    await _seed_fiscale_params_row(db, 2026)
    await assert_year_writable(db, '2026-03-15')  # must not raise


@pytest.mark.asyncio
async def test_assert_year_writable_rejects_definitief_year(db):
    """Year with status='definitief' must raise YearLockedError."""
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError, match='2025'):
        await assert_year_writable(db, '2025-06-01')


@pytest.mark.asyncio
async def test_assert_year_writable_accepts_int_year_or_datum_str(db):
    """Helper accepts either an ISO datum string or an int year."""
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await assert_year_writable(db, 2025)
    with pytest.raises(YearLockedError):
        await assert_year_writable(db, '2025-12-31')


def test_year_locked_error_is_value_error():
    """Backward compat: existing catch(ValueError) sites still catch this."""
    exc = YearLockedError('test')
    assert isinstance(exc, ValueError)


@pytest.mark.asyncio
async def test_add_werkdag_rejected_in_definitief_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await add_werkdag(db, datum='2025-06-10', klant_id=kid,
                          uren=8, tarief=80, km=0, km_tarief=0)
    # Verify the INSERT did not slip through before the raise.
    rows = await get_werkdagen(db)
    assert all(w.datum != '2025-06-10' for w in rows)


@pytest.mark.asyncio
async def test_update_werkdag_rejected_in_definitief_year(db):
    """Updating a werkdag whose current datum is in a definitief year is blocked."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2025)
    wid = await add_werkdag(db, datum='2025-06-10', klant_id=kid,
                            uren=8, tarief=80, km=0, km_tarief=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_werkdag(db, werkdag_id=wid, uren=9)
    # Guard-before-write contract: row unchanged.
    rows = await get_werkdagen(db)
    wd = next(w for w in rows if w.id == wid)
    assert wd.uren == 8


@pytest.mark.asyncio
async def test_update_werkdag_rejected_when_new_datum_in_definitief_year(db):
    """Moving a werkdag INTO a definitief year is also blocked."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2025)
    await _seed_fiscale_params_row(db, 2026)
    wid = await add_werkdag(db, datum='2026-01-05', klant_id=kid,
                            uren=8, tarief=80, km=0, km_tarief=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_werkdag(db, werkdag_id=wid, datum='2025-12-31')
    # Row must not have moved into the locked year.
    rows = await get_werkdagen(db)
    wd = next(w for w in rows if w.id == wid)
    assert wd.datum == '2026-01-05'


@pytest.mark.asyncio
async def test_delete_werkdag_rejected_in_definitief_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2025)
    wid = await add_werkdag(db, datum='2025-06-10', klant_id=kid,
                            uren=8, tarief=80, km=0, km_tarief=0)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await delete_werkdag(db, werkdag_id=wid)
    # Row must still exist.
    rows = await get_werkdagen(db)
    assert any(w.id == wid for w in rows)


@pytest.mark.asyncio
async def test_add_uitgave_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await add_uitgave(db, datum='2025-03-10', categorie='Bankkosten',
                          omschrijving='Rabo', bedrag=12.50)
    # No row slipped through.
    rows = await get_uitgaven(db)
    assert all(u.datum != '2025-03-10' for u in rows)


@pytest.mark.asyncio
async def test_update_uitgave_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2025)
    uid = await add_uitgave(db, datum='2025-03-10', categorie='Bankkosten',
                            omschrijving='Rabo', bedrag=12.50)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_uitgave(db, uitgave_id=uid, bedrag=15.00)
    # Amount unchanged.
    rows = await get_uitgaven(db)
    u = next(x for x in rows if x.id == uid)
    assert u.bedrag == 12.50


@pytest.mark.asyncio
async def test_update_uitgave_rejected_when_new_datum_in_definitief_year(db):
    """Moving an uitgave INTO a definitief year is blocked."""
    await _seed_fiscale_params_row(db, 2025)
    await _seed_fiscale_params_row(db, 2026)
    uid = await add_uitgave(db, datum='2026-02-01', categorie='Bankkosten',
                            omschrijving='Rabo', bedrag=12.50)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_uitgave(db, uitgave_id=uid, datum='2025-12-31')
    rows = await get_uitgaven(db)
    u = next(x for x in rows if x.id == uid)
    assert u.datum == '2026-02-01'


@pytest.mark.asyncio
async def test_delete_uitgave_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2025)
    uid = await add_uitgave(db, datum='2025-03-10', categorie='Bankkosten',
                            omschrijving='Rabo', bedrag=12.50)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await delete_uitgave(db, uitgave_id=uid)
    rows = await get_uitgaven(db)
    assert any(x.id == uid for x in rows)


@pytest.mark.asyncio
async def test_add_factuur_rejected_in_definitief_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await add_factuur(db, nummer='2025-999', klant_id=kid,
                          datum='2025-06-10', totaal_bedrag=100.00,
                          status='concept')
    facturen = await get_facturen(db)
    assert all(f.nummer != '2025-999' for f in facturen)


@pytest.mark.asyncio
async def test_update_factuur_status_rejected_in_definitief_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2025)
    fid = await add_factuur(db, nummer='2025-998', klant_id=kid,
                            datum='2025-06-10', totaal_bedrag=100.00,
                            status='verstuurd')
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_factuur_status(db, factuur_id=fid, status='betaald',
                                     betaald_datum='2026-02-01')
    facturen = await get_facturen(db)
    f = next(x for x in facturen if x.id == fid)
    assert f.status == 'verstuurd'


@pytest.mark.asyncio
async def test_update_factuur_rejected_in_definitief_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2025)
    fid = await add_factuur(db, nummer='2025-997', klant_id=kid,
                            datum='2025-06-10', totaal_bedrag=100.00,
                            status='concept')
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_factuur(db, factuur_id=fid, totaal_bedrag=200.00)
    facturen = await get_facturen(db)
    f = next(x for x in facturen if x.id == fid)
    assert f.totaal_bedrag == 100.00


@pytest.mark.asyncio
async def test_delete_factuur_rejected_in_definitief_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2025)
    fid = await add_factuur(db, nummer='2025-996', klant_id=kid,
                            datum='2025-06-10', totaal_bedrag=100.00,
                            status='concept')
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await delete_factuur(db, factuur_id=fid)
    facturen = await get_facturen(db)
    assert any(f.id == fid for f in facturen)


@pytest.mark.asyncio
async def test_save_factuur_atomic_rejected_when_new_datum_in_definitief_year(db):
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await save_factuur_atomic(
            db, nummer='2025-995', klant_id=kid, datum='2025-06-10',
            totaal_bedrag=100.00, regels_json='[]', werkdag_ids=[],
        )
    facturen = await get_facturen(db)
    assert all(f.nummer != '2025-995' for f in facturen)


@pytest.mark.asyncio
async def test_save_factuur_atomic_rejected_when_replacing_factuur_in_definitief_year(db):
    """Rewriting an existing factuur whose old datum is locked is blocked,
    even if the new datum is in a writable year."""
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2025)
    await _seed_fiscale_params_row(db, 2026)
    fid = await add_factuur(db, nummer='2025-994', klant_id=kid,
                            datum='2025-06-10', totaal_bedrag=100.00,
                            status='concept')
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await save_factuur_atomic(
            db, nummer='2025-994', klant_id=kid, datum='2026-01-15',
            totaal_bedrag=200.00, regels_json='[]', werkdag_ids=[],
            replacing_factuur_id=fid,
        )
    facturen = await get_facturen(db)
    f = next(x for x in facturen if x.id == fid)
    assert f.datum == '2025-06-10'
    assert f.totaal_bedrag == 100.00


@pytest.mark.asyncio
async def test_add_banktransacties_rejected_if_any_row_in_definitief_year(db):
    """Bulk import: ANY row in a locked year rejects the WHOLE batch."""
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError, match='2025'):
        await add_banktransacties(db, [
            {'datum': '2026-01-10', 'bedrag': 100, 'tegenpartij': 'X',
             'omschrijving': 'ok', 'categorie': ''},
            {'datum': '2025-12-28', 'bedrag': 200, 'tegenpartij': 'Y',
             'omschrijving': 'locked year', 'categorie': ''},
        ], csv_bestand='mix.csv')
    # Neither row was inserted — whole-batch rejection.
    rows = await get_banktransacties(db)
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_add_banktransacties_passes_when_all_rows_writable(db):
    """Sanity: batch with all concept/unseeded years imports normally."""
    await _seed_fiscale_params_row(db, 2025)  # concept status
    await add_banktransacties(db, [
        {'datum': '2025-05-10', 'bedrag': 100, 'tegenpartij': 'X',
         'omschrijving': 'ok', 'categorie': ''},
        {'datum': '2026-01-10', 'bedrag': 200, 'tegenpartij': 'Y',
         'omschrijving': 'ok', 'categorie': ''},
    ], csv_bestand='ok.csv')
    rows = await get_banktransacties(db)
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_update_banktransactie_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2026)
    await add_banktransacties(db, [
        {'datum': '2026-05-10', 'bedrag': 100, 'tegenpartij': 'X',
         'omschrijving': 'x', 'categorie': ''},
    ], csv_bestand='ok.csv')
    rows_before = await get_banktransacties(db)
    bank_id = rows_before[0].id
    await update_jaarafsluiting_status(db, 2026, 'definitief')
    with pytest.raises(YearLockedError):
        await update_banktransactie(db, transactie_id=bank_id,
                                     categorie='Bankkosten')
    # Categorie unchanged.
    rows_after = await get_banktransacties(db)
    b = next(x for x in rows_after if x.id == bank_id)
    assert b.categorie == ''


@pytest.mark.asyncio
async def test_delete_banktransacties_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2026)
    await add_banktransacties(db, [
        {'datum': '2026-05-10', 'bedrag': 100, 'tegenpartij': 'X',
         'omschrijving': 'x', 'categorie': ''},
    ], csv_bestand='ok.csv')
    rows_before = await get_banktransacties(db)
    bank_id = rows_before[0].id
    await update_jaarafsluiting_status(db, 2026, 'definitief')
    with pytest.raises(YearLockedError):
        await delete_banktransacties(db, [bank_id])
    # Row still exists.
    rows_after = await get_banktransacties(db)
    assert any(x.id == bank_id for x in rows_after)


@pytest.mark.asyncio
async def test_delete_banktransacties_rejected_if_any_row_in_definitief_year(db):
    """Bulk delete: ANY row in a locked year rejects the whole delete."""
    await _seed_fiscale_params_row(db, 2025)
    await _seed_fiscale_params_row(db, 2026)
    await add_banktransacties(db, [
        {'datum': '2025-12-10', 'bedrag': 100, 'tegenpartij': 'X',
         'omschrijving': 'locked', 'categorie': ''},
        {'datum': '2026-01-10', 'bedrag': 200, 'tegenpartij': 'Y',
         'omschrijving': 'free', 'categorie': ''},
    ], csv_bestand='mix.csv')
    rows_before = await get_banktransacties(db)
    assert len(rows_before) == 2
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    ids = [x.id for x in rows_before]
    with pytest.raises(YearLockedError, match='2025'):
        await delete_banktransacties(db, ids)
    # Both still present.
    rows_after = await get_banktransacties(db)
    assert len(rows_after) == 2


@pytest.mark.asyncio
async def test_delete_banktx_rejected_when_linked_factuur_in_frozen_year(db):
    """P0-2: a writable-year bank-tx paying a frozen-year factuur must not
    revert that factuur's status. Snapshot-definitief jaren blijven
    bevroren, ook via late-payment cascades."""
    await _seed_fiscale_params_row(db, 2024)
    await _seed_fiscale_params_row(db, 2025)
    kid = await add_klant(db, naam='LatePayer BV', tarief_uur=0)
    # Factuur issued in 2024, paid in early 2025 (real-world scenario).
    fid = await add_factuur(db, nummer='2024-900', klant_id=kid,
                             datum='2024-12-30', totaal_bedrag=500)
    await update_factuur_status(db, factuur_id=fid, status='verstuurd')
    await update_factuur_status(db, factuur_id=fid, status='betaald',
                                 betaald_datum='2025-01-10')
    await add_banktransacties(db, [
        {'datum': '2025-01-10', 'bedrag': 500, 'tegenpartij': 'LatePayer BV',
         'omschrijving': '2024-900', 'categorie': ''},
    ], csv_bestand='jan2025.csv')
    # Link the bank-tx to the factuur.
    bank_rows = await get_banktransacties(db)
    bank_id = bank_rows[0].id
    await update_banktransactie(
        db, transactie_id=bank_id,
        koppeling_type='factuur', koppeling_id=fid)
    # Freeze 2024.
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    # 2025 bank-tx delete would revert the 2024 betaald factuur → must reject.
    with pytest.raises(YearLockedError, match='2024'):
        await delete_banktransacties(db, [bank_id])
    # Bank-tx still present, factuur still betaald.
    rows_after = await get_banktransacties(db)
    assert any(x.id == bank_id for x in rows_after)
    facturen = await get_facturen(db)
    f = next(x for x in facturen if x.id == fid)
    assert f.status == 'betaald'


@pytest.mark.asyncio
async def test_delete_banktx_rejected_when_linked_uitgave_in_frozen_year(db):
    """Codex-found gap: delete_banktransacties must year-lock linked uitgaven
    datums too, not only bank-tx and factuur. Otherwise the FK
    `ON DELETE SET NULL` on uitgaven.bank_tx_id would silently null the
    bank_tx_id of a frozen-year uitgave when its writable-year bank-tx is
    deleted — a mutation on a frozen-year row without assert_year_writable.
    """
    await _seed_fiscale_params_row(db, 2024)
    await _seed_fiscale_params_row(db, 2025)
    # Bank-tx in writable 2025 (debit, e.g. paying a 2024 invoice late)
    await add_banktransacties(db, [
        {'datum': '2025-01-15', 'bedrag': -100, 'tegenpartij': 'Vendor',
         'omschrijving': 'late factuur 2024', 'categorie': ''},
    ], csv_bestand='jan2025.csv')
    bank_id = (await get_banktransacties(db))[0].id
    # Uitgave dated in 2024 (still writable at this point), linked to the
    # 2025 bank-tx via bank_tx_id.
    await add_uitgave(
        db, datum='2024-12-30', categorie='Kantoor',
        omschrijving='late factuur 2024', bedrag=100, bank_tx_id=bank_id)
    # Now freeze 2024.
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    # Deleting the 2025 bank-tx would null the 2024 uitgave's bank_tx_id
    # → must reject with YearLockedError matching 2024.
    with pytest.raises(YearLockedError, match='2024'):
        await delete_banktransacties(db, [bank_id])
    # Both rows still present (delete was rejected before any mutation).
    assert len(await get_banktransacties(db)) == 1
    assert len(await get_uitgaven(db)) == 1
    # Verify the link is still in DB (bank_tx_id not nulled by SET NULL).
    async with aiosqlite.connect(db) as conn:
        cur = await conn.execute(
            "SELECT bank_tx_id FROM uitgaven LIMIT 1")
        row = await cur.fetchone()
    assert row[0] == bank_id


@pytest.mark.asyncio
async def test_delete_banktx_allowed_when_linked_factuur_also_writable(db):
    """Regression guard: if both the bank-tx and linked factuur jaar are
    writable, the delete succeeds and the factuur reverts to verstuurd."""
    await _seed_fiscale_params_row(db, 2025)
    await _seed_fiscale_params_row(db, 2026)
    kid = await add_klant(db, naam='OnTimePayer', tarief_uur=0)
    fid = await add_factuur(db, nummer='2025-200', klant_id=kid,
                             datum='2025-12-20', totaal_bedrag=250)
    await update_factuur_status(db, factuur_id=fid, status='verstuurd')
    await update_factuur_status(db, factuur_id=fid, status='betaald',
                                 betaald_datum='2026-01-05')
    await add_banktransacties(db, [
        {'datum': '2026-01-05', 'bedrag': 250, 'tegenpartij': 'OnTimePayer',
         'omschrijving': '2025-200', 'categorie': ''},
    ], csv_bestand='jan2026.csv')
    bank_id = (await get_banktransacties(db))[0].id
    await update_banktransactie(
        db, transactie_id=bank_id,
        koppeling_type='factuur', koppeling_id=fid)
    # Neither year frozen — delete must succeed and revert factuur.
    count, reverted = await delete_banktransacties(db, [bank_id])
    assert count == 1
    assert reverted == [fid]
    facturen = await get_facturen(db)
    f = next(x for x in facturen if x.id == fid)
    assert f.status == 'verstuurd'


@pytest.mark.asyncio
async def test_delete_banktx_does_not_falsely_report_reverted_when_factuur_not_betaald(db):
    """Codex-found: delete_banktransacties must only return factuur-ids
    that were actually reverted (status changed from betaald → verstuurd).
    A bank-tx can keep its koppeling to a factuur that the user manually
    flipped back via "Markeer als concept" (betaald→verstuurd→concept).
    Including such ids in the return value would falsely tell the user
    "factuur teruggezet" when in fact nothing changed."""
    await _seed_fiscale_params_row(db, 2025)
    kid = await add_klant(db, naam='ManualFlipper', tarief_uur=0)
    fid = await add_factuur(db, nummer='2025-300', klant_id=kid,
                             datum='2025-06-01', totaal_bedrag=300)
    await update_factuur_status(db, factuur_id=fid, status='verstuurd')
    await update_factuur_status(db, factuur_id=fid, status='betaald',
                                 betaald_datum='2025-06-15')
    await add_banktransacties(db, [
        {'datum': '2025-06-15', 'bedrag': 300, 'tegenpartij': 'ManualFlipper',
         'omschrijving': '2025-300', 'categorie': ''},
    ], csv_bestand='jun2025.csv')
    bank_id = (await get_banktransacties(db))[0].id
    await update_banktransactie(
        db, transactie_id=bank_id,
        koppeling_type='factuur', koppeling_id=fid)
    # User manually flips factuur back: betaald → verstuurd. Koppeling
    # on the bank-tx is intentionally NOT cleared by update_factuur_status.
    await update_factuur_status(db, factuur_id=fid, status='verstuurd')
    # Now delete the bank-tx. The factuur is already verstuurd, so the
    # internal UPDATE WHERE status='betaald' is a no-op. Returned
    # reverted list must be empty.
    count, reverted = await delete_banktransacties(db, [bank_id])
    assert count == 1
    assert reverted == []
    # Factuur status unchanged.
    facturen = await get_facturen(db)
    f = next(x for x in facturen if x.id == fid)
    assert f.status == 'verstuurd'


@pytest.mark.asyncio
async def test_upsert_fiscale_params_rejected_in_definitief_year(db):
    """Full-upsert to a definitief jaar is blocked."""
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        # Use a seeded FISCALE_PARAMS row for 2025 — it has all required keys.
        await upsert_fiscale_params(db, **FISCALE_PARAMS[2025])


@pytest.mark.asyncio
async def test_update_jaarafsluiting_status_unfreeze_always_succeeds(db):
    """Escape hatch: setting status back to 'concept' must always work.

    This is what the 'Heropenen' button on /jaarafsluiting calls.
    """
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    # Must NOT raise even though year is definitief — this IS the unfreeze.
    await update_jaarafsluiting_status(db, 2025, 'concept')
    # After unfreezing, mutations succeed again.
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await add_werkdag(db, datum='2025-06-10', klant_id=kid,
                      uren=8, tarief=80, km=0, km_tarief=0)  # no raise


@pytest.mark.asyncio
async def test_update_jaarafsluiting_status_refreeze_always_succeeds(db):
    """Re-setting status to 'definitief' via the dedicated function must work
    (it's the same escape path — one-column update)."""
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    # Re-freeze via the same path must not self-block.
    await update_jaarafsluiting_status(db, 2025, 'definitief')  # idempotent, no raise


# === A6b: guard the remaining fiscale_params update helpers ===


@pytest.mark.asyncio
async def test_update_ib_inputs_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_ib_inputs(db, jaar=2025, aov_premie=1234)


@pytest.mark.asyncio
async def test_update_za_sa_toggles_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_za_sa_toggles(db, jaar=2025, za_actief=False, sa_actief=False)


@pytest.mark.asyncio
async def test_update_ew_naar_partner_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_ew_naar_partner(db, jaar=2025, value=False)


@pytest.mark.asyncio
async def test_update_box3_fiscaal_partner_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_box3_fiscaal_partner(db, jaar=2025, fiscaal_partner=False)


@pytest.mark.asyncio
async def test_update_box3_inputs_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_box3_inputs(db, jaar=2025, bank_saldo=10000)


@pytest.mark.asyncio
async def test_update_partner_inputs_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_partner_inputs(db, jaar=2025, bruto_loon=50000)


@pytest.mark.asyncio
async def test_update_balans_inputs_rejected_in_definitief_year(db):
    """Regression: balans-sheet helper is the 7th fiscale_params update path."""
    from database import update_balans_inputs
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError):
        await update_balans_inputs(db, jaar=2025, balans_bank_saldo=12345)


@pytest.mark.asyncio
async def test_apply_factuur_matches_rejected_in_definitief_year(db):
    """Final-review gap: apply_factuur_matches was the most-used mutation
    path and bypassed the year-lock via raw UPDATE on status + koppeling.

    Both the factuur-datum side and the bank-datum side must be guarded —
    applying matches in a locked year would silently mutate a frozen jaar.
    """
    from database import (
        apply_factuur_matches, find_factuur_matches, get_banktransacties,
    )

    await _seed_fiscale_params_row(db, 2025)
    kid = await add_klant(db, naam="AM", tarief_uur=100, retour_km=0)
    fid = await add_factuur(
        db, nummer='2025-AM1', klant_id=kid, datum='2025-06-15',
        totaal_bedrag=500.00, status='verstuurd', type='factuur',
    )
    await add_banktransacties(db, [
        {'datum': '2025-06-20', 'bedrag': 500.00, 'tegenpartij': 'AM',
         'omschrijving': '2025-AM1 payment', 'categorie': ''},
    ], csv_bestand='am.csv')
    proposals = await find_factuur_matches(db)
    assert len(proposals) == 1

    # Freeze the year AFTER matches are found but BEFORE apply.
    await update_jaarafsluiting_status(db, 2025, 'definitief')

    with pytest.raises(YearLockedError):
        await apply_factuur_matches(db, proposals)

    # Factuur still 'verstuurd', bank still uncoupled.
    facturen = await get_facturen(db)
    f = next(x for x in facturen if x.id == fid)
    assert f.status == 'verstuurd', "apply must not have mutated status"
    bank_rows = await get_banktransacties(db)
    assert all((b.koppeling_type or '') == '' for b in bank_rows), (
        "apply must not have created bank koppeling in a locked year"
    )


# === Werkdagen koppeling year-lock (Plan 2026-04-26 Lane 1, A1) ===

@pytest.mark.asyncio
async def test_link_werkdagen_to_factuur_rejected_for_locked_werkdag(db):
    """link_werkdagen_to_factuur must guard each werkdag's datum.

    Scenario: a werkdag from a definitief-locked year is selected during
    invoice creation. Linking would silently mutate werkdagen.factuurnummer
    on the locked row — a K6 violation.
    """
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2024)
    wid = await add_werkdag(db, datum='2024-06-10', klant_id=kid,
                            uren=8, tarief=80, km=0, km_tarief=0)
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    with pytest.raises(YearLockedError, match='2024'):
        await link_werkdagen_to_factuur(
            db, werkdag_ids=[wid], factuurnummer='2025-001')
    # Guard-before-write: factuurnummer must remain ''.
    rows = await get_werkdagen(db)
    wd = next(w for w in rows if w.id == wid)
    assert wd.factuurnummer == '', (
        "link_werkdagen_to_factuur leaked through year-lock guard"
    )


@pytest.mark.asyncio
async def test_link_werkdagen_to_factuur_rejects_mixed_year_list(db):
    """A list mixing writable + locked werkdagen must reject the WHOLE batch.

    Pins that the guard iterates all years, not just the first ID's year —
    a buggy "check first only" implementation would let the locked row's
    factuurnummer slip through.
    """
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2024)
    await _seed_fiscale_params_row(db, 2025)
    wid_writable = await add_werkdag(
        db, datum='2025-04-10', klant_id=kid, uren=8, tarief=80,
        km=0, km_tarief=0)
    wid_locked = await add_werkdag(
        db, datum='2024-11-22', klant_id=kid, uren=8, tarief=80,
        km=0, km_tarief=0)
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    with pytest.raises(YearLockedError, match='2024'):
        await link_werkdagen_to_factuur(
            db, werkdag_ids=[wid_writable, wid_locked],
            factuurnummer='2025-MIX')
    # Whole batch rejected: the writable row also stays unlinked.
    rows = await get_werkdagen(db)
    by_id = {w.id: w for w in rows}
    assert by_id[wid_writable].factuurnummer == '', (
        "writable werkdag was linked despite locked sibling — guard ran "
        "after partial mutation"
    )
    assert by_id[wid_locked].factuurnummer == ''


@pytest.mark.asyncio
async def test_save_factuur_atomic_rejected_when_linking_locked_werkdag(db):
    """save_factuur_atomic's inline werkdag UPDATE must also be guarded.

    Even if the new factuur datum is in a writable year, including a
    werkdag from a locked year in werkdag_ids must raise YearLockedError
    and roll back the entire save.
    """
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2024)
    await _seed_fiscale_params_row(db, 2025)
    wid = await add_werkdag(db, datum='2024-09-15', klant_id=kid,
                            uren=8, tarief=80, km=0, km_tarief=0)
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    with pytest.raises(YearLockedError, match='2024'):
        await save_factuur_atomic(
            db, nummer='2025-NEW', klant_id=kid, datum='2025-03-01',
            totaal_bedrag=640.00, regels_json='[]', werkdag_ids=[wid],
        )
    # Rollback: no factuur row, werkdag still ongefactureerd.
    facturen = await get_facturen(db)
    assert all(f.nummer != '2025-NEW' for f in facturen), (
        "factuur was inserted despite locked werkdag in werkdag_ids"
    )
    rows = await get_werkdagen(db)
    wd = next(w for w in rows if w.id == wid)
    assert wd.factuurnummer == '', (
        "locked werkdag's factuurnummer was mutated"
    )


# === A9 / Lane 2: OLD-werkdag unlink guards ===

@pytest.mark.asyncio
async def test_delete_factuur_rejected_when_linked_werkdag_in_locked_year(db):
    """delete_factuur unlinks werkdagen by setting factuurnummer=''.
    A 2025 concept factuur linked to a 2024 werkdag must NOT be deletable
    once 2024 is locked: the unlink is a mutation on a frozen-year row.
    """
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2024)
    await _seed_fiscale_params_row(db, 2025)
    # Werkdag in 2024 (still writable at seed time).
    wid = await add_werkdag(db, datum='2024-09-15', klant_id=kid,
                            uren=8, tarief=80, km=0, km_tarief=0)
    # Concept factuur in 2025.
    fid = await add_factuur(db, nummer='2025-XLINK', klant_id=kid,
                            datum='2025-03-01', totaal_bedrag=640.00,
                            status='concept')
    # Link the 2024 werkdag to the 2025 factuur.
    await link_werkdagen_to_factuur(
        db, werkdag_ids=[wid], factuurnummer='2025-XLINK')
    # Now freeze 2024.
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    # delete_factuur on the 2025 concept would unlink the 2024 werkdag — reject.
    with pytest.raises(YearLockedError, match='2024'):
        await delete_factuur(db, factuur_id=fid)
    # Werkdag's factuurnummer must still be the link (not flipped to '').
    rows = await get_werkdagen(db)
    wd = next(w for w in rows if w.id == wid)
    assert wd.factuurnummer == '2025-XLINK', (
        "delete_factuur leaked through OLD-werkdag year-lock guard"
    )
    # Factuur must still exist (delete was rejected before mutation).
    facturen = await get_facturen(db)
    assert any(f.id == fid for f in facturen), (
        "factuur was deleted despite locked-year werkdag link"
    )


@pytest.mark.asyncio
async def test_save_factuur_atomic_step1_rejected_when_old_werkdag_in_locked_year(db):
    """save_factuur_atomic step 1 (replacing an existing factuur) unlinks the
    OLD nummer's werkdagen via UPDATE werkdagen SET factuurnummer=''.
    If any of those werkdagen sit in a locked year, that unlink is a
    mutation on a frozen-year row and must be rejected.
    """
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2024)
    await _seed_fiscale_params_row(db, 2025)
    # 2024 werkdag (still writable at seed time).
    wid_old = await add_werkdag(db, datum='2024-09-15', klant_id=kid,
                                uren=8, tarief=80, km=0, km_tarief=0)
    # 2025 concept factuur '2025-100', linked to the 2024 werkdag.
    fid = await add_factuur(db, nummer='2025-100', klant_id=kid,
                            datum='2025-03-01', totaal_bedrag=640.00,
                            status='concept')
    await link_werkdagen_to_factuur(
        db, werkdag_ids=[wid_old], factuurnummer='2025-100')
    # Freeze 2024 AFTER setup.
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    # Now: replace 2025-100 with a new 2025 concept that does NOT include
    # the 2024 werkdag (empty werkdag_ids). Step 1 would unlink it.
    with pytest.raises(YearLockedError, match='2024'):
        await save_factuur_atomic(
            db, nummer='2025-100', klant_id=kid, datum='2025-04-01',
            totaal_bedrag=320.00, regels_json='[]', werkdag_ids=[],
            replacing_factuur_id=fid,
        )
    # Original factuur must still exist with original totaal_bedrag.
    facturen = await get_facturen(db)
    f = next(x for x in facturen if x.id == fid)
    assert f.totaal_bedrag == 640.00, (
        "step 1 leaked: old factuur was deleted/replaced despite locked werkdag"
    )
    assert f.datum == '2025-03-01'
    # Werkdag's factuurnummer must remain pointing at the original.
    rows = await get_werkdagen(db)
    wd = next(w for w in rows if w.id == wid_old)
    assert wd.factuurnummer == '2025-100', (
        "save_factuur_atomic step 1 unlinked a locked-year werkdag"
    )


@pytest.mark.asyncio
async def test_save_factuur_atomic_step1_succeeds_when_old_werkdag_in_writable_year(db):
    """Happy-path regression: when both factuur years are writable, step 1
    proceeds normally — old factuur replaced, werkdag unlinked + relinked.
    """
    kid = await add_klant(db, naam="Test", tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2025)
    wid = await add_werkdag(db, datum='2025-02-15', klant_id=kid,
                            uren=8, tarief=80, km=0, km_tarief=0)
    fid_old = await add_factuur(db, nummer='2025-200', klant_id=kid,
                                datum='2025-03-01', totaal_bedrag=640.00,
                                status='concept')
    await link_werkdagen_to_factuur(
        db, werkdag_ids=[wid], factuurnummer='2025-200')
    # Replace with a new 2025 concept that re-includes the werkdag.
    new_id = await save_factuur_atomic(
        db, nummer='2025-200', klant_id=kid, datum='2025-04-01',
        totaal_bedrag=320.00, regels_json='[]', werkdag_ids=[wid],
        replacing_factuur_id=fid_old,
    )
    assert new_id is not None
    # Exactly one factuur exists; old row replaced by new with updated values.
    # (SQLite may reuse the rowid, so we don't assert id inequality.)
    facturen = await get_facturen(db, jaar=2025)
    assert len(facturen) == 1
    f_new = facturen[0]
    assert f_new.nummer == '2025-200'
    assert f_new.totaal_bedrag == 320.00
    assert f_new.datum == '2025-04-01'
    # Werkdag re-linked to the same nummer.
    rows = await get_werkdagen(db)
    wd = next(w for w in rows if w.id == wid)
    assert wd.factuurnummer == '2025-200'


# === L1.2 (A7): afschrijving_overrides year-lock ===

@pytest.mark.asyncio
async def test_set_afschrijving_override_rejected_in_definitief_year(db):
    """Locked-year override write is blocked."""
    # Seed an investering uitgave (unrelated year so we can later seed and
    # lock 2025 specifically without the uitgave itself being affected).
    uid = await add_uitgave(
        db, datum='2024-06-01', categorie='Apparatuur',
        omschrijving='Laptop', bedrag=2000.00,
        is_investering=1, levensduur_jaren=5,
        aanschaf_bedrag=2000.00, zakelijk_pct=100)
    await _seed_fiscale_params_row(db, 2025)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError, match='2025'):
        await set_afschrijving_override(
            db, uitgave_id=uid, jaar=2025, bedrag=400.00)
    # No row was inserted.
    rows = await get_afschrijving_overrides(db, uitgave_id=uid)
    assert 2025 not in rows


@pytest.mark.asyncio
async def test_delete_afschrijving_override_rejected_in_definitief_year(db):
    """Locked-year override delete is blocked. Row must remain."""
    uid = await add_uitgave(
        db, datum='2024-06-01', categorie='Apparatuur',
        omschrijving='Laptop', bedrag=2000.00,
        is_investering=1, levensduur_jaren=5,
        aanschaf_bedrag=2000.00, zakelijk_pct=100)
    await _seed_fiscale_params_row(db, 2025)
    # Seed an override before locking.
    await set_afschrijving_override(
        db, uitgave_id=uid, jaar=2025, bedrag=400.00)
    await update_jaarafsluiting_status(db, 2025, 'definitief')
    with pytest.raises(YearLockedError, match='2025'):
        await delete_afschrijving_override(db, uitgave_id=uid, jaar=2025)
    rows = await get_afschrijving_overrides(db, uitgave_id=uid)
    assert rows.get(2025) == 400.00


@pytest.mark.asyncio
async def test_set_afschrijving_override_succeeds_in_concept_year(db):
    """Regression: writable years still take overrides normally."""
    uid = await add_uitgave(
        db, datum='2024-06-01', categorie='Apparatuur',
        omschrijving='Laptop', bedrag=2000.00,
        is_investering=1, levensduur_jaren=5,
        aanschaf_bedrag=2000.00, zakelijk_pct=100)
    await _seed_fiscale_params_row(db, 2026)
    await set_afschrijving_override(
        db, uitgave_id=uid, jaar=2026, bedrag=350.00)
    rows = await get_afschrijving_overrides(db, uitgave_id=uid)
    assert rows.get(2026) == 350.00


# === L1.3 (A8): aangifte_documenten year-lock ===

@pytest.mark.asyncio
async def test_add_aangifte_document_rejected_in_definitief_year(db):
    await _seed_fiscale_params_row(db, 2024)
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    with pytest.raises(YearLockedError, match='2024'):
        await add_aangifte_document(
            db, jaar=2024, categorie='eigen_woning',
            documenttype='woz_beschikking',
            bestandsnaam='WOZ_2024.pdf',
            bestandspad='/data/aangifte/2024/eigen_woning/WOZ_2024.pdf',
            upload_datum='2026-03-04',
        )
    docs = await get_aangifte_documenten(db, jaar=2024)
    assert len(docs) == 0


@pytest.mark.asyncio
async def test_delete_aangifte_document_rejected_in_definitief_year(db):
    """Concept-year doc inserted, year locked, delete rejected."""
    await _seed_fiscale_params_row(db, 2024)
    doc_id = await add_aangifte_document(
        db, jaar=2024, categorie='pensioen',
        documenttype='upo_eigen',
        bestandsnaam='UPO.pdf',
        bestandspad='/data/aangifte/2024/pensioen/UPO.pdf',
        upload_datum='2026-03-04',
    )
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    with pytest.raises(YearLockedError, match='2024'):
        await delete_aangifte_document(db, doc_id=doc_id)
    docs = await get_aangifte_documenten(db, jaar=2024)
    assert len(docs) == 1


@pytest.mark.asyncio
async def test_delete_aangifte_document_nonexistent_does_not_raise(db):
    """Regression: deleting an unknown doc_id stays a no-op (no jaar to look up)."""
    # No row, no fiscale_params — must not raise.
    await delete_aangifte_document(db, doc_id=99999)


# === L1.4 (A11): update_factuur_herinnering_datum helper ===

@pytest.mark.asyncio
async def test_update_factuur_herinnering_datum_writes_value(db):
    """Concept-year factuur: helper writes the herinnering_datum normally."""
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    fid = await add_factuur(
        db, nummer='2025-H1', klant_id=kid, datum='2025-06-01',
        totaal_bedrag=100.00, status='verstuurd')
    await update_factuur_herinnering_datum(db, factuur_id=fid, datum='2026-04-27')
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT herinnering_datum FROM facturen WHERE id = ?", (fid,))
        row = await cur.fetchone()
    assert row['herinnering_datum'] == '2026-04-27'


@pytest.mark.asyncio
async def test_update_factuur_herinnering_datum_rejected_in_definitief_year(db):
    """Helper must guard via the factuur's datum, not the new herinnering datum."""
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    await _seed_fiscale_params_row(db, 2024)
    fid = await add_factuur(
        db, nummer='2024-H1', klant_id=kid, datum='2024-12-15',
        totaal_bedrag=100.00, status='verstuurd')
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    with pytest.raises(YearLockedError, match='2024'):
        await update_factuur_herinnering_datum(
            db, factuur_id=fid, datum='2026-04-27')
    # Field was not written.
    async with get_db_ctx(db) as conn:
        cur = await conn.execute(
            "SELECT herinnering_datum FROM facturen WHERE id = ?", (fid,))
        row = await cur.fetchone()
    assert (row['herinnering_datum'] or '') == ''


# === L1.5 (A12): delete_klant_locatie year-lock via werkdagen ===

@pytest.mark.asyncio
async def test_delete_klant_locatie_rejected_when_werkdag_in_definitief_year(db):
    """Schema FK is ON DELETE SET NULL on werkdagen.locatie_id. Deleting a
    locatie referenced by a werkdag in a locked year would silently null
    that werkdag's locatie_id — a stealth mutation on a frozen-year row.
    Reject the delete."""
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    lid = await add_klant_locatie(
        db, klant_id=kid, naam='Assen', retour_km=60)
    await _seed_fiscale_params_row(db, 2024)
    await add_werkdag(
        db, datum='2024-09-15', klant_id=kid, uren=8, tarief=80,
        km=0, km_tarief=0, locatie_id=lid)
    await update_jaarafsluiting_status(db, 2024, 'definitief')
    with pytest.raises(YearLockedError, match='2024'):
        await delete_klant_locatie(db, locatie_id=lid)
    # Locatie still exists.
    locaties = await get_klant_locaties(db, klant_id=kid)
    assert any(loc.id == lid for loc in locaties)


@pytest.mark.asyncio
async def test_delete_klant_locatie_succeeds_when_no_locked_werkdagen(db):
    """Regression: ordinary delete still works when nothing is locked."""
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    lid_keep = await add_klant_locatie(
        db, klant_id=kid, naam='Keep', retour_km=10)
    lid_drop = await add_klant_locatie(
        db, klant_id=kid, naam='Drop', retour_km=20)
    # No werkdagen referencing lid_drop in any year.
    await delete_klant_locatie(db, locatie_id=lid_drop)
    locaties = await get_klant_locaties(db, klant_id=kid)
    ids = {loc.id for loc in locaties}
    assert lid_keep in ids
    assert lid_drop not in ids


@pytest.mark.asyncio
async def test_delete_klant_locatie_succeeds_when_werkdagen_only_in_concept_years(db):
    """Locatie used by werkdagen only in writable years → delete is allowed."""
    kid = await add_klant(db, naam='Test', tarief_uur=80, retour_km=0)
    lid = await add_klant_locatie(
        db, klant_id=kid, naam='Concept', retour_km=10)
    await _seed_fiscale_params_row(db, 2026)  # concept
    await add_werkdag(
        db, datum='2026-04-15', klant_id=kid, uren=8, tarief=80,
        km=0, km_tarief=0, locatie_id=lid)
    await delete_klant_locatie(db, locatie_id=lid)
    locaties = await get_klant_locaties(db, klant_id=kid)
    assert all(loc.id != lid for loc in locaties)
