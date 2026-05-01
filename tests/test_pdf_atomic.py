"""Tests voor write_pdf_atomic helper (components/utils.py).

K2 review: bestaande PDF mag niet corrupt worden bij WeasyPrint-crash mid-write.
Atomair patroon: write naar .tmp, dan os.replace. Bij crash: .tmp opgeruimd,
bestaande PDF intact.
"""
import os
from pathlib import Path

import pytest

from components.utils import write_pdf_atomic


class TestWritePdfAtomic:

    @pytest.mark.asyncio
    async def test_writes_pdf_happy_path(self, tmp_path):
        """Schrijven van een geldig HTML naar PDF werkt."""
        out = tmp_path / 'out.pdf'
        html = '<html><body><h1>Hello</h1></body></html>'
        await write_pdf_atomic(html, out)
        assert out.exists()
        assert out.read_bytes()[:4] == b'%PDF'

    @pytest.mark.asyncio
    async def test_keeps_existing_pdf_on_render_failure(
            self, tmp_path, monkeypatch):
        """Als WeasyPrint mid-render crasht, blijft de bestaande PDF intact."""
        out = tmp_path / 'out.pdf'
        original = b'%PDF-1.4 ORIGINAL CONTENT'
        out.write_bytes(original)

        # Monkeypatch HTML().write_pdf to fail
        from weasyprint import HTML

        def boom(*args, **kwargs):
            raise RuntimeError("simulated weasyprint crash")

        monkeypatch.setattr(HTML, 'write_pdf', boom)

        with pytest.raises(RuntimeError):
            await write_pdf_atomic('<html/>', out)

        # Original moet nog steeds intact zijn
        assert out.read_bytes() == original

    @pytest.mark.asyncio
    async def test_cleans_tmp_on_replace_failure(self, tmp_path, monkeypatch):
        """Als os.replace faalt na succesvolle render, wordt .tmp opgeruimd."""
        out = tmp_path / 'out.pdf'

        def boom_replace(src, dst):  # noqa: ARG001
            raise OSError("simulated replace failure")

        monkeypatch.setattr(os, 'replace', boom_replace)

        with pytest.raises(OSError):
            await write_pdf_atomic(
                '<html><body>x</body></html>', out)

        leftovers = list(tmp_path.glob('*.tmp'))
        assert leftovers == []
