"""Tests for components.mail_helper.

The helper builds a JSON payload and shells out to `mail_compose_helper.py`
which invokes NSSharingService. We mock the subprocess so we can assert
the payload shape without actually opening Mail.app compose windows.
"""
import json
import subprocess
from unittest.mock import patch, MagicMock

from components.mail_helper import open_mail_with_attachment


def _fake_cp(returncode=0, stdout=b'', stderr=b''):
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


def test_open_mail_passes_payload_as_stdin_json():
    with patch('components.mail_helper.subprocess.run') as run:
        run.return_value = _fake_cp()
        result = open_mail_with_attachment(
            to='klant@example.nl',
            subject='Factuur 2026-001',
            body_html='<p>Hoi <a href="https://x/">deze link</a></p>',
            attachment_path='/tmp/factuur.pdf',
        )
    assert result.returncode == 0
    # One subprocess call with stdin bytes containing our JSON payload
    assert run.call_count == 1
    kwargs = run.call_args.kwargs
    payload = json.loads(kwargs['input'].decode('utf-8'))
    assert payload == {
        'to': 'klant@example.nl',
        'subject': 'Factuur 2026-001',
        'body_html': '<p>Hoi <a href="https://x/">deze link</a></p>',
        'attachment_path': '/tmp/factuur.pdf',
    }
    # Stderr/stdout must be captured so callers can surface errors.
    assert kwargs['capture_output'] is True


def test_open_mail_default_timeout_is_reasonable():
    """Compose-window spawn should not hang the UI if Mail.app is unresponsive."""
    with patch('components.mail_helper.subprocess.run') as run:
        run.return_value = _fake_cp()
        open_mail_with_attachment(
            to='x@y.nl', subject='s', body_html='<p>b</p>',
            attachment_path='/tmp/x.pdf',
        )
    assert run.call_args.kwargs['timeout'] <= 30


def test_open_mail_surfaces_nonzero_returncode():
    """When the helper fails, we return the CompletedProcess so callers
    can inspect stderr and notify the user."""
    with patch('components.mail_helper.subprocess.run') as run:
        run.return_value = _fake_cp(
            returncode=5, stderr=b'mail_compose_helper: share service rejects items')
        result = open_mail_with_attachment(
            to='x@y.nl', subject='s', body_html='<p>b</p>',
            attachment_path='/missing.pdf',
        )
    assert result.returncode == 5
    assert b'share service rejects items' in result.stderr


# ============================================================
# _ensure_utf8_html — UTF-8 meta wrapper (fixes "â,¬" mojibake)
# ============================================================

def test_ensure_utf8_html_wraps_fragment_without_meta():
    """NSAttributedString defaults to Windows-1252 without an explicit
    charset. Wrapping an HTML fragment with a UTF-8 <meta> makes "€"
    render correctly instead of "â‚¬"."""
    from components.mail_compose_helper import _ensure_utf8_html
    wrapped = _ensure_utf8_html('<p>Bedrag € 754,92</p>')
    assert 'charset=UTF-8' in wrapped
    assert '€' in wrapped  # literal euro still there, untouched
    assert '<p>Bedrag € 754,92</p>' in wrapped


def test_ensure_utf8_html_is_idempotent_for_full_document():
    """If the caller already supplies an HTML document with a meta
    charset, we must not double-wrap it."""
    from components.mail_compose_helper import _ensure_utf8_html
    input_html = (
        '<!DOCTYPE html><html><head>'
        '<meta charset="UTF-8"></head>'
        '<body><p>€ 100</p></body></html>')
    assert _ensure_utf8_html(input_html) == input_html


def test_ensure_utf8_html_utf8_roundtrips_euro_byte_sequence():
    """End-to-end guard: wrapping + UTF-8 encode yields the canonical
    E2 82 AC byte sequence for "€" — which is what NSAttributedString
    with the meta tag present decodes back to U+20AC."""
    from components.mail_compose_helper import _ensure_utf8_html
    wrapped = _ensure_utf8_html('<p>€ 754,92</p>')
    encoded = wrapped.encode('utf-8')
    assert b'\xe2\x82\xac' in encoded
    # The OLD bug: if these bytes were decoded as Windows-1252, the user
    # would see "â‚¬" in Mail. With the meta tag, Cocoa reads UTF-8.
