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

def test_compute_va_termijnen_schedule_cumulative_basic():
    """11 termijnen feb-dec; today=15 mei. €2789 op 28 feb + €2789 op 31 mrt:
    cumulatief €5578 t/m 31 mrt = exact 2 × termijnbedrag → feb+mrt 'betaald';
    apr (vervaldatum 30 apr < today, cum verwacht 4×termijnbedrag, cum betaald
    nog steeds €5578) → 'achter'; mei toekomst."""
    bank = [
        {'datum': '2026-02-28', 'bedrag': 2789.0},
        {'datum': '2026-03-31', 'bedrag': 2789.0},
    ]
    rows = compute_va_termijnen_schedule(
        bedrag=30670.0, termijnen=11, jaar=2026,
        bank_tx=bank, today=date(2026, 5, 15),
    )
    assert len(rows) == 11
    assert [r.termijn for r in rows] == list(range(1, 12))
    assert [r.maand for r in rows] == list(range(2, 13))

    # feb + mrt betaald (cumulatief 5578 ≈ 2 × 2788.18)
    assert rows[0].status == 'betaald'
    assert rows[0].laatste_betaling_op == date(2026, 2, 28)
    assert rows[0].cumulatief_betaald == 2789.0
    assert rows[1].status == 'betaald'
    assert rows[1].cumulatief_betaald == 5578.0

    # apr (termijn 3): cum verwacht ≈ 8364 (3 × 2788), cum betaald 5578.
    # Vervaldatum 30 apr < today 15 mei → 'achter' (overdue + tekort).
    assert rows[2].maand == 4
    assert rows[2].status == 'achter'
    assert rows[2].tekort == pytest.approx(2786.5, abs=1.0)

    # mei (termijn 4) vervaldatum 31 mei > today 15 mei + cum_betaald 5578
    # > 0 + cum_verwacht ~11153 → 'partial' (iets betaald, niet voldoende,
    # vervaldatum nog niet voorbij).
    assert rows[3].maand == 5
    assert rows[3].status == 'partial'

    # dec (termijn 11) zelfde state — partial want cum_betaald 5578 > 0
    # maar < cum_verwacht 30670 én vervaldatum 31 dec > today.
    assert rows[10].maand == 12
    assert rows[10].status == 'partial'


def test_compute_va_termijnen_schedule_pre_eerste_maand_tx_counts():
    """Codex catch — bug-2: jan-betaling voor 11-termijn-feb-start ZVW
    werd in oude per-month-match versie compleet genegeerd. Nu telt het
    cumulatief mee zodra het in jaar 2026 valt.

    €1808 op 22 jan (= ~7 × ZVW-termijnbedrag €255) dekt feb..aug
    cumulatief — alle 7 termijnen status='betaald' op vervaldatum.
    """
    bank = [{'datum': '2026-01-22', 'bedrag': 1808.0}]
    rows = compute_va_termijnen_schedule(
        bedrag=2808.0, termijnen=11, jaar=2026,
        bank_tx=bank, today=date(2026, 5, 15),
    )
    # €1808 dekt termijn 1 t/m 7 cumulatief (255 × 7 = 1785, < 1808 + tol)
    for r in rows[:7]:
        assert r.status == 'betaald', (
            f"Termijn {r.termijn} (cum_betaald={r.cumulatief_betaald}, "
            f"cum_verwacht={r.cumulatief_verwacht}) zou 'betaald' moeten zijn"
        )
    # Termijn 8 (sep, vervaldatum 30 sep > today): cum verwacht 2042,
    # cum betaald nog steeds 1808 → 'toekomst' (vervaldatum nog niet voorbij)
    # met tekort 234.
    assert rows[7].cumulatief_verwacht > rows[7].cumulatief_betaald


def test_compute_va_termijnen_schedule_overpayment_cascades_forward():
    """€5800 IB op 23 feb (= 2× termijnbedrag €2788 met €224 over) dekt
    cumulatief termijn 1 én termijn 2. Termijn 3 (apr) blijft tekort."""
    bank = [{'datum': '2026-02-23', 'bedrag': 5800.0}]
    rows = compute_va_termijnen_schedule(
        bedrag=30670.0, termijnen=11, jaar=2026,
        bank_tx=bank, today=date(2026, 4, 1),  # 1 apr — termijn 3 just verwacht
    )
    # Termijn 1 (feb 28): cum betaald 5800 ≥ verwacht 2788 → betaald
    assert rows[0].status == 'betaald'
    # Termijn 2 (mrt 31): cum betaald 5800 ≥ verwacht 5576 → betaald
    assert rows[1].status == 'betaald'
    # Termijn 3 (apr 30): cum betaald 5800 < verwacht 8364 → 'partial' of
    # 'toekomst' (today=1 apr, vervaldatum=30 apr — beide voor today)
    assert rows[2].status in ('partial', 'toekomst')
    assert rows[2].tekort > 0
    assert rows[2].cumulatief_betaald == 5800.0


def test_compute_va_termijnen_schedule_underpayment_partial_then_achter():
    """€100 IB betaald 28 feb (< termijn 2788). Vóór vervaldatum:
    'partial' (iets betaald, niet voldoende). Na vervaldatum: 'achter'."""
    bank = [{'datum': '2026-02-28', 'bedrag': 100.0}]

    # today=15 feb (voor vervaldatum 28 feb)
    rows_before = compute_va_termijnen_schedule(
        bedrag=30670.0, termijnen=11, jaar=2026,
        bank_tx=bank, today=date(2026, 2, 15),
    )
    # Vervaldatum 28 feb > today → 'partial' (heeft cumulatief betaald > 0)
    # Maar hold on: tx-datum 28 feb > today 15 feb → tx telt nog niet mee?
    # Cumulatief filter is `tx.datum <= vervaldatum`. tx_d (28 feb) ≤
    # vervaldatum_1 (28 feb). cum_betaald = 100. Status: 100 < 2788 - 1, en
    # vervaldatum (28 feb) > today (15 feb) → 'partial'.
    assert rows_before[0].status == 'partial'
    assert rows_before[0].tekort > 2600

    # today=15 mrt (na vervaldatum 28 feb)
    rows_after = compute_va_termijnen_schedule(
        bedrag=30670.0, termijnen=11, jaar=2026,
        bank_tx=bank, today=date(2026, 3, 15),
    )
    assert rows_after[0].status == 'achter'


def test_compute_va_termijnen_schedule_zero_termijnen():
    """Edge case: termijnen=0 (data-corruption defense) → empty list,
    geen division-by-zero. Code-quality reviewer T1.4 catched dat de
    early-return path uncovered was."""
    rows = compute_va_termijnen_schedule(
        bedrag=1000.0, termijnen=0, jaar=2026,
        bank_tx=[], today=date(2026, 5, 15),
    )
    assert rows == []


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
