"""End-to-end VA-tracker userflow test (Sprint J T1.3, Codex round-2 should-fix).

Simuleert de DB-laag van de full lifecycle:
  upload-saved → parse → process_voorlopige_aanslag_upload → fp synced
  → get_active_voorlopige_aanslag returns row
  → delete_aangifte_document_with_va_cleanup → fp gereset → active=None

NiceGUI confirm-dialog (mismatch-flow) wordt apart smoke-getest in
manuele rooktest; pure async DB-laag dekken we hier deterministisch.
"""
from datetime import date

import pytest

from services.va_parser import ParsedBeschikking
from database import (
    add_aangifte_document,
    delete_aangifte_document_with_va_cleanup,
    get_active_voorlopige_aanslag,
    get_fiscale_params,
    process_voorlopige_aanslag_upload,
    upsert_fiscale_params,
)


def _minimal_fp_kwargs(jaar: int) -> dict:
    """Minimal kwargs that satisfy upsert_fiscale_params required keys.

    Mirrors tests/test_db_queries.py::_minimal_fiscale_params_kwargs zodat
    de VA-flow tegen een realistische (non-empty) fp-row test.
    """
    return dict(
        jaar=jaar,
        zelfstandigenaftrek=0, mkb_vrijstelling_pct=0,
        kia_ondergrens=0, kia_bovengrens=0, kia_pct=0,
        km_tarief=0.23, schijf1_grens=0, schijf1_pct=0,
        schijf2_grens=0, schijf2_pct=0, schijf3_pct=0,
        ahk_max=0, ahk_afbouw_pct=0, ahk_drempel=0, ak_max=0,
        zvw_pct=0, zvw_max_grondslag=0, repr_aftrek_pct=80,
        ew_forfait_pct=0.35, villataks_grens=1_350_000,
        wet_hillen_pct=0, urencriterium=1225,
        pvv_premiegrondslag=0, arbeidskorting_brackets='',
        pvv_aow_pct=17.90, pvv_anw_pct=0.10, pvv_wlz_pct=9.65,
        box3_heffingsvrij_vermogen=57000,
        box3_rendement_bank_pct=1.03, box3_rendement_overig_pct=6.17,
        box3_rendement_schuld_pct=2.46, box3_tarief_pct=36,
        box3_drempel_schulden=3700,
    )


@pytest.mark.asyncio
async def test_va_userflow_upload_parse_sync_dashboard_delete_clears_fp(db):
    """Full lifecycle: upload → process → fp synced → delete → fp cleared.

    Dit dekt de userflow die /documenten parse-on-upload triggert + de
    delete-cleanup die /aangifte-laag (en eventueel /va-tracker) gebruikt.
    """
    # --- 1. Seed fp + add aangifte_document for VA-IB
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(2026))
    document_id = await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking',
        bestandsnaam='VA_IB_2026.pdf',
        bestandspad='/tmp/fake/VA_IB_2026.pdf',
        upload_datum='2026-01-31',
    )
    assert isinstance(document_id, int) and document_id > 0

    # --- 2. process_voorlopige_aanslag_upload met geparseerde data
    parsed = ParsedBeschikking(
        jaar=2026, soort='ib',
        aanslagnummer='9999.99.999.H.60.01',
        dagtekening=date(2026, 1, 31),
        bedrag=30670.0,
        betalingskenmerk='9999999999990001',
        termijnen=11,
    )
    result = await process_voorlopige_aanslag_upload(
        db_path=db, document_id=document_id, parsed=parsed,
    )
    assert result['action'] == 'inserted'
    assert isinstance(result['beschikking_id'], int)

    # --- 3. Verifieer active row + fp-sync (dashboard read-pad)
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active is not None
    assert active['bedrag'] == 30670.0
    assert active['aanslagnummer'] == '9999.99.999.H.60.01'
    assert active['termijnen'] == 11
    assert active['is_active'] == 1

    fp = await get_fiscale_params(db, 2026)
    assert fp is not None
    assert fp.voorlopige_aanslag_betaald == 30670.0
    assert fp.voorlopige_aanslag_ib_termijnen == 11
    # ZVW-zijde onaangetast
    assert fp.voorlopige_aanslag_zvw == 0

    # --- 4. Delete document + cleanup
    await delete_aangifte_document_with_va_cleanup(db, doc_id=document_id)

    # --- 5. Active row weg + fp gereset (cleanup-default = 11)
    active_after = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active_after is None

    fp_after = await get_fiscale_params(db, 2026)
    assert fp_after is not None
    assert fp_after.voorlopige_aanslag_betaald == 0
    # delete_aangifte_document_with_va_cleanup reset termijnen naar default
    # (11), niet naar 0 — checked in database.py:3164-3168.
    assert fp_after.voorlopige_aanslag_ib_termijnen == 11
