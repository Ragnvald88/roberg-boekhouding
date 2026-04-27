"""Archive-to-SynologyDrive logic for facturen.

Covers:
- archive_paths.jaar_dir helper
- archive_factuur_pdf with optional archive_filename override
- import-flow archives uploaded factuur PDFs (was missing — Bevinding 1)
- expense scan path includes 'Inkomen en Uitgaven' segment (Bevinding 2)
"""

from pathlib import Path


# ============================================================
# jaar_dir helper
# ============================================================


def test_jaar_dir_resolves_under_inkomen_en_uitgaven():
    from components.archive_paths import ARCHIVE_BASE, jaar_dir
    assert jaar_dir(2025) == ARCHIVE_BASE / 'Inkomen en Uitgaven' / '2025'


def test_jaar_dir_accepts_int_or_str():
    from components.archive_paths import jaar_dir
    assert jaar_dir(2025) == jaar_dir('2025')


# ============================================================
# archive_factuur_pdf with archive_filename
# ============================================================


def test_archive_uses_pdf_basename_when_no_override(tmp_path, monkeypatch):
    """Backwards-compat: existing callers (no archive_filename) keep
    using pdf_path.name as the destination basename."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    src = tmp_path / 'src' / '2025-001_Klant7.pdf'
    src.parent.mkdir()
    src.write_bytes(b'%PDF-1.4\n')

    result = archive_factuur_pdf(
        src, factuur_type='factuur', factuur_datum='2025-03-15')

    expected = (tmp_path / 'Inkomen en Uitgaven' / '2025'
                / 'Inkomsten' / 'Dagpraktijk' / '2025-001_Klant7.pdf')
    assert result == expected
    assert expected.exists()


def test_archive_filename_override_used_when_supplied(tmp_path, monkeypatch):
    """Imported factuur preserves user's original upload filename rather
    than the app's local-storage `{nummer}.pdf` form."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    # Local app storage uses {nummer}.pdf for collision-safety:
    src = tmp_path / 'data' / '2024-042.pdf'
    src.parent.mkdir()
    src.write_bytes(b'%PDF-1.4\n')

    result = archive_factuur_pdf(
        src, factuur_type='anw', factuur_datum='2024-02-10',
        archive_filename='0224_HAP_Drenthe.pdf')

    expected = (tmp_path / 'Inkomen en Uitgaven' / '2024'
                / 'Inkomsten' / 'ANW_Diensten' / '0224_HAP_Drenthe.pdf')
    assert result == expected
    assert expected.exists()


def test_archive_anw_lands_in_anw_diensten(tmp_path, monkeypatch):
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    src = tmp_path / 'src' / 'in.pdf'
    src.parent.mkdir()
    src.write_bytes(b'%PDF-1.4\n')

    result = archive_factuur_pdf(
        src, factuur_type='anw', factuur_datum='2026-01-15')

    assert result is not None
    assert (result.parent.name == 'ANW_Diensten'
            and result.parent.parent.name == 'Inkomsten')


def test_archive_vergoeding_lands_in_inkomsten_root(tmp_path, monkeypatch):
    """vergoeding type writes to Inkomsten/ flat (matches user pattern of
    e.g. 2026-027_Zwart.pdf at the root)."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    src = tmp_path / 'src' / 'verg.pdf'
    src.parent.mkdir()
    src.write_bytes(b'%PDF-1.4\n')

    result = archive_factuur_pdf(
        src, factuur_type='vergoeding', factuur_datum='2026-04-01',
        archive_filename='2026-027_Zwart.pdf')

    expected = (tmp_path / 'Inkomen en Uitgaven' / '2026'
                / 'Inkomsten' / '2026-027_Zwart.pdf')
    assert result == expected
    assert expected.exists()


def test_archive_filename_strips_path_traversal(tmp_path, monkeypatch):
    """Untrusted upload name containing '../' must not escape target_dir.
    `Path(name).name` reduces the input to its basename component."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    src = tmp_path / 'src' / 'in.pdf'
    src.parent.mkdir()
    src.write_bytes(b'%PDF-1.4\n')

    # Hostile name attempting to write outside target dir:
    result = archive_factuur_pdf(
        src, factuur_type='factuur', factuur_datum='2025-03-15',
        archive_filename='../../etc/passwd.pdf')

    assert result is not None
    # Result must be inside the expected target dir, regardless of
    # what was attempted in archive_filename:
    expected_dir = (tmp_path / 'Inkomen en Uitgaven' / '2025'
                    / 'Inkomsten' / 'Dagpraktijk')
    assert result.parent == expected_dir
    assert result.name == 'passwd.pdf'  # basename only — no traversal


