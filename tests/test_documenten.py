"""Tests voor pages/documenten.py — upload safety, atomicity, collision.

Verzekert dat upload-flows in /documenten en /aangifte:
- Path-traversal afwijzen (file naam mag geen '..' / '/' / '\\' bevatten)
- Leading dot-files afwijzen (bijv. '.env.pdf' niet stilzwijgend strippen)
- NUL bytes en lege strings afwijzen
- Alleen toegestane extensies accepteren (pdf, jpg, jpeg, png)
- Atomair schrijven (write-then-rename) met cleanup op crash
- Collision-suffix (_2.pdf, _3.pdf) bij gelijke naam met andere content
- Idempotent (zelfde naam + zelfde content → geen 2e write)
- Year-lock preflight + cleanup-on-DB-fail
"""
import os
from pathlib import Path

import pytest

from pages.documenten import _safe_documenten_basename, _safe_atomic_write


class TestSafeDocumentenBasename:
    """Loud-fail filename sanitization. Geen silent stripping."""

    def test_accepts_clean_pdf(self):
        assert _safe_documenten_basename('hypotheek.pdf') == 'hypotheek.pdf'

    def test_accepts_clean_jpg(self):
        assert _safe_documenten_basename('foto.jpg') == 'foto.jpg'

    def test_accepts_clean_jpeg(self):
        assert _safe_documenten_basename('scan.jpeg') == 'scan.jpeg'

    def test_accepts_clean_png(self):
        assert _safe_documenten_basename('screenshot.png') == 'screenshot.png'

    def test_rejects_path_traversal_dotdot(self):
        with pytest.raises(ValueError):
            _safe_documenten_basename('../../etc/passwd.pdf')

    def test_rejects_forward_slash(self):
        with pytest.raises(ValueError):
            _safe_documenten_basename('foo/bar.pdf')

    def test_rejects_backslash(self):
        with pytest.raises(ValueError):
            _safe_documenten_basename('foo\\bar.pdf')

    def test_rejects_null_byte(self):
        with pytest.raises(ValueError):
            _safe_documenten_basename('foo\x00.pdf')

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError):
            _safe_documenten_basename('')

    def test_rejects_disallowed_extension(self):
        with pytest.raises(ValueError):
            _safe_documenten_basename('script.exe')

    def test_rejects_leading_dot(self):
        # Codex round-4 push: '.env.pdf' niet stilzwijgend strippen naar
        # 'env.pdf' — reject loud zodat user de fout ziet.
        with pytest.raises(ValueError):
            _safe_documenten_basename('.env.pdf')


class TestSafeAtomicWrite:
    """Atomic write with collision + idempotent + cleanup-on-failure."""

    @pytest.mark.asyncio
    async def test_creates_new_file(self, tmp_path):
        p, is_new = await _safe_atomic_write(tmp_path, 'a.pdf', b'hello')
        assert is_new is True
        assert p == tmp_path / 'a.pdf'
        assert p.read_bytes() == b'hello'

    @pytest.mark.asyncio
    async def test_idempotent_same_content_returns_existing(self, tmp_path):
        p1, new1 = await _safe_atomic_write(tmp_path, 'a.pdf', b'hello')
        p2, new2 = await _safe_atomic_write(tmp_path, 'a.pdf', b'hello')
        assert p1 == p2
        assert new1 is True
        assert new2 is False

    @pytest.mark.asyncio
    async def test_collision_different_content_uses_suffix(self, tmp_path):
        p1, new1 = await _safe_atomic_write(tmp_path, 'a.pdf', b'first')
        p2, new2 = await _safe_atomic_write(tmp_path, 'a.pdf', b'second')
        assert p1 == tmp_path / 'a.pdf'
        assert p2 == tmp_path / 'a_2.pdf'
        assert new1 is True
        assert new2 is True
        assert p1.read_bytes() == b'first'
        assert p2.read_bytes() == b'second'

    @pytest.mark.asyncio
    async def test_collision_then_idempotent_routes_to_existing_match(
            self, tmp_path):
        # Codex round-4: 3rd upload met content van A.pdf moet A.pdf
        # terugvinden, niet A_3.pdf creëren.
        await _safe_atomic_write(tmp_path, 'a.pdf', b'first')
        await _safe_atomic_write(tmp_path, 'a.pdf', b'second')
        p3, new3 = await _safe_atomic_write(tmp_path, 'a.pdf', b'first')
        assert p3 == tmp_path / 'a.pdf'
        assert new3 is False

    @pytest.mark.asyncio
    async def test_cleans_tmp_on_replace_failure(self, tmp_path, monkeypatch):
        """Als os.replace faalt, moet de .tmp file opgeruimd zijn."""
        def boom(src, dst):  # noqa: ARG001 (dst unused — simulating failure)
            assert Path(src).exists()
            raise OSError("simulated failure")

        monkeypatch.setattr(os, 'replace', boom)

        with pytest.raises(OSError):
            await _safe_atomic_write(tmp_path, 'a.pdf', b'hello')

        leftovers = list(tmp_path.glob('*.tmp'))
        assert leftovers == []


class TestDocumentenIntegration:
    """End-to-end via DB: bewijst dat add_aangifte_document YearLockedError
    raises voor een definitief jaar — zodat de 4-step upload-flow zijn
    cleanup-pad kan triggeren in productie."""

    @pytest.mark.asyncio
    async def test_year_locked_year_raises(self, tmp_path, monkeypatch):
        """add_aangifte_document moet YearLockedError raisen voor locked jaar.

        Hergebruikt het bestaande test_year_locking.py-patroon:
        - direct minimale INSERT in fiscale_params (jaar)
        - update_jaarafsluiting_status positional (db, jaar, status)
        """
        import aiosqlite
        from database import (
            YearLockedError, add_aangifte_document,
            update_jaarafsluiting_status, init_db,
        )
        # Setup tmp DB
        db = tmp_path / 'test.db'
        monkeypatch.setattr('database.DB_PATH', db)
        await init_db(db)

        # Cruciaal: maak fiscale_params row vóór status-lock — anders raakt
        # de UPDATE 0 rows en is de "lock" een silent no-op.
        async with aiosqlite.connect(db) as conn:
            await conn.execute(
                "INSERT INTO fiscale_params (jaar) VALUES (?)", (2024,))
            await conn.commit()

        # Lock 2024
        result = await update_jaarafsluiting_status(db, 2024, 'definitief')
        assert result is True, "update_jaarafsluiting_status must return True"

        # Try to add doc to 2024 → moet YearLockedError raisen
        with pytest.raises(YearLockedError):
            await add_aangifte_document(
                db, jaar=2024,
                categorie='WOZ', documenttype='woz_beschikking',
                bestandsnaam='woz.pdf', bestandspad='/tmp/woz.pdf',
                upload_datum='2024-12-01')
