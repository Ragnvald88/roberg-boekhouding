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
    add_banktransacties, update_banktransactie, delete_banktransacties,
    get_banktransacties,
    upsert_fiscale_params,
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