def test_archive_filename_falls_back_when_basename_empty(
        tmp_path, monkeypatch):
    """archive_filename='..' or '.' or '' degenerates into an empty
    basename — fall back to pdf_path.name to avoid writing to a dir."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    src = tmp_path / 'src' / 'fallback.pdf'
    src.parent.mkdir()
    src.write_bytes(b'%PDF-1.4\n')

    for hostile in ('', '.', '..', '/'):
        result = archive_factuur_pdf(
            src, factuur_type='factuur', factuur_datum='2025-04-01',
            archive_filename=hostile)
        assert result is not None
        assert result.name == 'fallback.pdf'


def test_archive_skips_silent_overwrite_when_identical(
        tmp_path, monkeypatch):
    """Idempotent re-import: identical content under same archive
    filename returns the existing target without rewriting."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    src = tmp_path / 'src' / 'a.pdf'
    src.parent.mkdir()
    src.write_bytes(b'%PDF-1.4\nIDENTICAL CONTENT')

    first = archive_factuur_pdf(
        src, factuur_type='anw', factuur_datum='2024-02-15',
        archive_filename='0224_HAP.pdf')
    assert first is not None
    first_mtime = first.stat().st_mtime_ns

    # Re-archive identical content — should NOT rewrite (mtime stable):
    second = archive_factuur_pdf(
        src, factuur_type='anw', factuur_datum='2024-02-15',
        archive_filename='0224_HAP.pdf')
    assert second == first
    assert second.stat().st_mtime_ns == first_mtime  # not overwritten


def test_archive_suffixes_when_different_content_same_name(
        tmp_path, monkeypatch):
    """Two HAP uploads with the same filename but different content
    must NOT silently overwrite — second gets `_2` suffix."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    src1 = tmp_path / 'src' / 'first.pdf'
    src1.parent.mkdir()
    src1.write_bytes(b'%PDF-1.4\nFIRST UPLOAD')

    src2 = tmp_path / 'src' / 'second.pdf'
    src2.write_bytes(b'%PDF-1.4\nSECOND UPLOAD')

    r1 = archive_factuur_pdf(
        src1, factuur_type='anw', factuur_datum='2024-04-01',
        archive_filename='0424_HAP.pdf')
    r2 = archive_factuur_pdf(
        src2, factuur_type='anw', factuur_datum='2024-04-01',
        archive_filename='0424_HAP.pdf')

    assert r1 is not None and r2 is not None
    assert r1.name == '0424_HAP.pdf'
    assert r2.name == '0424_HAP_2.pdf'  # suffix avoids overwrite
    assert r1.read_bytes() == b'%PDF-1.4\nFIRST UPLOAD'
    assert r2.read_bytes() == b'%PDF-1.4\nSECOND UPLOAD'


def test_archive_suffix_continues_past_n2(tmp_path, monkeypatch):
    """If `_2` is also taken with different content, fall through to `_3`."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    src1 = tmp_path / 's1.pdf'
    src1.write_bytes(b'A')
    src2 = tmp_path / 's2.pdf'
    src2.write_bytes(b'B')
    src3 = tmp_path / 's3.pdf'
    src3.write_bytes(b'C')

    r1 = archive_factuur_pdf(
        src1, factuur_type='factuur', factuur_datum='2025-06-01',
        archive_filename='dup.pdf')
    r2 = archive_factuur_pdf(
        src2, factuur_type='factuur', factuur_datum='2025-06-01',
        archive_filename='dup.pdf')
    r3 = archive_factuur_pdf(
        src3, factuur_type='factuur', factuur_datum='2025-06-01',
        archive_filename='dup.pdf')

    assert r1.name == 'dup.pdf'
    assert r2.name == 'dup_2.pdf'
    assert r3.name == 'dup_3.pdf'


