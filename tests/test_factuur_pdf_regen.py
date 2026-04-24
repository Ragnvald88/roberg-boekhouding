"""F-5/6/7 — PDF auto-regeneration for factuur row-menu actions.

Covers ``_compute_regen_sources`` (the pure source-picker) end-to-end
against a test DB. The WeasyPrint-based ``_regenerate_factuur_pdf`` is
smoke-tested separately to keep the fast suite fast.
"""
import json
import aiosqlite
import pytest

from pages import facturen as facturen_module
from database import (
    DB_PATH, add_factuur, add_klant, add_werkdag,
    link_werkdagen_to_factuur, upsert_bedrijfsgegevens,
    update_factuur,
)


async def _seed_bg(db_path):
    await upsert_bedrijfsgegevens(
        db_path,
        bedrijfsnaam='Test Praktijk',
        naam='Doc',
        adres='Teststraat 1',
        postcode_plaats='1234AB Testdorp',
        kvk='12345678',
        iban='NL00TEST0000000000',
        thuisplaats='Testdorp',
        telefoon='0612345678',
        email='doc@test.nl',
    )


@pytest.fixture(autouse=True)
def _patch_db_path(db, monkeypatch):
    """Point the facturen module at the per-test DB path."""
    monkeypatch.setattr(facturen_module, 'DB_PATH', db)
    # database.DB_PATH is the global the module reads for DB access.
    import database as db_mod
    monkeypatch.setattr(db_mod, 'DB_PATH', db)
    return db


@pytest.mark.asyncio
async def test_compute_regen_sources_reads_regels_json(db):
    """regels_json is the preferred source — line_items are carried verbatim."""
    await _seed_bg(db)
    kid = await add_klant(db, naam='RegelsJsonKlant', tarief_uur=90,
                           retour_km=20)
    fid = await add_factuur(db, nummer='2026-RJ1', klant_id=kid,
                             datum='2026-04-01', totaal_bedrag=900,
                             status='concept')
    regels_data = {
        'line_items': [
            {'datum': '2026-04-01',
             'omschrijving': 'Waarneming dagpraktijk',
             'aantal': 10, 'tarief': 90, 'km': 0, 'km_tarief': 0,
             'is_reiskosten': False, 'werkdag_id': None},
        ],
        'klant_fields': {
            'naam': 'RegelsJsonKlant', 'adres': 'Staat 1',
            'postcode': '1111AA', 'plaats': 'Stad',
            'contactpersoon': '',
        },
    }
    await update_factuur(
        db, factuur_id=fid, regels_json=json.dumps(regels_data))

    row = {'id': fid, 'nummer': '2026-RJ1', 'klant_id': kid,
           'datum': '2026-04-01', 'type': 'factuur'}
    src = await facturen_module._compute_regen_sources(row)
    assert src is not None
    assert len(src['line_items']) == 1
    assert src['line_items'][0]['omschrijving'] == 'Waarneming dagpraktijk'
    assert src['klant_fields']['naam'] == 'RegelsJsonKlant'
    assert src['factuur_type'] == 'factuur'


@pytest.mark.asyncio
async def test_compute_regen_sources_falls_back_to_werkdagen(db):
    """Historic factures have empty regels_json — reconstruct from linked
    werkdagen instead. This is the key fix for 2026-029."""
    await _seed_bg(db)
    kid = await add_klant(db, naam='WerkdagKlant', tarief_uur=82.5,
                           retour_km=54)
    wid = await add_werkdag(db, datum='2026-04-23', klant_id=kid,
                             uren=9, tarief=82.5, km=54, km_tarief=0.23)
    fid = await add_factuur(db, nummer='2026-WD1', klant_id=kid,
                             datum='2026-04-24', totaal_bedrag=754.92,
                             status='concept')
    await link_werkdagen_to_factuur(db, werkdag_ids=[wid],
                                     factuurnummer='2026-WD1')
    # regels_json deliberately empty — mirrors historic facturen.

    row = {'id': fid, 'nummer': '2026-WD1', 'klant_id': kid,
           'datum': '2026-04-24', 'type': 'factuur'}
    src = await facturen_module._compute_regen_sources(row)
    assert src is not None, (
        "Werkdagen fallback should have produced line_items for a "
        "factuur with empty regels_json but linked werkdagen.")
    assert len(src['line_items']) == 1
    li = src['line_items'][0]
    assert li['aantal'] == 9
    assert li['tarief'] == 82.5
    assert li['km'] == 54
    assert li['km_tarief'] == 0.23
    # klant_fields came from the klanten record since regels_json was empty.
    assert src['klant_fields']['naam'] == 'WerkdagKlant'


