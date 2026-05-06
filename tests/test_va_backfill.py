"""Unit-tests voor services.va_backfill (Sprint J post-redesign).

Dekt:
  1. get_unprocessed_voorlopige_aanslag_documents query
  2. backfill_voorlopige_aanslag_documents — happy path, idempotent,
     parse-fail, locked-year
"""
import shutil
from datetime import date
from pathlib import Path

import pytest

from database import (
    add_aangifte_document,
    get_active_voorlopige_aanslag,
    get_unprocessed_voorlopige_aanslag_documents,
    process_voorlopige_aanslag_upload,
    update_jaarafsluiting_status,
    upsert_fiscale_params,
)
from services.va_backfill import backfill_voorlopige_aanslag_documents
from services.va_parser import ParsedBeschikking


def _minimal_fp_kwargs(jaar: int) -> dict:
    """Mirror van tests/test_va_tracker_userflow.py voor consistent gedrag."""
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
async def test_get_unprocessed_va_documents_finds_unlinked(db, tmp_path):
    """Aangifte_document zonder voorlopige_aanslagen-row → in result."""
    pdf = tmp_path / 'va.pdf'
    pdf.write_text('fake')
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(2026))
    doc_id = await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking',
        bestandspad=str(pdf), bestandsnaam='va.pdf',
    )
    rows = await get_unprocessed_voorlopige_aanslag_documents(db, 2026)
    assert len(rows) == 1
    assert rows[0]['id'] == doc_id


@pytest.mark.asyncio
async def test_get_unprocessed_va_documents_skips_already_linked(db, tmp_path):
    """Document met voorlopige_aanslagen-row → NIET in result."""
    pdf = tmp_path / 'va.pdf'
    pdf.write_text('fake')
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(2026))
    doc_id = await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking',
        bestandspad=str(pdf), bestandsnaam='va.pdf',
    )
    parsed = ParsedBeschikking(
        jaar=2026, soort='ib', aanslagnummer='9999.99.999.H.60.01',
        dagtekening=date(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='9999999999990001', termijnen=11,
    )
    await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc_id, parsed=parsed)
    rows = await get_unprocessed_voorlopige_aanslag_documents(db, 2026)
    assert rows == []


@pytest.mark.asyncio
async def test_get_unprocessed_va_documents_ignores_other_categories(db, tmp_path):
    """Alleen categorie='voorlopige_aanslag' wordt opgepikt."""
    pdf = tmp_path / 'woz.pdf'
    pdf.write_text('fake')
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(2026))
    await add_aangifte_document(
        db_path=db, jaar=2026, categorie='eigen_woning',
        documenttype='woz_beschikking',
        bestandspad=str(pdf), bestandsnaam='woz.pdf',
    )
    rows = await get_unprocessed_voorlopige_aanslag_documents(db, 2026)
    assert rows == []