def test_archive_skips_when_existing_suffix_has_identical_content(
        tmp_path, monkeypatch):
    """G1: re-importing the same batch twice. First time creates
    `dup.pdf` (content A) + `dup_2.pdf` (content B). Re-import of
    content B should NOT create `dup_3.pdf` since `dup_2.pdf` already
    holds identical bytes."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    src_a = tmp_path / 'a.pdf'
    src_a.write_bytes(b'CONTENT_A')
    src_b = tmp_path / 'b.pdf'
    src_b.write_bytes(b'CONTENT_B')

    archive_factuur_pdf(
        src_a, factuur_type='factuur', factuur_datum='2025-07-01',
        archive_filename='dup.pdf')
    archive_factuur_pdf(
        src_b, factuur_type='factuur', factuur_datum='2025-07-01',
        archive_filename='dup.pdf')

    # Re-import of B should land on the existing dup_2.pdf, not dup_3:
    target_dir = (tmp_path / 'Inkomen en Uitgaven' / '2025'
                  / 'Inkomsten' / 'Dagpraktijk')
    third = archive_factuur_pdf(
        src_b, factuur_type='factuur', factuur_datum='2025-07-01',
        archive_filename='dup.pdf')

    assert third is not None
    assert third.name == 'dup_2.pdf'  # idempotent — no _3 created
    assert not (target_dir / 'dup_3.pdf').exists()


def test_archive_rejects_embedded_nul_byte(tmp_path, monkeypatch):
    """G3: archive_filename containing \\x00 must not crash with
    ValueError from shutil.copy2 — basename helper falls back to the
    local pdf_path.name."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    src = tmp_path / 'src' / 'fallback.pdf'
    src.parent.mkdir()
    src.write_bytes(b'%PDF-1.4\n')

    # Embedded NUL in the upload name — common in fuzzing tools, rare
    # in real life but a real source of "exception bubbled to UI":
    result = archive_factuur_pdf(
        src, factuur_type='factuur', factuur_datum='2025-08-01',
        archive_filename='evil\x00name.pdf')

    assert result is not None
    assert result.name == 'fallback.pdf'  # NUL filtered → fallback
    assert '\x00' not in str(result)