@pytest.mark.asyncio
async def test_compute_regen_sources_returns_none_for_anw(db):
    """ANW invoices are imports — the original PDF is the authority and
    we must never try to regenerate them from app state."""
    await _seed_bg(db)
    kid = await add_klant(db, naam='ANW Post', tarief_uur=0)
    fid = await add_factuur(db, nummer='22470-26-01', klant_id=kid,
                             datum='2026-01-05', totaal_bedrag=500,
                             status='betaald', type='anw', bron='import')

    row = {'id': fid, 'nummer': '22470-26-01', 'klant_id': kid,
           'datum': '2026-01-05', 'type': 'anw'}
    src = await facturen_module._compute_regen_sources(row)
    assert src is None, "ANW imports must not be regenerated"


@pytest.mark.asyncio
async def test_compute_regen_sources_returns_none_when_no_data(db):
    """A vergoeding-type factuur with no regels_json AND no werkdagen
    cannot be reconstructed. The helper returns None; the UI surfaces a
    clear 'open via Bewerken' instruction."""
    await _seed_bg(db)
    kid = await add_klant(db, naam='AdHoc', tarief_uur=0)
    fid = await add_factuur(db, nummer='2026-VG1', klant_id=kid,
                             datum='2026-03-01', totaal_bedrag=100,
                             status='verstuurd', type='vergoeding')

    row = {'id': fid, 'nummer': '2026-VG1', 'klant_id': kid,
           'datum': '2026-03-01', 'type': 'vergoeding'}
    src = await facturen_module._compute_regen_sources(row)
    assert src is None


@pytest.mark.asyncio
async def test_compute_regen_sources_bg_dict_populated(db):
    """bedrijfsgegevens.thuisplaats is needed for the reiskosten line
    label ('Reiskosten (retour X – Y)'). Regression guard: the helper
    must load and pass bg_dict through."""
    await _seed_bg(db)
    kid = await add_klant(db, naam='BGTest', tarief_uur=80)
    wid = await add_werkdag(db, datum='2026-04-01', klant_id=kid,
                             uren=8, tarief=80, km=30, km_tarief=0.23,
                             locatie='Groningen')
    fid = await add_factuur(db, nummer='2026-BG1', klant_id=kid,
                             datum='2026-04-01', totaal_bedrag=646.90,
                             status='concept')
    await link_werkdagen_to_factuur(db, werkdag_ids=[wid],
                                     factuurnummer='2026-BG1')

    row = {'id': fid, 'nummer': '2026-BG1', 'klant_id': kid,
           'datum': '2026-04-01', 'type': 'factuur'}
    src = await facturen_module._compute_regen_sources(row)
    assert src is not None
    assert src['bg_dict']['thuisplaats'] == 'Testdorp'
    # Line item km_omschrijving built using both endpoints.
    li = src['line_items'][0]
    assert 'Testdorp' in li.get('km_omschrijving', '')
    assert 'Groningen' in li.get('km_omschrijving', '')


@pytest.mark.asyncio
async def test_regenerate_factuur_pdf_writes_file_and_updates_db(db, tmp_path, monkeypatch):
    """Smoke test of the full regenerate path: WeasyPrint renders a PDF,
    the file ends up on disk, pdf_pad is updated in DB."""
    # Redirect PDF_DIR to a tmp_path so the test doesn't touch real data.
    pdf_dir = tmp_path / 'facturen'
    pdf_dir.mkdir()
    monkeypatch.setattr(facturen_module, 'PDF_DIR', pdf_dir)
    # Disable SynologyDrive archiving so the test has no network dep.
    monkeypatch.setattr(
        facturen_module, 'archive_factuur_pdf',
        lambda *a, **kw: None)

    await _seed_bg(db)
    kid = await add_klant(db, naam='SmokeTest', tarief_uur=80)
    wid = await add_werkdag(db, datum='2026-05-01', klant_id=kid,
                             uren=8, tarief=80, km=0)
    fid = await add_factuur(db, nummer='2026-SMK1', klant_id=kid,
                             datum='2026-05-01', totaal_bedrag=640,
                             status='concept')
    await link_werkdagen_to_factuur(db, werkdag_ids=[wid],
                                     factuurnummer='2026-SMK1')

    row = {'id': fid, 'nummer': '2026-SMK1', 'klant_id': kid,
           'datum': '2026-05-01', 'type': 'factuur',
           'pdf_pad': ''}
    pdf_path = await facturen_module._regenerate_factuur_pdf(row)
    assert pdf_path is not None
    assert pdf_path.exists()
    assert pdf_path.suffix == '.pdf'

    # DB pdf_pad got updated.
    async with aiosqlite.connect(db) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT pdf_pad FROM facturen WHERE id = ?", (fid,))
        db_row = await cur.fetchone()
    assert db_row['pdf_pad'] == str(pdf_path)
