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
