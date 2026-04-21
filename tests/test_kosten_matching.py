"""find_pdf_matches_for_banktx — tegenpartij token + (optional) bedrag match."""
import aiosqlite
import pytest
from database import find_pdf_matches_for_banktx


async def _seed_banktx(db_path, id_, datum, bedrag, tegenpartij):
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO banktransacties (id, datum, bedrag, tegenpartij) "
            "VALUES (?, ?, ?, ?)",
            (id_, datum, bedrag, tegenpartij))
        await conn.commit()


def _mock_archive(tmp_path, files: list[tuple[str, str]]) -> None:
    """files: list of (folder, filename). Creates empty PDFs directly under
    the monkeypatched ARCHIVE_BASE: tmp_path/{year}/Uitgaven/{folder}/.
    """
    for folder, fname in files:
        d = tmp_path / "2026" / "Uitgaven" / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_bytes(b"%PDF-1.4\n")


@pytest.mark.asyncio
async def test_match_returns_high_confidence_tegenpartij_hit(db, tmp_path,
                                                              monkeypatch):
    from components import archive_paths
    monkeypatch.setattr(archive_paths, "ARCHIVE_BASE", tmp_path)
    _mock_archive(tmp_path, [("KPN", "2026-04-01_KPN_abo.pdf")])
    await _seed_banktx(db, 1, "2026-04-01", -120.87, "KPN B.V.")
    matches = await find_pdf_matches_for_banktx(db, 1, jaar=2026)
    assert len(matches) >= 1
    assert matches[0].filename == "2026-04-01_KPN_abo.pdf"
    assert matches[0].categorie == "Telefoon/KPN"


@pytest.mark.asyncio
async def test_match_returns_empty_when_no_overlap(db, tmp_path, monkeypatch):
    from components import archive_paths
    monkeypatch.setattr(archive_paths, "ARCHIVE_BASE", tmp_path)
    _mock_archive(tmp_path, [("KPN", "2026-04-01_KPN_abo.pdf")])
    await _seed_banktx(db, 1, "2026-04-01", -50.00, "Shell Nederland")
    matches = await find_pdf_matches_for_banktx(db, 1, jaar=2026)
    assert matches == []


@pytest.mark.asyncio
async def test_match_ignores_unknown_bank_tx(db):
    with pytest.raises(ValueError):
        await find_pdf_matches_for_banktx(db, 999, jaar=2026)


@pytest.mark.asyncio
async def test_match_multiple_returns_sorted(db, tmp_path, monkeypatch):
    from components import archive_paths
    monkeypatch.setattr(archive_paths, "ARCHIVE_BASE", tmp_path)
    _mock_archive(tmp_path, [
        ("KPN", "2026-04-01_KPN_abo.pdf"),
        ("KPN", "2026-03-01_kpn_internet.pdf"),
    ])
    await _seed_banktx(db, 1, "2026-04-01", -120.87, "KPN B.V.")
    matches = await find_pdf_matches_for_banktx(db, 1, jaar=2026)
    assert len(matches) == 2


@pytest.mark.asyncio
async def test_find_banktx_match_returns_unmatched_only(db):
    import aiosqlite
    from database import (find_banktx_matches_for_pdf,
                          ensure_uitgave_for_banktx)
    async with aiosqlite.connect(db) as conn:
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij) VALUES (1, ?, ?, ?)",
            ("2026-04-01", -120.87, "KPN B.V."))
        await conn.execute(
            "INSERT INTO banktransacties "
            "(id, datum, bedrag, tegenpartij) VALUES (2, ?, ?, ?)",
            ("2026-04-01", -120.87, "KPN B.V."))
        await conn.commit()
    # Link the first one
    await ensure_uitgave_for_banktx(db, 1)
    hits = await find_banktx_matches_for_pdf(
        db, "2026-04-01_KPN_abo.pdf", 2026)
    ids = [h[0] for h in hits]
    assert 1 not in ids
    assert 2 in ids