@pytest.mark.asyncio
async def test_backfill_processes_unlinked_doc(db, tmp_path):
    """Happy path: ongekoppelde fixture-PDF → parse + insert + sync fp."""
    fixture_src = (Path(__file__).parent / 'fixtures'
                   / 'va_beschikking_ib_2026_anon.txt')
    # Backfill verwacht .pdf — kopieer text-fixture als pdf en mock parser
    # via subprocess... eenvoudiger: gebruik echte 2026 PDF in dev,
    # of skip-marker. Voor unit-test: roep parser-text-pad direct via
    # parse_va_beschikking_text en gebruik een pre-parsed result-direct
    # via process_voorlopige_aanslag_upload (daarmee dekken we backfill-
    # detection + DB-state, parse zelf is in test_va_parser.py).
    # Daarom: hier alleen detection + idempotent re-run testen.
    pdf_path = tmp_path / 'va.pdf'
    # Kopieer geanonimiseerde IB-fixture text als pdf-stand-in. parser
    # leest via pdftotext-subprocess die zal falen op text-bestand →
    # parse_failed. Dat is OK: we testen het detection-pad.
    shutil.copy(fixture_src, pdf_path)
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(2026))
    doc_id = await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking',
        bestandspad=str(pdf_path), bestandsnaam='va.pdf',
    )

    summary = await backfill_voorlopige_aanslag_documents(db, 2026)
    # pdftotext op text-file → parse_failed (verwacht)
    assert summary.total == 1
    assert len(summary.failed) == 1
    assert summary.failed[0].document_id == doc_id

    # Document blijft staan; voorlopige_aanslagen blijft leeg.
    rows = await get_unprocessed_voorlopige_aanslag_documents(db, 2026)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_backfill_idempotent_on_already_processed_doc(db, tmp_path):
    """2× backfill — 2e call ziet 0 ongekoppelde docs (al gekoppeld)."""
    pdf = tmp_path / 'va.pdf'
    pdf.write_text('fake')
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(2026))
    doc_id = await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking',
        bestandspad=str(pdf), bestandsnaam='va.pdf',
    )
    parsed = ParsedBeschikking(
        jaar=2026, soort='ib', aanslagnummer='9999.99.999.H.60.01',
        dagtekening=date(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='9999999999990001', termijnen=11,
    )
    # Direct insert via process_*_upload (simulate succesful first parse)
    await process_voorlopige_aanslag_upload(
        db_path=db, document_id=doc_id, parsed=parsed)
    # 2e backfill ziet 0 ongekoppelde docs
    summary = await backfill_voorlopige_aanslag_documents(db, 2026)
    assert summary.total == 0


@pytest.mark.asyncio
async def test_backfill_happy_path_with_monkeypatched_parser(
        db, tmp_path, monkeypatch):
    """Happy path via monkeypatch — parser-mock geeft pre-parsed result,
    backfill insert + sync fp via process_*_upload."""
    from services import va_backfill
    pdf = tmp_path / 'va.pdf'
    pdf.write_text('fake')
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(2026))
    doc_id = await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking',
        bestandspad=str(pdf), bestandsnaam='va_ib.pdf',
    )

    fake_parsed = ParsedBeschikking(
        jaar=2026, soort='ib', aanslagnummer='9999.99.999.H.60.01',
        dagtekening=date(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='9999999999990001', termijnen=11,
    )
    monkeypatch.setattr(
        va_backfill, 'parse_va_beschikking',
        lambda _path: fake_parsed,
    )

    summary = await backfill_voorlopige_aanslag_documents(db, 2026)
    assert len(summary.processed) == 1
    assert summary.processed[0].status == 'inserted'
    assert summary.processed[0].soort == 'ib'
    assert summary.processed[0].bedrag == 30670.0
    # fp gesynchroniseerd
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active is not None
    assert active['bedrag'] == 30670.0


@pytest.mark.asyncio
async def test_backfill_skip_path_for_duplicate_aanslagnummer(
        db, tmp_path, monkeypatch):
    """Twee docs met zelfde aanslagnummer → 1× inserted + 1× skipped."""
    from services import va_backfill
    pdf1 = tmp_path / 'va1.pdf'; pdf1.write_text('fake1')
    pdf2 = tmp_path / 'va2.pdf'; pdf2.write_text('fake2')
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(2026))
    await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking',
        bestandspad=str(pdf1), bestandsnaam='va1.pdf',
    )
    await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking',
        bestandspad=str(pdf2), bestandsnaam='va2.pdf',
    )
    fake_parsed = ParsedBeschikking(
        jaar=2026, soort='ib', aanslagnummer='9999.99.999.H.60.01',
        dagtekening=date(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='9999999999990001', termijnen=11,
    )
    monkeypatch.setattr(
        va_backfill, 'parse_va_beschikking',
        lambda _path: fake_parsed,
    )
    summary = await backfill_voorlopige_aanslag_documents(db, 2026)
    assert len(summary.processed) == 1
    assert len(summary.skipped) == 1
    assert summary.skipped[0].status == 'skipped'


@pytest.mark.asyncio
async def test_backfill_year_locked_returns_locked_status(
        db, tmp_path, monkeypatch):
    """Backfill in definitief jaar → result.status='locked' per doc.

    Codex round-2 finding: ontbrak in v1 omdat fixture-only test parser
    al faalde vóór year-lock check. Monkeypatch-fix maakt parser
    deterministisch zodat year-lock-pad de échte test-target wordt.
    """
    from services import va_backfill
    pdf = tmp_path / 'va.pdf'
    pdf.write_text('fake')
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(2026))
    await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking',
        bestandspad=str(pdf), bestandsnaam='va.pdf',
    )
    # Lock the year AFTER seeding (anders kan upsert_fp niet schrijven).
    await update_jaarafsluiting_status(db, 2026, 'definitief')

    fake_parsed = ParsedBeschikking(
        jaar=2026, soort='ib', aanslagnummer='9999.99.999.H.60.01',
        dagtekening=date(2026, 1, 31), bedrag=30670.0,
        betalingskenmerk='9999999999990001', termijnen=11,
    )
    monkeypatch.setattr(
        va_backfill, 'parse_va_beschikking',
        lambda _path: fake_parsed,
    )

    summary = await backfill_voorlopige_aanslag_documents(db, 2026)
    assert len(summary.locked) == 1
    assert summary.locked[0].status == 'locked'
    # Geen actieve VA-row gemaakt (year-lock blokkeerde insert)
    active = await get_active_voorlopige_aanslag(db, 2026, 'ib')
    assert active is None


@pytest.mark.asyncio
async def test_backfill_handles_missing_file_gracefully(db):
    """PDF-bestand bestaat niet op disk → parse_failed met message."""
    await upsert_fiscale_params(db_path=db, **_minimal_fp_kwargs(2026))
    doc_id = await add_aangifte_document(
        db_path=db, jaar=2026, categorie='voorlopige_aanslag',
        documenttype='va_ib_beschikking',
        bestandspad='/tmp/nonexistent_va.pdf', bestandsnaam='va.pdf',
    )
    summary = await backfill_voorlopige_aanslag_documents(db, 2026)
    assert len(summary.failed) == 1
    assert 'niet gevonden op disk' in summary.failed[0].message
    assert summary.failed[0].document_id == doc_id