def test_archive_rejects_dangling_symlink_target(tmp_path, monkeypatch):
    """G4: a pre-existing dangling symlink at the target path must be
    treated as 'taken', not as 'free' (Path.exists returns False for
    dangling symlinks)."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    src = tmp_path / 'src' / 'symlink_test.pdf'
    src.parent.mkdir()
    src.write_bytes(b'%PDF-1.4\nNEW CONTENT')

    target_dir = (tmp_path / 'Inkomen en Uitgaven' / '2025'
                  / 'Inkomsten' / 'Dagpraktijk')
    target_dir.mkdir(parents=True)
    # Create a dangling symlink at the would-be target path:
    target_link = target_dir / 'will_be_dangling.pdf'
    target_link.symlink_to(tmp_path / 'nonexistent_destination.pdf')
    assert target_link.is_symlink()
    assert not target_link.exists()  # dangling — Path.exists returns False

    # Without the lexists guard, copy2 would follow the symlink and
    # write to nonexistent_destination.pdf (outside target_dir).
    result = archive_factuur_pdf(
        src, factuur_type='factuur', factuur_datum='2025-09-01',
        archive_filename='will_be_dangling.pdf')

    assert result is not None
    # Result must NOT be the symlink path — should suffix to _2:
    assert result.name == 'will_be_dangling_2.pdf'
    # Symlink-followed write to outside target_dir would have created
    # this — verify it didn't:
    assert not (tmp_path / 'nonexistent_destination.pdf').exists()


def test_archive_returns_none_when_source_missing(tmp_path, monkeypatch):
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)
    from components.invoice_generator import archive_factuur_pdf

    missing = tmp_path / 'nope.pdf'
    result = archive_factuur_pdf(
        missing, factuur_type='factuur', factuur_datum='2025-03-15')
    assert result is None


# ============================================================
# scan_archive uses jaar_dir (Bevinding 2 fix)
# ============================================================


def test_scan_archive_reads_from_inkomen_en_uitgaven_subpath(
        tmp_path, monkeypatch):
    """Pre-fix bug: scan_archive looked at ARCHIVE_BASE/{year}/Uitgaven,
    skipping the 'Inkomen en Uitgaven' segment, so the user's actual
    archive was never seen. This test pins the corrected layout."""
    from components import archive_paths
    monkeypatch.setattr(archive_paths, 'ARCHIVE_BASE', tmp_path)

    # Place a pdf in the CORRECT location:
    correct = (tmp_path / 'Inkomen en Uitgaven' / '2026'
               / 'Uitgaven' / 'KPN' / '0126_KPN.pdf')
    correct.parent.mkdir(parents=True)
    correct.write_bytes(b'%PDF-1.4\n')

    # Place a decoy in the OLD (buggy) location to ensure the fix
    # doesn't accidentally read both:
    decoy = (tmp_path / '2026' / 'Uitgaven' / 'KPN' / '_decoy.pdf')
    decoy.parent.mkdir(parents=True)
    decoy.write_bytes(b'%PDF-1.4\n')

    from import_.expense_utils import scan_archive
    results = scan_archive(2026)

    filenames = {r['filename'] for r in results}
    assert '0126_KPN.pdf' in filenames
    assert '_decoy.pdf' not in filenames


# ============================================================
# Import flow archives uploaded factuur (Bevinding 1 fix)
#
# The import-loop in pages/facturen.py is wrapped in a NiceGUI handler
# that's hard to drive without a UI runtime. Source-pin: assert that
# the import-loop body explicitly calls archive_factuur_pdf with the
# user's original filename.
# ============================================================


def test_import_loop_archives_with_original_filename():
    """pages/facturen.py import-loop must call archive_factuur_pdf
    with archive_filename derived from item['_filename'] so the upload
    lands in the SynologyDrive archive under the user's filename."""
    src = Path(__file__).resolve().parent.parent / 'pages' / 'facturen.py'
    text = src.read_text()
    # The import-flow archive call has a distinctive signature:
    assert 'archive_factuur_pdf' in text
    # archive_filename derived from _filename with pdf_dest.name fallback
    assert "archive_filename=orig_filename" in text or (
        "archive_filename" in text and "_filename" in text)


def test_import_loop_archives_only_when_local_pdf_exists():
    """The import-flow must guard archive_factuur_pdf behind
    pdf_dest.exists() so an upload that didn't carry _content (rare,
    but possible) doesn't trigger an archive call on a missing source."""
    src = Path(__file__).resolve().parent.parent / 'pages' / 'facturen.py'
    lines = src.read_text().splitlines()
    # At least one archive_factuur_pdf call site in this file must be
    # preceded within ~12 lines by a `pdf_dest.exists()` guard so a
    # parsed-only-no-content upload doesn't trigger an archive on a
    # missing source.
    found_guard = False
    for i, line in enumerate(lines):
        if 'archive_factuur_pdf' in line:
            window = '\n'.join(lines[max(0, i - 12):i])
            if 'pdf_dest.exists()' in window:
                found_guard = True
                break
    assert found_guard, (
        "Import-flow archive_factuur_pdf call should be guarded by "
        "`if pdf_dest.exists():` (or equivalent) within ~12 lines.")
