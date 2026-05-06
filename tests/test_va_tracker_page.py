"""Unit-tests voor /va-tracker page helpers (Sprint J T1.4).

Dekt:
  1. compute_va_termijnen_schedule — pure helper, schedule-derivation
  2. load_va_tracker_summary — async wrapper, fall-through:
     active beschikking > fp-handmatig > defaults
"""
from datetime import date

import pytest

from services.dashboard import (
    compute_va_termijnen_schedule, load_va_tracker_summary,
)
from services.va_parser import ParsedBeschikking
from database import (
    add_aangifte_document, process_voorlopige_aanslag_upload,
    update_ib_inputs, upsert_fiscale_params,
)


def _minimal_fp_kwargs(jaar: int, **overrides) -> dict:
    """Mirrors tests/test_va_tracker_userflow.py voor consistent gedrag."""
    base = dict(
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
    base.update(overrides)
    return base


# --------------------------------------------------------------------- #
# 1. compute_va_termijnen_schedule
# --------------------------------------------------------------------- #

def test_compute_va_termijnen_schedule_status_per_termijn():
    """11 termijnen feb-dec; today=15 mei → feb+mrt betaald, apr verwacht,
    mei..dec toekomst (mei vervaldatum 31 mei > today)."""
    bank = [
        {'datum': '2026-02-28', 'bedrag': 2789.0},
        {'datum': '2026-03-31', 'bedrag': 2789.0},
    ]
    rows = compute_va_termijnen_schedule(
        bedrag=30670.0, termijnen=11, jaar=2026,
        bank_tx=bank, today=date(2026, 5, 15),
    )
    assert len(rows) == 11  # feb-dec
    assert [r.maand for r in rows] == list(range(2, 13))

    # feb + mrt betaald
    assert rows[0].status == 'betaald'
    assert rows[0].betaald_op == date(2026, 2, 28)
    assert rows[0].betaald_bedrag == 2789.0
    assert rows[1].status == 'betaald'

    # apr vervaldatum = 30 apr < 15 mei → verwacht (overdue)
    assert rows[2].maand == 4
    assert rows[2].status == 'verwacht'
    assert rows[2].betaald_op is None

    # mei vervaldatum = 31 mei > 15 mei → toekomst
    assert rows[3].maand == 5
    assert rows[3].status == 'toekomst'

    # dec toekomst
    assert rows[10].maand == 12
    assert rows[10].status == 'toekomst'

    # Alle bedragen = 30670 / 11
    assert all(abs(r.bedrag - 30670.0 / 11) < 1e-9 for r in rows)


# --------------------------------------------------------------------- #
# 2a. load_va_tracker_summary — active beschikking wins over fp
# --------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_load_va_tracker_summary_uses_active_beschikking_when_present(db):
    """Beschikking-bedrag (30670) overruled fp.voorlopige_aanslag_betaald
    (99999), zodat de wrapper niet stilletjes verkeerde bedragen aan
    compute_va_tracker doorgeeft.
    """
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(2026))
    # voorlopige_aanslag_betaald moet via update_ib_inputs (upsert_fiscale_params
    # negeert dat veld voor preserve-existing semantics).
    await update_ib_inputs(
        db_path=db, jaar=2026,
        voorlopige_aanslag_betaald=99999.0,  # handmatig — moet overruled worden
    )
    document_id = await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking',
        bestandsnaam='VA_IB_2026.pdf',
        bestandspad='/tmp/fake/VA_IB_2026.pdf',
        upload_datum='2026-01-31',
    )
    parsed = ParsedBeschikking(
        jaar=2026, soort='ib',
        aanslagnummer='9999.99.999.H.60.01',
        dagtekening=date(2026, 1, 31),
        bedrag=30670.0,
        betalingskenmerk='9999999999990001',
        termijnen=11,
    )
    await process_voorlopige_aanslag_upload(
        db_path=db, document_id=document_id, parsed=parsed,
    )

    summary = await load_va_tracker_summary(db, 2026, date(2026, 5, 15))
    assert summary.ib.verplicht == 30670.0  # uit beschikking, NIET 99999
    assert summary.ib.totaal_termijnen == 11
    # ZVW geen beschikking → fp-fallback (= 0 default)
    assert summary.zvw.verplicht == 0.0


# --------------------------------------------------------------------- #
# 2b. load_va_tracker_summary — fp fallback bij ontbreken beschikking
# --------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_load_va_tracker_summary_falls_back_to_fp_when_no_beschikking(db):
    """Geen beschikking → fp.voorlopige_aanslag_betaald + _ib_termijnen
    worden gebruikt als datasource."""
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(
        2026, voorlopige_aanslag_ib_termijnen=11,
    ))
    await update_ib_inputs(
        db_path=db, jaar=2026,
        voorlopige_aanslag_betaald=25000.0,
        voorlopige_aanslag_ib_termijnen=11,
    )

    summary = await load_va_tracker_summary(db, 2026, date(2026, 5, 15))
    assert summary.ib.verplicht == 25000.0
    assert summary.ib.totaal_termijnen == 11
    # ZVW kant blijft default 0
    assert summary.zvw.verplicht == 0.0
